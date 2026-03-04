# Changelog

## 0.8.0 — 2026-03-03

Add `claude-helper` plugin:
- New plugin for reviewing Claude Code skill and agent definition files
- `review-skill`, `review-agent`, `review-all` skills scoring 10 quality dimensions
- Pure-skill architecture — no MCP server, no external dependencies

New `proj` skills:
- `quick-workflow` — create a new todo and immediately run full-workflow on it
- `save` — save session notes and write a dated session file to tracking dir
- `agents-list`, `agents-set`, `agents-remove` — manage per-project agent overrides for workflow steps
- `create-agent` — create a custom Claude Code agent file for a workflow step

New `perms` MCP tools:
- `perms_remove_mcp_allow` — remove a wildcard allow rule for an MCP server
- `perms_batch_add_mcp_allow` — add wildcard rules for multiple servers in one atomic write

## 0.6.0 — 2026-02-26

Auto-allow plugin MCP tools during init:
- `perms` plugin: new `perms_add_mcp_allow` and `perms_remove_mcp_allow` MCP tools — add/remove `mcp__<server>__*` wildcard allow rules to `settings.json`
- `proj` plugin: new `permissions.auto_allow_mcps: true` config key in `proj.yaml`; `/proj:init-plugin` asks user whether to auto-allow all plugin MCP tools; `/proj:init` supports per-project override; Todoist MCP included when `todoist.enabled: true`
- 10 new tests in perms covering MCP allow rules

## 0.5.0 — 2026-02-26

Fix perms MCP server failing to start — source files were in the uv project root (`server/`) instead of the required `server/server/` package subdirectory, causing `ModuleNotFoundError: No module named 'server'` at runtime. Added 4 regression tests (`test_server_structure.py`) that catch this.

## 0.4.0 — 2026-02-26

Fix duplicate hooks reference — remove `"hooks": "./hooks/hooks.json"` from `plugin.json`; Claude Code auto-discovers `hooks/hooks.json` and the explicit reference caused "Duplicate hooks file detected". Added regression test.

## 0.3.0 — 2026-02-26

Fix hooks.json schema — correct two-level nesting (`matcher group → hooks array`) required by Claude Code.

## 0.2.0 — 2026-02-26

Full implementation:
- **perms** plugin — MCP tools for auto-managing Claude Code `settings.json` permissions
- **worktree** plugin — MCP tools + skills for git worktree management
- **proj** plugin — full project lifecycle management with MCP server, hooks, and 13 skills:
  - `init-plugin`, `init`, `status`, `update`, `todo`, `define`, `research`, `decompose`, `execute`, `sync`, `report`, `archive`, `switch`
  - SessionStart/End/PreCompact hooks for auto context injection
  - Nested todos with dependencies, requirements & research lifecycle
  - Todoist sync via existing MCP tools
  - Git integration (optional, multi-repo)
  - CLAUDE.md per project directory

## 0.1.0 — 2026-02-26

Initial skeleton — marketplace manifest and plugin scaffold.
