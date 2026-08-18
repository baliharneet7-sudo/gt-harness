import json, os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gt_engine.central_runtime import CENTRAL_FEATURE_IDS
from gt_engine.deep_metrics import extract_trajectory
from gt_engine.delivery_audit import audit_provider_deliveries
from scripts.central_feature_lifecycle import build_feature_lifecycle_report
from scripts.central_release_gate import audit_treatment_runtime
from scripts.tb2_regression_forensics import build_regression_forensics
from scripts.tb2_promotion_gate import assess_tb2_promotion, treatment_from_merged

expected = json.loads(os.environ.get("EXPECTED_TASKS_JSON") or "[]")
dense_required = True
trials, missing, per_task, receipt_metrics = [], [], [], []
observed_artifact_tasks = set()
feature_receipts = []
deep_tasks = {}

def solved(t):
    rewards = (t.get("verifier_result") or {}).get("rewards") or {}
    vals = [v for v in rewards.values() if isinstance(v, (int, float))]
    return bool(vals) and all(v >= 1 for v in vals)

for task_dir in sorted(Path("tasks").glob("*")):
    task_name = task_dir.name.split("-task-", 1)[-1]
    observed_artifact_tasks.add(task_name)
    receipt_paths = list(task_dir.rglob("central_receipt.json"))
    if receipt_paths:
        receipt = json.loads(receipt_paths[0].read_text(encoding="utf-8"))
        receipt_for_lifecycle = dict(receipt)
        receipt_for_lifecycle["task"] = task_name
        feature_receipts.append(receipt_for_lifecycle)
        metrics = receipt.get("metrics") or {}
        intelligence = receipt.get("repository_intelligence") or {}
        preemptive = receipt.get("preemptive_retrieval") or {}
        dense_receipt = preemptive.get("dense_backend") or {}
        contexts = receipt.get("model_call_contexts") or []
        first_context = contexts[0] if contexts else {}
        control_provider_hash = str(
            first_context.get("control_provider_messages_sha256")
            or first_context.get("stock_provider_messages_sha256")
            or ""
        )
        provider_hash = str(
            first_context.get("provider_messages_sha256") or ""
        )
        dense_proofs = list(task_dir.rglob("dense-backend-proof.json"))
        dense_proof = (
            json.loads(dense_proofs[0].read_text(encoding="utf-8"))
            if dense_proofs
            else {}
        )
        provider_identity = receipt.get("provider_response_identity") or {}
        executor_identity = provider_identity.get("executor") or {}
        system_fingerprints = list(
            executor_identity.get("system_fingerprints") or ()
        ) or [
            (provider_identity.get("bootstrap") or {}).get("system_fingerprint")
            or ""
        ]
        (
            _provider_delivery_rows,
            provider_delivery_failures,
            provider_delivery_totals,
        ) = audit_provider_deliveries(receipt, task=task_name)
        treatment_release_failures = []
        if dense_required:
            treatment_release_failures = [
                failure
                for check in audit_treatment_runtime(receipt, label=task_name)
                for failure in check.failures
            ]
        receipt_metrics.append({
            "task": task_name,
            "feature_count": (receipt.get("features") or {}).get("feature_count"),
            "features_enabled": (receipt.get("features") or {}).get("enabled"),
            "sensor_healthy": receipt.get("workspace_sensor_healthy"),
            "input_tokens": metrics.get("input_tokens"),
            "output_tokens": metrics.get("output_tokens"),
            "cache_tokens": metrics.get("cache_tokens"),
            "total_tokens": metrics.get("total_tokens"),
            "normalized_cost_usd": metrics.get("normalized_cost_usd"),
            "api_calls": metrics.get("api_calls"),
            "executor_api_calls": metrics.get("executor_api_calls"),
            "bootstrap_api_calls": metrics.get("bootstrap_api_calls"),
            "persistent_applicable": (
                ((receipt.get("product_mechanism_census") or {})
                .get("persistent_execution_state") or {}).get("applicable")
            ),
            "actions": metrics.get("actions"),
            "effective_task_actions": metrics.get("effective_task_actions"),
            "actual_environment_execs": metrics.get("actual_environment_execs"),
            "controller_environment_execs": metrics.get("controller_environment_execs"),
            "controller_cached_reads": metrics.get("controller_cached_reads"),
            "sensor_environment_execs": metrics.get("sensor_environment_execs"),
            "assistant_steps": metrics.get("assistant_steps"),
            "trajectory_messages": metrics.get("trajectory_messages"),
            "guidance_events": metrics.get("guidance_events"),
            "guidance_chars": metrics.get("guidance_chars"),
            "guidance_candidates": metrics.get("guidance_candidates"),
            "guidance_suppressed": metrics.get("guidance_suppressed"),
            "uncached_input_tokens": metrics.get("uncached_input_tokens"),
            "cache_hit_rate": metrics.get("prompt_cache_hit_rate"),
            "successful_actions": metrics.get("successful_actions"),
            "failed_actions": metrics.get("failed_actions"),
            "check_actions": metrics.get("check_actions"),
            "workspace_change_actions": metrics.get("workspace_change_actions"),
            "repeated_commands": metrics.get("repeated_commands"),
            "censored": metrics.get("censored"),
            "censored_reason": metrics.get("censored_reason"),
            "repository_intelligence_status": intelligence.get("status"),
            "repository_intelligence_applicability": intelligence.get("applicability"),
            "repository_intelligence_denominator_excluded": bool(
                intelligence.get("denominator_excluded")
            ),
            "repository_intelligence_required": intelligence.get("required"),
            "repository_intelligence_failures": intelligence.get("failures") or [],
            "repository_intelligence_transient_failures": (
                intelligence.get("transient_failures") or []
            ),
            "repository_graph_degraded_fallback": bool(
                metrics.get("repository_graph_degraded_fallback")
                or (intelligence.get("graph_gate") or {}).get("degraded_fallback")
            ),
            "repository_graph_schema_valid": metrics.get("repository_graph_schema_valid"),
            "repository_graph_nodes": metrics.get("repository_graph_nodes"),
            "repository_graph_edges": metrics.get("repository_graph_edges"),
            "repository_mirror_transfer_ms": metrics.get("repository_mirror_transfer_ms"),
            "repository_index_refresh_ms": metrics.get("repository_index_refresh_ms"),
            "context_frontier_deliveries": metrics.get("context_frontier_deliveries"),
            "context_frontier_chars_added": metrics.get("context_frontier_chars_added"),
            "preemptive_retrieval_deliveries": metrics.get(
                "preemptive_retrieval_deliveries"
            ),
            "preemptive_retrieval_chars_added": metrics.get(
                "preemptive_retrieval_chars_added"
            ),
            "preemptive_dense_backend_available": bool(
                metrics.get("preemptive_dense_backend_available") == 1
                and dense_receipt.get("available") is True
                and dense_proof.get("available") is True
            ),
            "preemptive_dense_backend_error": (
                metrics.get("preemptive_dense_backend_error")
                or preemptive.get("dense_backend_error")
            ),
            "dense_backend_identity": (
                dense_receipt.get("model_name")
                or dense_proof.get("identity")
            ),
            "control_provider_messages_sha256": control_provider_hash,
            "provider_messages_sha256": provider_hash,
            "system_fingerprints": system_fingerprints,
            "executor_models": list(executor_identity.get("models") or ()),
            "executor_providers": list(executor_identity.get("providers") or ()),
            "executor_identity_complete": bool(
                executor_identity.get("model_identity_complete") is True
                and executor_identity.get("provider_identity_complete") is True
                and executor_identity.get("stable_model_identity") is True
                and executor_identity.get("stable_provider_identity") is True
            ),
            "bootstrap_model": str(
                (provider_identity.get("bootstrap") or {}).get("model") or ""
            ),
            "bootstrap_provider": str(
                (provider_identity.get("bootstrap") or {}).get("provider") or ""
            ),
            "call1_gt_view_changed": bool(
                control_provider_hash
                and provider_hash
                and control_provider_hash != provider_hash
            ),
            "total_gt_context_chars_added": metrics.get(
                "total_gt_context_chars_added"
            ),
            "provider_delivery_count": provider_delivery_totals.get(
                "delivery_count"
            ),
            "provider_delivery_visible_chars": provider_delivery_totals.get(
                "visible_chars"
            ),
            "provider_delivery_surfaces": provider_delivery_totals.get(
                "surfaces"
            ),
            "provider_delivery_failures": provider_delivery_failures,
            "treatment_release_failures": treatment_release_failures,
        })
    results = list(task_dir.rglob("result.json"))
    if not results:
        missing.append(task_name)
        trajectories = list(task_dir.rglob("miniswe_trajectory.json"))
        if trajectories:
            deep_tasks[task_name] = extract_trajectory(
                trajectories[0],
                task=task_name,
                reward=None,
                receipt_path=receipt_paths[0] if receipt_paths else None,
            )
        continue
    got = []
    for rp in results:
        r = json.loads(rp.read_text(encoding="utf-8"))
        # Single-task runs emit per-trial result.json (has
        # verifier_result/task_name) plus a job-level one (only stats,
        # no trial data). Count the per-trial files, skip job-level.
        if not r.get("verifier_result") and not r.get("task_name"):
            continue
        got.append(r)
    trials.extend(got)
    per_task.append((task_dir.name, len(got)))
    trajectories = list(task_dir.rglob("miniswe_trajectory.json"))
    if trajectories:
        reward = 1 if got and any(solved(item) for item in got) else 0 if got else None
        deep_tasks[task_name] = extract_trajectory(
            trajectories[0],
            task=task_name,
            reward=reward,
            receipt_path=receipt_paths[0] if receipt_paths else None,
            harbor_result=got[0] if got else None,
        )

missing.extend(
    task for task in expected if task not in observed_artifact_tasks
)
missing = list(dict.fromkeys(missing))

graded = [t for t in trials if (t.get("verifier_result") or {}).get("rewards")]
errored = [t for t in trials if t.get("exception_info")]
n_solved = sum(1 for t in graded if solved(t))
n_expected = len(expected) if expected else 0
invalid_intelligence = [
    row["task"]
    for row in receipt_metrics
    if row["repository_intelligence_required"]
    and not row["repository_intelligence_denominator_excluded"]
    and (
        row["repository_intelligence_status"] != "passed"
        or row["repository_graph_degraded_fallback"]
        or row["repository_intelligence_failures"]
    )
]
invalid_dense = [
    row["task"]
    for row in receipt_metrics
    if dense_required
    and row["repository_intelligence_required"]
    and not row["repository_intelligence_denominator_excluded"]
    and not row["preemptive_dense_backend_available"]
]
invalid_provider_deliveries = [
    row["task"]
    for row in receipt_metrics
    if row["provider_delivery_failures"]
]
invalid_treatment_release = [
    row["task"]
    for row in receipt_metrics
    if row["treatment_release_failures"]
]
call1_gt_changed_tasks = [
    row["task"]
    for row in receipt_metrics
    if row["call1_gt_view_changed"]
]
# Response model/provider identity is the comparison identity.
# Serving fingerprints remain non-gating metadata.
observed_fingerprints = {
    fp
    for row in receipt_metrics
    for fp in (row.get("system_fingerprints") or ())
    if fp
}
fingerprint_metadata = sorted(observed_fingerprints)
observed_executor_models = sorted({
    model
    for row in receipt_metrics
    for model in row.get("executor_models") or ()
    if model
})
observed_executor_providers = sorted({
    provider
    for row in receipt_metrics
    for provider in row.get("executor_providers") or ()
    if provider
})
applicable_rows = [
    row for row in receipt_metrics if row.get("persistent_applicable") is True
]
observed_bootstrap_models = sorted({
    row["bootstrap_model"] for row in applicable_rows if row["bootstrap_model"]
})
observed_bootstrap_providers = sorted({
    row["bootstrap_provider"] for row in applicable_rows if row["bootstrap_provider"]
})
observed_identity_complete = bool(
    len(receipt_metrics) == len(expected)
    and all(row["executor_identity_complete"] for row in receipt_metrics)
    and all(row["bootstrap_model"] and row["bootstrap_provider"] for row in applicable_rows)
)
observed_identity_stable = bool(
    observed_executor_models == ["deepseek-v4-flash"]
    and observed_executor_providers == ["openai"]
    and observed_bootstrap_models == ["deepseek-v4-flash"]
    and observed_bootstrap_providers == ["openai"]
)

out = ["# TB2 miniswe central matrix (GT-on)", ""]
out.append("- arm: **certified_full**")
out.append("- feature: **integrated 17+1**")
if missing:
    out.append(f"> **INCOMPLETE**: {len(missing)} task(s) produced no "
               f"result.json: {', '.join(missing)}. The score below covers "
               "only tasks that reported.")
    out.append("")
out += [
    f"- tasks planned: **{n_expected}**",
    f"- trials returned: **{len(trials)}**",
    f"- graded (verifier produced rewards): **{len(graded)}**",
    f"- errored (exception, not graded): **{len(errored)}**",
]
if graded:
    out.append(f"- **solved: {n_solved}/{len(graded)} "
               f"({100 * n_solved / len(graded):.1f}% of graded)**")
if n_expected:
    out.append(f"- **solved of planned: {n_solved}/{n_expected} "
               f"({100 * n_solved / n_expected:.1f}%)**")
if invalid_intelligence:
    out.append(
        f"> **INVALID GT TREATMENT**: repository intelligence failed for "
        f"{len(invalid_intelligence)} task(s): {', '.join(invalid_intelligence)}."
    )
if invalid_dense:
    out.append(
        f"> **INVALID DENSE TREATMENT**: pinned dense retrieval was unavailable "
        f"for {len(invalid_dense)} applicable task(s): {', '.join(invalid_dense)}."
    )
if invalid_provider_deliveries:
    out.append(
        f"> **INVALID PROVIDER DELIVERY**: deterministic delivery audit failed "
        f"for {len(invalid_provider_deliveries)} task(s): "
        f"{', '.join(invalid_provider_deliveries)}."
    )
if invalid_treatment_release:
    out.append(
        f"> **INVALID TREATMENT RELEASE**: persistent-state release gate failed "
        f"for {len(invalid_treatment_release)} task(s): "
        f"{', '.join(invalid_treatment_release)}."
    )
if call1_gt_changed_tasks:
    out.append(
        f"> **GT CHANGED CALL 1**: final call-1 provider bytes differ from "
        f"the same run's recorded pre-GT control for {len(call1_gt_changed_tasks)} "
        f"task(s): {', '.join(call1_gt_changed_tasks)}. This is intervention "
        "accounting, not a baseline-parity failure."
    )
if fingerprint_metadata:
    out.append(
        f"> **SERVING FINGERPRINT METADATA**: {fingerprint_metadata}. The model "
        "ID remains the comparison identity; fingerprint drift does not excuse "
        "losses or block the frozen-baseline promotion verdict."
    )
out += ["", "| task | solved | rewards / error |", "|---|---|---|"]
for t in sorted(trials, key=lambda x: x.get("task_name") or ""):
    name = (t.get("task_name") or t.get("trial_name", "?")).split("__")[0]
    rewards = (t.get("verifier_result") or {}).get("rewards")
    exc = (t.get("exception_info") or {}).get("exception_type")
    mark = "yes" if rewards and solved(t) else ("no" if rewards else "-")
    out.append(f"| {name} | {mark} | {json.dumps(rewards) if rewards else (exc or 'no reward')} |")

out += [
    "", "## Central runtime metrics", "",
    "| task | total tokens | uncached input | calls | model actions | effective task execs | controller execs | cached reads | checks | changes | failed | repeated | guidance delivered/candidates/suppressed | frontier deliveries/chars | graph nodes/edges | mirror/index ms | intelligence | censored |",
    "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|",
]
for row in sorted(receipt_metrics, key=lambda x: x["task"]):
    out.append(
        f"| {row['task']} | {row['total_tokens'] or '-'} | "
        f"{row['uncached_input_tokens'] or '-'} | {row['api_calls'] or '-'} | "
        f"{row['actions'] or '-'} | {row['effective_task_actions'] or '-'} | "
        f"{row['controller_environment_execs'] or 0} | "
        f"{row['controller_cached_reads'] or 0} | {row['check_actions'] or 0} | "
        f"{row['workspace_change_actions'] or 0} | {row['failed_actions'] or 0} | "
        f"{row['repeated_commands'] or 0} | {row['guidance_events'] or 0}/"
        f"{row['guidance_candidates'] or 0}/{row['guidance_suppressed'] or 0} | "
        f"{row['context_frontier_deliveries'] or 0}/"
        f"{row['context_frontier_chars_added'] or 0} | "
        f"{row['repository_graph_nodes'] or 0}/"
        f"{row['repository_graph_edges'] or 0} | "
        f"{row['repository_mirror_transfer_ms'] or 0}/"
        f"{row['repository_index_refresh_ms'] or 0} | "
        f"{row['repository_intelligence_status'] or 'unreported'} | "
        f"{row['censored'] or False} |"
    )

merged_payload = {
    "expected_tasks": n_expected,
    "missing_tasks": missing,
    "n_trials": len(trials),
    "n_graded": len(graded),
    "n_errored": len(errored),
    "n_solved": n_solved,
    "invalid_repository_intelligence_tasks": invalid_intelligence,
    "invalid_dense_backend_tasks": invalid_dense,
    "invalid_provider_delivery_tasks": invalid_provider_deliveries,
    "invalid_treatment_release_tasks": invalid_treatment_release,
    "dense_backend_required": dense_required,
    "call1_gt_changed_tasks": call1_gt_changed_tasks,
    "fingerprint_metadata": fingerprint_metadata,
    "trial_results": trials,
    "receipt_metrics": receipt_metrics,
    "treatment_manifest": {
        "model": "deepseek-v4-flash",
        "gt_commit": os.environ["GT_COMMIT"],
        "run_id": os.environ["GT_RUN_ID"],
        "system_fingerprints": sorted(observed_fingerprints),
        "profile_id": os.environ["COMPARISON_PROFILE"],
        "planned_task_ids": expected,
        "task_set_sha256": os.environ["TASK_SET_SHA256"],
        "observed_identity": {
            "executor_models": observed_executor_models,
            "executor_providers": observed_executor_providers,
            "bootstrap_model": (
                observed_bootstrap_models[0]
                if len(observed_bootstrap_models) == 1
                else ""
            ),
            "bootstrap_provider": (
                observed_bootstrap_providers[0]
                if len(observed_bootstrap_providers) == 1
                else ""
            ),
            "canary_model": os.environ["CANARY_MODEL"],
            "canary_provider": os.environ["CANARY_PROVIDER"],
            "route": "deepseek:native:api.deepseek.com",
            "api_host": "api.deepseek.com",
            "complete": observed_identity_complete,
            "stable": observed_identity_stable,
        },
        "runtime_contract": {
            "catalog_model": "openai/deepseek-v4-flash",
            "response_model": "deepseek-v4-flash",
            "route": "deepseek:native:api.deepseek.com",
            "api_host": "api.deepseek.com",
            "adapter_provider": "openai",
            "mini_version": "2.2.8",
            "agent_class": "eval.gt_central_agent:MiniSweCentralAgent",
            "preflight_mode": "assistive_safe",
            "temperature": 1.0,
            "step_limit": 100,
            "environment_timeout_sec": 30,
            "timeout_multiplier": 1.0,
            "agent_timeout_multiplier": 1.0,
            "system_template_sha256": "6fb54145bbb1724ce77430ff3852887acbd4a5cce10c86cd8dfbf4c7d55f1091",
            "instance_template_sha256": "546a89156d7823eb34eb49c5b31a3703df4d27639d034a6d13f0162488d70821",
            "observation_template_sha256": "da32186e7f86c2070607e69fdb7465b25cdfd108a4e932a379ea3763161db4a8",
            "tool_contract": "miniswe_bash_command_v1",
        },
    },
}
lifecycle_report = build_feature_lifecycle_report(
    feature_receipts,
    forced_feature_ids=CENTRAL_FEATURE_IDS,
    forced_proof={
        "status": "passed",
        "exact_commit": os.environ["GT_COMMIT"],
        "feature_ids": list(CENTRAL_FEATURE_IDS),
    },
    expected_task_ids=expected,
)
treatment = treatment_from_merged(merged_payload)
baseline = json.loads(
    Path("eval/frozen_baselines/tb2_miniswe_20260731.json").read_text(
        encoding="utf-8"
    )
)
promotion_report = assess_tb2_promotion(baseline, treatment)
forensics_report = build_regression_forensics(
    baseline,
    treatment,
    treatment_artifact_root=Path("tasks"),
)
profile_config = (
    (baseline.get("manifest") or {}).get("profiles") or {}
).get(os.environ["COMPARISON_PROFILE"], {})
diagnostic_only = bool(profile_config.get("diagnostic_only"))
merged_payload["feature_lifecycle_passed"] = lifecycle_report["passed"]
merged_payload["diagnostic_only"] = diagnostic_only
merged_payload["promotion_passed"] = (
    None if diagnostic_only else promotion_report.passed
)
merged_payload["forensics_complete"] = forensics_report["passed"]

out += [
    "",
    "## Release verdicts",
    "",
    f"- 17+1 mechanism lifecycle: **{'PASS' if lifecycle_report['passed'] else 'FAIL'}**",
    (
        "- frozen-baseline promotion: **NOT APPLIED (diagnostic smoke profile)**"
        if diagnostic_only
        else f"- frozen-baseline promotion: **{'PASS' if promotion_report.passed else 'FAIL'}**"
    ),
    f"- legacy features naturally fired: **{lifecycle_report['naturally_fired_legacy_feature_count']}/17**",
    f"- solve flips: **{', '.join(promotion_report.flips) or 'none'}**",
    f"- baseline solve losses: **{', '.join(promotion_report.losses) or 'none'}**",
]

Path("merged.json").write_text(
    json.dumps(merged_payload, indent=2), encoding="utf-8"
)
Path("feature_lifecycle_report.json").write_text(
    json.dumps(lifecycle_report, indent=2), encoding="utf-8"
)
Path("tb2_treatment.json").write_text(
    json.dumps(treatment, indent=2), encoding="utf-8"
)
Path("promotion_report.json").write_text(
    json.dumps(promotion_report.as_dict(), indent=2), encoding="utf-8"
)
Path("regression_forensics.json").write_text(
    json.dumps(forensics_report, indent=2), encoding="utf-8"
)
Path("deep_metrics_certified_full.json").write_text(json.dumps({
    "schema": "central-deep-metrics-v2",
    "arm": "certified_full",
    "run_id": os.environ["GT_RUN_ID"],
    "tasks": deep_tasks,
}, indent=2), encoding="utf-8")

body = "\n".join(out) + "\n"
Path("SUMMARY.md").write_text(body, encoding="utf-8")
with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
    f.write(body)
print(body[:4000])
if (invalid_intelligence or invalid_dense or invalid_provider_deliveries
        or invalid_treatment_release or not lifecycle_report["passed"]
        or (not diagnostic_only and not promotion_report.passed)):
    sys.exit(2)
