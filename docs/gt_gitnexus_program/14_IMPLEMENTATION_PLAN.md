# 14 — Implementation plan

## Outcome

Advance only when the frozen 20-task treatment has clean integrity and its solve/efficiency report is honest. The plan has three separate products:

1. **Type 1:** a receipt-complete, revision-current treatment whose failures can be trusted;
2. **Type 2:** action-relevant process/completion context that replaces exploration;
3. **Type 3:** certified coupled-change and convention evidence that creates additional solves.

The TB2 promotion workflow remains treatment-only on `repair20-v1`. Do not dispatch a new GT-off arm. Compare outcomes to the frozen local GT-off cohort descriptively and use legal-source same-state replay/ablations for mechanism evidence. The product census remains 17 historical features plus persistent execution state. Repository-context composition, identity-only nodes, and coupled obligations evolve those mechanisms; they do not create a nineteenth census entry.

## Current implementation state

| Item | Type | State | Required next proof |
|---|---|---|---|
| Terminal effect flush | Type 1 | Committed at `18f95fb`; live-unverified | Full suite, exact-commit provider-free, same-20 receipts |
| Fresh decisive delivery claim identity | Type 1 | Committed; live-unverified | Changed/unchanged/reverted claim tests and live delivery audit |
| Rendered frontier/revision accounting | Type 1 | Committed; live-unverified | largest/portfolio receipt witnesses |
| Contribution task-token conservation | Type 1 | Committed; live-unverified | per-call/task conservation on all 20 |
| Root-search classifier and neutral provider wording | Type 1/2 | Candidate commit; full local matrix passes | Exact-SHA provider-free and extract/tensor/video trajectory witnesses |
| Declaration-free identity-only `File` nodes | Type 2 | Candidate commit; Python consumers, full Go, and Codespaces/Linux tests pass | Exact-SHA provider-free proof and live qemu receipt |
| Action-relevant semantic filtering | Type 2 | Candidate commit; focused projection tests pass | sanitize replay and live relevance receipts |
| Graph DB/manifest pair certification and publication lock | Type 1 | Candidate commit; mismatch/lock/rollback/interruption tests pass | Exact-SHA Linux provider-free proof |
| Advisory `CoupledChangeObligation` | Type 3 | Candidate commit; projection and exhaustive authoritative delivery-support tests pass | Exact-SHA provider-free proof, same-20 opportunity receipts, then ablation |

## Phase 0 — Freeze the candidate and preserve ownership

### Work

1. Inventory the shared dirty tree and assign each modification to an owner.
2. Include only the intended Type 1/2/3 files and tests in the candidate commit.
3. Record the exact commit SHA, indexer source SHA, dense asset identity, treatment manifest hash, and frozen task manifest hash.
4. Keep benchmark task IDs out of runtime selection and policy logic.

### Completion criterion

One reviewable candidate commit contains all intended repairs and no unrelated user/agent changes; the runtime manifest points to that exact commit. No paid or outcome run starts before this criterion is met.

## Phase 1 — Close Type 1 integration seams

### 1.1 Certify coupled-obligation delivery before enabling it — implemented, live-unverified

The candidate adds `projection.coupled_obligations[*].claim_id` to
the authoritative repository-context `supported_ids` and has a red/green audit
test. Exact constituent completeness and negative authority cases are covered;
exact-SHA and live receipts remain required before an outperformance claim.

Implement:

- coupled claim ID in the authoritative supported-ID set;
- exact constituent claim IDs and current source/graph revision;
- changed symbol, dependent paths, test paths, and declared check as bounded delivery facts;
- `authority=certified_composition`, `blocking=false`, origin, materiality, completeness, and truncation;
- a proof that every constituent is itself certified and action-relevant;
- semantic supersession so rendered constituent impact/validation lines are not duplicated;
- rejection when any constituent is rank-only, stale, ambiguous, missing, or not represented in the projection.

Tests:

- valid coupled claim passes authoritative delivery audit;
- missing/foreign/stale constituent fails;
- heuristic/co-change/global-name edge cannot authorize a coupled claim;
- selected coupled claim has exact provider hash/message index and first-eligible timing;
- no duplicate constituent delivery text;
- advisory `blocking=false` cannot create a preflight return or submit block.

### 1.2 Finish graph publication certification

Implement/verify:

- every full and incremental publication occurs under the same cross-process lock;
- graph bytes and manifest are certified as one root/source/binary identity before exposure;
- readers either acquire the publication lock or certify the pair after publication before use;
- crash between DB and manifest replacement rolls back or leaves an explicitly invalid pair;
- old graph/manifest remain usable together after failed publication;
- Windows and Linux locking semantics are covered;
- source revision, schema, indexer binary, parser coverage, and graph hash enter the receipt.

Tests:

- competing publishers serialize;
- reader cannot certify a mixed pair;
- malformed/missing/wrong-root/wrong-source/wrong-binary manifest fails closed;
- incremental no-op still proves current source revision;
- process termination/fault injection does not publish a partial certified pair.

### 1.3 Re-run conservation tests

Assert for every central lifecycle, including final submit and exhausted trajectories:

```text
produced effects == consumed/applied/audit-only effects
selected contributions == rendered/accounted contributions
visible claims == certified first-eligible provider claims
task token usage == sum of selected contribution tokens
```

### Completion criterion

The full Python gate, delivery audit, effect/contribution conservation tests, static contamination scan, and graph publication tests pass locally. Every newly composed claim is accepted by the authoritative audit only under its intended authority.

## Phase 2 — Close Type 2 policy and graph-coverage seams

### 2.1 Convergence/root behavior

Required behavior:

- `/` is a search root, not itself a forbidden artifact;
- exact forbidden paths and `find` selectors for known grader-only artifacts are returned before execution;
- generic broad searches are returned only with a typed `STALLED`, `CONTRADICTED`, or `BUDGET_RISK` witness;
- provider-visible text uses neutral task-evidence language;
- ordinary task runtime logs remain legal observed execution;
- every return records which operation it replaced and whether another provider call followed.

Replay extract, tensor, and video through the classifier. Their former broad-root commands must pass unless a separate typed convergence witness applies. Direct `/logs/verifier/...`, reference, solution, reward, and hidden-verifier selectors must still fail closed.

### 2.2 Declaration-free identity nodes

Required behavior:

- successfully parsed non-comment executable/module syntax may create one `File` node when no declarations exist;
- comment/shebang-only and malformed files remain node-free;
- generic command-only `File` nodes are not exported definitions;
- `File` nodes establish repository identity/applicability only;
- definitions, callers, obligations, contradictions, and intervention authority exclude identity-only nodes;
- imports/module links may use explicitly certified module identity without upgrading it to a symbol definition.

Run Go parser tests and source-built index fixtures on Linux. Audit every SQL/graph consumer, not only `_graph_structural_roles`, for label/authority handling.

### 2.3 Action-relevant semantic filtering

Required selection link for each provider-visible repository fact:

```text
instruction anchor
or active changed path/symbol
or current diagnostic
or required deliverable/check
or certified unresolved obligation
```

Tests:

- sanitize call 1 cannot select the unrelated histogram relation;
- a caller/test in another path remains selectable when its target is the exact changed symbol;
- path-only and symbol-only anchors behave correctly;
- same-file unrelated symbols are excluded;
- no-anchor task-start behavior remains bounded and useful;
- stale or model-authored semantic rows cannot masquerade as preexisting repository evidence.

### Completion criterion

Focused negative witnesses pass, full central tests remain green, and no new authority path treats identity, rank-only support, or unknown evidence as a certified relation.

## Phase 3 — Authoritative exact-commit provider-free proof

Use the Linux/Codespaces or CI path because local Windows lacks Go and may carry a stale binary.

The workflow must:

1. check out the exact candidate SHA;
2. build `vendor/gt-index-src` from source;
3. run the Go parser/indexer suite including declaration-free witnesses;
4. provision and hash the pinned Snowflake ONNX asset;
5. run the full central Python/static/contamination gates;
6. exercise graph DB/manifest publication, mismatch rejection, and lock tests;
7. print all 17 feature census lines plus persistent-state proof, `READY`, and `SMOKE_APPROVED`;
8. upload a provider-free receipt with `provider_calls: 0` and exact source/runtime identities.

### Completion criterion

One source-built provider-free workflow passes on the exact candidate SHA. A local Python pass or historical Linux workflow is not a substitute.

## Phase 4 — Rerun the same 20 treatment tasks

Dispatch exactly the frozen `repair20-v1` GT-on treatment. Preserve task order, model catalog ID, temperature 1, timeout/step/token policy, provider route, retry policy, dense configuration, scaffold, and evaluator. Do not dispatch GT-off and do not broaden the denominator.

Required per-task integrity:

- repository graph applicable and current, or explicit legitimate non-applicability;
- dense expected/actual mode certified;
- graph DB/manifest/root/source/binary identities agree;
- exactly one bootstrap on each applicable task;
- repeated persistent-state compile/preflight/postflight/rebase lifecycle;
- every selected contribution and effect conserved;
- every visible claim has exact provider/request hashes, changed index, timing, revision, and semantic support;
- coupled obligation, if produced, is advisory and fully certified;
- no silent retrieval/delivery failure;
- final graph/source fingerprint current.

Do not rerun an individual task merely because its solve outcome is unfavorable. Infrastructure-censored rows follow the predeclared retry policy; model failures remain counted.

### Completion criterion

All 20 tasks are graded, zero are silently excluded, and the implementation release gate passes every applicable task. Integrity results are reported separately from solve results.

## Phase 5 — Produce the 20-task report

Report four independent sections:

### Integrity

- graph/retrieval/delivery/PES/postflight/publication status per task;
- 17+1 configured status and natural 17-feature fires;
- every abstention/fallback/return and its certificate.

### Solve

- BOTH SOLVE, BASELINE ONLY, GT ONLY, BOTH FAIL against the frozen cohort;
- raw flips versus causally supported flips;
- fingerprint/provider-view differences;
- no claim that fingerprint metadata restores causal equivalence.

### Efficiency

On common-solved and full-profile tasks:

- steps, executor/bootstrap calls, uncached/cached input, output/total tokens, normalized cost, wall time;
- searches, reads, tests, environment executions, host GT computations, and GT evidence tokens;
- the exact operation each GT frame replaced or added.

### Intervention

- first meaningful divergence for every flip;
- evidence immediately before it;
- correctness, relevance, completeness, freshness, and authority;
- CONFIRMED/HIGH/MEDIUM/LOW/NOT ATTRIBUTABLE.

### Completion criterion

The report makes no aggregate promotion recommendation until every task receipt is reconstructable. A clean integrity gate with worse outcomes is reported as a valid treatment regression, not hidden.

## Phase 6 — Type 2 process composition ablation

After the 20-task integrity gate is clean, implement a bounded process projection inside existing repository context:

1. select an instruction/action/change anchor;
2. traverse only certified `CALLS`/route/test/sink relations;
3. use deterministic depth, branching, process, and token bounds;
4. cycle guard and stable order;
5. report total/returned/truncated and unresolved receiver/dynamic boundaries;
6. group the source span, callers, route/sink, and tests into one answer;
7. deliver it on the existing next provider request;
8. supersede redundant raw edge/span contributions.

Use legal-source decision replay on captured states:

- current repaired repository context;
- action-relevant filter only;
- filter plus process pack.

Measure next action, searches/reads avoided, time to first correct edit, uncached evidence tokens, and negative scope expansion. This is not a new GT-off benchmark arm.

### Completion criterion

The process pack replaces at least one ordinary exploration operation on target witnesses without a new provider call or an incorrect authoritative relation. Negative relevance/ambiguity fixtures remain green.

## Phase 7 — Type 3 coupled-change obligation ablation

Enable the fully certified advisory obligation only after Phase 1 delivery support passes.

Ablate one mechanism at a time on incomplete-fix witnesses:

- process context without coupled obligation;
- process context plus advisory changed-symbol/caller/test/check obligation.

Success conditions:

- model inspects/edits/verifies the coupled surface earlier;
- a previously missed caller/test/check is addressed;
- no claim says a dependent “must be edited” unless an exact task predicate proves it;
- no extra planning/provider call;
- no attributable negative flip from incomplete/heuristic edges.

### Completion criterion

At least one decision-level witness shows a correct coupled action attributable to the composed record, with all constituent claims and provider delivery certified. Only then is an outcome-scale ablation justified.

## Phase 8 — Completion and convention amplifiers

### Budgeted completion proof

Strengthen existing completion state to emit one current-revision record of deliverables, observed checks, unresolved predicates, contradictions, and cheapest remaining probe. Replay video. Repeated expensive generation after a passing candidate must require new evidence.

### Resolved convention record

Bridge certified compiler/LSP signatures/types and runtime observations into central context. Compose constructor/caller arguments, assertions, and observed shapes. Replay tensor-like states. Conflicting evidence must yield candidates/unknown, never a guessed singleton.

### Completion criterion

Each amplifier first passes a decision-level witness and negative uncertainty tests, then receives its own outcome ablation. Do not combine both in the first causal experiment.

## Phase 9 — Direct GitNexus comparison, only after internal validity

Use [10_GITNEXUS_BENCHMARK_FORENSICS.md](10_GITNEXUS_BENCHMARK_FORENSICS.md) as the reproducibility checklist. A direct claim requires the same published task/repository SHAs, model/provider/settings, scaffold, budgets, evaluator, trial policy, prompts, index configuration, and accounting. If Akon's missing manifest/configuration remains unavailable, label the comparison non-reproducible and do not claim leaderboard superiority.

Scientifically useful arms on a separately authorized reproducible benchmark are:

- Bare;
- pinned GitNexus;
- GT;
- pinned GitNexus repository intelligence plus GT-specific task/change/validation intervention layer.

This future comparison is separate from the treatment-only TB2 promotion workflow.

## Stop/go gates

| Gate | Go when | Stop when |
|---|---|---|
| Local integration | Full tests and conservation pass | Any unsupported claim or authority leak |
| Provider-free | Exact candidate source-built workflow passes | Stale binary, Go gap, graph/manifest mismatch, provider call |
| Same-20 integrity | Every applicable row passes release gate | Any silent substrate/retrieval/delivery/state failure |
| Outcome | Causal positive minus causal negative is favorable | Confirmed/high attributable losses lack a repair |
| Efficiency | Common-solved calls/uncached/cost do not regress without solve tradeoff | GT adds exploration with no outcome value |
| Broader ablation | One mechanism has decision-level evidence | Multiple mechanisms changed without attribution |
| Direct GitNexus claim | Reproducible matched configuration exists | Akon identity/configuration remains undisclosed |

## Top three immediate implementation changes

1. **Complete Type 1 integration, especially coupled-claim delivery support and graph publication/read certification.** This makes the new work auditable rather than bypassing the gate.
2. **Land and validate root/neutral/action-relevance/identity repairs.** These directly address observed negative intervention, relevance, and availability failures with zero additional provider calls.
3. **Finish the advisory coupled-change obligation, then add bounded process packing.** This is the highest-reuse path to new solves and the most plausible route to GitNexus-level navigation efficiency plus GT-specific incomplete-fix recovery.

## Final completion criterion

The program may advance beyond the frozen 20 only when:

- exact-commit provider-free proof passes;
- all 20 treatment receipts pass integrity;
- solve and efficiency results are reported separately;
- every raw flip has a causal-confidence autopsy;
- no confirmed/high attributable negative flip remains without a minimal repair;
- at least one solve amplifier has decision-level evidence that it replaced exploration or recovered a coupled action without adding a provider call.
