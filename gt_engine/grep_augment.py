"""Query-anchored enrichment of the agent's own search observations.

The GitNexus ``native_augment`` pattern: after the agent runs grep/rg/ag,
append a compact ``[GT]`` block about the symbols THE AGENT searched for to
that same observation. GT never picks the symbol. Nothing is appended when the
graph has no answer. Answers come from the certified ``symbol_context`` query,
so they carry the same freshness and certification rules as the typed path.
"""
from __future__ import annotations

import hashlib
import re
import shlex
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from gt_engine.attached_budget import DeliveryBudget, compact_lines
from gt_engine.tool_render import AUGMENT_OUTPUT_BYTES, cap_text

if TYPE_CHECKING:  # pragma: no cover - typing only
    from gt_engine.gt_session import GTSession

MIN_PATTERN_LENGTH = 3
MAX_SYMBOLS_PER_SEARCH = 2
MAX_NEIGHBORS_SHOWN = 5
MAX_FLOWS_SHOWN = 2

_SEARCH_TOOLS = frozenset({"grep", "egrep", "fgrep", "rg", "ag", "ack"})
_SEGMENT_SPLIT = frozenset({"|", "||", "&&", ";", "|&"})
# Flags whose value is the NEXT token (so it is not mistaken for the pattern).
_VALUE_FLAGS = frozenset({
    "-A", "-B", "-C", "-m", "-g", "-t", "-T", "-f", "-d", "-D",
    "--include", "--exclude", "--exclude-dir", "--glob", "--type",
    "--type-not", "--max-count", "--context", "--before-context",
    "--after-context", "--max-depth", "--file", "--ignore-file",
})
_PATTERN_FLAGS = frozenset({"-e", "--regexp"})
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_NOISE_WORDS = frozenset({
    "def", "class", "function", "func", "return", "import", "from", "self",
    "this", "async", "await", "const", "let", "var", "public", "private",
    "static", "void", "struct", "impl", "type", "interface", "export",
    "module", "package", "raise", "throw", "new", "true", "false", "none",
    "null", "nil", "and", "not", "for", "while", "else", "elif", "try",
    "except", "catch", "fn", "pub", "use", "mod", "with", "lambda", "yield",
    "error", "test", "tests",
})


def _segments(command: str) -> list[list[str]]:
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars="|&;")
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return []
    segments: list[list[str]] = [[]]
    for token in tokens:
        if token in _SEGMENT_SPLIT:
            segments.append([])
        else:
            segments[-1].append(token)
    return [segment for segment in segments if segment]


def _pattern_from_segment(tokens: list[str]) -> str | None:
    index = 0
    if tokens[0] == "git" and len(tokens) > 1 and tokens[1] == "grep":
        index = 2
    elif tokens[0].rsplit("/", 1)[-1] in _SEARCH_TOOLS:
        index = 1
    else:
        return None
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            return tokens[index + 1] if index + 1 < len(tokens) else None
        if token in _PATTERN_FLAGS:
            return tokens[index + 1] if index + 1 < len(tokens) else None
        if token.startswith("--regexp="):
            return token.split("=", 1)[1]
        if token in _VALUE_FLAGS:
            index += 2
            continue
        if token.startswith("-"):
            index += 1
            continue
        return token
    return None


def extract_search_pattern(command: str) -> str | None:
    """The pattern of the first search command in ``command``, if any."""
    for segment in _segments(command):
        pattern = _pattern_from_segment(segment)
        if pattern and len(pattern) >= MIN_PATTERN_LENGTH:
            return pattern
    return None


def symbols_in_pattern(pattern: str) -> tuple[str, ...]:
    """Identifier candidates the agent itself named, most specific first."""
    seen: list[str] = []
    for match in _IDENTIFIER.findall(pattern.replace("\\b", " ").replace("\\s", " ")):
        if len(match) < MIN_PATTERN_LENGTH or match.lower() in _NOISE_WORDS:
            continue
        if match not in seen:
            seen.append(match)
    return tuple(sorted(seen, key=lambda name: (-len(name), seen.index(name))))[
        :MAX_SYMBOLS_PER_SEARCH
    ]


def _site(row: Any, *, callee: bool = False) -> str:
    if not isinstance(row, dict):
        return str(row)
    name = row.get("qualified_name") or row.get("name") or "?"
    path = row.get("file_path") or ""
    # A caller row's call_line is in the caller's own file; a callee row's
    # file_path is the callee's definition file, so its line is ``line``
    # (the call_line there belongs to the searched symbol's file).
    line = (row.get("line") or row.get("start_line") if callee
            else row.get("call_line") or row.get("line") or row.get("start_line"))
    where = f"{path}:{line}" if path and line else path
    tier = row.get("trust_tier")
    suffix = f" [{tier}]" if tier and tier != "CERTIFIED" else ""
    return f"{name} ({where}){suffix}" if where else f"{name}{suffix}"


def _neighbors(label: str, rows: Any, total: Any) -> str | None:
    if not isinstance(rows, list) or not rows:
        return None
    # SPECULATIVE edges (confidence < 0.5, name matches) were the only wrong
    # caller/callee locations the claim audit found (e.g. Go string(x) matched
    # to a String method); they are counted, not shown.
    speculative = sum(1 for row in rows if isinstance(row, dict) and row.get("trust_tier") == "SPECULATIVE")
    rows = [row for row in rows if not (isinstance(row, dict) and row.get("trust_tier") == "SPECULATIVE")]
    if not rows:
        return None
    callee = label == "calls"
    shown = ", ".join(_site(row, callee=callee) for row in rows[:MAX_NEIGHBORS_SHOWN])
    count = (total if isinstance(total, int) else len(rows) + speculative) - speculative
    more = count - min(len(rows), MAX_NEIGHBORS_SHOWN)
    hidden = f" ({speculative} unproven name match(es) hidden)" if speculative else ""
    return f"    {label}: {shown}" + (f" (+{more} more)" if more > 0 else "") + hidden


def render_symbol_block(symbol: str, answer: Any, facts: tuple[str, ...] = ()) -> str | None:
    """``facts`` are extra lines (``graph_facts``) appended under the symbol."""
    if not isinstance(answer, dict):
        return None
    definition = answer.get("definition")
    if not isinstance(definition, dict):
        return None
    kind = definition.get("kind") or "symbol"
    where = f"{definition.get('file_path', '')}:{definition.get('start_line', '')}"
    lines = [f"  {definition.get('qualified_name') or symbol} ({kind}) {where}"]
    extra = answer.get("additional_definitions")
    if isinstance(extra, int) and extra > 0:
        lines.append(f"    ambiguous: {extra} other definition(s) share this name")
    for label, rows, total in (
        ("called by", answer.get("callers"), answer.get("caller_count")),
        ("calls", answer.get("callees"), answer.get("callee_count")),
    ):
        rendered = _neighbors(label, rows, total)
        if rendered:
            lines.append(rendered)
    flows = answer.get("flows")
    if isinstance(flows, list):
        for flow in flows[:MAX_FLOWS_SHOWN]:
            text = flow.get("display_label") or flow.get("label") if isinstance(flow, dict) else flow
            if text:
                lines.append(f"    in flow: {text}")
    lines.extend(f"    {fact}" for fact in facts)
    return "\n".join(lines) if len(lines) > 1 else None


def _facts(session: "GTSession", answer: Any) -> tuple[tuple[str, str], ...]:
    """(features, line) for references, resolution, dispatch, routes, module
    and co-change of the resolved definition (see ``graph_facts``)."""
    from gt_engine.graph_facts import symbol_facts

    definition = answer.get("definition") if isinstance(answer, dict) else None
    return tuple(symbol_facts(session, definition)) if isinstance(definition, dict) else ()


def _mention(conn: sqlite3.Connection, symbol: str, verified: Any = None) -> tuple[str, set[str], str] | None:
    from gt_engine.graph_facts import mention_block

    return mention_block(conn, symbol, verified)


def block_features(answer: Any, facts: tuple[tuple[str, str], ...]) -> set[str]:
    """The features one rendered symbol block carries."""
    features = {"F2", "F12"}
    if isinstance(answer, dict):
        if answer.get("callers") or answer.get("callees"):
            features.add("F4")
        if answer.get("flows"):
            features.add("F9")
    for ids, _line in facts:
        features.update(ids.split())
    return features


_STALE_DEFINITION_LABELS = ("Function", "Method", "Class", "Interface")
_STALE_DEFINITIONS_SEEN = 5
_STALE_NEIGHBOURS = 25


class StaleView:
    """The adopted graph read while it is stale, restricted to rows whose
    files still hash to what it indexed (``file_hashes``).

    A stale graph is exact for every unchanged file, so a definition, caller
    or callee in such a file is as true as on a current graph; a row in a
    file the agent changed is left out and counted, never shown. This is what
    lets a passive read skip a whole-pipeline amend (see
    ``tool_server.PASSIVE_REFRESH_BUDGET_MS``) without serving a stale fact.
    """

    def __init__(self, session: "GTSession", conn: sqlite3.Connection, root: Path):
        self.session = session
        self.conn = conn
        self.root = root
        self._verified: dict[str, bool] = {}

    @classmethod
    def open(cls, session: "GTSession") -> "StaleView | None":
        engine = getattr(session, "_engine", None)
        graph = str(getattr(getattr(engine, "engine_state", None), "graph_path", "") or "")
        root = str(getattr(engine, "repo_root", "") or "")
        if not graph or not root or not Path(graph).is_file():
            return None
        try:
            conn = sqlite3.connect(Path(graph).resolve().as_uri() + "?mode=ro", uri=True)
        except sqlite3.Error:
            return None
        return cls(session, conn, Path(root))

    def close(self) -> None:
        self.conn.close()

    def verified(self, path: str) -> bool:
        if path not in self._verified:
            row = self.conn.execute(
                "SELECT content_hash FROM file_hashes WHERE file_path = ?", (path,)).fetchone()
            try:
                digest = hashlib.sha256((self.root / path).read_bytes()).hexdigest()
            except OSError:
                digest = ""
            self._verified[path] = row is not None and row[0] == digest
        return self._verified[path]

    def symbol(self, symbol: str) -> tuple[dict[str, Any] | None, tuple[tuple[str, str], ...]]:
        from gt_engine.graph_facts import symbol_facts

        rows = self.conn.execute(
            "SELECT id, name, qualified_name, label, file_path, start_line FROM nodes WHERE name = ?"
            f" AND label IN ({','.join('?' * len(_STALE_DEFINITION_LABELS))})"
            " ORDER BY is_test, file_path, start_line LIMIT ?",
            (symbol, *_STALE_DEFINITION_LABELS, _STALE_DEFINITIONS_SEEN)).fetchall()
        rows = [row for row in rows if self.verified(row[4])]
        if not rows:
            return None, ()
        node_id, name, qualified, label, path, line = rows[0]
        callers, callers_hidden = self._neighbours(
            "SELECT s.qualified_name, s.name, s.file_path, e.source_line, e.trust_tier FROM edges e"
            " JOIN nodes s ON s.id = e.source_id WHERE e.target_id = ? AND e.type = 'CALLS'"
            " ORDER BY s.file_path, e.source_line LIMIT ?", node_id, "call_line")
        callees, callees_hidden = self._neighbours(
            "SELECT t.qualified_name, t.name, t.file_path, t.start_line, e.trust_tier FROM edges e"
            " JOIN nodes t ON t.id = e.target_id WHERE e.source_id = ? AND e.type = 'CALLS'"
            " ORDER BY t.file_path, t.start_line LIMIT ?", node_id, "line")
        definition = {"id": node_id, "name": name, "qualified_name": qualified, "kind": label,
                      "label": label, "file_path": path, "start_line": line}
        answer = {"definition": definition, "additional_definitions": len(rows) - 1,
                  "callers": callers, "callees": callees}
        facts = tuple(symbol_facts(self.session, definition, conn=self.conn))
        hidden = callers_hidden + callees_hidden
        if hidden:
            facts += (("", f"{hidden} caller/callee row(s) in files you changed left out"),)
        return answer, facts

    def _neighbours(self, sql: str, node_id: Any, line_key: str) -> tuple[list[dict[str, Any]], int]:
        shown: list[dict[str, Any]] = []
        hidden = 0
        for qualified, name, path, line, tier in self.conn.execute(sql, (node_id, _STALE_NEIGHBOURS)):
            if not self.verified(path):
                hidden += 1
                continue
            shown.append({"qualified_name": qualified, "name": name, "file_path": path,
                          line_key: line, "trust_tier": tier})
        return shown, hidden


@dataclass
class AugmentMetrics:
    calls: int = 0
    hits: int = 0
    errors: int = 0
    time_ms: int = 0
    bytes_delivered: int = 0
    features: dict[str, int] = field(default_factory=dict)

    def as_dict(self, search_commands: int) -> dict[str, Any]:
        return {
            "augment_calls": self.calls,
            "augment_hits": self.hits,
            "augment_errors": self.errors,
            "augment_time_s": round(self.time_ms / 1000.0, 3),
            "augment_bytes_delivered": self.bytes_delivered,
            "augment_hit_rate": round(self.hits / search_commands, 4) if search_commands else 0.0,
            "augment_features": dict(sorted(self.features.items())),
        }


class GrepAugmenter:
    """Build the ``[GT]`` block for one search observation."""

    def __init__(self, session: "GTSession", *, max_bytes: int = AUGMENT_OUTPUT_BYTES):
        self.session = session
        self.max_bytes = max_bytes
        self.metrics = AugmentMetrics()
        self.budget = DeliveryBudget()
        self.search_commands = 0
        self.delivered_texts: list[str] = []
        self._lock = threading.Lock()

    def _journal(self, **row: Any) -> None:
        store = getattr(getattr(self.session, "_engine", None), "store", None)
        if store is not None:
            try:
                store.append("gt_augment", **row)
            except Exception:  # noqa: BLE001 - journaling never fails the action
                pass

    def _budgeted(self, symbol: str, answer: Any,
                  facts: tuple[tuple[str, str], ...]) -> tuple[str | None, set[str]]:
        """Render one symbol block under the task's delivery budget: a symbol
        already shown collapses to one line, a fact already shown (the same
        module line, the same co-change list) is dropped, and past the
        detail budget the block keeps its first lines only."""
        definition = answer.get("definition") if isinstance(answer, dict) else None
        if not isinstance(definition, dict):
            return None, set()
        key = f"sym:{definition.get('file_path')}:{definition.get('start_line')}:{definition.get('qualified_name') or symbol}"
        if self.budget.seen(key):
            name = definition.get("qualified_name") or symbol
            where = f"{definition.get('file_path', '')}:{definition.get('start_line', '')}"
            return f"  {name} ({where}): graph context shown earlier in this task", set()
        kept = tuple((ids, line) for ids, line in facts if not self.budget.seen(f"fact:{line}"))
        block = render_symbol_block(symbol, answer, tuple(line for _ids, line in kept))
        if block and self.budget.compact:
            block = "\n".join(compact_lines(block.splitlines()))
        return block, (block_features(answer, kept) if block else set())

    def _stale_verified(self, pattern: str, symbols: tuple[str, ...]) -> str:
        """Answer from the adopted graph while it is stale, using only rows
        whose files still hash to what the graph indexed (``StaleView``).
        Called under the lock by ``augment``; timing is closed there."""
        view = StaleView.open(self.session)
        if view is None:
            self._journal(pattern=pattern[:200], symbols=list(symbols), outcome="silent_stale")
            return ""
        blocks: list[str] = []
        hit_symbols: list[str] = []
        hit_features: set[str] = set()
        try:
            for symbol in symbols:
                answer, facts = view.symbol(symbol)
                if answer is None:
                    found = None if self.budget.seen(f"mention:{symbol}") else _mention(view.conn, symbol, view.verified)
                    if found:
                        blocks.append(found[0])
                        hit_symbols.append(found[2])
                        hit_features |= found[1]
                    continue
                block, carried = self._budgeted(symbol, answer, facts)
                if block:
                    blocks.append(block)
                    hit_symbols.append(symbol)
                    hit_features |= carried
        finally:
            view.close()
        if not blocks:
            self._journal(pattern=pattern[:200], symbols=list(symbols), outcome="silent_stale")
            return ""
        return self._deliver(pattern, symbols, blocks, hit_symbols, hit_features,
                             header="[GT] graph context for your search (graph from before your "
                                    "latest edits; rows from files you changed are left out):")

    def _deliver(self, pattern: str, symbols: tuple[str, ...], blocks: list[str],
                 hit_symbols: list[str], hit_features: set[str], *,
                 header: str = "[GT] graph context for your search:") -> str:
        hint = (f"\n  next: `gt-impact {hit_symbols[0]}` (what breaks if it changes), "
                "`gt-tests <file>` (tests to run)") if self.budget.hint_allowed() else ""
        text = cap_text(header + "\n" + "\n".join(blocks) + hint, self.max_bytes)
        self.budget.charge(text)
        self.metrics.hits += 1
        for feature in hit_features:
            self.metrics.features[feature] = self.metrics.features.get(feature, 0) + 1
        self.metrics.bytes_delivered += len(text.encode("utf-8"))
        self.delivered_texts.append(text)
        self._journal(pattern=pattern[:200], symbols=list(symbols), outcome="hit",
                      features=sorted(hit_features, key=lambda f: int(f[1:]) if f[1:].isdigit() else 99),
                      bytes=len(text.encode("utf-8")))
        return text

    def augment(self, command: str) -> str:
        """Return the block to append ('' when there is nothing to add)."""
        pattern = extract_search_pattern(command)
        if pattern is None:
            return ""
        symbols = symbols_in_pattern(pattern)
        with self._lock:
            self.search_commands += 1
            if not symbols:
                return ""
            from gt_engine.capabilities import structure
            from gt_engine.miniswe_typed_actions import snapshot_scope

            adapter = getattr(self.session, "_engine", None)
            scope = ("augment", id(adapter), getattr(adapter, "global_action", 0),
                     getattr(adapter, "_edit_epoch", 0))
            started = time.perf_counter()
            self.metrics.calls += 1
            blocks: list[str] = []
            try:
                from gt_engine.tool_server import refresh_if_stale

                refresh_if_stale(self.session, passive=True)
                from gt_engine.capabilities._query import graph_db_path

                if not graph_db_path(self.session):
                    return self._stale_verified(pattern, symbols)
                with snapshot_scope(scope):
                    symbol_results = [(symbol, structure.symbol_context(self.session, symbol))
                                      for symbol in symbols]
                unresolved = [symbol for symbol, result in symbol_results
                              if result.status in ("unavailable", "error", "abstain")
                              or not render_symbol_block(symbol, result.answer)]
                hit_symbols: list[str] = []
                hit_features: set[str] = set()
                for symbol, result in symbol_results:
                    if result.status in ("unavailable", "error", "abstain"):
                        continue
                    facts = _facts(self.session, result.answer)
                    block, carried = self._budgeted(symbol, result.answer, facts)
                    if block:
                        blocks.append(block)
                        hit_symbols.append(symbol)
                        hit_features |= carried
                if unresolved:
                    from gt_engine.capabilities._query import graph_conn

                    conn = graph_conn(self.session)
                    if conn is not None:
                        try:
                            for symbol in unresolved:
                                found = None if self.budget.seen(f"mention:{symbol}") else _mention(conn, symbol)
                                if found:
                                    blocks.append(found[0])
                                    hit_symbols.append(found[2])
                                    hit_features |= found[1]
                        finally:
                            conn.close()
            except Exception as exc:  # noqa: BLE001 - enrichment is silent on failure
                self.metrics.errors += 1
                self._journal(pattern=pattern[:200], outcome=f"error:{type(exc).__name__}")
                return ""
            finally:
                self.metrics.time_ms += int(round((time.perf_counter() - started) * 1000))
            if not blocks:
                self._journal(pattern=pattern[:200], symbols=list(symbols), outcome="silent")
                return ""
            return self._deliver(pattern, symbols, blocks, hit_symbols, hit_features)


__all__ = [
    "AugmentMetrics",
    "GrepAugmenter",
    "extract_search_pattern",
    "render_symbol_block",
    "symbols_in_pattern",
]
