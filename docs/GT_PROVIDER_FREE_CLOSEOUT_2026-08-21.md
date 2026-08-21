# GT provider-free closeout note — 2026-08-21

## Goal

This note is a documentation closeout for the latest mechanical proof run and the
remaining release gap required for benchmark authorization.

## Proven candidate proof

- workflow: [32526386608](https://github.com/harneet2512/gt-harness/actions/runs/32526386608)
- runtime SHA: `77db941152d0d33929348590c7ce9528b3be64d6`
- run status: PASS
- commit proof lines observed in receipt:
  - `provider_calls: 0`
  - `provider_credentials_present: false`
  - `READY`
  - `SMOKE_APPROVED`
  - `GT_MECHANICAL_COMPLETENESS=PASS`
- uploaded artifacts:
  - `central_provider_free_receipt.json` SHA
    `209fe2445362e149a5d09860ff14b1139839407b64a70cdd5d937bb0cb3cff55`
  - `mechanical-completeness.json` SHA
    `0628d9b3af03b980ac40a30987b56be508ff3f3a08cb1a728a0568cb10ff26d8`

## What this proof does certify

- source-built Linux indexer path in CI
- pinned Snowflake ONNX workflow contract
- zero-provider implementation run path
- mechanical completeness checks and documentation-consistency checks
- no-grader-source contract checks exercised in the no-spend flow

## What is still required for benchmark release authorization

1. The active release manifest must use the same exact runtime SHA as this proven
   proof, or this exact runtime SHA must be rerun in provider-free CI again as the
   manifest runtime.
2. Full integrity/no-spend suite must be rerun against that same frozen
   release SHA.
3. Paid benchmark authorization requires one exact 20-task GT-on run only,
   with separate integrity/solve/efficiency/intervention reports.

## Open evidence risks (high confidence)

- source→non-source and delete transitions when the workspace sensor drops oversized
  source bytes but the mirror has prior indexable content
- terminal observed-fact proof allowing unhelpful self-authored/private decisions to
  complete proof rows
- provider censor classification based on message pattern without exception-type gating

These are integrity risks for causal attribution, not blockers for mechanical
completeness in the current proof.

## Source references

- [GT release status authority](./GT_RELEASE_DOSSIER.md)
- [GT complete implementation record](./GT_COMPLETE_IMPLEMENTATION_RECORD_2026-08-21.md)
- [GT final handoff remaining work](./GT_FINAL_HANDOFF_REMAINING_WORK_2026-08-21.md)
- [active release manifest](../eval/release/active_release.json)
