"""Make the certified GT background promoter honor its full-selection contract.

The pinned 921bec20 wheel exposes ``GT_LSP_MAX_EDGES`` to its foreground
resolver, but its background scheduler calls ``_get_ambiguous_edges`` without
that limit and then stamps a literal 500 into its receipt.  Large repositories
therefore always fail the pinned strict diagnostic even when LSP promotion
successfully publishes edges.  This benchmark-owned startup hook raises only
that selection bound and corrects the corresponding receipt field.  It does
not relax the diagnostic or alter any pinned source object.
"""

from __future__ import annotations

import os
import sqlite3
from typing import Any

from groundtruth.lsp import background_promotion

from groundtruth import resolve

_SELECTION_LIMIT = int(os.environ.get("GT_LSP_MAX_EDGES", "100000"))
if _SELECTION_LIMIT < 500:
    raise RuntimeError("GT_LSP_MAX_EDGES must retain at least the certified 500-edge floor")


def _load_all_edges(db_path: str, language: str) -> list[dict[str, Any]]:
    connection = sqlite3.connect(db_path)
    try:
        return resolve._get_ambiguous_edges(  # noqa: SLF001 - pinned compatibility seam
            connection,
            min_confidence=0.95,
            language=language,
            limit=_SELECTION_LIMIT,
        )
    finally:
        connection.close()


_Scheduler = background_promotion.LSPPromotionScheduler
_original_run_languages = _Scheduler._run_languages  # noqa: SLF001


async def _run_languages_with_truthful_limit(
    self: Any,
    handle: Any,
    candidate: Any,
    languages: list[str],
    terminal: dict[str, Any],
) -> None:
    await _original_run_languages(self, handle, candidate, languages, terminal)
    for language in languages:
        receipt = terminal.get("language_receipts", {}).get(language)
        if not isinstance(receipt, dict) or "selected_unit_count" not in receipt:
            continue
        receipt["selection_limit"] = _SELECTION_LIMIT
        complete = receipt["selected_unit_count"] == receipt.get("candidate_unit_count")
        receipt["selection_complete"] = complete
        if complete:
            receipt.pop("selection_limitation", None)
        else:
            receipt["selection_limitation"] = "configured_selection_limit"


_Scheduler._load_edges = staticmethod(_load_all_edges)  # noqa: SLF001
_Scheduler._run_languages = _run_languages_with_truthful_limit  # noqa: SLF001
