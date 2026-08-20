#!/usr/bin/env python3
"""Authoritative no-spend configuration gate for the final GT treatment."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.documentation_consistency_audit import audit_documentation  # noqa: E402
from scripts.release_manifest import (  # noqa: E402
    ACTIVE_RELEASE_PATH,
    load_release_manifest,
)
from scripts.render_treatment_agent_args import build_runtime_arguments  # noqa: E402
from scripts.verify_frozen_outcome_prediction import (  # noqa: E402
    verify_release_manifest,
)

_REQUIRED_RUNTIME = {
    "integration_mode": "active",
    "policy_mode": "certified_active",
    "preflight_mode": "assistive_safe",
    "require_graph_ready": True,
    "enable_all_features": True,
    "enable_repository_intelligence": True,
    "enable_persistent_execution_state": True,
    "enable_preemptive_retrieval": True,
    "enable_relational_context": True,
    "enable_semantic_evidence": True,
    "enable_decision_sufficiency": True,
    "enable_replay_capture": True,
    "retrieval_delivery_mode": "integrated_same_observation",
    "persistent_state_selection_mode": "deterministic_v1",
}

_REQUIRED_TASK_CHECKS = (
    "treatment_runtime_identity",
    "repository_substrate",
    "dense_backend",
    "delivery_timing_accounting",
    "contribution_budget",
    "provider_value_contract",
    "action_lifecycle",
    "deterministic_task_controls",
    "preflight_precision",
    "decision_sufficiency",
    "persistent_execution_state",
    "repository_context_state",
    "product_mechanism_census",
    "outcome_preservation_controls",
    "project_validation",
    "terminal_validation_state",
    "retrieval_efficiency",
    "replay_and_intervention_audit",
    "task_artifact_integrity",
    "mechanical_completeness_runtime",
)

_REQUIRED_DOCS = (
    "docs/GT_MECHANICAL_COMPLETENESS_CONTRACT.md",
    "docs/GT_RELEASE_DOSSIER.md",
    "docs/gt_gitnexus_program/01_GT_CURRENT_ARCHITECTURE.md",
    "docs/gt_gitnexus_program/03_GT_FEATURE_LEDGER.md",
    "docs/gt_gitnexus_program/07_GITNEXUS_ARCHITECTURE.md",
    "docs/gt_gitnexus_program/09_GITNEXUS_DELIVERY_AND_LIFECYCLE.md",
    "docs/gt_gitnexus_program/11_GT_VS_GITNEXUS_CAPABILITY_MATRIX.md",
    "docs/gt_gitnexus_program/12_FAILURE_TO_MECHANISM_MATRIX.md",
    "docs/gt_gitnexus_program/14_IMPLEMENTATION_PLAN.md",
    "docs/gt_gitnexus_program/15_20_TASK_RERUN_REPORT.md",
    "docs/gt_gitnexus_program/20_FINAL_REGRESSION_CONTROL_AND_BENCHMARK_READINESS.md",
)


def _check(name: str, passed: bool, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "evidence": evidence}


def audit_configuration(
    root: Path,
    *,
    paid_workflow_path: Path | None = None,
    provider_free_workflow_path: Path | None = None,
    treatment_path: Path | None = None,
) -> dict[str, Any]:
    """Audit immutable configuration without making a provider call."""

    root = root.resolve()
    release = load_release_manifest(root / ACTIVE_RELEASE_PATH, root=root)
    paid_path = paid_workflow_path or root / ".github/workflows/tb2_miniswe_central.yml"
    provider_path = (
        provider_free_workflow_path
        or root / ".github/workflows/central_provider_free.yml"
    )
    selected_treatment_path = treatment_path or release.treatment_path
    paid = paid_path.read_text(encoding="utf-8")
    provider_free = provider_path.read_text(encoding="utf-8")
    treatment = json.loads(selected_treatment_path.read_text(encoding="utf-8"))
    runtime = build_runtime_arguments(
        treatment,
        source_sha=release.runtime_commit,
        max_steps=100,
    )["agent_kwargs"]
    release_gate_source = (root / "scripts/central_release_gate.py").read_text(
        encoding="utf-8"
    )
    agent_source = (root / "eval/gt_central_agent.py").read_text(encoding="utf-8")
    documentation = audit_documentation(root)

    checks = [
        _check(
            "canonical_task_profile",
            release.task_profile == "repair20-v1"
            and "options: [repair20-v1]" in paid
            and "regression-smoke-v1" not in paid,
            {"task_profile": release.task_profile},
        ),
        _check(
            "final_treatment_contract",
            treatment.get("profile_id") == "central_relational_v2"
            and all(runtime.get(key) == value for key, value in _REQUIRED_RUNTIME.items()),
            {
                "profile_id": treatment.get("profile_id"),
                "required_runtime": _REQUIRED_RUNTIME,
            },
        ),
        _check(
            "paid_dispatch_interlock",
            "needs: [resolve, provider_free, release_identity]" in paid
            and "Verify canonical release identity before provider spend" in paid
            and "Verify exact provider-free certification identity" in paid
            and 'enable_replay_capture="true"' in paid
            and "inputs.replay_capture" not in paid
            and "REPLAY_CAPTURE:" not in paid,
            {
                "release_identity_precedes_plan": (
                    paid.index("release_identity:") < paid.index("plan:")
                )
            },
        ),
        _check(
            "provider_free_is_provider_free",
            all(
                secret not in provider_free
                for secret in (
                    "OPENAI_API_KEY",
                    "DEEPSEEK_API_KEY",
                    "ANTHROPIC_API_KEY",
                )
            )
            and "python -m scripts.central_bootstrap_canary" not in provider_free
            and "python scripts/central_bootstrap_canary" not in provider_free
            and "fetch-depth: 0" in provider_free
            and "timeout-minutes:" not in provider_free,
            {"provider_credentials_declared": False},
        ),
        _check(
            "live_provider_barrier",
            "evaluate_provider_barrier(" in agent_source
            and 'terminal = "MechanicalCompletenessBlocked"' in agent_source
            and '"task_execution_certificate"' in agent_source,
            {"barrier_before_provider_query": True},
        ),
        _check(
            "terminal_task_check_surface",
            all(f'"{name}"' in release_gate_source for name in _REQUIRED_TASK_CHECKS)
            and "_task_execution_certificate" in release_gate_source,
            {"required_checks": list(_REQUIRED_TASK_CHECKS)},
        ),
        _check(
            "provider_free_test_surface",
            all(
                item in provider_free
                for item in (
                    "tests/test_mechanical_completeness.py",
                    "tests/test_mechanical_completeness_gate.py",
                    "tests/test_release_manifest.py",
                    "tests/test_verify_frozen_outcome_prediction.py",
                    "gt_engine/mechanical_completeness.py",
                    "scripts/mechanical_completeness_gate.py",
                )
            ),
            {"mutation_sensitive": True},
        ),
        _check(
            "release_documentation",
            all((root / path).is_file() for path in _REQUIRED_DOCS)
            and documentation["status"] == "PASS",
            {
                "required_documents": list(_REQUIRED_DOCS),
                "audit": documentation,
            },
        ),
    ]
    failures = [check["name"] for check in checks if not check["passed"]]
    return {
        "schema": "gt.mechanical_completeness_configuration.v1",
        "status": "PASS" if not failures else "BLOCKED",
        "release_id": release.release_id,
        "task_profile": release.task_profile,
        "runtime_commit": release.runtime_commit,
        "checks": checks,
        "failures": failures,
    }


def _head(root: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()


def _tracked_worktree_changes(root: Path) -> tuple[str, ...]:
    """Return tracked changes that are invisible to commit-based release proof."""

    completed = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return tuple(line.rstrip() for line in completed.stdout.splitlines() if line.strip())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=Path("mechanical-completeness.json"))
    args = parser.parse_args()
    root = args.root.resolve()
    report = audit_configuration(root)
    try:
        tracked_changes = _tracked_worktree_changes(root)
        report["worktree_identity"] = {
            "clean": not tracked_changes,
            "tracked_change_count": len(tracked_changes),
            "tracked_changes": list(tracked_changes),
        }
        if tracked_changes:
            report["status"] = "BLOCKED"
            report["failures"] = [
                *report["failures"],
                "tracked_worktree_not_clean",
            ]
            raise ValueError(
                "tracked worktree changes are not bound to the release commit"
            )
        report["release_identity_proof"] = verify_release_manifest(
            manifest_path=root / ACTIVE_RELEASE_PATH,
            current_commit=_head(root),
            root=root,
            expected_profile="repair20-v1",
        )
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        report["status"] = "BLOCKED"
        report["failures"] = [
            *report["failures"],
            "release_identity_proof",
        ]
        report["release_identity_error"] = str(exc)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    if report["status"] != "PASS":
        return 2
    print("GT_MECHANICAL_COMPLETENESS=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
