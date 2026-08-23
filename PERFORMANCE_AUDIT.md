# GroundTruth Performance and Scale Audit

Observed: `2026-08-23T00:45:12.538394Z`

Receipt: `D:\gt-product-audit-5296dc3\receipts\matrix-d2d352a6-v4-perf.json`

Verdict: **PASS_WITH_DECLARED_LIMITATIONS on Windows; Linux/Codespaces reproduction remains required.**

This gate measures the canonical source-built product against the ten frozen real repositories in `audit/real_repository_matrix.v1.json`. It does not use mocks, provider calls, precomputed benchmark graphs, or a substitute retrieval path.

## Results

| Repository | Indexed files | Symbols | Edges | Cold wall ms | Peak RSS MiB | CPU s | Graph MiB | First-process check ms | Warm p50/p95 ms | Query p50/p95 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| itsdangerous | 29 | 146 | 398 | 2,241 | 118.8 | 1.969 | 1.0 | 95.5 | 76.4 / 94.5 | 81.7 / 92.9 |
| Django | 3,500 | 45,224 | 140,544 | 214,768 | 408.9 | 419.531 | 302.6 | 1,698.1 | 208.1 / 216.0 | 217.6 / 246.1 |
| Pydantic | 730 | 16,569 | 37,906 | 46,198 | 197.3 | 92.953 | 84.8 | 572.3 | 93.7 / 106.2 | 105.0 / 111.9 |
| Express | 163 | 1,298 | 1,843 | 5,102 | 129.6 | 5.391 | 4.2 | 136.4 | 90.2 / 104.5 | 100.3 / 109.2 |
| Redux | 334 | 677 | 1,142 | 9,596 | 129.9 | 9.516 | 3.1 | 186.3 | 112.5 / 130.7 | 141.8 / 172.4 |
| pnpm | 4,249 | 34,848 | 95,206 | 469,325 | 403.7 | 598.766 | 257.6 | 3,769.7 | 594.4 / 720.0 | 582.0 / 835.4 |
| gorilla/mux | 23 | 271 | 880 | 6,737 | 134.7 | 6.359 | 2.5 | 264.9 | 187.6 / 223.1 | 208.9 / 254.9 |
| Testify | 73 | 1,156 | 3,320 | 12,532 | 141.3 | 15.594 | 8.4 | 380.2 | 191.7 / 224.7 | 203.4 / 266.1 |
| ripgrep | 161 | 3,917 | 10,072 | 23,047 | 138.8 | 28.141 | 18.3 | 459.9 | 191.1 / 216.6 | 228.4 / 267.6 |
| Gson | 292 | 4,144 | 12,459 | 27,962 | 135.0 | 31.094 | 22.0 | 598.2 | 246.8 / 298.8 | 245.2 / 278.2 |

Cold-build resource measurement samples the complete indexer process tree every 10 ms using pinned `psutil==7.2.2`. Query and warm latencies each use ten repetitions. `First-process check` includes reopening SQLite and recomputing the persisted graph checksum. `Warm` is repeated readiness validation in the same service process and still validates repository identity on every call.

## Findings

- Every measured operation returned only after the exact repository source revision, builder/schema identity, SQLite integrity, persisted graph checksum, and query-ready state had been verified.
- The v4 identity path no longer restats and rehashes every clean Git path on every query. It rehashes current/previous dirty paths plus Git `skip-worktree` and `assume-unchanged` paths, while retaining the previous full-scan fallback for non-Git and incomplete receipts.
- Compared with the prior v3 single warm check, steady readiness improved from 4,511.6 ms to 208.1 ms on Django (95.4%) and from 3,529.3 ms to 594.4 ms on pnpm (83.2%). This comparison is directional because the earlier receipt used one warm observation rather than ten repetitions.
- All query p95 values were below 836 ms. All observed peak process-tree RSS values were below 409 MiB.
- Scale is not yet ideal. pnpm required 469.3 seconds cold and Django required 214.8 seconds cold on this Windows host. These are explicit prerelease limitations, not hidden as normal startup latency.
- Persisted graph size is material: 302.6 MiB for Django and 257.6 MiB for pnpm. Cache sizing and eviction policy remain release engineering concerns.
- This receipt does not establish Linux performance, repeated-run variance across machines, or performance against repositories larger than this matrix. Those claims remain open until the Codespaces run.

## Reproduction

```powershell
python scripts/product_repository_matrix.py `
  --workspace D:\gt-product-audit-5296dc3 `
  --output D:\gt-product-audit-5296dc3\receipts\matrix-d2d352a6-v4-perf.json `
  --timeout 1200 `
  --query-repetitions 10 `
  --warm-repetitions 10
```
