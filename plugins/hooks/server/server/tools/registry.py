"""MCP tools for hook registration and unregistration."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from server.lib import storage
from server.lib.conditions import resolve_condition_status
from server.lib.dag import find_cycle_path, would_create_cycle
from server.lib.models import Hook

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


# ── Tool functions ────────────────────────────────────────────────────────────


def hooks_register(
    trigger_tool: str,
    target_tool: str,
    server: str,
    param_mapping: str = "{}",
    blocking: bool = False,
    condition: str | None = None,
) -> str:
    """Register a hook that links a trigger tool to a target tool on a server.

    param_mapping is a JSON string of key-value pairs supporting ${} template syntax.
    Duplicate detection: same trigger+target+server returns existing hook_id.
    Server endpoints are tracked under the servers: key in hooks.yaml.
    """
    # Validate param_mapping is valid JSON
    try:
        mapping: dict[str, str] = json.loads(param_mapping)
        if not isinstance(mapping, dict):
            return "Error: param_mapping must be a JSON object (dict), got " + type(mapping).__name__
    except json.JSONDecodeError as e:
        return f"Error: param_mapping is not valid JSON: {e}"

    registry = storage.load()

    # Duplicate detection
    existing = registry.find_duplicate(trigger_tool, target_tool, server)
    if existing is not None:
        return (
            f"Hook already exists: {existing.id}\n"
            f"  trigger: {existing.trigger_tool}\n"
            f"  target: {existing.target_tool}\n"
            f"  server: {existing.server}"
        )

    # Circular dependency prevention (DAG check)
    if would_create_cycle(registry.hooks, trigger_tool, target_tool):
        cycle_path = find_cycle_path(registry.hooks, trigger_tool, target_tool)
        if cycle_path:
            cycle_str = " -> ".join(cycle_path)
            return f"Error: registering this hook would create a cycle: {cycle_str}"
        return (
            f"Error: registering hook {trigger_tool} -> {target_tool} "
            "would create a circular dependency."
        )

    # Generate next ID and create hook
    hook_id = registry.next_id()
    hook = Hook(
        id=hook_id,
        trigger_tool=trigger_tool,
        target_tool=target_tool,
        server=server,
        param_mapping=mapping,
        blocking=blocking,
        condition=condition,
    )
    registry.hooks.append(hook)

    # Track server endpoint
    if server not in registry.servers:
        registry.servers[server] = {}

    target = storage.save(registry)

    lines = [
        f"Registered hook {hook_id} in {target}:",
        f"  trigger: {trigger_tool}",
        f"  target: {target_tool}",
        f"  server: {server}",
        f"  param_mapping: {param_mapping}",
        f"  blocking: {blocking}",
    ]
    if condition is not None:
        lines.append(f"  condition: {condition}")
    return "\n".join(lines)


def hooks_list(trigger_tool: str | None = None) -> str:
    """List all registered hooks, optionally filtered by trigger_tool.

    Returns a JSON object with 'hooks' (array of hook objects) and 'servers' (dict).
    Each hook includes a ``condition_status`` field resolved against the live
    proj config (``"always"`` / ``"active"`` / ``"inactive"``).
    Returns empty hooks array (not an error) when no matches are found.
    """
    registry = storage.load()

    if trigger_tool is not None:
        matched = [h for h in registry.hooks if h.trigger_tool == trigger_tool]
    else:
        matched = list(registry.hooks)

    hooks_out: list[dict[str, object]] = []
    for h in matched:
        entry = h.to_dict()
        entry["condition_status"] = resolve_condition_status(h.condition)
        hooks_out.append(entry)

    result = {
        "hooks": hooks_out,
        "servers": registry.servers,
    }
    return json.dumps(result, indent=2)


def hooks_unregister(hook_id: str) -> str:
    """Unregister a hook by its ID. Idempotent -- returns success even if not found."""
    registry = storage.load()

    if not registry.find_by_id(hook_id):
        return f"Hook {hook_id} not found — no changes made."

    registry.remove_by_id(hook_id)
    target = storage.save(registry)
    return f"Unregistered hook {hook_id} from {target}."


# ── Registration ──────────────────────────────────────────────────────────────


def register(app: FastMCP) -> None:
    """Register hook registry tools with the MCP application."""

    @app.tool(
        description=(
            "Register a hook that fires target_tool on a server when trigger_tool runs. "
            "param_mapping is a JSON string of key-value pairs supporting ${} template syntax "
            "(e.g. '{\"path\": \"${result.path}\"}').  "
            "blocking: if true, trigger waits for target to complete (default false). "
            "condition: optional expression to gate the hook. "
            "Duplicate detection: same trigger+target+server returns existing hook_id. "
            "YAML created on first register if it doesn't exist."
        )
    )
    def hooks_register_tool(
        trigger_tool: str,
        target_tool: str,
        server: str,
        param_mapping: str = "{}",
        blocking: bool = False,
        condition: str | None = None,
    ) -> str:
        return hooks_register(
            trigger_tool=trigger_tool,
            target_tool=target_tool,
            server=server,
            param_mapping=param_mapping,
            blocking=blocking,
            condition=condition,
        )

    @app.tool(
        description=(
            "List all registered hooks from ~/.claude/hooks.yaml. "
            "Optional trigger_tool filter returns only hooks for that trigger. "
            "Returns JSON with 'hooks' array and 'servers' dict. "
            "Empty array when no matches (not an error)."
        )
    )
    def hooks_list_tool(trigger_tool: str | None = None) -> str:
        return hooks_list(trigger_tool=trigger_tool)

    @app.tool(
        description=(
            "Unregister a hook by its ID (e.g. 'hook-001'). "
            "Removes the hook from ~/.claude/hooks.yaml. Idempotent."
        )
    )
    def hooks_unregister_tool(hook_id: str) -> str:
        return hooks_unregister(hook_id)
