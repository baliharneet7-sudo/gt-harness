import json
import subprocess
import sys
from pathlib import Path

from scripts.mechanical_completeness_gate import audit_configuration


def test_operator_entry_point_loads_from_repository_root() -> None:
    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, "scripts/mechanical_completeness_gate.py", "--help"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Authoritative no-spend configuration gate" in completed.stdout


def test_checked_in_final_configuration_is_mechanically_complete() -> None:
    root = Path(__file__).resolve().parents[1]
    report = audit_configuration(root)

    assert report["status"] == "PASS", report["failures"]
    assert report["task_profile"] == "repair20-v1"
    assert all(check["passed"] for check in report["checks"])


def test_gate_is_sensitive_to_replay_and_release_order_mutations(tmp_path) -> None:
    root = Path(__file__).resolve().parents[1]
    paid = (root / ".github/workflows/tb2_miniswe_central.yml").read_text(
        encoding="utf-8"
    )
    provider_free = (root / ".github/workflows/central_provider_free.yml").read_text(
        encoding="utf-8"
    )
    treatment = json.loads(
        (root / "eval/treatments/tb2_central_relational_v2.json").read_text(
            encoding="utf-8"
        )
    )

    paid_path = tmp_path / "paid.yml"
    provider_free_path = tmp_path / "provider-free.yml"
    treatment_path = tmp_path / "treatment.json"
    paid_path.write_text(
        paid.replace('--ak enable_replay_capture="true"', '--ak enable_replay_capture="false"')
        .replace(
            "needs: [resolve, provider_free, release_identity]",
            "needs: [resolve, provider_free]",
        ),
        encoding="utf-8",
    )
    provider_free_path.write_text(provider_free, encoding="utf-8")
    treatment["runtime_agent_kwargs"]["enable_replay_capture"] = False
    treatment_path.write_text(json.dumps(treatment), encoding="utf-8")

    report = audit_configuration(
        root,
        paid_workflow_path=paid_path,
        provider_free_workflow_path=provider_free_path,
        treatment_path=treatment_path,
    )

    assert report["status"] == "BLOCKED"
    assert "final_treatment_contract" in report["failures"]
    assert "paid_dispatch_interlock" in report["failures"]
