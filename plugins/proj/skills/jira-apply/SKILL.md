---
name: jira-apply
description: Apply a confirmed Jira mapping to create/update local projects and todos. Sub-skill of jira-sync.
allowed-tools: mcp__proj__proj_jira_apply, mcp__proj__tracking_git_flush
argument-hint: "<confirmed-mapping-json>"
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Apply confirmed Jira-to-local mapping, creating projects/todos. Sub-skill of `/proj:jira-sync`.

Input: confirmed mapping JSON from `/proj:jira-map`.

**1.** Accept confirmed mapping JSON.

**2.** `mcp__proj__proj_jira_apply` w/ confirmed mapping.

**3.** `mcp__proj__tracking_git_flush` w/ `commit_message="Sync: Jira"`.

**4.** Results

`status` = `"ok"`:

```
Jira sync applied.
Projects created: {created_projects}
Todos created: {created_todos}
Todos updated: {updated_todos}
Skipped (unmapped): {skipped}
```

Nothing changed → "Jira sync complete. Everything up to date."

`status` = `"partial"`:

```
Jira sync applied (with errors).
Projects created: {created_projects}  Todos created: {created_todos}  Todos updated: {updated_todos}  Failed: {count of failed issues}

Failed issues:
| Issue | Error |
|-------|-------|
| PROJ-123 | failed: <reason> |
| PROJ-456 | failed: <reason> |
```

`per_issue` maps each issue key → `"created"`, `"updated"`, `"skipped"`, `"failed: <reason>"`. Show only failed issues.

## Prerequisites

Confirmed mapping JSON from `/proj:jira-map` required.

## Err Handling

- Apply tool err → show err, stop.
- Partial failures → show failed issues table w/ key + reason.
- Git flush err → show err, no rollback.

## Output

Success: summary w/ projects created, todos created/updated, skipped counts. Partial failure: same + failed issues table. Nothing changed: `Jira sync complete. Everything up to date.`

## Notes

- Jira MCP tools: `mcp__jira__<tool_name>`.
- Idempotent: existing todos updated by `jira_issue_key` lookup, no dupes.
