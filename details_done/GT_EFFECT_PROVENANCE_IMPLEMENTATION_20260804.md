# GT Effect Provenance Implementation — 2026-08-04

## Purpose

The existing `effects_applied` counter proved state writes, not downstream
use. This change adds an additive provenance ledger so each effect can be
classified without changing GT routing, prompts, timing, action order, shadow
behavior, or submission behavior.

## Implementation

- `CentralFeatureRuntime` now records `effect_trace` rows for every applied
  effect.
- Each row has a stable effect ID, evidence/application timing, state section,
  existing state reads, actuator events, provider delivery IDs, and a terminal
  disposition.
- Confirmed model guidance is linked back to the exact contributing effect IDs.
- The existing `caller_contract` read used by signature-delta generation is
  recorded as an existing engine actuation.
- `central_receipt.json` keeps all prior fields and adds the trace under
  `features.effect_trace`.
- `scripts/central_effect_audit.py` validates terminal dispositions without
  changing runtime behavior.

## Disposition semantics

`provider_payload` requires a confirmed provider request.  
`existing_engine_actuation` requires a recorded existing consumer read.  
`audit_only` means the effect was applied but no downstream consumer was
observed; it is not counted as trajectory influence.  Unknown dispositions are
not permitted by the proof tests.

## Verification

Passed:

- `python -m pytest tests/test_gt_central_runtime.py tests/test_gt_central_consumer_proof.py tests/test_gt_central_agent.py -q`
- `python -m pytest tests/test_gt_central_consumer_proof.py -q`
- `python scripts/central_feature_census.py`
- `python -m pytest tests/test_central_effect_audit.py -q`

The provider-free census reported all existing all-17, timing, payload,
consumer, and no-action-blocked gates. Its trace contained provider payload,
existing engine actuation, and audit-only dispositions, demonstrating that the
new ledger distinguishes those cases.

The full repository suite exceeded the 120-second command limit without
returning a test failure; it must be rerun with a longer timeout before a
release claim.

No paid smoke was started by this change.
