from __future__ import annotations

import hashlib

import pytest

from gt_engine.treatment_adapter import (
    BareTreatmentAdapter,
    BenchmarkManifest,
    ExternalTreatmentAdapter,
    GroundTruthTreatmentAdapter,
    treatment_from_descriptor,
)


def _sha1(label: str) -> str:
    return hashlib.sha1(label.encode(), usedforsecurity=False).hexdigest()


def _sha256(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _execution_contract() -> dict[str, object]:
    return {
        "task_count": 7,
        "task_order_sha256": _sha256("fixture-task-order"),
        "provider_identity": "fixture-provider",
        "temperature": 0.25,
        "sampling_parameters": {"top_p": 0.9},
        "tool_envelope_sha256": _sha256("fixture-tools"),
        "hook_envelope_sha256": _sha256("fixture-hooks"),
        "embedding_configuration_sha256": _sha256("fixture-embedding"),
        "hardware_assumptions_sha256": _sha256("fixture-hardware"),
        "retry_policy_sha256": _sha256("fixture-retries"),
        "timeout_policy_sha256": _sha256("fixture-timeouts"),
        "token_accounting_sha256": _sha256("fixture-token-accounting"),
    }


def _treatments():
    harness = _sha1("fixture-harness-source")
    return (
        BareTreatmentAdapter("bare", harness),
        GroundTruthTreatmentAdapter(
            "groundtruth",
            harness,
            "central_relational_v2",
            preemptive_retrieval=True,
            relational_context=True,
            dense_fallback_only=True,
            semantic_evidence=True,
        ),
    )


def test_caller_supplied_treatment_descriptors_have_no_implicit_arms() -> None:
    treatments = (
        treatment_from_descriptor(
            {
                "adapter_kind": "bare",
                "treatment_id": "control",
                "source_sha": _sha1("fixture-harness-source"),
            }
        ),
        treatment_from_descriptor(
            {
                "adapter_kind": "groundtruth",
                "treatment_id": "candidate",
                "source_sha": _sha1("fixture-harness-source"),
                "profile_id": "central_relational_v2",
                "preemptive_retrieval": True,
                "relational_context": True,
                "dense_fallback_only": True,
                "semantic_evidence": True,
            }
        ),
    )
    by_id = {item.treatment_id: item for item in treatments}

    assert set(by_id) == {"control", "candidate"}
    final = by_id["candidate"]
    assert isinstance(final, GroundTruthTreatmentAdapter)
    assert final.agent_kwargs() == {
        "integration_mode": "active",
        "treatment_profile": "central_relational_v2",
        "enable_persistent_execution_state": True,
        "enable_preemptive_retrieval": True,
        "enable_relational_context": True,
        "dense_fallback_only": True,
        "relational_context_max_depth": 6,
        "relational_context_max_branching": 3,
        "relational_context_max_processes": 3,
        "relational_context_max_tokens": 256,
        "enable_semantic_evidence": True,
    }


def test_external_treatment_requires_pinned_source_and_declares_delivery_mode() -> None:
    with pytest.raises(ValueError, match="40-character source SHA"):
        ExternalTreatmentAdapter(
            treatment_id="external",
            source_sha="main",
            repository_origin="https://example.invalid/fixture/external.git",
            delivery_mode="mcp",
            preparation_contract_sha256=_sha256("fixture-preparation"),
            execution_contract_sha256=_sha256("fixture-execution"),
        )

    adapter = ExternalTreatmentAdapter(
        treatment_id="external",
        source_sha=_sha1("fixture-external-source"),
        repository_origin="https://example.invalid/fixture/external.git",
        delivery_mode="common_scaffold_context",
        preparation_contract_sha256=_sha256("fixture-preparation"),
        execution_contract_sha256=_sha256("fixture-execution"),
    )
    assert adapter.receipt_identity()["source_sha"] == _sha1(
        "fixture-external-source"
    )
    assert adapter.receipt_identity()["delivery_mode"] == "common_scaffold_context"
    assert adapter.receipt_identity()["executable"] is False


def test_benchmark_manifest_freezes_common_scaffold_and_rejects_duplicate_arms() -> None:
    treatments = _treatments()
    benchmark_id = "fixture-benchmark"
    task_manifest_sha = _sha256("fixture-task-manifest")
    model_id = "fixture-provider/model"
    scaffold_sha = _sha1("fixture-scaffold-source")
    configured_max_steps = 17
    configured_trials = 3
    manifest = BenchmarkManifest.create(
        benchmark_id=benchmark_id,
        task_manifest_sha256=task_manifest_sha,
        model_id=model_id,
        scaffold_sha=scaffold_sha,
        max_steps=configured_max_steps,
        trials_per_task=configured_trials,
        execution_contract=_execution_contract(),
        treatments=treatments,
    )

    payload = manifest.as_dict()
    assert payload["schema"] == "gt.benchmark_manifest.v1"
    assert payload["benchmark_id"] == benchmark_id
    assert payload["max_steps"] == configured_max_steps
    assert payload["trials_per_task"] == configured_trials
    assert payload["common_scaffold"] is True
    assert payload["manifest_sha256"]
    assert len(payload["treatments"]) == 2
    assert payload["parity_treatment_ids"] == ["bare", "groundtruth"]
    assert BenchmarkManifest.from_dict(payload).as_dict() == payload

    tampered = {**payload, "max_steps": configured_max_steps + 1}
    with pytest.raises(ValueError, match="content or hash mismatch"):
        BenchmarkManifest.from_dict(tampered)

    with pytest.raises(ValueError, match="treatment IDs must be unique"):
        BenchmarkManifest.create(
            benchmark_id=benchmark_id,
            task_manifest_sha256=task_manifest_sha,
            model_id=model_id,
            scaffold_sha=scaffold_sha,
            max_steps=configured_max_steps,
            trials_per_task=configured_trials,
            execution_contract=_execution_contract(),
            treatments=(treatments[0], treatments[0]),
        )

    empty_id = ExternalTreatmentAdapter(
        treatment_id="",
        source_sha=_sha1("fixture-empty-id-source"),
        repository_origin="https://example.invalid/fixture/empty.git",
        delivery_mode="fixture",
        preparation_contract_sha256=_sha256("fixture-empty-preparation"),
        execution_contract_sha256=_sha256("fixture-empty-execution"),
    )
    with pytest.raises(ValueError, match="treatment IDs must be unique and non-empty"):
        BenchmarkManifest.create(
            benchmark_id=benchmark_id,
            task_manifest_sha256=task_manifest_sha,
            model_id=model_id,
            scaffold_sha=scaffold_sha,
            max_steps=configured_max_steps,
            trials_per_task=configured_trials,
            execution_contract=_execution_contract(),
            treatments=(empty_id,),
        )


def test_manifest_rejects_incomplete_execution_freeze() -> None:
    treatments = _treatments()
    incomplete = _execution_contract()
    del incomplete["token_accounting_sha256"]

    with pytest.raises(ValueError, match="execution contract missing"):
        BenchmarkManifest.create(
            benchmark_id="fixture-suite",
            task_manifest_sha256=_sha256("fixture-tasks"),
            model_id="fixture-provider/model",
            scaffold_sha=_sha1("fixture-scaffold"),
            max_steps=9,
            trials_per_task=2,
            execution_contract=incomplete,
            treatments=treatments,
        )


@pytest.mark.parametrize("invalid_temperature", [True, False, float("nan"), float("inf")])
def test_manifest_rejects_non_numeric_or_non_finite_temperature(
    invalid_temperature: object,
) -> None:
    treatments = _treatments()
    contract = _execution_contract()
    contract["temperature"] = invalid_temperature

    with pytest.raises(ValueError, match="temperature"):
        BenchmarkManifest.create(
            benchmark_id="fixture-suite",
            task_manifest_sha256=_sha256("fixture-tasks"),
            model_id="fixture-provider/model",
            scaffold_sha=_sha1("fixture-scaffold"),
            max_steps=9,
            trials_per_task=2,
            execution_contract=contract,
            treatments=treatments,
        )
