"""Deterministic utility admission for one-dose GT candidates."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_SEVERITY = {
    "covering_verdict": 1.0,
    "syntax_result": 1.0,
    "submit_refusal": 1.0,
    "recovery": 0.95,
    "signature_delta": 0.85,
    "patch_delta": 0.85,
    "localization": 0.75,
    "ranked_localization": 0.75,
    "caller_contract": 0.65,
    "caller_contract_view": 0.65,
    "def_partition": 0.55,
    "def_ref_partition": 0.55,
    "missing_role:registration": 0.72,
    "missing_role:implementation": 0.68,
    "new_file_destination": 0.60,
}


@dataclass(frozen=True)
class UtilityScore:
    candidate: Any
    evidence_type: str
    severity: float
    evidence_strength: float
    actionability: float
    token_cost: float
    score: float


def score_candidate(candidate: Any, rendered: str) -> UtilityScore:
    kind = str(getattr(candidate, "evidence_type", "") or "")
    severity = _SEVERITY.get(kind, 0.5)
    evidence_strength = max(
        0.0, min(1.0, float(getattr(candidate, "confidence", 0.5) or 0.5))
    )
    target = str(getattr(candidate, "target", "") or "")
    provenance = tuple(getattr(candidate, "provenance", ()) or ())
    actionability = 1.0 if target or provenance else 0.7
    token_cost = min(0.4, len(rendered or "") / 10_000)
    # Severity expresses the deterministic SDLC priority and must remain the
    # dominant term. Confidence modulates within that priority; it must not
    # let a high-confidence navigation hint displace a more timely contract or
    # localization intervention. Long payloads still lose enough utility to
    # permit abstention.
    score = (
        severity
        * (0.6 + 0.4 * evidence_strength)
        * actionability
        - token_cost
    )
    return UtilityScore(
        candidate,
        kind,
        severity,
        evidence_strength,
        actionability,
        token_cost,
        score,
    )


def choose_candidate(
    candidates: list[Any],
    rendered_by_id: dict[int, str],
    *,
    minimum: float = 0.08,
) -> tuple[Any | None, tuple[UtilityScore, ...]]:
    scores = tuple(
        score_candidate(item, rendered_by_id.get(id(item), ""))
        for item in candidates
    )
    if not scores:
        return None, ()
    winner = max(
        scores,
        key=lambda item: (item.score, item.evidence_type),
    )
    return (winner.candidate if winner.score >= minimum else None), scores
