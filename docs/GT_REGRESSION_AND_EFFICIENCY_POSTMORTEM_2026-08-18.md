# GroundTruth Regression and Efficiency Postmortem

Date: 2026-08-18

Confidence: high for implementation defects and archived-smoke accounting;
moderate for predicted outcome impact; unknown for final solve lift until the
frozen comparison runs.

## Executive verdict

GroundTruth's main regression was not simply an insufficient graph. The benchmark
path combined four more direct failures:

1. the intended relational/semantic treatment was not actually selected;
2. evidence authority was not preserved after model-authored source appeared;
3. multiple context surfaces could restate related information without a shared
   lifetime budget; and
4. action/call accounting could misclassify timing and lifecycle validity.

The archived smoke also shows that long-task slowness was dominated by the coding
model's retained reasoning and continued exploration. FEAL ended with 532,036
provider characters, including 474,430 assistant-reasoning characters. GT cannot
delete that reasoning under the current behavioral contract. The correct response
is to tightly bound GT's own additions and expose the residual cause, not silently
apply lossy compaction and call it equivalent.

The highest-value GitNexus lesson is composition: compute one bounded relational
answer before the next existing model decision, preserve resolution uncertainty,
and avoid another model-selected search turn. The implementation adopts that
pattern while retaining GroundTruth's compiler/LSP-capable evidence, host-owned
validation, and 17+1 mechanism identity.

## Evidence boundary

- Harness smoke source: `40b5332d0bbd91560f5118ffdcd98654ec1eb503`.
- Full GroundTruth repository examined:
  `04c3da7e55cc9f776d492aeee396682c52f84f08`.
- Archived smoke workflow: `32106687133`.
- GitNexus mechanisms come from the existing official-source audit. GitNexus is
  not an evaluation arm.
- Current repairs are working-tree changes and therefore do not yet have a final
  exact commit SHA.

No grader-only artifact is used by the implementation or this diagnosis.

## What the smoke actually ran

```text
task + workspace
  -> GraphDB / hybrid retrieval
  -> one persistent-state bootstrap
  -> central_pes_v1
     + task-semantic context
     + persistent-state advisory frames
     + legacy feature/frontier/preemptive surfaces
  -> existing Mini-SWE provider loop
```

The inspected receipts explicitly report:

- `treatment_profile=central_pes_v1`;
- `relational_context=false`; and
- `semantic_evidence=false`.

Therefore the 7/10 smoke is not a test of `RepositoryContextEngine` or
`central_relational_v2`.

## Measured result and inefficiency

| Arm | Solve | Calls | Steps | Total tokens | Uncached input |
|---|---:|---:|---:|---:|---:|
| Frozen GT off | 8/10 | 506 | unavailable | 29,974,968 | 651,492 |
| Previous GT | 4/10 | 500 | 489 | 26,208,749 | 598,598 |
| Smoke GT | 7/10 | 648 | 634 | 35,856,511 | 1,252,041 |

The smoke improved over previous GT but remained one solve below GT off and used
substantially more calls and uncached input. Its negative flips against GT off
were FEAL, video processing, and winning average Core Wars.

FEAL is the clearest slowness witness:

- 68 provider calls;
- 55 compaction deferrals;
- zero compactions;
- 532,036 final provider characters; and
- 474,430 assistant-reasoning characters.

That distribution rules out indexing as the primary cause of the measured
slowdown. Index latency can still fail a treatment, but it does not explain the
dominant token/call growth in this smoke.

## Root-cause registry

| Cause | Observed failure | Repair | Remaining risk |
|---|---|---|---|
| Wrong treatment identity | Relational and semantic engines were disabled in the smoke. | Typed `central_relational_v2` descriptor, generated runtime args, contract hash, fail-closed profile gate. | Must be proven in a new exact-commit receipt. |
| Origin laundering | New model-authored paths could appear as pre-existing relational endpoints. | Endpoint origin/revision/authority carried through PES and shared contributions; unsafe origins are controller-only. | Correctness still depends on complete workspace transition capture. |
| Duplicate relational surfaces | PES advisory frames could overlap repository context. | Under relational v2, PES keeps state/control duties while repository context owns advisory relational text. | Legacy profiles retain their old behavior. |
| No lifetime evidence cap | Per-call packing allowed cumulative GT growth. | Shared 4,096-token discretionary-evidence budget with 512-token critical reserve and audited commits; mandatory bounded PES lifecycle frames are exempt but remain request-bounded. | A lower cap can omit useful noncritical evidence; measure abstention. |
| Ordinal mismatch | Evidence action numbers were compared with provider call numbers. | Timing uses completed-action counts; action conservation is separately receipted. | Old receipts cannot satisfy the new release contract. |
| Conflated actions | Selected actions looked executed around returns/cancellations. | Selected = processed + cancelled; processed = executed + returned. | Executor/provider failures remain externally caused. |
| False duplicate failure | Rejected duplicate candidates could fail release. | Candidate duplication and applied duplicate intervention are separate metrics. | Repeated candidates still describe model behavior. |
| Synthetic benchmark identity | Workflow/merge duplicated feature args and fixed values. | Caller-owned descriptor and one run-wide benchmark manifest; exact SHA/model/step budget and complete timeout-policy map are derived and audited, and all effective runtime kwargs must match. | Hosted artifact plumbing still needs proof. |
| Long retained reasoning | Difficult tasks repeatedly explored and accumulated assistant history. | GT additions are lifetime-bounded; deferrals identify the reasoning-preservation boundary. | GT cannot remove distinct reasoning without changing the scaffold contract. |

## Strengthened architecture

```text
legal task instruction + exact workspace + observed execution
  -> source-origin ledger and revision-current GraphDB
  -> five-channel HybridRetriever
  -> one bounded bootstrap (when graph-applicable)
  -> PersistentExecutionStateEngine
       private control state, obligations, preflight/postflight/rebase
  -> RepositoryContextEngine
       certified semantic facts
       directed execution/process view
       reverse impact / tests / routes / consumers
       explicit unknown/external/ambiguous refusal
  -> shared ContributionTaskBudget
       discretionary regular budget + protected critical reserve
       mandatory request-bounded PES lifecycle context
       claim-complete provenance and materiality admission
       cross-surface deduplication
  -> first eligible existing provider request
  -> action/postflight transition and exact delivery receipt
```

There is no extra model-selected GT exploration call after bootstrap. Repository
context is additive to an existing provider request and is not a durable duplicate
history stream.

## What was learned from GitNexus

### Adopted engineering patterns

- precompose a relational answer rather than expose raw edges and ask the model
  to walk them;
- group directed call/process/impact evidence in one bounded response;
- make unresolved, external, ambiguous, stale, and weak resolution terminal;
- deliver at an existing action boundary instead of adding exploration turns;
- use persistent, revision-bound repository intelligence and explicit staleness;
- prefer precision over recall for provider-visible relationships.

### GroundTruth assets retained

- compiler/LSP-derived definitions, signatures, types, diagnostics, and language
  semantics when durably available;
- host-owned validation classification and postflight observation;
- runtime/introspection knowledge only when legally observed in the task
  environment;
- source-revision binding, incremental graph refresh, delivery hashes, and exact
  provider-view audits;
- the central 17+1 mechanism census and one persistent execution state.

### Not copied

- no GitNexus benchmark arm;
- no replacement Tree-sitter/indexing subsystem;
- no architecture clustering without a measured failure that requires it;
- no embedding-only authority;
- no global weak-name fallback or fuzzy autocorrection;
- no model-selected GT tool loop; and
- no lossy deletion of distinct assistant reasoning.

## Implementation map

| Area | Files | Result |
|---|---|---|
| Treatment and benchmark identity | `eval/treatments/tb2_central_relational_v2.json`, `scripts/render_treatment_agent_args.py`, `gt_engine/treatment_adapter.py`, TB2 workflow | Caller-derived exact identity; no silent profile fallback or duplicate fixed step limit. |
| Contribution admission/budget | `gt_engine/contributions.py`, `eval/gt_central_agent.py` | Claim-complete origin/authority/materiality checks, cumulative discretionary accounting, and mandatory PES continuity. |
| Origin-safe persistent state | `gt_engine/persistent_execution_state.py` | Endpoint origin survives graph revisions; model-authored relations cannot become repository advice. |
| Task semantics | `gt_engine/task_semantic_substrate.py` | Model-authored/generated facts stay controller-only; timing uses action ordinal. |
| Unified relational delivery | `gt_engine/repository_context.py`, `eval/gt_central_agent.py` | One provenance-bearing repository contribution; PES advisory text is private in relational v2. |
| Audits | `gt_engine/delivery_audit.py`, `scripts/central_trajectory_audit.py`, `scripts/central_release_gate.py`, `scripts/tb2_merge_results.py` | Unsafe/missing origins, lifecycle conservation, task budget, all runtime kwargs, one run-wide manifest, and benchmark parity fail closed. |

## What remains unsolved

1. **Final outcome effect is unknown.** Local tests prove contracts, not solve
   lift.
2. **Model over-exploration can still dominate.** GT now bounds its additions but
   cannot force the model to stop while preserving the existing scaffold.
3. **Graph-nonapplicable tasks receive only universal task semantics.** That is
   intentional, not a fabricated graph fallback.
4. **Hidden-only behavioral conventions remain outside legal evidence.** GT must
   abstain rather than infer verifier-only facts.
5. **Historical legal workspaces are incomplete.** Frozen predictions must not be
   called executed replays where source workspaces are unavailable.
6. **Hosted integration is not yet re-proven.** The working tree must become one
   exact commit and pass the Linux source-built provider-free workflow.

## Final verification sequence

1. Complete local full-suite, static, YAML, bytecode, and diff verification.
2. Freeze the implementation in one exact commit.
3. Run the source-built Linux provider-free workflow for that exact SHA; require
   zero provider calls and all treatment identity/budget/lifecycle gates.
4. Freeze the updated 20-task predictions before observing outcomes.
5. Run only strengthened GT on frozen `repair20-v1` and compare offline with the
   existing GT-off and previous-GT artifacts.
6. Report resolve, flips, calls, steps, tokens, cost, evidence, latency,
   abstentions, and every invalid/provider-censored row.
7. Proceed to DeepSWE only after TB2.0 passes its release criteria.

The release objective remains parity or better on resolve rate with fewer or
equal reasoning steps/tokens and fewer negative flips. The implementation is now
structured to test that claim honestly; it does not yet prove it.
