"""Stable logical identities for graph snapshots and semantic symbols."""

from __future__ import annotations

import hashlib


def _frame(*values: str) -> bytes:
    payload = bytearray()
    for value in values:
        encoded = str(value or "").encode("utf-8", "surrogatepass")
        payload.extend(len(encoded).to_bytes(8, "big"))
        payload.extend(encoded)
    return bytes(payload)


def stable_symbol_id(
    *,
    language: str,
    file_path: str,
    qualified_name: str,
    kind: str,
    signature: str,
) -> str:
    """Return an insertion-order-independent symbol identity.

    The path remains part of the identity until an authoritative compiler/LSP
    package coordinate is available.  Database row IDs and source line
    locations are deliberately excluded.
    """

    normalized_path = str(file_path or "").replace("\\", "/").lstrip("./")
    digest = hashlib.sha256(
        _frame(
            str(language or "").lower(),
            normalized_path,
            str(qualified_name or ""),
            str(kind or ""),
            " ".join(str(signature or "").split()),
        )
    ).hexdigest()
    return "gt-symbol-" + digest


__all__ = ["stable_symbol_id"]
