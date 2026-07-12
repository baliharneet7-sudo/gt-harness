from __future__ import annotations

import os
import queue
import shlex
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any


def _resolve_shell() -> tuple[list[str], bool]:
    """Pick the persistent shell. Models emit POSIX/bash commands (pipes, &&,
    heredocs, `;`), so we use bash everywhere it exists — including Windows,
    where Git ships bash.exe. cmd.exe is a last resort only; it cannot run the
    commands models actually write. Returns (argv, is_cmd)."""
    if sys.platform != "win32":
        return ["bash", "--norc", "--noprofile"], False
    bash = shutil.which("bash") or next(
        (p for p in (r"C:\Program Files\Git\bin\bash.exe",
                     r"C:\Program Files (x86)\Git\bin\bash.exe")
         if os.path.exists(p)), None)
    if bash:
        return [bash, "--norc", "--noprofile"], False
    return ["cmd.exe", "/Q", "/K", "prompt $G"], True


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
        cmd, self._is_cmd = _resolve_shell()
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env={**os.environ, "PS1": "", "PROMPT_COMMAND": ""},
        )
        # A reader thread drains stdout into a queue so run() can enforce the
        # timeout even when a command produces no output for a long time
        # (a blocking readline() would otherwise sail past the deadline).
        self._lines: queue.Queue[str] = queue.Queue()
        self._reader = threading.Thread(target=self._pump, args=(self._proc,),
                                        daemon=True)
        self._reader.start()

    def _pump(self, proc: subprocess.Popen) -> None:
        for line in proc.stdout:  # type: ignore[union-attr]
            self._lines.put(line)

    def run(self, command: str, timeout: int = 60) -> str:
        if self._proc is None or self._proc.poll() is not None:
            self._spawn()
        sentinel = f"__NANO_DONE_{uuid.uuid4().hex}__"
        nl = "\r\n" if self._is_cmd else "\n"
        assert self._proc and self._proc.stdin
        self._proc.stdin.write(f"{command}{nl}echo {sentinel}{nl}")
        self._proc.stdin.flush()

        deadline = time.monotonic() + timeout
        out_lines: list[str] = []
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._kill()
                raise ToolError(
                    f"Command exceeded timeout of {timeout}s and was killed: "
                    f"{command!r}. The shell was restarted: cwd, env vars, and "
                    f"background processes are reset. Re-establish state if "
                    f"needed; pass a larger timeout for long commands."
                )
            try:
                line = self._lines.get(timeout=min(remaining, 0.5))
            except queue.Empty:
                if self._proc.poll() is not None:
                    raise ToolError("Shell process exited unexpectedly.")
                continue
            if sentinel in line:
                pre = line.split(sentinel, 1)[0]
                if pre.strip():
                    out_lines.append(pre)
                break
            out_lines.append(line)

        joined = "".join(out_lines).rstrip("\r\n") + "\n"
        if self._is_cmd:
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


def _require(arguments: dict[str, Any], name: str, *keys: str) -> None:
    """A malformed tool call (missing required arg, often from a weaker model
    or a truncated JSON blob) must come back as a ToolError the model can fix,
    never an exception that kills the run."""
    missing = [k for k in keys if k not in arguments]
    if missing:
        raise ToolError(
            f"Tool {name!r} called without required argument(s) "
            f"{', '.join(missing)}. Provided: {sorted(arguments)}. "
            f"Re-issue the call with all required arguments."
        )


def _int_arg(arguments: dict[str, Any], key: str, default: int | None = None) -> int | None:
    """Weak models pass numbers as strings ('5' not 5). Coerce; a value that
    won't parse comes back as a ToolError, never a TypeError that kills the run."""
    value = arguments.get(key, default)
    if value is None or isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ToolError(
            f"Argument {key!r} must be an integer, got {value!r}. "
            f"Re-issue the call with an integer value."
        )


def dispatch(name: str, arguments: dict[str, Any], *, bash: BashTool) -> str:
    if name == "bash":
        _require(arguments, name, "command")
        return bash.run(arguments["command"], timeout=_int_arg(arguments, "timeout", 60))
    if name == "read_file":
        _require(arguments, name, "path")
        return read_file(arguments["path"],
                         _int_arg(arguments, "line_start"),
                         _int_arg(arguments, "line_end"))
    if name == "edit_file":
        _require(arguments, name, "path", "old", "new")
        return edit_file(arguments["path"], arguments["old"], arguments["new"])
    raise ToolError(f"Unknown tool: {name}")
