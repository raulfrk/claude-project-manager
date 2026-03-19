---
name: jira-sync-trello
description: Pull Jira issues to local projects, then push to Trello. Equivalent to running /proj:jira-sync followed by /proj:trello-sync.
disable-model-invocation: "false"
allowed-tools: mcp__proj__config_load
argument-hint: "[--user <username>] [--projects <key1,key2>]"
---

Convenience wrapper that chains `/proj:jira-sync` and `/proj:trello-sync` in sequence.

**Full sub-skill chain**: jira-fetch -> jira-map -> jira-apply -> trello-setup -> trello-fetch -> trello-diff -> trello-push -> trello-link. See each parent skill for details on sub-skill responsibilities.

## Steps

### 1. Check prerequisites

- Call `mcp__proj__config_load` -- read `jira.enabled` and `trello.enabled`.
- If `jira.enabled` is false or not set: stop with "Jira sync not enabled. Set `jira.enabled: true` in `~/.claude/proj.yaml`."
- If `trello.enabled` is false or not set: stop with "Trello sync not enabled. Set `trello.enabled: true` in `~/.claude/proj.yaml`."

### 2. Run Jira sync

- Invoke `Skill("proj:jira-sync")` passing through any `--user` and `--projects` arguments from the original invocation.
- If jira-sync fails or is cancelled, stop. Do not proceed to Trello sync.

### 3. Run Trello sync

- Invoke `Skill("proj:trello-sync")`.

### 4. Combined summary

Display a single combined summary:

```
Jira -> Local -> Trello sync complete.
```

If either step reported "everything up to date", note that in the summary.

## Suggested next

- `/proj:status` -- review project status after sync
- `/proj:todo list` -- review todos after sync
