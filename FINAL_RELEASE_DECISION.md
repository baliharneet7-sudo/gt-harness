# GroundTruth Final Release Decision

Verdict: `HOLD`

Exact implementation subject: `3e2185d3f4ba0a228c740ab2a6d23a287cfc5380`

Frozen baseline: `3df01d2507c1f2fa8907eb2f33342368723a58d5`

Decision date: `2026-08-23`

`HOLD` applies to a general/competitive release claim. The implementation is credible for a controlled two-month prerelease and is product-certified with declared limitations; it is not yet justified as externally validated agent-performance infrastructure.

## Evidence summary

- Mechanical reproducibility: Codespaces wrapper `PASS` on clean detached Linux exact SHA; install, doctor, full Python/Go tests, canonical lint, all product campaigns, and public certifier passed. Hosted GitHub Actions run `32617666718` independently repeated the exact ten-repository matrix and uploaded a `PASS` artifact. Provider calls `0`; credentials not inspected.
- Product verdict: `CERTIFIED_WITH_DECLARED_LIMITATIONS`.
- Certified languages: Python, JavaScript, TypeScript, Go, Rust, and Java.
- Graph construction: ten frozen real repositories, 9,550 attempted/indexed source files, zero file failures, persisted/reopened exact graph identity on every repository.
- Certification truth corpus: 62 TP, 0 FP, 0 FN over 11 independently derived fact groups. This is bounded, not universal.
- Adversarial GitNexus set: GT 50 TP / 4 FP / 3 FN (precision 0.9259, recall 0.9434); GitNexus 20 TP / 0 FP / 33 FN (precision 1.0, recall 0.3774) over 53 facts. The aggregate is dominated by Redux's 22 re-exports and cannot be generalized.
- Lifecycle: cold, warm, add, modify, rename, delete, commit change, interrupted build recovery, and concurrent access passed; six-language edit campaigns reported zero sampled stale edges.
- Product boundary: `gt-harness run` is the canonical model-agnostic benchmark path. The optional MCP adapter independently passed build/query/edit/update/restart/reuse on a real repository.
- Performance: query p95 was at most 75.8 ms in the ten-repository matrix. Large cold builds remain 121.6 seconds/303.2 MiB for Django and 74.2 seconds/257.5 MiB for pnpm. Edits intentionally use correctness-first full rebuilds.
- Direct build comparison: GT 0.435 s versus GitNexus 4.2 s reported analysis on itsdangerous; GT 1.197 s versus GitNexus 7.8 s on Redux. Node/edge counts are not compared because schemas differ.
- Competitive capability: GitNexus still leads in first-class processes, communities, trace/change tools, hybrid retrieval, optional PDG, and compact delivery. GT leads in exact dirty-source binding, fail-closed readiness, atomic recovery, and selected structural coverage/build cost.
- Agent benchmark: not run and not authorized. No solve-rate, negative-flip, cost-per-solve, or causal-consumption conclusion exists for final GT.

## Remaining limitations

1. Broader randomized relationship truth is required beyond the 62-fact certification corpus and 53-fact competitive set.
2. The adversarial set still exposes four false-positive base-dispatch candidates and three missing Python fixture/factory call sites.
3. Correct edits require atomic full rebuild until file-keyed incremental whole-graph parity is proven.
4. Large-repository cold build and graph size are material prerelease costs.
5. Higher-order process/community/hybrid-ranking/impact capabilities need truth tests and agent ablations before promotion.
6. Historical research, benchmark, and compatibility code remains where it contains unique behavior; it is explicitly non-canonical. Eighty-five proven generated/dead artifacts were removed. More deletion requires consumer proof, not aesthetic cleanup.
7. The common Bare/GT/GitNexus agent experiment, treatment-delivery verification, and statistical plan are not frozen.

## Final questions

| Question | Answer | Confidence |
| --- | --- | --- |
| A. Mechanically reproducible? | Yes, on the certified clean Linux path. | High |
| B. Complete production project? | Yes within the declared prerelease scope; certified with limitations, not a universal repository oracle. | High |
| C. Graph reliably builds? | Yes on the ten-repository matrix; partial/stale/corrupt graphs fail closed. | High |
| D. Graph accurate and sufficiently complete? | Accurate on bounded audited sets; sufficiently complete for prerelease structural use, not universally proven. | Moderate |
| E. Correct across edits, commits, crashes, restarts? | Yes in the certified lifecycle using correctness-first atomic rebuild. | High |
| F. Can a normal coding agent use the product without benchmark substitutes? | The common harness treatment path and optional adapter are production-reachable and tested; live cross-comparator agent consumption remains unproven. | Moderate |
| G. Claimed languages genuinely supported? | Yes for Python, JavaScript, TypeScript, Go, Rust, and Java, with explicit parser limitations. | High |
| H. Competitive with GitNexus/current alternatives? | Competitive and higher-recall on the bounded structural set; inferior in several higher-order abstractions; broad superiority not established. | Moderate |
| I. Causally improves agent solve rates? | Unknown; no authorized final experiment. | Unknown |
| J. Improves without unacceptable cost, latency, or negative flips? | Unknown at the agent-task level; repository build/query costs are measured, solve/cost/flip effects are not. | Unknown |

## Release condition

Use the next two months as an instrumented prerelease. Change `HOLD` only after the comparator treatment is production-integrated without scaffold asymmetry, the benchmark methodology is frozen, paid execution is explicitly authorized, and paired evidence shows useful solve/efficiency behavior without unacceptable negative flips.
