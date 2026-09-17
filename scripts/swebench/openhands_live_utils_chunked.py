"""OpenHands 0.54 SWE-bench Live completion hook with lossless patch capture.

This is the upstream ``evaluation/benchmarks/swe_bench/live_utils.py`` hook
with one deliberate change: the final staged diff is read from the runtime in
12 KiB base64 chunks. OpenHands truncates a single ``CmdOutputObservation`` at
``llm.max_message_chars`` (30,000 by default), which otherwise corrupts large
submission patches.
"""

from __future__ import annotations

import base64
from typing import Any

import pandas as pd
from evaluation.utils.shared import assert_and_raise
from openhands.core.logger import openhands_logger as logger
from openhands.events.action import CmdRunAction
from openhands.events.observation import CmdOutputObservation
from openhands.runtime.base import Runtime

_PATCH_PATH = "/tmp/openhands-swe-live.patch"
_CHUNK_BYTES = 12 * 1024


def _run(runtime: Runtime, command: str, timeout: int = 600) -> CmdOutputObservation:
    action = CmdRunAction(command=command)
    action.set_hard_timeout(timeout)
    logger.info(action, extra={"msg_type": "ACTION"})
    observation = runtime.run_action(action)
    logger.info(observation, extra={"msg_type": "OBSERVATION"})
    assert_and_raise(
        isinstance(observation, CmdOutputObservation)
        and observation.exit_code == 0,
        f"Command failed while capturing the final patch: {observation}",
    )
    return observation


def _read_patch(runtime: Runtime, base_commit: str) -> str:
    size_observation = _run(
        runtime,
        f"git diff --no-color --cached {base_commit} > {_PATCH_PATH} "
        f"&& wc -c < {_PATCH_PATH}",
    )
    size = int(size_observation.content.strip().splitlines()[-1])
    chunks: list[bytes] = []

    for offset in range(0, size, _CHUNK_BYTES):
        count = min(_CHUNK_BYTES, size - offset)
        command = (
            "python -c \"import base64; "
            f"f=open('{_PATCH_PATH}','rb'); f.seek({offset}); "
            f"print(base64.b64encode(f.read({count})).decode())\""
        )
        observation = _run(runtime, command)
        chunks.append(base64.b64decode(observation.content.strip(), validate=True))

    patch_bytes = b"".join(chunks)
    assert_and_raise(
        len(patch_bytes) == size,
        f"Final patch byte count mismatch: expected {size}, got {len(patch_bytes)}",
    )
    return patch_bytes.decode("utf-8", errors="replace").strip()


def complete_runtime(runtime: Runtime, instance: pd.Series) -> dict[str, Any]:
    """Complete the runtime and export the full git patch for SWE-bench Live."""
    logger.info("-" * 30)
    logger.info("BEGIN Runtime Completion Fn (chunked patch capture)")
    logger.info("-" * 30)

    workspace_dir_name = instance.instance_id
    _run(runtime, f"cd /workspace/{workspace_dir_name}")
    _run(runtime, 'git config --global core.pager ""')
    _run(runtime, "git add -A")
    git_patch = _read_patch(runtime, str(instance["base_commit"]))

    logger.info("-" * 30)
    logger.info("END Runtime Completion Fn (chunked patch capture)")
    logger.info("-" * 30)
    return {"git_patch": git_patch}
