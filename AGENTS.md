# GT central-runtime behavioral contract

The active GT-on implementation is `eval.gt_central_agent:MiniSweCentralAgent`.
It is a host-owned engine, not a task-container package, prompt add-on, or
model-invoked sidecar. It owns the model loop and observes every model-selected
command before and after host-side execution.

## What counts as GT working

Keep these states distinct in every audit:

1. **Receipt:** a FACT or CAP payload was produced at the correct action and
   workspace revision. This proves observation, not trajectory influence.
2. **Controller decision:** the engine ran lint, validation/readiness policy,
   or a one-time submit hold. A `PASS` is a real decision but does not alter the
   model's next action.
3. **Intervention:** the engine either holds a submission or sends one bounded,
   grounded payload into the immediately following model request. Only this can
   be credited with changing a trajectory.

Private receipts must never be mistaken for an inactive engine. Conversely,
receipt counts must never be claimed as causal help.

## Active delivery policy

The engine may deliver only new, grounded control evidence:

- a concrete changed-file syntax failure;
- a real, structurally recognized validation failure;
- the same failure repeating at the same command/revision;
- an anchored signature/caller impact;
- a one-time submit hold for a fresh grounded failing check; or
- `GT_EDIT_CHECK` validation debt: three material source revisions occurred
  without a completed recognized behavioral check, and the task supplied a
  declared check.

Validation debt is emitted once, before the next decision, carries the declared
check and changed paths, and resets after a successful recognized validation.
Interpreter/test cache artifacts (`__pycache__`, `.pyc`, pytest/mypy caches)
are not material source edits. Generic obligations, search echoes, passing
syntax checks, CAP aliases, and submission certificates remain private.

Every active delivery must be receipt-audited for evidence action, revision,
next-decision timing, non-prediction, non-lateness, one-shot deduplication, and
causal use. Do not re-enable the historical generic guidance stream; its 94
advisories in run `30869649342` were the documented context/token regression.

## Live-run gate

Before any paid smoke, run focused lint/tests and the provider-free all-17
census. Then replay archived trajectories through the policy and confirm that
the intervention is reachable only on its intended lifecycle state. A smoke is
confirmation, never exploratory debugging. The 89-task run remains blocked
until outcome preservation and repeated outcome-first efficiency gates pass.
