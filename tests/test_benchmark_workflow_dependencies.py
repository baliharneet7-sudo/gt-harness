from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = (
    ROOT / ".github" / "workflows" / "tb2_miniswe_central.yml",
    ROOT / ".github" / "workflows" / "swebench_live_lite_full.yml",
)


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
    workflow = WORKFLOWS[1].read_text(encoding="utf-8")
    manifest = json.loads(
        (ROOT / "config" / "tb2_gt_import_manifest.json").read_text(encoding="utf-8-sig")
    )
    assert manifest["gt_source_commit"] == (
        "921bec20d3dbabd12e4b442936d9259c24cdcc74"
    )
    assert "SWE-Live-GT-${{ inputs.mode }} | ${{ inputs.model }}" in workflow
    assert "secrets.OPENROUTER_NEW || secrets.OPENROUTER_API_KEY" in workflow
    assert 'MODE_LIMITS = {"smoke": 5, "pilot": 20, "pilot100": 100, "full": 300}' in workflow
    assert "max-parallel: 20" in workflow
    assert "mini-swe-agent==2.4.5" in workflow
    assert "openhands" not in workflow.lower()
    assert "python3 -m swebench.harness.run_evaluation" in workflow
    assert "official-verifier progress receipt" in workflow.lower()
    assert "ref: ${{ inputs.gt_ref || 'gt-trial' }}" in workflow
