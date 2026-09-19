from __future__ import annotations

import json
import tomllib
from pathlib import Path

import yaml

from scripts.build_swelive_smoke_tasks import DIGESTS, build

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/swelive_gt_harness_paid.yaml"
DISPATCHER = ROOT / ".github/workflows/swebench_live_lite_full.yml"
# One pin, read rather than copied: a partial repin must fail in
# tests/test_benchmark_workflow_dependencies.py, not in a paid dispatch.
MODEL_PIN = json.loads(
    (ROOT / "config" / "benchmark_model.v1.json").read_text(encoding="utf-8")
)


def test_frozen_five_task_packages_rebuild_exactly(tmp_path: Path) -> None:
    manifest = build(tmp_path)
    assert [row["task_id"] for row in manifest["tasks"]] == list(DIGESTS)
    for row in manifest["tasks"]:
        task = tmp_path / "tasks" / row["task_id"]
        config = tomllib.loads((task / "task.toml").read_text(encoding="utf-8"))
        assert config["environment"]["docker_image"].endswith(row["container_digest"])
        assert (task / "tests/test_patch.diff").is_file()
        assert json.loads((task / "tests/spec.json").read_text())["instance_id"] == row["task_id"]


def test_paid_workflow_is_exact_miniswe_union_alpha_and_officially_graded() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "eval.pier_gt_harness_adapter:PierGtHarnessMiniSwe246Agent" in text
    assert "eval.pier_filtered_docker:PierFilteredDockerEnvironment" in text
    assert MODEL_PIN["swelive_route_manifest"] in text
    assert "secrets.OPENROUTER_NEW" in text
    assert "max-parallel: 20" in text
    assert "multiplier=5.0" in text
    assert 'gt_source_commit != "921bec20d3dbabd12e4b442936d9259c24cdcc74"' in text
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


def test_registered_workflow_dispatches_the_certified_workflow() -> None:
    text = DISPATCHER.read_text(encoding="utf-8")
    assert MODEL_PIN["model"] in text
    assert "uses: ./.github/workflows/swelive_gt_harness_paid.yaml" in text
    assert "secrets: inherit" in text
    assert "cohort_stage: ${{ inputs.cohort_stage }}" in text


def test_provider_gate_prices_the_whole_cohort_it_is_about_to_dispatch() -> None:
    # The funds estimate defaults to one task.  A five-task cohort cleared
    # against the price of one task is not a funds gate, it is a spelling
    # check on the key - and run 35383113823 died mid-run because of it.
    text = WORKFLOW.read_text(encoding="utf-8")
    call = text[
        text.index("python -m scripts.provider_preflight") : text.index(
            "--live", text.index("python -m scripts.provider_preflight")
        )
    ]
    assert '--expected-tasks "${{ needs.plan.outputs.task_count }}"' in call

    # The expression has to resolve: `plan` must publish task_count and the
    # gate job must depend on `plan`, or the flag silently arrives empty.
    workflow = yaml.safe_load(text)
    plan = workflow["jobs"]["plan"]
    gate = workflow["jobs"]["provider_gate"]
    assert "task_count" in plan["outputs"]
    assert "plan" in gate["needs"]


def test_provider_gate_reports_a_funds_verdict_it_cannot_act_on() -> None:
    # `sufficient` is tri-state: an unbounded key and an unpriced model both
    # skip the comparison and still report PASS.  Skipping quietly is the
    # failure mode; say which verdict was reached.
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'verdict = receipt.get("funds_verdict", "absent")' in text
    assert 'if verdict != "sufficient":' in text
    assert "::warning title=Provider funds::funds_verdict=" in text
