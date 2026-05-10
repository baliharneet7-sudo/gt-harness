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


@pytest.mark.skipif(sys.platform != "win32", reason="cmd.exe prompt artifacts are Windows-only")
def test_bash_strips_cmd_prompt_artifacts_on_windows(bash):
    out = bash.run("echo clean", timeout=5)
    assert out.startswith("clean") or out.lstrip().startswith("clean"), \
        f"prompt artifacts leaked: {out!r}"
    assert ">" not in out.split("clean", 1)[0], f"leading '>' present: {out!r}"
