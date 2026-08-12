# GroundTruth central engine architecture

Authoritative date: 2026-08-11

GroundTruth is an in-process deterministic evidence and control layer owned by
`eval.gt_central_agent.MiniSweCentralAgent`. It is not an MCP sidecar and the
model does not invoke it.

```text
model-selected Bash action
  -> typed ProposedAction / SHADOW preflight
  -> host execution
  -> workspace + source revision sensor
  -> incremental certified graph refresh
  -> postflight validation + 17 feature runtime
  -> frozen hybrid retrieval for the next decision boundary
  -> typed GTContribution compiler
  -> provider-evidence ledger + exact request hash
  -> immediate next model request
```

## Retrieval profile

`gt_engine.retrieval_profile.FINAL_RETRIEVAL_PROFILE` is shared by ARB and the
live loop. It combines exact, lexical, BM25, structural, and pinned Snowflake
ONNX dense channels through the existing reciprocal-rank fusion. It ranks 20
files, selects at most eight complete evidence units inside 1,200 tokens, and
embeds at most 32 dense candidate spans. Active/changed paths and stale source
revisions retain the existing exclusion rules.

Cold retrieval has a 30-second deadline derived from the accepted ARB latency
distribution. Cached turns have a two-second fail-open deadline. Failure,
timeout, incomplete graph, or missing model asset produces abstention and does
not block Mini-SWE.

## Composition contract

Each potential provider payload becomes a `GTContribution` with surface,
kind, payload hash, claim/fact IDs, evidence action, eligible call, source
revision, and priority. `compile_contributions()` gives every candidate one
replayable disposition. Selection is complete-fact only; stale, expired,
future, duplicate, controller-only, and over-budget rows are not rendered.
The call receipt must satisfy candidate/accounted equality.

The compiler does not turn private engine work into model text. The provider
ledger remains the authority for actual dispatch, message indices, exact
request hash, and first-eligible timing.

## Paired decision-point capture

When replay capture is explicitly enabled, a visible GT call stores both the
provider-prepared control view before GT text and the dispatched treatment
view, plus the exact tool schema and compiled contribution metadata. The
validator reconstructs the treatment from the control and recorded payload;
any other byte difference rejects the case. This measurement path is inert
when capture is disabled and never adds a model or agent action.

## Active component authority

`gt_engine.component_registry` enumerates the active central subsystems and
derives all 17 feature contracts from executable inventories. The five
postflight-only features remain `GT_CHANGE_SURFACE`, `signature_delta`,
`GT_PATCH_DELTA`, `syntax_result`, and `covering_red`. A stochastic run is not
required to fire every feature; eligibility, abstention, firing, consumption,
and provider delivery remain separate statuses.

## Current evidence boundary

ARB workflow `31517629497` proves retrieval metrics only. Local real-ONNX
tests prove live cold/warm execution, dense availability, exact first-request
delivery, and zero extra calls/actions. Exact-tree GitHub provider-free run
`31527155811` passed at `90896d4`; paired decision-point utility remains
required before freeze. Archived run `31421610097` has zero eligible pairs
because it omitted exact controls. End-to-end solve
uplift and non-regression remain unproven until the frozen GT-on evaluations.

## Pre-execution decision sufficiency

The engine has a narrow, opt-in compiler between typed proposal normalization
and host execution:

```text
ProposedAction
  -> bounded target/structural-neighbor repository slice
  -> hybrid ranking without per-action dense inference
  -> exact selecting-request visibility check
  -> certified complete evidence bundle or PASS
  -> SHADOW receipt, or separately gated ASSISTIVE_SAFE return
```

It does not predict an action, rewrite a command, or add generic advice. A
single-target mutation is `RETURN_ELIGIBLE` only when one current
exact/mechanical or certified structural claim is missing from what the model
already saw. Semantic and graph revisions are checked independently. Ambiguous
parsing, incomplete state, staleness, sparse/dense-only evidence, co-change
evidence, duplicates, and complete-evidence budget overflow fail to `PASS`.

Visibility is certified from exact provider-prepared messages, including
ordinary Mini-SWE tool observations such as `sed` or `cat`; no marker or model
acknowledgement is used. A biting perturbation disabling this check caused a
duplicate second return, and the restored end-to-end test rejects it. DeepSWE
and Terminal-Bench workflows currently qualify this mechanism in `SHADOW`, so
it cannot change execution or add calls during treatment measurement.

## Substrate recovery invariants

Derived trees are pruned before manifest entry limits. Recovery after an
unhealthy sensor snapshot performs a complete supported-source rehash. Host
waiting exceeds the bounded index subprocess timeout, preventing a timed-out
coroutine from racing a live index worker. Final graph state comes from the
atomic repository session. `scripts/central_release_gate.py` rejects substrate,
dense, delivery, preflight, or decision-receipt violations before paid work.

## Final promotion repair (2026-08-12)

The live DeepSWE diagnostic exposed three objects that must not be collapsed
into one word such as "evidence": a repository candidate may be broad and
useful for ranking; a provider-deliverable content claim must name one complete,
grounded span; and a decision claim must additionally be mechanically material
to the exact proposed action.

`RetrievalCandidate.content_claim_id` now hashes only semantic content
(path/span/symbol/relation/text). Graph row IDs, channel receipts, revision IDs,
and delivery support do not create a new fact. `claim_hash` remains a
compatibility alias. Decision bundles carry a separate `decision_claim_id`
bound to content, operation, target, and support kind.

Graph structure is no longer file-only at delivery time. `StructuralLink`
retains source and target symbol/line endpoints from GraphDB. The structural
channel indexes every document span per path and selects the exact endpoint;
an unresolved endpoint remains rankable but receives
`edge_endpoint_unresolved` and cannot certify delivery or action return. RRF
retains its per-channel representatives, so an exact-path certificate cannot be
borrowed to deliver an unrelated structural span. Generic import and co-change
facts can rank context, but they cannot authorize pre-action return.

Retrieval is budget-first and event-accounted. A zero/closed delivery budget
runs no channel. A positive partial character budget is enforced while
complete spans are packed, so selection cannot precede a host-side budget
discard. Identical state/revision/visibility/configuration queries use
a bounded 128-entry result cache. Up to 3,000 of the 12,000 task characters is
reserved for post-mutation, diagnostic, and validation opportunities so
task-start and read/search traffic cannot consume the failure-recovery budget.
Every provider boundary records opportunity kind, candidates, selection,
delivery, abstention reason, cache status, latency, and exact visibility hashes.
This accounting is measurement, not a claim that a delivery helped.

The DeepSWE treatment workflow now enables bounded provider-budget compaction,
the fail-open completion controller, semantic progress control, and adaptive
validation timeouts. The release gate rejects disabled controls, work after a
closed budget, missing opportunity accounting, duplicate content claims, and
non-material or non-endpoint-aligned decision evidence. Preflight remains
`SHADOW`; no action-changing claim is made before a separately approved smoke.

Provider-free workflow `31616184187` passed the complete implementation gate on
runtime commit `80a8376`, with current native graph build, pinned Snowflake ONNX,
all-17/timing/context proof, `READY`, `SMOKE_APPROVED`, and zero provider calls.
This is architecture/integration evidence only; outcome and efficiency remain
live matched-smoke gates.
