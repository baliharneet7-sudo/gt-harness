Exit code: 0
Wall time: 0.2 seconds
Output:
# 01 — Current GroundTruth architecture

## Evidence boundary and versions

This document describes two different systems and does not merge their evidence:

- **Current source:** `18f95fbc366d5857f090b304a04c5bd6861ef7db` (`18f95fb`).
- **Latest completed 20-task treatment:** workflow `32163376177`, source `e423c87bb9380850c4db1427dbc1423f53d97711` (`e423c87`). Its merged artifacts are under `D:\tmp\run32163376177-merged\`; task receipts and trajectories are under `D:\tmp\run32163376177\`.

The source changes between those commits repair receipt/accounting defects, but there is no exact-`18f95fb` live receipt yet. “Implemented at HEAD” therefore does not mean “validated in the matched run.” Confidence labels mean: **high** = directly established by current code or a typed receipt; **moderate** = consistent evidence from more than one artifact but not a causal experiment; **low** = plausible interpretation; **unknown** = the required observation does not exist.

Benchmark contamination boundary: GT may derive provider-visible facts only from the instruction, repository source in the task workspace, and the agent's already-observed execution results. Post-hoc reward is used below only for outcome accounting. Hidden verifier artifacts, reference solutions, and host verifier output are never admissible runtime evidence. This is the contract in the [mechanical completeness contract](../GT_MECHANICAL_COMPLETENESS_CONTRACT.md).

## A. Current full GT

The production architecture is a host-owned control loop, not a prompt appendix and not a task-container tool:

```text
task instruction + transferred workspace + observed execution
                    |
                    v
         workspace/source revision sensor
                    |
       +------------+-------------+
       |                          |
 graph-independent facts      repository mirror
 TaskSemanticSubstrate            |
                                  v
                       GraphDB/index + validation
                                  |
                    +-------------+-------------+
                    |                           |
             HybridRetriever          relational/context engines
                    |                           |
                    +-------------+-------------+
                                  v
                    PersistentExecutionState
                                  |
    model response -> typed ProposedAction -> preflight -> environment.exec
                                             |                 |
                                             +----postflight---+
                                                      |
                                          refresh/rebase if changed
                                                      |
                         contribution compiler + delivery audit
                                                      |
                                  exact next provider request
```

### Host loop and revision ownership

- [eval/gt_central_agent.py](../../eval/gt_central_agent.py) — `MiniSweCentralAgent` owns model requests, normalizes Bash calls, runs preflight, executes actions, commits postflight state, refreshes the graph, compiles provider context, and writes the central receipt. It is the active benchmark implementation. **Confidence: high.**
- [gt_engine/central_runtime.py](../../gt_engine/central_runtime.py) — workspace sensing, validation/source revision accounting, feature production, and central runtime state. Raw workspace changes and validation-relevant source changes are distinct. **High.**
- [gt_engine/repository_mirror.py](../../gt_engine/repository_mirror.py) and [gt_engine/indexer.py](../../gt_engine/indexer.py) — transfer the bounded checkout and build/refresh the local graph. The indexer implementation is built from [vendor/gt-index-src](../../vendor/gt-index-src) on the authoritative Linux gate. **High.**

### Repository intelligence and retrieval

- [gt_engine/repository_intelligence.py](../../gt_engine/repository_intelligence.py) — graph applicability, schema/coverage/revision checks, repository frontier production, and graph refresh lifecycle. Missing or stale source-backed graphs fail closed. **High.**
- [gt_engine/hybrid_retrieval.py](../../gt_engine/hybrid_retrieval.py) — the shared `HybridRetriever`. Its independent channels are exact path/symbol, lexical overlap, BM25, local Snowflake Arctic ONNX dense retrieval, and certified graph structure. It applies equal-weight reciprocal-rank fusion (`k=60`) and packs at most eight complete spans. Dense errors abstain; they do not fabricate facts. **High.**
- [gt_engine/repository_context.py](../../gt_engine/repository_context.py) and [gt_engine/relational_context.py](../../gt_engine/relational_context.py) — relational-v2 composition over definitions/signatures, directed calls, reverse impact, tests, routes, re-exports, inheritance, and overrides. Ambiguous, unresolved, external, global-fallback, and unknown edges are rejected rather than guessed. **High.**
- [gt_engine/task_semantic_substrate.py](../../gt_engine/task_semantic_substrate.py) — graph-independent facts derived from the instruction and bounded workspace: declared checks, deliverables, structural binary format, and focus anchors. This keeps source-less tasks from being blind without fabricating graph facts. **High.**

### Living state and intervention

- [gt_engine/persistent_execution_state.py](../../gt_engine/persistent_execution_state.py) — task-scoped graph-first state. It receives one bounded bootstrap selection, then deterministic `compile_context`, `project_preflight`, `commit_postflight`, and `rebase_graph` transitions. A source edit invalidates graph state until refresh completes. **High.**
- [gt_engine/convergence_controller.py](../../gt_engine/convergence_controller.py) — narrow assistive convergence, validation/declaration probes, forbidden-path protection, and budget-state response. It may return an action to the model but may not rewrite or silently suppress a command. **High.**
- [gt_engine/contributions.py](../../gt_engine/contributions.py) — bounded, revision-aware contribution selection and task-budget accounting. **High.**
- [gt_engine/delivery_audit.py](../../gt_engine/delivery_audit.py) — authoritative certification of provider-visible deliveries. It checks claim identity, first-eligible timing, provider-view and request hashes, changed message indices, grounding, and surface-specific certificates. **High.**

### Product surface beyond the benchmark adapter

[src/groundtruth/mcp/tools.py](../../src/groundtruth/mcp/tools.py) exposes a broader MCP/product surface. Historical GT also contains LSP-oriented definitions/references/types, runtime-KB facilities, impact and validation tooling. Those are part of full GT, but the Mini-SWE/DeepSWE scaffolds do not invoke the MCP tool surface. Several imports also depend on the external GroundTruth package. Their existence must not be reported as benchmark treatment use. **Implementation confidence: moderate; benchmark-use confidence: high that they were not exercised as MCP tools.**

## B. GT as exercised by run 32163376177

The run used `MiniSweCentralAgent`, the `central_relational_v2` treatment profile, `certified_active` policy, and `assistive_safe` preflight. It enabled repository intelligence, preemptive retrieval, relational context, semantic evidence, persistent execution state, completion/progress/context controls, all 17 legacy features, and the pinned dense backend. `merged.json` records temperature `1.0`, `max_steps=100`, one trial per task, and no retries.

What was demonstrably exercised:

- All 20 tasks built a source-backed graph with valid schema and nonzero graph nodes/edges. No task was denominator-excluded. **High.**
- Dense retrieval was available on all 20 tasks. `invalid_dense_backend_tasks` is empty. **High.**
- Persistent execution state passed aggregate lifecycle validation: 20 bootstrap calls, 3,006 lifecycle uses, 920 context compilations, 959 preflights, 913 postflights, and 194 graph rebases. **High.**
- All tasks received at least one provider-visible GT delivery. The observed surfaces were feature guidance, observed execution, progress, persistent state, repository context, and task semantic substrate. **High.**
- Sixteen of 17 legacy features fired naturally. `recovery` was the only non-natural trigger; its path was exercised only by a forced proof. **High.**
- Operational controls produced 39 submit holds, one completion evaluation, two completion probes, and 105 recap receipts with no recap fallback. **High.**

What was not established:

- Provider delivery certification failed on `count-dataset-tokens` and `llm-inference-batching-scheduler` because changing decisive facts reused a stable underlying claim identity. Therefore “payload existed” is not equivalent to a valid delivery certificate. **High.**
- Analytical repository-intelligence status failed on `largest-eigenval` and `portfolio-optimization` solely with `material_frontier_not_delivered`. Their graphs and dense backends were healthy. This is a downstream frontier-rendering/accounting failure, not substrate unavailability. **High.**
- The treatment release gate failed on 13 tasks because of contribution usage mismatches, unconsumed terminal effects, or the duplicate-claim defects. **High.**
- No receipt proves that the model internally used a delivered fact. Exact provider-view hashes prove exposure; model-action causality remains **unknown** without a matched decision replay or ablation.
- No full-product MCP call, LSP session, or runtime-KB correction is present in these benchmark receipts. **High.**

## The 17+1 accounting boundary

GT's integrated census is the 17 IDs in the executable `CENTRAL_FEATURE_IDS` registry plus `persistent_execution_state`. The universal task-semantic substrate is a delivery substrate, not a silently added nineteenth mechanism. In the run, 18/18 mechanisms were configured and persistent state was repeatedly exercised; this must not be rewritten as “18/18 legacy features fired.” The accurate result is “16/17 legacy features fired naturally, the recovery path was forced-only, and persistent state passed its repeated lifecycle.”

## Run defects versus current-source repairs

The following is a source comparison, not live validation:

| Run defect at `e423c87` | Current `18f95fb` repair | Evidence status |
|---|---|---|
| Final feature effects created after the normal consume boundary on `extract-elf`, `sanitize-git-repo`, and `torch-tensor-parallelism` | `MiniSweCentralAgent` performs a terminal `consume_effects` flush | Implemented; exact-HEAD receipt pending |
| Repository frontier registered material facts that were not actually rendered, and used the wrong revision/accounting boundary | Frontier contribution now registers only rendered facts and uses the frontier revision | Implemented; live gate pending |
| Per-task contribution token usage was not conserved in serialized accounting | Contribution serialization includes task budget token usage and limit | Implemented; live gate pending |
| Changing decisive values reused a stable fact ID and looked like duplicate provider claims | Delivery audit prioritizes fresh explicit claim IDs over stable underlying fact IDs | Implemented; live gate pending |

## Architecture conclusion

The current architecture is not missing its core substrate. The latest run proves a working graph-first lifecycle, dense retrieval, repeated persistent state, and exact provider-boundary delivery on most tasks. The active defects are at the composition, relevance, intervention-policy, and proof/accounting boundaries. The biggest underused gap is that full semantic assets—particularly resolved types/LSP/runtime knowledge and higher-level process/change-obligation composition—are not yet proven to reach the benchmark provider view. **Confidence: high on the substrate conclusion; moderate on which missing composition will create solves.**
