# GT harness hardening — RSI campaign, 2026-09-18

Single tracking document for the offline hardening pass that followed the
2026-09-17 smokes. Everything here was done with mocks, stubs and copies of
already-downloaded artifacts: **no provider call, no GitHub dispatch, no
Docker, zero spend.** Linear: HAR-88 (this document is its body; the file is
the source of truth).

Worktree `D:\w\t`, branch `codex/tb2-gt-union-921bec20`, base commit
`a03ad260`. The campaign branch on GitHub is
`baliharneet7-sudo/gt-harness@codex/gt-921bec20-union-smokes`.

## Rules that governed the work

1. **Pinned source objects were never edited in campaign 1**: `gt_engine/`,
   `gt_harness/`, `eval/`, `vendor/`, `nano/`, `gt_finalstand/`,
   `pyproject.toml`, `conftest.py`; `gt_engine` stayed tree `22daf78b...`
   through commit `07a16e58`. **Campaign 2 re-pinned `gt_engine`** by the
   user's decision: commit `89d5494d` edits `gt_engine/indexer.py` and
   `gt_engine/attribution.py` only; commit `88fc821c` sets the manifest's
   `source_object_ids.gt_engine` to `9d987079019f523035d7e276a551952e2048566a`,
   keeps `gt_source_commit` at `921bec20` (import provenance of the seven
   unchanged objects) and records `gt_source_patch_commit = 89d5494d`.
2. **No GT-off run, ever** (CLAUDE.md). Step limit stays 100, the frozen
   baseline's value.
3. **Every fix is TDD**: failing test first, then the fix, both outputs shown
   by the implementing agent.
4. **Every round is reviewed adversarially** by a separate Opus reviewer that
   reproduces findings on copies of real artifact trees
   (`.tmp-swelive-35249057348`, `.tmp-swelive-35241999929`) rather than
   reading diffs. Exit criterion: a review with nothing above LOW.
5. Workflow YAML is CRLF; edits were byte-level. Whole-file rewrites are
   defects.

## Method

Orchestrator (Fable 5.1) → two Opus fix agents per round on disjoint files →
full pytest suite → Opus adversarial review → next round. Nine rounds.

| Round | Review verdict | Headline |
|---|---|---|
| 1 | 1 CRITICAL | attestation exact set-equality vs 8 new preflight fields |
| 2 | 1 CRITICAL + 4 HIGH | verifier step pointed one level above Pier receipts |
| 3 | 3 HIGH | phantom `*_count` keys; unbounded rglob; test resolved `$root` itself |
| 4 | 2 HIGH | `except OSError` missed `UnicodeDecodeError`; `_trial_roots` expanded a checkout |
| 5 | 1 HIGH | `_inside_a_trial` parent-NAME rule rejected depth-2 SWE-bench trials |
| 6 | 2 HIGH + 1 MEDIUM | crashed check → rc 0 (false green); `NaN` crashes `_int`; joiner ate `#` lines |
| 7 | 1 HIGH + 1 MEDIUM + 4 LOW | bare trial dir counted as resolved → rc 0; joiner not BuildKit-faithful |
| 8 | 0 HIGH, 4 MEDIUM + 4 LOW | corrupt receipt misnamed; trial-dir mode; ONBUILD heredoc; CI coverage hole |
| 9 | **APPROVE — 0 C / 0 H / 0 M / 3 LOW** | merge criterion met |

After review 9 the orchestrator closed two of its three LOWs directly (see
"Closed after review 9").

## What was fixed

### Provider route and spend gate (`scripts/provider_preflight.py`, `config/provider_route*.json`, paid workflows)

- Route pinned to `deepseek/deepseek-v4-flash-0731` on `deepinfra` only
  (fp8, $0.06/M in, $0.18/M out). The earlier `relace` route was fp4 — a
  quantization confound against the fp8 baseline
  (`fp_a18b46594c_prod0820_fp8_kvcache_20260402`).
- `expected_quantization` fail-closed (`provider_quantization_mismatch`);
  `served_endpoint` / `fingerprint_available` recorded; witnesses
  `served_build_unverified`, `served_quantization_unverified`.
- Funds-sufficiency preflight: `--expected-tasks` (wired from the planner's
  post-exclusion `task_count`), per-task token assumptions, safety factor;
  `funds_verdict ∈ {sufficient, insufficient, unbounded_key, pricing_unavailable}`.
  Balance privacy via coarse `funds_headroom_bucket` (`lt_1x … ge_10x`), not a
  ratio (a ratio was invertible to the balance).
- `PLANNED_TASK_COUNT` assertion in every paid workflow (`::error` +
  `SystemExit(1)` on mismatch).
- Model single source of truth: `config/benchmark_model.v1.json`; all seven
  consumers repinned and pinned by tests.

### Attestation (`scripts/attest_deepswe.py`)

- `PROVIDER_GATE_FIELDS` exact set-equality with the preflight receipt, plus
  a producer→consumer JOIN test so a new preflight field cannot silently
  desync.
- Bound errors: `provider_gate_funds_insufficient`,
  `provider_gate_funds_verdict_missing`, `provider_gate_expected_tasks_*`,
  `provider_gate_quantization_mismatch`.

### Terminal classification (`scripts/miniswe_gt_run.py`, classifier region only)

- Terminal chosen by exception **type** (MRO walk gated on the
  litellm/openai module root), not by substrings in messages. The `"status"`
  substring match that graded a git failure as `provider_failed` is gone.
- `OSError`/`SubprocessError` → `internal_error`; `Submitted` gated on the
  `minisweagent` root; `TERMINAL_EXIT_CODES["submitted"] = 0`.
- Patch-export failure is promoted to the run's terminal only when a
  submission was claimed and the earned terminal is not in
  `_NON_SUBMITTED_TERMINALS` (`budget_exhausted` keeps its exit 0).

### Receipt-consistency verifier (`scripts/verify_run_receipts.py`, NEW)

Reads a task's receipts against each other after every task job
(`tb2_miniswe_central.yml` `always()` step). Six checks; **UNKNOWN is never a
pass**; rc 1 = contradiction only, rc 2 = unresolved, receipt always written.

- Trial resolution: bounded `_TRIAL_GLOBS`, first depth wins,
  `AmbiguousTrialError` → rc 2; unified ancestor `_inside_a_trial` rule with
  `Path.resolve()` shared byte-for-byte with `tb2_report.py` and
  `diagnose_benchmark_run.py` (agreement test + AST hash); a candidate that
  resolves outside the root (symlink/junction) is never a search root.
- `CHECK_IDS` static; a check that raises is recorded `crashed: true`,
  counted in `checks_crashed`, and **main returns 2** (round 7: previously a
  crashed check became UNKNOWN and the job went green).
- `_int` is the only numeric conversion and rejects non-finite values
  (`json.loads` accepts `NaN`/`Infinity`; `int(nan)` raised into the crash
  handler).
- Exit precedence: contradiction (rc 1) is decided on disk and cannot be
  downgraded by an unwritable `--json`.
- Resolution refusals, all rc 2 with `task_id: null` and a
  `resolution_detail`: `no_trial_found`, `no_run_receipt` (a trial directory
  exists but wrote neither `gt-run.json` nor `miniswe_report.json` — the
  real run-35241999929 shape, which previously exited 0 with six UNKNOWNs),
  `ambiguous_trial`, `read_error` (a run receipt exists on disk but is
  unparseable or not an object; a healthy receipt beside it does not rescue
  it), `no_decidable_check` (both receipts parse but every check is UNKNOWN
  and none crashed — the third door to the same false pass).
- Trial-dir mode (root is the trial) reports what the trial wrote instead of
  "wrong path".
- Synthetic `_pier_tree` / `_dead_pier_tree` fixtures so every refusal branch
  executes on CI, where the untracked real trees do not exist (116 tests run
  with the real trees hidden; only the real-tree layer skips).
- AST guard: every literal or variable handed to `build_unresolved_receipt`
  is in `RESOLUTION_ERRORS` and named in the module docstring
  (`Assign` and `AnnAssign`).

### Workflow cross-read step (`tb2_miniswe_central.yml`)

- Root is `results/terminal-bench${JOB_NAME:+/$JOB_NAME}` (the Pier job
  directory). Branch order: rc 1 → "Receipt contradiction" (names
  `checks_crashed`), rc 2 → "Receipts unresolved" (names `resolution_error`
  and `checks_crashed`), any other non-zero → "Receipt checker did not run"
  (an exit the checker does not define, e.g. signal death), rc 0 without the
  receipt file → error. Absent-file suffix on every branch. Every non-zero
  path exits 1.

### TB2 planner: Alpine/musl exclusion (`tb2_miniswe_central.yml`)

Excluded tasks come from `config/tb2_unsupported_tasks.v1.json`
(`qemu-alpine-ssh`) ∪ a Dockerfile parse of the **final stage's** base image.
The parser is now BuildKit-faithful on every shape the reviewers threw at it:
heredoc bodies skipped (only on `RUN`/`COPY`/`ADD`, including `ONBUILD`-wrapped),
`<<-` indented terminators, quoted/escaped `<<`, `$((1<<3))`, `<<<`,
`\`-continuations joined with `\\[ \t]*$` semantics, comment and empty
continuation lines dropped without ending the continuation, `# escape=`
directive (top-of-file block, BOM-tolerant, unknown key ends the block,
duplicate falls back), lines split on `\n` only (Python's `splitlines`
invented stages on `\f`/`\x85`/`U+2028`), leading whitespace before `FROM`,
`ARG`-scoped `${VAR}` resolution. A Dockerfile with no `FROM` is kept and
warned (`Dockerfile unparsed`); an unresolved `$ARG` base is kept and warned.
`task_count` is computed after exclusions; the plan receipt carries
`excluded` and `unresolved`.

### Reporting and audit

- `scripts/tb2_report.py` (NEW): per-task table with model column, cost from
  manifest pricing (refuses to print `$0.00` silently), `--baseline` parser,
  bounded walks, non-finite values shown as `-` and excluded from totals.
- `scripts/gt_audit.py`: `attribution_red_features()` excuses
  `DELIVERY_REFUSAL_REASONS`; LSP no-op annotation
  (`scripts/lsp_no_op.py`, EXPECTED/UNEXPECTED/UNKNOWN/NOT_APPLICABLE);
  `oom_kill_during_index` requires rc −9 AND `initial_index_failed`.
- `scripts/diagnose_benchmark_run.py`: LSP annotation in stderr and step
  summary; bounded globs.

### Workflow composition

- `tb2_miniswe_engine.yml`: import guard fails fast naming `inline-engine`
  when `eval.gt_central_agent` is absent (it is absent on the pinned branch
  by design); `task_progress`/`merge` guarded on `plan` success; timeouts.
- `deepswe_miniswe_central.yml`: adapter is
  `eval.pier_gt_harness_adapter:PierGtHarnessMiniSwe246Agent` (the only one
  that exists); pip install before the guard; guarded progress job.
- `central_provider_free.yml`: ruff target guarded when the module is absent.
- `tb2_miniswe_central.yml`: `cohort_stage: subset` + `subset_tasks`;
  `summarize` runs `always() && needs.plan.result == 'success'` with a
  30-minute timeout.

## Closed after review 9 (orchestrator, TDD)

- `no_decidable_check` refusal (review-9 LOW-1): `{}`, `{"unrelated": 1}` and
  an other-schema object as `gt-run.json` now exit 2; one decidable check is
  enough to resolve. Tests: `test_a_run_receipt_that_decides_nothing_is_not_a_resolved_run[*]`,
  `test_one_decidable_check_is_enough_to_resolve_a_run`.
- AST guard reads `AnnAssign` (review-9 LOW-2):
  `test_the_refusal_guard_reads_an_annotated_constant_too`.

## Campaign 2 (2026-09-19): decisions 1-3, offline

Same method: TDD, disjoint-file Opus agents, adversarial review per round.
Reviews 10-15. Landed as `89d5494d` (code), `88fc821c` (manifest re-pin)
and `f28cdf99` (workflow-command escaping, round 4).

| Round | Review verdict | Headline |
|---|---|---|
| 1 | 1 CRITICAL + 1 HIGH + 2 MEDIUM + 4 LOW | restored full-suite step could never pass (`.githooks/`, `docs/historical-workflows/` deleted by `c464bc57`); attribution fix laundered dark reasons across records |
| 2 | 1 CRITICAL + 3 HIGH + 6 MEDIUM + 5 LOW | `test_swelive_corpus.py` aborted collection on a clean checkout (corpus never merged onto this lineage); `::warning` lines carried unescaped model-writable bytes into the Actions command parser; auto-push hook as tracked content; stale hook digest |
| 3 | **APPROVE - 0 C / 0 H / 0 M / 3 LOW** (one MEDIUM outside the set, fixed in round 4) | merge criterion met |
| 4 | reviews 13/14/15: 2 MEDIUM -> 1 HIGH (escape-expansion arithmetic) -> clean staged set; CRITICAL found upstream in `gt_audit.py` | one shared escaper (`scripts/gh_annotations.py`) for every workflow-command line, bounded per field, module set discovered by walk; landed `f28cdf99` |
| 5 | in progress (review 16 pending) | `gt_audit.py::render_report` printed raw container-written fields to the runner's stdout in both paid workflows (the review-11 class, one module upstream, invisible to a `::`-literal guard) - every artifact-derived field now escaped, multi-line `quote` indented per physical line with a 20-line budget, column-zero backstop, end-to-end sink test; diagnose step-summary cells bounded then pipe-escaped; stream-safe emitter shared. **Record correction:** commit `99ebf5c5` (subject "docs: record round 4") also carries `scripts/gt_audit.py` and `tests/test_gt_audit_report_sanitised.py` - they were staged by the round-5 agent when that docs commit ran and were swept in; the message does not describe them. Not rewritten (already on both remotes); reviewed under review 16. |

What changed:

- `gt_engine/indexer.py`: own-cgroup resolution (v1+v2) with ordering
  identical to `gt_harness.cgroup.memory_snapshot`, pinned by an agreement
  test (double-`cgroup2`-mount and cgroup-namespace fixtures); a kernel
  without `memory.peak` keeps its ceiling; unreadable `memory.current` is no
  longer `limit=0`; `limit_state`/`cgroup_version`/`headroom_basis` on every
  refusal and receipt; amend floor scales with parent size (11 nodes:
  178,438,144 -> 67,289,088). Inside a cgroup namespace nothing changes -
  HEAD already read the task cgroup there; a 256 MiB container with 144 MiB
  resident still refuses under the 128 MiB reserve (handoff defect 7's true
  shape; needs container memory, not code).
- `gt_engine/attribution.py`: designed delivery-budget refusals are
  `SUPPRESSED_WITH_REASON` unless any dark reason exists on the feature, in
  any arrival order; every reason survives on the record. Status identical
  to HEAD on every local artifact; reasons set-equal except refusals now
  survive onto higher-status records (intended). Tracked fixture proves the
  delta against HEAD's module in CI.
- `scripts/miniswe_gt_run.py`: `command_descendant_receipt_missing` and
  `command_descendants_not_reaped` are witnesses when the workspace holds
  work, fatal only on a pristine tree, raised after publish; three
  consecutive gaps -> terminal `containment_lost`, exit 0, workspace graded.
  Verifier: seventh check `containment_gap_reported`; every `::` line
  escaped (bound 512, then percent/CR/LF); gap names whitelisted;
  `truncated` => WARNING.
- `.github/workflows/deepswe_gt_harness_product.yml`: merged back from
  `ba51aa97` with the 921bec20 pin step and the workflow lint kept;
  `workflow_call`/`dispatch` only; shipped content restored (`.githooks/`
  with opt-in auto-push and re-derived digests, `docs/historical-workflows/`
  as the exact FS-023 blob LF-pinned, corpus task `cyclotruc__gitingest-94`);
  `--collect-only` runs first. Supported set closed at 11 workflows; 21
  lanes archived to `.github/workflows-archive/` as pure renames.
- Full suite on the final tree: one failure,
  `test_repository_snapshot_and_ci_are_wired`, red only in a dirty worktree
  (validator scans untracked scratch), green on the staged tree.

Residuals after campaign 2 (LOW, documented): `scripts/validate_failure_ids.py`
scans untracked paths; `.githooks/pre-commit`'s failure gate self-disables
off its recorded HEAD (inert by design - decide whether to keep it);
`indexer.py` resolver docstring says "same parse" where it means "same parse
on well-formed input".

## Landed

- **Commit `07a16e58`** on `codex/gt-921bec20-union-smokes` (2026-09-19),
  pushed to `baliharneet7` and `fork`. Post-commit closure guard
  `tests/test_product_acceptance.py`: 14 passed. `HEAD:gt_engine` =
  `22daf78b80d74a0524de36c96d2060d411bdf5a5`.

## User decisions, 2026-09-19

1. YES - re-pin the GT source to fix the indexer OOM and the attribution
   dark-trigger category.
2. YES - fix the `command_descendant_receipt_missing` policy so a committed
   patch is not discarded.
3. YES - restore the 346-line `deepswe_gt_harness_product.yml` and close the
   supported-workflow set.
4. **NO runs.** No paid dispatch and no online test of any kind. GT is to be
   fixed architecturally with everything mocked and stubbed.

## Verification state

- Full suite (`tests/`, minus the corpus file, the post-commit closure guard
  and five deselected tests that need live artifacts) has produced **the same
  12 pre-existing failures and nothing else** after every round since round 2:
  `test_failure_id_validator` ×1, `test_failure_ids` ×4,
  `test_gt_finalstand` ×4, `test_product_workflow` ×3. Nine are environmental
  (no `.githooks/`, missing local artifacts); three are branch-composition
  contracts (commit `c7e5d424` gutted `deepswe_gt_harness_product.yml`
  346→93 lines; supported-workflow set 7 vs 32 present). None is touched by
  this work.
- `tests/test_product_acceptance.py` (`source_closure_differs_from_head`)
  fails on any dirty tree by design; it is run after the commit.
- ruff clean on every file this campaign touched.

## What is left

### LOW residuals (accepted, documented)

1. Test files exceed the 800-line style ceiling:
   `tests/test_verify_run_receipts.py` (~2.7k), `tests/test_tb2_gt_smoke_workflow.py`
   (~1.6k), `tests/test_tb2_report.py` (~1.3k). Natural seams exist (round
   banners). Split in a follow-up, not under active review.
2. `_trial_task_id` splits a flat `amoffat__sh-744/` directory (no hash) at
   the last `__`. Unreachable from the shipped emitter
   (`gt_harness/runtime_receipts.py` raises `task_id_required`, so
   `gt-run.json` always names the task) and TB2 ids carry no `__`; pinned by
   a test that documents it.
3. `tb2_report.has_metrics` keys off the presence of `gt-run.json`, not on
   whether its numbers were finite; a receipt full of `NaN` counts as "has
   metrics" with every column `-`.
4. `find_progress` parses the harness JSON tree before the strict receipt
   read raises — wasted I/O on a refusal path, harmless.
5. `diagnose_benchmark_run` prefixes reach depth 0/1/2 only.

### Open decisions (need the user, not code)

1. **Re-pin the GT source** to fix two defects that live in pinned files and
   cannot be fixed from the workflow: the OOM in `gt_engine/indexer.py`
   (`GT_INDEX_MEMORY_HEADROOM_INSUFFICIENT` refused 9 graph refreshes under
   TB2 cgroups; handoff defect 7) and the dark-trigger category in
   `gt_engine/attribution.py`. Editing them breaks the 921bec20 pin
   (`GT_SOURCE_OBJECT_MISMATCH`), which was tried and reverted (`80044a4a`).
2. Whether to restore the 346-line `deepswe_gt_harness_product.yml` from
   `ba51aa97` (merge, not revert) and extend/close the 7-workflow supported
   set — the three branch-composition test failures.
3. Handoff defect 3: `command_descendant_receipt_missing` (`miniswe_gt_run.py`)
   kills a run whose work is already committed (`amoffat__sh-744`,
   `committed_patch_bytes: 4660`); 2 of 4 SWE-Live tasks died this way.
   Needs a policy decision on whether a missing containment receipt is fatal
   when the patch is on disk.
4. Handoff defect 5: `total_cost` is 0.0 against 22.8M input tokens — tokens
   are metered in the GT receipt but do not reach the Pier/Harbor receipt.
   `tb2_report.py` now computes cost from manifest pricing, which is the
   workaround, not the fix.
5. Handoff defect 6: ~10% no-tool-call responses (`FormatError` →
   `GT_PROVIDER_MALFORMED_RESPONSE`) burn turns against `STEP_LIMIT: 100`.
   Model behaviour, not harness; visible in the report.
6. Handoff defect 4: `cfn-lint-3764`'s gold patch does not resolve in its
   image (not ours; the pre-spend canary refused at zero spend).

### Next steps, in order (revised after the decisions above)

1. DONE - commit `07a16e58`, closure guard passed, pushed, pin intact.
2. **Campaign 2, offline only**, same method (TDD, disjoint-file Opus agents,
   adversarial review per round, exit at nothing above LOW):
   - (a) re-pin the GT source: fix the cgroup memory-headroom read in
     `gt_engine/indexer.py` and the dark-trigger category in
     `gt_engine/attribution.py`; regenerate `source_object_ids`; update every
     pin consumer; prove with mocked cgroup files and receipts.
   - (b) `command_descendant_receipt_missing`: a missing containment receipt
     must not discard a patch that is already committed; policy chosen from
     the reconnaissance options and proven on the real `amoffat__sh-744`
     artifact copy.
   - (c) restore `deepswe_gt_harness_product.yml` from `ba51aa97` as a merge,
     close the supported-workflow set, make the three branch-composition
     tests pass.
3. Commit and push after each clean review; update HAR-88's status board.
4. No workflow dispatch and no provider call until the user explicitly
   authorises spend. Comparison targets stay the frozen local TB2 GT-off
   baseline (66/89) and the official DeepSWE v1.1 `deepseek-v4-flash` row
   (pass@1 0.5332). GT-off is never run by us.
