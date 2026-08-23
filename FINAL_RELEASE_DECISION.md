# GroundTruth Final Release Decision

Verdict: `BLOCK`

Exact experimental release SHA: `2140693bc038449cfdf02b49fb03e34eae50ac29`

Implementation SHA: `d8286c15783ba090e1594bba69d0645d439a1b5c`

Latest post-experiment fix SHA: `b1020bd47929e740ce5e4532d4e151f510602afb` (not release-certified)

Decision date: `2026-08-23`

The graph core remains credible within its certified scope, but GT Harness is not yet a complete official benchmarking product. The production 20-task run did not satisfy end-to-end completion: 14/20 GT run receipts were non-complete and seven timeout checkpoints remained `RUNNING`. The workflow correctly failed closed.

## Evidence

- Exact-subject provider-free run `32634873373`: PASS for clean install, Linux Python/Go, and frozen ten-repository matrix.
- Final smoke `32635379908`: Harbor 20/20 graded; 8 solved, 12 unsolved, 7 `AgentTimeoutError`; artifact upload PASS; outcome binding 20/20 PASS; integrity gate FAIL because 14 receipts were not `COMPLETED`.
- Treatment split: 7 ACTIVE, 13 NOT_APPLICABLE. ACTIVE delivery was bounded to 12 packets, 36,307 characters, 18 source-verified evidence items, maximum four packets per task.
- Graph certification scope remains Python, JavaScript, TypeScript, Go, Rust and Java, with correctness-first atomic rebuild and declared parser limitations.
- Bounded fact comparison remains GT 50 TP / 4 FP / 3 FN versus GitNexus 20 TP / 0 FP / 33 FN over 53 facts. This does not establish broad superiority.
- No controlled Bare/GT/GitNexus solve-rate experiment exists. Cost, negative flips and causal uplift remain unknown.

## Release blockers

1. Reserve shutdown grace and atomically finalize every interrupted receipt as explicit `ERROR`/`TIMEOUT`, never `RUNNING`.
2. Persist the exact initial task plus delivered GT packet before the first provider call so timeout trajectories remain auditable.
3. Certify the post-experiment plain-text Rich rendering fix on Linux.
4. Add provider-free kill/recovery tests at the actual Harbor boundary, including ownership, binding and upload.
5. Run paired Bare/GT/GitNexus trials only after the product smoke passes; do not infer uplift from 8/20 GT-only results.

## Final questions

| Question | Answer | Confidence |
| --- | --- | --- |
| A. Mechanically reproducible? | Yes for clean install, graph matrix and source build at the experimental release. | High |
| B. Complete production project? | No; benchmark receipt finalization and interrupted trajectory durability are incomplete. | High |
| C. Graph reliably builds? | Yes on the certified ten-repository matrix. | High |
| D. Graph accurate and sufficiently complete? | Accurate on bounded audited facts; broad completeness remains unproven. | Moderate |
| E. Correct across edits, commits, crashes and restarts? | Graph lifecycle passed; agent-run timeout lifecycle did not. | High |
| F. Normal agent without benchmark substitutes? | Production GT Harness ran, but only 6/20 runs completed cleanly. | High |
| G. Claimed languages genuinely supported? | Six languages are graph-certified with declared limits. | High |
| H. Competitive with GitNexus? | Competitive structurally; weaker in processes, communities, trace, hybrid retrieval and PDG. | Moderate |
| I. Causally improves solve rates? | Unknown; no paired experiment. | High |
| J. Improves efficiency without negative flips? | Unknown; 404 calls and 4.45M input tokens were observed without a matched comparator or cost receipt. | High |

The two-month prerelease may continue as a development program, but this exact product must not be called complete or ready for broad release.
