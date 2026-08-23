# GT Competitive Repository-Intelligence Audit

Status: **BOUNDED DIRECT COMPARISON COMPLETE; BROAD COMPETITIVE VALIDATION INCOMPLETE**

GroundTruth subject: `3e2185d3f4ba0a228c740ab2a6d23a287cfc5380`

Observed: `2026-08-23`

This is Gate 14 repository-fact evidence. It is not an agent solve-rate benchmark and it does not authorize paid execution.

## Frozen subjects and modes

| System | Version / revision | Build mode | Provider use |
| --- | --- | --- | --- |
| GT Harness | implementation `3e2185d3f4ba0a228c740ab2a6d23a287cfc5380`; indexer source `ed268dbefb3040116f10ea3412cad83d4f3fadf5938482f692558357ec997556` | canonical `RepositoryGraphService` source build and persisted graph | 0 |
| GitNexus | npm `gitnexus@1.6.9`; researched source revision `aac7515d2a8c50a1f8f923c6fb77218b333560d6` | `analyze --force --drop-embeddings --index-only` | 0; embeddings disabled |

Repositories:

- itsdangerous at `672971d66a2ef9f85151e53283113f33d642dabd`.
- Redux at `71606661ac515bdd64c199a6bb508401c7cf736f`.

Both checkouts were detached and clean. Expected facts were established from the checked-out source using manual source inspection and repository search. Neither GT nor GitNexus output was used to create the expected set.

## Blind fact set

The ten questions contain 53 independently enumerated facts. Counts below score returned repository relationships, not feature names. Candidate edges returned by a system count as claims and therefore can be false positives.

| Question | Expected | GT TP / FP / FN | GitNexus TP / FP / FN | Finding |
| --- | ---: | ---: | ---: | --- |
| Definition of `Signer` | 1 | 1 / 0 / 0 | 1 / 0 / 0 | Both exact |
| Direct subclasses of `Signer` | 1 | 1 / 0 / 0 | 1 / 0 / 0 | Both find `TimestampSigner` |
| Files importing `Signer` | 6 | 6 / 0 / 0 | 3 / 0 / 3 | GitNexus omits the three test imports |
| Callers of `Serializer.make_signer` | 4 | 4 / 0 / 0 | 4 / 0 / 0 | Both exact |
| Callees of `Serializer.make_signer` | 1 | 1 / 0 / 0 | 0 / 0 / 1 | Final GT emits a confidence-0.6 typed callable-field candidate for `Signer.__init__`; GitNexus has no outgoing edge |
| May-call sites for `Signer.sign` | 13 | 10 / 4 / 3 | 6 / 0 / 7 | GT has substantially higher recall but four inherited-fixture dispatch candidates bind the base method incorrectly |
| Callees of `Signer.sign` | 2 | 2 / 0 / 0 | 2 / 0 / 0 | Both exact |
| Named type re-exports from Redux `src/index.ts` | 22 | 22 / 0 / 0 | 0 / 0 / 22 | GT enumerates the barrel; GitNexus symbol/file context cannot answer this question |
| Callers of top-level Redux `createStore` | 1 | 1 / 0 / 0 | 1 / 0 / 0 | Both exact after GT callback-shadow repair |
| Direct callees of top-level Redux `createStore` | 2 | 2 / 0 / 0 | 2 / 0 / 0 | Both return `dispatch` and `kindOf` |
| **Aggregate** | **53** | **50 / 4 / 3** | **20 / 0 / 33** | Aggregate is dominated by the 22-element barrel question; per-question results remain authoritative |

### Aggregate metrics

| System | Precision | Recall | F1 |
| --- | ---: | ---: | ---: |
| GT | 0.9259 | 0.9434 | 0.9346 |
| GitNexus | 1.0000 | 0.3774 | 0.5479 |

Confidence: **high** for the exact two-repository, ten-question fact set; **low** for generalizing these aggregate values to other repositories or relationship distributions.

## Defects exposed and repaired before final certification

The first GT run on implementation `d5fd7f56f2516930f70ba4e21f4b3660704e6611` scored 49 TP, 5 FP, and 4 FN. It exposed two source-truth defects:

1. Redux's lexical callback parameter `createStore` was incorrectly bound to the same-named top-level function. The parser/resolver now records parameter shadowing and abstains unless callable-value flow proves a target.
2. `Serializer.make_signer` calls the typed class-valued field `self.signer`. GT omitted the candidate constructor. The resolver now uses explicit `type[Signer]` assignment/data-flow evidence and reports `Signer.__init__` as a confidence-0.6 candidate rather than a certified edge.

Regression coverage uses repository-shaped Python and TypeScript source. The complete local suites and the complete Codespaces G0-G12 campaign were rerun on the resulting exact SHA `3e2185d`.

## Build cost

| Repository | GT internal build | GitNexus reported analysis | GitNexus complete CLI wall | GT / GitNexus caveat |
| --- | ---: | ---: | ---: | --- |
| itsdangerous | 0.435 s | 4.2 s | 5.603 s | GT was 9.7x faster against GitNexus's internal reported time |
| Redux | 1.197 s | 7.8 s | 9.314 s | GT was 6.5x faster against GitNexus's internal reported time |

GT's certified query p50/p95 on these repositories was 5.467/5.602 ms for itsdangerous and 9.356/10.225 ms for Redux. An equivalent repeated in-process GitNexus query distribution was not frozen, so this audit does not claim query-latency superiority. Raw node/edge totals are also not directly comparable because GitNexus materializes properties, communities, and process objects that GT models differently.

## Where GitNexus is stronger

GitNexus's `context` results expose ordered processes attached to `make_signer`, `Signer.sign`, and `createStore`; GT has no equivalent first-class bounded process object. GitNexus also provides seeded Leiden communities, hybrid lexical/optional-embedding retrieval, trace, change detection, a dedicated typed impact response, optional PDG mode, proactive hooks, and contract-aware multi-repository analysis. Its responses are compact and decision-oriented.

GT's advantages on this run are exact repository/dirty-source binding at every graph read, atomic recovery, explicit degraded states, much stronger re-export/import coverage in the selected questions, a bounded source-receipted treatment packet, and lower cold-build cost. GitNexus's query boundary remains fail-open/non-blocking on staleness; that is an integrity difference, not proof that GT gives better task context.

## Gate 15: missing-capability analysis

| Missing capability | Repository fact unavailable or weak | Agent decision affected | Proposed deterministic mechanism | Expected effect | Risk | Required test |
| --- | --- | --- | --- | --- | --- | --- |
| Python callable/fixture flow completeness | Three `Signer.sign` call sites created through `partial` and fixtures are absent | Whether all affected tests are inspected | Bounded constructor/partial/fixture value-flow facts with explicit union targets | Better affected-test recall | Framework-specific overfitting | Independent fixture and factory truth corpus across real Python repositories |
| Override-aware candidate dispatch | Four `TimestampSigner` fixture calls are also claimed against base `Signer.sign` | Which implementation is edited | Preserve receiver candidate set and remove a base target when source-proven concrete subtype override dominates | Higher caller precision | Removing legitimate polymorphic may-call edges | CHA/RTA oracle with base, subclass, factory, and dependency-injection cases |
| First-class execution processes | No compact ordered entry-to-sink abstraction | Which path/files to inspect first | Rank bounded paths over high-confidence call edges; expose caps and omissions | Fewer exploration steps | Plausible-looking but incomplete flows | Path precision/recall plus task ablation |
| Stable architecture communities | No graph-derived functional cluster | Which neighboring subsystem matters | Seeded deterministic Leiden on selected evidence-qualified edges with content IDs | Better relevant-file ranking | Decorative clusters that do not help | Stability/modularity/manual-label audit and agent ablation |
| Hybrid issue-to-symbol ranking | Lexically distant symbols can be missed | Where the agent anchors investigation | Deterministic RRF over lexical, graph, and optional pinned local embeddings | Better initial localization | Semantic false positives and provisioning cost | Blind ranking corpus, latency, tokens, negative flips |
| Dedicated change/impact receipt | Existing impact mode is less typed and less compact | What can break and what to test | Evidence-qualified reverse traversal with relation types, confidence, truncation, and unsupported counters | Safer edits and test selection | Transitive overreach | Edge-type impact precision/recall and paired task ablation |
| Cross-repository contracts | No certified consumer/provider graph | Whether another service breaks | Explicit protocol/version contract nodes; never label-only merge | Multi-service change coverage | Catastrophic false links | Independently auditable real multi-repo fixtures |
| Optional PDG/def-use | Branch/control conditions behind a sink remain shallow | Which guard/value origin matters | Language-native CFG/def-use only where verified | Better deep bug localization | Cost and false precision | Compiler/AST oracle by language and scale |

These are hypotheses, not an instruction to clone GitNexus. No remaining capability is promoted merely to match a feature list. The causal bar remains:

`new repository fact -> better agent decision -> measured solve/efficiency effect`.

## Gate 14 verdict

GT is **competitive on this bounded structural fact set** and materially better on recall, build time, exact revision integrity, imports, and TypeScript re-exports. GitNexus is better on zero-false-positive precision in this set and on higher-order process/community/trace delivery.

Broad competitive validation is **not complete** because this run covers only two repositories and ten structural questions, does not execute Graphify on the same truth set, and does not freeze equivalent repeated query/token measurements or agent consumption. Those gaps block paid-benchmark authorization; they do not invalidate Gate 12 product certification.
