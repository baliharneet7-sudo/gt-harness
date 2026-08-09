"""Deterministic progress-state tracking for early stall detection."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass


@dataclass(frozen=True)
class ProgressTransition:
    prior: str
    current: str
    reason: str
    streak: int
    signature: str


@dataclass(frozen=True, slots=True)
class StallAggregateFact:
    """Bounded deterministic description of an observed no-progress cycle."""

    fact_id: str
    state: str
    repeated_operation: str
    concrete_targets: tuple[str, ...]
    repeat_count: int
    last_returncode: int | None
    timeout_observed: bool
    source_revision: str
    remaining_calls: int
    remaining_seconds: float | None
    unresolved_anchors: tuple[str, ...]
    evidence_action: int
    eligible_call: int

    @staticmethod
    def _bounded(values: tuple[str, ...], *, count: int = 2, chars: int = 72) -> tuple[str, ...]:
        return tuple(" ".join(str(value).split())[:chars] for value in values[:count] if value)

    @classmethod
    def create(
        cls,
        *,
        state: str,
        repeated_operation: str,
        concrete_targets: tuple[str, ...],
        repeat_count: int,
        last_returncode: int | None,
        timeout_observed: bool,
        source_revision: str,
        remaining_calls: int,
        remaining_seconds: float | None,
        unresolved_anchors: tuple[str, ...],
        evidence_action: int,
        eligible_call: int,
    ) -> StallAggregateFact:
        targets = cls._bounded(concrete_targets)
        anchors = cls._bounded(unresolved_anchors)
        material = json.dumps(
            [
                state,
                repeated_operation,
                targets,
                repeat_count,
                last_returncode,
                timeout_observed,
                source_revision,
                remaining_calls,
                anchors,
                evidence_action,
                eligible_call,
            ],
            separators=(",", ":"),
        )
        return cls(
            fact_id="stall-" + hashlib.sha256(material.encode()).hexdigest()[:20],
            state=str(state),
            repeated_operation=" ".join(str(repeated_operation).split())[:48],
            concrete_targets=targets,
            repeat_count=max(1, int(repeat_count)),
            last_returncode=last_returncode,
            timeout_observed=bool(timeout_observed),
            source_revision=str(source_revision),
            remaining_calls=max(0, int(remaining_calls)),
            remaining_seconds=(
                None if remaining_seconds is None else max(0.0, float(remaining_seconds))
            ),
            unresolved_anchors=anchors,
            evidence_action=max(0, int(evidence_action)),
            eligible_call=max(1, int(eligible_call)),
        )

    def render(self) -> str:
        pieces = [
            f"Execution state {self.state}",
            f"operation={self.repeated_operation or 'unknown'} repeated={self.repeat_count}",
        ]
        if self.concrete_targets:
            pieces.append("targets=" + ",".join(self.concrete_targets))
        if self.last_returncode is not None:
            pieces.append(f"last_rc={self.last_returncode}")
        if self.timeout_observed:
            pieces.append("timeout_observed=true")
        if self.unresolved_anchors:
            pieces.append("unresolved=" + ",".join(self.unresolved_anchors))
        pieces.append(f"remaining_calls={self.remaining_calls}")
        if self.remaining_seconds is not None:
            pieces.append(f"remaining_seconds={int(self.remaining_seconds)}")
        rendered = "; ".join(pieces) + "."
        # Construction bounds make this exceptional; abstain rather than
        # truncate a source-backed fact into a misleading fragment.
        return rendered if len(rendered) <= 320 else ""


class ProgressLedger:
    """Track whether observations add information or mutate task state."""

    def __init__(
        self,
        *,
        stall_threshold: int = 3,
        cycle_threshold: int | None = None,
    ) -> None:
        self.state = "PROGRESS"
        self.stall_threshold = max(2, int(stall_threshold))
        self.cycle_threshold = max(
            self.stall_threshold,
            int(cycle_threshold if cycle_threshold is not None else stall_threshold),
        )
        self._last_signature = ""
        self._repeat_streak = 0
        self._signature_counts: dict[str, int] = {}
        self._history: list[str] = []

    def observe(
        self,
        signature: str,
        *,
        information_gain: bool,
        changed: bool,
        semantic_gain: bool | None = None,
        is_error: bool,
        contradictory: bool | None = None,
    ) -> ProgressTransition | None:
        prior = self.state
        # ``changed`` describes workspace activity and is still useful to the
        # host's stale-batch safety barrier.  It is not proof that the task
        # moved forward: fixture resets and scratch edits are common in long
        # trajectories.  Callers may therefore provide the narrower semantic
        # signal explicitly; legacy callers retain the old behavior.
        if semantic_gain is None:
            semantic_gain = changed
        # Budget risk is a task-state condition, not an observation-novelty
        # condition.  A fresh scratch result or unvalidated patch must not
        # clear it; only a proven semantic gain can recover the controller.
        if prior == "BUDGET_RISK" and not semantic_gain:
            if signature:
                self._signature_counts[signature] = (
                    self._signature_counts.get(signature, 0) + 1
                )
                self._history.append(signature)
                self._history = self._history[-self.cycle_threshold :]
                self._repeat_streak = (
                    self._repeat_streak + 1 if signature == self._last_signature else 1
                )
                self._last_signature = signature
            return None
        if semantic_gain:
            self._signature_counts.clear()
            self._history.clear()
            self._repeat_streak = 0
            self._last_signature = signature
            self.state = "RECOVERED" if prior in {
                "STALLED", "CONTRADICTED", "BUDGET_RISK"
            } else "PROGRESS"
            reason = "material_state_change"
        elif information_gain or not signature:
            if signature:
                self._signature_counts[signature] = self._signature_counts.get(signature, 0) + 1
                self._history.append(signature)
                self._history = self._history[-self.cycle_threshold :]
            self._repeat_streak = 1 if signature else 0
            self._last_signature = signature
            self.state = "RECOVERED" if prior in {
                "STALLED", "CONTRADICTED", "BUDGET_RISK"
            } else "PROGRESS"
            reason = "new_information"
        else:
            count = self._signature_counts.get(signature, 1) + 1
            self._signature_counts[signature] = count
            self._history.append(signature)
            self._history = self._history[-self.cycle_threshold :]
            self._repeat_streak = (
                self._repeat_streak + 1 if signature == self._last_signature else 1
            )
            self._last_signature = signature
            cyclic = bool(
                len(self._history) >= self.cycle_threshold
                and len(set(self._history)) > 1
                and any(
                    all(
                        self._history[index] == self._history[index % period]
                        for index in range(len(self._history))
                    )
                    for period in range(2, min(4, len(self._history)))
                )
            )
            repeated = self._repeat_streak >= self.stall_threshold
            nonconsecutive = count >= self.cycle_threshold
            if repeated or cyclic or nonconsecutive:
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
                    else (
                        "cyclic_actions_without_information"
                        if cyclic and not repeated
                        else "repeated_action_without_information"
                    )
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
