# GroundTruth Final Release Audit

Date: 2026-08-18

## Scope

This audit covered the implementation after the P0-P2 repairs, the exact hosted
provider-free workflow, the uploaded proof artifact, and the remaining benchmark
boundary. GitNexus is a design reference only. It is not a benchmark arm.

## Hosted evidence

The runtime commit was `15bc9424cec8c9bfdf34db58c66e645ec92f8724`.

Provider-free workflow run `32153590102` passed on that exact commit in 3m06s.
The run passed:

- source-built `gt-index` compilation and Go parser/spec regressions;
- pinned Snowflake ONNX and tokenizer hash checks;
- repository substrate and language-depth checks;
- central runtime tests;
- structural readiness and legal-source integrity audits;
- exact pre-smoke release gate and static checks.

The uploaded artifact contains both `central_provider_free_receipt.json` and
`tb2_language_contract.json`. The receipt records:

- `provider_calls: 0`;
- `dataset_verified: true`;
- pinned Terminal-Bench commit `2fd12b88aafdd04a52c298e3940bcb189f9766d6`;
- 89 verified dataset tasks;
- 14 language witnesses with no missing languages, symbol gaps, caller gaps, or
  ambiguous samples.

## Audit findings and repairs

The first green hosted run exposed a certification coverage gap. The workflow did
not directly test or lint the new treatment renderer, treatment adapter,
repository-context module, merge script, or their tests. Local tests covered them,
but the hosted gate did not. The workflow was expanded to include every changed
Python release path, then rerun successfully as `32153210852`.

The second audit found that the dataset language-contract JSON was printed only to
transient logs. The verifier was running against the pinned dataset, but the
uploaded receipt could not prove that later. The workflow now stores and uploads
the verifier JSON. Run `32153590102` confirmed the artifact contents.

No missing P0-P2 implementation path was found after those repairs.

## What this proof establishes

It establishes implementation and integration integrity:

- current source can build the indexer;
- the pinned retrieval asset is available and hash-valid;
- the typed treatment and central runtime paths are testable;
- provenance, action accounting, runtime identity, task budgets, graph lifecycle,
  delivery audits, and merge-manifest checks are included in the hosted gate;
- no provider call was made during provider-free certification;
- benchmark source-integrity checks passed.

## What it does not establish

It does not establish solve rate, negative-flip rate, token efficiency, latency in
live task containers, or parity with GitNexus. It also does not replay the 15
historical failure workspaces because the archived artifacts do not contain legal
source workspaces. The frozen counterfactual predictions must not be reported as
replay measurements.

## Remaining work

1. Freeze the final outcome prediction artifact before seeing new outcomes.
2. Run the existing three-arm 20-task comparison: GT off, previous GT, and the
   strengthened GT.
3. Report resolve rate, positive and negative flips, steps, calls, tokens, cost,
   latency, evidence delivery/use, abstentions, and provider-censored rows.
4. Only then decide whether the strengthened architecture is actually better than
   the previous GT and whether it is competitive with the GitNexus result.

The current state is `READY_FOR_OUTCOME_EVALUATION`, not `PROVEN_BETTER`.
