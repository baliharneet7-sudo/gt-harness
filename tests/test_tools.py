import os
import sys

import pytest

from nano.tools import TOOLS, BashTool, ToolError, dispatch, edit_file, read_file


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
    bash.run(f'cd "{sub}"', timeout=5)
    out = bash.run("cd" if bash._is_cmd else "pwd", timeout=5)
    assert "sub" in out


def test_bash_env_persists_across_calls(bash):
    bash.run("set NANO_TEST=42" if bash._is_cmd
             else "export NANO_TEST=42", timeout=5)
    out = bash.run("echo %NANO_TEST%" if bash._is_cmd
                   else "echo $NANO_TEST", timeout=5)
    assert "42" in out


def test_bash_handles_posix_compound_commands(bash):
    # Models write bash: pipes, &&, ; . These must work on every platform
    # (the t2 head-to-head failure was cmd.exe choking on exactly this).
    if bash._is_cmd:
        pytest.skip("no bash available; cmd.exe fallback cannot run POSIX")
    out = bash.run("echo one && echo two ; echo three | cat", timeout=5)
    assert "one" in out and "two" in out and "three" in out


def test_bash_timeout_raises_or_reports(bash):
    with pytest.raises(ToolError) as exc:
        bash.run("ping -n 6 127.0.0.1 > nul" if bash._is_cmd
                 else "sleep 5", timeout=1)
    assert "timeout" in str(exc.value).lower()


def test_bash_truncates_huge_output(bash):
    cmd = ("python -c \"print('x'*200000)\"")
    out = bash.run(cmd, timeout=10)
    assert len(out) < 200000
    assert "truncated" in out.lower()


def test_bash_output_has_no_prompt_or_command_echo(bash):
    # Output must be just the command's stdout - no shell prompt, no echoed
    # stdin. A leaked prompt or echo would confuse the model every turn.
    out = bash.run("echo clean", timeout=5)
    assert out.strip() == "clean", f"prompt or echo leaked: {out!r}"


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


def test_dispatch_missing_required_arg_raises_toolerror(bash):
    # A malformed tool call (weak model, truncated JSON) must surface as a
    # ToolError the loop feeds back, never an uncaught KeyError.
    with pytest.raises(ToolError) as exc:
        dispatch("bash", {}, bash=bash)
    assert "command" in str(exc.value)

    with pytest.raises(ToolError):
        dispatch("edit_file", {"path": "x"}, bash=bash)
