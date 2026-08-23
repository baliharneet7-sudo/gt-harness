# GroundTruth Performance and Scale Audit

Observed: `2026-08-23T03:57:29.260900Z`

Receipt: `D:\gt-product-audit-5296dc3\codespaces-3e2185d\receipts-only\real-repository-matrix.json`

Verdict: **PASS_WITH_DECLARED_LIMITATIONS on Linux Codespaces**

The canonical source-built product was measured on ten frozen real repositories. The run used no provider, mock graph, precomputed benchmark graph, or substitute query path.

| Repository | Files | Symbols | Edges | Cold ms | Peak MiB | CPU s | Graph MiB | First check ms | Warm p50/p95 ms | Query p50/p95 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| itsdangerous | 29 | 146 | 449 | 435 | 106.3 | 0.48 | 1.1 | 10.1 | 4.8 / 5.1 | 5.5 / 5.6 |
| Django | 3,500 | 45,224 | 142,622 | 121,580 | 469.6 | 181.13 | 303.2 | 1,682.5 | 73.4 / 77.2 | 74.5 / 75.8 |
| Pydantic | 729 | 16,569 | 38,345 | 24,334 | 240.9 | 42.11 | 84.9 | 455.5 | 9.7 / 10.7 | 10.6 / 10.7 |
| Express | 163 | 1,298 | 1,848 | 1,129 | 122.2 | 2.32 | 4.2 | 36.3 | 6.4 / 7.1 | 6.9 / 7.2 |
| Redux | 334 | 677 | 1,105 | 1,197 | 122.2 | 2.68 | 3.1 | 27.6 | 8.7 / 9.8 | 9.4 / 10.2 |
| pnpm | 4,246 | 34,848 | 94,920 | 74,157 | 469.9 | 142.43 | 257.5 | 1,733.6 | 64.2 / 65.9 | 65.3 / 65.5 |
| gorilla/mux | 23 | 271 | 880 | 797 | 125.2 | 1.23 | 2.5 | 19.4 | 4.6 / 5.0 | 5.2 / 5.4 |
| Testify | 73 | 1,156 | 3,317 | 2,038 | 127.0 | 4.66 | 8.4 | 51.1 | 5.1 / 5.9 | 5.8 / 6.0 |
| ripgrep | 161 | 3,917 | 10,056 | 3,709 | 137.0 | 8.16 | 18.3 | 109.0 | 6.3 / 7.2 | 7.1 / 7.5 |
| Gson | 292 | 4,144 | 12,459 | 3,911 | 137.0 | 7.91 | 21.9 | 124.2 | 8.4 / 9.2 | 8.7 / 9.4 |

Peak process-tree RSS was sampled every 10 ms with pinned `psutil==7.2.2`. Warm and query distributions each contain ten observations. The first-process check includes SQLite reopen and the complete persisted-graph checksum; every warm/query operation still verifies repository identity.

## Findings

- Query p95 stayed below 76 ms across this Linux matrix. First-process checks stayed below 1.74 seconds.
- Maximum observed peak RSS was 469.9 MiB. The two largest graphs were Django at 303.2 MiB and pnpm at 257.5 MiB.
- Cold construction is the material limitation: Django took 121.6 seconds and pnpm 74.2 seconds on the four-core Codespaces host.
- The correctness-first edit path performs an atomic full rebuild because file-keyed incremental relationship parity is not yet proven. Its latency is therefore explicit and noncompetitive for large interactive edits.
- v4 readiness avoids rehashing every unchanged normal Git path but still checks current/previous dirty paths, `skip-worktree` and `assume-unchanged` paths, repository identity, and the persisted graph checksum.
- These measurements cover the declared ten-repository matrix on one Linux host. They do not prove scaling beyond the matrix or cross-machine variance.
