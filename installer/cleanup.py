"""Cleanup orphan plugin cache dirs after install/update."""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Callable

logger = logging.getLogger("installer")


def _parse_live_plugins(data: dict) -> dict[str, set[str]]:
    """Parse installed_plugins.json into {marketplace: {plugin_names}}.

    Handles flat <plugin>@<marketplace> keys (real shape) and ignores
    malformed entries.
    """
    live: dict[str, set[str]] = {}
    plugins = data.get("plugins") if isinstance(data, dict) else None
    if not isinstance(plugins, dict):
        return live
    for key in plugins:
        if not isinstance(key, str) or "@" not in key:
            continue
        plugin, marketplace = key.split("@", 1)
        live.setdefault(marketplace, set()).add(plugin)
    return live


def cleanup_orphaned_plugin_caches(
    cache_root: Path,
    installed_plugins_json: Path,
    *,
    interactive: bool = False,
    confirm: Callable[[list[str]], bool] | None = None,
    dry_run: bool = False,
) -> list[str]:
    """Prune cache dirs whose plugin is not in installed_plugins.json.

    Returns list of removed composite names '<marketplace>/<plugin>'.
    """
    if not cache_root.is_dir():
        return []
    if not installed_plugins_json.is_file():
        logger.warning(
            "cleanup: installed_plugins.json missing: %s", installed_plugins_json
        )
        return []
    try:
        data = json.loads(installed_plugins_json.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("cleanup: failed to parse installed_plugins.json: %s", exc)
        return []
    live = _parse_live_plugins(data)

    orphans: list[tuple[Path, str]] = []
    for marketplace_dir in sorted(cache_root.iterdir()):
        if not marketplace_dir.is_dir():
            continue
        marketplace_name = marketplace_dir.name
        live_names = live.get(marketplace_name, set())
        for plugin_dir in sorted(marketplace_dir.iterdir()):
            if not plugin_dir.is_dir():
                continue
            if plugin_dir.name not in live_names:
                composite = f"{marketplace_name}/{plugin_dir.name}"
                orphans.append((plugin_dir, composite))

    if not orphans:
        return []

    composite_names = [c for _, c in orphans]
    if dry_run:
        return composite_names

    if interactive and confirm is not None:
        if not confirm(composite_names):
            return []

    cache_root_resolved = cache_root.resolve()
    removed: list[str] = []
    for path, composite in orphans:
        try:
            if not path.resolve().is_relative_to(cache_root_resolved):
                logger.warning("cleanup: path escapes cache_root, skipping: %s", path)
                continue
        except (OSError, ValueError) as exc:
            logger.warning("cleanup: resolve failed for %s: %s", path, exc)
            continue
        if path.is_symlink():
            try:
                path.unlink()
                removed.append(composite)
                logger.info("removed orphaned plugin cache: %s", composite)
            except OSError as exc:
                logger.warning("cleanup: failed to unlink symlink %s: %s", path, exc)
            continue
        try:
            shutil.rmtree(path)
            removed.append(composite)
            logger.info("removed orphaned plugin cache: %s", composite)
        except (PermissionError, FileNotFoundError, OSError) as exc:
            logger.warning("cleanup: failed to remove %s: %s", path, exc)
    return removed
