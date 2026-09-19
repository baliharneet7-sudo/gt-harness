# `.github/workflows-archive/` — retired workflow definitions

Everything in this directory is a **retired** GitHub Actions workflow. It is
kept as source-of-record text, not as something that runs.

## What "archived" means, precisely

GitHub Actions only registers workflows that live in `.github/workflows/`.
A file under `.github/workflows-archive/` therefore:

- **cannot be dispatched** — it does not appear in the Actions tab, and
  `gh workflow run <name>` cannot resolve it;
- **cannot be triggered** — a `schedule:`, `push:` or `pull_request:` block
  inside an archived file is inert text, not a trigger;
- **cannot be called** — `uses: ./.github/workflows/<name>` from a live
  workflow will not resolve to a file in this directory;
- **cannot spend** — an archived lane holds no secret and starts no runner,
  so no archived file can consume provider budget or CI minutes.

Moving a workflow here is the *only* supported way to retire it. Deleting it
would lose the recipe that produced historical receipts; leaving it in
`.github/workflows/` would keep it dispatchable by anyone with write access,
which is exactly the supply-chain surface the supported-set gate in
`tests/test_product_workflow.py::test_only_closed_supported_workflow_set_is_active`
exists to keep closed.

## Why these files were retired

- **Unattended lanes.** `tokenrouter_tb2_monitor.yml` was the repository's only
  `schedule:` workflow: it ran on a cron with a provider secret in scope and no
  operator watching the run. A lane that can spend without a human present is
  retired, not reviewed.
- **GT-off baselines.** `tb2_baseline.yml`, `tb2_baseline_sharded.yml`,
  `tb2_miniswe_baseline.yml`, `tb2_miniswe_baseline_matrix.yml`,
  `tb2_miniswe_baseline_sharded.yml` and `deepswe_gtoff_baseline.yml` produced
  GT-off numbers. Those baselines are frozen and are fetched, never re-run, so
  a live lane that can re-derive them is a way to *replace* the frozen baseline
  by accident.
- **Superseded arms.** `swe_gt.yml`, `tb2_gt.yml`, `tb2_miniswe_gt_single.yml`,
  `gt_v4flash_30.yml`, `arb_gt_retrieval.yml`, `decision_point_control.yml`,
  `bootstrap_canary.yml`, `engine_provider_free.yml` and
  `gt_finalstand_provider_free.yml` were folded into the central lanes
  (`tb2_miniswe_central.yml`, `deepswe_miniswe_central.yml`,
  `central_provider_free.yml`) or into the product acceptance workflow.
- **Superseded SWE-bench Live cluster.** `live_lite_full.yml`,
  `live_lite_bundle.yml`, `live_lite_inference.yml`, `live_lite_eval.yml` and
  `live_lite_cache_images.yml` were replaced by
  `swebench_live_lite_full.yml`.

## Notes for readers of these files

- Cross-references inside archived files (`uses: ./.github/workflows/...`,
  prose comments naming sibling lanes) were **not** rewritten. They describe
  the layout at the time the workflow was retired and are deliberately left
  as-is so the historical text stays byte-faithful.
- `gt_finalstand_provider_free.yml` also exists at
  `docs/historical-workflows/gt_finalstand_provider_free.yml`. That copy — not
  this one — is the one `scripts/validate_gt_finalstand.py` and
  `scripts/finalstand_offline.py` hash when they verify the FS-023 attestation
  bundle. Do not assume the two are interchangeable.

## Restoring one

Move it back with `git mv` **and** add its name to the expected list in
`tests/test_product_workflow.py::test_only_closed_supported_workflow_set_is_active`,
with a comment saying why it is admitted. The test fails closed: a workflow
that reappears in `.github/workflows/` without that justification reds the
suite, which is the intended behaviour.
