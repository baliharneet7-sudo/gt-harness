# GroundTruth final benchmark release dossier

## Release status authority

Paid-benchmark eligibility is a machine-verifiable state, not a sentence in
this document. A frozen SHA is eligible only when the
[`central_provider_free.yml`](../.github/workflows/central_provider_free.yml)
run for that exact SHA succeeds and its uploaded
`central_provider_free_receipt.json` records the same commit, zero provider
calls, no provider credentials, and `mechanical_completeness: PASS`. Local tests
establish implementation behavior; the hosted proof establishes the
source-built Linux indexer, pinned dense runtime, full integration suite,
release ancestry, and workflow contract for the exact frozen identity.

The run URL and its content-addressed artifacts are the status record. This
dossier deliberately does not embed a mutable latest-run ID: changing this file
after certification would change the release SHA and invalidate that proof.

The single canonical release identity is
[`eval/release/active_release.json`](../eval/release/active_release.json). No
workflow or merge script owns a second dated “active” prediction path.

## Product bound by the active release

- Agent: `eval.gt_central_agent:MiniSweCentralAgent`
- Treatment: `central_relational_v2`
- Denominator: `repair20-v1`, exactly 20 tasks
- Product census: 17 historical FACT/CAP paths plus persistent execution state
- Selection: deterministic, zero-provider `deterministic_v1`
- Retrieval: exact, lexical, BM25, pinned local dense, and certified structure
- Delivery: bounded same-observation contributions, no extra executor call
- Provider value: `gt.provider_value.v1`; instruction restatements, local
  observation duplicates, and partial/ambiguous relations stay private
- Preflight: `assistive_safe`; no rewrites or silent suppression
- Replay: mandatory and content-addressed
- Repository graph: required when supported source is present; dynamically
  activated when supported source is created
- Compaction: final v2 preserves the stock provider view until measured
  provider-budget pressure; soft character-pressure epochs are forbidden
- Convention: exact only from agreeing signature/type, caller, and test facts
- Completion: typed current-revision predicates; partial or stale proof cannot
  auto-submit

## What “GT did this” means

For every provider-visible effect, the retained artifacts identify the legal
source observation, certified fact or claim, current source/graph revision,
selection decision, exact provider request, changed message index, delivery
time, and next observable model action. The intervention chain reports
observable behavioral uptake without inventing hidden reasoning. Causal
positive or negative flip labels require a matched trajectory or controlled
mechanism ablation; delivery alone is not called causation.

## Mechanical proof chain

1. The canonical release manifest verifies content hashes and Git ancestry.
   The no-spend gate also requires a clean tracked worktree; uncommitted source
   cannot inherit certification from the manifest's older runtime commit.
2. The secret-free release job rejects profile or post-freeze drift.
3. The provider-free workflow builds `gt-index` from current Go source.
4. Parser/spec tests prove declaration-free files retain identity without
   leaking identity-only `File` nodes as semantic symbols.
5. The pinned Snowflake ONNX and tokenizer hashes are verified.
6. The complete central suite exercises repository intelligence, lifecycle,
   retrieval, delivery, persistent state, semantic composition, replay,
   intervention joins, promotion accounting, and mutation-sensitive gates.
   It also proves selected provider claims have exact information-value
   certificates and that rejected/uncertain facts remain controller-only.
7. Static, readiness, legal-source integrity, and pre-smoke checks pass.
8. The authoritative no-spend gate emits one machine-readable verdict.
   The paid caller verifies the certified commit/status before its canary, and
   merge retains and revalidates the provider-free receipt and documentation
   proof.
9. During a task, every executor call passes the provider barrier.
10. At terminal state, every task receives an independently re-audited
    execution certificate.
11. Merge requires all 20 receipts, artifacts, certificates, benchmark
    manifests, trials, and frozen identities before any outcome verdict.
    Canonical result ingestion uses `scripts.harbor_results`; missing or
    conflicting task rows cannot be converted into a score.

## GitNexus research applied without downgrading GT

Source-level research is retained in
[`07_GITNEXUS_ARCHITECTURE.md`](gt_gitnexus_program/07_GITNEXUS_ARCHITECTURE.md),
[`08_GITNEXUS_RESOLUTION_AND_UNCERTAINTY.md`](gt_gitnexus_program/08_GITNEXUS_RESOLUTION_AND_UNCERTAINTY.md),
and
[`09_GITNEXUS_DELIVERY_AND_LIFECYCLE.md`](gt_gitnexus_program/09_GITNEXUS_DELIVERY_AND_LIFECYCLE.md).
GT adopted bounded process composition, process-aware packing,
same-observation augmentation, and stronger atomic graph publication. GT did
not adopt GitNexus’s global unique-name CALLS guesses, silent delivery/setup
failure, static post-edit index behavior, weak cache identity, or reliance on
embeddings as authority. GT retains its stronger LSP/compiler-ready evidence
boundary, revision certification, post-change validation, persistent execution
state, obligation logic, exact delivery receipts, and legal-source audit.

## Historical evidence boundary

The numbered documents under [`docs/gt_gitnexus_program`](gt_gitnexus_program/) are
research and run snapshots. Their embedded commit IDs and “live-unverified”
statements describe the dated evidence they analyze; they are not the active
release identity. The active manifest and this dossier are the current release
authority.

The latest historical 20-task evidence demonstrated that lifecycle and
delivery failures were real and that raw flips were not causally attributable
without baseline trajectories. It does not certify the current candidate. The
new exact-commit provider-free proof certifies mechanics only; solve rate and
efficiency remain measurements for the subsequently authorized same-20 run.

## Paid-dispatch decision

Do not spend while any of these is absent:

- exact final runtime commit and two-file release freeze;
- `GT_MECHANICAL_COMPLETENESS=PASS` for that frozen SHA;
- complete provider-free receipt and artifacts;
- clean documentation/configuration audit; or
- user authorization after reviewing the proof.

After those conditions pass, the next action is one matched 20-task treatment
run—not repeated random smoke runs and not a broader benchmark. Report
integrity, solves, efficiency, and interventions separately.
