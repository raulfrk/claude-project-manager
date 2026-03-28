---
name: jira-sync
description: Pull Jira issues for the configured user and sync them to local projects/todos. Uses epic-first mapping — each epic becomes a project, standalone issues need user assignment. Works without loading a project first.
allowed-tools: mcp__proj__proj_session_context, mcp__proj__config_load, mcp__proj__proj_list, mcp__proj__proj_init, mcp__proj__proj_get_active, mcp__proj__proj_jira_map, mcp__proj__proj_jira_apply, mcp__proj__tracking_git_flush, mcp__proj__todo_list, mcp__proj__notes_append, mcp__jira__jira_search, mcp__jira__jira_get_issue, mcp__jira__jira_get_issue_comments, mcp__jira__jira_get_epic_issues, mcp__jira__jira_get_user_issues, mcp__jira__jira_init
argument-hint: "[--user <username>] [--projects <key1,key2>]"
context: fork
agent: general-purpose
---

Pull Jira issues for a user and sync them to local projects/todos using **epic-first mapping**.
This skill operates across all projects -- it does NOT require loading a project first.

**Sub-skill chain**: This skill chains three sub-skills in sequence:
1. `/proj:jira-fetch` -- fetch issues from Jira
2. `/proj:jira-map` -- compute epic-first mapping and display dry-run
3. `/proj:jira-apply` -- apply confirmed mapping, create projects/todos

## Epic-first mapping logic

1. **Epics become projects** -- each Jira epic maps to one local project. The project's `jira_issue_key` is set to the epic key for instant re-matching on future runs.
2. **Issues under an epic** -- become todos in that epic's project.
3. **Standalone issues (no epic)** -- flagged as `needs_user_decision`. The user must assign them to an existing project or create a new one. There is NO automatic catchall or default project.
4. **Re-run matching** -- projects are matched by `jira_issue_key` first (instant, stable), then by fuzzy name. This makes re-runs idempotent.

**1.** Setup

- Call `mcp__proj__proj_session_context` -- read all config, project metadata, and integration settings in one call.
  - From the result, extract `integrations.jira.enabled` and other config values.
  - Note: jira-sync works across all projects, so the active project from context is informational only.
- If `integrations.jira.enabled` is false or not set: stop with "Jira sync not enabled. Set `jira.enabled: true` in `~/.claude/proj.yaml`."
- Parse optional `--user` and `--projects` from skill arguments:
  - `--user <username>` overrides `jira.default_user`
  - `--projects <key1,key2>` filters to specific Jira project keys
- If no user is resolved (neither argument nor config default): stop with "No Jira user configured. Pass `--user <username>` or set `jira.default_user` in `~/.claude/proj.yaml`."

**Failure: Jira MCP server unavailable**
If the Jira MCP server is not reachable -- for example, a tool call raises a
tool-not-found error, returns a connection error, or is simply not registered -- stop immediately
and say:

> "Jira MCP server not available. Check your MCP server configuration and restart it."

Do not proceed with any further sync steps.

**2.** Fetch issues from Jira

- Call `mcp__jira__jira_get_user_issues` with the resolved username and project keys (if provided).
- If no issues are returned: "No open issues found." Stop.

**3.** Compute mapping

- Call `mcp__proj__proj_jira_map` with the fetched issues JSON.
- The response includes a mapping plan with two sections:
  - **Auto-mapped** (epic groups): epics matched to existing or new projects
  - **Needs input** (standalone groups): issues with no epic that require user assignment

**4.** Display dry-run

Show the proposed mapping in two sections:

```
### Auto-mapped (epic-based)

| # | Epic | Local Project | Issues | Status |
|---|------|---------------|--------|--------|
| 1 | PROJ-5 (User Auth) | user-auth | 4 | Existing (jira_issue_key match) |
| 2 | PROJ-12 (API v2) | api-v2 | 3 | Will create |

### Needs input (no epic)

| # | Issue | Summary | Suggested Project |
|---|-------|---------|-------------------|
| 3 | PROJ-789 | Fix login bug | (unmapped) |
| 4 | PROJ-801 | Update docs | (unmapped) |

Issues to sync: 10 (7 auto-mapped, 3 need input)
```

- **Existing** -- maps to an already-tracked local project (matched by jira_issue_key or fuzzy name)
- **Will create** -- a new local project will be created from the epic
- **(unmapped)** -- standalone issue with no automatic match; user must assign

**5.** User confirmation/editing

Present options:

```
Options:
1. **Apply** -- proceed with auto-mapped groups; skip unmapped issues
2. **Edit** -- assign unmapped issues to projects
3. **Cancel** -- abort sync
```

If the user chooses **Edit**: ask which row number to change. The user can:
- Assign to an existing project (list projects via `mcp__proj__proj_list`)
- Create a new project (ask for name, call `mcp__proj__proj_init`)
- Skip an issue (leave unmapped -- it will not be synced)

Repeat editing until the user confirms with **Apply** or aborts with **Cancel**.

**6.** Apply mapping

- Call `mcp__proj__proj_jira_apply` with the confirmed mapping JSON.
- Display results:
  ```
  Jira sync applied.
  Projects created: X
  Todos created: Y
  Todos updated: Z
  Skipped (unmapped): W
  ```

**7.** Git tracking flush

- Call `mcp__proj__tracking_git_flush` with `commit_message="Sync: Jira"`.

**8.** Summary

Display a final summary with counts. If nothing changed: "Jira sync complete. Everything up to date."

Display suggested next steps:
- `/proj:status` — review project status after sync
- `/proj:trello-sync` — if Trello is also enabled, sync there too

---

## Notes

- All Jira MCP tool names use the pattern `mcp__jira__<tool_name>`.
- This skill works WITHOUT loading a project first -- it operates across all projects.
- Epics become projects with `jira_issue_key` set on ProjectMeta for stable re-matching.
- Standalone issues (no epic) are NOT auto-assigned to any project. They require explicit user input.
- A single local project can receive issues from multiple Jira epics if the user edits the mapping.
- Re-running is idempotent: existing todos are updated by `jira_issue_key` lookup, no duplicates created.
- Epics themselves are NOT synced as todos -- they define the project boundary.
- Bulk tools: `jira_bulk_create_issues` (POST /rest/api/2/issue/bulk) and `jira_bulk_update_issues` (loops PUT per issue with rate limiting). Both return `{successes, failures}` for partial-failure handling.

Suggested next: (1) /proj:status — review project status after sync  (2) /proj:todo list — review todos after sync
