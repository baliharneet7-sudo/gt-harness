"""An LSP no-op must say WHY nothing was promoted.

The capability row reports lsp_promotion DEGRADED with evidence
`terminal_no_op:nothing_promotable` whenever the promoter found nothing to
promote. That single string covers two opposite situations:

  * extract-elf is a C/ELF binary task. No LSP-serviceable language is present,
    so promoting nothing is the CORRECT outcome and DEGRADED overstates it.
  * A Python task where promotion should have happened and did not is a real
    defect, and reads identically.

The promotion receipt (gt.lsp_promotion_task.v1) already records
languages_promotable, languages_attempted and languages_unavailable. Reading
them separates the cases. gt_session assigns the capability state and is a
pinned source object, so this does not change any verdict - it annotates the
report so a reader is not left guessing.
"""
from __future__ import annotations

from scripts.lsp_no_op import classify_lsp_no_op


def test_no_serviceable_language_is_expected_not_a_defect():
    """extract-elf: a C/ELF task with nothing an LSP could promote."""
    receipt = {
        "status": "no_op", "reason": "nothing_to_promote",
        "languages_promotable": [], "languages_attempted": [],
        "languages_unavailable": [],
    }
    verdict, detail = classify_lsp_no_op(receipt)
    assert verdict == "EXPECTED"
    assert "no LSP-serviceable language" in detail


def test_promotable_language_that_never_completed_is_a_defect():
    """Something could have been promoted and was not."""
    receipt = {
        "status": "no_op", "reason": "nothing_to_promote",
        "languages_promotable": ["python"], "languages_attempted": [],
        "languages_unavailable": [],
    }
    verdict, detail = classify_lsp_no_op(receipt)
    assert verdict == "UNEXPECTED"
    assert "python" in detail


def test_unavailable_toolchain_is_a_defect_and_names_the_language():
    """A missing language server is an environment fault, not a quiet task."""
    receipt = {
        "status": "no_op", "reason": "nothing_to_promote",
        "languages_promotable": [], "languages_attempted": [],
        "languages_unavailable": ["go"],
    }
    verdict, detail = classify_lsp_no_op(receipt)
    assert verdict == "UNEXPECTED"
    assert "go" in detail


def test_attempted_but_incomplete_is_a_defect():
    receipt = {
        "status": "no_op", "reason": "nothing_to_promote",
        "languages_promotable": ["rust"], "languages_attempted": ["rust"],
        "languages_completed": [], "languages_unavailable": [],
    }
    verdict, _ = classify_lsp_no_op(receipt)
    assert verdict == "UNEXPECTED"


def test_a_non_no_op_receipt_is_not_classified():
    assert classify_lsp_no_op({"status": "succeeded"})[0] == "NOT_APPLICABLE"


def test_an_unreadable_receipt_is_never_excused():
    """Absence of evidence must not read as evidence of correctness."""
    for bad in ({}, None, {"status": "no_op"}):
        verdict, detail = classify_lsp_no_op(bad)
        assert verdict in {"UNKNOWN", "NOT_APPLICABLE"}
        assert verdict != "EXPECTED", bad
