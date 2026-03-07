"""MCP tools for managing Claude Code settings.json / settings.local.json permissions."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from server.lib import storage

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


# ── Internal helpers ──────────────────────────────────────────────────────────


def _load_for_target(resolved: str, scope: str) -> storage.SettingsFile:
    """Load the appropriate settings file based on resolved target."""
    if resolved == "sandbox":
        return storage.load_local(scope)
    return storage.load(scope)


def _add_path_sandbox(settings: storage.SettingsFile, abs_path: str) -> list[str]:
    """Add a path to sandbox.filesystem.allowWrite. Returns list of added entries."""
    clean = abs_path.rstrip("/")
    added: list[str] = []
    if clean not in settings.sandbox.filesystem.allow_write:
        settings.sandbox.filesystem.allow_write.append(clean)
        added.append(f"sandbox.filesystem.allowWrite: {clean}")
    return added


def _remove_path_sandbox(settings: storage.SettingsFile, abs_path: str) -> int:
    """Remove a path from sandbox.filesystem.allowWrite. Returns count removed."""
    clean = abs_path.rstrip("/")
    before = len(settings.sandbox.filesystem.allow_write)
    settings.sandbox.filesystem.allow_write = [
        p for p in settings.sandbox.filesystem.allow_write if p != clean
    ]
    return before - len(settings.sandbox.filesystem.allow_write)


# ── Tool functions ────────────────────────────────────────────────────────────


def add_allow(path: str, scope: str = "user", target: str = "auto") -> str:
    """Add allow rules for a directory.

    In ``settings`` mode: adds Read+Edit rules to ``permissions.allow`` in settings.json.
    In ``sandbox`` mode: adds the path to ``sandbox.filesystem.allowWrite`` in settings.local.json.
    In ``auto`` mode: detects sandbox from settings.local.json and chooses accordingly.

    The path must be absolute. Idempotent.
    """
    abs_path = str(Path(path).expanduser().resolve())
    resolved = storage.resolve_target(target, scope)

    if resolved == "sandbox":
        settings = storage.load_local(scope)
        added = _add_path_sandbox(settings, abs_path)
        if added:
            storage.save(settings)
            rules = "\n".join(f"  {e}" for e in added)
            return f"Added {len(added)} sandbox rule(s) to {settings.path}:\n{rules}"
        return f"Path already present in sandbox allowWrite in {settings.path} — no changes made."

    # Standard mode
    new_entries = storage.allow_entries_for_path(abs_path)
    settings = storage.load(scope)
    added_entries: list[str] = []
    for entry in new_entries:
        if entry not in settings.permissions.allow:
            settings.permissions.allow.append(entry)
            added_entries.append(entry)

    if added_entries:
        storage.save(settings)
        rules = "\n".join(f"  {e}" for e in added_entries)
        return f"Added {len(added_entries)} rule(s) to {settings.path}:\n{rules}"
    return f"Rules already present in {settings.path} — no changes made."


def remove_allow(path: str, scope: str = "user", target: str = "auto") -> str:
    """Remove allow rules for a directory.

    In ``sandbox`` mode: removes from ``sandbox.filesystem.allowWrite``.
    In ``settings`` mode: removes Read+Edit rules from ``permissions.allow``.
    Idempotent.
    """
    abs_path = str(Path(path).expanduser().resolve())
    resolved = storage.resolve_target(target, scope)

    if resolved == "sandbox":
        settings = storage.load_local(scope)
        removed = _remove_path_sandbox(settings, abs_path)
        if removed:
            storage.save(settings)
            return f"Removed {removed} sandbox path(s) from {settings.path}."
        return f"No matching sandbox paths found in {settings.path} — no changes made."

    # Standard mode
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


def list_allow(scope: str = "all", target: str = "auto") -> str:
    """List current allow rules from Claude Code settings files."""
    lines: list[str] = []
    scopes = ["user", "project"] if scope == "all" else [scope]
    for s in scopes:
        resolved = storage.resolve_target(target, s)

        if resolved == "sandbox":
            settings = storage.load_local(s)
            if not settings.path.exists():
                lines.append(f"[{s}] {settings.path} — not found")
                continue
            aw = settings.sandbox.filesystem.allow_write
            allow = settings.permissions.allow
            if aw or allow:
                if aw:
                    lines.append(f"[{s}] {settings.path} — sandbox.filesystem.allowWrite ({len(aw)}):")
                    lines.extend(f"  {p}" for p in aw)
                if allow:
                    lines.append(f"[{s}] {settings.path} — permissions.allow ({len(allow)}):")
                    lines.extend(f"  {e}" for e in allow)
            else:
                lines.append(f"[{s}] {settings.path} — no sandbox rules")
        else:
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


def check_allow(path: str, scope: str = "all", target: str = "auto") -> str:
    """Check whether a path already has allow rules in settings."""
    abs_path = str(Path(path).expanduser().resolve())
    clean = abs_path.rstrip("/")

    scopes = ["user", "project"] if scope == "all" else [scope]
    results: list[str] = []
    for s in scopes:
        resolved = storage.resolve_target(target, s)

        if resolved == "sandbox":
            settings = storage.load_local(s)
            if clean in settings.sandbox.filesystem.allow_write:
                results.append(f"[{s}] OK — path present in sandbox allowWrite")
            else:
                results.append(f"[{s}] MISSING — path not in sandbox allowWrite")
        else:
            expected = set(storage.allow_entries_for_path(abs_path))
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


def add_mcp_allow(server_name: str, scope: str = "user", target: str = "auto") -> str:
    """Add an MCP server wildcard allow rule.

    MCP rules always go to ``permissions.allow`` (they are tool-level, not filesystem).
    In sandbox mode the rule is written to settings.local.json instead of settings.json.
    Idempotent.
    """
    entry = storage.mcp_allow_entry(server_name)
    resolved = storage.resolve_target(target, scope)
    settings = _load_for_target(resolved, scope)

    if entry in settings.permissions.allow:
        return f"Rule already present in {settings.path} — no changes made."
    settings.permissions.allow.append(entry)
    storage.save(settings)
    return f"Added rule to {settings.path}:\n  {entry}"


def remove_mcp_allow(server_name: str, scope: str = "user", target: str = "auto") -> str:
    """Remove an MCP server wildcard allow rule. Idempotent."""
    entry = storage.mcp_allow_entry(server_name)
    resolved = storage.resolve_target(target, scope)
    settings = _load_for_target(resolved, scope)

    before = len(settings.permissions.allow)
    settings.permissions.allow = [e for e in settings.permissions.allow if e != entry]
    removed = before - len(settings.permissions.allow)
    if removed:
        storage.save(settings)
        return f"Removed rule from {settings.path}: {entry}"
    return f"Rule not found in {settings.path} — no changes made."


def batch_add_mcp_allow(servers: list[str], scope: str = "user", target: str = "auto") -> str:
    """Add wildcard allow rules for multiple MCP servers in one atomic write.

    Idempotent — already-present rules are skipped.
    """
    if not servers:
        return "No servers specified — nothing to do."

    entries = [storage.mcp_allow_entry(s) for s in servers]
    resolved = storage.resolve_target(target, scope)
    settings = _load_for_target(resolved, scope)
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


_PATH_RULE_RE = re.compile(r"^(?:Read|Edit)\(//(.+?)/\*\*\)$")


def _extract_paths_from_allow(allow: list[str]) -> list[str]:
    """Extract unique base paths from Read(//path/**) and Edit(//path/**) rules."""
    paths: dict[str, None] = {}
    for entry in allow:
        m = _PATH_RULE_RE.match(entry)
        if m:
            paths[f"/{m.group(1)}"] = None
    return list(paths)


def sandbox_init(path: str | None = None) -> str:
    """Enable sandbox mode in global settings with auto-migration of existing path rules.

    Sets ``sandbox.enabled`` and ``sandbox.autoAllowBashIfSandboxed`` to true.
    Migrates existing ``Read(//path/**)`` / ``Edit(//path/**)`` rules from
    ``permissions.allow`` into ``sandbox.filesystem.allowWrite``.
    Optionally adds an extra path to ``allowWrite``.
    Idempotent.
    """
    settings = storage.load("user")
    actions: list[str] = []

    if not settings.sandbox.enabled:
        settings.sandbox.enabled = True
        actions.append("sandbox.enabled = true")
    if not settings.sandbox.auto_allow_bash_if_sandboxed:
        settings.sandbox.auto_allow_bash_if_sandboxed = True
        actions.append("sandbox.autoAllowBashIfSandboxed = true")

    aw_set = set(settings.sandbox.filesystem.allow_write)

    # Auto-migrate existing Read/Edit path rules
    migrated: list[str] = []
    for p in _extract_paths_from_allow(settings.permissions.allow):
        if p not in aw_set:
            settings.sandbox.filesystem.allow_write.append(p)
            aw_set.add(p)
            migrated.append(p)

    # Optional extra path
    if path:
        abs_path = str(Path(path).expanduser().resolve())
        if abs_path not in aw_set:
            settings.sandbox.filesystem.allow_write.append(abs_path)
            aw_set.add(abs_path)
            actions.append(f"sandbox.filesystem.allowWrite: {abs_path}")

    if not actions and not migrated:
        return f"Sandbox already initialized in {settings.path} — no changes made."

    storage.save(settings)
    lines = [f"Sandbox initialized in {settings.path}:"]
    for a in actions:
        lines.append(f"  {a}")
    if migrated:
        lines.append(f"  Migrated {len(migrated)} path(s) from permissions.allow:")
        for p in migrated:
            lines.append(f"    {p}")
    return "\n".join(lines)


def add_domain(domain: str) -> str:
    """Add a domain to sandbox.network.allowedDomains. Idempotent."""
    settings = storage.load("user")
    if domain in settings.sandbox.network.allowed_domains:
        return f"Domain already present in {settings.path} — no changes made."
    settings.sandbox.network.allowed_domains.append(domain)
    storage.save(settings)
    return f"Added domain to {settings.path}:\n  {domain}"


def remove_domain(domain: str) -> str:
    """Remove a domain from sandbox.network.allowedDomains. Idempotent."""
    settings = storage.load("user")
    before = len(settings.sandbox.network.allowed_domains)
    settings.sandbox.network.allowed_domains = [
        d for d in settings.sandbox.network.allowed_domains if d != domain
    ]
    removed = before - len(settings.sandbox.network.allowed_domains)
    if removed:
        storage.save(settings)
        return f"Removed domain from {settings.path}: {domain}"
    return f"Domain not found in {settings.path} — no changes made."


_DENY_DISPLAY = {"deny_write": "denyWrite", "deny_read": "denyRead"}


def _add_to_deny_list(path: str, field: str) -> str:
    """Add a path to a sandbox deny list (denyWrite or denyRead). Idempotent."""
    display = _DENY_DISPLAY[field]
    abs_path = str(Path(path).expanduser().resolve())
    settings = storage.load("user")
    deny_list: list[str] = getattr(settings.sandbox.filesystem, field)
    if abs_path in deny_list:
        return f"Path already in {display} in {settings.path} — no changes made."
    deny_list.append(abs_path)
    storage.save(settings)
    return f"Added to sandbox.filesystem.{display} in {settings.path}:\n  {abs_path}"


def _remove_from_deny_list(path: str, field: str) -> str:
    """Remove a path from a sandbox deny list (denyWrite or denyRead). Idempotent."""
    display = _DENY_DISPLAY[field]
    abs_path = str(Path(path).expanduser().resolve())
    settings = storage.load("user")
    deny_list: list[str] = getattr(settings.sandbox.filesystem, field)
    before = len(deny_list)
    new_list = [p for p in deny_list if p != abs_path]
    setattr(settings.sandbox.filesystem, field, new_list)
    removed = before - len(new_list)
    if removed:
        storage.save(settings)
        return f"Removed from {display} in {settings.path}: {abs_path}"
    return f"Path not in {display} in {settings.path} — no changes made."


def deny_write(path: str) -> str:
    """Add a path to sandbox.filesystem.denyWrite. Idempotent."""
    return _add_to_deny_list(path, "deny_write")


def remove_deny_write(path: str) -> str:
    """Remove a path from sandbox.filesystem.denyWrite. Idempotent."""
    return _remove_from_deny_list(path, "deny_write")


def deny_read(path: str) -> str:
    """Add a path to sandbox.filesystem.denyRead. Idempotent."""
    return _add_to_deny_list(path, "deny_read")


def remove_deny_read(path: str) -> str:
    """Remove a path from sandbox.filesystem.denyRead. Idempotent."""
    return _remove_from_deny_list(path, "deny_read")


def register(app: FastMCP) -> None:
    """Register all perms tools with the MCP application."""

    @app.tool(
        description=(
            "Add Read and Edit allow rules for a directory to Claude Code settings. "
            "Path must be absolute. Idempotent. "
            "target: 'settings' (settings.json), 'sandbox' (settings.local.json sandbox.filesystem.allowWrite), "
            "or 'auto' (detect sandbox mode). Default: 'auto'."
        )
    )
    def perms_add_allow(path: str, scope: str = "user", target: str = "auto") -> str:
        return add_allow(path, scope, target)

    @app.tool(
        description=(
            "Remove allow rules for a directory from Claude Code settings. Idempotent. "
            "target: 'settings', 'sandbox', or 'auto' (default)."
        )
    )
    def perms_remove_allow(path: str, scope: str = "user", target: str = "auto") -> str:
        return remove_allow(path, scope, target)

    @app.tool(
        description=(
            "List current allow rules from Claude Code settings files. "
            "target: 'settings', 'sandbox', or 'auto' (default)."
        )
    )
    def perms_list(scope: str = "all", target: str = "auto") -> str:
        return list_allow(scope, target)

    @app.tool(
        description=(
            "Check whether a path already has allow rules in settings. "
            "target: 'settings', 'sandbox', or 'auto' (default)."
        )
    )
    def perms_check(path: str, scope: str = "all", target: str = "auto") -> str:
        return check_allow(path, scope, target)

    @app.tool(
        description=(
            "Add an MCP server wildcard allow rule to Claude Code settings. "
            "Adds 'mcp__<server_name>__*' so Claude never prompts for that server's tools. Idempotent. "
            "target: 'settings', 'sandbox', or 'auto' (default). "
            "In sandbox mode, MCP rules go to permissions.allow in settings.local.json."
        )
    )
    def perms_add_mcp_allow(server_name: str, scope: str = "user", target: str = "auto") -> str:
        return add_mcp_allow(server_name, scope, target)

    @app.tool(
        description=(
            "Remove an MCP server wildcard allow rule from Claude Code settings. Idempotent. "
            "target: 'settings', 'sandbox', or 'auto' (default)."
        )
    )
    def perms_remove_mcp_allow(server_name: str, scope: str = "user", target: str = "auto") -> str:
        return remove_mcp_allow(server_name, scope, target)

    @app.tool(
        description=(
            "Add wildcard allow rules for multiple MCP servers in one atomic write. "
            "Equivalent to calling perms_add_mcp_allow for each server but faster — "
            "only one file write. Idempotent. "
            "target: 'settings', 'sandbox', or 'auto' (default)."
        )
    )
    def perms_batch_add_mcp_allow(servers: list[str], scope: str = "user", target: str = "auto") -> str:
        return batch_add_mcp_allow(servers, scope, target)

    @app.tool(
        description=(
            "Initialize sandbox mode in global settings (~/.claude/settings.json). "
            "Enables sandbox.enabled and sandbox.autoAllowBashIfSandboxed. "
            "Auto-migrates existing Read/Edit path rules from permissions.allow into "
            "sandbox.filesystem.allowWrite. Optionally adds an extra path. Idempotent."
        )
    )
    def perms_sandbox_init(path: str | None = None) -> str:
        return sandbox_init(path)

    @app.tool(
        description="Add a domain to sandbox.network.allowedDomains in global settings. Idempotent."
    )
    def perms_add_domain(domain: str) -> str:
        return add_domain(domain)

    @app.tool(
        description="Remove a domain from sandbox.network.allowedDomains in global settings. Idempotent."
    )
    def perms_remove_domain(domain: str) -> str:
        return remove_domain(domain)

    @app.tool(
        description="Add a path to sandbox.filesystem.denyWrite in global settings. Idempotent."
    )
    def perms_deny_write(path: str) -> str:
        return deny_write(path)

    @app.tool(
        description="Remove a path from sandbox.filesystem.denyWrite in global settings. Idempotent."
    )
    def perms_remove_deny_write(path: str) -> str:
        return remove_deny_write(path)

    @app.tool(
        description="Add a path to sandbox.filesystem.denyRead in global settings. Idempotent."
    )
    def perms_deny_read(path: str) -> str:
        return deny_read(path)

    @app.tool(
        description="Remove a path from sandbox.filesystem.denyRead in global settings. Idempotent."
    )
    def perms_remove_deny_read(path: str) -> str:
        return remove_deny_read(path)
