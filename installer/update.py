"""Plugin version comparison utilities (used by TUI update flow in app.py)."""

from __future__ import annotations

import json
from pathlib import Path

from installer.detect import InstallState
from installer.errors import InstallerError
from installer.plugin_cli import get_installed_plugin_versions


# Overridable by tests via monkeypatch.setattr("installer.update._MARKETPLACE_PATH", path)
_MARKETPLACE_PATH: Path | None = None


def _resolve_marketplace_path() -> Path:
    """Resolve marketplace.json path with fallback for source tree."""
    bundled = Path(__file__).resolve().parent / "marketplace.json"
    if bundled.exists():
        return bundled
    return (
        Path(__file__).resolve().parent.parent / ".claude-plugin" / "marketplace.json"
    )


def _read_marketplace_versions(marketplace_path: Path | None = None) -> dict[str, str]:
    """Read plugin versions from the bundled marketplace.json."""
    path = marketplace_path or _MARKETPLACE_PATH or _resolve_marketplace_path()
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        entry["name"]: entry.get("version", "0.0.0")
        for entry in data.get("plugins", [])
    }


def _read_installed_version(cache_dir: Path, plugin_name: str) -> str | None:
    """Read version for an installed plugin. CLI primary, disk fallback."""
    try:
        versions = get_installed_plugin_versions()
        if plugin_name in versions:
            return versions[plugin_name]
    except (InstallerError, FileNotFoundError, OSError):
        pass

    plugin_dir = cache_dir / plugin_name
    if not plugin_dir.is_dir():
        return None
    for version_dir in sorted(plugin_dir.iterdir(), reverse=True):
        if not version_dir.is_dir() or version_dir.name.startswith("."):
            continue
        for candidate in (
            version_dir / ".claude-plugin" / "plugin.json",
            version_dir / "plugin.json",
        ):
            if candidate.exists():
                try:
                    data = json.loads(candidate.read_text(encoding="utf-8"))
                    return data.get("version")
                except (OSError, json.JSONDecodeError):
                    continue
    return None


def compare_versions(
    state: InstallState, marketplace_path: Path | None = None
) -> dict[str, tuple[str, str]]:
    """Compare installed vs marketplace versions.

    Returns dict of plugin_name -> (installed_version, repo_version)
    for plugins where versions differ.
    """
    repo_versions = _read_marketplace_versions(marketplace_path)

    if state.cache_dir is None:
        return {}

    diffs: dict[str, tuple[str, str]] = {}
    for plugin_name in state.installed_plugins:
        installed_ver = _read_installed_version(state.cache_dir, plugin_name)
        repo_ver = repo_versions.get(plugin_name)
        if installed_ver is None or repo_ver is None:
            continue
        if installed_ver != repo_ver:
            diffs[plugin_name] = (installed_ver, repo_ver)

    return diffs
