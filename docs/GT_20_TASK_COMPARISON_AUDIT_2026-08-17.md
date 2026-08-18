# GroundTruth 20-Task Comparison Audit

## Scope

This is the comparison required before claiming parity or improvement:

1. the frozen baseline;
2. the previous GT-on small run; and
3. the strengthened GT candidate after the current implementation.

No ablation result is used as a success criterion. The task denominator remains the caller-selected
20-task manifest, and every task remains counted.

## Existing evidence

Sources inspected:

- frozen baseline: `eval/frozen_baselines/tb2_miniswe_20260731.json`;
- previous 20-task GT run: `artifacts/tb2_31778400203/merged/merged.json`;
- previous 15-task GT run: `artifacts/tb2_31748290228_merged/merged.json`;
- historical gate logic: `scripts/tb2_promotion_gate.py`.

The previous 20-task artifact is an older `central-certified_full-integrated` run. It is not an
outcome measurement of the current semantic-evidence candidate.

## Result from the previous 20-task run

| Measure | Frozen baseline | Previous GT-on | Difference |
|---|---:|---:|---:|
| Tasks | 20 | 20 | 0 |
| Resolved | 17 | 13 | -4 |
| Resolve rate | 85.0% | 65.0% | -20.0 pp |
| Positive flips | — | 2 | `count-dataset-tokens`, `largest-eigenval` |
| Negative flips | — | 6 | `extract-elf`, `headless-terminal`, `torch-tensor-parallelism`, `video-processing`, `winning-avg-corewars`, `write-compressor` |
| Total tokens | 65,625,578 | 53,437,150 | -18.6% |
| Provider calls | 1,041 | 1,024 | -1.6% |

The previous GT run therefore failed the actual objective: it was cheaper, but materially less
reliable. It cannot be used as evidence that GT is at parity with GitNexus or better.

## What the audit says to fix

The immediate target is not more features or more ablations. It is recovering the six negative
flips while preserving the two positive flips, without increasing calls or tokens. The current
candidate specifically targets the measured delivery/composition gap by putting bounded certified
semantic relationships into the existing provider request, while refusing stale, ambiguous, weak,
or malformed evidence.

## Required next run

Run only the caller-supplied matched comparison:

- frozen baseline;
- previous GT configuration, if reproducible under the same contract;
- strengthened GT candidate.

The manifest must bind the exact task bytes, task order, provider/model, sampling, scaffold,
tool/hook envelopes, timeout/retry policy, hardware assumptions, token accounting, step budget,
trial count, and treatment identity. The new `audit_runtime_receipt()` gate must pass before any
outcome row is accepted.

Report:

- resolve rate;
- positive and negative flips against the same baseline;
- calls, actions, steps, input/output/uncached tokens, and cost;
- files opened/edited and checks run;
- GT delivery count, delivery tokens, latency, and abstentions;
- infrastructure-invalid rows separately from agent failures.

Parity means at least the baseline resolve rate with no unacceptable negative-flip increase. Better
means a higher resolve rate with equal or lower calls/tokens/cost and no material increase in
negative flips.

## Status

The comparison infrastructure and audit are implemented. The strengthened candidate has not yet
been run on the 20-task benchmark, so its solve rate is currently **unknown**. No claim of parity,
outperformance, or GitNexus superiority can be made from the prior artifact.
