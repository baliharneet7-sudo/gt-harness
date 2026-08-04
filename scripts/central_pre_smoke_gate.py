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
    "tests/test_gt_central_agent.py::test_paid_engine_workflow_keeps_provider_timeout_below_loop_budget",
    "tests/test_gt_central_agent.py::test_actual_agent_loop_routes_all_17_features_with_nonpredictive_effects",
    "tests/test_gt_central_agent.py::test_grounded_failure_warns_before_submit_without_holding_it",
    "tests/test_gt_central_agent.py::test_syntax_failure_does_not_interrupt_multi_action_batch",
)


def run(label: str, *command: str) -> bool:
    print(f"== {label} ==")
    completed = subprocess.run(command, cwd=ROOT, check=False)
    if completed.returncode:
        print(f"FAILED: {label} (exit {completed.returncode})")
        return False
    print(f"PASSED: {label}")
    return True


def main() -> int:
    checks = (
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
