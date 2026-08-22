# GT-Harness

GT-Harness is a model-agnostic benchmarking product for measuring whether deterministic GroundTruth repository intelligence helps coding agents. The prerelease product owns graph construction, readiness, delivery, run receipts, and paired comparison; it does not depend on a particular model or provider.

## What is currently being built?

The current system combines:

- deterministic repository graph construction;
- hybrid retrieval across exact paths, lexical search, BM25, local embeddings, and certified graph structure;
- bounded evidence delivery at the provider boundary;
- preflight and postflight command classification;
- exact source-revision tracking and fail-closed full graph convergence after edits;
- replayable receipts containing request hashes, evidence, timing, and token accounting.

The goal is not to force a model's answer. The goal is to give the model less context, but better-grounded context, at the moment it can use it.

## Historical results (not product certification)

### Retrieval benchmark

On the 427-row Agent Retrieval Bench across 25 repositories:

| Metric | Result |
|---|---:|
| Ranked MRR | 0.4372 |
| Ranked Recall@20 | 0.7072 |
| Ranked BCY@8K | 0.5198 |
| Delivered-payload MRR | 0.4207 |

### Matched Mini-SWE smoke

In one ten-task matched smoke, GT-on matched the frozen GT-off baseline at **9/10 official tasks** on the common solved set, while using:

- **31.3% fewer tokens**;
- **51 fewer API calls**;
- **53 fewer assistant steps**;
- **103 fewer model actions**.

This is a single matched-smoke result, not a claim of causal solve-rate improvement. Provider-free tests establish implementation integrity; larger outcome claims require a separately authorized matched evaluation.

## Canonical local product path

```bash
pip install -e .
gt-harness doctor
gt-harness graph build --root /path/to/repository
gt-harness graph query definition Symbol --root /path/to/repository
gt-harness mcp --root /path/to/repository
gt-harness run "task" --model exact/provider-model --treatment bare
gt-harness run "task" --model exact/provider-model --treatment groundtruth
```

The legacy file-keyed incremental indexer and historical benchmark/control paths remain in the repository for parity analysis, but they are not the canonical graph lifecycle. See `CANONICAL_ARCHITECTURE.md` for the authoritative boundary.

## License

MIT.
