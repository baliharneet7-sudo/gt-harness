"""GroundTruth engine layer for nano-harness.

One entry point: :func:`create_bridge`. Returns a live :class:`~gt_engine.bridge.GTBridge`
when ``gt_root`` names an indexable code repository and GT is not explicitly
disabled, else ``None``. A ``None`` bridge means every nano code path behaves
byte-identically to stock nano-harness (GT-off byte identity).
"""
from __future__ import annotations

__all__ = ["create_bridge"]


def create_bridge(gt_root: str | None):
    """Build the GT bridge for a task rooted at ``gt_root``.

    Returns None (GT dormant) when:
    - gt_root is falsy,
    - GT_GATEWAY is explicitly set to an off value in the environment,
    - groundtruth is not importable,
    - gt_root is not a code repository / indexing fails.

    Never raises: GT failure must never break the harness.
    """
    if not gt_root:
        return None
    try:
        import os

        # An EXPLICIT off value is a user kill-switch; unset means "apply defaults".
        explicit = os.environ.get("GT_GATEWAY")
        if explicit is not None and explicit.strip().lower() in (
                "", "0", "false", "no", "off"):
            return None

        from gt_engine.bridge import GTBridge, apply_profile_env
        from gt_engine.indexer import ensure_index

        apply_profile_env()
        graph_db = ensure_index(gt_root)
        if graph_db is None:
            return None
        return GTBridge(repo_root=gt_root, graph_db=graph_db)
    except Exception:  # noqa: BLE001 - GT must never break the harness
        return None
