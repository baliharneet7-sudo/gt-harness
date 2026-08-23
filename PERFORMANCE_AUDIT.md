# GroundTruth Performance and Scale Audit

Observed: `2026-08-23T01:50:49.443921Z`

Receipt: `D:\gt-product-audit-5296dc3\codespaces-5bfb153\real-repository-matrix.json`

Verdict: **PASS_WITH_DECLARED_LIMITATIONS on Linux Codespaces**

The canonical source-built product was measured on ten frozen real repositories. The run used no provider, mock graph, precomputed benchmark graph, or substitute query path.

| Repository | Files | Symbols | Edges | Cold ms | Peak MiB | CPU s | Graph MiB | First check ms | Warm p50/p95 ms | Query p50/p95 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| itsdangerous | 29 | 146 | 398 | 496 | 106.3 | 0.47 | 1.0 | 11.5 | 6.4 / 6.9 | 7.3 / 7.6 |
| Django | 3,500 | 45,224 | 140,544 | 125,335 | 461.7 | 178.26 | 302.7 | 1,684.4 | 76.5 / 84.8 | 77.3 / 80.8 |
| Pydantic | 729 | 16,569 | 37,906 | 25,519 | 247.1 | 42.05 | 84.8 | 453.0 | 10.3 / 12.3 | 11.1 / 11.7 |
| Express | 163 | 1,298 | 1,843 | 1,172 | 121.8 | 1.87 | 4.2 | 37.5 | 6.8 / 7.5 | 7.4 / 7.6 |
| Redux | 334 | 677 | 1,142 | 2,152 | 121.8 | 2.74 | 3.1 | 28.1 | 8.9 / 10.6 | 10.0 / 10.6 |
| pnpm | 4,246 | 34,848 | 95,206 | 79,203 | 456.6 | 141.09 | 257.6 | 1,735.7 | 67.7 / 70.1 | 69.6 / 72.3 |
| gorilla/mux | 23 | 271 | 880 | 860 | 124.8 | 1.24 | 2.5 | 19.2 | 4.8 / 8.6 | 5.4 / 5.8 |
| Testify | 73 | 1,156 | 3,320 | 2,142 | 127.8 | 4.53 | 8.4 | 53.8 | 5.3 / 6.1 | 6.2 / 6.6 |
| ripgrep | 161 | 3,917 | 10,072 | 3,921 | 137.0 | 8.00 | 18.3 | 107.0 | 7.0 / 7.6 | 7.4 / 7.6 |
| Gson | 292 | 4,144 | 12,459 | 4,229 | 137.0 | 7.87 | 21.9 | 126.5 | 8.7 / 9.7 | 9.6 / 10.8 |

Peak process-tree RSS was sampled every 10 ms with pinned `psutil==7.2.2`. Warm and query distributions each contain ten observations. The first-process check includes SQLite reopen and the complete persisted-graph checksum; every warm/query operation still verifies repository identity.

## Findings

- Query p95 stayed below 85 ms across this Linux matrix. First-process checks stayed below 1.74 seconds.
- Maximum observed peak RSS was 461.7 MiB. The two largest graphs were Django at 302.7 MiB and pnpm at 257.6 MiB.
- Cold construction is the material limitation: Django took 125.3 seconds and pnpm 79.2 seconds on the four-core Codespaces host.
- The correctness-first edit path performs an atomic full rebuild because file-keyed incremental relationship parity is not yet proven. Its latency is therefore explicit and noncompetitive for large interactive edits.
- v4 readiness avoids rehashing every unchanged normal Git path but still checks current/previous dirty paths, `skip-worktree` and `assume-unchanged` paths, repository identity, and the persisted graph checksum.
- These measurements cover the declared ten-repository matrix on one Linux host. They do not prove scaling beyond the matrix or cross-machine variance.
