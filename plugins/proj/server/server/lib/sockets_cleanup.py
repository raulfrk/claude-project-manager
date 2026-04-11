"""Best-effort cleanup of stale socket registry files under ~/.claude/sockets.

Legacy plugin names (e.g. ``hooks``, ``perms``) can leave orphaned registry
files behind after a rename/uninstall. This module removes such files if they
are not present in the current ``installed_plugins.json``. An allowlist
restricts deletions to known managed plugin names so unrelated user files are
never touched.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

KNOWN_MANAGED_PLUGINS = frozenset(
    {
        "hooks",
        "perms",
        "router",
        "sandbox",
        "proj",
        "worktree",
        "trello",
        "jira",
        "todoist",
        "zoxide",
    }
)


def _load_installed(installed_plugins_json: Path) -> set[str] | None:
    """Parse installed_plugins.json and return the set of live plugin names.

    Returns ``None`` on parse failure or unrecognised shape so callers can
    abort cleanup rather than risk deleting live files.
    """
    try:
        raw = json.loads(installed_plugins_json.read_text())
    except (OSError, json.JSONDecodeError):
        return None

    if isinstance(raw, dict):
        plugins = raw.get("plugins")
        if isinstance(plugins, dict):
            names: set[str] = set()
            for key in plugins:
                if not isinstance(key, str):
                    return None
                names.add(key.split("@", 1)[0])
            return names
        if isinstance(plugins, list):
            names = set()
            for entry in plugins:
                if not isinstance(entry, dict):
                    return None
                name = entry.get("name") or entry.get("plugin_name")
                if not isinstance(name, str):
                    return None
                names.add(name.split("@", 1)[0])
            return names

    return None


def sockets_cleanup_stale(sockets_dir: Path, installed_plugins_json: Path) -> list[str]:
    """Delete stale socket registry files for plugins no longer installed.

    Only regular files whose name appears in ``KNOWN_MANAGED_PLUGINS`` are
    candidates. Symlinks and directories are ignored. Returns the list of
    removed plugin names (empty on any failure condition).
    """
    if not sockets_dir.exists():
        return []
    if not installed_plugins_json.exists():
        logger.warning(
            "sockets_cleanup_stale: installed_plugins.json missing at %s",
            installed_plugins_json,
        )
        return []

    live = _load_installed(installed_plugins_json)
    if live is None:
        logger.warning(
            "sockets_cleanup_stale: could not parse %s, skipping cleanup",
            installed_plugins_json,
        )
        return []

    removed: list[str] = []
    for entry in sockets_dir.iterdir():
        if entry.is_symlink() or not entry.is_file():
            continue
        name = entry.name
        if name not in KNOWN_MANAGED_PLUGINS:
            continue
        if name in live:
            continue
        try:
            entry.unlink()
        except FileNotFoundError:
            continue
        except OSError:
            logger.debug("sockets_cleanup_stale: failed to unlink %s", entry, exc_info=True)
            continue
        logger.info("sockets_cleanup_stale: removed stale registry file %s", entry)
        removed.append(name)

    return removed
