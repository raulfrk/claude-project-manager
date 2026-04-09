---
name: prioritize
description: "prioritize todos", "reorder todos", "suggest execution order", "analyze blocking"
allowed-tools: mcp__plugin_proj_proj__todo_analyze_graph, mcp__plugin_proj_proj__todo_tree, mcp__plugin_proj_proj__todo_block, mcp__plugin_proj_proj__todo_unblock, mcp__plugin_proj_proj__todo_update, mcp__plugin_proj_proj__proj_identify_batches, mcp__plugin_proj_proj__proj_session_context, mcp__plugin_proj_proj__tracking_git_flush, EnterPlanMode, ExitPlanMode
context: inline
argument-hint: "[--apply]"
---

Analyze the blocking graph and propose an optimal execution order for all open todos.

## Steps

**1. Load project context**

Call `mcp__plugin_proj_proj__proj_session_context` to get the active project name and config.

**2. Analyze the dependency graph**

Call `mcp__plugin_proj_proj__todo_analyze_graph` with the project name. This returns:
- `todos`: list of per-todo objects with `id`, `title`, `priority`, `blocked_by`, `blocks`, `tags`, `critical_path_depth`, `transitive_fan_out`, `is_on_critical_path`
- `tiers`: list of lists (topological tiers)
- `cycles`: list of cycle descriptions (strings)
- `critical_path`: ordered list of todo IDs on the critical path
- `orphans`: todo IDs with no blocking relationships

If `todo_analyze_graph` fails, display the error and stop.

**3. Guard: no todos**

If the `todos` list is empty: respond "No open todos to prioritize." and stop.

**4. Guard: single todo**

If there is exactly 1 todo: respond "Only one open todo -- nothing to reorder." and stop.

**5. Detect cycles**

If `cycles` is non-empty, display:

```
### Circular Dependencies

The following cycles were detected and must be resolved before optimal ordering is possible:
- <cycle description>
- ...
```

Continue with analysis despite cycles (the tiering will be partial).

**6. Compute hybrid scores**

For each todo, compute:

```
score = (transitive_fan_out * 2) + (critical_path_depth * 3) + priority_weight
```

Where `priority_weight` = `{high: 3, medium: 1, low: 0}`.

Sort todos by score descending within each tier.

**7. Propose changes**

Based on the graph analysis and scores, propose three types of changes:

- **New blocking edges**: for todos that should be sequenced but are not currently connected (e.g., a high-score todo in Tier 0 that logically must precede a Tier 1 todo but has no edge).
- **Removed blocking edges**: for existing edges that are redundant (transitive) or conflict with the optimal order.
- **Priority updates**: todos on the critical path with high fan-out should be `high`; leaf todos with no dependents should be `low`; others should be `medium`.

Only propose changes that differ from the current state.

**8. Present the plan**

`EnterPlanMode` -- display the proposed prioritization:

```
### Proposed Prioritization

#### Tier 0 -- Start immediately
- <icon> **<id>** -- <title> *(<priority>)* [blocks ...] [manual]

#### Tier 1 -- After Tier 0
- ...

#### Tier N -- After Tier N-1
- ...

### Changes
| Action | Todo | Detail |
|--------|------|--------|
| ADD block | <id> -> <id> | <reason> |
| REMOVE block | <id> -> <id> | <reason> |
| SET priority | <id> | <old> -> <new> (<reason>) |
```

Display rules:
- Use status icons: `<pending icon>` for pending, `<in_progress icon>` for in_progress.
- Bold the todo ID, show full exact title, priority in italics.
- Todos with `"manual"` in `tags` get a `[manual]` badge after the priority.
- Include `[blocks X, Y]` and `[blocked by X]` inline where applicable.
- Within each tier, sort by hybrid score descending.
- If no changes are needed, show the tiered display with: "No changes needed -- current ordering is already optimal."

**9. Await approval**

`ExitPlanMode` for user approval.

**10. Apply changes (on accept)**

Apply all proposed changes:
- Call `mcp__plugin_proj_proj__todo_block` for each new blocking edge.
- Call `mcp__plugin_proj_proj__todo_unblock` for each removed blocking edge.
- Call `mcp__plugin_proj_proj__todo_update` with `priority=<new>` for each priority change.

Do NOT call `todo_complete` -- this skill only reorders, never completes.

**11. Handle rejection**

If the user rejects the plan: respond "No changes made." and stop.

**12. Git flush**

Call `mcp__plugin_proj_proj__tracking_git_flush` with `commit_message="Prioritize: reorder todos"`.

## Prerequisites

- An active project must be loaded (call `proj_session_context` first).

## Error Handling

- **No active project**: displays error from `proj_session_context` and stops.
- **Graph analysis failure**: displays error from `todo_analyze_graph` and stops.
- **No open todos**: "No open todos to prioritize." and stops.
- **Single todo**: "Only one open todo -- nothing to reorder." and stops.

## Output

A tiered execution plan with proposed blocking and priority changes, applied after user approval. Confirmation of all applied changes.
