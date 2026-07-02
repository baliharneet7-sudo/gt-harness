# Head-to-Head v0 — nano-harness, same loop, three models

**Date:** 2026-07-02 · **Harness:** nano-harness (bash tools, reactive loop, verify pass)
**Gateway:** ASU AIML (`api-main.aiml.asu.edu/v1`, OpenAI-compatible) · **Routing:** `OpenAIProvider(base_url=...)`, zero code changes
**Status:** internal falsification test per design §3.8 — not a published benchmark claim.

## Tasks

| id | shape | difficulty |
|----|-------|-----------|
| t1 | fix `average([])` crash, make 2 tests pass | trivial |
| t2 | add `top_words(text, n)` + write 4 tests | medium (ambiguously worded: "in a working repository" on a bare folder) |
| t3 | harden `inventory.py` error handling + write 4 tests | hardest |

## Results (after harness hardening)

| Task | claude4_5_haiku ($1.10/$5.50) | gpt-oss-120b ($0.15/$0.60) | claude4_8_opus ($5/$25) | gpt5_4_thinking ($2.50/$15) |
|------|-------------------------------|----------------------------|-------------------------|------------------------------|
| t1 | PASS · 30 it (cap) · 84s | PASS · 10 it · 30s | PASS · 8 it · 47s | PASS · 7 it · 22s |
| t2 | PASS · 30 it (cap) · 85s | PASS · 12 it · 54s | PASS · 30 it (cap) · 212s * | PASS · 9 it · 31s |
| t3 | PASS · 30 it (cap) · 132s | PASS · 13 it · 62s | PASS · 9 it · 90s | PASS · 15 it · 46s |

\* opus t2 was high-variance across three runs: cmd.exe crash → wander-and-fail → pass-but-looped. Ambiguous task wording made even the frontier model thrash.

## Code quality (t3, the hardest task — judged by reading the diffs)

- **opus** — most senior. `pytest.approx` for float totals (avoids equality trap), `tmp_path` fixture, minimal and idiomatic. Fewest lines, best judgment. Missed `raise ... from e`.
- **gpt-oss-120b** — most professional-looking. Full Args/Returns/Raises docstrings, proper exception chaining (`from e`), defensive `.get("items", [])` beyond spec. Slightly less idiomatic tests (float `==`).
- **haiku** — correct but junior. Most test cases (6) but hand-rolled `tempfile` + `os.unlink` instead of `tmp_path`; float `==` asserts. Works, reads like a bootcamp grad.
- **gpt5_4_thinking** (added 2026-07-02) — best tests of the four: `pytest.raises(match=re.escape(...))`, `pytest.approx`, `tmp_path`, and a mixed missing-fields case asserting a non-zero total (stricter than everyone else's all-zero check). Code terse with proper `from exc` chaining. Fastest wall-clock on every task; clean exits on all three, including t2 where opus thrashed. Caveat: higher input tokens (thinking models resend more).

## Findings

1. **The harness is the body, the model is the brain — confirmed.** Every model passed every task functionally. The differences are all judgment: when to stop, how idiomatic, how defensive.
2. **gpt-oss-120b is the score-per-dollar winner.** Clean 10–13 iterations on all three, ~33x cheaper than opus, professional code. For routine coding it is genuinely competitive.
3. **haiku has no stopping judgment.** Correct output every time, but churns to the 30-iteration cap on all three tasks. Slowest and most tokens despite being a small model. The cap is load-bearing for cheap models.
4. **opus is cleanest but over-explores ambiguity.** 8–9 iterations when the task is crisp; thrashes when it isn't (t2). Task phrasing matters more for stronger models.

## Harness bugs found and fixed live (the real yield)

The cheap-model + Windows combination stress-tested the harness harder than a Linux benchmark would. Each fixed with a regression test; suite 55 green.

| commit | bug |
|--------|-----|
| 8d0983d | token cap counted cumulative spend, killed long tasks after ~4 steps |
| 3b991ac | cp1252 console crashed the CLI printer on unicode output (Windows) |
| 6b660cb | malformed tool call (missing arg) crashed the whole run instead of returning a ToolError |
| b5db725 | shell was cmd.exe on Windows but models write bash; also fixed a latent timeout that ignored silent long commands |
| 5fd6028 | tool-call inputs weren't logged — could see outputs, not the commands the model ran |

## Known limitations (not yet fixed)

- `read_file`/`edit_file` resolve paths against the process launch cwd, not the bash shell's live cwd. If a model `cd`s in bash then edits a relative path, it hits the wrong file. Deferred: the fix needs MSYS path translation on Windows and risks new bugs.
