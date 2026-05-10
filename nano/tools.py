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
