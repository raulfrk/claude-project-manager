"""MCP tools for managing Claude Code settings.json permissions."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from server.lib import storage

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def add_allow(path: str, scope: str = "user") -> str:
    """Add Read+Edit allow rules for a directory to Claude Code settings.json.

    The path must be absolute. Double-slash prefix is applied automatically.
    Changes take effect immediately — no restart required.
    Idempotent.
    """
    abs_path = str(Path(path).expanduser().resolve())
    new_entries = storage.allow_entries_for_path(abs_path)

    settings = storage.load(scope)
    added: list[str] = []
    for entry in new_entries:
        if entry not in settings.permissions.allow:
            settings.permissions.allow.append(entry)
            added.append(entry)

    if added:
        storage.save(settings)
        rules = "\n".join(f"  {e}" for e in added)
        return f"Added {len(added)} rule(s) to {settings.path}:\n{rules}"
    return f"Rules already present in {settings.path} — no changes made."


def remove_allow(path: str, scope: str = "user") -> str:
    """Remove Read+Edit allow rules for a directory from Claude Code settings.json.

    Idempotent.
    """
    abs_path = str(Path(path).expanduser().resolve())
    entries_to_remove = set(storage.allow_entries_for_path(abs_path))

    settings = storage.load(scope)
    before = len(settings.permissions.allow)
    settings.permissions.allow = [
        e for e in settings.permissions.allow if e not in entries_to_remove
    ]
    removed = before - len(settings.permissions.allow)

    if removed:
        storage.save(settings)
        return f"Removed {removed} rule(s) from {settings.path}."
    return f"No matching rules found in {settings.path} — no changes made."


def list_allow(scope: str = "all") -> str:
    """List current allow rules from Claude Code settings.json files."""
    lines: list[str] = []
    scopes = ["user", "project"] if scope == "all" else [scope]
    for s in scopes:
        settings = storage.load(s)
        if not settings.path.exists():
            lines.append(f"[{s}] {settings.path} — not found")
            continue
        allow = settings.permissions.allow
        if allow:
            lines.append(f"[{s}] {settings.path} — {len(allow)} allow rule(s):")
            lines.extend(f"  {e}" for e in allow)
        else:
            lines.append(f"[{s}] {settings.path} — no allow rules")
    return "\n".join(lines)


def check_allow(path: str, scope: str = "all") -> str:
    """Check whether a path already has allow rules in settings.json."""
    abs_path = str(Path(path).expanduser().resolve())
    expected = set(storage.allow_entries_for_path(abs_path))

    scopes = ["user", "project"] if scope == "all" else [scope]
    results: list[str] = []
    for s in scopes:
        settings = storage.load(s)
        found = expected & set(settings.permissions.allow)
        missing = expected - found
        if not found:
            results.append(f"[{s}] MISSING — no rules for this path")
        elif missing:
            results.append(f"[{s}] PARTIAL — missing: {', '.join(sorted(missing))}")
        else:
            results.append(f"[{s}] OK — all rules present")
    return "\n".join(results)


def add_mcp_allow(server_name: str, scope: str = "user") -> str:
    """Add an MCP server wildcard allow rule to Claude Code settings.json.

    Adds "mcp__<server_name>__*" to the allow list so Claude never prompts
    for permission when calling tools from that MCP server.
    Idempotent.
    """
    entry = storage.mcp_allow_entry(server_name)
    settings = storage.load(scope)
    if entry in settings.permissions.allow:
        return f"Rule already present in {settings.path} — no changes made."
    settings.permissions.allow.append(entry)
    storage.save(settings)
    return f"Added rule to {settings.path}:\n  {entry}"


def remove_mcp_allow(server_name: str, scope: str = "user") -> str:
    """Remove an MCP server wildcard allow rule from Claude Code settings.json.

    Idempotent.
    """
    entry = storage.mcp_allow_entry(server_name)
    settings = storage.load(scope)
    before = len(settings.permissions.allow)
    settings.permissions.allow = [e for e in settings.permissions.allow if e != entry]
    removed = before - len(settings.permissions.allow)
    if removed:
        storage.save(settings)
        return f"Removed rule from {settings.path}: {entry}"
    return f"Rule not found in {settings.path} — no changes made."


def batch_add_mcp_allow(servers: list[str], scope: str = "user") -> str:
    """Add wildcard allow rules for multiple MCP servers in one atomic write.

    Idempotent — already-present rules are skipped.
    Returns a summary of added and skipped rules.
    """
    if not servers:
        return "No servers specified — nothing to do."

    entries = [storage.mcp_allow_entry(s) for s in servers]
    settings = storage.load(scope)
    allow_set = set(settings.permissions.allow)

    added: list[str] = []
    skipped: list[str] = []
    for entry in entries:
        if entry in allow_set:
            skipped.append(entry)
        else:
            settings.permissions.allow.append(entry)
            allow_set.add(entry)
            added.append(entry)

    if added:
        storage.save(settings)
        lines = [f"Added {len(added)} rule(s) to {settings.path}:"]
        lines.extend(f"  {e}" for e in added)
        if skipped:
            lines.append(f"Skipped {len(skipped)} already-present rule(s).")
        return "\n".join(lines)

    return f"All {len(skipped)} rule(s) already present in {settings.path} — no changes made."


def register(app: FastMCP) -> None:
    """Register all perms tools with the MCP application."""

    @app.tool(
        description=(
            "Add Read and Edit allow rules for a directory to Claude Code settings.json. "
            "Path must be absolute. Idempotent."
        )
    )
    def perms_add_allow(path: str, scope: str = "user") -> str:
        return add_allow(path, scope)

    @app.tool(
        description="Remove Read+Edit allow rules for a directory from Claude Code settings.json. Idempotent."
    )
    def perms_remove_allow(path: str, scope: str = "user") -> str:
        return remove_allow(path, scope)

    @app.tool(description="List current allow rules from Claude Code settings.json files.")
    def perms_list(scope: str = "all") -> str:
        return list_allow(scope)

    @app.tool(description="Check whether a path already has allow rules in settings.json.")
    def perms_check(path: str, scope: str = "all") -> str:
        return check_allow(path, scope)

    @app.tool(
        description=(
            "Add an MCP server wildcard allow rule to Claude Code settings.json. "
            "Adds 'mcp__<server_name>__*' so Claude never prompts for that server's tools. Idempotent."
        )
    )
    def perms_add_mcp_allow(server_name: str, scope: str = "user") -> str:
        return add_mcp_allow(server_name, scope)

    @app.tool(description="Remove an MCP server wildcard allow rule from Claude Code settings.json. Idempotent.")
    def perms_remove_mcp_allow(server_name: str, scope: str = "user") -> str:
        return remove_mcp_allow(server_name, scope)

    @app.tool(
        description=(
            "Add wildcard allow rules for multiple MCP servers in one atomic write. "
            "Equivalent to calling perms_add_mcp_allow for each server but faster — "
            "only one settings.json write. Idempotent."
        )
    )
    def perms_batch_add_mcp_allow(servers: list[str], scope: str = "user") -> str:
        return batch_add_mcp_allow(servers, scope)
