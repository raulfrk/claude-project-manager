"""Auto-discover default-hooks.yaml from sibling plugins and register them."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from server.lib.models import Hook, HookRegistry

logger = logging.getLogger("hooks.discovery")

_DEFAULT_HOOKS_FILENAME = "default-hooks.yaml"
_DEFAULT_PLUGIN_GLOB = "plugins/*/.claude-plugin"
_AUTO_SOURCE = "auto"

# Fields compared for drift detection between existing hook and new definition
_DRIFT_FIELDS = ("blocking", "condition", "param_mapping", "feedback_tool", "feedback_mapping", "verification")


_DRIFT_DEFAULTS: dict[str, object] = {
    "blocking": False,
    "condition": None,
    "param_mapping": {},
    "feedback_tool": None,
    "feedback_mapping": {},
    "verification": False,
}


def _hook_content_differs(existing: Hook, new_def: dict[str, object]) -> bool:
    """Check if an existing auto hook has drifted from the new definition.

    Compares content fields only (not id, trigger, target, server, source).
    Missing keys in new_def are treated as the field's default value.
    """
    for fld in _DRIFT_FIELDS:
        old_val = getattr(existing, fld)
        new_val = new_def.get(fld, _DRIFT_DEFAULTS[fld])
        # Normalize: None and None are equal
        if old_val is None and new_val is None:
            continue
        # Normalize dict comparisons (stringify keys/values)
        if isinstance(old_val, dict) and isinstance(new_val, dict):
            if old_val != {str(k): str(v) for k, v in new_val.items()}:
                return True
            continue
        if old_val != new_val:
            return True
    return False


def _default_discovery_root() -> Path:
    """Return the project root that contains the plugins/ directory.

    Walks up from this file's location (inside plugins/hooks/server/server/lib/)
    to find the top-level plugins/ directory.
    """
    current = Path(__file__).resolve()
    # Walk up: lib -> server -> server -> hooks -> plugins -> <project-root>
    for _ in range(6):
        current = current.parent
        if (current / "plugins").is_dir():
            return current
    return current


def find_default_hooks_files(
    root: Path | None = None,
    glob_pattern: str = _DEFAULT_PLUGIN_GLOB,
) -> list[Path]:
    """Find all default-hooks.yaml files in sibling plugins.

    Returns a list of Paths to default-hooks.yaml files found.
    """
    discovery_root = root or _default_discovery_root()
    pattern = f"{glob_pattern}/{_DEFAULT_HOOKS_FILENAME}"
    found = sorted(discovery_root.glob(pattern))
    return found


def load_hooks_from_file(path: Path) -> list[dict[str, object]]:
    """Load hook definitions from a single default-hooks.yaml file.

    Expected format:
        hooks:
          - trigger_tool: some_tool
            target_tool: other_tool
            server: server_name
            param_mapping: {}
            blocking: false
            condition: null

    Returns a list of raw hook dicts. Returns empty list on any parse error.
    """
    try:
        with path.open() as f:
            raw = yaml.safe_load(f)
    except Exception:
        logger.warning("Failed to read %s", path)
        return []

    if not isinstance(raw, dict):
        logger.warning("Invalid format in %s: expected a mapping at top level", path)
        return []

    hooks_raw = raw.get("hooks", [])
    if not isinstance(hooks_raw, list):
        logger.warning("Invalid format in %s: 'hooks' must be a list", path)
        return []

    result: list[dict[str, object]] = []
    for entry in hooks_raw:
        if isinstance(entry, dict):
            result.append(entry)
        else:
            logger.warning("Skipping non-dict entry in %s", path)
    return result


def _plugin_name_from_path(path: Path) -> str:
    """Extract plugin name from a default-hooks.yaml path.

    Path looks like: .../plugins/<name>/.claude-plugin/default-hooks.yaml
    """
    # parent = .claude-plugin, parent.parent = <plugin-name>
    return path.parent.parent.name


_DEFAULT_SERVER_PORTS: dict[str, int] = {
    "hooks": 19100,
    "perms": 19101,
    "proj": 19102,
    "worktree": 19103,
    "trello": 19104,
    "jira": 19105,
    "todoist": 19106,
    "zoxide": 19107,
}


def discover_and_register(
    registry: HookRegistry,
    root: Path | None = None,
    glob_pattern: str = _DEFAULT_PLUGIN_GLOB,
) -> dict[str, dict[str, int]]:
    """Scan for default-hooks.yaml files and auto-register hooks.

    Hooks are registered idempotently:
    - If a hook with the same trigger+target+server already exists, it is skipped.
    - Auto-registered hooks are tagged with source="auto".
    - Hooks previously unregistered by the user (not present in registry) are not
      re-added within the same process lifetime. This is handled by the caller
      tracking unregistered IDs.

    Args:
        registry: The current HookRegistry to add hooks to.
        root: Project root containing the plugins/ directory. Auto-detected if None.
        glob_pattern: Glob pattern relative to root for finding .claude-plugin dirs.

    Returns:
        A dict mapping plugin name to stats: {"registered": N, "updated": M}.
    """
    files = find_default_hooks_files(root=root, glob_pattern=glob_pattern)
    stats: dict[str, dict[str, int]] = {}
    any_updated = False

    for path in files:
        plugin_name = _plugin_name_from_path(path)
        hook_defs = load_hooks_from_file(path)
        registered_count = 0
        updated_count = 0

        for hook_def in hook_defs:
            trigger = str(hook_def.get("trigger_tool", ""))
            target = str(hook_def.get("target_tool", ""))
            server = str(hook_def.get("server", ""))

            if not trigger or not target or not server:
                logger.warning(
                    "Skipping hook in %s: missing trigger_tool, target_tool, or server",
                    path,
                )
                continue

            existing = registry.find_duplicate(trigger, target, server)
            if existing is not None:
                # Drift detection: update auto hooks whose content has changed
                if existing.source == _AUTO_SOURCE and _hook_content_differs(existing, hook_def):
                    existing.update_from(hook_def)
                    updated_count += 1
                    any_updated = True
                continue

            # Build Hook from definition, forcing source="auto"
            hook_def["source"] = _AUTO_SOURCE
            hook_def["id"] = registry.next_id()
            hook = Hook.from_dict(hook_def)
            registry.hooks.append(hook)

            # Track server endpoint
            if server not in registry.servers:
                registry.servers[server] = {}

            registered_count += 1

        if hook_defs:
            stats[plugin_name] = {"registered": registered_count, "updated": updated_count}
            logger.info(
                "Plugin '%s': found %d hook(s), registered %d new, updated %d",
                plugin_name,
                len(hook_defs),
                registered_count,
                updated_count,
            )

    return stats


def populate_server_urls(
    registry: HookRegistry,
    port_overrides: dict[str, int] | None = None,
) -> int:
    """Populate registry.servers with default HTTP hook URLs.

    Existing manual entries (with a 'url' key) are preserved.
    Returns count of URLs added.
    """
    ports = {**_DEFAULT_SERVER_PORTS, **(port_overrides or {})}
    added = 0
    for name, port in ports.items():
        if name not in registry.servers:
            registry.servers[name] = {}
        if "url" not in registry.servers[name]:
            registry.servers[name]["url"] = f"http://127.0.0.1:{port}/hook"
            added += 1
    return added


def run_discovery(
    root: Path | None = None,
    glob_pattern: str = _DEFAULT_PLUGIN_GLOB,
) -> str:
    """Run the full discovery cycle: load registry, discover, save, return summary.

    This is the main entry point called from server startup.
    """
    from server.lib import storage

    registry = storage.load()

    stats = discover_and_register(registry, root=root, glob_pattern=glob_pattern)
    urls_added = populate_server_urls(registry)

    total_registered = sum(s["registered"] for s in stats.values())
    total_updated = sum(s["updated"] for s in stats.values())

    if stats or urls_added or total_updated:
        storage.save(registry)

    total_plugins = len(stats)
    lines = [f"Hook auto-discovery: scanned plugins, found {total_plugins} with default hooks."]
    for plugin_name, counts in stats.items():
        parts = []
        if counts["registered"]:
            parts.append(f"{counts['registered']} new")
        if counts["updated"]:
            parts.append(f"{counts['updated']} updated")
        if parts:
            lines.append(f"  {plugin_name}: {', '.join(parts)}")
    lines.append(f"Total auto-registered: {total_registered}")
    if total_updated:
        lines.append(f"Total updated: {total_updated}")
    lines.append(f"Server URLs populated: {urls_added}")
    summary = "\n".join(lines)
    logger.info(summary)
    return summary
