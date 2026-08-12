# DeepSWE v1.1 GT-on smoke — run 31557391617

## Status

The ten task jobs completed through the Pier runner and all nine executable
task environments reached a normal task result. The workflow's `merge` job
failed in reporting code after task completion because an optional
`preemptive_retrieval.dense_backend` field was `null`. This was an
instrumentation failure, not a Pier/Harbor or GT execution failure. The merge
logic was repaired in commit `7166e33`; the paid tasks were not rerun.

One task (`katex-multicolumn-array-spans`) stopped before agent execution due
Docker Hub rate limiting (`toomanyrequests`). It is censored infrastructure,
not a solve or a GT regression.

## Verifier results recovered from task artifacts

| Task | Reward | Exit | Calls | Actions | Tokens | GT deliveries | Candidates | Suppressed |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| abs-module-cache-flags | 1 | Submitted | 168 | 168 | 13,525,938 | 1 | 18 | 17 |
| abs-stepped-slices | 0 | Submitted | 156 | 156 | 12,551,926 | 1 | 25 | 24 |
| adaptix-name-mapping-aliases | 1 | Submitted | 195 | 195 | 24,238,654 | 1 | 33 | 32 |
| aiomonitor-task-snapshots-diff | 0 | Submitted | 163 | 163 | 15,106,056 | 2 | 19 | 17 |
| arktype-json-schema-refs-dependencies | 0 | ContextBudgetExhausted | 170 | 170 | 20,213,737 | 0 | 0 | 0 |
| awilix-async-container-initialization | 1 | Submitted | 117 | 117 | 11,609,613 | 1 | 10 | 9 |
| boa-hierarchical-evaluation-cancellation | 0 | ContextBudgetExhausted | 216 | 216 | 29,113,762 | 2 | 84 | 82 |
| csstree-shorthand-expansion-compression | 1 | Submitted | 157 | 157 | 17,676,845 | 2 | 9 | 7 |
| fd-deterministic-multi-key-sorting | 0 | Submitted | 108 | 111 | 9,249,446 | 1 | 8 | 7 |
| katex-multicolumn-array-spans | censored | Docker Hub rate limit | — | — | — | — | — | — |

Recovered reward is **4/9 executable tasks**, with one infrastructure-censored
task. This is a diagnostic GT-on smoke, not a baseline comparison and not
evidence of an end-to-end uplift.

## Interpretation

The Pier/Harbor boundary worked: no provider preflight failure, missing Pier
hook, result-type mismatch, or central-agent import failure occurred. The
remaining blockers are outcome/resource issues: two tasks hit the configured
provider context budget, and one environment was unavailable because of a
registry rate limit. The workflow also needs a contemporaneous GT-off arm
before any causal claim.

## Next order

1. Use the repaired merge code to produce the report on the next authorized
   run; do not rerun this paid task set merely for the reporting defect.
2. Decide whether the DeepSWE smoke budget should enable the existing bounded
   compaction path; this must be a controlled policy change, not a silent
   retuning of GT after seeing outcomes.
3. Run a matched GT-off ten-task arm with the same v1.1 Pier contract, model,
   limits, and task list, then compare reward, uncensored resolution, tokens,
   calls, actions, and context failures.
4. Keep the 113-task benchmark blocked until the matched outcome gate passes.
