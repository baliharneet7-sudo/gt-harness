# Terminal-Bench 2.0 regression smoke

Status: executed as workflow `32106687133`; diagnostic only and invalid as
`central_relational_v2` treatment evidence.

This is a diagnostic smoke for the latest `eval.gt_central_agent:MiniSweCentralAgent`.
It is not a promotion verdict and it does not replace the frozen `repair20-v1`
release comparison.

## Frozen selection

The `regression-smoke-v1` profile is recorded in
`eval/frozen_baselines/tb2_miniswe_20260731.json`. Its task set was derived
from the recorded GT-off baseline and the previous GT-on result:

- six measured regressions;
- two measured previous positive flips; and
- two stable solved controls.

The profile carries a task-set SHA-256 and is marked `diagnostic_only`. The
workflow does not contain a separate baseline arm and does not change the
benchmark denominator for the formal 20-task run.

## Comparison inputs

- GT-off: `eval/frozen_baselines/tb2_miniswe_20260731.json`
- Previous GT-on: the existing offline merged artifact from run `31778400203`
- Current GT-on: the merged artifact downloaded from the smoke workflow

The previous GT-on artifact remained an offline reference. It was not rerun.

## Observed result

| Arm | Solved | Tasks | Resolve | Provider calls | Assistant steps | Total tokens | Uncached input | Cost |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| GT off | 8 | 10 | 80% | 506 | unavailable | 29,974,968 | 651,492 | $0.452499 |
| Previous GT | 4 | 10 | 40% | 500 | 489 | 26,208,749 | 598,598 | unavailable |
| Smoke GT | 7 | 10 | 70% | 648 | 634 | 35,856,511 | 1,252,041 | $0.514852 |

Compared with GT off, the smoke gained `count-dataset-tokens` and
`largest-eigenval`, but lost `feal-linear-cryptanalysis`, `video-processing`,
and `winning-avg-corewars`. Compared with previous GT it recovered
`extract-elf`, `headless-terminal`, `torch-tensor-parallelism`, and
`write-compressor`, while losing FEAL.

This is not evidence for the intended strengthened architecture. The archived
receipts identify `treatment_profile=central_pes_v1`; they record
`relational_context=false` and `semantic_evidence=false`. The workflow omitted
the intended typed profile and therefore tested a different treatment.

## Efficiency diagnosis

The expensive rows were dominated by provider history and model exploration,
not graph indexing. FEAL made 68 provider calls and ended with a 532,036-character
provider request; 474,430 characters were distinct assistant reasoning. It
recorded 55 compaction deferrals and zero compactions because the available safe
savings threshold was not met. The current GT contract forbids deleting distinct
Mini-SWE reasoning, so silently summarizing that content would be a contract
change rather than a bug fix.

The old treatment also allowed persistent-state relations over model-authored
paths to be labelled `preexisting_repository`, and it had request-local token
limits without one cumulative task limit. The post-smoke implementation adds
explicit path origin, refuses unsafe provenance, suppresses duplicate PES
advisories under relational v2, and enforces a 4,096-token cumulative discretionary
evidence budget with a 512-token critical reserve. The mandatory bounded PES
lifecycle frame remains available on each applicable request. It cannot guarantee that the coding model
itself will stop exploring; that must be measured in the final run.

## Metrics

`scripts/compare_tb2_smoke.py` compares all three arms per selected task and
reports:

- solved state, resolve rate, positive flips, and negative flips;
- provider, executor, and bootstrap calls;
- assistant steps and environment actions;
- input, output, cached, uncached-input, and total tokens;
- normalized cost when the source artifact provides it;
- checks and workspace-changing actions;
- repository mirror/index latency; and
- visible provider-delivery count/characters and preemptive retrieval metrics.

Missing instrumentation is rendered as `-` and is never coerced to zero. The
GT-off frozen rows do not contain assistant-step receipts, so that field is
expected to be unavailable for that arm.

The archived comparison was generated with:

```powershell
python scripts/compare_tb2_smoke.py `
  --manifest .research/current-regression-smoke-manifest.json `
  --baseline eval/frozen_baselines/tb2_miniswe_20260731.json `
  --previous-gt artifacts/tb2_31778400203/merged/merged.json `
  --current .research/tb2_smoke_32106687133/merged/merged.json `
  --output .research/tb2-regression-smoke-comparison.json
```

The command emits JSON and a same-stem Markdown report. It performs no task
selection and no model/provider calls. The archived smoke must not be promoted
or described as the latest strengthened GT proof.
