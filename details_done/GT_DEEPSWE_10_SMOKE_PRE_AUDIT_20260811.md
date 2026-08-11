# GT DeepSWE ten-task smoke pre-audit (2026-08-11)

## Scope

This audit covers the current `gt-harness` HEAD (`e52ff9d814be56de53ae92764c4875fda93fe179`) and the requested ten-task DeepSWE smoke. It does not treat the older `D:\Groundtruth` checkout as the active product.

## Current implementation proof

- Active agent: `eval.gt_central_agent:MiniSweCentralAgent`.
- Current runtime is host-owned and in-process. It resolves the task image working directory, mirrors selected source into the host, observes model actions before and after execution, refreshes repository intelligence before the next provider call, and compiles one bounded provider view.
- The current integration repair is on the pushed HEAD. Tracked files are clean after restoring the locally rebuilt diagnostic binary.
- Provider-free GitHub certification at the exact HEAD is green: workflow `31545142600` passed the source-built index, all 17 producer/consumer/timing/payload/context gates, readiness, static checks, and exact pre-smoke.
- Local exact pre-smoke is also green when `GT_INDEX_BINARY` points to a source-built temporary binary. The default checked-in Windows binary is older and lacks the newly registered Objective-C adapter; this is an environment artifact, not the CI path. The paid workflow must build the index from `vendor/gt-index-src` and set `GT_INDEX_BINARY` to that build, as the certified workflow does.
- Local census markers: `ALL_17_PRODUCERS_PROVEN`, `ALL_17_CONSUMERS_PROVEN`, `ALL_EFFECTS_TIMING_VALID`, `ALL_PAYLOADS_GROUNDED`, `ALL_17_CONSUMER_PATHS_PROVEN`, `ALL_17_TRIGGERS_PROVEN`, `ALL_17_PAYLOADS_CONCRETE`, `ALL_17_CONSUMERS_APPLIED`, `ALL_VISIBLE_PAYLOADS_IN_FIRST_ELIGIBLE_REQUEST`, and `ALL_EFFECTS_CONTEXT_ACCOUNTED`.

## DeepSWE asset audit

- Local checkout: `D:\Groundtruth\deepswe-bench`, tag `v1.0.0`, 113 task directories.
- Manifest: `artifact_deepswe/repo_manifest.json`, 113 tasks, 92 repositories, Go/Python/TypeScript/JavaScript/Rust coverage.
- Existing downloaded trajectories and summaries are historical evidence only. They use the retired `artifact_deepswe.gt_agent:GTMiniSweAgent` path and are not evidence for the current central runtime.
- The current `gt-harness` repository has no DeepSWE workflow. The only `deepswe_full.yml` is in the older `D:\Groundtruth` checkout and uses the retired agent, legacy Pier integration, and legacy GT flags. Dispatching it would not test this HEAD and is prohibited by this audit.
- DeepSWE task TOMLs are Harbor-compatible (`metadata`, `verifier`, `agent`, `environment`, and `docker_image`). Harbor 0.20 supports a local dataset path plus task-name filtering, so a current workflow can run exact task IDs without rebuilding or copying the dataset into the repository.

## Smoke task set

The ten-task set will be frozen before dispatch from the v1.0.0 manifest, balanced across the five declared language families (two each). The exact IDs, manifest hash, workflow SHA, model, arm, and task order will be recorded in the smoke contract and uploaded with the run artifacts.

## Gate decision

**GT runtime: APPROVED.** Exact-head provider-free implementation and delivery gates pass.

**DeepSWE paid smoke: NOT YET DISPATCHABLE.** A current workflow is required first. Reusing the old workflow would run the wrong agent. The next implementation is therefore a thin Harbor matrix workflow that keeps the current central agent, fresh per-task graph/index construction, pinned Snowflake ONNX backend, and the existing receipt/delivery audit. No runtime GT code change is required.

## Required smoke measurements

Per task and cumulatively: verifier reward, uncensored resolve status, outer/inner timeout classification, provider request hash coverage, first-eligible timing, late/predictive counts, delivery-audit failures, graph applicability/readiness, dense backend identity/availability, GT effect dispositions, provider-visible chars, total GT context chars, model calls, assistant steps, effective actions, actual environment executions, input/output/total tokens, wall time, and cost. Historical DeepSWE-off results will be labeled descriptive unless the exact model/harness/config parity is proven.

