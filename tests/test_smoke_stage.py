from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.smoke_stage import (
    GATE_ONE_MAX_TIMEOUT_SECONDS,
    GATE_TASK_ID,
    select_stage_tasks,
    stage_timeout_cap_seconds,
    validate_prior_gate,
    validate_stage_inputs,
)


def _tasks() -> list[str]:
    return [GATE_TASK_ID, *(f"task-{index}" for index in range(19))]


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def test_stage_selection_partitions_the_frozen_cohort_exactly_once() -> None:
    tasks = _tasks()
    gate = select_stage_tasks(tasks, "gate-one")
    remainder = select_stage_tasks(tasks, "remaining-19")

    assert gate == [GATE_TASK_ID]
    assert len(remainder) == 19
    assert gate + remainder == tasks
    assert set(gate).isdisjoint(remainder)


def test_gate_one_ceiling_lets_the_gate_task_finish() -> None:
    # Measured, not assumed: every one of the 20 tasks declares
    # [agent] timeout_sec = 5400.0 at benchmark revision 435ee89e, and the plan
    # job resolves with multiplier 1.0, so min(5400, 5400) means this ceiling
    # subtracts nothing today. It is a rail against a future task.toml asking
    # for more than the benchmark's own budget, not a knob for buying a slow
    # task more time - raising it would make gate-one a different experiment
    # from the cohort it gates, and from both frozen GT-off controls.
    #
    # It was 30 minutes once, which left the agent 1500s after the supervisor
    # grace and killed run 34062325608 at terminal=timeout mid-loop. That is why
    # it is pinned rather than merely set.
    assert GATE_ONE_MAX_TIMEOUT_SECONDS == 90 * 60
    assert stage_timeout_cap_seconds("gate-one") == 90 * 60
    assert stage_timeout_cap_seconds("remaining-19") is None


@pytest.mark.parametrize("stage", ["", "all", "smoke20", "gate_one"])
def test_unknown_stage_fails_closed(stage: str) -> None:
    with pytest.raises(ValueError):
        select_stage_tasks(_tasks(), stage)


def test_stage_inputs_require_an_exact_prior_run_only_for_remainder() -> None:
    validate_stage_inputs("gate-one", "")
    validate_stage_inputs("remaining-19", "123")
    with pytest.raises(ValueError):
        validate_stage_inputs("gate-one", "123")
    with pytest.raises(ValueError):
        validate_stage_inputs("remaining-19", "")


def _prior_gate(root: Path) -> None:
    _write(
        root / "deepswe20-attestation.json",
        {
            "schema": "gt.deepswe_gt_harness_attestation.v1",
            "status": "PASS",
            "source_sha": "a" * 40,
            "workflow_run_id": "123",
            "task_job_result": "success",
            "task_count": 1,
            "task_ids": [GATE_TASK_ID],
            "official_verifier_tasks": [GATE_TASK_ID],
            "product_totals": {"provider_calls": 2, "provider_completed_calls": 2},
        },
    )
    _write(
        root / "diagnostic-summary.json",
        {
            "schema": "gt.diagnostic_summary.v1",
            "exit_code": 0,
            "artifact_issues": [],
            "tasks": [{"task_id": GATE_TASK_ID}],
            "capabilities": [
                {
                    "task_id": GATE_TASK_ID,
                    "capability": "dense_retrieval",
                    "required": True,
                    "state": "WORKING",
                    "verified": True,
                }
            ],
        },
    )


def test_prior_gate_binding_requires_passed_attestation_and_working_capabilities(
    tmp_path: Path,
) -> None:
    _prior_gate(tmp_path)
    binding = validate_prior_gate(
        tmp_path, source_sha="a" * 40, prior_gate_run_id="123"
    )
    assert binding["workflow_run_id"] == 123
    assert binding["task_id"] == GATE_TASK_ID


@pytest.mark.parametrize(
    ("filename", "field", "value"),
    [
        ("deepswe20-attestation.json", "status", "FAIL"),
        ("deepswe20-attestation.json", "task_ids", ["other"]),
        ("deepswe20-attestation.json", "official_verifier_tasks", []),
        ("diagnostic-summary.json", "exit_code", 1),
        ("diagnostic-summary.json", "artifact_issues", ["bad"]),
    ],
)
def test_prior_gate_mutations_fail_closed(
    tmp_path: Path, filename: str, field: str, value: object
) -> None:
    _prior_gate(tmp_path)
    path = tmp_path / filename
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload[field] = value
    _write(path, payload)
    with pytest.raises(ValueError):
        validate_prior_gate(tmp_path, source_sha="a" * 40, prior_gate_run_id="123")


def test_unverified_required_capability_blocks_remainder(tmp_path: Path) -> None:
    _prior_gate(tmp_path)
    path = tmp_path / "diagnostic-summary.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["capabilities"][0]["verified"] = False
    _write(path, payload)
    with pytest.raises(ValueError, match="required capability"):
        validate_prior_gate(tmp_path, source_sha="a" * 40, prior_gate_run_id="123")


def test_all_20_selects_the_whole_cohort_in_pinned_order():
    from scripts.smoke_stage import ALL_STAGE

    tasks = _tasks()
    assert select_stage_tasks(tasks, ALL_STAGE) == tasks


def test_all_20_runs_at_the_same_budget_as_the_remainder_stage():
    # A one-dispatch cohort must not become a different experiment. Both
    # multi-task stages resolve to each task's own [agent] timeout_sec.
    from scripts.smoke_stage import ALL_STAGE

    assert stage_timeout_cap_seconds(ALL_STAGE) == stage_timeout_cap_seconds(
        "remaining-19"
    )


def test_all_20_and_gate_one_partition_the_cohort():
    # Whichever way the cohort is dispatched, the same 20 tasks run exactly once.
    from scripts.smoke_stage import ALL_STAGE

    tasks = _tasks()
    split = select_stage_tasks(tasks, "gate-one") + select_stage_tasks(
        tasks, "remaining-19"
    )
    assert sorted(split) == sorted(select_stage_tasks(tasks, ALL_STAGE))


def test_all_20_must_not_claim_a_prior_gate():
    from scripts.smoke_stage import ALL_STAGE

    validate_stage_inputs(ALL_STAGE, "")
    with pytest.raises(ValueError):
        validate_stage_inputs(ALL_STAGE, "34257199043")


def _canonical():
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    return json.loads(
        (root / "eval" / "deepswe_smoke20_v1.json").read_text(encoding="utf-8")
    )["task_ids"]


def test_a_single_stage_selects_exactly_that_task():
    from scripts.smoke_stage import select_stage_tasks

    tasks = _canonical()
    target = "bandit-incremental-cache-control"
    assert target in tasks
    assert select_stage_tasks(tasks, f"single:{target}") == [target]


def test_a_single_stage_refuses_a_task_outside_the_cohort():
    import pytest

    from scripts.smoke_stage import select_stage_tasks

    with pytest.raises(ValueError):
        select_stage_tasks(_canonical(), "single:not-a-cohort-task")


def test_a_single_stage_runs_at_the_gate_budget():
    """A different budget would make its result incomparable to the cohort."""
    from scripts.smoke_stage import (
        GATE_STAGE,
        stage_timeout_cap_seconds,
    )

    assert stage_timeout_cap_seconds("single:bandit-incremental-cache-control") == (
        stage_timeout_cap_seconds(GATE_STAGE)
    )


def test_a_single_stage_may_not_claim_a_prior_gate():
    import pytest

    from scripts.smoke_stage import validate_stage_inputs

    validate_stage_inputs("single:bandit-incremental-cache-control", "")
    with pytest.raises(ValueError):
        validate_stage_inputs("single:bandit-incremental-cache-control", "123")


def test_the_existing_stages_are_unchanged_by_the_addition():
    """The new stage is additive: nothing about the pinned three moves."""
    from scripts.smoke_stage import (
        ALL_STAGE,
        GATE_STAGE,
        GATE_TASK_ID,
        REMAINDER_STAGE,
        select_stage_tasks,
        stage_timeout_cap_seconds,
    )

    tasks = _canonical()
    assert select_stage_tasks(tasks, GATE_STAGE) == [GATE_TASK_ID]
    assert select_stage_tasks(tasks, ALL_STAGE) == tasks
    assert len(select_stage_tasks(tasks, REMAINDER_STAGE)) == 19
    assert stage_timeout_cap_seconds(ALL_STAGE) is None
    assert stage_timeout_cap_seconds(REMAINDER_STAGE) is None


def test_an_unknown_stage_is_still_refused():
    import pytest

    from scripts.smoke_stage import select_stage_tasks

    with pytest.raises(ValueError):
        select_stage_tasks(_canonical(), "whatever")
