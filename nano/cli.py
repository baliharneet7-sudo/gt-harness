from __future__ import annotations

import argparse
import os
import sys

from rich.console import Console
from rich.panel import Panel

from .agent import Agent
from .prompts import SYSTEM_PROMPT
from .providers import AnthropicProvider, OpenAIProvider, Provider

_console = Console()


def build_provider(*, model: str, base_url: str | None) -> Provider:
    if base_url:
        # Local OpenAI-compatible servers (vLLM, ollama, llama.cpp) accept any
        # api_key. The openai SDK requires one to instantiate, so supply a
        # placeholder when none is set in the env.
        if not os.environ.get("OPENAI_API_KEY"):
            import openai
            client = openai.OpenAI(base_url=base_url, api_key="sk-local")
            return OpenAIProvider(model=model, base_url=base_url, client=client)
        return OpenAIProvider(model=model, base_url=base_url)
    if model.startswith(("claude", "anthropic")):
        return AnthropicProvider(model=model)
    return OpenAIProvider(model=model)


def _print_event(event: dict) -> None:
    et = event["type"]
    if et == "assistant" and event.get("text"):
        _console.print(Panel(event["text"], title="assistant", border_style="cyan"))
    elif et == "tool_result":
        title = "tool_result" + (" (error)" if event.get("is_error") else "")
        _console.print(Panel(event["output"][:2000], title=title,
                             border_style="red" if event.get("is_error") else "green"))


def main(argv: list[str] | None = None) -> int:
    # Windows consoles and pipes default to cp1252; model output is full of
    # unicode. Never let the printer kill a finished run.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="nano")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="Run the agent on a task description.")
    run.add_argument("task", help="Plain-English task description.")
    run.add_argument("--model", default="claude-opus-4-7")
    run.add_argument("--base-url", default=None,
                     help="OpenAI-compatible base URL (Together, vLLM, etc.).")
    run.add_argument("--max-iterations", type=int, default=30)
    args = parser.parse_args(argv)

    provider = build_provider(model=args.model, base_url=args.base_url)
    agent = Agent(provider=provider, system=SYSTEM_PROMPT,
                  max_iterations=args.max_iterations, on_event=_print_event)
    result = agent.run(args.task)
    _console.print(f"\n[bold]stop:[/] {result.stop_reason}  "
                   f"iterations={result.iterations}  "
                   f"in={result.total_input_tokens}  "
                   f"out={result.total_output_tokens}  "
                   f"cache_read={result.total_cache_read_tokens}")
    if result.final_text:
        _console.print(Panel(result.final_text, title="final", border_style="bold"))
    return 0 if result.stop_reason == "end_turn" else 1


if __name__ == "__main__":
    sys.exit(main())
