from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

from scripts.benchmark_progress import aggregate

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "tb2_miniswe_central.yml"
IMPORT = ROOT / "config" / "tb2_gt_import_manifest.json"
# The model pin lives in one place. Repinning it used to mean editing seven
# consumers, and three dispatches bounced from partial repins; this envelope
# test reads the expected strings rather than hardcoding an eighth copy.
MODEL_PIN = json.loads(
    (ROOT / "config" / "benchmark_model.v1.json").read_text(encoding="utf-8")
)


def test_gt_smoke_is_source_bound_and_uses_the_product_agent() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    manifest = json.loads(IMPORT.read_text(encoding="utf-8-sig"))

    assert manifest["baseline_harness_parent"] == (
        "f4aaf2bf88d007334195a6c71a34cd16b82bb8dc"
    )
    assert manifest["gt_source_commit"] == (
        "921bec20d3dbabd12e4b442936d9259c24cdcc74"
    )
    assert "TREATMENT_SHA: ${{ github.sha }}" in text
    assert "GT_SOURCE_SHA: 921bec20d3dbabd12e4b442936d9259c24cdcc74" in text
    assert "eval.pier_gt_harness_adapter:PierGtHarnessMiniSwe246Agent" in text
    assert "eval.miniswe_agent:MiniSweAgent" not in text
    assert "openhands" not in text.lower()
    assert 'MINISWE_AGENT_VERSION: "2.4.6"' in text


def test_gt_smoke_keeps_the_frozen_execution_envelope() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "max-parallel: 20" in text
    assert "options: [gate-one, remaining-19, all-20, subset]" in text
    assert '"gate-one": tasks[:1]' in text
    assert '"remaining-19": tasks[1:]' in text
    assert 'TIMEOUT_MULTIPLIER: "5.0"' in text
    assert 'STEP_LIMIT: "100"' in text
    assert "attempts_per_task" in text
    assert '"parallel": min(20, len(selected))' in text
    assert '"full_task_count": 20' in text
    assert "36d5c8945f6f8d9ae23fe2cea759f16da0c0cea424a98f710cfaa0d9d6fd0303" in text
    assert "actions/cache/restore@v4" in text
    assert "tb2-img-${{ matrix.task }}-${{ env.IMAGE_TAG }}" in text
    assert "Pull the existing GHCR mirror only on cache miss" in text
    assert "uses: ./.github/workflows/deepswe_gt_harness_product.yml" in text
    assert "pre_spend:" in text
    assert "needs: [plan, provider_free]" in text
    assert "needs: [plan, pre_spend]" in text
    assert "Run the real official verifier through Pier without a model" in text
    assert "Prove the exact treatment adapter and environment contract" in text
    assert "PYTHONPATH: ${{ github.workspace }}" in text
    assert "eval.pier_filtered_docker:PierFilteredDockerEnvironment" in text
    assert 'm.version("datacurve-pier")' in text
    assert '"exact_pier_environment_executed": "PASS"' in text
    assert "-a nop" in text
    assert '"task_model_requests": 0' in text
    assert MODEL_PIN["tb2_route_manifest"] in text
    assert "scripts.provider_preflight" in text
    assert '"provider_route_live_canary": "PASS"' in text
    assert "GT_PROVIDER_CONTEXT_WINDOW_TOKENS: ${{ needs.pre_spend.outputs.context_window_tokens }}" in text
    assert "GT_PROVIDER_ROUTING_JSON: ${{ needs.pre_spend.outputs.provider_routing_json }}" in text
    assert "Save the verifier-canary image for paid task reuse" in text
    assert "actions/cache/save@v4" in text


def test_gt_smoke_uses_official_harbor_grades_and_retains_evidence() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    parser = (ROOT / "scripts" / "benchmark_progress.py").read_text(encoding="utf-8")

    assert "pier run" in text
    assert "Run one official Pier TB2 trial" in text
    assert 'DATASET: terminal-bench@2.0' in text
    assert f"MODEL: {MODEL_PIN['model']}" in text
    assert f'--effective-model "{MODEL_PIN["effective_model"]}"' in text
    assert "secrets.OPENROUTER_NEW" in text
    assert "scripts.benchmark_progress emit-harbor" in text
    assert '"official_verifier": True' in parser
    assert '"official_verifier": False' in parser
    assert '"state": "passed" if reward == 1 else "verifier_failed"' in parser
    assert '"state": "infrastructure_failed"' in parser
    assert 'result_path.parent / "verifier" / "reward.txt"' in parser
    assert 'result_path.parent / "verifier" / "ctrf.json"' in parser
    assert "results/terminal-bench/" in text
    assert "benchmark-progress-tb2-gt-${{ github.run_id }}-${{ matrix.task }}" in text
    assert "tb2-gt-smoke20-921bec20-${{ github.run_id }}-task-${{ matrix.task }}" in text


def _planner_namespace() -> dict:
    """Exec the planner's own base-image detection out of the workflow heredoc.

    The functions live inline in the workflow because the planner runs before
    anything is installed, so the test reads them from the file that ships
    them rather than re-implementing the rule and testing the copy.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index("          def final_from_image(")
    end = text.index("          excluded = []")
    namespace: dict = {"re": re}
    exec(compile(textwrap.dedent(text[start:end]), str(WORKFLOW), "exec"), namespace)
    return namespace


def _planner_alpine_detector() -> tuple:
    namespace = _planner_namespace()
    return (
        namespace["final_from_image"],
        namespace["is_alpine_image"],
        namespace["musl_reason"],
    )


# (Dockerfile body, excluded?).  The first case is the defect: excluding on any
# FROM line containing "alpine" drops a multi-stage glibc task out of the
# graded denominator with nothing in the summary to say why.
ALPINE_FIXTURES = (
    (
        "FROM alpine AS builder\nRUN apk add build-base\n"
        "FROM ubuntu:24.04\nCOPY --from=builder /out /out\n",
        False,
    ),
    ("FROM python:3.12-alpine\n", True),
    ("FROM ubuntu # not alpine\n", False),
    ("FROM alpine:3.19\n", True),
    ("FROM --platform=linux/amd64 library/alpine AS base\n", True),
    # A name that merely contains the word is not the distro.
    ("FROM ghcr.io/org/alpine-builder:1\n", False),
    # Documented tag rule: tag tokens split on "-", "alpine" or "alpine<ver>".
    ("FROM node:22-alpine3.20\n", True),
    ("FROM ubuntu:24.04@sha256:0123456789abcdef\n", False),
    ("from alpine\n", True),
    # A heredoc a RUN writes is data this build emits, not a stage it builds.
    # Taking its FROM made a glibc task read as Alpine and silently leave the
    # graded denominator.
    (
        "FROM ubuntu:24.04\n"
        "RUN cat <<'EOF' > /tmp/Dockerfile\n"
        "FROM alpine:3.19\n"
        "EOF\n"
        "RUN echo done\n",
        False,
    ),
    # The heredoc has to CLOSE, or the real final stage after it is lost.
    (
        "RUN cat <<'EOF' > /tmp/Dockerfile\n"
        "FROM alpine:3.19\n"
        "EOF\n"
        "FROM ubuntu:24.04\n",
        False,
    ),
    # <<- with an unquoted word, and a tab-indented terminator.
    (
        "FROM ubuntu:24.04\nRUN cat <<-EOF > /tmp/D\n\tFROM alpine\n\tEOF\n",
        False,
    ),
    # An Alpine task that happens to write a heredoc is still Alpine.
    (
        "RUN cat <<'EOF' > /tmp/Dockerfile\nFROM ubuntu:24.04\nEOF\n"
        "FROM alpine:3.19\n",
        True,
    ),
    # LOW-1: any whitespace after FROM, tab included.
    ("FROM\talpine\n", True),
    ("FROM\tubuntu:24.04\n", False),
    # L-2 (round 7): Docker strips leading whitespace before ANY instruction,
    # FROM included.  Heredoc bodies are skipped and continuations joined, so
    # a line that reaches the FROM test is a logical instruction line - an
    # indented FROM is a stage, and reading it as shell text pinned the final
    # stage on the image above it.
    ("FROM ubuntu:24.04\n  FROM alpine:3.19\n", True),
    ("  FROM ubuntu:24.04\n", False),
    ("\tFROM alpine:3.19\n", True),
    ("FROM alpine:3.19\n   FROM ubuntu:24.04\n", False),
    # M-1: `<<` is a heredoc only as a REDIRECTION.  A left shift inside a
    # quoted string opened a heredoc terminated by "y", which swallowed the
    # rest of the file and made this glibc task read as Alpine.
    (
        'FROM alpine AS b\nRUN echo "shift x<<y bits"\nFROM ubuntu:24.04\n',
        False,
    ),
    # A here-STRING is not a here-doc: `<<<` opened a heredoc named "FROM".
    (
        "FROM alpine AS b\nRUN grep x <<<'FROM alpine'\nFROM ubuntu:24.04\n",
        False,
    ),
    ('FROM ubuntu:24.04\nRUN x <<< "herestring"\n', False),
    ('FROM alpine:3.19\nRUN x <<< "herestring"\n', True),
    # An UNQUOTED heredoc word is still a heredoc.
    (
        "FROM ubuntu:24.04\nRUN cat <<EOF > /tmp/D\nFROM alpine:3.19\nEOF\n",
        False,
    ),
    # And a double-quoted one.
    (
        'FROM ubuntu:24.04\nRUN cat <<"EOF" > /tmp/D\nFROM alpine:3.19\nEOF\n',
        False,
    ),
    # A shift outside quotes is not a redirection either: `x<<y` has no
    # whitespace-delimited word after it that a shell would read as one.
    ("FROM ubuntu:24.04\nRUN test $((x<<y))\nFROM alpine:3.19\n", True),
    # L-3: a top-level ARG default resolves the base this build actually uses.
    ("ARG BASE=alpine:3.19\nFROM ${BASE}\n", True),
    ("ARG BASE=alpine:3.19\nFROM $BASE\n", True),
    ("ARG BASE=ubuntu:24.04\nFROM ${BASE}\n", False),
    ('ARG BASE="alpine:3.19"\nFROM ${BASE}\n', True),
    # Only the default declared BEFORE the FROM that uses it.
    ("FROM ${BASE}\nARG BASE=alpine:3.19\n", False),
    # Left deliberately unresolved: no nesting, no ${X:-y}.
    ("FROM ${BASE}\n", False),
    ("ARG BASE=${OTHER:-alpine:3.19}\nFROM ${BASE}\n", False),
    # M-2 (round 5): the `#` was stripped BEFORE the heredoc was detected, so
    # this line was truncated at `RUN echo "` - ahead of the `<<` - and the
    # heredoc body was parsed as Dockerfile.  The glibc task read as Alpine
    # and left the graded denominator.  Docker supports no inline comment on
    # an instruction at all, so a `#` starts one only at column 0.
    (
        "FROM ubuntu:24.04\n"
        'RUN echo "#x" && cat <<EOF > /f\n'
        "FROM alpine:3.19\n"
        "EOF\n"
        "RUN echo done\n",
        False,
    ),
    # A whole-line comment is not an instruction: it builds nothing and opens
    # no heredoc.
    ("# FROM alpine:3.19\nFROM ubuntu:24.04\n", False),
    ("# cat <<EOF\nFROM alpine:3.19\n", True),
    # M-3: the terminator may be followed by a redirect or any other shell
    # metacharacter, not only whitespace - `cat <<EOF>/f` is a heredoc.
    ("FROM ubuntu:24.04\nRUN cat <<EOF>/f\nFROM alpine:3.19\nEOF\n", False),
    ("FROM ubuntu:24.04\nRUN cat <<EOF;echo x\nFROM alpine:3.19\nEOF\n", False),
    ("FROM ubuntu:24.04\nRUN cat <<EOF|tee /f\nFROM alpine:3.19\nEOF\n", False),
    # M-4: ARG scope.  Docker lets only an ARG declared BEFORE the first FROM
    # feed a FROM; one declared after it is stage-local and names no base.
    # Redefining it must not repoint a later FROM.
    (
        "ARG BASE=ubuntu:24.04\nFROM ${BASE}\n"
        "ARG BASE=alpine:3.19\nFROM ${BASE}\n",
        False,
    ),
    # A stage-local ARG feeding a later FROM leaves it unexpanded, which the
    # planner reports rather than guesses (see unresolved_base_reason).
    ("FROM ubuntu:24.04\nARG BASE=alpine:3.19\nFROM ${BASE}\n", False),
    # L-2: Docker strips leading whitespace from an instruction, so an
    # indented pre-FROM ARG still declares the default a FROM resolves.
    ("  ARG BASE=alpine:3.19\nFROM ${BASE}\n", True),
    ("\tARG BASE=alpine:3.19\nFROM ${BASE}\n", True),
    ("  ARG BASE=ubuntu:24.04\nFROM ${BASE}\n", False),
    # L-1 (round 6): the terminator line closed on `line.strip()`, so an
    # INDENTED `EOF` closed a plain `<<EOF` body.  Only `<<-` strips leading
    # tabs, and neither form strips spaces, so a body that is still running
    # was handed to the Dockerfile parser as instructions - here the `FROM
    # ubuntu` written into a file by an Alpine task, which then read as glibc
    # and was kept in a cohort that cannot install the GT wheel.
    ("FROM alpine:3.19\nRUN cat <<EOF > /f\n  EOF\nFROM ubuntu:24.04\n", True),
    # The same defect in the other direction: this glibc task's heredoc never
    # closes, so the `FROM alpine` inside it is data and the last real stage
    # is the ubuntu one above it.
    ("FROM ubuntu:24.04\nRUN cat <<EOF > /f\n  EOF\nFROM alpine:3.19\n", False),
    # `<<-` strips leading TABS, so a tab-indented terminator does close...
    ("FROM alpine:3.19\nRUN cat <<-EOF > /f\n\tEOF\nFROM ubuntu:24.04\n", False),
    # ...and a SPACE-indented one does not, for either form.
    ("FROM alpine:3.19\nRUN cat <<-EOF > /f\n  EOF\nFROM ubuntu:24.04\n", True),
    # L-2 (round 6): Docker accepts leading whitespace before the `#` of a
    # comment line, and a comment builds nothing and opens no heredoc.  An
    # indented `# cat <<EOF` opened a heredoc that never closed and swallowed
    # the real final stage - the Alpine one here, which left the task in the
    # cohort it cannot run in.
    ("FROM ubuntu:24.04\n  # cat <<EOF\nFROM alpine:3.19\n", True),
    ("FROM alpine:3.19\n\t# cat <<EOF\nFROM ubuntu:24.04\n", False),
    # The `# syntax=` parser directive is a comment like any other, indented
    # or not; it names a frontend, never a base image.
    ("# syntax=docker/dockerfile:1\nFROM alpine:3.19\n", True),
    ("  # syntax=docker/dockerfile:1\nFROM ubuntu:24.04\n", False),
    # L-3 (round 6): a `\`-continued instruction is ONE logical line.  Reading
    # the physical lines made `FROM \` resolve to the backslash itself, so an
    # Alpine base was never classified at all...
    ("FROM \\\n  alpine:3.19\n", True),
    ("FROM \\\n  ubuntu:24.04\n", False),
    # ...and made the continuation of a RUN read as a stage of its own, which
    # gave this glibc task an Alpine final stage it never builds.
    ("FROM ubuntu:24.04\nRUN echo \\\nFROM alpine:3.19\n", False),
    # Joining must hide no real stage: the one after the joined RUN is ours.
    ("FROM ubuntu:24.04\nRUN echo \\\nFROM x\nFROM alpine:3.19\n", True),
    # L-4 (round 6): `\"` and `\'` are escapes, not quote spans.  An odd
    # escaped quote opened a span that never closed, and every `<<` after it
    # went unseen - so this glibc task's heredoc body was parsed as Dockerfile
    # and its `FROM alpine` read as the final stage.
    (
        "FROM ubuntu:24.04\n"
        'RUN echo \\" && cat <<EOF > /f\n'
        "FROM alpine:3.19\n"
        "EOF\n",
        False,
    ),
    # A backslash inside SINGLE quotes is literal, so the span ends at the
    # next `\'` - the heredoc after it is real and still has to be seen.
    (
        "FROM ubuntu:24.04\n"
        "RUN echo 'a' \\' && cat <<EOF > /f\n"
        "FROM alpine:3.19\n"
        "EOF\n",
        False,
    ),
    # The converse: an escaped quote INSIDE a double-quoted span must not end
    # it, or the left shift that follows reads as a heredoc opener and
    # swallows the real Alpine stage below it.
    ('FROM ubuntu:24.04 AS b\nRUN echo "a \\" x<<y b"\nFROM alpine:3.19\n', True),
    # M-1 (round 7): Docker removes COMMENT lines BEFORE it joins a `\`
    # continuation, and a comment ends no continuation - `RUN echo hello \` +
    # `# comment` + `world` runs "hello world".  Concatenating the comment's
    # own text opened a phantom heredoc on a `<<` Docker never sees; it never
    # closed, swallowed the real Debian stage, and this glibc task left the
    # graded denominator as unsupported_platform:musl.
    (
        "FROM alpine AS b\n"
        "RUN echo a \\\n"
        "# cat <<EOF > /f\n"
        "    && echo b\n"
        "FROM debian:12\n",
        False,
    ),
    # The same joiner without a `<<`: the comment ended the logical line, so
    # the physical line under it read as a stage of its own.  Docker joins it
    # into the RUN, and the last real stage is the ubuntu one above.
    ("FROM ubuntu:24.04\nRUN echo a \\\n# note\nFROM alpine:3.19\n", False),
    # A comment carrying its own trailing `\` inside a continuation changes
    # nothing: the continuation was already live, so Docker joins the line
    # BELOW the comment into the RUN and this build has no Debian stage at
    # all.  Alpine is the right answer here - not a false exclusion.
    ("FROM alpine AS b\nRUN echo a \\\n# note \\\nFROM debian:12\n", True),
    # The harmless shape the fix must not disturb: a comment inside a
    # continuation with no `<<` and no trailing `\`, followed by a genuine
    # continuation line.  The stage after the joined RUN is still ours.
    (
        "FROM ubuntu:24.04\n"
        "RUN echo a \\\n"
        "# note\n"
        "  && echo b\n"
        "FROM alpine:3.19\n",
        True,
    ),
    # A comment line outside any continuation still opens no heredoc and ends
    # nothing, joined loop or not.
    ("FROM ubuntu:24.04\n# note \\\nFROM alpine:3.19\n", True),
)


@pytest.mark.parametrize("body,excluded", ALPINE_FIXTURES)
def test_planner_excludes_only_final_stage_alpine_bases(body: str, excluded: bool) -> None:
    final_from_image, is_alpine_image, _ = _planner_alpine_detector()
    assert is_alpine_image(final_from_image(body)) is excluded


@pytest.mark.parametrize("name", ("Dockerfile", "environment/Dockerfile"))
def test_planner_excludes_a_task_whose_own_dockerfile_is_alpine(tmp_path, name) -> None:
    """Live detection, run against a task directory instead of asserted about."""
    _, _, musl_reason = _planner_alpine_detector()
    task_dir = tmp_path / "qemu-alpine-ssh"
    dockerfile = task_dir / name
    dockerfile.parent.mkdir(parents=True, exist_ok=True)
    dockerfile.write_text("FROM alpine:3.19\n", encoding="utf-8")

    assert musl_reason(task_dir) == "unsupported_platform:musl"


def test_planner_keeps_a_glibc_task_with_an_alpine_builder_stage(tmp_path) -> None:
    _, _, musl_reason = _planner_alpine_detector()
    task_dir = tmp_path / "extract-elf"
    (task_dir / "environment").mkdir(parents=True)
    (task_dir / "environment" / "Dockerfile").write_text(
        "FROM alpine AS builder\nRUN apk add build-base\nFROM ubuntu:24.04\n",
        encoding="utf-8",
    )

    assert musl_reason(task_dir) is None


def test_planner_says_nothing_about_a_task_with_no_dockerfile(tmp_path) -> None:
    """No Dockerfile is not evidence of musl; the static list still decides."""
    _, _, musl_reason = _planner_alpine_detector()
    task_dir = tmp_path / "extract-elf"
    task_dir.mkdir()

    assert musl_reason(task_dir) is None


def test_planner_unions_live_detection_with_the_frozen_config(tmp_path) -> None:
    """Both sources exclude, and the frozen reason is the one reported.

    L-3: this was a pin on the text `static_unsupported.get(task) or
    musl_reason(dataset / task)`, which proved the characters were in the
    file and nothing about what the loop does. The loop is executed here
    instead, so dropping either source of exclusions fails this.
    """
    namespace = _planner_cohort(
        tmp_path,
        {
            "frozen-only": "FROM ubuntu:24.04\n",
            "live-only": "FROM alpine:3.19\n",
            "kept": "FROM ubuntu:24.04\n",
        },
        static_unsupported={"frozen-only": "unsupported_platform:no_musl_wheel"},
    )

    assert {row["task"]: row["reason"] for row in namespace["excluded"]} == {
        "frozen-only": "unsupported_platform:no_musl_wheel",
        "live-only": "unsupported_platform:musl",
    }
    assert namespace["runnable"] == ["kept"]


def test_planner_loads_the_frozen_config_from_the_pinned_path() -> None:
    # The read happens above the slice the tests execute (it runs before the
    # detector is defined), so the path it reads stays a text pin.
    assert "config/tb2_unsupported_tasks.v1.json" in WORKFLOW.read_text(
        encoding="utf-8"
    )


def _bash() -> str | None:
    """A POSIX bash. On Windows the bare name resolves to WSL, which cannot
    see the test tree, so prefer Git's bash when it is installed."""
    for candidate in (
        os.environ.get("GT_TEST_BASH"),
        shutil.which("bash") if os.name != "nt" else None,
        "C:/Program Files/Git/bin/bash.exe",
        "C:/Program Files (x86)/Git/bin/bash.exe",
        "/bin/bash",
    ):
        if candidate and Path(candidate).is_file():
            return candidate
    return None


BASH = _bash()


def _workflow_step_in(text: str, name: str) -> dict:
    document = yaml.safe_load(text)
    for job in document["jobs"].values():
        for step in job.get("steps") or []:
            if step.get("name") == name:
                return step
    raise AssertionError(f"no step named {name!r} in {WORKFLOW.name}")


def _workflow_step(name: str) -> dict:
    return _workflow_step_in(WORKFLOW.read_text(encoding="utf-8"), name)


_CROSS_READ_STEP = "Read this task's receipts against each other"
_ROOT_ASSIGNMENT = re.compile(r'^\s*root="([^"\n]*)"\s*$', re.M)
# The two expansions the step uses, and no others: ${VAR:+word} and $VAR.
_ALTERNATE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*):\+([^{}]*)\}")
_VARIABLE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)")


def _expand(value: str, env: dict) -> str:
    """Expand ${VAR:+word} and $VAR the way the step's shell would."""

    def alternate(match: re.Match) -> str:
        name, word = match.group(1), match.group(2)
        return _expand(word, env) if env.get(name) else ""

    def variable(match: re.Match) -> str:
        return env.get(match.group(1) or match.group(2), "")

    return _VARIABLE.sub(variable, _ALTERNATE.sub(alternate, value))


def _root_assignment(text: str) -> str:
    """The literal right-hand side of the step's own ``root=`` line."""
    script = _workflow_step_in(text, _CROSS_READ_STEP)["run"]
    assignments = _ROOT_ASSIGNMENT.findall(script)
    assert len(assignments) == 1, assignments
    return assignments[0]


def _resolved_root(text: str, job_name: str) -> str:
    """The directory the step actually hands the checker, for this job name.

    Mapping the literal token ``$root`` to a path the TEST picked proved
    nothing about the step: the reviewer reverted the assignment to
    ``results/terminal-bench`` - the suite root, two levels above the
    receipts - and this file still passed. The argument is resolved from the
    workflow's own assignment instead.
    """
    return _expand(_root_assignment(text), {"JOB_NAME": job_name})


def _cross_read_argv(workspace: Path, job_name: str, receipt: Path) -> list[str]:
    """The step's own command line, taken from the YAML, variables resolved.

    Reconstructing the invocation here would test the reconstruction: the
    defect was that the step passed a path two levels above the receipts, and
    only the step's real argument can show that.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    script = _workflow_step_in(text, _CROSS_READ_STEP)["run"]
    line = next(
        candidate
        for candidate in script.replace("\\\n", " ").splitlines()
        if "python -m scripts.verify_run_receipts" in candidate
    )
    root = workspace / _resolved_root(text, job_name)
    resolved = {
        "$root": str(root),
        "$conclusion": "success",
        "results/terminal-bench/receipt-consistency.json": str(receipt),
    }
    argv = [resolved.get(token, token) for token in shlex.split(line)]
    assert not [token for token in argv if "$" in token], argv
    assert str(root) in argv, argv
    return argv


def test_the_cross_read_step_reads_the_receipts_pier_actually_wrote(tmp_path) -> None:
    """Harbor exits 0 on an errored trial, so a green job proves nothing.

    Pier writes results/terminal-bench/<job-name>/<task>__<hash>/agent/.  The
    step was pointed at the suite root, two levels above, so five of the six
    checks reported UNKNOWN, the task_id degraded to "terminal-bench" and
    three planted contradictions still exited 0.
    """
    task = "extract-elf"
    job = "tb2-gt-smoke20-921bec20-42-extract-elf"
    # Where Pier writes, laid out under a fake workspace: the argument the
    # step computes has to land here, or nothing below is read.
    root = tmp_path / "results" / "terminal-bench" / job
    agent = root / f"{task}__9f3c1a2b" / "agent"
    agent.mkdir(parents=True)
    # (1) a child that exited 0 under an internal_error terminal, (2) a git
    # failure blamed on a provider that answered every request, (3) a
    # COMPLETED, research-valid run the progress receipt calls infrastructure.
    (agent / "miniswe_report.json").write_text(
        json.dumps({
            "terminal": "internal_error",
            "supervisor": {"child_returncode": 0, "reason": "exited"},
        }),
        encoding="utf-8",
    )
    (agent / "gt-run.json").write_text(
        json.dumps({
            "task_id": task,
            "terminal": "provider_failed",
            "status": "COMPLETED",
            "research_valid": True,
            "provider_calls": 12,
            "provider_attempts": 12,
            "provider_completed_calls": 12,
            "provider_failed_calls": 0,
        }),
        encoding="utf-8",
    )
    # The step copies the progress receipt into the tree it hands over.
    (root / "benchmark-progress.json").write_text(
        json.dumps({
            "schema": "gt.benchmark_progress.v1",
            "tasks": [{
                "task_id": task,
                "state": "infrastructure_failed",
                "official_verifier": True,
                "reward": None,
            }],
        }),
        encoding="utf-8",
    )
    receipt = tmp_path / "receipt-consistency.json"

    argv = _cross_read_argv(tmp_path, job, receipt)
    completed = subprocess.run(
        [sys.executable, *argv[1:]], cwd=ROOT, capture_output=True, text=True
    )

    assert completed.returncode == 1, completed.stderr
    document = json.loads(receipt.read_text(encoding="utf-8"))
    assert document["task_id"] == task
    assert document["contradictions"] == 3


def test_the_cross_read_step_runs_after_the_trial_and_can_redden_the_job() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    verifier = text.index("python -m scripts.verify_run_receipts")
    trial = text.index("Run one official Pier TB2 trial")
    upload = text.index("tb2-gt-smoke20-921bec20-${{ github.run_id }}-task-")
    assert trial < verifier < upload
    # always(): a failed trial is precisely the case worth cross-reading.
    assert _workflow_step(_CROSS_READ_STEP)["if"] == "always()"
    # L-3: the conclusion mapping, the receipt path and both nonzero-exit
    # branches used to be pinned here as shell text, which proved only that
    # the characters were in the file. They are EXECUTED under a real bash in
    # test_the_cross_read_step_turns_each_checker_exit_into_a_job_verdict.


def _cross_read_script(text: str, *, job_name: str, job_status: str) -> str:
    """The step's own shell body, with its two expressions resolved."""
    script = _workflow_step_in(text, _CROSS_READ_STEP)["run"]
    script = script.replace("${{ steps.harbor.outputs.job_name }}", job_name)
    script = script.replace("${{ job.status }}", job_status)
    assert "${{" not in script, script
    return script


def _run_cross_read_step(
    tmp_path: Path,
    *,
    rc: int,
    job_name: str = "tb2-gt-smoke20-921bec20-42-extract-elf",
    job_status: str = "success",
    writes_receipt: bool = True,
) -> tuple[subprocess.CompletedProcess, str]:
    """Execute the step under bash with the checker stubbed to exit ``rc``.

    Only the checker is replaced: the root it resolves, the copy of the
    progress receipt, the conclusion mapping and every error branch are the
    workflow's own lines, run by a real shell.  ``writes_receipt`` is the
    difference between a checker that ran and answered and one that died on
    import or on its own arguments: the second exits nonzero having written
    nothing, and the message must not send the reader to that file.
    """
    script = _cross_read_script(
        WORKFLOW.read_text(encoding="utf-8"), job_name=job_name, job_status=job_status
    )
    stub = (
        'python() { printf "%s\\n" "$*" >> "$ARGV_FILE";'
        ' if [ "$WRITE_RECEIPT" = 1 ]; then mkdir -p results/terminal-bench;'
        ' printf "{}" > results/terminal-bench/receipt-consistency.json; fi;'
        ' return "$PY_RC"; }\n'
    )
    completed = subprocess.run(
        [BASH, "-c", stub + script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "TASK": "extract-elf",
            "PY_RC": str(rc),
            "ARGV_FILE": "argv.txt",
            "WRITE_RECEIPT": "1" if writes_receipt else "0",
        },
    )
    argv = tmp_path / "argv.txt"
    return completed, argv.read_text(encoding="utf-8") if argv.is_file() else ""


@pytest.mark.skipif(not BASH, reason="bash absent")
@pytest.mark.parametrize(
    "rc,expected_exit,title",
    [
        (0, 0, None),
        (1, 1, "::error title=Receipt contradiction::"),
        (2, 1, "::error title=Receipts unresolved::"),
        # The checker defines 0, 1 and 2 and nothing else, so any other exit
        # is not a verdict it can have reached: neither a contradiction
        # between receipts nor a refusal to read them.
        (3, 1, "::error title=Receipt checker did not run::"),
    ],
)
def test_the_cross_read_step_turns_each_checker_exit_into_a_job_verdict(
    tmp_path: Path, rc: int, expected_exit: int, title: str | None
) -> None:
    """rc=1 is a contradiction between receipts; anything else nonzero is not.

    The step's own branches are executed rather than pinned: a revert that
    swapped the two messages, or that stopped reddening the job on rc=2,
    left the pinned strings in place and this file passing.
    """
    completed, argv = _run_cross_read_step(tmp_path, rc=rc)

    assert completed.returncode == expected_exit, completed.stderr
    if title is None:
        assert "::error" not in completed.stdout
    else:
        assert title in completed.stdout
    # The receipt lands inside the uploaded task artifact.
    assert "--json results/terminal-bench/receipt-consistency.json" in argv


@pytest.mark.skipif(not BASH, reason="bash absent")
@pytest.mark.parametrize(
    "job_status,conclusion",
    [("success", "success"), ("failure", "failure"), ("cancelled", "failure")],
)
def test_the_cross_read_step_passes_the_jobs_conclusion_as_an_input(
    tmp_path: Path, job_status: str, conclusion: str
) -> None:
    """The job's own conclusion is an input to the check, never its verdict.

    The script accepts success|failure only, and job.status can also be
    cancelled; anything that is not success did not succeed.
    """
    _completed, argv = _run_cross_read_step(tmp_path, rc=0, job_status=job_status)

    assert f"--job-conclusion {conclusion}" in argv


def test_summary_keeps_the_leak_check_and_drops_the_arithmetic_tautology(
    tmp_path: Path,
) -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    # Exclusions leaking a verifier receipt is a real contradiction: keep it.
    assert "excluded tasks produced verifier receipts" in text
    assert "official verifier counts do not close over the cohort" not in text

    # Why it is safe to drop: scripts/benchmark_progress.aggregate rejects any
    # state outside STATES, so officially_graded + infrastructure_failed +
    # remaining == total holds by construction and the check could never fire.
    receipt = {
        "schema": "gt.benchmark_progress.v1",
        "benchmark_suite": "terminal-bench",
        "tasks": [
            {"task_id": "a", "state": "passed", "reward": 1},
            {"task_id": "b", "state": "verifier_failed", "reward": 0},
            {"task_id": "c", "state": "infrastructure_failed", "reward": None},
        ],
    }
    (tmp_path / "shard").mkdir()
    (tmp_path / "shard" / "benchmark-progress.json").write_text(
        json.dumps(receipt), encoding="utf-8"
    )
    for finalize in (False, True):
        out = aggregate(tmp_path, ["a", "b", "c", "d"], finalize_missing=finalize)
        assert (
            out["officially_graded"] + out["infrastructure_failed"] + out["remaining"]
            == out["total"]
        )


# --- the resolution is the workflow's, not the test's ------------------------
# H-3: _cross_read_argv mapped the literal token "$root" to a path the test
# chose, so the step's own `root=` line was never read. The reviewer reverted
# it to `root="results/terminal-bench"` - CRITICAL-1, verbatim - and this file
# still passed.


def test_the_cross_read_root_is_read_from_the_workflows_own_assignment() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    job = "tb2-gt-smoke20-921bec20-42-extract-elf"

    # The job name has to be part of the resolved path: Pier writes the trial
    # under results/terminal-bench/<job-name>/.
    assert _resolved_root(text, job) == f"results/terminal-bench/{job}"
    # An empty job name (the trial step never ran) leaves the suite root.
    assert _resolved_root(text, "") == "results/terminal-bench"
    # The expansion this resolution depends on, pinned literally.
    assert "${JOB_NAME:+/$JOB_NAME}" in text


def test_reverting_the_root_to_the_suite_root_yields_the_wrong_directory() -> None:
    """The guard has to bite: prove the resolution follows the workflow text."""
    text = WORKFLOW.read_text(encoding="utf-8")
    job = "tb2-gt-smoke20-921bec20-42-extract-elf"
    reverted = text.replace(
        'root="results/terminal-bench${JOB_NAME:+/$JOB_NAME}"',
        'root="results/terminal-bench"',
    )

    assert reverted != text, "the assignment this test guards is no longer there"
    # Two levels above the receipts, and the job name gone from the path.
    assert _resolved_root(reverted, job) == "results/terminal-bench"
    assert _resolved_root(reverted, job) != _resolved_root(text, job)
    assert job not in _resolved_root(reverted, job)


@pytest.mark.skipif(not BASH, reason="bash absent")
def test_the_root_expansion_matches_a_real_shell() -> None:
    """The emulation stands in for the step's shell; check it against one."""
    assignment = _root_assignment(WORKFLOW.read_text(encoding="utf-8"))
    script = f'JOB_NAME="$1"\nroot="{assignment}"\nprintf %s "$root"'
    for job in ("tb2-gt-smoke20-921bec20-42-extract-elf", ""):
        shell = subprocess.run(
            [BASH, "-c", script, "bash", job], capture_output=True, text=True
        )
        assert shell.returncode == 0, shell.stderr
        assert shell.stdout == _expand(assignment, {"JOB_NAME": job})


# --- an unresolved ARG base keeps the task and says so -----------------------
# L-3: `ARG BASE=alpine:3.19` + `FROM ${BASE}` was never classified at all.
# The default is resolved when it is a plain top-level one; anything else stays
# unresolved, and an unresolved final base is reported as a warning rather than
# quietly dropping the task out of the cohort.


def test_planner_excludes_a_task_whose_arg_default_is_alpine(tmp_path) -> None:
    namespace = _planner_namespace()
    task_dir = tmp_path / "qemu-alpine-ssh"
    (task_dir / "environment").mkdir(parents=True)
    (task_dir / "environment" / "Dockerfile").write_text(
        "ARG BASE=alpine:3.19\nFROM ${BASE}\n", encoding="utf-8"
    )

    assert namespace["musl_reason"](task_dir) == "unsupported_platform:musl"
    assert namespace["unresolved_base_reason"](task_dir) is None


def test_planner_keeps_and_reports_a_task_whose_base_stays_unresolved(tmp_path) -> None:
    namespace = _planner_namespace()
    task_dir = tmp_path / "extract-elf"
    (task_dir / "environment").mkdir(parents=True)
    (task_dir / "environment" / "Dockerfile").write_text(
        "ARG BASE=${OTHER:-alpine:3.19}\nFROM ${BASE}\n", encoding="utf-8"
    )

    # Kept in the cohort: an unresolved base is not evidence of musl.
    assert namespace["musl_reason"](task_dir) is None
    assert namespace["unresolved_base_reason"](task_dir) == "unresolved_base_arg"


def test_planner_reports_nothing_for_a_resolved_glibc_base(tmp_path) -> None:
    namespace = _planner_namespace()
    task_dir = tmp_path / "extract-elf"
    (task_dir / "environment").mkdir(parents=True)
    (task_dir / "environment" / "Dockerfile").write_text(
        "ARG BASE=ubuntu:24.04\nFROM ${BASE}\n", encoding="utf-8"
    )

    assert namespace["musl_reason"](task_dir) is None
    assert namespace["unresolved_base_reason"](task_dir) is None


def _planner_cohort(
    tmp_path: Path, dockerfiles: dict, static_unsupported: dict | None = None
) -> dict:
    """Run the planner's own exclusion loop over a fake dataset directory.

    The loop is not a function, so it is executed out of the workflow the same
    way the detector is: asserting about its text would only prove the text.
    ``static_unsupported`` stands in for config/tb2_unsupported_tasks.v1.json,
    which the planner reads above this slice.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index("          def final_from_image(")
    end = text.index("          rows = []")
    for task, body in dockerfiles.items():
        (tmp_path / task / "environment").mkdir(parents=True)
        (tmp_path / task / "environment" / "Dockerfile").write_text(body, encoding="utf-8")
    namespace: dict = {
        "re": re,
        "selected": list(dockerfiles),
        "static_unsupported": dict(static_unsupported or {}),
        "dataset": tmp_path,
    }
    exec(compile(textwrap.dedent(text[start:end]), str(WORKFLOW), "exec"), namespace)
    return namespace


def test_planner_warns_about_an_unresolved_base_without_excluding_it(
    tmp_path, capsys
) -> None:
    namespace = _planner_cohort(
        tmp_path,
        {
            "arg-alpine": "ARG BASE=alpine:3.19\nFROM ${BASE}\n",
            "arg-unresolved": "ARG BASE=${OTHER:-alpine}\nFROM ${BASE}\n",
            "shift-not-heredoc": (
                'FROM alpine AS b\nRUN echo "shift x<<y bits"\nFROM ubuntu:24.04\n'
            ),
        },
    )

    # Only the resolved Alpine base leaves the cohort.
    assert [row["task"] for row in namespace["excluded"]] == ["arg-alpine"]
    assert namespace["runnable"] == ["arg-unresolved", "shift-not-heredoc"]
    # The unresolved one is kept and named, not excluded in silence.
    printed = capsys.readouterr().out
    assert (
        "::warning title=Unresolved base image::arg-unresolved: unresolved_base_arg"
        in printed
    )
    assert "arg-unresolved" not in str(namespace["excluded"])


# --- ARG scope is Docker's, not a flat dictionary ----------------------------
# M-4: every `ARG NAME=value` fed the FROM-resolution dictionary whatever its
# position, but Docker only lets an ARG declared BEFORE the first FROM feed a
# FROM. A stage-local ARG resolved a later `FROM ${BASE}` to an image the
# build never uses, which is how a task leaves - or stays in - the cohort for
# a reason that is not true of it.


def test_planner_ignores_an_arg_redefined_after_the_first_from(tmp_path) -> None:
    """The final FROM resolves from the pre-FROM default, not the later one."""
    namespace = _planner_namespace()
    body = (
        "ARG BASE=ubuntu:24.04\nFROM ${BASE}\n"
        "ARG BASE=alpine:3.19\nFROM ${BASE}\n"
    )
    task_dir = tmp_path / "extract-elf"
    (task_dir / "environment").mkdir(parents=True)
    (task_dir / "environment" / "Dockerfile").write_text(body, encoding="utf-8")

    assert namespace["final_from_image"](body) == "ubuntu:24.04"
    assert namespace["musl_reason"](task_dir) is None
    assert namespace["unresolved_base_reason"](task_dir) is None


def test_planner_leaves_a_stage_local_arg_base_unresolved(tmp_path) -> None:
    """A stage-local ARG names no base, so the FROM stays as written."""
    namespace = _planner_namespace()
    body = "FROM ubuntu:24.04\nARG BASE=alpine:3.19\nFROM ${BASE}\n"
    task_dir = tmp_path / "extract-elf"
    (task_dir / "environment").mkdir(parents=True)
    (task_dir / "environment" / "Dockerfile").write_text(body, encoding="utf-8")

    assert namespace["final_from_image"](body) == "${BASE}"
    # Unresolved is not evidence of musl: the task is kept, and named.
    assert namespace["musl_reason"](task_dir) is None
    assert namespace["unresolved_base_reason"](task_dir) == "unresolved_base_arg"


def test_planner_keeps_and_warns_about_a_stage_local_arg_task(tmp_path, capsys) -> None:
    namespace = _planner_cohort(
        tmp_path,
        {"stage-local-arg": "FROM ubuntu:24.04\nARG BASE=alpine:3.19\nFROM ${BASE}\n"},
    )

    assert namespace["excluded"] == []
    assert namespace["runnable"] == ["stage-local-arg"]
    assert (
        "::warning title=Unresolved base image::stage-local-arg: unresolved_base_arg"
        in capsys.readouterr().out
    )


def test_planner_keeps_a_glibc_task_that_writes_a_commented_heredoc(tmp_path) -> None:
    """M-2, through the cohort loop: the task must not silently vanish."""
    namespace = _planner_cohort(
        tmp_path,
        {
            "hash-before-heredoc": (
                "FROM ubuntu:24.04\n"
                'RUN echo "#x" && cat <<EOF > /f\n'
                "FROM alpine:3.19\n"
                "EOF\n"
            ),
            "no-space-redirect": (
                "FROM ubuntu:24.04\nRUN cat <<EOF>/f\nFROM alpine:3.19\nEOF\n"
            ),
        },
    )

    assert namespace["excluded"] == []
    assert namespace["runnable"] == ["hash-before-heredoc", "no-space-redirect"]


def test_planner_still_excludes_an_indented_arg_alpine_task(tmp_path) -> None:
    """L-2: an indented pre-FROM ARG is an instruction Docker honours."""
    namespace = _planner_cohort(
        tmp_path,
        {
            "indented-arg": "  ARG BASE=alpine:3.19\nFROM ${BASE}\n",
            "kept": "FROM ubuntu:24.04\n",
        },
    )

    assert [row["task"] for row in namespace["excluded"]] == ["indented-arg"]
    assert namespace["excluded"][0]["reason"] == "unsupported_platform:musl"
    assert namespace["runnable"] == ["kept"]
# --- round 7 -----------------------------------------------------------------


def test_planner_reads_an_indented_from_as_the_instruction_docker_honours() -> None:
    """L-2: leading whitespace before FROM is stripped, not a shell body.

    A `FROM` can no longer be inside a shell body by the time this test runs:
    heredoc bodies are skipped and `\\`-continued physical lines are joined, so
    every remaining line is a logical instruction line.
    """
    namespace = _planner_namespace()

    assert namespace["final_from_image"]("  FROM ubuntu:24.04\n") == "ubuntu:24.04"
    assert (
        namespace["final_from_image"]("FROM ubuntu:24.04\n\tFROM alpine:3.19\n")
        == "alpine:3.19"
    )


def test_planner_keeps_a_glibc_task_whose_continuation_spans_a_comment(
    tmp_path,
) -> None:
    """M-1, through the cohort loop: neither task may silently vanish."""
    namespace = _planner_cohort(
        tmp_path,
        {
            "phantom-heredoc": (
                "FROM alpine AS b\n"
                "RUN echo a \\\n"
                "# cat <<EOF > /f\n"
                "    && echo b\n"
                "FROM debian:12\n"
            ),
            "comment-ends-nothing": (
                "FROM ubuntu:24.04\nRUN echo a \\\n# note\nFROM alpine:3.19\n"
            ),
        },
    )

    assert namespace["excluded"] == []
    assert namespace["runnable"] == ["phantom-heredoc", "comment-ends-nothing"]


def test_planner_names_an_unparsed_dockerfile_without_excluding_it(tmp_path) -> None:
    """L-4: no FROM at all is a gap in this planner, not evidence of glibc."""
    namespace = _planner_namespace()
    task_dir = tmp_path / "no-from"
    (task_dir / "environment").mkdir(parents=True)
    (task_dir / "environment" / "Dockerfile").write_text(
        "# syntax=docker/dockerfile:1\nRUN echo hi\n", encoding="utf-8"
    )

    assert namespace["dockerfile_bases"](task_dir) == []
    assert namespace["musl_reason"](task_dir) is None
    assert namespace["unresolved_base_reason"](task_dir) is None
    assert namespace["unparsed_dockerfile_reason"](task_dir) == "no_from_found"
    # A task that ships no Dockerfile at all is not an unparsed one.
    empty = tmp_path / "none"
    empty.mkdir()
    assert namespace["unparsed_dockerfile_reason"](empty) is None


def test_planner_keeps_and_warns_about_a_dockerfile_with_no_from(
    tmp_path, capsys
) -> None:
    """L-4, through the cohort loop: kept, and said out loud."""
    namespace = _planner_cohort(
        tmp_path,
        {
            "no-from": "# syntax=docker/dockerfile:1\nRUN echo hi\n",
            "kept": "FROM ubuntu:24.04\n",
            "arg-unresolved": "FROM ${BASE}\n",
        },
    )

    assert namespace["excluded"] == []
    assert namespace["runnable"] == ["no-from", "kept", "arg-unresolved"]
    assert namespace["unresolved"] == [
        {"task": "no-from", "reason": "no_from_found"},
        {"task": "arg-unresolved", "reason": "unresolved_base_arg"},
    ]

    printed = capsys.readouterr().out
    assert "::warning title=Dockerfile unparsed::no-from: no_from_found" in printed
    assert (
        "::warning title=Unresolved base image::arg-unresolved: unresolved_base_arg"
        in printed
    )


def test_planner_receipt_records_the_kept_but_named_tasks() -> None:
    """The gap has to survive the log: the receipt is what the audit reads."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert '"unresolved": unresolved,' in text


# --- BuildKit's line continuation, not `endswith("\\")` ----------------------
# M-1: three divergences from BuildKit's own parser, each of which joins - or
# refuses to join - a line Docker treats the other way, so the final stage read
# out of the file is a stage this build never builds.  The expected value in
# every row is Docker's answer, and every rule is exercised in both directions:
# once where the divergence reads a glibc task as Alpine (dropped from the
# graded denominator as `unsupported_platform:musl`), once where it reads an
# Alpine task as glibc (kept in a cohort it cannot run).

CONTINUATION_FIXTURES = (
    # BuildKit's lineContinuationRegex is `\\[ \t]*$`, not a bare suffix test:
    # trailing blanks after the backslash do not end the continuation.
    (
        "trailing-space-still-continues",
        "FROM ubuntu:24.04\nRUN echo a \\ \nFROM alpine:3.19\n",
        "ubuntu:24.04",
    ),
    (
        "trailing-tab-still-continues",
        "FROM alpine:3.19\nRUN echo a \\\t\nFROM ubuntu:24.04\n",
        "alpine:3.19",
    ),
    # BuildKit's inner loop `continue`s on an empty continuation line: the
    # continuation stays live and the next non-empty line is the one joined.
    (
        "empty-continuation-line-keeps-it-live",
        "FROM ubuntu:24.04\nRUN echo a \\\n\nFROM alpine:3.19\n",
        "ubuntu:24.04",
    ),
    (
        "whitespace-continuation-line-keeps-it-live",
        "FROM alpine:3.19\nRUN echo a \\\n   \nFROM ubuntu:24.04\n",
        "alpine:3.19",
    ),
    # `# escape=` replaces the continuation character for the whole file.
    (
        "escape-directive-retires-the-backslash",
        "# escape=`\nFROM ubuntu:24.04\nRUN echo a \\\nFROM alpine:3.19\n",
        "alpine:3.19",
    ),
    (
        "escape-directive-promotes-its-own-token",
        "# escape=`\nFROM ubuntu:24.04\nRUN echo a `\nFROM alpine:3.19\n",
        "ubuntu:24.04",
    ),
    # The directive key is case-insensitive, and another directive above it
    # does not end the directive block.
    (
        "escape-follows-another-directive-and-ignores-case",
        "# syntax=docker/dockerfile:1\n# ESCAPE=`\n"
        "FROM alpine:3.19\nRUN echo a \\\nFROM ubuntu:24.04\n",
        "ubuntu:24.04",
    ),
    # Below the first instruction it is an ordinary comment, so the default
    # token still continues the line.
    (
        "escape-below-the-first-instruction-is-a-comment",
        "FROM ubuntu:24.04\n# escape=`\nRUN echo a \\\nFROM alpine:3.19\n",
        "ubuntu:24.04",
    ),
)


@pytest.mark.parametrize(
    "body,expected",
    [pytest.param(body, expected, id=name) for name, body, expected in CONTINUATION_FIXTURES],
)
def test_planner_joins_continuations_the_way_buildkit_does(
    body: str, expected: str
) -> None:
    assert _planner_namespace()["final_from_image"](body) == expected


@pytest.mark.parametrize(
    "body,expected",
    [pytest.param(body, expected, id=name) for name, body, expected in CONTINUATION_FIXTURES],
)
def test_planner_cohort_follows_buildkits_continuation(
    tmp_path, body: str, expected: str
) -> None:
    """The same rule through the exclusion loop: in or out of the denominator."""
    _, is_alpine_image, musl_reason = _planner_alpine_detector()
    task_dir = tmp_path / "task"
    (task_dir / "environment").mkdir(parents=True)
    (task_dir / "environment" / "Dockerfile").write_text(body, encoding="utf-8")

    excluded = musl_reason(task_dir) == "unsupported_platform:musl"
    assert excluded is is_alpine_image(expected)


def test_planner_reads_the_escape_directive_out_of_the_workflow() -> None:
    """The token is read from the file, not assumed, and only `\\` or a backtick.

    Docker accepts those two and nothing else; a `# escape=x` line is an error
    there, and guessing a token out of it would repoint every continuation in
    the file.
    """
    directives = _planner_namespace()["parser_directives"]

    assert directives(["FROM ubuntu:24.04"]) == "\\"
    assert directives(["# escape=`", "FROM ubuntu:24.04"]) == "`"
    assert directives(["#escape=\\", "FROM ubuntu:24.04"]) == "\\"
    assert directives(["  # escape = ` ", "FROM ubuntu:24.04"]) == "`"
    # Not a token Docker takes, so the default stands.
    assert directives(["# escape=x", "FROM ubuntu:24.04"]) == "\\"
    # A blank line ends the directive block, as does an instruction.
    assert directives(["", "# escape=`", "FROM ubuntu:24.04"]) == "\\"
    assert directives(["# a plain comment", "# escape=`"]) == "\\"


# --- a heredoc is a redirection on RUN, COPY or ADD --------------------------
# L-4: `ARG X=a<<b` is a left shift in a default value, not a heredoc, and
# opening one on it swallowed the rest of the file - so `final_from_image`
# returned the FIRST stage, silently, with no warning row to say so.

HEREDOC_GATE_FIXTURES = (
    (
        "arg-left-shift-opens-nothing",
        "FROM ubuntu:22.04\nARG X=a<<b\nFROM alpine:3.19\n",
        "alpine:3.19",
    ),
    (
        "env-left-shift-opens-nothing",
        "FROM alpine:3.19\nENV X=a<<b\nFROM ubuntu:24.04\n",
        "ubuntu:24.04",
    ),
    (
        "label-left-shift-opens-nothing",
        "FROM alpine:3.19\nLABEL shift=a<<b\nFROM ubuntu:24.04\n",
        "ubuntu:24.04",
    ),
    (
        "run-heredoc-still-suppresses-an-in-body-from",
        "FROM ubuntu:24.04\nRUN cat <<EOF > /D\nFROM alpine:3.19\nEOF\n",
        "ubuntu:24.04",
    ),
    (
        "copy-heredoc-still-suppresses-an-in-body-from",
        "FROM ubuntu:24.04\nCOPY <<EOF /D\nFROM alpine:3.19\nEOF\n",
        "ubuntu:24.04",
    ),
    (
        "add-heredoc-still-suppresses-an-in-body-from",
        "FROM ubuntu:24.04\nADD <<EOF /D\nFROM alpine:3.19\nEOF\n",
        "ubuntu:24.04",
    ),
    (
        "lowercase-run-is-the-same-instruction",
        "FROM ubuntu:24.04\n  run cat <<-EOF > /D\nFROM alpine:3.19\n\tEOF\n",
        "ubuntu:24.04",
    ),
)


@pytest.mark.parametrize(
    "body,expected",
    [pytest.param(body, expected, id=name) for name, body, expected in HEREDOC_GATE_FIXTURES],
)
def test_planner_opens_a_heredoc_only_where_docker_accepts_one(
    body: str, expected: str
) -> None:
    assert _planner_namespace()["final_from_image"](body) == expected


def test_planner_keeps_a_glibc_task_whose_arg_default_holds_a_left_shift(
    tmp_path,
) -> None:
    """The cohort consequence: an ARG left shift used to exclude a glibc task."""
    _, _, musl_reason = _planner_alpine_detector()
    task_dir = tmp_path / "shift-arg"
    (task_dir / "environment").mkdir(parents=True)
    (task_dir / "environment" / "Dockerfile").write_text(
        "FROM alpine:3.19 AS builder\nARG X=a<<b\nFROM ubuntu:24.04\n",
        encoding="utf-8",
    )

    assert musl_reason(task_dir) is None


def _planner_receipt(tmp_path: Path, monkeypatch, *, unresolved_reason: str) -> dict:
    """Run the warning loop and the receipt write with a reason injected.

    The slice starts at WARNING_TITLES so the two reason-producing helpers can
    be replaced: an unknown reason is exactly the case no fixture can produce
    today, and it is the case that used to kill the plan job with a KeyError
    before any receipt was written.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index("          WARNING_TITLES = {")
    end = text.index('          matrix = json.dumps({"include": rows}')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TREATMENT_SHA", "t" * 40)
    monkeypatch.setenv("GT_SOURCE_SHA", "g" * 40)
    monkeypatch.setenv("MODEL", "deepseek-v4-flash")
    monkeypatch.setenv("DATASET", "terminal-bench@2.0")
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "github-output"))
    (tmp_path / "github-output").write_text("", encoding="utf-8")
    namespace: dict = {
        "re": re,
        "json": json,
        "os": os,
        "Path": Path,
        "selected": ["gap"],
        "tasks": ["gap"],
        "stage": "subset",
        "digest": "d" * 64,
        "dataset": tmp_path,
        "static_unsupported": {},
        "SUPERVISOR_GRACE_SECONDS": 120,
        "musl_reason": lambda task_dir: None,
        "unresolved_base_reason": lambda task_dir: unresolved_reason,
        "unparsed_dockerfile_reason": lambda task_dir: None,
        "resolve_budget": lambda path, multiplier: {
            "execution_budget_sec": 600,
            "task_config_sha256": "c" * 64,
        },
    }
    exec(compile(textwrap.dedent(text[start:end]), str(WORKFLOW), "exec"), namespace)
    return namespace


def test_planner_writes_the_receipt_even_for_an_unknown_warning_reason(
    tmp_path, monkeypatch, capsys
) -> None:
    """L-3: `WARNING_TITLES[reason]` was a bare subscript on a widening set.

    A reason added to the helpers but not to the title table killed the plan
    job with a KeyError before the receipt was written - so the cohort lost
    every task over a missing dictionary entry, and the artifact that would
    have said why was never uploaded.
    """
    _planner_receipt(tmp_path, monkeypatch, unresolved_reason="a_new_gap")

    printed = capsys.readouterr().out
    assert "::warning title=Planner gap::gap: a_new_gap" in printed
    receipt = json.loads((tmp_path / "tb2-gt-smoke20-plan.json").read_text(encoding="utf-8"))
    assert receipt["unresolved"] == [{"task": "gap", "reason": "a_new_gap"}]
    assert receipt["task_ids"] == ["gap"]


def test_planner_keeps_the_known_warning_titles(tmp_path, monkeypatch, capsys) -> None:
    """The fallback does not swallow the titles the audit already reads."""
    _planner_receipt(tmp_path, monkeypatch, unresolved_reason="unresolved_base_arg")

    assert (
        "::warning title=Unresolved base image::gap: unresolved_base_arg"
        in capsys.readouterr().out
    )


# --- an exit code is not a receipt -------------------------------------------
# L-1: `python -m scripts.verify_run_receipts` exits 1 on a startup failure
# (ModuleNotFoundError, SyntaxError) and 2 on an argparse error, in both cases
# having written nothing.  The rc=1 branch then sent the reader to
# receipt-consistency.json to read failing checks that were never computed, and
# called an import error a contradiction between receipts.


# The exit code decides the message and an absent file is a SUFFIX on it.
# `verify_run_receipts` returns 1 both when it read both receipts, found a
# contradiction and could not write its `--json`, and when it died on import.
ABSENT_RECEIPT_SUFFIX = "; receipt-consistency.json was not written"

CROSS_READ_MATRIX = (
    ("rc0-receipt-written", 0, True, 0, None, False),
    ("rc0-no-receipt", 0, False, 1, "::error title=Receipt checker did not run::", False),
    ("rc1-receipt-written", 1, True, 1, "::error title=Receipt contradiction::", False),
    ("rc1-no-receipt", 1, False, 1, "::error title=Receipt contradiction::", True),
    ("rc2-receipt-written", 2, True, 1, "::error title=Receipts unresolved::", False),
    ("rc2-no-receipt", 2, False, 1, "::error title=Receipts unresolved::", True),
    ("rc3-receipt-written", 3, True, 1, "::error title=Receipt checker did not run::", False),
    ("rc3-no-receipt", 3, False, 1, "::error title=Receipt checker did not run::", True),
)


@pytest.mark.skipif(not BASH, reason="bash absent")
@pytest.mark.parametrize(
    "rc,writes_receipt,expected_exit,title,suffixed",
    [
        pytest.param(rc, writes, code, title, suffixed, id=name)
        for name, rc, writes, code, title, suffixed in CROSS_READ_MATRIX
    ],
)
def test_the_cross_read_step_reads_the_exit_code_before_the_receipt(
    tmp_path: Path,
    rc: int,
    writes_receipt: bool,
    expected_exit: int,
    title: str | None,
    suffixed: bool,
) -> None:
    """N-8: the absent-receipt guard used to run BEFORE the rc branches.

    An rc=1 that had run, read both receipts and found a contradiction, and
    only then failed to write its `--json`, was reported as "Receipt checker
    did not run" - the one message that is false about it.  The rc names the
    verdict now, and the missing file is named as a suffix on that verdict.
    """
    completed, argv = _run_cross_read_step(tmp_path, rc=rc, writes_receipt=writes_receipt)

    assert completed.returncode == expected_exit, completed.stderr
    if title is None:
        assert "::error" not in completed.stdout
    else:
        assert title in completed.stdout
    assert (ABSENT_RECEIPT_SUFFIX in completed.stdout) is suffixed
    # An rc=0 that wrote nothing answered nothing, whatever the exit says.
    if rc == 0 and not writes_receipt:
        assert (
            "extract-elf verifier exited 0 without writing receipt-consistency.json"
            in completed.stdout
        )
    # The checker itself is always invoked, and always at the artifact path.
    assert "--json results/terminal-bench/receipt-consistency.json" in argv
    receipt = tmp_path / "results" / "terminal-bench" / "receipt-consistency.json"
    assert receipt.exists() is writes_receipt


@pytest.mark.skipif(not BASH, reason="bash absent")
def test_the_contradiction_message_names_the_crashed_check_counter(
    tmp_path: Path,
) -> None:
    """L-2: rc=1 can also carry a check that crashed instead of answering.

    Reading only `checks` in the receipt leaves a crashed check unexplained,
    so the message names the counter that holds it.
    """
    completed, _argv = _run_cross_read_step(tmp_path, rc=1)

    assert completed.returncode == 1, completed.stderr
    assert "::error title=Receipt contradiction::" in completed.stdout
    assert "checks_crashed" in completed.stdout
    assert "receipt-consistency.json" in completed.stdout


# --- BuildKit unwraps ONBUILD before asking what can hold a heredoc ----------
# N-3: `canContainHeredoc` runs after the compound directives in
# `heredocCompoundDirectives` (ONBUILD) are unwrapped, so `ONBUILD RUN <<EOF`
# DOES open a heredoc in Docker.  Reading only the first keyword refused it,
# the body's `FROM alpine:3.19` was read as a stage, and a glibc task was
# excluded from the graded cohort as musl.

ONBUILD_HEREDOC_FIXTURES = (
    (
        "onbuild-run-opens-a-heredoc",
        "FROM ubuntu:24.04\nONBUILD RUN <<EOF\nFROM alpine:3.19\nEOF\n",
        "ubuntu:24.04",
    ),
    (
        "onbuild-copy-opens-a-heredoc",
        "FROM ubuntu:24.04\nONBUILD COPY <<EOF /f\nFROM alpine:3.19\nEOF\n",
        "ubuntu:24.04",
    ),
    (
        "onbuild-add-opens-a-heredoc",
        "FROM ubuntu:24.04\nONBUILD ADD <<EOF /f\nFROM alpine:3.19\nEOF\n",
        "ubuntu:24.04",
    ),
    (
        "lowercase-onbuild-run-is-the-same-instruction",
        "FROM ubuntu:24.04\n  onbuild run cat <<-EOF > /f\nFROM alpine:3.19\n\tEOF\n",
        "ubuntu:24.04",
    ),
    # Unwrapping ONBUILD does not widen the gate: the instruction underneath
    # still has to be one of the three that take a redirection.
    (
        "onbuild-arg-left-shift-opens-nothing",
        "FROM ubuntu:24.04\nONBUILD ARG X=a<<b\nFROM alpine:3.19\n",
        "alpine:3.19",
    ),
    (
        "onbuild-label-left-shift-opens-nothing",
        "FROM ubuntu:24.04\nONBUILD LABEL shift=a<<b\nFROM alpine:3.19\n",
        "alpine:3.19",
    ),
    (
        "onbuild-with-no-instruction-opens-nothing",
        "FROM ubuntu:24.04\nONBUILD\nFROM alpine:3.19\n",
        "alpine:3.19",
    ),
)


@pytest.mark.parametrize(
    "body,expected",
    [pytest.param(body, expected, id=name) for name, body, expected in ONBUILD_HEREDOC_FIXTURES],
)
def test_planner_unwraps_onbuild_before_gating_the_heredoc(body: str, expected: str) -> None:
    assert _planner_namespace()["final_from_image"](body) == expected


def test_planner_keeps_a_glibc_task_whose_onbuild_run_holds_a_heredoc(tmp_path) -> None:
    """The cohort consequence: an `ONBUILD RUN <<EOF` body read as a stage."""
    _, _, musl_reason = _planner_alpine_detector()
    task_dir = tmp_path / "onbuild-heredoc"
    (task_dir / "environment").mkdir(parents=True)
    (task_dir / "environment" / "Dockerfile").write_text(
        "FROM ubuntu:24.04\nONBUILD RUN <<EOF\nFROM alpine:3.19\nEOF\n",
        encoding="utf-8",
    )

    assert musl_reason(task_dir) is None


# --- a Dockerfile line ends at a newline, and nowhere else -------------------
# N-7: Go's bufio.ScanLines splits on `\n` alone; str.splitlines also splits on
# \v \f \x1c \x1d \x1e \x85 \u2028 \u2029, so a control character inside a RUN
# string invented a stage this build never has.


@pytest.mark.parametrize(
    "separator",
    ["\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"],
)
def test_planner_splits_dockerfile_lines_the_way_docker_does(separator: str) -> None:
    body = "FROM ubuntu:24.04\nRUN echo 'a" + separator + "FROM alpine:3.19'\n"

    assert _planner_namespace()["final_from_image"](body) == "ubuntu:24.04"


def test_planner_keeps_a_glibc_task_whose_run_string_holds_a_control_character(
    tmp_path,
) -> None:
    _, _, musl_reason = _planner_alpine_detector()
    task_dir = tmp_path / "formfeed"
    (task_dir / "environment").mkdir(parents=True)
    (task_dir / "environment" / "Dockerfile").write_text(
        "FROM ubuntu:24.04\nRUN echo 'a\x0cFROM alpine:3.19'\n", encoding="utf-8"
    )

    assert musl_reason(task_dir) is None


def test_planner_still_joins_a_continuation_in_a_crlf_dockerfile() -> None:
    """Splitting on the newline alone leaves a CR the continuation regex needs gone.

    The continuation pattern anchors at the end of the line, so a trailing
    carriage return after the escape character stops it matching: the
    continuation was dropped and the FROM below it read as a stage of its own.
    """
    body = "FROM ubuntu:24.04\r\nRUN echo hi \\\r\nFROM alpine:3.19\r\n"

    assert _planner_namespace()["final_from_image"](body) == "ubuntu:24.04"


# --- the parser directive block is three keys wide and ends on anything else -
# N-6: a UTF-8 BOM ahead of `# escape=` defeated the `^\s*#` of the directive
# regex; an unrecognised `# foo=bar` is a plain comment and ENDS the block in
# Docker; and a directive declared twice is a build error, not last-one-wins.


def test_planner_reads_the_escape_directive_through_a_utf8_bom() -> None:
    """A BOM is stripped before anything reads a line, exactly as Docker does.

    With the BOM in the way the declared backtick was lost, the default
    backslash stood, the backtick-continued RUN stopped continuing, and the
    FROM that belongs to it read as the final stage instead.
    """
    body = "\ufeff# escape=`\nFROM ubuntu:24.04\nRUN echo hi `\nFROM alpine:3.19\n"

    assert _planner_namespace()["final_from_image"](body) == "ubuntu:24.04"


def test_planner_ends_the_directive_block_at_an_unknown_comment_key() -> None:
    """escape, syntax and check are the directives; `# foo=bar` is a comment.

    Docker stops reading directives at the first line that is not one, and an
    unrecognised `key=value` comment is not one - so an `# escape=` below it is
    an ordinary comment and changes nothing.
    """
    directives = _planner_namespace()["parser_directives"]

    assert directives(["# foo=bar", "# escape=`", "FROM ubuntu:24.04"]) == "\\"
    # The two directives Docker does know keep the block open.
    assert directives(["# syntax=docker/dockerfile:1", "# escape=`", "FROM u"]) == "`"
    assert directives(["# check=skip=all", "# escape=`", "FROM ubuntu:24.04"]) == "`"
    # And the docstring no longer claims every other key is skipped in place.
    assert "WITHOUT ending the block" not in (directives.__doc__ or "")


def test_planner_falls_back_to_backslash_on_a_duplicated_escape_directive() -> None:
    """A directive declared twice is a build error in Docker, not last-one-wins.

    The file does not build either way, so the planner does not pick a token
    out of it: the default stands, and the task fails at its own build time
    rather than being classified off a guess.
    """
    directives = _planner_namespace()["parser_directives"]

    assert directives(["# escape=`", "# escape=\\", "FROM ubuntu:24.04"]) == "\\"
    assert directives(["# escape=`", "# escape=`", "FROM ubuntu:24.04"]) == "\\"
    # One declaration, of either token, still resolves.
    assert directives(["# escape=`", "FROM ubuntu:24.04"]) == "`"
