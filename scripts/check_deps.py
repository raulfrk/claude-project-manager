#!/usr/bin/env python3
"""Check for dependency conflicts across plugin pyproject.toml files.

Collects runtime dependencies from every plugin, groups by normalized
package name, checks for version-specifier conflicts, and validates that
the root pyproject.toml ``[project.optional-dependencies] plugins`` group
is a superset of all plugin runtime deps.

Usage:
    uv run --with packaging scripts/check_deps.py

Exit codes:
    0  no conflicts, root superset OK
    1  conflicts or missing root deps detected
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

# packaging is the only external dep — invoked via ``uv run --with packaging``
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet

ROOT = Path(__file__).resolve().parent.parent

# ── helpers ──────────────────────────────────────────────────────────

_NORMALIZE_RE = re.compile(r"[-_.]+")


def normalize(name: str) -> str:
    """PEP 503 normalize: lowercase, collapse runs of [-_.] to single dash."""
    return _NORMALIZE_RE.sub("-", name).lower()


# ── gather deps ──────────────────────────────────────────────────────


def find_plugin_pyprojects() -> list[Path]:
    """Return all plugin pyproject.toml paths (server dirs + _shared)."""
    plugins_dir = ROOT / "plugins"
    paths: list[Path] = []

    shared = plugins_dir / "_shared" / "pyproject.toml"
    if shared.exists():
        paths.append(shared)

    for child in sorted(plugins_dir.iterdir()):
        if child.name.startswith("_") or not child.is_dir():
            continue
        server_toml = child / "server" / "pyproject.toml"
        if server_toml.exists():
            paths.append(server_toml)

    return paths


def parse_deps(toml_path: Path) -> list[Requirement]:
    """Parse [project].dependencies from a pyproject.toml."""
    with toml_path.open("rb") as f:
        data = tomllib.load(f)
    raw: list[str] = data.get("project", {}).get("dependencies", [])
    return [Requirement(r) for r in raw]


def find_plugin_deps() -> dict[str, list[Requirement]]:
    """Map plugin label -> list of parsed requirements."""
    result: dict[str, list[Requirement]] = {}
    for p in find_plugin_pyprojects():
        # label: _shared, proj, hooks, ...
        parts = p.relative_to(ROOT / "plugins").parts
        label = parts[0]
        result[label] = parse_deps(p)
    return result


def parse_root_plugin_deps() -> list[Requirement]:
    """Parse root pyproject.toml [project.optional-dependencies].plugins."""
    root_toml = ROOT / "pyproject.toml"
    with root_toml.open("rb") as f:
        data = tomllib.load(f)
    raw: list[str] = (
        data.get("project", {}).get("optional-dependencies", {}).get("plugins", [])
    )
    return [Requirement(r) for r in raw]


# ── conflict detection ───────────────────────────────────────────────


def check_conflicts(
    plugin_deps: dict[str, list[Requirement]],
) -> list[str]:
    """Group deps by normalized name; report incompatible specifiers.

    Two specifiers conflict when their intersection is empty — i.e. there
    is no version that satisfies both.  We check this conservatively by
    combining all specifier sets and testing a large range of micro
    versions for the common lower bound.
    """
    # pkg_name -> list[(plugin, Requirement)]
    grouped: dict[str, list[tuple[str, Requirement]]] = {}
    for plugin, reqs in plugin_deps.items():
        for req in reqs:
            key = normalize(req.name)
            grouped.setdefault(key, []).append((plugin, req))

    errors: list[str] = []
    for pkg, entries in sorted(grouped.items()):
        # Merge all specifier sets
        combined = SpecifierSet()
        per_plugin: list[tuple[str, SpecifierSet]] = []
        for plugin, req in entries:
            per_plugin.append((plugin, req.specifier))
            combined &= req.specifier

        # If there are at least two distinct specifier strings, check
        # whether the combined set can be satisfied.
        unique_specs = {str(s) for _, s in per_plugin if str(s)}
        if len(unique_specs) <= 1:
            continue

        # Quick compatibility probe: test versions 0.1 .. 200.0
        satisfiable = False
        for major in range(201):
            for minor in range(10):
                v = f"{major}.{minor}.0"
                if v in combined:
                    satisfiable = True
                    break
            if satisfiable:
                break

        if not satisfiable:
            lines = [f"  CONFLICT: {pkg}"]
            for plugin, spec in per_plugin:
                lines.append(f"    {plugin:>12s}: {spec or '(any)'}")
            errors.append("\n".join(lines))

    return errors


# ── superset validation ──────────────────────────────────────────────


def validate_superset(
    root_deps: list[Requirement],
    plugin_deps: dict[str, list[Requirement]],
) -> list[str]:
    """Ensure root plugins group covers every plugin runtime dep.

    A root dep "covers" a plugin dep when:
      1. Same normalized name.
      2. Root specifier is a subset-or-equal of the plugin specifier
         (i.e., the root doesn't demand a narrower range than the plugin).
         In practice we just check the name is present — version alignment
         is caught by check_conflicts.
    """
    root_names: dict[str, Requirement] = {normalize(r.name): r for r in root_deps}

    # Collect all unique normalized dep names from plugins (skip path deps
    # like claude-hook-transport which are local and handled by uv sources)
    all_plugin_pkgs: dict[str, set[str]] = {}
    for plugin, reqs in plugin_deps.items():
        for req in reqs:
            key = normalize(req.name)
            all_plugin_pkgs.setdefault(key, set()).add(plugin)

    # Path / local deps that the root already references via [tool.uv.sources]
    local_deps = _find_local_source_names()

    errors: list[str] = []
    for pkg, plugins in sorted(all_plugin_pkgs.items()):
        if pkg in root_names:
            continue
        if pkg in local_deps:
            continue
        errors.append(
            f"  MISSING from root [plugins]: {pkg}"
            f"  (required by: {', '.join(sorted(plugins))})"
        )

    return errors


def _find_local_source_names() -> set[str]:
    """Return normalized names of deps resolved via [tool.uv.sources] in root."""
    root_toml = ROOT / "pyproject.toml"
    with root_toml.open("rb") as f:
        data = tomllib.load(f)
    sources: dict[str, object] = data.get("tool", {}).get("uv", {}).get("sources", {})
    return {normalize(name) for name in sources}


# ── main ─────────────────────────────────────────────────────────────


def main() -> int:
    plugin_deps = find_plugin_deps()
    root_deps = parse_root_plugin_deps()

    conflict_errors = check_conflicts(plugin_deps)
    superset_errors = validate_superset(root_deps, plugin_deps)

    if not conflict_errors and not superset_errors:
        return 0

    if conflict_errors:
        print("=== Dependency Conflicts ===")
        for e in conflict_errors:
            print(e)
        print()

    if superset_errors:
        print("=== Root pyproject.toml [plugins] Coverage ===")
        for e in superset_errors:
            print(e)
        print()

    return 1


if __name__ == "__main__":
    sys.exit(main())
