from __future__ import annotations

import json

from scripts.gt_live_gate import evaluate_live_gate


def _task(name, features, lifecycle=None):
    return {
        "task_name": name,
        "agent_error": None,
        "exception_info": None,
        "attribution_issues": [],
        "ledger_issues": [],
        "dose_violations": [],
        "feature_attribution": features,
        "lifecycle_checkpoints": lifecycle or {},
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


def test_live_gate_requires_sdlc_checkpoint_union(tmp_path):
    trial = tmp_path / "task__trial"
    trial.mkdir()
    (trial / "result.json").write_text(json.dumps({
        "config": {"agent": {"model_name": "deepseek-v4-flash"}},
    }), encoding="utf-8")
    audit = {
        "tasks": [
            _task(
                "task",
                {"obligations": _feature()},
                lifecycle={
                    "task_start": {"count": 1},
                    "research": {"count": 2},
                    "pre_edit": {"count": 1},
                    "post_edit": {"count": 1},
                    "verify": {"count": 1},
                    "submit": {"count": 1},
                },
            ),
        ],
    }

    report = evaluate_live_gate(
        audit,
        min_witnessed=1,
        expected_tasks=1,
        expected_model="deepseek-v4-flash",
        required_lifecycle=(
            "task_start", "research", "pre_edit", "post_edit",
            "test", "verify", "submit",
        ),
        run_dir=tmp_path,
    )

    assert report["passed"] is False
    assert report["missing_lifecycle"] == ["test"]
    assert any("missing SDLC" in issue for issue in report["issues"])
