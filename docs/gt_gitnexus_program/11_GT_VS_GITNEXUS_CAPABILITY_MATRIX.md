Exit code: 0
Wall time: 0.2 seconds
Output:
# 11 — GroundTruth versus GitNexus capability matrix

## Comparison boundary

This matrix compares:

- archived GT receipts and outcomes documented in [01](01_GT_CURRENT_ARCHITECTURE.md) through [06](06_GT_UNUSED_ASSETS.md);
- the current implementation candidate, which still requires exact-pushed-SHA provider-free proof;
- official GitNexus source snapshots documented in [07](07_GITNEXUS_ARCHITECTURE.md) through [10](10_GITNEXUS_BENCHMARK_FORENSICS.md), plus the later regression-control source audit pinned in [20](20_FINAL_REGRESSION_CONTROL_AND_BENCHMARK_READINESS.md).

Akon does not publish the GitNexus commit or full treatment configuration behind its benchmark. The source comparison therefore cannot attribute Akon's reported solve delta to a specific feature.

Status vocabulary:

- **LIVE-PROVEN:** exercised and valid in workflow `32163376177`.
- **RUN-BROKEN:** exercised there but failed a release contract.
- **CANDIDATE, LIVE-UNVERIFIED:** committed in the candidate, with the complete provider-free Python matrix, complete Go module, and focused Codespaces/Linux seams passing; exact-pushed-SHA and live same-20 proof remain pending.
- **SOURCE-PROVEN:** directly supported by pinned GitNexus source.
- **UNKNOWN:** public evidence is insufficient.

## Capability matrix

| Capability | GT full/current design | GT benchmark reality | GitNexus pinned source | Assessment | Decision |
|---|---|---|---|---|---|
| Host-owned automatic engine | Central agent owns provider/preflight/postflight loop | LIVE-PROVEN | Hooks and public adapter augment ordinary actions | GT stronger integration | Preserve GT host boundary; adapt same-observation packing |
| Graph construction | Current-source indexer with graph gate | LIVE-PROVEN on 20/20 | Broad Tree-sitter property graph | Different tradeoff | Keep GT; borrow lifecycle patterns |
| Language breadth | Multi-language Go indexer plus full-product semantics | Live graph coverage across all 20, depth varies | Broad normalized Tree-sitter providers/frameworks | GitNexus likely broader in framework maturity | Extend only from observed gaps |
| Compiler/LSP semantics | Full product can hold stronger resolved semantics | IMPLEMENTED BUT UNUSED in central run | Not compiler/LSP; reconstructs semantics | GT potentially stronger | Bridge certified fields into central composition |
| Definitions/symbols | Indexed and source-span bound | LIVE-PROVEN | SOURCE-PROVEN | Roughly equivalent base primitive | Preserve |
| Declaration-free source identity | Candidate emits identity-only `File` nodes for successfully parsed non-comment syntax | CANDIDATE, LIVE-UNVERIFIED | File nodes exist in graph schema | GT repair closes qemu-like availability gaps | Type 2; certify every consumer treats `File` as identity, not definition |
| Imports/re-exports | Certified graph relations | Partial live coverage | Strong source-proven cross-file resolution | GitNexus more explicitly reconstructed | Import only proven resolution improvements |
| Receiver/type resolution | LSP/compiler potential; central bridge incomplete | Not proven on tensor convention | Multi-hop receiver folding, overload narrowing, explicit suppression | GitNexus stronger in exposed composition; GT potentially stronger evidence | Type 2 bridge + explicit uncertainty |
| Ambiguity/unknown handling | Unknown is not false; ambiguity abstains | LIVE-PROVEN policy | Explicit resolved/suppressed/ambiguous outcomes; lower bounds | Complementary; GT authority stronger | Adapt typed outcomes/lower-bound reporting |
| Unique-name global fallback | Rank-only/positive-evidence contract | Not used as intervention authority | Can emit `CALLS` at 0.85 without import proof | GT stronger/saner | Explicitly reject GitNexus fallback as authority |
| Callers/callees | Certified directed relations | Three caller-contract applications | SOURCE-PROVEN, richly queryable | GitNexus currently exposes more | Compose GT edges rather than replace graph |
| Routes/frameworks/ORM/DI/AOP | Some full-product/routes support | Little isolated live evidence | First-class source-proven extractors | GitNexus stronger | Adopt selectively by failure frequency |
| Execution processes | Bounded execution views exist; new composition work underway | Delivered relational context, but no mature full process census | First-class entry-point scoring, bounded traversal, sinks, communities | GitNexus stronger | Type 2 certified process projection |
| Process completeness | GT can revision-bind and certify candidates | No complete process receipt yet | Six extraction truncation counters, incompletely delivered | Neither complete | GT should deliver lower-bound/truncation with every process claim |
| Communities/clustering | Not a central authority | Not exercised | Seeded Leiden communities | GitNexus stronger as ranking aid | Optional rank-only support; never obligation authority |
| CFG/PDG/taint | Full capability not proven centrally | UNKNOWN | Opt-in source-proven PDG/taint | GitNexus stronger in public implementation | Defer until an observed failure requires it |
| Hybrid retrieval | Exact, lexical, BM25, pinned dense, certified graph RRF | Dense available 20/20 | BM25 + optional vector RRF, process enrichment | GT stronger channel/certification design | Keep GT |
| Task-relevant retrieval | Designed around anchors/action state | Sanitize received unrelated histogram context | Query/process grouping; still query-dependent | Both can mis-rank | Candidate action-anchor filtering is Type 2, live-unverified |
| Task instruction semantics | Dedicated substrate for checks, deliverables, binary formats, focus | LIVE-PROVEN | Repository-centric | GT stronger | Preserve as differentiator |
| Change surface/diff | Source revision and change features | LIVE-PROVEN at high volume | `detect_changes` maps diff to symbols/processes/risk | GitNexus stronger response composition; GT stronger freshness | Type 3 combine GT change state with process/test relations |
| Coupled-change obligation | Candidate composes changed symbol + callers + tests + declared check, advisory only | CANDIDATE, projection and authoritative provider-audit tests pass; live-unverified | Change/process/test context available but no GT-style certified obligation | GT differentiated opportunity | Type 3; require exact-SHA provider-free proof and live opportunity receipts before outcome claims |
| Runtime KB/observed runtime | Historical GT asset plus execution observations | Runtime KB unused; observed execution live | Static extractors, optional PDG | GT potentially stronger | Activate only on certified source/runtime contradiction |
| Validation/test feedback | One classifier, checks, diagnostics, holds, completion | LIVE-PROVEN mechanics; benefit unisolated | Repository relations, no equivalent live host validator | GT stronger | Compose tests/checks into process obligations |
| Per-edit graph freshness | Edit invalidates graph; refresh before next certified frame | LIVE-PROVEN lifecycle | Product hook detects commit drift; public evaluator static after task start | GT materially stronger | Preserve; do not copy static lifecycle |
| Graph DB/manifest publication | Candidate adds pair certification, durable interruption recovery, rollback, and a cross-process publication lock | CANDIDATE, focused Python-tested, live-unverified | Mature lock, dirty marker, staging publication, mismatch recovery | GitNexus stronger operational maturity; GT now adapting | Type 1; require exact-SHA Linux proof |
| Cache identity | Binary/graph/source/dense identities in receipts | Strong but prior Windows stale binary history | Production builder has rich identity; public eval cache only repo+commit | GT stronger benchmark gate; GitNexus production pattern useful | Preserve complete identity, reject weak eval cache |
| Persistent execution state | Bootstrap + deterministic transitions + rebases | LIVE-PROVEN 20/20 | No equivalent task execution-state engine | GT stronger | Preserve 17+1 boundary |
| Provider delivery placement | Contributions enter existing request/observation | Visible on all tasks; certified on 18/20 | Automatic hook/adapter path; explicit MCP alternative | Placement comparable; GT proof much stronger | Adopt compact process answer, not hook integrity model |
| Delivery certification | Claim IDs, hashes, indices, timing, revisions | RUN-BROKEN on 2; repaired at committed HEAD, unverified | No equivalent receipts; silent failures possible | GT substantially stronger | Keep fail-closed analytical gate |
| Contribution/effect conservation | Typed contribution/effect ledgers | RUN-BROKEN on 13 rows; committed repairs unverified | Not present | GT differentiated but unfinished | Type 1 exact-HEAD proof first |
| Assistive convergence | May return only mechanically proven unsafe/stalled actions | Broad root false positives in run | Hooks mostly add context | GT more capable and riskier | Candidate root/selector split + neutral wording is Type 1/2, live-unverified |
| Completion/budget control | Deliverables/checks/probes/holds | Video exhausted 100 steps | Lower reported steps publicly, mechanism unknown | GT not yet effective enough | Type 2 completion proof; measure operation replacement |
| Causal observability | Fingerprints, pre-GT/final views, trajectory receipts | Strong exposure proof; no same-state counterfactual | Akon raw trajectories/config absent | GT much stronger | Enable bounded legal-source replay for mechanism ablations |
| Benchmark reproducibility | Frozen 20 denominator, exact manifests/receipts | Strong identity; stochastic comparison caveat | Akon trial arithmetic/config incomplete | GT stronger | Keep frozen treatment-only promotion gate |

## Candidate implementation audit

The candidate contains five converged changes. None is live-proven:

| Change | Type | Local evidence | Remaining release work |
|---|---|---|---|
| Repository root is no longer inherently forbidden; exact forbidden selectors are preserved; provider wording is neutral `Current task evidence` | Type 1 integrity + Type 2 policy | Focused convergence/agent tests pass | Full suite, receipt golden tests, provider-free exact SHA, same-20 live proof |
| Successfully parsed declaration-free source emits an identity-only `File` node; semantic-role extraction skips `File` | Type 2 | Python role, complete Go, and Codespaces/Linux tests pass | Exact-SHA provider-free proof; live qemu graph receipt; all-consumer authority audit |
| Preexisting semantic rows are filtered to current action path/symbol anchors | Type 2 | Focused repository-context test passes | Ensure callers/tests connected to the anchor remain; sanitize replay; live relevance receipt |
| Published graph DB and manifest are jointly certified under a cross-process publication lock with rollback | Type 1 | Mismatch and process-lock Python tests pass | Linux/Windows concurrency, reader-lock/certification coverage, crash/rollback proof, provider-free gate |
| `CoupledChangeObligation` composes a changed symbol, dependent paths, test paths, and declared check; `blocking=False` | Type 3 | Projection and authoritative delivery-support tests pass | Prove the exact candidate in provider-free CI, observe same-20 opportunity receipts, then run a one-mechanism live ablation |

The coupled obligation is implemented in the candidate but is not yet live-proven. [delivery_audit.py](../../gt_engine/delivery_audit.py) now includes `coupled_obligations` in repository-context support and requires an advisory composition, exact changed endpoint, exhaustive certified dependency/test/check constituents, current revisions, and matching provider metadata. The remaining boundary is exact-SHA provider-free and same-20 receipt evidence, not additional authority or a weaker audit.

## What GT should adapt

1. **Type 2 — certified execution-process projection:** bounded ordered paths from task/change anchor to entry point, caller, route, test, or meaningful sink, with revision and truncation.
2. **Type 2 — explicit uncertainty delivery:** resolved/ambiguous/unresolved/suppressed, origin, visibility, completeness, and authority in the provider claim.
3. **Type 2 — process-aware packing:** one relational answer instead of unrelated source spans and edge lists.
4. **Type 3 — changed-symbol/process/test obligation:** the candidate advisory composition, after exact-SHA and live delivery certification.
5. **Type 1 — publication/recovery hardening:** lock, graph/manifest identity, rollback, dirty recovery, and exact configuration identity.

## What GT should reject

- Tree-sitter as a wholesale replacement for compiler/LSP evidence.
- Globally unique name resolution as obligation or intervention authority.
- Community membership as a semantic fact.
- A bounded static process presented as a complete runtime trace.
- A task-start graph used after source edits.
- Silent hook/setup failure counted as valid treatment.
- Explicit MCP as the default delivery path when host-side composition fits the existing request.
- Embeddings or PDG added without an observed failure and controlled ablation.

## Matrix conclusion

GitNexus is currently stronger at converting graph edges into process-shaped answers. GT is stronger at task semantics, live revision state, observed validation, intervention authority, and exact delivery proof. The outperformance architecture is their intersection: **GitNexus-quality composition on GT-certified, revision-current evidence, delivered automatically through GT's existing provider boundary and joined to change/test/completion state.**
