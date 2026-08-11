# Matched outcome smoke results — 2026-08-11

Runs:

- treatment (`certified_context`): `31535815764`
- baseline (`off`): `31535955624`
- commit used by both task arms: `9ca48b9`

Both runs completed all ten task jobs with normal workflow completion. The
strict central trajectory audit certified deterministic receipt integrity for
the treatment (`failures=[]`, all deliveries first-eligible/grounded) and
reported model causality as `UNIDENTIFIABLE`, as required. The baseline has no
GT effects by design.

## Outcome table

| Task | GT-on | GT-off | Delta | GT-on tokens | GT-off tokens | GT deliveries |
|---|---:|---:|---:|---:|---:|---:|
| count-dataset-tokens | pass | pass | 0 | 648,942 | 749,964 | 0 |
| headless-terminal | pass | pass | 0 | 838,050 | 2,077,309 | 1 |
| portfolio-optimization | pass | pass | 0 | 545,240 | 537,541 | 0 |
| prove-plus-comm | pass | pass | 0 | 17,300 | 40,485 | 0 |
| qemu-alpine-ssh | fail | pass | -1 | 2,901,020 | 1,898,391 | 0 |
| regex-chess | pass | fail | +1 | 15,331,460 | 19,542,861 | 4 |
| sanitize-git-repo | fail | pass | -1 | 2,481,132 | 1,262,807 | 0 |
| schemelike-metacircular-eval | pass | pass | 0 | 7,650,357 | 7,104,107 | 1 |
| torch-tensor-parallelism | fail | fail | 0 | 1,918,894 | 1,424,016 | 0 |
| write-compressor | pass | pass | 0 | 2,658,759 | 784,317 | 1 |
| **total** | **7/10** | **8/10** | **-1** | **34,991,154** | **35,421,798** | **7** |

All rewarded outcomes in this smoke had normal task results; no outer censor was
counted as a solve. The treatment gained `regex-chess` and lost
`qemu-alpine-ssh` and `sanitize-git-repo`, for a net one-task regression.

## Resource deltas

These are descriptive single-rollout deltas, not causal efficiency claims:

- total model tokens: **-430,644 (-1.22%)**;
- provider/model calls and assistant steps: **+25 (+5.62%)**;
- model-selected action count: **0** (474 in each arm);
- effective task actions including host/sensor work: **+75 on the six common-solved tasks (+14.59%)**;
- common-solved model tokens: **+1,064,925 (+9.43%)**;
- common-solved calls/steps: **+1**;
- GT-visible deliveries: **7**, all grounded and first-eligible; six tasks had no
  model-visible delivery (three were correctly non-applicable/no-source and
  three source-backed tasks abstained because no bounded high-value evidence
  qualified).

The aggregate token decrease is therefore not an efficiency win: it is driven
by changed trajectories and two outcome losses. On tasks solved by both arms,
tokens increased materially.

## Applicability and delivery

Treatment repository intelligence was `passed/source_backed` for all
source-backed tasks in this slice. `count-dataset-tokens`, `qemu-alpine-ssh`,
and `torch-tensor-parallelism` were `not_applicable_no_supported_source`, so GT
correctly abstained on repository intelligence for those tasks. The treatment
receipt audit produced 8 exact first-intervention replay pairs (including one
private/late-in-trajectory evidence window) and 7 model-visible deliveries.
No late, predictive, duplicate, or ungrounded delivery was found by the strict
trajectory audit.

## Decision

This smoke fails the outcome-preservation and common-solved efficiency gate:

1. GT-on resolved 7/10 versus GT-off 8/10.
2. Two common baseline solves regressed.
3. Common-solved model tokens rose 9.43%, and effective actions rose 14.59%.

The 89-task benchmark remains blocked. The next work is causal adjudication of
the two losses (`qemu-alpine-ssh`, `sanitize-git-repo`) and the one gain
(`regex-chess`) using the captured trajectories, not another unbounded paid
run. This report intentionally does not claim that GT caused any outcome.
