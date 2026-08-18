# Terminal-Bench 2.0 regression smoke

Status: prepared, outcome run not yet executed.

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

The previous GT-on artifact remains an offline reference. It is not rerun and
it is not silently treated as the current implementation.

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

After downloading the current merged artifact, run:

```powershell
python scripts/compare_tb2_smoke.py `
  --manifest .research/current-regression-smoke-manifest.json `
  --baseline eval/frozen_baselines/tb2_miniswe_20260731.json `
  --previous-gt artifacts/tb2_31778400203/merged/merged.json `
  --current <current-merged.json> `
  --output .research/tb2-regression-smoke-comparison.json
```

The command emits JSON and a same-stem Markdown report. It performs no task
selection and no model/provider calls.
