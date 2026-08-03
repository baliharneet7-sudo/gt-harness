from __future__ import annotations

import pytest

from gt_engine.experiment import (
    BASELINE_ACTIONS,
    BASELINE_SOLVED,
    BASELINE_TOKENS,
    TrialRecord,
    assess_release,
    deterministic_arm,
    select_eligible_panel,
)


def test_assignment_is_stable_and_uses_both_gt_on_arms():
    first = deterministic_arm("task-a", 1, "lint", "v1", "seed")
    second = deterministic_arm("task-a", 1, "lint", "v1", "seed")
    arms = {
        deterministic_arm(f"task-{i}", 1, "lint", "v1", "seed")
        for i in range(100)
    }

    assert first == second
    assert arms == {"shadow", "treatment"}


def test_eligible_panel_is_deterministic_and_severity_ranked():
    events = {f"task-{i:02d}": float(i) for i in range(40)}

    panel = select_eligible_panel(events, minimum=20, maximum=30)

    assert len(panel) == 30
    assert panel[0] == "task-39"
    assert panel[-1] == "task-10"


def test_too_few_eligible_tasks_stays_shadow_only():
    assert select_eligible_panel({"a": 2.0, "b": 1.0}, minimum=20) == ()


def test_release_gate_accepts_clear_pareto_improvement():
    baseline = {
        f"task-{i:02d}": TrialRecord(
            task=f"task-{i:02d}",
            trial=0,
            arm="baseline",
            solved=i < BASELINE_SOLVED,
            tokens=BASELINE_TOKENS / 89,
            actions=BASELINE_ACTIONS / 89,
            errored=i < 4,
        )
        for i in range(89)
    }
    candidate = [
        TrialRecord(
            task=f"task-{i:02d}",
            trial=trial,
            arm="treatment",
            solved=i < 75,
            tokens=(BASELINE_TOKENS * 0.70) / 89,
            actions=(BASELINE_ACTIONS * 0.70) / 89,
            errored=False,
        )
        for trial in range(1, 6)
        for i in range(89)
    ]

    result = assess_release(
        baseline,
        candidate,
        bootstrap_samples=2_000,
        seed=7,
        runtime_errors=0,
        permanently_blocked_submissions=0,
    )

    assert result.passed is True
    assert result.mean_solved >= 72
    assert result.mean_tokens <= BASELINE_TOKENS * 0.85
    assert result.mean_actions <= BASELINE_ACTIONS * 0.85


def test_release_gate_rejects_efficiency_or_reliability_regression():
    baseline = {
        f"task-{i:02d}": TrialRecord(
            task=f"task-{i:02d}",
            trial=0,
            arm="baseline",
            solved=i < BASELINE_SOLVED,
            tokens=BASELINE_TOKENS / 89,
            actions=BASELINE_ACTIONS / 89,
            errored=i < 4,
        )
        for i in range(89)
    }
    candidate = [
        TrialRecord(
            task=f"task-{i:02d}",
            trial=trial,
            arm="treatment",
            solved=i < 75,
            tokens=(BASELINE_TOKENS * 1.10) / 89,
            actions=(BASELINE_ACTIONS * 1.10) / 89,
            errored=i < 5,
        )
        for trial in range(1, 6)
        for i in range(89)
    ]

    result = assess_release(baseline, candidate, bootstrap_samples=500, seed=9)

    assert result.passed is False
    assert "tokens" in result.failures
    assert "actions" in result.failures
    assert "errors" in result.failures


def test_release_gate_rejects_duplicate_trial_ids_within_a_task():
    baseline = {
        f"task-{i:02d}": TrialRecord(
            task=f"task-{i:02d}",
            trial=0,
            arm="baseline",
            solved=i < BASELINE_SOLVED,
            tokens=BASELINE_TOKENS / 89,
            actions=BASELINE_ACTIONS / 89,
        )
        for i in range(89)
    }
    candidate = [
        TrialRecord(
            task=f"task-{i:02d}",
            trial=(1 if i == 0 and trial == 2 else trial),
            arm="treatment",
            solved=i < 75,
            tokens=(BASELINE_TOKENS * 0.70) / 89,
            actions=(BASELINE_ACTIONS * 0.70) / 89,
        )
        for trial in range(1, 6)
        for i in range(89)
    ]

    with pytest.raises(ValueError, match="same five unique trials"):
        assess_release(baseline, candidate, bootstrap_samples=100)
