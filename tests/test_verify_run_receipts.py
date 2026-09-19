"""Cross-receipt consistency: the contradictions nobody was reading together.

Every fixture here is a reconstruction of a real run, named in the test. The
receipts themselves were each internally consistent; the defect only shows up
when two of them are read side by side, which is exactly what nothing did.
"""
from __future__ import annotations

import ast
import json
import shutil
from pathlib import Path

import pytest

from scripts.verify_run_receipts import (
    CHECK_IDS,
    CONTRADICTION,
    INFO,
    OK,
    UNKNOWN,
    WARNING,
    AmbiguousTrialError,
    build_receipt,
    find_named,
    find_trials,
    load_inputs,
    main,
    run_checks,
)

ROOT = Path(__file__).resolve().parents[1]
# gt-run.json is written by gt_harness/runtime_receipts.py. A fixture is only
# evidence while it spells the keys that producer emits: the check that read
# provider_failure_count / provider_request_count / provider_response_count
# was permanently UNKNOWN on every real receipt, and the fixture that invented
# those keys is what hid it.
PRODUCER = ROOT / "gt_harness" / "runtime_receipts.py"
RECORDED_RECEIPTS = sorted(
    (ROOT / "tests" / "fixtures").glob("**/recorded_runs/*/provenance/gt-run.json")
)


def _gt_run_builders(tree: ast.Module) -> list[tuple[ast.AST, str]]:
    """Every function that writes gt-run.json, with the name of its dict.

    Located by what the function does - ``_atomic_json(product_receipt_path,
    <name>)`` - and not by its name, so a rename cannot silently empty the
    key set and turn this guard back into a rubber stamp.
    """
    builders: list[tuple[ast.AST, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for call in ast.walk(node):
            if (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id == "_atomic_json"
                and len(call.args) == 2
                and isinstance(call.args[0], ast.Name)
                and call.args[0].id == "product_receipt_path"
                and isinstance(call.args[1], ast.Name)
            ):
                builders.append((node, call.args[1].id))
                break
    return builders


def _literal_keys(node: ast.Dict) -> set[str]:
    return {
        key.value
        for key in node.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }


def _string_constants(node: ast.AST) -> set[str]:
    return {
        child.value
        for child in ast.walk(node)
        if isinstance(child, ast.Constant) and isinstance(child.value, str)
    }


def _returned_dict_keys(tree: ast.Module, function_name: str) -> set[str]:
    """Keys of every dict literal a module-level function returns.

    ``**provider_usage`` in the product literal is still the receipt's own
    spelling; the names live one call away, in the helper that builds it.
    """
    keys: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            for statement in ast.walk(node):
                if isinstance(statement, ast.Return) and isinstance(statement.value, ast.Dict):
                    keys |= _literal_keys(statement.value)
    return keys


def _producer_receipt_keys() -> set[str]:
    """Every key the gt-run.json builders themselves write.

    M-5: this used to be every string key of every ast.Dict anywhere in the
    producer - 130 keys, 111 of which no recorded receipt carries - so the
    adapter receipt's names, the delivery budget's and the graph
    certification's were all accepted as gt-run.json spellings and the guard
    bit on nothing. Only what the builders assemble into the product receipt
    counts: the dict literal assigned to it, anything unpacked into that
    literal, subscript assignments onto it, and the names an ``update`` on it
    moves across.
    """
    tree = ast.parse(PRODUCER.read_text(encoding="utf-8"))
    keys: set[str] = set()
    for function, receipt in _gt_run_builders(tree):
        # `provider_usage = _provider_usage(...)`: the name unpacked into the
        # literal, mapped to the helper that returns it.
        produced_by: dict[str, str] = {
            statement.targets[0].id: statement.value.func.id
            for statement in ast.walk(function)
            if isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and isinstance(statement.value, ast.Call)
            and isinstance(statement.value.func, ast.Name)
        }
        for statement in ast.walk(function):
            value = getattr(statement, "value", None)
            targets = list(getattr(statement, "targets", None) or [])
            if isinstance(statement, ast.AnnAssign):
                targets = [statement.target]
            for target in targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id == receipt
                    and isinstance(value, ast.Dict)
                ):
                    keys |= _literal_keys(value)
                    for key, item in zip(value.keys, value.values, strict=True):
                        if key is None and isinstance(item, ast.Name):
                            keys |= _returned_dict_keys(tree, produced_by.get(item.id, ""))
                if (
                    isinstance(target, ast.Subscript)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == receipt
                    and isinstance(target.slice, ast.Constant)
                    and isinstance(target.slice.value, str)
                ):
                    keys.add(target.slice.value)
            if (
                isinstance(statement, ast.Call)
                and isinstance(statement.func, ast.Attribute)
                and statement.func.attr == "update"
                and isinstance(statement.func.value, ast.Name)
                and statement.func.value.id == receipt
            ):
                # Both shapes the builders use: a dict literal, and a
                # comprehension filtered by `key in {...}`.
                keys |= _string_constants(statement)
    return keys


def _real_receipt_keys() -> set[str]:
    """The union of a recorded receipt's keys and the producer's spellings."""
    recorded: set[str] = set()
    for path in RECORDED_RECEIPTS:
        body = json.loads(path.read_text(encoding="utf-8"))
        recorded |= set(body)
    return recorded | _producer_receipt_keys()


def _write(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _progress(task_id: str, **overrides) -> dict:
    task = {
        "task_id": task_id,
        "state": "verifier_failed",
        "official_verifier": True,
        "reward": 0,
        "failure_class": "graded",
        "error_code": "",
    }
    task.update(overrides)
    return {
        "schema": "gt.benchmark_progress.v1",
        "benchmark_suite": "terminal-bench-2",
        "tasks": [task],
    }


def _gt_run(task_id: str, **overrides) -> dict:
    body = {
        "schema": "gt.run_receipt.v1",
        "task_id": task_id,
        "terminal": "submitted",
        "status": "COMPLETED",
        "research_valid": True,
        "provider_calls": 12,
        "provider_attempts": 12,
        "provider_completed_calls": 12,
        "provider_failed_calls": 0,
        "agent_turn_calls": 11,
        "input_tokens": 100_000,
        "output_tokens": 9_000,
    }
    body.update(overrides)
    return body


def _report(**overrides) -> dict:
    body = {
        "terminal": "submitted",
        "exit_code": 0,
        "exception": None,
        "patch_export_error": None,
        "submission_patch_state": {
            "layout": "gt.submission_patch_state.v1",
            "baseline": "b" * 40,
            "status": "observed",
            "committed_patch_bytes": 4_660,
            "committed_patch_empty": False,
        },
        "supervisor": {
            "schema": "gt.supervisor_result.v1",
            "child_returncode": 0,
            "reason": "exited",
        },
        "collected_patch_will_be_empty": False,
    }
    body.update(overrides)
    return body


def _by_id(checks: list[dict]) -> dict[str, dict]:
    return {check["check_id"]: check for check in checks}


def _severity(checks: list[dict], check_id: str) -> str:
    return _by_id(checks)[check_id]["severity"]


def _healthy_tree(root: Path, task_id: str = "extract-elf") -> Path:
    """A run where nothing contradicts anything: every check must pass."""
    task_dir = root / task_id
    _write(task_dir / "agent" / "gt-run.json", _gt_run(task_id))
    _write(task_dir / "agent" / "miniswe_report.json", _report())
    _write(task_dir / "progress" / "benchmark-progress.json", _progress(task_id))
    return task_dir


def _collected_patch(task_dir: Path, text: str = "diff --git a/x b/x\n") -> Path:
    """The patch Pier collected and handed the grader.

    M-2 (round 6): committed work with no readable submitted patch is UNKNOWN,
    not OK, so a fixture that means "this run shipped what it built" has to
    say so on disk. _healthy_tree deliberately does not write one - the tests
    that plant a predictions.jsonl need the patch file absent.
    """
    patch = task_dir / "artifacts" / "model.patch"
    patch.parent.mkdir(parents=True, exist_ok=True)
    patch.write_text(text, encoding="utf-8")
    return patch


def test_find_named_locates_receipts_at_any_depth(tmp_path):
    _healthy_tree(tmp_path)
    assert find_named(tmp_path, "gt-run.json") is not None
    assert find_named(tmp_path, "miniswe_report.json") is not None
    assert find_named(tmp_path, "nothing-here.json") is None


def test_healthy_run_passes_every_check_and_exits_zero(tmp_path, capsys):
    _collected_patch(_healthy_tree(tmp_path))
    exit_code = main([str(tmp_path), "--job-conclusion", "success"])
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["schema"] == "gt.receipt_consistency.v1"
    assert receipt["task_id"] == "extract-elf"
    assert receipt["contradictions"] == 0
    assert exit_code == 0
    severities = {check["severity"] for check in receipt["checks"]}
    assert severities == {OK}


# (a) Run 35280614124: the supervisor reported the child exited 0 while the
# report's own terminal said internal_error. A clean child exit cannot coexist
# with an internal error terminal; one of the two is lying.
def test_child_exit_zero_contradicts_internal_error_terminal(tmp_path):
    task_dir = _healthy_tree(tmp_path, "run-35280614124")
    _write(
        task_dir / "agent" / "miniswe_report.json",
        _report(terminal="internal_error", exit_code=5),
    )
    inputs = load_inputs(tmp_path)
    checks = run_checks(inputs)
    assert _severity(checks, "child_exit_vs_terminal") == CONTRADICTION
    assert "child_returncode" in _by_id(checks)["child_exit_vs_terminal"]["message"]


@pytest.mark.parametrize("terminal", ["internal_error", "provider_failed", "setup_error"])
def test_child_exit_zero_contradicts_each_failure_terminal(tmp_path, terminal):
    task_dir = _healthy_tree(tmp_path)
    _write(task_dir / "agent" / "miniswe_report.json", _report(terminal=terminal))
    checks = run_checks(load_inputs(tmp_path))
    assert _severity(checks, "child_exit_vs_terminal") == CONTRADICTION


def test_child_exit_nonzero_with_failure_terminal_is_consistent(tmp_path):
    task_dir = _healthy_tree(tmp_path)
    _write(
        task_dir / "agent" / "miniswe_report.json",
        _report(
            terminal="internal_error",
            supervisor={"child_returncode": 5, "reason": "exited"},
        ),
    )
    checks = run_checks(load_inputs(tmp_path))
    assert _severity(checks, "child_exit_vs_terminal") == OK


def test_missing_supervisor_block_is_unknown_not_a_pass(tmp_path):
    task_dir = _healthy_tree(tmp_path)
    report = _report(terminal="internal_error")
    report.pop("supervisor")
    _write(task_dir / "agent" / "miniswe_report.json", report)
    checks = run_checks(load_inputs(tmp_path))
    assert _severity(checks, "child_exit_vs_terminal") == UNKNOWN
    assert _severity(checks, "oom_signature") == UNKNOWN


def test_missing_report_file_makes_report_checks_unknown(tmp_path):
    task_dir = tmp_path / "t"
    _write(task_dir / "gt-run.json", _gt_run("t"))
    _write(task_dir / "benchmark-progress.json", _progress("t"))
    checks = run_checks(load_inputs(tmp_path))
    assert _severity(checks, "child_exit_vs_terminal") == UNKNOWN
    assert _severity(checks, "committed_work_vs_empty_submission") == UNKNOWN
    assert _severity(checks, "oom_signature") == UNKNOWN


# (b) Run 35256147148, task amoffat__sh-744: 4,660 bytes of committed work were
# observed in the workspace and the submission was still graded as empty.
def test_committed_bytes_contradict_collected_patch_will_be_empty(tmp_path):
    task_dir = _healthy_tree(tmp_path, "amoffat__sh-744")
    _write(
        task_dir / "agent" / "miniswe_report.json",
        _report(collected_patch_will_be_empty=True),
    )
    checks = run_checks(load_inputs(tmp_path))
    check = _by_id(checks)["committed_work_vs_empty_submission"]
    assert check["severity"] == CONTRADICTION
    assert "4,660" in check["message"] or "4660" in check["message"]


def test_committed_bytes_contradict_zero_byte_submission_graded_zero(tmp_path):
    """The graded side of 35256147148: reward 0, no error code, nothing submitted."""
    _healthy_tree(tmp_path, "amoffat__sh-744")
    inputs = load_inputs(tmp_path)
    checks = run_checks(inputs, submitted_patch_bytes=0)
    assert _severity(checks, "committed_work_vs_empty_submission") == CONTRADICTION


def test_zero_byte_submission_without_committed_work_is_consistent(tmp_path):
    task_dir = _healthy_tree(tmp_path)
    _write(
        task_dir / "agent" / "miniswe_report.json",
        _report(
            submission_patch_state={
                "layout": "gt.submission_patch_state.v1",
                "status": "observed",
                "committed_patch_bytes": 0,
                "committed_patch_empty": True,
            },
            collected_patch_will_be_empty=True,
        ),
    )
    checks = run_checks(load_inputs(tmp_path), submitted_patch_bytes=0)
    assert _severity(checks, "committed_work_vs_empty_submission") == OK


def test_unobserved_patch_state_is_unknown(tmp_path):
    task_dir = _healthy_tree(tmp_path)
    _write(
        task_dir / "agent" / "miniswe_report.json",
        _report(
            submission_patch_state={
                "layout": "gt.submission_patch_state.v1",
                "status": "unavailable",
            },
            collected_patch_will_be_empty=True,
        ),
    )
    checks = run_checks(load_inputs(tmp_path))
    assert _severity(checks, "committed_work_vs_empty_submission") == UNKNOWN


# (c) A run cannot be simultaneously a valid, completed research run and an
# infrastructure failure. Whichever receipt is right, the pair is unusable.
def test_completed_valid_run_contradicts_infrastructure_failed_state(tmp_path):
    task_dir = _healthy_tree(tmp_path)
    _write(
        task_dir / "progress" / "benchmark-progress.json",
        _progress(
            "extract-elf",
            state="infrastructure_failed",
            official_verifier=False,
            reward=None,
            error_code="harbor_trial_failed",
        ),
    )
    checks = run_checks(load_inputs(tmp_path))
    assert _severity(checks, "valid_run_vs_infra_state") == CONTRADICTION


def test_incomplete_run_with_infrastructure_failed_state_is_consistent(tmp_path):
    task_dir = _healthy_tree(tmp_path)
    _write(
        task_dir / "agent" / "gt-run.json",
        _gt_run("extract-elf", status="ERROR", research_valid=False),
    )
    _write(
        task_dir / "progress" / "benchmark-progress.json",
        _progress("extract-elf", state="infrastructure_failed", reward=None),
    )
    checks = run_checks(load_inputs(tmp_path))
    assert _severity(checks, "valid_run_vs_infra_state") == OK


def test_missing_progress_receipt_makes_progress_checks_unknown(tmp_path):
    task_dir = tmp_path / "t"
    _write(task_dir / "gt-run.json", _gt_run("t"))
    _write(task_dir / "miniswe_report.json", _report())
    checks = run_checks(load_inputs(tmp_path), job_conclusion="success")
    assert _severity(checks, "valid_run_vs_infra_state") == UNKNOWN
    assert _severity(checks, "green_job_zero_graded") == UNKNOWN


# (d) Run 35262214538: a git error was labelled provider_failed. Every provider
# call was completed and no provider failure was recorded, so the provider was
# never the thing that failed.
def test_provider_failed_without_any_provider_failure_is_a_contradiction(tmp_path):
    task_dir = _healthy_tree(tmp_path, "run-35262214538")
    _write(
        task_dir / "agent" / "gt-run.json",
        _gt_run(
            "run-35262214538",
            terminal="provider_failed",
            status="ERROR",
            research_valid=False,
            provider_calls=9,
            provider_attempts=9,
            provider_completed_calls=9,
            provider_failed_calls=0,
        ),
    )
    _write(
        task_dir / "agent" / "miniswe_report.json",
        _report(terminal="provider_failed", supervisor={"child_returncode": 4, "reason": "exited"}),
    )
    checks = run_checks(load_inputs(tmp_path))
    check = _by_id(checks)["provider_failed_without_provider_failures"]
    assert check["severity"] == CONTRADICTION
    assert "provider_failed_calls=0" in check["message"]


def test_provider_failed_with_recorded_failures_is_consistent(tmp_path):
    task_dir = _healthy_tree(tmp_path)
    _write(
        task_dir / "agent" / "gt-run.json",
        _gt_run(
            "extract-elf",
            terminal="provider_failed",
            status="ERROR",
            research_valid=False,
            provider_calls=9,
            provider_attempts=12,
            provider_completed_calls=6,
            provider_failed_calls=3,
        ),
    )
    checks = run_checks(load_inputs(tmp_path))
    assert _severity(checks, "provider_failed_without_provider_failures") == OK


def test_provider_failed_with_a_call_that_never_completed_is_consistent(tmp_path):
    """No failure was recorded, but a call that never came back is still a gap."""
    task_dir = _healthy_tree(tmp_path)
    _write(
        task_dir / "agent" / "gt-run.json",
        _gt_run(
            "extract-elf",
            terminal="provider_failed",
            status="ERROR",
            research_valid=False,
            provider_calls=9,
            provider_attempts=9,
            provider_completed_calls=8,
            provider_failed_calls=0,
        ),
    )
    checks = run_checks(load_inputs(tmp_path))
    assert _severity(checks, "provider_failed_without_provider_failures") == OK


def test_missing_provider_counters_are_unknown(tmp_path):
    task_dir = _healthy_tree(tmp_path)
    body = _gt_run("extract-elf", terminal="provider_failed")
    body.pop("provider_failed_calls")
    _write(task_dir / "agent" / "gt-run.json", body)
    checks = run_checks(load_inputs(tmp_path))
    assert _severity(checks, "provider_failed_without_provider_failures") == UNKNOWN


def test_the_provider_count_spellings_never_reach_this_check(tmp_path):
    """H-1: the keys the check used to read are the supervisor journal's.

    gt-run.json has never carried provider_failure_count, so a receipt that
    carries only those spellings has to read UNKNOWN - never OK, and never a
    contradiction invented out of a journal key that is not in this file.
    """
    task_dir = _healthy_tree(tmp_path)
    body = _gt_run("extract-elf", terminal="provider_failed")
    for key in (
        "provider_calls",
        "provider_attempts",
        "provider_completed_calls",
        "provider_failed_calls",
    ):
        body.pop(key)
    body.update(
        provider_request_count=9, provider_response_count=9, provider_failure_count=0
    )
    _write(task_dir / "agent" / "gt-run.json", body)
    checks = run_checks(load_inputs(tmp_path))
    assert _severity(checks, "provider_failed_without_provider_failures") == UNKNOWN


def test_the_gt_run_fixture_only_spells_keys_a_real_receipt_carries():
    """H-1: the fixture cannot drift back to keys no receipt ever wrote.

    gt-run.json is built by gt_harness/runtime_receipts.py. A fixture key in
    neither a recorded receipt nor that producer's source is invented, and a
    check written against an invented key is permanently UNKNOWN on every real
    run while every test of it passes.
    """
    assert RECORDED_RECEIPTS, "no recorded gt-run.json under tests/fixtures"
    allowed = _real_receipt_keys()

    assert set(_gt_run("extract-elf")) <= allowed

    # The guard has to bite: these three are the supervisor journal's
    # run_terminal event and appear in no receipt.
    assert not (
        {"provider_failure_count", "provider_request_count", "provider_response_count"}
        & allowed
    )
    # And the keys the check now reads are the producer's own.
    assert {
        "provider_calls",
        "provider_attempts",
        "provider_completed_calls",
        "provider_failed_calls",
    } <= allowed


def test_a_key_from_another_schema_in_the_producer_is_not_accepted():
    """M-5: the extraction is gt-run.json's dict, not every dict in the file.

    The module-wide ast.Dict walk accepted 130 keys, 111 of which appear in
    no recorded receipt, so a fixture could spell any name that occurs
    anywhere in the producer and still pass. These two are written by the
    same module into different schemas: ``product_command`` belongs to
    ``gt.benchmark_adapter_receipt.v1`` and ``sealed_limit`` to the
    treatment receipt's delivery-budget block. Neither is ever a key of
    gt-run.json, so neither may be admitted here.
    """
    producer_keys = _producer_receipt_keys()

    assert "product_command" not in producer_keys
    assert "sealed_limit" not in producer_keys
    assert "product_command" not in _real_receipt_keys()
    assert "sealed_limit" not in _real_receipt_keys()
    # The product receipt is a few dozen fields, not the file's whole
    # vocabulary; a set back in the hundreds means the bound was lost again.
    assert len(producer_keys) < 40, sorted(producer_keys)
    # It still has to carry what gt-run.json actually writes.
    assert {"schema", "task_id", "terminal", "status", "research_valid"} <= producer_keys


# (e) Harbor exits 0 on an errored trial, so a green job says nothing about
# whether a single task was officially graded.
def test_green_job_with_zero_graded_tasks_warns(tmp_path):
    task_dir = _healthy_tree(tmp_path)
    _write(
        task_dir / "progress" / "benchmark-progress.json",
        _progress(
            "extract-elf",
            state="infrastructure_failed",
            official_verifier=False,
            reward=None,
            error_code="harbor_trial_failed",
        ),
    )
    _write(
        task_dir / "agent" / "gt-run.json",
        _gt_run("extract-elf", status="ERROR", research_valid=False),
    )
    checks = run_checks(load_inputs(tmp_path), job_conclusion="success")
    assert _severity(checks, "green_job_zero_graded") == WARNING


def test_warning_alone_does_not_fail_the_exit_code(tmp_path, capsys):
    task_dir = _healthy_tree(tmp_path)
    _write(
        task_dir / "progress" / "benchmark-progress.json",
        _progress("extract-elf", state="infrastructure_failed", official_verifier=False, reward=None),
    )
    _write(
        task_dir / "agent" / "gt-run.json",
        _gt_run("extract-elf", status="ERROR", research_valid=False),
    )
    exit_code = main([str(tmp_path), "--job-conclusion", "success"])
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["contradictions"] == 0
    assert exit_code == 0


def test_failed_job_does_not_warn_about_zero_graded(tmp_path):
    _healthy_tree(tmp_path)
    checks = run_checks(load_inputs(tmp_path), job_conclusion="failure")
    assert _severity(checks, "green_job_zero_graded") == OK


def test_absent_job_conclusion_is_unknown_not_a_pass(tmp_path):
    _healthy_tree(tmp_path)
    checks = run_checks(load_inputs(tmp_path))
    assert _severity(checks, "green_job_zero_graded") == UNKNOWN


def test_explicit_officially_graded_counter_is_honoured(tmp_path):
    task_dir = _healthy_tree(tmp_path)
    progress = _progress("extract-elf")
    progress["officially_graded"] = 0
    _write(task_dir / "progress" / "benchmark-progress.json", progress)
    checks = run_checks(load_inputs(tmp_path), job_conclusion="success")
    assert _severity(checks, "green_job_zero_graded") == WARNING


# (f) Cohort 35298094010 lost write-compressor and sanitize-git-repo to the OOM
# killer during initial indexing. Neither is a model result.
def test_sigkill_child_returncode_reports_oom_signature(tmp_path):
    task_dir = _healthy_tree(tmp_path, "write-compressor")
    _write(
        task_dir / "agent" / "miniswe_report.json",
        _report(
            terminal="setup_error",
            supervisor={"child_returncode": -9, "reason": "exited"},
        ),
    )
    checks = run_checks(load_inputs(tmp_path))
    check = _by_id(checks)["oom_signature"]
    assert check["severity"] == INFO
    assert check["message"] == "oom_kill_during_index"


def test_initial_index_failed_reason_reports_oom_signature(tmp_path):
    task_dir = _healthy_tree(tmp_path, "sanitize-git-repo")
    _write(
        task_dir / "agent" / "miniswe_report.json",
        _report(
            terminal="setup_error",
            supervisor={"child_returncode": 6, "reason": "initial_index_failed:Killed"},
        ),
    )
    checks = run_checks(load_inputs(tmp_path))
    check = _by_id(checks)["oom_signature"]
    assert check["severity"] == INFO
    assert check["message"] == "oom_kill_during_index"


def test_info_severity_does_not_fail_the_exit_code(tmp_path, capsys):
    task_dir = _healthy_tree(tmp_path, "write-compressor")
    _write(
        task_dir / "agent" / "miniswe_report.json",
        _report(supervisor={"child_returncode": -9, "reason": "exited"}),
    )
    exit_code = main([str(tmp_path)])
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["contradictions"] == 0
    assert exit_code == 0


def test_contradiction_exits_one_and_counts_every_contradiction(tmp_path, capsys):
    """Run 35262214538 again, end to end, through the CLI."""
    task_dir = _healthy_tree(tmp_path, "run-35262214538")
    _write(
        task_dir / "agent" / "gt-run.json",
        _gt_run(
            "run-35262214538",
            terminal="provider_failed",
            provider_calls=9,
            provider_attempts=9,
            provider_completed_calls=9,
            provider_failed_calls=0,
        ),
    )
    _write(task_dir / "agent" / "miniswe_report.json", _report(terminal="provider_failed"))
    exit_code = main([str(tmp_path)])
    receipt = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    # child_exit_vs_terminal (0 vs provider_failed) and
    # provider_failed_without_provider_failures both fire on this one run.
    assert receipt["contradictions"] == 2
    fired = {c["check_id"] for c in receipt["checks"] if c["severity"] == CONTRADICTION}
    assert fired == {"child_exit_vs_terminal", "provider_failed_without_provider_failures"}


def test_json_flag_writes_the_receipt_to_a_file(tmp_path):
    _healthy_tree(tmp_path)
    out = tmp_path / "out" / "consistency.json"
    exit_code = main([str(tmp_path), "--json", str(out)])
    assert exit_code == 0
    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert receipt["schema"] == "gt.receipt_consistency.v1"
    assert len(receipt["checks"]) == 6


def test_every_named_check_is_always_reported(tmp_path):
    """An empty directory still yields all six checks, all UNKNOWN."""
    checks = run_checks(load_inputs(tmp_path))
    assert [check["check_id"] for check in checks] == [
        "child_exit_vs_terminal",
        "committed_work_vs_empty_submission",
        "valid_run_vs_infra_state",
        "provider_failed_without_provider_failures",
        "green_job_zero_graded",
        "oom_signature",
    ]
    assert {check["severity"] for check in checks} == {UNKNOWN}


def test_unreadable_json_that_is_not_a_run_receipt_is_unknown_not_a_crash(tmp_path):
    """Only the two run receipts are read strictly (round 8, N-1).

    Every other JSON under the harness subtrees is opened while looking for
    the progress receipt's schema, and the tree holds files this checker knows
    nothing about. One of them being unparseable says nothing about the run,
    so it degrades the checks that wanted it and takes nothing down.
    """
    task_dir = _healthy_tree(tmp_path, "extract-elf")
    (task_dir / "progress" / "benchmark-progress.json").write_text("{not json", encoding="utf-8")

    inputs = load_inputs(tmp_path)

    assert inputs.gt_run is not None
    assert inputs.progress is None
    checks = run_checks(inputs)
    assert _severity(checks, "valid_run_vs_infra_state") == UNKNOWN


def test_build_receipt_falls_back_to_the_directory_name_for_task_id(tmp_path):
    task_dir = tmp_path / "amoffat__sh-744"
    _write(task_dir / "miniswe_report.json", _report())
    inputs = load_inputs(task_dir)
    receipt = build_receipt(inputs, run_checks(inputs))
    assert receipt["task_id"] == "amoffat__sh-744"


# --- the submitted patch size, derived from the artifact ---------------------
# Nothing in CI passes --submitted-patch-bytes, so the second half of the
# 35256147148 check (committed work graded as an empty submission) could never
# fire as shipped. The size has to come off the artifact itself.


def _grade_as_empty(task_dir: Path) -> None:
    """Make the progress receipt say what 35256147148 said: reward 0, no error."""
    _write(
        task_dir / "progress" / "benchmark-progress.json",
        _progress(task_dir.name, state="verifier_failed", reward=0, error_code=""),
    )


def test_empty_model_patch_artifact_supplies_the_submitted_size(tmp_path):
    """artifacts/model.patch is what Pier collects and hands the grader."""
    task_dir = _healthy_tree(tmp_path, "amoffat__sh-744")
    _grade_as_empty(task_dir)
    (task_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    (task_dir / "artifacts" / "model.patch").write_text("", encoding="utf-8")

    check = _by_id(run_checks(load_inputs(tmp_path)))["committed_work_vs_empty_submission"]

    assert check["severity"] == CONTRADICTION
    assert "model.patch" in check["message"]


def test_nonempty_model_patch_artifact_is_not_an_empty_submission(tmp_path):
    task_dir = _healthy_tree(tmp_path, "amoffat__sh-744")
    _grade_as_empty(task_dir)
    (task_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    (task_dir / "artifacts" / "model.patch").write_text(
        "diff --git a/sh.py b/sh.py\n", encoding="utf-8"
    )

    checks = run_checks(load_inputs(tmp_path))

    assert _severity(checks, "committed_work_vs_empty_submission") == OK


def test_predictions_jsonl_supplies_the_submitted_size_when_no_patch_file_exists(tmp_path):
    task_dir = _healthy_tree(tmp_path, "amoffat__sh-744")
    _grade_as_empty(task_dir)
    predictions = task_dir / "official-evaluator" / "predictions.jsonl"
    predictions.parent.mkdir(parents=True, exist_ok=True)
    predictions.write_text(
        json.dumps({"instance_id": "amoffat__sh-744", "model_patch": ""}) + "\n",
        encoding="utf-8",
    )

    check = _by_id(run_checks(load_inputs(tmp_path)))["committed_work_vs_empty_submission"]

    assert check["severity"] == CONTRADICTION
    assert "predictions.jsonl" in check["message"]


def test_predictions_jsonl_row_is_matched_on_the_task_id(tmp_path):
    """A merged predictions file carries every task; only this task's row counts."""
    task_dir = _healthy_tree(tmp_path, "amoffat__sh-744")
    _grade_as_empty(task_dir)
    predictions = task_dir / "official-evaluator" / "predictions.jsonl"
    predictions.parent.mkdir(parents=True, exist_ok=True)
    predictions.write_text(
        "\n".join(
            json.dumps(row)
            for row in (
                {"instance_id": "other__task-1", "model_patch": ""},
                {"instance_id": "amoffat__sh-744", "model_patch": "diff --git a/sh.py b/sh.py\n"},
            )
        )
        + "\n",
        encoding="utf-8",
    )

    checks = run_checks(load_inputs(tmp_path))

    assert _severity(checks, "committed_work_vs_empty_submission") == OK


def test_the_patch_file_wins_over_predictions_jsonl(tmp_path):
    """Pier's collection is the thing that shipped; predictions is a copy of it."""
    task_dir = _healthy_tree(tmp_path, "amoffat__sh-744")
    _grade_as_empty(task_dir)
    (task_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    (task_dir / "artifacts" / "model.patch").write_text("", encoding="utf-8")
    predictions = task_dir / "official-evaluator" / "predictions.jsonl"
    predictions.parent.mkdir(parents=True, exist_ok=True)
    predictions.write_text(
        json.dumps({"instance_id": "amoffat__sh-744", "model_patch": "diff --git x\n"}) + "\n",
        encoding="utf-8",
    )

    check = _by_id(run_checks(load_inputs(tmp_path)))["committed_work_vs_empty_submission"]

    assert check["severity"] == CONTRADICTION
    assert "model.patch" in check["message"]


def test_the_flag_still_overrides_the_artifact(tmp_path):
    task_dir = _healthy_tree(tmp_path, "amoffat__sh-744")
    _grade_as_empty(task_dir)
    (task_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    (task_dir / "artifacts" / "model.patch").write_text("diff --git x\n", encoding="utf-8")

    checks = run_checks(load_inputs(tmp_path), submitted_patch_bytes=0)

    assert _severity(checks, "committed_work_vs_empty_submission") == CONTRADICTION


def test_no_patch_artifact_at_all_does_not_invent_an_empty_submission(tmp_path):
    """Absence of the patch is absence of evidence, not a 0-byte submission.

    M-2 (round 6): it is not a pass either. Committed work was observed and
    nothing readable says what shipped, so the only honest verdict is UNKNOWN,
    which is this module's own contract. Pinning OK here made the one path a
    latin-1 predictions.jsonl actually lands on read as a clean run.
    """
    task_dir = _healthy_tree(tmp_path, "amoffat__sh-744")
    _grade_as_empty(task_dir)

    inputs = load_inputs(tmp_path)
    check = _by_id(run_checks(inputs))["committed_work_vs_empty_submission"]

    assert inputs.submitted_patch_bytes is None
    assert check["severity"] == UNKNOWN
    assert "unavailable" in check["message"]


def test_an_empty_collected_patch_contradicts_committed_work_with_no_grading_row(tmp_path):
    """The two receipts disagree by themselves: N bytes committed, 0 shipped.

    The graded side (reward 0, no error_code) is what run 35256147148 also
    recorded, but it is not what makes this a contradiction: the workspace
    receipt and the collected patch already disagree, and a task nothing
    graded is not thereby explained.
    """
    task_dir = _healthy_tree(tmp_path, "amoffat__sh-744")
    (task_dir / "progress" / "benchmark-progress.json").unlink()
    _collected_patch(task_dir, "")

    inputs = load_inputs(tmp_path)
    check = _by_id(run_checks(inputs))["committed_work_vs_empty_submission"]

    assert inputs.progress is None
    assert inputs.submitted_patch_bytes == 0
    assert check["severity"] == CONTRADICTION
    assert "model.patch" in check["message"]


def test_the_workflow_cli_contract_reports_the_shipped_defect(tmp_path):
    """Exactly the invocation the workflow step makes, end to end."""
    task_dir = _healthy_tree(tmp_path, "amoffat__sh-744")
    _grade_as_empty(task_dir)
    (task_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    (task_dir / "artifacts" / "model.patch").write_text("", encoding="utf-8")
    out = tmp_path / "receipts" / "consistency.json"

    exit_code = main([str(task_dir), "--job-conclusion", "success", "--json", str(out)])

    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert exit_code == 1
    assert receipt["contradictions"] == 1
    fired = {c["check_id"] for c in receipt["checks"] if c["severity"] == CONTRADICTION}
    assert fired == {"committed_work_vs_empty_submission"}


# --- the search is bounded to the harness's own subtrees ---------------------
# A TB2 task directory contains the task's whole repository checkout. Walking
# it per task is slow, and worse, a look-alike receipt inside it would be read
# as this run's own.


def _decoy_checkout(task_dir: Path) -> Path:
    """A repo checkout under the task dir carrying look-alike receipts.

    Both a dotted virtualenv and a plain source tree, because a whole-tree
    walk visits them in name order and ``.venv`` sorts ahead of ``agent`` -
    the harness's own receipts would lose the race.
    """
    for decoy in (
        task_dir / ".venv" / "lib" / "site-packages" / "harness",
        task_dir / "repo" / "tests" / "fixtures" / "nested",
    ):
        _write(decoy / "gt-run.json", _gt_run("decoy", terminal="provider_failed"))
        _write(decoy / "miniswe_report.json", _report(terminal="internal_error"))
        _write(
            decoy / "benchmark-progress.json",
            _progress("decoy", state="infrastructure_failed", official_verifier=False, reward=None),
        )
    return decoy


def test_receipts_inside_a_repo_checkout_are_never_read(tmp_path, monkeypatch):
    import scripts.verify_run_receipts as module

    task_dir = _healthy_tree(tmp_path, "extract-elf")
    _decoy_checkout(task_dir)

    opened: list[Path] = []
    real_read = module._read_json

    def _recording_read(path):
        if path is not None:
            opened.append(Path(path))
        return real_read(path)

    monkeypatch.setattr(module, "_read_json", _recording_read)
    inputs = module.load_inputs(tmp_path)
    checks = module.run_checks(inputs)

    checkout = {"repo", ".venv"}
    assert not [path for path in opened if checkout & set(path.parts)], opened
    assert inputs.task_id == "extract-elf"
    assert {check["severity"] for check in checks} == {OK, UNKNOWN}


def test_find_named_ignores_a_look_alike_inside_a_repo_checkout(tmp_path):
    task_dir = tmp_path / "extract-elf"
    _decoy_checkout(task_dir)

    assert find_named(tmp_path, "gt-run.json") is None
    assert find_named(tmp_path, "miniswe_report.json") is None


def test_receipts_in_the_harness_subtrees_are_still_found(tmp_path):
    """The bound must not cost us the layouts the workflows actually produce."""
    task_dir = tmp_path / "extract-elf"
    _write(task_dir / "artifacts" / "gt-run.json", _gt_run("extract-elf"))
    _write(task_dir / "miniswe_report.json", _report())
    _write(
        task_dir / "agent" / "gt-state" / "extract-elf" / "progress.json",
        _progress("extract-elf"),
    )

    inputs = load_inputs(task_dir)

    assert inputs.gt_run is not None
    assert inputs.report is not None
    assert inputs.progress is not None
# --- Pier's own layout: <job-name>/<task>__<hash>/agent/ ---------------------
# The workflow step pointed the check at `results/terminal-bench`, two levels
# above where Pier writes its receipts, while the search reached the root's
# direct children only. Five of six checks reported UNKNOWN, the task_id
# degraded to the artifact root's name ("terminal-bench"), and the step could
# never redden a job however loudly the receipts contradicted each other.


def _pier_tree(
    root: Path,
    task_id: str = "extract-elf",
    job: str = "tb2-gt-smoke20-921bec20-42-extract-elf",
    digest: str = "9f3c1a2b",
) -> Path:
    """Exactly what Pier writes: <root>/<job>/<task>__<hash>/agent/."""
    trial = root / job / f"{task_id}__{digest}"
    _write(trial / "agent" / "gt-run.json", _gt_run(task_id))
    _write(trial / "agent" / "miniswe_report.json", _report())
    # The workflow copies the progress receipt into the tree it hands over.
    _write(root / job / "benchmark-progress.json", _progress(task_id))
    return trial


def test_pier_trial_two_levels_below_the_artifact_root_is_read(tmp_path):
    _collected_patch(_pier_tree(tmp_path))

    inputs = load_inputs(tmp_path)

    assert inputs.gt_run is not None
    assert inputs.report is not None
    assert inputs.progress is not None
    assert inputs.task_id == "extract-elf"
    severities = {c["severity"] for c in run_checks(inputs, job_conclusion="success")}
    assert severities == {OK}


def test_pier_trial_one_level_below_the_job_directory_is_read(tmp_path):
    """The same check pointed at the job dir, which is the workflow's target."""
    trial = _pier_tree(tmp_path)

    inputs = load_inputs(trial.parent)

    assert inputs.trial == trial
    assert inputs.gt_run is not None
    assert inputs.progress is not None
    assert inputs.task_id == "extract-elf"


def test_task_id_comes_from_the_trial_dir_not_the_artifact_root(tmp_path):
    """With no receipt declaring one, the trial dir names the task."""
    root = tmp_path / "terminal-bench"
    trial = root / "job-1" / "extract-elf__9f3c1a2b"
    _write(trial / "agent" / "miniswe_report.json", _report())

    inputs = load_inputs(root)
    receipt = build_receipt(inputs, run_checks(inputs))

    assert receipt["task_id"] == "extract-elf"


def test_a_swebench_instance_id_keeps_its_own_double_underscore(tmp_path):
    """Only the LAST __ separates the hash; the instance id stays whole."""
    trial = tmp_path / "job-1" / "amoffat__sh-744__9f3c1a2b"
    _write(trial / "agent" / "miniswe_report.json", _report())

    assert load_inputs(tmp_path).task_id == "amoffat__sh-744"


def test_two_trials_under_one_root_are_refused_and_named(tmp_path):
    """Two trials read as one task would report the first file's story."""
    _pier_tree(tmp_path, "extract-elf")
    _pier_tree(tmp_path, "write-compressor", job="tb2-gt-smoke20-921bec20-42-wc")

    with pytest.raises(AmbiguousTrialError) as raised:
        load_inputs(tmp_path)

    message = str(raised.value)
    assert "extract-elf__9f3c1a2b" in message
    assert "write-compressor__9f3c1a2b" in message


def test_an_ambiguous_root_exits_nonzero_instead_of_reporting_one_task(tmp_path, capsys):
    _pier_tree(tmp_path, "extract-elf")
    _pier_tree(tmp_path, "write-compressor", job="tb2-gt-smoke20-921bec20-42-wc")

    exit_code = main([str(tmp_path), "--job-conclusion", "success"])

    assert exit_code == 2
    assert "::error title=Ambiguous trial::" in capsys.readouterr().err


def test_a_contradiction_inside_a_pier_trial_exits_one(tmp_path):
    trial = _pier_tree(tmp_path, "run-35262214538")
    _write(
        trial / "agent" / "gt-run.json",
        _gt_run(
            "run-35262214538",
            terminal="provider_failed",
            provider_calls=12,
            provider_attempts=12,
            provider_completed_calls=12,
            provider_failed_calls=0,
        ),
    )
    out = tmp_path / "receipt-consistency.json"

    exit_code = main([str(tmp_path), "--job-conclusion", "success", "--json", str(out)])

    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert exit_code == 1
    assert receipt["task_id"] == "run-35262214538"
    assert receipt["contradictions"] == 1


def test_the_submitted_patch_is_found_inside_the_pier_trial(tmp_path):
    trial = _pier_tree(tmp_path, "amoffat__sh-744")
    _write(
        trial.parent / "benchmark-progress.json",
        _progress("amoffat__sh-744", state="verifier_failed", reward=0, error_code=""),
    )
    (trial / "artifacts").mkdir(parents=True, exist_ok=True)
    (trial / "artifacts" / "model.patch").write_text("", encoding="utf-8")

    check = _by_id(run_checks(load_inputs(tmp_path)))["committed_work_vs_empty_submission"]

    assert check["severity"] == CONTRADICTION
    assert "model.patch" in check["message"]


# --- a predictions row belongs to the task it names --------------------------
# A single-row predictions.jsonl was taken as this task's whatever instance it
# named, so a neighbour's empty patch could be read as this task's empty
# submission - the very contradiction the check exists to find, invented.


def test_a_lone_predictions_row_naming_another_task_is_not_ours(tmp_path):
    """Another task's row is no evidence about this one, so nothing is known."""
    task_dir = _healthy_tree(tmp_path, "amoffat__sh-744")
    _grade_as_empty(task_dir)
    predictions = task_dir / "official-evaluator" / "predictions.jsonl"
    predictions.parent.mkdir(parents=True, exist_ok=True)
    predictions.write_text(
        json.dumps({"instance_id": "other__task-1", "model_patch": ""}) + "\n",
        encoding="utf-8",
    )

    checks = run_checks(load_inputs(tmp_path))

    assert _severity(checks, "committed_work_vs_empty_submission") == UNKNOWN


def test_a_lone_predictions_row_naming_nobody_is_taken_as_ours(tmp_path):
    """Only a row that names no instance falls back to being this task's."""
    task_dir = _healthy_tree(tmp_path, "amoffat__sh-744")
    _grade_as_empty(task_dir)
    predictions = task_dir / "official-evaluator" / "predictions.jsonl"
    predictions.parent.mkdir(parents=True, exist_ok=True)
    predictions.write_text(json.dumps({"model_patch": ""}) + "\n", encoding="utf-8")

    check = _by_id(run_checks(load_inputs(tmp_path)))["committed_work_vs_empty_submission"]

    assert check["severity"] == CONTRADICTION
    assert "predictions.jsonl" in check["message"]


# --- a checkout directory is never a second trial ----------------------------
# M-3: the trial globs were ("*__*", "*/*__*"), and the second one reaches one
# level INSIDE a resolved trial - into the task's own repository checkout. A
# checkout directory whose name happens to carry "__" and to own an "agent"
# directory made find_trials return two, which raised AmbiguousTrialError, exit
# 2 and a red job for a directory name.


def test_a_checkout_directory_inside_the_trial_is_not_a_second_trial(tmp_path):
    """The job directory is what the workflow passes; resolve one trial there."""
    trial = _pier_tree(tmp_path)
    job_dir = trial.parent
    (trial / "sub__x" / "agent").mkdir(parents=True)

    assert find_trials(job_dir) == [trial]
    assert load_inputs(job_dir).trial == trial


def test_a_checkout_directory_inside_the_trial_does_not_redden_the_job(tmp_path):
    trial = _pier_tree(tmp_path)
    (trial / "vendor__pkg" / "agent").mkdir(parents=True)
    out = tmp_path / "receipt-consistency.json"

    exit_code = main([str(trial.parent), "--job-conclusion", "success", "--json", str(out)])

    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert receipt["task_id"] == "extract-elf"
    assert receipt["resolution_error"] is None


def test_a_candidate_whose_parent_is_a_trial_directory_is_never_a_trial(tmp_path):
    """Below a trial - a directory that OWNS an agent/ - is the checkout.

    H-1 (round 6) narrowed this from the parent's NAME to the parent being a
    trial. A parent named with a "__" that owns no agent/ is not a trial and
    never was: Pier names its job directory after the task, and every
    SWE-bench instance id carries a "__", so the name rule rejected every
    real trial under a swelive job directory. What the rule is really for is
    the checkout INSIDE a resolved trial, which is what this plants.
    """
    trial = tmp_path / "amoffat__sh-744__9f3c1a2b"
    (trial / "agent").mkdir(parents=True)
    (trial / "vendor__pkg" / "agent").mkdir(parents=True)

    assert find_trials(tmp_path) == [trial]
    assert find_trials(trial) == []


def test_a_checkout_inside_the_trial_the_check_is_pointed_at_is_not_a_trial(tmp_path):
    """Pointed straight at the trial, its checkout is below it, not beside it."""
    trial = _pier_tree(tmp_path)
    (trial / "sub__x" / "agent").mkdir(parents=True)

    assert find_trials(trial) == []
    inputs = load_inputs(trial)
    assert inputs.gt_run is not None
    assert inputs.task_id == "extract-elf"


def test_an_artifact_root_named_like_an_instance_still_resolves_its_trial(tmp_path):
    """A download directory may carry a `__` of its own; only a trial owns agent/."""
    root = tmp_path / "tb2-gt-smoke20-42-task-amoffat__sh-744"
    trial = root / "amoffat__sh-744__9f3c1a2b"
    _write(trial / "agent" / "gt-run.json", _gt_run("amoffat__sh-744"))

    assert find_trials(root) == [trial]
    assert load_inputs(root).task_id == "amoffat__sh-744"


def test_two_real_trials_are_still_refused_when_one_holds_a_checkout(tmp_path):
    """The ambiguity guard must survive the fix that stops it over-firing."""
    first = _pier_tree(tmp_path, "extract-elf")
    _pier_tree(tmp_path, "write-compressor", job="tb2-gt-smoke20-921bec20-42-wc")
    (first / "sub__x" / "agent").mkdir(parents=True)

    with pytest.raises(AmbiguousTrialError):
        load_inputs(tmp_path)


# --- a refusal still writes the receipt it points readers to -----------------
# L-1/L-2: main returned 2 before writing --json, while the workflow's ::error
# told the reader to see receipt-consistency.json - a file that was never
# written. And a root with no trial and no receipt at all emitted a receipt of
# six UNKNOWNs labelled with the artifact root's name ("terminal-bench"),
# which reads as a task that was checked.


def _check_ids(receipt: dict) -> list[str]:
    return [check["check_id"] for check in receipt["checks"]]


def test_an_ambiguous_root_still_writes_the_json_receipt(tmp_path, capsys):
    _pier_tree(tmp_path, "extract-elf")
    _pier_tree(tmp_path, "write-compressor", job="tb2-gt-smoke20-921bec20-42-wc")
    out = tmp_path / "receipt-consistency.json"

    exit_code = main([str(tmp_path), "--job-conclusion", "success", "--json", str(out)])

    assert exit_code == 2
    assert "::error title=Ambiguous trial::" in capsys.readouterr().err
    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert receipt["schema"] == "gt.receipt_consistency.v1"
    assert receipt["resolution_error"] == "ambiguous_trial"
    assert receipt["task_id"] is None
    assert receipt["contradictions"] == 0
    assert len(receipt["checks"]) == 6
    assert {check["severity"] for check in receipt["checks"]} == {UNKNOWN}
    assert "extract-elf__9f3c1a2b" in receipt["resolution_detail"]


def test_an_ambiguous_root_without_json_prints_the_receipt(tmp_path, capsys):
    _pier_tree(tmp_path, "extract-elf")
    _pier_tree(tmp_path, "write-compressor", job="tb2-gt-smoke20-921bec20-42-wc")

    exit_code = main([str(tmp_path)])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert json.loads(captured.out)["resolution_error"] == "ambiguous_trial"
    assert "::error title=Ambiguous trial::" in captured.err


def test_no_trial_and_no_receipts_exits_two_instead_of_naming_the_root(tmp_path, capsys):
    """Pointed two levels above the receipts, this reported task "terminal-bench"."""
    root = tmp_path / "results" / "terminal-bench"
    root.mkdir(parents=True)
    out = tmp_path / "receipt-consistency.json"

    exit_code = main([str(root), "--job-conclusion", "success", "--json", str(out)])

    assert exit_code == 2
    assert "::error title=Unresolved receipts::" in capsys.readouterr().err
    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert receipt["resolution_error"] == "no_trial_found"
    assert receipt["task_id"] is None
    assert receipt["task_id"] != "terminal-bench"
    assert _check_ids(receipt) == [
        "child_exit_vs_terminal",
        "committed_work_vs_empty_submission",
        "valid_run_vs_infra_state",
        "provider_failed_without_provider_failures",
        "green_job_zero_graded",
        "oom_signature",
    ]
    assert {check["severity"] for check in receipt["checks"]} == {UNKNOWN}


def test_a_flat_layout_with_receipts_and_no_trial_dir_still_reports(tmp_path):
    """No trial directory is only unresolved when no receipt was read either."""
    _healthy_tree(tmp_path)
    out = tmp_path / "receipt-consistency.json"

    exit_code = main([str(tmp_path), "--job-conclusion", "success", "--json", str(out)])

    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert receipt["resolution_error"] is None
    assert receipt["task_id"] == "extract-elf"


# --- a receipt that cannot be decoded is never a crash -----------------------
# H-1 (round 5): _predictions_patch_bytes caught only OSError around
# read_text(encoding="utf-8"), and UnicodeDecodeError is a ValueError. A
# model_patch that diffed a latin-1 file therefore took main() down with a
# traceback: exit 1 and NO receipt on disk, while the workflow's rc -eq 1
# branch printed "Receipt contradiction ... see receipt-consistency.json"
# about a file that was never written. Two guards, because one is not enough:
# the read site itself, and a catch-all in main so that rc=1 means a
# contradiction between receipts and nothing else ever.


def _latin1_predictions(task_dir: Path, task_id: str) -> Path:
    """A predictions row whose model_patch diffs a latin-1 encoded file."""
    predictions = task_dir / "official-evaluator" / "predictions.jsonl"
    predictions.parent.mkdir(parents=True, exist_ok=True)
    predictions.write_bytes(
        b'{"instance_id": "' + task_id.encode() + b'", "model_patch": "caf\xe9"}\n'
    )
    return predictions


def test_a_latin1_predictions_file_is_unreadable_evidence_not_a_crash(tmp_path):
    task_dir = _healthy_tree(tmp_path, "amoffat__sh-744")
    _grade_as_empty(task_dir)
    _latin1_predictions(task_dir, "amoffat__sh-744")

    inputs = load_inputs(tmp_path)

    # Undecodable is unread, and an unread patch is not a 0-byte submission -
    # nor is it a clean one (M-2): committed work with nothing readable to
    # weigh it against is UNKNOWN.
    assert inputs.submitted_patch_bytes is None
    assert _severity(run_checks(inputs), "committed_work_vs_empty_submission") == UNKNOWN


def test_a_latin1_predictions_file_still_leaves_a_receipt_and_exits_zero(tmp_path):
    task_dir = _healthy_tree(tmp_path, "amoffat__sh-744")
    _grade_as_empty(task_dir)
    _latin1_predictions(task_dir, "amoffat__sh-744")
    out = tmp_path / "receipt-consistency.json"

    exit_code = main([str(tmp_path), "--job-conclusion", "success", "--json", str(out)])

    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert receipt["resolution_error"] is None
    assert receipt["task_id"] == "amoffat__sh-744"


def test_an_undecodable_read_below_main_writes_a_read_error_receipt(
    tmp_path, monkeypatch, capsys
):
    """The catch-all, proved by removing the guard above it.

    The point is not this one read site: it is that NO unhandled error under
    load_inputs or run_checks can reach the workflow as exit 1 with nothing
    on disk, because exit 1 is the workflow's "the receipts contradict each
    other" branch and it names a file the reader is told to open.
    """
    import scripts.verify_run_receipts as module

    task_dir = _healthy_tree(tmp_path, "amoffat__sh-744")
    _grade_as_empty(task_dir)
    _latin1_predictions(task_dir, "amoffat__sh-744")

    def _unguarded(path, task_id):
        return len(path.read_text(encoding="utf-8"))

    monkeypatch.setattr(module, "_predictions_patch_bytes", _unguarded)
    out = tmp_path / "receipt-consistency.json"

    exit_code = module.main(
        [str(tmp_path), "--job-conclusion", "success", "--json", str(out)]
    )

    assert exit_code == 2
    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert receipt["schema"] == "gt.receipt_consistency.v1"
    assert receipt["resolution_error"] == "read_error"
    assert "UnicodeDecodeError" in receipt["resolution_detail"]
    assert receipt["task_id"] is None
    assert receipt["contradictions"] == 0
    assert _check_ids(receipt) == [
        "child_exit_vs_terminal",
        "committed_work_vs_empty_submission",
        "valid_run_vs_infra_state",
        "provider_failed_without_provider_failures",
        "green_job_zero_graded",
        "oom_signature",
    ]
    assert {check["severity"] for check in receipt["checks"]} == {UNKNOWN}
    assert "::error title=Unresolved receipts::" in capsys.readouterr().err


def test_a_failure_inside_one_check_does_not_erase_the_others(tmp_path, monkeypatch):
    """H-2 (round 6): a check that raises is one UNKNOWN, not a blank receipt.

    ``_int`` is reached only by a check that found a value to read, so this
    plants a failure that fires on real receipts and on nothing else. Before
    the per-check guard the whole run collapsed into the refusal receipt -
    six UNKNOWNs, exit 2 - and the contradiction the remaining checks had
    already found was erased. valid_run_vs_infra_state reads no number, so it
    is the check that survives and it must still redden the job.
    """
    import scripts.verify_run_receipts as module

    task_dir = _healthy_tree(tmp_path)
    _write(
        task_dir / "progress" / "benchmark-progress.json",
        _progress("extract-elf", state="infrastructure_failed", reward=None),
    )

    def _boom(*_args, **_kwargs):
        raise RuntimeError("check exploded")

    monkeypatch.setattr(module, "_int", _boom)
    out = tmp_path / "receipt-consistency.json"

    exit_code = module.main([str(tmp_path), "--json", str(out)])

    receipt = json.loads(out.read_text(encoding="utf-8"))
    checks = _by_id(receipt["checks"])
    assert exit_code == 1
    assert receipt["resolution_error"] is None
    assert receipt["task_id"] == "extract-elf"
    assert receipt["contradictions"] == 1
    assert checks["valid_run_vs_infra_state"]["severity"] == CONTRADICTION
    # The checks that did touch the failing helper say so, one by one.
    broken = checks["child_exit_vs_terminal"]
    assert broken["severity"] == UNKNOWN
    assert "error: RuntimeError: check exploded" in broken["message"]
    assert _check_ids(receipt) == list(CHECK_IDS)


def test_a_genuine_contradiction_still_exits_one_after_the_catch_all(tmp_path):
    """rc=1 is a contradiction, and only ever that."""
    task_dir = _healthy_tree(tmp_path, "run-35262214538")
    _write(
        task_dir / "agent" / "miniswe_report.json",
        _report(terminal="internal_error"),
    )
    out = tmp_path / "receipt-consistency.json"

    exit_code = main([str(tmp_path), "--job-conclusion", "success", "--json", str(out)])

    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert exit_code == 1
    assert receipt["resolution_error"] is None
    assert receipt["contradictions"] == 1


# --- pointed AT a trial, its checkout is not a search root -------------------
# H-2 (round 5): _trial_roots added every direct child of root as a glob root
# unconditionally. Pointing the CLI at one trial directory is a documented
# mode, and there every child other than agent/, artifacts/,
# official-evaluator/ and progress/ is the task's own repository checkout. A
# look-alike at <trial>/checkout/agent/ was therefore read as this run's
# receipts: four OK verdicts under another task's id, and exit 0.


def _trial_with_a_look_alike_checkout(
    root: Path, task_id: str = "extract-elf", decoy: str = "other__task-1"
) -> Path:
    """A real trial whose own receipts are gone, with a checkout that has some."""
    trial = root / f"{task_id}__9f3c1a2b"
    (trial / "agent").mkdir(parents=True)
    checkout = trial / "checkout"
    _write(checkout / "agent" / "gt-run.json", _gt_run(decoy))
    _write(checkout / "agent" / "miniswe_report.json", _report())
    _write(checkout / "progress" / "benchmark-progress.json", _progress(decoy))
    return trial


def test_a_checkout_under_the_trial_is_never_read_as_this_runs_receipts(
    tmp_path, capsys
):
    trial = _trial_with_a_look_alike_checkout(tmp_path)
    out = tmp_path / "receipt-consistency.json"

    exit_code = main([str(trial), "--job-conclusion", "success", "--json", str(out)])

    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert exit_code == 2
    # N-2 (round 8): the refusal used to be no_trial_found here, because
    # find_trials looks BELOW the root and this root is the trial. Nothing
    # about the checkout changed - it is still never read - but the reader is
    # now told the trial wrote no receipt rather than that the path is wrong.
    assert receipt["resolution_error"] == "no_run_receipt"
    assert receipt["task_id"] is None
    assert {check["severity"] for check in receipt["checks"]} == {UNKNOWN}
    assert OK not in {check["severity"] for check in receipt["checks"]}
    # The decoy's task id never reaches the receipt or the annotation.
    assert "other__task-1" not in json.dumps(receipt)
    assert "::error title=Unresolved receipts::" in capsys.readouterr().err


def test_no_json_inside_the_trials_checkout_is_ever_opened(tmp_path, monkeypatch):
    """Every _read_json call is recorded; none of them may be in the checkout."""
    import scripts.verify_run_receipts as module

    trial = _trial_with_a_look_alike_checkout(tmp_path)
    opened: list[Path] = []
    real_read = module._read_json

    def _recording_read(path):
        if path is not None:
            opened.append(Path(path))
        return real_read(path)

    monkeypatch.setattr(module, "_read_json", _recording_read)
    inputs = module.load_inputs(trial)

    assert not [path for path in opened if "checkout" in path.parts], opened
    assert inputs.gt_run is None
    assert inputs.report is None
    assert inputs.progress is None
    assert inputs.submitted_patch_bytes is None


def test_a_trials_own_receipts_win_over_a_look_alike_in_its_checkout(tmp_path):
    """The bound must not cost the trial its own harness subtrees."""
    trial = tmp_path / "extract-elf__9f3c1a2b"
    _write(trial / "agent" / "gt-run.json", _gt_run("extract-elf"))
    _write(trial / "agent" / "miniswe_report.json", _report())
    _write(trial / "progress" / "benchmark-progress.json", _progress("extract-elf"))
    _write(
        trial / "checkout" / "agent" / "gt-run.json",
        _gt_run("other__task-1", terminal="provider_failed"),
    )
    _collected_patch(trial)

    inputs = load_inputs(trial)

    assert inputs.task_id == "extract-elf"
    severities = {c["severity"] for c in run_checks(inputs, job_conclusion="success")}
    assert severities == {OK}


def test_the_job_directory_layout_still_resolves_under_the_checkout_bound(tmp_path):
    trial = _pier_tree(tmp_path)
    _collected_patch(trial)

    inputs = load_inputs(trial.parent)

    assert inputs.trial == trial
    assert inputs.gt_run is not None
    assert inputs.report is not None
    assert inputs.progress is not None
    severities = {c["severity"] for c in run_checks(inputs, job_conclusion="success")}
    assert severities == {OK}


def test_the_flat_task_layout_still_resolves_under_the_checkout_bound(tmp_path):
    _collected_patch(_healthy_tree(tmp_path))

    inputs = load_inputs(tmp_path)

    assert inputs.task_id == "extract-elf"
    severities = {c["severity"] for c in run_checks(inputs, job_conclusion="success")}
    assert severities == {OK}


def test_the_submitted_patch_is_not_taken_from_a_checkout_under_the_trial(tmp_path):
    """model.patch inside the checkout is another project's file, not ours."""
    trial = tmp_path / "amoffat__sh-744__9f3c1a2b"
    _write(trial / "agent" / "gt-run.json", _gt_run("amoffat__sh-744"))
    _write(trial / "agent" / "miniswe_report.json", _report())
    _write(
        trial / "progress" / "benchmark-progress.json",
        _progress("amoffat__sh-744", state="verifier_failed", reward=0, error_code=""),
    )
    (trial / "checkout" / "artifacts").mkdir(parents=True)
    (trial / "checkout" / "artifacts" / "model.patch").write_text("", encoding="utf-8")

    inputs = load_inputs(trial)

    assert inputs.submitted_patch_bytes is None
    assert _severity(run_checks(inputs), "committed_work_vs_empty_submission") == UNKNOWN


# --- round 6, H-1: a job directory named after the task hid every trial -------
# Pier names its job directory after the task, and every SWE-bench instance id
# carries a "__" (swelive-...-aiogram__aiogram-1594 / aiogram__aiogram-1594__
# pteFG6N). _inside_a_trial rejected a depth-2 candidate whose PARENT's NAME
# held a "__", so find_trials returned [] for every real swelive job: the run
# proceeded with trial, gt_run and report all None, and the workflow's copied
# progress receipt kept the no_trial_found branch from firing. A planted
# child_returncode=0 / internal_error contradiction then exited 0 under a real
# task id, with contradictions=0. That is the false-pass shape this section
# reproduces from the artifact of run 35249057348 itself.

SWELIVE_ARTIFACT = ROOT / ".tmp-swelive-35249057348"
SWELIVE_JOB = "swelive-gt-harness-35249057348-aiogram__aiogram-1594"
SWELIVE_TRIAL = "aiogram__aiogram-1594__pteFG6N"
SWELIVE_TASK = "aiogram__aiogram-1594"


def _copy_swelive_job(root: Path) -> Path:
    """The real run's job directory, copied under ``root``, minus its state dir.

    ``agent/gt-state/`` is 2 GB of per-request provider blobs and holds no
    receipt this reads (only its top level is globbed, and that level is
    directories). Everything the checker opens - the trial's own JSON, agent/,
    artifacts/model.patch, the job directory's files - is copied verbatim.
    """
    source = SWELIVE_ARTIFACT / SWELIVE_JOB
    if not source.is_dir():
        pytest.skip(f"real artifact {source} is not present")
    destination = root / SWELIVE_JOB
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns("gt-state"))
    return destination / SWELIVE_TRIAL


def test_the_real_swelive_job_directory_resolves_its_trial(tmp_path):
    """Run 35249057348, pointed at the suite root exactly as the step does."""
    trial = _copy_swelive_job(tmp_path)

    inputs = load_inputs(tmp_path)

    assert find_trials(tmp_path) == [trial]
    assert inputs.trial == trial
    assert inputs.task_id == SWELIVE_TASK
    assert inputs.gt_run is not None
    assert inputs.report is not None
    # The patch Pier collected is this run's, read from inside the trial.
    assert inputs.submitted_patch_bytes == 2702
    receipt = build_receipt(inputs, run_checks(inputs, job_conclusion="success"))
    assert receipt["task_id"] == SWELIVE_TASK
    assert receipt["contradictions"] == 0
    assert SWELIVE_TRIAL in receipt["inputs"]["gt-run.json"]


def test_a_contradiction_in_the_real_swelive_artifact_reddens_the_job(tmp_path, capsys):
    """The same tree with one planted contradiction must exit 1, not 0.

    The progress receipt is copied into the job directory because that is what
    the workflow step does, and it is what kept the no_trial_found branch from
    firing while nothing else had been read.
    """
    trial = _copy_swelive_job(tmp_path)
    report = json.loads((trial / "agent" / "miniswe_report.json").read_text(encoding="utf-8"))
    report["terminal"] = "internal_error"
    report["supervisor"] = {"child_returncode": 0, "reason": "exited"}
    _write(trial / "agent" / "miniswe_report.json", report)
    _write(trial.parent / "benchmark-progress.json", _progress(SWELIVE_TASK))
    out = tmp_path / "receipt-consistency.json"

    exit_code = main([str(tmp_path), "--job-conclusion", "success", "--json", str(out)])

    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert exit_code == 1, capsys.readouterr()
    assert receipt["task_id"] == SWELIVE_TASK
    assert receipt["contradictions"] >= 1
    fired = {c["check_id"] for c in receipt["checks"] if c["severity"] == CONTRADICTION}
    assert "child_exit_vs_terminal" in fired


def test_a_job_directory_named_with_a_double_underscore_still_yields_its_trial(tmp_path):
    """Depth 2: <suite root>/<job named after a SWE-bench instance>/<trial>/."""
    job = f"swelive-gt-harness-35249057348-{SWELIVE_TASK}"
    trial = _pier_tree(tmp_path, SWELIVE_TASK, job=job)

    assert find_trials(tmp_path) == [trial]
    inputs = load_inputs(tmp_path)
    assert inputs.trial == trial
    assert inputs.task_id == SWELIVE_TASK
    assert inputs.gt_run is not None


def test_a_job_directory_named_with_a_double_underscore_resolves_when_pointed_at(tmp_path):
    """Depth 1: the same job directory handed to the checker directly."""
    job = f"swelive-gt-harness-35249057348-{SWELIVE_TASK}"
    trial = _pier_tree(tmp_path, SWELIVE_TASK, job=job)

    inputs = load_inputs(trial.parent)

    assert find_trials(trial.parent) == [trial]
    assert inputs.trial == trial
    assert inputs.task_id == SWELIVE_TASK
    assert inputs.report is not None


def test_a_relative_root_inside_a_trial_still_bounds_the_checkout(tmp_path, monkeypatch):
    """`.` as the root must resolve like any other path, or the bound is gone.

    The ancestor rule compares paths, so both sides are resolved before they
    are compared: a relative root would otherwise never equal the candidate's
    ancestors and every look-alike under <trial>/checkout/ would be read.
    """
    import scripts.verify_run_receipts as module

    trial = _trial_with_a_look_alike_checkout(tmp_path)
    monkeypatch.chdir(trial)
    opened: list[Path] = []
    real_read = module._read_json

    def _recording_read(path):
        if path is not None:
            opened.append(Path(path))
        return real_read(path)

    monkeypatch.setattr(module, "_read_json", _recording_read)

    inputs = module.load_inputs(Path("."))

    assert module.find_trials(Path(".")) == []
    assert not [path for path in opened if "checkout" in path.parts], opened
    assert inputs.gt_run is None
    assert inputs.report is None
    assert inputs.progress is None
    assert inputs.submitted_patch_bytes is None


def test_a_progress_receipt_alone_is_not_a_resolved_task(tmp_path, capsys):
    """The false-pass shape: a task-labelled receipt whose checks all say UNKNOWN.

    The progress receipt is the one the workflow copies in, so it is present
    on every run whether or not anything else was found. Resolving on it alone
    put a real task id on a receipt in which nothing had been read.
    """
    _write(tmp_path / SWELIVE_JOB / "benchmark-progress.json", _progress(SWELIVE_TASK))
    out = tmp_path / "receipt-consistency.json"

    exit_code = main([str(tmp_path), "--job-conclusion", "success", "--json", str(out)])

    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert exit_code == 2
    assert receipt["resolution_error"] == "no_trial_found"
    assert receipt["task_id"] is None
    assert {check["severity"] for check in receipt["checks"]} == {UNKNOWN}
    assert "::error title=Unresolved receipts::" in capsys.readouterr().err


def test_a_flat_layout_resolves_on_a_run_receipt_not_on_progress_alone(tmp_path):
    """The flat layout is still supported - when a run receipt was read."""
    task_dir = tmp_path / "extract-elf"
    _write(task_dir / "gt-run.json", _gt_run("extract-elf"))
    _write(task_dir / "benchmark-progress.json", _progress("extract-elf"))
    out = tmp_path / "receipt-consistency.json"

    exit_code = main([str(tmp_path), "--job-conclusion", "success", "--json", str(out)])

    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert receipt["resolution_error"] is None
    assert receipt["task_id"] == "extract-elf"


# --- round 6, H-2: the refusal receipt never re-runs what just failed ---------
# build_unresolved_receipt enumerated the check ids by CALLING run_checks on an
# empty Inputs. A check that raises only on real receipts therefore turned a
# genuine contradiction into read_error, and an input-independent bug re-raised
# inside the exception handler: exit 1, a traceback, and no receipt at all,
# while exit 1 is the workflow's "the receipts contradict each other" branch.


def test_the_refusal_receipt_runs_no_check_to_name_them(monkeypatch):
    import scripts.verify_run_receipts as module

    def _never(*_args, **_kwargs):
        raise AssertionError("a refusal must not execute the checks")

    monkeypatch.setattr(module, "run_checks", _never)

    receipt = module.build_unresolved_receipt("no_trial_found", "nothing under the root")

    assert [check["check_id"] for check in receipt["checks"]] == list(module.CHECK_IDS)
    assert {check["severity"] for check in receipt["checks"]} == {UNKNOWN}
    assert receipt["task_id"] is None
    assert receipt["contradictions"] == 0


def test_the_static_check_ids_are_the_ids_the_checks_report(tmp_path):
    """The refusal names checks it never ran, so the two lists must agree."""
    _healthy_tree(tmp_path)

    reported = [check["check_id"] for check in run_checks(load_inputs(tmp_path))]

    assert reported == list(CHECK_IDS)


def test_an_input_independent_bug_still_leaves_a_receipt_and_exits_two(
    tmp_path, monkeypatch, capsys
):
    """Round-4 HIGH-1 verbatim: the bug fired again inside the handler.

    ``_result`` is called by every check, including the ones an empty Inputs
    reaches, so a bug there is input-independent: the refusal receipt used to
    be built by re-running those same checks, and the exception escaped main
    as exit 1 with a traceback and nothing on disk.
    """
    import scripts.verify_run_receipts as module

    _healthy_tree(tmp_path)

    def _boom(*_args, **_kwargs):
        raise RuntimeError("input-independent bug")

    monkeypatch.setattr(module, "_result", _boom)
    out = tmp_path / "receipt-consistency.json"

    exit_code = module.main([str(tmp_path), "--json", str(out)])

    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert exit_code == 2
    assert receipt["resolution_error"] == "read_error"
    assert "RuntimeError" in receipt["resolution_detail"]
    assert [check["check_id"] for check in receipt["checks"]] == list(CHECK_IDS)
    assert {check["severity"] for check in receipt["checks"]} == {UNKNOWN}
    assert "::error title=Unresolved receipts::" in capsys.readouterr().err


def test_a_receipt_that_cannot_be_written_is_reported_not_swallowed(tmp_path, capsys):
    """--json under a path that is a FILE: the write fails, the run must say so."""
    _healthy_tree(tmp_path)
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")

    exit_code = main([str(tmp_path), "--json", str(blocker / "receipt.json")])

    assert exit_code == 2
    assert "::error title=Receipt not written::" in capsys.readouterr().err


# --- round 7, HIGH-1: a crashed check is not a data-driven UNKNOWN -----------
# A check that raises was recorded as that check's UNKNOWN, and UNKNOWN is not
# counted anywhere. When the raising check is the one that would have returned
# CONTRADICTION, `contradictions` stays 0 and main returns 0 - a green job over
# a contradiction sitting on disk, because the workflow reads the exit code and
# nothing reads receipt-consistency.json. "A silent check is a missing one" has
# to hold for a check that was silenced by its own exception too, so a crash is
# recorded as its own class and the run is unresolved (rc 2) rather than clean.


def _explode_check(monkeypatch, module, check_id: str, message: str = "check exploded"):
    """Replace one registered check with one that raises, leaving the rest."""

    def _boom(*_args, **_kwargs):
        raise RuntimeError(message)

    monkeypatch.setattr(
        module,
        "CHECKS",
        tuple(
            (registered, _boom if registered == check_id else check)
            for registered, check in module.CHECKS
        ),
    )


def _plant_swelive_contradiction(trial: Path) -> None:
    """Run 35280614124's shape inside the real 35249057348 artifact."""
    report = json.loads((trial / "agent" / "miniswe_report.json").read_text(encoding="utf-8"))
    report["terminal"] = "internal_error"
    report["supervisor"] = {"child_returncode": 0, "reason": "exited"}
    _write(trial / "agent" / "miniswe_report.json", report)
    _write(trial.parent / "benchmark-progress.json", _progress(SWELIVE_TASK))


def test_a_crashed_check_never_exits_zero_over_the_contradiction_it_would_have_found(
    tmp_path, monkeypatch, capsys
):
    """HIGH-1: the one check that would have fired raises; rc must not be 0."""
    import scripts.verify_run_receipts as module

    trial = _copy_swelive_job(tmp_path)
    _plant_swelive_contradiction(trial)
    _explode_check(monkeypatch, module, "child_exit_vs_terminal")
    out = tmp_path / "receipt-consistency.json"

    exit_code = module.main([str(tmp_path), "--job-conclusion", "success", "--json", str(out)])

    receipt = json.loads(out.read_text(encoding="utf-8"))
    entry = _by_id(receipt["checks"])["child_exit_vs_terminal"]
    assert exit_code == 2, capsys.readouterr()
    assert receipt["task_id"] == SWELIVE_TASK
    assert receipt["checks_crashed"] == 1
    assert receipt["contradictions"] == 0
    assert entry["crashed"] is True
    assert entry["severity"] == UNKNOWN
    assert "error: RuntimeError: check exploded" in entry["message"]
    assert _check_ids(receipt) == list(CHECK_IDS)


def test_a_data_driven_unknown_is_not_a_crash_and_still_exits_zero(tmp_path, capsys):
    """green_job_zero_graded with no --job-conclusion is UNKNOWN by design."""
    _collected_patch(_healthy_tree(tmp_path))
    out = tmp_path / "receipt-consistency.json"

    exit_code = main([str(tmp_path), "--json", str(out)])

    receipt = json.loads(out.read_text(encoding="utf-8"))
    entry = _by_id(receipt["checks"])["green_job_zero_graded"]
    assert exit_code == 0, capsys.readouterr()
    assert entry["severity"] == UNKNOWN
    assert entry.get("crashed") is not True
    assert receipt["checks_crashed"] == 0


def test_a_crashed_check_beside_a_healthy_tree_is_still_unresolved(tmp_path, monkeypatch):
    """No contradiction anywhere, one check crashed: unresolved, never clean."""
    import scripts.verify_run_receipts as module

    _collected_patch(_healthy_tree(tmp_path))
    _explode_check(monkeypatch, module, "oom_signature")
    out = tmp_path / "receipt-consistency.json"

    exit_code = module.main([str(tmp_path), "--job-conclusion", "success", "--json", str(out)])

    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert exit_code == 2
    assert receipt["contradictions"] == 0
    assert receipt["checks_crashed"] == 1
    assert _by_id(receipt["checks"])["oom_signature"]["crashed"] is True


def test_a_contradiction_still_wins_over_a_crashed_check(tmp_path, monkeypatch):
    """rc=1 means the receipts contradict each other, crash or no crash."""
    import scripts.verify_run_receipts as module

    task_dir = _healthy_tree(tmp_path, "run-35262214538")
    _collected_patch(task_dir)
    _write(task_dir / "agent" / "miniswe_report.json", _report(terminal="internal_error"))
    _explode_check(monkeypatch, module, "oom_signature")
    out = tmp_path / "receipt-consistency.json"

    exit_code = module.main([str(tmp_path), "--json", str(out)])

    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert exit_code == 1
    assert receipt["contradictions"] == 1
    assert receipt["checks_crashed"] == 1


# --- round 7, HIGH-2: NaN and Infinity are JSON that Python writes -----------
# json.dumps emits bare NaN/Infinity and json.loads accepts them, so a receipt
# can carry a float that int() refuses: int(nan) is a ValueError and int(inf)
# an OverflowError. Every one of those landed in the per-check except above and
# became HIGH-1's silent UNKNOWN. A value that is not a finite number is
# unreadable, and unreadable is UNKNOWN - never a crash, and never an OK that
# names the number it could not read.

_NON_FINITE = ("NaN", "Infinity", "-Infinity")


def _write_raw(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize("literal", _NON_FINITE)
def test_a_non_finite_child_returncode_is_unknown_not_a_crash(tmp_path, literal):
    """The field cannot be read, so the check that reads it says so."""
    task_dir = _healthy_tree(tmp_path, "extract-elf")
    _collected_patch(task_dir)
    report = _report(terminal="internal_error")
    report["supervisor"]["child_returncode"] = float(literal.replace("Infinity", "inf"))
    _write_raw(task_dir / "agent" / "miniswe_report.json", json.dumps(report))
    # A genuine contradiction in another receipt pair, decided by strings only.
    _write(
        task_dir / "progress" / "benchmark-progress.json",
        _progress("extract-elf", state="infrastructure_failed"),
    )
    out = tmp_path / "receipt-consistency.json"

    exit_code = main([str(tmp_path), "--json", str(out)])

    receipt = json.loads(out.read_text(encoding="utf-8"))
    entry = _by_id(receipt["checks"])["child_exit_vs_terminal"]
    assert literal in (task_dir / "agent" / "miniswe_report.json").read_text(encoding="utf-8")
    assert exit_code == 1
    assert receipt["checks_crashed"] == 0
    assert entry.get("crashed") is not True
    assert entry["severity"] == UNKNOWN
    assert "ValueError" not in entry["message"]
    assert "OverflowError" not in entry["message"]
    assert receipt["contradictions"] == 1
    assert _severity(receipt["checks"], "valid_run_vs_infra_state") == CONTRADICTION


def test_every_numeric_field_at_once_survives_a_non_finite_value(tmp_path):
    """Every `_int` call site in the module, fed NaN in one pass.

    child_returncode, committed_patch_bytes, the three provider counters,
    officially_graded and the progress row's reward are the whole set. None of
    them may crash a check, and the contradiction that needs no number at all
    must still redden the job.
    """
    nan = float("nan")
    task_dir = tmp_path / "extract-elf"
    report = _report(terminal="provider_failed")
    report["supervisor"]["child_returncode"] = nan
    report["submission_patch_state"]["committed_patch_bytes"] = nan
    _write_raw(task_dir / "agent" / "miniswe_report.json", json.dumps(report))
    _write_raw(
        task_dir / "agent" / "gt-run.json",
        json.dumps(
            _gt_run(
                "extract-elf",
                terminal="provider_failed",
                provider_calls=nan,
                provider_completed_calls=nan,
                provider_failed_calls=nan,
            )
        ),
    )
    progress = _progress("extract-elf", state="infrastructure_failed", reward=nan)
    progress["officially_graded"] = nan
    _write_raw(task_dir / "progress" / "benchmark-progress.json", json.dumps(progress))
    _collected_patch(task_dir)
    out = tmp_path / "receipt-consistency.json"

    exit_code = main([str(tmp_path), "--job-conclusion", "success", "--json", str(out)])

    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert exit_code == 1
    assert receipt["checks_crashed"] == 0
    assert _severity(receipt["checks"], "valid_run_vs_infra_state") == CONTRADICTION
    assert _severity(receipt["checks"], "child_exit_vs_terminal") == UNKNOWN
    assert _severity(receipt["checks"], "provider_failed_without_provider_failures") == UNKNOWN


# --- round 7, LOW-5: an unwritable receipt never downgrades a contradiction --
# rc 1 is the workflow's "these receipts contradict each other" branch and rc 2
# is "nothing could be resolved". A --json path that cannot be written is a
# reporting failure, not a retraction of what was found: it may raise rc 0 to
# 2, and it must never lower rc 1 to 2.


def test_an_unwritable_receipt_does_not_downgrade_a_contradiction(tmp_path, capsys):
    task_dir = _healthy_tree(tmp_path, "run-35280614124")
    _collected_patch(task_dir)
    _write(task_dir / "agent" / "miniswe_report.json", _report(terminal="internal_error"))
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")

    exit_code = main([str(tmp_path), "--json", str(blocker / "receipt.json")])

    assert exit_code == 1
    assert "::error title=Receipt not written::" in capsys.readouterr().err


# --- round 7, LOW-3: a path that escapes the root is never a trial of it -----
# Both sides are resolved before they are compared, so a symlink under the root
# pointing outside it resolves out from under the root: the ancestor walk runs
# off the top, the for...else fired, and the escapee was reported as NOT inside
# a trial - which made it a search root, and another project's receipts this
# run's. Windows denies symlinks to an unprivileged process, so the escape is
# modelled by resolving one directory elsewhere, which is exactly what the
# kernel does with a symlink.


def _resolve_elsewhere(monkeypatch, mapping: dict) -> None:
    """Make `Path.resolve` send specific directories outside the root."""
    real_resolve = Path.resolve
    resolved = {real_resolve(source): real_resolve(target) for source, target in mapping.items()}

    def fake_resolve(self, *args, **kwargs):
        actual = real_resolve(self, *args, **kwargs)
        return resolved.get(actual, actual)

    monkeypatch.setattr(Path, "resolve", fake_resolve)


def test_a_child_that_resolves_outside_the_root_is_not_a_search_root(tmp_path, monkeypatch):
    import scripts.verify_run_receipts as module

    root = tmp_path / "job"
    trial = root / "extract-elf__8VJiMwD"
    (trial / "agent").mkdir(parents=True)
    escapee = root / "vendored"
    _write(escapee / "agent" / "gt-run.json", _gt_run("another-task"))
    outside = tmp_path / "outside" / "vendored"
    outside.mkdir(parents=True)
    _resolve_elsewhere(monkeypatch, {escapee: outside})

    roots = module._trial_roots(root)

    assert escapee not in roots
    assert roots == [root, trial]
    assert all(escapee not in path.parents for path in module.harness_receipts(root))


def test_the_root_itself_is_always_a_search_root(tmp_path):
    """`candidate == root` is not an escape: the root is where the search starts."""
    import scripts.verify_run_receipts as module

    trial = tmp_path / "extract-elf__8VJiMwD"
    (trial / "agent").mkdir(parents=True)

    assert module._inside_a_trial(trial, trial) is False
    assert module._trial_roots(trial)[0] == trial


# --- round 7, LOW-1: the trial directory is the last word on the task id -----
# `<task>__<hash>`.rpartition("__") reads a flat `amoffat__sh-744/` directory -
# a SWE-bench instance id with no Pier hash appended - as the task `amoffat`.
# The suffix is not decidable from the name alone (a Pier hash and a repo
# segment are both just text), so the split is left as it is and bounded
# instead: the trial name is the LAST fallback, and gt-run.json always carries
# a task_id because its only producer refuses to write one without it.


def test_gt_run_json_always_carries_a_task_id_so_the_directory_is_a_last_resort():
    """gt_harness/runtime_receipts.py refuses to issue a receipt without one."""
    source = PRODUCER.read_text(encoding="utf-8")
    assert 'raise ValueError("task_id_required")' in source
    assert "task_id: str," in source


def test_the_task_id_comes_off_the_receipt_not_off_a_hashless_directory(tmp_path):
    """A flat `amoffat__sh-744/` trial: the receipt names the task, and wins."""
    task_dir = tmp_path / "amoffat__sh-744"
    _write(task_dir / "agent" / "gt-run.json", _gt_run("amoffat__sh-744"))
    _write(task_dir / "agent" / "miniswe_report.json", _report())

    inputs = load_inputs(tmp_path)

    assert inputs.task_id == "amoffat__sh-744"
    # Documented, not fixed: with no hash to strip the split takes the instance
    # id apart. Nothing reads it while any receipt names the task.
    assert inputs.trial_task_id == "amoffat"


# --- round 7, HIGH-1: a trial directory is not a run receipt ------------------
# The resolved gate asked `trial is None and gt_run is None and report is None`,
# so in the Pier layout the mere EXISTENCE of a `<task>__<hash>/agent/`
# directory satisfied it - even though nothing in it was a run receipt. Run
# 35241999929 is that shape on disk: the trial died inside harbor and its
# `agent/` holds only diagnostics.json, incident-replay.json and
# official-verifier-result.json. Pointed at the job directory exactly as the
# workflow points it, the checker exited 0 with task_id aiogram__aiogram-1594,
# resolution_error null and all six checks UNKNOWN - the false-pass shape
# round 6 declared unacceptable, now reached through the trial branch instead
# of through the copied progress receipt.

DEAD_ARTIFACT = ROOT / ".tmp-swelive-35241999929"
DEAD_JOB = "swelive-gt-harness-35241999929-aiogram__aiogram-1594"
DEAD_TRIAL = "aiogram__aiogram-1594__QxUynm4"


def _copy_dead_swelive_job(root: Path) -> Path:
    """Run 35241999929's job directory, copied under ``root``, minus its state dir.

    ``agent/gt-state/`` is 466 MB of per-request provider blobs and holds no
    receipt this reads. Everything the checker opens is copied verbatim.
    """
    source = DEAD_ARTIFACT / DEAD_JOB
    if not source.is_dir():
        pytest.skip(f"real artifact {source} is not present")
    destination = root / DEAD_JOB
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns("gt-state"))
    return destination / DEAD_TRIAL


def test_a_real_trial_that_wrote_no_run_receipt_is_not_a_resolved_task(tmp_path, capsys):
    """Run 35241999929: a trial directory, an agent/, and no run receipt at all."""
    trial = _copy_dead_swelive_job(tmp_path)
    out = tmp_path / "receipt-consistency.json"

    exit_code = main([str(tmp_path), "--job-conclusion", "success", "--json", str(out)])

    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert exit_code == 2, receipt
    assert receipt["resolution_error"] == "no_run_receipt"
    # No receipt named this task, so nothing here may name it either: the
    # trial directory's name is a directory name, not evidence of a run.
    assert receipt["task_id"] is None
    assert _check_ids(receipt) == list(CHECK_IDS)
    assert {check["severity"] for check in receipt["checks"]} == {UNKNOWN}
    assert receipt["checks_crashed"] == 0
    assert receipt["contradictions"] == 0
    # The reader has to be told what WAS found, or "no receipt" is unfalsifiable.
    detail = receipt["resolution_detail"]
    assert str(trial) in detail
    assert "diagnostics.json" in detail
    assert "::error title=Unresolved receipts::" in capsys.readouterr().err


def test_a_trial_stripped_of_both_receipts_is_not_a_green_job(tmp_path, capsys):
    """The healthy run's own tree, minus its receipts, with progress copied in.

    This is the WARNING-only path the false pass hid behind: a green job with
    zero graded tasks is rc 0, so a trial whose receipts are absent must be
    refused before the checks ever run.
    """
    trial = _copy_swelive_job(tmp_path)
    (trial / "agent" / "gt-run.json").unlink()
    (trial / "agent" / "miniswe_report.json").unlink()
    _write(trial.parent / "benchmark-progress.json", _progress(SWELIVE_TASK))
    out = tmp_path / "receipt-consistency.json"

    exit_code = main([str(tmp_path), "--job-conclusion", "success", "--json", str(out)])

    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert exit_code == 2, receipt
    assert receipt["resolution_error"] == "no_run_receipt"
    assert receipt["task_id"] is None
    assert {check["severity"] for check in receipt["checks"]} == {UNKNOWN}
    assert "::error title=Unresolved receipts::" in capsys.readouterr().err


def test_the_healthy_real_swelive_tree_still_exits_zero(tmp_path, capsys):
    """The gate must refuse an empty trial without refusing a real one."""
    _copy_swelive_job(tmp_path)
    out = tmp_path / "receipt-consistency.json"

    exit_code = main([str(tmp_path), "--job-conclusion", "success", "--json", str(out)])

    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert exit_code == 0, capsys.readouterr()
    assert receipt["resolution_error"] is None
    assert receipt["task_id"] == SWELIVE_TASK


def test_a_trial_with_only_a_miniswe_report_still_resolves(tmp_path):
    """Either run receipt resolves; the gate is about receipts, not about both."""
    trial = _pier_tree(tmp_path, "extract-elf")
    (trial / "agent" / "gt-run.json").unlink()
    out = tmp_path / "receipt-consistency.json"

    exit_code = main([str(tmp_path), "--job-conclusion", "success", "--json", str(out)])

    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert exit_code == 0, receipt
    assert receipt["resolution_error"] is None


def test_every_refusal_code_written_is_a_documented_one():
    """A refusal code nobody documented reads as a checker bug, not a verdict.

    Located by what the code does - the code handed to
    ``build_unresolved_receipt`` - so adding a fifth refusal in a new branch
    cannot quietly ship an undocumented ``resolution_error``.

    N-5 (round 8): the walk read string constants only, and main chooses
    between no_trial_found and no_run_receipt in a variable, so neither was
    ever located and a hardcoded membership assertion stood in for them - the
    guard marking its own homework. ``_refusal_codes`` resolves the variable
    and fails on any call it cannot read, so the two sets can be compared
    exactly: every documented code is emitted somewhere and nothing else is.
    """
    import scripts.verify_run_receipts as module

    emitted = _refusal_codes(
        (ROOT / "scripts" / "verify_run_receipts.py").read_text(encoding="utf-8")
    )
    assert emitted, "no refusal code was located; the guard would be a rubber stamp"
    assert emitted == set(module.RESOLUTION_ERRORS)
    for code in module.RESOLUTION_ERRORS:
        assert code in module.__doc__, f"{code} is not named in the module docstring"


# --- round 8, MEDIUM N-1 / N-2 / N-4: artifacts that exist and were misread --
# Three ways the round-7 refusal reported something other than what was on
# disk, all of them reproduced on copies of the real trees:
#
#  * N-1: a gt-run.json that EXISTS and cannot be parsed was swallowed to None
#    by the reader, so the gate reported no_run_receipt - "wrote no
#    gt-run.json" - in a detail whose own file list named gt-run.json, and
#    past _DETAIL_FILE_LIMIT names the contradiction truncated away. A receipt
#    that exists and cannot be read is evidence of a writer or an upload
#    fault, so it is refused by name as read_error and a healthy
#    miniswe_report.json beside it does not rescue it: silently preferring the
#    readable one reports a half-written upload as a graded run.
#  * N-2: pointed at the trial directory ITSELF - a mode the CLI's own help
#    offers - find_trials correctly finds nothing below it, and the refusal
#    then said no_trial_found with no file list: a run that died read as a
#    wrong path.
#  * N-4: the only tests of the no_run_receipt branch copy the untracked
#    .tmp-swelive-* trees, so on CI and in a fresh clone they skip and the
#    round-7 gate executes in zero tests. These build the same shapes from
#    nothing, and the real-tree tests stay as the extra layer.


def _dead_pier_tree(
    root: Path,
    task_id: str = "aiogram__aiogram-1594",
    job: str = "swelive-gt-harness-35241999929-aiogram__aiogram-1594",
    digest: str = "QxUynm4",
) -> Path:
    """Run 35241999929's shape: a trial the runner made and the agent never filled.

    Harbor killed the trial before the harness wrote either run receipt, so
    ``agent/`` holds only what the infrastructure itself writes. Built here
    rather than copied, so the branch is exercised where the real tree is not.
    """
    trial = root / job / f"{task_id}__{digest}"
    _write(trial / "agent" / "diagnostics.json", {"killed_by": "harbor"})
    _write(trial / "agent" / "incident-replay.json", {"events": []})
    _write(trial / "agent" / "official-verifier-result.json", {"reward": 0})
    return trial


def _found_files(detail: str) -> str:
    """The file list out of a refusal detail, which is the falsifiable half."""
    _, marker, listed = detail.partition("harness JSON found there:")
    assert marker, detail
    return listed


def test_a_synthetic_dead_trial_is_refused_and_names_what_it_did_write(tmp_path, capsys):
    """N-4: the no_run_receipt branch, without the untracked artifact tree."""
    trial = _dead_pier_tree(tmp_path)
    out = tmp_path / "receipt-consistency.json"

    exit_code = main([str(tmp_path), "--job-conclusion", "success", "--json", str(out)])

    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert exit_code == 2, receipt
    assert receipt["resolution_error"] == "no_run_receipt"
    assert receipt["task_id"] is None
    assert _check_ids(receipt) == list(CHECK_IDS)
    assert {check["severity"] for check in receipt["checks"]} == {UNKNOWN}
    assert receipt["checks_crashed"] == 0
    detail = receipt["resolution_detail"]
    assert str(trial) in detail
    assert "diagnostics.json" in _found_files(detail)
    # The claim and the evidence have to agree: a detail that says "wrote no
    # gt-run.json" while listing one is self-contradicting (N-1).
    assert "gt-run.json" not in _found_files(detail)
    assert "::error title=Unresolved receipts::" in capsys.readouterr().err


def test_a_synthetic_dead_trial_with_a_progress_receipt_is_not_a_green_job(tmp_path):
    """N-4: the copied progress receipt must not turn the refusal into a WARNING."""
    trial = _dead_pier_tree(tmp_path)
    _write(trial.parent / "benchmark-progress.json", _progress("aiogram__aiogram-1594"))
    out = tmp_path / "receipt-consistency.json"

    exit_code = main([str(tmp_path), "--job-conclusion", "success", "--json", str(out)])

    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert exit_code == 2, receipt
    assert receipt["resolution_error"] == "no_run_receipt"
    assert receipt["task_id"] is None


def test_the_trial_directory_itself_is_a_run_that_died_not_a_wrong_path(tmp_path, capsys):
    """N-2: pointed at the trial, the refusal must still be about the receipts."""
    trial = _dead_pier_tree(tmp_path)
    out = tmp_path / "receipt-consistency.json"

    exit_code = main([str(trial), "--job-conclusion", "success", "--json", str(out)])

    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert exit_code == 2, receipt
    assert receipt["resolution_error"] == "no_run_receipt"
    assert receipt["task_id"] is None
    detail = receipt["resolution_detail"]
    assert str(trial) in detail
    assert "diagnostics.json" in _found_files(detail)
    assert "::error title=Unresolved receipts::" in capsys.readouterr().err


def test_a_real_dead_trial_pointed_at_directly_reports_what_it_wrote(tmp_path):
    """N-2 on run 35241999929's own directory, the tree the reviewer ran."""
    trial = _copy_dead_swelive_job(tmp_path)
    out = tmp_path / "receipt-consistency.json"

    exit_code = main([str(trial), "--job-conclusion", "success", "--json", str(out)])

    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert exit_code == 2, receipt
    assert receipt["resolution_error"] == "no_run_receipt"
    assert "diagnostics.json" in _found_files(receipt["resolution_detail"])


def test_a_trial_directory_root_holding_receipts_still_resolves(tmp_path):
    """Trial-dir mode is a supported layout, not only a refusal path."""
    trial = _pier_tree(tmp_path, "extract-elf")
    out = tmp_path / "receipt-consistency.json"

    exit_code = main([str(trial), "--job-conclusion", "success", "--json", str(out)])

    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert exit_code == 0, receipt
    assert receipt["resolution_error"] is None
    assert receipt["task_id"] == "extract-elf"


def test_a_corrupt_gt_run_receipt_is_a_read_error_not_a_missing_one(tmp_path, capsys):
    """N-1: the file is there. Saying it was never written is a false report."""
    trial = _dead_pier_tree(tmp_path)
    _write_raw(trial / "agent" / "gt-run.json", "{ this is not json")
    out = tmp_path / "receipt-consistency.json"

    exit_code = main([str(tmp_path), "--job-conclusion", "success", "--json", str(out)])

    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert exit_code == 2, receipt
    assert receipt["resolution_error"] == "read_error"
    assert receipt["task_id"] is None
    assert {check["severity"] for check in receipt["checks"]} == {UNKNOWN}
    detail = receipt["resolution_detail"]
    assert "gt-run.json" in detail
    # The parse error itself, so the reader knows what to look at on disk.
    assert "Expecting" in detail
    assert len(detail) < 500, detail
    assert "::error title=Unresolved receipts::" in capsys.readouterr().err


def test_a_healthy_report_does_not_rescue_a_corrupt_gt_run_receipt(tmp_path):
    """A corrupt receipt beside a readable one is a fault, not a spare tyre.

    Both files are written by the same step of the same run. One of them
    arriving unparseable says the writer or the upload broke, and grading the
    run off the other reports a partial artifact as a complete one.
    """
    trial = _pier_tree(tmp_path, "extract-elf")
    _write_raw(trial / "agent" / "gt-run.json", "{ this is not json")
    out = tmp_path / "receipt-consistency.json"

    exit_code = main([str(tmp_path), "--job-conclusion", "success", "--json", str(out)])

    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert exit_code == 2, receipt
    assert receipt["resolution_error"] == "read_error"
    assert "gt-run.json" in receipt["resolution_detail"]
    assert receipt["task_id"] is None


def test_a_gt_run_receipt_that_is_a_json_list_is_a_read_error(tmp_path):
    """Valid JSON that is not an object carries no key any check reads."""
    trial = _dead_pier_tree(tmp_path)
    _write_raw(trial / "agent" / "gt-run.json", json.dumps([_gt_run("aiogram__aiogram-1594")]))
    out = tmp_path / "receipt-consistency.json"

    exit_code = main([str(tmp_path), "--json", str(out)])

    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert exit_code == 2, receipt
    assert receipt["resolution_error"] == "read_error"
    detail = receipt["resolution_detail"]
    assert "gt-run.json" in detail
    assert "list" in detail


def test_a_run_receipt_in_another_encoding_is_a_read_error(tmp_path):
    """Undecodable is unread, and an unread receipt on disk is a fault."""
    trial = _dead_pier_tree(tmp_path)
    raw = b'{"task_id": "caf' + bytes([0xE9]) + b'"}'  # latin-1, not UTF-8
    (trial / "agent" / "gt-run.json").write_bytes(raw)
    out = tmp_path / "receipt-consistency.json"

    exit_code = main([str(tmp_path), "--json", str(out)])

    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert exit_code == 2, receipt
    assert receipt["resolution_error"] == "read_error"
    assert "gt-run.json" in receipt["resolution_detail"]


def test_a_corrupt_miniswe_report_is_a_read_error_too(tmp_path):
    """Both run receipts are read on the same terms."""
    trial = _dead_pier_tree(tmp_path)
    _write_raw(trial / "agent" / "miniswe_report.json", "[[[")
    out = tmp_path / "receipt-consistency.json"

    exit_code = main([str(tmp_path), "--json", str(out)])

    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert exit_code == 2, receipt
    assert receipt["resolution_error"] == "read_error"
    assert "miniswe_report.json" in receipt["resolution_detail"]


def test_load_inputs_refuses_an_unreadable_receipt_by_name(tmp_path):
    """The refusal is decided at the read, so every caller gets it."""
    import scripts.verify_run_receipts as module

    trial = _dead_pier_tree(tmp_path)
    _write_raw(trial / "agent" / "gt-run.json", "{ this is not json")

    with pytest.raises(module.ReceiptReadError) as excinfo:
        module.load_inputs(tmp_path)

    assert str(trial / "agent" / "gt-run.json") in str(excinfo.value)


# --- round 8, LOW N-5: the refusal-code guard has to read the real calls -----
# The guard walked build_unresolved_receipt calls whose first argument is a
# string constant. main passes a variable - the round-8 codes no_trial_found
# and no_run_receipt are chosen in an if-expression - so both were invisible
# to it and a hardcoded membership assertion stood in for them, which is the
# guard marking its own homework. Names are now resolved through the string
# constants assigned to them, a call whose code cannot be read fails the guard
# outright, and the documented set and the emitted set must match exactly.


def _code_constants(node: ast.AST) -> set[str]:
    """The string constants a refusal-code expression can evaluate to."""
    if isinstance(node, ast.Constant):
        return {node.value} if isinstance(node.value, str) else set()
    if isinstance(node, ast.IfExp):
        return _code_constants(node.body) | _code_constants(node.orelse)
    return set()


def _refusal_codes(source: str) -> set[str]:
    """Every code ``build_unresolved_receipt`` is handed anywhere in ``source``."""
    tree = ast.parse(source)
    assigned: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        else:
            continue
        values = _code_constants(node.value)
        if not values:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                assigned.setdefault(target.id, set()).update(values)
    codes: set[str] = set()
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "build_unresolved_receipt"
            and node.args
        ):
            continue
        first = node.args[0]
        found = _code_constants(first)
        if not found and isinstance(first, ast.Name):
            found = assigned.get(first.id, set())
        if not found:
            raise AssertionError(
                f"build_unresolved_receipt at line {node.lineno} is handed a code this "
                "guard cannot read; its refusal codes would go unchecked"
            )
        codes |= found
    return codes


def test_the_refusal_guard_reads_a_code_chosen_in_a_variable():
    """The two codes main decides between are located by what the code does."""
    source = (ROOT / "scripts" / "verify_run_receipts.py").read_text(encoding="utf-8")

    assert {"no_trial_found", "no_run_receipt"} <= _refusal_codes(source)


@pytest.mark.parametrize(
    ("original", "planted"),
    (
        # A literal argument, which the old guard did see ...
        (
            'build_unresolved_receipt("ambiguous_trial"',
            'build_unresolved_receipt("mystery_code"',
        ),
        # ... and the variable main actually passes, which it did not.
        ('"no_trial_found" if', '"mystery_code" if'),
    ),
)
def test_the_refusal_guard_catches_a_planted_undocumented_code(original, planted):
    """Planted in a copy of the source text, never in the file itself."""
    source = (ROOT / "scripts" / "verify_run_receipts.py").read_text(encoding="utf-8")
    assert original in source, original
    modified = source.replace(original, planted, 1)

    assert "mystery_code" in _refusal_codes(modified)


def test_the_refusal_guard_fails_on_a_code_it_cannot_read():
    """An unreadable call is an unchecked refusal code, not an absent one."""
    with pytest.raises(AssertionError):
        _refusal_codes("build_unresolved_receipt(code_from_somewhere, detail)\n")


# --- round 9, LOW: a run receipt that parses and says nothing ----------------
# The third door to the same false pass. Round 6 closed the progress-receipt
# door and round 7 the bare-trial-directory door; a gt-run.json that parses as
# an object but carries no key any check reads walked through a third one:
# it resolved the task, every check said UNKNOWN, and main exited 0. Six of
# six UNKNOWN with no check crashed means nothing about the run was decided,
# which is what "unresolved" means, so it is refused by name. A healthy run
# never trips it: a real gt-run.json decides at least one check.


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"unrelated": 1},
        {"schema": "some.other.v1", "hello": "world"},
    ],
    ids=["empty_object", "unrelated_key", "other_schema"],
)
def test_a_run_receipt_that_decides_nothing_is_not_a_resolved_run(tmp_path, capsys, payload):
    trial = _pier_tree(tmp_path)
    _write(trial / "agent" / "gt-run.json", payload)
    (trial / "agent" / "miniswe_report.json").unlink()
    (tmp_path / trial.parent.name / "benchmark-progress.json").unlink()

    exit_code = main([str(trial.parent)])
    receipt = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert receipt["resolution_error"] == "no_decidable_check"
    assert receipt["task_id"] is None
    assert receipt["contradictions"] == 0
    assert receipt["checks_crashed"] == 0
    assert {check["severity"] for check in receipt["checks"]} == {UNKNOWN}
    assert "gt-run.json" in receipt["resolution_detail"]


def test_one_decidable_check_is_enough_to_resolve_a_run(tmp_path, capsys):
    """The rule is all-six-UNKNOWN, not any-UNKNOWN: a partial receipt resolves."""
    trial = _pier_tree(tmp_path)
    _write(trial / "agent" / "gt-run.json", {"task_id": "extract-elf"})
    (tmp_path / trial.parent.name / "benchmark-progress.json").unlink()

    exit_code = main([str(trial.parent)])
    receipt = json.loads(capsys.readouterr().out)

    assert receipt["resolution_error"] is None
    assert receipt["task_id"] == "extract-elf"
    severities = [check["severity"] for check in receipt["checks"]]
    assert UNKNOWN in severities and severities.count(UNKNOWN) < len(severities)
    assert exit_code == 0


def test_the_refusal_guard_reads_an_annotated_constant_too():
    """``_READ: str = "read_error"`` is the same constant as ``_READ = ...``.

    The module already spells its constants with annotations (``CHECKS``,
    ``CHECK_IDS``), so this is the spelling the next refactor reaches for; a
    guard that raises on it and passes on the bare form is a guard that gets
    deleted.
    """
    bare = _refusal_codes(
        '_READ = "read_error"\nbuild_unresolved_receipt(_READ, detail)\n'
    )
    annotated = _refusal_codes(
        '_READ: str = "read_error"\nbuild_unresolved_receipt(_READ, detail)\n'
    )

    assert bare == annotated == {"read_error"}
