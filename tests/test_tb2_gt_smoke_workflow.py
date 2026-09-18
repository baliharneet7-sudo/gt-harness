from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "tb2_miniswe_central.yml"
IMPORT = ROOT / "config" / "tb2_gt_import_manifest.json"


def test_gt_smoke_is_source_bound_and_uses_the_product_agent() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    manifest = json.loads(IMPORT.read_text(encoding="utf-8-sig"))

    assert manifest["baseline_harness_parent"] == (
        "f4aaf2bf88d007334195a6c71a34cd16b82bb8dc"
    )
    assert manifest["gt_source_commit"] == (
        "921bec20d3dbabd12e4b442936d9259c24cdcc74"
    )
    assert "TREATMENT_SHA: ${{ github.sha }}" in text
    assert "GT_SOURCE_SHA: 921bec20d3dbabd12e4b442936d9259c24cdcc74" in text
    assert "eval.pier_gt_harness_adapter:PierGtHarnessMiniSwe246Agent" in text
    assert "eval.miniswe_agent:MiniSweAgent" not in text
    assert "openhands" not in text.lower()
    assert 'MINISWE_AGENT_VERSION: "2.4.6"' in text


def test_gt_smoke_keeps_the_frozen_execution_envelope() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "max-parallel: 20" in text
    assert "options: [gate-one, remaining-19, all-20]" in text
    assert '"gate-one": tasks[:1]' in text
    assert '"remaining-19": tasks[1:]' in text
    assert 'TIMEOUT_MULTIPLIER: "5.0"' in text
    assert 'STEP_LIMIT: "100"' in text
    assert "attempts_per_task" in text
    assert '"parallel": min(20, len(selected))' in text
    assert '"full_task_count": 20' in text
    assert "36d5c8945f6f8d9ae23fe2cea759f16da0c0cea424a98f710cfaa0d9d6fd0303" in text
    assert "actions/cache/restore@v4" in text
    assert "tb2-img-${{ matrix.task }}-${{ env.IMAGE_TAG }}" in text
    assert "Pull the existing GHCR mirror only on cache miss" in text
    assert "uses: ./.github/workflows/deepswe_gt_harness_product.yml" in text
    assert "pre_spend:" in text
    assert "needs: [plan, provider_free]" in text
    assert "needs: [plan, pre_spend]" in text
    assert "Run the real official verifier through Pier without a model" in text
    assert "Prove the exact treatment adapter and environment contract" in text
    assert "PYTHONPATH: ${{ github.workspace }}" in text
    assert "eval.pier_filtered_docker:PierFilteredDockerEnvironment" in text
    assert 'm.version("datacurve-pier")' in text
    assert '"exact_pier_environment_executed": "PASS"' in text
    assert "-a nop" in text
    assert '"task_model_requests": 0' in text
    assert "config/provider_route_deepseek_v4_flash_0731.v1.json" in text
    assert "scripts.provider_preflight" in text
    assert '"provider_route_live_canary": "PASS"' in text
    assert "GT_PROVIDER_CONTEXT_WINDOW_TOKENS: ${{ needs.pre_spend.outputs.context_window_tokens }}" in text
    assert "GT_PROVIDER_ROUTING_JSON: ${{ needs.pre_spend.outputs.provider_routing_json }}" in text
    assert "Save the verifier-canary image for paid task reuse" in text
    assert "actions/cache/save@v4" in text


def test_gt_smoke_uses_official_harbor_grades_and_retains_evidence() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    parser = (ROOT / "scripts" / "benchmark_progress.py").read_text(encoding="utf-8")

    assert "pier run" in text
    assert "Run one official Pier TB2 trial" in text
    assert 'DATASET: terminal-bench@2.0' in text
    assert 'MODEL: deepseek/deepseek-v4-flash-0731' in text
    assert '--effective-model "openai/deepseek/deepseek-v4-flash-0731"' in text
    assert "secrets.OPENROUTER_NEW" in text
    assert "scripts.benchmark_progress emit-harbor" in text
    assert '"official_verifier": True' in parser
    assert '"official_verifier": False' in parser
    assert '"state": "passed" if reward == 1 else "verifier_failed"' in parser
    assert '"state": "infrastructure_failed"' in parser
    assert 'result_path.parent / "verifier" / "reward.txt"' in parser
    assert 'result_path.parent / "verifier" / "ctrf.json"' in parser
    assert "results/terminal-bench/" in text
    assert "benchmark-progress-tb2-gt-${{ github.run_id }}-${{ matrix.task }}" in text
    assert "tb2-gt-smoke20-921bec20-${{ github.run_id }}-task-${{ matrix.task }}" in text
