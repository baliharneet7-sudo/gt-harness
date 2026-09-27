from __future__ import annotations

import json
from pathlib import Path

from scripts.aggregate_delivery_ab import ARTIFACT_PREFIX, aggregate, main, sign_test_p


def _leg(task, arm, run, step_limit=300):
    return {"leg_id": f"{task}__{arm}__r{run}", "task": task, "arm": arm, "run": run,
            "step_limit": step_limit}


def _write_leg(root: Path, leg: dict, *, reward, effective=300, failed=0, report=True,
               graded=True, delivery=None):
    agent = root / f"{ARTIFACT_PREFIX}{leg['leg_id']}-123" / "deepswe-gt-ab-x" / "trial" / "agent"
    agent.mkdir(parents=True)
    (agent / "official-verifier-result.json").write_text(json.dumps({
        "status": "GRADED" if graded else "ERROR", "reward": reward if graded else None,
        "failure_class": "graded" if graded else "provider_failure",
    }), encoding="utf-8")
    (agent / "gt-run.json").write_text(json.dumps({
        "provider_failed_calls": failed, "input_tokens": 1000, "output_tokens": 100,
        "total_cost": 0.1}), encoding="utf-8")
    if report:
        (agent / "miniswe_report.json").write_text(json.dumps({
            "effective_step_limit": effective, "requested_step_limit": leg["step_limit"],
            "gt_delivery": delivery or {"gt_delivery_mode": leg["arm"], "gt_bytes_delivered": 500,
                                        "gt_tool_calls": 2 if leg["arm"] == "attached" else None},
        }), encoding="utf-8")


def _plan(legs):
    return {"legs": legs}


def test_rates_pass_at_1_and_paired_sign_test(tmp_path):
    legs = [_leg(t, a, r) for t in ("a", "b", "c") for r in (1, 2) for a in ("push", "attached")]
    outcomes = {("a", "push"): 1, ("a", "attached"): 1, ("b", "push"): 0,
                ("b", "attached"): 1, ("c", "push"): 0, ("c", "attached"): 1}
    for leg in legs:
        _write_leg(tmp_path, leg, reward=outcomes[(leg["task"], leg["arm"])])
    result, code = aggregate(_plan(legs), tmp_path, provider_failure_threshold=10)
    assert code == 0
    assert result["arms"]["push"]["pass_at_1"] == round(1 / 3, 4)
    assert result["arms"]["attached"]["pass_at_1"] == 1.0
    assert result["paired"] == {"tasks_paired": 3, "push_better": 0, "attached_better": 2,
                                "ties": 1, "sign_test_p_two_sided": 0.5,
                                "method": "exact sign test over per-task solve rates; ties dropped"}
    assert result["arms"]["attached"]["mechanism_means"]["gt_tool_calls"] == 2.0


def test_never_graded_is_reported_not_counted_as_a_loss(tmp_path):
    legs = [_leg("a", "push", 1), _leg("a", "attached", 1), _leg("b", "push", 1)]
    _write_leg(tmp_path, legs[0], reward=1)
    _write_leg(tmp_path, legs[1], reward=None, graded=False)
    result, code = aggregate(_plan(legs), tmp_path, provider_failure_threshold=10)
    assert code == 0
    assert result["never_graded"] == ["a__attached__r1", "b__push__r1"]
    assert result["arms"]["attached"]["pass_at_1"] is None
    assert result["arms"]["push"]["pass_at_1"] == 1.0
    assert result["arms"]["push"]["never_graded"] == 1


def test_provider_failure_threshold_excludes_before_scoring(tmp_path):
    legs = [_leg("a", "push", 1), _leg("a", "push", 2)]
    _write_leg(tmp_path, legs[0], reward=0, failed=44)
    _write_leg(tmp_path, legs[1], reward=1, failed=2)
    result, _ = aggregate(_plan(legs), tmp_path, provider_failure_threshold=10)
    assert result["excluded"] == ["a__push__r1"]
    assert result["per_task_solve_rate"] == {"a": {"push": 1.0}}


def test_step_limit_mismatch_or_missing_report_fails_the_proof(tmp_path):
    legs = [_leg("a", "push", 1), _leg("a", "attached", 1)]
    _write_leg(tmp_path, legs[0], reward=0, effective=100)
    _write_leg(tmp_path, legs[1], reward=1, report=False)
    result, code = aggregate(_plan(legs), tmp_path, provider_failure_threshold=10)
    assert code == 2
    assert [row["leg_id"] for row in result["step_limit_violations"]] == [
        "a__push__r1", "a__attached__r1"]


def test_sign_test_values():
    assert sign_test_p(0, 0) == 1.0
    assert sign_test_p(5, 0) == 0.0625
    assert round(sign_test_p(6, 0), 5) == 0.03125


def test_cli_writes_json_and_markdown_and_propagates_the_exit(tmp_path):
    legs = [_leg("a", "push", 1), _leg("a", "attached", 1)]
    legs_root = tmp_path / "legs"
    _write_leg(legs_root, legs[0], reward=1)
    _write_leg(legs_root, legs[1], reward=0, effective=100)
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps(_plan(legs)), encoding="utf-8")
    comparator = tmp_path / "comparator.json"
    comparator.write_text(json.dumps({"comparator": {
        "leaderboard_model": "m", "reasoning_effort": "max", "match": "exact",
        "pass_at_1": 0.5, "n_tasks": 1}}), encoding="utf-8")
    out, md = tmp_path / "r.json", tmp_path / "r.md"
    code = main(["--plan", str(plan), "--legs-root", str(legs_root), "--comparator",
                 str(comparator), "--output", str(out), "--markdown", str(md)])
    assert code == 2
    assert json.loads(out.read_text(encoding="utf-8"))["schema"] == "gt.deepswe_delivery_ab.v1"
    text = md.read_text(encoding="utf-8")
    assert "Leaderboard comparator" in text and "Step-limit proof failed" in text


def test_an_attached_leg_without_a_graph_is_not_scored_as_gt(tmp_path):
    """The push arm aborts when the graph never becomes ready; the attached arm
    runs on as plain mini-swe and reports treatment_valid=false. Scoring it
    would credit GT with a run GT never touched."""
    legs = [_leg("a", "attached", 1), _leg("a", "attached", 2)]
    _write_leg(tmp_path, legs[0], reward=1, delivery={
        "gt_delivery_mode": "attached", "treatment_valid": False,
        "treatment_invalid_reason": "graph_not_ready"})
    _write_leg(tmp_path, legs[1], reward=0)
    result, code = aggregate(_plan(legs), tmp_path, provider_failure_threshold=10)
    assert code == 0
    assert result["treatment_invalid"] == ["a__attached__r1"]
    assert result["arms"]["attached"]["treatment_invalid"] == 1
    assert result["per_task_solve_rate"] == {"a": {"attached": 0.0}}


def test_a_leg_that_ran_in_the_wrong_arm_fails_the_proof(tmp_path):
    legs = [_leg("a", "attached", 1)]
    _write_leg(tmp_path, legs[0], reward=1, delivery={"gt_delivery_mode": "push"})
    result, code = aggregate(_plan(legs), tmp_path, provider_failure_threshold=10)
    assert code == 2
    assert result["arm_violations"] == [
        {"leg_id": "a__attached__r1", "planned": "attached", "reported": "push"}]
