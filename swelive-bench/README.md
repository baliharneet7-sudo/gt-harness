# SWE-bench-Live Lite smoke package

This directory freezes the five-task preflight cohort used by
`.github/workflows/swelive_gt_harness_paid.yaml`. The workflow runs the
Mini-SWE 2.4.6 Pier adapter with `stealth/union-alpha` and the GT product
imported from `921bec20d3dbabd12e4b442936d9259c24cdcc74`.

The cohort is the first five rows, in source order, of
`benchmarks/data/swebench_live_lite.jsonl`:

1. `aiogram__aiogram-1594`
2. `amoffat__sh-744`
3. `arviz-devs__arviz-2413`
4. `aws-cloudformation__cfn-lint-3749`
5. `aws-cloudformation__cfn-lint-3764`

`manifest.json` binds each task to its base commit, canonical task-config
hash, Docker Hub image name, and immutable image digest. Each task package
contains the source problem statement, hidden test patch, official test lists,
and a Pier-compatible verifier. `scripts/build_swelive_smoke_tasks.py`
reconstructs the package from the checked-in dataset snapshot.

The paid workflow performs all gates before a model request: imported GT object
verification, workflow and integration tests, task/config hashes, all five
image manifests, the OpenRouter route and exact model, and an official
SWE-bench evaluator canary. It pulls each task image once in its task job and
reuses that image for Mini-SWE and final grading.

Every completed task is graded twice: first through Pier's task verifier, then
independently with Microsoft's official SWE-bench-Live `python-only` evaluator
pinned at `ad79b850f15e33992e96f03f6e97f05ddf9aa0be`. The job fails if the two
rewards disagree.
The saved artifacts include the plan, trajectory, patch, Pier verifier receipt,
official evaluator report, per-task metrics, diagnostics, and final attestation.

Run `gate-one` first. Run `remaining` with the successful gate run ID only after
the gate task has an official grade. The remaining four tasks may execute in
parallel; the workflow supports up to 20 parallel task jobs for the later full
cohort.
