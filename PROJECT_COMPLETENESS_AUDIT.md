# GroundTruth Project Completeness Audit

Audit subject: frozen baseline `3df01d2507c1f2fa8907eb2f33342368723a58d5`, with demonstrated defects repaired on `prerelease/gt-harness-v0.9`. Current verdict: **IN PROGRESS - NOT CERTIFIED**.

Passing the inherited test suite is Gate 0 evidence only. The table below records production reachability and external evidence available as of 2026-08-23.

| Component | Exists | Production reachable | Tested | Real-world verified | Canonical | Legacy/dead |
|---|---:|---:|---:|---:|---:|---:|
| `gt-harness` CLI | Yes | Yes | Yes | Local invocation | Yes | No |
| Source indexer provisioning | Yes | Yes | Yes | Reproducible Windows build and clean Linux source build | Yes | Opaque wheel/binary removed |
| Git-authoritative discovery receipt | Yes | Yes | Go + Python regressions | GT-Harness and real Git fixtures | Yes | Replaces incompatible Python count comparison |
| Tree-sitter graph construction | Yes | Yes | Go suite + Python integration | GT-Harness and real fixtures | Yes | No |
| Graph receipt/readiness state machine | Yes | Yes | Yes | False-READY reproduction and repair | Yes | No |
| SQLite persistence/atomic publication | Yes | Yes | Existing and new tests | Warm restart fixture | Yes | No |
| Edit/add/delete/rename convergence | Yes | Yes | Real graph, six-language, and MCP lifecycle tests | Safe full-rebuild publication; zero stale sampled edges | Yes | File-keyed optimization blocked pending relationship parity |
| Query service | Yes | Yes | Yes | 62/62 independently derived sampled relationships across six languages | Yes | Broader randomized truth remains |
| Production MCP | Yes | Yes | Actual stdio client E2E | Build/query/edit/update/restart/reuse with public graph receipt | Yes | Older GT MCP servers non-canonical |
| GroundTruth benchmark treatment | Yes | Yes | Parity and immutability tests | Full task benchmarks not yet authorized | Yes | Legacy `gt_root` bridge non-canonical |
| Bare treatment | Yes | Yes | Strict no-op test | Harness invocation | Yes | No |
| Provider/model adapters | Yes | Yes | Existing adapter tests | Controlled multi-model trial pending | Yes | No model-specific GT logic permitted |
| LSP promotion | Yes in imported GT | Not on canonical default path | Historical tests | Not recertified | No | Candidate research capability |
| Embeddings/ONNX | Yes in imported GT | Not required by canonical structural path | Historical Gate 0 | Clean Linux provisioning pending | No | Optional/research until routed |
| Benchmark compare command | Yes | Yes | Strict pairing/statistics regressions | Awaiting evaluator-completed live receipts | Yes | No provider calls |
| Product certify command | Yes | Yes | Strict positive and adversarial receipt-bundle tests | Exact Linux campaign verification pending the resulting implementation SHA | Yes | Placeholder removed |
| Failure-state campaign | Yes | Yes | 18 Linux attacks | Explicit fail/recover behavior including permissions and symlink loops | Yes | No |
| Performance instrumentation | Yes | Yes | Ten frozen repositories | Linux cold/warm/query/CPU/RSS/graph-size receipt | Yes | No |
| Historical central engine/bridge | Yes | Compatibility paths only | Extensive inherited tests | Historical runs only | No | Classification/removal pending |
| Historical workflows/reports | Yes | Several still active | Mixed | Cannot certify current product | No | Cleanup pending |

## Demonstrated release-blocking defects and repairs

1. The vendored wheel provenance hash did not match the wheel and the product identity was `nano-harness 0.0.1`. The wheel and prebuilt binary were removed; pinned first-party source and a content-addressed build became authoritative.
2. The frozen release could report `READY` by comparing a Python discovery count with a different Go discovery policy. Cancellation between omitted dot-directories and additionally indexed Markdown concealed the mismatch. One Go-authored path/reason receipt now controls readiness.
3. Every dot-directory and every directory named `vendor` was excluded, dropping tracked workflows and GT's own Go source. Discovery now uses Git's tracked plus non-ignored working-tree set; `.github` and tracked product source are covered by regression tests.
4. An ignored 91,556,692-byte developer `gt-index.exe` silently outranked the certified source build. The file was removed and local/PATH/cache fallback precedence was deleted from the canonical resolver.
5. A null parse result with no error was not counted as a parse failure. It is now a recorded failure.
6. Incremental selection used `lstrip("./")`, corrupting paths such as `.github/workflow.yml`; path normalization is now exact.
7. Deleted files were skipped by the historical incremental refresh, leaving stale nodes and edges. Although its deletion mechanics were repaired, the same file-keyed path still does not rerun every whole-repository relationship pass. The canonical product now fails over to an atomic full rebuild for every edit until incremental parity is proven.
8. Git and indexer subprocesses inherited MCP stdin, hanging repository-backed MCP calls on Windows. Production subprocess stdin is now `DEVNULL`; an actual stdio MCP lifecycle test reproduces and prevents regression.
9. Bare and GT benchmark arms used different system prompts. The prompt is now identical; treatment evidence is the only intended difference.
10. Every query rescanned the entire repository and rehashed/rechecked the graph. On the pinned Django checkout this produced an 8.3-second definition query. Receipt v4 uses Git as the authoritative changed-path source, rehashes current/previous dirty paths and special-index paths, and reuses stored hashes only for unchanged normal paths. It retains full-scan fallback and the persisted-graph checksum. Final Django steady readiness p50 is 208 ms and query p95 is 246 ms; pnpm is 594 ms and 835 ms.
11. Extensionless non-source files such as `LICENSE` were mislabeled as unresolved languages. They remain fully accounted for but are now correctly classified as `unsupported_path`.
12. Nonfatal graph component failures were only written to stderr. The Go graph now persists `component_failures`, and any such failure makes the canonical graph `DEGRADED` and non-queryable.
13. Files containing declarations lacked stable file/module nodes. Import and re-export edges were therefore attached to whichever declaration happened to be first, producing false relationships such as Express's `Router` export pointing to an unrelated test function. Every parsed source now has one explicit File anchor, and file relationships can no longer fall back to arbitrary declarations.
14. Rust external imports were suffix-matched to unrelated local modules (`std::process::Command` to ripgrep's local `process.rs`). External paths now abstain unless an exact workspace crate/module target is proven.
15. JavaScript/TypeScript inheritance ignored import provenance, so React's external `Component` was connected to an unrelated local declaration. Type relationships now resolve through proven import targets and abstain on external bindings.
16. TypeScript parser recovery silently omitted declarations after a syntax-error region while reporting successful parsing. Parser recovery is now a first-class receipt limitation, and bounded declaration recovery restored all 22 independently enumerated Redux type re-exports without claiming unqualified `READY`.
17. Hierarchy queries treated a Java class and its same-named constructor as ambiguous even when the graph contained the correct inheritance edges. Query anchoring is now relationship-aware and selects type nodes for subclass/implementation traversal.
18. The Go walker used `os.Stat`, followed source symlinks, and could index an external target while the Python receipt hashed only the link target string. External content could therefore change without changing graph identity. Discovery now uses `os.Lstat`, classifies symlinks and loops as `non_regular_file`, and never gives them graph authority.
19. CLI and MCP exposed different subsets of graph identity, and startup failures could terminate MCP without an agent-visible repository state. Both surfaces now use one public receipt projection; MCP records startup errors and CLI emits a structured non-queryable failure receipt.
20. The source provenance digest sorted platform-native `Path` objects. Windows and POSIX path comparison order differs, so identical 82-file checkouts produced different aggregate identities and Linux `doctor` failed. Identity now sorts normalized POSIX relative-path strings, reports observed as well as expected provenance, and is regression-tested across case-sensitive path order and line endings.
21. The declared development extra omitted `hypothesis`, `zstandard`, and `pytest-timeout`, while the full inherited suite depended on packages already installed on the developer machine. The clean-suite dependencies are now pinned. Tests requiring the separately pinned ARB evaluator or a hosted historical Finalstand artifact are explicitly classified `external_evidence` and cannot masquerade as provider-free product tests.
22. The public `certify` command was a refusal placeholder even after every product gate had executable evidence. It now validates the exact clean Linux subject SHA, campaign steps, provider-free state, receipt schemas, ten-repository graph matrix, bounded truth minimum, lifecycle, six-language matrix, production MCP, and 18-case failure campaign. Any missing or contradictory evidence produces `NOT_CERTIFIED`.

## Current real-repository evidence

- The portable source identity `e2afb40abc3763c0cc75a03a9a21e12b6c1cf53fb53c0017b31b4fc9f552a83c` (82 files) produced byte-identical Windows Go builds twice (`ee656e94e703f820c65ae403d91e84ec4ac62964edaac133d119cf4c34761b41`) and a successful Linux source build (`f15352d20902eecba9e3c8c403fa3af6acc1d0124ef2120597e2d1c7b3b1ef51`).
- All ten frozen repository-matrix checkouts rebuilt, reopened, matched their exact commits, and passed their production query smoke checks.
- The source-derived truth corpus covers Python, JavaScript, TypeScript, Go, Rust, and Java across callers, callees, imports, re-exports, and direct inheritance. Its current bounded result is 62 true positives, 0 false positives, and 0 false negatives. This is strong sampled evidence, not universal accuracy certification.
- Parser recovery and deliberate repository exclusions are exposed as `READY_WITH_DECLARED_LIMITATIONS`; they are never collapsed into unqualified `READY`.
- The same cold/warm/add/modify/delete lifecycle passed for all six declared languages, with zero stale sampled edges.
- A clean stdio MCP client built, queried, updated, restarted, and reused the production graph on a real repository without benchmark machinery.
- The complete Windows Python suite, vendored Go suite, and canonical prerelease lint scope pass. The Linux provider-free suite excludes only tests labeled `external_evidence`; these require the separately pinned official ARB evaluator or a hosted historical Finalstand artifact and are not product-certification evidence.

## Gate 11 cleanup disposition

- Deleted 85 tracked generated run files under `docs/headtohead-runs/`, `artifacts/`, and the remaining `artifact_deepswe/` configurations. They had no production consumer; the DeepSWE configs referenced modules that were already absent. The frozen `gt-frozen-3df01d2` tag retains exact recovery history.
- Retained first-party central-engine, LSP, embedding, delivery, and benchmark code as `RESEARCH` or `BENCHMARK` where unique behavior has not yet been migrated. It is not reachable through the canonical graph authority merely because it remains checked in.
- Retained manually dispatched historical workflows as `LEGACY/BENCHMARK`. They are not product certification and paid execution remains unauthorized. Workflow consolidation remains a release-maintenance item because several historical workflows depend on removed seams.

## Remaining blockers

- Independent graph precision/recall is currently exact on a bounded 62-edge source-derived sample; broader randomized sampling remains.
- Languages beyond Python, JavaScript, TypeScript, Go, Rust, and Java are not certified product support.
- Proven file-keyed incremental parity is absent; correctness currently requires a full rebuild after changes.
- Cold construction is slow on the largest repositories (pnpm 79 seconds; Django 125 seconds on the four-core Linux host), and their persisted graphs are 257.6 MiB and 302.7 MiB.
- Historical graph/MCP/control implementations, generated run outputs, and workflows still require final consumer classification and cleanup.
- The new certification command and documentation require one exact-SHA Linux rerun before Gate 12 can close.
- Competitive implementation research and blind GitNexus comparison remain blocked until that Gate 12 rerun passes.
- Paid agent benchmarking is not authorized.
