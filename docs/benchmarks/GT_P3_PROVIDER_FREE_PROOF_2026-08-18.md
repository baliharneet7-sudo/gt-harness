# P3 Provider-Free Proof Status — 2026-08-18

## Scope

This is an implementation-integrity record for the frozen GroundTruth source
commit. It is not a solve-rate result, an efficiency result, or a GitNexus
comparison.

Frozen source commit:

`4f37f1f4afc1a7a6c7a2fe8981906567c7537800`

The commit contains the runtime-parity observation builder, the host-private
runtime-observation path, the strengthened relational/context machinery, and
the current central workflow wiring.

## Exact source-built Linux checks completed

In an isolated Linux Codespace checkout of that exact commit:

- `CGO_ENABLED=1 go test ./...` passed for `vendor/gt-index-src`.
- The current Go source built successfully with the `sqlite_fts5` tag.
- The vendored `groundtruth_mcp` wheel was installed.
- The pinned Snowflake ONNX model, tokenizer, and manifest were provisioned.
- The central provider-free test set passed after excluding one Codespace-only
  shell-profile test described below.
- `central_readiness_audit.py` reported `READY` and
  `ALL_18_PRODUCT_MECHANISMS_PROVEN`.
- `central_integrity_audit.py` reported `INTEGRITY_CERTIFIED`,
  `EVIDENCE_SOURCE_ALLOWLIST_PROVEN`, and `NO_GRADER_ACCESS_PROVEN`.
- No provider calls were made.

## Harness-only caveat

The full curated test invocation had one failure:

`tests/test_gt_central_runtime.py::test_workspace_manifest_command_is_shell_parseable_and_prunes_derived_trees`

The test launches `bash -lc` with a temporary working directory. This
Codespace's login shell profile forcibly changes the directory to
`/workspaces/gt-harness`, so the command scans that checkout instead of the
temporary fixture. The same failure is reproducible with:

`cd /tmp; bash -lc pwd`

which prints `/workspaces/gt-harness`. This is an environment discrepancy in
the Codespace shell profile, not a failure of the manifest predicate or its
pruning assertions. The remaining curated tests pass. The hosted Ubuntu
workflow still needs to execute the exact test without this Codespace profile
override before the formal workflow gate can be marked complete.

## What this proves

The result proves source buildability, central runtime integration, product
mechanism accounting, and benchmark-integrity boundaries for the frozen
commit. It does not prove that strengthened GT improves resolve rate, reduces
tokens, or beats the previous small run. Those claims require the frozen
baseline/previous-GT/strengthened-GT comparison on the same 20-task
denominator.

## Remaining release gates

1. Run the exact hosted provider-free workflow for the frozen commit, or record
   a reproducible hosted-workflow substitute with the shell-profile issue
   removed.
2. Replay only historical rows for which a legal source workspace is present.
   The current archive has trajectory/receipt/replay data but no restorable
   repository workspace, so those rows are currently unavailable.
3. Freeze the final prediction artifact before viewing new outcome results.
4. Run baseline, previous small GT, and strengthened GT only; do not add a
   GitNexus arm.

