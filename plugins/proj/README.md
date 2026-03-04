# proj

Full project lifecycle management for Claude Code. Track todos, notes, git activity, and Todoist sync across all your projects — from a single active-project context that auto-loads at session start.

---

## Table of Contents

- [What it does](#what-it-does)
- [Requirements](#requirements)
- [Installation](#installation)
- [First-time setup](#first-time-setup)
- [Key concepts](#key-concepts)
- [Skills](#skills)
- [MCP tools reference](#mcp-tools-reference)
- [Todo tags](#todo-tags)
- [Todo IDs](#todo-ids)
- [Configuration](#configuration)
- [Hooks](#hooks)
- [Todoist sync](#todoist-sync)
- [Permissions integration](#permissions-integration)

---

## What it does

The `proj` plugin provides a complete project management workflow inside Claude Code:

- **Project tracking** — each project has a tracking directory (`~/projects/tracking/<name>/`) containing a `todos.yaml`, `NOTES.md`, and per-todo `requirements.md` / `research.md` files.
- **Todo lifecycle** — add, prioritize, block/unblock, complete, and archive todos with hierarchical dot-notation IDs (`1`, `1.1`, `1.2.3`).
- **Full workflow** — structured skills for defining requirements, researching approaches, decomposing into sub-todos, and executing them — individually or in parallel batches.
- **Git integration** — detect recent commits across all project repos, suggest todo completions, and link commits to specific todos.
- **Todoist sync** — bidirectional sync with a Todoist project (optional).
- **CLAUDE.md management** — write and update per-project `CLAUDE.md` files to keep Claude's context current.
- **Session context** — at session start, the plugin auto-injects the active project's status, in-progress todos, and recent notes.

---

## Requirements

- Claude Code with MCP support
- Python 3.12+ (managed by `uv`)
- `uv` installed (`pip install uv` or `brew install uv`)

---

## Installation

Install from the Claude Code plugin marketplace:

```
/plugins install proj
```

Or install manually by cloning this repository and adding the MCP server to `~/.claude/mcp.json`:

```json
{
  "mcpServers": {
    "proj": {
      "command": "uv",
      "args": ["--directory", "/path/to/plugins/proj/server", "run", "proj-server"],
      "env": {
        "PROJ_CONFIG": "~/.claude/proj.yaml"
      }
    }
  }
}
```

---

## First-time setup

Run the interactive setup wizard once before using any other `proj` commands:

```
/proj:init-plugin
```

This asks you for:

| Setting | Default | Description |
|---------|---------|-------------|
| Tracking directory | `~/projects/tracking` | Where todos.yaml, NOTES.md, and per-todo content are stored |
| Projects base directory | (none) | If set, `/proj:init` uses `<base>/<name>` as the content path |
| Auto-grant permissions | yes | Add Read/Edit allow rules for project directories automatically |
| Auto-allow MCP tools | yes | Add `mcp__plugin_proj_proj__*` wildcard allow rules to settings.json |
| Todoist sync | no | Enable bidirectional Todoist sync |
| Git integration | yes | Detect recent commits and suggest todo updates |
| Default priority | medium | Default priority for new todos |
| perms plugin installed | no | Required for automatic permission management |
| worktree plugin installed | no | Required for worktree integration |

Configuration is written to `~/.claude/proj.yaml`.

After setup, initialize your first project:

```
/proj:init my-project
```

---

## Key concepts

### Project tracking directory

Each project gets a tracking directory at `<tracking_dir>/<project-name>/` containing:

```
tracking/my-project/
  meta.yaml          # project metadata (status, priority, repos, etc.)
  todos.yaml         # active todos
  archive.yaml       # completed todos
  NOTES.md           # freeform dated notes
  <todo-id>/
    requirements.md  # structured requirements (from /proj:define)
    research.md      # implementation research (from /proj:research)
```

### todos.yaml

Todos are stored as plain YAML — no frontmatter, no markdown. Each todo has:

- `id` — dot-notation string (`1`, `1.1`, `2.3.1`)
- `title`, `status` (`pending` / `in_progress` / `done`)
- `priority` (`low` / `medium` / `high`)
- `tags` — list of strings; `manual` has special behavior (see [Todo tags](#todo-tags))
- `blocked_by`, `blocks` — dependency lists
- `parent`, `children` — hierarchy
- `notes` — inline notes
- `git.branch`, `git.commits` — linked git references
- `todoist_task_id` — set when synced with Todoist
- `has_requirements`, `has_research` — flags indicating content files exist

### CLAUDE.md per project

Each project's content directory can have a `CLAUDE.md` that gives Claude context about the codebase. The `/proj:init` skill creates one automatically; `/proj:update` and `/proj:execute` keep it current. `/proj:explore` scans the codebase and writes or merges findings into CLAUDE.md.

### Active project

One project is "active" at a time. The active project is used as the default target for all todo and note operations. The active project persists across sessions (stored in the project index); use `/proj:load` to set a session-only override without changing the global active project.

### Session context injection

At session start, the `SessionStart` hook calls `ctx_session_start`, which auto-detects the active project from `$CLAUDE_PROJECT_DIR` (by matching the cwd against registered repo paths) and injects a context block into the conversation:

```
## Active Project: my-project
Status: active | Priority: high
...
### In Progress
### Ready to Start
### Recent Notes
```

---

## Skills

Skills are invoked as `/proj:<name>`. Most accept `$ARGUMENTS` for the primary input.

### Setup and project management

| Skill | Usage | Description |
|-------|-------|-------------|
| `init-plugin` | `/proj:init-plugin` | First-time setup wizard. Creates `~/.claude/proj.yaml`. Run this before anything else. |
| `init` | `/proj:init [name]` | Initialize tracking for a project. Asks for name, path, description, tags, git integration. Creates tracking directory, CLAUDE.md, and optional Todoist project. |
| `list-proj` | `/proj:list-proj` | List all non-archived tracked projects. |
| `switch` | `/proj:switch [name]` | Switch the globally active project. Displays the new project's context after switching. |
| `load` | `/proj:load [name]` | Load a project for this session only (session-local override, not persisted). Supports fuzzy name matching. |
| `archive` | `/proj:archive [name]` | Archive a completed project. Warns if open todos remain. |
| `explore` | `/proj:explore [path]` | Scan a codebase directory and write findings (tech stack, entry points, key dirs) to CLAUDE.md and NOTES.md. |
| `migrate-to-proj` | `/proj:migrate-to-proj [path]` | Import an existing project into proj tracking. Detects TODOS.md, todo.yaml, NOTES.md, and legacy `~/.project-tracker/` data. Creates a backup before migrating. |
| `migrate-ids` | `/proj:migrate-ids [--dry-run]` | Migrate todo IDs from legacy T-format (T001) to numeric dot-notation (1, 1.1). Backs up todos.yaml. |

### Status and reporting

| Skill | Usage | Description |
|-------|-------|-------------|
| `status` | `/proj:status` | Show project status, open todos grouped by in-progress/ready/blocked, and recent git activity. Syncs Todoist if auto_sync is enabled. |
| `update` | `/proj:update [note]` | Reconcile recent git commits with todos (suggest completions, link commits). Add new todos and notes. Rebuild CLAUDE.md. |
| `save` | `/proj:save` | Save session notes and context (decisions, todos, insights, open questions) to NOTES.md + session file. |
| `report` | `/proj:report` | Generate a comprehensive Markdown report: completed work, in-progress todos, pending todos, git history (30 days), and recent notes. Spawns parallel agents to gather data. |

### Todo management

| Skill | Usage | Description |
|-------|-------|-------------|
| `todo` | `/proj:todo <subcommand>` | All todo CRUD operations. See subcommands below. |

`/proj:todo` subcommands:

| Subcommand | Example | Description |
|------------|---------|-------------|
| `add <title>` | `/proj:todo add Fix login bug` | Add a new todo. Asks for priority, tags, blocked_by. Smart parent inference: if title starts with an existing todo ID, the new todo is created as a child. |
| `done <id>` | `/proj:todo done 2` | Mark a todo complete and archive it. |
| `update <id> [fields]` | `/proj:todo update 2 priority=high` | Update a todo's title, priority, tags, or notes. |
| `list [filter]` | `/proj:todo list ready` | List todos. Filters: `all`, `ready`, `blocked`. Default shows pending todos. |
| `tree` | `/proj:todo tree` | Show todos as a nested hierarchy. |
| `block <id> blocks <id>` | `/proj:todo block 1 blocks 2` | Set a blocking dependency. |
| `delete <id>` | `/proj:todo delete 3` | Delete a todo (asks for confirmation). |

### Workflow

| Skill | Usage | Description |
|-------|-------|-------------|
| `define` | `/proj:define <id>` | Gather requirements for a todo through iterative Q&A. Writes a structured `requirements.md` covering Goal, Acceptance Criteria, Out of Scope, Testing Strategy, and Q&A. |
| `research` | `/proj:research <id>` | Research implementation approaches for a todo. Explores the codebase (Read, Glob, Grep) and external sources (WebSearch, WebFetch). Writes `research.md` with approach options and a recommendation. Supports `all` or comma-separated IDs to spawn parallel research agents. |
| `decompose` | `/proj:decompose <id>` | Break a large todo into sub-todos based on its requirements and research. Proposes a multi-level breakdown, confirms with you, then creates the sub-todos with correct parent/child relationships and dependencies. |
| `execute` | `/proj:execute [id\|range]` | Implement one or more todos. Reads requirements and research before starting. For a range with independent todos, spawns parallel agents. Respects `blocked_by` ordering. Calls `todo_complete` on finish. |
| `prep-workflow` | `/proj:prep-workflow <id> [--iter N]` | Run define + research + decompose in sequence. Supports `--iter N` to repeat the cycle N times. Supports ranges and comma lists for batch processing. |
| `full-workflow` | `/proj:full-workflow <id> [--steps ...] [--from ...]` | Run the full workflow (define + research + decompose + execute) with interactive prompts between steps. Flags: `--steps define,execute` to select steps; `--from research` to start from a specific step; `--iter N` for prep iterations. Supports ranges for batch autonomous execution. |
| `quick-workflow` | `/proj:quick-workflow <description> [flags]` | Create a new todo and immediately run full-workflow on it. Accepts the same flags as `full-workflow` (`--steps`, `--from`, `--iter`, `--iter-as-needed`). If no description is given, prompts interactively. |

### Agent management

| Skill | Usage | Description |
|-------|-------|-------------|
| `agents-set` | `/proj:agents-set <step> <agent-name>` | Set a specialized agent override for a specific project step (research, decompose, define, execute). |
| `agents-list` | `/proj:agents-list` | List all agent overrides for the active project, showing defaults for unset steps. |
| `agents-remove` | `/proj:agents-remove <step>` | Remove an agent override and revert a step to its default agent. |
| `create-agent` | `/proj:create-agent [step] [name]` | Generic skill to create a custom Claude Code agent file for any workflow step. Asks which step, then guides through name and specialization to generate a properly configured `.claude/agents/<name>.md`. |
| `agents-create-define` | `/proj:agents-create-define [name]` | Create a custom agent file for the define (requirements) step. Uses define-specific tool defaults and system prompt structure. |
| `agents-create-research` | `/proj:agents-create-research [name]` | Create a custom agent file for the research step. Defaults to `claude-haiku-4-5-20251001` model and includes WebSearch/WebFetch tools. |
| `agents-create-decompose` | `/proj:agents-create-decompose [name]` | Create a custom agent file for the decompose step. Uses decompose-specific tool defaults and structured breakdown prompt format. |
| `agents-create-execute` | `/proj:agents-create-execute [name]` | Create a custom agent file for the execute step. Includes Edit, Write, Bash tools and enforces the check-executable guard in the generated agent. |

### Sync and permissions

| Skill | Usage | Description |
|-------|-------|-------------|
| `sync` | `/proj:sync` | Manually trigger a full bidirectional Todoist sync regardless of auto_sync setting. |
| `perms-sync` | `/proj:perms-sync` | Check whether settings.json allow rules match the active project config. Reports missing rules without auto-fixing. |

---

## MCP tools reference

All tools are exposed under the `proj` MCP server (tool names prefixed with `mcp__proj__`).

### Config

| Tool | Description |
|------|-------------|
| `config_load` | Check if the plugin is configured. Returns config summary or setup instructions. |
| `config_init` | Initialize configuration (called by `/proj:init-plugin`). |
| `config_update` | Update individual config settings (tracking_dir, projects_base_dir, priorities, Todoist, git, perms). |

### Projects

| Tool | Description |
|------|-------------|
| `proj_init` | Initialize tracking for a new project. |
| `proj_list` | List all projects (active and archived). |
| `proj_get` | Get full project metadata. Defaults to active project. |
| `proj_get_active` | Get the currently active project. |
| `proj_set_active` | Set the globally active project. |
| `proj_load_session` | Set the active project for this session only (not persisted). Fuzzy-matches project names. |
| `proj_update_meta` | Update project fields: description, status, priority, tags, target_date, git_enabled. |
| `proj_archive` | Archive a project (removes from active list). |
| `proj_add_repo` | Register an additional repository path against a project. |
| `proj_set_permissions` | Set per-project auto_grant override (null = use global config). |
| `proj_set_agent` | Set an agent override for a step (research, decompose, define, execute) in the active project. |
| `proj_get_agents` | Get all agent overrides for the active project, with defaults shown for unset steps. |
| `proj_remove_agent` | Remove an agent override for a step, reverting it to default. |
| `proj_explore_codebase` | Scan a directory and return structured findings: tech_stack, entry_points, key_dirs, config_files, file_types, file_tree, arch_note. No Bash required. |
| `proj_identify_batches` | Topological sort of todo IDs by dependency graph. Returns independent parallel batches with cycle detection. |
| `proj_migrate_ids` | Migrate all project todo IDs from T-prefix format to numeric dot-notation. Backs up todos.yaml. |

### Todos

| Tool | Description |
|------|-------------|
| `todo_add` | Add a new todo. Accepts title, priority, tags, blocked_by, parent, notes. |
| `todo_list` | List todos with optional status/tag/blocked filters and pagination. |
| `todo_list_all` | List todos including archived items (todos.yaml + archive.yaml). |
| `todo_get` | Get a single todo by ID (checks active and archived). |
| `todo_update` | Update a todo's fields: title, status, priority, tags, notes, todoist_task_id. |
| `todo_complete` | Mark a todo done and archive it. Parent todos require all children to be done first. |
| `todo_check_executable` | Guard for the `manual` tag. Returns todo JSON if executable; returns an error string if manual-tagged. Skills call this before executing. |
| `todo_delete` | Delete a todo and clean up all blocks/blocked_by/children references. |
| `todo_block` | Set blocking relationships between todos (bidirectional). |
| `todo_unblock` | Remove all blocking relationships from a todo. |
| `todo_ready` | List todos that are pending with no blockers. |
| `todo_add_child` | Add a child todo under a parent todo. |
| `todo_tree` | Return todos as a nested JSON tree. Prunes done nodes with no active descendants by default; pass `include_done=true` for full history. |
| `todo_set_content_flag` | Set `has_requirements` or `has_research` flags on a todo. Idempotent. |

### Content (per-todo requirements and research)

| Tool | Description |
|------|-------------|
| `content_set_requirements` | Write `requirements.md` for a todo. |
| `content_get_requirements` | Read `requirements.md` for a todo (truncates at max_chars with a path hint). |
| `content_set_research` | Write `research.md` for a todo. |
| `content_get_research` | Read `research.md` for a todo (truncates at max_chars with a path hint). |
| `proj_get_todo_context` | Return a todo's full context in one call: todo + parent + requirements + research. Replaces 3-4 sequential tool calls. |

### Notes and context

| Tool | Description |
|------|-------------|
| `notes_append` | Append a dated note to the active project's `NOTES.md`. |
| `claudemd_write` | Write or update `CLAUDE.md` in a project repo directory. |
| `claudemd_read` | Read `CLAUDE.md` from a project repo directory. |
| `ctx_session_start` | Build the session context string for the active project (used by the SessionStart hook). Auto-detects project from cwd. |
| `ctx_session_end` | Update the `last_updated` timestamp for the active project (used by the SessionEnd hook). |
| `ctx_detect_project` | Detect which tracked project matches the given cwd by comparing against registered repo paths. |

### Git

| Tool | Description |
|------|-------------|
| `git_detect_work` | Detect recent commits and branches across all project repos (uses `git log`). Returns empty results gracefully if git is not available or not enabled. |
| `git_link_todo` | Link a git branch and/or commit SHA to a todo. |
| `git_suggest_todos` | Suggest todo titles based on recent commit messages. |
| `proj_git_reconcile_todos` | Single-call git reconciliation: detects commits, branches, and generates structured todo suggestions. Replaces calling `git_detect_work` + `git_suggest_todos` separately. |

### Permissions

| Tool | Description |
|------|-------------|
| `proj_setup_permissions` | Grant all permission rules in one atomic settings.json write: Read+Edit path rules, scoped Bash investigation-tool rules, and MCP wildcard rules. Idempotent. |
| `proj_grant_tool_permissions` | Add scoped Bash allow rules for investigation tools (grep, find, ls, etc.) for a project's directories. Idempotent. |
| `proj_revoke_tool_permissions` | Remove scoped Bash investigation-tool allow rules added by `proj_grant_tool_permissions`. Does not touch other rules. Idempotent. |
| `proj_perms_sync` | Compare expected vs actual settings.json allow rules and report missing entries. Does not auto-fix. |

---

## Todo tags

Todos support a `tags` list. Tags are free-form strings except for `manual`, which has built-in behavior.

### The `manual` tag

Mark a todo as requiring human execution (cannot be automated):

```
/proj:todo add Deploy to production server
# then: /proj:todo update 5 tags=manual
```

Behavior when `manual` is set:

- **`/proj:execute <id>`** — shows a warning and stops: `"Todo <id> is tagged manual — execute it yourself, then run /proj:todo done <id>"`. Does not attempt implementation.
- **`/proj:full-workflow <id>`** — runs define/research/decompose normally but skips the execute step. Shows the warning in the summary.
- **Batch/range modes** — manual todos are skipped at execute with a warning in the aggregated summary.
- **MCP guard** — `todo_check_executable` returns an error string (not JSON) for manual-tagged todos. All execute-capable skills call this before implementing.
- **Display** — `[manual]` badge shown after priority in all todo list, tree, and decompose output.
- **Tags do not propagate** — child todos are independent; setting `manual` on a parent does not affect children.
- **No effect on Todoist sync** — the `manual` tag syncs to Todoist as a label like any other tag.

---

## Todo IDs

Todos use numeric dot-notation IDs:

- Root todos: `1`, `2`, `3`, ...
- Child todos: `1.1`, `1.2`, `2.1`, ...
- Nested children: `1.1.1`, `1.2.3`, ...

IDs are assigned automatically when todos are created. The `/proj:migrate-ids` skill converts legacy T-format IDs (`T001`, `T001.1`) to this format.

---

## Configuration

Configuration file: `~/.claude/proj.yaml` (created by `/proj:init-plugin`, permissions set to `0600`).

| Key | Default | Description |
|-----|---------|-------------|
| `tracking_dir` | `~/projects/tracking` | Root directory for all project tracking data |
| `projects_base_dir` | null | If set, `/proj:init` uses `<base>/<name>` as content path |
| `git_integration` | `true` | Enable git commit detection in `/proj:update` |
| `default_priority` | `medium` | Default priority for new todos (`low` / `medium` / `high`) |
| `perms_integration` | `false` | Enable automatic `settings.json` permission management |
| `worktree_integration` | `false` | Enable worktree plugin integration |
| `permissions.auto_grant` | `true` | Auto-add Read/Edit rules for project directories on `/proj:init` |
| `permissions.auto_allow_mcps` | `true` | Auto-add MCP wildcard allow rules on `/proj:init-plugin` |
| `permissions.investigation_tools` | `["grep", "find", "ls"]` | Bash tools granted scoped access via `proj_grant_tool_permissions` |
| `todoist.enabled` | `false` | Enable Todoist sync |
| `todoist.auto_sync` | `true` | Auto-sync on status/load/update commands when Todoist is enabled |

Update individual settings after initial setup:

```
# via MCP tool (in a Claude conversation)
mcp__proj__config_update(tracking_dir="~/work/tracking")
```

---

## Hooks

The plugin registers three lifecycle hooks in `hooks/hooks.json`. These are auto-discovered by Claude Code — they do not need to be referenced in `plugin.json`.

| Hook | Timing | What it does |
|------|--------|--------------|
| `SessionStart` | At the start of every Claude Code session | Calls `ctx_session_start` to auto-detect the active project from `$CLAUDE_PROJECT_DIR` and inject project context (status, in-progress todos, ready todos, recent notes) into the conversation. |
| `SessionEnd` | When the session ends | Calls `ctx_session_end` to update the `last_updated` timestamp on the active project's metadata. Runs asynchronously. |
| `PreCompact` | Before context window compaction | Calls `ctx_session_start` with `--compact` flag to re-inject a condensed project context so Claude retains awareness of the active project after compaction. |

All hooks call `server/cli.py` (a thin CLI wrapper that shares the MCP server's library). Hooks cannot call the MCP stdio server directly.

---

## Todoist sync

When `todoist.enabled: true`, the plugin can bidirectionally sync todos with a Todoist project.

Field mapping:

| Local field | Todoist field |
|-------------|---------------|
| `title` | `content` |
| `status` (`done`) | task completed |
| `priority` `high` | `p2` |
| `priority` `medium` | `p3` |
| `priority` `low` | `p4` |
| `notes` | `description` |
| `tags` | `labels` |

Sync runs automatically (when `auto_sync: true`) during `/proj:status`, `/proj:load`, and `/proj:update`. To trigger manually: `/proj:sync`.

The `/proj:sync` skill performs a full bidirectional sync:
1. Pull new and updated tasks from Todoist into local todos.
2. Push new and updated local todos to Todoist.
3. Detect tasks closed or deleted in Todoist and complete them locally.

The `todoist_task_id` field on each todo is the stable link between local and Todoist state.

---

## Trello sync

When `trello.enabled: true`, the plugin can bidirectionally sync **root-level todos** with a Trello board. Child/subtodos are never synced to Trello.

### Requirements

Register the `delorenj/mcp-server-trello` MCP server in your Claude Code MCP configuration (`~/.claude/mcp.json`):

```json
{
  "mcpServers": {
    "trello": {
      "command": "npx",
      "args": ["-y", "@delorenj/mcp-server-trello"],
      "env": {
        "TRELLO_API_KEY": "<your-api-key>",
        "TRELLO_TOKEN": "<your-token>"
      }
    }
  }
}
```

Get your API key and token from [https://trello.com/app-key](https://trello.com/app-key).

### Configuration

Enable Trello sync in the plugin config (`~/.claude/proj.yaml`):

```yaml
sync:
  trello:
    enabled: true
    mcp_server: "trello"         # MCP server name from mcp.json
    default_board_id: "abc123"   # Trello board ID (from board URL)
    list_mappings:
      created: "Backlog"         # List where new todos are created as cards
      done: "Done"               # List where completed todos are moved
    on_delete: "archive"         # "archive" or "delete"
```

Per-project overrides in `meta.yaml` (set via `proj_update_meta`):

```yaml
trello:
  enabled: true
  board_id: "abc123"
  list_mappings:
    created: "To Do"
    done: "Completed"
  on_delete: "archive"
```

### Action mapping

| Local action | Trello action |
|---|---|
| Todo created | Card added to configured "created" list |
| Todo completed | Card moved to configured "done" list |
| Todo title updated | Card name updated |
| Todo deleted | Card archived or deleted (per `on_delete`) |
| Todo due_date updated | Card due date updated |

| Trello event | Local action |
|---|---|
| Card moved to "done" list | Todo marked complete |
| Card renamed | Todo title updated |
| Card due date changed | `due_date` field updated |

### Running a sync

```
/proj:trello-sync
```

The `trello_card_id` field on each root todo is the stable link to its Trello card.

---

## Permissions integration

When `perms_integration: true` (requires the `perms` plugin), the `proj` plugin can automatically manage `~/.claude/settings.json` allow rules:

- **Path access** — `Read(//path/**)` and `Edit(//path/**)` rules for each project's repo directories and the tracking directory.
- **Bash investigation tools** — scoped rules like `Bash(grep //path/**)` for configured tools (grep, find, ls, etc.).
- **MCP wildcard rules** — `mcp__plugin_proj_proj__*` and similar entries so Claude never prompts for MCP tool permissions.

These rules are added atomically in a single `settings.json` write by `proj_setup_permissions`. They take effect immediately.

The `proj_perms_sync` tool (and `/proj:perms-sync` skill) checks whether all expected rules are present without modifying anything, making it safe to audit at any time.

---

## Version

Current version: **0.23.2**

See `CHANGELOG.md` for full release history.
