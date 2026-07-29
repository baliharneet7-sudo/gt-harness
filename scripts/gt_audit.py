#!/usr/bin/env python3
"""gt_audit - deterministic Tier-2 auditor for a Terminal-Bench run artifact.

Reads a harbor output tree (one dir per task, each with ``agent/nano.txt`` +
``result.json``) and grades GroundTruth's CONDUCT per task - the mechanical
half of GT's own audit methodology (fired != delivered != consumed; this tool
grades what was DELIVERED into observations, the model-facing surface).

Checks per task:
  1. RUN HEALTH   real iterations? tokens>0? stop reason? "agent error:" in
                  the final panel (= harness/GT crash) is an automatic RED.
  2. GT ACTIVITY  count GT-attributable blocks visible in tool observations
                  (submit refusals, covering-failure blocks, compiler-voice
                  diagnostics). Zero on a non-code task = GREEN-dormant
                  (correct-or-quiet); zero on a code task = noted quiet.
  3. LEAK LAW     no ``<gt-*>`` substring anywhere under native mode (hard
                  RED); test-file paths inside GT-attributable blocks are
                  flagged REVIEW (heuristic, never a hard fail).
  4. DOSE LAW     at most ONE GT-attributable block per tool observation
                  (heuristic detection; violations reported with context).
  5. ERROR RATE   tool_result panels flagged (error) / total.
  6. TOKENS/COST  totals from the trailing "stop:" line; GT overhead
                  observable = chars inside GT-attributable blocks.
  7. PAIRING      with ``--baseline <dir>``: align tasks by name, emit the
                  no-harm table (reward / tokens / iterations / deliveries).

Anything the parser does not recognize is reported as UNPARSED - the tool
fails loud, never lies quiet (one-sided observation scores false-green).

Stdlib only. Deterministic output ordering (tasks sorted by name).

Usage:
    python scripts/gt_audit.py <run_dir> [--baseline <run_dir>] [--json out.json]

Exit code: 1 if any audited task is RED, else 0 (2 = usage error).

Known detection limits (documented, not silent):
  * The task-start capsule rides the INITIAL USER message, which nano's CLI
    does not print - it is NOT observable in nano.txt. Counted only if a
    future transcript format surfaces user messages.
  * Bare grep-row deliveries (``path:line:sym``) are byte-shaped like real
    ripgrep output BY DESIGN and cannot be attributed from the transcript
    alone; they are excluded from delivery counts (documented undercount).
  * The CLI truncates each tool_result panel to 2000 chars; a GT suffix past
    that boundary is invisible here.
  * ADJACENT single-line diagnostics of different kinds group as ONE block
    (multi-row renderers ship many rows per dose); two distinct doses shipped
    back-to-back with no interleaving output can undercount to one - the
    wrap-tolerance recheck tops up the multi-word kinds but not all.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------- #
# transcript parsing (nano CLI rich-panel format, tee'd without ANSI)
# --------------------------------------------------------------------------- #
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_PANEL_TOP_RE = re.compile(r"^\s*╭─+(?: (.+?) )?─*╮\s*$")
_PANEL_BOTTOM_RE = re.compile(r"^\s*╰─+╯\s*$")
_PANEL_CONTENT_RE = re.compile(r"^\s*│ ?(.*?) ?│\s*$")
_STOP_RE = re.compile(
    r"^stop:\s*(?P<reason>\S+)\s+iterations=(?P<iters>\d+)\s+in=(?P<in>\d+)"
    r"\s+out=(?P<out>\d+)\s+cache_read=(?P<cache>\d+)\s*$")
_STATS_RE = re.compile(r"^iter=(?P<iter>\d+)\s+in=(?P<in>\d+)\s+out=(?P<out>\d+)\s*$")
_SETUP_ERROR_RE = re.compile(r"^setup error:")

_KNOWN_PANEL_TITLES = {"assistant", "tool_call", "tool_result", "tool_result (error)", "final"}


@dataclass
class Panel:
    title: str
    lines: list[str]
    start_line: int  # 1-based line number in nano.txt

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


@dataclass
class Transcript:
    panels: list[Panel] = field(default_factory=list)
    stop: dict | None = None
    stats: list[dict] = field(default_factory=list)
    setup_error: str | None = None
    unparsed: list[tuple[int, str]] = field(default_factory=list)  # (lineno, line)
    unparsed_structures: list[str] = field(default_factory=list)


def parse_transcript(text: str) -> Transcript:
    """Tolerant parser: every non-blank line is either consumed by a known
    structure or recorded as UNPARSED - never silently skipped."""
    t = Transcript()
    cur: Panel | None = None
    for i, raw in enumerate(_ANSI_RE.sub("", text).splitlines(), start=1):
        line = raw.rstrip("\r")
        if cur is not None:
            if _PANEL_BOTTOM_RE.match(line):
                t.panels.append(cur)
                cur = None
                continue
            m = _PANEL_CONTENT_RE.match(line)
            if m:
                cur.lines.append(m.group(1).rstrip())
                continue
            # A top border while a panel is open: the previous panel never
            # closed (truncated transcript). Keep what we have, flag it.
            if _PANEL_TOP_RE.match(line):
                t.panels.append(cur)
                t.unparsed_structures.append(
                    f"line {cur.start_line}: panel '{cur.title}' not closed")
                cur = None
                # fall through to top-border handling below
            else:
                t.unparsed.append((i, line))
                continue
        m = _PANEL_TOP_RE.match(line)
        if m:
            cur = Panel(title=(m.group(1) or "").strip(), lines=[], start_line=i)
            if cur.title not in _KNOWN_PANEL_TITLES:
                t.unparsed_structures.append(
                    f"line {i}: unknown panel title '{cur.title}'")
            continue
        if not line.strip():
            continue
        sm = _STOP_RE.match(line.strip())
        if sm:
            t.stop = {"reason": sm.group("reason"), "iterations": int(sm.group("iters")),
                      "in_tokens": int(sm.group("in")), "out_tokens": int(sm.group("out")),
                      "cache_read": int(sm.group("cache"))}
            continue
        tm = _STATS_RE.match(line.strip())
        if tm:
            t.stats.append({"iteration": int(tm.group("iter")),
                            "in_tokens": int(tm.group("in")),
                            "out_tokens": int(tm.group("out"))})
            continue
        if _SETUP_ERROR_RE.match(line.strip()):
            t.setup_error = line.strip()
            continue
        t.unparsed.append((i, line))
    if cur is not None:
        t.panels.append(cur)
        t.unparsed_structures.append(
            f"line {cur.start_line}: panel '{cur.title}' not closed (EOF)")
    return t


# --------------------------------------------------------------------------- #
# GT-attributable block detection (shapes from groundtruth native_render.py)
# --------------------------------------------------------------------------- #
# High-confidence markers only. Bare grep rows (path:line:sym) are deliberately
# excluded: GT ships them byte-shaped like real ripgrep output (that is the
# point of the native channel), so they cannot be attributed from the
# transcript alone. Documented undercount, never a guess.
_GT_LINE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("submit_refusal", re.compile(r"^pre-commit hook failed:\s*$")),
    ("ss_submit_red", re.compile(r"pre-submit check: `.*` was last observed FAILING")),
    ("covering_failure", re.compile(
        r"^(A covering test fails:|Your change to `.+\(\)` fails a covering test:)")),
    ("caller_contract", re.compile(
        r"error: \S+\(\) signature changed.*must update the call sites")),
    ("signature_delta", re.compile(
        r"error: \S+\(\) takes \d+(?:-\d+)? positional argument\(s\) but \d+ given")),
    ("note_row", re.compile(r": note: \S+ - verify your change is consistent here")),
    ("registration", re.compile(r": warning: registers .+ but not '")),
    ("scope_note", re.compile(r": note: your change must also update this file\s*$")),
    ("related_note", re.compile(r": note: related file to inspect \(certified \w+ relation\)")),
    ("caller_usage", re.compile(
        r": note: \S+\(\) result is (boolean-checked|unpacked into multiple values"
        r"|used inside an exception guard|iterated)")),
    ("cert_hook_line", re.compile(r"^\S.*\.{3,}Failed\s*$")),
]
_SUBMIT_END_RE = re.compile(r"^commit aborted \(exit 1\)\s*$")
# multi-word shapes re-checked on whitespace-joined text (panel wrap tolerance)
_WRAP_CHECK_KINDS = ("caller_contract", "signature_delta", "registration",
                     "ss_submit_red", "related_note", "caller_usage")

_GT_TAG_RE = re.compile(r"<gt-", re.IGNORECASE)
# test-identity heuristic for REVIEW flags inside GT-attributable blocks
_TEST_IDENTITY_RE = re.compile(
    r"(^|[\s'\"(/])tests?/|(^|[\s'\"(/])(test_\w+|conftest)\.py\b"
    r"|_test\.(py|go|rb)\b|\.(test|spec)\.(js|jsx|ts|tsx|mjs|cjs)\b"
    r"|\.\w+::[\w.\[\]-]+|\bdef test_\w+")
_SOURCE_EXT_RE = re.compile(
    r"\.(py|pyi|go|rs|js|jsx|ts|tsx|rb|java|kt|cs|php|swift|scala|c|h|cc|cpp|hpp|sh|lua)\b")


@dataclass
class GTBlock:
    kind: str
    panel_start_line: int
    text: str


def _classify_line(line: str) -> str | None:
    for kind, rx in _GT_LINE_PATTERNS:
        if rx.search(line):
            return kind
    return None


def detect_gt_blocks(panel: Panel) -> list[GTBlock]:
    """Group GT-recognized lines into blocks (one block = one dose)."""
    blocks: list[GTBlock] = []
    lines = panel.lines
    i = 0
    n = len(lines)
    while i < n:
        kind = _classify_line(lines[i])
        if kind is None:
            i += 1
            continue
        start = i
        if kind == "submit_refusal":
            # consume until "commit aborted (exit 1)" (inclusive) or panel end
            j = i + 1
            while j < n and not _SUBMIT_END_RE.match(lines[j]):
                j += 1
            i = min(j + 1, n)
        elif kind == "covering_failure":
            # head + up to 14 following non-blank, non-head lines (_MAX_KEEP_LINES)
            j = i + 1
            kept = 0
            while j < n and lines[j].strip() and kept < 14:
                k2 = _classify_line(lines[j])
                if k2 in ("submit_refusal", "covering_failure"):
                    break
                j += 1
                kept += 1
            i = j
        else:
            # contiguous run of single-line GT diagnostics = one block
            j = i + 1
            while j < n:
                k2 = _classify_line(lines[j])
                if k2 is None or k2 in ("submit_refusal", "covering_failure"):
                    break
                j += 1
            i = j
        blocks.append(GTBlock(kind=kind, panel_start_line=panel.start_line,
                              text="\n".join(lines[start:i])))
    # wrap tolerance: a diagnostic split across wrapped panel lines evades the
    # per-line pass; re-check multi-word shapes on the joined text and top up.
    joined = " ".join(ln.strip() for ln in lines if ln.strip())
    per_line = {k: sum(1 for b in blocks if b.kind == k) for k, _ in _GT_LINE_PATTERNS}
    for kind, rx in _GT_LINE_PATTERNS:
        if kind not in _WRAP_CHECK_KINDS:
            continue
        extra = len(rx.findall(joined)) - per_line.get(kind, 0)
        for _ in range(max(0, extra)):
            blocks.append(GTBlock(kind=kind + " (wrapped)",
                                  panel_start_line=panel.start_line,
                                  text="<detected across wrapped panel lines>"))
    return blocks


# --------------------------------------------------------------------------- #
# per-task audit
# --------------------------------------------------------------------------- #
@dataclass
class TaskAudit:
    task_name: str
    trial_dir: str
    verdict: str = "UNKNOWN"
    verdict_reasons: list[str] = field(default_factory=list)
    # run health
    stop_reason: str | None = None
    iterations: int | None = None
    in_tokens: int | None = None
    out_tokens: int | None = None
    cache_read: int | None = None
    agent_error: str | None = None
    exception_info: str | None = None
    reward: float | None = None
    # gt activity
    code_task: bool = False
    gt_deliveries: int = 0
    gt_delivery_kinds: dict[str, int] = field(default_factory=dict)
    gt_overhead_chars: int = 0
    # laws
    leak_tag_count: int = 0
    leak_tag_context: list[str] = field(default_factory=list)
    review_flags: list[str] = field(default_factory=list)
    dose_violations: list[str] = field(default_factory=list)
    # tool health
    tool_results: int = 0
    tool_errors: int = 0
    # parser honesty
    unparsed_lines: int = 0
    unparsed_samples: list[str] = field(default_factory=list)
    unparsed_structures: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def error_rate(self) -> float | None:
        return (self.tool_errors / self.tool_results) if self.tool_results else None


def _load_result_json(task_dir: Path) -> dict:
    p = task_dir / "result.json"
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def audit_task(task_dir: Path) -> TaskAudit:
    rj = _load_result_json(task_dir)
    name = rj.get("task_name") or task_dir.name.split("__", 1)[0]
    a = TaskAudit(task_name=name, trial_dir=task_dir.name)

    # result.json facts
    try:
        a.reward = float(rj["verifier_result"]["rewards"]["reward"])
    except (KeyError, TypeError, ValueError):
        a.reward = None
    exc = rj.get("exception_info")
    if exc:
        a.exception_info = json.dumps(exc, sort_keys=True)[:400]

    nano_txt = task_dir / "agent" / "nano.txt"
    if not nano_txt.is_file():
        a.verdict = "RED"
        a.verdict_reasons.append("missing agent/nano.txt (no transcript to audit)")
        return a
    text = nano_txt.read_text(encoding="utf-8", errors="replace")
    t = parse_transcript(text)

    # 1. RUN HEALTH -------------------------------------------------------- #
    if t.stop:
        a.stop_reason = t.stop["reason"]
        a.iterations = t.stop["iterations"]
        a.in_tokens = t.stop["in_tokens"]
        a.out_tokens = t.stop["out_tokens"]
        a.cache_read = t.stop["cache_read"]
    elif t.stats:
        last = t.stats[-1]
        a.iterations = last["iteration"]
        a.in_tokens = last["in_tokens"]
        a.out_tokens = last["out_tokens"]
        a.notes.append("no 'stop:' line - run killed externally; totals from last stats line")
    for p in t.panels:
        if p.title == "final" and "agent error:" in p.text:
            a.agent_error = " ".join(p.text.split())[:300]
    if t.setup_error:
        a.agent_error = a.agent_error or t.setup_error[:300]

    # 2-6. per-panel checks ------------------------------------------------ #
    all_blocks: list[GTBlock] = []
    for p in t.panels:
        if p.title.startswith("tool_result"):
            a.tool_results += 1
            if p.title == "tool_result (error)" or p.text.startswith("ERROR:"):
                a.tool_errors += 1
            blocks = detect_gt_blocks(p)
            all_blocks.extend(blocks)
            if len(blocks) > 1:
                kinds = ", ".join(b.kind for b in blocks)
                a.dose_violations.append(
                    f"panel at line {p.start_line}: {len(blocks)} GT blocks in one "
                    f"observation ({kinds})")
        elif p.title == "tool_call":
            if _SOURCE_EXT_RE.search(p.text) or p.text.startswith("edit_file("):
                a.code_task = True

    a.gt_deliveries = len(all_blocks)
    for b in all_blocks:
        a.gt_delivery_kinds[b.kind] = a.gt_delivery_kinds.get(b.kind, 0) + 1
        a.gt_overhead_chars += len(b.text)
        if _TEST_IDENTITY_RE.search(b.text):
            a.review_flags.append(
                f"possible test identity inside GT block ({b.kind}, panel line "
                f"{b.panel_start_line}) - human review")
    a.gt_delivery_kinds = dict(sorted(a.gt_delivery_kinds.items()))

    # 3. LEAK LAW: <gt-*> anywhere in the transcript ------------------------ #
    for i, raw in enumerate(text.splitlines(), start=1):
        if _GT_TAG_RE.search(raw):
            a.leak_tag_count += 1
            if len(a.leak_tag_context) < 5:
                a.leak_tag_context.append(f"line {i}: {raw.strip()[:160]}")

    # parser honesty -------------------------------------------------------- #
    a.unparsed_lines = len(t.unparsed)
    a.unparsed_samples = [f"line {ln}: {s.strip()[:120]}" for ln, s in t.unparsed[:5]]
    a.unparsed_structures = list(t.unparsed_structures)

    # verdict ---------------------------------------------------------------- #
    if a.agent_error:
        a.verdict_reasons.append(
            f"agent error at iteration {a.iterations if a.iterations is not None else '?'}"
            f", {a.in_tokens or 0}+{a.out_tokens or 0} tokens: {a.agent_error}")
    if a.exception_info:
        a.verdict_reasons.append(f"harness exception_info present: {a.exception_info}")
    if a.leak_tag_count:
        a.verdict_reasons.append(
            f"LEAK: <gt-*> tag visible in observations x{a.leak_tag_count}")
    if a.agent_error or a.exception_info or a.leak_tag_count or a.stop_reason == "error":
        a.verdict = "RED"
        return a

    if a.dose_violations:
        a.verdict_reasons.extend(a.dose_violations)
    if a.review_flags:
        a.verdict_reasons.extend(a.review_flags)
    if a.unparsed_lines or a.unparsed_structures:
        a.verdict_reasons.append(
            f"UNPARSED content: {a.unparsed_lines} line(s), "
            f"{len(a.unparsed_structures)} structure issue(s) - parser does not "
            "recognize this shape; verdict cannot be trusted GREEN")
    if t.stop is None:
        a.verdict_reasons.append("no trailing 'stop:' line (transcript incomplete)")
    if a.verdict_reasons:
        a.verdict = "YELLOW"
        return a

    if a.gt_deliveries == 0:
        if a.code_task:
            a.verdict = "GREEN-quiet"
            a.verdict_reasons.append(
                "code task, zero GT deliveries observed (correct-or-quiet; "
                "not automatically wrong)")
        else:
            a.verdict = "GREEN-dormant"
            a.verdict_reasons.append(
                "non-code task, zero GT deliveries (dormancy is correct)")
    else:
        a.verdict = "GREEN"
    return a


# --------------------------------------------------------------------------- #
# run-dir walking
# --------------------------------------------------------------------------- #
def find_task_dirs(run_dir: Path) -> list[Path]:
    """Task dirs = dirs containing result.json AND agent/. Handles one level
    of nesting (the downloaded artifact often wraps the run dir once)."""
    def is_task(d: Path) -> bool:
        return (d / "result.json").is_file() and (d / "agent").is_dir()

    found = sorted(d for d in run_dir.iterdir() if d.is_dir() and is_task(d))
    if found:
        return found
    for sub in sorted(d for d in run_dir.iterdir() if d.is_dir()):
        nested = sorted(d for d in sub.iterdir() if d.is_dir() and is_task(d))
        if nested:
            return nested
    return []


def audit_run(run_dir: Path) -> list[TaskAudit]:
    dirs = find_task_dirs(run_dir)
    if not dirs:
        raise SystemExit(f"gt_audit: no task dirs (result.json + agent/) under {run_dir}")
    return [audit_task(d) for d in dirs]  # find_task_dirs is sorted -> deterministic


# --------------------------------------------------------------------------- #
# reporting
# --------------------------------------------------------------------------- #
def _fmt(v: object, width: int) -> str:
    s = "-" if v is None else str(v)
    return s[:width].ljust(width)


def render_report(audits: list[TaskAudit], run_dir: Path) -> str:
    out: list[str] = []
    out.append(f"GT AUDIT  {run_dir}")
    out.append("=" * 100)
    hdr = (_fmt("task", 34) + _fmt("verdict", 14) + _fmt("stop", 12) + _fmt("iter", 6)
           + _fmt("in/out tok", 16) + _fmt("reward", 8) + _fmt("gt", 4) + _fmt("err%", 6))
    out.append(hdr)
    out.append("-" * 100)
    for a in audits:
        tok = None
        if a.in_tokens is not None or a.out_tokens is not None:
            tok = f"{a.in_tokens or 0}/{a.out_tokens or 0}"
        er = None if a.error_rate is None else f"{a.error_rate:.0%}"
        out.append(_fmt(a.task_name, 34) + _fmt(a.verdict, 14) + _fmt(a.stop_reason, 12)
                   + _fmt(a.iterations, 6) + _fmt(tok, 16) + _fmt(a.reward, 8)
                   + _fmt(a.gt_deliveries, 4) + _fmt(er, 6))
    out.append("-" * 100)
    for a in audits:
        out.append(f"\n{a.task_name} [{a.verdict}]")
        for r in a.verdict_reasons:
            out.append(f"  - {r}")
        if a.gt_delivery_kinds:
            out.append(f"  - GT delivery kinds: {a.gt_delivery_kinds}")
        if a.gt_overhead_chars:
            out.append(f"  - GT overhead observable: {a.gt_overhead_chars} chars")
        for n in a.notes:
            out.append(f"  - note: {n}")
        for s in a.unparsed_samples:
            out.append(f"  - UNPARSED {s}")
        for s in a.unparsed_structures:
            out.append(f"  - UNPARSED-STRUCTURE {s}")
    counts: dict[str, int] = {}
    for a in audits:
        counts[a.verdict] = counts.get(a.verdict, 0) + 1
    out.append("\nSUMMARY: " + "  ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return "\n".join(out)


def render_paired(gt: list[TaskAudit], base: list[TaskAudit]) -> str:
    bmap = {a.task_name: a for a in base}
    gmap = {a.task_name: a for a in gt}
    names = sorted(set(bmap) | set(gmap))
    out: list[str] = []
    out.append("\nPAIRED (no-harm check): baseline vs GT")
    out.append("=" * 110)
    out.append(_fmt("task", 34) + _fmt("rw base", 9) + _fmt("rw gt", 9) + _fmt("d", 6)
               + _fmt("tok base", 14) + _fmt("tok gt", 14) + _fmt("it b/g", 9)
               + _fmt("gt-doses", 9) + "flag")
    out.append("-" * 110)
    for name in names:
        b, g = bmap.get(name), gmap.get(name)
        rb = b.reward if b else None
        rg = g.reward if g else None
        delta = None if (rb is None or rg is None) else round(rg - rb, 3)
        flag = ""
        if b is None or g is None:
            flag = "UNPAIRED"
        elif rb is not None and rg is not None and rg < rb:
            flag = "HARM?"
        tb = f"{b.in_tokens or 0}/{b.out_tokens or 0}" if b else None
        tg = f"{g.in_tokens or 0}/{g.out_tokens or 0}" if g else None
        it = f"{b.iterations if b else '-'}/{g.iterations if g else '-'}"
        out.append(_fmt(name, 34) + _fmt(rb, 9) + _fmt(rg, 9) + _fmt(delta, 6)
                   + _fmt(tb, 14) + _fmt(tg, 14) + _fmt(it, 9)
                   + _fmt(g.gt_deliveries if g else None, 9) + flag)
    out.append("-" * 110)
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    # The report can quote arbitrary transcript bytes; never let a cp1252
    # console kill the auditor (the exact failure class it exists to catch).
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(
        prog="gt_audit", description="Deterministic Tier-2 GT-conduct auditor "
        "for a Terminal-Bench harbor run artifact.")
    ap.add_argument("run_dir", help="the run to audit (the GT arm in paired mode)")
    ap.add_argument("--baseline", default=None,
                    help="baseline run dir - adds the paired no-harm table")
    ap.add_argument("--json", dest="json_out", default=None,
                    help="write the full machine-readable audit to this path")
    args = ap.parse_args(argv)

    run_dir = Path(args.run_dir)
    if not run_dir.is_dir():
        print(f"gt_audit: not a directory: {run_dir}", file=sys.stderr)
        return 2
    audits = audit_run(run_dir)
    print(render_report(audits, run_dir))

    base_audits: list[TaskAudit] | None = None
    if args.baseline:
        base_dir = Path(args.baseline)
        if not base_dir.is_dir():
            print(f"gt_audit: not a directory: {base_dir}", file=sys.stderr)
            return 2
        base_audits = audit_run(base_dir)
        print(render_paired(audits, base_audits))

    if args.json_out:
        payload: dict = {
            "run_dir": str(run_dir),
            "tasks": [asdict(a) | {"error_rate": a.error_rate} for a in audits],
        }
        if base_audits is not None:
            payload["baseline_dir"] = str(args.baseline)
            payload["baseline_tasks"] = [
                asdict(a) | {"error_rate": a.error_rate} for a in base_audits]
        Path(args.json_out).write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    return 1 if any(a.verdict == "RED" for a in audits) else 0


if __name__ == "__main__":
    sys.exit(main())
