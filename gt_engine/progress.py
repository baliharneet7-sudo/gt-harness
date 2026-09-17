"""Deterministic progress-state tracking for early stall detection."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProgressTransition:
    prior: str
    current: str
    reason: str
    streak: int
    signature: str


class ProgressLedger:
    """Track whether observations add information or mutate task state."""

    def __init__(self, *, stall_threshold: int = 3) -> None:
        self.state = "PROGRESS"
        self.stall_threshold = max(2, int(stall_threshold))
        self._last_signature = ""
        self._repeat_streak = 0
        self._signature_counts: dict[str, int] = {}

    def observe(
        self,
        signature: str,
        *,
        information_gain: bool,
        changed: bool,
        is_error: bool,
        contradictory: bool | None = None,
    ) -> ProgressTransition | None:
        prior = self.state
        if changed:
            self._signature_counts.clear()
            self._repeat_streak = 0
            self._last_signature = signature
            self.state = "RECOVERED" if prior in {
                "STALLED", "CONTRADICTED", "BUDGET_RISK"
            } else "PROGRESS"
            reason = "material_state_change"
        elif information_gain or not signature:
            if signature:
                self._signature_counts[signature] = 1
            self._repeat_streak = 0
            self._last_signature = signature
            self.state = "RECOVERED" if prior in {
                "STALLED", "CONTRADICTED", "BUDGET_RISK"
            } else "PROGRESS"
            reason = "new_information"
        else:
            count = self._signature_counts.get(signature, 1) + 1
            self._signature_counts[signature] = count
            self._last_signature = signature
            self._repeat_streak = count
            if count >= self.stall_threshold:
                source_contradiction = (
                    bool(is_error)
                    if contradictory is None
                    else bool(contradictory)
                )
                self.state = (
                    "CONTRADICTED" if source_contradiction else "STALLED"
                )
                reason = (
                    "repeated_failure_without_information"
                    if source_contradiction
                    else "repeated_action_without_information"
                )
            else:
                self.state = "PROGRESS"
                reason = "no_new_information"
        if self.state == prior and self.state == "PROGRESS":
            return None
        return ProgressTransition(
            prior=prior,
            current=self.state,
            reason=reason,
            streak=self._repeat_streak,
            signature=signature,
        )

    def budget_risk(
        self,
        *,
        iteration: int,
        limit: int,
        unresolved: bool = False,
    ) -> ProgressTransition | None:
        if limit <= 0 or iteration < max(1, int(limit * 0.8)):
            return None
        if self.state == "BUDGET_RISK":
            return None
        if (
            unresolved
            or self.state in {"STALLED", "CONTRADICTED"}
        ):
            prior = self.state
            self.state = "BUDGET_RISK"
            return ProgressTransition(
                prior=prior,
                current=self.state,
                reason=(
                    "unresolved_contract_near_iteration_limit"
                    if unresolved
                    else "unresolved_stall_near_iteration_limit"
                ),
                streak=self._repeat_streak,
                signature=self._last_signature,
            )
        return None
