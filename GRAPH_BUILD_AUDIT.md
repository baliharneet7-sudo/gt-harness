# GroundTruth Graph Build Audit

Observed: `2026-08-23T03:57:29.260900Z`

Gate status: **PASS on Linux Codespaces for the frozen ten-repository matrix**

Machine receipt: `D:\gt-product-audit-5296dc3\codespaces-3e2185d\receipts-only\real-repository-matrix.json`

This is graph-construction evidence, not universal graph-truth or competitive evidence. Every checkout was clean and pinned by `audit/real_repository_matrix.v1.json`. Each graph was persisted, reopened through a new production service, rebound to the exact repository source revision and graph identity, and queried through the public interface.

## Builder under test

- Product subject: `3e2185d3f4ba0a228c740ab2a6d23a287cfc5380`
- Frozen starting point: `3df01d2507c1f2fa8907eb2f33342368723a58d5`
- Source-tree identity: `ed268dbefb3040116f10ea3412cad83d4f3fadf5938482f692558357ec997556` (82 files)
- Graph builder: `gt-index-source-ed268dbefb304011-repository-identity-v4`
- Graph schema: `v15.3-discovery-receipt`
- Linux binary SHA-256: `c21ed5f480c702be88a85ee7eb360b819bb8e577791f1ff97156e7519b30214a`
- Windows source-build control: `eb3f1be3ded1c06577abc6f4fbbfc862e7bc804e1b568f256e387fb1eddf3bc6`; source identity, not cross-platform binary equality, is the provenance invariant.
- Provider calls / credentials inspected: `0 / false`

## Frozen repository results

| Repository | Build state | Discovered | Attempted | Indexed | Skipped | Failed | Symbols | Nodes | Edges | Coverage |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| itsdangerous | READY | 50 | 29 | 29 | 21 | 0 | 146 | 173 | 449 | 1.000 |
| Django | READY_WITH_DECLARED_LIMITATIONS | 7,085 | 3,500 | 3,500 | 3,585 | 0 | 45,224 | 48,040 | 142,622 | 1.000 |
| Pydantic | READY_WITH_DECLARED_LIMITATIONS | 816 | 729 | 729 | 87 | 0 | 16,569 | 17,284 | 38,345 | 1.000 |
| Express | READY_WITH_DECLARED_LIMITATIONS | 213 | 163 | 163 | 50 | 0 | 1,298 | 1,457 | 1,848 | 1.000 |
| Redux | READY_WITH_DECLARED_LIMITATIONS | 477 | 334 | 334 | 143 | 0 | 677 | 1,008 | 1,105 | 1.000 |
| pnpm | READY_WITH_DECLARED_LIMITATIONS | 5,839 | 4,246 | 4,246 | 1,593 | 0 | 34,848 | 39,069 | 94,920 | 1.000 |
| gorilla/mux | READY | 27 | 23 | 23 | 4 | 0 | 271 | 293 | 880 | 1.000 |
| Testify | READY_WITH_DECLARED_LIMITATIONS | 91 | 73 | 73 | 18 | 0 | 1,156 | 1,229 | 3,317 | 1.000 |
| ripgrep | READY_WITH_DECLARED_LIMITATIONS | 237 | 161 | 161 | 76 | 0 | 3,917 | 4,077 | 10,056 | 1.000 |
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
