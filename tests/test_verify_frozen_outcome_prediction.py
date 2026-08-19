import subprocess
from pathlib import Path

import pytest

from scripts.verify_frozen_outcome_prediction import (
    _validate_post_runtime_paths,
    verify,
)


def test_checked_in_outcome_prediction_is_bound_to_repair20_profile() -> None:
    root = Path(__file__).resolve().parents[1]
    current = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    proof = verify(
        prediction_path=root
        / "docs/benchmarks/GT_FINAL_20_TASK_OUTCOME_PREDICTION_2026-08-19_V2.json",
        baseline_path=root / "eval/frozen_baselines/tb2_miniswe_20260731.json",
        profile_id="repair20-v1",
        current_commit=current,
    )
    assert proof["task_count"] == 20
    assert proof["prediction_before_outcome"] is True
    assert proof["outcome_run_executed"] is False


def test_final_freeze_rejects_runtime_changes_after_implementation_commit() -> None:
    with pytest.raises(ValueError, match="runtime or harness changed after prediction freeze"):
        _validate_post_runtime_paths(
            changed_paths=(
                "docs/benchmarks/GT_FINAL_20_TASK_OUTCOME_PREDICTION_2026-08-19_V2.json",
                "eval/gt_central_agent.py",
            ),
            allowed_paths=(
                "docs/benchmarks/GT_FINAL_20_TASK_OUTCOME_PREDICTION_2026-08-19_V2.json",
            ),
        )
