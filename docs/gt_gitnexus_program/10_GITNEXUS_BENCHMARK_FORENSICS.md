# Akon Labs GitNexus benchmark forensics

## Audit identity and source boundary

Primary sources only:

- **Akon Labs official benchmark page:** [akonlabs.com/benchmarks](https://www.akonlabs.com/benchmarks), accessed 2026-08-18.
- **Official GitNexus repository revision used for implementation comparison:** [`fc885a4bf3edddf9214df633d8d1c0767ef58af9`](https://github.com/abhigyanpatwari/GitNexus/commit/fc885a4bf3edddf9214df633d8d1c0767ef58af9).
- **Official DeepSWE repository snapshot used to check public benchmark structure:** [`datacurve-ai/deep-swe@435ee89ec2f2e2289f33b0da4f992f0b7b7266b9`](https://github.com/datacurve-ai/deep-swe/commit/435ee89ec2f2e2289f33b0da4f992f0b7b7266b9), with its [pinned README](https://raw.githubusercontent.com/datacurve-ai/deep-swe/435ee89ec2f2e2289f33b0da4f992f0b7b7266b9/README.md).

Important pin limitation:

- GitNexus and DeepSWE source can be pinned to commits.
- The Akon benchmark page is mutable and has no public source commit or versioned data artifact.
- Akon does not identify the GitNexus commit, benchmark-harness commit, or DeepSWE manifest commit used in the reported experiment.
- Therefore `fc885a4` is the source revision audited for current mechanisms, not the proven treatment revision behind the reported scores.

Evidence labels:

- **PUBLISHED FACT:** stated on an official first-party page or repository.
- **DERIVED FACT:** exact arithmetic or direct source inspection from published facts.
- **INFERENCE:** plausible interpretation not isolated by the experiment.
- **UNKNOWN:** not publicly disclosed.

## Executive verdict

Akon reports a large configuration-level result: GitNexus 68.37%, Graphify 54.02%, and Bare 36.99% on what it calls the full DeepSWE benchmark, with lower average cost, output tokens, and steps for GitNexus.

The report is not publicly reproducible. The manifest, task/repository SHAs, harness, prompts, raw attempt rows, trajectories, model sampling settings, treatment source versions, retrieval configuration, embeddings, hooks, index lifecycle, retries, exclusions, and token-accounting details are not published.

The headline arithmetic is internally inconsistent:

```text
113 tasks * 3 arms * 10 trials = 3,390 trials
```

but the page reports 3,471 trials.

The stated 116-entry manifest would imply:

```text
116 entries * 3 arms * 10 trials = 3,480 trials
```

which is nine more than reported.

The reported percentages are almost exactly integer solve counts over 1,157 attempts per arm, suggesting balanced arm denominators of 1,157, but that denominator cannot be reconciled with “113 tasks” and “10 per task per arm” from the public page.

The correct causal statement is narrow:

> Akon's undisclosed GitNexus-enhanced configuration substantially outperformed its undisclosed Bare and Graphify configurations in the reported experiment.

The public evidence does not identify which GitNexus mechanism caused the delta.

Confidence: **high** in the reporting and reproducibility defects; **low** in feature-level causal attribution.

## 1. Published setup

The [official Akon page](https://www.akonlabs.com/benchmarks) states:

| Field | Published value |
|---|---|
| Benchmark | DeepSWE, “116 entry manifest” |
| Evaluated tasks | 113 |
| Projects | 89 |
| Languages | Python, Go, TypeScript, Rust |
| Model | `openai/gpt-5.6-terra (med)` |
| Arms | GitNexus, Graphify, Bare model |
| Trials | 3,471 |
| Repetitions | “10 per task per arm” |
| Scaffold claim | same model and scaffold throughout |
| Scoring | all failing tests pass and no previously passing test regresses; no partial credit |
| Run metrics | cost, tokens, and steps from one run-record row per attempt |

Akon describes the arms as:

- GitNexus with its code graph;
- Graphify with “code extraction only”;
- Bare with no retrieval layer.

That description is not a reproducible treatment specification.

## 2. Published aggregate results

| Arm | Pass rate | Cost per trial | Output tokens | Steps | Published/derived cost per solve |
|---|---:|---:|---:|---:|---:|
| GitNexus | 68.37% | $0.6008 | 21,077 | 44.94 | about $0.88 |
| Graphify | 54.02% | $0.6364 | 21,769 | 48.00 | about $1.18 |
| Bare | 36.99% | $0.6631 | 22,252 | 50.25 | about $1.79 |

The page also reports GitNexus versus Bare:

- 15.8% fewer input tokens;
- 5.3% fewer output tokens;
- 10.6% fewer steps;
- lower spend per attempt;
- GitNexus wins 98 tasks, ties 8, and loses 7;
- a two-proportion z-test of `z = 15.11`, `p < 1e-50`;
- 95% pass-rate intervals of 65.6–71.0% for GitNexus and 34.3–39.8% for Bare.

The task head-to-head counts sum correctly:

```text
98 + 8 + 7 = 113 tasks
```

## 3. Difficulty breakdown

Akon groups tasks by the Bare arm's observed solve frequency:

| Group | Definition | Tasks | GitNexus | Graphify | Bare |
|---|---|---:|---:|---:|---:|
| Easy | Bare solves over 66% | 17 | 94.7% | 78.9% | 80.8% |
| Moderate | Bare solves 33–66% | 38 | 77.3% | 66.6% | 49.9% |
| Hard | Bare solves under 33% | 58 | 55.9% | 39.1% | 15.9% |

The group counts reconcile:

```text
17 + 38 + 58 = 113 tasks
```

The page emphasizes a 40-point GitNexus advantage on the 58 hard tasks.

### Forensic limitation

Difficulty is defined using the Bare outcomes from the same experiment and the same trials used to estimate the within-group difference.

**INFERENCE:** this can amplify regression-to-the-mean and selection effects. A cleaner difficulty definition would use independent historical outcomes, a separate model/configuration, reference complexity, or leave-one-trial-out grouping.

This does not prove the hard-task gain is false. It means the exact 40-point magnitude is not cleanly estimated by the disclosed grouping procedure.

## 4. Trial arithmetic inconsistency

### 4.1 Task-based arithmetic

Published claims:

```text
tasks = 113
arms = 3
trials per task per arm = 10
```

Required total:

```text
113 * 3 * 10 = 3,390
```

Published total:

```text
3,471
```

Difference:

```text
3,471 - 3,390 = 81 unexplained trials
```

### 4.2 Manifest-based arithmetic

Using the published 116-entry manifest:

```text
116 * 3 * 10 = 3,480
```

Difference:

```text
3,480 - 3,471 = 9 unreported/missing trials
```

### 4.3 Integer-denominator reconstruction

If trials were balanced across three arms:

```text
3,471 / 3 = 1,157 attempts per arm
```

The published pass rates map almost exactly to integer solve counts over 1,157:

| Arm | Integer solves | Fraction | Rounded published rate |
|---|---:|---:|---:|
| GitNexus | 791 | `791 / 1157 = 68.366%` | 68.37% |
| Graphify | 625 | `625 / 1157 = 54.019%` | 54.02% |
| Bare | 428 | `428 / 1157 = 36.992%` | 36.99% |

This strongly suggests an arm denominator of 1,157.

But:

```text
1,157 / 113 = 10.2389 attempts per evaluated task per arm
```

That is inconsistent with exactly ten attempts per evaluated task per arm.

### Required explanation

At least one of these must be wrong or incomplete:

- 113 evaluated tasks;
- 116-entry manifest;
- ten trials per task per arm;
- 3,471 total trials;
- balanced arm denominators;
- absence of extra retries/replacements/exclusions.

The page does not reconcile them.

## 5. Missing benchmark identity

The public page does not provide:

- exact task IDs;
- exact repository commits or images;
- the 116-entry manifest;
- which three entries were not part of the 113-task result;
- benchmark harness source or commit;
- evaluator/verifier source revision;
- GitNexus source/package commit;
- Graphify source or commit;
- Bare/Graphify/GitNexus prompts;
- tool schemas and tool descriptions;
- hook configuration;
- augmentation mode;
- index options;
- embeddings enabled/disabled and model identity;
- PDG enabled/disabled;
- process/community options;
- stale-index behavior;
- model provider and response identity;
- exact reasoning effort semantics behind `(med)`;
- temperature, top-p, seed, or other sampling settings;
- maximum steps, tokens, cost, or wall time;
- retry policy;
- infrastructure-error and censoring policy;
- exclusions and replacement attempts;
- cached versus uncached token accounting;
- indexing cost, latency, and failures;
- raw per-attempt metrics;
- raw trajectories.

The page invites readers to contact Akon for raw trajectories; it does not publish them.

## 6. Graphify is undefined

The page's phrase “code extraction only” does not identify Graphify's:

- parser;
- language versions;
- symbol and relation schema;
- import/call/receiver resolution;
- uncertainty policy;
- storage/index lifecycle;
- retrieval/ranking;
- response format;
- prompt and tool descriptions;
- hook behavior;
- embeddings;
- process construction.

Therefore the `54.02% -> 68.37%` difference cannot be attributed specifically to:

- receiver resolution;
- execution processes;
- clustering;
- hybrid retrieval;
- automatic augmentation;
- impact/context response composition;
- any other individual GitNexus feature.

Bare → Graphify → GitNexus are experimental arms. They are not product-version history and are not a component-ablation ladder.

## 7. Public GitNexus evaluator does not reconstruct Akon's benchmark

The pinned official GitNexus repository contains a public SWE-bench-oriented evaluator:

- [`eval/agents/gitnexus_agent.py`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/eval/agents/gitnexus_agent.py)
- [`eval/environments/gitnexus_docker.py`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/eval/environments/gitnexus_docker.py)

It proves that a GitNexus treatment can combine:

- mode-specific system and instance prompts;
- explicit native graph tools;
- automatic grep-observation augmentation;
- a task-start index and warm eval server;
- optional/skipped embeddings.

It does not prove that Akon's DeepSWE run used the same adapter, settings, or lifecycle.

Conflating the public evaluator with the unpublished Akon harness would be a source error.

## 8. Official DeepSWE source boundary

The pinned [DeepSWE README](https://raw.githubusercontent.com/datacurve-ai/deep-swe/435ee89ec2f2e2289f33b0da4f992f0b7b7266b9/README.md) describes task packages containing:

- `task.toml` repository/base-commit/language/image/limit metadata;
- `instruction.md` shown to the agent;
- a reproducible environment;
- held-out verifier tests and grader configuration;
- a held-out reference solution for offline review, not grading-time use.

This demonstrates that a reproducible DeepSWE run can be pinned at task and repository level.

Akon's page does not publish which DeepSWE snapshot, manifest transformation, repository/image revisions, or exclusions produced its “116 entry manifest” and 113 evaluated tasks.

Therefore the Akon denominator cannot be independently reconstructed from official public artifacts.

## 9. Statistical-method limitations

### 9.1 Unit of analysis

Ten attempts on one task share:

- task specification;
- repository;
- verifier;
- task difficulty;
- many infrastructure conditions.

They are clustered observations, not 10 unrelated task samples.

The page reports a two-proportion z-test but does not disclose whether it accounts for task/project clustering.

**INFERENCE:** the reported interval widths are compatible with treating attempts as independent binomial observations. Without code or raw rows, this cannot be confirmed.

A stronger analysis would use:

- paired task-level effects;
- task-clustered bootstrap;
- hierarchical bootstrap across projects and tasks;
- mixed-effects/hierarchical outcome modeling;
- predeclared handling of missing attempts and censoring.

### 9.2 Repeated-trial independence

Provider/system state can create additional dependence:

- shared rate limits;
- warm caches;
- image or network incidents;
- repeated repository indexing;
- temporal provider drift;
- upstream model/provider routing.

The public page does not describe randomization order, concurrency, or crossover balancing.

### 9.3 Multiple outcomes

Akon emphasizes pass rate, cost, output tokens, and steps. It does not publish:

- uncached versus cached input;
- total tokens;
- provider calls;
- file reads and searches;
- tests;
- indexing/host computations;
- evidence tokens;
- wall time;
- cost on common-solved tasks;
- failure-capped resource accounting.

Without common-solved accounting, cheaper failure trajectories can distort aggregate efficiency. In Akon's result the higher solve rate makes a purely cheap-failure explanation less likely, but it does not identify which operations were removed or added.

## 10. Why lower average steps/tokens do not isolate navigation

The published metrics are compatible with more efficient repository navigation, but several mechanisms can produce the same aggregate pattern:

- successful trajectories terminate earlier;
- failed trajectories exhaust more of the budget;
- prompts change reasoning verbosity;
- automatic context replaces searches;
- automatic context adds information and changes strategy;
- tools alter testing behavior;
- retries or censored rows are handled differently;
- indexing/host work is excluded;
- cached input is accounted differently.

Raw matched trajectories are required to answer:

```text
Did GitNexus replace exploration?
or
Did it add context while some other factor shortened the run?
```

## 11. Source-versus-inference ledger

| Claim | Status | Confidence |
|---|---|---:|
| Akon reports 68.37/54.02/36.99% | Published fact | High |
| Akon reports 3,471 trials and ten/task/arm | Published fact | High |
| The arithmetic does not reconcile | Derived fact | High |
| Rates fit 791/625/428 solves over 1,157 attempts/arm | Derived fact | High |
| The benchmark used `fc885a4` | Unknown | Unknown |
| The benchmark enabled embeddings | Unknown | Unknown |
| The benchmark enabled PDG | Unknown | Unknown |
| The benchmark used automatic augmentation | Unknown | Unknown |
| GitNexus process composition caused the solve delta | Inference | Low |
| GitNexus replaced exploration in many trials | Inference | Moderate plausibility, unproven |
| Graph resolution quality contributed | Inference | Moderate plausibility, unproven |
| GitNexus is causally better than Bare under the undisclosed configuration | Supported at configuration level if reporting is accurate | Moderate/high, not independently reproducible |
| A particular GitNexus mechanism accounts for the Graphify delta | Unsupported | Low/unknown |

## 12. Strongest plausible mechanism hypothesis

Current source proves that GitNexus can combine:

```text
automatic enrichment of an ordinary search/read
  +
process-grouped callers/callees/routes/sinks
  +
compact provider responses
```

**INFERENCE:** this combination is the strongest source-level explanation for simultaneously higher solves and fewer steps/tokens because it can replace repeated grep/read/caller-search cycles.

Alternative contributors include:

- broader receiver/call resolution;
- prompts and tool descriptions;
- framework extraction;
- impact and change-detection tools;
- task-selection or infrastructure differences;
- embeddings or other undisclosed settings.

No public ablation separates them.

## 13. Required artifacts for reproduction

An independently reproducible report needs:

1. exact GitNexus commit and package/build digest;
2. exact DeepSWE task manifest and benchmark commit;
3. task repository/image/base-commit identities;
4. exact Graphify source/configuration;
5. exact prompts for every arm;
6. exact tool schemas, hooks, and automatic augmentation configuration;
7. model provider, catalog ID, reasoning mode, temperature, and sampling parameters;
8. step/token/cost/wall-time budgets;
9. embeddings, PDG, community, and process settings;
10. index cache/freshness/update policy;
11. trial randomization and concurrency;
12. retry, censoring, infrastructure-error, and exclusion rules;
13. exact denominator reconciliation for 3,471 trials;
14. per-task and per-attempt outcomes;
15. cached/uncached token and cost accounting;
16. indexing/host-call latency and resource accounting;
17. raw trajectories or sufficient event-level receipts;
18. task-clustered confidence intervals;
19. feature ablations separating graph construction, resolution, processes, retrieval, prompt, and delivery.

## 14. Implications for GT's evaluation

GT should preserve the opposite measurement properties:

- exact frozen task and repository identity;
- exact treatment source/runtime SHA;
- complete denominator with no silent exclusion;
- per-task substrate, retrieval, delivery, state, outcome, and resource receipts;
- common-solved efficiency accounting;
- explicit provider calls and bootstrap overhead;
- matched flip classification;
- task-clustered repeated-trial analysis when repeated trials are used;
- component ablations for mechanism claims;
- no causal positive/negative flip claim without trajectory evidence.

The current 20-task gate is not made stronger by running more stochastic repetitions before fixing integrity. First establish that the intended deterministic treatment actually ran and reached the provider correctly on every applicable task.

## 15. What the benchmark supports and does not support

### Supports, conditional on the first-party report

- a large aggregate difference between Akon's three configurations;
- higher reported GitNexus pass rate;
- lower reported average cost, output tokens, and steps;
- a result worth investigating at source level.

### Does not support

- public independent reproduction;
- attribution of the delta to one GitNexus mechanism;
- treating Bare → Graphify → GitNexus as version history;
- claiming embeddings, clustering, or processes individually caused uplift;
- claiming zero regressions per task or trial;
- assuming the public GitNexus eval adapter is the Akon harness;
- direct comparison with GT until task/model/scaffold/provider/evaluator identity is matched;
- official leaderboard equivalence for an undisclosed configuration.

## Final verdict

GitNexus's source is valuable competitive evidence. Akon's current benchmark is useful directional signal but weak causal and reproducibility evidence.

The strongest defensible program decision is:

> Test GitNexus-derived process composition and action-local delivery inside GT's existing frozen, receipt-complete evaluation framework. Do not import Akon's aggregate causal story, and do not claim direct outperformance until the manifest, model, provider, scaffold, settings, and evaluator are matched.
