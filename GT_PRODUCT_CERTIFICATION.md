# GroundTruth Product Certification

Verdict: `CERTIFIED_WITH_DECLARED_LIMITATIONS`

Implementation subject: `3e2185d3f4ba0a228c740ab2a6d23a287cfc5380`

Frozen baseline: `3df01d2507c1f2fa8907eb2f33342368723a58d5`

Certified on: `2026-08-23T03:58:41.796092Z`

Environment: GitHub Codespaces, Linux `6.8.0-1052-azure`, x86-64, Python 3.12.1, four cores, 16 GiB RAM.

Certification receipt: `D:\gt-product-audit-5296dc3\codespaces-3e2185d\receipts-only\product-certification.json`

Campaign wrapper: `D:\gt-product-audit-5296dc3\codespaces-3e2185d\receipts-only\codespaces-product-certification.json`

The public `gt-harness certify` command independently accepted the complete bundle with zero errors. It verified a clean checkout at the exact implementation SHA, all required campaign steps, all required receipt schemas and statuses, the minimum truth/lifecycle/language/MCP/failure evidence, and provider-free execution. Provider calls were zero; provider credentials were not inspected.

The independent hosted repository-matrix workflow was repaired after GitHub rejected its job-level `runner.temp` expression before job creation. Workflow dispatch run `32617666718` then completed `SUCCESS` in 6m51s against exact input subject `3e2185d`, and uploaded a ten-repository `PASS` receipt (SHA-256 `2218b0315abc0930d98ba2006e950cc8a9edbc1f8913e28a043c8ceeef7eb7e3`). The richer product verdict still comes from the full Codespaces bundle above.

## Certified product facts

| Requirement | Observed evidence | Result |
| --- | --- | --- |
| Clean install and first run | Editable install with pinned development dependencies, `doctor`, source Go build | PASS |
| Repository identity | Exact Git commit plus complete graph-input source revision, including dirty/untracked state | PASS |
| Graph construction | 10 frozen repositories; 9,550 attempted source files; 0 file failures; every graph persisted, reopened, and queried | PASS |
| Graph health | Explicit READY, READY_WITH_DECLARED_LIMITATIONS, DEGRADED, FAILED, STALE, and query-ready state | PASS |
| Graph truth | 62/62 independently source-derived sampled facts across six languages; 0 false positives and 0 false negatives | PASS, bounded sample |
| Persistence and lifecycle | Cold/warm, add, modify, rename, delete, commit change, interrupted build, concurrent reads/update | PASS |
| Incremental correctness | Zero stale sampled edges through atomic full-rebuild publication after edits | PASS, performance limitation |
| Query boundary | Definition, callers/callees, imports/re-exports, hierarchy and source evidence audited | PASS, supported relationships only |
| Optional MCP adapter | Clean stdio client build/query/edit/update/restart/reuse through `gt-harness mcp` | PASS; not the product identity |
| Claimed languages | Python, JavaScript, TypeScript, Go, Rust, Java received real build/truth/lifecycle evidence | PASS with declared parser limits |
| Failure behavior | 18 Linux attacks including corruption, locks, permissions, symlinks/loop, timeouts, dirty trees and unsupported input | PASS |
| Reproducibility | Full provider-free Python suite, Go suite, lint, real campaigns, public certifier | PASS |

## Declared limitations

- The 62-fact truth corpus is exact for the sampled facts; it is not evidence of universal precision or recall over arbitrary repositories.
- Correct edit convergence currently uses an atomic full rebuild. The file-keyed incremental path remains non-canonical until whole-repository relationship parity is proven.
- Parser recovery, generated files, oversized files, non-regular files, and deliberate directory exclusions produce explicit limitations. `READY_WITH_DECLARED_LIMITATIONS` is not equivalent to complete semantic coverage.
- Large cold builds remain expensive on the four-core host: Django took 121.6 seconds and pnpm 74.2 seconds. Their graphs occupied 303.2 MiB and 257.5 MiB.
- Certified language support is limited to Python, JavaScript, TypeScript, Go, Rust, and Java. Other parsers are not product-certified.
- This verdict certifies GroundTruth as a working prerelease product. It does not certify superiority to GitNexus, causal agent solve-rate uplift, or acceptable paid-benchmark economics; those are later gates.

## Gate 12 conclusion

GT Harness now has one production graph authority, a clean installation path, source-built indexer provenance, exact repository-bound readiness, persistent and recoverable graph state, real query evidence, a certified model-agnostic treatment path, an optional MCP adapter, explicit failure states, and a fail-closed certification command. No benchmark-specific graph substitute is required.

Confidence: **high** for the bounded certified scope; **unknown** outside the declared repository, relationship, language, and scale boundaries.
