"""Sandbox MCP tools for managing ~/.claude/settings.json."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from sandbox import storage
from sandbox.storage import allow_entries_for_path, mcp_allow_entry, skill_allow_entry

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def _resolve_path(path: str) -> str:
    """Resolve a path to absolute, expanding ~ and resolving symlinks."""
    resolved = str(Path(path).expanduser().resolve()).rstrip("/")
    original = str(Path(path).expanduser()).rstrip("/")
    if resolved != original:
        # Symlink traversal — log but proceed
        logging.getLogger(__name__).warning("Path resolved via symlink: %s -> %s", path, resolved)
    return resolved


def _json_result(**kwargs: object) -> str:
    return json.dumps(kwargs)


# ---------------------------------------------------------------------------
# Tool implementation functions (module-level, importable by tests)
# ---------------------------------------------------------------------------


def sandbox_add_write_path(path: str) -> str:
    """Add a directory to sandbox write allowlist and Edit permission rules."""
    abs_path = _resolve_path(path)
    settings = storage.load()

    added = 0
    if abs_path not in settings.sandbox.filesystem.allow_write:
        settings.sandbox.filesystem.allow_write.append(abs_path)
        added += 1

    for entry in allow_entries_for_path(abs_path):
        if entry not in settings.permissions.allow:
            settings.permissions.allow.append(entry)
            added += 1

    if added:
        storage.save(settings)

    return _json_result(
        result=f"Added write path: {abs_path}" if added else f"Already present: {abs_path}",
        path=abs_path,
        settings_path=str(settings.path),
        added=added,
    )


def sandbox_remove_write_path(path: str) -> str:
    """Remove a directory from sandbox write allowlist and Edit permission rules."""
    abs_path = _resolve_path(path)
    settings = storage.load()

    removed = 0
    if abs_path in settings.sandbox.filesystem.allow_write:
        settings.sandbox.filesystem.allow_write.remove(abs_path)
        removed += 1

    for entry in allow_entries_for_path(abs_path):
        if entry in settings.permissions.allow:
            settings.permissions.allow.remove(entry)
            removed += 1

    if removed:
        storage.save(settings)

    return _json_result(
        result=f"Removed write path: {abs_path}" if removed else f"Not found: {abs_path}",
        path=abs_path,
        settings_path=str(settings.path),
        removed=removed,
    )


def sandbox_set_deny(rules: list[str]) -> str:
    """Replace permissions.deny rules atomically."""
    settings = storage.load()
    settings.permissions.deny = list(rules)
    storage.save(settings)

    return _json_result(
        result=f"Set {len(rules)} deny rule(s)",
        settings_path=str(settings.path),
        count=len(rules),
    )


def sandbox_batch_setup(
    paths: list[str] | None = None,
    mcp_servers: list[str] | None = None,
    domains: list[str] | None = None,
    skill_prefixes: list[str] | None = None,
) -> str:
    """Add write paths, MCP allow rules, domains, and Skill rules in one atomic write."""
    # Validate all entries before any mutation to prevent partial writes
    try:
        mcp_entries = [mcp_allow_entry(name) for name in mcp_servers or []]
        skill_entries = [skill_allow_entry(prefix) for prefix in skill_prefixes or []]
    except ValueError as exc:
        return _json_result(error=str(exc))

    settings = storage.load()
    paths_added = 0
    edit_added = 0
    mcp_added = 0
    domains_added = 0
    skills_added = 0

    for p in paths or []:
        abs_path = _resolve_path(p)
        if abs_path not in settings.sandbox.filesystem.allow_write:
            settings.sandbox.filesystem.allow_write.append(abs_path)
            paths_added += 1
        for entry in allow_entries_for_path(abs_path):
            if entry not in settings.permissions.allow:
                settings.permissions.allow.append(entry)
                edit_added += 1

    for entry in mcp_entries:
        if entry not in settings.permissions.allow:
            settings.permissions.allow.append(entry)
            mcp_added += 1

    for d in domains or []:
        if d not in settings.sandbox.network.allowed_domains:
            settings.sandbox.network.allowed_domains.append(d)
            domains_added += 1

    for entry in skill_entries:
        if entry not in settings.permissions.allow:
            settings.permissions.allow.append(entry)
            skills_added += 1

    total = paths_added + edit_added + mcp_added + domains_added + skills_added
    if total:
        storage.save(settings)

    return _json_result(
        result=f"Batch setup: {total} added",
        settings_path=str(settings.path),
        paths_added=paths_added,
        edit_added=edit_added,
        mcp_added=mcp_added,
        domains_added=domains_added,
        skills_added=skills_added,
        skipped=0,
    )


def sandbox_batch_revoke(
    paths: list[str] | None = None,
    mcp_servers: list[str] | None = None,
    domains: list[str] | None = None,
    skill_prefixes: list[str] | None = None,
) -> str:
    """Remove write paths, MCP allow rules, domains, and Skill rules in one atomic write."""
    # Validate all entries before any mutation to prevent partial writes
    try:
        mcp_entries = [mcp_allow_entry(name) for name in mcp_servers or []]
        skill_entries = [skill_allow_entry(prefix) for prefix in skill_prefixes or []]
    except ValueError as exc:
        return _json_result(error=str(exc))

    settings = storage.load()
    paths_removed = 0
    mcp_removed = 0
    domains_removed = 0
    skills_removed = 0

    for p in paths or []:
        abs_path = _resolve_path(p)
        if abs_path in settings.sandbox.filesystem.allow_write:
            settings.sandbox.filesystem.allow_write.remove(abs_path)
            paths_removed += 1
        for entry in allow_entries_for_path(abs_path):
            if entry in settings.permissions.allow:
                settings.permissions.allow.remove(entry)

    for entry in mcp_entries:
        if entry in settings.permissions.allow:
            settings.permissions.allow.remove(entry)
            mcp_removed += 1

    for d in domains or []:
        if d in settings.sandbox.network.allowed_domains:
            settings.sandbox.network.allowed_domains.remove(d)
            domains_removed += 1

    for entry in skill_entries:
        if entry in settings.permissions.allow:
            settings.permissions.allow.remove(entry)
            skills_removed += 1

    total = paths_removed + mcp_removed + domains_removed + skills_removed
    if total:
        storage.save(settings)

    return _json_result(
        result=f"Batch revoke: {total} removed",
        settings_path=str(settings.path),
        paths_removed=paths_removed,
        mcp_removed=mcp_removed,
        domains_removed=domains_removed,
        skills_removed=skills_removed,
    )


def sandbox_list(format: str = "text") -> str:
    """List current sandbox configuration from settings.json."""
    settings = storage.load()

    if format == "json":
        return json.dumps(
            {
                "write_paths": settings.sandbox.filesystem.allow_write,
                "mcp_allow": [r for r in settings.permissions.allow if r.startswith("mcp__")],
                "skill_allow": [r for r in settings.permissions.allow if r.startswith("Skill(")],
                "edit_rules": [r for r in settings.permissions.allow if r.startswith("Edit(")],
                "domains": settings.sandbox.network.allowed_domains,
                "deny": settings.permissions.deny,
                "sandbox_enabled": settings.sandbox.enabled,
            }
        )

    lines: list[str] = []
    lines.append("## Sandbox Configuration")
    lines.append(f"Enabled: {settings.sandbox.enabled}")
    lines.append("")

    lines.append("### Write Paths")
    for p in settings.sandbox.filesystem.allow_write or ["(none)"]:
        lines.append(f"  - {p}")
    lines.append("")

    mcp_rules = [r for r in settings.permissions.allow if r.startswith("mcp__")]
    lines.append("### MCP Allow Rules")
    for r in mcp_rules or ["(none)"]:
        lines.append(f"  - {r}")
    lines.append("")

    skill_rules = [r for r in settings.permissions.allow if r.startswith("Skill(")]
    lines.append("### Skill Allow Rules")
    for r in skill_rules or ["(none)"]:
        lines.append(f"  - {r}")
    lines.append("")

    lines.append("### Network Domains")
    for d in settings.sandbox.network.allowed_domains or ["(none)"]:
        lines.append(f"  - {d}")
    lines.append("")

    lines.append("### Deny Rules")
    for r in settings.permissions.deny or ["(none)"]:
        lines.append(f"  - {r}")

    return "\n".join(lines)


def sandbox_check(
    path: str | None = None,
    server: str | None = None,
    domain: str | None = None,
    skill: str | None = None,
) -> str:
    """Check if a path, MCP server, domain, or skill prefix is configured in sandbox settings."""
    if not any([path, server, domain, skill]):
        return _json_result(error="At least one of path, server, domain, or skill required")

    settings = storage.load()
    results: list[dict[str, str]] = []

    if path:
        abs_path = _resolve_path(path)
        present = abs_path in settings.sandbox.filesystem.allow_write
        results.append(
            {"type": "path", "value": abs_path, "status": "present" if present else "missing"}
        )

    if server:
        try:
            entry = mcp_allow_entry(server)
        except ValueError as exc:
            return _json_result(error=str(exc))
        present = entry in settings.permissions.allow
        results.append(
            {"type": "server", "value": server, "status": "present" if present else "missing"}
        )

    if domain:
        present = domain in settings.sandbox.network.allowed_domains
        results.append(
            {"type": "domain", "value": domain, "status": "present" if present else "missing"}
        )

    if skill:
        try:
            entry = skill_allow_entry(skill)
        except ValueError as exc:
            return _json_result(error=str(exc))
        present = entry in settings.permissions.allow
        results.append(
            {"type": "skill", "value": skill, "status": "present" if present else "missing"}
        )

    return json.dumps({"results": results})


def sandbox_reconcile(
    expected_servers: list[str],
    expected_paths: list[str] | None = None,
    stale_servers: list[str] | None = None,
    expected_skill_prefixes: list[str] | None = None,
) -> str:
    """Sync expected vs actual MCP servers, paths, and skill
    prefixes. Removes stale, adds missing."""
    # Validate all server names before loading settings to prevent partial mutations
    try:
        expected_entries = [mcp_allow_entry(name) for name in expected_servers]
        skill_entries = [skill_allow_entry(prefix) for prefix in expected_skill_prefixes or []]
    except ValueError as exc:
        return _json_result(error=str(exc))

    settings = storage.load()
    added = 0
    removed = 0

    # Remove stale servers
    stale = stale_servers or []
    if not stale:
        # Infer stale: present MCP rules not in expected
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
            removed += 1

    # Add missing servers
    for entry in expected_entries:
        if entry not in settings.permissions.allow:
            settings.permissions.allow.append(entry)
            added += 1

    # Reconcile paths if provided
    if expected_paths is not None:
        for p in expected_paths:
            abs_path = _resolve_path(p)
            if abs_path not in settings.sandbox.filesystem.allow_write:
                settings.sandbox.filesystem.allow_write.append(abs_path)
                added += 1
            for entry in allow_entries_for_path(abs_path):
                if entry not in settings.permissions.allow:
                    settings.permissions.allow.append(entry)
                    added += 1

    # Reconcile skill prefixes if provided
    if expected_skill_prefixes is not None:
        for entry in skill_entries:
            if entry not in settings.permissions.allow:
                settings.permissions.allow.append(entry)
                added += 1

    if added or removed:
        storage.save(settings)

    return _json_result(
        result=f"Reconciled: {added} added, {removed} removed",
        settings_path=str(settings.path),
        added=added,
        removed=removed,
    )


# ---------------------------------------------------------------------------
# MCP registration
# ---------------------------------------------------------------------------


def register(mcp: FastMCP) -> None:
    """Register all sandbox tools with the MCP server."""
    mcp.tool()(sandbox_add_write_path)
    mcp.tool()(sandbox_remove_write_path)
    mcp.tool()(sandbox_set_deny)
    mcp.tool()(sandbox_batch_setup)
    mcp.tool()(sandbox_batch_revoke)
    mcp.tool()(sandbox_list)
    mcp.tool()(sandbox_check)
    mcp.tool()(sandbox_reconcile)
