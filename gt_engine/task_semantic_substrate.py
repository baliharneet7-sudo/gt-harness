"""Graph-independent, deterministic task evidence for every provider call.

Repository intelligence remains graph-backed and keeps its existing
applicability boundary.  This substrate is narrower: it projects facts already
derived from the task instruction and bounded workspace snapshot so binary,
data, media, and greenfield tasks are not blind before source exists.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from gt_engine.decisive_derivation import (
    DecisiveDerivation,
    DecisiveFact,
    DecisiveKind,
    DecisiveStatus,
)
from gt_engine.hybrid_retrieval import EvidenceOrigin


class SemanticEvidenceClass(StrEnum):
    STRUCTURAL = "structural"
    OBLIGATION = "obligation"
    VERIFICATION = "verification"
    DIAGNOSTIC = "diagnostic"


_EVIDENCE_CLASS = {
    DecisiveKind.SECRET_LOCATION: SemanticEvidenceClass.DIAGNOSTIC,
    DecisiveKind.BINARY_FORMAT: SemanticEvidenceClass.STRUCTURAL,
    DecisiveKind.REQUIRED_CHECK: SemanticEvidenceClass.VERIFICATION,
    DecisiveKind.PROJECT_CHECK: SemanticEvidenceClass.VERIFICATION,
    DecisiveKind.DELIVERABLE_STATE: SemanticEvidenceClass.OBLIGATION,
    DecisiveKind.REPOSITORY_ANCHOR: SemanticEvidenceClass.STRUCTURAL,
}


@dataclass(frozen=True, slots=True)
class TaskSemanticFrame:
    rendered_text: str
    claim_ids: tuple[str, ...]
    fact_ids: tuple[str, ...]
    source_revision: str
    evidence_action: int
    eligible_call: int
    fact_metadata: tuple[dict[str, Any], ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _provider_text(messages: Iterable[Mapping[str, Any]]) -> str:
    return "\n".join(str(message.get("content") or "") for message in messages)


def _render_fact(fact: DecisiveFact) -> str:
    evidence_class = _EVIDENCE_CLASS[fact.kind]
    return f"- [{evidence_class.value}] {fact.gap_text.strip()}"


def _represented_by_provider_view(fact: DecisiveFact, provider_view: str) -> bool:
    if fact.gap_text in provider_view:
        return True
    if fact.kind in {DecisiveKind.REQUIRED_CHECK, DecisiveKind.PROJECT_CHECK}:
        _prefix, separator, command = fact.gap_text.partition(": ")
        return bool(separator and command.strip() and command.strip() in provider_view)
    return False


@dataclass(slots=True)
class TaskSemanticSubstrate:
    """One-shot, revision-aware delivery over deterministic derived facts."""

    derivation: DecisiveDerivation
    evidence_action: int
    eligible_call: int
    delivered_claim_ids: set[str] = field(default_factory=set)
    represented_claim_ids: set[str] = field(default_factory=set)
    compilation_receipts: list[dict[str, Any]] = field(default_factory=list)
    delivery_receipts: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_derivation(
        cls,
        derivation: DecisiveDerivation,
        *,
        evidence_action: int,
        eligible_call: int,
    ) -> TaskSemanticSubstrate:
        return cls(
            derivation=derivation,
            evidence_action=max(0, int(evidence_action)),
            eligible_call=max(1, int(eligible_call)),
        )

    def refresh(
        self,
        derivation: DecisiveDerivation,
        *,
        evidence_action: int,
        eligible_call: int,
    ) -> None:
        self.derivation = derivation
        self.evidence_action = max(0, int(evidence_action))
        self.eligible_call = max(1, int(eligible_call))

    def compile_context(
        self,
        *,
        current_source_revision: str,
        current_call: int,
        provider_messages: Iterable[Mapping[str, Any]],
        max_chars: int,
        max_facts: int = 6,
    ) -> TaskSemanticFrame | None:
        call = max(1, int(current_call))
        provider_view = _provider_text(provider_messages)
        accounting: list[dict[str, Any]] = []
        candidates: list[tuple[DecisiveFact, str]] = []
        for fact in self.derivation.facts:
            disposition = "selected_candidate"
            origin = EvidenceOrigin(str(fact.origin))
            if origin in {
                EvidenceOrigin.MODEL_AUTHORED,
                EvidenceOrigin.GENERATED_ARTIFACT,
            }:
                # The model already created this artifact.  Re-describing it as
                # novel task/repository evidence creates a self-reinforcing
                # context loop.  Keep the fact available to the host controller
                # but never grant it provider-delivery authority.
                disposition = "model_authored_controller_only"
            elif fact.claim_id in self.delivered_claim_ids:
                disposition = "already_delivered"
            elif fact.claim_id in self.represented_claim_ids or _represented_by_provider_view(
                fact, provider_view
            ):
                disposition = "represented_message"
                self.represented_claim_ids.add(fact.claim_id)
            elif fact.source_revision and fact.source_revision != current_source_revision:
                disposition = "stale_source_revision"
            elif self.eligible_call < call:
                disposition = "expired_window"
            elif self.eligible_call > call:
                disposition = "future_eligible_call"
            else:
                candidates.append((fact, _render_fact(fact)))
            accounting.append(
                {
                    "fact_id": fact.fact_id,
                    "claim_id": fact.claim_id,
                    "kind": fact.kind.value,
                    "disposition": disposition,
                }
            )

        header = "Current task evidence:"
        selected: list[tuple[DecisiveFact, str]] = []
        used = len(header)
        limit = max(0, int(max_chars))
        for fact, rendered in candidates[: max(0, int(max_facts))]:
            required = 1 + len(rendered)
            if used + required > limit:
                for row in accounting:
                    if row["fact_id"] == fact.fact_id:
                        row["disposition"] = "context_budget"
                continue
            selected.append((fact, rendered))
            used += required
            for row in accounting:
                if row["fact_id"] == fact.fact_id:
                    row["disposition"] = "selected"

        receipt = {
            "call": call,
            "source_revision": current_source_revision,
            "derivation_status": self.derivation.status.value,
            "candidate_count": len(self.derivation.facts),
            "accounted_count": len(accounting),
            "selected_count": len(selected),
            "accounting": accounting,
        }
        self.compilation_receipts.append(receipt)
        if not selected:
            return None
        facts = tuple(item[0] for item in selected)
        return TaskSemanticFrame(
            rendered_text="\n".join((header, *(item[1] for item in selected))),
            claim_ids=tuple(fact.claim_id for fact in facts),
            fact_ids=tuple(fact.fact_id for fact in facts),
            source_revision=current_source_revision,
            evidence_action=self.evidence_action,
            eligible_call=self.eligible_call,
            fact_metadata=tuple(
                {
                    **fact.as_dict(),
                    "evidence_class": _EVIDENCE_CLASS[fact.kind].value,
                }
                for fact in facts
            ),
        )

    def mark_dispatched(
        self,
        frame: TaskSemanticFrame,
        *,
        call: int | None = None,
        request_payload_sha256: str = "",
        provider_messages_sha256: str = "",
        message_index: int | None = None,
        completed_action_count_before_call: int | None = None,
    ) -> None:
        self.delivered_claim_ids.update(frame.claim_ids)
        dispatched_call = frame.eligible_call if call is None else max(1, int(call))
        completed_actions = (
            frame.evidence_action
            if completed_action_count_before_call is None
            else max(0, int(completed_action_count_before_call))
        )
        self.delivery_receipts.append(
            {
                **frame.as_dict(),
                "call": dispatched_call,
                "dispatched_call": dispatched_call,
                "first_eligible_call": frame.eligible_call,
                "delivered_before_call": dispatched_call,
                "delivered_before_model_query": True,
                "completed_action_count_before_call": completed_actions,
                "not_predictive": frame.evidence_action <= completed_actions,
                "one_step_late": dispatched_call != frame.eligible_call,
                "request_payload_sha256": request_payload_sha256,
                "provider_messages_sha256": provider_messages_sha256,
                "message_index": message_index,
                "provider_message_indices": (
                    [] if message_index is None else [message_index]
                ),
                "chars": len(frame.rendered_text),
                "claim_metadata": list(frame.fact_metadata),
            }
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "gt.task_semantic_substrate.v1",
            "status": (
                "active"
                if self.derivation.status is DecisiveStatus.DERIVED
                else "abstained"
            ),
            "derivation": self.derivation.as_dict(),
            "delivered_claim_count": len(self.delivered_claim_ids),
            "represented_claim_count": len(self.represented_claim_ids),
            "compilations": list(self.compilation_receipts),
            "deliveries": list(self.delivery_receipts),
        }


__all__ = [
    "SemanticEvidenceClass",
    "TaskSemanticFrame",
    "TaskSemanticSubstrate",
]
