from pathlib import Path


WORKFLOW = Path(__file__).parents[1] / ".github/workflows/swebench_live_lite_full.yml"


def _workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_model_and_task_cross_docker_boundary_as_environment() -> None:
    text = _workflow()
    assert 'bash -c "$(cat <<\'GT_CONTAINER_SCRIPT\'' in text
    assert "GT_CONTAINER_SCRIPT\n          )\" 2>&1 | tee -a trial_output.log" in text
    assert '-e GT_INPUT_MODEL="$INPUT_MODEL"' in text
    assert '-e GT_INPUT_TASK="$MTASK"' in text
    assert 'export GT_RUN_MODEL="$GT_INPUT_MODEL"' in text
    assert 'GT_PRO_MODEL="$GT_INPUT_MODEL"' in text
    assert 'GT_PRO_INSTANCE_ID="$GT_INPUT_TASK"' in text
    assert '"\'"$INPUT_MODEL"\'"' not in text


def test_task_execution_has_no_nonofficial_wall_cap() -> None:
    text = _workflow()
    assert "timeout --signal=" not in text
    assert "timeout-minutes:" not in text
    assert 'step_limit: 150' in (
        Path(__file__).parents[1]
        / "artifact_deepswe/gt_integration/deepswe_gt_pier_baseline.yaml"
    ).read_text(encoding="utf-8")
    assert "--timeout 1800" in text  # official evaluator timeout only
