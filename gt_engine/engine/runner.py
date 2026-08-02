"""Inline Engine runner (IE-02, IE-03, IE-04, IE-05, IE-08).

The ENGINE-mode action-to-observation executor. When a ``GTSession`` is in
``GTMode.ENGINE`` every selected action is normalized to an ``ActionRequest``,
bound to the current repository snapshot, decided by the five-decision law,
executed literally or deterministically, compiled into one canonical
observation, and bound to the provider exchange via a ``DeliveryReceipt``.

Fail-open: any engine fault degrades the session; the host then executes stock
Mini-SWE literally. The engine never selects the next action.

Raw-required observations retain exact raw bytes. Typed actions whose decision
is PASS_THROUGH now execute a literal fallback shell command (historical
behavior dropped it without executing anything).
"""
from __future__ import annotations

import hashlib
import json
import shlex
from typing import Any, Mapping

from .contracts import (
    ActionKind,
    ActionRequest,
    CanonicalObservation,
    Decision,
    DeliveryReceipt,
    EvidenceArtifact,
    FactOwnerRegistration,
    Fidelity,
    InterceptionDecision,
    RepositorySnapshot,
)
from .decide import AnalyzerState, decide
from .observe import compile_observation

# Registered FACT byte owners the ENGINE path may render. Only owners listed
# here may add model-visible deterministic bytes (IE-10 gate).
ENGINE_FACT_OWNERS: dict[str, FactOwnerRegistration] = {
    "lexical_FTS5": FactOwnerRegistration(
        owner="lexical_FTS5", role="FACT", producer="exact_literal_search",
        producer_version="1", semantics="exact token/literal search",
        freshness_authority="repository_revision", model_visible=True,
    ),
    "syntax_result": FactOwnerRegistration(
        owner="syntax_result", role="FACT", producer="py_ast",
        producer_version="1", semantics="immediate per-file syntax evidence",
        freshness_authority="repository_revision", model_visible=True,
    ),
    "verification_status": FactOwnerRegistration(
        owner="verification_status", role="FACT", producer="execution_evidence",
        producer_version="1", semantics="execution-specific verification result",
        freshness_authority="repository_revision", model_visible=True,
    ),
}


def _args_get(args: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = args.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return ""


def classify_shell(command: str) -> ActionKind:
    """Conservative typed classification of a literal shell command.

    Only clearly read-only commands are typed; everything else stays SHELL
    (opaque/compound/mixed passes through literally).
    """
    stripped = command.strip().lstrip("$")
    head = stripped.split(" ", 1)[0].strip()
    base = head.split("/")[-1]
    if base in {"cat", "less", "more", "head", "tail", "view"} and "|" not in stripped and not any(
        c in stripped for c in (">", ">>", "|", "&", ";", "&&", "||")
    ):
        return ActionKind.FILE_READ
    if base in {"grep", "rg", "ack", "ag"} and not any(
        c in stripped for c in (">", ">>", "|", "&", ";", "&&", "||")
    ):
        return ActionKind.SEARCH
    return ActionKind.SHELL


def fallback_shell_for_typed(kind: str, args: Mapping[str, Any]) -> str:
    """Literal shell fallback for a typed action whose decision is PASS_THROUGH.

    Historical behavior dropped the typed action without executing anything;
    the ENGINE executes a literal equivalent so no selected action disappears.
    Returns "" when no safe literal equivalent exists (the observation then
    declares an incomplete result and Mini-SWE chooses another action).
    """
    if kind == "exact_literal_search":
        literal = _args_get(args, "literal", "query", "pattern", "text")
        if not literal:
            return ""
        scope = _args_get(args, "paths", "path", "scope") or "."
        return f"grep -R -F -- {shlex.quote(literal)} {shlex.quote(scope)}"
    if kind == "syntax":
        path = _args_get(args, "path", "file", "extension")
        if not path or path.startswith("."):
            return ""
        return f"python3 -m py_compile {shlex.quote(path)}"
    return ""


def normalize_action(
    action: Mapping[str, Any],
    *,
    repo_root: str,
    configuration_digest: str,
    snapshot_token: str,
    batch_id: str,
    sequence_position: int,
) -> ActionRequest:
    """Normalize one selected action into an ActionRequest.

    Binds action id, typed kind, exact arguments, literal shell form, snapshot
    token, configuration digest, fidelity, batch id, and sequence position.
    """
    tool_call_id = str(action.get("tool_call_id") or "")
    gt_action = action.get("gt_action") or {}
    kind_raw = str(gt_action.get("kind") or "")
    arguments = dict(gt_action.get("arguments") or {})
    if kind_raw:
        kind = _typed_kind(kind_raw)
        literal_shell = fallback_shell_for_typed(kind_raw, arguments)
        return ActionRequest(
            action_id=tool_call_id or f"{batch_id}-{sequence_position}",
            kind=kind,
            arguments=arguments,
            literal_shell_form=literal_shell,
            snapshot_token=snapshot_token,
            configuration_digest=configuration_digest,
            requested_fidelity=_fidelity(gt_action.get("requested_fidelity", "raw")),
            batch_id=batch_id,
            sequence_position=sequence_position,
            raw_fallback=True,
        )
    command = _command_text(action)
    return ActionRequest(
        action_id=tool_call_id or f"{batch_id}-{sequence_position}",
        kind=classify_shell(command),
        arguments={},
        literal_shell_form=command,
        snapshot_token=snapshot_token,
        configuration_digest=configuration_digest,
        requested_fidelity=Fidelity.RAW,
        batch_id=batch_id,
        sequence_position=sequence_position,
        raw_fallback=True,
    )


def _command_text(action: Mapping[str, Any]) -> str:
    value = action.get("command")
    if isinstance(value, str):
        return value
    return str(value or "")


def _typed_kind(kind_raw: str) -> ActionKind:
    mapping = {
        "exact_literal_search": ActionKind.SEARCH,
        "syntax": ActionKind.SYNTAX_QUERY,
        "verification_status": ActionKind.RUN_VERIFICATION,
        "definition": ActionKind.SYMBOL_DEFINITIONS,
        "references": ActionKind.SYMBOL_REFERENCES,
        "callers": ActionKind.SYMBOL_CALLERS,
        "patch_impact": ActionKind.SEARCH,
    }
    return mapping.get(kind_raw, ActionKind.SHELL)


def _fidelity(value: str | None) -> Fidelity:
    try:
        return Fidelity(str(value or "raw"))
    except ValueError:
        return Fidelity.RAW


def _typed_compiled(typed_result: Mapping[str, Any] | None) -> dict[str, Any]:
    """Parse the typed producer's compiled observation JSON."""
    if typed_result is None:
        return {}
    try:
        value = json.loads(str(typed_result.get("output") or "{}"))
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def _direct_answer(typed_result: Mapping[str, Any] | None) -> str:
    compiled = _typed_compiled(typed_result)
    answer = compiled.get("direct_answer")
    return str(answer) if answer else ""


def _typed_omissions(typed_result: Mapping[str, Any] | None) -> tuple[str, ...]:
    compiled = _typed_compiled(typed_result)
    evidence = compiled.get("evidence") or {}
    if isinstance(evidence, dict):
        return tuple(str(x) for x in evidence.get("omissions") or ())
    return ()


def build_analyzer_state(
    request: ActionRequest,
    *,
    repository_revision: str,
    graph_fresh: bool,
    graph_available: bool,
    typed_result: Mapping[str, Any] | None,
) -> AnalyzerState:
    """Deterministic analyzer facts at decision time."""
    kind = request.kind
    is_test = kind in (ActionKind.RUN_VERIFICATION, ActionKind.SYNTAX_QUERY)
    omissions = _typed_omissions(typed_result)
    certified = not bool(omissions)
    return AnalyzerState(
        current_revision=repository_revision,
        stale=not graph_fresh,
        analyzer_incomplete=not graph_available,
        ambiguous=not graph_fresh and graph_available,
        configuration_sensitive=True,
        is_test_or_build=is_test,
        certified_replacement=certified,
        replacement_complete=certified,
        replacement_fresh=graph_fresh,
        pre_side_effect=kind == ActionKind.SUBMIT,
    )


def snapshot_token_for(
    repository_revision: str,
    repo_root: str,
    workspace_fingerprint: Mapping[str, Any] | None,
    configuration_digest: str,
) -> str:
    """Content-addressed snapshot token binding revision + dirty state."""
    snapshot = RepositorySnapshot(
        revision_heads={"HEAD": repository_revision or ""},
        dirty_files=dict(workspace_fingerprint or {}),
        untracked_files=(),
        configuration_digest=configuration_digest,
    )
    return snapshot.token()


def configuration_digest_for(repo_root: str, graph_db: str, repository_revision: str) -> str:
    digest = f"{repo_root}::{graph_db}::{repository_revision}"
    return hashlib.sha256(digest.encode("utf-8")).hexdigest()


def classify_batch_barriers(
    requests: tuple[ActionRequest, ...],
) -> tuple[int, ...]:
    """Sequential dependency barriers (IE-08).

    Any mutation, build, test, submit, or snapshot-sensitive replacement in a
    batch forces later actions to observe preceding state changes. Returns the
    sequence positions AFTER which a barrier must be placed (i.e. positions of
    barrier-creating actions themselves).
    """
    barrier_kinds = {
        ActionKind.SHELL,
        ActionKind.CREATE_PROPOSAL,
        ActionKind.EDIT_PROPOSAL,
        ActionKind.COMMIT_MUTATION,
        ActionKind.RUN_VERIFICATION,
        ActionKind.SUBMIT,
    }
    barriers: list[int] = []
    for index, request in enumerate(requests, start=1):
        if request.kind in barrier_kinds:
            barriers.append(index)
    return tuple(barriers)


# ---------------------------------------------------------------------------
# Seam executor (Mini-SWE integration)
# ---------------------------------------------------------------------------


def _typed_evidence(request: ActionRequest, typed_result: Mapping[str, Any] | None) -> tuple[EvidenceArtifact, ...]:
    """Wrap a typed producer's compiled observation as FACT evidence."""
    compiled = _typed_compiled(typed_result)
    evidence = compiled.get("evidence") or {}
    semantics = str(evidence.get("semantics") or "typed result") if isinstance(evidence, dict) else "typed result"
    omissions = _typed_omissions(typed_result)
    answer = _direct_answer(typed_result)
    if request.kind == ActionKind.RUN_VERIFICATION:
        owner = "verification_status"
    elif request.kind == ActionKind.SYNTAX_QUERY:
        owner = "syntax_result"
    else:
        owner = "lexical_FTS5"
    artifact_id = hashlib.sha256(
        f"{request.action_id}::{request.kind.value}".encode("utf-8")
    ).hexdigest()[:16]
    return (
        EvidenceArtifact(
            artifact_id=artifact_id,
            owner=owner,
            semantics=semantics,
            content={"answer": answer, "omissions": list(omissions)},
            producer="engine.typed",
            producer_version="1",
            freshness_revision=request.snapshot_token,
            coverage="complete" if not omissions else "incomplete",
            omissions=omissions,
            model_visible=bool(answer),
        ),
    )


def _execute_and_observe(
    request: ActionRequest,
    decision: InterceptionDecision,
    action: Mapping[str, Any],
    typed_result: Mapping[str, Any] | None,
    is_typed: bool,
    adapter: Any,
    session: Any,
    environment: Any,
    rt: Any,
) -> tuple[CanonicalObservation, int]:
    """Execute per decision and compile one canonical observation.

    Returns (observation, returncode).
    """
    from ..miniswe_runtime import _observation_output, _returncode

    if decision.decision == Decision.SUPPRESS:
        return compile_observation(request, decision, raw_exact=False), 2

    if decision.decision == Decision.REPLACE and typed_result is not None:
        answer = _direct_answer(typed_result)
        observation = compile_observation(
            request, decision, replaced=answer, evidence=_typed_evidence(request, typed_result)
        )
        return observation, 0

    if is_typed:
        answer = _direct_answer(typed_result)
        fallback = request.literal_shell_form
        if fallback and not answer:
            # PASS_THROUGH fix: a typed action with no certified answer now
            # executes its literal fallback command instead of dropping it.
            result = environment.execute({"cmd": fallback, "tool_call_id": request.action_id})
            raw = _observation_output(result)
            rc = _returncode(result)
            observation = compile_observation(
                request, decision,
                raw_result=raw, raw_exact=True,
                evidence=_typed_evidence(request, typed_result),
                fallback_notice="typed action executed as a literal fallback command",
            )
            return observation, rc or 0
        observation = compile_observation(
            request, decision,
            raw_result=answer, raw_exact=bool(answer),
            evidence=_typed_evidence(request, typed_result),
            fallback_notice="" if answer else "typed action produced no answer; select another action",
        )
        return observation, 0 if answer else 2

    result = environment.execute(action)
    raw = _observation_output(result)
    rc = _returncode(result)
    observation = compile_observation(
        request, decision, raw_result=raw, raw_exact=True
    )
    return observation, rc or 0


def _delivery_receipt(
    request: ActionRequest,
    decision: InterceptionDecision,
    observation: CanonicalObservation,
    adapter: Any,
) -> DeliveryReceipt:
    """Bind the delivered observation to the provider exchange (IE-05)."""
    import uuid

    latest = getattr(adapter, "_latest_delivery", None)
    request_id = (
        getattr(latest, "request_id", "")
        or getattr(adapter, "last_provider_request_id", "")
        or getattr(adapter, "provider_request_id", "")
        or ""
    )
    response_id = (
        getattr(latest, "provider_response_id", "")
        or getattr(adapter, "last_provider_response_id", "")
        or getattr(adapter, "provider_response_id", "")
        or ""
    )
    return DeliveryReceipt(
        delivery_id=uuid.uuid4().hex[:16],
        action_request=request,
        pre_state_hash=request.snapshot_token,
        raw_result_hash=hashlib.sha256(observation.raw_result.encode("utf-8")).hexdigest(),
        transformation_version="1.0",
        final_observation_bytes=observation.render(),
        provider_request_id=str(request_id),
        provider_response_id=str(response_id),
    )


def engine_execute_actions(
    agent: Any,
    message: dict,
    *,
    session: Any,
    adapter: Any,
    model: Any,
    environment: Any,
    original_execute: Any = None,
) -> list[dict]:
    """ENGINE-mode replacement for the Mini-SWE ``execute_actions`` seam.

    Normalizes every selected action, decides it, executes it literally or
    deterministically, compiles one canonical observation per action, and
    records a delivery receipt. Fail-open: any fault degrades the session and
    falls back to stock execution.
    """
    from .. import miniswe_runtime as rt
    from ..miniswe_typed_actions import execute_typed_action_fail_open, is_typed_action

    if session.disabled:
        return original_execute(message) if callable(original_execute) else []

    actions = tuple((message.get("extra") or {}).get("actions") or ())
    if not actions:
        return original_execute(message) if callable(original_execute) else []

    repo_root = adapter.repo_root or os.getcwd()
    cfg_digest = configuration_digest_for(
        repo_root, str(adapter.graph_db or ""), adapter.repository_revision
    )
    workspace_fingerprint = rt._workspace_fingerprint(repo_root)
    snapshot_token = snapshot_token_for(
        adapter.repository_revision, repo_root, workspace_fingerprint, cfg_digest
    )

    batch_id = f"b{adapter.global_action + 1}"
    requests = tuple(
        normalize_action(
            action,
            repo_root=repo_root,
            configuration_digest=cfg_digest,
            snapshot_token=snapshot_token,
            batch_id=batch_id,
            sequence_position=sequence,
        )
        for sequence, action in enumerate(actions, start=1)
    )
    classify_batch_barriers(requests)  # barriers are honored by sequential execution

    outputs: list[dict] = []
    directives: list[dict] = []
    for action, request in zip(actions, requests):
        typed_result = None
        is_typed = is_typed_action(action)
        if is_typed:
            try:
                _, typed_result = execute_typed_action_fail_open(
                    action,
                    repo_root=repo_root,
                    configuration={
                        "graph_db": adapter.graph_db if adapter.graph_fresh else "",
                        "graph_fresh": adapter.graph_fresh,
                        "repository_revision": adapter.repository_revision,
                        "gt_mode": session.mode.value,
                    },
                )
            except Exception as exc:  # noqa: BLE001 - engine failure is fail-open
                session.degrade("engine_typed", exc)
                typed_result = None
        if session.disabled:
            return original_execute(message) if callable(original_execute) else []

        state = build_analyzer_state(
            request,
            repository_revision=adapter.repository_revision,
            graph_fresh=adapter.graph_fresh,
            graph_available=bool(adapter.graph_db),
            typed_result=typed_result,
        )
        decision = decide(request, (), ENGINE_FACT_OWNERS, state)

        if request.kind == ActionKind.SUBMIT and not _submit_allowed(request, session, adapter, rt):
            decision = InterceptionDecision(
                decision=Decision.SUPPRESS,
                reason="certified closed-scope blocker",
                eligibility=("submit",),
            )

        observation, returncode = _execute_and_observe(
            request, decision, action, typed_result, is_typed,
            adapter, session, environment, rt,
        )
        rendered = observation.render()
        outputs.append({
            "output": rendered,
            "returncode": returncode,
            "extra": {
                "gt_engine": True,
                "engine_decision": decision.decision.value,
                "canonical_observation_sha256": hashlib.sha256(
                    rendered.encode("utf-8")
                ).hexdigest(),
            },
        })
        if decision.decision == Decision.SUPPRESS:
            directives.append(rt._refusal_directive(adapter))

        try:
            receipt = _delivery_receipt(request, decision, observation, adapter)
            if getattr(adapter, "store", None) is not None:
                adapter.store.append(
                    "engine_delivery",
                    schema="gt.engine.delivery_receipt.v1",
                    delivery_id=receipt.delivery_id,
                    action_id=request.action_id,
                    decision=decision.decision.value,
                    final_observation_sha256=receipt.hash(),
                )
        except Exception:  # noqa: BLE001 - receipt failure is fail-open
            pass

    formatter = getattr(model, "format_observation_messages", None)
    if callable(formatter):
        formatted = list(formatter(message, outputs, agent.get_template_vars()))
        return agent.add_messages(*formatted, *directives)
    return [*outputs, *directives]


def _submit_allowed(request: ActionRequest, session: Any, adapter: Any, rt: Any) -> bool:
    if request.kind != ActionKind.SUBMIT:
        return True
    try:
        return rt._run_submit_gate(session, request.literal_shell_form)
    except Exception:  # noqa: BLE001 - policy is fail-open
        return True
