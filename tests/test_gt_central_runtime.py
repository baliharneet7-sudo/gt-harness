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
    assert all(item["model_visible"] for item in summary["receipts"])
    assert all(item["payload"].get("message") for item in summary["receipts"])
    by_feature = {item["feature_id"]: item for item in summary["receipts"]}
    assert by_feature["obligations"]["boundary"] == "task_start"
    assert by_feature["def_partition"]["payload"]["definitions"] is True
    assert by_feature["caller_contract"]["boundary"] == "search_result"
    assert by_feature["caller_contract"]["payload"]["callers_verified"] is True
    assert by_feature["signature_delta"]["payload"]["signature_edit"] is True
    assert by_feature["recovery"]["payload"]["repeat_count"] == 2
    assert by_feature["submit_refusal"]["payload"]["refused"] is True


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
