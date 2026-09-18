"""Say why an LSP promotion promoted nothing.

`gt_session` reports the capability row as DEGRADED with evidence
`terminal_no_op:nothing_promotable` whenever the promoter finds nothing to
promote. That one string covers two opposite situations, and reporting them
identically makes a correct run look broken:

  * extract-elf is a C/ELF binary task. No LSP-serviceable language is present,
    so promoting nothing is right, and DEGRADED overstates it. Run 35293191813
    reported exactly this.
  * A task whose language IS serviceable, where promotion should have happened
    and did not, is a real defect and currently reads the same way.

The promotion receipt (`gt.lsp_promotion_task.v1`) already records the three
lists that separate them. `gt_session` is a pinned source object, so nothing
here changes a state or a verdict: it annotates the report so the reader is
not left guessing which case they are looking at.

Absence of evidence is never excused. A receipt that cannot be read, or that
omits the lists, returns UNKNOWN rather than EXPECTED.
"""
from __future__ import annotations

from typing import Any

EXPECTED = "EXPECTED"
UNEXPECTED = "UNEXPECTED"
UNKNOWN = "UNKNOWN"
NOT_APPLICABLE = "NOT_APPLICABLE"

_LISTS = ("languages_promotable", "languages_attempted", "languages_unavailable")


def classify_lsp_no_op(receipt: Any) -> tuple[str, str]:
    """Return (verdict, human detail) for one promotion receipt."""
    if not isinstance(receipt, dict):
        return UNKNOWN, "no readable promotion receipt"
    if str(receipt.get("status") or "") != "no_op":
        return NOT_APPLICABLE, f"status={receipt.get('status')!r}"
    if not all(key in receipt for key in _LISTS):
        missing = ", ".join(k for k in _LISTS if k not in receipt)
        return UNKNOWN, f"receipt omits {missing}"

    promotable = [str(x) for x in (receipt.get("languages_promotable") or [])]
    attempted = [str(x) for x in (receipt.get("languages_attempted") or [])]
    completed = [str(x) for x in (receipt.get("languages_completed") or [])]
    unavailable = [str(x) for x in (receipt.get("languages_unavailable") or [])]

    if unavailable:
        return UNEXPECTED, (
            "language server unavailable for: " + ", ".join(sorted(unavailable))
        )
    if promotable:
        stalled = sorted(set(promotable) - set(completed))
        return UNEXPECTED, (
            "promotable but not completed: " + ", ".join(stalled or promotable)
            + (f" (attempted: {', '.join(attempted)})" if attempted else "")
        )
    return EXPECTED, (
        "no LSP-serviceable language in this workspace; promoting nothing is "
        "the correct outcome for this task shape"
    )
