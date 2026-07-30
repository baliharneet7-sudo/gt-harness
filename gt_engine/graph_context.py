"""Read-only projection of graph.db surfaces into task and verification context."""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass

from gt_engine.task_contract import TaskContract, significant_tokens

GRAPH_SURFACES = (
    "nodes",
    "nodes_fts",
    "symbol_content_fts",
    "content_passages",
    "content_passages_fts",
    "edges",
    "edge_metadata",
    "closure",
    "properties",
    "assertions",
    "cochanges",
    "cochange_sets",
    "file_hashes",
    "project_meta",
)


@dataclass(frozen=True)
class GraphProjection:
    files: frozenset[str]
    symbols: frozenset[str]
    node_ids: frozenset[int]
    surface_hits: tuple[tuple[str, int], ...]


def _connect(graph_db: str) -> sqlite3.Connection | None:
    if not graph_db or not os.path.isfile(graph_db):
        return None
    try:
        return sqlite3.connect(f"file:{graph_db}?mode=ro", uri=True)
    except sqlite3.Error:
        return None


def _tables(con: sqlite3.Connection) -> set[str]:
    try:
        return {
            str(row[0])
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
            )
        }
    except sqlite3.Error:
        return set()


def graph_surface_receipt(graph_db: str) -> dict[str, object]:
    counts = {name: 0 for name in GRAPH_SURFACES}
    con = _connect(graph_db)
    if con is None:
        return {"available": False, "surfaces": counts}
    try:
        present = _tables(con)
        for name in GRAPH_SURFACES:
            if name not in present:
                continue
            try:
                counts[name] = int(con.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0])
            except sqlite3.Error:
                counts[name] = 0
        return {"available": True, "surfaces": counts}
    finally:
        con.close()


def _fts_query(contract: TaskContract) -> str:
    tokens: list[str] = []
    for item in contract.obligations:
        tokens.extend(significant_tokens(item.text))
        tokens.extend(s.lower() for s in item.subjects)
    clean = sorted(
        {
            token.replace('"', "")
            for token in tokens
            if token.replace("_", "").replace(".", "").isalnum()
        }
    )[:24]
    return " OR ".join(f'"{token}"' for token in clean)


def build_graph_projection(
    graph_db: str,
    contract: TaskContract,
    *,
    limit: int = 24,
) -> GraphProjection:
    """Use lexical, body, relation, closure, property, test, and cochange surfaces."""
    con = _connect(graph_db)
    if con is None:
        return GraphProjection(frozenset(), frozenset(), frozenset(), ())
    files: set[str] = set()
    symbols: set[str] = set()
    node_ids: set[int] = set()
    hits = {name: 0 for name in GRAPH_SURFACES}
    try:
        tables = _tables(con)
        query = _fts_query(contract)
        if query and "nodes_fts" in tables:
            try:
                rows = con.execute(
                    "SELECT n.id,n.file_path,n.name FROM nodes_fts f "
                    "JOIN nodes n ON n.id=f.rowid WHERE nodes_fts MATCH ? "
                    "AND COALESCE(n.is_test,0)=0 ORDER BY bm25(nodes_fts) LIMIT ?",
                    (query, limit),
                ).fetchall()
                hits["nodes_fts"] += len(rows)
                for node_id, file_path, name in rows:
                    node_ids.add(int(node_id))
                    files.add(str(file_path).replace("\\", "/"))
                    symbols.add(str(name))
            except sqlite3.Error:
                pass
        if query and {"symbol_content_fts", "nodes"} <= tables:
            try:
                rows = con.execute(
                    "SELECT n.id,n.file_path,n.name FROM symbol_content_fts f "
                    "JOIN nodes n ON n.id=f.rowid "
                    "WHERE symbol_content_fts MATCH ? AND COALESCE(n.is_test,0)=0 "
                    "ORDER BY bm25(symbol_content_fts) LIMIT ?",
                    (query, limit),
                ).fetchall()
                hits["symbol_content_fts"] += len(rows)
                for node_id, file_path, name in rows:
                    node_ids.add(int(node_id))
                    files.add(str(file_path).replace("\\", "/"))
                    symbols.add(str(name))
            except sqlite3.Error:
                pass
        if query and {"content_passages_fts", "content_passages", "nodes"} <= tables:
            try:
                rows = con.execute(
                    "SELECT n.id,n.file_path,n.name FROM content_passages_fts f "
                    "JOIN content_passages p ON p.passage_id=f.rowid "
                    "JOIN nodes n ON n.id=p.node_id "
                    "WHERE content_passages_fts MATCH ? AND COALESCE(n.is_test,0)=0 "
                    "ORDER BY bm25(content_passages_fts) LIMIT ?",
                    (query, limit),
                ).fetchall()
                hits["content_passages_fts"] += len(rows)
                hits["content_passages"] += len(rows)
                for node_id, file_path, name in rows:
                    node_ids.add(int(node_id))
                    files.add(str(file_path).replace("\\", "/"))
                    symbols.add(str(name))
            except sqlite3.Error:
                pass

        seed_ids = sorted(node_ids)[:limit]
        if seed_ids and {"edges", "nodes"} <= tables:
            placeholders = ",".join("?" for _ in seed_ids)
            try:
                rows = con.execute(
                    "SELECT DISTINCT n.id,n.file_path,n.name FROM edges e "
                    "JOIN nodes n ON n.id=CASE WHEN e.source_id IN ("
                    + placeholders
                    + ") THEN e.target_id ELSE e.source_id END "
                    "WHERE (e.source_id IN ("
                    + placeholders
                    + ") OR e.target_id IN ("
                    + placeholders
                    + ")) AND e.confidence>=0.7 AND COALESCE(n.is_test,0)=0 "
                    "LIMIT ?",
                    (*seed_ids, *seed_ids, *seed_ids, limit),
                ).fetchall()
                hits["edges"] += len(rows)
                for node_id, file_path, name in rows:
                    node_ids.add(int(node_id))
                    files.add(str(file_path).replace("\\", "/"))
                    symbols.add(str(name))
            except sqlite3.Error:
                pass
        if seed_ids and {"closure", "nodes"} <= tables:
            placeholders = ",".join("?" for _ in seed_ids)
            try:
                rows = con.execute(
                    "SELECT DISTINCT n.id,n.file_path,n.name FROM closure c "
                    "JOIN nodes n ON n.id=c.target_id WHERE c.source_id IN ("
                    + placeholders
                    + ") AND c.depth<=2 AND c.min_confidence>=0.5 "
                    "AND COALESCE(n.is_test,0)=0 LIMIT ?",
                    (*seed_ids, limit),
                ).fetchall()
                hits["closure"] += len(rows)
                for node_id, file_path, name in rows:
                    node_ids.add(int(node_id))
                    files.add(str(file_path).replace("\\", "/"))
                    symbols.add(str(name))
            except sqlite3.Error:
                pass
        if seed_ids and "properties" in tables:
            placeholders = ",".join("?" for _ in seed_ids)
            try:
                hits["properties"] = int(
                    con.execute(
                        "SELECT COUNT(*) FROM properties WHERE node_id IN ("
                        + placeholders
                        + ")",
                        seed_ids,
                    ).fetchone()[0]
                )
            except sqlite3.Error:
                pass
        if seed_ids and "assertions" in tables:
            placeholders = ",".join("?" for _ in seed_ids)
            try:
                hits["assertions"] = int(
                    con.execute(
                        "SELECT COUNT(*) FROM assertions WHERE target_node_id IN ("
                        + placeholders
                        + ")",
                        seed_ids,
                    ).fetchone()[0]
                )
            except sqlite3.Error:
                pass
        if files and "cochanges" in tables:
            base_files = sorted(files)[:limit]
            placeholders = ",".join("?" for _ in base_files)
            try:
                rows = con.execute(
                    "SELECT file_a,file_b FROM cochanges WHERE file_a IN ("
                    + placeholders
                    + ") OR file_b IN ("
                    + placeholders
                    + ") ORDER BY count DESC LIMIT ?",
                    (*base_files, *base_files, limit),
                ).fetchall()
                hits["cochanges"] += len(rows)
                for left, right in rows:
                    files.update(
                        {str(left).replace("\\", "/"), str(right).replace("\\", "/")}
                    )
            except sqlite3.Error:
                pass
        if files and "cochange_sets" in tables:
            base_files = sorted(files)[:limit]
            placeholders = ",".join("?" for _ in base_files)
            try:
                commits = [
                    row[0]
                    for row in con.execute(
                        "SELECT DISTINCT commit_hash FROM cochange_sets "
                        "WHERE file_path IN (" + placeholders + ") LIMIT ?",
                        (*base_files, limit),
                    ).fetchall()
                ]
                if commits:
                    commit_ph = ",".join("?" for _ in commits)
                    rows = con.execute(
                        "SELECT DISTINCT file_path FROM cochange_sets "
                        "WHERE commit_hash IN (" + commit_ph + ") LIMIT ?",
                        (*commits, limit),
                    ).fetchall()
                    hits["cochange_sets"] += len(rows)
                    files.update(str(row[0]).replace("\\", "/") for row in rows)
            except sqlite3.Error:
                pass
        return GraphProjection(
            files=frozenset(files),
            symbols=frozenset(symbols),
            node_ids=frozenset(node_ids),
            surface_hits=tuple(sorted((k, v) for k, v in hits.items() if v)),
        )
    finally:
        con.close()
