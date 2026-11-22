"""Check the import-linter contracts without import-linter's native module.

Windows Application Control blocks grimp's compiled extension on the development host
(docs/ENVIRONMENT.md), so this pure-Python check reads the same contracts from pyproject.toml and
applies them transitively over an AST import graph (every import, including function-local and
TYPE_CHECKING ones, as grimp does). CI runs the real import-linter as well.

    python scripts/check_imports.py           # exit 1 on a broken contract
"""

from __future__ import annotations

import ast
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build_graph(package: str) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    pkg_dir = ROOT / package
    mods: dict[str, Path] = {}
    for p in pkg_dir.rglob("*.py"):
        parts = list(p.relative_to(ROOT).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        mods[".".join(parts)] = p

    def resolve(name: str) -> str | None:
        while name:
            if name in mods:
                return name
            name = name.rpartition(".")[0]
        return None

    graph: dict[str, set[str]] = {m: set() for m in mods}
    external: dict[str, set[str]] = {m: set() for m in mods}
    for m, p in mods.items():
        pkg = m if p.name == "__init__.py" else m.rpartition(".")[0]
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    anchor = pkg.split(".")[: len(pkg.split(".")) - (node.level - 1)]
                    base = ".".join(anchor + ([base] if base else []))
                names = [base] + [f"{base}.{a.name}" for a in node.names]
            for n in names:
                if n.split(".")[0] == package:
                    r = resolve(n)
                    if r and r != m:
                        graph[m].add(r)
                elif n:
                    external[m].add(n.split(".")[0])
    return graph, external


def under(m: str, pkg: str) -> bool:
    return m == pkg or m.startswith(pkg + ".")


def reach(graph: dict[str, set[str]], start: str) -> dict[str, str]:
    seen = {start: ""}
    stack = [start]
    while stack:
        cur = stack.pop()
        for nxt in graph[cur]:
            if nxt not in seen:
                seen[nxt] = cur
                stack.append(nxt)
    return seen


def chain(seen: dict[str, str], end: str) -> str:
    out = [end]
    while seen[out[-1]]:
        out.append(seen[out[-1]])
    return " -> ".join(reversed(out))


def main() -> int:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"][
        "importlinter"
    ]
    package = config["root_package"]
    graph, external = build_graph(package)
    errors: list[str] = []
    for c in config["contracts"]:
        name = c["name"]
        if c["type"] == "forbidden":
            for m in graph:
                if not any(under(m, s) for s in c["source_modules"]):
                    continue
                seen = reach(graph, m)
                for r in seen:
                    for banned in c["forbidden_modules"]:
                        if banned.split(".")[0] == package and under(r, banned):
                            errors.append(f"{name}: {chain(seen, r)}")
                        elif banned.split(".")[0] != package and banned in external[r]:
                            errors.append(f"{name}: {chain(seen, r)} imports {banned}")
        elif c["type"] == "layers":
            layers = c["layers"]
            for i, low in enumerate(layers):
                for m in graph:
                    if not under(m, low):
                        continue
                    seen = reach(graph, m)
                    for r in seen:
                        if any(under(r, h) for h in layers[:i]):
                            errors.append(f"{name}: {chain(seen, r)}")
        else:
            errors.append(f"{name}: contract type {c['type']!r} is not supported here")
    for e in sorted(set(errors)):
        print("BROKEN", e)
    n = len(config["contracts"])
    print(
        f"{len(graph)} modules: {n} contracts "
        + ("kept" if not errors else f"broken ({len(set(errors))})")
    )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
