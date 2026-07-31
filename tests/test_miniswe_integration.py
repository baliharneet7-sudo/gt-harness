from __future__ import annotations

import json

from gt_engine.miniswe_controller import Predicate
from gt_engine.miniswe_integration import MiniSweAdapter


def test_adapter_external_state_and_provider_binding(tmp_path):
    a = MiniSweAdapter(
        task_id="task-1",
        state_dir=tmp_path,
        predicates=[Predicate("syntax", "syntax")],
    )
    a.start_task()
    a.begin_verify()
    a.record_receipt("syntax", "python -m py_compile x.py", 0, "ok", epoch=0)
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
