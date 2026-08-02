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

## Fixes after witness 30736459512 (gated)

- **Neutral in-band labels**: `CanonicalObservation.render()` no longer emits
  `<gt-engine>`/`<gt-fact>`/`GT_` — raw output is first (byte-exact,
  unwrapped), deterministic facts join as a neutral `<result>/<fact>` block.
  External framing made the model treat facts as out-of-band info.
- **Real postflight facts**: the bash path now runs deterministic producers —
  `syntax_result` (ast.parse on changed .py via git status) and `covering_red`
  (execution-specific test/build outcome); PASS_THROUGH upgrades to AUGMENT
  when facts attach. Bash submit commands cross the submit gate.
- **Journal corruption (the silly mistake)**: the `engine_delivery` append
  passed `schema="gt.engine.delivery_receipt.v1"` which overrode
  `ExternalStateStore`'s forced `gt.event.v1`, breaking the tamper chain →
  `research_valid=false`. Removed; gated by `test_engine_gates.py`.
- **Crash-landslide caught by gates**: missing `os`/`Path` imports in
  `runner.py` (`engine_execute_actions` survived only by short-circuit) and
  porcelain `" M"` status parsing would have crashed the next run.
- **Gates**: `tests/test_engine_gates.py` (10) — journal schema valid + trap
  documented, render sentinel-free + raw-exact + facts-present, postflight
  producers, non-repo omission. Full engine battery now **95 green**.
- Provider-free re-certification: run `30738422522` (in progress).

## Deep research + 17-feature activation (round-3 readiness)

`gt_finalstand/ENGINE_DEEP_RESEARCH.md` answers the two questions:

- **Why 0/low facts**: the ENGINE wired only 2 producers (syntax_result via
  git-status+ast, covering_red via command regex). The groundtruth gateway
  (`_produce_raw_candidates` / `produce_raw`) — which fires a producer for
  every semantic event (file_view/edit_result/test_result/search_result/
  submit) — was never ported. Dominant action types (generic commands, reads,
  searches, heredoc edits) mapped to no wired producer; schemelike's heredoc
  edits produced 0 syntax facts.
- **Why inert**: render put raw first, facts trailing (lost-in-the-middle);
  syntax facts reported only "parses OK" (zero information gain);
  `def_partition` results equalled grep; no affordances rendered. Causal trace:
  delivered→referenced→acted ≈ 0.

**Fix landed (commit `4d78600`)**: the gateway is now ported into the ENGINE
compile step (`_gateway_facts` = `classify_event` + `produce_raw` → canonical
EvidenceArtifacts), and the full FACT owner set is registered. Census
`scripts/engine_feature_census.py`: **all_17_wired = True (9/9 FACT, 7/7
CAP_OWNER)**; caller_contract is REMOVE by disposition. 97 engine tests green.

## Verified

- Round-2 witness `30738637714` (10 tasks; write-compressor recovered in
  `30740338420`): 9/10 solved (gpt2 failed 0.0, same as baseline). Token
  deltas: headless −74%, gpt2 −50%, llm-inference −46%, write-compressor −18%;
  regressions portfolio +278%, break-filter +193%, schemelike +52%. The delta
  is descriptive, not causal — the causal trace showed the round-2 facts were
  inert (see ENGINE_DEEP_RESEARCH.md).

## Constraints honored

- No provider run before provider-free gates are green.
- Exactly ten paid ENGINE trials authorized; baseline not rerun.
- Engine work commits to `inline-engine`; advisory docs untouched.
