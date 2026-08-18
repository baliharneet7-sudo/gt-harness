# GitNexus/Akon implementation and benchmark source audit

**Audit date:** 2026-08-17  
**GitNexus revision examined:** [`fe3d7e56be5a557e051f12684dfbdce9d5a31920`](https://github.com/abhigyanpatwari/GitNexus/commit/fe3d7e56be5a557e051f12684dfbdce9d5a31920)  
**Revision date:** 2026-08-16  
**Revision subject:** `feat(spring): detect non-HTTP handler entry points (#2891)`  
**Method:** Read-only inspection of current official GitNexus/Akon and DeepSWE primary sources. No Akon benchmark trajectories, private harness, or private Graphify implementation were available.

## Evidence notation

- **Fact** means directly supported by current source code or an official primary-source document linked in this report.
- **Inference** means a conclusion drawn from those facts but not isolated experimentally.
- **Unverified** means the public primary sources do not disclose enough information to establish the claim.

The GitNexus commit above is the current implementation revision examined by this audit. Akon does not identify the GitNexus commit used for its DeepSWE benchmark. The pinned revision must therefore not be described as the benchmark-treatment revision.

---

## 1. Executive verdict

GitNexus is not merely a Tree-sitter symbol extractor with an MCP wrapper. The current implementation has a substantial precomputation pipeline: repository filtering and caching, per-language Tree-sitter parsing, a unified semantic model, cross-file scope resolution, receiver-bound call resolution, explicit resolution outcomes, graph persistence, architecture clustering, bounded execution-process construction, hybrid retrieval, precomposed context and impact responses, diff-to-process mapping, and automatic augmentation of ordinary search actions.

The strongest source-backed conclusions are:

1. **GitNexus has a real uncertainty and refusal model, but it is not conservative everywhere.** Receiver ambiguity, overload ambiguity, unknown receivers, built-ins, and MCP symbol ambiguity commonly produce suppression, explicit ambiguity, or lower-bound results. However, the current free-call fallback explicitly admits that it may resolve a globally unique cross-package callable without proving an import relationship, then emits the resulting `CALLS` edge at confidence `0.85`.

2. **Execution processes are deterministic, bounded static summaries rather than complete execution traces.** They are constructed over selected `CALLS` edges with confidence, depth, branch, entry-point, and process-count limits. The implementation records truncation, but graph incompleteness and the traversal bounds remain material.

3. **Delivery architecture is plausibly as important as graph content.** Claude Code can receive relational context through `PreToolUse`; Cursor and Antigravity append it to completed tool results; and the public evaluation agent automatically appends graph context to grep observations. This can remove a model decision to invoke a separate graph tool, although it still incurs host-side lookup latency and provider-visible context tokens.

4. **Akon's DeepSWE result is a configuration-level result, not a feature-level causal decomposition.** Bare, Graphify, and GitNexus are not specified sufficiently to isolate graph resolution, processes, clustering, retrieval, prompt differences, automatic augmentation, or tool composition. The public GitNexus evaluation treatment changes prompts and tools and may automatically modify observations.

5. **The published benchmark has material reproducibility defects.** Its task/trial arithmetic does not reconcile; its description of DeepSWE conflicts with official DeepSWE sources; and it does not publish the exact treatment SHA, harness SHA, task manifest, Graphify implementation, sampling settings, exclusions, raw attempt rows, or trajectories.

The implementation conclusions in this report are high confidence. The proposed implications for GroundTruth are engineering hypotheses to test, not claims that GitNexus's public benchmark isolates their causal effect.

---

## 2. Primary sources

### GitNexus

- [Pinned commit](https://github.com/abhigyanpatwari/GitNexus/commit/fe3d7e56be5a557e051f12684dfbdce9d5a31920)
- [Pinned `ARCHITECTURE.md`](https://github.com/abhigyanpatwari/GitNexus/blob/fe3d7e56be5a557e051f12684dfbdce9d5a31920/ARCHITECTURE.md)
- [Pinned `README.md`](https://github.com/abhigyanpatwari/GitNexus/blob/fe3d7e56be5a557e051f12684dfbdce9d5a31920/README.md)
- [Public evaluation README](https://github.com/abhigyanpatwari/GitNexus/blob/fe3d7e56be5a557e051f12684dfbdce9d5a31920/eval/README.md)
- [Akon DeepSWE benchmark page](https://www.akonlabs.com/benchmarks)

### DeepSWE

- [Official DeepSWE repository](https://github.com/datacurve-ai/deep-swe)
- [Official DeepSWE site](https://deepswe.datacurve.ai/)
- [DeepSWE paper, arXiv:2607.07946](https://arxiv.org/abs/2607.07946)

No secondary benchmark summary is treated as authoritative in this report.

---

## 3. End-to-end GitNexus architecture

### 3.1 Top-level dataflow

```text
repository checkout
  -> ignore and traversal policy
  -> file-content hashing and parse-cache lookup
  -> worker-based Tree-sitter parsing
  -> per-file ParsedFile semantic artifacts
  -> ownership/import/scope reconciliation
  -> receiver/free-call/reference/property/callable resolution
  -> graph nodes and relationships
  -> optional routes/tools/ORM/Spring/PDG enrichments
  -> Leiden communities
  -> bounded execution processes
  -> LadybugDB + FTS + optional embeddings + metadata
  -> query/context/impact/detect_changes/trace/augment
  -> MCP, CLI, hooks, skills, and editor integrations
```

The main analysis lifecycle is implemented by [`runFullAnalysis()` and `runFullAnalysisInner()`](https://github.com/abhigyanpatwari/GitNexus/blob/fe3d7e56be5a557e051f12684dfbdce9d5a31920/gitnexus/src/core/run-analyze.ts). The pipeline DAG is validated, topologically sorted, and executed by [`runPipeline()`](https://github.com/abhigyanpatwari/GitNexus/blob/fe3d7e56be5a557e051f12684dfbdce9d5a31920/gitnexus/src/core/ingestion/pipeline-phases/runner.ts).

The architecture document describes 19 default phases, or 21 with optional PDG work:

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

**Fact:** The phase graph is explicitly declared and validated. Phase-level execution is sequential in topological order; parsing and selected enrichment operations provide internal parallelism.

### 3.2 Repository traversal and ignore policy

Repository enumeration is implemented by [`walkRepositoryPaths()` and `readFileContents()`](https://github.com/abhigyanpatwari/GitNexus/blob/fe3d7e56be5a557e051f12684dfbdce9d5a31920/gitnexus/src/core/ingestion/filesystem-walker.ts). Filtering is centralized in [`ignore-service.ts`](https://github.com/abhigyanpatwari/GitNexus/blob/fe3d7e56be5a557e051f12684dfbdce9d5a31920/gitnexus/src/config/ignore-service.ts).

Current behavior includes:

- repository-wide glob traversal;
- canonical sorting of discovered paths;
- metadata/stat work in batches of 32;
- a file-size ceiling with explicit skip warnings;
- `.gitignore`, global Git excludes, `.git/info/exclude`, and `.gitnexusignore`;
- `.gitnexusignore` negation support;
- hard-coded exclusions for dependencies, build output, caches, generated artifacts, declaration files, bundles, binaries, and common low-value files;
- generated-file heuristics.

**Fact:** The traversal order is made reproducible after discovery.  
**Caveat:** Generated-code handling is primarily exclusion-oriented. It is not a general provenance system that indexes generated code while preserving generator ownership.

### 3.3 Parsing and `ParsedFile`

Each language is represented through [`LanguageProvider`](https://github.com/abhigyanpatwari/GitNexus/blob/fe3d7e56be5a557e051f12684dfbdce9d5a31920/gitnexus/src/core/ingestion/language-provider.ts). Providers supply Tree-sitter queries, parse strategy, import resolution, ownership hooks, built-in names, type and export behavior, route extraction, scope captures, and optional CFG hooks.

Relevant implementation points include:

- [`tree-sitter-queries.ts`](https://github.com/abhigyanpatwari/GitNexus/blob/fe3d7e56be5a557e051f12684dfbdce9d5a31920/gitnexus/src/core/ingestion/tree-sitter-queries.ts)
- [`parse-impl.ts`](https://github.com/abhigyanpatwari/GitNexus/blob/fe3d7e56be5a557e051f12684dfbdce9d5a31920/gitnexus/src/core/ingestion/parse-impl.ts)
- [`ParsedFile`](https://github.com/abhigyanpatwari/GitNexus/blob/fe3d7e56be5a557e051f12684dfbdce9d5a31920/gitnexus-shared/src/scope-resolution/parsed-file.ts)

A `ParsedFile` can carry scopes, definitions, raw imports, reference sites, callable-flow sites, ownership data, and language-specific side channels. It is the common semantic artifact passed through finalization, reconciliation, resolution, and graph construction.

Parsing is worker-based and chunked at approximately 20 MB. The content-addressed, sharded parse cache is implemented in [`parse-cache.ts`](https://github.com/abhigyanpatwari/GitNexus/blob/fe3d7e56be5a557e051f12684dfbdce9d5a31920/gitnexus/src/storage/parse-cache.ts), including `computeChunkHash()`, `loadParseCacheChunk()`, `persistParseCacheChunk()`, and `saveParseCache()`.

Corrupt, incompatible, or version-mismatched cache entries become misses and are reparsed.

### 3.4 Persistence, incrementality, and stale state

The graph is persisted in LadybugDB under `.gitnexus/`, with metadata and a global repository registry at `~/.gitnexus/registry.json`.

`runFullAnalysis()` handles:

- commit and file-hash comparisons;
- graph and schema validation;
- schema-fingerprint drift;
- embedding-dimension drift;
- dirty/in-progress incremental state;
- graph-collapse checks;
- full-versus-incremental selection;
- parse-cache reuse;
- incremental changed-file and importer expansion;
- full-rebuild escalation;
- graph, FTS, embeddings, metadata, and registry updates.

Incremental importer expansion is bounded. Deletions, source-classification changes, schema drift, dirty-state recovery, or excessive incremental scope can force a full rebuild.

**Fact:** Full rebuilds use temporary targets and replacement where supported.  
**Fact:** Incremental updates are not universally atomic by default; an optional atomic path exists.  
**Caveat:** Platform-specific replacement behavior, especially on Windows, prevents an unconditional claim that every update is transactionally atomic.

---

## 4. Semantic and scope resolution

### 4.1 Resolution pipeline

The central entry point is [`runScopeResolution()`](https://github.com/abhigyanpatwari/GitNexus/blob/fe3d7e56be5a557e051f12684dfbdce9d5a31920/gitnexus/src/core/ingestion/scope-resolution/pipeline/run.ts).

The broad resolution order is:

1. finalize imports and scope bindings;
2. emit inheritance and interface evidence;
3. resolve receiver-bound calls;
4. run free-call fallback;
5. resolve general references;
6. resolve property dispatch;
7. resolve callable-value flow;
8. resolve imported references;
9. apply narrow last-resort property handling;
10. emit import relationships and optional flow evidence.

Receiver-bound resolution runs before free-call fallback so a less-specific free-call path cannot normally claim a receiver-owned site first.

### 4.2 Typed resolution outcomes

[`resolution-outcome.ts`](https://github.com/abhigyanpatwari/GitNexus/blob/fe3d7e56be5a557e051f12684dfbdce9d5a31920/gitnexus/src/core/ingestion/scope-resolution/resolution-outcome.ts) defines resolved and suppressed outcomes. Suppression reasons include:

- `member-lookup-ambiguous`;
- `overload-ambiguous`;
- `overload-ambiguous-normalization`;
- `conversion-rank-tied`;
- `inline-ns-ambiguous`;
- `selected-callable-deleted`;
- `free-call-instance-ownership`;
- `receiver-owned-but-unbound`;
- `receiver-unresolved`;
- ADL/ordinary-lookup restrictions.

Suppressed outcomes can retain candidate IDs, phase, path, symbol name, source range, site kind, receiver shape, and receiver origin.

**Fact:** Ambiguity is represented as first-class semantic data; it is not only inferred later from missing graph edges.

### 4.3 Receiver-bound calls

Receiver handling is implemented in [`receiver-bound-calls.ts`](https://github.com/abhigyanpatwari/GitNexus/blob/fe3d7e56be5a557e051f12684dfbdce9d5a31920/gitnexus/src/core/ingestion/scope-resolution/passes/receiver-bound-calls.ts). It attempts, in ordered cases:

- `super` dispatch;
- compound receiver chains;
- implicit `this` or `self`;
- namespace dispatch;
- static-class dispatch;
- dotted type receivers;
- receiver chains with propagated types;
- simple type receivers;
- value receivers;
- class-level fields.

The pass uses structural receiver-chain data rather than relying exclusively on source-line regexes. The receiver-chain representation can preserve call, field, await, and index operations; unknown wire versions are refused.

### 4.4 In-program, external, and unknown receivers

`classifyReceiverOrigin()` divides unresolved receiver roots into three classes:

| Origin | Source meaning | Downstream treatment |
|---|---|---|
| `in-program` | A declaration, value, or type in the indexed program is implicated | Treated as evidence that a real graph edge may be missing |
| `external` | Positive language-specific evidence identifies a built-in/external root | Retained separately; not treated as a missing in-graph target |
| `unknown` | Neither local nor external origin can be established | Conservatively included with unresolved in-program evidence for lower-bound reporting |

The summary layer is implemented by [`summarizeUnresolvedReceivers()`](https://github.com/abhigyanpatwari/GitNexus/blob/fe3d7e56be5a557e051f12684dfbdce9d5a31920/gitnexus/src/core/ingestion/scope-resolution/unresolved-receivers.ts).

Important behaviors:

- `external` requires positive built-in evidence rather than being the default for missing type information;
- an untyped or unresolvable receiver becomes `unknown`, not automatically external;
- unresolved call sites are separated from unresolved property reads and writes;
- external drops are persisted separately for auditability;
- unresolved in-program and unknown call sites can make `context` and `impact` counts lower bounds.

**Fact:** When receiver typing cannot be established, GitNexus commonly drops the edge rather than globally guessing a same-named method.  
**Caveat:** Third-party dependency symbols are not necessarily recognized as `external`. The positive classifier is based heavily on provider built-in knowledge, so unresolved imported library types can remain `unknown`.

### 4.5 Ambiguity and overload refusal

Same-file overload resolution can use arity, argument types, normalization, conversion rank, language rules, and ownership. When multiple plausible targets remain, the implementation records a suppression and emits no arbitrary edge.

Callable-flow and selected dispatch fan-outs are bounded, generally at 32 targets. Over-cap sites can emit no partial target set and record a warning.

This policy favors precision, but it also lowers graph recall. A clean-looking graph can therefore be incomplete by deliberate design.

### 4.6 Critical exception: free-call global fallback

The highest-priority resolution caveat is in [`free-call-fallback.ts`](https://github.com/abhigyanpatwari/GitNexus/blob/fe3d7e56be5a557e051f12684dfbdce9d5a31920/gitnexus/src/core/ingestion/scope-resolution/passes/free-call-fallback.ts), especially `emitFreeCallFallback()` and `pickUniqueGlobalCallable()`.

The current source explicitly states that its first-version global fallback can ignore import context. When enabled, a globally unique callable can be selected even when the caller has not been proved to import the target package.

Mitigations include:

- per-language/provider opt-in;
- file-local candidate filtering;
- optional caller-visibility filtering;
- distinct-name ambiguity refusal;
- arity and type narrowing;
- built-in guards;
- instance-method ownership gates.

The remaining weakness is still material:

- a globally unique callable can be selected without import proof;
- a cross-file target is labelled `import-resolved` based on file inequality;
- the emitted `CALLS` relationship receives confidence `0.85`.

This does not preserve the architecture document's generalized `0.95` same-file, `0.9` import-scoped, and `0.5` global-fallback distinction. Current source behavior is authoritative.

**Conclusion:** GitNexus refuses many weak receiver and overload resolutions, but the entire graph cannot be characterized as strictly refusing every low-evidence global match.

### 4.7 Tool-level symbol ambiguity

The MCP backend has a separate query-time resolver in [`LocalBackend.resolveSymbolCandidates()`](https://github.com/abhigyanpatwari/GitNexus/blob/fe3d7e56be5a557e051f12684dfbdce9d5a31920/gitnexus/src/mcp/local/local-backend.ts).

Its main rules are:

- exact UID: resolve directly;
- exactly one candidate: resolve;
- class/constructor collapse: only when uniqueness and complete candidate coverage are proved;
- strongly hinted candidate: resolve only when the top score is at least `0.95` and exceeds the runner-up by more than `0.09`;
- all other multi-candidate cases: return explicit ambiguity and ranked candidates.

The candidate window is deterministically ordered and capped at 20. A separate count query reports the full total where possible; count failures are marked as lower bounds.

Without a file hint, ordinary score contributions do not reach the confident-selection threshold. `context` and `trace` therefore return disambiguation candidates rather than choosing a common symbol arbitrarily. `impact` can analyze multiple ambiguous candidates while retaining uncertainty.

**Fact:** Query-time ambiguity handling is more conservative than arbitrary first-result lookup.  
**Caveat:** It cannot repair an incorrect `CALLS` edge already emitted during indexing.

---

## 5. Graph schema and documentation drift

The authoritative schema constants are in [`gitnexus-shared/src/lbug/schema-constants.ts`](https://github.com/abhigyanpatwari/GitNexus/blob/fe3d7e56be5a557e051f12684dfbdce9d5a31920/gitnexus-shared/src/lbug/schema-constants.ts). LadybugDB DDL and endpoint-pair rules are in [`gitnexus/src/core/lbug/schema.ts`](https://github.com/abhigyanpatwari/GitNexus/blob/fe3d7e56be5a557e051f12684dfbdce9d5a31920/gitnexus/src/core/lbug/schema.ts).

### 5.1 Node labels

The current source defines 32 node labels:

```text
File, Folder, Function, Class, Interface, Method, CodeElement,
Community, Process, Section, Struct, Enum, Macro, Typedef, Union,
Namespace, Trait, Impl, TypeAlias, Const, Static, Variable, Property,
Record, Delegate, Annotation, Constructor, Template, Module, Route,
Tool, BasicBlock
```

### 5.2 Relationship types

The current source defines 30 relationship names:

```text
CONTAINS, DEFINES, IMPORTS, CALLS, EXTENDS, IMPLEMENTS,
HAS_METHOD, HAS_PROPERTY, ACCESSES, METHOD_OVERRIDES, OVERRIDES,
METHOD_IMPLEMENTS, MEMBER_OF, STEP_IN_PROCESS, HANDLES_ROUTE,
FETCHES, HANDLES_TOOL, ENTRY_POINT_OF, WRAPS, QUERIES, INJECTS,
CONDITIONAL_ON, DECLARES, ADVISED_BY, CFG, REACHING_DEF, TAINTED,
SANITIZES, TAINT_PATH, CDG, POST_DOMINATE
```

`ARCHITECTURE.md` also names relationships such as `USES`, `DECORATES`, `BINDS_EVENT_HANDLER`, and `EMITS_EVENT`, but those names do not appear in the authoritative current `REL_TYPES`. Conversely, the current source constants include optional PDG relationships not represented consistently in every prose summary.

**Fact:** The documentation and current schema constants have drifted.  
**Audit policy:** Current source constants take precedence.  
**Unverified:** This audit did not execute every optional PDG mode, so schema reservation is verified but complete live emission of each optional relationship is not.

---

## 6. Architecture clustering

Clustering is implemented in [`community-processor.ts`](https://github.com/abhigyanpatwari/GitNexus/blob/fe3d7e56be5a557e051f12684dfbdce9d5a31920/gitnexus/src/core/ingestion/community-processor.ts), principally through `processCommunities()`, `buildCommunityProjection()`, and `runGraphologyLeiden()`.

The projection contains functions, classes, methods, and interfaces, with clustering relationships from:

- `CALLS`;
- `EXTENDS`;
- `IMPLEMENTS`.

The projected graph is unweighted, deduplicated, and undirected. Nodes and edges are sorted before clustering. The default Graphology Leiden path uses a seeded RNG with seed `0xc0de`.

For large graphs, the implementation can filter low-confidence and degree-one content. Resolution and iteration settings vary by graph size. A timeout falls back to assigning all nodes to community zero. Community names are heuristically generated from paths and symbol prefixes; cohesion is estimated from a bounded sample.

Classification:

- **Deterministic given the same graph, implementation, engine, and ordering:** default seeded path.
- **Heuristic but reproducible:** projection filtering, resolution, labels, and sampled cohesion.
- **Potentially engine-dependent:** optional alternative community engine and partition normalization.
- **Not proven benchmark-causal:** no public Akon ablation isolates community information.

---

## 7. Execution-process construction

Processes are built in [`process-processor.ts`](https://github.com/abhigyanpatwari/GitNexus/blob/fe3d7e56be5a557e051f12684dfbdce9d5a31920/gitnexus/src/core/ingestion/process-processor.ts), including `processProcesses()`, `traceFromEntryPoint()`, `deduplicateTraces()`, and `buildSinkFunctionSet()`.

### 7.1 Construction algorithm

The processor:

1. builds forward and reverse adjacency from `CALLS`;
2. excludes call edges below confidence `0.5`;
3. scores candidate entry points;
4. normally excludes test-owned entry points;
5. requires useful outgoing call behavior;
6. orders candidates deterministically;
7. considers at most 200 entry candidates;
8. performs bounded DFS over callees;
9. prevents cycles within a trace;
10. identifies terminal or interesting sinks;
11. deduplicates traces;
12. ranks and round-robins surviving traces;
13. creates `Process` nodes and `STEP_IN_PROCESS` relationships;
14. links matching routes and tools to a process where possible.

Important defaults include:

| Bound | Current value or behavior |
|---|---:|
| Maximum trace depth | 10 |
| Maximum branching per visited node | 4 |
| Nominal maximum process count | 75 |
| Minimum process length | 3 |
| Maximum entry candidates considered | 200 |
| Approximate per-entry trace budget | 12 |
| Minimum `CALLS` confidence | 0.5 |

Outbound fetch and ORM/database evidence can mark sink behavior and is attributed to the innermost containing function.

### 7.2 Truncation and completeness

The implementation records truncation statistics such as:

- dropped entry candidates;
- entry points not explored;
- walks stopped at maximum depth;
- callees dropped by the branch cap;
- traces dropped by per-entry limits;
- processes dropped by the final cap.

**Fact:** Process construction is reproducible under stable graph input and implementation order.  
**Fact:** It is deliberately bounded and therefore incomplete.  
**Fact:** It operates over static call relationships, not observed runtime execution.  
**Inference:** Precomposed processes can reduce the number of graph hops an agent must request separately.  
**Unverified:** No public evidence isolates process views as the cause of Akon's benchmark delta.

The defensible description is:

> A deterministic, bounded, heuristically selected summary of likely execution flows over the static call graph.

It is not defensible to call every generated process a complete or proven runtime path.

---

## 8. Retrieval and precomposed relational tools

The central local backend is [`LocalBackend`](https://github.com/abhigyanpatwari/GitNexus/blob/fe3d7e56be5a557e051f12684dfbdce9d5a31920/gitnexus/src/mcp/local/local-backend.ts).

### 8.1 `query`

`LocalBackend.query()` combines:

- LadybugDB full-text/BM25 retrieval;
- optional embedding similarity;
- reciprocal-rank fusion with `k = 60`;
- process-membership enrichment;
- community cohesion as a small ranking contribution;
- symbol and source enrichment;
- deterministic tie-breaking;
- partial/degraded warnings when retrieval channels fail.

Its response is precomposed into related processes, symbols grouped under processes, and direct definitions. Embeddings are optional; symbolic and BM25 retrieval continue when dense retrieval is unavailable.

### 8.2 `context`

`LocalBackend.context()` produces a categorized symbol view including:

- callers and callees;
- imports;
- inheritance and implementation relationships;
- methods and properties;
- accesses;
- process participation;
- optional source content;
- ambiguity candidates;
- lower-bound epistemic warnings.

Relationship categories are capped, generally around 30 rows each. The phrase “360-degree context” describes relational breadth, not unlimited completeness.

### 8.3 `impact`

`LocalBackend.impact()` performs bounded relationship traversal, groups results by depth and risk, and uses stored edge confidence where present. It preserves ambiguity and can label counts as lower bounds when unresolved receiver sites or interface indirection make the answer incomplete.

### 8.4 `detect_changes`

`LocalBackend.detectChanges()`:

1. obtains the requested Git diff;
2. maps changed hunks to overlapping indexed symbol ranges;
3. maps affected symbols into processes through `STEP_IN_PROCESS`;
4. summarizes affected processes;
5. assigns a risk category from affected-process counts.

This is a graph-derived change-surface estimate. It is not proof that every affected runtime behavior has been found.

### 8.5 `trace`

`LocalBackend.trace()` performs bounded path search over supported call and structural relationships. Ambiguous endpoint names produce disambiguation data rather than arbitrary endpoint selection.

### 8.6 Output budgets

[`output-budget.ts`](https://github.com/abhigyanpatwari/GitNexus/blob/fe3d7e56be5a557e051f12684dfbdce9d5a31920/gitnexus/src/mcp/output-budget.ts) applies optional budgets to `query`, `context`, and `impact`.

The budget estimator assumes four UTF-8 bytes per token and truncates the output prefix with a marker. It is neither tokenizer-accurate nor aware of semantic record boundaries.

### 8.7 Precomputed relational intelligence claim

**Fact:** A substantial amount of graph expansion, process grouping, ambiguity handling, confidence handling, and result formatting occurs before the model receives a response.  
**Inference:** One composed response can replace several manually chained graph requests.  
**Unverified:** The public benchmark does not report how many explicit graph calls, automatic augmentations, or ordinary searches occurred, so it cannot establish that this composition was the dominant source of uplift.

---

## 9. Delivery and hook architecture

### 9.1 Fast-path augmentation

The shared augmentation path is implemented by:

- [`augmentation/engine.ts` — `augment()`](https://github.com/abhigyanpatwari/GitNexus/blob/fe3d7e56be5a557e051f12684dfbdce9d5a31920/gitnexus/src/core/augmentation/engine.ts)
- [`cli/augment.ts` — `augmentCommand()`](https://github.com/abhigyanpatwari/GitNexus/blob/fe3d7e56be5a557e051f12684dfbdce9d5a31920/gitnexus/src/cli/augment.ts)

The fast path deliberately uses BM25 rather than embeddings. It:

1. retrieves files for the search pattern;
2. maps high-ranking files to symbols;
3. retains up to five unique symbols;
4. fetches up to three callers and three callees per symbol;
5. fetches process participation;
6. uses cohesion internally for ranking;
7. emits compact relational text;
8. returns an empty result on error.

The source states cold/warm latency targets, but this audit did not verify production latency distributions.

### 9.2 Claude Code

Claude's primary plugin hook is:

- [`gitnexus-claude-plugin/hooks/gitnexus-hook.js`](https://github.com/abhigyanpatwari/GitNexus/blob/fe3d7e56be5a557e051f12684dfbdce9d5a31920/gitnexus-claude-plugin/hooks/gitnexus-hook.js)
- [`gitnexus-claude-plugin/hooks/hooks.json`](https://github.com/abhigyanpatwari/GitNexus/blob/fe3d7e56be5a557e051f12684dfbdce9d5a31920/gitnexus-claude-plugin/hooks/hooks.json)

`PreToolUse` recognizes `Grep`, `Glob`, and Bash searches using `grep` or `rg`. It extracts a pattern, invokes `gitnexus augment`, and returns `hookSpecificOutput.additionalContext`.

Operational controls include:

- seven-second child timeout;
- ten-second hook timeout;
- per-repository concurrency slots;
- silent graceful failure outside debug mode;
- database-owner detection;
- a throttled MCP-query hint when the local augment process cannot access the DB.

`PostToolUse` monitors successful `git commit`, `merge`, `rebase`, `cherry-pick`, and `pull` commands. It compares current `HEAD` with the indexed commit and tells the agent to reindex if stale.

**Fact:** The hook detects and reports stale state.  
**Fact:** It does not automatically rebuild the index.

A session-start script also exists at [`gitnexus/hooks/claude/session-start.sh`](https://github.com/abhigyanpatwari/GitNexus/blob/fe3d7e56be5a557e051f12684dfbdce9d5a31920/gitnexus/hooks/claude/session-start.sh). The current plugin source notes a Windows SessionStart problem and uses project context/skills as an alternative delivery path.

### 9.3 Cursor

Cursor uses `postToolUse` for Shell, Read, and Grep:

- [`gitnexus-cursor-integration/hooks/gitnexus-hook.cjs`](https://github.com/abhigyanpatwari/GitNexus/blob/fe3d7e56be5a557e051f12684dfbdce9d5a31920/gitnexus-cursor-integration/hooks/gitnexus-hook.cjs)
- [`gitnexus-cursor-integration/hooks/hooks.json`](https://github.com/abhigyanpatwari/GitNexus/blob/fe3d7e56be5a557e051f12684dfbdce9d5a31920/gitnexus-cursor-integration/hooks/hooks.json)

The original tool runs first; graph context is appended to its result.

### 9.4 Antigravity

Antigravity's adapter is [`gitnexus-antigravity-hook.cjs`](https://github.com/abhigyanpatwari/GitNexus/blob/fe3d7e56be5a557e051f12684dfbdce9d5a31920/gitnexus/hooks/antigravity/gitnexus-antigravity-hook.cjs).

Its before-tool protocol cannot inject context, so augmentation runs after the tool and is delivered through `additionalContext`. Stale-index notices use the same channel.

### 9.5 Delivery implications

| Agent action | GitNexus behavior | Extra model decision? | Important caveat |
|---|---|---:|---|
| Grep/search in Claude | Pre-tool BM25 relational augmentation | No | Adds lookup latency and context tokens |
| Read/Grep/Shell in Cursor | Post-tool augmentation | No | Original exploration already occurred |
| Search in Antigravity | After-tool augmentation | No | Platform cannot inject before execution |
| Explicit MCP `query/context/impact` | Precomposed relational result | Yes | Consumes an agent action unless hidden by the host |
| Git mutation | Staleness check and reindex hint | No | Does not itself refresh the index |

**Inference:** Automatic augmentation can replace later exploration if it supplies the needed relation in the first eligible observation.  
**Unverified:** Without trajectories, it is unknown how often augmentation terminated exploration versus adding context before the model performed the same exploration anyway.

---

## 10. Public GitNexus evaluation harness

The public evaluation implementation defines three modes:

| Mode | Public implementation |
|---|---|
| `baseline` | Standard shell tools |
| `native` | Changed prompts plus explicit GitNexus query/context/impact/cypher commands |
| `native_augment` | Native treatment plus automatic graph augmentation of grep/rg observations |

Primary sources:

- [`eval/README.md`](https://github.com/abhigyanpatwari/GitNexus/blob/fe3d7e56be5a557e051f12684dfbdce9d5a31920/eval/README.md)
- [`GitNexusAgent.execute_actions()` and `_maybe_augment()`](https://github.com/abhigyanpatwari/GitNexus/blob/fe3d7e56be5a557e051f12684dfbdce9d5a31920/eval/agents/gitnexus_agent.py)
- [`system_baseline.jinja`](https://github.com/abhigyanpatwari/GitNexus/blob/fe3d7e56be5a557e051f12684dfbdce9d5a31920/eval/prompts/system_baseline.jinja)
- [`instance_baseline.jinja`](https://github.com/abhigyanpatwari/GitNexus/blob/fe3d7e56be5a557e051f12684dfbdce9d5a31920/eval/prompts/instance_baseline.jinja)
- [`system_native_augment.jinja`](https://github.com/abhigyanpatwari/GitNexus/blob/fe3d7e56be5a557e051f12684dfbdce9d5a31920/eval/prompts/system_native_augment.jinja)
- [`instance_native_augment.jinja`](https://github.com/abhigyanpatwari/GitNexus/blob/fe3d7e56be5a557e051f12684dfbdce9d5a31920/eval/prompts/instance_native_augment.jinja)
- [`baseline.yaml`](https://github.com/abhigyanpatwari/GitNexus/blob/fe3d7e56be5a557e051f12684dfbdce9d5a31920/eval/configs/modes/baseline.yaml)
- [`native.yaml`](https://github.com/abhigyanpatwari/GitNexus/blob/fe3d7e56be5a557e051f12684dfbdce9d5a31920/eval/configs/modes/native.yaml)
- [`native_augment.yaml`](https://github.com/abhigyanpatwari/GitNexus/blob/fe3d7e56be5a557e051f12684dfbdce9d5a31920/eval/configs/modes/native_augment.yaml)

The automatic path executes the original model-selected action, invokes `gitnexus-augment` host-side, and appends the result to the same observation.

This treatment bundles at least:

- a different system prompt;
- a different instance prompt;
- explicit GitNexus command availability;
- a recommended graph-first workflow;
- risk-assessment guidance;
- automatic observation augmentation;
- hidden host-side graph work.

The current public `native_augment` configuration has a step limit of 30. Akon's DeepSWE page reports approximately 45-50 average steps. The public model configurations also do not identify the reported `openai/gpt-5.6-terra` setup.

**Conclusion:** The public eval directory documents an important delivery implementation, but it cannot be assumed to be the exact harness used for Akon's published DeepSWE result.

---

## 11. Akon DeepSWE benchmark

The [Akon benchmark page](https://www.akonlabs.com/benchmarks) reports:

| Arm | Pass rate | Cost per trial | Output tokens | Steps |
|---|---:|---:|---:|---:|
| GitNexus | 68.37% | $0.6008 | 21,077 | 44.94 |
| Graphify | 54.02% | $0.6364 | 21,769 | 48.00 |
| Bare model | 36.99% | $0.6631 | 22,252 | 50.25 |

Reported model: `openai/gpt-5.6-terra (med)`.

Reported point differences:

- GitNexus versus Bare: `+31.38` percentage points;
- Graphify versus Bare: `+17.03` points;
- GitNexus versus Graphify: `+14.35` points.

The page further reports:

- 113 tasks;
- 89 projects;
- a 116-entry manifest;
- 3,471 trials;
- 10 trials per task per arm;
- GitNexus wins on 98 tasks, ties on 8, and loses on 7 against Bare;
- a two-proportion z-test;
- GitNexus 95% pass-rate interval of 65.6%-71.0%;
- Bare interval of 34.3%-39.8%.

### 11.1 Trial arithmetic does not reconcile

The disclosed quantities cannot all be true under a simple complete design:

```text
113 tasks * 3 arms * 10 trials = 3,390
116 entries * 3 arms * 10 trials = 3,480
reported total                 = 3,471
```

`3,471 / 3 = 1,157` trials per arm. That is 27 more per arm than `113 * 10`, or three fewer per arm than `116 * 10`.

The page does not explain whether this arose from:

- retries;
- invalid or censored rows;
- excluded tasks;
- replacement attempts;
- infrastructure failures;
- an earlier 116-task manifest;
- uneven arm denominators;
- simple reporting error.

This matters because pass rates and confidence intervals depend on the actual denominator and exclusion policy.

### 11.2 Confidence-interval concern

The published interval widths are approximately what a simple binomial calculation produces for about 1,157 independent attempts per arm. This is an inference because Akon does not publish the CI implementation.

Ten attempts on one task share repository, prompt, verifier, and task difficulty. They are therefore clustered observations rather than ten unrelated task samples. Treating all attempts as independent generally produces narrower uncertainty than a task-clustered bootstrap, per-task paired analysis, or hierarchical model.

The disclosed two-proportion z-test appears vulnerable to the same unit-of-analysis issue, although the exact test inputs are not public.

### 11.3 Difficulty-group selection

Akon groups tasks as easy, moderate, or hard according to the Bare arm's observed solve rate, then reports treatment gains within those groups. It reports 55.9% GitNexus versus 15.9% Bare on the 58 hardest tasks, described as a 3.5x result.

**Fact:** The grouping variable is measured Bare performance.  
**Inference:** Selecting the hard group because Bare happened to score poorly and then estimating the Bare-versus-treatment gap in the same samples introduces regression-to-the-mean and selection effects. The hard-group ratio may still indicate a real effect, but the disclosed procedure does not cleanly estimate its magnitude.

A cleaner difficulty definition would use an independent run, a separate model/configuration, historical task statistics, reference complexity, or leave-one-trial-out grouping.

### 11.4 Lower cost and steps are not isolated navigation effects

The treatment has higher success and lower average steps, output tokens, and cost. Those observations are compatible with more efficient navigation, but they do not prove it.

Possible mediators include:

- successful trials terminating earlier;
- failed trials exhausting larger fractions of the budget;
- changed test-running behavior;
- changed reasoning verbosity from the prompt;
- automatic context replacing searches;
- automatic context adding information that changes strategy;
- different tool latency or accounting;
- different exclusion or retry handling.

Raw trajectories and matched task-level mediation analysis are required to separate these effects.

---

## 12. Conflict with official DeepSWE methodology

Official DeepSWE sources describe:

- 113 original tasks;
- 91 active repositories;
- TypeScript, Go, Python, JavaScript, and Rust;
- tasks authored from scratch;
- reference solutions never merged upstream;
- some tasks motivated by unresolved issues, but not copied from public fixes;
- hand-written functional verifiers;
- shallow-clone task environments;
- mini-swe-agent as the official leaderboard harness.

See the [official repository](https://github.com/datacurve-ai/deep-swe), [official site](https://deepswe.datacurve.ai/), and [paper](https://arxiv.org/abs/2607.07946).

Akon's page instead describes:

- 89 projects;
- a 116-entry manifest;
- Python, Go, TypeScript, and Rust;
- every task as an issue someone filed;
- tasks paired with the test suite failing at that time.

These are not equivalent descriptions. The official paper says tasks and reference solutions were authored from scratch and that only some tasks were motivated by unresolved issues. DeepSWE verifiers were purpose-written rather than merely inherited from whatever project tests were failing when an issue was filed.

Possible explanations include an earlier/private manifest, different project deduplication, a selected subset, or inaccurate marketing copy. None is publicly documented.

---

## 13. Bare, Graphify, and GitNexus confounds

### 13.1 What the benchmark page establishes

The page characterizes:

- Bare as having no retrieval layer;
- Graphify as having “code extraction only”;
- GitNexus as having its code graph;
- all arms as using the same model and scaffold.

### 13.2 Graphify is not reproducibly defined

The public primary sources do not specify Graphify's:

- repository or commit;
- parser;
- graph schema;
- scope resolution;
- call resolution;
- prompt;
- tools;
- output format;
- retrieval and ranking;
- automatic hooks;
- embedding configuration;
- process construction;
- index lifecycle;
- ambiguity policy;
- token budget.

The `54.02% -> 68.37%` difference therefore cannot be attributed specifically to semantic resolution, processes, Leiden communities, embeddings, compact formatting, impact analysis, or hook delivery.

### 13.3 GitNexus treatment bundling

The public GitNexus eval implementation proves that a GitNexus treatment can combine changed prompts, explicit graph tools, workflow guidance, risk guidance, and automatic observation augmentation. The private benchmark may differ, but Akon does not publish enough information to show that it does.

Consequently, “the only difference is what the agent can ask” is not an adequate experimental specification. The relevant variables include:

- what the model is told to ask;
- what tools exist;
- what context is appended automatically;
- whether a host query consumes a model step;
- how responses are grouped and capped;
- whether embeddings are available;
- how stale or failed indexes are handled.

### 13.4 Strongest justified causal claim

The strongest defensible claim is:

> Akon's undisclosed GitNexus-enhanced configuration substantially outperformed its undisclosed Bare and Graphify configurations on the reported DeepSWE run.

It is not defensible from the public evidence to claim that an individual GitNexus feature caused a specific portion of the delta.

---

## 14. Determinism audit

| Stage | Classification | Basis and caveat |
|---|---|---|
| File enumeration after discovery | Deterministic given filesystem snapshot | Canonical sorting; filesystem availability still external |
| Ignore policy | Deterministic | Config and ignore files affect result |
| Tree-sitter parsing | Deterministic given bytes, grammar, and provider version | Parser/grammar version changes output |
| Parse-cache lookup | Deterministic | Corruption or version mismatch becomes a miss |
| Scope binding | Deterministic given ordered semantic artifacts | Language hooks and bounded indexes affect coverage |
| Receiver resolution | Deterministic | Can suppress or remain unknown |
| Free-call fallback | Deterministic but potentially unsound | Global uniqueness can substitute for import proof |
| Overload ambiguity | Deterministic refusal | May reduce recall |
| Tool symbol resolution | Heuristic but reproducible | Scoring thresholds and deterministic tie-breaks |
| Graph construction | Deterministic given emitted artifacts | Missing/incorrect evidence remains missing/incorrect |
| Leiden communities | Seeded heuristic | Engine/config changes can alter partition |
| Process construction | Deterministic bounded heuristic | Depth, branching, confidence, and count caps |
| BM25 retrieval | Deterministic given index | Index/tokenization version dependent |
| Embedding inference | Model/external-runtime dependent, normally reproducible | Optional and sensitive to model/runtime revision |
| RRF ranking | Deterministic given channel results | Channel failures change inputs |
| Context/impact composition | Deterministic given graph and parameters | Capped and potentially lower-bound |
| Automatic augmentation | Deterministic given search pattern and current index | Hook timing, DB locks, timeout, and process availability are external |
| Model tool choice | Model-dependent | Not controlled by graph determinism |
| Benchmark outcome | Model-, provider-, environment-, and verifier-dependent | Sampling and infrastructure policy undisclosed by Akon |

The useful determinism claim is not “GitNexus is 100% deterministic.” It is:

> GitNexus moves a substantial amount of repository traversal, graph expansion, ambiguity handling, process grouping, and result composition outside the coding model into mostly deterministic or reproducible host-side computation.

---

## 15. Source-backed strengths and limitations

### 15.1 Strong mechanisms

1. Explicit resolution outcomes and candidate provenance.
2. Positive-evidence distinction between external and unknown receivers.
3. Lower-bound reporting for known graph incompleteness.
4. Conservative query-time disambiguation.
5. Bounded process construction with explicit truncation metrics.
6. Process-grouped, precomposed query responses.
7. Diff-to-symbol-to-process composition.
8. Automatic augmentation of existing agent actions.
9. Persistent index, parse cache, and stale-index checks.
10. Graceful degradation when optional retrieval channels fail.

### 15.2 Material limitations

1. Global free-call fallback can ignore import context.
2. External classification is not a complete dependency type system.
3. Dynamic dispatch, reflection, framework behavior, and unresolved receivers lower call-graph recall.
4. Processes are bounded static summaries, not complete runtime paths.
5. Clusters are heuristic and not proven benchmark-causal.
6. `context` and `impact` are capped and can return lower bounds.
7. MCP output budgeting uses rough byte/token conversion and prefix truncation.
8. Hook augmentation can time out, skip under contention, or use a stale index until the agent reindexes.
9. Current source and `ARCHITECTURE.md` disagree on parts of the schema.
10. The public benchmark evidence does not isolate implementation mechanisms.

---

## 16. GroundTruth implications

This section translates source-backed GitNexus patterns into bounded GroundTruth engineering implications. It does not claim that Akon's benchmark proves any individual change will improve GroundTruth's resolve rate.

### 16.1 Preserve the distinction between raw evidence and delivered treatment

GitNexus's important product property is not only the amount of graph data. It precomputes process membership, categorized context, ambiguity outcomes, and impact layers before the model receives a response. Its hooks can also place that answer into an action the model already chose.

GroundTruth should therefore continue to evaluate four separate layers:

1. raw repository evidence;
2. semantic resolution and uncertainty;
3. relational composition;
4. provider-visible delivery timing and cost.

An implementation can have stronger raw semantics and still underperform if the benchmark path bypasses them or requires additional model decisions to retrieve them.

### 16.2 Adopt uncertainty patterns, not GitNexus's weak global fallback

The patterns worth preserving are:

- `program`, `external`, and `unknown` origin classes;
- explicit ambiguity and candidate provenance;
- unresolved outcomes as first-class records;
- lower-bound rather than exact claims when graph coverage is known incomplete;
- no correction or invented edge when receiver type or import ownership is unresolved.

The pattern not to copy is GitNexus's current globally unique free-call fallback without import proof. Uniqueness across a workspace does not establish semantic visibility. GroundTruth's rule should remain:

> Unknown is terminal for corrective action unless positive, revision-current evidence establishes the target.

### 16.3 Compose existing graph assets into bounded process views

GitNexus's process builder is relatively small composition logic over an existing call graph. It does not require replacing the parser or graph store.

If GroundTruth already has revision-current `CALLS`, route, test, assertion, import, and change-surface evidence, a compatible process view can be built as a deterministic projection with:

- explicit entry-point evidence;
- minimum relationship confidence;
- deterministic traversal order;
- cycle handling;
- strict branch/depth/process caps;
- provenance for every step;
- persisted truncation and epistemic status;
- no obligation generated from an uncertified process edge.

The likely value is response composition: one bounded process surface can expose coupled symbols and tests without requiring repeated caller/callee queries. That hypothesis should be tested on historical incomplete-fix failures before being enabled broadly.

### 16.4 Deliver through existing actions when evidence is timely

GitNexus's hooks demonstrate a concrete delivery pattern: enrich an existing search/read action rather than require a separate graph-tool decision.

GroundTruth's current provider-boundary context compiler, preemptive retrieval, and persistent execution state already target zero-extra-turn delivery. The useful lesson is narrower:

- attach only first-eligible, revision-current relational evidence;
- cap complete evidence records rather than raw graph dumps;
- avoid generic guidance streams;
- record whether the evidence replaced a later search, changed an opened/edited file set, or merely added tokens;
- distinguish host-side graph work from model actions in accounting.

Automatic delivery is not inherently helpful. It is helpful only when its precision and timing reduce total exploration or prevent a measured failure.

### 16.5 Preserve GroundTruth's stronger evidence where available

GitNexus uses Tree-sitter and language-specific semantic reconstruction. GroundTruth's LSP/compiler diagnostics, hover/type information, installed-environment knowledge, runtime introspection, and validation evidence can be stronger for supported languages and healthy environments.

GroundTruth should not replace stronger positive evidence with a parallel heuristic resolver merely to resemble GitNexus. The useful combined pattern is:

```text
LSP/compiler/runtime positive evidence
  -> explicit provenance and unknown handling
  -> deterministic graph composition
  -> bounded process/change-surface response
  -> zero-extra-turn provider delivery
```

AST-only paths should remain a graceful fallback with visibly weaker confidence, not silently masquerade as equivalent to full semantic resolution.

### 16.6 Benchmark implications

GroundTruth should avoid the reproducibility defects present in Akon's public report:

- freeze exact task, harness, model, graph, and treatment SHAs;
- reconcile manifest, denominator, attempts, retries, and exclusions exactly;
- publish per-arm task and attempt counts;
- treat attempts as clustered within tasks;
- freeze difficulty groups independently of the control outcomes being compared;
- expose exact prompts and automatic augmentation behavior;
- count hidden host queries, indexing, tokens, latency, and failures;
- publish task-level paired results and trajectories where permitted;
- separate configuration uplift from feature-level causal claims;
- ablate delivery, composition, graph resolution, and embeddings independently.

### 16.7 Highest-value GroundTruth hypotheses to test

These are hypotheses, not implementation authorization:

1. **Uncertainty provenance gate:** Ensure every corrective or obligation-producing semantic result distinguishes program, external, ambiguous, stale, and unknown origins. Unknown and ambiguity remain silent for correction.

2. **Precomposed relational slice:** Use current certified graph data to return one compact, depth- and confidence-grouped surface containing focus symbols, callers/callees, processes, tests/assertions, and affected files. Evaluate whether it reduces incomplete fixes without additional turns.

3. **Existing-action delivery:** Deliver that slice at the first existing provider boundary after a relevant search, read, edit, diff, or validation event, with strict deduplication and request-hash proof.

The key causal chain to test is:

```text
certified relational composition
  -> fewer model-selected discovery actions
  -> earlier coupled-file/test visibility
  -> fewer incomplete fixes and negative flips
  -> equal or lower turns and evidence tokens
```

### 16.8 Patterns not justified for GroundTruth adoption

- Replacing LSP/compiler semantics with Tree-sitter wholesale.
- Copying Leiden clustering before a measured failure requires architecture communities.
- Enabling a global unique-name call fallback without import proof.
- Treating a process as a complete execution trace.
- Adding an explicit graph tool when equivalent context can be supplied through an existing action.
- Adding embeddings without an independent retrieval ablation.
- Claiming benchmark lift from the existence of a feature rather than a frozen matched experiment.

---

## 17. Reproducibility requirements for an independent Akon replication

An independently reproducible comparison requires Akon to publish or freeze at least:

1. GitNexus source commit and build artifact digest;
2. benchmark harness and adapter commit;
3. exact DeepSWE manifest and task exclusions;
4. Graphify source, configuration, and prompts;
5. Bare, Graphify, and GitNexus system/instance prompts;
6. model provider, catalog ID, reasoning mode, temperature, and sampling settings;
7. maximum steps, tokens, cost, wall time, and retries;
8. embeddings enabled/disabled, model revision, and dimensions;
9. GitNexus tools and hooks enabled in each arm;
10. indexing timeout, failure, and stale-index policy;
11. whether indexing cost and latency are included;
12. exact trial denominator and reason for the 3,471 count;
13. infrastructure-error and censored-attempt handling;
14. task-level pass counts and paired comparisons;
15. raw trajectories or sufficient event-level summaries;
16. task-clustered confidence intervals;
17. feature ablations separating graph extraction, resolution, processes, retrieval, prompt, and automatic augmentation.

Until these are available, the benchmark should be cited as a reported Akon configuration result, not a fully reproducible demonstration that a named GitNexus mechanism caused the uplift.

---

## 18. Final conclusions

### A. What the source proves GitNexus does well

- It performs substantial deterministic repository reasoning before the coding model's next decision.
- It models many ambiguous and unresolved resolution outcomes explicitly.
- It composes graph information into process-grouped query, symbol context, impact, and diff-impact responses.
- It can deliver graph context through ordinary agent actions without another model decision.
- It persists indexes and parse results and detects stale commit state.

### B. Where the source contradicts a uniformly conservative narrative

- Global free-call fallback can ignore import context.
- Cross-file fallback edges receive confidence `0.85` without preserving a distinct low-confidence global tier.
- External dependency classification is incomplete.
- Process and context outputs remain bounded lower approximations.
- Source schema constants and architecture prose have drifted.

### C. What the benchmark supports

The benchmark supports a large reported performance difference between three Akon configurations under a nominally common model and scaffold.

### D. What the benchmark does not support

It does not identify which graph, resolution, retrieval, process, prompt, or delivery mechanism caused the difference. It is not presently reproducible from public sources.

### E. Most important implication for GroundTruth

The strongest engineering lesson is not “build GitNexus.” It is:

> Preserve GroundTruth's strongest positive semantic evidence, make uncertainty and abstention explicit, compose certified relationships into one bounded decision-relevant response, and deliver that response through an action the agent was already taking. Then prove the effect with task-clustered, fully frozen evaluation accounting.

