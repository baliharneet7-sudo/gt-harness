# GT central-runtime behavioral contract

The active GT-on implementation is `eval.gt_central_agent:MiniSweCentralAgent`.
It is a host-owned engine, not a task-container package, prompt add-on, or
model-invoked sidecar. It owns the model loop and observes every model-selected
command before and after host-side execution.

## What counts as GT working

Keep these states distinct in every audit:

1. **Receipt:** a FACT or CAP payload was produced at the correct action and
   source/workspace revision. This proves observation, not trajectory influence.
2. **Controller consumption/decision:** a registered consumer used the payload
   to change internal state, schedule a check, or interrupt a batch. A `PASS`
   is a real decision but does not alter the model's next action.
3. **Intervention:** the engine holds a submission, interrupts an already-planned
   action, or sends one bounded, grounded payload into the immediately following
   model request. Only this can be credited with changing a trajectory.

Private receipts must never be mistaken for an inactive engine. Conversely,
receipt counts must never be claimed as causal help.

## Source-revision model

The engine keeps two revisions: the raw workspace revision (audit) and a
validation-relevant source revision. Caches, compiled objects, binaries, build
products, logs, benchmark output, directories, and background writes never
advance source revision. Task-required deliverables satisfy obligations without
pretending to be source. Validation evidence goes stale only when authored
source changes.

## One validation classifier

Every executed action is classified exactly once in the agent. The immutable
`ValidationClassification` is shared by the feature runtime, the evidence
ledger, the receipt writer, and deep metrics. No component reparses the
command; runtime, ledger, and metrics cannot disagree about the same action.
Submit certificates report real current checks bound to the source revision.

## Active delivery policy

The engine may deliver only new, grounded control evidence that names concrete
anchors (paths, symbols, commands, diagnostics):

- a concrete changed-file syntax failure;
- a real, structurally recognized validation failure;
- the same failure repeating at an unchanged source revision;
- a signature delta with the affected symbol and caller impact;
- a one-time submit hold for a fresh grounded failing check; or
- `GT_EDIT_CHECK` validation debt: three source-revision-advancing authored
  edits occurred without a completed recognized behavioral check, and the task
  supplied a declared check.

A fresh syntax failure interrupts the remaining pre-decided actions in the same
model response; each cancelled action is recorded, not silently dropped.
Generic obligations, search echoes, passing syntax checks, CAP aliases, and
submission certificates remain private. If the engine cannot name the evidence,
the payload stays private and records `NO_OP_WITH_REASON`.

Every active delivery must be receipt-audited for evidence action, revision,
next-decision timing, non-prediction, non-lateness, one-shot deduplication, and
causal use. Do not re-enable the historical generic guidance stream; its 94
advisories in run `30869649342` were the documented context/token regression.

## Provider-free proof

`python -m scripts.central_feature_census` must print all five lines before any paid
run: `ALL_17_PRODUCERS_PROVEN`, `ALL_17_CONSUMERS_PROVEN`,
`ALL_EFFECTS_TIMING_VALID`, `ALL_PAYLOADS_GROUNDED`,
`ALL_17_CONSUMER_PATHS_PROVEN`. The census cannot pass on producer receipts
alone. `scripts/central_readiness_audit.py` must print `READY`.

## Live-run gate

Before any paid smoke, `python scripts/central_pre_smoke_gate.py` must print
`SMOKE_APPROVED` at the intended commit. It fails closed unless the exact paid
workflow timeout, the direct and module census entrypoints, all 17 agent-loop
producer/consumer effects, non-predictive/non-late timing, and submit-boundary
consumption are proven. Then replay archived trajectories through the policy and confirm that
the intervention is reachable only on its intended lifecycle state. A smoke is
confirmation, never exploratory debugging. The 89-task run remains blocked
until outcome preservation and repeated outcome-first efficiency gates pass.
