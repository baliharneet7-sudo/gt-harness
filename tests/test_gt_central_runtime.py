from __future__ import annotations

import pytest

from gt_engine.central_runtime import (
    CENTRAL_FEATURE_IDS,
    CentralFeatureRuntime,
    EvidenceLedger,
    FileState,
    InterventionDecision,
    WorkspaceSensor,
    WorkspaceSnapshot,
    WorkspaceTransition,
    diff_snapshots,
    parse_manifest,
    render_runtime_feedback,
)
from scripts.central_feature_census import census


def _snapshot(revision: str, **entries: FileState) -> WorkspaceSnapshot:
    return WorkspaceSnapshot(revision=revision, entries=entries, healthy=True)


def test_manifest_and_diff_are_non_git_and_cross_language():
    before = parse_manifest("f\t10\t1.0\t1.0\tsrc/a.js\t\nf\t20\t1.0\t1.0\tmain.c\t\n")
    after = parse_manifest("f\t11\t2.0\t2.0\tsrc/a.js\t\nf\t7\t2.0\t2.0\tjob.cob\t\n")

    transition = diff_snapshots(before, after, action_id=3, command="apply edits")

    assert transition.modified == ("src/a.js",)
    assert transition.created == ("job.cob",)
    assert transition.deleted == ("main.c",)
    assert transition.changed_paths == ("job.cob", "main.c", "src/a.js")


def test_ctime_detects_same_size_rewrite_even_when_mtime_is_preserved():
    before = _snapshot("r1", **{"same.py": FileState("f", 4, "1.0", "1.0", "")})
    after = _snapshot("r2", **{"same.py": FileState("f", 4, "1.0", "2.0", "")})

    transition = diff_snapshots(before, after, action_id=1, command="rewrite")

    assert transition.modified == ("same.py",)


def test_failed_grounded_check_holds_once_then_fails_open():
    ledger = EvidenceLedger(max_holds=1)
    ledger.record_check("pytest -q", returncode=1, revision="r1", grounded=True)

    first = ledger.submit_decision("r1")
    second = ledger.submit_decision("r1")

    assert first.decision == InterventionDecision.HOLD_ONCE
    assert second.decision == InterventionDecision.PASS


def test_passing_rerun_clears_failure_without_revision_change():
    ledger = EvidenceLedger(max_holds=1)
    ledger.record_check("pytest -q", returncode=1, revision="r1", grounded=True)
    ledger.record_check("pytest -q", returncode=0, revision="r1", grounded=True)

    assert ledger.submit_decision("r1").decision == InterventionDecision.PASS


def test_edit_makes_old_failure_stale_and_unrelated_failure_never_blocks():
    ledger = EvidenceLedger(max_holds=1)
    ledger.record_check("pytest -q", returncode=1, revision="r1", grounded=True)
    ledger.record_check("curl bad-host", returncode=1, revision="r2", grounded=False)

    assert ledger.submit_decision("r2").decision == InterventionDecision.PASS


def test_degraded_sensor_disables_hard_decisions():
    ledger = EvidenceLedger(max_holds=1)
    ledger.record_check("pytest -q", returncode=1, revision="r1", grounded=True)

    assert ledger.submit_decision("r1", sensor_healthy=False).decision == (
        InterventionDecision.PASS
    )


def test_feedback_is_concise_and_contains_no_private_runtime_identifier():
    text = render_runtime_feedback("x" * 1_000)

    assert len(text) <= 320
    assert "groundtruth" not in text.lower()
    assert "gt_" not in text.lower()


def test_all_seventeen_central_features_have_real_trigger_receipts():
    runtime = CentralFeatureRuntime(model_visible=True)
    runtime.begin_task("Implement the requested change", revision="r0")
    runtime.observe_action(
        action_id=1,
        command="rg -n 'Bottle|caller' .",
        output=(
            "bottle.py:10:class Bottle\n"
            "tests/test_bottle.py:20:caller references Bottle; existing registry pattern\n"
        ),
        returncode=0,
        transition=WorkspaceTransition(
            action_id=1,
            command="rg -n 'Bottle|caller' .",
            before_revision="r0",
            after_revision="r0",
        ),
        revision="r0",
    )
    runtime.observe_action(
        action_id=2,
        command="sed -i 's/def f(/def f(x:/' app.py",
        output="def f(x: -> syntax error",
        returncode=0,
        transition=WorkspaceTransition(
            action_id=2,
            command="sed -i 's/def f(/def f(x:/' app.py",
            before_revision="r0",
            after_revision="r1",
            created=("new_module.py",),
            modified=("app.py",),
        ),
        revision="r1",
    )
    runtime.observe_action(
        action_id=3,
        command="pytest -q",
        output="1 failed: Error",
        returncode=1,
        transition=WorkspaceTransition(
            action_id=3,
            command="pytest -q",
            before_revision="r1",
            after_revision="r1",
        ),
        revision="r1",
    )
    runtime.observe_action(
        action_id=4,
        command="pytest -q",
        output="1 failed: Error",
        returncode=1,
        transition=WorkspaceTransition(
            action_id=4,
            command="pytest -q",
            before_revision="r1",
            after_revision="r1",
        ),
        revision="r1",
    )
    runtime.record_syntax(action_id=2, revision="r1", failed=True, reason="fixture_syntax_failure")
    runtime.record_submit(action_id=5, revision="r1", refused=True, sensor_healthy=True)

    summary = runtime.summary()
    assert summary["feature_count"] == 17
    assert set(summary["feature_ids"]) == set(CENTRAL_FEATURE_IDS)
    assert all(summary["delivered_counts"][feature] >= 1 for feature in CENTRAL_FEATURE_IDS)
    assert all(item["fresh"] for item in summary["receipts"])
    visible = {item["feature_id"] for item in summary["receipts"] if item["model_visible"]}
    assert visible == {
        "covering_red",
        "recovery",
        "signature_delta",
        "submit_refusal",
        "syntax_result",
    }
    assert all(item["payload"].get("message") for item in summary["receipts"])
    by_feature = {item["feature_id"]: item for item in summary["receipts"]}
    assert by_feature["obligations"]["boundary"] == "task_start"
    assert by_feature["def_partition"]["payload"]["definitions"] is True
    assert by_feature["caller_contract"]["boundary"] == "search_result"
    assert by_feature["caller_contract"]["payload"]["callers_verified"] is True
    assert by_feature["signature_delta"]["payload"]["signature_edit"] is True
    assert by_feature["recovery"]["payload"]["repeat_count"] == 2
    assert by_feature["submit_refusal"]["payload"]["refused"] is True


def test_model_guidance_is_one_prioritized_advisory_per_action():
    runtime = CentralFeatureRuntime(model_visible=True)
    runtime.begin_task("Implement the requested change", revision="r0")
    assert runtime.model_feedback() == ""
    runtime.observe_action(
        action_id=1,
        command="pytest -q",
        output="1 failed: assertion error",
        returncode=1,
        transition=WorkspaceTransition(1, "pytest -q", "r0", "r0"),
        revision="r0",
    )
    feedback = runtime.model_feedback()
    assert "validation command failed" in feedback
    assert runtime.model_feedback() == ""
    summary = runtime.summary()
    assert summary["guidance_events"] == 1
    assert summary["guidance_chars"] == len(feedback)


def test_covering_red_rejects_heredoc_text_and_missing_executables():
    runtime = CentralFeatureRuntime(model_visible=True)
    runtime.begin_task("Implement the requested change", revision="r0")

    command = "python3 - <<'EOF'\n# Test 1: exploratory probe\nprint('check')\nEOF"
    runtime.observe_action(
        action_id=1,
        command=command,
        output="bash: line 1: python3: command not found",
        returncode=127,
        transition=WorkspaceTransition(1, command, "r0", "r0"),
        revision="r0",
    )

    summary = runtime.summary()
    assert summary["delivered_counts"]["covering_red"] == 0
    assert summary["delivered_counts"]["GT_HYPOTHESIS"] == 0
    assert runtime.model_feedback() == ""


def test_covering_red_records_recognized_validation_provenance():
    runtime = CentralFeatureRuntime(model_visible=True)
    runtime.begin_task("Implement the requested change", revision="r0")
    runtime.observe_action(
        action_id=1,
        command="pytest -q",
        output="1 failed: assertion error",
        returncode=1,
        transition=WorkspaceTransition(1, "pytest -q", "r0", "r0"),
        revision="r0",
    )

    receipt = next(
        row for row in runtime.summary()["receipts"] if row["feature_id"] == "covering_red"
    )
    assert receipt["payload"]["command_class"] == "recognized_validation"
    assert receipt["payload"]["failure_kind"] == "validation_failure"
    assert "attributable regression" not in runtime.model_feedback()


def test_recovery_requires_the_same_validation_command_and_failure():
    runtime = CentralFeatureRuntime(model_visible=True)
    runtime.begin_task("Implement the requested change", revision="r0")
    for action_id, command in enumerate(("pytest -q", "python -m pytest"), start=1):
        runtime.observe_action(
            action_id=action_id,
            command=command,
            output="1 failed: assertion error",
            returncode=1,
            transition=WorkspaceTransition(action_id, command, "r0", "r0"),
            revision="r0",
        )

    summary = runtime.summary()
    assert summary["delivered_counts"]["covering_red"] == 2
    assert summary["delivered_counts"]["recovery"] == 0


def test_model_guidance_excludes_passes_non_actionable_receipts_and_repeats():
    runtime = CentralFeatureRuntime(model_visible=True)
    runtime.begin_task("Implement the requested change", revision="r0")

    # Obligations are already present in the task prompt and must stay receipt-only.
    assert runtime.model_feedback() == ""

    # A passing syntax check must never tell the model to repair syntax.
    runtime.record_syntax(
        action_id=1,
        revision="r1",
        failed=False,
        reason="changed_file_syntax_pass",
    )
    assert runtime.model_feedback() == ""

    runtime.record_syntax(
        action_id=2,
        revision="r2",
        failed=True,
        reason="changed_file_syntax_failure",
    )
    assert "Repair the syntax" in runtime.model_feedback()

    # Repeating the same advisory at the same workspace revision adds context
    # without adding evidence, so it must be coalesced.
    runtime.record_syntax(
        action_id=3,
        revision="r2",
        failed=True,
        reason="changed_file_syntax_failure",
    )
    assert runtime.model_feedback() == ""

    summary = runtime.summary()
    assert summary["guidance_events"] == 1
    assert summary["guidance_candidates"] == 2
    assert summary["guidance_suppressed"] >= 3
    assert summary["guidance_by_feature"] == {"syntax_result": 1}


def test_change_and_failure_capabilities_fire_only_at_their_real_boundaries():
    runtime = CentralFeatureRuntime(model_visible=True)
    runtime.begin_task("Fix it", revision="r0")
    unchanged = WorkspaceTransition(1, "echo error", "r0", "r0")
    runtime.observe_action(
        action_id=1,
        command="echo error",
        output="error is ordinary text",
        returncode=1,
        transition=unchanged,
        revision="r0",
    )
    assert runtime.summary()["delivered_counts"]["covering_red"] == 0
    assert runtime.summary()["delivered_counts"]["GT_HYPOTHESIS"] == 0

    changed = WorkspaceTransition(2, "write", "r0", "r1", modified=("app.py",))
    runtime.observe_action(
        action_id=2,
        command="write",
        output="",
        returncode=0,
        transition=changed,
        revision="r1",
    )
    summary = runtime.summary()
    assert summary["delivered_counts"]["GT_CHANGE_SURFACE"] == 1
    assert summary["delivered_counts"]["GT_PATCH_DELTA"] == 1
    assert not next(row for row in summary["receipts"] if row["feature_id"] == "GT_CHANGE_SURFACE")[
        "model_visible"
    ]

    runtime.observe_action(
        action_id=3,
        command="pytest -q",
        output="1 failed: assertion error",
        returncode=1,
        transition=WorkspaceTransition(3, "pytest -q", "r1", "r1"),
        revision="r1",
    )
    summary = runtime.summary()
    assert summary["delivered_counts"]["covering_red"] == 1
    assert summary["delivered_counts"]["GT_HYPOTHESIS"] == 1


def test_signature_delta_requires_explicit_before_after_evidence():
    runtime = CentralFeatureRuntime(model_visible=True)
    runtime.observe_action(
        action_id=1,
        command="tee app.py <<'EOF'\ndef f(x): pass\nEOF",
        output="",
        returncode=0,
        transition=WorkspaceTransition(1, "write", "r0", "r1", created=("app.py",)),
        revision="r1",
    )
    assert runtime.summary()["delivered_counts"]["signature_delta"] == 0

    runtime.observe_action(
        action_id=2,
        command="sed -i 's/def f(/def f(x, /' app.py",
        output="",
        returncode=0,
        transition=WorkspaceTransition(2, "edit", "r1", "r2", modified=("app.py",)),
        revision="r2",
    )
    receipt = next(
        row for row in runtime.summary()["receipts"] if row["feature_id"] == "signature_delta"
    )
    assert receipt["payload"]["before_signature"] != receipt["payload"]["after_signature"]


def test_all_seventeen_census_proves_payload_visibility_and_timing():
    result = census()

    assert result["all_17_deliverable"] is True
    assert result["all_17_timing_valid"] is True
    assert result["all_guidance_on_time"] is True
    assert set(result["timing_audit"]) == {*CENTRAL_FEATURE_IDS, "_global"}
    assert all(row["valid"] for row in result["timing_audit"].values())
    assert all(
        row["not_predictive"] and row["not_late"] and row["delivered_before_next_decision"]
        for row in result["decision_window_audit"]
    )


@pytest.mark.asyncio
async def test_sensor_carries_hash_without_reinventing_an_edit():
    class Result:
        def __init__(self, stdout="", return_code=0):
            self.stdout = stdout
            self.return_code = return_code

    class Environment:
        async def exec(self, command, **kwargs):
            if command.startswith("sha256sum"):
                return Result(("b" * 64) + "  app.js\n")
            return Result("f\t3\t2.0\t2.0\tapp.js\t\n")

    sensor = WorkspaceSensor()
    empty = parse_manifest("")
    created = await sensor.scan(Environment(), cwd="/app", previous=empty)
    unchanged = await sensor.scan(Environment(), cwd="/app", previous=created)

    transition = diff_snapshots(created, unchanged, action_id=2, command="pwd")
    assert created.revision == unchanged.revision
    assert transition.changed_paths == ()


@pytest.mark.asyncio
async def test_sensor_exception_fails_open_and_preserves_last_known_revision():
    class Environment:
        async def exec(self, command, **kwargs):
            raise TimeoutError("scan exceeded budget")

    previous = parse_manifest("f\t3\t2.0\t2.0\tapp.js\t\n")
    snapshot = await WorkspaceSensor().scan(Environment(), cwd="/app", previous=previous)

    assert snapshot.healthy is False
    assert snapshot.revision == previous.revision
    assert snapshot.entries == previous.entries


@pytest.mark.asyncio
async def test_malformed_manifest_fails_open_without_inventing_deletions():
    class Result:
        stdout = "not-a-valid-manifest\n"
        return_code = 0

    class Environment:
        async def exec(self, command, **kwargs):
            return Result()

    previous = parse_manifest("f\t3\t2.0\t2.0\tapp.js\t\n")
    snapshot = await WorkspaceSensor().scan(Environment(), cwd="/app", previous=previous)

    transition = diff_snapshots(previous, snapshot, action_id=2, command="pwd")
    assert snapshot.healthy is False
    assert transition.changed_paths == ()
