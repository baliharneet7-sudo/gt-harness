# DeepSWE blocker repair — 2026-08-11

## Scope

This repair addresses only defects reproduced in the DeepSWE ten-task smoke
(`31550154123`). That smoke used `openrouter/xiaomi/mimo-v2.5-pro`; it is not
the intended DeepSeek V4 measurement. The active task workflow now defaults to
the established bare `deepseek-v4-flash` model ID. It remains pinned to the
DeepSWE `v1.0.0` task checkout; the public website's v1.1 artifacts are
leaderboard/catalog metadata and are not used as task inputs.

## Reproduced defects and fixes

### 1. Large-workspace manifest falsely degraded the source mirror

The manifest command used `find | sort | head -n 50001` under `set -o
pipefail`. `head` closed the pipe after the bound, so `find` could terminate
with status 141. The sensor treated that non-zero status as an unhealthy
snapshot. This caused `arktype-json-schema-refs-dependencies` to start without
a usable mirror and invalidated the later refresh for
`fd-deterministic-multi-key-sorting`.

The command now uses `awk 'NR <= 50001'`. `awk` still bounds the emitted rows
but consumes the complete sorted stream, so `find` is not killed by SIGPIPE.

### 2. Bounded source text falsely invalidated a usable graph

The hybrid repository builder recorded `chunk_character_limit` whenever a
graph span exceeded the bounded retrieval-text budget. It then set
`complete=False` for every reason, causing the agent to refuse construction of
the hybrid retriever even when the graph, source revision, and file were
valid. The DeepSWE smoke consequently showed graph-passed tasks with zero
retrieval candidates.

`chunk_character_limit` is now a non-fatal corpus-bound reason. The returned
document remains explicitly marked with `bounded_source_span` provenance and
is still bounded. All substrate failures (missing/invalid graph, source
read failure, unsafe path, incomplete links, etc.) remain fail-closed.

### 3. Initial graph indexing was aborted at 15 seconds

`MiniSweCentralAgent._start_repository_session` wrapped the initial refresh in
`asyncio.wait_for(..., timeout=15)`. The smoke measured initial indexing at
approximately 15.6s and 16.2s for two otherwise valid repositories, so the
host wrapper—not the indexer—aborted them.

The timeout is now a constructor setting,
`repository_initial_index_timeout_sec`, defaulting to 60 seconds and clamped
to at least one second. The DeepSWE workflow sets the same value explicitly
(`--ak repository_initial_index_timeout_sec=60`) and the value is written to
the component configuration receipt.

## Verification

Focused RED-to-GREEN checks:

```text
python -m pytest tests/test_gt_central_runtime.py::test_large_manifest_bound_does_not_turn_sort_limit_into_sigpipe_failure tests/test_hybrid_repository.py tests/test_hybrid_retrieval.py tests/test_gt_central_agent.py::test_deepswe_workflow_sets_a_nontrivial_initial_index_timeout -q
40 passed
```

Static checks:

```text
ruff check <all changed Python files>       PASS
python -m py_compile <all changed files>    PASS
git diff --check                            PASS
```

The broader GT subsystem suite passed all non-census tests. Three census
assertions remain red locally because the checked-in Windows binary does not
contain the registered `objective_c` parser. The provider-free workflow builds
`vendor/gt-index-src` from source on its runner; this local binary mismatch is
intentionally not hidden by changing the census gate.

The source-built verification then passed on the repaired commit:

```text
workflow: 31554230078
commit:   7bd17564d3c3832a7bb29275b7bde07e041c1475
result:   success
```

Its log proves the parser-complete repository substrate, `READY`, all 17
producer/consumer/timing/accounting census gates, strict lifecycle tests,
`SMOKE_APPROVED`, and static checks. The receipt and log are retained at
`artifacts/deepswe_provider_free_31554230078/` and
`artifacts/deepswe_provider_free_31554230078.log`.

## DeepSWE data captured locally

Fetched with `curl.exe` from `https://deepswe.datacurve.ai/`:

```text
artifacts/deepswe_leaderboard/index.html
artifacts/deepswe_leaderboard/leaderboard-live-v1.1.json
artifacts/deepswe_leaderboard/data-v1.1.html
artifacts/deepswe_leaderboard/tasks-v1.1.html
artifacts/deepswe_leaderboard/trials-v1.1.html
artifacts/deepswe_leaderboard/tasks-v1.1.json
artifacts/deepswe_leaderboard/local-smoke-task-comparison.json
artifacts/deepswe_leaderboard/local-smoke-task-comparison.csv
```

The v1.1 artifact reports 113 tasks, 91 repositories, five languages, and a
generation timestamp of 2026-08-07. The ten-task local smoke maps to ten
catalog tasks across Go (2), Python (2), TypeScript (2), Rust (2), and
JavaScript (2). Its treatment reward was 0/10; this is diagnostic evidence and
is not a leaderboard comparison. The public v1.1 artifact's DeepSeek V4 Flash
reference row is `mini-swe-agent`, max effort, 241/452 passed attempts,
pass@1 `0.5331858407`, pass@4 `0.8053097345`, across 113 tasks and four runs.
That is an external aggregate reference, not a GT-on row for this smoke.

The repository-wide workflow audit found no `v1.1` DeepSWE task reference.
The only active DeepSWE workflow is pinned to `v1.0.0` in both checkout steps
and verifies commit `c33fa70e68d11d85f9e58abcd5d78643705e916e`. Unrelated
Terminal-Bench release comments mentioning `v1.1.0` are not DeepSWE task
inputs and were not changed.

## Remaining gate

No new paid smoke was launched by this repair. The source-built provider-free
gate is now green; the remaining step is an explicitly authorized repaired
ten-task DeepSWE smoke, followed by the existing receipt/outcome audit.
