# GroundTruth Project Completeness Audit

Audit subject: frozen baseline `3df01d2507c1f2fa8907eb2f33342368723a58d5`, with demonstrated defects repaired on `prerelease/gt-harness-v0.9`. Current verdict: **IN PROGRESS — NOT CERTIFIED**.

Passing the inherited test suite is Gate 0 evidence only. The table below records production reachability and external evidence available as of 2026-08-22.

| Component | Exists | Production reachable | Tested | Real-world verified | Canonical | Legacy/dead |
|---|---:|---:|---:|---:|---:|---:|
| `gt-harness` CLI | Yes | Yes | Yes | Local invocation | Yes | No |
| Source indexer provisioning | Yes | Yes | Yes | Windows Go 1.23.4 build; Linux pending rerun | Yes | Opaque wheel/binary removed |
| Git-authoritative discovery receipt | Yes | Yes | Go + Python regressions | GT-Harness and real Git fixtures | Yes | Replaces incompatible Python count comparison |
| Tree-sitter graph construction | Yes | Yes | Go suite + Python integration | GT-Harness and real fixtures | Yes | No |
| Graph receipt/readiness state machine | Yes | Yes | Yes | False-READY reproduction and repair | Yes | No |
| SQLite persistence/atomic publication | Yes | Yes | Existing and new tests | Warm restart fixture | Yes | No |
| Incremental modify/new/delete | Yes | Yes | Real graph lifecycle test | Real temporary Git repository | Yes | No |
| Rename convergence | Yes | Yes | Real graph lifecycle test | Safe full-rebuild fallback | Yes | File-local rename optimization unsupported |
| Query service | Yes | Yes | Yes | Definitions/callers on real fixture | Yes | Accuracy matrix incomplete |
| Production MCP | Yes | Yes | Actual stdio client E2E | Build/query/edit/update/restart/reuse | Yes | Older GT MCP servers non-canonical |
| GroundTruth benchmark treatment | Yes | Yes | Parity and immutability tests | Full task benchmarks not yet authorized | Yes | Legacy `gt_root` bridge non-canonical |
| Bare treatment | Yes | Yes | Strict no-op test | Harness invocation | Yes | No |
| Provider/model adapters | Yes | Yes | Existing adapter tests | Controlled multi-model trial pending | Yes | No model-specific GT logic permitted |
| LSP promotion | Yes in imported GT | Not on canonical default path | Historical tests | Not recertified | No | Candidate research capability |
| Embeddings/ONNX | Yes in imported GT | Not required by canonical structural path | Historical Gate 0 | Clean Linux provisioning pending | No | Optional/research until routed |
| Benchmark compare/certify commands | Placeholder refusal | Explicitly blocked | Exit behavior only | No | No | Must be implemented after evidence schemas |
| Historical central engine/bridge | Yes | Compatibility paths only | Extensive inherited tests | Historical runs only | No | Classification/removal pending |
| Historical workflows/reports | Yes | Several still active | Mixed | Cannot certify current product | No | Cleanup pending |

## Demonstrated release-blocking defects and repairs

1. The vendored wheel provenance hash did not match the wheel and the product identity was `nano-harness 0.0.1`. The wheel and prebuilt binary were removed; pinned first-party source and a content-addressed build became authoritative.
2. The frozen release could report `READY` by comparing a Python discovery count with a different Go discovery policy. Cancellation between omitted dot-directories and additionally indexed Markdown concealed the mismatch. One Go-authored path/reason receipt now controls readiness.
3. Every dot-directory and every directory named `vendor` was excluded, dropping tracked workflows and GT's own Go source. Discovery now uses Git's tracked plus non-ignored working-tree set; `.github` and tracked product source are covered by regression tests.
4. An ignored 91,556,692-byte developer `gt-index.exe` silently outranked the certified source build. The file was removed and local/PATH/cache fallback precedence was deleted from the canonical resolver.
5. A null parse result with no error was not counted as a parse failure. It is now a recorded failure.
6. Incremental selection used `lstrip("./")`, corrupting paths such as `.github/workflow.yml`; path normalization is now exact.
7. Deleted files were skipped by incremental refresh, leaving stale nodes and edges. The Go incremental path now atomically deletes graph rows, hashes, closure/content remnants, and refreshes discovery metadata.
8. Git and indexer subprocesses inherited MCP stdin, hanging repository-backed MCP calls on Windows. Production subprocess stdin is now `DEVNULL`; an actual stdio MCP lifecycle test reproduces and prevents regression.
9. Bare and GT benchmark arms used different system prompts. The prompt is now identical; treatment evidence is the only intended difference.

## Remaining blockers

- Independent graph precision/recall has not yet been measured across the frozen repository matrix.
- Language claims beyond exercised fixtures are not certified.
- Crash/concurrency/failure and scale campaigns are incomplete.
- Graph size on GT-Harness exceeded the prerelease target and needs attribution/optimization without losing facts.
- Historical graph/MCP/control implementations and workflows still require consumer classification before deletion.
- Competitive implementation research and blind GitNexus comparison are correctly blocked until product Gate 12.
- Paid agent benchmarking is not authorized.
