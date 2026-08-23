from __future__ import annotations

import io
from types import SimpleNamespace

from rich.console import Console

import nano.cli


def test_event_printer_treats_model_and_tool_text_as_plain_text(monkeypatch) -> None:
    output = io.StringIO()
    monkeypatch.setattr(
        nano.cli,
        "_console",
        Console(file=output, force_terminal=False, width=120),
    )
    dangerous = "closing-looking path [/app/alpine-disk.qcow2]"

    nano.cli._print_event(
        {
            "type": "assistant",
            "text": dangerous,
            "tool_calls": [
                SimpleNamespace(name="bash", arguments={"command": dangerous})
            ],
        }
    )
    nano.cli._print_event(
        {"type": "tool_result", "output": dangerous, "is_error": False}
    )

    rendered = output.getvalue()
    assert rendered.count(dangerous) == 3
