"""Run pinned Mini-SWE-Agent 2.x with the GT lifecycle adapter."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from minisweagent.agents.default import AgentConfig, DefaultAgent
from minisweagent.config import builtin_config_dir
from minisweagent.environments.local import LocalEnvironment, LocalEnvironmentConfig
from minisweagent.models.litellm_model import LitellmModel

from gt_engine.miniswe_controller import Predicate
from gt_engine.miniswe_integration import MiniSweAdapter
from gt_engine.miniswe_runtime import install_runtime_hooks
from gt_engine.task_contract import extract_task_contract
from gt_engine.verification_contract import compile_obligation_predicates


def _templates() -> tuple[str, str]:
    import yaml

    config = yaml.safe_load((builtin_config_dir / "mini.yaml").read_text())
    agent = config["agent"]
    return str(agent["system_template"]), str(agent["instance_template"])


def build_agent(
    *,
    task: str,
    model: str,
    cwd: str,
    state_dir: str,
    output: str | None,
    temperature: float,
) -> tuple[DefaultAgent, MiniSweAdapter]:
    contract = extract_task_contract(task)
    compiled = compile_obligation_predicates(contract)
    predicates = tuple(
        Predicate(item.predicate_id, contract_obligation.text)
        for contract_obligation in contract.obligations
        for item in (compiled[contract_obligation.obligation_id],)
    )
    adapter = MiniSweAdapter(
        task_id=hashlib.sha256(task.encode("utf-8")).hexdigest()[:16],
        state_dir=state_dir,
        predicates=predicates,
        contract=contract,
    )
    system_template, instance_template = _templates()
    model_obj = LitellmModel(
        model_name=model,
        model_kwargs={"temperature": temperature},
    )
    env_obj = LocalEnvironment(
        config_class=LocalEnvironmentConfig,
        cwd=cwd,
    )
    agent = DefaultAgent(
        model_obj,
        env_obj,
        config_class=AgentConfig,
        system_template=system_template,
        instance_template=instance_template,
        step_limit=100,
        output_path=Path(output) if output else None,
    )
    install_runtime_hooks(agent, adapter)
    return agent, adapter


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--model", default="deepseek-v4-flash")
    parser.add_argument("--cwd", default=".")
    parser.add_argument("--state-dir", default=".gt-state")
    parser.add_argument("--output")
    parser.add_argument("--temperature", type=float, default=1.0)
    args = parser.parse_args()
    agent, adapter = build_agent(
        task=args.task,
        model=args.model,
        cwd=args.cwd,
        state_dir=args.state_dir,
        output=args.output,
        temperature=args.temperature,
    )
    result = agent.run(args.task)
    print(json.dumps({"result": result, "gt": adapter.final_state()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUTF8", "1")
    raise SystemExit(main())
