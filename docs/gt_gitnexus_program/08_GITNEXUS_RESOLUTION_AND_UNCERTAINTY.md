Exit code: 0
Wall time: 0.2 seconds
Output:
# GitNexus resolution and uncertainty audit

## Audit identity

- **Official repository:** [abhigyanpatwari/GitNexus](https://github.com/abhigyanpatwari/GitNexus)
- **Pinned revision:** [`fc885a4bf3edddf9214df633d8d1c0767ef58af9`](https://github.com/abhigyanpatwari/GitNexus/commit/fc885a4bf3edddf9214df633d8d1c0767ef58af9)
- **Audit date:** 2026-08-18

Evidence labels:

- **SOURCE-PROVEN:** directly supported by pinned source.
- **INFERENCE:** a likely consequence not isolated by an experiment.
- **UNKNOWN:** not established by public evidence.

## Executive verdict

GitNexus has a real uncertainty model. It suppresses several ambiguous resolutions, persists unresolved receiver information, distinguishes in-program, external, and unknown receiver roots, and exposes lower-bound impact/context results for known missing edges.

It is not uniformly conservative. The most important counterexample is the receiver-less globally unique callable fallback: source comments explicitly state that it can ignore import context and create false cross-package edges, then emit `CALLS` at confidence `0.85`.

The correct GT lesson is therefore selective:

- adapt explicit resolution outcomes, ambiguity suppression, receiver-origin typing, and lower-bound reporting;
- preserve GT's stronger mechanical certification and revision binding;
- reject unique-name inference as intervention authority;
- deliver uncertainty and truncation to the provider, not merely to metadata or logs.

Confidence: **high**.

## 1. Resolution pipeline

The principal source path is:

```text
parsed definitions/references/imports
  -> cross-file reconciliation
  -> scope indexes and definition ownership
  -> receiver-bound resolution
  -> compound receiver-chain folding
  -> free-call fallback and overload narrowing
  -> endpoint lookup
  -> graph-edge emission or explicit suppression/unresolved outcome
```

Relevant implementations:

- [`runScopeResolution()`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus/src/core/ingestion/scope-resolution/pipeline/run.ts)
- [`SCOPE_RESOLVERS`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus/src/core/ingestion/scope-resolution/pipeline/registry.ts)
- [`emitReceiverBoundCalls()`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus/src/core/ingestion/scope-resolution/passes/receiver-bound-calls.ts)
- [`foldReceiverChain()` and `resolveCompoundReceiverTyped()`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus/src/core/ingestion/scope-resolution/passes/compound-receiver.ts)
- [`emitFreeCallFallback()` and `pickUniqueGlobalCallable()`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus/src/core/ingestion/scope-resolution/passes/free-call-fallback.ts)
- [`overload-narrowing.ts`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus/src/core/ingestion/scope-resolution/passes/overload-narrowing.ts)
- [`ResolutionOutcome`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus/src/core/ingestion/scope-resolution/resolution-outcome.ts)
- [`tryEmitEdge()`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus/src/core/ingestion/scope-resolution/graph-bridge/edges.ts)

## 2. Import resolution

[`createImportResolver()`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus/src/core/ingestion/import-resolvers/resolver-factory.ts) composes ordered language-specific strategies.

Source-proven semantics:

- the first non-null result wins;
- an empty `files` array means handled but unresolved and stops the strategy chain;
- null means the strategy did not handle the import;
- a strategy exception propagates immediately instead of silently trying later strategies.

This is a useful explicit distinction between:

```text
not applicable
handled and resolved
handled but unresolved
implementation failure
```

However, an unresolved import does not automatically prevent later global name fallback for every language. That seam is where the most important unsound behavior can appear.

## 3. Receiver-bound calls

### 3.1 Ordered cases

`emitReceiverBoundCalls()` contains ordered cases for:

- `super` calls;
- compound receiver expressions;
- `this`/`self` ownership;
- namespace and module receivers;
- static/class calls;
- dotted bindings;
- chain bindings;
- typed receivers with inheritance/MRO lookup;
- value-receiver object literals;
- class-level field receivers.

The exact case order is material. More specific structural evidence runs before weaker fallback paths.

### 3.2 Receiver-chain folding

`foldReceiverChain()` and `resolveCompoundReceiverTyped()` operate on an AST-derived encoded receiver chain. Supported chain steps include:

- field access;
- method/function calls;
- constructor syntax;
- await-like unwrapping;
- index access;
- return-type propagation where the semantic model supports it.

Resolution stops when a required intermediate type cannot be established. It does not manufacture the remaining chain.

**SOURCE-PROVEN strength:** this is materially better than name-only, one-hop resolution for expressions such as:

```text
service.getUser().address.save()
```

**Limitation:** the chain is only as sound as the parser captures, declared/inferred type evidence, visibility rules, and language adapters. It is not compiler-grade merely because it is multi-hop.

## 4. Explicit resolution outcomes

[`ResolutionOutcome`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus/src/core/ingestion/scope-resolution/resolution-outcome.ts) is a discriminated union:

```text
resolved
  -> targetId, phase, file, name, range

suppressed
  -> reason, candidateIds, phase, file, name, range
  -> optional site kind, receiver shape, receiver origin
```

Suppression reasons include:

- ordinary lookup blocked by C++ ADL rules;
- conversion-rank tie;
- ambiguous inline namespace;
- ambiguous member lookup;
- selected callable deleted;
- overload ambiguity;
- normalized overload ambiguity;
- free-call instance ownership mismatch;
- receiver owned by its scope but unbound;
- receiver type unresolved.

This is a strong design pattern because the absence of an edge is not collapsed into one undifferentiated zero.

## 5. Receiver shape and origin

### 5.1 Structural shape

Unresolved receivers can record an AST-derived shape:

- `chain-call`;
- `chain-field`;
- `chain-mixed`;
- `chain-unwrap` for await/index steps;
- `no-chain`.

The source explicitly warns that this is a census only of unresolved sites that reached the recorder. It is not proof that every invisible parser/resolution gap was observed.

### 5.2 Origin

`classifyReceiverOrigin()` returns:

- `in-program` when the base/type is known inside the analyzed code;
- `external` only when there is positive language-provider evidence such as a declared built-in;
- `unknown` when neither status can be established.

The safe policy is explicit: `unknown` is grouped with `in-program` when determining whether impact/context counts may be incomplete. Unknown is not assumed external.

This directly matches a critical GT invariant:

> Absence of evidence is not evidence that the relation is external or nonexistent.

### 5.3 Why this matters

An unresolved external call such as a language built-in may have no in-repository target, so its absence is not necessarily a graph defect. An unresolved call on an untyped parameter may hide a real in-repository edge, so reporting exact caller counts would be wrong.

GitNexus's three-way split is worth adapting into GT's evidence ledger where GT currently collapses origin classes.

## 6. Overloads and ambiguity

The free-call and receiver passes combine:

- lexical and import scope;
- callable ownership;
- arity;
- argument types and type classes;
- language-specific conversion ranking;
- C++ ADL and namespace rules;
- deleted-callable checks.

When multiple overload candidates remain tied after narrowing, the source records a suppression outcome and emits no arbitrary edge.

Confidence: **high** that this policy would prevent a class of false-positive corrective interventions based on arbitrary overload choice.

It cannot be claimed to explain any of GT's current four negative flips until Track A proves that one of those flips was caused by this exact ambiguity class.

## 7. Edge emission and confidence

[`tryEmitEdge()`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus/src/core/ingestion/scope-resolution/graph-bridge/edges.ts) emits only when source, target, and edge type are available. The graph stores a numeric confidence and reason.

Important distinction:

```text
GitNexus numeric confidence
  !=
GT mechanical certification
```

A numeric score says how the implementation ranks trust. It does not by itself prove:

- import visibility;
- complete index coverage;
- current source revision;
- provider delivery;
- suitability as an intervention authority.

GT should accept GitNexus-style confidence only as one input to its stronger conjunctive certification boundary.

## 8. The globally unique callable fallback

This is the most important source-proven weakness.

In `emitFreeCallFallback()`, when `allowGlobalFallback=true`, `pickUniqueGlobalCallable()` may choose a callable that is globally unique by simple name. The source comments state:

- it can ignore import context;
- false cross-package edges are possible when the caller does not import the target package;
- same-package calls are often resolved earlier, but that does not make the fallback sound;
- the emitted `CALLS` edge receives confidence `0.85`.

The fallback does filter some file-local definitions and can apply an optional language-specific caller-visibility predicate. That reduces risk for supported languages but does not establish a universal import proof.

### GT decision

Reject this mechanism as delivery or intervention authority.

At most, a globally unique name can be:

- a rank-only candidate;
- explicitly labeled heuristic;
- excluded from contradiction, obligation, and command-return decisions;
- upgraded only when import, scope, compiler/LSP, or other positive evidence establishes visibility.

This is exactly the historical false-positive class GT must not reintroduce.

## 9. Query-time ambiguity

[`LocalBackend.context()`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus/src/mcp/local/local-backend.ts) uses symbol candidate resolution rather than silently selecting an arbitrary same-name symbol.

If multiple candidates survive, it returns:

- `status: ambiguous`;
- a true or lower-bound total;
- the displayed candidate window;
- UID, kind, file path, line, and score;
- an instruction to disambiguate by UID, path, or kind.

This is a strong delivery pattern: ambiguity is model-visible and actionable.

## 10. Epistemic lower bounds

[`computeEpistemicBoundary()`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus/src/mcp/local/local-backend.ts) can mark `context` and `impact` as:

- `exact`; or
- `lower-bound` with boundary notes and cause counts.

Source-proven lower-bound causes include:

- unresolved in-program or unknown receiver typing;
- external receiver boundaries tracked separately;
- interface/abstract dispatch with consumers or multiple implementations;
- unresolved/undecided structural interface satisfaction;
- dependency-injection or dynamic-dispatch boundaries represented through interface relations.

The current implementation specifically avoids treating metadata-read failure as certainty: if the heritage probe fails, it preserves any already-known dropped-receiver boundary through `epistemicFrom(...)`.

This corrects a key failure mode:

```text
probe failure
  must not become
exact zero
```

## 11. Incompleteness that is still under-delivered

### 11.1 Context relation caps

`LocalBackend.context()` caps incoming and outgoing relation queries. The source itself notes that the categorizer emits the rows it receives without a truncation flag. Therefore a category can disappear from a high-fan-in response even though more relations exist.

Classification: **SOURCE-PROVEN silent incompleteness risk**.

GT adaptation: every capped relation family must expose total/returned/truncated or explicitly state lower-bound.

### 11.2 Process truncation

Process extraction records six truncation counters and logs whole-flow loss. Normal `query` output does not join those counters to the returned process list.

Classification: **SOURCE-PROVEN internal observability, incomplete provider observability**.

GT adaptation: provider-visible process claims must carry their completeness boundary and graph revision.

### 11.3 Automatic augmentation

[`augment()`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus/src/core/augmentation/engine.ts) returns compact callers, callees, and flows but omits:

- edge confidence;
- receiver-origin uncertainty;
- process truncation;
- relation totals;
- lower-bound status;
- source/index revision.

Classification: **SOURCE-PROVEN weaker uncertainty delivery than full MCP responses**.

### 11.4 Dynamic framework behavior

GitNexus extracts several DI, Spring, AOP, route, event, and tool relationships. Dynamic registration, reflection, runtime mutation, framework conventions not represented by an extractor, and unresolved types can still leave missing edges.

Classification: **known static-analysis boundary**, exact coverage unknown per repository.

## 12. Failure behavior by condition

| Condition | Source-proven behavior | Conservative? | GT implication |
|---|---|---:|---|
| Import strategy not applicable | try next strategy | Yes | preserve typed not-applicable |
| Import handled but unresolved | empty result stops chain | Yes locally | ensure later global fallback cannot upgrade without proof |
| Import resolver throws | abort resolution path | Honest failure | receipt as substrate failure, not empty graph |
| Ambiguous overload | suppress edge and record candidates | Yes | adapt |
| Unresolved compound receiver | suppress and record shape/origin where available | Yes | adapt |
| Unknown receiver origin | hedge as potentially in-program | Yes | adapt |
| Positively identified built-in/external receiver | do not count as missing in-program target | Yes | adapt with provenance |
| Multiple same-name query symbols | return ambiguity and candidates | Yes | adapt |
| Interface/dynamic boundary | mark lower-bound when supported | Yes | adapt |
| Globally unique free callable | may emit without proven import, confidence 0.85 | No | reject as authority |
| Context relation window exhausted | rows omitted without complete truncation signal | No | require completeness receipt |
| Process traversal capped | counters recorded, not fully joined to provider response | Partial | deliver counters with claim |
| Automatic augment error | empty string | Operationally graceful, analytically weak | fail open to agent but fail closed in release accounting |

## 13. Would GitNexus's policy prevent known GT negative interventions?

### Source-supported answer

It could prevent a negative intervention if the GT loss was caused by:

- arbitrary overload selection;
- treating an unresolved receiver as a proven target;
- treating unknown as external or nonexistent;
- silently choosing one of several same-name symbols;
- reporting exact impact across a known interface/dynamic boundary.

### Counterexample

It could create or preserve a false relation if the loss was caused by globally unique name matching without import visibility. GitNexus's confidence `0.85` does not make that relation safe.

### Causal status

For the four current negative flips: **UNKNOWN** until Track A identifies the exact evidence delivered before divergence. No source comparison can replace the per-trajectory autopsy.

## 14. GT uncertainty contract to adopt

For every candidate semantic relation, persist:

```text
origin
  = in_program | external | unknown

resolution
  = exact | ambiguous | unresolved | suppressed | heuristic

completeness
  = exact | lower_bound | truncated | unavailable

visibility
  = import_proven | scope_proven | compiler_proven | framework_proven | unproven

revision
  = exact source and graph revision

authority
  = rank_only | deliverable | obligation_authorizing | intervention_authorizing
```

Promotion rules:

1. Unknown remains unknown.
2. Ambiguity remains a candidate set, never a guessed singleton.
3. An incomplete index cannot prove nonexistence.
4. Rank-only evidence cannot create contradiction, obligation, or intervention.
5. A capped result must state its lower-bound/truncation status.
6. Current revision and endpoint provenance are mandatory for provider delivery.
7. Mechanically certified relations may alter the model's plan; the objective is defensible influence, not passive advice.

## 15. Ranked adaptations

1. **Receiver origin and unresolved-shape ledger** — high value, low risk.
2. **Explicit resolved/suppressed/ambiguous outcomes** — high value, low risk.
3. **Provider-visible lower-bound and truncation status** — high value for preventing false negatives.
4. **Multi-hop receiver folding on GT-proven gaps** — moderate/high value, implementation dependent.
5. **Interface/dynamic-dispatch boundary accounting** — moderate value, prevents confident undercount.
6. **Query-time candidate disambiguation with stable IDs** — moderate value where provider asks directly.

## 16. Explicit rejections

1. Globally unique callable resolution without proven visibility.
2. Numeric confidence as a substitute for certification.
3. Silent empty augmentation as successful treatment delivery.
4. Capped callers/callees/processes presented as complete.
5. Community membership as a semantic fact.
6. A process path as proof of runtime execution.
7. External classification without positive language/runtime evidence.

## Final verdict

GitNexus's best uncertainty work is directly compatible with GT's thesis: deterministic repository intelligence should admit what it does not know. Its worst fallback demonstrates why GT's stronger intervention boundary remains necessary.

The implementation target is not “copy GitNexus confidence.” It is:

```text
GitNexus-style explicit resolution outcomes
  +
GT mechanical provenance, certification, revision binding, and delivery receipts
  =
aggressive but defensible engine behavior
```

