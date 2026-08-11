# GroundTruth Final Execution TODOs

This is the authoritative execution ledger for the retrieval-plus-reasoning
proof. Only one item may be `in_progress`. Paid provider work is blocked until
the relevant gate and explicit authorization are recorded.

## Control rules

- ARB proves retrieval quality only; it does not prove model reasoning or task success.
- Model utility is measured at paired decision points with exact control/treatment requests.
- No markers, acknowledgements, chain-of-thought inspection, or benchmark-task heuristics.
- No GT runtime changes after `FINAL_GT_MANIFEST.md` is frozen.
- Every 15-minute heartbeat records SHA, worktree, completed work, active TODO,
  verification, remaining work, blocker/permission, and deviation check.

## Ledger

| ID | Status | Acceptance condition | Evidence | Next action |
| --- | --- | --- | --- | --- |
| GT-FINAL-001 | complete | Four-layer proof contract documented | `FINAL_EXECUTION_PLAN.md` | continue baseline |
| GT-FINAL-002 | complete | ARB retrieval-only claim and paired reasoning contract documented | `RETRIEVAL_BENCH_CONTRACT.md`, `DECISION_POINT_EVAL_CONTRACT.md` | verify current defect evidence |
| GT-FINAL-003 | complete | Current SHA/config/environment captured | `artifacts/final_execution/baseline.md` | continue contract work |
| GT-FINAL-004 | complete | Verified P0/P1 defects reproduced and provider-free gates recorded | live/ARB profile RED tests; GitHub run `31526751148` | continue runtime proof |
| GT-FINAL-005 | complete | Runtime delivery/abstention/failure proof complete | real Snowflake local/GitHub witnesses; typed contribution compiler; `FINAL_RUNTIME_PROOF.md` | paired decision-point evaluation |
| GT-FINAL-006 | complete | Gold-isolated ARB adapter exercises production retrieval | `scripts/arb_adapter.py`, `tests/test_arb_adapter.py` | prepare official data |
| GT-FINAL-007 | complete | Complete 427-row ARB run is pinned, gold-isolated, evaluated, and retained | run `31517629497`; `RETRIEVAL_BENCH_RESULTS.md`; `D:\gt_runs\arb-31517629497` | connect the frozen profile to live Mini-SWE |
| GT-FINAL-008 | complete | One generalized hybrid retrieval repair completed and frozen | commits `55553a3` through `433c330`; ARB final metrics | no further retrieval tuning |
| GT-FINAL-009 | in_progress | Paired decision-point reasoning evaluation complete | exact validator; captures `31530343093` (11 valid), `31531620414` (4 valid), `31532480146` (1 valid; one graph-invalid task) | run matched controls through the GitHub workflow |
| GT-FINAL-010 | pending | GT and harness frozen | `FINAL_GT_MANIFEST.md` | freeze only after gates |
| GT-FINAL-011 | pending | Same-wrapper SWE-Live contract and run complete | final A/B artifacts | requires authorization |
| GT-FINAL-012 | pending | Existing online DeepSWE-off metadata verified; frozen GT-on evaluated first | `DEEPSWE_FINAL_RESULTS.md` | do not rerun baseline |
| GT-FINAL-013 | pending | Terminal-Bench 2.0 evaluated through Mini-SWE after DeepSWE | `TERMINAL_BENCH_20_RESULTS.md` | conditional |
| GT-FINAL-014 | pending | Final causal report and verdict complete | `GROUNDTRUTH_FINAL_REPORT.md` | close project |

## Current stop state

`GT-FINAL-009` is active. ARB is complete: workflow `31517629497` evaluated
all 427 rows at frozen commit `433c330`, and `RETRIEVAL_BENCH_RESULTS.md` is the
authoritative report. The live Mini-SWE defect was configuration drift: the
accepted retriever was disabled, lacked the 32-span dense cap, used three
selected files instead of the frozen eight-file packing policy, and had no
pinned ONNX asset. The shared profile, durable GitHub release asset, live
workflow configuration, real Snowflake integration witness, typed contribution
compiler, and active component registry passed exact GitHub provider-free run
`31527155811` at `90896d4`, including `READY` and `SMOKE_APPROVED`. The next gate
is paired decision-point utility. Archived run `31421610097` contains 1,051
complete treatment calls but zero exact control requests, so none is a valid
pair for the frozen mechanism. The bounded captures at `31530343093`,
`31531620414`, and `31532480146` contain 16 valid first-intervention pairs and
24 legitimate no-intervention abstentions, with zero corrupt bundles. The last
slice's merge failed closed for `crack-7z-hash` because its repository graph
was invalid; that task is excluded from any utility claim. The control replay
workflow is committed at `2cd0dfd` but GitHub only registers new workflow files
from the default branch, so it is prepared but not dispatchable until the
normal merge path is used. No end-to-end outcome claim is made and the 89-task
run remains blocked.

## Work plan mapped to the GT objective

### Phase 0 — Freeze the question and controls

- [x] Define the four claims separately: retrieval, delivery, model decision,
  and task outcome.
- [x] Record that ARB cannot prove model reasoning or end-to-end benefit.
- [x] Pin the active branch/commit and preserve the historical baseline only as
  non-causal reference evidence.
- [x] Resolve the exact-pushed-tree publication gate without bypassing it.
- [x] Reproduce each current live-retrieval P0/P1 defect against executable code and mark it
  `must_fix`, `measurement_only`, or `not_reproduced`.

### Phase 1 — Prove the deterministic GT engine

- [x] Verify all-17 producer/consumer/timing/payload/context-accounting gates.
- [x] Verify graph substrate, parser coverage, and readiness provider-free.
- [x] Capture local runtime proof for grounded dense delivery and warm abstention with exact request hashes.
- [x] Capture GitHub runtime proof for grounded delivery, correct abstention, and
  graph failure with exact request hashes.
- [x] Prove locally no extra agent action, no late delivery, no predictive delivery,
  no duplicate fact, and no stale-revision evidence.
- [x] Produce `FINAL_RUNTIME_PROOF.md`.

### Phase 2 — Prove retrieval quality independently of model sampling

- [x] Pin official ARB source at `07014c986f3deadb1548c62b32c0ffbe6a81465d`.
- [x] Implement the gold-isolated adapter through GT’s production contract,
  graph projection, evidence need, and ranker.
- [x] Reject recursive gold/fix/patch/evaluator leakage.
- [x] Separate index-build latency from post-index query latency.
- [x] Download and validate official V2 benchmark/corpus releases.
- [x] Prepare redacted input JSONL containing only query state and declared
  given files.
- [x] Move corpus/index/baseline execution to the pinned GitHub workflow;
  local memory-heavy evaluation is prohibited.
- [x] Evaluate the complete 427-row GitHub run and compare against official leaderboard baselines.
- [x] Dispatch GitHub lexical/BM25/RepoMap-compatible baselines with
  `all_files` and retain run artifacts.
- [x] Dispatch GitHub GT candidates and bounded delivered evidence; report
  both.
- [x] Classify misses as query, index, graph, ranking, redundancy, over-
  retrieval, failed abstention, or unrepresentable input.
- [x] Allow at most one generalized retrieval repair if the repeated-defect
  rule is satisfied.
- [x] Produce `RETRIEVAL_BENCH_RESULTS.md`.

### GitHub execution controls

- [x] Use immutable action SHAs and the pinned ARB source commit.
- [x] Use twenty balanced independent exact-base snapshot shards.
- [x] Keep gold/fix/patch/evaluator fields out of GT inputs.
- [x] Upload per-shard receipts and optional official baseline details.
- [x] Push the workflow and dispatch it from the intended harness SHA.
- [x] Verify uploaded artifacts and write the retrieval results report.

### Phase 3 — Prove whether the model’s next decision changes usefully

- [x] Locate replay-ready first-visible-intervention points; archived run
  `31421610097` has 0/1,051 because the legacy bundle omitted exact controls.
- [x] Implement opt-in exact control/treatment capture and reject pairs whose
  provider-visible difference is not exactly the compiled GT payload.
- [x] Make the paid GitHub capture bound explicit (`step_limit=1`) while
  preserving the normal workflow default of 100 calls.
- [x] Reject and cancel capture run `31529376771`: its first artifacts exposed
  that Mini-SWE's built-in Bash schema was not included in the pair receipt;
  no result from that run is evidence.
- [ ] If unavailable, obtain explicit authorization for bounded SHADOW capture;
  do not run a full paid benchmark merely to collect these points.
- [ ] Build exact control/treatment provider requests differing only by the
  production GT payload.
- [ ] Reject pairs with prior visible GT context, stale facts, duplicate facts,
  missing responses, or non-GT byte differences.
- [ ] Run one response per arm per distinct decision point with the same model,
  prompt, tools, sampling, and limits.
- [ ] Mechanically classify next actions as beneficial, harmful, equivalent, or
  indeterminate without markers or hidden-reasoning claims.
- [ ] Report paired sign-test results and all harmful cases.
- [ ] Produce `DECISION_POINT_EVAL_RESULTS.md`.

### Phase 4 — Freeze the final GT candidate

- [ ] Pass runtime, retrieval, and decision-point gates.
- [ ] Freeze GT SHA, Mini-SWE SHA, graph/index binary, model fingerprint,
  prompts, thresholds, evidence budget, containers, and evaluator.
- [ ] Produce `FINAL_GT_MANIFEST.md`.
- [ ] Make all later benchmark runs read-only with respect to GT code.

### Phase 5 — Establish end-to-end product evidence

- [ ] Run DeepSWE first after freeze, using a GitHub-hosted same-wrapper
  baseline/treatment adapter and its current official protocol.
- [ ] Analyze every DeepSWE gain/loss by first trajectory divergence; do not
  attribute zero-intervention differences to GT.
- [ ] Verify and run the existing GitHub-hosted DeepSWE workflow in the
  GroundTruth repository (`.github/workflows/deepswe_full.yml`/`deepswe_trial.yml`);
  it launches the pinned Mini-SWE agent through Pier (no OpenHands/OpenAgents
  path) and still requires a matched GT-off arm.
- [ ] Run Terminal-Bench 2.0 next through the existing GitHub Mini-SWE/Harbor
  workflows, with all-task and source-applicable results.
- [ ] Run contemporaneous same-wrapper SWE-Live Lite only after the DeepSWE and
  Terminal-Bench gates, if still needed for the final product claim.
- [ ] Report resolution first, then outcome-conditioned calls, steps, actions,
  tokens, cost, wall time, GT context, and graph applicability.
- [ ] Produce the final causal report and stop the project.

## Heartbeat contract

Every 15-minute update must show the phase, active TODO ID, completed IDs,
verification evidence, remaining IDs, next command/action, blockers or required
authorization, current/local-vs-origin SHA, and whether scope has deviated. A
heartbeat is not permission to cross a paid-run or freeze gate.
