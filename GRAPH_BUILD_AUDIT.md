# GroundTruth Graph Build Audit

Observed: `2026-08-23T01:50:49.443921Z`

Gate status: **PASS on Linux Codespaces for the frozen ten-repository matrix**

Machine receipt: `D:\gt-product-audit-5296dc3\codespaces-5bfb153\real-repository-matrix.json`

This is graph-construction evidence, not universal graph-truth or competitive evidence. Every checkout was clean and pinned by `audit/real_repository_matrix.v1.json`. Each graph was persisted, reopened through a new production service, rebound to the exact repository source revision and graph identity, and queried through the public interface.

## Builder under test

- Product subject: `5bfb153addfd03d84ed675f7c7c8b411a7c6a94b`
- Frozen starting point: `3df01d2507c1f2fa8907eb2f33342368723a58d5`
- Source-tree identity: `e2afb40abc3763c0cc75a03a9a21e12b6c1cf53fb53c0017b31b4fc9f552a83c` (82 files)
- Graph builder: `gt-index-source-e2afb40abc3763c0-repository-identity-v4`
- Graph schema: `v15.3-discovery-receipt`
- Linux binary SHA-256: `f15352d20902eecba9e3c8c403fa3af6acc1d0124ef2120597e2d1c7b3b1ef51`
- Windows reproducibility control: two forced source builds produced `ee656e94e703f820c65ae403d91e84ec4ac62964edaac133d119cf4c34761b41`
- Provider calls / credentials inspected: `0 / false`

## Frozen repository results

| Repository | Build state | Discovered | Attempted | Indexed | Skipped | Failed | Symbols | Nodes | Edges | Coverage |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| itsdangerous | READY | 50 | 29 | 29 | 21 | 0 | 146 | 173 | 398 | 1.000 |
| Django | READY_WITH_DECLARED_LIMITATIONS | 7,085 | 3,500 | 3,500 | 3,585 | 0 | 45,224 | 48,040 | 140,544 | 1.000 |
| Pydantic | READY_WITH_DECLARED_LIMITATIONS | 816 | 729 | 729 | 87 | 0 | 16,569 | 17,284 | 37,906 | 1.000 |
| Express | READY_WITH_DECLARED_LIMITATIONS | 213 | 163 | 163 | 50 | 0 | 1,298 | 1,457 | 1,843 | 1.000 |
| Redux | READY_WITH_DECLARED_LIMITATIONS | 477 | 334 | 334 | 143 | 0 | 677 | 1,008 | 1,142 | 1.000 |
| pnpm | READY_WITH_DECLARED_LIMITATIONS | 5,839 | 4,246 | 4,246 | 1,593 | 0 | 34,848 | 39,069 | 95,206 | 1.000 |
| gorilla/mux | READY | 27 | 23 | 23 | 4 | 0 | 271 | 293 | 880 | 1.000 |
| Testify | READY_WITH_DECLARED_LIMITATIONS | 91 | 73 | 73 | 18 | 0 | 1,156 | 1,229 | 3,320 | 1.000 |
| ripgrep | READY_WITH_DECLARED_LIMITATIONS | 237 | 161 | 161 | 76 | 0 | 3,917 | 4,077 | 10,072 | 1.000 |
| Gson | READY_WITH_DECLARED_LIMITATIONS | 313 | 292 | 292 | 21 | 0 | 4,144 | 4,433 | 12,459 | 1.000 |

Coverage is `files_indexed / files_attempted`, not indexed files divided by every repository file. Every skipped or failed path and reason remains in the graph receipt. Parser recovery makes a graph `READY_WITH_DECLARED_LIMITATIONS`; it cannot produce unqualified `READY`.

## Integrity findings

- All ten receipts reconcile discovery, attempted, indexed, skipped, and failed counts.
- No repository had a parse failure, file-hash failure, SQLite integrity failure, or graph-component failure.
- Every graph contains explicit File nodes plus nontrivial structural edges; suspiciously tiny or empty graphs fail closed.
- Readiness rechecks the exact commit, working-tree source revision, schema, builder identity, SQLite integrity, persisted graph checksum, and `query_ready` state.
- Linux source symlinks were classified `non_regular_file` and never followed. This accounts for the Pydantic and pnpm count differences from Windows without granting external files graph authority.
- A component failure produces `DEGRADED` and is non-queryable. A missing, stale, interrupted, or corrupt graph cannot be returned as ready.

## Reproduction

```bash
python scripts/product_repository_matrix.py \
  --workspace "$WORKSPACE" \
  --output "$RECEIPTS/real-repository-matrix.json" \
  --timeout 1200 \
  --query-repetitions 10 \
  --warm-repetitions 10
```
