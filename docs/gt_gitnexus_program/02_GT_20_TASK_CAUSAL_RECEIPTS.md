# 02 — Causal receipts for the current 20 tasks

## Scope and evidentiary rule

This audit joins the frozen local GT-off cohort at `D:\gt_runs\miniswe_tb2_gtoff_20260731\merged_local.json` to GT-on workflow `32163376177` (`e423c87`). The GT-on row data come from `D:\tmp\run32163376177-merged\merged.json`, `deep_metrics_certified_full.json`, `feature_lifecycle_report.json`, and the task receipts/trajectories below `D:\tmp\run32163376177\`.

The outcome join is **descriptive, not a controlled causal A/B**. Although the model catalog name is the same, the frozen GT-off trajectories record fingerprint `fp_a18…`, while GT-on records `a26a7955944dc5c60445bff77fac9c8e`; their initial provider views also differ. At temperature 1, one trial per arm cannot identify model variance. “Model action changed” is therefore `UNKNOWN` for every task unless a decision-level counterfactual exists; none does.

The verifier reward is used only after execution to label solved/unsolved. It was not and may never be used to construct GT evidence.

## Common transition findings

For all 20 tasks, the receipts establish:

1. Repository intelligence was requested and the task was source-backed.
2. Repository transfer, graph construction, schema validation, and dense-backend initialization succeeded. Every task has nonzero graph nodes/edges; dense-backend invalid-task count is zero.
3. Candidate evidence was generated and some GT surface was selected and placed in a provider request.
4. Persistent state was applicable, bootstrapped once, repeatedly compiled/preflighted/postflighted, and rebased when necessary.
5. Postflight ran at aggregate scale, but a successful lifecycle aggregate does not prove that every individual semantic fact was useful or that every terminal effect was consumed.

Two task-specific qualifications matter:

- `largest-eigenval` and `portfolio-optimization` failed the analytical repository-intelligence gate only because `material_frontier_not_delivered`; the graph/dense substrate itself was available.
- `count-dataset-tokens` and `llm-inference-batching-scheduler` had provider payloads, but their delivery certificates were invalid because a changing decisive fact reused a provider claim identity.

## Per-task receipt ledger

`RI` is the run's analytical repository-intelligence status; `delivery` is the authoritative provider-delivery certificate; `PES` is persistent execution state. `Checks` is the central receipt's structurally classified check-action count, not a claim that the verifier's hidden checks ran. “Release defect” is exact or normalized from `treatment_release_failures`.

| Task | GT-off → GT-on | RI | Deliveries / cert | PES | Checks | Release defect at `e423c87` | Outcome bucket |
|---|---:|---|---:|---|---:|---|---|
| cobol-modernization | 1 → 1 | PASS | 13 / PASS | PASS | 0 | contribution task-usage mismatch | BOTH SOLVE |
| count-dataset-tokens | 0 → 0 | PASS | 10 / **FAIL** | PASS | 0 | duplicate decisive claim | BOTH FAIL |
| extract-elf | 1 → 0 | PASS | 26 / PASS | PASS | 4 | terminal effects unapplied; accountability/FK mismatch | BASELINE ONLY |
| feal-linear-cryptanalysis | 1 → 1 | PASS | 14 / PASS | PASS | 0 | contribution task-usage mismatch | BOTH SOLVE |
| fix-code-vulnerability | 1 → 1 | PASS | 8 / PASS | PASS | 4 | contribution task-usage mismatch | BOTH SOLVE |
| headless-terminal | 1 → 1 | PASS | 9 / PASS | PASS | 7 | none | BOTH SOLVE |
| largest-eigenval | 0 → 1 | **FAIL: frontier** | 4 / PASS | PASS | 10 | contribution task-usage mismatch | GT ONLY |
| llm-inference-batching-scheduler | 1 → 1 | PASS | 11 / **FAIL** | PASS | 0 | two duplicate decisive claims; task-usage mismatch | BOTH SOLVE |
| mcmc-sampling-stan | 1 → 1 | PASS | 10 / PASS | PASS | 0 | none | BOTH SOLVE |
| portfolio-optimization | 1 → 1 | **FAIL: frontier** | 11 / PASS | PASS | 8 | contribution task-usage mismatch | BOTH SOLVE |
| prove-plus-comm | 1 → 1 | PASS | 6 / PASS | PASS | 0 | none | BOTH SOLVE |
| qemu-alpine-ssh | 1 → 1 | PASS | 2 / PASS | PASS | 0 | none | BOTH SOLVE |
| regex-chess | 1 → 1 | PASS | 14 / PASS | PASS | 0 | contribution task-usage mismatch | BOTH SOLVE |
| sanitize-git-repo | 1 → 0 | PASS | 31 / PASS | PASS | 10 | terminal effects unapplied; accountability/FK and task-usage mismatch | BASELINE ONLY |
| schemelike-metacircular-eval | 1 → 1 | PASS | 32 / PASS | PASS | 0 | contribution task-usage mismatch | BOTH SOLVE |
| torch-pipeline-parallelism | 0 → 0 | PASS | 3 / PASS | PASS | 5 | none | BOTH FAIL |
| torch-tensor-parallelism | 1 → 0 | PASS | 7 / PASS | PASS | 23 | terminal effects unapplied; accountability/FK mismatch | BASELINE ONLY |
| video-processing | 1 → 0 | PASS | 9 / PASS | PASS | 0 | none | BASELINE ONLY |
| winning-avg-corewars | 1 → 1 | PASS | 17 / PASS | PASS | 0 | contribution task-usage mismatch | BOTH SOLVE |
| write-compressor | 1 → 1 | PASS | 6 / PASS | PASS | 0 | none | BOTH SOLVE |

Totals: 13 BOTH SOLVE, 1 GT ONLY, 4 BASELINE ONLY, and 2 BOTH FAIL; GT-on solved 14/20 versus the frozen cohort's 17/20. All 20 were graded and none was censored.

## Transition-by-transition answer

The requested causal chain cannot honestly be collapsed to a single YES. These are the strongest supported values:

| Transition | Result | Evidence and limitation |
|---|---|---|
| RI requested? | YES, 20/20 | Treatment config and applicability fields |
| RI successfully built? | YES for graph substrate, 20/20 | Valid schema, nonzero nodes/edges; two later frontier failures must remain distinct |
| Retrieval available? | YES, 20/20 | Pinned dense backend reported available; no invalid dense task |
| Candidate evidence generated? | YES, 20/20 | Every task has visible deliveries and contribution receipts |
| Candidate evidence certified? | PARTIAL | Graph/semantic facts carry certificates; relevance and all terminal effect accounting did not universally pass |
| Evidence selected? | YES, 20/20 | At least 2 and up to 32 visible deliveries per task |
| Provider delivery attempted? | YES, 20/20 | Provider request hashes and changed indices exist |
| Delivery certificate valid? | YES 18 / NO 2 | Duplicate-claim failures on count and LLM batching |
| Model actually received evidence? | YES for certified rows; uncertified exposure exists on the other two | Exact provider-view/request hashes prove visibility, not comprehension |
| Model action changed because of evidence? | UNKNOWN, 20/20 | No same-state counterfactual; call-1 changes are intervention accounting only |
| Repository state changed? | Task-dependent, recorded | Workspace/source revisions and action cycles are receipted |
| Postflight executed? | YES at lifecycle level | 913 postflights; three tasks still had terminal effects after normal consumption |
| Persistent state refreshed? | YES at mechanism level | 194 rebases and no reported stale-final-graph failure; per-fact usefulness remains unproven |
| Subsequent evidence fresh? | CERTIFIED where delivery audit passed; otherwise UNKNOWN | Revision/hash checks are necessary, not sufficient for claim-identity defects |
| Tests/checks run? | YES on 7 tasks by typed check count; zero typed checks on 13 | Counts in table; zero does not mean no useful shell observation occurred |
| Final patch resolved? | YES 14 / NO 6 | Post-hoc official reward only |

## Exact failure patterns

### Delivery identity, not transport, failed on two tasks

Both affected tasks had provider-visible payloads. The failure was that a changing decisive fact retained the same semantic claim key, so the authoritative audit detected a duplicate provider claim. This is bucket **A5 — delivery receipt/certificate failure**, not A4 “not delivered.” Current HEAD changes claim selection in [delivery_audit.py](../../gt_engine/delivery_audit.py), but only a new receipt can close the finding.

### Frontier accounting, not graph availability, failed on two tasks

`material_frontier_not_delivered` means the analytical layer said a material frontier existed but could not prove its rendered delivery. Both tasks had a healthy graph and dense backend, and both still received other repository-context/PES payloads. This is primarily **A4/A5**, not A1 or A2. Current HEAD narrows frontier registration to rendered facts and aligns its revision in [gt_central_agent.py](../../eval/gt_central_agent.py); validation is pending.

### Terminal effect conservation failed on three tasks

`extract-elf`, `sanitize-git-repo`, and `torch-tensor-parallelism` produced final `submit_refusal`, `GT_CERT_DELIVERY`, and `GT_SS_SUBMIT_RED` effects after the normal consumption boundary. The effects existed but were not fully applied or linked through the effect ledger. This is **A7 — postflight lifecycle failure** plus accounting failure. It does not itself prove those effects caused the lost solves. Current HEAD adds a terminal effect flush.

### Contribution budget serialization failed on ten tasks

Ten tasks reported `contribution_task_usage_mismatch`. The payload path worked, but serialized per-task token usage did not conserve the contribution ledger. This invalidates release accounting and efficiency proof; it is not evidence that the model lacked the text. Current HEAD serializes both task token usage and limit in [contributions.py](../../gt_engine/contributions.py).

## Causal classification of outcome flips

| Task | Primary bucket | Secondary bucket | Causal confidence |
|---|---|---|---|
| largest-eigenval (positive) | A10 candidate: correct evidence followed by a good decision | A12 because no counterfactual | **Moderate**, not confirmed |
| extract-elf (negative) | A11/A12: reasoning variance or unobserved cause | A7 terminal accounting; assistive policy overhead | **Low** GT attribution |
| sanitize-git-repo (negative) | A3: correct repository corpus, wrong retrieval/relevance | A9 candidate; over-exploration | **Moderate** GT contribution, not confirmed |
| torch-tensor-parallelism (negative) | A11/A12: wrong convention/approach with insufficient distinguishing evidence | assistive-policy overhead | **Low** GT attribution |
| video-processing (negative) | A8/A12: useful facts did not produce convergence before budget | one unnecessary broad-root return | **Moderate** GT contribution, not sole cause |
| count-dataset-tokens (both fail) | A5 plus unresolved reasoning failure | A12 | **High** on certificate defect; unknown on outcome |
| torch-pipeline-parallelism (both fail) | A12 / missing solve capability | — | **Unknown** |

The task autopsies are in [04_GT_NEGATIVE_FLIP_AUTOPSY.md](04_GT_NEGATIVE_FLIP_AUTOPSY.md) and [05_GT_POSITIVE_FLIP_AUTOPSY.md](05_GT_POSITIVE_FLIP_AUTOPSY.md).

## Required deterministic receipt tests

Before another outcome run, the same 20-task receipt reconstruction must prove:

1. exactly one accountable disposition for every produced effect, including terminal effects;
2. fresh claim identity when a decisive value changes, while unchanged evidence stays deduplicated;
3. separate gates for graph substrate health and material-frontier rendering;
4. contribution token conservation at every call and task total;
5. provider-view hash, request hash, changed index, and first-eligible timing for every visible claim;
6. no direct grader-artifact path and no broad-root search returned outside the explicit convergence states allowed by [AGENTS.md](../../AGENTS.md);
7. a final graph/source fingerprint matching the evidence revision.

These tests can establish integrity. They cannot establish solve causality; that requires decision-level replay or a controlled ablation.
