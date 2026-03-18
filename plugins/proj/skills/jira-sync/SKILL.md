---
name: jira-sync
description: Pull Jira issues for the configured user and sync them to local projects/todos. Works without loading a project first. Shows a dry-run mapping for user confirmation before applying.
disable-model-invocation: "true"
allowed-tools: mcp__proj__config_load, mcp__proj__proj_list, mcp__proj__proj_init, mcp__proj__proj_get_active, mcp__proj__proj_jira_map, mcp__proj__proj_jira_apply, mcp__proj__tracking_git_flush, mcp__proj__todo_list, mcp__proj__notes_append
argument-hint: "[--user <username>] [--projects <key1,key2>]"
---

> **Note on allowed-tools:** Jira MCP tools (`mcp__{jira.mcp_server}__*`) are intentionally
> absent from `allowed-tools`. The Jira MCP server name is user-configurable via
> `jira.mcp_server` in the proj config (e.g. `"jira"`, `"atlassian"`, `"mcp-jira"`).
> Because the server name is only known at runtime, a static wildcard like
> `mcp__jira__*` would not match a differently-named server. Claude resolves the actual
> tool names dynamically after reading config and calls them without a pre-declared allow entry.

Pull Jira issues for a user and sync them to local projects/todos. This skill operates
across all projects -- it does NOT require loading a project first.

## Jira Tool Resolution

The Jira MCP server name is configurable. **Before making any Jira tool call**, read
`jira.mcp_server` from the config (via `mcp__proj__config_load`) and substitute it as the
prefix. All `mcp__jira__<tool>` references below are templates -- replace `jira` with the
actual server name from config.

Example: if `jira.mcp_server` is `atlassian`, call `mcp__atlassian__jira_get_user_issues` not
`mcp__jira__jira_get_user_issues`.

## Steps

### 1. Setup

- Call `mcp__proj__config_load` -- read `jira.*` config values. Note `jira.enabled`, `jira.mcp_server`, `jira.default_user`.
- If `jira.enabled` is false or not set: stop with "Jira sync not enabled. Set `jira.enabled: true` in `~/.claude/proj.yaml`."
- Parse optional `--user` and `--projects` from skill arguments:
  - `--user <username>` overrides `jira.default_user`
  - `--projects <key1,key2>` filters to specific Jira project keys
- If no user is resolved (neither argument nor config default): stop with "No Jira user configured. Pass `--user <username>` or set `jira.default_user` in `~/.claude/proj.yaml`."
- Resolve the Jira MCP server name for all subsequent calls.

**Failure: Jira MCP server unavailable**
If the Jira MCP server is not reachable -- for example, a tool call raises a
tool-not-found error, returns a connection error, or is simply not registered -- stop immediately
and say:

> "Jira MCP server '<server_name>' is not available. Verify the server is running and that
> `jira.mcp_server` in your proj config matches the registered MCP server name."

Do not proceed with any further sync steps.

### 2. Fetch issues from Jira

- Resolve the Jira MCP tool name: `mcp__{jira.mcp_server}__jira_get_user_issues`
- Call with the resolved username and project keys (if provided).
- If no issues are returned: "No open issues found." Stop.

### 3. Compute mapping

- Call `mcp__proj__proj_jira_map` with the fetched issues JSON.
- The response includes a mapping plan: groups of issues (by epic or Jira project key) mapped to suggested local projects.

### 4. Display dry-run

Show the proposed mapping as a table:

```
### Proposed Jira -> Local Mapping

| # | Jira Source | Local Project | Status |
|---|------------|---------------|--------|
| 1 | PROJ-123 (Epic: User Auth) | user-auth | Existing |
| 2 | PROJ-456 (Epic: API v2) | api-v2 | Will create |
| 3 | PROJ-789 (Story: Fix login) | (unassigned) | Needs mapping |

Issues to sync: 15
```

- **Existing** -- maps to an already-tracked local project
- **Will create** -- a new local project will be created
- **Needs mapping** -- no automatic match; user must assign manually

### 5. User confirmation/editing

Present options:

```
Options:
1. **Apply** -- proceed with this mapping
2. **Edit** -- reassign issues to different projects
3. **Cancel** -- abort sync
```

If the user chooses **Edit**: ask which row number to change. The user can:
- Assign to an existing project (list projects via `mcp__proj__proj_list`)
- Create a new project (ask for name, call `mcp__proj__proj_init`)
- Skip an issue (exclude from sync)

Repeat editing until the user confirms with **Apply** or aborts with **Cancel**.

### 6. Apply mapping

- Call `mcp__proj__proj_jira_apply` with the confirmed mapping JSON.
- Display results:
  ```
  Jira sync applied.
  Projects created: X
  Todos created: Y
  Todos updated: Z
  ```

### 7. Git tracking flush

- Call `mcp__proj__tracking_git_flush` with `commit_message="Jira sync"`.

### 8. Summary

Display a final summary with counts. If nothing changed: "Jira sync complete. Everything up to date."

Suggest next steps:
- `/proj:status` -- review project status after sync
- `/proj:trello-sync` -- if Trello is also enabled, sync there too

---

## Notes

- All Jira MCP tool names use the pattern `mcp__<mcp_server>__<tool_name>` where `<mcp_server>` comes from `jira.mcp_server` in config.
- This skill works WITHOUT loading a project first -- it operates across all projects.
- Each non-epic issue maps to a SPECIFIC local project (no catch-all).
- A single local project can receive issues from multiple Jira sources (different epics, different Jira project keys).
- Re-running is idempotent: existing todos are updated, no duplicates are created.
- Epics are used as grouping hints for mapping, not synced as todos themselves.

## Suggested next

- `/proj:status` -- review project status after sync
- `/proj:todo list` -- review todos after sync
- `/proj:jira-sync` -- run again after making local changes
