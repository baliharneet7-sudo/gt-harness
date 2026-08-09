# Counterfactual replay capture implementation

The trajectory audit can certify deterministic GT delivery, but it cannot
prove model causality from hashes and anchor-following. This change adds an
opt-in capture seam for the next authorized experiment.

## Capture contract

`gt_engine.replay_bundle.ReplayBundleWriter` writes
`gt_replay_bundle.json` beside the normal receipt only when
`enable_replay_capture=true`. It records, per model call:

* exact provider-prepared messages and both existing request hashes;
* model name, redacted model parameters, temperature, and optional provider
  seed;
* source/workspace revisions and the typed controller state frame;
* projected assistant response/actions and response hash;
* explicit omission/error receipts when size or runtime limits prevent capture.

Capture is bounded by per-call and total-byte limits. Truncation makes the
bundle incomplete; it never claims replay readiness. Secrets in model kwargs
are redacted. Capture does not alter the provider request or model loop.

## Replay-readiness boundary

`counterfactual_replay_ready` is true only when every request and response was
captured without omission and every call has a deterministic sampling seed.
The default is disabled, and current paid workflows remain unchanged. A
bundle with requests/responses but no seed is useful for trajectory inspection
but remains insufficient for a model counterfactual.

## Verification

Provider-free tests cover disabled capture, exact request capture, missing
seed, bounded omission, and agent receipt wiring. The central provider-free
workflow includes those tests and the static check. No paid smoke was started.

## Next authorized experiment

Enable capture on a dedicated matched ten-task run only after reviewing bundle
size and provider policy. Then replay each delivery with the same request,
checkpoint, and sampling state while holding that delivery out. Classify the
result as necessary, decision-relevant, redundant, or unidentifiable. Do not
call the 89-task run or claim causal efficiency until this gate passes.
