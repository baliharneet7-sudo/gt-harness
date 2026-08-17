# F6/F7 Diagnosis and Recap-Receipt Repair (run 31975107120)

**Date:** 2026-08-17
**Status:** F6 closed as verified-correct (no code change); F7 closed with a
biting-witness fix in `gt_engine/provider_view.py`; F8 closed as
verified-correct (no engine change); test-hang repair + Phase-2 sweep done
**Evidence base:** the 19 certified_full trajectories/receipts of the matched
20-task smoke, merged under `D:\tmp\opencode\run31975107120_merged`

---

## F6 — context starvation: mechanism audit (closed, no change)

The hypothesis "GT-on starves the model of context" was tested surface by
surface against the receipts. Result: every surface operates per the
authorized thin-compiler / semantic-authority contract; the small visible
totals are the contract working, not a defect.

1. **`context_facts_selected=0` on all tasks is correct accounting, not
   starvation.** The context-fact compiler counted every candidate
   (`candidate == accounted` on every call); candidates were
   `controller_only`, `represented_in_provider_history`, or budget-omitted.
   The legacy fact ledger is not the delivery surface.

2. **Preemptive retrieval abstained 100/100 opportunities per task on 18/19
   tasks, and that is contract-correct.** `_delivery_support`
   (`gt_engine/hybrid_retrieval.py:1326`) admits exactly three support kinds:
   certified structural relation (CERTIFIED trust + endpoint alignment),
   identity-only (killed downstream by `_decision_relevance:1443`), and
   validation candidate (dense+sparse on a mechanically test path under
   `VALIDATION_CONTEXT`). The run's graphs produced **zero certified
   CALLS/ASSERTED_BY/TESTED_BY edges anywhere**; the only CERTIFIED relations
   were IMPORTS (explicitly non-material) and one CALLS_TRANSITIVE. Scheme and
   Redcode adapter edges are SPECULATIVE by design, and C/C++ edges in this
   indexer build did not certify. So the sole eligible delivery path was the
   validation-candidate path, which fired exactly where it should:
   `fix-code-vulnerability` (4 frames to task-start `test/test_*.py` files,
   all first-eligible, all before `model.query()`, task solved). On
   greenfield-authoring tasks (schemelike, corewars, headless) every candidate
   is model-authored or IMPORTS-only, so abstention is the 2026-08-13
   semantic-authority rule operating exactly as authorized
   (`model_authored_context_rejected`, `active_path_context_rejected`,
   `no_decision_relevant_evidence`).
   Residual notes: `qemu-alpine-ssh` ran without the dense backend
   (`dense_backend.available` absent); one `preemptive_retrieval_timeout`
   (2,003 ms) on schemelike call 3.

3. **Persistent state and frontier delivered their bounded slices.** One
   bootstrap excerpt per task (persistent_state_deliveries=1; 4 on
   torch-pipeline, 12 on torch-tensor), contribution-compiler selections
   reached provider requests (schemelike: 20 compiler calls with payloads),
   and the frontier rendered certified facts on the 8 tasks whose graphs had
   substance (schemelike: 3 deliveries / 8 facts from 1,080 candidates).

Conclusion: the "starvation" is the thin-compiler boundary by design on
model-authored-ecosystem tasks. No code change. A future positive-flip
mechanism (O1 packet) would require a separately authorized delivery
extension; this run contains no evidence that one is safe.

## F7 — compaction recap receipts: defect found and fixed

**Observation:** 386 tool bodies cleared across 19 epochs; **0 typed recap
receipts**, all identity-bearing bodies fell back to the bare hash receipt
(`recap_fallbacks` 1-13 per task).

**Root cause:** `_assemble_recap_text` (200-char atomic cap) must carry
`command_sha256=<16>`, the read identity `path@rev` with the **full 64-char
source revision**, `returncode=…`, `chars=…`, and the 64-char content
`sha256=…` (verification field). Arithmetic: fixed load 166 chars + path +
64-char revision + digits pushes any real read receipt over 200 → `None` →
fallback. The suite only ever tested short fake revisions (`s1`, `abc`), so
the hole was invisible to the 60/60 property cases.

**Fix (`gt_engine/provider_view.py`):**
- new `_revision_short()` — bounds a ledger source revision to a 12-char
  prefix for display (full revision stays in the typed ledger);
- `_turn_semantic_parts()` now renders `read <path≤16>@<rev12>` and
  `validation rc=…@<rev12>`;
- recap assembly unchanged (atomic; overflow still falls back byte-for-byte).

**Regression witness** `test_recap_fits_200_chars_with_real_length_revision`
uses a real 64-char revision + `read_history` (the contract's authoritative
ledger) and asserts: recap emitted, `len ≤ 200`, `path@rev[:12]` present, no
command text, and the marker `sha256` verifies against the cleared body.

**Verified passing:** `test_provider_view_compaction.py` (15), `test_provider_view.py`
+ `test_gt_deep_metrics.py` + `test_provider_evidence.py` (48),
`test_gt_central_agent.py` submit/hold/gate/… chunk (23),
`test_gt_central_consumer_proof.py` + `test_gt_semantic_engine.py` +
`test_providers.py` (80). Phase A elision markers unchanged (unbounded by
design). This is provider-free implementation proof only; the next authorized
matched smoke will show the live recap counts in `metrics.context_recap_receipts`.

## F8 — progress/stall audit (closed, no engine change)

The hypothesis "progress control mislabels healthy work as stalled and
over-sticks BUDGET_RISK" was tested against the receipts via
`probe_f8a.py`/`probe_f8b.py` (per-task stall facts, transitions, gains).
Result: the controller behaved exactly per the 2026-08-12 hardening contract;
no engine change was needed.

1. **Stall facts are budget-transition facts, not false stall labels.** Seven
   tasks delivered a `stall-*` fact (cobol, mcmc, regex-chess, schemelike,
   torch-pipeline, video-processing, write-compressor), each created at a
   real `PROGRESS->BUDGET_RISK` transition with reason
   `unresolved_contract_near_iteration_limit` / `_near_time_limit` and
   delivered first-eligible (`delivered_before_call == first_eligible_call`,
   `delivered_before_model_query=true`, exact request hash + message index,
   `not_predictive=true`). The receipt's `evidence_action` can exceed the next
   call number because calls batch multiple actions; the fact is created only
   after its evidence actions executed, so it is never predictive.
2. **BUDGET_RISK is monotonic-until-progress.** Every recovery was
   `material_state_change` (attributed validation pass or confirmed task
   output): mcmc recovered at actions 68/69/77/80/85, schemelike at 63/88,
   regex-chess at 60/61/65/74/79/86/90/94/99, video-processing at
   63..103 — and re-entered only because the contract remained unresolved
   while the iteration limit was near (60% of 100). Final states are
   correct: BUDGET_RISK where the task ended unresolved near the limit,
   RECOVERED where the last material change was recent (regex-chess 99,
   video-processing 103), PROGRESS elsewhere (extract-elf, headless, …).
3. **The false-stall class from run 31421610097 is gone.** Attempt identity
   includes the exact command hash; distinct searches no longer collapse.
   `same_state_updates_suppressed=0` on all 19 tasks — no repeated identical
   frames. Search-heavy tasks (mcmc 66 no_gain, regex-chess 72 no_gain)
   produced only budget facts, never repeated-operation frames.

## Test-hang repair discovered during the Phase-2 sweep (2026-08-17)

The full-suite "timeout" symptom had a concrete root cause: the scripted
model doubles raise `StopIteration` from `next(iter)` when the agent's flow
calls the model one more time than the script provides. Because executor
queries run through `asyncio.to_thread`, a StopIteration in the worker
poisons `_chain_future` (TypeError: StopIteration interacts badly with
generators…), leaving the awaiting coroutine suspended forever: an infinite
hang with no error surface, not a test failure.

- `_ScriptedModel.query` and `_BatchModel.query` now raise
  `RuntimeError("scripted model script exhausted")` — hang becomes a fast
  failure.
- Four tests were flow-stale and were updated to the post-F1/F2 contract:
  - `test_action_conditioned_missing_evidence_returns_before_mutation_once`
    — assistive_safe holds the unverified submit once, so the script is
    `[original, revised, submit, submit]` with `observed_history == 4` and
    `executed.count(submit) == 1`;
  - `test_partial_completion_plan_executes_no_private_predicates` — the F2
    binding now legitimately completes the unqualified "Produce … plan_b1
    .jsonl" plan, so the instruction is qualified ("containing exactly 3
    rows") to preserve the partial-plan premise;
  - `test_assistive_safe_breaks_mutating_batch_before_stale_second_action`
    and `test_compound_mutating_action_breaks_batch_after_observed_directory_change`
    — with the F2 binding, the plan completes after the mutation and the
    completion auto-submit (not the stale barrier) cancels the suffix
    (contract-correct per the completion controller); the instructions are
    qualified ("matching the reference layout", "containing the expected
    layout") to keep the plan partial so the stale-barrier premise holds,
    and the submit is scripted twice for the one-shot hold.
- Ruff (changed files only): 4 new E501s fixed; the 2 remaining
  `test_gt_completion.py` findings are pre-existing at HEAD.

## Phase-2 sweep results (2026-08-17)

- `test_gt_central_agent.py`: all 134 tests executed to completion
  (133 pass + 1 skipped: dense ONNX asset not provisioned). Coverage was
  built from disjoint -k chunks plus per-nodeid batches; the three
  batch/interrupt tests above were the only flow-stale ones.
- Focused suites green: task_contract + noise + completion + progress +
  hybrid_retrieval + delivery_audit + decision_sufficiency (90),
  consumer_proof + semantic_engine + deep_metrics + provider_view +
  provider_view_compaction + provider_evidence + providers (78),
  central_runtime (3 known pre-existing graph-gate failures only:
  `verify_gt_index_runtime` — stale Windows `gt-index.exe` gives c/cpp
  SPECULATIVE 0.2 and elm/ocaml no definitions; identical failure set on
  the pristine HEAD tree).
- Gates: census, readiness audit, and pre-smoke gate all fail closed ONLY
  on the same stale-indexer blocker; the source-built Linux provider-free
  workflow remains the authoritative readiness proof.

## Remaining

Commit at the exact commit, then the authorized matched 20-task smoke with
the all-18 gate, then STOP for explicit 89-task permission.
