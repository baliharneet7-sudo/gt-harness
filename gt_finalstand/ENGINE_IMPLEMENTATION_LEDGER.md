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
- Codespace `special-fortnight-95p9q5wrpqp2qww` created on `inline-engine`
  (pending full-battery run).

## Remaining

- IE-05: authoritative provider boundary on every overridden query path +
  DeliveryReceipt provider-request/response binding (runner records
  `engine_delivery` events; hardening in progress).
- IE-06: read/search vertical slice (typed producers already dispatch via
  `execute_typed_action_fail_open`; literal views stay literal).
- IE-10: passive PERF certificate (PERF rows never model-visible / never
  decision-eligible).
- IE-11: advisory-dependency removal certificate (import closure of the engine
  package).
- IE-12: replay/provenance/security for engine events.
- IE-13: provider-free certification in Codespaces + GitHub Actions.
- IE-14: exactly ten ENGINE witness trials vs frozen baseline.
- Phase A: `finalstand.md` authoritative handoff.

## Constraints honored

- No provider run before provider-free gates are green.
- Exactly ten paid ENGINE trials authorized; baseline not rerun.
- Engine work commits to `inline-engine`; advisory docs untouched.
