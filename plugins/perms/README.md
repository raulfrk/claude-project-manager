# perms

Manage Claude Code `settings.json` permissions from within Claude sessions. Provides MCP tools to add and remove allow rules for project directories and MCP server tool access — no manual JSON editing required.

## What it does

Claude Code controls file access and tool execution via `permissions.allow` in `settings.json`. Entries must follow specific formats (double-slash prefix for absolute paths, `mcp__<server>__*` for MCP tools). This plugin exposes MCP tools that handle those formats correctly and write to `settings.json` atomically.

Changes take effect immediately — no restart required.

## Installation

Install from the Claude Code plugin marketplace:

```
/install-plugin perms
```

This registers the `perms` MCP server. The server is invoked as `mcp__plugin_perms_perms__<tool>`.

## MCP Tools

All tools are idempotent — calling them when a rule already exists (or doesn't exist) is safe.

### Directory allow rules

| Tool | Description |
|------|-------------|
| `perms_add_allow(path, scope?)` | Add `Read` and `Edit` allow rules for a directory |
| `perms_remove_allow(path, scope?)` | Remove `Read` and `Edit` allow rules for a directory |
| `perms_list(scope?)` | List all current allow rules |
| `perms_check(path, scope?)` | Check whether a path already has allow rules |

The `path` parameter must be an absolute path. The double-slash prefix required by Claude Code (`//home/raul/...`) is applied automatically.

Each call to `perms_add_allow` adds two entries to `permissions.allow`:

```
Read(//home/raul/projects/my-project/**)
Edit(//home/raul/projects/my-project/**)
```

### MCP server allow rules

| Tool | Description |
|------|-------------|
| `perms_add_mcp_allow(server_name, scope?)` | Add a wildcard allow rule for an MCP server |
| `perms_remove_mcp_allow(server_name, scope?)` | Remove a wildcard allow rule for an MCP server |
| `perms_batch_add_mcp_allow(servers, scope?)` | Add wildcard rules for multiple MCP servers in one write |

`perms_add_mcp_allow("proj")` adds `mcp__proj__*` to `permissions.allow`, which allows all tools from the `proj` MCP server without prompting.

`perms_batch_add_mcp_allow` is equivalent to calling `perms_add_mcp_allow` for each server but performs a single atomic write. Prefer this when granting access to multiple servers at once.

### Scope parameter

All tools accept an optional `scope` parameter:

- `"user"` (default) — reads/writes `~/.claude/settings.json`
- `"project"` — reads/writes `.claude/settings.json` in the current working directory
- `"all"` — reads both files (list and check tools only)

## Usage examples

Grant Claude access to a project directory:

```
perms_add_allow("/home/raul/projects/my-project")
```

Allow all tools from the `proj` and `worktree` MCP servers:

```
perms_batch_add_mcp_allow(["proj", "worktree"])
```

Check whether a path is already allowed:

```
perms_check("/home/raul/projects/my-project")
# [user] OK — all rules present
```

List all current rules:

```
perms_list()
# [user] /home/raul/.claude/settings.json — 4 allow rule(s):
#   Read(//home/raul/projects/my-project/**)
#   Edit(//home/raul/projects/my-project/**)
#   mcp__proj__*
#   mcp__worktree__*
```

Remove access to a directory:

```
perms_remove_allow("/home/raul/projects/my-project")
```

## Technical notes

**Atomic writes** — `settings.json` is written via a temp file in the same directory, then renamed. This prevents corruption if the process is interrupted mid-write.

**Double-slash path format** — Claude Code requires absolute paths in `permissions.allow` to use a double-slash prefix (e.g., `//home/raul/...`). The tools apply this automatically; pass a normal absolute path.

**Preserves existing content** — the tools only modify the `permissions.allow` array. All other keys in `settings.json` are preserved as-is.

**No configuration required** — the server has no configuration file. It reads the standard Claude Code settings locations directly.

**Python 3.12+, single dependency** — the server requires only the `mcp` package at runtime.
