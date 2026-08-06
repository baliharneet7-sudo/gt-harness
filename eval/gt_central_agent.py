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
from dataclasses import replace
from datetime import UTC, datetime
from enum import StrEnum
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
    ChangeOrigin,
    EvidenceLedger,
    InterventionDecision,
    WorkspaceSensor,
    classify_change,
    classify_validation_command,
    diff_snapshots,
    explicit_check_commands,
    is_check_command,
    is_submit_command,
    lint_commands,
    source_revision_of,
    task_deliverable_paths,
)
from gt_engine.checkpoint_ledger import ShadowCheckpointLedger
from gt_engine.deep_metrics import normalized_token_cost
from gt_engine.preflight import (
    PREFLIGHT_FEATURE_PLACEMENT,
    ActionDisposition,
    ActionOperation,
    PreflightMode,
    adapt_proposed_action,
    pass_decision,
)
from gt_engine.provider_view import build_provider_view
from gt_engine.repository_intelligence import RepositoryEvidence, RepositorySession


def _message_context_chars(message: dict[str, Any]) -> int:
    """Count assistant fields that are retained in the next provider request."""
    text = str(message.get("content") or "") + str(message.get("reasoning_content") or "")
    for key in ("tool_calls", "function_call"):
        value = message.get(key)
        if value:
            text += json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return len(text)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * percentile + 0.5)))
    return round(ordered[index], 6)


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _provider_request_receipt(
    model: Any, messages: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], str, str, int]:
    """Hash the exact messages produced by Mini-SWE's provider adapter.

    A neutral observer may already wrap the preparation method.  In that case
    use its original pure preparation function so measurement cannot create a
    duplicate observer event.  Scripted test models use the same minimum
    contract as Mini-SWE: private ``extra`` metadata is not provider-visible.
    """

    observer = getattr(model, "_research_receipt_observer", None)
    prepare = getattr(observer, "_original_prepare", None)
    if not callable(prepare):
        prepare = getattr(model, "_prepare_messages_for_api", None)
    if callable(prepare):
        prepared = prepare(messages)
    else:
        prepared = [
            {key: value for key, value in item.items() if key != "extra"}
            for item in messages
        ]
    envelope = {
        "model": str(
            getattr(getattr(model, "config", None), "model_name", "")
            or getattr(model, "model_name", "")
        ),
        "model_kwargs": getattr(model, "model_kwargs", {}) or {},
        "tools": getattr(model, "tools", None),
        "messages": prepared,
    }
    messages_bytes = _canonical_json(prepared)
    return (
        prepared,
        hashlib.sha256(_canonical_json(envelope)).hexdigest(),
        hashlib.sha256(messages_bytes).hexdigest(),
        len(messages_bytes.decode("utf-8")),
    )


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


class GTIntegrationMode(StrEnum):
    """One-switch policy for provider-visible GT integration."""

    OFF = "off"
    AUDIT = "audit"
    ACTIVE = "active"

    @classmethod
    def parse(cls, value: str | GTIntegrationMode) -> GTIntegrationMode:
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError as exc:
            choices = ", ".join(item.value for item in cls)
            raise ValueError(
                f"unknown GT integration mode {value!r}; expected {choices}"
            ) from exc


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
        model_timeout_sec: int | None = None,
        model_loop_timeout_sec: int | None = None,
        cost_limit: float = 3.0,
        max_submit_holds: int = 1,
        enable_lint: bool = True,
        enable_submit_readiness: bool = True,
        enable_all_features: bool = True,
        enable_repository_intelligence: bool = True,
        enable_task_start_advisory: bool = False,
        enable_context_compaction: bool = False,
        context_trigger_chars: int = 120_000,
        context_target_chars: int = 60_000,
        integration_mode: str | GTIntegrationMode | None = None,
        preflight_mode: str | PreflightMode = PreflightMode.OFF,
        enable_preflight: bool | None = None,
        preflight_timeout_sec: float = 0.1,
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
        inferred_integration_mode = (
            GTIntegrationMode.AUDIT if self.runtime_mode == "shadow" else GTIntegrationMode.ACTIVE
        )
        self.integration_mode = GTIntegrationMode.parse(
            integration_mode if integration_mode is not None else inferred_integration_mode
        )
        if self.integration_mode is GTIntegrationMode.OFF:
            enable_lint = False
            enable_submit_readiness = False
            enable_all_features = False
            enable_repository_intelligence = False
            enable_task_start_advisory = False
            enable_context_compaction = False
        elif self.integration_mode is GTIntegrationMode.AUDIT:
            enable_task_start_advisory = False
            enable_context_compaction = False
        self.enable_lint = enable_lint
        self.enable_submit_readiness = enable_submit_readiness
        self.enable_all_features = enable_all_features
        self.enable_repository_intelligence = enable_repository_intelligence
        self.enable_task_start_advisory = enable_task_start_advisory
        self.enable_context_compaction = enable_context_compaction
        self.context_trigger_chars = max(1_000, int(context_trigger_chars))
        self.context_target_chars = max(800, int(context_target_chars))
        parsed_preflight_mode = PreflightMode.parse(preflight_mode)
        if enable_preflight is not None:
            legacy_mode = PreflightMode.ASSISTIVE_SAFE if enable_preflight else PreflightMode.OFF
            if parsed_preflight_mode not in {PreflightMode.OFF, legacy_mode}:
                raise ValueError("enable_preflight conflicts with explicit preflight_mode")
            parsed_preflight_mode = legacy_mode
        if self.integration_mode is GTIntegrationMode.OFF:
            parsed_preflight_mode = PreflightMode.OFF
        elif (
            self.integration_mode is GTIntegrationMode.AUDIT
            and parsed_preflight_mode is PreflightMode.ASSISTIVE_SAFE
        ):
            parsed_preflight_mode = PreflightMode.SHADOW
        self.preflight_mode = parsed_preflight_mode
        # Compatibility for external receipt consumers; dispatch uses the enum.
        self.enable_preflight = parsed_preflight_mode is not PreflightMode.OFF
        self.preflight_timeout_sec = max(0.001, float(preflight_timeout_sec))
        self._ledger = EvidenceLedger(max_holds=max_submit_holds)
        self._checkpoints = ShadowCheckpointLedger()
        self._sensor = WorkspaceSensor()
        self._features = CentralFeatureRuntime(
            enabled=enable_all_features,
            model_visible=(
                self.runtime_mode == "treatment"
                and self.integration_mode is GTIntegrationMode.ACTIVE
            ),
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
        # Benchmark runs never retry provider errors: a bad request fails fast
        # instead of burning wall time in litellm backoff.
        kwargs: dict[str, Any] = {"temperature": self.temperature, "num_retries": 0}
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

    async def _start_repository_session(
        self,
        environment: BaseEnvironment,
        instruction: str,
        *,
        source_revision: str,
    ) -> tuple[RepositoryEvidence, RepositorySession | None]:
        """Mirror, index, and rank the repository on the host before call one."""
        if not self.enable_repository_intelligence or not hasattr(
            environment, "download_dir_with_exclusions"
        ):
            return RepositoryEvidence(status="environment_transfer_unavailable"), None
        session = RepositorySession.temporary(instruction=instruction)
        try:
            await asyncio.wait_for(
                environment.download_dir_with_exclusions(
                    source_dir=self.cwd,
                    target_dir=str(session.root),
                    exclude=[
                        ".git",
                        ".gt",
                        "node_modules",
                        "__pycache__",
                        ".pytest_cache",
                        "target",
                        "dist",
                        "build",
                    ],
                ),
                timeout=20,
            )
            evidence = await asyncio.wait_for(
                asyncio.to_thread(session.refresh, source_revision=source_revision),
                timeout=15,
            )
            return evidence, session
        except Exception as exc:
            session.close()
            return RepositoryEvidence(status=f"error:{type(exc).__name__}"), None

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
        repository_evidence, repository_session = await self._start_repository_session(
            environment,
            instruction,
            source_revision=source_revision,
        )
        if repository_evidence.available:
            self._features.register_structural_evidence(
                source_revision=source_revision,
                anchors=repository_evidence.anchors,
                callers=repository_evidence.callers,
                graph_revision=repository_evidence.graph_revision,
            )
            self._features.consume_effects(action_id=0, call=0)
        if not self.enable_task_start_advisory:
            self._features.suppress_task_start_delivery()
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
        context_compactions = 0
        context_chars_elided = 0
        pending_reconsideration_cycle = ""

        if (
            repository_evidence.available
            and self.runtime_mode == "treatment"
            and self.enable_task_start_advisory
        ):
            pending_guidance = self._features.model_feedback(deferred=True, for_call=1)

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
                if (
                    self.model_loop_timeout_sec is not None
                    and elapsed >= self.model_loop_timeout_sec
                ):
                    terminal = "WallTimeExceeded"
                    censored_reason = "model_loop_wall_time"
                    break
                calls += 1
                active_state = {
                    **self._features.progress_ledger(),
                    "obligations": list(explicit_checks) or sorted(task_deliverables),
                    "project_checks": list(repository_evidence.project_checks),
                    "source_revision": source_revision,
                    "workspace_revision": snapshot.revision,
                }
                if self.enable_context_compaction:
                    query_messages, provider_view_metrics = build_provider_view(
                        messages,
                        active_state=active_state,
                        trigger_chars=self.context_trigger_chars,
                        target_chars=self.context_target_chars,
                        keep_recent_turns=2,
                        transform=True,
                    )
                else:
                    query_messages, provider_view_metrics = build_provider_view(
                        messages,
                        active_state=active_state,
                        trigger_chars=10**18,
                        target_chars=10**18,
                        keep_recent_turns=2,
                        transform=False,
                    )
                if provider_view_metrics.compacted:
                    context_compactions += 1
                    context_chars_elided += provider_view_metrics.elided_chars
                runtime_enrichment_chars = 0
                runtime_message_index: int | None = None
                delivery_metadata: dict[str, Any] | None = None
                if pending_guidance:
                    (
                        query_messages,
                        runtime_message_index,
                        runtime_enrichment_chars,
                    ) = _inject_runtime_evidence(query_messages, pending_guidance)
                    delivery_metadata = self._features.confirm_prepared_guidance() or {}
                    pending_guidance = ""
                logical_messages_sha256 = hashlib.sha256(
                    _canonical_json(query_messages)
                ).hexdigest()
                (
                    provider_messages,
                    request_payload_sha256,
                    provider_messages_sha256,
                    provider_request_chars,
                ) = _provider_request_receipt(model, query_messages)
                self._features.record_context_compiler_call(
                    call=calls,
                    request_payload_sha256=request_payload_sha256,
                    fact_accounting=provider_view_metrics.fact_accounting,
                )
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
                            "claim_ids": delivery_metadata.get("claim_ids", []),
                            "claim_anchors": delivery_metadata.get("claim_anchors", []),
                            "decision_need_id": delivery_metadata.get("decision_need_id"),
                            "decision_need_kind": delivery_metadata.get("decision_need_kind"),
                            "decision_frame_id": delivery_metadata.get("decision_frame_id"),
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
                        "logical_messages_sha256": logical_messages_sha256,
                        "provider_messages_sha256": provider_messages_sha256,
                        "provider_request_chars": provider_request_chars,
                        "provider_message_count": len(provider_messages),
                        "runtime_message_index": runtime_message_index,
                        "provider_view_compacted": provider_view_metrics.compacted,
                        "provider_view_input_chars": provider_view_metrics.input_chars,
                        "provider_view_output_chars": provider_view_metrics.output_chars,
                        "provider_view_elided_chars": provider_view_metrics.elided_chars,
                        "context_compiler": provider_view_metrics.as_dict(),
                        "context_compiler_ran": provider_view_metrics.compiler_ran,
                        "context_fact_candidates": provider_view_metrics.candidate_fact_count,
                        "context_facts_selected": provider_view_metrics.selected_fact_count,
                        "context_facts_represented": (
                            provider_view_metrics.represented_fact_count
                        ),
                        "context_facts_controller_only": (
                            provider_view_metrics.controller_only_fact_count
                        ),
                        "context_facts_omitted": provider_view_metrics.omitted_fact_count,
                        "context_facts_accounted": provider_view_metrics.accounted_fact_count,
                        "context_stale_facts": provider_view_metrics.stale_fact_count,
                        "context_duplicate_facts": provider_view_metrics.duplicate_fact_count,
                        "context_exact_duplicate_chars_removed": (
                            provider_view_metrics.exact_duplicate_chars_removed
                        ),
                        "context_unique_reasoning_chars_removed": (
                            provider_view_metrics.unique_assistant_reasoning_chars_removed
                        ),
                        "query_started_at": None,
                        "next_action_relation": "",
                        "context_selected_facts_action_measurable": 0,
                        "context_selected_facts_action_aligned": 0,
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
                action_classifications = tuple(
                    classify_validation_command(str(action.get("command") or ""), explicit_checks)
                    for action in actions
                )
                proposed_actions = tuple(
                    adapt_proposed_action(
                        action,
                        source_revision=source_revision,
                        workspace_revision=snapshot.revision,
                        model_call=calls,
                        batch_index=index,
                        batch_size=len(actions),
                        validation=action_classifications[index],
                    )
                    for index, action in enumerate(actions)
                )
                next_commands = tuple(
                    str(action.get("command") or action.get("cmd") or "")
                    for action in actions
                )
                compiler_fact_rows = model_call_contexts[-1]["context_compiler"].get(
                    "fact_accounting", []
                )
                for fact_row in compiler_fact_rows:
                    if fact_row.get("disposition") != "selected_state_frame":
                        continue
                    anchors = tuple(
                        str(anchor)
                        for anchor in fact_row.get("action_anchors") or ()
                        if anchor
                    )
                    measurable = bool(anchors and next_commands)
                    aligned = measurable and any(
                        anchor in command
                        for anchor in anchors
                        for command in next_commands
                    )
                    fact_row["next_action_measurable"] = measurable
                    fact_row["next_action_anchor_aligned"] = aligned
                    model_call_contexts[-1][
                        "context_selected_facts_action_measurable"
                    ] += int(measurable)
                    model_call_contexts[-1][
                        "context_selected_facts_action_aligned"
                    ] += int(aligned)
                if pending_reconsideration_cycle:
                    self._features.record_reconsideration(
                        cycle_id=pending_reconsideration_cycle,
                        next_command=str((actions[0] if actions else {}).get("command") or ""),
                        next_model_call=calls,
                    )
                    pending_reconsideration_cycle = ""
                if not actions:
                    model_call_contexts[-1]["next_action_relation"] = "no_action"
                elif proposed_actions[0].operation == ActionOperation.SUBMIT:
                    model_call_contexts[-1]["next_action_relation"] = "submit"
                elif proposed_actions[0].operation == ActionOperation.VALIDATE:
                    model_call_contexts[-1]["next_action_relation"] = "validation"
                else:
                    model_call_contexts[-1]["next_action_relation"] = "other"
                if delivery_metadata is not None:
                    first_command = str((actions[0] if actions else {}).get("command") or "")
                    anchors = tuple(delivery_metadata.get("claim_anchors") or ())
                    anchor_followed = bool(first_command) and any(
                        str(anchor).split(":", 1)[0] in first_command
                        or str(anchor).rsplit(":", 1)[-1] in first_command
                        for anchor in anchors
                        if anchor
                    )
                    if not first_command:
                        behavioral_relation = "no_action"
                    elif anchor_followed:
                        behavioral_relation = "anchor_followed"
                    elif is_check_command(first_command):
                        behavioral_relation = "validation_action"
                    elif is_submit_command(first_command):
                        behavioral_relation = "submit_action"
                    else:
                        behavioral_relation = "other_action"
                    guidance_deliveries[-1].update(
                        {
                            "next_command": first_command,
                            "behavioral_relation": behavioral_relation,
                            "anchor_followed": anchor_followed,
                        }
                    )
                if not actions:
                    no_action_assistant_steps += 1
                outputs: list[dict[str, Any]] = []

                for index, (_action, proposed, classification) in enumerate(
                    zip(actions, proposed_actions, action_classifications, strict=True)
                ):
                    actions_count += 1
                    command = proposed.raw_command
                    preflight = pass_decision(proposed, "preflight_disabled")
                    applied_disposition = ActionDisposition.PASS
                    applied_reasons: tuple[str, ...] = ("preflight_disabled",)
                    if self.preflight_mode is not PreflightMode.OFF:
                        preflight_started = time.perf_counter()
                        try:
                            preflight = await asyncio.wait_for(
                                asyncio.to_thread(
                                    self._features.preflight_action,
                                    proposed,
                                    snapshot,
                                    revision=snapshot.revision,
                                    source_revision=source_revision,
                                    ledger=self._ledger,
                                ),
                                timeout=self.preflight_timeout_sec,
                            )
                        except TimeoutError:
                            preflight = pass_decision(proposed, "preflight_timeout")
                        except Exception as exc:
                            preflight = pass_decision(
                                proposed, f"preflight_exception:{type(exc).__name__}"
                            )
                        if preflight.latency_ms <= 0:
                            preflight = replace(
                                preflight,
                                latency_ms=(time.perf_counter() - preflight_started) * 1000,
                            )
                        applied_disposition = preflight.disposition
                        applied_reasons = preflight.reason_codes
                        if self.preflight_mode is PreflightMode.SHADOW:
                            applied_disposition = ActionDisposition.PASS
                            applied_reasons = (*applied_reasons, "shadow_observe_only")
                        elif preflight.source_revision not in {"", source_revision}:
                            applied_disposition = ActionDisposition.PASS
                            applied_reasons = (
                                *applied_reasons,
                                "dispatch_revision_mismatch",
                            )
                        elif preflight.disposition == ActionDisposition.REWRITE:
                            applied_disposition = ActionDisposition.PASS
                            applied_reasons = (*applied_reasons, "rewrite_disabled")
                        elif preflight.disposition == ActionDisposition.SUPPRESS:
                            applied_disposition = ActionDisposition.PASS
                            applied_reasons = (
                                *applied_reasons,
                                "suppress_host_policy_only",
                            )
                        elif preflight.disposition in {
                            ActionDisposition.AUGMENT,
                            ActionDisposition.RETURN_TO_MODEL,
                        }:
                            admitted, admission_reason = (
                                self._features.admit_preflight_intervention(proposed, preflight)
                            )
                            if not admitted:
                                applied_disposition = ActionDisposition.PASS
                                applied_reasons = (
                                    *applied_reasons,
                                    admission_reason,
                                )
                        self._features.record_preflight_cycle(
                            proposed,
                            preflight,
                            mode=self.preflight_mode,
                            applied_disposition=applied_disposition,
                            applied_reason_codes=applied_reasons,
                            dispatch_command=command,
                            revision=snapshot.revision,
                            source_revision=source_revision,
                        )
                    if applied_disposition == ActionDisposition.RETURN_TO_MODEL:
                        pending_reconsideration_cycle = proposed.cycle_id
                        outputs.append(
                            {
                                "output": "Pre-execution check: " + " ".join(preflight.evidence),
                                "returncode": 2,
                                "exception_info": "",
                            }
                        )
                        cancelled = len(actions) - index - 1
                        for cancelled_proposal in proposed_actions[index + 1 :]:
                            self._features.record_cancelled_proposal(
                                cancelled_proposal,
                                mode=self.preflight_mode,
                                reason="preflight_return_to_model",
                            )
                        outputs.extend(
                            {
                                "output": "Cancelled: earlier action requires fresh reasoning.",
                                "returncode": 2,
                                "exception_info": "",
                            }
                            for _ in range(cancelled)
                        )
                        self._features.record_skipped_action(action_id=actions_count)
                        if cancelled:
                            self._features.record_batch_interrupt(
                                action_id=actions_count,
                                cancelled=cancelled,
                                reason="preflight_return_to_model",
                            )
                        break
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
                    if applied_disposition == ActionDisposition.AUGMENT and preflight.evidence:
                        output["output"] += "\n\nPre-execution check: " + " ".join(
                            preflight.evidence
                        )
                    after = await self._sensor.scan(environment, cwd=self.cwd, previous=snapshot)
                    transition = diff_snapshots(
                        snapshot,
                        after,
                        action_id=actions_count,
                        command=command,
                    )
                    snapshot = after
                    source_revision = source_revision_of(after, task_deliverables)
                    classified_transition = tuple(
                        classify_change(
                            path,
                            kind=(after.entries[path].kind if path in after.entries else "f"),
                            task_deliverables=task_deliverables,
                        )
                        for path in transition.changed_paths
                    )
                    material_workspace_change = any(
                        item.origin
                        in {
                            ChangeOrigin.MODEL_AUTHORED,
                            ChangeOrigin.TASK_DELIVERABLE,
                            ChangeOrigin.UNKNOWN,
                        }
                        for item in classified_transition
                    ) or (
                        proposed.mutates_workspace and bool(transition.changed_paths)
                    )
                    if (
                        repository_session is not None
                        and source_revision != proposed.source_revision
                    ):
                        source_paths = tuple(
                            item.path for item in classified_transition if item.validation_relevant
                        )
                        mirror_advanced = repository_session.apply_transition(
                            transition,
                            source_revision=source_revision,
                            changed_paths=source_paths,
                        )
                        if mirror_advanced:
                            try:
                                repository_evidence = await asyncio.wait_for(
                                    asyncio.to_thread(
                                        repository_session.refresh,
                                        source_revision=source_revision,
                                    ),
                                    timeout=5,
                                )
                            except TimeoutError:
                                repository_session.invalidate(
                                    source_revision=source_revision,
                                    status="refresh_timeout",
                                )
                                repository_evidence = repository_session.evidence
                            if repository_evidence.available:
                                self._features.refresh_structural_evidence(
                                    source_revision=source_revision,
                                    anchors=repository_evidence.anchors,
                                    callers=repository_evidence.callers,
                                    graph_revision=repository_evidence.graph_revision,
                                )
                        else:
                            repository_evidence = repository_session.evidence
                            self._features.refresh_structural_evidence(
                                source_revision=source_revision,
                                anchors=(),
                                callers=(),
                                graph_revision="",
                            )
                    classification = classification.with_result(
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
                        proposed=proposed,
                    )
                    if self.preflight_mode is not PreflightMode.OFF:
                        self._features.record_action_postflight(
                            proposed,
                            action_ordinal=actions_count,
                            command=command,
                            returncode=result.return_code,
                            workspace_revision=snapshot.revision,
                            source_revision=source_revision,
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
                    current_checks = self._ledger.readiness_evidence(source_revision)
                    self._checkpoints.observe(
                        source_revision=source_revision,
                        workspace_revision=snapshot.revision,
                        changed_paths=changed_files,
                        passing_checks=(
                            item.command for item in current_checks if item.returncode == 0
                        ),
                        failing_checks=(
                            item.command for item in current_checks if item.returncode != 0
                        ),
                        action_id=actions_count,
                    )
                    outputs.append(output)
                    # A submit can emit GT_CERT_DELIVERY before its shell
                    # command executes.  Consume every action's effects
                    # before the terminal submit exit, otherwise the final
                    # boundary would leave registered effects un-applied.
                    effects = self._features.consume_effects(action_id=actions_count, call=calls)
                    stale_batch_barrier = (
                        self.preflight_mode is PreflightMode.ASSISTIVE_SAFE
                        and index + 1 < len(actions)
                        and (
                            proposed.operation
                            in {ActionOperation.VALIDATE, ActionOperation.SUBMIT}
                            or material_workspace_change
                            or source_revision != proposed.source_revision
                        )
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
                            0
                            if stale_batch_barrier
                            else (len(later_actions) if first_submit is None else first_submit + 1)
                        )
                        self._features.record_predecided_continuation(
                            evidence_action=actions_count,
                            executed=executed_after,
                        )
                    if submit:
                        cancelled = len(actions) - index - 1
                        if cancelled:
                            if self.preflight_mode is not PreflightMode.OFF:
                                for cancelled_proposal in proposed_actions[index + 1 :]:
                                    self._features.record_cancelled_proposal(
                                        cancelled_proposal,
                                        mode=self.preflight_mode,
                                        reason="terminal_submit",
                                    )
                            outputs.extend(
                                {
                                    "output": "Cancelled: task already submitted.",
                                    "returncode": 2,
                                    "exception_info": "",
                                }
                                for _ in range(cancelled)
                            )
                            self._features.record_batch_interrupt(
                                action_id=actions_count,
                                cancelled=cancelled,
                                reason="terminal_submit",
                            )
                        terminal = "Submitted"
                        break
                    if stale_batch_barrier:
                        cancelled = len(actions) - index - 1
                        for cancelled_proposal in proposed_actions[index + 1 :]:
                            self._features.record_cancelled_proposal(
                                cancelled_proposal,
                                mode=self.preflight_mode,
                                reason="stale_batch_barrier",
                            )
                        outputs.extend(
                            {
                                "output": "Cancelled: prior action changed the decision boundary.",
                                "returncode": 2,
                                "exception_info": "",
                            }
                            for _ in range(cancelled)
                        )
                        self._features.record_batch_interrupt(
                            action_id=actions_count,
                            cancelled=cancelled,
                            reason="stale_batch_barrier",
                        )
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
            preflight_rows = feature_summary["preflight_receipts"]
            action_cycles = feature_summary["action_cycles"]
            preflight_latencies = [
                float(row["decision"].get("latency_ms") or 0.0) for row in preflight_rows
            ]
            parser_confidences = [
                float(row["proposed"].get("parser_confidence") or 0.0) for row in preflight_rows
            ]
            seen_preflight_evidence: set[tuple[str, str, tuple[str, ...]]] = set()
            duplicate_preflight_evidence = 0
            for row in preflight_rows:
                evidence_key = (
                    str(row.get("source_revision") or ""),
                    str(row["proposed"].get("operation") or ""),
                    tuple(row["decision"].get("evidence") or ()),
                )
                if not evidence_key[2]:
                    continue
                if evidence_key in seen_preflight_evidence:
                    duplicate_preflight_evidence += 1
                seen_preflight_evidence.add(evidence_key)
            action_metrics = feature_summary["action_metrics"]
            accountability_counts = feature_summary["effect_accountability_counts"]
            compiler_effect_counts = feature_summary[
                "context_compiler_effect_accountability_counts"
            ]
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
                "provider_request_chars_sent": sum(
                    int(row.get("provider_request_chars") or 0)
                    for row in model_call_contexts
                ),
                "provider_requests_hashed": sum(
                    bool(row.get("provider_messages_sha256"))
                    and bool(row.get("request_payload_sha256"))
                    for row in model_call_contexts
                ),
                "provider_request_hash_coverage": (
                    round(
                        sum(
                            bool(row.get("provider_messages_sha256"))
                            for row in model_call_contexts
                        )
                        / len(model_call_contexts),
                        6,
                    )
                    if model_call_contexts
                    else 1.0
                ),
                "context_compactions": context_compactions,
                "context_chars_elided": context_chars_elided,
                "context_compiler_calls": sum(
                    bool(row.get("context_compiler_ran")) for row in model_call_contexts
                ),
                "context_fact_candidates": sum(
                    int(row.get("context_fact_candidates") or 0)
                    for row in model_call_contexts
                ),
                "context_facts_selected": sum(
                    int(row.get("context_facts_selected") or 0)
                    for row in model_call_contexts
                ),
                "context_facts_represented": sum(
                    int(row.get("context_facts_represented") or 0)
                    for row in model_call_contexts
                ),
                "context_facts_controller_only": sum(
                    int(row.get("context_facts_controller_only") or 0)
                    for row in model_call_contexts
                ),
                "context_facts_omitted": sum(
                    int(row.get("context_facts_omitted") or 0)
                    for row in model_call_contexts
                ),
                "context_facts_accounted": sum(
                    int(row.get("context_facts_accounted") or 0)
                    for row in model_call_contexts
                ),
                "context_selected_facts_action_measurable": sum(
                    int(row.get("context_selected_facts_action_measurable") or 0)
                    for row in model_call_contexts
                ),
                "context_selected_facts_action_aligned": sum(
                    int(row.get("context_selected_facts_action_aligned") or 0)
                    for row in model_call_contexts
                ),
                "context_stale_facts": sum(
                    int(row.get("context_stale_facts") or 0)
                    for row in model_call_contexts
                ),
                "context_duplicate_facts": sum(
                    int(row.get("context_duplicate_facts") or 0)
                    for row in model_call_contexts
                ),
                "context_exact_duplicate_chars_removed": sum(
                    int(row.get("context_exact_duplicate_chars_removed") or 0)
                    for row in model_call_contexts
                ),
                "context_unique_reasoning_chars_removed": sum(
                    int(row.get("context_unique_reasoning_chars_removed") or 0)
                    for row in model_call_contexts
                ),
                "context_state_frame_calls": sum(
                    bool((row.get("context_compiler") or {}).get("active_state_chars"))
                    for row in model_call_contexts
                ),
                "context_provider_view_changed_calls": sum(
                    bool(row.get("provider_view_compacted"))
                    or bool(row.get("context_exact_duplicate_chars_removed"))
                    or bool((row.get("context_compiler") or {}).get("active_state_chars"))
                    for row in model_call_contexts
                ),
                "preflight_mode": self.preflight_mode.value,
                "preflight_calls": len(preflight_rows),
                "preflight_candidate_dispositions": {
                    disposition: sum(
                        row["decision"]["disposition"] == disposition for row in preflight_rows
                    )
                    for disposition in sorted(
                        {row["decision"]["disposition"] for row in preflight_rows}
                    )
                },
                "preflight_applied_dispositions": {
                    disposition: sum(
                        row["applied_disposition"] == disposition for row in preflight_rows
                    )
                    for disposition in sorted(
                        {row["applied_disposition"] for row in preflight_rows}
                    )
                },
                "preflight_operation_distribution": {
                    operation: sum(
                        row["proposed"]["operation"] == operation for row in preflight_rows
                    )
                    for operation in sorted(
                        {row["proposed"]["operation"] for row in preflight_rows}
                    )
                },
                "preflight_segment_operation_distribution": {
                    operation: sum(
                        nested.get("operation") == operation
                        for row in preflight_rows
                        for nested in row["proposed"].get("operations") or ()
                    )
                    for operation in sorted(
                        {
                            str(nested.get("operation") or "")
                            for row in preflight_rows
                            for nested in row["proposed"].get("operations") or ()
                        }
                    )
                },
                "preflight_known_segment_operations": sum(
                    nested.get("operation") != ActionOperation.OTHER.value
                    for row in preflight_rows
                    for nested in row["proposed"].get("operations") or ()
                ),
                "preflight_unknown_segment_operations": sum(
                    nested.get("operation") == ActionOperation.OTHER.value
                    for row in preflight_rows
                    for nested in row["proposed"].get("operations") or ()
                ),
                "preflight_typed_targets": sum(
                    len(row["proposed"].get("targets") or ()) for row in preflight_rows
                ),
                "preflight_latency_ms": {
                    "p50": _percentile(preflight_latencies, 0.50),
                    "p95": _percentile(preflight_latencies, 0.95),
                    "p99": _percentile(preflight_latencies, 0.99),
                    "max": round(max(preflight_latencies), 6) if preflight_latencies else 0.0,
                },
                "preflight_parser_confidence": {
                    "mean": round(sum(parser_confidences) / len(parser_confidences), 6)
                    if parser_confidences
                    else 0.0,
                    "min": round(min(parser_confidences), 6) if parser_confidences else 0.0,
                },
                "preflight_material_evidence": sum(
                    bool(row["decision"].get("evidence"))
                    and row["decision"]["disposition"] != "pass"
                    for row in preflight_rows
                ),
                "preflight_commands_returned_to_model": sum(
                    row["applied_disposition"] == "return_to_model" for row in preflight_rows
                ),
                "preflight_commands_changed_after_return": sum(
                    bool(row.get("reconsideration", {}).get("command_changed"))
                    for row in action_cycles
                ),
                "preflight_duplicate_evidence": duplicate_preflight_evidence,
                "preflight_false_interventions": None,
                "preflight_false_intervention_status": "requires_outcome_oracle",
                "postflight_only_feature_count": sum(
                    placement.postflight_only for placement in PREFLIGHT_FEATURE_PLACEMENT.values()
                ),
                "validation_status_distribution": {
                    status: sum(
                        row.get("status") == status
                        for row in feature_summary.get("validation_log") or ()
                    )
                    for status in ("unknown", "pending", "pass", "fail")
                },
                "validation_attributed_results": sum(
                    bool(row.get("status_attributed"))
                    for row in feature_summary.get("validation_log") or ()
                ),
                "validation_unattributed_intents": sum(
                    bool(row.get("is_validation"))
                    and not bool(row.get("status_attributed"))
                    for row in feature_summary.get("validation_log") or ()
                ),
                "stale_batched_actions_prevented": sum(
                    int(row.get("cancelled") or 0) for row in feature_summary["batch_interrupts"]
                ),
                "model_output_chars": model_output_chars,
                "no_action_assistant_steps": no_action_assistant_steps,
                "censored": bool(censored_reason),
                "censored_reason": censored_reason,
                "guidance_events": feature_summary["guidance_events"],
                "guidance_chars": feature_summary["guidance_chars"],
                "guidance_candidates": feature_summary["guidance_candidates"],
                "guidance_suppressed": feature_summary["guidance_suppressed"],
                "gt_context_chars_added": sum(
                    int(row.get("runtime_advisory_chars") or 0) for row in model_call_contexts
                ),
                "context_state_frame_chars_added": sum(
                    int((row.get("context_compiler") or {}).get("active_state_chars") or 0)
                    for row in model_call_contexts
                ),
                "total_gt_context_chars_added": sum(
                    int(row.get("runtime_advisory_chars") or 0)
                    + int((row.get("context_compiler") or {}).get("active_state_chars") or 0)
                    for row in model_call_contexts
                ),
                "stock_context_chars_sent": sum(
                    int(row.get("stock_context_chars") or 0) for row in model_call_contexts
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
                        {row.get("disposition") for row in feature_summary["effect_trace"]}
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
                "effect_accountability": accountability_counts,
                "context_compiler_effect_accountability": compiler_effect_counts,
                "context_compiler_effects_considered": sum(
                    count
                    for status, count in compiler_effect_counts.items()
                    if status != "no_eligible_model_call"
                ),
                "context_compiler_effects_no_eligible_call": compiler_effect_counts.get(
                    "no_eligible_model_call", 0
                ),
                "context_compiler_effects_unaccounted": compiler_effect_counts.get(
                    "unaccounted_bug", 0
                ),
                "inert_private_state_effects": accountability_counts.get("inert_private_state", 0),
                "pending_decision_claim_effects": accountability_counts.get(
                    "pending_decision_claim", 0
                ),
                "prepared_decision_frame_effects": accountability_counts.get(
                    "prepared_decision_frame", 0
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
                        "integration_mode": self.integration_mode.value,
                        "preflight_mode": self.preflight_mode.value,
                        "calls": calls,
                        "actions": actions_count,
                        "elapsed_seconds": elapsed_seconds,
                        "workspace_sensor_healthy": snapshot.healthy,
                        "workspace_sensor_reason": snapshot.reason,
                        "source_revision": source_revision,
                        "repository_evidence": repository_evidence.as_dict(),
                        "repository_session": (
                            repository_session.summary() if repository_session is not None else None
                        ),
                        "checkpoint_ledger": self._checkpoints.summary(),
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
                "integration_mode": self.integration_mode.value,
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
            if repository_session is not None:
                repository_session.close()


class MiniSweCentralShadowAgent(MiniSweCentralAgent):
    """GT-on core arm: private state active, every candidate stays shadowed."""

    runtime_mode = "shadow"

    @staticmethod
    def name() -> str:
        return "miniswe-central-shadow"
