# Handoff — read this, run the checks, then work

Written 2026-09-07. Supersedes `HANDOFF-2026-09-07-run-34095557374.md` for state.
Evidence and reasoning live in `ARCHITECTURE-IMPROVEMENTS.md`; this file exists
so you do not re-derive any of it.

**Do not summarise this file back to the user. Do not re-explain the fixes.
Start at "The next action".**

---

## The next action

**Blocker 7c: make the live path use incremental indexing.** Nothing else moves
the benchmark number until this lands.

```
gt_engine/miniswe_integration.py :: _build_frozen_graph
  → ensure_index_with_receipt(...)   # FULL index, every invalidation
```

`-file` is never called from product code. Confirm in one command:

```bash
grep -rn '"-file"\|run_incremental_index' --include=*.py gt_engine/ scripts/   # expect: nothing
```

The producer side is done and lossless (see ledger). What is missing is the
engine calling it.

---

## Verify the state, do not trust this file

Each line is a fact and the command that proves it. Run them; do not re-derive.

| fact | check |
|---|---|
| producer amends in place, loses nothing | `go test -tags sqlite_fts5 ./internal/store/... ./cmd/...` in `vendor/gt-index-src` |
| product suite is green | `.venv/Scripts/python.exe -m pytest tests/ -q -p no:randomly` |
| one failure is PRE-EXISTING, not yours | `test_red_evidence_integration.py::test_repository_producer_inventory_routes_through_canonical_cli` fails at baseline — verify by stashing your changes before blaming them |
| `-file` unreachable from product code | the grep above |
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
| 7b | caller queries refuse (authority tier) | **OPEN** | |
| 7c | live path never calls `-file` | **OPEN — start here** | |

7a measured, one 20-symbol edit on the arktype graph:
`nodes 182,258 → 182,258 · overlay 178,421 → 178,421 · dangling 0/0 ·
inserted 0 / updated 20 / removed 0`. Was `181,200 → 3,810`.

### 7b, precisely

`graph_resolution_complete = 1` asserts candidates derived from whole-repository
CHA→RTA reachability. You cannot compute that from a local edit. Two honest
routes: make the global analyses fast enough per-edit, or add an explicitly
weaker authority tier that serves candidates **labelled** with the revision they
were proven at (rows already carry `ResolutionCallsite.RepositoryRevision` and
`AttachedCandidate.Revision`).

**Setting the flag without doing one of those is a false attestation. Do not.**

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

## Standing constraints

- **Never run GT-off.** Not in a plan either. Baselines are frozen locally and on
  the public leaderboard (`deepseek-v4-flash` row only, never `-pro`).
- Instinct reviews work; it is not asked questions.
- Token spend is the metric, reported as input / cached / uncached / output —
  never dollars.
- One task proves nothing about outcomes. The leaderboard is 113 tasks × n_runs=4.
