import os
import sys

import pytest

from nano.tools import BashTool, ToolError, read_file


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


@pytest.mark.skipif(sys.platform != "win32", reason="cmd.exe prompt artifacts are Windows-only")
def test_bash_strips_cmd_prompt_artifacts_on_windows(bash):
    out = bash.run("echo clean", timeout=5)
    assert out.startswith("clean") or out.lstrip().startswith("clean"), \
        f"prompt artifacts leaked: {out!r}"
    assert ">" not in out.split("clean", 1)[0], f"leading '>' present: {out!r}"


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
