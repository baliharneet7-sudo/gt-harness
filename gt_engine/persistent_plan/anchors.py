"""Graph anchoring for the persistent plan: what each requirement touches.

Everything here is a read of the published, immutable graph revision. No
requirement is guessed: a row either resolves to nodes the graph actually
contains or it is recorded as an abstention, because a confident plan with
silent gaps is worse than no plan.

The mode candidates are the reason this module exists. A requirement stated in
the prompt is one axis; the modes, flags and alternate paths already present in
the repository are the other. The prompt never enumerates the cross product, so
an agent reading only the prompt satisfies the requirement on the default path
and fails the alternate one. The three detectors below are structural -- an
enum-shaped class is a class whose members are constants, a config-shaped class
is one whose fields carry defaults, a flag parameter is a parameter with a
default -- so they work on any repository without a curated list of names.
"""
from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import dataclass, field

# Definition-bearing labels across the producer's languages. 'Enum',
# 'Interface', 'Struct' and 'Trait' do not appear in every language's graph
# (Python enums are Classes), which is exactly why membership is decided by
# structure below rather than by label.
_DEFINITION_LABELS = ("Function", "Method", "Class", "Interface", "Enum", "Struct", "Trait")
_CONTAINER_LABELS = ("Class", "Interface", "Enum", "Struct", "Trait")

# Edge types that make a neighbour reachable from an anchor for the purpose of
# "what else could this requirement touch".
_NEIGHBOUR_EDGES = ("CALLS", "READS", "WRITES", "IMPORTS", "EXTENDS", "CONTAINS", "COMPOSES")

_CONST_MEMBER_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_ASSIGNMENT_RE = re.compile(r"^\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*(?::[^=]+)?(?:=(?P<value>.*))?$")
_DEFAULTED_PARAM_RE = re.compile(
    r"^\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*(?::\s*(?P<type>[^=]+?))?\s*=\s*(?P<default>.+?)\s*$"
)
_MODE_TYPE_RE = re.compile(r"(?i)\b(bool|boolean|optional|literal|enum|flag|mode|option)\b")

MAX_ANCHORS_PER_ROW = 6
# A lexical hit is a shared word, not a resolved identifier. Two is enough to
# offer a starting point; more of them drown the exact matches that are facts.
MAX_LEXICAL_ANCHORS = 2
MAX_CALLERS_PER_ANCHOR = 12
MAX_MODE_CANDIDATES = 24
MAX_MEMBERS_PER_MODE = 16


@dataclass(frozen=True)
class Anchor:
    node_id: int
    name: str
    qualified_name: str
    label: str
    file_path: str
    start_line: int
    signature: str
    language: str
    basis: str

    def as_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "name": self.name,
            "qualified_name": self.qualified_name,
            "label": self.label,
            "file": self.file_path,
            "line": self.start_line,
            "signature": self.signature[:240],
            "language": self.language,
            "basis": self.basis,
        }


@dataclass(frozen=True)
class Caller:
    node_id: int
    name: str
    file_path: str
    calls_node_id: int

    def as_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "name": self.name,
            "file": self.file_path,
            "calls": self.calls_node_id,
        }


@dataclass(frozen=True)
class ModeCandidate:
    """An existing switch a new requirement may have to behave correctly under."""

    symbol: str
    node_id: int
    file_path: str
    kind: str
    members: tuple[str, ...]
    reached_from: tuple[int, ...] = ()

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "node_id": self.node_id,
            "file": self.file_path,
            "kind": self.kind,
            "members": list(self.members),
            "reached_from": list(self.reached_from),
        }


@dataclass
class AnchorResult:
    anchors: dict[str, tuple[Anchor, ...]] = field(default_factory=dict)
    callers: dict[int, tuple[Caller, ...]] = field(default_factory=dict)
    modes: tuple[ModeCandidate, ...] = ()
    edit_order: tuple[str, ...] = ()
    abstentions: tuple[tuple[str, str], ...] = ()
    surfaces: dict[str, bool] = field(default_factory=dict)

    def anchored_rows(self) -> int:
        return sum(1 for items in self.anchors.values() if items)

    def all_node_ids(self) -> tuple[int, ...]:
        seen: list[int] = []
        for items in self.anchors.values():
            for anchor in items:
                if anchor.node_id not in seen:
                    seen.append(anchor.node_id)
        return tuple(seen)

    def all_names(self) -> tuple[str, ...]:
        names = {anchor.name for items in self.anchors.values() for anchor in items}
        return tuple(sorted(name for name in names if name))


def connect_readonly(graph_db: str | None) -> sqlite3.Connection | None:
    """Open the published revision read-only; None on any fault."""
    if not graph_db or not os.path.isfile(graph_db):
        return None
    try:
        connection = sqlite3.connect(f"file:{graph_db}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        return connection
    except sqlite3.Error:
        return None


def _tables(connection: sqlite3.Connection) -> set[str]:
    try:
        return {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
            )
        }
    except sqlite3.Error:
        return set()


def _rows(connection: sqlite3.Connection, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    try:
        return list(connection.execute(sql, params))
    except sqlite3.Error:
        return []


def _anchor_from_row(row: sqlite3.Row, basis: str) -> Anchor:
    return Anchor(
        node_id=int(row["id"]),
        name=str(row["name"] or ""),
        qualified_name=str(row["qualified_name"] or "" if "qualified_name" in row.keys() else ""),
        label=str(row["label"] or ""),
        file_path=str(row["file_path"] or "").replace("\\", "/").lstrip("./"),
        start_line=int(row["start_line"] or 0),
        signature=str(row["signature"] or "" if "signature" in row.keys() else ""),
        language=str(row["language"] or "" if "language" in row.keys() else ""),
        basis=basis,
    )


_NODE_COLUMNS = (
    "id, label, name, qualified_name, file_path, start_line, signature, language"
)


def resolve_row_anchors(
    connection: sqlite3.Connection, terms: tuple[str, ...], *, limit: int = MAX_ANCHORS_PER_ROW
) -> tuple[Anchor, ...]:
    """Definitions a requirement's own identifiers name, exact match first.

    Exact name and qualified-name matches are FACT-grade: the identifier the
    prompt wrote is the identifier the graph holds. The FTS pass is a fallback
    for prose that names a concept rather than a symbol, and is marked as such
    so the plan can say which anchors are weaker.
    """
    if not terms:
        return ()
    found: dict[int, Anchor] = {}
    labels = ",".join("?" * len(_DEFINITION_LABELS))
    candidates = [term for term in terms if term][:24]
    if candidates:
        placeholders = ",".join("?" * len(candidates))
        sql = (
            f"SELECT {_NODE_COLUMNS} FROM nodes "
            f"WHERE COALESCE(is_test,0)=0 AND label IN ({labels}) "
            f"AND (name IN ({placeholders}) COLLATE NOCASE "
            f"OR qualified_name IN ({placeholders}) COLLATE NOCASE) "
            f"ORDER BY (label='Class') DESC, id LIMIT ?"
        )
        params = (*_DEFINITION_LABELS, *candidates, *candidates, limit * 3)
        for row in _rows(connection, sql, params):
            anchor = _anchor_from_row(row, "exact_name")
            found.setdefault(anchor.node_id, anchor)
    # Lexical search is a FALLBACK, not a supplement. Measured on a real task:
    # 51 lexical anchors against 8 exact ones, with a single unrelated helper
    # attached to four different requirements. A row that already resolved the
    # identifier it named gains nothing from a bag of words that merely share a
    # token, and the noise makes the plan read as though everything is located.
    if not found and "nodes_fts" in _tables(connection):
        query = " OR ".join(f'"{term}"' for term in candidates[:8] if term)
        if query:
            sql = (
                f"SELECT n.id, n.label, n.name, n.qualified_name, n.file_path, "
                f"n.start_line, n.signature, n.language FROM nodes_fts f "
                f"JOIN nodes n ON n.id = f.rowid "
                f"WHERE nodes_fts MATCH ? AND COALESCE(n.is_test,0)=0 "
                f"AND n.label IN ({labels}) ORDER BY bm25(nodes_fts) LIMIT ?"
            )
            for row in _rows(
                connection, sql, (query, *_DEFINITION_LABELS, MAX_LEXICAL_ANCHORS)
            ):
                anchor = _anchor_from_row(row, "lexical")
                found.setdefault(anchor.node_id, anchor)
    ordered = sorted(
        found.values(), key=lambda item: (item.basis != "exact_name", item.node_id)
    )
    return tuple(ordered[:limit])


def callers_of(
    connection: sqlite3.Connection,
    node_ids: tuple[int, ...],
    *,
    limit: int = MAX_CALLERS_PER_ANCHOR,
) -> dict[int, tuple[Caller, ...]]:
    """Direct verified callers per anchor: the blast radius of editing it."""
    if not node_ids:
        return {}
    placeholders = ",".join("?" * len(node_ids))
    sql = (
        f"SELECT e.target_id AS anchor_id, n.id, n.name, n.file_path "
        f"FROM edges e JOIN nodes n ON n.id = e.source_id "
        f"WHERE e.target_id IN ({placeholders}) AND e.type='CALLS' "
        f"AND COALESCE(n.is_test,0)=0 "
        f"ORDER BY COALESCE(e.confidence,0) DESC, n.id"
    )
    out: dict[int, list[Caller]] = {}
    for row in _rows(connection, sql, tuple(node_ids)):
        anchor_id = int(row["anchor_id"])
        bucket = out.setdefault(anchor_id, [])
        if len(bucket) >= limit:
            continue
        caller = Caller(
            node_id=int(row["id"]),
            name=str(row["name"] or ""),
            file_path=str(row["file_path"] or "").replace("\\", "/").lstrip("./"),
            calls_node_id=anchor_id,
        )
        if all(existing.node_id != caller.node_id for existing in bucket):
            bucket.append(caller)
    return {key: tuple(value) for key, value in out.items()}


def _member_name(raw: str) -> tuple[str, str]:
    match = _ASSIGNMENT_RE.match((raw or "").strip())
    if not match:
        return "", ""
    return match.group("name") or "", (match.group("value") or "").strip()


def _neighbour_ids(
    connection: sqlite3.Connection, node_ids: tuple[int, ...]
) -> dict[int, set[int]]:
    """Nodes one edge away from each anchor, in either direction."""
    if not node_ids:
        return {}
    placeholders = ",".join("?" * len(node_ids))
    types = ",".join("?" * len(_NEIGHBOUR_EDGES))
    sql = (
        f"SELECT source_id, target_id FROM edges "
        f"WHERE type IN ({types}) "
        f"AND (source_id IN ({placeholders}) OR target_id IN ({placeholders}))"
    )
    params = (*_NEIGHBOUR_EDGES, *node_ids, *node_ids)
    anchors = set(node_ids)
    out: dict[int, set[int]] = {}
    for row in _rows(connection, sql, params):
        source, target = int(row["source_id"]), int(row["target_id"])
        if source in anchors:
            out.setdefault(source, set()).add(target)
        if target in anchors:
            out.setdefault(target, set()).add(source)
    return out


def mode_candidates(
    connection: sqlite3.Connection,
    anchors: tuple[Anchor, ...],
    *,
    limit: int = MAX_MODE_CANDIDATES,
) -> tuple[ModeCandidate, ...]:
    """Existing switches reachable from the anchors, found by structure.

    Three detectors, none of which needs a curated name list:

    * ``enum_like`` -- a container whose members are constants. Python enums are
      plain classes in the graph, so a label test would find none of them.
    * ``config_like`` -- a container whose fields carry defaults: an options
      object whose non-default values are the alternate paths.
    * ``flag_param`` -- a parameter of an anchor that has a default, or whose
      type is boolean/optional/literal. The default is the path the agent will
      exercise; the others are the ones it will not.
    """
    if not anchors:
        return ()
    tables = _tables(connection)
    if "nodes" not in tables:
        return ()
    anchor_ids = tuple(dict.fromkeys(anchor.node_id for anchor in anchors))
    anchor_files = {anchor.file_path for anchor in anchors if anchor.file_path}
    neighbours = _neighbour_ids(connection, anchor_ids)
    reachable: dict[int, set[int]] = {}
    for anchor_id, related in neighbours.items():
        for node_id in related:
            reachable.setdefault(node_id, set()).add(anchor_id)

    containers: dict[int, sqlite3.Row] = {}
    labels = ",".join("?" * len(_CONTAINER_LABELS))
    if reachable:
        ids = tuple(list(reachable)[:400])
        placeholders = ",".join("?" * len(ids))
        sql = (
            f"SELECT {_NODE_COLUMNS} FROM nodes WHERE id IN ({placeholders}) "
            f"AND label IN ({labels}) AND COALESCE(is_test,0)=0"
        )
        for row in _rows(connection, sql, (*ids, *_CONTAINER_LABELS)):
            containers[int(row["id"])] = row
    if anchor_files:
        files = tuple(sorted(anchor_files)[:12])
        placeholders = ",".join("?" * len(files))
        sql = (
            f"SELECT {_NODE_COLUMNS} FROM nodes "
            f"WHERE file_path IN ({placeholders}) AND label IN ({labels}) "
            f"AND COALESCE(is_test,0)=0 LIMIT 200"
        )
        for row in _rows(connection, sql, (*files, *_CONTAINER_LABELS)):
            containers.setdefault(int(row["id"]), row)

    found: list[ModeCandidate] = []
    if containers and "properties" in tables:
        ids = tuple(containers)
        placeholders = ",".join("?" * len(ids))
        sql = (
            f"SELECT node_id, value FROM properties "
            f"WHERE node_id IN ({placeholders}) AND kind='class_field' "
            f"ORDER BY node_id, COALESCE(line,0)"
        )
        fields: dict[int, list[tuple[str, str]]] = {}
        for row in _rows(connection, sql, ids):
            name, value = _member_name(str(row["value"] or ""))
            if name and not name.startswith("__"):
                fields.setdefault(int(row["node_id"]), []).append((name, value))
        for node_id, members in fields.items():
            row = containers[node_id]
            constants = [name for name, _value in members if _CONST_MEMBER_RE.match(name)]
            defaulted = [name for name, value in members if value]
            if len(constants) >= 2:
                kind, chosen = "enum_like", constants
            elif len(defaulted) >= 2:
                kind, chosen = "config_like", defaulted
            else:
                continue
            found.append(
                ModeCandidate(
                    symbol=str(row["name"] or ""),
                    node_id=node_id,
                    file_path=str(row["file_path"] or "").replace("\\", "/").lstrip("./"),
                    kind=kind,
                    members=tuple(chosen[:MAX_MEMBERS_PER_MODE]),
                    reached_from=tuple(sorted(reachable.get(node_id, set()))),
                )
            )

    if "properties" in tables and anchor_ids:
        placeholders = ",".join("?" * len(anchor_ids))
        sql = (
            f"SELECT node_id, value FROM properties "
            f"WHERE node_id IN ({placeholders}) AND kind='param' "
            f"ORDER BY node_id, COALESCE(line,0)"
        )
        by_anchor: dict[int, list[str]] = {}
        for row in _rows(connection, sql, anchor_ids):
            raw = str(row["value"] or "").strip()
            match = _DEFAULTED_PARAM_RE.match(raw)
            name = ""
            if match:
                name = match.group("name")
            else:
                candidate, _value = _member_name(raw)
                if candidate and _MODE_TYPE_RE.search(raw):
                    name = candidate
            if name and name not in {"self", "cls"}:
                by_anchor.setdefault(int(row["node_id"]), []).append(raw[:80])
        anchor_by_id = {anchor.node_id: anchor for anchor in anchors}
        for node_id, params in by_anchor.items():
            anchor = anchor_by_id.get(node_id)
            if anchor is None or not params:
                continue
            found.append(
                ModeCandidate(
                    symbol=anchor.qualified_name or anchor.name,
                    node_id=node_id,
                    file_path=anchor.file_path,
                    kind="flag_param",
                    members=tuple(params[:MAX_MEMBERS_PER_MODE]),
                    reached_from=(node_id,),
                )
            )

    found.sort(key=lambda item: (item.kind != "enum_like", -len(item.members), item.symbol))
    return tuple(found[:limit])


def edit_order(
    connection: sqlite3.Connection, anchors_by_row: dict[str, tuple[Anchor, ...]]
) -> tuple[str, ...]:
    """Row order that edits callees before their callers.

    Deterministic and advisory: it is rendered for the agent to follow, never
    enforced. Ties and cycles fall back to the ledger's own order, so this can
    reorder rows but can never drop one.
    """
    rows = list(anchors_by_row)
    if not rows:
        return ()
    node_to_rows: dict[int, set[str]] = {}
    for row_id, anchors in anchors_by_row.items():
        for anchor in anchors:
            node_to_rows.setdefault(anchor.node_id, set()).add(row_id)
    if not node_to_rows:
        return tuple(rows)
    ids = tuple(node_to_rows)
    placeholders = ",".join("?" * len(ids))
    sql = (
        f"SELECT source_id, target_id FROM edges WHERE type='CALLS' "
        f"AND source_id IN ({placeholders}) AND target_id IN ({placeholders})"
    )
    depth = {row_id: 0 for row_id in rows}
    edges: list[tuple[str, str]] = []
    for edge in _rows(connection, sql, (*ids, *ids)):
        for caller_row in node_to_rows.get(int(edge["source_id"]), ()):  # noqa: PLR1702
            for callee_row in node_to_rows.get(int(edge["target_id"]), ()):
                if caller_row != callee_row:
                    edges.append((caller_row, callee_row))
    # Bounded relaxation instead of a full toposort: a cycle in the call graph
    # is normal and must not deadlock the ordering.
    for _pass in range(min(8, len(rows))):
        changed = False
        for caller_row, callee_row in edges:
            if depth[caller_row] <= depth[callee_row]:
                depth[caller_row] = depth[callee_row] + 1
                changed = True
        if not changed:
            break
    # A caller's depth is its callee's plus one, so ASCENDING depth edits the
    # callee first -- the bottom-up order that keeps an earlier edit's ground
    # from being moved by a later one.
    original = {row_id: index for index, row_id in enumerate(rows)}
    return tuple(sorted(rows, key=lambda row_id: (depth[row_id], original[row_id])))


def build_anchor_result(graph_db: str | None, ledger) -> AnchorResult:
    """Resolve every ledger row against the published graph revision."""
    result = AnchorResult()
    connection = connect_readonly(graph_db)
    if connection is None:
        result.abstentions = (("*", "graph_unavailable"),)
        return result
    try:
        tables = _tables(connection)
        result.surfaces = {
            name: name in tables
            for name in ("nodes", "edges", "properties", "nodes_fts", "closure")
        }
        if "nodes" not in tables:
            result.abstentions = (("*", "graph_has_no_nodes_surface"),)
            return result
        abstentions: list[tuple[str, str]] = []
        for row in ledger.rows:
            terms = tuple(dict.fromkeys((*row.subjects, *row.tokens)))
            anchors = resolve_row_anchors(connection, terms)
            result.anchors[row.row_id] = anchors
            if not anchors:
                abstentions.append((row.row_id, "no_anchor"))
        node_ids = result.all_node_ids()
        result.callers = callers_of(connection, node_ids)
        every_anchor = tuple(
            anchor for anchors in result.anchors.values() for anchor in anchors
        )
        result.modes = mode_candidates(connection, every_anchor)
        if not result.modes and every_anchor:
            abstentions.append(("*", "no_mode_candidates_reachable"))
        result.edit_order = edit_order(connection, result.anchors)
        result.abstentions = tuple(abstentions)
        return result
    finally:
        try:
            connection.close()
        except sqlite3.Error:
            pass
