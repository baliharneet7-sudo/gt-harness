from __future__ import annotations

import json

from scripts.gt_live_gate import evaluate_live_gate


def _task(
    name,
    features,
    lifecycle=None,
    *,
    provider_temperatures=None,
    expected_profile_controls=None,
    active_profile_controls=None,
    missing_profile_controls=None,
    profile_behavior_flags=None,
    profile_receipt_fault="",
):
    return {
        "task_name": name,
        "agent_error": None,
        "exception_info": None,
        "attribution_issues": [],
        "ledger_issues": [],
        "dose_violations": [],
        "feature_attribution": features,
        "lifecycle_checkpoints": lifecycle or {},
        "provider_temperatures": provider_temperatures or [],
        "expected_profile_controls": expected_profile_controls or [],
        "active_profile_controls": active_profile_controls or [],
        "missing_profile_controls": missing_profile_controls or [],
        "profile_behavior_flags": profile_behavior_flags or [],
        "profile_receipt_fault": profile_receipt_fault,
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


def test_live_gate_requires_complete_census_temperature_and_actions(tmp_path):
    from gt_engine.attribution import DIRECT_FEATURES

    trial = tmp_path / "task__trial"
    trial.mkdir()
    (trial / "result.json").write_text(json.dumps({
        "config": {"agent": {"model_name": "deepseek-v4-flash"}},
    }), encoding="utf-8")
    features = {
        feature_id: _feature(
            "INELIGIBLE", delivered=False, exposed=False
        )
        for feature_id in DIRECT_FEATURES
    }
    features["obligations"] = _feature()
    features["localization"] = _feature()
    audit = {
        "tasks": [
            _task(
                "task",
                features,
                provider_temperatures=[1.0],
            ),
        ],
    }

    report = evaluate_live_gate(
        audit,
        min_witnessed=2,
        min_action_consistent=2,
        expected_tasks=1,
        expected_model="deepseek-v4-flash",
        expected_temperature=1.0,
        require_complete_census=True,
        run_dir=tmp_path,
    )

    assert report["passed"] is True
    assert report["provider_temperatures"] == [1.0]
    assert report["complete_census"] is True


def test_live_gate_rejects_missing_identity_wrong_temperature_and_too_few_actions(
    tmp_path,
):
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
                provider_temperatures=[0.7],
            ),
        ],
    }

    report = evaluate_live_gate(
        audit,
        min_witnessed=1,
        min_action_consistent=2,
        expected_tasks=1,
        expected_model="deepseek-v4-flash",
        expected_temperature=1.0,
        require_complete_census=True,
        run_dir=tmp_path,
    )

    assert report["passed"] is False
    assert any("feature census" in issue for issue in report["issues"])
    assert any("temperature" in issue for issue in report["issues"])
    assert any("action-consistent" in issue for issue in report["issues"])


def test_live_gate_requires_profile_controls_and_behavior_flags(tmp_path):
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
                missing_profile_controls=["GT_CS_EDIT_TRIGGER"],
                profile_behavior_flags=[],
            ),
        ],
    }

    report = evaluate_live_gate(
        audit,
        min_witnessed=1,
        expected_tasks=1,
        expected_model="deepseek-v4-flash",
        required_behavior_flags=("GT_CS_EDIT_TRIGGER",),
        require_complete_profile=True,
        run_dir=tmp_path,
    )

    assert report["passed"] is False
    assert any("profile control" in issue for issue in report["issues"])
    assert any("behavior flag" in issue for issue in report["issues"])


def test_live_gate_accepts_complete_profile_and_required_behavior(tmp_path):
    trial = tmp_path / "task__trial"
    trial.mkdir()
    (trial / "result.json").write_text(json.dumps({
        "config": {"agent": {"model_name": "deepseek-v4-flash"}},
    }), encoding="utf-8")
    controls = ["GT_GATEWAY", "GT_CS_EDIT_TRIGGER"]
    audit = {
        "tasks": [
            _task(
                "task",
                {"obligations": _feature()},
                expected_profile_controls=controls,
                active_profile_controls=controls,
                profile_behavior_flags=["GT_CS_EDIT_TRIGGER"],
            ),
        ],
    }

    report = evaluate_live_gate(
        audit,
        min_witnessed=1,
        expected_tasks=1,
        expected_model="deepseek-v4-flash",
        required_behavior_flags=("GT_CS_EDIT_TRIGGER",),
        require_complete_profile=True,
        run_dir=tmp_path,
    )

    assert report["passed"] is True
    assert report["complete_profile"] is True
    assert report["observed_behavior_flags"] == ["GT_CS_EDIT_TRIGGER"]
