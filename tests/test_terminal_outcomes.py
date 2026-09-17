from __future__ import annotations

import json
import signal
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.miniswe_gt_run import (  # noqa: E402
    TERMINAL_EXIT_CODES,
    _classify_terminal,
)


def test_submitted_exception_maps_to_submitted():
    assert _classify_terminal(Exception("Submitted"), {}) == "submitted"


def test_lifecycle_exception_is_a_harness_error_not_solver_stuck():
    assert _classify_terminal(ValueError("tool action after STUCK"), {}) == "internal_error"
    assert _classify_terminal(ValueError("LifecycleError"), {}) == "internal_error"


def test_limits_exceeded_maps_to_budget_exhausted():
    assert _classify_terminal(RuntimeError("LimitsExceeded"), {}) == "budget_exhausted"


def test_miniswe_wall_time_exceeded_maps_to_budget_exhausted():
    time_exceeded = type("TimeExceeded", (Exception,), {})
    assert _classify_terminal(time_exceeded("wall time"), {}) == "budget_exhausted"
    assert _classify_terminal(None, {"exit_status": "TimeExceeded"}) == (
        "budget_exhausted"
    )


def test_provider_errors_map_to_provider_failed():
    assert _classify_terminal(TimeoutError("APIConnectionError"), {}) == "provider_failed"
    assert _classify_terminal(RuntimeError("AuthenticationError"), {}) == "provider_failed"
    assert _classify_terminal(
        RuntimeError("provider model mismatch"), {}
    ) == "provider_failed"


def test_typed_model_mismatch_is_distinct():
    class ProviderModelMismatch(RuntimeError):
        pass

    assert _classify_terminal(
        ProviderModelMismatch("substituted"), {}
    ) == "provider_model_mismatch"


def test_unknown_exception_maps_to_internal_error():
    assert _classify_terminal(KeyError("boom"), {}) == "internal_error"


def test_clean_exit_message_maps_to_submitted():
    assert _classify_terminal(None, {"exit_status": "Submitted"}) == "submitted"
    assert _classify_terminal(None, {"submission": "final"}) == "submitted"


def test_exit_codes_separate_valid_solver_outcomes_from_process_failures():
    assert TERMINAL_EXIT_CODES["submitted_verified"] == 0
    assert TERMINAL_EXIT_CODES["submitted_unverified"] == 0
    # A completed but unsuccessful solver attempt must remain gradable.  Only
    # shared infrastructure/process faults make Harbor treat the agent phase as
    # failed.
    for terminal in ("stuck", "budget_exhausted", "task_failed"):
        assert TERMINAL_EXIT_CODES[terminal] == 0
    for terminal in ("timeout", "provider_failed", "internal_error", "setup_error"):
        assert TERMINAL_EXIT_CODES[terminal] > 0


def test_setup_failure_writes_report_and_manifest_and_returns_nonzero(
    monkeypatch, tmp_path
):
    import scripts.miniswe_gt_run as runner

    def explode(**kwargs):
        raise RuntimeError("injected setup failure")

    metrics = tmp_path / "report.json"
    manifest = tmp_path / "manifest.json"
    monkeypatch.setattr(runner, "build_agent", explode)
    monkeypatch.setattr(sys, "argv", [
        "miniswe_gt_run.py",
        "--task", "fix it",
        "--cwd", str(tmp_path),
        "--state-dir", str(tmp_path / "state"),
        "--metrics", str(metrics),
        "--manifest", str(manifest),
        "--gt-off",
    ])
    assert runner.main() == TERMINAL_EXIT_CODES["setup_error"]
    report = json.loads(metrics.read_text(encoding="utf-8"))
    assert report["terminal"] == "setup_error"
    assert "injected setup failure" in report["exception"]
    repro = json.loads(manifest.read_text(encoding="utf-8"))
    assert repro["research_valid"] is False


def test_killed_requested_gt_on_cannot_be_reported_as_intentional_off(monkeypatch, tmp_path):
    import scripts.miniswe_gt_run as runner

    agent = SimpleNamespace(model=SimpleNamespace(), n_calls=0, cost=0,
                            run=lambda task: {"submission": False})
    monkeypatch.setattr(runner, "build_agent", lambda **kwargs: (agent, None, None))
    monkeypatch.setenv("GT_KILL_SWITCH", "1")
    metrics = tmp_path / "report.json"
    manifest = tmp_path / "manifest.json"
    monkeypatch.setattr(sys, "argv", ["miniswe_gt_run.py", "--task", "fix it",
        "--cwd", str(tmp_path), "--state-dir", str(tmp_path / "state"),
        "--metrics", str(metrics), "--manifest", str(manifest), "--gt-mode", "assistive"])
    assert runner.main() == TERMINAL_EXIT_CODES["task_failed"]
    report = json.loads(metrics.read_text())
    repro = json.loads(manifest.read_text())
    assert report["gt_mode"] == "assistive"
    assert repro["gt_mode"] == "assistive"
    assert repro["research_valid"] is False


def test_receipt_issuance_failure_preserves_native_exit_and_writes_error_receipts(
    monkeypatch, tmp_path, capsys
):
    import gt_harness.runtime_receipts as receipts
    import scripts.miniswe_gt_run as runner

    output = tmp_path / "trajectory.json"

    class FakeAgent:
        model = SimpleNamespace()
        n_calls = 2
        cost = 0.25

        def run(self, _task):
            output.write_text(
                json.dumps({"messages": [], "info": {"model_stats": {"api_calls": 2}}}),
                encoding="utf-8",
            )
            return {"submission": False}

    def fail_receipt_issuance(**_kwargs):
        raise ValueError("injected conservation failure")

    monkeypatch.setattr(
        runner, "build_agent", lambda **_kwargs: (FakeAgent(), None, None)
    )
    monkeypatch.setattr(receipts, "issue_runtime_receipts", fail_receipt_issuance)
    metrics = tmp_path / "miniswe_report.json"
    product = tmp_path / "gt-run.json"
    adapter = tmp_path / "benchmark-adapter.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "miniswe_gt_run.py",
            "--task", "fix it",
            "--cwd", str(tmp_path),
            "--state-dir", str(tmp_path / "state"),
            "--output", str(output),
            "--metrics", str(metrics),
            "--product-receipt", str(product),
            "--adapter-receipt", str(adapter),
            "--task-id", "task-a",
            "--product-source-sha", "f" * 40,
            "--time-budget-seconds", "60",
            "--gt-off",
        ],
    )

    assert runner.main() == TERMINAL_EXIT_CODES["task_failed"]
    assert "runtime receipt issuance failed" in capsys.readouterr().err
    report = json.loads(metrics.read_text(encoding="utf-8"))
    assert report["terminal"] == "task_failed"
    assert report["receipt_issuance"]["status"] == "ERROR"
    product_receipt = json.loads(product.read_text(encoding="utf-8"))
    adapter_receipt = json.loads(adapter.read_text(encoding="utf-8"))
    assert product_receipt["status"] == "ERROR"
    assert product_receipt["terminal"] == "task_failed"
    assert product_receipt["exit_code"] == TERMINAL_EXIT_CODES["task_failed"]
    assert product_receipt["effective_model"] == "deepseek-v4-flash"
    assert product_receipt["provider_calls"] == 2
    assert product_receipt["receipt_issuance"]["code"] == (
        "runtime_receipt_issuance_failed"
    )
    assert adapter_receipt["status"] == "ERROR"
    assert adapter_receipt["effective_model"] == "deepseek-v4-flash"
    assert adapter_receipt["receipt_issuance"] == product_receipt["receipt_issuance"]


def test_sigterm_during_agent_run_conserves_patch_and_terminal_artifacts(
    monkeypatch, tmp_path
):
    import scripts.miniswe_gt_run as runner

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "GT Test"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "gt-test@example.invalid"],
        cwd=tmp_path,
        check=True,
    )
    source = tmp_path / "source.py"
    source.write_text("before = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "source.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)

    class FakeAgent:
        model = SimpleNamespace()
        # The patch exporter reads agent.env.runtime_layout.excluded_roots
        # (miniswe_gt_run.py:991) to keep generated cache out of the patch.
        # Without an env this fake could never reach export at all: the run
        # recorded patch_export_error AttributeError and wrote no patch, so
        # the conservation property this test exists to prove was never
        # actually exercised - the assertion below failed on a missing file
        # rather than on missing content.
        env = SimpleNamespace(
            runtime_layout=SimpleNamespace(excluded_roots=())
        )
        n_calls = 0
        cost = 0

        def run(self, _task):
            source.write_text("after = 2\n", encoding="utf-8")
            signal.raise_signal(signal.SIGTERM)
            raise AssertionError("SIGTERM handler did not interrupt the run")

    monkeypatch.setattr(
        runner, "build_agent", lambda **_kwargs: (FakeAgent(), None, None)
    )
    metrics = tmp_path / "metrics.json"
    manifest = tmp_path / "manifest.json"
    patch = tmp_path / "model.patch"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "miniswe_gt_run.py",
            "--task",
            "fix it",
            "--cwd",
            str(tmp_path),
            "--state-dir",
            str(tmp_path / "state"),
            "--metrics",
            str(metrics),
            "--manifest",
            str(manifest),
            "--patch-output",
            str(patch),
            "--gt-off",
        ],
    )

    assert runner.main() == TERMINAL_EXIT_CODES["timeout"]
    assert "after = 2" in patch.read_text(encoding="utf-8")
    report = json.loads(metrics.read_text(encoding="utf-8"))
    assert report["terminal"] == "timeout"
    # An export that failed is recorded, not silent. Asserting its absence
    # keeps "the patch exists" from being satisfied by a stale file.
    assert "patch_export_error" not in report
    assert json.loads(manifest.read_text(encoding="utf-8"))["research_valid"] is False


# --------------------------------------------------------------------------- #
# The submitted_* split: what "verified" is allowed to mean
# --------------------------------------------------------------------------- #


def test_blind_baseline_terminal_is_not_submitted_verified():
    """A terminal may not claim verification the gate could not establish.

    `completion_state()["verified"]` is computed from predicate and plan-row
    status alone (`miniswe_integration.final_state`): it reads neither
    `baseline_status` nor `completion_proven`, so a run whose regression
    baseline never produced a conservation verdict - `unknown`, `incomplete`,
    `no_tests_observed`, `timeout`, `not_attempted` - could close
    `submitted_verified` on rows proven against a proxy the grading signal
    never touched. `persistent_plan/gate.py` already decides this correctly
    and has had no non-test consumer since it was written.
    """
    from scripts.miniswe_gt_run import _submission_terminal

    blind = {
        "verified": True,
        "completion_proven": False,
        "baseline_status": "unknown",
    }
    assert _submission_terminal(blind) == "submitted_unverified"

    proven = {
        "verified": True,
        "completion_proven": True,
        "baseline_status": "intact",
    }
    assert _submission_terminal(proven) == "submitted_verified"

    # The gate cannot rescue an unverified row ledger either.
    assert _submission_terminal(
        {"verified": False, "completion_proven": True, "baseline_status": "intact"}
    ) == "submitted_unverified"


def test_a_session_with_no_gate_decision_keeps_todays_terminal():
    """No plan means no gate evidence, and absence is not a contradiction.

    GT-on runs with the persistent plan off journal no `plan_gate_decision` at
    all, so `completion_proven` is absent rather than False. Treating absent as
    False would relabel every plan-off run, which is a different claim from the
    one this defect is about.
    """
    from scripts.miniswe_gt_run import _submission_terminal

    assert _submission_terminal({"verified": True}) == "submitted_verified"
    assert _submission_terminal({"verified": False}) == "submitted_unverified"
    assert _submission_terminal(None) == "submitted_unverified"


# --------------------------------------------------------------------------- #
# Provider classification must not capture harness faults
# --------------------------------------------------------------------------- #


def test_git_failure_is_not_a_provider_failure():
    """A subprocess fault must never be graded as a provider failure.

    Run 35262214538 (TB2 extract-elf) exported no patch because the task
    workspace had no git baseline.  `git read-tree ''` raised
    CalledProcessError, whose stock message ends "returned non-zero exit
    status 128".  `_classify_terminal` matched the bare substring "status"
    against that message and returned provider_failed, which exits 4, which
    makes harbor raise NonZeroAgentExitCodeError and error the trial.  A
    harness fault was reported as the provider refusing the model, and the
    task was never graded.

    The provider heuristic exists for litellm classes that "surface with
    provider-ish names", so it belongs on the class name, never on the
    message text an arbitrary subprocess controls.
    """
    import subprocess

    from scripts.miniswe_gt_run import TERMINAL_EXIT_CODES, _classify_terminal

    git_failure = subprocess.CalledProcessError(128, ["git", "read-tree", ""])
    assert "status" in str(git_failure).lower()  # the substring that misfired
    terminal = _classify_terminal(git_failure, {})
    assert terminal != "provider_failed"
    assert terminal == "internal_error"
    assert TERMINAL_EXIT_CODES[terminal] != 4

    # Real provider classes must still classify as provider failures, both by
    # exact name and by the provider-ish-name fallback.
    class APIConnectionError(Exception):
        pass

    class ProviderOverloadedError(Exception):
        pass

    assert _classify_terminal(APIConnectionError("boom"), {}) == "provider_failed"
    assert _classify_terminal(ProviderOverloadedError("boom"), {}) == "provider_failed"

    # Message matching stays: litellm errors arrive wrapped in generic
    # exceptions carrying the provider class name, which
    # test_provider_errors_map_to_provider_failed pins.  Only the bare
    # "status" token is gone, so a subprocess message cannot claim the
    # provider failed.
    assert _classify_terminal(ValueError("baseline_unavailable"), {}) == "internal_error"
    assert _classify_terminal(
        subprocess.CalledProcessError(1, ["git", "diff", "--cached"]), {}
    ) == "internal_error"


def test_failed_patch_export_does_not_overwrite_a_non_submitted_terminal(
    monkeypatch, tmp_path
):
    """A run that never claimed a submission keeps the terminal it earned.

    Run 35262214538 (TB2 extract-elf) burned all 100 turns and mini-swe
    returned exit_status "LimitsExceeded" - budget_exhausted, which exits 0 and
    leaves the workspace for the official verifier, exactly as
    TERMINAL_EXIT_CODES documents.  The workspace then had no git baseline, so
    patch export raised, and the export failure was promoted to the run's
    terminating exception.  That promotion, not the agent, decided the
    terminal: harbor saw a non-zero exit, errored the trial, and the run was
    recorded as an infrastructure failure with no grade.

    The export failure is still recorded.  It just cannot overwrite an outcome
    the solver already reached.
    """
    import scripts.miniswe_gt_run as runner

    # No git init: the patch exporter cannot resolve a baseline here, which is
    # the production condition for a terminal-bench task workspace.
    class FakeAgent:
        model = SimpleNamespace()
        env = SimpleNamespace(runtime_layout=SimpleNamespace(excluded_roots=()))
        n_calls = 100
        cost = 0

        def run(self, _task):
            return {"exit_status": "LimitsExceeded", "submission": ""}

    monkeypatch.setattr(
        runner, "build_agent", lambda **_kwargs: (FakeAgent(), None, None)
    )
    metrics = tmp_path / "metrics.json"
    patch = tmp_path / "model.patch"
    monkeypatch.setattr(
        sys, "argv",
        [
            "miniswe_gt_run.py", "--task", "do it", "--cwd", str(tmp_path),
            "--state-dir", str(tmp_path / "state"), "--metrics", str(metrics),
            "--patch-output", str(patch), "--gt-off",
        ],
    )

    assert runner.main() == TERMINAL_EXIT_CODES["budget_exhausted"] == 0
    report = json.loads(metrics.read_text(encoding="utf-8"))
    assert report["terminal"] == "budget_exhausted"
    # The failure is conserved, never silent.
    assert "patch_export_error" in report
