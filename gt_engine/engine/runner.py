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
import os
import re
import shlex
from pathlib import Path
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
# here may add model-visible deterministic bytes (IE-10 gate). Owners are FACT
# identities from the 129-row inventory (ACQ rows stay internal; CAP rows are
# lineage; PERF rows are passive). The full DIRECT set is registered so the
# gateway's producers can fire every feature on its trigger; caller_contract is
# REMOVE by disposition and stays absent.
ENGINE_FACT_OWNERS: dict[str, FactOwnerRegistration] = {
    "def_partition": FactOwnerRegistration(
        owner="def_partition", role="FACT", producer="exact_literal_search",
        producer_version="1", semantics="typed definition/partition search result",
        freshness_authority="repository_revision", model_visible=True,
    ),
    "syntax_result": FactOwnerRegistration(
        owner="syntax_result", role="FACT", producer="py_ast",
        producer_version="1", semantics="immediate per-file syntax evidence",
        freshness_authority="repository_revision", model_visible=True,
    ),
    "covering_red": FactOwnerRegistration(
        owner="covering_red", role="FACT", producer="execution_evidence",
        producer_version="1", semantics="execution-specific verification result",
        freshness_authority="repository_revision", model_visible=True,
    ),
    "obligations": FactOwnerRegistration(
        owner="obligations", role="FACT", producer="contract_delta",
        producer_version="1", semantics="task obligation spans bound to an action",
        freshness_authority="repository_revision", model_visible=True,
    ),
    "localization": FactOwnerRegistration(
        owner="localization", role="FACT", producer="ranked_localization",
        producer_version="1", semantics="action-keyed ranked repository localization",
        freshness_authority="repository_revision", model_visible=True,
    ),
    "recovery": FactOwnerRegistration(
        owner="recovery", role="FACT", producer="failure_identity",
        producer_version="1", semantics="exact repeated-failure recovery evidence",
        freshness_authority="repository_revision", model_visible=True,
    ),
    "signature_delta": FactOwnerRegistration(
        owner="signature_delta", role="FACT", producer="patch_delta",
        producer_version="1", semantics="exact post-edit signature delta",
        freshness_authority="repository_revision", model_visible=True,
    ),
    "newfile_precedent": FactOwnerRegistration(
        owner="newfile_precedent", role="FACT", producer="change_surface",
        producer_version="1", semantics="provenance-rich new-file precedent",
        freshness_authority="repository_revision", model_visible=True,
    ),
    "submit_refusal": FactOwnerRegistration(
        owner="submit_refusal", role="FACT", producer="submit_gate",
        producer_version="1", semantics="certified fresh closed-scope submit blocker",
        freshness_authority="repository_revision", model_visible=True,
    ),
}

# groundtruth gateway evidence_type -> registered FACT owner (the real
# evidence_type strings the gateway emits, not the producer names).
_EVIDENCE_TO_OWNER: dict[str, str] = {
    "covering_verdict": "covering_red",
    "patch_delta": "signature_delta",
    "signature_mismatch": "signature_delta",
    "localization": "localization",
    "ranked_localization": "localization",
    "def_ref_partition": "def_partition",
    "new_file_destination": "newfile_precedent",
    "companion_surface": "newfile_precedent",
    "obligations": "obligations",
    # caller_contract is REMOVE by disposition -> not mapped (never rendered).
    # body_concept / trace_frame / name_fold / wrong_surface are advisory
    # classes; body folds into def_partition knowledge, trace into recovery.
    "body_concept": "def_partition",
    "trace_frame": "recovery",
    "name_fold": "def_partition",
    "wrong_surface": "localization",
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
    normalized = str(value or "raw").strip().lower()
    if normalized in {"sound_overapprox", "sound-overapprox"}:
        normalized = "sound_overapproximate"
    try:
        return Fidelity(normalized)
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
        owner = "covering_red"
    elif request.kind == ActionKind.SYNTAX_QUERY:
        owner = "syntax_result"
    else:
        owner = "def_partition"
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


def _tool_output(observation: CanonicalObservation, returncode: int) -> dict[str, Any]:
    """Build the Mini-SWE tool-result dict for one engine observation.

    Must match the shape Mini-SWE's formatter renders: ``output``,
    ``returncode``, ``exception_info`` (the Jinja template accesses it as an
    attribute and a missing key raises), and ``extra``.
    """
    rendered = observation.render()
    return {
        "output": rendered,
        "returncode": returncode,
        "exception_info": "",
        "extra": {
            "gt_engine": True,
            "engine_decision": observation.decision.decision.value,
            "canonical_observation_sha256": hashlib.sha256(
                rendered.encode("utf-8")
            ).hexdigest(),
        },
    }


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
    facts = _postflight_facts(
        request, command=request.literal_shell_form, raw=raw, returncode=rc,
        repo_root=getattr(adapter, "repo_root", "") or os.getcwd(),
        adapter=adapter,
    )
    if facts and decision.decision == Decision.PASS_THROUGH:
        # Postflight deterministic facts joined -> the decision is AUGMENT:
        # raw preserved exactly, evidence attached to the same observation.
        decision = InterceptionDecision(
            decision=Decision.AUGMENT,
            reason="postflight deterministic facts joined the observation",
            eligibility=("postflight",),
        )
    observation = compile_observation(
        request, decision, raw_result=raw, raw_exact=True, evidence=facts
    )
    return observation, rc or 0


def _syntax_artifact(path: str, repo_root: str) -> EvidenceArtifact | None:
    """Deterministic Python syntax evidence for one changed file (IE-06).

    ast.parse of the file's current bytes. Python is exact; any failure to
    read/parse is an omission on the artifact, never a lie. Non-Python files
    produce no artifact (the caller records the omission).
    """
    import ast

    if not path.endswith(".py"):
        return None
    full = path if os.path.isabs(path) else os.path.join(repo_root, path)
    try:
        source = Path(full).read_bytes()
    except OSError:
        return None
    try:
        ast.parse(source, filename=full)
        ok, detail = True, ""
    except SyntaxError as exc:
        ok, detail = False, f"line {exc.lineno}: {exc.msg}"
    return EvidenceArtifact(
    artifact_id=hashlib.sha256(
        f"syntax:{path}:{len(source)}".encode("utf-8")
    ).hexdigest()[:16],
        owner="syntax_result",
        semantics="immediate per-file syntax evidence",
        content={"file": path, "ok": ok, "detail": detail},
        anchors=(f"{path}:1",),
        producer="py_ast",
        producer_version="1",
        freshness_revision=hashlib.sha256(source).hexdigest(),
        coverage="complete" if ok else "exact_error",
        model_visible=True,
    )


def _covering_red_artifact(
    command: str, raw: str, returncode: int | None
) -> EvidenceArtifact | None:
    """Execution-specific verification evidence for test/build commands."""
    lower = command.lower()
    if not any(word in lower for word in ("pytest", "make test", "make check",
                                          "tox", "nosetests", "unittest",
                                          "cargo test", "go test", "npm test",
                                          "yarn test")):
        return None
    outcome = "passed" if returncode in (0, None) else "failed"
    return EvidenceArtifact(
        artifact_id=hashlib.sha256(
            f"covering:{command}:{returncode}".encode("utf-8")
        ).hexdigest()[:16],
        owner="covering_red",
        semantics="execution-specific verification outcome",
        content={"command": command[:200], "outcome": outcome,
                 "returncode": returncode, "diagnostics_bytes": len(raw.encode("utf-8"))},
        producer="execution_evidence",
        producer_version="1",
        coverage="execution_specific",
        model_visible=True,
    )


_GATEWAY_FLAGS_ENABLED = False


def _ensure_gateway_flags() -> None:
    """Enable the gateway's deterministic producers.

    They default OFF (advisory-era rollout gates). The ENGINE is the canonical
    runtime: localization, signature_delta, def_partition, covering, and the
    change-surface edit trigger must be able to fire. Idempotent; never
    disables anything the caller explicitly set.
    """
    global _GATEWAY_FLAGS_ENABLED
    if _GATEWAY_FLAGS_ENABLED:
        return
    for flag in ("GT_GATEWAY", "GT_LOC_RESLOT", "GT_PATCH_DELTA",
                 "GT_CS_EDIT_TRIGGER", "GT_CHANGE_SURFACE", "GT_EDIT_OVERLAY"):
        os.environ.setdefault(flag, "1")
    _GATEWAY_FLAGS_ENABLED = True


def _update_graph_freshness(adapter: Any) -> None:
    """Incremental graph freshness — NO full rebuild (the round-5 gap).

    The advisory seam invalidates the whole graph on any edit (graph_fresh=False
    forever) so the gateway's graph-backed producers (localization,
    signature_delta caller-impact, newfile_precedent) abstain permanently. The
    ENGINE instead keeps the graph live and marks ONLY the changed files stale
    in the episode overlay via build_episode_overlay_entry — an O(changed-file)
    read-only signature comparison against the base graph (never a rebuild).
    Gateway route_delivery then drops base facts about edited files and fires
    latest info on unchanged files.
    """
    repo_root = getattr(adapter, "repo_root", "") or ""
    graph_db = getattr(adapter, "graph_db", None)
    if not repo_root or not graph_db:
        return
    try:
        changed = _git_changed_py(repo_root)
        if not changed:
            return
        from groundtruth.runtime.edit_overlay import build_episode_overlay_entry

        gateway_state = adapter.gateway_state()
        overlay = getattr(gateway_state, "episode_overlay", None)
        if not isinstance(overlay, dict):
            return
        for rel in changed:
            full = rel if os.path.isabs(rel) else os.path.join(repo_root, rel)
            try:
                content = Path(full).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            overlay[rel] = build_episode_overlay_entry(graph_db, rel, content)
        adapter.graph_fresh = True
        adapter.graph_stale_since_revision = ""
    except Exception:  # noqa: BLE001 - freshness is fail-open
        pass


def _gateway_facts(
    *,
    command: str,
    raw: str,
    returncode: int | None,
    changed_files: tuple[str, ...],
    viewed_files: tuple[str, ...],
    adapter: Any,
) -> tuple[EvidenceArtifact, ...]:
    """Run the groundtruth gateway's deterministic producers for one action.

    This is the port of the full producer set (Q3 research fix): the gateway
    fires localization on search, covering on test, signature_delta/newfile_
    precedent/def_partition on edit/search outcomes, submit_refusal on submit
    — the dominant action types the two ad-hoc producers missed. The engine
    threads the state the producers require: a CoveringResult for test events
    and edit_before_after for edit events. Fail-open: any gateway fault returns
    () and the observation stays raw-only.
    """
    try:
        from groundtruth.runtime.gateway import ToolEvent, produce_raw
        from groundtruth.runtime.adapters.miniswe import arbitrate
    except Exception:  # noqa: BLE001 - gateway is optional
        return ()
    _ensure_gateway_flags()
    try:
        edit_before_after = _edit_before_after(
            getattr(adapter, "repo_root", "") or "", changed_files
        )
        covering = _covering_result(command, raw, returncode)
        test_outcome = ""
        if covering is not None:
            verdict = str(getattr(covering, "verdict", "") or "").upper()
            test_outcome = "fail" if verdict == "FAIL" else "pass"
        # Authoritative semantic set (the gateway's semantics_authoritative
        # mode): the ENGINE knows the truth from git/covering/command shapes,
        # so it does not rely on command-spelling inference (which misses
        # sed/heredoc edits). Empty set is authoritative (a no-op).
        semantic: list[str] = []
        if covering is not None:
            semantic.append("test_result")
        elif changed_files:
            semantic.append("edit_result")
        elif viewed_files:
            semantic.append("file_view")
        elif _is_search_command(command):
            semantic.append("search_result" if raw.strip() else "failed_search")
        elif _is_submit_command(command):
            semantic.append("submit")
        primary = semantic[0] if semantic else ""
        event = ToolEvent(
            kind="bash",
            command=command,
            output=raw,
            exit_status=returncode,
            cwd=getattr(adapter, "repo_root", "") or "",
            changed_files=changed_files,
            viewed_files=viewed_files,
            action_index=1,
            edit_before_after=edit_before_after,
            covering=covering,
            semantic_events=tuple(semantic),
            primary_boundary=primary,
            test_outcome=test_outcome,
            state_revision=adapter.repository_revision,
            semantics_authoritative=True,
        )
        envelopes = produce_raw(event, adapter.gateway_state())
        if not envelopes:
            return ()
        # Single-dose: at most one fact per observation (frontier context
        # hygiene + trust preservation). Arbitrate picks the highest-priority
        # envelope, rotating away recently-delivered classes and preferring the
        # fact that answers THIS observation's boundary.
        winner = arbitrate(
            envelopes,
            recently_delivered=frozenset(
                getattr(adapter, "_dedup_chain", ()) or ()
            ),
            observed_event=event.primary_boundary,
        )
    except Exception:  # noqa: BLE001 - producer failure is an omission
        return ()
    if winner is None:
        return ()
    try:
        chain = getattr(adapter, "_dedup_chain", None)
        if isinstance(chain, set):
            chain.add(getattr(winner, "dedup_key", "") or "")
    except Exception:  # noqa: BLE001 - fire-once stamping is best-effort
        pass
    evidence_type = str(getattr(winner, "evidence_type", "") or "")
    owner = _EVIDENCE_TO_OWNER.get(evidence_type)
    if owner is None or owner not in ENGINE_FACT_OWNERS:
        return ()
    target = str(getattr(winner, "target", "") or "")
    content = str(getattr(winner, "content", "") or "")
    artifact_id = (
        str(getattr(winner, "fact_id", "") or "")
        or hashlib.sha256(f"{owner}:{target}:{content}".encode("utf-8")).hexdigest()[:16]
    )
    artifact = EvidenceArtifact(
        artifact_id=artifact_id,
        owner=owner,
        semantics=evidence_type,
        content={"evidence": content, "target": target},
        anchors=(target,) if target else (),
        producer=str(getattr(winner, "producer", "") or "gateway"),
        producer_version="gateway",
        freshness_revision=adapter.repository_revision,
        coverage="produced",
        model_visible=True,
    )
    return (artifact,)


def _significant(text: str, _unused: str) -> set[str]:
    """Significant lowercase tokens (files, symbols, identifiers) for the
    obligation relevance gate."""
    tokens = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", text or ""))
    return {t.lower() for t in tokens if t.lower() not in {
        "the", "and", "for", "are", "with", "that", "this", "you", "should",
        "must", "from", "have", "not", "was", "will", "can", "all", "into",
        "out", "its", "has", "but", "any", "your", "our", "their", "them",
    }}


def _obligations_fact(
    *,
    command: str,
    raw: str,
    returncode: int | None,
    adapter: Any,
) -> EvidenceArtifact | None:
    """Action-bound task obligations — the highest-gain 'right info'.

    The task contract lists the requirements (files/behaviors) the issue asks
    for. This fact tells the model which obligations its current action matches,
    with the ACTUAL requirement text (not opaque IDs) and the files/subjects the
    obligations reference (anchors the ladder can measure). The model may not
    have parsed the issue text, so this is information it lacks — delivered at
    the correct time (same observation, before the next call).
    """
    contract = getattr(adapter, "contract", None)
    if contract is None:
        return None
    try:
        from ..task_contract import matching_obligation_ids

        matched_ids = matching_obligation_ids(contract, command, raw)
    except Exception:  # noqa: BLE001 - obligation matching is fail-open
        return None
    if not matched_ids:
        return None
    matched = [
        item for item in contract.obligations
        if item.obligation_id in matched_ids
    ]
    # Relevance gate: an obligation is only reported when the action actually
    # references its subject (file/symbol) or carries a strong token overlap —
    # otherwise matching_obligation_ids' 1-2 token threshold spams the same
    # requirement on unrelated actions (the round-5 242x repeat).
    action_text = f"{command}\n{raw}".lower()
    relevant = []
    for item in matched:
        subjects = [str(s).lower() for s in (item.subjects or ()) if s]
        subject_hit = any(s and s in action_text for s in subjects)
        strong_overlap = len(
            set(_significant(command, raw)) & set(_significant(item.text, ""))
        ) >= 3
        if subject_hit or strong_overlap:
            relevant.append(item)
    if not relevant:
        return None
    matched = relevant
    requirements = [str(item.text) for item in matched if item.text]
    subjects = [
        str(s) for item in matched for s in (item.subjects or ())
        if s and not str(s).startswith("obl-")
    ]
    anchors = tuple(dict.fromkeys(subjects))
    if not requirements and not anchors:
        return None  # nothing usable -> abstain honestly
    return EvidenceArtifact(
        artifact_id=hashlib.sha256(
            f"oblig:{','.join(sorted(matched_ids))}".encode("utf-8")
        ).hexdigest()[:16],
        owner="obligations",
        semantics="task obligation spans bound to this action",
        content={
            "matched": [item.obligation_id for item in matched],
            "requirements": requirements[:4],
            "subjects": list(anchors)[:8],
        },
        anchors=anchors,
        producer="contract_delta",
        producer_version="1",
        freshness_revision=adapter.repository_revision,
        coverage="lexical_match",
        model_visible=True,
    )


def _fact_dedup_key(fact: EvidenceArtifact) -> str:
    """Stable per-episode dedup key.

    obligations key on the matched obligation IDs (a requirement fires once per
    episode even across different actions); everything else keys on
    owner + anchors (or content hash when no anchors). Fire-once prevents the
    round-5 spam (242 obligation deliveries of the same requirement).
    """
    if fact.owner == "obligations":
        matched = (fact.content or {}).get("matched") or []
        return f"obligations:{','.join(sorted(str(x) for x in matched))}"
    anchors = ":".join(fact.anchors) if fact.anchors else ""
    return f"{fact.owner}:{anchors or fact.hash()}"


def _dedup_facts(
    facts: tuple[EvidenceArtifact, ...], adapter: Any
) -> tuple[EvidenceArtifact, ...]:
    """Fire-once per episode: drop facts already delivered, stamp the new ones.

    The gateway already dedups its own winner via adapter._dedup_chain; this
    extends the same registry to the engine-direct producers (obligations,
    syntax, covering) so no fact type spams the conversation.
    """
    chain = getattr(adapter, "_dedup_chain", None)
    if not isinstance(chain, set):
        return facts
    out: list[EvidenceArtifact] = []
    for fact in facts:
        key = _fact_dedup_key(fact)
        if key in chain:
            continue
        chain.add(key)
        out.append(fact)
    return tuple(out)


def _postflight_facts(
    request: ActionRequest,
    *,
    command: str,
    raw: str,
    returncode: int | None,
    repo_root: str,
    adapter: Any,
) -> tuple[EvidenceArtifact, ...]:
    """Deterministic post-execution facts for one shell action (IE-06).

    The full gateway producer set first (localization/covering/signature_delta/
    newfile_precedent/def_partition), then the engine's own syntax_result on
    changed .py files. Raw-preserving: the observation keeps the exact raw
    bytes and the facts only add to the same canonical observation.
    """
    changed = _git_changed_py(repo_root)
    viewed = _viewed_paths(request)
    facts: list[EvidenceArtifact] = list(
        _gateway_facts(
            command=command,
            raw=raw,
            returncode=returncode,
            changed_files=changed,
            viewed_files=viewed,
            adapter=adapter,
        )
    )
    obligations = _obligations_fact(
        command=command, raw=raw, returncode=returncode, adapter=adapter,
    )
    if obligations is not None:
        facts.append(obligations)
    for path in changed:
        artifact = _syntax_artifact(path, repo_root)
        if artifact is None:
            continue
        content = artifact.content or {}
        # Information-gain gate: "file parses OK" carries zero novel signal
        # (the model sees it by reading the file). Only a syntax ERROR ("line N
        # broken") is decision-relevant. Omitted syntax (unreadable) is kept.
        if content.get("ok") is True:
            continue
        facts.append(artifact)
    covering = _covering_red_artifact(command, raw, returncode)
    if covering is not None and not any(f.owner == "covering_red" for f in facts):
        outcome = (covering.content or {}).get("outcome")
        # RED (failed) is the actionable fact; a pass is visible in the raw and
        # adds no information.
        if outcome == "failed":
            facts.append(covering)
    return _dedup_facts(tuple(facts), adapter)


def _is_search_command(command: str) -> bool:
    return bool(re.search(
        r"(?:^|[;&|\s])(?:rg\b|grep\b|git\s+grep\b|\bfind\b|\bag\b|\back\b)",
        command or "",
    ))


def _is_submit_command(command: str) -> bool:
    try:
        from ..miniswe_evidence import is_submit_command

        return is_submit_command(command)
    except Exception:  # noqa: BLE001
        return False


def _viewed_paths(request: ActionRequest) -> tuple[str, ...]:
    """Best-effort viewed-file list from a FILE_READ/SEARCH shell request."""
    args = request.arguments or {}
    path = str(args.get("path") or args.get("paths") or "")
    if path:
        return (path,)
    command = request.literal_shell_form or ""
    match = re.search(r"(?:cat|less|head|tail|more|view)\s+[\"\']?([\w./-]+)", command)
    return (match.group(1),) if match else ()


def _edit_before_after(
    repo_root: str, changed: tuple[str, ...]
) -> dict[str, tuple[str, str]] | None:
    """Deterministic before/after content for changed tracked files.

    before = `git show HEAD:<path>`, after = current bytes. The gateway's
    patch_delta/signature producers need this. Returns None when repo_root is
    not a git checkout or no .py file yields both sides (omission, never a lie).
    """
    if not repo_root or not changed:
        return None
    import subprocess

    mapping: dict[str, tuple[str, str]] = {}
    for path in changed:
        if not path.endswith(".py"):
            continue
        try:
            before = subprocess.run(
                ["git", "-C", repo_root, "show", f"HEAD:{path}"],
                capture_output=True, text=True, timeout=10,
            ).stdout
            full = path if os.path.isabs(path) else os.path.join(repo_root, path)
            after = Path(full).read_text(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - a missing side is an omission
            continue
        mapping[path] = (before, after)
    return mapping or None


def _covering_result(
    command: str, raw: str, returncode: int | None
) -> "object | None":
    """Build the CoveringResult the gateway's covering producer threads.

    The gateway's leak-law rejects test/demo/docs paths, so the target must be
    the SOURCE file under test — parsed from the output's traceback frames
    (non-test, non-vendored .py), falling back to a changed source file. Only
    explicit test commands produce a result; others abstain honestly.
    """
    if _covering_red_artifact(command, raw, returncode) is None:
        return None
    try:
        from groundtruth.runtime.adapters.miniswe import CoveringResult
    except Exception:  # noqa: BLE001
        return None
    test_files = tuple(
        m for m in re.findall(r"(?:^|\s)([\w./-]*test[\w./-]*\.py)", raw) if m
    )
    target = ""
    # prefer a source frame from the output: a .py path that is not a test /
    # vendored / venv path (the code under test, not the test itself).
    for m in re.findall(r"([\w./-]+\.py):\d+", raw):
        if not re.search(r"(test|tests|vendor|site-packages|\.venv|/venv/)", m):
            target = m
            break
    verdict = "FAIL" if returncode not in (0, None) else "PASS"
    if not target:
        return None  # honest abstention: no source target derivable
    # Body = the failure-relevant pytest lines (traceback/assert/error), not
    # the summary tail; the render firewall expects the assertion block and an
    # ERROR tier, and evidence anchors the source line.
    body = [
        ln for ln in raw.splitlines()
        if re.search(r"(Error|assert|raise|E\s|Traceback|\.py:\d+)", ln)
    ][-8:]
    return CoveringResult(
        target=target,
        verdict=verdict,
        body_lines=body or [line for line in raw.splitlines()[-4:] if line],
        evidence=[(target, 1)],
        tier="ERROR",
        test_files=test_files,
    )


def _git_changed_py(repo_root: str) -> tuple[str, ...]:
    """Changed tracked .py paths via git status --porcelain (deterministic).

    Returns () when repo_root is not a git checkout (omission, never a lie).
    """
    if not repo_root:
        return ()
    try:
        import subprocess

        proc = subprocess.run(
            ["git", "-C", repo_root, "status", "--porcelain"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:  # noqa: BLE001 - git is optional; omission
        return ()
    if proc.returncode != 0:
        return ()
    changed: list[str] = []
    for line in proc.stdout.splitlines():
        if len(line) < 4:
            continue
        status, path = line[:2], line[3:]
        # Tracked modifications (M/A anywhere in the pair) and untracked
        # additions (??) count as edits. Porcelain writes a modified worktree
        # file as " M" (index space + worktree M), so strip before matching.
        if status.startswith("??") or status.strip().startswith(("M", "A")):
            path = path.split(" -> ")[-1]
            if path.endswith(".py") and not path.startswith("."):
                changed.append(path)
    return tuple(changed)


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
        if not is_typed and request.kind == ActionKind.SHELL:
            # Bash submit commands must cross the submit boundary (the typed
            # SUBMIT kind already does). Detect them the same way the advisory
            # seam does and reclassify so the gate can suppress under a fresh
            # certified blocker.
            from ..miniswe_evidence import is_submit_command

            if is_submit_command(request.literal_shell_form):
                request = ActionRequest(
                    action_id=request.action_id,
                    kind=ActionKind.SUBMIT,
                    arguments=request.arguments,
                    literal_shell_form=request.literal_shell_form,
                    snapshot_token=request.snapshot_token,
                    configuration_digest=request.configuration_digest,
                    requested_fidelity=request.requested_fidelity,
                    batch_id=request.batch_id,
                    sequence_position=request.sequence_position,
                    raw_fallback=request.raw_fallback,
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
        # Track obligation GREEN/RED predicates so the submit gate and recovery
        # facts have real state (the advisory seam did this; the engine must
        # too, or obligations/RED never populate).
        if getattr(adapter, "contract", None) is not None:
            try:
                raw_output = observation.raw_result or ""
                adapter.evaluate_observation(
                    request.literal_shell_form, raw_output,
                    returncode=returncode,
                    action_index=adapter.global_action,
                )
                adapter.evaluate_failing_observation(
                    request.literal_shell_form, raw_output,
                    returncode=returncode,
                    action_index=adapter.global_action,
                )
            except Exception:  # noqa: BLE001 - obligation tracking is fail-open
                pass
        # Incremental graph freshness: mark changed files stale in the overlay
        # (no full rebuild) so graph-backed producers keep firing latest info.
        _update_graph_freshness(adapter)
        rendered = observation.render()
        outputs.append(_tool_output(observation, returncode))
        if decision.decision == Decision.SUPPRESS:
            directives.append(rt._refusal_directive(adapter))

        try:
            receipt = _delivery_receipt(request, decision, observation, adapter)
            if getattr(adapter, "store", None) is not None:
                # NOTE: do NOT pass schema= here. ExternalStateStore.append
                # forces gt.event.v1; a payload schema kwarg OVERRIDES it and
                # breaks the tamper-evident journal (verify_event_journal then
                # reports 'unsupported or missing schema' and research_valid
                # becomes false). Covered by test_engine_journal_schema.
                adapter.store.append(
                    "engine_delivery",
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
