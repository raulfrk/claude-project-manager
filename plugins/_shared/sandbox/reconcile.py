"""Pure reconciler for ~/.claude/settings.json MCP allow rules.

Factored out of plugins/proj/server/server/tools/sandbox.py:sandbox_reconcile
so the installer can call it directly without crossing process boundaries.
The MCP tool in proj-server now wraps this function and serializes the
result to JSON for skill consumers.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sandbox import storage
from sandbox.storage import allow_entries_for_path, mcp_allow_entry, skill_allow_entry

PLUGIN_TO_MCP_SERVER: dict[str, str] = {
    "proj": "plugin_proj_proj",
    "router": "plugin_router_router",
    "todoist": "plugin_todoist_todoist",
    "trello": "plugin_trello_trello",
    "jira": "plugin_jira_jira",
    "confluence": "plugin_confluence_confluence",
    "wiki": "plugin_wiki_wiki",
    "worktree": "plugin_worktree_worktree",
}


@dataclass
class ReconcileResult:
    """Outcome of a reconcile_settings call.

    `added` and `removed` are counts. `stale_removed` lists server names
    that were inferred-stale and removed. `paths_added` lists filesystem
    paths added to sandbox.filesystem.allow_write (when expected_paths
    was provided).
    """

    added: int = 0
    removed: int = 0
    stale_removed: list[str] = field(default_factory=list)
    paths_added: list[str] = field(default_factory=list)


def reconcile_settings(
    expected_servers: list[str],
    expected_paths: list[str] | None = None,
    expected_skill_prefixes: list[str] | None = None,
) -> ReconcileResult:
    """Sync expected vs actual MCP servers, paths, and skill prefixes.

    Args:
        expected_servers: list of MCP server names (e.g. `plugin_proj_proj`).
        expected_paths: optional sandbox.filesystem.allow_write paths.
        expected_skill_prefixes: optional skill-allow prefix strings.

    Returns:
        ReconcileResult with counts and diagnostic lists.

    Raises:
        ValueError: malformed server name (rejected by mcp_allow_entry).
        OSError: filesystem failure during save.
    """
    expected_entries = [mcp_allow_entry(name) for name in expected_servers]
    skill_entries = [skill_allow_entry(prefix) for prefix in expected_skill_prefixes or []]

    settings = storage.load()
    result = ReconcileResult()

    # Infer stale: present mcp__*__* rules not in expected_servers.
    current_servers = [
        r.removeprefix("mcp__").removesuffix("__*")
        for r in settings.permissions.allow
        if r.startswith("mcp__") and r.endswith("__*")
    ]
    stale = [s for s in current_servers if s not in expected_servers]

    for name in stale:
        try:
            stale_entry = mcp_allow_entry(name)
        except ValueError:
            continue
        if stale_entry in settings.permissions.allow:
            settings.permissions.allow.remove(stale_entry)
            result.removed += 1
            result.stale_removed.append(name)

    # Add missing servers.
    for entry in expected_entries:
        if entry not in settings.permissions.allow:
            settings.permissions.allow.append(entry)
            result.added += 1

    # Reconcile paths if provided.
    if expected_paths is not None:
        for p in expected_paths:
            abs_path = p  # caller is expected to pass absolute paths
            if abs_path not in settings.sandbox.filesystem.allow_write:
                settings.sandbox.filesystem.allow_write.append(abs_path)
                result.added += 1
                result.paths_added.append(abs_path)
            for entry in allow_entries_for_path(abs_path):
                if entry not in settings.permissions.allow:
                    settings.permissions.allow.append(entry)
                    result.added += 1

    # Reconcile skill prefixes if provided.
    if expected_skill_prefixes is not None:
        for entry in skill_entries:
            if entry not in settings.permissions.allow:
                settings.permissions.allow.append(entry)
                result.added += 1

    storage.save(settings)
    return result
