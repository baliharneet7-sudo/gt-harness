# nano-harness

Minimal coding agent harness. Score >30% on Terminal-bench and SWE-bench Verified with the smallest, most readable harness possible. Karpathy nano-aesthetic applied to agent harnesses.

## Current Status
**Phase:** Implemented — core harness built and hardened; benchmark runs deferred (cost)
**Started:** 2026-05-02 · **Hardening landed:** 2026-06-17
**Owner:** Troy

Core loop, 3 tools, 2 providers, CLI, logger all built with tests (52 passing).
Loop hardening: per-step token cap, API retries, output-truncation recovery,
verify pass, 60s bash timeout, system prompt v2 (see design doc §3.5a).
Terminal-Bench 2.0 adapter (`eval/tb_agent.py`, Harbor) written but never run —
first benchmark execution awaits budget approval.

## GT central runtime: current behavioral truth

The active benchmark path is a host-owned engine in
`eval/gt_central_agent.py`, not the legacy installed inline runtime. It owns
the model/action loop, observes every execution transition, and keeps GT code,
state, credentials, and receipts outside the task container. The model never
asks a GT tool for help.

Do not equate a produced feature receipt with working integration. A triggered
feature must apply its typed payload to operational controller state. When the
model needs the result, the engine enriches the first provider request after the
evidence action with one bounded grounded payload. The pre-action boundary can
return a mechanically contradicted selected action for fresh model reasoning
only in `ASSISTIVE_SAFE`; it never rewrites or silently suppresses commands.

The 17 feature identities all have a registered consumer (`central_controls.py`);
most effects are internal and cost zero prompt tokens. The source revision is
separate from the whole-workspace revision: caches, binaries, build products,
logs, and background output never stale validation evidence. One immutable
validation classification is shared by the runtime, the evidence ledger, the
receipt, and deep metrics. OFF and SHADOW preserve chosen batches unchanged;
ASSISTIVE_SAFE permits read/search batches but breaks stale state-changing
suffixes. Fresh evidence is inserted before the next model query starts, never
one reasoning step later and never before its evidence exists. Every
model-visible payload must name concrete paths, symbols, commands, checks, or
diagnostics; related feature payloads are coalesced to avoid context spam.

Validation intent is not a result certificate. The shared classifier records
UNKNOWN/PENDING/PASS/FAIL, and only a terminal foreground validator may own the
outer shell status. Reads of verifier files, background commands, trailing
reporters, and unproven pipelines cannot pass or fail an obligation. The typed
shell adapter preserves command newlines and keeps heredoc/interpreter source
opaque, so source strings and diagnostics never become fake targets.

The paid path uses bounded deterministic context compaction: exact semantic
duplicate turns (including tool status, but excluding transport-local IDs) are
removed first, then only older turns are compacted once the 70%-of-400,000
character envelope is exceeded. The latest two turns and a typed current-state
frame survive; below the threshold the history is unchanged apart from exact
duplicates. No LLM summarizes context and unique reasoning is never silently
removed. Each call hashes the provider-prepared messages after private metadata
is stripped. `integration_mode=off|audit|active` is the one-switch policy; the
paid workflow explicitly selects ACTIVE with SHADOW preflight, completion
certificates, progress control, and the exact task-owned Harbor deadline.
Disabled task-start localization cannot surface on call two, and new-file
precedent is one-shot per task.

Workflow `31068690296` is a rejected diagnostic smoke: official reward was
9/10, but uncensored resolved was 8/10 because `write-compressor` gained an
outer 900-second timeout. Six tasks had a positive resource dimension and two
of six provider payloads were semantically wrong. The repairs permanently
classify serialized data/model files as derived artifacts, canonicalize
`/app/...` task deliverables to sensor-relative paths, and require a non-empty,
semantically ranked new-file precedent. Empty `__init__.py` is not useful
precedent. Do not cite this run as an approved GT win; 89 remains blocked.

Completion and deadline controls are now conservative and measurable. Host
workflow text is removed before extracting obligations; auto-submit is enabled
only when every remaining obligation has an executable, current, passing
predicate. A certificate invokes the existing submit marker once and cancels
pre-decided suffixes; predicate checks and submit attempts are counted in
`effective_actions`. Harbor's exported `task.toml` timeout is passed to the
agent with a reserve so the engine returns before outer cancellation. Reward,
outer-censor state, solver exhaustion, and uncensored resolved are reported as
separate fields.

Provider-free proof is gated by `python -m scripts.central_feature_census` and must
print all of:
`ALL_17_PRODUCERS_PROVEN`, `ALL_17_CONSUMERS_PROVEN`,
`ALL_EFFECTS_TIMING_VALID`, `ALL_PAYLOADS_GROUNDED`,
`ALL_17_CONSUMER_PATHS_PROVEN`, `ALL_17_TRIGGERS_PROVEN`,
`ALL_17_PAYLOADS_CONCRETE`, `ALL_17_CONSUMERS_APPLIED`,
`ALL_VISIBLE_PAYLOADS_IN_FIRST_ELIGIBLE_REQUEST`, `NO_ACTIONS_BLOCKED`, and
`ALL_EFFECTS_CONTEXT_ACCOUNTED`.
Receipts are schema v3 with effect-application and exact request-boundary proof.
The 89-task run
remains blocked until the ten-task treatment smoke and repeated matched trials
pass. See `AGENTS.md` for the executable contract.

Before a paid smoke, run `python scripts/central_pre_smoke_gate.py`. Only its
`SMOKE_APPROVED` terminal line authorizes dispatch: it verifies both census
entrypoints, the exact paid workflow, and a deterministic all-17 run through
the real `MiniSweCentralAgent` lifecycle, including terminal submit effects.

The additive `features.effect_trace` ledger distinguishes application from
downstream influence. It records existing consumer reads and confirmed
provider-delivery IDs; `audit_only` is not trajectory influence. This tracing
must not alter model prompts, effect routing, timing, action order, shadow
visibility, or submit behavior.

### Pre-action implementation state

Every selected Bash action is classified once and adapted to a typed
`ProposedAction` before host execution. `ActionCycleReceipt` joins proposal,
candidate preflight decision, applied policy, actual dispatch, postflight, and
reconsideration. Modes are `OFF`, `SHADOW`, and `ASSISTIVE_SAFE`; the paid
workflow is pinned to SHADOW. Timeout and parser failures fail open to the
original command with a receipt. Production rewrite and feature-driven
suppression are disabled. Five features remain strictly postflight-only;
twelve have evidence-gated two-sided placement. See
`GT_PRE_ACTION_IMPLEMENTATION_RECEIPT_20260805.md` for proof and remaining
benchmark gates.

### Deterministic context compiler state (2026-08-05)

GT is the in-process Mini-SWE controller and context compiler, not a stream of
extra advice. Every provider request now passes through a typed fact compiler.
It proves whether each current fact is already represented at exact provider
message indices, is selected into one bounded declarative state frame, remains
controller-only, is stale, or is omitted by the frame budget. The per-call
invariant is `candidate_fact_count == accounted_fact_count`; the final request
hash proves what the model actually received.

The compiler preserves all distinct Mini-SWE reasoning. The paid compaction
transform is enabled, but it may change only tool-observation bodies: oversized
results are bounded, exact duplicate results are represented append-only, and
old tool bodies may become hash/return-code receipts. Assistant content and
reasoning are never removed, and the compiler does not emit a recurring state
frame. Grounded decision evidence uses the bounded one-shot semantic-delivery
path. The exact provider-prepared request must pass the hard context-headroom
check before `model.query()` or guidance-delivery confirmation.

Compound Bash is classified segment by segment. Typed read observations carry
canonical path, requested line range, source/workspace revision, return code,
and output hash into controller state. Validation classification is bound only
to the actual runner segment; setup/reporting segments do not inherit it, and
shell programs such as `sed 's/x/y/'` are not treated as file targets.

Every feature effect receives first-eligible context accounting without being
misreported as model influence. `provider_payload` proves delivery;
`controller_state_considered` proves private deterministic controller work;
superseded, stale, audit-only, existing-actuation, and no-next-call outcomes
stay explicit. Next-action anchor alignment is a utilization proxy, not proof
of an internal model acknowledgement. A matched benchmark is still required
for a causal efficiency claim.

### Final ten-task correctness audit

The final paid treatment smoke is workflow `30954660207` on commit `e7418a7`.
All ten task jobs completed successfully. Every receipt had all 17 features
enabled; 372 effects were produced and applied. The effect breakdown was 297
engine-internal state effects, 11 existing engine-actuation effects, 48
audit-only effects, and 16 provider-payload effects. Fourteen payloads reached
the model; all were concrete, grounded, non-predictive, and delivered in the
first eligible provider request. Late deliveries: 0.

The source-precedent bug is fixed and tested. A `newfile_precedent` trigger must
be a regular model-authored validation-relevant source file with a recognized
source suffix; sibling candidates receive the same classification. The payload
contains only the selected source trigger, not every path in the workspace
transition. The final smoke had 10 valid precedent payloads and zero cache,
binary, generated-output, or task-output paths. The earlier run
`30952995623` is not valid evidence because it still exposed the whole created
batch.

Efficiency against the frozen GT-off baseline was: tokens `-9,135,151`
(-31.26%), API calls `-51`, assistant steps `-53`, and actions `-103`. This is
one matched smoke at temperature 1, so it is an efficiency signal rather than a
causal model-quality claim. The 89-task run is not yet started; it is ready for
the next gated evaluation from this commit or a descendant.

## What this is
An agent harness — the code that wraps an LLM and turns it into something that does work (loop, tools, context management, system prompt). This one is single-purpose: a coding agent. Built to score on benchmarks while staying tiny enough to read end-to-end.

## What this is NOT
- A general agent framework (no plugin system, no extensibility for arbitrary domains — that's Archon/DeerFlow's lane)
- A product with a UI (no dashboard, no auth, no SaaS — that's Agent OS's lane)
- A chat assistant (single-turn-ish, task-completion-focused)

## Decisions made
- **Scope:** Vertical coding agent (option A). Educational nanoharness (option C) emerges naturally from minimalism. Framework (option B) deferred indefinitely — premature abstraction kills these projects.
- **Benchmark target:** Terminal-bench primary, SWE-bench Verified secondary. Terminal-bench because (a) less crowded, (b) the harness shape (shell loop + minimal tools) is terminal-native, (c) attention is rising, (d) >30% is still respectable there. SWE-bench Verified runs the same harness for cross-validation credibility.

## Decisions pending
- **Model strategy:** Frontier-only vs provider-agnostic vs multi-model leaderboard table
- **Minimalism budget:** LOC ceiling, system prompt token ceiling, dependency count
- **Architecture sketch:** Loop shape, tool set, context management strategy
- **Repo layout:** Single file vs small file tree

## Files in this project
- `CLAUDE.md` — this file (project context, current status)
- `memory.md` — running decision log + notes that are project-specific
- `skills.md` — which skills to use during this work and when
- `docs/superpowers/specs/2026-05-06-nano-harness-design.md` — approved design (v1.1)
- `eval/tb_agent.py` — Terminal-Bench 2.0 adapter (Harbor `BaseInstalledAgent`)

## Strategic context
Tracked in user-level memory:
- `reference_agent_harnesses.md` — competitor watch list (Archon, DeerFlow 2.0, etc.)
- `reference_archon.md` — primary reference harness
- The wedge: "None of the popular harnesses publish benchmark scores. They compete on features. Nano-harness wedge: minimal harness with published >30% scores. Score-per-line-of-code as the differentiator."

## Working norms
- Don't auto-commit by default (Troy decides when to commit).
  - **Exception:** when executing a written and approved implementation plan from `docs/superpowers/plans/`, per-task commits specified in the plan are pre-authorized. Commit messages and staged-file lists must follow the plan exactly.
- Brainstorm → design doc → user approval → writing-plans → implementation. No code before design approval.
- Karpathy aesthetic: small, readable, end-to-end legible. If a file passes ~500 lines without a damn good reason, the design is wrong.

## GT coverage and engine-accounting rule

Keep these claims separate in every report:

1. The provider-free census proves all 17 producer/consumer paths.
2. A paid trajectory fires a feature only if its receipt set contains that
   feature ID.
3. A feature is consumed when its effect is applied and has a recorded
   downstream disposition.
4. A feature is model-delivered only when its grounded effect ID appears in a
   confirmed guidance delivery.

The ten-task smoke `30976148466` naturally fired 15/17 features; `recovery`
and `signature_delta` were absent because their exact triggers did not occur.
It produced 361 effects; 36 were model-visible payloads. Never describe that
as “GT produced only 36.”

Private effects are not automatically useless. Read the effect trace and
separate `engine_internal_state`, `existing_engine_actuation`,
`provider_payload`, `audit_only`, and `unread_private_state`. Producer-side
deterministic engine work counts as engine activity even when it does not emit
model text. Usefulness requires a downstream state read, decision-frame
contribution, validation/batch action, or provider delivery. The detailed
archived comparison is in
`GT_SMOKE_30976148466_BASELINE_COMPARISON.md`.

### Latest context-compiler smoke and hard gate

Smoke `31061665540` at `a45601f0ba05` preserved reward 9/10 and passed every
integration-accounting invariant, but failed the experiment gate. It had a new
outer Harbor timeout on `cobol-modernization`, a step-capped `schemelike`, six
strict per-task Pareto failures, and +13.33% aggregate normalized token cost.
Do not promote it and do not start 89 tasks.

The live receipts also proved that `edit_target_absent` was an invalid material
preflight rule: 104 normal edit/scratch commands became candidate returns.
Shadow mode prevented execution changes. Current code makes absent targets PASS
and provider-free replay yields zero such candidates. Never restore this rule.

Outer Harbor exceptions occur after the last central receipt and must be joined
from trial/merged results. Context accounting must include bounded compiler
state-frame characters as well as active guidance characters. The complete
audit is `GT_SMOKE_31061665540_CONTEXT_COMPILER_AUDIT.md`.

### Regression repair after workflow 31078501162

The later paid smoke `31078501162` regressed to 7/10 and is also rejected.
The scheduler reached 100 steps because task outputs were misclassified and
novel observations could clear budget risk without task progress. The
compressor exceeded the provider context limit because the old compactor
could remove distinct reasoning yet still produce an oversized request.

Current code uses typed task-resource roles, output-only deliverable
projection, non-certifying output-existence progress probes, sticky budget
risk, reasoning-preserving tool-result compaction, and an exact pre-query
provider budget. Over-budget exits are internal solver exhaustion, not Harbor
censoring, and unsent guidance is not marked delivered. New receipts include
provider headroom, stable-prefix/cacheability, bounded-observation, completion,
and task-progress metrics. This is provider-free proof, not a recovered solve
claim; another matched smoke still requires authorization and the 89-task run
remains blocked.

### Feature applicability and graph-runtime repair (2026-08-06)

The corrected smoke's 13/17 statement was incomplete. Across its ten tasks,
38/38 repository refreshes were `index_unavailable`; `caller_contract` and
`def_partition` were therefore infrastructure misses. Only `recovery` and
`signature_delta` were valid exact-trigger absences. Of 100 localization and
reslot receipts, only four carried concrete anchors.

Current paid workflows install the vendored GroundTruth wheel, export the
pinned index binary, and execute a real binary-to-SQLite fixture before any
provider call. Definitions, references, and certified directed callers come
only from graph roles; grep prose cannot create them. Search filters,
ambiguous output, unsupported source, and incomplete graph evidence record a
typed abstention and emit no empty effect.

Every task receipt now reports feature applicability as fired, correct
abstention, trigger absent, ambiguous, substrate unavailable, or missed. Deep
metrics expose the corresponding feature IDs plus false fires. Provider facts
must be coalesced into their first eligible call or remain controller-only;
they cannot leak one step late. The all-17 census additionally requires zero
eligible misses, false fires, empty localization, unverified callers, and
duplicate frame evidence, plus a real repository-substrate proof.
