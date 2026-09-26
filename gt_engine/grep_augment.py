"""Query-anchored enrichment of the agent's own search observations.

The GitNexus ``native_augment`` pattern: after the agent runs grep/rg/ag,
append a compact ``[GT]`` block about the symbols THE AGENT searched for to
that same observation. GT never picks the symbol. Nothing is appended when the
graph has no answer. Answers come from the certified ``symbol_context`` query,
so they carry the same freshness and certification rules as the typed path.
"""
from __future__ import annotations

import re
import shlex
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

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


def _site(row: Any) -> str:
    if not isinstance(row, dict):
        return str(row)
    name = row.get("qualified_name") or row.get("name") or "?"
    path = row.get("file_path") or ""
    line = row.get("call_line") or row.get("line") or row.get("start_line")
    where = f"{path}:{line}" if path and line else path
    tier = row.get("trust_tier")
    suffix = f" [{tier}]" if tier and tier != "CERTIFIED" else ""
    return f"{name} ({where}){suffix}" if where else f"{name}{suffix}"


def _neighbors(label: str, rows: Any, total: Any) -> str | None:
    if not isinstance(rows, list) or not rows:
        return None
    shown = ", ".join(_site(row) for row in rows[:MAX_NEIGHBORS_SHOWN])
    count = total if isinstance(total, int) else len(rows)
    more = count - min(len(rows), MAX_NEIGHBORS_SHOWN)
    return f"    {label}: {shown}" + (f" (+{more} more)" if more > 0 else "")


def render_symbol_block(symbol: str, answer: Any) -> str | None:
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
    return "\n".join(lines) if len(lines) > 1 else None


@dataclass
class AugmentMetrics:
    calls: int = 0
    hits: int = 0
    errors: int = 0
    time_ms: int = 0
    bytes_delivered: int = 0

    def as_dict(self, search_commands: int) -> dict[str, Any]:
        return {
            "augment_calls": self.calls,
            "augment_hits": self.hits,
            "augment_errors": self.errors,
            "augment_time_s": round(self.time_ms / 1000.0, 3),
            "augment_bytes_delivered": self.bytes_delivered,
            "augment_hit_rate": round(self.hits / search_commands, 4) if search_commands else 0.0,
        }


class GrepAugmenter:
    """Build the ``[GT]`` block for one search observation."""

    def __init__(self, session: "GTSession", *, max_bytes: int = AUGMENT_OUTPUT_BYTES):
        self.session = session
        self.max_bytes = max_bytes
        self.metrics = AugmentMetrics()
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

            started = time.perf_counter()
            self.metrics.calls += 1
            blocks: list[str] = []
            try:
                for symbol in symbols:
                    result = structure.symbol_context(self.session, symbol)
                    if result.status in ("unavailable", "error", "abstain"):
                        continue
                    block = render_symbol_block(symbol, result.answer)
                    if block:
                        blocks.append(block)
            except Exception as exc:  # noqa: BLE001 - enrichment is silent on failure
                self.metrics.errors += 1
                self._journal(pattern=pattern[:200], outcome=f"error:{type(exc).__name__}")
                return ""
            finally:
                self.metrics.time_ms += int(round((time.perf_counter() - started) * 1000))
            if not blocks:
                self._journal(pattern=pattern[:200], symbols=list(symbols), outcome="silent")
                return ""
            text = cap_text(
                "[GT] graph context for your search:\n" + "\n".join(blocks),
                self.max_bytes,
            )
            self.metrics.hits += 1
            self.metrics.bytes_delivered += len(text.encode("utf-8"))
            self.delivered_texts.append(text)
            self._journal(pattern=pattern[:200], symbols=list(symbols), outcome="hit",
                          bytes=len(text.encode("utf-8")))
            return text


__all__ = [
    "AugmentMetrics",
    "GrepAugmenter",
    "extract_search_pattern",
    "render_symbol_block",
    "symbols_in_pattern",
]
