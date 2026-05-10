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
    agent = Agent(provider=fp, system="sys", max_iterations=10)
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


def test_agent_token_cap_stops_loop():
    huge = [
        StepResult(text=None,
                   tool_calls=[ToolCall(id="t1", name="bash",
                                        arguments={"command": "echo x"})],
                   stop_reason="tool_use", usage=_u(50_000, 100)),
        StepResult(text="ok", tool_calls=[], stop_reason="end_turn", usage=_u(50_000, 50)),
    ]
    fp = FakeProvider(huge)
    agent = Agent(provider=fp, system="sys", max_iterations=10,
                  max_input_tokens=80_000)
    result = agent.run("burn budget")
    assert result.stop_reason == "max_tokens"


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
    agent = Agent(provider=fp, system="sys", max_iterations=10)
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
