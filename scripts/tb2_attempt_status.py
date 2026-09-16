"""Classify a Terminal-Bench task attempt for infrastructure-only retries.

An official reward, including zero, is final. A retry is allowed only when the
provider failed transiently before the model produced any assistant action.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

TRANSIENT_PROVIDER_EXCEPTIONS = frozenset(
    {
        "APIConnectionError",
        "APITimeoutError",
        "BadGatewayError",
        "InternalServerError",
        "RateLimitError",
        "ServiceUnavailableError",
        "Timeout",
        "TimeoutError",
    }
)


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def classify_attempt(root: Path, task_id: str) -> dict[str, Any]:
    trials: list[dict[str, Any]] = []
    for path in sorted(root.rglob("result.json")) if root.exists() else []:
        payload = _object(path)
        runner_task = str(payload.get("task_name") or "").rsplit("/", 1)[-1]
        if runner_task == task_id and payload.get("trial_name"):
            trials.append(payload)

    if len(trials) != 1:
        return {
            "schema": "gt.tb2_attempt_status.v1",
            "task_id": task_id,
            "state": "infrastructure_failed",
            "retryable": False,
            "reason": "trial_result_missing" if not trials else "trial_result_ambiguous",
            "trial_results": len(trials),
        }

    trial = trials[0]
    verifier = trial.get("verifier_result")
    rewards = verifier.get("rewards") if isinstance(verifier, dict) else None
    reward = rewards.get("reward") if isinstance(rewards, dict) else None
    if type(reward) in (int, float) and reward in (0, 1):
        return {
            "schema": "gt.tb2_attempt_status.v1",
            "task_id": task_id,
            "state": "graded",
            "retryable": False,
            "reason": "official_verifier_reward",
            "reward": int(reward),
            "trial_results": 1,
        }

    exception = trial.get("exception_info")
    exception_type = (
        str(exception.get("exception_type") or "") if isinstance(exception, dict) else ""
    )
    exception_message = (
        str(exception.get("exception_message") or "") if isinstance(exception, dict) else ""
    )
    trajectories = sorted(root.rglob("miniswe_trajectory.json"))
    assistant_actions = 0
    for path in trajectories:
        trajectory = _object(path)
        messages = trajectory.get("messages")
        if isinstance(messages, list):
            assistant_actions += sum(
                1
                for message in messages
                if isinstance(message, dict) and message.get("role") == "assistant"
            )

    transient_provider = exception_type in TRANSIENT_PROVIDER_EXCEPTIONS
    package_setup_failure = bool(
        exception_type == "NonZeroAgentExitCodeError"
        and "command -v curl" in exception_message
        and "apt-get" in exception_message
    )
    retryable = bool(
        (transient_provider and trajectories or package_setup_failure) and assistant_actions == 0
    )
    reason = (
        "infrastructure_before_first_action" if retryable else "nonretryable_infrastructure_failure"
    )
    return {
        "schema": "gt.tb2_attempt_status.v1",
        "task_id": task_id,
        "state": "infrastructure_failed",
        "retryable": retryable,
        "reason": reason,
        "exception_type": exception_type,
        "assistant_actions": assistant_actions,
        "trajectory_files": len(trajectories),
        "trial_results": 1,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = classify_attempt(args.root, args.task_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
