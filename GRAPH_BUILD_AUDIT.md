# GroundTruth Graph Build Audit

Observed: 2026-08-22. Gate status: **PASS for the frozen ten-repository Windows matrix; Linux clean-environment rerun remains a release prerequisite.**

This is graph-construction evidence, not graph-truth or product certification. The machine-readable receipt is `D:\gt-product-audit-5296dc3\receipts\matrix-2b1b648e.json`.

## Builder under test

- Frozen starting point: `3df01d2507c1f2fa8907eb2f33342368723a58d5`
- Repair branch: `prerelease/gt-harness-v0.9`
- Source-tree identity: `2b1b648e418a450ef7a738dde2d44ffcb0238d59e3ca8f530a7dd465649ab6bb` (82 files)
- Graph builder: `gt-index-source-2b1b648e418a450e-repository-identity-v3`
- Graph schema: `v15.3-discovery-receipt`
- Windows binary SHA-256: `6425af23ba4df377abd479b5d14c598fd2ce66d1e2c7b8768f6f4891fea8b750`
- Reproducibility: two forced source builds produced the same binary SHA-256.
- Provider calls: 0
- Provider credentials required or inspected: false

## Frozen repository results

Every checkout was clean and detached at the commit pinned in `audit/real_repository_matrix.v1.json`. Every candidate graph was persisted, reopened through a new `RepositoryGraphService`, rebound to the same repository source revision and graph checksum, and successfully served its smoke query.

| Repository | Build state | Discovered | Attempted | Indexed | Skipped | Failed | Symbols | Nodes | Edges | Coverage |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| python-small-itsdangerous | READY | 50 | 29 | 29 | 21 | 0 | 146 | 173 | 398 | 1.000 |
| python-large-django | READY_WITH_DECLARED_LIMITATIONS | 7,085 | 3,500 | 3,500 | 3,585 | 0 | 45,224 | 48,040 | 140,544 | 1.000 |
| python-reexports-pydantic | READY_WITH_DECLARED_LIMITATIONS | 816 | 730 | 730 | 86 | 0 | 16,569 | 17,285 | 37,906 | 1.000 |
| javascript-express | READY_WITH_DECLARED_LIMITATIONS | 213 | 163 | 163 | 50 | 0 | 1,298 | 1,457 | 1,843 | 1.000 |
| typescript-redux | READY_WITH_DECLARED_LIMITATIONS | 477 | 334 | 334 | 143 | 0 | 677 | 1,008 | 1,142 | 1.000 |
| typescript-pnpm | READY_WITH_DECLARED_LIMITATIONS | 5,839 | 4,249 | 4,249 | 1,590 | 0 | 34,848 | 39,072 | 95,206 | 1.000 |
| go-gorilla-mux | READY | 27 | 23 | 23 | 4 | 0 | 271 | 293 | 880 | 1.000 |
| go-testify | READY_WITH_DECLARED_LIMITATIONS | 91 | 73 | 73 | 18 | 0 | 1,156 | 1,229 | 3,320 | 1.000 |
| rust-ripgrep | READY_WITH_DECLARED_LIMITATIONS | 237 | 161 | 161 | 76 | 0 | 3,917 | 4,077 | 10,072 | 1.000 |
| java-gson | READY_WITH_DECLARED_LIMITATIONS | 313 | 292 | 292 | 21 | 0 | 4,144 | 4,433 | 12,459 | 1.000 |

Coverage is `files_indexed / files_attempted`, not `files_indexed / every repository file`. Every skipped path and reason remains in the graph receipt. A recovered syntax tree counts as indexed but forces `READY_WITH_DECLARED_LIMITATIONS` and records the affected file; it cannot produce unqualified `READY`.

## Declared limitations observed

| Repository | Declared reasons |
| --- | --- |
| Django | 51 parser-recovery regions; 2 unresolved-language files |
| Pydantic | 2 parser-recovery regions; 2 generated files |
| Express | 3 parser-recovery regions |
| Redux | 5 parser-recovery regions; 1 oversized file |
| pnpm | 8 parser-recovery regions; 2 oversized files; 82 files under excluded dependency/build directories |
| Testify | 4 generated files |
| ripgrep | 2 parser-recovery regions |
| Gson | 3 parser-recovery regions; 1 unresolved-language file |

These limitations require targeted language-truth review. They are not silently treated as complete indexing.

## Sanity and integrity checks

- No repository had a parse failure, file-hash failure, or graph component failure.
- Discovery accounting, parse accounting, file-hash accounting, and detailed-failure accounting were internally consistent for all ten receipts.
- Nontrivial repositories contained imports/calls and hundreds to hundreds of thousands of edges; the suspicious-empty and no-edge guards did not fire.
- The exact commit, complete graph-input source revision, schema, builder identity, SQLite integrity, persisted graph digest, and `query_ready` state were checked again on warm reopen.
- A graph with any component failure is `DEGRADED` and non-queryable. A graph with declared parser recovery remains queryable only as `READY_WITH_DECLARED_LIMITATIONS`.

## Performance observations (not a performance PASS)

The largest cold builds were Django (171,939 ms indexer time; 249,959 ms wall time) and pnpm (113,864 ms indexer; 149,561 ms wall). Warm status checks were 4,512 ms and 3,529 ms respectively. These are correctness-preserving measurements and remain inputs to Gate 10; they are too slow to call the performance gate complete.

## Reproduction

```powershell
python scripts/product_repository_matrix.py `
  --workspace D:\gt-product-audit-5296dc3 `
  --output D:\gt-product-audit-5296dc3\receipts\matrix-2b1b648e.json `
  --timeout 1200
```
