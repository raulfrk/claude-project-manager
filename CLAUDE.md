# claude-project-manager

**Status**: active | **Priority**: medium
**Tracking**: ~/projects/tracking/claude-project-manager

## Overview

Claude Code plugin marketplace for project management workflows. Nine plugins:
- `sandbox` — manage sandbox-mode `settings.json` (write paths, MCP allow rules, network domains, deny rules)
- `worktree` — git worktree management
- `proj` — full project lifecycle (todos, notes, git, Todoist/Trello/Jira sync)
- `trello` — Trello MCP server (boards, cards, checklists, labels, comments, attachments)
- `jira` — Jira MCP server (issues, projects, epics, bulk operations)
- `router` — central MCP-to-MCP router (formerly `hooks`); schema-based param mapping, auto-registration, and recovery
- `todoist` — Todoist task and project management via REST API
- `zoxide` — zoxide frecency database integration (boost, remove, query paths)
- `analyse` — guided code review skill (walk through features, explain code, create todos)

## Overhaul Plan

A comprehensive overhaul requirements document exists at:
`~/projects/tracking/claude-project-manager/overhaul-requirements.md` (7,565 lines)

It contains the full workflow map, user vision, quality assessment, gap analysis, 31 change proposals, and 35 implementation todos across 6 phases. **Read this file before starting any overhaul work.** Key architectural decisions:
- **Router plugin** (`plugins/router/`) — central MCP→MCP registry with schema-based param mapping, auto-registration, and recovery (formerly `plugins/hooks/`)
- **Sandbox is single source of truth** for settings.json — proj must never write settings files directly
- **Proj must not read worktree.yaml directly** — use worktree MCP tools
- **Remove deny functionality** from sandbox (denyWrite/denyRead)
- **Define skill rewrite** — free-form writing → probing Q&A → iterative rerun → quality gate
- **Default --iter 5** for `/proj:run`

## Task Planning

Before starting any non-trivial task, evaluate whether it should be broken down into a todo list of smaller steps. Use task tracking to manage progress on multi-step work.

## Branch layout and caveman experiment

This repository uses three long-lived branches:

- **`main`** — release branch.
- **`dev`** — integration branch for all non-experimental work. Pull requests target `dev`; releases merge `dev` → `main`.
- **`dev-caveman`** — permanent experimental sidecar for the caveman-mode adoption work (todo 519). Branches off `dev`. **Never merges to `dev` or `main`.**

### Caveman-only content

The caveman experiment adds constraints and output conventions that only apply when the assistant is running against the `dev-caveman` branch. Specifically, the following marker strings **must not appear** on `main` or `dev`:

- `Caveman-Aware Output`
- `CPM-CAVEMAN-BACKUP`
- `Caveman Mode Precedence`
- `_CAVEMAN_APPEND`
- `# cpm:caveman`

Two independent guards enforce this:

1. **CI** — `.github/workflows/caveman-guard.yml` runs on every push and PR targeting `main`/`dev`. Any diff containing a marker fails the build.
2. **Pre-commit** — `.pre-commit-hooks/caveman-guard.sh` wired into `.pre-commit-config.yaml` rejects local commits on `main`/`dev` that add any marker. It is a no-op on every other branch, including `dev-caveman`.

If you need to do caveman work, check out `dev-caveman`, do the work there, and leave it there. Do not rebase `dev-caveman` onto `dev` with a merge.

### Branch switching and global `~/.claude/CLAUDE.md`

The global `~/.claude/CLAUDE.md` is **not** a tracked file and is shared across every repository the installer has touched. When switching branches between `dev` and `dev-caveman`, its managed section must be updated to match the active branch. This happens exclusively inside the installer wizard sync step — **not** from a SessionStart hook and **not** from a git post-checkout hook.

**After every branch switch between `dev` and `dev-caveman`, run `claude-installer update`** to refresh `~/.claude/CLAUDE.md`. The installer backs up the previous managed content to `~/.claude/CLAUDE.md.pre-caveman` with a `# CPM-CAVEMAN-BACKUP v1 <timestamp>` magic header and restores it atomically on switch-back. User-added content outside the managed markers is preserved via a non-managed-region diff.

Full design and rationale in `tracking/claude-project-manager/todos/519/requirements.md`.

## Implementation Validation

After completing any implementation, always validate the result against the specs (requirements, research, or overhaul document) that were provided for that work. Check for gaps, deviations, and missing test coverage before marking a todo as done.

## Key Conventions

- Version must be bumped in both `plugin.json` and `marketplace.json` together
- `hooks/hooks.json` is auto-discovered — do NOT reference it in `plugin.json`
- Source files live in `plugins/<name>/server/server/` (inner `server/` is the Python package)
- Skills invoked as `/proj:<name>`, `/worktree:<name>`
- MCP allow rules: `mcp__<server>__*` wildcard format; use `sandbox_add_mcp_allow(server_name)`
- **Worktree isolation is ON by default** for `/proj:run` at all quality levels except `--paranoid`. Pass `--no-worktree` to opt out. Default `team_mode.max_agents` is **30** (recommended cap: 10 for CPU-bound / API-rate-limited workloads). Team mode triggers at **2+** non-manual descendants.

## Batch Completion Enforcement

**Always use `mcp__proj__todo_batch_complete` when marking 2 or more todos done in the same operation.** Never loop `todo_complete` across multiple ids. The batch tool:
- Validates, deduplicates, and atomically saves all ids under a cross-process file lock (`threading.Lock` + `fcntl.flock`).
- Fires ONE aggregated hook chain per integration (Todoist `todoist_complete_tasks`, Trello `trello_batch_archive_cards`, Jira `jira_bulk_update_issues`) instead of N sequential chains.
- Returns a `_hooks.structured_errors` sidecar that identifies which integration/ids failed per hook.

Single-todo completion continues to use `mcp__proj__todo_complete`. Skills that mark todos done in a loop (execute, run, quick) must collect ids first and call the batch tool at the end of the loop.

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

## E2E TUI Snapshot Flakes

**First-run flake after new panes added**: when a PR adds new TUI snapshots or widgets that alter pane composition, the first CI run often reports mismatches against stale goldens. These resolve on the second CI run (goldens auto-commit via `SNAPSHOT_CREATE_MISSING=1` in the generate step). **Do NOT fix rendering logic on the first failure** — rerun the workflow first. Only investigate if the second run still fails.

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

## Hook Architecture

**Dispatch flow** (full path): tool called → `_wrap_tool_fn` wrapper (injected by `enable_hook_dispatch`) → tool executes → result serialized to JSON (max 100KB) → POST to router server via Unix domain socket (resolved from `~/.claude/sockets/router`, prefix `/tmp/claude-cpm-router-<pid>.sock`) with `{tool: "router_fire_tool", params: {trigger_tool, source_result, depth: 0}}` → `router_fire_tool` loads registry, matches hooks by `trigger_tool` → evaluates each hook's `condition` against `~/.claude/proj.yaml` → POSTs to target server socket (from `hooks.yaml` `servers` map, e.g. `unix:///tmp/claude-cpm-todoist-<pid>.sock`) → target tool executes → result returned.

**Transport**: Unix domain sockets at `/tmp/claude-cpm-{plugin}-{pid}.sock` (default). Set `HOOK_TRANSPORT=tcp` env var to fall back to TCP on 127.0.0.1 (legacy ports below). Each plugin's `run_dual()` call passes the plugin name for socket path construction.

**Port assignments** (TCP fallback only, via `HOOK_TRANSPORT=tcp`):
| Plugin | Port |
|--------|-------|
| router | 19100 |
| sandbox | 19101 |
| proj | 19102 |
| worktree | 19103 |
| trello | 19104 |
| jira | 19105 |
| todoist | 19106 |
| zoxide | 19107 |

**`enable_hook_dispatch()`** (source: `plugins/_shared/hook_dispatch/dispatch.py`): called in each plugin's `main.py` **before** any `register()` calls. Monkey-patches `mcp.tool()` on the FastMCP instance so all subsequently registered tools get a post-execution wrapper. The patch intercepts both `@mcp.tool` (no parens) and `@mcp.tool(name="x", ...)` decorator forms. After the original tool function returns, the wrapper calls `_dispatch_hook()` which serializes the result and POSTs to the router server. If the router server is unreachable (ConnectError/TimeoutException), the tool returns normally with a warning logged. Tool exceptions propagate without dispatch.

Usage pattern in each plugin's `main.py`:
```python
from hook_dispatch import enable_hook_dispatch
mcp = FastMCP("plugin_name")
enable_hook_dispatch(mcp, exclude={"meta_tool_1", "meta_tool_2"})
# register() calls come after — they use the patched mcp.tool()
```

The `exclude` parameter prevents dispatch for meta-tools that should not trigger hooks. The router plugin excludes: `router_fire_tool`, `router_list_tool`, `router_recover_tool`.

**Condition evaluation**: `hooks.yaml` conditions are evaluated against `~/.claude/proj.yaml` at fire time. Dot-path resolution walks nested YAML keys. Supports `and`/`or` operators (`and` binds tighter) and `!` negation. Missing keys or missing config file evaluate to `False`.

Condition-to-`proj.yaml` path mapping (from `default-hooks.yaml` files):

| Condition | `proj.yaml` path | Used by |
|-----------|------------------|---------|
| `sandbox_integration` | `sandbox_integration` (top-level bool) | sandbox, proj, worktree |
| `zoxide_integration` | `zoxide_integration` (top-level bool) | worktree, zoxide |
| `git_tracking.enabled` | `git_tracking.enabled` | proj |
| `sync.todoist.enabled` | `sync.todoist.enabled` | todoist |
| `sync.todoist.auto_sync` | `sync.todoist.auto_sync` | todoist |
| `todo.todoist_task_id` | `todo.todoist_task_id` (runtime) | todoist |
| `project.todoist_project_id` | `project.todoist_project_id` (runtime) | todoist |
| `sync.trello.enabled` | `sync.trello.enabled` | trello |
| `sync.trello.auto_sync` | `sync.trello.auto_sync` | trello |
| `project.trello_card_id` | `project.trello_card_id` (runtime) | trello |

Compound conditions are common, e.g. `"sync.todoist.enabled and sync.todoist.auto_sync and project.todoist_project_id"`.

**Blocking vs non-blocking**: the dispatcher always awaits the `router_fire_tool` HTTP response (30s timeout). Inside `router_fire_tool`, blocking hooks (`blocking: true`) are awaited concurrently via `asyncio.gather`; non-blocking hooks (`blocking: false`, the default) are dispatched in background daemon threads and return immediately.

**Depth tracking**: `max_depth=3` (configurable in `hooks.yaml` `settings.max_depth`). Prevents runaway cascades when hooks trigger tools that trigger hooks. The `depth` param is passed through the dispatch chain and checked at the start of `router_fire_tool`.

**Verification hooks**: hooks with `verification: true` fire in Phase 2 after all primary hooks complete. They receive an enriched source containing `hook_results` from Phase 1 blocking hooks. Verification hooks are always blocking and do not increment depth.

## Config Naming Conventions

- **Field names**: `underscore_case` (`tracking_dir`, `auto_sync`, `default_priority`)
- **Nested section names**: lowercase (`sync.todoist`, `permissions`, `archive`)
- **Integration flags**: `underscore_case` (`sandbox_integration`, `worktree_integration`)
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
