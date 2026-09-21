"""GT capabilities as standalone shell tools the agent can call.

mini-swe-agent runs every command through ``subprocess.run`` in a fresh
subshell: no ``.bashrc``, no inherited environment, no session state. A tool
the agent can use therefore has to be a self-contained executable on PATH,
not an MCP server and not a shell function.

Each script takes the warm path when the tool daemon is up and falls back to
the ``groundtruth`` CLI when it is not, so a missing daemon costs latency
rather than the capability.

The tools wrap the handlers already shipped in ``groundtruth.mcp.tools``;
nothing here reimplements an answer.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Where tool scripts are installed inside the task container.
TOOL_BIN_DIR = "/usr/local/bin"

#: Default loopback endpoint for the warm daemon.
DEFAULT_TOOL_HOST = "127.0.0.1"
DEFAULT_TOOL_PORT = 4873

#: A tool call that has not answered in this many seconds is not worth waiting
#: for: the agent has a step budget and a slow graph answer costs it a turn.
TOOL_TIMEOUT_SECONDS = 20.0

#: Enrichment is cheaper than a tool call and runs on the agent's own search,
#: so it gets a tighter bound.
AUGMENT_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class GtToolSpec:
    """One agent-callable GT capability.

    ``key``       metric name, and the suffix of the daemon endpoint.
    ``bin_name``  the executable the agent types.
    ``usage``     printed on a usage error, so the agent can self-correct.
    ``args``      positional argument names, in order; the first is required.
    ``summary``   one line for the system prompt.
    """

    key: str
    bin_name: str
    usage: str
    args: tuple[str, ...]
    summary: str


#: The surface the agent sees. Every entry maps to a handler in
#: ``groundtruth.mcp.tools``; the names are the agent's vocabulary, so they are
#: short and verb-shaped rather than internal.
TOOL_SPECS: tuple[GtToolSpec, ...] = (
    GtToolSpec(
        key="find_relevant",
        bin_name="gt-find",
        usage='gt-find "<what you are looking for>"',
        args=("query",),
        summary="Rank the code most relevant to a description of the problem.",
    ),
    GtToolSpec(
        key="context",
        bin_name="gt-context",
        usage='gt-context "<symbol>" ["<file>"]',
        args=("symbol", "file"),
        summary="All callers, callees and flows for a symbol. Finds callers grep misses.",
    ),
    GtToolSpec(
        key="impact",
        bin_name="gt-impact",
        usage='gt-impact "<symbol>" [upstream|downstream]',
        args=("symbol", "direction"),
        summary="Blast radius: what breaks if this changes.",
    ),
    GtToolSpec(
        key="trace",
        bin_name="gt-trace",
        usage='gt-trace "<symbol>"',
        args=("symbol",),
        summary="Execution paths through a symbol.",
    ),
    GtToolSpec(
        key="explain",
        bin_name="gt-explain",
        usage='gt-explain "<symbol>"',
        args=("symbol",),
        summary="What a symbol is for, from its structure and usage.",
    ),
    GtToolSpec(
        key="symbols",
        bin_name="gt-symbols",
        usage='gt-symbols "<file or pattern>"',
        args=("target",),
        summary="Symbols defined in a file, or matching a pattern.",
    ),
    GtToolSpec(
        key="brief",
        bin_name="gt-brief",
        usage='gt-brief "<task description>"',
        args=("task",),
        summary="An orientation brief for the task against this repository.",
    ),
    GtToolSpec(
        key="orient",
        bin_name="gt-orient",
        usage="gt-orient",
        args=(),
        summary="Shape of the repository: entry points, layout, hot paths.",
    ),
    GtToolSpec(
        key="hotspots",
        bin_name="gt-hotspots",
        usage="gt-hotspots",
        args=(),
        summary="Files that change together and carry the most risk.",
    ),
    GtToolSpec(
        key="validate",
        bin_name="gt-validate",
        usage='gt-validate "<file>"',
        args=("file",),
        summary="Check an edit against the contracts its callers rely on.",
    ),
    GtToolSpec(
        key="dead_code",
        bin_name="gt-dead-code",
        usage="gt-dead-code",
        args=(),
        summary="Symbols with no reachable callers.",
    ),
    GtToolSpec(
        key="unused_packages",
        bin_name="gt-unused-packages",
        usage="gt-unused-packages",
        args=(),
        summary="Declared dependencies nothing imports.",
    ),
    GtToolSpec(
        key="status",
        bin_name="gt-status",
        usage="gt-status",
        args=(),
        summary="Whether the graph is built and current.",
    ),
    GtToolSpec(
        key="checkpoint",
        bin_name="gt-checkpoint",
        usage="gt-checkpoint",
        args=(),
        summary="Record the current workspace state.",
    ),
)

#: The enrichment helper. Not in TOOL_SPECS because the agent never types it —
#: the harness calls it on the agent's own search pattern.
AUGMENT_BIN = "gt-augment"

#: Marker the agent sees on enriched output, and the harness tests for before
#: deciding an enrichment was worth appending.
AUGMENT_MARKER = "[GT]"

BINARIES_BY_KEY: dict[str, str] = {spec.key: spec.bin_name for spec in TOOL_SPECS}
SPECS_BY_KEY: dict[str, GtToolSpec] = {spec.key: spec for spec in TOOL_SPECS}
TOOL_METRIC_KEYS: tuple[str, ...] = tuple(spec.key for spec in TOOL_SPECS)


def tool_script(spec: GtToolSpec, *, host: str = DEFAULT_TOOL_HOST,
                port: int = DEFAULT_TOOL_PORT) -> str:
    """The POSIX shell source for one tool.

    Self-contained on purpose: no sourcing, no PATH assumptions beyond the
    interpreter, and a cold fallback so the daemon is an optimisation rather
    than a dependency.
    """
    required = spec.args[0] if spec.args else ""
    guard = (
        f'if [ -z "${{1:-}}" ]; then echo "usage: {spec.usage}" >&2; exit 2; fi\n'
        if required else ""
    )
    # Arguments travel as a query string; the daemon and the CLI agree on names.
    query = "&".join(
        f'{name}=$(printf %s "${{{index}:-}}" | sed "s/ /%20/g")'
        for index, name in enumerate(spec.args, start=1)
    )
    build_query = f"{query}\n" if spec.args else ""
    params = "&".join(f'{name}=${name}' for name in spec.args)
    return f"""#!/bin/sh
# GT tool: {spec.key}. Generated by eval/gt_tool_registry.py - do not edit in place.
set -u
{guard}{build_query}
url="http://{host}:{port}/tool/{spec.key}?{params}"
if command -v curl >/dev/null 2>&1; then
  body=$(curl -fsS --max-time {int(TOOL_TIMEOUT_SECONDS)} "$url" 2>/dev/null) && {{
    printf '%s\\n' "$body"
    exit 0
  }}
fi
# Cold fallback: the daemon is not up, answer in-process.
exec groundtruth tool {spec.key} {" ".join(f'"${{{i}:-}}"' for i in range(1, len(spec.args) + 1))}
"""


def augment_script(*, host: str = DEFAULT_TOOL_HOST,
                   port: int = DEFAULT_TOOL_PORT) -> str:
    """Enrichment helper, called by the harness on the agent's search pattern.

    Exits 0 and prints nothing when GT has no annotation: a silent tool lets
    the caller append unconditionally without ever showing the agent an empty
    section.
    """
    return f"""#!/bin/sh
# GT enrichment. Generated by eval/gt_tool_registry.py - do not edit in place.
set -u
if [ -z "${{1:-}}" ]; then exit 0; fi
pattern=$(printf %s "$1" | sed "s/ /%20/g")
url="http://{host}:{port}/tool/augment?pattern=$pattern"
if command -v curl >/dev/null 2>&1; then
  body=$(curl -fsS --max-time {int(AUGMENT_TIMEOUT_SECONDS)} "$url" 2>/dev/null) && {{
    printf '%s' "$body"
    exit 0
  }}
fi
groundtruth tool augment "$1" 2>/dev/null || true
"""


def all_scripts(*, host: str = DEFAULT_TOOL_HOST,
                port: int = DEFAULT_TOOL_PORT) -> dict[str, str]:
    """Every executable to install, keyed by the name the agent types."""
    scripts = {spec.bin_name: tool_script(spec, host=host, port=port)
               for spec in TOOL_SPECS}
    scripts[AUGMENT_BIN] = augment_script(host=host, port=port)
    return scripts
