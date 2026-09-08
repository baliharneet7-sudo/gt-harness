# Handoff — read this, run the checks, then work

Written 2026-09-07. Supersedes `HANDOFF-2026-09-07-run-34095557374.md` for state.
Evidence and reasoning live in `ARCHITECTURE-IMPROVEMENTS.md`; this file exists
so you do not re-derive any of it.

**Do not summarise this file back to the user. Do not re-explain the fixes.
Start at "The next action".**

---

## The next action

**Run a codespace smoke on the amend path and compare it to the run below.**
7c landed; nothing about it is proven on a live run yet.

The pre-fix baseline to beat, final state of the 2026-09-07 run at `25a37a5f`:

```
invalidations 62 · publications 19
caller_coverage  recorded 16 / unavailable 46   (74% blind)
```

Success is `graph_build_mode` rows carrying `mode=incremental` with a non-empty
`amended` list, publications tracking invalidations, and the recorded share
rising. A run whose rows all say `mode=full` with
`reason=producer_lacks_amend_capability` means `GT_INDEX_BINARY` is not pointing
at a producer built from this source — that is the gate working, not a defect.

---

## Verify the state, do not trust this file

Each line is a fact and the command that proves it. Run them; do not re-derive.

| fact | check |
|---|---|
| producer amends in place, loses nothing | `go test -tags sqlite_fts5 ./internal/store/... ./cmd/...` in `vendor/gt-index-src` |
| product suite is green | `.venv/Scripts/python.exe -m pytest tests/ -q -p no:randomly` |
| one failure is PRE-EXISTING, not yours | `test_red_evidence_integration.py::test_repository_producer_inventory_routes_through_canonical_cli` fails at baseline — verify by stashing your changes before blaming them |
| `-file` IS now reached from product code | `grep -rn '"-file"' --include=*.py gt_engine/` -> `indexer.py` |
| the amend path is gated on a declared capability | `python -m pytest tests/test_index_incremental.py -q` |
| reverification fires and preserves proofs | `python -m pytest tests/test_obligation_reverify.py -q` |
| candidate queries gate on completeness | `internal/store/sqlite.go` → `queryAttachedCandidates`: `if complete != "1"` refuses |
| completeness is a GLOBAL claim | `cmd/gt-index/main.go:~713` `AnalyzeCHAThenRTAWithReachability(allCalls, ...)` — RTA reachability is whole-repo, so it is **not** derivable from a local edit |

---

## Blocker ledger

| # | blocker | state | commit |
|---|---|---|---|
| 1 | incremental destroyed 98% of the graph | closed | `043e14c6` |
| 2 | `nodes_fts` cleared with a statement its table type forbids | closed | `043e14c6` |
| 3 | graph identity no run could satisfy | closed | `1920a127` |
| 4 | history marker moved, destroyed the prompt cache | closed | `1920a127` |
| 5 | producer committed non-executable; refusals named nothing | closed | `da43ebcd` |
| 6 | `provider_manifest_count_mismatch` on every retried call | closed | `3f53b55c` |
| 7a | graph rebuilt instead of amended on every edit | closed | `25a37a5f` |
| 7b | caller queries refuse (authority tier) | **OPEN** — not on the Python path | |
| 7c | live path never calls `-file` | closed | this session |
| 8 | `obligation_reverified` never fired | closed | this session |

7a measured, one 20-symbol edit on the arktype graph:
`nodes 182,258 → 182,258 · overlay 178,421 → 178,421 · dangling 0/0 ·
inserted 0 / updated 20 / removed 0`. Was `181,200 → 3,810`.

7c measured end to end on the real arktype graph, codespace, 2026-09-08, with a
producer built from this source (`/opt/gtcand2`, `complete: true`, declaring
`incremental_amend_in_place`). One symbol appended to
`ark/json-schema/common.ts`:

```
full index          85.0s      amend  10.7s          (8x)
nodes           182,249 -> 182,250      edges  467,716 -> 467,714
resolution_symbols  3,816 -> 3,817      callsite overlay  19,744 -> 19,744
  of which common.ts    6 -> 7          every other file  3,810 -> 3,810
dangling native_id      0
result line   inserted 1 / updated 6 / removed 0 / symbols_reminted 7 / symbols_removed 6
graph_resolution_complete = 0, analysis_state = not_run
  reason incremental_reindex_requires_full_analysis
```

Read the last line as the design holding, not as a defect: the amend re-derives
one file and says so, and the producer's own candidate authority stays refused
until a full rebuild. The Python caller query does not read that flag.

### 7c, what landed

`MiniSweAdapter._build_frozen_graph` now calls `indexer.refresh_index_files`
whenever the request carries a parent graph and dirty paths. That copies the
published graph into a NEW revision directory, runs `gt-index -file` once per
changed path against the copy, and publishes it through the same certification
the full build uses.

The parent is never written to. A published graph is immutable and its manifest
pins its exact bytes, so amending in place would invalidate the certificate of
the graph readers are holding; retention keeps the parent as the one superseded
revision.

Every refusal falls back to the full rebuild and names itself on the receipt and
in the new `graph_build_mode` journal row: `producer_lacks_amend_capability`,
`incremental_parent_uncertifiable:<reason>`, `path_removed:<p>` (a delete or a
rename, which an amend cannot express), `config_input_changed:<name>`
(`tsconfig.json` and friends change how every OTHER file resolves),
`dirty_paths_exceed_limit:<n>` (`INCREMENTAL_MAX_DIRTY_PATHS = 8`, the measured
12.0s-per-file against ~115s crossover), and `amend_failed:<code>`.

**The capability gate matters more than it looks.** The certified `c3b9f16e`
accepts `-file` and its amend is the one that discarded 177,390 of 181,200
nodes, and its declared capability list is otherwise identical to a build that
amends correctly. So the producer now DECLARES `incremental_amend_in_place` in
`-build-info`, and the engine probes for that name and fails closed on anything
it cannot read. Flag presence proves nothing.

Producer change that came with it: `-file` no longer clears `resolution_symbols`
wholesale. Symbol identity (`gt.symbol.identity.v1`) is derived per file, so the
amended file's rows are deleted and re-minted and no other file's are touched.
Clearing the table made `gt_engine/contract.py` fall back to a locally derived
`gtsym1:` id, changing every contract digest in the repository, and left the
verification planner with no entities at all.

### Which producer runs where — this decides whether 7c can matter

| path | producer | amend active? |
|---|---|---|
| `deepswe_miniswe_central.yml` (the 113-task set) | built from `vendor/gt-index-src` of the evaluated ref, `GT_INDEX_BINARY` exported | **yes**, if the ref carries these changes |
| `deepswe_gt_harness_product_p0731.yaml` (paid 20-task attestation) | the vendored certified `c3b9f16e` | no — falls back, correctly |
| codespace smoke | whatever `run.sh` points `GT_INDEX_BINARY` at | yes, with a locally built producer |

The attested path cannot use the amend until the Route-B lineage covers a
producer that carries it, and that needs review packets that are groundtruth
commits under an owner directive — not something the harness can issue. The
benchmark path has no such pin: it builds the binary from source at run time.

### 8, what landed

`obligation_reverified` had produced 0 rows in every run ever recorded. The pass
was not unreachable — it ran on every edit and returned at its first line.
Candidacy came from `_affected_predicate_ids`, which needs the obligation's
English text to literally quote a filename; the invalidation that actually runs
is footprint-based and matches every edit. The two rules never intersected, so
proofs were destroyed by a rule whose members were never eligible for the rescue.

`GroundtruthController.note_edit` now returns the set it actually reset, and the
adapter builds reverification candidates from that. Two consequences:

- the pass runs, and a proof an unrelated edit discarded is re-established by
  re-running its recorded command instead of costing the model ~10 steps;
- `obligation_invalidation` reported the OPPOSITE of what happened. Its
  `proven_discarded`/`proven_surviving` were computed against the empty scope
  match, so it claimed every proof survived an edit the controller had already
  wiped. It is now computed against the applied set, with `scope_matched` kept
  beside it.

A skip now emits a row naming itself (`no_candidates`, `verify_execute_off`)
rather than returning in silence, which is what let zero rows read as "nothing
needed re-proving" for the life of the project.

### 7b, precisely

`graph_resolution_complete = 1` asserts candidates derived from whole-repository
CHA→RTA reachability. You cannot compute that from a local edit. Two honest
routes: make the global analyses fast enough per-edit, or add an explicitly
weaker authority tier that serves candidates **labelled** with the revision they
were proven at (rows already carry `ResolutionCallsite.RepositoryRevision` and
`AttachedCandidate.Revision`).

**Setting the flag without doing one of those is a false attestation. Do not.**

7b does not block 7c and does not block `caller_coverage`. `graph_resolution_complete`
has zero readers in Python: the caller query in `runtime_observation.py` reads
`CALLS` edges from SQLite directly, and coverage reports `unavailable` purely
because `EngineState.graph_current` is false. What 7b costs is the producer's
own `queryAttachedCandidates` authority, which refuses after any amend until a
full rebuild.

---

## Anti-patterns — each cost real time on 2026-09-07

1. **Fixing an unreachable path.** `-file` was fixed before checking callers.
   Grep for callers first.
2. **Crediting a fix without proving it ran.** A `caller_coverage` improvement
   was attributed to the producer fix; that code never executed in the run. Name
   the journal event that proves execution, or say "unattributed".
3. **Changing a pinned constant.** Two reverts (`SEALED_DELIVERY_BYTE_LIMIT`,
   the staleness markers). Read the assertion's rationale — in this repo it is
   written beside the test — before deciding a literal is stale.
4. **Deleting state under a live process.** `rm -rf /logs/gt-state` while the
   supervisor ran produced a `FileNotFoundError` report that read like a product
   defect. Kill, poll to zero, *then* delete.
5. **Reading stale artifacts.** `report.json` / `gt-run.json` / `gt-worktree.patch`
   survive across runs. Check mtimes before reading any outcome.
6. **Deleting without counting.** Two over-broad deletions (684 overlay rows;
   18,972 `unresolved_fact` rows matched by bare name repo-wide) were invisible
   until the result line reported `inserted/updated/removed`.

---

## Running a codespace smoke

Codespace `ominous-memory-6px974ppp9crw6x`, container `gtlive`, script `/logs/run.sh`.

- **`--product-source-sha` must be passed on the command line.** It defaults to
  `""`, and `issue_runtime_receipts` then raises `product_source_sha_invalid`,
  so the run reports ERROR at the finish line no matter how well it went. CI
  supplies it via pier's `--ak product_source_sha=`; the codespace script must
  pass the flag itself.
- Sustained `BadGatewayError` on `{"only":["relace"],"allow_fallbacks":false}` is
  intermittent gateway failure on ~120k-token requests, not an outage. Probe the
  pinned route directly before changing routing.
- Clean up graph copies. Four 870MB reproduction copies filled the disk to 100%
  mid-run.
- The candidate producer is staged at `/opt/gtcand/gt-index-linux-amd64`. The
  **vendored** binary stays the certified `c3b9f16e`: the Route-B contract binds
  it through a `lineage_exception` whose ancestry path and review packets are
  groundtruth commits under an owner directive. Do not re-point that chain at a
  locally rebuilt binary.

---

## The codespace — how to reach it and what is staged there

```
codespace   ominous-memory-6px974ppp9crw6x
container   gtlive              (gh codespace ssh -c <name> -- 'docker exec gtlive ...')
workspace   /work               product checkout, currently 25a37a5f
task repo   /app                arktype
logs/state  /logs               run.sh, run.log, gt-state/, report.json ...
journal     /logs/gt-state/arktype-json-schema-refs-dependencies/events.jsonl
producer    /opt/gtcand/gt-index-linux-amd64  (+ .build-info.json)
```

`/opt/gtcand` holds the **candidate** producer carrying the amend-in-place fix,
built from `25a37a5f` with identity ldflags (`complete: true`). `run.sh` points
`GT_INDEX_BINARY` at it. The vendored binary in the repo is deliberately the
older certified `c3b9f16e` — see "Running a codespace smoke" above.

Launch, stop and watch:

```bash
CS=ominous-memory-6px974ppp9crw6x
# stop cleanly: kill, poll to ZERO, only then touch state
gh codespace ssh -c $CS -- 'docker exec gtlive sh -lc "pkill -9 -f \"[m]iniswe\"; sleep 3; ps -eo cmd|grep -c \"[m]iniswe\""'
# launch
gh codespace cp -e -c $CS ./run.sh "remote:/tmp/run.sh"
gh codespace ssh -c $CS -- 'docker cp /tmp/run.sh gtlive:/logs/run.sh; docker exec gtlive chmod 755 /logs/run.sh; docker exec -d gtlive sh /logs/run.sh'
# read progress from the journal, never from report.json until session_closed
```

Disk runs ~75% of 32G. Each graph revision is ~900MB and retention keeps
live + 1. Delete reproduction copies under `/tmp` when done — four of them
filled the disk to 100% mid-run on 2026-09-07.

## The 2026-09-07 smoke — completed, submitted, and what it proves

Run at `25a37a5f`, step limit 300, candidate producer at `/opt/gtcand`.
It TERMINATED cleanly: `session_closed`, `final_state`, `exit_code 0`,
`terminal: submitted_unverified`, `research_valid: true`. Artifacts written
00:52:25-27 (check mtimes yourself before reading any of them).

```
1 obligation_reverified   0 rows                      still dark
2 unmet                   18 -> min 2 -> final 2      33 resets
3 steps                   230   vs GT-off's 166       +39%
4 cache                   96.2%   in 20,518,443 / cached 19,728,896
                                  uncached 789,547 / out 103,664
5 verifier reward         NONE - bare supervisor run, no official verifier
```

**On (5):** this path has no verifier, so `submitted_unverified` + exit 0 is the
correct terminal, not a failure. A reward requires the GitHub workflow. Do not
report a reward from a codespace run.

**Attributable win — the prompt cache.** Uncached input **789,547** against the
graded run's **5,117,500**: a 6.5x reduction on the tokens billed at full rate,
with the hit rate 85.0% -> 96.2%. This is `1920a127` (the history marker that
used to move and invalidate already-sent messages). It is attributable precisely
because it does not touch the graph path.

**Also new:** `exit_code 0` with a clean receipt. Every earlier codespace run
died at the finish line on `product_source_sha_invalid` because the launcher
never passed the flag.

**Confirms 7c, quantified.** 62 edits produced **19 publications**;
`caller_coverage` ended 16 recorded / 46 unavailable = **74% blind**, identical
to the graded run. Publications froze at 14 for ~25 minutes of continuous
editing and only caught up once the agent STOPPED editing. That is the
full-rebuild path losing to the edit rate, and it is not evidence about the
amend fix, whose code never executed.

## Standing constraints

- **Never run GT-off.** Not in a plan either. Baselines are frozen locally and on
  the public leaderboard (`deepseek-v4-flash` row only, never `-pro`).
- Instinct reviews work; it is not asked questions.
- Token spend is the metric, reported as input / cached / uncached / output —
  never dollars.
- One task proves nothing about outcomes. The leaderboard is 113 tasks × n_runs=4.
