# CI workflows

## `tb2_baseline.yml` — Terminal-Bench 2.0 baseline (stock nano, no GT)

Runs the Harbor + Terminal-Bench 2.0 evaluation of the stock nano-harness
(`eval.tb_agent:NanoAgent`) on `ubuntu-latest` (Docker available), so benchmark
runs happen in CI instead of a local machine. Manual dispatch only — every run
spends API credits.

Pinned: `harbor==0.20.0` (the flag set in the workflow was validated against
this version; bump deliberately, not casually).

### 1. Set secrets (once)

Set whichever your chosen model needs:

```bash
gh secret set OPENAI_API_KEY        # OpenAI models, DeepSeek, or any OpenAI-compatible gateway
gh secret set OPENAI_BASE_URL       # only if you route through a gateway (e.g. https://api.deepseek.com/v1)
gh secret set ANTHROPIC_API_KEY     # Anthropic (claude-*) models
```

Per-provider cheat sheet (nano routes `claude*`/`anthropic*` names to the
Anthropic provider, everything else to the OpenAI provider — see
`nano/providers.py` and the README):

| Model choice | Required secrets |
|---|---|
| `deepseek/deepseek-v4-flash` (default) | `OPENAI_API_KEY` (=DeepSeek key) + `OPENAI_BASE_URL` (DeepSeek's OpenAI-compatible endpoint) |
| `openai/gpt-*` | `OPENAI_API_KEY` |
| `anthropic/claude-*` | `ANTHROPIC_API_KEY` |
| Gemini or anything else | via an OpenAI-compatible gateway: `OPENAI_API_KEY` (gateway token) + `OPENAI_BASE_URL` |

The `base_url` dispatch input overrides the `OPENAI_BASE_URL` secret for a
single run. When `OPENAI_BASE_URL` is set, the full `provider/name` string is
passed through as the gateway's model id; without it, the provider prefix is
stripped (see `eval/tb_agent.py`).

### 2. Dispatch

```bash
# 5-task slice (the default)
gh workflow run tb2_baseline.yml

# explicit
gh workflow run tb2_baseline.yml -f model=deepseek/deepseek-v4-flash -f n_tasks=5

# full 89-task baseline
gh workflow run tb2_baseline.yml -f n_tasks=all -f concurrency=4

# a manual shard (task_ids overrides n_tasks; names support globs)
gh workflow run tb2_baseline.yml -f task_ids="hello-world,regex-*"

# watch it
gh run watch "$(gh run list -w tb2_baseline.yml -L1 --json databaseId -q '.[0].databaseId')"
```

Runs dispatch on whatever ref you pass with `--ref` (default: repo default
branch); use `--ref gt-integration` while that is the working branch.

### 3. Results

- **Job summary**: solved/total per reward plus a per-task table, parsed from
  harbor's `result.json`, on the run's page in the Actions tab.
- **Artifact** `tb2-baseline-<run id>` (uploaded even on failure/timeout):
  the whole `results/terminal-bench/` tree —
  `<job-name>/result.json` and per-task dirs with the agent transcript
  (`<task>/agent/nano.txt`), verifier output, and config.

```bash
gh run download <run-id> -n tb2-baseline-<run-id>
```

### Timeouts and sharding

Job timeout is 350 minutes. A full 89-task run at concurrency 4 may exceed it
(budget roughly: 89 tasks x TB2 per-task clock x 2.0 agent-timeout multiplier
/ 4 concurrent, worst case). If it times out, shard: dispatch several runs
with disjoint `task_ids` lists (glob patterns work), then merge the
`result.json` files offline. The artifact uploads on timeout too, so a partial
run is never lost. Disk: the workflow prints `df -h` before/after; for
`n_tasks=all` it first reclaims ~25-30 GB of preinstalled runner toolchains,
since 89 distinct task images can exhaust the runner disk.

### The ladder

1. **5-task slice** (now): prove the CI plumbing + model routing end to end.
2. **Full 89-task baseline** (next): the frozen no-GT reference number.
   Freeze the commit + model + job artifact; all GT comparisons point at it.
3. **GT arm** (future, not enabled): same workflow shape with the
   GroundTruth-augmented agent. Blocked on container plumbing in
   `eval/tb_agent.py` `install()` (upload `gt_engine/`, install the
   `groundtruth` package, stage the `gt-index` binary, pass `--gt-root`) —
   see the `TODO(gt)` there. It will be a separate workflow (or a
   `gt_enabled` input) so the baseline stays byte-for-byte reproducible.
