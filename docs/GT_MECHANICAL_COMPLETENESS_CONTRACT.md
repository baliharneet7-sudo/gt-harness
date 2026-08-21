Exit code: 0
Wall time: 0.3 seconds
Output:
# GroundTruth mechanical-completeness contract

## Claim

For the final `central_relational_v2` treatment, GroundTruth does not certify a
task merely because the agent loop returned or because 18 mechanisms were
configured. A task is mechanically complete only when every applicable GT
lifecycle requirement was executed against current state and independently
audited. The only terminal requirement states are `SATISFIED` and
`PROVEN_NOT_APPLICABLE`. `FAILED`, pending, missing, stale, skipped, inferred,
or unaccounted evidence blocks the task and the run.

This is a guarantee about GT execution, state, delivery, and auditability. It
is not a claim that a stochastic coding model must solve every task.

## Admission and applicability

Task semantics always run from the legal benchmark sources: the instruction,
the transferred workspace, and observed execution results. Repository
intelligence is applicable when supported source exists. A genuinely
source-less workspace records `PROVEN_NOT_APPLICABLE` for graph-only work, but
continues task-semantic processing. If the model creates supported source,
applicability changes in the same action postflight: GT must build and certify
the graph, retrieval corpus, deterministic persistent selection, and current
state before the next provider request. A failed activation is not an accepted
fallback; it blocks release certification.

## Provider barrier

Immediately before every final-profile executor provider call,
[`evaluate_provider_barrier`](../gt_engine/mechanical_completeness.py) proves:

1. the exact request and provider-view SHA-256 identities exist;
2. the bounded workspace snapshot is complete;
3. the graph is current when applicable, or non-applicability is explicit;
4. every previously selected action is executed, returned, or cancelled;
5. every context fact is accounted;
6. every contribution candidate is accounted;
7. every provider-visible claim has an admissible exact
   `gt.provider_value.v1` certificate naming authority, materiality, novelty,
   anchors, decision point, and the exploration operation it replaces; and
8. exact replay capture is enabled.

The host records the barrier in both the model-call row and the task-level
runtime ledger. A failure sets `MechanicalCompletenessBlocked` before
`model.query()`; no request is dispatched from incomplete or stale GT state.

## Terminal task certificate

After the trajectory, replay bundle, and intervention chain are finalized, the
agent embeds `gt.task_execution_certificate.v1` in `central_receipt.json`.
[`build_task_certificate`](../scripts/central_release_gate.py) recomputes the
following independent requirements:

- treatment identity and exact runtime arguments;
- repository substrate and dense retrieval;
- delivery timing, hashes, message indices, novelty, and grounding;
- contribution budget and complete candidate accounting;
- provider information-value certificates proving novelty, decision point, and
  the ordinary search/read/rediscovery operation each visible claim replaces;
- selected/processed/executed/returned/cancelled action conservation;
- task semantics and convergence preflights;
- assistive preflight precision;
- decision sufficiency;
- persistent-state initialization, selection, reads, preflights, postflights,
  deliveries, and graph rebases;
- composed repository context;
- the 17+1 product-mechanism census;
- outcome-preservation controls;
- project validation and retrieval-efficiency accounting;
- a current passing validation bound to the final source revision after a
  material change whenever a source-derived check exists;
- exact replay and intervention-chain coverage; and
- every live provider barrier.

The merge gate recomputes these requirements again and compares their statuses
with the embedded certificate. A receipt cannot authorize itself by writing
`PASS`.

Provider route identity is also non-circular. The merge joins the immutable
release route contract, the actual one-call bootstrap canary response identity,
and every task receipt's configured endpoint and executor response identity.
Expected route metadata alone cannot certify an observed route.

The completion requirement is separately typed. `gt.completion_plan.v1` may
authorize submission only when it is executable and every
`gt.completion_predicate_observation.v1` in the current
`gt.completion_certificate.v1` passes at the same workspace revision. A stale,
missing, failing, or partial predicate blocks automatic submission and release.

Repository convention evidence is also compositional. An exact convention may
be provider-visible only when signature/type evidence, at least one certified
caller, and at least one certified test agree. Conflicting type evidence is an
audited abstention, never a guessed convention.

## Intervention and model-reasoning audit

Every visible intervention is joined as:

`source/workspace observation -> certified claim -> selected contribution -> exact provider request -> next observable model action`

The canonical `gt.intervention_chain.v2` records delivery surface, claim IDs,
source revision, request hash, provider-view hash, changed message index,
timing, and the next action. Behavioral uptake is based only on observable
actions and text present in retained trajectory artifacts. GT never claims to
read hidden chain-of-thought; `hidden_reasoning_inferred` must be `false`.
Consequently the audit can truthfully say “GT delivered fact X before call N,
and the next observable action used anchor Y,” while causal uplift still
requires a matched baseline or ablation.

## Run-level release invariant

The same frozen `repair20-v1` task set is mandatory. All 20 task artifacts must
exist. Every task certificate must pass. The release manifest, prediction,
baseline, treatment descriptor, task set, runtime commit, source-built indexer,
pinned dense asset, and benchmark manifest must match their recorded
identities. Any missing task or artifact remains in the denominator and blocks
promotion.

Harbor results are loaded only through `scripts.harbor_results`. Aggregate and
per-trial rows are normalized, identical duplicates are deduplicated,
conflicting duplicates and unexpected tasks fail, and every missing expected
task blocks the run. A row with verifier rewards remains graded even if Harbor
also records a nonzero agent exit after submission.

The paid workflow has no replay-off switch and no alternate profile. Its
secret-free release-identity job and reusable provider-free certification must
pass before the bootstrap canary or task matrix can start.

## Authoritative outputs

- Per-call proof: `model_call_contexts[*].mechanical_completeness_barrier`
- Per-task proof: `central_receipt.json.task_execution_certificate`
- Per-task causal audit: `intervention_chain.json` and `gt_replay/manifest.json`
- Run proof: `merged.json`, integrity/solve/efficiency/intervention reports
- No-spend proof: `mechanical-completeness.json`
- Release identity: [`active_release.json`](../eval/release/active_release.json)

The no-spend proof is valid only from a clean tracked worktree. The gate checks
tracked status before verifying the manifest so uncommitted runtime changes can
never inherit a PASS from an older release commit.
