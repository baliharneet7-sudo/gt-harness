"""Join deterministic GT evidence to the provider decision that followed it.

The chain is intentionally an audit record, not a claim about hidden model
reasoning.  It joins only fields that the host actually records: evidence
identity, provider request hashes/message indices, visible response metadata,
the next observed action, and postflight state.  Missing observations are
represented as ``UNKNOWN``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def _sha(value: Any) -> str:
    body = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _response_for_call(trajectory: dict[str, Any], call: int) -> dict[str, Any] | None:
    messages = trajectory.get("messages") or []
    seen = 0
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        seen += 1
        if seen != call:
            continue
        return {
            "content": message.get("content"),
            "reasoning_content": message.get("reasoning_content"),
            "actions": list((message.get("extra") or {}).get("actions") or []),
            "visible": True,
        }
    return None


def build_intervention_chain(
    receipt: dict[str, Any],
    trajectory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a replayable, evidence-backed intervention chain."""

    contexts = {
        int(row["call"]): row
        for row in receipt.get("model_call_contexts") or []
        if isinstance(row, dict) and str(row.get("call") or "").isdigit()
    }
    trajectory = trajectory or {}
    rows: list[dict[str, Any]] = []
    surfaces = (
        ("preemptive_retrieval", receipt.get("preemptive_retrieval") or {}),
        ("repository_context", receipt.get("repository_context") or {}),
        ("semantic_evidence", receipt.get("semantic_evidence") or {}),
        ("relational_context", receipt.get("relational_context") or {}),
        ("progress", receipt.get("progress") or {}),
        ("interventions", {"deliveries": receipt.get("interventions") or []}),
    )
    for surface, payload in surfaces:
        if not isinstance(payload, dict):
            continue
        deliveries = payload.get("deliveries") or payload.get("interventions") or []
        for delivery in deliveries:
            if not isinstance(delivery, dict):
                continue
            call = int(delivery.get("call") or delivery.get("provider_call") or 0)
            context = contexts.get(call, {})
            response = _response_for_call(trajectory, call)
            next_actions = (response or {}).get("actions") or []
            rows.append(
                {
                    "surface": surface,
                    "delivery_id": str(
                        delivery.get("delivery_id")
                        or delivery.get("frame_id")
                        or delivery.get("effect_id")
                        or _sha(delivery)[:16]
                    ),
                    "evidence": {
                        "claim_ids": list(delivery.get("claim_ids") or delivery.get("fact_ids") or []),
                        "source_revision": delivery.get("source_revision"),
                        "evidence_action": delivery.get("evidence_action"),
                        "eligible_call": delivery.get("eligible_call"),
                        "provenance": list(delivery.get("provenance") or []),
                    },
                    "provider": {
                        "call": call,
                        "request_payload_sha256": context.get("request_payload_sha256"),
                        "provider_messages_sha256": context.get("provider_messages_sha256"),
                        "changed_message_indices": list(context.get("changed_message_indices") or []),
                        "delivery_status": context.get("dispatch_status", "UNKNOWN"),
                    },
                    "model_observation": {
                        "visible_response": bool(response),
                        "content_sha256": _sha(response.get("content")) if response else None,
                        "reasoning_observed": bool(response and response.get("reasoning_content")),
                        "next_actions": next_actions,
                    },
                    "postflight": {
                        "action_cycle": context.get("action_cycle"),
                        "postflight": context.get("postflight"),
                        "source_revision_after": context.get("source_revision_after"),
                    },
                    "causal_status": "UNKNOWN",
                }
            )
    rows.sort(key=lambda row: (int(row["provider"].get("call") or 0), row["surface"], row["delivery_id"]))
    return {
        "schema": "gt.intervention_chain.v1",
        "claim_policy": "visible_host_observations_only",
        "hidden_reasoning_inferred": False,
        "rows": rows,
        "counts": {
            "rows": len(rows),
            "visible_model_observations": sum(bool(row["model_observation"]["visible_response"]) for row in rows),
            "unknown_causal_status": sum(row["causal_status"] == "UNKNOWN" for row in rows),
        },
    }


def write_intervention_chain(
    receipt_path: str | Path,
    *,
    trajectory_path: str | Path | None = None,
) -> dict[str, Any]:
    receipt_path = Path(receipt_path)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    trajectory = (
        json.loads(Path(trajectory_path).read_text(encoding="utf-8"))
        if trajectory_path is not None and Path(trajectory_path).exists()
        else None
    )
    chain = build_intervention_chain(receipt, trajectory)
    output = receipt_path.with_name("intervention_chain.json")
    output.write_text(json.dumps(chain, indent=2), encoding="utf-8")
    return {
        "path": output.name,
        "schema": chain["schema"],
        "hidden_reasoning_inferred": chain["hidden_reasoning_inferred"],
        "rows": chain["counts"]["rows"],
        **chain["counts"],
    }
