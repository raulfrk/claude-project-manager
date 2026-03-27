---
name: perms-grant
description: Interactive permission granting for filesystem paths and MCP servers
---

# perms-grant

Grant permissions for filesystem paths or MCP servers.

## Parse arguments

The user may provide: `<path_or_mcp_server> [scope]`

- **scope** defaults to `user` if not specified. Valid values: `user`, `project`.

## Determine type and act

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

## After granting

- Show the confirmation result.
- Suggest: "Run `perms:audit` to verify the updated permissions."
