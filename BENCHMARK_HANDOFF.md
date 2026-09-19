# Benchmark handoff

This file is the persistent operating record for the GT benchmark campaign. A
new session should read it before dispatching anything. It is deliberately
free of API keys, account emails, project IDs, and other credentials.

## Fixed experiment contract

- Model (current, 2026-09-19): `deepseek/deepseek-v4-flash-0731`, provider
  `deepinfra` only, **fp8**, $0.06/M input and $0.18/M output. Single source
  of truth `config/benchmark_model.v1.json`; route manifest
  `config/provider_route_deepseek_v4_flash_0731_fp8.v1.json`. The `relace`
  route that preceded it served fp4 - a quantization confound against the
  fp8 GT-off baseline - and the preflight now refuses any served build
  whose quantization is not fp8. The paragraph below is the earlier muse
  contract, kept as history.
- Model (history): `meta/muse-spark-1.2-contributor` through OpenRouter
  (`https://openrouter.ai/api/v1`), provider-pinned to the `meta` tag,
  $0.10/M input and $0.20/M output on a 1,048,576-token context.
  **1.2 specifically, not 1.3**: `miniswe_gt_run._model_and_kwargs` applies
  `reasoning={"effort":"xhigh"}` on an exact match of this string, and its
  comment states that leaving the field implicit "makes GT-on vs baseline
  outcome comparisons invalid even when the visible model identifier is
  identical". `eval/muse_spark_1_2_smoke20_baseline.json` is the retained
  DeepSWE v1.1 baseline for that exact configuration
  (`mini_swe_agent_muse_spark_1_2_xhigh`, HAR-82).
- Model history this campaign. `stealth/union-alpha` is **retired** -
  OpenRouter ended the Stealth Union Alpha preview on 2026-09-17 and lists no
  `stealth/*` models at all; run `35283782651` died at agent turn 2 with
  `litellm.NotFoundError` carrying the provider's own notice. It became
  `unbiased/pareto`, which was pinned and proven working
  (run `35288104554`, `officially_graded: 1`) before being replaced on cost:
  $2.50/M and $7.50/M put a 20-task TB2 cohort near $230 against roughly $9
  on the contributor tier. Both remain as additive allowlist history; neither
  is on the dispatch path.
- Repinning a model touches SEVEN consumers, not one. In order:
  `scripts/provider_preflight.py` `_AUTHORIZED_ROUTES`,
  `scripts/miniswe_gt_run.py` `_PROVIDER_ROUTING_BY_MODEL` (plus any
  model-specific kwargs), `config/provider_route_*.v1.json`,
  `tb2_miniswe_central.yml` (MODEL, run-name, three effective_model strings,
  the model assertion AND the provider_routing assertion),
  `swebench_live_lite_full.yml`, `swelive_gt_harness_paid.yaml`,
  `scripts/attest_deepswe.py`'s suite-to-route map, and the frozen envelope
  tests `test_tb2_gt_smoke_workflow.py` / `test_swelive_gt_smoke_workflow.py`
  / `test_benchmark_suites.py` (`REQUESTED`/`EFFECTIVE`). Missing any one of
  them fails a gate before spend - three dispatches bounced that way on
  2026-09-17. Run the twelve suites listed in
  `deepswe_gt_harness_product.yml` locally first.
- Comparability warning: `unbiased/pareto` has NO GT-off baseline. The three
  TB2 GT-off baselines are (A) `D:\gt_runsull89_2026-07-29` nano-harness
  45/88, self-labelled an orientation baseline and not a paired reference;
  (B) `D:\gt_runs\miniswe_tb2_gtoff_20260731` mini-swe-agent 2.2.8, **66/89**,
  the frozen paired reference; (C) `D:\gt_runs	b2_gtoff_oxalpha_20260821`
  stealth/ox-alpha 48/82. A and B are `deepseek-v4-flash`. Pareto results are a
  standalone arm plus harness validation, not baseline-comparable.
  `scripts/provider_preflight.py` records that `deepseek-v4-flash-0731/relace`
  is the only route whose results may be cited against the frozen baselines.
- GT source: `921bec20d3dbabd12e4b442936d9259c24cdcc74`.
- The object IDs in `config/tb2_gt_import_manifest.json` must remain unchanged.
- Official SWE-Live grader: Microsoft SWE-bench-Live verifier.
- Official TB2 grader: Harbor Terminal-Bench 2.0 verifier.
- SWE-Live uses the Mini-SWE 2.4.6 Pier adapter and `eval.pier_gt_harness_adapter:PierGtHarnessMiniSwe246Agent`.
- TB2 uses the Mini-SWE central agent workflow, never OpenHands.
- Concurrency target is 20. GitHub may schedule fewer jobs temporarily; inspect the live job count.
- Save every trajectory, provider receipt, product receipt, verifier result, diagnostic summary, and task patch.

## Required update format

For each benchmark, report exactly:

`Model: deepseek/deepseek-v4-flash-0731 | Tasks completed: N | Tasks left: N | Tasks success: N | Tasks failed (incorrect): N | Tasks failed (infrastructure): N`

Only an official verifier result counts as completed. An incorrect patch is a
graded failure. Missing setup, image, provider, parser, verifier, or artifact
receipts are infrastructure failures. If infrastructure failures exceed five,
stop the run series, preserve all artifacts, fix the cause, and restart with a
new series identifier.

## Current state

### SWE-Live

- Gate run `35252797829`: PASS. Task `aiogram__aiogram-1594` was officially graded reward 0 (incorrect), with no infrastructure failure.
- Gate diagnostic: exit 0; every required capability WORKING; LSP published 460 edges; official and independent verifiers agreed.
- Gate product metrics: 17 provider calls, 172,510 input tokens, 87,092 cached tokens, 25,521 output tokens.
- Remaining release run: `35256147148`, gated by `35252797829`, currently active at last update.
- Existing clean-series infrastructure count is 1 from the earlier strict-diagnostic failure; the gate itself is no longer an infrastructure failure.

### TB2

- Attempts `35256152140`, `35257234010`, `35257606223`, `35257941589`, and `35258327432` failed in `plan` before task dispatch. The first referenced test files absent from the checked-out tree; the second selected a test tied to a different producer digest and historical commits; the third invoked an absent `scripts/central_feature_census.py` after all selected tests passed; the fourth used only `OPENAI_API_KEY`; the fifth populated the secret fallback but still omitted LiteLLM's required `OPENROUTER_API_KEY`, producing a 401. Attempt `35258719496` reached task jobs but failed six tasks during setup because the run job lacked the Snowflake model/tokenizer hash environment. No TB2 task was officially graded.
- TB2 now sets both `OPENAI_API_KEY` and `OPENROUTER_API_KEY` from `secrets.OPENROUTER_NEW` in its plan and task environments, matching the proven SWE-Live route.
- The TB2 infrastructure count exceeded five in this first series, so that series is closed. The Snowflake hashes are now bound in both plan and task jobs. The next dispatch starts a fresh TB2 series with infrastructure count 0.
- The planner list is now limited to source-compatible central-agent, progress, provider-preflight, budget, and outcome tests in `.github/workflows/tb2_miniswe_engine.yml`. Push this fix to both benchmark accounts before retrying TB2.
- Retry (superseded 2026-09-19): the model is now `deepseek/deepseek-v4-flash-0731`
  on `deepinfra` fp8, and the first paid dispatch is a 2-3 task `cohort_stage:
  subset`, not p20 - see the dispatch runbook in
  `docs/benchmarks/gt_hardening_rsi_2026-09-18.md` section 8.

### TB2 root cause, corrected 2026-09-17

The five plan failures and the Snowflake failure above were real but they were
symptoms in front of a wall. `tb2_miniswe_engine.yml:367` pins
`AGENT="eval.gt_central_agent:MiniSweCentralAgent"`, and that module does not
exist on `codex/gt-921bec20-union-smokes`: commit `97efb7f0`, the one that
integrated GT 921bec20, deleted it (9,094 lines). Run `35259343723` therefore
lost 20/20 tasks to `No module named 'eval.gt_central_agent'`. The module is
not lost - it is 226,811 bytes on `harneet2512@inline-engine`, which is that
workflow's own documented default `ref`. The dispatches overrode `ref` to the
pinned-source branch, the one branch guaranteed not to carry it.

Do not "fix" this by restoring the file. Two different experiments exist:

- `tb2_miniswe_central.yml` uses `eval.pier_gt_harness_adapter:PierGtHarnessMiniSwe246Agent`,
  the same adapter SWE-Live uses, and it works. This is the proven path.
- `tb2_miniswe_engine.yml` needs `ref=inline-engine`, which abandons the
  921bec20 pin. Treat it as a separately pinned experiment.

`deepswe_miniswe_central.yml:822` has the same defect via
`eval.pier_gt_adapter`, which exists on no branch at all (only at `97efb7f0^`).
It will fail on first dispatch.

### Run conclusion is not a valid signal

Harbor exits 0 on an errored trial, so GitHub reports the run green while the
receipt records `infrastructure_failed`. Count only
`gt.benchmark_progress.v1`: `officially_graded`, `passed`,
`infrastructure_failed`. Run `35262214538` is the worked example - green run,
zero graded tasks.

### Defects found by the 2026-09-17 smokes

1. FIXED (`8bf0a107`). `_classify_terminal` matched the bare substring
   `"status"` against the exception message. A TB2 task workspace has no git
   baseline, so patch export raised `CalledProcessError` ending "returned
   non-zero exit status 128", and a git failure was graded `provider_failed`,
   exit 4, harbor errored the trial. Message matching itself is deliberate and
   is pinned by `test_provider_errors_map_to_provider_failed`; only the
   `"status"` token was removed.
2. FIXED (`8bf0a107`). A failed patch export was promoted to the run's
   terminating exception whenever the agent had not raised, overwriting an
   outcome the solver had earned. `extract-elf` returned
   `exit_status: LimitsExceeded` - `budget_exhausted`, which exits 0 precisely
   because the workspace stays gradable. Promotion is kept for runs that claim
   a submission and dropped for non-submitted terminals.
3. OPEN, needs a decision. `scripts/miniswe_gt_run.py:427` raises
   `command_descendant_receipt_missing` when a worker leaves no containment
   receipt. On `amoffat__sh-744` this killed a run whose work was already
   committed: `committed_patch_bytes: 4660`, `committed_patch_empty: false`,
   `repository_head_moved: true`, and the harness had recorded
   `collected_patch_will_be_empty: false`. Exit 5 errored the trial, so
   task.toml's verifier-collect stage - the only producer of
   `/logs/artifacts/model.patch` - never ran, and an empty patch was graded 0.
   2 of 4 SWE-Live tasks died this way. Neither fix above touches it.
4. OPEN, not ours. `cfn-lint-3764`'s own gold patch does not resolve in its
   pinned image; the pre-spend canary correctly refused at zero model spend.
   The canary discards the per-instance `test_output.txt`, so the failing test
   is unknown - keep those logs.
5. OPEN. `total_cost` reads 0.0 against 22,847,464 input tokens. Tokens are
   metered in the GT receipt but do not reach the Pier/Harbor receipt, which
   reports null.
6. OPEN. The model returns no-tool-call responses at a steady ~10%
   (SWE-Live 34/354, TB2 11/102), surfaced as `FormatError` and labelled
   `GT_PROVIDER_MALFORMED_RESPONSE`. That code is the fallback branch of
   `_classify`, NOT evidence of a transport fault: transport was healthy
   (`provider_request_count == provider_response_count`). Every one burns an
   agent turn against `STEP_LIMIT: 100`.
7. OPEN. TB2 task cgroups are memory-pressured:
   `GT_INDEX_MEMORY_HEADROOM_INSUFFICIENT` refused 9 graph refreshes
   (`limit=0..12804096` vs `need=178438144`), leaving `lsp_promotion`
   non-WORKING and `verified_claims_prohibited`. The GT arm is measured
   degraded until the task container gets more memory.

### GT mode is already pinned

`eval/miniswe_agent.py:565` builds the supervisor command with
`--gt-mode advisory`, inherited by `PierGtHarnessMiniSwe246Agent` through
`super()._run_command`. Both benchmarks use that one adapter, so `advisory` is
a deliberate pin, not a default. The workflows pass no `--gt-mode`; do not add
one without deciding to change the arm.

### Account topology

Runs live in `baliharneet7-sudo/gt-harness`. Three accounts are authenticated
in the gh keyring; use `GH_TOKEN=$(gh auth token --user <acct>)` per command
rather than `gh auth switch`, which is global and races. Only the owning
account has push/admin. TB2 images resolve as
`ghcr.io/<repo_owner>/tb2.<task>:<tag>` with NO Docker Hub fallback, so a
fresh account must run `tb2_cache_images.yml` first; this was done for
`baliharneet7-sudo` on 2026-09-17 (run `35262200448`, 13/13) and verified by
`35280614124`.

Stuck runs whose `plan` failed leave a non-terminating progress job and stay
`in_progress` forever, leaking concurrency. Plain cancel does not clear them;
`POST .../force-cancel` does.

## Offline hardening, 2026-09-18 (HAR-88)

Nine rounds of fix -> full suite -> adversarial Opus review, all offline (no
provider call, no dispatch, no Docker). Review 9 approved with nothing above
LOW. The complete record - every fix, the severity trend, the twelve
pre-existing test failures, the LOW residuals, the open decisions and the
dispatch plan - is `docs/benchmarks/gt_hardening_rsi_2026-09-18.md`, mirrored
in Linear HAR-88. Read that before dispatching anything.

Three things it changes for the next dispatch:

1. The provider route is `deepseek/deepseek-v4-flash-0731` on `deepinfra`
   only (fp8). The `relace` route was fp4 - a confound against the fp8
   baseline. `config/benchmark_model.v1.json` is the model's single source
   of truth.
2. Every TB2 task job now ends with `scripts.verify_run_receipts` over the
   Pier job directory. rc 1 means the receipts contradict each other, rc 2
   means nothing was resolved (`resolution_error` says which way), and a
   green job with `receipt-consistency.json` absent is an error. Read that
   file before counting a task.
3. The planner excludes Alpine/musl final stages by parsing the Dockerfile
   the way BuildKit does and reports `excluded` / `unresolved` in
   `tb2-gt-smoke20-plan.json`; the funds preflight is sized by the
   post-exclusion `task_count`.

Campaign 2 (commits `89d5494d` + `88fc821c`) closed defects 3 and 7 on the
code side: a committed patch is no longer discarded on a missing containment
receipt (terminal `containment_lost`, exit 0), and the index headroom guard
reads the task's real cgroup. `gt_engine` is re-pinned to tree `9d987079`;
`gt_source_commit` stays `921bec20`. Defects 4, 5 and 6 remain (not ours /
workaround in place / model behaviour). Defect 7's residual is container
memory, not code.

## How state carries between sessions

There is no hidden model memory between GitHub jobs. Continuity is explicit:

1. The branch and `config/tb2_gt_import_manifest.json` carry source identity.
2. Workflow inputs carry model, provider route, task cohort, parallelism, and timeout policy.
3. A passing SWE-Live gate run ID is supplied as `prior_gate_run_id` to release the remaining tasks.
4. GitHub artifacts are downloaded into `.tmp-*` directories and indexed by run ID; never overwrite an earlier run.
5. Each task's trajectory, token report, product receipt, official verifier output, attestation, and diagnostic summary are the source of truth.
6. This handoff is updated after every run transition, failure classification, and dispatch.

When resuming, inspect `git status`, this file, the latest run IDs, and the
latest artifact manifests. Do not ask the user to restate the model, source
commit, verifier, parallelism, or failure policy.

## Safe dispatch sequence

Superseded on 2026-09-19 by the runbook in
`docs/benchmarks/gt_hardening_rsi_2026-09-18.md` section 8 (provider-free
product workflow first, then a 2-3 task TB2 subset, then the smoke). The
steps below are the original sequence and still describe the SWE-Live gate.

1. Run provider-free readiness and exact-source verification.
2. Run one gate task for SWE-Live. Release the remaining four only when the gate has official grading, PASS attestation, diagnostic exit 0, and all required capabilities WORKING.
3. Run TB2 smoke at p20 only after the planner and provider preflight pass.
4. Monitor both workflows. For each completed task, classify it from the official verifier and task diagnostic artifacts before updating counters.
5. Download all artifacts before starting any repeat. Keep run IDs and commit SHAs in the update.

## Known runtime detail

The certified wheel's background LSP promoter hardcodes a 500-edge selection
limit. The SWE-Live adapter uploads a benchmark-owned `sitecustomize.py` hook
that honors `GT_LSP_MAX_EDGES` and makes the receipt truthful. This preserves
all pinned GT source objects and keeps the strict diagnostic enabled; it does
not turn incomplete promotion into a pass.
