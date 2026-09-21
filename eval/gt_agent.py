"""GT attached to mini-swe-agent: callable tools plus query-anchored enrichment.

This is a delivery change, not a capability change. Everything GT computes is
unchanged - graph, dense index, plan gate, contracts, predicates, provenance.
What changes is how the answers reach the model:

  before   GT decided what was relevant and injected it at every action
           boundary, whether or not the agent had asked for anything.
  now      the agent calls a tool when it wants one, and a search it ran
           itself comes back annotated for the symbol IT named.

The motivation is measured, not aesthetic. Across 98 tasks GT never beat its
GT-off baseline, and on DeepSWE the three healthiest graphs each lost a task
the stock scaffold solved while the worst-health task won; losing runs carried
roughly half again as much injected context as winning ones. The context
window is a budget, and we were spending the agent's on material it had not
asked for.

There is ONE mode. A run either has GT attached or it does not.
"""

from __future__ import annotations

import logging
import re
import time

from eval.gt_tool_registry import (
    AUGMENT_BIN,
    AUGMENT_MARKER,
    AUGMENT_TIMEOUT_SECONDS,
    BINARIES_BY_KEY,
    TOOL_METRIC_KEYS,
)

logger = logging.getLogger("gt_agent")

#: A pattern shorter than this matches everything and annotating it is noise.
MIN_PATTERN_LENGTH = 3

#: Hard ceiling on an appended annotation. The whole point is to stop spending
#: the agent's context window without being asked; an unbounded annotation
#: would reintroduce the problem through the new door.
MAX_AUGMENT_BYTES = 4096

#: Commands whose output is worth annotating: the agent is looking for a
#: symbol and has told us which one.
_SEARCH_COMMANDS = ("grep", "rg", "ag", "ack")

# The pattern is the first non-flag, non-path token after the search command.
# Quoted first, because a quoted pattern may contain spaces.
_PATTERN_PATTERNS = (
    re.compile(r"(?:^|[\s|;&])(?:grep|rg|ag|ack)\s+(?:-[-\w]+\s+)*[\"']([^\"']+)[\"']"),
    re.compile(r"(?:^|[\s|;&])(?:grep|rg|ag|ack)\s+(?:-[-\w]+\s+)*(\S+)"),
)


def extract_search_pattern(command: str) -> str | None:
    """The symbol the agent asked about, or None if this is not a search.

    Returns None rather than guessing: an annotation about a symbol the agent
    did not name is the supply-driven push this module exists to remove.
    """
    if not command or not any(name in command for name in _SEARCH_COMMANDS):
        return None
    for matcher in _PATTERN_PATTERNS:
        match = matcher.search(command)
        if not match:
            continue
        # Strip quotes before judging: otherwise a pattern rejected as too
        # short by the quoted matcher is matched again by the looser one WITH
        # its quotes, which passes the length check and annotates rubbish.
        pattern = match.group(1).strip().strip("\"'")
        # A path or a flag is not a symbol.
        if not pattern or pattern.startswith(("-", "/", ".", "~", "$")):
            continue
        if len(pattern) < MIN_PATTERN_LENGTH:
            return None
        return pattern
    return None


class GtMetrics:
    """What the AGENT did with GT, which is what we have never measured.

    The existing journal counts producer invocations and abstentions: those
    say what GT did. None of them answer whether the agent wanted it, called
    it, or read it.
    """

    def __init__(self) -> None:
        self.tool_calls: dict[str, int] = {key: 0 for key in TOOL_METRIC_KEYS}
        self.augment_calls = 0
        self.augment_hits = 0
        self.augment_errors = 0
        self.augment_seconds = 0.0
        self.bytes_delivered = 0
        self.searches_seen = 0

    @property
    def total_tool_calls(self) -> int:
        return sum(self.tool_calls.values())

    @property
    def augment_hit_rate(self) -> float:
        """Share of the agent's searches that came back with something."""
        return self.augment_hits / self.searches_seen if self.searches_seen else 0.0

    def to_dict(self) -> dict:
        return {
            "schema": "gt.attachment_usage.v1",
            "tool_calls": dict(self.tool_calls),
            "total_tool_calls": self.total_tool_calls,
            "searches_seen": self.searches_seen,
            "augment_calls": self.augment_calls,
            "augment_hits": self.augment_hits,
            "augment_errors": self.augment_errors,
            "augment_hit_rate": round(self.augment_hit_rate, 4),
            "augment_seconds": round(self.augment_seconds, 2),
            "gt_bytes_delivered": self.bytes_delivered,
        }


class GtAttachmentMixin:
    """Tool-usage tracking and query-anchored enrichment for a mini-swe agent.

    A mixin rather than a subclass so it can sit on whichever agent class the
    lane already builds, without forking the scaffold.
    """

    augment_timeout: float = AUGMENT_TIMEOUT_SECONDS
    max_augment_bytes: int = MAX_AUGMENT_BYTES

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.gt_metrics = GtMetrics()

    # -- tracking -----------------------------------------------------------

    def note_tool_usage(self, command: str) -> None:
        """Count a GT tool the agent chose to run."""
        if not command:
            return
        for key, binary in BINARIES_BY_KEY.items():
            if binary in command:
                self.gt_metrics.tool_calls[key] += 1
                return

    # -- enrichment ---------------------------------------------------------

    def augment_observation(self, command: str, output: str) -> str:
        """Append GT's annotation for the symbol the agent searched for.

        Returns ``output`` unchanged when the command is not a search, when GT
        has nothing, or when anything goes wrong. A failed annotation must
        never cost the agent its observation.
        """
        pattern = extract_search_pattern(command)
        if pattern is None:
            return output

        self.gt_metrics.searches_seen += 1
        started = time.monotonic()
        try:
            result = self.run_augment(pattern)
        except Exception as exc:  # noqa: BLE001 - enrichment is never fatal
            self.gt_metrics.augment_errors += 1
            logger.debug("gt augmentation failed for %r: %s", pattern, exc)
            return output
        finally:
            self.gt_metrics.augment_calls += 1
            self.gt_metrics.augment_seconds += time.monotonic() - started

        annotation = (result or "").strip()
        if not annotation or AUGMENT_MARKER not in annotation:
            # Silent is correct. An empty section teaches the agent to ignore
            # the marker, which costs us the times we do have something.
            return output

        if len(annotation) > self.max_augment_bytes:
            annotation = (
                annotation[: self.max_augment_bytes]
                + f"\n... truncated at {self.max_augment_bytes} bytes"
            )

        self.gt_metrics.augment_hits += 1
        self.gt_metrics.bytes_delivered += len(annotation)
        return f"{output}\n\n{annotation}" if output else annotation

    def run_augment(self, pattern: str) -> str:
        """Execute the enrichment helper in the task environment.

        Split out so a lane with a different execution seam overrides one
        method, and so tests can drive the logic without a container.
        """
        raise NotImplementedError

    # -- receipts -----------------------------------------------------------

    def usage_receipt(self) -> dict:
        return {"gt_attachment": self.gt_metrics.to_dict()}


def augment_command(pattern: str) -> str:
    """The shell command that asks GT about one pattern.

    Quoting matters: a pattern can contain shell metacharacters, and the
    helper exits 0 with no output when GT has nothing to say.
    """
    escaped = pattern.replace("'", "'\"'\"'")
    return f"{AUGMENT_BIN} '{escaped}' 2>/dev/null || true"
