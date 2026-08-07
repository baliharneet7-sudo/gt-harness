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
action metadata, tool output, and tool status (transport-local tool-call IDs are
ignored). Therefore duplicate semantic turns may be removed, but two turns
with different Mini-SWE reasoning or return status must both survive. The paid
workflow now enables the bounded deterministic transform at a 70% of the
400,000-character context envelope trigger and a 50% target. It first removes
duplicate turns, then compacts only older turns while retaining the latest two
turns and a typed current-state frame. Below the trigger it preserves the
provider history byte-for-byte (apart from exact duplicate turns). No LLM is
used to summarize. Read observations come from every typed shell segment, not
only a command's primary label, and retain path/range/revision/result hash.

## Regression-hardening contract (2026-08-05)

Validation intent and outcome are separate. `ValidationStatus` is `UNKNOWN`,
`PENDING`, `PASS`, or `FAIL`; PASS/FAIL is legal only when the validator is the
terminal foreground segment that owns the shell action's return status. A
verifier mentioned by `cat`, a background check, a validator followed by
`echo`, or a validator piped into a reporter without mechanically proven
`pipefail` remains UNKNOWN/PENDING and cannot create or clear a certificate.

The shared shell parser preserves top-level newlines, treats heredoc bodies and
interpreter `-c`/`-e` programs as opaque, and derives targets only from parsed
operands/redirections. It never regex-scans raw source or diagnostic text into
typed targets. Unsupported syntax abstains to `OTHER`/PASS.

When compaction is disabled, the compiler is observation-only: it may account
facts but must not deduplicate turns, append a user state frame, or change any
provider message. Missing facts are `no_compaction_controller_only`.
Exact-turn deduplication and bounded state frames belong only to the separately
gated compaction transform. Read identity canonicalizes `/app/path` and
relative paths and excludes output hashes from the identity.

The receipt hashes Mini-SWE's provider-prepared message list after private
`extra` metadata is removed/reordered. No model marker is required.
`provider_request_hash_coverage` must be 1.0. With compaction enabled, view
changes are permitted only at the deterministic threshold and must report
duplicate removal or bounded old-turn elision; unique reasoning removal,
unaccounted facts, and duplicate evidence remain failures.

`integration_mode` is the single host switch: `off` disables GT behavior,
`audit` permits private accounting but preserves provider history and
downgrades intervention to SHADOW, and `active` enables grounded one-shot
delivery. The paid workflow is explicitly ACTIVE + SHADOW preflight + bounded
deterministic compaction + executable completion checks + progress control.
Harbor's task-owned `agent.timeout_sec` is resolved from the exported
`task.toml` and passed unchanged to the agent; a small reserve exits cleanly
before Harbor's outer cancellation. A disabled task-start advisory is resolved
at action zero and may not leak into call two. `newfile_precedent` is one-shot
per task.

## Outcome-preservation lifecycle (2026-08-06)

Reward and solve are not interchangeable. The official verifier reward is
reported separately from `uncensored_resolved`; a rewarded run with an outer
Harbor exception is a censored salvage witness and cannot count as a preserved
solve. Internal clean exhaustion (`LimitsExceeded`, step/cost cap, or the
engine's deadline-reserve exit) is recorded separately and is not mislabeled as
an outer censor when Harbor still receives a normal result.

Completion control is deliberately fail-open. The task contract first removes
Terminal-Bench's host workflow text. Only a complete set of mechanically
equivalent predicates can produce a certificate. Each predicate is executed
privately at one workspace revision; a current all-pass certificate emits the
existing submit marker exactly once and cancels the pre-decided suffix. Any
uncovered obligation, timeout, ambiguity, stale revision, or failed predicate
continues the model loop. Completion probes and auto-submit attempts are
included in `effective_actions`, so controller savings cannot be hidden as
model-action savings.

Progress control records repeated identical observations at three occurrences,
alternating cycles at six, and budget risk near 80% of the step limit. It is
controller state, not generic model advice, and does not block a command by
itself. Context compaction similarly preserves the complete audit history and
changes only the provider view when the bounded threshold is exceeded.

The archived `31068690296` treatment remains rejected evidence: official reward
was 9/10, but uncensored resolved was 8/10 because `write-compressor` hit the
outer 900-second timeout. The corrected archived replay identifies that the
task had already satisfied both real obligations before the timeout; the new
certificate/auto-submit path is provider-free proven but still needs an
authorized matched smoke. The 89-task run remains blocked until outcome
preservation and repeated outcome-first efficiency gates pass.

## Post-smoke semantic hardening (workflow 31068690296)

Paid workflow `31068690296` on `b0c7760` is diagnostic evidence, not an
approved treatment. Outcomes matched the frozen ten-task baseline at 9/10 and
aggregate resources fell, but the correctness/efficiency gate failed: six
solved tasks had a positive resource dimension, `write-compressor` newly hit
Harbor's 900-second outer timeout, and only four of six provider payloads were
semantically valid. Do not cite this run as proof that GT improves outcomes.

The two invalid visible payloads exposed permanent classification rules:

- serialized/model/data artifacts such as `.pkl`, `.npy`, `.npz`, `.pt`,
  `.parquet`, `.h5`, `.onnx`, and `.wasm` are derived artifacts. They cannot
  advance source revision, increase validation debt, or appear as authored
  source in a provider payload;
- `newfile_precedent` requires a non-empty sibling and deterministically ranks
  semantically related stems. An empty package marker such as `__init__.py` is
  not a concrete precedent when a related implementation exists, and the
  feature abstains when it is the only candidate.

Replay also exposed an engine-private path mismatch: task deliverables named as
`/app/path` must canonicalize to the sensor's relative `path`. A required
`/app/report.jsonl` is a deliverable, never source revision. Finally, replay
requires a certificate only for an attributable terminal declared validator;
an un-attributable pipeline is validation intent, not a lost certificate.

The run produced and applied 405 effects and naturally fired 12/17 feature IDs.
The five absent IDs (`covering_red`, `GT_HYPOTHESIS`, `recovery`,
`GT_SS_SUBMIT_RED`, and `submit_refusal`) lacked their exact grounded failure
triggers. Provider-free proof still covers all 17 paths. All 372 provider calls
were exactly hashed; SHADOW preflight made 397/397 PASS decisions; context
transformation, batch interruption, late delivery, and predictive delivery
were all zero. The 89-task run remains blocked, and another paid smoke requires
separate authorization after the repaired commit passes the exact gate.

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

## Feature-applicability and repository-substrate rule (2026-08-06)

Do not report every absent paid-run feature as an absent task trigger. Classify
each ID as `fired_when_eligible`, `correct_abstention`, `trigger_absent`,
`ambiguous_evidence`, `substrate_unavailable`, or `missed_trigger`. Every
evaluation records a reason code and evidence hash; an eligible event without
an effect is a release failure, and a fired feature without an eligible event
is a false fire.

Corrected smoke `31136099371` had 38/38 repository refreshes
`index_unavailable`. Therefore its absent `caller_contract` and
`def_partition` were substrate failures, not proven natural abstentions.
`recovery` and `signature_delta` had no exact repeated-failure/signature-change
event and were legitimate trigger absences. The same smoke emitted 100
localization/reslot receipts but only four concrete anchors; do not cite the
other 96 as useful localization.

The paid workflow must install the vendored GroundTruth wheel, export the
pinned `GT_INDEX_BINARY`, and run `scripts/verify_gt_index_runtime.py` before
provider use. Readiness requires actual binary execution, SQLite integrity,
definition nodes, and a certified directed `CALLS` edge. Import availability
alone is insufficient.

Search text may produce localization only when typed command scope and output
anchors are deterministic. It never certifies definitions or callers.
`def_partition` uses separate graph definition/reference roles;
`caller_contract` uses only directed `CALLS` edges with confidence >= 0.95,
`CERTIFIED` trust, and one candidate. Missing or ambiguous evidence abstains.

Provider facts have one delivery window. Compatible facts from action N may be
coalesced in call N+1; an unselected fact remains controller state and is
explicitly suppressed from provider delivery. It may not leak into call N+2.
Each decision frame has unique claim IDs and unique fact text.

## Regression repair after workflow 31078501162 (2026-08-06)

Workflow `31078501162` is rejected evidence: GT-on resolved 7/10 against the
frozen 9/10 baseline. `llm-inference-batching-scheduler` exhausted 100 steps;
`write-compressor` reached the provider context limit. The failures exposed
four controller defects, not missing 17-feature triggers:

1. line-local deliverable parsing could label an input as the output and miss
   wrapped output paths;
2. novelty could clear `BUDGET_RISK` even when no source or required output
   changed;
3. the provider compactor could delete distinct assistant reasoning while
   reporting zero unique-reasoning removal; and
4. no exact provider-prepared request budget stopped an overflow before
   `model.query()`.

The repaired contract is permanent. Task paths are first normalized into
typed `TaskResource` rows (`INPUT`, `OUTPUT`, `REFERENCE`, `EXECUTABLE`, or
`UNKNOWN`). Only high-confidence outputs become task deliverables. Confirmed
outputs may produce private `test -s` progress probes, but those probes cover
no normative obligation and can never make a partial completion plan eligible
for auto-submit.

Provider compaction preserves every assistant content and reasoning field.
It bounds oversized tool observations (including the newest observation),
represents exact duplicate results append-only, and may clear only old tool
bodies to hash/return-code receipts. It does not inject a generic state frame.
Every exact provider-prepared request is measured before `model.query()` with
a configured hard headroom. An over-budget request is not sent, no pending
guidance is confirmed as delivered, and the exit is recorded as internal
`ContextBudgetExhausted`, not an outer censor.

`BUDGET_RISK` is monotonic until authored source or a confirmed task output
changes. Scratch, cache, derived-artifact, and observation novelty cannot clear
it. Receipts now expose bounded-observation counts/chars, duplicate-result
representation, cleared old tool results, provider budget/headroom, exact
append-stable provider-prefix metrics, completion probes, and task-progress
changes. These repairs are provider-free implementation proof only. They do
not restore the 9/10 baseline until an authorized matched smoke passes; the
89-task run remains blocked.
