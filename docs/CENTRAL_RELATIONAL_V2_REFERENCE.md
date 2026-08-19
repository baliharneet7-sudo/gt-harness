# Strengthened GroundTruth Runtime Reference

The final-profile mechanical execution contract and authoritative release proof
are defined in [GT_MECHANICAL_COMPLETENESS_CONTRACT.md](GT_MECHANICAL_COMPLETENESS_CONTRACT.md)
and [GT_RELEASE_DOSSIER.md](GT_RELEASE_DOSSIER.md).

## Profile contract

`eval.gt_central_agent.MiniSweCentralAgent` accepts `treatment_profile=central_relational_v2`.
Selecting it forces these additive capabilities on:

- `enable_persistent_execution_state=true`;
- `enable_preemptive_retrieval=true`;
- `enable_relational_context=true` by default;
- `enable_semantic_evidence=true` by default; and
- `dense_fallback_only=true` by default.
- `persistent_state_selection_mode=deterministic_v1`; and
- `enable_replay_capture=true`.

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
- a `RepositorySnapshot` containing current `RepositoryEvidence`, `StructuralLink` rows, and
  optional five-channel rank-only path hints.

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

Retrieval ranks may order certified process/impact rows for packing. They never certify a row and
cannot turn dense, lexical, or BM25 similarity into provider-visible repository fact authority.

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
| `replay_bundle` | Exact v3 request/control/response bundle metadata. |
| `intervention_chain` | Canonical v2 evidence-to-call-to-visible-action audit metadata. |

`gt_engine.delivery_audit.audit_provider_deliveries()` validates claim support against semantic
items, execution-view IDs, and impact claim IDs, as well as revision, timing, message index, and
request/provider-view hashes.

## Release gate

For `central_relational_v2`, `scripts.central_release_gate` requires:

- healthy graph substrate or legitimate no-supported-source abstention;
- canonical persistent-state initialization, one deterministic selection event, zero selection
  provider calls, repeated lifecycle use, and delivery accounting when applicable;
- repository-context configuration and opportunity accounting;
- unique delivered claims backed by the stored projection;
- delivery metrics equal receipt rows;
- at least one integrated repository-context delivery across applicable proof receipts;
- dense backend proof unless every attempted dense opportunity was mechanically skipped because
  sparse support already existed; and
- exact canonical 17+1 product identity.

The merger additionally verifies the actual replay/chain/trajectory files and emits separate
`integrity_report.json`, `solve_report.json`, `efficiency_report.json`, and
`intervention_report.json`. Visible model reasoning is retained only when the provider returned it;
it is never inferred and is not itself a causal claim.

## Benchmark identity

`gt_engine.benchmark_parity.audit_runtime_receipt()` compares two surfaces:

1. `benchmark_identity`: the frozen declaration; and
2. `observed_runtime_contract`: independently reported model, step budget, treatment ID, actual
   agent flags, and execution contract.

Declaration echo alone fails. The agent derives model, step limit, GT flags, and temperature from
its live configuration. The launcher must provide the independently observed execution-envelope
hashes through `observed_execution_contract`; absence fails parity.
