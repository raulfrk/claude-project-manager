---
name: parallel-batch-execute
description: Orchestrate parallel impl of >=2 disjoint todos w/ full superpowers gate fidelity. Use when user requests parallel batch impl OR says "parallel batch", "/proj:parallel-batch-execute", "execute these N todos in parallel". Wraps standard superpowers workflow (brainstorming -> writing-plans -> subagent-driven-development -> finishing-a-development-branch); parallelism only in execution stage.
allowed-tools: mcp__plugin_proj_proj__proj_session_context, mcp__plugin_proj_proj__todo_get, mcp__plugin_proj_proj__todo_list, mcp__plugin_proj_proj__todo_batch_complete, mcp__plugin_proj_proj__notes_append, mcp__plugin_worktree_worktree__wt_create, mcp__plugin_worktree_worktree__wt_list, mcp__plugin_worktree_worktree__wt_remove, AskUserQuestion, TaskCreate, TaskUpdate, TaskList, Agent, Bash, Skill, Read, Edit
argument-hint: "<todo-id> <todo-id> [<todo-id>...]"
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Orchestrate parallel impl of >=2 disjoint todos. Wrap superpowers workflow; parallelize Phase 3 only.

**Threshold**: N >= 2 disjoint todos. N=1 OR coupled work -> standard sequential superpowers flow.

## Phases

### Phase 0 — Setup

1. `mcp__plugin_proj_proj__proj_session_context` -> active proj name + tracking_dir.
2. Parse `$ARGUMENTS` -> N todo IDs. N < 2 -> err: "use sequential superpowers workflow".
3. Each todo: `mcp__plugin_proj_proj__todo_get` -> verify exists + open. Missing/done -> err.
4. Disjointness: prompt user via `AskUserQuestion` to confirm per-todo file scopes disjoint. Coupled -> abort.
5. `TaskCreate` 1 parent task per phase + subtasks per todo for Phases 1+3.

### Phase 1 — Per-todo design (sequential, fully interactive)

Strict per-todo. No batch-brainstorm shortcut.

```
for each todo in batch:
  1. invoke `superpowers:brainstorming` w/ todo context
       -> docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md
       -> spec self-review + revdiff-routed user review (per managed rule 12)
  2. invoke `superpowers:writing-plans` w/ spec
       -> docs/superpowers/plans/YYYY-MM-DD-<topic>-plan.md
       -> user approval gate
  3. user kills brainstorm/plan -> drop todo from batch; continue w/ N-1
```

Outputs: N spec docs + N plan docs committed before Phase 2.

### Phase 2 — Worktree setup (parallel)

```
1. wt_create x N parallel via mcp__plugin_worktree_worktree__wt_create
   - one branch per todo, forked from current dev
2. post-wt-create-remote-sync per worktree (parallel; single Bash loop)
   - per managed rule 13 (git fetch origin + reset based on local-ahead check)
3. wt_create fails -> abort batch; leave Phase 1 artifacts intact; surface failed todo
```

No language/framework setup (deps, lockfiles) -> implementer handles in Phase 3. Skill stays project-agnostic.

<!-- Sections to fill: Phase 3, Phase 4, Phase 5, Cross-refs -->
