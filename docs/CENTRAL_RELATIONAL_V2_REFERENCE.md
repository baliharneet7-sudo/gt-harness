# Strengthened GroundTruth Runtime Reference

## Profile contract

`eval.gt_central_agent.MiniSweCentralAgent` accepts `treatment_profile=central_relational_v2`.
Selecting it forces these additive capabilities on:

- `enable_persistent_execution_state=true`;
- `enable_preemptive_retrieval=true`;
- `enable_relational_context=true` by default;
- `enable_semantic_evidence=true` by default; and
- `dense_fallback_only=true` by default.

OFF, AUDIT, and certified-shadow isolation still force active delivery mechanisms off. The default
profile remains `central_pes_v1`.

The profile keeps the canonical product census:

```text
CENTRAL_FEATURE_IDS (17) + persistent_execution_state (1) = 18
```

Repository context is a strengthening component, not a replacement eighteenth mechanism.

## RepositoryContextEngine

Implementation: `gt_engine.repository_context.RepositoryContextEngine`.

Input:

- a typed `DecisionOpportunity` bound to evidence action, eligible provider call, source revision,
  graph revision, paths, and changed symbols; and
- a `RepositorySnapshot` containing current `RepositoryEvidence` and `StructuralLink` rows.

Output: one `RepositoryContextProjection` with:

- terminal status `deliver` or `abstain`;
- complete contribution payloads;
- semantic claim IDs;
- directed execution views;
- impact facts;
- reason codes;
- token/truncation/rejected-edge counts; and
- exact source/graph revisions.

Eligible opportunities are post-read/search, post-mutation, post-diagnostic, post-validation,
post-submit, pre-submit, and diff boundaries. Other opportunities abstain.

## Resolution boundary

`gt_engine.hybrid_repository` reads edge resolution provenance from GraphDB when the schema exposes
it. `candidate_count > 1` is ambiguous. Missing origin/resolution provenance is unknown. Only
program-origin, exact, confidence-at-least-0.95, content-bound, certified edges enter execution and
impact views.

This is intentionally precision-first. Unknown is safer than confidently wrong.

## Delivery

The projection contributes through the existing `compile_contributions()` request budget. The old
`relational_context` and `semantic_evidence` runtime sections remain visible for compatibility but
do not independently deliver duplicate claims in the strengthened profile.

Authoritative receipt paths:

| Path | Meaning |
|---|---|
| `repository_context.decisions` | Every eligible evaluation and terminal status/reason. |
| `repository_context.deliveries` | Provider-visible, hash-bound unified deliveries. |
| `metrics.repository_context_*` | Opportunities, claims, execution views, impact facts, and characters. |
| `model_call_contexts[*].repository_context` | Per-call projection and selection state. |
| `provider_evidence` | Prepared/dispatched/abstained provider-surface ledger. |
| `product_mechanism_census.persistent_execution_state` | Canonical eighteenth mechanism lifecycle. |

`gt_engine.delivery_audit.audit_provider_deliveries()` validates claim support against semantic
items, execution-view IDs, and impact claim IDs, as well as revision, timing, message index, and
request/provider-view hashes.

## Release gate

For `central_relational_v2`, `scripts.central_release_gate` requires:

- healthy graph substrate or legitimate no-supported-source abstention;
- canonical persistent-state initialization, one bootstrap, repeated lifecycle use, and delivery
  accounting when applicable;
- repository-context configuration and opportunity accounting;
- unique delivered claims backed by the stored projection;
- delivery metrics equal receipt rows;
- at least one integrated repository-context delivery across applicable proof receipts;
- dense backend proof unless every attempted dense opportunity was mechanically skipped because
  sparse support already existed; and
- exact canonical 17+1 product identity.

## Benchmark identity

`gt_engine.benchmark_parity.audit_runtime_receipt()` compares two surfaces:

1. `benchmark_identity`: the frozen declaration; and
2. `observed_runtime_contract`: independently reported model, step budget, treatment ID, actual
   agent flags, and execution contract.

Declaration echo alone fails. The agent derives model, step limit, GT flags, and temperature from
its live configuration. The launcher must provide the independently observed execution-envelope
hashes through `observed_execution_contract`; absence fails parity.
