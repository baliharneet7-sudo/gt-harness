import pytest

from nano.agent import Agent, AgentResult
from nano.providers import StepResult, ToolCall, Usage
from nano.tools import BashTool


class FakeProvider:
    """Returns a scripted sequence of StepResults; raises if we run past."""
    model = "fake-model"

    def __init__(self, scripted: list[StepResult]) -> None:
        self.scripted = list(scripted)
        self.calls: list[dict] = []

    def step(self, messages, tools, system) -> StepResult:
        self.calls.append({"messages": list(messages),
                           "tools": tools, "system": system})
        if not self.scripted:
            raise AssertionError("FakeProvider exhausted")
        return self.scripted.pop(0)


def _u(i, o):
    return Usage(input_tokens=i, output_tokens=o)


def test_agent_one_shot_end_turn():
    fp = FakeProvider([
        StepResult(text="task done", tool_calls=[], stop_reason="end_turn",
                   usage=_u(10, 5)),
    ])
    agent = Agent(provider=fp, system="sys", max_iterations=10)
    result = agent.run("solve x")

    assert isinstance(result, AgentResult)
    assert result.final_text == "task done"
    assert result.stop_reason == "end_turn"
    assert result.iterations == 1
    assert result.total_input_tokens == 10
    assert result.total_output_tokens == 5


def test_agent_executes_tool_then_completes(tmp_workdir):
    p = tmp_workdir / "a.txt"
    p.write_text("hello\n")

    fp = FakeProvider([
        StepResult(
            text="reading", tool_calls=[ToolCall(
                id="t1", name="read_file", arguments={"path": str(p)})],
            stop_reason="tool_use", usage=_u(50, 10),
        ),
        StepResult(text="done", tool_calls=[], stop_reason="end_turn",
                   usage=_u(70, 4)),
    ])
    agent = Agent(provider=fp, system="sys", max_iterations=10, verify=False)
    result = agent.run("read it")

    assert result.iterations == 2
    assert result.final_text == "done"
    second_call_msgs = fp.calls[1]["messages"]
    user_with_tool_result = [m for m in second_call_msgs if m["role"] == "user"][-1]
    assert "hello" in str(user_with_tool_result["content"])


def test_agent_iteration_cap_stops_loop():
    looper = [
        StepResult(text="loop",
                   tool_calls=[ToolCall(id=f"t{i}", name="bash",
                                        arguments={"command": "echo i"})],
                   stop_reason="tool_use", usage=_u(1, 1))
        for i in range(20)
    ]
    fp = FakeProvider(looper)
    agent = Agent(provider=fp, system="sys", max_iterations=3)
    result = agent.run("loop forever")
    assert result.iterations == 3
    assert result.stop_reason == "max_iterations"


def test_agent_token_cap_stops_when_context_outgrows_budget():
    # The cap is on per-step context size (what one request sends), not on
    # cumulative spend. First step fits; second step's context exceeds cap.
    huge = [
        StepResult(text=None,
                   tool_calls=[ToolCall(id="t1", name="bash",
                                        arguments={"command": "echo x"})],
                   stop_reason="tool_use", usage=_u(50_000, 100)),
        StepResult(text=None,
                   tool_calls=[ToolCall(id="t2", name="bash",
                                        arguments={"command": "echo x"})],
                   stop_reason="tool_use", usage=_u(90_000, 100)),
    ]
    fp = FakeProvider(huge)
    agent = Agent(provider=fp, system="sys", max_iterations=10,
                  max_input_tokens=80_000)
    result = agent.run("burn budget")
    assert result.stop_reason == "max_tokens"
    assert result.iterations == 2


def test_agent_cumulative_spend_does_not_kill_long_tasks():
    # Regression: cumulative input across steps (150k) exceeds the cap, but
    # each individual step's context (50k) fits — the task must complete.
    steps = [
        StepResult(text=None,
                   tool_calls=[ToolCall(id=f"t{i}", name="bash",
                                        arguments={"command": "echo x"})],
                   stop_reason="tool_use", usage=_u(50_000, 100))
        for i in range(2)
    ]
    steps.append(StepResult(text="ok", tool_calls=[], stop_reason="end_turn",
                            usage=_u(50_000, 50)))
    fp = FakeProvider(steps)
    agent = Agent(provider=fp, system="sys", max_iterations=10,
                  max_input_tokens=80_000, verify=False)
    result = agent.run("long task")
    assert result.stop_reason == "end_turn"
    assert result.total_input_tokens == 150_000


def test_agent_reports_tool_error_back_to_model():
    """When dispatch raises ToolError, the loop continues with is_error=True
    in the tool_result, and the model gets to retry."""
    from nano.tools import ToolError

    fp = FakeProvider([
        StepResult(
            text="trying", tool_calls=[ToolCall(
                id="t1", name="read_file", arguments={"path": "no/such/file"})],
            stop_reason="tool_use", usage=_u(10, 5),
        ),
        StepResult(text="gave up", tool_calls=[], stop_reason="end_turn",
                   usage=_u(10, 5)),
    ])
    agent = Agent(provider=fp, system="sys", max_iterations=10, verify=False)
    result = agent.run("read missing file")

    assert result.stop_reason == "end_turn"
    assert result.iterations == 2
    second_call_msgs = fp.calls[1]["messages"]
    last_user = [m for m in second_call_msgs if m["role"] == "user"][-1]
    content = last_user["content"]
    assert isinstance(content, list)
    tr = content[0]
    assert tr["type"] == "tool_result"
    assert tr["is_error"] is True
    assert "ERROR" in tr["content"]


def test_agent_truncates_oldest_tool_result_when_history_grows():
    # Five tool_use rounds then a final end_turn. Truncation budget set so
    # the oldest tool_result must be replaced with a placeholder before the
    # last step is sent to the provider.
    big = "x" * 5000
    rounds = []
    for i in range(5):
        rounds.append(StepResult(
            text=f"step{i}",
            tool_calls=[ToolCall(id=f"t{i}", name="bash",
                                 arguments={"command": "echo " + big})],
            stop_reason="tool_use", usage=_u(100, 10)))
    rounds.append(StepResult(text="done", tool_calls=[], stop_reason="end_turn",
                             usage=_u(100, 10)))
    fp = FakeProvider(rounds)

    class _RecordingBash:
        def run(self, command, timeout=30):
            return command.removeprefix("echo ")

    agent = Agent(provider=fp, system="sys",
                  max_iterations=20, max_input_tokens=10**9,
                  bash=_RecordingBash(), verify=False)
    agent.truncation_char_budget = 8000  # forces truncation by step 4+
    result = agent.run("loop")

    assert result.stop_reason == "end_turn"
    truncations = [t for t in result.transcript if t.get("type") == "truncation"]
    assert truncations, "expected at least one truncation event"
    last_call_messages = fp.calls[-1]["messages"]
    seen_placeholder = any(
        isinstance(m.get("content"), list)
        and any(b.get("content", "").startswith("[truncated")
                for b in m["content"] if b.get("type") == "tool_result")
        for m in last_call_messages
    )
    assert seen_placeholder


def test_agent_nudges_continuation_when_output_truncated():
    # A response cut off by the output limit (stop_reason=max_tokens, no tool
    # calls) must not be reported as success — the loop nudges a continuation.
    fp = FakeProvider([
        StepResult(text="half a thou", tool_calls=[], stop_reason="max_tokens",
                   usage=_u(10, 4096)),
        StepResult(text="done", tool_calls=[], stop_reason="end_turn",
                   usage=_u(20, 5)),
    ])
    agent = Agent(provider=fp, system="sys", max_iterations=10)
    result = agent.run("long answer")

    assert result.stop_reason == "end_turn"
    assert result.iterations == 2
    second_call_msgs = fp.calls[1]["messages"]
    last_user = [m for m in second_call_msgs if m["role"] == "user"][-1]
    assert "cut off" in str(last_user["content"])


def test_agent_verify_pass_challenges_first_done():
    # After the model first claims done (having used tools), the loop injects
    # one verification nudge; the second end_turn is accepted.
    fp = FakeProvider([
        StepResult(text="fixing", tool_calls=[ToolCall(
            id="t1", name="bash", arguments={"command": "echo hi"})],
            stop_reason="tool_use", usage=_u(10, 5)),
        StepResult(text="done", tool_calls=[], stop_reason="end_turn",
                   usage=_u(20, 5)),
        StepResult(text="verified done", tool_calls=[], stop_reason="end_turn",
                   usage=_u(30, 5)),
    ])
    agent = Agent(provider=fp, system="sys", max_iterations=10)
    result = agent.run("fix the bug")

    assert result.stop_reason == "end_turn"
    assert result.iterations == 3
    assert result.final_text == "verified done"
    third_call_msgs = fp.calls[2]["messages"]
    last_user = [m for m in third_call_msgs if m["role"] == "user"][-1]
    assert "re-read the original task" in str(last_user["content"])


def test_agent_verify_pass_skipped_without_tool_use():
    # Pure text answer, no tools touched: nothing to verify, no extra step.
    fp = FakeProvider([
        StepResult(text="answer", tool_calls=[], stop_reason="end_turn",
                   usage=_u(10, 5)),
    ])
    agent = Agent(provider=fp, system="sys", max_iterations=10)
    result = agent.run("what is 2+2")
    assert result.iterations == 1
    assert result.final_text == "answer"


def test_agent_verify_pass_can_be_disabled():
    fp = FakeProvider([
        StepResult(text="working", tool_calls=[ToolCall(
            id="t1", name="bash", arguments={"command": "echo hi"})],
            stop_reason="tool_use", usage=_u(10, 5)),
        StepResult(text="done", tool_calls=[], stop_reason="end_turn",
                   usage=_u(20, 5)),
    ])
    agent = Agent(provider=fp, system="sys", max_iterations=10, verify=False)
    result = agent.run("fix it")
    assert result.iterations == 2
    assert result.final_text == "done"


def test_agent_emits_running_stats_each_step():
    # Token totals must survive an external kill - emitted every step,
    # not only in the final summary.
    events = []
    fp = FakeProvider([
        StepResult(text="working", tool_calls=[ToolCall(
            id="t1", name="bash", arguments={"command": "echo hi"})],
            stop_reason="tool_use", usage=_u(100, 20)),
        StepResult(text="done", tool_calls=[], stop_reason="end_turn",
                   usage=_u(150, 10)),
    ])
    agent = Agent(provider=fp, system="sys", max_iterations=10, verify=False,
                  on_event=events.append)
    agent.run("task")
    stats = [e for e in events if e["type"] == "stats"]
    assert len(stats) == 2
    assert stats[0] == {"type": "stats", "iteration": 1,
                        "input_tokens": 100, "output_tokens": 20}
    assert stats[1]["input_tokens"] == 250
