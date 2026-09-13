"""Dense-embedder bake-off: arctic-embed-m vs codet5p-110m-embedding.

For each DeepSWE task: embed instruction.md as the query and every source file
in the repo@base_commit as passages, then measure recall@K of the gold patch
file set. Both models see identical corpus and chunking; arctic gets its
Snowflake query prefix; codet5p encodes raw.

Outputs results.jsonl (one row per task) + a summary table.
"""

import io
import json
import re
import tarfile
import time
import urllib.request
from pathlib import Path

import numpy as np

def _arg(name: str, default: str) -> str:
    import sys
    flag = f"--{name}"
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


TASKS_ROOT = Path(_arg("tasks-root", r"D:\gt-harness\.tmp_deepswe\tasks"))
OUT = Path(_arg("out", str(Path(__file__).parent / "results.jsonl")))
REPO_CACHE = Path(_arg("repos", str(Path(__file__).parent / "repos")))
ONLY_TASK = _arg("task", "")
ONLY_MODEL = _arg("model", "")

TASKS = [
    "abs-module-cache-flags",
    "adaptix-name-mapping-aliases",
    "arktype-json-schema-refs-dependencies",
    "csstree-shorthand-expansion-compression",
    "boa-hierarchical-evaluation-cancellation",
    "abs-stepped-slices",
    "aiomonitor-task-snapshots-diff",
    "awilix-async-container-initialization",
    "katex-multicolumn-array-spans",
    "fd-deterministic-multi-key-sorting",
]

SOURCE_EXTS = {
    ".py", ".pyi", ".go", ".rs", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx",
    ".rb", ".java", ".kt", ".kts", ".cs", ".php", ".swift", ".scala",
    ".c", ".h", ".cc", ".hh", ".cpp", ".hpp", ".m", ".mm", ".lua", ".ex",
    ".exs", ".erl", ".hs", ".ml", ".clj", ".dart", ".zig", ".sh",
    ".bash", ".cue", ".elm", ".css", ".groovy", ".gradle", ".html", ".htm",
    ".tf", ".hcl", ".proto", ".sql", ".svelte", ".cxx", ".hxx",
}
SKIP_DIRS = {".git", "node_modules", "vendor", "dist", "build", "target",
             "__pycache__", ".venv", "venv", "coverage", ".next"}
MAX_FILE_BYTES = 200_000
CHUNK_WORDS = 350
CHUNK_OVERLAP = 50
MAX_CHUNKS_PER_REPO = 6000
SNOWFLAKE_PREFIX = "Represent this sentence for searching relevant passages: "


def task_meta(task_dir: Path) -> dict:
    toml_text = (task_dir / "task.toml").read_text(encoding="utf-8")
    repo = re.search(r'repository_url\s*=\s*"([^"]+)"', toml_text).group(1)
    sha = re.search(r'base_commit_hash\s*=\s*"([^"]+)"', toml_text).group(1)
    patch = task_dir / "solution" / "solution.patch"
    gold = set()
    for line in patch.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"\+\+\+ b/(.+)", line) or re.match(r"diff --git a/\S+ b/(.+)", line)
        if m:
            gold.add(m.group(1).strip())
    query = (task_dir / "instruction.md").read_text(encoding="utf-8", errors="replace")
    return {"repo": repo, "sha": sha, "gold": gold, "query": query}


def fetch_repo(repo_url: str, sha: str, dest: Path) -> Path:
    if not dest.exists():
        dest.mkdir(parents=True, exist_ok=True)
        parts = repo_url.rstrip("/").replace(".git", "").split("/")
        owner, name = parts[-2], parts[-1]
        url = f"https://codeload.github.com/{owner}/{name}/tar.gz/{sha}"
        with urllib.request.urlopen(url, timeout=120) as resp:
            data = resp.read()
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
            tf.extractall(dest, filter="data")
    # tarballs nest under <name>-<sha>/ — flatten one level
    subs = [p for p in dest.iterdir() if p.is_dir()]
    if len(subs) == 1:
        return subs[0]
    return dest


def collect_chunks(repo_dir: Path):
    files, chunks = [], []
    for p in sorted(repo_dir.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in SOURCE_EXTS:
            continue
        if any(part in SKIP_DIRS for part in p.relative_to(repo_dir).parts):
            continue
        if p.stat().st_size > MAX_FILE_BYTES:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = str(p.relative_to(repo_dir)).replace("\\", "/")
        files.append(rel)
        words = text.split()
        if not words:
            chunks.append((rel, rel))
            continue
        step = max(1, CHUNK_WORDS - CHUNK_OVERLAP)
        for i in range(0, len(words), step):
            chunks.append((rel, " ".join(words[i:i + CHUNK_WORDS])))
    if len(chunks) > MAX_CHUNKS_PER_REPO:
        chunks = chunks[:MAX_CHUNKS_PER_REPO]
    return files, chunks


def l2norm(x: np.ndarray) -> np.ndarray:
    return x / np.clip(np.linalg.norm(x, axis=1, keepdims=True), 1e-12, None)


def embed(model, texts, is_query, batch=64):
    t0 = time.time()
    vecs = model.encode(list(texts), batch_size=batch, show_progress_bar=False,
                        convert_to_numpy=True, normalize_embeddings=True)
    return np.asarray(vecs, dtype=np.float32), (time.time() - t0) / max(1, len(texts))


class CodeT5pEncoder:
    """codet5p-110m-embedding returns [B, 256] embeddings directly."""

    def __init__(self):
        import torch
        from transformers import AutoModel, AutoTokenizer
        self._torch = torch
        self._tok = AutoTokenizer.from_pretrained(
            "Salesforce/codet5p-110m-embedding", trust_remote_code=True)
        self._model = AutoModel.from_pretrained(
            "Salesforce/codet5p-110m-embedding", trust_remote_code=True).eval()

    def encode(self, texts, batch_size=64, **_kw):
        torch = self._torch
        vecs = []
        for i in range(0, len(texts), batch_size):
            inp = self._tok(texts[i:i + batch_size], return_tensors="pt",
                            truncation=True, max_length=512, padding=True)
            with torch.no_grad():
                vecs.append(self._model(**inp).cpu().numpy())
        out = np.concatenate(vecs)
        return out / np.clip(np.linalg.norm(out, axis=1, keepdims=True), 1e-12, None)


def main() -> None:
    from sentence_transformers import SentenceTransformer

    print("loading models...", flush=True)
    builders = {
        "arctic_m": lambda: SentenceTransformer(
            "Snowflake/snowflake-arctic-embed-m", device="cpu"),
        "codet5p_110m": CodeT5pEncoder,
        "qodo_1_5b": lambda: SentenceTransformer(
            "Qodo/Qodo-Embed-1-1.5B", device="cpu", trust_remote_code=True),
    }
    names = [ONLY_MODEL] if ONLY_MODEL else list(builders)
    models = {n: builders[n]() for n in names}

    REPO_CACHE.mkdir(parents=True, exist_ok=True)
    task_list = [ONLY_TASK] if ONLY_TASK else TASKS
    with OUT.open("a", encoding="utf-8") as out:
        for task in task_list:
            meta = task_meta(TASKS_ROOT / task)
            dest = REPO_CACHE / task
            repo_dir = fetch_repo(meta["repo"], meta["sha"], dest)
            files, chunks = collect_chunks(repo_dir)
            file_set = set(files)
            gold = sorted(g for g in meta["gold"] if g in file_set)
            if not chunks or not gold:
                print(f"{task}: SKIP chunks={len(chunks)} gold={len(gold)}", flush=True)
                continue
            row = {"task": task, "files": len(files), "chunks": len(chunks),
                   "gold": len(gold)}
            for name, model in models.items():
                q = meta["query"]
                if name == "arctic_m":
                    q = SNOWFLAKE_PREFIX + q
                qv, qt = embed(model, [q], is_query=True)
                cv, ct = embed(model, [c for _, c in chunks], is_query=False)
                sims = l2norm(qv.astype(np.float32)) @ cv.T
                chunk_score = sims[0]
                best = {}
                for (rel, _), s in zip(chunks, chunk_score):
                    if rel not in best or s > best[rel]:
                        best[rel] = float(s)
                ranked = sorted(best, key=best.get, reverse=True)
                ranks = {f: i for i, f in enumerate(ranked)}
                gold_ranks = sorted(ranks[g] for g in gold if g in ranks)
                row[name] = {
                    "recall@10": sum(r < 10 for r in gold_ranks) / len(gold),
                    "recall@20": sum(r < 20 for r in gold_ranks) / len(gold),
                    "recall@50": sum(r < 50 for r in gold_ranks) / len(gold),
                    "best_gold_rank": gold_ranks[0] if gold_ranks else None,
                    "ms_per_chunk": round(ct * 1000, 1),
                }
                print(f"{task} {name}: r@20={row[name]['recall@20']:.2f} "
                      f"best={gold_ranks[0] if gold_ranks else '-'} "
                      f"({row[name]['ms_per_chunk']}ms/chunk)", flush=True)
            out.write(json.dumps(row) + "\n")
            out.flush()


if __name__ == "__main__":
    main()
