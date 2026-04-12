---
name: jira-sync-trello
description: Pull Jira issues to local projects, then push to Trello. Equivalent to running /proj:jira-sync followed by /proj:trello-sync.
allowed-tools: mcp__proj__config_load
argument-hint: "[--user <username>] [--projects <key1,key2>]"
context: fork
agent: general-purpose
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Chains `/proj:jira-sync` → `/proj:trello-sync`. See each parent skill for details.

**1.** Check prereqs

- `mcp__proj__config_load` — read `jira.enabled`, `trello.enabled`.
- `jira.enabled` false/unset → stop: "Jira sync not enabled. Run `/proj:init-plugin` to enable it."
- `trello.enabled` false/unset → stop: "Trello sync not enabled. Run `/proj:init-plugin` to enable it."

**2.** Jira sync

- Skill tool: `skill: "proj:jira-sync", args: "<forwarded --user and --projects arguments>"`.
- Fails/cancelled → stop. No Trello sync.

**3.** Trello sync

- Skill tool: `skill: "proj:trello-sync"`.

**4.** Combined summary

```
Jira -> Local -> Trello sync complete.
```

Either step "everything up to date" → note in summary.

## Prereqs

- `jira.enabled: true` in config
- `trello.enabled: true` in config
- Both Jira/Trello MCP servers running, reachable

## Err Handling

- Jira not enabled → "Jira sync not enabled. Run `/proj:init-plugin` to enable it." Stop.
- Trello not enabled → "Trello sync not enabled. Run `/proj:init-plugin` to enable it." Stop.
- Jira sync fails → stop, no Trello sync.
- Trello sync fails → report in combined summary.

## Output

Combined summary: `Jira -> Local -> Trello sync complete.` Either step up-to-date → note in summary.
