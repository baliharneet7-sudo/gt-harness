"""The SWE-bench-Live Lite GT-on workflow contract (launch-time model, attached
delivery, pinned 300-task catalog, sharded matrix).

Structural assertions pin what no local execution can observe (expressions,
job wiring, the registered wrapper's forwarding); the planner itself is
executed in tests/test_swelive_plan_and_attest.py.
"""
from __future__ import annotations

import hashlib
import json
import re
import tomllib
from pathlib import Path

import yaml

from scripts.build_swelive_catalog import CATALOG_PATH, canonical_lf, catalog_sha256
from scripts.build_swelive_smoke_tasks import build

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/swelive_gt_harness_paid.yaml"
DISPATCHER = ROOT / ".github/workflows/swebench_live_lite_full.yml"
# The five digests the smoke cohort was certified against (run history of
# swelive_gt_harness_paid.yaml). The catalog must keep them, byte for byte.
CERTIFIED_SMOKE5_DIGESTS = {
    "aiogram__aiogram-1594": "sha256:4461f94ae2293dcbabcd71b2425a9d00f9d88dba0e0203fecba6aee311199c2d",
    "amoffat__sh-744": "sha256:0ab5f01f2c45fe84813deec1dd1478917ba63b9a2a7443dc43a065bd186e14c3",
    "arviz-devs__arviz-2413": "sha256:ba0f72743455df00addcdfdfe326e3645761a019b166652318a5c828f1231a80",
    "aws-cloudformation__cfn-lint-3749": "sha256:f66404b8fee73c41820929afe4778e2c0dbba735a950ad9a042ae9e2ea649d29",
    "aws-cloudformation__cfn-lint-3764": "sha256:3a1787a94d8589771a6306984fb0826498eb1a63e14ca87c4826e6382f092cc4",
}
LAUNCH_INPUTS = {
    "approve_paid_run", "cohort_stage", "single_task_id", "prior_gate_run_id",
    "readiness_run_id", "model", "gt_delivery_mode", "provider_only",
    "quantization", "allow_fallbacks", "reasoning_effort", "temperature",
    "step_limit", "max_parallel", "shard_index", "shard_count",
}
# GitHub rejects a workflow_dispatch with more than 25 inputs.
DISPATCH_INPUT_LIMIT = 25


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _document(path: Path = WORKFLOW) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _step(job: str, name_fragment: str) -> dict:
    for step in _document()["jobs"][job]["steps"]:
        if name_fragment in str(step.get("name") or ""):
            return step
    raise AssertionError(f"{job}: no step named like {name_fragment!r}")


def test_smoke5_packages_rebuild_exactly_from_the_catalog(tmp_path: Path) -> None:
    manifest = build(tmp_path)
    assert {row["task_id"]: row["container_digest"] for row in manifest["tasks"]} == (
        CERTIFIED_SMOKE5_DIGESTS
    )
    assert [row["task_id"] for row in manifest["tasks"]] == list(CERTIFIED_SMOKE5_DIGESTS)
    for row in manifest["tasks"]:
        task = tmp_path / "tasks" / row["task_id"]
        config = tomllib.loads((task / "task.toml").read_text(encoding="utf-8"))
        assert config["environment"]["docker_image"].endswith(row["container_digest"])
        assert json.loads((task / "tests/spec.json").read_text())["instance_id"] == row["task_id"]
        committed = ROOT / "swelive-bench" / "tasks" / row["task_id"]
        for rendered in task.rglob("*"):
            if rendered.is_file():
                twin = committed / rendered.relative_to(task)
                assert canonical_lf(twin.read_bytes()) == canonical_lf(rendered.read_bytes()), twin


def test_catalog_identity_is_pinned_by_sha256_in_the_planner() -> None:
    text = _text()
    pinned = re.search(r'EXPECTED_CATALOG_SHA256 = "([0-9a-f]{64})"', text)
    assert pinned, "the planner must pin the catalog digest literally"
    assert pinned.group(1) == catalog_sha256(CATALOG_PATH)
    assert "catalog_digest != EXPECTED_CATALOG_SHA256" in text
    manifest = json.loads((ROOT / "swelive-bench/manifest.json").read_text(encoding="utf-8"))
    assert manifest["catalog"]["sha256"] == pinned.group(1)
    # The raw file bytes on a LF checkout are what CI hashes.
    assert pinned.group(1) == hashlib.sha256(
        canonical_lf(CATALOG_PATH.read_bytes())
    ).hexdigest()


def test_paid_workflow_is_miniswe_and_officially_graded() -> None:
    text = _text()
    assert "eval.pier_gt_harness_adapter:PierGtHarnessMiniSwe246Agent" in text
    assert "eval.pier_filtered_docker:PierFilteredDockerEnvironment" in text
    assert "multiplier=5.0" in text
    assert 're.fullmatch(r"[0-9a-f]{40}", str(gt_source_commit or ""))' in text
    assert '"swebench==4.1.0"' in text
    assert "git+https://github.com/microsoft/SWE-bench-Live.git@ad79b850f15e33992e96f03f6e97f05ddf9aa0be" in text
    assert 'direct["vcs_info"]["commit_id"] == "ad79b850f15e33992e96f03f6e97f05ddf9aa0be"' in text
    assert "python -m swebench.harness.run_evaluation" in text
    assert "--predictions_path gold" in text
    assert 'name "*.${EVAL_RUN_ID}.json"' in text
    assert 'for key in ("resolved_ids", "unresolved_ids", "error_ids", "empty_patch_ids")' in text
    assert "official evaluator disagrees with Pier verifier" in text
    pre = text.index("Prove the official SWE-bench evaluator before any model request")
    paid = text.index("Run SWE-bench-Live through the released gt-harness run boundary")
    assert pre < paid


def test_no_model_route_or_retired_source_is_baked_in() -> None:
    for path in (WORKFLOW, DISPATCHER):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"deepseek", text, re.I), path.name
        assert not re.search(r"config/provider_route_[A-Za-z0-9_.]+\.json", text), path.name
        assert "921bec20" not in text, path.name
        assert "--ak temperature=1.0" not in text, path.name
        document = _document(path)
        assert "921bec20" not in str(document.get("name")) + str(document.get("run-name"))
    text = _text()
    assert "python -m scripts.render_provider_route" in text
    assert re.search(r"--manifest \S*plan/provider-route\.json", text)


def test_model_is_a_required_launch_input_everywhere() -> None:
    for path in (WORKFLOW, DISPATCHER):
        triggers = _document(path)[True]
        for trigger, spec in triggers.items():
            model = spec["inputs"]["model"]
            assert model["required"] is True, (path.name, trigger)
            assert "default" not in model, (path.name, trigger)


def test_launch_inputs_are_declared_and_the_wrapper_forwards_every_one() -> None:
    paid = _document()[True]
    wrapper = _document(DISPATCHER)
    for inputs in (paid["workflow_dispatch"]["inputs"], paid["workflow_call"]["inputs"],
                   wrapper[True]["workflow_dispatch"]["inputs"]):
        assert set(inputs) == LAUNCH_INPUTS
        assert len(inputs) <= DISPATCH_INPUT_LIMIT
        assert inputs["temperature"]["default"] == "1.0"
        assert inputs["step_limit"]["default"] == "0"
        assert inputs["max_parallel"]["default"] == "20"
        assert inputs["shard_index"]["default"] == "1"
        assert inputs["shard_count"]["default"] == "1"
        assert inputs["gt_delivery_mode"]["default"] == "attached"
        assert "smoke5" in (inputs["cohort_stage"].get("options") or ["smoke5"])
    for inputs in (paid["workflow_dispatch"]["inputs"], wrapper[True]["workflow_dispatch"]["inputs"]):
        mode = inputs["gt_delivery_mode"]
        assert mode["type"] == "choice" and mode["options"] == ["attached", "push"]
        assert mode["required"] is True
    assert paid["workflow_call"]["inputs"]["gt_delivery_mode"]["type"] == "string"
    call = wrapper["jobs"]["certified-gt-run"]
    assert call["uses"] == "./.github/workflows/swelive_gt_harness_paid.yaml"
    assert call["secrets"] == "inherit"
    assert call["with"] == {name: "${{ inputs.%s }}" % name for name in LAUNCH_INPUTS}


def test_every_provider_key_read_falls_back_across_the_two_secret_names() -> None:
    reads = [line.strip() for line in _text().splitlines() if "secrets.OPENROUTER" in line]
    assert reads, "the paid workflow reads no provider key"
    for line in reads:
        assert line.endswith("${{ secrets.OPENROUTER_NEW || secrets.OPENROUTER_API_KEY }}"), line


def test_the_pier_run_carries_the_launch_contract() -> None:
    run = _step("task", "Run SWE-bench-Live through the released gt-harness")
    script = run["run"]
    for flag, output in (
        ("gt_delivery_mode", "gt_delivery_mode"),
        ("step_limit", "step_limit"),
        ("max_iterations", "step_limit"),
        ("temperature", "temperature"),
    ):
        assert f'--ak {flag}="${{{{ needs.plan.outputs.{output} }}}}"' in script, flag
    assert run["env"]["GT_REASONING_EFFORT"] == "${{ needs.plan.outputs.reasoning_effort }}"
    assert run["env"]["OPENAI_BASE_URL"] == "${{ needs.plan.outputs.provider_base_url }}"
    assert '-m "$MODEL"' in script
    job = _document()["jobs"]["task"]
    assert job["env"]["MODEL"] == "${{ needs.plan.outputs.model }}"
    assert job["env"]["GT_DELIVERY_MODE"] == "${{ needs.plan.outputs.gt_delivery_mode }}"


def test_matrix_concurrency_stagger_and_timeout_fit_the_hosted_ceiling() -> None:
    job = _document()["jobs"]["task"]
    assert job["strategy"]["max-parallel"] == "${{ fromJSON(needs.plan.outputs.max_parallel) }}"
    assert job["strategy"]["matrix"] == "${{ fromJSON(needs.plan.outputs.matrix) }}"
    assert "max-parallel: 20" not in _text()
    # GitHub-hosted runners stop every job at 360 minutes.
    assert job["timeout-minutes"] < 360
    planned = re.search(r"HOSTED_JOB_TIMEOUT_MINUTES = (\d+)", _text())
    assert planned and int(planned.group(1)) == job["timeout-minutes"]
    stagger = _step("task", "Stagger provider dispatch")["run"]
    assert "((ORDINAL - 1) % MAX_PARALLEL) * STAGGER_SECONDS" in stagger
    assert "(ORDINAL - 1) * STAGGER_SECONDS" not in stagger
    assert job["env"]["MAX_PARALLEL"] == "${{ needs.plan.outputs.max_parallel }}"


def test_each_task_is_materialized_from_the_catalog_before_it_runs() -> None:
    steps = [step.get("name") or step.get("uses") for step in _document()["jobs"]["task"]["steps"]]
    materialize = steps.index("Materialize this task's package from the pinned catalog")
    run = steps.index("Run SWE-bench-Live through the released gt-harness run boundary")
    assert materialize < run
    plan = _step("plan", "Verify the pinned Lite catalog")["run"]
    assert "python -m scripts.build_swelive_catalog verify" in plan
    assert "python -m scripts.build_swelive_catalog materialize --tasks all" in plan


def test_progress_rows_carry_the_delivery_and_the_summary_counts_invalid_treatment() -> None:
    emit = _step("task", "Emit the official-verifier progress receipt")
    script = emit["run"]
    assert emit["if"] == "always()"
    assert "python -m scripts.benchmark_progress emit-official" in script
    annotate = script.index("python -m scripts.annotate_gt_delivery")
    assert script.index("emit-official") < annotate
    assert '--requested-mode "$GT_DELIVERY_MODE"' in script
    assert '--requested-step-limit "$STEP_LIMIT"' in script
    summary = _document()["jobs"]["summarize"]
    assert summary["needs"] == ["plan", "task"]
    body = "\n".join(str(step.get("run") or "") for step in summary["steps"])
    assert "treatment_invalid_count" in body
    assert "step_limit_mismatch_count" in body
    assert "--finalize-missing" in body


def test_plan_artifact_carries_the_rendered_route_the_gate_and_attestation_read() -> None:
    upload = _step("plan", "Upload the immutable SWE-bench-Live plan")
    assert upload["with"]["path"] == "plan/"
    download = _step("provider_gate", "Download the immutable plan")
    assert download["with"]["path"] == "plan"
    attest = _step("attest", "Download immutable plan")
    assert attest["with"]["path"] == "attestation"
    assert "--suite swelive" in _step("attest", "Verify all SWE-bench-Live outcomes")["run"]


def test_registered_workflow_dispatches_the_certified_workflow() -> None:
    text = DISPATCHER.read_text(encoding="utf-8")
    assert "uses: ./.github/workflows/swelive_gt_harness_paid.yaml" in text
    assert "secrets: inherit" in text
    assert "cohort_stage: ${{ inputs.cohort_stage }}" in text
    assert "model: ${{ inputs.model }}" in text
    assert "gt_delivery_mode: ${{ inputs.gt_delivery_mode }}" in text


def test_no_gt_off_arm_exists() -> None:
    for path in (WORKFLOW, DISPATCHER):
        text = path.read_text(encoding="utf-8").lower()
        assert "gt_off=true" not in text and "--gt-off" not in text, path.name
        assert "integration_mode=off" not in text, path.name
    assert '"gt_off_arm": False' in _text()


def test_provider_gate_prices_the_whole_cohort_it_is_about_to_dispatch() -> None:
    # The funds estimate defaults to one task.  A cohort cleared against the
    # price of one task is not a funds gate, it is a spelling check on the key
    # - and run 35383113823 died mid-run because of it.
    text = _text()
    call = text[
        text.index("python -m scripts.provider_preflight") : text.index(
            "--live", text.index("python -m scripts.provider_preflight")
        )
    ]
    assert '--expected-tasks "${{ needs.plan.outputs.task_count }}"' in call
    workflow = _document()
    plan = workflow["jobs"]["plan"]
    gate = workflow["jobs"]["provider_gate"]
    assert "task_count" in plan["outputs"]
    assert "plan" in gate["needs"]


def test_provider_gate_reports_a_funds_verdict_it_cannot_act_on() -> None:
    # `sufficient` is tri-state: an unbounded key and an unpriced model both
    # skip the comparison and still report PASS.  Say which verdict was reached.
    text = _text()
    assert 'verdict = receipt.get("funds_verdict", "absent")' in text
    assert 'if verdict != "sufficient":' in text
    assert "::warning title=Provider funds::funds_verdict=" in text


def test_image_gate_confirms_by_digest_from_the_plan_file_not_the_env() -> None:
    gate = _document()["jobs"]["image_digest_gate"]
    assert "env" not in gate
    script = "\n".join(str(step.get("run") or "") for step in gate["steps"])
    assert "python -m scripts.build_swelive_catalog confirm-images --plan plan/swelive-plan.json" in script
    assert "imagetools inspect" not in script
    assert "needs.plan.outputs.matrix }}" not in _text().replace(
        "matrix: ${{ fromJSON(needs.plan.outputs.matrix) }}", ""
    )


def test_runs_use_only_catalog_rendered_packages() -> None:
    # Committed packages are reference material (tasks/cyclotruc__gitingest-94
    # predates the renderer and differs textually); a run must never pick one
    # up or be refused because one differs.
    from scripts.build_swelive_catalog import RENDERED_TASKS_DIR, main

    run = _step("task", "Run SWE-bench-Live through the released gt-harness")["run"]
    assert "-p swelive-bench/rendered" in run
    assert "-p swelive-bench/tasks" not in _text()
    assert 'rendered = Path("swelive-bench/rendered")' in _text()
    assert RENDERED_TASKS_DIR == ROOT / "swelive-bench" / "rendered"
    ignore = (ROOT / "swelive-bench" / ".gitignore").read_text(encoding="utf-8")
    assert "rendered/" in ignore.splitlines()
    assert main.__module__ == "scripts.build_swelive_catalog"
