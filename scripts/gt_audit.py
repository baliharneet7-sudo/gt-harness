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
  8. LEDGER-JOIN  when ``agent/gt_ledger.jsonl`` exists (GT-side seal records,
                  one JSONL row per SEALED delivery), every ledger row is
                  reconciled 1:1 against the agent-side transcript - gt_math's
                  dose-reconciliation law made mechanical.  Per row:
                    TRANSCRIPT-CONFIRMED  the shipped bytes were located in a
                        tool_result panel (sha256 of the located slice matches
                        the row's ``rendered_bytes_hash``, or the byte-exact
                        text from ``gt_deliveries.txt`` was found);
                    MODEL-ONLY  delivered to the model but structurally
                        invisible in nano.txt - either boundary=task_start
                        (rides the un-printed initial user message) or the
                        target observation hit the CLI's [:2000] display cap
                        (the GT suffix sits past the display window);
                    UNRECONCILED  should be visible but is not = potential
                        delivery lie (the F1 class) -> verdict RED.
                  Ledger integrity: chain_head values must be unique 64-hex
                  and event_ids strictly advancing; duplicate dedup_keys are
                  flagged; >1 gateway/covering row per event_id violates the
                  dose law.  When a ledger exists it REPLACES the heuristic
                  dose count (ledger truth); the heuristic remains for
                  ledgerless/baseline runs.  ``agent/gt_deliveries.txt``
                  (optional, per-delivery framed blocks: header line carrying
                  event_id/boundary/evidence_type/rendered_bytes_hash, then
                  the exact shipped text, then a blank line) is sha256-checked
                  block-by-block and used to locate/quote deliveries; when
                  absent the auditor degrades to hash-locating panel slices.
                  A fully reconciled ledger with clean leak/dose laws earns
                  GREEN-delivered (proven delivery), distinct from GREEN-quiet.

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
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from gt_engine.attribution import summarize_features, verify_trace_rows  # noqa: E402

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
# GT L1 host-side telemetry (bare stdout between panels, never model-facing;
# verified in-panel count = 0 across the smoke artifact). Known shape, so it
# is consumed - an occurrence INSIDE a panel is flagged separately.
_GT_L1_RE = re.compile(r"^\[GT L1\] ")

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
    gt_l1_lines: int = 0  # host-side [GT L1] telemetry lines (outside panels)
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
        if _GT_L1_RE.match(line):
            t.gt_l1_lines += 1
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
# LEDGER-JOIN: reconcile GT-side seals (gt_ledger.jsonl) against the transcript
# --------------------------------------------------------------------------- #
# Hash contract (verified against the real smoke artifact tb2-gt-30501483446):
#   rendered_bytes_hash = sha256(shipped bytes); shipped = the delivery lines
#   joined with '\n' + a trailing '\n', with ONE leading '\n' only when the
#   base observation did not already end in a newline (bridge._join).
#   len_shipped_chars = len(shipped).  event_id N (gateway/covering) rides the
#   N-th tool observation = the N-th tool_result panel (1-based); event_id 0
#   with boundary=task_start rides the initial user message, which the nano
#   CLI never prints.  The CLI displays output[:2000] per panel - a suffix
#   past that boundary is model-received but transcript-invisible.
_DISPLAY_CAP = 2000
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_LEDGER_KEYS = ("event_id", "boundary", "evidence_type", "tier", "dedup_key",
                "rendered_bytes_hash", "chain_head", "len_shipped_chars")
# statuses
CONFIRMED = "TRANSCRIPT-CONFIRMED"
MODEL_ONLY = "MODEL-ONLY"
UNRECONCILED = "UNRECONCILED"

_DELIV_EVENT_RE = re.compile(r"\bevent_id=(\S+)")
_DELIV_HASH_RE = re.compile(r"\brendered_bytes_hash=([0-9a-fA-F]{64})\b")


@dataclass
class LedgerRow:
    event_id: str
    boundary: str
    evidence_type: str
    tier: str
    dedup_key: str
    rendered_bytes_hash: str
    chain_head: str
    len_shipped_chars: int
    status: str = UNRECONCILED
    status_reason: str = ""
    quote: str = ""


def load_ledger(path: Path) -> tuple[list[LedgerRow], list[str]]:
    """Parse gt_ledger.jsonl. Malformed lines are ISSUES (fail loud), never
    silently dropped - a seal record the auditor cannot read is a seal record
    it cannot clear."""
    rows: list[LedgerRow] = []
    issues: list[str] = []
    for i, raw in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            d = json.loads(raw)
            if not isinstance(d, dict):
                raise ValueError("not an object")
        except (json.JSONDecodeError, ValueError) as e:
            issues.append(f"gt_ledger.jsonl line {i}: unparseable ({e})")
            continue
        missing = [k for k in _LEDGER_KEYS if k not in d]
        if missing:
            issues.append(f"gt_ledger.jsonl line {i}: missing keys {missing}")
        try:
            shipped = int(d.get("len_shipped_chars", 0))
        except (TypeError, ValueError):
            shipped = 0
            issues.append(f"gt_ledger.jsonl line {i}: non-integer len_shipped_chars")
        rows.append(LedgerRow(
            event_id=str(d.get("event_id", "")), boundary=str(d.get("boundary", "")),
            evidence_type=str(d.get("evidence_type", "")), tier=str(d.get("tier", "")),
            dedup_key=str(d.get("dedup_key", "")),
            rendered_bytes_hash=str(d.get("rendered_bytes_hash", "")),
            chain_head=str(d.get("chain_head", "")), len_shipped_chars=shipped))
    return rows, issues


_DELIV_HEADER_LINE_RE = re.compile(
    r"^(?=.*\bevent_id=\S)(?=.*\brendered_bytes_hash=[0-9a-fA-F]{64}\b).*$",
    re.MULTILINE)


def load_deliveries(path: Path) -> tuple[dict[str, str], list[str]]:
    """Parse the OPTIONAL gt_deliveries.txt: per-delivery framed blocks - a
    header line carrying event_id=... rendered_bytes_hash=<64hex> (the bridge
    writes ``--- event_id=<id> boundary=<b> evidence_type=<t>
    rendered_bytes_hash=<h> ---``), then the EXACT shipped bytes, then a blank
    line.  Framing is header-delimited (the shipped text itself may begin with
    a newline or contain blank lines), and each block is sha256-verified
    against its header hash with the writer's ``shipped + '\\n\\n'`` frame
    peeled 0-2 trailing newlines.  Returns {event_id: verified_text}; a block
    that fails verification is an ISSUE and yields no text - tampered bytes
    must never be used to 'confirm' a delivery."""
    texts: dict[str, str] = {}
    issues: list[str] = []
    content = path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
    headers = list(_DELIV_HEADER_LINE_RE.finditer(content))
    if not headers:
        issues.append("gt_deliveries.txt: no delivery header lines recognized")
        return texts, issues
    lead = content[:headers[0].start()]
    if lead.strip():
        issues.append(
            f"gt_deliveries.txt: unrecognized content before the first header: "
            f"{lead.strip()[:80]}")
    for k, m in enumerate(headers):
        eid = _DELIV_EVENT_RE.search(m.group(0)).group(1)  # guaranteed by regex
        want = _DELIV_HASH_RE.search(m.group(0)).group(1).lower()
        start = m.end()
        if start < len(content) and content[start] == "\n":
            start += 1
        end = headers[k + 1].start() if k + 1 < len(headers) else len(content)
        seg = content[start:end]
        verified = None
        for cand in (seg, seg[:-1] if seg.endswith("\n") else None,
                     seg[:-2] if seg.endswith("\n\n") else None,
                     seg + "\n"):
            if cand and hashlib.sha256(
                    cand.encode("utf-8", "surrogatepass")).hexdigest() == want:
                verified = cand
                break
        if verified is None:
            issues.append(
                f"gt_deliveries.txt event {eid}: block text fails sha256 against "
                f"header hash {want[:12]}... (tamper or corruption)")
        elif eid in texts:
            issues.append(f"gt_deliveries.txt: duplicate block for event {eid}")
        else:
            texts[eid] = verified
    return texts, issues


def _hash_scan_panel(panel: Panel, row: LedgerRow) -> str | None:
    """Try to find a contiguous run of panel lines whose joined text (with the
    bridge's newline variants) hashes to the row's rendered_bytes_hash.
    Returns the matched shipped text, or None."""
    lines = panel.lines
    want = row.rendered_bytes_hash
    target = row.len_shipped_chars
    for j in range(len(lines), 0, -1):
        for i in range(j - 1, -1, -1):
            cand = "\n".join(lines[i:j]) + "\n"
            if len(cand) > target + 1:
                break  # extending further back only grows the candidate
            if len(cand) == target and hashlib.sha256(
                    cand.encode("utf-8", "surrogatepass")).hexdigest() == want:
                return cand
            if len(cand) + 1 == target and hashlib.sha256(
                    ("\n" + cand).encode("utf-8", "surrogatepass")).hexdigest() == want:
                return "\n" + cand
    return None


def _target_panel(row: LedgerRow, tool_panels: list[Panel]) -> tuple[int, Panel] | None:
    """event_id N (1-based tool-action index) -> the N-th tool_result panel."""
    try:
        idx = int(row.event_id)
    except ValueError:
        return None
    if 1 <= idx <= len(tool_panels):
        return idx, tool_panels[idx - 1]
    return None


def _first_line(text: str) -> str:
    for ln in text.splitlines():
        if ln.strip():
            return ln.strip()[:120]
    return ""


def reconcile_ledger(rows: list[LedgerRow], tool_panels: list[Panel],
                     deliveries: dict[str, str], deliveries_issue_ids: set[str],
                     ) -> None:
    """Assign a reconciliation status to every ledger row, in place."""
    for row in rows:
        # 0. a deliveries block that FAILED its hash check poisons the row:
        #    the one byte-source we were given is untrustworthy -> F1 class.
        if row.event_id in deliveries_issue_ids:
            row.status = UNRECONCILED
            row.status_reason = ("gt_deliveries.txt block for this event fails "
                                 "its sha256 check - byte source untrusted")
            continue
        text = deliveries.get(row.event_id)
        # 1. byte-exact join via the deliveries file (when present).
        if text is not None:
            if hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest() \
                    != row.rendered_bytes_hash:
                row.status = UNRECONCILED
                row.status_reason = ("gt_deliveries.txt bytes verify against their "
                                     "header but NOT against the ledger row hash "
                                     "(ledger/deliveries disagree)")
                continue
            body = text.strip("\n")
            hit = None
            for k, p in enumerate(tool_panels, start=1):
                if body and body in p.text:
                    hit = (k, p, "byte-exact")
                    break
                joined = " ".join(ln.strip() for ln in p.lines if ln.strip())
                if body and all(ln.strip() in joined
                                for ln in body.splitlines() if ln.strip()):
                    hit = (k, p, "wrap-tolerant")
                    break
            if hit:
                k, p, how = hit
                row.status = CONFIRMED
                row.status_reason = (f"deliveries-file bytes located ({how}) in "
                                     f"tool_result #{k} (panel line {p.start_line})")
                row.quote = _first_line(text)
                continue
            # fall through: bytes known but not visible - explain or escalate
        else:
            # 2. no byte source: hash-locate a panel slice (target panel first,
            #    then all panels - deterministic order).
            ordered: list[tuple[int, Panel]] = []
            tp = _target_panel(row, tool_panels)
            if tp:
                ordered.append(tp)
            ordered.extend((k, p) for k, p in enumerate(tool_panels, start=1)
                           if not tp or p is not tp[1])
            located = None
            for k, p in ordered:
                m = _hash_scan_panel(p, row)
                if m is not None:
                    located = (k, p, m)
                    break
            if located:
                k, p, m = located
                row.status = CONFIRMED
                row.status_reason = (f"sha256 of a panel slice matches the seal - "
                                     f"tool_result #{k} (panel line {p.start_line})")
                row.quote = _first_line(m)
                continue
        # 3. explained invisibility, else UNRECONCILED.
        if row.boundary == "task_start":
            row.status = MODEL_ONLY
            row.status_reason = ("task_start capsule rides the initial user "
                                 "message, which the nano CLI never prints - "
                                 "invisible by construction")
            continue
        tp = _target_panel(row, tool_panels)
        if tp and len(tp[1].text) >= _DISPLAY_CAP:
            row.status = MODEL_ONLY
            row.status_reason = (
                f"display-cap truncation: tool_result #{tp[0]} (panel line "
                f"{tp[1].start_line}) shows >= {_DISPLAY_CAP} chars - the CLI "
                f"prints output[:{_DISPLAY_CAP}], so the GT suffix sits past "
                f"the display window (model-received, transcript-invisible)")
            continue
        row.status = UNRECONCILED
        if tp is None:
            row.status_reason = (f"event_id {row.event_id!r} maps to no tool "
                                 f"observation ({len(tool_panels)} panels seen) "
                                 "and bytes were not located anywhere")
        else:
            row.status_reason = (f"tool_result #{tp[0]} (panel line "
                                 f"{tp[1].start_line}, {len(tp[1].text)} chars, "
                                 "under the display cap) does not contain the "
                                 "sealed bytes - potential delivery lie")


def check_ledger_integrity(rows: list[LedgerRow]) -> tuple[list[str], list[str]]:
    """Chain/dedup integrity + the ledger-truth dose law.
    Returns (integrity_issues, dose_violations)."""
    issues: list[str] = []
    dose: list[str] = []
    seen_heads: dict[str, str] = {}
    seen_dedup: dict[str, str] = {}
    prev_eid: int | None = None
    gateway_per_event: dict[str, int] = {}
    for r in rows:
        if not _HEX64_RE.match(r.chain_head):
            issues.append(f"ev{r.event_id}: chain_head is not 64-hex "
                          f"({r.chain_head[:16]!r}...)")
        elif r.chain_head in seen_heads:
            issues.append(f"ev{r.event_id}: chain_head duplicates "
                          f"ev{seen_heads[r.chain_head]} (chain must strictly "
                          "advance; identical heads = replay/tamper)")
        else:
            seen_heads[r.chain_head] = r.event_id
        if r.dedup_key:
            if r.dedup_key in seen_dedup:
                issues.append(f"ev{r.event_id}: dedup_key {r.dedup_key} already "
                              f"sealed at ev{seen_dedup[r.dedup_key]} (double "
                              "delivery of one fact)")
            else:
                seen_dedup[r.dedup_key] = r.event_id
        try:
            eid = int(r.event_id)
            if prev_eid is not None and eid < prev_eid:
                issues.append(f"ev{r.event_id}: event_id regressed after "
                              f"ev{prev_eid} (seal order must advance)")
            prev_eid = eid
        except ValueError:
            issues.append(f"non-numeric event_id {r.event_id!r}")
        if r.boundary in ("gateway", "covering"):
            gateway_per_event[r.event_id] = gateway_per_event.get(r.event_id, 0) + 1
    for eid in sorted(gateway_per_event, key=lambda s: (len(s), s)):
        if gateway_per_event[eid] > 1:
            dose.append(f"ledger dose-law violation: {gateway_per_event[eid]} "
                        f"gateway/covering rows sealed for event {eid} "
                        "(at most ONE dose per observation)")
    return issues, dose


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
    # gt activity (gt_deliveries = ledger truth when a ledger exists,
    # else the heuristic transcript-block count)
    code_task: bool = False
    gt_deliveries: int = 0
    gt_delivery_kinds: dict[str, int] = field(default_factory=dict)
    gt_overhead_chars: int = 0
    gt_blocks_observed: int = 0  # heuristic count, always reported
    # ledger join
    ledger_present: bool = False
    deliveries_file_present: bool = False
    ledger_rows: list[LedgerRow] = field(default_factory=list)
    ledger_issues: list[str] = field(default_factory=list)
    # complete opportunity/decision/exposure trace (new runs only)
    attribution_present: bool = False
    attribution_rows: int = 0
    attribution_issues: list[str] = field(default_factory=list)
    feature_attribution: dict[str, dict] = field(default_factory=dict)
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


def load_attribution(path: Path) -> tuple[list[dict], list[str]]:
    """Load and integrity-check the append-only GT attribution stream."""
    rows: list[dict] = []
    issues: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return [], [f"gt_attribution.jsonl: unreadable ({type(exc).__name__})"]
    for index, line in enumerate(lines, 1):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            issues.append(f"gt_attribution.jsonl line {index}: unparseable")
            continue
        if not isinstance(value, dict):
            issues.append(f"gt_attribution.jsonl line {index}: not an object")
            continue
        rows.append(value)
    if len(rows) == len(lines):
        issues.extend(verify_trace_rows(rows))
    return rows, issues


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

    # LEDGER-JOIN inputs --------------------------------------------------- #
    ledger_path = task_dir / "agent" / "gt_ledger.jsonl"
    a.ledger_present = ledger_path.is_file()
    ledger_rows: list[LedgerRow] = []
    if a.ledger_present:
        ledger_rows, issues = load_ledger(ledger_path)
        a.ledger_issues.extend(issues)
    deliveries_texts: dict[str, str] = {}
    deliveries_bad_ids: set[str] = set()
    deliv_path = task_dir / "agent" / "gt_deliveries.txt"
    a.deliveries_file_present = deliv_path.is_file()
    if a.deliveries_file_present:
        deliveries_texts, dl_issues = load_deliveries(deliv_path)
        a.ledger_issues.extend(dl_issues)
        for msg in dl_issues:
            m = re.search(r"event (\S+):", msg)
            if m:
                deliveries_bad_ids.add(m.group(1))

    # ATTRIBUTION-JOIN inputs --------------------------------------------- #
    attribution_path = task_dir / "agent" / "gt_attribution.jsonl"
    a.attribution_present = attribution_path.is_file()
    attribution_rows: list[dict] = []
    if a.attribution_present:
        attribution_rows, attr_issues = load_attribution(attribution_path)
        a.attribution_rows = len(attribution_rows)
        a.attribution_issues.extend(attr_issues)
        a.feature_attribution = summarize_features(attribution_rows)
        for row in attribution_rows:
            payload = row.get("payload", {})
            if (row.get("event_type") == "decision.committed"
                    and payload.get("decision") == "telemetry_fault"):
                a.attribution_issues.append(
                    f"trace event {row.get('sequence', '?')}: "
                    f"{payload.get('reason') or 'telemetry_fault'} "
                    f"({payload.get('fault_type') or 'unknown fault'})"
                )
        if a.ledger_present and not attr_issues:
            traced = {
                (
                    str(row.get("payload", {}).get("delivery_id") or ""),
                    str(row.get("payload", {}).get("evidence_type") or ""),
                    str(row.get("payload", {}).get("rendered_bytes_hash") or ""),
                )
                for row in attribution_rows
                if row.get("event_type") == "decision.committed"
                and row.get("payload", {}).get("decision") == "delivered"
            }
            sealed = {
                (row.event_id, row.evidence_type, row.rendered_bytes_hash)
                for row in ledger_rows
            }
            if traced != sealed:
                missing = len(sealed - traced)
                extra = len(traced - sealed)
                a.attribution_issues.append(
                    "delivery/attribution join mismatch: "
                    f"{missing} sealed row(s) missing, {extra} trace-only row(s)"
                )

    # 2-6. per-panel checks ------------------------------------------------ #
    all_blocks: list[GTBlock] = []
    tool_panels: list[Panel] = []
    for p in t.panels:
        if p.title.startswith("tool_result"):
            a.tool_results += 1
            tool_panels.append(p)
            if p.title == "tool_result (error)" or p.text.startswith("ERROR:"):
                a.tool_errors += 1
            blocks = detect_gt_blocks(p)
            all_blocks.extend(blocks)
            if len(blocks) > 1 and not a.ledger_present:
                # heuristic dose law - ledger truth supersedes it when present
                kinds = ", ".join(b.kind for b in blocks)
                a.dose_violations.append(
                    f"panel at line {p.start_line}: {len(blocks)} GT blocks in one "
                    f"observation ({kinds})")
            if any(_GT_L1_RE.match(ln) for ln in p.lines):
                a.review_flags.append(
                    f"[GT L1] telemetry INSIDE a model-facing panel at line "
                    f"{p.start_line} - host diagnostics leaked into an observation")
        elif p.title == "tool_call":
            if _SOURCE_EXT_RE.search(p.text) or p.text.startswith("edit_file("):
                a.code_task = True

    a.gt_blocks_observed = len(all_blocks)
    for b in all_blocks:
        if _TEST_IDENTITY_RE.search(b.text):
            a.review_flags.append(
                f"possible test identity inside GT block ({b.kind}, panel line "
                f"{b.panel_start_line}) - human review")

    if a.ledger_present:
        # ledger truth replaces the heuristic count (fired-side undercounts -
        # bare grep rows, display caps, task_start - become explained rows).
        a.gt_deliveries = len(ledger_rows)
        for r in ledger_rows:
            a.gt_delivery_kinds[r.evidence_type] = \
                a.gt_delivery_kinds.get(r.evidence_type, 0) + 1
            a.gt_overhead_chars += r.len_shipped_chars
        reconcile_ledger(ledger_rows, tool_panels, deliveries_texts,
                         deliveries_bad_ids)
        integ, dose = check_ledger_integrity(ledger_rows)
        a.ledger_issues.extend(integ)
        a.dose_violations.extend(dose)
        a.ledger_rows = ledger_rows
    else:
        a.gt_deliveries = len(all_blocks)
        for b in all_blocks:
            a.gt_delivery_kinds[b.kind] = a.gt_delivery_kinds.get(b.kind, 0) + 1
            a.gt_overhead_chars += len(b.text)
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
    if a.attribution_issues:
        a.verdict_reasons.extend(a.attribution_issues)
    attribution_red = [
        feature_id
        for feature_id, item in a.feature_attribution.items()
        if item.get("status") in {
            "TRIGGERED_DARK",
            "TELEMETRY_FAULT",
            "DELIVERED_UNEXPOSED",
            "EXPOSED",
        }
    ]
    if attribution_red:
        a.verdict_reasons.append(
            "attribution RED feature(s): " + ", ".join(sorted(attribution_red))
        )
    unreconciled = [r for r in a.ledger_rows if r.status == UNRECONCILED]
    for r in unreconciled:
        a.verdict_reasons.append(
            f"UNRECONCILED ledger row ev{r.event_id} ({r.evidence_type}, "
            f"{r.len_shipped_chars}c): {r.status_reason}")
    if (a.agent_error or a.exception_info or a.leak_tag_count
            or a.stop_reason == "error" or unreconciled
            or a.attribution_issues or attribution_red):
        a.verdict = "RED"
        return a

    if a.ledger_issues:
        a.verdict_reasons.extend(a.ledger_issues)
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
    elif a.ledger_present:
        # every sealed row is TRANSCRIPT-CONFIRMED or explained MODEL-ONLY,
        # leak/dose/chain laws clean: delivery is PROVEN, not just quiet.
        confirmed = sum(1 for r in a.ledger_rows if r.status == CONFIRMED)
        model_only = sum(1 for r in a.ledger_rows if r.status == MODEL_ONLY)
        a.verdict = "GREEN-delivered"
        a.verdict_reasons.append(
            f"{len(a.ledger_rows)} sealed deliver(y/ies) fully reconciled: "
            f"{confirmed} transcript-confirmed, {model_only} model-only "
            "(explained); chain and dose laws clean")
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
    out.append("=" * 104)
    hdr = (_fmt("task", 34) + _fmt("verdict", 16) + _fmt("stop", 12) + _fmt("iter", 6)
           + _fmt("in/out tok", 16) + _fmt("reward", 8) + _fmt("gt", 5) + _fmt("err%", 6))
    out.append(hdr)
    out.append("-" * 104)
    for a in audits:
        tok = None
        if a.in_tokens is not None or a.out_tokens is not None:
            tok = f"{a.in_tokens or 0}/{a.out_tokens or 0}"
        er = None if a.error_rate is None else f"{a.error_rate:.0%}"
        gt_col = f"{a.gt_deliveries}L" if a.ledger_present else str(a.gt_deliveries)
        out.append(_fmt(a.task_name, 34) + _fmt(a.verdict, 16) + _fmt(a.stop_reason, 12)
                   + _fmt(a.iterations, 6) + _fmt(tok, 16) + _fmt(a.reward, 8)
                   + _fmt(gt_col, 5) + _fmt(er, 6))
    out.append("-" * 104)
    out.append("gt column: deliveries ('NL' = N sealed rows from gt_ledger.jsonl = "
               "ledger truth; bare N = transcript heuristic, no ledger)")
    for a in audits:
        out.append(f"\n{a.task_name} [{a.verdict}]")
        for r in a.verdict_reasons:
            out.append(f"  - {r}")
        if a.gt_delivery_kinds:
            out.append(f"  - GT delivery kinds: {a.gt_delivery_kinds}")
        if a.gt_overhead_chars:
            src = "sealed (ledger)" if a.ledger_present else "observable"
            out.append(f"  - GT overhead {src}: {a.gt_overhead_chars} chars")
        if a.ledger_present:
            n_c = sum(1 for r in a.ledger_rows if r.status == CONFIRMED)
            n_m = sum(1 for r in a.ledger_rows if r.status == MODEL_ONLY)
            n_u = sum(1 for r in a.ledger_rows if r.status == UNRECONCILED)
            deliv = (" + gt_deliveries.txt" if a.deliveries_file_present else "")
            out.append(f"  - LEDGER{deliv}: {len(a.ledger_rows)} sealed row(s) | "
                       f"{n_c} {CONFIRMED}, {n_m} {MODEL_ONLY}, {n_u} {UNRECONCILED}"
                       f" | heuristic blocks observed: {a.gt_blocks_observed}")
            for r in a.ledger_rows:
                line = (f"      ev{_fmt(r.event_id, 5)} "
                        f"{_fmt(r.evidence_type, 22)} {_fmt(r.tier, 11)} "
                        f"{_fmt(str(r.len_shipped_chars) + 'c', 6)} {r.status}")
                out.append(line)
                out.append(f"            {r.status_reason}")
                if r.quote:
                    out.append(f"            quote: {r.quote}")
            for s in a.ledger_issues:
                out.append(f"  - LEDGER-ISSUE {s}")
        if a.attribution_present:
            out.append(
                f"  - ATTRIBUTION: {a.attribution_rows} hash-chained event(s), "
                f"{len(a.attribution_issues)} integrity issue(s)"
            )
        for n in a.notes:
            out.append(f"  - note: {n}")
        for s in a.unparsed_samples:
            out.append(f"  - UNPARSED {s}")
        for s in a.unparsed_structures:
            out.append(f"  - UNPARSED-STRUCTURE {s}")
    counts: dict[str, int] = {}
    for a in audits:
        counts[a.verdict] = counts.get(a.verdict, 0) + 1
    feature_ids = sorted({
        feature_id
        for audit in audits
        for feature_id in audit.feature_attribution
    })
    if feature_ids:
        out.append("\n17-FEATURE ATTRIBUTION")
        out.append("=" * 104)
        out.append(
            _fmt("feature", 25) + _fmt("kind", 7) + _fmt("W", 5)
            + _fmt("EXP", 5) + _fmt("UNEXP", 7) + _fmt("DARK", 7)
            + _fmt("SUP", 5) + _fmt("N/A", 5) + _fmt("FAULT", 7)
            + _fmt("delivery", 10) + _fmt("exposed", 9) + "response"
        )
        out.append("-" * 104)
        for feature_id in feature_ids:
            items = [
                audit.feature_attribution[feature_id]
                for audit in audits if feature_id in audit.feature_attribution
            ]
            status_counts = {
                status: sum(item["status"] == status for item in items)
                for status in (
                    "WITNESSED", "EXPOSED", "DELIVERED_UNEXPOSED",
                    "TRIGGERED_DARK", "SUPPRESSED_WITH_REASON", "INELIGIBLE",
                    "TELEMETRY_FAULT",
                )
            }
            out.append(
                _fmt(feature_id, 25)
                + _fmt(items[0]["kind"] if items else "-", 7)
                + _fmt(status_counts["WITNESSED"], 5)
                + _fmt(status_counts["EXPOSED"], 5)
                + _fmt(status_counts["DELIVERED_UNEXPOSED"], 7)
                + _fmt(status_counts["TRIGGERED_DARK"], 7)
                + _fmt(status_counts["SUPPRESSED_WITH_REASON"], 5)
                + _fmt(status_counts["INELIGIBLE"], 5)
                + _fmt(status_counts["TELEMETRY_FAULT"], 7)
                + _fmt(sum(len(item["deliveries"]) for item in items), 10)
                + _fmt(sum(bool(item["exposed"]) for item in items), 9)
                + str(sum(bool(item["response_observed"]) for item in items))
            )
        out.append("-" * 104)
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
