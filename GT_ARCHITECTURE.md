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
delivery, and zero extra calls/actions. GitHub provider-free certification and
paired decision-point utility remain required before freeze. End-to-end solve
uplift and non-regression remain unproven until the frozen GT-on evaluations.
