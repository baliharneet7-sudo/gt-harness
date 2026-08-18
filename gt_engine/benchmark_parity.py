"""Fail-closed comparison of frozen benchmark manifests and runtime receipts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from gt_engine.treatment_adapter import BenchmarkManifest

RUNTIME_FIELD_ORIGINS: dict[str, frozenset[str]] = {
    "task_count": frozenset({"dispatch_manifest"}),
    "task_order_sha256": frozenset({"dispatch_manifest"}),
    "provider_identity": frozenset({"provider_request", "provider_response"}),
    "temperature": frozenset({"agent_instance", "provider_request"}),
    "sampling_parameters": frozenset({"provider_request"}),
    "tool_envelope_sha256": frozenset({"serialized_runtime_envelope"}),
    "hook_envelope_sha256": frozenset({"serialized_runtime_envelope"}),
    "embedding_configuration_sha256": frozenset({"loaded_asset_receipt"}),
    "hardware_assumptions_sha256": frozenset({"runner_environment"}),
    "retry_policy_sha256": frozenset({"runtime_policy"}),
    "timeout_policy_sha256": frozenset({"runtime_policy"}),
    "token_accounting_sha256": frozenset({"metering_adapter"}),
}

RUNTIME_SOURCE_FIELDS: dict[str, tuple[str, ...]] = {
    "dispatch_manifest": ("task_count", "task_order_sha256"),
    "provider_request": ("provider_identity", "temperature", "sampling_parameters"),
    "serialized_runtime_envelope": (
        "tool_envelope_sha256",
        "hook_envelope_sha256",
    ),
    "loaded_asset_receipt": ("embedding_configuration_sha256",),
    "runner_environment": ("hardware_assumptions_sha256",),
    "runtime_policy": ("retry_policy_sha256", "timeout_policy_sha256"),
    "metering_adapter": ("token_accounting_sha256",),
}


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def runtime_observation_hash(value: object) -> str:
    """Hash one independently observed runtime field."""

    return hashlib.sha256(_canonical(value).encode("utf-8", "surrogatepass")).hexdigest()


@dataclass(frozen=True, slots=True)
class RuntimeParityAudit:
    """The complete result of one manifest-to-runtime comparison."""

    valid: bool
    failures: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RuntimeFieldObservation:
    """One runtime value captured at the component that owns it."""

    value: Any
    origin: str


def build_runtime_execution_observation(
    observations: Mapping[str, RuntimeFieldObservation],
) -> dict[str, Any]:
    """Build a complete source-labelled execution observation.

    This deliberately accepts observations rather than a benchmark manifest.
    The runner must capture each value from the component named by ``origin``;
    missing, unknown, and incorrectly owned fields fail before a parity receipt
    can be produced.
    """

    missing = sorted(set(RUNTIME_FIELD_ORIGINS) - set(observations))
    unknown = sorted(set(observations) - set(RUNTIME_FIELD_ORIGINS))
    if missing:
        raise ValueError("runtime observations missing fields: " + ", ".join(missing))
    if unknown:
        raise ValueError("runtime observations contain unknown fields: " + ", ".join(unknown))

    execution_contract: dict[str, Any] = {}
    field_sources: dict[str, dict[str, str]] = {}
    for field, allowed_origins in RUNTIME_FIELD_ORIGINS.items():
        observation = observations[field]
        if not isinstance(observation, RuntimeFieldObservation):
            raise TypeError(f"runtime observation {field} must be RuntimeFieldObservation")
        origin = str(observation.origin or "").strip()
        if origin not in allowed_origins:
            allowed = ", ".join(sorted(allowed_origins))
            raise ValueError(
                f"runtime observation {field} origin must be one of: {allowed}"
            )
        value = json.loads(_canonical(observation.value))
        execution_contract[field] = value
        field_sources[field] = {
            "origin": origin,
            "value_sha256": runtime_observation_hash(value),
        }
    return {
        "schema": "gt.benchmark_runtime_execution_observation.v1",
        "execution_contract": execution_contract,
        "field_sources": field_sources,
    }


def build_runtime_observation_from_sources(
    sources: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Build an observation from fixed runner-component source documents.

    Source ownership is defined by ``RUNTIME_SOURCE_FIELDS`` rather than by
    caller-provided origin labels. This prevents a manifest or arbitrary JSON
    declaration from being relabelled as provider, hardware, or metering
    evidence after the fact.
    """

    observations: dict[str, RuntimeFieldObservation] = {}
    missing_sources = sorted(set(RUNTIME_SOURCE_FIELDS) - set(sources))
    unknown_sources = sorted(set(sources) - set(RUNTIME_SOURCE_FIELDS))
    if missing_sources:
        raise ValueError("runtime source documents missing: " + ", ".join(missing_sources))
    if unknown_sources:
        raise ValueError("runtime source documents unknown: " + ", ".join(unknown_sources))
    for source_name, fields in RUNTIME_SOURCE_FIELDS.items():
        document = sources[source_name]
        if not isinstance(document, Mapping):
            raise TypeError(f"runtime source document {source_name} must be an object")
        for field in fields:
            if field not in document:
                raise ValueError(f"runtime source {source_name} missing field: {field}")
            observations[field] = RuntimeFieldObservation(
                document[field], source_name
            )
    return build_runtime_execution_observation(observations)


def audit_runtime_receipt(
    manifest: BenchmarkManifest,
    receipt: dict[str, Any],
) -> RuntimeParityAudit:
    """Compare all frozen benchmark identity fields with a runtime receipt.

    The receipt must contain a ``benchmark_identity`` object.  Missing identity,
    missing treatment identity, and any contract drift are failures; no field is
    defaulted from the manifest.  This function only audits identity and does
    not score tasks or alter the benchmark denominator.
    """
    failures: list[str] = []
    identity = receipt.get("benchmark_identity") if isinstance(receipt, dict) else None
    if not isinstance(identity, dict):
        return RuntimeParityAudit(False, ("benchmark_identity_missing",))

    expected = manifest.as_dict()
    for field in (
        "benchmark_id",
        "task_manifest_sha256",
        "model_id",
        "scaffold_sha",
        "max_steps",
        "trials_per_task",
        "manifest_sha256",
    ):
        if identity.get(field) != expected[field]:
            failures.append(f"{field}_mismatch")

    if _canonical(identity.get("execution_contract")) != _canonical(
        expected["execution_contract"]
    ):
        failures.append("execution_contract_mismatch")

    treatment = identity.get("treatment")
    if not isinstance(treatment, dict):
        failures.append("treatment_identity_missing")
    else:
        treatment_id = str(treatment.get("treatment_id") or "")
        expected_treatments = {
            str(row.get("treatment_id") or ""): row
            for row in expected["treatments"]
            if isinstance(row, dict)
        }
        expected_treatment = expected_treatments.get(treatment_id)
        if expected_treatment is None:
            failures.append("treatment_id_unknown")
        elif _canonical(treatment) != _canonical(expected_treatment):
            failures.append("treatment_identity_mismatch")

    observed = receipt.get("observed_runtime_contract")
    if not isinstance(observed, dict):
        failures.append("observed_runtime_contract_missing")
    else:
        if observed.get("schema") != "gt.benchmark_runtime_observation.v1":
            failures.append("observed_contract_schema_invalid")
        if observed.get("model_id") != expected["model_id"]:
            failures.append("observed_model_id_mismatch")
        if observed.get("max_steps") != expected["max_steps"]:
            failures.append("observed_max_steps_mismatch")
        observed_treatment_id = str(observed.get("treatment_id") or "")
        if not isinstance(treatment, dict) or (
            observed_treatment_id != str(treatment.get("treatment_id") or "")
        ):
            failures.append("observed_treatment_id_mismatch")
        expected_agent_kwargs = (
            treatment.get("agent_kwargs") if isinstance(treatment, dict) else None
        )
        if _canonical(observed.get("agent_kwargs")) != _canonical(
            expected_agent_kwargs
        ):
            failures.append("observed_agent_kwargs_mismatch")
        observed_execution = observed.get("execution_contract")
        if _canonical(observed_execution) != _canonical(
            expected["execution_contract"]
        ):
            failures.append("observed_execution_contract_mismatch")
        field_sources = observed.get("field_sources")
        if not isinstance(field_sources, dict):
            failures.append("observed_contract_field_sources_missing")
        else:
            for field, allowed_origins in RUNTIME_FIELD_ORIGINS.items():
                source = field_sources.get(field)
                if not isinstance(source, dict):
                    failures.append(f"observed_{field}_source_missing")
                    continue
                origin = str(source.get("origin") or "")
                if origin not in allowed_origins:
                    failures.append(f"observed_{field}_source_invalid")
                value = (
                    observed_execution.get(field)
                    if isinstance(observed_execution, dict)
                    else None
                )
                if source.get("value_sha256") != runtime_observation_hash(value):
                    failures.append(f"observed_{field}_hash_mismatch")

    return RuntimeParityAudit(not failures, tuple(dict.fromkeys(failures)))


__all__ = [
    "RUNTIME_FIELD_ORIGINS",
    "RUNTIME_SOURCE_FIELDS",
    "RuntimeFieldObservation",
    "RuntimeParityAudit",
    "audit_runtime_receipt",
    "build_runtime_execution_observation",
    "build_runtime_observation_from_sources",
    "runtime_observation_hash",
]
