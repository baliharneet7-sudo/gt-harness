from __future__ import annotations

import json
from pathlib import Path

from scripts.build_regression_smoke_manifest import build_manifest


def _write(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_manifest_derives_regressions_gains_and_controls(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    previous = tmp_path / "previous.json"
    _write(
        baseline,
        {
            "rows": [
                {"task": "regression", "solved": True},
                {"task": "gain", "solved": False},
                {"task": "control-a", "solved": True},
                {"task": "control-b", "solved": True},
            ]
        },
    )
    _write(
        previous,
        {
            "rows": [
                {"task": "regression", "solved": False},
                {"task": "gain", "solved": True},
                {"task": "control-a", "solved": True},
                {"task": "control-b", "solved": True},
            ]
        },
    )

    result = build_manifest(
        baseline_path=baseline,
        previous_path=previous,
        stable_control_count=1,
    )

    assert result["regressions"] == ["regression"]
    assert result["positive_flips"] == ["gain"]
    assert result["stable_controls"] == ["control-a"]
    assert result["tasks"] == ["regression", "gain", "control-a"]
    assert result["outcome_run_executed"] is False


def test_manifest_reads_previous_trial_results(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    previous = tmp_path / "previous.json"
    _write(baseline, {"rows": [{"task": "task", "solved": True}]})
    _write(
        previous,
        {
            "trial_results": [
                {"task_name": "task", "verifier_result": {"rewards": {"reward": 0}}}
            ]
        },
    )

    result = build_manifest(
        baseline_path=baseline,
        previous_path=previous,
        stable_control_count=0,
    )

    assert result["regressions"] == ["task"]
