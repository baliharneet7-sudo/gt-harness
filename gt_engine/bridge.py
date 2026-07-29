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

_OFF_VALUES = ("", "0", "false", "no", "off")


def apply_profile_env() -> None:
    """Apply the GT capability-flag environment at init (decision E).

    The resolver returns a dict and does NOT set os.environ itself; every value
    is applied with setdefault so an explicit user value (including "0") always
    wins. An explicit GT_RL_PROFILE fans out to its member set; otherwise the
    default is the minimal deterministic pair GT_GATEWAY=1 + GT_GATEWAY_NATIVE=1.
    GT_XSESSION_* is never set here (determinism for A/B runs).
    """
    try:
        profile = (os.environ.get("GT_RL_PROFILE") or "").strip()
        if profile and profile.lower() not in ("0", "off", "none"):
            from groundtruth.runtime.rl_profile import resolve_profile

            for k, v in resolve_profile(os.environ).items():
                if k.startswith("GT_XSESSION"):
                    continue  # durable cross-session memory: off for determinism
                os.environ.setdefault(k, v)
        else:
            os.environ.setdefault("GT_GATEWAY", "1")
            os.environ.setdefault("GT_GATEWAY_NATIVE", "1")
    except Exception:  # noqa: BLE001 - misconfigured profile must not break the run
        os.environ.setdefault("GT_GATEWAY", "1")
        os.environ.setdefault("GT_GATEWAY_NATIVE", "1")


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

    def __post_init__(self) -> None:
        self.repo_root = self._fwd(self.repo_root)
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
            return (str(tool_args.get("command") or ""),
                    parse_exit_code(output, is_error), (), (), None)
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
            return self._deliver(cmd, output, rc,
                                 changed_files=changed, viewed_files=viewed,
                                 edit_before_after=eba)
        except Exception:  # noqa: BLE001 - GT failure must never break the harness
            return output

    def submit_probe(self) -> str | None:
        """Advisory submit-boundary check (gt_engine.verify uses this).

        Runs a synthetic submit event through the SAME pipeline; returns the
        delivered evidence text only when a submit_refusal / syntax_result
        class fires, else None. Never raises."""
        self.action_index += 1
        try:
            base = self._deliver(
                "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT", "", 0,
                allowed_types=frozenset({"submit_refusal", "syntax_result"}))
            return base.strip() or None
        except Exception:  # noqa: BLE001
            return None

    def _deliver(
        self,
        command: str,
        output: str,
        returncode: int | None,
        *,
        changed_files: tuple[str, ...] = (),
        viewed_files: tuple[str, ...] = (),
        edit_before_after: dict | None = None,
        allowed_types: frozenset[str] | None = None,
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
        if allowed_types is not None:
            envelopes = [
                e for e in envelopes
                if (e.evidence_type or "").split(":", 1)[0] in allowed_types
            ]
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
