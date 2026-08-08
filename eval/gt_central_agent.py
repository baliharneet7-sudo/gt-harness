"""Host-owned Mini-SWE runtime for GT-on Terminal-Bench experiments.

Unlike the legacy installed agents, this agent keeps provider access, private
state, policy, and source on the Harbor host.  The task container receives
only literal model-selected shell commands plus host-only observation probes
whose output is never added to model context.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import tarfile
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
    ValidationAuthority,
    ValidationClassification,
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
from gt_engine.completion import (
    CompletionCertificate,
    CompletionStatus,
    PredicateObservation,
    certificate_from_observations,
    compile_completion_plan,
)
from gt_engine.context_frontier import (
    FrontierDisposition,
    compile_incremental_frontier,
)
from gt_engine.deep_metrics import normalized_token_cost
from gt_engine.host_execution import HostExecCategory, HostExecutionRecorder
from gt_engine.preflight import (
    PREFLIGHT_FEATURE_PLACEMENT,
    ActionDisposition,
    ActionOperation,
    MutationCertainty,
    PreflightMode,
    ProposedAction,
    SegmentRole,
    adapt_proposed_action,
    pass_decision,
)
from gt_engine.progress import ProgressLedger
from gt_engine.provider_view import (
    DEFAULT_MIN_COMPACTION_SAVINGS_CHARS,
    DEFAULT_MIN_COMPACTION_SAVINGS_RATIO,
    DEFAULT_SOFT_COMPACTION_TARGET_CHARS,
    DEFAULT_SOFT_COMPACTION_TRIGGER_CHARS,
    ProviderViewSession,
    build_provider_view,
    provider_compaction_required,
    provider_request_budget,
)
from gt_engine.repository_intelligence import (
    RepositoryEvidence,
    RepositoryIntelligenceStatus,
    RepositorySession,
    classify_repository_applicability,
    graph_gate_failures,
)
from gt_engine.repository_mirror import SourceMirrorPlan, plan_source_mirror
from gt_engine.task_contract import task_external_paths, task_shebang_paths


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


def _partition_recovered_repository_failures(
    rows: list[dict[str, Any]],
    *,
    current_source_revision: str,
    failure_values: frozenset[str],
    prefix: str,
) -> tuple[list[str], list[str]]:
    """Separate current fail-closed errors from recovered historical errors."""

    failures = [
        row
        for row in rows
        if str(row.get("status") or row.get("disposition") or "") in failure_values
    ]
    latest_by_revision: dict[str, dict[str, Any]] = {}
    for row in rows:
        revision = str(row.get("source_revision") or "")
        latest_by_revision[revision] = row
    current: list[str] = []
    transient: list[str] = []
    for row in failures:
        revision = str(row.get("source_revision") or "")
        reason = f"{prefix}:{row.get('status') or row.get('disposition') or 'unknown'}"
        if revision == current_source_revision and latest_by_revision.get(revision) is row:
            current.append(reason)
        else:
            transient.append(reason)
    return list(dict.fromkeys(current)), list(dict.fromkeys(transient))


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
            {key: value for key, value in item.items() if key != "extra"} for item in messages
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


def _stable_provider_prefix(
    previous: list[dict[str, Any]] | None,
    current: list[dict[str, Any]],
) -> tuple[int, int, float]:
    """Measure the exact append-stable provider-message prefix.

    This is a transport-visible cacheability measurement, not a claim about
    model attention.  A changed or elided old message ends the prefix.
    """

    if not previous or not current:
        return 0, 0, 0.0
    count = 0
    chars = 0
    for prior, present in zip(previous, current, strict=False):
        if _canonical_json(prior) != _canonical_json(present):
            break
        count += 1
        chars += len(_canonical_json(present).decode("utf-8"))
    total_chars = sum(len(_canonical_json(item).decode("utf-8")) for item in current)
    return count, chars, round(chars / total_chars, 6) if total_chars else 0.0


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
            raise ValueError(f"unknown GT integration mode {value!r}; expected {choices}") from exc


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
        execution_budget_sec: float | None = None,
        deadline_reserve_sec: float = 15.0,
        cost_limit: float = 3.0,
        max_submit_holds: int = 1,
        enable_lint: bool = True,
        enable_submit_readiness: bool = True,
        enable_all_features: bool = True,
        enable_repository_intelligence: bool = True,
        require_graph_ready: bool = False,
        enable_task_start_advisory: bool = False,
        enable_context_frontier: bool = True,
        context_frontier_task_budget_chars: int = 6_000,
        enable_context_compaction: bool = False,
        enable_completion_controller: bool = True,
        completion_check_timeout_sec: float = 10.0,
        enable_adaptive_validation_timeout: bool = False,
        max_validation_timeout_sec: float = 120.0,
        validation_timeout_budget_ratio: float = 0.20,
        enable_progress_control: bool = True,
        context_capacity_chars: int = 400_000,
        context_trigger_chars: int | None = None,
        context_target_chars: int | None = None,
        context_min_compaction_savings_chars: int = (
            DEFAULT_MIN_COMPACTION_SAVINGS_CHARS
        ),
        context_min_compaction_savings_ratio: float = (
            DEFAULT_MIN_COMPACTION_SAVINGS_RATIO
        ),
        provider_context_limit_tokens: int = 1_048_576,
        provider_context_hard_ratio: float = 0.90,
        provider_context_reserve_tokens: int = 131_072,
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
        self.execution_budget_sec = (
            None if execution_budget_sec is None else max(0.001, float(execution_budget_sec))
        )
        self.deadline_reserve_sec = max(0.0, float(deadline_reserve_sec))
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
            enable_context_frontier = False
            enable_context_compaction = False
            enable_completion_controller = False
            enable_progress_control = False
            enable_adaptive_validation_timeout = False
        elif self.integration_mode is GTIntegrationMode.AUDIT:
            enable_task_start_advisory = False
            enable_context_compaction = False
            enable_completion_controller = False
            enable_adaptive_validation_timeout = False
        self.enable_lint = enable_lint
        self.enable_submit_readiness = enable_submit_readiness
        self.enable_all_features = enable_all_features
        self.enable_repository_intelligence = enable_repository_intelligence
        self.require_graph_ready = bool(require_graph_ready)
        self.enable_task_start_advisory = enable_task_start_advisory
        self.enable_context_frontier = bool(enable_context_frontier)
        self.context_frontier_task_budget_chars = max(0, int(context_frontier_task_budget_chars))
        self.enable_context_compaction = enable_context_compaction
        self.enable_completion_controller = enable_completion_controller
        self.completion_check_timeout_sec = max(0.05, float(completion_check_timeout_sec))
        self.enable_adaptive_validation_timeout = bool(enable_adaptive_validation_timeout)
        self.max_validation_timeout_sec = max(
            float(self.command_timeout_sec), float(max_validation_timeout_sec)
        )
        self.validation_timeout_budget_ratio = min(
            1.0, max(0.01, float(validation_timeout_budget_ratio))
        )
        self.enable_progress_control = enable_progress_control
        self.context_capacity_chars = max(10_000, int(context_capacity_chars))
        self.context_trigger_chars = max(
            1_000,
            int(
                context_trigger_chars
                if context_trigger_chars is not None
                else min(
                    self.context_capacity_chars * 0.70,
                    DEFAULT_SOFT_COMPACTION_TRIGGER_CHARS,
                )
            ),
        )
        self.context_target_chars = max(
            800,
            int(
                context_target_chars
                if context_target_chars is not None
                else min(
                    self.context_capacity_chars * 0.50,
                    DEFAULT_SOFT_COMPACTION_TARGET_CHARS,
                )
            ),
        )
        if self.context_target_chars >= self.context_trigger_chars:
            raise ValueError("context_target_chars must be smaller than context_trigger_chars")
        self.context_min_compaction_savings_chars = max(
            0, int(context_min_compaction_savings_chars)
        )
        self.context_min_compaction_savings_ratio = min(
            1.0, max(0.0, float(context_min_compaction_savings_ratio))
        )
        self.provider_context_limit_tokens = max(1, int(provider_context_limit_tokens))
        self.provider_context_hard_ratio = min(0.99, max(0.50, float(provider_context_hard_ratio)))
        self.provider_context_reserve_tokens = max(1, int(provider_context_reserve_tokens))
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
        self._progress = ProgressLedger(stall_threshold=3, cycle_threshold=6)
        self._sensor = WorkspaceSensor()
        self._features = CentralFeatureRuntime(
            enabled=enable_all_features,
            model_visible=(
                self.runtime_mode == "treatment"
                and self.integration_mode is GTIntegrationMode.ACTIVE
            ),
        )
        self._model_factory: Callable[[], Any] = self._build_model
        self._repository_work_receipts: list[dict[str, Any]] = []
        self._completion_cache: dict[tuple[str, str], PredicateObservation] = {}
        self._completion_cache_hits = 0
        self._completion_probe_execs = 0
        self._host_executions = HostExecutionRecorder()

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
            result = await self._host_executions.exec(
                environment,
                "uname -s; uname -r; uname -v; uname -m",
                category=HostExecCategory.SYSTEM_INFORMATION,
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
        snapshot: Any,
        source_revision: str,
        task_deliverables: set[str] | frozenset[str] = frozenset(),
    ) -> tuple[RepositoryEvidence, RepositorySession | None]:
        """Mirror, index, and rank the repository on the host before call one."""
        started = time.perf_counter()
        if not self.enable_repository_intelligence:
            self._repository_work_receipts.append(
                {
                    "kind": "mirror_transfer",
                    "status": (
                        "disabled"
                        if not self.enable_repository_intelligence
                        else "environment_transfer_unavailable"
                    ),
                    "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                    "files": 0,
                    "bytes": 0,
                }
            )
            return RepositoryEvidence(status="environment_transfer_unavailable"), None
        session = RepositorySession.temporary(instruction=instruction)
        stage = "mirror_transfer"
        try:
            transfer_mode = "legacy_directory"
            mirror_plan: SourceMirrorPlan | None = None
            if callable(getattr(environment, "download_file", None)):
                transfer_mode = "source_only_archive"
                mirror_plan = plan_source_mirror(
                    snapshot,
                    excluded_paths=frozenset(task_deliverables),
                )
                self._repository_work_receipts.append(
                    {"kind": "source_mirror_plan", **mirror_plan.as_dict()}
                )
                if not mirror_plan.complete:
                    raise RuntimeError("SourceMirrorIncomplete")
                archive_members = tuple(
                    (
                        path[len("__external__/") :]
                        if path.startswith("__external__/")
                        else "app/" + path
                    )
                    for path in mirror_plan.paths
                )
                manifest_bytes = b"".join(
                    path.encode("utf-8", "surrogateescape") + b"\0"
                    for path in archive_members
                )
                remote_manifest = "/tmp/gt-source-paths.nul"
                remote_archive = "/tmp/gt-source-mirror.tar.gz"
                init = await self._host_executions.exec(
                    environment,
                    f"umask 077; : > {remote_manifest}",
                    category=HostExecCategory.REPOSITORY_TRANSFER,
                    source_revision=source_revision,
                    cwd=self.cwd,
                    env={},
                    timeout_sec=5,
                )
                if init.return_code != 0:
                    raise RuntimeError("SourceMirrorManifestInitFailed")
                # Keep each host command bounded even for a large source tree.
                raw_chunk_bytes = 24_000
                for offset in range(0, len(manifest_bytes), raw_chunk_bytes):
                    encoded = base64.b64encode(
                        manifest_bytes[offset : offset + raw_chunk_bytes]
                    ).decode("ascii")
                    appended = await self._host_executions.exec(
                        environment,
                        f"printf '%s' '{encoded}' | base64 -d >> {remote_manifest}",
                        category=HostExecCategory.REPOSITORY_TRANSFER,
                        source_revision=source_revision,
                        cwd=self.cwd,
                        env={},
                        timeout_sec=5,
                    )
                    if appended.return_code != 0:
                        raise RuntimeError("SourceMirrorManifestWriteFailed")
                archived = await self._host_executions.exec(
                    environment,
                    (
                        "tar --null --verbatim-files-from --transform='s,^app/,,' "
                        "--transform='s,^etc/,__external__/etc/,' "
                        "--transform='s,^var/,__external__/var/,' -czf "
                        f"{remote_archive} -C / -T {remote_manifest}"
                    ),
                    category=HostExecCategory.REPOSITORY_TRANSFER,
                    source_revision=source_revision,
                    cwd=self.cwd,
                    env={},
                    timeout_sec=20,
                )
                if archived.return_code != 0:
                    raise RuntimeError("SourceMirrorArchiveFailed")
                local_archive = session.state_dir / "source-mirror.tar.gz"
                await asyncio.wait_for(
                    environment.download_file(remote_archive, local_archive),
                    timeout=20,
                )
                with tarfile.open(local_archive, mode="r:gz") as archive:
                    for member in archive.getmembers():
                        target = (session.root / member.name).resolve()
                        try:
                            target.relative_to(session.root)
                        except ValueError as exc:
                            raise RuntimeError("UnsafeSourceMirrorArchive") from exc
                        if not (member.isfile() or member.isdir()):
                            raise RuntimeError("UnsafeSourceMirrorMember")
                    archive.extractall(session.root, filter="data")
            elif callable(getattr(environment, "download_dir_with_exclusions", None)):
                # Compatibility for provider-free fakes.  Paid Harbor
                # environments implement download_file and must use the
                # bounded source-only path above.
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
            else:
                raise RuntimeError("EnvironmentTransferUnavailable")
            transferred = [path for path in session.root.rglob("*") if path.is_file()]
            self._repository_work_receipts.append(
                {
                    "kind": "mirror_transfer",
                    "status": "complete",
                    "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                    "files": len(transferred),
                    "bytes": sum(path.stat().st_size for path in transferred),
                    "transfer_mode": transfer_mode,
                    "selected_manifest_sha256": (
                        mirror_plan.manifest_sha256 if mirror_plan is not None else ""
                    ),
                }
            )
            stage = "initial_index"
            index_started = time.perf_counter()
            evidence = await asyncio.wait_for(
                asyncio.to_thread(session.refresh, source_revision=source_revision),
                timeout=15,
            )
            self._repository_work_receipts.append(
                {
                    "kind": "initial_index",
                    "status": evidence.status,
                    "duration_ms": round((time.perf_counter() - index_started) * 1000, 3),
                    "source_revision": source_revision,
                    "graph_revision": evidence.graph_revision,
                    "schema_valid": bool(evidence.index and evidence.index.schema_valid),
                    "nodes": int(evidence.index.node_count if evidence.index else 0),
                    "edges": int(evidence.index.edge_count if evidence.index else 0),
                }
            )
            return evidence, session
        except Exception as exc:
            self._repository_work_receipts.append(
                {
                    "kind": stage,
                    "status": "failed",
                    "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                    "error_type": type(exc).__name__,
                }
            )
            session.close()
            return RepositoryEvidence(status=f"error:{type(exc).__name__}"), None

    @staticmethod
    def _render(template: str, variables: dict[str, Any]) -> str:
        return Template(template, undefined=StrictUndefined).render(**variables)

    def _select_action_timeout(
        self,
        proposed: ProposedAction,
        classification: ValidationClassification,
        *,
        remaining_agent_time_sec: float | None,
    ) -> tuple[float, str]:
        """Select a bounded host timeout from mechanically parsed validation intent."""

        selected = float(self.command_timeout_sec)
        reason = "default_command_timeout"
        validator_is_terminal = (
            classification.validator_segment_index is not None
            and classification.validator_segment_index == len(proposed.shell_segments) - 1
            and not (
                len(proposed.shell_connectors) > classification.validator_segment_index
                and "&" in proposed.shell_connectors[classification.validator_segment_index]
            )
        )
        requested = proposed.requested_timeout_sec
        if (
            self.enable_adaptive_validation_timeout
            and proposed.operation is ActionOperation.VALIDATE
            and proposed.parser_confidence >= 0.95
            and classification.authority
            in {ValidationAuthority.DECLARED, ValidationAuthority.STANDARD_RUNNER}
            and validator_is_terminal
            and requested is not None
            and requested > selected
        ):
            available_cap = self.max_validation_timeout_sec
            if remaining_agent_time_sec is not None:
                available_cap = min(
                    available_cap,
                    max(
                        selected,
                        remaining_agent_time_sec * self.validation_timeout_budget_ratio,
                    ),
                )
            selected = max(selected, min(float(requested), available_cap))
            reason = "literal_validation_timeout"
        if remaining_agent_time_sec is not None:
            selected = min(selected, max(0.05, remaining_agent_time_sec))
        return selected, reason

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
                result = await self._host_executions.exec(
                    environment,
                    command,
                    category=HostExecCategory.SYNTAX_PROBE,
                    action_id=action_id,
                    source_revision=source_revision,
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

    async def _evaluate_completion(
        self,
        environment: BaseEnvironment,
        plan: Any,
        *,
        workspace_revision: str,
        source_revision: str,
        snapshot: Any | None = None,
        action_id: int,
        timeout_sec: float,
    ) -> CompletionCertificate:
        """Run only task-text-equivalent predicates as private host probes."""

        observations: list[PredicateObservation] = []
        for predicate in plan.predicates:
            dependency_material: list[Any] = []
            for path in predicate.dependency_paths or predicate.target_paths:
                entries = getattr(snapshot, "entries", {}) if snapshot is not None else {}
                relative_path = path[5:] if path.startswith("/app/") else path
                entry = entries.get(path) or entries.get(relative_path)
                dependency_material.append(
                    (
                        path,
                        None
                        if entry is None
                        else (
                            entry.kind,
                            entry.size,
                            entry.mtime,
                            entry.ctime,
                            entry.link_target,
                            entry.digest,
                        ),
                    )
                )
            dependency_key = hashlib.sha256(_canonical_json(dependency_material)).hexdigest()
            cache_key = (predicate.predicate_id, dependency_key)
            cached = self._completion_cache.get(cache_key)
            if cached is not None:
                self._completion_cache_hits += 1
                self._host_executions.record_cache_hit(
                    category=HostExecCategory.COMPLETION_PROBE,
                    command=predicate.command,
                    action_id=action_id,
                    source_revision=source_revision,
                )
                observations.append(replace(cached, workspace_revision=workspace_revision))
                continue
            try:
                self._completion_probe_execs += 1
                result = await self._host_executions.exec(
                    environment,
                    predicate.command,
                    category=HostExecCategory.COMPLETION_PROBE,
                    action_id=action_id,
                    source_revision=source_revision,
                    cwd=self.cwd,
                    env={},
                    timeout_sec=max(0.05, min(self.completion_check_timeout_sec, timeout_sec)),
                )
                output = (result.stdout or "") + (result.stderr or "")
                returncode = result.return_code
            except Exception as exc:
                output = f"{type(exc).__name__}: {exc}"
                returncode = -1
            observation = PredicateObservation(
                predicate_id=predicate.predicate_id,
                returncode=returncode,
                output=output,
                workspace_revision=workspace_revision,
            )
            observations.append(observation)
            self._completion_cache[cache_key] = observation
        return certificate_from_observations(
            plan,
            tuple(observations),
            workspace_revision=workspace_revision,
            action_id=action_id,
        )

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
        started = time.monotonic()
        self._host_executions = HostExecutionRecorder()
        self._repository_work_receipts = []
        effective_budget = self.execution_budget_sec
        if self.model_loop_timeout_sec is not None:
            legacy_budget = float(self.model_loop_timeout_sec)
            effective_budget = (
                legacy_budget if effective_budget is None else min(effective_budget, legacy_budget)
            )
        deadline = None if effective_budget is None else started + effective_budget
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
        external_paths = task_external_paths(instruction)
        shebang_paths = task_shebang_paths(instruction)
        snapshot = await self._sensor.scan(
            environment,
            cwd=self.cwd,
            recorder=self._host_executions,
            tracked_paths=task_deliverables,
            external_paths=external_paths,
            shebang_paths=shebang_paths,
        )
        source_revision = source_revision_of(snapshot, task_deliverables)
        self._features.begin_task(
            instruction,
            revision=snapshot.revision,
            source_revision=source_revision,
            explicit_checks=explicit_checks,
            task_deliverables=task_deliverables,
        )
        completion_plan = compile_completion_plan(instruction, cwd=self.cwd)
        completion_certificates: list[CompletionCertificate] = []
        self._completion_cache.clear()
        self._completion_cache_hits = 0
        self._completion_probe_execs = 0
        last_completion_workspace_revision = ""
        completion_target_paths = {
            path[len(self.cwd.rstrip("/")) + 1 :]
            if path.startswith(self.cwd.rstrip("/") + "/")
            else path.lstrip("./")
            for path in completion_plan.target_paths
        }
        auto_submit_attempts = 0
        auto_submit_count = 0
        self._progress = ProgressLedger(stall_threshold=3, cycle_threshold=6)
        progress_transitions: list[dict[str, Any]] = []
        seen_semantic_signatures: set[str] = set()
        seen_validation_fingerprints: set[str] = set()
        seen_read_anchors: set[str] = set()
        semantic_progress_kinds: dict[str, int] = {}
        activity_events = 0
        task_progress_changes = 0
        repository_evidence, repository_session = await self._start_repository_session(
            environment,
            instruction,
            snapshot=snapshot,
            source_revision=source_revision,
            task_deliverables=frozenset(task_deliverables),
        )
        self._features.record_repository_evidence_status(
            source_revision=source_revision,
            status=repository_evidence.status,
            available=repository_evidence.available,
            substrate_ready=repository_evidence.substrate_ready,
            retrieval_disposition=repository_evidence.retrieval_disposition,
        )
        if repository_evidence.available:
            self._features.register_structural_evidence(
                source_revision=source_revision,
                anchors=repository_evidence.anchors,
                definitions=repository_evidence.definitions,
                references=repository_evidence.references,
                callers=repository_evidence.callers,
                graph_revision=repository_evidence.graph_revision,
            )
            self._features.consume_effects(action_id=0, call=0)
        if not self.enable_task_start_advisory or self.enable_context_frontier:
            self._features.suppress_task_start_delivery()
        terminal = ""
        solver_exhausted_reason = ""
        graph_gate_reasons = (
            graph_gate_failures(repository_evidence)
            if (
                self.require_graph_ready
                and self.integration_mode is GTIntegrationMode.ACTIVE
                and self.runtime_mode == "treatment"
                and self.enable_repository_intelligence
            )
            else ()
        )
        # Repository failures invalidate the GT treatment analytically, but
        # they must not erase the underlying Mini-SWE solve.  Operationally
        # fail open; the run-level acceptance gate still fails closed on the
        # recorded substrate failure.
        graph_degraded_fallback = bool(graph_gate_reasons)
        graph_gate_blocked = False
        calls = 0
        actions_count = 0
        input_tokens = output_tokens = cache_tokens = 0
        cost = 0.0
        receipts: list[dict[str, Any]] = []
        guidance_deliveries: list[dict[str, Any]] = []
        frontier_decisions: list[dict[str, Any]] = []
        frontier_deliveries: list[dict[str, Any]] = []
        delivered_frontier_fact_ids: set[str] = set()
        delivered_frontier_claim_ids: set[str] = set()
        frontier_chars_delivered = 0
        model_call_contexts: list[dict[str, Any]] = []
        pending_guidance = ""
        pending_prepared_after_call = 0
        no_action_assistant_steps = 0
        context_chars_sent = 0
        model_output_chars = 0
        censored_reason = ""
        context_compactions = 0
        context_chars_elided = 0
        context_compaction_deferrals: list[dict[str, Any]] = []
        pending_reconsideration_cycle = ""
        deadline_reserve_exits = 0
        action_timeout_decisions: list[dict[str, Any]] = []
        previous_provider_messages: list[dict[str, Any]] | None = None
        provider_view_session = ProviderViewSession()

        if (
            repository_evidence.available
            and self.runtime_mode == "treatment"
            and self.enable_task_start_advisory
            and not self.enable_context_frontier
        ):
            pending_guidance = self._features.model_feedback(
                deferred=True, for_call=1, history=messages
            )

        try:
            while not terminal:
                if calls >= self.step_limit:
                    terminal = "StepLimitExceeded"
                    solver_exhausted_reason = "assistant_step_limit"
                    break
                if cost >= self.cost_limit:
                    terminal = "CostLimitExceeded"
                    solver_exhausted_reason = "cost_limit"
                    break
                remaining_to_deadline = None if deadline is None else deadline - time.monotonic()
                if (
                    remaining_to_deadline is not None
                    and remaining_to_deadline <= self.deadline_reserve_sec
                ):
                    terminal = "DeadlineReserveReached"
                    solver_exhausted_reason = "deadline_reserve_reached"
                    deadline_reserve_exits += 1
                    break
                budget_transition = (
                    self._progress.budget_risk(
                        iteration=max(calls, actions_count),
                        limit=self.step_limit,
                        unresolved=not bool(
                            completion_certificates
                            and completion_certificates[-1].auto_submit_eligible
                        ),
                    )
                    if self.enable_progress_control
                    else None
                )
                if budget_transition is not None:
                    progress_transitions.append(
                        {
                            "prior": budget_transition.prior,
                            "current": budget_transition.current,
                            "reason": budget_transition.reason,
                            "streak": budget_transition.streak,
                            "signature": budget_transition.signature,
                            "action_id": actions_count,
                        }
                    )
                calls += 1
                active_state = {
                    **self._features.progress_ledger(),
                    "obligations": list(explicit_checks) or sorted(task_deliverables),
                    "project_checks": list(repository_evidence.project_checks),
                    "source_revision": source_revision,
                    "workspace_revision": snapshot.revision,
                    "decision": {
                        "progress_state": self._progress.state,
                        "completion_plan": completion_plan.status.value,
                        "completion_eligible": bool(
                            completion_certificates
                            and completion_certificates[-1].auto_submit_eligible
                        ),
                    },
                }
                if self.enable_context_compaction:
                    query_messages, provider_view_metrics = provider_view_session.project(
                        messages,
                        active_state=active_state,
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
                compaction_epoch_started = False
                if (
                    self.enable_context_compaction
                    and provider_view_session.epoch == 0
                    and provider_view_metrics.output_chars > self.context_trigger_chars
                ):
                    _preview_view, preview_metrics = build_provider_view(
                        query_messages,
                        active_state=active_state,
                        trigger_chars=1,
                        target_chars=self.context_target_chars,
                        keep_recent_turns=2,
                        transform=True,
                        attach_state_frame=False,
                    )
                    projected_savings = max(
                        0,
                        provider_view_metrics.output_chars - preview_metrics.output_chars,
                    )
                    projected_ratio = (
                        projected_savings / provider_view_metrics.output_chars
                        if provider_view_metrics.output_chars
                        else 0.0
                    )
                    if (
                        projected_savings >= self.context_min_compaction_savings_chars
                        and projected_ratio >= self.context_min_compaction_savings_ratio
                    ):
                        query_messages, provider_view_metrics = provider_view_session.compact(
                            messages,
                            active_state=active_state,
                            target_chars=self.context_target_chars,
                            keep_recent_turns=2,
                            trigger_tokens=0,
                            trigger_kind="provider_view_chars",
                            trigger_chars=provider_view_metrics.output_chars,
                        )
                        context_compactions += 1
                        context_chars_elided += provider_view_metrics.elided_chars
                        compaction_epoch_started = True
                    else:
                        context_compaction_deferrals.append(
                            {
                                "call": calls,
                                "input_chars": provider_view_metrics.output_chars,
                                "projected_output_chars": preview_metrics.output_chars,
                                "projected_savings_chars": projected_savings,
                                "projected_savings_ratio": round(projected_ratio, 6),
                                "reason": "insufficient_cache_break_benefit",
                            }
                        )
                runtime_enrichment_chars = 0
                runtime_message_index: int | None = None
                delivery_metadata: dict[str, Any] | None = None
                frontier_decision = compile_incremental_frontier(
                    repository_evidence,
                    query_messages,
                    source_revision=source_revision,
                    delivered_fact_ids=frozenset(delivered_frontier_fact_ids),
                    delivered_claim_ids=frozenset(delivered_frontier_claim_ids),
                    max_chars=min(
                        1_200,
                        max(
                            0,
                            self.context_frontier_task_budget_chars - frontier_chars_delivered,
                        ),
                    ),
                )
                frontier_payload = (
                    frontier_decision.rendered
                    if (
                        self.enable_context_frontier
                        and self.integration_mode is GTIntegrationMode.ACTIVE
                        and self.runtime_mode == "treatment"
                        and frontier_decision.disposition is FrontierDisposition.SELECTED_FRONTIER
                    )
                    else ""
                )
                guidance_payload = pending_guidance
                runtime_parts = [item for item in (frontier_payload, guidance_payload) if item]
                runtime_payload = "\n\n".join(runtime_parts)
                frontier_decisions.append(
                    {
                        "call": calls,
                        "source_revision": source_revision,
                        "integration_mode": self.integration_mode.value,
                        "delivery_enabled": bool(frontier_payload),
                        **frontier_decision.as_dict(),
                    }
                )
                if runtime_payload:
                    (
                        query_messages,
                        runtime_message_index,
                        runtime_enrichment_chars,
                    ) = _inject_runtime_evidence(query_messages, runtime_payload)
                logical_messages_sha256 = hashlib.sha256(
                    _canonical_json(query_messages)
                ).hexdigest()
                (
                    provider_messages,
                    request_payload_sha256,
                    provider_messages_sha256,
                    provider_request_chars,
                ) = _provider_request_receipt(model, query_messages)
                request_budget = provider_request_budget(
                    provider_messages,
                    model_name=str(self.model_name or ""),
                    context_limit_tokens=self.provider_context_limit_tokens,
                    hard_ratio=self.provider_context_hard_ratio,
                )
                effective_reserve = min(
                    self.provider_context_reserve_tokens,
                    max(1, request_budget.hard_prompt_limit // 4),
                )
                if (
                    self.enable_context_compaction
                    and not compaction_epoch_started
                    and provider_compaction_required(
                        request_budget,
                        reserve_tokens=self.provider_context_reserve_tokens,
                    )
                ):
                    query_messages, provider_view_metrics = provider_view_session.compact(
                        messages,
                        active_state=active_state,
                        target_chars=self.context_target_chars,
                        keep_recent_turns=2,
                        trigger_tokens=request_budget.effective_tokens,
                        trigger_kind="provider_budget",
                        trigger_chars=provider_view_metrics.output_chars,
                    )
                    runtime_enrichment_chars = 0
                    runtime_message_index = None
                    if runtime_payload:
                        (
                            query_messages,
                            runtime_message_index,
                            runtime_enrichment_chars,
                        ) = _inject_runtime_evidence(query_messages, runtime_payload)
                    logical_messages_sha256 = hashlib.sha256(
                        _canonical_json(query_messages)
                    ).hexdigest()
                    (
                        provider_messages,
                        request_payload_sha256,
                        provider_messages_sha256,
                        provider_request_chars,
                    ) = _provider_request_receipt(model, query_messages)
                    request_budget = provider_request_budget(
                        provider_messages,
                        model_name=str(self.model_name or ""),
                        context_limit_tokens=self.provider_context_limit_tokens,
                        hard_ratio=self.provider_context_hard_ratio,
                    )
                    context_compactions += 1
                    context_chars_elided += provider_view_metrics.elided_chars
                    compaction_epoch_started = True
                (
                    stable_prefix_messages,
                    stable_prefix_chars,
                    stable_prefix_ratio,
                ) = _stable_provider_prefix(previous_provider_messages, provider_messages)
                self._features.record_context_compiler_call(
                    call=calls,
                    request_payload_sha256=request_payload_sha256,
                    fact_accounting=provider_view_metrics.fact_accounting,
                )
                if (
                    request_budget.within_limit
                    and runtime_message_index is not None
                    and pending_guidance
                ):
                    delivery_metadata = self._features.confirm_prepared_guidance() or {}
                    pending_guidance = ""
                if (
                    request_budget.within_limit
                    and runtime_message_index is not None
                    and frontier_payload
                ):
                    fact_ids = [fact.fact_id for fact in frontier_decision.facts]
                    claim_ids = [fact.claim_id for fact in frontier_decision.facts]
                    delivered_frontier_fact_ids.update(fact_ids)
                    delivered_frontier_claim_ids.update(claim_ids)
                    frontier_chars_delivered += len(frontier_payload)
                    frontier_deliveries.append(
                        {
                            "call": calls,
                            "source_revision": source_revision,
                            "graph_revision": (
                                frontier_decision.facts[0].graph_revision
                                if frontier_decision.facts
                                else ""
                            ),
                            "fact_ids": fact_ids,
                            "claim_ids": claim_ids,
                            "facts": [fact.as_dict() for fact in frontier_decision.facts],
                            "message_index": runtime_message_index,
                            "request_payload_sha256": request_payload_sha256,
                            "provider_messages_sha256": provider_messages_sha256,
                            "first_eligible_call": calls,
                            "delivered_before_call": calls,
                            "delivered_before_model_query": True,
                            "not_predictive": True,
                            "one_step_late": False,
                            "chars": len(frontier_payload),
                        }
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
                            "chars": len(guidance_payload),
                        }
                    )
                context_parts = {
                    "system_user_chars": 0,
                    "assistant_chars": 0,
                    "tool_observation_chars": 0,
                    "runtime_advisory_chars": len(guidance_payload),
                    "context_frontier_chars": len(frontier_payload),
                    "runtime_separator_chars": max(
                        0,
                        runtime_enrichment_chars - len(guidance_payload) - len(frontier_payload),
                    ),
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
                        "provider_stable_prefix_messages": stable_prefix_messages,
                        "provider_stable_prefix_chars": stable_prefix_chars,
                        "provider_stable_prefix_ratio": stable_prefix_ratio,
                        "request_budget": request_budget.as_dict(),
                        "request_budget_within_limit": request_budget.within_limit,
                        "request_budget_effective_tokens": request_budget.effective_tokens,
                        "request_budget_remaining_tokens": request_budget.remaining_tokens,
                        "runtime_message_index": runtime_message_index,
                        "context_frontier": frontier_decision.as_dict(),
                        "context_frontier_delivered": bool(frontier_payload),
                        "provider_view_compacted": provider_view_metrics.compacted,
                        "provider_compaction_epoch": provider_view_session.epoch,
                        "provider_compaction_epoch_started": compaction_epoch_started,
                        "provider_context_reserve_tokens": effective_reserve,
                        "provider_view_input_chars": provider_view_metrics.input_chars,
                        "provider_view_output_chars": provider_view_metrics.output_chars,
                        "provider_view_elided_chars": provider_view_metrics.elided_chars,
                        "context_compiler": provider_view_metrics.as_dict(),
                        "context_compiler_ran": provider_view_metrics.compiler_ran,
                        "context_fact_candidates": provider_view_metrics.candidate_fact_count,
                        "context_facts_selected": provider_view_metrics.selected_fact_count,
                        "context_facts_represented": (provider_view_metrics.represented_fact_count),
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
                if not request_budget.within_limit:
                    terminal = "ContextBudgetExhausted"
                    solver_exhausted_reason = "context_budget_exhausted"
                    break
                previous_provider_messages = [dict(item) for item in provider_messages]
                try:
                    query_started_at = time.monotonic()
                    model_call_contexts[-1]["query_started_at"] = query_started_at
                    if delivery_metadata is not None:
                        guidance_deliveries[-1]["query_started_at"] = query_started_at
                    remaining_for_query = (
                        None
                        if deadline is None
                        else max(0.0, deadline - query_started_at - self.deadline_reserve_sec)
                    )
                    query_timeout = (
                        self.model_timeout_sec
                        if remaining_for_query is None
                        else (
                            remaining_for_query
                            if self.model_timeout_sec is None
                            else min(float(self.model_timeout_sec), remaining_for_query)
                        )
                    )
                    if query_timeout is not None and query_timeout <= 0:
                        terminal = "DeadlineReserveReached"
                        solver_exhausted_reason = "deadline_reserve_reached"
                        deadline_reserve_exits += 1
                        break
                    message = await asyncio.wait_for(
                        asyncio.to_thread(model.query, query_messages),
                        timeout=query_timeout,
                    )
                except TimeoutError:
                    if (
                        deadline is not None
                        and deadline - time.monotonic() <= self.deadline_reserve_sec + 0.01
                    ):
                        terminal = "DeadlineReserveReached"
                        solver_exhausted_reason = "deadline_reserve_reached"
                        deadline_reserve_exits += 1
                    else:
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
                    str(action.get("command") or action.get("cmd") or "") for action in actions
                )
                compiler_fact_rows = model_call_contexts[-1]["context_compiler"].get(
                    "fact_accounting", []
                )
                for fact_row in compiler_fact_rows:
                    if fact_row.get("disposition") != "selected_state_frame":
                        continue
                    anchors = tuple(
                        str(anchor) for anchor in fact_row.get("action_anchors") or () if anchor
                    )
                    measurable = bool(anchors and next_commands)
                    aligned = measurable and any(
                        anchor in command for anchor in anchors for command in next_commands
                    )
                    fact_row["next_action_measurable"] = measurable
                    fact_row["next_action_anchor_aligned"] = aligned
                    model_call_contexts[-1]["context_selected_facts_action_measurable"] += int(
                        measurable
                    )
                    model_call_contexts[-1]["context_selected_facts_action_aligned"] += int(aligned)
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
                        remaining_for_action = (
                            None
                            if deadline is None
                            else max(
                                0.05,
                                deadline - time.monotonic() - self.deadline_reserve_sec,
                            )
                        )
                        action_timeout, timeout_reason = self._select_action_timeout(
                            proposed,
                            classification,
                            remaining_agent_time_sec=remaining_for_action,
                        )
                        action_timeout_decisions.append(
                            {
                                "action": actions_count,
                                "operation": proposed.operation.value,
                                "validation_authority": classification.authority.value,
                                "requested_timeout_sec": proposed.requested_timeout_sec,
                                "selected_timeout_sec": action_timeout,
                                "reason": timeout_reason,
                            }
                        )
                        result = await self._host_executions.exec(
                            environment,
                            command,
                            category=HostExecCategory.MODEL_ACTION,
                            action_id=actions_count,
                            source_revision=source_revision,
                            cwd=self.cwd,
                            env={},
                            timeout_sec=action_timeout,
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
                    if proposed.mutation_certainty is MutationCertainty.PROVEN_READ_ONLY:
                        self._host_executions.record_cache_hit(
                            category=HostExecCategory.WORKSPACE_MANIFEST,
                            command="[workspace scan skipped: proven read-only action]",
                            action_id=actions_count,
                            source_revision=source_revision,
                        )
                        after = snapshot
                    else:
                        after = await self._sensor.scan(
                            environment,
                            cwd=self.cwd,
                            previous=snapshot,
                            recorder=self._host_executions,
                            action_id=actions_count,
                            source_revision=source_revision,
                            tracked_paths=task_deliverables,
                            external_paths=external_paths,
                            shebang_paths=shebang_paths,
                        )
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
                    ) or (proposed.mutates_workspace and bool(transition.changed_paths))
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
                                    definitions=repository_evidence.definitions,
                                    references=repository_evidence.references,
                                    callers=repository_evidence.callers,
                                    graph_revision=repository_evidence.graph_revision,
                                )
                        else:
                            repository_evidence = repository_session.evidence
                            self._features.refresh_structural_evidence(
                                source_revision=source_revision,
                                anchors=(),
                                definitions=(),
                                references=(),
                                callers=(),
                                graph_revision="",
                            )
                    classification = classification.with_result(
                        result_code=result.return_code,
                        output=output["output"],
                        source_revision=source_revision,
                        workspace_revision=snapshot.revision,
                    )
                    # Workspace activity remains useful for stale-batch safety,
                    # but it is not proof of task progress.  A fixture reset,
                    # scratch-file rewrite, or novel command must not clear
                    # budget risk or prevent semantic stall detection.
                    activity_events += 1
                    source_paths = tuple(
                        sorted(
                            item.path
                            for item in classified_transition
                            if item.validation_relevant
                            and item.origin
                            in {
                                ChangeOrigin.MODEL_AUTHORED,
                                ChangeOrigin.TASK_DELIVERABLE,
                            }
                        )
                    )
                    read_anchors = tuple(
                        sorted(target.path for target in proposed.targets if target.path)
                    )
                    new_read_anchor = bool(
                        proposed.operation in {ActionOperation.READ, ActionOperation.SEARCH}
                        and any(anchor not in seen_read_anchors for anchor in read_anchors)
                    )
                    seen_read_anchors.update(read_anchors)
                    validation_gain = bool(
                        classification.is_validation
                        and classification.status.value == "pass"
                        and classification.status_attributed
                    )
                    diagnostic_gain = bool(
                        classification.is_validation
                        and classification.status.value == "fail"
                        and classification.status_attributed
                        and classification.diagnostic_fingerprint
                        not in seen_validation_fingerprints
                    )
                    if classification.diagnostic_fingerprint:
                        seen_validation_fingerprints.add(classification.diagnostic_fingerprint)
                    if validation_gain:
                        semantic_kind = "validation_gain"
                    elif diagnostic_gain:
                        semantic_kind = "diagnostic_gain"
                    elif new_read_anchor:
                        semantic_kind = "localization_gain"
                    elif source_paths:
                        semantic_kind = "patch_attempt"
                    else:
                        semantic_kind = "no_gain"
                    semantic_progress_kinds[semantic_kind] = (
                        semantic_progress_kinds.get(semantic_kind, 0) + 1
                    )
                    semantic_gain = semantic_kind in {
                        "validation_gain",
                        "diagnostic_gain",
                        "localization_gain",
                    }
                    semantic_signature = hashlib.sha256(
                        _canonical_json(
                            {
                                "kind": semantic_kind,
                                "validation_status": classification.status.value,
                                "declared_check_id": classification.declared_check_id,
                                "failure_fingerprint": classification.diagnostic_fingerprint,
                                "source_paths": source_paths,
                                "read_anchors": read_anchors if new_read_anchor else (),
                            }
                        )
                    ).hexdigest()
                    semantic_information_gain = semantic_signature not in seen_semantic_signatures
                    seen_semantic_signatures.add(semantic_signature)
                    if semantic_gain:
                        task_progress_changes += 1
                    if self.enable_progress_control:
                        progress_transition = self._progress.observe(
                            semantic_signature,
                            information_gain=semantic_information_gain and semantic_gain,
                            changed=bool(source_paths),
                            semantic_gain=semantic_gain,
                            is_error=result.return_code != 0,
                            contradictory=(
                                classification.is_validation and result.return_code != 0
                            ),
                        )
                        if progress_transition is not None:
                            progress_transitions.append(
                                {
                                    "prior": progress_transition.prior,
                                    "current": progress_transition.current,
                                    "reason": progress_transition.reason,
                                    "streak": progress_transition.streak,
                                    "signature": progress_transition.signature,
                                    "semantic_kind": semantic_kind,
                                    "action_id": actions_count,
                                }
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
                    auto_submitted = False
                    completion_triggered = bool(
                        self.enable_completion_controller
                        and completion_plan.executable
                        and snapshot.healthy
                        and snapshot.revision != last_completion_workspace_revision
                        and (
                            bool(set(transition.changed_paths) & completion_target_paths)
                            or proposed.operation is ActionOperation.VALIDATE
                        )
                    )
                    if completion_triggered:
                        remaining_for_checks = (
                            self.completion_check_timeout_sec
                            if deadline is None
                            else max(
                                0.05,
                                deadline - time.monotonic() - self.deadline_reserve_sec,
                            )
                        )
                        certificate = await self._evaluate_completion(
                            environment,
                            completion_plan,
                            workspace_revision=snapshot.revision,
                            source_revision=source_revision,
                            snapshot=snapshot,
                            action_id=actions_count,
                            timeout_sec=remaining_for_checks,
                        )
                        completion_certificates.append(certificate)
                        last_completion_workspace_revision = snapshot.revision
                        receipts.append(
                            {
                                "action": actions_count,
                                "kind": "completion_certificate",
                                "decision": (
                                    "AUTO_SUBMIT"
                                    if certificate.auto_submit_eligible
                                    else "CONTINUE"
                                ),
                                "revision": snapshot.revision,
                                "reason_codes": list(certificate.reason_codes),
                            }
                        )
                        if certificate.auto_submit_eligible:
                            auto_submit_attempts += 1
                            try:
                                submit_result = await self._host_executions.exec(
                                    environment,
                                    "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT",
                                    category=HostExecCategory.AUTO_SUBMIT,
                                    action_id=actions_count,
                                    source_revision=source_revision,
                                    cwd=self.cwd,
                                    env={},
                                    timeout_sec=max(0.05, min(5.0, remaining_for_checks)),
                                )
                            except Exception:
                                submit_result = ExecResult(return_code=-1)
                            if submit_result.return_code == 0:
                                auto_submit_count += 1
                                auto_submitted = True
                                readiness_evidence = self._ledger.readiness_evidence(
                                    source_revision
                                )
                                self._features.record_submit(
                                    action_id=actions_count,
                                    revision=snapshot.revision,
                                    source_revision=source_revision,
                                    refused=False,
                                    sensor_healthy=snapshot.healthy,
                                    check_count=(
                                        len(readiness_evidence) + len(certificate.observations)
                                    ),
                                    passing_checks=sum(
                                        item.returncode == 0 for item in readiness_evidence
                                    )
                                    + sum(
                                        item.returncode == 0 for item in certificate.observations
                                    ),
                                    failing_checks=sum(
                                        item.returncode != 0 for item in readiness_evidence
                                    )
                                    + sum(
                                        item.returncode != 0 for item in certificate.observations
                                    ),
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
                            proposed.operation in {ActionOperation.VALIDATE, ActionOperation.SUBMIT}
                            or material_workspace_change
                            or source_revision != proposed.source_revision
                        )
                    )
                    if effects and not (submit or auto_submitted):
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
                    if submit or auto_submitted:
                        cancelled = len(actions) - index - 1
                        if cancelled:
                            if self.preflight_mode is not PreflightMode.OFF:
                                for cancelled_proposal in proposed_actions[index + 1 :]:
                                    self._features.record_cancelled_proposal(
                                        cancelled_proposal,
                                        mode=self.preflight_mode,
                                        reason=(
                                            "completion_auto_submit"
                                            if auto_submitted
                                            else "terminal_submit"
                                        ),
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
                                reason=(
                                    "completion_auto_submit"
                                    if auto_submitted
                                    else "terminal_submit"
                                ),
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
                    feature_feedback = self._features.model_feedback(
                        deferred=True, history=messages
                    )
                    if feature_feedback and self.runtime_mode == "treatment":
                        pending_guidance = feature_feedback
                        pending_prepared_after_call = calls
                observation_messages = list(
                    model.format_observation_messages(message, outputs, variables)
                )
                observation_start_index = len(messages)
                for observation_offset, (observation, proposed, output) in enumerate(
                    zip(observation_messages, proposed_actions, outputs, strict=True)
                ):
                    # Private typed metadata lets the provider-view governor
                    # reuse the single preflight classification.  Mini-SWE's
                    # provider adapter strips ``extra`` before model.query.
                    private_extra = dict(observation.get("extra") or {})
                    private_extra.update(
                        {
                            "operation": proposed.operation.value,
                            "action_id": proposed.action_id,
                            "observation_index": observation_start_index + observation_offset,
                            "returncode": int(output.get("returncode") or 0),
                        }
                    )
                    observation["extra"] = private_extra
                messages.extend(observation_messages)

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
            host_execution = self._host_executions.summary()
            repository_required = bool(
                self.enable_repository_intelligence
                and self.integration_mode is GTIntegrationMode.ACTIVE
                and self.runtime_mode == "treatment"
            )
            frontier_required = bool(repository_required and self.enable_context_frontier)
            repository_applicability = classify_repository_applicability(repository_evidence)
            intelligence_failures: list[str] = []
            transient_intelligence_failures: list[str] = []
            if repository_required and not repository_evidence.substrate_ready:
                intelligence_failures.append(
                    repository_evidence.status or "repository_intelligence_invalid"
                )
            final_graph_gate_reasons = (
                graph_gate_failures(repository_evidence)
                if (
                    self.require_graph_ready
                    and self.integration_mode is GTIntegrationMode.ACTIVE
                    and self.runtime_mode == "treatment"
                    and self.enable_repository_intelligence
                )
                else ()
            )
            intelligence_failures.extend(final_graph_gate_reasons)
            transient_intelligence_failures.extend(
                f"graph_gate:{reason}"
                for reason in graph_gate_reasons
                if reason not in final_graph_gate_reasons
            )
            if repository_required and repository_session is not None:
                refresh_current, refresh_transient = _partition_recovered_repository_failures(
                    repository_session.refresh_log,
                    current_source_revision=str(
                        repository_session.source_revision or repository_evidence.source_revision
                    ),
                    failure_values=frozenset(
                        status.value
                        for status in RepositoryIntelligenceStatus
                        if status is not RepositoryIntelligenceStatus.HEALTHY_CURRENT
                    ),
                    prefix="repository_refresh",
                )
                intelligence_failures.extend(refresh_current)
                transient_intelligence_failures.extend(refresh_transient)
            if frontier_required:
                frontier_current, frontier_transient = _partition_recovered_repository_failures(
                    frontier_decisions,
                    current_source_revision=str(
                        repository_session.source_revision
                        if repository_session is not None
                        else repository_evidence.source_revision
                    ),
                    failure_values=frozenset(
                        {
                            FrontierDisposition.SUBSTRATE_FAILURE.value,
                            FrontierDisposition.STALE_SOURCE_REVISION.value,
                        }
                    ),
                    prefix="frontier",
                )
                intelligence_failures.extend(frontier_current)
                transient_intelligence_failures.extend(frontier_transient)
                if any(
                    int(row.get("candidate_count") or 0) != int(row.get("accounted_count") or 0)
                    for row in frontier_decisions
                ):
                    intelligence_failures.append("frontier_fact_accounting_incomplete")
                delivered_ids = [
                    str(fact_id)
                    for row in frontier_deliveries
                    for fact_id in row.get("fact_ids") or ()
                ]
                if len(delivered_ids) != len(set(delivered_ids)):
                    intelligence_failures.append("duplicate_frontier_fact_delivery")
                delivered_claims = [
                    str(claim_id)
                    for row in frontier_deliveries
                    for claim_id in row.get("claim_ids") or ()
                ]
                if len(delivered_claims) != len(set(delivered_claims)):
                    intelligence_failures.append("duplicate_frontier_claim_delivery")
                if frontier_chars_delivered > self.context_frontier_task_budget_chars:
                    intelligence_failures.append("frontier_task_budget_exceeded")
            frontier_material_undelivered = bool(
                frontier_required
                and not frontier_deliveries
                and any(
                    row.get("disposition") == FrontierDisposition.SELECTED_FRONTIER.value
                    for row in frontier_decisions
                )
            )
            if frontier_material_undelivered:
                intelligence_failures.append("material_frontier_not_delivered")
            frontier_coverage = (
                "delivered"
                if frontier_deliveries
                else "represented_in_provider_history"
                if any(
                    row.get("disposition") == FrontierDisposition.REPRESENTED_MESSAGE.value
                    for row in frontier_decisions
                )
                else "no_certified_incremental_fact"
                if frontier_decisions
                else "no_provider_call"
            )
            intelligence_failures = list(dict.fromkeys(intelligence_failures))
            transient_intelligence_failures = list(dict.fromkeys(transient_intelligence_failures))
            intelligence_status = (
                "disabled"
                if not self.enable_repository_intelligence
                else "shadow"
                if self.integration_mode is not GTIntegrationMode.ACTIVE
                or self.runtime_mode != "treatment"
                else "not_applicable"
                if repository_applicability
                == "not_applicable_no_supported_source"
                else "failed"
                if intelligence_failures
                else "passed"
            )
            bounded_observation_applications = [
                dict(observation)
                for call_row in model_call_contexts
                for observation in (
                    (call_row.get("context_compiler") or {}).get("bounded_observations") or ()
                )
            ]
            unique_bounded_observations: dict[tuple[int, str], dict[str, Any]] = {}
            for observation in bounded_observation_applications:
                key = (
                    int(observation.get("observation_index") or 0),
                    str(observation.get("full_sha256") or ""),
                )
                unique_bounded_observations.setdefault(key, observation)
            bounded_operation_counts: dict[str, int] = {}
            for observation in unique_bounded_observations.values():
                operation = str(observation.get("operation") or "other")
                bounded_operation_counts[operation] = (
                    bounded_operation_counts.get(operation, 0) + 1
                )
            mirror_plan_rows = [
                row
                for row in self._repository_work_receipts
                if row.get("kind") == "source_mirror_plan"
            ]
            mirror_plan = mirror_plan_rows[-1] if mirror_plan_rows else {}
            frontier_candidate_language_counts: dict[str, int] = {}
            for decision in frontier_decisions:
                for fact in decision.get("accounting") or ():
                    language = str(fact.get("language") or "unknown")
                    frontier_candidate_language_counts[language] = (
                        frontier_candidate_language_counts.get(language, 0) + 1
                    )
            frontier_delivered_language_counts: dict[str, int] = {}
            for delivery in frontier_deliveries:
                for fact in delivery.get("facts") or ():
                    language = str(fact.get("language") or "unknown")
                    frontier_delivered_language_counts[language] = (
                        frontier_delivered_language_counts.get(language, 0) + 1
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
                    int(row.get("provider_request_chars") or 0) for row in model_call_contexts
                ),
                "provider_requests_hashed": sum(
                    bool(row.get("provider_messages_sha256"))
                    and bool(row.get("request_payload_sha256"))
                    for row in model_call_contexts
                ),
                "provider_request_hash_coverage": (
                    round(
                        sum(
                            bool(row.get("provider_messages_sha256")) for row in model_call_contexts
                        )
                        / len(model_call_contexts),
                        6,
                    )
                    if model_call_contexts
                    else 1.0
                ),
                "provider_request_budget_failures": sum(
                    not bool(row.get("request_budget_within_limit", True))
                    for row in model_call_contexts
                ),
                "provider_request_min_headroom_tokens": min(
                    (
                        int(row.get("request_budget_remaining_tokens") or 0)
                        for row in model_call_contexts
                    ),
                    default=self.provider_context_limit_tokens,
                ),
                "provider_stable_prefix_chars": sum(
                    int(row.get("provider_stable_prefix_chars") or 0) for row in model_call_contexts
                ),
                "provider_stable_prefix_ratio_mean": (
                    round(
                        sum(
                            float(row.get("provider_stable_prefix_ratio") or 0.0)
                            for row in model_call_contexts[1:]
                        )
                        / len(model_call_contexts[1:]),
                        6,
                    )
                    if len(model_call_contexts) > 1
                    else 0.0
                ),
                "provider_context_limit_tokens": self.provider_context_limit_tokens,
                "provider_context_hard_ratio": self.provider_context_hard_ratio,
                "provider_context_reserve_tokens": self.provider_context_reserve_tokens,
                "context_compactions": context_compactions,
                "context_compaction_epochs": [
                    item.as_dict() for item in provider_view_session.receipts
                ],
                "context_compaction_deferrals": context_compaction_deferrals,
                "context_compaction_deferral_count": len(
                    context_compaction_deferrals
                ),
                "context_chars_elided": context_chars_elided,
                "context_capacity_chars": self.context_capacity_chars,
                "context_trigger_chars": self.context_trigger_chars,
                "context_target_chars": self.context_target_chars,
                "context_min_compaction_savings_chars": (
                    self.context_min_compaction_savings_chars
                ),
                "context_min_compaction_savings_ratio": (
                    self.context_min_compaction_savings_ratio
                ),
                "completion_plan_status": completion_plan.status.value,
                "completion_predicates": len(completion_plan.predicates),
                "completion_certificate_evaluations": len(completion_certificates),
                "completion_predicate_checks": sum(
                    len(item.observations) for item in completion_certificates
                ),
                "completion_probe_execs": self._completion_probe_execs,
                "completion_cache_hits": self._completion_cache_hits,
                "completion_certificates_complete": sum(
                    item.status is CompletionStatus.COMPLETE for item in completion_certificates
                ),
                "auto_submit_attempts": auto_submit_attempts,
                "auto_submits": auto_submit_count,
                "effective_actions": host_execution["effective_task_actions"],
                "effective_actions_schema": "actual-task-environment-execs-v2",
                "effective_task_actions": host_execution["effective_task_actions"],
                "actual_environment_execs": host_execution["actual_environment_execs"],
                "controller_environment_execs": host_execution["controller_environment_execs"],
                "controller_cached_reads": host_execution["controller_cached_reads"],
                "sensor_environment_execs": host_execution["sensor_environment_execs"],
                "host_exec_category_counts": host_execution["category_counts"],
                "host_exec_category_latency": host_execution["category_latency"],
                "progress_state": self._progress.state,
                "progress_transitions": len(progress_transitions),
                "task_progress_changes": task_progress_changes,
                "activity_events": activity_events,
                "semantic_progress_kinds": dict(semantic_progress_kinds),
                "deadline_configured": effective_budget is not None,
                "execution_budget_sec": effective_budget,
                "deadline_reserve_sec": self.deadline_reserve_sec,
                "deadline_reserve_exits": deadline_reserve_exits,
                "action_timeout_decisions": action_timeout_decisions,
                "context_compiler_calls": sum(
                    bool(row.get("context_compiler_ran")) for row in model_call_contexts
                ),
                "context_fact_candidates": sum(
                    int(row.get("context_fact_candidates") or 0) for row in model_call_contexts
                ),
                "context_facts_selected": sum(
                    int(row.get("context_facts_selected") or 0) for row in model_call_contexts
                ),
                "context_facts_represented": sum(
                    int(row.get("context_facts_represented") or 0) for row in model_call_contexts
                ),
                "context_facts_controller_only": sum(
                    int(row.get("context_facts_controller_only") or 0)
                    for row in model_call_contexts
                ),
                "context_facts_omitted": sum(
                    int(row.get("context_facts_omitted") or 0) for row in model_call_contexts
                ),
                "context_facts_accounted": sum(
                    int(row.get("context_facts_accounted") or 0) for row in model_call_contexts
                ),
                "context_frontier_calls": len(frontier_decisions),
                "context_frontier_candidates": sum(
                    int(row.get("candidate_count") or 0) for row in frontier_decisions
                ),
                "context_frontier_accounted": sum(
                    int(row.get("accounted_count") or 0) for row in frontier_decisions
                ),
                "context_frontier_deliveries": len(frontier_deliveries),
                "context_frontier_facts_delivered": sum(
                    len(row.get("facts") or ()) for row in frontier_deliveries
                ),
                "context_frontier_chars_added": sum(
                    int(row.get("chars") or 0) for row in frontier_deliveries
                ),
                "context_frontier_task_budget_chars": (self.context_frontier_task_budget_chars),
                "context_frontier_budget_remaining_chars": max(
                    0,
                    self.context_frontier_task_budget_chars - frontier_chars_delivered,
                ),
                "context_frontier_duplicate_facts": (
                    sum(len(row.get("fact_ids") or ()) for row in frontier_deliveries)
                    - len(delivered_frontier_fact_ids)
                ),
                "context_frontier_duplicate_claims": (
                    sum(len(row.get("claim_ids") or ()) for row in frontier_deliveries)
                    - len(delivered_frontier_claim_ids)
                ),
                "context_frontier_zero_tasks": int(frontier_required and not frontier_deliveries),
                "context_frontier_candidate_languages": len(
                    frontier_candidate_language_counts
                ),
                "context_frontier_delivered_languages": len(
                    frontier_delivered_language_counts
                ),
                "context_frontier_candidate_language_counts": dict(
                    sorted(frontier_candidate_language_counts.items())
                ),
                "context_frontier_delivered_language_counts": dict(
                    sorted(frontier_delivered_language_counts.items())
                ),
                "context_frontier_coverage": frontier_coverage,
                "repository_intelligence_status": intelligence_status,
                "repository_intelligence_failures": list(intelligence_failures),
                "repository_intelligence_valid": int(
                    intelligence_status in {"disabled", "shadow", "passed"}
                ),
                "repository_graph_gate_enabled": int(self.require_graph_ready),
                "repository_graph_gate_blocked": int(graph_gate_blocked),
                "repository_graph_degraded_fallback": int(graph_degraded_fallback),
                "repository_graph_gate_failures": list(final_graph_gate_reasons),
                "repository_graph_gate_initial_failures": list(graph_gate_reasons),
                "repository_graph_schema_valid": int(
                    bool(repository_evidence.index and repository_evidence.index.schema_valid)
                ),
                "repository_graph_source_revision": (
                    repository_evidence.index.source_revision
                    if repository_evidence.index is not None
                    else ""
                ),
                "repository_graph_nodes": int(
                    repository_evidence.index.node_count
                    if repository_evidence.index is not None
                    else 0
                ),
                "repository_graph_edges": int(
                    repository_evidence.index.edge_count
                    if repository_evidence.index is not None
                    else 0
                ),
                "repository_source_files": int(
                    repository_evidence.index.source_files
                    if repository_evidence.index is not None
                    else 0
                ),
                "repository_indexable_files": int(
                    repository_evidence.index.indexable_files
                    if repository_evidence.index is not None
                    else 0
                ),
                "repository_ambiguous_source_files": int(
                    len(repository_evidence.index.ambiguous_paths)
                    if repository_evidence.index is not None
                    else 0
                ),
                "repository_unsupported_source_files": int(
                    len(repository_evidence.index.unsupported_paths)
                    if repository_evidence.index is not None
                    else 0
                ),
                "repository_resolved_languages": int(
                    len(repository_evidence.index.language_file_counts)
                    if repository_evidence.index is not None
                    else 0
                ),
                "repository_resolution_reason_kinds": int(
                    len(repository_evidence.index.resolution_reason_counts)
                    if repository_evidence.index is not None
                    else 0
                ),
                "repository_parser_failures": int(
                    repository_evidence.index.parser_failures
                    if repository_evidence.index is not None
                    else 0
                ),
                "repository_language_file_counts": dict(
                    repository_evidence.index.language_file_counts
                    if repository_evidence.index is not None
                    else ()
                ),
                "repository_resolution_reason_counts": dict(
                    repository_evidence.index.resolution_reason_counts
                    if repository_evidence.index is not None
                    else ()
                ),
                "repository_refreshes": (
                    len(repository_session.refresh_log) if repository_session is not None else 0
                ),
                "repository_mirror_transfer_ms": round(
                    sum(
                        float(row.get("duration_ms") or 0.0)
                        for row in self._repository_work_receipts
                        if row.get("kind") == "mirror_transfer"
                    ),
                    6,
                ),
                "repository_mirror_files": sum(
                    int(row.get("files") or 0)
                    for row in self._repository_work_receipts
                    if row.get("kind") == "mirror_transfer"
                ),
                "repository_mirror_bytes": sum(
                    int(row.get("bytes") or 0)
                    for row in self._repository_work_receipts
                    if row.get("kind") == "mirror_transfer"
                ),
                "repository_mirror_selected_source_files": int(
                    mirror_plan.get("source_files") or 0
                ),
                "repository_mirror_selected_metadata_files": int(
                    mirror_plan.get("metadata_files") or 0
                ),
                "repository_mirror_excluded_artifacts": int(
                    mirror_plan.get("excluded_artifacts") or 0
                ),
                "repository_mirror_excluded_deliverables": int(
                    mirror_plan.get("excluded_deliverables") or 0
                ),
                "repository_mirror_excluded_oversize": int(
                    mirror_plan.get("excluded_oversize") or 0
                ),
                "repository_mirror_excluded_budget": int(
                    mirror_plan.get("excluded_budget") or 0
                ),
                "repository_index_refresh_ms": round(
                    sum(
                        float(row.get("elapsed_ms") or 0.0)
                        for row in (
                            repository_session.refresh_log if repository_session is not None else ()
                        )
                    ),
                    6,
                ),
                "repository_full_refreshes": sum(
                    row.get("mode") == "full"
                    for row in (
                        repository_session.refresh_log if repository_session is not None else ()
                    )
                ),
                "repository_incremental_refreshes": sum(
                    row.get("mode") == "incremental"
                    for row in (
                        repository_session.refresh_log if repository_session is not None else ()
                    )
                ),
                "repository_revision_cache_hits": sum(
                    row.get("mode") == "revision_cache_hit"
                    for row in (
                        repository_session.refresh_log if repository_session is not None else ()
                    )
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
                    int(row.get("context_stale_facts") or 0) for row in model_call_contexts
                ),
                "context_duplicate_facts": sum(
                    int(row.get("context_duplicate_facts") or 0) for row in model_call_contexts
                ),
                "context_exact_duplicate_chars_removed": sum(
                    int(row.get("context_exact_duplicate_chars_removed") or 0)
                    for row in model_call_contexts
                ),
                "context_unique_reasoning_chars_removed": sum(
                    int(row.get("context_unique_reasoning_chars_removed") or 0)
                    for row in model_call_contexts
                ),
                "context_bounded_observations": len(unique_bounded_observations),
                "context_bounded_observation_applications": len(
                    bounded_observation_applications
                ),
                "context_bounded_observation_chars_removed": sum(
                    int(row.get("omitted_chars") or 0)
                    for row in unique_bounded_observations.values()
                ),
                "context_bounded_observation_operation_counts": bounded_operation_counts,
                "context_duplicate_turns_represented": sum(
                    int((row.get("context_compiler") or {}).get("duplicate_turns_represented") or 0)
                    for row in model_call_contexts
                ),
                "context_old_tool_results_cleared": sum(
                    int((row.get("context_compiler") or {}).get("old_tool_results_cleared") or 0)
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
                    nested.get("segment_role", SegmentRole.UNKNOWN.value)
                    == SegmentRole.ACTION.value
                    for row in preflight_rows
                    for nested in row["proposed"].get("operations") or ()
                ),
                "preflight_unknown_segment_operations": sum(
                    nested.get("segment_role", SegmentRole.UNKNOWN.value)
                    == SegmentRole.UNKNOWN.value
                    for row in preflight_rows
                    for nested in row["proposed"].get("operations") or ()
                ),
                "preflight_shell_context_segments": sum(
                    nested.get("segment_role") == SegmentRole.SHELL_CONTEXT.value
                    for row in preflight_rows
                    for nested in row["proposed"].get("operations") or ()
                ),
                "preflight_output_only_segments": sum(
                    nested.get("segment_role") == SegmentRole.OUTPUT_ONLY.value
                    for row in preflight_rows
                    for nested in row["proposed"].get("operations") or ()
                ),
                "preflight_opaque_program_segments": sum(
                    nested.get("segment_role") == SegmentRole.OPAQUE_PROGRAM.value
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
                "preflight_parse_coverage": {
                    "mean": round(
                        sum(
                            float(row["proposed"].get("parse_coverage") or 0.0)
                            for row in preflight_rows
                        )
                        / len(preflight_rows),
                        6,
                    )
                    if preflight_rows
                    else 0.0,
                    "min": round(
                        min(
                            float(row["proposed"].get("parse_coverage") or 0.0)
                            for row in preflight_rows
                        ),
                        6,
                    )
                    if preflight_rows
                    else 0.0,
                },
                "preflight_mutation_certainty_distribution": {
                    certainty: sum(
                        row["proposed"].get("mutation_certainty") == certainty
                        for row in preflight_rows
                    )
                    for certainty in ("proven_read_only", "may_mutate", "proven_mutating")
                },
                "preflight_actions_with_unknown_segments": sum(
                    bool(row["proposed"].get("has_unknown_segments")) for row in preflight_rows
                ),
                "preflight_actions_with_opaque_segments": sum(
                    bool(row["proposed"].get("has_opaque_segments")) for row in preflight_rows
                ),
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
                    bool(row.get("is_validation")) and not bool(row.get("status_attributed"))
                    for row in feature_summary.get("validation_log") or ()
                ),
                "stale_batched_actions_prevented": sum(
                    int(row.get("cancelled") or 0) for row in feature_summary["batch_interrupts"]
                ),
                "model_output_chars": model_output_chars,
                "no_action_assistant_steps": no_action_assistant_steps,
                "censored": bool(censored_reason),
                "censored_reason": censored_reason,
                "solver_exhausted": bool(solver_exhausted_reason),
                "solver_exhausted_reason": solver_exhausted_reason,
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
                    + int(row.get("context_frontier_chars") or 0)
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
                        "repository_work_receipts": list(self._repository_work_receipts),
                        "checkpoint_ledger": self._checkpoints.summary(),
                        "completion": {
                            "plan": completion_plan.as_dict(),
                            "certificates": [item.as_dict() for item in completion_certificates],
                            "latest_certificate": (
                                completion_certificates[-1].as_dict()
                                if completion_certificates
                                else None
                            ),
                            "auto_submit_attempts": auto_submit_attempts,
                            "auto_submit_count": auto_submit_count,
                        },
                        "progress": {
                            "state": self._progress.state,
                            "transitions": progress_transitions,
                        },
                        "deadline": {
                            "execution_budget_sec": effective_budget,
                            "reserve_sec": self.deadline_reserve_sec,
                            "elapsed_sec": elapsed_seconds,
                            "remaining_sec": (
                                None if deadline is None else max(0.0, deadline - time.monotonic())
                            ),
                            "reserve_exits": deadline_reserve_exits,
                        },
                        "metrics": deep_metrics,
                        "repository_intelligence": {
                            "status": intelligence_status,
                            "required": repository_required,
                            "frontier_required": frontier_required,
                            "applicability": repository_applicability,
                            "denominator_excluded": repository_applicability
                            == "not_applicable_no_supported_source",
                            "failures": list(intelligence_failures),
                            "transient_failures": list(transient_intelligence_failures),
                            "frontier_decisions": frontier_decisions,
                            "frontier_deliveries": frontier_deliveries,
                            "graph_gate": {
                                "enabled": bool(self.require_graph_ready),
                                "blocked": graph_gate_blocked,
                                "degraded_fallback": graph_degraded_fallback,
                                "failures": list(final_graph_gate_reasons),
                                "initial_failures": list(graph_gate_reasons),
                            },
                        },
                        "host_execution": host_execution,
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
                "solver_exhausted": bool(solver_exhausted_reason),
                "solver_exhausted_reason": solver_exhausted_reason,
                "completion_plan_status": completion_plan.status.value,
                "completion_certificates": len(completion_certificates),
                "auto_submits": auto_submit_count,
                "progress_state": self._progress.state,
                "execution_budget_sec": effective_budget,
                "deadline_reserve_exits": deadline_reserve_exits,
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
