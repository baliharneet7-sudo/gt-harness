import json
from pathlib import Path

from scripts.tb2_regression_forensics import build_regression_forensics

ROOT = Path(__file__).resolve().parents[1]


def test_run_320_forensics_preserves_exact_gain_and_loss_sets():
    baseline = json.loads(
        (ROOT / "eval/frozen_baselines/tb2_miniswe_20260731.json").read_text(
            encoding="utf-8"
        )
    )
    treatment = json.loads(
        (ROOT / "tests/fixtures/tb2_run_32047133236_treatment.json").read_text(
            encoding="utf-8"
        )
    )

    report = build_regression_forensics(baseline, treatment)

    assert report["passed"] is True
    assert report["positive_flips"] == [
        "count-dataset-tokens",
        "largest-eigenval",
    ]
    assert report["negative_flips"] == [
        "extract-elf",
        "sanitize-git-repo",
        "torch-tensor-parallelism",
        "video-processing",
        "write-compressor",
    ]
    loss = next(row for row in report["rows"] if row["task"] == "extract-elf")
    assert loss["attribution"] == "unknown_missing_trajectory"
    assert "verifier tests" in report["integrity_boundary"]


def test_forensics_rejects_treatment_task_hash_drift():
    baseline = json.loads(
        (ROOT / "eval/frozen_baselines/tb2_miniswe_20260731.json").read_text(
            encoding="utf-8"
        )
    )
    treatment = json.loads(
        (ROOT / "tests/fixtures/tb2_run_32047133236_treatment.json").read_text(
            encoding="utf-8"
        )
    )
    treatment["manifest"]["task_set_sha256"] = "0" * 64

    report = build_regression_forensics(baseline, treatment)

    assert report["passed"] is False
    assert "treatment_task_set_hash_mismatch" in report["failures"]
