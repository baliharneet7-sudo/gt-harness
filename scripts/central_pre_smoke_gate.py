#!/usr/bin/env python3
"""Fail-closed release gate for a paid central GT smoke dispatch.

This is deliberately narrower than the repository test suite.  It checks the
exact workflow that GitHub executes, invokes the census exactly as documented,
and exercises all 17 feature identities through the real agent loop with no
provider or task-container cost.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE_TESTS = (
    "tests/test_gt_central_runtime.py::test_effect_timing_consumes_evidence_before_the_next_action",
    "tests/test_gt_central_runtime.py::test_documented_direct_census_entrypoint_is_executable",
    "tests/test_gt_central_agent.py::test_paid_engine_workflow_has_no_additional_inner_model_time_censors",
    "tests/test_gt_central_agent.py::test_actual_agent_loop_routes_all_17_features_with_nonpredictive_effects",
    "tests/test_gt_central_agent.py::test_grounded_failure_warns_before_submit_without_holding_it",
    "tests/test_gt_central_agent.py::test_syntax_failure_does_not_interrupt_multi_action_batch",
    "tests/test_gt_preflight.py::test_validation_classification_applies_only_to_runner_segment",
    "tests/test_gt_preflight.py::test_sed_range_does_not_attach_across_non_pipeline_connector",
    "tests/test_gt_preflight.py::test_attached_output_redirection_is_classified_as_edit",
    "tests/test_gt_preflight.py::test_absent_output_target_is_expected_creation_and_preflight_passes",
    "tests/test_gt_preflight.py::test_absent_in_place_edit_target_fails_open_to_shell_postflight",
    "tests/test_provider_view.py::test_compiler_proves_existing_read_fact_at_exact_provider_message",
    "tests/test_provider_view.py::test_compiler_emits_missing_current_failure_but_not_private_revisions",
    "tests/test_gt_central_consumer_proof.py::test_context_compiler_accounts_every_effect_without_claiming_model_visibility",
    "tests/test_gt_deep_metrics.py::test_extract_trajectory_includes_outer_harbor_timeout_and_wall_time",
)


def run(label: str, *command: str) -> bool:
    print(f"== {label} ==")
    completed = subprocess.run(command, cwd=ROOT, check=False)
    if completed.returncode:
        print(f"FAILED: {label} (exit {completed.returncode})")
        return False
    print(f"PASSED: {label}")
    return True


def exact_commit_is_pushed() -> bool:
    """Fail closed unless tracked files match the pushed workflow commit."""

    print("== exact pushed commit ==")
    dirty = subprocess.run(
        ("git", "status", "--porcelain", "--untracked-files=no"),
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    branch = subprocess.run(
        ("git", "branch", "--show-current"),
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    ).stdout.strip()
    local = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    ).stdout.strip()
    remote = subprocess.run(
        ("git", "rev-parse", f"origin/{branch}"),
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    ).stdout.strip()
    approved = (
        dirty.returncode == 0
        and not dirty.stdout.strip()
        and bool(branch)
        and bool(local)
        and local == remote
    )
    print(f"branch={branch} local={local[:12]} origin={remote[:12]}")
    print("PASSED: exact pushed commit" if approved else "FAILED: exact pushed commit")
    return approved


def main() -> int:
    checks = (
        exact_commit_is_pushed(),
        run("strict agent lifecycle tests", sys.executable, "-m", "pytest", *RELEASE_TESTS, "-q"),
        run("documented direct census", sys.executable, "scripts/central_feature_census.py"),
        run("module census", sys.executable, "-m", "scripts.central_feature_census"),
        run("workflow/readiness audit", sys.executable, "scripts/central_readiness_audit.py"),
    )
    if all(checks):
        print("SMOKE_APPROVED")
        return 0
    print("SMOKE_BLOCKED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
