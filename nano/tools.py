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


def _strip_cmd_prompt(text: str) -> str:
    """Remove cmd.exe '>' prompt artifacts from captured shell output (Windows)."""
    out_lines: list[str] = []
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        if stripped.startswith(">"):
            stripped = stripped[1:]
            # Drop the line entirely if it's now blank.
            if not stripped.strip():
                continue
            out_lines.append(stripped)
        else:
            out_lines.append(line)
    return "".join(out_lines)


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

    def run(self, command: str, timeout: int = 60) -> str:
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
                    f"{command!r}. The shell was restarted: cwd, env vars, and "
                    f"background processes are reset. Re-establish state if "
                    f"needed; pass a larger timeout for long commands."
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

        joined = "".join(out_lines).rstrip("\r\n") + "\n"
        if sys.platform == "win32":
            joined = _strip_cmd_prompt(joined)
        return _truncate(joined)

    def _kill(self) -> None:
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.kill()
            except ProcessLookupError:
                pass
        self._proc = None

    def __del__(self) -> None:
        try:
            self._kill()
        except Exception:
            pass

    def close(self) -> None:
        self._kill()


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
            f"old string matches {count} places in {path} - must be unique. "
            f"Add surrounding context to disambiguate."
        )
    p.write_text(text.replace(old, new, 1), encoding="utf-8")
    return f"Edited {path} (1 replacement, {len(old)}->{len(new)} chars)."


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
                "timeout": {"type": "integer", "default": 60,
                            "description": "Seconds before kill. Default 60. "
                            "Set generously for builds, installs, and tests."},
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
        return bash.run(arguments["command"], timeout=arguments.get("timeout", 60))
    if name == "read_file":
        return read_file(arguments["path"],
                         arguments.get("line_start"), arguments.get("line_end"))
    if name == "edit_file":
        return edit_file(arguments["path"], arguments["old"], arguments["new"])
    raise ToolError(f"Unknown tool: {name}")
