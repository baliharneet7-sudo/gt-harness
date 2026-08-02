# Post-Audit Runtime Hardening Verification

This appendix records the GroundTruth hardening implemented after the initial Phase II closeout audit. It is implementation and focused-verification evidence only. It does not change the machine authority in [closeout_status.csv](closeout_status.csv): FS-023, FS-024, FS-025, and FS-026 remain `IN_PROGRESS`, and the current count remains 21 `COMPLETE`, 4 `IN_PROGRESS`, and 1 `REMOVED`.

## Provider-free Codespaces receipts

The final machine-readable receipt is [final_codespace_verification.json](receipts/final_codespace_verification.json). It binds the exact Codespace host, base HEAD, tracked-diff Git object, command, result counts, and artifact hashes for the final provider-free verification:

- GroundTruth Python: **9,980 passed, 415 skipped, 6 expected failures, 0 failures/errors**, exit 0 in 395.26 seconds. JUnit SHA-256: `2e96bae37da6761c1a1088a988d08ad0642ffc447190cdbf94cf160e8dbac688`; log SHA-256: `4fbbff7aa80bfb8f85c4a4757fdb6275bef6c5eb1c60509be2312d0173934f48`.
- Harness Python: **592 collected, 591 passed, 1 skipped, 0 failed**. JUnit SHA-256: `0a26259408a93879563f288c7f1433331aff27ecf20c59350ec32733ff075189`; log SHA-256: `9eeb7303bd1b54335628fcc5f5e95c33b9427e7a6a0c1f4f724afec5a681a49e`.
- Provider-free runtime smoke: **10 collected, 9 passed, 1 skipped, 0 failed, 0 provider calls**. JUnit SHA-256: `c420152806eabc9dfa73ef98394d3acf0482926ad8974913ef4a1795a5716234`.
- GroundTruth Go: `CGO_ENABLED=1 go test -tags sqlite_fts5 ./...` passed across all packages.
- Shell syntax validation: `scripts/ci/substrate_proof.sh` passed `bash -n` after LF normalization.

The sole harness and smoke skip is `tests/test_miniswe_smoke.py::test_miniswe_gt_smoke_localization_requires_graph`: the graph is available, and the positive graph behavior is covered by `test_task_start_localization_delivered_with_graph`. The GroundTruth JUnit reports 10,401 cases with 421 skipped nodes because pytest represents the 6 expected failures as skipped in JUnit.

Focused Ruff and whitespace checks pass for `tests/conftest.py` and `tests/runtime/test_runtime_package_isolation_20260801.py`. A wider exploratory Ruff sweep across 18 untracked Python closeout surfaces reports 49 diagnostics, 26 auto-fixable. No edits were applied from that sweep, and this appendix makes no global Ruff-green claim.

These are Codespaces receipts over dirty worktrees, not immutable GitHub Actions receipts. No provider call, paid experiment, GitHub authentication, workflow dispatch, immutable Actions run ID, or immutable Actions run URL is asserted.

Before the full suites ran, focused provider-free batches were reported as **140/140** runtime/action tests and **57/57** dependency/verification tests. No machine receipt is created for those two historical focused counts because their exact commands, complete outputs, and artifact hashes are not recoverable. They remain non-terminal prose and are superseded for regression status by the machine-readable full-suite receipt above; they do not promote FS-023, FS-024, FS-025, or FS-026.

## Implemented hardening

### Injected runtime closure

The DeepSWE injection bundle now includes the runtime modules imported by the terminal and provider seams: `presubmit_verification.py`, `producer_audit.py`, `terminal_evidence.py`, and `evidence/issue_obligations.py`. This closes the task-container import graph so a product runtime does not disappear merely because it was present only in the host checkout.

Primary implementation and proof surfaces:

- `D:/Groundtruth/artifact_deepswe/gt_agent.py`
- `D:/Groundtruth/tests/test_deepswe_injection_import_coverage.py`
- `D:/Groundtruth/tests/runtime/test_runtime_package_isolation_20260801.py`

### Action-specific freshness and snapshot authority

Repository-content actions now bind to a complete per-file snapshot manifest, repository revision, and working-tree hash. Verification-status actions bind to runtime-evidence freshness rather than graph freshness. Interception compares the producer revision against the action-specific authority and downgrades stale, incomplete, mismatched, or omitted evidence instead of granting replacement.

Primary implementation and proof surfaces:

- `D:/Groundtruth/src/groundtruth/runtime/deterministic_queries.py`
- `D:/Groundtruth/src/groundtruth/runtime/observation_compiler.py`
- [miniswe_typed_actions.py](../gt_engine/miniswe_typed_actions.py)
- [miniswe_integration.py](../gt_engine/miniswe_integration.py)
- `D:/Groundtruth/tests/unit/test_runtime_deterministic_queries.py`
- `D:/Groundtruth/tests/runtime/test_observation_compiler_contracts_20260801.py`

### Same-byte syntax checking

Syntax evidence now hashes and parses the same captured postimage bytes. `check_edit_syntax_bytes` materializes the immutable byte capture in a private temporary location, scrubs that temporary identity from diagnostics, and fails quiet when an injected executor cannot receive the captured bytes. This removes the reopen-between-hash-and-parse TOCTOU window.

Primary implementation and proof surfaces:

- `D:/Groundtruth/src/groundtruth/runtime/edit_check.py`
- `D:/Groundtruth/src/groundtruth/runtime/deterministic_queries.py`
- `D:/Groundtruth/tests/unit/test_runtime_deterministic_queries.py`

### Removed definition, reference, and caller execution surfaces

The public observation-compiler action enum and generated Mini-SWE schema do not expose definition, reference, or caller actions. The remaining legacy names in compatibility/rejection tables are non-dispatchable guards: they reject or normalize old input; they do not restore a `FIND_DEFINITION`, `FIND_REFERENCES`, or `FIND_CALLERS` producer path.

Primary implementation and proof surfaces:

- `D:/Groundtruth/src/groundtruth/runtime/observation_compiler.py`
- [generated_typed_capabilities.py](../gt_engine/generated_typed_capabilities.py)
- [miniswe_typed_actions.py](../gt_engine/miniswe_typed_actions.py)
- `D:/Groundtruth/tests/runtime/test_observation_compiler_contracts_20260801.py`
- [test_phase2_closeout.py](../tests/test_phase2_closeout.py)

### Response-committed delivery receipts

An observation-compiler delivery receipt can now be created only from a `RESPONSE_COMMITTED` delivery attempt. The receipt binds the provider request payload, provider response identity and hash, exact final observation bytes, and immediate next action. A merely accepted, compiled, joined, dispatched, or delivered attempt is insufficient.

Primary implementation and proof surfaces:

- `D:/Groundtruth/src/groundtruth/runtime/observation_compiler.py`
- `D:/Groundtruth/src/groundtruth/runtime/miniswe_provider_boundary.py`
- `D:/Groundtruth/tests/runtime/test_observation_compiler_contracts_20260801.py`
- `D:/Groundtruth/tests/runtime/test_provider_delivery_lifecycle.py`

### Rust task-owned dependency provenance

The substrate script no longer transplants `rust-src` from an arbitrary baked toolchain into the task toolchain. Rust dependency evidence must come from the task-owned path, the dependency manifest requires a nonempty Rust source store for Rust tasks, and a missing dependency manifest is a proof failure rather than a completed dependency stage.

Primary implementation and proof surfaces:

- `D:/Groundtruth/scripts/ci/substrate_proof.sh`
- `D:/Groundtruth/scripts/swebench/dep_store_manifest.py`
- `D:/Groundtruth/scripts/swebench/gt_run_proof.py`
- `D:/Groundtruth/tests/test_dep_store_manifest.py`

### Total presubmit syntax budget and language coverage

The verification plan applies one total wall-clock budget across rungs and a remaining-budget bound to each syntax target. Targets left after exhaustion are explicitly `unavailable` with `total_budget_exhausted`; they cannot be silently treated as clean. The positive syntax set now includes `.pyi`, `.mjs`, `.cjs`, `.ts`, `.tsx`, and `.jsx` in addition to the previously supported Python, JavaScript, Go, and Ruby extensions.

Primary implementation and proof surfaces:

- `D:/Groundtruth/src/groundtruth/runtime/verification_plan.py`
- `D:/Groundtruth/src/groundtruth/runtime/edit_check.py`
- `D:/Groundtruth/tests/runtime/test_verification_plan.py`

### Exact-only canonical submit suppression

Submit suppression is authorized only from the canonical submit boundary, only for a fresh exact closed-scope syntax blocker over the current repository revision, and only when a durable provider-bound zero-byte receipt succeeds. Unknown, partial, stale, execution-specific, missing-authority, and receipt-failure cases fail open. The authority is single-proposal and is cleared before each new submit proposal.

Primary implementation and proof surfaces:

- `D:/Groundtruth/artifact_deepswe/gt_mini_patch.py`
- `D:/Groundtruth/src/groundtruth/runtime/terminal_evidence.py`
- `D:/Groundtruth/src/groundtruth/runtime/miniswe_provider_boundary.py`
- `D:/Groundtruth/tests/test_ledger_suppression.py`
- `D:/Groundtruth/tests/runtime/test_terminal_evidence_contracts_20260801.py`

### Restored clean-CI coverage

The clean-CI dependency set now explicitly supplies packages imported by the determinism, metrics, workflow-contract, language-pack, Mini-SWE, and embedding contract tests. The workflow also executes generated language-operation compatibility parity in the Go specs package. Architecture-contract tests read their shipped JSON authority instead of a missing prose document.

Primary implementation and proof surfaces:

- `D:/Groundtruth/pyproject.toml`
- `D:/Groundtruth/.github/workflows/ci.yml`
- `D:/Groundtruth/tests/contract/architecture_contract.json`
- `D:/Groundtruth/tests/contract/test_architecture_contract.py`

### Acquisition and delivery counter consistency

Acquisition counters now remain independent of delivery reduction, while delivery counters retain their delivery-side population. When re-slotting withholds every acquired candidate, delivery is explicitly not evaluable rather than a fabricated zero. Legacy delivery fields remain delivery-scoped so existing gates do not compare an acquisition numerator against a delivery denominator.

Primary implementation and proof surfaces:

- `D:/Groundtruth/src/groundtruth/pretask/v1r_brief.py`
- `D:/Groundtruth/tests/pretask/test_acquisition_vs_delivery_families_20260727.py`
- `D:/Groundtruth/tests/pretask/test_acquisition_proof_20260728.py`

### Clean full-suite fixture and isolation repairs

The final suite no longer depends on the ignored `artifact_verified/` directory. Verified-adapter comparison artifacts live under `tests/fixtures/verified_adapter/`, and `tests/test_verified_adapter.py` reads that test-owned location. The Codespace byte hashes for the three fixture files are frozen in `receipts/final_codespace_verification.json`. The fixture paths are currently untracked release inputs, so the immutable workflow remains blocked until the scoped release set is committed and pushed.

The shared test process now imports the co-located `src` package before unrelated editable installs, while the package-isolation test performs destructive import-cache checks in a subprocess. Reload-sensitive runtime tests preserve the current producer carrier, compare canonical enum values instead of import-generation identity, and repair the shared embedding-cache alias after module reload. Attempt-suffixed task artifacts retain their initial resolved trial identity. Lock ownership, POSIX/Windows path rewriting, delivery deduplication, and sealed Go workspace metadata fixtures now exercise the current deterministic contracts instead of stale implementation assumptions.

Primary implementation and proof surfaces:

- `D:/Groundtruth/tests/conftest.py`
- `D:/Groundtruth/tests/fixtures/verified_adapter/`
- `D:/Groundtruth/tests/test_verified_adapter.py`
- `D:/Groundtruth/tests/runtime/test_runtime_package_isolation_20260801.py`
- `D:/Groundtruth/artifact_deepswe/gt_mini_patch.py`
- `D:/Groundtruth/scripts/swebench/task_truth.py`
- `D:/Groundtruth/tests/test_semantic_encode_budget.py`
- `D:/Groundtruth/tests/test_ss_gate_selftest.py`
- `D:/Groundtruth/tests/test_ss_replay_oracle_selftest.py`
- `D:/Groundtruth/tests/test_verification_horizon_stage_a.py`
- `D:/Groundtruth/tests/test_workspace_metadata_probe.py`

## Status boundary

This hardening strengthens already implemented deterministic contracts and their regression protection. It does not supply the immutable external offline-workflow identity required by FS-023, the authorized paired experiment required by FS-024, the evidence-based default promotion and rollback proof required by FS-025, or the immutable clean-machine workflow identity and final artifact bundle required by FS-026. Those four rows therefore remain open without qualification.
