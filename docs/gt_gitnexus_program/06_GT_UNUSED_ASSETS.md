# 06 — Underused GT assets and historical failure lessons

## Evidence rule

An asset is “underused” only when current source or historical product code shows that GT can compute it while workflow `32163376177` does not prove an equivalent provider-visible composition. Historical documents recovered from `D:\Groundtruth` Git objects are experiment evidence, not current architecture authority. No capability is credited merely because a PRD names it.

Confidence is **high** where both code and live receipts establish the gap, **moderate** where code exists but the external/full-product dependency prevents an end-to-end proof, and **unknown** where only an aspiration is documented.

## Existing asset → lost information → useful composition

| Existing asset | Information currently lost at the benchmark boundary | New deterministic composition | Failure class addressed | Confidence |
|---|---|---|---|---|
| LSP/compiler-resolved definitions, references, signatures, and types | Relational-v2 does not bridge every full semantic field; no live central receipt proves LSP output | `target symbol + resolved signature/type + concrete callers + diagnostics`, current-revision bound | wrong convention, wrong receiver/shape, incomplete coupled fix | Moderate |
| Full caller/callee graph | Low-level directed edges are available, but only three caller-contract applications occurred and no full process answer is receipted | `changed symbol → affected callers → externally visible entry points → exact tests` | missed coupled change, incomplete fix | High |
| Certified tests/assertions/routes | They help structural ranking but are not consistently composed with the active edit and validation debt | `active change → covering assertion/route → cheapest exact check → unresolved obligation` | wrong test, over-testing, incomplete validation | High |
| Runtime KB/runtime introspection | Historical Phase2B isolated it to validation and produced zero corrections over 185 cases; current central run shows no contribution | Use only when a source/runtime mismatch exists: `resolved symbol + observed runtime member/type + contradiction` | dynamic API/runtime mismatch | Moderate |
| Change surface and signature delta | Hundreds of fires remain mostly controller/accounting events; they do not automatically create a coupled-change answer | `diff symbol + signature delta + certified reverse impact + touched/untouched callers` | incomplete fix, hidden caller breakage | High |
| Obligations and task constraints | Obligations fired on every task, but negative constraints and completion predicates can remain private or too weak | `instruction constraint + changed-file set + current deliverables/checks → contradiction/completion certificate` | sanitize scope expansion; video budget exhaustion | High |
| Persistent revision/fingerprint state | Strong freshness/accounting exists, but current baseline comparisons still lack same-state counterfactuals | replay-safe decision snapshot with pre-GT provider view, source revision, observed history, and treatment delta | causal ambiguity/model churn | High |
| Hybrid retrieval's five support families | Ranking can select a source-backed but task-irrelevant relation; support strength is not task relevance | require both semantic support and an instruction/change/diagnostic/obligation linkage | wrong retrieval and tunnel vision | High |
| Complete source-span packing | Often gives local target body but loses multi-edge reasoning needed around it | compact “implementation + callers + tests + constraint” relational answer under one budget | wrong localization plus incomplete fix | High |
| Graph rebases and source capture | Freshness works, but newly created source activation/value is mostly lifecycle proof | on activation, compile new source's entry points, obligations, and required checks in the first next request | source-less-to-source dynamic tasks | High |
| Full MCP/product tools | Mini-SWE/DeepSWE do not call them; separate tool invocation would add reasoning/provider work | reuse their deterministic backend functions inside the host contribution compiler, not as agent-selected tools | broad semantic coverage without extra turns | Moderate |
| Replay capture | Treatment config explicitly disabled it | bounded, legal-source decision replay around first divergence | attribution, intervention-policy tuning | High |

## The missing composition layer

GT already has more raw mechanics than the latest solve result suggests. The important absent object is a **certified change/process obligation**, for example:

```text
instruction anchor
  + current target definition/signature
  + source/runtime-resolved types
  + reverse callers / route or entry point
  + current diff
  + covering tests and observed results
  + explicit task constraint
  = bounded required-coupled-change or completion record
```

This record must preserve uncertainty:

- unresolved import or receiver → `UNKNOWN`, not no caller;
- incomplete index → absence is not nonexistence;
- co-change-only relation → ranking support, never an obligation;
- graph edge alone → advisory dependency, not mandatory edit;
- stale revision → no certified current evidence.

The central host can inject such a record into the ordinary next provider request. Making it another optional agent tool would repeat the historical extra-turn problem.

## Historical evidence index

The requested historical files are recoverable from the `D:\Groundtruth` repository's Git object database:

| Historical artifact | Git blob | Use in this audit |
|---|---|---|
| `PROGRESS.md` | `eb88abe…` | v4–v15 experiment chronology |
| `PHASE2B_RESULTS.md` | `e07a4846…` | 300-task outcome comparisons |
| `PHASE2B_FINAL_REPORT.md` | `0b7c86bf…` | runtime-KB and bounded-feedback findings |
| `DIAGNOSTIC_ANALYSIS.md` | `189f8eb…` | validation adoption and context-utilization defects |
| `autoresearch.md` | `d7744d0…` | search-loop design/history |
| `autoresearch_results.tsv` | `0f9ef336…` | iteration guard-test results, not solve results |
| `PRD.md` | `84947736…` | intended full-product capability set |
| `ENGINEERING_PERSPECTIVE.md` | `24794d5…` | critical data-path and observability failures |
| `CEO_PERSPECTIVE.md` | `27e8fb3…` | product/benchmark interpretation |
| `PLAN_REVIEW.md` | `d77e9fd…` | historical plan criticism |
| `audit_report.md` | `708b9e3…` | LSP/integration and Windows timeout findings |
| `TODOS.md` | `ff179f14…` | unresolved historical work |

Abbreviated hashes identify local Git blobs; use `git -C D:\Groundtruth cat-file -p <blob>` to reproduce the source. These artifacts must not be treated as current-runtime proof.

## Historical failure root-cause audit

### Active-tool / over-exploration regression — **PARTIALLY PRESENT**

Historical v4.2 scored 105/300 against 113/300 baseline, with 20 gains and 28 losses. Tool use was most promising at roughly 1–5 calls and harmful on heavy 16+ call trajectories; outline/context operations sometimes duplicated ordinary `cat`/`head` exploration. The current host no longer requires an optional intelligence tool call, which fixes the delivery architecture. However, `e423c87` returned broad root searches on extract, tensor, and video, and video exhausted 100 steps after a viable output. The mechanism has changed, but added decision cycles and insufficient convergence remain.

### Validation-heavy regression — **PARTIALLY PRESENT**

Historical v4.1 scored 73/300 against 76/300. Tool/check wording was widely adopted but added validation without reliable value. Current validation is mechanically typed and bounded, which is a substantial repair. Yet the latest run still recorded resource failures on LLM batching, prove-plus-comm, qemu, and write-compressor; sanitize expanded into unrelated dependency/test repair. “Run more validation” remains unsafe unless each check discharges a named current obligation.

### v6 autocorrection false positives — **ROOT CAUSE NOT PRESENT in the current relational path**

Historical v6 scored 106 versus 113; 53 of 54 corrections were false positives. Current central policy rejects ambiguous/unresolved/external/global-fallback relations, does not treat unknown as false, and disallows arbitrary command rewrite. No v6-style fuzzy name correction appears in the current run. The broader lesson—high-confidence mechanical evidence can still be irrelevant—remains visible on sanitize.

### Safe runtime-KB with zero useful corrections — **ASSET STILL UNUSED**

Historical Phase2B processed 185 cases, produced zero corrections, preserved predictions, and caused zero false positives. This proved safety, not value. The current central receipts still do not show runtime-KB intervention. Do not resurrect it as a generic advice stream; activate it only for a certified source/runtime contradiction.

### Bounded test feedback positive result — **PRINCIPLE PRESENT; CURRENT EFFECT UNKNOWN**

Historical bounded test feedback reached 116/300 versus 113/300, the first positive aggregate delta in seven experiment generations. Current GT owns declared checks, one validation classifier, observed execution, covering-red relations, completion state, and submit holds. Those mechanics implement the principle, but workflow `32163376177` does not isolate their effect. A targeted ablation is still required.

### Context-utilization / grounding gap — **PARTIALLY PRESENT**

The historical diagnostic's naive substring “utilization” metric was not a valid measure of model use; `agent_fixed_after_validation=0` and some repositories indexed zero files/symbols. Current exact request/provider hashes, changed indices, claim IDs, and revisions repair grounding and exposure observability. They do not prove semantic use. Sanitize demonstrates the residual problem: a fact can be grounded and delivered yet irrelevant.

### Absence from incomplete index treated as false — **CORE PRINCIPLE REPAIRED**

Historical AST default-deny behavior generated false positives. Current graph gates fail closed, incomplete or stale graphs cannot certify evidence, ambiguity abstains, and co-change cannot create obligations. No latest-run evidence shows an absence-based contradiction. Preserve this invariant in every new composition.

### Autoresearch “improvement” metric confusion — **ACCOUNTING RISK REMAINS**

The historical TSV's improved rows meant local guard tests such as 564/564 or 602/602 passed, not that benchmark solves improved. The latest run's extensive mechanism counts create the same temptation. “16/17 naturally fired,” “3,006 PES uses,” or “all unit tests pass” are integrity/activity results, not solve uplift.

### Critical data-path fragility — **PARTIALLY PRESENT, actively repaired**

The historical engineering perspective identified dual-write JSONL corruption, ephemeral monkey patches, weak tests on critical paths, and silent accounting corruption. Current typed receipts and authoritative delivery audit are much stronger. Nevertheless, the latest release exposed exactly the modern version of this class: terminal effects without consumption, duplicate claim IDs, frontier rendering mismatch, and contribution token mismatch. Current HEAD has focused repairs; live exact-commit validation remains mandatory.

## Tight deterministic feedback loops and test seams

### 1. Effect conservation loop

At every action and at terminal finalization:

```text
produced effect -> one registered consumer -> one applied/audit-only disposition
                -> one effect-ledger foreign key -> task aggregate conservation
```

Test an effect produced on the final submit action. Release must fail on zero or multiple dispositions.

### 2. Provider claim freshness loop

Keep stable semantic fact identity for deduplication, but create a fresh delivery claim when its value/revision changes. Test unchanged, changed, reverted, and compaction-retained cases against exact provider hashes.

### 3. Substrate-versus-frontier loop

Report graph build/schema/revision, candidate frontier, rendered frontier, and provider delivery as four separate transitions. A healthy graph plus missing render must never be called “repository intelligence unavailable.”

### 4. Relevance loop

For every selected structural row, require a deterministic link to one of:

- explicit instruction anchor;
- current diagnostic;
- active changed symbol/path;
- required deliverable/check;
- certified unresolved obligation.

Add a negative fixture proving the sanitize instruction does not select the histogram relation.

### 5. Safe convergence loop

Classify direct known grader-artifact access separately from generic root search. Generic root search may be returned only with a typed `STALLED`, `CONTRADICTED`, or `BUDGET_RISK` witness. Record whether the return **replaced** an operation or added another provider call.

### 6. Change-obligation loop

After each source rebase:

```text
changed definitions/signatures
 -> certified reverse impact
 -> unresolved affected callers/routes/tests
 -> bounded provider frame
 -> observed edit/check
 -> obligation discharged or refreshed
```

Test ambiguity, deleted source, newly authored source, multiple callers, and co-change-only edges.

### 7. Completion loop

After a material change or validation, compile deliverable presence, declared checks, observed results, and unresolved predicates once per revision. At budget risk, surface only the cheapest unresolved proof. Repeated expensive generation after a passing candidate requires a new contradiction.

### 8. Decision-replay loop

Enable legal-source replay capture for forensic runs. Freeze the exact pre-GT provider state and compare no contribution, current composition, and one-mechanism ablation. Record first action divergence and resource replacement. Never include verifier-only artifacts.

## Highest-value recompositions

1. **Certified change obligation:** current diff + signature/type + callers/routes + covering tests. This attacks incomplete-fix and wrong-approach failures without another provider call.
2. **Task-relevance certificate:** semantic support plus an explicit instruction/change/diagnostic/obligation link. This reduces sanitize-like negative salience while preserving aggressive delivery.
3. **Budgeted completion proof:** current deliverables + observed checks + one unresolved predicate. This attacks video-like budget exhaustion and can reduce calls/tokens.

## Conclusion

GT's underperformance is not explained by a total lack of program intelligence. It is explained by an incomplete conversion chain: rich low-level semantics are not consistently composed into task-specific process/change obligations, while delivery/activity accounting has been stronger than relevance and causality accounting. The next build should reuse the existing graph, types, revision state, validation classifier, and provider-boundary compiler to create higher-value relational answers—not add another advisory tool or another generic context stream.
