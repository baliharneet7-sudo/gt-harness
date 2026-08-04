# GT efficiency remediation and proof plan

Status: implemented locally through the provider-free gate; GitHub canary and
repeated live proof remain pending. Confidence in the code-level root cause is
high. Confidence that the treatment now beats GT-off is unknown until the
live paired gates pass.

## 1. Strongest conclusion

The previous all-17 treatment was not an efficiency mechanism. It was an
over-intervention mechanism. Run `30869649342` sent 94 advisories (11,341
characters) into model context. Twenty-three of those advisories told the model
to repair syntax immediately after syntax had passed. Non-actionable task
obligations, localization receipts, precedent receipts, and certification
receipts were also surfaced. Because every later API request resends the full
conversation, each unnecessary advisory creates cumulative input-token cost
and can redirect the search/edit trajectory. This is sufficient to explain the
large positive per-task deltas without blaming private bookkeeping.

The old aggregate comparison also understated failure. A task that stops early
or is cancelled can use fewer tokens while producing no solution. Resource
reduction is admissible only after outcome preservation; censored tasks are
automatic gate failures.

## 2. Deterministic SWE lifecycle (no ideation stage)

The implementation follows a deterministic evidence pipeline:

`TASK_STARTED -> CONTRACT_CAPTURED -> BEHAVIOR_OBSERVED -> LOCATION_ANCHORED
-> IMPACT_CAPTURED -> WORKSPACE_EDITED -> STATIC_VALIDATED ->
FOCUSED_CHECK_VALIDATED -> REGRESSION_VALIDATED -> CHANGE_SURFACE_CERTIFIED ->
SUBMIT_READY`

This choice matches the strongest relevant agent research:

- [Agentless](https://arxiv.org/abs/2407.01489) decomposes repair into
  hierarchical localization, patch generation, and validation without an
  autonomous planning/ideation layer.
- [AutoCodeRover](https://arxiv.org/abs/2404.05427) uses program structure and
  test evidence to make localization more precise.
- [SWE-agent](https://arxiv.org/abs/2405.15793) attributes material performance
  to a constrained agent-computer interface; its
  [official ACI documentation](https://github.com/SWE-agent/SWE-agent/blob/main/docs/background/aci.md)
  emphasizes concise search output and automatic lint feedback at edit time.
- [SWE-Edit](https://arxiv.org/abs/2604.26102) reports that editing performance
  and cost depend on how context is coupled to the model. That supports keeping
  lifecycle facts private unless they change the next action.

These sources do not prove this GT implementation is efficient. They justify
the lifecycle and context-minimization hypotheses that the experiment must
test.

## 3. Feature changes

| Feature | Revised trigger/payload | Visibility |
|---|---|---|
| obligations | non-empty task contract at task start | private |
| localization / GT_LOC_RESLOT | non-empty search evidence at the search boundary | private |
| def_partition | definition/reference evidence in search output | private |
| caller_contract | caller/reference evidence from search, not a generic edit | private |
| newfile_precedent | a new file only after precedent evidence was observed | private |
| GT_CHANGE_SURFACE | every real workspace revision change with created/modified/deleted paths | private |
| GT_PATCH_DELTA | every non-empty changed-path surface | private |
| signature_delta | signature-shaped edit plus a real changed path | visible only when actionable |
| syntax_result / GT_EDIT_CHECK | pass and fail both receipted; only a concrete failure is visible | failed FACT only |
| covering_red | non-zero recognized check, labelled reproduction or post-edit | visible, deduplicated |
| recovery | same normalized failure fingerprint repeats | visible, deduplicated |
| GT_HYPOTHESIS | deterministic failure-state transition ID; never model ideation | private |
| submit_refusal / GT_SS_SUBMIT_RED | current-revision grounded failure at submit; one hold maximum | submit message only |
| GT_CERT_DELIVERY | current check counts and `validated`, `blocked`, or `unverified`; never implies success without evidence | private |

The provider-facing allowlist is now only failed `syntax_result`,
`covering_red`, deterministic `recovery`, anchored `signature_delta`, and
`submit_refusal`. A successful lint, a CAP receipt, or a non-actionable FACT
cannot become guidance.

Deduplication is by feature and workspace revision. Treatment is capped at four
guidance events and 640 guidance characters per task, with at most one advisory
per action. Ordinary guidance says `Runtime evidence:` and does not tell the
model to resubmit. Only a real submit hold carries resubmit language. The
separate lint injection that previously duplicated syntax guidance has been
removed.

Ordinary guidance is transient. It is prepared only after the triggering tool
observation, included in exactly the next model request, and then omitted from
durable conversation history. Receipt-v2 records the evidence action, the call
after which it was prepared, and the call before which it was delivered. This
prevents prediction (delivery before evidence), late delivery (after the next
decision), and cumulative re-sending on unrelated later decisions. Competing
same-turn candidates are prioritized once and suppressed; they are not queued
for stale delivery.

## 4. Deep metrics and causal gates

The same trajectory extractor is used for GT-off, shadow, and treatment. It
records:

- outcome, exit status, and censoring;
- input, output, total, cache-hit, and uncached-input tokens;
- provider and normalized cost;
- API calls, assistant steps, tool actions, and no-action responses;
- search, read, edit, check, submit, and other command counts;
- successful/failed actions, exact repeated commands, and a wasted-action
  proxy;
- steps to first search/read/edit/check/submit;
- context and model-output characters;
- guidance delivered/candidates/suppressed and L1/L2/L3 causal ladder counts
  when a central receipt is present;
- lifecycle boundaries from receipt-v2.

The comparator writes `deep_metrics_baseline.json`,
`deep_metrics_shadow.json`, `deep_metrics_treatment.json`, `deep_delta.json`,
and `DEEP_DELTA.md`. Every delta is `later arm - earlier arm`; a positive
resource delta is bad.

The strict per-task Pareto gate applies only where both arms solved the task:
no positive delta in total tokens, API calls, tool actions, assistant steps, or
normalized cost, and at least one strict improvement. Any baseline solve lost
by treatment fails the experiment. Any treatment censoring fails the
experiment. Lower resource use caused by failure never passes.

## 5. Termination and receipt integrity

The workflow now fixes the budgets at 100 assistant calls, 900 seconds for the
model loop, 120 seconds per model request, and the existing per-command limit.
Step, cost, wall, and request limits receive distinct exit statuses. The agent
always writes a receipt-v2 partial trajectory with `censored=true` and a reason.
This directly addresses the schemelike long-tail problem without mislabelling a
cut-off run as an efficiency win.

## 6. Execution sequence

1. Provider-free unit/integration tests and the forced all-17 census must pass.
2. Run a three-task GitHub treatment canary on
   `break-filter-js-from-html`, `write-compressor`, and
   `llm-inference-batching-scheduler`, the clearest prior regressions.
3. Require three verifier results, receipt-v2, healthy sensors, valid payload
   boundaries, no duplicate advisory, no private feature-name leak, and no
   censoring.
4. Run all ten tasks in shadow. This measures host-only observation overhead
   without model-visible guidance.
5. Run all ten tasks in treatment.
6. Compare frozen GT-off to shadow, shadow to treatment, and frozen GT-off to
   treatment with the shared extractor.
7. Repeat shadow and treatment three times and use task-level medians. Report
   all repetitions; do not discard bad or censored trials.
8. Unblock the 89-task workflow only if all expected artifacts exist, no solve
   regresses, no treatment task is censored, the strict per-task Pareto gate
   passes for every comparable solve, and guidance reaches L2/L3 often enough
   to demonstrate behavioral use rather than receipt activity alone.

The 89-task run remains blocked. The next authorized live action is the
three-task GitHub treatment canary, not a local Docker run and not a full
matrix.

## 7. Implemented files

- `gt_engine/central_runtime.py`: feature boundaries, private/visible policy,
  deduplication, budgets, lifecycle and action counters.
- `eval/gt_central_agent.py`: one-advisory path, receipt-v2 metrics, request and
  wall timeouts, censored partial receipts.
- `gt_engine/deep_metrics.py` and `scripts/central_deep_metrics.py`: shared
  extraction and strict comparison.
- `.github/workflows/tb2_miniswe_central.yml`: explicit budgets, deep metric
  artifact, expanded merge telemetry.
- `tests/test_gt_central_runtime.py`, `tests/test_gt_central_agent.py`, and
  `tests/test_gt_deep_metrics.py`: boundary, deduplication, timeout, metrics,
  censoring, and Pareto proofs.

The provider-free timing census additionally reports
`ALL_17_TIMING_VALID`, `ALL_GUIDANCE_ON_TIME`, and `ALL_17_DELIVERABLE`.

## 8. Live canary status

Implementation commit `27c2652` and preflight-bound commit `eb0aaf2` were
pushed to `inline-engine`. GitHub run `30875492432` was cancelled while still
in provider preflight after the request exceeded the agent's 120-second budget;
zero task jobs started. The workflow was then fixed to terminate preflight as a
process after 150 seconds, rather than leaving an HTTP worker alive.

The bounded retry, GitHub run `30875688484`, ended at that 150-second deadline
with exit code 124. Again, dataset enumeration and all task jobs were skipped.
This proves the preflight termination control works. It provides no benchmark,
trajectory, feature-timing, or delta evidence because the provider returned no
response and no task container ran.

Remaining TODOs:

1. When the configured provider responds inside the bounded preflight window,
   dispatch the same three-task treatment canary once.
2. Audit 3/3 verifier outputs, receipt-v2, transient decision windows, feature
   payload/boundary timing, censorship, and per-task deep metrics.
3. Only after that gate passes, run the ten-task shadow and treatment arms.
4. Repeat each arm three times, compute task-level medians, and apply the strict
   outcome-first Pareto gate.
5. Keep the 89-task workflow blocked until every prior gate passes.
