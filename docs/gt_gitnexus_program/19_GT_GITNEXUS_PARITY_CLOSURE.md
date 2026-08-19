# GT × GitNexus delivery-parity closure

Status: implementation complete on the next release candidate; provider-free
proof is still required for the exact candidate before any paid run.

## G-1 — process composition

GitNexus returns process-shaped paths from entry points through terminal/cycle
boundaries. GT already had a certified bounded execution projection, but its
delivery receipt did not prove whether the returned view list was complete or
bounded. `RepositoryContextEngine._execution_views` now emits the explicit
`gt.certified_process.v1` profile and its depth, branching, view-limit,
entry/path, truncation, cycle, rejection, and lower-bound counters. The
provider delivery audit and release gate reject a non-empty process surface
without this certificate or with inconsistent counts.

This preserves GT's stricter uncertainty policy: only exact, preexisting,
high-confidence directed edges enter a process. Unknown, ambiguous, external,
or co-change-only links remain non-authoritative. The change imports GitNexus'
composition value without importing global-name guessing.

## G-2 — replacement evidence

GT's `SemanticUtilizationTracker` already matches typed action targets to
delivered anchors. Its summary now reports:

- `replacement_opportunities`: context used without a preceding read/search in
  the bounded window;
- `causal_claim_allowed: false`;
- `causal_claim_requires_matched_ablation: true`.

This is an observable trajectory-alignment proxy, not an internal model-use or
counterfactual claim. `scripts/central_process_ablation.py` compares matched
process-on/process-off receipt roots, reports delivery and alignment per task,
and explicitly refuses a causal claim until task/repository/model/scaffold,
evaluation, and complete receipt requirements are satisfied.

## G-3 — dense versus fallback

Every hybrid retrieval result now carries `gt.retrieval_status.v1` with separate
fields for expected mode, dense-channel presence, backend availability, query
attempt, candidate count, selected dense support, fallback use, and fallback
reason. The status is persisted in task-start retrieval and every preemptive
decision. A sparse/structural fallback can therefore never be reported as a
dense result merely because a dense backend was provisioned.

The dense release gate remains strict: applicable treatment still requires the
content-hashed, zero-network local backend receipt. This status addition does
not weaken that gate and does not turn retrieval delivery into solve causality.

## Verification boundary

Focused Python suites cover process coverage acceptance/rejection, retrieval
status separation, utilization accounting, delivery audit, release gate, and
the central agent. The authoritative next proof is the source-built Linux
provider-free workflow for the exact candidate. Only after that proof may a
matched 20-task paid validation be authorized; the outcome and efficiency
claims remain empirical.
