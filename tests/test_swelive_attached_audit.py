"""Attached delivery withholds pushes by design; the audit must name it, not RED it.

In ``attached`` mode the push pipeline runs in SHADOW (gt_engine/attached_delivery.py):
producers fire, nothing is pushed, and gt_engine's attribution calls each such
trigger TRIGGERED_DARK. Unexcused, every attached SWE-bench-Live task would be
RED in scripts/gt_audit.py and fail scripts/gt_live_gate.py, so an attached run
could never attest. Push mode must stay exactly as strict as before.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from gt_engine.attribution import DIRECT_FEATURES
from scripts import gt_audit
from scripts.gt_audit import (
    ATTACHED_WITHHELD_REASON,
    attribution_red_features,
    excuse_attached_withheld,
    report_delivery_mode,
)
from scripts.gt_live_gate import evaluate_live_gate
from tests.test_gt_audit import make_native_miniswe_task

DARK_FEATURE = next(iter(sorted(DIRECT_FEATURES)))


def _projection(status: str = "TRIGGERED_DARK", reasons=("candidate_returned",)) -> dict:
    base = gt_audit.summarize_features({})
    return {
        **base,
        DARK_FEATURE: {**base[DARK_FEATURE], "status": status, "reasons": list(reasons)},
    }


def _write_report(task: Path, mode: str | None) -> None:
    report = {"gt": {}}
    if mode is not None:
        report["gt_delivery"] = {"gt_delivery_mode": mode, "treatment_valid": True}
    (task / "agent" / "miniswe_report.json").write_text(json.dumps(report), encoding="utf-8")


def test_attached_mode_names_the_withheld_push() -> None:
    projection = _projection()
    excused = excuse_attached_withheld(projection, "attached")
    item = excused[DARK_FEATURE]
    assert item["status"] == "SUPPRESSED_WITH_REASON"
    assert item["reasons"] == [ATTACHED_WITHHELD_REASON]
    assert item["withheld_status"] == "TRIGGERED_DARK"
    assert item["withheld_reasons"] == ["candidate_returned"]
    assert attribution_red_features(excused) == []
    # The input is never mutated.
    assert projection[DARK_FEATURE]["status"] == "TRIGGERED_DARK"


@pytest.mark.parametrize("mode", ["push", None, "off", "ATTACHED"])
def test_every_other_mode_stays_strict(mode) -> None:
    excused = excuse_attached_withheld(_projection(), mode)
    assert excused[DARK_FEATURE]["status"] == "TRIGGERED_DARK"
    assert attribution_red_features(excused) == [DARK_FEATURE]


@pytest.mark.parametrize("status", ["DELIVERED_UNEXPOSED", "EXPOSED", "TELEMETRY_FAULT"])
def test_attached_mode_does_not_excuse_contrary_evidence(status) -> None:
    # Attached makes no push deliveries, so a delivery or a fault is not the design.
    excused = excuse_attached_withheld(_projection(status, ("x",)), "attached")
    assert excused[DARK_FEATURE]["status"] == status
    assert attribution_red_features(excused) == [DARK_FEATURE]


def test_the_mode_is_read_from_the_runners_own_report() -> None:
    assert report_delivery_mode({"gt_delivery": {"gt_delivery_mode": "attached"}}) == "attached"
    assert report_delivery_mode({"gt_delivery": {"gt_delivery_mode": "push"}}) == "push"
    assert report_delivery_mode({}) is None
    assert report_delivery_mode({"gt_delivery": "attached"}) is None


@pytest.mark.parametrize("mode, verdict", [
    ("attached", "GREEN-quiet"),
    ("push", "RED"),
    (None, "RED"),
])
def test_native_audit_verdict_by_delivery_mode(tmp_path, monkeypatch, mode, verdict) -> None:
    task = make_native_miniswe_task(tmp_path)
    _write_report(task, mode)
    monkeypatch.setattr(gt_audit, "_native_feature_projection", lambda *a, **k: _projection())
    audit = gt_audit.audit_task(task)
    assert audit.verdict == verdict, audit.verdict_reasons
    status = audit.feature_attribution[DARK_FEATURE]["status"]
    if mode == "attached":
        assert status == "SUPPRESSED_WITH_REASON"
        assert any(ATTACHED_WITHHELD_REASON in note for note in audit.notes)
    else:
        assert status == "TRIGGERED_DARK"
        assert any("attribution RED feature(s)" in reason for reason in audit.verdict_reasons)


@pytest.mark.parametrize("mode, dark", [("attached", False), ("push", True)])
def test_live_gate_follows_the_audit(mode, dark) -> None:
    audit = {"tasks": [{
        "task_name": "t",
        "feature_attribution": excuse_attached_withheld(_projection(), mode),
    }]}
    report = evaluate_live_gate(
        audit, min_witnessed=0, expected_tasks=1, expected_model="m",
        require_complete_census=True,
    )
    went_dark = any("went dark" in issue for issue in report["issues"])
    assert went_dark is dark
    assert not any("incomplete feature census" in issue for issue in report["issues"])
