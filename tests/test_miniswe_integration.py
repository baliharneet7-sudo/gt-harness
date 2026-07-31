from __future__ import annotations

import json

from gt_engine.miniswe_controller import Predicate
from gt_engine.miniswe_integration import MiniSweAdapter
from gt_engine.task_contract import Obligation, TaskContract
from gt_engine.verification_contract import compile_obligation_predicates


def test_adapter_external_state_and_provider_binding(tmp_path):
    a = MiniSweAdapter(
        task_id="task-1",
        state_dir=tmp_path,
        predicates=[Predicate("syntax", "syntax")],
    )
    a.start_task()
    a.begin_verify()
    a.record_receipt("syntax", "python -m py_compile x.py", 0, "ok", epoch=0,
                     semantic=True)
    a.begin_submit()
    payload = a.bind_provider_payload({
        "model": "deepseek-v4-flash",
        "messages": [{"role": "user", "content": a.provider_suffix()}],
    })
    assert payload.request_id.startswith("task-1-")
    assert payload.payload_sha256
    assert a.submit_decision() is True
    rows = [json.loads(x) for x in (tmp_path / "task-1" / "events.jsonl").read_text().splitlines()]
    assert any(row["event"] == "provider_delivery" for row in rows)
    assert any(row["event"] == "state" for row in rows)


def test_adapter_rejects_provider_payload_without_messages(tmp_path):
    a = MiniSweAdapter(task_id="task", state_dir=tmp_path, predicates=[])
    a.start_task()
    try:
        a.bind_provider_payload({"model": "deepseek-v4-flash"})
    except ValueError as exc:
        assert "messages" in str(exc)
    else:
        raise AssertionError("missing provider messages was accepted")


def test_adapter_evaluates_semantic_predicates_from_real_observation(tmp_path):
    contract = TaskContract(
        "ARTIFACT",
        (Obligation("obl-1", "Create output.json artifact.", "test"),),
    )
    predicate_id = next(
        iter(compile_obligation_predicates(contract).values())
    ).predicate_id
    a = MiniSweAdapter(
        task_id="task",
        state_dir=tmp_path,
        predicates=[Predicate(predicate_id, "output.json exists")],
        contract=contract,
    )
    a.start_task()
    a.begin_verify()
    receipts = a.evaluate_observation(
        "test -f output.json", "output.json exists", returncode=0, action_index=1
    )
    assert receipts == (predicate_id,)
    assert a.predicate_status(predicate_id).value == "GREEN"


def test_provider_suffix_is_stable_until_state_changes(tmp_path):
    a = MiniSweAdapter(
        task_id="task",
        state_dir=tmp_path,
        predicates=[Predicate("p", "predicate")],
    )
    a.start_task()
    first = a.provider_suffix()
    second = a.provider_suffix()
    assert first == second
    a.note_edit(["x.py"])
    assert a.provider_suffix() != first


def test_provider_control_delta_is_empty_when_state_is_unchanged(tmp_path):
    a = MiniSweAdapter(
        task_id="task",
        state_dir=tmp_path,
        predicates=[Predicate("p", "predicate")],
    )
    a.start_task()
    assert a.next_provider_suffix()
    assert a.next_provider_suffix() == ""
    a.note_edit(["x.py"])
    assert a.next_provider_suffix()
