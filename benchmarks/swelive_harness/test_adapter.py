from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

from groundtruth.lsp import background_promotion

from benchmarks.swelive_harness import adapter
from eval.pier_gt_harness_adapter import PierGtHarnessMiniSwe246Agent
from groundtruth import resolve

ROOT = Path(__file__).resolve().parents[2]


def test_prewarm_runs_after_exact_adapter_install_and_before_the_agent(monkeypatch):
    order = []

    async def base_install(self, environment):
        order.append("exact-install")

    async def execute(self, environment, command, env=None, **kwargs):
        order.append("prewarm")
        assert command.endswith("/installed-agent/swelive-prewarm-graph.py")
        assert env["GT_TASK_ID"] == "task-1"
        assert env["GT_PRODUCT_SOURCE_SHA"] == "a" * 40
        assert env["GT_STATE_DIR"] == "/logs/agent/gt-state"

    class Environment:
        async def upload_file(self, source, destination):
            order.append("upload")
            expected = {
                "prewarm_graph.py": "/installed-agent/swelive-prewarm-graph.py",
                "sitecustomize.py": "/installed-agent/swelive-runtime/sitecustomize.py",
            }
            assert destination == expected[Path(source).name]

    async def execute_root(self, environment, command, **kwargs):
        order.append("runtime-dir")
        assert command == "mkdir -p /installed-agent/swelive-runtime"

    monkeypatch.setattr(adapter, "_ORIGINAL_INSTALL", base_install)
    monkeypatch.setattr(PierGtHarnessMiniSwe246Agent, "exec_as_agent", execute)
    monkeypatch.setattr(PierGtHarnessMiniSwe246Agent, "exec_as_root", execute_root)
    monkeypatch.setattr(
        PierGtHarnessMiniSwe246Agent,
        "resolve_env_vars",
        lambda self: {},
    )
    agent = object.__new__(PierGtHarnessMiniSwe246Agent)
    agent._resolved_flags = {
        "task_id": "task-1",
        "product_source_sha": "a" * 40,
    }

    asyncio.run(adapter._prewarmed_install(agent, Environment()))
    assert order == ["exact-install", "runtime-dir", "upload", "upload", "prewarm"]


def test_hook_retains_the_official_agent_import_path(monkeypatch):
    monkeypatch.setattr(PierGtHarnessMiniSwe246Agent, "install", adapter._ORIGINAL_INSTALL)
    monkeypatch.setattr(
        PierGtHarnessMiniSwe246Agent, "_run_command", adapter._ORIGINAL_RUN_COMMAND
    )
    adapter.install_prewarm_hook()
    assert PierGtHarnessMiniSwe246Agent.install is adapter._prewarmed_install
    assert PierGtHarnessMiniSwe246Agent._run_command is adapter._complete_lsp_run_command
    assert (
        f"{PierGtHarnessMiniSwe246Agent.__module__}:"
        f"{PierGtHarnessMiniSwe246Agent.__name__}"
        == "eval.pier_gt_harness_adapter:PierGtHarnessMiniSwe246Agent"
    )


def test_agent_command_loads_the_full_lsp_selection_hook(monkeypatch):
    monkeypatch.setattr(
        adapter,
        "_ORIGINAL_RUN_COMMAND",
        lambda self, instruction, model, extra: (
            'PATH="/installed-agent/lsp-bin:$PATH" '
            'exec "$HOME/.local/share/uv/tools/nano-harness/bin/python" '
            "-m scripts.miniswe_supervisor"
        ),
    )
    command = adapter._complete_lsp_run_command(object(), "task", "model", "")
    assert command.count("PYTHONPATH=") == 1
    assert "/installed-agent/swelive-runtime" in command


def test_full_lsp_selection_hook_loads_all_edges_and_corrects_receipt(monkeypatch):
    observed = {}

    def load_edges(connection, **kwargs):
        observed.update(kwargs)
        return [{"id": index} for index in range(700)]

    async def bounded_run(self, handle, candidate, languages, terminal):
        terminal["language_receipts"] = {
            "python": {
                "candidate_unit_count": 700,
                "selected_unit_count": 700,
                "selection_limit": 500,
                "selection_complete": False,
                "selection_limitation": "bounded_or_primary_identity_unavailable",
            }
        }

    scheduler = background_promotion.LSPPromotionScheduler
    monkeypatch.setattr(resolve, "_get_ambiguous_edges", load_edges)
    monkeypatch.setattr(scheduler, "_run_languages", bounded_run)
    monkeypatch.setenv("GT_LSP_MAX_EDGES", "100000")

    path = ROOT / "benchmarks/swelive_harness/sitecustomize.py"
    spec = importlib.util.spec_from_file_location("swelive_sitecustomize_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    edges = scheduler._load_edges(":memory:", "python")
    assert len(edges) == 700
    assert observed == {
        "min_confidence": 0.95,
        "language": "python",
        "limit": 100000,
    }

    terminal = {}
    asyncio.run(scheduler._run_languages(object(), None, None, ["python"], terminal))
    receipt = terminal["language_receipts"]["python"]
    assert receipt["selection_limit"] == 100000
    assert receipt["selection_complete"] is True
    assert "selection_limitation" not in receipt


def test_workflow_uses_one_pull_and_retains_image_by_id():
    text = (ROOT / ".github/workflows/swelive_gt_harness_paid.yaml").read_text(
        encoding="utf-8"
    )
    assert text.count('docker pull "${SOURCE_IMAGE}@${SOURCE_DIGEST}"') == 1
    canary = text.split(
        "Prove the official SWE-bench evaluator before any model request", 1
    )[1].split("Stagger provider dispatch within the parallel cohort", 1)[0]
    assert "docker pull" not in canary
    assert "docker image inspect --format '{{.Id}}'" in canary
    assert "pre-spend-official/image-id.txt" in text
    assert "python benchmarks/swelive_harness/run_pier.py run" in text
    assert (
        '--agent-setup-timeout-multiplier '
        '"${{ matrix.agent_timeout_multiplier }}"'
    ) in text
    assert (
        "--agent-import-path "
        "eval.pier_gt_harness_adapter:PierGtHarnessMiniSwe246Agent"
    ) in text


def test_prewarm_requires_dense_work_before_the_provider():
    text = (ROOT / "benchmarks/swelive_harness/prewarm_graph.py").read_text(
        encoding="utf-8"
    )
    assert "embedding_budget_seconds=1800.0" in text
    assert 'receipt.embedding_state != "refreshed"' in text
    assert '"dense_ready_before_provider": True' in text
