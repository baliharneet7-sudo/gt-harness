# Benchmark handoff

This file is the persistent operating record for the GT benchmark campaign. A
new session should read it before dispatching anything. It is deliberately
free of API keys, account emails, project IDs, and other credentials.

## Fixed experiment contract

- Model: `stealth/union-alpha` through OpenRouter (`https://openrouter.ai/api/v1`).
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

`Model: stealth/union-alpha | Tasks completed: N | Tasks left: N | Tasks success: N | Tasks failed (incorrect): N | Tasks failed (infrastructure): N`

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

- Attempts `35256152140`, `35257234010`, `35257606223`, and `35257941589` failed in `plan` before task dispatch. The first referenced test files absent from the checked-out tree; the second selected a test tied to a different producer digest and historical commits; the third invoked an absent `scripts/central_feature_census.py` after all selected tests passed; the fourth used only `OPENAI_API_KEY` and sent no `OPENROUTER_NEW` credential, producing a 401. No TB2 task was graded and no TB2 image was pulled.
- TB2 now uses the same `secrets.OPENROUTER_NEW` fallback as SWE-Live in both its plan and task environments.
- The planner list is now limited to source-compatible central-agent, progress, provider-preflight, budget, and outcome tests in `.github/workflows/tb2_miniswe_engine.yml`. Push this fix to both benchmark accounts before retrying TB2.
- Retry with the exact branch, model `openrouter/stealth/union-alpha`, `parallel=20`, `arm=certified_full`, and the documented smoke task list.

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
