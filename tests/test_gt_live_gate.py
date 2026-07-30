from __future__ import annotations

import json

from scripts.gt_live_gate import evaluate_live_gate


def _task(name, features):
    return {
        "task_name": name,
        "agent_error": None,
        "exception_info": None,
        "attribution_issues": [],
        "ledger_issues": [],
        "dose_violations": [],
        "feature_attribution": features,
    }


def _feature(status="WITNESSED", *, delivered=True, exposed=True):
    return {
        "status": status,
        "deliveries": ["d1"] if delivered else [],
        "exposed": exposed,
        "action_consistent": status == "WITNESSED",
    }


def test_live_gate_accepts_healthy_provider_bound_feature_union(tmp_path):
    trial = tmp_path / "task__trial"
    trial.mkdir()
    (trial / "result.json").write_text(json.dumps({
        "config": {"agent": {"model_name": "deepseek-v4-flash"}},
    }), encoding="utf-8")
    audit = {
        "tasks": [
            _task("task", {
                "obligations": _feature(),
                "localization": _feature(),
                "GT_LOC_RESLOT": _feature(),
            }),
        ],
    }

    report = evaluate_live_gate(
        audit,
        min_witnessed=3,
        expected_tasks=1,
        expected_model="deepseek-v4-flash",
        run_dir=tmp_path,
    )

    assert report["passed"] is True
    assert report["witnessed_count"] == 3


def test_live_gate_rejects_dark_unexposed_and_wrong_model(tmp_path):
    trial = tmp_path / "task__trial"
    trial.mkdir()
    (trial / "result.json").write_text(json.dumps({
        "config": {"agent": {"model_name": "other-model"}},
    }), encoding="utf-8")
    audit = {
        "tasks": [
            _task("task", {
                "localization": _feature(
                    "TRIGGERED_DARK", delivered=False, exposed=False
                ),
                "caller_contract": _feature(exposed=False),
            }),
        ],
    }

    report = evaluate_live_gate(
        audit,
        min_witnessed=2,
        expected_tasks=1,
        expected_model="deepseek-v4-flash",
        run_dir=tmp_path,
    )

    assert report["passed"] is False
    assert any("went dark" in issue for issue in report["issues"])
    assert any("unexposed" in issue for issue in report["issues"])
    assert any("expected model" in issue for issue in report["issues"])
