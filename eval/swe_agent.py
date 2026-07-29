"""SWE-bench Verified adapter (Harbor installed agent).

Harbor's hub hosts `swebench-verified@1.0` (500 tasks; also `swebench_multilingual@1.0`,
`swesmith@1.0`) as ordinary Harbor tasks: each task's environment is the official
`swebench/sweb.eval.x86_64.*` image with the repo checked out at /testbed, the
instruction is the raw GitHub issue text, and the verifier grades the CONTAINER STATE
in place — it resets the test files to the base commit, runs `git clean -fd`, applies
the official test patch, runs the suite, and scores with `swebench.harness.grading`.
There is no predictions JSONL and no patch file to submit: whatever the agent leaves
in /testbed *is* the submission.

Two consequences drive this adapter:

1. Because the verifier runs `git clean -fd` before grading, any NEW file the agent
   creates must be in the git index to survive. After the agent finishes we stage
   everything (`git add -A`) — gitignored junk (*.pyc, __pycache__) is skipped by
   git itself, and GT's per-task `.gt/` index dir is removed first so it is neither
   staged nor graded.
2. The staged diff (`git diff --cached`) is therefore the canonical "model patch"
   (it includes new-file contents, which plain `git diff` would miss); we save it to
   /logs/agent/model_patch.diff for failure-case analysis. Grading never reads it.

Usage (host needs Docker running):

    pip install harbor
    export ANTHROPIC_API_KEY=...
    # Baseline arm (stock nano, GT off):
    harbor run -d swebench-verified@1.0 \
        -a eval.swe_agent:NanoSweAgent \
        -m anthropic/claude-opus-4-8 \
        -l 5 -n 2 -o results/swebench --job-name swe-smoke -y
    # GT arm (same adapter; the ONLY difference is the flag):
    #   ... --ak gt_root=/testbed        (or --ae NANO_GT_ROOT=/testbed)

Results land in results/swebench/<job-name>/; per-task agent stdout in
<task>/agent/nano.txt, the staged model patch in <task>/agent/model_patch.diff,
and the verifier's swebench report in <task>/verifier/report.json.
"""
from __future__ import annotations

import os
import shlex
from pathlib import Path

from harbor.agents.installed.base import (
    BaseInstalledAgent,
    CliFlag,
    with_prompt_template,
)
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

_REPO_ROOT = Path(__file__).resolve().parent.parent
_REMOTE_DIR = "/installed-agent/nano-harness"
_WORKDIR = "/testbed"  # SWE-bench convention, baked into the task images/verifiers

# SWE-bench images are conda-based Ubuntu, but keep the tb_agent hardening: make
# sure curl exists, then let uv bring its own Python so we never depend on the
# image's python3 (the /testbed conda env is the TASK's env — do not touch it).
_ENSURE_CURL = (
    "command -v curl >/dev/null 2>&1 || { "
    "command -v apt-get >/dev/null && apt-get update && apt-get install -y curl; } || { "
    "command -v apk >/dev/null && apk add --no-cache curl bash; } || { "
    "command -v dnf >/dev/null && dnf install -y curl; } || { "
    "command -v yum >/dev/null && yum install -y curl; }"
)

_INSTALL_NANO = (
    "set -eu; "
    "curl -LsSf https://astral.sh/uv/install.sh | sh && "
    f'"$HOME/.local/bin/uv" tool install --python 3.12 {_REMOTE_DIR} && '
    '"$HOME/.local/bin/nano" --help >/dev/null'
)

# Minimal, benchmark-agnostic task frame around the raw issue text. No task-id
# logic, no gold hints, no test names — the model gets exactly what a developer
# reading the issue would get, plus where the repo is and the no-test-edits rule.
_TASK_TEMPLATE = """\
You are working in a git repository checked out at {workdir}. The repository has \
an issue, reported below. Fix it by editing the source code.

<issue>
{issue}
</issue>

Guidelines:
- Explore the repository, locate the root cause, and make the smallest change that \
resolves the issue.
- Do NOT modify any test files. Your fix will be judged by the repository's own tests.
- You may run code or existing tests to verify your fix.
- Leave your changes in the working tree (no commit needed) when you are done."""

# Post-run snapshot, run best-effort even if the agent errored: drop GT's index
# dir, stage everything that survived .gitignore (new files must be in the index
# or the verifier's `git clean -fd` deletes them), and save the staged diff as
# the model patch for analysis.
_SNAPSHOT = (
    f"cd {_WORKDIR} && "
    "rm -rf .gt && "
    "git add -A -- . "
    "':(exclude,glob)**/*.pyc' ':(exclude,glob)**/__pycache__' ':(exclude)node_modules' "
    "2>/dev/null; "
    "git -c core.quotepath=false diff --cached > /logs/agent/model_patch.diff 2>/dev/null "
    "|| true"
)


class NanoSweAgent(BaseInstalledAgent):
    """nano-harness as a SWE-bench (Harbor) agent. The loop, tools, and system
    prompt are exactly what `nano run` ships locally — no benchmark forks.

    GT arm: pass ``gt_root`` (agent kwarg ``--ak gt_root=/testbed`` or env
    ``NANO_GT_ROOT``) and the same adapter runs ``nano run --gt-root <path>``.
    Default is OFF — a run without the flag is byte-identical stock nano.
    """

    # gt_root rides Harbor's declarative flag machinery: --ak gt_root=/testbed on
    # the CLI, NANO_GT_ROOT as the env fallback, absent by default (baseline arm).
    CLI_FLAGS = [
        CliFlag(kwarg="gt_root", cli="--gt-root", type="str", env_fallback="NANO_GT_ROOT"),
    ]

    @staticmethod
    def name() -> str:
        return "nano-swe"

    def get_version_command(self) -> str | None:
        return (
            f'"$HOME/.local/bin/uv" tool run --from {_REMOTE_DIR} '
            "python -c \"import nano; print(nano.__version__)\""
        )

    async def install(self, environment: BaseEnvironment) -> None:
        # TODO(gt): when the GT arm goes live in containers, also upload
        # gt_engine/ + the groundtruth package (or a wheel) and the gt-index
        # binary here, mirroring eval/tb_agent.py's plumbing. Until then a
        # gt_root run degrades to stock nano inside the container (nano's
        # bridge import is fail-open) — see the marker line in run().
        await environment.upload_dir(_REPO_ROOT / "nano", f"{_REMOTE_DIR}/nano")
        await environment.upload_dir(_REPO_ROOT / "eval", f"{_REMOTE_DIR}/eval")
        await environment.upload_file(
            _REPO_ROOT / "pyproject.toml", f"{_REMOTE_DIR}/pyproject.toml"
        )
        await self.exec_as_root(
            environment, _ENSURE_CURL, env={"DEBIAN_FRONTEND": "noninteractive"}
        )
        await self.exec_as_agent(environment, _INSTALL_NANO)

    @with_prompt_template
    async def run(
        self, instruction: str, environment: BaseEnvironment, context: AgentContext
    ) -> None:
        # Harbor model names look like "anthropic/claude-opus-4-7"; nano's
        # provider routing wants the bare model name. Exception: when routing
        # through an OpenAI-compatible gateway (OPENAI_BASE_URL set), the full
        # "provider/name" string IS the gateway's model id - pass it through.
        model = self.model_name or "anthropic/claude-opus-4-7"
        if not os.environ.get("OPENAI_BASE_URL"):
            model = model.split("/", 1)[-1]
        env = {
            k: v
            for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL")
            if (v := os.environ.get(k))
        }
        task = _TASK_TEMPLATE.format(workdir=_WORKDIR, issue=instruction)
        gt_flags = self.build_cli_flags()  # "" (baseline) or "--gt-root <path>"
        marker = (
            f"echo '[swe_agent] GT arm requested ({gt_flags})'; " if gt_flags else ""
        )
        # `|| true` on the nano run: a partial run (max_iterations) may still
        # pass the tests — never let the agent's exit code abort the trial
        # before grading. The snapshot runs unconditionally for the same reason.
        await self.exec_as_agent(
            environment,
            f"cd {_WORKDIR} && {marker}"
            f'"$HOME/.local/bin/nano" run {shlex.quote(task)} '
            f"--model {shlex.quote(model)} --max-iterations 100 "
            f"{gt_flags} "
            "</dev/null 2>&1 | tee /logs/agent/nano.txt || true",
            env=env,
        )
        await self.exec_as_agent(environment, _SNAPSHOT)
