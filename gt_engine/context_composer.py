"""Deterministic, bounded graph context for agents and MCP clients."""

from __future__ import annotations

import re
from typing import Any

from gt_engine.repository_graph_service import RepositoryGraphService

_STOP_WORDS = frozenset(
    {
        "and",
        "are",
        "break",
        "breaking",
        "change",
        "fix",
        "for",
        "from",
        "into",
        "its",
        "that",
        "the",
        "their",
        "this",
        "what",
        "when",
        "where",
        "which",
        "with",
        "without",
    }
)


def task_tokens(task: str, *, limit: int = 16) -> tuple[str, ...]:
    """Extract stable identifier-like task terms without semantic guessing."""

    raw = (
        token
        for token in re.findall(r"[A-Za-z_][A-Za-z0-9_:.]{2,}", task or "")
        if token.lower() not in _STOP_WORDS
    )
    expanded: list[str] = []
    for token in raw:
        expanded.append(token)
        if "." in token:
            container = token.rsplit(".", 1)[0]
            if len(container) >= 3:
                expanded.append(container)
    return tuple(dict.fromkeys(expanded))[: max(1, limit)]


def _relationship_modes(label: str) -> tuple[str, ...]:
    normalized = label.lower()
    if normalized in {"function", "method", "constructor"}:
        return ("callers", "callees", "tests")
    if normalized in {"class", "interface", "trait", "type", "struct", "enum"}:
        return ("subclasses", "implementations", "importers", "tests")
    if normalized == "file":
        return ("imports", "reexports", "importers")
    return ("references", "tests")


def _identity(row: dict[str, Any]) -> tuple[object, ...]:
    return (
        row.get("context_role"),
        row.get("relationship"),
        row.get("file_path"),
        row.get("start_line"),
        row.get("qualified_name"),
    )


def compose_repository_context(
    service: RepositoryGraphService,
    task: str,
    *,
    limit: int = 12,
    min_confidence: float = 0.5,
) -> dict[str, Any]:
    """Find task anchors, then compose their source-evidenced relationships.

    Lexical search is used only to establish graph anchors. The returned payload
    also includes callers, callees, inheritance, imports, implementations, and
    tests as applicable. Every row records why it was selected, making ranking
    and agent delivery auditable without a model or embedding provider.
    """

    bound = max(1, min(int(limit), 50))
    tokens = task_tokens(task)
    query_count = 0
    errors: list[str] = []
    anchors: list[dict[str, Any]] = []
    anchor_ids: set[tuple[object, ...]] = set()
    anchor_bound = min(4, max(1, bound // 2))

    for token in tokens:
        try:
            result = service.query("search", token, limit=4)
            query_count += 1
        except Exception as exc:  # noqa: BLE001 - error is returned in the context receipt
            errors.append(f"search:{token}:{type(exc).__name__}")
            continue
        candidates = list(result.get("evidence", ()))
        exact = [
            row
            for row in candidates
            if row.get("name") == token or row.get("qualified_name") == token
        ]
        for source in exact or candidates[:1]:
            row = dict(source)
            row["context_role"] = "anchor"
            row["query_mode"] = "search"
            row["query_token"] = token
            row["anchor_symbol"] = row.get("qualified_name") or row.get("name") or token
            identity = (
                row.get("file_path"),
                row.get("start_line"),
                row.get("qualified_name"),
            )
            if identity in anchor_ids:
                continue
            anchor_ids.add(identity)
            anchors.append(row)
            if len(anchors) >= anchor_bound:
                break
        if len(anchors) >= anchor_bound:
            break

    evidence: list[dict[str, Any]] = []
    identities: set[tuple[object, ...]] = set()
    for anchor in anchors:
        identity = _identity(anchor)
        if identity not in identities and len(evidence) < bound:
            identities.add(identity)
            evidence.append(anchor)

    truncated = len(anchors) > len(evidence)
    plans: list[tuple[dict[str, Any], str]] = []
    relationship_modes = [_relationship_modes(str(row.get("label") or "")) for row in anchors]
    for index in range(max((len(modes) for modes in relationship_modes), default=0)):
        for anchor, modes in zip(anchors, relationship_modes, strict=True):
            if index < len(modes):
                plans.append((anchor, modes[index]))
    for anchor, mode in plans:
        if len(evidence) >= bound:
            truncated = True
            break
        symbol = str(anchor.get("qualified_name") or anchor.get("name") or "")
        if not symbol:
            continue
        selected_file = str(anchor.get("file_path") or "")
        try:
            result = service.query(
                mode,
                symbol,
                limit=bound,
                file_path=selected_file or None,
                min_confidence=min_confidence,
            )
            query_count += 1
        except Exception as exc:  # noqa: BLE001 - error remains explicit and bounded
            errors.append(f"{mode}:{symbol}:{type(exc).__name__}")
            continue
        added_for_relationship = 0
        for source in result.get("evidence", ()):
            row = dict(source)
            row["context_role"] = "relationship"
            row["query_mode"] = mode
            row["query_token"] = anchor.get("query_token")
            row["anchor_symbol"] = symbol
            identity = _identity(row)
            if identity in identities:
                continue
            identities.add(identity)
            evidence.append(row)
            added_for_relationship += 1
            if len(evidence) >= bound:
                truncated = True
                break
            if added_for_relationship >= 2:
                truncated = True
                break

    return {
        "schema": "gt.graph_context_composition.v1",
        "task_tokens": list(tokens),
        "anchor_count": len(anchors),
        "query_count": query_count,
        "evidence": evidence,
        "count": len(evidence),
        "truncated": truncated,
        "query_errors": errors,
        "min_confidence": max(0.0, min(float(min_confidence), 1.0)),
    }


__all__ = ["compose_repository_context", "task_tokens"]
