# DeepSWE 20-task paid smoke - live status

All 20 tasks in ONE dispatch, stage `all-20`.

The two-stage split (gate-one, then remaining-19) still exists and is still the
safer default. It is not used here by choice: run 34257199043 already showed that
every gate passes and the agent loop runs all the way to its deadline, so a
canary now buys an extra hour of serialisation and nothing else. The 20 fan out
in parallel with `fail-fast: false`, in the identical pinned order and at the
identical per-task budget.

A superseded gate-one dispatch, run 34270553336, was cancelled at 19:44 while it
was still in the image digest gate. No task job had started, so nothing was paid.

| time (UTC) | event |
|---|---|

---


## What was fixed before this run

Run 34257199043 (gate-one, arktype) passed every gate, ran 86 minutes, made 250
completed model calls and executed 334 commands — and produced **no reward**.
Two separate causes, both now fixed.

### 1. A benchmark timeout was thrown away instead of graded

`scripts/miniswe_supervisor.py` maps an exhausted agent budget to exit 3.
`eval/miniswe_agent.py` re-raised that as `NonZeroAgentExitCodeError`, so Pier
recorded the trial as an exception:

```
"error_code": "runner_setup_or_execution_failed", "failure_class": "setup_failure",
"reward": null, "solved": null, "status": "ERROR"
```

A timeout is a result, not an infrastructure fault, and **both frozen GT-off
controls grade theirs**: Terminal-Bench 2.0 is 89/89 graded with 4
`AgentTimeoutError` trials counted as non-solves inside its 66/89, and the
DeepSWE 10-task control is 10/10 graded with no censoring. Raising instead
removed a zero from the GT arm that the baseline keeps — a comparison biased in
our favour by construction.

Exit 3 is now absorbed so the task's own official verifier grades whatever the
agent committed. Every other code still raises: 4 provider_failed,
5 internal_error, 6 setup_error, 137 OOM. Grading those would assert something
about work the agent never got to attempt.

### 2. The canary was the cohort's most expensive, least informative task

`GATE_TASK_ID` was arktype, which is the largest workspace in the cohort
(184,370 graph nodes) **and** TypeScript — the one language this producer
abstains on. Measured: all six signature-delta-eligible edits in the arktype
codespace run were TypeScript and the producer analyses Python only. So the
canary cost the most and proved the least, and neither Actions (86 min) nor the
codespace (96 min) finished it.

The canary is now `aiomonitor-task-snapshots-diff`: a small Python repository,
in the language the producer analyses in full. **arktype still runs** — it is
one of the 19 rather than the gate.

---

## Benchmark parity — what did NOT change

Every task's budget is the benchmark's own, read from `task.toml` at pinned
revision `435ee89ec2f2e2289f33b0da4f992f0b7b7266b9`.

| | benchmark | this run |
|---|---|---|
| `[agent] timeout_sec` | 5400.0, identical for all 20 tasks | resolved with multiplier 1.0 → 5400 |
| gate-one cap | — | 5400, so `min(5400, 5400)` subtracts nothing |
| step limit | 300 | `--ak max_iterations=300` |
| trials per task | 1 | `-n 1` |
| grader | the task's own verifier | `pier run` → `official-verifier-result.json` |
| timeout outcome | graded non-solve | graded non-solve (fixed above) |

The 90-minute gate cap is now provably non-binding and is kept only as a rail
against a future `task.toml` asking for more than the benchmark's own budget.
Raising it would make the gate stage a different experiment from the cohort it
gates.

One asymmetry, in the baseline's favour and left alone: our supervisor reserves
300 s of the 5400 to publish receipts, so the agent loop gets 5100 s where the
public leaderboard's agent gets the full 5400. That is 5.6% less time for GT,
not more.

## Baselines this will be read against

Never re-run; fetched or frozen.

- **DeepSWE GT-off, `deepseek-v4-flash`**, 113 tasks, n=4: pass@1 **0.5332**
  (241/452), mean 152.9 agent steps, mean duration 1439 s. The
  `deepseek-v4-pro` row is a different model and is not our baseline.
- **DeepSWE GT-off 10-task matched control**: 4/10 solved, GT commit `67b7ef50`,
  same runner and budget.

## How to read the outcome

- `official-verifier-result.json` carries `status: GRADED` and `reward` 0 or 1.
  That is the only number that means "solved".
- `gt-run.json` carries the run receipt: terminal state, provider call count,
  and tokens as input / cached / uncached / output.
- Token spend is the cost metric. Never dollars.
