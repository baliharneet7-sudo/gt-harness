# 04 — Negative-flip autopsy

## Causal standard

The four rows below are **raw outcome flips**, not four proven GT-caused regressions. The comparison joins GT-on workflow `32163376177` to the frozen GT-off trajectories below `D:\gt_runs\miniswe_tb2_gtoff_20260731\matrix_cache\`. Both use the `deepseek-v4-flash` catalog name, but provider fingerprints and initial provider views differ; sampling temperature is 1 and there is one trial per arm. This is insufficient for trajectory-level causal identification.

The autopsy uses only the task instruction, workspace/source observations present to the agent, and the agent's own executed results to evaluate decisions. Official reward labels the final outcome post hoc. It does not inspect hidden grader logic or reference solutions to manufacture an explanation.

Causal confidence:

- **CONFIRMED:** same-state replay/ablation or direct deterministic intervention proves the loss.
- **HIGH:** one specific GT action is necessary for the observed divergence and alternatives are implausible.
- **MEDIUM:** timing and mechanism support contribution, but stochastic or independent causes remain.
- **LOW:** only weak temporal association; the failure can be explained without GT.
- **NOT ATTRIBUTABLE:** affirmative evidence excludes GT.

None of the four reaches CONFIRMED or HIGH.

## 1. `extract-elf`

**Outcome:** frozen GT-off solved; GT-on failed. GT-off used 42 actions; GT-on used 66.

### Baseline trajectory

The baseline localized the ELF program-header problem, used `PT_LOAD` virtual addresses (`p_vaddr`), wrote the extraction logic, and cross-checked its JavaScript output against an independently generated Python reconstruction. It converged and submitted.

### GT trajectory and first meaningful divergence

GT-on call 1 received correct, neutral task semantics: ELF x86-64 format and the required `extract.js` and `out.json` deliverables were absent. That evidence did not prescribe an address convention. The GT trajectory later chose a `0x400000 + p_offset`/file-offset-centered mapping and iterated broad variants. The first material divergence is this address-model choice, not the mere presence of GT context.

Three assistive returns occurred later, at calls 7, 16, and 47:

1. a broad `find / ...` search;
2. a direct read of `/logs/agent/provider_query_started.json`;
3. another root/reference/grader-oriented search.

The direct known grader/agent-artifact defense is within the intended safety boundary. Treating an arbitrary root-wide search as equivalently forbidden is not: [AGENTS.md](../../AGENTS.md) permits such a return only at a proven `STALLED`, `CONTRADICTED`, or `BUDGET_RISK` state. These returns added decision cycles after the core mapping error was already underway.

### Evidence quality

- Factual correctness of call-1 evidence: **yes**.
- Relevance: **yes but incomplete**; it identified format/deliverables, not the decisive address semantics.
- Staleness: no evidence of stale graph state.
- Evidence immediately before the wrong address choice: no certified fact establishing the wrong mapping was found.
- Terminal lifecycle: final submit-related effects were produced after the normal consume boundary, causing effect-application/accountability/FK failures.

### Classification

- Primary: **A11 — difference consistent with model variance** or **A12 — insufficient observability**.
- Secondary: **A7 — postflight/terminal lifecycle failure** and assistive-policy overhead.
- GT causal confidence: **LOW**.

### Minimum repair

Do not globally reduce GT influence. Split “direct known grader-artifact path” from “broad root search”; require an explicit convergence-state certificate for the latter. Add a deterministic ELF relation/format composition only if it is derivable from instruction/source/observed execution; otherwise abstain. Add same-state decision replay around the first address-model decision.

## 2. `sanitize-git-repo`

**Outcome:** frozen GT-off solved in 20 actions; GT-on failed after 74 actions.

### Baseline trajectory

The baseline found the five concrete credential/token values across three contaminated files, replaced them, verified the relevant files, and avoided unrelated modifications.

### GT trajectory and first meaningful divergence

GT-on also found the secrets, including the token embedded in data. Its initial provider request, however, combined a real AWS-credential diagnostic from `ray_cluster.yaml` and the task's pytest requirement with unrelated repository context for `baselines/aggregators.py#histogram`, including a source excerpt. That relation was mechanically grounded but not task-relevant.

The trajectory then widened scope: it installed optional dependencies, changed unrelated baseline code/tests to make broader pytest execution pass, and staged/committed the entire worktree with `git add -A`, despite the task's constraint against modifying uncontaminated files. The divergence is scope expansion from targeted sanitization into repository-wide validation repair.

No assistive return was applied on this task, so the loss cannot be blamed on command rejection. The candidate causal mechanism is instead **wrong retrieval/composition and salience**: a high-confidence but irrelevant code relation arrived at the first decision point and the agent subsequently spent substantial effort in that subsystem.

### Evidence quality

- Credential diagnostic: factually correct and highly relevant.
- Histogram relation/excerpt: factually source-backed, but task-irrelevant.
- Completeness: the useful secret evidence did not encode the negative obligation “preserve every uncontaminated file.”
- Staleness: no stale-state evidence.
- Presentation risk: multiple grounded facts shared one authoritative frame without sufficient task-relevance discrimination.
- Terminal lifecycle: the same three terminal effect/accountability failures as `extract-elf`, plus contribution task-usage mismatch.

### Classification

- Primary: **A3 — correct intelligence, wrong retrieval/composition**.
- Secondary: **A9 candidate — delivered evidence may have encouraged a bad scope decision**, plus A7 accounting failure.
- GT causal confidence: **MEDIUM contribution**, not confirmed.

### Minimum repair

Add a relevance-negative certificate: a structural relation cannot enter the initial frame merely because it is high-ranking; it must connect to an instruction anchor, diagnosed file, declared deliverable/check, active change, or certified obligation. Preserve task-owned negative constraints (“do not modify uncontaminated files”) as source-revision-bound invariants and surface a changed-file contradiction before `git add -A` or broad unrelated edits. A regression fixture should prove that the sanitize task cannot select the histogram relation.

## 3. `torch-tensor-parallelism`

**Outcome:** frozen GT-off solved in 41 actions; GT-on failed in 56.

### Baseline trajectory

The baseline implemented the tensor-parallel module and explicitly exercised both weight orientations/shape behavior before submission.

### GT trajectory and first meaningful divergence

GT-on call 1 exposed only that `parallel_linear.py` was required and absent. The trajectory chose and then reinforced a master-weight convention shaped as `[in_features, out_features]`, building its tests around that assumption. The first material divergence is the unverified orientation convention. GT supplied no resolved type, existing consumer, runtime shape, or contract evidence that could discriminate the alternatives.

At call 5 the controller returned `find / -name "python*" ...`. This broad-root search was not a direct grader-path access and delayed discovery of the usable interpreter/venv. It is an efficiency defect and potentially a contributor, but it did not create the weight-orientation assumption.

### Evidence quality

- Delivered call-1 fact: correct but insufficient.
- Relevant semantic evidence missing: expected consumer orientation, constructor/call-site types, runtime shape contract, or an existing implementation pattern.
- Staleness: no stale-state evidence.
- Ranking/presentation: no identified bad repository claim immediately before the convention choice.
- Terminal lifecycle: final submit-related effects were unconsumed/accountability-invalid.

### Classification

- Primary: **A11/A12 — wrong approach under an unresolved convention, with insufficient causal observability**.
- Secondary: assistive-policy overhead and A7 terminal accounting.
- GT causal confidence: **LOW**.

### Minimum repair

Compose resolved signature/type, caller construction, tensor-shape assertions, and runtime-observed shapes into a certified convention record when those facts exist. If the repository/instruction does not distinguish orientation, report unknown rather than bless either shape. Independently repair broad-root search handling.

## 4. `video-processing`

**Outcome:** frozen GT-off solved in 60 actions; GT-on failed at the 100-step limit.

### Baseline trajectory

The baseline produced the required implementation/output and submitted within its budget.

### GT trajectory and first meaningful divergence

GT-on call 1 received correct task semantics: `jump_analyzer.py` and `output.toml` were absent and the example video was present. It eventually produced the public result `[54], [61]`, but continued iterating. At call 63 the controller returned a broad root search for `output.toml`/`*jump*`. The trajectory later spent its final action generating another long video and never submitted.

The key failure is bounded convergence: a candidate output existed, but task state did not transition into an efficient verify-and-submit path before the hard budget. The assistive return consumed an additional provider decision and did not replace exploration with a more targeted deterministic probe.

### Evidence quality

- Initial evidence: correct and relevant, but only structural.
- Model ignored/failed to exploit completion state: plausible, but internal acknowledgement is unobservable.
- Missing controller behavior: a budget-aware proof of deliverable presence plus declared/public validation was not strong enough to terminate further exploration.
- No release-receipt defect was reported for this task; provider delivery and PES lifecycle passed.

### Classification

- Primary: **A8 candidate — delivered evidence did not produce convergence**, or A12.
- Secondary: assistive-policy/budget overhead.
- GT causal confidence: **MEDIUM contribution**, not sole cause.

### Minimum repair

At deterministic budget risk, compile one bounded completion frame from present deliverables, exact observed validation, unresolved predicates, and the single cheapest remaining probe. A returned command must replace an exploratory operation rather than add a provider roundtrip. Add a trajectory invariant: after a candidate deliverable and passing declared check, repeated expensive artifact generation requires a newly observed contradiction.

## Cross-flip findings

### What the four flips do prove

1. GT-on did not preserve solve parity on this one stochastic cohort.
2. Lifecycle/integrity defects co-occurred on three of four negative flips.
3. Two policy failures are reproducible from receipts: broad-root searches were treated like direct grader-artifact access, and a task-irrelevant structural relation reached sanitize's call 1.
4. The completion controller did not prevent video's budget exhaustion.

### What they do not prove

1. They do not prove four GT-caused losses.
2. They do not prove that fingerprint metadata restores comparability.
3. They do not prove that terminal receipt defects changed earlier model decisions.
4. They do not justify making GT passive. The repair target is more selective, more complete intervention at the decision point.

## Required negative-flip test seams

| Seam | Deterministic witness | Required assertion |
|---|---|---|
| Forbidden-path classifier | direct `/logs/...` versus broad `find /` | direct artifact access may return; broad root requires a certified convergence state |
| Retrieval relevance | sanitize instruction + current repository corpus | unrelated histogram relation is not selected for call 1 |
| Negative task constraint | sanitize changed-file set | unrelated edit creates a bounded contradiction before broad stage/submit |
| Convention uncertainty | tensor shape with ambiguous source | GT emits unknown or multiple candidates, never a single invented orientation |
| Completion/budget | video deliverables present + observed check | next frame names only unresolved predicate/cheapest probe; repeated generation is not encouraged |
| Terminal effect conservation | submit as final action | every produced effect has exactly one application/accountability disposition |
| Counterfactual observability | captured pre-GT provider state | replay treatment/no-treatment from the identical state and record first divergent decision |

## Bottom line

The strongest genuine GT defect among the four is sanitize's task-irrelevant initial composition, followed by convergence/budget handling on video and overbroad forbidden-path policy on three tasks. The core wrong answers on extract and tensor are not traceably caused by a false GT fact. The honest current accounting is: **zero confirmed GT-caused negative flips; two medium-confidence GT contributions; two low-confidence attributions; four raw negative outcome flips.**
