# 13 — Outperformance opportunities

## Objective and constraints

The target is a Pareto improvement:

```text
more causal positive flips
  - fewer causal negative flips
  - fewer unnecessary provider/search/read/test operations
  - lower uncached input and cost per solve where possible
```

The ranking below is an engineering prior, not a measured effect estimate. Akon's reported GitNexus configuration achieved higher solves and lower average steps/tokens, but its manifest, raw trajectories, treatment commit, hooks, prompts, and trial arithmetic are not reproducible. The useful source-level hypothesis is narrower: **process-shaped context delivered beside an ordinary action can replace exploration.**

The TB2 promotion workflow remains treatment-only on frozen `repair20-v1`. No new GT-off task run is proposed. The frozen local GT-off cohort remains descriptive outcome context, and same-state legal-source replay is used for mechanism attribution. The product census remains **17+1**: the changes below compose existing repository-context, state, validation, and delivery machinery; they do not silently create a nineteenth census item.

## Scoring method

Each proposal is ranked on:

- causal confidence from an observed failure;
- frequency in the current 20 and historical runs;
- positive-flip opportunity;
- attributable negative-flip risk;
- provider-call and uncached-token effect;
- reuse of current GT machinery;
- implementation effort and cross-language generality.

`++` means strongly favorable, `+` favorable, `0` neutral/unknown, and `-` unfavorable. “Benchmark value” weights solve opportunity first, then negative-flip and efficiency effects; integrity-only work is marked **gate-critical** rather than misrepresented as solve uplift.

## Ranked opportunities

| Rank | Proposal | Type | Causal evidence | Solve upside | Negative-flip effect | Calls/tokens | Reuse | Effort | Benchmark value | Status |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | Action-relevant certified process packing | Type 2 | Sanitize relevance miss; GitNexus source composition | ++ | ++ | ++ | ++ | Medium | Highest | Anchor filtering implemented in worktree; full process pack planned |
| 2 | Advisory coupled-change obligation | Type 3 | Historical incomplete-fix class; current raw graph/test/check assets | ++ | + | + | ++ | Medium | Highest solve amplifier | Worktree projection and authoritative delivery support implemented; live-unverified |
| 3 | Budgeted completion proof | Type 2 | Video exhausted 100 steps after viable output | + | ++ | ++ | ++ | Medium | High | Mechanics exist; stronger composition planned |
| 4 | Resolved convention record: type/signature/callers/assertions/runtime | Type 3 | Tensor wrong orientation; central type bridge absent | ++ | + if uncertainty preserved | + | + | High | High, risk-sensitive | Planned |
| 5 | Explicit uncertainty/lower-bound/truncation delivery | Type 2 | Historical false positives; GitNexus source patterns | + | ++ | 0/+ | ++ | Medium | High safety enabler | Partly present; unified record planned |
| 6 | Declaration-free identity-only File nodes | Type 2 | Source-backed command-only files can lack declarations | + on availability tasks | + | + | ++ | Low/medium | High on affected tasks | Worktree implementation; Python test passes; Go/live proof pending |
| 7 | Root-search classifier and neutral task wording | Type 1/2 | Three negative trajectories had broad-root returns | 0/+ | ++ | + | ++ | Low | High regression recovery | Worktree implementation; focused tests pass; live-unverified |
| 8 | Graph DB/manifest pair certification and publication lock | Type 1 | Known stale/partial identity risk | 0 | ++ | 0 | ++ | Medium | Gate-critical | Worktree implementation; focused tests pass; concurrency/live proof pending |
| 9 | Receipt/effect/contribution conservation closure | Type 1 | 13/20 release rows failed | 0 | + through accidental-loss prevention | 0 | ++ | Low | Gate-critical, first prerequisite | Committed at `18f95fb`; live-unverified |
| 10 | Legal-source decision replay and operation-replacement accounting | Type 1 research integrity | Every flip remains causally uncertain | Indirect ++ | Indirect ++ | Identifies exact waste | ++ | Medium | High learning value | Capture exists but disabled in run |
| 11 | Selective framework/route/ORM/DI extractors | Type 2 | GitNexus breadth; no current 20 frequency proof | + | 0/+ | + | 0/+ | High | Deferred | Research-only until failure witness |
| 12 | Runtime-KB contradiction activation | Type 3 | Historical zero corrections/185 | + on narrow dynamic class | + | 0/+ | + | Medium | Deferred | Implemented asset, current trigger absent |
| 13 | CFG/PDG/taint | Type 3 | GitNexus opt-in source; no current 20 witness | Unknown | Unknown | - | Low | Low now | Defer |

## Opportunity 1: action-relevant certified process packing

### Mechanism

```text
current action/instruction/change anchor
  -> exact definition and source span
  -> bounded certified callers/callees/route/sink
  -> relevant tests and declared check
  -> one compact lower-bound answer
  -> existing provider request/observation
```

This combines GitNexus's strongest composition pattern with GT's stronger evidence authority. The worktree's action-anchor semantic filter is the first step: it prevents unrelated catalog rows such as sanitize's histogram relation. The next step is grouping relevant edges into an ordered process rather than emitting separate rows.

Expected recovered classes: wrong localization, missed relationship, wrong strategy, context overload, and excessive search/read loops.

Efficiency mechanism: replace the next caller search, file read, or test-discovery action. A frame that does not replace an operation is not counted as an efficiency success.

### Safety contract

- exact current graph/source revision;
- each edge mechanically certified;
- ambiguity/unresolved receiver retained as a boundary;
- branch/depth/path and total/returned/truncated exposed;
- community/co-change support remains rank-only;
- one action-relevance link for every selected fact.

## Opportunity 2: advisory coupled-change obligation

The worktree prototype in [repository_context.py](../../gt_engine/repository_context.py) composes:

```text
changed symbol
  + caller/API-consumer/re-export
  + asserted/test relation
  + declared check
  = Coupled verification surface (advisory)
```

It is `blocking=False` and avoids saying a dependent must be edited. That is correct: a graph relation proves a dependency surface, not a mandatory patch.

Before live use, the authoritative delivery audit must recognize the composed claim, verify constituent claims, persist exact facts, revision, authority, and truncation, and reject incomplete/heuristic constituents. The worktree's projection unit test is not an integrated treatment proof.

Expected new solve class: tasks where the model edits the local implementation but misses a caller, export, route, test, or validation obligation. This is the clearest path for GT to exceed a static GitNexus process answer because GT joins the process to the current diff and observed validation state.

## Opportunity 3: budgeted completion proof

At material change, explicit validation, or deterministic budget risk, compile once per source revision:

- required deliverables present/absent;
- exact declared/discovered checks and latest observed result;
- current changed-file/task-constraint contradictions;
- unresolved coupled obligations;
- one cheapest remaining deterministic probe.

This should change the model's plan when evidence is certified. It must not auto-submit a partial state or create another planning call. The next ordinary provider request receives the bounded proof.

Expected recovered class: video-like near-complete trajectories that continue generating, testing, or exploring until the step budget.

## Opportunity 4: resolved convention record

For tensor-like failures, raw definitions are insufficient. The useful record is:

```text
constructor/signature
  + compiler/LSP-resolved type
  + concrete callers and argument shapes
  + assertion/test shape
  + observed runtime shape when available
  -> exact convention, candidate set, or UNKNOWN
```

The intervention may be strong only when evidence agrees. Conflicting or incomplete evidence becomes a provider-visible candidate set/lower bound. This is higher effort because central benchmark receipts do not yet prove LSP/runtime-KB delivery.

## Type 1 gate bundle

The following work is mandatory before any solve claim, but it is not itself a new capability claim:

1. committed terminal-effect, claim-identity, frontier, and contribution-accounting repairs;
2. worktree neutral/root-search policy;
3. worktree graph DB/manifest certification and publication lock;
4. complete support for composed coupled-obligation delivery;
5. all focused, full Python, Go/indexer, static contamination, provider-free source-built, and same-20 receipt gates.

Passing this bundle means the treatment ran as specified. It does not mean it improves solve rate.

## Strongest path to exceed GitNexus solve rate

The strongest differentiated chain is:

```text
GitNexus-quality process composition
  + GT compiler/LSP/runtime evidence where certified
  + GT task instruction semantics and constraints
  + GT current diff and persistent state
  + GT observed validation/completion state
  + GT claim-level authority and delivery proof
  = current, task-specific coupled-change/completion intervention
```

GitNexus's public source can describe processes and impact; it does not maintain GT's per-edit state or prove provider delivery. GT can turn the same graph relationships into a current verification surface and detect when it is discharged. That is the most plausible new solvable class beyond repository navigation.

## Strongest path to match or beat GitNexus efficiency

1. Deliver on the existing provider request; add no model-selected intelligence tool.
2. Pack one process/obligation answer, not raw edges plus source duplicates.
3. Use semantic supersession: when a composed claim contains caller/test/check constituents, do not render them again independently.
4. Require a recorded replaced operation in replay: search, read, test discovery, or provider call.
5. Gate common-solved uncached input, output, provider calls, and normalized cost independently.
6. Count bootstrap overhead; keep exactly one bootstrap on applicable tasks.

## Opportunities explicitly rejected now

- More stochastic repetitions before integrity is clean.
- A new paid GT-off arm in the treatment-only TB2 promotion workflow.
- Another generic guidance stream.
- Explicit GitNexus-like MCP calls for routine localization.
- Embeddings as an explanation or feature priority; dense retrieval already passed 20/20.
- PDG/taint without a current failure witness.
- Community membership or unique-name edges as obligation authority.
- Benchmark-task-specific rules.

## Decision

The immediate release priority is the Type 1 gate bundle. The immediate product priority is action-relevant process packing plus a fully certified advisory coupled-change obligation. The first removes accidental loss and false evidence salience; the second creates a new solve mechanism. Budgeted completion is the third priority because it can improve both solve rate and provider-call efficiency on near-complete trajectories.
