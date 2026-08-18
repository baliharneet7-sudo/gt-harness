# Next targeted ablation plan

## Status and purpose

This is a post-release-gate experiment plan, not authorization to dispatch work now.

The immediate experiment remains the strengthened GroundTruth treatment on the frozen `repair20-v1` denominator. Targeted mechanism ablations begin only after that same-20 run passes every integrity condition below. The experiments isolate why GT changes solves and efficiency; they do not weaken GT into an advisory-only system.

Confidence in the experimental design: **high**. Confidence that any named mechanism will improve outcomes: **unknown until measured**.

## 1. Non-negotiable control policy

All baseline controls are immutable, read-only artifacts. No new bare or GT-disabled job is part of this plan.

| Control | Authorized use | Identity |
|---|---|---|
| Frozen local TB2 baseline | Offline outcome/efficiency join only | `eval/frozen_baselines/tb2_miniswe_20260731.json`, SHA-256 `f75ebc8dd1eb25cb31cfa099b196d54346016b9f2de8e6f026e420cc213dd0bf` |
| Previous GT treatment | Offline historical comparison only | `artifacts/tb2_31778400203/merged/merged.json`, SHA-256 `bd3065e05a8cd22fdd139d17ceec3a30733100244f18c4008beed3f0bb307673` |
| Current strengthened GT | Live same-20 release-gate candidate, then the full-treatment reference for ablations | runtime commit `15bc9424cec8c9bfdf34db58c66e645ec92f8724`; profile `central_relational_v2` |

The frozen prediction at `docs/benchmarks/GT_FINAL_20_TASK_OUTCOME_PREDICTION_2026-08-18.json` remains immutable after outcomes are visible. It is a preregistered forecast, not an editable explanation.

Completion criterion: every run manifest identifies the two frozen control hashes and contains no dispatched control job.

## 2. Prerequisite: clean the same-20 release gate

Run exactly one strengthened GT treatment over the existing ordered `repair20-v1` task set. Join the result offline to both immutable controls. Do not expand the denominator and do not substitute tasks.

The gate passes only if all of the following are true:

1. Every supported source-backed task has revision-current repository intelligence, or the task fails the treatment gate.
2. Every retrieval channel expected by configuration is available; an inapplicable channel has an explicit, grounded abstention receipt.
3. Every provider-visible intervention has a valid delivery certificate, exact request hash, exact provider-view hash, in-range message index, first-eligible timing, and semantic support.
4. Persistent state is graph-first, bound to the actual source revision, repeatedly exercised when the trajectory permits, refreshed after material changes, and never serves a stale frame.
5. Postflight, graph rebase, completion, validation, and fingerprint receipts agree with the observed workspace state.
6. The product census reports the exact 17 registered feature mechanisms plus persistent execution state; natural feature fires remain reported separately.
7. No retrieval, provider-delivery, indexing, or state failure is silent.
8. Every task remains in the 20-task solve denominator, including integrity failures and legitimate graph abstentions.
9. Provider censoring is reported separately and never converted into a solve or treatment failure.
10. Integrity, solve, efficiency, and intervention results are four separate sections of the rerun report.

If any integrity condition fails, stop. Repair the identified integrity defect and repeat the same-20 treatment gate before starting an intelligence ablation. If a baseline-only solve is confirmed or highly likely to be GT-caused, perform its causal autopsy and minimum repair before ablation work.

Completion criterion: `15_20_TASK_RERUN_REPORT.md` records a clean integrity gate and a complete 20-task matched outcome table.

## 3. Shared ablation contract

Each ablation changes exactly one named mechanism. Everything else is frozen:

- the 20 task IDs, order, repository/task snapshots, task instructions, and verifier;
- model catalog identity, provider route, reasoning mode, temperature, sampling controls, and tool-choice policy;
- Mini-SWE scaffold, system prompt, task prompt, tool schemas, step budget, wall-clock budget, and retry/censoring policy;
- indexer source revision, pinned dense model revision/hash, retrieval channels, graph schema, and source-applicability rules;
- evidence budget, critical reserve, stable-core/delta budgets, bootstrap count, and resource accounting;
- preflight mode, validation classifier, postflight behavior, incremental graph refresh, stale-state fail-closed behavior, delivery audit, and central-integrity audit;
- the exact 17+1 product-mechanism identity and full 20-task denominator.

An ablation may suppress a selected mechanism's provider payload, but it must still compute a shadow receipt identifying what would have been selected. This preserves observability without pretending that private computation influenced the model. The ablation must not add an advisor call, planning call, explicit intelligence tool roundtrip, or extra provider call.

Before any paid dispatch, a provider-free differential test must prove:

1. the intended mechanism is the only changed treatment dimension;
2. all shared request bytes are identical before the targeted contribution is applied;
3. all unaffected task-state transitions and hashes remain identical under deterministic replay; and
4. the arm still passes central integrity and release auditing.

Completion criterion: the experiment manifest contains a one-field treatment delta and a provider-free proof receipt for that delta.

## 4. Ablation order

### A1 — Certified process composition

**Type:** Type 2, mechanism strengthening.

**Hypotheses tested:** H1, H4, and H5: precomposed process-level relationships replace exploration, and GT's weakness was composition rather than raw semantic coverage.

**Full treatment:** `RepositoryContextEngine` may compose certified path/symbol, directed call, route/API, inheritance, test, and process relationships into bounded relational evidence.

**Ablated treatment:** remove only the process grouping/projection layer. Preserve the same certified low-level candidate facts, retrieval channels, rankings, lifecycle, and total packing budget. Do not replace the removed process view with additional generic text.

**Primary evidence:** per-task solve flips, first changed action after a process delivery, searches and file reads replaced or added, provider calls, uncached input, total tokens, steps, and cost on common-solved tasks.

**Promotion signal:** the full arm creates at least one trajectory-supported positive flip or materially reduces search/file-read work without a confirmed/high-confidence negative flip attributable to process evidence.

**Rejection signal:** process text adds exploration, causes a confirmed/high-confidence negative intervention, or consumes budget while producing no observed localization, coupled-change, test-selection, or strategy effect.

### A2 — Changed-symbol → impact → test/obligation composition

**Type:** Type 3, new solve capability.

**Hypotheses tested:** H6 and H7: incomplete fixes and wrong approaches can be recovered by a deterministic coupled-change obligation assembled from existing GT evidence.

**Full treatment:** a certified changed symbol may compose reverse callers, implementation/inheritance relations, routes/APIs, and relevant tests into a bounded, provenance-bearing obligation or impact frame.

**Ablated treatment:** retain process context and individual certified relations, but prevent only their conversion into changed-symbol impact/test obligations. Ordinary validation debt, declared checks, deliverables, and exact task semantics remain active.

**Primary evidence:** missing-coupled-change repairs, test selection, validation timing, first action after delivery, positive/negative flips, and whether the same work required additional searches or reads in the ablated arm.

**Promotion signal:** the composition causes a trajectory-supported coupled edit, catches an incomplete fix, or selects a relevant test while preserving the negative-flip contract.

**Rejection signal:** the obligation overstates what a certified relationship proves, induces unnecessary edits, or duplicates facts already represented in retained history.

### A3 — Automatic provider-visible relational delivery

**Type:** Type 2, mechanism strengthening.

**Hypotheses tested:** H1 and H2: decision-local delivery through the existing provider request replaces exploration more efficiently than requiring agent-initiated intelligence work.

**Full treatment:** selected certified relational/process evidence is appended to the first eligible normal provider request through GT's existing bounded contribution compiler.

**Ablated treatment:** compute and receipt the identical selection in shadow, but suppress only that selected relational/process payload from the provider view. Task-semantic evidence, exact validation evidence, completion evidence, and safety-critical delivery remain unchanged.

**Primary evidence:** request-by-request provider-view hashes, the first divergent model action, search/read/test counts, provider calls, tokens, steps, cost, and solves.

**Promotion signal:** visible relational delivery changes a useful decision or replaces exploration without increasing provider calls and without an attributable negative flip.

**Rejection signal:** visible delivery is routinely ignored, duplicates history, or causes harmful over-weighting. A rejection applies to the selection/presentation policy, not to automatic delivery as a product invariant.

### A4 — Conditional follow-up selected by failure evidence

Do not pre-authorize a broad fourth arm. Select one narrow follow-up only if A1-A3 or the same-20 autopsies identify a repeated failure class with at least two task witnesses.

Eligible examples are:

- receiver-chain/type-resolution composition;
- explicit completeness/truncation disclosure;
- ambiguity/external/heuristic suppression policy; or
- route/API/test process enrichment.

The selected arm must name the two witnesses, the exact changed function/configuration boundary, the claimed failure class, and why A1-A3 did not already isolate it.

Completion criterion: no A4 job exists without this evidence-backed selection record.

## 5. Per-arm causal receipt

For every task and arm, record this chain with `YES`, `NO`, or `UNKNOWN` at each transition:

```text
mechanism eligible
  -> candidate facts existed
  -> facts were current and certified
  -> composition selected them
  -> payload fit the budget
  -> provider delivery was valid
  -> first model action after delivery changed or did not change
  -> repository state changed
  -> validation/postflight refreshed state
  -> final solve result
```

For each changed outcome, identify the first meaningful trajectory divergence. Classify positive flips as `GT CAUSED`, `GT LIKELY CAUSED`, `UNCERTAIN`, or `MODEL VARIANCE`. Classify negative flips as `GT CAUSED`, `GT LIKELY CAUSED`, `INFRASTRUCTURE`, `DELIVERY`, `STATE`, `MODEL VARIANCE`, or `UNKNOWN`, with `CONFIRMED/HIGH/MEDIUM/LOW/NOT ATTRIBUTABLE` confidence.

Private computation, receipt generation, or a changed request hash alone is not causal evidence.

Completion criterion: every flip has a task-level receipt and a stated causal confidence.

## 6. Efficiency accounting

On common-solved tasks, compare:

- total executor steps;
- provider calls, including the one bootstrap separately and in total;
- uncached input, cached input, output tokens, and total tokens;
- total cost and cost per solved task;
- wall-clock time;
- searches, file reads, and tests;
- GT computation time and delivered evidence tokens; and
- the exact additional or avoided operation responsible for each material delta.

The interpretation question is binary: did the mechanism replace exploration, or did it add exploration? Aggregate token changes without an operation-level explanation are insufficient.

Completion criterion: every material efficiency regression maps to a concrete extra action, request contribution, or host computation.

## 7. Decision rules and stop conditions

Promote a mechanism only when all of these hold:

1. both compared treatment arms pass integrity;
2. the claimed effect is visible in task-level trajectories, not only an aggregate score;
3. attributable positive flips exceed attributable negative flips;
4. no confirmed/high-confidence negative flip remains without a minimum causal repair;
5. provider calls do not increase;
6. evidence either improves solves or replaces measurable exploration; and
7. no benchmark-specific task-ID or repository rule was introduced.

Stop an arm immediately from release consideration if it has an integrity failure, stale evidence, invalid delivery receipt, task/commit/model mismatch, silent retrieval loss, denominator change, uncontrolled prompt difference, or provider censoring that prevents a matched interpretation.

A single stochastic outcome can establish an observed result but not temperature-invariant solve causality. Deterministic host behavior is proven through replayable state/request hashes and provider-free differential tests; model-outcome uncertainty remains reported rather than erased by repeated benchmark spending.

## 8. Required output

After each authorized arm, append one experiment report containing:

1. immutable identities and the one treatment delta;
2. integrity result;
3. 20-task solve accounting;
4. task-level flip autopsies;
5. common-solved efficiency accounting;
6. intervention/delivery accounting;
7. hypothesis verdict: supported, falsified, or unresolved;
8. promote, repair-and-retest, or reject decision; and
9. the next authorized arm, if any.

The ablation program is complete when A1-A3 each have an integrity-valid causal report, or when a stop condition establishes that continuing would not yield an interpretable comparison.
