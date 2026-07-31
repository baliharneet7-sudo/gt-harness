from __future__ import annotations

import pytest

from gt_engine.miniswe_controller import (
    GroundtruthController,
    LifecycleError,
    Predicate,
    PredicateStatus,
)


def test_controller_lifecycle_and_fresh_submit():
    c = GroundtruthController([Predicate("syntax", "syntax check")])
    assert c.phase == "ORIENT"
    c.start_task()
    assert c.phase == "IMPLEMENT"
    c.record_receipt("syntax", "cmd", 0, "ok", epoch=0)
    with pytest.raises(LifecycleError, match="VERIFY"):
        c.submit_decision()
    c.begin_verify()
    c.begin_submit()
    assert c.submit_decision() is True
    assert c.phase == "FINISHED"
    with pytest.raises(LifecycleError, match="FINISHED"):
        c.before_action("bash", "echo after")


def test_edit_invalidates_receipt_and_refuses_stale_submit():
    c = GroundtruthController([Predicate("artifact", "artifact exists")])
    c.start_task()
    c.begin_verify()
    c.record_receipt("artifact", "check", 0, "ok", epoch=c.workspace_epoch)
    c.begin_implement()
    c.note_edit(["out.txt"])
    c.begin_verify()
    c.begin_submit()
    assert c.submit_decision() is False
    assert c.unmet_predicates == ("artifact",)


def test_duplicate_action_is_rejected_after_second_repeat():
    c = GroundtruthController([], repeat_budget=1)
    c.start_task()
    c.before_action("bash", "printf 1")
    c.after_observation("same output", diff_hash="d")
    c.before_action("bash", "printf 1")
    with pytest.raises(LifecycleError, match="repeat"):
        c.before_action("bash", "printf 1")
    assert c.phase == "STUCK"


def test_unknown_receipt_is_not_green():
    c = GroundtruthController([Predicate("p", "predicate")])
    c.start_task()
    c.begin_verify()
    c.record_receipt("p", "check", 0, "unknown", epoch=c.workspace_epoch)
    c.begin_submit()
    assert c.submit_decision() is False
    assert c.predicate_status("p") is PredicateStatus.UNKNOWN
