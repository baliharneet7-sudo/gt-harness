#!/usr/bin/env python3
"""Provider-free structural gate for the host-owned central runtime.

This gate proves the isolation architecture and stock tool contract.  It does
not claim model efficacy or replace the live task-container surface audit.
"""

from __future__ import annotations

import inspect
import importlib.util
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
    workflow = (ROOT / ".github/workflows/tb2_miniswe_engine.yml").read_text(encoding="utf-8")
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
        "preflight_default_is_off": agent.preflight_mode is PreflightMode.OFF,
        "paid_preflight_is_shadow_only": (
            "--ak preflight_mode=shadow" in workflow
            and "--ak enable_preflight=true" not in workflow
        ),
        "paid_integration_mode_is_explicit_active": "--ak integration_mode=active" in workflow,
        "one_switch_off_is_provider_neutral": (
            GTIntegrationMode.OFF.value == "off"
            and "transform=False" in run_source
            and "self.integration_mode is GTIntegrationMode.OFF" in source
        ),
        "provider_free_gate_covers_preflight": "tests/test_gt_preflight.py" in workflow,
        "provider_free_gate_covers_context_compiler": (
            "tests/test_provider_view.py" in workflow
            and "tests/test_gt_deep_metrics.py" in workflow
        ),
        "paid_deterministic_compaction_enabled": (
            "--ak enable_context_compaction=true" in workflow
            and "tests/test_provider_view.py" in workflow
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
        "validation_status_is_attributed_not_outer_rc_only": (
            "status_attributed=True" in validation_source
            and "later_shell_segment_owns_action_status" in validation_source
            and "classification.status is ValidationStatus.PASS" in observation_source
            and "classification.status is ValidationStatus.FAIL" in observation_source
        ),
        "typed_proposal_precedes_environment_exec": (
            0
            <= run_source.find("adapt_proposed_action(")
            < run_source.find("await environment.exec(")
        ),
        "task_exec_env_is_empty": "env={}," in source,
        "treatment_workflow_central": (
            'AGENT="eval.gt_central_agent:MiniSweCentralAgent"' in workflow
        ),
        "shadow_workflow_central": "MiniSweCentralShadowAgent" in workflow,
        "custom_agent_uses_import_path": '--agent-import-path "$AGENT"' in workflow,
        "frozen_miniswe_version": '"mini-swe-agent==2.2.8"' in workflow,
        "legacy_agent_not_in_paid_workflow": (
            "eval.miniswe_agent:MiniSweEngineAgent" not in workflow
        ),
        "paid_exact_harbor_deadline_is_propagated": (
            "--ak enable_lint=true --ak enable_submit_readiness=true" in workflow
            and "scripts/resolve_harbor_budget.py" in workflow
            and '--ak execution_budget_sec="$EXECUTION_BUDGET"' in workflow
            and "--agent-timeout-multiplier 1.0" in workflow
            and "--ak model_timeout_sec" not in workflow
            and "--ak model_loop_timeout_sec" not in workflow
        ),
        "paid_completion_and_progress_control_enabled": (
            "--ak enable_completion_controller=true" in workflow
            and "--ak enable_progress_control=true" in workflow
            and "tests/test_gt_completion.py" in workflow
            and "tests/test_harbor_budget.py" in workflow
        ),
        "central_features_consumer_paths_proven": bool(
            feature_result["all_17_consumer_paths_proven"]
        ),
        "all_effects_context_accounted": bool(
            feature_result["all_effects_context_accounted"]
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
