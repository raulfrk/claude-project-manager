# Changelog — proj

## [0.23.2] — 2026-02-28
### Added
- `proj_explore_codebase` tool: structured codebase exploration (tech stack, entry points, key dirs, file tree) using Python stdlib — no Bash required
- `proj_git_reconcile_todos` tool: single-call git reconciliation combining `git_detect_work` + `git_suggest_todos` with structured suggestions output
- `proj_get_todo_context` tool: return todo + parent + requirements + research in one call, replacing 3–4 sequential tool calls
- `proj_setup_permissions` tool: grant all permission rules (path Read/Edit, Bash investigation tools, MCP wildcards) in one atomic `settings.json` write
- `proj_revoke_tool_permissions` tool: remove scoped Bash investigation-tool allow rules without touching unrelated rules
- `proj_perms_sync` tool: compare expected vs actual `settings.json` allow rules and report missing entries
- `todo_list_all` tool: list todos including archived items (`todos.yaml` + `archive.yaml`)
- `proj_load_session` tool: set active project for the current session only (not persisted globally); fuzzy-match project name with `difflib`
- `perms-sync` skill added to plugin skills

## [0.22.x – 0.7.0] — 2026-02-26 to 2026-02-28
### Added
- Todo ID migration (`proj_migrate_ids`): migrate T-prefix IDs (T001, T001.1) to numeric dot-notation (1, 1.1); backs up `todos.yaml`; renames content directories atomically
- `manual` tag support on todos: `todo_check_executable` guards `/proj:execute` and returns an error for manual-tagged todos; `/proj:full-workflow` skips execute step for manual todos
- `todo_tree` tool: return todos as nested JSON tree; prune done nodes with no active descendants; `include_done` flag for full history
- `proj_identify_batches` tool: topological sort of todo IDs with cycle detection (Kahn's algorithm), returns parallel execution batches
- `todo_set_content_flag` tool: mark `has_requirements` / `has_research` flags on a todo
- Content tools: `content_set_requirements`, `content_get_requirements`, `content_set_research`, `content_get_research` — per-todo markdown files under the tracking directory
- Git tools: `git_detect_work`, `git_link_todo`, `git_suggest_todos` — optional git integration across multi-repo projects
- `proj_grant_tool_permissions` tool: add scoped Bash allow rules for investigation tools (grep, find, ls, etc.) per project path
- `proj_add_repo` tool: register additional repository paths against a project
- `proj_set_permissions` tool: per-project `auto_grant` override (null = use global config)
- `claudemd_write` / `claudemd_read` tools: manage CLAUDE.md files in project repo directories
- SessionStart/End/PreCompact hooks: auto-inject project context (status, in-progress todos, recent notes) at session boundaries via `server/cli.py`
- `ctx_detect_project` tool: auto-detect active project from `$CLAUDE_PROJECT_DIR` by matching repo paths
- Todoist sync via existing `mcp__claude_ai_Todoist__*` MCP tools at skill level
- `migrate-to-proj` skill for migrating from legacy tracker format
- 28 skills total: `init-plugin`, `init`, `status`, `update`, `todo`, `define`, `research`, `decompose`, `execute`, `full-workflow`, `prep-workflow`, `sync`, `report`, `archive`, `switch`, `explore`, `load`, `list-proj`, `workflows`, `migrate-ids`, `migrate-to-proj`, `perms-sync`

## [0.6.0] — 2026-02-26
### Added
- `permissions.auto_allow_mcps: true` config key; `/proj:init-plugin` asks whether to auto-allow all plugin MCP tools
- Per-project Todoist MCP include when `todoist.enabled: true`

## [0.5.0] — 2026-02-26
### Fixed
- Source package moved to `server/server/` subdirectory, resolving `ModuleNotFoundError` at runtime
- Added regression tests for server structure

## [0.4.0] — 2026-02-26
### Fixed
- Removed explicit `"hooks"` key from `plugin.json` (duplicate auto-discovery fix)

## [0.3.0] — 2026-02-26
### Fixed
- Corrected `hooks.json` schema (two-level nesting required by Claude Code)

## [0.2.0] — 2026-02-26
### Added
- Initial full implementation: FastMCP server with project lifecycle tools
  - Project tools: `proj_init`, `proj_list`, `proj_get`, `proj_get_active`, `proj_set_active`, `proj_update_meta`, `proj_archive`
  - Todo tools: `todo_add`, `todo_list`, `todo_get`, `todo_update`, `todo_complete`, `todo_block`, `todo_unblock`, `todo_delete`, `todo_ready`, `todo_add_child`
  - Config tool: `config_load`, `config_init`, `config_update`
  - Context/notes tools: `ctx_session_start`, `ctx_session_end`, `notes_append`
- Todos stored in pure YAML (`todos.yaml`); completed todos archived to `archive.yaml`
- Nested todos with parent/child relationships and `blocked_by` dependency tracking
- Configurable default priority; all paths from `~/.claude/proj.yaml` (no hardcoded paths)
- Git integration optional per project (`git_enabled: false` degrades gracefully)
- 13 skills: `init-plugin`, `init`, `status`, `update`, `todo`, `define`, `research`, `decompose`, `execute`, `sync`, `report`, `archive`, `switch`

## [0.1.0] — 2026-02-26
### Added
- Initial skeleton — marketplace manifest and plugin scaffold
