from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from gt_engine.central_runtime import (
    CENTRAL_FEATURE_IDS,
    CentralFeatureRuntime,
    ChangeOrigin,
    EvidenceLedger,
    FileState,
    InterventionDecision,
    WorkspaceSensor,
    WorkspaceSnapshot,
    WorkspaceTransition,
    classify_change,
    classify_validation_command,
    diff_snapshots,
    explicit_check_commands,
    feature_payload_grounded,
    parse_manifest,
    render_runtime_feedback,
    select_declared_check,
    source_revision_of,
    task_deliverable_paths,
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
    assert all(summary["produced_counts"][feature] >= 1 for feature in CENTRAL_FEATURE_IDS)
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
    assert summary["produced_counts"]["covering_red"] == 0
    assert summary["produced_counts"]["GT_HYPOTHESIS"] == 0
    assert runtime.model_feedback() == ""


def test_validation_classifier_handles_timeout_without_matching_probes():
    assert classify_validation_command("timeout 600 pytest -q").is_validation
    classification = classify_validation_command("timeout --signal=TERM 25 python3 -c 'print(1)'")
    assert classification.is_validation is False


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
    assert summary["produced_counts"]["covering_red"] == 2
    assert summary["produced_counts"]["recovery"] == 0


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


def test_validation_debt_is_grounded_once_and_resets_after_a_real_check():
    runtime = CentralFeatureRuntime(model_visible=True)
    runtime.begin_task(
        "Update it, then run `pytest -q`.",
        revision="r0",
        explicit_checks=("pytest -q",),
    )
    for action_id, revision in ((1, "r1"), (2, "r2"), (3, "r3")):
        runtime.observe_action(
            action_id=action_id,
            command=f"write source {action_id}",
            output="",
            returncode=0,
            transition=WorkspaceTransition(
                action_id, "write", "r0", revision, modified=("app.py",)
            ),
            revision=revision,
        )
    feedback = runtime.model_feedback()
    assert "Three source revisions" in feedback
    assert "pytest -q" in feedback
    receipt = next(
        row for row in runtime.summary()["receipts"] if row["feature_id"] == "GT_EDIT_CHECK"
    )
    assert receipt["payload"]["intervention"] == "validation_debt"
    assert receipt["model_visible"] is True

    runtime.observe_action(
        action_id=4,
        command="pytest -q",
        output="1 passed",
        returncode=0,
        transition=WorkspaceTransition(4, "pytest -q", "r3", "r3"),
        revision="r3",
    )
    assert runtime._unvalidated_material_edits == 0
    assert runtime._validation_debt_notified is False


def test_cache_artifacts_do_not_count_as_material_engine_edits():
    runtime = CentralFeatureRuntime(model_visible=True)
    runtime.begin_task("Run `pytest -q`.", revision="r0", explicit_checks=("pytest -q",))
    for action_id in (1, 2):
        runtime.observe_action(
            action_id=action_id,
            command="python3 -c 'pass'",
            output="",
            returncode=0,
            transition=WorkspaceTransition(
                action_id,
                "python3 -c",
                "r0",
                f"r{action_id}",
                created=("__pycache__/app.cpython-313.pyc",),
            ),
            revision=f"r{action_id}",
        )
    assert runtime.model_feedback() == ""
    assert runtime.summary()["action_metrics"]["workspace_change_actions"] == 0


def test_explicit_verifier_path_is_a_grounded_check_without_an_interpreter():
    checks = explicit_check_commands("You can run /app/test_outputs.py to verify.")

    assert checks == ("/app/test_outputs.py",)
    assert classify_validation_command("python3 /app/test_outputs.py", checks).grounded


def test_explicit_check_parser_keeps_contract_named_build_and_pipe_commands():
    instruction = (
        "To build, run `python3 setup.py build_ext --inplace`, then test using "
        "`python3 benchmark.py`.\n"
        "echo '(+ 7 8)' | python3 interp.py test/calculator.scm"
    )

    checks = explicit_check_commands(instruction)

    assert checks[:2] == ("python3 setup.py build_ext --inplace", "python3 benchmark.py")
    assert checks[2] == "echo '(+ 7 8)' | python3 interp.py test/calculator.scm"


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
    assert runtime.summary()["produced_counts"]["covering_red"] == 0
    assert runtime.summary()["produced_counts"]["GT_HYPOTHESIS"] == 0

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
    assert summary["produced_counts"]["GT_CHANGE_SURFACE"] == 1
    assert summary["produced_counts"]["GT_PATCH_DELTA"] == 1
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
    assert summary["produced_counts"]["covering_red"] == 1
    assert summary["produced_counts"]["GT_HYPOTHESIS"] == 1


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
    assert runtime.summary()["produced_counts"]["signature_delta"] == 0

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


def test_all_seventeen_census_proves_producers_and_fails_consumer_proof():
    result = census()

    # Producer-side proof must hold: all 17 IDs produced a valid, on-boundary,
    # fresh receipt and every guidance window was on time.
    assert result["all_17_producers_proven"] is True
    assert result["all_17_timing_valid"] is True
    assert result["all_guidance_on_time"] is True
    assert set(result["timing_audit"]) == {*CENTRAL_FEATURE_IDS, "_global"}
    assert all(row["valid"] for row in result["timing_audit"].values())
    assert all(
        row["not_predictive"] and row["not_late"] and row["delivered_before_next_decision"]
        for row in result["decision_window_audit"]
    )
    # Every produced receipt routes to a registered consumer with valid
    # timing, and every model-visible payload names concrete evidence.
    assert result["all_17_consumers_proven"] is True
    assert result["all_effects_timing_valid"] is True
    assert result["all_payloads_semantically_grounded"] is True
    assert result["all_17_consumer_paths_proven"] is True
    assert result["effect_window_audit"]
    assert all(
        row["evidence_before_effect"] and row["effect_before_next_action"] and row["non_late"]
        for row in result["effect_window_audit"]
    )


def test_signature_delta_is_eligible_but_discarded_by_one_message_selection():
    result = census()

    # signature_delta is produced at the edit boundary and is model-actionable,
    # so it is eligible for the single delivery slot...
    produced = [
        row for row in result["receipts"] if row["feature_id"] == "signature_delta"
    ]
    assert produced
    assert all(row["model_visible"] for row in produced)
    # ...but the one-message arbitration picks syntax_result first, so the
    # eligible signature_delta fact never reaches a model request.
    delivered = {row["feature_id"] for row in result["decision_window_audit"]}
    assert "signature_delta" not in delivered
    assert "syntax_result" in delivered


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


def test_task_deliverable_paths_extracts_contract_outputs():
    instruction = (
        "Run `pytest -q` to validate. Write your final report to `report.jsonl` "
        "as a JSON list of findings."
    )

    assert "report.jsonl" in task_deliverable_paths(instruction)
    assert task_deliverable_paths("just fix the bug") == ()


def test_classify_change_never_advances_source_for_artifacts():
    for path, kind in (
        ("benchmark_out.txt", "f"),
        ("callback-test.txt", "f"),
        ("a.out", "f"),
        ("data.comp", "f"),
        ("build/x.o", "f"),
        ("app.so", "f"),
        ("logs/run.log", "f"),
        ("__pycache__/x.pyc", "f"),
        ("build", "d"),
    ):
        change = classify_change(path, kind=kind)
        assert change.validation_relevant is False, path
        assert change.origin != ChangeOrigin.MODEL_AUTHORED, path

    assert classify_change("app.py", kind="f").validation_relevant is True
    assert classify_change("eval.scm", kind="f").validation_relevant is True


def test_report_jsonl_is_a_deliverable_not_source():
    change = classify_change("report.jsonl", kind="f", task_deliverables={"report.jsonl"})

    assert change.origin == ChangeOrigin.TASK_DELIVERABLE
    assert change.validation_relevant is False


def test_source_revision_ignores_artifact_changes_but_not_source_edits():
    base = parse_manifest("f\t10\t1.0\t1.0\tapp.py\t\nf\t5\t1.0\t1.0\tbenchmark_out.txt\t\n")
    artifact_only = parse_manifest(
        "f\t10\t1.0\t1.0\tapp.py\t\nf\t99\t2.0\t2.0\tbenchmark_out.txt\t\n"
    )
    source_edit = parse_manifest("f\t11\t2.0\t2.0\tapp.py\t\nf\t5\t1.0\t1.0\tbenchmark_out.txt\t\n")

    assert source_revision_of(artifact_only) == source_revision_of(base)
    assert source_revision_of(source_edit) != source_revision_of(base)


def test_validation_debt_does_not_fire_on_artifact_only_changes():
    runtime = CentralFeatureRuntime(model_visible=True)
    runtime.begin_task(
        "Update it, then run `pytest -q`.",
        revision="r0",
        explicit_checks=("pytest -q",),
        task_deliverables={"report.jsonl"},
    )
    for action_id, path in ((1, "benchmark_out.txt"), (2, "report.jsonl"), (3, "build/x.o")):
        runtime.observe_action(
            action_id=action_id,
            command=f"write {path}",
            output="",
            returncode=0,
            transition=WorkspaceTransition(
                action_id, "write", "r0", f"r{action_id}", modified=(path,)
            ),
            revision=f"r{action_id}",
        )

    assert runtime.model_feedback() == ""
    assert runtime.summary()["source_epoch"] == 0
    assert runtime.summary()["action_metrics"]["workspace_change_actions"] == 0


def test_validation_debt_selects_highest_priority_declared_check():
    runtime = CentralFeatureRuntime(model_visible=True)
    runtime.begin_task(
        "Build then verify: run `python3 setup.py build_ext --inplace` and "
        "`python3 /app/verify_solution.py`.",
        revision="r0",
        explicit_checks=(
            "python3 setup.py build_ext --inplace",
            "python3 /app/verify_solution.py",
        ),
    )
    for action_id in (1, 2, 3):
        runtime.observe_action(
            action_id=action_id,
            command=f"write app.py {action_id}",
            output="",
            returncode=0,
            transition=WorkspaceTransition(
                action_id, "write", "r0", f"r{action_id}", modified=("app.py",)
            ),
            revision=f"r{action_id}",
        )

    feedback = runtime.model_feedback()
    assert "/app/verify_solution.py" in feedback


def test_select_declared_check_skips_freshly_passing_checks():
    checks = ("build", "verify")
    assert select_declared_check(checks, {"verify": "passed"}) == "build"
    assert select_declared_check(checks, {"build": "passed", "verify": "passed"}) is None
    assert select_declared_check(checks, {"verify": "stale"}) == "verify"


def test_ledger_records_declared_validation_bound_to_source_revision():
    ledger = EvidenceLedger(max_holds=1)
    source_r = "source-v1"
    classification = classify_validation_command("pytest -q", ("pytest -q",)).with_result(
        result_code=1,
        output="1 failed: assert error",
        source_revision=source_r,
        workspace_revision="workspace-v9",
    )
    ledger.record_check(
        "pytest -q",
        returncode=1,
        revision=source_r,
        grounded=True,
        classification=classification,
    )

    readiness = ledger.readiness_evidence(source_r)
    assert len(readiness) == 1
    assert readiness[0].command_class == "declared_validation"
    assert readiness[0].failure_kind == "validation_failure"
    assert ledger.submit_decision(source_r).decision == InterventionDecision.HOLD_ONCE


def test_fresh_passing_declared_check_yields_positive_certificate_counts():
    ledger = EvidenceLedger(max_holds=1)
    source_r = "source-v1"
    classification = classify_validation_command("pytest -q", ("pytest -q",))
    ledger.record_check(
        "pytest -q",
        returncode=0,
        revision=source_r,
        grounded=True,
        classification=classification,
    )

    evidence = ledger.readiness_evidence(source_r)
    assert len(evidence) == 1
    assert evidence[0].returncode == 0
    assert ledger.submit_decision(source_r).decision == InterventionDecision.PASS


def test_runtime_validation_log_records_declared_checks():
    runtime = CentralFeatureRuntime(model_visible=True)
    runtime.begin_task(
        "Run `pytest -q`.",
        revision="r0",
        explicit_checks=("pytest -q",),
    )
    classification = classify_validation_command("pytest -q", ("pytest -q",)).with_result(
        result_code=0,
        output="1 passed",
        source_revision="r0",
        workspace_revision="r0",
    )
    runtime.observe_action(
        action_id=1,
        command="pytest -q",
        output="1 passed",
        returncode=0,
        transition=WorkspaceTransition(1, "pytest -q", "r0", "r0"),
        revision="r0",
        source_revision="r0",
        validation=classification,
    )

    log = runtime.summary()["validation_log"]
    assert len(log) == 1
    assert log[0]["command_class"] == "declared_validation"
    assert log[0]["declared_check_id"] == "pytest -q"
    assert log[0]["result_code"] == 0


def test_effect_timing_consumes_evidence_before_the_next_action():
    runtime = CentralFeatureRuntime(model_visible=True)
    runtime.begin_task("Fix it", revision="r0")
    runtime.observe_action(
        action_id=1,
        command="pytest -q",
        output="1 failed: assert error",
        returncode=1,
        transition=WorkspaceTransition(1, "pytest -q", "r0", "r0"),
        revision="r0",
    )

    effects = runtime.consume_effects(action_id=1, call=1)

    assert effects
    for effect in effects:
        row = effect.as_dict()
        assert row["evidence_before_effect"] is True
        assert row["effect_before_next_action"] is True
        assert row["non_late"] is True
        # The effect is applied only after the action has produced its
        # evidence.  Same-action delivery is immediate, not predictive.
        assert row["predictive"] is False
        assert row["predecided_actions_executed_after_evidence"] == 0
    # Full 17-ID consumer coverage is proven by the census, not one action.
    assert runtime.summary()["consumer_paths"]


def test_documented_direct_census_entrypoint_is_executable():
    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, "scripts/central_feature_census.py"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "ALL_17_CONSUMER_PATHS_PROVEN" in completed.stdout


def test_batch_interrupt_stamps_cancellation_on_the_effect():
    runtime = CentralFeatureRuntime(model_visible=True)
    runtime.begin_task("Fix it", revision="r0")
    runtime.observe_action(
        action_id=1,
        command="pytest -q",
        output="1 failed: assert error",
        returncode=1,
        transition=WorkspaceTransition(1, "pytest -q", "r0", "r0"),
        revision="r0",
    )
    effects = runtime.consume_effects(action_id=1, call=1)
    assert any(effect.required_before_action == 1 for effect in effects)

    runtime.record_batch_interrupt(action_id=1, cancelled=2, reason="covering_red")

    stamped = next(
        effect
        for effect in runtime.summary()["effects"]
        if effect["feature_id"] == "covering_red"
    )
    assert stamped["predecided_actions_cancelled"] == 2
    assert runtime.summary()["action_metrics"]["batch_interrupts"] == 1


def test_grounded_payloads_require_concrete_evidence():
    runtime = CentralFeatureRuntime(model_visible=True)
    runtime.begin_task("Run `pytest -q`.", revision="r0", explicit_checks=("pytest -q",))
    classification = classify_validation_command("pytest -q", ("pytest -q",)).with_result(
        result_code=1,
        output="1 failed: assert error at tests/test_app.py:42",
        source_revision="r0",
        workspace_revision="r0",
    )
    runtime.observe_action(
        action_id=1,
        command="pytest -q",
        output="1 failed: assert error at tests/test_app.py:42",
        returncode=1,
        transition=WorkspaceTransition(1, "pytest -q", "r0", "r0"),
        revision="r0",
        source_revision="r0",
        validation=classification,
    )

    covering = next(
        row
        for row in runtime.summary()["receipts"]
        if row["feature_id"] == "covering_red"
    )
    assert covering["model_visible"] is True
    assert feature_payload_grounded("covering_red", covering["payload"]) is True
    assert covering["payload"]["command"] == "pytest -q"
    assert "assert error" in covering["payload"]["diagnostic"]
    assert covering["payload"]["attribution"] == "pytest -q"


def test_localization_payload_names_concrete_anchors():
    runtime = CentralFeatureRuntime(model_visible=True)
    runtime.begin_task("Find Bottle", revision="r0")
    runtime.observe_action(
        action_id=1,
        command="rg -n 'class Bottle' .",
        output="bottle.py:10:class Bottle\n",
        returncode=0,
        transition=WorkspaceTransition(1, "rg -n 'class Bottle' .", "r0", "r0"),
        revision="r0",
    )

    receipt = next(
        row for row in runtime.summary()["receipts"] if row["feature_id"] == "localization"
    )
    assert receipt["payload"]["anchors"][0]["path"] == "bottle.py"
    assert receipt["payload"]["anchors"][0]["line"] == 10


def test_signature_delta_payload_names_the_symbol():
    runtime = CentralFeatureRuntime(model_visible=True)
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
    assert receipt["payload"]["symbol"] == "f"
    assert receipt["payload"]["before_signature"] != receipt["payload"]["after_signature"]
