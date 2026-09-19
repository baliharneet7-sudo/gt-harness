"""The model probe: check a host's request surface (tokenizer, template, tools,
thinking, fp8) against the baseline before any paid run. It does not prove weights.

Every test here is offline. The one function that touches the network,
``model_identity_probe._post_chat``, is replaced; a test that reached the real
transport would fail on the sentinel below rather than spend.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts import extract_model_identity_refs as extractor
from scripts import model_identity_probe as probe

ROOT = Path(__file__).resolve().parents[1]
ROUTE = ROOT / "config" / "provider_route_deepseek_v4_flash_0731_fp8.v1.json"
COMMITTED_REFS = ROOT / "config" / "model_identity_refs.v1.json"
FAKE_KEY = "sk-or-v1-THIS-KEY-MUST-NEVER-BE-PRINTED-0123456789"
FINGERPRINT = "fp_a18b46594c_prod0820_fp8_kvcache_20260402"


@pytest.fixture(autouse=True)
def _no_real_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    """A test that forgets to install a fake transport must not reach urllib."""

    def refuse(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("real network transport reached in an offline test")

    monkeypatch.setattr(probe.urllib.request, "urlopen", refuse)


# --------------------------------------------------------------------------
# Synthetic refs and a scripted fake provider
# --------------------------------------------------------------------------


def _ref(task: str, prompt_tokens: int, reasoning: int = 20) -> dict[str, Any]:
    return {
        "task": task,
        "prompt_tokens": prompt_tokens,
        "reasoning_tokens": reasoning,
        "cached_tokens": 0,
        "source_trajectory": f"matrix_cache/{task}/job/{task}__x/agent/miniswe_trajectory.json",
        "source_sha256": "0" * 64,
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": f"Please solve this issue: {task}"},
        ],
    }


def _write_refs(tmp_path: Path, count: int = 6) -> Path:
    doc = {
        "schema": "gt.model_identity_refs.v1",
        "baseline_id": "miniswe_tb2_gtoff_20260731",
        "served_snapshot": "DeepSeek-V4-Flash-0731",
        "served_model": "deepseek-v4-flash",
        "system_fingerprint": FINGERPRINT,
        "baseline_temperature": 1.0,
        "tools": extractor.BASH_TOOLS,
        "extracted_at": "2026-09-19T00:00:00Z",
        "refs": [_ref(f"task-{i}", 1100 + 10 * i) for i in range(count)],
    }
    path = tmp_path / "refs.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def _response(
    *,
    prompt_tokens: int | None,
    reasoning_tokens: int | None = 12,
    cached: int | None = 0,
    content: str = "",
    reasoning_text: str | None = "Let me look.",
    usage: bool = True,
) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if reasoning_text is not None:
        message["reasoning"] = reasoning_text
    payload: dict[str, Any] = {
        "id": "gen-1",
        "model": "deepseek/deepseek-v4-flash-0731",
        "provider": "StreamLake",
        "system_fingerprint": None,
        "choices": [{"index": 0, "message": message, "finish_reason": "length"}],
    }
    if usage:
        body: dict[str, Any] = {"completion_tokens": 64}
        if prompt_tokens is not None:
            body["prompt_tokens"] = prompt_tokens
        if reasoning_tokens is not None:
            body["completion_tokens_details"] = {"reasoning_tokens": reasoning_tokens}
        if cached is not None:
            body["prompt_tokens_details"] = {"cached_tokens": cached}
        payload["usage"] = body
    return payload


class FakeProvider:
    """Answers each replay with the ref's own prompt_tokens unless told otherwise."""

    def __init__(self, refs_path: Path, **overrides: Any) -> None:
        refs = json.loads(refs_path.read_text(encoding="utf-8"))["refs"]
        self.expected = {r["messages"][1]["content"]: r["prompt_tokens"] for r in refs}
        self.task_of = {r["messages"][1]["content"]: r["task"] for r in refs}
        self.overrides = overrides
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, api_key: str, body: dict[str, Any]) -> dict[str, Any]:
        self.calls.append({"url": url, "api_key": api_key, "body": json.loads(json.dumps(body))})
        user = body["messages"][1]["content"]
        task = self.task_of[user]
        seen_before = sum(1 for c in self.calls if c["body"]["messages"][1]["content"] == user)
        prompt = self.expected[user] + self.overrides.get("offset", {}).get(task, 0)
        if self.overrides.get("no_usage"):
            return _response(prompt_tokens=None, usage=False)
        if self.overrides.get("no_prompt_tokens"):
            return _response(prompt_tokens=None)
        reasoning = 0 if self.overrides.get("no_reasoning") else 12
        text = (
            None
            if self.overrides.get("no_reasoning")
            else self.overrides.get("reasoning", "Let me look.")
        )
        cached = self.overrides.get("cached", 1024 if seen_before > 1 else 0)
        content = self.overrides.get("content", {}).get(task, "")
        if seen_before > 1 and "repeat_content" in self.overrides:
            content = self.overrides["repeat_content"]
        payload = _response(
            prompt_tokens=prompt,
            reasoning_tokens=reasoning,
            reasoning_text=text,
            cached=cached,
            content=content,
        )
        payload["system_fingerprint"] = self.overrides.get("fingerprint")
        return payload


def _run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    fake: Any,
    *extra: str,
    refs: Path | None = None,
    key_env: str = "OPENROUTER_API_KEY",
    key: str | None = FAKE_KEY,
) -> tuple[int, dict[str, Any], str]:
    refs = refs or _write_refs(tmp_path)
    out = tmp_path / "receipt.json"
    monkeypatch.setattr(probe, "_post_chat", fake)
    if key is None:
        monkeypatch.delenv(key_env, raising=False)
    else:
        monkeypatch.setenv(key_env, key)
    rc = probe.main(["--route", str(ROUTE), "--refs", str(refs), "--json", str(out), *extra])
    captured = capsys.readouterr()
    receipt = json.loads(out.read_text(encoding="utf-8"))
    return rc, receipt, captured.out + captured.err


# --------------------------------------------------------------------------
# tokenizer
# --------------------------------------------------------------------------


def test_exact_prompt_token_match_passes(tmp_path, monkeypatch, capsys):
    fake = FakeProvider(_write_refs(tmp_path))
    rc, receipt, _ = _run(tmp_path, monkeypatch, capsys, fake, "--provider", "streamlake")

    assert rc == 0
    assert receipt["schema"] == "gt.model_identity.v1"
    assert receipt["status"] == "CONFORMS"
    assert receipt["checks"]["tokenizer"]["severity"] == "PASS"
    assert receipt["checks"]["thinking"]["severity"] == "PASS"
    # Default count 5 replays + 1 cache repeat of ref 0.
    assert len(fake.calls) == 6
    assert fake.calls[-1]["body"] == fake.calls[0]["body"]
    for call in fake.calls:
        assert call["body"]["temperature"] == 0
        assert call["body"]["max_tokens"] == 64
        assert call["body"]["tools"] == extractor.BASH_TOOLS


def test_off_by_one_prompt_tokens_fails_naming_the_task(tmp_path, monkeypatch, capsys):
    fake = FakeProvider(_write_refs(tmp_path), offset={"task-2": 1})
    rc, receipt, output = _run(tmp_path, monkeypatch, capsys, fake)

    assert rc == 1
    assert receipt["status"] == "NONCONFORMING"
    tokenizer = receipt["checks"]["tokenizer"]
    assert tokenizer["severity"] == "FAIL"
    assert tokenizer["mismatches"] == [{"task": "task-2", "expected": 1120, "got": 1121}]
    assert "task-2" in tokenizer["message"]
    assert "1120" in tokenizer["message"] and "1121" in tokenizer["message"]
    assert "task-2" in output


def test_missing_usage_is_unknown_and_unresolved(tmp_path, monkeypatch, capsys):
    fake = FakeProvider(_write_refs(tmp_path), no_usage=True)
    rc, receipt, _ = _run(tmp_path, monkeypatch, capsys, fake)

    assert rc == 2
    assert receipt["status"] == "UNRESOLVED"
    assert receipt["checks"]["tokenizer"]["severity"] == "UNKNOWN"
    assert receipt["checks"]["thinking"]["severity"] in {"UNKNOWN", "PASS"}


def test_missing_prompt_tokens_alone_is_unknown(tmp_path, monkeypatch, capsys):
    fake = FakeProvider(_write_refs(tmp_path), no_prompt_tokens=True)
    rc, receipt, _ = _run(tmp_path, monkeypatch, capsys, fake)

    assert rc == 2
    assert receipt["checks"]["tokenizer"]["severity"] == "UNKNOWN"


# --------------------------------------------------------------------------
# thinking
# --------------------------------------------------------------------------


def test_no_reasoning_tokens_fails_thinking(tmp_path, monkeypatch, capsys):
    fake = FakeProvider(_write_refs(tmp_path), no_reasoning=True)
    rc, receipt, _ = _run(tmp_path, monkeypatch, capsys, fake)

    assert rc == 1
    assert receipt["checks"]["tokenizer"]["severity"] == "PASS"
    assert receipt["checks"]["thinking"]["severity"] == "FAIL"
    assert "thinking" in receipt["checks"]["thinking"]["message"]


def test_reasoning_text_alone_counts_as_thinking(tmp_path, monkeypatch, capsys):
    refs = _write_refs(tmp_path)
    base = FakeProvider(refs)

    def fake(url, api_key, body):
        payload = base(url, api_key, body)
        payload["usage"].pop("completion_tokens_details")
        payload["choices"][0]["message"].pop("reasoning")
        payload["choices"][0]["message"]["reasoning_content"] = "thinking..."
        return payload

    rc, receipt, _ = _run(tmp_path, monkeypatch, capsys, fake, refs=refs)

    assert rc == 0
    assert receipt["checks"]["thinking"]["severity"] == "PASS"


# --------------------------------------------------------------------------
# failure modes that must resolve to rc 2 with a receipt
# --------------------------------------------------------------------------


def test_network_error_is_unresolved_with_receipt_written(tmp_path, monkeypatch, capsys):
    def fake(url, api_key, body):
        raise probe.ProbeError("provider_transport_failed")

    rc, receipt, _ = _run(tmp_path, monkeypatch, capsys, fake)

    assert rc == 2
    assert receipt["status"] == "UNRESOLVED"
    assert receipt["error_code"] == "provider_transport_failed"
    assert receipt["checks"]["tokenizer"]["severity"] == "UNKNOWN"


def test_real_urllib_failure_maps_to_a_closed_code(tmp_path, monkeypatch):
    import urllib.error

    def boom(*_args, **_kwargs):
        raise urllib.error.URLError("dns")

    monkeypatch.setattr(probe.urllib.request, "urlopen", boom)
    with pytest.raises(probe.ProbeError, match="provider_transport_failed"):
        probe._post_chat("https://openrouter.ai/api/v1/chat/completions", FAKE_KEY, {})


def test_cap_exceeded_refuses_before_any_call(tmp_path, monkeypatch, capsys):
    fake = FakeProvider(_write_refs(tmp_path))
    rc, receipt, _ = _run(tmp_path, monkeypatch, capsys, fake, "--max-input-tokens", "1000")

    assert rc == 2
    assert fake.calls == []
    assert receipt["error_code"] == "spend_cap_exceeded"
    assert receipt["planned_input_tokens"] == sum(1100 + 10 * i for i in range(5)) + 1100
    assert receipt["calls"] == []


def test_missing_key_is_unresolved_with_zero_calls(tmp_path, monkeypatch, capsys):
    fake = FakeProvider(_write_refs(tmp_path))
    rc, receipt, _ = _run(tmp_path, monkeypatch, capsys, fake, key=None)

    assert rc == 2
    assert fake.calls == []
    assert receipt["error_code"] == "provider_credential_missing"


def test_count_larger_than_refs_is_refused(tmp_path, monkeypatch, capsys):
    fake = FakeProvider(_write_refs(tmp_path, count=3))
    rc, receipt, _ = _run(
        tmp_path, monkeypatch, capsys, fake, "--count", "5", refs=_write_refs(tmp_path, 3)
    )

    assert rc == 2
    assert fake.calls == []
    assert receipt["error_code"] == "refs_count_exceeds_available"


def test_key_never_appears_in_receipt_or_stdio(tmp_path, monkeypatch, capsys):
    fake = FakeProvider(_write_refs(tmp_path), offset={"task-0": 3})
    rc, receipt, output = _run(tmp_path, monkeypatch, capsys, fake)

    assert rc == 1
    assert fake.calls and fake.calls[0]["api_key"] == FAKE_KEY
    raw = (tmp_path / "receipt.json").read_text(encoding="utf-8")
    assert FAKE_KEY not in raw
    assert FAKE_KEY not in output
    assert receipt["credential_env"] == "OPENROUTER_API_KEY"


# --------------------------------------------------------------------------
# request shape
# --------------------------------------------------------------------------


def test_openrouter_provider_only_body_is_sent_exactly(tmp_path, monkeypatch, capsys):
    fake = FakeProvider(_write_refs(tmp_path))
    rc, receipt, _ = _run(tmp_path, monkeypatch, capsys, fake, "--provider", "baidu")

    assert rc == 0
    for call in fake.calls:
        assert call["url"] == "https://openrouter.ai/api/v1/chat/completions"
        assert call["body"]["model"] == "deepseek/deepseek-v4-flash-0731"
        assert call["body"]["provider"] == {
            "only": ["baidu"],
            "quantizations": ["fp8"],
            "allow_fallbacks": False,
            "require_parameters": True,
        }
        assert set(call["body"]) == {
            "model",
            "messages",
            "tools",
            "temperature",
            "max_tokens",
            "provider",
        }
    assert receipt["provider_routing"]["only"] == ["baidu"]
    assert receipt["scope"] == [
        "tokenizer_template_tools",
        "thinking_on_every_replay",
        "fp8_requested",
    ]
    assert receipt["does_not_prove"] == ["weights"]
    assert "native_fingerprint" not in receipt["checks"]
    # The route's price is DeepInfra's; the receipt must say so under --provider.
    assert receipt["pricing_provider"] == "deepinfra"


def test_route_manifest_provider_is_the_default(tmp_path, monkeypatch, capsys):
    fake = FakeProvider(_write_refs(tmp_path))
    _run(tmp_path, monkeypatch, capsys, fake)

    assert fake.calls[0]["body"]["provider"]["only"] == ["deepinfra"]


def test_invalid_provider_slug_is_refused(tmp_path, monkeypatch, capsys):
    fake = FakeProvider(_write_refs(tmp_path))
    rc, receipt, _ = _run(tmp_path, monkeypatch, capsys, fake, "--provider", "a b/../c")

    assert rc == 2
    assert fake.calls == []
    assert receipt["error_code"] == "provider_slug_invalid"


def test_native_override_sends_no_provider_object(tmp_path, monkeypatch, capsys):
    fake = FakeProvider(_write_refs(tmp_path), fingerprint=FINGERPRINT)
    rc, receipt, output = _run(
        tmp_path,
        monkeypatch,
        capsys,
        fake,
        "--base-url",
        "https://api.deepseek.com",
        "--model",
        "deepseek-flash",
        "--key-env",
        "DEEPSEEK_API_KEY",
        key_env="DEEPSEEK_API_KEY",
    )

    assert rc == 0
    for call in fake.calls:
        assert call["url"] == "https://api.deepseek.com/chat/completions"
        assert call["body"]["model"] == "deepseek-flash"
        assert "provider" not in call["body"]
    assert receipt["provider_routing"] is None
    assert receipt["override"] is True
    assert receipt["credential_env"] == "DEEPSEEK_API_KEY"
    # The route's OpenRouter price does not apply to a different host.
    assert receipt["pricing_source"] is None
    assert receipt["checks"]["native_fingerprint"]["severity"] == "PASS"
    assert "fp8_requested" not in receipt["scope"]
    assert receipt["does_not_prove"] == ["weights"]
    assert FAKE_KEY not in output


def test_override_to_an_unlisted_host_is_refused(tmp_path, monkeypatch, capsys):
    fake = FakeProvider(_write_refs(tmp_path))
    rc, receipt, _ = _run(
        tmp_path,
        monkeypatch,
        capsys,
        fake,
        "--base-url",
        "https://evil.example.com",
        "--model",
        "x",
        "--key-env",
        "DEEPSEEK_API_KEY",
        key_env="DEEPSEEK_API_KEY",
    )

    assert rc == 2
    assert fake.calls == []
    assert receipt["error_code"] == "override_host_not_allowed"


def test_partial_override_is_refused(tmp_path, monkeypatch, capsys):
    fake = FakeProvider(_write_refs(tmp_path))
    rc, receipt, _ = _run(
        tmp_path, monkeypatch, capsys, fake, "--base-url", "https://api.deepseek.com"
    )

    assert rc == 2
    assert fake.calls == []
    assert receipt["error_code"] == "override_incomplete"


# --------------------------------------------------------------------------
# caching, served identity, cost
# --------------------------------------------------------------------------


def test_caching_zero_is_a_warning_never_a_verdict(tmp_path, monkeypatch, capsys):
    fake = FakeProvider(_write_refs(tmp_path), cached=0)
    rc, receipt, _ = _run(tmp_path, monkeypatch, capsys, fake)

    assert rc == 0
    caching = receipt["checks"]["caching"]
    assert caching["severity"] == "WARNING"
    assert caching["cached_tokens"] == 0
    assert caching["message"] == (
        "no prompt caching observed; cost estimates must assume full input price"
    )


def test_caching_observed_is_ok(tmp_path, monkeypatch, capsys):
    fake = FakeProvider(_write_refs(tmp_path))
    _, receipt, _ = _run(tmp_path, monkeypatch, capsys, fake)

    assert receipt["checks"]["caching"]["severity"] == "OK"
    assert receipt["checks"]["caching"]["cached_tokens"] == 1024


def test_served_identity_and_cost_are_recorded(tmp_path, monkeypatch, capsys):
    fake = FakeProvider(_write_refs(tmp_path))
    _, receipt, _ = _run(tmp_path, monkeypatch, capsys, fake)

    served = receipt["checks"]["served_identity"]
    assert served["severity"] == "INFO"
    assert served["providers"] == ["StreamLake"]
    assert served["models"] == ["deepseek/deepseek-v4-flash-0731"]
    assert receipt["pricing_source"] == "route_manifest"
    first = receipt["calls"][0]
    assert first["prompt_tokens"] == 1100
    assert first["completion_tokens"] == 64
    assert first["estimated_cost_usd"] == pytest.approx(1100 * 6e-8 + 64 * 1.8e-7)
    assert receipt["totals"]["estimated_cost_usd"] == pytest.approx(
        sum(c["estimated_cost_usd"] for c in receipt["calls"])
    )


# --------------------------------------------------------------------------
# annotations
# --------------------------------------------------------------------------


def test_workflow_command_lines_are_single_escaped_lines(tmp_path, monkeypatch, capsys):
    refs = tmp_path / "refs.json"
    doc = json.loads(_write_refs(tmp_path).read_text(encoding="utf-8"))
    doc["refs"][0]["task"] = "evil\n::stop-commands::x"
    refs.write_text(json.dumps(doc), encoding="utf-8")
    fake = FakeProvider(refs, offset={"evil\n::stop-commands::x": 1})
    rc, _, output = _run(tmp_path, monkeypatch, capsys, fake, refs=refs)

    assert rc == 1
    command_lines = [line for line in output.splitlines() if line.startswith("::")]
    assert command_lines, output
    assert all(line.startswith(("::error", "::warning")) for line in command_lines)


# --------------------------------------------------------------------------
# review follow-ups: verdict wording, fp8, self-consistency, robustness
# --------------------------------------------------------------------------


def test_under_count_prompt_tokens_also_fails(tmp_path, monkeypatch, capsys):
    fake = FakeProvider(_write_refs(tmp_path), offset={"task-1": -1})
    rc, receipt, _ = _run(tmp_path, monkeypatch, capsys, fake)

    assert rc == 1
    assert receipt["status"] == "NONCONFORMING"
    assert receipt["checks"]["tokenizer"]["mismatches"] == [
        {"task": "task-1", "expected": 1110, "got": 1109}
    ]


def test_mismatch_then_network_error_is_still_rc_1(tmp_path, monkeypatch, capsys):
    refs = _write_refs(tmp_path)
    base = FakeProvider(refs, offset={"task-0": 2})

    def fake(url, api_key, body):
        if len(base.calls) >= 2:
            raise probe.ProbeError("provider_transport_failed")
        return base(url, api_key, body)

    rc, receipt, _ = _run(tmp_path, monkeypatch, capsys, fake, refs=refs)

    assert rc == 1
    assert receipt["status"] == "NONCONFORMING"
    assert receipt["error_code"] == "provider_transport_failed"
    assert receipt["provider_calls"] == 2


def test_verdict_never_claims_weights(tmp_path, monkeypatch, capsys):
    fake = FakeProvider(_write_refs(tmp_path))
    rc, receipt, output = _run(tmp_path, monkeypatch, capsys, fake)

    assert rc == 0
    assert receipt["status"] == "CONFORMS"
    assert receipt["does_not_prove"] == ["weights"]
    assert "identity PASS" not in output
    assert "does not prove" in probe.__doc__.lower()
    assert "weights" in probe.__doc__


def test_openrouter_sends_the_route_quantization(tmp_path, monkeypatch, capsys):
    fake = FakeProvider(_write_refs(tmp_path))
    _run(tmp_path, monkeypatch, capsys, fake)

    assert fake.calls[0]["body"]["provider"] == {
        "only": ["deepinfra"],
        "quantizations": ["fp8"],
        "allow_fallbacks": False,
        "require_parameters": True,
    }


def _native(tmp_path, monkeypatch, capsys, fake):
    return _run(
        tmp_path,
        monkeypatch,
        capsys,
        fake,
        "--base-url",
        "https://api.deepseek.com",
        "--model",
        "deepseek-flash",
        "--key-env",
        "DEEPSEEK_API_KEY",
        key_env="DEEPSEEK_API_KEY",
    )


def test_native_fingerprint_mismatch_fails(tmp_path, monkeypatch, capsys):
    fake = FakeProvider(_write_refs(tmp_path), fingerprint="fp_v41_prod0910")
    rc, receipt, _ = _native(tmp_path, monkeypatch, capsys, fake)

    assert rc == 1
    assert receipt["status"] == "NONCONFORMING"
    check = receipt["checks"]["native_fingerprint"]
    assert check["severity"] == "FAIL"
    assert check["expected"] == FINGERPRINT
    assert check["observed"] == ["fp_v41_prod0910"]


def test_native_fingerprint_missing_fails(tmp_path, monkeypatch, capsys):
    fake = FakeProvider(_write_refs(tmp_path))
    rc, receipt, _ = _native(tmp_path, monkeypatch, capsys, fake)

    assert rc == 1
    assert receipt["checks"]["native_fingerprint"]["severity"] == "FAIL"


def test_thinking_must_hold_on_every_replay(tmp_path, monkeypatch, capsys):
    refs = _write_refs(tmp_path)
    base = FakeProvider(refs)

    def fake(url, api_key, body):
        payload = base(url, api_key, body)
        if body["messages"][1]["content"].endswith("task-3"):
            payload["usage"]["completion_tokens_details"]["reasoning_tokens"] = 0
            payload["choices"][0]["message"].pop("reasoning")
        return payload

    rc, receipt, _ = _run(tmp_path, monkeypatch, capsys, fake, refs=refs)

    assert rc == 1
    thinking = receipt["checks"]["thinking"]
    assert thinking["severity"] == "FAIL"
    assert thinking["tasks_without_reasoning"] == ["task-3"]


def test_http_client_exception_maps_to_a_closed_code(monkeypatch):
    import http.client

    def boom(*_args, **_kwargs):
        raise http.client.IncompleteRead(b"partial")

    monkeypatch.setattr(probe.urllib.request, "urlopen", boom)
    with pytest.raises(probe.ProbeError, match="provider_transport_failed"):
        probe._post_chat("https://openrouter.ai/api/v1/chat/completions", FAKE_KEY, {})


def _tool_calls_not_a_list(payload):
    payload["choices"][0]["message"]["tool_calls"] = {"a": 1}


def _unhashable_model(payload):
    payload["model"] = {"unhashable": ["x"]}


def _details_not_a_dict(payload):
    payload["usage"]["completion_tokens_details"] = 7


def _choices_garbage(payload):
    payload["choices"] = "garbage"


@pytest.mark.parametrize(
    "mutate",
    [_tool_calls_not_a_list, _unhashable_model, _details_not_a_dict, _choices_garbage],
)
def test_malformed_response_fields_never_escape_as_a_traceback(
    tmp_path, monkeypatch, capsys, mutate
):
    refs = _write_refs(tmp_path)
    base = FakeProvider(refs)

    def fake(url, api_key, body):
        payload = base(url, api_key, body)
        mutate(payload)
        return payload

    rc, receipt, _ = _run(tmp_path, monkeypatch, capsys, fake, refs=refs)

    assert rc in (0, 1, 2)
    assert receipt["status"] in {"CONFORMS", "UNRESOLVED", "NONCONFORMING"}


def test_unexpected_record_failure_is_provider_response_invalid(tmp_path, monkeypatch, capsys):
    def explode(*_args, **_kwargs):
        raise KeyError("surprise")

    monkeypatch.setattr(probe, "_call_record", explode)
    fake = FakeProvider(_write_refs(tmp_path))
    rc, receipt, _ = _run(tmp_path, monkeypatch, capsys, fake)

    assert rc == 2
    assert receipt["status"] == "UNRESOLVED"
    assert receipt["error_code"] == "provider_response_invalid"


class _Body:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._raw = json.dumps(payload).encode()

    def read(self, *_args: Any) -> bytes:
        return self._raw

    def __enter__(self) -> _Body:
        return self

    def __exit__(self, *_exc: Any) -> bool:
        return False


def test_error_body_on_http_200_surfaces_its_code(monkeypatch):
    url = "https://openrouter.ai/api/v1/chat/completions"
    limited = _Body({"error": {"code": 429, "message": "slow down"}})
    monkeypatch.setattr(probe.urllib.request, "urlopen", lambda *_a, **_k: limited)
    with pytest.raises(probe.ProbeError, match="provider_rate_limited"):
        probe._post_chat(url, FAKE_KEY, {})

    other = _Body({"error": {"code": "no_endpoints", "message": "x"}})
    monkeypatch.setattr(probe.urllib.request, "urlopen", lambda *_a, **_k: other)
    with pytest.raises(probe.ProbeError, match="provider_error_body"):
        probe._post_chat(url, FAKE_KEY, {})

    upstream = _Body({"error": {"code": 502, "message": "x"}})
    monkeypatch.setattr(probe.urllib.request, "urlopen", lambda *_a, **_k: upstream)
    with pytest.raises(probe.ProbeError, match="provider_error_502"):
        probe._post_chat(url, FAKE_KEY, {})


# --------------------------------------------------------------------------
# re-review follow-ups: scope/proven, fingerprints, quantization note
# --------------------------------------------------------------------------


def test_proven_is_the_scope_only_when_the_host_conforms(tmp_path, monkeypatch, capsys):
    fake = FakeProvider(_write_refs(tmp_path))
    rc, receipt, _ = _run(tmp_path, monkeypatch, capsys, fake)

    assert rc == 0
    assert "proves" not in receipt
    assert receipt["proven"] == receipt["scope"]
    assert receipt["scope"][0] == "tokenizer_template_tools"


def test_nothing_is_proven_when_the_host_does_not_conform(tmp_path, monkeypatch, capsys):
    fake = FakeProvider(_write_refs(tmp_path), offset={"task-0": 1})
    rc, receipt, _ = _run(tmp_path, monkeypatch, capsys, fake)

    assert rc == 1
    assert receipt["scope"]
    assert receipt["proven"] == []


def test_nothing_is_proven_when_unresolved(tmp_path, monkeypatch, capsys):
    fake = FakeProvider(_write_refs(tmp_path))
    rc, receipt, _ = _run(tmp_path, monkeypatch, capsys, fake, key=None)

    assert rc == 2
    assert receipt["proven"] == []


def test_mixed_native_fingerprints_fail(tmp_path, monkeypatch, capsys):
    base = FakeProvider(_write_refs(tmp_path), fingerprint=FINGERPRINT)

    def fake(url, api_key, body):
        payload = base(url, api_key, body)
        if len(base.calls) == 3:
            payload["system_fingerprint"] = "fp_v41_prod0910"
        return payload

    rc, receipt, _ = _native(tmp_path, monkeypatch, capsys, fake)

    assert rc == 1
    check = receipt["checks"]["native_fingerprint"]
    assert check["severity"] == "FAIL"
    assert check["observed"] == [FINGERPRINT, "fp_v41_prod0910"]
    assert receipt["checks"]["served_identity"]["fingerprint_matches_baseline"] is False


def test_a_missing_fingerprint_does_not_match_the_baseline(tmp_path, monkeypatch, capsys):
    base = FakeProvider(_write_refs(tmp_path), fingerprint=FINGERPRINT)

    def fake(url, api_key, body):
        payload = base(url, api_key, body)
        if len(base.calls) == 2:
            payload["system_fingerprint"] = None
        return payload

    rc, receipt, _ = _native(tmp_path, monkeypatch, capsys, fake)

    assert rc == 1
    assert receipt["checks"]["native_fingerprint"]["severity"] == "FAIL"
    assert receipt["checks"]["served_identity"]["fingerprint_matches_baseline"] is False


def test_all_fingerprints_baseline_matches(tmp_path, monkeypatch, capsys):
    fake = FakeProvider(_write_refs(tmp_path), fingerprint=FINGERPRINT)
    rc, receipt, _ = _native(tmp_path, monkeypatch, capsys, fake)

    assert rc == 0
    assert receipt["checks"]["served_identity"]["fingerprint_matches_baseline"] is True


def test_docstring_states_the_unknown_quantization_divergence():
    doc = probe.__doc__

    assert "provider_preflight" in doc
    assert "``unknown``" in doc
