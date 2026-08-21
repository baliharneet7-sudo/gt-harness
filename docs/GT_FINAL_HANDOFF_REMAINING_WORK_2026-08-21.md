# GroundTruth Final Handoff — Remaining Work

This is the handoff for finishing the release gate. It is deliberately ordered
to avoid another paid 20-task run before integrity is clean.

## Current exact state

- Branch: `baseline-swe-live-lite-v4flash0731`
- Latest intended runtime: `df247ce025315590d759819398cdd72dba01d687`
- Active release prediction: V23, bound to the same full SHA;
- latest complete 20-task run: `32455040841`;
- artifact root: `D:\tmp\run32455040841`;
- merged artifact directory:
  `D:\tmp\run32455040841\tb2-miniswe-central-certified_full-integrated-32455040841-MERGED`.

## Do not rerun yet

Do not spend on another provider run until all of the following are true:

1. count-dataset-tokens graph refresh has a deterministic reproduced fixture;
2. FEAL, regex, and schemelike verifier `InternalServerError` rows are
   classified as provider/verifier failures or repaired as real task failures;
3. censor-state accounting is proven consistent for errored tasks;
4. the exact provider-free gate and release identity pass on the final SHA;
5. a local replay of every downloaded receipt passes current delivery and
   treatment gates;
6. the merge report has 20/20 returned, an explicit censor classification, and
   no hidden denominator reduction.

## Work item 1 — count-dataset-tokens graph refresh

### Observed evidence

Its receipt reports:

- `repository_intelligence.status = failed`;
- `persistent_graph_not_current`;
- `refresh_timeout`;
- `graph_missing`;
- `source_revision_missing`;
- `graph_not_current`;
- `repository_intelligence_invalid`.

The task still returned a task job successfully, but the treatment is invalid.

### Required diagnosis

1. Extract the count task's central receipt, runtime observation, source mirror,
   graph manifest, and index logs.
2. Determine whether the timeout occurred during source capture, index build,
   publication, graph validation, or postflight rebase.
3. Reproduce the exact source transition with a deterministic fixture.
4. Assert that a failed refresh cannot serve the previous graph as current.
5. Assert that a successful refresh publishes graph and manifest atomically and
   binds both to the same source revision.
6. Replay the receipt through the current release gate.

### Acceptance criteria

- no refresh timeout on the reproduced transition;
- graph status is either current and certified or explicitly unavailable;
- no stale graph evidence is delivered;
- count receipt passes repository-intelligence and treatment-release gates.

## Work item 2 — verifier InternalServerError classification

Affected tasks: FEAL, regex-chess, and schemelike-metacircular-eval.

### Required diagnosis

1. Inspect each task artifact's `harbor-budget` result, verifier output,
   runtime observation, trajectory, and central receipt.
2. Separate provider failure, verifier service failure, task-container failure,
   model failure, and GT receipt failure.
3. Verify whether the task produced a final patch before the error.
4. Verify whether the error is retryable infrastructure or a deterministic
   verifier response.
5. Ensure the merge script records the state as censored/error rather than
   silently converting it into unsolved or solved.

### Acceptance criteria

- every `InternalServerError` has a typed root-cause bucket;
- the merge summary reports returned, graded, errored, and censored counts
  consistently;
- no verifier error is used in causal solve-flip accounting;
- a retry policy is explicit and does not duplicate paid task attempts without
  authorization.

## Work item 3 — receipt replay and release-gate audit

Run current audits against every downloaded task receipt from `32455040841`.
Record, per task:

- repository applicability and graph freshness;
- dense backend status;
- persistent-state lifecycle;
- delivery failures;
- task-artifact integrity;
- verifier/censor state;
- prediction identity;
- final release disposition.

The FEAL certificate fix must be checked on a newly generated receipt, not only
the reconstructed old receipt.

## Work item 4 — efficiency and regression accounting

Do not claim causal GT regressions from the frozen reward-only baseline. For the
three ordinary baseline-only losses in the latest run (sanitize, tensor, video):

1. retain the exact GT trajectory;
2. obtain a matched baseline trajectory or a mechanism ablation;
3. identify the first meaningful divergence;
4. classify GT delivery, state, infrastructure, model variance, or unknown;
5. compare calls, uncached input, total tokens, cost, failed actions, tests, and
   repeated commands.

The latest run already shows high-cost trajectories and must not be optimized by
globally disabling GT. Reduce only demonstrated redundant operations.

## Work item 5 — authoritative release sequence

After work items 1–3 pass:

1. commit the final fix;
2. create a new prediction version if runtime changes after prediction freeze;
3. update the active release manifest hashes and full SHA;
4. push the full SHA;
5. run provider-free certification;
6. run release identity and frozen-plan checks;
7. verify the task matrix contains exactly the frozen 20 tasks;
8. run one and only one paid GT-on 20-task dispatch with `parallel=20`;
9. wait for all 20 task jobs;
10. inspect the merge artifact before making any performance claim.

## Evidence rules for the next run

- No short commit SHA in workflow `ref` inputs.
- No random cohort or arbitrary task subset.
- No additional canary after the authorized run unless separately approved.
- Provider, model, and route identity must come from the workflow inputs and
  receipts; do not hardcode a new provider in task code.
- Report integrity, outcomes, efficiency, and intervention attribution in
  separate sections.
- A solved reward with an invalid treatment receipt is not a valid GT solve
  claim.
- A verifier `InternalServerError` is not a solve regression.
- Call-1 provider-byte differences are intervention accounting only.

## Final release definition

The product is ready for benchmark expansion only when the same frozen 20-task
run has:

- 20/20 returned;
- explicit graded/error/censored accounting;
- zero unclassified repository-intelligence failures;
- zero unexplained delivery or persistent-state failures;
- current graph state on every applicable task;
- valid provider-value certificates for every visible claim;
- no hidden denominator changes;
- separate causal flip classifications;
- complete per-task receipts and replayable provenance.

