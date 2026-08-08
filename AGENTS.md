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

## Native R/Verilog language stage (2026-08-08)

The current branch stages parser-backed R (`.r`) and Verilog (`.v`) support
using pinned upstream Tree-sitter Go bindings (`r-lib/tree-sitter-r v1.3.0`
and `tree-sitter-verilog v1.0.3`). The gt-index specs, grammar-scoped Verilog
name unwrapping, module-instantiation attribution, and provider-free fixtures
are checked in. Redcode (`.red`) and POV-Ray (`.pov`) remain explicit
fail-closed capabilities; no regex parser may claim graph support for them.

This stage is not certified until the Linux provider-free workflow compiles
the cgo bindings and `verify_gt_index_runtime.py` proves R/Verilog definitions,
directed edges, SQLite integrity, and complete source/file-hash coverage. Do
not start a paid smoke from an unverified descendant. A green parser build is
substrate evidence only; regression approval still requires the existing
central census, readiness gate, archived replay, and matched outcome smoke.

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

## Latest outcome gate — workflow 31142998081 (2026-08-06)

Workflow `31142998081` at `5c92a6a` is rejected as an outcome-preserving
treatment: 8/10 verifier rewards versus the frozen GT-off baseline's 9/10.
`schemelike-metacircular-eval` is a new uncensored step-cap loss; the known
GT-off-unsolved `gpt2-codegolf` also remained unsolved. Never call the green
workflow or its aggregate token reduction an improvement.

The integration audit itself passed: every task enabled all 17 features,
304/304 effects were applied, 15 IDs fired naturally, the other two were
legitimate trigger absences, all 459 shadow preflights were PASS, and all five
model-visible payloads were grounded, first-eligible, timely, and
non-predictive. The exact first provider request in the lost task was byte
identical to GT-off, while the temperature-1 first response already differed.
That rules out a first-turn GT payload cause but does not clear the later
bounded context transform as a contributor. Use the archived audit
`details_done/GT_SMOKE_31142998081_OUTCOME_AUDIT_20260806.md`; do a request
diff/replay and a separately authorized ablation before another paid smoke.

## 10/10 versus 8/10 comparison (2026-08-06)

The prior 10/10 GT-on smoke (`31136099371`, `8ab1896`) is real paid evidence,
not a replay. The later 8/10 smoke (`31142998081`, `5c92a6a`) used the same
tasks, model/temperature, agent, active/shadow modes, compaction,
completion/progress controls, step cap, and task-owned budgets. Their initial
schemelike provider request was byte-identical, but the temperature-1 first
model action already differed before any GT-visible evidence.

The repair did not change the compactor, completion controller, or progress
controller. It repaired graph-runtime installation and graph-role semantics,
added applicability accounting, and prevents claims from leaking after their
first eligible provider call. In the lost task both runs rendered the exact
same 135-character `GT_EDIT_CHECK` payload; current graph effects were private
and caused no controller action/state frame. Therefore do not attribute the
observed outcome loss to the repair, and do not dismiss it as proven noise
either. Follow `details_done/GT_ON_10OF10_VS_8OF10_COMPARISON_AND_PLAN_20260806.md`:
first request-diff/fixed-trajectory proof, then a separately authorized
component ablation smoke.

## Provider-free run-diff gate (2026-08-06)

Before interpreting two GT-on smokes, run
`python -m scripts.central_run_diff <left-root> <right-root>`. It is an
offline, fail-closed receipt/trajectory comparator: it reports first divergent
model action, whether that predates visible GT evidence, prepared-request hash
differences, frames, compaction, preflight, and accounting completeness. It
must never call a model or modify an artifact. Both direct and module forms of
`central_replay` are required to work. This gate is in the provider-free and
pre-smoke suites. See
`details_done/GT_PROVIDER_FREE_RUN_DIFF_GATE_20260806.md`.

## GT-on smoke 31145623534 (2026-08-07)

Smoke `31145623534` on `f03cb02` is integrity-valid but efficiency-rejected.
It matched the frozen GT-off outcome at 9/10 official and uncensored resolves
with no outer Harbor exceptions. The former `schemelike-metacircular-eval`
loss returned reward 1, although it reached the 100-step cap before a clean
verifier success; it is uncensored, not a timeout salvage.

All 330 produced effects were applied. Fourteen of 17 feature IDs fired
naturally; `GT_SS_SUBMIT_RED`, `recovery`, and `submit_refusal` had no exact
grounded events, with all paths still provider-free proven. Six grounded
payloads reached their first eligible request (zero late/predictive), all 456
provider requests and all 8,125 context facts were accounted, and no unique
Mini-SWE reasoning was removed. Do not call this a 17-feature-fired smoke.

Efficiency failed on the nine common solved tasks: GT-on used 20,422,063
tokens and 416 API calls, versus GT-off's 20,344,163 and 361 (+77,900 tokens,
+55 calls). The all-ten aggregate is misleading because common-unsolved
`gpt2-codegolf` happened to be cheaper. Do not start 89; first isolate the
large LLM-batching and COBOL expansions with a component ablation. Full audit:
`details_done/GT_SMOKE_31145623534_OUTCOME_AND_INTEGRITY_AUDIT_20260807.md`.
## Semantic-progress and compaction repair (2026-08-07)

The first implementation of the regression repair is provider-free and remains
behind the existing host integration switch. Workspace activity is now
separate from semantic progress: source edits are `patch_attempt`, while only
new task-linked read anchors, new attributable diagnostics, or attributed
validation passes advance `task_progress_changes`. Scratch commands, fixture
resets, derived artifacts, and novel output hashes cannot clear `BUDGET_RISK`.
Receipts expose `activity_events` and `semantic_progress_kinds` separately.

When deterministic compaction clears old tool bodies, the compiler now attaches
one bounded current-state frame to the latest retained tool observation, with
fact IDs and the exact provider message index. It never removes distinct
assistant reasoning, injects a user instruction, or fabricates a fact. If no
tool observation survives, the selected fact is recorded as
`no_safe_delivery_surface` rather than silently claimed as delivered.

Completion predicates now carry dependency paths and cache private probe
results by predicate plus dependency fingerprint; cached observations are
rebased to the current workspace revision before certificate evaluation.
Shell coverage distinguishes `shell_context`, `output_only`,
`opaque_program`, and genuinely `unknown` segments; unsupported syntax still
fails open to `OTHER`/PASS.

These changes have passed the focused GT/progress/provider-view/preflight/
completion/deep-metrics tests, compilation, the central feature census, and
the readiness audit. No paid smoke has been run for this repair. A smoke is
blocked until the full provider-free suite and archived trajectory replay pass;
the paid workflow remains `ACTIVE + SHADOW` and the 89-task run remains
blocked.

## Outcome-preserving efficiency boundary (2026-08-07)

Validation recognition is not task-contract authority. Every validation action
has a typed authority (`NONE`, `CUSTOM_PROBE`, `STANDARD_RUNNER`, `DECLARED`,
or `HOST_SYNTAX`) derived from the shared normalized executable invocation.
Only a `DECLARED` check may create model-visible required-check failure text or
submission debt. Standard-runner failures may update private recovery state;
custom probes remain private. Every required-check receipt must name its
`declared_check_id`, and `required_check_claims_without_declared_id` must be
zero.

Completion is complete-only: a `PARTIAL` plan executes zero private predicates
and cannot produce a certificate. Adaptive action timeout is active-only and
may extend the historical 30-second timeout solely for a high-confidence,
terminal-foreground, literal-timeout `DECLARED` or `STANDARD_RUNNER` command.
It is capped at 120 seconds, 20% of remaining task time, and the deadline
reserve. Ambiguity and dynamic shell expressions keep the default timeout.

Compaction is based on the measured provider-prepared request, not raw history
size. Preserve the exact request while at least 131,072 tokens of reserve
remain (reserve is also capped at 25% of the hard prompt limit). Once required,
create one immutable compacted-checkpoint epoch and append later turns. Refresh
the bounded current-state frame only on a provider-view copy of the latest safe
tool observation; never mutate the checkpoint or freeze stale state into it.
Receipt every epoch and never remove distinct assistant reasoning.

All task-environment executions pass through `HostExecutionRecorder`, including
model actions, sensor manifest/hash/capture calls, syntax and completion probes,
and auto-submit. `effective_task_actions` is the actual execution count minus
host system-information calls; cache hits are separate. Never substitute model
action count for total task work. Deep metrics use schema v2.

Archived replay of run `31190135547` suppresses four non-authoritative visible
failure receipts on two actions, removes 28 partial-plan probe executions while
retaining five probes for the complete write-compressor plan, and projects zero
compaction epochs because reconstructed raw final provider requests retain at
least 211,100 tokens of headroom after a conservative advisory allowance. This
is provider-free policy proof, not a live efficiency claim. See
`details_done/GT_OUTCOME_PRESERVING_EFFICIENCY_IMPLEMENTATION_20260807.md`.

## Repository-intelligence regression boundary (2026-08-08)

GT is the deterministic repository-intelligence layer inside Mini-SWE, not a
sidecar that may be counted as healthy merely because feature receipts exist.
Keep substrate health, retrieval outcome, and provider delivery separate. A
certified current graph is a release requirement. A healthy graph may return
`EMPTY` because no new task-linked fact clears the precision threshold, or
`REPRESENTED` because Mini-SWE history already contains the fact. Those are
accounted abstentions, not substrate failures and not permission to force
generic text. Mini-SWE fails open operationally on a real graph failure so GT
cannot erase a baseline solve; the experiment still fails closed analytically.

`graph.db` is certified evidence, not a boolean file-presence check. Every
build/refresh receipt records source coverage, unsupported suffixes, schema
validity, node/edge counts, FTS tables, binary hash, graph revision, latency,
and error type. The language registry is the one authority used by the sensor,
source revision, syntax probes, indexer, and bridges. Its structural suffixes
match the vendored `gt-index` specs. Authored languages without a shipped
parser are `unsupported_language` or `incomplete_source_coverage`; they are
never relabeled as no source and never approximated with regex symbols.

The task-scoped repository mirror transfers only validation-relevant authored
source plus bounded project metadata before the certified full build. It never
copies checkpoints, datasets, binaries, build products, caches, or task
deliverables into the host index. The indexer uses its real `-file`
incremental path plus closure rebuild, atomically publishes graph and manifest,
and reuses a graph only at the identical validation-relevant source revision.
Deletes, unsafe paths, incomplete transfer, sensor degradation, schema failure,
stale revision, or incomplete authored-language coverage invalidate the
substrate. Healthy empty retrieval and low-relevance candidates instead produce
explicit retrieval dispositions. Derived artifacts and deliverables never
advance source revision.

Before every provider call, the deterministic context frontier advances beyond
facts already represented in durable Mini-SWE history. It emits only certified
definition, signature, caller, reference, test, or bounded ranked-anchor facts
with concrete path/line/symbol anchors, at most three facts and 1,200
characters per call and 6,000 characters per task. It never truncates a fact,
invents an anchor,
predicts the model's action, duplicates a delivered fact, or emits on stale or
unhealthy evidence. Candidate count must equal accounted count. Provider hash,
message index, source/graph revisions, fact IDs, timing, and exact characters
are receipted.

When a healthy current graph has a concrete high-confidence ranked anchor but
no separate definition, reference, caller, or test role, the frontier may use
that anchor as a bounded `FILE`/`SYMBOL` fallback. It names only the certified
source path, positive line, and optional symbol; it never invents a structural
relationship, and it is deduplicated against richer roles and retained history.

Semantic certainty and task retrieval relevance are independent. A structurally
valid graph node is not automatically relevant to the task. Generic anchors
such as `app`, `url`, or `repr` cannot become visible merely because they have a
high graph confidence. Frontier claim identity is semantic and stable across
source revisions; revision-bound fact IDs remain available for audit, while a
claim already delivered is not resent after an unrelated revision change.

Preflight mutation certainty is `PROVEN_READ_ONLY`, `PROVEN_MUTATION`, or
`MAY_MUTATE`, with parser coverage and opaque/unknown segment flags. A workspace
rescan may be skipped only for `PROVEN_READ_ONLY`; ambiguity remains fail-open
and is scanned. This optimization changes no model command.

Deep metrics must include frontier characters in total GT context and report
per task: intelligence status/failures, schema health, source/indexable counts,
nodes/edges, refreshes, frontier candidates/accounting/deliveries/facts/chars,
duplicates, provider hashes, model/API work, controller work, tokens, and
outcome/censoring. The paid merge fails when any required task is not
`repository_intelligence.status=passed`, but still uploads artifacts.

Provider-free proof now requires `REPOSITORY_SUBSTRATE_PROVEN` and
`CONTEXT_FRONTIER_PROVEN` in addition to the permanent all-17 census lines.
This proves deterministic integration and accounting, not a solve-rate or
efficiency gain. No new paid smoke has run for this implementation; the
89-task run remains blocked until an authorized matched smoke passes outcome,
intelligence-health, timing, payload, and efficiency gates. A matched slice
containing authored COBOL or Scheme source is now eligible for the parser gate:
the pinned Tree-sitter grammars are compiled into the checked-out `gt-index`
binary and the runtime fixture must observe nonzero COBOL and Scheme nodes.
R, Verilog, Red, POV-Ray, Racket, and the other explicitly unsupported suffixes
remain analytically fail-closed; an unsupported language is never silently
dropped. These four Terminal-Bench code-like suffixes are now recognized as
validation-relevant source, but they are not claimed as graph-supported until
a certified parser is shipped.

`central_provider_free.yml` must run `central_pre_smoke_gate.py` and print
`SMOKE_APPROVED` on the exact pushed commit intended for a paid smoke. Passing
the component tests on a parent commit is not sufficient.

`require_graph_ready=true` is an experimental validity requirement, not a
pre-provider execution kill switch. Missing, stale, empty, incomplete, or
schema-invalid substrate records `graph_degraded_fallback=true`, preserves the
ordinary Mini-SWE provider loop, suppresses uncertified graph payloads, and
causes the merged treatment gate to fail. This prevents a graph bug from
destroying a baseline solve while preventing a graph-less run from being
promoted as valid GT evidence.

## Portable source capture boundary (2026-08-08)

Workspace source mirroring is host-owned and must work in task images without
Python. `WorkspaceSensor` first tries bounded `python3 -c` JSON/base64 capture,
then falls back to shell-native `base64 | tr -d '\\n'` records for validated
changed paths when Python is missing or output is malformed. It decodes only
exact manifest paths and retains digest/metadata authority. If both captures
fail, the repository session is `mirror_incomplete`; Mini-SWE execution stays
fail-open, while the required intelligence gate fails closed.

Diagnostic paid workflow `31270761663` exposed this defect. COBOL had a healthy
graph but no frontier delivery because its candidates were already represented
in durable Mini-SWE messages; its one guidance event is not a causal-use
claim. `write-compressor` solved but lost current graph substrate after the
task image returned `python3: command not found`; its final graph had zero
nodes/edges, so the run is invalid GT evidence. A portable-capture regression
test and implementation now protect this boundary. Do not start a paid rerun
until provider-free gates pass on the pushed commit and a matched smoke is
separately authorized.

The staged language-completeness implementation is recorded in
`details_done/GT_ALL_TERMINAL_BENCH_LANGUAGE_SUPPORT_IMPLEMENTATION_PLAN_20260808.md`.
Phase 0 inventory/fail-closed accounting and all-registered-parser binary
parity are implemented; R/Verilog native grammar work and Red/POV structural
support remain required before claiming full Terminal-Bench language coverage.

Provider-view efficiency is governed at the observation boundary. Typed
read/search/edit/validate operations receive deterministic per-observation
bounds before the provider call; a successful large read retains head, three
evenly spaced interior windows, and tail so bounding is not head/tail-blind.
Distinct assistant content and reasoning are never removed. Soft checkpoint compaction is considered at 120,000 provider
characters with an 80,000-character target, but it is applied only when the
exact projected view saves at least 20,000 characters and 10% of the current
view. Otherwise it is explicitly deferred so a negligible reduction does not
break the provider's stable cache prefix. Hard provider-budget headroom remains
authoritative and fails before `model.query()` rather than sending overflow.

The top-down repair is provider-free certified on exact implementation commit
`e6ce41f` by workflow `31244088870`: the checked-out Linux `gt-index` build,
COBOL/Python/Scheme repository fixture, 311 workflow-scope tests, all-17 census
coverage, readiness audit, archived replay, and Ruff passed. This is
deterministic integration evidence, not live solve-rate or token evidence. A
separately authorized matched smoke is still required before promotion. The
89-task run remains blocked.
