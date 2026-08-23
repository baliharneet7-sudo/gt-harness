# GroundTruth Failure Campaign

Observed: `2026-08-23T00:26:56.900533Z`

Platform campaign: **PASS_WITH_PLATFORM_GAPS**

Machine receipt: `D:\gt-product-audit-5296dc3\receipts\failure-campaign-d2d352a6.json`

| Attack | Expected behavior | Observed | Result |
| --- | --- | --- | --- |
| missing indexer binary | FAILED and non-queryable | FAILED | PASS |
| corrupt indexer binary | FAILED and non-queryable | FAILED | PASS |
| corrupt graph database / wrong checksum | FAILED, then atomic rebuild | FAILED -> READY | PASS |
| corrupt graph receipt | FAILED, then atomic rebuild | FAILED -> READY | PASS |
| deleted graph cache | FAILED, then rebuild | FAILED -> READY | PASS |
| exclusive graph DB lock | correct immutable read or explicit failure; READY after release | consistent READY read -> READY | PASS |
| malformed source | READY_WITH_DECLARED_LIMITATIONS with file evidence | READY_WITH_DECLARED_LIMITATIONS | PASS |
| oversized source file | READY_WITH_DECLARED_LIMITATIONS and too_large receipt | READY_WITH_DECLARED_LIMITATIONS | PASS |
| generated source | READY_WITH_DECLARED_LIMITATIONS and generated receipt | READY_WITH_DECLARED_LIMITATIONS | PASS |
| mixed-language repository | query-ready with exact cross-language inventory | READY | PASS |
| process killed during update | non-queryable partial state; atomic recovery | FAILED -> READY | PASS |
| graph build timeout | FAILED and non-queryable | FAILED | PASS |
| unsupported-only repository | explicit non-queryable failure/degradation | FAILED | PASS |
| Git linked worktree / detached HEAD | repository-bound query-ready graph | READY | PASS |
| Git submodule | query-ready parent with explicit non_regular_file limitation | READY_WITH_DECLARED_LIMITATIONS | PASS |

## Explicitly non-applicable dependencies

The canonical structural graph does not invoke a language server, embedding model, ONNX runtime, or provider. Missing/broken LSP and missing/corrupt model cases are therefore `NOT_APPLICABLE` to graph readiness, rather than hidden dependencies.

## Remaining Linux-only attacks

Unreadable-source permissions, state-directory permission denial, and symlink-loop behavior cannot be credibly certified on this Windows checkout. They remain mandatory for the final Codespaces/Linux proof. This report does not convert them into PASS.
