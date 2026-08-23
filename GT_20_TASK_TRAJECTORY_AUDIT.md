# GT 20-task trajectory and local-baseline audit

Audit date: 2026-08-23

This report covers the failed pre-fix GT smoke, not a release certification.

## Cohorts

The GT cohort is `config/tb2_ox_alpha_smoke20.json`, Terminal-Bench 2.0,
`repair20-v1`, `stealth/ox-alpha`, one trial per task, 20 frozen task IDs. Its
purpose is explicitly GT-only end-to-end and trajectory validation. It is not a
causal comparison by itself.

The local baseline is
`D:\tmp\gt_smoke_metrics_20260822\tb2`, Harbor run 32589885199. It uses the
same Ox Alpha route and 17 of the 20 task IDs, but uses
`eval.miniswe_agent:MiniSweAgent` while the GT run uses
`eval.tb_agent:GTNanoAgent`. Therefore it is a useful failure comparator, not a
controlled treatment estimate. `cobol-modernization`, `largest-eigenval`, and
`regex-chess` have no matching baseline artifact in this local cohort.

## Pairwise result

| Task | GT | Baseline | Difference | GT run state | Diagnosis |
| --- | ---: | ---: | ---: | --- | --- |
| count-dataset-tokens | 1 | 1 | 0 | COMPLETED | tie |
| extract-elf | 1 | 0 | +1 | RUNNING | GT solved but receipt was killed before finalization |
| feal-linear-cryptanalysis | 0 | 1 | -1 | ERROR | empty provider response |
| fix-code-vulnerability | 1 | 1 | 0 | COMPLETED | tie |
| headless-terminal | 1 | 1 | 0 | RUNNING | solved, but receipt was killed before finalization |
| llm-inference-batching-scheduler | 0 | 0 | 0 | RUNNING | outer timeout |
| mcmc-sampling-stan | 1 | 1 | 0 | COMPLETED | tie |
| portfolio-optimization | 1 | 1 | 0 | COMPLETED | tie |
| prove-plus-comm | 1 | 1 | 0 | COMPLETED | tie |
| qemu-alpine-ssh | 0 | 1 | -1 | ERROR | Rich markup crash on a literal closing-tag-looking path |
| sanitize-git-repo | 1 | 1 | 0 | COMPLETED | tie; old packet was later found irrelevant and fixed in source |
| schemelike-metacircular-eval | 0 | 1 | -1 | ERROR | empty provider response |
| torch-pipeline-parallelism | 0 | 0 | 0 | RUNNING | outer timeout |
| torch-tensor-parallelism | 0 | 1 | -1 | RUNNING | outer timeout; baseline solved |
| video-processing | 0 | 0 | 0 | ERROR | max-iterations |
| winning-avg-corewars | 0 | 0 | 0 | ERROR | empty provider response |
| write-compressor | 0 | 0 | 0 | ERROR | empty provider response |

Paired totals are GT 8/17 and baseline 10/17. The only paired GT win is
`extract-elf`; paired GT losses are `feal-linear-cryptanalysis`,
`qemu-alpine-ssh`, `schemelike-metacircular-eval`, and
`torch-tensor-parallelism`. This is directional only because the scaffolds are
different.

## Independent receipt and trajectory checks

For GT run 32635379908:

* Harbor task name and GT task ID matched 20/20.
* `verifier/reward.txt` matched Harbor's numeric reward 20/20.
* All 20 `gt-run.json` receipts were present.
* Receipt states were `COMPLETED=6`, `ERROR=7`, `RUNNING=7`.
* The seven Harbor exceptions were real timeout events, not grader mismatches.
* Only FEAL, Bottle vulnerability, and CoreWars retained inspectable GT packets
  in this old release. Their evidence items were marked `verified` and their
  paths/symbols matched the packet source facts. The other interrupted tasks
  lost the initial packet from the durable receipt, which is the blocker fixed
  in the current source.

For the 17 local baseline trajectories:

* All 17 `miniswe_trajectory.json` files parsed.
* Every trajectory had valid message objects and tool-call structure.
* The baseline's `exception_info` values are agent non-zero exits/timeouts, not
  malformed grader records. They remain valid trajectory evidence.

The old GT run therefore had two separate failures: product execution errors
that changed outcomes, and receipt durability that made interrupted context
unrecoverable. The current patch addresses both before another smoke is run.

## Required next run

Rerun the frozen 20-task GT cohort only after the new commit passes the
provider-free Codespaces/GitHub Actions matrix. A valid rerun must have no
`RUNNING` receipts at artifact collection, must retain the exact initial task
and GT packet in every `gt-run.json`, and must be compared to a baseline with
the same scaffold, model, task order, timeout, and environment before any
causal claim is made.
