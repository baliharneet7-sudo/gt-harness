# Inline Engine — Implementation Ledger

Authoritative live record for the Inline Engine phase (branch `inline-engine` on
`harneet2512/gt-harness`). Supersedes nothing; it records what was built, what
was verified, and what remains. Receipts are appended as units complete.

## Authority

- Spec: the Inline Engine plan (finalstand contract) — outcome B, host-native
  action-to-observation middleware.
- GT-off remains the frozen stock-equivalent baseline and rollback path.
- Mini-SWE remains the planner and reasoner; the engine owns the
  action-to-observation interface in ENGINE mode only.
- Advisory-era docs in `gt_finalstand/` are historical evidence.

## Built (all provider-free, tests-first)

| Unit | Module(s) | Tests | Status |
|---|---|---|---|
| IE-01 contracts | `gt_engine/engine/contracts.py` — 14 public schemas (EngineMode, ActionRequest, RepositorySnapshot/SnapshotToken, EvidenceArtifact, InterceptionDecision, ActionResult, CanonicalObservation, MutationProposal, MutationCommitRequest, MutationCommitReceipt, DeliveryReceipt, ActionBatch, FactOwnerRegistration) | `tests/test_engine_contracts.py` (12) | PASS |
| IE-01 transitions | `gt_engine/engine/transitions.py` — lifecycle SELECTED→…→RECEIPT_FINAL, bounded exhaustive traversal, Hypothesis stateful oracle | `tests/test_engine_transitions.py` (12) | PASS |
| IE-02 posture | `GTMode.ENGINE` in `gt_engine/gt_session.py`; `--gt-mode engine` in `scripts/miniswe_gt_run.py`; all-action normalization in `gt_engine/engine/runner.py::engine_execute_actions`, wired at `miniswe_runtime.py` execute_actions seam | `tests/test_engine_runner.py` | PASS |
| IE-03 decision | `gt_engine/engine/decide.py` — five-decision law + locked policies | `tests/test_engine_decide.py` (11) | PASS |
| IE-04 observation | `gt_engine/engine/observe.py` — canonical observation compiler + evidence-delta projection | `tests/test_engine_observe.py` (6) | PASS |
| IE-07 mutation | `gt_engine/engine/mutation.py` — PROPOSE→PREFLIGHT→COMMIT with CAS (StaleProposal/PreimageMismatch/AtomicWriteFailed), atomic write set + rollback | `tests/test_engine_mutation.py` (12) | PASS |
| IE-08 batches | `classify_batch_barriers` in runner — sequential dependency barriers honored by ordered execution | runner tests | PASS |
| IE-09 inventory | `scripts/engine_129_audit.py` → `gt_finalstand/engine_129_transition.csv` (129 rows, 12/48/11/58, all dispositions terminal) | `tests/test_engine_129_audit.py` (8) | PASS |

Total engine tests: **73 green**. Full harness suite re-run after seam edits:
**no regressions** — 5 failures were confirmed pre-existing in the local Windows
environment (they also fail with engine changes stashed; the clean provider-free
Codespaces run is the authority).

## Current defects addressed by the ENGINE path

- Typed PASS_THROUGH now executes a literal fallback command (no longer drops
  the selected action) — `fallback_shell_for_typed` + runner typed branch.
- Every selected action is normalized and bound to a snapshot token in ENGINE
  mode.
- One canonical observation per action; raw bytes preserved where required;
  evidence-delta projection avoids re-dumping unchanged facts.
- Batched stateful actions are executed in order (dependency barriers).

## Verified

- `engine_129_audit.py` exits 0: inventory integrity holds (12/48/11/58, 129
  unique, all dispositions terminal).
- Codespace `special-fortnight-95p9q5wrpqp2qww` on `inline-engine`: all 84
  engine tests green in a clean Linux env (python 3.12, groundtruth 1.0.0,
  harbor 0.20.0, mini-swe-agent 2.2.8).
- Full harness battery in the Codespace: **no regressions**. 4 environment-
  specific failures only (gt-index Go binary + live GitHub API for FS-023).
- **IE-13 provider-free gate GREEN in GitHub Actions**: run `30736226330`
  passed every step (engine battery, 129-row audit, finalstand validator,
  compliance certificates) with zero provider calls.
- **First engine smoke exposed a bug**: run `30735955619` — every task's 2nd
  engine action crashed Mini-SWE's Jinja formatter (engine tool results
  omitted `exception_info`) and the session degraded to stock (`gt_degraded_
  fail_open`). fix-code-vulnerability still solved (reward 1.0) via fallback.
  Fixed in `runner.py::_tool_output` + regression test.
- **ENGINE witness run `30736459512` (fixed code)**: plan job green, 10 task
  jobs ran with parallel=10. **Proof from trajectories** (9 trajectories; the
  gpt2-codegolf artifact upload failed, mirroring that baseline arm's own
  infra failure):
  - 9/9 graded tasks solved at reward **1.0** (matching the frozen baseline's
    9 solved for the same tasks).
  - Every action crossed the engine boundary: 8-100 `engine_delivery` events
    and 16-200 canonical `<gt-engine>` observation blocks per task.
  - All decisions `pass_through`; **GT bytes == raw bytes** (raw preserved
    exactly inside the canonical observation); zero fallbacks.
  - Only cosmetic terminal degrade in the first-fixed run (the `Submitted`
    end-of-run signal); fixed in the seam (`except Submitted: raise`).
  - Full table: `gt_finalstand/ENGINE_WITNESS_30736459512.md`.
- **Two follow-up fixes landed after the witness**: `Submitted` propagation
  (seam) and the single-task merge (workflow) — no re-run needed for the
  witness data (per-task artifacts are authoritative).

## Remaining

- IE-14 witness: ENGINE smoke dispatched — GitHub Actions run
  `30735955619` (harneet2512/gt-harness, workflow `tb2_miniswe_engine.yml`,
  ref `inline-engine`, ten frozen tasks, `MINISWE_AGENT_VERSION=2.2.8`).
  Plan job completed success (provider preflight green, 10 tasks enumerated);
  10 task jobs in progress. Compare with
  `scripts/engine_witness_compare.py` vs the frozen baseline.
- IE-05 hardening: authoritative provider boundary on every overridden query
  path (runner records `engine_delivery` events; DeliveryReceipt request/
  response ids wired; full payload-receipt authority pending).
- IE-13 GHA provider-free closeout workflow (engine battery in Actions; the
  gt-index binary is built there and live GitHub API is available).
- IE-14 completion: download trajectories, run the witness comparison, record
  receipts in this ledger.

## Constraints honored

- No provider run before provider-free gates are green.
- Exactly ten paid ENGINE trials authorized; baseline not rerun.
- Engine work commits to `inline-engine`; advisory docs untouched.
