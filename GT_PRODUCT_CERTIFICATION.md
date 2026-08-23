# GroundTruth Product Certification

Verdict: `NOT_CERTIFIED`

Audited experimental release: `2140693bc038449cfdf02b49fb03e34eae50ac29`

Core graph implementation entering the final smoke: `d8286c15783ba090e1594bba69d0645d439a1b5c`

Provider-free certification receipt: GitHub Actions run `32634873373` (`SUCCESS`).

The repository graph core retains its prior `CERTIFIED_WITH_DECLARED_LIMITATIONS` evidence: clean Linux install; source-built Go indexer; ten real repositories; exact commit/source identity; persistence/reopen; explicit readiness states; lifecycle/failure campaigns; and bounded truth evidence for Python, JavaScript, TypeScript, Go, Rust and Java.

The complete GT Harness product is nevertheless `NOT_CERTIFIED` because its production-path smoke failed. Run `32635379908` bound and uploaded all 20 trials, but only six run receipts were `COMPLETED`; seven were explicit `ERROR` and seven externally timed-out checkpoints remained `RUNNING`. Interrupted receipts also omitted the exact initial delivered context text. These are release-blocking benchmark-lifecycle and auditability defects even though the graph did not silently claim stale readiness.

Certification can be restored only after timeout finalization, first-checkpoint context durability, Linux certification of the post-experiment Rich rendering fix, and a clean production-boundary smoke with no silently incomplete run state.
