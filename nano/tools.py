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
