"""The run summary exists to answer one question mid-run: better or worse.

Counts alone cannot. A run that scores 66 by solving a different 66 than the
baseline is not the same result, so these tests are about the per-task verdict
and about the two cases a reader must never have to hunt for: a task the
baseline solved and this run did not, and a task this run never graded.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.tb2_run_summary import main, render_run, render_task

COHORT = {
    "baseline_rewards": {
        "kept": 1.0,
        "lost": 1.0,
        "won": 0.0,
        "absent": 1.0,
    }
}


def _summary(tasks: list[dict]) -> dict:
    return {
        "total": len(tasks),
        "completed": len(tasks),
        "officially_graded": sum(
            row["state"] in ("passed", "verifier_failed") for row in tasks
        ),
        "passed": sum(row["state"] == "passed" for row in tasks),
        "infrastructure_failed": sum(
            row["state"] == "infrastructure_failed" for row in tasks
        ),
        "tasks": tasks,
    }


ROWS = [
    {"task_id": "kept", "state": "passed", "reward": 1, "failure_class": "graded"},
    {"task_id": "lost", "state": "verifier_failed", "reward": 0, "failure_class": "graded"},
    {"task_id": "won", "state": "passed", "reward": 1, "failure_class": "graded"},
    {
        "task_id": "absent",
        "state": "infrastructure_failed",
        "reward": None,
        "failure_class": "missing_result",
    },
]


def test_a_task_the_baseline_solved_and_this_run_did_not_is_named_a_regression() -> None:
    text = render_run(_summary(ROWS), COHORT)

    assert "regressions **1**" in text
    assert "| lost | 0 | 1 | REGRESSION |" in text


def test_a_task_this_run_won_is_named_a_gain() -> None:
    text = render_run(_summary(ROWS), COHORT)

    assert "gains **1**" in text
    assert "| won | 1 | 0 | gain |" in text


def test_an_ungraded_task_is_not_silently_a_zero() -> None:
    """`infrastructure_failed` with no reward is the case that has cost us
    whole cohorts; it must read as 'not graded', never as a loss."""
    text = render_run(_summary(ROWS), COHORT)

    assert "| absent | - | 1 | not graded |" in text


def test_the_regressions_are_at_the_top_of_the_table() -> None:
    text = render_run(_summary(ROWS), COHORT)
    body = text[text.index("|---|"):]

    assert body.index("| lost |") < body.index("| kept |")
    assert body.index("| absent |") < body.index("| kept |")


def test_the_baseline_count_covers_only_the_tasks_this_run_reported() -> None:
    """Comparing our 88 against the baseline's 89 hands us a task we never ran.

    qemu-alpine-ssh is excluded from a GT cohort for musl and the baseline
    solved it, so the comparison must be drawn over the reported tasks only.
    """
    reported = [row for row in ROWS if row["task_id"] != "absent"]

    text = render_run(_summary(reported), COHORT)

    # kept + lost were solved by the baseline; absent is not counted at all.
    assert "baseline solved **2**" in text


def test_a_task_block_carries_the_baseline_beside_the_reward() -> None:
    progress = {"tasks": [{"task_id": "lost", "state": "verifier_failed", "reward": 0,
                           "failure_class": "graded", "error_code": ""}]}

    text = render_task(progress, baseline_rewards=COHORT["baseline_rewards"])

    assert "lost - FAIL" in text
    assert "| 0 | 1 | REGRESSION | graded | - |" in text


def test_a_run_that_sealed_no_receipt_says_so() -> None:
    """write-compressor in run 35560215706 was solved and sealed no
    gt-run.json; an absent token table must be stated, not inferred."""
    progress = {"tasks": [{"task_id": "kept", "state": "passed", "reward": 1}]}

    text = render_task(progress, receipt=None)

    assert "did not seal a product receipt" in text


def test_the_task_block_reports_what_gt_did() -> None:
    progress = {"tasks": [{"task_id": "kept", "state": "passed", "reward": 1}]}
    events = [
        {"event": "graph_recovery"},
        {"event": "graph_recovery"},
        {"event": "graph_recovery_suspended"},
        {"event": "action_suppressed", "reason": "submit_refused"},
    ]

    text = render_task(progress, events=events)

    assert "graph recoveries: 2" in text
    assert "recovery suspended: 1" in text
    assert "submissions refused: 1" in text


def test_missing_optional_inputs_never_break_the_summary(tmp_path: Path) -> None:
    """Visibility must not be able to fail a paid run."""
    progress = tmp_path / "benchmark-progress.json"
    progress.write_text(
        json.dumps({"tasks": [{"task_id": "kept", "state": "passed", "reward": 1}]}),
        encoding="utf-8",
    )
    out = tmp_path / "summary.md"

    code = main(
        [
            "task",
            "--progress", str(progress),
            "--receipt", str(tmp_path / "absent.json"),
            "--events", str(tmp_path / "absent.jsonl"),
            "--cohort", str(tmp_path / "absent-cohort.json"),
            "--output", str(out),
        ]
    )

    assert code == 0
    assert "kept - PASS" in out.read_text(encoding="utf-8")


def test_the_shipped_cohort_rewards_render(tmp_path: Path) -> None:
    """The real config is the one CI passes; a schema drift must fail here."""
    cohort = json.loads(
        (Path(__file__).resolve().parents[1] / "config" / "tb2_full89_cohort.v1.json")
        .read_text(encoding="utf-8")
    )
    rewards = cohort["baseline_rewards"]
    task_id = next(iter(rewards))

    text = render_run(
        _summary([{"task_id": task_id, "state": "passed", "reward": 1,
                   "failure_class": "graded"}]),
        cohort,
    )

    assert f"| {task_id} |" in text
    assert sum(1 for value in rewards.values() if value == 1.0) == 66


@pytest.mark.parametrize("mode", ["task", "run"])
def test_output_is_appended_not_overwritten(tmp_path: Path, mode: str) -> None:
    """GITHUB_STEP_SUMMARY accumulates; a truncating write loses earlier steps."""
    out = tmp_path / "summary.md"
    out.write_text("EARLIER\n", encoding="utf-8")
    source = tmp_path / "in.json"
    if mode == "task":
        source.write_text(
            json.dumps({"tasks": [{"task_id": "kept", "state": "passed", "reward": 1}]}),
            encoding="utf-8",
        )
        argv = ["task", "--progress", str(source), "--output", str(out)]
    else:
        source.write_text(json.dumps(_summary(ROWS)), encoding="utf-8")
        argv = ["run", "--summary", str(source), "--output", str(out)]

    assert main(argv) == 0
    assert out.read_text(encoding="utf-8").startswith("EARLIER\n")
