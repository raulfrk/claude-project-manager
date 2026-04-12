---
name: prioritize
description: "prioritize todos", "reorder todos", "suggest execution order", "analyze blocking"
allowed-tools: mcp__plugin_proj_proj__todo_analyze_graph, mcp__plugin_proj_proj__todo_tree, mcp__plugin_proj_proj__todo_block, mcp__plugin_proj_proj__todo_unblock, mcp__plugin_proj_proj__todo_update, mcp__plugin_proj_proj__proj_identify_batches, mcp__plugin_proj_proj__proj_session_context, mcp__plugin_proj_proj__tracking_git_flush, EnterPlanMode, ExitPlanMode
context: inline
argument-hint: "[--apply]"
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Analyze blocking graph, propose optimal exec order for open todos.

## Steps

**1. Load project ctx**

`mcp__plugin_proj_proj__proj_session_context` → get active project name/config.

**2. Analyze dependency graph**

`mcp__plugin_proj_proj__todo_analyze_graph` w/ project name. Returns:
- `todos`: per-todo objects w/ `id`, `title`, `priority`, `blocked_by`, `blocks`, `tags`, `critical_path_depth`, `transitive_fan_out`, `is_on_critical_path`
- `tiers`: topological tiers (list of lists)
- `cycles`: cycle desc strings
- `critical_path`: ordered todo IDs on critical path
- `orphans`: todo IDs w/ no blocking relations

Fails → show err, stop.

**3. Guard: no todos**

Empty `todos` → "No open todos to prioritize." Stop.

**4. Guard: single todo**

Exactly 1 todo → "Only one open todo -- nothing to reorder." Stop.

**5. Detect cycles**

`cycles` non-empty →

```
### Circular Dependencies

The following cycles were detected and must be resolved before optimal ordering is possible:
- <cycle description>
- ...
```

Continue despite cycles (tiering partial).

**6. Compute hybrid scores**

Each todo:

```
score = (transitive_fan_out * 2) + (critical_path_depth * 3) + priority_weight
```

`priority_weight` = `{high: 3, medium: 1, low: 0}`.

Sort by score desc within each tier.

**7. Propose changes**

Three change types:

- New blocking edges: todos needing sequencing but unconnected (e.g., high-score Tier 0 todo logically preceding Tier 1 todo w/ no edge).
- Removed blocking edges: redundant (transitive) or conflicting edges.
- Priority updates: critical path + high fan-out → `high`; leaf todos w/ no dependents → `low`; others → `medium`.

Only propose diffs from cur state.

**8. Present plan**

`EnterPlanMode` — show proposed prioritization:

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
- Status icons: `<pending icon>` pending, `<in_progress icon>` in_progress
- Bold todo ID, full exact title, priority in italics
- `"manual"` in `tags` → `[manual]` badge after priority
- Include `[blocks X, Y]` / `[blocked by X]` inline
- Within each tier, sort by hybrid score desc
- No changes needed → show tiered display w/ "No changes needed -- cur ordering is already optimal."

**9. Await approval**

`ExitPlanMode` for user approval.

**10. Apply changes (on accept)**

Apply all proposed:
- `mcp__plugin_proj_proj__todo_block` each new blocking edge
- `mcp__plugin_proj_proj__todo_unblock` each removed edge
- `mcp__plugin_proj_proj__todo_update` w/ `priority=<new>` each priority change

Never call `todo_complete` — skill only reorders.

**11. Handle rejection**

Rejected → "No changes made." Stop.

**12. Git flush**

`mcp__plugin_proj_proj__tracking_git_flush` w/ `commit_message="Prioritize: reorder todos"`.

## Prerequisites

Active project must be loaded (`proj_session_context` first).

## Err Handling

- No active project → show err from `proj_session_context`, stop
- Graph analysis failure → show err from `todo_analyze_graph`, stop
- No open todos → "No open todos to prioritize." Stop
- Single todo → "Only one open todo -- nothing to reorder." Stop

## Output

Tiered exec plan w/ proposed blocking/priority changes, applied after user approval. Confirmation of all applied changes.
