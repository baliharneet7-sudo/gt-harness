"""GT reaches the agent only where the agent asked.

The behaviour under test is a delivery change. GT computes exactly what it
computed before; what these tests pin is that it arrives in response to the
agent's own search or an explicit tool call, and never because GT decided
something was relevant.

The motivation is measured. Across 98 tasks GT never beat its GT-off
baseline, and on DeepSWE the three healthiest graphs each lost a task the
stock scaffold solved while the worst-health task won, with losing runs
carrying about half again as much injected context as winning ones.
"""

from __future__ import annotations

import pytest

from eval.gt_agent import (
    MAX_AUGMENT_BYTES,
    GtAttachmentMixin,
    augment_command,
    extract_search_pattern,
)
from eval.gt_tool_registry import (
    AUGMENT_BIN,
    AUGMENT_MARKER,
    BINARIES_BY_KEY,
    TOOL_SPECS,
    all_scripts,
    tool_script,
)


class _Agent(GtAttachmentMixin):
    """The mixin over a null base, with the environment seam stubbed."""

    def __init__(self, reply: str = "", raises: Exception | None = None) -> None:
        super().__init__()
        self._reply = reply
        self._raises = raises
        self.patterns: list[str] = []

    def run_augment(self, pattern: str) -> str:
        self.patterns.append(pattern)
        if self._raises is not None:
            raise self._raises
        return self._reply


# --- the pattern the agent named ------------------------------------------

@pytest.mark.parametrize(
    "command,expected",
    [
        ('grep -rn "BoundField" .', "BoundField"),
        ("grep -rn BoundField src/", "BoundField"),
        ("rg --hidden 'parse_config' lib/", "parse_config"),
        ('ag "handle_request"', "handle_request"),
        ("cat django/forms/boundfield.py", None),
        ("ls -la", None),
        ("python -m pytest", None),
        ('grep -rn "ab" .', None),          # shorter than MIN_PATTERN_LENGTH
        ("grep -rn -- -flagish .", None),   # a flag is not a symbol
        ("grep -rn /etc/passwd .", None),   # a path is not a symbol
    ],
)
def test_the_pattern_comes_from_the_agents_own_command(command, expected):
    assert extract_search_pattern(command) == expected


def test_a_non_search_command_is_never_annotated():
    """The whole point: GT does not volunteer.

    Reading a file is not a question about a symbol, and the previous design
    treated it as one - `gateway.view.caller_contract_view` fired on every
    file view.
    """
    agent = _Agent(reply=f"{AUGMENT_MARKER} callers: x, y")

    result = agent.augment_observation("cat setup.py", "...file contents...")

    assert result == "...file contents..."
    assert agent.patterns == []
    assert agent.gt_metrics.augment_calls == 0


def test_a_search_is_annotated_with_what_gt_knows():
    agent = _Agent(reply=f"{AUGMENT_MARKER} callers of BoundField: Form.clean")

    result = agent.augment_observation('grep -rn "BoundField" .', "hit.py:1: BoundField")

    assert "hit.py:1: BoundField" in result
    assert "callers of BoundField" in result
    assert agent.patterns == ["BoundField"]
    assert agent.gt_metrics.augment_hits == 1


def test_silence_is_an_answer():
    """An empty section teaches the agent to skip the marker.

    That costs us the times we DO have something, so a tool with nothing to
    say must leave the observation untouched.
    """
    agent = _Agent(reply="")

    result = agent.augment_observation('grep -rn "Widget" .', "hit.py:2: Widget")

    assert result == "hit.py:2: Widget"
    assert agent.gt_metrics.searches_seen == 1
    assert agent.gt_metrics.augment_hits == 0


def test_output_without_the_marker_is_not_appended():
    agent = _Agent(reply="some stray stdout with no marker")

    result = agent.augment_observation('grep -rn "Widget" .', "hit")

    assert result == "hit"
    assert agent.gt_metrics.augment_hits == 0


def test_a_failed_augmentation_never_costs_the_observation():
    agent = _Agent(raises=RuntimeError("daemon down"))

    result = agent.augment_observation('grep -rn "Widget" .', "hit.py:2: Widget")

    assert result == "hit.py:2: Widget"
    assert agent.gt_metrics.augment_errors == 1
    assert agent.gt_metrics.augment_calls == 1


def test_an_annotation_is_bounded():
    """Unbounded enrichment would reintroduce the problem through a new door."""
    agent = _Agent(reply=AUGMENT_MARKER + " " + ("x" * (MAX_AUGMENT_BYTES * 2)))

    result = agent.augment_observation('grep -rn "Widget" .', "hit")

    assert len(result) < MAX_AUGMENT_BYTES * 2
    assert "truncated" in result


# --- what the agent did with it -------------------------------------------

def test_tool_calls_are_counted_per_tool():
    agent = _Agent()

    agent.note_tool_usage('gt-context "BoundField"')
    agent.note_tool_usage("gt-impact BoundField upstream")
    agent.note_tool_usage("gt-impact Widget downstream")
    agent.note_tool_usage("ls -la")

    assert agent.gt_metrics.tool_calls["context"] == 1
    assert agent.gt_metrics.tool_calls["impact"] == 2
    assert agent.gt_metrics.total_tool_calls == 3


def test_the_hit_rate_is_over_searches_not_over_turns():
    """The question is what share of the agent's OWN searches GT answered."""
    agent = _Agent(reply=f"{AUGMENT_MARKER} something")

    agent.augment_observation('grep -rn "Alpha" .', "a")
    agent.augment_observation("cat file.py", "b")          # not a search
    agent.augment_observation('grep -rn "Beta" .', "c")

    assert agent.gt_metrics.searches_seen == 2
    assert agent.gt_metrics.augment_hit_rate == 1.0


def test_the_receipt_reports_agent_side_usage():
    agent = _Agent(reply=f"{AUGMENT_MARKER} x")
    agent.augment_observation('grep -rn "Alpha" .', "a")
    agent.note_tool_usage("gt-find 'thing'")

    receipt = agent.usage_receipt()["gt_attachment"]

    assert receipt["schema"] == "gt.attachment_usage.v1"
    assert receipt["total_tool_calls"] == 1
    assert receipt["augment_hits"] == 1
    assert receipt["gt_bytes_delivered"] > 0


# --- the tools themselves --------------------------------------------------

def test_every_tool_is_self_contained():
    """mini-swe-agent runs each command in a fresh subshell.

    No `.bashrc`, no inherited environment, no session state: a script that
    needs sourcing is a script the agent cannot use.
    """
    for name, body in all_scripts().items():
        assert body.startswith("#!/bin/sh"), name
        assert "source " not in body, name
        assert ". /" not in body, name


def test_every_tool_falls_back_when_the_daemon_is_down():
    """The daemon is an optimisation, never a dependency."""
    for spec in TOOL_SPECS:
        body = tool_script(spec)
        assert "curl" in body
        assert "groundtruth tool" in body


def test_a_tool_called_wrong_explains_itself():
    """Exit 2 and a usage line, so the agent can correct without a traceback."""
    spec = next(s for s in TOOL_SPECS if s.args)

    body = tool_script(spec)

    assert "usage:" in body
    assert "exit 2" in body


def test_the_augment_helper_is_not_in_the_agents_vocabulary():
    """The harness calls it; the agent never types it."""
    assert AUGMENT_BIN not in BINARIES_BY_KEY.values()
    assert AUGMENT_BIN in all_scripts()


def test_a_pattern_with_shell_metacharacters_is_quoted():
    command = augment_command("O'Brien && rm -rf /")

    assert command.startswith(f"{AUGMENT_BIN} '")
    assert "'\"'\"'" in command       # the single quote is escaped, not closed
    assert command.rstrip().endswith("|| true")
