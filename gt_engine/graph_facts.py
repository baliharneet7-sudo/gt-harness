"""One-line graph facts about a resolved symbol, for attached observations.

The ``symbol_context`` answer covers definition, callers, callees and flows
(F2/F4/F9/F12). Every other feature that has something to say about the same
symbol - who references it (F3), how its call sites resolved (F5/F6), what
overrides or implements it (F7), which route or middleware it serves and what
is injected (F8/F18), which module it moves with (F10), which files change with
it (F13) - was reachable only through a tool the agent rarely calls. These are
read directly from the producer's published tables in one connection, so they
cost a few indexed lookups per hit, and each is omitted when the graph has
nothing to say.
"""
from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:  # pragma: no cover - typing only
    from gt_engine.gt_session import GTSession

MAX_FILES_SHOWN = 4
MAX_RELATED_SHOWN = 4
_REFERENCE_EDGES = ("CALLS", "ACCESSES", "READS", "WRITES", "INJECTS", "PARAM_TYPE", "IMPORTS")
_HIERARCHY_EDGES = ("EXTENDS", "IMPLEMENTS", "DECLARED_IMPLEMENTS")
_OVERRIDE_EDGES = ("OVERRIDES", "METHOD_OVERRIDES")


def _placeholders(values: tuple[str, ...]) -> str:
    return ",".join("?" * len(values))


def _files(paths: list[str], own: str) -> str:
    ordered = sorted({path for path in paths if path}, key=lambda path: (path != own, path))
    shown = ", ".join(ordered[:MAX_FILES_SHOWN])
    more = len(ordered) - MAX_FILES_SHOWN
    return shown + (f" (+{more} more)" if more > 0 else "")


def _references(conn: sqlite3.Connection, node_id: Any, own: str) -> str | None:
    """F3: distinct files that call, access, inject or import the symbol,
    including call sites whose candidate set names it."""
    paths = [row[0] for row in conn.execute(
        "SELECT DISTINCT s.file_path FROM edges e JOIN nodes s ON s.id = e.source_id"
        f" WHERE e.target_id = ? AND e.type IN ({_placeholders(_REFERENCE_EDGES)})",
        (node_id, *_REFERENCE_EDGES))]
    paths += [row[0] for row in conn.execute(
        "SELECT DISTINCT c.file_path FROM edges e JOIN nodes c ON c.id = e.source_id"
        " WHERE e.target_id = ? AND e.type = 'CANDIDATE_TARGET'", (node_id,))]
    distinct = {path for path in paths if path}
    if not distinct:
        return None
    return f"referenced from {len(distinct)} file(s): {_files(list(distinct), own)}"


def _resolution(conn: sqlite3.Connection, node_id: Any) -> str | None:
    """F5/F6: how the call sites that may reach the symbol were resolved."""
    rows = conn.execute(
        "SELECT c.candidate_state, c.dispatch_form, MAX(e.type = 'SELECTED_TARGET')"
        " FROM edges e JOIN nodes c ON c.id = e.source_id AND c.label = 'Callsite'"
        " WHERE e.target_id = ? AND e.type IN ('CANDIDATE_TARGET', 'SELECTED_TARGET')"
        " GROUP BY c.id", (node_id,)).fetchall()
    if not rows:
        return None
    proven = sum(1 for _state, _form, selected in rows if selected)
    ambiguous = len(rows) - proven
    by_value = sum(1 for _state, form, _selected in rows if form == "function_value")
    parts = [f"{proven} proven"]
    if ambiguous:
        parts.append(f"{ambiguous} ambiguous (dispatch not proven; it may run for them)")
    if by_value:
        parts.append(f"{by_value} as a passed/stored function value")
    return "call sites: " + ", ".join(parts)


def _dispatch(conn: sqlite3.Connection, node_id: Any, label: str) -> list[str]:
    """F7: overriding methods, the method it overrides, and implementations."""
    lines: list[str] = []
    overriders = conn.execute(
        "SELECT DISTINCT p.name, s.name, s.file_path, s.start_line FROM edges e"
        " JOIN nodes s ON s.id = e.source_id LEFT JOIN nodes p ON p.id = s.parent_id"
        f" WHERE e.target_id = ? AND e.type IN ({_placeholders(_OVERRIDE_EDGES)})"
        " ORDER BY s.file_path, s.start_line", (node_id, *_OVERRIDE_EDGES)).fetchall()
    if not overriders and label.lower() == "method":
        # The producer marks overrides syntactically (Java @Override); for
        # Python/TS the hierarchy edges answer it by name.
        overriders = conn.execute(
            "WITH RECURSIVE sub(id) AS ("
            " SELECT parent_id FROM nodes WHERE id = ?"
            " UNION SELECT e.source_id FROM edges e JOIN sub ON e.target_id = sub.id"
            f" WHERE e.type IN ({_placeholders(_HIERARCHY_EDGES)}))"
            " SELECT DISTINCT c.name, m.name, m.file_path, m.start_line FROM sub"
            " JOIN nodes c ON c.id = sub.id JOIN nodes m ON m.parent_id = c.id"
            " WHERE m.name = (SELECT name FROM nodes WHERE id = ?) AND m.id != ?"
            " AND m.label = 'Method' ORDER BY m.file_path, m.start_line",
            (node_id, *_HIERARCHY_EDGES, node_id, node_id)).fetchall()
    if overriders:
        shown = [f"{owner + '.' if owner else ''}{name} ({path}:{line})"
                 for owner, name, path, line in overriders[:MAX_RELATED_SHOWN]]
        more = len(overriders) - len(shown)
        lines.append("overridden by: " + ", ".join(shown) + (f" (+{more} more)" if more > 0 else ""))
    overridden = conn.execute(
        "SELECT DISTINCT p.name, t.name, t.file_path, t.start_line FROM edges e"
        " JOIN nodes t ON t.id = e.target_id LEFT JOIN nodes p ON p.id = t.parent_id"
        f" WHERE e.source_id = ? AND e.type IN ({_placeholders(_OVERRIDE_EDGES)})"
        " ORDER BY t.file_path, t.start_line", (node_id, *_OVERRIDE_EDGES)).fetchall()
    if overridden:
        shown = [f"{owner + '.' if owner else ''}{name} ({path}:{line})"
                 for owner, name, path, line in overridden[:MAX_RELATED_SHOWN]]
        lines.append("overrides: " + ", ".join(shown))
    if label.lower() in ("class", "interface", "struct", "trait"):
        subtypes = conn.execute(
            "SELECT DISTINCT s.name, s.file_path, s.start_line FROM edges e"
            f" JOIN nodes s ON s.id = e.source_id WHERE e.target_id = ?"
            f" AND e.type IN ({_placeholders(_HIERARCHY_EDGES)}) ORDER BY s.file_path, s.start_line",
            (node_id, *_HIERARCHY_EDGES)).fetchall()
        if subtypes:
            shown = [f"{name} ({path}:{line})" for name, path, line in subtypes[:MAX_RELATED_SHOWN]]
            more = len(subtypes) - len(shown)
            lines.append("extended/implemented by: " + ", ".join(shown)
                         + (f" (+{more} more)" if more > 0 else ""))
    return lines


def _metadata(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _framework(conn: sqlite3.Connection, node_id: Any) -> list[str]:
    """F8/F18: routes the symbol handles, middleware it is, injections."""
    lines: list[str] = []
    for edge_type, raw, tier in conn.execute(
        "SELECT type, metadata, trust_tier FROM edges WHERE source_id = ?"
        " AND type IN ('HANDLES_ROUTE', 'MIDDLEWARE_ON') ORDER BY source_line", (node_id,)):
        meta = _metadata(raw)
        tier_note = f" [{tier}]" if tier and tier != "CERTIFIED" else ""
        if edge_type == "HANDLES_ROUTE":
            method = f"{meta.get('method')} " if meta.get("method") else ""
            lines.append(f"handles route {method}{meta.get('route') or '?'}"
                         f" ({meta.get('framework') or meta.get('mechanism') or 'framework'}){tier_note};"
                         " `gt-api <route>` shows its clients")
        else:
            scope = meta.get("route") or "all routes"
            lines.append(f"middleware on {scope} ({meta.get('mechanism') or 'framework'}){tier_note}")
    injected = conn.execute(
        "SELECT DISTINCT s.name, s.file_path, s.start_line, e.metadata FROM edges e"
        " JOIN nodes s ON s.id = e.source_id WHERE e.target_id = ? AND e.type = 'INJECTS'"
        " ORDER BY s.file_path, s.start_line", (node_id,)).fetchall()
    if injected:
        shown = [f"{name} ({path}:{line}, {_metadata(raw).get('mechanism') or 'di'})"
                 for name, path, line, raw in injected[:MAX_RELATED_SHOWN]]
        lines.append("injected into: " + ", ".join(shown))
    return lines


def _module(conn: sqlite3.Connection, path: str) -> str | None:
    """F10: the community (module) the definition's file belongs to."""
    row = conn.execute(
        "SELECT c.id, COALESCE(c.label, c.heuristic_label), c.member_count"
        " FROM community_members m JOIN communities c ON c.id = m.community_id"
        " WHERE m.member = ? AND m.member_kind = 'file' LIMIT 1", (path,)).fetchone()
    if row is None:
        return None
    community_id, label, count = row
    siblings = [member for (member,) in conn.execute(
        "SELECT member FROM community_members WHERE community_id = ? AND member_kind = 'file'"
        " AND member != ? ORDER BY member LIMIT ?", (community_id, path, MAX_FILES_SHOWN + 1))]
    if not siblings:
        return None
    return f"module {label} ({count} files) with: {_files(siblings, '')}"


def _cochange(conn: sqlite3.Connection, path: str) -> str | None:
    """F13 prior: files that historically changed in the same commits."""
    rows = conn.execute(
        "SELECT CASE WHEN file_a = ? THEN file_b ELSE file_a END, count,"
        " CASE WHEN file_a = ? THEN confidence_a_to_b ELSE confidence_b_to_a END"
        " FROM cochanges WHERE file_a = ? OR file_b = ? ORDER BY count DESC LIMIT ?",
        (path, path, path, path, MAX_RELATED_SHOWN)).fetchall()
    if not rows:
        return None
    shown = [f"{other} ({count}x" + (f", {confidence:.0%}" if isinstance(confidence, (int, float)) else "") + ")"
             for other, count, confidence in rows]
    return "usually changes with: " + ", ".join(shown)


def _guarded(fact: Callable[[], Any]) -> Any:
    """An older graph may lack a table or column: that fact is simply absent."""
    try:
        return fact()
    except sqlite3.Error:
        return None


def symbol_facts(session: "GTSession", definition: dict[str, Any]) -> list[tuple[str, str]]:
    """(feature ids, fact line) pairs for one resolved definition; empty when
    none apply. Feature ids are space-separated (``"F5 F6"``) so a delivery
    is credited only to the features whose facts it actually carried."""
    from gt_engine.capabilities._query import graph_conn

    node_id = definition.get("id")
    if node_id is None:
        return []
    conn = graph_conn(session)
    if conn is None:
        return []
    path = str(definition.get("file_path") or "")
    label = str(definition.get("label") or definition.get("kind") or "")
    facts: list[tuple[str, str]] = []
    try:
        references = _guarded(lambda: _references(conn, node_id, path))
        if references:
            facts.append(("F3", references))
        resolution = _guarded(lambda: _resolution(conn, node_id))
        if resolution:
            facts.append(("F5 F6" if "function value" in resolution else "F5", resolution))
        facts += [("F7", line) for line in _guarded(lambda: _dispatch(conn, node_id, label)) or ()]
        facts += [("F8 F18" if line.startswith("handles route") else "F8", line)
                  for line in _guarded(lambda: _framework(conn, node_id)) or ()]
        module = _guarded(lambda: _module(conn, path))
        if module:
            facts.append(("F10", module))
        cochange = _guarded(lambda: _cochange(conn, path))
        if cochange:
            facts.append(("F13", cochange))
    finally:
        conn.close()
    return facts


__all__ = ["symbol_facts"]
