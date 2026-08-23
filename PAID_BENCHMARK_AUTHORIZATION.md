# Paid Benchmark Authorization

Verdict: `NOT_AUTHORIZED`

Audited experimental release: `2140693bc038449cfdf02b49fb03e34eae50ac29`

Observed: `2026-08-23`

The authorized GT-only 20-task smoke has been consumed. No additional paid run is authorized.

Blocking evidence from run `32635379908`:

- only 6/20 run receipts completed cleanly;
- seven outer timeouts left checkpoint receipts in `RUNNING` state;
- seven trials produced explicit run errors;
- interrupted receipts did not contain the complete initial delivered GT packet;
- a terminal-rendering crash was fixed only after the experimental release;
- no paired Bare/GT/GitNexus methodology has been executed.

Authorization can be reconsidered only after provider-free tests prove a shutdown grace period that always finalizes timeout receipts, complete packet text is durable from the first checkpoint, the post-experiment Rich fix is in a newly certified release, and a provider-free rehearsal proves binding/upload for completed, errored and externally killed trials. A new paid run requires explicit user authorization.
