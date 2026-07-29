"""gt_engine unit tests: bridge sequence, exit-code parsing, GT-off byte
identity of truncation, indexer detection, and a GT-off agent-loop smoke with
a stubbed provider (no API key required)."""
from __future__ import annotations

import copy
from typing import Any

import pytest

from gt_engine.bridge import DeliveredSpan, parse_exit_code
from gt_engine.context import smart_truncate
from gt_engine.indexer import ensure_index, is_code_repo
from nano.agent import Agent
from nano.providers import StepResult, ToolCall, Usage

try:
    import groundtruth  # noqa: F401
    HAVE_GT = True
except ImportError:
    HAVE_GT = False

requires_gt = pytest.mark.skipif(not HAVE_GT, reason="groundtruth not installed")


# --------------------------------------------------------------------------- #
# exit-code parsing (decision C: tools.py:172 flattens the code into a string)
# --------------------------------------------------------------------------- #
def test_parse_exit_code_success_is_zero():
    assert parse_exit_code("any output", is_error=False) == 0


def test_parse_exit_code_from_toolerror_text():
    out = "ERROR: FAILED tests/x.py::test_a\n[exit code 1]"
    assert parse_exit_code(out, is_error=True) == 1


def test_parse_exit_code_multiline_and_negative():
    assert parse_exit_code("ERROR: boom\nmore\n[exit code 137]", True) == 137
    assert parse_exit_code("ERROR: killed\n[exit code -9]", True) == -9


def test_parse_exit_code_unparsable_is_none():
    # Timeout / dead shell / dispatch errors carry no "[exit code N]" suffix.
    assert parse_exit_code("ERROR: Command exceeded timeout of 60s", True) is None
    assert parse_exit_code("", True) is None
    # The marker must be terminal, not mid-text.
    assert parse_exit_code("[exit code 3] and then more text", True) is None


# --------------------------------------------------------------------------- #
# GT-off byte identity: smart_truncate with no deliveries == stock truncation
# --------------------------------------------------------------------------- #
def _make_messages(n_results: int = 4, result_len: int = 500,
                   big_input: int = 0) -> list[dict[str, Any]]:
    msgs: list[dict[str, Any]] = [{"role": "user", "content": "task"}]
    for i in range(n_results):
        inp: dict[str, Any] = {"command": "echo hi"}
        if big_input:
            inp["new"] = "y" * big_input
        msgs.append({"role": "assistant", "content": [
            {"type": "tool_use", "id": f"t{i}", "name": "bash", "input": inp}]})
        msgs.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": f"t{i}",
             "content": f"out{i}:" + ("x" * result_len), "is_error": False}]})
    return msgs


@pytest.mark.parametrize("budget,big_input", [
    (10_000_000, 0),   # under budget: no-op
    (1200, 0),         # phase 1 only
    (300, 5000),       # phase 1 exhausts, phase 2 shrinks tool_use inputs
])
def test_smart_truncate_byte_identical_when_no_deliveries(budget, big_input):
    msgs = _make_messages(big_input=big_input)
    agent = Agent.__new__(Agent)  # no provider needed for _truncate_if_needed
    agent.truncation_char_budget = budget

    stock_msgs, stock_tr = copy.deepcopy(msgs), []
    Agent._truncate_if_needed(agent, stock_msgs, stock_tr)

    gt_msgs, gt_tr = copy.deepcopy(msgs), []
    smart_truncate(gt_msgs, gt_tr, char_budget=budget, delivered_spans=[])

    assert gt_msgs == stock_msgs
    assert gt_tr == stock_tr


def test_smart_truncate_drops_evidence_free_blocks_first():
    msgs = _make_messages(n_results=3, result_len=500)
    evidence = "pkg/a.py:1:helper\n"
    warn = "note: check callers\n"
    msgs[2]["content"][0]["content"] += "\n" + evidence   # block t0: VERIFIED
    msgs[4]["content"][0]["content"] += "\n" + warn       # block t1: WARNING
    spans = [DeliveredSpan(text=evidence, tier="VERIFIED",
                           evidence_type="def_ref_partition", dedup_key="k1"),
             DeliveredSpan(text=warn, tier="WARNING",
                           evidence_type="cochange_partner", dedup_key="k2")]
    # A tight budget drops all three blocks; the ORDER must be: the
    # evidence-free block (t2, the NEWEST) first, then WARNING (t1), then
    # VERIFIED (t0) last of all - the stock pass would have gone t0,t1,t2.
    tr: list[dict[str, Any]] = []
    smart_truncate(msgs, tr, char_budget=100, delivered_spans=spans)
    order = [t["tool_use_id"] for t in tr if t["type"] == "truncation"][:3]
    assert order == ["t2", "t1", "t0"]
    for i in (2, 4, 6):
        assert str(msgs[i]["content"][0]["content"]).startswith("[truncated")


def test_smart_truncate_keeps_phase_two():
    # Only oversized tool_use inputs can free the space: phase 2 must run.
    msgs = _make_messages(n_results=1, result_len=10, big_input=8000)
    tr: list[dict[str, Any]] = []
    smart_truncate(msgs, tr, char_budget=500, delivered_spans=[])
    assert str(msgs[1]["content"][0]["input"]["new"]).startswith("[truncated")


# --------------------------------------------------------------------------- #
# indexer: code-repo detection (GT dormant on non-code roots)
# --------------------------------------------------------------------------- #
def test_is_code_repo_detection(tmp_path):
    (tmp_path / "notes.txt").write_text("just text", encoding="utf-8")
    assert not is_code_repo(str(tmp_path))
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    assert is_code_repo(str(tmp_path))


def test_is_code_repo_skips_vendored_dirs(tmp_path):
    nm = tmp_path / "node_modules" / "dep"
    nm.mkdir(parents=True)
    (nm / "index.js").write_text("//", encoding="utf-8")
    assert not is_code_repo(str(tmp_path))


def test_ensure_index_non_code_root_returns_none(tmp_path):
    (tmp_path / "readme.txt").write_text("hello", encoding="utf-8")
    assert ensure_index(str(tmp_path)) is None
    assert ensure_index(str(tmp_path / "missing")) is None
    assert ensure_index(None) is None


# --------------------------------------------------------------------------- #
# bridge: the full production sequence against a real graph.db
# --------------------------------------------------------------------------- #
@pytest.fixture
def indexed_repo(tmp_path, monkeypatch):
    if not HAVE_GT:
        pytest.skip("groundtruth not installed")
    monkeypatch.setenv("GT_GATEWAY", "1")
    monkeypatch.setenv("GT_GATEWAY_NATIVE", "1")
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "alpha.py").write_text(
        "def helper(x, y):\n    return x + y\n\n\n"
        "def caller_a(v):\n    return helper(v, 1)\n", encoding="utf-8")
    (pkg / "beta.py").write_text(
        "def helper(a, b, c):\n    return a * b * c\n\n\n"
        "def caller_b(v):\n    return helper(v, 2, 3)\n", encoding="utf-8")
    (tmp_path / "main.py").write_text(
        "from pkg.alpha import caller_a\n\n\ndef run():\n"
        "    return caller_a(1)\n", encoding="utf-8")
    db = ensure_index(str(tmp_path))
    if db is None:
        pytest.skip("gt-index binary unavailable")
    from gt_engine.bridge import GTBridge
    return GTBridge(repo_root=str(tmp_path), graph_db=db)


_AMBIGUOUS_GREP = "grep -rn helper ."
_GREP_OUT = ("pkg/alpha.py:1:def helper(x, y):\n"
             "pkg/beta.py:1:def helper(a, b, c):\n")


@requires_gt
def test_bridge_delivers_sealed_pure_suffix(indexed_repo):
    b = indexed_repo
    out = b.enrich("bash", {"command": _AMBIGUOUS_GREP}, _GREP_OUT, False)
    # Pure suffix (TITO law 1): the original observation bytes are untouched.
    assert out.startswith(_GREP_OUT)
    assert len(out) > len(_GREP_OUT)
    # Sealed delivery: envelope stamped, chain advanced, dedup key recorded.
    assert len(b.deliveries) == 1
    sealed = b.deliveries[0]
    assert sealed.evidence_type == "def_ref_partition"
    assert sealed.receipt_state == "delivered"
    assert sealed.rendered_bytes_hash
    assert b.chain_head
    assert sealed.dedup_key in b.episode.delivered_dedup
    # Native render: no GT tag, no test identity, within budget.
    delta = out[len(_GREP_OUT):]
    assert "<gt-" not in delta.lower()
    assert len(delta) <= 4001  # delta + at most one inserted newline
    # Span tracked for evidence-aware truncation.
    assert b.delivered_spans[0].evidence_type == "def_ref_partition"


@requires_gt
def test_bridge_dedup_suppresses_repeat(indexed_repo):
    b = indexed_repo
    first = b.enrich("bash", {"command": _AMBIGUOUS_GREP}, _GREP_OUT, False)
    assert first != _GREP_OUT
    second = b.enrich("bash", {"command": _AMBIGUOUS_GREP}, _GREP_OUT, False)
    assert second == _GREP_OUT  # same fact never delivered twice
    assert len(b.deliveries) == 1


@requires_gt
def test_bridge_error_observation_never_breaks(indexed_repo):
    b = indexed_repo
    out = b.enrich("bash", {"command": "false"},
                   "ERROR: \n[exit code 1]", True)
    assert out.startswith("ERROR: ")  # raw output survives whatever GT does


@requires_gt
def test_bridge_internal_fault_returns_raw_output(indexed_repo):
    b = indexed_repo
    b.graph_db = 12345  # type: ignore[assignment] - poison the state
    out = b.enrich("bash", {"command": _AMBIGUOUS_GREP}, _GREP_OUT, False)
    assert out == _GREP_OUT  # correct-or-quiet: fault -> unchanged


@requires_gt
def test_bridge_repo_rel_paths(indexed_repo):
    b = indexed_repo
    rel = b._repo_rel(b.repo_root.replace("/", "\\") + "\\pkg\\alpha.py")
    assert rel == "pkg/alpha.py"  # decision J: repo-relative, forward slashes


# --------------------------------------------------------------------------- #
# GT-off agent-loop smoke: stubbed provider, no API key, gt_root=None
# --------------------------------------------------------------------------- #
class _ScriptedProvider:
    """Provider stub: yields a scripted sequence of StepResults."""

    def __init__(self, steps):
        self._steps = iter(steps)

    def step(self, messages, tools, system):
        return next(self._steps)


def _usage():
    return Usage(input_tokens=10, output_tokens=5, cache_read_tokens=0)


def test_agent_gt_off_smoke_end_to_end():
    steps = [
        StepResult(text=None, tool_calls=[ToolCall(
            id="c1", name="bash", arguments={"command": "echo nano-smoke"})],
            stop_reason="tool_use", usage=_usage()),
        StepResult(text="done", tool_calls=[], stop_reason="end_turn",
                   usage=_usage()),  # first done: challenged once
        StepResult(text=None, tool_calls=[ToolCall(
            id="c2", name="bash", arguments={"command": "echo verified"})],
            stop_reason="tool_use", usage=_usage()),
        StepResult(text="all done", tool_calls=[], stop_reason="end_turn",
                   usage=_usage()),
    ]
    agent = Agent(provider=_ScriptedProvider(steps), system="s")
    assert agent._gt is None  # gt_root defaulted: GT fully dormant
    result = agent.run("say hi")
    assert result.stop_reason == "end_turn"
    assert result.final_text == "all done"
    tool_outputs = [t for t in result.transcript if t["type"] == "tool_result"]
    assert any("nano-smoke" in t["output"] for t in tool_outputs)


def test_agent_gt_root_on_non_code_dir_stays_dormant(tmp_path):
    (tmp_path / "data.txt").write_text("no code here", encoding="utf-8")
    steps = [StepResult(text="hi", tool_calls=[], stop_reason="end_turn",
                        usage=_usage())]
    agent = Agent(provider=_ScriptedProvider(steps), system="s",
                  gt_root=str(tmp_path))
    assert agent._gt is None  # non-code root -> GT dormant
    assert agent.run("t").stop_reason == "end_turn"
