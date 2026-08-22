# GroundTruth Canonical Architecture

Status: prerelease implementation under audit. This document describes reachable code; it is not a certification.

## Product boundary

The sole product executable is `gt-harness` (`gt_harness.cli:main`). Its supported production surfaces are:

- `gt-harness doctor`: verifies Python, Git, Go, and the content-addressed source build of `gt-index`.
- `gt-harness graph build|status|query`: operates the canonical repository graph.
- `gt-harness mcp`: exposes the canonical graph through stdio, SSE, or streamable HTTP.
- `gt-harness run --treatment bare|groundtruth`: runs one common model-agnostic coding-agent scaffold. The two arms use the same prompt, tools, limits, provider adapter, and action semantics. The GroundTruth arm may only add bounded deterministic evidence and record observations.

`compare` and `certify` intentionally exit nonzero until their evidence gates exist. They do not fabricate success.

## Repository-to-agent execution path

```text
repository working tree
  -> RepositoryGraphService.compute_repository_identity
     (Git commit + hashes of actual graph inputs, including dirty/untracked state)
  -> checked-in vendor/gt-index-src
  -> content-addressed local Go build (gt_harness.indexer_setup)
  -> Git-authoritative discovery (tracked + non-ignored files)
  -> tree-sitter parse and deterministic relationship resolution
  -> SQLite candidate graph + metadata/discovery receipt
  -> atomic graph/manifest publication
  -> .groundtruth/graph.db + graph-receipt.json
  -> RepositoryGraphService readiness and identity validation
  -> bounded graph queries
  -> MCP tools or GroundTruthTreatment context
  -> unchanged common coding-agent action loop
```

No provider credential or provider call is required to build, validate, update, persist, or query the graph.

## Readiness invariant

Graph-derived evidence is available only when all of the following are true:

```text
current commit == receipt commit
current graph-input revision == receipt source revision
current builder == receipt builder
SQLite checksum and quick_check are valid
discovery + skipped == repository files seen by the indexer
parsed + parse failures == files attempted
file hashes + hash failures == files attempted
status in {READY, READY_WITH_DECLARED_LIMITATIONS}
query_ready == true
```

The explicit non-ready states are `ABSENT`, `BUILDING`, `DEGRADED`, `FAILED`, and `STALE`. A stale or partial graph cannot be queried through the canonical service.

## Lifecycle

- Cold build publishes a candidate database and receipt atomically.
- Warm start recomputes repository identity, validates the receipt/database, and reuses the graph.
- Same-commit additions, modifications, and deletions use atomic incremental publication.
- Rename-like delete/add pairs and commit changes use a full rebuild because incoming-edge re-resolution is not yet sound as a file-local operation.
- An interrupted build leaves `BUILDING` and cannot be queried; the next build repairs it.
- Publication is serialized with a cross-process lock and journaled rollback.

## Canonical and non-canonical code

| Area | Classification | Disposition |
|---|---|---|
| `gt_harness/` | PRODUCTION | Canonical CLI, MCP, treatment, and source provisioning |
| `gt_engine/repository_graph_service.py` | PRODUCTION | Sole graph readiness/lifecycle/query boundary |
| `vendor/gt-index-src/` | PRODUCTION | Source-built graph writer; upstream provenance plus audited overlay |
| `src/groundtruth/` | PRODUCTION SUPPORT / MIGRATION SOURCE | First-party GT capabilities retained; only code reached from the canonical service is production until migration finishes |
| `nano/` | PRODUCTION | Common model/provider/tool agent scaffold |
| `eval/miniswe_agent.py`, `eval/swe_agent.py`, `eval/tb_agent.py` | BENCHMARK | Adapters must invoke `gt-harness run`, not a substitute graph path |
| `gt_engine/bridge.py`, central runtime and historical control layers | LEGACY / RESEARCH pending parity audit | Not the official CLI/MCP path; do not delete until consumers and unique behavior are classified |
| historical workflows, `gt_finalstand/`, historical reports | BENCHMARK / LEGACY evidence | Cannot certify the prerelease; cleanup remains gated on classification |
| vendored wheel and prebuilt Linux binary | DELETE (completed) | Removed; frozen tag retains recovery history |

There is one canonical graph database: `.groundtruth/graph.db`. The separate historical `index.db`/SymbolStore and legacy MCP servers are not production-authoritative.
