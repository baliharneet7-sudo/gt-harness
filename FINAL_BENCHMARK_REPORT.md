# Final Benchmark Report

Status: `NOT_RUN_NOT_AUTHORIZED`

GroundTruth subject: `3e2185d3f4ba0a228c740ab2a6d23a287cfc5380`

No paid agent benchmark was run in this audit. Provider calls were `0`, and provider credentials were not inspected.

| Treatment | DeepSWE | SWE-bench / SWE-Live Lite | Terminal-Bench | Solve rate | Cost |
| --- | --- | --- | --- | --- | --- |
| Bare | NOT RUN | NOT RUN | NOT RUN | NOT MEASURED | $0 in this audit |
| GT | NOT RUN | NOT RUN | NOT RUN | NOT MEASURED | $0 in this audit |
| GitNexus | NOT RUN | NOT RUN | NOT RUN | NOT MEASURED | $0 in this audit |

Historical GT results are context, not evidence for this final implementation. In particular, older synthetic wins, the 105/300 versus 113/300 regression, parity post-processing, and small bounded-feedback deltas used different architectures and treatment paths. They cannot be relabeled as results for `3e2185d`.

The provider-free repository-intelligence comparison is reported in `GT_COMPETITIVE_INTELLIGENCE_AUDIT.md`. It establishes fact precision/recall and build-cost evidence, not task resolution, negative flips, treatment consumption, or cost per solve.

Consequently:

- statistically credible solve-rate improvement: `NOT_ESTABLISHED`;
- directional solve-rate improvement: `NOT_ESTABLISHED`;
- parity/regression for final GT: `UNKNOWN`;
- cost/latency impact during agent tasks: `UNKNOWN`;
- causal effect of GT evidence: `UNKNOWN`.

This is the only defensible report while `PAID_BENCHMARK_AUTHORIZATION.md` remains `NOT_AUTHORIZED`.
