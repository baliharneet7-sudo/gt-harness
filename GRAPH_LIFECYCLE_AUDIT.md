# GroundTruth Graph Lifecycle Audit

Observed: `2026-08-22T23:53:47.957793Z`

Verdict: **PASS**

Machine receipt: `D:\gt-product-audit-5296dc3\receipts\graph-lifecycle-2b1b648e.json`

The campaign used an isolated local clone of the frozen real itsdangerous checkout. All graph operations went through `RepositoryGraphService` or the production CLI.

| Phase | Result |
| --- | --- |
| cold_start | PASS |
| warm_start | PASS |
| new_file | PASS |
| modified_file | PASS |
| renamed_file | PASS |
| deleted_file | PASS |
| commit_change | PASS |
| restart_during_build | PASS |
| concurrent_reads_update | PASS |

## Key observations

- Cold/warm graph identity stable: `True`.
- Commit A: `40984b415daf18fb6db055f743a29cedc8b6a387`.
- Commit B: `1fe39f2fd6f5b6da539b103dc2ee751a71f2c351`.
- Add, modify, rename, and delete each produced an explicit STALE state before an atomic full rebuild and exact post-update query result.
- A process killed after the BUILDING receipt left no queryable partial graph; a fresh production build recovered the state.
- Concurrent read/update unexpected errors: `0`.

This campaign proves the canonical correctness-first full-rebuild lifecycle on one real Python repository. It does not claim file-keyed incremental parity or certify the same lifecycle for every language yet.
