from nano.providers import StepResult, ToolCall, Usage


def test_step_result_minimum_fields():
    sr = StepResult(
        text="hello",
        tool_calls=[ToolCall(id="c1", name="bash", arguments={"command": "ls"})],
        stop_reason="tool_use",
        usage=Usage(input_tokens=10, output_tokens=5, cache_read_tokens=0),
    )
    assert sr.text == "hello"
    assert sr.tool_calls[0].name == "bash"
    assert sr.tool_calls[0].arguments == {"command": "ls"}
    assert sr.stop_reason == "tool_use"
    assert sr.usage.input_tokens == 10


def test_step_result_text_only():
    sr = StepResult(text="done", tool_calls=[], stop_reason="end_turn",
                    usage=Usage(input_tokens=1, output_tokens=1, cache_read_tokens=0))
    assert sr.tool_calls == []
    assert sr.stop_reason == "end_turn"
