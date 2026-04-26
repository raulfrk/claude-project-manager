# Project CLAUDE.md Batch Completion Rule Update — Design

**Date**: 2026-04-26
**Status**: approved (brainstorm); ready for implementation
**Tracks todo**: 738

## Problem

The "Batch Completion Enforcement" section in `/home/raul/projects/claude-project-manager/CLAUDE.md` mandates a tool that no longer exists:

```markdown
**Always use `mcp__proj__todo_batch_complete` when marking 2 or more todos done in the same operation.** Never loop `todo_complete` across multiple ids.
```

Two problems with the current text:

1. **Removed tool**: `mcp__proj__todo_batch_complete` was removed (verified via `plugins/proj/server/tests/test_todos_batch_complete.py` which asserts removal).
2. **Stale prefix**: `mcp__proj__` is the legacy MCP server name; the current namespace is `mcp__plugin_proj_proj__`.

Agents following the rule fail with "tool not found" because the tool was unified into a single `todo_complete` that accepts either `todo_id` (single) or `todo_ids` (batch).

## Goal

Rewrite the section to point at the current tool name + form. Preserve the rule's intent: a single batch call is always preferred over N sequential calls when marking 2+ todos done.

## Non-goals

1. **Touching other rules** in CLAUDE.md — only the "Batch Completion Enforcement" section.
2. **Updating implementation comments / SKILL.md files / managed CLAUDE.md** — those may have similar stale refs but are out of scope. If any are found during this fix, capture as separate todos.
3. **Adding new behavior** — the rule's intent (single batch call > N calls) stays. Only the mechanics + tool name change.

## Architecture

Single-file edit: `/home/raul/projects/claude-project-manager/CLAUDE.md`.

Replace the entire `## Batch Completion Enforcement` section (currently lines starting at "## Batch Completion Enforcement" through the blank line before `## E2E TUI Snapshot Flakes`) with:

```markdown
## Batch Completion Enforcement

**Always pass `todo_ids=[...]` to `mcp__plugin_proj_proj__todo_complete` when marking 2+ todos done in the same operation.** Never loop the tool with one `todo_id` per call. The batch path:
- Routes via `todo_ids` (list) parameter — atomic, deduplicated, saved under a single cross-process file lock.
- Fires ONE aggregated hook chain per integration (Todoist `todoist_complete_tasks`, Trello `trello_batch_archive_cards`, Jira `jira_update_issues`) instead of N sequential chains.
- Returns `_hooks.structured_errors` listing per-integration failures by id.

Single-todo completion: pass `todo_id="..."` (or `todo_ids=["..."]` — both work).
```

## Why this rewrite

- **Tool name correct**: `mcp__plugin_proj_proj__todo_complete` matches the current MCP namespace + the unified tool's actual name.
- **Form correct**: The unified `todo_complete` accepts both `todo_id` (single) and `todo_ids` (list, batch) — verified at `plugins/proj/server/server/tools/todos.py:1223-1235`.
- **Atomic + single hook chain**: The batch path's atomicity claim is preserved (it still uses cross-process locking). The implementation detail of `threading.Lock` + `fcntl.flock` is dropped from the rule — that's internal, not part of the API contract agents need.
- **Single-todo guidance**: Clarifies that both params accept a single id; the batch tool is forward-compatible.

## Testing

This is a documentation change to a project-level CLAUDE.md file. No automated tests apply.

**Manual verification**: After the change lands, agents reading the project CLAUDE.md should be able to follow the rule by calling `mcp__plugin_proj_proj__todo_complete(todo_ids=[...])` successfully — verified by the fact that this very session's todo-completion calls (e.g., closing 779, 780, 781, 776) all used `todo_ids` and succeeded.

## Risks Accepted

- **Drift from managed CLAUDE.md (the user-global one)**: out of scope. If the managed version has similar stale refs, file as a follow-up todo.
- **No automated check** for stale tool refs in CLAUDE.md files. Future tool renames may surface similar bugs. Tracked separately if it becomes a pattern.
