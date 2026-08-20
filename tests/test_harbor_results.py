from __future__ import annotations

import json

from scripts.harbor_results import collect_harbor_results
from scripts.stage_harbor_artifacts import stage_harbor_artifacts


def _trial(task: str, reward: float) -> dict:
    return {
        "task_name": task,
        "trial_name": f"{task}__trial",
        "verifier_result": {"rewards": {"reward": reward}},
    }


def test_loader_merges_aggregate_and_top_level_trials_without_double_counting(tmp_path):
    shard = tmp_path / "shard-1"
    shard.mkdir()
    alpha = _trial("alpha", 1.0)
    beta = _trial("beta", 0.0)
    (shard / "aggregate-result.json").write_text(
        json.dumps({"trial_results": [alpha]}), encoding="utf-8"
    )
    (shard / "alpha-result.json").write_text(json.dumps(alpha), encoding="utf-8")
    (shard / "beta-result.json").write_text(json.dumps(beta), encoding="utf-8")

    result = collect_harbor_results(tmp_path, expected_tasks=("alpha", "beta"))

    assert [row["task_name"] for row in result.trials] == ["alpha", "beta"]
    assert result.solved_tasks == ("alpha",)
    assert result.missing_tasks == ()
    assert result.failures == ()
    assert result.duplicate_identical_rows == 1


def test_loader_fails_closed_on_conflicting_duplicate_task_rows(tmp_path):
    shard = tmp_path / "shard-1"
    shard.mkdir()
    (shard / "first-result.json").write_text(
        json.dumps(_trial("alpha", 1.0)), encoding="utf-8"
    )
    (shard / "second-result.json").write_text(
        json.dumps(_trial("alpha", 0.0)), encoding="utf-8"
    )

    result = collect_harbor_results(tmp_path, expected_tasks=("alpha",))

    assert result.trials == ()
    assert result.failures == ("conflicting_trial_result:alpha",)


def test_loader_reports_exact_missing_expected_tasks(tmp_path):
    shard = tmp_path / "shard-1"
    shard.mkdir()
    (shard / "alpha-result.json").write_text(
        json.dumps(_trial("alpha", 1.0)), encoding="utf-8"
    )

    result = collect_harbor_results(tmp_path, expected_tasks=("alpha", "beta"))

    assert result.missing_tasks == ("beta",)
    assert "missing_expected_task:beta" in result.failures


def test_loader_does_not_call_a_graded_nonzero_agent_exit_censored(tmp_path):
    shard = tmp_path / "shard-1"
    shard.mkdir()
    row = _trial("alpha", 1.0)
    row["exception_info"] = {
        "exception_type": "NonZeroAgentExitCodeError",
        "exception_message": "agent returned exit code 5 after submit",
    }
    (shard / "alpha-result.json").write_text(json.dumps(row), encoding="utf-8")

    result = collect_harbor_results(tmp_path, expected_tasks=("alpha",))

    assert result.solved_tasks == ("alpha",)
    assert result.errored_tasks == ()
    assert result.as_dict()["n_graded"] == 1


def test_loader_rejects_job_summary_as_a_trial(tmp_path):
    (tmp_path / "result.json").write_text(
        json.dumps({"stats": {"n_trials": 1}}), encoding="utf-8"
    )

    result = collect_harbor_results(tmp_path, expected_tasks=("alpha",))

    assert result.trials == ()
    assert result.ignored_job_results == 1
    assert result.failures == ("missing_expected_task:alpha",)


def test_artifact_stage_copies_and_certifies_expected_trial(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "target"
    trial_dir = source / "alpha__trial"
    trial_dir.mkdir(parents=True)
    (trial_dir / "result.json").write_text(
        json.dumps(_trial("alpha", 1.0)), encoding="utf-8"
    )
    (trial_dir / "miniswe_trajectory.json").write_text("{}", encoding="utf-8")

    manifest = stage_harbor_artifacts(
        source, target, expected_tasks=("alpha",)
    )

    assert manifest["status"] == "PASS"
    assert manifest["result_collection"]["n_trials"] == 1
    assert (target / "alpha__trial" / "miniswe_trajectory.json").exists()
