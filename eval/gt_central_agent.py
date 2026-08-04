"""Host-owned Mini-SWE runtime for GT-on Terminal-Bench experiments.

Unlike the legacy installed agents, this agent keeps provider access, private
state, policy, and source on the Harbor host.  The task container receives
only literal model-selected shell commands plus host-only observation probes
whose output is never added to model context.
"""

from __future__ import annotations

import asyncio
import hashlib
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
    CentralFeatureRuntime,
    EvidenceLedger,
    InterventionDecision,
    WorkspaceSensor,
    classify_validation_command,
    diff_snapshots,
    explicit_check_commands,
    is_check_command,
    is_submit_command,
    lint_commands,
    source_revision_of,
    task_deliverable_paths,
)
from gt_engine.deep_metrics import normalized_token_cost


def _message_context_chars(message: dict[str, Any]) -> int:
    """Count assistant fields that are retained in the next provider request."""
    text = str(message.get("content") or "") + str(message.get("reasoning_content") or "")
    for key in ("tool_calls", "function_call"):
        value = message.get(key)
        if value:
            text += json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return len(text)


def _inject_runtime_evidence(
    messages: list[dict[str, Any]], evidence: str
) -> tuple[list[dict[str, Any]], int, int]:
    """Place evidence in the next normal observation without mutating history."""
    prepared = [dict(item) for item in messages]
    for index in range(len(prepared) - 1, -1, -1):
        if prepared[index].get("role") != "tool":
            continue
        separator = "\n\n"
        prepared[index]["content"] = (
            str(prepared[index].get("content") or "") + separator + evidence
        )
        return prepared, index, len(separator) + len(evidence)
    prepared.append({"role": "user", "content": evidence})
    return prepared, len(prepared) - 1, len(evidence)


def _mini_config() -> dict[str, Any]:
    import yaml

    return yaml.safe_load((builtin_config_dir / "mini.yaml").read_text(encoding="utf-8"))


class MiniSweCentralAgent(BaseAgent):
    """GT-on treatment: deterministic state plus bounded next-request evidence."""

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
        model_timeout_sec: int = 120,
        model_loop_timeout_sec: int = 900,
        cost_limit: float = 3.0,
        max_submit_holds: int = 1,
        enable_lint: bool = True,
        enable_submit_readiness: bool = True,
        enable_all_features: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(logs_dir, model_name, **kwargs)
        if not model_name:
            raise ValueError("model_name is required")
        self.cwd = cwd
        self.temperature = temperature
        self.step_limit = step_limit
        self.command_timeout_sec = command_timeout_sec
        self.model_timeout_sec = model_timeout_sec
        self.model_loop_timeout_sec = model_loop_timeout_sec
        self.cost_limit = cost_limit
        self.enable_lint = enable_lint
        self.enable_submit_readiness = enable_submit_readiness
        self.enable_all_features = enable_all_features
        self._ledger = EvidenceLedger(max_holds=max_submit_holds)
        self._sensor = WorkspaceSensor()
        self._features = CentralFeatureRuntime(
            enabled=enable_all_features,
            model_visible=self.runtime_mode == "treatment",
        )
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
        source_revision: str,
        action_id: int,
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
                    revision=source_revision,
                    grounded=True,
                )
                self._features.record_syntax(
                    action_id=action_id,
                    revision=revision,
                    source_revision=source_revision,
                    failed=True,
                    reason="changed_file_syntax_failure",
                    path=path,
                    command=command,
                    returncode=result.return_code,
                    diagnostic=raw,
                )
                return detail
            self._ledger.record_check(
                f"syntax:{path}", returncode=0, revision=source_revision, grounded=True
            )
            self._features.record_syntax(
                action_id=action_id,
                revision=revision,
                source_revision=source_revision,
                failed=False,
                reason="changed_file_syntax_pass",
                path=path,
                command=command,
                returncode=0,
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
            raw_choice = (response.get("choices") or [{}])[0].get("message") or {}
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
        task_deliverables = task_deliverable_paths(instruction)
        snapshot = await self._sensor.scan(environment, cwd=self.cwd)
        source_revision = source_revision_of(snapshot, task_deliverables)
        self._features.begin_task(
            instruction,
            revision=snapshot.revision,
            source_revision=source_revision,
            explicit_checks=explicit_checks,
            task_deliverables=task_deliverables,
        )
        calls = 0
        actions_count = 0
        input_tokens = output_tokens = cache_tokens = 0
        cost = 0.0
        terminal = ""
        started = time.monotonic()
        receipts: list[dict[str, Any]] = []
        guidance_deliveries: list[dict[str, Any]] = []
        model_call_contexts: list[dict[str, Any]] = []
        pending_guidance = ""
        pending_prepared_after_call = 0
        no_action_assistant_steps = 0
        context_chars_sent = 0
        model_output_chars = 0
        censored_reason = ""

        try:
            while not terminal:
                elapsed = time.monotonic() - started
                if calls >= self.step_limit:
                    terminal = "StepLimitExceeded"
                    censored_reason = "assistant_step_limit"
                    break
                if cost >= self.cost_limit:
                    terminal = "CostLimitExceeded"
                    censored_reason = "cost_limit"
                    break
                if elapsed >= self.model_loop_timeout_sec:
                    terminal = "WallTimeExceeded"
                    censored_reason = "model_loop_wall_time"
                    break
                calls += 1
                query_messages = messages
                runtime_enrichment_chars = 0
                runtime_message_index: int | None = None
                delivery_metadata: dict[str, Any] | None = None
                if pending_guidance:
                    (
                        query_messages,
                        runtime_message_index,
                        runtime_enrichment_chars,
                    ) = _inject_runtime_evidence(messages, pending_guidance)
                    delivery_metadata = self._features.confirm_prepared_guidance() or {}
                    pending_guidance = ""
                request_payload_sha256 = hashlib.sha256(
                    json.dumps(
                        query_messages,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                        default=str,
                    ).encode("utf-8")
                ).hexdigest()
                if delivery_metadata is not None:
                    evidence_action = int(delivery_metadata.get("evidence_action") or 0)
                    guidance_deliveries.append(
                        {
                            "delivery_id": delivery_metadata.get("delivery_id"),
                            "effect_ids": delivery_metadata.get("effect_ids", []),
                            "feature_id": delivery_metadata.get("feature_id"),
                            "contributing_features": delivery_metadata.get(
                                "contributing_features", []
                            ),
                            "evidence_action": evidence_action,
                            "evidence_actions": delivery_metadata.get("evidence_actions", []),
                            "revision": delivery_metadata.get("revision"),
                            "prepared_after_call": pending_prepared_after_call,
                            "first_eligible_call": pending_prepared_after_call + 1,
                            "delivered_before_call": calls,
                            "decision_window": "first_next_model_call",
                            "not_predictive": evidence_action <= actions_count,
                            "one_step_late": calls != pending_prepared_after_call + 1,
                            "delivered_before_model_query": True,
                            "request_payload_sha256": request_payload_sha256,
                            "message_index": runtime_message_index,
                            "chars": runtime_enrichment_chars,
                        }
                    )
                context_parts = {
                    "system_user_chars": 0,
                    "assistant_chars": 0,
                    "tool_observation_chars": 0,
                    "runtime_advisory_chars": runtime_enrichment_chars,
                }
                for item_index, item in enumerate(query_messages):
                    chars = len(str(item.get("content") or ""))
                    role = str(item.get("role") or "")
                    if role == "assistant":
                        context_parts["assistant_chars"] += _message_context_chars(item)
                    elif role == "tool":
                        if item_index == runtime_message_index:
                            chars = max(0, chars - runtime_enrichment_chars)
                        context_parts["tool_observation_chars"] += chars
                    elif role in {"system", "user"} and item_index != runtime_message_index:
                        context_parts["system_user_chars"] += chars
                context_chars = sum(context_parts.values())
                context_chars_sent += context_chars
                model_call_contexts.append(
                    {
                        "call": calls,
                        **context_parts,
                        "stock_context_chars": context_chars - runtime_enrichment_chars,
                        "context_chars": context_chars,
                        "request_payload_sha256": request_payload_sha256,
                        "runtime_message_index": runtime_message_index,
                        "query_started_at": None,
                        "next_action_relation": "",
                    }
                )
                try:
                    query_started_at = time.monotonic()
                    model_call_contexts[-1]["query_started_at"] = query_started_at
                    if delivery_metadata is not None:
                        guidance_deliveries[-1]["query_started_at"] = query_started_at
                    message = await asyncio.wait_for(
                        asyncio.to_thread(model.query, query_messages),
                        timeout=self.model_timeout_sec,
                    )
                except TimeoutError:
                    terminal = "ModelTimeout"
                    censored_reason = "model_request_timeout"
                    break
                except InterruptAgentFlow as flow:
                    messages.extend(flow.messages)
                    continue
                messages.append(message)
                model_output_chars += _message_context_chars(message)
                extra = message.get("extra") or {}
                cost += float(extra.get("cost") or 0.0)
                usage = (extra.get("response") or {}).get("usage") or {}
                input_tokens += int(usage.get("prompt_tokens") or 0)
                output_tokens += int(usage.get("completion_tokens") or 0)
                cache_tokens += int(
                    usage.get("prompt_cache_hit_tokens")
                    or (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
                    or 0
                )
                actions = tuple(extra.get("actions") or ())
                if not actions:
                    model_call_contexts[-1]["next_action_relation"] = "no_action"
                elif is_submit_command(str(actions[0].get("command") or "")):
                    model_call_contexts[-1]["next_action_relation"] = "submit"
                elif is_check_command(str(actions[0].get("command") or "")):
                    model_call_contexts[-1]["next_action_relation"] = "validation"
                else:
                    model_call_contexts[-1]["next_action_relation"] = "other"
                if not actions:
                    no_action_assistant_steps += 1
                outputs: list[dict[str, Any]] = []

                for index, action in enumerate(actions):
                    actions_count += 1
                    command = str(action.get("command") or "")
                    submit = is_submit_command(command)
                    if submit and self.enable_submit_readiness:
                        decision = self._ledger.submit_decision(
                            source_revision, sensor_healthy=snapshot.healthy
                        )
                        readiness_evidence = self._ledger.readiness_evidence(source_revision)
                        readiness_kwargs = {
                            "check_count": len(readiness_evidence),
                            "passing_checks": sum(
                                item.returncode == 0 for item in readiness_evidence
                            ),
                            "failing_checks": sum(
                                item.returncode != 0 for item in readiness_evidence
                            ),
                        }
                        self._features.record_submit(
                            action_id=actions_count,
                            revision=source_revision,
                            source_revision=source_revision,
                            refused=False,
                            sensor_healthy=snapshot.healthy,
                            **readiness_kwargs,
                        )
                        receipts.append(
                            {
                                "action": actions_count,
                                "kind": "submit_readiness",
                                "decision": (
                                    "RISK"
                                    if decision.decision == InterventionDecision.HOLD_ONCE
                                    else "PASS"
                                ),
                                "revision": source_revision,
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
                    after = await self._sensor.scan(environment, cwd=self.cwd, previous=snapshot)
                    transition = diff_snapshots(
                        snapshot,
                        after,
                        action_id=actions_count,
                        command=command,
                    )
                    snapshot = after
                    source_revision = source_revision_of(after, task_deliverables)
                    classification = classify_validation_command(
                        command, explicit_checks
                    ).with_result(
                        result_code=result.return_code,
                        output=output["output"],
                        source_revision=source_revision,
                        workspace_revision=snapshot.revision,
                    )
                    self._features.observe_action(
                        action_id=actions_count,
                        command=command,
                        output=output["output"],
                        returncode=result.return_code,
                        transition=transition,
                        revision=snapshot.revision,
                        source_revision=source_revision,
                        snapshot=snapshot,
                        validation=classification,
                    )

                    if classification.is_validation:
                        self._ledger.record_check(
                            command,
                            returncode=result.return_code,
                            revision=source_revision,
                            grounded=classification.grounded,
                            classification=classification,
                        )

                    lint_feedback = ""
                    changed_files = tuple(
                        path
                        for path in transition.changed_paths
                        if path in snapshot.entries and snapshot.entries[path].kind == "f"
                    )
                    if self.enable_lint and changed_files and snapshot.healthy:
                        lint_feedback = await self._run_lint(
                            environment,
                            changed_files,
                            snapshot.revision,
                            source_revision,
                            actions_count,
                        )
                        receipts.append(
                            {
                                "action": actions_count,
                                "kind": "changed_file_lint",
                                "decision": (
                                    "ADVISE"
                                    if lint_feedback and self.runtime_mode == "treatment"
                                    else "SHADOW"
                                    if lint_feedback
                                    else "PASS"
                                ),
                                "revision": snapshot.revision,
                                "paths": list(changed_files),
                            }
                        )
                    outputs.append(output)
                    # A submit can emit GT_CERT_DELIVERY before its shell
                    # command executes.  Consume every action's effects
                    # before the terminal submit exit, otherwise the final
                    # boundary would leave registered effects un-applied.
                    effects = self._features.consume_effects(
                        action_id=actions_count, call=calls
                    )
                    if effects and not submit:
                        later_actions = actions[index + 1 :]
                        first_submit = next(
                            (
                                offset
                                for offset, later in enumerate(later_actions)
                                if is_submit_command(str(later.get("command") or ""))
                            ),
                            None,
                        )
                        executed_after = (
                            len(later_actions)
                            if first_submit is None
                            else first_submit + 1
                        )
                        self._features.record_predecided_continuation(
                            evidence_action=actions_count,
                            executed=executed_after,
                        )
                    if submit:
                        terminal = "Submitted"
                        break

                if not terminal:
                    feature_feedback = self._features.model_feedback(deferred=True)
                    if feature_feedback and self.runtime_mode == "treatment":
                        pending_guidance = feature_feedback
                        pending_prepared_after_call = calls
                messages.extend(model.format_observation_messages(message, outputs, variables))

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
            # Very fast provider-free tests can complete inside one Windows
            # monotonic clock tick.  Preserve the truthful lower bound that
            # work occurred instead of serializing an impossible zero duration.
            elapsed_seconds = max(time.monotonic() - started, 1e-6)
            assistant_steps = sum(1 for message in messages if message.get("role") == "assistant")
            feature_summary = self._features.summary()
            action_metrics = feature_summary["action_metrics"]
            total_tokens = input_tokens + output_tokens
            uncached_input_tokens = max(0, input_tokens - cache_tokens)
            normalized_cost = normalized_token_cost(
                uncached_input_tokens, cache_tokens, output_tokens
            )
            timely_deliveries = sum(
                bool(row.get("delivered_before_model_query"))
                and not bool(row.get("one_step_late"))
                and bool(row.get("not_predictive"))
                for row in guidance_deliveries
            )
            deep_metrics = {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_tokens": cache_tokens,
                "uncached_input_tokens": uncached_input_tokens,
                "total_tokens": total_tokens,
                "prompt_cache_hit_rate": (
                    round(cache_tokens / input_tokens, 6) if input_tokens else 0.0
                ),
                "provider_cost_usd": cost,
                "normalized_cost_usd": normalized_cost,
                "normalized_pricing": "deepseek-v4-flash-frozen-2026",
                "api_calls": calls,
                "actions": actions_count,
                "assistant_steps": assistant_steps,
                "trajectory_messages": len(messages),
                "tokens_per_call": round(total_tokens / calls, 6) if calls else 0.0,
                "tokens_per_assistant_step": (
                    round(total_tokens / assistant_steps, 6) if assistant_steps else 0.0
                ),
                "actions_per_assistant_step": (
                    round(actions_count / assistant_steps, 6) if assistant_steps else 0.0
                ),
                "elapsed_seconds": elapsed_seconds,
                "context_chars_sent": context_chars_sent,
                "model_output_chars": model_output_chars,
                "no_action_assistant_steps": no_action_assistant_steps,
                "censored": bool(censored_reason),
                "censored_reason": censored_reason,
                "guidance_events": feature_summary["guidance_events"],
                "guidance_chars": feature_summary["guidance_chars"],
                "guidance_candidates": feature_summary["guidance_candidates"],
                "guidance_suppressed": feature_summary["guidance_suppressed"],
                "gt_context_chars_added": sum(
                    int(row.get("runtime_advisory_chars") or 0)
                    for row in model_call_contexts
                ),
                "stock_context_chars_sent": sum(
                    int(row.get("stock_context_chars") or 0)
                    for row in model_call_contexts
                ),
                "effects_produced": len(feature_summary["effects"]),
                "effects_applied": len(feature_summary["effect_applications"]),
                "state_mutations": sum(
                    bool(row.get("state_fields_changed"))
                    for row in feature_summary["effect_applications"]
                ),
                "effect_trace_rows": len(feature_summary["effect_trace"]),
                "effect_dispositions": {
                    disposition: sum(
                        row.get("disposition") == disposition
                        for row in feature_summary["effect_trace"]
                    )
                    for disposition in sorted(
                        {
                            row.get("disposition")
                            for row in feature_summary["effect_trace"]
                        }
                    )
                },
                "provider_payload_effects": sum(
                    row.get("disposition") == "provider_payload"
                    for row in feature_summary["effect_trace"]
                ),
                "existing_engine_actuation_effects": sum(
                    row.get("disposition") == "existing_engine_actuation"
                    for row in feature_summary["effect_trace"]
                ),
                "engine_internal_state_effects": sum(
                    row.get("disposition") == "engine_internal_state"
                    for row in feature_summary["effect_trace"]
                ),
                "audit_only_effects": sum(
                    row.get("disposition") == "audit_only"
                    for row in feature_summary["effect_trace"]
                ),
                "payload_deliveries": len(guidance_deliveries),
                "timely_payload_deliveries": timely_deliveries,
                "late_payload_deliveries": sum(
                    bool(row.get("one_step_late")) for row in guidance_deliveries
                ),
                "predictive_payload_deliveries": sum(
                    not bool(row.get("not_predictive")) for row in guidance_deliveries
                ),
                "first_eligible_delivery_rate": (
                    round(timely_deliveries / len(guidance_deliveries), 6)
                    if guidance_deliveries
                    else 1.0
                ),
                "predecided_actions_after_evidence": sum(
                    int(row.get("predecided_actions_executed_after_evidence") or 0)
                    for row in feature_summary["effects"]
                ),
                **action_metrics,
            }
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
                        "schema": "central-runtime-receipt-v3",
                        "mode": self.runtime_mode,
                        "calls": calls,
                        "actions": actions_count,
                        "elapsed_seconds": elapsed_seconds,
                        "workspace_sensor_healthy": snapshot.healthy,
                        "workspace_sensor_reason": snapshot.reason,
                        "source_revision": source_revision,
                        "metrics": deep_metrics,
                        "features": feature_summary,
                        "interventions": receipts,
                        "guidance_deliveries": guidance_deliveries,
                        "model_call_contexts": model_call_contexts,
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
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_tokens": cache_tokens,
                "total_tokens": total_tokens,
                "assistant_steps": assistant_steps,
                "trajectory_messages": len(messages),
                "guidance_events": feature_summary["guidance_events"],
                "guidance_candidates": feature_summary["guidance_candidates"],
                "guidance_suppressed": feature_summary["guidance_suppressed"],
                "exit_status": terminal,
                "censored": bool(censored_reason),
                "censored_reason": censored_reason,
                "workspace_sensor_healthy": snapshot.healthy,
            }


class MiniSweCentralShadowAgent(MiniSweCentralAgent):
    """GT-on core arm: private state active, every candidate stays shadowed."""

    runtime_mode = "shadow"

    @staticmethod
    def name() -> str:
        return "miniswe-central-shadow"
