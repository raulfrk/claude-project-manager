---
name: jira-map
description: Compute Jira-to-local mapping using epic-first logic and display a dry-run. Sub-skill of jira-sync.
allowed-tools: mcp__proj__proj_jira_map, mcp__proj__config_load, mcp__jira__jira_get_epic_issues
argument-hint: "<issues-json>"
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Compute Jira-to-local project/todo mapping via epic-first logic. Sub-skill of `/proj:jira-sync`.

Accepts issues data from Jira fetch step.

**1.** Accept issues data

- Receive fetched Jira issues JSON.

**2.** Compute mapping

- `mcp__proj__proj_jira_map` w/ fetched issues JSON.
- Response includes mapping plan:
 - Auto-mapped (epic groups): epics matched to existing/new projects
 - Needs input (standalone groups): issues w/o epic requiring user assignment

**3.** Display mapping

Two sections:

**Auto-mapped (epic-based)**

| # | Epic | Local Project | Issues | Status |
|---|------|---------------|--------|--------|
| 1 | PROJ-5 (User Auth) | user-auth | 4 | Existing (jira_issue_key match) |
| 2 | PROJ-12 (API v2) | api-v2 | 3 | Will create |

**Needs input (no epic)**

| # | Issue | Summary | Suggested Project | Matched by |
|---|-------|---------|-------------------|------------|
| 3 | PROJ-789 | Fix login bug | (unmapped) | — |
| 4 | PROJ-801 | Update docs | docs-project | keyword_match |

```
Issues to sync: {total} ({auto_count} auto-mapped, {needs_input_count} need input)
```

- **Existing** — maps to already-tracked local project (matched by `jira_issue_key` or fuzzy name)
- **Will create** — new local project from epic
- **(unmapped)** — standalone issue, no auto match; user must assign
- **Matched by** — `matched_strategy` from JiraGroup (e.g. `tag_match`, `keyword_match`, `recent_suggestion`, `fuzzy_name`, `jira_issue_key`); `—` when unmapped

Return mapping plan for downstream sub-skills (`jira-apply`).

## Prerequisites

- Jira MCP server running/reachable.
- Issues data provided as input.

## Err Handling

- Jira MCP unavailable → show err, stop.
- No issues provided → show err, stop.
- Mapping tool err → show `proj_jira_map` err, stop.

## Output

Two-section mapping table: Auto-mapped (epic-based) w/ Epic, Local Project, Issues count, Status; Needs input (no epic) w/ Issue, Summary, Suggested Project, Matched by. Summary line w/ total/auto/needs-input counts.

## Notes

- All Jira MCP tool names: `mcp__jira__<tool_name>`.
- Epics → projects w/ `jira_issue_key` on ProjectMeta for stable re-matching.
- Standalone issues (no epic) NOT auto-assigned; require explicit user input.
