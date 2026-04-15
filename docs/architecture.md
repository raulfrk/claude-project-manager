# Architecture

This document describes the system architecture of claude-project-manager, a Claude Code plugin marketplace for project management workflows.

---

## System Overview

The marketplace contains 9 plugins that work independently or together:

| Plugin | Version | Category | Type | Description |
|--------|---------|----------|------|-------------|
| **sandbox** | 1.0.0 | utilities | MCP server | Manage sandbox-mode `settings.json` (write paths, MCP/Skill allow rules, network domains, deny rules) |
| **worktree** | 3.0.0 | utilities | MCP server + skills | Git worktree management from registered base repositories |
| **proj** | 4.0.0 | productivity | MCP server + skills + hooks | Full project lifecycle (todos, notes, git, Todoist/Trello/Jira sync) |
| **router** | 2.1.0 | utilities | MCP server + skills | Central MCP-to-MCP router with condition evaluation, auto-registration, and recovery |
| **todoist** | 2.0.0 | integrations | MCP server | Todoist task and project management via REST API |
| **trello** | 3.0.0 | integrations | MCP server | Trello board, card, checklist, label, comment, and attachment management via REST API |
| **jira** | 3.0.0 | integrations | MCP server | Read-only Jira Server issue and project access via REST API |
| **zoxide** | 2.0.0 | utilities | MCP server | Zoxide frecency database integration (boost, remove, query paths) |
### Marketplace Structure

```
claude-project-manager/
  .claude-plugin/
    marketplace.json          # Plugin registry with versions, descriptions, keywords
  plugins/
    _shared/                  # Shared dependency: claude-hook-transport
    sandbox/                  # MCP server plugin
    worktree/                 # MCP server + skills plugin
    proj/                     # MCP server + skills plugin
    router/                   # MCP server + skills plugin (MCP-to-MCP hook router; formerly `hooks`)
    todoist/                  # MCP server plugin
    trello/                   # MCP server plugin
    jira/                     # MCP server plugin
    zoxide/                   # MCP server plugin
  docs/                       # Documentation
```

Plugins are installed individually via `/plugin install raulfrk/claude-project-manager:<name>`.

---

## Plugin Structure

Each plugin follows a consistent directory layout:

```
plugins/<name>/
  .claude-plugin/
    plugin.json               # Plugin metadata (name, version, description, mcpServers ref)
  .mcp.json                   # MCP server configuration (stdio command)
  server/
    pyproject.toml            # Python package config, dependencies, tool settings
    uv.lock                   # Locked dependencies
    server/                   # Inner Python package
      __init__.py
      main.py                 # FastMCP entry point, hook dispatch setup, tool registration
      lib/                    # Shared library code (models, storage, config)
      tools/                  # MCP tool implementations (one file per domain)
        __init__.py           # Tool registration via register(mcp) function
  skills/                     # Skill definitions (optional)
    <skill-name>/
      SKILL.md                # Skill instructions with frontmatter
  hooks/                      # Hook definitions (optional, proj only)
    hooks.json                # Auto-discovered hook configuration
```

Skills-only plugins omit the `server/` directory and `.mcp.json`.

### Shared Dependency: `_shared`

The `plugins/_shared/` directory contains the `claude-hook-transport` package (v0.3.3), which provides two modules used by all MCP server plugins:

- **`hook_dispatch`** -- Post-execution hook dispatch wrapper (`enable_hook_dispatch()`)
- **`hook_transport`** -- Dual-transport HTTP client (Unix domain sockets + TCP fallback)

Plugins reference this as a path dependency via `[tool.uv.sources]`:

```toml
[tool.uv.sources]
claude-hook-transport = { path = "../../_shared" }
```

---

## Hook System

The hook system enables MCP-to-MCP communication: when a tool finishes executing in one plugin, it can automatically trigger tools in other plugins.

### Dispatch Flow

The full dispatch path:

1. **Tool called** -- A registered MCP tool is invoked by Claude Code
2. **Wrapper intercepts** -- `_wrap_tool_fn` (injected by `enable_hook_dispatch`) wraps the tool execution
3. **Tool executes** -- The original tool function runs and returns a result
4. **Result serialized** -- The result is serialized to JSON (max 100KB)
5. **POST to router server** -- Sends `{tool: "router_fire_tool", params: {trigger_tool, source_result, depth: 0}}` to the router server via Unix domain socket (resolved from `~/.claude/sockets/router`, prefix `/tmp/claude-cpm-router-<pid>.sock`)
6. **Registry lookup** -- `router_fire_tool` loads the hook registry and matches hooks by `trigger_tool`
7. **Condition evaluation** -- Each matched hook's `condition` is evaluated against `~/.claude/proj.yaml`
8. **Target dispatch** -- POSTs to the target server socket (e.g., `unix:///tmp/claude-cpm-todoist-<pid>.sock`)
9. **Target executes** -- The target tool runs and returns its result

### enable_hook_dispatch()

Source: `plugins/_shared/hook_dispatch/dispatch.py`

Called in each plugin's `main.py` **before** any `register()` calls. It monkey-patches `mcp.tool()` on the FastMCP instance so all subsequently registered tools get a post-execution wrapper.

```python
from hook_dispatch import enable_hook_dispatch

mcp = FastMCP("plugin_name")
enable_hook_dispatch(mcp, exclude={"meta_tool_1", "meta_tool_2"})
# register() calls come after -- they use the patched mcp.tool()
```

Key behaviors:
- Intercepts both `@mcp.tool` (no parens) and `@mcp.tool(name="x", ...)` decorator forms
- If the router server is unreachable (ConnectError/TimeoutException), the tool returns normally with a warning logged
- Tool exceptions propagate without dispatch
- The `exclude` parameter prevents dispatch for meta-tools (e.g., router plugin excludes `router_fire_tool`, `router_list_tool`, `router_recover_tool`)

### hooks.yaml and Conditions

Hook definitions live in `hooks.yaml` files. Conditions are boolean expressions evaluated against `~/.claude/proj.yaml` at fire time.

**Condition syntax:**
- Dot-path resolution walks nested YAML keys (e.g., `sync.todoist.enabled`)
- Supports `and`/`or` operators (`and` binds tighter)
- `!` negation prefix
- Missing keys or missing config file evaluate to `False`

**Standard condition mappings:**

| Condition | `proj.yaml` path | Used by |
|-----------|------------------|---------|
| `sandbox_integration` | top-level bool | sandbox, proj, worktree |
| `zoxide_integration` | top-level bool | worktree, zoxide |
| `git_tracking.enabled` | `git_tracking.enabled` | proj |
| `sync.todoist.enabled` | `sync.todoist.enabled` | todoist |
| `sync.todoist.auto_sync` | `sync.todoist.auto_sync` | todoist |
| `sync.trello.enabled` | `sync.trello.enabled` | trello |
| `sync.trello.auto_sync` | `sync.trello.auto_sync` | trello |

Compound conditions are common, e.g., `"sync.todoist.enabled and sync.todoist.auto_sync and project.todoist_project_id"`.

### Blocking vs Non-Blocking Hooks

The dispatcher always awaits the `router_fire_tool` HTTP response (30s timeout). Inside `router_fire_tool`:

- **Blocking hooks** (`blocking: true`) -- Awaited concurrently via `asyncio.gather`. Results are returned to the caller.
- **Non-blocking hooks** (`blocking: false`, the default) -- Dispatched in background daemon threads and return immediately.

### Verification Hooks

Hooks with `verification: true` fire in Phase 2 after all primary hooks complete. They receive an enriched source containing `hook_results` from Phase 1 blocking hooks. Verification hooks are always blocking and do not increment depth.

### Depth Tracking

`max_depth=3` (configurable in `hooks.yaml` `settings.max_depth`). Prevents runaway cascades when hooks trigger tools that trigger hooks. The `depth` param is passed through the dispatch chain and checked at the start of `router_fire_tool`.

---

## Transport

### Unix Domain Sockets (Default)

All inter-plugin communication uses Unix domain sockets at:

```
/tmp/claude-cpm-{plugin}-{pid}.sock
```

Each plugin's `run_dual()` call passes the plugin name for socket path construction. This is the default transport and requires no configuration.

### TCP Fallback

Set `HOOK_TRANSPORT=tcp` to fall back to TCP on `127.0.0.1` with the following port assignments:

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

---

## Config Conventions

### Field Naming

- **Field names**: `underscore_case` (`tracking_dir`, `auto_sync`, `default_priority`)
- **Nested section names**: lowercase (`sync.todoist`, `permissions`, `archive`)
- **Integration flags**: `underscore_case` (`sandbox_integration`, `worktree_integration`)

### MCP Tool Naming

- **Internal plugins**: `mcp__plugin_<marketplace>_<plugin>__<tool_name>` (e.g., `mcp__plugin_proj_proj__todo_add`)
- **External MCP servers**: `mcp__<server>__<tool-name>` (e.g., `mcp__claude_ai_Todoist__add_tasks`)
- **Wildcard allow rules**: `mcp__<server>__*` format

### Git Flush Messages

Git flush messages follow the `"Action: subject"` pattern:
- `"Define: {todo-id}"` -- Requirements gathered
- `"Sync: Jira"` -- External sync completed
- `"Save: session"` -- Session notes saved

### Skill Invocation

Skills are namespaced by plugin: `/proj:<skill-name>`, `/worktree:<skill-name>`, `/router:<skill-name>`.

Skill files live at `plugins/<name>/skills/<skill-name>/SKILL.md`.

### Version Bumping

Versions must be bumped in three places simultaneously:
1. `plugins/<name>/.claude-plugin/plugin.json`
2. `plugins/<name>/server/pyproject.toml`
3. `.claude-plugin/marketplace.json`

---

## Plugin Interaction

### Dependency Graph

```
proj ──── permissions mgmt ────> sandbox
worktree ── permissions mgmt ──> sandbox
proj ──── hook dispatch ────────> router ──> todoist, trello, jira
worktree ── hook dispatch ──────> router
```

**sandbox** is the single source of truth for `settings.json`. Neither `proj` nor `worktree` write settings files directly -- they call sandbox MCP tools.

**router** is the central dispatcher (formerly `hooks`). All plugins with MCP servers have hook dispatch enabled, and `router_fire_tool` routes events to the correct target server.

**proj** does not read `worktree.yaml` directly -- it uses worktree MCP tools for any worktree operations.

### Session Lifecycle

1. **SessionStart hook** -- Detects project from CWD, builds context (meta + todos + notes), injects into system prompt
2. **User runs skills** -- Interactive work session
3. **PreCompact hook** -- Compacts context when approaching token limits
4. **SessionEnd hook** -- Updates session timestamp
