# GroundTruth Graph Lifecycle Audit

Observed: `2026-08-23T03:57:34.347957Z`

Verdict: **PASS**

Machine receipt: `D:\gt-product-audit-5296dc3\codespaces-3e2185d\receipts-only\graph-lifecycle.json`

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
- Commit A: `918629af49515abc65777843c009d1fd3e53876b`.
- Commit B: `a22b792760b44065af6a274e04dcfb2229e14d6b`.
- Add, modify, rename, and delete each produced an explicit STALE state before an atomic full rebuild and exact post-update query result.
- A process killed after the BUILDING receipt left no queryable partial graph; a fresh production build recovered the state.
- Concurrent read/update unexpected errors: `0`.

This campaign proves the detailed crash/concurrency lifecycle on one real Python repository. `LANGUAGE_SUPPORT_AUDIT.md` separately applies the same cold/warm/add/modify/delete and stale-edge checks to all six declared languages. Neither campaign claims file-keyed incremental parity; correctness currently uses atomic full rebuilds after edits.
