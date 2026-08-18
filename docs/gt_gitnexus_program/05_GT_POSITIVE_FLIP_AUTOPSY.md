# 05 — Positive-flip autopsy

## Result and causal limit

Workflow `32163376177` contains exactly one raw GT-only solve against the frozen local GT-off cohort: `largest-eigenval`. The other 13 GT-on solves are common solves, not positive flips. Calling all of them GT-created value would be false.

The one flip is promising but not causally proven. The arms have different provider fingerprints and initial provider views, temperature is 1, and only one trial exists. Exact provider hashes prove what GT exposed; they do not reveal internal model reliance. The proper label is **credible GT mechanism, moderate causal confidence**, not “GT caused” with certainty.

Evidence sources are the GT-on artifacts at `D:\tmp\run32163376177\` and `D:\tmp\run32163376177-merged\`, plus the frozen GT-off trajectory below `D:\gt_runs\miniswe_tb2_gtoff_20260731\matrix_cache\largest-eigenval\`. Post-hoc reward is used only to identify the outcome.

## `largest-eigenval`

### Outcome

- Frozen GT-off: unresolved.
- GT-on: resolved in 47 actions.
- GT-on repository-intelligence analytical gate: failed `material_frontier_not_delivered`.
- GT-on dense backend: available.
- GT-on provider delivery: four certified visible deliveries.
- GT-on release accounting: `contribution_task_usage_mismatch`.

The apparent contradiction is important. The run can contain a useful delivered repository excerpt while separately failing to prove that its declared material frontier was rendered/accounted. The positive outcome does not erase the integrity failure, and the integrity failure does not imply that no repository evidence reached the model.

### What GT knew

At the first provider request GT supplied:

- the exact target anchor `eigen.py:4#find_dominant_eigenvalue_and_eigenvector`;
- a checkout-backed source excerpt containing the current target implementation;
- the instruction-derived focus on completing that function.

The evidence was bounded, source-derived, and available before the model's first repository command. It was not a guessed solution and did not use verifier-only material.

### How GT obtained it

The task semantic substrate extracted the explicit path/function focus from the instruction. Repository indexing and hybrid/relational context resolved that anchor to the current checkout and packed the complete relevant excerpt. Persistent state and the contribution compiler placed it into the provider view at call 1 with request/message hashes.

### What decision changed

The GT-on model could begin from the exact implementation body rather than first spending a model-selected read merely to discover it. It moved into implementation/performance investigation, including compiled C/`ctypes` exploration, testing, and eventual submission. The frozen baseline had to obtain its repository state through ordinary actions and followed a different, unsuccessful trajectory.

This is temporal/mechanistic evidence, not a counterfactual. The decisive statement is:

> GT delivered the exact target implementation before the first model action, and the GT-on trajectory solved; whether that delivery was necessary or sufficient is unknown.

### Positive mechanism extracted

**Certified target implementation replacement**

```text
explicit instruction anchor
        + exact symbol resolution
        + current complete source span
        + first-request delivery
        = one model search/read avoided and immediate implementation context
```

Why this can generalize:

- It uses task/repository facts, not task-ID rules.
- It is useful across languages whenever an explicit anchor resolves uniquely.
- It changes the information available at the decision point without adding a provider call.
- It can replace exploration rather than append a separate advisory turn.

Expected failure classes addressed: wrong localization, failure to inspect the current implementation, wasted early search/read, and incomplete task-start context.

Negative-flip risks:

- a uniquely resolved symbol can still be task-irrelevant if the instruction anchor is weak;
- a source excerpt without callers/tests/types can create local tunnel vision;
- overly large excerpts increase uncached input;
- stale revision binding would be unsafe.

The current exact-path/unique-symbol, current-revision, complete-span, bounded-token rules mitigate these risks. Sanitize shows why task relevance must remain an independent certificate.

## Was exploration actually replaced?

Conceptually, the call-1 payload replaces at least one ordinary localization/file-read cycle: locate `/app/eigen.py`, open it, identify the target function, then retain that source in context. The run does not provide an experimental “same model state with and without this excerpt,” so the exact saved call/token count is unknown. It is legitimate to claim **replacement potential**, not measured savings for this task.

Aggregate efficiency does not validate the mechanism. On common-solved tasks GT used six fewer provider calls and substantially fewer total tokens, yet more uncached input, output tokens, and normalized cost. The target-excerpt mechanism needs a focused ablation to show that its bytes replace more expensive exploration.

## Other live mechanisms with credible value but no positive-flip attribution

These mechanisms worked mechanically on common-solved tasks, but the current data cannot credit them with creating a solve:

| Mechanism | Live evidence | What can be claimed |
|---|---|---|
| Caller/definition partition | `caller_contract` and `def_partition`: 3/3 applied | Correct lifecycle on fix-code, schemelike, winning; causal solve effect unknown |
| Covering-red relationship | one natural fire on headless | Bounded test relation reached controller; no ablation |
| Signature delta | six fires across four tasks | GT tracked source-derived interface change; tensor still failed |
| New-file precedent | five natural fires | Existing pattern surfaced mechanically; no positive flip isolated |
| Change surface | 290 fires | Broad operational coverage, not evidence of benefit by count |
| Observed validation/task checks | 71 typed checks across eight tasks | Deterministic feedback existed; causality not isolated |
| Repository context delivery | numerous certified frames on solved tasks | Provider exposure, not model acknowledgement |

Receipt counts are not product value. These rows are candidates for ablation, not success claims.

## Historical positive evidence

Historical Phase2B results found that bounded test feedback reached 116/300 versus a 113/300 baseline, the first positive aggregate delta in seven experimental runs. That result supports the hypothesis that **bounded observed feedback** can create asymmetric value. It does not prove that the current implementation inherited the same gains or that any task in workflow `32163376177` was solved by test feedback.

Historical source: `D:\Groundtruth` Git blob `e07a4846…` (`PHASE2B_RESULTS.md`) and blob `0b7c86bf…` (`PHASE2B_FINAL_REPORT.md`). These are experiment records, not current architecture specifications.

## Required positive-mechanism ablation

Capture an identical pre-GT provider state for a set of explicit-anchor tasks and compare:

1. control view with no GT contribution;
2. exact target anchor only;
3. anchor plus complete current implementation span;
4. anchor/span plus certified callers/tests/types where available.

Keep the model, fingerprint, sampling parameters, tool envelope, action history, and checkout fingerprint identical. Measure the next action, localization/search/read actions, provider calls, uncached evidence tokens, time to first correct edit, final solve, and negative scope expansion. Replay captures must remain free of grader-only material.

Success requires more than the same outcome: the selected frame should eliminate at least one search/read or reduce time to the correct edit without increasing attributable losses.

## Product conclusion

The strongest current positive mechanism is not “the graph” in the abstract. It is **precomposed, certified, task-anchored source context delivered on the existing provider request before exploration begins**. `largest-eigenval` is credible product evidence for that mechanism, but still only one non-matched stochastic flip. The next step is to strengthen it with task relevance and multi-edge callers/tests/types, then isolate it by replay rather than counting another random 20-task outcome.
