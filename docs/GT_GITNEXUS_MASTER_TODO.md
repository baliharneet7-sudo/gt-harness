# Final GroundTruth Build TODO

## 2026-08-18 post-smoke correction

The archived regression smoke `32106687133` is diagnostic evidence, not proof of
`central_relational_v2`. It ran commit
`40b5332d0bbd91560f5118ffdcd98654ec1eb503` with treatment profile
`central_pes_v1`; the inspected receipts explicitly record
`relational_context=false` and `semantic_evidence=false`. Its 7/10 result therefore
cannot validate or invalidate the strengthened relational path.

That smoke exposed defects now repaired in the working tree: model-authored paths
could be labelled as pre-existing evidence; persistent-state advisory output could
duplicate repository context; GT had no shared per-task evidence budget; action
and call ordinals were conflated; and the workflow could silently omit the
strengthened profile. P0-P2 below means **implemented and locally testable**, not
benchmark-proven. Exact-commit provider-free and outcome proof remain P3.

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
| Benchmark configuration was hardcoded/self-attested. | Caller-owned treatment JSON plus a fail-closed manifest/runtime audit. | Implemented: source SHA/model/step budget are caller-derived and the manifest is audited per task. |
| Model-authored repository facts gained false authority. | Bind every claim to path origin, origin revision, authority, and materiality; unsafe origins are controller-only. | Implemented. |
| GT payload accumulated across long tasks. | One shared discretionary-evidence budget with a protected critical reserve; preserve the mandatory bounded PES lifecycle frame. | Implemented: treatment-configured 4,096 total / 512 critical-reserve tokens for discretionary evidence. |
| Difficult-task history became huge. | Bound GT additions and report when pressure is distinct assistant reasoning that GT may not delete. | Implemented truthfully; model over-exploration remains an outcome risk. |

## Completed build work

- [x] Preserve `PersistentExecutionStateEngine`; replace the final profile's generative bootstrap
  with one deterministic catalog-selection event and zero selection provider calls.
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
- [x] Require claim-complete origin/authority/materiality metadata and reject missing,
  model-authored, generated, and unknown origins from provider-visible shared contributions.
- [x] Add one cumulative task evidence budget with a protected critical reserve.
- [x] Separate selected, processed, executed, returned, and cancelled action counters and audit
  their conservation equations.
- [x] Use completed-action ordinals for non-prediction and lifecycle accounting.
- [x] Configure `central_relational_v2` from a typed descriptor and fail closed on profile/runtime
  mismatch.
- [x] Build and verify a caller-owned benchmark manifest before provider execution; remove the
  workflow's hand-maintained feature list and duplicate fixed step limit.
- [x] Require one common benchmark-manifest hash across the complete task set and derive the full
  selected-task timeout map without fixed task IDs or timeout values.
- [x] Compare every treatment-controlled runtime argument with the effective agent value; do not
  accept a hash that merely echoes an unused descriptor.

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

- [x] Finish broad local tests and static/type checks on the final working tree: 1,880 tests
  collected; 1,875 runnable tests pass in one complete final-tree run, with five expected
  platform/asset skips. The provider-free readiness audit reports `READY`; changed-file Ruff,
  bytecode compilation, workflow YAML parsing, and `git diff --check` pass.
- [x] Review the final diff for stale zero-bootstrap/replacement-census behavior and duplicate
  provider surfaces.
- [x] Wire independent runner observations for task order, tool/hook envelopes, hardware, retry,
  timeout, embedding, and token accounting into the frozen TB2 `repair20-v1` task workflow. The
  workflow now creates source-owned documents after live budget/asset setup, composes them through
  the fixed-source builder, exports a runner-private `GT_RUNTIME_OBSERVATION_PATH`, and uploads
  the observation only after the task finishes. A copied declaration remains invalid.
- [x] Freeze the implementation as exact commit `15bc9424cec8c9bfdf34db58c66e645ec92f8724`,
  including the post-smoke provenance, budget, lifecycle, treatment-identity, merge-manifest,
  hosted-coverage, and receipt-completeness repairs.
- [x] Run the exact runtime commit through the source-built Linux provider-free workflow with
  the current indexer and pinned ONNX asset. Run `32153590102` passed every job step and its
  artifact records `provider_calls: 0`, `dataset_verified: true`, dataset commit
  `2fd12b88aafdd04a52c298e3940bcb189f9766d6`, and 89 verified tasks. This proves integration
  integrity, not uplift.
- [x] Perform a post-proof deep audit. It found and repaired two proof gaps: hosted certification
  now directly tests/lints every changed Python release path, and the uploaded receipt retains
  the actual dataset language-contract JSON. No missing P0-P2 implementation path remains.
- [ ] Execute the current engine against the 15 selected historical trajectories/workspaces where
  those legal task artifacts can be restored. The current archive has receipts and replay blobs but
  no legal source workspaces, so those rows are currently unavailable; never turn the frozen
  counterfactual predictions into fake replay measurements.
- [x] Implement the final deterministic-selection, replay-v3, intervention-chain-v2, retrieval
  rank-consumption, and four-report merge contract. The candidate now has one deterministic
  selection event with zero selection/bootstrap provider calls; all visible delivery surfaces,
  exact request envelopes, action joins, replay hashes, and causal limitations are auditable.
- [x] Freeze the prediction artifact as the prediction-only follow-up commit
  `docs/benchmarks/GT_FINAL_20_TASK_OUTCOME_PREDICTION_2026-08-19_V2.json`. The verifier rejects
  any runtime or harness change after the implementation commit; only this artifact may be added.
- [ ] Run the exact source-built Linux provider-free workflow for the implementation commit,
  then verify the prediction-only commit. Local Windows execution is not authoritative because
  the checked-in index binary can be stale.
- [ ] Run the final frozen 20-task comparison: strengthened GT live, with the frozen GT-off
  baseline and previous GT result joined offline. A new GT-off arm is forbidden by the current
  benchmark contract. Do not run a paid smoke before the exact source-built proof passes.
- [ ] Publish the four separate reports: integrity, solve, efficiency, and intervention. Preserve
  the full denominator and classify counterfactual causality as unknown unless a matched replay or
  mechanism ablation supports it.

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

The implementation is frozen pending the source-built Linux proof. Run that proof, then verify the
prediction-only commit and only afterward execute the frozen `repair20-v1` comparison. The GT-off
baseline and previous GT result are offline reference artifacts, not new run arms. GitNexus is not
a run arm. Provider-free proof establishes integrity only; the four benchmark reports establish
solve, efficiency, and intervention results separately.
