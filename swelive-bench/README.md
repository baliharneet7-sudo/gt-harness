# SWE-bench-Live Lite (GT-on)

This directory holds the suite manifest and the reviewed task packages for
`.github/workflows/swelive_gt_harness_paid.yaml` (registered directly on one
account, and through the thin wrapper `swebench_live_lite_full.yml` on the
others). The workflow runs the Mini-SWE 2.4.6 Pier adapter with GroundTruth
on, using the model, OpenRouter routing and GT delivery mode (`attached` by
default, or `push`) chosen at launch. No GT-off arm exists or may be run;
outcomes are reported absolute.

## Catalog

The cohort is the full Lite split of the Hugging Face dataset
`SWE-bench-Live/SWE-bench-Live` (split `lite`, 300 instances), pinned in
`config/swelive_lite_catalog_v1.json`:

- every instance, in the row order of the checked-in snapshot
  `benchmarks/data/swebench_live_lite.jsonl` (verified field-for-field
  against the Hugging Face split at the recorded revision);
- its evaluation image `starryzhang/sweb.eval.x86_64.<id>` (the official
  evaluator's naming: id lower-cased, `__` -> `_1776_`), pinned by registry
  digest, resolved with anonymous registry HEAD requests (nothing pulled);
- the sha256 of the Pier `task.toml` rendered for it;
- `excluded`: any instance whose image could not be resolved, with the reason.

`manifest.json` is derived from the catalog (the runnable rows) and binds its
digest; `scripts/benchmark_suites.py` binds the manifest. The planner pins the
catalog digest literally, so a rebuilt catalog must be reviewed into the
workflow before it can run.

`scripts/build_swelive_catalog.py`:

- `resolve --hf-revision <sha> [--hf-parquet lite.parquet]` rebuilds the
  catalog and manifest (network; token-cached, 429-backoff);
- `verify` re-renders every task offline and checks catalog, snapshot digest
  and manifest binding;
- `materialize --tasks all|<ids>` writes task packages, refusing any whose
  `task.toml` digest differs from the catalog (the plan materializes all, each
  task job its own);
- `confirm-images --plan <plan>` HEADs every planned manifest by digest.

Runs never read the committed `tasks/` directory: every package a run uses is
rendered from the snapshot into the git-ignored `rendered/` tree by the one
renderer and must hash to the catalog. `tasks/` keeps the five reviewed
`smoke5` packages (which the renderer reproduces byte-for-byte, checked by
tests) and `cyclotruc__gitingest-94`, a hand-curated package predating the
renderer that backs `tests/test_swelive_corpus.py`.

## Cohorts and shards

`cohort_stage`: `gate-one` (the first catalog task), `remaining` (all but the
gate, bound to a passed gate-one attestation), `all`, `smoke5`, `single`,
`subset`. The selected cohort is split into `shard_count` strided shards and
`shard_index` picks one; a dispatch may not exceed GitHub's 256-job matrix
limit, so `all` and `remaining` need `shard_count >= 2`.

## Grading

Every completed task is graded twice: through Pier's task verifier, then
independently with Microsoft's official SWE-bench-Live `python-only` evaluator
pinned at `ad79b850f15e33992e96f03f6e97f05ddf9aa0be`; the job fails if two real
rewards disagree. Each task's progress receipt records the GT delivery the
agent actually received (`scripts/annotate_gt_delivery.py`), and the run
summary counts treatment-invalid tasks separately.
