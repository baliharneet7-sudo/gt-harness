# GT delivery versus GitNexus: deep source-level audit

## Audit identity and confidence

- **GT checkout audited:** the active repository checkout at the audit commit; the release identity is [active_release.json](../../eval/release/active_release.json).
- **Active treatment:** [tb2_central_relational_v2.json](../../eval/treatments/tb2_central_relational_v2.json).
- **GitNexus source pin:** [`fc885a4bf3edddf9214df633d8d1c0767ef58af9`](https://github.com/abhigyanpatwari/GitNexus/commit/fc885a4bf3edddf9214df633d8d1c0767ef58af9).
- **Audit date:** 2026-08-19.

Confidence is **high** for implementation facts cited to source. Confidence is **moderate** for token/turn consequences because neither public GitNexus source nor GT receipts alone proves that a model avoided a later action; that requires matched trajectories or ablations.

This document audits delivery and lifecycle. It does not claim that either system makes a stochastic model solve every task.

## Executive finding

GitNexus has the better *placement idea*: attach a compact relational answer to an ordinary search/read observation. Its public evaluation adapter does this in `native_augment`, and its Claude hook uses `PreToolUse.additionalContext`.

GT now has the stronger *delivery contract*: it compiles bounded evidence into the exact next provider request and records claim IDs, source/graph revisions, provider-view and request hashes, changed message indices, first-eligible timing, semantic support, disposition accounting, and replay state. The authoritative implementation is [gt_engine/delivery_audit.py](../../gt_engine/delivery_audit.py), with the last-call gate in [gt_engine/mechanical_completeness.py](../../gt_engine/mechanical_completeness.py).

The conclusion is not “copy GitNexus hooks.” It is:

1. preserve GT's fail-closed, revision-bound delivery proof;
2. preserve GT's graph refresh before the next provider request;
3. use GitNexus's process-shaped, same-observation composition as the efficiency target; and
4. repair only the concrete gaps identified below.

## 1. What each system actually delivers

### GitNexus

The pinned source has four delivery paths:

| Path | Exact source behavior | What the model must do | Source |
|---|---|---|---|
| Explicit MCP | `query`, `context`, `impact`, `trace`, `detect_changes`, route/API tools return structured graph answers | Select an additional intelligence tool | [`mcp/local/local-backend.ts`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus/src/mcp/local/local-backend.ts) |
| Claude `PreToolUse` | Extracts a pattern from `Grep`, `Glob`, or search-bearing `Bash`; runs `gitnexus augment`; emits `hookSpecificOutput.additionalContext` | Select an ordinary search; no separate graph-tool choice | [`gitnexus-hook.js#L430-L491`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus-claude-plugin/hooks/gitnexus-hook.js#L430-L491) |
| Cursor post-tool hook | Adds `additional_context` to selected Shell/Read/Grep observations | Select ordinary tool | [`gitnexus-hook.cjs`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus-cursor-integration/hooks/gitnexus-hook.cjs) |
| Public `native_augment` evaluation | Executes model actions, then runs `gitnexus-augment` for grep-like actions and appends its block to the observation | Select ordinary search; host performs augmentation | [`gitnexus_agent.py#L78-L131`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/eval/agents/gitnexus_agent.py#L78-L131) |

The augmentation engine is deliberately small: BM25/FTS search, top file-to-symbol mapping, bounded callers/callees/process lookups, and compact formatting. It performs no embedding call in this path and returns an empty string on errors or short/no-match patterns ([`engine.ts#L89-L177`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus/src/core/augmentation/engine.ts#L89-L177)).

The Claude hook's failure policy is operationally graceful: hook-slot contention, lock contention, and augmentation exceptions can produce no context; the source explicitly catches failures and continues ([`gitnexus-hook.js#L444-L490`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus-claude-plugin/hooks/gitnexus-hook.js#L444-L490)). That is acceptable for a developer convenience hook, but not sufficient as a benchmark treatment certificate.

GitNexus detects commit staleness only after successful `git commit`, `merge`, `rebase`, `cherry-pick`, or `pull`, then tells the agent to run analyze; it does not synchronously refresh the graph ([`gitnexus-hook.js#L493-L551`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus-claude-plugin/hooks/gitnexus-hook.js#L493-L551)). The public Docker evaluator restores/builds an index once at task setup; its cache identity and static-index behavior are separately audited in [09_GITNEXUS_DELIVERY_AND_LIFECYCLE.md](09_GITNEXUS_DELIVERY_AND_LIFECYCLE.md).

### GroundTruth

The active GT treatment is not a model-invoked sidecar. The host-owned `MiniSweCentralAgent` computes evidence before every provider request and places one bounded current slice into the same provider view as normal history. The treatment explicitly selects `retrieval_delivery_mode: integrated_same_observation`, enables relational and semantic evidence, and enables persistent execution state ([treatment JSON](../../eval/treatments/tb2_central_relational_v2.json)).

The delivery chain is:

```text
task/repository/observed result
  -> typed substrate, graph/retrieval/state transition
  -> bounded contribution compiler
  -> provider-view construction and exact hashes
  -> mechanical barrier
  -> one provider request
  -> receipt/replay/postflight state
```

Relevant implementation points:

- persistent state transitions: [persistent_execution_state.py](../../gt_engine/persistent_execution_state.py);
- process-shaped relational composition: [relational_context.py](../../gt_engine/relational_context.py);
- high-certainty semantic composition: [semantic_evidence.py](../../gt_engine/semantic_evidence.py);
- graph-independent task facts: [task_semantic_substrate.py](../../gt_engine/task_semantic_substrate.py);
- current provider request construction and evidence preparation: [gt_central_agent.py#L5960-L6053](../../eval/gt_central_agent.py#L5960-L6053) and [#L6064-L6218](../../eval/gt_central_agent.py#L6064-L6218);
- per-call mechanical barrier: [gt_central_agent.py#L6832-L6937](../../eval/gt_central_agent.py#L6832-L6937) and [mechanical_completeness.py#L51-L197](../../gt_engine/mechanical_completeness.py#L51-L197);
- authoritative visible-delivery audit: [delivery_audit.py#L224-L360](../../gt_engine/delivery_audit.py#L224-L360).

GT has an additional safety property GitNexus's public delivery paths do not show: after a source-changing action the graph is unavailable until the captured refresh is complete and revision-current. No old graph frame is allowed to pass the provider barrier.

## 2. Delivery-surface pass/fail matrix

Legend: **PASS** means the implementation and release receipts have an explicit contract; **CONDITIONAL** means the behavior is correct only when the active profile/provisioning requirement is met; **GAP** means a concrete repair or additional proof is required. “GitNexus comparison” describes the pinned public source, not a claim about Akon's undisclosed private configuration.

| GT surface | Compute | Trigger | Placement | Freshness | Identity | Uncertainty | Failure handling | Audit proof | Turn/token effect | GitNexus comparison |
|---|---|---|---|---|---|---|---|---|---|---|
| Task semantic substrate | **PASS**: instruction, bounded workspace, observed validation | **PASS**: loaded and compiled per provider call | **PASS**: same provider view, not a tool call | **PASS**: source/revision-bound; stale facts abstain | **PASS**: claim IDs, source revision, provider hash | **PASS**: incomplete/ambiguous facts abstain | **PASS**: no fabrication; barrier blocks unready state | **PASS**: contribution + delivery + mechanical certificate | **PASS**: bounded frame, exact accounting; no extra model call | GitNexus has no task-instruction/check/deliverable substrate. GT is stronger and should keep it. |
| Preemptive retrieval | **PASS/CONDITIONAL**: five-channel `HybridRetriever`, including pinned local dense lane when provisioned | **PASS** in final profile; deterministic safe abstentions are explicit | **PASS**: integrated same-observation frame | **PASS**: current graph/source required; post-edit refresh blocks stale use | **PASS**: selected evidence, claim IDs, channel/support rows, request/view hashes | **PASS**: certified support required; weak/ambiguous rows abstain | **PASS**: safe policy abstention is distinct from substrate failure; release gate rejects missing required readiness | **PASS**: authoritative delivery audit; semantic support for this surface | **PASS**: bounded payload; no separate provider call; benefit remains empirical | GitNexus augmentation is same-observation but BM25-oriented and has no equivalent proof. Do not weaken GT to silent hook failure. |
| Relational/process context | **PASS**: certified bounded chains with calls/tests/relations and `EXACT`/`LOWER_BOUND`/`PARTIAL` status | **PASS** on material lifecycle opportunities | **PASS**: one relational payload in next provider request | **PASS**: source + graph revision and graph-current barrier | **PASS**: stable process/claim IDs and hashes | **PASS**: uncertified edges rejected; truncation and epistemic status surfaced | **PASS**: abstains on unsupported/unsafe graph links | **PASS**: relational delivery rows require process/claim/revision support | **PASS**: bounded profile (default 256 tokens); no graph-tool turn | GitNexus is stronger today in broad first-class process extraction and process-grouped query answers. GT is stronger in certification and revision binding. |
| Persistent execution state | **PASS**: one graph-first state engine | **PASS**: bootstrap once, then compile/preflight/postflight/rebase repeatedly | **PASS**: current state frame in ordinary provider request | **PASS**: source edit invalidates graph-current state before rebase | **PASS**: state ID/version/revision + request/view hashes | **PASS**: stale/uncertain state is private or blocks | **PASS**: mechanical barrier requires state readiness; replay includes transitions | **PASS**: lifecycle receipts and task certificate | **PASS**: bounded 512/256/96 packing; bootstrap overhead counted | GitNexus has index lifecycle, not this task-scoped execution state. GT should not replace it with a static task-start graph. |
| Progress | **PASS**: typed progress facts and current provider-view insertion | **PASS**: first eligible call after progress evidence | **PASS**: same provider request, plural claim IDs | **PASS**: current source/workspace state | **PASS**: exact provider-view hash and changed message indices | **PASS**: only grounded progress; retained compaction epoch records reason | **PASS**: missing timing/hash rejects delivery | **PASS**: delivery audit includes progress surface | **PASS**: replaces duplicated progress where represented; bounded when new | GitNexus hooks do not expose equivalent progress receipts or provider hashes. |
| Completion/submit | **PASS**: deterministic completion controller and project validation probe | **PASS**: re-evaluate on material revision/check dependency/validation/budget events | **PASS**: exact completion/risk surface; assistive-safe return only for proven cases | **PASS**: check certificate is source-revision-bound | **PASS**: check ID, revision, request/view hashes and certificate | **PASS**: no partial/unknown completion auto-submission | **PASS**: task certificate requires applicable checks satisfied/proven N/A | **PASS**: release gate recomputes rather than trusts self-report | **PASS**: can remove repeated exploratory validation; savings must be measured | GitNexus exposes change/impact tools but not GT's task-owned completion contract. |
| Observed facts/validation | **PASS**: one immutable classifier, workspace sensor, postflight state | **PASS**: after every executed model action | **PASS**: next provider request; raw evidence remains in history | **PASS**: source revision distinguishes source from logs/build products | **PASS**: action/revision/fact provenance and delivery hashes | **PASS**: unknown is not false; unrecognized evidence remains private | **PASS**: failed capture/refresh fails closed rather than serve stale graph | **PASS**: receipts, effect traces, delivery audit, replay | **PASS**: uses existing observation instead of graph-tool call | GitNexus observes search actions but does not provide this field-level causal audit. |

### Matrix conclusion

There is no evidence that GT should downgrade any row above to GitNexus's best-effort hook semantics. The only conditional row is preemptive retrieval's expected channel availability: the final treatment must prove the dense asset or record a policy-certified abstention, while the release gate must still reject an actual missing/failed required substrate. The active treatment's `dense_fallback_only` setting is intentional and must remain visible in the receipt; it must not be silently interpreted as “dense succeeded.”

## 3. Exact comparison by delivery property

### Compute and composition

GitNexus's augmentation engine computes a BM25 match, maps up to five files to symbols, then fetches bounded callers/callees/process membership in parallel. Its richer MCP `query`/`context`/`impact`/`trace` surfaces compose more graph relations, but require a model-selected MCP action. The public source therefore supports the hypothesis that its efficiency comes from relational composition placed beside a search, not from raw graph size alone.

GT's relational context currently composes certified bounded chains and exposes an epistemic status. Its semantic bridge adds definitions, callers, tests, properties, signatures, and return types only at high certainty/relevance. This is safer, but GT's default process shape is smaller than GitNexus's broad process extractor. That is a solve-opportunity, not a delivery-integrity defect: expand only behind certified lower-bound and truncation fields.

### Trigger and placement

GitNexus's automatic path triggers only for recognized search patterns. A non-search read/edit/validation action does not receive the same augmentation unless it goes through another integration path. GT triggers typed state and context compilation at every provider request and can select evidence from task facts, retrieval, relational composition, persistent state, progress, completion, or observed validation. This is broader and more expensive in host work, but it avoids making the model discover GT first.

### Freshness

GitNexus's hook detects commit drift after selected Git mutations and asks the agent to run analyze. That is a useful warning, not current-byte certification; ordinary uncommitted edits can leave the graph stale. GT's source-revision and graph-revision contract is materially stronger: stale graph state cannot reach the provider barrier. Keep this asymmetry.

### Identity and audit

GitNexus output is a text block or structured tool result. The pinned public source does not attach stable evidence claim IDs, exact provider-view hashes, request hashes, changed provider-message indices, first-eligible timing, or a replay-complete certificate to the automatic augmentation. GT has all of these as explicit release conditions. This is the core reason a GitNexus-style silent hook cannot replace GT's delivery audit.

### Uncertainty and failure handling

GitNexus's graph resolver and MCP responses have useful confidence/partial and lower-bound concepts, but the augmentation hook can collapse any failure to no output. GT rejects uncertified relations for intervention, records abstention reasons, and fails the mechanical treatment when an applicable required substrate is unavailable. GT should borrow GitNexus's user-visible lower-bound and truncation vocabulary, not its silent release behavior.

### Turns and tokens

Both systems can avoid an explicit graph-tool turn. GitNexus's public `native_augment` implementation actually invokes a host `gitnexus-augment` command after the model's search action; that is an environment operation and its timing/cost is tracked in GitNexus metrics, but it is not an additional provider query. GT computes its bounded contribution before the provider query and counts host work plus bootstrap/provider resources in the receipt.

Neither codebase proves a reduction in model turns by itself. The required experiment is matched common-solved accounting of searches, reads, provider calls, uncached/cached input, output, total tokens, cost, and wall time, plus an ablation that removes process composition while retaining delivery placement.

## 4. Concrete gaps and required repairs

### G-1 — process composition breadth (mechanism gap; confidence high)

GT's relational composer is bounded and certified, but it is not yet equivalent to GitNexus's first-class entry-point-to-terminal process extraction. GT already has enough certified graph relations to build a stronger task/change/test process view, but it needs a composition layer that records entry anchor, ordered edges, cycle/depth/branch truncation, lower-bound status, and meaningful terminal (test, route, validation, or deliverable).

**Repair:** implement this as a new certified projection on existing GT graph data; do not replace the LSP/compiler substrate or treat a heuristic process as an intervention authority. Add provider-visible truncation and ablation tests.

### G-2 — proof that composition replaces exploration (measurement gap; confidence high)

GT has bounded same-observation delivery, but no source-level comparison can prove that the model subsequently needed fewer searches or reads. GitNexus's mechanism makes the same hypothesis explicit but does not prove its private benchmark causal effect either.

**Repair:** add per-task accounting linking each delivered process/semantic payload to later search/read actions, and run a process-off ablation. Do not claim efficiency improvement from delivery counts.

### G-3 — dense retrieval expectation must be unambiguous (configuration/gate gap; confidence moderate)

The final treatment sets `dense_fallback_only: true`; the runtime and barrier correctly distinguish a safe policy abstention from an unavailable dense lane, but a report can still misread “retrieval ready” as “dense contributed.”

**Repair:** preserve separate receipt fields for expected mode, dense backend provisioned, dense query attempted, dense result used, and certified fallback reason. The merge report must print these separately. Do not weaken the barrier or silently call fallback dense success.

### G-4 — GitNexus-style automatic search augmentation is not a missing GT integrity feature (no repair; confidence high)

GT's integrated same-observation frame already satisfies the placement goal and adds stronger identity/freshness/audit guarantees. Adding a second hook or MCP roundtrip would duplicate evidence and risk token/turn regressions.

**Decision:** do not implement a separate GitNexus hook in the benchmark harness. If ordinary search/read replacement is weak, improve GT's existing contribution selection and process composition instead.

### G-5 — public GitNexus index freshness is not a target to copy (no repair; confidence high)

GitNexus's post-commit warning and task-start index are weaker than GT's source-edit invalidation and refresh-before-next-provider-request contract.

**Decision:** do not adopt static task-start graph serving, commit-only freshness, or silent fail-open treatment setup.

## 5. What to adopt, preserve, and reject

### Adapt from GitNexus

1. **Process-shaped answers:** present ordered caller/callee/test/terminal relationships rather than unrelated edges.
2. **Search-local enrichment:** attach that answer to an existing observation, avoiding an explicit graph-tool decision.
3. **Lower-bound/truncation language:** make bounded process coverage explicit in provider text and receipts.
4. **Content/config-aware index identity:** retain GT's revision binding and add analyzer/schema/embedder/config identity where not already present.

### Keep GT's stronger behavior

1. Task-semantic evidence for non-graph and empty-source tasks.
2. Revision-current graph lifecycle after every source-changing action.
3. Certified relation support and uncertainty abstention.
4. Persistent execution state across provider/preflight/postflight/rebase.
5. Exact provider-view/request hashes, message indices, timing, claim IDs, replay, and recomputed task certificates.
6. One bounded contribution compiler, with no generic advisory stream.

### Explicitly reject

- silent hook failure as valid treatment delivery;
- commit-only freshness;
- global-name guesses as certified edges;
- static task-start index after source edits;
- a separate model-selected graph call when the same evidence fits the current provider request;
- treating a receipt or action-alignment proxy as proof of model utilization or causal solve benefit.

## 6. Release checks before spending on benchmark rerun

The timeout repair and provider-free mechanical proof are necessary but not sufficient for an efficiency claim. Before the paid retry, require every final-profile receipt to show:

1. active release identity equals `active_release.json`;
2. every dispatched provider call has a PASS mechanical barrier;
3. every applicable surface in the matrix is SATISFIED or PROVEN_NOT_APPLICABLE;
4. no stale graph frame is delivered after a source change;
5. every visible surface passes the authoritative delivery audit;
6. dense/fallback status is reported separately;
7. replay is complete, including unsent deadline-reserve terminals;
8. process/semantic payloads expose truncation and epistemic status;
9. common-solved efficiency compares contribution tokens against searches/reads and provider resource totals;
10. matched solve accounting classifies both flips and censoring separately.

The next paid run is therefore a validation of the repaired lifecycle and delivery contract, not evidence that GT is superior to GitNexus. Only after it is clean should the process-composition ablation be run.

## 7. Final verdict

- **Delivery placement:** GitNexus demonstrates the right efficiency pattern; GT already implements it at the provider boundary.
- **Delivery integrity:** GT is stronger and must not be downgraded.
- **Freshness:** GT is stronger; GitNexus's commit warning is not a substitute for revision-current evidence.
- **Composition:** GitNexus currently has the broader process layer; this is GT's main remaining intelligence opportunity.
- **Efficiency evidence:** unknown until matched trajectory accounting and an ablation show that GT evidence replaces exploration.
- **Required immediate work:** keep the repaired mechanical gate, make dense vs fallback status explicit, and build certified process/change/test composition on existing GT data before the final benchmark comparison.
