"""GT answers attached to the agent's own reads, without being asked.

The GT-on agent does not call gt-* tools, however they are offered: on the
7 DeepSWE tasks it lost (run 36359464192) it made 2 calls; with the tools in
the system prompt (run 36477828325) 5; with GitNexus's levers - the workflow
in the task message naming each tool, a gt-query worked example
(run 36485836462) - still 0 in the first 3 tasks. Its habits are fixed:
`find -name "*x*"`, then `cat` a file, then edit. GitNexus enriches only
grep; so did GT. This module answers the questions those reads imply, on the
read itself:

* reading a source file (cat / head / tail / nl / sed -n / less / more):
  once per file, what it defines and who calls each definition (gt-context
  for the file), the tests that reach it (gt-tests) and the files that
  usually change with it (co-change);
* `find ... -name "*pattern*"`: the pattern is searched like a grep
  (graph context for the symbols it names).

Everything rides the task's DeliveryBudget: a file is described once, and
past the detail budget blocks compact.
"""
from __future__ import annotations

import os
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from gt_engine.attached_budget import DeliveryBudget, compact_lines
from gt_engine.tool_render import AUGMENT_OUTPUT_BYTES, cap_text

if TYPE_CHECKING:  # pragma: no cover - typing only
    from gt_engine.gt_session import GTSession

READ_TOOLS = frozenset({"cat", "head", "tail", "nl", "less", "more", "bat", "sed"})
SOURCE_SUFFIXES = frozenset({".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".go", ".rs", ".java",
                             ".kt", ".rb", ".php", ".c", ".cc", ".cpp", ".h", ".hpp", ".cs", ".swift", ".scala"})
MAX_FILES_DESCRIBED = 15
MAX_DEFINITIONS_SHOWN = 6
MAX_TESTS_SHOWN = 4
_FIND_NAME = re.compile(r"^-i?name$")
_TEST_FILE = re.compile(r"(^|/)(tests?|__tests__|spec)/|(^|/)test_[^/]*$|_test\.[a-z]+$|\.(test|spec)\.[a-z]+$")


@dataclass
class ReadAugmentMetrics:
    calls: int = 0
    hits: int = 0
    finds: int = 0
    bytes_delivered: int = 0
    time_ms: int = 0
    features: dict[str, int] = field(default_factory=dict)

    def note(self, *features: str) -> None:
        for feature in features:
            self.features[feature] = self.features.get(feature, 0) + 1

    def as_dict(self) -> dict[str, Any]:
        return {"read_augment_calls": self.calls, "read_augment_hits": self.hits,
                "read_augment_finds": self.finds, "read_augment_bytes_delivered": self.bytes_delivered,
                "read_augment_time_s": round(self.time_ms / 1000, 3),
                "read_augment_features": dict(sorted(self.features.items()))}


def _segments(command: str) -> list[list[str]]:
    from gt_engine.grep_augment import _segments as split

    return split(command)


def files_read(command: str) -> list[str]:
    """Source files a command prints, as written in the command."""
    out: list[str] = []
    for tokens in _segments(command):
        if not tokens:
            continue
        tool = tokens[0].rsplit("/", 1)[-1]
        if tool not in READ_TOOLS:
            continue
        args = tokens[1:]
        if tool == "sed":
            if "-n" not in args and not any(a.startswith("-n") for a in args):
                continue  # sed without -n is an edit, not a read
            script_seen = False
            files = []
            for arg in args:
                if arg.startswith("-"):
                    continue
                if not script_seen:
                    script_seen = True
                    continue
                files.append(arg)
        else:
            files = [a for a in args if not a.startswith("-") and not a.isdigit()]
        for name in files:
            if Path(name).suffix.lower() in SOURCE_SUFFIXES and name not in out:
                out.append(name)
    return out


def find_patterns(command: str) -> list[str]:
    """`find ... -name "*x*"` patterns, wildcards stripped."""
    out: list[str] = []
    for tokens in _segments(command):
        if not tokens or tokens[0].rsplit("/", 1)[-1] != "find":
            continue
        for index, token in enumerate(tokens[:-1]):
            if _FIND_NAME.match(token):
                stem = re.sub(r"\.[A-Za-z0-9]+$", "", tokens[index + 1].strip("*"))
                core = re.sub(r"[*?\[\]]", "", stem)
                if len(core) >= 3 and core not in out:
                    out.append(core)
    return out


def _relative(name: str, root: Path) -> str | None:
    path = Path(name)
    try:
        resolved = (path if path.is_absolute() else root / path).resolve()
        rel = resolved.relative_to(root.resolve())
    except (ValueError, OSError):
        return None
    return rel.as_posix()


def _definitions(conn: sqlite3.Connection, path: str) -> list[tuple[str, int]]:
    """(name, number of other files calling it), most-called first."""
    rows = conn.execute(
        "SELECT n.id, COALESCE(n.qualified_name, n.name) FROM nodes n WHERE n.file_path = ?"
        " AND n.label IN ('Function', 'Method', 'Class', 'Interface')", (path,)).fetchall()
    scored = []
    for node_id, name in rows:
        (callers,) = conn.execute(
            "SELECT COUNT(DISTINCT s.file_path) FROM edges e JOIN nodes s ON s.id = e.source_id"
            " WHERE e.target_id = ? AND e.type = 'CALLS' AND s.file_path != ?"
            " AND COALESCE(e.trust_tier, '') != 'SPECULATIVE'", (node_id, path)).fetchone()
        scored.append((str(name), int(callers or 0)))
    scored.sort(key=lambda item: (-item[1], item[0]))
    return scored


class ReadAugmenter:
    """Builds the `[GT]` block for one read or find command."""

    def __init__(self, session: "GTSession", *, max_bytes: int = AUGMENT_OUTPUT_BYTES):
        self.session = session
        self.max_bytes = max_bytes
        self.metrics = ReadAugmentMetrics()
        self.budget = DeliveryBudget()
        self.grep = None  # the GrepAugmenter, wired by AttachedDelivery for find patterns
        self._described = 0

    def _conn(self) -> sqlite3.Connection | None:
        """The adopted graph as it stands, read-only: a read never waits on
        an amend, and every line is name-level (no line numbers)."""
        engine = getattr(self.session, "_engine", None)
        path = str(getattr(getattr(engine, "engine_state", None), "graph_path", "") or "")
        if not path or not Path(path).is_file():
            return None
        try:
            return sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
        except sqlite3.Error:
            return None

    def _root(self) -> Path:
        return Path(str(getattr(getattr(self.session, "_engine", None), "repo_root", "") or os.getcwd()))

    def _file_lines(self, conn: sqlite3.Connection, path: str) -> list[str]:
        from gt_engine.graph_facts import _cochange, _guarded
        from gt_engine.tool_server import _tests_by_reachability

        lines: list[str] = []
        definitions = _guarded(lambda: _definitions(conn, path)) or []
        if definitions:
            shown = ", ".join(f"{name} ({n} caller file{'s' if n != 1 else ''})" if n else name
                              for name, n in definitions[:MAX_DEFINITIONS_SHOWN])
            more = len(definitions) - MAX_DEFINITIONS_SHOWN
            lines.append(f"  defines: {shown}" + (f" (+{more} more)" if more > 0 else ""))
            self.metrics.note("F2", "F12")
            if any(n for _name, n in definitions):
                self.metrics.note("F4")
        if not _TEST_FILE.search(path):
            try:
                tests = _tests_by_reachability(self.session, [path])[:MAX_TESTS_SHOWN]
            except Exception:  # noqa: BLE001 - tests are advisory
                tests = []
            if tests:
                self.metrics.note("F20")
                lines.append("  tests reaching it: " + ", ".join(
                    f"{row.get('file_path')}::{str(row.get('name')).split(' (')[0]}" for row in tests))
        cochange = _guarded(lambda: _cochange(conn, path))
        if cochange:
            self.metrics.note("F13")
            lines.append(f"  {cochange}")
        return lines

    def augment(self, command: str) -> str:
        paths = files_read(command)
        patterns = find_patterns(command)
        if not paths and not patterns:
            return ""
        started = time.perf_counter()
        self.metrics.calls += 1
        blocks: list[str] = []
        try:
            if paths and self._described < MAX_FILES_DESCRIBED:
                conn = self._conn()
                if conn is not None:
                    try:
                        root = self._root()
                        for name in paths:
                            rel = _relative(name, root)
                            if not rel or self._described >= MAX_FILES_DESCRIBED:
                                continue
                            draft = self.budget.draft()
                            key = f"file:{rel}"
                            if not draft.is_new(key):
                                draft.commit("")
                                continue
                            lines = self._file_lines(conn, rel)
                            if not lines:
                                draft.commit("")
                                continue
                            if self.budget.compact:
                                lines = compact_lines(lines)
                            block = f"[GT] about {rel}:\n" + "\n".join(lines)
                            draft.stage(key, block.splitlines()[0])
                            draft.commit(block)
                            blocks.append(block)
                            self._described += 1
                    finally:
                        conn.close()
            if patterns and self.grep is not None:
                for pattern in patterns[:2]:
                    found = self.grep.augment(f'grep -rn "{pattern}" .')
                    if found:
                        self.metrics.finds += 1
                        blocks.append(found)
        except Exception:  # noqa: BLE001 - enrichment never costs the observation
            return ""
        finally:
            self.metrics.time_ms += int(round((time.perf_counter() - started) * 1000))
        if not blocks:
            return ""
        text = cap_text("\n\n".join(blocks), self.max_bytes)
        self.metrics.hits += 1
        self.metrics.bytes_delivered += len(text.encode("utf-8"))
        return text


__all__ = ["ReadAugmenter", "files_read", "find_patterns"]
