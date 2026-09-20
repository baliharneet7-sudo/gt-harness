import base64
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from scripts.miniswe_gt_run import CredentialIsolatedLocalEnvironment


def test_environment_recovers_fact_beyond_preview(tmp_path):
    script = tmp_path / "emit.py"
    payload = b"x" * 60_000 + b"\nNEEDED_FACT=731\n" + b"y" * 60_000
    script.write_text(f"import sys; sys.stdout.buffer.write({payload!r})")
    env = CredentialIsolatedLocalEnvironment(cwd=str(tmp_path), timeout=5)
    result = env.execute({"command": f'"{sys.executable}" "{script}"'})
    # The model gets a bounded head/tail view, not a retrieval pointer; the
    # paged reader stays available for analyzers and recovery.
    assert "output truncated" in result["output"]
    assert "gt-evidence" not in result["output"]
    assert "NEEDED_FACT" not in result["output"]
    ref = result["extra"]["output_artifact"]
    assert ref["sha256"] == hashlib.sha256(payload).hexdigest()
    assert "raw_output" not in result["extra"]
    from gt_engine.output_evidence import EvidenceStore
    store = EvidenceStore(ref["root"])
    page = store.read(ref["sha256"], 60_000, 200)
    assert "NEEDED_FACT=731" in page["text"]
    rebuilt = bytearray()
    offset = 0
    while True:
        page = store.read(ref["sha256"], offset, 8192)
        rebuilt.extend(page["text"].encode() if page["encoding"] == "utf-8"
                       else base64.b64decode(page["base64"]))
        if page["continuation_offset"] is None:
            break
        offset = page["continuation_offset"]
    assert bytes(rebuilt) == payload


def test_binary_pages_cli_and_corruption(tmp_path):
    from gt_engine.output_evidence import EvidenceStore
    store = EvidenceStore(tmp_path / "evidence")
    source = tmp_path / "raw"
    source.write_bytes(b"\xff\xfe" + b"a" * 9000)
    ref = store.publish(source)
    page = store.read(ref["sha256"], 0, 8192)
    assert page["encoding"] == "base64"
    assert len(base64.b64decode(page["base64"])) == 8192
    with pytest.raises(ValueError):
        store.read(ref["sha256"], 0, 8193)
    proc = subprocess.run([sys.executable, "-m", "gt_engine.output_evidence", "read",
                           ref["sha256"], "0", "8192"],
                          env=os.environ | {"GT_EVIDENCE_ROOT": str(store.root)},
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == page
    store.path(ref["sha256"]).write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="digest"):
        store.read(ref["sha256"], 0, 1)


def test_paged_reads_verify_the_blob_once_then_seek(tmp_path, monkeypatch):
    from pathlib import Path

    from gt_engine.output_evidence import PAGE_BYTES, EvidenceStore

    store = EvidenceStore(tmp_path / "evidence")
    source = tmp_path / "spool"
    payload = b"A" * (PAGE_BYTES * 10) + b"TAIL"
    source.write_bytes(payload)
    reference = store.publish(source)
    digest = reference["sha256"]
    total = reference["total_length"]
    assert total == len(payload) > 2 * PAGE_BYTES

    consumed = [0]
    real_open = Path.open

    def counting_open(path, *args, **kwargs):
        stream = real_open(path, *args, **kwargs)
        try:
            path.relative_to(store.root)
        except ValueError:
            return stream

        class Counted:
            def __enter__(self):
                stream.__enter__()
                return self

            def __exit__(self, *exc):
                return stream.__exit__(*exc)

            def read(self, size=-1):
                chunk = stream.read(size)
                consumed[0] += len(chunk)
                return chunk

            def __getattr__(self, name):
                return getattr(stream, name)

        return Counted()

    monkeypatch.setattr(Path, "open", counting_open)

    tail = store.read(digest, total - PAGE_BYTES, PAGE_BYTES)
    assert tail["text"].endswith("TAIL")
    # The publish-time scan already proved this exact blob in this process;
    # a paged read on it must seek and slice, not rescan the whole artifact.
    assert consumed[0] <= 2 * PAGE_BYTES

    consumed[0] = 0
    head = store.read(digest, 0, PAGE_BYTES)
    assert head["offset"] == 0
    assert consumed[0] <= 2 * PAGE_BYTES


def test_paged_read_reverifies_after_same_size_blob_mutation(tmp_path):
    from gt_engine.output_evidence import PAGE_BYTES, EvidenceStore

    store = EvidenceStore(tmp_path / "evidence")
    source = tmp_path / "spool"
    source.write_bytes(b"A" * (PAGE_BYTES * 4) + b"ORIG")
    reference = store.publish(source)
    digest = reference["sha256"]
    assert store.read(digest, 0, PAGE_BYTES)["returned_length"] == PAGE_BYTES

    artifact = store.path(digest)
    tampered = bytearray(artifact.read_bytes())
    tampered[-4:] = b"HACK"
    artifact.write_bytes(bytes(tampered))
    # Same length: bump the mtime leg of the verification key explicitly so
    # the mutation is observable regardless of filesystem timestamp granularity.
    stat = artifact.stat()
    os.utime(artifact, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    with pytest.raises(ValueError, match="digest"):
        store.read(digest, 0, PAGE_BYTES)


def test_timeout_preserves_actual_bytes(tmp_path):
    script = tmp_path / "wait.py"
    script.write_text("import sys,time; sys.stdout.buffer.write(b'partial\\xff'); sys.stdout.flush(); time.sleep(30)")
    env = CredentialIsolatedLocalEnvironment(cwd=str(tmp_path), timeout=1)
    result = env.execute({"command": f'"{sys.executable}" "{script}"'})
    assert result["extra"]["timed_out"] is True
    from gt_engine.output_evidence import EvidenceStore
    ref = result["extra"]["output_artifact"]
    assert EvidenceStore(ref["root"]).bytes(ref["sha256"]) == b"partial\xff"
    assert result["returncode"] != 0


def test_task_scripts_package_cannot_shadow_installed_command_worker(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "__init__.py").write_text("raise RuntimeError('task code imported by harness')")
    env = CredentialIsolatedLocalEnvironment(cwd=str(tmp_path), timeout=5)
    result = env.execute({"command": "echo actual-command"})
    assert result["returncode"] == 0
    assert result["output"].strip() == "actual-command"


def test_relative_command_workspace_is_resolved_once(tmp_path, monkeypatch):
    (tmp_path / "task").mkdir()
    monkeypatch.chdir(tmp_path)
    env = CredentialIsolatedLocalEnvironment(cwd="task", timeout=5)
    result = env.execute({"command": "echo edited > actual-edit.txt"})
    assert result["returncode"] == 0
    assert (tmp_path / "task" / "actual-edit.txt").read_text().strip() == "edited"


@pytest.mark.skipif(os.name != "posix", reason="production Linux process ownership")
def test_detached_stdout_is_captured_before_immutable_publication(tmp_path):
    from gt_engine.output_evidence import EvidenceStore
    env = CredentialIsolatedLocalEnvironment(cwd=str(tmp_path), timeout=3)
    result = env.execute({"command": "setsid sh -c 'sleep 0.2; printf LATE' &"})
    assert result["returncode"] == 0
    assert result["output"] == "LATE"
    reference = result["extra"]["output_artifact"]
    assert EvidenceStore(reference["root"]).bytes(reference["sha256"]) == b"LATE"


@pytest.mark.skipif(os.name != "posix", reason="production Linux native background semantics")
def test_redirected_background_service_survives_successful_action(tmp_path):
    env = CredentialIsolatedLocalEnvironment(cwd=str(tmp_path), timeout=3)
    result = env.execute({"command": "sh -c 'sleep 0.2; echo ready > service-ready' >/dev/null 2>&1 & echo launched"})
    assert result["returncode"] == 0
    assert result["output"].strip() == "launched"
    deadline = time.monotonic() + 3
    while not (tmp_path / "service-ready").exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert (tmp_path / "service-ready").read_text().strip() == "ready"


@pytest.mark.skipif(shutil.which("gt-evidence") is None, reason="installed wheel CLI required")
def test_installed_bash_page_is_complete_and_drives_next_edit(tmp_path):
    script = tmp_path / "emit.py"
    script.write_text("import sys; sys.stdout.write('x'*25000+'NEEDED_FACT=731\\n'+'y'*25000)")
    env = CredentialIsolatedLocalEnvironment(cwd=str(tmp_path), timeout=5)
    observation = env.execute({"command": f'"{sys.executable}" "{script}"'})
    ref = observation["extra"]["output_artifact"]
    recovered = env.execute({"command": f"gt-evidence read {ref['sha256']} 25000 8192"})
    assert recovered["returncode"] == 0
    page = json.loads(recovered["output"])
    assert page["returned_length"] == 8192
    value = int(page["text"].splitlines()[0].split("=")[1])
    edit = tmp_path / "edit.py"
    edit.write_text(f"from pathlib import Path; Path('answer.txt').write_text('{value}')")
    result = env.execute({"command": f'"{sys.executable}" "{edit}"'})
    assert result["returncode"] == 0
    assert (tmp_path / "answer.txt").read_text() == "731"


def test_execution_evidence_uses_original_binary_output():
    from gt_engine.runtime_observation import compile_execution_evidence
    raw = b"FAIL\xff"
    result = compile_execution_evidence(
        command="pytest", output=raw.decode("utf-8", "replace"), raw_output=raw,
        returncode=-9, timed_out=True, action_id=1, repository_revision="source",
    )
    assert result.raw_output_sha256 == hashlib.sha256(raw).hexdigest()
    assert result.outcome == "timeout"


def test_execution_journal_references_the_capture_blob_without_copy(tmp_path):
    from gt_engine.miniswe_integration import MiniSweAdapter
    from gt_engine.output_evidence import EvidenceStore
    from gt_engine.runtime_observation import compile_execution_evidence
    adapter = MiniSweAdapter(task_id="task", state_dir=tmp_path, predicates=[])
    store = EvidenceStore(adapter.store.root / "output_evidence")
    spool = store.root / "pending"
    spool.write_bytes(b"FAIL\xff")
    ref = store.publish(spool)
    evidence = compile_execution_evidence(
        command="pytest", output="FAIL�", raw_output=b"FAIL\xff", returncode=1,
        action_id=1, repository_revision="source",
        output_artifact_path=str(store.path(ref["sha256"])),
    )
    adapter.record_execution_evidence(evidence)
    row = json.loads(adapter.store.path.read_text().splitlines()[-1])
    assert row["raw_blob"] == "output_evidence/" + ref["sha256"]
    assert not (adapter.store.root / "raw_execution_output").exists()


def test_transport_preview_does_not_replace_complete_gt_analysis(tmp_path):
    from gt_engine.miniswe_runtime import _observation_output
    from gt_engine.output_evidence import EvidenceStore
    from gt_engine.runtime_observation import compile_execution_evidence

    store = EvidenceStore(tmp_path / "evidence")
    source = tmp_path / "stdout"
    complete = "progress\n" * 10_000 + "25 passed in 1.00s\n"
    source.write_bytes(complete.encode())
    reference = store.publish(source)
    result = {"output": store.preview(reference), "returncode": 0,
              "extra": {"output_artifact": reference}}
    # The preview is bounded (middle elided; the tail keeps the summary), and
    # the canonical analyzer still consumes the complete artifact bytes.
    assert "output truncated" in result["output"]
    analyzed = _observation_output(result)
    assert analyzed == complete
    verification = compile_execution_evidence(
        command="pytest", output=analyzed, returncode=0, action_id=1,
        repository_revision="source", output_artifact=reference,
        output_artifact_path=str(store.path(reference["sha256"])),
    )
    assert verification.outcome == "pass"


def test_hidden_failure_keeps_canonical_precedence_over_earlier_pass(tmp_path):
    from gt_engine.miniswe_runtime import _observation_output
    from gt_engine.output_evidence import EvidenceStore
    from gt_engine.runtime_observation import compile_execution_evidence

    store = EvidenceStore(tmp_path / "evidence")
    source = tmp_path / "stdout"
    complete = "25 passed\n" + "progress\n" * 5000 + "1 failed\n"
    source.write_bytes(complete.encode())
    reference = store.publish(source)
    result = {"output": store.preview(reference), "returncode": 0,
              "extra": {"output_artifact": reference}}
    analyzed = _observation_output(result)
    assert "1 failed" in analyzed
    verification = compile_execution_evidence(
        command="pytest", output=analyzed, returncode=0, action_id=1,
        repository_revision="source", output_artifact=reference,
        output_artifact_path=str(store.path(reference["sha256"])),
    )
    assert verification.outcome == "fail"


def test_artifact_analysis_streams_complete_output_without_bytes_load(
    tmp_path, monkeypatch
):
    from gt_engine.output_evidence import EvidenceStore
    from gt_engine.runtime_observation import (
        classify_execution_outcome,
        compile_execution_evidence,
    )

    store = EvidenceStore(tmp_path / "evidence")
    source = tmp_path / "stdout"
    source.write_bytes(b"25 passed\n" + b"x" * 2_000_000 + b"\n1 failed\n")
    reference = store.publish(source)
    preview = store.preview(reference)
    monkeypatch.setattr(
        EvidenceStore,
        "bytes",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("complete artifact must not be loaded into memory")
        ),
    )

    evidence = compile_execution_evidence(
        command="pytest",
        output=preview,
        returncode=1,
        action_id=1,
        repository_revision="source",
        output_artifact=reference,
        output_artifact_path=str(store.path(reference["sha256"])),
    )

    assert evidence is not None
    assert evidence.outcome == "fail"
    assert evidence.raw_output is None
    assert evidence.raw_output_sha256 == reference["sha256"]
    assert classify_execution_outcome(
        "pytest", preview, 1, output_artifact=reference
    ) == "fail"


def test_artifact_stream_corrupt_tail_fails_before_evidence_is_returned(tmp_path):
    from gt_engine.output_evidence import EvidenceStore
    from gt_engine.runtime_observation import (
        classify_execution_outcome,
        compile_execution_evidence,
    )

    store = EvidenceStore(tmp_path / "evidence")
    source = tmp_path / "stdout"
    source.write_bytes(b"25 passed\n" + b"x" * 100_000)
    reference = store.publish(source)
    with store.path(reference["sha256"]).open("r+b") as corrupt:
        corrupt.seek(-1, os.SEEK_END)
        corrupt.write(b"y")

    with pytest.raises(ValueError, match="artifact digest mismatch"):
        compile_execution_evidence(
            command="pytest",
            output="25 passed\n[preview]",
            returncode=0,
            action_id=1,
            repository_revision="source",
            output_artifact=reference,
            output_artifact_path=str(store.path(reference["sha256"])),
        )
    with pytest.raises(ValueError, match="artifact digest mismatch"):
        classify_execution_outcome(
            "pytest", "25 passed\n[preview]", 124, output_artifact=reference
        )


def test_early_classifier_return_still_validates_artifact_tail(tmp_path, monkeypatch):
    import groundtruth.runtime.patterns as patterns

    from gt_engine.output_evidence import EvidenceStore
    from gt_engine.runtime_observation import compile_execution_evidence

    store = EvidenceStore(tmp_path / "evidence")
    source = tmp_path / "stdout"
    source.write_bytes(b"25 passed\n" + b"x" * 100_000)
    reference = store.publish(source)
    with store.path(reference["sha256"]).open("r+b") as corrupt:
        corrupt.seek(-1, os.SEEK_END)
        corrupt.write(b"y")

    def early_result(command, chunks, returncode, **kwargs):
        next(iter(chunks))
        return "pass", "command"

    monkeypatch.setattr(patterns, "classify_test_observation_stream", early_result)
    with pytest.raises(ValueError, match="artifact digest mismatch"):
        compile_execution_evidence(
            command="pytest",
            output="25 passed\n[preview]",
            returncode=0,
            action_id=1,
            repository_revision="source",
            output_artifact=reference,
        )


@pytest.mark.skipif(os.name != "posix", reason="production Linux signal boundary")
def test_real_interruption_preserves_capture_and_propagates(tmp_path):
    worker = tmp_path / "worker.py"
    evidence = tmp_path / "state"
    worker.write_text(
        "from scripts.miniswe_gt_run import CredentialIsolatedLocalEnvironment, _install_termination_guard\n"
        "_install_termination_guard()\n"
        f"env = CredentialIsolatedLocalEnvironment(cwd={str(tmp_path)!r}, evidence_root={str(evidence)!r})\n"
        "env.execute({'command': 'echo partial; echo repaired > repair.txt; sleep 60'})\n"
        "raise AssertionError('interruption was swallowed')\n"
    )
    with (tmp_path / "worker.log").open("wb") as log:
        child = subprocess.Popen([sys.executable, str(worker)], stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 30
            while not (tmp_path / "repair.txt").exists() and time.monotonic() < deadline:
                if child.poll() is not None:
                    pytest.fail((tmp_path / "worker.log").read_text())
                time.sleep(0.05)
            assert (tmp_path / "repair.txt").read_text().strip() == "repaired"
            child.send_signal(signal.SIGTERM)
            child.wait(timeout=10)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
    assert child.returncode != 0
    receipt, = evidence.glob("*.receipt.json")
    terminal = json.loads(receipt.read_text())
    assert terminal["status"] == "interrupted"
    assert terminal["returncode"] != 0
    from gt_engine.output_evidence import EvidenceStore
    assert EvidenceStore(evidence).bytes(terminal["output_artifact"]["sha256"]) == b"partial\n"
    assert "RunnerTerminationRequested" in (tmp_path / "worker.log").read_text()


# --- containment receipt gap -------------------------------------------------
# Run 35256147148 (amoffat__sh-744) died on the raise below with
# `committed_patch_bytes: 4660, committed_patch_empty: false,
# repository_head_moved: true` in its own report. The raise lives in a
# `finally:`, so it replaced the in-flight result AND skipped the publish: no
# capture receipt, no output artifact, RuntimeError -> internal_error -> exit 5
# -> Pier errors the trial -> `[[verifier.collect]]` never runs -> no
# /logs/artifacts/model.patch -> graded 0. 4,660 bytes of the model's work were
# thrown away to report that a containment RECEIPT was missing.
#
# Containment is a property of the harness, not of the submission. Where the
# workspace holds work the gap is recorded and the run continues; where it is
# pristine there is nothing to lose and broken tooling still fails fast.


def _git(repo, *arguments):
    return subprocess.run(
        ["git", *arguments], cwd=repo, check=True, capture_output=True, text=True,
    ).stdout.strip()


def _git_workspace(path):
    """A task workspace at a baseline commit, as Pier hands one over."""
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "t@example.invalid")
    _git(path, "config", "user.name", "t")
    (path / "README").write_text("base\n")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "baseline")
    return _git(path, "rev-parse", "HEAD")


def _commit_work(path, name="fix.py", body="value = 731\n"):
    (path / name).write_text(body)
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "work")


WORKER_RECEIPT = {
    "schema": "gt.command_worker.v1", "reason": "exited", "returncode": 0,
    "capture_complete": True, "descendants_reaped": False,
    "surviving_descendants": [],
}


class _StubWorkerChild:
    """The `python -I -m scripts.miniswe_supervisor --command-worker` child.

    The real one is Linux-only (subreaper + process groups), so every test here
    monkeypatches `sys.platform` and installs this in its place: the contained
    branch is exercised on Windows without ever spawning a worker.
    """

    def __init__(self, spool, output, returncode, receipt_path, receipt):
        spool.write(output)
        spool.flush()
        if receipt is not None:
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        self.returncode = returncode
        self.pid = -1

    def wait(self, timeout=None):
        return self.returncode

    def poll(self):
        return self.returncode

    def terminate(self):
        return None


def _install_stub_worker(monkeypatch, plan):
    """Answer only the worker launch; every other Popen is the real one.

    `subprocess.run` is built on `Popen`, and `submission_patch_state` shells
    out to git through it, so a blanket replacement would break the very
    observation these tests are about.
    """
    monkeypatch.setattr(sys, "platform", "linux")
    real_popen = subprocess.Popen
    calls = []

    def popen(args, **kwargs):
        if not (isinstance(args, list) and "--command-worker" in args):
            return real_popen(args, **kwargs)
        step = plan[min(len(calls), len(plan) - 1)]
        calls.append(step)
        return _StubWorkerChild(
            kwargs["stdout"], step.get("output", b""), step.get("returncode", 0),
            Path(args[args.index("--command-worker") + 1]), step.get("receipt"),
        )

    monkeypatch.setattr(subprocess, "Popen", popen)
    return calls


def _capture_receipts(env):
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(Path(env.evidence_store.root).glob("*.receipt.json"))
    ]


def test_missing_containment_receipt_over_committed_work_keeps_the_run(
    tmp_path, monkeypatch
):
    """The gap is recorded, the evidence is published, the run continues."""
    baseline = _git_workspace(tmp_path)
    _commit_work(tmp_path)
    _install_stub_worker(monkeypatch, [{"output": b"ok\n", "returncode": 0}])
    env = CredentialIsolatedLocalEnvironment(cwd=str(tmp_path), timeout=5)
    env._patch_baseline = baseline

    result = env.execute({"command": "echo ok"})

    extra = result["extra"]
    assert extra["descendant_scope"] == "linux_subreaper_unwitnessed"
    assert extra["containment_receipt_missing"] is True
    assert extra["capture_complete"] is False
    assert extra["containment_gap"] == "containment_unwitnessed"
    assert extra["submission_patch_state"]["committed_patch_bytes"] > 0
    assert result["output"].strip() == "ok"
    # The capture receipt is the artifact a reader gets: it must say the
    # capture was not witnessed rather than not exist.
    receipt = json.loads(Path(extra["capture_receipt"]).read_text(encoding="utf-8"))
    assert receipt["status"] == "finished"
    assert receipt["capture_complete"] is False
    assert receipt["containment_receipt_missing"] is True
    assert receipt["containment_gap"] == "containment_unwitnessed"


def test_missing_containment_receipt_over_a_pristine_tree_raises_after_publishing(
    tmp_path, monkeypatch
):
    """Broken tooling with nothing to lose still fails fast - but not silently.

    `python -I -m scripts.miniswe_supervisor` drops cwd from sys.path, so an
    uninstalled product makes every contained command fail this way
    (scripts/linux_suite_check.sh). The interpreter's own "No module named"
    line is the only thing in the spool: the command never ran.
    """
    baseline = _git_workspace(tmp_path)
    _install_stub_worker(monkeypatch, [
        {"output": b"/usr/bin/python: No module named scripts\n", "returncode": 1},
    ])
    env = CredentialIsolatedLocalEnvironment(cwd=str(tmp_path), timeout=5)
    env._patch_baseline = baseline

    with pytest.raises(RuntimeError) as caught:
        env.execute({"command": "echo ok"})

    assert str(caught.value) == "command_descendant_receipt_missing:worker_start_failed"
    from gt_engine.output_evidence import EvidenceStore

    receipts = _capture_receipts(env)
    assert len(receipts) == 1
    assert receipts[0]["status"] == "finished"
    assert receipts[0]["containment_gap"] == "worker_start_failed"
    reference = receipts[0]["output_artifact"]
    assert EvidenceStore(reference["root"]).bytes(reference["sha256"]) == (
        b"/usr/bin/python: No module named scripts\n"
    )


def test_three_consecutive_unwitnessed_commands_over_work_end_the_run(
    tmp_path, monkeypatch
):
    """Two gaps are a warning; three in a row is a harness that lost the boundary."""
    from scripts.miniswe_gt_run import CONTAINMENT_GAP_LIMIT, ContainmentLost

    assert CONTAINMENT_GAP_LIMIT == 3
    baseline = _git_workspace(tmp_path)
    _commit_work(tmp_path)
    _install_stub_worker(monkeypatch, [{"output": b"ok\n", "returncode": 0}])
    env = CredentialIsolatedLocalEnvironment(cwd=str(tmp_path), timeout=5)
    env._patch_baseline = baseline

    env.execute({"command": "echo one"})
    env.execute({"command": "echo two"})
    with pytest.raises(ContainmentLost) as caught:
        env.execute({"command": "echo three"})

    assert caught.value.misses == 3
    assert caught.value.gap == "containment_unwitnessed"
    assert caught.value.patch_state["committed_patch_bytes"] > 0
    # Every one of the three published its evidence; none was lost to the raise.
    assert len(_capture_receipts(env)) == 3


def test_one_good_containment_receipt_resets_the_consecutive_count(
    tmp_path, monkeypatch
):
    """The terminal is for a boundary that STAYS lost, not for two bad commands."""
    baseline = _git_workspace(tmp_path)
    _commit_work(tmp_path)
    _install_stub_worker(monkeypatch, [
        {"output": b"a\n", "returncode": 0},
        {"output": b"b\n", "returncode": 0},
        {"output": b"c\n", "returncode": 0, "receipt": WORKER_RECEIPT},
        {"output": b"d\n", "returncode": 0},
        {"output": b"e\n", "returncode": 0},
    ])
    env = CredentialIsolatedLocalEnvironment(cwd=str(tmp_path), timeout=5)
    env._patch_baseline = baseline

    env.execute({"command": "echo a"})
    env.execute({"command": "echo b"})
    assert env.containment_gap_streak == 2
    healthy = env.execute({"command": "echo c"})
    assert healthy["extra"]["descendant_scope"] == "linux_subreaper"
    assert healthy["extra"]["capture_complete"] is True
    assert env.containment_gap_streak == 0
    # Two more gaps: five commands, four of them unwitnessed, and still no
    # terminal - because the boundary was witnessed in between.
    env.execute({"command": "echo d"})
    env.execute({"command": "echo e"})
    assert env.containment_gap_streak == 2
    assert env.containment_gap_commands == 4



# --- the second way the boundary goes unwitnessed ----------------------------
# A worker receipt that EXISTS can still say the boundary failed: the command
# was terminated and the descendants it left behind were not reaped. That raise
# sat in the same `finally:` as the missing-receipt one and cost the same
# thing - the publish is skipped, RuntimeError classifies as internal_error,
# exit 5, Pier errors the trial and no patch reaches the grader. The receipt is
# there, so `containment_receipt_missing` is false; what is missing is the
# reaping, and the policy is identical.

NOT_REAPED_RECEIPT = {
    "schema": "gt.command_worker.v1", "reason": "deadline_exceeded",
    "returncode": -9, "capture_complete": False, "descendants_reaped": False,
    "surviving_descendants": [4242],
}


def test_unreaped_descendants_over_committed_work_keep_the_run(tmp_path, monkeypatch):
    """The receipt's own facts are recorded, not thrown away with the run."""
    baseline = _git_workspace(tmp_path)
    _commit_work(tmp_path)
    _install_stub_worker(monkeypatch, [
        {"output": b"slow\n", "returncode": 0, "receipt": NOT_REAPED_RECEIPT},
    ])
    env = CredentialIsolatedLocalEnvironment(cwd=str(tmp_path), timeout=5)
    env._patch_baseline = baseline

    result = env.execute({"command": "echo slow"})

    extra = result["extra"]
    assert extra["containment_gap"] == "descendants_not_reaped"
    assert extra["descendant_scope"] == "linux_subreaper_unwitnessed"
    # From the worker receipt, which exists - unlike the missing-receipt case,
    # where there is nothing to read and capture_complete is false by fiat.
    assert extra["capture_complete"] is False
    assert extra["surviving_descendants"] == [4242]
    assert extra["timed_out"] is True
    assert "containment_receipt_missing" not in extra
    assert result["returncode"] == -9
    assert result["exception_info"] == "deadline_exceeded"
    assert extra["submission_patch_state"]["committed_patch_bytes"] > 0
    receipt = json.loads(Path(extra["capture_receipt"]).read_text(encoding="utf-8"))
    assert receipt["containment_gap"] == "descendants_not_reaped"
    assert receipt["surviving_descendants"] == [4242]
    assert receipt["status"] == "finished"


def test_unreaped_descendants_over_a_pristine_tree_raise_after_publishing(
    tmp_path, monkeypatch
):
    """Nothing to conserve: still a refusal, still not before the publish."""
    baseline = _git_workspace(tmp_path)
    _install_stub_worker(monkeypatch, [
        {"output": b"slow\n", "returncode": 0, "receipt": NOT_REAPED_RECEIPT},
    ])
    env = CredentialIsolatedLocalEnvironment(cwd=str(tmp_path), timeout=5)
    env._patch_baseline = baseline

    with pytest.raises(RuntimeError) as caught:
        env.execute({"command": "echo slow"})

    assert str(caught.value) == "command_descendants_not_reaped"
    from gt_engine.output_evidence import EvidenceStore

    receipts = _capture_receipts(env)
    assert len(receipts) == 1
    assert receipts[0]["containment_gap"] == "descendants_not_reaped"
    reference = receipts[0]["output_artifact"]
    assert EvidenceStore(reference["root"]).bytes(reference["sha256"]) == b"slow\n"


def test_both_gap_kinds_count_toward_one_streak(tmp_path, monkeypatch):
    """The streak is about the BOUNDARY, not about which way it was lost."""
    from scripts.miniswe_gt_run import ContainmentLost

    baseline = _git_workspace(tmp_path)
    _commit_work(tmp_path)
    _install_stub_worker(monkeypatch, [
        {"output": b"a\n", "returncode": 0},
        {"output": b"b\n", "returncode": 0, "receipt": NOT_REAPED_RECEIPT},
        {"output": b"c\n", "returncode": 0},
    ])
    env = CredentialIsolatedLocalEnvironment(cwd=str(tmp_path), timeout=5)
    env._patch_baseline = baseline

    env.execute({"command": "echo a"})
    env.execute({"command": "echo b"})
    assert env.containment_gap_streak == 2
    with pytest.raises(ContainmentLost) as caught:
        env.execute({"command": "echo c"})

    assert caught.value.misses == 3
    assert env.containment_gaps == [
        "containment_unwitnessed", "descendants_not_reaped", "containment_unwitnessed",
    ]
    assert env.containment_gap_commands == 3


def test_the_containment_subcase_separates_interpreter_bytes_from_command_bytes(
    tmp_path, monkeypatch
):
    """A start failure writes a traceback into the same spool as the command.

    stderr is redirected into stdout, so "no spool bytes" cannot be the whole
    rule: an import failure of the worker entry point puts a traceback there
    while the command never ran. A signal death is never a start failure - the
    worker writes its receipt as its last statement, so a negative returncode
    means it was alive and running.
    """
    from scripts.miniswe_gt_run import _containment_gap

    assert _containment_gap(1, b"", 0) == "worker_start_failed"
    assert _containment_gap(
        1, b"/usr/bin/python: No module named scripts\n", 41
    ) == "worker_start_failed"
    traceback_bytes = (
        b"Traceback (most recent call last):\n"
        b'  File "<frozen runpy>", line 198, in _run_module_as_main\n'
        b'  File "/x/scripts/miniswe_supervisor.py", line 3, in <module>\n'
        b"RuntimeError: task code imported by harness\n"
    )
    assert _containment_gap(1, traceback_bytes, len(traceback_bytes)) == "worker_start_failed"
    # The command ran and printed: not a start failure whatever the exit code.
    assert _containment_gap(1, b"FAILED tests/test_x.py\n", 23) == "containment_unwitnessed"
    assert _containment_gap(0, b"", 0) == "containment_unwitnessed"
    assert _containment_gap(-9, b"", 0) == "containment_unwitnessed"
    assert _containment_gap(None, b"", 0) == "containment_unwitnessed"


def test_reaping_never_signals_a_group_the_child_does_not_own(monkeypatch):
    """A child pid that is not a group leader must not take the harness with it.

    The reap path called `os.killpg(child.pid, SIGKILL)` on whatever pid the
    child reported and caught only ProcessLookupError. A non-positive pid
    raises OSError(EINVAL) on Linux, which is how the contained branch died in
    CI while every Windows run skipped the branch and looked green; a pid of 0
    is worse, because killpg(0) signals the harness's own process group.
    """
    import os as _os
    import signal as _signal

    from scripts.miniswe_gt_run import _reap_descendants

    # SIGKILL exists on every posix host and on no Windows one; the branch
    # under test is the posix branch, so the constant is supplied here.
    monkeypatch.setattr(_signal, "SIGKILL", _signal.SIGTERM, raising=False)
    signalled: list[int] = []
    monkeypatch.setattr(_os, "killpg", lambda pid, sig: signalled.append(pid), raising=False)

    for pid in (-1, 0):
        _reap_descendants(_StubWorkerChildPid(pid), contained=True, posix=True)
    assert signalled == [], "a pid that cannot own a group must never reach killpg"

    _reap_descendants(_StubWorkerChildPid(4321), contained=True, posix=True)
    assert signalled == [4321]


def test_reaping_survives_a_group_that_is_already_gone(monkeypatch):
    """EINVAL, ESRCH and EPERM all mean the descendants are not ours to kill."""
    import os as _os
    import signal as _signal

    from scripts.miniswe_gt_run import _reap_descendants

    monkeypatch.setattr(_signal, "SIGKILL", _signal.SIGTERM, raising=False)

    def refuse(pid, sig):
        raise OSError(22, "Invalid argument")

    monkeypatch.setattr(_os, "killpg", refuse, raising=False)
    _reap_descendants(_StubWorkerChildPid(4321), contained=True, posix=True)


class _StubWorkerChildPid:
    """A child that has exited, carrying only the pid under test."""

    def __init__(self, pid):
        self.pid = pid
        self.returncode = 0

    def poll(self):
        return 0

    def terminate(self):
        return None

    def wait(self, timeout=None):
        return 0
