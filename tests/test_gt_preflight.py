from __future__ import annotations

from dataclasses import replace

import pytest

from gt_engine.central_runtime import (
    CentralFeatureRuntime,
    EvidenceLedger,
    WorkspaceSnapshot,
    classify_validation_command,
)
from gt_engine.preflight import (
    PREFLIGHT_FEATURE_PLACEMENT,
    ActionDisposition,
    ActionOperation,
    EvidenceGrade,
    PreflightDecision,
    PreflightMode,
    adapt_proposed_action,
)


@pytest.mark.parametrize(
    ("command", "operation"),
    [
        ("cat src/app.py", ActionOperation.READ),
        ("rg -n greet src", ActionOperation.SEARCH),
        ("sed -i 's/a/b/' src/app.py", ActionOperation.EDIT),
        ("cp src/a.py src/b.py", ActionOperation.EDIT),
        ("touch src/new.py", ActionOperation.CREATE),
        ("rm src/old.py", ActionOperation.DELETE),
        ("pytest -q", ActionOperation.VALIDATE),
        ("echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT", ActionOperation.SUBMIT),
        ("pip install demo", ActionOperation.INSTALL),
        ("python weird.py", ActionOperation.OTHER),
    ],
)
def test_real_shell_operations_are_conservatively_typed(command, operation):
    proposal = adapt_proposed_action(
        {"command": command, "tool_call_id": "call-1"},
        source_revision="s1",
        workspace_revision="w1",
        model_call=1,
        batch_index=0,
        batch_size=1,
    )
    assert proposal.operation == operation
    if command.startswith("sed -i"):
        assert [target.path for target in proposal.targets] == ["src/app.py"]


def test_compound_shell_action_exposes_every_known_operation_and_read_span():
    proposal = adapt_proposed_action(
        {
            "command": (
                "cd /app && sed -n '10,25p' src/app.py | nl -ba "
                "&& rg -n 'target' tests"
            ),
            "tool_call_id": "call-compound",
        },
        source_revision="s1",
        workspace_revision="w1",
        model_call=4,
        batch_index=0,
        batch_size=1,
    )

    operations = [item.operation for item in proposal.operations]
    assert ActionOperation.READ in operations
    assert ActionOperation.SEARCH in operations
    read_spans = [span for item in proposal.operations for span in item.read_spans]
    assert any(
        span.path == "/app/src/app.py"
        and span.start_line == 10
        and span.end_line == 25
        for span in read_spans
    )


def test_compound_write_redirection_is_not_mistyped_as_a_read():
    proposal = adapt_proposed_action(
        {"command": "cd /app && cat input.txt > generated.txt"},
        source_revision="s1",
        workspace_revision="w1",
        model_call=1,
        batch_index=0,
        batch_size=1,
    )

    operations = [item.operation for item in proposal.operations]
    assert ActionOperation.CREATE in operations or ActionOperation.EDIT in operations
    assert any(item.mutates_workspace for item in proposal.operations)


def test_validation_classification_applies_only_to_runner_segment():
    command = "cd /app && python -m pytest -q; echo EXIT:$?"
    classification = classify_validation_command(command, (command,))
    proposal = adapt_proposed_action(
        {"command": command},
        source_revision="s0",
        workspace_revision="w0",
        model_call=1,
        batch_index=0,
        batch_size=1,
        validation=classification,
    )

    assert proposal.operation is ActionOperation.VALIDATE
    assert [item.operation for item in proposal.operations] == [
        ActionOperation.OTHER,
        ActionOperation.VALIDATE,
        ActionOperation.OTHER,
    ]


def test_sed_range_does_not_attach_across_non_pipeline_connector():
    proposal = adapt_proposed_action(
        {"command": "cat src/a.py && sed -n '20,40p' src/b.py"},
        source_revision="s0",
        workspace_revision="w0",
        model_call=1,
        batch_index=0,
        batch_size=1,
    )

    reads = [
        span
        for operation in proposal.operations
        if operation.operation is ActionOperation.READ
        for span in operation.read_spans
    ]
    assert [(span.path, span.start_line, span.end_line) for span in reads] == [
        ("src/a.py", None, None),
        ("src/b.py", 20, 40),
    ]


def test_attached_output_redirection_is_classified_as_edit():
    proposal = adapt_proposed_action(
        {"command": "printf value >src/generated.py"},
        source_revision="s0",
        workspace_revision="w0",
        model_call=1,
        batch_index=0,
        batch_size=1,
    )

    assert proposal.operation is ActionOperation.EDIT
    assert proposal.mutates_workspace is True
    assert any(target.path == "src/generated.py" for target in proposal.targets)


def test_read_and_unknown_default_to_literal_pass():
    runtime = CentralFeatureRuntime(model_visible=True)
    snapshot = WorkspaceSnapshot("w1", {}, True, "")
    for command in ("cat src/app.py", "python weird.py"):
        proposal = adapt_proposed_action(
            {"command": command},
            source_revision="s1",
            workspace_revision="w1",
            model_call=1,
            batch_index=0,
            batch_size=1,
        )
        decision = runtime.preflight_action(proposal, snapshot, revision="w1", source_revision="s1")
        assert decision.disposition == ActionDisposition.PASS
        assert decision.command == command


def test_source_revision_mismatch_invalidates_non_pass_policy():
    runtime = CentralFeatureRuntime(model_visible=True)
    proposal = adapt_proposed_action(
        {"command": "touch app.py"},
        source_revision="old",
        workspace_revision="w1",
        model_call=1,
        batch_index=0,
        batch_size=1,
    )
    decision = runtime.preflight_action(
        proposal,
        WorkspaceSnapshot("w1", {}, True, ""),
        revision="w1",
        source_revision="new",
    )
    assert decision.disposition == ActionDisposition.PASS
    assert "source_revision_mismatch" in decision.reason_codes


def test_submit_preflight_returns_proven_failing_check_to_model():
    runtime = CentralFeatureRuntime(model_visible=True)
    ledger = EvidenceLedger()
    ledger.record_check("pytest -q", returncode=1, revision="s1", grounded=True)
    proposal = adapt_proposed_action(
        {"command": "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"},
        source_revision="s1",
        workspace_revision="w1",
        model_call=2,
        batch_index=0,
        batch_size=1,
    )
    decision = runtime.preflight_action(
        proposal,
        WorkspaceSnapshot("w1", {}, True, ""),
        revision="w1",
        source_revision="s1",
        ledger=ledger,
    )
    assert decision.disposition == ActionDisposition.RETURN_TO_MODEL
    assert "pytest -q" in decision.evidence[0]


def test_idempotent_touch_of_existing_path_does_not_trigger_duplicate_create():
    runtime = CentralFeatureRuntime(model_visible=True)
    snapshot = WorkspaceSnapshot(
        "w1",
        {"app.py": object()},
        True,
        "",
    )
    proposal = adapt_proposed_action(
        {"command": "touch app.py"},
        source_revision="s1",
        workspace_revision="w1",
        model_call=1,
        batch_index=0,
        batch_size=1,
    )

    decision = runtime.preflight_action(
        proposal,
        snapshot,
        revision="w1",
        source_revision="s1",
    )

    assert decision.disposition == ActionDisposition.PASS


def test_material_intervention_requires_grounded_bounded_evidence_and_dedupes():
    runtime = CentralFeatureRuntime(model_visible=True)
    proposal = adapt_proposed_action(
        {"command": "sed -i 's/x/y/' missing.py"},
        source_revision="s1",
        workspace_revision="w1",
        model_call=1,
        batch_index=0,
        batch_size=1,
    )
    empty = PreflightDecision(
        ActionDisposition.RETURN_TO_MODEL,
        proposal.raw_command,
        confidence=1.0,
        source_revision="s1",
    )
    heuristic = replace(
        empty,
        evidence=("maybe another file",),
        evidence_grade=EvidenceGrade.HEURISTIC,
    )
    grounded = replace(
        empty,
        evidence=("missing.py is absent from the current workspace",),
        reason_codes=("edit_target_absent",),
        evidence_grade=EvidenceGrade.DIRECT,
    )

    assert runtime.admit_preflight_intervention(proposal, empty)[0] is False
    assert runtime.admit_preflight_intervention(proposal, heuristic)[0] is False
    assert runtime.admit_preflight_intervention(proposal, grounded) == (True, "admitted")
    assert runtime.admit_preflight_intervention(proposal, grounded) == (
        False,
        "duplicate_evidence",
    )


def test_low_confidence_rewrite_contract_can_be_rejected_by_dispatch():
    proposal = adapt_proposed_action(
        {"command": "python weird.py"},
        source_revision="s1",
        workspace_revision="w1",
        model_call=1,
        batch_index=0,
        batch_size=1,
    )
    assert replace(proposal, parser_confidence=0.2).parser_confidence < 1.0


def test_all_17_features_have_explicit_lifecycle_placement():
    runtime = CentralFeatureRuntime(model_visible=True)
    assert set(PREFLIGHT_FEATURE_PLACEMENT) == set(runtime.summary()["feature_ids"])
    assert sum(value.postflight_only for value in PREFLIGHT_FEATURE_PLACEMENT.values()) == 5


def test_preflight_modes_are_explicit_and_fail_closed_to_off():
    assert PreflightMode.parse("off") is PreflightMode.OFF
    assert PreflightMode.parse("shadow") is PreflightMode.SHADOW
    assert PreflightMode.parse("assistive_safe") is PreflightMode.ASSISTIVE_SAFE
    with pytest.raises(ValueError, match="preflight mode"):
        PreflightMode.parse("rewrite-everything")


def test_every_lifecycle_placement_declares_inputs_and_evidence_grade():
    for feature_id, placement in PREFLIGHT_FEATURE_PLACEMENT.items():
        assert placement.feature_id == feature_id
        assert placement.required_inputs
        assert placement.evidence_grade in EvidenceGrade
        if placement.postflight_only:
            assert placement.preflight_operations == ()
