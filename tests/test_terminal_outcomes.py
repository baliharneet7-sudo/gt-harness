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

    # Real provider classes must still classify as provider failures: a
    # litellm/openai class by its module root (HIGH-1 made that root a
    # precondition, so the stand-in carries it), and the harness-raised
    # ProviderOverloadedError by name from wherever it is defined - it is the
    # one name on the any-module allow list precisely because only this harness
    # raises it.
    APIConnectionError = type(
        "APIConnectionError", (Exception,), {"__module__": "litellm.exceptions"}
    )

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


def test_a_submission_is_not_invalidated_when_no_patch_could_exist(
    monkeypatch, tmp_path
):
    """No baseline means no patch is producible, so its absence proves nothing.

    Cohort 35298094010 lost four tasks this way - headless-terminal,
    feal-linear-cryptanalysis, count-dataset-tokens and
    torch-pipeline-parallelism. Each agent finished and mini-swe returned
    exit_status "Submitted" (headless-terminal after 73 turns). The
    terminal-bench container ships no git binary, so patch export raised
    FileNotFoundError: 'git', and because the earned terminal WAS a submission
    the export failure was promoted to the run's terminating exception:
    internal_error, exit 5, harbor errored the trial, no official grade.

    Promotion on submit exists so an empty patch cannot be graded as the
    model's answer, which is a SWE-Live invariant - there the patch IS the
    submission. On terminal-bench the official verifier grades container state
    and the patch is evidence only. Requiring one where git does not exist
    discards completed work.

    Keep promotion wherever a baseline exists, on either benchmark: a run that
    could have produced a patch and did not is still suspect.
    """
    import scripts.miniswe_gt_run as runner

    class FakeAgent:
        model = SimpleNamespace()
        env = SimpleNamespace(runtime_layout=SimpleNamespace(excluded_roots=()))
        n_calls = 73
        cost = 0

        def run(self, _task):
            return {"exit_status": "Submitted", "submission": "done"}

    monkeypatch.setattr(
        runner, "build_agent", lambda **_kwargs: (FakeAgent(), None, None)
    )
    metrics = tmp_path / "metrics.json"
    patch = tmp_path / "model.patch"
    # No git init: _repository_head finds no baseline, exactly as a
    # terminal-bench workspace presents.
    monkeypatch.setattr(
        sys, "argv",
        [
            "miniswe_gt_run.py", "--task", "do it", "--cwd", str(tmp_path),
            "--state-dir", str(tmp_path / "state"), "--metrics", str(metrics),
            "--patch-output", str(patch), "--gt-off",
        ],
    )

    # Exit 0: `submitted` is a completed solver outcome like stuck,
    # budget_exhausted and task_failed, so the process must not report a
    # harness fault for it either.
    assert runner.main() == 0
    report = json.loads(metrics.read_text(encoding="utf-8"))
    # The promotion is what this fix controls: the submission survives instead
    # of being rewritten as a harness fault.
    assert report["terminal"] == "submitted"
    assert report["terminal"] != "internal_error"
    # The failure is still recorded, never silent.
    assert "patch_export_error" in report
    # `_submission_terminal` produces submitted_verified/submitted_unverified
    # and only runs when GT is active, so under --gt-off the terminal stays
    # the plain `submitted` produced above. TERMINAL_EXIT_CODES had no key for
    # it, so `.get(terminal, internal_error)` mapped every GT-off submission
    # to exit 5 - the same harbor trial error this test exists to prevent,
    # arriving one step later.
    from scripts.miniswe_gt_run import TERMINAL_EXIT_CODES

    assert TERMINAL_EXIT_CODES["submitted"] == 0
    assert report["exit_code"] == 0
    assert TERMINAL_EXIT_CODES["submitted_verified"] == 0
    assert TERMINAL_EXIT_CODES["submitted_unverified"] == 0


def test_ordinary_english_words_are_not_provider_failures():
    """The provider heuristic may not fire on a substring of a plain word.

    After run 35262214538 the "status" token was removed, but the remaining
    bare substrings were fragile the same way: lowercasing
    f"{class name} {message}" and testing "api" matches "capital", "auth"
    matches "author", and "provider" matches any message that merely mentions
    one.  Every such hit exits 4, which makes harbor raise
    NonZeroAgentExitCodeError and error a trial that the provider never
    touched.

    A provider failure is now named by the exception CLASS - either the exact
    table, or a camel-case word of the class name - and by the message only
    for the wrapped-provider shape that
    test_provider_errors_map_to_provider_failed pins.
    """
    assert _classify_terminal(ValueError("capital allocation"), {}) == "internal_error"
    assert _classify_terminal(RuntimeError("author missing"), {}) == "internal_error"
    assert _classify_terminal(
        RuntimeError("the provider was fine; the workspace was not"), {}
    ) == "internal_error"
    assert _classify_terminal(
        RuntimeError("no such api documented"), {}
    ) == "internal_error"


def test_wrapped_provider_class_names_still_classify_from_the_message():
    """litellm errors arrive wrapped, carrying the class name in the text.

    This is the contract test_provider_errors_map_to_provider_failed pins, so
    message matching stays - narrowed to whole-token hits on known provider
    exception class names instead of bare substrings.
    """
    assert _classify_terminal(RuntimeError("APIConnectionError"), {}) == "provider_failed"
    assert _classify_terminal(
        RuntimeError("litellm.InternalServerError: upstream said no"), {}
    ) == "provider_failed"
    assert _classify_terminal(
        RuntimeError("provider model mismatch"), {}
    ) == "provider_failed"


def test_provider_class_names_classify_without_help_from_the_message():
    """A litellm class is recognised by its own type, with no message help.

    HIGH-1 made the litellm/openai module root a precondition for the roster of
    provider class names, so the stand-ins here carry the root the classes they
    stand in for really have.  The message says nothing provider-ish in either
    case, which is the property this test exists to pin.
    """
    RateLimitError = type(
        "RateLimitError", (Exception,), {"__module__": "litellm.exceptions"}
    )
    ServiceUnavailableError = type(
        "ServiceUnavailableError", (Exception,), {"__module__": "litellm.exceptions"}
    )

    assert _classify_terminal(RateLimitError("429"), {}) == "provider_failed"
    assert _classify_terminal(ServiceUnavailableError("503"), {}) == "provider_failed"

    # ...and the same names from somewhere else are not provider verdicts.
    foreign = type("RateLimitError", (Exception,), {"__module__": "harbor.api"})
    assert _classify_terminal(foreign("429"), {}) == "internal_error"


def test_missing_git_binary_is_an_internal_error_not_a_provider_failure():
    """Cohort 35298094010 lost four tasks to `FileNotFoundError: 'git'`.

    A terminal-bench container ships no git binary, so patch export raises
    FileNotFoundError.  Under the old heuristic nothing claimed it and it fell
    through to internal_error by luck; naming it makes the classification a
    decision instead of a default, and keeps a future token from capturing it.
    """
    assert _classify_terminal(FileNotFoundError("git"), {}) == "internal_error"
    assert _classify_terminal(PermissionError("denied"), {}) == "internal_error"
    assert _classify_terminal(OSError("disk"), {}) == "internal_error"
    assert _classify_terminal(
        subprocess.CalledProcessError(128, ["git", "read-tree", ""]), {}
    ) == "internal_error"


def test_a_gt_off_submission_exits_zero():
    """`submitted` is a completed solver outcome, so it must map to exit 0.

    `_submission_terminal` only runs when GT is active, so under `--gt-off`
    the terminal stays the plain `submitted` produced by `_classify_terminal`.
    With no key for it, `TERMINAL_EXIT_CODES.get(terminal, internal_error)`
    turned every GT-off submission into exit 5 - the same harbor trial error
    cohort 35298094010 hit from the other direction.
    """
    assert TERMINAL_EXIT_CODES["submitted"] == 0


# --------------------------------------------------------------------------- #
# H3: classification is decided by TYPE, not by splitting a class name into
# camel-case words.  The word heuristic matched {api, auth, authentication,
# connection, provider, timeout, unavailable} against the words of ANY class
# name, so every OSError subclass - ConnectionResetError, ConnectionRefusedError,
# TimeoutError - and every local timeout was graded as the provider refusing the
# model: exit 4, harbor raises NonZeroAgentExitCodeError, the trial is errored,
# and gt-run.json shows zero provider failures.  That is the run-35262214538
# chain this classifier exists to break, arriving through the class name instead
# of the message.
# --------------------------------------------------------------------------- #


def test_stdlib_faults_are_internal_errors_whatever_their_name_spells():
    """A stdlib/OS fault is a harness fault, decided by type before any text.

    Every case here was classified provider_failed by the camel-case word
    heuristic: `TimeoutExpired` and `TimeoutError` contain the word "timeout",
    `ConnectionResetError` and `ConnectionRefusedError` contain "connection".
    None of them involves a provider.  A local timeout is not a provider
    verdict.
    """
    cases = (
        subprocess.TimeoutExpired(["pytest"], 60),
        TimeoutError("local op timed out"),
        ConnectionResetError("reset by peer"),
        ConnectionRefusedError("refused"),
        BrokenPipeError("broken pipe"),
    )
    for exception in cases:
        terminal = _classify_terminal(exception, {})
        assert terminal == "internal_error", (type(exception).__name__, terminal)
        assert TERMINAL_EXIT_CODES[terminal] != TERMINAL_EXIT_CODES["provider_failed"]


def test_harness_messages_that_merely_name_a_provider_shape_are_internal():
    """A generic wrapper is only a provider failure when it carries a provider name.

    "Timeout while waiting for the docker daemon" is infrastructure, and
    "BadRequestError from our own harness call" is our own call site quoting a
    class it did not receive.  Message matching is kept only for the wrapped
    shape `test_provider_errors_map_to_provider_failed` pins: the message IS the
    provider class name, or the name arrives module-qualified
    (`litellm.InternalServerError: ...`).  Prose that mentions one does not
    qualify.
    """
    assert _classify_terminal(
        RuntimeError("Timeout while waiting for the docker daemon"), {}
    ) == "internal_error"
    assert _classify_terminal(
        RuntimeError("BadRequestError from our own harness call"), {}
    ) == "internal_error"


def test_litellm_exception_types_are_provider_failures_by_type():
    """The provider family is recognised through the MRO, not the spelling."""

    rate_limit = type("RateLimitError", (Exception,), {
        "__module__": "litellm.exceptions",
    })
    assert _classify_terminal(rate_limit("429"), {}) == "provider_failed"

    # A subclass of a litellm error is still a provider failure, even when its
    # own name spells nothing provider-ish and it lives in our package.
    class WrappedUpstream(rate_limit):
        pass

    assert _classify_terminal(WrappedUpstream("429"), {}) == "provider_failed"

    # The module is an independent signal: an openai class whose name is not in
    # the family roster still classifies by where it came from.
    unknown_openai = type("SomethingNewError", (Exception,), {
        "__module__": "openai._exceptions",
    })
    assert _classify_terminal(unknown_openai("boom"), {}) == "provider_failed"


def test_provider_family_names_do_not_classify_from_a_foreign_module():
    """HIGH-1 inverted this: the family NAME alone is NOT enough.

    This test previously pinned the opposite - "the roster is authoritative on
    its own and the module check is an additional signal, never a
    precondition".  That rule graded `pier.errors.NotFoundError`,
    `docker.errors.Timeout` and `harbor.api.APIError` as the provider refusing
    the model, because half the roster is made of words that ordinary
    infrastructure libraries also use.  The module root is now a precondition:
    a roster name classifies provider_failed only when the litellm/openai root
    is reached through the MRO, or when the name is one this harness raises
    itself (`ProviderOverloadedError`).
    """
    local_rate_limit = type("RateLimitError", (Exception,), {
        "__module__": "myharness",
    })
    assert _classify_terminal(local_rate_limit("429"), {}) == "internal_error"

    # The one name that still classifies from anywhere is the harness's own.
    local_overloaded = type("ProviderOverloadedError", (Exception,), {
        "__module__": "myharness",
    })
    assert _classify_terminal(local_overloaded("busy"), {}) == "provider_failed"


# --------------------------------------------------------------------------- #
# HIGH-1 (round 3): the litellm/openai module root is a PRECONDITION for the
# roster of provider class names, not an extra signal.  The roster holds
# generic words - APIError, NotFoundError, Timeout, ConflictError - that
# infrastructure libraries in this very environment also use, so matching the
# NAME wherever it was defined hands run 35262214538's chain a second door:
# exit 4, harbor raises NonZeroAgentExitCodeError and errors the trial, and
# gt-run.json records zero provider failures for an infrastructure fault.
# --------------------------------------------------------------------------- #


def test_roster_names_from_foreign_modules_are_not_provider_failures():
    """The three reproductions: our own stack spells these names too.

    `pier.errors.NotFoundError` (the Datacurve runner), `docker.errors.Timeout`
    and `harbor.api.APIError` are infrastructure faults.  `docker.errors.APIError`
    and `requests.exceptions.Timeout` are importable in the installed
    environment, so this is not hypothetical.
    """
    cases = (
        type("NotFoundError", (Exception,), {"__module__": "pier.errors"}),
        type("Timeout", (Exception,), {"__module__": "docker.errors"}),
        type("APIError", (Exception,), {"__module__": "harbor.api"}),
    )
    for exc_type in cases:
        terminal = _classify_terminal(exc_type("boom"), {})
        assert terminal == "internal_error", (
            exc_type.__module__,
            exc_type.__name__,
            terminal,
        )
        assert (
            TERMINAL_EXIT_CODES[terminal]
            != TERMINAL_EXIT_CODES["provider_failed"]
        )


def test_inheritance_carries_the_provider_root_into_a_harness_module():
    """A subclass of a real litellm class is still a provider failure.

    The precondition is on the MRO, not on the raised class alone: wrapping a
    litellm error in a harness-defined subclass must not launder it into an
    internal error.
    """
    litellm_rate_limit = type(
        "RateLimitError", (Exception,), {"__module__": "litellm.exceptions"}
    )

    class HarnessWrappedRateLimit(litellm_rate_limit):
        pass

    assert HarnessWrappedRateLimit.__module__.split(".", 1)[0] not in (
        "litellm",
        "openai",
    )
    assert (
        _classify_terminal(HarnessWrappedRateLimit("429"), {}) == "provider_failed"
    )


def test_exact_name_table_provider_entries_obey_the_module_precondition():
    """The exact-name table is the first door, so it needs the same lock.

    `APIError`, `APIConnectionError`, `AuthenticationError` and
    `BadRequestError` all sit in `_EXCEPTION_TERMINAL` mapped to
    provider_failed, and that lookup runs before any MRO walk.  Without the
    precondition, `harbor.api.APIError` never reaches the roster check at all.
    """
    for name in (
        "APIError",
        "APIConnectionError",
        "AuthenticationError",
        "BadRequestError",
    ):
        foreign = type(name, (Exception,), {"__module__": "harbor.api"})
        assert _classify_terminal(foreign("boom"), {}) == "internal_error", name
        genuine = type(name, (Exception,), {"__module__": "litellm.exceptions"})
        assert _classify_terminal(genuine("boom"), {}) == "provider_failed", name


# --------------------------------------------------------------------------- #
# MEDIUM-6: "submitted" is now an exit code 0 terminal, so the substring rule
# on the exception MESSAGE reports a crash as a success.
# --------------------------------------------------------------------------- #


def test_a_crash_that_merely_mentions_a_submission_is_not_a_submission():
    """`RuntimeError("failed after the patch was submitted")` is a crash.

    `TERMINAL_EXIT_CODES["submitted"]` is 0, so the old
    `if "submitted" in lowered` rule turned any harness exception whose prose
    contains the word into a clean GT-off pass.
    """
    crashes = (
        RuntimeError("failed after the patch was submitted"),
        ValueError("submitted patch could not be re-read"),
        RuntimeError("SubmissionError: the submitted diff was empty"),
    )
    for exception in crashes:
        terminal = _classify_terminal(exception, {})
        assert terminal == "internal_error", (str(exception), terminal)
        assert TERMINAL_EXIT_CODES[terminal] != 0

    # mini-swe's own signal survives, by class name and by the bare exit
    # message `test_submitted_exception_maps_to_submitted` pins. L-4: the
    # class arm now also requires the minisweagent module root, so the stand-in
    # has to declare it - a bare look-alike is `pier.errors.Submitted`, which
    # `test_a_foreign_class_named_submitted_is_not_a_submission` pins as an
    # internal_error.
    submitted = type("Submitted", (Exception,), {"__module__": "minisweagent.exceptions"})
    assert _classify_terminal(submitted("anything at all"), {}) == "submitted"
    assert _classify_terminal(Exception("Submitted"), {}) == "submitted"


# --------------------------------------------------------------------------- #
# L-4: `Submitted` maps to exit 0, and the class-name path matched the bare
# name from ANY module - so `pier.errors.Submitted` would have reported an
# infrastructure fault as a clean pass. Every provider name already requires
# the litellm/openai module precondition (HIGH-1); mini-swe's own success
# signal now requires the minisweagent one.
# --------------------------------------------------------------------------- #


def test_the_real_minisweagent_submitted_class_still_maps_to_submitted():
    from minisweagent.exceptions import Submitted

    assert Submitted.__module__.split(".", 1)[0] == "minisweagent"
    assert _classify_terminal(Submitted("anything at all"), {}) == "submitted"
    assert TERMINAL_EXIT_CODES["submitted"] == 0


def test_a_foreign_class_named_submitted_is_not_a_submission():
    """`pier.errors.Submitted` is infrastructure, and exit 0 would hide it."""
    for module in ("pier.errors", "harbor.api", "docker.errors", "requests.exceptions"):
        foreign = type("Submitted", (Exception,), {"__module__": module})
        terminal = _classify_terminal(foreign("boom"), {})
        assert terminal == "internal_error", module
        assert TERMINAL_EXIT_CODES[terminal] != 0


def test_a_minisweagent_subclass_of_submitted_is_still_a_submission():
    """Inheritance carries the module root, exactly as the provider walk does."""
    from minisweagent.exceptions import Submitted

    derived = type("SubmittedWithPatch", (Submitted,), {"__module__": "gt_engine.x"})
    assert _classify_terminal(derived("done"), {}) == "submitted"


def test_the_bare_exit_message_survives_the_module_precondition():
    """The asymmetry is deliberate and pinned by
    test_submitted_exception_maps_to_submitted: mini-swe writes the exit
    message `Submitted` through handle_uncaught_exception and it reaches us on
    a plain Exception, which has no minisweagent module to check.
    """
    assert _classify_terminal(Exception("Submitted"), {}) == "submitted"
    foreign = type("Submitted", (Exception,), {"__module__": "pier.errors"})
    assert _classify_terminal(foreign("Submitted"), {}) == "submitted"
