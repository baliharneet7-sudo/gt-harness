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


from unittest.mock import MagicMock

from nano.providers import AnthropicProvider


class _AnthroMsg:
    def __init__(self, content, stop_reason, usage):
        self.content = content
        self.stop_reason = stop_reason
        self.usage = usage


class _Block:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def _fake_anthropic_response_with_tool():
    return _AnthroMsg(
        content=[
            _Block(type="text", text="I'll list files."),
            _Block(type="tool_use", id="tu_1", name="bash",
                   input={"command": "ls"}),
        ],
        stop_reason="tool_use",
        usage=MagicMock(input_tokens=120, output_tokens=30,
                        cache_read_input_tokens=80, cache_creation_input_tokens=0),
    )


def test_anthropic_provider_translates_tool_use():
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_anthropic_response_with_tool()
    p = AnthropicProvider(model="claude-opus-4-7", client=fake_client)

    result = p.step(
        messages=[{"role": "user", "content": "list files"}],
        tools=[{"name": "bash", "description": "shell",
                "input_schema": {"type": "object", "properties": {
                    "command": {"type": "string"}}, "required": ["command"]}}],
        system="you help",
    )

    assert result.text == "I'll list files."
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].id == "tu_1"
    assert result.tool_calls[0].name == "bash"
    assert result.tool_calls[0].arguments == {"command": "ls"}
    assert result.stop_reason == "tool_use"
    assert result.usage.input_tokens == 120
    assert result.usage.cache_read_tokens == 80


def test_anthropic_provider_end_turn_text_only():
    msg = _AnthroMsg(
        content=[_Block(type="text", text="done")],
        stop_reason="end_turn",
        usage=MagicMock(input_tokens=5, output_tokens=2,
                        cache_read_input_tokens=0, cache_creation_input_tokens=0),
    )
    fake_client = MagicMock()
    fake_client.messages.create.return_value = msg
    p = AnthropicProvider(model="claude-opus-4-7", client=fake_client)

    result = p.step(messages=[{"role": "user", "content": "hi"}], tools=[], system="s")

    assert result.text == "done"
    assert result.tool_calls == []
    assert result.stop_reason == "end_turn"


def test_anthropic_provider_applies_cache_control_to_system_and_last_user():
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_anthropic_response_with_tool()
    p = AnthropicProvider(model="claude-opus-4-7", client=fake_client)

    p.step(
        messages=[
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "ack"},
            {"role": "user", "content": "second"},
        ],
        tools=[],
        system="SYS",
    )

    kwargs = fake_client.messages.create.call_args.kwargs
    sys_param = kwargs["system"]
    assert isinstance(sys_param, list)
    assert sys_param[0]["text"] == "SYS"
    assert sys_param[0]["cache_control"] == {"type": "ephemeral"}

    last_user = kwargs["messages"][-1]
    assert last_user["role"] == "user"
    last_block = last_user["content"][-1]
    assert last_block["cache_control"] == {"type": "ephemeral"}


def test_anthropic_provider_caches_last_user_not_last_message():
    # Mid-conversation: last message is assistant. Cache should still go on the
    # most recent user turn, not the assistant turn.
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_anthropic_response_with_tool()
    p = AnthropicProvider(model="claude-opus-4-7", client=fake_client)
    p.step(
        messages=[
            {"role": "user", "content": "do thing"},
            {"role": "assistant", "content": "thinking"},
        ],
        tools=[], system="s",
    )
    sent = fake_client.messages.create.call_args.kwargs["messages"]
    assert sent[0]["role"] == "user"
    assert sent[0]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in sent[1]["content"][-1]


import json as _json

from nano.providers import OpenAIProvider


def _fake_openai_response_with_tool():
    return MagicMock(
        choices=[MagicMock(
            message=MagicMock(
                content="I'll list.",
                tool_calls=[MagicMock(
                    id="call_1",
                    function=MagicMock(name="bash",
                                       arguments=_json.dumps({"command": "ls"})),
                )],
            ),
            finish_reason="tool_calls",
        )],
        usage=MagicMock(prompt_tokens=50, completion_tokens=20),
    )


def test_openai_provider_translates_tool_calls():
    # MagicMock auto-sets `.name`; force it to the literal string we want.
    resp = _fake_openai_response_with_tool()
    resp.choices[0].message.tool_calls[0].function.name = "bash"

    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = resp
    p = OpenAIProvider(model="gpt-5", client=fake_client)

    result = p.step(
        messages=[{"role": "user", "content": "list"}],
        tools=[{"name": "bash", "description": "shell",
                "input_schema": {"type": "object",
                                 "properties": {"command": {"type": "string"}},
                                 "required": ["command"]}}],
        system="sys",
    )

    assert result.text == "I'll list."
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].id == "call_1"
    assert result.tool_calls[0].name == "bash"
    assert result.tool_calls[0].arguments == {"command": "ls"}
    assert result.stop_reason == "tool_use"  # normalized from "tool_calls"
    assert result.usage.input_tokens == 50


def test_openai_provider_end_turn():
    resp = MagicMock(
        choices=[MagicMock(
            message=MagicMock(content="done", tool_calls=None),
            finish_reason="stop",
        )],
        usage=MagicMock(prompt_tokens=3, completion_tokens=1),
    )
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = resp
    p = OpenAIProvider(model="gpt-5", client=fake_client)

    result = p.step(messages=[{"role": "user", "content": "hi"}], tools=[], system="s")

    assert result.text == "done"
    assert result.tool_calls == []
    assert result.stop_reason == "end_turn"  # normalized from "stop"


def test_openai_provider_translates_tool_schema_to_openai_format():
    resp = MagicMock(
        choices=[MagicMock(
            message=MagicMock(content="hi", tool_calls=None),
            finish_reason="stop",
        )],
        usage=MagicMock(prompt_tokens=1, completion_tokens=1),
    )
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = resp
    p = OpenAIProvider(model="gpt-5", client=fake_client)

    p.step(
        messages=[{"role": "user", "content": "x"}],
        tools=[{"name": "bash", "description": "shell",
                "input_schema": {"type": "object",
                                 "properties": {"command": {"type": "string"}},
                                 "required": ["command"]}}],
        system="SYS",
    )

    kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert kwargs["messages"][0] == {"role": "system", "content": "SYS"}
    sent_tool = kwargs["tools"][0]
    assert sent_tool["type"] == "function"
    assert sent_tool["function"]["name"] == "bash"
    assert sent_tool["function"]["parameters"]["required"] == ["command"]


def test_normalize_assistant_for_openai_round_trips_tool_calls():
    from nano.providers import _normalize_assistant_for_openai
    out = _normalize_assistant_for_openai({
        "role": "assistant",
        "content": [{"type": "text", "text": "I'll list."},
                    {"type": "tool_use", "id": "tu_1", "name": "bash",
                     "input": {"command": "ls"}}],
        "tool_calls": [{"id": "tu_1", "name": "bash",
                        "arguments": {"command": "ls"}}],
    })
    assert out["content"] == "I'll list."  # tool_use block dropped from content
    assert out["tool_calls"][0]["function"]["name"] == "bash"
    assert out["tool_calls"][0]["function"]["arguments"] == '{"command": "ls"}'
