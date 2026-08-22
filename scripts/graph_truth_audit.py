#!/usr/bin/env python3
"""Score canonical GT graph queries against independent facts from frozen repositories."""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
import time
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gt_engine.repository_graph_service import RepositoryGraphService  # noqa: E402

Fact = tuple[str, str]


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8",
        errors="replace", check=False, stdin=subprocess.DEVNULL,
    )
    if result.returncode:
        raise RuntimeError("git failed: " + " ".join((result.stderr or result.stdout).split()))
    return result.stdout.strip()


def _tracked(root: Path, suffixes: tuple[str, ...]) -> list[Path]:
    output = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True,
    ).stdout
    return [
        root / item.decode("utf-8", errors="surrogateescape")
        for item in output.split(b"\0")
        if item and item.decode("utf-8", errors="surrogateescape").endswith(suffixes)
    ]


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _python_definitions(root: Path) -> dict[str, set[Fact]]:
    found: dict[str, set[Fact]] = defaultdict(set)
    for path in _tracked(root, (".py",)):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                found[node.name].add((node.name, _relative(root, path)))
    return found


def _python_direct_subclasses(root: Path, oracle: dict[str, Any]) -> set[Fact]:
    subject = str(oracle["symbol"])
    found: set[Fact] = set()
    for path in _tracked(root, (".py",)):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            bases = {
                base.id if isinstance(base, ast.Name) else base.attr
                for base in node.bases
                if isinstance(base, (ast.Name, ast.Attribute))
            }
            if subject in bases:
                found.add((node.name, _relative(root, path)))
    return found


def _python_in_repo_callees(root: Path, oracle: dict[str, Any]) -> set[Fact]:
    relative = str(oracle["file"])
    tree = ast.parse((root / relative).read_text(encoding="utf-8"), filename=relative)
    subject = str(oracle["symbol"])
    definitions = _python_definitions(root)
    matches = [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == subject
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"oracle expected one Python definition for {subject}, got {len(matches)}"
        )
    names: set[str] = set()
    for node in ast.walk(matches[0]):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                names.add(node.func.attr)
    return {fact for name in names for fact in definitions.get(name, set())}


def _resolve_relative_module(
    root: Path, source: Path, module: str, suffixes: tuple[str, ...]
) -> Path:
    base = (source.parent / module).resolve()
    candidates = [base, *(Path(str(base) + suffix) for suffix in suffixes)]
    candidates.extend(base / ("index" + suffix) for suffix in suffixes)
    for candidate in candidates:
        if candidate.is_file() and root.resolve() in candidate.parents:
            return candidate
    raise RuntimeError(f"cannot resolve relative module {module!r} from {_relative(root, source)}")


def _javascript_relative_requires(root: Path, oracle: dict[str, Any]) -> set[Fact]:
    path = root / str(oracle["file"])
    source = path.read_text(encoding="utf-8")
    modules = re.findall(r"\brequire\(\s*['\"](\.[^'\"]+)['\"]\s*\)", source)
    targets = {
        _resolve_relative_module(root, path, module, (".js", ".cjs", ".mjs"))
        for module in modules
    }
    return {(target.stem, _relative(root, target)) for target in targets}


def _javascript_commonjs_local_reexports(root: Path, oracle: dict[str, Any]) -> set[Fact]:
    path = root / str(oracle["file"])
    source = path.read_text(encoding="utf-8")
    declarations = set(re.findall(r"(?m)^\s*function\s+([A-Za-z_$][\w$]*)\s*\(", source))
    exports = re.findall(
        r"(?m)^\s*exports\.[A-Za-z_$][\w$]*\s*=\s*([A-Za-z_$][\w$]*)\s*;?\s*$",
        source,
    )
    unresolved = sorted(set(exports) - declarations)
    if unresolved:
        raise RuntimeError(f"CommonJS oracle encountered non-local exports: {unresolved}")
    relative = _relative(root, path)
    return {(name, relative) for name in exports}


def _typescript_named_type_reexports(root: Path, oracle: dict[str, Any]) -> set[Fact]:
    path = root / str(oracle["file"])
    source = path.read_text(encoding="utf-8")
    found: set[Fact] = set()
    blocks = re.findall(
        r"\bexport\s+type\s*\{(.*?)\}\s*from\s*['\"](\.[^'\"]+)['\"]",
        source,
        flags=re.DOTALL,
    )
    for body, module in blocks:
        target = _resolve_relative_module(root, path, module, (".ts", ".tsx"))
        target_source = target.read_text(encoding="utf-8")
        for item in body.split(","):
            token = re.sub(r"/\*.*?\*/|//.*", "", item, flags=re.DOTALL).strip()
            if not token:
                continue
            original = re.split(r"\s+as\s+", token, maxsplit=1)[0].strip()
            declaration = re.search(
                rf"(?m)^\s*export\s+(?:declare\s+)?(?:interface|type|class|enum)\s+{re.escape(original)}\b",
                target_source,
            )
            if declaration is None:
                raise RuntimeError(
                    f"TypeScript oracle cannot find {original} in {_relative(root, target)}"
                )
            found.add((original, _relative(root, target)))
    if not found:
        raise RuntimeError("TypeScript oracle found no named type re-exports")
    return found


def _external_import_subclass_abstention(root: Path, oracle: dict[str, Any]) -> set[Fact]:
    symbol = re.escape(str(oracle["symbol"]))
    module = re.escape(str(oracle["module"]))
    occurrences = 0
    for path in _tracked(root, (".js", ".jsx", ".ts", ".tsx")):
        source = path.read_text(encoding="utf-8", errors="replace")
        if not re.search(rf"\bextends\s+{symbol}\b", source):
            continue
        occurrences += 1
        imported = re.search(
            rf"\bimport\s+(?:[^\n;]*\b{symbol}\b[^\n;]*)\s+from\s+['\"]{module}['\"]",
            source,
        )
        if imported is None:
            raise RuntimeError(
                f"{symbol} subclass is not proven external in {_relative(root, path)}"
            )
    if occurrences == 0:
        raise RuntimeError("external-import abstention oracle found no subclasses")
    return set()


def _go_text_callers(root: Path, oracle: dict[str, Any]) -> set[Fact]:
    symbol = str(oracle["symbol"])
    definition = re.compile(rf"^\s*func\s+(?:\([^)]*\)\s*)?{re.escape(symbol)}\s*\(")
    call = re.compile(rf"\b{re.escape(symbol)}\s*\(")
    function = re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)\s*\(")
    found: set[Fact] = set()
    for path in _tracked(root, (".go",)):
        current = ""
        depth = 0
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            match = function.match(line)
            if match and depth == 0:
                current = match.group(1)
            if current and call.search(line) and not definition.match(line):
                found.add((current, _relative(root, path)))
            depth += line.count("{") - line.count("}")
            if depth <= 0:
                depth = 0
                current = ""
    if not found:
        raise RuntimeError(f"Go source oracle found no caller for {symbol}")
    return found


def _rust_group(tokens: list[str], position: int, prefix: list[str]) -> tuple[list[list[str]], int]:
    paths: list[list[str]] = []
    while position < len(tokens):
        token = tokens[position]
        if token == "}":
            return paths, position + 1
        if token == ",":
            position += 1
            continue
        if not re.fullmatch(r"[A-Za-z_]\w*", token):
            raise RuntimeError(f"unexpected Rust use token: {token}")
        name = token
        position += 1
        if position + 1 < len(tokens) and tokens[position] == "::" and tokens[position + 1] == "{":
            nested, position = _rust_group(tokens, position + 2, [*prefix, name])
            paths.extend(nested)
        elif (
            position + 1 < len(tokens)
            and tokens[position] == "::"
            and re.fullmatch(r"[A-Za-z_]\w*", tokens[position + 1])
        ):
            paths.append([*prefix, name, tokens[position + 1]])
            position += 2
        else:
            paths.append([*prefix, name])
    raise RuntimeError("unterminated Rust use group")


def _rust_crate_named_reexports(root: Path, oracle: dict[str, Any]) -> set[Fact]:
    path = root / str(oracle["file"])
    source = path.read_text(encoding="utf-8")
    match = re.search(r"\bpub\s+use\s+crate::\{(.*?)\};", source, flags=re.DOTALL)
    if match is None:
        raise RuntimeError("Rust oracle found no crate re-export group")
    tokens = re.findall(r"::|[{},]|[A-Za-z_]\w*", match.group(1)) + ["}"]
    paths, consumed = _rust_group(tokens, 0, [])
    if consumed != len(tokens):
        raise RuntimeError("Rust oracle did not consume the complete re-export group")
    found: set[Fact] = set()
    for parts in paths:
        if len(parts) < 2:
            raise RuntimeError(f"Rust oracle needs module-qualified item: {parts}")
        module, name = parts[0], parts[-1]
        target = path.parent / f"{module}.rs"
        if not target.is_file():
            target = path.parent / module / "mod.rs"
        target_source = target.read_text(encoding="utf-8")
        definition = re.search(
            rf"(?m)^\s*pub\s+(?:struct|enum|fn|type|trait|const|static)\s+"
            rf"{re.escape(name)}\b",
            target_source,
        )
        if definition is None:
            raise RuntimeError(f"Rust oracle cannot find {name} in {_relative(root, target)}")
        found.add((name, _relative(root, target)))
    return found


def _rust_external_use_abstention(root: Path, oracle: dict[str, Any]) -> set[Fact]:
    path = root / str(oracle["file"])
    source = path.read_text(encoding="utf-8")
    module = re.escape(str(oracle["module"]))
    symbol = re.escape(str(oracle["symbol"]))
    if re.search(rf"\buse\s+{module}::{symbol}\s*;", source) is None:
        raise RuntimeError("Rust external-use oracle could not verify the declared import")
    return set()


def _java_direct_subclasses(root: Path, oracle: dict[str, Any]) -> set[Fact]:
    subject = re.escape(str(oracle["symbol"]))
    declaration = re.compile(
        rf"\b(?:class|record)\s+([A-Za-z_]\w*)[^{{;]*?\bextends\s+{subject}\b"
    )
    found: set[Fact] = set()
    for path in _tracked(root, (".java",)):
        source = path.read_text(encoding="utf-8", errors="replace")
        found.update((name, _relative(root, path)) for name in declaration.findall(source))
    return found


def _java_in_file_callees(root: Path, oracle: dict[str, Any]) -> set[Fact]:
    path = root / str(oracle["file"])
    source = path.read_text(encoding="utf-8")
    symbol = str(oracle["symbol"])
    method_pattern = (
        rf"(?m)^\s*(?:public|protected|private)\s+(?:static\s+)?"
        rf"[\w<>?\[\], ]+\s+{re.escape(symbol)}\s*\([^)]*\)\s*\{{"
    )
    signature = re.search(
        method_pattern,
        source,
    )
    if signature is None:
        raise RuntimeError(f"Java oracle cannot find method {symbol}")
    start = signature.end()
    depth = 1
    end = start
    while end < len(source) and depth:
        depth += source[end] == "{"
        depth -= source[end] == "}"
        end += 1
    if depth:
        raise RuntimeError(f"Java oracle found unterminated body for {symbol}")
    body = source[start : end - 1]
    called = set(re.findall(r"\b([A-Za-z_]\w*)\s*\(", body))
    defined = set(
        re.findall(
            r"(?m)^\s*(?:public|protected|private)\s+(?:static\s+)?"
            r"[\w<>?\[\], ]+\s+([A-Za-z_]\w*)\s*\([^)]*\)\s*\{",
            source,
        )
    )
    relative = _relative(root, path)
    return {(name, relative) for name in called & defined}


ORACLES: dict[str, Callable[[Path, dict[str, Any]], set[Fact]]] = {
    "python_direct_subclasses": _python_direct_subclasses,
    "python_in_repo_callees": _python_in_repo_callees,
    "javascript_relative_requires": _javascript_relative_requires,
    "javascript_commonjs_local_reexports": _javascript_commonjs_local_reexports,
    "typescript_named_type_reexports": _typescript_named_type_reexports,
    "external_import_subclass_abstention": _external_import_subclass_abstention,
    "go_text_callers": _go_text_callers,
    "rust_crate_named_reexports": _rust_crate_named_reexports,
    "rust_external_use_abstention": _rust_external_use_abstention,
    "java_direct_subclasses": _java_direct_subclasses,
    "java_in_file_callees": _java_in_file_callees,
}


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 1.0


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    tp = sum(row["true_positives"] for row in rows)
    fp = sum(row["false_positives"] for row in rows)
    fn = sum(row["false_negatives"] for row in rows)
    unsupported = sum(not row["query_supported"] for row in rows)
    wrong_file = sum(row["wrong_file"] for row in rows)
    wrong_symbol = sum(row["wrong_symbol"] for row in rows)
    return {
        "facts": len(rows),
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "precision": _ratio(tp, tp + fp),
        "recall": _ratio(tp, tp + fn),
        "false_positive_rate": _ratio(fp, tp + fp),
        "false_negative_rate": _ratio(fn, tp + fn),
        "unsupported_rate": _ratio(unsupported, len(rows)),
        "wrong_file_rate": _ratio(wrong_file, tp + fp),
        "wrong_symbol_rate": _ratio(wrong_symbol, tp + fp),
        "exact_set_accuracy": _ratio(sum(row["exact_match"] for row in rows), len(rows)),
        "stale_edge_rate": "NOT_MEASURED_IN_STATIC_TRUTH_CORPUS",
    }


def _markdown(report: dict[str, Any], receipt_path: Path) -> str:
    overall = report["metrics"]
    lines = [
        "# Graph Truth Audit",
        "",
        f"Observed: `{report['completed']}`",
        "",
        f"Receipt: `{receipt_path}`",
        "",
        f"Verdict: **{report['status']}**",
        "",
        "Expected facts were derived from frozen repository source by the independent oracles in "
        "`scripts/graph_truth_audit.py`; GT output was used only as the system under test.",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    for key in (
        "facts", "true_positives", "false_positives", "false_negatives", "precision",
        "recall", "false_positive_rate", "false_negative_rate", "unsupported_rate",
        "wrong_file_rate", "wrong_symbol_rate", "exact_set_accuracy", "stale_edge_rate",
    ):
        lines.append(f"| {key} | {overall[key]} |")
    lines.extend(
        [
            "",
            "## Fact results",
            "",
            "| Fact | Language | Relationship | Result | TP | FP | FN | Latency ms |",
            "| --- | --- | --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in report["facts"]:
        lines.append(
            f"| {row['id']} | {row['language']} | {row['relationship']} | "
            f"{'PASS' if row['exact_match'] else 'FAIL'} | {row['true_positives']} | "
            f"{row['false_positives']} | {row['false_negatives']} | {row['latency_ms']} |"
        )
    lines.extend(
        [
            "",
            "## Scope",
            "",
            "This is a bounded, reproducible real-repository sample, not a claim of "
            "universal graph accuracy. Stale-edge behavior is intentionally deferred to "
            "the separate lifecycle campaign.",
            "",
            "Reproduce (PowerShell):",
            "",
            "```powershell",
            "python scripts/graph_truth_audit.py --workspace "
            "D:\\gt-product-audit-5296dc3 --output "
            "D:\\gt-product-audit-5296dc3\\receipts\\graph-truth.json "
            "--report GRAPH_TRUTH_AUDIT.md",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--facts", default="audit/graph_truth_facts.v1.json")
    parser.add_argument("--matrix", default="audit/real_repository_matrix.v1.json")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report")
    args = parser.parse_args(argv)

    facts_manifest = json.loads(Path(args.facts).read_text(encoding="utf-8"))
    matrix = json.loads(Path(args.matrix).read_text(encoding="utf-8"))
    if facts_manifest.get("schema") != "gt.graph_truth_facts.v1":
        raise SystemExit("unsupported graph truth schema")
    commits = {row["id"]: row["commit"] for row in matrix["repositories"]}
    workspace = Path(args.workspace).resolve()
    rows: list[dict[str, Any]] = []
    for fact in facts_manifest["facts"]:
        repository_id = str(fact["repository_id"])
        root = workspace / "repositories" / repository_id
        state = workspace / "states" / repository_id
        expected_commit = commits[repository_id]
        observed_commit = _git(root, "rev-parse", "HEAD")
        if observed_commit != expected_commit or _git(root, "status", "--porcelain=v1"):
            raise SystemExit(f"repository identity is not frozen and clean: {repository_id}")
        oracle = fact["oracle"]
        expected = ORACLES[str(oracle["kind"])](root, oracle)
        service = RepositoryGraphService(root, state_dir=state)
        receipt = service.status()
        query_started = time.perf_counter()
        query = fact["query"]
        result = service.query(
            str(query["mode"]), str(query["symbol"]), file_path=query.get("file"), limit=1000
        )
        latency_ms = round((time.perf_counter() - query_started) * 1000.0, 3)
        actual = {
            (str(item.get("name") or ""), str(item.get("file_path") or ""))
            for item in result.get("evidence", [])
        }
        tp_set = actual & expected
        fp_set = actual - expected
        fn_set = expected - actual
        expected_names = {name for name, _path in expected}
        expected_paths_by_name: dict[str, set[str]] = defaultdict(set)
        for name, path in expected:
            expected_paths_by_name[name].add(path)
        wrong_file = sum(
            name in expected_paths_by_name and path not in expected_paths_by_name[name]
            for name, path in fp_set
        )
        wrong_symbol = sum(name not in expected_names for name, _path in fp_set)
        query_supported = result.get("status") == "READY"
        row = {
            "id": fact["id"],
            "repository_id": repository_id,
            "commit_sha": observed_commit,
            "graph_identity": receipt.graph_checksum_or_identity,
            "graph_status": receipt.build_status.value,
            "language": fact["language"],
            "relationship": fact["relationship"],
            "query": query,
            "oracle": oracle,
            "query_supported": query_supported,
            "expected": [{"name": name, "file_path": path} for name, path in sorted(expected)],
            "actual": [{"name": name, "file_path": path} for name, path in sorted(actual)],
            "true_positives": len(tp_set),
            "false_positives": len(fp_set),
            "false_negatives": len(fn_set),
            "wrong_file": wrong_file,
            "wrong_symbol": wrong_symbol,
            "exact_match": query_supported and not fp_set and not fn_set,
            "latency_ms": latency_ms,
        }
        rows.append(row)
        print(json.dumps({"id": row["id"], "exact_match": row["exact_match"]}), flush=True)

    grouped: dict[str, dict[str, Any]] = {}
    for field in ("language", "relationship"):
        for value in sorted({str(row[field]) for row in rows}):
            grouped[f"{field}:{value}"] = _metrics([row for row in rows if row[field] == value])
    report = {
        "schema": "gt.graph_truth_audit_receipt.v1",
        "started_from_frozen_clean_checkouts": True,
        "provider_calls": 0,
        "provider_credentials_inspected": False,
        "facts_manifest": str(Path(args.facts).resolve()),
        "facts": rows,
        "metrics": _metrics(rows),
        "metrics_by_dimension": grouped,
        "status": "PASS" if rows and all(row["exact_match"] for row in rows) else "FAIL",
        "completed": _now(),
    }
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.report:
        Path(args.report).write_text(_markdown(report, output), encoding="utf-8")
    print(json.dumps({"status": report["status"], "receipt": str(output)}), flush=True)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
