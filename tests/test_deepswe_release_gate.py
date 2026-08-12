from scripts.deepswe_release_gate import assess_deepswe_release

IDENTITY = {
    "benchmark_sha": "b" * 40,
    "model": "deepseek/deepseek-v4-flash",
    "provider": "openrouter:deepseek:only:no-fallback",
    "temperature": 1.0,
    "step_limit": 300,
    "execution_budget_sec": 5400,
    "runner": "datacurve-pier==0.3.1",
}


def _arm(rows, *, gt_commit=""):
    return {
        "schema": "gt.deepswe.central.evaluation.v1.1",
        "manifest": {**IDENTITY, "gt_commit": gt_commit},
        "rows": rows,
    }


def _row(task, solved, *, tokens, calls, actions, cost=0.0, exception=None):
    return {
        "task": task,
        "solved": solved,
        "exception": exception,
        "total_tokens": tokens,
        "provider_calls": calls,
        "decision_actions": actions,
        "provider_cost_usd": cost,
    }


def test_preservation_gate_requires_every_baseline_solve_and_no_resource_expansion():
    baseline = _arm(
        [
            _row("kept", True, tokens=100, calls=10, actions=12),
            _row("flip", False, tokens=90, calls=9, actions=10),
        ]
    )
    treatment = _arm(
        [
            _row("kept", True, tokens=90, calls=9, actions=11),
            _row("flip", False, tokens=80, calls=8, actions=9),
        ],
        gt_commit="a" * 40,
    )

    report = assess_deepswe_release(baseline, treatment, phase="preservation")

    assert report.passed is True
    assert report.losses == ()
    assert report.common_solved_deltas == {
        "total_tokens": -10.0,
        "provider_calls": -1.0,
        "decision_actions": -1.0,
        "provider_cost_usd": 0.0,
    }


def test_preservation_gate_rejects_one_loss_even_when_aggregate_is_lower():
    baseline = _arm(
        [
            _row("lost", True, tokens=1000, calls=50, actions=60),
            _row("kept", True, tokens=1000, calls=50, actions=60),
        ]
    )
    treatment = _arm(
        [
            _row("lost", False, tokens=1, calls=1, actions=1),
            _row("kept", True, tokens=10, calls=2, actions=3),
        ],
        gt_commit="a" * 40,
    )

    report = assess_deepswe_release(baseline, treatment, phase="preservation")

    assert report.passed is False
    assert report.losses == ("lost",)
    assert "baseline_solve_regression:lost" in report.failures


def test_promotion_gate_requires_a_flip_and_strictly_more_solved_tasks():
    baseline = _arm(
        [
            _row("kept", True, tokens=100, calls=10, actions=10),
            _row("flip", False, tokens=80, calls=8, actions=8),
        ]
    )
    treatment = _arm(
        [
            _row("kept", True, tokens=90, calls=9, actions=9),
            _row("flip", True, tokens=120, calls=12, actions=12),
        ],
        gt_commit="a" * 40,
    )

    report = assess_deepswe_release(baseline, treatment, phase="promotion")

    assert report.passed is True
    assert report.flips == ("flip",)
    assert report.baseline_solved == 1
    assert report.treatment_solved == 2


def test_gate_rejects_censored_reward_and_manifest_mismatch():
    baseline = _arm([_row("task", True, tokens=100, calls=10, actions=10)])
    treatment = _arm(
        [
            _row(
                "task",
                True,
                tokens=90,
                calls=9,
                actions=9,
                exception={"type": "AgentTimeoutError"},
            )
        ],
        gt_commit="a" * 40,
    )
    treatment["manifest"]["model"] = "different-model"

    report = assess_deepswe_release(baseline, treatment, phase="preservation")

    assert report.passed is False
    assert "manifest_mismatch:model" in report.failures
    assert "censored_treatment:task" in report.failures


def test_gate_fails_closed_on_missing_metric_or_task_mismatch():
    baseline = _arm([_row("task", True, tokens=100, calls=10, actions=10)])
    treatment = _arm(
        [_row("other", True, tokens=90, calls=9, actions=9)],
        gt_commit="a" * 40,
    )
    treatment["rows"][0].pop("decision_actions")

    report = assess_deepswe_release(baseline, treatment, phase="preservation")

    assert report.passed is False
    assert "task_set_mismatch" in report.failures
    assert "missing_metric:other:decision_actions" in report.failures
