from __future__ import annotations

from scripts.compare_tb2_smoke import compare


def _arm(*, solved: bool, calls: int, steps: int, tokens: int) -> dict:
    return {
        "task": "task-a",
        "solved": solved,
        "reward": 1.0 if solved else 0.0,
        "provider_calls": calls,
        "api_calls": calls,
        "assistant_steps": steps,
        "total_tokens": tokens,
        "uncached_input_tokens": 10,
    }


def test_comparison_uses_manifest_and_reports_flips_and_missing_baseline_steps() -> None:
    manifest = {"tasks": ["task-a", "task-b"]}
    baseline = {"rows": [
        {"task": "task-a", "solved": False, "reward": 0.0, "provider_calls": 4, "total_tokens": 100},
        {"task": "task-b", "solved": True, "reward": 1.0, "provider_calls": 3, "total_tokens": 80},
    ]}
    previous = {
        "receipt_metrics": [
            _arm(solved=False, calls=6, steps=6, tokens=140),
            {**_arm(solved=True, calls=5, steps=5, tokens=120), "task": "task-b"},
        ],
        "trial_results": [
            {"task_name": "task-a__x", "verifier_result": {"rewards": {"reward": 0}}},
            {"task_name": "task-b__x", "verifier_result": {"rewards": {"reward": 1}}},
        ],
    }
    current = {
        "receipt_metrics": [
            {**_arm(solved=True, calls=3, steps=3, tokens=90), "task": "task-a"},
            {**_arm(solved=False, calls=4, steps=4, tokens=110), "task": "task-b"},
        ],
        "trial_results": [
            {"task_name": "task-a__x", "verifier_result": {"rewards": {"reward": 1}}},
            {"task_name": "task-b__x", "verifier_result": {"rewards": {"reward": 0}}},
        ],
    }
    report = compare(manifest=manifest, baseline=baseline, previous=previous, current=current)
    assert report["flips"]["current_vs_gt_off_positive"] == ["task-a"]
    assert report["flips"]["current_vs_gt_off_negative"] == ["task-b"]
    assert report["flips"]["current_vs_previous_gt_positive"] == ["task-a"]
    assert report["flips"]["current_vs_previous_gt_negative"] == ["task-b"]
    assert report["arms"]["gt_off"]["assistant_steps"] is None
    assert report["rows"][0]["current_minus_previous_gt"]["total_tokens"] == -50
