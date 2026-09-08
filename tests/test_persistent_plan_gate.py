"""The completion gate: refuses once, escapes on budget, never blocks blindly."""
from __future__ import annotations

import pytest

from gt_engine.persistent_plan import PersistentPlan, PlanInputs, PlanRow
from gt_engine.persistent_plan.anchors import AnchorResult
from gt_engine.persistent_plan.baseline import BaselineResult
from gt_engine.persistent_plan.gate import (
    MIN_REMAINING_SECONDS,
    MIN_REMAINING_STEPS,
    budget_allows_refusal,
    decide,
    render_directive,
)
from gt_engine.persistent_plan.ledger import build_requirement_ledger

AMPLE = {"remaining_seconds": 3000.0, "remaining_steps": 200}


def _plan(rows=("req-a", "req-b")) -> PersistentPlan:
    inputs = PlanInputs(
        ledger=build_requirement_ledger(""),
        anchors=AnchorResult(),
        baseline=BaselineResult(status="captured", passed=10, command=("pytest",)),
    )
    return PersistentPlan(
        status="READY",
        inputs=inputs,
        rows=tuple(
            PlanRow(
                row_id=row_id,
                text=f"requirement {row_id}",
                verification_command=f"pytest -k {row_id}",
            )
            for row_id in rows
        ),
    )


def test_a_complete_plan_is_accepted():
    decision = decide(
        plan=_plan(), unmet_rows=(), regressions=(), refusals=0, **AMPLE
    )
    assert decision.accepted
    assert decision.reason == "complete"


def test_unmet_rows_refuse_once_when_there_is_room():
    decision = decide(
        plan=_plan(), unmet_rows=("req-a",), regressions=(), refusals=0, **AMPLE
    )
    assert not decision.accepted
    assert decision.reason == "unmet_plan_rows"
    assert "req-a" in decision.directive
    assert "pytest -k req-a" in decision.directive


def test_the_second_submit_is_always_accepted():
    """The gate is a reminder, not a cage."""
    decision = decide(
        plan=_plan(), unmet_rows=("req-a",), regressions=(), refusals=1, **AMPLE
    )
    assert decision.accepted
    assert decision.reason == "already_refused_once"


def test_low_time_escapes_rather_than_forcing_a_timeout():
    """A refusal near the deadline converts a near-miss into a zero."""
    decision = decide(
        plan=_plan(), unmet_rows=("req-a",), regressions=(), refusals=0,
        remaining_seconds=MIN_REMAINING_SECONDS - 1, remaining_steps=200,
    )
    assert decision.accepted
    assert decision.reason == "budget_escape"
    assert decision.escaped == "time"


def test_low_steps_escapes_too():
    decision = decide(
        plan=_plan(), unmet_rows=("req-a",), regressions=(), refusals=0,
        remaining_seconds=3000.0, remaining_steps=MIN_REMAINING_STEPS - 1,
    )
    assert decision.accepted
    assert decision.escaped == "steps"


def test_a_baseline_regression_alone_refuses():
    decision = decide(
        plan=_plan(), unmet_rows=(), regressions=("tests/test_x.py::test_y",),
        refusals=0, **AMPLE,
    )
    assert not decision.accepted
    assert decision.reason == "baseline_regression"
    assert "tests/test_x.py::test_y" in decision.directive
    assert "green when you arrived" in decision.directive


def test_no_plan_never_gates():
    decision = decide(
        plan=None, unmet_rows=("req-a",), regressions=(), refusals=0, **AMPLE
    )
    assert decision.accepted
    assert decision.reason == "no_plan"


def test_an_empty_plan_never_gates():
    empty = _plan(rows=())
    decision = decide(
        plan=empty, unmet_rows=("req-a",), regressions=(), refusals=0, **AMPLE
    )
    assert decision.accepted
    assert decision.reason == "no_plan"


@pytest.mark.parametrize(
    "seconds,steps,allowed",
    [
        (3000.0, 200, True),
        (MIN_REMAINING_SECONDS, MIN_REMAINING_STEPS, True),
        (MIN_REMAINING_SECONDS - 0.1, 200, False),
        (3000.0, MIN_REMAINING_STEPS - 1, False),
        (0.0, 0, False),
    ],
)
def test_budget_predicate(seconds, steps, allowed):
    assert budget_allows_refusal(seconds, steps)[0] is allowed


def test_the_directive_says_a_retry_will_be_accepted():
    text = render_directive(_plan(), ("req-a",), ())
    assert "accepted" in text
    assert "disagree" in text


def test_the_directive_truncates_a_long_unmet_list():
    plan = _plan(rows=tuple(f"req-{index}" for index in range(30)))
    text = render_directive(plan, tuple(f"req-{index}" for index in range(30)), ())
    assert "and 18 more" in text


def test_the_decision_row_is_journal_shaped():
    decision = decide(
        plan=_plan(), unmet_rows=("req-a",), regressions=(), refusals=0, **AMPLE
    )
    row = decision.as_row()
    assert row["accepted"] is False
    assert row["unmet_rows"] == ["req-a"]
    assert isinstance(row["remaining_seconds"], float)
    assert isinstance(row["remaining_steps"], int)
