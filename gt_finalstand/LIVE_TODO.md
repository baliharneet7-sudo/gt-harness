# GroundTruth Phase II Live TODO

This is the current operational authority for closing FS-001 through FS-026. The machine state remains [closeout_status.csv](closeout_status.csv). A carrier type, dormant producer, source diff, or historical checkpoint is not a completion receipt. Every `IN_PROGRESS` row stays open until its terminal criterion is observed in an external workflow or authorized experiment, as applicable.

## Live queue

| TODO | Decision | Status | Terminal criterion | Current evidence and next proof |
|---|---|---|---|---|
| FS-001 | BUILD | COMPLETE | Canonical contracts, strict validation, deterministic bytes, and decision truth table pass. | Observation compiler exists; 14/14 new contract and 120/120 focused core tests passed. |
| FS-002 | BUILD | COMPLETE | One snapshot authority detects every relevant worktree/config/revision change and ignores irrelevant caches. | Content-addressed pre/post action authority is runtime-wired; final harness authority receipt is 129 collected, 128 passed, 1 environment-conditional skip. |
| FS-003 | MODIFY | COMPLETE | Native registry produces exactly 30 collision-free languages and the harness consumes the generated manifest. | GroundTruth manifest/parity and full tagged Go suites passed in Codespaces; generated hash `53afc445...` and 30 sorted identities are the harness authority, and Mini-SWE binds that nonempty hash by default; focused harness receipt 28/28 passed. |
| FS-004 | BUILD | COMPLETE | Seven typed actions coexist with byte-compatible stock Bash and fail open without another model call. | Native tool and tests exist; the final provider-free harness suite collected 592 tests, passed 591, and recorded one declared complementary graph skip. |
| FS-005 | MODIFY | COMPLETE | Exact final provider bytes join one request, response, and immediate next action across retry/restart/error cases. | Final request/response/next-action lineage and exact provider-bound receipts pass the final harness authority suite. |
| FS-006 | BUILD | COMPLETE | Off/shadow/augment/replace/enforce precedence and every capability kill switch pass rollback tests. | Global modes, independent capability controls, GT-off restoration, kill switches, and fail-open paths pass the final harness authority suite. |
| FS-007 | MODIFY | COMPLETE | Ten cold semantic builds match byte-for-byte and source, Windows, and vendored Linux binaries pass one corpus. | Codespace GroundTruth `7fcb0191...`: full `CGO_ENABLED=1 go test -tags sqlite_fts5 ./...` passed; runtime freshness and atomic publication cluster passes. |
| FS-008 | BUILD | COMPLETE | Explicit-scope literal results equal the reference byte scanner; every omission revokes exactness. | Producer exists; 9/9 focused and 132/132 related GroundTruth tests passed. |
| FS-009 | MODIFY | COMPLETE | One ordered transaction captures multi-file add/edit/delete/rename/mode/symlink effects and partial failure. | Canonical pre/post snapshots, ordered multi-file deltas, exact blobs, modes, symlinks, rename candidates, and omission semantics are runtime-wired and tested. |
| FS-010 | MODIFY | COMPLETE | Every changed applicable file has an immediate revision-bound syntax receipt or explicit unsupported record. | Immediate transaction artifacts emit one post-revision syntax row for every changed file: Python exact, deletion not applicable, and every other file explicitly unsupported; 66/66 closure tests passed. |
| FS-011 | MODIFY | COMPLETE | Exact patch reconstructs postimages and callers never claim completeness without a certified closed world. | Untruncated patches plus exact postimage bytes/hashes reconstruct text, binary, create, modify, and delete changes; callers remain `graph_recorded`, never complete; 66/66 passed. |
| FS-012 | MODIFY | COMPLETE | Structured build/test parsing can fail without dropping a raw byte and every result is execution-scoped. | Execution artifacts preserve raw observations and bind command, outcome, revision, transaction, and delivery; parse failure retains raw output. |
| FS-013 | BUILD | COMPLETE | Incremental and clean-full results match across edit/config/delete/rename/crash cases with atomic fallback. | Runtime rejects stale graph evidence, invalidates on edits, atomically publishes refreshes, and fails open; full tagged Go suite passed. |
| FS-014 | MODIFY | COMPLETE | Every definition/reference/caller pair has certified language/config scope or is absent from the typed schema. | All definition/reference/caller pairs are terminally removed, the generated public schema omits them, and runtime certification rejects manual construction; typed contract passed 16/16. |
| FS-015 | BUILD | COMPLETE | All 210 language-operation pairs are terminally certified and the public schema is generated from that matrix. | GroundTruth authority records 35 exact, 30 execution-specific, 145 removed; harness advertises only literal, syntax, and verification. |
| FS-016 | MODIFY | COMPLETE | Localization stays advisory, gives stable anchors and score reasons, and passes tie/stale/no-match fixtures. | Advisory anchors/scores/reasons/ties, dirty files, no-match and unavailable fallback pass; existing stale graphs are gated by `graph_fresh`, fall back lexically, and record `graph_localization_stale`; Codespaces cell 620 passed 27/27 plus lint. |
| FS-017 | MODIFY | COMPLETE | Task-span obligation IDs deliver deltas and invalidate on task/edit/verification changes. | Exact UTF-8 task-span IDs, episode-session wiring, delta-only emission, and revision invalidation pass the 67/67 widened GroundTruth artifact suite. |
| FS-018 | MODIFY | COMPLETE | Recovery reuses only an identical normalized failure identity and never prescribes action for similar-only failures. | Exact normalized action/environment/revision/outcome/diagnostic identity is episode-wired; similar-only failures do not match; 67/67 widened tests pass. |
| FS-019 | BUILD | COMPLETE | On-demand build/config adapters qualify target membership, generated inputs, and dependency edges. | Repository adapters emit deterministic sound-overapprox slices on demand; unresolved targets, membership, generated inputs, and dependency edges are explicit omissions rather than false exactness. |
| FS-020 | MODIFY | COMPLETE | New-file precedent is provenance-rich, path-specific, inspectable, and incapable of replacement/suppression. | Same-action advisory binds revision/transaction, reasons, destination and sibling paths; preserves raw output, stays quiet without precedent, excludes exact renames, runs no hidden command, and only augments; 66/66 passed. |
| FS-021 | BUILD | COMPLETE | Fresh closed-scope blockers alone suppress submit in enforce mode, with provider-absence receipt and rollback. | Exact closed fresh blocker gate, immediate enforce kill switch, zero-provider-byte suppression receipt, and receipt-failure fail-open behavior pass the 67/67 widened suite. |
| FS-022 | REMOVE | REMOVED | Prohibited capabilities have zero public/default visibility and zero execution; comparison controls are isolated. | AST import closure covers 66 files reachable from Mini-SWE and reports zero forbidden findings; typed schema omits comparison controls. |
| FS-023 | BUILD | IN_PROGRESS | The complete offline battery passes in one immutable external workflow with artifacts and hashes. | The [final Codespaces receipt](receipts/final_codespace_verification.json) records green product, harness, smoke, and Go suites, and [FS-023 provenance](receipts/fs023_provenance.json) binds the locally available hashes. `workflow_execution_identity_bound=false`; the immutable Actions run and uploaded artifact identities are still missing, so the literal criterion is unmet. |
| FS-024 | BUILD | IN_PROGRESS | User-authorized six-arm matched experiment finishes with independent outcomes and preregistered paired analysis. | The deterministic [execution plan](receipts/experiment_execution_plan.json) binds 10 tasks, 6 arms, and 60 planned trials with SHA-256 `a3edf2fa...`; `executed=false` and `provider_calls=0`, so authorized paid execution remains absent. |
| FS-025 | MODIFY | IN_PROGRESS | Measured Pareto-dominant defaults ship; duplicate legacy model-visible paths are removed; GT-off parity and rollback pass. | Promotion machinery correctly refuses and performs no mutation without experiment, Go, rollback, and default-promotion evidence. |
| FS-026 | BUILD | IN_PROGRESS | Every FS item has a terminal receipt; all hashes, runbooks, benchmark results, and rollback rehearsal are frozen. | The Codespaces receipt freezes current dirty-worktree test hashes, but clean-machine/rollback runbooks only validate structurally; immutable Actions identity, committed release inputs, uploaded artifact bundle hash, paid experiment, promotion, and rollback rehearsal remain absent. |

## Current post-audit proof note

The bounded hardening inventory and proof surfaces are recorded in [POST_AUDIT_HARDENING.md](POST_AUDIT_HARDENING.md). The machine-readable [final Codespaces receipt](receipts/final_codespace_verification.json) records GroundTruth **9,980 passed, 415 skipped, 6 expected failures**, harness **592 collected, 591 passed, 1 skipped**, offline smoke **10 collected, 9 passed, 1 skipped**, and a passing full tagged Go suite. GroundTruth JUnit SHA-256 is `2e96bae3...`; harness JUnit SHA-256 is `0a262594...`; smoke JUnit SHA-256 is `c4201528...`. These provider-free results do not close FS-023, FS-024, FS-025, or FS-026 because Codespaces are not the required immutable workflow and no causal experiment ran.

## Ten-minute checkpoint loop

At every checkpoint:

1. Pull the latest external workflow state by immutable run identity.
2. Update only evidence that actually changed.
3. Run `python scripts/generate_gt_finalstand.py --check` and `python scripts/validate_gt_finalstand.py` in the Codespace or GitHub Actions job.
4. Keep every missing proof attached to its FS row.
5. Promote a status only when its terminal criterion is fully observed; otherwise leave it `IN_PROGRESS`.

## Current execution state

- Machine authority: **21 `COMPLETE`, 4 `IN_PROGRESS`, 1 `REMOVED`**.
- Provider-free regression state: product, harness, smoke, and tagged Go suites are green for the exact Codespace worktrees bound in `receipts/final_codespace_verification.json`.
- Open terminal gates: FS-023 immutable external offline workflow execution, FS-024 authorized paired experiment, FS-025 evidence-based promotion and rollback, and FS-026 immutable clean-machine workflow closure.
- FS-022 remains `REMOVED` by decision.
- Historical checkpoint records are preserved in [LIVE_TODO_HISTORY.md](LIVE_TODO_HISTORY.md). They are superseded and are not current status authority.
