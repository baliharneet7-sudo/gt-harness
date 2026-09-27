# GT attached-delivery campaign — progress record

Branch `integ/gt-attached` (from `canonical/gt-har90` @ b005a74e). Plan: `C:\Users\Lenovo\.claude\plans\i-want-you-to-witty-frost.md`.
Links: HAR-93 (delivery experiment), HAR-90 (canonical + MINISWE_INTEGRATION_DESIGN phases 1–3).

Legend: [ ] todo · [~] in progress · [x] done · [!] blocked / needs the user

## W2 — attached delivery (GitNexus `native_augment` pattern on canonical GT)
- [x] `gt_delivery_mode=push|attached` — declared CliFlag, consumed by `treatment_flags` (attached ⇒ SHADOW session; refuses with GT-off or a conflicting `--gt-mode`)
- [x] tools: 22 `gt-*` commands (core 8 in the prompt, rest via `gt-help`); every one of the 21 features mapped (`FEATURE_SURFACES`) and exercised on a real producer graph (`tests/canonical/test_attached_feature_coverage.py`). Initially 12 over the certified facades (`gt_engine/tool_server.py`), model-shaped renderer (`gt_engine/tool_render.py`), tier shown, no hashes, 6 KB cap, exit 0/1/2
- [x] warm server in the runner process (shares EngineState ⇒ per-edit freshness; refresh-before-query); stdlib wrappers with the URL baked in (credential-isolated env safe). No cold CLI fallback: the server lives exactly as long as the agent
- [x] grep/rg/ag/git-grep augmentation on the SAME observation (`gt_engine/grep_augment.py`), anchored to the agent's own identifiers, 2 KB cap, silent on no answer, deterministic
- [x] attached gate: session SHADOW (no pushed units, steers, catalog), `typed_actions` off (bash is the one tool surface), persistent plan off, submit gate + churn abort bypassed and journaled
- [x] prompt: stock mini-swe template + one short tool-reference section (`attached_system_section`)
- [x] report fields: `gt_delivery` (tool calls/by name, augment calls/hits/rate/bytes, `gt_bytes_delivered`, `gt_context_referenced` + method), `effective_step_limit`, `requested_step_limit`; push arm reports its delivered bytes too
- [x] dropped `gt_bytes_would_push`: push producers do not run in SHADOW, and running them only to count bytes would add per-action cost; the A/B compares arms directly
- [x] pay-per-intent compute: no per-action graph refresh / transaction-boundary amend in attached mode; the first tool/augment read amends (tested edit -> query)
- [x] graph failure in attached mode -> `attached_treatment_invalid`, agent keeps running (no startup abort)
- [x] `gt-calls`: per-call resolution from CANDIDATE_TARGET/SELECTED_TARGET edges (F5/F6/F7), cross-language candidates flagged
- [x] tests: `tests/test_gt_attached_unit.py` (40) + `tests/canonical/test_attached_delivery.py` (5, real gt-index graph)

## W1 — benchmark path (model-agnostic)
- [x] model/route/effort are launch inputs: hardcoded model tables removed from runner + preflight; one structural validator `gt_harness/provider_routing.py`; gateway runs still fail closed without a stated route
- [x] `GT_REASONING_EFFORT` (validated) replaces the muse-only special case; `temperature` is a declared launch knob
- [x] `scripts/resolve_baseline.py` — per-(model, effort) comparator from the public leaderboard trials; reproduces deepseek-v4-flash/max pass@1 0.5332 exactly
- [x] `config/deepswe_task_catalog_v1.json` — all 113 tasks, images pinned by registry digest, 20 bundle rows cross-checked byte-for-byte; task set == leaderboard's 113
- [x] `deepswe_gt_delivery_ab.yml` — interleaved push/attached × n_runs, catalog cohort, rendered route, aggregate with step-limit proof (in progress)
- [x] import-provenance pin re-derived per release: `scripts/rederive_import_manifest.py` (in-place, `--check`); pinned to 70969751; workflows/tests assert zero drift, not a literal (98d2c332)
- [ ] TB2 central still sets `GT_SOURCE_SHA 921bec20` in the workflow env (TB2 secondary)
- [x] GitHub accepts up to 25 `workflow_dispatch` inputs since 2025-12-04 (changelog) — the A/B workflow's 14 are fine

## W3 — hardening
- [x] producer re-certified: Route-B run 36290313967 @ec587ccc (VTA bound, nested defs, inline routes, 9cf513af) vendored with wheel a873f92a, blob-exact gt-index-src; `verify_producer_binding --enforce` VERIFIED (70969751)
- [x] inline route handler no longer reported `route_handler_unresolved`; answer carries `handler_kind` (producer ec587ccc)
- [~] lineage attestation extended with review packet `har90-certified-producer-ec587ccc` (gt-review-inbox)
- [x] stale canonical docs: `TYPED_SURFACE.md` (subprocess.run, revision identity, route_map middleware) + registry limitation string; [ ] re-render `HAR90_CANONICAL_SECTION.md`
- [x] real-repo provider-free smoke (`scripts/smoke_attached_real_repos.py`; adaptix, aiomonitor, awilix, abs, fd, csstree)
- [x] `gt-query` path (`hybrid_rank` facade) already fuses available sources with RRF (dense absence = omission, not all-or-nothing); the all-or-nothing defect is only in the push localization lane
- [x] efficiency: wheel `processes._stable_id_to_nodes` quadratic CAST join (40 s/call on adaptix) → output-identical shim 0.94 s, attached arm only; per-action working-tree snapshot cache

## W4/W5 — evidence & graduation (no paid run without the user)
- [ ] pre-registration doc
- [ ] provider-free acceptance on a clean checkout
- [ ] canary 1 task/arm → 10×2×4 → 113×4

## Cross-account GT-on (3 accounts x 3 benchmarks) - 2026-09-27
Accounts: harneet2512, hbali-stack, baliharneet7-sudo (each `<acct>/gt-harness`). GitHub dispatches only filenames registered on the default branch and runs the version on `--ref`, so each benchmark uses a filename already registered everywhere:

| benchmark | entry point (dispatch with `--ref integ/gt-attached`) |
|---|---|
| TB2 | `tb2_miniswe_central.yml` (all three) |
| DeepSWE | `deepswe_miniswe_central.yml` -> wrapper forwarding to `deepswe_gt_delivery_ab.yml` (all three) |
| SWE-Live Lite | `swelive_gt_harness_paid.yaml` (harneet2512); `swebench_live_lite_full.yml` wrapper (hbali-stack, baliharneet7-sudo) |

- [x] TB2: model/route/effort/temperature/step_limit/gt_delivery_mode are launch inputs; route rendered + certified per run; source SHA from the import manifest (no 921bec20); `OPENROUTER_NEW || OPENROUTER_API_KEY`; trial budget capped under the 360-min hosted ceiling; per-task `gt_delivery` (treatment_valid, step-limit match) via `scripts/annotate_gt_delivery.py`; failed gate no longer summarizes as 89 missing; summary labels a non-baseline model "context only"
- [x] DeepSWE: A/B gains `workflow_call`; model required; secret fallback; aggregator marks `treatment_invalid` legs (not scored) and fails on a leg run in the wrong arm
- [x] readiness blockers: stale hammer-test amend fake (missing `source_revision` kwarg) made 5 freshness tests fail on Linux and Windows since canonical b005a74e - fixed; A/B admitted to the closed workflow set
- [x] SWE-Live Lite: launch inputs, secret fallback, route attestation, 300-task catalog pinned by image digest (0 excluded, sha256 0013f6b7), sharding (<=256 legs), slot stagger, hosted-ceiling timeout; gt_audit names attached-mode withheld pushes
- [x] Linux readiness defect: the product lock pins mcp 2.1.1 (datacurve-pier), and the wheel imported mcp.server.fastmcp eagerly, so route_map/api_impact failed to import on Linux. Producer 93e2e86e (lazy create_server) certified by Route-B run 36298175850 and vendored (ab159952; pin 2dcfbb88); lineage 18/18 PASS
- [x] Linux verification (WSL, product lock, `pip install .`, GT_INDEX_BINARY): route/oracle/static/freshness suites and the previously failing recorded-content, plan-verification, recovery, producer-binding, runtime, amend-retention, supervisor and product-acceptance files all pass
- [x] `integ/gt-attached` @ 2dcfbb88 on harneet2512, hbali-stack, baliharneet7-sudo (no push-triggered workflows)
- [ ] dispatch: canary 1 task per benchmark (user's call); free-model rate limits unknown

## Findings recorded during implementation
- Certified wheel defect: `ON CAST(native_id AS INTEGER)` joins defeat indexes (processes.py:218, mcp/_graph_db.py:145, resolve.py:498/597) — `symbol_context` cost 50-72 s on a 489-file repo. Likely contributor to past push-arm timeouts; worth auditing old journals.
- Canonical bundle closure omitted two shipped modules (`taint_dataflow.py`, `shape_check_guard.py`) — fixed.
- F6: candidates exist as graph edges; `analysis.callable_values` reads an empty table (harness bug).
- `gt-tests` (covering selector) misses a caller-reachable test that `gt-impact` shows.
- Every past DeepSeek comparison was effort-mismatched: the only leaderboard deepseek-v4-flash row ran at `max`; our harness sent none.
- Akon's GitNexus "bare" arm (37.0%, gpt-5.6-terra med) matches the public leaderboard (0.3496) — its 68.4% is against a real stock level.
- Canonical `submitted_unverified` exits 0; the embed-bakeoff "exit 5 with a patch" is specific to its `gt_central_agent`.
- The 20-task product bundle cannot run a matched control or the full 113 — hence the catalog.

## Round 3: GT on the agent's own actions (44af8b6d, pin ee20bb8e)
Measured before (28 fixed-code tasks): 8/21 features reached the agent; 16 tool calls total; augment carried symbol context only.
- [x] grep block: F3 refs, F5/F6 resolution, F7 overrides (graph edges + name-level hierarchy fallback for Python/TS), F8/F18 routes/middleware/DI, F10 module, F13 co-change
- [x] edit block: changed functions + callers (F13/F4), tests reaching (F20), parse errors (F1), reached sinks (F19, 5 s budget), handled routes (F18)
- [x] failure block: failing test, innermost source frame's function, backward slice (F14-F17), repeated-failure note (F20)
- [x] attached task plan (not one of the 21): ledger + graph anchors + reaching tests, no provider call/baseline/gate; shown once, `gt-plan`
- [x] per-delivery feature tags; observer credits only carried features
- [x] F14/F15/F16 oracle tests (Go); Python persisted CFG strict xfail
- [ ] first5 x 3 benchmarks on ee20bb8e: TB2 36336290322, DeepSWE 36336203906, SWE-Live 36336250729
Found, not fixed:
- `_CATALOG_NOISE_RE` (task_contract.py) drops any requirement line containing sanitize/escape/injection as a CWE catalog row - hits the contract and the plan on security fixes.
- cfn-lint (SWE-Live 36322976462, solved): batch amend needs 3.35 GB vs 0.94 GB cgroup headroom (8 GiB max, 7.86 GB current), incremental fallback uncoverable -> graph stale after edits; attest fails the run on GT_GRAPH_REFRESH_FAILED.
- Local Windows producer (C:\gt-smoke-a6) fails 3 oracle tests (F1 nested defs x2, F18 routes) that pass on the vendored Linux producer.

## Round 4: feature-reach audit of runs 36336290322 / 36336203906 / 36336250729 (ee20bb8e)
Evidence: every delivered `[GT]` block parsed from the trajectories (`scripts/delivered_gt_evidence.py`), each shown caller/callee traced to its CALLS edge provenance, journal quiet traces, per-task graph applicability (`scripts/classify_feature_reach.py`).
- Reached (9 code tasks): F1/F21 substrate 9, F2 9, F4 9, F12 9, F13 9, F20 8 (tests reaching), F10 7, F3 6, F5 9 (meshed: 58% of 206 traced rows import/same_file/verified_unique), F7 3 (meshed type_flow/impl_method; aiogram 36/53 rows), F9 3, F8 1.
- Never reached: F6 (callable_value edges + VTA facts computed, no consumer), F11 (shadow-only, 30-104 computations/task), F14-F17 (failure trigger used shell rc; 26/30 failing runs exited 0 through `| tail`), F19 (taint budget eaten by the forced refresh), F18 (not in these repos).
- Cost: blocking amends 104-1,121 s per task (edit block forced refresh; grep refresh already in round 2).
- GT infra: aiomonitor startup index failed 3x "producer input superseded before publication" (edits during indexing) -> treatment invalid.
- Fixed (round 4): non-blocking passive reads (StaleView, hash-verified), edit block on the pre-edit graph + cumulative pre-image mapping, parsed-outcome failure trigger, graph-free Python slice, call-graph sink reach, F11 in the plan, empty plan withheld.

## Round 5: offline replay gate + fixes found with it (b39b0b3c)
- `scripts/replay_attached.py`: replays a recorded task through current code (no model/container). Pre-launch gate from now on.
- SWE-Live sitecustomize leaked into the agent's Python (PYTHONPATH inherited): "No module named 'groundtruth'" 18-124x per task on every SWE-Live task of rounds 2-3. Fixed (hook is a no-op outside GT's interpreter).
- Startup graph discarded as "superseded" when the agent edited during a frozen build (aiomonitor: no graph). Fixed in `_publish_candidate(frozen_input=True)`.
- Grep fallback for non-definition names from `properties_fts` (F3/F15); resolution mix line (F5/F6/F7 explicit); edit blocks for class-body edits, added definitions, test edits; slices via persisted CFG for non-Python; plan carries F11.
- DeepSWE image digest gate: backoff on public ECR 429 (run 36345273390 died there).
- Replay on the round-3 trajectories: features per code task 6-12 -> 6-17; GT time 104-1,121 s -> 2-5 s per task.
- Full runs relaunched on b39b0b3c: DeepSWE all 36346438031, TB2 full-89 36346440397, SWE-Live 1/2 36346442578, 2/2 36346444850.
- Open: F6 never reached (callable_value edges rarely touch searched symbols); `_CATALOG_NOISE_RE` drops security requirement lines (shared with the push contract, not changed); startup `initial_index_ready.elapsed_ms` is always 0.

## Log
- 2026-09-27: round 3 landed (44af8b6d, pin ee20bb8e) on all three accounts; SWE-Live first5 @5994b3ef 5/5 solved, red only on the cfn-lint amend refusal; stale DeepSWE rest15 @09ae8ff4 (queued for hours) cancelled.
- 2026-09-27: GT-on on 3 accounts x 3 benchmarks landed (54822a6b); producer 93e2e86e (mcp 2 import) certified + vendored (ab159952, pin 2dcfbb88); pushed to all three accounts.
- 2026-09-27: producer ec587ccc certified + vendored (70969751); import pin re-derived (98d2c332); producer CI profile identical to certified 1e83ea68 (pre-existing lint + 60 s Go-build fixture timeouts on ubuntu-3.11/windows), the one real regression fixed.
- 2026-09-26: committed a609ee28 (W2 core, routing, resolver, catalog, A/B workflow); extended catalog + lazy freshness + gt-calls; real-repo smoke running.
- 2026-09-26: worktree `D:\gt-attached` created; audit + plan approved; W2 core, W1 routing/resolver/catalog landed locally.
