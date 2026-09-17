"""Benchmark-owned install hook closing GT's initial-index/model-edit race."""

from __future__ import annotations

import os
from pathlib import Path

from eval._env import UTF8_ENV
from eval.pier_gt_harness_adapter import PierGtHarnessMiniSwe246Agent
from gt_harness.product import project_task_environment

_REMOTE_HELPER = "/installed-agent/swelive-prewarm-graph.py"
_REMOTE_RUNTIME_DIR = "/installed-agent/swelive-runtime"
_REMOTE_SITECUSTOMIZE = f"{_REMOTE_RUNTIME_DIR}/sitecustomize.py"
_REMOTE_PY = "$HOME/.local/share/uv/tools/nano-harness/bin/python"


_ORIGINAL_INSTALL = PierGtHarnessMiniSwe246Agent.install
_ORIGINAL_RUN_COMMAND = PierGtHarnessMiniSwe246Agent._run_command


async def _prewarmed_install(self, environment) -> None:
    """Run the exact adapter install, then build the fresh task-local graph."""
    await _ORIGINAL_INSTALL(self, environment)

    helper = Path(__file__).with_name("prewarm_graph.py")
    runtime_hook = Path(__file__).with_name("sitecustomize.py")
    await self.exec_as_root(environment, f"mkdir -p {_REMOTE_RUNTIME_DIR}")
    await environment.upload_file(helper, _REMOTE_HELPER)
    await environment.upload_file(runtime_hook, _REMOTE_SITECUSTOMIZE)

    task_id = str(self._resolved_flags.get("task_id", "")).strip()
    source_sha = str(self._resolved_flags.get("product_source_sha", "")).strip()
    if not task_id or not source_sha:
        raise ValueError("SWE-Live graph prewarm identity is incomplete")

    env = project_task_environment(os.environ, treatment="groundtruth")
    env.update(UTF8_ENV)
    env.update(self.resolve_env_vars())
    env.update(
        {
            "GT_DENSE_MODEL_DIR": "/installed-agent/dense-model",
            "GT_INDEX_BINARY": "/installed-agent/gt-index",
            "GT_PRODUCT_SOURCE_SHA": source_sha,
            "GT_STATE_DIR": "/logs/agent/gt-state",
            "GT_TASK_ID": task_id,
        }
    )
    await self.exec_as_agent(
        environment,
        f'PATH="/installed-agent/lsp-bin:$PATH" "{_REMOTE_PY}" {_REMOTE_HELPER}',
        env=env,
    )


def _complete_lsp_run_command(
    self, instruction: str, model: str, extra_args: str = ""
) -> str:
    """Load the benchmark-owned full-selection compatibility hook."""
    command = _ORIGINAL_RUN_COMMAND(self, instruction, model, extra_args)
    marker = f'exec "{_REMOTE_PY}"'
    replacement = (
        f'PYTHONPATH="{_REMOTE_RUNTIME_DIR}${{PYTHONPATH:+:$PYTHONPATH}}" '
        + marker
    )
    if command.count(marker) != 1:
        raise RuntimeError("unexpected Mini-SWE command shape")
    return command.replace(marker, replacement, 1)


def install_prewarm_hook() -> None:
    """Patch only the process-local install seam; retain the official class path."""
    if PierGtHarnessMiniSwe246Agent.install is not _prewarmed_install:
        PierGtHarnessMiniSwe246Agent.install = _prewarmed_install
    if PierGtHarnessMiniSwe246Agent._run_command is not _complete_lsp_run_command:
        PierGtHarnessMiniSwe246Agent._run_command = _complete_lsp_run_command


__all__ = ["install_prewarm_hook"]
