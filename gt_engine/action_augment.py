"""GT facts attached to the agent's edits and failing test runs.

``grep_augment`` covers the agent's searches. The two other actions every
trajectory repeats are editing a file and running tests, and those got no GT
at all: the patch-impact (F13), test (F20), syntax (F1) and taint (F19)
answers, and the CFG/data-dependence slice (F14-F17), were reachable only
through tools the agent rarely called. This module appends a short ``[GT]``
block to the observation of the action itself:

* after an edit: the functions it changed on the amended graph, their
  callers, the tests that reach the edited files, parse errors, and a
  sink the changed function reaches;
* after a failing test run: the failing source line's enclosing function,
  the backward slice of that line, and whether the same failure has
  already been seen after an edit.

The same rules as grep augmentation hold: anchored to what the agent just
did, silent when the graph has nothing, never blocking, bounded in bytes.
"""
from __future__ import annotations

import hashlib
import re
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Iterable, Mapping

from gt_engine.tool_render import AUGMENT_OUTPUT_BYTES, cap_text

if TYPE_CHECKING:  # pragma: no cover - typing only
    from gt_engine.gt_session import GTSession

MAX_CHANGED_SHOWN = 3
MAX_CALLERS_SHOWN = 4
MAX_TESTS_SHOWN = 4
MAX_SLICE_LINES = 6
MAX_TAINT_CHECKS = 2
# The edit block is paid on the agent's clock after every edit. Callers and
# tests come first; taint (a dataflow fixpoint) runs only while the block is
# still cheap, so a large repository never turns an edit into a long wait.
EDIT_OPTIONAL_BUDGET_SECONDS = 5.0

_TEST_COMMAND = re.compile(
    r"\b(pytest|py\.test|unittest|nosetests|tox|go\s+test|cargo\s+test|npm\s+(run\s+)?test|"
    r"yarn\s+test|pnpm\s+test|jest|vitest|mocha|rspec|phpunit|mvn\s+test|gradle\w*\s+test|"
    r"make\s+test|ctest|runtests)\b|(^|[\s/])test[\w.-]*\.(py|sh)\b",
)
_PY_FRAME = re.compile(r'File "([^"]+)", line (\d+), in ([A-Za-z_<][\w<>]*)')
_PATH_LINE = re.compile(r"((?:[\w.\-]+/)*[\w.\-]+\.(?:py|go|rs|ts|tsx|js|jsx|mjs|java|rb|php|c|cc|cpp|h))"
                        r":(\d+)")
_ERROR_LINE = re.compile(r"^(?:E\s+)?([A-Za-z_][\w.]*(?:Error|Exception|Failure|panic))\b.*$", re.M)
_TEST_PATH = re.compile(r"(^|/)(tests?|__tests__|spec)/|(^|/)test_[^/]*$|_test\.[a-z]+$|\.(test|spec)\.[a-z]+$")


def is_test_command(command: str) -> bool:
    return bool(_TEST_COMMAND.search(command))


def _repo_relative(path: str, repo_root: str) -> str:
    """Traceback paths are absolute inside the container (/testbed/x.py)."""
    normalized = path.replace("\\", "/")
    root = repo_root.replace("\\", "/").rstrip("/")
    if root and normalized.startswith(root + "/"):
        return normalized[len(root) + 1:]
    for marker in ("/testbed/", "/app/", "/workspace/", "/repo/", "/src/repo/"):
        if marker in normalized:
            return normalized.split(marker, 1)[1]
    return normalized[2:] if normalized.startswith("./") else normalized


def failure_frames(output: str, repo_root: str) -> list[tuple[str, int]]:
    """(repo-relative path, line) of every source location the output names,
    innermost last, de-duplicated, excluding installed packages."""
    frames: list[tuple[str, int]] = []
    for match in _PY_FRAME.finditer(output):
        frames.append((match.group(1), int(match.group(2))))
    if not frames:
        frames = [(match.group(1), int(match.group(2))) for match in _PATH_LINE.finditer(output)]
    out: list[tuple[str, int]] = []
    for path, line in frames:
        if "site-packages" in path or "/lib/python" in path or "node_modules" in path:
            continue
        rel = _repo_relative(path, repo_root)
        if (rel, line) not in out:
            out.append((rel, line))
    return out


def _enclosing_function(conn: Any, path: str, line: int) -> tuple[str, int] | None:
    row = conn.execute(
        "SELECT name, start_line FROM nodes WHERE file_path = ? AND label IN ('Function', 'Method')"
        " AND start_line <= ? AND end_line >= ? ORDER BY end_line - start_line LIMIT 1",
        (path, line, line)).fetchone()
    return (row[0], int(row[1])) if row else None


def _failure_signature(output: str, frames: list[tuple[str, int]]) -> str:
    errors = _ERROR_LINE.findall(output)
    basis = "|".join([*(f"{p}:{n}" for p, n in frames[-3:]), *errors[-2:]])
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16] if basis else ""


@dataclass
class ActionAugmentMetrics:
    edit_calls: int = 0
    edit_hits: int = 0
    failure_calls: int = 0
    failure_hits: int = 0
    errors: int = 0
    time_ms: int = 0
    bytes_delivered: int = 0
    features: dict[str, int] = field(default_factory=dict)

    def note(self, *features: str) -> None:
        for feature in features:
            self.features[feature] = self.features.get(feature, 0) + 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "edit_augment_calls": self.edit_calls,
            "edit_augment_hits": self.edit_hits,
            "failure_augment_calls": self.failure_calls,
            "failure_augment_hits": self.failure_hits,
            "action_augment_errors": self.errors,
            "action_augment_time_s": round(self.time_ms / 1000.0, 3),
            "action_augment_bytes_delivered": self.bytes_delivered,
            "action_augment_features": dict(sorted(self.features.items())),
        }


def _site(row: Mapping[str, Any]) -> str:
    name = row.get("qualified_name") or row.get("name") or "?"
    path, line = row.get("file_path") or "", row.get("call_line") or row.get("line") or ""
    tier = row.get("trust_tier")
    suffix = f" [{tier}]" if tier and tier != "CERTIFIED" else ""
    return f"{name} ({path}:{line}){suffix}" if path else f"{name}{suffix}"


def _listed(rows: list[Any], limit: int) -> str:
    shown = ", ".join(_site(row) if isinstance(row, Mapping) else str(row) for row in rows[:limit])
    more = len(rows) - limit
    return shown + (f" (+{more} more)" if more > 0 else "")


class ActionAugmenter:
    """Builds the ``[GT]`` block for one edit or one failing test run."""

    def __init__(self, session: "GTSession", *, max_bytes: int = AUGMENT_OUTPUT_BYTES):
        self.session = session
        self.max_bytes = max_bytes
        self.metrics = ActionAugmentMetrics()
        self.delivered_texts: list[str] = []
        self._failures_seen: dict[str, int] = {}
        self._lock = threading.Lock()

    def _journal(self, **row: Any) -> None:
        store = getattr(getattr(self.session, "_engine", None), "store", None)
        if store is not None:
            try:
                store.append("gt_action_augment", **row)
            except Exception:  # noqa: BLE001 - journaling never fails the action
                pass

    def _repo_root(self) -> str:
        return str(getattr(getattr(self.session, "_engine", None), "repo_root", "") or "")

    def _finish(self, kind: str, lines: list[str], started: float) -> str:
        self.metrics.time_ms += int(round((time.perf_counter() - started) * 1000))
        if len(lines) <= 1:
            self._journal(kind=kind, outcome="silent")
            return ""
        text = cap_text("\n".join(lines), self.max_bytes)
        self.metrics.bytes_delivered += len(text.encode("utf-8"))
        self.delivered_texts.append(text)
        self._journal(kind=kind, outcome="hit", bytes=len(text.encode("utf-8")))
        return text

    # -- edits ---------------------------------------------------------------

    def after_edit(self, changes: Mapping[str, tuple[str | None, str | None]],
                   syntax: Iterable[Mapping[str, Any]] = ()) -> str:
        """``changes`` maps each edited path to its (before, after) text."""
        paths = [path for path in changes if path]
        if not paths:
            return ""
        with self._lock:
            self.metrics.edit_calls += 1
            started = time.perf_counter()
            try:
                lines = ["[GT] after your edit (graph updated):"]
                lines += self._syntax_lines(syntax)
                lines += self._impact_lines(changes)
                lines += self._test_lines(paths)
            except Exception as exc:  # noqa: BLE001 - enrichment is silent on failure
                self.metrics.errors += 1
                self._journal(kind="edit", outcome=f"error:{type(exc).__name__}")
                return ""
            text = self._finish("edit", lines, started)
            if text:
                self.metrics.edit_hits += 1
            return text

    def _syntax_lines(self, syntax: Iterable[Mapping[str, Any]]) -> list[str]:
        broken = [row for row in syntax if row.get("valid") is False]
        if not broken:
            return []
        self.metrics.note("F1")
        return [f"  PARSE ERROR {row.get('path')}"
                + (f":{row.get('line')}" if row.get("line") else "")
                + f" ({row.get('error') or ', '.join(row.get('diagnostics') or ()) or 'syntax'})"
                for row in broken]

    def _impact_lines(self, changes: Mapping[str, tuple[str | None, str | None]]) -> list[str]:
        started = time.perf_counter()
        from gt_engine.tool_server import _impact_of_edits, refresh_if_stale

        refresh_if_stale(self.session)
        edited = {path: {"before": before or "", "after": after or ""}
                  for path, (before, after) in changes.items()}
        impact = _impact_of_edits(self.session, edited)
        changed = impact.get("changed functions") or []
        if not changed:
            return []
        self.metrics.note("F13")
        lines = [f"  changed: {_listed(changed, MAX_CHANGED_SHOWN)}"]
        for row in changed[:MAX_CHANGED_SHOWN]:
            name = row.get("name")
            callers = impact.get(f"callers of {name}") or []
            if callers:
                self.metrics.note("F4")
                lines.append(f"    {name} is called by: {_listed(callers, MAX_CALLERS_SHOWN)}")
            else:
                lines.append(f"    {name}: no callers in the graph")
        lines += self._route_lines(changed[:MAX_CHANGED_SHOWN])
        if time.perf_counter() - started < EDIT_OPTIONAL_BUDGET_SECONDS:
            lines += self._taint_lines([str(row.get("name")) for row in changed[:MAX_TAINT_CHECKS]])
        else:
            self._journal(kind="edit", skipped="taint_over_budget")
        return lines

    def _taint_lines(self, names: list[str]) -> list[str]:
        from gt_engine.capabilities import analysis

        lines = []
        for name in names:
            result = analysis.taint(self.session, name)
            answer = result.answer if isinstance(result.answer, dict) else {}
            sinks = answer.get("heuristic_sinks_reached_certified") or answer.get("heuristic_sinks_reached")
            if sinks:
                self.metrics.note("F19")
                lines.append(f"    {name} reaches sensitive sink(s): {', '.join(map(str, sinks[:3]))}"
                             f" (`gt-taint {name}` for the path)")
        return lines

    def _route_lines(self, changed: list[Mapping[str, Any]]) -> list[str]:
        from gt_engine.capabilities._query import graph_conn
        from gt_engine.graph_facts import _framework, _guarded

        conn = graph_conn(self.session)
        if conn is None:
            return []
        lines = []
        try:
            for row in changed:
                node = conn.execute(
                    "SELECT id FROM nodes WHERE file_path = ? AND name = ? AND start_line = ?"
                    " AND label IN ('Function', 'Method') LIMIT 1",
                    (row.get("file_path"), row.get("name"), row.get("line"))).fetchone()
                facts = _guarded(lambda: _framework(conn, node[0])) if node else None
                for fact in facts or ():
                    self.metrics.note(*(("F8", "F18") if fact.startswith("handles route") else ("F8",)))
                    lines.append(f"    {row.get('name')} {fact}")
        finally:
            conn.close()
        return lines

    def _test_lines(self, paths: list[str]) -> list[str]:
        from gt_engine.tool_server import _tests_by_reachability

        source = [path for path in paths if not _TEST_PATH.search(path)]
        if not source:
            return []
        reached = _tests_by_reachability(self.session, source)
        if not reached:
            return []
        self.metrics.note("F20")
        return [f"  tests reaching {', '.join(source[:3])}: {_listed(reached, MAX_TESTS_SHOWN)}"]

    # -- failing test runs ---------------------------------------------------

    def after_failure(self, command: str, output: str, returncode: int | None) -> str:
        if returncode in (None, 0) or not is_test_command(command):
            return ""
        with self._lock:
            self.metrics.failure_calls += 1
            started = time.perf_counter()
            try:
                lines = ["[GT] about this failure:"]
                frames = failure_frames(output, self._repo_root())
                lines += self._location_lines(frames)
                lines += self._repeat_lines(output, frames)
            except Exception as exc:  # noqa: BLE001 - enrichment is silent on failure
                self.metrics.errors += 1
                self._journal(kind="failure", outcome=f"error:{type(exc).__name__}")
                return ""
            text = self._finish("failure", lines, started)
            if text:
                self.metrics.failure_hits += 1
            return text

    def _location_lines(self, frames: list[tuple[str, int]]) -> list[str]:
        from gt_engine.capabilities._query import graph_conn

        if not frames:
            return []
        conn = graph_conn(self.session)
        if conn is None:
            return []
        located: list[tuple[str, int, str, int]] = []
        try:
            for path, line in frames:
                enclosing = _enclosing_function(conn, path, line)
                if enclosing is not None:
                    located.append((path, line, *enclosing))
        finally:
            conn.close()
        if not located:
            return []
        # The innermost non-test frame is where the wrong value surfaced; the
        # innermost test frame is the assertion that noticed it.
        source = [row for row in located if not _TEST_PATH.search(row[0])]
        tests = [row for row in located if _TEST_PATH.search(row[0])]
        lines = []
        if tests:
            path, line, name, _start = tests[-1]
            lines.append(f"  failing test: {name} ({path}:{line})")
            self.metrics.note("F20")
        if source:
            path, line, name, _start = source[-1]
            lines.append(f"  failure surfaced in: {name} ({path}:{line})")
            lines += self._slice_lines(name, path, line)
        return lines

    def _slice_lines(self, name: str, path: str, line: int) -> list[str]:
        from gt_engine.capabilities import analysis
        from gt_engine.tool_server import _source_line

        result = analysis.slice(self.session, name, line, "backward", path=path)
        answer = result.answer if isinstance(result.answer, dict) else {}
        for item in answer.get("slices") or []:
            numbers = [n for n in (item.get("slice_lines") or []) if n != line][-MAX_SLICE_LINES:]
            if not numbers:
                continue
            self.metrics.note("F14", "F15", "F16", "F17")
            rows = [f"    {path}:{n}: {_source_line(self.session, path, n)}" for n in numbers]
            return [f"  line {line} depends on (backward slice; control + data):", *rows]
        return []

    def _repeat_lines(self, output: str, frames: list[tuple[str, int]]) -> list[str]:
        signature = _failure_signature(output, frames)
        if not signature:
            return []
        epoch = int(getattr(getattr(self.session, "_engine", None), "_edit_epoch", 0) or 0)
        previous = self._failures_seen.get(signature)
        self._failures_seen[signature] = epoch
        if previous is None or previous == epoch:
            return []
        self.metrics.note("F20")
        return ["  same failure as before your last edit(s): the change did not reach"
                " this path; re-check the location above"]


__all__ = [
    "ActionAugmenter",
    "ActionAugmentMetrics",
    "failure_frames",
    "is_test_command",
]
