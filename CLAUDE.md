# claude-project-manager

**Status**: active | **Priority**: medium
**Tracking**: ~/projects/tracking/claude-project-manager

## Overview

Claude Code plugin marketplace for project management workflows. Three plugins:
- `perms` — auto-manage `settings.json` permissions (file paths + MCP tool wildcards)
- `worktree` — git worktree management
- `proj` — full project lifecycle (todos, notes, git, Todoist sync)

## Key Conventions

- Version must be bumped in both `plugin.json` and `marketplace.json` together
- `hooks/hooks.json` is auto-discovered — do NOT reference it in `plugin.json`
- Source files live in `plugins/<name>/server/server/` (inner `server/` is the Python package)
- Skills invoked as `/proj:<name>`, `/worktree:<name>`
- MCP allow rules: `mcp__<server>__*` wildcard format; use `perms_add_mcp_allow(server_name)`

## Todo Tags

Todos support a `tags: list[str]` field. The `manual` tag has special behaviour:

- **`manual`** — marks a todo as requiring human execution. Claude will not execute it.
  - `/proj:execute <id>` shows a warning and stops: "⚠️ Todo <id> is tagged `manual` — execute it yourself, then run `/proj:todo done <id>`"
  - `/proj:full-workflow <id>` runs define/research/decompose normally but skips the execute step
  - In range/batch mode, manual todos are skipped at execute with a warning in the summary
  - MCP guard: `todo_check_executable(todo_id)` returns an error for manual-tagged todos
  - Display: `[manual]` badge shown after priority in all todo list/tree/decompose output
  - Tags do NOT propagate to child todos; each todo is independent
  - No effect on Todoist sync

## Skill Files

New skills go in `plugins/<name>/skills/<skill-name>/SKILL.md`. Add new skills to the README skill reference table and the "Skills by category" list.
