# claude-project-manager

**Status**: active | **Priority**: medium
**Tracking**: ~/projects/tracking/claude-project-manager

## Overview

Claude Code plugin marketplace for project management workflows. Five plugins:
- `perms` — auto-manage `settings.json` permissions (file paths + MCP tool wildcards)
- `worktree` — git worktree management
- `proj` — full project lifecycle (todos, notes, git, Todoist/Trello/Jira sync)
- `trello` — Trello MCP server (boards, cards, checklists, labels, comments, attachments)
- `jira` — Jira MCP server (issues, projects, epics, bulk operations)

## Overhaul Plan

A comprehensive overhaul requirements document exists at:
`~/projects/tracking/claude-project-manager/overhaul-requirements.md` (7,565 lines)

It contains the full workflow map, user vision, quality assessment, gap analysis, 31 change proposals, and 35 implementation todos across 6 phases. **Read this file before starting any overhaul work.** Key architectural decisions:
- **Hooks plugin** (`plugins/hooks/`) — central MCP→MCP registry with schema-based param mapping, auto-registration, and recovery
- **3 new plugins planned**: `plugins/todoist/` (local, replacing external MCP), `plugins/zoxide/`, `plugins/hooks/`
- **Perms is single source of truth** for settings.json — proj must never write settings files directly
- **Proj must not read worktree.yaml directly** — use worktree MCP tools
- **Remove deny functionality** from perms (denyWrite/denyRead)
- **Define skill rewrite** — free-form writing → probing Q&A → iterative rerun → quality gate
- **Default --iter 5** for `/proj:run`

## Task Planning

Before starting any non-trivial task, evaluate whether it should be broken down into a todo list of smaller steps. Use task tracking to manage progress on multi-step work.

## Implementation Validation

After completing any implementation, always validate the result against the specs (requirements, research, or overhaul document) that were provided for that work. Check for gaps, deviations, and missing test coverage before marking a todo as done.

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
  - `/proj:run <id>` runs define/decompose normally but skips the execute step
  - In range/batch mode, manual todos are skipped at execute with a warning in the summary
  - MCP guard: `todo_check_executable(todo_id)` returns an error for manual-tagged todos
  - Display: `[manual]` badge shown after priority in all todo list/tree/decompose output
  - Tags do NOT propagate to child todos; each todo is independent
  - No effect on Todoist sync

## Verification

`/proj:execute` and `/proj:run` include a verification step (execute step **4a.**) after implementation, before the satisfaction prompt. Three checks run in sequence:
- **Automated checks**: detect test runner (`pyproject.toml` `[tool.pytest]` → `uv run pytest`, `package.json` `"test"` script → `npm test`) and linter (`[tool.ruff]` → `uv run ruff check`, `.eslintrc*` → `npx eslint`)
- **Spec validation**: read requirements.md acceptance criteria, compare each against `git diff`, categorize as met/unmet/unverifiable
- **Diff review**: compare approved plan's "Files to modify" list against `git diff --name-only`, flag planned-but-untouched and unplanned files

**Report format**: single-todo uses inline per-category results; batch/range uses a combined table (`| Todo | Automated | Spec | Diff | Status |`).

**Graceful degradation**: if no test runner, skip automated checks with note; if no requirements.md, skip spec validation; if no plan (`--no-interactive`), skip diff review. Never fail the whole step for missing prerequisites.

- `--no-verify` flag skips the entire verification step (default: verification ON)
- Reports persisted to `todos/<id>/verification-report.md` in the tracking dir (overwritten each run)
- In batch/range mode, all todos are verified first, then a combined report is shown before prompting
- Fix flow: user can choose to spawn agents to fix failures (max 2 retries), then re-verify
- Full details: `plugins/proj/skills/execute/SKILL.md` (step **4a.**) and `plugins/proj/skills/run/SKILL.md`

## Config Naming Conventions

- **Field names**: `underscore_case` (`tracking_dir`, `auto_sync`, `default_priority`)
- **Nested section names**: lowercase (`sync.todoist`, `permissions`, `archive`)
- **Integration flags**: `underscore_case` (`perms_integration`, `worktree_integration`)
- **MCP tool names**: `mcp__plugin_<name>_<name>__<tool_name>` (internal plugins), `mcp__<server>__<tool-name>` (external MCP servers)
- **Git flush messages**: `"Action: subject"` pattern (`"Define: {todo-id}"`, `"Sync: Jira"`, `"Save: session"`)

## Skill Files

New skills go in `plugins/<name>/skills/<skill-name>/SKILL.md`. Add new skills to the README skill reference table and the "Skills by category" list.

### context/agent Frontmatter Criteria

Add `context: fork` and `agent: general-purpose` to skills that can run autonomously without user interaction during execution. Criteria:
- Skill performs a self-contained operation (list, sync, status display)
- Skill does NOT require interactive Q&A during execution
- Skill does NOT need plan mode approval mid-execution
- Examples: hooks-*, status, todo, todoist-sync, trello-sync, jira-sync, jira-sync-trello
- Do NOT add to: interactive skills (define, init, load), sub-skills, or skills needing plan approval (execute, run, quick)
