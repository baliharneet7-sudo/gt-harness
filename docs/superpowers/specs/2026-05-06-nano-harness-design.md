# nano-harness — Design Doc

**Status:** v1.1 — core implemented; loop hardening landed 2026-06-17 (§3.5a); benchmark runs deferred
**Author:** Troy + Claude (brainstorm)
**Started:** 2026-05-02
**Spec date:** 2026-05-06

---

## 1. Goal

nano-harness is the **smallest readable coding-agent loop that can run benchmark-grade evals with transparent logs**. It answers one question:

> How much benchmark performance can you get from the smallest readable agent loop?

The project leads with **benchmark credibility**, not pedagogy. Because the core is intentionally small, it also works as an educational reference implementation — but that is a byproduct, not the headline.

> **Tagline candidate (README copy, not spec-binding):** A coding agent you can read in an afternoon, benchmark in an evening, and audit line by line.

### The wedge

Popular agent harnesses (Archon, DeerFlow 2.0, your-claude-engineer, etc.) compete on **features** — sandboxes, channels, sub-agents, plugin systems. Most minimal open-source harnesses do not publish reproducible, inspectable benchmark runs tied to their exact harness code. (Commercial agents like Claude Code, Codex, and Devin publish benchmark scores — but those are products, not readable open-source loops you can audit.)

nano-harness competes on a **score-per-line-of-code** axis. The marketing artifact is a leaderboard table where every cell is reproducible from a logged eval run, and the entire harness is small enough that a competent dev can read it end-to-end in an afternoon.

> Sub-500 LOC core. Real Terminal-bench scores. No framework bloat.

**Guiding principle when minimalism and absolute score fight:** v1 optimizes for score-per-line-of-code, not raw score. If a convenience tool or a heavier prompt would lift the score 5 points but cost 200 LOC, we don't add it. The brand is "the small thing that scores honestly," not "the maximally tuned thing."

---

## 2. Non-goals

- **Not a general agent framework.** No plugin system, no extensibility for arbitrary domains. That is Archon / DeerFlow's lane.
- **Not a product.** No UI, no auth, no SaaS, no dashboard. That is Agent OS's lane.
- **Not a chat assistant.** Single-task, completion-focused. Conversation is incidental.
- **Not a router library.** No LiteLLM, no provider hub. We accept that we support exactly two SDKs.
- **No fine-tuning.** Models are used as-is.

---

## 3. Decisions locked

### 3.1 Benchmarks

| Benchmark | Why | Target |
|:---:|:---:|:---:|
| **Terminal-bench** (primary) | Less crowded; terminal-native shape matches harness; attention rising in 2026 | >30% to draw attention; >45% is the stretch |
| **SWE-bench Verified** (secondary) | Cross-validation. Same harness runs both. >30% is below 2026 median (~75-80% top) but still useful as a credibility signal that the same code generalizes | >30% |

Skipped on purpose: HumanEval, MBPP, SWE-bench Lite (saturated), Aider Polyglot (Aider's home turf, bad optics), SWE-bench Full (too noisy).

### 3.2 Loop shape — native tool-use, reactive

Use the SDK's native tool-use API (Anthropic `tool_use` content blocks, OpenAI `tool_calls`). Not ReAct text prompting. Not plan-then-execute.

The loop is one tight reactive cycle:

```
while True:
    result = provider.step(messages, tools, system)
    messages.append(assistant_message(result))
    if result.stop_reason == "end_turn":
        break
    for call in result.tool_calls:
        output = execute_tool(call)
        messages.append(tool_result(call.id, output))
    if iteration > MAX_ITERATIONS or tokens > MAX_TOKENS:
        break
```

Frontier models self-correct better than they plan. Reactive beats plan-then-execute for one-shot coding tasks under the budgets we care about.

### 3.3 Tool set — three tools, no more

| Tool | Signature | Notes |
|:---:|:---:|:---:|
| `bash` | `command: str, timeout: int=30` | One persistent shell session per task; cwd survives across calls |
| `read_file` | `path: str, line_start: int?=None, line_end: int?=None` | Returns line-numbered content |
| `edit_file` | `path: str, old: str, new: str` | Exact string replacement; fails loudly on non-unique matches |

Why these three: they are the irreducible coding-agent surface. Anything more (web fetch, multi-file diff, glob, grep) is either expressible via `bash` or scope creep. Anything less and you cannot solve realistic tasks.

For the Anthropic impl we may swap in the proven beta tools `text_editor_20250728` and `bash_20250728` behind the same Tool interface — the agent loop will not know.

### 3.4 Provider strategy — two impls, leaderboard table

**Two SDKs cover the whole leaderboard:**

```python
class StepResult(NamedTuple):
    text: str | None
    tool_calls: list[ToolCall]      # normalized shape
    stop_reason: str                 # end_turn | tool_use | max_tokens
    usage: Usage                     # input/output/cache tokens

class Provider(Protocol):
    def step(self, messages, tools, system) -> StepResult: ...

class AnthropicProvider:    # native tool_use blocks + cache_control
class OpenAIProvider:       # configurable base_url; covers GPT-5 + everything OpenAI-compatible
```

Slots in the published leaderboard. Exact model + version is named only when actually tested, with the test date — old runs must not pretend to be current frontier.

| Slot | Provider | Why |
|:---:|:---:|:---:|
| Latest Claude Opus | Anthropic | Frontier. Prompt-cache friendly. |
| Latest Claude Sonnet | Anthropic | Cost-perf reference point. |
| Latest GPT frontier | OpenAI | Frontier. Different family. |
| Current strong open coding model | OpenAI-compatible (Together / Fireworks / OpenRouter) | E.g. DeepSeek, Qwen-Coder family. |
| Current local / open-weight baseline | OpenAI-compatible (llama.cpp / vLLM) | "Same harness lifts a local model from baseline to X." Most viral framing. |

**Why two SDKs instead of LiteLLM:** The point of the harness is end-to-end legibility. A router library buries the interesting logic behind one more wrapper. Two thin impls keep the readable-in-an-afternoon promise.

**Translator boundaries live inside each impl.** The agent loop sees only `StepResult`. Prompt caching is Anthropic-only — the OpenAI impl no-ops on cache hints. We publish per-model cost numbers honestly; Claude looking cheaper-to-iterate-on is a true and useful signal.

### 3.5 Context management

- **Prompt caching:** Anthropic impl applies `cache_control` to (a) the system prompt and (b) the second-to-last user turn. Validate cache hit rate >50% on multi-turn tasks before publishing any cost numbers.
- **Conversation truncation:** Hard cap on iterations and on total input tokens. On overflow, drop oldest tool_result content (not the messages — keep the structural skeleton). Log every truncation event.
- **System prompt:** <1,000 tokens. Drafted from first principles, then trimmed against eval scores. No "you are an expert agent" filler.

### 3.5a Loop hardening (locked 2026-06-17, implemented)

Decisions added after implementation review; all landed with tests:

- **Token cap semantics:** the cap guards *per-step context size* (what one request sends), never cumulative spend — cumulative counting silently killed long tasks. Totals are still reported in `AgentResult`.
- **Transient API retry:** providers retry 429/5xx/529 and connection drops, 3 attempts, exponential backoff. Other client errors raise immediately.
- **Output-truncation recovery:** `stop_reason=max_tokens` with no tool calls injects a continuation nudge instead of reporting false success.
- **Verify pass:** the loop challenges the model's first "done" once — re-read requirements, run tests, fix or confirm (skipped for tool-free runs; `verify=False` to disable). Cheapest defense against self-graded success; a full planner/generator/evaluator role split was considered and rejected as a different product (days-scale autonomy, ~3x LOC).
- **Bash timeout:** default 60s; on timeout the error message tells the model the shell restarted and cwd/env/background state is gone.
- **System prompt v2:** adds code-quality directives (match repo style, no placeholders, test what you change), verification-before-done, non-interactive command discipline, and persistence; drops the "if blocked, stop" clause.

### 3.6 Repo layout & LOC budget

We do **not** reimplement the benchmarks. Terminal-Bench 2.0 is run by **Harbor** (`pip install harbor`), which drives agents via a `BaseInstalledAgent` interface (the 1.x `tb` CLI / `AbstractAgent` path is legacy); SWE-bench Verified ships a Docker eval pipeline with its own grader. Our `eval/` is **adapters that plug nano-harness into existing infrastructure**, plus thin run scripts that produce predictions in their expected formats. Credibility goes up *because* we use the canonical scorers unchanged — there is no "did they grade it themselves?" attack surface.

```
nano-harness/
  nano/
    agent.py                    ~150 LOC   # the loop + iteration cap
    tools.py                    ~150 LOC   # bash, read_file, edit_file impls
    providers.py                ~120 LOC   # Provider protocol + Anthropic + OpenAI impls
    prompts.py                   ~50 LOC   # system prompt, tool descriptions
    cli.py                       ~50 LOC   # `nano run "task description"`
  eval/
    tb_agent.py                 ~100 LOC   # Harbor BaseInstalledAgent adapter (TB 2.0)
    swebench_adapter.py          ~50 LOC   # produces SWE-bench predictions, invokes official grader
    log.py                       ~50 LOC   # per-run JSON manifest writer
  results/                                   # committed eval transcripts + manifests
  README.md                                  # leaderboard table lives here
  pyproject.toml
```

**Hard limits:**

- Core (`nano/`) ≤ 500 LOC.
- Eval adapters (`eval/`) ≤ 200 LOC.
- System prompt ≤ 1,000 tokens.
- Runtime deps ≤ 5 (`anthropic`, `openai`, `pydantic` if needed, `rich` for CLI, `pytest` dev-only — pytest does not count toward runtime).
- Eval-only deps (Terminal-Bench SDK, SWE-bench grader) live in a separate optional dep group and do not count toward the runtime cap.

**Report LOC honestly, by layer.** The README never claims a single LOC number for the whole project. It always splits: core loop / tools / providers / prompts / adapters. If we honestly hit 300 LOC core, that becomes the headline. If we land at 480, that becomes the headline. We never compress numbers to fit the slogan, and we never write clever code to hit a target LOC at the cost of readability — readability is the wedge, not LOC count.

If a file is approaching its budget, the design is wrong. Refactor or scope-cut, do not raise the cap.

### 3.7 Eval logging

Every benchmark run produces `results/<benchmark>/<model>/<run-id>/manifest.json`:

```json
{
  "run_id": "...",
  "benchmark": "terminal-bench",
  "benchmark_version": "v0.1.5",
  "model": "claude-opus-4-7",
  "provider": "anthropic",
  "harness_commit": "abc123",
  "command": "python -m eval.terminal_bench_adapter --model claude-opus-4-7 --concurrency 4",
  "started_at": "...",
  "completed_at": "...",
  "score": 0.42,
  "grader_output_path": "results/.../grader.txt",
  "tasks": [
    {
      "task_id": "...",
      "passed": true,
      "iterations": 7,
      "wall_seconds": 84,
      "input_tokens": 12450,
      "output_tokens": 1820,
      "cache_read_tokens": 9400,
      "cost_usd": 0.18,
      "transcript_path": "results/.../<task_id>.transcript.jsonl",
      "failure_reason": null
    }
  ],
  "failed_task_samples": ["task_id_a", "task_id_b", "task_id_c"]
}
```

**Rules:**

- No cherry-picking. Failed tasks stay in the log. Disabled tasks must be justified in the README.
- Cold-cache reproduction: any published number must be reproducible from a fresh `git clone` and a re-run of the exact `command` field.
- Transcripts are full per-task JSONL: every message and tool call.
- **Every published score links to the full run artifact:** exact commit, model + provider, benchmark name + version, command line, transcripts, raw grader output, per-task cost / wall-time / iteration counts, and an explicit list of failed-task samples a reviewer can spot-check.
- **No benchmark-specific agent behavior.** Eval adapters may prepare the task environment (mounting the repo, exposing test commands), but the agent loop, tools, and system prompt must remain identical across benchmarks. Any benchmark-tuned variant must be clearly labeled as such in the README and run as a separate row in the leaderboard — never replacing the canonical run.

### 3.8 Validation gate — v0 head-to-head

Before official benchmark runs, run a cheap v0 head-to-head against one larger open-source coding-agent harness, likely Archon or a similar project.

This is not a published benchmark claim. It is an internal falsification test for the wedge.

The comparison uses:

- the same model
- the same 8–10 hand-curated coding tasks
- the same starting repositories
- the same task prompts
- comparable iteration and token budgets

Track:

- pass/fail
- iterations
- input/output tokens
- estimated cost
- transcript readability
- setup friction
- lines of core harness code

If nano-harness is dramatically worse, the wedge needs revision before official eval work. If nano-harness is competitive, even at a lower absolute score, the score-per-line-of-code story is worth pursuing.

---

## 4. Build order (11 steps)

1. **Provider abstraction.** `StepResult`, `Provider` Protocol, Anthropic impl with prompt caching, OpenAI impl with configurable `base_url`. TDD with mocked SDK responses.
2. **Tool implementations.** `bash` (persistent shell), `read_file`, `edit_file`. TDD around edge cases (non-unique edit match, missing file, timeout, large output truncation).
3. **Agent loop.** `nano/agent.py` — the reactive loop, iteration cap, token cap, truncation policy.
4. **System prompt + tool descriptions.** Draft from first principles. Keep <1,000 tokens.
5. **CLI.** `nano run "task"` — minimal entry point. Local sanity test on a hand-written task.
6. **v0 head-to-head validation gate.** Run nano-harness vs one larger open-source harness (likely Archon) on 8–10 hand-curated coding tasks per §3.8. Internal-only; not published as a benchmark. If dramatically worse, revisit the wedge before spending money on official evals.
7. **Terminal-Bench adapter.** `eval/tb_agent.py` — Harbor `BaseInstalledAgent`: uploads the local checkout into each task container, installs with uv, runs `nano run` inside. We do not write a scorer or a runner. Smoke-test on 5 tasks before any full run. *(Written; unexecuted — benchmark runs deferred until budget approved.)*
8. **First public number.** Run the official Terminal-Bench harness end-to-end against nano-harness with the latest Claude Opus. Commit the full run artifact (manifest + transcripts + raw grader output). Iterate prompt + truncation until score stabilizes.
9. **Multi-model.** Re-run the same Terminal-Bench harness against the other leaderboard slots. Publish leaderboard table in README; every cell links to its full artifact.
10. **SWE-bench Verified adapter + run.** `eval/swebench_adapter.py` — produce predictions in SWE-bench's expected format, hand them to the official Docker grader, commit the artifact. Same harness, no benchmark-specific tweaks.
11. **Ship.** Public GitHub repo, README with the table, blog post / X thread leading with score-per-line-of-code framing.

---

## 5. Open questions

- **Cost ceiling per benchmark run.** Hard $ cap (e.g. abort run if total cost > $X) vs track-and-report only? Recommend **track-and-report** for v1 — a hard cap can mask harness bugs (runaway iterations look like cost overruns). Add cap later if costs sting.
- **Local model serving.** llama.cpp vs vLLM for the Llama 3.3 70B leaderboard slot. Decide when we get to step 8; defer until then.
- **Sandbox safety.** Terminal-bench / SWE-bench tasks run inside their own Docker containers, so the harness itself does not need a sandbox layer. If we ever support arbitrary user tasks via the CLI, we revisit.
- **Failure-mode tagging.** Do we tag failed tasks with a reason (timeout, max-iterations, wrong-answer, tool-error)? Useful for iteration but adds eval-side code. Likely yes after first full run reveals the failure distribution.

---

## 6. Success criteria

A run is "shippable" when all of these hold:

- [ ] Core (`nano/`) is ≤ 500 LOC; eval adapters (`eval/`) ≤ 200 LOC.
- [ ] Terminal-Bench score ≥ 30% with the latest Claude Opus, scored by the official Terminal-Bench harness (no DIY grader).
- [ ] SWE-bench Verified score ≥ 30% with the same harness, scored by the official SWE-bench grader, no per-benchmark forks.
- [ ] At least 3 models in the leaderboard table, every cell linking to a full reproducible run artifact (manifest + transcripts + raw grader output).
- [ ] README leads with the table; first paragraph names the score-per-line-of-code framing and reports LOC by layer (not a single composite number).
- [ ] A competent dev can read the entire `nano/` tree and explain the loop without external help.

---

## 7. What this doc does NOT decide

These are intentionally left to the implementation plan or to first-run telemetry:

- Exact iteration cap number (start at 30, tune from data).
- Exact context-truncation cutoff (start at 80% of model window, tune from data).
- Whether to support both Anthropic computed-tools (`text_editor_20250728`, `bash_20250728`) and our hand-written tools, or pick one. Likely pick one per provider after a head-to-head.
- Logging format minutiae (JSON shape will evolve).
