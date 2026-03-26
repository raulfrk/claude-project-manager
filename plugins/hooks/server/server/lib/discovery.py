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
) -> dict[str, int]:
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
        A dict mapping plugin name to the number of hooks registered from it.
    """
    files = find_default_hooks_files(root=root, glob_pattern=glob_pattern)
    stats: dict[str, int] = {}

    for path in files:
        plugin_name = _plugin_name_from_path(path)
        hook_defs = load_hooks_from_file(path)
        registered_count = 0

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

            # Idempotent: skip if duplicate already exists
            if registry.find_duplicate(trigger, target, server) is not None:
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
            stats[plugin_name] = registered_count
            logger.info(
                "Plugin '%s': found %d hook(s), registered %d new",
                plugin_name,
                len(hook_defs),
                registered_count,
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

    if stats or urls_added:
        storage.save(registry)

    total_plugins = len(stats)
    total_hooks = sum(stats.values())
    lines = [f"Hook auto-discovery: scanned plugins, found {total_plugins} with default hooks."]
    for plugin_name, count in stats.items():
        lines.append(f"  {plugin_name}: {count} hook(s) registered")
    lines.append(f"Total auto-registered: {total_hooks}")
    lines.append(f"Server URLs populated: {urls_added}")
    summary = "\n".join(lines)
    logger.info(summary)
    return summary
