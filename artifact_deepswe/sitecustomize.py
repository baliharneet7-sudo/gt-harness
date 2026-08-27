"""Compatibility bootstrap for older task-image Python runtimes.

Some Live-Lite images use Python 3.10 while the installed LiteLLM dependency
imports ``NotRequired`` from ``typing`` (it moved there in Python 3.11).  The
headless runner puts ``/opt/gt`` on ``PYTHONPATH``, so Python loads this module
before LiteLLM and we can provide the standard backport without changing the
task repository or model code.
"""

try:
    import typing
    from typing_extensions import NotRequired

    if not hasattr(typing, "NotRequired"):
        typing.NotRequired = NotRequired
except Exception:
    # The shim is defensive; if typing_extensions is unavailable, the normal
    # import error remains visible in the task log for classification.
    pass
