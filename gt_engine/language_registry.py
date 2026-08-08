"""One deterministic authority for authored-source language capabilities.

The central runtime, repository indexer, syntax probes, and legacy Mini-SWE
bridges historically carried different extension inventories.  A path may be
validation-relevant source even when the structural index has no parser for
its language.  Keeping those two facts separate prevents ``no source`` from
masking an unsupported-index failure.
"""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LanguageCapability:
    name: str
    suffixes: tuple[str, ...]
    validation_relevant: bool = True
    structural_required: bool = True
    structural_index: bool = True
    symbol_support: bool = True
    caller_support: bool = True
    syntax_probe: str | None = None


LANGUAGE_CAPABILITIES: tuple[LanguageCapability, ...] = (
    LanguageCapability("python", (".py", ".pyi"), syntax_probe="python"),
    LanguageCapability("javascript", (".js", ".jsx", ".mjs", ".cjs"), syntax_probe="node"),
    LanguageCapability("typescript", (".ts", ".tsx")),
    LanguageCapability("go", (".go",)),
    LanguageCapability("rust", (".rs",)),
    LanguageCapability("ruby", (".rb", ".rake"), syntax_probe="ruby"),
    LanguageCapability("java", (".java",)),
    LanguageCapability("kotlin", (".kt", ".kts")),
    LanguageCapability("csharp", (".cs",)),
    LanguageCapability("php", (".php",)),
    LanguageCapability("swift", (".swift",)),
    LanguageCapability("scala", (".scala", ".sc")),
    LanguageCapability("c", (".c", ".h")),
    LanguageCapability("cpp", (".cc", ".cpp", ".cxx", ".hpp", ".hxx")),
    LanguageCapability("lua", (".lua",)),
    LanguageCapability("elixir", (".ex", ".exs")),
    LanguageCapability("ocaml", (".ml", ".mli")),
    LanguageCapability("shell", (".sh", ".bash"), syntax_probe="bash"),
    LanguageCapability("css", (".css",)),
    LanguageCapability("cue", (".cue",)),
    LanguageCapability("elm", (".elm",)),
    LanguageCapability("groovy", (".groovy", ".gradle")),
    LanguageCapability("hcl", (".tf", ".hcl")),
    LanguageCapability("html", (".html", ".htm")),
    LanguageCapability("protobuf", (".proto",)),
    LanguageCapability("sql", (".sql",)),
    LanguageCapability("svelte", (".svelte",)),
    LanguageCapability(
        "markdown",
        (".md",),
        structural_required=False,
        symbol_support=False,
        caller_support=False,
    ),
    LanguageCapability(
        "toml",
        (".toml",),
        symbol_support=False,
        caller_support=False,
    ),
    LanguageCapability(
        "yaml",
        (".yaml", ".yml"),
        symbol_support=False,
        caller_support=False,
    ),
    LanguageCapability(
        "configuration",
        (".json", ".xml", ".ini", ".cfg"),
        structural_required=False,
        structural_index=False,
        symbol_support=False,
        caller_support=False,
    ),
    # These are authored source and affect validation revisions.  The shipped
    # gt-index binary has no certified structural parser for them yet, so GT
    # must report unsupported structural coverage rather than pretend that no
    # code exists or manufacture symbols with regexes.
    LanguageCapability(
        "cobol",
        (".cob", ".cbl"),
        structural_index=False,
        symbol_support=False,
        caller_support=False,
        syntax_probe="cobc",
    ),
    LanguageCapability(
        "scheme",
        (".scm", ".ss"),
        structural_index=False,
        symbol_support=False,
        caller_support=False,
    ),
    LanguageCapability(
        "racket",
        (".rkt",),
        structural_index=False,
        symbol_support=False,
        caller_support=False,
    ),
    LanguageCapability(
        "objective_c",
        (".m", ".mm"),
        structural_index=False,
        symbol_support=False,
        caller_support=False,
    ),
    LanguageCapability(
        "erlang",
        (".erl",),
        structural_index=False,
        symbol_support=False,
        caller_support=False,
    ),
    LanguageCapability(
        "haskell",
        (".hs",),
        structural_index=False,
        symbol_support=False,
        caller_support=False,
    ),
    LanguageCapability(
        "clojure",
        (".clj", ".cljs", ".cljc"),
        structural_index=False,
        symbol_support=False,
        caller_support=False,
    ),
    LanguageCapability(
        "dart",
        (".dart",),
        structural_index=False,
        symbol_support=False,
        caller_support=False,
    ),
    LanguageCapability(
        "zig",
        (".zig",),
        structural_index=False,
        symbol_support=False,
        caller_support=False,
    ),
    LanguageCapability(
        "perl",
        (".pl", ".pm"),
        structural_index=False,
        symbol_support=False,
        caller_support=False,
    ),
    LanguageCapability(
        "fsharp",
        (".fs", ".fsx"),
        structural_index=False,
        symbol_support=False,
        caller_support=False,
    ),
    LanguageCapability(
        "visual_basic",
        (".vb",),
        structural_index=False,
        symbol_support=False,
        caller_support=False,
    ),
)

_BY_SUFFIX = {
    suffix: capability for capability in LANGUAGE_CAPABILITIES for suffix in capability.suffixes
}

VALIDATION_SOURCE_SUFFIXES = frozenset(
    suffix
    for capability in LANGUAGE_CAPABILITIES
    if capability.validation_relevant
    for suffix in capability.suffixes
)
INDEXABLE_SOURCE_SUFFIXES = frozenset(
    suffix
    for capability in LANGUAGE_CAPABILITIES
    if capability.structural_index
    for suffix in capability.suffixes
)
INDEX_REQUIRED_SOURCE_SUFFIXES = frozenset(
    suffix
    for capability in LANGUAGE_CAPABILITIES
    if capability.structural_required
    for suffix in capability.suffixes
)


def capability_for_path(path: str | os.PathLike[str]) -> LanguageCapability | None:
    return _BY_SUFFIX.get(os.path.splitext(os.fspath(path))[1].lower())


def is_validation_source(path: str | os.PathLike[str]) -> bool:
    capability = capability_for_path(path)
    return bool(capability and capability.validation_relevant)


def is_indexable_source(path: str | os.PathLike[str]) -> bool:
    capability = capability_for_path(path)
    return bool(capability and capability.structural_index)


def syntax_probe_command(path: str) -> str | None:
    capability = capability_for_path(path)
    probe = capability.syntax_probe if capability is not None else None
    quoted = shlex.quote(path)
    if probe == "python":
        return (
            "command -v python3 >/dev/null 2>&1 || exit 0; "
            f"PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile -- {quoted}"
        )
    if probe == "node":
        return f"command -v node >/dev/null 2>&1 || exit 0; node --check -- {quoted}"
    if probe == "bash":
        return f"command -v bash >/dev/null 2>&1 || exit 0; bash -n -- {quoted}"
    if probe == "ruby":
        return f"command -v ruby >/dev/null 2>&1 || exit 0; ruby -c -- {quoted}"
    if probe == "cobc":
        return f"command -v cobc >/dev/null 2>&1 || exit 0; cobc -fsyntax-only -- {quoted}"
    return None


__all__ = [
    "INDEXABLE_SOURCE_SUFFIXES",
    "INDEX_REQUIRED_SOURCE_SUFFIXES",
    "LANGUAGE_CAPABILITIES",
    "LanguageCapability",
    "VALIDATION_SOURCE_SUFFIXES",
    "capability_for_path",
    "is_indexable_source",
    "is_validation_source",
    "syntax_probe_command",
]
