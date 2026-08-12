# GroundTruth Persistent Execution State — Final Implementation Status

**Date:** 2026-08-12
**Runtime implementation SHA:** `e0c63ae15be6eeff9eae67ffe873f3b44e2da31f`
**Status:** IMPLEMENTED AND PROVIDER-FREE CERTIFIED; NOT BENCHMARK-PROVEN

## Executive result

The graph-first persistent execution-state mechanism is implemented in the active
Mini-SWE central agent. It is not a second autonomous agent and it does not replace
the existing 17-feature engine. After the repository graph is built and validated,
GroundTruth performs one bounded bootstrap model call that may select only
catalogued, graph-backed items. It then maintains typed state deterministically at
every executor boundary and exposes only a bounded current slice to the next normal
model request.

The authoritative provider-free workflow `31647174958` passed at the runtime SHA
above. It built the current indexer from source, provisioned the pinned Snowflake
Arctic ONNX asset, ran the central tests and readiness gates, printed `READY` and
`SMOKE_APPROVED`, and uploaded a receipt with `provider_calls: 0`. This proves
implementation integrity and delivery accounting. It does **not** prove solve-rate
uplift, flips, no regression, or efficiency on a sampled model run.

## What shipped

### Graph-first lifecycle

```text
task enters MiniSweCentralAgent
  -> build and validate repository graph
  -> shared five-channel HybridRetriever runs once
  -> result seeds the bootstrap catalog and the first live retrieval cache
  -> one bounded temp=0 bootstrap call selects catalog IDs (no action executes)
  -> executor provider request receives the current state slice
  -> preflight projects the proposed action into state
  -> host executes the original action
  -> postflight commits observed result, validation, diff, and obligations
  -> source refresh rebases the graph and invalidates stale labels
  -> next provider request receives the updated state slice
```

The state kernel is `gt_engine/persistent_execution_state.py`. The active loop is
`eval/gt_central_agent.py`. Retrieval is shared with the accepted ARB path through
`gt_engine.hybrid_retrieval.HybridRetriever`; the initial retrieval result is reused
to avoid duplicate task-start dense/ranking work.

### Determinism boundary

| Component | Behavior |
|---|---|
| Graph build, source revision, language resolution | Deterministic and fail-closed |
| Exact/lexical/BM25/Snowflake-ONNX/structural retrieval | Deterministic for a fixed checkout and asset |
| Catalog construction and evidence provenance | Deterministic |
| Bootstrap selection | One bounded model call; returns catalog IDs only |
| State transitions, validation consumption, graph rebase | Deterministic; unknown evidence causes no mutation |
| Context packing, deduplication, request receipts | Deterministic |
| Executor action choice and code edits | Model-driven Mini-SWE behavior |
| Replanning/advisor loops, command rewrite, feature suppression | Not present |

The mechanism therefore constrains non-determinism to one bounded bootstrap choice
and the ordinary executor. It does not claim to make a temperature-1 model
deterministic.

## State used repeatedly

The artifact is task-scoped and held in memory; it is not a one-time Markdown plan.
The same state object is consumed and updated at these boundaries:

1. **Initialization:** graph-backed catalog, task requirements, current revision.
2. **Provider compilation:** active phase, focus, obligations, evidence gaps, and
   recent deterministic deltas are packed into one bounded frame.
3. **Preflight:** the proposed typed action is associated with the current state
   before `environment.exec`.
4. **Postflight:** action result, validation classification, changed paths, and
   newly discovered obligations update the state.
5. **Graph rebase:** source changes refresh the graph; stale graph labels are
   removed before any later frame can expose them.

No additional executor action is created by state maintenance. Bootstrap calls,
executor calls, and effective actions are counted separately in deep metrics.

## Correct delivery contract

The model receives only a bounded declarative state frame in the normal provider
request. It contains source-backed claims, active obligations, current focus, and
deterministic progress/validation state that are absent from retained history. It
does not contain raw Bash programs, heredoc bodies, speculative file choices, or a
free-form plan. Existing Mini-SWE observations remain intact.

Every prepared request is audited for:

- exact provider request hash and message index;
- one first-eligible delivery, never predictive or late;
- source/workspace revision validity;
- evidence provenance and token/character budget;
- duplicate suppression and complete accounting;
- state initialization, boundary use, and graph-current status.

Private state transitions are not counted as model influence. A receipt proves
production; a controller disposition proves internal consumption; only an exact
provider-visible frame proves delivery. Solve causality still requires a matched
control/treatment trajectory comparison.

## Defects found and repaired before certification

- Production GraphDB relations are normalized across the bounded certified aliases;
  uppercase `CALLS`/`ASSERTED_BY` data no longer disappears at the state boundary.
- Validation obligations consume the shared canonical
  `ValidationClassification.declared_check_id`; wrapped commands do not require
  unsafe raw-command reparsing.
- Reads cannot satisfy a creation/deliverable obligation.
- Unknown or pending validation cannot be converted into a fabricated failure.
- Invalid or timed-out bootstrap cannot invent a ranked focus.
- Initial graph retrieval and first live retrieval share one result/cache key.
- Graph rebase removes stale labels after source changes.

## Certification evidence

Workflow `31647174958` passed these mandatory provider-free census lines:

```text
ALL_17_PRODUCERS_PROVEN
ALL_17_CONSUMERS_PROVEN
ALL_EFFECTS_TIMING_VALID
ALL_PAYLOADS_GROUNDED
ALL_17_CONSUMER_PATHS_PROVEN
ALL_17_TRIGGERS_PROVEN
ALL_17_PAYLOADS_CONCRETE
ALL_17_CONSUMERS_APPLIED
ALL_VISIBLE_PAYLOADS_IN_FIRST_ELIGIBLE_REQUEST
NO_ACTIONS_BLOCKED
ALL_EFFECTS_CONTEXT_ACCOUNTED
READY
SMOKE_APPROVED
```

The workflow also passed source-built graph coverage, pinned ONNX provisioning,
central release tests, static checks, and byte-compilation. The local Windows
checked-in `vendor/gt-index.exe` remains an intentionally known stale-binary
witness; it lacks current Objective-C support. It must not be used to override or
weaken the source-built Linux gate.

## What is not proven

The following claims remain unproven until a paid, contemporaneous matched run:

1. GT-on resolves more tasks than GT-off.
2. GT creates positive flips without GT-attributable losses.
3. GT reduces tokens, calls, actions, steps, wall time, or cost after counting the
   bootstrap call and all effective controller actions.
4. Persistent state improves multi-file completeness or validation success.
5. The mechanism generalizes to DeepSWE or Terminal-Bench without regressions.

The historical GT-off artifacts remain the control reference supplied by the user;
they are not a same-commit proof for this new treatment. No paid run was launched
in this documentation pass.

## Release gates and remaining TODOs

### Completed

- [x] Implement graph-first persistent state.
- [x] Use one bounded catalog-ID bootstrap after graph construction.
- [x] Reuse the initial HybridRetriever result at the first live retrieval boundary.
- [x] Update state at provider, preflight, postflight, and graph-rebase boundaries.
- [x] Add exact delivery, state-transition, bootstrap, and resource accounting.
- [x] Add regression tests for graph relations, validation identity, reads, and
      invalid bootstrap.
- [x] Pass the exact source-built provider-free release gate.

### Remaining, in order

1. **Freeze a paid diagnostic manifest.** Pin model/checkpoint, prompt, task set,
   wrapper, temperature, timeout, tool schema, graph/indexer revision, ONNX hash,
   and evaluator. Keep GT-off and GT-on identical except for the treatment switch.
2. **Run one bounded matched diagnostic** on a predeclared mixture of historical
   gains, losses, both-fail tasks, source-applicable tasks, and legitimate
   no-source tasks. This requires separate paid-run authorization.
3. **Audit every trajectory** for graph applicability, one bootstrap/zero bootstrap
   actions, cache reuse, state-boundary receipts, exact next-request delivery,
   stale-state rejection, outer timeout/censoring, and complete resource counts.
4. **Compute outcome-first comparisons:** resolved, gained, lost, both-pass,
   both-fail, uncensored resolved, total/executor/bootstrap calls, tokens, actions,
   steps, wall time, cost, and per-task Pareto status.
5. **Apply the release decision.** Any GT-attributable loss or invalid delivery
   blocks expansion. A non-regressive positive result permits the frozen mechanism
   to proceed to the planned DeepSWE and Terminal-Bench evaluation arms.
6. **Do not tune the state mechanism against individual task IDs** after seeing the
   diagnostic. A failed gate requires a new explicit defect diagnosis and plan.

## Immediate next step

The next action is **not another provider-free rerun** and not the 89-task benchmark.
The implementation gate is already certified. The next action is to prepare and
review the matched paid diagnostic manifest, then dispatch it only after explicit
authorization. Until that approval, the correct project state is:

```text
runtime integrity: PASS
deterministic state lifecycle: PASS
provider-visible delivery accounting: PASS (provider-free proof)
outcome uplift: UNKNOWN
regression safety: UNKNOWN
efficiency: UNKNOWN
full benchmark readiness: BLOCKED on live matched evidence
```

## Authoritative files

- `gt_engine/persistent_execution_state.py`
- `eval/gt_central_agent.py`
- `scripts/central_release_gate.py`
- `scripts/central_readiness_audit.py`
- `scripts/central_pre_smoke_gate.py`
- `GT_PERSISTENT_EXECUTION_STATE_RESEARCH.md`
- `GT_PERSISTENT_EXECUTION_STATE_IMPLEMENTATION_PLAN.md`
- `AGENTS.md`
- `CLAUDE.md`
- `GT_ARCHITECTURE.md`
