# GT-Harness

GT-Harness is a host-owned repository-intelligence layer for coding agents. It is being built to help Mini-SWE-style agents make better software-engineering decisions by gathering bounded, source-grounded context locally instead of asking the model to rediscover the repository from scratch.

## What is currently being built?

The current system combines:

- deterministic repository graph construction;
- hybrid retrieval across exact paths, lexical search, BM25, local embeddings, and certified graph structure;
- bounded evidence delivery at the provider boundary;
- preflight and postflight command classification;
- source-revision tracking and incremental graph refresh;
- replayable receipts containing request hashes, evidence, timing, and token accounting.

The goal is not to force a model's answer. The goal is to give the model less context, but better-grounded context, at the moment it can use it.

## Measured results

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

## Run locally

```bash
pip install -e .
pytest
python -m scripts.central_feature_census
python scripts/central_readiness_audit.py
```

The repository contains the Mini-SWE integration, GT runtime, retrieval engine, graph/indexer integration, evaluation adapters, and tests. Do not place API keys in source files; provide them through the runtime environment.

## License

MIT.
