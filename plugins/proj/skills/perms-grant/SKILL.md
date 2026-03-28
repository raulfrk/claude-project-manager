---
name: perms-grant
description: Interactive permission granting for filesystem paths and MCP servers
allowed-tools: mcp__plugin_perms_perms__perms_add_allow, mcp__plugin_perms_perms__perms_add_mcp_allow, mcp__plugin_perms_perms__perms_add_domain, mcp__plugin_perms_perms__perms_batch_setup
argument-hint: "<path_or_mcp_server> [scope]"
---

# perms-grant

Grant permissions for filesystem paths or MCP servers.

**1.** Parse arguments

The user may provide: `<path_or_mcp_server> [scope]`

- **scope** defaults to `user` if not specified. Valid values: `user`, `project`.

**2.** Determine type and act

**If a filesystem path is provided** (starts with `/`, `~`, or `.`):
- Call `mcp__plugin_perms_perms__perms_add_allow(path=<path>, scope=<scope>)`
- Display the result to the user.

**If an MCP server name is provided** (no path separators, looks like a server identifier):
- Call `mcp__plugin_perms_perms__perms_add_mcp_allow(server_name=<name>, scope=<scope>)`
- Display the result to the user.

**If no arguments are provided**, ask the user interactively:
1. "What would you like to grant access to? (filesystem path or MCP server name)"
2. "What scope? (user or project)" — default to `user` if they skip this.
3. Then proceed with the appropriate call above.

**3.** After granting

- Show the confirmation result.
Suggested next: (1) /proj:perms-audit — verify the updated permissions
