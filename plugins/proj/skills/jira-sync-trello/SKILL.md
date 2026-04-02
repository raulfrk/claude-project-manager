---
name: jira-sync-trello
description: Pull Jira issues to local projects, then push to Trello. Equivalent to running /proj:jira-sync followed by /proj:trello-sync.
allowed-tools: mcp__proj__config_load
argument-hint: "[--user <username>] [--projects <key1,key2>]"
context: fork
agent: general-purpose
---

Convenience wrapper that chains `/proj:jira-sync` and `/proj:trello-sync` in sequence.

**Full sub-skill chain**: jira-sync -> trello-setup -> trello-fetch -> trello-diff -> trello-push -> trello-link. See each parent skill for details on sub-skill responsibilities.

**1.** Check prerequisites

- Call `mcp__proj__config_load` -- read `jira.enabled` and `trello.enabled`.
- If `jira.enabled` is false or not set, stop with: "Jira sync not enabled. Run `/proj:init-plugin` to enable it."
- If `trello.enabled` is false or not set, stop with: "Trello sync not enabled. Run `/proj:init-plugin` to enable it."

**2.** Run Jira sync

- Invoke `Skill("proj:jira-sync")` passing through any `--user` and `--projects` arguments from the original invocation.
- If jira-sync fails or is cancelled, stop. Do not proceed to Trello sync.

**3.** Run Trello sync

- Invoke `Skill("proj:trello-sync")`.

**4.** Combined summary

Display a single combined summary:

```
Jira -> Local -> Trello sync complete.
```

If either step reported "everything up to date", note that in the summary.

## Prerequisites

- Jira sync must be enabled (`jira.enabled: true` in config).
- Trello sync must be enabled (`trello.enabled: true` in config).
- Both Jira and Trello MCP servers must be running and reachable.

## Error Handling

- **Jira not enabled**: displays "Jira sync not enabled. Run `/proj:init-plugin` to enable it." and stops.
- **Trello not enabled**: displays "Trello sync not enabled. Run `/proj:init-plugin` to enable it." and stops.
- **Jira sync fails**: stops without proceeding to Trello sync.
- **Trello sync fails**: reports the Trello failure in the combined summary.

## Output

Combined summary: `Jira -> Local -> Trello sync complete.` If either step reported everything up to date, notes that in the summary.
