# GroundTruth Failure Campaign

Observed: `2026-08-23T03:58:41.613818Z`

Platform campaign: **PASS on Linux Codespaces**

Machine receipt: `D:\gt-product-audit-5296dc3\codespaces-3e2185d\receipts-only\failure-campaign.json`

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
| source symlink and symlink loop | declared limitation; never follow external authority | READY_WITH_DECLARED_LIMITATIONS | PASS |
| unreadable source permission | explicit limitation/degradation with exact path | DEGRADED | PASS |
| state-directory permission denial | structured non-queryable CLI failure | PermissionError payload | PASS |

## Explicitly non-applicable dependencies

The canonical structural graph does not invoke a language server, embedding model, ONNX runtime, or provider. Missing/broken LSP and missing/corrupt model cases are therefore `NOT_APPLICABLE` to graph readiness, rather than hidden dependencies.

The final campaign ran as the non-root Codespaces user on Linux. It closes the permission and symlink gaps that could not be credibly exercised on Windows.
