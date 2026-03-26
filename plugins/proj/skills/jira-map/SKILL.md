---
name: jira-map
description: Compute Jira-to-local mapping using epic-first logic and display a dry-run. Sub-skill of jira-sync.
allowed-tools: mcp__proj__proj_jira_map, mcp__proj__config_load, mcp__jira__jira_get_epic_issues
argument-hint: "<issues-json>"
---

Compute the Jira-to-local project/todo mapping using epic-first logic. This is a sub-skill used by `/proj:jira-sync`.

Accepts the issues data produced by `/proj:jira-fetch`.

## Steps

### 1. Accept issues data

- Receive the fetched Jira issues JSON (output from jira-fetch).

### 2. Compute mapping

- Call `mcp__proj__proj_jira_map` with the fetched issues JSON.
- The response includes a mapping plan with two sections:
  - **Auto-mapped** (epic groups): epics matched to existing or new projects
  - **Needs input** (standalone groups): issues with no epic that require user assignment

### 3. Display mapping

Show the proposed mapping in two sections:

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

- **Existing** -- maps to an already-tracked local project (matched by jira_issue_key or fuzzy name)
- **Will create** -- a new local project will be created from the epic
- **(unmapped)** -- standalone issue with no automatic match; user must assign
- **Matched by** -- the `matched_strategy` from the JiraGroup (e.g., `tag_match`, `keyword_match`, `recent_suggestion`, `fuzzy_name`, `jira_issue_key`); shown as `—` when unmapped

Return the mapping plan for use by downstream sub-skills (jira-apply).

## Notes

- All Jira MCP tool names use the static pattern `mcp__jira__<tool_name>`.
- Epics become projects with `jira_issue_key` set on ProjectMeta for stable re-matching.
- Standalone issues (no epic) are NOT auto-assigned to any project. They require explicit user input.
