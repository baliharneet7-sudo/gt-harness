# Strengthened GroundTruth: Repository-Context Design

## Decision

`central_relational_v2` strengthens the canonical GroundTruth central runtime. It does not replace
`PersistentExecutionStateEngine`, create a second product identity, or introduce a competitor
runtime. The release identity remains exactly 17 legacy feature mechanisms plus
`persistent_execution_state`.

The design adopts three source-supported engineering lessons from the GitNexus audit without
running GitNexus as a benchmark arm:

1. compute useful relational answers before the coding model's next decision;
2. attach those answers to an existing provider request instead of requiring another model-chosen
   exploration tool; and
3. make unresolved, external, ambiguous, stale, or content-unbound evidence terminal rather than
   corrective.

## Current architecture

```text
task + exact checkout + observed actions
                 |
                 v
      GraphDB + RepositoryEvidence
                 |
                 v
 five-channel HybridRetriever
 exact | lexical | BM25 | local dense fallback | certified graph
                 |
                 v
       typed StructuralLink boundary
 origin + resolution + candidate count + provenance + endpoint hashes
                 |
                 v
       RepositoryContextEngine
 semantic facts + directed CALLS views + reverse impact/test expansion
                 |
                 v
 canonical contribution compiler (shared token budget)
                 |
                 v
 existing next provider request (zero added executor turns)
                 |
                 v
 provider evidence ledger + delivery audit + release gate

PersistentExecutionStateEngine remains active around the same loop:
one deterministic zero-provider selection event, compile_context, preflight, postflight, graph
rebase. The generative bootstrap remains a legacy-profile implementation path only.
```

## Safety and evidence rules

An edge can drive execution or impact context only when all of these hold:

- current source and graph revisions match;
- both endpoints have exact paths, symbols, lines, and content hashes;
- origin is `program`;
- resolution is `exact`;
- confidence is at least `0.95`;
- the edge is mechanically certified.

Missing provenance is `unknown`, not exact. Multiple candidates are `ambiguous`. External,
heuristic, unresolved, ambiguous, stale, or incomplete edges can support retrieval ranking but
cannot create an execution view, impact fact, obligation, or correction.

Semantic claim identity excludes the global source revision and includes the semantic evidence
itself. This prevents unrelated edits from redelivering unchanged evidence. Revision checks still
prevent stale delivery.

## What is implemented

- additive `central_relational_v2` profile with persistent state forced on;
- one unified `RepositoryContextEngine` provider surface;
- source-backed definitions, signatures, callers, and explicit tests from existing
  `RepositoryEvidence`;
- direction-preserving, symbol-qualified `CALLS` traversal with depth, branching, cycle, and view
  bounds;
- reverse caller impact by depth plus certified assertion/test, inheritance, implementation,
  override, route, API, import, and reference relations when those relations exist;
- stable semantic claim IDs and cross-call deduplication;
- one contribution-compiler budget and no duplicate legacy relational/semantic delivery;
- exact provider-view/request hashes and a dedicated delivery-audit surface;
- a release gate requiring canonical 17+1 accounting, live persistent state, repository-context
  opportunity accounting, unique supported claims, and either an integrated delivery or an
  explicitly accounted correct abstention on every applicable proof receipt;
- caller-owned benchmark manifests with no embedded task, budget, treatment, or competitor;
- manifest parity against a separate observed runtime contract rather than declaration echo.

## What is deliberately not claimed

- Directed call views are lower-bound graph paths, not CFGs, PDGs, runtime traces, or proof that a
  repair must edit every node.
- GT does not autocorrect unresolved symbols.
- The current semantic bridge does not yet expose every LSP/compiler/runtime-KB field available in
  the full product.
- Local tests prove behavior and integration, not resolve-rate uplift.
- GitNexus is a source-learning input only; it is not an evaluation arm.

## Remaining release work

P0-P2 implementation is complete at the durable central-runtime boundary. Direct live LSP and
host-only runtime introspection remain deliberate abstention boundaries rather than missing
benchmark claims. The remaining work is to wire runner-owned runtime observations, freeze an exact
commit, pass the source-built provider-free proof, execute available historical replays, freeze the
final prediction, and then run the matched 20-task comparison. No GitNexus run is planned.

## Success condition

The candidate succeeds only if the final matched evaluation improves resolve rate while preserving
or reducing negative flips, executor steps, evidence tokens, and repository exploration. More
edges, more context, or a passing unit suite alone are not outcome evidence.
