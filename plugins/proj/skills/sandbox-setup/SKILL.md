---
name: sandbox-setup
description: Initialize sandbox mode and grant permissions for filesystem paths and MCP servers
allowed-tools: mcp__plugin_sandbox_sandbox__sandbox_list, mcp__plugin_sandbox_sandbox__sandbox_batch_setup, mcp__plugin_sandbox_sandbox__sandbox_batch_setup, mcp__plugin_sandbox_sandbox__sandbox_batch_setup, mcp__plugin_sandbox_sandbox__sandbox_list, mcp__plugin_sandbox_sandbox__sandbox_add_write_path, mcp__plugin_sandbox_sandbox__sandbox_add_mcp_allow, mcp__plugin_proj_proj__notes_append, Edit
argument-hint: "[path_or_mcp_server] [scope]"
context: fork
agent: general-purpose
---

# sandbox-setup

Set up sandbox mode and configure permissions, or grant a single ad-hoc permission.

If arguments are provided, runs **ad-hoc grant mode**. Otherwise, runs **full setup mode**.

---

## Ad-hoc grant mode

Triggered when the user passes arguments (a path or MCP server name).

**1.** Parse arguments

The user may provide: `<path_or_mcp_server> [scope]`

- **scope** defaults to `user` if not specified. Valid values: `user`, `project`.

**2.** Determine type and act

**If a filesystem path is provided** (starts with `/`, `~`, or `.`):
- Call `mcp__plugin_sandbox_sandbox__sandbox_add_write_path(path=<path>, scope=<scope>)`
- Display the result to the user.

**If an MCP server name is provided** (no path separators, looks like a server identifier):
- Call `mcp__plugin_sandbox_sandbox__sandbox_add_mcp_allow(server_name=<name>, scope=<scope>)`
- Display the result to the user.

**If no recognizable argument is provided**, ask the user interactively:
1. "What would you like to grant access to? (filesystem path or MCP server name)"
2. "What scope? (user or project)" — default to `user` if they skip this.
3. Then proceed with the appropriate call above.

**3.** After granting

- Show the confirmation result.

Suggested next: `1. /proj:perms-audit` -- verify the updated permissions

---

## Full setup mode

Triggered when no arguments are provided.

**1.** Check sandbox state

Call `mcp__plugin_sandbox_sandbox__sandbox_list()`.

- **If sandbox is already enabled**: proceed to step 2.
- **If sandbox is NOT enabled**: warn the user that sandbox mode is not yet active and ask them to confirm before proceeding. If the user declines, stop.

**2.** Auto-backup current permissions

Before making any changes, capture the current permission state as a backup.

Call `mcp__plugin_sandbox_sandbox__sandbox_list()` to snapshot the current permissions. Then call `mcp__plugin_proj_proj__notes_append` with:
- `project_id`: the active project ID (from session context), or `"claude-project-manager"` if running outside a project session
- `text`: a timestamped block containing the full `sandbox_list` output, formatted as:
  ```
  ## Sandbox-setup auto-backup (YYYY-MM-DDTHH:MM)
  <sandbox_list output>
  ```

This ensures pre-setup state can be recovered if anything goes wrong.

**3.** Initialize sandbox

Call `mcp__plugin_sandbox_sandbox__sandbox_batch_setup()`. This is idempotent — safe to call even if already initialized.

**4.** Batch setup permissions

Call `mcp__plugin_sandbox_sandbox__sandbox_batch_setup()` in a single atomic call with:

- `mcp_servers`: `["plugin_hooks_hooks", "plugin_proj_proj", "plugin_sandbox_sandbox", "plugin_worktree_worktree", "plugin_trello_trello", "plugin_jira_jira", "plugin_todoist_todoist", "plugin_zoxide_zoxide"]`
- `paths`: `["//home/raul/projects/**", "//home/raul/projects/tracking/**", "//home/raul/worktrees/**", "//home/raul/.claude/skills/**", "//home/raul/.claude/plugins/**"]`
- `target`: `"settings"`

**5.** Set sandbox write paths

Call `mcp__plugin_sandbox_sandbox__sandbox_batch_setup()` to configure sandbox filesystem write rules for all project paths.

**6.** Add explicit Read permissions

Add `Read(path)` entries to `permissions.allow` in `~/.claude/settings.json` for all sandbox paths. These are needed because the `Read` tool checks `permissions.allow` separately from sandbox filesystem rules.

Use Edit on `~/.claude/settings.json` to append the following entries to the `permissions.allow` array (after the last MCP rule, before the closing `]`):
- `"Read(//home/raul/projects/**)"`
- `"Read(//home/raul/projects/tracking/**)"`
- `"Read(//home/raul/worktrees/**)"`
- `"Read(//home/raul/.claude/skills/**)"`
- `"Read(//home/raul/.claude/plugins/**)"`

These are idempotent — skip any that are already present.

**7.** Verify grants

Call `mcp__plugin_sandbox_sandbox__sandbox_list()` to verify all grants are present.

**8.** Print summary

Display: "Sandbox permissions configured for N MCP servers and M filesystem paths."

Replace N with the number of MCP servers (8) and M with the number of filesystem paths (5) confirmed in the verification step.

---

## Prerequisites

- Perms plugin MCP server must be running and reachable.
- For full setup mode, a project should be loaded (detect missing project context and prompt user to load one first).

## Error Handling

- **No arguments in ad-hoc mode**: starts interactive Q&A to collect path/server and scope.
- **Perms MCP unavailable**: displays error from tool call and stops.
- **Invalid path or server name**: displays error from the perms tool and stops.
- **Sandbox already configured**: idempotent — re-running reports current state without errors.
- **No project loaded** (full setup mode): detect missing project context and prompt user to load a project first.
