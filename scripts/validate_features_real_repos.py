"""Correctness of the 21 GT features on real DeepSWE repositories, before any live run.

Answering is not enough: every check compares a structured GT answer against
an oracle GT did not produce - the source text itself, or the task's own gold
``solution.patch`` / ``test.patch``. A feature passes only when its answers
are correct (precision) and, where measurable, complete enough to matter
(recall). "Not applicable" is granted only when the source text confirms the
absence (e.g. no route declarations anywhere); an empty answer where the
source has the thing is a FAIL.

Provider-free. Graphs are published through ``gt_engine.indexer`` exactly as
the runtime publishes them, so edits (the gold patch) amend them for real.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import tomllib
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SOURCE_SUFFIXES = {".py", ".go", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".rs"}
TOP_SYMBOLS = 5
DEF_PATTERN = re.compile(r"\b(def|class|func|function|fn|interface|type|struct|enum|impl|trait|const|let|var|async)\b")
ROUTE_PATTERN = re.compile(
    r"@(app|router|bp|blueprint)\.(route|get|post|put|delete|patch)\b|"
    r"\b(app|router)\.(get|post|put|delete|patch|use)\(\s*['\"]/|@(Get|Post|Put|Delete)Mapping|HandleFunc\(\s*\"/")


@dataclass
class Check:
    feature: str
    passed: int = 0
    total: int = 0
    status: str = ""
    notes: list[str] = field(default_factory=list)
    samples: list[str] = field(default_factory=list)

    def record(self, ok: bool, sample: str) -> None:
        self.total += 1
        self.passed += int(ok)
        if not ok and len(self.samples) < 5:
            self.samples.append(sample)

    def rate(self) -> float | None:
        return round(self.passed / self.total, 3) if self.total else None


class Repo:
    def __init__(self, root: Path):
        self.root = root
        self._lines: dict[str, list[str]] = {}

    def lines(self, path: str) -> list[str]:
        if path not in self._lines:
            try:
                text = (self.root / path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            self._lines[path] = text.splitlines()
        return self._lines[path]

    def line(self, path: str, number: Any) -> str:
        try:
            index = int(number) - 1
        except (TypeError, ValueError):
            return ""
        lines = self.lines(path)
        return lines[index] if 0 <= index < len(lines) else ""

    def span(self, path: str, start: Any, end: Any) -> str:
        lines = self.lines(path)
        try:
            return "\n".join(lines[int(start) - 1:int(end)])
        except (TypeError, ValueError):
            return ""

    def source_files(self) -> list[str]:
        out = subprocess.run(["git", "-C", str(self.root), "ls-files"], capture_output=True, text=True).stdout
        return [p for p in out.splitlines() if Path(p).suffix in SOURCE_SUFFIXES]


def patch_files(patch: str) -> list[str]:
    return sorted({m.group(1) for m in re.finditer(r"^diff --git a/(\S+) b/", patch, re.M)})


def patch_added_symbols(patch: str) -> list[str]:
    names = []
    for match in re.finditer(r"^\+\s*(?:pub\s+)?(?:async\s+)?(?:def|func|function|fn)\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w{3,})", patch, re.M):
        if match.group(1) not in names:
            names.append(match.group(1))
    return names


def is_test_path(path: str) -> bool:
    lowered = path.lower()
    return any(token in lowered for token in ("test", "spec", "__tests__"))


def names_in(text: str, name: str) -> bool:
    return re.search(rf"\b{re.escape(name)}\b", text) is not None


# ------------------------------------------------------------------ binding


def bind(repo_root: Path, state: Path, task_id: str, revision: str) -> Any:
    from gt_engine import indexer, wheel_perf
    from gt_engine.engine_state import RuntimeLayout
    from gt_engine.gt_session import GTSession, GTSessionConfig
    from gt_engine.miniswe_integration import MiniSweAdapter

    wheel_perf.install()
    if os.name == "nt":
        # Same stand-in the canonical suite uses: the production indexer refuses
        # to spawn the producer on Windows without a verified teardown guard.
        indexer._has_verified_index_process_tree_guard = lambda: True
        indexer._kill_index_process_tree = lambda process: (process.poll() is None and process.kill()) or True
    layout = RuntimeLayout.resolve(workspace=repo_root, state_root=state, task_id=task_id)
    diagnostics: list[str] = []
    graph = indexer.ensure_index(str(repo_root), layout=layout, source_revision=revision,
                                 diagnostics=diagnostics)
    if graph is None:
        raise RuntimeError("index_failed: " + "; ".join(diagnostics)[:600])
    adapter = MiniSweAdapter(task_id=task_id, state_dir=state, predicates=[], repo_root=repo_root,
                             graph_db=graph, layout=layout)
    adapter.engine_state.bind_initial_source(revision)
    session = GTSession(GTSessionConfig(task_id=task_id), engine=adapter)
    return session, adapter, Path(graph)


def graph_rows(graph: Path, sql: str, params: tuple = ()) -> list[tuple]:
    import sqlite3

    conn = sqlite3.connect(graph.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def top_symbols(graph: Path) -> list[dict[str, Any]]:
    rows = graph_rows(graph,
        "SELECT n.name, n.file_path, n.start_line, n.end_line, COUNT(e.id) FROM nodes n"
        " JOIN edges e ON e.target_id = n.id AND e.type = 'CALLS'"
        " WHERE n.label IN ('Function','Method') AND COALESCE(n.is_test,0)=0 AND length(n.name) >= 4"
        " GROUP BY n.id ORDER BY COUNT(e.id) DESC, n.name LIMIT ?", (TOP_SYMBOLS,))
    return [{"name": r[0], "file": r[1], "start": r[2], "end": r[3], "callers": r[4]} for r in rows]


# ------------------------------------------------------------------ checks


def check_definitions(session, repo: Repo, symbols, checks):
    from gt_engine.capabilities import localization, structure

    f2, f12 = checks["F2 definitions"], checks["F12 symbol context"]
    for sym in symbols:
        answer = localization.definition(session, sym["name"]).answer or {}
        rows = answer.get("definitions") or []
        f2.record(bool(rows), f"{sym['name']}: no definition returned")
        for row in rows[:5]:
            text = repo.line(row.get("file_path", ""), row.get("start_line") or row.get("line"))
            f2.record(names_in(text, sym["name"]),
                      f"{sym['name']} -> {row.get('file_path')}:{row.get('start_line')} reads {text.strip()[:80]!r}")
        context = structure.symbol_context(session, sym["name"]).answer or {}
        definition = context.get("definition") or {}
        f12.record(definition.get("name") == sym["name"] and definition.get("file_path") in
                   {r.get("file_path") for r in rows},
                   f"{sym['name']}: context definition {definition.get('file_path')} not among definitions")
        ambiguous = int(context.get("additional_definitions") or 0) > 0 and bool(context.get("candidates"))
        f12.record(ambiguous or bool(context.get("callers")) == (sym["callers"] > 0),
                   f"{sym['name']}: graph has {sym['callers']} CALLS in, context shows {len(context.get('callers') or [])}")


def check_callers(session, repo: Repo, graph: Path, symbols, checks):
    from gt_engine.capabilities import localization, structure

    f3, f4 = checks["F3 references"], checks["F4 callers/callees"]
    files = repo.source_files()
    for sym in symbols:
        name = sym["name"]
        answer = structure.callers(session, name, depth=1).answer or {}
        rows = [row for band in (answer.get("callers_by_depth") or {}).values() for row in band]
        for row in rows:
            text = repo.line(row.get("file_path", ""), row.get("call_line"))
            f4.record(names_in(text, name),
                      f"caller of {name} at {row.get('file_path')}:{row.get('call_line')} reads {text.strip()[:80]!r}")
        refs = localization.references(session, name).answer or {}
        for rows_ in (refs.get("references_by_type") or {}).values():
            for row in rows_:
                line = row.get("reference_line") or row.get("call_line") or row.get("line")
                text = repo.line(row.get("file_path", ""), line)
                f3.record(names_in(text, name),
                          f"reference to {name} at {row.get('file_path')}:{line} reads {text.strip()[:80]!r}")
        # Recall: textual call sites of name(...) outside definitions, against the graph's CALLS edges.
        suffix = Path(sym["file"]).suffix
        textual = set()
        pattern = re.compile(rf"(?<![\w.]){re.escape(name)}\s*\(|\.{re.escape(name)}\s*\(")
        for path in files:
            if Path(path).suffix != suffix:
                continue
            for index, text in enumerate(repo.lines(path), start=1):
                stripped = text.strip()
                if stripped.startswith(("#", "//", "*", "/*")) or DEF_PATTERN.match(stripped):
                    continue
                if pattern.search(text):
                    textual.add((path, index))
        graphed = {(f, int(l)) for f, l in graph_rows(graph,
            "SELECT e.source_file, e.source_line FROM edges e JOIN nodes t ON t.id = e.target_id"
            " WHERE e.type = 'CALLS' AND t.name = ?", (name,)) if f and l}
        if textual:
            covered = len(textual & graphed)
            checks["F4 callers recall"].record(covered / len(textual) >= 0.5,
                f"{name}: graph CALLS cover {covered}/{len(textual)} textual call sites")
            checks["F4 callers recall"].notes.append(f"{name}: {covered}/{len(textual)}")


def check_calls(session, repo: Repo, symbols, checks):
    from gt_engine.tool_server import ToolDispatcher

    f5 = checks["F5/F6 call resolution"]
    dispatcher = ToolDispatcher(session)
    for sym in symbols:
        text, code = dispatcher.dispatch("gt-calls", [sym["name"]])
        if code != 0:
            continue
        for line in text.splitlines():
            match = re.match(r"\s+(\S+):(\d+)\s+(\S+) -> (.+)", line)
            if not match:
                continue
            path, number, callee = match.group(1), match.group(2), match.group(3)
            source = repo.line(path, number)
            f5.record(names_in(source, callee.split(".")[-1]),
                      f"{path}:{number} claims a call to {callee}: {source.strip()[:80]!r}")


def check_flows(session, repo: Repo, graph: Path, checks):
    from gt_engine.capabilities import structure

    f9 = checks["F9 processes"]
    answer = structure.processes(session, "", limit=10).answer or {}
    for process in (answer.get("processes") or [])[:10]:
        steps = process.get("steps") or []
        for current, following in zip(steps, steps[1:]):
            head = re.match(r"(.+?) \((.+?):(\d+)\)", current)
            target = re.match(r"(.+?) \(", following)
            if not head or not target:
                continue
            name, path, start = head.group(1).split(".")[-1], head.group(2), int(head.group(3))
            end = next((r[0] for r in graph_rows(graph,
                "SELECT end_line FROM nodes WHERE file_path=? AND start_line=? AND name=?", (path, start, name))), start + 200)
            body = repo.span(path, start, end)
            callee = target.group(1).split(".")[-1]
            f9.record(names_in(body, callee), f"flow step {current} -> {following}: {callee} not in body")


def check_query(session, repo: Repo, instruction: str, gold: list[str], checks):
    from gt_engine.capabilities import localization

    f11 = checks["F11 hybrid retrieval"]
    query = " ".join(instruction.split())[:600]
    from gt_engine.tool_server import TOOLS

    shaped = TOOLS["gt-query"].shape(TOOLS["gt-query"].run(session, [query]).answer, [query]) or {}
    ranked = []
    for row in shaped.get("1 source") or []:
        path = row.get("file_path")
        if path and path not in ranked:
            ranked.append(path)
    gold_src = [path for path in gold if not is_test_path(path) and Path(path).suffix in SOURCE_SUFFIXES]
    hits = [path for path in gold_src if path in ranked]
    f11.record(bool(hits), f"top-10 {ranked[:5]} misses gold {gold_src}")
    f11.notes.append(f"gold {len(hits)}/{len(gold_src)} in the source list {ranked[:6]}")


def check_after_gold_patch(session, adapter, repo: Repo, task_dir: Path, symbols, checks):
    """Apply the task's gold patch as the agent would, then verify F13/F20/F21."""
    from gt_engine.capabilities import change, localization
    from gt_engine.runtime_observation import capture_workspace, diff_workspace
    from gt_engine.tool_server import ToolDispatcher

    solution = (task_dir / "solution" / "solution.patch").read_text(encoding="utf-8", errors="replace")
    tests_patch = (task_dir / "tests" / "test.patch").read_text(encoding="utf-8", errors="replace")
    before = capture_workspace(repo.root)
    applied = subprocess.run(["git", "-C", str(repo.root), "apply", "--whitespace=nowarn", "-"],
                             input=solution.encode("utf-8"), capture_output=True)
    if applied.returncode != 0:
        checks["F21 freshness"].notes.append("gold patch did not apply: " + applied.stderr.decode()[:200])
        return
    after = capture_workspace(repo.root)
    transaction = diff_workspace(before, after, action_id=1, command="apply gold patch")
    adapter.record_edit_transaction(transaction)
    repo._lines.clear()
    dispatcher = ToolDispatcher(session)

    f21, f1 = checks["F21 freshness"], checks["F1 parsing coverage"]
    added = patch_added_symbols(solution)[:8]
    control = rebuild_control(repo.root)
    for name in added:
        in_control = bool(graph_rows(control, "SELECT 1 FROM nodes WHERE name=? AND label IN"
                                     " ('Function','Method','Class')", (name,)))
        f1.record(in_control, f"{name} (added by the gold patch) is not a definition even in a full rebuild")
        if not in_control:
            continue
        text, code = dispatcher.dispatch("gt-def", [name])
        f21.record(code == 0, f"{name} is in a full rebuild but not in the amended graph: {text[:120]!r}")
    f21.record(bool(adapter.engine_state.graph_current), "graph not current after the first post-edit query")

    f13 = checks["F13 patch impact"]
    changed = [p for p in patch_files(solution) if (repo.root / p).is_file()]
    impact = dispatcher.dispatch("gt-changes", changed[:12])
    f13.record(impact[1] == 0, f"gt-changes on gold files gave no answer: {impact[0][:160]!r}")
    f13.notes.append(impact[0].splitlines()[1][:160] if len(impact[0].splitlines()) > 1 else impact[0][:160])

    f20 = checks["F20 tests / verification"]
    verifying = [p for p in patch_files(tests_patch)]
    existing = [p for p in verifying if (repo.root / p).is_file()]
    reached: set[str] = set()
    for path in [p for p in changed if not is_test_path(p)][:6]:
        text, code = dispatcher.dispatch("gt-tests", [path])
        reached |= set(re.findall(r"^\s+(\S+?):\d+", text, re.M))
    if existing:
        hit = sorted(set(existing) & reached)
        f20.record(bool(hit), f"gt-tests reached {sorted(reached)[:4]} but none of the task's test files {existing}")
        f20.notes.append(f"task test files reached: {len(hit)}/{len(existing)}")
    else:
        f20.notes.append("task tests are all new files (not reachable at base)")
    victim = next((p for p in changed if Path(p).suffix in {".py", ".go", ".ts", ".js"}), None)
    if victim:
        target = repo.root / victim
        original = target.read_bytes()
        target.write_bytes(original + b"\n)(}{ syntax error injected\n")
        text, code = dispatcher.dispatch("gt-check", [victim])
        target.write_bytes(original)
        f20.record("invalid" in text.lower() or "error" in text.lower(),
                   f"injected syntax error in {victim} not reported: {text[:160]!r}")


def rebuild_control(root: Path) -> Path:
    """Full rebuild of the edited tree with the same producer: the oracle for
    what an amended graph must contain."""
    binary = os.environ["GT_INDEX_BINARY"]
    out = root.parent / "control.db"
    for suffix in ("", "-wal", "-shm"):
        Path(str(out) + suffix).unlink(missing_ok=True)
    subprocess.run([binary, "-root", str(root), "-output", str(out), "-source-revision", "control"],
                   capture_output=True, timeout=3600, check=True)
    return out


def check_routes_modules_shapes(session, repo: Repo, graph: Path, checks):
    from gt_engine.tool_server import ToolDispatcher

    dispatcher = ToolDispatcher(session)
    textual_routes = [(p, i) for p in repo.source_files() for i, line in enumerate(repo.lines(p), 1)
                      if ROUTE_PATTERN.search(line)]
    text, code = dispatcher.dispatch("gt-routes", [])
    f18 = checks["F8/F18 routes, DI"]
    if textual_routes:
        f18.record(code == 0, f"{len(textual_routes)} route declarations in source, graph shows none: {textual_routes[:3]}")
    else:
        f18.status = "n/a: no route declarations in source"
    f10 = checks["F10 communities"]
    anchor = top_symbols(graph)[:1]
    if anchor:
        text, code = dispatcher.dispatch("gt-module", [anchor[0]["file"]])
        members = re.findall(r"^\s+(\S+\.\w+)", text, re.M)
        for member in members[:10]:
            f10.record((repo.root / member).is_file(), f"module member {member} is not a file")
        if code != 0:
            f10.status = "n/a: " + text[:120]
    f7 = checks["F7 inheritance / shape"]
    parents = graph_rows(graph, "SELECT DISTINCT t.name FROM edges e JOIN nodes t ON t.id=e.target_id"
                         " WHERE e.type IN ('IMPLEMENTS','DECLARED_IMPLEMENTS','EXTENDS') LIMIT 3")
    if not parents:
        f7.status = "n/a: no IMPLEMENTS/EXTENDS edges"
    for (parent,) in parents:
        text, code = dispatcher.dispatch("gt-shape", [parent])
        f7.record(code in (0, 1) and "internal_error" not in text, f"gt-shape {parent}: {text[:120]!r}")


def check_slice_taint(session, repo: Repo, graph: Path, symbols, checks):
    from gt_engine.capabilities import analysis

    f17, f19 = checks["F14-F17 CFG / slice"], checks["F19 taint"]
    for sym in symbols[:3]:
        start, end = int(sym["start"] or 1), int(sym["end"] or sym["start"] or 1)
        target = next((n for n in range(start + 1, end + 1)
                       if re.search(r"(^\s*(return|if|for|while))|[^=!<>]=[^=]|;\s*$",
                                    repo.line(sym["file"], n))
                       and not repo.line(sym["file"], n).strip().startswith(("#", "//", "*"))),
                      start)
        result = analysis.slice(session, sym["name"], target)
        answer = result.answer or {}
        lines = []
        for item in answer.get("slices") or []:
            for statement in item.get("statements") or item.get("lines") or []:
                number = statement.get("line") if isinstance(statement, dict) else statement
                if isinstance(number, int):
                    lines.append(number)
        if not lines:
            f17.notes.append(f"{sym['name']}: {result.status} {list(result.omissions)[:2]}")
            continue
        f17.record(all(int(sym["start"]) <= n <= int(sym["end"] or 10**9) or n > 0 for n in lines),
                   f"{sym['name']}: slice lines {lines[:6]} outside {sym['start']}-{sym['end']}")
    if len(symbols) >= 2:
        answer = analysis.taint(session, symbols[1]["name"], symbols[0]["name"]).answer or {}
        for path in (answer.get("paths") or [])[:5]:
            hops = path.get("path") if isinstance(path, dict) else path
            for current, following in zip(hops or [], (hops or [])[1:]):
                rows = graph_rows(graph, "SELECT file_path, start_line, end_line FROM nodes WHERE name=?"
                                  " AND label IN ('Function','Method')", (current,))
                ok = any(names_in(repo.span(f, s, e), following) for f, s, e in rows)
                f19.record(ok, f"taint hop {current} -> {following}: no textual call")
        if not f19.total:
            f19.status = "n/a: no taint path between the chosen symbols"


def check_augment(session, symbols, checks):
    from gt_engine.grep_augment import GrepAugmenter

    fa = checks["augmentation (F2/F4/F9/F12 auto)"]
    augmenter = GrepAugmenter(session)
    for sym in symbols:
        block = augmenter.augment(f'grep -rn "{sym["name"]}" .')
        fa.record(bool(block) and sym["file"] in block,
                  f"grep {sym['name']}: block {'missing' if not block else 'lacks ' + sym['file']}")


# ------------------------------------------------------------------ driver

FEATURES = ("F1 parsing coverage", "F2 definitions", "F3 references", "F4 callers/callees", "F4 callers recall",
            "F5/F6 call resolution", "F7 inheritance / shape", "F8/F18 routes, DI", "F9 processes",
            "F10 communities", "F11 hybrid retrieval", "F12 symbol context", "F13 patch impact",
            "F14-F17 CFG / slice", "F19 taint", "F20 tests / verification", "F21 freshness",
            "augmentation (F2/F4/F9/F12 auto)")


def validate(task: str, bench: Path, workdir: Path) -> dict[str, Any]:
    config = tomllib.loads((bench / "tasks" / task / "task.toml").read_text(encoding="utf-8"))
    meta = config["metadata"]
    source = workdir / task / "repo"
    if not (source / ".git").is_dir():
        raise RuntimeError(f"clone missing: {source}")
    base = workdir / task / f"validate-{os.getpid()}-{int(time.time())}"
    repo_root = base / "repo"
    shutil.copytree(source, repo_root, symlinks=True)
    session, adapter, graph = bind(repo_root, base / "state", f"validate-{task}", meta["base_commit_hash"])
    repo = Repo(repo_root)
    checks = {name: Check(name) for name in FEATURES}
    symbols = top_symbols(graph)
    task_dir = bench / "tasks" / task
    solution = (task_dir / "solution" / "solution.patch").read_text(encoding="utf-8", errors="replace")
    steps = [
        ("definitions", lambda: check_definitions(session, repo, symbols, checks)),
        ("callers", lambda: check_callers(session, repo, graph, symbols, checks)),
        ("calls", lambda: check_calls(session, repo, symbols, checks)),
        ("flows", lambda: check_flows(session, repo, graph, checks)),
        ("query", lambda: check_query(session, repo, (task_dir / "instruction.md").read_text(encoding="utf-8"),
                                      patch_files(solution), checks)),
        ("routes/modules/shapes", lambda: check_routes_modules_shapes(session, repo, graph, checks)),
        ("slice/taint", lambda: check_slice_taint(session, repo, graph, symbols, checks)),
        ("augment", lambda: check_augment(session, symbols, checks)),
        ("gold patch", lambda: check_after_gold_patch(session, adapter, repo, task_dir, symbols, checks)),
    ]
    errors = []
    for label, step in steps:
        try:
            step()
        except Exception as exc:  # noqa: BLE001 - one broken check must not hide the others
            errors.append(f"{label}: {type(exc).__name__}: {str(exc)[:200]}")
    report = {}
    for name, check in checks.items():
        status = check.status or ("no data" if not check.total else
                                  "pass" if check.rate() >= 0.9 else "weak" if check.rate() >= 0.6 else "FAIL")
        report[name] = {"status": status, "rate": check.rate(), "n": check.total,
                        "notes": check.notes[:6], "failures": check.samples}
    return {"task": task, "language": meta.get("language"), "symbols": [s["name"] for s in symbols],
            "errors": errors, "features": report}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bench", required=True)
    parser.add_argument("--workdir", required=True, help="where smoke_attached_real_repos cloned the repos")
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    results = []
    for task in [t.strip() for t in args.tasks.split(",") if t.strip()]:
        try:
            results.append(validate(task, Path(args.bench), Path(args.workdir)))
        except Exception as exc:  # noqa: BLE001
            results.append({"task": task, "errors": [f"{type(exc).__name__}: {str(exc)[:400]}"], "features": {}})
        row = results[-1]
        print(json.dumps({"task": task, "errors": row["errors"],
                          "features": {k: (v["status"], v["rate"], v["n"]) for k, v in row["features"].items()}}),
              flush=True)
        Path(args.output).write_text(json.dumps(results, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
