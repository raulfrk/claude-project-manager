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
- **Full workflow** — structured skills for defining requirements + researching approaches, decomposing into sub-todos, and executing them — individually or in parallel batches.
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
    research.md      # implementation research (from /proj:define)
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

Each project's content directory can have a `CLAUDE.md` that gives Claude context about the codebase. The `/proj:init` skill creates one automatically; `/proj:save` and `/proj:execute` keep it current.

### Active project

One project is "active" at a time. The active project is used as the default target for all todo and note operations. Use `/proj:load` to set a session-only override without changing the global active project.

### Session context injection

At session start, the `SessionStart` hook calls `ctx_session_start`, which auto-detects the active project from `$CLAUDE_PROJECT_DIR` and injects a context block into the conversation.

---

## Skills

Skills are invoked as `/proj:<name>`. Most accept `$ARGUMENTS` for the primary input.

### Setup and project management

| Skill | Usage | Description |
|-------|-------|-------------|
| `init-plugin` | `/proj:init-plugin` | First-time setup wizard. Creates `~/.claude/proj.yaml`. |
| `init` | `/proj:init [name]` | Initialize tracking for a project. Creates tracking directory, CLAUDE.md, and optional Todoist project. |
| `list-proj` | `/proj:list-proj` | List all non-archived tracked projects. |
| `switch` | `/proj:switch [name]` | Switch the globally active project. |
| `load` | `/proj:load [name]` | Load a project for this session only. Supports fuzzy matching. |
| `archive` | `/proj:archive [name]` | Archive a completed project. Asks if project is purgeable. |
| `purge` | `/proj:purge` | Purge archived projects older than `archive.purge_after_days`. |

### Status and notes

| Skill | Usage | Description |
|-------|-------|-------------|
| `status` | `/proj:status` | Show project status, open todos, and recent git activity. Syncs Todoist if auto_sync is enabled. |
| `save` | `/proj:save` | Save session notes (decisions, todos, insights, open questions) to session file + NOTES.md. Reconciles git activity with todos. |

### Todo management

| Skill | Usage | Description |
|-------|-------|-------------|
| `todo` | `/proj:todo <subcommand>` | All todo CRUD: add, done, update, list, tree, block, delete. |

### Workflow

| Skill | Usage | Description |
|-------|-------|-------------|
| `define` | `/proj:define <id>` | Gather requirements through Q&A and research implementation approaches. Writes `requirements.md` and `research.md`. Uses plan mode to outline before writing. |
| `decompose` | `/proj:decompose <id>` | Break a large todo into sub-todos with dependency analysis. Detects shared-file conflicts for safe parallel execution. |
| `execute` | `/proj:execute [id\|range]` | Implement todos. Uses plan mode for review. For ranges, plans sequentially then executes in parallel. |
| `run` | `/proj:run <id> [--steps ...] [--from ...]` | Full workflow: define → decompose → execute. Interactive prompts between steps. Supports `--steps`, `--from`, `--iter N`. Ranges run autonomously in batches. |
| `quick` | `/proj:quick [description]` | Quick-start: creates a new project (if none active) or a new todo (if active project exists), then launches `/proj:run`. |

### Sync

| Skill | Usage | Description |
|-------|-------|-------------|
| `sync` | `/proj:sync` | Manually trigger bidirectional Todoist sync. |
| `trello-sync` | `/proj:trello-sync` | Sync root-level todos with a Trello board. |

### Repository management

| Skill | Usage | Description |
|-------|-------|-------------|
| `add-repo` | `/proj:add-repo <path>` | Register an additional repository path for a project. |
| `remove-repo` | `/proj:remove-repo <label>` | Unregister a repository by label. |

---

## MCP tools reference

All tools are exposed under the `proj` MCP server (tool names prefixed with `mcp__proj__`).

### Config

| Tool | Description |
|------|-------------|
| `config_load` | Check if the plugin is configured. Returns config summary or setup instructions. |
| `config_init` | Initialize configuration (called by `/proj:init-plugin`). |
| `config_update` | Update individual config settings. |

### Projects

| Tool | Description |
|------|-------------|
| `proj_init` | Initialize tracking for a new project. |
| `proj_list` | List all projects (active and archived). |
| `proj_get` | Get full project metadata. |
| `proj_get_active` | Get the currently active project. |
| `proj_load_session` | Set the active project for this session (not persisted). |
| `proj_update_meta` | Update project fields. |
| `proj_archive` | Archive a project. Sets archive_date and purgeable flag. |
| `proj_purge_archive` | List or execute purge of archived projects older than purge_after_days. |
| `proj_add_repo` | Register a repository path. |
| `proj_remove_repo` | Unregister a repository. |
| `proj_set_permissions` | Set per-project auto_grant override. |
| `proj_explore_codebase` | Scan a directory and return structured findings. |
| `proj_identify_batches` | Topological sort of todo IDs by dependency graph. |
| `proj_migrate_ids` | Migrate todo IDs from T-format to numeric dot-notation. |
| `proj_migrate_dirs` | Migrate single-dir projects to multi-dir format. |
| `proj_find_archived_by_title` | Fuzzy-match archived todos by title. |

### Todos

| Tool | Description |
|------|-------------|
| `todo_add` | Add a new todo. |
| `todo_list` | List todos with filters and pagination. |
| `todo_list_all` | List todos including archived items. |
| `todo_get` | Get a single todo by ID. |
| `todo_update` | Update a todo's fields. |
| `todo_complete` | Mark a todo done and archive it. |
| `todo_check_executable` | Guard for the `manual` tag. |
| `todo_delete` | Delete a todo. |
| `todo_block` | Set blocking relationships. |
| `todo_unblock` | Remove blocking relationships. |
| `todo_ready` | List pending unblocked todos. |
| `todo_add_child` | Add a child todo. |
| `todo_tree` | Return todos as a nested JSON tree. |
| `todo_set_content_flag` | Set `has_requirements` or `has_research` flags. |

### Content

| Tool | Description |
|------|-------------|
| `content_set_requirements` | Write `requirements.md` for a todo. |
| `content_get_requirements` | Read `requirements.md` for a todo. |
| `content_set_research` | Write `research.md` for a todo. |
| `content_get_research` | Read `research.md` for a todo. |
| `proj_get_todo_context` | Get todo + parent + requirements + research in one call. |

### Notes and context

| Tool | Description |
|------|-------------|
| `notes_append` | Append a dated note to NOTES.md. |
| `claudemd_write` | Write CLAUDE.md in a project repo. |
| `claudemd_read` | Read CLAUDE.md from a project repo. |
| `ctx_session_start` | Build session context string (SessionStart hook). |
| `ctx_session_end` | Update last_updated timestamp (SessionEnd hook). |
| `ctx_detect_project` | Detect project from cwd. |

### Git

| Tool | Description |
|------|-------------|
| `git_detect_work` | Detect recent commits and branches. |
| `git_link_todo` | Link a git branch/commit to a todo. |
| `git_suggest_todos` | Suggest todo titles from commit messages. |
| `proj_git_reconcile_todos` | Combined git detection + todo suggestions. |

### Permissions

| Tool | Description |
|------|-------------|
| `proj_setup_permissions` | Grant all permission rules atomically. |
| `proj_grant_tool_permissions` | Add scoped Bash investigation-tool rules. |
| `proj_revoke_tool_permissions` | Remove scoped Bash investigation-tool rules. |
| `proj_perms_sync` | Compare expected vs actual permission rules. |

---

## Todo tags

Todos support a `tags` list. Tags are free-form strings except for `manual`, which has built-in behavior.

### The `manual` tag

Mark a todo as requiring human execution:

- **`/proj:execute <id>`** — shows a warning and stops.
- **`/proj:run <id>`** — runs define/decompose normally but skips execute.
- **Batch modes** — manual todos are skipped at execute with a warning.
- **MCP guard** — `todo_check_executable` returns an error for manual-tagged todos.
- **Display** — `[manual]` badge shown after priority.
- **Tags do not propagate** — child todos are independent.

---

## Todo IDs

Todos use numeric dot-notation IDs: `1`, `1.1`, `1.2.3`. IDs are assigned automatically.

---

## Configuration

Configuration file: `~/.claude/proj.yaml` (created by `/proj:init-plugin`).

| Key | Default | Description |
|-----|---------|-------------|
| `tracking_dir` | `~/projects/tracking` | Root directory for all project tracking data |
| `projects_base_dir` | null | If set, `/proj:init` uses `<base>/<name>` as content path |
| `git_integration` | `true` | Enable git commit detection |
| `default_priority` | `medium` | Default priority for new todos |
| `perms_integration` | `false` | Enable automatic permission management |
| `worktree_integration` | `false` | Enable worktree plugin integration |
| `permissions.auto_grant` | `true` | Auto-add Read/Edit rules |
| `permissions.auto_allow_mcps` | `true` | Auto-add MCP wildcard rules |
| `todoist.enabled` | `false` | Enable Todoist sync |
| `todoist.auto_sync` | `true` | Auto-sync on status/load commands |

---

## Hooks

Three lifecycle hooks (auto-discovered from `hooks/hooks.json`):

| Hook | What it does |
|------|--------------|
| `SessionStart` | Auto-detect active project, inject context (status, todos, notes). |
| `SessionEnd` | Update `last_updated` timestamp. |
| `PreCompact` | Re-inject condensed context before compaction. |

---

## Todoist sync

When `todoist.enabled: true`, bidirectional sync with a Todoist project.

| Local field | Todoist field |
|-------------|---------------|
| `title` | `content` |
| `status` (`done`) | task completed |
| `priority` `high` | `p2` |
| `priority` `medium` | `p3` |
| `priority` `low` | `p4` |
| `notes` | `description` |
| `tags` | `labels` |

Sync runs automatically during `/proj:status` and `/proj:load` when `auto_sync: true`. Manual trigger: `/proj:sync`.

---

## Trello sync

When `trello.enabled: true`, bidirectional sync of root-level todos with a Trello board. See configuration in `~/.claude/proj.yaml`. Manual trigger: `/proj:trello-sync`.

---

## Permissions integration

When `perms_integration: true` (requires the `perms` plugin), automatic management of `~/.claude/settings.json` allow rules for path access, Bash investigation tools, and MCP wildcards.

---

## Version

Current version: **0.51.0**

See `CHANGELOG.md` for full release history.
