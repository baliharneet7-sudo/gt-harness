"""Join every canonical GT delivery to its next observable model decision.

This artifact is deliberately observational.  It proves which evidence was in
which exact provider request and records the response/action/postflight that
followed.  It never promotes visible reasoning or action alignment into a
causal claim; causality requires a matched counterfactual arm.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from gt_engine.delivery_audit import collect_provider_deliveries


def _sha(value: Any) -> str:
    body = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _response_for_call(trajectory: dict[str, Any], call: int) -> dict[str, Any] | None:
    seen = 0
    for message in trajectory.get("messages") or ():
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        seen += 1
        if seen == call:
            return {
                "content": message.get("content"),
                "reasoning_content": message.get("reasoning_content"),
                "actions": list((message.get("extra") or {}).get("actions") or ()),
                "visible": True,
                "source": "trajectory",
            }
    return None


def _replay_responses(replay_bundle: dict[str, Any] | None) -> dict[int, dict[str, Any]]:
    responses: dict[int, dict[str, Any]] = {}
    for row in (replay_bundle or {}).get("calls") or ():
        if not isinstance(row, dict) or not isinstance(row.get("call"), int):
            continue
        response = row.get("response")
        if not isinstance(response, dict):
            continue
        responses[int(row["call"])] = {
            "content": response.get("content"),
            "reasoning_content": response.get("reasoning_content"),
            "actions": list((response.get("extra") or {}).get("actions") or ()),
            "visible": True,
            "source": "verified_replay_bundle",
            "response_blob_sha256": row.get("response_blob_sha256"),
        }
    return responses


def _action_cycles(receipt: dict[str, Any]) -> dict[int, list[dict[str, Any]]]:
    by_call: dict[int, list[dict[str, Any]]] = {}
    for row in (receipt.get("features") or {}).get("action_cycles") or ():
        if not isinstance(row, dict):
            continue
        proposed = row.get("proposed") or {}
        call = proposed.get("model_call")
        if isinstance(call, int) and not isinstance(call, bool) and call > 0:
            by_call.setdefault(call, []).append(row)
    return by_call


def _uptake(
    *,
    response: dict[str, Any] | None,
    cycles: list[dict[str, Any]],
    claims: list[str],
) -> dict[str, Any]:
    if response is None:
        return {"status": "UNOBSERVABLE", "claim_mentions": []}
    reasoning = str(response.get("reasoning_content") or "")
    content = str(response.get("content") or "")
    visible_text = f"{reasoning}\n{content}"
    mentions = [claim for claim in claims if claim and claim in visible_text]
    if mentions:
        status = "VISIBLE_REASONING_REFERENCES_CLAIM"
    elif any((row.get("proposed") or {}).get("validation_kind") for row in cycles):
        status = "VALIDATION_ACTION"
    elif any(
        "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
        in str((row.get("proposed") or {}).get("raw_command") or "")
        for row in cycles
    ):
        status = "SUBMIT_ACTION"
    elif cycles or response.get("actions"):
        status = "NEXT_ACTION_OBSERVED"
    else:
        status = "NO_ACTION_OBSERVED"
    return {
        "status": status,
        "claim_mentions": mentions,
        "observational_only": True,
    }


def build_intervention_chain(
    receipt: dict[str, Any],
    trajectory: dict[str, Any] | None = None,
    *,
    replay_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return one audit row for every canonical provider delivery."""

    contexts = {
        int(row["call"]): row
        for row in receipt.get("model_call_contexts") or ()
        if isinstance(row, dict) and isinstance(row.get("call"), int)
    }
    trajectory = trajectory or {}
    replay_responses = _replay_responses(replay_bundle)
    cycles_by_call = _action_cycles(receipt)
    rows: list[dict[str, Any]] = []
    canonical = collect_provider_deliveries(receipt)
    for delivery in canonical:
        call = int(delivery.get("delivered_before_call") or 0)
        context = contexts.get(call, {})
        response = replay_responses.get(call) or _response_for_call(trajectory, call)
        cycles = cycles_by_call.get(call, [])
        claims = list(delivery.get("claim_ids") or ())
        rows.append(
            {
                "surface": delivery["surface"],
                "surface_index": delivery["surface_index"],
                "delivery_id": delivery["delivery_id"] or delivery["identity"],
                "delivery_identity": delivery["identity"],
                "evidence": {
                    "claim_ids": claims,
                    "evidence_action": delivery.get("evidence_action"),
                    "first_eligible_call": delivery.get("first_eligible_call"),
                    "selected_evidence": delivery.get("selected_evidence") or [],
                    "claim_metadata": delivery.get("claim_metadata") or [],
                },
                "provider": {
                    "call": call,
                    "request_payload_sha256": context.get("request_payload_sha256"),
                    "provider_messages_sha256": context.get("provider_messages_sha256"),
                    "changed_message_indices": list(
                        context.get("provider_changed_message_indices") or ()
                    ),
                    "delivery_message_indices": list(
                        delivery.get("provider_message_indices") or ()
                    ),
                    "delivery_status": context.get("dispatch_status", "UNKNOWN"),
                    "delivered_before_model_query": delivery.get(
                        "delivered_before_model_query"
                    ),
                },
                "model_observation": {
                    "visible_response": bool(response),
                    "response_source": (response or {}).get("source"),
                    "content_sha256": (
                        _sha(response.get("content")) if response else None
                    ),
                    "reasoning_observed": bool(
                        response and response.get("reasoning_content")
                    ),
                    "reasoning_sha256": (
                        _sha(response.get("reasoning_content"))
                        if response and response.get("reasoning_content")
                        else None
                    ),
                    "response_blob_sha256": (response or {}).get(
                        "response_blob_sha256"
                    ),
                    "next_actions": list((response or {}).get("actions") or ()),
                },
                "postflight": {
                    "action_cycles": cycles,
                    "source_revisions_after": [
                        (row.get("postflight") or {}).get("source_revision")
                        for row in cycles
                        if (row.get("postflight") or {}).get("source_revision")
                    ],
                },
                "behavioral_uptake": _uptake(
                    response=response,
                    cycles=cycles,
                    claims=claims,
                ),
                "causal_status": "UNIDENTIFIABLE_WITHOUT_COUNTERFACTUAL",
            }
        )
    rows.sort(
        key=lambda row: (
            int(row["provider"].get("call") or 0),
            row["surface"],
            int(row["surface_index"]),
        )
    )
    surface_counts = dict(sorted(Counter(row["surface"] for row in rows).items()))
    return {
        "schema": "gt.intervention_chain.v2",
        "claim_policy": "visible_host_observations_only",
        "causal_policy": "matched_counterfactual_required",
        "hidden_reasoning_inferred": False,
        "rows": rows,
        "counts": {
            "rows": len(rows),
            "canonical_delivery_rows": len(canonical),
            "surface_counts": surface_counts,
            "visible_model_observations": sum(
                bool(row["model_observation"]["visible_response"]) for row in rows
            ),
            "causally_unidentifiable": len(rows),
        },
    }


def _atomic_write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_intervention_chain(
    receipt_path: str | Path,
    *,
    trajectory_path: str | Path | None = None,
    replay_bundle_path: str | Path | None = None,
) -> dict[str, Any]:
    receipt_path = Path(receipt_path)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    trajectory = (
        json.loads(Path(trajectory_path).read_text(encoding="utf-8"))
        if trajectory_path is not None and Path(trajectory_path).exists()
        else None
    )
    replay_bundle = None
    if replay_bundle_path is not None and Path(replay_bundle_path).exists():
        from gt_engine.replay_bundle import load_replay_bundle

        replay_bundle = load_replay_bundle(replay_bundle_path)
    chain = build_intervention_chain(
        receipt,
        trajectory,
        replay_bundle=replay_bundle,
    )
    output = receipt_path.with_name("intervention_chain.json")
    payload = json.dumps(chain, indent=2) + "\n"
    _atomic_write_text(output, payload)
    return {
        "path": output.name,
        "sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        "schema": chain["schema"],
        "hidden_reasoning_inferred": chain["hidden_reasoning_inferred"],
        **chain["counts"],
    }


def _artifact_path(root: Path, relative: object) -> Path | None:
    value = str(relative or "").strip()
    if not value:
        return None
    candidate = (root / value).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate


def audit_intervention_artifacts(
    receipt: dict[str, Any],
    *,
    artifact_root: str | Path,
) -> tuple[list[str], dict[str, Any]]:
    """Verify receipt, replay, trajectory, and intervention chain together."""

    from gt_engine.replay_bundle import load_replay_bundle

    root = Path(artifact_root)
    failures: list[str] = []
    replay_metadata = receipt.get("replay_bundle") or {}
    chain_metadata = receipt.get("intervention_chain") or {}
    replay_path = _artifact_path(root, replay_metadata.get("path"))
    chain_path = _artifact_path(root, chain_metadata.get("path"))
    trajectory_path = root / "miniswe_trajectory.json"
    replay: dict[str, Any] | None = None
    chain: dict[str, Any] | None = None
    trajectory: dict[str, Any] | None = None
    if replay_path is None:
        failures.append("replay_artifact_path_invalid")
    else:
        try:
            replay = load_replay_bundle(replay_path)
        except ValueError as exc:
            failures.append(f"replay_artifact_invalid:{exc}")
        manifest_path = replay_path / "manifest.json"
        if manifest_path.exists() and str(replay_metadata.get("sha256") or "") != hashlib.sha256(
            manifest_path.read_bytes()
        ).hexdigest():
            failures.append("replay_manifest_sha256_mismatch")
    if chain_path is None or not chain_path.is_file():
        failures.append("intervention_chain_artifact_missing")
    else:
        body = chain_path.read_bytes()
        if hashlib.sha256(body).hexdigest() != str(chain_metadata.get("sha256") or ""):
            failures.append("intervention_chain_sha256_mismatch")
        try:
            chain = json.loads(body)
        except ValueError:
            failures.append("intervention_chain_json_invalid")
    try:
        trajectory = json.loads(trajectory_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        failures.append("trajectory_artifact_invalid")
    contexts = {
        int(row["call"]): row
        for row in receipt.get("model_call_contexts") or ()
        if isinstance(row, dict) and isinstance(row.get("call"), int)
    }
    if replay is not None:
        replay_calls = replay.get("calls") or []
        if len(replay_calls) != len(contexts):
            failures.append("replay_context_call_count_mismatch")
        for row in replay_calls:
            call = int(row.get("call") or 0)
            context = contexts.get(call)
            if context is None:
                failures.append(f"replay_context_call_missing:{call}")
                continue
            for field in (
                "request_payload_sha256",
                "provider_messages_sha256",
                "control_request_payload_sha256",
                "control_provider_messages_sha256",
            ):
                replay_value = str(row.get(field) or "")
                context_value = str(context.get(field) or "")
                if replay_value and replay_value != context_value:
                    failures.append(f"replay_context_hash_mismatch:{call}:{field}")
    if chain is not None and replay is not None and trajectory is not None:
        rebuilt = build_intervention_chain(
            receipt,
            trajectory,
            replay_bundle=replay,
        )
        if chain != rebuilt:
            failures.append("intervention_chain_rebuild_mismatch")
        canonical_rows = len(collect_provider_deliveries(receipt))
        if int((chain.get("counts") or {}).get("rows") or 0) != canonical_rows:
            failures.append("intervention_chain_delivery_coverage")
    return failures, {
        "verified": not failures,
        "replay_calls": len((replay or {}).get("calls") or ()),
        "chain_rows": len((chain or {}).get("rows") or ()),
        "canonical_delivery_rows": len(collect_provider_deliveries(receipt)),
    }


__all__ = [
    "audit_intervention_artifacts",
    "build_intervention_chain",
    "write_intervention_chain",
]
