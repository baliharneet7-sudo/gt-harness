# Final GroundTruth Build TODO

## Objective

Build the strongest GroundTruth from measured GT failures and source-level lessons learned from
GitNexus. GitNexus is not a benchmark arm. The final outcome comparison is baseline versus previous
small-run GT versus strengthened GT on the frozen 20-task setup.

## What GT was doing wrong

| Failure | Engineering correction | Status |
|---|---|---|
| GT tools added exploration turns instead of replacing search. | Compose evidence before the next existing provider request. | Implemented in unified repository context. |
| Validation/post-processing arrived after the decisive action. | Prefer pre-decision/current-boundary context; retain postflight only for observed facts. | Implemented for repository context. |
| Autocorrection guessed from unresolved/global similarity. | Program/external/unknown origin, exact/ambiguous/unresolved resolution, and terminal abstention. | Implemented and regression-frozen. |
| Benchmark path bypassed stronger product semantics. | Project durable semantic facts through one typed provider-boundary model; abstain on non-durable host-only evidence. | Implemented; exact LSP/runtime boundary inventoried. |
| Raw edges were weakly composed. | One semantic + directed execution + impact projection. | Implemented. |
| Incomplete fixes missed callers/tests/coupled files. | Reverse caller depth and certified test/relationship impact from changed anchors. | Implemented where certified graph relations exist. |
| Unrelated edits redelivered context. | Semantic claim identity independent of global revision plus current-revision validation. | Implemented. |
| Product accounting forked into a fake replacement mechanism. | Preserve exact 17+1 identity; repository context strengthens PES. | Implemented. |
| Benchmark configuration was hardcoded/self-attested. | Caller-owned treatment JSON plus a fail-closed manifest/runtime audit. | Manifest, typed observation builder, host-path loading, and fail-closed audit are implemented; final workflow capture remains a P3 gate. |

## Completed build work

- [x] Preserve `PersistentExecutionStateEngine` and its one bounded bootstrap.
- [x] Preserve the canonical 17 legacy mechanisms plus persistent state product census.
- [x] Read edge resolution provenance and treat missing provenance as unknown.
- [x] Refuse ambiguous, external, heuristic, stale, low-confidence, or content-unbound edges.
- [x] Add stable semantic evidence IDs and cross-call deduplication.
- [x] Add `RepositoryContextEngine` as the one strengthened provider surface.
- [x] Add directed, symbol-qualified CALLS views with cycle/depth/branch bounds.
- [x] Add reverse caller impact and certified test/inheritance/route/API/reference impact handling.
- [x] Route the projection through the existing contribution compiler with no extra executor turn.
- [x] Suppress duplicate legacy relational and semantic deliveries in the strengthened profile.
- [x] Add provider-evidence and delivery-audit support for repository context.
- [x] Add a strengthened-profile release gate without replacing the eighteenth mechanism.
- [x] Require `central_relational_v2` explicitly at the strengthened release gate; a legacy or
  missing self-declared profile cannot silently pass.
- [x] Remove built-in competitor/treatment arms from benchmark manifest construction.
- [x] Reject missing or mismatched observed runtime facts in the parity auditor. The final runner must
  produce those observations independently in P3; the agent does not manufacture missing facts.
- [x] Add focused tests for direction, ambiguity, provenance, deduplication, semantic test-role
  classification, unified delivery, product census, and runtime parity.
- [x] Invalidate pre-edit graph state on every failed source refresh; retry only one explicitly
  classified transient index failure.
- [x] Evaluate all five retrieval channels on every production retrieval state.
- [x] Abstain on ambiguous same-file definitions and ambiguous re-export targets.
- [x] Report observed context use without claiming counterfactual exploration replacement.

## P0-P2 completion state

### P0 — product semantics

- [x] Inventory exact full-product LSP/compiler/runtime-KB fields and map them to immutable
  origin/resolution/provenance records.
- [x] Project verified definitions, signatures, persisted hover-derived types, imports/re-exports,
  receiver types, observed compiler diagnostics, and external/runtime origins through
  `RepositoryEvidence` and its adjacent typed snapshot.
- [x] Preserve explicit unknown and ambiguity outcomes through storage and language adapters.
- [x] Bind semantic and relational endpoints to task-start repository origin. Graph rows on
  model-authored/generated/unknown paths remain controller-only.
- [x] Populate route, framework-entry, override/implementation, API-consumer, and test relations
  where source evidence certifies them.

Raw hover markdown, ephemeral LSP caches, and host-only runtime introspection are intentionally not
projected as benchmark facts. Durable/source-observed fields are used; otherwise GT abstains.

### P1 — destructive and incomplete-fix regressions

- [x] Add fixtures for Python builtins, stdlib symbols, third-party dependencies, framework
  classes, dynamic modules, re-exports, ambiguous globals, incomplete indexes, and unresolved
  receiver chains.
- [x] Reconstruct the destructive v6 cases and prove the strengthened path abstains.
- [x] Forensically inspect five negative flips, five both-fail tasks, and five GT gains from
  historical trajectories/artifacts.
- [x] Freeze the smallest predicted repository-context response and expected effect for every case
  before the final outcome run.

These are frozen counterfactual predictions, not executions of the current
`RepositoryContextEngine` against restored historical workspaces. Do not call them completed
replays unless those workspaces and trajectories are actually replayed.

### P2 — certified process and impact coverage

- [x] Add framework/route-aware entry classification without calling every graph root an entry.
- [x] Add return-type/receiver-chain propagation only for certified source/LSP/compiler evidence.
- [x] Bind diffs to exact action/revision signature-delta symbols before path fallback.
- [x] Add relevant check/test selection through existing task semantics without duplicate claims.
- [x] Distinguish context used without prior exploration, accompanying exploration, following
  exploration, and unmatched context without making a causal replacement claim.
- [x] Account rejected execution and non-call impact edges; correct abstention is release-valid and
  never converted into a forced provider delivery.

Detailed evidence is in `GT_P0_P2_IMPLEMENTATION_CLOSEOUT_2026-08-17.md` and the machine-readable
prediction is in `docs/benchmarks/GT_P0_P2_FROZEN_REPLAY_PREDICTIONS_2026-08-17.json`.

## Remaining TODOs

### P3 — final release proof, in order

- [x] Finish broad local tests and static/type checks on the final working tree: 1,848 tests
  collected; 1,843 runnable tests passed through the 1,847-test six-shard run plus the final
  endpoint-origin regression, with five expected platform/asset skips. Changed-file Ruff, bytecode
  compilation, and diff checks pass.
- [x] Review the final diff for stale zero-bootstrap/replacement-census behavior and duplicate
  provider surfaces.
- [x] Wire independent runner observations for task order, tool/hook envelopes, hardware, retry,
  timeout, embedding, and token accounting into the frozen TB2 `repair20-v1` task workflow. The
  workflow now creates source-owned documents after live budget/asset setup, composes them through
  the fixed-source builder, exports a runner-private `GT_RUNTIME_OBSERVATION_PATH`, and uploads
  the observation only after the task finishes. A copied declaration remains invalid.
- [ ] Freeze one exact commit.
- [ ] Run the exact-commit source-built Linux provider-free workflow with current indexer and pinned
  ONNX asset. This proves integrity, not uplift.
- [ ] Execute the current engine against the 15 selected historical trajectories/workspaces where
  those legal task artifacts can be restored. Record unavailable rows as unavailable; never turn
  the frozen counterfactual predictions into fake replay measurements.
- [ ] Freeze the final 20-task outcome prediction artifact.
- [ ] Run the final frozen 20-task comparison: baseline, previous GT small run, strengthened GT.
- [ ] Report resolve rate, flips, steps, calls, tokens, cost, evidence use, latency, abstentions, and
  invalid/provider-censored rows with the full denominator preserved.

## Do not build

- no GitNexus runtime adapter or comparison arm;
- no model-selected GroundTruth exploration tool;
- no post-generation fuzzy autocorrection;
- no benchmark task IDs, repository-specific rules, fixed step counts, or fixed trial counts in
  product/runtime code;
- no second product census replacing persistent state;
- no architecture clustering without a concrete historical failure it would change;
- no parallel replacement indexer when existing GT evidence can be composed; and
- no outcome claim before the final matched benchmark.

## Exact next step

Freeze one exact commit and run the source-built Linux provider-free workflow. The Go
resolver already passes Linux `go test ./...` and a source build in the existing Codespace, but that
is not the exact-commit provider-free release proof. Benchmarking remains the final step.
