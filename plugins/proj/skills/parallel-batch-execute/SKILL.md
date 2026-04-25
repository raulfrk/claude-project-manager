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

<!-- Sections filled in subsequent tasks: Phase 0, Phase 1, Phase 2, Phase 3, Phase 4, Phase 5, Cross-refs -->
