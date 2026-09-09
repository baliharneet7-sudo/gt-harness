# Handoff: everything that landed, and the one thing left

Written 2026-09-08 after the first complete 20-task attested DeepSWE run.
Everything in Part 1 is done and measured. Part 2 is the only open work.

---

## Part 1 — Done

### Blocker 7c: the live path amends instead of rebuilding

`gt_engine/indexer.py` gained a real incremental path: capability probe
(`_producer_supports_incremental_amend`, fails closed), copy-then-amend into a
new immutable revision, `_publish_candidate` shared with the full build, and a
real `refresh_index_files`. `graph_coordinator.py` carries the parent graph
through coalescing. `miniswe_integration.py` emits a `graph_build_mode` journal
row so the path can be proven rather than assumed.

Measured on the arktype codespace run: caller coverage 26% -> 63%, 28 amends on
a 184,370-node graph, 484 proofs preserved, 166 calls against a 230 baseline,
input tokens 12.9M against 20.5M.

### `obligation_reverified` fires

First time in project history. Its sibling `obligation_invalidation` was found
to be reporting the OPPOSITE of reality (claiming proofs survived edits that had
wiped them) and was corrected. Both now fire, 33 times each on a single task in
the live run.

### `signature_delta` was a dead path

It needed edit text and graph simultaneously, which were mutually exclusive.
Fixed by plumbing a pre-edit graph through `_run_evidence`. It then correctly
abstains on TypeScript, because the producer analyses Python only.

### A benchmark timeout is graded, not discarded — commit `41ad8853`

`scripts/miniswe_supervisor.py` maps an exhausted budget to exit 3.
`eval/miniswe_agent.py` re-raised that as `NonZeroAgentExitCodeError`, so Pier
recorded `status: ERROR`, `reward: null`, and the official verifier never ran.

Both frozen GT-off controls grade their timeouts: Terminal-Bench 2.0 is 89/89
graded with 4 `AgentTimeoutError` trials counted as non-solves inside its 66/89,
and the DeepSWE 10-task control is 10/10 graded with no censoring. Raising
removed a zero from the GT arm that the baseline keeps.

Exit 3 is now absorbed so the verifier grades whatever was committed. Exit 4
provider_failed, 5 internal_error, 6 setup_error, 137 OOM and any unparseable
message still raise. Both arms share the policy;
`tests/test_agent_timeout_is_graded.py` pins that the workflow-reachable Pier
adapter carries it.

**Proven in production**: arktype ran 1h13m, hit its deadline, and returned
`reward: 0` with real test counts. The previous attempt returned no reward at
all after 250 completed model calls.

### `all-20` cohort stage — commit `a50b89dd`

The workflow offered only `gate-one` or `remaining-19`. `all-20` selects the
same 20 tasks in the same pinned order at the same per-task budget, refuses a
prior-gate binding, and `attest_deepswe.py` rejects a plan carrying one.

### Benchmark parity, verified rather than assumed

Every one of the 20 tasks declares `[agent] timeout_sec = 5400.0` at benchmark
revision `435ee89ec2f2e2289f33b0da4f992f0b7b7266b9`, and the plan job resolves
with multiplier 1.0. `GATE_ONE_MAX_TIMEOUT_SECONDS = 5400` therefore subtracts
nothing. An earlier plan to RAISE that cap would have done nothing and would
have broken parity if it had. The comment beside it now says so.

One asymmetry runs against us and is deliberately left alone: the supervisor
reserves 300 s of the 5400 to publish receipts, so the agent loop gets 5100 s
where the public leaderboard's agent gets the full 5400.

---

## Part 2 — The run, and what it says

GitHub Actions run **34272342544**, all 20 tasks, one dispatch, commit
`a50b89dd`. Every gate passed. All 20 graded.

### Score

| | value |
|---|---|
| GT solved | **8 / 20 = 0.400** |
| flash, difficulty-adjusted to THESE 20 tasks | **0.524** |
| flash, published headline (113 tasks, n=4) | 0.5332 |

The 0.524 is derived, not borrowed. `deepseek-v4-flash` publishes NO per-task
data (absent from both the v1 and v1.1 heatmaps; the site loads only
`leaderboard-live.json`, `v1-delta.json`, `tasks.json`, `distribution.json`, and
per-task endpoints that serve repository files, not results). So: the v1.1
heatmap's 8 models give a per-task field pass rate; the full 113 average 0.5044
and our 20 average 0.4960; flash sits at 0.5332/0.5044 = 1.0571 of field; hence
0.4960 x 1.0571 = **0.5243 expected on our 20**. Never use `deepseek-v4-pro`.

### Tokens, per task

| | GT | flash | delta |
|---|---|---|---|
| input | 8,940,519 | 19,829,931 | -54.9% |
| cached | 8,580,646 | 19,719,518 | -56.5% |
| uncached | 359,873 | 110,413 | **+225.9%** |
| output | 48,709 | 107,687 | -54.8% |
| provider calls | 95 | 153 | -37.8% |

Cache hit rate GT 96.0% against 99.4%. GT injects fresh evidence on nearly every
call, mutating the prompt and breaking the cached prefix. In absolute terms the
extra uncached is 2.3% of the input saved, so it is not itself a crisis — but it
is the number a naive plan implementation would multiply.

### Where the score is lost

**Four losses were one or two tests short.** Converting exactly these four gives
12/20 = 0.600, above baseline. This is the entire prize.

| task | missed by |
|---|---|
| adaptix-name-mapping-aliases | 1 of 44 |
| awilix-async-container-initialization | 1 of 24 |
| bandit-incremental-cache-control | 1 of 88 |
| aiomonitor-task-snapshots-diff | 2 of 53 |

**Two tasks broke previously-passing tests**: clack 18 of 643, arktype 2 of 1679.

**Two are deeper failures** that no verification layer will fix:
oxvg 0 of 6, anko 1 of 2.

**The attestation FAIL has two disjoint causes, not one.** Read from run
34272342544's own attestation artifact rather than inferred:

| tasks | cause |
|---|---|
| 12 | receipt ISSUANCE raised, so no product row exists at all: `product_not_completed` + `treatment_receipt_missing` + every conservation check |
| 7 | receipt issued fine, but `product_completion_unverified` + `product_unmet_predicates` |
| 8 | product rows present (1 of them verified) |

The two sets do not overlap. Only 8 of 20 receipts issued.

The dominant failure is therefore NOT `submitted_unverified` — it is receipt
issuance throwing before a receipt exists. On aiomonitor the exception is
`semantic_localization_certified_graph_missing`
(`gt_harness/runtime_receipts.py:559`): the task-start localization artifact
names a graph revision, and by the end of the run no surviving
`graph.manifest.json` matches it, because 42 publications and live+1 retention
evicted it. Reproduced identically in run 34294960097, with the same nine
errors, before and after the persistent plan existed. Fixing the completion
predicate cannot make this attestation pass; the graph-retention lifetime is a
separate and larger blocker.

Runtimes were 16-72 minutes against 85. There is large unused headroom for
verification.

### Two near-misses, diagnosed in full

Both were derivable from the prompt alone. Neither needed hidden information.

**awilix (23/24)** — the agent made `scope.initialize()` cascade into the
parent. The prompt's own Assumptions list said verbatim: *"Scoped containers can
be initialized independently; parent container's singletons are not
reinitialized"*. A pure **completeness** failure.

**adaptix (43/44)** — failing test
`test_alias_conflict_required_all_mode_no_spurious_not_found`. The prompt said
"Multi-key conflicts raise `ExtraFieldsLoadError`" and "Trail reflects the
actual resolved key". The agent DID raise the error; it got the behaviour wrong
specifically under **`DebugTrail.ALL`**, an existing enum in that codebase. An
**interaction** failure: a new requirement crossed with an existing mode. Not a
bullet in the prompt, but mechanically enumerable from a graph that knows
`DebugTrail` exists, knows its members, and knows what consumes them.

That distinction is the design brief for Part 3.

### GT was working, and the cost is identified

On awilix: 123 evidence deliveries, 22 caller contract views, 55 co-change
partners, 33 obligations reverified across 33 edit transactions, caller coverage
answered on 18 of 33 edits.

**All 33 graph builds were FULL rebuilds.** 31 were refused for amend with
reason `producer_lacks_amend_capability` — the certified binary does not declare
`incremental_amend_in_place`. They consumed **10.8 minutes of a 43-minute run**.
That is the single largest recoverable cost and it is blocked on Route-B
re-certification of the producer, not on code.

---

## Part 3 — The only open work: a persistent plan

### The rule, first

The plan is derived from ONLY: the task prompt, the repository at base commit,
and the graph built from it. **Never** the verifier's tests, the fail-to-pass
list, or anything under the benchmark harness. Reading hidden tests invalidates
every number in Part 2. Depth must come from reasoning harder about what we are
given, not from seeing more.

### Why build it once, up front

The graph is strongest at step zero: complete, current, fully certified. Every
edit degrades it — measured, caller coverage was answered on only 18 of 33 edits
mid-run, and 31 of 33 rebuilds were refused. A plan built before the first edit
harvests the graph at full strength, once, with no invalidation and no rebuild
churn. One extra model call against 42 minutes of unused budget is a good trade.

The token numbers point the same way structurally. Continuous per-call evidence
injection is what dropped cache hits from 99.4% to 96.0%. Concentrating context
into one planning call and holding a stable artifact in the prefix delivers MORE
context while injecting it FEWER times.

### Research agenda — do this before writing code

1. **How is the prompt assembled today?** Find where evidence enters the
   mini-swe turn loop (`gt_engine/bridge.py`, `gt_engine/miniswe_runtime.py`;
   there are 184 `context_assembly` rows against 123 `evidence_delivery` rows on
   one task). Establish empirically what is byte-stable across turns and what is
   not. Do not assume.
2. **Where does the plan live so it is cached once?** The tension: a plan is
   most cacheable when immutable and at the very front; progress against it is
   inherently mutable. Anything mutable in the prefix busts the cache for every
   later call. Likely shape is an immutable plan in the prefix and a mutable
   progress ledger at the tail, but confirm against how the provider actually
   caches rather than asserting it.
3. **Resident whole, or index plus active slice?** Weigh both against the real
   per-task figures above. Produce a recommendation with a token budget stated
   as input / cached / uncached / output. Never dollars.
4. **What already exists?** `gt_engine/persistent_execution_state.py` is 756
   lines and exposes `build_planning_payload`. It recorded **zero** rows in the
   live run — dormant on the mini-swe path, like `graph_lease.py`.
   `gt_engine/attribution.py` already defines `covering_red`, `submit_refusal`,
   `GT_SS_SUBMIT_RED`, `obligations`. `gt_engine/bridge.py` has
   `_build_verification_plan`, which is a PER-EDIT plan and not what is wanted.
   Obligation invalidation and reverification already work. What is missing is
   the obligation SET originating from a plan rather than from whatever happened
   to be edited.

### What the plan should contain

1. **Requirement ledger** — every normative statement from the prompt, verbatim,
   one row with a stable id. Not paraphrased; a paraphrase is where a wrong plan
   starts. This alone catches the awilix class.
2. **Graph anchor per requirement** — the symbols, files and definitions it
   touches, resolved from the graph. A requirement with no anchor is flagged,
   not guessed. This is what keeps the plan factual rather than confident.
3. **Interaction matrix** — for each requirement, the existing enums, flags,
   modes and alternate paths reachable from its anchors, each cell either
   checked or explicitly marked not-applicable with a reason. This is the
   adaptix class: unseen edge cases become cells rather than intuitions.
4. **Blast radius** — callers of every anchor entity, plus the currently-green
   test set captured before the first edit. This is the direct fix for clack's
   18 and arktype's 2 broken tests, and it needs no model call at all.
5. **Verification method per requirement** — the command or test that proves it.
   A requirement with no verification method is a comment.
6. **Edit ordering** from the graph's dependency edges, bottom-up, so later
   edits do not invalidate the ground earlier ones stood on.
7. **Abstention record** — where the graph could NOT resolve. A confident plan
   with silent gaps is worse than no plan, and this is the section most likely
   to be dropped.
8. **Completion predicate** — submit permitted when every requirement has
   evidence and the green baseline is intact. This is what turns
   `submitted_unverified` into a real gate.

Keep OUT: speculative implementation detail (the agent's job), and anything the
graph cannot source (where confident-and-wrong re-enters).

### Integration constraints — what must not break

- `ensure_index_with_receipt`'s signature is pinned by three test stubs and
  `miniswe_integration.py`. Do not change it.
- The submit gate needs a budget-aware escape, or it converts near-misses into
  timeouts, which score the same zero.
- Adding a mutable artifact to the prompt prefix would multiply the one number
  that is already worse than baseline. Measure the cache hit rate before and
  after.
- `scripts/smoke_stage.py` pins the cohort, its order hash and its budgets. The
  plan work must not touch them, or the run stops being comparable.

### Evaluation protocol

Target task: **`aiomonitor-task-snapshots-diff`**. Smallest test surface in the
cohort (53 f2p + 8 p2p), small Python repository, Python is the one language the
producer analyses in full, failed by 2 tests with 42 minutes of unused budget.

**awilix and adaptix are burned as clean targets.** Their failing tests were
read during this session's diagnosis, so a plan designed afterwards is
contaminated even though the harness never saw a test. aiomonitor's and
bandit-incremental's specific failing tests have NOT been inspected. Keep it
that way: look only at the reward.

---

## Reproducing the analysis

Scripts live in the session scratchpad and are worth re-creating if lost:

- per-task partial credit and P2P regressions, parsed from Pier's
  `Reward / Count` block in each job log (order: reward, f2p_total, f2p_passed,
  p2p_total, p2p_passed, then three fractions)
- head-to-head against the frozen control at
  `D:\gt_runs\deepswe_gtoff_31824834187\deepswe-central-31824834187-merged\DEEPSWE_EVALUATION_RESULTS.json`
- difficulty weighting from `https://deepswe.datacurve.ai/artifacts/v1.1/heatmap.json`

Do not re-run GT-off. Fetch baselines online or use the frozen local copies.
