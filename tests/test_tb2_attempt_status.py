import json
from pathlib import Path

from scripts.tb2_attempt_status import classify_attempt


def _attempt(root: Path, *, reward=None, exception="", assistant=False) -> None:
    trial = root / "job" / "task__trial"
    (trial / "agent").mkdir(parents=True)
    payload = {
        "task_name": "task",
        "trial_name": "task__trial",
        "verifier_result": ({"rewards": {"reward": reward}} if reward is not None else None),
        "exception_info": ({"exception_type": exception} if exception else None),
    }
    (trial / "result.json").write_text(json.dumps(payload), encoding="utf-8")
    messages = [{"role": "user", "content": "task"}]
    if assistant:
        messages.append({"role": "assistant", "content": "action"})
    (trial / "agent" / "miniswe_trajectory.json").write_text(
        json.dumps({"messages": messages}), encoding="utf-8"
    )


def test_transient_provider_failure_before_first_action_is_retryable(tmp_path: Path) -> None:
    _attempt(tmp_path, exception="BadGatewayError")
    result = classify_attempt(tmp_path, "task")
    assert result["retryable"] is True
    assert result["reason"] == "transient_provider_before_first_action"


def test_official_zero_reward_is_final(tmp_path: Path) -> None:
    _attempt(tmp_path, reward=0)
    result = classify_attempt(tmp_path, "task")
    assert result["state"] == "graded"
    assert result["reward"] == 0
    assert result["retryable"] is False


def test_provider_failure_after_an_action_is_not_retried(tmp_path: Path) -> None:
    _attempt(tmp_path, exception="BadGatewayError", assistant=True)
    result = classify_attempt(tmp_path, "task")
    assert result["retryable"] is False


def test_missing_trial_is_not_retried(tmp_path: Path) -> None:
    result = classify_attempt(tmp_path, "task")
    assert result["retryable"] is False
    assert result["reason"] == "trial_result_missing"


def test_baseline_workflow_keeps_gt_off_and_requires_complete_grading() -> None:
    workflow = Path(".github/workflows/tb2_miniswe_baseline_matrix.yml").read_text(
        encoding="utf-8"
    )
    assert "eval.miniswe_agent:MiniSweAgent" in workflow
    assert "eval.miniswe_agent:MiniSweGtAgent" not in workflow
    assert 'default: "5.0"' in workflow
    assert "scripts.tb2_attempt_status" in workflow
    assert "scripts.benchmark_progress emit-harbor" in workflow
    assert "Require an official grade for every planned task" in workflow
