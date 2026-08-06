# GT central-runtime behavioral contract

The active GT-on implementation is `eval.gt_central_agent:MiniSweCentralAgent`.
It is a host-owned engine, not a task-container package, prompt add-on, or
model-invoked sidecar. It owns the model loop and observes every model-selected
command before and after host-side execution.

## What counts as GT working

Keep these states distinct in every audit:

1. **Receipt:** a FACT or CAP payload was produced at the correct action and
   source/workspace revision. This proves observation, not trajectory influence.
2. **Controller consumption/decision:** a registered consumer used the payload
   to change internal state or schedule a deterministic check. A `PASS` is a
   real decision but does not alter the model's next action.
3. **Integrated consequence:** the engine updates operational controller state
   and, when the model needs the result, places one bounded grounded payload in
   the first provider request after the evidence action. Under the separately
   gated `ASSISTIVE_SAFE` preflight mode, a mechanically proven contradiction
   may return the selected action to the model before execution. GT never
   rewrites a command or silently suppresses one.

## Pre-action interface (2026-08-05)

The central agent normalizes every Bash tool call into one typed
`ProposedAction` after model selection and before `environment.exec`. The same
shell segmentation and immutable validation classification are reused by
preflight and postflight. The host applies exactly one mode:

- `OFF`: the historical postflight loop; no preflight evaluation or receipts.
- `SHADOW`: evaluate and receipt every proposal, but execute the original
  command and preserve batch behavior.
- `ASSISTIVE_SAFE`: allow only `PASS`, bounded `AUGMENT`, or grounded
  `RETURN_TO_MODEL`. `REWRITE` and feature-driven `SUPPRESS` are rejected to
  `PASS`. Timeout, exception, ambiguity, low confidence, heuristic evidence,
  stale evidence, or duplicate evidence also degrade to recorded `PASS`.

Read/search batches may continue. In assistive mode a known mutation,
validation, submit, material workspace change, or source-revision
change prevents a pre-decided suffix from executing on stale reasoning. An
`OTHER` action does not split a batch merely because parsing abstained; it
splits only when postflight proves a material change. A generic exploratory
nonzero exit is recorded but is not by itself worth another model call. Each proposal receives
an `ActionCycleReceipt` joining candidate decision, applied disposition,
dispatch, postflight result/revisions, and the next command after a return.

The five evidence-correct postflight-only features remain
`GT_CHANGE_SURFACE`, `signature_delta`, `GT_PATCH_DELTA`, `syntax_result`, and
`covering_red`. The other twelve have explicit two-sided lifecycle placement,
but preflight may use them only when their required evidence already exists.
No feature is moved earlier merely to increase trigger counts.

The paid workflow is deliberately `preflight_mode=shadow`. Do not change it to
`assistive_safe` until provider-free gates and a separately authorized matched
smoke approve intervention behavior.

## Effect provenance (2026-08-04)

`central_receipt.json.features.effect_trace` is an additive provenance ledger.
It links each applied effect to existing state reads and confirmed provider
deliveries without changing routing, prompt selection, timing, or action
execution. `audit_only` means the effect was recorded but no existing
downstream consumer was exercised; it must not be reported as trajectory
influence. `provider_payload` and `existing_engine_actuation` require a
recorded downstream event. `engine_internal_state` records producer-side GT
control work (revision, validation-debt, failure, lifecycle, or trigger
updates) and is distinct from provider delivery. Unknown dispositions fail the
audit.

Private receipts must never be mistaken for an inactive engine. Conversely,
receipt counts must never be claimed as causal help.

## Source-revision model

The engine keeps two revisions: the raw workspace revision (audit) and a
validation-relevant source revision. Caches, compiled objects, binaries, build
products, logs, benchmark output, directories, and background writes never
advance source revision. Task-required deliverables satisfy obligations without
pretending to be source. Validation evidence goes stale only when authored
source changes.

## One validation classifier

Every executed action is classified exactly once in the agent. The immutable
`ValidationClassification` is shared by the feature runtime, the evidence
ledger, the receipt writer, and deep metrics. No component reparses the
command; runtime, ledger, and metrics cannot disagree about the same action.
Submit certificates report real current checks bound to the source revision.

## Active delivery policy

The engine may deliver only new, grounded control evidence that names concrete
anchors (paths, symbols, commands, diagnostics):

- a concrete changed-file syntax failure;
- a real, structurally recognized validation failure;
- the same failure repeating at an unchanged source revision;
- a source-derived signature delta with affected caller evidence;
- a concrete new-file precedent or ranked-context reslot; or
- source-bound validation or submission-risk state naming the exact check.

A fresh syntax failure is delivered before the next available model decision.
In OFF/SHADOW, actions already selected in the same response continue
unchanged; ASSISTIVE_SAFE uses the hybrid stale-batch barrier. Generic
obligations, search echoes, passing syntax checks, and submission certificates
remain private unless they contribute new decision-relevant evidence. CAP
features must apply their own actuator payload rather than copy an owner message.
If the engine cannot name the evidence, the payload stays private.

Every active delivery must be present in the exact final provider request before
`model.query()` begins. Evidence from action N belongs in the first call after
action N; call N+2 is one-step-late. Audit revision, request hash, message index,
non-prediction, deduplication, and next action. Do not re-enable the historical
generic guidance stream; its 94 advisories in run `30869649342` were the
documented context/token regression.

## Deterministic context compiler contract (2026-08-05)

GT is not an advice sidecar. `MiniSweCentralAgent` compiles every provider
request from the durable Mini-SWE history plus typed current controller state.
The compiler may expose only source-backed task facts; it does not reason,
predict intent, invent a plan, ask the model to acknowledge GT, or delete
distinct Mini-SWE reasoning.

Every candidate `ContextFact` receives exactly one replayable disposition in
the request receipt:

- `represented_message`: exact provider-message indices already contain the
  command/result fact, so no duplicate text is added;
- `selected_state_frame`: a current material fact is absent from retained
  history and is emitted once in a bounded declarative frame;
- `controller_only`: revision/control state affects deterministic selection but
  is not useful model text;
- `stale_source_revision`: revision-bound evidence is rejected;
- `state_frame_budget`: a complete fact could not fit and is omitted rather
  than truncated into a misleading fragment.

`candidate_fact_count == accounted_fact_count` must hold on every model call.
Request hash and message indices prove exposure. `next_action_anchor_aligned`
is only a behavioral utilization proxy; it must never be called proof of an
internal model acknowledgement or causal benefit. Causal influence requires a
matched arm/ablation. Effect receipts separately record first-eligible compiler
status (`provider_payload`, `controller_state_considered`,
`stale_state_rejected`, `superseded_before_request`,
`existing_engine_actuation`, `audit_only`, or `no_eligible_model_call`).

Exact-turn deduplication includes assistant content, hidden reasoning content,
tool commands, and tool results. Therefore byte-identical duplicate turns may
be removed, but two turns with different Mini-SWE reasoning must both survive.
Lossy old-turn compaction is disabled in the paid workflow until a matched
ablation proves it preserves outcomes; the compiler and exact accounting still
run on every request. Read observations come from every typed shell segment,
not only a command's primary label, and retain path/range/revision/result hash.

## Provider-free proof

`python -m scripts.central_feature_census` must print all required lines before any paid
run: `ALL_17_PRODUCERS_PROVEN`, `ALL_17_CONSUMERS_PROVEN`,
`ALL_EFFECTS_TIMING_VALID`, `ALL_PAYLOADS_GROUNDED`,
`ALL_17_CONSUMER_PATHS_PROVEN`, `ALL_17_TRIGGERS_PROVEN`,
`ALL_17_PAYLOADS_CONCRETE`, `ALL_17_CONSUMERS_APPLIED`,
`ALL_VISIBLE_PAYLOADS_IN_FIRST_ELIGIBLE_REQUEST`, and `NO_ACTIONS_BLOCKED`.
It must additionally print `ALL_EFFECTS_CONTEXT_ACCOUNTED`.
The census cannot pass on producer receipts alone.
`scripts/central_readiness_audit.py` must print `READY`. The workflow's
provider-free suite must also include `tests/test_gt_preflight.py`.

## Live-run gate

Before any paid smoke, `python scripts/central_pre_smoke_gate.py` must print
`SMOKE_APPROVED` at the intended commit. It fails closed unless the exact paid
workflow timeout, the direct and module census entrypoints, all 17 agent-loop
producer/consumer effects, non-predictive/non-late timing, and non-blocking
submission-risk consumption are proven. Then replay archived trajectories
through the policy and confirm that each effect is reachable only on its
intended lifecycle state. A smoke is confirmation, never exploratory debugging.
The 89-task run remains blocked until outcome preservation and repeated
outcome-first efficiency gates pass.

## Permanent coverage and accounting rule (2026-08-05)

Never write “all 17 features worked” when referring to one stochastic paid
trajectory without checking feature IDs in its receipts. The statements are
different:

- **17 paths proven:** provider-free census and forced-trigger tests exercised
  every producer and consumer path.
- **17 features fired:** the paid receipt set contains at least one receipt for
  every feature ID.
- **17 features consumed:** every produced effect has an applied engine
  effect and an explicit downstream disposition.
- **17 features delivered to the model:** every feature produced a grounded
  model-visible payload and a confirmed provider delivery. This is not the
  normal requirement; many features are correctly engine-private.

In smoke `30976148466`, 15/17 feature IDs fired naturally; `recovery` and
`signature_delta` did not because their exact triggers were absent. The run
still had 361 applied effects, not 36. The 36 count was only model-visible
provider payload effects.

Never equate private with unused. The effect trace must distinguish
`provider_payload`, `existing_engine_actuation`, `engine_internal_state`,
`audit_only`, and `unread_private_state`. `engine_internal_state` proves
deterministic GT work even when no model text was emitted; only an explicit
downstream read, decision-frame contribution, or provider delivery proves
that the work influenced a later decision. The summary must never relabel
producer-side engine work as inert solely because it was not model-visible.

## Final ten-task smoke (2026-08-04)

The repaired treatment smoke is workflow `30954660207` on commit `e7418a7`
(`inline-engine`). All ten jobs completed successfully. The receipt audit found
372 effects produced and applied, with 297 `engine_internal_state`, 11
`existing_engine_actuation`, 48 `audit_only`, and 16 `provider_payload`
effects. There were 14 model payload deliveries, all grounded and in the first
eligible request: 0 late and 0 predictive deliveries.

The final source-precedent boundary is now strict. `newfile_precedent` may fire
only for a regular model-authored validation-relevant source file with a
recognized source suffix, and its payload names only that source trigger and a
source-classified sibling. The ten-task audit found 10/10 valid precedent
payloads and zero cache, binary, generated-output, or task-output paths. The
previous smoke `30952995623` was rejected as evidence because it exposed the
entire workspace-created batch in the payload; do not use it for readiness.

Against the frozen GT-off baseline, the final smoke measured token delta
`-9,135,151` (-31.26%), API-call delta `-51`, assistant-step delta `-53`, and
action delta `-103`. These are a single matched-smoke efficiency signal, not a
causal quality claim. The 89-task run has not been started; dispatch it only
from this commit or a descendant after retaining the receipt audit.

## Context-compiler smoke audit (2026-08-05)

Paid shadow smoke `31061665540` ran commit `a45601f0ba05`. Integration
integrity passed: 334/334 compiler/API calls, 349/349 preflighted actions all
applied as PASS, 5,287/5,287 facts accounted, 339/339 effects accounted, and
21/21 grounded first-eligible deliveries with zero late/predictive payloads,
zero compactions, and zero unique reasoning removal. The smoke naturally fired
11/17 feature IDs; all 17 paths remain provider-free proven.

The efficiency acceptance gate failed despite preserving verifier reward 9/10.
`cobol-modernization` was a new treatment `AgentTimeoutError`,
`schemelike-metacircular-eval` reached the step cap, six solved tasks failed
strict per-task Pareto, and aggregate normalized token cost increased 13.33%.
The 89-task run remains blocked.

Never infer censoring only from `central_receipt.json`: Harbor can terminate the
agent after the last receipt. Shared metrics must consume the adjacent trial
result or frozen merged result and report outer exception type plus agent wall
time.

The smoke exposed 104 shadow candidate returns, all caused by
`edit_target_absent` on normal scratch-file creation or shell edits. That is not
a material contradiction. Current code defaults such proposals to PASS and
rejects legacy absent-target interventions; post-fix replay produces zero
material candidates. Only new mechanically grounded evidence may return to the
model.

GT context accounting includes both active guidance and compiler state frames.
For this smoke the exact totals were 2,337 guidance characters plus 182,536
state-frame characters, not merely 21 delivery receipts. Keep
`gt_context_chars_added`, `context_state_frame_chars_added`, and
`total_gt_context_chars_added` distinct.
