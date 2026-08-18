# GroundTruth P0-P2 Implementation Closeout

This closeout covers the product implementation boundary. Final runner parity, exact-commit Linux
proof, and outcome benchmarking are P3 and are not claimed here.

Date: 2026-08-18

Harness source examined: `73562e7ebbc4796548fe5dd8c029161107d14e6f` plus the
uncommitted P0-P2 working-tree changes documented here.

Full GroundTruth source examined: `04c3da7e55cc9f776d492aeee396682c52f84f08` in
`D:\Groundtruth`.

## Verdict

P0, P1, and P2 are implemented at the legal central-runtime boundary. The strengthened path now
projects certified semantic facts, bounded execution views, reverse impact, observed diagnostics,
and relevant checks in one zero-extra-turn provider contribution. It preserves the 17+1 product
identity and refuses external, ambiguous, unresolved, dynamic, stale, weak, or incompletely
proven resolution.

This is implementation plus frozen historical forensics/prediction, not an execution replay and
not solve-rate proof. The final matched benchmark remains deliberately last.

## P0: production-semantics inventory and projection

### What full GroundTruth can obtain

| Evidence | Full-product implementation | Durable representation | Central projection | Unknown policy |
|---|---|---|---|---|
| Definitions | `src/groundtruth/lsp/client.py:740`, `resolve.py:546` | Resolved graph edge target and method | Certified definitions/references/callers | No target selection when proof is absent |
| References | `lsp/edge_verifier.py:152`, `client.py:701` | Verified edges and confidence | Certified callers/references | Candidate-only edges stay rank-only |
| Signatures and return types | `resolve.py:1327-1566`, `index/graph_store.py:102` | Sanitized `nodes.signature` and `nodes.return_type` | Semantic definition and execution-step facts | Empty fields remain absent |
| Hover | `lsp/protocol.py:120`, `client.py:724` | Only sanitized signature/return type is persisted | Persisted fields only | Raw hover markdown is never invented or replayed |
| Diagnostics | `lsp/protocol.py:137`, `client.py:472,803` | Ephemeral LSP client cache | Concrete observed `path:line: message` diagnostics | Unanchored/free-form text is rejected |
| External resolution | `resolve.py:615-632` | `lsp_external`, confidence zero | Terminal `external` outcome, never a correction | Silence |
| Runtime introspection | `core/trust.py:35` | Runtime `TrustResult`, not GraphDB | Not projected unless observed in the task environment | Host-only introspection is not treated as task evidence |
| Builtin/stdlib identity | `delivery/name_policy.py:66,79`, `evidence/mismatch.py` | Dynamic language/runtime classification | Terminal builtin/stdlib origin fixtures | Silence |
| Imports/re-exports | Go graph resolver and `RE_EXPORTS` edges | Typed edge with provenance | Context and impact when exact/certified | Unverified re-export stays terminal |
| Receiver/type flow | Go resolver `assignments.go` and `resolver.go` | Resolution method plus `receiver_type` metadata | Directed call step with receiver/return type | Every uncertified hop is omitted |
| Properties | Go parser `properties` table | Kind, value, confidence, tier, method, verification, ID | Params, return shape, class fields, visibility, decorators | Missing provenance is not deliverable |
| Routes | Go relationship resolver | `HANDLES_ROUTE` plus `route=` metadata | Route entry point and route label | A graph root is labelled `graph_root`, not a framework entry |
| Implementations/overrides/tests/API consumers | Typed graph relations | Certified edges | Reverse impact with relation-specific labels | Weak edges do not create obligations |

The important boundary is explicit: central Mini-SWE builds its graph with the source-built Go
indexer. It does not launch the separate full-product LSP manager inside every benchmark task.
Therefore central can consume LSP-enriched fields when a graph legitimately contains them, but it
does not claim direct live-LSP coverage. Direct host runtime introspection would also be invalid for
container-only dependencies. Both cases abstain.

### Implemented data path

```text
task instruction + exact workspace source + observed execution
    -> source-built GraphDB and revision binding
    -> RepositoryEvidence
       definitions / references / callers / semantic properties / project checks
    -> HybridRepository
       exact spans + typed, provenance-bearing structural links
    -> RepositoryContextEngine
       semantic facts + execution views + impact + diagnostics + checks
    -> shared contribution compiler
    -> first eligible existing provider request (zero extra model turns)
    -> delivery and utilization receipts
```

Implementation points:

- `gt_engine/repository_intelligence.py`: reads persisted node return types, export/test flags,
  certified properties, definitions, references, and callers.
- `gt_engine/hybrid_repository.py`: preserves edge origin, outcome, candidate count, method,
  receiver type, route, node kinds, return types, and both endpoint content origins; missing
  provenance or endpoint origin is unknown.
- `gt_engine/semantic_evidence.py`: immutable definitions, properties, callers, references, and
  tests with stable semantic IDs.
- `gt_engine/repository_context.py`: one bounded semantic/execution/impact/diagnostic/check view.
- `eval/gt_central_agent.py`: obtains exact changed symbols from signature-delta receipts, compiles
  the contribution before the provider call, and receipts exact visible facts.

Provider-visible semantic rows and graph links must bind to task-start repository documents at
both endpoints. Model-authored, generated, deliverable, external-runtime, and origin-unknown rows
remain controller-only. Rejected CALLS and non-CALLS impact edges are counted in the projection
receipt. A correct all-abstention trajectory is release-valid when every opportunity is accounted;
the gate never forces text merely to manufacture a delivery.

## P1: destructive-correction closure and historical forensics

### Regression closure

`tests/test_destructive_correction_regressions.py` freezes the destructive classes:

- `Counter -> Count`: builtin;
- `OSError -> Error`: stdlib;
- `Engine -> engines`: third-party/external;
- `Node -> Code`: ambiguous global candidates;
- framework classes;
- dynamic modules;
- unverified re-exports;
- unresolved receivers;
- incomplete indexes; and
- low-confidence receiver binding.

Every case must produce no corrective text. Additional tests prove same-file typed calls remain
available, certified route metadata survives the source indexer, and certified semantic properties
retain provenance.

### Frozen counterfactual set

The forensic set uses run `31355487270` for the strict 89-task rows and archived full-product
evidence for the fifth gain. This is post-hoc failure analysis, not a task-specific runtime rule.
The current `RepositoryContextEngine` was not executed against restored historical workspaces for
these 15 rows; the table freezes predictions that must not be described as measured replay results.

| Class | Task | Historical decision/failure | Smallest strengthened response | Frozen expected effect | Confidence |
|---|---|---|---|---|---|
| Negative | `extract-elf` | Submitted a flat ELF map after self-checking only the provided binary; alternate hidden fixture decided the score | No response; no legal repository fact resolves the hidden format convention | No effect | High |
| Negative | `regex-chess` | Reached 100 steps while repeated generated-file/signature context echoed its own work | Abstain from self-echo; only pre-existing certified dependency facts may appear | Reduce interference/turn pressure; solve recovery unproven | Moderate |
| Negative | `torch-tensor-parallelism` | Submitted a locally verified implementation but failed the official behavior | Exact signatures, receiver-resolved calls, and impacted checks only if present before the decision | Possible incomplete-fix prevention; otherwise no effect | Low |
| Negative | `video-processing` | Submitted a video heuristic that did not generalize | No graph response beyond concrete observed diagnostics/checks | No effect expected; this is behavioral synthesis | High |
| Negative | `winning-avg-corewars` | Consumed the 100-step budget iterating warrior constants | One pre-existing opponent/process surface, then dedupe; never repeat frontier facts | Fewer exploration steps, but solve recovery uncertain | Moderate |
| Both fail | `caffe-cifar-10` | Deadline reached during installation/training repair | Required deliverables and declared checks only; graph abstains when source-less | No semantic-graph effect | High |
| Both fail | `db-wal-recovery` | Submitted eleven reconstructed records that did not match the hidden data | Concrete observed SQLite diagnostics only | No effect expected; hidden values are unavailable | High |
| Both fail | `gpt2-codegolf` | Knew the 5 KB bound but spent the deadline implementing/golfing | Do not repeat size/check facts already represented | No effect expected; synthesis bottleneck | High |
| Both fail | `model-extraction-relu-logits` | Deadline reached during numerical extraction experiments | `forward.py` signature once, if not already read | Little/no effect; the agent opened the API first | High |
| Both fail | `train-fasttext` | Reached 100 steps tuning training experiments | Deliverable/check state only | No effect expected; optimization bottleneck | High |
| Gain | `count-dataset-tokens` | Resolved with a one-node/no-edge graph | Usually abstain; preserve task semantics and observations | Preserve gain, no causal GT claim | High |
| Gain | `largest-eigenval` | Resolved after reading `eigen.py` and `eval.py`; two frontier deliveries occurred | Exact function signature and certified check/caller once | Preserve gain with no extra turn | Moderate |
| Gain | `protein-assembly` | Resolved with no graph nodes | Abstain from repository context | Preserve gain | High |
| Gain | `torch-pipeline-parallelism` | Resolved in the strict run with a three-node/four-edge graph | Exact pipeline call/check surface once | Preserve gain; no causal attribution | Moderate |
| Gain | `kozea__weasyprint-2300` | One of two runs localized from `flex.py` to `block.py` after cross-file caller evidence | `block.py` caller set with exact call counts/paths before edit | Plausible positive localization effect; non-deterministic historically | Moderate |

The machine-readable prediction is frozen in
`docs/benchmarks/GT_P0_P2_FROZEN_REPLAY_PREDICTIONS_2026-08-17.json`.

## P2: certified process and impact coverage

| Requirement | Implementation | Safety boundary |
|---|---|---|
| Route/framework entry classification | `RepositoryContextEngine._execution_views` | Only certified `HANDLES_ROUTE` becomes `route_entry`; ordinary roots remain `graph_root` |
| Receiver/return propagation | `StructuralLink` and `DirectedExecutionStep` | Metadata is displayed only after edge certification; no inferred extra hop |
| Diff-to-symbol binding | `CentralFeatureRuntime.changed_symbols_for_action` | Reads exact action/revision `signature_delta`; no Bash or fuzzy name parsing |
| Impacted checks | `RepositoryContextEngine._validation` | Prefer a path-specific discovered check, otherwise the first deterministic project check; represented checks dedupe |
| Diagnostics | `RepositoryContextEngine._diagnostics` | Concrete anchored observed diagnostics only |
| API/re-export/test/route/override impact | Relation-specific reverse impact | Only certified exact program edges |
| Exploration-use instrumentation | `SemanticUtilizationTracker` | Separates use without prior exploration, accompanied, followed, and unmatched; it makes no counterfactual replacement claim |
| Zero-turn delivery | Existing contribution compiler/provider boundary | No model-selected GT query and no extra executor call |

## Verification completed on the working tree

- 1,848 Python tests collected. The six-shard run covered the prior 1,847-test tree; all 1,842
  runnable tests passed with five expected skips. The added caller/reference endpoint-origin
  regression then passed in the focused post-review run (1,843 runnable passes total).
- Expected skips cover an unprovisioned pinned ONNX integration asset, the inverse graph smoke,
  one POSIX-only check, and two Windows privilege/mode checks.
- Changed-file Ruff, Python bytecode compilation, and `git diff --check` pass.
- Linux Codespace `go test ./...` and a source build of `cmd/gt-index` pass, including ambiguous
  re-export regression tests.
- `tests/test_gt_engine.py` fell from about 227 seconds to 145 seconds by building one immutable
  graph template and copying it per test. The remaining dominant 41–53 seconds is the legacy
  `groundtruth.pretask.v1r_brief` import/execution path. The exact-source integrity scan is 21
  seconds cold and cached by source fingerprint thereafter; its full module is 28.5 seconds.

## Bugs found and corrected during final review

- failed source refresh previously restored stale graph evidence;
- dense retrieval was skipped after sparse/graph support despite the five-channel contract;
- ambiguous same-file definitions were stamped `exact`;
- ambiguous re-export targets were stamped verified with candidate count one;
- semantic caller/reference origin filtering did not validate the correct source and target fields;
- utilization telemetry claimed context replaced exploration without causal evidence;
- the strengthened release gate could pass a legacy/missing profile;
- runtime parity could echo a declared execution contract; and
- a Go callback signature change was not buildable before Linux verification.

## What remains after P0-P2

Only P3 proof and release work remains. The reusable source-owned observation builder and CLI are
implemented and wired into the frozen TB2 `repair20-v1` task runner. The remaining work is proof,
historical replay availability, prediction freeze, and the final matched outcome run:

1. run the hosted provider-free workflow for frozen commit
   `4f37f1f4afc1a7a6c7a2fe8981906567c7537800`;
2. replay the current engine on the 15 selected historical workspaces/trajectories where legal
   archived task state is actually available, marking unavailable rows honestly;
3. freeze/update the final 20-task prediction artifact without looking at new outcomes;
4. run the final frozen comparison against the baseline and previous small GT run; and
5. report outcomes and efficiency with the full denominator.

No claim of parity, superiority, solve lift, or efficiency lift is valid before step 5 completes.
