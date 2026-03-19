---
name: jira-apply
description: Apply a confirmed Jira mapping to create/update local projects and todos. Sub-skill of jira-sync.
disable-model-invocation: "true"
allowed-tools: mcp__proj__proj_jira_apply, mcp__proj__tracking_git_flush
argument-hint: "<confirmed-mapping-json>"
---

Apply a confirmed Jira-to-local mapping, creating projects and todos. This is a sub-skill used by `/proj:jira-sync`.

Accepts the confirmed mapping produced by `/proj:jira-map` (after user review/editing).

## Steps

### 1. Accept confirmed mapping

- Receive the confirmed mapping JSON (output from jira-map, after user confirmation).

### 2. Apply mapping

- Call `mcp__proj__proj_jira_apply` with the confirmed mapping JSON.

### 3. Git tracking flush

- Call `mcp__proj__tracking_git_flush` with `commit_message="Jira sync"`.

### 4. Display results

```
Jira sync applied.
Projects created: {created_projects}
Todos created: {created_todos}
Todos updated: {updated_todos}
Skipped (unmapped): {skipped}
```

If nothing changed: "Jira sync complete. Everything up to date."

## Notes

- All Jira MCP tool names use the static pattern `mcp__jira__<tool_name>`.
- Re-running is idempotent: existing todos are updated by `jira_issue_key` lookup, no duplicates created.
