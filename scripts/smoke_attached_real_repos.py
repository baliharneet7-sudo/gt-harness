"""Provider-free smoke of attached delivery on real DeepSWE repositories.

For each task: clone the repository at the task's base commit, index it with a
gt-index binary, bind a MiniSweAdapter + GTSession exactly as the runtime does,
then run every ``gt-*`` tool and the grep augmentation. Tool arguments are
derived from the graph itself (the most-called non-test functions), never
hand-picked, so the report measures what an agent would plausibly ask for.
No model or provider is involved.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import statistics
import subprocess
import sys
import time
import tomllib
from pathlib import Path
from typing import Any

DEFAULT_TASKS = (
    "adaptix-name-mapping-aliases",
    "aiomonitor-task-snapshots-diff",
    "awilix-async-container-initialization",
    "abs-module-cache-flags",
    "fd-deterministic-multi-key-sorting",
    "csstree-shorthand-expansion-compression",
)
_TOP_SYMBOLS = 5
_CALLABLE_LABELS = ("Function", "Method")


def _git(*args: str, cwd: Path | None = None, timeout: int = 900) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, timeout=timeout)


def checkout(url: str, commit: str, dest: Path) -> None:
    if (dest / ".git").is_dir():
        return
    dest.mkdir(parents=True, exist_ok=True)
    _git("init", "-q", cwd=dest)
    _git("remote", "add", "origin", url, cwd=dest)
    _git("fetch", "-q", "--depth", "1", "origin", commit, cwd=dest)
    _git("checkout", "-q", "FETCH_HEAD", cwd=dest)


def build_info(binary: str) -> dict[str, Any]:
    done = subprocess.run([binary, "-build-info"], capture_output=True, timeout=60)
    try:
        return json.loads(done.stdout.decode("utf-8"))
    except ValueError:
        return {}


def index(binary: str, root: Path, graph: Path, revision: str) -> float:
    argv = [binary, "-root", str(root), "-output", str(graph)]
    if "source_revision_meta_v1" in (build_info(binary).get("capabilities") or ()):
        argv += ["-source-revision", revision]
    started = time.perf_counter()
    done = subprocess.run(argv, capture_output=True, timeout=3600)
    if done.returncode != 0 or not graph.is_file():
        raise RuntimeError(done.stderr.decode("utf-8", "replace")[-1500:])
    return time.perf_counter() - started


def top_symbols(graph: Path) -> tuple[list[dict[str, Any]], dict[str, int], dict[str, int]]:
    conn = sqlite3.connect(graph.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT n.name, n.file_path, n.start_line, COUNT(e.id) AS callers"
            " FROM nodes n JOIN edges e ON e.target_id = n.id AND e.type = 'CALLS'"
            f" WHERE n.label IN ({','.join('?' * len(_CALLABLE_LABELS))})"
            " AND COALESCE(n.is_test, 0) = 0 AND length(n.name) >= 4"
            " GROUP BY n.id ORDER BY callers DESC, n.name LIMIT ?",
            (*_CALLABLE_LABELS, _TOP_SYMBOLS),
        ).fetchall()
        counts = dict(conn.execute("SELECT label, COUNT(*) FROM nodes GROUP BY label").fetchall())
        edges = dict(conn.execute("SELECT type, COUNT(*) FROM edges GROUP BY type").fetchall())
    finally:
        conn.close()
    symbols = [{"name": r[0], "file": r[1], "line": r[2], "callers": r[3]} for r in rows]
    return symbols, counts, edges


def tool_calls(symbols: list[dict[str, Any]], title: str) -> list[tuple[str, list[str]]]:
    top = symbols[0] if symbols else {"name": "main", "file": "", "line": 1}
    calls = [("gt-query", [title]), ("gt-flows", []), ("gt-routes", []), ("gt-tools", []),
             ("gt-verify", []), ("gt-failures", []), ("gt-help", [])]
    for sym in symbols[:3]:
        calls += [("gt-context", [sym["name"]]), ("gt-callers", [sym["name"]]),
                  ("gt-impact", [sym["name"]]), ("gt-refs", [sym["name"]]),
                  ("gt-def", [sym["name"]]), ("gt-calls", [sym["name"]])]
    if top.get("file"):
        calls += [("gt-tests", [top["file"]]), ("gt-module", [top["file"]]),
                  ("gt-check", [top["file"]]), ("gt-cochange", [top["file"]]),
                  ("gt-changes", [top["file"]]),
                  ("gt-slice", [top["name"], str(int(top["line"] or 1) + 1)]),
                  ("gt-shape", [top["name"]]), ("gt-api", [top["name"]]),
                  ("gt-rename", [top["name"], f"{top['name']}_renamed"])]
    if len(symbols) >= 2:
        calls.append(("gt-taint", [symbols[1]["name"], top["name"]]))
    return calls


def smoke_task(task: str, *, bench: Path, workdir: Path, binary: str) -> dict[str, Any]:
    from gt_engine import wheel_perf
    from gt_engine.grep_augment import GrepAugmenter
    from gt_engine.gt_session import GTSession, GTSessionConfig
    from gt_engine.miniswe_integration import MiniSweAdapter
    from gt_engine.tool_server import ToolDispatcher

    wheel_perf.install()
    config = tomllib.loads((bench / "tasks" / task / "task.toml").read_text(encoding="utf-8"))
    meta = config["metadata"]
    commit = meta["base_commit_hash"]
    repo = workdir / task / "repo"
    graph = workdir / task / "graph.db"
    checkout(meta["repository_url"], commit, repo)
    if graph.exists():
        graph.unlink()
    index_seconds = index(binary, repo, graph, commit)
    symbols, node_counts, edge_counts = top_symbols(graph)

    state = workdir / task / "state"
    shutil.rmtree(state, ignore_errors=True)
    adapter = MiniSweAdapter(task_id=task, state_dir=state, predicates=[],
                             repo_root=repo, graph_db=str(graph))
    adapter.engine_state.bind_initial_source(commit)
    session = GTSession(GTSessionConfig(task_id=task), engine=adapter)
    dispatcher = ToolDispatcher(session)

    results = []
    for name, args in tool_calls(symbols, meta.get("display_title") or task):
        started = time.perf_counter()
        text, code = dispatcher.dispatch(name, args)
        results.append({
            "tool": name, "args": args, "exit_code": code,
            "ms": round((time.perf_counter() - started) * 1000, 1),
            "bytes": len(text.encode("utf-8")),
            "internal_error": "internal_error" in text,
            "head": text.splitlines()[0][:160] if text else "",
            "text": text,
        })
    augmenter = GrepAugmenter(session)
    augment = []
    for sym in symbols:
        started = time.perf_counter()
        block = augmenter.augment(f'grep -rn "{sym["name"]}" .')
        augment.append({"symbol": sym["name"], "hit": bool(block),
                        "bytes": len(block.encode("utf-8")),
                        "ms": round((time.perf_counter() - started) * 1000, 1),
                        "text": block})
    answered = [row for row in results if row["exit_code"] == 0]
    return {
        "task": task, "repository": meta["repository_url"], "commit": commit,
        "language": meta.get("language"), "index_seconds": round(index_seconds, 1),
        "node_counts": node_counts, "edge_counts": edge_counts, "top_symbols": symbols,
        "tools_answered": len(answered), "tools_run": len(results),
        "internal_errors": sum(row["internal_error"] for row in results),
        "tool_ms_p50": statistics.median(row["ms"] for row in results) if results else 0,
        "tool_ms_max": max((row["ms"] for row in results), default=0),
        "augment_hits": sum(row["hit"] for row in augment), "augment_runs": len(augment),
        "tools": results, "augment": augment,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bench", required=True, help="deep-swe checkout at the pinned commit")
    parser.add_argument("--workdir", required=True)
    parser.add_argument("--gt-index", required=True)
    parser.add_argument("--tasks", default=",".join(DEFAULT_TASKS))
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    report = {"binary": args.gt_index, "build_info": build_info(args.gt_index), "tasks": []}
    for task in [item.strip() for item in args.tasks.split(",") if item.strip()]:
        try:
            row = smoke_task(task, bench=Path(args.bench), workdir=Path(args.workdir),
                             binary=args.gt_index)
        except Exception as exc:  # noqa: BLE001 - one repo failing must not hide the rest
            row = {"task": task, "error": f"{type(exc).__name__}: {str(exc)[:500]}"}
        report["tasks"].append(row)
        print(json.dumps({k: v for k, v in row.items()
                          if k not in ("tools", "augment", "edge_counts", "node_counts")}))
        Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
