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
import posixpath
import re
import shlex
import tarfile
import time
import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
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
    ValidationStatus,
    WorkspaceSensor,
    classify_change,
    classify_validation_command,
    diff_snapshots,
    explicit_check_commands,
    graph_revision_receipt,
    is_check_command,
    is_submit_command,
    lint_commands,
    normalize_command,
    source_revision_receipt,
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
    RepositoryFactTracker,
    compile_incremental_frontier,
)
from gt_engine.contributions import (
    ContributionKind,
    GTContribution,
    compile_contributions,
)
from gt_engine.decision_sufficiency import (
    DecisionEvidenceBundle,
    DecisionSufficiencyDisposition,
    ProviderVisibleState,
    compile_decision_sufficiency,
)
from gt_engine.deep_metrics import normalized_token_cost
from gt_engine.diagnostics import extract_diagnostic_anchors
from gt_engine.host_execution import HostExecCategory, HostExecutionRecorder
from gt_engine.hybrid_repository import HybridRepository, build_hybrid_repository
from gt_engine.hybrid_retrieval import (
    HybridRetriever,
    RetrievalActionState,
    RetrievalIntent,
    RetrievalState,
    build_preemptive_frame,
)
from gt_engine.preemptive_retrieval import (
    PreemptiveFrame,
    PreemptiveFrameCompilation,
    PreemptiveFrameStatus,
    compile_preemptive_frame,
)
from gt_engine.preflight import (
    PREFLIGHT_FEATURE_PLACEMENT,
    ActionDisposition,
    ActionOperation,
    EvidenceGrade,
    PreflightDecision,
    PreflightMode,
    ProposedAction,
    SegmentRole,
    WorkspaceImpact,
    adapt_proposed_action,
    classify_workspace_impact,
    pass_decision,
)
from gt_engine.progress import (
    ActionResultKind,
    ProgressLedger,
    ProgressObservation,
    StallAggregateFact,
    classify_action_result,
    semantic_progress_fingerprint,
    task_information_gain,
)
from gt_engine.provider_evidence import (
    ProviderEvidenceDisposition,
    ProviderEvidenceLedger,
    ProviderEvidenceSurface,
)
from gt_engine.provider_view import (
    DEFAULT_MIN_COMPACTION_SAVINGS_CHARS,
    DEFAULT_MIN_COMPACTION_SAVINGS_RATIO,
    DEFAULT_SOFT_COMPACTION_TARGET_CHARS,
    DEFAULT_SOFT_COMPACTION_TRIGGER_CHARS,
    ProviderViewSession,
    build_provider_view,
    provider_compaction_required,
    provider_compaction_target_chars,
    provider_request_budget,
)
from gt_engine.replay_bundle import ReplayBundleWriter
from gt_engine.repository_intelligence import (
    RepositoryEvidence,
    RepositoryIntelligenceStatus,
    RepositorySession,
    classify_repository_applicability,
    graph_gate_failures,
)
from gt_engine.repository_mirror import SourceMirrorPlan, plan_source_mirror
from gt_engine.retrieval_profile import FINAL_RETRIEVAL_PROFILE
from gt_engine.snowflake_onnx import SnowflakeOnnxDenseBackend
from gt_engine.task_contract import task_external_paths, task_shebang_paths
from gt_engine.trajectory_utilization import SemanticUtilizationTracker
from gt_engine.uplift_policy import (
    EvidenceAuthority,
    GTPolicyMode,
    OpportunityKind,
    certify_opportunity,
)


def _message_context_chars(message: dict[str, Any]) -> int:
    """Count assistant fields that are retained in the next provider request."""
    text = str(message.get("content") or "") + str(message.get("reasoning_content") or "")
    for key in ("tool_calls", "function_call"):
        value = message.get(key)
        if value:
            text += json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return len(text)


def _workspace_target_path(path: str, *, cwd: str | None = None) -> str:
    normalized = str(path or "").strip().replace("\\", "/")
    resolved_cwd = posixpath.normpath(str(cwd or "/app"))
    if resolved_cwd != "/" and normalized.startswith(resolved_cwd.rstrip("/") + "/"):
        return normalized[len(resolved_cwd.rstrip("/")) + 1 :]
    if normalized.startswith("./"):
        return normalized[2:]
    return normalized


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


def _graph_gate_degraded_fallback(
    *, initial_failures: tuple[str, ...], current_failures: tuple[str, ...]
) -> bool:
    """Report only an unresolved graph failure as treatment degradation.

    A task may begin with no source files because its deliverable is created by
    the model (for example, a blank task containing only weights/data).  The
    initial graph gate is still recorded for audit, but a later current graph
    must clear the operational degradation flag.  The merge gate should fail
    only when the final source-bound substrate remains unhealthy.
    """

    del initial_failures  # retained in the receipt as historical evidence
    return bool(current_failures)


def _resolved_repository_evidence(
    observed: RepositoryEvidence,
    session: RepositorySession | None,
) -> RepositoryEvidence:
    """Use the session's final atomic state after any recovered refresh."""

    return session.evidence if session is not None else observed


def _model_kwargs(model: Any) -> dict[str, Any]:
    direct = getattr(model, "model_kwargs", None)
    if isinstance(direct, dict):
        return dict(direct)
    configured = getattr(getattr(model, "config", None), "model_kwargs", None)
    return dict(configured) if isinstance(configured, dict) else {}


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
    # Mini-SWE's LitellmModel passes the built-in Bash schema directly to
    # litellm rather than exposing a ``model.tools`` attribute.  The hash must
    # include the actual provider tool schema; otherwise control/treatment
    # requests are not reproducible even when their messages match.
    provider_tools = getattr(model, "tools", None) or [BASH_TOOL]
    envelope = {
        "model": str(
            getattr(getattr(model, "config", None), "model_name", "")
            or getattr(model, "model_name", "")
        ),
        "model_kwargs": _model_kwargs(model),
        "tools": provider_tools,
        "messages": prepared,
    }
    messages_bytes = _canonical_json(prepared)
    return (
        prepared,
        hashlib.sha256(_canonical_json(envelope)).hexdigest(),
        hashlib.sha256(messages_bytes).hexdigest(),
        len(messages_bytes.decode("utf-8")),
    )


def _provider_route_configuration(model: Any) -> dict[str, Any]:
    """Return the non-secret provider route that participates in every call."""

    model_name = str(
        getattr(getattr(model, "config", None), "model_name", "")
        or getattr(model, "model_name", "")
    )
    kwargs = _model_kwargs(model)
    provider_policy = dict((kwargs.get("extra_body") or {}).get("provider") or {})
    return {
        "model": model_name,
        "api_base": str(kwargs.get("api_base") or ""),
        "provider_policy": provider_policy,
        "credential_in_receipt": any(
            key in kwargs for key in ("api_key", "authorization", "headers")
        ),
    }


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


def _changed_provider_message_indices(
    stock: list[dict[str, Any]], current: list[dict[str, Any]]
) -> list[int]:
    """Return exact provider-message positions changed by the GT treatment."""

    changed: list[int] = []
    for index in range(max(len(stock), len(current))):
        if index >= len(stock) or index >= len(current):
            changed.append(index)
        elif _canonical_json(stock[index]) != _canonical_json(current[index]):
            changed.append(index)
    return changed


def _preemptive_frame_identity(
    query_hash: str,
    claim_hashes: tuple[str, ...],
    eligible_call: int,
    source_revision: str,
) -> str:
    """Return a stable ID for one concrete preemptive evidence delivery.

    A retrieval query can recur while the selected claims change after a
    workspace/graph transition.  The receipt identity therefore includes the
    claim set and delivery window, not only the query hash.
    """

    return hashlib.sha256(
        json.dumps(
            {
                "query_hash": query_hash,
                "claim_hashes": list(claim_hashes),
                "eligible_call": eligible_call,
                "source_revision": source_revision,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:20]


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


def _retrieval_intent(
    *,
    operation: str,
    validation_state: str,
    changed_paths: tuple[str, ...],
    diagnostics: tuple[str, ...],
) -> RetrievalIntent:
    """Map observed trajectory state to the relationship needed next."""

    normalized_operation = str(operation or "").strip().lower()
    normalized_validation = str(validation_state or "").strip().lower()
    if diagnostics or normalized_validation == "fail":
        return RetrievalIntent.DIAGNOSTIC_ROOT_CAUSE
    if normalized_operation == ActionOperation.VALIDATE.value:
        if normalized_validation == "pass":
            return RetrievalIntent.OTHER
        return RetrievalIntent.VALIDATION_CONTEXT
    if changed_paths or normalized_operation in {
        ActionOperation.EDIT.value,
        ActionOperation.CREATE.value,
        ActionOperation.DELETE.value,
    }:
        return RetrievalIntent.CHANGE_IMPACT
    if normalized_operation in {
        ActionOperation.READ.value,
        ActionOperation.SEARCH.value,
    }:
        return RetrievalIntent.MISSING_CONTEXT
    return RetrievalIntent.IMPLEMENTATION_CONTEXT


def _retrieval_opportunity_kind(
    *,
    evidence_action: int,
    operation: str,
    validation_state: str,
    diagnostics: tuple[str, ...],
) -> str:
    """Name the lifecycle decision point without inferring model intent."""

    if evidence_action == 0:
        return "task_start"
    normalized_operation = str(operation or "").strip().lower()
    if diagnostics or str(validation_state or "").strip().lower() == "fail":
        return "post_diagnostic"
    if normalized_operation in {ActionOperation.READ.value, ActionOperation.SEARCH.value}:
        return "post_read_search"
    if normalized_operation in {
        ActionOperation.EDIT.value,
        ActionOperation.CREATE.value,
        ActionOperation.DELETE.value,
    }:
        return "post_mutation"
    if normalized_operation == ActionOperation.VALIDATE.value:
        return "post_validation"
    if normalized_operation == ActionOperation.SUBMIT.value:
        return "post_submit"
    return "post_other"


def _preemptive_opportunity_accounting(
    decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Account every retrieval opportunity without equating delivery with help."""

    by_kind: dict[str, dict[str, Any]] = {}
    for row in decisions:
        kind = str(row.get("opportunity_kind") or "unknown")
        bucket = by_kind.setdefault(
            kind,
            {
                "opportunities": 0,
                "candidate_generated": 0,
                "evidence_selected": 0,
                "delivered": 0,
                "model_visible": 0,
                "abstained": 0,
                "cache_hits": 0,
                "reason_counts": {},
            },
        )
        bucket["opportunities"] += 1
        bucket["candidate_generated"] += int(bool(row.get("ranked_files")))
        bucket["evidence_selected"] += int(bool(row.get("selected_evidence")))
        bucket["delivered"] += int(row.get("status") == "delivered")
        delivery = row.get("delivery_receipt") or {}
        bucket["model_visible"] += int(
            row.get("status") == "delivered"
            and bool(delivery.get("request_payload_sha256"))
            and bool(delivery.get("provider_messages_sha256"))
        )
        bucket["abstained"] += int(row.get("status") == "abstained")
        bucket["cache_hits"] += int(bool(row.get("cache_hit")))
        reasons = bucket["reason_counts"]
        for reason in row.get("reason_codes") or ():
            key = str(reason)
            reasons[key] = int(reasons.get(key, 0)) + 1
    return {
        "schema": "gt.retrieval_opportunity_accounting.v1",
        "opportunities": len(decisions),
        "by_kind": dict(sorted(by_kind.items())),
    }


def _preemptive_opportunity_budget_limit(
    opportunity_kind: str,
    *,
    task_budget_chars: int,
    priority_reserve_chars: int,
) -> int:
    """Reserve late budget for evidence created by execution or validation."""

    total = max(0, int(task_budget_chars))
    reserve = min(total, max(0, int(priority_reserve_chars)))
    if opportunity_kind in {
        "post_mutation",
        "post_diagnostic",
        "post_validation",
    }:
        return total
    return total - reserve


def _preemptive_lifecycle_budget(
    opportunity_kind: str,
    *,
    task_budget_chars: int,
) -> tuple[int, int]:
    """Return cumulative character cap and per-frame evidence count."""

    total = max(0, int(task_budget_chars))
    profiles = {
        "task_start": (800, 1),
        "post_read_search": (2_400, 1),
        "post_mutation": (3_600, 2),
        "post_diagnostic": (5_200, 2),
        "post_validation": (5_200, 2),
    }
    cap, count = profiles.get(str(opportunity_kind or ""), (0, 0))
    return min(total, cap), count if total else 0


def _preemptive_lifecycle_group(opportunity_kind: str) -> str:
    if opportunity_kind in {"post_diagnostic", "post_validation"}:
        return "post_failure_validation"
    return opportunity_kind


def _preemptive_retrieval_gate_reason(
    *,
    enabled: bool,
    integration_active: bool,
    policy_active: bool,
    treatment: bool,
    source_less_task_at_start: bool,
    last_operation: str = "",
    validation_state: str = "unknown",
    diagnostics: tuple[str, ...] = (),
) -> str | None:
    """Return the deterministic reason live repository retrieval must abstain."""

    if not enabled:
        return "preemptive_retrieval_disabled"
    if not integration_active:
        return "integration_mode_not_active"
    if not policy_active:
        return "policy_inactive"
    if not treatment:
        return "not_treatment_runtime"
    if source_less_task_at_start:
        return "not_applicable_no_supported_source"
    if (
        str(last_operation or "").strip().lower() == ActionOperation.VALIDATE.value
        and str(validation_state or "").strip().lower() == "pass"
        and not diagnostics
    ):
        return "validation_pass_no_diagnostic"
    return None


def _retrieval_action_state(
    proposed: ProposedAction,
    *,
    target_paths: tuple[str, ...],
) -> RetrievalActionState:
    """Project the shared shell parser result into bounded retrieval state."""

    selected_operation = next(
        (
            operation
            for operation in proposed.operations
            if operation.executable
            and operation.segment_role is SegmentRole.ACTION
            and operation.operation is proposed.operation
        ),
        None,
    )
    if selected_operation is None:
        selected_operation = next(
            (
                operation
                for operation in proposed.operations
                if operation.executable and operation.segment_role is SegmentRole.ACTION
            ),
            None,
        )
    if selected_operation is None:
        selected_operation = next(
            (operation for operation in proposed.operations if operation.executable),
            None,
        )
    executable = (
        selected_operation.executable
        if selected_operation is not None
        else ""
    )
    return RetrievalActionState(
        operation=proposed.operation.value,
        executable=executable,
        targets=target_paths,
        validation_kind=(
            proposed.validation_kind
            or (executable if proposed.operation is ActionOperation.VALIDATE else None)
        ),
    )


def _provider_visible_claim_ids(
    messages: list[dict[str, Any]],
    candidates: tuple[Any, ...],
) -> tuple[str, ...]:
    """Certify exact candidate text already present in the selecting request.

    Claim ledgers cover GT-originated evidence.  This additional check covers
    normal Mini-SWE observations such as ``sed``/``cat`` output.  Exact text
    containment is deliberately conservative: normalized or fuzzy matches do
    not prove that the model received the same source fact.
    """

    visible_strings: list[str] = []

    def collect(value: Any) -> None:
        if isinstance(value, str):
            visible_strings.append(value)
        elif isinstance(value, dict):
            for nested in value.values():
                collect(nested)
        elif isinstance(value, (list, tuple)):
            for nested in value:
                collect(nested)

    collect(messages)
    return tuple(
        dict.fromkeys(
            str(candidate.claim_hash)
            for candidate in candidates
            if str(getattr(candidate, "text", ""))
            and any(str(candidate.text) in value for value in visible_strings)
        )
    )


def _render_decision_evidence(bundle: DecisionEvidenceBundle) -> tuple[str, ...]:
    """Render complete certified claims without truncating source evidence."""

    return tuple(
        (
            f"[GT certified evidence: {claim.path}:{claim.start_line}-{claim.end_line}"
            + (f"; symbol={claim.symbol}" if claim.symbol else "")
            + (f"; {claim.relation}" if claim.relation else "")
            + "]\n"
            + claim.text
        )
        for claim in bundle.claims
    )


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

    @staticmethod
    def _prepare_preemptive_retrieval_request(
        messages: list[dict[str, Any]],
        *,
        frame: PreemptiveFrame | None,
        legacy_payload: str,
        enabled: bool,
        current_source_revision: str,
        current_call: int,
        budget_chars: int,
        now_ms: float,
        deadline_ms: float | None = None,
        model_query_count: int = 0,
        agent_action_count: int = 0,
    ) -> PreemptiveFrameCompilation:
        """Prepare one additive frame at the host-owned provider boundary.

        Keeping this seam on the central agent proves the transformation is
        part of Mini-SWE's in-process model loop.  The pure compiler performs
        no provider call and executes no action; disabled or invalid inputs
        preserve the supplied provider view exactly.
        """

        return compile_preemptive_frame(
            messages,
            frame=frame,
            legacy_payload=legacy_payload,
            enabled=enabled,
            current_source_revision=current_source_revision,
            current_call=current_call,
            budget_chars=budget_chars,
            now_ms=now_ms,
            deadline_ms=deadline_ms,
            model_query_count=model_query_count,
            agent_action_count=agent_action_count,
        )

    def _snowflake_dense_backend(self) -> SnowflakeOnnxDenseBackend | None:
        """Load the explicitly provisioned local model once, never download it."""

        if self._preemptive_dense_backend is not None:
            return self._preemptive_dense_backend
        if self._preemptive_dense_backend_error or not self.preemptive_retrieval_model_dir:
            return None
        try:
            self._preemptive_dense_backend = SnowflakeOnnxDenseBackend.from_directory(
                self.preemptive_retrieval_model_dir
            )
        except Exception as exc:  # noqa: BLE001 - optional dense channel fails open
            self._preemptive_dense_backend_error = (
                f"{type(exc).__name__}: {exc}"
            )[:500]
            return None
        return self._preemptive_dense_backend

    def __init__(
        self,
        logs_dir: Path,
        model_name: str | None = None,
        *,
        cwd: str | None = None,
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
        repository_initial_index_timeout_sec: float = 60.0,
        repository_refresh_timeout_sec: float = 35.0,
        enable_task_start_advisory: bool = False,
        enable_feature_guidance: bool = True,
        enable_context_frontier: bool = True,
        context_frontier_task_budget_chars: int = 6_000,
        enable_preemptive_retrieval: bool = False,
        preemptive_retrieval_token_budget: int | None = None,
        preemptive_retrieval_task_budget_chars: int | None = None,
        preemptive_retrieval_priority_reserve_chars: int | None = None,
        preemptive_retrieval_timeout_sec: float | None = None,
        preemptive_retrieval_cold_start_timeout_sec: float | None = None,
        preemptive_retrieval_channel_limit: int | None = None,
        preemptive_retrieval_top_k: int | None = None,
        preemptive_retrieval_selection_limit: int | None = None,
        preemptive_retrieval_dense_candidate_limit: int | None = None,
        preemptive_retrieval_model_dir: str | None = None,
        enable_decision_sufficiency: bool = False,
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
        policy_mode: str | GTPolicyMode | None = None,
        preflight_mode: str | PreflightMode = PreflightMode.OFF,
        enable_preflight: bool | None = None,
        preflight_timeout_sec: float = 0.1,
        enable_replay_capture: bool = False,
        replay_capture_max_call_chars: int = 500_000,
        replay_capture_max_bundle_bytes: int = 25_000_000,
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
        inferred_policy_mode = {
            GTIntegrationMode.OFF: GTPolicyMode.OFF,
            GTIntegrationMode.AUDIT: GTPolicyMode.AUDIT,
            GTIntegrationMode.ACTIVE: (
                GTPolicyMode.AUDIT
                if self.runtime_mode == "shadow"
                else GTPolicyMode.CERTIFIED_ACTIVE
            ),
        }[self.integration_mode]
        self.policy_mode = GTPolicyMode.parse(
            policy_mode if policy_mode is not None else inferred_policy_mode
        )
        if self.policy_mode is GTPolicyMode.OFF:
            self.integration_mode = GTIntegrationMode.OFF
        elif self.policy_mode is GTPolicyMode.AUDIT:
            self.integration_mode = GTIntegrationMode.AUDIT
        elif self.integration_mode is GTIntegrationMode.OFF:
            # A second switch cannot reactivate an explicitly disabled host.
            self.policy_mode = GTPolicyMode.OFF
        self.policy_active = self.policy_mode is GTPolicyMode.CERTIFIED_ACTIVE
        if self.integration_mode is GTIntegrationMode.OFF:
            enable_lint = False
            enable_submit_readiness = False
            enable_all_features = False
            enable_repository_intelligence = False
            enable_task_start_advisory = False
            enable_feature_guidance = False
            enable_context_frontier = False
            enable_preemptive_retrieval = False
            enable_decision_sufficiency = False
            enable_context_compaction = False
            enable_completion_controller = False
            enable_progress_control = False
            enable_adaptive_validation_timeout = False
        elif self.integration_mode is GTIntegrationMode.AUDIT:
            enable_task_start_advisory = False
            enable_feature_guidance = False
            enable_preemptive_retrieval = False
            enable_decision_sufficiency = False
            enable_context_compaction = False
            enable_completion_controller = False
            enable_adaptive_validation_timeout = False
        elif self.policy_mode is GTPolicyMode.CERTIFIED_SHADOW:
            enable_lint = False
            enable_task_start_advisory = False
            enable_feature_guidance = False
            enable_preemptive_retrieval = False
            enable_decision_sufficiency = False
            enable_context_compaction = False
            enable_completion_controller = False
            enable_adaptive_validation_timeout = False
        self.enable_lint = enable_lint
        self.enable_submit_readiness = enable_submit_readiness
        self.enable_all_features = enable_all_features
        self.enable_repository_intelligence = enable_repository_intelligence
        self.require_graph_ready = bool(require_graph_ready)
        self.repository_initial_index_timeout_sec = max(
            1.0, float(repository_initial_index_timeout_sec)
        )
        # ``refresh_index_files`` has its own 30-second subprocess budget.
        # A shorter asyncio deadline abandons the await but cannot stop the
        # worker thread, allowing stale and current refreshes to race.
        self.repository_refresh_timeout_sec = max(
            35.0, float(repository_refresh_timeout_sec)
        )
        self.enable_task_start_advisory = enable_task_start_advisory
        self.enable_feature_guidance = bool(enable_feature_guidance)
        self.enable_context_frontier = bool(enable_context_frontier)
        self.context_frontier_task_budget_chars = max(0, int(context_frontier_task_budget_chars))
        self.enable_preemptive_retrieval = bool(enable_preemptive_retrieval)
        self.preemptive_retrieval_token_budget = max(
            0,
            int(
                FINAL_RETRIEVAL_PROFILE.token_budget
                if preemptive_retrieval_token_budget is None
                else preemptive_retrieval_token_budget
            ),
        )
        self.preemptive_retrieval_task_budget_chars = max(
            0,
            int(
                FINAL_RETRIEVAL_PROFILE.task_budget_chars
                if preemptive_retrieval_task_budget_chars is None
                else preemptive_retrieval_task_budget_chars
            ),
        )
        self.preemptive_retrieval_priority_reserve_chars = min(
            self.preemptive_retrieval_task_budget_chars,
            max(
                0,
                int(
                    min(3_000, self.preemptive_retrieval_task_budget_chars // 4)
                    if preemptive_retrieval_priority_reserve_chars is None
                    else preemptive_retrieval_priority_reserve_chars
                ),
            ),
        )
        self.preemptive_retrieval_timeout_sec = max(
            0.01,
            float(
                FINAL_RETRIEVAL_PROFILE.steady_state_timeout_sec
                if preemptive_retrieval_timeout_sec is None
                else preemptive_retrieval_timeout_sec
            ),
        )
        self.preemptive_retrieval_cold_start_timeout_sec = max(
            self.preemptive_retrieval_timeout_sec,
            float(
                FINAL_RETRIEVAL_PROFILE.cold_start_timeout_sec
                if preemptive_retrieval_cold_start_timeout_sec is None
                else preemptive_retrieval_cold_start_timeout_sec
            ),
        )
        self.preemptive_retrieval_channel_limit = max(
            1,
            int(
                FINAL_RETRIEVAL_PROFILE.channel_limit
                if preemptive_retrieval_channel_limit is None
                else preemptive_retrieval_channel_limit
            ),
        )
        self.preemptive_retrieval_top_k = max(
            1,
            int(
                FINAL_RETRIEVAL_PROFILE.top_k
                if preemptive_retrieval_top_k is None
                else preemptive_retrieval_top_k
            ),
        )
        self.preemptive_retrieval_selection_limit = max(
            1,
            int(
                FINAL_RETRIEVAL_PROFILE.selection_limit
                if preemptive_retrieval_selection_limit is None
                else preemptive_retrieval_selection_limit
            ),
        )
        self.preemptive_retrieval_dense_candidate_limit = max(
            1,
            int(
                FINAL_RETRIEVAL_PROFILE.dense_candidate_limit
                if preemptive_retrieval_dense_candidate_limit is None
                else preemptive_retrieval_dense_candidate_limit
            ),
        )
        self.preemptive_retrieval_model_dir = str(
            preemptive_retrieval_model_dir or ""
        ).strip()
        self.enable_decision_sufficiency = bool(enable_decision_sufficiency)
        self._preemptive_dense_backend: SnowflakeOnnxDenseBackend | None = None
        self._preemptive_dense_backend_error = ""
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
        elif not self.policy_active and parsed_preflight_mode is PreflightMode.ASSISTIVE_SAFE:
            parsed_preflight_mode = PreflightMode.SHADOW
        self.preflight_mode = parsed_preflight_mode
        # Compatibility for external receipt consumers; dispatch uses the enum.
        self.enable_preflight = parsed_preflight_mode is not PreflightMode.OFF
        self.preflight_timeout_sec = max(0.001, float(preflight_timeout_sec))
        self.enable_replay_capture = bool(enable_replay_capture)
        self.replay_capture_max_call_chars = max(1_000, int(replay_capture_max_call_chars))
        self.replay_capture_max_bundle_bytes = max(10_000, int(replay_capture_max_bundle_bytes))
        self._ledger = EvidenceLedger(max_holds=max_submit_holds)
        self._checkpoints = ShadowCheckpointLedger()
        self._progress = ProgressLedger(stall_threshold=12, cycle_threshold=24)
        self._sensor = WorkspaceSensor()
        self._features = CentralFeatureRuntime(
            enabled=enable_all_features,
            model_visible=(
                self.runtime_mode == "treatment"
                and self.integration_mode is GTIntegrationMode.ACTIVE
                and self.policy_active
                and self.enable_feature_guidance
            ),
        )
        self._model_factory: Callable[[], Any] = self._build_model
        self._repository_work_receipts: list[dict[str, Any]] = []
        self._cwd_receipt: dict[str, Any] = {}
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
            openrouter = "openrouter.ai" in api_base.lower()
            if openrouter:
                if model == "deepseek-v4-flash":
                    model = "deepseek/deepseek-v4-flash"
                if not model.startswith("openai/"):
                    model = f"openai/{model}"
                provider = (
                    os.environ.get("GT_OPENROUTER_PROVIDER_ONLY") or ""
                ).strip()
                if provider:
                    kwargs["extra_body"] = {
                        "provider": {
                            "only": [provider],
                            "order": [provider],
                            "allow_fallbacks": False,
                            "require_parameters": True,
                        }
                    }
            elif "/" not in model:
                model = f"openai/{model}"
            kwargs["api_base"] = api_base
        return LitellmModel(
            model_name=model,
            model_kwargs=kwargs,
            cost_tracking="ignore_errors",
        )

    async def _system_information(self, environment: BaseEnvironment) -> dict[str, str]:
        configured = str(self.cwd or "").strip()
        # Kernel release/version identify the GitHub runner host rather than
        # the task image, so they can perturb otherwise matched A/B prompts.
        # Preserve Mini-SWE's four template fields with image-owned values.
        command = (
            "uname -s; "
            "if test -r /etc/os-release; then "
            ". /etc/os-release; printf '%s\\n%s\\n' \"${ID:-}\" \"${VERSION_ID:-}\"; "
            "else printf '\\n\\n'; fi; "
            "uname -m; pwd -P"
        )
        if configured:
            configured_q = shlex.quote(configured)
            command += f"; if test -d {configured_q}; then cd -- {configured_q} && pwd -P; fi"
        try:
            result = await self._host_executions.exec(
                environment,
                command,
                category=HostExecCategory.SYSTEM_INFORMATION,
                cwd=None,
                env={},
                timeout_sec=5,
            )
        except Exception:
            result = ExecResult(stdout="Linux\n\n\n\n", return_code=-1)
        values = (result.stdout or "").strip().splitlines()
        if len(values) == 1 and "\t" in values[0]:
            values = values[0].split("\t")
        inherited = values[4].strip() if len(values) >= 5 else ""
        validated_configured = values[5].strip() if configured and len(values) >= 6 else ""
        if validated_configured.startswith("/") and "\x00" not in validated_configured:
            self.cwd = posixpath.normpath(validated_configured)
            status = "configured"
        elif inherited.startswith("/") and "\x00" not in inherited:
            self.cwd = posixpath.normpath(inherited)
            status = "invalid_configured_fallback" if configured else "resolved"
        else:
            # Fail open for transports/test doubles that expose no pwd line;
            # real POSIX task images return it. An explicit cwd remains the
            # compatibility fallback, otherwise the historical /app path is
            # retained and clearly receipted rather than silently assumed.
            self.cwd = configured or "/app"
            status = "configured_fallback" if configured else "legacy_fallback"
        self._cwd_receipt = {
            "status": status,
            "configured": configured,
            "observed": inherited,
            "resolved": self.cwd,
        }
        values += [""] * (4 - len(values))
        return dict(zip(("system", "release", "version", "machine"), values[:4], strict=True))

    async def _resolve_cwd(self, environment: BaseEnvironment) -> str:
        """Resolve the task image's actual working directory before scanning."""

        configured = str(self.cwd or "").strip()
        result = await self._host_executions.exec(
            environment,
            "pwd -P",
            category=HostExecCategory.SYSTEM_INFORMATION,
            cwd=None,
            env={},
            timeout_sec=5,
        )
        lines = (result.stdout or "").strip().splitlines()
        candidate = lines[-1].strip() if result.return_code == 0 and lines else ""
        if not candidate.startswith("/") or "\x00" in candidate:
            raise RuntimeError("TaskWorkingDirectoryUnavailable")
        inherited = posixpath.normpath(candidate)
        resolved = inherited
        status = "resolved"
        if configured:
            configured_q = shlex.quote(configured)
            try:
                configured_probe = await self._host_executions.exec(
                    environment,
                    f"test -d {configured_q} && cd -- {configured_q} && pwd -P",
                    category=HostExecCategory.SYSTEM_INFORMATION,
                    cwd=None,
                    env={},
                    timeout_sec=5,
                )
            except Exception:
                configured_probe = ExecResult(stdout="", return_code=-1)
            configured_lines = (configured_probe.stdout or "").strip().splitlines()
            configured_value = (
                configured_lines[-1].strip()
                if configured_probe.return_code == 0 and configured_lines
                else ""
            )
            if configured_value.startswith("/") and "\x00" not in configured_value:
                resolved = posixpath.normpath(configured_value)
                status = "configured"
            else:
                status = "invalid_configured_fallback"
        if not resolved.startswith("/"):
            raise RuntimeError("TaskWorkingDirectoryInvalid")
        self.cwd = resolved
        self._cwd_receipt = {
            "status": status,
            "configured": configured,
            "observed": inherited,
            "resolved": resolved,
        }
        return resolved

    async def _transfer_source_archive(
        self,
        environment: BaseEnvironment,
        session: RepositorySession,
        mirror_plan: SourceMirrorPlan,
        *,
        source_revision: str,
    ) -> None:
        """Transfer selected source without leaving task-visible controller files."""

        cwd = posixpath.normpath(str(self.cwd or "/"))
        if not cwd.startswith("/"):
            raise RuntimeError("TaskWorkingDirectoryInvalid")
        cwd_prefix = cwd.lstrip("/").rstrip("/")
        archive_members = tuple(
            (
                path[len("__external__/") :]
                if path.startswith("__external__/")
                else posixpath.join(cwd_prefix, path)
                if cwd_prefix
                else path
            )
            for path in mirror_plan.paths
        )
        manifest_bytes = b"".join(
            path.encode("utf-8", "surrogateescape") + b"\0"
            for path in archive_members
        )
        remote_stage = f"/tmp/.gt-mirror.{uuid.uuid4().hex}"
        remote_manifest = f"{remote_stage}/paths.nul"
        remote_archive = f"{remote_stage}/source.tar.gz"
        stage_q = shlex.quote(remote_stage)
        manifest_q = shlex.quote(remote_manifest)
        archive_q = shlex.quote(remote_archive)
        cleanup_status = "not_attempted"
        try:
            init = await self._host_executions.exec(
                environment,
                f"umask 077; mkdir -m 700 -- {stage_q}; : > {manifest_q}",
                category=HostExecCategory.REPOSITORY_TRANSFER,
                source_revision=source_revision,
                cwd=self.cwd,
                env={},
                timeout_sec=5,
            )
            if init.return_code != 0:
                raise RuntimeError("SourceMirrorManifestInitFailed")
            for offset in range(0, len(manifest_bytes), 24_000):
                encoded = base64.b64encode(
                    manifest_bytes[offset : offset + 24_000]
                ).decode("ascii")
                appended = await self._host_executions.exec(
                    environment,
                    f"printf '%s' '{encoded}' | base64 -d >> {manifest_q}",
                    category=HostExecCategory.REPOSITORY_TRANSFER,
                    source_revision=source_revision,
                    cwd=self.cwd,
                    env={},
                    timeout_sec=5,
                )
                if appended.return_code != 0:
                    raise RuntimeError("SourceMirrorManifestWriteFailed")
            transforms = []
            if cwd_prefix:
                # GNU tar transforms use a basic regular expression.  Escape
                # the resolved cwd so repository roots such as /workspace and
                # nested roots such as /app/project are handled literally.
                escaped_prefix = re.escape(cwd_prefix + "/")
                transforms.append(
                    "--transform=" + shlex.quote(f"s,^{escaped_prefix},,")
                )
            transforms.extend(
                (
                    "--transform='s,^etc/,__external__/etc/,'",
                    "--transform='s,^var/,__external__/var/,'",
                )
            )
            archived = await self._host_executions.exec(
                environment,
                (
                    "tar --null --verbatim-files-from "
                    + " ".join(transforms)
                    + " -czf "
                    f"{archive_q} -C / -T {manifest_q}"
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
        finally:
            try:
                cleanup = await self._host_executions.exec(
                    environment,
                    (
                        f"rm -f -- {manifest_q} {archive_q}; "
                        f"rmdir -- {stage_q} 2>/dev/null || true; "
                        f"test ! -e {stage_q}"
                    ),
                    category=HostExecCategory.REPOSITORY_TRANSFER,
                    source_revision=source_revision,
                    cwd=self.cwd,
                    env={},
                    timeout_sec=5,
                )
                cleanup_status = "complete" if cleanup.return_code == 0 else "failed"
            except Exception:
                cleanup_status = "failed"
            self._repository_work_receipts.append(
                {
                    "kind": "mirror_transfer_cleanup",
                    "status": cleanup_status,
                    "remote_stage_sha256": hashlib.sha256(
                        remote_stage.encode("utf-8")
                    ).hexdigest(),
                }
            )
            if cleanup_status != "complete":
                raise RuntimeError("SourceMirrorCleanupFailed")

    async def _hydrate_graph_transition(
        self,
        environment: BaseEnvironment,
        session: RepositorySession,
        transition: Any,
        *,
        snapshot: Any,
        changed_paths: tuple[str, ...],
        source_revision: str,
    ) -> Any:
        """Download changed graph source omitted by bounded inline capture."""

        after_contents = dict(getattr(transition, "after_contents", {}) or {})
        deleted = set(getattr(transition, "deleted", ()) or ())
        missing = tuple(
            path for path in changed_paths if path not in deleted and path not in after_contents
        )
        if not missing:
            return transition
        if not callable(getattr(environment, "download_file", None)):
            self._repository_work_receipts.append(
                {
                    "kind": "incremental_source_transfer",
                    "status": "unavailable",
                    "files": len(missing),
                    "source_revision": source_revision,
                }
            )
            return transition
        transferred = 0
        verified = True
        for path in missing:
            normalized = str(path or "").replace("\\", "/")
            candidate = PurePosixPath(normalized)
            if not normalized or ".." in candidate.parts or "\x00" in normalized:
                verified = False
                break
            state = snapshot.entries.get(path)
            if state is None or state.kind != "f" or state.size > 50_000_000:
                verified = False
                break
            remote_path = (
                normalized
                if normalized.startswith("/")
                else posixpath.join(str(self.cwd or "/"), normalized)
            )
            local_path = session.state_dir / (
                "incremental-"
                + hashlib.sha256(normalized.encode("utf-8", "surrogatepass")).hexdigest()
                + ".source"
            )
            try:
                await asyncio.wait_for(
                    environment.download_file(remote_path, local_path),
                    timeout=20,
                )
                payload = local_path.read_bytes()
                observed_digest = hashlib.sha256(payload).hexdigest()
                if len(payload) != state.size or observed_digest != state.digest:
                    verified = False
                    break
                after_contents[path] = payload.decode("utf-8", "replace")
                transferred += 1
            except Exception:
                verified = False
                break
            finally:
                local_path.unlink(missing_ok=True)
        status = "complete" if verified and transferred == len(missing) else "failed"
        self._repository_work_receipts.append(
            {
                "kind": "incremental_source_transfer",
                "status": status,
                "files": transferred,
                "requested_files": len(missing),
                "digest_verified": status == "complete",
                "source_revision": source_revision,
            }
        )
        return replace(transition, after_contents=after_contents)

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
                await self._transfer_source_archive(
                    environment,
                    session,
                    mirror_plan,
                    source_revision=source_revision,
                )
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
                timeout=self.repository_initial_index_timeout_sec,
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
                    "error_type": str(evidence.index.error_type or "") if evidence.index else "",
                    "error_diagnostic": (
                        str(evidence.index.error_diagnostic or "") if evidence.index else ""
                    ),
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
        source_receipt = source_revision_receipt(snapshot, task_deliverables)
        source_revision = source_receipt.revision
        graph_receipt = graph_revision_receipt(snapshot, task_deliverables)
        graph_source_revision = graph_receipt.revision
        initial_source_paths = graph_receipt.source_paths
        self._features.begin_task(
            instruction,
            revision=snapshot.revision,
            source_revision=source_revision,
            explicit_checks=explicit_checks,
            task_deliverables=task_deliverables,
            initial_source_paths=initial_source_paths,
        )
        repository_fact_tracker = RepositoryFactTracker(
            task_start_source_paths=frozenset(initial_source_paths)
        )
        repository_evidence_action = 0
        repository_evidence_eligible_call = 1
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
        controller_opportunities: list[dict[str, Any]] = []
        project_validation_probes: list[dict[str, Any]] = []
        project_validation_probe_revisions: set[str] = set()
        project_validation_probe_diagnostics: dict[str, str] = {}
        # Do not interrupt ordinary exploration after three actions.  A stall
        # is semantic (no source/validation/diagnostic progress), and only a
        # sustained 12-action witness is strong enough for model-visible state.
        self._progress = ProgressLedger(stall_threshold=12, cycle_threshold=24)
        progress_transitions: list[dict[str, Any]] = []
        pending_progress_fact: StallAggregateFact | None = None
        delivered_progress_fact_ids: set[str] = set()
        progress_fact_deliveries: list[dict[str, Any]] = []
        seen_observation_ids: set[str] = set()
        seen_validation_fingerprints: set[str] = set()
        seen_read_anchors: set[str] = set()
        progress_observations: list[dict[str, Any]] = []
        failed_read_anchors_not_consumed = 0
        valid_nonzero_observations = 0
        semantic_progress_kinds: dict[str, int] = {}
        activity_events = 0
        task_progress_changes = 0
        source_validation_debt = False
        if graph_receipt.complete:
            repository_evidence, repository_session = await self._start_repository_session(
                environment,
                instruction,
                snapshot=snapshot,
                source_revision=graph_source_revision,
                task_deliverables=frozenset(task_deliverables),
            )
        else:
            repository_evidence = RepositoryEvidence(
                status=RepositoryIntelligenceStatus.MIRROR_INCOMPLETE.value
            )
            repository_session = None
            self._repository_work_receipts.append(
                {
                    "kind": "semantic_source_revision",
                    "status": "incomplete",
                    "source_revision": graph_source_revision,
                    "missing_digest_paths": list(graph_receipt.missing_digest_paths),
                    "revision_scope": "graph_input",
                }
            )
        self._features.record_repository_evidence_status(
            source_revision=source_revision,
            status=repository_evidence.status,
            available=repository_evidence.available,
            substrate_ready=repository_evidence.substrate_ready,
            retrieval_disposition=repository_evidence.retrieval_disposition,
        )
        explicit_checks = self._features.register_project_checks(
            (*explicit_checks, *repository_evidence.project_checks)
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
        repository_applicability = classify_repository_applicability(repository_evidence)
        source_less_task = (
            repository_applicability
            == "not_applicable_no_supported_source"
        )
        # Applicability is a property of the task substrate at transfer time,
        # not of arbitrary helper files the model may create later.  Persist it
        # so a source-less binary/data task cannot become a graph failure merely
        # because the trajectory writes an unsupported-language scratch helper.
        source_less_task_at_start = source_less_task
        graph_gate_reasons = (
            graph_gate_failures(repository_evidence)
            if (
                self.require_graph_ready
                and self.integration_mode is GTIntegrationMode.ACTIVE
                and self.runtime_mode == "treatment"
                and self.enable_repository_intelligence
                and not source_less_task
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
        provider_requests_prepared = 0
        model_query_invocations = 0
        provider_query_marker_error = ""
        provider_responses_received = 0
        actions_count = 0
        input_tokens = output_tokens = cache_tokens = 0
        cost = 0.0
        receipts: list[dict[str, Any]] = []
        guidance_deliveries: list[dict[str, Any]] = []
        frontier_decisions: list[dict[str, Any]] = []
        frontier_deliveries: list[dict[str, Any]] = []
        semantic_utilization = SemanticUtilizationTracker(max_calls=5, max_actions=10)
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
        pending_preflight_evidence: dict[str, Any] | None = None
        deadline_reserve_exits = 0
        action_timeout_decisions: list[dict[str, Any]] = []
        declared_validator_proposals = 0
        declared_validators_with_redirection = 0
        declared_validators_preserved_with_redirection = 0
        model_action_timeouts = 0
        previous_provider_messages: list[dict[str, Any]] | None = None
        provider_view_session = ProviderViewSession()
        replay_bundle = ReplayBundleWriter(
            self.logs_dir / "gt_replay",
            enabled=self.enable_replay_capture,
            max_call_chars=self.replay_capture_max_call_chars,
            max_bundle_bytes=self.replay_capture_max_bundle_bytes,
        )
        provider_evidence = ProviderEvidenceLedger()
        contribution_compilations: list[dict[str, Any]] = []
        preemptive_retrieval_decisions: list[dict[str, Any]] = []
        preemptive_retrieval_deliveries: list[dict[str, Any]] = []
        decision_sufficiency_receipts: list[dict[str, Any]] = []
        delivered_preemptive_claim_ids: set[str] = set()
        preemptive_retrieval_chars_delivered = 0
        preemptive_retrieval_chars_by_lifecycle: dict[str, int] = {}
        preemptive_retrieval_cache: dict[str, Any] = {}
        preemptive_retrieval_cache_limit = 128
        preemptive_repository: HybridRepository | None = None
        preemptive_repository_revision = ""
        preemptive_retriever: HybridRetriever | None = None
        retrieval_last_action: RetrievalActionState | None = None
        retrieval_last_operation = ""
        retrieval_active_paths: tuple[str, ...] = ()
        retrieval_active_symbols: tuple[str, ...] = ()
        retrieval_changed_paths: tuple[str, ...] = ()
        retrieval_diagnostics: tuple[str, ...] = ()
        retrieval_validation_state = "unknown"
        retrieval_evidence_action = 0
        retrieval_eligible_call = 1

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
                        iteration_risk_ratio=0.6,
                        unresolved=not bool(
                            completion_certificates
                            and completion_certificates[-1].auto_submit_eligible
                        ),
                        remaining_seconds=remaining_to_deadline,
                        time_risk_threshold_seconds=(
                            None
                            if effective_budget is None
                            else max(
                                self.deadline_reserve_sec * 2.0,
                                effective_budget * 0.10,
                            )
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
                    if (
                        pending_progress_fact is None
                        and len(delivered_progress_fact_ids) < 2
                    ):
                        pending_progress_fact = StallAggregateFact.create(
                            state=budget_transition.current,
                            repeated_operation="budget",
                            concrete_targets=(),
                            repeat_count=max(1, budget_transition.streak),
                            last_returncode=None,
                            timeout_observed=False,
                            source_revision=source_revision,
                            remaining_calls=max(0, self.step_limit - calls),
                            remaining_seconds=(
                                None
                                if deadline is None
                                else deadline - time.monotonic()
                            ),
                            unresolved_anchors=tuple(
                                list(explicit_checks)[:2]
                                or sorted(task_deliverables)[:2]
                            ),
                            evidence_action=actions_count,
                            eligible_call=calls + 1,
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
                (
                    stock_provider_messages,
                    _stock_request_payload_sha256,
                    stock_provider_messages_sha256,
                    stock_provider_request_chars,
                ) = _provider_request_receipt(model, messages)
                compaction_epoch_started = False
                if self.enable_context_compaction:
                    raw_context_chars = sum(
                        _message_context_chars(message) for message in messages
                    )
                    if (
                        not provider_view_session.checkpoint_messages
                        and raw_context_chars >= self.context_trigger_chars
                    ):
                        _candidate_view, candidate_metrics = build_provider_view(
                            messages,
                            active_state=active_state,
                            trigger_chars=self.context_trigger_chars,
                            target_chars=self.context_target_chars,
                            keep_recent_turns=2,
                            transform=True,
                        )
                        savings = max(0, candidate_metrics.elided_chars)
                        savings_ratio = savings / max(1, raw_context_chars)
                        if (
                            savings >= self.context_min_compaction_savings_chars
                            and savings_ratio
                            >= self.context_min_compaction_savings_ratio
                            and candidate_metrics.unique_assistant_reasoning_chars_removed == 0
                        ):
                            query_messages, provider_view_metrics = (
                                provider_view_session.compact(
                                    messages,
                                    active_state=active_state,
                                    target_chars=self.context_target_chars,
                                    keep_recent_turns=2,
                                    trigger_tokens=0,
                                    trigger_kind="character_pressure",
                                    trigger_chars=raw_context_chars,
                                )
                            )
                            context_compactions += 1
                            context_chars_elided += provider_view_metrics.elided_chars
                            compaction_epoch_started = True
                        else:
                            query_messages, provider_view_metrics = (
                                provider_view_session.project(
                                    messages,
                                    active_state=active_state,
                                )
                            )
                            context_compaction_deferrals.append(
                                {
                                    "call": calls,
                                    "trigger_kind": "character_pressure",
                                    "raw_chars": raw_context_chars,
                                    "projected_savings_chars": savings,
                                    "projected_savings_ratio": savings_ratio,
                                    "reason": "minimum_safe_savings_not_met",
                                }
                            )
                    else:
                        query_messages, provider_view_metrics = (
                            provider_view_session.project(
                                messages,
                                active_state=active_state,
                            )
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
                # Preserve the exact provider-view control before any GT text is
                # attached. Replay capture is opt-in, but when enabled this is
                # the only defensible paired decision-point control.
                control_query_messages = [dict(item) for item in query_messages]
                runtime_enrichment_chars = 0
                runtime_message_index: int | None = None
                delivery_metadata: dict[str, Any] | None = None
                preemptive_frame: PreemptiveFrame | None = None
                preemptive_compilation: PreemptiveFrameCompilation | None = None
                retrieval_opportunity_kind = _retrieval_opportunity_kind(
                    evidence_action=retrieval_evidence_action,
                    operation=retrieval_last_operation,
                    validation_state=retrieval_validation_state,
                    diagnostics=retrieval_diagnostics,
                )
                opportunity_budget_limit = _preemptive_opportunity_budget_limit(
                    retrieval_opportunity_kind,
                    task_budget_chars=self.preemptive_retrieval_task_budget_chars,
                    priority_reserve_chars=(
                        self.preemptive_retrieval_priority_reserve_chars
                    ),
                )
                lifecycle_budget_limit, lifecycle_selection_limit = (
                    _preemptive_lifecycle_budget(
                        retrieval_opportunity_kind,
                        task_budget_chars=self.preemptive_retrieval_task_budget_chars,
                    )
                )
                lifecycle_group = _preemptive_lifecycle_group(
                    retrieval_opportunity_kind
                )
                lifecycle_chars_delivered = preemptive_retrieval_chars_by_lifecycle.get(
                    lifecycle_group, 0
                )
                lifecycle_remaining_chars = max(
                    0, lifecycle_budget_limit - lifecycle_chars_delivered
                )
                preemptive_decision: dict[str, Any] = {
                    "call": calls,
                    "evidence_action": retrieval_evidence_action,
                    "eligible_call": retrieval_eligible_call,
                    "source_revision": graph_source_revision,
                    "enabled": self.enable_preemptive_retrieval,
                    "status": "disabled",
                    "reason_codes": ["preemptive_retrieval_disabled"],
                    "intent": RetrievalIntent.OTHER.value,
                    "ranked_files": [],
                    "selected_evidence": [],
                    "channel_receipts": [],
                    "latency_ms": 0.0,
                    "opportunity_kind": retrieval_opportunity_kind,
                    "opportunity_budget_limit_chars": opportunity_budget_limit,
                    "lifecycle_budget_limit_chars": lifecycle_budget_limit,
                    "lifecycle_budget_remaining_chars": lifecycle_remaining_chars,
                    "lifecycle_selection_limit": lifecycle_selection_limit,
                    "cache_hit": False,
                }
                preemptive_gate_reason = _preemptive_retrieval_gate_reason(
                    enabled=self.enable_preemptive_retrieval,
                    integration_active=(
                        self.integration_mode is GTIntegrationMode.ACTIVE
                    ),
                    policy_active=self.policy_active,
                    treatment=self.runtime_mode == "treatment",
                    source_less_task_at_start=source_less_task_at_start,
                    last_operation=retrieval_last_operation,
                    validation_state=retrieval_validation_state,
                    diagnostics=retrieval_diagnostics,
                )
                if (
                    preemptive_gate_reason is None
                    and self.preemptive_retrieval_task_budget_chars < 1
                ):
                    preemptive_gate_reason = "task_character_budget_closed_precheck"
                if (
                    preemptive_gate_reason is None
                    and lifecycle_selection_limit < 1
                ):
                    preemptive_gate_reason = "lifecycle_not_material"
                if (
                    preemptive_gate_reason is None
                    and lifecycle_remaining_chars < 1
                ):
                    preemptive_gate_reason = "lifecycle_budget_closed_precheck"
                if (
                    preemptive_gate_reason is None
                    and preemptive_retrieval_chars_delivered
                    >= opportunity_budget_limit
                ):
                    preemptive_gate_reason = (
                        "task_character_budget_closed_precheck"
                        if opportunity_budget_limit
                        == self.preemptive_retrieval_task_budget_chars
                        else "opportunity_budget_reserved_precheck"
                    )
                if preemptive_gate_reason is not None:
                    preemptive_decision["reason_codes"] = [preemptive_gate_reason]
                    if preemptive_gate_reason in {
                        "not_applicable_no_supported_source",
                        "validation_pass_no_diagnostic",
                        "task_character_budget_closed_precheck",
                        "opportunity_budget_reserved_precheck",
                        "lifecycle_not_material",
                        "lifecycle_budget_closed_precheck",
                    }:
                        preemptive_decision["status"] = "abstained"
                if preemptive_gate_reason is None:
                    retrieval_started = time.perf_counter()
                    retrieval_cold_start = (
                        preemptive_repository is None
                        or preemptive_repository_revision != graph_source_revision
                        or preemptive_retriever is None
                    )
                    retrieval_timeout_sec = (
                        self.preemptive_retrieval_cold_start_timeout_sec
                        if retrieval_cold_start
                        else self.preemptive_retrieval_timeout_sec
                    )
                    preemptive_decision["timeout_sec"] = retrieval_timeout_sec
                    preemptive_decision["cold_start"] = retrieval_cold_start
                    preemptive_decision["status"] = "abstained"
                    preemptive_decision["reason_codes"] = []
                    if (
                        repository_session is None
                        or repository_evidence.index is None
                        or not repository_evidence.index.graph_db
                        or not repository_evidence.substrate_ready
                        or repository_session.indexed_source_revision
                        != graph_source_revision
                    ):
                        preemptive_decision["reason_codes"] = [
                            "repository_substrate_unavailable"
                        ]
                    else:
                        try:
                            if (
                                preemptive_repository is None
                                or preemptive_repository_revision != graph_source_revision
                            ):
                                preemptive_repository = await asyncio.wait_for(
                                    asyncio.to_thread(
                                        build_hybrid_repository,
                                        repository_session.root,
                                        repository_evidence.index.graph_db,
                                        source_revision=graph_source_revision,
                                    ),
                                    timeout=retrieval_timeout_sec,
                                )
                                preemptive_repository_revision = graph_source_revision
                                preemptive_retriever = None
                            if not preemptive_repository.complete:
                                preemptive_decision["reason_codes"] = list(
                                    preemptive_repository.reason_codes
                                    or ("repository_corpus_incomplete",)
                                )
                            else:
                                intent = _retrieval_intent(
                                    operation=retrieval_last_operation,
                                    validation_state=retrieval_validation_state,
                                    changed_paths=retrieval_changed_paths,
                                    diagnostics=retrieval_diagnostics,
                                )
                                preemptive_decision["intent"] = intent.value
                                state = RetrievalState(
                                    task_text=instruction,
                                    intent=intent,
                                    action=retrieval_last_action,
                                    active_paths=retrieval_active_paths,
                                    active_symbols=retrieval_active_symbols,
                                    changed_paths=retrieval_changed_paths,
                                    diagnostics=retrieval_diagnostics,
                                    validation_state=retrieval_validation_state,
                                    source_revision=graph_source_revision,
                                    previously_exposed_claims=tuple(
                                        sorted(delivered_preemptive_claim_ids)
                                    ),
                                )
                                preemptive_decision["action_state"] = (
                                    {
                                        "operation": retrieval_last_action.operation,
                                        "executable": retrieval_last_action.executable,
                                        "targets": list(retrieval_last_action.targets),
                                        "validation_kind": (
                                            retrieval_last_action.validation_kind
                                        ),
                                        "semantic_tokens": list(
                                            retrieval_last_action.semantic_tokens
                                        ),
                                    }
                                    if retrieval_last_action is not None
                                    else None
                                )
                                if preemptive_retriever is None:
                                    preemptive_retriever = HybridRetriever(
                                        preemptive_repository.documents,
                                        structural_links=(
                                            preemptive_repository.structural_links
                                        ),
                                        dense_backend=self._snowflake_dense_backend(),
                                        dense_candidate_limit=(
                                            self.preemptive_retrieval_dense_candidate_limit
                                        ),
                                    )
                                remaining_chars = min(
                                    lifecycle_remaining_chars,
                                    max(
                                        0,
                                        opportunity_budget_limit
                                        - preemptive_retrieval_chars_delivered,
                                    ),
                                )
                                retrieval_cache_key = hashlib.sha256(
                                    _canonical_json(
                                        {
                                            "query_hash": state.query_hash,
                                            "visible_claims": sorted(
                                                delivered_preemptive_claim_ids
                                            ),
                                            "channel_limit": (
                                                self.preemptive_retrieval_channel_limit
                                            ),
                                            "top_k": self.preemptive_retrieval_top_k,
                                            "selection_limit": (
                                                min(
                                                    self.preemptive_retrieval_selection_limit,
                                                    lifecycle_selection_limit,
                                                )
                                            ),
                                            "token_budget": (
                                                self.preemptive_retrieval_token_budget
                                            ),
                                            "remaining_chars": remaining_chars,
                                        }
                                    )
                                ).hexdigest()
                                cached_result = preemptive_retrieval_cache.get(
                                    retrieval_cache_key
                                )
                                if cached_result is not None:
                                    retrieval_result = replace(
                                        cached_result,
                                        latency_ms=0.0,
                                        channel_receipts=tuple(
                                            replace(
                                                receipt,
                                                latency_ms=0.0,
                                                reason=(
                                                    "cache_replay"
                                                    + (
                                                        f":{receipt.reason}"
                                                        if receipt.reason
                                                        else ""
                                                    )
                                                ),
                                            )
                                            for receipt in cached_result.channel_receipts
                                        ),
                                    )
                                    preemptive_decision["cache_hit"] = True
                                else:
                                    retrieval_result = await asyncio.wait_for(
                                        asyncio.to_thread(
                                            preemptive_retriever.retrieve,
                                            state,
                                            channel_limit=(
                                                self.preemptive_retrieval_channel_limit
                                            ),
                                            top_k=self.preemptive_retrieval_top_k,
                                            selection_limit=min(
                                                self.preemptive_retrieval_selection_limit,
                                                lifecycle_selection_limit,
                                            ),
                                            token_budget=(
                                                self.preemptive_retrieval_token_budget
                                            ),
                                            character_budget=remaining_chars,
                                        ),
                                        timeout=retrieval_timeout_sec,
                                    )
                                    if (
                                        len(preemptive_retrieval_cache)
                                        >= preemptive_retrieval_cache_limit
                                    ):
                                        preemptive_retrieval_cache.pop(
                                            next(iter(preemptive_retrieval_cache))
                                        )
                                    preemptive_retrieval_cache[retrieval_cache_key] = (
                                        retrieval_result
                                    )
                                preemptive_decision["cache_key"] = retrieval_cache_key
                                preemptive_decision.update(
                                    {
                                        "status": (
                                            "abstained"
                                            if retrieval_result.abstained
                                            else "selected"
                                        ),
                                        "query_hash": retrieval_result.query_hash,
                                        "reason_codes": list(
                                            retrieval_result.reason_codes
                                        ),
                                        "ranked_files": [
                                            {
                                                "path": row.path,
                                                "fused_score": row.fused_score,
                                                "channel_ranks": [
                                                    {
                                                        "channel": channel.value,
                                                        "rank": rank,
                                                    }
                                                    for channel, rank in row.channel_ranks
                                                ],
                                                "provenance": list(row.provenance),
                                            }
                                            for row in retrieval_result.ranked_files
                                        ],
                                        "selected_evidence": [
                                            {
                                                "path": row.path,
                                                "start_line": row.start_line,
                                                "end_line": row.end_line,
                                                "symbol": row.symbol,
                                                "relation": row.relation,
                                                 "claim_hash": row.claim_hash,
                                                 "provenance": list(row.provenance),
                                                 "support_kind": next(
                                                     (
                                                         item.split(":", 1)[1]
                                                         for item in row.provenance
                                                         if item.startswith(
                                                             "delivery_support:"
                                                         )
                                                     ),
                                                     "",
                                                 ),
                                                 "supporting_channels": [
                                                     item.split(":", 1)[1]
                                                     for item in row.provenance
                                                     if item.startswith(
                                                         "support_channel:"
                                                     )
                                                 ],
                                             }
                                            for row in retrieval_result.selected_context
                                        ],
                                        "selected_token_count": (
                                            retrieval_result.selected_token_count
                                        ),
                                        "selected_character_count": (
                                            retrieval_result.selected_character_count
                                        ),
                                        "remaining_budget_chars": remaining_chars,
                                        "channel_receipts": [
                                            {
                                                "channel": row.channel.value,
                                                "candidate_count": row.candidate_count,
                                                "failed": row.failed,
                                                "reason": row.reason,
                                                "latency_ms": row.latency_ms,
                                                "available": row.available,
                                                "backend_identity": (
                                                    row.backend_identity
                                                ),
                                            }
                                            for row in retrieval_result.channel_receipts
                                        ],
                                    }
                                )
                                frame = build_preemptive_frame(
                                    retrieval_result,
                                    state,
                                    trigger=(
                                        "task_start"
                                        if retrieval_evidence_action == 0
                                        else f"post_{retrieval_last_operation or 'action'}"
                                    ),
                                )
                                remaining_chars = min(
                                    lifecycle_remaining_chars,
                                    max(
                                        0,
                                        opportunity_budget_limit
                                        - preemptive_retrieval_chars_delivered,
                                    ),
                                )
                                if (
                                    frame is not None
                                    and len(frame.rendered_text) <= remaining_chars
                                ):
                                    # ``query_hash`` identifies the retrieval
                                    # state, not this particular delivery. A
                                    # repeated state can legitimately produce
                                    # a different claim set after the graph or
                                    # workspace changes. Include the selected
                                    # claims and eligible call so each provider
                                    # frame has a stable, unique receipt ID.
                                    frame_identity = _preemptive_frame_identity(
                                        frame.query_hash,
                                        tuple(frame.claim_hashes),
                                        retrieval_eligible_call,
                                        frame.source_revision,
                                    )
                                    preemptive_frame = PreemptiveFrame(
                                        frame_id="preemptive-" + frame_identity,
                                        text=frame.rendered_text,
                                        source_revision=frame.source_revision,
                                        eligible_call=retrieval_eligible_call,
                                        evidence_action=retrieval_evidence_action,
                                        evidence_ids=frame.claim_hashes,
                                        claim_ids=frame.claim_hashes,
                                    )
                                elif frame is not None:
                                    preemptive_decision["status"] = "abstained"
                                    preemptive_decision["reason_codes"] = [
                                        *preemptive_decision["reason_codes"],
                                        "task_character_budget",
                                    ]
                        except TimeoutError:
                            preemptive_decision["reason_codes"] = [
                                "preemptive_retrieval_timeout"
                            ]
                        except Exception as exc:  # noqa: BLE001 - fail open
                            preemptive_decision["reason_codes"] = [
                                f"preemptive_retrieval_error:{type(exc).__name__}"
                            ]
                    preemptive_decision["latency_ms"] = round(
                        (time.perf_counter() - retrieval_started) * 1_000.0,
                        6,
                    )
                frontier_decision = compile_incremental_frontier(
                    repository_evidence,
                    query_messages,
                    source_revision=source_revision,
                    workspace_revision=snapshot.revision,
                    current_call=calls,
                    eligible_call=repository_evidence_eligible_call,
                    evidence_action=repository_evidence_action,
                    fact_tracker=repository_fact_tracker,
                    delivered_fact_ids=frozenset(delivered_frontier_fact_ids),
                    delivered_claim_ids=frozenset(delivered_frontier_claim_ids),
                    max_chars=min(
                        600,
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
                        and self.policy_active
                        and self.runtime_mode == "treatment"
                        and frontier_decision.disposition is FrontierDisposition.SELECTED_FRONTIER
                    )
                    else ""
                )
                guidance_payload = pending_guidance
                prepared_guidance_metadata = self._features.prepared_guidance() or {}
                progress_payload = (
                    pending_progress_fact.render()
                    if pending_progress_fact is not None
                    and pending_progress_fact.eligible_call == calls
                    and pending_progress_fact.fact_id not in delivered_progress_fact_ids
                    else ""
                )
                prepared_progress_fact = (
                    pending_progress_fact if progress_payload else None
                )
                contribution_candidates: list[GTContribution] = []
                contribution_by_surface: dict[str, str] = {}

                def register_contribution(
                    *,
                    surface: str,
                    payload: str,
                    claim_ids: tuple[str, ...],
                    fact_ids: tuple[str, ...],
                    evidence_action: int,
                    eligible_call: int,
                    revision: str,
                    priority: int,
                    _candidates: list[GTContribution] = contribution_candidates,
                    _by_surface: dict[str, str] = contribution_by_surface,
                ) -> None:
                    if not payload:
                        return
                    kind = (
                        ContributionKind.EVIDENCE
                        if claim_ids or fact_ids
                        else ContributionKind.CONTROLLER_STATE
                    )
                    contribution = GTContribution.create(
                        surface=surface,
                        kind=kind,
                        payload=payload,
                        claim_ids=claim_ids,
                        fact_ids=fact_ids,
                        evidence_action=evidence_action,
                        eligible_call=eligible_call,
                        source_revision=revision,
                        priority=priority,
                    )
                    _candidates.append(contribution)
                    _by_surface[surface] = contribution.contribution_id

                if preemptive_frame is not None:
                    register_contribution(
                        surface="preemptive_retrieval",
                        payload=preemptive_frame.text,
                        claim_ids=preemptive_frame.claim_ids,
                        fact_ids=preemptive_frame.evidence_ids,
                        evidence_action=preemptive_frame.evidence_action,
                        eligible_call=preemptive_frame.eligible_call,
                        revision=preemptive_frame.source_revision,
                        priority=10,
                    )
                frontier_fact_ids = tuple(
                    str(row.get("fact_id") or "")
                    for row in frontier_decision.accounting
                    if row.get("fact_id")
                )
                frontier_claim_ids = tuple(
                    str(row.get("claim_id") or "")
                    for row in frontier_decision.accounting
                    if row.get("claim_id")
                )
                register_contribution(
                    surface="graph_frontier",
                    payload=frontier_payload,
                    claim_ids=frontier_claim_ids,
                    fact_ids=frontier_fact_ids,
                    evidence_action=repository_evidence_action,
                    eligible_call=repository_evidence_eligible_call,
                    revision=source_revision,
                    priority=20,
                )
                register_contribution(
                    surface="feature_fact",
                    payload=guidance_payload,
                    claim_ids=tuple(
                        str(item)
                        for item in prepared_guidance_metadata.get("claim_ids") or ()
                        if str(item)
                    ),
                    fact_ids=tuple(
                        str(item)
                        for item in prepared_guidance_metadata.get("effect_ids") or ()
                        if str(item)
                    ),
                    evidence_action=int(
                        prepared_guidance_metadata.get("evidence_action") or 0
                    ),
                    eligible_call=max(1, pending_prepared_after_call + 1),
                    revision=source_revision,
                    priority=30,
                )
                register_contribution(
                    surface="progress_frame",
                    payload=progress_payload,
                    claim_ids=(
                        (prepared_progress_fact.fact_id,)
                        if prepared_progress_fact is not None
                        else ()
                    ),
                    fact_ids=(),
                    evidence_action=(
                        prepared_progress_fact.evidence_action
                        if prepared_progress_fact is not None
                        else actions_count
                    ),
                    eligible_call=(
                        prepared_progress_fact.eligible_call
                        if prepared_progress_fact is not None
                        else calls
                    ),
                    revision=source_revision,
                    priority=40,
                )
                contribution_budget = (
                    min(
                        lifecycle_remaining_chars,
                        max(
                            0,
                            opportunity_budget_limit
                            - preemptive_retrieval_chars_delivered,
                        ),
                    )
                    + len(frontier_payload)
                    + len(guidance_payload)
                    + len(progress_payload)
                    + 6
                )
                compiled_contributions = compile_contributions(
                    tuple(contribution_candidates),
                    # Raw workspace/source revision and graph source revision
                    # are separate certified domains.  Retrieval frames are
                    # bound to the latter; feature/controller evidence is
                    # commonly bound to the former.  Validate against both,
                    # while still rejecting every unrelated/stale revision.
                    current_source_revision=(source_revision, graph_source_revision),
                    current_call=calls,
                    budget_chars=contribution_budget,
                )
                selected_contribution_ids = set(compiled_contributions.selected_ids)

                def contribution_selected(
                    surface: str,
                    _by_surface: dict[str, str] = contribution_by_surface,
                    _selected: set[str] = selected_contribution_ids,
                ) -> bool:
                    contribution_id = _by_surface.get(surface)
                    return bool(
                        contribution_id and contribution_id in _selected
                    )

                if preemptive_frame is not None and not contribution_selected(
                    "preemptive_retrieval"
                ):
                    preemptive_frame = None
                if frontier_payload and not contribution_selected("graph_frontier"):
                    frontier_payload = ""
                if guidance_payload and not contribution_selected("feature_fact"):
                    guidance_payload = ""
                if progress_payload and not contribution_selected("progress_frame"):
                    progress_payload = ""
                    prepared_progress_fact = None
                contribution_receipt = compiled_contributions.as_dict()
                contribution_receipt.update(
                    {
                        "call": calls,
                        "source_revision": source_revision,
                        "selected_surfaces": [
                            surface
                            for surface, contribution_id in contribution_by_surface.items()
                            if contribution_id in selected_contribution_ids
                        ],
                    }
                )
                contribution_compilations.append(contribution_receipt)
                legacy_runtime_parts = [
                    item
                    for item in (frontier_payload, guidance_payload, progress_payload)
                    if item
                ]
                legacy_runtime_payload = "\n\n".join(legacy_runtime_parts)
                preemptive_payload = ""
                runtime_payload = legacy_runtime_payload
                frontier_decisions.append(
                    {
                        "call": calls,
                        "source_revision": source_revision,
                        "integration_mode": self.integration_mode.value,
                        "policy_mode": self.policy_mode.value,
                        "delivery_enabled": bool(frontier_payload),
                        **frontier_decision.as_dict(),
                    }
                )
                if preemptive_frame is not None:
                    preemptive_input_chars = sum(
                        len(str(item.get("content") or "")) for item in query_messages
                    )
                    preemptive_compilation = self._prepare_preemptive_retrieval_request(
                        query_messages,
                        frame=preemptive_frame,
                        legacy_payload=legacy_runtime_payload,
                        enabled=True,
                        current_source_revision=graph_source_revision,
                        current_call=calls,
                        budget_chars=(
                            min(
                                lifecycle_remaining_chars,
                                max(
                                    0,
                                    opportunity_budget_limit
                                    - preemptive_retrieval_chars_delivered,
                                ),
                            )
                            + len(legacy_runtime_payload)
                        ),
                        now_ms=time.monotonic() * 1_000.0,
                        model_query_count=model_query_invocations,
                        agent_action_count=actions_count,
                    )
                    if preemptive_compilation.status is PreemptiveFrameStatus.DELIVERED:
                        query_messages = [
                            dict(item) for item in preemptive_compilation.provider_messages
                        ]
                        indices = preemptive_compilation.receipt.get(
                            "provider_message_indices"
                        ) or []
                        runtime_message_index = int(indices[0]) if indices else None
                        preemptive_payload = preemptive_frame.text.strip()
                        runtime_payload = "\n\n".join(
                            item
                            for item in (
                                preemptive_payload,
                                legacy_runtime_payload,
                            )
                            if item
                        )
                        runtime_enrichment_chars = max(
                            0,
                            sum(
                                len(str(item.get("content") or ""))
                                for item in query_messages
                            )
                            - preemptive_input_chars,
                        )
                        preemptive_decision["status"] = "prepared"
                        preemptive_decision["delivery_receipt"] = dict(
                            preemptive_compilation.receipt
                        )
                    else:
                        preemptive_decision["status"] = "abstained"
                        preemptive_decision["reason_codes"] = [
                            *preemptive_decision.get("reason_codes", []),
                            str(
                                preemptive_compilation.receipt.get("reason_code")
                                or "preemptive_frame_abstained"
                            ),
                        ]
                if runtime_message_index is None and legacy_runtime_payload:
                    (
                        query_messages,
                        runtime_message_index,
                        runtime_enrichment_chars,
                    ) = _inject_runtime_evidence(query_messages, legacy_runtime_payload)
                preemptive_retrieval_decisions.append(preemptive_decision)
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
                        target_chars=provider_compaction_target_chars(
                            current_view_chars=provider_view_metrics.output_chars,
                            budget=request_budget,
                            target_ratio=0.70,
                        ),
                        keep_recent_turns=2,
                        trigger_tokens=request_budget.effective_tokens,
                        trigger_kind="provider_budget",
                        trigger_chars=provider_view_metrics.output_chars,
                    )
                    control_query_messages = [dict(item) for item in query_messages]
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
                remaining_for_query = (
                    None
                    if deadline is None
                    else max(0.0, deadline - time.monotonic() - self.deadline_reserve_sec)
                )
                planned_query_timeout = (
                    self.model_timeout_sec
                    if remaining_for_query is None
                    else (
                        remaining_for_query
                        if self.model_timeout_sec is None
                        else min(float(self.model_timeout_sec), remaining_for_query)
                    )
                )
                request_dispatch_eligible = bool(
                    request_budget.within_limit
                    and (
                        planned_query_timeout is None
                        or planned_query_timeout > 0
                    )
                )
                (
                    control_provider_messages,
                    control_request_payload_sha256,
                    control_provider_messages_sha256,
                    control_provider_request_chars,
                ) = _provider_request_receipt(model, control_query_messages)
                intervention_capture: dict[str, Any] | None = None
                if runtime_payload:
                    intervention_capture = {
                        "payload": runtime_payload,
                        "message_index": runtime_message_index,
                        "prior_visible_gt_count": sum(
                            1
                            for row in model_call_contexts
                            if row.get("runtime_message_index") is not None
                            and row.get("dispatch_status")
                            in {"invoked", "response_received"}
                        ),
                        "selected_contribution_ids": list(
                            compiled_contributions.selected_ids
                        ),
                        "selected_surfaces": list(
                            contribution_receipt.get("selected_surfaces") or []
                        ),
                        "source_revision": source_revision,
                        "eligible_call": calls,
                        "evidence_action": max(
                            (
                                int(item.evidence_action)
                                for item in contribution_candidates
                                if item.contribution_id
                                in selected_contribution_ids
                            ),
                            default=actions_count,
                        ),
                    }
                replay_bundle.record_request(
                    call=calls,
                    provider_messages=provider_messages,
                    control_provider_messages=control_provider_messages,
                    intervention=intervention_capture,
                    provider_tools=getattr(model, "tools", None) or [BASH_TOOL],
                    request_payload_sha256=request_payload_sha256,
                    provider_messages_sha256=provider_messages_sha256,
                    model_name=str(self.model_name or ""),
                    model_kwargs=_model_kwargs(model),
                    temperature=self.temperature,
                    active_state=active_state,
                    source_revision=source_revision,
                    workspace_revision=snapshot.revision,
                )
                provider_requests_prepared += 1
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
                    request_dispatch_eligible
                    and runtime_message_index is not None
                    and preemptive_payload
                    and preemptive_frame is not None
                ):
                    delivered_preemptive_claim_ids.update(preemptive_frame.claim_ids)
                    preemptive_retrieval_chars_delivered += len(preemptive_payload)
                    preemptive_retrieval_chars_by_lifecycle[lifecycle_group] = (
                        preemptive_retrieval_chars_by_lifecycle.get(lifecycle_group, 0)
                        + len(preemptive_payload)
                    )
                    delivery_receipt = dict(
                        preemptive_compilation.receipt
                        if preemptive_compilation
                        else {}
                    )
                    delivery_receipt.update(
                        {
                            "status": "delivered",
                            "prepared_call": calls,
                            "delivered_before_call": calls,
                            "provider_message_indices": [runtime_message_index],
                            "request_payload_sha256": request_payload_sha256,
                            "provider_messages_sha256": provider_messages_sha256,
                            "first_eligible_request": (
                                calls == preemptive_frame.eligible_call
                            ),
                            "one_step_late": calls != preemptive_frame.eligible_call,
                            "predictive": (
                                preemptive_frame.evidence_action > actions_count
                            ),
                            "chars": len(preemptive_payload),
                            "selected_evidence": list(
                                preemptive_decision.get("selected_evidence") or []
                            ),
                        }
                    )
                    preemptive_retrieval_deliveries.append(delivery_receipt)
                    preemptive_retrieval_decisions[-1]["status"] = "delivered"
                    preemptive_retrieval_decisions[-1]["delivery_receipt"] = (
                        delivery_receipt
                    )
                if (
                    request_dispatch_eligible
                    and runtime_message_index is not None
                    and pending_guidance
                ):
                    delivery_metadata = self._features.confirm_prepared_guidance() or {}
                    pending_guidance = ""
                if (
                    request_dispatch_eligible
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
                            "first_eligible_call": repository_evidence_eligible_call,
                            "delivered_before_call": calls,
                            "delivered_before_model_query": True,
                            "not_predictive": True,
                            "one_step_late": False,
                            "chars": len(frontier_payload),
                            "certified_opportunity": (
                                frontier_decision.opportunity.as_dict()
                                if frontier_decision.opportunity is not None
                                else None
                            ),
                        }
                    )
                    semantic_utilization.register(
                        frontier_deliveries[-1],
                        call=calls,
                        source_revision=source_revision,
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
                            "certified_opportunity": delivery_metadata.get(
                                "certified_opportunity"
                            ),
                            "decision_need_id": delivery_metadata.get("decision_need_id"),
                            "decision_need_kind": delivery_metadata.get("decision_need_kind"),
                            "decision_frame_id": delivery_metadata.get("decision_frame_id"),
                            "evidence_action": evidence_action,
                            "evidence_actions": delivery_metadata.get("evidence_actions", []),
                            "revision": delivery_metadata.get("revision"),
                            "source_revision": source_revision,
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
                    semantic_utilization.register(
                        guidance_deliveries[-1],
                        call=calls,
                        source_revision=source_revision,
                    )
                if (
                    request_dispatch_eligible
                    and runtime_message_index is not None
                    and progress_payload
                    and prepared_progress_fact is not None
                ):
                    delivered_progress_fact_ids.add(prepared_progress_fact.fact_id)
                    progress_fact_deliveries.append(
                        {
                            "fact_id": prepared_progress_fact.fact_id,
                            "evidence_action": prepared_progress_fact.evidence_action,
                            "first_eligible_call": prepared_progress_fact.eligible_call,
                            "delivered_before_call": calls,
                            "message_index": runtime_message_index,
                            "request_payload_sha256": request_payload_sha256,
                            "chars": len(progress_payload),
                            "not_predictive": (
                                prepared_progress_fact.evidence_action <= actions_count
                            ),
                            "one_step_late": (
                                calls != prepared_progress_fact.eligible_call
                            ),
                        }
                    )
                    pending_progress_fact = None
                context_parts = {
                    "system_user_chars": 0,
                    "assistant_chars": 0,
                    "tool_observation_chars": 0,
                    "preemptive_retrieval_chars": len(preemptive_payload),
                    "runtime_advisory_chars": len(guidance_payload),
                    "context_frontier_chars": len(frontier_payload),
                    "progress_frame_chars": len(progress_payload),
                    "runtime_separator_chars": max(
                        0,
                        runtime_enrichment_chars
                        - len(preemptive_payload)
                        - len(guidance_payload)
                        - len(frontier_payload)
                        - len(progress_payload),
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
                provider_changed_message_indices = _changed_provider_message_indices(
                    stock_provider_messages, provider_messages
                )
                provider_change_reasons = [
                    reason
                    for reason, applies in (
                        ("provider_budget_compaction", provider_view_metrics.compacted),
                        ("preemptive_retrieval", bool(preemptive_payload)),
                        ("certified_evidence", bool(legacy_runtime_payload)),
                    )
                    if applies
                ]
                model_call_contexts.append(
                    {
                        "call": calls,
                        **context_parts,
                        "stock_context_chars": context_chars - runtime_enrichment_chars,
                        "stock_provider_chars": stock_provider_request_chars,
                        "control_provider_chars": control_provider_request_chars,
                        "feature_guidance_chars": len(guidance_payload),
                        "certified_graph_chars": len(frontier_payload),
                        "compaction_removed_chars": provider_view_metrics.elided_chars,
                        "compaction_receipt_chars": max(
                            0,
                            provider_view_metrics.output_chars
                            - max(
                                0,
                                provider_view_metrics.input_chars
                                - provider_view_metrics.elided_chars,
                            ),
                        ),
                        "final_provider_chars": provider_request_chars,
                        "stock_provider_messages_sha256": stock_provider_messages_sha256,
                        "control_request_payload_sha256": (
                            control_request_payload_sha256
                        ),
                        "control_provider_messages_sha256": (
                            control_provider_messages_sha256
                        ),
                        "provider_changed_message_indices": provider_changed_message_indices,
                        "provider_view_changed": bool(provider_changed_message_indices),
                        "provider_change_reasons": provider_change_reasons,
                        "provider_change_reason": "+".join(provider_change_reasons) or "none",
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
                        "preemptive_retrieval": dict(preemptive_decision),
                        "preemptive_retrieval_delivered": bool(preemptive_payload),
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
                        "dispatch_status": "prepared_not_sent",
                    }
                )
                frontier_disposition = {
                    FrontierDisposition.REPRESENTED_MESSAGE: (
                        ProviderEvidenceDisposition.REPRESENTED_MESSAGE
                    ),
                    FrontierDisposition.STALE_SOURCE_REVISION: (
                        ProviderEvidenceDisposition.STALE
                    ),
                    FrontierDisposition.EXPIRED_WINDOW: (
                        ProviderEvidenceDisposition.EXPIRED
                    ),
                    FrontierDisposition.FRONTIER_BUDGET: (
                        ProviderEvidenceDisposition.BUDGET
                    ),
                }.get(frontier_decision.disposition)
                if preemptive_frame is not None:
                    provider_evidence.prepare(
                        surface=ProviderEvidenceSurface.PREEMPTIVE_RETRIEVAL,
                        fact_ids=preemptive_frame.evidence_ids,
                        claim_ids=preemptive_frame.claim_ids,
                        evidence_action=preemptive_frame.evidence_action,
                        eligible_call=preemptive_frame.eligible_call,
                        prepared_call=calls,
                        message_indices=(
                            (runtime_message_index,)
                            if preemptive_payload and runtime_message_index is not None
                            else ()
                        ),
                        chars=len(preemptive_payload),
                        disposition=(
                            None
                            if preemptive_payload
                            else ProviderEvidenceDisposition.CONTROLLER_ONLY
                        ),
                        reason_codes=tuple(
                            str(item)
                            for item in preemptive_decision.get("reason_codes") or ()
                        ),
                        source_revision=graph_source_revision,
                    )
                if frontier_decision.candidate_count or frontier_decision.facts:
                    provider_evidence.prepare(
                        surface=ProviderEvidenceSurface.GRAPH_FRONTIER,
                        fact_ids=tuple(
                            str(row.get("fact_id") or "")
                            for row in frontier_decision.accounting
                            if row.get("fact_id")
                        ),
                        claim_ids=tuple(
                            str(row.get("claim_id") or "")
                            for row in frontier_decision.accounting
                            if row.get("claim_id")
                        ),
                        evidence_action=repository_evidence_action,
                        eligible_call=repository_evidence_eligible_call,
                        prepared_call=calls,
                        message_indices=(
                            (runtime_message_index,)
                            if frontier_payload and runtime_message_index is not None
                            else ()
                        ),
                        chars=len(frontier_payload),
                        disposition=frontier_disposition,
                        reason_codes=frontier_decision.reason_codes,
                        source_revision=source_revision,
                    )
                if guidance_payload:
                    provider_evidence.prepare(
                        surface=ProviderEvidenceSurface.FEATURE_FACT,
                        fact_ids=tuple(
                            str(item)
                            for item in prepared_guidance_metadata.get("effect_ids") or ()
                        ),
                        claim_ids=tuple(
                            str(item)
                            for item in prepared_guidance_metadata.get("claim_ids") or ()
                        ),
                        evidence_action=int(
                            prepared_guidance_metadata.get("evidence_action") or 0
                        ),
                        eligible_call=max(1, pending_prepared_after_call + 1),
                        prepared_call=calls,
                        message_indices=(
                            (runtime_message_index,)
                            if runtime_message_index is not None
                            else ()
                        ),
                        chars=len(guidance_payload),
                        source_revision=source_revision,
                    )
                if provider_view_metrics.active_state_chars:
                    provider_evidence.prepare(
                        surface=ProviderEvidenceSurface.STATE_FRAME,
                        fact_ids=tuple(provider_view_metrics.selected_fact_ids),
                        eligible_call=calls,
                        prepared_call=calls,
                        message_indices=(
                            (provider_view_metrics.state_frame_message_index,)
                            if provider_view_metrics.state_frame_message_index is not None
                            else ()
                        ),
                        chars=provider_view_metrics.active_state_chars,
                        source_revision=source_revision,
                    )
                if (
                    pending_preflight_evidence is not None
                    and int(pending_preflight_evidence.get("eligible_call") or 0) == calls
                ):
                    preflight_text = str(pending_preflight_evidence.get("text") or "")
                    indices = tuple(
                        index
                        for index, item in enumerate(provider_messages)
                        if preflight_text
                        and preflight_text in str(item.get("content") or "")
                    )
                    provider_evidence.prepare(
                        surface=ProviderEvidenceSurface.PREFLIGHT_RETURN,
                        fact_ids=(str(pending_preflight_evidence.get("fact_id") or ""),),
                        evidence_action=int(
                            pending_preflight_evidence.get("evidence_action") or 0
                        ),
                        eligible_call=calls,
                        prepared_call=calls,
                        message_indices=indices,
                        chars=0,
                        disposition=ProviderEvidenceDisposition.REPRESENTED_MESSAGE,
                        reason_codes=("preflight_tool_observation",),
                        source_revision=source_revision,
                    )
                if progress_payload and prepared_progress_fact is not None:
                    provider_evidence.prepare(
                        surface=ProviderEvidenceSurface.PROGRESS_FRAME,
                        fact_ids=(prepared_progress_fact.fact_id,),
                        evidence_action=prepared_progress_fact.evidence_action,
                        eligible_call=prepared_progress_fact.eligible_call,
                        prepared_call=calls,
                        message_indices=(
                            (runtime_message_index,)
                            if runtime_message_index is not None
                            else ()
                        ),
                        chars=len(progress_payload),
                        source_revision=source_revision,
                    )
                if not request_budget.within_limit:
                    provider_evidence.mark_not_sent(
                        call=calls,
                        reason="context_budget_exhausted",
                    )
                    replay_bundle.record_not_sent(
                        call=calls,
                        reason="context_budget_exhausted",
                    )
                    terminal = "ContextBudgetExhausted"
                    solver_exhausted_reason = "context_budget_exhausted"
                    break
                previous_provider_messages = [dict(item) for item in provider_messages]
                try:
                    query_started_at = time.monotonic()
                    model_call_contexts[-1]["query_started_at"] = query_started_at
                    if delivery_metadata is not None:
                        guidance_deliveries[-1]["query_started_at"] = query_started_at
                    query_timeout = planned_query_timeout
                    if query_timeout is not None and query_timeout <= 0:
                        provider_evidence.mark_not_sent(
                            call=calls,
                            reason="deadline_reserve_reached",
                        )
                        replay_bundle.record_not_sent(
                            call=calls,
                            reason="deadline_reserve_reached",
                        )
                        terminal = "DeadlineReserveReached"
                        solver_exhausted_reason = "deadline_reserve_reached"
                        deadline_reserve_exits += 1
                        break
                    model_query_invocations += 1
                    try:
                        (self.logs_dir / "provider_query_started.json").write_text(
                            json.dumps(
                                {
                                    "schema": "gt.provider_query_started.v1",
                                    "calls_started": model_query_invocations,
                                    "last_call": calls,
                                    "request_payload_sha256": request_payload_sha256,
                                    "model": str(self.model_name or ""),
                                    "gt_commit": (
                                        os.environ.get("GT_COMMIT") or ""
                                    ).strip(),
                                },
                                indent=2,
                            )
                            + "\n",
                            encoding="utf-8",
                        )
                    except OSError as exc:
                        provider_query_marker_error = type(exc).__name__
                    model_call_contexts[-1]["dispatch_status"] = "invoked"
                    replay_bundle.record_invocation(call=calls)
                    provider_evidence.mark_dispatched(
                        call=calls,
                        request_hash=request_payload_sha256,
                    )
                    if (
                        pending_preflight_evidence is not None
                        and int(pending_preflight_evidence.get("eligible_call") or 0)
                        == calls
                    ):
                        pending_preflight_evidence = None
                    message = await asyncio.wait_for(
                        asyncio.to_thread(model.query, query_messages),
                        timeout=query_timeout,
                    )
                except TimeoutError:
                    replay_bundle.record_error(call=calls, error_type="TimeoutError")
                    model_call_contexts[-1]["dispatch_status"] = "response_error"
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
                    replay_bundle.record_error(call=calls, error_type="InterruptAgentFlow")
                    model_call_contexts[-1]["dispatch_status"] = "response_error"
                    messages.extend(flow.messages)
                    continue
                replay_bundle.record_response(call=calls, response=message)
                provider_responses_received += 1
                model_call_contexts[-1]["dispatch_status"] = "response_received"
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
                for classification, proposed in zip(
                    action_classifications, proposed_actions, strict=True
                ):
                    if classification.authority is ValidationAuthority.DECLARED:
                        declared_validator_proposals += 1
                        if proposed.shell_redirections:
                            declared_validators_with_redirection += 1
                            if proposed.operation is ActionOperation.VALIDATE:
                                declared_validators_preserved_with_redirection += 1
                semantic_utilization.observe(
                    call=calls,
                    actions=proposed_actions,
                    source_revision=source_revision,
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
                if frontier_payload and frontier_deliveries:
                    first_command = str((actions[0] if actions else {}).get("command") or "")
                    frontier_anchors = tuple(
                        str(anchor)
                        for fact in frontier_deliveries[-1].get("facts") or ()
                        for anchor in (fact.get("path"), fact.get("symbol"))
                        if anchor
                    )
                    anchor_followed = bool(first_command) and any(
                        anchor in first_command for anchor in frontier_anchors
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
                    frontier_deliveries[-1].update(
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
                        sufficiency_row: dict[str, Any] | None = None
                        if self.enable_decision_sufficiency:
                            sufficiency_row = {
                                "action_id": proposed.action_id,
                                "cycle_id": proposed.cycle_id,
                                "model_call": calls,
                                "source_revision": source_revision,
                                "graph_revision": graph_source_revision,
                                "selecting_request_hash": request_payload_sha256,
                                "disposition": "pass",
                                "return_eligible": False,
                                "reason_codes": ["repository_substrate_unavailable"],
                            }
                            target_paths = tuple(
                                dict.fromkeys(
                                    path
                                    for target in proposed.targets
                                    if (
                                        path := _workspace_target_path(
                                            target.path,
                                            cwd=self.cwd,
                                        )
                                    )
                                )
                            )
                            if (
                                preemptive_repository is not None
                                and preemptive_repository.complete
                                and preemptive_repository_revision
                                == graph_source_revision
                                and target_paths
                            ):
                                target_keys = {
                                    path.lower().replace("\\", "/")
                                    for path in target_paths
                                }
                                adjacent_paths = set(target_keys)
                                selected_links = []
                                for link in preemptive_repository.structural_links:
                                    source_key = link.source_path.lower().replace("\\", "/")
                                    target_key = link.target_path.lower().replace("\\", "/")
                                    if source_key in target_keys or target_key in target_keys:
                                        selected_links.append(link)
                                        adjacent_paths.update((source_key, target_key))
                                selected_documents = tuple(
                                    document
                                    for document in preemptive_repository.documents
                                    if document.path.lower().replace("\\", "/")
                                    in adjacent_paths
                                )
                                if len(selected_documents) > 256 or len(selected_links) > 256:
                                    sufficiency_row["reason_codes"] = [
                                        "action_repository_slice_limit"
                                    ]
                                elif selected_documents:
                                    try:
                                        action_retriever = HybridRetriever(
                                            selected_documents,
                                            structural_links=tuple(selected_links),
                                        )
                                        action_state = RetrievalState(
                                            task_text=instruction,
                                            intent=RetrievalIntent.CHANGE_IMPACT,
                                            action=_retrieval_action_state(
                                                proposed,
                                                target_paths=target_paths,
                                            ),
                                            diagnostics=retrieval_diagnostics,
                                            active_symbols=retrieval_active_symbols,
                                            validation_state=retrieval_validation_state,
                                            source_revision=graph_source_revision,
                                        )
                                        action_result = await asyncio.wait_for(
                                            asyncio.to_thread(
                                                action_retriever.retrieve,
                                                action_state,
                                                channel_limit=min(
                                                    32,
                                                    self.preemptive_retrieval_channel_limit,
                                                ),
                                                top_k=min(
                                                    12,
                                                    self.preemptive_retrieval_top_k,
                                                ),
                                                selection_limit=1,
                                                token_budget=min(
                                                    160,
                                                    self.preemptive_retrieval_token_budget,
                                                ),
                                            ),
                                            timeout=self.preflight_timeout_sec,
                                        )
                                        visible_claim_ids = _provider_visible_claim_ids(
                                            provider_messages,
                                            action_result.selected_context,
                                        )
                                        sufficiency = compile_decision_sufficiency(
                                            proposed,
                                            action_result,
                                            ProviderVisibleState(
                                                selecting_request_hash=(
                                                    request_payload_sha256
                                                ),
                                                source_revision=source_revision,
                                                graph_revision=graph_source_revision,
                                                selecting_request_claim_ids=(
                                                    visible_claim_ids
                                                ),
                                                complete=True,
                                            ),
                                            current_source_revision=source_revision,
                                            current_graph_revision=(
                                                graph_source_revision
                                            ),
                                            max_evidence_tokens=160,
                                            max_evidence_chars=480,
                                            max_evidence_claims=1,
                                        )
                                        sufficiency_row.update(sufficiency.as_dict())
                                        sufficiency_row["retrieval"] = {
                                            "query_hash": action_result.query_hash,
                                            "latency_ms": action_result.latency_ms,
                                            "selected_claim_ids": [
                                                candidate.claim_hash
                                                for candidate in action_result.selected_context
                                            ],
                                            "provider_visible_claim_ids": list(
                                                visible_claim_ids
                                            ),
                                            "reason_codes": list(
                                                action_result.reason_codes
                                            ),
                                        }
                                        if (
                                            sufficiency.disposition
                                            is DecisionSufficiencyDisposition.RETURN_ELIGIBLE
                                            and sufficiency.bundle is not None
                                            and preflight.disposition
                                            is ActionDisposition.PASS
                                        ):
                                            evidence = _render_decision_evidence(
                                                sufficiency.bundle
                                            )
                                            preflight = PreflightDecision(
                                                disposition=(
                                                    ActionDisposition.RETURN_TO_MODEL
                                                ),
                                                command=proposed.raw_command,
                                                evidence=evidence,
                                                reason_codes=(
                                                    "certified_missing_decision_evidence",
                                                ),
                                                confidence=1.0,
                                                source_revision=source_revision,
                                                evidence_grade=(
                                                    EvidenceGrade.STRUCTURAL
                                                    if any(
                                                        claim.support_kind
                                                        == "certified_structural"
                                                        for claim in sufficiency.bundle.claims
                                                    )
                                                    else EvidenceGrade.DIRECT
                                                ),
                                                evidence_ids=tuple(
                                                    claim.claim_id
                                                    for claim in sufficiency.bundle.claims
                                                ),
                                            )
                                        elif (
                                            sufficiency.return_eligible
                                            and preflight.disposition
                                            is not ActionDisposition.PASS
                                        ):
                                            sufficiency_row["reason_codes"] = [
                                                *sufficiency_row.get("reason_codes", []),
                                                "existing_preflight_preferred",
                                            ]
                                    except TimeoutError:
                                        sufficiency_row["reason_codes"] = [
                                            "decision_sufficiency_timeout"
                                        ]
                                    except Exception as exc:
                                        sufficiency_row["reason_codes"] = [
                                            "decision_sufficiency_exception:"
                                            + type(exc).__name__
                                        ]
                                else:
                                    sufficiency_row["reason_codes"] = [
                                        "action_target_not_indexed"
                                    ]
                            elif not target_paths:
                                sufficiency_row["reason_codes"] = [
                                    "action_target_unavailable"
                                ]
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
                        if sufficiency_row is not None:
                            sufficiency_row["applied_disposition"] = (
                                applied_disposition.value
                            )
                            sufficiency_row["applied_reason_codes"] = list(
                                applied_reasons
                            )
                            decision_sufficiency_receipts.append(sufficiency_row)
                    if (
                        applied_disposition == ActionDisposition.RETURN_TO_MODEL
                        and proposed.operation is ActionOperation.SUBMIT
                        and "proven_submit_blocker" in applied_reasons
                    ):
                        readiness_evidence = self._ledger.readiness_evidence(
                            source_revision
                        )
                        self._features.record_submit(
                            action_id=actions_count,
                            revision=source_revision,
                            source_revision=source_revision,
                            refused=True,
                            sensor_healthy=snapshot.healthy,
                            check_count=len(readiness_evidence),
                            passing_checks=sum(
                                item.returncode == 0 for item in readiness_evidence
                            ),
                            failing_checks=sum(
                                item.returncode != 0 for item in readiness_evidence
                            ),
                            blockers=tuple(
                                item.command
                                for item in readiness_evidence
                                if item.returncode != 0
                            ),
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
                        preflight_text = "Pre-execution check: " + " ".join(
                            preflight.evidence
                        )
                        pending_preflight_evidence = {
                            "fact_id": proposed.cycle_id,
                            "evidence_action": actions_count,
                            "eligible_call": calls + 1,
                            "text": preflight_text,
                        }
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
                        current_readiness = self._ledger.readiness_evidence(
                            source_revision
                        )
                        if (
                            self.preflight_mode is PreflightMode.ASSISTIVE_SAFE
                            and source_validation_debt
                            and repository_evidence.project_checks
                            and not current_readiness
                            and source_revision not in project_validation_probe_revisions
                        ):
                            project_validation_probe_revisions.add(source_revision)
                            project_check = repository_evidence.project_checks[0]
                            probe_timeout = self.max_validation_timeout_sec
                            if deadline is not None:
                                probe_timeout = min(
                                    probe_timeout,
                                    max(
                                        0.05,
                                        (deadline - time.monotonic())
                                        * self.validation_timeout_budget_ratio,
                                    ),
                                )
                            try:
                                probe_result = await self._host_executions.exec(
                                    environment,
                                    project_check,
                                    category=HostExecCategory.PROJECT_VALIDATION_PROBE,
                                    action_id=actions_count,
                                    source_revision=source_revision,
                                    cwd=self.cwd,
                                    env={},
                                    timeout_sec=probe_timeout,
                                )
                            except Exception as exc:  # fail open at submit
                                project_validation_probes.append(
                                    {
                                        "action_id": actions_count,
                                        "command": project_check,
                                        "source_revision": source_revision,
                                        "status": "failed_open",
                                        "error_type": type(exc).__name__,
                                    }
                                )
                            else:
                                raw_probe_diagnostic = " ".join(
                                    (
                                        (probe_result.stderr or "")
                                        + " "
                                        + (probe_result.stdout or "")
                                    ).split()
                                )[:800]
                                project_validation_probe_diagnostics[
                                    normalize_command(project_check)
                                ] = raw_probe_diagnostic
                                probe_classification = classify_validation_command(
                                    project_check,
                                    explicit_checks,
                                ).with_result(
                                    result_code=probe_result.return_code,
                                    output=(
                                        (probe_result.stderr or "")
                                        + "\n"
                                        + (probe_result.stdout or "")
                                    ),
                                    source_revision=source_revision,
                                    workspace_revision=snapshot.revision,
                                )
                                self._ledger.record_check(
                                    project_check,
                                    returncode=probe_result.return_code,
                                    revision=source_revision,
                                    grounded=probe_classification.grounded,
                                    classification=probe_classification,
                                )
                                if (
                                    probe_classification.status is ValidationStatus.PASS
                                    and probe_classification.status_attributed
                                ):
                                    source_validation_debt = False
                                project_validation_probes.append(
                                    {
                                        "action_id": actions_count,
                                        "command": project_check,
                                        "source_revision": source_revision,
                                        "status": probe_classification.status.value,
                                        "returncode": probe_result.return_code,
                                        "project_scoped": (
                                            probe_classification.project_scoped
                                        ),
                                        "diagnostic": raw_probe_diagnostic,
                                    }
                                )
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
                        hold_submit = bool(
                            decision.decision == InterventionDecision.HOLD_ONCE
                            and self.preflight_mode is PreflightMode.ASSISTIVE_SAFE
                        )
                        self._features.record_submit(
                            action_id=actions_count,
                            revision=source_revision,
                            source_revision=source_revision,
                            refused=hold_submit,
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
                        if hold_submit:
                            blocker_text = ", ".join(decision.blockers[:2])
                            blocker_diagnostic = next(
                                (
                                    project_validation_probe_diagnostics.get(
                                        normalize_command(blocker), ""
                                    )
                                    for blocker in decision.blockers
                                    if project_validation_probe_diagnostics.get(
                                        normalize_command(blocker), ""
                                    )
                                ),
                                "",
                            )
                            preflight_text = (
                                "Pre-execution check: current validation is failing; "
                                f"blocker={blocker_text}."
                                + (
                                    f" diagnostic={blocker_diagnostic}"
                                    if blocker_diagnostic
                                    else ""
                                )
                            )
                            pending_reconsideration_cycle = proposed.cycle_id
                            pending_preflight_evidence = {
                                "fact_id": "submit-"
                                + hashlib.sha256(
                                    f"{source_revision}\0{blocker_text}".encode()
                                ).hexdigest()[:20],
                                "evidence_action": actions_count,
                                "eligible_call": calls + 1,
                                "text": preflight_text,
                            }
                            outputs.append(
                                {
                                    "output": preflight_text,
                                    "returncode": 2,
                                    "exception_info": "",
                                }
                            )
                            cancelled = len(actions) - index - 1
                            for cancelled_proposal in proposed_actions[index + 1 :]:
                                self._features.record_cancelled_proposal(
                                    cancelled_proposal,
                                    mode=self.preflight_mode,
                                    reason="submit_readiness_return_to_model",
                                )
                            outputs.extend(
                                {
                                    "output": (
                                        "Cancelled: submit readiness requires fresh reasoning."
                                    ),
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
                                    reason="submit_readiness_return_to_model",
                                )
                            break

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
                    workspace_impact = classify_workspace_impact(
                        proposed,
                        cwd=self.cwd,
                    )
                    if workspace_impact is WorkspaceImpact.PROVEN_NO_WORKSPACE_CHANGE:
                        self._host_executions.record_cache_hit(
                            category=HostExecCategory.WORKSPACE_MANIFEST,
                            command=(
                                "[workspace scan skipped: mechanically proven no workspace change]"
                            ),
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
                    source_receipt = source_revision_receipt(after, task_deliverables)
                    source_revision = source_receipt.revision
                    graph_receipt = graph_revision_receipt(after, task_deliverables)
                    graph_source_revision = graph_receipt.revision
                    classification = classification.with_result(
                        result_code=result.return_code,
                        output=output["output"],
                        source_revision=source_revision,
                        workspace_revision=snapshot.revision,
                    )
                    diagnostic_text = str(output["output"] or "").strip()
                    if len(diagnostic_text) > 4_000:
                        diagnostic_text = (
                            diagnostic_text[:2_000]
                            + "\n...[bounded diagnostic]...\n"
                            + diagnostic_text[-2_000:]
                        )
                    retrieval_diagnostics = (
                        (diagnostic_text,)
                        if diagnostic_text
                        and (
                            result.return_code != 0
                            or classification.status.value == "fail"
                        )
                        else ()
                    )
                    diagnostic_repository_paths = tuple(
                        path
                        for path, entry in snapshot.entries.items()
                        if entry.kind == "f"
                        and classify_change(
                            path,
                            kind="f",
                            task_deliverables=task_deliverables,
                            content=entry.content,
                        ).graph_indexable
                    )
                    diagnostic_anchors = (
                        extract_diagnostic_anchors(
                            diagnostic_text,
                            repository_paths=diagnostic_repository_paths,
                            cwd=self.cwd,
                        )
                        if retrieval_diagnostics
                        else ()
                    )
                    classified_transition = tuple(
                        classify_change(
                            path,
                            kind=(after.entries[path].kind if path in after.entries else "f"),
                            task_deliverables=task_deliverables,
                            content=(
                                after.entries[path].content
                                if path in after.entries
                                else transition.before_contents.get(path)
                            ),
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
                    model_authored_source_paths = tuple(
                        item.path
                        for item in classified_transition
                        if item.origin
                        in {ChangeOrigin.MODEL_AUTHORED, ChangeOrigin.TASK_DELIVERABLE}
                        and item.graph_indexable
                    )
                    if model_authored_source_paths:
                        repository_fact_tracker.record_model_authored_paths(
                            model_authored_source_paths,
                            action_id=actions_count,
                        )
                    if (
                        repository_session is not None
                        and graph_receipt.complete
                        and graph_source_revision != repository_session.source_revision
                    ):
                        source_paths = tuple(
                            item.path for item in classified_transition if item.graph_indexable
                        )
                        transition = await self._hydrate_graph_transition(
                            environment,
                            repository_session,
                            transition,
                            snapshot=after,
                            changed_paths=source_paths,
                            source_revision=graph_source_revision,
                        )
                        mirror_advanced = repository_session.apply_transition(
                            transition,
                            source_revision=graph_source_revision,
                            changed_paths=source_paths,
                        )
                        if mirror_advanced:
                            try:
                                repository_evidence = await asyncio.wait_for(
                                    asyncio.to_thread(
                                        repository_session.refresh,
                                        source_revision=graph_source_revision,
                                    ),
                                    timeout=self.repository_refresh_timeout_sec,
                                )
                            except TimeoutError:
                                repository_session.invalidate(
                                    source_revision=graph_source_revision,
                                    status="refresh_timeout",
                                )
                                repository_evidence = repository_session.evidence
                            if repository_evidence.available:
                                repository_evidence_action = actions_count
                                repository_evidence_eligible_call = calls + 1
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
                    elif not graph_receipt.complete:
                        if repository_session is not None:
                            repository_session.invalidate(
                                source_revision=graph_source_revision,
                                status=RepositoryIntelligenceStatus.MIRROR_INCOMPLETE.value,
                            )
                            repository_evidence = repository_session.evidence
                    action_target_paths = tuple(
                        dict.fromkeys(
                            normalized
                            for target in proposed.targets
                            for normalized in [
                                _workspace_target_path(target.path, cwd=self.cwd)
                            ]
                            if normalized in snapshot.entries
                            and snapshot.entries[normalized].kind == "f"
                            and classify_change(
                                normalized,
                                kind="f",
                                task_deliverables=task_deliverables,
                                content=snapshot.entries[normalized].content,
                            ).graph_indexable
                        )
                    )
                    action_graph_paths = tuple(
                        dict.fromkeys(
                            (
                                *action_target_paths,
                                *(anchor.path for anchor in diagnostic_anchors),
                            )
                        )
                    )
                    action_graph_symbols = tuple(
                        dict.fromkeys(
                            anchor.symbol
                            for anchor in diagnostic_anchors
                            if anchor.symbol
                        )
                    )
                    if (
                        repository_session is not None
                        and repository_session.evidence.substrate_ready
                        and action_graph_paths
                        and proposed.operation
                        in {
                            ActionOperation.READ,
                            ActionOperation.SEARCH,
                            ActionOperation.EDIT,
                            ActionOperation.CREATE,
                            ActionOperation.VALIDATE,
                        }
                    ):
                        repository_evidence = await asyncio.to_thread(
                            repository_session.query,
                            source_revision=graph_source_revision,
                            active_paths=action_graph_paths,
                            active_symbols=action_graph_symbols,
                            diagnostic_fingerprint=(
                                classification.diagnostic_fingerprint
                            ),
                            boundary=f"post_{proposed.operation.value}",
                        )
                        if repository_evidence.available:
                            repository_evidence_action = actions_count
                            repository_evidence_eligible_call = calls + 1
                            self._features.refresh_structural_evidence(
                                source_revision=source_revision,
                                anchors=repository_evidence.anchors,
                                definitions=repository_evidence.definitions,
                                references=repository_evidence.references,
                                callers=repository_evidence.callers,
                                graph_revision=repository_evidence.graph_revision,
                            )
                    retrieval_last_action = _retrieval_action_state(
                        proposed,
                        target_paths=action_target_paths,
                    )
                    retrieval_last_operation = proposed.operation.value
                    retrieval_active_paths = action_graph_paths
                    retrieval_active_symbols = action_graph_symbols
                    retrieval_changed_paths = tuple(model_authored_source_paths)
                    retrieval_validation_state = classification.status.value
                    retrieval_evidence_action = actions_count
                    retrieval_eligible_call = calls + 1
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
                            and item.origin is ChangeOrigin.MODEL_AUTHORED
                        )
                    )
                    deliverable_paths = tuple(
                        sorted(
                            item.path
                            for item in classified_transition
                            if item.origin is ChangeOrigin.TASK_DELIVERABLE
                            and item.path in after.entries
                            and item.path in (*transition.created, *transition.modified)
                            and after.entries[item.path].size > 0
                        )
                    )
                    read_anchors = tuple(
                        sorted(
                            {
                                target.path
                                for operation in proposed.operations
                                if operation.operation
                                in {ActionOperation.READ, ActionOperation.SEARCH}
                                for target in operation.targets
                                if target.path
                            }
                        )
                    )
                    primary_operation = next(
                        (
                            operation
                            for operation in proposed.operations
                            if operation.operation is proposed.operation
                        ),
                        next(iter(proposed.operations), None),
                    )
                    result_kind = classify_action_result(
                        operation=proposed.operation.value,
                        executable=(
                            primary_operation.executable
                            if primary_operation is not None
                            else ""
                        ),
                        return_code=result.return_code,
                        output=output["output"],
                    )
                    if result_kind is ActionResultKind.TIMEOUT:
                        model_action_timeouts += 1
                    valid_observation = result_kind in {
                        ActionResultKind.SUCCESS,
                        ActionResultKind.SEARCH_NO_MATCH,
                        ActionResultKind.DIFFERENCE,
                        ActionResultKind.VALIDATION_PASS,
                        ActionResultKind.VALIDATION_FAIL,
                    }
                    new_read_anchor = bool(
                        proposed.operation in {ActionOperation.READ, ActionOperation.SEARCH}
                        and valid_observation
                        and any(anchor not in seen_read_anchors for anchor in read_anchors)
                    )
                    if valid_observation:
                        seen_read_anchors.update(read_anchors)
                    elif (
                        proposed.operation in {ActionOperation.READ, ActionOperation.SEARCH}
                        and read_anchors
                    ):
                        failed_read_anchors_not_consumed += len(read_anchors)
                    if result_kind in {
                        ActionResultKind.SEARCH_NO_MATCH,
                        ActionResultKind.DIFFERENCE,
                    }:
                        valid_nonzero_observations += 1
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
                    task_progress_gain = bool(validation_gain or deliverable_paths)
                    progress_observation = ProgressObservation.create(
                        command=command,
                        operation=proposed.operation.value,
                        executable=(
                            primary_operation.executable
                            if primary_operation is not None
                            else ""
                        ),
                        targets=tuple(
                            sorted(
                                {
                                    *read_anchors,
                                    *source_paths,
                                    *deliverable_paths,
                                    *(
                                        target.path
                                        for target in proposed.targets
                                        if target.path
                                    ),
                                }
                            )
                        ),
                        source_revision=source_revision,
                        result_kind=result_kind,
                        output=output["output"],
                        declared_check_id=classification.declared_check_id or "",
                        diagnostic_fingerprint=(
                            classification.diagnostic_fingerprint or ""
                        ),
                        task_progress_gain=task_progress_gain,
                        contradictory=bool(
                            classification.is_validation
                            and classification.status.value == "fail"
                            and classification.status_attributed
                        ),
                    )
                    observation_novelty = (
                        progress_observation.observation_id not in seen_observation_ids
                    )
                    seen_observation_ids.add(progress_observation.observation_id)
                    observation_gain = task_information_gain(
                        new_read_anchor=new_read_anchor,
                        diagnostic_gain=diagnostic_gain,
                    )
                    progress_observation = replace(
                        progress_observation,
                        observation_gain=observation_gain,
                    )
                    progress_observations.append(
                        {
                            "action_id": actions_count,
                            "attempt_id": progress_observation.attempt_id,
                            "observation_id": progress_observation.observation_id,
                            "operation": progress_observation.operation,
                            "executable": progress_observation.executable,
                            "targets": list(progress_observation.targets),
                            "result_kind": progress_observation.result_kind.value,
                            "output_sha256": progress_observation.output_sha256,
                            "command_sha256": progress_observation.command_sha256,
                            "declared_check_id": progress_observation.declared_check_id,
                            "diagnostic_fingerprint": (
                                progress_observation.diagnostic_fingerprint
                            ),
                            "observation_gain": observation_gain,
                            "observation_novelty": observation_novelty,
                            "task_progress_gain": task_progress_gain,
                            "contradictory": progress_observation.contradictory,
                            "source_revision": source_revision,
                        }
                    )
                    if validation_gain:
                        semantic_kind = "validation_gain"
                    elif deliverable_paths:
                        semantic_kind = "task_output_gain"
                    elif diagnostic_gain:
                        semantic_kind = "diagnostic_observation"
                    elif new_read_anchor:
                        semantic_kind = "localization_gain"
                    elif source_paths:
                        semantic_kind = "patch_attempt"
                    elif observation_gain:
                        semantic_kind = "observation_gain"
                    else:
                        semantic_kind = "no_gain"
                    semantic_progress_kinds[semantic_kind] = (
                        semantic_progress_kinds.get(semantic_kind, 0) + 1
                    )
                    if task_progress_gain:
                        task_progress_changes += 1
                    if source_paths:
                        source_validation_debt = True
                    if validation_gain and (
                        classification.authority is ValidationAuthority.DECLARED
                        or classification.project_scoped
                    ):
                        source_validation_debt = False
                    if self.enable_progress_control:
                        progress_signature = semantic_progress_fingerprint(
                            source_revision=source_revision,
                            changed_paths=source_paths,
                            validation_state=classification.status.value,
                            diagnostic_fingerprint=(
                                classification.diagnostic_fingerprint or ""
                            ),
                            project_checks=repository_evidence.project_checks,
                            validation_debt=source_validation_debt,
                        )
                        progress_transition = self._progress.observe(
                            progress_signature,
                            information_gain=observation_gain,
                            changed=bool(source_paths),
                            semantic_gain=task_progress_gain,
                            is_error=result_kind
                            in {
                                ActionResultKind.EXECUTION_ERROR,
                                ActionResultKind.TIMEOUT,
                                ActionResultKind.VALIDATION_FAIL,
                            },
                            contradictory=progress_observation.contradictory,
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
                                    "attempt_id": progress_observation.attempt_id,
                                    "semantic_fingerprint": progress_signature,
                                    "observation_id": progress_observation.observation_id,
                                    "result_kind": result_kind.value,
                                    "observation_gain": observation_gain,
                                    "task_progress_gain": task_progress_gain,
                                    "action_id": actions_count,
                                }
                            )
                            if (
                                progress_transition.current
                                in {"STALLED", "CONTRADICTED", "BUDGET_RISK"}
                                and pending_progress_fact is None
                                and len(delivered_progress_fact_ids) < 2
                            ):
                                pending_progress_fact = StallAggregateFact.create(
                                    state=progress_transition.current,
                                    repeated_operation=proposed.operation.value,
                                    concrete_targets=tuple(
                                        target.path
                                        for target in proposed.targets
                                        if target.path
                                    ),
                                    repeat_count=max(1, progress_transition.streak),
                                    last_returncode=result.return_code,
                                    timeout_observed=(result.return_code == 124),
                                    source_revision=source_revision,
                                    remaining_calls=max(0, self.step_limit - calls),
                                    remaining_seconds=(
                                        None
                                        if deadline is None
                                        else deadline - time.monotonic()
                                    ),
                                    unresolved_anchors=tuple(
                                        list(explicit_checks)[:2]
                                        or sorted(task_deliverables)[:2]
                                    ),
                                    evidence_action=actions_count,
                                    eligible_call=calls + 1,
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
                        and source_receipt.complete
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
                        completion_opportunity = None
                        if certificate.auto_submit_eligible:
                            completion_opportunity = certify_opportunity(
                                kind=OpportunityKind.COMPLETION_READY,
                                authority=EvidenceAuthority.MECHANICAL,
                                source_revision=source_revision,
                                current_source_revision=source_revision,
                                workspace_revision=snapshot.revision,
                                evidence_ids=tuple(
                                    item.predicate_id for item in certificate.observations
                                ),
                                concrete_anchors=tuple(
                                    predicate.command
                                    for predicate in completion_plan.predicates
                                ),
                                absent_from_provider_history=True,
                                decision_relevant=True,
                                eligible_call=calls,
                                current_call=calls,
                            )
                            controller_opportunities.append(
                                {
                                    "boundary": "completion_controller",
                                    "action_id": actions_count,
                                    **completion_opportunity.as_dict(),
                                }
                            )
                        receipts.append(
                            {
                                "action": actions_count,
                                "kind": "completion_certificate",
                                "decision": (
                                    "AUTO_SUBMIT"
                                    if certificate.auto_submit_eligible
                                    and completion_opportunity is not None
                                    and completion_opportunity.certified
                                    else "CONTINUE"
                                ),
                                "revision": snapshot.revision,
                                "reason_codes": list(certificate.reason_codes),
                                "certified_opportunity": (
                                    completion_opportunity.as_dict()
                                    if completion_opportunity is not None
                                    else None
                                ),
                            }
                        )
                        if (
                            certificate.auto_submit_eligible
                            and completion_opportunity is not None
                            and completion_opportunity.certified
                        ):
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
            semantic_utilization.finalize()
            semantic_utilization_summary = semantic_utilization.summary()
            assistant_steps = sum(1 for message in messages if message.get("role") == "assistant")
            dispatched_model_call_contexts = [
                row
                for row in model_call_contexts
                if row.get("dispatch_status")
                in {"invoked", "response_received", "response_error"}
            ]
            feature_summary = self._features.summary()
            provider_evidence_summary = provider_evidence.as_dict()
            certification_decisions = [
                *feature_summary.get("certification_decisions", ()),
                *(
                    {
                        "boundary": "repository_frontier",
                        "call": int(row.get("call") or 0),
                        **dict(row["opportunity"]),
                    }
                    for row in frontier_decisions
                    if isinstance(row.get("opportunity"), dict)
                ),
                *controller_opportunities,
            ]
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
            repository_evidence = _resolved_repository_evidence(
                repository_evidence,
                repository_session,
            )
            repository_applicability = classify_repository_applicability(repository_evidence)
            # Keep task-start substrate applicability authoritative.  A task
            # that transferred no structurally supported source remains outside
            # the graph denominator even if the model later creates helper
            # files in languages the vendored index cannot parse.
            source_less_task = bool(source_less_task_at_start) or (
                repository_applicability
                == "not_applicable_no_supported_source"
            )
            if source_less_task_at_start:
                repository_applicability = "not_applicable_no_supported_source"
            frontier_required = bool(
                repository_required
                and self.enable_context_frontier
                and not source_less_task
            )
            intelligence_failures: list[str] = []
            transient_intelligence_failures: list[str] = []
            if (
                repository_required
                and not source_less_task
                and not repository_evidence.substrate_ready
            ):
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
                    and not source_less_task
                )
                else ()
            )
            graph_degraded_fallback = _graph_gate_degraded_fallback(
                initial_failures=graph_gate_reasons,
                current_failures=final_graph_gate_reasons,
            )
            intelligence_failures.extend(final_graph_gate_reasons)
            transient_intelligence_failures.extend(
                f"graph_gate:{reason}"
                for reason in graph_gate_reasons
                if reason not in final_graph_gate_reasons
            )
            if repository_required and repository_session is not None and not source_less_task:
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
                "api_calls": model_query_invocations,
                "provider_requests_prepared": provider_requests_prepared,
                "model_query_invocations": model_query_invocations,
                "provider_responses_received": provider_responses_received,
                "provider_query_marker_error": provider_query_marker_error,
                "provider_requests_not_sent": max(
                    0, provider_requests_prepared - model_query_invocations
                ),
                "provider_evidence_events": provider_evidence_summary["event_count"],
                "provider_evidence_dispatched": provider_evidence_summary[
                    "dispatched_events"
                ],
                "provider_evidence_prepared_not_sent": provider_evidence_summary[
                    "prepared_not_sent_events"
                ],
                "actions": actions_count,
                "assistant_steps": assistant_steps,
                "trajectory_messages": len(messages),
                "tokens_per_call": (
                    round(total_tokens / model_query_invocations, 6)
                    if model_query_invocations
                    else 0.0
                ),
                "tokens_per_assistant_step": (
                    round(total_tokens / assistant_steps, 6) if assistant_steps else 0.0
                ),
                "actions_per_assistant_step": (
                    round(actions_count / assistant_steps, 6) if assistant_steps else 0.0
                ),
                "elapsed_seconds": elapsed_seconds,
                "wall_time_sec": elapsed_seconds,
                "context_chars_sent": sum(
                    int(row.get("context_chars") or 0)
                    for row in dispatched_model_call_contexts
                ),
                "provider_request_chars_sent": sum(
                    int(row.get("provider_request_chars") or 0)
                    for row in dispatched_model_call_contexts
                ),
                "provider_requests_hashed": sum(
                    bool(row.get("provider_messages_sha256"))
                    and bool(row.get("request_payload_sha256"))
                    for row in dispatched_model_call_contexts
                ),
                "provider_request_hash_coverage": (
                    round(
                        sum(
                            bool(row.get("provider_messages_sha256"))
                            for row in dispatched_model_call_contexts
                        )
                        / len(dispatched_model_call_contexts),
                        6,
                    )
                    if dispatched_model_call_contexts
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
                "stock_provider_chars_sent": sum(
                    int(row.get("stock_provider_chars") or 0)
                    for row in dispatched_model_call_contexts
                ),
                "feature_guidance_chars_sent": sum(
                    int(row.get("feature_guidance_chars") or 0)
                    for row in dispatched_model_call_contexts
                ),
                "certified_graph_chars_sent": sum(
                    int(row.get("certified_graph_chars") or 0)
                    for row in dispatched_model_call_contexts
                ),
                "provider_compaction_removed_chars": sum(
                    int(row.get("compaction_removed_chars") or 0) for row in model_call_contexts
                ),
                "provider_compaction_receipt_chars": sum(
                    int(row.get("compaction_receipt_chars") or 0) for row in model_call_contexts
                ),
                "final_provider_chars_sent": sum(
                    int(row.get("final_provider_chars") or 0)
                    for row in dispatched_model_call_contexts
                ),
                "provider_changed_message_count": sum(
                    len(row.get("provider_changed_message_indices") or ())
                    for row in model_call_contexts
                ),
                "provider_view_changed_calls": sum(
                    bool(row.get("provider_view_changed")) for row in model_call_contexts
                ),
                "provider_exact_parity_calls": sum(
                    not bool(row.get("provider_view_changed")) for row in model_call_contexts
                ),
                "certified_evidence_changed_calls": sum(
                    "certified_evidence" in (row.get("provider_change_reasons") or ())
                    for row in model_call_contexts
                ),
                "provider_budget_compaction_changed_calls": sum(
                    "provider_budget_compaction" in (row.get("provider_change_reasons") or ())
                    for row in model_call_contexts
                ),
                "certified_opportunity_evaluations": len(certification_decisions),
                "certified_opportunities": sum(
                    bool(row.get("certified")) for row in certification_decisions
                ),
                "certified_opportunity_abstentions": sum(
                    not bool(row.get("certified")) for row in certification_decisions
                ),
                "heuristic_opportunity_abstentions": sum(
                    "heuristic_evidence" in (row.get("reason_codes") or ())
                    for row in certification_decisions
                ),
                "certified_provider_deliveries": sum(
                    bool((row.get("certified_opportunity") or {}).get("certified"))
                    for row in (*guidance_deliveries, *frontier_deliveries)
                ),
                "certified_provider_behavior_measurable": sum(
                    bool(row.get("next_command"))
                    for row in (*guidance_deliveries, *frontier_deliveries)
                    if bool((row.get("certified_opportunity") or {}).get("certified"))
                ),
                "certified_provider_anchor_followed": sum(
                    bool(row.get("anchor_followed"))
                    for row in (*guidance_deliveries, *frontier_deliveries)
                    if bool((row.get("certified_opportunity") or {}).get("certified"))
                ),
                "semantic_utilization_deliveries": semantic_utilization_summary["deliveries"],
                "semantic_utilization_same_response": semantic_utilization_summary[
                    "same_response"
                ],
                "semantic_utilization_deferred": semantic_utilization_summary["deferred"],
                "semantic_utilization_stale_source": semantic_utilization_summary[
                    "stale_source"
                ],
                "semantic_utilization_no_match": semantic_utilization_summary["no_match"],
                "semantic_utilization_matched": semantic_utilization_summary["matched"],
                "semantic_utilization_rate": (
                    round(
                        semantic_utilization_summary["matched"]
                        / semantic_utilization_summary["deliveries"],
                        6,
                    )
                    if semantic_utilization_summary["deliveries"]
                    else 1.0
                ),
                "certified_controller_actuations": auto_submit_attempts,
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
                "project_validation_probe_attempts": len(project_validation_probes),
                "project_validation_probe_execs": sum(
                    row.get("status") != "failed_open"
                    for row in project_validation_probes
                ),
                "completion_certificates_complete": sum(
                    item.status is CompletionStatus.COMPLETE for item in completion_certificates
                ),
                "auto_submit_attempts": auto_submit_attempts,
                "auto_submits": auto_submit_count,
                "effective_actions": host_execution["effective_task_actions"],
                "effective_actions_schema": "actual-task-environment-execs-v2",
                "decision_actions": host_execution["decision_actions"],
                "harness_overhead_execs": host_execution["harness_overhead_execs"],
                "controller_intervention_execs": (
                    host_execution["controller_intervention_execs"]
                ),
                "substrate_environment_execs": (
                    host_execution["substrate_environment_execs"]
                ),
                "effective_task_actions": host_execution["effective_task_actions"],
                "actual_environment_execs": host_execution["actual_environment_execs"],
                "controller_environment_execs": host_execution["controller_environment_execs"],
                "controller_cached_reads": host_execution["controller_cached_reads"],
                "sensor_environment_execs": host_execution["sensor_environment_execs"],
                "host_exec_category_counts": host_execution["category_counts"],
                "host_exec_category_latency": host_execution["category_latency"],
                "progress_state": self._progress.state,
                "progress_transitions": len(progress_transitions),
                "progress_frame_deliveries": len(progress_fact_deliveries),
                "progress_frame_chars_sent": sum(
                    int(row.get("chars") or 0) for row in progress_fact_deliveries
                ),
                "progress_frame_late_deliveries": sum(
                    bool(row.get("one_step_late")) for row in progress_fact_deliveries
                ),
                "progress_frame_predictive_deliveries": sum(
                    not bool(row.get("not_predictive")) for row in progress_fact_deliveries
                ),
                "task_progress_changes": task_progress_changes,
                "activity_events": activity_events,
                "semantic_progress_kinds": dict(semantic_progress_kinds),
                "progress_observations": len(progress_observations),
                "progress_distinct_attempts": len(
                    {row["attempt_id"] for row in progress_observations}
                ),
                "progress_distinct_observations": len(
                    {row["observation_id"] for row in progress_observations}
                ),
                "progress_observation_gains": sum(
                    bool(row["observation_gain"]) for row in progress_observations
                ),
                "progress_task_gains": sum(
                    bool(row["task_progress_gain"]) for row in progress_observations
                ),
                "progress_same_state_updates_suppressed": (
                    self._progress.same_state_updates_suppressed
                ),
                "failed_read_anchors_not_consumed": failed_read_anchors_not_consumed,
                "valid_nonzero_observations": valid_nonzero_observations,
                "deadline_configured": effective_budget is not None,
                "execution_budget_sec": effective_budget,
                "deadline_reserve_sec": self.deadline_reserve_sec,
                "deadline_reserve_exits": deadline_reserve_exits,
                "action_timeout_decisions": action_timeout_decisions,
                "declared_validator_proposals": declared_validator_proposals,
                "declared_validators_with_redirection": (
                    declared_validators_with_redirection
                ),
                "declared_validators_preserved_with_redirection": (
                    declared_validators_preserved_with_redirection
                ),
                "adaptive_validation_timeouts": sum(
                    row.get("reason") == "literal_validation_timeout"
                    for row in action_timeout_decisions
                ),
                "default_validation_timeouts": sum(
                    row.get("operation") == ActionOperation.VALIDATE.value
                    and row.get("reason") == "default_command_timeout"
                    for row in action_timeout_decisions
                ),
                "model_action_timeouts": model_action_timeouts,
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
                "preemptive_retrieval_enabled": int(
                    self.enable_preemptive_retrieval
                ),
                "preemptive_retrieval_calls": len(preemptive_retrieval_decisions),
                "preemptive_retrieval_selected_calls": sum(
                    row.get("status") in {"selected", "prepared", "delivered"}
                    for row in preemptive_retrieval_decisions
                ),
                "preemptive_retrieval_abstained_calls": sum(
                    row.get("status") == "abstained"
                    for row in preemptive_retrieval_decisions
                ),
                "preemptive_retrieval_budget_closed_calls": sum(
                    "task_character_budget_closed_precheck"
                    in set(row.get("reason_codes") or ())
                    for row in preemptive_retrieval_decisions
                ),
                "preemptive_retrieval_cache_hits": sum(
                    bool(row.get("cache_hit"))
                    for row in preemptive_retrieval_decisions
                ),
                "preemptive_retrieval_cache_misses": sum(
                    not bool(row.get("cache_hit"))
                    and row.get("status")
                    not in {"disabled"}
                    and bool(row.get("cache_key"))
                    for row in preemptive_retrieval_decisions
                ),
                "preemptive_retrieval_opportunities": len(
                    preemptive_retrieval_decisions
                ),
                "preemptive_retrieval_candidate_opportunities": sum(
                    bool(row.get("ranked_files"))
                    for row in preemptive_retrieval_decisions
                ),
                "preemptive_retrieval_model_visible_opportunities": sum(
                    row.get("status") == "delivered"
                    and bool(
                        (row.get("delivery_receipt") or {}).get(
                            "request_payload_sha256"
                        )
                    )
                    for row in preemptive_retrieval_decisions
                ),
                "preemptive_retrieval_deliveries": len(
                    preemptive_retrieval_deliveries
                ),
                "preemptive_retrieval_ranked_files": sum(
                    len(row.get("ranked_files") or ())
                    for row in preemptive_retrieval_decisions
                ),
                "preemptive_retrieval_selected_evidence": sum(
                    len(row.get("selected_evidence") or ())
                    for row in preemptive_retrieval_decisions
                ),
                "preemptive_retrieval_claims_delivered": len(
                    delivered_preemptive_claim_ids
                ),
                "preemptive_retrieval_duplicate_claims": (
                    sum(
                        len(row.get("claim_ids") or ())
                        for row in preemptive_retrieval_deliveries
                    )
                    - len(delivered_preemptive_claim_ids)
                ),
                "preemptive_retrieval_chars_added": (
                    preemptive_retrieval_chars_delivered
                ),
                "preemptive_retrieval_task_budget_chars": (
                    self.preemptive_retrieval_task_budget_chars
                ),
                "preemptive_retrieval_priority_reserve_chars": (
                    self.preemptive_retrieval_priority_reserve_chars
                ),
                "preemptive_retrieval_budget_remaining_chars": max(
                    0,
                    self.preemptive_retrieval_task_budget_chars
                    - preemptive_retrieval_chars_delivered,
                ),
                "preemptive_retrieval_late_deliveries": sum(
                    bool(row.get("one_step_late"))
                    for row in preemptive_retrieval_deliveries
                ),
                "preemptive_retrieval_predictive_deliveries": sum(
                    bool(row.get("predictive"))
                    for row in preemptive_retrieval_deliveries
                ),
                "preemptive_retrieval_latency_ms": {
                    "p50": _percentile(
                        [
                            float(row.get("latency_ms") or 0.0)
                            for row in preemptive_retrieval_decisions
                        ],
                        0.50,
                    ),
                    "p95": _percentile(
                        [
                            float(row.get("latency_ms") or 0.0)
                            for row in preemptive_retrieval_decisions
                        ],
                        0.95,
                    ),
                    "p99": _percentile(
                        [
                            float(row.get("latency_ms") or 0.0)
                            for row in preemptive_retrieval_decisions
                        ],
                        0.99,
                    ),
                },
                "preemptive_dense_backend_available": int(
                    self._preemptive_dense_backend is not None
                ),
                "preemptive_dense_backend_error": (
                    self._preemptive_dense_backend_error
                ),
                "contribution_compiler_candidates": sum(
                    int(row.get("candidate_count") or 0)
                    for row in contribution_compilations
                ),
                "contribution_compiler_accounted": sum(
                    int(row.get("accounted_count") or 0)
                    for row in contribution_compilations
                ),
                "contribution_compiler_selected": sum(
                    len(row.get("selected_ids") or ())
                    for row in contribution_compilations
                ),
                "contribution_compiler_duplicate_suppressions": sum(
                    str(item.get("disposition") or "").startswith("duplicate_")
                    for row in contribution_compilations
                    for item in row.get("accounting") or ()
                ),
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
                "semantic_source_revision_complete": int(source_receipt.complete),
                "semantic_source_paths": len(source_receipt.source_paths),
                "semantic_source_missing_digests": len(
                    source_receipt.missing_digest_paths
                ),
                "graph_source_revision_complete": int(graph_receipt.complete),
                "graph_source_paths": len(graph_receipt.source_paths),
                "graph_source_missing_digests": len(graph_receipt.missing_digest_paths),
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
                "repository_action_queries": sum(
                    row.get("mode") == "action_query"
                    for row in (
                        repository_session.refresh_log if repository_session is not None else ()
                    )
                ),
                "repository_action_query_cache_hits": sum(
                    row.get("mode") == "action_query_cache_hit"
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
                "decision_sufficiency_calls": len(decision_sufficiency_receipts),
                "decision_sufficiency_return_eligible": sum(
                    row.get("disposition") == "return_eligible"
                    for row in decision_sufficiency_receipts
                ),
                "decision_sufficiency_returns_applied": sum(
                    row.get("applied_disposition") == "return_to_model"
                    for row in decision_sufficiency_receipts
                ),
                "decision_sufficiency_existing_visibility_passes": sum(
                    "evidence_already_provider_visible"
                    in (row.get("reason_codes") or ())
                    for row in decision_sufficiency_receipts
                ),
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
                "guidance_private_effects": feature_summary[
                    "feature_delivery_disposition_counts"
                ].get("private_ineligible", 0),
                "guidance_delivery_dispositions": dict(
                    feature_summary["feature_delivery_disposition_counts"]
                ),
                "legacy_guidance_suppressed_counter": feature_summary[
                    "legacy_guidance_suppressed_counter"
                ],
                "gt_context_chars_added": sum(
                    int(row.get("runtime_advisory_chars") or 0)
                    for row in dispatched_model_call_contexts
                ),
                "preemptive_retrieval_context_chars_added": sum(
                    int(row.get("preemptive_retrieval_chars") or 0)
                    for row in dispatched_model_call_contexts
                ),
                "context_state_frame_chars_added": sum(
                    int((row.get("context_compiler") or {}).get("active_state_chars") or 0)
                    for row in dispatched_model_call_contexts
                ),
                "progress_frame_chars_added": sum(
                    int(row.get("progress_frame_chars") or 0)
                    for row in dispatched_model_call_contexts
                ),
                "total_gt_context_chars_added": sum(
                    int(row.get("runtime_advisory_chars") or 0)
                    + int(row.get("preemptive_retrieval_chars") or 0)
                    + int(row.get("context_frontier_chars") or 0)
                    + int(row.get("progress_frame_chars") or 0)
                    + int((row.get("context_compiler") or {}).get("active_state_chars") or 0)
                    for row in dispatched_model_call_contexts
                ),
                "newly_inserted_context_chars": sum(
                    int(row.get("runtime_advisory_chars") or 0)
                    + int(row.get("preemptive_retrieval_chars") or 0)
                    + int(row.get("context_frontier_chars") or 0)
                    + int(row.get("progress_frame_chars") or 0)
                    + int((row.get("context_compiler") or {}).get("active_state_chars") or 0)
                    for row in dispatched_model_call_contexts
                ),
                "represented_context_facts": sum(
                    int(row.get("context_facts_represented") or 0)
                    for row in dispatched_model_call_contexts
                ),
                "stock_context_chars_sent": sum(
                    int(row.get("stock_context_chars") or 0)
                    for row in dispatched_model_call_contexts
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
                    "model_stats": {
                        "instance_cost": cost,
                        "api_calls": model_query_invocations,
                    },
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
            replay_bundle_metadata = replay_bundle.finalize()
            (self.logs_dir / "central_receipt.json").write_text(
                json.dumps(
                    {
                        "schema": "central-runtime-receipt-v3",
                        "mode": self.runtime_mode,
                        "integration_mode": self.integration_mode.value,
                        "policy_mode": self.policy_mode.value,
                        "preflight_mode": self.preflight_mode.value,
                        "provider_route": _provider_route_configuration(model),
                        "component_configuration": {
                            "feature_guidance": self.enable_feature_guidance,
                            "context_frontier": self.enable_context_frontier,
                            "context_compaction": self.enable_context_compaction,
                            "completion_controller": self.enable_completion_controller,
                            "progress_control": self.enable_progress_control,
                            "adaptive_validation_timeout": (
                                self.enable_adaptive_validation_timeout
                            ),
                            "replay_capture": self.enable_replay_capture,
                            "lint": self.enable_lint,
                            "repository_intelligence": self.enable_repository_intelligence,
                            "repository_initial_index_timeout_sec": (
                                self.repository_initial_index_timeout_sec
                            ),
                            "repository_refresh_timeout_sec": (
                                self.repository_refresh_timeout_sec
                            ),
                            "preemptive_retrieval": self.enable_preemptive_retrieval,
                            "decision_sufficiency": self.enable_decision_sufficiency,
                            "preemptive_retrieval_token_budget": (
                                self.preemptive_retrieval_token_budget
                            ),
                            "preemptive_retrieval_task_budget_chars": (
                                self.preemptive_retrieval_task_budget_chars
                            ),
                            "preemptive_retrieval_priority_reserve_chars": (
                                self.preemptive_retrieval_priority_reserve_chars
                            ),
                            "preemptive_retrieval_timeout_sec": (
                                self.preemptive_retrieval_timeout_sec
                            ),
                            "preemptive_retrieval_cold_start_timeout_sec": (
                                self.preemptive_retrieval_cold_start_timeout_sec
                            ),
                            "preemptive_retrieval_dense_candidate_limit": (
                                self.preemptive_retrieval_dense_candidate_limit
                            ),
                            "preemptive_retrieval_dense_model_configured": bool(
                                self.preemptive_retrieval_model_dir
                            ),
                            "graph_required": self.require_graph_ready,
                        },
                        "calls": model_query_invocations,
                        "provider_requests_prepared": provider_requests_prepared,
                        "actions": actions_count,
                        "elapsed_seconds": elapsed_seconds,
                        "workspace_sensor_healthy": snapshot.healthy,
                        "workspace_sensor_reason": snapshot.reason,
                        "workspace_capture_backend": self._sensor.capture_backend,
                        "task_working_directory": dict(self._cwd_receipt),
                        "source_revision": source_revision,
                        "semantic_source_revision": {
                            "revision": source_receipt.revision,
                            "complete": source_receipt.complete,
                            "source_paths": list(source_receipt.source_paths),
                            "missing_digest_paths": list(
                                source_receipt.missing_digest_paths
                            ),
                        },
                        "graph_source_revision": {
                            "revision": graph_receipt.revision,
                            "complete": graph_receipt.complete,
                            "source_paths": list(graph_receipt.source_paths),
                            "missing_digest_paths": list(
                                graph_receipt.missing_digest_paths
                            ),
                        },
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
                        "project_validation": {
                            "discovered_checks": list(
                                repository_evidence.project_checks
                            ),
                            "probes": project_validation_probes,
                        },
                        "progress": {
                            "state": self._progress.state,
                            "transitions": progress_transitions,
                            "observations": progress_observations,
                            "same_state_updates_suppressed": (
                                self._progress.same_state_updates_suppressed
                            ),
                            "fact_deliveries": progress_fact_deliveries,
                            "pending_fact": (
                                None
                                if pending_progress_fact is None
                                else {
                                    "fact_id": pending_progress_fact.fact_id,
                                    "eligible_call": pending_progress_fact.eligible_call,
                                    "evidence_action": pending_progress_fact.evidence_action,
                                }
                            ),
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
                        "preemptive_retrieval": {
                            "schema": "gt.preemptive_retrieval_runtime.v1",
                            "enabled": self.enable_preemptive_retrieval,
                            "decisions": preemptive_retrieval_decisions,
                            "deliveries": preemptive_retrieval_deliveries,
                            "delivered_claim_ids": sorted(
                                delivered_preemptive_claim_ids
                            ),
                            "opportunity_accounting": (
                                _preemptive_opportunity_accounting(
                                    preemptive_retrieval_decisions
                                )
                            ),
                            "dense_backend": (
                                {
                                    "available": True,
                                    **self._preemptive_dense_backend.receipt(),
                                }
                                if self._preemptive_dense_backend is not None
                                else None
                            ),
                            "dense_backend_error": (
                                self._preemptive_dense_backend_error
                            ),
                        },
                        "decision_sufficiency": {
                            "schema": "gt.decision_sufficiency_runtime.v1",
                            "enabled": self.enable_decision_sufficiency,
                            "decisions": decision_sufficiency_receipts,
                        },
                        "contribution_compiler": {
                            "schema": "gt.contribution_compiler.runtime.v1",
                            "calls": contribution_compilations,
                            "candidate_count": sum(
                                int(row.get("candidate_count") or 0)
                                for row in contribution_compilations
                            ),
                            "accounted_count": sum(
                                int(row.get("accounted_count") or 0)
                                for row in contribution_compilations
                            ),
                        },
                        "host_execution": host_execution,
                        "features": feature_summary,
                        "certification_decisions": certification_decisions,
                        "interventions": receipts,
                        "guidance_deliveries": guidance_deliveries,
                        "provider_evidence": provider_evidence_summary,
                        "model_call_contexts": model_call_contexts,
                        "replay_bundle": replay_bundle_metadata,
                        "replay_state": replay_bundle_metadata,
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
                calls=model_query_invocations,
            )
            context.n_input_tokens = input_tokens
            context.n_output_tokens = output_tokens
            context.n_cache_tokens = cache_tokens
            context.cost_usd = cost
            context.metadata = {
                "runtime_mode": self.runtime_mode,
                "integration_mode": self.integration_mode.value,
                "policy_mode": self.policy_mode.value,
                "api_calls": model_query_invocations,
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
