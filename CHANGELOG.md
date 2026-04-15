# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [5.0.0] - 2026-04-15

Breaking changes. No backward-compat shims. Update skill files and hook configs on upgrade.

### Removed tools (use replacement)

**proj plugin:**
- `todo_add_child(parent_id, title)` → `todo_add(title=..., parent=parent_id)`
- `todo_batch_add_children(parent_id, children)` → `todo_add(parent=parent_id, children=<json>)`
- `todo_batch_complete(todo_ids)` → `todo_complete(todo_ids=[...])`
- `todo_block(todo_id, blocks_ids)` → `todo_update(todo_id=blocked_id, blocked_by_set=[blocker_id])`
- `todo_unblock(todo_id)` → `todo_update(todo_id=todo_id, blocked_by_set=[])`
- `proj_todoist_full_sync()` → `proj_sync(integration="todoist")`
- `proj_trello_full_sync()` → `proj_sync(integration="trello")`
- `proj_jira_full_sync()` → `proj_sync(integration="jira")`

**trello plugin:**
- `batch_add_checklist_items(checklist_id, items)` → `add_checklist_item(checklist_id, items=[...])`
- `batch_update_checklist_items(card_id, updates)` → `update_checklist_item(card_id, updates=[...])`

**jira plugin:**
- `jira_bulk_update_issues(issues)` → `jira_update_issues(issues=[...])`

**todoist plugin:**
- `todoist_complete_task_hook`, `todoist_update_task_hook`, `todoist_add_child_task_hook`, `todoist_add_project_hook` — removed (dead hook-variant wrappers)

**sandbox plugin (now in proj):**
- `sandbox_add_mcp_allow`, `sandbox_remove_mcp_allow`, `sandbox_add_skill_allow`, `sandbox_remove_skill_allow`, `sandbox_add_domain`, `sandbox_remove_domain` — removed (use `sandbox_batch_setup` / `sandbox_batch_revoke`)

### Removed plugins (functionality folded)

- **analyse** → skills now available as `proj:review`, `proj:explore`
- **zoxide** → tools (`zoxide_boost`, `zoxide_query`, `zoxide_remove`) moved into `worktree` MCP server (names unchanged)
- **sandbox** → tools moved into `proj` MCP server (names unchanged); `mcp__plugin_sandbox_sandbox__*` allow rule now covered by `mcp__plugin_proj_proj__*`

### Storage changes

- YAML fallback removed from storage layer — `data.db` missing now raises `FileNotFoundError`
- `archive.yaml.bak` disaster-recovery path in `load_archived_todos` retained

### Hook migration

Hooks with renamed trigger/target tools must be updated in `~/.claude/hooks.yaml`:
- `trigger_tool: todo_add_child` → `todo_add`
- `trigger_tool: todo_batch_add_children` → `todo_add`
- `trigger_tool: todo_batch_complete` → `todo_complete`
- `target_tool: proj_todoist_full_sync` → `proj_sync` (add `integration: "todoist"` param)
- `target_tool: proj_jira_full_sync` → `proj_sync` (add `integration: "jira"` param)
- `target_tool: jira_bulk_update_issues` → `jira_update_issues`

### Upgrade path

1. Re-run installer to update MCP server entries (removes zoxide/sandbox standalone servers)
2. Run `python scripts/migrate_hooks.py --dry-run` then without `--dry-run` to update hooks
3. Update any custom skill files that call removed tool names

## [Unreleased]

### Breaking changes
- **Plugin `hooks` renamed to `router`.** MCP-to-MCP registry plugin now at `plugins/router/`. Tool names updated: `hooks_fire_tool` → `router_fire_tool` (etc.). MCP tool prefix: `mcp__plugin_hooks_hooks__*` → `mcp__plugin_router_router__*`. Slash commands: `/proj:hooks-*` → `/router:*`. Socket path prefix: `claude-hooks-` → `claude-cpm-`. Registry directory: `~/.claude/sockets/router`.
- **No backwards-compat fallback.** Users must run `claude-installer update` and restart any running MCP servers. Manual cleanup: `rm -rf ~/.claude/plugins/cache/claude-project-manager/hooks ~/.claude/sockets/hooks /tmp/claude-hooks-*.sock`. Settings.json: `enabledPlugins: hooks@claude-project-manager` → `router@claude-project-manager`, `permissions.allow: mcp__plugin_hooks_hooks__*` → `mcp__plugin_router_router__*`, `permissions.allow: Skill(hooks::*)` → `Skill(router::*)`.

### Added
- Documentation: `docs/architecture.md`, `docs/plugins.md`, `docs/development.md`
- This changelog (rewritten in Keep a Changelog format)

## [3.0.1] - 2026-04-07

### Fixed
- Test suite fixes across proj, hooks, and sandbox plugins

## [3.0.0] - 2026-04-06

### Added
- Sandbox plugin (v0.2.0): Skill permission management (`sandbox_add_skill_allow`, `sandbox_remove_skill_allow`)
- Todoist load hook, Jira create issue tool
- Cascade dispatch for blocking hooks with nested error propagation
- Hook invocation history tool and `/hooks:hooks-debug` skill (hooks 1.9.0)

### Changed
- Replaced perms plugin with sandbox plugin as single source of truth for `settings.json`
- Eliminated `Any`/`object` types, enforced strict typing across all plugins
- Skill invocations now use Skill tool calls and `context: fork`

### Fixed
- Sandbox uv cache blocked by Claude Code sandbox mode
- Hook dispatch: socket registry priority, batch result fields, batch feedback mapping
- Lazy transport resolution in hook dispatch (claude-hook-transport 0.3.1)
- Trello sync: UnboundLocalError, list mismatches, snapshot recording, root-todo delete
- True last-changed-wins conflict resolution using `trello_updated` timestamp
- Cascade delete children when `pull_delete` is applied
- Log feedback writeback failures and surface in `_hooks.errors`
- Create checklist when `checklist_id` is null for Trello hook sync
- Push reopen op to Trello when local wins and local state is incomplete

## [2.10.0] - 2026-03-20

### Added
- Todoist full-sync at MCP layer (proj 2.10.0)
- Blocking hook chain with `_hooks` injection
- `proj_trello_full_sync` and `proj_jira_full_sync` MCP tools
- Analyse plugin (v1.0.0): guided code review with `/review:review` skill

### Fixed
- Todoist pull phase parent inference from child-task links
- Prevent duplicate Todoist tasks on `push_create` retry
- Todoist timestamp comparison (date-only strings, proper datetime)
- Never push_complete Todoist tasks based on archived todos
- Include `project_name` in feedback writeback params
- Honour `quality_level` and `worktree_isolation` from config in `/proj:run`
- Unwrap Jira search response envelope in `proj_jira_full_sync`

## [2.9.0] - 2026-03-15

### Added
- `proj_trello_full_sync` tool with pull/push/delete operations
- `pull_delete` integration with Trello full sync

## [2.0.0] - 2026-03-01

### Added
- Hooks plugin (v1.0.0): central MCP-to-MCP hook registry with condition evaluation
- Todoist plugin (v1.0.0): local Todoist MCP server replacing external MCP
- Trello plugin (v2.0.0): full CRUD for boards, lists, cards, labels, comments, checklists, attachments
- Jira plugin (v2.0.0): read-only Jira Server issue and project access
- Zoxide plugin (v1.0.0): frecency database integration
- Hook dispatch system with Unix domain sockets and TCP fallback
- Bidirectional Todoist sync with priority mapping and ghost detection
- Trello board sync (cards mapped to root todos)

### Changed
- Multi-directory project support with migration from single-dir format
- Git tracking with per-project overrides

## [0.9.0] - 2026-04-06

### Fixed
- Sandbox MCP server failing to start: `uv sync` could not write to `~/.cache/uv` in Claude Code sandbox mode; added `UV_CACHE_DIR` fallback to all plugin `start.sh` scripts

## [0.8.0] - 2026-03-03

### Added
- `claude-helper` plugin: review Claude Code skill and agent definition files
- `review-skill`, `review-agent`, `review-all` skills scoring 10 quality dimensions
- Proj skills: `quick-workflow`, `save`, `agents-list`, `agents-set`, `agents-remove`, `create-agent`
- Perms tools: `perms_remove_mcp_allow`, `perms_batch_add_mcp_allow`

## [0.6.0] - 2026-02-26

### Added
- Auto-allow plugin MCP tools during init
- Perms tools: `perms_add_mcp_allow`, `perms_remove_mcp_allow`
- Proj config: `permissions.auto_allow_mcps` with per-project override
- 10 new tests for perms MCP allow rules

## [0.5.0] - 2026-02-26

### Fixed
- Perms MCP server failing to start: source files in wrong directory (`server/` instead of `server/server/`), causing `ModuleNotFoundError`
- Added 4 regression tests for server structure

## [0.4.0] - 2026-02-26

### Fixed
- Duplicate hooks reference: removed explicit `hooks.json` from `plugin.json` (auto-discovered by Claude Code)

## [0.3.0] - 2026-02-26

### Fixed
- `hooks.json` schema: corrected two-level nesting required by Claude Code

## [0.2.0] - 2026-02-26

### Added
- Perms plugin: MCP tools for auto-managing Claude Code `settings.json` permissions
- Worktree plugin: MCP tools + 6 skills for git worktree management
- Proj plugin: full project lifecycle with MCP server, hooks, and 13 skills
- Nested todos with dependencies, requirements and research lifecycle
- Todoist sync via MCP tools, Git integration, per-project CLAUDE.md

## [0.1.0] - 2026-02-26

### Added
- Initial skeleton: marketplace manifest and plugin scaffold
