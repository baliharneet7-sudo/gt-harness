"""Output-identical performance shim for one certified-wheel hot path.

``groundtruth.runtime.processes._stable_id_to_nodes`` (wheel 658cad06) joins
``resolution_symbols`` with ``ON CAST(rs.native_id AS INTEGER) = n.id``. The
cast defeats every index, so SQLite runs a nested scan of every node against
every resolution symbol: 40 s of a 54 s ``symbol_context`` call on
adaptix@a691069 (489 files), paid on every call because nothing memoizes it.

The shim computes the same mapping - ``COALESCE(NULLIF(n.stable_id,''),
rs.stable_id, '')`` per joined row, later rows overwriting earlier ones for a
repeated stable id, exactly as the original loop does - with two linear scans
and a dict join. The wheel's bytes are untouched; the function is replaced in
the running process only. Equality with the original is pinned by tests on a
real producer graph. The real fix belongs in the wheel.
"""
from __future__ import annotations

import os
import sqlite3
from typing import Any, Callable

_ORIGINAL: Callable[..., Any] | None = None
_ORIGINAL_DETECT: Callable[..., Any] | None = None
# Published graphs are immutable (an amend publishes a new file), so one
# detection per (file identity, arguments) is exact. Bounded to a few graphs.
_DETECT_CACHE: dict[tuple[Any, ...], Any] = {}
_DETECT_CACHE_MAX = 4


def _native_as_int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def fast_stable_id_to_nodes(connection: sqlite3.Connection) -> dict[str, Any]:
    from groundtruth.runtime.processes import ProcessNode

    node_cols = {row[1] for row in connection.execute("PRAGMA table_info(nodes)")}
    has_rs = bool(connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='resolution_symbols'"
    ).fetchone())
    stable_col = "stable_id" if "stable_id" in node_cols else "''"
    by_native: dict[int, list[str]] = {}
    if has_rs:
        for native_id, stable_id in connection.execute(
            "SELECT native_id, stable_id FROM resolution_symbols"
        ):
            key = _native_as_int(native_id)
            if key is not None:
                by_native.setdefault(key, []).append(stable_id)
    out: dict[str, Any] = {}
    for row in connection.execute(
        "SELECT id, name, COALESCE(label,''), COALESCE(file_path,''),"
        " COALESCE(start_line,0), COALESCE(signature,''), COALESCE(is_test,0),"
        f" COALESCE({stable_col},'') FROM nodes"
    ):
        node_id, name, label, file_path, start_line, signature, is_test, own = row
        joined = by_native.get(int(node_id)) if has_rs else None
        candidates = [own or rs_sid or "" for rs_sid in joined] if joined else [own or ""]
        for sid in candidates:
            if not sid:
                continue
            out[str(sid)] = ProcessNode(
                node_id=int(node_id),
                name=str(name or ""),
                label=str(label or ""),
                file_path=str(file_path or ""),
                start_line=int(start_line or 0),
                signature=str(signature or ""),
                is_test=bool(is_test),
            )
    return out


def _graph_identity(graph_db: Any) -> tuple[Any, ...] | None:
    try:
        stat = os.stat(graph_db)
    except (OSError, TypeError, ValueError):
        return None
    return (os.path.realpath(str(graph_db)), stat.st_size, stat.st_mtime_ns)


def memo_detect_processes(graph_db: Any, **kwargs: Any) -> Any:
    assert _ORIGINAL_DETECT is not None
    identity = _graph_identity(graph_db)
    if identity is None:
        return _ORIGINAL_DETECT(graph_db, **kwargs)
    key = (*identity, tuple(sorted(kwargs.items())))
    if key not in _DETECT_CACHE:
        if len(_DETECT_CACHE) >= _DETECT_CACHE_MAX:
            _DETECT_CACHE.pop(next(iter(_DETECT_CACHE)))
        _DETECT_CACHE[key] = _ORIGINAL_DETECT(graph_db, **kwargs)
    return _DETECT_CACHE[key]


def install() -> bool:
    """Replace the hot paths in this process. Idempotent; False if absent."""
    global _ORIGINAL, _ORIGINAL_DETECT
    try:
        from groundtruth.runtime import deterministic_queries, processes
    except ImportError:
        return False
    current = getattr(processes, "_stable_id_to_nodes", None)
    if current is None:
        return False
    if current is not fast_stable_id_to_nodes:
        _ORIGINAL = current
        processes._stable_id_to_nodes = fast_stable_id_to_nodes
    if processes.detect_processes is not memo_detect_processes:
        _ORIGINAL_DETECT = processes.detect_processes
        processes.detect_processes = memo_detect_processes
        if getattr(deterministic_queries, "detect_processes", None) is _ORIGINAL_DETECT:
            deterministic_queries.detect_processes = memo_detect_processes
    return True


def uninstall() -> None:
    global _ORIGINAL, _ORIGINAL_DETECT
    from groundtruth.runtime import deterministic_queries, processes

    if _ORIGINAL is not None:
        processes._stable_id_to_nodes = _ORIGINAL
        _ORIGINAL = None
    if _ORIGINAL_DETECT is not None:
        processes.detect_processes = _ORIGINAL_DETECT
        if deterministic_queries.detect_processes is memo_detect_processes:
            deterministic_queries.detect_processes = _ORIGINAL_DETECT
        _ORIGINAL_DETECT = None
    _DETECT_CACHE.clear()


def original() -> Callable[..., Any] | None:
    if _ORIGINAL is not None:
        return _ORIGINAL
    try:
        from groundtruth.runtime import processes
    except ImportError:
        return None
    current = processes._stable_id_to_nodes
    return None if current is fast_stable_id_to_nodes else current


__all__ = ["fast_stable_id_to_nodes", "install", "memo_detect_processes", "original", "uninstall"]
