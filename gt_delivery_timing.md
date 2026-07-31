# GroundTruth deterministic SDLC: delivery-timing diagnosis

Status: measured design defect and implementation contract  
Repository: `gt-harness` (`nano + GroundTruth`, not mini-swe)  
Primary live artifacts: runs `30601595795` and `30603315821`  
Frozen comparison: existing GT-off observations only; do not dispatch GT-off

## Executive finding

GroundTruth's premise is valid only when deterministic evidence replaces model
work. Deterministic bytes are not automatically efficient. Evidence delivered
after the corresponding decision, evidence that is too broad, or evidence that
does not constrain the next action adds context and can induce more search.

The current implementation proves transport and attribution, but does not yet
prove the intended deterministic SDLC:

1. the graph projection is built and ranked at task start, but the only
   canonical task-start delivery is `obligations`;
2. canonical `localization` waits for a later search-result trigger;
3. context compaction retains recent turns rather than authoritative semantic
   work state;
4. progress control knows iteration state but not remaining wall-clock budget;
5. verification frequently acts as a late submit refusal rather than an early
   executable contract; and
6. feature census counts wiring, not whether evidence arrived before the
   decision and avoided work.

The required efficiency relation is:

```text
avoided search + avoided wrong work + avoided verification loops
>
GT payload + GT-induced work
```

No superiority claim is valid until that relation holds at non-worse reward.

## What the two latest live runs show

### Feature census

Global witnessed identities did not fall:

| Metric | Run `30601595795` | Run `30603315821` | Interpretation |
|---|---:|---:|---|
| unique witnessed identities | 9 | 9 | unchanged |
| unique exercised identities | 16 | 15 | `def_partition` did not trigger |
| action-consistent identities | 8 | 8 | unchanged |
| sealed deliveries | 84 | 21 | intentional recovery deduplication |
| unexposed deliveries | 2 | 0 | fixed |
| forbidden harness-path attempts | 1 false positive | 0 | fixed |

Per-task witnessed identities:

| Task | Old | New | Material change |
|---|---:|---:|---|
| build-cython-ext | 5 | 4 | localization no longer delivered |
| headless-terminal | 6 | 8 | gained submit certificate/refusal |
| llm-inference-batching-scheduler | 7 | 7 | unchanged |
| reshard-c4-data | 6 | 6 | different trigger mix |
| sanitize-git-repo | 6 | 6 | unchanged |

The delivery-count reduction is mostly correct: per-signature progress
interventions were replaced by a maximum of two per task. The loss of build
localization and the missing `def_partition` exercise are separate timing or
eligibility findings, not consequences of deduplication.

### Canonical localization timing

`task_start()` extracts obligations, builds the graph projection, reranks graph
evidence, and seals event `0` as `obligations`. It does not seal a localization
fact. Ranked localization is produced by a later gateway search-result event.

Provider-confirmed timing in run `30603315821`:

| Task | First canonical localization | Exact evidence |
|---|---:|---|
| build-cython-ext | never | graph unavailable/cached-empty or subject mismatch |
| headless-terminal | provider iteration 2 | `base_terminal.py:4:BaseTerminal` |
| batching-scheduler | provider iteration 2 | `cost_model.py:align`, `baseline_packer.py:load_requests` |
| reshard-c4-data | provider iteration 29 | `decompress.py`, `compress.py` |
| sanitize-git-repo | never | irrelevant `tools/eval_expdb.py` candidate was suppressed |

The deterministic context checkpoint can render decision-linked graph lines,
but those bytes are not the canonical localization delivery and cannot be
counted as proof that the localization feature reached the model at step 0.
This dual path is both confusing and operationally weak.

### Wall-clock result

Five-way concurrency was correct. Four trials became faster or remained close;
one straggler dominated the workflow:

| Task | Old agent time | New agent time | Change |
|---|---:|---:|---|
| build | 8m45s | 7m58s | faster |
| headless | 11m27s | 7m42s | faster |
| batching | 13m19s | 30m00s | outer timeout |
| reshard | 10m01s | 11m14s | slightly slower |
| sanitizer | 13m11s | 2m22s | much faster |

At iteration 54, batching launched a model-authored `timeout 2400` sweep with
tool timeout 2500 seconds inside Harbor's 1800-second whole-agent budget. Nano
accepted the requested tool timeout because the inner tool runner has no
knowledge of the outer deadline. Harbor killed the trial at exactly 1800
seconds. The repository artifact passed all six verifier tests, but the trial
correctly lacked a clean terminal and verification-plan receipt.

### Frozen GT-off token comparison

`headless-terminal` has no valid completed frozen GT-off row. For the four
descriptively comparable tasks:

| Task | GT-off iter | GT-on iter | GT-off input | GT-on input | GT-off output | GT-on output |
|---|---:|---:|---:|---:|---:|---:|
| build | 82 | 100 | 2,680,318 | 905,998 | 21,094 | 28,558 |
| batching | 21 | 54 | 557,372 | 1,112,185 | 33,398 | 98,392 |
| reshard | 57 | 48 | 1,350,848 | 1,226,805 | 20,980 | 62,416 |
| sanitizer | 35 | 28 | 1,296,069 | 367,140 | 14,902 | 14,301 |
| **total** | **195** | **230** | **5,884,607** | **3,612,128** | **90,374** | **203,667** |

Aggregate GT-on changed input by -38.6%, output by +125.4%, and iterations by
+17.9%. GT-off solved 4/4. GT-on earned repository reward on 3/4, but only two
of those four were clean non-timeout passes.

Compared with the immediately preceding GT-on run, the new run used 40.9%
fewer iterations but 11.7% more input. Average input per iteration rose from
8,148 to 15,394 (+88.9%) because retaining up to eight recent turns restored
memory by spending substantially more request context. Recent transcript is
not equivalent to compact semantic state.

## Required deterministic SDLC timing

### Task start: before provider iteration 1

One compact orientation block must contain:

- complete issue-derived obligations;
- top ranked files and symbols with a short relevance claim;
- proven repository precedents when applicable;
- the initial executable verification contract; and
- explicit uncertainty when graph evidence is unavailable.

The block remains one dose, but attribution records independent receipts for
`obligations`, `localization`, and `GT_LOC_RESLOT` when their bytes are present.

### Research: immediately after a view or search

Deliver only novel, decision-relevant facts:

- definitions separated from references;
- verified callers and contracts;
- relation or value-flow facts connected to the active target;
- repository precedent for an intended new file; and
- a reslotted localization only when it improves on step-0 orientation.

### Pre-edit: before edit execution

The edit must not execute until deterministic state records:

- target path and symbol;
- current file preimage;
- affected callers/registries/siblings;
- new-file precedent when the target does not exist;
- relevant obligation IDs; and
- the verification commands invalidated by the proposed edit.

This checkpoint may stay model-quiet when there is no new actionable evidence,
but it must be auditable before the tool dispatch.

### Post-edit: before the next provider request

Record and, when actionable, deliver:

- actual before/after patch delta;
- signature changes;
- syntax/compiler result;
- affected callers and covering checks;
- graph refresh revision; and
- invalidated verification receipts.

### Test and recovery

Map an observed result to edited surfaces and obligations. A recovery
intervention must name:

- the falsified hypothesis or repeated no-gain action;
- the attributable RED;
- the smallest graph-backed discriminating action; and
- the remaining time/iteration affordability of that action.

Generic "try something different" text is insufficient.

### Verify and submit

Verification is an early contract, not merely a late refusal. Before submission
GT must have fresh executable receipts for the changed behavior. A refusal
must name the exact missing or failing receipt and must not repeat unchanged.

### Wall-clock boundary

The outer agent deadline must be propagated into nano. Before each tool call:

```text
allowed tool time =
min(model requested timeout, remaining agent time - finalization reserve)
```

When the reserve is reached, exploratory tools are rejected and the next
provider request receives a deterministic verify-and-finish state. GT must
never allow a command whose requested runtime exceeds the remaining trial.

## Typed context contract

Active provider context should preserve authoritative state, not a fixed number
of recent turns:

1. original task;
2. compact obligations and their verification states;
3. current ranked work surface;
4. decisions made and hypotheses ruled out;
5. changed files and concise patch intent;
6. latest attributable RED/GREEN receipts;
7. unresolved obligations;
8. current smallest useful next action; and
9. at most one or two raw complete tool turns needed to perform that action.

Obsolete searches, installation logs, repeated outputs, superseded plans, and
already-exposed GT capsules must not remain in the active request merely
because they are recent.

## Observable invariants

For every eligible feature:

```text
trigger observed
→ producer completed
→ bytes or deterministic state applied
→ provider request receipt
→ immediate model response receipt
→ next action classified
```

Additional timing invariants:

- task-start localization is present in provider iteration 1 when ranked
  locations exist;
- pre-edit checkpoint precedes the edit tool execution;
- post-edit evidence is present no later than the next provider request;
- no delivery is sealed without a following provider budget;
- no requested tool timeout exceeds remaining wall-clock affordability;
- a fresh passing verification transitions toward termination rather than more
  exploration; and
- feature census distinguishes eligible, suppressed, delivered, exposed,
  action-consistent, helpful, and harmful.

## Implementation sequence

1. Add RED tests that reproduce missing step-0 localization, oversized retained
   context, unaffordable tool timeout, and delivery-after-decision timing.
2. Build a single task-start orientation renderer from the task contract and
   graph projection.
3. Record compound task-start feature/capability receipts without duplicating
   model-facing bytes.
4. Replace fixed eight-turn retention with typed state plus a small adaptive
   raw tail.
5. propagate an outer deadline and reserve into nano's tool dispatcher;
   clamp/reject unaffordable calls and render verify-and-finish state.
6. Make timing and action-effect rows first-class live-gate requirements.
7. Run focused tests, 17-feature tests, full regressions, Ruff, exact replay,
   then the real five-task DeepSeek V4 Flash smoke at temperature 1,
   Profile 2, timeout multiplier 1.0, and concurrency 5.

## Acceptance gates

The next live candidate is accepted only when:

- all five tasks start in parallel with concurrency exactly 5;
- every task with ranked graph locations receives localization in provider
  iteration 1;
- all sealed deliveries are provider- and response-confirmed;
- all pre/post/test/verify/submit timing invariants pass;
- no task has a tool timeout larger than its remaining agent budget;
- no task ends in an agent timeout or unexposable terminal delivery;
- reward is non-worse than the frozen comparable baseline;
- input, output, iterations, and wall time are reported per task;
- token reduction does not hide a correctness regression; and
- stable superiority is claimed only after repeated GT-on trials because
  temperature 1 is stochastic.

