"""The space-bunny baseline's Harbor agent, and the same agent with GT attached.

``MiniSweBaselineAgent`` reproduces the installed agent that produced the
GT-off baselines (embed-bakeoff eval/miniswe_agent.py at 8e94abf9 / 086fb8e5):
``uv tool install`` on Python 3.12.13 with mini-swe-agent 2.3.0, the runner run
directly (no supervisor), ``--temperature 1.0``, ``GT_STEP_LIMIT`` forwarded.

``MiniSweThinGtAgent`` installs the identical bundle and differs in two places,
the GitNexus shape (abhigyanpatwari/GitNexus eval/): the task's graph is built
during install (GitNexus ``env.start()``: outside the agent's time), and the
runner is started without ``--gt-off``, which gives GTAttachedAgent - the
stock DefaultAgent with GT blocks appended to its own observations.
"""
from __future__ import annotations

import hashlib
import io
import os
import shlex
import tarfile
import tempfile
import urllib.request
from pathlib import Path

from harbor.agents.installed.base import BaseInstalledAgent, with_prompt_template
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

from eval._env import UTF8_ENV, provider_env
from eval.miniswe_agent import MiniSweAgent as _CertifiedBundle

_REPO_ROOT = Path(__file__).resolve().parent.parent
_REMOTE_DIR = "/installed-agent/miniswe"
_REMOTE_RUNNER = "/installed-agent/miniswe_run.py"
_REMOTE_REPRO = "/installed-agent/miniswe_repro_baseline.py"
_REMOTE_GT_BINARY = "/installed-agent/gt-index"
_REMOTE_PY = "$HOME/.local/share/uv/tools/nano-harness/bin/python"
_UV_VERSION = "0.11.32"
_PYTHON_VERSION = "3.12.13"
# The version every space-bunny GT-off trajectory records (info.mini_version).
MINISWE_AGENT_VERSION = "2.3.0"
_UV_RELEASE = f"https://github.com/astral-sh/uv/releases/download/{_UV_VERSION}/uv-x86_64-unknown-linux-musl.tar.gz"
_REMOTE_UV = "/installed-agent/uv"
_STATE_DIR = "/logs/agent/gt-state"
_BASELINE_PROVIDER_VARS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL")
# Harbor 0.20.0 gives agent setup 360 s (harbor/trial/trial.py). The thin
# arm's setup also builds the graph, so its launch passes
# --agent-setup-timeout-multiplier SETUP_TIMEOUT_MULTIPLIER; the agent's own
# timeout multiplier stays 1.0, exactly as the baseline.
SETUP_TIMEOUT_MULTIPLIER = 3.5
# GitNexus gives `gitnexus analyze` 120 s; a GT graph of a large repository
# takes longer, and a build that does not finish is finished by the run.
PREBUILD_TIMEOUT_SECONDS = 900
_STAGED_SOURCE_CLEANUP = (
    f"cp {_REMOTE_DIR}/scripts/miniswe_thin_run.py {_REMOTE_RUNNER} && "
    f"cp {_REMOTE_DIR}/scripts/miniswe_repro_baseline.py {_REMOTE_REPRO} && "
    f"chmod +x {_REMOTE_RUNNER} && "
    f"rm -rf -- {_REMOTE_DIR}"
)
# Best effort only: uv arrives from the host (_uv_binary_host), so an image whose
# package mirror is gone (TB2 qemu-*: Debian 11 security pool 404s) still installs.
_ENSURE_CURL = (
    "command -v curl >/dev/null 2>&1 || { "
    "command -v apt-get >/dev/null && apt-get update && apt-get install -y curl; } || { "
    "command -v apk >/dev/null && apk add --no-cache curl bash; } || { "
    "command -v dnf >/dev/null && dnf install -y curl; } || { "
    "command -v yum >/dev/null && yum install -y curl; } || true"
)


def _uv_binary_host() -> Path:
    """The pinned static uv binary, fetched once on the host and checked against its release sha256."""
    cache = Path(tempfile.gettempdir()) / f"uv-{_UV_VERSION}-musl"
    binary = cache / "uv"
    if binary.is_file():
        return binary
    cache.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(_UV_RELEASE, timeout=120) as response:
        archive = response.read()
    with urllib.request.urlopen(_UV_RELEASE + ".sha256", timeout=60) as response:
        expected = response.read().decode("ascii").split()[0].lower()
    actual = hashlib.sha256(archive).hexdigest()
    if actual != expected:
        raise RuntimeError(f"uv {_UV_VERSION} archive sha256 {actual} != published {expected}")
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        member = next(m for m in tar.getmembers() if m.isfile() and m.name.endswith("/uv"))
        handle = tar.extractfile(member)
        if handle is None:
            raise RuntimeError(f"uv {_UV_VERSION} archive has no readable uv binary")
        data = handle.read()
    partial = binary.with_suffix(".partial")
    partial.write_bytes(data)
    partial.chmod(0o755)
    partial.replace(binary)
    return binary


class MiniSweBaselineAgent(BaseInstalledAgent):
    """The GT-off baseline's installed agent (stock loop, ``--gt-off``)."""

    @staticmethod
    def name() -> str:
        return "miniswe-baseline"

    def get_version_command(self) -> str | None:
        return f'"{_REMOTE_PY}" -c "import minisweagent; print(minisweagent.__version__)"'

    async def install(self, environment: BaseEnvironment) -> None:
        wheel = _CertifiedBundle._gt_wheel()
        binary = _CertifiedBundle._gt_binary_host()
        await environment.upload_dir(_REPO_ROOT / "scripts", f"{_REMOTE_DIR}/scripts")
        await environment.upload_dir(_REPO_ROOT / "eval", f"{_REMOTE_DIR}/eval")
        await environment.upload_dir(_REPO_ROOT / "gt_engine", f"{_REMOTE_DIR}/gt_engine")
        await environment.upload_dir(_REPO_ROOT / "gt_harness", f"{_REMOTE_DIR}/gt_harness")
        await environment.upload_dir(_REPO_ROOT / "nano", f"{_REMOTE_DIR}/nano")
        await environment.upload_dir(_REPO_ROOT / "config", f"{_REMOTE_DIR}/config")
        await environment.upload_file(_REPO_ROOT / "pyproject.toml", f"{_REMOTE_DIR}/pyproject.toml")
        remote_wheel = f"{_REMOTE_DIR}/{wheel.name}"
        await environment.upload_file(wheel, remote_wheel)
        await environment.upload_file(binary, _REMOTE_GT_BINARY)
        await environment.upload_file(_uv_binary_host(), _REMOTE_UV)
        await self.exec_as_root(environment, _ENSURE_CURL, env={"DEBIAN_FRONTEND": "noninteractive"})
        await self.exec_as_root(environment, f"chmod 755 {_REMOTE_GT_BINARY} {_REMOTE_UV}")
        install = (
            "set -eu; "
            f'"{_REMOTE_UV}" tool install --python {_PYTHON_VERSION} '
            f'--with "mini-swe-agent=={MINISWE_AGENT_VERSION}" '
            f"--with {shlex.quote(remote_wheel)} --with 'numpy==2.5.1' "
            f"{_REMOTE_DIR} && "
            f'"{_REMOTE_PY}" -c "import importlib.metadata as m, sys; '
            "assert sys.version_info[:3] == (3, 12, 13); "
            f"assert m.version('mini-swe-agent') == '{MINISWE_AGENT_VERSION}'; "
            "assert m.version('groundtruth-mcp') == '1.0.0'; "
            "import minisweagent, groundtruth, gt_engine" + '" && '
            'rm -rf "$HOME/.cache/uv/archive-v0" && '
            f"{_STAGED_SOURCE_CLEANUP}"
        )
        await self.exec_as_agent(environment, install, env=dict(UTF8_ENV))

    def _model_and_env(self) -> tuple[str, dict[str, str]]:
        model = str(self.model_name or "").strip()
        if not model:
            raise ValueError("model_name is required")
        if not os.environ.get("OPENAI_BASE_URL"):
            model = model.split("/", 1)[-1]
        # The baseline forwarded exactly these three (embed-bakeoff eval/_env.py).
        env = {name: value for name, value in provider_env().items() if name in _BASELINE_PROVIDER_VARS}
        env.update(UTF8_ENV)
        return model, env

    def _run_command(self, instruction: str, model: str, extra_args: str = "") -> str:
        return (
            f'"{_REMOTE_PY}" {_REMOTE_RUNNER} '
            f"--task {shlex.quote(instruction)} --model {shlex.quote(model)} "
            f"--cwd \"$PWD\" "
            f"--output /logs/agent/miniswe_trajectory.json "
            f"--temperature 1.0 "
            f"--metrics /logs/agent/miniswe_report.json "
            '${GT_STEP_LIMIT:+--step-limit $GT_STEP_LIMIT} '
            f"{extra_args}"
            "</dev/null 2>&1"
        )

    @with_prompt_template
    async def run(self, instruction: str, environment: BaseEnvironment, context: AgentContext) -> None:
        model, env = self._model_and_env()
        await self.exec_as_agent(
            environment,
            self._run_command(instruction, model, extra_args=f"--gt-off --state-dir {_STATE_DIR} "),
            env=env,
        )


def prebuild_command(python: str = f'"{_REMOTE_PY}"', state_dir: str = _STATE_DIR) -> str:
    """The install-time graph build, only inside a git work tree: TB2 workspaces
    without a repository (an ISO, a CSV, one C file) spent setup building a
    graph no step used (gt_engine.workspace_gate). Skips only when git itself
    says there is no repository; any other git failure still builds. Never
    fails the install."""
    return (
        "if git -c safe.directory='*' rev-parse --is-inside-work-tree 2>&1 "
        "| grep -q 'not a git repository'; then "
        'echo "gt prebuild skipped: no git work tree"; '
        f'else timeout {PREBUILD_TIMEOUT_SECONDS} {python} -m gt_engine.thin_agent prebuild '
        f'--cwd "$PWD" --state-dir {state_dir} </dev/null 2>&1 || true; fi'
    )


class MiniSweThinGtAgent(MiniSweBaselineAgent):
    """The baseline agent with GT attached (gt_engine.thin_agent)."""

    @staticmethod
    def name() -> str:
        return "miniswe-gt-thin"

    def _gt_env(self) -> dict[str, str]:
        return {"GT_INDEX_BINARY": _REMOTE_GT_BINARY, "GT_STATE_DIR": _STATE_DIR}

    async def install(self, environment: BaseEnvironment) -> None:
        await super().install(environment)
        # GitNexus env.start(): the graph is built before the agent runs. The
        # run reuses it (the cache is keyed by workspace path and source
        # manifest); if this fails or times out, the run builds it itself.
        await self.exec_as_agent(environment, prebuild_command(), env={**UTF8_ENV, **self._gt_env()})

    @with_prompt_template
    async def run(self, instruction: str, environment: BaseEnvironment, context: AgentContext) -> None:
        model, env = self._model_and_env()
        env.update(self._gt_env())
        await self.exec_as_agent(
            environment,
            self._run_command(instruction, model, extra_args=f"--state-dir {_STATE_DIR} "),
            env=env,
        )
