from __future__ import annotations

import json

from gt_engine.hybrid_retrieval import (
    HybridRetriever,
    RepositoryDocument,
    RetrievalIntent,
    RetrievalState,
    StructuralLink,
)
from gt_engine.persistent_execution_state import (
    BootstrapCatalog,
    ContextFrameKind,
    PersistentExecutionStateEngine,
    StatePhase,
    StateValidationStatus,
    bootstrap_visible_item_ids,
    build_bootstrap_catalog,
    build_bootstrap_messages,
    parse_bootstrap_selection,
)
from gt_engine.preflight import adapt_proposed_action
from gt_engine.repository_intelligence import RepositoryEvidence


def _document(path: str, symbol: str, line: int = 1) -> RepositoryDocument:
    return RepositoryDocument(
        path=path,
        start_line=line,
        end_line=line + 2,
        symbol=symbol,
        text=f"def {symbol}():\n    return None",
        provenance=("graph_node",),
    )


def _evidence(source_revision: str = "source-1") -> RepositoryEvidence:
    return RepositoryEvidence(
        available=True,
        graph_revision="graph-1",
        anchors=(
            {
                "path": "src/service.py",
                "line": 10,
                "symbol": "save_user",
                "semantic_certainty": 1.0,
                "retrieval_relevance": 1.0,
            },
        ),
        definitions=({"path": "src/service.py", "line": 10, "symbol": "save_user"},),
        callers=(
            {
                "path": "src/api.py",
                "line": 24,
                "symbol": "create_user",
                "target_path": "src/service.py",
                "target_symbol": "save_user",
            },
        ),
        project_checks=("pytest tests/test_service.py -q",),
        status="source_backed",
        source_revision=source_revision,
        index_current=True,
        intelligence_valid=True,
        substrate_ready=True,
    )


def _links() -> tuple[StructuralLink, ...]:
    return (
        StructuralLink(
            source_path="src/api.py",
            target_path="src/service.py",
            relation="CALLS",
            confidence=1.0,
            provenance=("graph_edge:CALLS",),
            certified=True,
            source_symbol="create_user",
            target_symbol="save_user",
        ),
        StructuralLink(
            source_path="src/service.py",
            target_path="tests/test_service.py",
            relation="ASSERTED_BY",
            confidence=1.0,
            provenance=("resolved_test_assertion",),
            certified=True,
            source_symbol="save_user",
            target_symbol="test_save_user",
        ),
        StructuralLink(
            source_path="src/service.py",
            target_path="notes/history.md",
            relation="commit_set_cochange",
            confidence=1.0,
            provenance=("commit_set_cochange",),
            certified=False,
        ),
    )


def _catalog() -> BootstrapCatalog:
    return build_bootstrap_catalog(
        instruction="Fix save_user and run pytest tests/test_service.py -q.",
        evidence=_evidence(),
        documents=(
            _document("src/service.py", "save_user", 10),
            _document("src/api.py", "create_user", 24),
            _document("tests/test_service.py", "test_save_user", 5),
        ),
        structural_links=_links(),
        explicit_checks=("pytest tests/test_service.py -q",),
        task_deliverables=(),
        source_revision="source-1",
        graph_revision="graph-1",
        repository_complete=True,
    )


def _proposed(command: str, *, source_revision: str = "source-1", call: int = 1):
    return adapt_proposed_action(
        {"command": command, "tool_call_id": f"action-{call}"},
        source_revision=source_revision,
        workspace_revision=f"workspace-{call}",
        model_call=call,
        batch_index=0,
        batch_size=1,
    )


def test_graph_first_catalog_contains_only_bounded_certified_inputs():
    catalog = _catalog()

    assert catalog.complete is True
    assert len(catalog.items) <= 32
    assert catalog.source_revision == "source-1"
    assert catalog.graph_revision == "graph-1"
    assert any(item.path == "src/service.py" for item in catalog.items)
    assert any(item.kind.value == "validation" for item in catalog.items)
    assert all("notes/history.md" not in item.anchors for item in catalog.items)
    assert all(item.item_id.startswith("pes-") for item in catalog.items)
    assert all(item.required for item in catalog.items if item.kind.value == "validation")


def test_inferred_project_check_is_a_nonblocking_candidate_not_a_task_requirement():
    catalog = build_bootstrap_catalog(
        instruction="Fix save_user.",
        evidence=_evidence(),
        documents=(_document("src/service.py", "save_user"),),
        structural_links=(),
        explicit_checks=(),
        source_revision="source-1",
        graph_revision="graph-1",
        repository_complete=True,
    )
    engine = PersistentExecutionStateEngine.initialize_from_graph(
        task="Fix save_user.",
        catalog=catalog,
        structural_links=(),
        present_paths=("src/service.py",),
    )

    validation = next(item for item in catalog.items if item.kind.value == "validation")
    assert validation.label.startswith("Project validation candidate:")
    assert validation.required is False
    assert engine.snapshot.obligations == ()


def test_graph_incomplete_catalog_fails_closed_without_items():
    catalog = build_bootstrap_catalog(
        instruction="Fix save_user",
        evidence=_evidence("source-2"),
        documents=(_document("src/service.py", "save_user"),),
        structural_links=(),
        source_revision="source-1",
        graph_revision="graph-1",
        repository_complete=False,
    )

    assert catalog.complete is False
    assert catalog.items == ()
    assert "repository_corpus_incomplete" in catalog.reason_codes


def test_graph_without_task_conditioned_catalog_abstains_before_bootstrap():
    evidence = RepositoryEvidence(
        available=True,
        graph_revision="graph-1",
        status="source_backed",
        source_revision="source-1",
        index_current=True,
        intelligence_valid=True,
        substrate_ready=True,
    )

    catalog = build_bootstrap_catalog(
        instruction="Fix the behavior.",
        evidence=evidence,
        documents=(_document("src/unrelated.py", "unrelated"),),
        structural_links=(),
        source_revision="source-1",
        graph_revision="graph-1",
        repository_complete=True,
    )

    assert catalog.complete is False
    assert catalog.items == ()
    assert catalog.reason_codes == ("empty_catalog",)


def test_shared_hybrid_retrieval_seeds_bootstrap_when_legacy_graph_query_is_empty():
    evidence = RepositoryEvidence(
        available=True,
        graph_revision="graph-1",
        status="source_backed",
        source_revision="source-1",
        index_current=True,
        intelligence_valid=True,
        substrate_ready=True,
    )
    documents = (
        _document("src/compressor.py", "write_compressed"),
        _document("src/unrelated.py", "unrelated"),
    )
    state = RetrievalState(
        task_text="Fix write_compressed output truncation.",
        intent=RetrievalIntent.IMPLEMENTATION_CONTEXT,
        source_revision="source-1",
    )
    result = HybridRetriever(documents).retrieve(
        state,
        channel_limit=20,
        top_k=8,
        selection_limit=2,
        token_budget=400,
    )

    catalog = build_bootstrap_catalog(
        instruction=state.task_text,
        evidence=evidence,
        documents=documents,
        structural_links=(),
        source_revision="source-1",
        graph_revision="graph-1",
        repository_complete=True,
        initial_retrieval=result,
    )

    ranked = [item for item in catalog.items if item.retrieval_rank]
    assert catalog.complete is True
    assert ranked
    assert ranked[0].path == "src/compressor.py"
    assert ranked[0].certified is False
    assert "hybrid_ranked_candidate" in ranked[0].provenance
    assert {"lexical", "bm25"} <= set(ranked[0].support_channels)


def test_valid_bootstrap_may_abstain_from_ranked_focus_without_forced_anchor():
    catalog = _catalog()

    selection = parse_bootstrap_selection(
        json.dumps(
            {
                "primary_focus_id": "",
                "ordered_item_ids": [],
                "risk_item_ids": [],
                "validation_item_ids": [],
            }
        ),
        catalog,
    )

    assert selection.valid is True
    assert selection.primary_focus_id == ""


def test_invalid_bootstrap_fails_open_without_ranked_context_delivery():
    catalog = _catalog()
    engine = PersistentExecutionStateEngine.initialize_from_graph(
        task="Fix save_user.",
        catalog=catalog,
        structural_links=_links(),
        present_paths=("src/service.py",),
    )

    engine.apply_bootstrap(
        parse_bootstrap_selection("not-json", catalog),
        current_source_revision="source-1",
    )
    frame = engine.compile_context(
        current_source_revision="source-1", provider_call=1, max_tokens=512
    )

    assert engine.snapshot.bootstrap_status.value == "invalid_fallback"
    assert engine.snapshot.primary_focus_id == ""
    assert frame.kind is ContextFrameKind.NONE
    assert frame.reason_codes == ("bootstrap_selection_unavailable",)


def test_ranked_focus_is_never_rendered_as_certified_relevance():
    evidence = RepositoryEvidence(
        available=True,
        graph_revision="graph-1",
        status="source_backed",
        source_revision="source-1",
        index_current=True,
        intelligence_valid=True,
        substrate_ready=True,
    )
    documents = (_document("src/compressor.py", "write_compressed"),)
    state = RetrievalState(
        task_text="Fix write_compressed output truncation.",
        intent=RetrievalIntent.IMPLEMENTATION_CONTEXT,
        source_revision="source-1",
    )
    result = HybridRetriever(documents).retrieve(state, token_budget=400)
    catalog = build_bootstrap_catalog(
        instruction=state.task_text,
        evidence=evidence,
        documents=documents,
        structural_links=(),
        source_revision="source-1",
        graph_revision="graph-1",
        repository_complete=True,
        initial_retrieval=result,
    )
    ranked = next(item for item in catalog.items if item.retrieval_rank == 1)
    engine = PersistentExecutionStateEngine.initialize_from_graph(
        task=state.task_text,
        catalog=catalog,
        structural_links=(),
        present_paths=(ranked.path,),
    )
    engine.apply_bootstrap(
        parse_bootstrap_selection(
            json.dumps(
                {
                    "primary_focus_id": ranked.item_id,
                    "ordered_item_ids": [ranked.item_id],
                    "risk_item_ids": [],
                    "validation_item_ids": [],
                }
            ),
            catalog,
        ),
        current_source_revision="source-1",
    )

    frame = engine.compile_context(
        current_source_revision="source-1", provider_call=1, max_tokens=512
    )

    assert "bootstrap-selected ranked focus" in frame.rendered_text
    assert "Current certified focus" not in frame.rendered_text
    assert engine.snapshot.current_focus_path == ""


def test_bootstrap_selection_is_strictly_catalog_bounded():
    catalog = _catalog()
    focus = next(item.item_id for item in catalog.items if item.path == "src/service.py")
    check = next(item.item_id for item in catalog.items if item.kind.value == "validation")

    selection = parse_bootstrap_selection(
        json.dumps(
            {
                "primary_focus_id": focus,
                "ordered_item_ids": [focus, check],
                "risk_item_ids": [],
                "validation_item_ids": [check],
            }
        ),
        catalog,
    )

    assert selection.valid is True
    assert selection.primary_focus_id == focus
    assert selection.validation_item_ids == (check,)

    invalid = parse_bootstrap_selection(
        json.dumps(
            {
                "primary_focus_id": "invented-file",
                "ordered_item_ids": ["invented-file"],
                "risk_item_ids": [],
                "validation_item_ids": [],
            }
        ),
        catalog,
    )
    assert invalid.valid is False
    assert invalid.primary_focus_id == ""
    assert "unknown_catalog_id" in invalid.reason_codes


def test_bootstrap_transport_uses_one_bash_json_envelope_without_repo_bytes():
    catalog = _catalog()
    messages = build_bootstrap_messages(
        task="Fix save_user and its tests.",
        catalog=catalog,
        max_input_tokens=2_000,
    )

    serialized = json.dumps(messages, sort_keys=True)
    assert len(messages) == 2
    assert "primary_focus_id" in serialized
    assert "bash" in serialized
    assert "def save_user" not in serialized
    assert sum(len(item["content"].encode("utf-8")) for item in messages) <= 2_000
    assert bootstrap_visible_item_ids(messages)


def test_bootstrap_cannot_select_a_catalog_item_omitted_by_the_request_budget():
    catalog = _catalog()
    shown = frozenset({catalog.items[0].item_id})
    hidden = catalog.items[-1].item_id

    selection = parse_bootstrap_selection(
        json.dumps(
            {
                "primary_focus_id": hidden,
                "ordered_item_ids": [hidden],
                "risk_item_ids": [],
                "validation_item_ids": [],
            }
        ),
        catalog,
        visible_item_ids=shown,
    )

    assert selection.valid is False
    assert selection.reason_codes == ("unshown_catalog_id",)


def test_state_is_reused_at_provider_preflight_postflight_and_rebase_boundaries():
    catalog = _catalog()
    engine = PersistentExecutionStateEngine.initialize_from_graph(
        task="Fix save_user and run its test.",
        catalog=catalog,
        structural_links=_links(),
        present_paths=("src/service.py", "src/api.py", "tests/test_service.py"),
    )
    focus = next(item.item_id for item in catalog.items if item.path == "src/service.py")
    check = next(item.item_id for item in catalog.items if item.kind.value == "validation")
    engine.apply_bootstrap(
        parse_bootstrap_selection(
            json.dumps(
                {
                    "primary_focus_id": focus,
                    "ordered_item_ids": [focus, check],
                    "risk_item_ids": [],
                    "validation_item_ids": [check],
                }
            ),
            catalog,
        ),
        current_source_revision="source-1",
    )

    first = engine.compile_context(
        current_source_revision="source-1",
        provider_call=1,
        max_tokens=512,
    )
    read = _proposed("sed -n '1,120p' src/service.py")
    projection = engine.project_preflight(read, current_source_revision="source-1")
    engine.commit_postflight(
        read,
        returncode=0,
        output="def save_user(): pass",
        changed_paths=(),
        current_source_revision="source-1",
        current_graph_revision="graph-1",
        validation_status="unknown",
    )
    second = engine.compile_context(
        current_source_revision="source-1",
        provider_call=2,
        max_tokens=256,
    )
    edit = _proposed("sed -i 's/pass/return 1/' src/service.py", call=2)
    engine.project_preflight(edit, current_source_revision="source-1")
    engine.commit_postflight(
        edit,
        returncode=0,
        output="",
        changed_paths=("src/service.py",),
        current_source_revision="source-2",
        current_graph_revision="graph-2",
        validation_status="unknown",
    )
    stale_graph_frame = engine.compile_context(
        current_source_revision="source-2",
        provider_call=3,
        max_tokens=256,
    )
    engine.rebase_graph(
        evidence=_evidence("source-2"),
        structural_links=_links(),
        current_source_revision="source-2",
        current_graph_revision="graph-2",
        graph_complete=True,
        changed_paths=("src/service.py",),
        present_paths=("src/service.py", "src/api.py", "tests/test_service.py"),
    )
    third = engine.compile_context(
        current_source_revision="source-2",
        provider_call=4,
        max_tokens=256,
    )

    assert first.kind is ContextFrameKind.INITIAL
    assert projection.considered is True
    assert "src/service.py" in engine.snapshot.files_inspected
    assert "src/service.py" in engine.snapshot.files_modified
    assert engine.snapshot.phase is StatePhase.IMPLEMENTING
    assert engine.snapshot.current_focus_path == "src/service.py"
    assert engine.snapshot.validation.status is StateValidationStatus.PENDING
    assert {item.path for item in engine.snapshot.obligations if item.status.value == "open"} >= {
        "src/api.py",
        "tests/test_service.py",
    }
    assert second.kind in {ContextFrameKind.DELTA, ContextFrameKind.CORE}
    assert stale_graph_frame.kind is ContextFrameKind.NONE
    assert "graph_rebase_required" in stale_graph_frame.reason_codes
    assert third.source_revision == "source-2"
    assert "Current observed repository focus: src/service.py" in third.rendered_text
    assert "Candidate implementation src/service.py:10" not in third.rendered_text
    assert engine.metrics["context_compilations"] == 4
    assert engine.metrics["preflight_projections"] == 2
    assert engine.metrics["postflight_commits"] == 2
    assert engine.metrics["graph_rebases"] == 1


def test_initial_frame_contains_only_bootstrap_selected_checkout_span():
    catalog = _catalog()
    engine = PersistentExecutionStateEngine.initialize_from_graph(
        task="Fix save_user and run its test.",
        catalog=catalog,
        structural_links=_links(),
        present_paths=("src/service.py", "src/api.py", "tests/test_service.py"),
    )
    focus = next(item.item_id for item in catalog.items if item.path == "src/service.py")
    engine.apply_bootstrap(
        parse_bootstrap_selection(
            json.dumps(
                {
                    "primary_focus_id": focus,
                    "ordered_item_ids": [focus],
                    "risk_item_ids": [],
                    "validation_item_ids": [],
                }
            ),
            catalog,
        ),
        current_source_revision="source-1",
    )

    frame = engine.compile_context(
        current_source_revision="source-1",
        provider_call=1,
        max_tokens=512,
    )

    assert frame.kind is ContextFrameKind.INITIAL
    assert "src/service.py" in frame.rendered_text
    assert "def save_user():" in frame.rendered_text
    assert "def create_user():" not in frame.rendered_text
    assert "Bootstrap-selected repository context" in frame.rendered_text
    assert frame.selected_evidence == (
        {
            "path": "src/service.py",
            "start_line": 10,
            "end_line": 12,
            "symbol": "save_user",
            "claim_id": frame.selected_evidence[0]["claim_id"],
            "support_kind": "certified_identity",
            "retrieval_rank": 0,
            "supporting_channels": [],
        },
    )

    read = _proposed("sed -n '1,40p' src/service.py")
    engine.commit_postflight(
        read,
        returncode=0,
        output="def save_user():\n    return None",
        changed_paths=(),
        current_source_revision="source-1",
        current_graph_revision="graph-1",
        validation_status="unknown",
    )
    after_read = engine.compile_context(
        current_source_revision="source-1",
        provider_call=2,
        max_tokens=512,
    )

    assert "Bootstrap-selected repository context" not in after_read.rendered_text
    assert "def save_user():" not in after_read.rendered_text
    assert after_read.selected_evidence == ()


def test_bootstrap_selected_symbol_uses_its_exact_span_in_a_multi_symbol_file():
    catalog = build_bootstrap_catalog(
        instruction="Fix save_user in src/service.py.",
        evidence=_evidence(),
        documents=(
            RepositoryDocument(
                path="src/service.py",
                start_line=1,
                end_line=2,
                symbol="unrelated_helper",
                text="def unrelated_helper():\n    return 'wrong span'",
                provenance=("graph_node",),
            ),
            RepositoryDocument(
                path="src/service.py",
                start_line=10,
                end_line=12,
                symbol="save_user",
                text="def save_user():\n    return 'selected span'",
                provenance=("graph_node",),
            ),
        ),
        structural_links=(),
        explicit_checks=(),
        task_deliverables=(),
        source_revision="source-1",
        graph_revision="graph-1",
        repository_complete=True,
    )
    focus = next(
        item
        for item in catalog.items
        if item.path == "src/service.py" and item.symbol == "save_user"
    )

    assert focus.source_start_line == 10
    assert focus.source_end_line == 12
    assert "selected span" in focus.source_excerpt
    assert "wrong span" not in focus.source_excerpt


def test_graph_discovery_after_edit_updates_state_without_a_second_model_plan():
    engine = PersistentExecutionStateEngine.initialize_from_graph(
        task="Fix save_user.",
        catalog=_catalog(),
        structural_links=(),
        present_paths=("src/service.py", "src/api.py"),
    )
    edit = _proposed("sed -i 's/pass/return 1/' src/service.py")
    engine.commit_postflight(
        edit,
        returncode=0,
        output="",
        changed_paths=("src/service.py",),
        current_source_revision="source-2",
        current_graph_revision="graph-2",
        validation_status="unknown",
    )
    discovered = StructuralLink(
        source_path="src/api.py",
        target_path="src/service.py",
        relation="CALLS",
        confidence=1.0,
        provenance=("graph_edge:CALLS",),
        certified=True,
    )

    engine.rebase_graph(
        evidence=_evidence("source-2"),
        structural_links=(discovered,),
        current_source_revision="source-2",
        current_graph_revision="graph-2",
        graph_complete=True,
        changed_paths=("src/service.py",),
        present_paths=("src/service.py", "src/api.py"),
    )

    graph_obligations = [item for item in engine.snapshot.obligations if item.relation == "calls"]
    assert len(graph_obligations) == 1
    assert graph_obligations[0].path == "src/api.py"
    assert graph_obligations[0].blocking is False
    assert engine.metrics["bootstrap_applications"] == 0
    assert engine.metrics["graph_rebases"] == 1


def test_graph_advisories_do_not_create_a_false_submit_block():
    catalog = build_bootstrap_catalog(
        instruction="Fix save_user.",
        evidence=_evidence(),
        documents=(
            _document("src/service.py", "save_user"),
            _document("src/api.py", "create_user"),
        ),
        structural_links=_links()[:1],
        explicit_checks=(),
        source_revision="source-1",
        graph_revision="graph-1",
        repository_complete=True,
    )
    engine = PersistentExecutionStateEngine.initialize_from_graph(
        task="Fix save_user.",
        catalog=catalog,
        structural_links=_links()[:1],
        present_paths=("src/service.py", "src/api.py"),
    )
    edit = _proposed("sed -i 's/pass/return 1/' src/service.py")
    engine.commit_postflight(
        edit,
        returncode=0,
        output="",
        changed_paths=("src/service.py",),
        current_source_revision="source-2",
        current_graph_revision="graph-2",
        validation_status="unknown",
    )
    engine.rebase_graph(
        evidence=_evidence("source-2"),
        structural_links=_links()[:1],
        current_source_revision="source-2",
        current_graph_revision="graph-2",
        graph_complete=True,
        changed_paths=("src/service.py",),
        present_paths=("src/service.py", "src/api.py"),
    )
    submit = _proposed(
        "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT",
        source_revision="source-2",
        call=2,
    )

    projection = engine.project_preflight(submit, current_source_revision="source-2")

    assert projection.open_obligation_ids
    assert projection.blocking_obligation_ids == ()
    assert projection.material_contradiction is False


def test_successful_current_validation_advances_ready_without_inventing_completion():
    catalog = _catalog()
    engine = PersistentExecutionStateEngine.initialize_from_graph(
        task="Fix save_user and run its test.",
        catalog=catalog,
        structural_links=_links(),
        present_paths=("src/service.py", "src/api.py", "tests/test_service.py"),
    )
    edit = _proposed("sed -i 's/pass/return 1/' src/service.py")
    engine.commit_postflight(
        edit,
        returncode=0,
        output="",
        changed_paths=("src/service.py",),
        current_source_revision="source-2",
        current_graph_revision="graph-2",
        validation_status="unknown",
    )
    engine.rebase_graph(
        evidence=_evidence("source-2"),
        structural_links=_links(),
        current_source_revision="source-2",
        current_graph_revision="graph-2",
        graph_complete=True,
    )
    test_action = _proposed("pytest tests/test_service.py -q", source_revision="source-2", call=2)
    engine.commit_postflight(
        test_action,
        returncode=0,
        output="1 passed",
        changed_paths=(),
        current_source_revision="source-2",
        current_graph_revision="graph-2",
        validation_status="pass",
    )

    assert engine.snapshot.validation.status is StateValidationStatus.PASS
    assert engine.snapshot.validation.source_revision == "source-2"
    assert engine.snapshot.phase in {StatePhase.VALIDATING, StatePhase.READY_TO_SUBMIT}
    assert engine.snapshot.current_failure is None


def test_canonical_declared_check_satisfies_obligation_through_shell_wrapper():
    engine = PersistentExecutionStateEngine.initialize_from_graph(
        task="Fix save_user and run its test.",
        catalog=_catalog(),
        structural_links=_links(),
        present_paths=("src/service.py", "tests/test_service.py"),
    )
    wrapped = _proposed("timeout 120 pytest tests/test_service.py -q")

    engine.commit_postflight(
        wrapped,
        returncode=0,
        output="1 passed",
        changed_paths=(),
        current_source_revision="source-1",
        current_graph_revision="graph-1",
        validation_status="pass",
        validation_check_id="pytest tests/test_service.py -q",
    )

    required_checks = [
        item
        for item in engine.snapshot.obligations
        if item.kind == "run_validation" and item.blocking
    ]
    assert len(required_checks) == 1
    assert required_checks[0].status.value == "satisfied"


def test_failed_validation_is_current_and_visible_in_critical_frame():
    catalog = _catalog()
    engine = PersistentExecutionStateEngine.initialize_from_graph(
        task="Fix save_user.",
        catalog=catalog,
        structural_links=_links(),
        present_paths=("src/service.py",),
    )
    focus = next(item.item_id for item in catalog.items if item.path == "src/service.py")
    engine.apply_bootstrap(
        parse_bootstrap_selection(
            json.dumps(
                {
                    "primary_focus_id": focus,
                    "ordered_item_ids": [focus],
                    "risk_item_ids": [],
                    "validation_item_ids": [],
                }
            ),
            catalog,
        ),
        current_source_revision="source-1",
    )
    action = _proposed("pytest tests/test_service.py -q")
    engine.commit_postflight(
        action,
        returncode=1,
        output="tests/test_service.py:9: AssertionError: expected 2",
        changed_paths=(),
        current_source_revision="source-1",
        current_graph_revision="graph-1",
        validation_status="fail",
    )
    frame = engine.compile_context(
        current_source_revision="source-1", provider_call=1, max_tokens=512
    )

    assert engine.snapshot.validation.status is StateValidationStatus.FAIL
    assert engine.snapshot.current_failure is not None
    assert frame.kind is ContextFrameKind.CRITICAL
    assert "AssertionError" in frame.rendered_text
    assert "pytest tests/test_service.py -q" in frame.rendered_text


def test_unattributed_validation_exit_does_not_manufacture_failure():
    engine = PersistentExecutionStateEngine.initialize_from_graph(
        task="Fix save_user.",
        catalog=_catalog(),
        structural_links=_links(),
        present_paths=("src/service.py",),
    )
    action = _proposed("pytest tests/test_service.py -q")

    engine.commit_postflight(
        action,
        returncode=1,
        output="the shell exit was not attributable",
        changed_paths=(),
        current_source_revision="source-1",
        current_graph_revision="graph-1",
        validation_status="unknown",
    )

    assert engine.snapshot.validation.status is StateValidationStatus.PENDING
    assert engine.snapshot.current_failure is None
    assert engine.snapshot.last_transition == "validation_outcome_unattributed"


def test_reading_required_deliverable_does_not_satisfy_production_obligation():
    catalog = build_bootstrap_catalog(
        instruction="Write reports/final.json.",
        evidence=_evidence(),
        documents=(_document("src/service.py", "save_user"),),
        structural_links=(),
        task_deliverables=("reports/final.json",),
        source_revision="source-1",
        graph_revision="graph-1",
        repository_complete=True,
    )
    engine = PersistentExecutionStateEngine.initialize_from_graph(
        task="Write reports/final.json.",
        catalog=catalog,
        structural_links=(),
        present_paths=("src/service.py", "reports/final.json"),
    )
    read = _proposed("cat reports/final.json")

    engine.commit_postflight(
        read,
        returncode=0,
        output="{}",
        changed_paths=(),
        current_source_revision="source-1",
        current_graph_revision="graph-1",
        validation_status="unknown",
    )

    obligation = next(item for item in engine.snapshot.obligations if item.blocking)
    assert obligation.kind == "produce_deliverable"
    assert obligation.status.value == "open"


def test_stale_revision_never_mutates_or_emits_state():
    engine = PersistentExecutionStateEngine.initialize_from_graph(
        task="Fix save_user.",
        catalog=_catalog(),
        structural_links=_links(),
        present_paths=("src/service.py",),
    )
    before = engine.snapshot
    stale = _proposed("sed -n '1,20p' src/service.py", source_revision="stale")

    projection = engine.project_preflight(stale, current_source_revision="source-1")
    engine.commit_postflight(
        stale,
        returncode=0,
        output="data",
        changed_paths=(),
        current_source_revision="source-1",
        current_graph_revision="graph-1",
        validation_status="unknown",
    )
    frame = engine.compile_context(current_source_revision="other", provider_call=1, max_tokens=512)

    assert projection.considered is False
    assert "stale_proposed_revision" in projection.reason_codes
    assert engine.snapshot == before
    assert frame.rendered_text == ""
    assert "stale_source_revision" in frame.reason_codes


def test_non_app_workspace_root_is_canonicalized_for_state_paths():
    engine = PersistentExecutionStateEngine.initialize_from_graph(
        task="Fix save_user.",
        catalog=_catalog(),
        structural_links=_links(),
        present_paths=("src/service.py",),
        workspace_root="/workspace/project",
    )
    action = _proposed("sed -n '1,20p' /workspace/project/src/service.py")

    projection = engine.project_preflight(action, current_source_revision="source-1")
    engine.commit_postflight(
        action,
        returncode=0,
        output="def save_user(): pass",
        changed_paths=(),
        current_source_revision="source-1",
        current_graph_revision="graph-1",
        validation_status="unknown",
    )

    assert projection.target_paths == ("src/service.py",)
    assert engine.snapshot.files_inspected == ("src/service.py",)


def test_deterministic_replay_produces_identical_state_and_context():
    def run_once():
        engine = PersistentExecutionStateEngine.initialize_from_graph(
            task="Fix save_user.",
            catalog=_catalog(),
            structural_links=_links(),
            present_paths=("src/service.py",),
        )
        action = _proposed("sed -n '1,20p' src/service.py")
        engine.project_preflight(action, current_source_revision="source-1")
        engine.commit_postflight(
            action,
            returncode=0,
            output="def save_user(): pass",
            changed_paths=(),
            current_source_revision="source-1",
            current_graph_revision="graph-1",
            validation_status="unknown",
        )
        frame = engine.compile_context(
            current_source_revision="source-1", provider_call=1, max_tokens=256
        )
        return engine.snapshot.as_dict(), frame.as_dict(), engine.receipts

    assert run_once() == run_once()


def test_raw_commands_and_outputs_are_not_persisted_in_state_receipts():
    engine = PersistentExecutionStateEngine.initialize_from_graph(
        task="Fix save_user.",
        catalog=_catalog(),
        structural_links=_links(),
        present_paths=("src/service.py",),
    )
    action = _proposed("python -c \"SECRET = 'do-not-store'\"")
    engine.project_preflight(action, current_source_revision="source-1")
    engine.commit_postflight(
        action,
        returncode=1,
        output="SECRET_OUTPUT do-not-store",
        changed_paths=(),
        current_source_revision="source-1",
        current_graph_revision="graph-1",
        validation_status="unknown",
    )

    serialized = json.dumps(
        {"state": engine.snapshot.as_dict(), "receipts": engine.receipts}, sort_keys=True
    )
    assert "do-not-store" not in serialized
    assert "SECRET_OUTPUT" not in serialized


def test_state_receipt_exposes_the_determinism_boundary_field_by_field():
    snapshot = PersistentExecutionStateEngine.initialize_from_graph(
        task="Fix save_user.",
        catalog=_catalog(),
        structural_links=_links(),
        present_paths=("src/service.py",),
    ).snapshot.as_dict()

    authorities = snapshot["field_authority"]
    assert authorities["primary_focus_id"] == "generative_bootstrap"
    assert authorities["current_focus_path"] == "executor_observed"
    assert authorities["phase"] == "deterministic_mutable"
    assert authorities["task_digest"] == "immutable_input"
