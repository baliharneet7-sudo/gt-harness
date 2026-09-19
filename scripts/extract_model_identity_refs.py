"""Extract the model-identity reference calls from the frozen TB2 GT-off baseline.

The baseline (``miniswe_tb2_gtoff_20260731``) ran on DeepSeek's own API while
it served DeepSeek-V4-Flash-0731. Every trajectory's first assistant message
records the exact ``usage.prompt_tokens`` the served tokenizer produced for a
known (system, user, tools) request. Replaying those requests verbatim against
another host and comparing prompt_tokens is a tokenizer-identity test that
needs no logprobs and survives the baseline's temperature 1.0.

The request is rebuilt as mini-swe-agent's LitellmModel sent it: the messages
with the ``extra`` key dropped (``_prepare_messages_for_api``) and
``tools=[BASH_TOOL]``. The trajectory does not store the tool schema, so it is
pinned here: mini-swe-agent's ``BASH_TOOL`` from 2.2.8, the version the
baseline ran, verified byte-identical to the 2.4.6 copy in review. The pinned
schema is recorded in the refs file and the tests compare against that record,
not against whatever mini-swe-agent happens to be installed.

Rerunnable: ``python -m scripts.extract_model_identity_refs --root
D:/gt_runs/miniswe_tb2_gtoff_20260731 --output
config/model_identity_refs.v1.json``. Only ``extracted_at`` changes between
runs over the same tree.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
from pathlib import Path
from typing import Any

SCHEMA = "gt.model_identity_refs.v1"
BASELINE_ID = "miniswe_tb2_gtoff_20260731"
SERVED_SNAPSHOT = "DeepSeek-V4-Flash-0731"
TRAJECTORY_GLOB = "matrix_cache/*/*/*/agent/miniswe_trajectory.json"
DEFAULT_COUNT = 12

# mini-swe-agent 2.2.8 minisweagent/models/utils/actions_toolcall.py BASH_TOOL,
# verified byte-identical to 2.4.6. Tests compare it to the committed refs.
BASH_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Execute a bash command",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The bash command to execute",
                    }
                },
                "required": ["command"],
            },
        },
    }
]
TOOLS_SOURCE = (
    "mini-swe-agent LitellmModel tools=[BASH_TOOL] "
    "(schema pinned from mini-swe-agent 2.2.8, the baseline's version; "
    "verified identical to 2.4.6)"
)


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _first_call(path: Path, root: Path) -> dict[str, Any]:
    """One trajectory's first request and the usage the baseline host reported."""
    raw = path.read_bytes()
    doc = json.loads(raw)
    relative = path.relative_to(root).as_posix()
    messages = doc.get("messages") if isinstance(doc, dict) else None
    if not isinstance(messages, list) or len(messages) < 3:
        raise ValueError(f"trajectory_shape_invalid: {relative}")
    roles = [m.get("role") if isinstance(m, dict) else None for m in messages[:3]]
    if roles != ["system", "user", "assistant"]:
        raise ValueError(f"trajectory_roles_invalid: {relative}: {roles}")
    response = (messages[2].get("extra") or {}).get("response")
    usage = response.get("usage") if isinstance(response, dict) else None
    if not isinstance(usage, dict) or not _positive_int(usage.get("prompt_tokens")):
        raise ValueError(f"trajectory_usage_missing: {relative}")
    details = usage.get("completion_tokens_details") or {}
    prompt_details = usage.get("prompt_tokens_details") or {}
    request = [{k: v for k, v in m.items() if k != "extra"} for m in messages[:2]]
    for message in request:
        if not isinstance(message.get("content"), str):
            raise ValueError(f"trajectory_content_not_text: {relative}")
    kwargs = ((doc.get("info") or {}).get("config") or {}).get("model") or {}
    return {
        "task": Path(relative).parts[1],
        "prompt_tokens": usage["prompt_tokens"],
        "reasoning_tokens": details.get("reasoning_tokens"),
        "cached_tokens": prompt_details.get("cached_tokens"),
        "source_trajectory": relative,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "messages": request,
        "_fingerprint": response.get("system_fingerprint"),
        "_model": response.get("model"),
        "_temperature": (kwargs.get("model_kwargs") or {}).get("temperature"),
    }


def extract(root: Path, count: int = DEFAULT_COUNT, now: str | None = None) -> dict[str, Any]:
    """The ``count`` smallest-prompt first calls under ``root``, verbatim."""
    paths = sorted(root.glob(TRAJECTORY_GLOB))
    if count < 1 or len(paths) < count:
        raise ValueError(f"count {count} exceeds the {len(paths)} trajectories found")
    calls = [_first_call(path, root) for path in paths]
    tasks = [call["task"] for call in calls]
    if len(set(tasks)) != len(tasks):
        raise ValueError("duplicate task in baseline tree; refusing an ambiguous reference")
    fingerprints = {call["_fingerprint"] for call in calls}
    if len(fingerprints) != 1 or None in fingerprints:
        raise ValueError(f"baseline fingerprint is not uniform: {sorted(map(str, fingerprints))}")
    models = {call["_model"] for call in calls}
    temperatures = {call["_temperature"] for call in calls}
    chosen = sorted(calls, key=lambda call: (call["prompt_tokens"], call["task"]))[:count]
    refs = [{k: v for k, v in call.items() if not k.startswith("_")} for call in chosen]
    return {
        "schema": SCHEMA,
        "baseline_id": BASELINE_ID,
        "served_snapshot": SERVED_SNAPSHOT,
        "served_model": models.pop() if len(models) == 1 else sorted(map(str, models)),
        "system_fingerprint": fingerprints.pop(),
        "baseline_temperature": (
            temperatures.pop() if len(temperatures) == 1 else sorted(map(str, temperatures))
        ),
        "selection": f"{count} smallest first-call prompt_tokens, ties by task name",
        "tools": BASH_TOOLS,
        "tools_source": TOOLS_SOURCE,
        "population": {
            "trajectories": len(calls),
            "reasoning_positive": sum(_positive_int(c["reasoning_tokens"]) for c in calls),
            "prompt_tokens_min": min(c["prompt_tokens"] for c in calls),
            "prompt_tokens_max": max(c["prompt_tokens"] for c in calls),
        },
        "source_trajectory_sha256": {r["source_trajectory"]: r["source_sha256"] for r in refs},
        "extracted_at": now or _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "refs": refs,
    }


def _write(output: Path, doc: dict[str, Any]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, output)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    doc = extract(args.root, args.count)
    _write(args.output, doc)
    for ref in doc["refs"]:
        print(
            f"{ref['task']}\tprompt_tokens={ref['prompt_tokens']}"
            f"\treasoning_tokens={ref['reasoning_tokens']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
