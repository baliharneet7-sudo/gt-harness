"""Host-owned Mini-SWE runtime for GT-on Terminal-Bench experiments.

Unlike the legacy installed agents, this agent keeps provider access, private
state, policy, and source on the Harbor host.  The task container receives
only literal model-selected shell commands plus host-only observation probes
whose output is never added to model context.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from harbor.agents.base import BaseAgent
from harbor.environments.base import BaseEnvironment, ExecResult
from harbor.models.agent.context import AgentContext
from harbor.models.trajectories import (
    Agent,
    FinalMetrics,
    Metrics,
    Observation,
    ObservationResult,
    Step,
    ToolCall,
    Trajectory,
)
from harbor.utils.trajectory_utils import format_trajectory_json
from jinja2 import StrictUndefined, Template
from minisweagent.config import builtin_config_dir
from minisweagent.exceptions import InterruptAgentFlow
from minisweagent.models.litellm_model import BASH_TOOL, LitellmModel

from gt_engine.central_runtime import (
    EvidenceLedger,
    InterventionDecision,
    WorkspaceSensor,
    diff_snapshots,
    explicit_check_commands,
    is_check_command,
    is_grounded_check,
    is_submit_command,
    lint_commands,
    render_runtime_feedback,
)


def _mini_config() -> dict[str, Any]:
    import yaml

    return yaml.safe_load((builtin_config_dir / "mini.yaml").read_text(encoding="utf-8"))


class MiniSweCentralAgent(BaseAgent):
    """GT-on treatment: central state plus bounded model-visible interventions."""

    runtime_mode = "treatment"
    SUPPORTS_ATIF = True

    def __init__(
        self,
        logs_dir: Path,
        model_name: str | None = None,
        *,
        cwd: str = "/app",
        temperature: float = 1.0,
        step_limit: int = 100,
        command_timeout_sec: int = 30,
        cost_limit: float = 3.0,
        max_submit_holds: int = 1,
        enable_lint: bool = True,
        enable_submit_readiness: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(logs_dir, model_name, **kwargs)
        if not model_name:
            raise ValueError("model_name is required")
        self.cwd = cwd
        self.temperature = temperature
        self.step_limit = step_limit
        self.command_timeout_sec = command_timeout_sec
        self.cost_limit = cost_limit
        self.enable_lint = enable_lint
        self.enable_submit_readiness = enable_submit_readiness
        self._ledger = EvidenceLedger(max_holds=max_submit_holds)
        self._sensor = WorkspaceSensor()
        self._model_factory: Callable[[], Any] = self._build_model

    @staticmethod
    def name() -> str:
        return "miniswe-central"

    def version(self) -> str | None:
        return "host-central-v1"

    async def setup(self, environment: BaseEnvironment) -> None:
        """No install by design: task images contain no private runtime artifact."""

    def _build_model(self) -> LitellmModel:
        assert self.model_name is not None
        model = self.model_name
        kwargs: dict[str, Any] = {"temperature": self.temperature}
        api_base = (os.environ.get("OPENAI_BASE_URL") or "").strip()
        if api_base:
            if "/" not in model:
                model = f"openai/{model}"
            kwargs["api_base"] = api_base
        return LitellmModel(
            model_name=model,
            model_kwargs=kwargs,
            cost_tracking="ignore_errors",
        )

    async def _system_information(self, environment: BaseEnvironment) -> dict[str, str]:
        try:
            result = await environment.exec(
                "uname -s; uname -r; uname -v; uname -m",
                cwd=self.cwd,
                env={},
                timeout_sec=5,
            )
        except Exception:
            result = ExecResult(stdout="Linux\n\n\n\n", return_code=-1)
        values = (result.stdout or "").strip().splitlines()
        if len(values) == 1 and "\t" in values[0]:
            values = values[0].split("\t")
        values += [""] * (4 - len(values))
        return dict(zip(("system", "release", "version", "machine"), values[:4], strict=True))

    @staticmethod
    def _render(template: str, variables: dict[str, Any]) -> str:
        return Template(template, undefined=StrictUndefined).render(**variables)

    async def _run_lint(
        self,
        environment: BaseEnvironment,
        changed_paths: tuple[str, ...],
        revision: str,
    ) -> str:
        for path, command in lint_commands(changed_paths):
            try:
                result = await environment.exec(
                    command,
                    cwd=self.cwd,
                    env={},
                    timeout_sec=10,
                )
            except Exception:
                continue
            if result.return_code != 0:
                raw = " ".join(((result.stderr or "") + " " + (result.stdout or "")).split())
                detail = f"{path} has a fresh syntax error: {raw or 'syntax check failed'}"
                self._ledger.record_check(
                    f"syntax:{path}",
                    returncode=result.return_code,
                    revision=revision,
                    grounded=True,
                )
                return render_runtime_feedback(detail)
            self._ledger.record_check(
                f"syntax:{path}", returncode=0, revision=revision, grounded=True
            )
        return ""

    def _write_atif(
        self,
        messages: list[dict[str, Any]],
        *,
        input_tokens: int,
        output_tokens: int,
        cache_tokens: int,
        cost: float,
        calls: int,
    ) -> None:
        steps: list[Step] = []
        index = 0
        while index < len(messages):
            message = messages[index]
            role = message.get("role")
            if role == "exit":
                index += 1
                continue
            if role in {"system", "user"}:
                steps.append(
                    Step(
                        step_id=len(steps) + 1,
                        timestamp=datetime.now(UTC).isoformat(),
                        source=role,
                        message=str(message.get("content") or ""),
                        llm_call_count=0,
                    )
                )
                index += 1
                continue
            if role != "assistant":
                index += 1
                continue

            extra = message.get("extra") or {}
            actions = tuple(extra.get("actions") or ())
            response = extra.get("response") or {}
            usage = response.get("usage") or {}
            tool_calls = [
                ToolCall(
                    tool_call_id=str(action.get("tool_call_id") or f"call-{index}-{n}"),
                    function_name="bash",
                    arguments={"command": str(action.get("command") or "")},
                )
                for n, action in enumerate(actions, start=1)
            ]
            observations: list[ObservationResult] = []
            cursor = index + 1
            while cursor < len(messages) and messages[cursor].get("role") == "tool":
                tool_message = messages[cursor]
                observations.append(
                    ObservationResult(
                        source_call_id=str(tool_message.get("tool_call_id") or "") or None,
                        content=str(tool_message.get("content") or ""),
                    )
                )
                cursor += 1
            raw_choice = ((response.get("choices") or [{}])[0].get("message") or {})
            steps.append(
                Step(
                    step_id=len(steps) + 1,
                    timestamp=datetime.now(UTC).isoformat(),
                    source="agent",
                    model_name=str(response.get("model") or self.model_name or ""),
                    message=str(message.get("content") or ""),
                    reasoning_content=(
                        message.get("reasoning_content")
                        or raw_choice.get("reasoning_content")
                        or None
                    ),
                    tool_calls=tool_calls or None,
                    observation=Observation(results=observations) if observations else None,
                    metrics=Metrics(
                        prompt_tokens=int(usage.get("prompt_tokens") or 0),
                        completion_tokens=int(usage.get("completion_tokens") or 0),
                        cached_tokens=int(
                            usage.get("prompt_cache_hit_tokens")
                            or (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
                            or 0
                        ),
                        cost_usd=float(extra.get("cost") or 0.0),
                    ),
                    llm_call_count=1,
                )
            )
            index = cursor

        trajectory = Trajectory(
            # Harbor 0.20's BaseAgent does not initialize session_id when an
            # agent is constructed directly (as provider-free tests and some
            # third-party runners do).  ATIF permits a null session id, so do
            # not make trajectory emission depend on runner-owned injection.
            session_id=getattr(self, "session_id", None),
            agent=Agent(
                name=self.name(),
                version=self.version() or "unknown",
                model_name=self.model_name,
                tool_definitions=[BASH_TOOL],
                extra={"runtime_mode": self.runtime_mode},
            ),
            steps=steps,
            notes="Private runtime receipts are stored separately and are not model context.",
            final_metrics=FinalMetrics(
                total_prompt_tokens=input_tokens,
                total_completion_tokens=output_tokens,
                total_cached_tokens=cache_tokens,
                total_cost_usd=cost,
                total_steps=len(steps),
                extra={"llm_calls": calls},
            ),
        )
        (self.logs_dir / "trajectory.json").write_text(
            format_trajectory_json(trajectory.to_json_dict()), encoding="utf-8"
        )

    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        config = _mini_config()
        model = self._model_factory()
        system_info = await self._system_information(environment)
        variables = {
            "task": instruction,
            **system_info,
            **config["agent"],
            **config["model"],
        }
        messages = [
            model.format_message(
                role="system",
                content=self._render(str(config["agent"]["system_template"]), variables),
            ),
            model.format_message(
                role="user",
                content=self._render(str(config["agent"]["instance_template"]), variables),
            ),
        ]
        explicit_checks = explicit_check_commands(instruction)
        snapshot = await self._sensor.scan(environment, cwd=self.cwd)
        calls = 0
        actions_count = 0
        input_tokens = output_tokens = cache_tokens = 0
        cost = 0.0
        terminal = ""
        started = time.monotonic()
        receipts: list[dict[str, Any]] = []

        try:
            while calls < self.step_limit and not terminal and cost < self.cost_limit:
                calls += 1
                try:
                    message = await asyncio.to_thread(model.query, messages)
                except InterruptAgentFlow as flow:
                    messages.extend(flow.messages)
                    continue
                messages.append(message)
                extra = message.get("extra") or {}
                cost += float(extra.get("cost") or 0.0)
                usage = ((extra.get("response") or {}).get("usage") or {})
                input_tokens += int(usage.get("prompt_tokens") or 0)
                output_tokens += int(usage.get("completion_tokens") or 0)
                cache_tokens += int(
                    usage.get("prompt_cache_hit_tokens")
                    or (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
                    or 0
                )
                actions = tuple(extra.get("actions") or ())
                outputs: list[dict[str, Any]] = []

                for action in actions:
                    actions_count += 1
                    command = str(action.get("command") or "")
                    submit = is_submit_command(command)
                    if submit and self.enable_submit_readiness:
                        decision = self._ledger.submit_decision(
                            snapshot.revision, sensor_healthy=snapshot.healthy
                        )
                        if (
                            self.runtime_mode == "treatment"
                            and decision.decision == InterventionDecision.HOLD_ONCE
                        ):
                            detail = "A fresh required check is still failing: " + ", ".join(
                                decision.blockers
                            )
                            outputs.append(
                                {
                                    "output": render_runtime_feedback(detail),
                                    "returncode": 2,
                                    "exception_info": "action was not executed",
                                }
                            )
                            receipts.append(
                                {
                                    "action": actions_count,
                                    "kind": "submit_readiness",
                                    "decision": "HOLD_ONCE",
                                    "revision": snapshot.revision,
                                }
                            )
                            continue
                        receipts.append(
                            {
                                "action": actions_count,
                                "kind": "submit_readiness",
                                "decision": (
                                    "SHADOW"
                                    if self.runtime_mode == "shadow"
                                    and decision.decision == InterventionDecision.HOLD_ONCE
                                    else "PASS"
                                ),
                                "revision": snapshot.revision,
                            }
                        )

                    try:
                        result = await environment.exec(
                            command,
                            cwd=self.cwd,
                            env={},
                            timeout_sec=self.command_timeout_sec,
                        )
                    except Exception as exc:
                        result = ExecResult(
                            stdout="",
                            stderr=f"{type(exc).__name__}: {exc}",
                            return_code=-1,
                        )
                    output = {
                        "output": (result.stdout or "") + (result.stderr or ""),
                        "returncode": result.return_code,
                        "exception_info": "",
                    }
                    after = await self._sensor.scan(
                        environment, cwd=self.cwd, previous=snapshot
                    )
                    transition = diff_snapshots(
                        snapshot,
                        after,
                        action_id=actions_count,
                        command=command,
                    )
                    snapshot = after

                    if is_check_command(command):
                        self._ledger.record_check(
                            command,
                            returncode=result.return_code,
                            revision=snapshot.revision,
                            grounded=is_grounded_check(command, explicit_checks),
                        )

                    lint_feedback = ""
                    changed_files = tuple(
                        path
                        for path in transition.changed_paths
                        if path in snapshot.entries and snapshot.entries[path].kind == "f"
                    )
                    if self.enable_lint and changed_files and snapshot.healthy:
                        lint_feedback = await self._run_lint(
                            environment, changed_files, snapshot.revision
                        )
                        receipts.append(
                            {
                                "action": actions_count,
                                "kind": "changed_file_lint",
                                "decision": (
                                    "ADVISE"
                                    if lint_feedback and self.runtime_mode == "treatment"
                                    else "SHADOW" if lint_feedback else "PASS"
                                ),
                                "revision": snapshot.revision,
                                "paths": list(changed_files),
                            }
                        )
                    if lint_feedback and self.runtime_mode == "treatment":
                        output["output"] = lint_feedback + "\n" + output["output"]
                    outputs.append(output)
                    if submit:
                        terminal = "Submitted"
                        break

                messages.extend(
                    model.format_observation_messages(message, outputs, variables)
                )

            if not terminal:
                terminal = "LimitsExceeded"
        except Exception as exc:
            terminal = type(exc).__name__
            messages.append(
                model.format_message(
                    role="exit",
                    content=str(exc),
                    extra={"exit_status": terminal, "submission": ""},
                )
            )
            raise
        finally:
            if not messages or messages[-1].get("role") != "exit":
                messages.append(
                    model.format_message(
                        role="exit",
                        content="",
                        extra={"exit_status": terminal, "submission": ""},
                    )
                )
            self.logs_dir.mkdir(parents=True, exist_ok=True)
            trajectory = {
                "info": {
                    "model_stats": {"instance_cost": cost, "api_calls": calls},
                    "agent": self.name(),
                    "version": self.version(),
                    "exit_status": terminal,
                },
                "messages": messages,
                "trajectory_format": "mini-swe-agent-1.1",
            }
            (self.logs_dir / "miniswe_trajectory.json").write_text(
                json.dumps(trajectory, indent=2), encoding="utf-8"
            )
            (self.logs_dir / "central_receipt.json").write_text(
                json.dumps(
                    {
                        "schema": "central-runtime-receipt-v1",
                        "mode": self.runtime_mode,
                        "calls": calls,
                        "actions": actions_count,
                        "elapsed_seconds": time.monotonic() - started,
                        "workspace_sensor_healthy": snapshot.healthy,
                        "workspace_sensor_reason": snapshot.reason,
                        "interventions": receipts,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            self._write_atif(
                messages,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_tokens=cache_tokens,
                cost=cost,
                calls=calls,
            )
            context.n_input_tokens = input_tokens
            context.n_output_tokens = output_tokens
            context.n_cache_tokens = cache_tokens
            context.cost_usd = cost
            context.metadata = {
                "runtime_mode": self.runtime_mode,
                "api_calls": calls,
                "actions": actions_count,
                "exit_status": terminal,
                "workspace_sensor_healthy": snapshot.healthy,
            }


class MiniSweCentralShadowAgent(MiniSweCentralAgent):
    """GT-on core arm: private state active, every candidate stays shadowed."""

    runtime_mode = "shadow"

    @staticmethod
    def name() -> str:
        return "miniswe-central-shadow"
