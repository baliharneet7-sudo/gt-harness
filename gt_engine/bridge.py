"""Bridge between nano-harness tool dispatch and the GT Gateway.

Replicates the production seam template ``_gt_gateway_deliver``
(gt_mini_patch.py:16215-16599) with nano's tool vocabulary:

    bash       -> command passed through verbatim (gateway.classify_command
                  decides search/view/edit/test/submit/other)
    read_file  -> synthetic ``cat <relpath>`` carrier + viewed_files authority
    edit_file  -> synthetic ``apply_patch <relpath>`` carrier + changed_files
                  + edit_before_after (the B-3 edit bridges)

Pipeline per observation (all pure/adapter except the append):
    normalize_event -> per-turn GatewayState(shared EpisodeState) -> augment
    -> select(max_doses=1) -> render_envelope(native=?) -> seam leak guard
    -> fits_budget -> SEAL BEFORE APPEND (seal_delivery over the exact shipped
    suffix bytes) -> pure-suffix append.

Laws honored:
- Correct-or-quiet: any exception returns the raw output unchanged.
- Append-only (TITO law 1): evidence is a pure suffix on the observation.
- Dose law: at most ONE envelope per observation (select defaults).
- Leak law: seam-owned rendered-bytes guard (contains_gt_tag /
  contains_test_identity) drops the delta WHOLE.
- Law 8: an over-budget delta is dropped WHOLE, never clipped.
- update_receipts is NOT wired (removed from production 2026-07-28: the acted
  signal was causally inverted).
- covering= is NOT threaded into normalize_event (SM-3). Phase-3 DECISION: the
  covering-RED home is a BRIDGE-OWNED lane at post-edit (production's own home,
  ``_executed_covering_emission`` — gt_mini_patch.py:11980; the gateway's
  ``_produce_covering`` bridge is LEFT DARK INTENTIONALLY there too, :16293).
  Second reason the gateway home is unsound here: the registry declares the
  gateway's ``covering_verdict`` boundary as test_result (fact_registry.py:723
  — only the seam's ``covering_red`` is re-homed to edit_result), so under
  Profile-2's GT_REGISTRY_ENFORCE a covering fact fired on an EDIT event would
  route DEFER — structurally mute. ONE home: when the covering lane delivers,
  the gateway dose is skipped for that observation (dose law, <=1/observation);
  the submit gate consumes the CACHED verdict only as its covering HEAD (G-2),
  which renders submit_refusal-class bytes, never a second Format-D dose.
- L6 freshness (GT_L6_FRESH): after an edit observation touching a source file
  the graph.db is refreshed with a FULL gt-index run (never the -file
  incremental — see ``_refresh_graph``), and a DORMANT bridge (non-code task
  root, graph_db=None) wakes when the agent's edits create source files.
- Delivery ledger: every sealed delivery appends one JSONL line on disk
  (``_ledger_record``) so a transcript auditor can join agent-side blocks
  against GT-side seals 1:1 (dose-reconciliation law). Host-side telemetry
  only — never model bytes; a ledger fault never affects delivery.
- Deliveries file (FIX A): alongside the ledger, ``gt_deliveries.txt`` records
  the VERBATIM shipped bytes per sealed delivery (``_deliveries_record``) —
  the human-auditable record for deliveries the transcript display hides
  (task-start rides the unprinted seed message; long suffixes fall past the
  CLI's [:2000] cap). Contains payload bytes: lives in /logs/agent when
  possible; the <root>/.gt fallback is self-gitignored + rm'd pre-snapshot.
- Recovery lane (FIX B, GT_HYPOTHESIS): the HypothesisLedger's typed
  falsification rule over the shared EpisodeState — the SAME genuine test
  failure recurring after an intervening edit delivers ONE short native
  imperative at HYPOTHESIS tier (never [VERIFIED]), once per signature per
  episode, only when the gateway dose was quiet (ladder floor, dose law).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

# Budget for one delivered delta (chars). Matches the adapter default.
MAX_DELTA_CHARS = 4000

# tools.py:172 flattens a failed bash command into ToolError text ending with
# "[exit code N]". nano gives the agent only (output_string, is_error) - the
# exit code must be parsed back out of the string.
_EXIT_CODE_RE = re.compile(r"\[exit code (-?\d+)\]\s*$")
_AGGREGATE_CHECK_RE = re.compile(
    r"(?im)\b(?:ALL\s+TARGETS\s+MET|OVERALL\s+PASS)\s*[:=]\s*(True|False)\b"
)
_ITEM_CHECK_RE = re.compile(
    r"(?im)\b[A-Za-z][A-Za-z0-9_ -]{0,30}\s*[:=]\s*"
    r"(true|false|pass|fail)\b"
)
_CHECK_EXEC_RE = re.compile(
    r"(?i)(?:^|[;&|]\s*)(?:python\d*|node|pytest|npm\s+test|"
    r"(?:bash|sh)\s+\S*(?:test|check|verify)\S*)\b"
)


def _explicit_check_outcome(output: str) -> str | None:
    """Classify explicit boolean verifier output without reading prose."""
    aggregate = _AGGREGATE_CHECK_RE.findall(output or "")
    if aggregate:
        return "pass" if aggregate[-1].lower() == "true" else "fail"
    items = [item.lower() for item in _ITEM_CHECK_RE.findall(output or "")]
    if not items:
        return None
    return "fail" if {"false", "fail"} & set(items) else "pass"


def _minimal_pair() -> None:
    """The minimal deterministic flag pair (last-resort / explicit-legacy)."""
    os.environ.setdefault("GT_GATEWAY", "1")
    os.environ.setdefault("GT_GATEWAY_NATIVE", "1")


def apply_profile_env() -> None:
    """Apply the GT capability-flag environment at init (decision E).

    Production parity (AGENTS.md §C / rl_profile W8 inversion): every GT-on arm
    runs Profile-2, and an UNSET ``GT_RL_PROFILE`` resolves the production
    default. So:

    - GT_RL_PROFILE unset  -> ``resolve_profile_defaults`` (W8: Profile-2 members
      + behavior flags, each "1").
    - GT_RL_PROFILE = explicit token -> ``resolve_profile_defaults`` (that
      profile's members and behavior flags; an explicit env value rides
      through unchanged at the ``setdefault`` seam).
    - GT_RL_PROFILE = explicit "0"/"off"/"none" -> the legacy/control posture:
      no fan-out, only the minimal pair (the bridge still needs GT_GATEWAY to
      produce anything at all; a user who wants GT fully off unsets --gt-root
      or sets GT_GATEWAY=0).

    Every value is applied with ``setdefault`` so an explicit user env value
    (including "0") always wins — the resolver never sets os.environ itself.
    GT_XSESSION_* is never set here (durable cross-session memory: skipped for
    deterministic A/B runs). An unknown profile token resolves no members and
    falls back to the minimal pair (never silently dark).
    """
    try:
        profile = (os.environ.get("GT_RL_PROFILE") or "").strip()
        if profile and profile.lower() in ("0", "off", "none"):
            _minimal_pair()  # explicit legacy posture: no profile fan-out
            return
        from groundtruth.runtime.rl_profile import resolve_profile_defaults

        # Use the defaults resolver for both an unset token and an explicit
        # profile token. ``resolve_profile`` returns inventory members only;
        # it deliberately excludes PROFILE_BEHAVIOR_FLAGS. Workflows set
        # GT_RL_PROFILE=2 explicitly, so using resolve_profile here silently
        # disabled the seven Profile-2 behavior switches in every live run.
        members = resolve_profile_defaults(os.environ)
        for k, v in members.items():
            if k.startswith("GT_XSESSION"):
                continue  # durable cross-session memory: off for determinism
            os.environ.setdefault(k, v)
        if not members:
            _minimal_pair()  # unknown token: never silently dark
    except Exception:  # noqa: BLE001 - misconfigured profile must not break the run
        _minimal_pair()


def parse_exit_code(output: str, is_error: bool) -> int | None:
    """Exit code for a bash observation (decision C).

    Success -> 0. Failure -> parse the trailing "[exit code N]" tools.py:172
    embeds in the ToolError text; unparsable (timeout, dead shell, dispatch
    error) -> None.
    """
    if not is_error:
        return 0
    m = _EXIT_CODE_RE.search(output or "")
    return int(m.group(1)) if m else None


def gateway_observation_output(
    command: str, output: str, returncode: int | None
) -> str:
    """Restore an empty failed-search observation for Groundtruth only.

    ``BashTool`` appends ``[exit code 1]`` to every failed command. For a grep
    with no stdout this turns the physically empty result into non-empty text,
    so Groundtruth classifies it as ``search_result`` instead of
    ``failed_search`` and the repeated-absence/new-file trigger is unreachable.

    Strip only a lone exit-code marker, only for a search, only for rc=1.
    Real diagnostics, other return codes, and the model-visible observation
    remain byte-identical.
    """
    if returncode != 1:
        return output
    try:
        from groundtruth.runtime.gateway import KIND_SEARCH, classify_command

        if classify_command(command) != KIND_SEARCH:
            return output
    except Exception:  # noqa: BLE001 - classifier fault preserves raw truth
        return output
    without_marker = _EXIT_CODE_RE.sub("", output or "")
    return "" if not without_marker.strip() else output


# --------------------------------------------------------------------------- #
# Recovery / GT_HYPOTHESIS lane (FIX B): failure-signature normalization.
# Port of production ``_hypothesis_failure_fingerprint``
# (gt_mini_patch.py:12658-12686): marker-line extraction (last 8), volatile-
# numeric + path-token scrub, sha256[:16] — with ONE deliberate divergence
# (W2-R6 fix, see inline): assertion-value numerals are PRESERVED so numeric
# progress never fingerprints as an unchanged failure. HOST-ONLY:
# the hash is the repeat key in EpisodeState.failure_fingerprints — it is
# NEVER emitted to the model (the model surface is the generic imperative).
# The W4 infra-noise guard (GT_INFRA_NOISE_GUARD, Profile-2 member) keeps
# harness teardown noise out of the failure-repeat memory, exactly as there.
# --------------------------------------------------------------------------- #
_FAILURE_MARKERS = ("error", "failed", "failure", "exception", "traceback",
                    "assert", "fatal", "not found", "cannot", "no such", "panic")


def failure_fingerprint(observation: str) -> str:
    """Deterministic path/number-scrubbed signature of a FAILING observation,
    or "" when it shows no failure (production's exact normalization)."""
    obs = observation or ""
    if os.environ.get("GT_INFRA_NOISE_GUARD", "").strip() == "1":
        try:
            from groundtruth.runtime.patterns import is_infra_noise

            if is_infra_noise(obs):
                return ""
        except Exception:  # noqa: BLE001 - guard absent: fall through (as prod)
            pass
    low = obs.lower()
    if not any(s in low for s in _FAILURE_MARKERS):
        return ""
    sig_lines = [ln.strip() for ln in obs.splitlines()
                 if any(s in ln.lower() for s in _FAILURE_MARKERS)]
    if not sig_lines:
        return ""
    sig = "\n".join(sig_lines[-8:])
    # DIVERGENCE from production (W2-R6 fix): production scrubs ALL numerals,
    # which collides genuinely DIFFERENT failing values ("expected 5 got 3"
    # vs "... got 4") into one key — the recurrence steer then falsely tells
    # a numerically-PROGRESSING agent "the last edit did not change the
    # failing result". We scrub only the numeric classes that are volatile
    # across identical failures — hex addresses, file:line(:col) locators,
    # `line N` traceback refs, durations, timestamps — and PRESERVE the
    # remaining numeric literals (assertion values). Tradeoff: any OTHER
    # volatile numeral (a PID, a port) now shifts the key -> repeat missed ->
    # quiet no-fire; that degrades toward SILENCE, never toward the false
    # steer, while flaky path:line/duration drift still reads as the SAME
    # failure (the failure mode the blanket scrub existed for).
    sig = re.sub(r"0x[0-9a-fA-F]+", "", sig)               # addresses
    sig = re.sub(                                          # file:line(:col)
        r"(?:[\w.-]+[/\\])*[\w-][\w.-]*\.\w+:\d+(?::\d+)?", "", sig)
    sig = re.sub(r"\bline \d+\b", "line", sig)             # traceback refs
    sig = re.sub(                                          # durations
        r"\b\d+(?:\.\d+)?\s*(?:ns|us|ms|s|secs?|seconds?|mins?|minutes?)\b",
        "", sig)
    sig = re.sub(r"\b\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\b", "", sig)   # clock times
    sig = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", "", sig)               # ISO dates
    sig = re.sub(r"[\w.]*[/\\][\w./\\-]+", "", sig)   # path-ish tokens are volatile
    sig = " ".join(sig.split())
    if not sig:
        return ""
    return hashlib.sha256(sig.encode("utf-8", "replace")).hexdigest()[:16]


# --------------------------------------------------------------------------- #
# Bash-mediated edit bridges (B-3 for the bash channel).
#
# Port of the MECHANISM of production's `_gateway_edit_bridges` +
# `_gateway_capture_edit_preimage` (gt_mini_patch.py:15429-15540): a bash edit
# (sed -i, >> redirection, heredoc cat, apply_patch/git apply, a python/node
# in-place write) carries no changed_files/edit_before_after by itself, so the
# edit-turn producers never see it. The production contract:
#   * gated by GT_GATEWAY_EDIT_BRIDGES (default-off byte-identical);
#   * BEFORE-image captured at the PRE-dispatch boundary (a redirect cannot be
#     reverse-applied post-hoc): None = positive evidence of a creation; an
#     ABSENT entry (unreadable / not a file / >1MB) keeps downstream quiet;
#   * AFTER = the file's current on-disk content post-dispatch (<=1MB bound);
#   * unreadable after -> changed_files only, NO before/after fabrication;
#   * correct-or-quiet everywhere - never raises into the delivery path.
# NOT ported (documented gap, production covers more): the staged `< file`
# diff-payload read for `git apply < /tmp/p.diff` (target inside a file on
# disk, not the command text) - such an edit degrades to no bridges, exactly
# the pre-B-3 posture, never a wrong bridge.
# --------------------------------------------------------------------------- #
_MAX_BRIDGE_FILE_BYTES = 1_000_000  # production's snapshot bound

# Broad source-extension gate (production `_has_source_ext`: broad by design,
# /tmp staging included for DETECTION; scratch exclusion is a credit concern).
_SRC_EXTS = (
    ".py", ".pyi", ".go", ".rs", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx",
    ".rb", ".java", ".kt", ".kts", ".cs", ".php", ".swift", ".scala",
    ".c", ".h", ".cc", ".hh", ".cpp", ".hpp", ".m", ".mm", ".lua", ".ex",
    ".exs", ".erl", ".hs", ".ml", ".clj", ".dart", ".zig", ".sh",
)

# Repo-confined structured artifacts are also legitimate task outputs. They do
# not feed the source graph or syntax checker, but tracking their mutation lets
# the unresolved-observed-RED submit head protect data/config/document tasks.
_ARTIFACT_EXTS = (
    ".json", ".jsonl", ".yaml", ".yml", ".toml", ".csv", ".tsv",
    ".xml", ".txt", ".md",
)

# sed -i / tee / patch / apply_patch at line start or after a shell separator
# (production _EDIT_KW_RE).
_EDIT_KW_RE = re.compile(r"(?:^|[|&;]\s*)(sed\s+-i|tee\b|patch\b|apply_patch\b)")
# python / node in-place writes (production _PY_WRITE_RE / _JS_WRITE_RE).
_PY_WRITE_RE = re.compile(r"""open\(\s*['"]([^'"]+)['"]\s*,\s*['"][wa]""")
_JS_WRITE_RE = re.compile(
    r"""(?:writeFileSync|appendFileSync|writeFile)\(\s*['"]([^'"]+)['"]""")
# patch-payload target markers (production _APPLY_PATCH_FILE_RE / _DIFF_PLUS_RE).
_APPLY_PATCH_FILE_RE = re.compile(
    r"^\s*\*\*\*\s+(?:Update|Add)\s+File:\s*(.+?)\s*$", re.MULTILINE)
_DIFF_PLUS_RE = re.compile(r"^\+\+\+\s+(\S+)", re.MULTILINE)
_PATCH_APPLY_RE = re.compile(r"(?:^|[|&;]\s*)(apply_patch\b|git\s+apply\b|patch\b)")
_PATCH_NOOP_RE = re.compile(r"(?:^|\s)--(?:check|stat|numstat|summary|dry-run)\b")
_HEREDOC_DELIM_RE = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
_REDIRECT_RE = re.compile(r">>?\s*([^\s'\"<>|&;]+)")


def _has_source_ext(tok: str) -> bool:
    return (tok or "").replace("\\", "/").lower().endswith(_SRC_EXTS)


def _has_trackable_ext(tok: str) -> bool:
    normalized = (tok or "").replace("\\", "/").lower()
    return normalized.endswith(_SRC_EXTS + _ARTIFACT_EXTS)


def _without_heredoc_bodies(cmd: str) -> str:
    """Executable shell lines with declared heredoc DATA bodies removed
    (production `_shell_without_heredoc_bodies`, simplified: one pending
    delimiter at a time covers the agent's real single-heredoc shapes)."""
    out: list[str] = []
    pending: str | None = None
    for line in (cmd or "").splitlines():
        if pending is not None:
            if line.lstrip("\t") == pending:
                pending = None
            continue
        out.append(line)
        m = _HEREDOC_DELIM_RE.search(line)
        if m:
            pending = m.group(2)
    return "\n".join(out)


def _src_tokens(text: str) -> list[str]:
    toks: list[str] = []
    for tok in re.split(r"\s+", text or ""):
        t = tok.strip("\"'`()<>;|&")
        if _has_source_ext(t) and "*" not in t and "$" not in t:
            toks.append(t)
    return toks


def _trackable_tokens(text: str) -> list[str]:
    toks: list[str] = []
    for tok in re.split(r"\s+", text or ""):
        t = tok.strip("\"'`()<>;|&")
        if _has_trackable_ext(t) and "*" not in t and "$" not in t:
            toks.append(t)
    return toks


def _patch_payload_target(cmd: str) -> str | None:
    """Target of an INLINE-heredoc patch-apply command, or None."""
    first = (cmd or "").split("\n", 1)[0]
    if not _PATCH_APPLY_RE.search(first) or _PATCH_NOOP_RE.search(first):
        return None
    if "<<" not in cmd:
        return None  # staged `< file` payload: not ported (see module note)
    payload = cmd.split("<<", 1)[1]
    nl = payload.find("\n")
    payload = payload[nl + 1:] if nl != -1 else ""
    for m in _APPLY_PATCH_FILE_RE.finditer(payload):
        p = m.group(1).strip().replace("\\", "/")
        if p and p != "/dev/null":
            return p
    for m in _DIFF_PLUS_RE.finditer(payload):
        p = m.group(1).strip().replace("\\", "/")
        if p in ("/dev/null", ""):
            continue
        parts = p.split("/")
        return "/".join(parts[1:]) if len(parts) > 1 else p  # -p1 strip
    return None


def bash_edit_targets(cmd: str) -> tuple[str, ...]:
    """Repo file targets an explicit bash write mutates, in command order."""
    if not cmd:
        return ()
    targets: list[str] = []

    def add(target: str) -> None:
        normalized = (target or "").strip().replace("\\", "/")
        if (
            normalized
            and normalized not in targets
            and "*" not in normalized
            and "$" not in normalized
        ):
            targets.append(normalized)

    pt = _patch_payload_target(cmd)
    if pt:
        add(pt)
        return tuple(targets)
    nohd = _without_heredoc_bodies(cmd)
    redir_fallbacks: list[str] = []
    for mm in _REDIRECT_RE.finditer(nohd):
        t = mm.group(1).strip("\"'`()")
        if _has_trackable_ext(t) and "*" not in t and "$" not in t:
            if t.startswith("/tmp/"):
                if _has_source_ext(t) and t not in redir_fallbacks:
                    redir_fallbacks.append(t)  # scratch: defer
            else:
                add(t)
    if _EDIT_KW_RE.search(cmd.split("\n", 1)[0].lstrip()):
        for target in _trackable_tokens(nohd):
            add(target)
    for rx in (_PY_WRITE_RE, _JS_WRITE_RE):
        for match in rx.finditer(cmd):
            if _has_trackable_ext(match.group(1)):
                add(match.group(1))
    if not targets:
        for target in redir_fallbacks:
            add(target)
    return tuple(targets)


def bash_edit_target(cmd: str) -> str | None:
    """First explicit bash write target (backward-compatible single-target API)."""
    targets = bash_edit_targets(cmd)
    return targets[0] if targets else None


def _edit_bridges_on() -> bool:
    """GT_GATEWAY_EDIT_BRIDGES gate (production `_gateway_edit_bridges_on`).
    Default-off byte-identical; Profile-2 fans it to "1"."""
    return os.environ.get("GT_GATEWAY_EDIT_BRIDGES", "").strip().lower() not in (
        "", "0", "false", "no", "off")


@dataclass
class DeliveredSpan:
    """One delivered evidence suffix, tracked for evidence-aware truncation."""

    text: str  # the exact shipped suffix (incl. any inserted '\n')
    tier: str  # VERIFIED / WARNING / INFO / HYPOTHESIS
    evidence_type: str
    dedup_key: str


@dataclass
class GTBridge:
    """Per-task GT state: ONE EpisodeState for the whole task, a fresh
    GatewayState per turn (the production seam pattern)."""

    repo_root: str
    # None = DORMANT (non-code task root at start). The bridge stays quiet
    # (producers abstain on a missing graph) until an edit observation creates
    # source files and the L6 wake path (_refresh_graph) indexes them.
    graph_db: str | None = None
    issue_text: str = ""
    action_index: int = 0
    chain_head: str = ""  # TITO chain genesis per episode
    deliveries: list[Any] = field(default_factory=list)  # sealed envelopes
    delivered_spans: list[DeliveredSpan] = field(default_factory=list)
    edited_files: list[str] = field(default_factory=list)  # repo-rel, in order
    submit_bounces: int = 0  # gate-kernel refusals already spent this episode

    def __post_init__(self) -> None:
        self.repo_root = self._fwd(self.repo_root)
        from gt_engine.attribution import AttributionTrace

        self._attribution = AttributionTrace(self._attribution_path)
        # Exact shipped text is kept only in memory so exposure can be proven
        # against the provider request. The attribution file stores IDs/hashes,
        # never unrestricted model or tool content.
        self._delivery_texts: dict[str, str] = {}
        self._delivery_metadata: dict[str, dict[str, str]] = {}
        self._capability_receipts: set[tuple[str, str]] = set()
        # Bash-edit pre-images captured at the pre-dispatch boundary:
        # {rel: before_content_or_None}; None = the target did not exist (a
        # creation); an ABSENT key = unreadable/huge -> downstream stays quiet.
        self._bash_preimages: dict[str, str | None] = {}
        # Covering lane state (WIRE 2): files with an executed covering result
        # plus the latest result reused by the submit head. The set is
        # telemetry, not a suppression latch: every later edit changes the
        # revision and creates a new correct-time verification opportunity.
        self._covering_fired: set[str] = set()
        self._last_covering: dict[str, Any] | None = None
        # Recovery lane (FIX B): once-per-signature-per-episode fire latch,
        # burned ONLY on an actual delivery (production burns its counters on
        # delivery too, never on a deferred candidate).
        self._recovery_fired_sigs: set[str] = set()
        # SS-2 observed-RED latch (FIX D, production `_ss_last_failing_test`,
        # gt_mini_patch.py:18947): the most recent formal test event the agent
        # ran that FAILED while TOUCHING an edited surface and has not since
        # gone green. Host-side only; consumed at the submit boundary under
        # GT_SS_SUBMIT_RED.
        self._observed_red: dict[str, Any] | None = None
        # SDLC lifecycle state. Canonical facts remain exception-triggered;
        # these counters prove that the deterministic checkpoint itself ran
        # even when the correct result is quiet (for example, syntax OK).
        self._lifecycle_phases: set[str] = set()
        self._last_source_edit_action = 0
        self._last_green_verification_action = 0
        self._last_test_outcome = ""
        from groundtruth.runtime.episode_state import EpisodeState

        self.episode = EpisodeState()
        self.episode.episode_id = self.repo_root or "episode"

    # ------------------------------------------------------------------ #
    # path normalization (decision J / GT_API_MAP risk 12)
    # ------------------------------------------------------------------ #
    @staticmethod
    def _fwd(p: str) -> str:
        return (p or "").replace("\\", "/")

    def _repo_rel(self, path: str) -> str:
        """Repo-relative forward-slash form of ``path`` for everything entering
        GT. A path outside the repo is returned normalized (never raises)."""
        p = self._fwd(path)
        root = self.repo_root.rstrip("/")
        try:
            if root:
                low_p, low_r = p.lower(), root.lower()
                if low_p == low_r:
                    return ""
                if low_p.startswith(low_r + "/"):
                    return p[len(root) + 1:]
                if not os.path.isabs(path):
                    return p.lstrip("./")
        except Exception:  # noqa: BLE001
            pass
        return p

    # ------------------------------------------------------------------ #
    # WIRE 6: on-disk delivery ledger (both-sides observability).
    # One JSONL line per SEALED delivery, written at seal time, so an auditor
    # can join the agent-side observation blocks against the GT-side seals 1:1
    # (the dose-reconciliation law). No payload bytes (rendered_bytes_hash is
    # the byte-proof), no wall clock (event_id is the order key), no test
    # identity (only already-leak-guarded envelope metadata). Correct-or-quiet:
    # a ledger fault never affects the delivery it records.
    # ------------------------------------------------------------------ #
    _LEDGER_CONTAINER_DIR = "/logs/agent"  # harbor containers' artifact tree

    def _attribution_path(self) -> str | None:
        path = self._ledger_path()
        if not path:
            return None
        return os.path.join(os.path.dirname(path), "gt_attribution.jsonl")

    def _trace_record(
        self,
        event_type: str,
        boundary: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Record behavior-neutral host telemetry; never raise into GT."""
        try:
            self._attribution.record(
                event_type,
                action_index=self.action_index,
                boundary=boundary,
                payload=payload,
            )
        except Exception:  # noqa: BLE001 - observability is always fail-open
            pass

    def _lifecycle_checkpoint(
        self,
        phase: str,
        outcome: str,
        **details: Any,
    ) -> None:
        """Record a content-safe SDLC checkpoint.

        This does not manufacture a canonical feature delivery. It answers
        the orthogonal operational question: did GT execute at the lifecycle
        boundary, and what deterministic result did that checkpoint reach?
        """
        phase = str(phase or "").strip()
        if not phase:
            return
        self._lifecycle_phases.add(phase)
        self._trace_record(
            "lifecycle.checkpoint",
            phase,
            {
                "phase": phase,
                "outcome": str(outcome or "observed"),
                **details,
            },
        )

    def pre_edit_checkpoint(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        *,
        edit_before: str | None = None,
    ) -> None:
        """Observe the real pre-dispatch edit boundary without changing it.

        The checkpoint is deliberately behavior-neutral until GT has positive
        evidence worth interrupting an edit for. It still proves that every
        ``edit_file`` proposal was seen before execution, rather than inferred
        later from a post-edit trajectory.
        """
        try:
            rel = self._repo_rel(str(tool_args.get("path") or ""))
            self._lifecycle_checkpoint(
                "pre_edit",
                "new_file_proposed" if edit_before is None
                else "existing_file_proposed",
                tool_name=str(tool_name),
                target=rel,
                before_available=edit_before is not None,
                proposed_action_index=self.action_index + 1,
            )
        except Exception:  # noqa: BLE001 - checkpoint telemetry is fail-open
            pass

    def _record_feature_census(self) -> None:
        """Snapshot all 17 mechanisms at the penultimate submit boundary."""
        try:
            from gt_engine.attribution import census_trace_rows

            self._trace_record(
                "run.feature_census",
                "submit",
                {"features": census_trace_rows(self._attribution.rows)},
            )
        except Exception:  # noqa: BLE001 - census cannot affect submission
            pass

    @staticmethod
    def _profile_activation_receipt() -> dict[str, Any]:
        """Return names-only proof that the selected profile fully fanned out."""
        profile = (os.environ.get("GT_RL_PROFILE") or "2").strip() or "2"
        try:
            from groundtruth.runtime.rl_profile import (
                PROFILE_BEHAVIOR_FLAGS,
                resolve_profile_defaults,
            )

            expected = sorted(
                name for name in resolve_profile_defaults(os.environ)
                if not name.startswith("GT_XSESSION")
            )
            active = sorted(
                name for name in expected
                if os.environ.get(name, "").strip().lower()
                not in {"", "0", "false", "no", "off"}
            )
            behavior = sorted(
                name for name in PROFILE_BEHAVIOR_FLAGS.get(
                    profile, frozenset()
                )
                if name in active
            )
            return {
                "profile": profile,
                "expected_profile_controls": expected,
                "active_profile_controls": active,
                "expected_profile_control_count": len(expected),
                "active_profile_control_count": len(active),
                "missing_profile_controls": sorted(set(expected) - set(active)),
                "active_behavior_flags": behavior,
                "profile_receipt_fault": "",
            }
        except Exception as exc:  # noqa: BLE001 - receipt cannot break task start
            return {
                "profile": profile,
                "expected_profile_controls": [],
                "active_profile_controls": [],
                "expected_profile_control_count": 0,
                "active_profile_control_count": 0,
                "missing_profile_controls": [],
                "active_behavior_flags": [],
                "profile_receipt_fault": type(exc).__name__,
            }

    def _producer_record(self, row: dict[str, Any]) -> None:
        """Adapter for GT core's ``gt.producer_invocation.v1`` hook."""
        safe = dict(row)
        self._trace_record(
            "producer.invocation",
            str(safe.get("event_type") or "gateway"),
            safe,
        )

    def _control_record(
        self,
        feature_id: str,
        decision_site: str,
        decision: str,
        **extra: Any,
    ) -> None:
        """Adapter for GT core control decisions, excluding candidate bytes."""
        candidate = str(extra.pop("candidate_bytes", "") or "")
        if candidate:
            import hashlib

            extra["candidate_sha256"] = hashlib.sha256(
                candidate.encode("utf-8", "surrogatepass")
            ).hexdigest()
            extra["candidate_chars"] = len(candidate)
        self._trace_record(
            "control.decision",
            "gateway",
            {
                "feature_id": str(feature_id),
                "decision_site": str(decision_site),
                "decision": str(decision),
                **extra,
            },
        )

    def _ledger_path(self) -> str | None:
        try:
            if os.path.isdir(self._LEDGER_CONTAINER_DIR):
                return self._LEDGER_CONTAINER_DIR + "/gt_ledger.jsonl"
            if not self.repo_root:
                return None
            gt_dir = os.path.join(self.repo_root, ".gt")
            os.makedirs(gt_dir, exist_ok=True)
            ignore = os.path.join(gt_dir, ".gitignore")
            if not os.path.exists(ignore):
                with open(ignore, "w", encoding="utf-8") as fh:
                    fh.write("*\n")  # never pollute the task's diff
            return os.path.join(gt_dir, "gt_ledger.jsonl")
        except Exception:  # noqa: BLE001 - no ledger home: stay quiet
            return None

    def _ledger_record(
        self,
        sealed: Any,
        shipped: str,
        boundary: str,
        *,
        capability_ids: tuple[str, ...] = (),
    ) -> None:
        """Append one delivery line (+ the verbatim shipped-bytes block, FIX A).
        Never raises; a failed write does NOT unseal the delivery (the seal
        already happened). ``shipped`` is the EXACT appended suffix text."""
        event_id = str(getattr(sealed, "event_id", "") or "")
        evidence_type = str(getattr(sealed, "evidence_type", "") or "")
        try:
            path = self._ledger_path()
            if not path:
                return
            import json

            line = json.dumps({
                "event_id": event_id,
                "evidence_type": evidence_type,
                "tier": str(getattr(sealed, "tier", "") or ""),
                "dedup_key": str(getattr(sealed, "dedup_key", "") or ""),
                "rendered_bytes_hash": str(
                    getattr(sealed, "rendered_bytes_hash", "") or ""),
                "chain_head": self.chain_head,
                "len_shipped_chars": int(len(shipped)),
                "boundary": boundary,
            }, sort_keys=True)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
                fh.flush()
        except Exception:  # noqa: BLE001 - ledger failure must never break delivery
            pass
        self._deliveries_record(sealed, shipped, boundary)
        self._delivery_texts[event_id] = shipped
        self._delivery_metadata[event_id] = {
            "evidence_type": evidence_type,
            "producer": str(getattr(sealed, "producer", "") or ""),
            "target": str(getattr(sealed, "target", "") or ""),
        }
        from gt_engine.attribution import feature_for_evidence

        fact_id = feature_for_evidence(evidence_type) or ""
        self._trace_record(
            "decision.committed",
            boundary,
            {
                "decision": "delivered",
                "reason": "sealed_and_delivered",
                "delivery_id": event_id,
                "evidence_type": evidence_type,
                "feature_id": fact_id,
                "rendered_bytes_hash": str(
                    getattr(sealed, "rendered_bytes_hash", "") or ""
                ),
                "shipped_chars": len(shipped),
            },
        )
        for capability_id in capability_ids:
            self._record_capability_applied(
                capability_id,
                fact_id=fact_id,
                boundary=boundary,
                delivery_id=event_id,
            )

    def _record_capability_applied(
        self,
        feature_id: str,
        *,
        fact_id: str,
        boundary: str,
        delivery_id: str = "",
        reason: str = "producer_applied",
    ) -> None:
        """Record a capability only at the decision site that applied it."""
        key = (str(feature_id), str(delivery_id))
        if key in self._capability_receipts:
            return
        self._capability_receipts.add(key)
        self._trace_record(
            "capability.applied",
            boundary,
            {
                "feature_id": str(feature_id),
                "fact_id": str(fact_id),
                "delivery_id": str(delivery_id),
                "decision": "APPLIED",
                "reason": str(reason),
            },
        )

    @staticmethod
    def _message_text(value: Any) -> str:
        """Flatten only model-visible text fields for exact exposure checks."""
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return "\n".join(GTBridge._message_text(item) for item in value)
        if isinstance(value, dict):
            parts = []
            for key in ("content", "text"):
                if key in value:
                    parts.append(GTBridge._message_text(value[key]))
            return "\n".join(parts)
        return ""

    def trace_model_request(
        self, iteration: int, messages: list[dict[str, Any]]
    ) -> tuple[str, ...]:
        """Prove which sealed delivery bytes were in the actual model request."""
        visible = self._message_text(messages)
        delivery_ids = tuple(
            delivery_id
            for delivery_id, text in self._delivery_texts.items()
            if text and text in visible
        )
        self._trace_record(
            "model.request",
            "model",
            {
                "iteration": int(iteration),
                "delivery_ids": list(delivery_ids),
                "message_count": len(messages),
                "visible_chars": len(visible),
            },
        )
        return delivery_ids

    @staticmethod
    def _text_leaves(
        value: Any, path: tuple[str, ...] = ()
    ) -> list[tuple[tuple[str, ...], str]]:
        """Return block-aware paths to all textual leaves in a payload."""
        leaves: list[tuple[tuple[str, ...], str]] = []
        if isinstance(value, str):
            leaves.append((path, value))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                leaves.extend(
                    GTBridge._text_leaves(item, path + (str(index),))
                )
        elif isinstance(value, dict):
            for key, item in value.items():
                leaves.extend(
                    GTBridge._text_leaves(item, path + (str(key),))
                )
        return leaves

    def trace_provider_request(
        self, iteration: int, provider: str, payload: dict[str, Any]
    ) -> tuple[str, ...]:
        """Bind sealed bytes to the final normalized provider request."""
        messages = payload.get("messages", ())
        leaves = self._text_leaves(messages)
        matches: list[dict[str, Any]] = []
        delivery_ids: list[str] = []
        for delivery_id, shipped in self._delivery_texts.items():
            locations = [
                ".".join(path)
                for path, text in leaves
                if shipped and shipped in text
            ]
            if not locations:
                continue
            delivery_ids.append(delivery_id)
            matches.append({
                "delivery_id": delivery_id,
                "locations": locations,
                "rendered_sha256": hashlib.sha256(
                    shipped.encode("utf-8", "surrogatepass")
                ).hexdigest(),
                "rendered_chars": len(shipped),
            })
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        )
        self._trace_record(
            "provider.request",
            "provider",
            {
                "iteration": int(iteration),
                "provider": str(provider),
                "model": str(payload.get("model") or ""),
                "temperature": payload.get("temperature"),
                "delivery_ids": delivery_ids,
                "matches": matches,
                "message_count": len(messages) if isinstance(messages, list) else 0,
                "payload_chars": len(canonical),
                "payload_sha256": hashlib.sha256(
                    canonical.encode("utf-8", "surrogatepass")
                ).hexdigest(),
            },
        )
        for delivery_id in delivery_ids:
            meta = self._delivery_metadata.get(delivery_id, {})
            if meta.get("evidence_type") in {
                "localization", "ranked_localization"
            } and os.environ.get("GT_LOC_RESLOT", "").strip().lower() not in {
                "", "0", "false", "no", "off"
            }:
                self._record_capability_applied(
                    "GT_LOC_RESLOT",
                    fact_id="localization",
                    boundary="provider",
                    delivery_id=delivery_id,
                    reason="provider_payload_reslot",
                )
        return tuple(delivery_ids)

    def trace_model_response(
        self, iteration: int, result: Any, delivery_ids: tuple[str, ...]
    ) -> None:
        """Link the next response/actions to exposure without claiming causality."""
        calls = list(getattr(result, "tool_calls", ()) or ())
        payload = {
            "iteration": int(iteration),
            "delivery_ids": list(delivery_ids),
            "stop_reason": str(getattr(result, "stop_reason", "") or ""),
            "tool_calls": [
                {
                    "id": str(getattr(call, "id", "") or ""),
                    "name": str(getattr(call, "name", "") or ""),
                }
                for call in calls
            ],
        }
        try:
            self._attribution.record_content(
                "model.response",
                content=str(getattr(result, "text", "") or ""),
                action_index=self.action_index,
                boundary="model",
                payload=payload,
            )
        except Exception:  # noqa: BLE001 - observability is always fail-open
            pass
        for delivery_id in delivery_ids:
            meta = self._delivery_metadata.get(delivery_id, {})
            try:
                from gt_engine.attribution import feature_for_evidence

                feature_id = feature_for_evidence(
                    meta.get("evidence_type")
                ) or ""
            except Exception:  # noqa: BLE001 - classification telemetry only
                feature_id = ""
            tool_names = [
                str(getattr(call, "name", "") or "") for call in calls
            ]
            target = self._fwd(meta.get("target", "")).lower()
            arguments = "\n".join(
                json.dumps(
                    getattr(call, "arguments", {}) or {},
                    sort_keys=True,
                    ensure_ascii=False,
                    default=str,
                )
                for call in calls
            ).lower()
            if not calls:
                classification = "no_tool_action"
            elif (
                target
                and target not in {"task_start", "submit", "recovery"}
                and (
                    target in arguments
                    or os.path.basename(target) in arguments
                )
            ):
                classification = "target_referenced"
            elif feature_id in {
                "syntax_result", "covering_red", "submit_refusal", "recovery"
            } and any(name in {"bash", "edit_file"} for name in tool_names):
                classification = "repair_or_verify_action"
            elif feature_id == "def_partition" and any(
                name in {"bash", "read_file"} for name in tool_names
            ):
                classification = "inspect_or_search_action"
            elif feature_id == "obligations":
                classification = "action_taken"
            else:
                classification = "other_action"
            self._trace_record(
                "response.action",
                "model",
                {
                    "iteration": int(iteration),
                    "delivery_id": str(delivery_id),
                    "feature_id": feature_id,
                    "classification": classification,
                    "tool_names": tool_names,
                },
            )

    def trace_run_completed(self, result: Any) -> None:
        """Record nano's terminal state; the benchmark reward joins offline."""
        self._trace_record(
            "run.completed",
            "run",
            {
                "stop_reason": str(getattr(result, "stop_reason", "") or ""),
                "iterations": int(getattr(result, "iterations", 0) or 0),
                "input_tokens": int(
                    getattr(result, "total_input_tokens", 0) or 0
                ),
                "output_tokens": int(
                    getattr(result, "total_output_tokens", 0) or 0
                ),
                "cache_read_tokens": int(
                    getattr(result, "total_cache_read_tokens", 0) or 0
                ),
                "delivery_count": len(self.deliveries),
            },
        )
        self._record_feature_census()

    def _deliveries_record(self, sealed: Any, shipped: str, boundary: str) -> None:
        """FIX A: gt_deliveries.txt — the VERBATIM shipped bytes, one framed
        block per sealed delivery, alongside gt_ledger.jsonl (same dir
        selection: /logs/agent preferred; <root>/.gt fallback is self-
        gitignored at creation and rm'd pre-snapshot on SWE). Motivation
        (TRAJECTORY_AUDIT.md): two deliveries were model-received but
        human-invisible — task-start rides the unprinted seed message and a
        suffix past nano's [:2000] display cap never prints. This file is the
        human-auditable byte record; it CONTAINS payload bytes, so it must
        never enter the graded tree (both homes guarantee that).

        Format per block:
            --- event_id=<id> boundary=<b> evidence_type=<t> rendered_bytes_hash=<h> ---
            <EXACT shipped text>
            <blank line>
        Written in binary so the body bytes hash exactly to
        rendered_bytes_hash (sha256 of the shipped utf-8 bytes, law 6).
        Correct-or-quiet: a write failure never unseals; GT-off -> no file
        (the bridge does not exist)."""
        try:
            path = self._ledger_path()
            if not path:
                return
            dpath = os.path.join(os.path.dirname(path), "gt_deliveries.txt")
            header = (
                f"--- event_id={getattr(sealed, 'event_id', '') or ''}"
                f" boundary={boundary}"
                f" evidence_type={getattr(sealed, 'evidence_type', '') or ''}"
                f" rendered_bytes_hash="
                f"{getattr(sealed, 'rendered_bytes_hash', '') or ''} ---")
            with open(dpath, "ab") as fh:
                fh.write(header.encode("utf-8") + b"\n"
                         + shipped.encode("utf-8", "surrogatepass") + b"\n\n")
                fh.flush()
        except Exception:  # noqa: BLE001 - never affects the sealed delivery
            pass

    # ------------------------------------------------------------------ #
    # WIRE 1: L6 freshness + wake-from-dormant (GT_L6_FRESH).
    #
    # FULL reindex, NEVER `gt-index -file` incremental. Decision evidence
    # (cmd/gt-index/main.go:966-1090, read in source): runIncremental is a
    # single-file delete-and-replace whose INCOMING edges are restored only
    # from a pre-delete snapshot — a NEW file's symbols gain their own nodes
    # and OUTGOING edges, but existing files' calls INTO the new symbols are
    # never minted (their edges did not exist to snapshot), and a multi-file
    # bash edit would need N invocations. The create-from-scratch case (the
    # TB-critical gap) therefore needs the full run; task repos are small and
    # ensure_index's own contract already says "gt-index is fast". One path,
    # correct for changed+new+multi-file alike.
    # ------------------------------------------------------------------ #
    def _refresh_graph(self, changed: tuple[str, ...]) -> None:
        """Refresh (or WAKE: graph_db None -> indexed) the graph after an edit
        observation that touched a source-ext file. Runs BEFORE the producers
        see this observation, so post-edit evidence reads the post-edit graph
        (the contract-DRIFT ordering _binary.run_incremental_index documents).
        Gated by GT_L6_FRESH == "1" (production's exact read, rl_profile:207;
        Profile-2 fans it to "1"). Correct-or-quiet: any fault keeps the prior
        graph (stale beats broken; producers still abstain on a bad db)."""
        try:
            if os.environ.get("GT_L6_FRESH", "").strip() != "1":
                return
            if not any(_has_source_ext(c) for c in changed):
                return  # bounded: only a source-file edit can move the graph
            from gt_engine.indexer import ensure_index

            db = ensure_index(self.repo_root)
            if db:
                self.graph_db = db  # wake-from-dormant is this same assignment
        except Exception:  # noqa: BLE001 - a reindex fault must never break the turn
            pass

    # ------------------------------------------------------------------ #
    # WIRE 2: executed covering-RED at post-edit (GT_VERIFY_EXECUTE).
    # Bridge-owned lane (the SM-3 home decision — module docstring). Budget
    # caps are production's own (gt_mini_patch.py:12046).
    # ------------------------------------------------------------------ #
    _COV_PER_FILE_TIMEOUT = 20
    _COV_TOTAL_BUDGET = 35

    def _post_edit_syntax(
        self, changed: tuple[str, ...],
    ) -> tuple[str, dict[str, Any]] | None:
        """Execute the deterministic edit checker at the post-edit boundary.

        A clean result is capability proof and stays model-quiet. The first
        positive syntax/name failure is returned for one-dose delivery before
        slower covering tests or advisory Gateway facts.
        """
        from groundtruth.runtime.edit_check import check_edit_syntax
        from groundtruth.runtime.native_render import render_syntax_error_native

        checked = False
        for rel in changed[: self._MAX_SUBMIT_SYNTAX_FILES]:
            if not rel or not _has_source_ext(rel):
                continue
            res = check_edit_syntax(rel, self.repo_root)
            verdict = str(res.get("verdict") or "")
            if verdict not in ("ok", "syntax_error", "name_error"):
                continue
            checked = True
            self._trace_record(
                "feature.evaluated",
                "post_edit",
                {
                    "feature_id": "GT_EDIT_CHECK",
                    "eligible": True,
                    "outcome": verdict,
                },
            )
            self._trace_record(
                "feature.evaluated",
                "post_edit",
                {
                    "feature_id": "syntax_result",
                    "eligible": verdict in ("syntax_error", "name_error"),
                    "outcome": (
                        "candidate_returned"
                        if verdict in ("syntax_error", "name_error")
                        else "ok"
                    ),
                },
            )
            if verdict == "ok":
                self._record_capability_applied(
                    "GT_EDIT_CHECK",
                    fact_id="syntax_result",
                    boundary="post_edit",
                    reason="executed_ok",
                )
                continue
            text = render_syntax_error_native(res)
            if text:
                return rel, {**res, "rendered": text}
        if not checked:
            self._trace_record(
                "feature.evaluated",
                "post_edit",
                {
                    "feature_id": "GT_EDIT_CHECK",
                    "eligible": False,
                    "outcome": "no_supported_source_target",
                },
            )
        return None

    def _deliver_post_edit_syntax(
        self,
        output: str,
        rel: str,
        result: dict[str, Any],
    ) -> str | None:
        """Seal one executed post-edit syntax diagnostic as a pure suffix.

        ``None`` means no dose shipped, so the caller must continue through
        the remaining post-edit lanes instead of muting them.
        """
        from groundtruth.runtime.adapters.miniswe import fits_budget, seal_delivery
        from groundtruth.runtime.evidence_envelope import (
            VERIFIED,
            EvidenceEnvelope,
        )
        from groundtruth.runtime.native_render import (
            contains_gt_tag,
            contains_test_identity,
        )

        text = str(result.get("rendered") or "")
        if (
            not text
            or contains_gt_tag(text)
            or contains_test_identity(text)
            or not fits_budget(text, max_delta_chars=MAX_DELTA_CHARS)
        ):
            self._trace_record(
                "decision.committed",
                "post_edit",
                {
                    "decision": "suppressed",
                    "reason": (
                        "render_empty" if not text
                        else (
                            "over_budget"
                            if text and not fits_budget(
                                text, max_delta_chars=MAX_DELTA_CHARS
                            )
                            else "leak_guard"
                        )
                    ),
                    "evidence_type": "syntax_result",
                    "feature_id": "syntax_result",
                },
            )
            return None
        env = EvidenceEnvelope.build(
            producer="edit_check",
            fact_id=rel,
            target=rel,
            evidence_type="syntax_result",
            payload=tuple(text.splitlines()),
            provenance=((rel, 0),),
            confidence=1.0,
            tier=VERIFIED,
            preferred_event="edit",
            measured=True,
        )
        shipped = self._join(output, text)[len(output):]
        tob = output.encode("utf-8", "surrogatepass")
        sealed, self.chain_head = seal_delivery(
            env,
            episode_id=getattr(self.episode, "episode_id", ""),
            event_id=str(self.action_index),
            parent_hash=self.chain_head,
            rendered_bytes=shipped.encode("utf-8", "surrogatepass"),
            renderer_id="native",
            tool_output_bytes=tob,
            boundary=(str(len(tob)) + ":syntax_result").encode("utf-8"),
            dedup_chain=self.episode.delivered_dedup,
        )
        self.deliveries.append(sealed)
        self.delivered_spans.append(DeliveredSpan(
            text=shipped,
            tier="VERIFIED",
            evidence_type="syntax_result",
            dedup_key=env.dedup_key or "",
        ))
        self._ledger_record(
            sealed,
            shipped,
            "post_edit",
            capability_ids=("GT_EDIT_CHECK",),
        )
        return output + shipped

    def _edited_symbol_identities(self, changed: tuple[str, ...]) -> set[str]:
        """Qualified ``path::name`` identities of the NON-test symbols defined
        in the changed files (graph read-only, bounded, deterministic order).
        Path-qualified so select_covering_tests resolves by exact identity —
        never the global bare-name match production measured at 12% cross-file
        collision (gt_mini_patch.py:7186). Empty on any fault."""
        if not self.graph_db or not os.path.isfile(self.graph_db):
            return set()
        from groundtruth.runtime.covering_runner import _connect_ro
        from groundtruth.runtime.reasoning_runtime import repository_symbol_identity

        con = _connect_ro(self.graph_db)
        if con is None:
            return set()
        try:
            rels = sorted({self._fwd(c) for c in changed if c})
            if not rels:
                return set()
            ph = ",".join("?" * len(rels))
            rows = con.execute(
                "SELECT file_path, name FROM nodes "
                f"WHERE REPLACE(file_path, '\\', '/') IN ({ph}) "
                "AND COALESCE(is_test, 0) = 0 "
                "ORDER BY file_path, name LIMIT 20", rels).fetchall()
            out: set[str] = set()
            for fp, name in rows:
                ident = repository_symbol_identity(str(fp or ""), str(name or ""))
                if ident:
                    out.add(ident)
            return out
        except Exception:  # noqa: BLE001 - correct-or-quiet
            return set()
        finally:
            try:
                con.close()
            except Exception:  # noqa: BLE001
                pass

    def _run_covering(self, changed: tuple[str, ...]) -> tuple[dict | None, list[str]]:
        """Select + EXECUTE the repo's own covering tests for the symbols the
        changed files define. Returns ``(result, files)``; caches the result
        for the submit gate's covering head. ``(None, [])`` when nothing is
        selectable (correct-or-quiet)."""
        from groundtruth.runtime.covering_runner import (
            run_covering_tests,
            select_covering_tests,
        )

        syms = self._edited_symbol_identities(changed)
        if not syms:
            return None, []
        sel = select_covering_tests(
            self.graph_db, syms, limit=2, repo_root=self.repo_root)
        files = [c["file"] for c in (sel or []) if c.get("file")]
        if not files:
            return None, []
        cres = run_covering_tests(
            self.repo_root, files,
            per_file_timeout=self._COV_PER_FILE_TIMEOUT,
            total_budget_seconds=self._COV_TOTAL_BUDGET)
        self._last_covering = cres
        return cres, files

    def _covering_lane(self, changed: tuple[str, ...]) -> str | None:
        """The post-edit covering-RED text (Format D, identity-scrubbed), or
        None. Delivers ONLY an ATTRIBUTED executed failure (frames first, then
        the green->base->red differential — is_red_attributable, the ONE
        question the seam asks). A pass/unavailable/unattributed run caches its
        verdict for the submit head and stays quiet."""
        if os.environ.get("GT_VERIFY_EXECUTE", "").strip() != "1":
            self._trace_record(
                "feature.evaluated", "covering",
                {"feature_id": "covering_red", "eligible": False,
                 "outcome": "feature_disabled"})
            return None
        if not self.graph_db:
            self._trace_record(
                "feature.evaluated", "covering",
                {"feature_id": "covering_red", "eligible": False,
                 "outcome": "graph_unavailable"})
            return None
        src = [c for c in changed if c and _has_source_ext(c)]
        if not src:
            self._trace_record(
                "feature.evaluated", "covering",
                {"feature_id": "covering_red", "eligible": False,
                 "outcome": "no_source_edit"})
            return None
        from groundtruth.runtime.covering_runner import is_red_attributable
        from groundtruth.runtime.native_render import (
            render_covering_failure_native,
        )

        cres, files = self._run_covering(changed)
        # Latch ONLY after a run that actually EXECUTED (verdict pass/fail).
        # A transient fault (spawn error, timeout, empty selection -> None/
        # unavailable) leaves the latch unset so the NEXT edit re-attempts —
        # burning it before the run permanently muted the file's edit-lane
        # covering for the episode on one transient fault. Cost bound: each
        # retry is capped by the runner's own budgets (20s/file, 35s total),
        # and a never-selectable file costs only the sqlite selection query
        # per edit turn — bounded, and strictly cheaper than a muted lane.
        if cres and cres.get("verdict") in ("pass", "fail"):
            self._covering_fired.update(src)
            covering_outcome = str(cres.get("verdict"))
            self._lifecycle_checkpoint(
                "test",
                f"covering_check_{covering_outcome}",
                after_latest_edit=True,
                selected_files=len(files),
            )
            if covering_outcome == "pass":
                self._last_green_verification_action = self.action_index
        if not cres or cres.get("verdict") != "fail":
            self._trace_record(
                "feature.evaluated", "covering",
                {"feature_id": "covering_red", "eligible": False,
                 "outcome": (
                     "covering_pass" if cres and cres.get("verdict") == "pass"
                     else "covering_unavailable"
                 )})
            return None
        ran = list(cres.get("ran") or files)
        if not is_red_attributable(
                cres, list(changed), test_files=ran,
                repo_root=self.repo_root, covering_files=files,
                per_file_timeout=self._COV_PER_FILE_TIMEOUT,
                total_budget_seconds=self._COV_TOTAL_BUDGET):
            self._trace_record(
                "feature.evaluated", "covering",
                {"feature_id": "covering_red", "eligible": False,
                 "outcome": "red_not_attributable"})
            return None  # a red the edit did not plausibly cause never ships
        # No edited_symbol claim: nano has no span-derived symbol proof, and an
        # unproven name in model-facing text is worse than the generic head
        # (production's _verified_edited_symbol_for_rendering rule).
        rendered = render_covering_failure_native(
            cres, test_files=ran, repo_root=self.repo_root) or None
        self._trace_record(
            "feature.evaluated", "covering",
            {"feature_id": "covering_red", "eligible": True,
             "outcome": "candidate_returned" if rendered else "render_empty"})
        return rendered

    def _deliver_covering(self, output: str, text: str, target: str) -> str:
        """Seal + append the covering-RED as THIS observation's one dose (the
        gateway dose is skipped by the caller — dose law). Same guard order as
        _deliver: leak guard, law 8, seal-before-append."""
        from groundtruth.runtime.adapters.miniswe import fits_budget, seal_delivery
        from groundtruth.runtime.evidence_envelope import (
            VERIFIED,
            EvidenceEnvelope,
        )
        from groundtruth.runtime.native_render import (
            contains_gt_tag,
            contains_test_identity,
        )

        native = os.environ.get("GT_GATEWAY_NATIVE") == "1"
        if not text:
            self._trace_record(
                "decision.committed", "covering",
                {"decision": "suppressed", "reason": "render_empty",
                 "evidence_type": "covering_verdict",
                 "feature_id": "covering_red"})
            return output
        if (native and contains_gt_tag(text)) or contains_test_identity(text):
            self._trace_record(
                "decision.committed", "covering",
                {"decision": "suppressed", "reason": "leak_guard",
                 "evidence_type": "covering_verdict",
                 "feature_id": "covering_red"})
            return output
        if not fits_budget(text, max_delta_chars=MAX_DELTA_CHARS):
            self._trace_record(
                "decision.committed", "covering",
                {"decision": "suppressed", "reason": "over_budget",
                 "evidence_type": "covering_verdict",
                 "feature_id": "covering_red",
                 "rendered_chars": len(text)})
            return output
        env = EvidenceEnvelope.build(
            producer="covering_runner", fact_id=target or "covering",
            target=target or "covering", evidence_type="covering_verdict",
            payload=tuple(text.splitlines()),
            provenance=((target, 0),) if target else (),
            confidence=0.9, tier=VERIFIED, preferred_event="edit",
            measured=True)  # an EXECUTED test verdict, never a heuristic
        shipped = self._join(output, text)[len(output):]
        tob = output.encode("utf-8", "surrogatepass")
        sealed, self.chain_head = seal_delivery(
            env,
            episode_id=getattr(self.episode, "episode_id", ""),
            event_id=str(self.action_index),
            parent_hash=self.chain_head,
            rendered_bytes=shipped.encode("utf-8", "surrogatepass"),
            renderer_id="native" if native else "tagged",
            tool_output_bytes=tob,
            boundary=(str(len(tob)) + ":covering_verdict").encode("utf-8"),
            dedup_chain=self.episode.delivered_dedup,
        )
        self.deliveries.append(sealed)
        self.delivered_spans.append(DeliveredSpan(
            text=shipped, tier="VERIFIED",
            evidence_type="covering_verdict", dedup_key=env.dedup_key or ""))
        self._ledger_record(sealed, shipped, "covering")
        return output + shipped

    # ------------------------------------------------------------------ #
    # FIX B: recovery / GT_HYPOTHESIS lane (the last unwired DIRECT feature).
    #
    # Port of the production MECHANISM (gt_mini_patch.py):
    #   * `_gt_hypothesis_classify_turn` (:12689) — run the HypothesisLedger's
    #     `classify_all` over the shared EpisodeState + a per-turn LedgerEvent;
    #     feed the failure fingerprint into the episode memory AFTER classify
    #     (a repeat is detected on the NEXT occurrence, never the same turn);
    #     first-mapped disposition wins (the production imperative-map order).
    #   * The recurrence rule is the ledger's own `classify_edit_contradicted_
    #     contract` (hypothesis_ledger.py:736): the SAME failure fingerprint
    #     recurred with a PROVABLE intervening source edit (prior index KNOWN
    #     from last_failure_record + an edit index strictly inside the window;
    #     unknown ordering NEVER fires — falsification demands proof, F1).
    #   * The W6 FIX 1b stall gate (:12732): a candidate is eligible only on a
    #     GENUINE failing state RIGHT NOW — here the observation itself must
    #     classify as a formal test FAIL (`classify_test_observation`), the
    #     bridge's honest equivalent of `_last_test_outcome_failed`; the
    #     repeat half is already strictly implied by the falsification rule.
    #   * Render: `render_recovery_native` (native_render.py:925) — ONE short
    #     active imperative at the decision point, identity-scrubbed; the
    #     imperative text is production's own D_HYPOTHESIS_FALSIFIED mapping
    #     (:12639).
    #   * HYPOTHESIS tier, never [VERIFIED] (the GT_HYPOTHESIS CAP contract,
    #     gt_gt.md: 'HYPOTHESIS-tier steer ... fires when the SAME genuine
    #     test failure recurs across edits'); once per signature per episode
    #     (latch burned on delivery only); ladder FLOOR (SM-10, :12769) — the
    #     candidate defers to the gateway dose and ships only when nothing
    #     higher delivered on this observation (dose law, <=1/observation).
    #
    # HONEST SUBSET (documented): production's imperative map covers five
    # dispositions (env-repair, falsified, new-hypothesis, alternate-surface,
    # stale-graph). Only D_HYPOTHESIS_FALSIFIED is DELIVERED here — it is the
    # class the GT_HYPOTHESIS CAP owns and the only one nano's observables
    # prove (an executed formal-test FAIL + the bridge's own edit record).
    # Selection still respects production's first-mapped-wins order: when a
    # higher-priority mapped disposition (e.g. env-failure -> repair) wins the
    # turn, this lane stays QUIET rather than misdelivering falsification.
    # Also NOT ported: the degenerate-loop stall union (GT_RECOVERY_LOOP needs
    # the seam's TIDE loop detector, which nano does not track) and the
    # GT_RECOVERY_ESCALATE form escalation (needs delivery-count history that
    # only matters once >1 recovery ships; we ship at most one per signature).
    # ------------------------------------------------------------------ #
    def _recovery_classify(
        self, cmd: str, output: str, rc: int | None,
    ) -> tuple[str, str] | None:
        """Classify THIS observation; return ``(rendered_text, signature)``
        when the recovery steer should fire, else None. ALWAYS feeds the
        episode failure memory when the flag is on (classification state is
        not conditional on delivery). Flag off -> no state touched."""
        if os.environ.get("GT_HYPOTHESIS", "").strip() != "1":
            return None
        from groundtruth.runtime.hypothesis_ledger import (
            D_ALTERNATE_SURFACE_CANDIDATE,
            D_HYPOTHESIS_FALSIFIED,
            D_REFRESH_BEFORE_ADVICE,
            D_REPAIR_NOT_SOURCE,
            D_REQUEST_NEW_HYPOTHESIS,
            LedgerEvent,
            classify_all,
        )

        fp = failure_fingerprint(output)
        event = LedgerEvent(
            action_index=self.action_index, command=cmd or "",
            observation=output or "", probe_stem="",
            failure_fingerprint=fp, graph_revision="")
        advisories = classify_all(self.episode, event)  # sees PRIOR memory
        if fp:  # feed AFTER classify: this failure is prior-memory next turn
            self.episode.failure_fingerprints.add(fp)
            self.episode.last_failure_record = {
                "failure_fingerprint": fp, "action_index": self.action_index}
        # Production's selection: TRANSITIONS order is the fixed priority and
        # the FIRST disposition present in the imperative map wins (:12717).
        mapped = (D_REPAIR_NOT_SOURCE, D_HYPOTHESIS_FALSIFIED,
                  D_REQUEST_NEW_HYPOTHESIS, D_ALTERNATE_SURFACE_CANDIDATE,
                  D_REFRESH_BEFORE_ADVICE)
        selection = next(
            (a.disposition for a in advisories if a.disposition in mapped), None)
        if selection != D_HYPOTHESIS_FALSIFIED:
            return None  # honest subset: only the CAP's recurs-across-edits class
        if fp in self._recovery_fired_sigs:
            return None  # once per signature per episode
        from groundtruth.runtime.patterns import classify_test_observation

        if classify_test_observation(cmd or "", output or "", rc)[0] != "fail":
            return None  # stall gate: a GENUINE failing TEST right now (W6 1b)
        from groundtruth.runtime.native_render import render_recovery_native

        # Production's D_HYPOTHESIS_FALSIFIED imperative, verbatim (:12639).
        imperative = ("The last edit did not change the failing result — form "
                      "a new hypothesis before editing again.")
        text = render_recovery_native(D_HYPOTHESIS_FALSIFIED, imperative)
        return (text, fp) if text else None

    def _deliver_recovery(self, output: str, text: str, signature: str) -> str:
        """Seal + append the HYPOTHESIS-tier recovery steer as THIS
        observation's one dose (caller guarantees the gateway dose was quiet —
        ladder-floor semantics). Same guard order as every delivery lane."""
        from groundtruth.runtime.adapters.miniswe import fits_budget, seal_delivery
        from groundtruth.runtime.evidence_envelope import (
            HYPOTHESIS,
            EvidenceEnvelope,
        )
        from groundtruth.runtime.native_render import (
            contains_gt_tag,
            contains_test_identity,
        )

        native = os.environ.get("GT_GATEWAY_NATIVE") == "1"
        if not text:
            self._trace_record(
                "decision.committed", "recovery",
                {"decision": "suppressed", "reason": "render_empty",
                 "evidence_type": "recovery", "feature_id": "recovery"})
            return output
        if (native and contains_gt_tag(text)) or contains_test_identity(text):
            self._trace_record(
                "decision.committed", "recovery",
                {"decision": "suppressed", "reason": "leak_guard",
                 "evidence_type": "recovery", "feature_id": "recovery"})
            return output
        if not fits_budget(text, max_delta_chars=MAX_DELTA_CHARS):
            self._trace_record(
                "decision.committed", "recovery",
                {"decision": "suppressed", "reason": "over_budget",
                 "evidence_type": "recovery", "feature_id": "recovery",
                 "rendered_chars": len(text)})
            return output
        env = EvidenceEnvelope.build(
            producer="hypothesis_ledger", fact_id=signature or "recovery",
            target="recovery", evidence_type="recovery",
            payload=tuple(text.splitlines()),
            confidence=0.5, tier=HYPOTHESIS,  # never [VERIFIED] (CAP contract)
            preferred_event="test")
        shipped = self._join(output, text)[len(output):]
        tob = output.encode("utf-8", "surrogatepass")
        sealed, self.chain_head = seal_delivery(
            env,
            episode_id=getattr(self.episode, "episode_id", ""),
            event_id=str(self.action_index),
            parent_hash=self.chain_head,
            rendered_bytes=shipped.encode("utf-8", "surrogatepass"),
            renderer_id="native" if native else "tagged",
            tool_output_bytes=tob,
            boundary=(str(len(tob)) + ":recovery").encode("utf-8"),
            dedup_chain=self.episode.delivered_dedup,
        )
        self.deliveries.append(sealed)
        self.delivered_spans.append(DeliveredSpan(
            text=shipped, tier="HYPOTHESIS",
            evidence_type="recovery", dedup_key=env.dedup_key or ""))
        self._ledger_record(
            sealed,
            shipped,
            "recovery",
            capability_ids=("GT_HYPOTHESIS",),
        )
        self._recovery_fired_sigs.add(signature)  # burned on DELIVERY only
        return output + shipped

    # ------------------------------------------------------------------ #
    # FIX D: SS-2 observed-RED tracking (the submit gate's broad fallback).
    # Port of production's latch rule (`_ss_record_test` tail,
    # gt_mini_patch.py:20651 + `_ss_test_touches_edit`, :20546): the LAST
    # formal test event TOUCHING an edited surface decides — a FAIL sets the
    # latch (agent's own command + step), a PASS clears it, a test touching
    # no edit (or any non-test event) leaves it unchanged. "No edits yet"
    # is False by construction: a pre-existing failure on an unedited tree
    # is never the agent's unresolved RED (correct-or-quiet). Populated
    # unconditionally (host state, zero model bytes); CONSUMED only under
    # GT_SS_SUBMIT_RED (Profile-2 member, rl_profile.py:260).
    # ------------------------------------------------------------------ #
    def _test_touches_edit(self, cmd: str, output: str) -> bool:
        """True iff an edited rel path (or its basename, len>=4) appears in
        the agent's OWN command or observed output — production's leak-safe
        relatedness signal (it reads only the agent's own strings)."""
        rels = self.edited_files
        if not rels:
            return False
        hay = (cmd or "") + "\n" + (output or "")
        if not hay.strip():
            return False
        for rel in rels:
            r = self._fwd(rel)
            if r and r in hay:
                return True
        return False

    def _track_observed_red(
        self, cmd: str, output: str, rc: int | None,
    ) -> str | None:
        """Set/clear the observed-RED latch from THIS observation. Uses the
        same formal-runner classifier normalize_event derives test_outcome
        from (patterns.classify_test_observation — never a home-grown test
        detector). Returns pass/fail for a recognized executed behavioral
        check and records the test-stage checkpoint; otherwise None."""
        try:
            from groundtruth.runtime.patterns import classify_test_observation

            outcome, _ = classify_test_observation(cmd or "", output or "", rc)
            # Generated artifacts often have no test runner. An inline
            # assertion is still an explicit self-check with an unambiguous
            # fail/pass result, so keep it in the same unresolved-RED latch.
            if (
                outcome not in ("fail", "pass")
                and re.search(r"\bassert\b", cmd or "")
            ):
                if (
                    rc not in (None, 0)
                    and "assertionerror" in (output or "").lower()
                ):
                    outcome = "fail"
                elif rc == 0:
                    outcome = "pass"
            # A deterministic self-check can report its boolean verdict while
            # incorrectly exiting zero. Honor only explicit verdict sentinels
            # from an executed checker; passive cat/grep views must never
            # create or clear the unresolved-RED latch.
            if (
                outcome not in ("fail", "pass")
                and _CHECK_EXEC_RE.search(cmd or "")
            ):
                outcome = _explicit_check_outcome(output or "") or outcome
            if outcome not in ("fail", "pass"):
                return None  # env_fail / no-tests / non-test: latch unchanged
            self._last_test_outcome = outcome
            self._lifecycle_checkpoint(
                "test",
                f"behavioral_check_{outcome}",
                command_present=bool((cmd or "").strip()),
                after_latest_edit=bool(
                    self._last_source_edit_action
                    and self.action_index > self._last_source_edit_action
                ),
            )
            # Passing runners normally print only aggregate success, not the
            # edited source path. A formal green after the latest edit is
            # therefore valid SDLC verification even without a path echo.
            if (
                outcome == "pass"
                and self._last_source_edit_action
                and self.action_index > self._last_source_edit_action
            ):
                self._last_green_verification_action = self.action_index
            if not self._test_touches_edit(cmd, output):
                return outcome  # checkpoint is valid; RED attribution is not
            self._observed_red = (
                {"cmd": (cmd or "").strip(), "step": self.action_index}
                if outcome == "fail" else None)
            return outcome
        except Exception:  # noqa: BLE001 - host-side latch must never break the turn
            return None

    # ------------------------------------------------------------------ #
    # bash-mediated edit bridges (pre-dispatch snapshot + post-dispatch derive)
    # ------------------------------------------------------------------ #
    def _confined_abs(self, rel: str) -> str | None:
        """Absolute path for a repo-relative target, confined INSIDE the repo
        (production `_ss_confined_repo_source_abs` intent). None = outside."""
        try:
            root = os.path.realpath(self.repo_root)
            fp = os.path.realpath(os.path.join(root, rel))
            if os.path.commonpath([root, fp]) != root:
                return None
            return fp
        except Exception:  # noqa: BLE001
            return None

    def capture_bash_preimage(self, tool_args: dict[str, Any]) -> None:
        """PRE-dispatch boundary: snapshot the file a bash edit is about to
        write (production `_gateway_capture_edit_preimage`). A redirect/sed
        cannot be reverse-applied after execution, so the before-image must be
        read HERE. Never raises; clears prior state either way."""
        self._bash_preimages.clear()
        try:
            cmd = str(tool_args.get("command") or "")
            from groundtruth.runtime.gateway import KIND_EDIT, classify_command

            if classify_command(cmd) != KIND_EDIT:
                return
            targets = bash_edit_targets(cmd)
            if not _edit_bridges_on():
                self._lifecycle_checkpoint(
                    "pre_edit",
                    "bash_edit_proposed",
                    tool_name="bash",
                    targets=list(targets),
                    target_count=len(targets),
                    before_available=False,
                    proposed_action_index=self.action_index + 1,
                )
                return
            if not targets:
                self._lifecycle_checkpoint(
                    "pre_edit",
                    "bash_edit_proposed_targets_unknown",
                    tool_name="bash",
                    targets=[],
                    target_count=0,
                    before_available=False,
                    proposed_action_index=self.action_index + 1,
                )
                return
            for target in targets:
                rel = self._repo_rel(target)
                if not rel:
                    continue
                fp = self._confined_abs(rel)
                if fp is None:
                    continue
                if not os.path.exists(fp):
                    self._bash_preimages[rel] = None  # positive creation evidence
                    continue
                if (
                    not os.path.isfile(fp)
                    or os.path.getsize(fp) > _MAX_BRIDGE_FILE_BYTES
                ):
                    continue  # no entry: downstream stays quiet
                with open(fp, encoding="utf-8", errors="replace") as fh:
                    self._bash_preimages[rel] = fh.read()
            self._lifecycle_checkpoint(
                "pre_edit",
                "bash_edit_proposed",
                tool_name="bash",
                targets=sorted(self._bash_preimages),
                target_count=len(targets),
                before_available=any(
                    before is not None for before in self._bash_preimages.values()
                ),
                proposed_action_index=self.action_index + 1,
            )
        except Exception:  # noqa: BLE001 - pre-image capture must never break dispatch
            self._bash_preimages.clear()

    def _bash_bridges(self, cmd: str) -> tuple[tuple[str, ...], dict | None]:
        """POST-dispatch: (changed_files, edit_before_after) for a bash edit
        (production `_gateway_edit_bridges`). AFTER = current on-disk content;
        BEFORE only from the captured pre-image - a wrong before/after
        fabrication is worse than absence."""
        if not _edit_bridges_on():
            return (), None
        targets = bash_edit_targets(cmd)
        if not targets:
            return (), None
        changed: list[str] = []
        before_after: dict[str, tuple[str | None, str]] = {}
        for target in targets:
            rel = self._repo_rel(target)
            if not rel:
                continue
            changed.append(rel)
            after: str | None = None
            try:
                fp = self._confined_abs(rel)
                if (
                    fp
                    and os.path.isfile(fp)
                    and os.path.getsize(fp) <= _MAX_BRIDGE_FILE_BYTES
                ):
                    with open(fp, encoding="utf-8", errors="replace") as fh:
                        after = fh.read()
            except Exception:  # noqa: BLE001
                after = None
            if after is not None and rel in self._bash_preimages:
                before_after[rel] = (self._bash_preimages[rel], after)
        return tuple(changed), before_after or None

    # ------------------------------------------------------------------ #
    # nano tool call -> gateway event ingredients
    # ------------------------------------------------------------------ #
    def _event_parts(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        output: str,
        is_error: bool,
        edit_before: str | None,
        edit_after: str | None,
    ) -> tuple[str, int | None, tuple[str, ...], tuple[str, ...], dict | None]:
        """(command, returncode, changed_files, viewed_files, edit_before_after)."""
        if tool_name == "bash":
            cmd = str(tool_args.get("command") or "")
            # Bash-mediated edit bridges (see module section above): production
            # derives them for every edit-classified bash command, success or
            # not - the on-disk after-content tells the truth either way.
            changed, eba = self._bash_bridges(cmd)
            self._bash_preimages.clear()  # consumed by THIS observation
            return (cmd, parse_exit_code(output, is_error), changed, (), eba)
        if tool_name == "read_file":
            rel = self._repo_rel(str(tool_args.get("path") or ""))
            viewed = (rel,) if (rel and not is_error) else ()
            # `cat` is the view carrier classify_command already understands.
            return (f"cat {rel}", None if is_error else 0, (), viewed, None)
        if tool_name == "edit_file":
            rel = self._repo_rel(str(tool_args.get("path") or ""))
            changed: tuple[str, ...] = ()
            eba: dict | None = None
            if rel and not is_error:
                changed = (rel,)
                if edit_after is not None:
                    # {path: (before_or_None, after)} - before None = new file.
                    eba = {rel: (edit_before, edit_after)}
            # `apply_patch` matches gateway._EDIT_KIND_RE -> KIND_EDIT carrier.
            return (f"apply_patch {rel}", None if is_error else 0, changed, (), eba)
        return ("", None if is_error else 0, (), (), None)

    # ------------------------------------------------------------------ #
    # THE seam: one observation in, (possibly) one evidence suffix out
    # ------------------------------------------------------------------ #
    def enrich(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        output: str,
        is_error: bool,
        *,
        edit_before: str | None = None,
        edit_after: str | None = None,
        tool_call_id: str = "",
    ) -> str:
        """Complete this observation with at most one gateway dose.

        Returns ``output`` + evidence suffix, or ``output`` unchanged (GT off,
        nothing produced, guard drop, or ANY internal fault)."""
        self.action_index += 1
        try:
            cmd, rc, changed, viewed, eba = self._event_parts(
                tool_name, tool_args, output, is_error, edit_before, edit_after)
            import hashlib

            self._trace_record(
                "observation.received",
                "gateway",
                {
                    "tool_call_id": str(tool_call_id),
                    "tool_name": str(tool_name),
                    "command_sha256": hashlib.sha256(
                        cmd.encode("utf-8", "surrogatepass")
                    ).hexdigest(),
                    "returncode": rc,
                    "is_error": bool(is_error),
                    "changed_files": list(changed),
                    "viewed_files": list(viewed),
                    "output_chars": len(output),
                    "output_sha256": hashlib.sha256(
                        output.encode("utf-8", "surrogatepass")
                    ).hexdigest(),
                },
            )
            repository_observation = tool_name == "read_file"
            if tool_name == "bash" and not changed and (cmd or "").strip():
                try:
                    from groundtruth.runtime.gateway import (
                        KIND_SEARCH,
                        KIND_VIEW,
                        classify_command,
                    )

                    repository_observation = classify_command(cmd) in {
                        KIND_SEARCH,
                        KIND_VIEW,
                    }
                except Exception:  # noqa: BLE001 - telemetry stays conservative
                    repository_observation = False
            if repository_observation:
                self._lifecycle_checkpoint(
                    "research",
                    "repository_observation",
                    tool_name=str(tool_name),
                    viewed_count=len(viewed),
                )
            for rel in changed:
                if rel and rel not in self.edited_files:
                    self.edited_files.append(rel)  # submit-gate syntax domain
            if changed:
                source_edit = any(_has_source_ext(rel) for rel in changed)
                if source_edit:
                    self._last_source_edit_action = self.action_index
                self._lifecycle_checkpoint(
                    "post_edit",
                    "edit_observed",
                    changed_count=len(changed),
                    before_after_available=bool(eba),
                    source_edit=source_edit,
                )
            # FIX B (recovery lane state): the ledger's edit-ordering predicate
            # reads EpisodeState.edited_files (path -> last action_index) +
            # edit_events. augment appends edit_events only when the gateway
            # dose path runs, so the bridge mirrors the seam's own feed
            # (`_oracle_edited_rels -> edited_files`, episode_state.py:153)
            # here — covering-lane-delivered edits stay ordered too. Flag-
            # gated so GT_HYPOTHESIS off leaves the episode state untouched.
            if changed and os.environ.get("GT_HYPOTHESIS", "").strip() == "1":
                for rel in changed:
                    if rel:
                        self.episode.edited_files[rel] = self.action_index
            # FIX B (classification): runs on EVERY observation (the
            # production seam classifies each turn) — feeds the failure-repeat
            # memory and names this turn's recovery candidate, if any.
            try:
                recovery = self._recovery_classify(cmd, output, rc)
                self._trace_record(
                    "feature.evaluated",
                    "recovery",
                    {
                        "feature_id": "recovery",
                        "eligible": bool(recovery),
                        "outcome": (
                            "candidate_returned" if recovery
                            else "trigger_not_satisfied"
                        ),
                    },
                )
                self._trace_record(
                    "feature.evaluated",
                    "recovery",
                    {
                        "feature_id": "GT_HYPOTHESIS",
                        "eligible": bool(recovery),
                        "outcome": (
                            "candidate_returned" if recovery
                            else "trigger_not_satisfied"
                        ),
                    },
                )
            except Exception as exc:  # noqa: BLE001 - classification fault: no candidate
                recovery = None
                self._trace_record(
                    "feature.evaluated",
                    "recovery",
                    {
                        "feature_id": "recovery",
                        "eligible": True,
                        "outcome": "producer_fault",
                        "fault_type": type(exc).__name__,
                    },
                )
                self._trace_record(
                    "feature.evaluated",
                    "recovery",
                    {
                        "feature_id": "GT_HYPOTHESIS",
                        "eligible": True,
                        "outcome": "producer_fault",
                        "fault_type": type(exc).__name__,
                    },
                )
            # FIX D: SS-2 observed-RED latch — real executions only (the
            # read_file `cat` carrier is a VIEW; a viewed log containing a
            # runner frame must never latch a phantom RED).
            if tool_name == "bash":
                self._track_observed_red(cmd, output, rc)
            if changed:
                # WIRE 1: refresh/wake the graph BEFORE the producers read it,
                # so this observation's evidence reflects the post-edit code.
                self._refresh_graph(changed)
                try:
                    syntax_failure = self._post_edit_syntax(changed)
                except Exception:  # noqa: BLE001 - new lane cannot mute old lanes
                    syntax_failure = None
                if syntax_failure is not None:
                    rel, syntax_result = syntax_failure
                    try:
                        syntax_delivery = self._deliver_post_edit_syntax(
                            output, rel, syntax_result
                        )
                    except Exception:  # noqa: BLE001 - sealing fault stays quiet
                        syntax_delivery = None
                    if syntax_delivery is not None:
                        return syntax_delivery
                # WIRE 2: the executed covering-RED lane. When it delivers, it
                # IS this observation's one dose — the gateway is skipped
                # (dose law; covering_verdict out-ranks every gateway class at
                # severity 60 anyway, so no evidence is wrongly displaced).
                try:
                    cov_text = self._covering_lane(changed)
                except Exception:  # noqa: BLE001 - covering fault: fall through
                    cov_text = None
                if cov_text:
                    # Recovery defers (ladder floor); its latch is NOT burned.
                    return self._deliver_covering(output, cov_text, changed[0])
            enriched = self._deliver(cmd, output, rc,
                                     changed_files=changed, viewed_files=viewed,
                                     edit_before_after=eba)
            if enriched != output or not recovery:
                # Gateway dose spent (recovery is the severity FLOOR — SM-10:
                # it defers to every higher producer) or no candidate: done.
                return enriched
            return self._deliver_recovery(output, recovery[0], recovery[1])
        except Exception as exc:  # noqa: BLE001 - GT failure must never break the harness
            self._trace_record(
                "decision.committed",
                "gateway",
                {
                    "decision": "telemetry_fault",
                    "reason": "bridge_exception",
                    "fault_type": type(exc).__name__,
                },
            )
            return output

    def submit_probe(self) -> str | None:
        """Advisory submit-boundary check (gt_engine.verify uses this).

        The Gate Kernel path: ``gateway.augment`` has NO submit-boundary
        producer (verified: producers dispatch on view/edit/test/search
        semantics only), so the probe consumes GT's pure submit decision head
        directly - ``submit_gate.safe_gate_verdict`` - fed with the nearest
        honest evidence nano possesses: an EXECUTED syntax check
        (``edit_check.check_edit_syntax``, correct-or-quiet by construction)
        over the files this episode actually edited. No covering-test result
        and no hygiene predicate exist in nano, so those heads are None
        (pass-with-record - never a false block). A BLOCK renders as the
        native pre-commit refusal (``render_submit_rejection``), leak-guarded,
        budget-checked, and SEALED as a delivery. Never raises; never blocks
        completion (the agent spends one EXISTING pushback on it, advisory)."""
        self.action_index += 1
        try:
            self._trace_record(
                "observation.received",
                "submit",
                {"edited_files": list(self.edited_files)},
            )
            self._lifecycle_checkpoint(
                "submit",
                "submission_attempted",
                edited_count=len(self.edited_files),
            )
            result = self._submit_gate()
            if result is None:
                self._trace_record(
                    "decision.committed",
                    "submit",
                    {"decision": "no_delivery", "reason": "gate_allowed_or_unavailable"},
                )
            return result
        except Exception as exc:  # noqa: BLE001 - advisory: any fault abstains
            self._trace_record(
                "decision.committed",
                "submit",
                {
                    "decision": "telemetry_fault",
                    "reason": "submit_probe_exception",
                    "fault_type": type(exc).__name__,
                },
            )
            return None
        finally:
            self._record_feature_census()

    # Syntax-check at most this many edited files at the submit boundary.
    _MAX_SUBMIT_SYNTAX_FILES = 10

    def _submit_covering(self) -> dict | None:
        """The submit gate's covering HEAD (G-2 staleness law, the mini seam's
        `_gt_submit_covering` mechanism, gt_mini_patch.py:22146): a cached
        NON-fail can never false-block -> reuse without re-run; a cached FAIL
        (or no cache) is STALE at the submit decision point -> re-select +
        re-RUN fresh over the episode's edited files. A fresh FAIL feeds the
        head ONLY when the edit is PROVEN to have caused it
        (is_red_attributable — unproven never blocks, invariant FP=0).
        Correct-or-quiet: gate off / no graph / no selection / fault -> None."""
        if os.environ.get("GT_VERIFY_EXECUTE", "").strip() != "1":
            return None
        if not self.graph_db:
            return None
        try:
            if (self._last_covering is not None
                    and self._last_covering.get("verdict") != "fail"):
                return self._last_covering
            changed = tuple(self.edited_files[: self._MAX_SUBMIT_SYNTAX_FILES])
            cres, files = self._run_covering(changed)
            if not cres:
                return None
            if cres.get("verdict") == "fail":
                from groundtruth.runtime.covering_runner import is_red_attributable

                if not is_red_attributable(
                        cres, list(changed),
                        test_files=list(cres.get("ran") or files),
                        repo_root=self.repo_root, covering_files=files,
                        per_file_timeout=self._COV_PER_FILE_TIMEOUT,
                        total_budget_seconds=self._COV_TOTAL_BUDGET):
                    return None  # unattributed RED must not block the submit
            return cres
        except Exception:  # noqa: BLE001 - covering head unavailable: never block
            return None

    def _submit_gate(self) -> str | None:
        from groundtruth.runtime.adapters.miniswe import fits_budget, seal_delivery
        from groundtruth.runtime.edit_check import check_edit_syntax
        from groundtruth.runtime.evidence_envelope import (
            VERIFIED,
            EvidenceEnvelope,
        )
        from groundtruth.runtime.native_render import (
            contains_gt_tag,
            contains_test_identity,
            render_submit_rejection,
        )
        from groundtruth.runtime.submit_gate import safe_gate_verdict

        from gt_engine.attribution import feature_for_evidence

        # POSITIVE evidence only: an executed parse failure in an edited file.
        # ``syntax_res`` additionally feeds the certificate's syntax head (a
        # descriptive FieldCert — the head still decides through submit_block).
        submit_block: dict[str, Any] | None = None
        syntax_res: dict[str, Any] | None = None
        bad_rel = ""
        for rel in self.edited_files[: self._MAX_SUBMIT_SYNTAX_FILES]:
            res = check_edit_syntax(rel, self.repo_root)
            if res.get("verdict") == "syntax_error":
                bad_rel = rel
                syntax_res = res
                submit_block = {
                    "blocking": True,
                    "reason": "syntax_error",
                    "detail": str(res.get("diagnostic") or "")
                    or f"syntax error in {rel}",
                }
                break
            if syntax_res is None and res.get("verdict") == "ok":
                syntax_res = res  # an executed PASS is honest cert evidence
        syntax_outcome = (
            str(syntax_res.get("verdict") or "")
            if isinstance(syntax_res, dict)
            else "no_edited_syntax_target"
        )
        self._trace_record(
            "feature.evaluated",
            "submit",
            {
                "feature_id": "GT_EDIT_CHECK",
                "eligible": syntax_res is not None,
                "outcome": syntax_outcome,
            },
        )
        if syntax_res is not None:
            self._record_capability_applied(
                "GT_EDIT_CHECK",
                fact_id="syntax_result",
                boundary="submit",
                reason=f"executed_{syntax_outcome}",
            )
        self._trace_record(
            "feature.evaluated",
            "submit",
            {
                "feature_id": "syntax_result",
                "eligible": bool(submit_block and bad_rel),
                "outcome": (
                    "candidate_returned" if submit_block and bad_rel
                    else syntax_outcome
                ),
            },
        )
        # FIX D (SS-2 broad fallback, GT_SS_SUBMIT_RED): the agent's OWN
        # unresolved observed RED — fires exactly where graph coverage is
        # dark (production's conan-17092 class: the agent watched a test on
        # an edited surface FAIL, rationalized it away, and submitted). Feeds
        # the SAME decision head (gate_verdict documents submit_block as "an
        # unresolved test RED the agent itself observed"). Correct-or-quiet:
        # if the agent NEVER observed a failing test (hidden verifier tests
        # are invisible by design), the latch is None and this never fires —
        # GT only knows what the agent observed. Single-dose rides the
        # existing bounce economy (max_bounces=1: the second submit passes).
        # Leak guard on the detail: the echoed command is the agent's OWN
        # (agent-visible by definition), but the seam law still applies —
        # if the quoted line trips contains_test_identity it degrades to the
        # generic form (production's render_ss_submit_red scrub-or-silent
        # rule, native_render.py:486-500; here degrade beats silent because
        # the block itself is still honest positive evidence).
        if (submit_block is None and self._observed_red is not None
                and self.edited_files
                and os.environ.get("GT_SS_SUBMIT_RED", "").strip().lower()
                not in ("", "0", "false", "no", "off")):
            cmd_line = str(self._observed_red.get("cmd") or "").splitlines()[0][:200]
            detail = "your last test run failed and was never re-run green"
            if cmd_line:
                quoted = (f"your last test run (`{cmd_line}`) failed and was "
                          "never re-run green")
                if not contains_test_identity(quoted):
                    detail = quoted
            submit_block = {
                "blocking": True,
                "reason": "observed_red_unresolved",
                "detail": detail,
            }
        observed_red_eligible = bool(
            self._observed_red is not None
            and self.edited_files
            and os.environ.get("GT_SS_SUBMIT_RED", "").strip().lower()
            not in ("", "0", "false", "no", "off")
        )
        self._trace_record(
            "feature.evaluated",
            "submit",
            {
                "feature_id": "GT_SS_SUBMIT_RED",
                "eligible": observed_red_eligible,
                "outcome": (
                    "candidate_returned"
                    if submit_block
                    and submit_block.get("reason") == "observed_red_unresolved"
                    else "trigger_not_satisfied"
                ),
            },
        )
        # WIRE 2 (submit head): the executed covering verdict — fresh by the
        # G-2 staleness law, attribution-gated. None never blocks.
        covering = self._submit_covering()
        self._trace_record(
            "feature.evaluated",
            "submit",
            {
                "feature_id": "covering_red",
                "eligible": bool(
                    covering and covering.get("verdict") == "fail"
                ),
                "outcome": (
                    f"covering_{covering.get('verdict')}"
                    if covering else "covering_unavailable"
                ),
            },
        )
        if covering and covering.get("verdict") == "pass":
            self._last_green_verification_action = self.action_index

        # SDLC penultimate gate: syntax success proves parseability, not
        # behavior. When enabled, a source edit must be followed by a passing
        # formal test, explicit self-check, or selected covering run. This is
        # one advisory refusal using the existing bounce economy; the second
        # submit still fails open, so GT cannot deadlock completion.
        sdlc_verify_on = os.environ.get(
            "GT_SDLC_VERIFY", ""
        ).strip().lower() not in ("", "0", "false", "no", "off")
        verification_current = bool(
            self._last_source_edit_action
            and self._last_green_verification_action
            > self._last_source_edit_action
        )
        if (
            sdlc_verify_on
            and submit_block is None
            and self._last_source_edit_action
            and not verification_current
        ):
            submit_block = {
                "blocking": True,
                "reason": "verification_missing",
                "detail": (
                    "no passing post-edit behavioral check was observed; run "
                    "the relevant tests or an explicit executable self-check"
                ),
            }
        verify_outcome = (
            "not_applicable_no_source_edit"
            if not self._last_source_edit_action
            else (
                "post_edit_verification_green"
                if verification_current
                else (
                    "missing_post_edit_verification"
                    if sdlc_verify_on
                    else "checkpoint_disabled"
                )
            )
        )
        self._lifecycle_checkpoint(
            "verify",
            verify_outcome,
            latest_source_edit_action=self._last_source_edit_action,
            latest_green_action=self._last_green_verification_action,
            syntax_outcome=syntax_outcome,
            covering_outcome=(
                str(covering.get("verdict"))
                if isinstance(covering, dict) else "unavailable"
            ),
        )
        verdict = safe_gate_verdict(
            covering=covering, hygiene=None, submit_block=submit_block,
            bounce_count=self.submit_bounces, max_bounces=1)
        # WIRE 3: the CompletionCertificate (GT_CERT_DELIVERY, production's own
        # flag read — gt_mini_patch.py:22329). Built from what nano HONESTLY
        # has: the frozen head itself, the executed syntax + covering results.
        # Heads nano cannot compute stay absent -> UNKNOWN/NOT_APPLICABLE
        # (visible, fail-open). obligations=None exactly as production passes
        # it: ADVISORY-only, never a block input (T2 law). ``cert.decision`` is
        # a pure function of the head, so the cert can NEVER turn an allow into
        # a block (allow-never-block) — we return None on allow regardless.
        cert = None
        if os.environ.get("GT_CERT_DELIVERY") == "1":
            try:
                from groundtruth.runtime.submit_gate import safe_build_certificate

                cert = safe_build_certificate(
                    head=verdict, covering=covering, hygiene=None,
                    submit_block=submit_block,
                    bounce_count=self.submit_bounces, max_bounces=1,
                    syntax=syntax_res, obligations=None)
            except Exception:  # noqa: BLE001 - a cert fault degrades to the head
                cert = None
        self._trace_record(
            "feature.evaluated",
            "submit",
            {
                "feature_id": "GT_CERT_DELIVERY",
                "eligible": bool(
                    os.environ.get("GT_CERT_DELIVERY") == "1" and not verdict.allow
                ),
                "outcome": (
                    "candidate_returned" if cert is not None
                    else (
                        "gate_allowed" if verdict.allow
                        else "certificate_unavailable"
                    )
                ),
            },
        )
        self._trace_record(
            "feature.evaluated",
            "submit",
            {
                "feature_id": "submit_refusal",
                "eligible": not verdict.allow,
                "outcome": (
                    "candidate_returned" if not verdict.allow else "gate_allowed"
                ),
            },
        )
        if verdict.allow:
            return None  # clean / unavailable / failed-open: quiet
        # BLOCK render: the NOT-CLEAN cert as the native per-head pre-commit
        # block (D7 headline); an empty cert render (or cert off/fault) falls
        # back to the existing single-line native refusal — never silent on a
        # real block.
        text = ""
        cert_rendered = False
        if cert is not None:
            try:
                from groundtruth.runtime.native_render import (
                    render_completion_cert_native,
                )

                text = render_completion_cert_native(
                    list(getattr(cert, "unresolved_failures", ()) or ()))
                cert_rendered = bool(text)
            except Exception:  # noqa: BLE001 - render fault -> plain refusal
                text = ""
        if not text:
            text = render_submit_rejection(verdict.reason, verdict.detail)
        ev_type = ("submit_refusal"
                   if cert_rendered
                   or verdict.reason in ("covering_test_failed",
                                         "observed_red_unresolved",
                                         "verification_missing")
                   else "syntax_result")
        # Seam-owned leak guard + law 8 on the rendered bytes, same as a delta.
        if not text:
            self._trace_record(
                "decision.committed", "submit",
                {"decision": "suppressed", "reason": "render_empty",
                 "evidence_type": ev_type,
                 "feature_id": feature_for_evidence(ev_type) or ""})
            return None
        if contains_gt_tag(text) or contains_test_identity(text):
            self._trace_record(
                "decision.committed", "submit",
                {"decision": "suppressed", "reason": "leak_guard",
                 "evidence_type": ev_type,
                 "feature_id": feature_for_evidence(ev_type) or ""})
            return None
        if not fits_budget(text, max_delta_chars=MAX_DELTA_CHARS):
            self._trace_record(
                "decision.committed", "submit",
                {"decision": "suppressed", "reason": "over_budget",
                 "evidence_type": ev_type,
                 "feature_id": feature_for_evidence(ev_type) or "",
                 "rendered_chars": len(text)})
            return None
        # W2-R4 fix: the bounce is spent ONLY when refusal text actually
        # ships (all guards above passed). A guard-suppressed refusal (empty
        # render, leak trip, over budget) is a silent allow and must not burn
        # the single bounce — otherwise the NEXT submit fails open
        # unconditionally and a real block never ships at all. max_bounces=1
        # semantics are unchanged for genuinely-shipped refusals: the probe
        # after a shipped refusal is gate_overridden (fail-open, no deadlock).
        self.submit_bounces += 1
        # The cert block / a covering block / the SS-2 observed-RED block is
        # the submit_refusal fact class (production's lineage binding,
        # gt_mini_patch.py:22415; gt_gt.md: GT_SS_SUBMIT_RED owns
        # submit_refusal); the legacy syntax-only fallback keeps its executed
        # syntax_result identity.
        env = EvidenceEnvelope.build(
            producer="submit_gate", fact_id=bad_rel or "submit",
            target=bad_rel or "submit", evidence_type=ev_type,
            payload=tuple(text.splitlines()),
            provenance=((bad_rel, 0),) if bad_rel else (),
            confidence=0.9, tier=VERIFIED, preferred_event="submit",
            measured=True)  # an EXECUTED toolchain check, not a heuristic
        sealed, self.chain_head = seal_delivery(
            env,
            episode_id=getattr(self.episode, "episode_id", ""),
            event_id=str(self.action_index),
            parent_hash=self.chain_head,
            rendered_bytes=text.encode("utf-8", "surrogatepass"),
            renderer_id="native",
            tool_output_bytes=b"",
            boundary=("0:" + ev_type).encode("utf-8"),
            dedup_chain=self.episode.delivered_dedup,
        )
        self.deliveries.append(sealed)
        capability_ids: list[str] = []
        if ev_type == "syntax_result" and syntax_res is not None:
            capability_ids.append("GT_EDIT_CHECK")
        if (
            submit_block
            and submit_block.get("reason") == "observed_red_unresolved"
        ):
            capability_ids.append("GT_SS_SUBMIT_RED")
        # The certificate owns the completion decision whenever it was built
        # successfully. Its native renderer may legitimately yield no
        # per-head lines for the broad observed-RED fallback, in which case
        # the refusal text falls back to render_submit_rejection; that render
        # fallback does not erase the certificate's applied decision.
        if cert is not None:
            capability_ids.append("GT_CERT_DELIVERY")
        self._ledger_record(
            sealed,
            text,
            "submit",
            capability_ids=tuple(capability_ids),
        )
        return text

    def task_start(self) -> str | None:
        """Task-start capsule: production's step-0 surface is the v1r brief
        (``pretask.v1r_brief.generate_v1r_brief`` - ranked files + obligations;
        deterministic given the graph: without an installed embedder the dense
        leg degrades to the zero-embedding model and lexical/graph signals
        lead). ``gateway.augment`` has NO task_start producer (its producers
        dispatch on view/edit/test/search semantics), so the brief is the one
        correct option. Returns the rendered, leak-guarded, budget-checked,
        SEALED capsule string, or None (no issue text, empty brief, guard
        drop, or ANY fault - correct-or-quiet). Never raises."""
        try:
            profile_receipt = self._profile_activation_receipt()
            self._trace_record(
                "run.started",
                "task_start",
                {
                    "gt_enabled": True,
                    "graph_available": bool(self.graph_db),
                    "feature_count": 17,
                    "provider_final_receipts_required": True,
                    **profile_receipt,
                },
            )
            self._lifecycle_checkpoint(
                "task_start",
                "issue_and_graph_received",
                issue_present=bool((self.issue_text or "").strip()),
                graph_available=bool(self.graph_db),
            )
            result = self._task_start()
            if result is None:
                self._trace_record(
                    "decision.committed",
                    "task_start",
                    {
                        "decision": "no_delivery",
                        "reason": (
                            "required_input_absent"
                            if not self.graph_db or not (self.issue_text or "").strip()
                            else "producer_abstained_or_guarded"
                        ),
                        "feature_id": "obligations",
                    },
                )
            return result
        except Exception as exc:  # noqa: BLE001 - a brief fault must never break task start
            self._trace_record(
                "decision.committed",
                "task_start",
                {
                    "decision": "telemetry_fault",
                    "reason": "task_start_exception",
                    "fault_type": type(exc).__name__,
                    "feature_id": "obligations",
                },
            )
            return None

    def _task_start(self) -> str | None:
        if not (self.issue_text or "").strip():
            self._trace_record(
                "feature.evaluated", "task_start",
                {"feature_id": "obligations", "eligible": False,
                 "outcome": "issue_text_absent"})
            return None
        if not self.graph_db:
            self._trace_record(
                "feature.evaluated", "task_start",
                {"feature_id": "obligations", "eligible": False,
                 "outcome": "graph_unavailable"})
            return None  # DORMANT bridge: no graph substrate, no honest brief
        if os.environ.get("GT_GATEWAY", "").strip().lower() in (
                "", "0", "false", "no", "off"):
            self._trace_record(
                "feature.evaluated", "task_start",
                {"feature_id": "obligations", "eligible": False,
                 "outcome": "feature_disabled"})
            return None
        import contextlib
        import io

        from groundtruth.pretask.v1r_brief import generate_v1r_brief
        from groundtruth.runtime.adapters.miniswe import fits_budget, seal_delivery
        from groundtruth.runtime.evidence_envelope import INFO, EvidenceEnvelope
        from groundtruth.runtime.native_render import (
            contains_gt_tag,
            contains_test_identity,
        )

        # The brief generator prints host-side diagnostics ([GT L1]/[GT_META])
        # to stdout; swallow them - they are telemetry, never model bytes.
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            res = generate_v1r_brief(self.issue_text, self.repo_root, self.graph_db)
        text = (getattr(res, "brief_text", "") or "").strip()
        # Unwrap the <gt-task-brief> FRAME (production's step-0 container tag;
        # a pure form unwrap of GT's own wrapper, content untouched). Any
        # OTHER <gt-*> tag surviving inside still fails the leak guard below.
        text = re.sub(r"^\s*<gt-task-brief>\s*", "", text)
        text = re.sub(r"\s*</gt-task-brief>\s*$", "", text).strip()
        if not text:
            self._trace_record(
                "feature.evaluated", "task_start",
                {"feature_id": "obligations", "eligible": False,
                 "outcome": "brief_empty"})
            return None
        # Seam leak guard on the rendered bytes: in the native channel a
        # <gt-*> tag must never reach the model; test identity never may.
        native = os.environ.get("GT_GATEWAY_NATIVE") == "1"
        if (native and contains_gt_tag(text)) or contains_test_identity(text):
            self._trace_record(
                "decision.committed", "task_start",
                {"decision": "suppressed", "reason": "leak_guard",
                 "evidence_type": "obligations",
                 "feature_id": "obligations"})
            return None
        if not fits_budget(text, max_delta_chars=MAX_DELTA_CHARS):
            self._trace_record(
                "decision.committed", "task_start",
                {"decision": "suppressed", "reason": "over_budget",
                 "evidence_type": "obligations",
                 "feature_id": "obligations",
                 "rendered_chars": len(text)})
            return None  # law 8: over-budget dropped WHOLE, never clipped
        env = EvidenceEnvelope.build(
            producer="v1r_brief", fact_id="task_start", target="task_start",
            evidence_type="obligations", payload=tuple(text.splitlines()),
            confidence=0.5, tier=INFO, preferred_event="step0")
        sealed, self.chain_head = seal_delivery(
            env,
            episode_id=getattr(self.episode, "episode_id", ""),
            event_id="0",
            parent_hash=self.chain_head,
            rendered_bytes=text.encode("utf-8", "surrogatepass"),
            renderer_id="native" if native else "tagged",
            tool_output_bytes=b"",
            boundary=b"0:task_start",
            dedup_chain=self.episode.delivered_dedup,
        )
        self.deliveries.append(sealed)
        self._ledger_record(sealed, text, "task_start")
        return text

    def _deliver(
        self,
        command: str,
        output: str,
        returncode: int | None,
        *,
        changed_files: tuple[str, ...] = (),
        viewed_files: tuple[str, ...] = (),
        edit_before_after: dict | None = None,
    ) -> str:
        """The production call sequence. Returns the (possibly) enriched output."""
        from groundtruth.runtime.adapters.miniswe import (
            fits_budget,
            normalize_event,
            render_envelope,
            seal_delivery,
            select,
        )
        from groundtruth.runtime.gateway import GatewayState, augment
        from groundtruth.runtime.native_render import (
            contains_gt_tag,
            contains_test_identity,
        )

        # 1. normalize (pure). covering= deliberately NOT threaded (SM-3).
        event_output = gateway_observation_output(command, output, returncode)
        ev = normalize_event(
            command, event_output, returncode, self.action_index,
            changed_files=changed_files, viewed_files=viewed_files,
            edit_before_after=edit_before_after)
        # 2. per-turn state over the ONE shared episode (production pattern).
        st = GatewayState(
            graph_db=self.graph_db, repo_root=self.repo_root,
            issue_text=self.issue_text, episode=self.episode,
            control_recorder=self._control_record,
            producer_recorder=self._producer_record,
            producer_audit_context={
                "observation_id": f"{self._attribution.trace_id}:{self.action_index}",
                "decision_id": f"gateway:{self.action_index}",
                "decision_context": "nano.tool_result",
                "decision_open": True,
            })
        # 3. THE ONE CALL.
        envelopes = augment(ev, st)
        # 4. dose law: <=1 envelope per observation.
        winners = select(envelopes, max_doses=1, multidose=False)
        if not winners:
            self._trace_record(
                "decision.committed",
                "gateway",
                {
                    "decision": "no_delivery",
                    "reason": "no_candidate",
                    "candidate_count": len(envelopes),
                },
            )
            return output
        winner = winners[0]
        # 5. render in the seam's channel (GT_GATEWAY_NATIVE keys the form).
        native = os.environ.get("GT_GATEWAY_NATIVE") == "1"
        delta = render_envelope(winner, native=native)
        # 6. seam-owned leak guard on the RENDERED bytes: drop WHOLE.
        if not delta:
            self._trace_record(
                "decision.committed",
                "gateway",
                {
                    "decision": "suppressed",
                    "reason": "render_empty",
                    "evidence_type": winner.evidence_type or "",
                },
            )
            return output
        if (native and contains_gt_tag(delta)) or contains_test_identity(delta):
            self._trace_record(
                "decision.committed",
                "gateway",
                {
                    "decision": "suppressed",
                    "reason": "leak_guard",
                    "evidence_type": winner.evidence_type or "",
                },
            )
            return output
        # 7. law 8: over-budget delta dropped WHOLE (checked on the delta,
        #    BEFORE the newline join - the seam then seals the joined suffix).
        if not fits_budget(delta, max_delta_chars=MAX_DELTA_CHARS):
            self._trace_record(
                "decision.committed",
                "gateway",
                {
                    "decision": "suppressed",
                    "reason": "over_budget",
                    "evidence_type": winner.evidence_type or "",
                    "rendered_chars": len(delta),
                },
            )
            return output
        # 8. SEAL BEFORE APPEND (B-33). Seal the EXACT shipped suffix bytes,
        #    including the single '\n' boundary inserted only when needed.
        shipped = self._join(output, delta)[len(output):]
        tob = output.encode("utf-8", "surrogatepass")
        sealed, self.chain_head = seal_delivery(
            winner,
            episode_id=getattr(self.episode, "episode_id", ""),
            event_id=str(self.action_index),
            parent_hash=self.chain_head,
            rendered_bytes=shipped.encode("utf-8", "surrogatepass"),
            renderer_id="native" if native else "tagged",
            tool_output_bytes=tob,
            boundary=(str(len(tob)) + ":" + (winner.evidence_type or "gw")
                      ).encode("utf-8"),
            dedup_chain=self.episode.delivered_dedup,
        )
        self.deliveries.append(sealed)
        self.delivered_spans.append(DeliveredSpan(
            text=shipped, tier=winner.tier or "",
            evidence_type=winner.evidence_type or "",
            dedup_key=winner.dedup_key or ""))
        producer_capability = {
            "change_surface": "GT_CHANGE_SURFACE",
            "patch_delta": "GT_PATCH_DELTA",
            "edit_check": "GT_EDIT_CHECK",
        }.get(str(getattr(winner, "producer", "") or ""))
        self._ledger_record(
            sealed,
            shipped,
            "gateway",
            capability_ids=(
                (producer_capability,) if producer_capability else ()
            ),
        )
        # 9. pure-suffix append (TITO law 1).
        return output + shipped

    @staticmethod
    def _join(prev: str, block: str) -> str:
        """Exactly ONE '\\n' boundary, only when neither side supplies one
        (the seam's _join_lane_output, gt_mini_patch.py:15072)."""
        if block and prev and not prev.endswith("\n") and not block.startswith("\n"):
            return prev + "\n" + block
        return prev + block
