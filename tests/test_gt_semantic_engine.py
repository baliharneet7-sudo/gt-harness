from __future__ import annotations

from gt_engine.central_runtime import CentralFeatureRuntime, WorkspaceTransition
from gt_engine.provider_view import build_provider_view
from gt_engine.semantic_decisions import (
    DecisionNeedKind,
    SemanticClaimKind,
    SemanticDecisionEngine,
)


def test_pending_claim_survives_an_unrelated_higher_priority_frame():
    engine = SemanticDecisionEngine(max_frame_chars=320)
    engine.upsert_claim(
        feature_id="signature_delta",
        kind=SemanticClaimKind.IMPACT,
        fact="Signature changed for greet in app.py; inspect callers in cli.py.",
        anchors=("app.py:greet", "cli.py:12"),
        source_revision="r1",
        evidence_action=1,
    )
    engine.upsert_claim(
        feature_id="syntax_result",
        kind=SemanticClaimKind.FAILURE,
        fact="Syntax check failed for app.py: invalid syntax at line 4.",
        anchors=("app.py:4",),
        source_revision="r1",
        evidence_action=1,
    )
    engine.open_need(
        kind=DecisionNeedKind.REPAIR_FAILURE,
        source_revision="r1",
        created_after_action=1,
        required_claim_kinds=(SemanticClaimKind.FAILURE,),
    )

    failure = engine.materialize(call=2, source_revision="r1")

    assert failure is not None
    assert failure.feature_ids == ("syntax_result",)
    engine.resolve_need(failure.need_id, resolution="source_changed")
    engine.open_need(
        kind=DecisionNeedKind.REPAIR_IMPACT,
        source_revision="r1",
        created_after_action=1,
        required_claim_kinds=(SemanticClaimKind.IMPACT,),
    )

    impact = engine.materialize(call=3, source_revision="r1")

    assert impact is not None
    assert impact.feature_ids == ("signature_delta",)
    assert "cli.py" in impact.text


def test_task_start_localization_is_available_before_the_first_model_call():
    runtime = CentralFeatureRuntime(model_visible=True)
    runtime.begin_task("Fix greet output", revision="r0", source_revision="s0")
    runtime.register_structural_evidence(
        source_revision="s0",
        anchors=(
            {"path": "src/app.py", "line": 4, "symbol": "greet"},
            {"path": "tests/test_app.py", "line": 9, "symbol": "test_greet"},
        ),
        callers=({"path": "src/cli.py", "line": 12, "symbol": "main"},),
        graph_revision="graph-1",
    )

    feedback = runtime.model_feedback()
    prepared = runtime.prepared_guidance()

    assert "src/app.py:4" in feedback
    assert prepared is None
    receipt = next(
        row for row in runtime.summary()["receipts"] if row["feature_id"] == "GT_LOC_RESLOT"
    )
    assert receipt["action"] == 0
    assert receipt["source_revision"] == "s0"


def test_same_boundary_syntax_and_signature_claims_are_coalesced_not_destroyed():
    runtime = CentralFeatureRuntime(model_visible=True)
    runtime.begin_task("Change greet signature", revision="r0", source_revision="s0")
    runtime.observe_action(
        action_id=1,
        command="sed -i 's/def greet(/def greet(name, /' app.py",
        output="",
        returncode=0,
        transition=WorkspaceTransition(
            1,
            "edit",
            "r0",
            "r1",
            modified=("app.py",),
            before_contents={"app.py": "def greet():\n    return 'hi'\n"},
            after_contents={"app.py": "def greet(name):\n    return f'hi {name}'\n"},
        ),
        revision="r1",
        source_revision="s1",
    )
    runtime.record_syntax(
        action_id=1,
        revision="r1",
        source_revision="s1",
        failed=True,
        reason="changed_file_syntax_failure",
        path="app.py",
        command="python3 -m py_compile app.py",
        returncode=1,
        diagnostic="SyntaxError at app.py:1",
    )

    first = runtime.model_feedback()
    assert "Syntax check failed" in first
    assert "Signature changed for greet" in first

    runtime.observe_action(
        action_id=2,
        command="sed -n '1,80p' app.py",
        output="def greet(name):\n",
        returncode=0,
        transition=WorkspaceTransition(2, "read", "r1", "r1"),
        revision="r1",
        source_revision="s1",
    )
    second = runtime.model_feedback()

    assert second == ""


def test_provider_view_compacts_only_tool_bodies_and_accounts_private_state():
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "fix greet and run pytest"},
    ]
    for index in range(8):
        messages.extend(
            [
                {
                    "role": "assistant",
                    "content": "reasoning " + ("x" * 80),
                    "tool_calls": [
                        {
                            "id": f"call-{index}",
                            "type": "function",
                            "function": {
                                "name": "bash",
                                "arguments": f'{{"command":"cat file{index}.py"}}',
                            },
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": f"call-{index}",
                    "content": f"failure output {index} " + ("y" * 120),
                },
            ]
        )

    view, metrics = build_provider_view(
        messages,
        active_state={
            "obligations": ["run pytest"],
            "changed_paths": ["app.py"],
            "latest_failure": "pytest -q failed at tests/test_app.py:9",
        },
        trigger_chars=600,
        target_chars=400,
        keep_recent_turns=2,
    )

    assert view[0] == messages[0]
    assert view[1] == messages[1]
    assert metrics.compacted is True
    assert metrics.output_chars < metrics.input_chars
    assert "tests/test_app.py:9" not in str(view)
    failure_fact = next(
        row for row in metrics.fact_accounting if row["state_key"] == "latest_failure"
    )
    assert failure_fact["disposition"] == "no_compaction_controller_only"
    assert [item["content"] for item in view if item["role"] == "assistant"] == [
        item["content"] for item in messages if item["role"] == "assistant"
    ]
    assert metrics.unique_assistant_reasoning_chars_removed == 0
    assert view[-4:] == messages[-4:]
    assert all(
        not (message.get("role") == "tool") or message.get("tool_call_id")
        for message in view
        if message.get("role") == "tool"
    )


def test_effect_accountability_counts_engine_state_work_separately_from_unread_state():
    runtime = CentralFeatureRuntime(model_visible=True)
    runtime.begin_task("Fix greet", revision="r0", source_revision="s0")
    runtime.consume_effects(action_id=0, call=0)

    summary = runtime.summary()
    obligation = next(
        row for row in summary["effect_accountability"] if row["feature_id"] == "obligations"
    )

    assert obligation["outcome"] == "engine_internal_state"
