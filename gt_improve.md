# GT Improvement Plan: From Attributable Wiring to Measured Advantage

Status: implementation plan  
Repository: `gt-harness`  
Runtime: nano-harness with GroundTruth (GT)  
Last diagnosed live run: `30582455019`, commit `4694257`  
Confidence: high on the diagnosed defects; moderate that the proposed changes
will improve outcomes until matched repeated live runs establish the effect.

## Decision

GT is a deterministic evidence and control engine for nano-harness. It is not
the coding agent and must not perform open-ended reasoning. Nano owns ideation,
planning, code generation, and tool choice. GT must improve those activities by
supplying bounded repository evidence and enforcing checkable SDLC invariants
at the decision point where they matter.

The current engine has crossed the attribution threshold: sealed GT bytes can
be proved in the provider-final request, linked to the response, and associated
with the next action. It has not crossed the utility threshold. The latest run
solved only two of five tasks and greatly increased tokens and iterations
against the available, imperfect GT-off comparison.

The objective is therefore:

> Improve solved tasks per provider token and per iteration while preserving
> correct-or-quiet evidence, exact provider attribution, and lifecycle timing.

No paid smoke is justified merely because a feature path exists. Offline,
replay, integration, audit, and configuration gates must pass first. The final
candidate proof must then be a real nano + GT provider run, not an offline or
pre-modelled simulation.

## Current evidence

Run `30582455019` used `deepseek-v4-flash`, temperature `1`, Profile 2,
concurrency `4`, timeout multiplier `1.0`, and the exact five-task workflow
slice. Both the workflow gate and an independent local rerun passed.

It proved:

- all five task contracts reached the provider-final request byte-for-byte;
- all 17 canonical identities were censused on every task;
- nine identities were live-witnessed across the run;
- no eligible identity went dark;
- observed lifecycle opportunities were recorded at task start, research,
  pre-edit, post-edit, test, verify, and submit;
- all 14 trustworthy `graph.db` surfaces were inventoried;
- graph projection, role routing, and obligation accounting executed; and
- attribution used structured provider-bound payload blocks, not trajectory
  substring guesses.

It also proved that wiring is insufficient:

| Task | Reward | Principal miss |
|---|---:|---|
| `build-cython-ext` | 0 | Left `np.int` in `ccomplexity.pyx`; exhausted 100 iterations |
| `headless-terminal` | 1 | Solved |
| `llm-inference-batching-scheduler` | 0 | Bucket 2 was 36.66m against a 32m threshold; exhausted 100 iterations |
| `reshard-c4-data` | 1 | Solved |
| `sanitize-git-repo` | 0 | Excluded `exp_data/`, missed a second HF token, and had 13 localization candidates over-suppressed |

Across the four tasks with a graded historical GT-off observation, GT-off was
4/4 and the latest GT-on was 1/4. GT-on used 55.4% more iterations, 114.0% more
input tokens, 78.3% more output tokens, 23.1% more tool results, and 23.5% more
tool errors. Those arms differed in timeout and temperature configuration, so
these are descriptive observations, not causal estimates.

The run sealed 13,810 GT characters but repeatedly exposed them for roughly
821,971 characters across provider requests: about 59.5x amplification.

### Tool-error diagnosis

Raw tool-error count is not a valid quality metric. Across the four graded
historical pairs, GT-on produced 42 errors versus 34 GT-off, an increase of 8.
Across all five GT-on tasks there were 51:

| Task | GT-off | GT-on | Difference |
|---|---:|---:|---:|
| `build-cython-ext` | 15 | 19 | +4 |
| `headless-terminal` | 0 partial | 9 | not comparable: GT-off was OOM-killed after 7 iterations |
| `llm-inference-batching-scheduler` | 1 | 17 | +16 |
| `reshard-c4-data` | 0 | 5 | +5 |
| `sanitize-git-repo` | 18 | 1 | -17 |

The counts mix genuine failing builds, useful RED self-checks, intended
no-match searches, missing dependencies, malformed one-off commands,
unavailable binaries, timeouts, edit-precondition misses, and shell crashes.
The GT-off sanitizer passed despite 18 errors, many from negative searches and
bad-path probes. Error count alone therefore measures neither GT health nor
agent competence.

Response-to-observation linkage narrows, but does not settle, causality:

- 48/51 GT-on errors followed requests containing only previously issued,
  persistent GT capsules;
- a newly issued build localization capsule was followed by a useful failing
  probe that exposed `np.float`;
- a newly issued reshard localization capsule was followed by a useful failing
  decompression probe that exposed a missing `argparse` import; and
- the sanitizer submit refusal was followed by a validation script containing
  `exit`, which killed nano's persistent shell and produced
  `Shell process exited unexpectedly`.

This does not exonerate GT. The task-start contract persisted in every later
request, so its longer-term effect is confounded. It does prove that future
analysis must separate new from persistent capsules and useful RED from harmful
tool misuse.

## Non-goals

- GT will not replace nano's reasoning policy.
- GT will not dump `graph.db` into the prompt.
- GT will not force all 17 identities to deliver on every task.
- GT will not infer behavior from lexical overlap alone.
- GT will not expose hidden tests or verifier-only information.
- GT will not optimize feature-fire count.
- GT will not claim superiority from one temperature-1 run.

## Target operating model

```text
issue
  -> complete TaskContract
  -> typed executable predicates
  -> task-role capability pack
  -> fresh semantic graph projection
  -> stage transaction
  -> deterministic utility arbiter
  -> one bounded ephemeral capsule
  -> provider-final request
  -> response
  -> action and tool outcome
  -> progress/recovery governor
  -> executable verify
  -> submit or precise refusal
```

Durable facts and receipts live in host state. Only evidence still useful for
the current decision belongs in the provider request.

## Invariants

1. **Correct or quiet:** unsupported, stale, or irrelevant evidence is worse
   than silence.
2. **Opportunity, not frequency:** every genuine trigger reaches a named
   terminal state; more deliveries are not intrinsically better.
3. **Provider-final attribution:** only exact sealed bytes found in the final
   structured request count as delivery.
4. **Freshness:** patch, graph, contract, and verification revisions agree.
5. **One bounded dose:** at most one intervention per observation unless a
   specified coalition is demonstrably better.
6. **Stage locality:** deliver at the earliest useful lifecycle boundary and
   expire after that decision.
7. **Executable completion:** requirements are verified by semantic checks
   against affected surfaces.
8. **Visible abstention:** suppression, expiry, ineligibility, and failure have
   explicit reasons.
9. **Outcome before rhetoric:** wiring, behavior, efficiency, and outcome are
   separate claims.

## Workstream 1: Executable obligation verification

### Defect

`gt_engine/task_contract.py::matching_obligation_ids` maps passing commands to
requirements using shared tokens. `gt_engine/bridge.py` can credit the whole
contract after a generic full-suite command. Neither proves that every
requirement was exercised.

### Change

Compile obligations into typed predicates such as:

- test selector;
- content presence or absence over an explicit scope;
- artifact existence or schema;
- numeric threshold;
- build/import success; and
- command/output contract.

Each predicate receipt records obligation, scope, command and output hashes,
workspace revision, action, and `pass`, `fail`, `unknown`, or `stale`.
An obligation becomes verified only when its required fresh predicates pass.
Uncompilable requirements remain unknown. A generic test pass cannot certify
unrelated content, artifact, or numeric obligations.

### Code and tests

- Add `gt_engine/verification_contract.py`.
- Replace or demote lexical matching in `gt_engine/task_contract.py`.
- Update verification and submit certification in `gt_engine/bridge.py`.
- Add predicate state to `scripts/gt_audit.py` and `scripts/gt_live_gate.py`.
- Test unrelated full-suite passes, scoped scans, exact numeric values,
  post-edit staleness, and multi-obligation selectors.

### Acceptance

- No lexical-only verified transition.
- Every verified obligation has a fresh executable receipt.
- Replay keeps `np.int`, the 32m threshold, and repository-wide token absence
  unresolved.
- Refusal delivers the smallest unresolved predicate set.

## Workstream 2: Semantic use of `graph.db`

### Defect

`GraphProjection` currently returns files, symbols, node IDs, and hit counts.
`properties` and `assertions` are counted but discarded.
`edge_metadata`, `file_hashes`, and `project_meta` are inventory-only.

### Change

Project typed, ranked evidence with source surface, provenance, confidence,
revision, and intended lifecycle use:

| Surface | Required semantic use |
|---|---|
| `nodes` | Canonical identity, symbol kind, source/test role |
| `nodes_fts` | Ranked name/path localization |
| `symbol_content_fts` | Implementation-body matches and spans |
| `content_passages` | Bounded source excerpt and line provenance |
| `content_passages_fts` | Requirement-specific passage retrieval |
| `edges` | Typed caller, callee, import, inheritance, and test relations |
| `edge_metadata` | Relation provenance, confidence, and stale filtering |
| `closure` | Bounded transitive impact surface |
| `properties` | Signature, decorator, schema, constant, and stored properties |
| `assertions` | Existing invariants and verification predicate candidates |
| `cochanges` | Ranked companion surface with count/recency |
| `cochange_sets` | Concrete precedent/change sets |
| `file_hashes` | Freshness and receipt invalidation |
| `project_meta` | Index schema, revision, and compatibility |

Preserve rank and provenance instead of flattening results into sets. Query
only role-relevant surfaces; never dump the database.

### Acceptance

- Every trustworthy surface changes a typed projection or has an explicit
  `inventory_only_by_design` outcome.
- Every graph fact has surface and revision provenance.
- Replay localizes `ccomplexity.pyx` and the complete sanitizer scope.
- Prompt bytes stay inside the dose budget.

## Workstream 3: Atomic graph wake and refresh

### Defect

`gt_engine/bridge.py::_refresh_graph` updates `self.graph_db` but does not
rebuild `self._graph_projection` or `self._evidence_router`. Clone-late and
create-late tasks use a new database pointer with dormant task context.

### Change

Make refresh an atomic transaction:

1. update the index;
2. validate the revision;
3. rebuild the task projection;
4. rebuild/version the router;
5. invalidate graph-dependent receipts;
6. record old/new revisions and outcome.

On failure, retain the last internally consistent snapshot.

### Acceptance

- `build-cython-ext` and `reshard-c4-data` gain populated post-wake
  projections.
- Router paths and evidence revisions change with refresh.
- Audit rejects database/projection/router revision mismatch.

## Workstream 4: Challenge incomplete content-search scope

### Defect

For `content_scan`, `gt_engine/evidence_router.py` suppresses candidates outside
the model's observed search paths. In the sanitizer failure, an explicit
`exp_data/` exclusion became the boundary of truth and suppressed 13 graph
candidates.

### Change

Parse search inclusions and exclusions into a scope receipt. Observed scope is
evidence, not authority. When the contract requires repository-wide coverage,
one fresh high-confidence candidate outside the searched scope may become a
bounded `scope_gap` containing:

- required root;
- observed inclusions/exclusions;
- relevant candidate outside scope;
- provenance; and
- a deterministic next check.

Unrelated graph neighbors remain suppressed. Positive unresolved scope gaps
block submit.

### Acceptance

- Sanitizer replay identifies excluded `exp_data/` before submit.
- The 13 suppressions collapse into ranked named outcomes and at most one
  corrective capsule.
- Content-scan tasks still reject call-graph noise.

## Workstream 5: Early progress and recovery

### Defect

Recovery requires the same formal failure across an intervening source edit.
The bridge explicitly omits degenerate-loop detection and escalation. Two
tasks exhausted 100 iterations without recovery.

### Change

Track deterministic progress in unresolved predicates, patch fingerprint,
failure fingerprint, localization frontier, verified count, test outcome, and
submit readiness. Add a configurable state machine:

```text
PROGRESS
  -> STALLED
  -> CONTRADICTED
  -> ESCALATED
  -> BUDGET_RISK
  -> RECOVERED
```

Calibrate thresholds in shadow mode from stored trajectories. Deliver a bounded
steer only after acceptable shadow precision. Allow one escalation after a
delivered recovery produces no material transition.

### Acceptance

- Replay detects both 100-iteration stalls before exhaustion.
- Improving state never triggers a stall.
- Environment errors do not masquerade as source contradictions.
- Recovery and escalation are provider-bound and action-linked.

## Workstream 6: Ephemeral GT context

### Defect

GT text remains in conversation history and is resent repeatedly, causing about
59.5x exposure amplification and stale competition.

### Change

Give each capsule:

- issue action and decision stage;
- graph/workspace revisions;
- expiry condition;
- supersession key;
- maximum exposure count; and
- resolution state.

Build a separate provider-bound request view containing only active capsules.
Do not mutate the forensic trajectory. Expired bytes disappear from later
requests while hashes and attribution receipts remain durable.

### Acceptance

- Task-start contracts can be superseded by compact unresolved deltas.
- Post-edit capsules expire after the decision they govern.
- Provider block-list tests prove expired text is absent.
- Repeated GT input bytes fall at least 50% in five-trajectory replay.

## Workstream 7: Deterministic utility arbitration

### Defect

The one-dose arbiter limits volume but does not explicitly decide whether a
candidate is worth its context and interruption cost.

### Change

Use documented bounded factors:

```text
utility =
    severity
  * evidence_strength
  * actionability
  * freshness
  * unresolved_relevance
  * expected_information_gain
  - repetition_cost
  - token_cost
  - interruption_cost
  - false_positive_risk
```

This is not a learned reasoner. Every component comes from deterministic
receipts. Admission requires highest coalition score and a minimum threshold;
silence is valid. Penalize already exposed facts and actions nano is already
taking.

### Acceptance

- Every delivery has an inspectable score decomposition.
- Fresh failing predicates outrank repeated localization.
- All-low candidates produce `utility_abstain`.
- Replay materially reduces equivalent repeated deliveries.

## Workstream 8: Task-role capability packs

### Defect

The current roles affect routing but do not define a complete
lifecycle-specific evidence and verification policy.

### Change

Configure stable canonical features through declarative packs:

| Pack | Evidence | Verification |
|---|---|---|
| Code/build | Build metadata, bodies, callers, tests, impact | Build, import, targeted behavior, API surface |
| Data transform | Schemas, invariants, reference patterns, numeric obligations | Samples, conservation, order, schema, thresholds |
| Content scan | Required root, patterns, tracked/untracked scope, exclusions | Complete-scope absence and placeholder correctness |
| Artifact/CLI | Expected paths, entry points, executable contract | Existence, invocation, output/schema |
| Service/system | Config, process, port, dependency topology | Health, protocol, persistence |

Allow deterministic multi-label selection when necessary. Record pack version
on every routing and verification decision.

### Acceptance

- The five smoke tasks select the intended pack(s).
- Content tasks avoid caller noise.
- Build tasks receive compile/import and impact predicates.
- Data tasks preserve exact numeric thresholds.

## Workstream 9: Matched repeated experiments

### Defect

The current GT-off comparison differs in timeout and temperature, includes an
ungraded task, and has no repetitions.

### Change

Separate these claims:

| Claim | Required evidence |
|---|---|
| Wiring | Complete census and terminal outcomes at correct lifecycle stages |
| Attribution | Exact provider-final bytes, linked response, linked action |
| Behavior | Fresh actionable evidence, action consistency, low false intervention |
| Efficiency | Matched repetitions with lower cost at non-worse reward |
| Outcome | Matched repetitions with higher reward and acceptable cost |

Freeze exact tasks/order, substrate, nano version, commit except intended GT
change, model, explicit temperature, timeout, iteration limit, concurrency,
prompt/tools, adapter, and grader. Run at least three paired repetitions; five
are preferred.

Candidate arms:

1. GT-off;
2. attribution-only, with no model-facing GT bytes;
3. contract/verification only;
4. semantic graph;
5. progress governor;
6. full GT.

Use replay to eliminate broken arms before paid execution. Report every task
before aggregates. Primary metrics are reward, input tokens per reward,
iterations per reward, and wall time per reward.

### Acceptance

- Workflow rejects configuration mismatch.
- Every artifact carries the full configuration receipt.
- Provider block lists are inspected structurally.
- Reports distinguish observation, causal estimate, and hypothesis.

## Workstream 10: Tool outcomes and GT-induced misuse

This is a cross-cutting safety/measurement requirement, not an eighteenth
canonical feature.

### Defect

All nonzero tool results currently feed one aggregate. Attribution links GT to
a response and tool name but does not classify the observation, its information
gain, or whether the capsule was new or merely persistent. Nano's persistent
bash process can also be killed by top-level `exit` in model-generated checks.

### Change

Classify every error:

- `useful_red`;
- `expected_negative_probe`;
- `agent_command_error`;
- `tool_contract_error`;
- `dependency_or_environment`;
- `timeout_or_resource`;
- `shell_lifecycle`;
- `product_failure`; or
- `unknown`.

Link request, response, active delivery IDs, new/persistent exposure position,
capsule age, tool call, observation, information gain, next recovery action,
and comparable off event.

Detect top-level `exit`/`logout` in persistent-shell commands and run that
command in an isolated child shell or reject it precisely. Do not silently
rewrite arbitrary shell semantics. Feed repeated harmful outcomes—not useful
RED—into progress and utility penalties.

### Acceptance

- All 51 stored GT-on errors receive a class and reason.
- `unknown` is below a predeclared limit.
- The sanitizer counterfactual cannot kill the persistent shell.
- Useful RED and harmful errors are reported separately per task.
- New-capsule attribution is separated from persistent context.

## Dependency-ordered execution

### Phase 0: Measurement freeze and replay

Deliver:

- preserve run `30582455019` as failure fixtures;
- exact capsule exposure/expiry metrics;
- tool-outcome taxonomy and response-to-observation linkage;
- persistent-shell lifecycle protection;
- matched workflow receipts;
- deterministic replay for predicates, routing, progress, and utility; and
- goldens for the three failed tasks.

Exit:

- reproduce graph wake, sanitizer suppression, absent recovery, lexical
  verification, capsule amplification, and all 51 tool outcomes;
- prove provider block-list handling is structural; and
- keep the complete suite green.

### Phase 1: Truthful completion

Implement workstreams 1 and 8. Exit when every smoke task has role-appropriate
predicates and all three known incomplete patches remain correctly unverified.

### Phase 2: Complete and fresh repository evidence

Implement workstreams 2, 3, and 4. Exit when clone-late tasks have post-wake
projections, sanitizer scope is complete, revision mismatch fails audit, and
graph bytes remain bounded.

### Phase 3: Reduce waste and prevent exhaustion

Implement workstreams 5, 6, and 7. Exit when both historical stalls are found
early, repeated GT exposure falls at least 50%, every capsule expires, and
every intervention has a utility decision.

### Phase 4: Pre-live audit

Run:

- full unit and integration suite;
- repository static/format checks;
- five-trajectory replay;
- complete 17-identity census;
- all lifecycle boundary tests;
- provider block-list attribution tests;
- graph surface/revision/wake tests;
- predicate freshness and refusal tests;
- context expiry/exposure tests;
- tool-outcome and shell-lifecycle tests;
- progress shadow precision review; and
- workflow/substrate parity audit.

The audit emits exactly:

- `GO_LIVE`;
- `NO_GO_CODE`; or
- `NO_GO_EXPERIMENT`.

### Phase 5: Real nano + GT live run

Dispatch `.github/workflows/tb2_gt.yml` only after `GO_LIVE`:

- nano-harness with GT, not Mini-SWE;
- `deepseek-v4-flash` only;
- explicit temperature `1`;
- Profile 2;
- exact task slice:
  `build-cython-ext,headless-terminal,llm-inference-batching-scheduler,reshard-c4-data,sanitize-git-repo`;
- concurrency `4`, unless the paired arm freezes another value;
- timeout multiplier `1.0`;
- exact expected count `5`; and
- strict contract, profile, lifecycle, provider attribution, feature census,
  behavior flag, and action-consistency gates.

Every trial must contain result/reward, nano trajectory, GT ledger and sealed
deliveries, provider receipts, response/action/observation linkage, roles and
predicates, graph revisions, capsule lifecycle, progress, utility, and
classified tool outcomes.

One run is a candidate observation. Improvement requires the matched repeated
protocol.

## Five-task acceptance matrix

| Task | Required GT opportunity | Proof required before submit |
|---|---|---|
| `build-cython-ext` | Graph wake, build pack, compiled-source impact | All affected Cython sources checked for removed aliases; build/import pass |
| `headless-terminal` | Code/CLI pack | Required terminal behavior and repository checks pass |
| `llm-inference-batching-scheduler` | Data pack, exact numeric obligations | Structured per-bucket thresholds, including bucket 2 ≤ 32m |
| `reshard-c4-data` | Graph wake, data/artifact pack | Schema, shards, order/conservation, and CLI checks |
| `sanitize-git-repo` | Content pack, repository scope challenge | Complete-scope sensitive-content absence and placeholders |

## Telemetry and gate additions

Recommended events:

- `contract.predicate_compiled|observed|invalidated`
- `graph.context_refreshed|refresh_failed`
- `search.scope_observed|scope_gap`
- `progress.transition`
- `recovery.shadow_candidate`
- `capsule.issued|exposed|expired|superseded`
- `utility.scored|abstained`
- `tool.outcome_classified`

Every event includes episode/action, lifecycle stage, role-pack version,
workspace/graph revisions, evidence hashes, decision/reason, and provider
request/response/action linkage when model-facing.

`scripts/gt_audit.py` must report per task:

- predicate state by obligation;
- graph revisions, surface semantics, and refresh consistency;
- search inclusions/exclusions and scope gaps;
- progress/recovery transitions;
- unique, repeated, and expired capsule bytes;
- utility winners and suppressions;
- tool-outcome class, information gain, exposure position, and recovery; and
- configuration parity.

`scripts/gt_live_gate.py` must fail on:

- verified obligations without fresh executable receipts;
- stale/mismatched graph evidence;
- unresolved eligible repository scope gaps;
- capsules exceeding exposure policy;
- interventions without utility decisions;
- harmful tool errors lacking the response/action chain;
- top-level `exit` still killing the persistent shell;
- eligible-dark identities;
- missing provider attribution/response linkage; or
- comparison mismatch.

It must not fail because an ineligible feature stayed quiet.

## Reviewable implementation slices

1. Measurement, outcome taxonomy, shell protection, and replay fixtures.
2. Predicate compiler/evaluator and audit schema.
3. Role packs and five-task predicate adapters.
4. Semantic graph projection and freshness.
5. Atomic graph wake and router revisioning.
6. Content-scope challenge.
7. Progress ledger and recovery shadow mode.
8. Ephemeral provider request view.
9. Utility arbiter.
10. Recovery delivery after shadow review.
11. Workflow parity, live dispatch, and result report.

Every slice needs unit tests, replay, audit compatibility, and a rollback flag
when it changes model-facing behavior.

## Stop/go rules

Do not dispatch if:

- a known incomplete patch can be certified;
- graph wake retains an old projection/router;
- sanitizer exclusions remain invisible;
- historical stalls have no shadow transition;
- repeated GT exposure is unbounded;
- utility/expiry is unauditable;
- tool outcomes are unclassified or checks can kill the shell;
- attribution relies on trajectory text;
- experiment parity is ambiguous; or
- the local suite is red.

Claim improvement only after matched repetitions show higher reward, or
non-worse reward with materially lower cost, without hiding a catastrophic
task-level regression. Flat reward with higher cost means GT is worse. A
single positive temperature-1 run is promising but inconclusive.

## Definition of done

1. Completion credit is predicate-backed.
2. Every trustworthy graph surface is semantically used or explicitly
   abstained from.
3. Graph wake atomically refreshes projection and routing.
4. Strong repository evidence can challenge incomplete searches.
5. Stalls and contradictions are detected before exhaustion.
6. GT context expires and repeated exposure is bounded.
7. Every intervention passes deterministic utility admission.
8. Role packs provide task-appropriate SDLC support.
9. Experiments are matched and repeated.
10. Tool outcomes are classified and harmful GT-linked misuse is prevented or
    surfaced.
11. All 17 identities retain complete per-task terminal-state accounting.
12. Every delivery is provider-final attributable and action-linked.
13. A real nano + GT run passes strict audit with a per-task result report.

## Research basis

- [Terminal-Bench](https://arxiv.org/abs/2601.11868): hard multi-step terminal
  tasks and comprehensive end-state tests make correctness the primary target.
- [SWE-agent](https://arxiv.org/abs/2405.15793) and its
  [ACI documentation](https://swe-agent.com/0.7/background/aci/): interface
  design and concise purpose-built interaction surfaces affect performance.
- [Agentless](https://arxiv.org/abs/2407.01489): bounded localization, repair,
  and validation can outperform more complex agent loops at lower cost.
- [SWT-Bench](https://arxiv.org/abs/2406.12952): executable fail-to-pass tests
  support more precise completion decisions.
- [Failure as Process](https://arxiv.org/abs/2607.09510): many failures begin
  before final submission, supporting early progress controls.
- [HarnessFix](https://arxiv.org/abs/2606.06324): trace-grounded cross-layer
  diagnosis is superior to treating final failure as an isolated model error.

## Repository evidence

- `gt_features.md`: historical/current feature map and run `30582455019`
  diagnosis.
- `gt_engine/task_contract.py`: contract extraction and lexical matching.
- `gt_engine/graph_context.py`: 14-surface inventory and task projection.
- `gt_engine/evidence_router.py`: role/relevance suppression.
- `gt_engine/bridge.py`: lifecycle, refresh, recovery, verification, delivery,
  and attribution.
- `scripts/gt_audit.py` and `scripts/gt_live_gate.py`: evidence accounting and
  acceptance.
- `.github/workflows/tb2_gt.yml`: real nano + GT Terminal-Bench workflow.
