#!/usr/bin/env python3
"""Outcome-first promotion gate against the frozen TB2 Mini-SWE baseline."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from gt_engine.deep_metrics import normalized_token_cost

RESOURCE_FIELDS = (
    "total_tokens",
    "uncached_input_tokens",
    "provider_calls",
    "output_tokens",
    "normalized_cost_usd",
)
GATED_NONINCREASE_FIELDS = (
    "uncached_input_tokens",
    "provider_calls",
    "normalized_cost_usd",
)

PINNED_BASELINE_PROVENANCE = {
    "run_id": "30665246698",
    "benchmark_sha": "69671fbaac6d67a7ef0dfec016cc38a64ef7a77c",
    "source_artifact_sha256": "602fc6ac093ef3a35c25f00b4a4311229f631bb525dec3cc1eee3b5493456f79",
    "token_artifact_sha256": "aea4158aa9e568997b5ae5e5438929bc10ddc71da93dcfaef4a2c660c85f82f4",
}
EXPECTED_MODEL_IDENTITY = {
    "catalog_model": "openai/deepseek-v4-flash",
    "response_model": "deepseek-v4-flash",
    "route": "deepseek:native:api.deepseek.com",
    "api_host": "api.deepseek.com",
    "adapter_provider": "openai",
    "mini_version": "2.2.8",
    "agent_class": "eval.miniswe_agent:MiniSweAgent",
    "temperature": 1.0,
    "step_limit": 100,
    "environment_timeout_sec": 30,
    "timeout_multiplier": 1.0,
    "agent_timeout_multiplier": 1.0,
    "system_template_sha256": "6fb54145bbb1724ce77430ff3852887acbd4a5cce10c86cd8dfbf4c7d55f1091",
    "instance_template_sha256": "546a89156d7823eb34eb49c5b31a3703df4d27639d034a6d13f0162488d70821",
    "observation_template_sha256": (
        "da32186e7f86c2070607e69fdb7465b25cdfd108a4e932a379ea3763161db4a8"
    ),
    "tool_contract": "miniswe_bash_command_v1",
}
EXPECTED_TREATMENT_CONTRACT = {
    **EXPECTED_MODEL_IDENTITY,
    "agent_class": "eval.gt_central_agent:MiniSweCentralAgent",
    "preflight_mode": "assistive_safe",
}
REPAIR20_TASKS = (
    "cobol-modernization",
    "count-dataset-tokens",
    "extract-elf",
    "feal-linear-cryptanalysis",
    "fix-code-vulnerability",
    "headless-terminal",
    "largest-eigenval",
    "llm-inference-batching-scheduler",
    "mcmc-sampling-stan",
    "portfolio-optimization",
    "prove-plus-comm",
    "qemu-alpine-ssh",
    "regex-chess",
    "sanitize-git-repo",
    "schemelike-metacircular-eval",
    "torch-pipeline-parallelism",
    "torch-tensor-parallelism",
    "video-processing",
    "winning-avg-corewars",
    "write-compressor",
)
PINNED_PROFILE_HASHES = {
    "repair20-v1": "36d5c8945f6f8d9ae23fe2cea759f16da0c0cea424a98f710cfaa0d9d6fd0303",
    "regression-smoke-v1": "4c49430169d32ba1e63ba0449c6cf9841d58205cb7200d03755904ec0dfac9eb",
    "full89-v1": "3778b86071c74c8a342222cfff41089916adb5c7338d1afa69f42c9cae21fe3e",
}


@dataclass(frozen=True, slots=True)
class Tb2PromotionReport:
    passed: bool
    failures: tuple[str, ...]
    baseline_solved: int
    treatment_solved: int
    losses: tuple[str, ...]
    flips: tuple[str, ...]
    common_solved: tuple[str, ...]
    common_solved_resource_deltas: dict[str, float]
    full_profile_resource_deltas: dict[str, float]
    per_task_resource_deltas: dict[str, dict[str, float]]
    per_task_bound_failures: tuple[str, ...]
    fingerprint_metadata: tuple[str, ...]
    profile_id: str
    task_set_sha256: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _number(row: dict[str, Any], field: str) -> float | None:
    value = row.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    if not math.isfinite(numeric) or numeric < 0.0:
        return None
    return numeric


def _row_map(rows: Iterable[dict[str, Any]], *, arm: str) -> tuple[dict[str, dict], list[str]]:
    mapped: dict[str, dict] = {}
    failures: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            failures.append(f"{arm}_row_malformed")
            continue
        task = str(row.get("task") or "").strip()
        if not task:
            failures.append(f"{arm}_task_missing")
        elif task in mapped:
            failures.append(f"{arm}_task_duplicate:{task}")
        else:
            mapped[task] = row
    return mapped, failures


def _outcome_valid(row: dict[str, Any]) -> bool:
    reward = row.get("reward")
    return bool(
        isinstance(row.get("solved"), bool)
        and not isinstance(reward, bool)
        and isinstance(reward, (int, float))
        and math.isfinite(float(reward))
        and float(reward) in {0.0, 1.0}
        and row["solved"] is (float(reward) == 1.0)
    )


def task_set_sha256(task_ids: Iterable[str]) -> str:
    canonical = "\n".join(sorted(str(task) for task in task_ids)) + "\n"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _profile_task_ids(
    baseline_manifest: dict[str, Any],
    baseline_rows: dict[str, dict[str, Any]],
    profile_id: str,
) -> tuple[set[str], list[str]]:
    failures: list[str] = []
    profiles = baseline_manifest.get("profiles")
    if profile_id not in PINNED_PROFILE_HASHES:
        return set(), [f"comparison_profile_unknown:{profile_id or '<missing>'}"]
    if not isinstance(profiles, dict) or profile_id not in profiles:
        return set(), [f"comparison_profile_unknown:{profile_id or '<missing>'}"]
    profile = profiles.get(profile_id)
    if not isinstance(profile, dict):
        return set(), [f"comparison_profile_malformed:{profile_id}"]
    if profile.get("task_source") == "all_rows":
        task_ids = set(baseline_rows)
    else:
        raw_ids = profile.get("task_ids")
        if not isinstance(raw_ids, list) or any(not str(item) for item in raw_ids):
            return set(), [f"comparison_profile_task_ids_invalid:{profile_id}"]
        task_ids = {str(item) for item in raw_ids}
        if len(task_ids) != len(raw_ids):
            failures.append(f"comparison_profile_task_duplicate:{profile_id}")
    digest = task_set_sha256(task_ids)
    if int(profile.get("task_count") or 0) != len(task_ids):
        failures.append(f"comparison_profile_count_mismatch:{profile_id}")
    if str(profile.get("task_set_sha256") or "") != digest:
        failures.append(f"comparison_profile_hash_mismatch:{profile_id}")
    if digest != PINNED_PROFILE_HASHES[profile_id]:
        failures.append(f"comparison_profile_not_pinned:{profile_id}")
    if not task_ids.issubset(baseline_rows):
        failures.append(f"comparison_profile_baseline_rows_missing:{profile_id}")
    return task_ids, failures


def assess_tb2_promotion(
    baseline: dict[str, Any], treatment: dict[str, Any]
) -> Tb2PromotionReport:
    failures: list[str] = []
    if baseline.get("schema") != "gt.tb2.frozen_baseline.v2":
        failures.append("baseline_schema_invalid")
    if treatment.get("schema") != "gt.tb2.treatment.v2":
        failures.append("treatment_schema_invalid")
    baseline_manifest = baseline.get("manifest") or {}
    treatment_manifest = treatment.get("manifest") or {}
    for field, expected in PINNED_BASELINE_PROVENANCE.items():
        if str(baseline_manifest.get(field) or "").lower() != expected.lower():
            failures.append(f"baseline_provenance_mismatch:{field}")
    baseline_identity = baseline_manifest.get("model_identity")
    if not isinstance(baseline_identity, dict):
        failures.append("baseline_model_identity_missing")
        baseline_identity = {}
    for field, expected in EXPECTED_MODEL_IDENTITY.items():
        if baseline_identity.get(field) != expected:
            failures.append(f"baseline_model_identity_mismatch:{field}")
    if len(str(treatment_manifest.get("gt_commit") or "")) != 40:
        failures.append("treatment_gt_commit_not_exact")
    fingerprints = tuple(
        sorted(
            {
                str(item)
                for item in treatment_manifest.get("system_fingerprints") or ()
                if str(item)
            }
        )
    )
    failures.extend(
        f"treatment_integrity:{failure}"
        for failure in treatment.get("integrity_failures") or ()
    )

    baseline_rows, row_failures = _row_map(baseline.get("rows") or (), arm="baseline")
    failures.extend(row_failures)
    treatment_rows, row_failures = _row_map(treatment.get("rows") or (), arm="treatment")
    failures.extend(row_failures)
    profile_id = str(treatment_manifest.get("profile_id") or "")
    profile_tasks, profile_failures = _profile_task_ids(
        baseline_manifest, baseline_rows, profile_id
    )
    failures.extend(profile_failures)
    profile_digest = task_set_sha256(profile_tasks) if profile_tasks else ""
    planned = treatment_manifest.get("planned_task_ids")
    planned_tasks = (
        {str(item) for item in planned}
        if isinstance(planned, list) and all(str(item) for item in planned)
        else set()
    )
    if planned_tasks != profile_tasks or len(planned_tasks) != len(planned or ()):
        failures.append("planned_task_set_mismatch")
    if str(treatment_manifest.get("task_set_sha256") or "") != profile_digest:
        failures.append("treatment_task_set_hash_mismatch")
    if set(treatment_rows) != profile_tasks:
        failures.append("treatment_task_set_mismatch")
    observed = treatment_manifest.get("observed_identity")
    if not isinstance(observed, dict):
        failures.append("observed_identity_missing")
        observed = {}
    if observed.get("complete") is not True or observed.get("stable") is not True:
        failures.append("observed_identity_incomplete_or_unstable")
    response_model = EXPECTED_MODEL_IDENTITY["response_model"]
    adapter_provider = EXPECTED_MODEL_IDENTITY["adapter_provider"]
    if observed.get("executor_models") != [response_model] or observed.get(
        "bootstrap_model"
    ) != response_model or observed.get("canary_model") != response_model:
        failures.append("observed_model_identity_mismatch")
    if observed.get("executor_providers") != [adapter_provider] or observed.get(
        "bootstrap_provider"
    ) != adapter_provider or observed.get("canary_provider") != adapter_provider:
        failures.append("observed_provider_identity_mismatch")
    if observed.get("route") != EXPECTED_MODEL_IDENTITY["route"] or observed.get(
        "api_host"
    ) != EXPECTED_MODEL_IDENTITY["api_host"]:
        failures.append("observed_route_identity_mismatch")
    treatment_contract = treatment_manifest.get("runtime_contract")
    if not isinstance(treatment_contract, dict):
        failures.append("treatment_runtime_contract_missing")
        treatment_contract = {}
    for field, expected_value in EXPECTED_TREATMENT_CONTRACT.items():
        if treatment_contract.get(field) != expected_value:
            failures.append(f"treatment_runtime_contract_mismatch:{field}")

    comparable = sorted(profile_tasks & set(baseline_rows) & set(treatment_rows))
    for task in comparable:
        before = baseline_rows[task]
        after = treatment_rows[task]
        if not _outcome_valid(before):
            failures.append(f"verifier_outcome_invalid:baseline:{task}")
        if not _outcome_valid(after):
            failures.append(f"verifier_outcome_invalid:treatment:{task}")
        if after.get("censored") is not False:
            failures.append(f"censored_treatment:{task}")
        if not isinstance(after.get("persistent_applicable"), bool):
            failures.append(f"persistent_applicability_missing:{task}")
        for field in RESOURCE_FIELDS:
            if _number(before, field) is None:
                failures.append(f"missing_metric:baseline:{task}:{field}")
            if _number(after, field) is None:
                failures.append(f"missing_metric:treatment:{task}:{field}")
        provider_calls = _number(after, "provider_calls")
        executor_calls = _number(after, "executor_provider_calls")
        bootstrap_calls = _number(after, "bootstrap_provider_calls")
        if (
            provider_calls is None
            or executor_calls is None
            or bootstrap_calls is None
            or provider_calls != executor_calls + bootstrap_calls
            or bootstrap_calls not in {0.0, 1.0}
        ):
            failures.append(f"provider_call_accounting:{task}")
        if after.get("persistent_applicable") is True and bootstrap_calls != 1.0:
            failures.append(f"applicable_bootstrap_count:{task}")
        if after.get("persistent_applicable") is False and bootstrap_calls != 0.0:
            failures.append(f"abstained_bootstrap_count:{task}")

    valid_tasks = {
        task
        for task in comparable
        if _outcome_valid(baseline_rows[task]) and _outcome_valid(treatment_rows[task])
    }
    baseline_solved_tasks = {
        task for task in valid_tasks if baseline_rows[task].get("solved") is True
    }
    treatment_solved_tasks = {
        task for task in valid_tasks if treatment_rows[task].get("solved") is True
    }
    losses = tuple(sorted(baseline_solved_tasks - treatment_solved_tasks))
    flips = tuple(sorted(treatment_solved_tasks - baseline_solved_tasks))
    common = tuple(sorted(baseline_solved_tasks & treatment_solved_tasks))
    failures.extend(f"baseline_solve_regression:{task}" for task in losses)
    if not flips:
        failures.append("no_positive_flip")
    if len(treatment_solved_tasks) <= len(baseline_solved_tasks):
        failures.append("no_net_solve_improvement")
    if not common:
        failures.append("no_common_solved_tasks")

    per_task_deltas: dict[str, dict[str, float]] = {}
    aggregate = {field: 0.0 for field in RESOURCE_FIELDS}
    full_aggregate = {field: 0.0 for field in RESOURCE_FIELDS}
    bound_failures: list[str] = []
    for task in common:
        before = baseline_rows[task]
        after = treatment_rows[task]
        deltas: dict[str, float] = {}
        if all(_number(before, field) is not None for field in RESOURCE_FIELDS) and all(
            _number(after, field) is not None for field in RESOURCE_FIELDS
        ):
            for field in RESOURCE_FIELDS:
                delta = (_number(after, field) or 0.0) - (_number(before, field) or 0.0)
                deltas[field] = round(delta, 9)
                aggregate[field] += delta
        per_task_deltas[task] = deltas
        exceeded: list[str] = []
        if deltas:
            if deltas["provider_calls"] > max(
                3.0, (_number(before, "provider_calls") or 0.0) * 0.20
            ):
                exceeded.append("provider_calls")
            if deltas["total_tokens"] > max(
                50_000.0, (_number(before, "total_tokens") or 0.0) * 0.20
            ):
                exceeded.append("total_tokens")
            if deltas["normalized_cost_usd"] > max(
                0.01, (_number(before, "normalized_cost_usd") or 0.0) * 0.25
            ):
                exceeded.append("normalized_cost_usd")
        if len(exceeded) >= 2:
            bound_failures.append(task)
            failures.append(f"per_task_resource_bound:{task}:{','.join(exceeded)}")

    for task in sorted(valid_tasks):
        before = baseline_rows[task]
        after = treatment_rows[task]
        if all(_number(before, field) is not None for field in RESOURCE_FIELDS) and all(
            _number(after, field) is not None for field in RESOURCE_FIELDS
        ):
            for field in RESOURCE_FIELDS:
                full_aggregate[field] += (_number(after, field) or 0.0) - (
                    _number(before, field) or 0.0
                )

    aggregate = {field: round(value, 9) for field, value in aggregate.items()}
    if common and aggregate["total_tokens"] >= 0:
        failures.append("common_solved_no_strict_total_token_improvement")
    for field in GATED_NONINCREASE_FIELDS:
        if common and aggregate[field] > 0:
            failures.append(f"common_solved_resource_regression:{field}")
    full_aggregate = {
        field: round(value, 9) for field, value in full_aggregate.items()
    }
    if valid_tasks and full_aggregate["total_tokens"] >= 0:
        failures.append("full_profile_no_strict_total_token_improvement")
    for field in GATED_NONINCREASE_FIELDS:
        if valid_tasks and full_aggregate[field] > 0:
            failures.append(f"full_profile_resource_regression:{field}")

    return Tb2PromotionReport(
        passed=not failures,
        failures=tuple(dict.fromkeys(failures)),
        baseline_solved=len(baseline_solved_tasks),
        treatment_solved=len(treatment_solved_tasks),
        losses=losses,
        flips=flips,
        common_solved=common,
        common_solved_resource_deltas=aggregate,
        full_profile_resource_deltas=full_aggregate,
        per_task_resource_deltas=per_task_deltas,
        per_task_bound_failures=tuple(bound_failures),
        fingerprint_metadata=fingerprints,
        profile_id=profile_id,
        task_set_sha256=profile_digest,
    )


def build_frozen_baseline(
    merged: dict[str, Any],
    token_rows: Iterable[list[Any]],
    *,
    run_id: str,
    source_artifact_sha256: str,
) -> dict[str, Any]:
    usage = {str(row[0]): row for row in token_rows if isinstance(row, list) and len(row) >= 6}
    trials = merged.get("trial_results") or ()
    rows = []
    benchmark_shas = set()
    models = set()
    for trial in trials:
        task = str(trial.get("task_name") or "").split("__", 1)[0]
        rewards = (trial.get("verifier_result") or {}).get("rewards") or {}
        reward = rewards.get("reward")
        resource = usage.get(task)
        if not task or not isinstance(reward, (int, float)) or resource is None:
            raise ValueError(f"incomplete frozen baseline row: {task or '<missing>'}")
        benchmark_shas.add(str((trial.get("task_id") or {}).get("git_commit_id") or ""))
        models.add(str(((trial.get("agent_info") or {}).get("model_info") or {}).get("name") or ""))
        provider_calls, total, input_tokens, output_tokens, uncached = map(int, resource[1:6])
        rows.append(
            {
                "task": task,
                "solved": float(reward) == 1.0,
                "reward": float(reward),
                "exception": (trial.get("exception_info") or {}).get("exception_type"),
                "provider_calls": provider_calls,
                "total_tokens": total,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "uncached_input_tokens": uncached,
                "normalized_cost_usd": normalized_token_cost(
                    uncached,
                    max(0, input_tokens - uncached),
                    output_tokens,
                ),
            }
        )
    if len(benchmark_shas) != 1 or len(models) != 1:
        raise ValueError("frozen baseline identity is not stable")
    row_tasks = {str(row["task"]) for row in rows}
    if (
        str(run_id) != PINNED_BASELINE_PROVENANCE["run_id"]
        or str(source_artifact_sha256).lower()
        != PINNED_BASELINE_PROVENANCE["source_artifact_sha256"]
        or next(iter(benchmark_shas)) != PINNED_BASELINE_PROVENANCE["benchmark_sha"]
        or task_set_sha256(row_tasks) != PINNED_PROFILE_HASHES["full89-v1"]
        or not set(REPAIR20_TASKS).issubset(row_tasks)
    ):
        raise ValueError("frozen baseline does not match pinned provenance/profile")
    return {
        "schema": "gt.tb2.frozen_baseline.v2",
        "manifest": {
            "run_id": str(run_id),
            "benchmark_sha": next(iter(benchmark_shas)),
            "model": next(iter(models)),
            "source_artifact_sha256": str(source_artifact_sha256),
            "token_artifact_sha256": PINNED_BASELINE_PROVENANCE[
                "token_artifact_sha256"
            ],
            "model_identity": dict(EXPECTED_MODEL_IDENTITY),
            "normalized_cost_formula": "deepseek_v4_flash_2026q3_v1",
            "profiles": {
                "repair20-v1": {
                    "task_ids": list(REPAIR20_TASKS),
                    "task_count": len(REPAIR20_TASKS),
                    "task_set_sha256": PINNED_PROFILE_HASHES["repair20-v1"],
                },
                "full89-v1": {
                    "task_source": "all_rows",
                    "task_count": len(row_tasks),
                    "task_set_sha256": PINNED_PROFILE_HASHES["full89-v1"],
                },
            },
        },
        "rows": sorted(rows, key=lambda row: row["task"]),
    }


def treatment_from_merged(merged: dict[str, Any]) -> dict[str, Any]:
    metric_rows = list(merged.get("receipt_metrics") or ())
    metric_tasks = [
        str(row.get("task") or "") for row in metric_rows if isinstance(row, dict)
    ]
    metrics = {
        str(row.get("task") or ""): row for row in metric_rows if isinstance(row, dict)
    }
    integrity = [
        *(
            f"repository_intelligence:{task}"
            for task in merged.get("invalid_repository_intelligence_tasks") or ()
        ),
        *(f"dense_backend:{task}" for task in merged.get("invalid_dense_backend_tasks") or ()),
        *(
            f"provider_delivery:{task}"
            for task in merged.get("invalid_provider_delivery_tasks") or ()
        ),
        *(
            f"treatment_release:{task}"
            for task in merged.get("invalid_treatment_release_tasks") or ()
        ),
        *(f"missing_task:{task}" for task in merged.get("missing_tasks") or ()),
    ]
    if len(metric_tasks) != len(set(metric_tasks)):
        integrity.append("receipt_task_duplicate")
    manifest = dict(merged.get("treatment_manifest") or {})
    planned = manifest.get("planned_task_ids")
    if isinstance(planned, list) and set(metric_tasks) != {str(item) for item in planned}:
        integrity.append("receipt_task_set_mismatch")
    expected = int(merged.get("expected_tasks") or 0)
    n_trials = int(merged.get("n_trials") or 0)
    n_graded = int(merged.get("n_graded") or 0)
    if expected and n_trials != expected:
        integrity.append(f"trial_count:{n_trials}/{expected}")
    if expected and n_graded != expected:
        integrity.append(f"graded_count:{n_graded}/{expected}")
    rows = []
    for trial in merged.get("trial_results") or ():
        task = str(trial.get("task_name") or trial.get("trial_name") or "").split("__", 1)[0]
        rewards = (trial.get("verifier_result") or {}).get("rewards") or {}
        reward = rewards.get("reward")
        row = metrics.get(task) or {}
        if not row:
            integrity.append(f"receipt_missing:{task}")
        receipt_censored = row.get("censored") if "censored" in row else None
        trial_exception = trial.get("exception_info")
        if not isinstance(receipt_censored, bool):
            integrity.append(f"censor_state_missing:{task}")
            censored: bool | None = None
        else:
            censored = receipt_censored
            if bool(trial_exception) != censored:
                integrity.append(f"censor_state_mismatch:{task}")
        rows.append(
            {
                "task": task,
                "solved": isinstance(reward, (int, float)) and float(reward) == 1.0,
                "reward": reward,
                "censored": censored,
                "provider_calls": row.get("api_calls"),
                "executor_provider_calls": row.get("executor_api_calls"),
                "bootstrap_provider_calls": row.get("bootstrap_api_calls"),
                "persistent_applicable": row.get("persistent_applicable"),
                "total_tokens": row.get("total_tokens"),
                "input_tokens": row.get("input_tokens"),
                "output_tokens": row.get("output_tokens"),
                "uncached_input_tokens": row.get("uncached_input_tokens"),
                "normalized_cost_usd": row.get("normalized_cost_usd"),
            }
        )
    return {
        "schema": "gt.tb2.treatment.v2",
        "manifest": manifest,
        "integrity_failures": list(dict.fromkeys(integrity)),
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--treatment", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    treatment = json.loads(args.treatment.read_text(encoding="utf-8"))
    if treatment.get("schema") != "gt.tb2.treatment.v2":
        treatment = treatment_from_merged(treatment)
    report = assess_tb2_promotion(baseline, treatment)
    payload = json.dumps(report.as_dict(), indent=2) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
