# GT regression repair implementation — 2026-08-05

## Outcome before the new paid smoke

This patch fixes the deterministic central-runtime defects exposed by paid
workflow `31061665540`. It does not claim an outcome or efficiency win before a
new matched smoke. The 89-task run remains blocked.

## Root causes repaired

1. **SHADOW was not provider-neutral.** The no-compaction branch still removed
   duplicate turns and appended a recurring user state frame. It is now
   observation-only and cannot change provider messages.
2. **Shell text was mistaken for intent.** Newlines were discarded and a raw
   regex extracted paths from heredoc bodies, diagnostics, and `python -c`
   programs. Newlines are real list separators; heredoc/code bodies are opaque;
   targets come only from parsed operands and redirections.
3. **The outer shell return code was borrowed by validators.** `pytest; echo`,
   `pytest | tee`, and background commands could create false certificates.
   Validation now has UNKNOWN/PENDING/PASS/FAIL and requires terminal foreground
   ownership for PASS/FAIL.
4. **Task-start evidence could arrive on call two.** When call-one localization
   was disabled, its durable semantic need remained open. It is now resolved at
   action zero and cannot appear after the initial model decision.
5. **New-file precedent repeated per filename.** It is now one-shot per task.
6. **Delivery hashes described the logical history, not the provider input.**
   Receipts now hash Mini-SWE's prepared messages after private metadata removal
   and record exact request characters/message count.
7. **Read facts fragmented by spelling/output.** `/app/src/a.py` and
   `src/a.py` are the same fact; new output hashes update provenance rather than
   manufacture a new read identity.

## Deterministic safety policy

- `integration_mode=off`: GT behavior disabled with one switch.
- `integration_mode=audit`: private accounting only; provider history unchanged;
  assistive preflight downgraded to SHADOW.
- `integration_mode=active`: grounded one-shot delivery enabled.
- Paid workflow: ACTIVE integration, SHADOW preflight, compaction disabled.
- Parser ambiguity, timeout, stale revision, and low confidence remain PASS.
- REWRITE and feature-driven SUPPRESS remain disabled.

## New receipt metrics

- exact prepared-message/request hashes and hash coverage;
- provider request characters and message counts;
- provider-view changed calls and state-frame calls;
- validation status distribution, attributed results, and unattributed intents;
- typed target count and segment operation distribution;
- existing action/call/token/cache/cost/wall-time/outcome metrics.

The next smoke must have `provider_request_hash_coverage == 1.0`,
`context_state_frame_calls == 0`, and
`context_provider_view_changed_calls == 0`. UNKNOWN/PENDING validation intents
must not appear as certificates or submission blockers.

## Verification state

The central release-relevant suite and static checks pass locally. The complete
repository suite still has unrelated pre-existing failures in the untouched
legacy installed runtime, typed-action snapshot invalidation, and stale
finalstand provenance. These are not silently relabeled as central-runtime
success and are outside the paid `tb2_miniswe_engine.yml` path.

## Research basis

- Bash lists: newlines delimit commands and asynchronous `&` returns without
  waiting: https://www.gnu.org/software/bash/manual/html_node/Lists.html
- Bash pipelines: without `pipefail`, pipeline status belongs to the last
  command: https://www.gnu.org/software/bash/manual/html_node/Pipelines.html
- POSIX shell heredocs are delimited bodies, not executable operands:
  https://pubs.opengroup.org/onlinepubs/9799919799/utilities/V3_chap02.html
- DeepSeek cache reuse depends on exact persisted prefixes:
  https://api-docs.deepseek.com/guides/kv_cache/
- Long-context models do not use all positions uniformly, so repeated true text
  is not free: https://direct.mit.edu/tacl/article/doi/10.1162/tacl_a_00638/119630/Lost-in-the-Middle-How-Language-Models-Use-Long

## Provider-free verification completed

- The release-relevant provider-free suite passes (189 tests in the paid
  workflow selection; 177 in the focused central/replay selection).
- Both census entrypoints prove all 17 producer/consumer paths, grounded
  payloads, first-eligible timing, context accounting, and no blocked actions.
- `central_readiness_audit.py` prints `READY`, including the explicit ACTIVE
  paid mode, SHADOW preflight, exact provider preparation, provider-neutral OFF,
  attributed validation status, and disabled lossy compaction checks.
- Replaying all ten archived trajectories from workflow `31061665540` prints
  `REPLAY_OK`. Legacy certificates that borrowed an unrelated outer shell exit
  code are deliberately invalidated; attributable checks remain mandatory.

## Remaining gate

The pre-smoke gate must run on the exact clean commit after it is pushed because
it verifies local HEAD equals `origin/inline-engine`. Only then dispatch the
authorized 10-task GitHub workflow and compare every task plus aggregate metrics
against the frozen local GT-off baseline. Do not start 89 tasks.
