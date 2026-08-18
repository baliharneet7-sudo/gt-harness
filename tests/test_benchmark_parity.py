from __future__ import annotations

import hashlib

import pytest

from gt_engine.benchmark_parity import (
    RUNTIME_FIELD_ORIGINS,
    RuntimeFieldObservation,
    audit_runtime_receipt,
    build_runtime_execution_observation,
    build_runtime_observation_from_sources,
    runtime_observation_hash,
)
from gt_engine.treatment_adapter import (
    BareTreatmentAdapter,
    BenchmarkManifest,
    GroundTruthTreatmentAdapter,
)


def _sha256(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _sha1(label: str) -> str:
    return hashlib.sha1(label.encode()).hexdigest()


def _contract() -> dict[str, object]:
    return {
        "task_count": 2,
        "task_order_sha256": _sha256("order"),
        "provider_identity": "fixture/provider",
        "temperature": 0.0,
        "sampling_parameters": {"top_p": 1.0},
        "tool_envelope_sha256": _sha256("tools"),
        "hook_envelope_sha256": _sha256("hooks"),
        "embedding_configuration_sha256": _sha256("embedding"),
        "hardware_assumptions_sha256": _sha256("hardware"),
        "retry_policy_sha256": _sha256("retry"),
        "timeout_policy_sha256": _sha256("timeout"),
        "token_accounting_sha256": _sha256("tokens"),
    }


def _manifest() -> BenchmarkManifest:
    harness = _sha1("harness")
    return BenchmarkManifest.create(
        benchmark_id="fixture-benchmark",
        task_manifest_sha256=_sha256("tasks"),
        model_id="fixture/provider",
        scaffold_sha=_sha1("scaffold"),
        max_steps=19,
        trials_per_task=2,
        execution_contract=_contract(),
        treatments=(
            BareTreatmentAdapter("bare", harness),
            GroundTruthTreatmentAdapter(
                "central_relational_v2",
                harness,
                "central_relational_v2",
                preemptive_retrieval=True,
                relational_context=True,
                dense_fallback_only=True,
                semantic_evidence=True,
            ),
        ),
    )


def _receipt(manifest: BenchmarkManifest) -> dict[str, object]:
    identity = manifest.runtime_identity("central_relational_v2")
    treatment = identity["treatment"]
    assert isinstance(treatment, dict)
    execution_contract = identity["execution_contract"]
    assert isinstance(execution_contract, dict)
    source_origins = {
        field: sorted(origins)[0]
        for field, origins in RUNTIME_FIELD_ORIGINS.items()
    }
    return {
        "benchmark_identity": identity,
        "observed_runtime_contract": {
            "schema": "gt.benchmark_runtime_observation.v1",
            "model_id": identity["model_id"],
            "max_steps": identity["max_steps"],
            "treatment_id": treatment["treatment_id"],
            "agent_kwargs": treatment["agent_kwargs"],
            "execution_contract": execution_contract,
            "field_sources": {
                field: {
                    "origin": source_origins[field],
                    "value_sha256": runtime_observation_hash(
                        execution_contract[field]
                    ),
                }
                for field in RUNTIME_FIELD_ORIGINS
            },
        },
    }


def test_runtime_receipt_matches_manifest() -> None:
    manifest = _manifest()

    result = audit_runtime_receipt(manifest, _receipt(manifest))

    assert result.valid is True
    assert result.failures == ()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("model_id", "other/provider"),
        ("max_steps", 20),
        ("trials_per_task", 3),
        ("manifest_sha256", "0" * 64),
    ],
)
def test_runtime_receipt_rejects_contract_drift(field: str, value: object) -> None:
    manifest = _manifest()
    receipt = _receipt(manifest)
    identity = receipt["benchmark_identity"]
    assert isinstance(identity, dict)
    identity[field] = value

    result = audit_runtime_receipt(manifest, receipt)

    assert result.valid is False
    assert result.failures
    assert any(field in failure for failure in result.failures)


def test_runtime_receipt_rejects_missing_identity_without_defaults() -> None:
    result = audit_runtime_receipt(_manifest(), {})

    assert result.valid is False
    assert "benchmark_identity_missing" in result.failures


def test_runtime_receipt_rejects_self_attested_identity_when_observed_model_differs() -> None:
    manifest = _manifest()
    receipt = _receipt(manifest)
    observed = receipt["observed_runtime_contract"]
    assert isinstance(observed, dict)
    observed["model_id"] = "different/runtime-model"

    result = audit_runtime_receipt(manifest, receipt)

    assert result.valid is False
    assert "observed_model_id_mismatch" in result.failures


def test_runtime_receipt_requires_independent_observed_contract() -> None:
    manifest = _manifest()

    result = audit_runtime_receipt(
        manifest,
        {"benchmark_identity": manifest.runtime_identity("central_relational_v2")},
    )

    assert result.valid is False
    assert "observed_runtime_contract_missing" in result.failures


def test_runtime_receipt_rejects_copied_contract_without_field_observations() -> None:
    manifest = _manifest()
    receipt = _receipt(manifest)
    observed = receipt["observed_runtime_contract"]
    assert isinstance(observed, dict)
    observed.pop("field_sources", None)
    observed.pop("schema", None)

    result = audit_runtime_receipt(manifest, receipt)

    assert result.valid is False
    assert "observed_contract_schema_invalid" in result.failures
    assert "observed_contract_field_sources_missing" in result.failures


def test_runtime_observation_builder_requires_every_independent_source() -> None:
    contract = _contract()
    observations = {
        field: RuntimeFieldObservation(contract[field], sorted(origins)[0])
        for field, origins in RUNTIME_FIELD_ORIGINS.items()
    }
    observations.pop("retry_policy_sha256")

    with pytest.raises(ValueError, match="retry_policy_sha256"):
        build_runtime_execution_observation(observations)


def test_runtime_observation_builder_rejects_wrong_component_owner() -> None:
    contract = _contract()
    observations = {
        field: RuntimeFieldObservation(contract[field], sorted(origins)[0])
        for field, origins in RUNTIME_FIELD_ORIGINS.items()
    }
    observations["task_count"] = RuntimeFieldObservation(2, "provider_request")

    with pytest.raises(ValueError, match="task_count origin"):
        build_runtime_execution_observation(observations)


def test_runtime_observation_builder_hashes_exact_observed_values() -> None:
    contract = _contract()
    built = build_runtime_execution_observation(
        {
            field: RuntimeFieldObservation(contract[field], sorted(origins)[0])
            for field, origins in RUNTIME_FIELD_ORIGINS.items()
        }
    )

    assert built["execution_contract"] == contract
    assert built["field_sources"]["sampling_parameters"] == {
        "origin": "provider_request",
        "value_sha256": runtime_observation_hash({"top_p": 1.0}),
    }


def test_runtime_source_bundle_assigns_fixed_component_ownership() -> None:
    contract = _contract()
    sources = {
        "dispatch_manifest": {
            "task_count": contract["task_count"],
            "task_order_sha256": contract["task_order_sha256"],
        },
        "provider_request": {
            "provider_identity": contract["provider_identity"],
            "temperature": contract["temperature"],
            "sampling_parameters": contract["sampling_parameters"],
        },
        "serialized_runtime_envelope": {
            "tool_envelope_sha256": contract["tool_envelope_sha256"],
            "hook_envelope_sha256": contract["hook_envelope_sha256"],
        },
        "loaded_asset_receipt": {
            "embedding_configuration_sha256": contract[
                "embedding_configuration_sha256"
            ],
        },
        "runner_environment": {
            "hardware_assumptions_sha256": contract["hardware_assumptions_sha256"],
        },
        "runtime_policy": {
            "retry_policy_sha256": contract["retry_policy_sha256"],
            "timeout_policy_sha256": contract["timeout_policy_sha256"],
        },
        "metering_adapter": {
            "token_accounting_sha256": contract["token_accounting_sha256"],
        },
    }

    built = build_runtime_observation_from_sources(sources)

    assert built["execution_contract"] == contract
    assert built["field_sources"]["task_count"]["origin"] == "dispatch_manifest"
    assert built["field_sources"]["token_accounting_sha256"]["origin"] == (
        "metering_adapter"
    )


def test_runtime_source_bundle_rejects_missing_component_field() -> None:
    contract = _contract()
    sources = {
        "dispatch_manifest": {
            "task_count": contract["task_count"],
            "task_order_sha256": contract["task_order_sha256"],
        },
        "provider_request": {
            "provider_identity": contract["provider_identity"],
            "temperature": contract["temperature"],
            "sampling_parameters": contract["sampling_parameters"],
        },
        "serialized_runtime_envelope": {
            "tool_envelope_sha256": contract["tool_envelope_sha256"],
            "hook_envelope_sha256": contract["hook_envelope_sha256"],
        },
        "loaded_asset_receipt": {},
        "runner_environment": {
            "hardware_assumptions_sha256": contract["hardware_assumptions_sha256"],
        },
        "runtime_policy": {
            "retry_policy_sha256": contract["retry_policy_sha256"],
            "timeout_policy_sha256": contract["timeout_policy_sha256"],
        },
        "metering_adapter": {
            "token_accounting_sha256": contract["token_accounting_sha256"],
        },
    }

    with pytest.raises(ValueError, match="embedding_configuration_sha256"):
        build_runtime_observation_from_sources(sources)


def test_manifest_runtime_identity_rejects_unknown_treatment() -> None:
    with pytest.raises(ValueError, match="unknown treatment ID"):
        _manifest().runtime_identity("not-a-treatment")
