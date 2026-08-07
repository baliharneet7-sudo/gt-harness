"""Provider-view dedup and smart-compaction contract tests."""

from __future__ import annotations

from gt_engine.central_runtime import (
    CentralFeatureRuntime,
    WorkspaceTransition,
    classify_validation_command,
)
from gt_engine.preflight import adapt_proposed_action
from gt_engine.provider_view import (
    ProviderViewSession,
    RequestBudget,
    build_provider_view,
    dedupe_provider_view,
    provider_compaction_required,
    provider_request_budget,
)


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


def test_provider_view_session_is_byte_identical_before_budget_compaction():
    messages = _history(("cat app.py", "x" * 30_000))
    session = ProviderViewSession()

    view, metrics = session.project(messages, active_state={"source_revision": "s1"})

    assert view == messages
    assert metrics.compacted is False
    assert session.epoch == 0


def test_provider_view_session_reuses_an_immutable_compacted_prefix():
    messages = _history(
        ("cat old.py", "A" * 30_000),
        ("cat current.py", "B" * 30_000),
        ("cat newest.py", "C" * 30_000),
    )
    session = ProviderViewSession()

    compacted, metrics = session.compact(
        messages,
        active_state={"source_revision": "s1"},
        target_chars=45_000,
        keep_recent_turns=1,
        trigger_tokens=900_000,
    )
    stable_checkpoint = [dict(item) for item in session.checkpoint_messages]
    appended = [*messages, *_turn("cat later.py", "D" * 100, index=4)]

    projected, projected_metrics = session.project(
        appended,
        active_state={"source_revision": "s2", "changed_paths": ["later.py"]},
    )

    assert session.epoch == 1
    assert session.receipts[0].reasoning_messages_removed == 0
    assert session.checkpoint_messages == stable_checkpoint
    assert projected_metrics.compacted is False
    assert projected[-1]["content"] == "D" * 100


def test_provider_view_session_refreshes_current_frame_without_mutating_checkpoint():
    messages = _history(
        ("cat old.py", "A" * 30_000),
        ("cat current.py", "B" * 30_000),
        ("cat newest.py", "C" * 30_000),
    )
    session = ProviderViewSession()
    first_state = {
        "source_revision": "s1",
        "unresolved_failure": {
            "command": "pytest -q",
            "diagnostic": "FAILED first_contract",
            "source_revision": "s1",
        },
    }

    first, first_metrics = session.compact(
        messages,
        active_state=first_state,
        target_chars=45_000,
        keep_recent_turns=1,
        trigger_tokens=900_000,
    )
    checkpoint = [dict(item) for item in session.checkpoint_messages]
    second_state = {
        "source_revision": "s2",
        "unresolved_failure": {
            "command": "pytest -q",
            "diagnostic": "FAILED second_contract",
            "source_revision": "s2",
        },
    }
    second, second_metrics = session.project(messages, active_state=second_state)

    assert first_metrics.selected_fact_count == 1
    assert "FAILED first_contract" in str(first[first_metrics.state_frame_message_index])
    assert second_metrics.selected_fact_count == 1
    assert "FAILED second_contract" in str(second[second_metrics.state_frame_message_index])
    assert "FAILED first_contract" not in "\n".join(
        str(item.get("content") or "") for item in second
    )
    assert session.checkpoint_messages == checkpoint


def test_provider_compaction_trigger_is_based_on_measured_headroom():
    safe = RequestBudget(1_048_576, 700_000, 700_000, 700_000, 943_718, 243_718, "test")
    risky = RequestBudget(1_048_576, 850_000, 850_000, 850_000, 943_718, 93_718, "test")

    assert provider_compaction_required(safe, reserve_tokens=131_072) is False
    assert provider_compaction_required(risky, reserve_tokens=131_072) is True


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


def test_dedupe_keeps_same_text_when_tool_status_differs():
    messages = _history(("pytest -q", "same output"), ("pytest -q", "same output"))
    tools = [item for item in messages if item.get("role") == "tool"]
    tools[0]["extra"] = {"returncode": 0}
    tools[1]["extra"] = {"returncode": 1}

    deduped = dedupe_provider_view(messages)

    assert len([item for item in deduped if item.get("role") == "assistant"]) == 2
    assert len([item for item in deduped if item.get("role") == "tool"]) == 2


def test_dedupe_never_deletes_distinct_miniswe_reasoning():
    messages = _history(
        ("cat a.py", "SAME BODY"),
        ("cat a.py", "SAME BODY"),
    )
    assistants = [item for item in messages if item.get("role") == "assistant"]
    assistants[0]["content"] = "First hypothesis: parser A owns this behavior."
    assistants[0]["reasoning_content"] = "reasoning A"
    assistants[1]["content"] = "Second hypothesis: parser B owns this behavior."
    assistants[1]["reasoning_content"] = "reasoning B"

    deduped = dedupe_provider_view(messages)

    kept = [item for item in deduped if item.get("role") == "assistant"]
    assert [item["content"] for item in kept] == [
        "First hypothesis: parser A owns this behavior.",
        "Second hypothesis: parser B owns this behavior.",
    ]


def test_duplicate_is_represented_below_tool_clearing_trigger():
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

    assert metrics.compacted is True
    assert metrics.duplicate_turns_removed == 0
    assert metrics.duplicate_turns_represented == 1
    tool_contents = [m.get("content") for m in view if m.get("role") == "tool"]
    assert tool_contents[0] == "X" * 50
    assert "Exact duplicate of prior action" in tool_contents[1]


def test_observation_only_compiler_preserves_duplicate_history_exactly():
    messages = _history(
        ("cat a.py", "X" * 50),
        ("cat a.py", "X" * 50),
    )

    view, metrics = build_provider_view(
        messages,
        active_state={"source_revision": "s1"},
        trigger_chars=1,
        target_chars=1,
        transform=False,
    )

    assert view == messages
    assert metrics.compacted is False
    assert metrics.duplicate_turns_removed == 0
    assert metrics.input_chars == metrics.output_chars


def test_compiler_proves_existing_read_fact_at_exact_provider_message():
    messages = _history(("cat src/app.py", "def run(): pass"))
    state = {
        "source_revision": "s1",
        "workspace_revision": "w1",
        "recent_reads": [
            {
                "path": "src/app.py",
                "source_revision": "s1",
                "workspace_revision": "w1",
                "action_id": 1,
                "returncode": 0,
            }
        ],
    }

    view, metrics = build_provider_view(
        messages,
        active_state=state,
        trigger_chars=10**18,
        target_chars=10**18,
    )

    read_rows = [
        row for row in metrics.fact_accounting if row["kind"] == "read"
    ]
    assert len(read_rows) == 1
    assert read_rows[0]["disposition"] == "represented_message"
    assert read_rows[0]["provider_message_indices"] == [1, 2]
    assert metrics.represented_fact_count == 1
    assert metrics.accounted_fact_count == metrics.candidate_fact_count
    assert view == messages


def test_compiler_canonicalizes_app_absolute_and_repository_relative_paths():
    messages = _history(("sed -n '1,80p' src/app.py", "def run(): pass"))
    state = {
        "source_revision": "s1",
        "workspace_revision": "w1",
        "recent_reads": [
            {
                "path": "/app/src/app.py",
                "source_revision": "s1",
                "workspace_revision": "w1",
                "action_id": 1,
                "returncode": 0,
            }
        ],
    }

    view, metrics = build_provider_view(
        messages,
        active_state=state,
        trigger_chars=10**18,
        target_chars=10**18,
    )

    row = next(item for item in metrics.fact_accounting if item["kind"] == "read")
    assert row["disposition"] == "represented_message"
    assert row["provider_message_indices"] == [1, 2]
    assert view == messages


def test_compiler_emits_missing_current_failure_but_not_private_revisions():
    messages = _history(("cat src/app.py", "def run(): pass"))
    state = {
        "source_revision": "s2",
        "workspace_revision": "w2",
        "unresolved_failure": {
            "command": "pytest -q",
            "diagnostic": "FAILED tests/test_app.py::test_contract",
            "source_revision": "s2",
            "workspace_revision": "w2",
            "action_id": 2,
        },
    }

    view, metrics = build_provider_view(
        messages,
        active_state=state,
        trigger_chars=10**18,
        target_chars=10**18,
    )

    joined = "\n".join(str(item.get("content") or "") for item in view)
    assert "FAILED tests/test_app.py::test_contract" not in joined
    failure = next(row for row in metrics.fact_accounting if row["kind"] == "failure")
    revisions = [row for row in metrics.fact_accounting if row["kind"] == "revision"]
    assert failure["disposition"] == "no_compaction_controller_only"
    assert failure["provider_message_indices"] == []
    assert all(row["disposition"] == "controller_only" for row in revisions)
    assert metrics.selected_fact_count == 0
    assert metrics.controller_only_fact_count == 2
    assert metrics.accounted_fact_count == metrics.candidate_fact_count


def test_below_compaction_trigger_preserves_provider_messages_byte_for_byte():
    messages = _history(("cat src/app.py", "def run(): pass"))
    state = {
        "source_revision": "s2",
        "workspace_revision": "w2",
        "unresolved_failure": {
            "command": "pytest -q",
            "diagnostic": "FAILED tests/test_app.py::test_contract",
            "source_revision": "s2",
            "workspace_revision": "w2",
            "action_id": 2,
        },
    }

    view, metrics = build_provider_view(
        messages,
        active_state=state,
        trigger_chars=10**18,
        target_chars=10**18,
    )

    assert view == messages
    assert metrics.compacted is False
    assert metrics.selected_fact_count == 0
    assert metrics.accounted_fact_count == metrics.candidate_fact_count


def test_tool_clearing_keeps_controller_state_private_and_never_deletes_reasoning():
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
    # Current state is retained once old tool bodies are cleared.
    assert "Latest source edit" in joined
    assert "Files already read" in joined
    assert "rerun the command" not in joined.lower()
    assert metrics.old_tool_results_cleared > 0
    assert metrics.unique_assistant_reasoning_chars_removed == 0
    assert metrics.accounted_fact_count == metrics.candidate_fact_count
    # Recent tool turns stay verbatim.
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


def test_progress_ledger_records_real_compound_read_operations():
    runtime = CentralFeatureRuntime(model_visible=True)
    runtime.begin_task("Inspect app.py.", revision="w0", source_revision="s0")
    proposal = adapt_proposed_action(
        {"command": "cd /app && nl -ba src/app.py | sed -n '20,40p'"},
        source_revision="s0",
        workspace_revision="w0",
        model_call=1,
        batch_index=0,
        batch_size=1,
    )

    runtime.observe_action(
        action_id=1,
        command=proposal.raw_command,
        output="20 line\n21 line\n",
        returncode=0,
        transition=WorkspaceTransition(1, proposal.raw_command, "w0", "w0"),
        revision="w0",
        source_revision="s0",
        proposed=proposal,
    )

    reads = runtime.progress_ledger()["recent_reads"]
    assert reads
    assert reads[-1]["path"] == "/app/src/app.py"
    assert reads[-1]["source_revision"] == "s0"
    assert reads[-1]["start_line"] == 20
    assert reads[-1]["end_line"] == 40
    assert reads[-1]["output_hash"]


def test_active_state_budget_accounts_validation_and_failure_without_ephemeral_frame():
    messages = [{"role": "user", "content": "task"}]
    for index in range(4):
        messages.extend(_turn(f"cat file{index}.py", "body" * 100, index=index))
    state = {
        "source_revision": "s9",
        "last_edit": {
            "command": "cat <<'EOF' > app.py\n" + ("x" * 20_000) + "\nEOF",
            "paths": ["app.py"],
            "source_revision": "s9",
        },
        "latest_validation": {
            "command": "pytest -q",
            "returncode": 1,
            "source_revision": "s9",
        },
        "unresolved_failure": {
            "command": "pytest -q",
            "diagnostic": "FAILED tests/test_app.py::test_contract",
            "source_revision": "s9",
        },
    }

    view, _metrics = build_provider_view(
        messages,
        active_state=state,
        trigger_chars=1,
        target_chars=50_000,
    )
    joined = "\n".join(str(item.get("content") or "") for item in view)

    assert "pytest -q" not in joined
    assert "FAILED tests/test_app.py::test_contract" not in joined
    assert "x" * 1_000 not in joined
    assert _metrics.accounted_fact_count == _metrics.candidate_fact_count
    assert _metrics.selected_fact_count == 0


def test_compaction_retains_missing_current_failure_in_latest_tool_observation():
    messages = _history(
        ("cat old.py", "old output" * 200),
        ("cat current.py", "current output" * 200),
        ("cat third.py", "third output" * 200),
        ("cat fourth.py", "fourth output" * 200),
    )
    state = {
        "source_revision": "s9",
        "unresolved_failure": {
            "command": "pytest -q",
            "diagnostic": "FAILED tests/test_app.py::test_contract",
            "source_revision": "s9",
        },
    }

    view, metrics = build_provider_view(
        messages,
        active_state=state,
        trigger_chars=1,
        target_chars=100,
    )

    assert metrics.old_tool_results_cleared > 0
    assert metrics.active_state_chars > 0
    assert metrics.selected_fact_count == 1
    assert metrics.state_frame_message_index is not None
    assert "FAILED tests/test_app.py::test_contract" in str(
        view[metrics.state_frame_message_index].get("content") or ""
    )
    selected = next(
        row for row in metrics.fact_accounting if row["disposition"] == "selected_state_frame"
    )
    assert selected["provider_message_indices"] == [metrics.state_frame_message_index]


def test_compaction_never_removes_distinct_assistant_reasoning():
    messages = _history(
        ("cat a.py", "A" * 500),
        ("cat b.py", "B" * 500),
        ("cat c.py", "C" * 500),
    )
    assistants = [item for item in messages if item.get("role") == "assistant"]
    for index, item in enumerate(assistants):
        item["content"] = f"public reasoning {index}"
        item["reasoning_content"] = f"private reasoning {index}"

    view, metrics = build_provider_view(
        messages,
        active_state={},
        trigger_chars=1,
        target_chars=400,
    )

    kept = [item for item in view if item.get("role") == "assistant"]
    assert [item.get("content") for item in kept] == [
        "public reasoning 0",
        "public reasoning 1",
        "public reasoning 2",
    ]
    assert [item.get("reasoning_content") for item in kept] == [
        "private reasoning 0",
        "private reasoning 1",
        "private reasoning 2",
    ]
    assert metrics.unique_assistant_reasoning_chars_removed == 0


def test_recent_oversized_observation_is_bounded_even_when_it_is_the_only_turn():
    huge = "TRACE\n" + ("diagnostic line\n" * 200_000)
    messages = _history(("cat dbg_trace.txt", huge))

    view, metrics = build_provider_view(
        messages,
        active_state={},
        trigger_chars=280_000,
        target_chars=200_000,
    )

    tool = next(item for item in view if item.get("role") == "tool")
    assert len(tool["content"]) <= 21_000
    assert "Tool output bounded by host" in tool["content"]
    assert "sha256=" in tool["content"]
    assert metrics.output_chars < 200_000


def test_duplicate_turn_is_represented_append_only_instead_of_deleting_history():
    messages = _history(
        ("cat a.py", "SAME BODY"),
        ("cat a.py", "SAME BODY"),
    )

    view, metrics = build_provider_view(
        messages,
        active_state={},
        trigger_chars=10**18,
        target_chars=10**18,
    )

    assistants = [item for item in view if item.get("role") == "assistant"]
    tools = [item for item in view if item.get("role") == "tool"]
    assert len(assistants) == 2
    assert len(tools) == 2
    assert tools[0]["content"] == "SAME BODY"
    assert "Exact duplicate of prior action" in tools[1]["content"]
    assert metrics.duplicate_turns_removed == 0


def test_provider_request_budget_fails_closed_before_provider_overflow():
    budget = provider_request_budget(
        [{"role": "tool", "content": "x" * 20_000}],
        model_name="unknown-test-model",
        context_limit_tokens=10_000,
        hard_ratio=0.90,
    )

    assert budget.within_limit is False
    assert budget.hard_prompt_limit == 9_000
    assert budget.effective_tokens >= budget.conservative_tokens
    assert budget.remaining_tokens < 0
