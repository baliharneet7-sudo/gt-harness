"""Regression gate: existing tests that passed at the task's start commit and fail now.

At the agent's first submit, GT runs the repository's OWN tests - test files present and
unchanged since the start commit, related to the files the agent changed - in the agent's
environment. A test that fails now is re-run on a clean copy of the start commit
(`git archive`, the agent's tree is never touched). Only tests that pass there and fail now
are regressions; they hold the submit once, by name.

Only what a developer has is used: the repository, its history and its tests. Nothing the
benchmark's verifier adds (see docs/benchmarks/benchmark_integrity.md). A test that was
already failing, cannot be collected, or whose run cannot be confirmed on the start commit
never holds the submit: every uncertain case fails open.

Evidence (DeepSWE GT runs 1-2, error analysis only): 16% of failed runs broke existing
tests; vulture (both runs) and sqlfmt (run 2) passed every hidden requirement test and
failed only on repository tests the agent could have run.
"""
from __future__ import annotations

import re
import shlex
import time
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Callable

# execute(command) -> (output, returncode); runs a shell command in the agent's environment.
Execute = Callable[[str], "tuple[str, int]"]

MAX_TEST_FILES = 8
RUN_TIMEOUT_SECONDS = 150
BASE_COPY = "/tmp/gt-regression-base"
_PY_TEST = re.compile(r"(^|/)(test_[^/]+|[^/]+_test)\.py$")
_GO_TEST = re.compile(r"_test\.go$")
_PY_FAILED = re.compile(r"^(?:FAILED|ERROR) (\S+?::\S+?)(?: - |$)", re.M)
_PY_SUMMARY = re.compile(r"=+ .*?\b(\d+ (?:passed|failed)|no tests ran)\b.*=+|^\d+ (?:passed|failed)", re.M)
_GO_FAILED = re.compile(r"^\s*--- FAIL: (\S+)", re.M)
_GO_RAN = re.compile(r"^(?:ok|FAIL|---)\s", re.M)


@dataclass
class RegressionResult:
    regressions: list[str] = field(default_factory=list)
    failing_now: list[str] = field(default_factory=list)
    candidates: list[str] = field(default_factory=list)
    skipped: str = ""
    seconds: float = 0.0

    def message(self) -> str:
        if not self.regressions:
            return ""
        lines = "\n".join(f"  - {name}" for name in self.regressions[:12])
        return ("[GT] regression check: these existing tests passed at the task's starting commit and fail "
                f"with your changes:\n{lines}\n"
                "They describe behaviour the repository already had. Fix the code so they pass again "
                "(do not edit or delete these tests), rerun them, then submit again.")


def _q(value: str) -> str:
    return shlex.quote(value)


def candidate_test_files(changed: list[str], reachable: list[str], exists_at_start: Callable[[str], bool]) -> list[str]:
    """Existing, untouched test files related to the change: reachable tests first, then
    test files named after a changed module (test_<stem>.py, <stem>_test.go)."""
    changed_set = set(changed)
    sources = [c for c in changed if not (_PY_TEST.search(c) or _GO_TEST.search(c))]
    picked: list[str] = []
    for item in reachable:
        path = item.split("::", 1)[0]
        if path not in picked:
            picked.append(path)
    for src in sources:
        p = PurePosixPath(src)
        stem, parent = p.stem, str(p.parent)
        if p.suffix == ".py":
            picked += [f"tests/test_{stem}.py", f"test/test_{stem}.py", f"{parent}/tests/test_{stem}.py",
                       f"{parent}/test_{stem}.py"]
        elif p.suffix == ".go":
            picked.append(f"{parent}/{stem}_test.go")
    out: list[str] = []
    for path in picked:
        path = path.lstrip("./")
        if (path in out or path in changed_set or not (_PY_TEST.search(path) or _GO_TEST.search(path))
                or not exists_at_start(path)):
            continue
        out.append(path)
    return out[:MAX_TEST_FILES]


def _pytest(execute: Execute, cwd: str, targets: list[str], pythonpath: str = "") -> tuple[set[str], bool]:
    # PYTHONDONTWRITEBYTECODE: the agent's tree must end exactly as the gate found it (no
    # __pycache__ an agent's `git add -A` could commit); the pytest cache is off below.
    env = "PYTHONDONTWRITEBYTECODE=1 "
    env += f"PYTHONPATH={_q(pythonpath)}${{PYTHONPATH:+:$PYTHONPATH}} " if pythonpath else ""
    cmd = (f"cd {_q(cwd)} && {env}timeout {RUN_TIMEOUT_SECONDS} python -m pytest -q -rfE -p no:cacheprovider "
           f"--no-header {' '.join(_q(t) for t in targets)} 2>&1 | tail -n 400")
    output, _ = execute(cmd)
    ran = bool(_PY_SUMMARY.search(output)) and "No module named pytest" not in output
    return set(_PY_FAILED.findall(output)), ran


def _gotest(execute: Execute, cwd: str, packages: list[str], run: str = "") -> tuple[set[str], bool]:
    flt = f" -run {_q(run)}" if run else ""
    cmd = (f"cd {_q(cwd)} && timeout {RUN_TIMEOUT_SECONDS} go test -count=1{flt} "
           f"{' '.join(_q('./' + p) for p in packages)} 2>&1 | tail -n 400")
    output, _ = execute(cmd)
    return set(_GO_FAILED.findall(output)), bool(_GO_RAN.search(output))


def check(root: str, baseline: str, changed: list[str], reachable: list[str], execute: Execute,
          exists_at_start: Callable[[str], bool]) -> RegressionResult:
    started = time.perf_counter()
    result = RegressionResult()
    try:
        if not baseline:
            result.skipped = "no_start_commit"
            return result
        files = candidate_test_files(changed, reachable, exists_at_start)
        result.candidates = files
        if not files:
            result.skipped = "no_related_existing_tests"
            return result
        py = [f for f in files if f.endswith(".py")]
        go_pkgs = sorted({str(PurePosixPath(f).parent) for f in files if f.endswith(".go")})
        now_py, ran_py = _pytest(execute, root, py) if py else (set(), False)
        now_go, ran_go = _gotest(execute, root, go_pkgs) if go_pkgs else (set(), False)
        result.failing_now = sorted(now_py | now_go)
        if not result.failing_now:
            result.skipped = "all_pass" if (ran_py or ran_go) else "tests_did_not_run"
            return result
        # Same tests on a clean copy of the start commit; the agent's tree is not touched.
        out, rc = execute(f"rm -rf {BASE_COPY} && mkdir -p {BASE_COPY} && "
                          f"git -c safe.directory='*' -C {_q(root)} archive {_q(baseline)} | tar -x -C {BASE_COPY} "
                          f"&& echo GT_BASE_READY")
        if "GT_BASE_READY" not in out:
            result.skipped = "start_copy_failed"
            return result
        regressions: list[str] = []
        if now_py:
            base_failed, base_ran = _pytest(execute, BASE_COPY, sorted(now_py),
                                            pythonpath=f"{BASE_COPY}:{BASE_COPY}/src")
            if base_ran:
                regressions += sorted(now_py - base_failed)
        if now_go:
            names = "|".join(re.escape(n.split("/")[0]) for n in sorted(now_go))
            base_failed, base_ran = _gotest(execute, BASE_COPY, go_pkgs, run=f"^({names})$")
            if base_ran:
                regressions += sorted(now_go - base_failed)
        result.regressions = regressions
        if not regressions:
            result.skipped = "failures_predate_the_change"
        return result
    except Exception as exc:  # noqa: BLE001 - the gate fails open, never costs the submit
        result.skipped = f"error:{type(exc).__name__}"
        return result
    finally:
        result.seconds = round(time.perf_counter() - started, 2)


__all__ = ["RegressionResult", "candidate_test_files", "check"]
