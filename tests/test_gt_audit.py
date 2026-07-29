"""Tests for scripts/gt_audit.py - the Tier-2 GT-conduct auditor.

Fixture tests run against a REAL crashed-run task dir copied from GHA run
tb2-gt-30496848157 (tests/fixtures/gt_audit/crashed_run/). Synthetic tests
build transcripts in the exact nano-CLI panel shapes (rich Panel tee'd
without ANSI) so healthy-run behaviors - dormancy, dose counting, leak
detection, pairing - are pinned before a healthy artifact exists.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "gt_audit.py"
CRASHED_RUN = Path(__file__).resolve().parent / "fixtures" / "gt_audit" / "crashed_run"

_spec = importlib.util.spec_from_file_location("gt_audit", SCRIPT)
gt_audit = importlib.util.module_from_spec(_spec)
sys.modules["gt_audit"] = gt_audit  # dataclasses resolve types via sys.modules
_spec.loader.exec_module(gt_audit)


# --------------------------------------------------------------------------- #
# synthetic transcript builders (nano CLI rich-panel shape)
# --------------------------------------------------------------------------- #
def panel(title: str, text: str, width: int = 78) -> str:
    inner = width - 4  # "| " + " |"
    lines: list[str] = []
    for raw in text.splitlines() or [""]:
        while True:
            lines.append(raw[:inner])
            raw = raw[inner:]
            if not raw:
                break
    pad = width - 4 - len(title)
    top = "╭" + "─" * (pad // 2) + f" {title} " + "─" * (pad - pad // 2) + "╮"
    body = [f"│ {ln.ljust(inner)} │" for ln in lines]
    bottom = "╰" + "─" * (width - 2) + "╯"
    return "\n".join([top, *body, bottom])


def stop_line(reason="end_turn", iters=3, in_t=1000, out_t=200, cache=0) -> str:
    return (f"stop: {reason}  iterations={iters}  in={in_t}  out={out_t}  "
            f"cache_read={cache}")


def make_task_dir(root: Path, trial: str, task_name: str, transcript: str,
                  reward: float = 0.0) -> Path:
    d = root / trial
    (d / "agent").mkdir(parents=True)
    (d / "agent" / "nano.txt").write_text(transcript, encoding="utf-8")
    (d / "result.json").write_text(json.dumps({
        "task_name": task_name,
        "verifier_result": {"rewards": {"reward": reward}},
        "exception_info": None,
    }), encoding="utf-8")
    return d


HEALTHY_NONCODE = "\n".join([
    panel("assistant", "Let me check the date."),
    panel("tool_call", "bash(command='date')"),
    "iter=1 in=500 out=50",
    panel("tool_result", "Tue Jul 29 2026"),
    panel("assistant", "Done."),
    "iter=2 in=600 out=60",
    stop_line(iters=2, in_t=1100, out_t=110),
    panel("final", "The date is printed."),
    "",
])


# --------------------------------------------------------------------------- #
# 1. crash detection against the REAL artifact
# --------------------------------------------------------------------------- #
def test_crashed_run_is_red():
    audits = gt_audit.audit_run(CRASHED_RUN)
    assert len(audits) == 1
    a = audits[0]
    assert a.task_name == "break-filter-js-from-html"
    assert a.verdict == "RED"
    assert a.stop_reason == "error"
    assert a.iterations == 1
    assert a.in_tokens == 0 and a.out_tokens == 0
    assert a.agent_error and "UnicodeEncodeError" in a.agent_error
    assert a.reward == 0.0
    assert a.gt_deliveries == 0
    # the real crashed transcript must parse fully - nothing unexplained
    assert a.unparsed_lines == 0
    assert not a.unparsed_structures


def test_cli_end_to_end_on_crashed_fixture(tmp_path):
    out_json = tmp_path / "audit.json"
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), str(CRASHED_RUN), "--json", str(out_json)],
        capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 1  # RED present
    assert "RED" in proc.stdout
    assert "agent error at iteration 1" in proc.stdout
    data = json.loads(out_json.read_text(encoding="utf-8"))
    assert data["tasks"][0]["verdict"] == "RED"


# --------------------------------------------------------------------------- #
# 2. dormancy classification (healthy non-code run, zero GT activity)
# --------------------------------------------------------------------------- #
def test_dormant_noncode_task_is_green_dormant(tmp_path):
    make_task_dir(tmp_path, "datecheck__abc", "datecheck", HEALTHY_NONCODE, reward=1.0)
    audits = gt_audit.audit_run(tmp_path)
    a = audits[0]
    assert a.verdict == "GREEN-dormant"
    assert a.gt_deliveries == 0
    assert a.code_task is False
    assert a.stop_reason == "end_turn"
    assert a.iterations == 2
    assert a.unparsed_lines == 0


def test_quiet_code_task_is_green_quiet(tmp_path):
    transcript = "\n".join([
        panel("assistant", "Editing."),
        panel("tool_call", "edit_file(path='src/main.py', old='a', new='b')"),
        panel("tool_result", "edited src/main.py"),
        stop_line(),
        panel("final", "done"),
    ])
    make_task_dir(tmp_path, "fix__x", "fix", transcript)
    a = gt_audit.audit_run(tmp_path)[0]
    assert a.verdict == "GREEN-quiet"
    assert a.code_task is True
    assert a.gt_deliveries == 0


# --------------------------------------------------------------------------- #
# 3. dose counting on a synthetic multi-dose observation
# --------------------------------------------------------------------------- #
def test_single_dose_is_green_and_counted(tmp_path):
    obs = ("$ apply_patch src/api.py\n"
           "src/api.py: error: handler() signature changed; 3 caller(s) in 2 "
           "file(s) must update the call sites")
    transcript = "\n".join([
        panel("tool_call", "edit_file(path='src/api.py', old='x', new='y')"),
        panel("tool_result", obs, width=120),
        stop_line(),
        panel("final", "done"),
    ])
    make_task_dir(tmp_path, "t__1", "t", transcript)
    a = gt_audit.audit_run(tmp_path)[0]
    assert a.verdict == "GREEN"
    assert a.gt_deliveries == 1
    assert a.gt_delivery_kinds == {"caller_contract": 1}
    assert not a.dose_violations
    assert a.gt_overhead_chars > 0


def test_multi_dose_observation_is_flagged(tmp_path):
    obs = ("ok\n"
           "src/api.py: error: handler() signature changed; 3 caller(s) in 2 "
           "file(s) must update the call sites\n"
           "some interleaved tool output\n"
           "src/config.py: note: your change must also update this file")
    transcript = "\n".join([
        panel("tool_call", "bash(command='sed -i s/a/b/ src/api.py')"),
        panel("tool_result", obs, width=120),
        stop_line(),
        panel("final", "done"),
    ])
    make_task_dir(tmp_path, "t__1", "t", transcript)
    a = gt_audit.audit_run(tmp_path)[0]
    assert a.gt_deliveries == 2
    assert len(a.dose_violations) == 1
    assert "2 GT blocks" in a.dose_violations[0]
    assert a.verdict == "YELLOW"


def test_submit_refusal_block_counts_once(tmp_path):
    obs = ("pre-commit hook failed:\n"
           "syntax_error\n"
           "invalid syntax (api.py, line 10)\n"
           "commit aborted (exit 1)")
    transcript = "\n".join([
        panel("tool_call", "bash(command='python src/api.py')"),
        panel("tool_result", obs, width=100),
        stop_line(),
        panel("final", "done"),
    ])
    make_task_dir(tmp_path, "t__1", "t", transcript)
    a = gt_audit.audit_run(tmp_path)[0]
    assert a.gt_deliveries == 1
    assert a.gt_delivery_kinds == {"submit_refusal": 1}
    assert not a.dose_violations


# --------------------------------------------------------------------------- #
# 4. leak law
# --------------------------------------------------------------------------- #
def test_gt_tag_leak_is_red(tmp_path):
    transcript = "\n".join([
        panel("tool_call", "bash(command='ls')"),
        panel("tool_result", "file1\n<gt-fact>secret evidence</gt-fact>", width=100),
        stop_line(),
        panel("final", "done"),
    ])
    make_task_dir(tmp_path, "t__1", "t", transcript)
    a = gt_audit.audit_run(tmp_path)[0]
    assert a.verdict == "RED"
    # counted per matching line; the opening tag sits on one transcript line
    assert a.leak_tag_count == 1
    assert any("<gt-fact>" in c for c in a.leak_tag_context)


def test_test_identity_in_gt_block_is_review_flag_not_red(tmp_path):
    obs = ("tests/test_api.py: error: handler() signature changed; 1 caller(s) "
           "in 1 file(s) must update the call sites")
    transcript = "\n".join([
        panel("tool_call", "edit_file(path='src/api.py', old='x', new='y')"),
        panel("tool_result", obs, width=120),
        stop_line(),
        panel("final", "done"),
    ])
    make_task_dir(tmp_path, "t__1", "t", transcript)
    a = gt_audit.audit_run(tmp_path)[0]
    assert a.verdict == "YELLOW"  # human review, never a hard RED on heuristic
    assert len(a.review_flags) == 1
    assert "human review" in a.review_flags[0]


# --------------------------------------------------------------------------- #
# 5. error rate + 6. tokens
# --------------------------------------------------------------------------- #
def test_error_rate_and_tokens(tmp_path):
    transcript = "\n".join([
        panel("tool_call", "bash(command='date')"),
        panel("tool_result", "ok"),
        panel("tool_call", "bash(command='nope')"),
        panel("tool_result (error)", "ERROR: nope: command not found [exit code 127]"),
        stop_line(reason="end_turn", iters=4, in_t=4321, out_t=765, cache=99),
        panel("final", "done"),
    ])
    make_task_dir(tmp_path, "t__1", "t", transcript)
    a = gt_audit.audit_run(tmp_path)[0]
    assert a.tool_results == 2
    assert a.tool_errors == 1
    assert a.error_rate == 0.5
    assert (a.in_tokens, a.out_tokens, a.cache_read) == (4321, 765, 99)


# --------------------------------------------------------------------------- #
# UNPARSED honesty: unknown shapes are surfaced, never silently skipped
# --------------------------------------------------------------------------- #
def test_unrecognized_lines_are_reported_unparsed(tmp_path):
    transcript = "\n".join([
        "some junk the parser has never seen",
        panel("tool_call", "bash(command='date')"),
        panel("tool_result", "ok"),
        stop_line(),
        panel("final", "done"),
    ])
    make_task_dir(tmp_path, "t__1", "t", transcript)
    a = gt_audit.audit_run(tmp_path)[0]
    assert a.unparsed_lines == 1
    assert "junk" in a.unparsed_samples[0]
    assert a.verdict == "YELLOW"  # cannot be trusted GREEN


def test_unknown_panel_title_is_flagged(tmp_path):
    transcript = "\n".join([
        panel("mystery", "??"),
        panel("tool_result", "ok"),
        stop_line(),
        panel("final", "done"),
    ])
    make_task_dir(tmp_path, "t__1", "t", transcript)
    a = gt_audit.audit_run(tmp_path)[0]
    assert any("mystery" in s for s in a.unparsed_structures)
    assert a.verdict == "YELLOW"


def test_missing_transcript_is_red(tmp_path):
    d = make_task_dir(tmp_path, "t__1", "t", "x")
    (d / "agent" / "nano.txt").unlink()
    a = gt_audit.audit_run(tmp_path)[0]
    assert a.verdict == "RED"
    assert "missing agent/nano.txt" in a.verdict_reasons[0]


# --------------------------------------------------------------------------- #
# 7. pairing
# --------------------------------------------------------------------------- #
def test_paired_table_aligns_by_task_name(tmp_path):
    base = tmp_path / "base"
    gt = tmp_path / "gt"
    make_task_dir(base, "alpha__b1", "alpha", HEALTHY_NONCODE, reward=1.0)
    make_task_dir(base, "beta__b2", "beta", HEALTHY_NONCODE, reward=1.0)
    make_task_dir(gt, "alpha__g1", "alpha", HEALTHY_NONCODE, reward=1.0)
    make_task_dir(gt, "beta__g2", "beta", HEALTHY_NONCODE, reward=0.0)  # harm
    out = gt_audit.render_paired(gt_audit.audit_run(gt), gt_audit.audit_run(base))
    lines = out.splitlines()
    alpha = next(ln for ln in lines if ln.startswith("alpha"))
    beta = next(ln for ln in lines if ln.startswith("beta"))
    assert "HARM?" not in alpha
    assert "HARM?" in beta
    assert lines.index(alpha) < lines.index(beta)  # deterministic name order


def test_paired_unpaired_task_is_flagged(tmp_path):
    base = tmp_path / "base"
    gt = tmp_path / "gt"
    make_task_dir(base, "alpha__b1", "alpha", HEALTHY_NONCODE, reward=1.0)
    make_task_dir(gt, "gamma__g1", "gamma", HEALTHY_NONCODE, reward=1.0)
    out = gt_audit.render_paired(gt_audit.audit_run(gt), gt_audit.audit_run(base))
    assert out.count("UNPAIRED") == 2


# --------------------------------------------------------------------------- #
# determinism: two runs over the same tree produce identical bytes
# --------------------------------------------------------------------------- #
def test_report_is_deterministic():
    a1 = gt_audit.render_report(gt_audit.audit_run(CRASHED_RUN), CRASHED_RUN)
    a2 = gt_audit.render_report(gt_audit.audit_run(CRASHED_RUN), CRASHED_RUN)
    assert a1 == a2


def test_nested_run_dir_is_found(tmp_path):
    nested = tmp_path / "wrapper"
    make_task_dir(nested, "t__1", "t", HEALTHY_NONCODE)
    audits = gt_audit.audit_run(tmp_path)  # one level above the task dirs' parent
    assert len(audits) == 1 and audits[0].task_name == "t"


def test_empty_run_dir_fails_loud(tmp_path):
    with pytest.raises(SystemExit):
        gt_audit.audit_run(tmp_path)
