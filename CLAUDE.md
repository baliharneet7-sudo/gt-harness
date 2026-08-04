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

Do not equate a delivered feature receipt with a model intervention. The engine
can observe a valid lifecycle fact privately, execute a policy decision that
passes, or actively change the next decision via a bounded runtime payload or
a one-time submit hold. Only the latter two are behavior-changing channels.

The historical all-17 policy sent 94 generic/pass/repeated advisories and was
inefficient. The current policy keeps those passive facts private and delivers
only grounded failure/impact evidence. It additionally emits one `GT_EDIT_CHECK`
validation-debt control after three material source revisions without a completed
recognized declared check; it resets after validation and ignores cache files.
Every delivery is transient, next-decision-only, and audit-recorded with its
evidence action and revision. See `AGENTS.md` for the executable contract and
`gt_finalstand/GT_EFFICIENCY_REMEDIATION_PLAN.md` for the release gates.

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
