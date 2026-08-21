# GroundTruth Product Audit — 2026-08-21

## Scope

This audit covers the latest matched GT-on TB2 run (`32449596981`), the
current source tree, the central readiness/integrity gates, and the repaired
provider-delivery path.

## Latest run truth

Run `32449596981` executed the frozen 20-task `repair20-v1` cohort with GT on.
All 20 tasks completed, all 20 were graded, and none were censored. Fifteen
tasks solved. Promotion was rejected because FEAL had one provider-value
certificate accounting defect.

The five unsolved tasks were `extract-elf`, `regex-chess`,
`torch-tensor-parallelism`, `video-processing`, and `winning-avg-corewars`.
Their receipts reported healthy repository intelligence, retrieval,
artifact-integrity, and mechanical provider barriers. Their losses therefore
were not explained by the known graph, dense-backend, or persistent-state
lifecycle failures.

## Confirmed defect repaired

The repository-context projection contains candidate contributions that may be
rejected by the shared contribution budget. The old delivery preparation used
all projection claim IDs even when only a subset was included in the provider
payload. FEAL consequently advertised the budgeted process claim as delivered,
while the compiler certificate ledger contained only the selected diagnostic
claims. The authoritative audit rejected the receipt with:

`provider_value_certificate_count:6:gt-execution-bb3abf1253c2c059a46a:0`

Commit `7d069573b4c6` filters repository-context receipt facts and claim IDs to
selected contributions before delivery certification. It does not weaken the
certificate requirement.

## Verification completed

- `tests/test_gt_delivery_audit.py`: 36 passed
- `tests/test_central_release_gate.py`: 56 passed
- `tests/test_gt_central_agent.py`: 153 passed, 1 expected ONNX skip
- `python -m compileall -q gt_engine eval scripts`: passed
- `scripts/central_readiness_audit.py`: `READY`, all 18 mechanisms proven
- `scripts/central_integrity_audit.py`: legal-source allowlist proven; no
  grader access proven

The previous FEAL receipt was also replayed with the corrected selected-claim
shape and produced zero delivery-audit failures.

## Remaining risks

1. The repaired commit must be pushed and pass the exact-commit provider-free
   gate before any paid run.
2. The five task-level solve failures remain unresolved and require trajectory
   debugging; they are not currently attributable to infrastructure.
3. The previous run had large reasoning expansion: regex and winning Corewars
   reached 100 provider calls; video used 63; tensor used 61.
4. Historical integrity audits contain observed-fact abstention gaps. These are
   not release failures, but they are a real under-delivery/utilization risk.
5. The local Windows index binary may be stale; Linux source-built indexing is
   authoritative.

## Release rule

The next run must use the same frozen 20 tasks, GT on, and the exact pushed
commit. Integrity, solve outcomes, efficiency, and intervention attribution
must be reported separately. A delivery or lifecycle failure invalidates the
treatment even if the task reward is solved.

