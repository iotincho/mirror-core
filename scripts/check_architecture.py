"""Check hexagonal import boundaries without importing application code.

Standard library only. Legacy exceptions identify one source/import edge and must
be removed when no longer needed. No command automatically accepts new exceptions.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import tomllib
from dataclasses import asdict, dataclass
from importlib.util import resolve_name
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = Path("config/architecture-exceptions.json")
NAME = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*\Z")
SOURCE_REFERENCE = re.compile(r"\bsrc(?:\.[A-Za-z_]\w*)+(?::[A-Za-z_]\w*)?")
LAYERS = {"core", "use_cases", "adapters", "bootstrap"}
ACCESS_LIBRARIES = {"fastapi", "starlette", "taskiq", "fastapi_users", "pydantic"}


@dataclass(frozen=True, order=True)
class ImportEdge:
    source: str
    line: int
    target: str
    kind: str = "static"

    @property
    def key(self):
        return self.source, self.target


def module_name(path: Path) -> str:
    parts = list(path.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def call_name(node, aliases):
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        parent = call_name(node.value, aliases)
        return f"{parent}.{node.attr}" if parent else None
    return None


def imports_in(path: Path, text: str) -> tuple[list[ImportEdge], list[dict]]:
    """Resolve absolute, relative and function-local imports, including aliases."""
    tree = ast.parse(text, filename=str(path))
    source = path.as_posix()
    module = module_name(path)
    package = module if path.name == "__init__.py" else module.rpartition(".")[0]
    edges, dynamic, aliases = [], [], {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for name in node.names:
                edges.append(ImportEdge(source, node.lineno, name.name))
                aliases[name.asname or name.name.split(".")[0]] = (
                    name.name if name.asname else name.name.split(".")[0]
                )
        elif isinstance(node, ast.ImportFrom):
            target = node.module or ""
            if node.level:
                target = resolve_name("." * node.level + target, package)
            for name in node.names:
                imported = f"{target}.{name.name}"
                edges.append(ImportEdge(source, node.lineno, imported))
                aliases[name.asname or name.name] = imported

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = call_name(node.func, aliases)
        if name not in {"__import__", "importlib.import_module"}:
            continue
        literal = node.args[0] if node.args else None
        target = literal.value if isinstance(literal, ast.Constant) else None
        extra_targets = []
        if name == "__import__" and isinstance(target, str):
            try:
                level_arg = next((kw.value for kw in node.keywords if kw.arg == "level"),
                                 node.args[4] if len(node.args) > 4 else ast.Constant(0))
                level = ast.literal_eval(level_arg)
                if not isinstance(level, int) or level < 0:
                    raise ValueError("unknown import level")
                if level:
                    target = resolve_name("." * level + target, package)
                fromlist_arg = next((kw.value for kw in node.keywords if kw.arg == "fromlist"),
                                    node.args[3] if len(node.args) > 3 else ast.Tuple(elts=[]))
                fromlist = ast.literal_eval(fromlist_arg)
                if not isinstance(fromlist, (tuple, list)) or any(
                    not isinstance(item, str) or not NAME.fullmatch(item) for item in fromlist
                ):
                    raise ValueError("unknown import fromlist")
                extra_targets = [f"{target}.{item}" for item in fromlist]
            except (ValueError, TypeError):
                target = None
        if isinstance(target, str) and target.startswith("."):
            package_arg = node.args[1] if len(node.args) > 1 else next(
                (kw.value for kw in node.keywords if kw.arg == "package"), None
            )
            relative_package = (
                package_arg.value if isinstance(package_arg, ast.Constant)
                else package if isinstance(package_arg, ast.Name)
                and package_arg.id == "__package__" else None
            )
            target = resolve_name(target, relative_package) if relative_package else None
        dynamic.append({"source": source, "line": node.lineno,
                        "expression": ast.unparse(node), "resolved": target})
        if isinstance(target, str):
            edges.append(ImportEdge(source, node.lineno, target, "dynamic"))
            edges.extend(ImportEdge(source, node.lineno, item, "dynamic") for item in extra_targets)
    return edges, dynamic


def scan(root: Path):
    edges, dynamic, sources = [], [], []
    for path in sorted((root / "src").rglob("*.py")):
        source = path.relative_to(root)
        imported, calls = imports_in(source, path.read_text(encoding="utf-8"))
        sources.append(source.as_posix())
        edges.extend(imported)
        dynamic.extend(calls)
    return sorted(set(edges)), dynamic, sources


def within(target: str, namespace: str) -> bool:
    return target == namespace or target.startswith(namespace + ".")


def violation(edge: ImportEdge) -> str | None:
    parts = Path(edge.source).parts
    area = parts[1] if len(parts) > 2 else "legacy"
    if within(edge.target, "src.bootstrap") and area != "bootstrap":
        return "bootstrap must not be imported by other layers"
    if edge.target.endswith(".*"):
        return "wildcard imports cannot establish a bounded dependency"
    if area == "bootstrap":
        return None
    external = edge.target.split(".")[0]
    standard = external in sys.stdlib_module_names
    if area in {"core", "domain", "use_cases"}:
        allowed = ["src.core"]
        if area == "domain":
            allowed.append("src.domain")
        if area == "use_cases":
            allowed.append("src.use_cases")
        if standard or external == "pydantic" or any(
            within(edge.target, name) for name in allowed
        ):
            return None
        return f"{area} depends on infrastructure or a legacy module"
    if area == "adapters":
        if within(edge.target, "src.core") or standard:
            return None
        role = parts[2] if len(parts) > 3 else ""
        if role == "access":
            if any(within(edge.target, prefix) for prefix in (
                "src.use_cases", "src.adapters.access"
            )) or external in ACCESS_LIBRARIES:
                return None
            return "access must invoke application contracts, not output adapters or SDKs"
        if role in {"storage", "providers", "messaging"}:
            if external != "src":
                return None
            own_adapter = ".".join(parts[:4]) if len(parts) > 4 else ""
            if own_adapter and within(edge.target, own_adapter):
                return None
            return "output adapters may depend on core and their own implementation"
        return "adapter must belong to access, storage, providers or messaging"
    return None


def validate_policy(policy: dict):
    if policy.get("version") != 1:
        raise ValueError("architecture policy must declare version 1")
    legacy = policy.get("legacy_files", [])
    if len(set(legacy)) != len(legacy):
        raise ValueError("duplicate legacy file")
    for source in legacy:
        if not source.startswith("src/") or any(char in source for char in "*?["):
            raise ValueError(f"legacy entry must be an exact source path: {source}")
    keys = set()
    for entry in policy.get("exceptions", []):
        source, target = entry["source"], entry["target"]
        if not source.startswith("src/") or any(char in source for char in "*?[") \
                or not NAME.fullmatch(target):
            raise ValueError("exceptions require an exact source and import, without wildcards")
        if not entry.get("reason", "").strip() or not entry.get("remove_in", "").strip():
            raise ValueError("exceptions require reason and removal stage")
        if (source, target) in keys:
            raise ValueError("duplicate architectural exception")
        keys.add((source, target))


def audit(root: Path, policy: dict):
    validate_policy(policy)
    edges, dynamic, sources = scan(root)
    expected = {(entry["source"], entry["target"]) for entry in policy.get("exceptions", [])}
    blocked = {edge.key for edge in edges if violation(edge)}
    failures = [f"{edge.source}:{edge.line}: {edge.target}: {violation(edge)}"
                for edge in edges if edge.key in blocked - expected]
    failures.extend(f"stale exception: {source} -> {target}"
                    for source, target in sorted(expected - blocked))
    legacy = set(policy.get("legacy_files", []))
    actual_legacy = {source for source in sources if source != "src/__init__.py"
                     and Path(source).parts[1] not in LAYERS}
    failures.extend(f"new module outside target layout: {source}"
                    for source in sorted(actual_legacy - legacy))
    failures.extend(f"stale legacy file entry: {source}"
                    for source in sorted(legacy - actual_legacy))
    failures.extend(f"adapter outside a defined role: {source}"
                    for source in sources if source.startswith("src/adapters/")
                    and source != "src/adapters/__init__.py"
                    and Path(source).parts[2] not in {
                        "access", "storage", "providers", "messaging"
                    })
    failures.extend(f"{call['source']}:{call['line']}: unresolved dynamic import requires review"
                    for call in dynamic if not call["resolved"])
    return failures, edges, dynamic, sources


def inventory(root: Path, edges, dynamic, sources):
    """Record static references only; never inspect .env, user files or runtime state."""
    references, process_commands = [], []
    paths = set()
    for directory in ("tests", "scripts", "migrations", ".github/workflows"):
        paths.update(path for path in (root / directory).rglob("*")
                     if path.suffix in {".py", ".yml", ".yaml"})
    paths.update(root / name for name in (
        "Dockerfile", "Dockerfile.prod", "docker-compose.yml", "deploy.sh", "admin-local.sh",
        "pyproject.toml", "alembic.ini",
    ))
    for path in sorted(paths):
        if not path.is_file():
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for target in sorted(set(SOURCE_REFERENCE.findall(line))):
                references.append({"source": path.relative_to(root).as_posix(),
                                   "line": number, "target": target})
            if path.name in {"Dockerfile", "Dockerfile.prod", "docker-compose.yml",
                             "deploy.sh", "admin-local.sh"} and re.search(
                r"^\s*(?:command:|entrypoint:|CMD\b|ENTRYPOINT\b)|"
                r"\b(?:uvicorn|taskiq|alembic|python(?:3)?)\b", line
            ):
                process_commands.append({"source": path.name, "line": number,
                                         "command": line.strip()})
    composition = []
    for source in sources:
        if Path(source).name not in {"dependencies.py", "runtime.py", "workflows.py"}:
            continue
        tree = ast.parse((root / source).read_text(encoding="utf-8"))
        composition.append({"source": source, "functions": [
            {"name": node.name, "line": node.lineno} for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]})
    project = tomllib.loads((root / "pyproject.toml").read_text())
    return {"sources": sources, "imports": [asdict(edge) for edge in edges],
            "dynamic_imports": dynamic, "composition_candidates": composition,
            "consumer_references": references,
            "inspected_consumers": sorted(path.relative_to(root).as_posix()
                                          for path in paths if path.is_file()),
            "process_commands": process_commands,
            "package_data": project.get("tool", {}).get("setuptools", {}).get("package-data", {})}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, help="write a reproducible static JSON inventory")
    args = parser.parse_args()
    try:
        policy = json.loads((ROOT / POLICY).read_text(encoding="utf-8"))
        failures, edges, dynamic, sources = audit(ROOT, policy)
        if args.inventory:
            data = inventory(ROOT, edges, dynamic, sources)
            args.inventory.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    except (ValueError, KeyError, OSError, ImportError, SyntaxError) as error:
        print(f"Architecture check failed: {error}", file=sys.stderr)
        return 1
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(f"OK: {len(sources)} modules, {len(edges)} imports; "
          f"{len(policy['exceptions'])} exact legacy edges; "
          f"{len(dynamic)} dynamic imports reviewed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
