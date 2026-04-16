"""Cleanup orphan plugin cache dirs after install/update."""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from packaging.version import InvalidVersion, Version

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


@dataclass
class PruneReport:
    """Classification of cache dirs for pruning."""

    orphans: list[str] = field(default_factory=list)
    stale_versions: dict[str, list[str]] = field(default_factory=dict)


def _load_marketplace_plugins(marketplace_path: Path) -> set[str]:
    """Load plugin names from marketplace.json.

    Raises FileNotFoundError if the file doesn't exist.
    """
    if not marketplace_path.is_file():
        raise FileNotFoundError(f"marketplace.json not found: {marketplace_path}")
    data = json.loads(marketplace_path.read_text())
    plugins = data.get("plugins", [])
    return {p["name"] for p in plugins if isinstance(p, dict) and "name" in p}


def scan_stale_cache(cache_dir: Path, marketplace_path: Path) -> PruneReport:
    """Classify every dir in cache_dir as active, stale-version, or orphan.

    - Orphans: plugin dirs whose name is not in marketplace.json.
    - Stale versions: non-highest semver subdirs for active plugins.
    - The highest-semver dir for each active plugin is kept out of the report.

    Raises FileNotFoundError if marketplace.json is missing.
    """
    active = _load_marketplace_plugins(marketplace_path)
    report = PruneReport()

    if not cache_dir.is_dir():
        return report

    for plugin_dir in sorted(cache_dir.iterdir()):
        if not plugin_dir.is_dir():
            continue
        if plugin_dir.name.startswith("."):
            continue
        if plugin_dir.name == "_shared":
            continue
        if plugin_dir.name not in active:
            report.orphans.append(plugin_dir.name)
            continue
        # Active plugin — enumerate version subdirs
        version_dirs: list[tuple[Version, str]] = []
        for v_dir in plugin_dir.iterdir():
            if not v_dir.is_dir():
                continue
            try:
                version_dirs.append((Version(v_dir.name), v_dir.name))
            except InvalidVersion:
                continue  # skip unparseable
        if len(version_dirs) <= 1:
            continue
        # Keep highest semver; rest are stale
        version_dirs.sort(key=lambda t: t[0], reverse=True)
        stale = [name for _, name in version_dirs[1:]]
        if stale:
            report.stale_versions[plugin_dir.name] = stale

    return report


def prune_stale_versions(cache_dir: Path, report: PruneReport) -> list[str]:
    """Delete the stale version dirs listed in the report.

    Returns list of deleted paths (as strings) for logging.
    """
    deleted: list[str] = []
    for plugin, versions in report.stale_versions.items():
        plugin_dir = cache_dir / plugin
        if not plugin_dir.is_dir():
            continue
        for version in versions:
            v_dir = plugin_dir / version
            if not v_dir.is_dir():
                continue
            try:
                shutil.rmtree(v_dir)
                deleted.append(str(v_dir))
                logger.info("Pruned stale version dir: %s", v_dir)
            except OSError as exc:
                logger.warning("Failed to remove %s: %s", v_dir, exc)
    return deleted


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
