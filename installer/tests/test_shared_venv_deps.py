"""Drift-detection: every plugin's runtime deps must be in the shared-venv extras.

The shared marketplace venv is built via `uv sync --frozen --extra plugins` against
the root pyproject.toml's `[project.optional-dependencies].plugins`. start.sh wires
each plugin to that venv at runtime, so any per-plugin dep missing from the extras
list yields ImportError when the MCP server starts.

This test is the canary for that drift. Add a new dep to a plugin → also add it to
the root pyproject's plugins extra, or this test fails.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGINS_DIR = REPO_ROOT / "plugins"


def _names_from_specs(specs: list[str]) -> set[str]:
    names: set[str] = set()
    for spec in specs:
        try:
            req = Requirement(spec)
        except Exception:
            continue
        names.add(canonicalize_name(req.name))
    return names


def _root_plugins_extra() -> set[str]:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    extras = data.get("project", {}).get("optional-dependencies", {})
    return _names_from_specs(extras.get("plugins", []))


def _plugin_runtime_deps() -> dict[str, set[str]]:
    """Return {plugin_name: {dep_name, ...}} for every plugin/server/pyproject.toml."""
    out: dict[str, set[str]] = {}
    for server_pyproject in sorted(PLUGINS_DIR.glob("*/server/pyproject.toml")):
        plugin_name = server_pyproject.parents[1].name
        if plugin_name == "_shared":
            continue
        data = tomllib.loads(server_pyproject.read_text())
        deps = data.get("project", {}).get("dependencies", [])
        out[plugin_name] = _names_from_specs(deps)
    return out


def test_every_plugin_runtime_dep_is_in_shared_venv_extras():
    """Per-plugin runtime deps must be a subset of root pyproject's plugins extra."""
    extras = _root_plugins_extra()
    plugin_deps = _plugin_runtime_deps()
    assert plugin_deps, "no plugins discovered — glob may be wrong"

    missing: dict[str, set[str]] = {}
    for plugin, deps in plugin_deps.items():
        gap = deps - extras
        if gap:
            missing[plugin] = gap

    assert not missing, (
        "Plugin runtime dep(s) missing from root pyproject.toml "
        "[project.optional-dependencies].plugins:\n"
        + "\n".join(f"  {p}: {sorted(g)}" for p, g in sorted(missing.items()))
        + "\nAdd them to the shared venv extras or the shared venv won't import "
        "them at runtime."
    )


def test_at_least_one_plugin_discovered():
    plugin_deps = _plugin_runtime_deps()
    assert len(plugin_deps) >= 6, (
        f"expected ≥6 plugins, found {len(plugin_deps)}: {sorted(plugin_deps)}"
    )
