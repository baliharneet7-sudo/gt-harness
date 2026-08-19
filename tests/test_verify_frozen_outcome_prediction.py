import subprocess
from pathlib import Path

import pytest

from scripts.verify_frozen_outcome_prediction import (
    _validate_post_runtime_paths,
    _validate_release_freeze_paths,
    verify_release_manifest,
)


def test_checked_in_outcome_prediction_is_bound_to_repair20_profile() -> None:
    root = Path(__file__).resolve().parents[1]
    current = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    proof = verify_release_manifest(
        manifest_path=root / "eval/release/active_release.json",
        current_commit=current,
        root=root,
        expected_profile="repair20-v1",
    )
    assert proof["task_count"] == 20
    assert proof["prediction_before_outcome"] is True
    assert proof["outcome_run_executed"] is False


def test_final_freeze_rejects_runtime_changes_after_implementation_commit() -> None:
    with pytest.raises(ValueError, match="runtime or harness changed after prediction freeze"):
        _validate_post_runtime_paths(
            changed_paths=(
                "docs/benchmarks/prediction.json",
                "eval/gt_central_agent.py",
            ),
            allowed_paths=(
                "docs/benchmarks/prediction.json",
            ),
        )


def test_release_freeze_cannot_whitelist_runtime_or_workflow_changes() -> None:
    with pytest.raises(ValueError, match="only its manifest and prediction"):
        _validate_release_freeze_paths(
            manifest_relative="eval/release/active_release.json",
            prediction_relative="docs/benchmarks/prediction.json",
            allowed_paths=(
                "eval/release/active_release.json",
                "docs/benchmarks/prediction.json",
                "eval/gt_central_agent.py",
            ),
        )


def test_provider_free_checkout_supplies_history_required_by_freeze_verifier() -> None:
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/central_provider_free.yml").read_text(
        encoding="utf-8"
    )
    checkout = workflow.split("- uses: actions/checkout@v4", 1)[1].split(
        "- uses: actions/setup-python@v5", 1
    )[0]
    assert "fetch-depth: 0" in checkout


def test_release_manifest_rejects_selected_profile_drift() -> None:
    root = Path(__file__).resolve().parents[1]
    current = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    with pytest.raises(ValueError, match="selected profile disagrees"):
        verify_release_manifest(
            manifest_path=root / "eval/release/active_release.json",
            current_commit=current,
            root=root,
            expected_profile="regression-smoke-v1",
        )


def test_paid_workflow_cannot_disable_mandatory_replay_capture() -> None:
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/tb2_miniswe_central.yml").read_text(
        encoding="utf-8"
    )
    assert "REPLAY_CAPTURE: ${{ inputs.replay_capture }}" not in workflow
    assert '--ak enable_replay_capture="true"' in workflow


def test_release_identity_gates_provider_canary_and_paid_matrix() -> None:
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/tb2_miniswe_central.yml").read_text(
        encoding="utf-8"
    )
    release_job = workflow.index("  release_identity:")
    plan_job = workflow.index("  plan:")
    canary = workflow.index("Prove exact persistent bootstrap provider contract")
    task_job = workflow.index("  task:")

    assert release_job < plan_job < canary < task_job
    assert "needs: [resolve, provider_free, release_identity]" in workflow
    release_block = workflow[release_job:plan_job]
    assert "secrets." not in release_block
    assert "Verify canonical release identity before provider spend" in release_block
    assert "Verify exact provider-free certification identity" in release_block
    assert "CERTIFIED_COMMIT:" in release_block
    assert 'test "$MECHANICAL_STATUS" = "PASS"' in release_block
    canary_identity_block = workflow[
        workflow.index("      - id: canary_identity"):workflow.index(
            "      - name: Upload exact bootstrap proof"
        )
    ]
    assert "if-no-files-found" not in canary_identity_block
