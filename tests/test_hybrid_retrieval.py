from __future__ import annotations

import math

import gt_engine.hybrid_retrieval as hybrid_module
from gt_engine.hybrid_retrieval import (
    BM25RetrievalChannel,
    DenseRetrievalChannel,
    ExactRetrievalChannel,
    HybridRetriever,
    LexicalRetrievalChannel,
    RepositoryDocument,
    RetrievalCandidate,
    RetrievalChannel,
    RetrievalIntent,
    RetrievalState,
    StructuralLink,
    StructuralRetrievalChannel,
    build_preemptive_frame,
    reciprocal_rank_fusion,
)


def _state(**overrides: object) -> RetrievalState:
    values: dict[str, object] = {
        "task_text": "repair allocator cleanup",
        "intent": RetrievalIntent.IMPLEMENTATION_CONTEXT,
        "source_revision": "source-1",
    }
    values.update(overrides)
    return RetrievalState(**values)


def _candidate(
    path: str,
    channel: RetrievalChannel,
    rank: int,
    *,
    text: str = "implementation",
) -> RetrievalCandidate:
    return RetrievalCandidate(
        path=path,
        start_line=1,
        end_line=2,
        symbol=None,
        text=text,
        channel=channel,
        channel_rank=rank,
        relation=None,
        provenance=(channel.value,),
        source_revision="source-1",
        channel_score=1.0 / rank,
    )


class FakeDenseBackend:
    """Deterministic semantic witness; no external model is involved."""

    identity = "fake-dense-v1"

    def embed_query(self, text: str) -> tuple[float, ...]:
        del text
        return (1.0, 0.0)

    def embed_documents(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        return tuple(
            (1.0, 0.0) if "releases reserved storage" in text else (0.0, 1.0) for text in texts
        )


class BrokenDenseBackend:
    def embed_query(self, text: str) -> tuple[float, ...]:
        del text
        raise RuntimeError("model unavailable")

    def embed_documents(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        del texts
        raise AssertionError("query failure should short-circuit")


def test_typed_state_builds_trajectory_conditioned_query_without_gold_fields():
    state = _state(
        task_text="repair allocator cleanup",
        active_paths=("src/allocator.py",),
        active_symbols=("Arena.release",),
        changed_paths=("src/pool.py",),
        diagnostics=("tests/test_pool.py:44 leaked block",),
        validation_state="fail",
    )

    query = state.query_text()

    assert "repair allocator cleanup" in query
    assert "src/allocator.py" in query
    assert "Arena.release" in query
    assert "tests/test_pool.py:44 leaked block" in query
    assert not hasattr(state, "gold_files")


def test_exact_lexical_and_bm25_channels_are_independent_rankers():
    documents = (
        RepositoryDocument(
            "src/allocator.py",
            "def cleanup_allocator(): pass",
            symbol="cleanup_allocator",
        ),
        RepositoryDocument("src/network.py", "def open_socket(): pass", symbol="open_socket"),
        RepositoryDocument("tests/test_allocator.py", "cleanup allocator regression test"),
    )
    state = _state(task_text="cleanup allocator")

    exact = ExactRetrievalChannel(documents).retrieve(state, limit=10)
    lexical = LexicalRetrievalChannel(documents).retrieve(state, limit=10)
    bm25 = BM25RetrievalChannel(documents).retrieve(state, limit=10)

    assert exact[0].path == "src/allocator.py"
    assert lexical[0].path in {"src/allocator.py", "tests/test_allocator.py"}
    assert bm25[0].path in {"src/allocator.py", "tests/test_allocator.py"}
    assert {row.channel for row in exact} == {RetrievalChannel.EXACT}
    assert {row.channel for row in lexical} == {RetrievalChannel.LEXICAL}
    assert {row.channel for row in bm25} == {RetrievalChannel.BM25}


def test_prepared_sparse_channels_do_not_retokenize_documents_per_query(monkeypatch):
    marker = "unique_document_marker"
    documents = (RepositoryDocument("src/allocator.py", f"cleanup allocator {marker}"),)
    retriever = HybridRetriever(documents, dense_backend=None)
    original = hybrid_module._tokens
    observed: list[str] = []

    def recording_tokens(text: str) -> tuple[str, ...]:
        observed.append(text)
        return original(text)

    monkeypatch.setattr(hybrid_module, "_tokens", recording_tokens)
    retriever.retrieve(_state(task_text="cleanup allocator"), token_budget=200)
    retriever.retrieve(_state(task_text="cleanup allocator again"), token_budget=200)

    assert not any(marker in text for text in observed)


def test_exact_channel_splits_snake_and_camel_case_symbols():
    documents = (
        RepositoryDocument(
            "src/helpers.py",
            "def cleanupAllocatorCache(): pass",
            symbol="cleanupAllocatorCache",
        ),
    )

    ranked = ExactRetrievalChannel(documents).retrieve(
        _state(task_text="repair allocator cache cleanup"),
        limit=10,
    )

    assert ranked[0].path == "src/helpers.py"
    assert "exact_symbol_token" in ranked[0].provenance


def test_dense_channel_finds_semantic_candidate_sparse_terms_do_not_name():
    documents = (
        RepositoryDocument("src/reclaimer.py", "releases reserved storage after use"),
        RepositoryDocument("src/socket.py", "opens a remote network connection"),
    )
    state = _state(task_text="repair allocator cleanup")

    dense = DenseRetrievalChannel(documents, FakeDenseBackend()).retrieve(state, limit=2)

    assert dense[0].path == "src/reclaimer.py"
    assert dense[0].channel is RetrievalChannel.DENSE


def test_dense_channel_can_use_a_bounded_cascade_candidate_pool():
    class CapturingBackend(FakeDenseBackend):
        documents: tuple[str, ...] = ()

        def embed_documents(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
            self.documents = texts
            return super().embed_documents(texts)

    backend = CapturingBackend()
    documents = tuple(
        RepositoryDocument(f"src/{index}.py", "releases reserved storage after use")
        for index in range(4)
    )
    channel = DenseRetrievalChannel(documents, backend)
    channel.set_candidate_paths(("src/2.py", "src/0.py"))

    result = channel.retrieve(_state(), limit=10)

    assert [row.path for row in result] == ["src/0.py", "src/2.py"]
    assert len(backend.documents) == 2
    assert "candidate_pool=2/4_docs/2_paths" in channel.availability_reason


def test_dense_candidate_limit_bounds_spans_when_a_path_has_many_documents():
    class CapturingBackend(FakeDenseBackend):
        documents: tuple[str, ...] = ()

        def embed_documents(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
            self.documents = texts
            return super().embed_documents(texts)

    backend = CapturingBackend()
    documents = tuple(
        RepositoryDocument(f"src/{index // 4}.py", "releases reserved storage after use")
        for index in range(12)
    )
    channel = DenseRetrievalChannel(documents, backend)
    channel.set_candidate_paths(("src/0.py", "src/1.py", "src/2.py"), document_limit=5)

    channel.retrieve(_state(), limit=10)

    assert len(backend.documents) == 5


def test_dense_backend_receives_path_symbol_and_exact_source_text():
    class CapturingBackend(FakeDenseBackend):
        documents: tuple[str, ...] = ()

        def embed_documents(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
            self.documents = texts
            return super().embed_documents(texts)

    backend = CapturingBackend()
    document = RepositoryDocument(
        "src/reclaimer.py",
        "releases reserved storage after use",
        symbol="release_pool",
    )

    DenseRetrievalChannel((document,), backend).retrieve(_state(), limit=1)

    assert "path: src/reclaimer.py" in backend.documents[0]
    assert "symbol: release_pool" in backend.documents[0]
    assert "releases reserved storage after use" in backend.documents[0]


def test_structural_channel_uses_known_path_as_seed_and_returns_related_file():
    documents = (
        RepositoryDocument("src/allocator.py", "def allocate(): pass"),
        RepositoryDocument("tests/test_allocator.py", "def test_allocate(): pass"),
    )
    links = (
        StructuralLink(
            source_path="src/allocator.py",
            target_path="tests/test_allocator.py",
            relation="tested_by",
            confidence=1.0,
        ),
    )
    state = _state(active_paths=("src/allocator.py",), intent=RetrievalIntent.VALIDATION_CONTEXT)

    ranked = StructuralRetrievalChannel(documents, links).retrieve(state, limit=10)

    assert [row.path for row in ranked] == ["tests/test_allocator.py"]
    assert ranked[0].relation == "tested_by"


def test_high_confidence_cochange_fact_is_not_alone_a_delivery_certificate():
    documents = (
        RepositoryDocument("src/anchor.py", "anchor_surface"),
        RepositoryDocument("src/neighbor.py", "zqxv_payload"),
    )
    state = _state(
        task_text="repair foobar",
        active_paths=("src/anchor.py",),
        intent=RetrievalIntent.CHANGE_IMPACT,
    )
    retriever = HybridRetriever(
        documents,
        structural_links=(
            StructuralLink(
                "src/anchor.py",
                "src/neighbor.py",
                "COCHANGE",
                confidence=1.0,
                certified=False,
            ),
        ),
    )

    result = retriever.retrieve(state, selection_limit=1)

    assert result.ranked_files[0].path == "src/neighbor.py"
    assert result.selected_context == ()
    assert result.abstained is True


def test_rrf_is_equal_weight_k60_and_aggregates_unique_files_deterministically():
    channel_results = {
        RetrievalChannel.LEXICAL: (
            _candidate("src/a.py", RetrievalChannel.LEXICAL, 1),
            _candidate("src/b.py", RetrievalChannel.LEXICAL, 2),
        ),
        RetrievalChannel.DENSE: (
            _candidate("src/b.py", RetrievalChannel.DENSE, 1),
            _candidate("src/a.py", RetrievalChannel.DENSE, 2),
            _candidate("src/a.py", RetrievalChannel.DENSE, 3),
        ),
    }

    ranked = reciprocal_rank_fusion(channel_results, k=60)

    assert [row.path for row in ranked] == ["src/a.py", "src/b.py"]
    assert math.isclose(ranked[0].fused_score, (1 / 61) + (1 / 62))
    assert math.isclose(ranked[1].fused_score, (1 / 62) + (1 / 61))
    assert ranked[0].channel_ranks == (
        (RetrievalChannel.LEXICAL, 1),
        (RetrievalChannel.DENSE, 2),
    )


def test_hybrid_selection_excludes_active_paths_and_prior_claims():
    documents = (
        RepositoryDocument("src/allocator.py", "cleanup allocator current implementation"),
        RepositoryDocument(
            "src/reclaimer.py",
            "allocator cleanup releases reserved storage after use",
        ),
        RepositoryDocument("tests/test_allocator.py", "cleanup allocator regression test"),
    )
    first = HybridRetriever(documents, dense_backend=FakeDenseBackend()).retrieve(
        _state(
            task_text="repair allocator cleanup in src/reclaimer.py",
            active_paths=("src/allocator.py",),
        ),
        selection_limit=3,
        token_budget=200,
    )
    exposed = first.selected_context[0].claim_hash

    second = HybridRetriever(documents, dense_backend=FakeDenseBackend()).retrieve(
        _state(
            task_text="repair allocator cleanup in src/reclaimer.py",
            active_paths=("src/allocator.py",),
            previously_exposed_claims=(exposed,),
        ),
        selection_limit=3,
        token_budget=200,
    )

    assert "src/allocator.py" not in {row.path for row in first.ranked_files}
    assert "src/allocator.py" not in {row.path for row in first.selected_context}
    assert exposed not in {row.claim_hash for row in second.selected_context}
    dense_receipt = next(
        row for row in first.channel_receipts if row.channel is RetrievalChannel.DENSE
    )
    assert dense_receipt.available is True
    assert dense_receipt.backend_identity == "fake-dense-v1"


def test_optional_dense_backend_failure_is_fail_open_and_receipted():
    documents = (
        RepositoryDocument("src/allocator.py", "cleanup allocator"),
        RepositoryDocument("src/unrelated.py", "network transport"),
    )
    result = HybridRetriever(documents, dense_backend=BrokenDenseBackend()).retrieve(
        _state(task_text="cleanup allocator"),
        token_budget=200,
    )

    assert result.ranked_files[0].path == "src/allocator.py"
    dense_receipt = next(
        row for row in result.channel_receipts if row.channel is RetrievalChannel.DENSE
    )
    assert dense_receipt.failed is True
    assert dense_receipt.available is False
    assert dense_receipt.candidate_count == 0
    assert "RuntimeError" in dense_receipt.reason


def test_absent_dense_backend_is_a_clean_abstaining_channel_not_an_error():
    result = HybridRetriever(
        (RepositoryDocument("src/allocator.py", "cleanup allocator"),),
        dense_backend=None,
    ).retrieve(_state(), token_budget=200)

    dense_receipt = next(
        row for row in result.channel_receipts if row.channel is RetrievalChannel.DENSE
    )
    assert dense_receipt.failed is False
    assert dense_receipt.available is False
    assert dense_receipt.reason == "backend_unavailable"


def test_selection_requires_certified_or_multi_channel_support():
    class WeakChannel:
        channel = RetrievalChannel.LEXICAL

        def retrieve(self, state: RetrievalState, *, limit: int) -> tuple[RetrievalCandidate, ...]:
            del state, limit
            return (_candidate("src/weak.py", RetrievalChannel.LEXICAL, 1),)

    result = HybridRetriever((), channels=(WeakChannel(),)).retrieve(_state())

    assert result.ranked_files[0].path == "src/weak.py"
    assert result.selected_context == ()
    assert result.abstained is True
    assert "insufficient_independent_support" in result.reason_codes


def test_lexical_and_bm25_are_one_sparse_family_for_abstention():
    class SparseChannel:
        def __init__(self, channel: RetrievalChannel) -> None:
            self.channel = channel

        def retrieve(self, state: RetrievalState, *, limit: int) -> tuple[RetrievalCandidate, ...]:
            del state, limit
            return (_candidate("src/sparse.py", self.channel, 1),)

    result = HybridRetriever(
        (),
        channels=(
            SparseChannel(RetrievalChannel.LEXICAL),
            SparseChannel(RetrievalChannel.BM25),
        ),
    ).retrieve(_state())

    assert result.ranked_files[0].support_count == 2
    assert result.selected_context == ()
    assert result.reason_codes == ("insufficient_independent_support",)


def test_dense_rerank_of_sparse_candidates_is_not_independent_delivery_support():
    class CandidateChannel:
        def __init__(self, channel: RetrievalChannel) -> None:
            self.channel = channel

        def retrieve(self, state: RetrievalState, *, limit: int) -> tuple[RetrievalCandidate, ...]:
            del state, limit
            return (_candidate("src/candidate.py", self.channel, 1),)

    result = HybridRetriever(
        (),
        channels=(
            CandidateChannel(RetrievalChannel.BM25),
            CandidateChannel(RetrievalChannel.DENSE),
        ),
    ).retrieve(_state())

    assert result.ranked_files[0].path == "src/candidate.py"
    assert result.selected_context == ()
    assert result.abstained is True
    assert result.reason_codes == ("insufficient_independent_support",)


def test_stale_revision_candidates_are_rejected_before_fusion():
    class StaleChannel:
        channel = RetrievalChannel.EXACT

        def retrieve(self, state: RetrievalState, *, limit: int) -> tuple[RetrievalCandidate, ...]:
            del state, limit
            return (
                RetrievalCandidate(
                    path="src/stale.py",
                    start_line=1,
                    end_line=2,
                    symbol="stale",
                    text="stale evidence",
                    channel=self.channel,
                    channel_rank=1,
                    relation=None,
                    provenance=("exact_symbol",),
                    source_revision="source-0",
                ),
            )

    result = HybridRetriever((), channels=(StaleChannel(),)).retrieve(_state())

    assert result.ranked_files == ()
    assert result.abstained is True
    assert "stale_candidates_rejected" in result.reason_codes


def test_selection_keeps_complete_evidence_and_never_truncates_to_fit_budget():
    class SupportedChannel:
        channel = RetrievalChannel.EXACT

        def retrieve(self, state: RetrievalState, *, limit: int) -> tuple[RetrievalCandidate, ...]:
            del state, limit
            return (
                RetrievalCandidate(
                    path="src/large.py",
                    start_line=1,
                    end_line=2,
                    symbol=None,
                    text=" ".join(f"token{i}" for i in range(80)),
                    channel=self.channel,
                    channel_rank=1,
                    relation=None,
                    provenance=("exact_path",),
                    source_revision="source-1",
                    channel_score=1.0,
                ),
            )

    result = HybridRetriever(
        (),
        channels=(SupportedChannel(),),
    ).retrieve(_state(), token_budget=10)

    assert result.selected_context == ()
    assert result.abstained is True
    assert "context_budget" in result.reason_codes


def test_preemptive_frame_is_bounded_revision_bound_and_replayable():
    documents = (
        RepositoryDocument("src/allocator.py", "cleanup allocator implementation"),
        RepositoryDocument("tests/test_allocator.py", "cleanup allocator regression"),
    )
    state = _state(
        task_text="inspect tests/test_allocator.py for cleanup allocator",
        active_paths=("src/allocator.py",),
    )
    result = HybridRetriever(documents).retrieve(state, token_budget=200)

    frame = build_preemptive_frame(result, state, trigger="diagnostic_changed")

    assert frame is not None
    assert frame.source_revision == "source-1"
    assert frame.trigger == "diagnostic_changed"
    assert frame.token_count <= 200
    assert frame.claim_hashes == tuple(row.claim_hash for row in result.selected_context)
    assert frame.query_hash


def test_preemptive_frame_is_none_when_retriever_abstains():
    result = HybridRetriever(()).retrieve(_state())

    assert result.abstained is True
    assert build_preemptive_frame(result, _state(), trigger="task_start") is None
