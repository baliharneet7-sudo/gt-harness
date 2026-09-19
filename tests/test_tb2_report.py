"""Per-task TB2 report: metrics joined by task_id, cost from a declared rate.

The harness ``total_cost`` field is 0.0 by design, so a report that silently
prints $0.00 has repeatedly been read as "this run was free". Every test here
that touches cost asserts either a real number or a loud refusal - never a
quiet zero.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.tb2_report as tb2_report
from scripts.tb2_report import (
    _GT_RUN_NAME,
    BaselineUnreadable,
    RateUnavailable,
    collect_rows,
    format_report,
    main,
    parse_baseline_summary,
    read_pricing,
    resolve_rates,
)

# Made-up rates: cheap enough to be obviously fictional, exact enough to assert.
_PROMPT_USD = 0.000001
_COMPLETION_USD = 0.000002


def _write(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _route_manifest(path: Path, *, pricing: bool = True) -> Path:
    body = {
        "schema": "gt.provider_route.v1",
        "route_id": "openrouter-deepseek-v4-flash-0731-relace-only",
        "model": "deepseek/deepseek-v4-flash-0731",
    }
    if pricing:
        body["pricing"] = {
            "prompt_usd_per_token": _PROMPT_USD,
            "completion_usd_per_token": _COMPLETION_USD,
        }
    return _write(path, body)


def _progress(root: Path, tasks: list[dict], *, model: str = "deepseek/deepseek-v4-flash-0731"):
    return _write(
        root / "progress.json",
        {
            "schema": "gt.benchmark_progress.v1",
            "benchmark_suite": "terminal-bench-2",
            "model": model,
            "tasks": tasks,
        },
    )


def _task(task_id: str, *, reward=1, graded=True, state="passed", error="") -> dict:
    return {
        "task_id": task_id,
        "state": state,
        "official_verifier": graded,
        "reward": reward,
        "failure_class": "graded" if graded else "runner_error",
        "error_code": error,
    }


def _gt_run(root: Path, task_id: str, **overrides) -> Path:
    body = {
        "schema": "gt.run_receipt.v1",
        "task_id": task_id,
        "terminal": "submitted",
        "status": "COMPLETED",
        "agent_turn_calls": 42,
        "provider_calls": 44,
        "provider_failed_calls": 2,
        "input_tokens": 1_000_000,
        "cached_tokens": 750_000,
        "output_tokens": 100_000,
        "total_cost": 0.0,
    }
    body.update(overrides)
    return _write(root / task_id / "agent" / "gt-run.json", body)


def _two_task_tree(root: Path) -> Path:
    _progress(root, [_task("extract-elf"), _task("fix-git", reward=0, state="verifier_failed")])
    _gt_run(root, "extract-elf")
    _gt_run(
        root,
        "fix-git",
        agent_turn_calls=13,
        provider_calls=13,
        provider_failed_calls=0,
        input_tokens=200_000,
        cached_tokens=0,
        output_tokens=20_000,
    )
    return root


# --- rates -----------------------------------------------------------------


def test_read_pricing_reads_the_route_manifest_pricing_block(tmp_path):
    manifest = _route_manifest(tmp_path / "provider_route_x.v1.json")
    assert read_pricing(manifest) == (_PROMPT_USD, _COMPLETION_USD)


def test_read_pricing_returns_none_when_the_block_is_absent(tmp_path):
    """The pricing block is still being added; its absence is not a crash."""
    manifest = _route_manifest(tmp_path / "provider_route_x.v1.json", pricing=False)
    assert read_pricing(manifest) is None


def test_resolve_rates_prefers_the_manifest(tmp_path):
    manifest = _route_manifest(tmp_path / "route.json")
    prompt, completion, source = resolve_rates(rates_path=manifest)
    assert (prompt, completion) == (_PROMPT_USD, _COMPLETION_USD)
    assert str(manifest) in source


def test_resolve_rates_accepts_explicit_flags_when_the_manifest_has_no_pricing(tmp_path):
    manifest = _route_manifest(tmp_path / "route.json", pricing=False)
    prompt, completion, source = resolve_rates(
        rates_path=manifest, prompt_price=3e-7, completion_price=6e-7
    )
    assert (prompt, completion) == (3e-7, 6e-7)
    assert "flag" in source


def test_resolve_rates_refuses_loudly_when_no_rate_is_available(tmp_path):
    manifest = _route_manifest(tmp_path / "route.json", pricing=False)
    with pytest.raises(RateUnavailable) as excinfo:
        resolve_rates(rates_path=manifest)
    message = str(excinfo.value)
    assert "pricing" in message
    assert "--prompt-price" in message and "--completion-price" in message


def test_resolve_rates_refuses_when_no_rates_path_is_given_at_all():
    with pytest.raises(RateUnavailable):
        resolve_rates()


def test_resolve_rates_refuses_a_half_specified_rate():
    with pytest.raises(RateUnavailable):
        resolve_rates(prompt_price=3e-7)


def test_missing_rate_makes_the_cli_fail_instead_of_printing_zero(tmp_path, capsys):
    _two_task_tree(tmp_path)
    exit_code = main([str(tmp_path)])
    captured = capsys.readouterr()
    assert exit_code != 0
    assert "$0.00" not in captured.out
    assert "rate" in captured.err.lower()


# --- table -----------------------------------------------------------------


def test_basic_table_reports_every_task_with_a_token_derived_cost(tmp_path, capsys):
    _two_task_tree(tmp_path)
    manifest = _route_manifest(tmp_path / "route.json")
    exit_code = main([str(tmp_path), "--rates", str(manifest)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "extract-elf" in out and "fix-git" in out
    # 1,000,000 prompt * 1e-6 + 100,000 completion * 2e-6 = $1.20
    assert "1.20" in out
    # 200,000 * 1e-6 + 20,000 * 2e-6 = $0.24
    assert "0.24" in out
    # cache hit: 750,000 of 1,000,000
    assert "75.0" in out
    assert "officially_graded=2" in out
    assert "solved=1" in out


def test_collect_rows_joins_progress_and_gt_run_on_task_id(tmp_path):
    _two_task_tree(tmp_path)
    rows = collect_rows([tmp_path])
    by_task = {row["task"]: row for row in rows}
    assert set(by_task) == {"extract-elf", "fix-git"}
    assert by_task["extract-elf"]["turns"] == 42
    assert by_task["extract-elf"]["calls"] == 44
    assert by_task["extract-elf"]["provider_failed_calls"] == 2
    assert by_task["extract-elf"]["cached_tokens"] == 750_000
    assert by_task["fix-git"]["reward"] == 0
    assert by_task["fix-git"]["graded"] is True


def test_collect_rows_searches_several_roots(tmp_path):
    left, right = tmp_path / "left", tmp_path / "right"
    _progress(left, [_task("extract-elf")])
    _gt_run(left, "extract-elf")
    _progress(right, [_task("fix-git", reward=0, state="verifier_failed")])
    _gt_run(right, "fix-git")
    rows = collect_rows([left, right])
    assert {row["task"] for row in rows} == {"extract-elf", "fix-git"}


def test_task_without_a_gt_run_receipt_shows_no_metrics_and_no_cost(tmp_path, capsys):
    """A trial that died before writing gt-run.json still owes us a row."""
    _progress(
        tmp_path,
        [
            _task("extract-elf"),
            _task("write-compressor", reward=None, graded=False,
                  state="infrastructure_failed", error="harbor_trial_failed"),
        ],
    )
    _gt_run(tmp_path, "extract-elf")
    manifest = _route_manifest(tmp_path / "route.json")

    rows = {row["task"]: row for row in collect_rows([tmp_path])}
    assert rows["write-compressor"]["has_metrics"] is False
    assert rows["write-compressor"]["input_tokens"] is None

    exit_code = main([str(tmp_path), "--rates", str(manifest)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "write-compressor" in out
    assert "harbor_trial_failed" in out
    # No tokens means no derivable cost; a dash, never a zero dollar figure.
    line = next(row for row in out.splitlines() if row.startswith("write-compressor"))
    assert "0.00" not in line
    assert "no gt-run.json" in out
    assert "officially_graded=1" in out


def test_report_refuses_when_no_progress_receipt_exists(tmp_path, capsys):
    manifest = _route_manifest(tmp_path / "route.json")
    exit_code = main([str(tmp_path), "--rates", str(manifest)])
    assert exit_code != 0
    assert "gt.benchmark_progress.v1" in capsys.readouterr().err


def test_markdown_flag_emits_a_markdown_table(tmp_path, capsys):
    _two_task_tree(tmp_path)
    manifest = _route_manifest(tmp_path / "route.json")
    exit_code = main([str(tmp_path), "--rates", str(manifest), "--markdown"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "| task |" in out
    assert "|---" in out
    assert "| extract-elf |" in out


# --- baseline pairing ------------------------------------------------------

_BASELINE_SUMMARY = """# MINISWE GT-OFF BASELINE (Terminal-Bench 2.0) - FROZEN

**Result: 2/3 solved.**

## Result table

| task | solved | reward / error | prompt tok | comp tok | calls |
|---|---|---|---|---|---|
| extract-elf | yes | {"reward": 1.0} | 5,561,759 | 4,842,368 | 42 |
| fix-git | yes | {"reward": 1.0} | 88,401 | 81,280 | 13 |
| caffe-cifar-10 | no | {"reward": 0.0} | 2,857,053 | 2,821,120 | 86 |
"""


def test_parse_baseline_summary_reads_solved_calls_and_tokens():
    baseline = parse_baseline_summary(_BASELINE_SUMMARY)
    assert set(baseline) == {"extract-elf", "fix-git", "caffe-cifar-10"}
    assert baseline["extract-elf"]["solved"] is True
    assert baseline["extract-elf"]["calls"] == 42
    assert baseline["extract-elf"]["prompt_tokens"] == 5_561_759
    assert baseline["extract-elf"]["completion_tokens"] == 4_842_368
    assert baseline["extract-elf"]["reward"] == 1.0
    assert baseline["caffe-cifar-10"]["solved"] is False


def test_parse_baseline_summary_ignores_the_header_and_separator_rows():
    baseline = parse_baseline_summary(_BASELINE_SUMMARY)
    assert "task" not in baseline
    assert all(not key.startswith("-") for key in baseline)


def test_baseline_pairing_adds_columns_and_a_paired_footer(tmp_path, capsys):
    _two_task_tree(tmp_path)
    manifest = _route_manifest(tmp_path / "route.json")
    summary = tmp_path / "SUMMARY.md"
    summary.write_text(_BASELINE_SUMMARY, encoding="utf-8")

    exit_code = main([str(tmp_path), "--rates", str(manifest), "--baseline", str(summary)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "base" in out
    # Only the two tasks present on both sides are paired; caffe-cifar-10 was
    # not run here and must not inflate either side of the comparison.
    assert "paired 2" in out
    assert "GT-off solved 2" in out
    assert "GT-on solved 1" in out


def test_baseline_columns_render_for_a_task_missing_from_the_baseline(tmp_path, capsys):
    _progress(tmp_path, [_task("brand-new-task")])
    _gt_run(tmp_path, "brand-new-task")
    manifest = _route_manifest(tmp_path / "route.json")
    summary = tmp_path / "SUMMARY.md"
    summary.write_text(_BASELINE_SUMMARY, encoding="utf-8")

    exit_code = main([str(tmp_path), "--rates", str(manifest), "--baseline", str(summary)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "brand-new-task" in out
    assert "paired 0" in out


def test_format_report_is_pure_and_takes_explicit_rates(tmp_path):
    _two_task_tree(tmp_path)
    rows = collect_rows([tmp_path])
    text = format_report(rows, prompt_price=_PROMPT_USD, completion_price=_COMPLETION_USD)
    assert "extract-elf" in text
    assert "total_cost is 0.0 by design" in text


# --- the model each row was run under --------------------------------------
# collect_rows has always recorded the model and the table never showed it. A
# report over roots that span two models is exactly where that silence lies.


def test_the_model_column_is_rendered(tmp_path, capsys):
    _two_task_tree(tmp_path)
    manifest = _route_manifest(tmp_path / "route.json")

    exit_code = main([str(tmp_path), "--rates", str(manifest)])

    out = capsys.readouterr().out
    assert exit_code == 0
    header = out.splitlines()[0]
    assert "model" in header
    assert out.count("deepseek/deepseek-v4-flash-0731") >= 2


def test_rows_from_roots_that_span_models_each_name_their_own(tmp_path, capsys):
    left, right = tmp_path / "left", tmp_path / "right"
    _progress(left, [_task("extract-elf")], model="deepseek/deepseek-v4-flash-0731")
    _gt_run(left, "extract-elf")
    _progress(right, [_task("fix-git")], model="deepseek/deepseek-v4-pro")
    _gt_run(right, "fix-git")
    manifest = _route_manifest(tmp_path / "route.json")

    exit_code = main([str(left), str(right), "--rates", str(manifest), "--markdown"])

    out = capsys.readouterr().out
    assert exit_code == 0
    elf = next(line for line in out.splitlines() if line.startswith("| extract-elf "))
    git = next(line for line in out.splitlines() if line.startswith("| fix-git "))
    assert "deepseek/deepseek-v4-flash-0731" in elf
    assert "deepseek/deepseek-v4-pro" in git


def test_a_progress_receipt_without_a_model_renders_a_dash_not_a_blank(tmp_path):
    _write(
        tmp_path / "progress.json",
        {
            "schema": "gt.benchmark_progress.v1",
            "benchmark_suite": "terminal-bench-2",
            "tasks": [_task("extract-elf")],
        },
    )
    _gt_run(tmp_path, "extract-elf")

    text = format_report(
        collect_rows([tmp_path]),
        prompt_price=_PROMPT_USD,
        completion_price=_COMPLETION_USD,
        markdown=True,
    )

    row = next(line for line in text.splitlines() if line.startswith("| extract-elf "))
    assert "|  |" not in row
    assert "| - |" in row


# --- the baseline table is read by header, not by position ------------------
# Positional parsing reads whatever the sixth column happens to be. A SUMMARY
# with its columns in another order would have been parsed as calls=reward.

_REORDERED_SUMMARY = """# MINISWE GT-OFF BASELINE (Terminal-Bench 2.0) - FROZEN

| task | calls | solved | comp tok | prompt tok | reward / error |
|---|---|---|---|---|---|
| extract-elf | 42 | yes | 4,842,368 | 5,561,759 | {"reward": 1.0} |
| caffe-cifar-10 | 86 | no | 2,821,120 | 2,857,053 | {"reward": 0.0} |
"""

_HEADERLESS_SUMMARY = """# Something else entirely

| task | solved | calls |
|---|---|---|
| extract-elf | yes | 42 |
"""


def test_parse_baseline_summary_locates_columns_by_header_name():
    baseline = parse_baseline_summary(_REORDERED_SUMMARY)

    assert set(baseline) == {"extract-elf", "caffe-cifar-10"}
    assert baseline["extract-elf"]["calls"] == 42
    assert baseline["extract-elf"]["prompt_tokens"] == 5_561_759
    assert baseline["extract-elf"]["completion_tokens"] == 4_842_368
    assert baseline["extract-elf"]["reward"] == 1.0
    assert baseline["caffe-cifar-10"]["solved"] is False


def test_parse_baseline_summary_refuses_a_table_missing_required_headers():
    with pytest.raises(BaselineUnreadable) as excinfo:
        parse_baseline_summary(_HEADERLESS_SUMMARY)

    message = str(excinfo.value)
    assert "prompt tok" in message and "comp tok" in message


def test_an_unparseable_baseline_fails_the_cli_instead_of_pairing_nothing(tmp_path, capsys):
    """A silently empty baseline reads as 'GT-off solved 0', which is a lie."""
    _two_task_tree(tmp_path)
    manifest = _route_manifest(tmp_path / "route.json")
    summary = tmp_path / "SUMMARY.md"
    summary.write_text(_HEADERLESS_SUMMARY, encoding="utf-8")

    exit_code = main([str(tmp_path), "--rates", str(manifest), "--baseline", str(summary)])

    captured = capsys.readouterr()
    assert exit_code != 0
    assert "paired" not in captured.out
    assert "header" in captured.err.lower()


# --- the walk is bounded to the subtrees the harness itself writes ----------
# H-2: a TB2 task directory holds the task's whole repository checkout. An
# unbounded rglob walked ~850 JSON files per task and, worse, joined on
# task_id with first-in-sorted-order-wins: a planted
# `.venv/lib/site-packages/harness/gt-run.json` sorts ahead of `agent/` and
# was reported as that task's turns. The walk now uses the same harness-owned
# globs as verify_run_receipts._HARNESS_GLOBS / _TRIAL_GLOBS and
# gt_audit._MINISWE_REPORT_GLOBS, so the checkout is never entered at all.


def _checkout_noise(task_dir: Path, *, count: int = 40) -> list[Path]:
    """JSON that belongs to the task's own checkout, not to this run."""
    return [
        _write(
            task_dir / ".venv" / "lib" / "site-packages" / f"pkg{index}" / "meta.json",
            {"name": f"pkg{index}"},
        )
        for index in range(count)
    ]


def _decoy_receipt(task_dir: Path, task_id: str) -> Path:
    """A look-alike receipt vendored inside the checkout, sorting before agent/."""
    return _write(
        task_dir / ".venv" / "lib" / "site-packages" / "harness" / _GT_RUN_NAME,
        {
            "schema": "gt.run_receipt.v1",
            "task_id": task_id,
            "agent_turn_calls": 999,
            "provider_calls": 999,
            "provider_failed_calls": 999,
            "input_tokens": 9,
            "cached_tokens": 9,
            "output_tokens": 9,
        },
    )


def _record_reads(monkeypatch) -> list[Path]:
    """Every file collect_rows opens, in the order it opened them."""
    opened: list[Path] = []
    original = tb2_report._read_json

    def recording(path):
        opened.append(Path(path))
        return original(path)

    monkeypatch.setattr(tb2_report, "_read_json", recording)
    return opened


def test_a_look_alike_receipt_inside_the_checkout_is_never_read(tmp_path, monkeypatch):
    _progress(tmp_path, [_task("extract-elf")])
    _gt_run(tmp_path, "extract-elf")
    task_dir = tmp_path / "extract-elf"
    decoy = _decoy_receipt(task_dir, "extract-elf")
    noise = _checkout_noise(task_dir)
    # The decoy only matters because it wins the old sort; assert that it does.
    assert decoy < task_dir / "agent" / _GT_RUN_NAME

    opened = _record_reads(monkeypatch)
    rows = {row["task"]: row for row in collect_rows([tmp_path])}

    assert rows["extract-elf"]["turns"] == 42
    assert rows["extract-elf"]["calls"] == 44
    assert decoy not in opened
    assert [path for path in noise if path in opened] == []


def test_the_checkout_is_not_walked_at_all(tmp_path, monkeypatch):
    """847 JSON files per task were parsed to find the two that are ours."""
    _progress(tmp_path, [_task("extract-elf")])
    _gt_run(tmp_path, "extract-elf")
    _checkout_noise(tmp_path / "extract-elf", count=200)

    opened = _record_reads(monkeypatch)
    collect_rows([tmp_path])

    # progress.json plus the one receipt; nothing from inside the checkout.
    assert len(opened) <= 4, [str(path) for path in opened]


def test_two_harness_owned_receipts_prefer_agent_and_warn(tmp_path):
    """Both locations are ours, so neither can be ignored silently."""
    _progress(tmp_path, [_task("extract-elf")])
    _gt_run(tmp_path, "extract-elf")
    # The trial directory's own top level is globbed before agent/.
    stray = _write(
        tmp_path / "extract-elf" / _GT_RUN_NAME,
        {
            "schema": "gt.run_receipt.v1",
            "task_id": "extract-elf",
            "agent_turn_calls": 7,
            "provider_calls": 7,
            "input_tokens": 1,
            "output_tokens": 1,
        },
    )

    warnings: list[str] = []
    rows = {row["task"]: row for row in collect_rows([tmp_path], warn=warnings.append)}

    assert rows["extract-elf"]["turns"] == 42
    assert any("extract-elf" in text and str(stray) in text for text in warnings)


def test_a_duplicate_receipt_warning_reaches_stderr(tmp_path, capsys):
    _two_task_tree(tmp_path)
    _write(
        tmp_path / "extract-elf" / _GT_RUN_NAME,
        {"schema": "gt.run_receipt.v1", "task_id": "extract-elf", "agent_turn_calls": 7},
    )
    manifest = _route_manifest(tmp_path / "route.json")

    exit_code = main([str(tmp_path), "--rates", str(manifest)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "extract-elf" in captured.err
    line = next(row for row in captured.out.splitlines() if row.startswith("extract-elf"))
    assert "42" in line


def test_a_pier_trial_layout_is_joined(tmp_path):
    """`<job>/<task>__<hash>/agent/` with the progress receipt under progress/."""
    job = tmp_path / "terminal-bench"
    _write(
        job / "progress" / "progress.json",
        {
            "schema": "gt.benchmark_progress.v1",
            "benchmark_suite": "terminal-bench-2",
            "model": "deepseek/deepseek-v4-flash-0731",
            "tasks": [_task("extract-elf")],
        },
    )
    _write(
        job / "extract-elf__deadbeef" / "agent" / _GT_RUN_NAME,
        {
            "schema": "gt.run_receipt.v1",
            "task_id": "extract-elf",
            "agent_turn_calls": 11,
            "provider_calls": 11,
            "input_tokens": 5,
            "output_tokens": 5,
        },
    )
    _decoy_receipt(job / "extract-elf__deadbeef", "extract-elf")

    rows = {row["task"]: row for row in collect_rows([tmp_path])}

    assert rows["extract-elf"]["turns"] == 11


def test_the_harness_owned_locations_match_the_sibling_walkers():
    """One list of harness-owned locations across the modules that walk them.

    verify_run_receipts, gt_audit and diagnose_benchmark_run each bound their
    own walk the same way. A new artifact location added to the receipt
    verifier and not here would put this report back on a location it cannot
    see - so the subset check fails, naming the location to add.
    """
    from scripts import verify_run_receipts

    # This report searches one trial level deeper (a downloaded attestation
    # bundle nests `<job>/<artifact>/<task>__<hash>/`), so the sibling's shapes
    # must be covered here, not equalled.
    assert set(verify_run_receipts._TRIAL_GLOBS) <= set(tb2_report._TRIAL_GLOBS)
    missing = set(verify_run_receipts._HARNESS_GLOBS) - set(tb2_report._HARNESS_GLOBS)
    assert missing == set(), sorted(missing)


def test_a_nested_attestation_bundle_is_joined(tmp_path):
    """`<job>/<artifact>/<task>__<hash>/agent/` - the downloaded bundle shape.

    A trial this report cannot reach prints "-" for turns, calls and tokens
    that are sitting in the artifact, which reads as a trial that died.
    """
    trial = tmp_path / "gt-harness-job-1" / "swelive-gt-harness-1-extract-elf" / "extract-elf__8VJiMwD"
    _write(
        tmp_path / "gt-harness-job-1" / "progress.json",
        {
            "schema": "gt.benchmark_progress.v1",
            "benchmark_suite": "terminal-bench-2",
            "model": "deepseek/deepseek-v4-flash-0731",
            "tasks": [_task("extract-elf")],
        },
    )
    _write(
        trial / "agent" / _GT_RUN_NAME,
        {
            "schema": "gt.run_receipt.v1",
            "task_id": "extract-elf",
            "agent_turn_calls": 73,
            "provider_calls": 73,
            "input_tokens": 5,
            "output_tokens": 5,
        },
    )
    _decoy_receipt(trial, "extract-elf")

    rows = {row["task"]: row for row in collect_rows([tmp_path])}

    assert rows["extract-elf"]["turns"] == 73


def test_a_checkout_directory_that_merely_spells_a_trial_name_is_not_one(tmp_path):
    """The trial guard is the name AND an owned `agent/`, at every depth."""
    _progress(tmp_path, [_task("extract-elf")])
    _gt_run(tmp_path, "extract-elf")
    # A vendored package inside the checkout whose name carries `__` and which
    # is two levels below the task dir - reachable by the deepest trial glob.
    planted = _write(
        tmp_path / "extract-elf" / "src" / "pkg__fixtures" / _GT_RUN_NAME,
        {"schema": "gt.run_receipt.v1", "task_id": "extract-elf", "agent_turn_calls": 999},
    )

    rows = {row["task"]: row for row in collect_rows([tmp_path])}

    assert rows["extract-elf"]["turns"] == 42
    assert planted.exists()


def test_a_checkout_directory_inside_a_trial_is_not_a_second_trial(tmp_path, monkeypatch):
    """M-3: `<trial>/sub__x/agent/` is a vendored tree, not another trial.

    Searching every trial depth at once reaches one level INSIDE a resolved
    trial, and a checkout directory that happens to carry a `__` and own an
    `agent/` then has its JSON read as this task's receipts. The depths are
    tried in order and nothing below a trial is ever a trial - the same rule
    verify_run_receipts.find_trials applies; the two must agree.
    """
    _progress(tmp_path, [_task("extract-elf")])
    trial = tmp_path / "extract-elf__8VJiMwD"
    _write(
        trial / "agent" / _GT_RUN_NAME,
        {
            "schema": "gt.run_receipt.v1",
            "task_id": "extract-elf",
            "agent_turn_calls": 42,
            "provider_calls": 44,
            "input_tokens": 1,
            "output_tokens": 1,
        },
    )
    planted = _write(
        trial / "sub__x" / "agent" / _GT_RUN_NAME,
        {"schema": "gt.run_receipt.v1", "task_id": "extract-elf", "agent_turn_calls": 999},
    )
    # A progress receipt inside the checkout must not be reachable either.
    decoy_progress = _write(
        trial / "sub__x" / "progress.json",
        {
            "schema": "gt.benchmark_progress.v1",
            "model": "vendored/look-alike",
            "tasks": [_task("not-a-real-task")],
        },
    )

    opened = _record_reads(monkeypatch)
    warnings: list[str] = []
    rows = {row["task"]: row for row in collect_rows([tmp_path], warn=warnings.append)}

    assert set(rows) == {"extract-elf"}
    assert rows["extract-elf"]["turns"] == 42
    assert planted not in opened
    assert decoy_progress not in opened
    # Nothing was ambiguous, so nothing may be warned about either.
    assert warnings == []


# --- a root that is ITSELF a trial must not expand into its checkout --------
# M-1 (round 5): `_trial_roots` unconditionally added root's direct child
# directories as search roots. Pointed at one trial directory - which is what
# every per-task workflow step does - `<trial>/checkout/` became a search root,
# so `<trial>/checkout/agent/progress.json` was read as a progress receipt and
# `<trial>/checkout/agent/gt-run.json` as a receipt. The checkout is the task's
# own repository: a fixture progress document in it fabricated a graded, solved
# row that the footer counted.


def _trial_with_a_checkout(root: Path) -> tuple[Path, Path]:
    """`<trial>/` holding the real receipts, plus the task's own checkout."""
    trial = root / "extract-elf__8VJiMwD"
    _write(
        trial / "progress" / "progress.json",
        {
            "schema": "gt.benchmark_progress.v1",
            "benchmark_suite": "terminal-bench-2",
            "model": "deepseek/deepseek-v4-flash-0731",
            "tasks": [_task("extract-elf")],
        },
    )
    _write(
        trial / "agent" / _GT_RUN_NAME,
        {
            "schema": "gt.run_receipt.v1",
            "task_id": "extract-elf",
            "agent_turn_calls": 42,
            "provider_calls": 44,
            "input_tokens": 1,
            "output_tokens": 1,
        },
    )
    checkout = trial / "checkout"
    _write(
        checkout / "agent" / "progress.json",
        {
            "schema": "gt.benchmark_progress.v1",
            "model": "vendored/look-alike",
            "tasks": [_task("DECOY-TASK")],
        },
    )
    _write(
        checkout / "agent" / _GT_RUN_NAME,
        {"schema": "gt.run_receipt.v1", "task_id": "extract-elf", "agent_turn_calls": 999},
    )
    # The fabricated row only matters because it carries metrics: read, it puts
    # 999,999 prompt tokens of the task's own fixture tree into the cost total.
    _write(
        checkout / "agent" / "gt-state" / "0000" / _GT_RUN_NAME,
        {
            "schema": "gt.run_receipt.v1",
            "task_id": "DECOY-TASK",
            "agent_turn_calls": 999,
            "provider_calls": 999,
            "input_tokens": 999_999,
            "output_tokens": 999_999,
        },
    )
    return trial, checkout


def test_a_root_that_is_itself_a_trial_never_searches_its_checkout(tmp_path, monkeypatch):
    """The per-task step points the report at one trial directory."""
    trial, checkout = _trial_with_a_checkout(tmp_path)

    opened = _record_reads(monkeypatch)
    warnings: list[str] = []
    rows = collect_rows([trial], warn=warnings.append)

    assert [row["task"] for row in rows] == ["extract-elf"]
    assert rows[0]["turns"] == 42
    assert rows[0]["model"] == "deepseek/deepseek-v4-flash-0731"
    assert [str(path) for path in opened if checkout in path.parents] == []
    assert warnings == []


def test_a_fabricated_checkout_row_is_not_counted_as_graded_or_solved(tmp_path, capsys):
    """The footer is the number that gets quoted; a decoy row inflated both."""
    trial, _checkout = _trial_with_a_checkout(tmp_path)
    manifest = _route_manifest(tmp_path / "route.json")

    exit_code = main([str(trial), "--rates", str(manifest)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "DECOY-TASK" not in captured.out
    assert "tasks=1  officially_graded=1  solved=1" in captured.out


def test_the_trial_roots_of_a_trial_are_only_its_own_harness_subtrees(tmp_path):
    trial, checkout = _trial_with_a_checkout(tmp_path)

    roots = tb2_report._trial_roots(trial)

    assert roots == [trial]
    assert checkout not in roots


def test_the_other_artifact_layouts_still_resolve(tmp_path):
    """Job-dir, flat and the three-level attestation bundle, after the guard."""
    def _plant(trial: Path, turns: int) -> None:
        _write(
            trial / "agent" / _GT_RUN_NAME,
            {
                "schema": "gt.run_receipt.v1",
                "task_id": "extract-elf",
                "agent_turn_calls": turns,
                "provider_calls": turns,
                "input_tokens": 1,
                "output_tokens": 1,
            },
        )

    receipt = {
        "schema": "gt.benchmark_progress.v1",
        "benchmark_suite": "terminal-bench-2",
        "model": "deepseek/deepseek-v4-flash-0731",
        "tasks": [_task("extract-elf")],
    }

    flat = tmp_path / "flat"
    _write(flat / "progress.json", receipt)
    _plant(flat / "extract-elf", 11)

    job = tmp_path / "job"
    _write(job / "progress" / "progress.json", receipt)
    _plant(job / "extract-elf__8VJiMwD", 22)

    bundle = tmp_path / "bundle" / "gt-harness-job-1"
    _write(bundle / "progress.json", receipt)
    _plant(bundle / "swelive-gt-harness-1-extract-elf" / "extract-elf__8VJiMwD", 33)

    assert [row["turns"] for row in collect_rows([flat])] == [11]
    assert [row["turns"] for row in collect_rows([job])] == [22]
    assert [row["turns"] for row in collect_rows([tmp_path / "bundle"])] == [33]


# --- an unreadable --baseline file is an input fault, not a traceback -------
# L-4 (round 5): every other input fault in main returns 2 with a message.
# `Path(args.baseline).read_text()` was reached outside any guard, so a
# baseline that is missing or is not UTF-8 ended the run in a traceback - and
# a traceback in a workflow step reads as the harness having crashed.


def test_a_missing_baseline_file_fails_the_cli_with_an_exit_code(tmp_path, capsys):
    _two_task_tree(tmp_path)
    manifest = _route_manifest(tmp_path / "route.json")

    exit_code = main(
        [str(tmp_path), "--rates", str(manifest), "--baseline", str(tmp_path / "nope.md")]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "nope.md" in captured.err
    assert "Traceback" not in captured.err


def test_a_baseline_that_is_not_utf8_fails_the_cli_with_an_exit_code(tmp_path, capsys):
    _two_task_tree(tmp_path)
    manifest = _route_manifest(tmp_path / "route.json")
    baseline = tmp_path / "SUMMARY.md"
    # A latin-1 byte: the frozen summaries are copied by hand often enough.
    baseline.write_bytes(b"| task | solved |\n| caf\xe9 | yes |\n")

    exit_code = main(
        [str(tmp_path), "--rates", str(manifest), "--baseline", str(baseline)]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert str(baseline) in captured.err
    assert "Traceback" not in captured.err


# --- M-1 (round 6): the ancestor walk never ran for a relative root ---------
# `while parent != parent.parent` cannot enter for `Path(".")`, whose parent IS
# itself, so `_inside_a_trial` answered False for every candidate under a
# relative root. `python -m scripts.tb2_report .` from inside a trial - the
# shape of every "look at this one task" invocation - then made `./checkout/`
# a search root and read the task's own repository: a fixture progress document
# produced a graded, solved DECOY-TASK row and a fixture receipt put 999,999
# tokens into the cost total. Both spellings are asserted here: the relative
# one is the defect, the absolute one is the guard that must not regress while
# it is fixed.


def _read_under(opened: list[Path], checkout: Path) -> list[str]:
    """Every recorded read that landed inside `checkout`, however spelled."""
    resolved = checkout.resolve()
    return [
        str(path)
        for path in opened
        if resolved == path.resolve() or resolved in path.resolve().parents
    ]


def test_a_relative_root_that_is_itself_a_trial_never_searches_its_checkout(
    tmp_path, monkeypatch
):
    trial, checkout = _trial_with_a_checkout(tmp_path)
    monkeypatch.chdir(trial)

    opened = _record_reads(monkeypatch)
    warnings: list[str] = []
    rows = collect_rows([Path(".")], warn=warnings.append)

    assert [row["task"] for row in rows] == ["extract-elf"]
    assert rows[0]["turns"] == 42
    assert rows[0]["input_tokens"] == 1
    assert _read_under(opened, checkout) == []
    assert warnings == []


def test_an_absolute_root_that_is_itself_a_trial_never_searches_its_checkout(
    tmp_path, monkeypatch
):
    trial, checkout = _trial_with_a_checkout(tmp_path)

    opened = _record_reads(monkeypatch)
    warnings: list[str] = []
    rows = collect_rows([trial.resolve()], warn=warnings.append)

    assert [row["task"] for row in rows] == ["extract-elf"]
    assert rows[0]["turns"] == 42
    assert rows[0]["input_tokens"] == 1
    assert _read_under(opened, checkout) == []
    assert warnings == []


def test_a_relative_root_does_not_fabricate_a_graded_row_or_a_cost(
    tmp_path, monkeypatch, capsys
):
    """The footer and the cost are the numbers that get quoted out of this."""
    trial, _checkout = _trial_with_a_checkout(tmp_path)
    manifest = _route_manifest(tmp_path / "route.json")
    monkeypatch.chdir(trial)

    exit_code = main([".", "--rates", str(manifest)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "DECOY-TASK" not in captured.out
    assert "999,999" not in captured.out
    assert "tasks=1  officially_graded=1  solved=1" in captured.out
    assert "input=1  cached=0" in captured.out


def test_the_trial_roots_of_a_relative_trial_root_are_only_its_own(
    tmp_path, monkeypatch
):
    trial, _checkout = _trial_with_a_checkout(tmp_path)
    monkeypatch.chdir(trial)

    assert tb2_report._trial_roots(Path(".")) == [Path(".")]
    assert tb2_report._inside_a_trial(Path("."), Path("checkout")) is True


# --- M-3 (round 6): a trial-only receipt fell out of the join ---------------
# A `gt-run.json` that carries no `task_id` fell back to the trial DIRECTORY
# name, which under Pier is `<task>__<hash>` - a name no progress row ever
# carries. The metrics were collected and then joined to nothing: the row
# printed "-" for turns, calls and tokens, and the footer said
# "$0.00 over 0 task(s)" for a run that had just spent real tokens.


def test_a_trial_only_receipt_without_a_task_id_joins_its_progress_row(tmp_path):
    """The hash is separated at the LAST `__`, so a SWE-bench id stays whole."""
    job = tmp_path / "terminal-bench"
    _write(
        job / "progress" / "progress.json",
        {
            "schema": "gt.benchmark_progress.v1",
            "benchmark_suite": "terminal-bench-2",
            "model": "deepseek/deepseek-v4-flash-0731",
            "tasks": [_task("amoffat__sh-744")],
        },
    )
    _write(
        job / "amoffat__sh-744__8VJiMwD" / "agent" / _GT_RUN_NAME,
        {
            "schema": "gt.run_receipt.v1",
            "agent_turn_calls": 11,
            "provider_calls": 12,
            "input_tokens": 1_000_000,
            "output_tokens": 100_000,
        },
    )

    rows = collect_rows([tmp_path])

    assert [row["task"] for row in rows] == ["amoffat__sh-744"]
    assert rows[0]["has_metrics"] is True
    assert rows[0]["turns"] == 11
    assert rows[0]["input_tokens"] == 1_000_000


def test_a_trial_only_receipts_tokens_reach_the_cost(tmp_path, capsys):
    job = tmp_path / "terminal-bench"
    _write(
        job / "progress" / "progress.json",
        {
            "schema": "gt.benchmark_progress.v1",
            "benchmark_suite": "terminal-bench-2",
            "model": "deepseek/deepseek-v4-flash-0731",
            "tasks": [_task("extract-elf")],
        },
    )
    _write(
        job / "extract-elf__8VJiMwD" / "agent" / _GT_RUN_NAME,
        {
            "schema": "gt.run_receipt.v1",
            "agent_turn_calls": 11,
            "input_tokens": 1_000_000,
            "output_tokens": 100_000,
        },
    )
    manifest = _route_manifest(tmp_path / "route.json")

    exit_code = main([str(tmp_path), "--rates", str(manifest)])

    captured = capsys.readouterr()
    assert exit_code == 0
    # 1,000,000 * 1e-6 + 100,000 * 2e-6
    assert "cost $1.20 over 1 task(s)" in captured.out
    assert f"no {_GT_RUN_NAME} for" not in captured.out


def test_a_flat_task_directory_without_a_task_id_still_joins(tmp_path):
    """`<root>/<task>/agent/` carries no `__`, so the whole name is the task."""
    _progress(tmp_path, [_task("extract-elf")])
    _write(
        tmp_path / "extract-elf" / "agent" / _GT_RUN_NAME,
        {"schema": "gt.run_receipt.v1", "agent_turn_calls": 7},
    )

    rows = collect_rows([tmp_path])

    assert [row["turns"] for row in rows] == [7]


# --- L-5 (round 6): three copies of one rule, and they must agree ----------
# tb2_report, verify_run_receipts and diagnose_benchmark_run each own a
# private `_inside_a_trial`. They are deliberately NOT imported from one
# another (two are gates, one is a reporting tool), which is exactly why the
# rule drifted into two incompatible versions: an ancestor walk here and a
# look-at-the-parent's-name rule there, so the same tree was read one way by
# the report and another by the receipt gate. One table of synthetic trees,
# one expected verdict per row, and every module answers it.


def _agreement_trees(root: Path) -> list[tuple[str, Path, Path, bool]]:
    """`(label, root, candidate, inside a trial?)` over the real layouts.

    The rule: a candidate is inside a trial when some ancestor between it and
    the root - the root included - owns an `agent/`.
    """
    cases: list[tuple[str, Path, Path, bool]] = []

    # Flat: `<root>/<task>/agent/`, the task's checkout below it.
    flat = root / "flat"
    (flat / "extract-elf" / "agent").mkdir(parents=True)
    (flat / "extract-elf" / "src" / "pkg__fixtures" / "agent").mkdir(parents=True)
    cases.append(("flat root", flat, flat, False))
    cases.append(("flat task dir", flat, flat / "extract-elf", False))
    cases.append(
        ("flat checkout", flat, flat / "extract-elf" / "src" / "pkg__fixtures", True)
    )

    # Pier, two levels down, under a JOB directory whose own name carries `__`.
    job = root / "job"
    (job / "gt-harness__run-1" / "extract-elf__8VJiMwD" / "agent").mkdir(parents=True)
    (job / "gt-harness__run-1" / "extract-elf__8VJiMwD" / "sub__x" / "agent").mkdir(
        parents=True
    )
    cases.append(("job dir named with __", job, job / "gt-harness__run-1", False))
    cases.append(
        ("pier trial", job, job / "gt-harness__run-1" / "extract-elf__8VJiMwD", False)
    )
    cases.append(
        (
            "pier checkout",
            job,
            job / "gt-harness__run-1" / "extract-elf__8VJiMwD" / "sub__x",
            True,
        )
    )

    # A downloaded attestation bundle nests one level deeper still.
    bundle = root / "bundle"
    deep = bundle / "gt-harness-job-1" / "swelive-1-extract-elf" / "extract-elf__8VJiMwD"
    (deep / "agent").mkdir(parents=True)
    (deep / "checkout" / "agent").mkdir(parents=True)
    cases.append(("attestation artifact dir", bundle, deep.parent, False))
    cases.append(("attestation trial", bundle, deep, False))
    cases.append(("attestation checkout", bundle, deep / "checkout", True))

    # The root IS the trial: everything below it is the task's own repository.
    trial = root / "extract-elf__8VJiMwD"
    (trial / "agent").mkdir(parents=True)
    (trial / "checkout" / "agent").mkdir(parents=True)
    cases.append(("trial root", trial, trial, False))
    cases.append(("trial root checkout", trial, trial / "checkout", True))
    cases.append(("trial root nested", trial, trial / "checkout" / "deeper", True))

    # L-3 (round 7): a candidate that is not under the root AT ALL. Both sides
    # are resolved before they are compared, so a symlink under a trial that
    # points outside the root arrives here exactly like this - already
    # resolved out from under it. It is not a trial OF THIS ROOT and it is not
    # searchable either: "not inside a trial" would make it a search root and
    # another project's receipts this run's.
    escape = root / "escape"
    (escape / "root" / "extract-elf__8VJiMwD" / "agent").mkdir(parents=True)
    (escape / "outside" / "vendored" / "agent").mkdir(parents=True)
    cases.append(
        ("candidate outside the root", escape / "root", escape / "outside" / "vendored", True)
    )
    cases.append(("candidate beside the root", escape / "root", escape / "outside", True))
    cases.append(("candidate above the root", escape / "root", escape, True))

    return cases


def test_the_three_inside_a_trial_walkers_implement_one_rule(tmp_path, monkeypatch):
    from scripts import diagnose_benchmark_run, verify_run_receipts

    walkers = {
        "scripts.tb2_report": tb2_report._inside_a_trial,
        "scripts.verify_run_receipts": verify_run_receipts._inside_a_trial,
        "scripts.diagnose_benchmark_run": diagnose_benchmark_run._inside_a_trial,
    }

    cases = _agreement_trees(tmp_path)
    # The relative spelling of the trial-root case: `Path(".").parent` IS
    # `Path(".")`, which is what silently emptied the walk.
    monkeypatch.chdir(tmp_path / "extract-elf__8VJiMwD")
    cases.append(("relative '.' root", Path("."), Path("checkout"), True))
    cases.append(("relative '.' root itself", Path("."), Path("."), False))

    wrong: list[str] = []
    for label, root, candidate, expected in cases:
        for name, walker in walkers.items():
            verdict = walker(root, candidate)
            if verdict is not expected:
                wrong.append(
                    f"{name} disagrees on {label}: "
                    f"_inside_a_trial({root!s}, {candidate!s}) == {verdict}, "
                    f"expected {expected}"
                )

    assert wrong == [], (
        "the three _inside_a_trial copies must implement the identical "
        "ancestor rule (inside iff some ancestor between the candidate and "
        "the resolved root, root included, owns an agent/):\n" + "\n".join(wrong)
    )


# --- round 7, NOTE: a non-finite number is not a measurement ------------------
# json.dumps writes bare NaN/Infinity (it is Python's own default) and
# json.loads reads them back as floats, so a receipt can carry one. _num let
# them straight through: the row printed "nan", every cohort total that summed
# the column became nan, and the cost column printed "nan" - a number-shaped
# value that no reader would take as "this was not measured". Non-finite is
# unmeasured, which this report already renders as "-" and excludes from
# totals.


def _nan_tree(root: Path) -> Path:
    """The two-task tree with one receipt's input_tokens recorded as NaN."""
    _progress(root, [_task("extract-elf"), _task("fix-git")])
    _gt_run(root, "extract-elf", input_tokens=float("nan"))
    _gt_run(root, "fix-git", input_tokens=200_000, cached_tokens=0, output_tokens=20_000)
    return root


def test_a_nan_token_count_is_read_as_unmeasured(tmp_path):
    rows = {row["task"]: row for row in collect_rows([str(_nan_tree(tmp_path))])}

    assert rows["extract-elf"]["input_tokens"] is None
    assert rows["fix-git"]["input_tokens"] == 200_000


def test_a_nan_token_count_never_reaches_a_cohort_total(tmp_path):
    rows = collect_rows([str(_nan_tree(tmp_path))])

    report = format_report(rows, prompt_price=_PROMPT_USD, completion_price=_COMPLETION_USD)

    assert "nan" not in report.lower()
    # The one good row is still counted in full, and only it.
    assert "input=200,000" in report
    assert "output=120,000" in report


def test_a_nan_token_count_shows_as_a_dash_and_does_not_poison_the_cost(tmp_path):
    rows = collect_rows([str(_nan_tree(tmp_path))])

    report = format_report(rows, prompt_price=_PROMPT_USD, completion_price=_COMPLETION_USD)

    line = next(line for line in report.splitlines() if line.startswith("extract-elf"))
    assert " -" in line
    # input unmeasured, output 100,000 recorded: the cost is the output's alone.
    assert f"{100_000 * _COMPLETION_USD:.2f}" in line


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_no_non_finite_number_survives_into_a_row(tmp_path, literal):
    """Every numeric column goes through _num, so one guard covers them all."""
    _progress(tmp_path, [_task("extract-elf")])
    path = tmp_path / "extract-elf" / "agent" / _GT_RUN_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '{"schema": "gt.run_receipt.v1", "task_id": "extract-elf", '
        f'"agent_turn_calls": {literal}, "provider_calls": {literal}, '
        f'"provider_failed_calls": {literal}, "input_tokens": {literal}, '
        f'"cached_tokens": {literal}, "output_tokens": {literal}}}',
        encoding="utf-8",
    )

    (row,) = collect_rows([str(tmp_path)])

    assert row["has_metrics"] is True
    for key in ("turns", "calls", "provider_failed_calls",
                "input_tokens", "cached_tokens", "output_tokens"):
        assert row[key] is None, key
    report = format_report(rows := [row], prompt_price=_PROMPT_USD,
                           completion_price=_COMPLETION_USD)
    assert "nan" not in report.lower() and "inf" not in report.lower()
    assert rows == [row]


def test_a_non_finite_reward_is_not_counted_as_solved(tmp_path):
    _progress(tmp_path, [_task("extract-elf", reward=float("nan"))])
    _gt_run(tmp_path, "extract-elf")

    (row,) = collect_rows([str(tmp_path)])

    assert row["reward"] is None
    report = format_report([row], prompt_price=_PROMPT_USD, completion_price=_COMPLETION_USD)
    assert "solved=0" in report
    assert "nan" not in report.lower()
