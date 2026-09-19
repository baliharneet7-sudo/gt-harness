from __future__ import annotations

import importlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = (
    ROOT / ".github" / "workflows" / "tb2_miniswe_central.yml",
    ROOT / ".github" / "workflows" / "swebench_live_lite_full.yml",
)
# The three workflows that spend money.  Each one gates the matrix behind the
# same inline funds check, so the behavioural tests below run all three.
PAID_WORKFLOWS = (
    ROOT / ".github" / "workflows" / "tb2_miniswe_central.yml",
    ROOT / ".github" / "workflows" / "swelive_gt_harness_paid.yaml",
    ROOT / ".github" / "workflows" / "deepswe_gt_harness_product_p0731.yaml",
)
# Single source of truth for the benchmark model pin.  Repinning the model on
# 2026-09-17 required editing seven consumers by hand and three dispatches
# bounced from partial repins; the test below makes a partial repin fail here
# instead of in CI.
MODEL_PIN = ROOT / "config" / "benchmark_model.v1.json"


def load_model_pin() -> dict:
    return json.loads(MODEL_PIN.read_text(encoding="utf-8"))


def test_benchmark_workflows_reference_existing_local_scripts() -> None:
    missing: list[str] = []
    pattern = re.compile(r"(?<![\w/])(scripts/[A-Za-z0-9_./-]+(?:\.py|\.sh))")
    for workflow in WORKFLOWS:
        references = set(pattern.findall(workflow.read_text(encoding="utf-8")))
        missing.extend(
            f"{workflow.name}: {reference}"
            for reference in sorted(references)
            if not (ROOT / reference).is_file()
        )
    assert missing == []


def test_live_prediction_builder_imports_and_preserves_expected_denominator(
    tmp_path: Path,
) -> None:
    module_path = ROOT / "scripts" / "swebench" / "build_ll_predictions.py"
    spec = importlib.util.spec_from_file_location("build_ll_predictions", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    artifact = tmp_path / "ll-full-task-a"
    artifact.mkdir()
    patch = "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n"
    (artifact / "agent_patch.diff").write_text(patch, encoding="utf-8")

    records, counts, extra = module.build(
        tmp_path,
        ["task-a", "task-b"],
        "mini-swe-agent + stealth/union-alpha (GT 921bec20)",
    )
    assert [row["instance_id"] for row in records] == ["task-a", "task-b"]
    assert records[0]["model_patch"] == patch
    assert records[1]["model_patch"] == ""
    assert counts["bindmount_agent"] == 1
    assert counts["absent_artifact"] == 1
    assert extra == []
    json.dumps(records)


def test_live_gt_smoke_is_miniswe_official_and_bound_to_the_imported_source() -> None:
    dispatcher = WORKFLOWS[1].read_text(encoding="utf-8")
    workflow = (
        ROOT / ".github" / "workflows" / "swelive_gt_harness_paid.yaml"
    ).read_text(encoding="utf-8")
    manifest = json.loads(
        (ROOT / "config" / "tb2_gt_import_manifest.json").read_text(encoding="utf-8-sig")
    )
    assert manifest["gt_source_commit"] == (
        "921bec20d3dbabd12e4b442936d9259c24cdcc74"
    )
    assert "uses: ./.github/workflows/swelive_gt_harness_paid.yaml" in dispatcher
    assert "secrets: inherit" in dispatcher
    assert "secrets.OPENROUTER_NEW" in workflow
    assert "max-parallel: 20" in workflow
    assert "mini-swe-agent\"))')\" = \"2.4.6\"" in workflow
    assert "openhands" not in workflow.lower()
    assert "python -m swebench.harness.run_evaluation" in workflow
    assert "official evaluator disagrees with Pier verifier" in workflow
    assert 'gt_source_commit != "921bec20d3dbabd12e4b442936d9259c24cdcc74"' in workflow
    assert "uses: ./.github/workflows/deepswe_gt_harness_product.yml" in workflow
    assert "needs: [plan, readiness, readiness_binding]" in workflow


def test_benchmark_model_pin_is_the_single_source_of_truth() -> None:
    pin = load_model_pin()
    model = pin["model"]
    effective = pin["effective_model"]
    tb2_route = ROOT / pin["tb2_route_manifest"]
    swelive_route = ROOT / pin["swelive_route_manifest"]

    assert pin["schema"] == "gt.benchmark_model.v1"
    assert effective == f"openai/{model}"

    # Both routing tables.
    for route_path in (tb2_route, swelive_route):
        route = json.loads(route_path.read_text(encoding="utf-8"))
        assert route["model"] == model, route_path.name
        assert route["provider_routing"]["only"] == pin["provider_only"], route_path.name
        # The served format is requested on every call, not just checked after.
        assert route["provider_routing"]["quantizations"] == [
            route["expected_quantization"]
        ], route_path.name

    # The route manifest referenced by each paid workflow, so a repin that
    # leaves one workflow bound to a retired manifest fails here.
    route_pattern = re.compile(r"config/provider_route_[A-Za-z0-9_.]+\.json")
    tb2 = WORKFLOWS[0].read_text(encoding="utf-8")
    dispatcher = WORKFLOWS[1].read_text(encoding="utf-8")
    swelive = (
        ROOT / ".github" / "workflows" / "swelive_gt_harness_paid.yaml"
    ).read_text(encoding="utf-8")
    attest = (ROOT / "scripts" / "attest_deepswe.py").read_text(encoding="utf-8")
    assert set(route_pattern.findall(tb2)) == {pin["tb2_route_manifest"]}
    assert set(route_pattern.findall(swelive)) == {pin["swelive_route_manifest"]}
    assert Path(pin["swelive_route_manifest"]).name in attest

    # Every model literal in every consumer, including the run-name banners.
    model_pattern = re.compile(r"deepseek/deepseek-[A-Za-z0-9.\-]+")
    for name, text in (
        ("tb2_miniswe_central.yml", tb2),
        ("swebench_live_lite_full.yml", dispatcher),
        ("swelive_gt_harness_paid.yaml", swelive),
        ("attest_deepswe.py", attest),
    ):
        found = set(model_pattern.findall(text))
        assert found <= {model}, f"{name} names a different model: {sorted(found)}"
    assert f"MODEL: {model}" in tb2
    assert f'"model": "{model}"' in tb2
    assert f'"effective_model": "{effective}"' in tb2
    assert f'--effective-model "{effective}"' in tb2
    assert f'"only": {json.dumps(pin["provider_only"])}' in tb2
    assert '"quantizations": ["fp8"]' in tb2
    assert model in dispatcher

    manifest = json.loads(
        (ROOT / "config" / "tb2_gt_import_manifest.json").read_text(encoding="utf-8-sig")
    )
    assert manifest["model"] == model


def test_tb2_planner_excludes_musl_tasks_it_cannot_install_into() -> None:
    # Cohort 35298094010: qemu-alpine-ssh was counted as an infrastructure
    # failure because cryptography, a GT wheel dependency, ships no musl wheel.
    tb2 = WORKFLOWS[0].read_text(encoding="utf-8")
    fallback = json.loads(
        (ROOT / "config" / "tb2_unsupported_tasks.v1.json").read_text(encoding="utf-8")
    )
    assert fallback["schema"] == "gt.tb2_unsupported_tasks.v1"
    assert {row["task"]: row["reason"] for row in fallback["tasks"]} == {
        "qemu-alpine-ssh": "unsupported_platform:musl"
    }
    assert "config/tb2_unsupported_tasks.v1.json" in tb2
    assert '"unsupported_platform:musl"' in tb2
    assert 'environment/Dockerfile' in tb2
    assert '"excluded": excluded' in tb2
    assert "excluded: ${{ steps.plan.outputs.excluded }}" in tb2
    assert "excluded_tasks_json: ${{ needs.plan.outputs.excluded }}" in tb2
    assert '"excluded_count": len(excluded)' in tb2


def test_progress_and_summary_jobs_cannot_outlive_a_failed_plan() -> None:
    # Runs 35256152140, 35257234010, 35257606223, 35257941589 and 35258327432
    # each sat in_progress for hours holding a concurrency slot after `plan`
    # failed, because the polling job carried `if: always()`.
    engine = (
        ROOT / ".github" / "workflows" / "tb2_miniswe_engine.yml"
    ).read_text(encoding="utf-8")
    deepswe = (
        ROOT / ".github" / "workflows" / "deepswe_miniswe_central.yml"
    ).read_text(encoding="utf-8")
    tb2 = WORKFLOWS[0].read_text(encoding="utf-8")

    for name, text in (("engine", engine), ("deepswe", deepswe)):
        progress = text.index("\n  task_progress:")
        following = text.index("uses: ./.github/workflows/task_progress.yml", progress)
        block = text[progress:following]
        directives = [
            line.strip()
            for line in block.splitlines()
            if line.strip().startswith("if:")
        ]
        assert directives == ["if: needs.plan.result == 'success'"], (name, directives)
    # The engine must NOT restate task_progress.yml's default: a call that
    # repeats the default reads as a bound this workflow imposes, and the
    # next person changing the real bound edits the wrong file.
    operative = [
        line
        for line in engine.splitlines()
        if "monitor_timeout_minutes" in line and not line.lstrip().startswith("#")
    ]
    assert operative == []
    progress = (
        ROOT / ".github" / "workflows" / "task_progress.yml"
    ).read_text(encoding="utf-8")
    assert "monitor_timeout_minutes:" in progress
    assert 'default: "350"' in progress
    assert "always() && needs.plan.result == 'success'" in tb2
    assert "always() && needs.plan.result == 'success'" in engine


def test_agent_import_paths_are_resolved_before_any_matrix_fan_out() -> None:
    # Run 35259343723 dispatched 20 task jobs that all died on
    # "No module named 'eval.gt_central_agent'".
    engine = (
        ROOT / ".github" / "workflows" / "tb2_miniswe_engine.yml"
    ).read_text(encoding="utf-8")
    deepswe = (
        ROOT / ".github" / "workflows" / "deepswe_miniswe_central.yml"
    ).read_text(encoding="utf-8")

    for name, text in (("engine", engine), ("deepswe", deepswe)):
        guard = "Resolve the exact agent import path before any matrix fan-out"
        assert guard in text, name
        # The guard runs in `plan`, which is the only job before the fan-out.
        assert text.index(guard) < text.index("    strategy:"), name
        # The literal is READ out of the workflow, never restated here: a copy
        # in the test only proves the test and the workflow agree, which is how
        # the retired eval.pier_gt_adapter pin stayed alive through a test that
        # asserted it. What the dispatcher declares is imported for real below.
        literal = _declared_agent_import_path(text)
        # Exactly one operative literal: prose in the header comment may repeat
        # it, but nothing outside the shared env may hardcode it again.
        operative = [
            line
            for line in text.splitlines()
            if literal in line and not line.lstrip().startswith("#")
        ]
        assert len(operative) == 1, (name, operative)
        assert "importlib.import_module(module)" in text, name
        assert "::error::agent module" in text, name
    assert "codex/gt-921bec20-union-smokes does NOT carry the engine" in engine


def _declared_agent_import_path(text: str) -> str:
    """The one AGENT_IMPORT_PATH a workflow declares."""
    declared = re.findall(r'AGENT_IMPORT_PATH: "([^"]+)"', text)
    assert len(declared) == 1, declared
    return declared[0]


def test_dispatched_agent_import_path_resolves_to_a_module_that_exists() -> None:
    # The deepswe env pinned `eval.pier_gt_adapter:PierMiniSweCentralAgent`,
    # which exists on no branch of this repository - so the plan-stage guard
    # that resolves it could only ever fail, and a literal pin in the test kept
    # the broken string alive.  Import whatever the workflow declares: the
    # dispatcher's own string, resolved the way the guard resolves it.
    deepswe = (
        ROOT / ".github" / "workflows" / "deepswe_miniswe_central.yml"
    ).read_text(encoding="utf-8")
    literal = _declared_agent_import_path(deepswe)
    # Including the header comment, which described the deleted gt_central_agent.
    assert "eval.pier_gt_adapter:" not in deepswe
    assert "gt_central_agent" not in deepswe

    module, _, symbol = literal.partition(":")
    imported = importlib.import_module(module)
    assert isinstance(getattr(imported, symbol), type), literal
    # The retired path really is absent; the guard's error message says so.
    assert not (ROOT / "eval" / "pier_gt_adapter.py").exists()


def test_deepswe_import_guard_installs_first_and_blames_the_right_module() -> None:
    # Two defects in one guard: it ran before any install, so a present adapter
    # whose dependency was missing looked identical to an absent one; and
    # `except ModuleNotFoundError: spec = None` threw away the one piece of
    # evidence that tells those apart.
    deepswe = (
        ROOT / ".github" / "workflows" / "deepswe_miniswe_central.yml"
    ).read_text(encoding="utf-8")
    install = deepswe.index("Install the central runtime the guard resolves against")
    guard = deepswe.index("Resolve the exact agent import path before any matrix fan-out")
    assert install < guard
    assert 'python -m pip install -e . "mini-swe-agent==2.2.8"' in deepswe
    assert "except ModuleNotFoundError as exc:" in deepswe
    assert "except ModuleNotFoundError:" not in deepswe
    # find_spec imports the PARENT package, so only a miss on the target or on
    # the package that contains it is the trap this guard exists for.
    body = deepswe[guard:]
    blame = body.index('missing = getattr(exc, "name", "") or ""')
    assert body.index('if missing == module or module.startswith(f"{missing}.")') > blame


def test_engine_import_guard_blames_the_right_module_too() -> None:
    # LOW-3: the deepswe guard learned to read `exc.name` and the engine guard
    # did not, so the two copies of the same block rotted apart.  The engine's
    # `except ModuleNotFoundError: spec = None` turns any dependency the
    # PARENT package reaches for - find_spec imports it - into a fatal
    # "agent module is not importable on ref" verdict, which is exactly the
    # false blame the deepswe refinement exists to prevent.  Workflows cannot
    # import each other, so the block is mirrored, and this test is the thing
    # that keeps the mirror honest.
    engine = (
        ROOT / ".github" / "workflows" / "tb2_miniswe_engine.yml"
    ).read_text(encoding="utf-8")
    guard = engine.index("Resolve the exact agent import path before any matrix fan-out")
    body = engine[guard:]
    assert "except ModuleNotFoundError as exc:" in body
    # The discarded-evidence shape must be gone from the operative lines
    # (the mirrored comment quotes it while explaining why it was removed).
    operative = " ".join(
        line for line in body.splitlines() if not line.lstrip().startswith("#")
    )
    assert "spec = None" not in operative
    blame = body.index('missing = getattr(exc, "name", "") or ""')
    assert body.index('if missing == module or module.startswith(f"{missing}.")') > blame
    # The unrelated-dependency arm must warn and pass, never fail the planner.
    warning = body.index("::warning::resolving ")
    assert body.index("sys.exit(0)", warning) < body.index("if spec is None:")


def test_every_live_preflight_prices_the_whole_cohort_and_reports_its_verdict() -> None:
    # scripts/provider_preflight.py defaults --expected-tasks to 1 and no caller
    # passed it, so a 20-task cohort was cleared against the price of one task.
    # A key with no declared limit, or a model with no published price, also
    # skips the comparison and still reports PASS - which is how run
    # 35383113823 got past the gate and then died on per-request credit errors.
    preflight = (ROOT / "scripts" / "provider_preflight.py").read_text(encoding="utf-8")
    assert '"--expected-tasks"' in preflight

    # L-5: the shell invocation of the CLI is the one thing here with no
    # behavioural equivalent - pricing the cohort for real is a live, paid
    # call - so the flags stay a text assertion, read off the gate step this
    # time rather than off the first `index()` hit in the whole file. What the
    # gate then DOES with the receipt (the funds verdict, the ::warning, the
    # cohort comparison) is executed by the parameterised tests below.
    for workflow in PAID_WORKFLOWS:
        script = _preflight_step(workflow)["run"]
        call = script[
            script.index(_PREFLIGHT_INVOCATION) : script.index(
                "--live", script.index(_PREFLIGHT_INVOCATION)
            )
        ]
        assert "--expected-tasks" in call, workflow.name
        # Threaded from the planner's own count, never a hardcoded cohort size.
        assert "needs.plan.outputs.task_count" in call, workflow.name
# --- the funds gate reads its own receipt back ------------------------------
# --expected-tasks is the whole cohort price.  Dropped, defaulted or threaded
# from the wrong output, the gate clears a key against the price of ONE task
# and the rest die mid-run on per-request credit errors (run 35383113823).
# The gate is inline Python in the workflow, so the test runs THAT source
# rather than a restatement of it.


# M-2: the planners of swelive_gt_harness_paid.yaml and
# deepswe_gt_harness_product_p0731.yaml do `from scripts.provider_preflight
# import load_route`, so selecting the first step whose `run` merely MENTIONS
# the module returned the PLANNER's heredoc for two of the three paid
# workflows, and every behavioural test below was then exercising cohort
# resolution instead of the funds gate. The gate is the step that invokes the
# CLI as a module.
_PREFLIGHT_INVOCATION = "python -m scripts.provider_preflight"


def _preflight_step(workflow: Path) -> dict:
    """The step that RUNS the preflight CLI, never one that only imports it."""
    document = yaml.safe_load(workflow.read_text(encoding="utf-8"))
    for job in document["jobs"].values():
        for step in job.get("steps") or []:
            if _PREFLIGHT_INVOCATION in (step.get("run") or ""):
                return step
    raise AssertionError(f"{workflow.name}: no `{_PREFLIGHT_INVOCATION}` step")


def _preflight_gate_source(workflow: Path) -> str:
    script = _preflight_step(workflow)["run"]
    match = re.search(r"python - <<'PY'\n(.*?)\nPY(\n|$)", script, re.S)
    assert match, f"{workflow.name}: no python heredoc beside the preflight"
    return match.group(1)


def _preflight_receipt_name(workflow: Path) -> str:
    """The receipt the CLI is told to write, which the gate then reads back.

    tb2 writes provider-preflight.json and the other two provider-gate.json, so
    a fixture that hardcoded one name would leave the gate reading nothing and
    passing for the wrong reason in two of the three workflows.
    """
    match = re.search(r"--output\s+(\S+)", _preflight_step(workflow)["run"])
    assert match, f"{workflow.name}: the preflight invocation names no --output"
    return match.group(1)


def _preflight_receipt(**overrides) -> dict:
    receipt = {
        "status": "PASS",
        "provider_ready": True,
        "model": load_model_pin()["model"],
        "provider_routing": {
            "only": ["streamlake"],
            "quantizations": ["fp8"],
            "allow_fallbacks": False,
            "require_parameters": True,
        },
        "context_window_tokens": 131072,
        "reserved_output_tokens": 8192,
        "context_window_source": "manifest",
        "funds_verdict": "sufficient",
        "funds_reason": None,
        "estimate_usd": 2.0,
        "funds_headroom_bucket": "ge_10x",
        "expected_tasks": 20,
    }
    receipt.update(overrides)
    return receipt


def _run_preflight_gate(
    tmp_path: Path,
    receipt: dict,
    expected_tasks: int,
    workflow: Path = WORKFLOWS[0],
):
    (tmp_path / _preflight_receipt_name(workflow)).write_text(
        json.dumps(receipt), encoding="utf-8"
    )
    environment = dict(os.environ)
    environment["PLANNED_TASK_COUNT"] = str(expected_tasks)
    environment["GITHUB_OUTPUT"] = str(tmp_path / "github-output.txt")
    return subprocess.run(
        [sys.executable, "-c", _preflight_gate_source(workflow)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=environment,
    )


# Three workflows spend money behind the same inline gate, so every gate
# behaviour below is asserted against all three rather than against tb2 alone.
_PAID = pytest.mark.parametrize("workflow", PAID_WORKFLOWS, ids=lambda path: path.name)


@_PAID
def test_preflight_gate_passes_a_receipt_that_priced_the_whole_plan(
    tmp_path, workflow
) -> None:
    completed = _run_preflight_gate(tmp_path, _preflight_receipt(), 20, workflow)

    assert completed.returncode == 0, completed.stderr
    written = (tmp_path / "github-output.txt").read_text(encoding="utf-8")
    assert "context_window_tokens=131072" in written


@_PAID
def test_preflight_gate_fails_when_the_receipt_priced_one_task(
    tmp_path, workflow
) -> None:
    """A dropped --expected-tasks leaves the default of 1 in the receipt."""
    completed = _run_preflight_gate(
        tmp_path, _preflight_receipt(expected_tasks=1), 20, workflow
    )

    assert completed.returncode == 1
    assert "::error title=Provider funds::" in completed.stdout
    assert "the funds gate priced" in completed.stdout
    assert "priced 1 task(s) for a cohort of 20" in completed.stdout


@_PAID
def test_funds_warning_names_the_verdict_reason_and_cohort(tmp_path, workflow) -> None:
    """An unbounded key skips the comparison; the warning has to say so."""
    completed = _run_preflight_gate(
        tmp_path,
        _preflight_receipt(
            funds_verdict="unassessed",
            funds_reason="no_declared_limit",
            estimate_usd=None,
            funds_headroom_bucket=None,
        ),
        20,
        workflow,
    )

    assert completed.returncode == 0, completed.stderr
    warning = next(
        line for line in completed.stdout.splitlines()
        if line.startswith("::warning title=Provider funds::")
    )
    assert "verdict=unassessed" in warning
    assert "reason=no_declared_limit" in warning
    assert "20 task(s)" in warning
    # The receipt reports a bucket now; a ratio is gone from the gate entirely.
    assert "ratio" not in warning


@_PAID
def test_funds_warning_reports_the_headroom_bucket(tmp_path, workflow) -> None:
    completed = _run_preflight_gate(
        tmp_path,
        _preflight_receipt(
            funds_verdict="insufficient",
            funds_reason="estimate_exceeds_available",
            funds_headroom_bucket="lt_1x",
        ),
        20,
        workflow,
    )

    warning = next(
        line for line in completed.stdout.splitlines()
        if line.startswith("::warning title=Provider funds::")
    )
    assert "headroom=lt_1x" in warning


@_PAID
def test_the_three_paid_workflows_bind_the_cohort_the_same_way(workflow) -> None:
    """One shape across the three, so a fix to one is a fix to all.

    What the gate DOES with PLANNED_TASK_COUNT - reading it, comparing it to
    expected_tasks, annotating ::error and exiting 1, reporting the headroom
    bucket - is asserted by running each workflow's own gate above. What is
    left here is the part running it cannot show.
    """
    step = _preflight_step(workflow)
    # The gate reads PLANNED_TASK_COUNT from the environment, and the fixture
    # above supplies it, so only the workflow can bind it to the planner's
    # count: a dropped or mistyped binding is invisible to an execution.
    assert (step.get("env") or {}).get("PLANNED_TASK_COUNT") == (
        "${{ needs.plan.outputs.task_count }}"
    ), workflow.name
    # A retired field's ABSENCE has no behavioural equivalent: a gate that
    # never mentions funds_headroom_ratio proves nothing about a leftover copy
    # of it elsewhere in the workflow.
    assert "funds_headroom_ratio" not in workflow.read_text(encoding="utf-8"), (
        workflow.name
    )


@_PAID
def test_every_paid_planner_publishes_the_task_count_the_gate_binds_to(
    workflow,
) -> None:
    """`needs.plan.outputs.task_count` resolves to the empty string in Actions
    when the planner does not publish it, and the gate would then price one
    task. Structural, because no local execution resolves a needs expression.
    """
    document = yaml.safe_load(workflow.read_text(encoding="utf-8"))
    published = (document["jobs"]["plan"].get("outputs") or {}).get("task_count", "")
    assert str(published).startswith("${{ steps."), workflow.name


# --- M-2: the extracted gate must be the gate ------------------------------
# `_preflight_gate_source` selected the first step whose `run` merely mentions
# `scripts.provider_preflight`.  In swelive_gt_harness_paid.yaml and
# deepswe_gt_harness_product_p0731.yaml that is the PLANNER, which imports
# `from scripts.provider_preflight import load_route` - so the helper returned
# the planner's heredoc for two of the three paid workflows and every
# behavioural test above was, for them, exercising cohort resolution.


def test_the_extracted_gate_is_the_funds_gate_not_the_planner() -> None:
    for workflow in PAID_WORKFLOWS:
        source = _preflight_gate_source(workflow)
        assert "PLANNED_TASK_COUNT" in source, workflow.name
        assert 'receipt.get("expected_tasks")' in source, workflow.name
        # The planner's heredoc is the shape that used to be returned.
        assert "load_route" not in source, workflow.name
        assert "select_stage_tasks" not in source, workflow.name
