# nano-harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the smallest readable coding-agent loop that runs Terminal-Bench and SWE-bench Verified end-to-end, with reproducible per-run artifacts.

**Architecture:** A reactive native-tool-use loop wrapping a `Provider` protocol. Two provider implementations (Anthropic, OpenAI-compatible) translate to a normalized `StepResult`. Three tools (`bash`, `read_file`, `edit_file`) form the irreducible coding surface. Eval adapters plug nano-harness into Terminal-Bench's `AbstractAgent` interface and SWE-bench's prediction-grader pipeline — neither benchmark gets a reimplemented scorer.

**Tech Stack:** Python 3.12+, `anthropic` SDK, `openai` SDK, `pydantic` (typed messages), `rich` (CLI rendering), `pytest` (tests). Eval-only optional deps: `terminal-bench`, `swe-bench` (separate dep group).

**Spec reference:** `docs/superpowers/specs/2026-05-06-nano-harness-design.md`. Sections cited inline as §3.x.

---

## File Structure

| Path | Responsibility | LOC budget |
|---|---|---|
| `nano/__init__.py` | Package marker, version | <10 |
| `nano/agent.py` | Reactive loop, iteration cap, truncation | ~150 |
| `nano/tools.py` | `bash`, `read_file`, `edit_file`, registry | ~150 |
| `nano/providers.py` | `StepResult`, `Provider`, Anthropic + OpenAI impls | ~120 |
| `nano/prompts.py` | System prompt, tool descriptions | ~50 |
| `nano/cli.py` | `nano run "task"` entry point | ~50 |
| `eval/__init__.py` | Package marker | <5 |
| `eval/log.py` | Per-run JSON manifest writer, transcript JSONL | ~50 |
| `eval/terminal_bench_adapter.py` | Implements Terminal-Bench `AbstractAgent` | ~50 |
| `eval/swebench_adapter.py` | Produces SWE-bench predictions, calls official grader | ~50 |
| `eval/headtohead.py` | v0 internal validation runner (§3.8) | ~80 |
| `tests/test_providers.py` | Provider tests with mocked SDK responses | n/a |
| `tests/test_tools.py` | Tool tests (real shell/fs in tmpdir) | n/a |
| `tests/test_agent.py` | Loop tests with fake provider | n/a |
| `tests/test_log.py` | Manifest writer tests | n/a |
| `pyproject.toml` | Deps, build config, ruff/pytest config | n/a |
| `README.md` | Leaderboard table, score-per-LOC framing | n/a |
| `results/` | Committed per-run artifacts (created on first run) | n/a |

**Hard limits (§3.6):** core ≤ 500 LOC, eval ≤ 200 LOC (`headtohead.py` is internal-only and counted separately), system prompt ≤ 1000 tokens, runtime deps ≤ 5.

---

## Task 0: Bootstrap repo

**Files:**
- Create: `pyproject.toml`
- Create: `nano/__init__.py`
- Create: `eval/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `.gitignore`

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "nano-harness"
version = "0.0.1"
description = "Smallest readable coding-agent loop that scores on benchmarks."
requires-python = ">=3.12"
dependencies = [
  "anthropic>=0.40",
  "openai>=1.50",
  "pydantic>=2.7",
  "rich>=13.7",
]

[project.optional-dependencies]
dev = ["pytest>=8.2", "pytest-asyncio>=0.23", "ruff>=0.6"]
eval = ["terminal-bench", "swebench"]

[project.scripts]
nano = "nano.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["nano", "eval"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra -q"

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP"]
```

- [ ] **Step 2: Write package markers**

`nano/__init__.py`:
```python
__version__ = "0.0.1"
```

`eval/__init__.py`:
```python
```

`tests/__init__.py`:
```python
```

- [ ] **Step 3: Write `tests/conftest.py`**

```python
import pytest


@pytest.fixture
def tmp_workdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path
```

- [ ] **Step 4: Write `.gitignore`**

```
__pycache__/
*.pyc
.venv/
.pytest_cache/
.ruff_cache/
*.egg-info/
dist/
build/
.env
results/**/raw/
```

- [ ] **Step 5: Install and verify**

Run: `python -m venv .venv && .\.venv\Scripts\Activate.ps1 && pip install -e ".[dev]"`
Expected: install succeeds, no resolver errors.

Run: `pytest`
Expected: `no tests ran` (exit 5 or 0; both fine — confirms pytest discovered the project).

- [ ] **Step 6: Commit**

```bash
git init
git add pyproject.toml nano eval tests .gitignore
git commit -m "chore: bootstrap nano-harness package skeleton"
```

---

## Task 1: Provider types — `StepResult`, `ToolCall`, `Usage`

**Files:**
- Create: `nano/providers.py` (types only this task)
- Create: `tests/test_providers.py`

- [ ] **Step 1: Write failing test for `ToolCall` and `StepResult` shape**

`tests/test_providers.py`:
```python
from nano.providers import StepResult, ToolCall, Usage


def test_step_result_minimum_fields():
    sr = StepResult(
        text="hello",
        tool_calls=[ToolCall(id="c1", name="bash", arguments={"command": "ls"})],
        stop_reason="tool_use",
        usage=Usage(input_tokens=10, output_tokens=5, cache_read_tokens=0),
    )
    assert sr.text == "hello"
    assert sr.tool_calls[0].name == "bash"
    assert sr.tool_calls[0].arguments == {"command": "ls"}
    assert sr.stop_reason == "tool_use"
    assert sr.usage.input_tokens == 10


def test_step_result_text_only():
    sr = StepResult(text="done", tool_calls=[], stop_reason="end_turn",
                    usage=Usage(input_tokens=1, output_tokens=1, cache_read_tokens=0))
    assert sr.tool_calls == []
    assert sr.stop_reason == "end_turn"
```

- [ ] **Step 2: Run test, verify failure**

Run: `pytest tests/test_providers.py -v`
Expected: FAIL — `ImportError: cannot import name 'StepResult' from 'nano.providers'`.

- [ ] **Step 3: Implement types in `nano/providers.py`**

```python
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]


class Usage(BaseModel):
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0


class StepResult(BaseModel):
    text: str | None
    tool_calls: list[ToolCall]
    stop_reason: str  # end_turn | tool_use | max_tokens
    usage: Usage


@runtime_checkable
class Provider(Protocol):
    model: str

    def step(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        system: str,
    ) -> StepResult: ...
```

- [ ] **Step 4: Run test, verify pass**

Run: `pytest tests/test_providers.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add nano/providers.py tests/test_providers.py
git commit -m "feat(providers): add normalized StepResult/ToolCall/Usage types"
```

---

## Task 2: AnthropicProvider — translate to/from `StepResult`

**Files:**
- Modify: `nano/providers.py` (append `AnthropicProvider`)
- Modify: `tests/test_providers.py` (append tests)

**Why:** Spec §3.4 says Anthropic uses native `tool_use` blocks and `cache_control`. The provider hides this from the loop. Tests use a fake `client.messages.create` so we never hit the network.

- [ ] **Step 1: Write failing test for `AnthropicProvider.step` with a tool_use response**

Append to `tests/test_providers.py`:
```python
from unittest.mock import MagicMock

from nano.providers import AnthropicProvider


class _AnthroMsg:
    def __init__(self, content, stop_reason, usage):
        self.content = content
        self.stop_reason = stop_reason
        self.usage = usage


class _Block:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def _fake_anthropic_response_with_tool():
    return _AnthroMsg(
        content=[
            _Block(type="text", text="I'll list files."),
            _Block(type="tool_use", id="tu_1", name="bash",
                   input={"command": "ls"}),
        ],
        stop_reason="tool_use",
        usage=MagicMock(input_tokens=120, output_tokens=30,
                        cache_read_input_tokens=80, cache_creation_input_tokens=0),
    )


def test_anthropic_provider_translates_tool_use():
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_anthropic_response_with_tool()
    p = AnthropicProvider(model="claude-opus-4-7", client=fake_client)

    result = p.step(
        messages=[{"role": "user", "content": "list files"}],
        tools=[{"name": "bash", "description": "shell",
                "input_schema": {"type": "object", "properties": {
                    "command": {"type": "string"}}, "required": ["command"]}}],
        system="you help",
    )

    assert result.text == "I'll list files."
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].id == "tu_1"
    assert result.tool_calls[0].name == "bash"
    assert result.tool_calls[0].arguments == {"command": "ls"}
    assert result.stop_reason == "tool_use"
    assert result.usage.input_tokens == 120
    assert result.usage.cache_read_tokens == 80


def test_anthropic_provider_end_turn_text_only():
    msg = _AnthroMsg(
        content=[_Block(type="text", text="done")],
        stop_reason="end_turn",
        usage=MagicMock(input_tokens=5, output_tokens=2,
                        cache_read_input_tokens=0, cache_creation_input_tokens=0),
    )
    fake_client = MagicMock()
    fake_client.messages.create.return_value = msg
    p = AnthropicProvider(model="claude-opus-4-7", client=fake_client)

    result = p.step(messages=[{"role": "user", "content": "hi"}], tools=[], system="s")

    assert result.text == "done"
    assert result.tool_calls == []
    assert result.stop_reason == "end_turn"


def test_anthropic_provider_applies_cache_control_to_system_and_last_user():
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_anthropic_response_with_tool()
    p = AnthropicProvider(model="claude-opus-4-7", client=fake_client)

    p.step(
        messages=[
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "ack"},
            {"role": "user", "content": "second"},
        ],
        tools=[],
        system="SYS",
    )

    kwargs = fake_client.messages.create.call_args.kwargs
    sys_param = kwargs["system"]
    assert isinstance(sys_param, list)
    assert sys_param[0]["text"] == "SYS"
    assert sys_param[0]["cache_control"] == {"type": "ephemeral"}

    last_user = kwargs["messages"][-1]
    assert last_user["role"] == "user"
    last_block = last_user["content"][-1]
    assert last_block["cache_control"] == {"type": "ephemeral"}
```

- [ ] **Step 2: Run tests, verify failure**

Run: `pytest tests/test_providers.py -v`
Expected: 3 failures with `ImportError: cannot import name 'AnthropicProvider'`.

- [ ] **Step 3: Implement `AnthropicProvider` in `nano/providers.py`**

Append to `nano/providers.py`:
```python
from dataclasses import dataclass


def _ensure_block_list(content: Any) -> list[dict[str, Any]]:
    """Normalize a message's content to a list-of-blocks form so we can
    attach cache_control to the last block."""
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return [dict(b) for b in content]


@dataclass
class AnthropicProvider:
    model: str
    client: Any = None  # injectable for tests; defaults to anthropic.Anthropic()
    max_tokens: int = 4096

    def __post_init__(self) -> None:
        if self.client is None:
            import anthropic
            self.client = anthropic.Anthropic()

    def step(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        system: str,
    ) -> StepResult:
        sys_param = [{"type": "text", "text": system,
                      "cache_control": {"type": "ephemeral"}}]
        msgs = [{"role": m["role"], "content": _ensure_block_list(m["content"])}
                for m in messages]
        # Cache-mark the last user turn (spec §3.5: system + second-to-last user
        # turn — by the time step() runs, the "second-to-last" is the most recent
        # user message before the assistant turn we're about to generate).
        for m in reversed(msgs):
            if m["role"] == "user" and m["content"]:
                m["content"][-1]["cache_control"] = {"type": "ephemeral"}
                break

        resp = self.client.messages.create(
            model=self.model,
            system=sys_param,
            messages=msgs,
            tools=tools,
            max_tokens=self.max_tokens,
        )

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in resp.content:
            btype = getattr(block, "type", None)
            if btype == "text":
                text_parts.append(block.text)
            elif btype == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.id, name=block.name, arguments=dict(block.input)))

        usage = Usage(
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            cache_read_tokens=getattr(resp.usage, "cache_read_input_tokens", 0) or 0,
        )

        return StepResult(
            text="\n".join(text_parts) if text_parts else None,
            tool_calls=tool_calls,
            stop_reason=resp.stop_reason,
            usage=usage,
        )
```

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/test_providers.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add nano/providers.py tests/test_providers.py
git commit -m "feat(providers): AnthropicProvider with cache_control on system + last user"
```

---

## Task 3: OpenAIProvider — translate to/from `StepResult`

**Files:**
- Modify: `nano/providers.py` (append `OpenAIProvider`)
- Modify: `tests/test_providers.py` (append tests)

**Why:** Spec §3.4 — OpenAI provider with configurable `base_url` covers GPT frontier, OpenRouter, Together, Fireworks, vLLM, llama.cpp. No-ops on cache hints.

- [ ] **Step 1: Write failing test**

Append to `tests/test_providers.py`:
```python
import json as _json

from nano.providers import OpenAIProvider


def _fake_openai_response_with_tool():
    return MagicMock(
        choices=[MagicMock(
            message=MagicMock(
                content="I'll list.",
                tool_calls=[MagicMock(
                    id="call_1",
                    function=MagicMock(name="bash",
                                       arguments=_json.dumps({"command": "ls"})),
                )],
            ),
            finish_reason="tool_calls",
        )],
        usage=MagicMock(prompt_tokens=50, completion_tokens=20),
    )


def test_openai_provider_translates_tool_calls():
    # MagicMock auto-sets `.name`; force it to the literal string we want.
    resp = _fake_openai_response_with_tool()
    resp.choices[0].message.tool_calls[0].function.name = "bash"

    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = resp
    p = OpenAIProvider(model="gpt-5", client=fake_client)

    result = p.step(
        messages=[{"role": "user", "content": "list"}],
        tools=[{"name": "bash", "description": "shell",
                "input_schema": {"type": "object",
                                 "properties": {"command": {"type": "string"}},
                                 "required": ["command"]}}],
        system="sys",
    )

    assert result.text == "I'll list."
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].id == "call_1"
    assert result.tool_calls[0].name == "bash"
    assert result.tool_calls[0].arguments == {"command": "ls"}
    assert result.stop_reason == "tool_use"  # normalized from "tool_calls"
    assert result.usage.input_tokens == 50


def test_openai_provider_end_turn():
    resp = MagicMock(
        choices=[MagicMock(
            message=MagicMock(content="done", tool_calls=None),
            finish_reason="stop",
        )],
        usage=MagicMock(prompt_tokens=3, completion_tokens=1),
    )
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = resp
    p = OpenAIProvider(model="gpt-5", client=fake_client)

    result = p.step(messages=[{"role": "user", "content": "hi"}], tools=[], system="s")

    assert result.text == "done"
    assert result.tool_calls == []
    assert result.stop_reason == "end_turn"  # normalized from "stop"


def test_openai_provider_translates_tool_schema_to_openai_format():
    resp = MagicMock(
        choices=[MagicMock(
            message=MagicMock(content="hi", tool_calls=None),
            finish_reason="stop",
        )],
        usage=MagicMock(prompt_tokens=1, completion_tokens=1),
    )
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = resp
    p = OpenAIProvider(model="gpt-5", client=fake_client)

    p.step(
        messages=[{"role": "user", "content": "x"}],
        tools=[{"name": "bash", "description": "shell",
                "input_schema": {"type": "object",
                                 "properties": {"command": {"type": "string"}},
                                 "required": ["command"]}}],
        system="SYS",
    )

    kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert kwargs["messages"][0] == {"role": "system", "content": "SYS"}
    sent_tool = kwargs["tools"][0]
    assert sent_tool["type"] == "function"
    assert sent_tool["function"]["name"] == "bash"
    assert sent_tool["function"]["parameters"]["required"] == ["command"]
```

- [ ] **Step 2: Run tests, verify failure**

Run: `pytest tests/test_providers.py -v`
Expected: 3 new failures (`OpenAIProvider` undefined).

- [ ] **Step 3: Implement `OpenAIProvider`**

Append to `nano/providers.py`:
```python
import json

_OAI_FINISH_REASON = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "length": "max_tokens",
}


def _normalize_assistant_for_openai(msg: dict[str, Any]) -> dict[str, Any]:
    """Convert our internal assistant message (which may carry tool_calls in
    Anthropic-style dict form) to OpenAI's expected shape. Tool messages stay
    role='tool' with tool_call_id."""
    if msg["role"] != "assistant":
        return msg
    content = msg.get("content")
    tool_calls = msg.get("tool_calls")
    out: dict[str, Any] = {"role": "assistant"}
    if isinstance(content, list):
        out["content"] = "\n".join(
            b["text"] for b in content if b.get("type") == "text"
        ) or None
    else:
        out["content"] = content
    if tool_calls:
        out["tool_calls"] = [{
            "id": tc["id"],
            "type": "function",
            "function": {"name": tc["name"], "arguments": json.dumps(tc["arguments"])},
        } for tc in tool_calls]
    return out


@dataclass
class OpenAIProvider:
    model: str
    client: Any = None
    base_url: str | None = None
    max_tokens: int = 4096

    def __post_init__(self) -> None:
        if self.client is None:
            import openai
            self.client = openai.OpenAI(base_url=self.base_url) if self.base_url \
                else openai.OpenAI()

    def step(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        system: str,
    ) -> StepResult:
        oai_messages = [{"role": "system", "content": system}] + [
            _normalize_assistant_for_openai(m) for m in messages
        ]
        oai_tools = [{
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        } for t in tools]

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": oai_messages,
            "max_tokens": self.max_tokens,
        }
        if oai_tools:
            kwargs["tools"] = oai_tools

        resp = self.client.chat.completions.create(**kwargs)
        choice = resp.choices[0]
        msg = choice.message

        tool_calls: list[ToolCall] = []
        for tc in (msg.tool_calls or []):
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {"_raw": tc.function.arguments}
            tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))

        usage = Usage(
            input_tokens=getattr(resp.usage, "prompt_tokens", 0),
            output_tokens=getattr(resp.usage, "completion_tokens", 0),
            cache_read_tokens=0,
        )

        return StepResult(
            text=msg.content,
            tool_calls=tool_calls,
            stop_reason=_OAI_FINISH_REASON.get(choice.finish_reason, choice.finish_reason),
            usage=usage,
        )
```

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/test_providers.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add nano/providers.py tests/test_providers.py
git commit -m "feat(providers): OpenAIProvider with configurable base_url"
```

---

## Task 4: `bash` tool — persistent shell session

**Files:**
- Create: `nano/tools.py`
- Create: `tests/test_tools.py`

**Why:** Spec §3.3 — one persistent shell per task; cwd survives across calls; 30s default timeout. We do **not** use `subprocess.run` per call because that loses cwd between calls.

- [ ] **Step 1: Write failing test for cwd persistence and basic execution**

`tests/test_tools.py`:
```python
import os
import sys

import pytest

from nano.tools import BashTool, ToolError


@pytest.fixture
def bash():
    t = BashTool()
    yield t
    t.close()


def test_bash_runs_simple_command(bash):
    out = bash.run("echo hello", timeout=5)
    assert "hello" in out


def test_bash_cwd_persists_across_calls(bash, tmp_workdir):
    sub = tmp_workdir / "sub"
    sub.mkdir()
    bash.run(f"cd {sub}", timeout=5)
    out = bash.run("pwd" if sys.platform != "win32" else "cd", timeout=5)
    assert "sub" in out


def test_bash_env_persists_across_calls(bash):
    bash.run("export NANO_TEST=42" if sys.platform != "win32"
             else "set NANO_TEST=42", timeout=5)
    out = bash.run("echo $NANO_TEST" if sys.platform != "win32"
                   else "echo %NANO_TEST%", timeout=5)
    assert "42" in out


def test_bash_timeout_raises_or_reports(bash):
    with pytest.raises(ToolError) as exc:
        bash.run("sleep 5" if sys.platform != "win32"
                 else "ping -n 6 127.0.0.1 > nul", timeout=1)
    assert "timeout" in str(exc.value).lower()


def test_bash_truncates_huge_output(bash):
    cmd = ("python -c \"print('x'*200000)\"")
    out = bash.run(cmd, timeout=10)
    assert len(out) < 200000
    assert "truncated" in out.lower()
```

- [ ] **Step 2: Run tests, verify failure**

Run: `pytest tests/test_tools.py -v`
Expected: ImportError on `BashTool` / `ToolError`.

- [ ] **Step 3: Implement `BashTool` and `ToolError` in `nano/tools.py`**

```python
from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any


class ToolError(Exception):
    """Raised when a tool call fails. The message is shown to the model."""


_OUTPUT_LIMIT = 16_000  # chars; spec §3.3 leaves "large output truncation" to impl


def _truncate(text: str, limit: int = _OUTPUT_LIMIT) -> str:
    if len(text) <= limit:
        return text
    head = text[: limit // 2]
    tail = text[-limit // 2 :]
    dropped = len(text) - limit
    return f"{head}\n... [truncated {dropped} chars] ...\n{tail}"


class BashTool:
    """Persistent shell. Each `run()` writes the command followed by a sentinel
    echo, then reads stdout until the sentinel appears. Cwd, env, and shell
    state survive between calls. On timeout we kill the shell and start a new
    one — bash supports nothing reliable here.
    """

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._spawn()

    def _spawn(self) -> None:
        if sys.platform == "win32":
            cmd = ["cmd.exe", "/Q", "/K", "prompt $G"]
        else:
            cmd = ["bash", "--norc", "--noprofile", "-i"]
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env={**os.environ, "PS1": "", "PROMPT_COMMAND": ""},
        )

    def run(self, command: str, timeout: int = 30) -> str:
        if self._proc is None or self._proc.poll() is not None:
            self._spawn()
        sentinel = f"__NANO_DONE_{uuid.uuid4().hex}__"
        if sys.platform == "win32":
            payload = f"{command}\r\necho {sentinel}\r\n"
        else:
            payload = f"{command}\necho {sentinel}\n"
        assert self._proc and self._proc.stdin and self._proc.stdout
        self._proc.stdin.write(payload)
        self._proc.stdin.flush()

        deadline = time.monotonic() + timeout
        out_lines: list[str] = []
        while True:
            if time.monotonic() > deadline:
                self._kill()
                raise ToolError(
                    f"Command exceeded timeout of {timeout}s and was killed: "
                    f"{command!r}"
                )
            line = self._proc.stdout.readline()
            if not line:
                if self._proc.poll() is not None:
                    raise ToolError("Shell process exited unexpectedly.")
                continue
            if sentinel in line:
                # Drop the sentinel echo line itself.
                pre = line.split(sentinel, 1)[0]
                if pre.strip():
                    out_lines.append(pre)
                break
            out_lines.append(line)

        return _truncate("".join(out_lines).rstrip("\r\n") + "\n")

    def _kill(self) -> None:
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.kill()
            except ProcessLookupError:
                pass
        self._proc = None

    def close(self) -> None:
        self._kill()
```

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/test_tools.py -v`
Expected: 5 passed. If `test_bash_truncates_huge_output` is flaky on Windows, ensure `python` is on PATH; otherwise replace with `python -c "import sys;sys.stdout.write('x'*200000)"`.

- [ ] **Step 5: Commit**

```bash
git add nano/tools.py tests/test_tools.py
git commit -m "feat(tools): persistent BashTool with cwd/env survival and timeout"
```

---

## Task 5: `read_file` tool

**Files:**
- Modify: `nano/tools.py` (append `read_file`)
- Modify: `tests/test_tools.py` (append tests)

**Why:** Spec §3.3 — line-numbered output, optional `line_start` / `line_end`. Returning line numbers makes `edit_file` reasoning easier for the model.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_tools.py`:
```python
from nano.tools import read_file


def test_read_file_full(tmp_workdir):
    p = tmp_workdir / "a.txt"
    p.write_text("line1\nline2\nline3\n")
    out = read_file(str(p))
    assert "1\tline1" in out
    assert "2\tline2" in out
    assert "3\tline3" in out


def test_read_file_range(tmp_workdir):
    p = tmp_workdir / "a.txt"
    p.write_text("\n".join(f"row{i}" for i in range(1, 11)) + "\n")
    out = read_file(str(p), line_start=3, line_end=5)
    assert "3\trow3" in out
    assert "5\trow5" in out
    assert "row1" not in out
    assert "row6" not in out


def test_read_file_missing_raises(tmp_workdir):
    with pytest.raises(ToolError) as exc:
        read_file(str(tmp_workdir / "no.txt"))
    assert "not found" in str(exc.value).lower()


def test_read_file_binary_rejected(tmp_workdir):
    p = tmp_workdir / "blob.bin"
    p.write_bytes(b"\x00\x01\x02\x03BINARY\xff")
    with pytest.raises(ToolError) as exc:
        read_file(str(p))
    assert "binary" in str(exc.value).lower() or "decode" in str(exc.value).lower()
```

- [ ] **Step 2: Run, verify failure**

Run: `pytest tests/test_tools.py::test_read_file_full -v`
Expected: ImportError on `read_file`.

- [ ] **Step 3: Implement `read_file`**

Append to `nano/tools.py`:
```python
def read_file(path: str, line_start: int | None = None,
              line_end: int | None = None) -> str:
    p = Path(path)
    if not p.exists():
        raise ToolError(f"File not found: {path}")
    if not p.is_file():
        raise ToolError(f"Not a regular file: {path}")
    try:
        text = p.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        raise ToolError(f"Cannot decode {path} as UTF-8 (binary file?): {e}")

    lines = text.splitlines()
    start = (line_start or 1) - 1
    end = line_end if line_end is not None else len(lines)
    if start < 0 or start > len(lines):
        raise ToolError(f"line_start {line_start} out of range (1..{len(lines)})")
    selected = lines[start:end]
    return _truncate("\n".join(f"{i + start + 1}\t{ln}"
                               for i, ln in enumerate(selected)) + "\n")
```

- [ ] **Step 4: Run, verify pass**

Run: `pytest tests/test_tools.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add nano/tools.py tests/test_tools.py
git commit -m "feat(tools): read_file with optional line range and binary guard"
```

---

## Task 6: `edit_file` tool — exact, fail-loudly

**Files:**
- Modify: `nano/tools.py` (append `edit_file`)
- Modify: `tests/test_tools.py` (append tests)

**Why:** Spec §3.3 — exact string replacement; fails loudly on non-unique matches. The "fail loudly" behavior is what stops the model from clobbering code silently.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_tools.py`:
```python
from nano.tools import edit_file


def test_edit_file_replaces_unique(tmp_workdir):
    p = tmp_workdir / "x.py"
    p.write_text("a = 1\nb = 2\n")
    out = edit_file(str(p), old="b = 2", new="b = 99")
    assert "edited" in out.lower()
    assert p.read_text() == "a = 1\nb = 99\n"


def test_edit_file_creates_when_old_empty(tmp_workdir):
    p = tmp_workdir / "new.py"
    out = edit_file(str(p), old="", new="print('hi')\n")
    assert p.read_text() == "print('hi')\n"
    assert "created" in out.lower()


def test_edit_file_non_unique_raises(tmp_workdir):
    p = tmp_workdir / "y.py"
    p.write_text("x = 1\nx = 1\n")
    with pytest.raises(ToolError) as exc:
        edit_file(str(p), old="x = 1", new="x = 2")
    assert "non-unique" in str(exc.value).lower() or "matches 2" in str(exc.value).lower()
    assert p.read_text() == "x = 1\nx = 1\n"  # unchanged


def test_edit_file_no_match_raises(tmp_workdir):
    p = tmp_workdir / "z.py"
    p.write_text("hello\n")
    with pytest.raises(ToolError) as exc:
        edit_file(str(p), old="nope", new="something")
    assert "not found" in str(exc.value).lower() or "no match" in str(exc.value).lower()
```

- [ ] **Step 2: Run, verify failure**

Run: `pytest tests/test_tools.py -v`
Expected: 4 failures (`edit_file` undefined).

- [ ] **Step 3: Implement `edit_file`**

Append to `nano/tools.py`:
```python
def edit_file(path: str, old: str, new: str) -> str:
    p = Path(path)
    if old == "":
        if p.exists():
            raise ToolError(
                f"edit_file with old='' creates a new file but {path} already exists. "
                f"Read it first, then call with the exact text to replace."
            )
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(new, encoding="utf-8")
        return f"Created {path} ({len(new)} chars)."

    if not p.exists():
        raise ToolError(f"File not found: {path}")
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count == 0:
        raise ToolError(
            f"old string not found in {path}. Re-read the file and try again."
        )
    if count > 1:
        raise ToolError(
            f"old string matches {count} places in {path} — must be unique. "
            f"Add surrounding context to disambiguate."
        )
    p.write_text(text.replace(old, new, 1), encoding="utf-8")
    return f"Edited {path} (1 replacement, {len(old)}→{len(new)} chars)."
```

- [ ] **Step 4: Run, verify pass**

Run: `pytest tests/test_tools.py -v`
Expected: 13 passed.

- [ ] **Step 5: Commit**

```bash
git add nano/tools.py tests/test_tools.py
git commit -m "feat(tools): edit_file with strict uniqueness check"
```

---

## Task 7: Tool registry + JSON-Schema descriptions

**Files:**
- Modify: `nano/tools.py` (append `TOOLS` registry, schema dicts)
- Modify: `tests/test_tools.py` (append registry test)

**Why:** The agent loop dispatches tool calls by name. The schemas in this registry are exactly what gets sent to providers, so this is the canonical contract surface. Keeping schema next to impl keeps drift impossible.

- [ ] **Step 1: Write failing test**

Append to `tests/test_tools.py`:
```python
from nano.tools import TOOLS, dispatch


def test_registry_has_three_tools():
    assert {t["name"] for t in TOOLS} == {"bash", "read_file", "edit_file"}
    for t in TOOLS:
        assert "description" in t and t["description"]
        assert t["input_schema"]["type"] == "object"


def test_dispatch_runs_read_file(tmp_workdir, bash):
    p = tmp_workdir / "f.txt"
    p.write_text("hello\n")
    out = dispatch("read_file", {"path": str(p)}, bash=bash)
    assert "hello" in out


def test_dispatch_unknown_tool(bash):
    with pytest.raises(ToolError) as exc:
        dispatch("nope", {}, bash=bash)
    assert "unknown tool" in str(exc.value).lower()
```

- [ ] **Step 2: Run, verify failure**

Run: `pytest tests/test_tools.py -v`
Expected: 3 new failures.

- [ ] **Step 3: Implement registry + dispatch**

Append to `nano/tools.py`:
```python
TOOLS: list[dict[str, Any]] = [
    {
        "name": "bash",
        "description": (
            "Run a shell command in a persistent session. cwd, env, and shell "
            "state are preserved across calls. Use for running tests, listing "
            "files, building, anything stateful."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout": {"type": "integer", "default": 30,
                            "description": "Seconds before kill. Default 30."},
            },
            "required": ["command"],
        },
    },
    {
        "name": "read_file",
        "description": (
            "Read a UTF-8 text file. Returns 1-indexed lines prefixed with "
            "'<n>\\t'. Use line_start/line_end to slice large files."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "line_start": {"type": "integer", "minimum": 1},
                "line_end": {"type": "integer", "minimum": 1},
            },
            "required": ["path"],
        },
    },
    {
        "name": "edit_file",
        "description": (
            "Replace exactly one occurrence of `old` with `new` in the file. "
            "Fails if `old` is missing or matches more than one location. "
            "Pass old='' to create a new file with `new` as content."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old": {"type": "string"},
                "new": {"type": "string"},
            },
            "required": ["path", "old", "new"],
        },
    },
]


def dispatch(name: str, arguments: dict[str, Any], *, bash: BashTool) -> str:
    if name == "bash":
        return bash.run(arguments["command"], timeout=arguments.get("timeout", 30))
    if name == "read_file":
        return read_file(arguments["path"],
                         arguments.get("line_start"), arguments.get("line_end"))
    if name == "edit_file":
        return edit_file(arguments["path"], arguments["old"], arguments["new"])
    raise ToolError(f"Unknown tool: {name}")
```

- [ ] **Step 4: Run, verify pass**

Run: `pytest tests/test_tools.py -v`
Expected: 16 passed.

- [ ] **Step 5: Commit**

```bash
git add nano/tools.py tests/test_tools.py
git commit -m "feat(tools): registry + dispatch with JSON-Schema descriptions"
```

---

## Task 8: Agent loop — reactive cycle with iteration cap

**Files:**
- Create: `nano/agent.py`
- Create: `tests/test_agent.py`

**Why:** Spec §3.2 — reactive cycle, end_turn → break, tool_use → execute and feed back, cap on iterations + tokens. Truncation lives here too (next task).

- [ ] **Step 1: Write failing test using a fake provider**

`tests/test_agent.py`:
```python
import pytest

from nano.agent import Agent, AgentResult
from nano.providers import StepResult, ToolCall, Usage
from nano.tools import BashTool


class FakeProvider:
    """Returns a scripted sequence of StepResults; raises if we run past."""
    model = "fake-model"

    def __init__(self, scripted: list[StepResult]) -> None:
        self.scripted = list(scripted)
        self.calls: list[dict] = []

    def step(self, messages, tools, system) -> StepResult:
        self.calls.append({"messages": list(messages),
                           "tools": tools, "system": system})
        if not self.scripted:
            raise AssertionError("FakeProvider exhausted")
        return self.scripted.pop(0)


def _u(i, o):
    return Usage(input_tokens=i, output_tokens=o)


def test_agent_one_shot_end_turn():
    fp = FakeProvider([
        StepResult(text="task done", tool_calls=[], stop_reason="end_turn",
                   usage=_u(10, 5)),
    ])
    agent = Agent(provider=fp, system="sys", max_iterations=10)
    result = agent.run("solve x")

    assert isinstance(result, AgentResult)
    assert result.final_text == "task done"
    assert result.stop_reason == "end_turn"
    assert result.iterations == 1
    assert result.total_input_tokens == 10
    assert result.total_output_tokens == 5


def test_agent_executes_tool_then_completes(tmp_workdir):
    p = tmp_workdir / "a.txt"
    p.write_text("hello\n")

    fp = FakeProvider([
        StepResult(
            text="reading", tool_calls=[ToolCall(
                id="t1", name="read_file", arguments={"path": str(p)})],
            stop_reason="tool_use", usage=_u(50, 10),
        ),
        StepResult(text="done", tool_calls=[], stop_reason="end_turn",
                   usage=_u(70, 4)),
    ])
    agent = Agent(provider=fp, system="sys", max_iterations=10)
    result = agent.run("read it")

    assert result.iterations == 2
    assert result.final_text == "done"
    # second step must have seen the tool_result we appended
    second_call_msgs = fp.calls[1]["messages"]
    user_with_tool_result = [m for m in second_call_msgs if m["role"] == "user"][-1]
    assert "hello" in str(user_with_tool_result["content"])


def test_agent_iteration_cap_stops_loop():
    looper = [
        StepResult(text="loop",
                   tool_calls=[ToolCall(id=f"t{i}", name="bash",
                                        arguments={"command": "echo i"})],
                   stop_reason="tool_use", usage=_u(1, 1))
        for i in range(20)
    ]
    fp = FakeProvider(looper)
    agent = Agent(provider=fp, system="sys", max_iterations=3)
    result = agent.run("loop forever")
    assert result.iterations == 3
    assert result.stop_reason == "max_iterations"


def test_agent_token_cap_stops_loop():
    huge = [
        StepResult(text=None,
                   tool_calls=[ToolCall(id="t1", name="bash",
                                        arguments={"command": "echo x"})],
                   stop_reason="tool_use", usage=_u(50_000, 100)),
        StepResult(text="ok", tool_calls=[], stop_reason="end_turn", usage=_u(50_000, 50)),
    ]
    fp = FakeProvider(huge)
    agent = Agent(provider=fp, system="sys", max_iterations=10,
                  max_input_tokens=80_000)
    result = agent.run("burn budget")
    assert result.stop_reason == "max_tokens"
```

- [ ] **Step 2: Run, verify failure**

Run: `pytest tests/test_agent.py -v`
Expected: ImportError on `Agent` / `AgentResult`.

- [ ] **Step 3: Implement `Agent`**

`nano/agent.py`:
```python
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from .providers import Provider, StepResult, ToolCall
from .tools import TOOLS, BashTool, ToolError, dispatch


@dataclass
class AgentResult:
    final_text: str | None
    stop_reason: str  # end_turn | max_iterations | max_tokens | error
    iterations: int
    total_input_tokens: int
    total_output_tokens: int
    total_cache_read_tokens: int
    transcript: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Agent:
    provider: Provider
    system: str
    max_iterations: int = 30
    max_input_tokens: int = 200_000
    on_event: Callable[[dict[str, Any]], None] | None = None
    bash: BashTool | None = None

    def __post_init__(self) -> None:
        if self.bash is None:
            self.bash = BashTool()

    def _emit(self, event: dict[str, Any]) -> None:
        if self.on_event:
            self.on_event(event)

    def run(self, task: str) -> AgentResult:
        messages: list[dict[str, Any]] = [{"role": "user", "content": task}]
        transcript: list[dict[str, Any]] = [{"type": "user", "content": task}]
        total_in = total_out = total_cache = 0
        iteration = 0

        while True:
            iteration += 1
            if iteration > self.max_iterations:
                return AgentResult(
                    final_text=None, stop_reason="max_iterations",
                    iterations=iteration - 1,
                    total_input_tokens=total_in, total_output_tokens=total_out,
                    total_cache_read_tokens=total_cache, transcript=transcript,
                )

            sr: StepResult = self.provider.step(messages, TOOLS, self.system)
            total_in += sr.usage.input_tokens
            total_out += sr.usage.output_tokens
            total_cache += sr.usage.cache_read_tokens

            transcript.append({
                "type": "assistant", "text": sr.text,
                "tool_calls": [tc.model_dump() for tc in sr.tool_calls],
                "stop_reason": sr.stop_reason, "usage": sr.usage.model_dump(),
            })
            self._emit({"type": "assistant", "text": sr.text,
                        "tool_calls": sr.tool_calls})

            messages.append(self._assistant_message(sr))

            if sr.stop_reason == "end_turn" or not sr.tool_calls:
                return AgentResult(
                    final_text=sr.text, stop_reason="end_turn",
                    iterations=iteration,
                    total_input_tokens=total_in, total_output_tokens=total_out,
                    total_cache_read_tokens=total_cache, transcript=transcript,
                )

            tool_results = self._execute_tool_calls(sr.tool_calls, transcript)
            messages.append({"role": "user", "content": tool_results})

            if total_in >= self.max_input_tokens:
                return AgentResult(
                    final_text=None, stop_reason="max_tokens",
                    iterations=iteration,
                    total_input_tokens=total_in, total_output_tokens=total_out,
                    total_cache_read_tokens=total_cache, transcript=transcript,
                )

    def _assistant_message(self, sr: StepResult) -> dict[str, Any]:
        # Internal canonical shape: assistant carries text + structured tool_calls.
        # Each provider re-serializes from this form.
        content_blocks: list[dict[str, Any]] = []
        if sr.text:
            content_blocks.append({"type": "text", "text": sr.text})
        for tc in sr.tool_calls:
            content_blocks.append({"type": "tool_use", "id": tc.id,
                                   "name": tc.name, "input": tc.arguments})
        return {
            "role": "assistant",
            "content": content_blocks,
            "tool_calls": [tc.model_dump() for tc in sr.tool_calls],
        }

    def _execute_tool_calls(self, calls: list[ToolCall],
                            transcript: list[dict[str, Any]]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for call in calls:
            try:
                output = dispatch(call.name, call.arguments, bash=self.bash)
                is_error = False
            except ToolError as e:
                output = f"ERROR: {e}"
                is_error = True
            transcript.append({"type": "tool_result", "id": call.id,
                               "name": call.name, "output": output,
                               "is_error": is_error})
            self._emit({"type": "tool_result", "id": call.id,
                        "output": output, "is_error": is_error})
            results.append({"type": "tool_result", "tool_use_id": call.id,
                            "content": output, "is_error": is_error})
        return results
```

- [ ] **Step 4: Run, verify pass**

Run: `pytest tests/test_agent.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add nano/agent.py tests/test_agent.py
git commit -m "feat(agent): reactive loop with iteration + token caps"
```

---

## Task 9: Truncation policy — drop oldest tool_result, keep skeleton

**Files:**
- Modify: `nano/agent.py` (add `_truncate_history` and call site)
- Modify: `tests/test_agent.py` (append truncation test)

**Why:** Spec §3.5 — on overflow, drop oldest tool_result content (not the messages — keep the structural skeleton). Log every truncation event. This is the difference between "stops working at long horizon" and "keeps grinding."

- [ ] **Step 1: Write failing test**

Append to `tests/test_agent.py`:
```python
def test_agent_truncates_oldest_tool_result_when_history_grows():
    # Five tool_use rounds then a final end_turn. Truncation budget set so
    # the oldest tool_result must be replaced with a placeholder before the
    # last step is sent to the provider.
    big = "x" * 5000
    rounds = []
    for i in range(5):
        rounds.append(StepResult(
            text=f"step{i}",
            tool_calls=[ToolCall(id=f"t{i}", name="bash",
                                 arguments={"command": "echo " + big})],
            stop_reason="tool_use", usage=_u(100, 10)))
    rounds.append(StepResult(text="done", tool_calls=[], stop_reason="end_turn",
                             usage=_u(100, 10)))
    fp = FakeProvider(rounds)

    class _RecordingBash:
        def run(self, command, timeout=30):
            return command.removeprefix("echo ")

    agent = Agent(provider=fp, system="sys",
                  max_iterations=20, max_input_tokens=10**9,
                  bash=_RecordingBash())
    agent.truncation_char_budget = 8000  # forces truncation by step 4+
    result = agent.run("loop")

    assert result.stop_reason == "end_turn"
    truncations = [t for t in result.transcript if t.get("type") == "truncation"]
    assert truncations, "expected at least one truncation event"
    last_call_messages = fp.calls[-1]["messages"]
    seen_placeholder = any(
        isinstance(m.get("content"), list)
        and any(b.get("content", "").startswith("[truncated")
                for b in m["content"] if b.get("type") == "tool_result")
        for m in last_call_messages
    )
    assert seen_placeholder
```

- [ ] **Step 2: Run, verify failure**

Run: `pytest tests/test_agent.py::test_agent_truncates_oldest_tool_result_when_history_grows -v`
Expected: AssertionError on truncation event missing.

- [ ] **Step 3: Implement truncation in `nano/agent.py`**

Add a class attribute and a method, then call it before each `provider.step`. Modify `Agent` like so:

```python
@dataclass
class Agent:
    provider: Provider
    system: str
    max_iterations: int = 30
    max_input_tokens: int = 200_000
    truncation_char_budget: int = 120_000  # ≈ 30k tokens of tool_result content
    on_event: Callable[[dict[str, Any]], None] | None = None
    bash: BashTool | None = None
```

In `run()`, before calling `self.provider.step(...)`, insert:
```python
            self._truncate_if_needed(messages, transcript)
            sr: StepResult = self.provider.step(messages, TOOLS, self.system)
```

Add the method (place above `_assistant_message`):
```python
    def _truncate_if_needed(self, messages: list[dict[str, Any]],
                            transcript: list[dict[str, Any]]) -> None:
        def total_chars() -> int:
            n = 0
            for m in messages:
                c = m.get("content")
                if isinstance(c, str):
                    n += len(c)
                elif isinstance(c, list):
                    for b in c:
                        n += len(b.get("text", "")) + len(b.get("content", ""))
            return n

        if total_chars() <= self.truncation_char_budget:
            return

        # Drop oldest tool_result block content first; keep the message and id.
        for m in messages:
            if not isinstance(m.get("content"), list):
                continue
            for b in m["content"]:
                if b.get("type") == "tool_result" and not str(
                        b.get("content", "")).startswith("[truncated"):
                    original_len = len(b.get("content", ""))
                    b["content"] = f"[truncated — {original_len} chars dropped]"
                    transcript.append({"type": "truncation",
                                       "tool_use_id": b.get("tool_use_id"),
                                       "dropped_chars": original_len})
                    if total_chars() <= self.truncation_char_budget:
                        return
```

- [ ] **Step 4: Run, verify pass**

Run: `pytest tests/test_agent.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add nano/agent.py tests/test_agent.py
git commit -m "feat(agent): truncation drops oldest tool_result, keeps skeleton + logs event"
```

---

## Task 10: System prompt + tool descriptions

**Files:**
- Create: `nano/prompts.py`
- Create: `tests/test_prompts.py`

**Why:** Spec §3.5 — <1000 tokens, drafted from first principles. The "<1000 tokens" constraint is a structural test; we enforce it programmatically.

- [ ] **Step 1: Write failing tests**

`tests/test_prompts.py`:
```python
import re

from nano.prompts import SYSTEM_PROMPT, count_tokens_approx


def test_system_prompt_under_1000_tokens():
    assert count_tokens_approx(SYSTEM_PROMPT) < 1000, (
        f"system prompt = ~{count_tokens_approx(SYSTEM_PROMPT)} tokens, "
        f"hard cap is 1000 (spec §3.5)"
    )


def test_system_prompt_mentions_three_tools():
    s = SYSTEM_PROMPT.lower()
    assert "bash" in s
    assert "read_file" in s
    assert "edit_file" in s


def test_system_prompt_no_filler_phrases():
    forbidden = ["you are an expert", "i'd be happy", "as an ai"]
    s = SYSTEM_PROMPT.lower()
    for phrase in forbidden:
        assert phrase not in s, f"filler phrase present: {phrase!r}"
```

- [ ] **Step 2: Run, verify failure**

Run: `pytest tests/test_prompts.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `nano/prompts.py`**

```python
SYSTEM_PROMPT = """\
You are a coding agent. The user gives you a task in a working repository. \
You complete it by reading code and running commands.

Tools:
- bash(command, timeout=30): run a shell command in a persistent session. cwd \
and env survive across calls. Use it to list files, run tests, build, grep, \
and inspect anything stateful.
- read_file(path, line_start?, line_end?): read a UTF-8 file. Lines are \
1-indexed and prefixed "<n>\\t". Slice large files with line_start/line_end.
- edit_file(path, old, new): replace exactly one occurrence of `old` with \
`new`. Fails loudly if `old` is missing or non-unique. Pass old="" to create a \
new file with `new` as its content.

Operating rules:
- Read before you write. Use read_file or bash (cat / sed) to confirm code \
before edit_file.
- When edit_file fails on non-uniqueness, add surrounding context to make \
`old` unique. Never weaken the match.
- Run the existing tests after non-trivial changes. If there are no tests, \
write a small one when it lets you verify the change.
- Prefer small, surgical edits. Do not rewrite a file when an edit_file will do.
- When you finish, end your turn with a one-paragraph summary of what you \
changed and how you verified it. No trailing tool calls.
- If a tool result starts with "ERROR:", read the message, diagnose the cause, \
and adjust. Do not retry the same call unchanged.
- If you are blocked, say so explicitly and stop — do not loop on the same \
failed approach.
"""


def count_tokens_approx(text: str) -> int:
    """4 chars ≈ 1 token rule of thumb. Good enough for the cap test."""
    return max(1, len(text) // 4)
```

- [ ] **Step 4: Run, verify pass**

Run: `pytest tests/test_prompts.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add nano/prompts.py tests/test_prompts.py
git commit -m "feat(prompts): system prompt and approximate token counter (<1000 tokens)"
```

---

## Task 11: CLI — `nano run "task"`

**Files:**
- Create: `nano/cli.py`
- Create: `tests/test_cli.py`

**Why:** Spec §3.6 — minimal entry point, ~50 LOC. Loads provider from env/flag, runs agent, prints rich output.

- [ ] **Step 1: Write failing test**

`tests/test_cli.py`:
```python
from unittest.mock import MagicMock, patch

from nano.cli import build_provider, main


def test_build_provider_anthropic_by_default(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    p = build_provider(model="claude-opus-4-7", base_url=None)
    assert p.__class__.__name__ == "AnthropicProvider"


def test_build_provider_openai_for_gpt_model(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    p = build_provider(model="gpt-5", base_url=None)
    assert p.__class__.__name__ == "OpenAIProvider"


def test_build_provider_openai_with_base_url():
    p = build_provider(model="local/llama3", base_url="http://localhost:8000/v1")
    assert p.__class__.__name__ == "OpenAIProvider"
    assert p.base_url == "http://localhost:8000/v1"


def test_main_runs_agent_and_prints(monkeypatch, capsys):
    fake_agent = MagicMock()
    fake_agent.run.return_value = MagicMock(
        final_text="DONE",
        stop_reason="end_turn",
        iterations=2,
        total_input_tokens=100,
        total_output_tokens=20,
        total_cache_read_tokens=80,
    )
    with patch("nano.cli.Agent", return_value=fake_agent), \
         patch("nano.cli.build_provider", return_value=MagicMock(model="m")):
        rc = main(["run", "do the thing", "--model", "m"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "DONE" in out
```

- [ ] **Step 2: Run, verify failure**

Run: `pytest tests/test_cli.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `nano/cli.py`**

```python
from __future__ import annotations

import argparse
import sys

from rich.console import Console
from rich.panel import Panel

from .agent import Agent
from .prompts import SYSTEM_PROMPT
from .providers import AnthropicProvider, OpenAIProvider, Provider

_console = Console()


def build_provider(*, model: str, base_url: str | None) -> Provider:
    if base_url:
        return OpenAIProvider(model=model, base_url=base_url)
    if model.startswith(("claude", "anthropic")):
        return AnthropicProvider(model=model)
    return OpenAIProvider(model=model)


def _print_event(event: dict) -> None:
    et = event["type"]
    if et == "assistant" and event.get("text"):
        _console.print(Panel(event["text"], title="assistant", border_style="cyan"))
    elif et == "tool_result":
        title = "tool_result" + (" (error)" if event.get("is_error") else "")
        _console.print(Panel(event["output"][:2000], title=title,
                             border_style="red" if event.get("is_error") else "green"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nano")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="Run the agent on a task description.")
    run.add_argument("task", help="Plain-English task description.")
    run.add_argument("--model", default="claude-opus-4-7")
    run.add_argument("--base-url", default=None,
                     help="OpenAI-compatible base URL (Together, vLLM, etc.).")
    run.add_argument("--max-iterations", type=int, default=30)
    args = parser.parse_args(argv)

    provider = build_provider(model=args.model, base_url=args.base_url)
    agent = Agent(provider=provider, system=SYSTEM_PROMPT,
                  max_iterations=args.max_iterations, on_event=_print_event)
    result = agent.run(args.task)
    _console.print(f"\n[bold]stop:[/] {result.stop_reason}  "
                   f"iterations={result.iterations}  "
                   f"in={result.total_input_tokens}  "
                   f"out={result.total_output_tokens}  "
                   f"cache_read={result.total_cache_read_tokens}")
    if result.final_text:
        _console.print(Panel(result.final_text, title="final", border_style="bold"))
    return 0 if result.stop_reason == "end_turn" else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run, verify pass**

Run: `pytest tests/test_cli.py -v`
Expected: 4 passed.

- [ ] **Step 5: Smoke test (manual)**

Run: `set ANTHROPIC_API_KEY=sk-...` (PowerShell: `$env:ANTHROPIC_API_KEY="sk-..."`) then `nano run "list the files in this repo and tell me what each top-level directory does"`
Expected: agent reads, runs `bash ls`, summarizes.

- [ ] **Step 6: Commit**

```bash
git add nano/cli.py tests/test_cli.py
git commit -m "feat(cli): nano run with provider routing on model name + --base-url"
```

---

## Task 12: Eval log writer — `eval/log.py`

**Files:**
- Create: `eval/log.py`
- Create: `tests/test_log.py`

**Why:** Spec §3.7 — every run produces `manifest.json` + per-task transcript JSONL. This module is the single writer; eval adapters call it.

- [ ] **Step 1: Write failing test**

`tests/test_log.py`:
```python
import json

import pytest

from eval.log import RunLog, TaskRecord


def test_run_log_writes_manifest_and_transcripts(tmp_path):
    rl = RunLog(
        results_root=tmp_path,
        benchmark="terminal-bench",
        benchmark_version="v0.1.5",
        model="claude-opus-4-7",
        provider="anthropic",
        harness_commit="abc123",
        command="python -m eval.terminal_bench_adapter --model claude-opus-4-7",
    )
    rl.start()
    rl.add_task(TaskRecord(
        task_id="task-001", passed=True, iterations=4, wall_seconds=12.0,
        input_tokens=1000, output_tokens=200, cache_read_tokens=800,
        cost_usd=0.05,
        transcript=[{"type": "user", "content": "do x"}],
        failure_reason=None,
    ))
    rl.add_task(TaskRecord(
        task_id="task-002", passed=False, iterations=30, wall_seconds=180.0,
        input_tokens=20000, output_tokens=4000, cache_read_tokens=15000,
        cost_usd=1.50,
        transcript=[{"type": "user", "content": "do y"}],
        failure_reason="max_iterations",
    ))
    manifest_path = rl.finish(grader_output_path=tmp_path / "grader.txt")

    manifest = json.loads(manifest_path.read_text())
    assert manifest["benchmark"] == "terminal-bench"
    assert manifest["score"] == pytest.approx(0.5)
    assert manifest["model"] == "claude-opus-4-7"
    assert manifest["harness_commit"] == "abc123"
    assert len(manifest["tasks"]) == 2
    assert "task-002" in manifest["failed_task_samples"]

    t1 = manifest["tasks"][0]
    transcript_path = manifest_path.parent / t1["transcript_path"]
    lines = transcript_path.read_text().strip().splitlines()
    assert json.loads(lines[0]) == {"type": "user", "content": "do x"}
```

- [ ] **Step 2: Run, verify failure**

Run: `pytest tests/test_log.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `eval/log.py`**

```python
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class TaskRecord:
    task_id: str
    passed: bool
    iterations: int
    wall_seconds: float
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cost_usd: float
    transcript: list[dict[str, Any]] = field(default_factory=list)
    failure_reason: str | None = None


@dataclass
class RunLog:
    results_root: Path
    benchmark: str
    benchmark_version: str
    model: str
    provider: str
    harness_commit: str
    command: str
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    _started_at: str = ""
    _tasks: list[TaskRecord] = field(default_factory=list)

    @property
    def run_dir(self) -> Path:
        return Path(self.results_root) / self.benchmark / self.model / self.run_id

    def start(self) -> None:
        self._started_at = datetime.now(timezone.utc).isoformat()
        self.run_dir.mkdir(parents=True, exist_ok=True)

    def add_task(self, rec: TaskRecord) -> None:
        transcript_path = self.run_dir / f"{rec.task_id}.transcript.jsonl"
        with transcript_path.open("w", encoding="utf-8") as f:
            for event in rec.transcript:
                f.write(json.dumps(event) + "\n")
        self._tasks.append(rec)

    def finish(self, grader_output_path: Path | None = None) -> Path:
        completed_at = datetime.now(timezone.utc).isoformat()
        passed = sum(1 for t in self._tasks if t.passed)
        total = len(self._tasks) or 1
        manifest = {
            "run_id": self.run_id,
            "benchmark": self.benchmark,
            "benchmark_version": self.benchmark_version,
            "model": self.model,
            "provider": self.provider,
            "harness_commit": self.harness_commit,
            "command": self.command,
            "started_at": self._started_at,
            "completed_at": completed_at,
            "score": passed / total,
            "grader_output_path": (str(grader_output_path)
                                   if grader_output_path else None),
            "tasks": [self._task_summary(t) for t in self._tasks],
            "failed_task_samples": [t.task_id for t in self._tasks
                                    if not t.passed][:10],
        }
        out = self.run_dir / "manifest.json"
        out.write_text(json.dumps(manifest, indent=2))
        return out

    def _task_summary(self, t: TaskRecord) -> dict[str, Any]:
        d = asdict(t)
        d.pop("transcript")
        d["transcript_path"] = f"{t.task_id}.transcript.jsonl"
        return d
```

- [ ] **Step 4: Run, verify pass**

Run: `pytest tests/test_log.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add eval/log.py tests/test_log.py
git commit -m "feat(eval): RunLog writes per-run manifest + per-task transcript JSONL"
```

---

## Task 13: v0 head-to-head harness (§3.8)

**Files:**
- Create: `eval/headtohead.py`
- Create: `eval/h2h_tasks/` (directory; one folder per task with `prompt.txt`, `setup.sh`, `verify.sh`)
- Create: `tests/test_headtohead.py`

**Why:** Spec §3.8 — internal falsification gate, not published. Same model + 8–10 hand-curated coding tasks. Compares pass/fail, iterations, tokens, transcript readability against one larger open-source harness (Archon).

This is internal-only. We do not count its LOC against the eval/ budget; the spec excludes it explicitly in this plan's File Structure section.

- [ ] **Step 1: Write task fixtures**

For each of 8 tasks (the comparison set), create `eval/h2h_tasks/<task-id>/`:
- `prompt.txt` — task description handed to both agents.
- `setup.sh` — populates `$WORKDIR` (a fresh tempdir) with the starting repo / files.
- `verify.sh` — exits 0 iff the task is solved. Run inside `$WORKDIR` after the agent finishes.

Initial 8 tasks (representative; tune after first dry run):
1. `fix-failing-test` — tiny Python repo with 1 failing pytest case; agent must fix the implementation.
2. `add-cli-flag` — a CLI script; agent must add `--verbose` flag with tests.
3. `refactor-extract-function` — extract a long function into two with no behavior change; existing tests must still pass.
4. `bug-off-by-one` — failing pagination test caused by a `<` instead of `<=`.
5. `regex-tighten` — overly permissive regex passes invalid emails; tighten + tests pass.
6. `migrate-print-to-logging` — replace `print` calls with `logging.getLogger(__name__).info`.
7. `fix-import-cycle` — two modules import each other; agent must break the cycle.
8. `dependency-pin` — `requirements.txt` has unpinned deps; pin to versions present in a frozen `pip freeze` snapshot in the task dir.

- [ ] **Step 2: Write failing test for the runner**

`tests/test_headtohead.py`:
```python
from pathlib import Path

from eval.headtohead import HeadToHeadRunner, TaskSpec


def test_runner_loads_task_specs(tmp_path):
    task_dir = tmp_path / "tasks" / "demo"
    task_dir.mkdir(parents=True)
    (task_dir / "prompt.txt").write_text("Make foo print 'hi'.")
    (task_dir / "setup.sh").write_text("#!/bin/sh\necho '' > $WORKDIR/foo.py\n")
    (task_dir / "verify.sh").write_text("#!/bin/sh\ngrep -q hi $WORKDIR/foo.py\n")

    specs = HeadToHeadRunner.load_specs(tmp_path / "tasks")
    assert len(specs) == 1
    assert specs[0].task_id == "demo"
    assert "Make foo" in specs[0].prompt
```

- [ ] **Step 3: Run, verify failure**

Run: `pytest tests/test_headtohead.py -v`
Expected: ImportError.

- [ ] **Step 4: Implement `eval/headtohead.py`**

```python
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from nano.agent import Agent
from nano.prompts import SYSTEM_PROMPT
from nano.providers import Provider


@dataclass
class TaskSpec:
    task_id: str
    prompt: str
    task_dir: Path

    def setup(self, workdir: Path) -> None:
        env = {**os.environ, "WORKDIR": str(workdir)}
        subprocess.run(["bash", str(self.task_dir / "setup.sh")],
                       env=env, check=True)

    def verify(self, workdir: Path) -> bool:
        env = {**os.environ, "WORKDIR": str(workdir)}
        rc = subprocess.run(["bash", str(self.task_dir / "verify.sh")],
                            env=env).returncode
        return rc == 0


@dataclass
class TaskOutcome:
    task_id: str
    passed: bool
    iterations: int
    input_tokens: int
    output_tokens: int
    wall_seconds: float
    transcript: list


class HeadToHeadRunner:
    @staticmethod
    def load_specs(tasks_root: Path) -> list[TaskSpec]:
        specs: list[TaskSpec] = []
        for d in sorted(p for p in tasks_root.iterdir() if p.is_dir()):
            specs.append(TaskSpec(
                task_id=d.name,
                prompt=(d / "prompt.txt").read_text().strip(),
                task_dir=d,
            ))
        return specs

    def run_nano(self, specs: list[TaskSpec],
                 provider: Provider) -> list[TaskOutcome]:
        outcomes: list[TaskOutcome] = []
        for spec in specs:
            with tempfile.TemporaryDirectory(prefix="h2h-") as wd:
                workdir = Path(wd)
                spec.setup(workdir)
                cwd = os.getcwd()
                os.chdir(workdir)
                try:
                    agent = Agent(provider=provider, system=SYSTEM_PROMPT)
                    t0 = time.monotonic()
                    result = agent.run(spec.prompt)
                    elapsed = time.monotonic() - t0
                    passed = spec.verify(workdir)
                finally:
                    os.chdir(cwd)
                outcomes.append(TaskOutcome(
                    task_id=spec.task_id, passed=passed,
                    iterations=result.iterations,
                    input_tokens=result.total_input_tokens,
                    output_tokens=result.total_output_tokens,
                    wall_seconds=elapsed,
                    transcript=result.transcript,
                ))
        return outcomes


def summarize(outcomes: list[TaskOutcome]) -> str:
    passed = sum(1 for o in outcomes if o.passed)
    total = len(outcomes) or 1
    avg_iter = sum(o.iterations for o in outcomes) / total
    avg_in = sum(o.input_tokens for o in outcomes) / total
    return (f"pass: {passed}/{total} ({passed/total:.0%})  "
            f"avg_iter: {avg_iter:.1f}  avg_in: {avg_in:.0f}")
```

- [ ] **Step 5: Run, verify pass**

Run: `pytest tests/test_headtohead.py -v`
Expected: 1 passed.

- [ ] **Step 6: Commit**

```bash
git add eval/headtohead.py eval/h2h_tasks tests/test_headtohead.py
git commit -m "feat(eval): v0 head-to-head harness with 8-task fixture set"
```

- [ ] **Step 7: Manual run vs Archon**

Run nano-harness:
`python -c "from eval.headtohead import HeadToHeadRunner, summarize; from nano.providers import AnthropicProvider; r = HeadToHeadRunner(); s = r.load_specs(Path('eval/h2h_tasks')); o = r.run_nano(s, AnthropicProvider(model='claude-opus-4-7')); print(summarize(o))"`

Then run Archon (or chosen comparator) on the same 8 tasks with the same model. Record both transcripts.

**Decision gate (per §3.8):** If nano-harness is dramatically worse on pass-rate or iterations-to-success, stop and revisit the wedge in the spec before spending money on official evals. Otherwise, proceed to Task 14. Document the comparison in `results/v0_h2h.md`.

---

## Task 14: Terminal-Bench adapter

**Files:**
- Create: `eval/terminal_bench_adapter.py`
- Create: `tests/test_terminal_bench_adapter.py`

**Why:** Spec §3.6 — Terminal-Bench ships its own runner with `AbstractAgent`. We implement that interface; their harness drives nano-harness; the official grader scores. We do not write a scorer.

- [ ] **Step 1: Read Terminal-Bench's `AbstractAgent` interface**

Run: `pip install terminal-bench` (in the `eval` extras group).
Run: `python -c "from terminal_bench.agents.base import AbstractAgent; help(AbstractAgent)"`

Read the methods that are required (typically `name`, `model`, and a `solve(task, container) -> AgentResult`-style entry). Confirm signatures before writing the adapter; the official API is the source of truth, not this plan.

- [ ] **Step 2: Write failing test (with Terminal-Bench types mocked)**

`tests/test_terminal_bench_adapter.py`:
```python
from unittest.mock import MagicMock, patch

from eval.terminal_bench_adapter import NanoTerminalBenchAgent


def test_adapter_translates_task_to_agent_run():
    agent_runs = []

    fake_agent = MagicMock()
    fake_agent.run.return_value = MagicMock(
        final_text="solved", stop_reason="end_turn", iterations=3,
        total_input_tokens=500, total_output_tokens=80, total_cache_read_tokens=400,
        transcript=[{"type": "user", "content": "do x"}],
    )

    with patch("eval.terminal_bench_adapter.Agent", return_value=fake_agent), \
         patch("eval.terminal_bench_adapter.AnthropicProvider") as P:
        P.return_value = MagicMock(model="claude-opus-4-7")
        adapter = NanoTerminalBenchAgent(model="claude-opus-4-7")
        instruction = "Make a file called done.txt"
        out = adapter.perform_task(instruction=instruction, session=MagicMock())

    fake_agent.run.assert_called_once_with(instruction)
    assert out.final_text == "solved" or hasattr(out, "final_text")
```

- [ ] **Step 3: Run, verify failure**

Run: `pytest tests/test_terminal_bench_adapter.py -v`
Expected: ImportError.

- [ ] **Step 4: Implement `eval/terminal_bench_adapter.py`**

The exact base class and method names are determined by the installed `terminal-bench` version (read in Step 1). Use the structure below and rename `perform_task` to whatever the real abstract method is.

```python
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from terminal_bench.agents.base import AbstractAgent  # type: ignore

from nano.agent import Agent, AgentResult
from nano.prompts import SYSTEM_PROMPT
from nano.providers import AnthropicProvider, OpenAIProvider, Provider
from eval.log import RunLog, TaskRecord


class _SessionBash:
    """BashTool replacement that funnels commands through Terminal-Bench's
    container session instead of a local subprocess. Same `run(command, timeout)`
    surface so nano.agent.Agent and nano.tools.dispatch don't notice."""

    def __init__(self, session: Any) -> None:
        self._session = session

    def run(self, command: str, timeout: int = 30) -> str:
        # Adjust to the actual Terminal-Bench session API observed in Step 1.
        return self._session.run(command, timeout=timeout)

    def close(self) -> None:
        pass


def _build_provider(model: str, base_url: str | None) -> Provider:
    if base_url:
        return OpenAIProvider(model=model, base_url=base_url)
    return AnthropicProvider(model=model) if model.startswith("claude") \
        else OpenAIProvider(model=model)


class NanoTerminalBenchAgent(AbstractAgent):
    """Hands Terminal-Bench tasks to nano-harness. Only the loop, tools,
    and prompt are nano's; scoring stays with Terminal-Bench."""

    def __init__(self, model: str = "claude-opus-4-7",
                 base_url: str | None = None) -> None:
        self._model = model
        self._provider = _build_provider(model=model, base_url=base_url)

    @property
    def name(self) -> str:
        return "nano-harness"

    @property
    def model(self) -> str:
        return self._model

    def perform_task(self, instruction: str, session: Any) -> AgentResult:
        agent = Agent(
            provider=self._provider,
            system=SYSTEM_PROMPT,
            bash=_SessionBash(session),
        )
        return agent.run(instruction)


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="claude-opus-4-7")
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--results-root", default="results")
    parser.add_argument("--limit", type=int, default=None,
                        help="Cap number of tasks (smoke test).")
    args = parser.parse_args()

    from terminal_bench import TerminalBench  # type: ignore
    tb = TerminalBench()  # default task set; pin version via env if needed
    bench_version = getattr(tb, "version", "unknown")

    rl = RunLog(
        results_root=Path(args.results_root),
        benchmark="terminal-bench",
        benchmark_version=bench_version,
        model=args.model,
        provider="anthropic" if args.model.startswith("claude") else "openai",
        harness_commit=_git_commit(),
        command=" ".join([sys.executable, "-m",
                          "eval.terminal_bench_adapter"] + sys.argv[1:]),
    )
    rl.start()

    nano = NanoTerminalBenchAgent(model=args.model, base_url=args.base_url)
    # Use Terminal-Bench's official runner; do not roll our own loop here.
    report = tb.run(agent=nano, concurrency=args.concurrency, limit=args.limit)

    for task_report in report.tasks:
        rl.add_task(TaskRecord(
            task_id=task_report.task_id,
            passed=task_report.passed,
            iterations=getattr(task_report.agent_result, "iterations", 0),
            wall_seconds=task_report.wall_seconds,
            input_tokens=getattr(task_report.agent_result,
                                 "total_input_tokens", 0),
            output_tokens=getattr(task_report.agent_result,
                                  "total_output_tokens", 0),
            cache_read_tokens=getattr(task_report.agent_result,
                                      "total_cache_read_tokens", 0),
            cost_usd=task_report.cost_usd,
            transcript=getattr(task_report.agent_result, "transcript", []),
            failure_reason=getattr(task_report, "failure_reason", None),
        ))

    grader_path = Path(args.results_root) / "terminal-bench" / args.model \
        / rl.run_id / "grader.txt"
    grader_path.write_text(report.raw_grader_output if hasattr(
        report, "raw_grader_output") else "")
    rl.finish(grader_output_path=grader_path)
    print(f"score: {report.score:.3f}  manifest: {grader_path.parent}/manifest.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

> Adjust the Terminal-Bench import surface (`TerminalBench`, `report.tasks`, `task_report.agent_result`) to whatever the installed package actually exposes. The shape is mocked here; the real API is locked in Step 1 and we adapt.

- [ ] **Step 5: Run, verify pass**

Run: `pytest tests/test_terminal_bench_adapter.py -v`
Expected: 1 passed.

- [ ] **Step 6: Smoke run on 5 tasks**

Run: `python -m eval.terminal_bench_adapter --model claude-opus-4-7 --limit 5`
Expected: 5 tasks attempted; at least 1 passes; `results/terminal-bench/claude-opus-4-7/<run-id>/manifest.json` exists with score, per-task entries, and transcript files.

- [ ] **Step 7: Commit**

```bash
git add eval/terminal_bench_adapter.py tests/test_terminal_bench_adapter.py
git commit -m "feat(eval): Terminal-Bench AbstractAgent adapter + smoke runner"
```

---

## Task 15: First public Terminal-Bench number (build-order step 8)

**Files:**
- Modify: prompts/truncation/iteration cap based on smoke results.
- Create: `results/terminal-bench/<model>/<run-id>/` (committed artifact).
- Create: `README.md` with leaderboard scaffold.

- [ ] **Step 1: Full Terminal-Bench run vs latest Claude Opus**

Run: `python -m eval.terminal_bench_adapter --model claude-opus-4-7 --concurrency 4`
Expected: full run completes; `manifest.json` written; score visible in stdout.

- [ ] **Step 2: Inspect failures, iterate prompt + caps**

Look at `manifest["failed_task_samples"]` and read 5 transcripts. Common patterns to fix at the prompt or cap level (do not benchmark-tune; spec §3.7 forbids it):
- Loops on the same edit_file failure → prompt note already covers; check it's actually rendered.
- Hits `max_iterations` repeatedly → consider raising from 30 to 50 once, but only if not score-tuning.
- Tool args malformed by the model → prompt nudge for arg shape.

Re-run after each prompt change. Score must stabilize (two consecutive runs within 2 percentage points) before publishing.

- [ ] **Step 3: Commit the artifact**

```bash
git add results/terminal-bench
git commit -m "results(terminal-bench): first published run, claude-opus-4-7, <score>%"
```

- [ ] **Step 4: Write README leaderboard scaffold**

`README.md`:
```markdown
# nano-harness

A coding agent you can read in an afternoon, benchmark in an evening, and audit line by line.

**Score-per-line-of-code, not raw score.** Core loop is small enough to read end-to-end. Eval runs use the official benchmark graders unchanged — every cell links to a reproducible artifact.

## LOC by layer

| Layer | LOC |
|---|---|
| `nano/agent.py` | TBD |
| `nano/tools.py` | TBD |
| `nano/providers.py` | TBD |
| `nano/prompts.py` | TBD |
| `nano/cli.py` | TBD |
| `eval/` (adapters + log) | TBD |
| **Core (`nano/`) total** | TBD / 500 cap |

(Numbers filled by `scripts/loc.py`; see §3.6 of the design doc — we report honestly, no composite slogan number.)

## Leaderboard

| Model | Terminal-Bench | SWE-bench Verified | Run artifact |
|---|---|---|---|
| Claude Opus 4.7 | TBD | — | [run](results/terminal-bench/claude-opus-4-7/<run-id>) |

## Reproduce

```sh
git clone <this repo>
pip install -e ".[dev,eval]"
export ANTHROPIC_API_KEY=...
python -m eval.terminal_bench_adapter --model claude-opus-4-7 --concurrency 4
```
```

- [ ] **Step 5: Commit README**

```bash
git add README.md
git commit -m "docs: README leaderboard scaffold + reproduce instructions"
```

---

## Task 16: Multi-model Terminal-Bench runs (build-order step 9)

**Files:**
- Create: `results/terminal-bench/<other-models>/<run-id>/`
- Modify: `README.md` (fill leaderboard rows)

- [ ] **Step 1: Run Claude Sonnet (latest)**

Run: `python -m eval.terminal_bench_adapter --model claude-sonnet-4-6 --concurrency 4`

- [ ] **Step 2: Run latest GPT frontier via OpenAI**

Run: `python -m eval.terminal_bench_adapter --model gpt-5 --concurrency 4`

- [ ] **Step 3: Run a strong open coding model via OpenAI-compatible**

Run (Together example):
`python -m eval.terminal_bench_adapter --model deepseek-coder-v3 --base-url https://api.together.xyz/v1 --concurrency 4`

- [ ] **Step 4: Run a local open-weight baseline**

Stand up llama.cpp or vLLM (decision deferred per §5; pick whichever ships first):
- llama.cpp: `./llama-server -m <gguf> --port 8000 -c 32000 --jinja`
- vLLM: `python -m vllm.entrypoints.openai.api_server --model <hf-id> --port 8000`

Then run:
`python -m eval.terminal_bench_adapter --model local/<name> --base-url http://localhost:8000/v1 --concurrency 1`

- [ ] **Step 5: Fill leaderboard rows**

For each completed run, edit `README.md` `Leaderboard` table. Each cell links to its `results/.../manifest.json`. Do **not** edit prompts between cells; same harness across rows is the entire credibility argument.

- [ ] **Step 6: Commit**

```bash
git add results/terminal-bench README.md
git commit -m "results(terminal-bench): multi-model leaderboard"
```

---

## Task 17: SWE-bench Verified adapter + run (build-order step 10)

**Files:**
- Create: `eval/swebench_adapter.py`
- Create: `tests/test_swebench_adapter.py`
- Create: `results/swe-bench-verified/<model>/<run-id>/`

**Why:** Spec §3.6 — produce predictions in SWE-bench's expected format and hand to the official Docker grader. Same harness, no benchmark-specific tweaks (§3.7).

- [ ] **Step 1: Read SWE-bench Verified prediction format**

Run: `pip install swebench`
Run: `python -c "import swebench; help(swebench.harness.run_evaluation)"`

Confirm: predictions are a list of `{"instance_id", "model_name_or_path", "model_patch"}` JSONL. The grader takes that JSONL plus the dataset and runs each instance in Docker.

- [ ] **Step 2: Write failing test**

`tests/test_swebench_adapter.py`:
```python
from unittest.mock import MagicMock, patch

from eval.swebench_adapter import solve_instance


def test_solve_instance_returns_patch_when_agent_writes_one(tmp_workdir):
    fake_agent = MagicMock()
    fake_agent.run.return_value = MagicMock(
        final_text="patched", stop_reason="end_turn", iterations=5,
        total_input_tokens=100, total_output_tokens=20, total_cache_read_tokens=80,
        transcript=[],
    )
    instance = {
        "instance_id": "django__django-12345",
        "repo": "django/django",
        "base_commit": "abc",
        "problem_statement": "fix bug",
    }

    with patch("eval.swebench_adapter.Agent", return_value=fake_agent), \
         patch("eval.swebench_adapter._prepare_repo", return_value=tmp_workdir), \
         patch("eval.swebench_adapter._diff",
               return_value="diff --git a/x b/x\n@@\n-old\n+new\n"):
        result = solve_instance(instance, provider=MagicMock(model="m"))
    assert result["instance_id"] == "django__django-12345"
    assert result["model_patch"].startswith("diff --git")
```

- [ ] **Step 3: Run, verify failure**

Run: `pytest tests/test_swebench_adapter.py -v`
Expected: ImportError.

- [ ] **Step 4: Implement `eval/swebench_adapter.py`**

```python
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from nano.agent import Agent
from nano.prompts import SYSTEM_PROMPT
from nano.providers import AnthropicProvider, OpenAIProvider, Provider
from eval.log import RunLog, TaskRecord


def _prepare_repo(repo: str, base_commit: str, dest: Path) -> Path:
    subprocess.run(["git", "clone", f"https://github.com/{repo}.git", str(dest)],
                   check=True, capture_output=True)
    subprocess.run(["git", "checkout", base_commit], cwd=dest,
                   check=True, capture_output=True)
    return dest


def _diff(repo_dir: Path) -> str:
    out = subprocess.run(["git", "diff"], cwd=repo_dir,
                         check=True, capture_output=True, text=True)
    return out.stdout


def solve_instance(instance: dict[str, Any], *, provider: Provider) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="swe-") as wd:
        repo_dir = _prepare_repo(instance["repo"], instance["base_commit"], Path(wd))
        cwd = os.getcwd()
        os.chdir(repo_dir)
        try:
            agent = Agent(provider=provider, system=SYSTEM_PROMPT,
                          max_iterations=50, max_input_tokens=400_000)
            result = agent.run(instance["problem_statement"])
            patch = _diff(repo_dir)
        finally:
            os.chdir(cwd)
    return {
        "instance_id": instance["instance_id"],
        "model_name_or_path": getattr(provider, "model", "unknown"),
        "model_patch": patch,
        "_meta": {
            "iterations": result.iterations,
            "input_tokens": result.total_input_tokens,
            "output_tokens": result.total_output_tokens,
            "cache_read_tokens": result.total_cache_read_tokens,
            "stop_reason": result.stop_reason,
            "transcript": result.transcript,
        },
    }


def _build_provider(model: str, base_url: str | None) -> Provider:
    if base_url:
        return OpenAIProvider(model=model, base_url=base_url)
    return AnthropicProvider(model=model) if model.startswith("claude") \
        else OpenAIProvider(model=model)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="claude-opus-4-7")
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--results-root", default="results")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    from datasets import load_dataset  # type: ignore
    ds = load_dataset("princeton-nlp/SWE-bench_Verified", split="test")
    if args.limit:
        ds = ds.select(range(args.limit))

    provider = _build_provider(args.model, args.base_url)
    rl = RunLog(
        results_root=Path(args.results_root),
        benchmark="swe-bench-verified",
        benchmark_version="2024-09",  # current Verified version at impl time
        model=args.model,
        provider="anthropic" if args.model.startswith("claude") else "openai",
        harness_commit=subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True).strip(),
        command=" ".join([sys.executable, "-m",
                          "eval.swebench_adapter"] + sys.argv[1:]),
    )
    rl.start()

    predictions_path = rl.run_dir / "predictions.jsonl"
    with predictions_path.open("w") as fp:
        for instance in ds:
            pred = solve_instance(instance, provider=provider)
            meta = pred.pop("_meta")
            fp.write(json.dumps(pred) + "\n")
            rl.add_task(TaskRecord(
                task_id=instance["instance_id"],
                passed=False,  # filled by grader pass below
                iterations=meta["iterations"],
                wall_seconds=0.0,  # filled if we wrap in timer
                input_tokens=meta["input_tokens"],
                output_tokens=meta["output_tokens"],
                cache_read_tokens=meta["cache_read_tokens"],
                cost_usd=0.0,
                transcript=meta["transcript"],
                failure_reason=meta["stop_reason"]
                    if meta["stop_reason"] != "end_turn" else None,
            ))

    # Hand predictions.jsonl to the official SWE-bench grader.
    grader_log = rl.run_dir / "grader.txt"
    subprocess.run(
        [sys.executable, "-m", "swebench.harness.run_evaluation",
         "--predictions_path", str(predictions_path),
         "--dataset_name", "princeton-nlp/SWE-bench_Verified",
         "--run_id", rl.run_id],
        check=True, stdout=open(grader_log, "w"))

    rl.finish(grader_output_path=grader_log)
    print(f"manifest: {rl.run_dir}/manifest.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run, verify pass**

Run: `pytest tests/test_swebench_adapter.py -v`
Expected: 1 passed.

- [ ] **Step 6: Smoke run on 5 instances**

Run: `python -m eval.swebench_adapter --model claude-opus-4-7 --limit 5`
Expected: predictions.jsonl + grader output produced; at least 1 passes.

- [ ] **Step 7: Full run**

Run: `python -m eval.swebench_adapter --model claude-opus-4-7`

- [ ] **Step 8: Commit artifact + update leaderboard**

```bash
git add results/swe-bench-verified eval/swebench_adapter.py tests/test_swebench_adapter.py README.md
git commit -m "feat(eval): SWE-bench Verified adapter + first run + leaderboard cell"
```

---

## Task 18: LOC reporter + final budget check

**Files:**
- Create: `scripts/loc.py`
- Modify: `README.md` (fill LOC table)

**Why:** Spec §3.6 — "Report LOC honestly, by layer." Run on every commit-of-record so the README cannot drift.

- [ ] **Step 1: Implement reporter**

`scripts/loc.py`:
```python
"""Print LOC by file under nano/ and eval/. Counts non-blank, non-comment lines."""
from __future__ import annotations

from pathlib import Path


def count_loc(path: Path) -> int:
    n = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        n += 1
    return n


def main() -> int:
    layers = {
        "nano/agent.py": Path("nano/agent.py"),
        "nano/tools.py": Path("nano/tools.py"),
        "nano/providers.py": Path("nano/providers.py"),
        "nano/prompts.py": Path("nano/prompts.py"),
        "nano/cli.py": Path("nano/cli.py"),
        "eval/log.py": Path("eval/log.py"),
        "eval/terminal_bench_adapter.py": Path("eval/terminal_bench_adapter.py"),
        "eval/swebench_adapter.py": Path("eval/swebench_adapter.py"),
    }
    rows: list[tuple[str, int]] = []
    for label, p in layers.items():
        if p.exists():
            rows.append((label, count_loc(p)))
    core_total = sum(n for label, n in rows if label.startswith("nano/"))
    eval_total = sum(n for label, n in rows if label.startswith("eval/"))
    for label, n in rows:
        print(f"{label:40s} {n}")
    print(f"{'core total':40s} {core_total} / 500")
    print(f"{'eval total':40s} {eval_total} / 200")
    return 0 if core_total <= 500 and eval_total <= 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run reporter**

Run: `python scripts/loc.py`
Expected: every layer line, both totals under cap. If over: refactor (per §3.6, never raise the cap).

- [ ] **Step 3: Update README LOC table**

Edit `README.md` LOC table with the actual numbers from Step 2. Replace `TBD` cells.

- [ ] **Step 4: Commit**

```bash
git add scripts/loc.py README.md
git commit -m "tooling: scripts/loc.py reports LOC by layer; README updated to actual numbers"
```

---

## Task 19: Final ship — public repo + post (build-order step 11)

**Files:**
- Modify: `README.md` (fill all leaderboard cells, link artifacts).
- Create: GitHub repo, push.

- [ ] **Step 1: Verify success criteria (spec §6)**

Manually walk the checklist:
- [ ] Core ≤ 500 LOC, eval ≤ 200 LOC (run `python scripts/loc.py`)
- [ ] Terminal-Bench score ≥ 30% with latest Claude Opus
- [ ] SWE-bench Verified score ≥ 30% with same harness
- [ ] At least 3 models in leaderboard table, every cell links to artifact
- [ ] README leads with the table; first paragraph names score-per-LOC framing
- [ ] A competent dev can read all of `nano/` and explain the loop

If any unchecked, fix before shipping. Do not raise caps to make scores look better; per §1, the brand is small-and-honest, not maximally-tuned.

- [ ] **Step 2: Push to GitHub**

```bash
gh repo create nano-harness --public --source . --remote origin --push
```

- [ ] **Step 3: Cold-cache reproduce check**

In a clean directory:
```sh
git clone https://github.com/<user>/nano-harness.git
cd nano-harness
pip install -e ".[dev,eval]"
export ANTHROPIC_API_KEY=...
python -m eval.terminal_bench_adapter --model claude-opus-4-7 --concurrency 4 --limit 5
```
Expected: smoke run completes; score within 2 points of published cell on the same 5 instances.

- [ ] **Step 4: Blog / X thread**

Lead with: score-per-LOC table, link to artifacts, link to repo. Do not lead with "smallest agent" — lead with "smallest agent that scores X on the official Terminal-Bench grader, here's the artifact." (Per §1, credibility first, minimalism as the supporting evidence.)

- [ ] **Step 5: Final commit (if README updates needed)**

```bash
git add README.md
git commit -m "docs: final leaderboard with all four model rows + artifact links"
git push
```

---

## Open questions to resolve during execution (spec §5)

These are explicitly deferred to data, not pre-decided:

- **Cost ceiling per benchmark run.** Track-and-report only for v1 (per §5). Add a hard cap only after a real cost surprise.
- **Local model serving.** llama.cpp vs vLLM — decided in Task 16 Step 4 based on whichever has working OpenAI-compatible chat-completions with tool-use support at run-time.
- **Failure-mode tagging.** Add a `failure_reason` taxonomy (`timeout`, `max_iterations`, `wrong_answer`, `tool_error`) only after Task 15 reveals the failure distribution. The current `failure_reason` field already accepts free-form strings.
- **Iteration cap (start at 30, tune).** Tune in Task 15 Step 2 based on smoke results.
- **Truncation budget (start at ~120k chars).** Tune likewise in Task 15.

---

## Self-review notes

Spec coverage walk:

- §1 goal — README scaffold (Task 15) + framing → covered.
- §2 non-goals — no plugin/UI/router code anywhere → covered by omission.
- §3.1 benchmarks — Tasks 14–17 implement both → covered.
- §3.2 loop shape — Task 8 implements reactive cycle → covered.
- §3.3 tool set — Tasks 4–7 implement three tools + registry → covered.
- §3.4 provider strategy — Tasks 1–3 implement two providers + leaderboard slot covered in Task 16 → covered.
- §3.5 context management — Tasks 2 (cache), 9 (truncation), 10 (prompt) → covered.
- §3.6 repo layout + LOC budget — Task 0 lays it out, Task 18 enforces → covered.
- §3.7 eval logging — Task 12 (writer) + Tasks 14, 17 (consumers) → covered.
- §3.8 v0 head-to-head — Task 13 → covered.
- §4 build order — Tasks 0–19 mirror the 11-step order with bootstrap and LOC reporter inserted → covered.
- §6 success criteria — Task 19 Step 1 walks the checklist → covered.

No placeholders found in code blocks (every step shows the code or the exact command).

Type consistency — `StepResult`, `ToolCall`, `Usage`, `AgentResult`, `TaskRecord`, `RunLog` are referenced consistently across tasks. `BashTool.run(command, timeout)` signature is identical at definition (Task 4) and use sites (Tasks 7, 8, 14).
