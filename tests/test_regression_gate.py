"""Regression gate (gt_engine.regression_gate), end to end on real git repositories and real
pytest: only a repository test that passed at the start commit and fails now holds the submit.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from gt_engine import regression_gate
from gt_engine.regression_gate import candidate_test_files, check


def _bash() -> str:
    if os.name != "nt":
        return "bash"
    git = shutil.which("git")
    candidates = [parent / sub / "bash.exe" for parent in Path(git).parents for sub in ("bin", "usr/bin")] if git else []
    found = next((str(p) for p in candidates if p.is_file()), None)
    if found is None:
        pytest.skip("Git bash not found")
    return found


def _execute(extra_path: str = ""):
    """Run a shell command like the agent's environment: bash, with this interpreter as `python`."""
    python_dir = Path(sys.executable).parent.as_posix()
    if os.name == "nt":
        python_dir = "/" + python_dir[0].lower() + python_dir[2:]  # C:/x -> /c/x for Git bash

    def run(cmd: str) -> tuple[str, int]:
        full = f'export PATH="{python_dir}:$PATH"; ' + cmd
        done = subprocess.run([_bash(), "-c", full], capture_output=True, text=True, timeout=300)
        return done.stdout + done.stderr, done.returncode

    return run


def _git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _repo(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "repo"
    (root / "pkg").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "config.py").write_text("def limit():\n    return 10\n\ndef name():\n    return 'app'\n", encoding="utf-8")
    (root / "tests" / "test_config.py").write_text(
        "from pkg.config import limit, name\n\n"
        "def test_limit():\n    assert limit() == 10\n\n"
        "def test_name():\n    assert name() == 'app'\n\n"
        "def test_already_broken():\n    assert name() == 'other'\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    _git(root, "add", "-A")
    _git(root, "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "base")
    head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    return root, head


def _exists(root: Path, baseline: str):
    return lambda path: subprocess.run(["git", "-C", str(root), "cat-file", "-e", f"{baseline}:{path}"],
                                       capture_output=True).returncode == 0


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    for var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        monkeypatch.delenv(var, raising=False)
    base = tmp_path / "base-copy"
    monkeypatch.setattr(regression_gate, "BASE_COPY", base.as_posix() if os.name != "nt" else
                        "/" + base.as_posix()[0].lower() + base.as_posix()[2:])


def test_a_broken_existing_test_is_a_regression(tmp_path):
    root, base = _repo(tmp_path)
    (root / "pkg" / "config.py").write_text("def limit():\n    return 20\n\ndef name():\n    return 'app'\n", encoding="utf-8")

    result = check(root.as_posix(), base, ["pkg/config.py"], [], _execute(), _exists(root, base))

    assert result.regressions == ["tests/test_config.py::test_limit"]
    assert "test_limit" in result.message() and "do not edit or delete" in result.message()


def test_a_test_already_failing_at_the_start_is_not_a_regression(tmp_path):
    root, base = _repo(tmp_path)
    (root / "pkg" / "config.py").write_text("def limit():\n    return 10\n\ndef name():\n    return 'app'\n# edit\n", encoding="utf-8")

    result = check(root.as_posix(), base, ["pkg/config.py"], [], _execute(), _exists(root, base))

    assert "tests/test_config.py::test_already_broken" in result.failing_now
    assert result.regressions == [] and result.message() == ""
    assert result.skipped == "failures_predate_the_change"


def test_test_files_the_agent_edited_are_not_used(tmp_path):
    root, base = _repo(tmp_path)
    assert candidate_test_files(["pkg/config.py", "tests/test_config.py"], [], _exists(root, base)) == []


def test_new_test_files_do_not_count(tmp_path):
    root, base = _repo(tmp_path)
    (root / "tests" / "test_new.py").write_text("def test_x():\n    assert False\n", encoding="utf-8")
    assert candidate_test_files(["pkg/config.py"], ["tests/test_new.py"], _exists(root, base)) == ["tests/test_config.py"]


def test_no_start_commit_or_no_related_tests_never_holds(tmp_path):
    root, base = _repo(tmp_path)
    assert check(root.as_posix(), "", ["pkg/config.py"], [], _execute(), _exists(root, base)).skipped == "no_start_commit"
    assert check(root.as_posix(), base, ["pkg/other.py"], [], _execute(), _exists(root, base)).skipped == "no_related_existing_tests"


def test_an_environment_without_pytest_fails_open(tmp_path):
    root, base = _repo(tmp_path)
    (root / "pkg" / "config.py").write_text("def limit():\n    return 20\n\ndef name():\n    return 'app'\n", encoding="utf-8")

    def no_pytest(cmd):
        return "/usr/bin/python: No module named pytest\n", 1

    result = check(root.as_posix(), base, ["pkg/config.py"], [], no_pytest, _exists(root, base))
    assert result.regressions == [] and result.skipped == "tests_did_not_run"


def test_the_agent_tree_is_untouched(tmp_path):
    root, base = _repo(tmp_path)
    (root / "pkg" / "config.py").write_text("def limit():\n    return 20\n\ndef name():\n    return 'app'\n", encoding="utf-8")
    before = subprocess.run(["git", "-C", str(root), "status", "--porcelain"], capture_output=True, text=True).stdout

    check(root.as_posix(), base, ["pkg/config.py"], [], _execute(), _exists(root, base))

    after = subprocess.run(["git", "-C", str(root), "status", "--porcelain"], capture_output=True, text=True).stdout
    assert after == before and "return 20" in (root / "pkg" / "config.py").read_text(encoding="utf-8")


def test_any_internal_error_fails_open(tmp_path):
    def boom(cmd):
        raise RuntimeError("container went away")

    root, base = _repo(tmp_path)
    (root / "pkg" / "config.py").write_text("x = 1\n", encoding="utf-8")
    result = check(root.as_posix(), base, ["pkg/config.py"], [], boom, _exists(root, base))
    assert result.regressions == [] and result.skipped.startswith("error:")
