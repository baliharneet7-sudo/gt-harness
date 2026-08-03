from __future__ import annotations

import pytest

from gt_engine.central_runtime import (
    EvidenceLedger,
    FileState,
    InterventionDecision,
    WorkspaceSensor,
    WorkspaceSnapshot,
    diff_snapshots,
    parse_manifest,
    render_runtime_feedback,
)


def _snapshot(revision: str, **entries: FileState) -> WorkspaceSnapshot:
    return WorkspaceSnapshot(revision=revision, entries=entries, healthy=True)


def test_manifest_and_diff_are_non_git_and_cross_language():
    before = parse_manifest(
        "f\t10\t1.0\t1.0\tsrc/a.js\t\n"
        "f\t20\t1.0\t1.0\tmain.c\t\n"
    )
    after = parse_manifest(
        "f\t11\t2.0\t2.0\tsrc/a.js\t\n"
        "f\t7\t2.0\t2.0\tjob.cob\t\n"
    )

    transition = diff_snapshots(before, after, action_id=3, command="apply edits")

    assert transition.modified == ("src/a.js",)
    assert transition.created == ("job.cob",)
    assert transition.deleted == ("main.c",)
    assert transition.changed_paths == ("job.cob", "main.c", "src/a.js")


def test_ctime_detects_same_size_rewrite_even_when_mtime_is_preserved():
    before = _snapshot(
        "r1", **{"same.py": FileState("f", 4, "1.0", "1.0", "")}
    )
    after = _snapshot(
        "r2", **{"same.py": FileState("f", 4, "1.0", "2.0", "")}
    )

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
    snapshot = await WorkspaceSensor().scan(
        Environment(), cwd="/app", previous=previous
    )

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
    snapshot = await WorkspaceSensor().scan(
        Environment(), cwd="/app", previous=previous
    )

    transition = diff_snapshots(previous, snapshot, action_id=2, command="pwd")
    assert snapshot.healthy is False
    assert transition.changed_paths == ()
