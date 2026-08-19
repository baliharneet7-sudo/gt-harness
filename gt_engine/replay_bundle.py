"""Bounded, opt-in capture of provider requests for counterfactual replay.

The writer stores exact prepared provider messages and the corresponding model
response metadata in a separate artifact when the treatment contract enables
it.  It never alters the provider request.  A bundle is trajectory-replay-ready
only when every request/response is captured without truncation. It never
injects or requires provider-specific sampling controls; model-level causal
reaction remains explicitly unidentifiable.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import tempfile
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


def _atomic_write(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class ReplayBundleWriter:
    """Write an exact content-addressed replay bundle.

    Requests and responses are stored once by canonical SHA-256.  Per-call
    rows contain only ordered references, so long tasks cannot become
    unreplayable because one monolithic JSON document crossed an arbitrary
    character or byte cap.
    """

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
        # Retained as constructor compatibility and reported for audits; v2
        # does not truncate exact replay data at either legacy threshold.
        self.max_call_chars = max(1_000, int(max_call_chars))
        self.max_bundle_bytes = max(10_000, int(max_bundle_bytes))
        self._calls: dict[int, dict[str, Any]] = {}
        self._complete = self.enabled
        self._blobs: dict[str, bytes] = {}

    def _blob(self, value: Any) -> str:
        body = _canonical(value)
        digest = hashlib.sha256(body).hexdigest()
        self._blobs.setdefault(digest, body)
        return digest

    def record_request(
        self,
        *,
        call: int,
        provider_messages: list[dict[str, Any]],
        request_envelope: dict[str, Any],
        control_provider_messages: list[dict[str, Any]] | None = None,
        control_request_envelope: dict[str, Any] | None = None,
        intervention: dict[str, Any] | None = None,
        provider_tools: Any = None,
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
        request_blob = self._blob(provider_messages)
        envelope_blob = self._blob(request_envelope)
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
            "request_blob_sha256": request_blob,
            "request_envelope_blob_sha256": envelope_blob,
            "request_envelope_captured": True,
            "request_captured": True,
            "response_captured": False,
            "dispatch_status": "prepared",
        }
        if control_provider_messages is not None:
            if control_request_envelope is None:
                raise ValueError("control request envelope required")
            control_body = _canonical(control_provider_messages)
            row.update(
                {
                    "control_request_blob_sha256": self._blob(
                        control_provider_messages
                    ),
                    "control_provider_messages_sha256": hashlib.sha256(
                        control_body
                    ).hexdigest(),
                    "control_request_captured": True,
                    "control_request_envelope_blob_sha256": self._blob(
                        control_request_envelope
                    ),
                    "control_request_envelope_captured": True,
                    "intervention": dict(intervention or {}),
                }
            )
        if provider_tools is not None:
            tools_body = _canonical(provider_tools)
            row.update(
                {
                    "provider_tools_blob_sha256": self._blob(provider_tools),
                    "provider_tools_sha256": hashlib.sha256(tools_body).hexdigest(),
                    "provider_tools_captured": True,
                }
            )
        self._calls[int(call)] = row

    def record_invocation(self, *, call: int) -> None:
        if not self.enabled:
            return
        self._calls.setdefault(int(call), {"call": int(call)})[
            "dispatch_status"
        ] = "invoked"

    def record_not_sent(self, *, call: int, reason: str) -> None:
        if not self.enabled:
            return
        row = self._calls.setdefault(int(call), {"call": int(call)})
        row["dispatch_status"] = "prepared_not_sent"
        row["not_sent_reason"] = str(reason)

    def record_response(self, *, call: int, response: Any) -> None:
        if not self.enabled:
            return
        row = self._calls.setdefault(int(call), {"call": int(call)})
        projected = _response_projection(response)
        body = _canonical(projected)
        row["response_sha256"] = hashlib.sha256(body).hexdigest()
        row["response_blob_sha256"] = self._blob(projected)
        row["response_captured"] = True
        row["dispatch_status"] = "response_received"

    def record_error(self, *, call: int, error_type: str) -> None:
        if not self.enabled:
            return
        row = self._calls.setdefault(int(call), {"call": int(call)})
        row["response_error"] = str(error_type)
        row["dispatch_status"] = "response_error"
        self._complete = False

    def finalize(self) -> dict[str, Any]:
        paired_rows = [
            row
            for row in self._calls.values()
            if row.get("control_request_captured") and row.get("intervention")
        ]
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
            "request_envelopes_captured": bool(
                self.enabled
                and self._calls
                and all(
                    row.get("request_envelope_captured")
                    for row in self._calls.values()
                )
            ),
            "responses_captured": bool(
                self.enabled
                and all(
                    row.get("response_captured")
                    for row in self._calls.values()
                    if row.get("dispatch_status") != "prepared_not_sent"
                )
            ),
            "trajectory_replay_ready": bool(
                self.enabled
                and self._complete
                and self._calls
                and all(row.get("request_captured") for row in self._calls.values())
                and all(
                    row.get("request_envelope_captured")
                    for row in self._calls.values()
                )
                and all(
                    row.get("response_captured")
                    for row in self._calls.values()
                    if row.get("dispatch_status") != "prepared_not_sent"
                )
            ),
            "model_causal_replay_ready": False,
            "paired_decision_point_count": len(paired_rows),
            "paired_decision_capture_ready": bool(
                self.enabled
                and paired_rows
                and all(row.get("request_captured") for row in paired_rows)
                and all(row.get("control_request_captured") for row in paired_rows)
            ),
            "blob_count": len(self._blobs),
        }
        if not self.enabled:
            return metadata
        self.path.mkdir(parents=True, exist_ok=True)
        blobs_dir = self.path / "blobs"
        blobs_dir.mkdir(parents=True, exist_ok=True)
        for digest, body in self._blobs.items():
            target = blobs_dir / f"{digest}.json.gz"
            if not target.exists():
                _atomic_write(target, gzip.compress(body, mtime=0))
        calls_body = b"".join(
            _canonical(self._calls[key]) + b"\n" for key in sorted(self._calls)
        )
        calls_path = self.path / "calls.jsonl"
        _atomic_write(calls_path, calls_body)
        metadata["calls_sha256"] = hashlib.sha256(calls_body).hexdigest()
        manifest = {
            "schema": "gt.counterfactual_replay_bundle.v3",
            "metadata": metadata,
        }
        manifest_path = self.path / "manifest.json"
        _atomic_write(
            manifest_path,
            (json.dumps(manifest, indent=2) + "\n").encode("utf-8"),
        )
        metadata["sha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        return metadata


def load_replay_bundle(path: str | Path) -> dict[str, Any]:
    """Load and cryptographically verify an exact replay bundle."""

    root = Path(path)
    manifest_path = root / "manifest.json"
    calls_path = root / "calls.jsonl"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        calls_body = calls_path.read_bytes()
    except (OSError, ValueError) as exc:
        raise ValueError("replay manifest unreadable") from exc
    schema = str(manifest.get("schema") or "")
    if schema not in {
        "gt.counterfactual_replay_bundle.v2",
        "gt.counterfactual_replay_bundle.v3",
    }:
        raise ValueError("replay schema mismatch")
    metadata = manifest.get("metadata") or {}
    if hashlib.sha256(calls_body).hexdigest() != metadata.get("calls_sha256"):
        raise ValueError("replay calls hash mismatch")
    calls: list[dict[str, Any]] = []
    for raw in calls_body.splitlines():
        try:
            row = json.loads(raw)
        except ValueError as exc:
            raise ValueError("replay call row invalid") from exc
        for field, output_key in (
            ("request_blob_sha256", "provider_messages"),
            ("request_envelope_blob_sha256", "request_envelope"),
            ("control_request_blob_sha256", "control_provider_messages"),
            (
                "control_request_envelope_blob_sha256",
                "control_request_envelope",
            ),
            ("provider_tools_blob_sha256", "provider_tools"),
            ("response_blob_sha256", "response"),
        ):
            digest = str(row.get(field) or "")
            if not digest:
                continue
            blob_path = root / "blobs" / f"{digest}.json.gz"
            try:
                body = gzip.decompress(blob_path.read_bytes())
            except (OSError, EOFError, gzip.BadGzipFile) as exc:
                raise ValueError("replay blob unreadable") from exc
            if hashlib.sha256(body).hexdigest() != digest:
                raise ValueError("replay blob hash mismatch")
            try:
                row[output_key] = json.loads(body)
            except ValueError as exc:
                raise ValueError("replay blob JSON invalid") from exc
        calls.append(row)
    call_ids = [int(row.get("call") or 0) for row in calls]
    if call_ids != sorted(call_ids) or len(call_ids) != len(set(call_ids)):
        raise ValueError("replay call order invalid")
    if schema == "gt.counterfactual_replay_bundle.v3":
        if call_ids and call_ids != list(range(1, len(call_ids) + 1)):
            raise ValueError("replay call sequence invalid")
        for row in calls:
            messages = row.get("provider_messages")
            envelope = row.get("request_envelope")
            if not isinstance(messages, list) or not isinstance(envelope, dict):
                raise ValueError("replay request envelope missing")
            if hashlib.sha256(_canonical(messages)).hexdigest() != str(
                row.get("provider_messages_sha256") or ""
            ):
                raise ValueError("replay provider messages hash mismatch")
            if hashlib.sha256(_canonical(envelope)).hexdigest() != str(
                row.get("request_payload_sha256") or ""
            ):
                raise ValueError("replay request envelope hash mismatch")
            if envelope.get("messages") != messages:
                raise ValueError("replay envelope messages mismatch")
            if row.get("provider_tools_captured") and envelope.get("tools") != row.get(
                "provider_tools"
            ):
                raise ValueError("replay envelope tools mismatch")
            control = row.get("control_provider_messages")
            control_envelope = row.get("control_request_envelope")
            if control is not None:
                if not isinstance(control_envelope, dict):
                    raise ValueError("replay control envelope missing")
                if control_envelope.get("messages") != control:
                    raise ValueError("replay control envelope messages mismatch")
    return {"manifest": manifest, "calls": calls}


__all__ = ["ReplayBundleWriter", "load_replay_bundle"]
