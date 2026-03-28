---
name: jira-fetch
description: Fetch all Jira issues assigned to the configured user. Sub-skill of jira-sync.
allowed-tools: mcp__jira__jira_get_user_issues, mcp__proj__config_load
argument-hint: "[--user <username>] [--projects <key1,key2>]"
---

Fetch Jira issues for a user. This is a sub-skill used by `/proj:jira-sync`.

**1.** Read config

- Call `mcp__proj__config_load` -- read `jira.*` config values. Note `jira.enabled`, `jira.default_user`.
- If `jira.enabled` is false or not set, stop with: "Jira sync not enabled. Run `/proj:init-plugin` to enable it."
- Parse optional `--user` and `--projects` from skill arguments:
  - `--user <username>` overrides `jira.default_user`
  - `--projects <key1,key2>` filters to specific Jira project keys
- If no user is resolved (neither argument nor config default), stop with: "No Jira user configured. Pass `--user <username>` or set `jira.default_user` in `~/.claude/proj.yaml`."

**Failure: Jira MCP server unavailable**
If the Jira MCP server is not reachable -- for example, a tool call raises a
tool-not-found error, returns a connection error, or is simply not registered -- stop immediately
with:

> "Jira MCP server not available. Check your MCP server configuration and restart Claude Code."

Do not proceed with any further steps.

**2.** Fetch issues

- Call `mcp__jira__jira_get_user_issues` with the resolved username and project keys (if provided).
- If no issues are returned: "No open issues found." Stop.

**3.** Display summary

Show a summary of fetched issues:

```
Fetched {count} issues from Jira for user {username}.
Epics: {epic_count}
Standalone issues: {standalone_count}
```

Return the fetched issues data for use by downstream sub-skills (jira-map).

## Prerequisites

- Jira sync must be enabled (`jira.enabled: true` in config).
- A Jira username must be configured (via `--user` argument or `jira.default_user` in config).
- Jira MCP server must be running and reachable.

## Error Handling

- **Jira not enabled**: displays "Jira sync not enabled. Run `/proj:init-plugin` to enable it." and stops.
- **No user configured**: displays "No Jira user configured. Pass `--user <username>` or set `jira.default_user` in `~/.claude/proj.yaml`." and stops.
- **Jira MCP unavailable**: displays "Jira MCP server not available. Check your MCP server configuration and restart Claude Code." and stops.
- **No issues found**: displays "No open issues found." and stops.

## Output

Summary of fetched issues: total count, epic count, standalone issue count. Returns the issues data for downstream sub-skills.

## Notes

- All Jira MCP tool names use the static pattern `mcp__jira__<tool_name>`.
- This skill works WITHOUT loading a project first -- it operates across all projects.
