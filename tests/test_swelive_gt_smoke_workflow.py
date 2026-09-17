from __future__ import annotations

import json
import tomllib
from pathlib import Path

from scripts.build_swelive_smoke_tasks import DIGESTS, build

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/swelive_gt_harness_paid.yaml"
DISPATCHER = ROOT / ".github/workflows/swebench_live_lite_full.yml"


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
    assert "config/provider_route_union_alpha.v1.json" in text
    assert "secrets.OPENROUTER_NEW" in text
    assert "max-parallel: 20" in text
    assert "multiplier=5.0" in text
    assert 'gt_source_commit != "921bec20d3dbabd12e4b442936d9259c24cdcc74"' in text
    assert '"swebench==4.1.0"' in text
    assert "python -m swebench.harness.run_evaluation" in text
    assert "official evaluator disagrees with Pier verifier" in text
    pre = text.index("Prove the official SWE-bench evaluator before any model request")
    paid = text.index("Run SWE-bench-Live through the released gt-harness run boundary")
    assert pre < paid


def test_registered_workflow_dispatches_the_certified_workflow() -> None:
    text = DISPATCHER.read_text(encoding="utf-8")
    assert "uses: ./.github/workflows/swelive_gt_harness_paid.yaml" in text
    assert "secrets: inherit" in text
    assert "cohort_stage: ${{ inputs.cohort_stage }}" in text
