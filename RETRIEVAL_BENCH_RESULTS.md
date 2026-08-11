# GroundTruth Agent Retrieval Bench results

Date: 2026-08-10

## Current result

**No valid post-repair result exists yet.**

The previous low score measured the older graph-centric retrieval/delivery
path and motivated this repair.  It must not be relabeled as the score of the
new hybrid retriever.  Likewise, passing unit tests do not imply competitive
retrieval.

## Configuration awaiting execution

- Dataset: complete pinned ARB v2 release, 427 samples.
- Positive cases: 345.
- Selective/no-gold cases: 82.
- Retrieval channels: exact, lexical, BM25, Snowflake ONNX dense, GraphDB
  structural.
- Fusion: equal RRF, `k=60`, unique file.
- Ranked view: top 20.
- Delivered view: at most three complete evidence spans within 1,200 estimated
  tokens.
- Dense model: `Snowflake/snowflake-arctic-embed-m`, immutable revision and
  model SHA recorded in `RETRIEVAL_BENCH_CONTRACT.md`.
- Execution: GitHub Actions only, default 20 shards, no inference API.

## Mandatory outputs

Both ranked and delivered views must report official file-level MRR,
Recall@20, and BCY@8k.  The evaluator also records precision/recall/F1 at the
delivery boundary, Any@n, nDCG, task/repository macro scores, selective
precision/recall, evidence token/character load, channel contribution, and
index/query latency p50/p95/p99.

The next update to this file must be generated from the complete merged GitHub
artifact.  Partial shard scores may be used for diagnosis but cannot pass the
retrieval gate.
