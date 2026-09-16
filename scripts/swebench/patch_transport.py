"""Lossless normalization at the JSON-to-unified-diff transport boundary."""

from __future__ import annotations


def normalize_patch_transport(patch: str) -> str:
    """Preserve patch bytes while supplying the required record terminator."""
    if not patch:
        return ""
    return patch if patch.endswith(("\n", "\r")) else patch + "\n"
