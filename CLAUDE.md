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

Provider-free proof is gated by `python -m scripts.central_feature_census` and must
print all of:
`ALL_17_PRODUCERS_PROVEN`, `ALL_17_CONSUMERS_PROVEN`,
`ALL_EFFECTS_TIMING_VALID`, `ALL_PAYLOADS_GROUNDED`,
`ALL_17_CONSUMER_PATHS_PROVEN`, `ALL_17_TRIGGERS_PROVEN`,
`ALL_17_PAYLOADS_CONCRETE`, `ALL_17_CONSUMERS_APPLIED`,
`ALL_VISIBLE_PAYLOADS_IN_FIRST_ELIGIBLE_REQUEST`, and `NO_ACTIONS_BLOCKED`.
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
