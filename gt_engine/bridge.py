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
  signal was causally inverted). covering= is NOT threaded (SM-3: would
  double-deliver once a covering lane exists).
"""
from __future__ import annotations

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
    - GT_RL_PROFILE = explicit token -> ``resolve_profile`` (that profile's
      members; an explicit member env value rides through unchanged).
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
        if profile:
            from groundtruth.runtime.rl_profile import resolve_profile

            members = resolve_profile(os.environ)
        else:
            from groundtruth.runtime.rl_profile import resolve_profile_defaults

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


def bash_edit_target(cmd: str) -> str | None:
    """The SOURCE file a bash command WRITES, or None (production
    `_edit_target` mechanism: patch payload -> redirect -> edit-keyword source
    arg -> python/node write -> deferred /tmp redirect)."""
    if not cmd:
        return None
    pt = _patch_payload_target(cmd)
    if pt:
        return pt
    nohd = _without_heredoc_bodies(cmd)
    redir_fallback: str | None = None
    for mm in _REDIRECT_RE.finditer(nohd):
        t = mm.group(1).strip("\"'`()")
        if _has_source_ext(t) and "*" not in t and "$" not in t:
            if t.startswith("/tmp/"):
                redir_fallback = redir_fallback or t  # scratch: defer
            else:
                return t
    if _EDIT_KW_RE.search(cmd.split("\n", 1)[0].lstrip()):
        toks = _src_tokens(nohd)
        if toks:
            return toks[-1]
    for rx in (_PY_WRITE_RE, _JS_WRITE_RE):
        m = rx.search(cmd)
        if m and _has_source_ext(m.group(1)) and "*" not in m.group(1):
            return m.group(1)
    return redir_fallback


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
    graph_db: str
    issue_text: str = ""
    action_index: int = 0
    chain_head: str = ""  # TITO chain genesis per episode
    deliveries: list[Any] = field(default_factory=list)  # sealed envelopes
    delivered_spans: list[DeliveredSpan] = field(default_factory=list)
    edited_files: list[str] = field(default_factory=list)  # repo-rel, in order
    submit_bounces: int = 0  # gate-kernel refusals already spent this episode

    def __post_init__(self) -> None:
        self.repo_root = self._fwd(self.repo_root)
        # Bash-edit pre-images captured at the pre-dispatch boundary:
        # {rel: before_content_or_None}; None = the target did not exist (a
        # creation); an ABSENT key = unreadable/huge -> downstream stays quiet.
        self._bash_preimages: dict[str, str | None] = {}
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
            if not _edit_bridges_on():
                return
            cmd = str(tool_args.get("command") or "")
            from groundtruth.runtime.gateway import KIND_EDIT, classify_command

            if classify_command(cmd) != KIND_EDIT:
                return
            target = bash_edit_target(cmd)
            if not target:
                return
            rel = self._repo_rel(target)
            if not rel:
                return
            fp = self._confined_abs(rel)
            if fp is None:
                return
            if not os.path.exists(fp):
                self._bash_preimages[rel] = None  # positive creation evidence
                return
            if not os.path.isfile(fp) or os.path.getsize(fp) > _MAX_BRIDGE_FILE_BYTES:
                return  # no entry: downstream stays quiet
            with open(fp, encoding="utf-8", errors="replace") as fh:
                self._bash_preimages[rel] = fh.read()
        except Exception:  # noqa: BLE001 - pre-image capture must never break dispatch
            self._bash_preimages.clear()

    def _bash_bridges(self, cmd: str) -> tuple[tuple[str, ...], dict | None]:
        """POST-dispatch: (changed_files, edit_before_after) for a bash edit
        (production `_gateway_edit_bridges`). AFTER = current on-disk content;
        BEFORE only from the captured pre-image - a wrong before/after
        fabrication is worse than absence."""
        if not _edit_bridges_on():
            return (), None
        target = bash_edit_target(cmd)
        if not target:
            return (), None
        rel = self._repo_rel(target)
        if not rel:
            return (), None
        changed: tuple[str, ...] = (rel,)
        after: str | None = None
        try:
            fp = self._confined_abs(rel)
            if (fp and os.path.isfile(fp)
                    and os.path.getsize(fp) <= _MAX_BRIDGE_FILE_BYTES):
                with open(fp, encoding="utf-8", errors="replace") as fh:
                    after = fh.read()
        except Exception:  # noqa: BLE001
            after = None
        if after is None or rel not in self._bash_preimages:
            return changed, None  # changed only - never a fabricated before
        return changed, {rel: (self._bash_preimages[rel], after)}

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
    ) -> str:
        """Complete this observation with at most one gateway dose.

        Returns ``output`` + evidence suffix, or ``output`` unchanged (GT off,
        nothing produced, guard drop, or ANY internal fault)."""
        self.action_index += 1
        try:
            cmd, rc, changed, viewed, eba = self._event_parts(
                tool_name, tool_args, output, is_error, edit_before, edit_after)
            for rel in changed:
                if rel and rel not in self.edited_files:
                    self.edited_files.append(rel)  # submit-gate syntax domain
            return self._deliver(cmd, output, rc,
                                 changed_files=changed, viewed_files=viewed,
                                 edit_before_after=eba)
        except Exception:  # noqa: BLE001 - GT failure must never break the harness
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
            return self._submit_gate()
        except Exception:  # noqa: BLE001 - advisory: any fault abstains
            return None

    # Syntax-check at most this many edited files at the submit boundary.
    _MAX_SUBMIT_SYNTAX_FILES = 10

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

        # POSITIVE evidence only: an executed parse failure in an edited file.
        submit_block: dict[str, Any] | None = None
        bad_rel = ""
        for rel in self.edited_files[: self._MAX_SUBMIT_SYNTAX_FILES]:
            res = check_edit_syntax(rel, self.repo_root)
            if res.get("verdict") == "syntax_error":
                bad_rel = rel
                submit_block = {
                    "blocking": True,
                    "reason": "syntax_error",
                    "detail": str(res.get("diagnostic") or "")
                    or f"syntax error in {rel}",
                }
                break
        verdict = safe_gate_verdict(
            covering=None, hygiene=None, submit_block=submit_block,
            bounce_count=self.submit_bounces, max_bounces=1)
        if verdict.allow:
            return None  # clean / unavailable / failed-open: quiet
        self.submit_bounces += 1
        text = render_submit_rejection(verdict.reason, verdict.detail)
        # Seam-owned leak guard + law 8 on the rendered bytes, same as a delta.
        if (not text or contains_gt_tag(text) or contains_test_identity(text)
                or not fits_budget(text, max_delta_chars=MAX_DELTA_CHARS)):
            return None
        env = EvidenceEnvelope.build(
            producer="submit_gate", fact_id=bad_rel or "submit",
            target=bad_rel or "submit", evidence_type="syntax_result",
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
            boundary=b"0:syntax_result",
            dedup_chain=self.episode.delivered_dedup,
        )
        self.deliveries.append(sealed)
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
            return self._task_start()
        except Exception:  # noqa: BLE001 - a brief fault must never break task start
            return None

    def _task_start(self) -> str | None:
        if not (self.issue_text or "").strip():
            return None
        if os.environ.get("GT_GATEWAY", "").strip().lower() in (
                "", "0", "false", "no", "off"):
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
            return None
        # Seam leak guard on the rendered bytes: in the native channel a
        # <gt-*> tag must never reach the model; test identity never may.
        native = os.environ.get("GT_GATEWAY_NATIVE") == "1"
        if (native and contains_gt_tag(text)) or contains_test_identity(text):
            return None
        if not fits_budget(text, max_delta_chars=MAX_DELTA_CHARS):
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
        ev = normalize_event(
            command, output, returncode, self.action_index,
            changed_files=changed_files, viewed_files=viewed_files,
            edit_before_after=edit_before_after)
        # 2. per-turn state over the ONE shared episode (production pattern).
        st = GatewayState(
            graph_db=self.graph_db, repo_root=self.repo_root,
            issue_text=self.issue_text, episode=self.episode)
        # 3. THE ONE CALL.
        envelopes = augment(ev, st)
        # 4. dose law: <=1 envelope per observation.
        winners = select(envelopes, max_doses=1, multidose=False)
        if not winners:
            return output
        winner = winners[0]
        # 5. render in the seam's channel (GT_GATEWAY_NATIVE keys the form).
        native = os.environ.get("GT_GATEWAY_NATIVE") == "1"
        delta = render_envelope(winner, native=native)
        # 6. seam-owned leak guard on the RENDERED bytes: drop WHOLE.
        if (not delta or (native and contains_gt_tag(delta))
                or contains_test_identity(delta)):
            return output
        # 7. law 8: over-budget delta dropped WHOLE (checked on the delta,
        #    BEFORE the newline join - the seam then seals the joined suffix).
        if not fits_budget(delta, max_delta_chars=MAX_DELTA_CHARS):
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
        # 9. pure-suffix append (TITO law 1).
        return output + shipped

    @staticmethod
    def _join(prev: str, block: str) -> str:
        """Exactly ONE '\\n' boundary, only when neither side supplies one
        (the seam's _join_lane_output, gt_mini_patch.py:15072)."""
        if block and prev and not prev.endswith("\n") and not block.startswith("\n"):
            return prev + "\n" + block
        return prev + block
