# 03 — GroundTruth feature and capability ledger

## Reading this ledger

Statuses refer first to live workflow `32163376177` at `e423c87`. When current source `18f95fb` differs, the distinction is explicit. The categories are:

- **WORKING:** the latest run has a valid lifecycle and observable product use.
- **PARTIALLY WORKING:** useful path exists, but a receipt, relevance, coverage, or lifecycle defect remains.
- **IMPLEMENTED BUT UNUSED:** code/product facility exists but the current benchmark adapter did not exercise it.
- **UNAVAILABLE ON SOME TASKS:** legitimate applicability or backend coverage varies.
- **BROKEN:** a required live contract failed.
- **UNKNOWN:** implementation/usefulness cannot be established from the available source and receipts.

Working means the mechanism ran correctly; it does not by itself mean it caused a solve.

## Repository-intelligence ledger

| Capability | Primary implementation | Live status | Benchmark-exercised evidence and failure mode |
|---|---|---|---|
| Repository transfer/mirror | [repository_mirror.py](../../gt_engine/repository_mirror.py) | WORKING | 20/20 source-backed checkouts transferred; bounded failures fail closed |
| Graph indexing | [indexer.py](../../gt_engine/indexer.py), [vendor/gt-index-src](../../vendor/gt-index-src) | WORKING | 20/20 valid schemas with nonzero nodes/edges; incremental refresh occurred |
| AST/parser substrate | Go indexer and repository-intelligence bridge | WORKING | Supplies graph entities across the run's languages; exact per-language semantic depth varies |
| LSP/compiler-resolved semantics | Full GT/product code and external package integration | IMPLEMENTED BUT UNUSED | No central receipt proves a live LSP session or delivery; relational-v2 design explicitly does not bridge every LSP/compiler field |
| Symbols/definitions | indexer; [repository_context.py](../../gt_engine/repository_context.py) | WORKING | Target anchors/definitions delivered, including `largest-eigenval` call 1 |
| References | graph/context engine | PARTIALLY WORKING | Graph relations exist; no universal proof that all reference kinds reach the provider |
| Imports/exports/re-exports | graph/context engine | PARTIALLY WORKING | Re-export composition exists; language/framework coverage and live fire counts are not separately certified |
| Signatures | graph/context engine; signature feature | WORKING | `signature_delta` fired six times on four tasks; correctness is source-bound |
| Resolved types | full semantic substrate | IMPLEMENTED BUT UNUSED | Not proven in the benchmark provider view; important on tensor orientation/receiver cases |
| Callers/callees | graph; relational context | WORKING, bounded | `caller_contract` and `def_partition` each applied three times; ambiguous/global-fallback edges abstain |
| Inheritance/overrides/implementations | relational context | PARTIALLY WORKING | Supported by composition; latest run does not isolate coverage or solve effect |
| Dependencies | graph/context engine | PARTIALLY WORKING | File/symbol relations exist; no process-level dependency answer is certified |
| Routes/API relationships | relational context | PARTIALLY WORKING | Routes are supported; no distinct live route mechanism count |
| Tests/assertions | graph/retrieval structure | PARTIALLY WORKING | Certified test/assertion edges can rank evidence, but active-change-to-test obligation composition is incomplete |
| Runtime KB/introspection | full GT historical product | IMPLEMENTED BUT UNUSED | Historical Phase2B processed 185 cases and made zero corrections; no central-run contribution |
| Change surface | `GT_CHANGE_SURFACE`, graph refresh | WORKING | 290 natural fires; revision/rebase lifecycle active |
| Obligations | central runtime/PES/task semantics | WORKING mechanically; value PARTIAL | Fired on 20/20; some remain private or do not create a decisive next action |
| Contradictions/contracts | convergence/PES/feature runtime | PARTIALLY WORKING | Certified contradictions may act; terminal submit effects failed conservation on three tasks |
| Existing patterns/new-file precedent | `newfile_precedent`, hybrid retrieval | WORKING | Five natural fires; no causal isolation |
| Full repository graph | repository intelligence | WORKING | Graph substrate passed all tasks |
| Material repository frontier | central agent/context compiler | BROKEN in run; repaired at HEAD | `material_frontier_not_delivered` on largest and portfolio; source repair awaits live proof |
| Process/flow representation | no complete central implementation identified | UNKNOWN / MISSING COMPOSITION | Low-level edges exist, but no receipt shows stable entry-point-to-process composition |
| Control/data flow, PDG, taint | no current central benchmark proof | UNKNOWN | Do not infer these from a generic graph edge |
| Impact | relational context and full product tools | PARTIALLY WORKING | Reverse impact exists; higher-value change obligation/test composition remains underused |

## Retrieval ledger

| Capability | Status | Evidence |
|---|---|---|
| Exact path/symbol | WORKING | Shared `HybridRetriever`; exact support can authorize delivery |
| Lexical overlap | WORKING | Independent channel; common path tokens cannot certify delivery |
| BM25/FTS-like sparse retrieval | WORKING | Shared channel and RRF contribution |
| Dense retrieval | WORKING in latest run | Pinned Snowflake ONNX backend available on 20/20; local inference, no provider call |
| Certified graph structural retrieval | WORKING | Calls/assertions/closure can certify; co-change is rank-only |
| Five-channel reciprocal-rank fusion | WORKING mechanically | One implementation shared by adapters; `k=60`, max eight spans |
| Relevance selection | PARTIALLY WORKING | `sanitize-git-repo` call 1 received an unrelated histogram relation despite a secrets-removal task |
| Complete-span packing/budgeting | PARTIALLY WORKING | Bounded packing works; ten run rows had task-usage serialization mismatch |
| Semantic deduplication | PARTIALLY WORKING | Unchanged facts dedupe; changed decisive facts caused duplicate-claim failures on two tasks |
| Preemptive retrieval delivery | WORKING when certified | Provider-boundary delivery adds no model/tool call; aggregate surface counts show use, though task receipts often expose composed repository context rather than a separately named preemptive surface |

## Execution and integration ledger

| Capability | Status in run | Evidence / qualification |
|---|---|---|
| Preflight typed action projection | WORKING mechanically | 959 PES preflights; one immutable validation classification per action |
| `ASSISTIVE_SAFE` action return | PARTIALLY WORKING | Narrow direct-path defense is valid; broad `/` searches were also returned on extract, tensor, and video without proven allowed convergence state |
| Environment execution observation | WORKING | Observed-execution deliveries and action-cycle receipts |
| Postflight | PARTIALLY WORKING | 913 commits, but terminal effects were not consumed on three tasks |
| Incremental graph rebase | WORKING | 194 rebases; no reported stale-final-graph failure |
| Evidence compilation | PARTIALLY WORKING | Exact accounting is strong, but frontier rendering and task-token usage failed on some rows |
| Evidence ranking | PARTIALLY WORKING | Mechanically bounded; relevance miss on sanitize demonstrates unresolved task-fit risk |
| Provider delivery | PARTIALLY WORKING | Valid on 18/20; duplicate-claim certificates on count and LLM batching |
| Receipt certification | BROKEN at release level | 13 task release rows failed even though most payload transport succeeded |
| Persistent state bootstrap | WORKING | Exactly 20 bootstraps; bootstrap separated from executor accounting |
| Persistent state repeated lifecycle | WORKING | 3,006 uses, 920 compiles, 959 preflights, 913 postflights, 194 rebases |
| Fingerprints/intervention accounting | WORKING | Control/final provider hashes, model identities, source revisions; fingerprints improve attribution but do not excuse a lost solve |
| Validation classifier | WORKING | Shared typed classification; 71 check actions across eight tasks |
| Submit gate/readiness | PARTIALLY WORKING | 39 holds; final effects on three tasks missed terminal consumption |
| Completion controller | PARTIALLY WORKING | One evaluation and two probes across 20 tasks; `video-processing` still exhausted 100 steps without submission |
| Progress/recap | WORKING mechanically | 105 recap receipts, no fallback; effect on convergence not established |
| Context compaction/compiler | WORKING mechanically | Exact fact dispositions/hashes; provider view still grew uncached input overall |
| Autocorrection | Historical aggressive form retired | Current policy rejects ambiguity and disallows arbitrary rewrite; no v6 fuzzy-correction behavior observed |
| Test feedback | PARTIALLY WORKING | Bounded declared/observed checks exist; latest run does not isolate causal benefit |
| Replay capture | IMPLEMENTED BUT UNUSED in run | Treatment config records `enable_replay_capture=false` |
| MCP/editor hooks | IMPLEMENTED BUT UNUSED by Mini-SWE | Full-product surface is not called by this scaffold |

## Natural legacy-feature lifecycle

The live lifecycle report establishes 16/17 naturally triggered legacy paths:

| Feature | Natural live evidence | Status |
|---|---:|---|
| `caller_contract` | 3 eligible / 3 applied | WORKING |
| `covering_red` | 1 | WORKING |
| `def_partition` | 3 | WORKING |
| `localization` | 36 | WORKING mechanically |
| `newfile_precedent` | 5 | WORKING mechanically |
| `obligations` | all 20 tasks | WORKING mechanically; usefulness not implied |
| `recovery` | 0 natural; forced-only path proof | IMPLEMENTED BUT NATURALLY UNUSED |
| `signature_delta` | 6 on largest, pipeline, tensor, video | WORKING |
| `syntax_result` | 145 | WORKING |
| `GT_CHANGE_SURFACE` | 290 | WORKING |
| `GT_EDIT_CHECK` | 24; 2 provider deliveries | WORKING, selectively visible |
| `GT_HYPOTHESIS` | 1 | WORKING mechanically |
| `GT_LOC_RESLOT` | 36 | WORKING mechanically |
| `GT_PATCH_DELTA` | 202 | WORKING |
| `submit_refusal` | produced, three terminal effects unconsumed | BROKEN in run terminal lifecycle |
| `GT_CERT_DELIVERY` | produced, three terminal effects unconsumed | BROKEN in run terminal lifecycle |
| `GT_SS_SUBMIT_RED` | produced, three terminal effects unconsumed | BROKEN in run terminal lifecycle |

The last three are not intrinsically broken algorithms; their run failure was a shared terminal consumption/accountability seam. Current HEAD repairs that seam, pending exact-commit validation.

## Efficiency status

On common-solved tasks, GT-on used six fewer provider calls and 5,001,412 fewer total tokens, but 304,712 more uncached input tokens, 500,124 more output tokens, and $0.166436906 more normalized cost. Across the full profile, calls increased by 112 and uncached input by 621,801 while total tokens fell by 4,635,371. Per-task resource gates failed on LLM batching, prove-plus-comm, qemu, and write-compressor.

Therefore context reuse/cache volume is working, but “less and better context” is not yet established at the expensive uncached boundary. **Confidence: high.**

## Ledger conclusion

The latest run is not a case where GT “did nothing.” Its graph, dense retriever, state lifecycle, change tracking, and most delivery paths worked extensively. The release failed because output conservation and certification were incomplete and because extensive activity did not translate into net solve gain. The most important capability gap is not another raw index: it is task-relevant composition of types, process paths, changed-symbol impact, required coupled edits, and their tests into a bounded intervention that replaces exploration.
