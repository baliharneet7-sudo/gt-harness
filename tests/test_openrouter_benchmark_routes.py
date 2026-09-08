from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _workflow(name: str) -> str:
    return (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


def test_live_lite_dispatch_requires_an_explicit_model() -> None:
    source = _workflow("swebench_live_lite_dispatch.yml")

    assert 'model: {description: "OpenRouter model id.' in source
    assert "model: ${{ inputs.model }}" in source
    assert "image_owner: harneet2512" in source
    assert "minimax/minimax-m3:free" not in source


def test_live_lite_has_one_openrouter_execution_route() -> None:
    source = _workflow("swebench_live_lite_full.yml")

    assert "OpenRouter model id" in source
    assert 'OPENAI_API_BASE="https://openrouter.ai/api/v1"' in source
    assert 'INPUT_MODEL="${INPUT_MODEL#openrouter/}"' in source
    assert '"provider": "openrouter"' in source
    assert "TOKENROUTER_API_KEY" not in source
    assert "DEEPSEEK_API_KEY" not in source
    assert '"provider": "deepseek"' not in source
