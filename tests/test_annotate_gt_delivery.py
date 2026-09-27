from __future__ import annotations

import json
from pathlib import Path

from scripts.annotate_gt_delivery import annotate, delivery_fields, main


def _report(root: Path, report: dict) -> None:
    agent = root / "job" / "task__abc" / "agent"
    agent.mkdir(parents=True)
    (agent / "miniswe_report.json").write_text(json.dumps(report), encoding="utf-8")


def test_valid_attached_run_carries_its_mechanism_counts() -> None:
    fields = delivery_fields(
        {"effective_step_limit": 100, "gt_delivery": {
            "gt_delivery_mode": "attached", "treatment_valid": True, "gt_tool_calls": 7}},
        requested_mode="attached", requested_step_limit=100,
    )
    assert fields["treatment_valid"] is True
    assert fields["step_limit_matches"] is True
    assert fields["gt_tool_calls"] == 7


def test_graph_never_ready_is_not_a_gt_result() -> None:
    fields = delivery_fields(
        {"effective_step_limit": 100, "gt_delivery": {
            "gt_delivery_mode": "attached", "treatment_valid": False,
            "treatment_invalid_reason": "graph_not_ready"}},
        requested_mode="attached", requested_step_limit=100,
    )
    assert fields["treatment_valid"] is False
    assert fields["treatment_invalid_reason"] == "graph_not_ready"


def test_wrong_mode_or_missing_report_is_invalid() -> None:
    wrong = delivery_fields({"effective_step_limit": 100, "gt_delivery": {"gt_delivery_mode": "off"}},
                            requested_mode="attached", requested_step_limit=100)
    missing = delivery_fields(None, requested_mode="push", requested_step_limit=100)
    assert wrong["treatment_valid"] is False and wrong["treatment_invalid_reason"] == "delivery_mode_mismatch:off"
    assert missing["treatment_valid"] is False and missing["report_present"] is False


def test_step_limit_mismatch_is_recorded() -> None:
    fields = delivery_fields({"effective_step_limit": 100, "gt_delivery": {"gt_delivery_mode": "push"}},
                             requested_mode="push", requested_step_limit=300)
    assert fields["step_limit_matches"] is False


def test_cli_annotates_the_single_task_row(tmp_path, capsys) -> None:
    _report(tmp_path / "results", {"effective_step_limit": 50, "gt_delivery": {
        "gt_delivery_mode": "attached", "treatment_valid": False, "treatment_invalid_reason": "x:y"}})
    progress = tmp_path / "benchmark-progress.json"
    progress.write_text(json.dumps({"schema": "s", "tasks": [{"task_id": "t", "state": "passed"}]}),
                        encoding="utf-8")
    assert main(["--results", str(tmp_path / "results"), "--progress", str(progress),
                 "--requested-mode", "attached", "--requested-step-limit", "50"]) == 0
    row = json.loads(progress.read_text(encoding="utf-8"))["tasks"][0]
    assert row["state"] == "passed" and row["gt_delivery"]["treatment_valid"] is False
    # The reason is container-derived text: it reaches the runner through the
    # escaping helper, on one line.
    assert "::warning title=GT treatment invalid::x:y" in capsys.readouterr().err


def test_annotate_refuses_a_multi_task_receipt() -> None:
    import pytest
    with pytest.raises(ValueError):
        annotate({"tasks": [{}, {}]}, {})
