# GroundTruth Complete Implementation Record

Date: 2026-08-21  
Repository: `harneet2512/gt-harness`  
Active branch: `baseline-swe-live-lite-v4flash0731`

## Purpose

This document records what was implemented, what was verified, which runs are
valid evidence, and which results must not be treated as product claims.

## Product boundary

GroundTruth is a host-owned engine around the Mini-SWE model loop. It gathers
bounded, source-grounded repository and execution evidence, maintains
revision-bound state, and delivers selected evidence in the exact provider
request before the next model decision. It does not read grader-only artifacts,
rewrite model commands, change the verifier, or alter the benchmark denominator.

The integrated product census is 17 historical mechanisms plus persistent
execution state: 18 configured mechanisms in total. A feature firing in a
particular task is not the same as the product mechanism being configured.

## Implemented product components

### Repository and retrieval

- bounded workspace/source mirroring;
- source and graph revision separation;
- Go indexer built from vendored source on Linux;
- graph-first persistent execution state;
- exact, lexical, BM25, local dense, and certified structural retrieval;
- pinned Snowflake Arctic ONNX embedding asset with content hash;
- graph definitions, signatures, directed calls, reverse impact, tests,
  routes, re-exports, inheritance and override composition where certified;
- ambiguity, unresolved, external, stale, and incomplete relations abstain;
- incremental graph refresh after source changes;
- source/graph identity and publication-lock certification.

### Runtime and delivery

- one bounded bootstrap call when a task becomes graph-applicable;
- deterministic persistent state reads and transitions;
- typed preflight/postflight lifecycle;
- one immutable validation classifier;
- context compiler with shared token budget;
- task-semantic substrate independent of graph applicability;
- provider-view and request hashes;
- first-eligible, non-predictive delivery timing;
- provider-value certificates with authority, anchors, source revision,
  novelty basis, decision point, and replaced-operation fields;
- replay bundle and intervention-chain receipts;
- release gates for mechanism census, state lifecycle, retrieval, delivery,
  graph freshness, prediction identity, and task artifact integrity;
- assistive convergence limited to certified artifact-targeting or deterministic
  stalled/contradicted/budget-risk searches.

## Commits and changes

### `42d1fd5`

Repaired configured provider/model identity and readiness-gate behavior.

### `b287929`

Refroze release prediction on the then-current repaired runtime.

### `7d06957`

Fixed provider-delivery receipt construction. Repository-context projections
contain both selected and budget-rejected candidate contributions; receipts now
publish only selected contributions. This prevents a budgeted claim from being
advertised as delivered without a matching provider-value certificate.

### `b383a9a`

Added the product audit and frozen-20 workflow guard. The guard requires the
explicit `repair20-v1` task order whenever a 20-task release is requested.

### `df247ce`

Created prediction version V23 and updated the active release manifest to bind
the prediction and proof commits to the repaired runtime. This was required
because the prediction freeze correctly rejects runtime changes after a prior
prediction was created.

## Verification evidence

Local verification after the delivery fix:

- `tests/test_gt_delivery_audit.py`: 36 passed;
- `tests/test_central_release_gate.py`: 56 passed;
- `tests/test_gt_central_agent.py`: 153 passed, 1 expected skip because the
  local Snowflake ONNX asset was not provisioned;
- Python compilation of `gt_engine`, `eval`, and `scripts`: passed;
- `scripts/central_readiness_audit.py`: `READY`, all 18 mechanisms proven;
- `scripts/central_integrity_audit.py`: legal-source allowlist and no-grader
  access proven.

The FEAL receipt from run `32449596981` was replayed with the corrected
selected-claim shape and produced zero delivery-audit failures.

## Run history relevant to the final state

### Run `32449596981`

Correct frozen GT-on 20-task run on the older `b287929` runtime:

- 20 tasks completed and graded;
- 15 solved;
- FEAL reward was solved but release was rejected by the provider-value
  certificate defect fixed in `7d06957`;
- five task-level losses remained: extract, regex, torch tensor, video, and
  winning Corewars.

### Run `32454018052`

Invalid dispatch. A short SHA was supplied to checkout, so resolve failed
before provider-free validation and before any task jobs or provider calls.

### Run `32454667785`

Valid full-SHA dispatch on `b383a9a`, but provider-free correctly failed because
the frozen outcome prediction still named the older runtime commit. No task
jobs or provider calls were started.

### Run `32455040841`

The final corrected dispatch on `df247ce`:

- resolve passed;
- provider-free passed;
- release identity passed;
- frozen plan passed;
- all 20 task jobs completed;
- merge/release failed closed.

Final merged result:

- 20 task trials returned;
- 17 graded normally;
- 3 returned `InternalServerError` from the verifier/provider path;
- 12/17 graded tasks solved;
- 12/20 solved over the full denominator;
- no promotion claim is valid.

The merged artifact reports:

- repository-intelligence invalid: `count-dataset-tokens`;
- treatment-release invalid: count, FEAL, regex, and schemelike;
- verifier errors: FEAL, regex, schemelike;
- baseline-only losses: sanitize-git-repo, torch-tensor-parallelism,
  video-processing;
- positive flip: largest-eigenval.

The three `InternalServerError` rows are not ordinary solved/unsolved outcomes
and must not be used as evidence that GT solved or broke those tasks.

## Current conclusion

The core lifecycle and delivery machinery is substantially more observable and
fail-closed than the historical implementation. The product is not yet
benchmark-ready because one graph-refresh failure and three verifier-error /
censor-accounting cases remain unresolved, and the release gate correctly
rejects the run rather than silently promoting partial evidence.

