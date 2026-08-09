"""Bounded, opt-in capture of provider requests for counterfactual replay.

The normal paid workflow keeps this disabled.  When explicitly enabled, the
writer stores exact prepared provider messages and the corresponding model
response metadata in a separate artifact.  It never alters the provider
request.  A bundle is trajectory-replay-ready only when every request/response
is captured without truncation. It never injects or requires provider-specific
sampling controls; model-level causal reaction remains explicitly
unidentifiable.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _safe_model_kwargs(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    redacted: dict[str, Any] = {}
    for key, item in value.items():
        lowered = str(key).lower()
        if any(marker in lowered for marker in ("key", "token", "secret", "authorization")):
            redacted[str(key)] = "<redacted>"
        else:
            redacted[str(key)] = item
    return redacted


def _response_projection(response: Any) -> dict[str, Any]:
    if not isinstance(response, dict):
        return {"value": str(response)}
    extra = response.get("extra") or {}
    return {
        "role": response.get("role"),
        "content": response.get("content"),
        "reasoning_content": response.get("reasoning_content"),
        "tool_calls": response.get("tool_calls"),
        "function_call": response.get("function_call"),
        "extra": {
            "actions": extra.get("actions"),
            "response": extra.get("response"),
            "cost": extra.get("cost"),
        },
    }


class ReplayBundleWriter:
    """Write one bounded replay artifact without changing runtime behavior."""

    def __init__(
        self,
        path: Path,
        *,
        enabled: bool,
        max_call_chars: int = 500_000,
        max_bundle_bytes: int = 25_000_000,
    ) -> None:
        self.path = path
        self.enabled = bool(enabled)
        self.max_call_chars = max(1_000, int(max_call_chars))
        self.max_bundle_bytes = max(10_000, int(max_bundle_bytes))
        self._calls: dict[int, dict[str, Any]] = {}
        self._complete = self.enabled
        self._bytes_estimate = 0

    def record_request(
        self,
        *,
        call: int,
        provider_messages: list[dict[str, Any]],
        request_payload_sha256: str,
        provider_messages_sha256: str,
        model_name: str,
        model_kwargs: Any,
        temperature: float,
        active_state: dict[str, Any],
        source_revision: str,
        workspace_revision: str,
    ) -> None:
        if not self.enabled:
            return
        body = _canonical(provider_messages)
        row: dict[str, Any] = {
            "call": int(call),
            "request_payload_sha256": str(request_payload_sha256),
            "provider_messages_sha256": str(provider_messages_sha256),
            "provider_request_chars": len(body.decode("utf-8")),
            "model_name": str(model_name),
            "model_kwargs": _safe_model_kwargs(model_kwargs),
            "sampling": {"temperature": float(temperature)},
            "source_revision": str(source_revision),
            "workspace_revision": str(workspace_revision),
            "controller_state": active_state,
            "request_captured": False,
            "response_captured": False,
        }
        if len(body) > self.max_call_chars or (
            self._bytes_estimate + len(body) > self.max_bundle_bytes
        ):
            self._complete = False
            row["request_omitted"] = True
            row["request_sha256"] = hashlib.sha256(body).hexdigest()
        else:
            row["provider_messages"] = provider_messages
            row["request_captured"] = True
            self._bytes_estimate += len(body)
        self._calls[int(call)] = row

    def record_response(self, *, call: int, response: Any) -> None:
        if not self.enabled:
            return
        row = self._calls.setdefault(int(call), {"call": int(call)})
        projected = _response_projection(response)
        body = _canonical(projected)
        row["response_sha256"] = hashlib.sha256(body).hexdigest()
        if len(body) > self.max_call_chars or (
            self._bytes_estimate + len(body) > self.max_bundle_bytes
        ):
            self._complete = False
            row["response_omitted"] = True
        else:
            row["response"] = projected
            row["response_captured"] = True
            self._bytes_estimate += len(body)

    def record_error(self, *, call: int, error_type: str) -> None:
        if not self.enabled:
            return
        row = self._calls.setdefault(int(call), {"call": int(call)})
        row["response_error"] = str(error_type)
        self._complete = False

    def finalize(self) -> dict[str, Any]:
        metadata = {
            "enabled": self.enabled,
            "path": str(self.path.name) if self.enabled else "",
            "call_count": len(self._calls),
            "complete": bool(self.enabled and self._complete),
            "request_bodies_captured": bool(
                self.enabled
                and self._calls
                and all(row.get("request_captured") for row in self._calls.values())
            ),
            "responses_captured": bool(
                self.enabled
                and self._calls
                and all(row.get("response_captured") for row in self._calls.values())
            ),
            "trajectory_replay_ready": bool(
                self.enabled
                and self._complete
                and self._calls
                and all(row.get("request_captured") for row in self._calls.values())
                and all(row.get("response_captured") for row in self._calls.values())
            ),
            "model_causal_replay_ready": False,
        }
        if not self.enabled:
            return metadata
        payload = {
            "schema": "gt.counterfactual_replay_bundle.v1",
            "metadata": metadata,
            "calls": [self._calls[key] for key in sorted(self._calls)],
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        metadata["sha256"] = hashlib.sha256(self.path.read_bytes()).hexdigest()
        return metadata
