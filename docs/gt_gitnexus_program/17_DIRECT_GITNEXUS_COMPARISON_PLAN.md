# Direct GroundTruth versus GitNexus comparison plan

## Status and decision boundary

This document defines the evidence required before a direct comparison can be called fair. It does not authorize a paid run.

Start only after:

1. the strengthened GroundTruth treatment passes the same-20 release gate in `15_20_TASK_RERUN_REPORT.md`; and
2. at least one targeted mechanism in `16_NEXT_ABLATION_PLAN.md` has an integrity-valid, task-level result.

The comparison must answer whether GT produces a defensible solve-rate/efficiency Pareto improvement over GitNexus. It must not be presented as an exact reproduction of Akon Labs' benchmark unless Akon's currently missing experimental artifacts are obtained and verified.

## 1. Baseline policy

The comparison dispatches intelligence-treatment arms only. It never dispatches a new bare or GT-disabled arm.

Use one of these read-only references:

- for the frozen local `repair20-v1` experiment, join `eval/frozen_baselines/tb2_miniswe_20260731.json` at SHA-256 `f75ebc8dd1eb25cb31cfa099b196d54346016b9f2de8e6f026e420cc213dd0bf`;
- for a DeepSWE experiment, use the official online baseline entry and its published configuration identity, without locally recreating that arm.

The direct primary comparison is GitNexus versus GroundTruth on identical task instances. The read-only baseline supplies context; it is not part of the dispatched experiment.

Completion criterion: the run graph contains only pinned GitNexus and GT treatment jobs, while the report records the immutable reference source separately.

## 2. What the Akon result does and does not provide

The source audit in `10_GITNEXUS_BENCHMARK_FORENSICS.md` establishes the following first-party claims:

- 113 tasks across 89 projects, with a separate statement referring to a 116-entry manifest;
- model `openai/gpt-5.6-terra (med)`;
- 3,471 trials and a claim of 10 trials per task per arm;
- reported solve rates of 68.37% for GitNexus, 54.02% for Graphify, and 36.99% for Bare; and
- reported GitNexus averages of $0.6008 per trial, 21,077 output tokens, and 44.94 steps.

The published arithmetic is internally inconsistent:

- `113 × 3 × 10 = 3,390`, not 3,471;
- `116 × 3 × 10 = 3,480`, nine more than 3,471; and
- the published rates reconstruct exactly as 791/1,157, 625/1,157, and 428/1,157, implying 1,157 attempts per arm without explaining their allocation.

The official sources do not publish the exact task manifest, task/repository SHAs, complete prompts, scaffold version, tool schemas, hook configuration, GitNexus/Graphify commit identities, embedding/PDG settings, retry/censoring rules, raw attempt rows, or trajectories. Those omissions prevent independent reproduction and prevent attributing the reported aggregate delta to any one GitNexus mechanism.

Decision rule: treat Akon's numbers as configuration-level reported results. Do not use 68.37% as a release threshold and do not call a new comparison an Akon reproduction while any required identity is unknown.

## 3. Two permissible comparison paths

### Path A — Exact Akon/DeepSWE reconstruction

Use this path only if Akon Labs supplies and permits verification of every item in the parity ledger below, including raw trial allocation sufficient to resolve the 3,471-trial inconsistency.

Dispatch only:

1. pinned GitNexus on the disclosed task instances; and
2. pinned GroundTruth on the same instances.

Join the official online bare baseline offline. If the exact `openai/gpt-5.6-terra (med)` route, scaffold, prompts, or task snapshots cannot be reproduced, stop calling the experiment a reconstruction and move to Path B.

### Path B — New controlled direct comparison

This is the recommended path under current evidence.

Predeclare a public or frozen task manifest and run GitNexus and GT under one newly frozen, identical agent configuration. Prefer the exact public DeepSWE task snapshot if its task identities, repositories, and evaluator are available. Otherwise use the frozen local `repair20-v1` set as an initial direct mechanism comparison, keeping all 20 tasks in the denominator even when one system lacks language or graph coverage.

Label the result as a new controlled comparison, not as validation or refutation of Akon's reported benchmark. Join the corresponding official-online or frozen-local baseline offline.

Completion criterion: the selected path and its claim boundary are written into the preregistration before any treatment job is dispatched.

## 4. Exact parity ledger

Freeze and hash every field below. An unknown field blocks an exact-parity claim.

| Domain | Required identity |
|---|---|
| Tasks | task IDs, order, instruction bytes, repository URL, base SHA, task image, workspace transfer rules, supported-source policy |
| Evaluation | verifier code/version, grader image, timeout, denominator, failure/censoring policy, exclusions, pass aggregation |
| Model | exact catalog ID, response model identity, provider route, system fingerprint when supplied, reasoning effort/mode, temperature, top-p, seed support, tool-choice policy |
| Agent | scaffold source SHA/version, system prompt, instance prompt, retained-history/compaction policy, tool loop, submission rule |
| Tools | tool names, schemas, command executor, search/read/edit/test interfaces, MCP or hook exposure, tool-result rendering |
| Budgets | maximum steps, provider calls, tokens, wall clock, per-call timeout, task timeout, retries, concurrency |
| GitNexus | official repository and commit SHA, build/runtime versions, parser set, GraphRAG/embeddings/PDG settings, index command, MCP/hook configuration, automatic augmentation configuration |
| GT | repository and commit SHA, profile, exact 17+1 census, indexer source SHA, dense asset revision/hash, preflight mode, delivery and lifecycle configuration |
| Lifecycle | initial indexing point, repository fingerprint, changed-file handling, stale detection, reindex/refresh policy, lock/recovery behavior, partial-index policy |
| Accounting | system-specific setup calls, bootstrap calls, provider calls, host computations, indexing time, retrieval time, evidence tokens, cached/uncached tokens, cost source |
| Runtime | operating system/image, CPU/GPU class where relevant, filesystem semantics, network policy, dependency lockfiles |
| Provenance | run manifest hash, per-task receipt paths, raw trajectories, provider receipts, result rows, artifact retention |

No arm may receive a more informative task prompt, larger budget, different model setting, or different evaluator. System-specific intelligence surfaces may differ because that is the treatment, but their prompts, automatic injections, tool calls, tokens, latency, and failures must all be visible and counted.

Completion criterion: a machine-readable parity manifest has no unresolved required field and hashes to the same non-treatment configuration for both arms.

## 5. Pinned treatment identities

### GitNexus

Start from the audited official commit:

```text
fc885a4bf3edddf9214df633d8d1c0767ef58af9
```

Use the official product surface selected in the preregistration. The source audit in `07_GITNEXUS_ARCHITECTURE.md` and `09_GITNEXUS_DELIVERY_AND_LIFECYCLE.md` distinguishes:

- explicit MCP queries;
- automatic augmentation through hooks; and
- the public evaluation adapter.

These are not interchangeable. Select one primary configuration, preserve it for the entire run, and count every model-visible payload and agent-initiated intelligence call. If the model must choose a separate GitNexus tool, that provider/tool roundtrip is part of its efficiency result.

### GroundTruth

Pin the exact release-gate-passing commit and the strengthened profile derived from `central_relational_v2`. GT remains the active host-owned engine with deterministic state compilation, certified delivery, one bounded bootstrap, and current-revision postflight/rebase behavior. Do not remove these capabilities to imitate GitNexus.

Completion criterion: both repositories build from the pinned sources and pass provider-free smoke/integrity checks before the task matrix exists.

## 6. Index and state lifecycle fairness

The systems need the same correctness requirement, not the same architecture:

> No model-visible repository claim may be represented as current after the underlying source revision changes unless the system has refreshed or explicitly marked the claim unavailable/stale.

GitNexus's audited public evaluation adapter indexes before the trajectory and does not prove post-edit refresh. Its source contains index locks, dirty-state recovery, and incremental-update machinery, but source existence does not prove that a given benchmark integration exercises it. GT refreshes graph/state at host postflight and fails closed on stale source intelligence.

For each arm:

1. record the exact repository fingerprint used by each model-visible claim;
2. record every material source transition;
3. record whether the index/state refresh completed before the next eligible provider request;
4. mark stale or unavailable evidence explicitly; and
5. count refresh/reindex time and computation.

Run the official native integration as the primary product comparison. Do not secretly add a lifecycle service to one arm. If a secondary lifecycle-normalized diagnostic is scientifically necessary, preregister it as a separate experiment and report it separately.

Completion criterion: no stale claim is silently counted as valid, and lifecycle differences remain treatment facts rather than hidden harness differences.

## 7. Primary arms and optional differentiated arm

### Primary G — GitNexus

Pinned GitNexus with the selected official native delivery mode.

### Primary T — GroundTruth

Pinned release-gate-passing GT with the selected strengthened profile.

### Optional G+T — GitNexus intelligence plus GT-specific intervention layer

Run this only after the primary comparison. Its purpose is to test whether GT's differentiated capabilities add value on top of GitNexus repository intelligence, especially:

- compiler/LSP-resolved semantics;
- certified uncertainty and provenance;
- task/check/deliverable semantics;
- post-change deterministic verification;
- changed-symbol/process/test obligations; and
- assistive-safe contradiction handling.

The combined arm must identify the provenance of every contribution and prevent duplicate facts from consuming the evidence budget. It is a separate product hypothesis, not evidence that primary GT beat GitNexus.

Completion criterion: G and T complete with valid integrity before G+T can be authorized.

## 8. Integration rules

1. Preserve one common Mini-SWE/provider loop and one common task prompt.
2. Let each treatment use its native repository-intelligence computation and delivery surface.
3. Render all automatic context through auditable provider-visible messages.
4. Count setup, indexing, retrieval, embeddings, bootstrap, model/tool calls, and refresh work.
5. Retain complete raw trajectories and treatment receipts.
6. Do not silently continue after index/setup/hook failure. Mark the task integrity-invalid for that arm while retaining it in the solve denominator.
7. Do not exclude unsupported languages or repositories. Report support coverage separately and count the full frozen task set.
8. Do not add benchmark-task-specific prompts, rules, paths, or expected patches.
9. Do not give either system grader-only artifacts or host verifier output unavailable to the agent.
10. Keep provider censoring separate from product failure while preserving the task row.

Completion criterion: a provider-free integration witness proves each treatment's exact provider view, calls, and index identity before paid execution.

## 9. Outcome and causal accounting

Report four result planes separately:

### Integrity

- repository-intelligence availability;
- retrieval/tool availability;
- delivery visibility and receipts;
- source/index freshness;
- setup/hook/MCP failures; and
- treatment applicability.

### Solves

For G versus T, report:

```text
BOTH SOLVE
GITNEXUS ONLY
GT ONLY
BOTH FAIL
```

Use the immutable baseline only as a third, offline reference classification. It must not be conflated with the direct paired result.

### Efficiency

On common-solved tasks compare steps, provider calls, uncached/cached input, output and total tokens, cost, wall clock, searches, file reads, tests, system computation, indexing/refresh cost, and cost per solved task.

### Interventions

For every treatment-only solve or loss, locate the first meaningful trajectory divergence, identify the immediately preceding evidence/tool response, and classify causal confidence. A tool availability difference, request hash, or aggregate score is not by itself a causal mechanism proof.

Completion criterion: every row has integrity, solve, efficiency, and intervention fields without collapsing them into one pass/fail label.

## 10. Statistical plan

The primary estimand is the paired difference in solve probability between G and T across the full frozen task denominator. Secondary estimands are cost per solved task and resource differences on common-solved tasks.

- For one attempt per task, report exact paired counts and an exact McNemar interval/test where informative; do not imply that one stochastic outcome proves temperature-invariant superiority.
- If repeated treatment trials are explicitly authorized, preregister the count and use task-clustered bootstrap or a hierarchical model. Do not treat repeated attempts on the same task as independent task samples.
- Report confidence intervals for solve difference and cost per solve.
- Treat tasks as the primary generalization unit; repositories form a second clustering level when the benchmark includes multiple tasks per repository.
- Separate exploratory subgroup results from preregistered primary outcomes.
- Publish raw task/attempt rows so the arithmetic reconstructs exactly.

Completion criterion: reported denominators, solve numerators, trial counts, and aggregate rates reproduce exactly from the public result rows.

## 11. Decision standard

GT outperforms GitNexus when the paired evidence supports a defensible Pareto improvement, prioritizing:

1. higher solve rate;
2. higher causal positive-flip minus causal negative-flip balance;
3. lower cost per solved task;
4. fewer unnecessary provider calls and reasoning steps; and
5. lower uncached input and exploration work.

GT need not win every raw efficiency metric if it achieves a material solve-rate gain with better or defensible cost per success. Conversely, lower cost with lower solve rate is not automatically superiority.

Claims must be bounded:

- `observed better on this frozen comparison` when evidence is a single matched run;
- `statistically supported on this task distribution` when the preregistered clustered analysis supports it;
- never `reproduces Akon` unless Path A parity is complete; and
- never `mechanism X caused the whole GitNexus delta` without an isolated ablation and trajectories.

## 12. Stop conditions

Do not dispatch or do not interpret the result as direct evidence when any of these holds:

- unknown task or repository identity;
- model/provider/scaffold/prompt mismatch;
- changed verifier, denominator, budget, or censoring policy;
- unavailable pinned source or dependency;
- silent GitNexus setup/augmentation failure;
- invalid GT delivery/lifecycle receipt;
- stale index evidence represented as current;
- missing raw trajectories or per-task result rows; or
- an accounting path that omits system-specific calls, tokens, indexing, or refresh work.

If Akon's missing materials remain unavailable, that blocks only an exact Akon reconstruction. It does not block a transparently labeled new controlled G-versus-T comparison once the full Path B manifest is frozen.

## 13. Required artifacts and authorization checkpoint

Before task dispatch, create and review:

1. a claim-boundary statement selecting Path A or Path B;
2. the machine-readable exact-parity manifest;
3. pinned source/dependency/build receipts for both systems;
4. provider-free provider-view and lifecycle witnesses;
5. the immutable task manifest and baseline-reference hash/URL;
6. the statistical preregistration;
7. the artifact-retention plan for raw trajectories and receipts; and
8. a cost ceiling covering only the two treatment arms.

The authorization checkpoint passes only when every parity field is known, every hash is verified, both integrations pass provider-free checks, and the claim language matches the selected path. Until then, the scientifically correct result is `NOT READY FOR DIRECT COMPARISON`.
