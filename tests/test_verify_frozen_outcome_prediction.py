import subprocess
from pathlib import Path

from scripts.verify_frozen_outcome_prediction import verify


def test_checked_in_outcome_prediction_is_bound_to_repair20_profile() -> None:
    root = Path(__file__).resolve().parents[1]
    current = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    proof = verify(
        prediction_path=root
        / "docs/benchmarks/GT_FINAL_20_TASK_OUTCOME_PREDICTION_2026-08-18.json",
        baseline_path=root / "eval/frozen_baselines/tb2_miniswe_20260731.json",
        profile_id="repair20-v1",
        current_commit=current,
    )
    assert proof["task_count"] == 20
    assert proof["prediction_before_outcome"] is True
    assert proof["outcome_run_executed"] is False
