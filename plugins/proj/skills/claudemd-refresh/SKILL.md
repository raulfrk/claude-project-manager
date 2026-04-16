---
name: claudemd-refresh
description: Refresh cpm-managed block in ~/.claude/CLAUDE.md to the current version. Use after upgrading cpm to pick up new rules without re-running the installer wizard. Use when user says "refresh claudemd", "update managed block", or "refresh managed section".
allowed-tools: mcp__plugin_proj_proj__claudemd_refresh_managed
context: fork
agent: general-purpose
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

# claudemd-refresh

Refresh cpm-managed block in `~/.claude/CLAUDE.md`. Single-step op.

## Flow

**1.** Call `mcp__plugin_proj_proj__claudemd_refresh_managed()`.

**2.** Parse result `{updated: bool, path: str}`.

**3.** Report:

- `updated=true` → "Managed block refreshed at `<path>`. Pick up new rules in next Claude session."
- `updated=false` → "Managed block already current at `<path>`. No changes."

## Err Handling

- Tool raises → surface err verbatim. Likely cause: `~/.claude` unreadable or installer pkg missing. Suggest: verify `~/.claude` perms or reinstall cpm.

## When to Use

- After `uv tool upgrade cpm-install` or equivalent cpm upgrade.
- After pulling new cpm rules from main (dev only).
- When `~/.claude/CLAUDE.md` missing the cpm-managed block entirely.

## When NOT to Use

- Normal session start — block is static, refresh only needed on upgrade.
- User wants to *remove* managed block — use installer uninstall flow instead.
