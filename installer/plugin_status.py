"""Data layer for the three-column plugin status screen.

Computes per-plugin state (available / installed / outdated) by combining
the bundled marketplace.json versions with the live ``claude plugin list``
output and the on-disk cache directory. Used by ``PluginStatusScreen`` and
the install worker in ``installer.app``.
"""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from installer.errors import InstallerError
from installer.plugin_cli import get_installed_plugins
from installer.update import _read_installed_version, _read_marketplace_versions

PLUGIN_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")

_DEFAULT_CACHE_DIR = (
    Path.home() / ".claude" / "plugins" / "cache" / "claude-project-manager"
)

PluginState = Literal["available", "installed", "outdated"]


@dataclass(frozen=True)
class PluginStatus:
    """Snapshot of a single plugin's install state."""

    name: str
    installed_version: str | None
    available_version: str | None
    state: PluginState


def build_plugin_status_list(
    marketplace_path: Path | None = None,
    cache_dir: Path | None = None,
) -> list[PluginStatus]:
    """Return a sorted list of ``PluginStatus`` entries for every marketplace plugin.

    The marketplace acts as the source of truth for which plugins exist; any
    ``get_installed_plugins()`` result that isn't in the marketplace is logged
    as a warning and excluded from the returned list.

    Raises:
        ValueError: if any marketplace plugin name fails ``PLUGIN_NAME_RE``.
    """
    marketplace_versions = _read_marketplace_versions(marketplace_path)

    for name in marketplace_versions:
        if not PLUGIN_NAME_RE.match(name):
            raise ValueError(
                f"Invalid plugin name in marketplace: {name!r}. "
                f"Names must match {PLUGIN_NAME_RE.pattern}."
            )

    try:
        installed_ids = get_installed_plugins()
    except InstallerError as exc:
        warnings.warn(
            f"Could not list installed plugins: {exc}. "
            f"Showing marketplace-only status.",
            stacklevel=2,
        )
        installed_ids = []

    installed_names = {pid.split("@")[0] for pid in installed_ids}

    for orphan in sorted(installed_names - set(marketplace_versions)):
        warnings.warn(
            f"Installed plugin {orphan!r} is not in the marketplace — excluding.",
            stacklevel=2,
        )

    effective_cache = cache_dir if cache_dir is not None else _DEFAULT_CACHE_DIR

    statuses: list[PluginStatus] = []
    for name in sorted(marketplace_versions):
        available = marketplace_versions.get(name)
        is_installed = name in installed_names
        installed_ver: str | None = None
        if is_installed:
            installed_ver = _read_installed_version(effective_cache, name)
            if installed_ver is None:
                warnings.warn(
                    f"Plugin {name!r} is installed but its plugin.json could not "
                    f"be read — marking as outdated.",
                    stacklevel=2,
                )

        state: PluginState
        if not is_installed:
            state = "available"
        elif installed_ver == available and installed_ver is not None:
            state = "installed"
        else:
            state = "outdated"

        statuses.append(
            PluginStatus(
                name=name,
                installed_version=installed_ver,
                available_version=available,
                state=state,
            )
        )

    return statuses
