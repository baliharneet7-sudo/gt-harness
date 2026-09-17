"""Run Pier with the SWE-Live task-local graph prewarm installed."""

from pier.cli.main import app

try:
    from benchmarks.swelive_harness.adapter import install_prewarm_hook
except ModuleNotFoundError:  # Direct script execution in the workflow.
    from adapter import install_prewarm_hook


def main() -> None:
    install_prewarm_hook()
    app()


if __name__ == "__main__":
    main()
