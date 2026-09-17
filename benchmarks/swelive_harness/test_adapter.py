from __future__ import annotations

import asyncio
from pathlib import Path

from benchmarks.swelive_harness import adapter
from eval.pier_gt_harness_adapter import PierGtHarnessMiniSwe246Agent

ROOT = Path(__file__).resolve().parents[2]


def test_prewarm_runs_after_exact_adapter_install_and_before_the_agent(monkeypatch):
    order = []

    async def base_install(self, environment):
        order.append("exact-install")

    async def execute(self, environment, command, env=None, **kwargs):
        order.append("prewarm")
        assert command.endswith("/installed-agent/swelive-prewarm-graph.py")
        assert env["GT_TASK_ID"] == "task-1"
        assert env["GT_PRODUCT_SOURCE_SHA"] == "a" * 40
        assert env["GT_STATE_DIR"] == "/logs/agent/gt-state"

    class Environment:
        async def upload_file(self, source, destination):
            order.append("upload")
            assert Path(source).name == "prewarm_graph.py"
            assert destination == "/installed-agent/swelive-prewarm-graph.py"

    monkeypatch.setattr(adapter, "_ORIGINAL_INSTALL", base_install)
    monkeypatch.setattr(PierGtHarnessMiniSwe246Agent, "exec_as_agent", execute)
    monkeypatch.setattr(
        PierGtHarnessMiniSwe246Agent,
        "resolve_env_vars",
        lambda self: {},
    )
    agent = object.__new__(PierGtHarnessMiniSwe246Agent)
    agent._resolved_flags = {
        "task_id": "task-1",
        "product_source_sha": "a" * 40,
    }

    asyncio.run(adapter._prewarmed_install(agent, Environment()))
    assert order == ["exact-install", "upload", "prewarm"]


def test_hook_retains_the_official_agent_import_path(monkeypatch):
    monkeypatch.setattr(PierGtHarnessMiniSwe246Agent, "install", adapter._ORIGINAL_INSTALL)
    adapter.install_prewarm_hook()
    assert PierGtHarnessMiniSwe246Agent.install is adapter._prewarmed_install
    assert (
        f"{PierGtHarnessMiniSwe246Agent.__module__}:"
        f"{PierGtHarnessMiniSwe246Agent.__name__}"
        == "eval.pier_gt_harness_adapter:PierGtHarnessMiniSwe246Agent"
    )


def test_workflow_uses_one_pull_and_retains_image_by_id():
    text = (ROOT / ".github/workflows/swelive_gt_harness_paid.yaml").read_text(
        encoding="utf-8"
    )
    assert text.count('docker pull "${SOURCE_IMAGE}@${SOURCE_DIGEST}"') == 1
    canary = text.split(
        "Prove the official SWE-bench evaluator before any model request", 1
    )[1].split("Stagger provider dispatch within the parallel cohort", 1)[0]
    assert "docker pull" not in canary
    assert "docker image inspect --format '{{.Id}}'" in canary
    assert "pre-spend-official/image-id.txt" in text
    assert "python benchmarks/swelive_harness/run_pier.py run" in text
    assert (
        "--agent-import-path "
        "eval.pier_gt_harness_adapter:PierGtHarnessMiniSwe246Agent"
    ) in text
