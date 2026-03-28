"""MCP tools for managing Claude Code settings.json / settings.local.json permissions."""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from server.lib import storage

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


DEFAULT_DENY_RULES: list[str] = [
    "Bash(git push *)",
    "Bash(git push)",
    "Bash(git push --force*)",
    "Bash(git reset --hard*)",
    "Bash(git clean -f*)",
    "Bash(git checkout .)",
    "Bash(git restore .)",
    "Bash(git branch -D *)",
    "Bash(git rebase *)",
    "Bash(git stash drop *)",
    "Bash(git stash clear)",
    "Bash(rm -rf *)",
    "Bash(rm -r *)",
    "Bash(rm -f *)",
    "Bash(chmod 777 *)",
    "Bash(chown *)",
    "Bash(sudo *)",
    "Bash(curl *)",
    "Bash(wget *)",
    "Bash(ssh *)",
    "Bash(npm publish*)",
    "Bash(cargo publish*)",
    "Bash(twine upload*)",
    "Bash(docker rm *)",
    "Bash(docker rmi *)",
    "Bash(kill *)",
    "Bash(killall *)",
    "Bash(shutdown *)",
    "Bash(reboot *)",
    "Edit(~/.claude/settings.json)",
    "Edit(~/.claude/settings.local.json)",
]

KNOWN_STALE_MCP_SERVERS: list[str] = [
    "perms",
    "proj",
    "worktree",
    "sentry",
    "Todoist",
    "claude_ai_Todoist",
    "remotion-documentation",
    "claude_ai_WebSearch",
    "claude_ai_WebFetch",
]


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


def list_allow(scope: str = "all", target: str = "auto", format: str = "text") -> str:
    """List current allow rules from Claude Code settings files.

    When *format* is ``"json"``, returns a JSON string with structured data
    suitable for programmatic consumption::

        {"scopes": [{"scope": "user", "path": "...", "target": "sandbox",
                      "permissions_allow": [...], "sandbox_allow_write": [...]}]}
    """
    scopes = ["user", "project"] if scope == "all" else [scope]

    if format == "json":
        entries: list[dict[str, object]] = []
        for s in scopes:
            resolved = storage.resolve_target(target, s)
            if resolved == "sandbox":
                settings = storage.load_local(s)
            else:
                settings = storage.load(s)
            entry: dict[str, object] = {
                "scope": s,
                "path": str(settings.path),
                "target": resolved,
                "permissions_allow": list(settings.permissions.allow),
                "sandbox_allow_write": list(settings.sandbox.filesystem.allow_write),
            }
            if settings.permissions.deny:
                entry["permissions_deny"] = list(settings.permissions.deny)
            entries.append(entry)
        return json.dumps({"scopes": entries})

    # Default text format — unchanged behaviour
    lines: list[str] = []
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


def batch_setup(
    paths: list[str] | None = None,
    mcp_servers: list[str] | None = None,
    scope: str = "user",
    target: str = "auto",
    additional_directories: list[str] | None = None,
) -> str:
    """Add sandbox paths, MCP allow rules, and additional directories in one atomic write.

    Combines ``_add_path_sandbox`` (for sandbox mode), MCP wildcard rule
    addition, and ``permissions.additionalDirectories`` updates into a single
    ``storage.save()`` call.  Idempotent — already-present entries are skipped.
    """
    paths = paths or []
    mcp_servers = mcp_servers or []
    additional_directories = additional_directories or []

    if not paths and not mcp_servers and not additional_directories:
        return "No paths or servers specified — nothing to do."

    resolved = storage.resolve_target(target, scope)
    settings = _load_for_target(resolved, scope)

    # ── Sandbox paths ─────────────────────────────────────────────────────
    sandbox_added: list[str] = []
    sandbox_skipped = 0
    if paths and resolved == "sandbox":
        for p in paths:
            abs_path = str(Path(p).expanduser().resolve())
            added = _add_path_sandbox(settings, abs_path)
            if added:
                sandbox_added.extend(added)
            else:
                sandbox_skipped += 1

    # ── MCP wildcard rules ────────────────────────────────────────────────
    mcp_added: list[str] = []
    mcp_skipped = 0
    if mcp_servers:
        allow_set = set(settings.permissions.allow)
        for server in mcp_servers:
            entry = storage.mcp_allow_entry(server)
            if entry in allow_set:
                mcp_skipped += 1
            else:
                settings.permissions.allow.append(entry)
                allow_set.add(entry)
                mcp_added.append(entry)

    # ── Additional directories ───────────────────────────────────────────
    addl_added: list[str] = []
    addl_skipped = 0
    if additional_directories:
        existing = set(settings.permissions.additional_directories)
        for d in additional_directories:
            abs_d = str(Path(d).expanduser().resolve())
            if abs_d not in existing:
                settings.permissions.additional_directories.append(abs_d)
                existing.add(abs_d)
                addl_added.append(abs_d)
            else:
                addl_skipped += 1

    # ── Persist & report ──────────────────────────────────────────────────
    total_added = len(sandbox_added) + len(mcp_added) + len(addl_added)
    if not total_added:
        total_skipped = sandbox_skipped + mcp_skipped
        return f"Already up to date — {total_skipped} existing entry/entries skipped in {settings.path}."

    storage.save(settings)

    lines: list[str] = [f"Updated {settings.path}:"]
    if sandbox_added:
        lines.append(f"  Sandbox paths added: {len(sandbox_added)}")
        lines.extend(f"    {e}" for e in sandbox_added)
    if sandbox_skipped:
        lines.append(f"  Sandbox paths skipped (already present): {sandbox_skipped}")
    if mcp_added:
        lines.append(f"  MCP rules added: {len(mcp_added)}")
        lines.extend(f"    {e}" for e in mcp_added)
    if mcp_skipped:
        lines.append(f"  MCP rules skipped (already present): {mcp_skipped}")
    if addl_added:
        lines.append(f"  Additional directories added: {len(addl_added)}")
        lines.extend(f"    {e}" for e in addl_added)
    if addl_skipped:
        lines.append(f"  Additional directories skipped (already present): {addl_skipped}")
    return "\n".join(lines)


def batch_revoke(
    paths: list[str] | None = None,
    mcp_servers: list[str] | None = None,
    scope: str = "user",
    target: str = "auto",
    additional_directories: list[str] | None = None,
) -> str:
    """Remove sandbox paths, MCP allow rules, and additional directories in one atomic write.

    Inverse of batch setup. Removes matching paths from
    ``sandbox.filesystem.allowWrite`` (sandbox mode), matching
    ``mcp__<server>__*`` wildcard rules from ``permissions.allow``,
    and matching entries from ``permissions.additionalDirectories``.
    Single atomic write. Idempotent — removing non-existent entries is a no-op.
    """
    paths = paths or []
    mcp_servers = mcp_servers or []
    additional_directories = additional_directories or []

    if not paths and not mcp_servers and not additional_directories:
        return "Nothing to revoke — paths, mcp_servers, and additional_directories are all empty."

    resolved = storage.resolve_target(target, scope)
    settings = _load_for_target(resolved, scope)

    if not settings.path.exists():
        return f"Settings file {settings.path} does not exist — nothing to revoke."

    sandbox_removed = 0
    mcp_removed = 0
    addl_removed = 0

    # Remove sandbox paths
    if paths and resolved == "sandbox":
        for p in paths:
            abs_path = str(Path(p).expanduser().resolve())
            sandbox_removed += _remove_path_sandbox(settings, abs_path)

    # Remove MCP wildcard rules
    if mcp_servers:
        entries_to_remove = {storage.mcp_allow_entry(s) for s in mcp_servers}
        before = len(settings.permissions.allow)
        settings.permissions.allow = [
            e for e in settings.permissions.allow if e not in entries_to_remove
        ]
        mcp_removed = before - len(settings.permissions.allow)

    # Remove additional directories
    if additional_directories:
        dirs_to_remove = {str(Path(d).expanduser().resolve()) for d in additional_directories}
        before = len(settings.permissions.additional_directories)
        settings.permissions.additional_directories = [
            d for d in settings.permissions.additional_directories if d not in dirs_to_remove
        ]
        addl_removed = before - len(settings.permissions.additional_directories)

    total = sandbox_removed + mcp_removed + addl_removed
    if total == 0:
        return f"No matching entries found in {settings.path} — nothing removed."

    storage.save(settings)

    parts: list[str] = [f"Revoked {total} entry/entries from {settings.path}:"]
    if sandbox_removed:
        parts.append(f"  sandbox paths removed: {sandbox_removed}")
    if mcp_removed:
        parts.append(f"  MCP rules removed: {mcp_removed}")
    if addl_removed:
        parts.append(f"  additional directories removed: {addl_removed}")
    return "\n".join(parts)


_PATH_RULE_RE = re.compile(r"^(?:Read|Edit)\(//(.+?)/\*\*\)$")
_STALE_RULE_RE = re.compile(r"^(?:Read|Edit|Bash)\(")


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
    if settings.sandbox.allow_unsandboxed_commands is not False:
        settings.sandbox.allow_unsandboxed_commands = False
        actions.append("sandbox.allowUnsandboxedCommands = false")

    aw_set = set(settings.sandbox.filesystem.allow_write)

    # Auto-migrate existing Read/Edit path rules
    migrated: list[str] = []
    for p in _extract_paths_from_allow(settings.permissions.allow):
        if p not in aw_set:
            settings.sandbox.filesystem.allow_write.append(p)
            aw_set.add(p)
            migrated.append(p)

    # After migration, strip the source Read/Edit rules from permissions.allow
    allow_before = len(settings.permissions.allow)
    cleaned = [r for r in settings.permissions.allow if not _PATH_RULE_RE.match(r)]
    stripped_count = allow_before - len(cleaned)
    if stripped_count:
        settings.permissions.allow = cleaned
        actions.append(f"Stripped {stripped_count} Read/Edit rule(s) from permissions.allow")

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


def backup() -> str:
    """Create timestamped backups of settings.json and settings.local.json."""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backed_up: list[str] = []
    for name in ("settings.json", "settings.local.json"):
        src = Path.home() / ".claude" / name
        if src.exists():
            dst = src.with_suffix(f".pre-sandbox-{timestamp}.json")
            shutil.copy2(src, dst)
            backed_up.append(str(dst))
    return f"Backed up {len(backed_up)} file(s) with suffix .pre-sandbox-{timestamp}.json"


def restore(timestamp: str) -> str:
    """Restore settings files from a timestamped backup."""
    restored: list[str] = []
    for name in ("settings.json", "settings.local.json"):
        backup_path = Path.home() / ".claude" / f"{Path(name).stem}.pre-sandbox-{timestamp}.json"
        target = Path.home() / ".claude" / name
        if backup_path.exists():
            shutil.copy2(backup_path, target)
            restored.append(name)
    return f"Restored {len(restored)} file(s) from .pre-sandbox-{timestamp} backups"


def cleanup_stale() -> str:
    """Strip Read/Edit/Bash rules from both settings files, keeping only MCP + WebFetch rules."""
    results = []
    loaders = [
        ("settings.json", lambda: storage.load("user")),
        ("settings.local.json", lambda: storage.load_local("user")),
    ]
    for name, loader in loaders:
        path = Path.home() / ".claude" / name
        if not path.exists():
            continue
        data = loader()
        allow = data.permissions.allow
        before = len(allow)
        # Keep only mcp__* rules and WebFetch() rules
        cleaned = [r for r in allow if not _STALE_RULE_RE.match(r)]
        after = len(cleaned)
        if before != after:
            data.permissions.allow = cleaned
            storage.save(data)
            results.append(f"{name}: {before} -> {after} rules ({before - after} removed)")
        else:
            results.append(f"{name}: {before} rules (no stale rules found)")
    return "\n".join(results) if results else "No settings files found."


def is_sandbox_enabled_tool(scope: str = "user") -> str:
    """Check if sandbox mode is enabled."""
    enabled = storage.is_sandbox_enabled(scope)
    return f"sandbox_enabled: {str(enabled).lower()}"


def set_sandbox_paths(paths: list[str], preserve_extra: bool = True) -> str:
    """Replace sandbox.filesystem.allowWrite paths atomically.

    Default preserves user-added paths not under the given roots.
    """
    settings = storage.load_local()
    resolved = [str(Path(p).expanduser().resolve()) for p in paths]

    preserved: list[str] = []
    if preserve_extra:
        for existing in settings.sandbox.filesystem.allow_write:
            if not any(existing.startswith(r + "/") or existing == r for r in resolved):
                preserved.append(existing)
        new_paths = resolved + preserved
    else:
        new_paths = resolved

    settings.sandbox.filesystem.allow_write = new_paths
    storage.save(settings)
    return f"Sandbox paths set: {len(resolved)} root(s), {len(preserved)} preserved"


def set_deny(rules: list[str], clear_settings_json_deny: bool = False) -> str:
    """Replace permissions.deny rules atomically in settings.local.json."""
    settings = storage.load_local()
    settings.permissions.deny = list(rules)
    storage.save(settings)

    if clear_settings_json_deny:
        main = storage.load()
        if main.permissions.deny:
            main.permissions.deny = []
            storage.save(main)

    return f"Deny rules set: {len(rules)} rules in settings.local.json"


def reconcile_mcp(expected_servers: list[str], stale_servers: list[str] | None = None) -> str:
    """Reconcile MCP wildcard rules: remove known-stale servers, add missing expected servers."""
    expected = {f"mcp__{s}__*" for s in expected_servers}
    stale = {f"mcp__{s}__*" for s in (stale_servers or [])}

    main = storage.load()
    local = storage.load_local()

    # Remove stale from both
    main_before = len(main.permissions.allow)
    main.permissions.allow = [r for r in main.permissions.allow if r not in stale]
    main_removed = main_before - len(main.permissions.allow)

    local_before = len(local.permissions.allow)
    local.permissions.allow = [r for r in local.permissions.allow if r not in stale]
    local_removed = local_before - len(local.permissions.allow)

    # Find missing: expected - (set of main.allow) - (set of local.allow)
    merged = set(main.permissions.allow) | set(local.permissions.allow)
    missing = expected - merged

    # Add missing to local only
    local.permissions.allow.extend(sorted(missing))

    storage.save(main)
    storage.save(local)

    total_removed = main_removed + local_removed
    return (
        f"MCP reconciled: {total_removed} stale removed, "
        f"{len(missing)} missing added to settings.local.json"
    )


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
            "target: 'settings', 'sandbox', or 'auto' (default). "
            "format: 'text' (default, human-readable) or 'json' (structured data for programmatic use)."
        )
    )
    def perms_list(scope: str = "all", target: str = "auto", format: str = "text") -> str:
        return list_allow(scope, target, format)

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
            "Add sandbox filesystem paths and MCP server allow rules in one atomic write. "
            "In sandbox mode: adds each path to sandbox.filesystem.allowWrite. "
            "In all modes: adds mcp__<server>__* wildcard rules to permissions.allow. "
            "Single file write regardless of how many paths/servers. Idempotent. "
            "target: 'settings', 'sandbox', or 'auto' (default)."
        )
    )
    def perms_batch_setup(
        paths: list[str] | None = None,
        mcp_servers: list[str] | None = None,
        scope: str = "user",
        target: str = "auto",
        additional_directories: list[str] | None = None,
    ) -> str:
        return batch_setup(paths, mcp_servers, scope, target, additional_directories)

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
        description=(
            "Create timestamped backups of ~/.claude/settings.json and "
            "~/.claude/settings.local.json. Use before making bulk permission changes "
            "so you can roll back with perms_restore."
        )
    )
    def perms_backup() -> str:
        return backup()

    @app.tool(
        description=(
            "Restore settings files from a timestamped backup created by perms_backup. "
            "Pass the timestamp string (e.g. '20260321-143000') to restore from "
            ".pre-sandbox-<timestamp>.json files."
        )
    )
    def perms_restore(timestamp: str) -> str:
        return restore(timestamp)

    @app.tool(
        description=(
            "Strip stale Read/Edit/Bash rules from permissions.allow in both "
            "~/.claude/settings.json and ~/.claude/settings.local.json, keeping only "
            "MCP wildcard (mcp__*) and WebFetch rules. Useful after migrating to "
            "sandbox mode where file-path rules are no longer needed."
        )
    )
    def perms_cleanup_stale() -> str:
        return cleanup_stale()

    @app.tool(
        description=(
            "Remove sandbox paths, MCP allow rules, and additional directories in one atomic write. "
            "Inverse of batch setup. Accepts lists of filesystem paths, MCP server names, "
            "and additional directories. "
            "In sandbox mode removes matching paths from sandbox.filesystem.allowWrite. "
            "Removes matching mcp__<server>__* rules from permissions.allow. "
            "Removes matching entries from permissions.additionalDirectories. "
            "Idempotent — removing non-existent entries is a no-op. "
            "target: 'settings', 'sandbox', or 'auto' (default)."
        )
    )
    def perms_batch_revoke(
        paths: list[str] | None = None,
        mcp_servers: list[str] | None = None,
        scope: str = "user",
        target: str = "auto",
        additional_directories: list[str] | None = None,
    ) -> str:
        return batch_revoke(paths, mcp_servers, scope, target, additional_directories)

    @app.tool(
        description=(
            "Check if sandbox mode is enabled in settings.local.json. "
            "Returns 'sandbox_enabled: true' or 'sandbox_enabled: false'. Read-only."
        )
    )
    def perms_is_sandbox_enabled(scope: str = "user") -> str:
        return is_sandbox_enabled_tool(scope)

    @app.tool(
        description=(
            "Replace sandbox.filesystem.allowWrite paths atomically. "
            "Default preserves user-added paths not under the given roots."
        )
    )
    def perms_set_sandbox_paths(paths: list[str], preserve_extra: bool = True) -> str:
        return set_sandbox_paths(paths, preserve_extra)

    @app.tool(
        description="Replace permissions.deny rules atomically in settings.local.json."
    )
    def perms_set_deny(rules: list[str], clear_settings_json_deny: bool = False) -> str:
        return set_deny(rules, clear_settings_json_deny)

    @app.tool(
        description=(
            "Reconcile MCP wildcard rules: remove known-stale servers from both settings files, "
            "add missing expected servers to settings.local.json only."
        )
    )
    def perms_reconcile_mcp(
        expected_servers: list[str], stale_servers: list[str] | None = None
    ) -> str:
        return reconcile_mcp(expected_servers, stale_servers)
