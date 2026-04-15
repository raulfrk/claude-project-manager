"""Thin wrappers around ``claude plugin`` CLI subcommands."""

from __future__ import annotations

import json
import subprocess

from installer.errors import InstallerError

_MARKETPLACE_NAME = "claude-project-manager"
_MARKETPLACE_SOURCE = "raulfrk/claude-project-manager"
_TIMEOUT = 60


def _run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run *cmd* and return the result, raising on failure or timeout."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=_TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        raise InstallerError(
            f"Plugin CLI timed out after {_TIMEOUT}s: {' '.join(cmd)}"
        ) from exc
    if check and result.returncode != 0:
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        detail = stderr or stdout
        raise InstallerError(
            f"Command failed (exit {result.returncode}): {' '.join(cmd)}\n{detail}"
        )
    return result


def format_output(result: subprocess.CompletedProcess[str]) -> str:
    """Extract human-readable output from a completed subprocess."""
    out = result.stdout.strip()
    err = result.stderr.strip()
    parts = [p for p in (out, err) if p]
    return "\n".join(parts) if parts else "(no output)"


def check_marketplace_registered(
    name: str = _MARKETPLACE_NAME,
) -> bool:
    """Return ``True`` if *name* appears in ``claude plugin marketplace list``."""
    result = _run(["claude", "plugin", "marketplace", "list"])
    # Check for the marketplace name in the output (e.g. "❯ claude-project-manager")
    for line in result.stdout.splitlines():
        if name in line:
            return True
    return False


def add_marketplace(
    source: str = _MARKETPLACE_SOURCE, branch: str | None = None
) -> None:
    """Register marketplace via ``claude plugin marketplace add``.

    If *branch* is provided, appends ``#branch`` to the source
    (e.g. ``raulfrk/claude-project-manager#dev``).
    """
    ref = f"{source}#{branch}" if branch else source
    _run(["claude", "plugin", "marketplace", "add", ref])


def remove_marketplace(name: str = _MARKETPLACE_NAME) -> None:
    """Remove marketplace via ``claude plugin marketplace remove``."""
    _run(["claude", "plugin", "marketplace", "remove", name], check=False)


def get_installed_plugins(
    marketplace: str = _MARKETPLACE_NAME,
) -> list[str]:
    """Return plugin IDs installed from *marketplace* (e.g. ``router@claude-project-manager``)."""
    result = _run(["claude", "plugin", "list", "--json"])
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    plugins = data.get("installed", []) if isinstance(data, dict) else data
    return [
        p["id"]
        for p in plugins
        if isinstance(p, dict) and p.get("id", "").endswith(f"@{marketplace}")
    ]


def get_installed_plugin_versions(
    marketplace: str = _MARKETPLACE_NAME,
) -> dict[str, str]:
    """Return {plugin_name: version} for plugins installed from *marketplace*."""
    result = _run(["claude", "plugin", "list", "--json"])
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}
    plugins = data.get("installed", []) if isinstance(data, dict) else data
    versions: dict[str, str] = {}
    for p in plugins:
        if not isinstance(p, dict):
            continue
        pid = p.get("id", "")
        ver = p.get("version")
        if pid.endswith(f"@{marketplace}") and ver:
            name = pid.split("@")[0]
            versions[name] = ver
    return versions


def get_available_plugins(
    marketplace: str = _MARKETPLACE_NAME,
) -> list[str]:
    """Return plugin IDs available from *marketplace* (e.g. ``router@claude-project-manager``)."""
    result = _run(["claude", "plugin", "list", "--available", "--json"])
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    plugins = data.get("available", []) if isinstance(data, dict) else data
    return [
        p["pluginId"]
        for p in plugins
        if isinstance(p, dict) and p.get("pluginId", "").endswith(f"@{marketplace}")
    ]


def install_plugin(plugin_id: str) -> None:
    """Install a plugin by its full ID (e.g. ``router@claude-project-manager``)."""
    _run(["claude", "plugin", "install", plugin_id])


def update_plugin(plugin_id: str) -> None:
    """Update a plugin by its full ID."""
    _run(["claude", "plugin", "update", plugin_id])


def uninstall_plugin(plugin_id: str) -> None:
    """Uninstall a plugin by its full ID."""
    _run(["claude", "plugin", "uninstall", plugin_id], check=False)
