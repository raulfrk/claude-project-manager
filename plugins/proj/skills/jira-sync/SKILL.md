---
name: jira-sync
description: Pull Jira issues for the configured user and sync them to local projects/todos. Uses epic-first mapping — each epic becomes a project, standalone issues need user assignment. Works without loading a project first.
allowed-tools: mcp__proj__proj_session_context, mcp__proj__config_load, mcp__proj__proj_list, mcp__proj__proj_init, mcp__proj__proj_get_active, mcp__proj__proj_sync, mcp__proj__tracking_git_flush, mcp__proj__todo_list, mcp__proj__notes_append, mcp__jira__jira_get_issue_comments, mcp__jira__jira_init
argument-hint: "[--user <username>] [--projects <key1,key2>]"
context: fork
agent: general-purpose
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Pull Jira issues for user, sync to local projects/todos via **epic-first mapping**.
Works across all projects -- no project load required.

## Sync path

Call `proj_sync(integration="jira")` directly -- handles fetch, map, apply in one call.

## Epic-first mapping

1. **Epics → projects** -- each epic maps to one project. `jira_issue_key` set to epic key for re-matching.
2. **Issues under epic** → todos in epic's project.
3. **Standalone issues (no epic)** → assigned to `project_name` if provided; else warned, skipped.
4. **Re-run matching** -- match by `jira_issue_key` first (instant, stable), then fuzzy name. Idempotent.
5. **Auto-create** -- new epics w/o match auto-created (cap: 10/sync). Warns if >80% title similarity w/ existing.
6. **Status sync** -- Jira Done/Closed/Resolved → complete local todos; Jira reopened + local done → pending.

**1.** Setup

- `mcp__proj__proj_session_context` -- read config, metadata, integration settings.
 - Extract `integrations.jira.enabled` + other vals.
 - jira-sync works across all projects; active project informational only.
- `jira.enabled` false/unset → stop: "Jira sync not enabled. Run `/proj:init-plugin` to enable it."
- Parse opt `--user`/`--projects` from args:
 - `--user <username>` overrides `jira.default_user`
 - `--projects <key1,key2>` filters to specific Jira project keys
- No user resolved → stop: "No Jira user configured. Pass `--user <username>` or set `jira.default_user` in `~/.claude/proj.yaml`."

**Failure: Jira MCP unavailable**
Tool-not-found, connection err, or not registered → stop:

> "Jira MCP server not available. Check your MCP server config and restart Claude Code."

No further sync steps.

**2.** Pre-fetch comments (opt)

- `mcp__jira__jira_get_issue_comments` for known issue keys (if available from prior ctx).
- Build `comments_by_key` dict mapping keys → comment lists.
- Best-effort -- skip on failure.

**3.** Call `proj_sync(integration="jira")`

- `mcp__proj__proj_sync(integration="jira")` (opt `project_name` to scope, `comments_json` from step 2 not directly supported — pre-fetch comments and pass via jira_issues_json if needed).
- Handle response:
 - `"success"` → show summary counts
 - `"partial_success"` → show errors table, offer one retry:
 - Ask: "Some issues failed. Retry failed issues?"
 - Yes → `proj_sync(integration="jira", retry_failures=retry_token)`
 - No → continue to summary
 - `"error"` → show err, stop

**4.** Git tracking flush

- `mcp__proj__tracking_git_flush` w/ `commit_message="Sync: Jira"`.

**5.** Summary

Show final counts. Nothing changed: "Jira sync complete. Everything up to date."

Next steps:
- `1. /proj:status` -- review project status
- `2. /proj:trello-sync` -- if Trello enabled, sync there too


## Prerequisites

- `jira.enabled: true` in config
- Jira username configured (`--user` arg or `jira.default_user`)
- Jira MCP server running + reachable

## Error Handling

- Jira not enabled → `Jira sync not enabled.` stop
- No user → `No Jira user configured.` w/ instructions, stop
- MCP unavailable → `Jira MCP server not available.` stop
- No issues → `No open issues found.` stop
- Partial failures → table w/ issue key + err; offer one retry

## Output

Summary: projects created, todos created/updated, warnings. Nothing changed → `Jira sync complete. Everything up to date.`

## Notes

- All Jira MCP tools: `mcp__jira__<tool_name>`.
- Works WITHOUT loading project -- operates across all.
- Epics → projects w/ `jira_issue_key` on ProjectMeta for stable re-matching.
- Standalone issues (no epic) skipped w/ warning unless `project_name` provided.
- Re-run idempotent: existing todos updated by `jira_issue_key`, no dupes.
- Epics NOT synced as todos -- define project boundary only.
- `retry_token` expires 30min. After → fresh sync required.

Next: `1. /proj:status` -- review status | `2. /proj:todo list` -- review todos
