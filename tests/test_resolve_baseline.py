from __future__ import annotations

import json

from scripts.resolve_baseline import main, normalize_model, resolve


def _row(model, task, passed, effort="max", harness="mini-swe-agent", steps=10):
    return {"model": model, "task_name": task, "passed": passed, "reasoning_effort": effort,
            "harness": harness, "included_in_score": True, "n_agent_steps": steps}


ROWS = [
    _row("deepseek-v4-flash", "a", True), _row("deepseek-v4-flash", "a", False),
    _row("deepseek-v4-flash", "b", True), _row("deepseek-v4-flash", "b", True),
    _row("gpt-5-6-terra", "a", False, effort="medium"),
    _row("gpt-5-6-terra", "b", True, effort="medium"),
]


def test_normalize_model_drops_provider_and_folds_dots():
    assert normalize_model("openai/GPT-5.6-Terra") == "gpt-5-6-terra"
    assert normalize_model("deepseek/deepseek-v4-flash-0731") == "deepseek-v4-flash-0731"


def test_exact_match_and_task_clustered_pass_rate():
    result = resolve(ROWS, model="openai/gpt-5.6-terra", reasoning_effort="medium")
    comparator = result["comparator"]
    assert comparator["match"] == "exact"
    assert comparator["pass_at_1"] == 0.5 and comparator["n_trials"] == 2


def test_date_pinned_model_matches_with_an_explicit_label():
    comparator = resolve(ROWS, model="deepseek/deepseek-v4-flash-0731",
                         reasoning_effort="max")["comparator"]
    assert comparator["match"] == "date_suffix_stripped"
    assert comparator["pass_at_1"] == 0.75
    assert comparator["per_task_pass_rate"] == {"a": 0.5, "b": 1.0}


def test_effort_mismatch_is_named_not_silently_matched():
    result = resolve(ROWS, model="deepseek-v4-flash", reasoning_effort="")
    assert result["comparator"] is None
    assert result["reason"] == "reasoning_effort_mismatch"
    assert result["leaderboard_efforts"] == ["max"]


def test_unknown_model_and_harness():
    assert resolve(ROWS, model="stealth/space-bunny-alpha", reasoning_effort="")["reason"] == (
        "model_not_on_leaderboard")
    assert resolve(ROWS, model="deepseek-v4-flash", reasoning_effort="max",
                   harness="claude-code")["reason"] == "harness_not_on_leaderboard"


def test_task_subset_reports_missing_tasks():
    comparator = resolve(ROWS, model="deepseek-v4-flash", reasoning_effort="max",
                         tasks=["b", "zz"])["comparator"]
    assert comparator["n_tasks"] == 1 and comparator["missing_tasks"] == ["zz"]


def test_cli_reads_a_local_trials_file(tmp_path, capsys):
    trials = tmp_path / "trials.json"
    trials.write_text(json.dumps({"rows": ROWS}), encoding="utf-8")
    out = tmp_path / "comparator.json"
    assert main(["--trials", str(trials), "--model", "deepseek-v4-flash",
                 "--reasoning-effort", "max", "--output", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["comparator"]["passes"] == 3
