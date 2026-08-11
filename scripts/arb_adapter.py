#!/usr/bin/env python3
"""Gold-isolated Agent Retrieval Bench adapter for the shared GT retriever.

The adapter is deliberately benchmark-only.  It does not change the central
runtime and it never reads expected files, patches, or evaluator labels while
constructing a retrieval query.  Each redacted JSONL row points at an already
checked-out repository snapshot and is mapped into the same typed state,
bounded repository corpus, hybrid channels, fusion, and selection used by the
runtime.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gt_engine.hybrid_repository import HybridRepository, build_hybrid_repository
from gt_engine.hybrid_retrieval import (
    DenseEmbeddingBackend,
    HybridRetrievalResult,
    HybridRetriever,
    RankedFile,
    RetrievalChannel,
    RetrievalIntent,
    RetrievalState,
    build_preemptive_frame,
)
from gt_engine.indexer import IndexBuildReceipt
from gt_engine.repository_intelligence import inspect_repository


class RedactedSampleError(ValueError):
    """Raised when the benchmark input could leak evaluator information."""


# These keys are never valid query state.  Gold data must be joined after the
# adapter finishes, not carried through the runner under a different name.
_FORBIDDEN_KEYS = frozenset(
    {
        "gold",
        "gold_files",
        "expected",
        "expected_files",
        "patch",
        "gold_patch",
        "fix",
        "fix_files",
        "target_files",
        "evaluator",
        "labels",
    }
)


@dataclass(frozen=True, slots=True)
class RetrievalProbe:
    sample_id: str
    repository: str
    base_commit: str
    instruction: str
    active_paths: tuple[str, ...]
    source_revision: str
    task_type: str = ""


@dataclass(frozen=True, slots=True)
class RetrievalProbeResult:
    sample_id: str
    repository: str
    base_commit: str
    task_type: str
    retrieval_intent: str
    ranked_candidates: tuple[dict[str, Any], ...]
    delivered_evidence: tuple[dict[str, Any], ...]
    abstained: bool
    abstention_reason: str | None
    graph_status: str
    graph_revision: str
    source_revision: str
    index_latency_ms: float
    query_latency_ms: float
    index_cache_hit: bool = False
    repository_cache_hit: bool = False
    query_hash: str = ""
    selected_token_count: int = 0
    payload_chars: int = 0
    payload_tokens: int = 0
    channel_receipts: tuple[dict[str, Any], ...] = ()
    dense_backend_receipt: dict[str, Any] | None = None
    retrieval_reason_codes: tuple[str, ...] = ()
    repository_complete: bool = False
    repository_reason_codes: tuple[str, ...] = ()
    repository_document_count: int = 0
    repository_document_chars: int = 0
    repository_structural_link_count: int = 0
    # Index-build diagnostics are part of the retrieval measurement.  A bare
    # ``index_unavailable`` status cannot distinguish a missing executable,
    # parser/coverage failure, invalid SQLite schema, or a build exception,
    # which makes a GitHub run impossible to diagnose or promote.
    index_error_type: str | None = None
    index_error_diagnostic: str = ""
    index_source_files: int = 0
    index_indexable_files: int = 0
    index_schema_valid: bool = False
    index_node_count: int = 0
    index_edge_count: int = 0
    index_binary_sha256: str = ""


def _walk_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            keys.add(str(key).lower())
            keys.update(_walk_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.update(_walk_keys(child))
    return keys


def _paths(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list | tuple):
        raise RedactedSampleError("given_files/active_paths must be a list")
    result: list[str] = []
    for raw in value:
        path = str(raw or "").replace("\\", "/").strip()
        if path and path not in result:
            result.append(path)
    return tuple(result)


def normalize_sample(raw: dict[str, Any]) -> RetrievalProbe:
    """Validate and normalize one gold-free ARB input row."""

    forbidden = sorted(_FORBIDDEN_KEYS & _walk_keys(raw))
    if forbidden:
        raise RedactedSampleError(
            "gold/fix leakage in redacted sample: " + ", ".join(forbidden)
        )
    sample_id = str(raw.get("sample_id") or raw.get("id") or "").strip()
    repository = str(raw.get("repository") or raw.get("repo") or "").strip()
    base_commit = str(raw.get("base_commit") or "").strip()
    instruction = str(raw.get("instruction") or raw.get("query") or "").strip()
    if not sample_id or not repository or not base_commit or not instruction:
        raise RedactedSampleError(
            "sample_id, repository, base_commit, and instruction/query are required"
        )
    active_paths = _paths(raw.get("active_paths", raw.get("given_files")))
    task_type = str(raw.get("task_type") or "").strip().lower()
    source_revision = str(raw.get("source_revision") or f"arb:{base_commit}")
    return RetrievalProbe(
        sample_id=sample_id,
        repository=repository,
        base_commit=base_commit,
        instruction=instruction,
        task_type=task_type,
        active_paths=active_paths,
        source_revision=source_revision,
    )


def _intent_for_task_type(task_type: str) -> RetrievalIntent:
    """Map ARB's public task family to the production retrieval vocabulary."""

    return {
        "code2test": RetrievalIntent.VALIDATION_CONTEXT,
        "comment2context": RetrievalIntent.MISSING_CONTEXT,
        "trace2code": RetrievalIntent.DIAGNOSTIC_ROOT_CAUSE,
        "edit2ripple": RetrievalIntent.CHANGE_IMPACT,
    }.get(str(task_type or "").strip().lower(), RetrievalIntent.OTHER)


def load_redacted_samples(path: str | Path) -> tuple[RetrievalProbe, ...]:
    rows: list[RetrievalProbe] = []
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RedactedSampleError(f"invalid JSON on line {line_number}") from exc
        if not isinstance(raw, dict):
            raise RedactedSampleError(f"line {line_number} is not an object")
        rows.append(normalize_sample(raw))
    return tuple(rows)


def _evidence_row(item: Any) -> dict[str, Any]:
    if hasattr(item, "to_receipt"):
        return dict(item.to_receipt())
    return asdict(item)


def _source_chunk(
    row: dict[str, Any],
    *,
    repo_root: str | Path,
    graph_db: str | None,
    max_chars: int = 12_000,
) -> dict[str, Any]:
    """Persist the exact ranked source span used by ARB evaluation.

    GraphEvidence intentionally remains a small runtime receipt.  The ARB
    artifact needs a reproducible source window for line/block/BCY metrics, so
    this benchmark-only layer resolves the indexed node range and reads the
    corresponding base-checkout bytes.  Missing/ambiguous ranges degrade to a
    one-line window; they never fabricate a span.
    """

    path = str(row.get("file_path") or "").replace("\\", "/")
    start = int(row.get("line") or 0)
    end = start
    excerpt = ""
    if graph_db and path:
        try:
            connection = sqlite3.connect(
                f"file:{Path(graph_db).resolve().as_posix()}?mode=ro", uri=True
            )
            try:
                result = connection.execute(
                    "SELECT start_line,end_line,COALESCE(signature,'') "
                    "FROM nodes WHERE file_path=? AND name=? "
                    "ORDER BY start_line,id LIMIT 1",
                    (path, str(row.get("symbol") or "")),
                ).fetchone()
            finally:
                connection.close()
            if result:
                start = int(result[0] or start or 0)
                end = int(result[1] or start)
                excerpt = str(result[2] or "")
        except (OSError, sqlite3.Error, TypeError, ValueError):
            # Source persistence must not make retrieval fail.  The receipt
            # still records a conservative source window below.
            pass

    source_path = (Path(repo_root) / Path(path)).resolve()
    root = Path(repo_root).resolve()
    try:
        source_path.relative_to(root)
    except ValueError:
        source_path = root / Path(path)
    source_text = ""
    try:
        lines = source_path.read_text(encoding="utf-8", errors="replace").splitlines()
        if start <= 0:
            start = 1
        if end < start:
            end = start
        source_text = "\n".join(lines[start - 1 : end])
    except OSError:
        source_text = excerpt
    if not source_text:
        source_text = excerpt
    source_text = source_text[:max_chars]
    return {
        "path": path,
        "start_line": start,
        "end_line": max(start, end),
        "text": source_text,
    }


def _attach_source_chunks(
    rows: tuple[dict[str, Any], ...],
    *,
    repo_root: str | Path,
    graph_db: str | None,
) -> tuple[dict[str, Any], ...]:
    output: list[dict[str, Any]] = []
    for row in rows:
        enriched = dict(row)
        chunk = _source_chunk(enriched, repo_root=repo_root, graph_db=graph_db)
        enriched["source_span"] = {
            "path": chunk["path"],
            "start_line": chunk["start_line"],
            "end_line": chunk["end_line"],
        }
        enriched["source_text"] = chunk["text"]
        enriched["source_chunk"] = chunk
        output.append(enriched)
    return tuple(output)


def _confidence_fields(ranked: RankedFile) -> tuple[float | None, str]:
    provenance = set(ranked.provenance)
    if "exact_path" in provenance or "exact_symbol" in provenance:
        return 1.0, "mechanically_exact"
    if "structural_certified" in provenance:
        return 1.0, "certified_graph_relation"
    channels = {channel for channel, _rank in ranked.channel_ranks}
    sparse = bool(
        channels
        & {
            RetrievalChannel.EXACT,
            RetrievalChannel.LEXICAL,
            RetrievalChannel.BM25,
        }
    )
    if sparse and RetrievalChannel.DENSE in channels:
        return None, "cross_channel_corroborated_uncalibrated"
    return None, "rank_only_uncalibrated"


def _ranked_row(ranked: RankedFile, *, rank: int) -> dict[str, Any]:
    candidate = ranked.representative
    confidence, confidence_kind = _confidence_fields(ranked)
    source_span = {
        "path": candidate.path,
        "start_line": candidate.start_line,
        "end_line": candidate.end_line,
    }
    return {
        "rank": rank,
        "path": candidate.path,
        "file_path": candidate.path,
        "symbol": candidate.symbol or "",
        "start_line": candidate.start_line,
        "end_line": candidate.end_line,
        "source_span": source_span,
        "source_text": candidate.text,
        "source_chunk": {**source_span, "text": candidate.text},
        "relation": candidate.relation,
        "fused_score": ranked.fused_score,
        "channel_ranks": tuple(
            {"channel": channel.value, "rank": channel_rank}
            for channel, channel_rank in ranked.channel_ranks
        ),
        "representative_channel": candidate.channel.value,
        "representative_channel_score": candidate.channel_score,
        "provenance": ranked.provenance,
        "confidence": confidence,
        "confidence_kind": confidence_kind,
        "source_revision": candidate.source_revision,
        "claim_hash": candidate.claim_hash,
    }


def _hybrid_rows(
    result: HybridRetrievalResult,
) -> tuple[tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]]:
    ranked_rows = tuple(
        _ranked_row(ranked, rank=rank)
        for rank, ranked in enumerate(result.ranked_files, 1)
    )
    rows_by_claim = {str(row["claim_hash"]): row for row in ranked_rows}
    delivered = tuple(
        dict(rows_by_claim[candidate.claim_hash])
        for candidate in result.selected_context
        if candidate.claim_hash in rows_by_claim
    )
    return ranked_rows, delivered


def run_probe(
    probe: RetrievalProbe,
    *,
    repo_root: str | Path,
    state_dir: str | Path,
    dense_backend: DenseEmbeddingBackend | None = None,
    index_receipt: IndexBuildReceipt | None = None,
    prepared_repository: HybridRepository | None = None,
) -> RetrievalProbeResult:
    """Run the shared hybrid retrieval path for one checked-out snapshot."""

    started = time.perf_counter()
    evidence = inspect_repository(
        repo_root,
        probe.instruction,
        state_dir=state_dir,
        limit=12,
        source_revision=probe.source_revision,
        active_paths=probe.active_paths,
        boundary="arb_retrieval",
        index_receipt=index_receipt,
    )
    indexed_at = time.perf_counter()
    graph_db = evidence.index.graph_db if evidence.index is not None else None
    repository = prepared_repository or build_hybrid_repository(
        repo_root,
        graph_db or (Path(state_dir) / "graph.unavailable"),
        source_revision=probe.source_revision,
    )
    intent = _intent_for_task_type(probe.task_type)
    state = RetrievalState(
        task_text=probe.instruction,
        intent=intent,
        active_paths=probe.active_paths,
        changed_paths=(
            probe.active_paths if intent is RetrievalIntent.CHANGE_IMPACT else ()
        ),
        validation_state=(
            "fail" if intent is RetrievalIntent.DIAGNOSTIC_ROOT_CAUSE else "unknown"
        ),
        source_revision=probe.source_revision,
    )
    retrieval = HybridRetriever(
        repository.documents,
        structural_links=repository.structural_links,
        dense_backend=dense_backend,
    ).retrieve(
        state,
        channel_limit=100,
        top_k=20,
        selection_limit=3,
        token_budget=1_200,
    )
    ranked_rows, delivered = _hybrid_rows(retrieval)
    preemptive_frame = build_preemptive_frame(
        retrieval,
        state,
        trigger=f"arb_{probe.task_type or 'retrieval'}",
    )
    if delivered:
        abstention_reason = None
    elif evidence.status != "source_backed":
        abstention_reason = str(evidence.status)
    else:
        abstention_reason = ",".join(
            (*retrieval.reason_codes, *repository.reason_codes)
        ) or "no_retrieval_evidence"
    index = evidence.index
    return RetrievalProbeResult(
        sample_id=probe.sample_id,
        repository=probe.repository,
        base_commit=probe.base_commit,
        task_type=probe.task_type,
        retrieval_intent=intent.value,
        ranked_candidates=ranked_rows,
        delivered_evidence=delivered,
        abstained=not bool(delivered),
        abstention_reason=abstention_reason,
        graph_status=str(evidence.status),
        graph_revision=str(evidence.graph_revision),
        source_revision=probe.source_revision,
        index_latency_ms=round(
            0.0
            if index_receipt is not None
            else (
                float(evidence.index.elapsed_ms)
                if evidence.index is not None
                else (indexed_at - started) * 1000.0
            ),
            6,
        ),
        query_latency_ms=round((time.perf_counter() - indexed_at) * 1000.0, 6),
        index_cache_hit=index_receipt is not None,
        repository_cache_hit=prepared_repository is not None,
        query_hash=retrieval.query_hash,
        selected_token_count=retrieval.selected_token_count,
        payload_chars=(
            len(preemptive_frame.rendered_text) if preemptive_frame is not None else 0
        ),
        payload_tokens=retrieval.selected_token_count,
        channel_receipts=tuple(
            {
                **asdict(receipt),
                "channel": receipt.channel.value,
            }
            for receipt in retrieval.channel_receipts
        ),
        dense_backend_receipt=(
            dict(dense_backend.receipt())
            if dense_backend is not None
            and callable(getattr(dense_backend, "receipt", None))
            else None
        ),
        retrieval_reason_codes=retrieval.reason_codes,
        repository_complete=repository.complete,
        repository_reason_codes=repository.reason_codes,
        repository_document_count=len(repository.documents),
        repository_document_chars=repository.document_chars,
        repository_structural_link_count=len(repository.structural_links),
        index_error_type=str(index.error_type) if index and index.error_type else None,
        index_error_diagnostic=str(index.error_diagnostic) if index else "",
        index_source_files=int(index.source_files) if index else 0,
        index_indexable_files=int(index.indexable_files) if index else 0,
        index_schema_valid=bool(index.schema_valid) if index else False,
        index_node_count=int(index.node_count) if index else 0,
        index_edge_count=int(index.edge_count) if index else 0,
        index_binary_sha256=str(index.binary_sha256) if index else "",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", required=True, help="gold-free JSONL input")
    parser.add_argument("--repo-root", required=True, help="checked-out ARB repository snapshot")
    parser.add_argument("--state-dir", required=True, help="private index state directory")
    parser.add_argument("--output", required=True, help="JSONL predictions output")
    args = parser.parse_args(argv)
    probes = load_redacted_samples(args.samples)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        for probe in probes:
            result = run_probe(probe, repo_root=args.repo_root, state_dir=args.state_dir)
            handle.write(json.dumps(asdict(result), sort_keys=True, separators=(",", ":")))
            handle.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
