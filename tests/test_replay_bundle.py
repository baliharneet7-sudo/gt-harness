"""Provider-free tests for opt-in counterfactual replay capture."""

from __future__ import annotations

import json

from gt_engine.replay_bundle import ReplayBundleWriter


def _request() -> list[dict[str, str]]:
    return [{"role": "user", "content": "Fix app.py"}]


def test_capture_is_disabled_without_writing_an_artifact(tmp_path):
    writer = ReplayBundleWriter(tmp_path / "bundle.json", enabled=False)

    metadata = writer.finalize()

    assert metadata["enabled"] is False
    assert metadata["counterfactual_replay_ready"] is False
    assert not (tmp_path / "bundle.json").exists()


def test_capture_records_exact_requests_and_reports_missing_seed(tmp_path):
    path = tmp_path / "bundle.json"
    writer = ReplayBundleWriter(path, enabled=True)
    writer.record_request(
        call=1,
        provider_messages=_request(),
        request_payload_sha256="request-1",
        provider_messages_sha256="messages-1",
        model_name="test-model",
        model_kwargs={"temperature": 1.0},
        temperature=1.0,
        active_state={"source_revision": "s1"},
        source_revision="s1",
        workspace_revision="w1",
    )
    writer.record_response(call=1, response={"role": "assistant", "content": "ok"})

    metadata = writer.finalize()
    bundle = json.loads(path.read_text(encoding="utf-8"))

    assert metadata["complete"] is True
    assert metadata["request_bodies_captured"] is True
    assert metadata["responses_captured"] is True
    assert metadata["sampling_seed_available"] is False
    assert metadata["counterfactual_replay_ready"] is False
    assert bundle["calls"][0]["provider_messages"] == _request()


def test_capture_is_not_replay_ready_when_request_is_bounded_out(tmp_path):
    writer = ReplayBundleWriter(tmp_path / "bundle.json", enabled=True, max_call_chars=1_000)
    writer.record_request(
        call=1,
        provider_messages=[{"role": "user", "content": "x" * 2_000}],
        request_payload_sha256="request-1",
        provider_messages_sha256="messages-1",
        model_name="test-model",
        model_kwargs={"seed": 7},
        temperature=1.0,
        active_state={},
        source_revision="s1",
        workspace_revision="w1",
    )
    writer.record_response(call=1, response={"role": "assistant", "content": "ok"})

    metadata = writer.finalize()

    assert metadata["complete"] is False
    assert metadata["counterfactual_replay_ready"] is False
