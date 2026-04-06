---
name: jira-sync
description: Pull Jira issues for the configured user and sync them to local projects/todos. Uses epic-first mapping — each epic becomes a project, standalone issues need user assignment. Works without loading a project first.
allowed-tools: mcp__proj__proj_session_context, mcp__proj__config_load, mcp__proj__proj_list, mcp__proj__proj_init, mcp__proj__proj_get_active, mcp__proj__proj_jira_map, mcp__proj__proj_jira_apply, mcp__proj__proj_jira_full_sync, mcp__proj__tracking_git_flush, mcp__proj__todo_list, mcp__proj__notes_append, mcp__jira__jira_search, mcp__jira__jira_get_issue, mcp__jira__jira_get_issue_comments, mcp__jira__jira_init
argument-hint: "[--user <username>] [--projects <key1,key2>]"
context: fork
agent: general-purpose
---

Pull Jira issues for a user and sync them to local projects/todos using **epic-first mapping**.
This skill operates across all projects -- it does NOT require loading a project first.

## Primary path: `proj_jira_full_sync`

The preferred approach uses a single tool call that handles deterministic mapping + apply:

1. Fetch issues from Jira
2. Call `proj_jira_full_sync` with the issues JSON
3. Handle the response

**Fallback**: If `proj_jira_full_sync` is unavailable (tool-not-found error), fall back to the legacy 3-step chain described in the "Legacy path" section below.

## Epic-first mapping logic

1. **Epics become projects** -- each Jira epic maps to one local project. The project's `jira_issue_key` is set to the epic key for instant re-matching on future runs.
2. **Issues under an epic** -- become todos in that epic's project.
3. **Standalone issues (no epic)** -- assigned to `project_name` if provided; otherwise warned and skipped. No interactive disambiguation.
4. **Re-run matching** -- projects are matched by `jira_issue_key` first (instant, stable), then by fuzzy name. This makes re-runs idempotent.
5. **Auto-create** -- new epics without a matching project get auto-created (cap: 10 per sync). Warns if >80% title similarity with existing project.
6. **Status sync** -- Jira "Done"/"Closed"/"Resolved" completes local todos; Jira reopened + local done sets pending.

**1.** Setup

- Call `mcp__proj__proj_session_context` -- read all config, project metadata, and integration settings in one call.
  - From the result, extract `integrations.jira.enabled` and other config values.
  - Note: jira-sync works across all projects, so the active project from context is informational only.
- If `integrations.jira.enabled` is false or not set, stop with: "Jira sync not enabled. Run `/proj:init-plugin` to enable it."
- Parse optional `--user` and `--projects` from skill arguments:
  - `--user <username>` overrides `jira.default_user`
  - `--projects <key1,key2>` filters to specific Jira project keys
- If no user is resolved (neither argument nor config default), stop with: "No Jira user configured. Pass `--user <username>` or set `jira.default_user` in `~/.claude/proj.yaml`."

**Failure: Jira MCP server unavailable**
If the Jira MCP server is not reachable -- for example, a tool call raises a
tool-not-found error, returns a connection error, or is simply not registered -- stop immediately
with:

> "Jira MCP server not available. Check your MCP server configuration and restart Claude Code."

Do not proceed with any further sync steps.

**2.** Pre-fetch comments (optional)

- Call `mcp__jira__jira_get_issue_comments` for known issue keys (if any are already available from prior context).
- Build a `comments_by_key` dict mapping issue keys to comment lists.
- This step is best-effort -- if comment fetching fails for an issue, skip it.

**3.** Call `proj_jira_full_sync`

- Call `mcp__proj__proj_jira_full_sync` with:
  - `project_name`: optional, to scope sync to one project
  - `comments_json`: JSON of the `comments_by_key` dict from step 2 (if available)
  - **Important**: When passing Jira issues from `jira_get_user_issues`, serialize the result with `json.dumps()` before passing to `jira_issues_json`. The tool also accepts raw dicts/lists as a fallback, but string serialization is preferred.
- Handle the response:
  - `"success"` -- display the summary counts
  - `"partial_success"` -- display errors table, offer one retry:
    - Ask user: "Some issues failed. Retry failed issues?"
    - If yes, call `proj_jira_full_sync` again with `retry_failures` set to the `retry_token`
    - If no, continue to summary
  - `"error"` -- display the error and stop

**4.** Git tracking flush

- Call `mcp__proj__tracking_git_flush` with `commit_message="Sync: Jira"`.

**5.** Summary

Display a final summary with counts. If nothing changed: "Jira sync complete. Everything up to date."

Display suggested next steps:
- `1. /proj:status` -- review project status after sync
- `2. /proj:trello-sync` -- if Trello is also enabled, sync there too

---

## Legacy path (fallback)

If `proj_jira_full_sync` is not available, fall back to the 3-step chain:

1. Call `mcp__proj__proj_jira_map` with the fetched issues JSON -- produces a mapping plan.
2. Display the mapping as a dry-run table with auto-mapped and needs-input sections.
3. Ask user to **Apply**, **Edit**, or **Cancel**.
4. Call `mcp__proj__proj_jira_apply` with the confirmed mapping.

## Prerequisites

- Jira sync must be enabled (`jira.enabled: true` in config).
- A Jira username must be configured (via `--user` argument or `jira.default_user` in config).
- Jira MCP server must be running and reachable.

## Error Handling

- **Jira not enabled**: displays `Jira sync not enabled.` and stops.
- **No user configured**: displays `No Jira user configured.` with instructions and stops.
- **Jira MCP unavailable**: displays `Jira MCP server not available.` and stops.
- **No issues found**: displays `No open issues found.` and stops.
- **Partial failures**: displays failed issues in a table with issue key and error. Offers one retry.

## Output

Summary with projects created, todos created, todos updated, warnings. If nothing changed: `Jira sync complete. Everything up to date.`

## Notes

- All Jira MCP tool names use the pattern `mcp__jira__<tool_name>`.
- This skill works WITHOUT loading a project first -- it operates across all projects.
- Epics become projects with `jira_issue_key` set on ProjectMeta for stable re-matching.
- Standalone issues (no epic) are skipped with a warning unless a `project_name` is provided.
- Re-running is idempotent: existing todos are updated by `jira_issue_key` lookup, no duplicates created.
- Epics themselves are NOT synced as todos -- they define the project boundary.
- `retry_token` expires after 30 minutes. After that, a fresh sync is required.

Suggested next: `1. /proj:status` -- review project status after sync | `2. /proj:todo list` -- review todos after sync
