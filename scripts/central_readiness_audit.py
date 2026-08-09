#!/usr/bin/env python3
"""Provider-free structural gate for the host-owned central runtime.

This gate proves the isolation architecture and stock tool contract.  It does
not claim model efficacy or replace the live task-container surface audit.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import sys
import tempfile
from pathlib import Path

# Mini-SWE may print a first-run Unicode banner during import.  Windows CI can
# expose a legacy CP1252 stdout even though the repository itself is UTF-8.
# Make the provider-free audit deterministic before importing Mini-SWE.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from harbor.agents.base import BaseAgent
from harbor.agents.installed.base import BaseInstalledAgent
from minisweagent.models.litellm_model import BASH_TOOL, LitellmModel

from eval.gt_central_agent import GTIntegrationMode, MiniSweCentralAgent
from gt_engine.central_runtime import CentralFeatureRuntime, ValidationClassification
from gt_engine.host_execution import HostExecutionRecorder
from gt_engine.preflight import PreflightMode
from scripts.central_feature_census import census as central_feature_census

ROOT = Path(__file__).resolve().parents[1]

_REQUIRED_GROUNDTRUTH_RUNTIME = (
    "groundtruth.runtime.terminal_evidence",
    "groundtruth.runtime.deterministic_queries",
    "groundtruth.runtime.miniswe_provider_boundary",
)


def _vendored_runtime_surface_available() -> bool:
    """Fail readiness when an older/incomplete groundtruth wheel is installed."""

    try:
        return all(
            importlib.util.find_spec(module_name) is not None
            for module_name in _REQUIRED_GROUNDTRUTH_RUNTIME
        )
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def audit() -> dict[str, bool]:
    source = inspect.getsource(MiniSweCentralAgent)
    run_source = inspect.getsource(MiniSweCentralAgent.run)
    setup_source = inspect.getsource(MiniSweCentralAgent.setup)
    validation_source = inspect.getsource(ValidationClassification)
    observation_source = inspect.getsource(CentralFeatureRuntime.observe_action)
    # The paid ten-task smoke dispatches the central matrix workflow.  Keep
    # the older engine workflow in the audit as a second release surface, but
    # never let a correctly configured sibling mask a stale dispatch target.
    workflow_paths = (
        ROOT / ".github/workflows/tb2_miniswe_central.yml",
        ROOT / ".github/workflows/tb2_miniswe_engine.yml",
    )
    workflows = tuple(path.read_text(encoding="utf-8") for path in workflow_paths)
    workflow = workflows[0]
    verification_workflow = workflows[1]
    provider_free_workflow = (ROOT / ".github/workflows/central_provider_free.yml").read_text(
        encoding="utf-8"
    )
    deep_metrics_source = (ROOT / "gt_engine/deep_metrics.py").read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as directory:
        agent = MiniSweCentralAgent(logs_dir=Path(directory), model_name="audit-model")
        model = agent._build_model()
    feature_result = central_feature_census()
    return {
        "host_base_agent": issubclass(MiniSweCentralAgent, BaseAgent),
        "not_installed_agent": not issubclass(MiniSweCentralAgent, BaseInstalledAgent),
        "setup_has_no_exec": ".exec(" not in setup_source,
        "setup_has_no_upload": "upload_" not in setup_source,
        "stock_litellm_model": type(model) is LitellmModel,
        "stock_bash_tool_only": BASH_TOOL["function"]["name"] == "bash",
        "vendored_groundtruth_runtime_surface": _vendored_runtime_surface_available(),
        "paid_central_installs_vendored_groundtruth": (
            workflow.count("vendor/groundtruth_mcp-*.whl") >= 2
            and workflow.count("chmod +x vendor/gt-index-linux-amd64") >= 2
        ),
        "paid_central_exports_index_binary": (
            workflow.count("GT_INDEX_BINARY:") >= 2
            and workflow.count("vendor/gt-index-linux-amd64") >= 4
        ),
        "paid_central_executes_index_fixture": (
            workflow.count("python scripts/verify_gt_index_runtime.py") >= 2
        ),
        "paid_central_executes_language_contract": (
            workflow.count("python scripts/verify_tb2_language_contract.py") >= 2
        ),
        "preflight_default_is_off": agent.preflight_mode is PreflightMode.OFF,
        "paid_preflight_is_shadow_only": all(
            "--ak preflight_mode=shadow" in item and "--ak enable_preflight=true" not in item
            for item in workflows
        ),
        "staged_policy_arms_are_explicit_and_default_safe": all(
            "options: [off, audit, certified_context, certified_controllers, certified_full]"
            in item
            and "default: audit" in item
            and "--ak integration_mode=off --ak policy_mode=off --ak preflight_mode=off"
            in item
            and "--ak integration_mode=audit --ak policy_mode=audit --ak preflight_mode=shadow"
            in item
            and "--ak policy_mode=certified_active" in item
            for item in workflows
        ),
        "one_switch_off_is_provider_neutral": (
            GTIntegrationMode.OFF.value == "off"
            and "transform=False" in run_source
            and "self.integration_mode is GTIntegrationMode.OFF" in source
        ),
        "provider_free_gate_covers_preflight": (
            "tests/test_gt_preflight.py" in provider_free_workflow
        ),
        "provider_free_gate_covers_trajectory_audit": (
            "scripts/central_trajectory_audit.py" in provider_free_workflow
            and "tests/test_central_trajectory_audit.py" in provider_free_workflow
        ),
        "provider_free_gate_covers_context_compiler": (
            "tests/test_provider_view.py" in provider_free_workflow
            and "tests/test_gt_deep_metrics.py" in provider_free_workflow
            and "tests/test_gt_uplift_policy.py" in provider_free_workflow
            and "tests/test_gt_on_experiment.py" in provider_free_workflow
        ),
        "provider_baseline_shield_is_exact_until_measured_pressure": (
            "stock_provider_messages_sha256" in run_source
            and "provider_changed_message_indices" in run_source
            and "provider_compaction_required(" in run_source
            and "feature_guidance_chars" in run_source
            and "certified_graph_chars" in run_source
        ),
        "common_certification_boundary_is_applied": (
            "certify_opportunity(" in run_source
            and "completion_opportunity.certified" in run_source
            and "certification_decisions" in run_source
            and (ROOT / "gt_engine/uplift_policy.py").is_file()
        ),
        "repeated_control_release_gate_is_available": (
            "assess_repeated_release" in (ROOT / "gt_engine/experiment.py").read_text(
                encoding="utf-8"
            )
            and "crossover_arm" in (ROOT / "gt_engine/experiment.py").read_text(
                encoding="utf-8"
            )
        ),
        "provider_free_gate_covers_repository_intelligence": (
            "tests/test_gt_intelligence_layer.py" in provider_free_workflow
            and "tests/test_gt_repository_intelligence.py" in provider_free_workflow
            and "tests/test_gt_repository_mirror.py" in provider_free_workflow
            and "gt_engine/context_frontier.py" in provider_free_workflow
            and "gt_engine/language_registry.py" in provider_free_workflow
            and "gt_engine/repository_mirror.py" in provider_free_workflow
        ),
        "provider_free_gate_covers_pinned_benchmark_languages": (
            "tests/test_gt_language_resolution.py" in provider_free_workflow
            and "tests/test_gt_benchmark_language_contract.py" in provider_free_workflow
            and "scripts/verify_tb2_language_contract.py --dataset-root"
            in provider_free_workflow
            and "2fd12b88aafdd04a52c298e3940bcb189f9766d6"
            in provider_free_workflow
        ),
        "paid_context_frontier_is_explicit": all(
            "--ak enable_context_frontier=true" in item for item in workflows
        ),
        "paid_graph_gate_is_explicit": all(
            "--ak require_graph_ready=true" in item for item in workflows
        )
        and "graph_gate_failures" in run_source
        and "graph_degraded_fallback" in run_source
        and "graph_gate_blocked = False" in run_source,
        "paid_deterministic_compaction_enabled": all(
            "--ak enable_context_compaction=true" in item for item in workflows
        )
        and "tests/test_provider_view.py" in provider_free_workflow,
        "paid_adaptive_validation_timeout_is_explicit": all(
            "--ak enable_adaptive_validation_timeout=true" in item for item in workflows
        ),
        "provider_free_gate_covers_execution_accounting": (
            "tests/test_gt_host_execution.py" in provider_free_workflow
            and "gt_engine/host_execution.py" in provider_free_workflow
            and inspect.isclass(HostExecutionRecorder)
        ),
        "context_compiler_precedes_model_query": (
            0
            <= run_source.find("record_context_compiler_call(")
            < run_source.find("model.query, query_messages")
        ),
        "provider_prepared_hash_precedes_model_query": (
            0
            <= run_source.find("_provider_request_receipt(model, query_messages)")
            < run_source.find("model.query, query_messages")
        ),
        "repository_frontier_precedes_model_query": (
            0
            <= run_source.find("compile_incremental_frontier(")
            < run_source.find("model.query, query_messages")
        ),
        "action_conditioned_graph_query_precedes_postflight": (
            0
            <= run_source.find("repository_session.query,")
            < run_source.find("self._features.observe_action(")
            and "active_paths=action_graph_paths" in run_source
            and 'boundary=f"post_{proposed.operation.value}"' in run_source
        ),
        "repository_intelligence_failure_is_receipted": (
            "material_frontier_not_delivered" in run_source
            and "context_frontier_coverage" in run_source
            and "repository_intelligence_valid" in run_source
            and "frontier_fact_accounting_incomplete" in run_source
        ),
        "repository_mirror_is_source_only_and_bounded": (
            "plan_source_mirror" in source
            and "SourceMirrorIncomplete" in source
            and "source_only_archive" in source
            and "REPOSITORY_TRANSFER" in source
        ),
        "repository_intelligence_failure_blocks_outcome_gate": (
            "invalid_treatments" in deep_metrics_source
            and "repository_intelligence_required" in deep_metrics_source
            and "context_frontier_chars_added" in deep_metrics_source
            and "INVALID GT TREATMENT" in workflow
        ),
        "validation_status_is_attributed_not_outer_rc_only": (
            "status_attributed=True" in validation_source
            and "later_shell_segment_owns_action_status" in validation_source
            and "classification.status is ValidationStatus.PASS" in observation_source
            and "classification.status is ValidationStatus.FAIL" in observation_source
        ),
        "validation_authority_is_explicit": (
            "authority: ValidationAuthority" in validation_source
            and "CUSTOM_PROBE"
            in inspect.getsource(sys.modules[ValidationClassification.__module__])
        ),
        "typed_proposal_precedes_environment_exec": (
            0
            <= run_source.find("adapt_proposed_action(")
            < run_source.find("self._host_executions.exec(")
        ),
        "workflow_deep_metrics_receive_harbor_result": (
            "harbor_result=got[0] if got else None" in workflow
        ),
        "task_exec_env_is_empty": "env={}," in source,
        "treatment_workflow_central": (
            'AGENT="eval.gt_central_agent:MiniSweCentralAgent"' in workflow
        ),
        "all_component_arms_use_one_central_engine": (
            'AGENT="eval.gt_central_agent:MiniSweCentralAgent"' in workflow
            and "MiniSweCentralShadowAgent" not in workflow
        ),
        "custom_agent_uses_import_path": '--agent-import-path "$AGENT"' in workflow,
        "frozen_miniswe_version": '"mini-swe-agent==2.2.8"' in workflow,
        "legacy_agent_not_in_paid_workflow": (
            "eval.miniswe_agent:MiniSweEngineAgent" not in workflow
        ),
        "paid_exact_harbor_deadline_is_propagated": (
            all(
                "--ak enable_lint=true" in item
                and "--ak enable_submit_readiness=true" in item
                and "scripts/resolve_harbor_budget.py" in item
                and '--ak execution_budget_sec="$EXECUTION_BUDGET"' in item
                and "--agent-timeout-multiplier 1.0" in item
                and "--ak model_timeout_sec" not in item
                and "--ak model_loop_timeout_sec" not in item
                for item in workflows
            )
        ),
        "paid_completion_and_progress_control_enabled": (
            all(
                "--ak enable_completion_controller=true" in item
                and "--ak enable_progress_control=true" in item
                for item in workflows
            )
            and "tests/test_gt_completion.py" in verification_workflow
            and "tests/test_gt_progress.py" in verification_workflow
            and "tests/test_harbor_budget.py" in verification_workflow
        ),
        "provider_budget_and_reasoning_preservation_gated": (
            "test_provider_request_budget_fails_closed_before_provider_overflow"
            in (ROOT / "scripts/central_pre_smoke_gate.py").read_text(encoding="utf-8")
            and "test_over_budget_next_request_does_not_confirm_pending_guidance"
            in (ROOT / "scripts/central_pre_smoke_gate.py").read_text(encoding="utf-8")
            and "test_compaction_never_removes_distinct_assistant_reasoning"
            in (ROOT / "scripts/central_pre_smoke_gate.py").read_text(encoding="utf-8")
            and "test_provider_view_session_reuses_an_immutable_compacted_prefix"
            in (ROOT / "scripts/central_pre_smoke_gate.py").read_text(encoding="utf-8")
            and "tests/test_gt_progress.py" in verification_workflow
        ),
        "central_features_consumer_paths_proven": bool(
            feature_result["all_17_consumer_paths_proven"]
        ),
        "all_effects_context_accounted": bool(feature_result["all_effects_context_accounted"]),
        "repository_substrate_and_frontier_proven": bool(
            feature_result["repository_substrate_proven"]
            and feature_result["context_frontier_proven"]
        ),
    }


def main() -> int:
    results = audit()
    print(json.dumps(results, indent=2, sort_keys=True))
    ready = all(results.values())
    print("READY" if ready else "NOT READY")
    return 0 if ready else 1


if __name__ == "__main__":
    sys.exit(main())
