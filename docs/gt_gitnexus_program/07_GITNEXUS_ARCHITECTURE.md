# GitNexus architecture at the pinned source revision

## Audit identity and evidence rules

- **Official repository:** [abhigyanpatwari/GitNexus](https://github.com/abhigyanpatwari/GitNexus)
- **Pinned revision:** [`fc885a4bf3edddf9214df633d8d1c0767ef58af9`](https://github.com/abhigyanpatwari/GitNexus/commit/fc885a4bf3edddf9214df633d8d1c0767ef58af9)
- **Revision inspected:** 2026-08-18
- **Latest release observed during the audit:** [`v1.6.9`](https://github.com/abhigyanpatwari/GitNexus/releases/tag/v1.6.9), tag commit `4227194ad7bdfbedc29a7fe20e09c6737ce0e744`
- **Scope:** current official source, not marketing reconstruction and not an assumption about the private Akon benchmark configuration.

Evidence labels used below:

- **SOURCE-PROVEN:** directly implemented or stated in the pinned official source.
- **INFERENCE:** a reasoned implication of source behavior that has not been isolated by a controlled benchmark.
- **UNKNOWN:** the public source or benchmark does not disclose enough information.

The pinned source is the implementation audited here. Akon does not identify the GitNexus commit used in its reported DeepSWE experiment. Therefore this document must not call `fc885a4` the benchmark-treatment revision.

## Executive conclusion

GitNexus is not just a Tree-sitter symbol index with an MCP wrapper. At the pinned revision it implements a multi-phase repository-analysis pipeline, cross-file and receiver-aware resolution, a property graph, framework extractors, deterministic architecture clustering, bounded execution-process construction, FTS and optional vector retrieval, and precomposed relational responses.

Its most important architectural advantage over the GT contract is **composition**. GitNexus turns low-level relations into process-grouped answers such as entry point to service to sink, then exposes those answers through `query`, `context`, `impact`, `trace`, `detect_changes`, route/API tools, and automatic augmentation.

Its main architectural weakness relative to the intended GT engine is **state and evidence integrity during a live coding trajectory**. GitNexus has strong index-build machinery, but ordinary source edits do not force a revision-current graph before the next provider request. Its hooks, MCP responses, and public evaluation adapter also lack GT's claim-level delivery receipts, provider-view hashes, state fingerprints, and first-eligible timing proof.

Confidence: **high** for the implementation description; **moderate** that process composition and action-local delivery explain part of GitNexus's reported efficiency; **unknown** for any exact contribution to Akon's solve-rate delta.

## 1. End-to-end pipeline

The top-level source flow is:

```text
repository checkout
  -> resolve repository and index identity
  -> scan and structure files
  -> parse language-specific syntax and semantic captures
  -> extract routes, MCP tools, ORM, Spring, AOP, DI, and other framework facts
  -> reconcile cross-file imports and ownership
  -> resolve free calls, receiver-bound calls, properties, inheritance, and implementations
  -> prune local-only artifacts
  -> construct MRO and framework inheritance
  -> build graph communities
  -> compose bounded execution processes
  -> persist LadybugDB, FTS, metadata, and optional embeddings
  -> serve precomposed answers through MCP, CLI, hooks, and editor integrations
```

The exact orchestration points are:

- [`runFullAnalysis()` and `runFullAnalysisInner()`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus/src/core/run-analyze.ts) own locking, freshness, full versus incremental analysis, persistence, and recovery.
- [`buildPhaseList()` and `runPipelineFromRepo()`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus/src/core/ingestion/pipeline.ts) construct and run the ingestion DAG.
- [`runPipeline()`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus/src/core/ingestion/pipeline-phases/runner.ts) topologically orders phases and rejects duplicate IDs, missing dependencies, and dependency cycles.
- [`runChunkedParseAndResolve()`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus/src/core/ingestion/pipeline-phases/parse-impl.ts) performs worker-based bounded parse chunks.
- [`runScopeResolution()`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus/src/core/ingestion/scope-resolution/pipeline/run.ts) and [`SCOPE_RESOLVERS`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus/src/core/ingestion/scope-resolution/pipeline/registry.ts) own the ordered resolution pipeline.

The source-declared default phase order is:

```text
scan
  -> structure
  -> springConfig / markdown / cobol
  -> parse
  -> routes / tools / orm
  -> crossFile
  -> scopeResolution
  -> springAutoConfiguration / springAop
  -> pruneLocalSymbols
  -> mro
  -> springAopInheritance
  -> di
  -> communities
  -> processes
```

Two additional interprocedural summary phases, `taintSummaries` and `callSummaries`, are registered only when `pdg=true`. The PDG substrate is opt-in; it is not part of the default graph. Akon does not disclose whether its benchmark enabled it.

## 2. Parsing and semantic normalization

### 2.1 Parser model

**SOURCE-PROVEN:** GitNexus uses language-specific Tree-sitter providers and normalized semantic capture structures. It is not a compiler or LSP implementation.

The parser layer extracts definitions, references, imports, calls, ownership, source ranges, declared types, receiver chains, framework sites, and optional CFG/PDG artifacts. Later passes reconcile these artifacts across files.

This distinction matters for GT:

- GitNexus can cover many languages and frameworks with one normalized graph pipeline.
- It must reconstruct types, receiver ownership, overloads, and visibility heuristically or with language-specific passes.
- A healthy compiler/LSP-backed GT path can possess stronger positive semantic evidence for supported languages.
- Tree-sitter breadth is not evidence that GT should replace its stronger semantic substrate.

### 2.2 Framework and non-call enrichment

The phase registry and graph schema include source-backed extraction for:

- routes and handlers;
- MCP tools;
- ORM activity and database sinks;
- dependency injection;
- Spring configuration, auto-configuration, and AOP;
- imports, exports, inheritance, implementation, property access, and method ownership;
- outward fetch/query sites used as meaningful process terminals;
- optional CFG, data dependency, control dependency, and taint relations.

These enrichments are valuable because process composition can terminate at a meaningful external action rather than only at a call-graph leaf.

## 3. Graph construction and schema

The persisted schema is defined in [`core/lbug/schema.ts`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus/src/core/lbug/schema.ts).

Node families include files, folders, functions, classes, interfaces, methods, language-specific code elements, communities, processes, routes, tools, and optional basic blocks. Relationships are stored in a general `CodeRelation` table with a relation `type`, confidence, reason, and endpoint data.

Important relation families include:

- `CALLS`, with reverse caller lookup derived by traversing the same relation backward;
- `IMPORTS`, `USES`, and `ACCESSES`;
- `EXTENDS`, `IMPLEMENTS`, method override, and method implementation relations;
- ownership and membership relations;
- `STEP_IN_PROCESS` and process entry relations;
- route, tool, ORM, DI, AOP, condition, and event relations;
- optional `CFG`, `REACHING_DEF`, `CDG`, post-dominance, taint, sanitization, and interprocedural summary relations.

**SOURCE-PROVEN:** `CALLED_BY` is not required as a second stored edge; callers are the incoming side of `CALLS`.

**Architecture consequence:** GitNexus uses a broad, normalized property graph. Its value does not come from storing every relation twice. It comes from resolution, higher-level composition, and response design.

## 4. Receiver and call resolution

The detailed uncertainty policy is in [08_GITNEXUS_RESOLUTION_AND_UNCERTAINTY.md](08_GITNEXUS_RESOLUTION_AND_UNCERTAINTY.md). The architectural path is:

1. Reconcile imports and cross-file definitions.
2. Build scope and definition indexes.
3. Resolve receiver-bound sites in an ordered set of cases.
4. Fold multi-hop receiver chains where each step is supported.
5. Resolve receiver-less calls by lexical/import scope, language hooks, arity, overload, and type narrowing.
6. Emit a graph edge only after both graph endpoints are available.
7. Record selected suppressed and unresolved outcomes for later epistemic reporting.

Primary implementations:

- [`emitReceiverBoundCalls()` and `classifyReceiverOrigin()`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus/src/core/ingestion/scope-resolution/passes/receiver-bound-calls.ts)
- [`foldReceiverChain()` and `resolveCompoundReceiverTyped()`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus/src/core/ingestion/scope-resolution/passes/compound-receiver.ts)
- [`emitFreeCallFallback()` and `pickUniqueGlobalCallable()`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus/src/core/ingestion/scope-resolution/passes/free-call-fallback.ts)
- [`ResolutionOutcome`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus/src/core/ingestion/scope-resolution/resolution-outcome.ts)
- [`tryEmitEdge()`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus/src/core/ingestion/scope-resolution/graph-bridge/edges.ts)

## 5. Communities

[`processCommunities()`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus/src/core/ingestion/community-processor.ts) constructs a symbol projection and runs seeded Leiden community detection.

Source-proven properties:

- the seed is fixed at `0xc0de`;
- function/class/method/interface structure is projected from selected relationship types;
- large graphs receive filtering before clustering;
- community nodes and membership relations are persisted;
- a Leiden timeout assigns all nodes to community zero and records a fallback reason.

Communities are useful for:

- grouping search results;
- cohesion-based ranking;
- labeling processes as intra- or cross-community;
- providing compact architectural orientation.

They are not mechanically proven modules or change obligations. GT should use such clusters only as ranking and presentation support unless independent evidence certifies the relation being asserted.

## 6. Execution-process construction

[`processProcesses()` and `traceFromEntryPoint()`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus/src/core/ingestion/process-processor.ts) form GitNexus's clearest composition layer.

### 6.1 Entry points

[`entry-point-scoring.ts`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus/src/core/ingestion/entry-point-scoring.ts) scores candidate entry points. The processor describes them as functions that call others while having relatively few callers; language and test/file characteristics also influence scoring.

The candidate set is capped at 200. The truncation record counts candidates dropped before tracing.

### 6.2 Traversal

Source-proven shipped defaults are:

| Bound | Value |
|---|---:|
| Maximum trace depth | 10 |
| Maximum callees followed per node | 4 |
| Minimum process length | 3 nodes |
| Per-entry trace budget | `maxBranching * 3`, therefore 12 by default |
| Dynamic maximum processes | `max(20, round(symbolCount / 10))` |

The traversal is depth-first, cycle-guarded, and source-order deterministic. A path can terminate at a call-graph leaf, the depth limit, a cycle-only frontier, or a meaningful outward sink. Sink traces may end at a fetch or ORM action while traversal continues to preserve a longer path too.

### 6.3 Deduplication and selection

The processor:

- removes subset-like duplicate traces;
- keeps the longest path for an entry/terminal pair;
- preserves meaningful sink-bearing paths;
- chooses deeper results while round-robining across terminals;
- labels processes heuristically as an entry-to-terminal flow;
- records community membership and cross-community status;
- links routes and tools to their processes in the pipeline phase.

### 6.4 Completeness

The process result records six truncation counters:

- entry-point candidates dropped;
- ranked entry points not traced;
- deduplicated processes dropped by the process limit;
- traces cut at maximum depth;
- callees skipped by the branch cap;
- walks cut by the per-entry trace budget.

Current source logs a warning when whole flows are missing and a debug message for shape-only traversal truncation. This is stronger than silently claiming completeness.

However, normal `query` responses do not carry the complete process-extraction truncation receipt. Therefore a consumer can still see a process list without knowing the complete repository-wide coverage boundary.

### 6.5 What this gives the model

Instead of disconnected edges:

```text
handler CALLS service
service CALLS repository
repository CALLS executeQuery
test CALLS handler
```

GitNexus can present:

```text
RequestHandler -> ServiceMethod -> RepositoryMethod -> DatabaseSink
```

alongside matched symbols and source locations. This is a materially higher-value answer because it encodes order and relational context.

## 7. Retrieval and response composition

### 7.1 Search channels

The primary `query` implementation is [`LocalBackend.query()`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus/src/mcp/local/local-backend.ts).

It runs:

- BM25/FTS retrieval;
- optional semantic vector retrieval;
- equal-form reciprocal-rank fusion using `1 / (60 + rank)`;
- process membership, cohesion, and source-content enrichment;
- process-level grouping of matched symbols;
- a separate standalone-definition list.

The default local embedding implementation uses `Snowflake/snowflake-arctic-embed-xs`, 384 dimensions, as documented in [`embeddings/types.ts`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus/src/core/embeddings/types.ts) and [`embedder.ts`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus/src/core/embeddings/embedder.ts). Embeddings are opt-in. The embedding pipeline uses versioned, content-derived identity to reuse unchanged vectors.

The public GitNexus evaluation adapter defaults to `skip_embeddings=True`. The private Akon benchmark does not disclose its embedding configuration.

### 7.2 Smart-response surface

Tool declarations live in [`mcp/tools.ts`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus/src/mcp/tools.ts). Implementations are primarily in [`mcp/local/local-backend.ts`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus/src/mcp/local/local-backend.ts).

| Response | Exact implementation | Composition performed |
|---|---|---|
| `query` | `LocalBackend.query()` | BM25/vector RRF, process grouping, cohesion/content enrichment |
| `context` | `LocalBackend.context()` | symbol disambiguation, incoming/outgoing categories, process membership, type/framework metadata, epistemic boundary |
| `impact` | `LocalBackend.impact()` and `_runImpactBFS()` | bounded relationship traversal, confidence filtering, depth grouping, process/module enrichment |
| `trace` | `LocalBackend.trace()` | directed paths and group-aware tracing |
| `detect_changes` | `LocalBackend.detectChanges()` | git diff hunks to symbols to affected processes and risk |
| `route_map` | `LocalBackend.routeMap()` | routes, handlers, and process context |
| `shape_check` | `LocalBackend.shapeCheck()` | API/shape compatibility context |
| `api_impact` | `LocalBackend.apiImpact()` | API consumers, handlers, shape, and transitive impact |
| `explain` | `LocalBackend.explain()` | optional CFG/PDG-backed explanation |
| `pdg_query` | `LocalBackend.pdgQuery()` | optional statement/data/control/taint query |

These are precomposed relational answers rather than raw edge dumps.

### 7.3 Graceful degradation

`query` now surfaces several FTS, vector-width, CJK, and enrichment failures through `warning` and sometimes `partial`. This is a useful pattern.

Two limits remain important:

1. `context` caps incoming and outgoing relation windows. The current source itself notes that categorized output lacks a truncation flag, so a high-fan-in category can still be silently incomplete.
2. Process-extraction truncation is not joined into each `query` response, so the returned flow set can be a lower-bound sample without a provider-visible completeness certificate.

## 8. Delivery surfaces

GitNexus reaches coding agents through four distinct paths:

1. **Explicit MCP/CLI tools.** The model chooses `query`, `context`, `impact`, and related actions.
2. **Claude Code hooks.** `PreToolUse` augments selected `Grep`, `Glob`, and search-bearing `Bash` actions.
3. **Cursor hooks.** `postToolUse` augments `Shell`, `Read`, and `Grep` observations.
4. **Public evaluation adapter.** `native_augment` appends `gitnexus-augment` output to grep-like observations.

The exact delivery and lifecycle audit is in [09_GITNEXUS_DELIVERY_AND_LIFECYCLE.md](09_GITNEXUS_DELIVERY_AND_LIFECYCLE.md).

The architectural distinction is:

```text
explicit MCP
  -> model chooses intelligence action
  -> extra tool/reasoning step

automatic augmentation
  -> agent chooses an ordinary search/read action
  -> host computes graph context
  -> same or adjacent observation receives the relational answer
```

**INFERENCE:** automatic augmentation can replace exploration when the added answer prevents subsequent searches. Source proves the delivery mechanism, not that replacement occurred in Akon's trajectories.

## 9. Determinism boundary

| Stage | Classification | Important caveat |
|---|---|---|
| File hashing and phase ordering | Deterministic for a fixed checkout/configuration | filesystem and tool versions are external inputs |
| Tree-sitter parsing | Deterministic for fixed bytes and parser versions | parser coverage is not compiler semantic completeness |
| Scope/receiver resolution | Deterministic ordered computation | may suppress, miss, or heuristically resolve edges |
| Community detection | Seeded deterministic heuristic | timeout fallback collapses all nodes to one community |
| Process construction | Deterministic bounded heuristic | not a complete runtime trace |
| BM25 and RRF | Deterministic for a fixed index | optional channel failures change inputs |
| Embedding retrieval | Reproducible only for fixed model/runtime/configuration | optional and not benchmark-disclosed |
| Response composition | Deterministic for a fixed graph/query | capped windows and missing completeness signals matter |
| Hook firing | Environment and contention dependent | hooks can skip or fail silently |
| Model action and solve outcome | Stochastic/model dependent | repository determinism cannot enforce the sampled outcome |

The defensible determinism claim is:

> GitNexus moves a substantial amount of repository traversal, graph expansion, ambiguity handling, flow composition, and result formatting into host-side computation.

It does not make the coding model's outcome deterministic.

## 10. Capability comparison with current GT contract

This table compares the pinned GitNexus source to the supplied GT contract. Track A must separately prove that the current GT implementation and benchmark path actually exercise each claimed GT capability.

| Capability | Current assessment | Reason |
|---|---|---|
| Compiler/LSP-resolved semantics | **GT potentially stronger** | GitNexus uses Tree-sitter plus reconstruction; GT contract includes compiler/LSP evidence |
| Receiver-chain heuristic breadth | **GitNexus strong** | explicit multi-hop field/call/await/index/constructor folding |
| Execution-process composition | **GitNexus stronger** | first-class bounded entry-to-terminal processes |
| Process-grouped search | **GitNexus stronger** | `query` groups retrieval results by process and cohesion |
| Retrieval channels | **GT design stronger** | GT specifies exact, lexical, BM25, pinned dense, and certified graph channels |
| Edge/evidence certification | **GT stronger in design** | GitNexus numeric confidence is not GT mechanical certification |
| Task instruction semantics | **GT stronger** | GitNexus is repository-centric; GT also derives checks/deliverables/focus from legal task inputs |
| Validation feedback | **GT stronger** | GT owns preflight/postflight and observed validation state |
| Live post-edit graph freshness | **GT stronger in design** | GitNexus does not automatically refresh on every source edit |
| Delivery audit | **GT much stronger in design** | GitNexus lacks claim, request-hash, state-fingerprint, and first-eligible receipts |
| Broad framework extraction | **GitNexus stronger/more mature** | routes, ORM, DI, Spring, AOP, events, and tools are first-class |
| Multi-repository contracts | **GitNexus stronger** | group and cross-repository bridge support exists |

## 11. Mechanisms GT should adapt

### Priority 1: certified execution-process projection

Build on GT's existing current certified graph:

```text
task/change anchor
  -> certified entry/caller
  -> bounded ordered CALLS chain
  -> meaningful sink, route, test, validation, or deliverable
```

Preserve graph revision, edge provenance, lower-bound status, cycle/depth/branch bounds, and truncation in the provider receipt.

Expected value: wrong-localization, wrong-strategy, incomplete-fix, and missed-coupled-change failures.

### Priority 2: process-aware evidence packing

Group existing GT retrieval spans into one compact flow or obligation answer rather than emitting unrelated files and graph edges.

Expected value: fewer searches and file reads, lower uncached input, and clearer coupling.

### Priority 3: action-local automatic delivery

Use GT's existing provider boundary to attach the composed answer to a normal search/read/edit/validation observation with zero extra provider calls. Preserve GT's stronger claim and request-hash accounting.

Expected value: convert GT from additive exploration into exploration replacement.

### Priority 4: changed-symbol to process to test composition

Combine GT change surface, current callers, process path, test relation, declared checks, and validation state into a bounded coupled-change or coupled-check obligation only when each relationship is certified.

Expected value: a new solve capability beyond static GitNexus navigation.

## 12. Mechanisms GT should reject

- Replacing LSP/compiler evidence with Tree-sitter wholesale.
- Treating community membership as a certified obligation.
- Treating a bounded static process as a complete execution trace.
- Adding an explicit model-selected graph tool when the same answer can enter an existing provider turn.
- Copying globally unique-name call inference without import or visibility proof.
- Adopting silent graceful failure for treatment-critical indexing or delivery.
- Adding embeddings merely because GitNexus supports them; GT already has a pinned dense path whose availability must be repaired and certified.
- Copying a static task-start index into a stateful repair benchmark.

## 13. Architecture verdict

### Source-proven

GitNexus builds a broad repository graph, resolves many call and receiver forms, composes graph paths into processes, groups retrieval by those processes, and can attach relational context to ordinary agent operations.

### Inference

The interaction of process composition and action-local delivery is the most plausible source-level explanation for reduced exploration. It is a stronger hypothesis than “embeddings caused the gain” or “more edges caused the gain.”

### Unknown

Public evidence cannot identify which of these mechanisms, prompts, tools, hooks, settings, or task-selection choices caused Akon's reported solve-rate delta.

### GT decision

GitNexus should be mined for **composition patterns**, not copied as a replacement architecture. GT's strongest path is to place a certified, revision-current process/change/test layer on top of its existing semantic, task, validation, contribution, and delivery machinery.
