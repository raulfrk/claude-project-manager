---
name: perms-sandbox-setup
description: Initialize and verify sandbox mode for permissions
allowed-tools: mcp__plugin_perms_perms__perms_is_sandbox_enabled, mcp__plugin_perms_perms__perms_sandbox_init, mcp__plugin_perms_perms__perms_batch_setup, mcp__plugin_perms_perms__perms_list, Edit
context: fork
agent: general-purpose
---

# perms-sandbox-setup

Set up sandbox mode and configure permissions for all MCP servers and filesystem paths.

**1.** Check sandbox state

Call `mcp__plugin_perms_perms__perms_is_sandbox_enabled()`.

- **If sandbox is already enabled**: proceed to step 2.
- **If sandbox is NOT enabled**: warn the user that sandbox mode is not yet active and ask them to confirm before proceeding. If the user declines, stop.

**2.** Initialize sandbox

Call `mcp__plugin_perms_perms__perms_sandbox_init()`. This is idempotent — safe to call even if already initialized.

**3.** Batch setup permissions

Call `mcp__plugin_perms_perms__perms_batch_setup()` in a single atomic call with:

- `mcp_servers`: `["plugin_hooks_hooks", "plugin_proj_proj", "plugin_perms_perms", "plugin_worktree_worktree", "plugin_trello_trello", "plugin_jira_jira", "plugin_todoist_todoist", "plugin_zoxide_zoxide"]`
- `paths`: `["//home/raul/projects/**", "//home/raul/projects/tracking/**", "//home/raul/worktrees/**", "//home/raul/.claude/skills/**", "//home/raul/.claude/plugins/**"]`
- `target`: `"settings"`

**4.** Add explicit Read permissions

Add `Read(path)` entries to `permissions.allow` in `~/.claude/settings.json` for all sandbox paths. These are needed because the `Read` tool checks `permissions.allow` separately from sandbox filesystem rules.

Use Edit on `~/.claude/settings.json` to append the following entries to the `permissions.allow` array (after the last MCP rule, before the closing `]`):
- `"Read(//home/raul/projects/**)"`
- `"Read(//home/raul/projects/tracking/**)"`
- `"Read(//home/raul/worktrees/**)"`
- `"Read(//home/raul/.claude/skills/**)"`
- `"Read(//home/raul/.claude/plugins/**)"`

These are idempotent — skip any that are already present.

**5.** Verify grants

Call `mcp__plugin_perms_perms__perms_list()` to verify all grants are present.

**6.** Print summary

Display: "✓ Sandbox permissions configured for N MCP servers and M filesystem paths."

Replace N with the number of MCP servers (8) and M with the number of filesystem paths (5) confirmed in the verification step.
