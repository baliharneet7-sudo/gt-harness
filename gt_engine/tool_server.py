"""Agent-callable GT tools for the attached delivery mode.

The GitNexus eval pattern: standalone ``gt-*`` executables the agent runs as
ordinary shell commands, answered by a warm server that already holds the
graph. Unlike GitNexus the server lives INSIDE the runner process, so every
answer goes through the same EngineState freshness gate as the typed path:
a tool call after an edit is answered from the amended graph, never from the
task-start index. Because the server lives and dies with the runner, a cold
CLI fallback would have no graph to read and is deliberately absent.
"""
from __future__ import annotations

import dataclasses
import json
import os
import stat
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from gt_engine.capabilities import analysis, change, localization, runtime, structure
from gt_engine.capabilities._query import CapabilityResult, run_typed, wrap
from gt_engine.miniswe_typed_actions import snapshot_scope
from gt_engine.tool_render import DEFAULT_TOOL_OUTPUT_BYTES, render_result

if TYPE_CHECKING:  # pragma: no cover - typing only
    from gt_engine.gt_session import GTSession

READY_PREFIX = "GT_TOOL_SERVER_READY:"
EXIT_ANSWER = 0
EXIT_NO_ANSWER = 1
EXIT_USAGE = 2


class ToolUsageError(ValueError):
    """The agent called a tool with the wrong argument shape."""


@dataclass(frozen=True)
class ToolSpec:
    name: str
    usage: str
    summary: str
    run: Callable[["GTSession", list[str]], CapabilityResult]
    title: Callable[[list[str]], str]
    next_hint: str = ""
    reads_graph: bool = True
    shape: Callable[[Any, list[str]], Any] | None = None
    core: bool = False


def _need(args: list[str], count: int, usage: str) -> None:
    if len(args) < count or any(not arg.strip() for arg in args[:count]):
        raise ToolUsageError(usage)


def _int(value: str, usage: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise ToolUsageError(usage) from exc


def _symbol_hints(args: list[str]) -> dict[str, Any]:
    return {"path": args[1]} if len(args) > 1 and args[1].strip() else {}


_QUERY_CANDIDATES = 30
_QUERY_SOURCE_SHOWN = 8
_QUERY_TESTS_SHOWN = 4


_TEST_DIRS = frozenset({"test", "tests", "__tests__", "__tests", "spec", "specs", "testing"})


def _looks_like_test(path: str) -> bool:
    parts = path.replace("\\", "/").lower().split("/")
    name = parts[-1]
    return (any(part in _TEST_DIRS for part in parts[:-1])
            or name.startswith("test_") or ".test." in name or ".spec." in name
            or name.endswith(("_test.go", "_test.py", "_test.rs", "_spec.rb")))


def _run_query(session: "GTSession", args: list[str]) -> CapabilityResult:
    _need(args, 1, TOOLS["gt-query"].usage)
    return localization.hybrid_rank(session, " ".join(args), k=_QUERY_CANDIDATES)


def _run_context(session: "GTSession", args: list[str]) -> CapabilityResult:
    _need(args, 1, TOOLS["gt-context"].usage)
    return structure.symbol_context(session, args[0], **_symbol_hints(args))


def _callers_with_fallback(session: "GTSession", symbol: str, depth: int,
                           **hints: Any) -> CapabilityResult:
    """A heavily called symbol can overflow the typed byte bound, which drops
    the whole answer; the callers that matter most would then read as none.
    Fall back to the nearest band and say so."""
    result = structure.callers(session, symbol, depth=depth, **hints)
    if result.answer is None and depth > 1 and "callers_truncated" in result.omissions:
        shallow = structure.callers(session, symbol, depth=1, **hints)
        if shallow.answer is not None:
            return dataclasses.replace(shallow, omissions=(
                f"depth_reduced_to_1:depth_{depth}_exceeded_byte_bound", *shallow.omissions))
    return result


def _run_callers(session: "GTSession", args: list[str]) -> CapabilityResult:
    usage = TOOLS["gt-callers"].usage
    _need(args, 1, usage)
    depth = _int(args[1], usage) if len(args) > 1 else 2
    return _callers_with_fallback(session, args[0], max(1, min(depth, 6)))


def _run_impact(session: "GTSession", args: list[str]) -> CapabilityResult:
    _need(args, 1, TOOLS["gt-impact"].usage)
    return _callers_with_fallback(session, args[0], 3, **_symbol_hints(args))


def _run_refs(session: "GTSession", args: list[str]) -> CapabilityResult:
    _need(args, 1, TOOLS["gt-refs"].usage)
    return localization.references(session, args[0], _symbol_hints(args) or None)


def _run_def(session: "GTSession", args: list[str]) -> CapabilityResult:
    _need(args, 1, TOOLS["gt-def"].usage)
    return localization.definition(session, args[0], _symbol_hints(args) or None)


def _run_flows(session: "GTSession", args: list[str]) -> CapabilityResult:
    return structure.processes(session, " ".join(args), limit=10)


_TEST_REACH_DEPTH = 3
_TEST_REACH_LIMIT = 25
_TEST_REACH_QUERY = (
    "WITH RECURSIVE reach(id, depth) AS ("
    " SELECT id, 0 FROM nodes WHERE file_path = ? AND label IN ('Function', 'Method')"
    " UNION SELECT e.source_id, r.depth + 1 FROM edges e JOIN reach r ON e.target_id = r.id"
    " WHERE e.type = 'CALLS' AND r.depth < ?)"
    " SELECT n.file_path, n.qualified_name, n.name, n.start_line, MIN(r.depth)"
    " FROM reach r JOIN nodes n ON n.id = r.id"
    " WHERE n.is_test = 1 AND r.depth > 0"
    " GROUP BY n.id ORDER BY MIN(r.depth), n.file_path, n.start_line LIMIT ?"
)


def _tests_by_reachability(session: "GTSession", files: list[str]) -> list[dict[str, Any]]:
    """Test functions that reach the files' functions within a few CALLS hops.

    The certified covering selector returned nothing on 5/5 real repositories
    (adaptix, awilix, abs, fd, csstree) although each has hundreds of is_test
    functions calling into the code; this is the graph's own answer to the
    same question, labelled as reachability rather than coverage."""
    from gt_engine.capabilities._query import graph_conn

    conn = graph_conn(session)
    if conn is None:
        return []
    rows: list[dict[str, Any]] = []
    try:
        for path in files:
            for file_path, qualified, name, line, depth in conn.execute(
                _TEST_REACH_QUERY, (path, _TEST_REACH_DEPTH, _TEST_REACH_LIMIT)
            ):
                rows.append({"file_path": file_path, "line": line,
                             "name": f"{qualified or name} ({depth} call hop(s) away)"})
    finally:
        conn.close()
    return rows[:_TEST_REACH_LIMIT]


def _run_tests(session: "GTSession", args: list[str]) -> CapabilityResult:
    _need(args, 1, TOOLS["gt-tests"].usage)
    result = change.affected_tests(session, list(args))
    covering = (result.answer or {}).get("tests") if isinstance(result.answer, dict) else None
    if covering:
        return result
    reached = _tests_by_reachability(session, list(args))
    if not reached:
        return result
    return wrap(session, "affected_tests", semantics="heuristic",
                answer={"tests reaching these files": reached},
                omissions=("covering_selector_empty",
                           f"graph_reachability_depth_{_TEST_REACH_DEPTH}"))


def _run_routes(session: "GTSession", args: list[str]) -> CapabilityResult:
    return run_typed(session, "route_map", {})


MAX_CHANGED_FILES = 12


def _edited_paths(session: "GTSession") -> list[str]:
    """Every path the agent's recorded edit transactions touched, in order."""
    store = getattr(getattr(session, "_engine", None), "store", None)
    journal = Path(getattr(store, "path", "") or "")
    paths: list[str] = []
    if not journal.is_file():
        return paths
    with journal.open(encoding="utf-8") as handle:
        for line in handle:
            if '"edit_transaction"' not in line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("event") != "edit_transaction":
                continue
            for path in row.get("changed_paths") or ():
                if path not in paths:
                    paths.append(str(path))
    return paths


def _base_text(repo_root: str, path: str) -> str:
    done = subprocess.run(
        ["git", "-C", repo_root, "show", f"HEAD:{path}"],
        capture_output=True, timeout=30, check=False,
    )
    return done.stdout.decode("utf-8", errors="replace") if done.returncode == 0 else ""


def _run_changes(session: "GTSession", args: list[str]) -> CapabilityResult:
    repo_root = str(getattr(getattr(session, "_engine", None), "repo_root", "") or "")
    paths = list(args) or _edited_paths(session)
    if not repo_root or not paths:
        return wrap(session, "patch_impact", status="abstain",
                    omissions=("no_edits_recorded",))
    edited: dict[str, dict[str, str]] = {}
    for path in paths[:MAX_CHANGED_FILES]:
        target = Path(repo_root) / path
        after = target.read_text(encoding="utf-8", errors="replace") if target.is_file() else ""
        edited[path] = {"before": _base_text(repo_root, path), "after": after}
    result = change.patch_impact(session, edited)
    if result.answer is None and len(edited) > 1:
        # One unmappable file (an export-only index, a config file) sinks the
        # combined answer; ask per file and merge what maps.
        merged: dict[str, Any] = {}
        unmapped = []
        for path, texts in edited.items():
            single = change.patch_impact(session, {path: texts})
            if isinstance(single.answer, dict):
                for key, value in single.answer.items():
                    if isinstance(value, list):
                        merged.setdefault(key, []).extend(value)
                    else:
                        merged.setdefault(key, value)
            else:
                unmapped.append(path)
        if merged:
            result = dataclasses.replace(result, answer=merged, status="partial", omissions=tuple(
                f"changed_symbols_unmapped:{path}" for path in unmapped))
    if len(paths) > MAX_CHANGED_FILES:
        result = dataclasses.replace(result, omissions=(
            *result.omissions, f"changed_files_truncated:{len(paths)}>{MAX_CHANGED_FILES}"))
    return result


def _run_check(session: "GTSession", args: list[str]) -> CapabilityResult:
    _need(args, 1, TOOLS["gt-check"].usage)
    return run_typed(session, "syntax", {"path": args[0]})


def _run_api(session: "GTSession", args: list[str]) -> CapabilityResult:
    _need(args, 1, TOOLS["gt-api"].usage)
    target = args[0]
    return change.route_impact(session, route=target if "/" in target else None,
                               handler=None if "/" in target else target)


def _run_shape(session: "GTSession", args: list[str]) -> CapabilityResult:
    _need(args, 1, TOOLS["gt-shape"].usage)
    return change.shape_change(session, args[0], **_symbol_hints(args))


_CALLSITE_QUERY = (
    "SELECT c.id, c.line_start, c.callee_lexeme, c.candidate_state, c.dispatch_form,"
    " ct.type, ct.trust_tier, t.name, t.qualified_name, t.file_path, t.start_line, t.language"
    " FROM edges h JOIN nodes c ON c.id = h.target_id"
    " LEFT JOIN edges ct ON ct.source_id = c.id"
    " AND ct.type IN ('CANDIDATE_TARGET', 'SELECTED_TARGET')"
    " LEFT JOIN nodes t ON t.id = ct.target_id"
    " WHERE h.type = 'HAS_CALLSITE' AND h.source_id = ?"
    " ORDER BY c.line_start, c.id, ct.type DESC, t.file_path, t.start_line"
)
_MAX_CANDIDATES_SHOWN = 4


def _run_calls(session: "GTSession", args: list[str]) -> CapabilityResult:
    """How every call inside one function resolved (F5 direct resolution,
    F6 callable values, F7 dispatch): each callsite with its selected target
    or its viable candidate set, read from the producer's HAS_CALLSITE /
    CANDIDATE_TARGET / SELECTED_TARGET edges. Unresolved calls are shown,
    never dropped; a candidate in another language is flagged."""
    _need(args, 1, TOOLS["gt-calls"].usage)
    from gt_engine.capabilities._query import graph_conn, resolve_symbol_node

    node = resolve_symbol_node(session, args[0], path=args[1] if len(args) > 1 else "")
    if node is None:
        return wrap(session, "calls", status="abstain", omissions=("symbol_not_found",))
    conn = graph_conn(session)
    if conn is None:
        return wrap(session, "calls", status="unavailable", omissions=("graph_unavailable",))
    try:
        rows = conn.execute(_CALLSITE_QUERY, (node.get("id"),)).fetchall()
    except Exception as exc:  # noqa: BLE001 - an older graph may lack the callsite layer
        return wrap(session, "calls", status="unavailable",
                    omissions=(f"callsite_layer_absent:{type(exc).__name__}",))
    finally:
        conn.close()
    language = node.get("language")
    sites: dict[int, dict[str, Any]] = {}
    for cid, line, callee, state, dispatch, edge, tier, name, qname, path, start, lang in rows:
        site = sites.setdefault(cid, {"line": line, "callee": callee, "state": state,
                                      "dispatch": dispatch, "selected": None, "candidates": []})
        if not name:
            continue
        where = f"{qname or name} ({path}:{start})"
        if language and lang and lang != language:
            where += f" [other language: {lang}]"
        if edge == "SELECTED_TARGET":
            site["selected"] = f"{where} [{tier}]"
        elif where not in site["candidates"]:
            site["candidates"].append(where)
    calls = []
    for site in sites.values():
        if site["selected"]:
            target = site["selected"]
        elif site["candidates"]:
            shown = site["candidates"][:_MAX_CANDIDATES_SHOWN]
            more = len(site["candidates"]) - len(shown)
            target = "one of: " + "; ".join(shown) + (f"; +{more} more" if more > 0 else "")
        else:
            target = "unresolved (external or unknown)"
        calls.append({
            "file_path": node.get("file_path"), "line": site["line"],
            "name": f"{site['callee']} -> {target} [{site['state']}, {site['dispatch']}]",
        })
    return wrap(session, "calls", answer={"calls": calls}, semantics="partial",
                omissions=() if calls else ("no_callsites_recorded",))


_MODULE_MEMBERS_SHOWN = 15


def _run_module(session: "GTSession", args: list[str]) -> CapabilityResult:
    """The community a file belongs to AND its sibling files - the facade
    returns only the community's label and cohesion, which does not tell the
    agent which other files move with this one."""
    _need(args, 1, TOOLS["gt-module"].usage)
    from gt_engine.capabilities._query import graph_conn

    result = structure.communities(session, args[0])
    answer = result.answer if isinstance(result.answer, dict) else None
    if not answer or not answer.get("communities"):
        return result
    conn = graph_conn(session)
    if conn is None:
        return result
    shaped = []
    try:
        for community in answer["communities"]:
            members = [row[0] for row in conn.execute(
                "SELECT member FROM community_members WHERE community_id = ? AND member_kind = 'file'"
                " AND member != ? ORDER BY member LIMIT ?",
                (community.get("id"), args[0], _MODULE_MEMBERS_SHOWN + 1))]
            cohesion = community.get("structural_cohesion") or community.get("cohesion")
            shaped.append({
                "cluster": f"{community.get('label') or community.get('heuristic_label')}"
                           f" ({community.get('member_count')} files, cohesion {cohesion})",
                "files moving with it": [{"file_path": member} for member in members[:_MODULE_MEMBERS_SHOWN]],
            })
    finally:
        conn.close()
    return dataclasses.replace(result, answer={"modules": shaped})


def _run_cochange(session: "GTSession", args: list[str]) -> CapabilityResult:
    _need(args, 1, TOOLS["gt-cochange"].usage)
    from gt_engine.cochange_evidence import run_cochange_prior

    adapter = getattr(session, "_engine", None)
    text = run_cochange_prior(adapter, tuple(args)) if adapter is not None else ""
    lines = [line for line in (text or "").splitlines()
             if line.strip() and not line.startswith("[GT_")]
    if not lines:
        return wrap(session, "cochange", status="abstain",
                    omissions=("no_cochange_history",), semantics="heuristic")
    return wrap(session, "cochange", answer={"co-changed with": lines}, semantics="heuristic")


def _run_rename(session: "GTSession", args: list[str]) -> CapabilityResult:
    _need(args, 2, TOOLS["gt-rename"].usage)
    return run_typed(session, "rename", {"symbol": args[0], "new_name": args[1]})


def _run_tool_map(session: "GTSession", args: list[str]) -> CapabilityResult:
    return run_typed(session, "tool_map", {})


def _run_failures(session: "GTSession", args: list[str]) -> CapabilityResult:
    return runtime.repeated_failure_state(session)


def _run_help(session: "GTSession", args: list[str]) -> CapabilityResult:
    return wrap(session, "help", semantics="exact", answer={"tools": [
        {"name": f"{spec.usage}  - {spec.summary}"} for spec in TOOLS.values()
    ]})


def _shape_query(answer: Any, _args: list[str]) -> Any:
    """Fused RRF rows carry only stable ids; locations live in provenance."""
    if not isinstance(answer, dict):
        return answer
    provenance = answer.get("provenance") or {}
    source: list[dict[str, Any]] = []
    tests: list[dict[str, Any]] = []
    for row in answer.get("fused") or []:
        origin = provenance.get(row.get("stable_id")) or {}
        path = origin.get("file_path") or ""
        item = {
            "file_path": path,
            "line": origin.get("start_line"),
            "qualified_name": origin.get("qualified_name") or origin.get("name")
            or row.get("snippet"),
            "kind": origin.get("label"),
        }
        # Natural-language task text matches descriptive test names; tests
        # would otherwise crowd out the code the agent has to change.
        (tests if _looks_like_test(path) else source).append(item)
    return {"1 source": source[:_QUERY_SOURCE_SHOWN], "2 related tests": tests[:_QUERY_TESTS_SHOWN]}


def _shape_modules(answer: Any, _args: list[str]) -> Any:
    if not isinstance(answer, dict) or "modules" not in answer:
        return answer
    flat: dict[str, Any] = {}
    for module in answer["modules"]:
        flat[f"cluster {module['cluster']}"] = module["files moving with it"]
    return flat


def _shape_tests(answer: Any, _args: list[str]) -> Any:
    if not isinstance(answer, dict):
        return answer
    if "tests reaching these files" in answer:
        return answer
    return {"covering tests": [
        {"file_path": row.get("file"), "confidence": row.get("confidence")}
        for row in answer.get("tests") or []
    ]}


def _shape_routes(answer: Any, args: list[str]) -> Any:
    if not isinstance(answer, dict):
        return answer
    needle = args[0] if args else ""
    rows = []
    for route in answer.get("routes") or []:
        haystack = " ".join(str(route.get(key) or "") for key in
                            ("route", "handler", "handler_file"))
        if needle and needle not in haystack:
            continue
        middleware = ", ".join(str(item.get("name")) for item in route.get("middleware") or [])
        injections = ", ".join(str(item.get("provider")) for item in route.get("injections") or [])
        extras = "".join((f" middleware=[{middleware}]" if middleware else "",
                          f" injects=[{injections}]" if injections else ""))
        rows.append({
            "file_path": route.get("handler_file"),
            "line": route.get("handler_line"),
            "name": f"{route.get('method') or 'ANY'} {route.get('route')} -> "
                    f"{route.get('handler')}{extras}",
        })
    return {"routes": rows}


def _run_slice(session: "GTSession", args: list[str]) -> CapabilityResult:
    usage = TOOLS["gt-slice"].usage
    _need(args, 2, usage)
    direction = args[2] if len(args) > 2 else "backward"
    if direction not in ("backward", "forward"):
        raise ToolUsageError(usage)
    return analysis.slice(session, args[0], _int(args[1], usage), direction)


def _run_taint(session: "GTSession", args: list[str]) -> CapabilityResult:
    _need(args, 1, TOOLS["gt-taint"].usage)
    return analysis.taint(session, args[0], args[1] if len(args) > 1 else None)


def _run_verify(session: "GTSession", args: list[str]) -> CapabilityResult:
    return runtime.last_test_result(session)


def _joined(prefix: str) -> Callable[[list[str]], str]:
    return lambda args: f"{prefix} {' '.join(args)}".strip()


TOOLS: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in (
        ToolSpec("gt-query", 'gt-query "<concept or error text>"',
                 "rank files and symbols relevant to a concept",
                 _run_query, _joined("query"), "gt-context <symbol> for the top hit",
                 shape=_shape_query, core=True),
        ToolSpec("gt-context", "gt-context <symbol> [file]",
                 "definition, callers, callees and flows of one symbol",
                 _run_context, _joined("context"), "gt-impact <symbol> before editing it",
                 core=True),
        ToolSpec("gt-callers", "gt-callers <symbol> [depth]",
                 "who calls this symbol, by call depth",
                 _run_callers, _joined("callers")),
        ToolSpec("gt-impact", "gt-impact <symbol> [file]",
                 "what may break if this symbol changes (callers to depth 3)",
                 _run_impact, _joined("impact"), "gt-tests <file> to find tests to run",
                 core=True),
        ToolSpec("gt-refs", "gt-refs <symbol> [file]",
                 "graph references to a symbol",
                 _run_refs, _joined("references")),
        ToolSpec("gt-def", "gt-def <symbol> [file]",
                 "where a symbol is defined",
                 _run_def, _joined("definition")),
        ToolSpec("gt-flows", 'gt-flows ["<concept>"]',
                 "execution flows (entry point -> steps)",
                 _run_flows, _joined("flows")),
        ToolSpec("gt-tests", "gt-tests <file> [file...]",
                 "tests that cover the given source files",
                 _run_tests, _joined("tests for"), shape=_shape_tests, core=True),
        ToolSpec("gt-routes", "gt-routes [route|handler|file filter]",
                 "HTTP routes, handlers, middleware and injections",
                 _run_routes, _joined("routes"), shape=_shape_routes),
        ToolSpec("gt-slice", "gt-slice <function> <line> [backward|forward]",
                 "statements that affect (or are affected by) a line",
                 _run_slice, _joined("slice")),
        ToolSpec("gt-taint", "gt-taint <source-symbol> [sink-symbol]",
                 "call paths from a source to a sink",
                 _run_taint, _joined("taint")),
        ToolSpec("gt-verify", "gt-verify",
                 "the last test/build result GT observed, vs the task baseline",
                 _run_verify, lambda _args: "last test result", reads_graph=False, core=True),
        ToolSpec("gt-changes", "gt-changes [file...]",
                 "callers and tests affected by your edits so far (or by the given files)",
                 _run_changes, _joined("impact of edits"), "gt-tests <file> for the listed files",
                 core=True),
        ToolSpec("gt-check", "gt-check <file>",
                 "parse a file you edited and report syntax errors",
                 _run_check, _joined("syntax"), reads_graph=False, core=True),
        ToolSpec("gt-help", "gt-help", "list every GT command",
                 _run_help, lambda _args: "commands", reads_graph=False, core=True),
        ToolSpec("gt-api", "gt-api <route|handler>",
                 "clients and callers of an HTTP route or handler",
                 _run_api, _joined("api impact")),
        ToolSpec("gt-shape", "gt-shape <interface|class> [file]",
                 "does each implementation still match the interface",
                 _run_shape, _joined("shape")),
        ToolSpec("gt-calls", "gt-calls <function> [file]",
                 "how each call inside a function resolved (target, ambiguous, external)",
                 _run_calls, _joined("calls in")),
        ToolSpec("gt-module", "gt-module <file>",
                 "the cluster of files this file belongs with",
                 _run_module, _joined("module cluster"), shape=_shape_modules),
        ToolSpec("gt-cochange", "gt-cochange <file>",
                 "files that historically change together with this one",
                 _run_cochange, _joined("co-change")),
        ToolSpec("gt-rename", "gt-rename <symbol> <new_name>",
                 "every site a rename must touch",
                 _run_rename, _joined("rename")),
        ToolSpec("gt-tools", "gt-tools",
                 "registered tool/command handlers (MCP, CLI)",
                 _run_tool_map, lambda _args: "tool handlers"),
        ToolSpec("gt-failures", "gt-failures",
                 "failures that keep recurring after your edits",
                 _run_failures, lambda _args: "recurring failures", reads_graph=False),
    )
}


@dataclass
class ToolMetrics:
    calls_by_name: dict[str, int] = field(default_factory=dict)
    answered: int = 0
    no_answer: int = 0
    usage_errors: int = 0
    faults: int = 0
    bytes_delivered: int = 0
    elapsed_ms: int = 0
    delivered_texts: list[str] = field(default_factory=list)

    @property
    def total_calls(self) -> int:
        return sum(self.calls_by_name.values())

    def as_dict(self) -> dict[str, Any]:
        return {
            "gt_tool_calls": self.total_calls,
            "gt_tool_calls_by_name": dict(sorted(self.calls_by_name.items())),
            "gt_tool_answered": self.answered,
            "gt_tool_no_answer": self.no_answer,
            "gt_tool_usage_errors": self.usage_errors,
            "gt_tool_faults": self.faults,
            "gt_tool_bytes_delivered": self.bytes_delivered,
            "gt_tool_elapsed_ms": self.elapsed_ms,
        }


class ToolDispatcher:
    """Resolve one tool call against the live session. Thread-safe."""

    def __init__(self, session: "GTSession", *, max_bytes: int = DEFAULT_TOOL_OUTPUT_BYTES):
        self.session = session
        self.max_bytes = max_bytes
        self.metrics = ToolMetrics()
        self._lock = threading.Lock()

    def _refresh_if_stale(self) -> None:
        adapter = getattr(self.session, "_engine", None)
        if adapter is None:
            return
        if (
            getattr(adapter, "graph_db", None)
            and not getattr(adapter, "graph_fresh", True)
            and self.session.capability_active("graph_refresh")
            and self.session.capability_active("graph_queries")
        ):
            adapter.refresh_graph(phase="graph_query")

    def _scope_key(self) -> tuple[Any, ...]:
        adapter = getattr(self.session, "_engine", None)
        return ("tool", id(adapter), getattr(adapter, "global_action", 0),
                getattr(adapter, "_edit_epoch", 0))

    def _journal(self, **row: Any) -> None:
        store = getattr(getattr(self.session, "_engine", None), "store", None)
        if store is not None:
            try:
                store.append("gt_tool_call", **row)
            except Exception:  # noqa: BLE001 - journaling never fails a tool call
                pass

    def dispatch(self, name: str, args: list[str]) -> tuple[str, int]:
        spec = TOOLS.get(name)
        if spec is None:
            with self._lock:
                self.metrics.calls_by_name[name] = self.metrics.calls_by_name.get(name, 0) + 1
                self.metrics.usage_errors += 1
            return f"[GT] unknown tool {name}; available: {', '.join(TOOLS)}", EXIT_USAGE
        with self._lock:
            started = time.perf_counter()
            self.metrics.calls_by_name[name] = self.metrics.calls_by_name.get(name, 0) + 1
            status = "fault"
            try:
                if spec.reads_graph:
                    self._refresh_if_stale()
                with snapshot_scope(self._scope_key()):
                    result = spec.run(self.session, list(args))
                if spec.shape is not None:
                    result = dataclasses.replace(
                        result, answer=spec.shape(result.answer, list(args)))
                text, has_answer = render_result(
                    spec.title(list(args)), result,
                    next_hint=spec.next_hint, max_bytes=self.max_bytes,
                )
                code = EXIT_ANSWER if has_answer else EXIT_NO_ANSWER
                status = result.status
                if has_answer:
                    self.metrics.answered += 1
                else:
                    self.metrics.no_answer += 1
            except ToolUsageError as exc:
                text, code, status = f"usage: {exc}", EXIT_USAGE, "usage_error"
                self.metrics.usage_errors += 1
            except Exception as exc:  # noqa: BLE001 - never a traceback to the agent
                text = f"[GT] {name}: no answer (internal_error:{type(exc).__name__})"
                code = EXIT_NO_ANSWER
                self.metrics.faults += 1
            elapsed = int(round((time.perf_counter() - started) * 1000))
            size = len(text.encode("utf-8"))
            self.metrics.bytes_delivered += size
            self.metrics.elapsed_ms += elapsed
            if code == EXIT_ANSWER:
                self.metrics.delivered_texts.append(text)
            self._journal(tool=name, args=list(args)[:6], status=status,
                          exit_code=code, bytes=size, elapsed_ms=elapsed)
            return text, code


def _handler_for(dispatcher: ToolDispatcher) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - keep runner stdout clean
            return

        def _send(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 - http.server API
            if self.path == "/health":
                self._send(200, {"ok": True, "tools": sorted(TOOLS)})
            else:
                self._send(404, {"error": "not_found"})

        def do_POST(self) -> None:  # noqa: N802 - http.server API
            if not self.path.startswith("/tool/"):
                self._send(404, {"error": "not_found"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                payload = json.loads(self.rfile.read(length) or b"{}")
                args = [str(arg) for arg in payload.get("args", [])]
            except (ValueError, TypeError, AttributeError):
                self._send(400, {"text": "usage: malformed request", "exit_code": EXIT_USAGE})
                return
            text, code = dispatcher.dispatch(self.path[len("/tool/"):], args)
            self._send(200, {"text": text, "exit_code": code})

    return Handler


class ToolServer:
    """HTTP front for :class:`ToolDispatcher` on a daemon thread."""

    def __init__(self, dispatcher: ToolDispatcher, host: str = "127.0.0.1", port: int = 0):
        self.dispatcher = dispatcher
        self._server = HTTPServer((host, port), _handler_for(dispatcher))
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="gt-tool-server", daemon=True,
        )

    @property
    def address(self) -> tuple[str, int]:
        host, port = self._server.server_address[:2]
        return str(host), int(port)

    @property
    def url(self) -> str:
        host, port = self.address
        return f"http://{host}:{port}"

    def start(self) -> "ToolServer":
        self._thread.start()
        host, port = self.address
        print(f"{READY_PREFIX}{host}:{port}", file=sys.stderr, flush=True)
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()


def parse_ready_line(line: str) -> tuple[str, int] | None:
    """Parse the READY line; the port is the LAST colon segment so IPv6
    forms such as ``[::1]:4848`` parse correctly."""
    if not line.startswith(READY_PREFIX):
        return None
    rest = line[len(READY_PREFIX):].strip()
    host, _, port = rest.rpartition(":")
    if not host or not port.isdigit():
        return None
    return host, int(port)


_WRAPPER = '''#!{python}
import json, sys, urllib.request
NAME = {name!r}
URL = {url!r}
try:
    request = urllib.request.Request(
        URL + "/tool/" + NAME,
        data=json.dumps({{"args": sys.argv[1:]}}).encode("utf-8"),
        headers={{"Content-Type": "application/json"}},
    )
    with urllib.request.urlopen(request, timeout={timeout}) as response:
        reply = json.loads(response.read().decode("utf-8"))
    print(reply.get("text", ""))
    sys.exit(int(reply.get("exit_code", 1)))
except Exception as exc:
    print("[GT] " + NAME + ": no answer (tool server unavailable: " + type(exc).__name__ + ")")
    sys.exit(1)
'''


def install_wrappers(
    bin_dir: str | os.PathLike[str],
    url: str,
    *,
    python: str = sys.executable,
    timeout_seconds: int = 60,
) -> tuple[Path, ...]:
    """Write one executable ``gt-*`` script per tool into ``bin_dir``."""
    target = Path(bin_dir)
    target.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name in TOOLS:
        path = target / name
        path.write_text(
            _WRAPPER.format(python=python, name=name, url=url, timeout=int(timeout_seconds)),
            encoding="utf-8",
        )
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        written.append(path)
    return tuple(written)


def tool_reference(*, core_only: bool = True) -> str:
    """One line per tool for the attached system prompt. Only the core set is
    paid on every request; ``gt-help`` lists the rest on demand."""
    return "\n".join(f"- `{spec.usage}`: {spec.summary}"
                     for spec in TOOLS.values() if spec.core or not core_only)


__all__ = [
    "EXIT_ANSWER",
    "EXIT_NO_ANSWER",
    "EXIT_USAGE",
    "READY_PREFIX",
    "TOOLS",
    "ToolDispatcher",
    "ToolMetrics",
    "ToolServer",
    "ToolSpec",
    "ToolUsageError",
    "install_wrappers",
    "parse_ready_line",
    "tool_reference",
]
