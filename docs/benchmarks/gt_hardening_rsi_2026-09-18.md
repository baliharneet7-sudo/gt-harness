# GT harness hardening — the complete record (2026-09-18 → 2026-09-19)

**Verdict: offline is done; the harness is ready for online.** Every claim in
this document was proven with mocks, stubs, real-artifact copies and fresh
clones — **no provider call, no GitHub dispatch, no Docker, zero spend.**
Nothing runs online until the user authorises spend.

Ticket: **HAR-88** (`done_and_dusted`) mirrors this file; this file is the
source of truth. Worktree `D:\w\t`, branch `codex/tb2-gt-union-921bec20`,
pushed as `codex/gt-921bec20-union-smokes` on remotes `baliharneet7` and
`fork`. Base commit `a03ad260`. Delta through `8272fce9`: 91 files,
+21,042 / −335.

---

## 1. What this was

After roughly $700 and eight months without a benchmark result, and after
the 2026-09-17 smokes died on infrastructure, the user redirected the work:
find the gaps in GT, fix them with Opus agents, review adversarially,
iterate until nothing above LOW remains, and prove everything offline. The
harness had to stop being able to report a false pass, a false model, a
false quantization, or a silently shrunk task cohort — and had to stop
losing graded work to its own infrastructure.

## 2. Method

- **Orchestrator** (Fable 5.1) → per round, two to four **Opus fix agents**
  on disjoint files → full pytest suite → **Opus adversarial reviewer** who
  reproduces findings on copies of real artifact trees
  (`.tmp-swelive-35249057348`, `.tmp-swelive-35241999929`,
  `.tmp-swelive-35238155998`, the `.research/` attribution traces) rather
  than reading diffs → next round.
- **Exit criterion per campaign:** a review reporting nothing above LOW.
- **TDD everywhere:** failing test first, fix, both outputs shown.
- **Pinned source objects** (`gt_engine/`, `gt_harness/`, `eval/`,
  `vendor/`, `nano/`, `gt_finalstand/`, `pyproject.toml`, `conftest.py`)
  were untouched in campaign 1; campaign 2 edited **only**
  `gt_engine/indexer.py` and `gt_engine/attribution.py` by the user's
  explicit decision and re-pinned the manifest.
- Nineteen reviews in total. Approvals: 9 (campaign 1), 12 (campaign 2
  round 3), 19 (campaign 2 round 5). Every commit reviewed before push
  except one docs commit that swept in staged code (§9).

## 3. Commits, oldest first

| SHA | What |
|---|---|
| `07a16e58` | Campaign 1: receipt verifier, fp8 route + funds preflight, BuildKit-faithful planner exclusion, type-based terminal classifier, LSP no-op annotation, reporting tools. |
| `4c7eaf81` | Record. |
| `89d5494d` | Campaign 2 rounds 1–3: cgroup-true index headroom, honest attribution, gradable containment loss, product workflow restored with its shipped content, workflow set closed. |
| `88fc821c` | Manifest re-pin: `source_object_ids.gt_engine` = `9d987079019f523035d7e276a551952e2048566a`; `gt_source_commit` stays `921bec20`; `gt_source_patch_commit` = `89d5494d`. |
| `e023467f` | Record + handoff. |
| `f28cdf99` | Round 4: one escaper for every workflow-command line (`scripts/gh_annotations.py`), bounded per field, guarded module set discovered by walk. |
| `99ebf5c5` | Docs commit that **also carries** the first `gt_audit.py` sanitisation pass (staged by an agent when the commit ran; see §9). |
| `604a6289` | Record correction for `99ebf5c5`. |
| `1a0d1084` | Round 5: `gt_audit.py` report and diagnostics summary cannot carry a workflow command or a forged table row; shared `emit_line`; diagnose path-launchable. |
| `f089cd2e` | Record. |
| `07659df3` | Lint on the last three touched test files. |
| `bb0736f6` | **Readiness fix found by the final check-up:** product workflow fetches the fixture commits through `fixtures/*` tags before pinning them by SHA. |
| `15245280`, `8272fce9` | Record of the final check-up and the definitive result. |

Tags on both campaign remotes, **never to be deleted**:
`fixtures/har41-e56c7ef1` → `e56c7ef17eaffee36c80ff4dde4f0cd3991c4dcd`,
`fixtures/har64-7bbbc9d0` → `7bbbc9d0b7f02f8cdaab79ad82ee86884b738eb5`.

## 4. What changed, by area

### 4.1 Model, provider route, spend gate
- Model single source of truth `config/benchmark_model.v1.json`:
  `deepseek/deepseek-v4-flash-0731`, provider `deepinfra` only, **fp8**,
  $0.06/M in, $0.18/M out. The earlier `relace` route served **fp4** — a
  quantization confound against the fp8 baseline
  (`fp_a18b46594c_prod0820_fp8_kvcache_20260402`). All seven consumers of
  the model string are repinned and pinned by tests.
- `scripts/provider_preflight.py`: `expected_quantization` fails closed
  (`provider_quantization_mismatch`); `served_endpoint`,
  `fingerprint_available`, witnesses `served_build_unverified` /
  `served_quantization_unverified`; **funds-sufficiency** gate sized by
  the planner's post-exclusion `task_count` with a coarse
  `funds_headroom_bucket` (a ratio was invertible to the balance).
  `PLANNED_TASK_COUNT` assertion in every paid workflow.
- `scripts/attest_deepswe.py`: exact set-equality with the preflight
  receipt plus a producer→consumer JOIN test; bound errors for funds,
  expected-tasks and quantization mismatches.

### 4.2 Terminal classification (`scripts/miniswe_gt_run.py`)
- Terminal chosen by exception **type** (MRO walk gated on the
  litellm/openai module root), never by message substrings. The `"status"`
  substring that graded a git failure as `provider_failed` is gone.
- Patch-export failure is promoted to the run's terminal only when a
  submission was claimed; `budget_exhausted` keeps exit 0.
- **Containment policy** (campaign 2): `command_descendant_receipt_missing`
  and `command_descendants_not_reaped` used to raise inside a `finally`,
  skipping publish and exiting 5 so harbor errored the trial and the
  verifier never collected a patch that was already committed (run
  35256147148, 4,660 bytes graded as empty). Now: a witness when the
  workspace holds work (`capture_complete: false`, gap named,
  `submission_patch_state` recorded), fatal only on a pristine tree and
  raised after publish; three consecutive gaps end the run with terminal
  **`containment_lost`, exit 0**, so the workspace is graded. The
  sub-case (`worker_start_failed` vs `containment_unwitnessed`) is
  detected from the interpreter's own bytes in the shared spool.

### 4.3 Receipt-consistency verifier (`scripts/verify_run_receipts.py`, new)
Runs after every TB2 task job over the Pier job directory. Seven checks;
**UNKNOWN is never a pass**; rc 1 = contradiction only, rc 2 = unresolved,
receipt always written, WARNINGs annotated in the job log.
- One ancestor `_inside_a_trial` rule shared byte-for-byte with
  `tb2_report.py` and `diagnose_benchmark_run.py` (agreement test + AST
  hash); a symlink/junction escaping the root is never a search root.
- A crashed check is `crashed: true`, counted, **rc 2** (it used to become
  UNKNOWN and the job went green). `_int` is the only numeric conversion
  and rejects `NaN`/`Infinity`. A contradiction cannot be downgraded by an
  unwritable `--json`.
- Refusals, all rc 2 with `task_id: null`: `no_trial_found`,
  `no_run_receipt` (a trial dir that wrote nothing — the real run
  35241999929 shape, previously rc 0 with six UNKNOWNs), `ambiguous_trial`,
  `read_error` (a receipt on disk but unparseable), `no_decidable_check`
  (receipts parse but decide nothing). Every branch runs on CI from
  synthetic fixtures; an AST guard binds every code to `RESOLUTION_ERRORS`.
- Workflow cross-read step: rc 1 → contradiction, rc 2 → unresolved, other
  non-zero → "checker did not run", rc 0 without the file → error; every
  non-zero path fails the job.

### 4.4 TB2 planner: Alpine/musl exclusion (`tb2_miniswe_central.yml`)
`config/tb2_unsupported_tasks.v1.json` ∪ a BuildKit-faithful parse of the
Dockerfile's **final stage**: heredocs only on `RUN`/`COPY`/`ADD` (incl.
`ONBUILD`), `<<-`, quoted/escaped `<<`, `$((1<<3))`, `<<<`,
`\`-continuation with `\\[ \t]*$` semantics, comment and empty continuation
lines dropped without ending the continuation, `# escape=` directive
(BOM-tolerant, unknown key ends the block, duplicate falls back), lines split
on `\n` only, leading whitespace before `FROM`, ARG-scoped `${VAR}`. No-FROM
and unresolved-ARG Dockerfiles are kept and warned. `task_count` is computed
after exclusions; the plan receipt carries `excluded` and `unresolved`.

### 4.5 GT engine (campaign 2, authorised pinned edits)
- `gt_engine/indexer.py`: the headroom guard read a hard-coded
  `/sys/fs/cgroup` (v2 only) and turned an unreadable `memory.current` into
  `limit=0`, refusing graph refreshes on a missing file rather than missing
  memory (run 35262214538: `limit=0..12804096` vs `need=178438144`, an
  11-node parent priced at 170 MiB). Now it resolves the process's own
  controller (v1 and v2) with ordering **identical** to
  `gt_harness.cgroup.memory_snapshot` (agreement-tested on the reference's
  fixtures plus double-`cgroup2`-mount and cgroup-namespace cases); a kernel
  without `memory.peak` keeps its ceiling; `limit_state` / `cgroup_version`
  / `headroom_basis` ride on every refusal and receipt; the amend floor
  scales with parent size (11 nodes: 178,438,144 → 67,289,088; 15,600 and
  above unchanged). Inside a cgroup namespace (the benchmark's case) nothing
  changes — HEAD already read the task cgroup there. A 256 MiB container
  with 144 MiB resident still refuses under the 128 MiB reserve: that is
  handoff defect 7's true shape and needs container memory, not code.
- `gt_engine/attribution.py`: a designed delivery-budget refusal
  (`boundary_claim_ceiling`, `localization_task_ceiling`, …) reached the
  audit projection as an eligible `feature.evaluated` row and was labelled
  `TRIGGERED_DARK`. Refusals are now accumulated per feature and resolved
  in a post-pass: any dark reason wins and every reason survives in any
  arrival order; a feature whose only dark-side evidence is a designed
  refusal is `SUPPRESSED_WITH_REASON`. Status is identical to HEAD on every
  local artifact; reasons are set-equal except that a refusal now survives
  onto a higher-status record (intended). A tracked fixture proves the delta
  against HEAD's module in CI. The audit-side excuse in `gt_audit.py` stays
  as defence in depth.

### 4.6 Workflow-command and report safety (campaign 2 rounds 4–5)
The GitHub Actions runner parses **every** stdio line for `::` commands;
several tools printed container-written bytes into that stream.
- `scripts/gh_annotations.py` (new): `gh_escape` (bound 512 on the raw
  field, then `%`/`\r`/`\n` escaped; `:`/`,` too for properties),
  `gh_command`, `gh_command_escaped`, `gh_verbatim` (a caller-defect trap
  whose line limit is derived from the measured worst escaped field —
  1,550 × 8 + 256 — after the original 4,096 ignored the 3× escape
  expansion and let a percent-dense field crash the renderer), and
  `emit_line` (never raises on a codepage it cannot spell).
- `scripts/verify_run_receipts.py`, `scripts/diagnose_benchmark_run.py`,
  `scripts/provider_preflight.py`, `scripts/gt_task_visibility.py` all
  build their `::` lines through it; the diagnostics renderer is contained
  per row with a fixed-text fallback; the `GITHUB_STEP_SUMMARY` table cells
  are bounded, backslash-escaped **before** pipe-escaped (verified against
  python-markdown, markdown-it-py and mistune plus a 20k-case fuzz), and
  backticks are replaced, not escaped.
- `scripts/gt_audit.py::render_report` printed raw container-written
  fields (task name, stop reason, agent error, ledger status/quote,
  capability evidence) to stdout in both paid attestation workflows —
  invisible to a `::`-literal guard because the module owns no such
  literal. Every artifact-derived field is now escaped and bounded, a
  leading `::` after any blank or list marker is rewritten to `%3A%3A`
  (structural, because whether the runner trims leading whitespace cannot
  be settled offline), the multi-line ledger quote keeps its lines under a
  16-space indent with a 20-line budget, a backstop rewrites rather than
  shifts, and an end-to-end sink test drives `main()` with the payload in
  every field. Guard ⊇ test oracle, proven over 341 prefix combinations;
  stubbing the guard or the source fix each fails a named test.
- An AST guard walks `scripts/**` and `gt_engine/**`, counts command
  literals (including the bare-`"::"` f-string head), refuses `+`/`%`/
  `.format`/`.join`-built commands, and requires every discovered module to
  be listed. Its stated limit: it cannot see a command printed without a
  `::` literal (that is why `gt_audit` needed its own sink test).

### 4.7 Product workflow and shipped content
- `.github/workflows/deepswe_gt_harness_product.yml` merged back from
  `ba51aa97`: immutable product pins, pinned checkouts, producer identity,
  lineage, failure IDs, RED evidence, provider-free arms, verified producer
  staging, **the full suite** — keeping the 921bec20 object-pin step and
  the workflow lint; `workflow_call`/`dispatch` only; no concurrency group
  (it would have made three callers on one ref cancel each other).
- The content the suite reads is tracked again: `.githooks/` (auto-push
  now **opt-in** via `GNX_AUTOPUSH=1`, refused on `main|master|release/*`;
  receipt digests re-derived and asserted), `docs/historical-workflows/`
  (the exact FS-023 blob, LF-pinned because the finalstand hasher reads raw
  bytes), and the swelive corpus task `cyclotruc__gitingest-94` (never
  merged onto this lineage; its absence aborted collection with zero tests
  run). A cheap step runs `--collect-only` and the formerly-failing tests
  before the 30-minute suite.
- Supported workflow set closed at 11: `central_provider_free.yml`,
  `deepswe_cache_images.yml`, `deepswe_gt_harness_product.yml`,
  `deepswe_gt_harness_product_p0731.yaml`, `deepswe_miniswe_central.yml`,
  `swebench_live_lite_full.yml`, `swelive_gt_harness_paid.yaml`,
  `task_progress.yml`, `tb2_cache_images.yml`, `tb2_miniswe_central.yml`,
  `tb2_miniswe_engine.yml`. Twenty-one superseded lanes (including the only
  scheduled workflow, which ran unattended with a secret, and every GT-off
  baseline lane) moved to `.github/workflows-archive/` as pure renames.
- **Fixture commits** `e56c7ef1` (HAR-41) and `7bbbc9d0` (HAR-64) sit on a
  side lineage reachable from no branch, tag or remote ref; they existed
  only as dangling objects in this worktree, so a fresh CI checkout could
  not have fetched them and the provider-free gate that fronts every paid
  lane would have gone red on its fixture step. Found by the final offline
  check-up in a `--no-local` clone; fixed by the `fixtures/*` tags and a
  refspec fetch before the SHA pins (`bb0736f6`).

### 4.8 Reporting and audit
- `scripts/tb2_report.py` (new): per-task table with model column, cost
  from manifest pricing (refuses a silent `$0.00`), baseline parser,
  bounded walks, non-finite values shown as `-`.
- `scripts/gt_audit.py`: delivery-refusal excusal, LSP no-op annotation,
  `oom_kill_during_index` requires rc −9 AND `initial_index_failed`.
- `scripts/diagnose_benchmark_run.py`: LSP annotation, bounded globs,
  launchable by path with the repository root resolved **before** an
  installed older `gt_engine` can shadow it (a real hazard on this machine).

## 5. Every review, in one table

| # | Verdict | What it found |
|---|---|---|
| 1 | 1 C | attestation exact set-equality vs 8 new preflight fields |
| 2 | 1 C + 4 H | verifier step pointed one level above Pier receipts |
| 3 | 3 H | phantom `*_count` keys; unbounded rglob; test resolved `$root` itself |
| 4 | 2 H | `except OSError` missed `UnicodeDecodeError`; `_trial_roots` expanded a checkout |
| 5 | 1 H | `_inside_a_trial` parent-NAME rule rejected depth-2 SWE-bench trials |
| 6 | 2 H + 1 M | crashed check → rc 0; `NaN` crashed `_int`; joiner ate `#` lines |
| 7 | 1 H + 1 M + 4 L | bare trial dir counted as resolved → rc 0; joiner not BuildKit-faithful |
| 8 | 4 M + 4 L | corrupt receipt misnamed; trial-dir mode; ONBUILD heredoc; CI coverage hole |
| **9** | **APPROVE** (3 L) | campaign 1 done |
| 10 | 1 C + 1 H + 2 M + 4 L | restored full-suite step could never pass (`.githooks/`, `docs/historical-workflows/` deleted by `c464bc57`); attribution laundered dark reasons across records; cgroup receipt lied on fallback |
| 11 | 1 C + 3 H + 6 M + 5 L | `test_swelive_corpus` aborted collection on a clean checkout; unescaped model bytes reached the Actions command parser; auto-push hook as tracked content; stale hook digest |
| **12** | **APPROVE** (3 L; 1 M outside the set) | campaign 2 rounds 1–3 done |
| 13 | 2 M + 3 L | composed-line bound could truncate the host verdict; guard module list hand-typed |
| 14 | 1 H + 2 M + 3 L | line limit ignored 3× escape expansion → renderer crash on adversarial input |
| 15 | 1 C (outside the set) + 1 M + 2 L | `gt_audit.py` still printed raw container fields to stdout |
| 16 | 2 H + 1 M + 3 L | column-zero backstop shifted by a space (positional, untested); oracle blind to it |
| 17 | 1 M + 2 L | guard tested index 0 while parser/oracle test first non-blank |
| 18 | 1 M + 3 L | `_md_cell` escaped the pipe but not the backslash; backtick escape inert in a code span |
| **19** | **APPROVE** (3 L) | campaign 2 done |

## 6. Final offline check-up (2026-09-19)

| Gate | Result |
|---|---|
| Object pin (local replica of the CI gate) | all eight ids match HEAD |
| `validate_product_workflow` on both product workflows | `[]` |
| `workflow_lint` on the three paid lanes | 0 violations |
| RED-evidence producer check | `pass` |
| `pytest --collect-only` | exit 0, no collection errors |
| All 11 supported workflows | parse |
| ruff over every Python file changed since `a03ad260` | clean except one deliberate `B017` |
| **Entire suite (232 files, closure guard included) in a fresh `--no-local` clone of `bb0736f6` with the fixture tags** | **zero failures** — run as four foreground slices because the host reaps idle background runs under memory pressure; every file ran exactly once |

## 7. What online will tell us that offline cannot

Online-only by nature; the first dispatch answers them and the harness
fails closed on each:
- the pinned external checkouts (`harneet2512/groundtruth`, GitNexus,
  review-inbox) and the DeepSWE task-image pull in the product workflow;
- provider funds and the served fp8 build (`provider_preflight` refuses at
  zero spend on either);
- the runner's real whitespace handling of workflow commands (defended
  structurally, so it no longer matters).

## 8. Dispatch runbook (only after the user authorises spend)

1. `deepswe_gt_harness_product.yml` alone — zero provider calls; proves
   the checkouts, the fixture tags, the image cache and the full suite on a
   runner.
2. `tb2_miniswe_central.yml` with `cohort_stage: subset` and two or three
   `subset_tasks` at fp8 pricing (cents). Read, per task:
   `receipt-consistency.json` (rc and every check), `tb2-gt-smoke20-plan.json`
   (`excluded`, `unresolved`, `task_count`), the provider preflight receipt
   (`funds_verdict`, quantization), and `python -m scripts.tb2_report`.
3. Only then the 20-task smoke at p20. SWE-Live: one gate task; release
   the rest only on official grading + PASS attestation + diagnostic exit 0.
4. Count only `gt.benchmark_progress.v1` (`officially_graded`, `passed`,
   `infrastructure_failed`); a green job is not a graded task.
5. Compare TB2 against the frozen local GT-off baseline (66/89) and DeepSWE
   against the official v1.1 leaderboard `deepseek-v4-flash` row (pass@1
   0.5332). **Never run GT-off.** Step limit stays 100.

## 9. Operating rules learned (they cost real time)

- Commit **by pathspec** (`git commit -F - -- <paths>`) whenever an agent
  may have staged files: `99ebf5c5` swept in `gt_audit.py` under a docs
  message and was already pushed before anyone noticed.
- The `block-no-verify` hook rejects any command containing both
  `git commit` and a bare ` -n ` token (e.g. `tail -n 2`).
- The Bash tool halves backslashes in heredocs and `re.sub` interprets
  escapes in replacement templates; build backslash-bearing bytes from
  `chr(92)` and use slice replacement.
- The host reaps idle background runs under memory pressure; run long
  suites in foreground slices.
- Never trust a worktree for reachability: prove CI-visible state in a
  `--no-local` clone (that is how the fixture-tag blocker was found).
- Verify before claiming: two agents' "no-op on real data" claims and one
  "closed" claim were overturned by reviewers who reproduced them.

## 10. Residuals (LOW, accepted)

- Test files over the 800-line ceiling (`test_verify_run_receipts.py`
  ~3.4k, `test_tb2_gt_smoke_workflow.py` ~1.6k, `test_tb2_report.py` ~1.3k).
- `_trial_task_id` on a flat hash-less `amoffat__sh-744/` dir (unreachable
  from the shipped emitter; documented by a test).
- `tb2_report.has_metrics` keys off presence of `gt-run.json`, not the
  finiteness of its numbers.
- `scripts/validate_failure_ids.py` scans untracked working-tree paths, so
  its test is red in any dirty worktree (green on a clean tree).
- `.githooks/pre-commit`'s failure gate self-disables off its recorded HEAD
  (inert by design; decide whether to keep it).
- A leading IPv6 `[::1]` literal in a quoted transcript line is
  display-rewritten (deliberate; the JSON receipt keeps the bytes); one test
  documents a tighter cell bound than guaranteed; one duplicated assertion.
- `test_graph_publication_lock_serializes_two_real_processes` flaked once
  under load on Windows (`PermissionError` on a byte-range lock, code
  untouched since `97efb7f0`; CI is Linux/fcntl).

## 11. Decisions resolved and still open

Resolved by the user on 2026-09-19: (1) re-pin the GT source — done;
(2) containment-receipt policy — done; (3) restore the product workflow and
close the set — done; (4) **no runs of any kind** without authorisation.

Still open, none of them code we own: handoff defect 4 (`cfn-lint-3764`'s
gold patch does not resolve in its image), defect 5 (`total_cost` reads 0.0
because tokens do not reach the Pier receipt — `tb2_report.py` computes it
from pricing), defect 6 (~10% no-tool-call responses burn turns against the
step limit — model behaviour, visible in the report), defect 7's residual
(container memory).

## 12. How to resume

Read HAR-88's status board, then this file. Check `git status` in `D:\w\t`
and that both remotes are at the head this file names. Do not ask the user
to restate the model, source pin, verifier, parallelism or failure policy —
they are all here and in `config/`. Do not dispatch without authorisation.
