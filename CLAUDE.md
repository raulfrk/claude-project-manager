# claude-project-manager

**Status**: active | **Priority**: medium
**Tracking**: ~/projects/tracking/claude-project-manager

## Overview

Claude Code plugin marketplace for project management workflows. Eight plugins:
- `worktree` — git worktree management
- `proj` — full project lifecycle (todos, notes, git, Todoist/Trello/Jira sync); includes sandbox tools for managing `settings.json`
- `trello` — Trello MCP server (boards, cards, checklists, labels, comments, attachments)
- `jira` — Jira MCP server (issues, projects, epics, bulk operations)
- `router` — central MCP-to-MCP router (formerly `hooks`); schema-based param mapping, auto-registration, and recovery
- `todoist` — Todoist task and project management via REST API
- `confluence` — read-only Confluence (Cloud + Server/DC) search + page fetch via REST API
- `zoxide` — zoxide frecency database integration (boost, remove, query paths)

## Overhaul Plan

A comprehensive overhaul requirements document exists at:
`~/projects/tracking/claude-project-manager/overhaul-requirements.md` (7,565 lines)

It contains the full workflow map, user vision, quality assessment, gap analysis, 31 change proposals, and 35 implementation todos across 6 phases. **Read this file before starting any overhaul work.** Key architectural decisions:
- **Router plugin** (`plugins/router/`) — central MCP→MCP registry with schema-based param mapping, auto-registration, and recovery (formerly `plugins/hooks/`)
- **Proj is single source of truth** for settings.json — sandbox tools folded into proj MCP server; proj skills call these tools directly
- **Proj must not read worktree.yaml directly** — use worktree MCP tools
- **Remove deny functionality** from sandbox (denyWrite/denyRead)
- **Define skill rewrite** — free-form writing → probing Q&A → iterative rerun → quality gate

## Task Planning

Before starting any non-trivial task, evaluate whether it should be broken down into a todo list of smaller steps. Use task tracking to manage progress on multi-step work.

## Implementation Validation

After completing any implementation, always validate the result against the specs (requirements, research, or overhaul document) that were provided for that work. Check for gaps, deviations, and missing test coverage before marking a todo as done.

## Key Conventions

- Version must be bumped in both `plugin.json` and `marketplace.json` together
- `hooks/hooks.json` is auto-discovered — do NOT reference it in `plugin.json`
- Source files live in `plugins/<name>/server/server/` (inner `server/` is the Python package)
- Skills invoked as `/proj:<name>`, `/worktree:<name>`
- MCP allow rules: `mcp__<server>__*` wildcard format; use `sandbox_batch_setup(mcp_servers=[server_name])` via proj
- **`isolation: "worktree"` on Agent tool does NOT work** — agents run in the main repo, not the worktree. Always use explicit `wt_create` via the worktree MCP tool, then pass the worktree path in the agent prompt with: "ALL file edits and git operations MUST happen in this directory: `<path>`".

## Batch Completion Enforcement

**Always pass `todo_ids=[...]` to `mcp__plugin_proj_proj__todo_complete` when marking 2+ todos done in the same operation.** Never loop the tool with one `todo_id` per call. The batch path:
- Routes via `todo_ids` (list) parameter — atomic, deduplicated, saved under a single cross-process file lock.
- Fires ONE aggregated hook chain per integration (Todoist `todoist_complete_tasks`, Trello `trello_batch_archive_cards`, Jira `jira_update_issues`) instead of N sequential chains.
- Returns `_hooks.structured_errors` listing per-integration failures by id.

Single-todo completion: pass `todo_id="..."` (or `todo_ids=["..."]` — both work).

## E2E TUI Snapshot Flakes

**First-run flake after new panes added**: when a PR adds new TUI snapshots or widgets that alter pane composition, the first CI run often reports mismatches against stale goldens. These resolve on the second CI run (goldens auto-commit via `SNAPSHOT_CREATE_MISSING=1` in the generate step). **Do NOT fix rendering logic on the first failure** — rerun the workflow first. Only investigate if the second run still fails.

## Hook Architecture

**Dispatch flow** (full path): tool called → `_wrap_tool_fn` wrapper (injected by `enable_hook_dispatch`) → tool executes → result serialized to JSON (max 100KB) → POST to router server via Unix domain socket (resolved from `~/.claude/sockets/router`, prefix `/tmp/claude-cpm-router-<pid>.sock`) with `{tool: "router_fire_tool", params: {trigger_tool, source_result, depth: 0}}` → `router_fire_tool` loads registry, matches hooks by `trigger_tool` → evaluates each hook's `condition` against `~/.claude/proj.yaml` → POSTs to target server socket (from `hooks.yaml` `servers` map, e.g. `unix:///tmp/claude-cpm-todoist-<pid>.sock`) → target tool executes → result returned.

**Transport**: Unix domain sockets at `/tmp/claude-cpm-{plugin}-{pid}.sock` (default). Set `HOOK_TRANSPORT=tcp` env var to fall back to TCP on 127.0.0.1 (legacy ports below). Each plugin's `run_dual()` call passes the plugin name for socket path construction.

**Port assignments** (TCP fallback only, via `HOOK_TRANSPORT=tcp`):
| Plugin | Port |
|--------|-------|
| router | 19100 |
| proj | 19102 |
| worktree | 19103 |
| trello | 19104 |
| jira | 19105 |
| todoist | 19106 |
| zoxide | 19107 |
| confluence | 19108 |
| wiki | 19109 |

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
| `sync.trello.list_mappings.archived` | `sync.trello.list_mappings.archived` | trello |
| `project.trello_card_id` | `project.trello_card_id` (runtime) | trello |
| `todo.trello_card_id` | `todo.trello_card_id` (runtime) | trello |
| `sync.jira.enabled` | `sync.jira.enabled` | jira |
| `sync.jira.auto_sync` | `sync.jira.auto_sync` | jira |
| `project.jira_issue_key` | `project.jira_issue_key` (runtime) | jira |
| `todo.jira_issue_key` | `todo.jira_issue_key` (runtime) | jira |
| `sync.wiki.enabled` | `sync.wiki.enabled` | proj (wiki integration) |
| `sync.wiki.auto_sync` | `sync.wiki.auto_sync` | (reserved) |
| `sync.wiki.auto_ingest_sessions` | `sync.wiki.auto_ingest_sessions` | (reserved) |
| `sync.wiki.capture_notes_as_log` | `sync.wiki.capture_notes_as_log` | proj (wiki integration) |
| `sync.wiki.replace_notes_md` | `sync.wiki.replace_notes_md` | (reserved) |
| `sync.confluence.enabled` | `sync.confluence.enabled` | (reserved) |

Compound conditions are common, e.g. `"sync.todoist.enabled and sync.todoist.auto_sync and project.todoist_project_id"`. The authoritative list of valid condition paths is enforced by `policies/condition_paths.rego::valid_paths` — keep this table in sync when adding new paths.

**Blocking vs non-blocking**: the dispatcher always awaits the `router_fire_tool` HTTP response (30s timeout). Inside `router_fire_tool`, blocking hooks (`blocking: true`) are awaited concurrently via `asyncio.gather`; non-blocking hooks (`blocking: false`, the default) are dispatched in background daemon threads and return immediately.

**Depth tracking**: `max_depth=3` (configurable in `hooks.yaml` `settings.max_depth`). Prevents runaway cascades when hooks trigger tools that trigger hooks. The `depth` param is passed through the dispatch chain and checked at the start of `router_fire_tool`.

**Verification hooks**: hooks with `verification: true` fire in Phase 2 after all primary hooks complete. They receive an enriched source containing `hook_results` from Phase 1 blocking hooks. Verification hooks are always blocking and do not increment depth.

## Config Naming Conventions

- **Field names**: `underscore_case` (`tracking_dir`, `auto_sync`, `default_priority`)
- **Nested section names**: lowercase (`sync.todoist`, `permissions`, `archive`)
- **Integration flags**: `underscore_case` (`sandbox_integration`, `worktree_integration`)
- **MCP tool names**: `mcp__plugin_<name>_<name>__<tool_name>` (internal plugins), `mcp__<server>__<tool-name>` (external MCP servers)
- **Git flush messages**: `"Action: subject"` pattern (`"Define: {todo-id}"`, `"Sync: Jira"`, `"Save: session"`)

## Wiki Plugin Config Flags

Wiki spans 4 config files. Full reference:

**`~/.claude/wiki.yaml`** (wiki runtime config — owned by wiki plugin):
- `enabled` — master switch. Wiki MCP tools no-op/return error when false.
- `wiki_dir` — wiki root (default `~/.claude/wiki`).
- `reingest_cooldown_hours` — dedup window for `/wiki:ingest <source>` re-runs (default 24).
- `bootstrap_pending` — flag set by installer wizard; prompts user on next session to run `/wiki:bootstrap`.
- `session_ingest.section_map` — map of session-file headings → wiki categories for `/proj:save` auto-ingest.

**`~/.claude/wiki/config.yaml`** (wiki-local schema + lint config):
- `schema_version: 1` — migration marker.
- `profile` — one of `software`/`personal`/`research`/`minimal`/`custom`.
- `categories` — required when `profile: custom`; list of category dir names.
- `required_frontmatter` — list of page frontmatter fields enforced by `wiki_lint_schema`.
- `lint.stale_after_days` — `wiki_lint_stale` threshold (default 90).
- `lint.orphan_min_page_count` — skip orphan lint when wiki has fewer pages (default 3).

**`~/.claude/proj.yaml::sync.wiki.*`** (proj→wiki integration gating):
- `enabled` — master switch for proj→wiki integrations.
- `auto_sync` — currently informational; reserved for future use.
- `auto_ingest_sessions` — `/proj:save` spawns wiki ingest subagent on session file.
- `capture_notes_as_log` — router hook `notes_append` → `wiki_log_append` fires.
- `replace_notes_md` — (future) redirect `notes_append` to wiki entirely.
- `bootstrap_docs` — per-project doc paths included by `/wiki:bootstrap` proj-aware mode.

**`~/.claude/proj-session.yaml`** (proj session state — owned by proj, read by wiki):
- Schema v2 — pid-keyed so concurrent Claude Code sessions don't clobber each other.
  ```yaml
  schema_version: 2
  active_by_claude_pid:
    "<claude-code-pid>":
      active: <project-name>
      last_seen: <iso8601>
  ```
- Each MCP subprocess resolves its slot by walking its ppid chain via `psutil`
  to find its Claude Code ancestor. Matcher regex configurable via env var
  `CPM_CLAUDE_CODE_CMDLINE_MATCHER` (default: `(?:^|/)claude(?:\s|$)`).
- Dead pid entries are garbage-collected on write. v1 files with a flat
  `active:` scalar auto-migrate into the current session's slot on first read.
- Cleared on `/proj:archive` (current session only) or explicit clear.
- Shared helper: `plugins/_shared/session_key/` (both proj and wiki import from here).

## Skill Files

New skills go in `plugins/<name>/skills/<skill-name>/SKILL.md`. Add new skills to the README skill reference table and the "Skills by category" list.

### SKILL.md Compression (Caveman Ultra)

All SKILL.md files are written in **caveman ultra** format to minimize token usage. When creating or editing SKILL.md files, follow these rules:

**Drop**: articles (a/an/the), filler (just/really/basically/actually/simply), hedging, conjunctions when meaning clear, "you should"/"make sure to"/"remember to"/"note that" — state action directly.

**Abbreviate**: fn/impl/config/req/res/DB/auth/msg/param/arg/deps/env/dir/repo/cmd/exec/init/sync/info/orig/desc/prev/cur/num/val/err/ctx/ref/opt/spec/max/min/avg/diff/fmt/ver

**Syntax**: fragments > sentences. Arrows for causality (X → Y). Semicolons merge short items. "If X: do Y" not "If the user does X, then you should do Y". Conditional chains: "A → X; B → Y; C → Z".

**Preserve exactly**: inline code, URLs, file paths, MCP tool names, heading structure, table structure, code blocks.

**Dedup**: repeated patterns (e.g. "After presenting:" + prompt) → define once, ref later. review/SKILL.md refs explore/SKILL.md Steps 1-5 instead of duplicating.

**Output directive**: every SKILL.md starts with (after frontmatter):
`> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.`

**Batch compression tool**: `/caveman:compress <filepath>` — uses Claude to compress + deterministic regex post-processing. Protected block extraction keeps frontmatter/code blocks byte-identical. Script at `~/.claude/plugins/cache/caveman/caveman/92f892f2b97/caveman-compress/`.

### context/agent Frontmatter Criteria

Add `context: fork` and `agent: general-purpose` to skills that can run autonomously without user interaction during execution. Criteria:
- Self-contained op (list, sync, status display)
- No interactive Q&A during exec
- No plan mode approval mid-exec
- Examples: hooks-*, status, todo, todoist-sync, trello-sync, jira-sync, jira-sync-trello
- NOT for: interactive skills (init, load) or sub-skills

<!-- claude-project-manager:start -->
## Claude Project Manager Rules

IMPORTANT: These rules take priority over all other instructions.

- Use parallel `Agent()` calls with `run_in_background=true` for concurrent work. Agents auto-terminate on completion — no cleanup needed.
- ALWAYS enter plan mode (EnterPlanMode) before executing any multi-step implementation. Get user approval before writing code.
- **Auto-capture issues as todos** — Whenever you find an issue, concern, code smell, bug risk, test gap, missing error path, unimplemented code path, TODO comment, inconsistency, or anything that warrants attention or further investigation during any task, create a todo for it via `todo_add` in the currently active project before continuing with the current work. Tag the todo with `auto-added`. Set priority based on your judgment of severity (high/medium/low). In the notes field, write: "Auto-added by Claude during <brief context>. Needs human verification — may not be a real issue." Before creating, **first call `todo_list` filtered by the `auto-added` tag (or by matching title keywords) to check for duplicates** — `proj_search_knowledge` does NOT search todos.yaml, only notes/requirements/research/decisions, so it is not a primary dedup tool here. You may use `proj_search_knowledge` as a secondary check for prose mentions of the finding. Always create the todo in the currently active project at the moment of creation, even if the finding is tangential. **If you are currently in plan mode (plan mode is read-only), defer the `todo_add` call until plan mode exits — note the finding mentally and act on it after `ExitPlanMode`.** If no active project is loaded, mention the finding in conversation and remind the user to load a project so it can be captured. Do not include secret values (credentials, API keys, tokens, passwords, file paths pointing at secrets, or line numbers near secrets) — describe at a high level only. Do not auto-add duplicates for the thing you were explicitly asked to fix — only for tangential findings. If the user says to ignore a finding, do not auto-add it.
- **Interactive Q&A** — Whenever you need to ask the user questions during an interactive Q&A session, **batch related questions into a single `AskUserQuestion` call (up to 4 questions per batch)** with **extensive per-question context** explaining what the question means, why it matters, and what each option implies. Use **multiple-choice options** whenever the answer is enumerable. Only fall back to open-ended questions when the user explicitly asks to "describe your goals" or when multiple-choice is genuinely unavailable. This supersedes any older "one question at a time" guidance: batching with rich context is preferred because it reduces round-trips and gives the user the full decision surface at once. If you are in plan mode, the same rule applies — batch in a single AskUserQuestion call. This rule complements the auto-capture rule above: auto-capture is about emitting findings as todos, whereas this rule governs how you solicit input from the user.
- **Patch-style editing for notes and requirements** — When updating todo notes, prefer `todo_notes_append` (add content) or `todo_notes_patch` (find/replace) over `todo_update(notes=...)`. When updating requirements or research files, prefer `content_patch_requirements`/`content_patch_research` over `content_set_requirements`/`content_set_research`. Only use full-content replacement for complete rewrites or when the patch target is ambiguous. This reduces payload size by 95%+ on large notes/requirements.
- **`isolation: "worktree"` does NOT work** — The Agent tool parameter `isolation: "worktree"` does not isolate agents into separate worktrees. Agents run in the main repo on the current branch. Always use explicit `wt_create` via the worktree MCP tool to create worktrees, then pass the path in the agent prompt: "ALL file edits and git operations MUST happen in this directory: `<path>`".
<!-- claude-project-manager:end -->
