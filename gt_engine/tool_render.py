"""Model-shaped rendering of capability answers for the attached delivery mode.

GitNexus's lesson (eval/agents/gitnexus_agent.py): the agent reads compact
relational prose, not envelopes. Every answer here is plain text, bounded,
free of revision hashes, and states its own truncation and partiality. The
full envelope stays in the journal.
"""
from __future__ import annotations

import re
from typing import Any

from gt_engine.capabilities._query import CapabilityResult

DEFAULT_TOOL_OUTPUT_BYTES = 6_000
AUGMENT_OUTPUT_BYTES = 2_000
_MAX_ROWS_PER_LIST = 20
_MAX_STEPS_SHOWN = 8

_LOCATION_KEYS = ("file_path", "path", "file")
_LINE_KEYS = ("call_line", "line", "start_line")
_NAME_KEYS = ("qualified_name", "name", "symbol", "label", "handler", "route")
_TIER_KEYS = ("trust_tier", "tier")
# Content hashes and revision ids cost context and give the model nothing
# to act on; they stay in the journal.
_HASH_VALUE = re.compile(r"^(sha256:)?[0-9a-f]{32,}$")
_SKIP_SCALARS = frozenset({
    "graph_revision", "source_revision", "revision", "sha256", "id", "node_id",
    "repository_revision", "graph_source_revision",
})


def _is_hash(value: Any) -> bool:
    return isinstance(value, str) and bool(_HASH_VALUE.match(value))


def _first(row: dict, keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _render_row(row: Any) -> str:
    if not isinstance(row, dict):
        return str(row)
    if isinstance(row.get("steps"), list):
        steps = [str(step) for step in row["steps"][:_MAX_STEPS_SHOWN]]
        more = len(row["steps"]) - len(steps)
        chain = " -> ".join(steps) + (f" -> ...(+{more})" if more > 0 else "")
        marker = "" if row.get("witnessed") else " (lower bound, unwitnessed)"
        return f"{chain}{marker}"
    parts: list[str] = []
    location = _first(row, _LOCATION_KEYS)
    line = _first(row, _LINE_KEYS)
    if location:
        parts.append(f"{location}:{line}" if line is not None else str(location))
    name = _first(row, _NAME_KEYS)
    if name:
        parts.append(str(name))
    kind = row.get("kind")
    if kind:
        parts.append(f"({kind})")
    tier = _first(row, _TIER_KEYS)
    confidence = row.get("confidence")
    if tier or confidence is not None:
        label = str(tier or "")
        if confidence is not None and tier != "CERTIFIED":
            label = f"{label} conf={confidence}".strip()
        parts.append(f"[{label}]")
    if not parts:
        parts = [
            f"{key}={value}" for key, value in sorted(row.items())
            if not isinstance(value, (dict, list)) and key not in _SKIP_SCALARS
            and not _is_hash(value)
        ][:6]
    return "  ".join(parts)


def _render_value(key: str, value: Any, lines: list[str], indent: str = "") -> bool:
    """Append ``value``'s lines; True when it carried a fact (rows or a
    located object) rather than only counts and echoed arguments."""
    if isinstance(value, list):
        if not value:
            return False
        shown = value[:_MAX_ROWS_PER_LIST]
        lines.append(f"{indent}{key} ({len(value)}):")
        lines.extend(f"{indent}  {_render_row(row)}" for row in shown)
        if len(value) > len(shown):
            lines.append(f"{indent}  ... {len(value) - len(shown)} more not shown")
        return True
    if isinstance(value, dict):
        if value and all(isinstance(item, list) for item in value.values()):
            found = False
            for sub_key in sorted(value, key=str):
                found = _render_value(f"{key} {sub_key}", value[sub_key], lines, indent) or found
            return found
        if value and _first(value, _LOCATION_KEYS + _NAME_KEYS) is not None:
            lines.append(f"{indent}{key}: {_render_row(value)}")
            return True
        return False
    if key not in _SKIP_SCALARS and value not in (None, "", False) and not _is_hash(value):
        lines.append(f"{indent}{key}: {value}")
    return False


def render_answer(answer: Any) -> tuple[list[str], bool]:
    """(lines, substantive): substantive when any fact row was rendered."""
    lines: list[str] = []
    substantive = False
    if isinstance(answer, dict):
        for key in sorted(answer, key=str):
            substantive = _render_value(str(key), answer[key], lines) or substantive
    elif isinstance(answer, list):
        substantive = _render_value("results", answer, lines)
    elif answer not in (None, ""):
        lines.append(str(answer))
        substantive = True
    return lines, substantive


def cap_text(text: str, max_bytes: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    notice = f"\n[output truncated at {max_bytes} bytes]"
    budget = max(0, max_bytes - len(notice.encode("utf-8")))
    clipped = encoded[:budget].decode("utf-8", errors="ignore")
    return clipped.rsplit("\n", 1)[0] + notice


def render_result(
    title: str,
    result: CapabilityResult,
    *,
    next_hint: str = "",
    max_bytes: int = DEFAULT_TOOL_OUTPUT_BYTES,
) -> tuple[str, bool]:
    """Return (text, has_answer). ``has_answer`` drives the exit code."""
    body, substantive = render_answer(result.answer)
    header = f"[GT] {title}"
    if not substantive:
        named = [item for item in (*result.omissions, *result.limitations)
                 if not str(item).startswith(("certified_semantics", "CERTIFICATION_",
                                              "EXACT_COMPLETE"))]
        reason = named[0] if named else (
            result.status if result.status in ("unavailable", "error", "abstain")
            else "no matching facts in the graph")
        return f"{header}: no answer ({reason})", False
    notes: list[str] = []
    if result.status == "partial" or result.semantics != "exact":
        notes.append("partial: name-level graph facts, verify by reading the code")
    if not result.fresh:
        notes.append("graph not current for the latest edit")
    omissions = [str(item) for item in result.omissions][:3]
    if omissions:
        notes.append("omitted: " + ", ".join(omissions))
    lines = [header, *body]
    if notes:
        lines.append("note: " + "; ".join(notes))
    if next_hint:
        lines.append(f"next: {next_hint}")
    return cap_text("\n".join(lines), max_bytes), True
