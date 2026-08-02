# GroundTruth Final Stand

This directory is the terminal execution authority for GroundTruth Phase II. It converts the accepted deterministic-observation monograph into implementation, validation, release, and closeout work. It does not reopen the research question.

There is no open-ended backlog. Every item ends as `BUILD`, `MODIFY`, `KEEP`, or `REMOVE`, and every execution item ends with evidence of completion or removal.

## Current state

The machine authority records **21 `COMPLETE`, 4 `IN_PROGRESS`, and 1 `REMOVED`**. The four open rows are FS-023 (immutable external offline-workflow execution and artifact identity), FS-024 (authorized paired experiment), FS-025 (evidence-based promotion and rollback), and FS-026 (final clean-machine workflow and frozen artifact closure). A suite-terminal local receipt does not close FS-023 without its literal external-workflow proof.

The latest provider-free Codespaces verification is [final_codespace_verification.json](receipts/final_codespace_verification.json): the GroundTruth Python suite passed 9,980 tests with 415 skips and 6 expected failures; the harness suite passed 591 of 592 collected tests with one declared environment-conditional skip; the offline smoke passed 9 of 10 with the same complementary graph skip; and the full tagged Go suite passed. This evidence is green for its recorded dirty-worktree inputs. It is not an immutable GitHub Actions run and does not change the four open rows.

## Authority order

1. [PHASE_II_IMPLEMENTATION_ROADMAP.md](PHASE_II_IMPLEMENTATION_ROADMAP.md) defines the architecture, priorities, gates, and engineering TODOs.
2. [direct_capabilities.csv](direct_capabilities.csv) is the machine-checkable 17-row DIRECT inventory.
3. [role_audit.csv](role_audit.csv) is the generated machine-checkable 129-row role inventory.
4. [language_support.csv](language_support.csv) is the 30-language registry inventory.
5. [language_operation_certification.csv](language_operation_certification.csv) terminally classifies all 210 language-operation pairs.
6. [closeout_status.csv](closeout_status.csv) is the 26-row execution-state authority.
7. [execution_ledger.md](execution_ledger.md) records implementation receipts, external gates, and exact limitations.
8. [LIVE_TODO.md](LIVE_TODO.md) is the current-only FS-001 through FS-026 closure loop.
9. [LIVE_TODO_HISTORY.md](LIVE_TODO_HISTORY.md) preserves superseded checkpoint history and is not current status authority.
10. [POST_AUDIT_HARDENING.md](POST_AUDIT_HARDENING.md) records bounded post-audit implementation and provider-free Codespaces receipts without changing open terminal gates.
11. [validation_receipt.json](validation_receipt.json) is the latest machine-validation result.
12. [CLEAN_MACHINE_RUNBOOK.md](CLEAN_MACHINE_RUNBOOK.md) defines the provider-free external validation flow.
13. [ROLLBACK_RUNBOOK.md](ROLLBACK_RUNBOOK.md) defines rollback triggers, execution, verification, and receipts.
14. [phase2_experiment_manifest.json](phase2_experiment_manifest.json) is the six-arm dry-run template; it is not an execution authorization.
15. [EXPERIMENT_EXECUTION_CONTRACT.md](EXPERIMENT_EXECUTION_CONTRACT.md) defines authorization, result rows, analysis, and promotion gates.
16. [receipts/](receipts/) contains provider-free positive and negative machine receipts.
17. [language_operation_compatibility.json](language_operation_compatibility.json) freezes the
    GroundTruth-produced compatibility authority used to generate the public typed-action schema.
18. [gt_finalstand_provider_free.yml](../.github/workflows/gt_finalstand_provider_free.yml) is the
    dispatch-only GitHub Actions implementation of the provider-free closeout gate.

Within [receipts/](receipts/), `final_codespace_verification.json` binds the latest product, harness, smoke, Go, worktree, and clean-fixture evidence; `provider_free_smoke10.json` binds the ten-node offline smoke; `experiment_execution_plan.json` binds the deterministic 10-task by 6-arm plan while recording that no trial executed; and `fs023_provenance.json` records the immutable workflow identities that are still missing.

The accepted monograph under `.research/gt-deterministic-interface/` remains the evidence basis. This directory owns the implementation decision. If prose here conflicts with a CSV inventory, the roadmap governs intent and the CSV must be repaired before work continues.

## Non-negotiable invariants

- GroundTruth does not replace Mini-SWE reasoning.
- The planner chooses the action before GroundTruth intervenes.
- Stock Bash semantics remain literal.
- Unknown, compound, mixed read/write, stale, ambiguous, or incomplete operations preserve raw behavior.
- Builds and tests retain complete native diagnostics.
- Replacement requires a typed action and a mechanically certified result contract.
- GT-off remains a first-class stock-compatible mode.
- Every capability has a kill switch and fail-open path.
- Unsupported functionality is removed from advertised support rather than left pending.
- Project closure requires completed controlled validation, frozen artifact hashes, and terminal receipts for every TODO.

## Machine checks

The complete provider-free release check runs through the dispatch-only
`gt_finalstand_provider_free.yml` GitHub Actions workflow. Fast document checks can also run in a
GitHub Codespace from the repository root:

```powershell
python scripts/generate_gt_finalstand.py --check
python scripts/validate_gt_finalstand.py
python -m pytest tests/test_gt_finalstand.py tests/test_phase2_closeout.py -q
```

The validator writes `validation_receipt.json` and exits nonzero on inventory drift, schema violations, broken links, forbidden public capability identifiers, illegal closeout states, or an unsupported completion claim.
