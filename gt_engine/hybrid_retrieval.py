"""Deterministic, trajectory-conditioned hybrid repository retrieval.

This module is deliberately independent from provider delivery and graph storage.
Callers adapt their repository index into :class:`RepositoryDocument` and
:class:`StructuralLink` values, then inject an optional dense backend.  Every
retrieval channel runs independently; fusion consumes ranks rather than
incomparable channel scores.
"""

from __future__ import annotations

import hashlib
import math
import re
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[0-9]+")
_PATH_SPLIT_RE = re.compile(r"[/\\.\-]+")


class RetrievalIntent(StrEnum):
    """The repository relationship needed for the agent's next decision."""

    IMPLEMENTATION_CONTEXT = "implementation_context"
    VALIDATION_CONTEXT = "validation_context"
    MISSING_CONTEXT = "missing_context"
    DIAGNOSTIC_ROOT_CAUSE = "diagnostic_root_cause"
    CHANGE_IMPACT = "change_impact"
    OTHER = "other"


class RetrievalChannel(StrEnum):
    EXACT = "exact"
    LEXICAL = "lexical"
    BM25 = "bm25"
    DENSE = "dense"
    STRUCTURAL = "structural"


_CHANNEL_ORDER = {
    RetrievalChannel.EXACT: 0,
    RetrievalChannel.LEXICAL: 1,
    RetrievalChannel.BM25: 2,
    RetrievalChannel.DENSE: 3,
    RetrievalChannel.STRUCTURAL: 4,
}


def _normalize_path(path: str) -> str:
    value = str(path or "").strip().replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    return value


def _tokens(value: str) -> tuple[str, ...]:
    tokens: list[str] = []
    for raw in _TOKEN_RE.findall(str(value or "")):
        tokens.append(raw.lower())
        expanded = raw.replace("_", " ")
        expanded = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", expanded)
        expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", expanded)
        tokens.extend(
            part.lower()
            for part in expanded.split()
            if part and part.lower() != raw.lower()
        )
    return tuple(tokens)


def _path_tokens(path: str) -> tuple[str, ...]:
    return tuple(
        token
        for part in _PATH_SPLIT_RE.split(_normalize_path(path))
        for token in _tokens(part)
    )


def _stable_hash(*parts: str) -> str:
    material = "\0".join(str(part) for part in parts)
    return hashlib.sha256(material.encode("utf-8", "surrogatepass")).hexdigest()


def _default_token_counter(text: str) -> int:
    """Return a deterministic conservative token approximation.

    Provider integrations can inject their exact tokenizer.  The default
    counts words and punctuation independently, so packing never depends on
    an optional model package.
    """

    return len(re.findall(r"\w+|[^\w\s]", str(text or ""), re.UNICODE))


@dataclass(frozen=True)
class RetrievalState:
    task_text: str
    intent: RetrievalIntent
    proposed_action: str | None = None
    active_paths: tuple[str, ...] = ()
    active_symbols: tuple[str, ...] = ()
    changed_paths: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
    validation_state: str = "unknown"
    source_revision: str = ""
    previously_exposed_claims: tuple[str, ...] = ()

    def query_text(self) -> str:
        """Compile only current trajectory state into a replayable query."""

        sections = (
            self.task_text,
            self.intent.value,
            self.proposed_action or "",
            " ".join(self.active_paths),
            " ".join(self.active_symbols),
            " ".join(self.changed_paths),
            " ".join(self.diagnostics),
            self.validation_state,
        )
        return "\n".join(section.strip() for section in sections if section.strip())

    def sparse_query_text(self) -> str:
        """Return sparse terms without creating false same-directory support.

        Active and changed paths seed the exact and structural channels.  Adding
        their generic directory/extension tokens (``src``, ``test``, ``py``)
        to lexical and BM25 makes those correlated channels appear to confirm
        almost every file in a repository.  Sparse retrieval instead consumes
        the task, typed intent, command, symbols, diagnostics, and validation
        state; exact path matching remains independently available.
        """

        sections = (
            self.task_text,
            self.intent.value,
            self.proposed_action or "",
            " ".join(self.active_symbols),
            " ".join(self.diagnostics),
            self.validation_state,
        )
        return "\n".join(section.strip() for section in sections if section.strip())

    @property
    def query_hash(self) -> str:
        return _stable_hash(self.query_text(), self.source_revision)


@dataclass(frozen=True)
class RepositoryDocument:
    path: str
    text: str
    start_line: int | None = 1
    end_line: int | None = None
    symbol: str | None = None
    provenance: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        normalized = _normalize_path(self.path)
        if not normalized:
            raise ValueError("repository document path must not be empty")
        object.__setattr__(self, "path", normalized)
        if self.end_line is None and self.start_line is not None:
            line_count = max(1, str(self.text or "").count("\n") + 1)
            object.__setattr__(self, "end_line", self.start_line + line_count - 1)


@dataclass(frozen=True)
class StructuralLink:
    source_path: str
    target_path: str
    relation: str
    confidence: float = 1.0
    provenance: tuple[str, ...] = ()
    certified: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_path", _normalize_path(self.source_path))
        object.__setattr__(self, "target_path", _normalize_path(self.target_path))
        if not self.source_path or not self.target_path:
            raise ValueError("structural link paths must not be empty")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("structural link confidence must be between zero and one")


@dataclass(frozen=True)
class RetrievalCandidate:
    path: str
    start_line: int | None
    end_line: int | None
    symbol: str | None
    text: str
    channel: RetrievalChannel
    channel_rank: int
    relation: str | None
    provenance: tuple[str, ...]
    source_revision: str
    channel_score: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _normalize_path(self.path))
        if not self.path:
            raise ValueError("candidate path must not be empty")
        if self.channel_rank < 1:
            raise ValueError("candidate rank must be one-based")

    @property
    def claim_hash(self) -> str:
        """Channel-independent identity for exact delivery deduplication."""

        normalized_text = " ".join(str(self.text or "").split())
        return _stable_hash(
            self.path.lower(),
            str(self.start_line or 0),
            str(self.end_line or 0),
            str(self.symbol or ""),
            normalized_text,
            self.source_revision,
        )


@dataclass(frozen=True)
class RankedFile:
    path: str
    fused_score: float
    channel_ranks: tuple[tuple[RetrievalChannel, int], ...]
    representative: RetrievalCandidate
    provenance: tuple[str, ...]

    @property
    def support_count(self) -> int:
        return len(self.channel_ranks)


@dataclass(frozen=True)
class ChannelReceipt:
    channel: RetrievalChannel
    candidate_count: int
    failed: bool
    reason: str
    latency_ms: float
    available: bool = True
    backend_identity: str = ""


@dataclass(frozen=True)
class HybridRetrievalResult:
    ranked_files: tuple[RankedFile, ...]
    ranked_spans: tuple[RetrievalCandidate, ...]
    selected_context: tuple[RetrievalCandidate, ...]
    abstained: bool
    reason_codes: tuple[str, ...]
    channel_receipts: tuple[ChannelReceipt, ...]
    latency_ms: float
    query_hash: str
    token_budget: int
    selected_token_count: int


@dataclass(frozen=True)
class PreemptiveRetrievalFrame:
    query_hash: str
    source_revision: str
    trigger: str
    evidence: tuple[RetrievalCandidate, ...]
    rendered_text: str
    token_count: int
    claim_hashes: tuple[str, ...]


@runtime_checkable
class RetrievalChannelBackend(Protocol):
    channel: RetrievalChannel

    def retrieve(
        self,
        state: RetrievalState,
        *,
        limit: int,
    ) -> Sequence[RetrievalCandidate]: ...


@runtime_checkable
class DenseEmbeddingBackend(Protocol):
    def embed_query(self, text: str) -> Sequence[float]: ...

    def embed_documents(self, texts: tuple[str, ...]) -> Sequence[Sequence[float]]: ...


def _document_candidate(
    document: RepositoryDocument,
    *,
    state: RetrievalState,
    channel: RetrievalChannel,
    rank: int,
    score: float,
    relation: str | None = None,
    provenance: tuple[str, ...] = (),
) -> RetrievalCandidate:
    return RetrievalCandidate(
        path=document.path,
        start_line=document.start_line,
        end_line=document.end_line,
        symbol=document.symbol,
        text=document.text,
        channel=channel,
        channel_rank=rank,
        relation=relation,
        provenance=tuple(dict.fromkeys((*document.provenance, *provenance, channel.value))),
        source_revision=state.source_revision,
        channel_score=float(score),
    )


def _rank_documents(
    scored: Sequence[tuple[float, RepositoryDocument, str | None, tuple[str, ...]]],
    *,
    state: RetrievalState,
    channel: RetrievalChannel,
    limit: int,
) -> tuple[RetrievalCandidate, ...]:
    ordered = sorted(
        (row for row in scored if row[0] > 0.0),
        key=lambda row: (-row[0], row[1].path.lower(), row[1].start_line or 0),
    )
    return tuple(
        _document_candidate(
            document,
            state=state,
            channel=channel,
            rank=rank,
            score=score,
            relation=relation,
            provenance=provenance,
        )
        for rank, (score, document, relation, provenance) in enumerate(
            ordered[: max(0, limit)], 1
        )
    )


class ExactRetrievalChannel:
    channel = RetrievalChannel.EXACT

    def __init__(self, documents: Sequence[RepositoryDocument]) -> None:
        self._documents = tuple(documents)

    def retrieve(
        self,
        state: RetrievalState,
        *,
        limit: int,
    ) -> tuple[RetrievalCandidate, ...]:
        query_tokens = set(_tokens(state.query_text()))
        query_text = state.query_text().lower()
        path_document_frequency = Counter(
            token
            for document in self._documents
            for token in set(_path_tokens(document.path))
        )
        distinctive_path_frequency = max(1, math.ceil(len(self._documents) * 0.20))
        scored: list[tuple[float, RepositoryDocument, str | None, tuple[str, ...]]] = []
        for document in self._documents:
            path_tokens = set(_path_tokens(document.path))
            symbol_tokens = set(_tokens(document.symbol or ""))
            text = str(document.text or "").lower()
            score = 0.0
            reasons: list[str] = []
            path_overlap = {
                token
                for token in query_tokens & path_tokens
                if path_document_frequency[token] <= distinctive_path_frequency
            }
            symbol_overlap = query_tokens & symbol_tokens
            if path_overlap:
                score += 5.0 * len(path_overlap)
                reasons.append("exact_path_token")
            if symbol_overlap:
                score += 6.0 * len(symbol_overlap)
                reasons.append("exact_symbol_token")
            normalized_path = document.path.lower()
            if normalized_path in query_text:
                score += 10.0
                reasons.append("exact_path")
            if document.symbol and document.symbol.lower() in query_text:
                score += 10.0
                reasons.append("exact_symbol")
            exact_phrases = {
                part.strip().lower()
                for part in (state.task_text, *(state.diagnostics or ()))
                if len(part.strip()) >= 8
            }
            if any(phrase in text for phrase in exact_phrases):
                score += 2.0
                reasons.append("exact_phrase")
            scored.append((score, document, None, tuple(reasons)))
        return _rank_documents(scored, state=state, channel=self.channel, limit=limit)


class LexicalRetrievalChannel:
    channel = RetrievalChannel.LEXICAL

    def __init__(self, documents: Sequence[RepositoryDocument]) -> None:
        self._documents = tuple(documents)

    def retrieve(
        self,
        state: RetrievalState,
        *,
        limit: int,
    ) -> tuple[RetrievalCandidate, ...]:
        query = Counter(_tokens(state.sparse_query_text()))
        scored: list[tuple[float, RepositoryDocument, str | None, tuple[str, ...]]] = []
        for document in self._documents:
            terms = Counter(
                (
                    *_path_tokens(document.path),
                    *_tokens(document.symbol or ""),
                    *_tokens(document.text),
                )
            )
            overlap = set(query) & set(terms)
            numerator = sum(min(query[token], terms[token]) for token in overlap)
            denominator = sum(query.values()) + sum(terms.values()) - numerator
            score = float(numerator / denominator) if denominator else 0.0
            scored.append((score, document, None, ("lexical_token_overlap",)))
        return _rank_documents(scored, state=state, channel=self.channel, limit=limit)


class BM25RetrievalChannel:
    channel = RetrievalChannel.BM25

    def __init__(
        self,
        documents: Sequence[RepositoryDocument],
        *,
        k1: float = 1.2,
        b: float = 0.75,
    ) -> None:
        self._documents = tuple(documents)
        self._k1 = float(k1)
        self._b = float(b)

    def retrieve(
        self,
        state: RetrievalState,
        *,
        limit: int,
    ) -> tuple[RetrievalCandidate, ...]:
        query_terms = tuple(dict.fromkeys(_tokens(state.sparse_query_text())))
        tokenized = tuple(
            (
                document,
                tuple(
                    (
                        *_path_tokens(document.path),
                        *_tokens(document.symbol or ""),
                        *_tokens(document.text),
                    )
                ),
            )
            for document in self._documents
        )
        if not tokenized or not query_terms:
            return ()
        document_count = len(tokenized)
        average_length = sum(len(terms) for _, terms in tokenized) / document_count
        frequencies = {
            term: sum(1 for _, terms in tokenized if term in set(terms))
            for term in query_terms
        }
        scored: list[tuple[float, RepositoryDocument, str | None, tuple[str, ...]]] = []
        for document, terms in tokenized:
            counts = Counter(terms)
            length_ratio = len(terms) / average_length if average_length else 1.0
            score = 0.0
            for term in query_terms:
                frequency = counts[term]
                if frequency <= 0:
                    continue
                document_frequency = frequencies[term]
                inverse_frequency = math.log(
                    1.0 + (document_count - document_frequency + 0.5) / (document_frequency + 0.5)
                )
                denominator = frequency + self._k1 * (1.0 - self._b + self._b * length_ratio)
                score += inverse_frequency * (frequency * (self._k1 + 1.0)) / denominator
            scored.append((score, document, None, ("bm25",)))
        return _rank_documents(scored, state=state, channel=self.channel, limit=limit)


class DenseRetrievalChannel:
    channel = RetrievalChannel.DENSE

    def __init__(
        self,
        documents: Sequence[RepositoryDocument],
        backend: DenseEmbeddingBackend | None,
    ) -> None:
        self._documents = tuple(documents)
        self._backend = backend
        self._candidate_paths: frozenset[str] | None = None
        self.availability_reason = ""

    def set_candidate_paths(self, paths: Sequence[str] | None) -> None:
        """Restrict this pass to a deterministic cascade candidate pool."""

        self._candidate_paths = (
            None
            if paths is None
            else frozenset(str(path).strip().lower() for path in paths if str(path).strip())
        )

    @property
    def backend_identity(self) -> str:
        if self._backend is None:
            return ""
        return str(
            getattr(self._backend, "identity", type(self._backend).__qualname__)
        )

    def retrieve(
        self,
        state: RetrievalState,
        *,
        limit: int,
    ) -> tuple[RetrievalCandidate, ...]:
        if self._backend is None:
            self.availability_reason = "backend_unavailable"
            return ()
        selected_documents = (
            self._documents
            if self._candidate_paths is None
            else tuple(
                document
                for document in self._documents
                if document.path.lower() in self._candidate_paths
            )
        )
        if not selected_documents:
            self.availability_reason = "candidate_pool_empty"
            return ()
        self.availability_reason = (
            ""
            if self._candidate_paths is None
            else f"candidate_pool={len(selected_documents)}/{len(self._documents)}"
        )
        query = tuple(float(item) for item in self._backend.embed_query(state.query_text()))
        document_texts = tuple(
            "\n".join(
                part
                for part in (
                    f"path: {document.path}",
                    f"symbol: {document.symbol}" if document.symbol else "",
                    document.text,
                )
                if part
            )
            for document in selected_documents
        )
        embeddings = tuple(
            tuple(float(item) for item in row)
            for row in self._backend.embed_documents(document_texts)
        )
        if len(embeddings) != len(selected_documents):
            raise ValueError("dense backend returned a different number of document embeddings")
        query_norm = math.sqrt(sum(value * value for value in query))
        scored: list[tuple[float, RepositoryDocument, str | None, tuple[str, ...]]] = []
        for document, embedding in zip(selected_documents, embeddings, strict=True):
            if len(embedding) != len(query):
                raise ValueError("dense backend returned inconsistent embedding dimensions")
            document_norm = math.sqrt(sum(value * value for value in embedding))
            denominator = query_norm * document_norm
            cosine = (
                sum(left * right for left, right in zip(query, embedding, strict=True))
                / denominator
                if denominator
                else 0.0
            )
            # Negative cosine is not useful evidence and must not be ranked.
            scored.append((max(0.0, cosine), document, None, ("dense_cosine",)))
        return _rank_documents(scored, state=state, channel=self.channel, limit=limit)


class StructuralRetrievalChannel:
    channel = RetrievalChannel.STRUCTURAL

    def __init__(
        self,
        documents: Sequence[RepositoryDocument],
        links: Sequence[StructuralLink],
    ) -> None:
        self._documents = {document.path.lower(): document for document in documents}
        self._links = tuple(links)

    def retrieve(
        self,
        state: RetrievalState,
        *,
        limit: int,
    ) -> tuple[RetrievalCandidate, ...]:
        seeds = {
            _normalize_path(path).lower()
            for path in (*state.active_paths, *state.changed_paths)
            if _normalize_path(path)
        }
        if not seeds:
            return ()
        best: dict[str, tuple[float, RepositoryDocument, str, tuple[str, ...]]] = {}
        for link in self._links:
            source = link.source_path.lower()
            target = link.target_path.lower()
            if source in seeds and target not in seeds:
                candidate_path = target
                relation = link.relation
            elif target in seeds and source not in seeds:
                candidate_path = source
                relation = f"inverse:{link.relation}"
            else:
                continue
            document = self._documents.get(candidate_path)
            if document is None:
                continue
            provenance = (*link.provenance, f"structural:{relation}")
            if link.certified:
                provenance = (*provenance, "structural_certified")
            row = (
                float(link.confidence),
                document,
                relation,
                tuple(dict.fromkeys(provenance)),
            )
            previous = best.get(candidate_path)
            if previous is None or (row[0], relation) > (previous[0], previous[2]):
                best[candidate_path] = row
        return _rank_documents(
            tuple(best.values()), state=state, channel=self.channel, limit=limit
        )


def reciprocal_rank_fusion(
    channel_results: dict[RetrievalChannel, Sequence[RetrievalCandidate]],
    *,
    k: int = 60,
) -> tuple[RankedFile, ...]:
    """Fuse independent ranks with equal-weight RRF and stable path ties."""

    if k < 1:
        raise ValueError("RRF k must be positive")
    per_path: dict[str, dict[RetrievalChannel, RetrievalCandidate]] = defaultdict(dict)
    display_paths: dict[str, str] = {}
    for channel in sorted(channel_results, key=lambda item: _CHANNEL_ORDER[item]):
        for candidate in channel_results[channel]:
            key = candidate.path.lower()
            display_paths.setdefault(key, candidate.path)
            previous = per_path[key].get(channel)
            if previous is None or candidate.channel_rank < previous.channel_rank:
                per_path[key][channel] = candidate

    fused: list[RankedFile] = []
    for key, by_channel in per_path.items():
        channel_ranks = tuple(
            (channel, by_channel[channel].channel_rank)
            for channel in sorted(by_channel, key=lambda item: _CHANNEL_ORDER[item])
        )
        score = sum(1.0 / (k + rank) for _, rank in channel_ranks)
        representative = min(
            by_channel.values(),
            key=lambda row: (
                row.channel_rank,
                _CHANNEL_ORDER[row.channel],
                row.start_line or 0,
                row.claim_hash,
            ),
        )
        provenance = tuple(
            dict.fromkeys(
                item
                for channel in sorted(by_channel, key=lambda value: _CHANNEL_ORDER[value])
                for item in by_channel[channel].provenance
            )
        )
        fused.append(
            RankedFile(
                path=display_paths[key],
                fused_score=score,
                channel_ranks=channel_ranks,
                representative=representative,
                provenance=provenance,
            )
        )
    return tuple(sorted(fused, key=lambda row: (-row.fused_score, row.path.lower(), row.path)))


def _render_candidate(candidate: RetrievalCandidate) -> str:
    location = candidate.path
    if candidate.start_line is not None:
        location += f":{candidate.start_line}"
        if candidate.end_line is not None and candidate.end_line != candidate.start_line:
            location += f"-{candidate.end_line}"
    metadata = [location]
    if candidate.symbol:
        metadata.append(f"symbol={candidate.symbol}")
    if candidate.relation:
        metadata.append(f"relation={candidate.relation}")
    return f"[GT repository evidence: {'; '.join(metadata)}]\n{candidate.text.strip()}"


def _delivery_supported(ranked: RankedFile) -> bool:
    channels = {channel for channel, _ in ranked.channel_ranks}
    if (
        RetrievalChannel.STRUCTURAL in channels
        and "structural_certified" in ranked.provenance
    ):
        return True
    if RetrievalChannel.EXACT in channels and (
        "exact_path" in ranked.provenance or "exact_symbol" in ranked.provenance
    ):
        return True
    # Lexical, BM25, and weak exact-token overlap are correlated sparse
    # signals, not three independent confirmations.
    families: set[str] = set()
    if channels & {
        RetrievalChannel.EXACT,
        RetrievalChannel.LEXICAL,
        RetrievalChannel.BM25,
    }:
        families.add("sparse")
    if RetrievalChannel.DENSE in channels:
        families.add("dense")
    if RetrievalChannel.STRUCTURAL in channels:
        families.add("structural")
    return len(families) >= 2


class HybridRetriever:
    """Run independent channels, fuse files, then pack bounded new evidence."""

    def __init__(
        self,
        documents: Sequence[RepositoryDocument],
        *,
        structural_links: Sequence[StructuralLink] = (),
        dense_backend: DenseEmbeddingBackend | None = None,
        channels: Sequence[RetrievalChannelBackend] | None = None,
        token_counter: Callable[[str], int] = _default_token_counter,
        rrf_k: int = 60,
        dense_candidate_limit: int | None = None,
    ) -> None:
        documents = tuple(documents)
        self._channels: tuple[RetrievalChannelBackend, ...] = (
            tuple(channels)
            if channels is not None
            else (
                ExactRetrievalChannel(documents),
                LexicalRetrievalChannel(documents),
                BM25RetrievalChannel(documents),
                StructuralRetrievalChannel(documents, structural_links),
                DenseRetrievalChannel(documents, dense_backend),
            )
        )
        present = [channel.channel for channel in self._channels]
        if len(present) != len(set(present)):
            raise ValueError("each retrieval channel may be registered at most once")
        self._token_counter = token_counter
        self._rrf_k = int(rrf_k)
        self._dense_candidate_limit = (
            None
            if dense_candidate_limit is None
            else max(1, int(dense_candidate_limit))
        )
        self._dense_channel = next(
            (
                channel
                for channel in self._channels
                if isinstance(channel, DenseRetrievalChannel)
            ),
            None,
        )

    def retrieve(
        self,
        state: RetrievalState,
        *,
        channel_limit: int = 100,
        top_k: int = 20,
        selection_limit: int = 3,
        token_budget: int = 1_200,
    ) -> HybridRetrievalResult:
        started = time.perf_counter()
        channel_results: dict[RetrievalChannel, tuple[RetrievalCandidate, ...]] = {}
        receipts: list[ChannelReceipt] = []
        stale_candidates_rejected = 0
        for channel in self._channels:
            if (
                self._dense_candidate_limit is not None
                and isinstance(channel, DenseRetrievalChannel)
            ):
                non_dense = tuple(
                    result
                    for key, result in channel_results.items()
                    if key is not RetrievalChannel.DENSE
                )
                pool: list[str] = []
                seen: set[str] = set()
                width = max(
                    1,
                    self._dense_candidate_limit // max(1, len(non_dense)),
                )
                for rank in range(width):
                    for result in non_dense:
                        if rank >= len(result):
                            continue
                        path = result[rank].path
                        key = path.lower()
                        if key not in seen:
                            seen.add(key)
                            pool.append(path)
                            if len(pool) >= self._dense_candidate_limit:
                                break
                    if len(pool) >= self._dense_candidate_limit:
                        break
                channel.set_candidate_paths(pool)
            channel_started = time.perf_counter()
            failed = False
            reason = ""
            try:
                raw_candidates = tuple(
                    channel.retrieve(state, limit=max(0, channel_limit))
                )
                candidates = tuple(
                    candidate
                    for candidate in raw_candidates
                    if candidate.source_revision == state.source_revision
                )
                stale_count = len(raw_candidates) - len(candidates)
                stale_candidates_rejected += stale_count
                if stale_count:
                    reason = f"stale_revision_rejected={stale_count}"
                if channel.channel is RetrievalChannel.DENSE:
                    reason = reason or str(
                        getattr(channel, "availability_reason", "") or ""
                    )
            except Exception as exc:  # noqa: BLE001 - retrieval must fail open
                candidates = ()
                failed = True
                reason = f"{type(exc).__name__}: {exc}"[:300]
            channel_results[channel.channel] = candidates
            receipts.append(
                ChannelReceipt(
                    channel=channel.channel,
                    candidate_count=len(candidates),
                    failed=failed,
                    reason=reason,
                    latency_ms=(time.perf_counter() - channel_started) * 1_000.0,
                    available=not failed and reason != "backend_unavailable",
                    backend_identity=str(
                        getattr(channel, "backend_identity", "") or ""
                    ),
                )
            )

        fused = reciprocal_rank_fusion(channel_results, k=self._rrf_k)
        known_paths = {
            _normalize_path(path).lower()
            for path in (*state.active_paths, *state.changed_paths)
            if _normalize_path(path)
        }
        ranked_files = tuple(
            row for row in fused if row.path.lower() not in known_paths
        )[: max(0, top_k)]
        ranked_spans = tuple(row.representative for row in ranked_files)
        exposed = set(state.previously_exposed_claims)
        selected: list[RetrievalCandidate] = []
        selected_rendered: list[str] = []
        selected_tokens = 0
        saw_supported = False
        skipped_budget = False
        skipped_duplicate = False
        for ranked in ranked_files:
            if len(selected) >= max(0, selection_limit):
                break
            if not _delivery_supported(ranked):
                continue
            saw_supported = True
            candidate = ranked.representative
            if candidate.claim_hash in exposed:
                skipped_duplicate = True
                continue
            rendered = _render_candidate(candidate)
            combined = "\n\n".join((*selected_rendered, rendered))
            combined_tokens = self._token_counter(combined)
            if combined_tokens <= selected_tokens:
                continue
            if combined_tokens > max(0, token_budget):
                skipped_budget = True
                continue
            selected.append(candidate)
            selected_rendered.append(rendered)
            selected_tokens = combined_tokens
            exposed.add(candidate.claim_hash)

        reasons: list[str] = []
        if not ranked_files:
            reasons.append("no_candidates")
        if stale_candidates_rejected:
            reasons.append("stale_candidates_rejected")
        if ranked_files and not saw_supported:
            reasons.append("insufficient_independent_support")
        if skipped_duplicate:
            reasons.append("already_visible_or_delivered")
        if skipped_budget:
            reasons.append("context_budget")
        if selected:
            reasons.append("selected_bounded_context")
        elif saw_supported and not skipped_budget and not skipped_duplicate:
            reasons.append("no_complete_evidence")

        return HybridRetrievalResult(
            ranked_files=ranked_files,
            ranked_spans=ranked_spans,
            selected_context=tuple(selected),
            abstained=not selected,
            reason_codes=tuple(dict.fromkeys(reasons)),
            channel_receipts=tuple(receipts),
            latency_ms=(time.perf_counter() - started) * 1_000.0,
            query_hash=state.query_hash,
            token_budget=max(0, token_budget),
            selected_token_count=selected_tokens,
        )


def build_preemptive_frame(
    result: HybridRetrievalResult,
    state: RetrievalState,
    *,
    trigger: str,
) -> PreemptiveRetrievalFrame | None:
    """Compile selected evidence without changing any legacy delivery stream."""

    if result.abstained or not result.selected_context:
        return None
    if result.query_hash != state.query_hash:
        return None
    rendered = "\n\n".join(_render_candidate(candidate) for candidate in result.selected_context)
    return PreemptiveRetrievalFrame(
        query_hash=result.query_hash,
        source_revision=state.source_revision,
        trigger=str(trigger or "unknown"),
        evidence=result.selected_context,
        rendered_text=rendered,
        token_count=result.selected_token_count,
        claim_hashes=tuple(candidate.claim_hash for candidate in result.selected_context),
    )


__all__ = [
    "BM25RetrievalChannel",
    "ChannelReceipt",
    "DenseEmbeddingBackend",
    "DenseRetrievalChannel",
    "ExactRetrievalChannel",
    "HybridRetrievalResult",
    "HybridRetriever",
    "LexicalRetrievalChannel",
    "PreemptiveRetrievalFrame",
    "RankedFile",
    "RepositoryDocument",
    "RetrievalCandidate",
    "RetrievalChannel",
    "RetrievalChannelBackend",
    "RetrievalIntent",
    "RetrievalState",
    "StructuralLink",
    "StructuralRetrievalChannel",
    "build_preemptive_frame",
    "reciprocal_rank_fusion",
]
