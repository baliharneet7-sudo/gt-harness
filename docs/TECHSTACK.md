---
project: projects/nano-harness
type: techstack
---

# Tech Stack

## Languages

- **Python ≥ 3.12** — the entire harness, CLI, eval glue, and tests. Uses modern syntax
  (PEP 604 unions, `from __future__ import annotations`, dataclasses).

## Runtime dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `anthropic` | `>=0.40` | Anthropic Messages API client. Powers `AnthropicProvider`, including prompt caching (`cache_control: ephemeral`) on the system prompt and most-recent user turn. |
| `openai` | `>=1.50` | OpenAI `chat.completions` client. Powers `OpenAIProvider`; also used for any OpenAI-compatible server (vLLM, Ollama, llama.cpp, Together) via a custom `base_url`. |
| `pydantic` | `>=2.7` | Typed models for the provider boundary: `ToolCall`, `Usage`, `StepResult`. |
| `rich` | `>=13.7` | Terminal rendering in the CLI — assistant turns and tool results as bordered `Panel`s, plus the run summary line via `Console`. |

## Optional dependency groups

### `dev`
| Package | Version | Purpose |
|---------|---------|---------|
| `pytest` | `>=8.2` | Test runner; suite under `tests/`. |
| `pytest-asyncio` | `>=0.23` | Async test support (the eval adapter exposes async `install`/`run`). |
| `ruff` | `>=0.6` | Lint + import sort. Configured rule sets: `E`, `F`, `I`, `B`, `UP`. Line length 100, target `py312`. |

### `eval`
| Package | Purpose |
|---------|---------|
| `harbor` | Terminal-Bench 2.0 runner. Provides `BaseInstalledAgent`, environment, and context base classes the `eval/tb_agent.py` adapter extends. Owns the sandbox, timeouts, and grading. |
| `swebench` | SWE-bench Verified harness — secondary benchmark for cross-validation. |

## Build tools

- **hatchling** (`build-backend = "hatchling.build"`) — PEP 517 build backend. Wheel packages: `nano`, `eval`.
- **pip / uv** — install the editable package and the `nano` console script. `uv tool install` is used by the Terminal-Bench adapter to install the harness inside task containers (with `--python 3.12`).
- **Console script:** `nano = "nano.cli:main"`.

## Tooling config

- **ruff** — lint/format/import-sort config in `pyproject.toml` (`[tool.ruff]`).
- **pytest** — `[tool.pytest.ini_options]`: `testpaths = ["tests"]`, `addopts = "-ra -q"`.
- **VS Code** — `.vscode/settings.json` project settings.

## External APIs

- **Anthropic Messages API** — via the `anthropic` SDK (`ANTHROPIC_API_KEY`).
- **OpenAI Chat Completions API** — via the `openai` SDK (`OPENAI_API_KEY`).
- **OpenAI-compatible inference servers** — any server speaking the OpenAI chat protocol
  (vLLM, Ollama, llama.cpp, Together), reached through `--base-url` / `OPENAI_BASE_URL`.

## Claude skills / MCP servers / plugins

None configured in this repository. There are no `.mcp.json`, plugin manifests, or
custom Claude skill definitions checked in. (The project's `skills.md` is a human-authored
playbook describing which Claude Code skills to use while *building* the project — it is
documentation, not a tooling integration. `CLAUDE.md` provides project context only.)

## Notable architecture / patterns

- **Provider abstraction** via a `typing.Protocol` (`Provider`) — providers are duck-typed
  and injectable, with the SDK clients lazily constructed in `__post_init__`.
- **Persistent subprocess shell** (`BashTool`) using a sentinel-echo protocol over
  `subprocess.Popen` to preserve shell state across tool calls, cross-platform (`bash` /
  `cmd.exe`).
- **Structured eval logging** — `dataclasses` + JSON manifests and JSONL transcripts.
