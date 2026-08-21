# GT 20-task causal receipts

## Evidence boundary

The latest complete archived cohort is workflow `32455040841`, stored locally
under `D:\tmp\run32455040841`. It predates the final refresh, routing, outcome,
and observed-fact accounting repairs. Replaying its receipts through current
code proves compatibility of recorded evidence; it does not prove that the
current runtime executed in that historical run.

Current replay results:

- 20/20 central deterministic replays passed;
- 20/20 provider-delivery audits passed;
- 59 visible deliveries and 175 claims were timely and hash-bound;
- 16/20 archived task release rows passed;
- `count-dataset-tokens` retained a real historical graph-refresh failure;
- FEAL, regex-chess, and schemelike ended in provider connection censors before
  a complete terminal task receipt could be produced.

The exact three errors were a connection reset and two incomplete chunked
reads. They are provider censors, not solved or unsolved verifier outcomes.

## Per-task archived receipt status

| task | graph/retrieval | delivery replay | archived terminal release |
|---|---|---|---|
| cobol-modernization | current | pass | pass |
| count-dataset-tokens | failed refresh | pass for recorded claims | fail |
| extract-elf | current | pass | pass |
| feal-linear-cryptanalysis | current before censor | pass | incomplete/censored |
| fix-code-vulnerability | current | pass | pass |
| headless-terminal | current | pass | pass |
| largest-eigenval | current | pass | pass |
| llm-inference-batching-scheduler | current | pass | pass |
| mcmc-sampling-stan | current | pass | pass |
| portfolio-optimization | current | pass | pass |
| prove-plus-comm | current | pass | pass |
| qemu-alpine-ssh | explicitly non-applicable while source-less | pass | pass |
| regex-chess | current before censor | pass | incomplete/censored |
| sanitize-git-repo | current | pass | pass |
| schemelike-metacircular-eval | current before censor | pass | incomplete/censored |
| torch-pipeline-parallelism | current | pass | pass |
| torch-tensor-parallelism | current | pass | pass |
| video-processing | current | pass | pass |
| winning-avg-corewars | current | pass | pass |
| write-compressor | current | pass | pass |

Every new run must regenerate these receipts from the exact frozen SHA. No
historical row is promoted into current implementation proof.
