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
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Iterable, Mapping

from gt_engine.attached_budget import DeliveryBudget, Draft, compact_lines
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


# Lines the detail budget never compacts away: a broken parse or a reached
# sink is worth more than any byte it costs.
_ALWAYS_SHOWN = re.compile(r"PARSE ERROR|sink")


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


def _enclosing_function(conn: Any, path: str, line: int) -> tuple[str, int, Any] | None:
    row = conn.execute(
        "SELECT name, start_line, id FROM nodes WHERE file_path = ? AND label IN ('Function', 'Method')"
        " AND start_line <= ? AND end_line >= ? ORDER BY end_line - start_line LIMIT 1",
        (path, line, line)).fetchone()
    return (row[0], int(row[1]), row[2]) if row else None


def _changed_line_ranges_before(before: str, after: str) -> list[tuple[int, int]]:
    """1-based line ranges of ``before`` that the edit replaced or deleted
    (an insertion maps to the line it lands after)."""
    import difflib

    ranges = []
    matcher = difflib.SequenceMatcher(a=before.splitlines(), b=after.splitlines(), autojunk=False)
    for tag, i1, i2, _j1, _j2 in matcher.get_opcodes():
        if tag != "equal":
            ranges.append((max(i1, 1), max(i2, i1 + 1)))
    return ranges


MAX_SLICE_TARGETS = 4


def _slice_targets(before: str, after: str) -> list[int]:
    """Lines of ``after`` worth slicing: the LAST real statement of each
    changed hunk (a return or assignment has the richest backward slice), in
    file order. Real statements come from the AST, so a ``def`` line, a
    docstring or a comment - what an added function starts with - is never
    chosen; an unparsable file falls back to the first changed line."""
    import ast
    import difflib

    try:
        tree = ast.parse(after)
    except (SyntaxError, ValueError):
        first = _first_changed_line(before, after)
        return [first] if first else []
    statements: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.stmt) or isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            continue  # a docstring
        statements.add(node.lineno)
    matcher = difflib.SequenceMatcher(a=before.splitlines(), b=after.splitlines(), autojunk=False)
    targets = []
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        inside = [n for n in range(j1 + 1, j2 + 1) if n in statements]
        if inside:
            targets.append(inside[-1])
    first = _first_changed_line(before, after)
    targets = targets[:MAX_SLICE_TARGETS]
    if first and first not in targets:
        targets.append(first)  # the pre-fix choice, kept as the last resort
    return targets


def _first_changed_line(before: str, after: str) -> int:
    """1-based line of ``after`` holding the first non-blank changed text."""
    import difflib

    new = after.splitlines()
    matcher = difflib.SequenceMatcher(a=before.splitlines(), b=new, autojunk=False)
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        for index in range(j1, j2):
            if new[index].strip():
                return index + 1
    return 0


def _changed_functions(conn: sqlite3.Connection,
                       changes: Mapping[str, tuple[str | None, str | None]],
                       preimages: Callable[[], Mapping[str, str]] | None = None,
                       ) -> list[tuple[Any, str, str, int]]:
    """(node id, name, path, line) of the innermost function around each
    changed range, for files whose baseline text is exactly what the graph
    indexed. The baseline is the edit's own pre-image, or - when an earlier
    edit already moved the file past the graph - the file before the agent
    first touched it, so the answer is every function changed since."""
    out: list[tuple[Any, str, str, int]] = []
    recorded: Mapping[str, str] | None = None
    for path, (before, after) in changes.items():
        row = conn.execute("SELECT content_hash FROM file_hashes WHERE file_path = ?", (path,)).fetchone()
        if row is None:
            continue
        if before is None or row[0] != hashlib.sha256(before.encode("utf-8")).hexdigest():
            if recorded is None:
                recorded = preimages() if preimages is not None else {}
            before = recorded.get(path)
            if before is None or row[0] != hashlib.sha256(before.encode("utf-8")).hexdigest():
                continue
        for start, end in _changed_line_ranges_before(before, after or ""):
            # A function around the change; else the class whose body it is in
            # (a new method, a class attribute) - its constructor callers and
            # users are what the edit can break.
            hit = conn.execute(
                "SELECT id, name, start_line FROM nodes WHERE file_path = ?"
                " AND label IN ('Function', 'Method', 'Class', 'Interface')"
                " AND start_line <= ? AND end_line >= ?"
                " ORDER BY label IN ('Class', 'Interface'), end_line - start_line LIMIT 1",
                (path, end, start)).fetchone()
            if hit and all(hit[0] != seen[0] for seen in out):
                out.append((hit[0], hit[1], path, int(hit[2])))
    return out


_NEW_DEFINITION = re.compile(
    r"^\s*(?:export\s+)?(?:async\s+)?(?:def|class|function|func|fn|interface|struct)\s+"
    r"(?:\([^)]*\)\s*)?([A-Za-z_$][\w$]*)")


def _added_definitions(changes: Mapping[str, tuple[str | None, str | None]]) -> list[tuple[str, str]]:
    """(name, path) of definitions the edit introduced."""
    import difflib

    added: list[tuple[str, str]] = []
    for path, (before, after) in changes.items():
        old = (before or "").splitlines()
        new = (after or "").splitlines()
        matcher = difflib.SequenceMatcher(a=old, b=new, autojunk=False)
        existing = {m.group(1) for m in map(_NEW_DEFINITION.match, old) if m}
        for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
            if tag in ("insert", "replace"):
                for line in new[j1:j2]:
                    match = _NEW_DEFINITION.match(line)
                    if match and match.group(1) not in existing and (match.group(1), path) not in added:
                        added.append((match.group(1), path))
    return added


def _exercised(conn: sqlite3.Connection, node_id: Any) -> list[dict[str, Any]]:
    """Non-test code a test function calls directly."""
    rows = conn.execute(
        "SELECT DISTINCT t.qualified_name, t.name, t.file_path, t.start_line, e.trust_tier FROM edges e"
        " JOIN nodes t ON t.id = e.target_id WHERE e.source_id = ? AND e.type = 'CALLS'"
        " AND COALESCE(t.is_test, 0) = 0 ORDER BY t.file_path, t.start_line LIMIT 25", (node_id,)).fetchall()
    return [{"qualified_name": q, "name": n, "file_path": p, "line": l, "trust_tier": tier}
            for q, n, p, l, tier in rows]


# The taint engine's sink-name markers, restricted to the unambiguous ones:
# "run", "write", "open", "send" and the like name half of every codebase.
_STRONG_SINK_MARKERS = frozenset({
    "eval", "exec", "system", "popen", "spawn", "subprocess", "check_output",
    "execute", "executemany", "shell", "pickle", "deserialize", "raw",
})
_SINK_REACH_DEPTH = 3


def _reached_sinks(conn: sqlite3.Connection, node_id: Any) -> list[str]:
    """Sink-like callees within a few CALLS hops of ``node_id``: resolved
    targets by name, unresolved call sites by their callee lexeme."""
    rows = conn.execute(
        "WITH RECURSIVE reach(id, depth) AS (SELECT ?, 0"
        " UNION SELECT e.target_id, r.depth + 1 FROM edges e JOIN reach r ON e.source_id = r.id"
        " WHERE e.type = 'CALLS' AND r.depth < ?)"
        " SELECT n.name FROM reach r JOIN nodes n ON n.id = r.id WHERE r.depth > 0"
        " UNION SELECT c.callee_lexeme FROM reach r JOIN edges h ON h.source_id = r.id"
        " AND h.type = 'HAS_CALLSITE' JOIN nodes c ON c.id = h.target_id",
        (node_id, _SINK_REACH_DEPTH)).fetchall()
    found = []
    for (name,) in rows:
        parts = [part.lower() for part in re.split(r"[.:]+", str(name or "")) if part]
        if parts and any(part in _STRONG_SINK_MARKERS for part in parts) and name not in found:
            found.append(str(name))
    return sorted(found)[:4]


def _python_enclosing(path: Path, line: int) -> tuple[str, int] | None:
    """Innermost function containing ``line`` in the file as it is now."""
    import ast

    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError, ValueError):
        return None
    best: tuple[str, int] | None = None
    best_span = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = getattr(node, "end_lineno", node.lineno)
            if node.lineno <= line <= end and (best_span is None or end - node.lineno < best_span):
                best, best_span = (node.name, node.lineno), end - node.lineno
    return best


def _python_slice(path: Path, function: str, line: int) -> list[int]:
    """Backward slice on the current source with the runtime CFG (the wheel's
    ``slice_at_line``): no graph involved, so it is exact after edits."""
    try:
        from groundtruth.runtime.cfg_analysis import slice_at_line

        result = slice_at_line(path.read_text(encoding="utf-8", errors="replace"), function, line)
    except Exception:  # noqa: BLE001 - a slice the CFG cannot build is absent
        return []
    return [int(n) for n in result.get("lines") or []]


def _stored_slice(conn: sqlite3.Connection, path: Path, node_id: Any, name: str, line: int) -> list[int]:
    """Backward slice over the producer's persisted CFG (JS/TS/Go/Java)."""
    try:
        from groundtruth.runtime.cfg_store import analyze_stored

        language = conn.execute("SELECT language FROM nodes WHERE id = ?", (node_id,)).fetchone()
        analysis = analyze_stored(conn, int(node_id), source=path.read_text(encoding="utf-8", errors="replace"),
                                  function_name=name, language=str((language or [""])[0] or ""))
        return sorted(int(n) for n in analysis.backward_slice(line))
    except Exception:  # noqa: BLE001 - no persisted CFG / no statement at that line
        return []

class Relocator:
    """Pre-edit graph lines -> the file as the agent sees it now.

    The edit block reads the graph from before the edit; a caller in a file
    that changed since (this edit or an earlier one) has shifted. Replay
    audit of runs 36336*: 11 of 16 "is called by" locations pointed at the
    wrong line of the just-edited file. Lines map through the diff between
    the text the graph indexed and the current text; a line that was itself
    rewritten maps to no line, and the row says "edited since"."""

    def __init__(self, conn: sqlite3.Connection, root: Path,
                 preimages: Callable[[], Mapping[str, str]]):
        self.conn = conn
        self.root = root
        self._preimages = preimages
        self._recorded: Mapping[str, str] | None = None
        self._maps: dict[str, dict[int, int] | None] = {}

    def _map(self, path: str) -> dict[int, int] | None:
        """None: file unchanged since indexing (identity)."""
        if path in self._maps:
            return self._maps[path]
        import difflib

        row = self.conn.execute("SELECT content_hash FROM file_hashes WHERE file_path = ?", (path,)).fetchone()
        try:
            current = (self.root / path).read_bytes()
        except OSError:
            current = None
        if row is None or current is None or row[0] == hashlib.sha256(current).hexdigest():
            self._maps[path] = None
            return None
        if self._recorded is None:
            self._recorded = self._preimages()
        baseline = self._recorded.get(path)
        mapping: dict[int, int] = {}
        if baseline is not None and hashlib.sha256(baseline.encode("utf-8")).hexdigest() == row[0]:
            matcher = difflib.SequenceMatcher(
                a=baseline.splitlines(), b=current.decode("utf-8", "replace").splitlines(), autojunk=False)
            for tag, i1, i2, j1, _j2 in matcher.get_opcodes():
                if tag == "equal":
                    for offset in range(i2 - i1):
                        mapping[i1 + offset + 1] = j1 + offset + 1
        self._maps[path] = mapping
        return mapping

    def to_indexed(self, path: str, line: int) -> int | None:
        """Current-file line -> the line of the indexed text (None if rewritten)."""
        mapping = self._map(path)
        if mapping is None:
            return line
        reverse = {new: old for old, new in mapping.items()}
        return reverse.get(line)

    def rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for row in rows:
            mapping = self._map(str(row.get("file_path") or ""))
            if mapping is None:
                out.append(row)
                continue
            key = "call_line" if row.get("call_line") else "line"
            moved = mapping.get(int(row.get(key) or 0))
            out.append({**row, key: moved} if moved else {**row, "edited_since": True})
        return out


def _direct_callers(conn: sqlite3.Connection, node_id: Any) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT DISTINCT s.qualified_name, s.name, s.file_path, e.source_line, e.trust_tier,"
        " e.resolution_method FROM edges e"
        " JOIN nodes s ON s.id = e.source_id WHERE e.target_id = ? AND e.type = 'CALLS'"
        " AND COALESCE(e.trust_tier, '') != 'SPECULATIVE'"
        " ORDER BY s.file_path, e.source_line LIMIT 25", (node_id,)).fetchall()
    # An edge resolved through a passed/stored function value is an indirect
    # call (F6): label it, since changing the target changes that callback.
    return [{"qualified_name": qualified, "name": name, "file_path": path, "line": line,
             "trust_tier": "via function value" if method == "callable_value" else tier}
            for qualified, name, path, line, tier, method in rows]


def _indexed_as_on_disk(conn: sqlite3.Connection, root: Path, path: str) -> bool:
    row = conn.execute("SELECT content_hash FROM file_hashes WHERE file_path = ?", (path,)).fetchone()
    try:
        data = (root / path).read_bytes()
    except OSError:
        return False
    return row is not None and row[0] == hashlib.sha256(data).hexdigest()

def _failure_signature(output: str, frames: list[tuple[str, int]], *, detailed: bool = False) -> str:
    """``detailed`` keys on the full error lines (``KeyError: 'a'`` and
    ``KeyError: 'b'`` differ); the default keys on the exception classes,
    which is what "the same failure again" after an edit means."""
    errors = ([m.group(0).strip()[:200] for m in _ERROR_LINE.finditer(output)] if detailed
              else _ERROR_LINE.findall(output))
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
    if path and row.get("edited_since"):
        return f"{name} ({path}, edited since){suffix}"
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
        # Shared with the grep augmenter by AttachedDelivery: one task budget.
        self.budget = DeliveryBudget()
        # The block being built (under ``_lock``); committed by ``_finish``.
        self._draft: Draft = self.budget.draft()
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

    def _finish(self, kind: str, lines: list[str], started: float,
                before: dict[str, int] | None = None) -> str:
        self.metrics.time_ms += int(round((time.perf_counter() - started) * 1000))
        if len(lines) <= 1:
            self._draft.commit("")
            self._journal(kind=kind, outcome="repeat" if self._draft.suppressed else "silent")
            return ""
        if self.budget.compact:
            lines = [lines[0], *compact_lines(lines[1:], always=_ALWAYS_SHOWN)]
        text = cap_text("\n".join(lines), self.max_bytes)
        self._draft.commit(text)
        self.metrics.bytes_delivered += len(text.encode("utf-8"))
        self.delivered_texts.append(text)
        carried = sorted((f for f, n in self.metrics.features.items() if n > (before or {}).get(f, 0)),
                         key=lambda f: int(f[1:]))
        self._journal(kind=kind, outcome="hit", bytes=len(text.encode("utf-8")), features=carried)
        return text

    # -- edits ---------------------------------------------------------------

    def after_edit(self, changes: Mapping[str, tuple[str | None, str | None]],
                   syntax: Iterable[Mapping[str, Any]] = (), pre_edit_graph: str = "") -> str:
        """``changes`` maps each edited path to its (before, after) text;
        ``pre_edit_graph`` is the graph the engine held when the edit began.

        The block reads that graph as it stands and NEVER amends it: forcing
        a refresh here cost aiogram (run 36336250729) an ~84 s synchronous
        batch amend on each of four edits. The pre-edit graph describes the
        pre-edit code exactly, so changed lines are mapped in pre-edit
        coordinates, and only for files whose pre-edit text is byte-identical
        to what the graph indexed (``file_hashes``) - a graph older than the
        file is never used to name what changed."""
        paths = [path for path in changes if path]
        if not paths:
            return ""
        with self._lock:
            self.metrics.edit_calls += 1
            self._draft = self.budget.draft()
            started = time.perf_counter()
            before = dict(self.metrics.features)
            try:
                lines = ["[GT] after your edit (from the graph before it):"]
                lines += self._syntax_lines(syntax)
                lines += self._graph_lines(changes, pre_edit_graph, started)
            except Exception as exc:  # noqa: BLE001 - enrichment is silent on failure
                self.metrics.errors += 1
                self._journal(kind="edit", outcome=f"error:{type(exc).__name__}")
                return ""
            text = self._finish("edit", lines, started, before)
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

    def _open_graph(self, pre_edit_graph: str) -> sqlite3.Connection | None:
        from gt_engine.capabilities._query import graph_conn

        if pre_edit_graph and Path(pre_edit_graph).is_file():
            try:
                return sqlite3.connect(Path(pre_edit_graph).resolve().as_uri() + "?mode=ro", uri=True)
            except sqlite3.Error:
                return None
        return graph_conn(self.session)

    def _graph_lines(self, changes: Mapping[str, tuple[str | None, str | None]],
                     pre_edit_graph: str, started: float) -> list[str]:
        conn = self._open_graph(pre_edit_graph)
        if conn is None:
            self._journal(kind="edit", skipped="no_graph")
            return []
        lines: list[str] = []
        sliced: list[str] = []
        try:
            changed = _changed_functions(conn, changes, self._preimages)
            relocate = Relocator(conn, Path(self._repo_root()), self._preimages).rows
            if changed:
                self.metrics.note("F13")
                lines.append("  changed: " + _listed(relocate(
                    [{"name": name, "file_path": path, "line": line} for _id, name, path, line in changed]),
                    MAX_CHANGED_SHOWN))
                for node_id, name, path, _line in changed[:MAX_CHANGED_SHOWN]:
                    if _TEST_PATH.search(path):
                        exercised = relocate(_exercised(conn, node_id))
                        if exercised:
                            self.metrics.note("F4", "F20")
                            lines.append(f"    test {name} exercises: {_listed(exercised, MAX_CALLERS_SHOWN)}")
                        continue
                    lines += self._caller_lines(relocate(_direct_callers(conn, node_id)), name, path)
                    if not sliced:
                        sliced = self._edit_slice_lines(changes, name, path)
                    lines += self._route_lines(conn, node_id, name)
            added = _added_definitions(changes)
            if added:
                self.metrics.note("F1")
                shown = ", ".join(f"{name} ({path})" for name, path in added[:MAX_CHANGED_SHOWN])
                more = len(added) - MAX_CHANGED_SHOWN
                lines.append(f"  added: {shown}" + (f" (+{more} more)" if more > 0 else "")
                             + " - new, so nothing calls it yet")
            tests = self._test_lines(conn, [path for path in changes if path], relocate)
            sink_lines = self._sink_reach_lines(conn, changed[:MAX_TAINT_CHECKS])
        finally:
            conn.close()
        # The typed taint query needs the CURRENT graph; when it is current
        # and the block is still cheap it gives the exact path, otherwise the
        # pre-edit call graph's reach into sink-like APIs stands in.
        typed = []
        if changed and time.perf_counter() - started < EDIT_OPTIONAL_BUDGET_SECONDS:
            typed = self._taint_lines([name for _id, name, _p, _l in changed[:MAX_TAINT_CHECKS]])
        # The slice goes last: it is the longest and least decisive part, so
        # the byte cap trims it before a sink, route or test line.
        return lines + (typed or sink_lines) + tests + sliced

    def _caller_lines(self, all_callers: list[dict[str, Any]], name: str, path: str) -> list[str]:
        """Callers not yet shown for this function. Only the callers that
        fit the display cap are staged, so the ``(+N more)`` stay eligible;
        "unchanged" is said only when every caller was delivered before."""
        draft = self._draft
        keyed = [(f"caller:{path}:{name}<-{row.get('file_path')}:{row.get('name')}", row)
                 for row in all_callers]
        fresh = [(key, row) for key, row in keyed if draft.is_new(key)]
        set_key = f"callerset:{path}:{name}:" + hashlib.sha256(
            "|".join(sorted(key for key, _row in keyed)).encode("utf-8")).hexdigest()[:20]
        if fresh:
            self.metrics.note("F4")
            rows = [row for _key, row in fresh]
            if any(row.get("trust_tier") == "via function value" for row in rows):
                self.metrics.note("F6")
            shown_before = len(all_callers) - len(fresh)
            tail = f" ({shown_before} shown earlier)" if shown_before else ""
            line = f"    {name} is called by: {_listed(rows, MAX_CALLERS_SHOWN)}{tail}"
            for key, _row in fresh[:MAX_CALLERS_SHOWN]:
                draft.stage(key, line)
            if len(fresh) <= MAX_CALLERS_SHOWN:
                draft.stage(set_key, line)
            return [line]
        if all_callers:
            if not draft.is_new(set_key):
                return [f"    {name}: callers unchanged since shown earlier"]
            # Every caller was shown before, but not as this set: one went
            # away. State the current set rather than claim nothing changed.
            line = f"    {name} is called by (current): {_listed(all_callers, MAX_CALLERS_SHOWN)}"
            draft.stage(set_key, line)
            return [line]
        key = f"nocallers:{path}:{name}"
        if not draft.is_new(key):
            return []
        line = f"    {name}: no callers in the graph"
        draft.stage(key, line)
        return [line]

    def _edit_slice_lines(self, changes: Mapping[str, tuple[str | None, str | None]],
                          name: str, path: str) -> list[str]:
        """F14-F17 on an edit: what the first edited statement of a changed
        Python function depends on (control + data), from the runtime CFG on
        the file as it is now - the values the new code reads and where they
        come from. Slices otherwise surfaced only on a located failure (27 of
        62 live DeepSWE tasks never got one)."""
        from gt_engine.tool_server import _source_line

        if not path.endswith(".py") or _TEST_PATH.search(path):
            return []
        before, after = changes.get(path, (None, None))
        source = Path(self._repo_root()) / path
        numbers: list[int] = []
        line = 0
        for target in _slice_targets(before or "", after or ""):
            # The function around the edit in the file as it is NOW: an edit
            # that adds a method is attributed by the pre-edit graph to the
            # neighbouring function (aiogram smoke 36383301807: get_value
            # added above update_data), whose slice at that line is empty.
            enclosing = _python_enclosing(source, target)
            if enclosing is None:
                continue
            found = [n for n in _python_slice(source, enclosing[0], target) if n != target]
            if found:
                numbers, line, name = found[-MAX_SLICE_LINES:], target, enclosing[0]
                break
        if not numbers:
            return []
        rows = [f"    {path}:{n}: {_source_line(self.session, path, n)}" for n in numbers]
        head = f"  your edit at {path}:{line} ({name}) depends on (backward slice; control + data):"
        key = "slice:" + hashlib.sha256("\n".join([head, *rows]).encode("utf-8")).hexdigest()[:20]
        if not self._draft.is_new(key):
            return []
        self._draft.stage(key, rows[-1])
        self.metrics.note("F14", "F15", "F16", "F17")
        return [head, *rows]

    def _preimages(self) -> dict[str, str]:
        """Each edited file's text before the agent first touched it."""
        from gt_engine.tool_server import _edit_preimages

        return _edit_preimages(self.session)

    def _sink_reach_lines(self, conn: sqlite3.Connection,
                          changed: list[tuple[Any, str, str, int]]) -> list[str]:
        lines = []
        for node_id, name, _path, _line in changed:
            sinks = _reached_sinks(conn, node_id)
            if sinks:
                self.metrics.note("F19")
                lines.append(f"    {name} reaches sink-like call(s): {', '.join(sinks)}"
                             f" (call graph; `gt-taint {name}` for the data path)")
        return lines

    def _taint_lines(self, names: list[str]) -> list[str]:
        from gt_engine.capabilities import analysis
        from gt_engine.capabilities._query import graph_db_path

        if not graph_db_path(self.session):
            return []
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

    def _route_lines(self, conn: sqlite3.Connection, node_id: Any, name: str) -> list[str]:
        from gt_engine.graph_facts import _framework, _guarded

        lines = []
        for fact in _guarded(lambda: _framework(conn, node_id)) or ():
            self.metrics.note(*(("F8", "F18") if fact.startswith("handles route") else ("F8",)))
            lines.append(f"    {name} {fact}")
        return lines

    def _test_lines(self, conn: sqlite3.Connection, paths: list[str],
                    relocate: Callable[[list[dict[str, Any]]], list[dict[str, Any]]] = lambda rows: rows,
                    ) -> list[str]:
        from gt_engine.tool_server import (
            _TEST_REACH_DEPTH, _TEST_REACH_LIMIT, _TEST_REACH_QUERY, is_real_test,
        )

        source = [path for path in paths if not _TEST_PATH.search(path)]
        reached: list[dict[str, Any]] = []
        for path in source:
            for file_path, qualified, name, line, depth in conn.execute(
                    _TEST_REACH_QUERY, (path, _TEST_REACH_DEPTH, _TEST_REACH_LIMIT)):
                if not is_real_test(file_path, qualified or name):
                    continue
                reached.append({"file_path": file_path, "line": line,
                                "name": f"{qualified or name} ({depth} call hop(s) away)"})
        if not reached:
            return []
        self.metrics.note("F20")
        line = f"  tests reaching {', '.join(source[:3])}: {_listed(relocate(reached), MAX_TESTS_SHOWN)}"
        key = "tests:" + hashlib.sha256(line.encode("utf-8")).hexdigest()[:20]
        if not self._draft.is_new(key):
            return []
        self._draft.stage(key, line)
        return [line]

    # -- failing test runs ---------------------------------------------------

    def _resolve(self, conn: sqlite3.Connection, root: Path, path: str, output: str) -> str:
        """A runner-printed path -> the indexed repo path.

        ``go test`` prints bare file names (``modules_test.go:45``); live
        DeepSWE abs tasks (run 36348029093) got failure blocks with no
        location because a bare name never matched the graph. A unique
        indexed path ending in it wins; among several, the one whose
        directory the output names (``FAIL github.com/x/y/evaluator``)."""
        if (root / path).is_file() or "/" in path:
            return path
        rows = [r[0] for r in conn.execute(
            "SELECT file_path FROM file_hashes WHERE file_path = ? OR file_path LIKE ?",
            (path, "%/" + path))]
        if len(rows) == 1:
            return rows[0]
        named = [row for row in rows if row.rsplit("/", 2)[-2:][0] in output]
        return named[0] if len(named) == 1 else path

    def after_failure(self, command: str, output: str, returncode: int | None,
                      test_outcome: str = "") -> str:
        """``test_outcome`` is the runtime's parsed outcome of the run
        (``execution_evidence.observed_test_outcome``). It decides first:
        on runs 36336203906/36336250729, 26 of 30 failing test runs exited 0
        because the agent piped the suite through ``tail``/``head``, and a
        return-code trigger produced 2 failure blocks in 8 tasks."""
        failed = test_outcome in ("fail", "env_fail") or (
            returncode not in (None, 0) and is_test_command(command))
        if not failed:
            return ""
        with self._lock:
            self.metrics.failure_calls += 1
            self._draft = self.budget.draft()
            started = time.perf_counter()
            before = dict(self.metrics.features)
            try:
                lines = ["[GT] about this failure:"]
                frames = failure_frames(output, self._repo_root())
                signature = _failure_signature(output, frames, detailed=True)
                key = f"failure:{signature}"
                shown_before = bool(signature) and not self._draft.is_new(key)
                located = [] if shown_before else self._location_lines(frames, output)
                if located and signature:
                    self._draft.stage(key, located[0])
                lines += located
                lines += self._repeat_lines(output, frames, bool(located), shown_before)
            except Exception as exc:  # noqa: BLE001 - enrichment is silent on failure
                self.metrics.errors += 1
                self._journal(kind="failure", outcome=f"error:{type(exc).__name__}")
                return ""
            text = self._finish("failure", lines, started, before)
            if text:
                self.metrics.failure_hits += 1
            return text

    def _location_lines(self, frames: list[tuple[str, int]], output: str = "") -> list[str]:
        if not frames:
            return []
        # Failures usually follow edits, and attached delivery leaves the
        # graph stale until something reads it; the adopted graph is still
        # exact for every file whose content is what it indexed, and a Python
        # file is resolved on its current text.
        engine = getattr(self.session, "_engine", None)
        conn = self._open_graph(str(getattr(getattr(engine, "engine_state", None), "graph_path", "") or ""))
        if conn is None:
            return []
        root = Path(self._repo_root())
        try:
            located: list[tuple[str, int, str, int, Any]] = []
            relocator = Relocator(conn, root, self._preimages)
            for printed, line in frames:
                path = self._resolve(conn, root, printed, output)
                if _indexed_as_on_disk(conn, root, path):
                    enclosing = _enclosing_function(conn, path, line)
                elif path.endswith(".py"):
                    found = _python_enclosing(root / path, line)
                    enclosing = (*found, None) if found else None
                else:
                    # An edited non-Python file: find the function on the
                    # indexed text through the diff; no stored-CFG slice,
                    # since the persisted CFG describes the old body.
                    indexed_line = relocator.to_indexed(path, line)
                    found = _enclosing_function(conn, path, indexed_line) if indexed_line else None
                    enclosing = (found[0], found[1], None) if found else None
                if enclosing is not None:
                    located.append((path, line, *enclosing))
            if not located:
                return []
            # The innermost non-test frame is where the wrong value surfaced;
            # the innermost test frame is the assertion that noticed it. When
            # the output names only the test (Go, JS runners), the assertion's
            # own dependencies are the slice worth showing.
            source = [row for row in located if not _TEST_PATH.search(row[0])]
            tests = [row for row in located if _TEST_PATH.search(row[0])]
            lines: list[str] = []
            if tests:
                path, line, name, _start, _node = tests[-1]
                lines.append(f"  failing test: {name} ({path}:{line})")
                self.metrics.note("F20")
            target = source[-1] if source else tests[-1] if tests else None
            if source:
                path, line, name, _start, _node = source[-1]
                lines.append(f"  failure surfaced in: {name} ({path}:{line})")
            if target is not None:
                lines += self._slice_lines(conn, *target)
            return lines
        finally:
            conn.close()

    def _slice_lines(self, conn: sqlite3.Connection, path: str, line: int, name: str,
                     _start: int, node_id: Any) -> list[str]:
        """Backward slice of the failing line: control + data dependencies.

        Python: the runtime CFG on the file as it is now. Other languages:
        the producer's persisted CFG on the hash-verified graph (exact for an
        unchanged file). Else the typed slice on a current graph."""
        from gt_engine.capabilities import analysis
        from gt_engine.tool_server import _source_line

        root = Path(self._repo_root())
        numbers: list[int] = []
        if path.endswith(".py"):
            numbers = _python_slice(root / path, name, line)
        if not numbers and node_id is not None:
            numbers = _stored_slice(conn, root / path, node_id, name, line)
        if not numbers:
            result = analysis.slice(self.session, name, line, "backward", path=path)
            answer = result.answer if isinstance(result.answer, dict) else {}
            for item in answer.get("slices") or []:
                numbers = [int(n) for n in item.get("slice_lines") or []]
                if numbers:
                    break
        numbers = [n for n in numbers if n != line][-MAX_SLICE_LINES:]
        if not numbers:
            return []
        self.metrics.note("F14", "F15", "F16", "F17")
        rows = [f"    {path}:{n}: {_source_line(self.session, path, n)}" for n in numbers]
        return [f"  line {line} depends on (backward slice; control + data):", *rows]

    def _repeat_lines(self, output: str, frames: list[tuple[str, int]], located: bool = True,
                      located_earlier: bool = False) -> list[str]:
        signature = _failure_signature(output, frames)
        if not signature:
            return []
        epoch = int(getattr(getattr(self.session, "_engine", None), "_edit_epoch", 0) or 0)
        previous = self._failures_seen.get(signature)
        self._failures_seen[signature] = epoch
        if previous is None or previous == epoch:
            return []
        self.metrics.note("F20")
        where = ("re-check the location shown earlier for this failure" if located_earlier
                 else "re-check the location above" if located
                 else "re-check where the failing assertion reads its value")
        return [f"  same failure as before your last edit(s): the change did not reach this path; {where}"]


__all__ = [
    "ActionAugmenter",
    "ActionAugmentMetrics",
    "failure_frames",
    "is_test_command",
]
