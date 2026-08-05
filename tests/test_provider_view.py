"""Provider-view dedup and smart-compaction contract tests."""

from __future__ import annotations

from gt_engine.central_runtime import (
    CentralFeatureRuntime,
    WorkspaceTransition,
    classify_validation_command,
)
from gt_engine.provider_view import build_provider_view, dedupe_provider_view


def _turn(command: str, output: str, *, index: int) -> list[dict]:
    tool_id = f"call-{index}"
    return [
        {
            "role": "assistant",
            "content": "act",
            "extra": {"actions": [{"command": command, "tool_call_id": tool_id}]},
        },
        {"role": "tool", "tool_call_id": tool_id, "content": output},
    ]


def _history(*turns) -> list[dict]:
    messages = [{"role": "user", "content": "task"}]
    for index, (command, output) in enumerate(turns):
        messages.extend(_turn(command, output, index=index))
    return messages


def test_dedupe_drops_identical_duplicate_turns_and_keeps_latest():
    messages = _history(
        ("cat a.py", "SAME BODY"),
        ("cat a.py", "SAME BODY"),
        ("grep foo a.py", "match"),
    )

    deduped = dedupe_provider_view(messages)

    commands = [
        (m.get("extra") or {}).get("actions") or []
        for m in deduped
        if m.get("role") == "assistant"
    ]
    flattened = [a.get("command") for group in commands for a in group]
    assert flattened == ["cat a.py", "grep foo a.py"]
    contents = [m.get("content") for m in deduped if m.get("role") == "tool"]
    assert contents == ["SAME BODY", "match"]
    # Protocol: every tool message still follows its assistant tool_call.
    roles = [m.get("role") for m in deduped]
    assert roles == ["user", "assistant", "tool", "assistant", "tool"]


def test_dedupe_keeps_distinct_turns_untouched():
    messages = _history(
        ("cat a.py", "AAA"),
        ("cat b.py", "BBB"),
    )

    deduped = dedupe_provider_view(messages)

    assert len(deduped) == len(messages)


def test_dedupe_runs_below_compaction_trigger():
    messages = _history(
        ("cat a.py", "X" * 50),
        ("cat a.py", "X" * 50),
    )
    view, metrics = build_provider_view(
        messages,
        active_state={},
        trigger_chars=10**18,
        target_chars=10**18,
    )

    assert metrics.compacted is False
    assert metrics.duplicate_turns_removed == 1
    tool_contents = [m.get("content") for m in view if m.get("role") == "tool"]
    assert tool_contents == ["X" * 50]


def test_smart_compaction_summarizes_progress_and_never_tells_model_to_rerun():
    messages = [{"role": "user", "content": "task"}]
    for index in range(20):
        messages.extend(_turn(f"cat file{index}.py", "B" * 200, index=index))

    active_state = {
        "last_edit": {
            "command": "write app.py",
            "paths": ["app.py"],
            "source_revision": "s7",
        },
        "latest_validation": {"command": "pytest -q", "returncode": 0, "source_revision": "s7"},
        "unresolved_failure": {
            "command": "pytest -q",
            "fingerprint": "abc",
            "diagnostic": "1 failed: assert x",
        },
        "recent_reads": ["a.py", "b.py"],
        "changed_paths": ["app.py"],
        "declared_checks": {"pytest -q": "passed"},
    }

    view, metrics = build_provider_view(
        messages,
        active_state=active_state,
        trigger_chars=200,
        target_chars=150,
    )

    assert metrics.compacted is True
    joined = " ".join(str(m.get("content") or "") for m in view)
    # The typed progress ledger is injected...
    assert "Latest source edit" in joined
    assert "write app.py" in joined
    assert "Files already read" in joined
    assert "a.py" in joined
    # ...and the model is never told to rerun a completed command.
    assert "rerun the command" not in joined.lower()
    # Recent turns stay verbatim.
    tail = " ".join(str(m.get("content") or "") for m in view[-4:])
    assert "B" * 200 in tail


def test_progress_ledger_tracks_last_edit_validation_and_failure():
    runtime = CentralFeatureRuntime(model_visible=True)
    runtime.begin_task("Run `pytest -q`.", revision="w0", source_revision="s0")
    runtime.observe_action(
        action_id=1,
        command="write app.py",
        output="",
        returncode=0,
        transition=WorkspaceTransition(
            1, "write", "w0", "w1", modified=("app.py",)
        ),
        revision="w1",
        source_revision="s1",
    )
    classification = classify_validation_command("pytest -q", ("pytest -q",)).with_result(
        result_code=1,
        output="1 failed: assert x",
        source_revision="s1",
        workspace_revision="w1",
    )
    runtime.observe_action(
        action_id=2,
        command="pytest -q",
        output="1 failed: assert x",
        returncode=1,
        transition=WorkspaceTransition(2, "pytest -q", "w1", "w1"),
        revision="w1",
        source_revision="s1",
        validation=classification,
    )

    ledger = runtime.progress_ledger()

    assert ledger["last_edit"]["paths"] == ["app.py"]
    assert ledger["latest_validation"]["returncode"] == 1
    assert ledger["unresolved_failure"]["diagnostic"] == "1 failed: assert x"
    assert "app.py" in ledger["changed_paths"]
