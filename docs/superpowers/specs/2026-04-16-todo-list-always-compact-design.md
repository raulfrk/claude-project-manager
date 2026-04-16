# Always-Compact Output for `/proj:todo list` and `/proj:todo tree`

**Date**: 2026-04-16
**Status**: Draft — awaiting user review
**Worktree**: `/home/raul/worktrees/cpm/feat-todo-list-always-compact`
**Branch**: `feat/todo-list-always-compact` (off `dev`)

## Problem

`/proj:todo list` and `/proj:todo tree` currently invoke `mcp__plugin_proj_proj__todo_tree`, `mcp__plugin_proj_proj__todo_list`, and `mcp__plugin_proj_proj__todo_ready` with their default `compact=False`. The tools respond with indented JSON dumps of full todo objects (every field, multi-line per todo). On projects with dozens of open todos this floods the session with low-value tokens: callers of the skill overwhelmingly want a scannable one-line-per-todo summary, not the full structured payload.

The MCP layer already supports a compact branch on two of the three tools (`todo_list`, `todo_tree`). It emits one-line-per-todo output and wraps the result in `{"result": "<lines>", "count": N, "truncated": K}`. The third tool, `todo_ready`, has no compact branch.

## Goals

1. Default `/proj:todo list` and `/proj:todo tree` to compact output for all non-priority subcommands.
2. Preserve the existing full-JSON output as an opt-in escape hatch (`--full` flag).
3. Add parity to `todo_ready` so the `list ready` path can participate in the same compact contract.
4. Do not change MCP tool defaults — direct callers of the MCP server (hooks, tests, other skills) must continue to see `compact=False` unless they explicitly set it.

## Non-Goals

- Changing the `--prio`/`--priorities` rendering path. That path already post-processes the tree into tier-sorted one-liners; it needs `compact=False` internally to keep the structured JSON it consumes.
- Changing `todo_list_all` (the archive-inclusive variant). The skill does not invoke it today and this work does not touch the archive flow.
- Changing `/proj:todo add|update|done|delete|block|unblock|notes-append|notes-patch` output. Only listing operations change.
- Removing or deprecating the non-compact output. It stays available via `--full` and via direct MCP calls with `compact=False`.

## Design

### Layer map

| Layer | Change |
|---|---|
| `plugins/proj/server/server/tools/todos.py` — `todo_ready` | Add `compact: bool = False` param. When true, emit one-line-per-todo output matching the `todo_list` compact format, wrapped in `{"result", "count", "truncated"}`. Non-compact path unchanged. |
| `plugins/proj/skills/todo/SKILL.md` — `list` subcommand | Parse trailing `--full` flag. Call `todo_tree`/`todo_list`/`todo_ready` with `compact=not_full`. |
| `plugins/proj/skills/todo/SKILL.md` — `tree` subcommand | Same `--full` parsing. Call `todo_tree` with `compact=not_full`. |
| `plugins/proj/skills/todo/SKILL.md` — `list --prio` path | Unchanged: skill always calls `todo_tree(compact=False)` because it needs structured JSON to flatten + tier. `--full` has no effect when combined with `--prio`. |
| `plugins/proj/server/tests/test_todos.py` (or the closest existing module covering `todo_ready`) | New tests covering the compact branch. |

### `todo_ready` compact rendering

Match `todo_list` exactly so consumers of the compact contract see a uniform shape:

```python
if compact:
    lines = []
    for t in ready:
        tags_str = ",".join(t.tags) if t.tags else ""
        lines.append(f"{t.id} | {t.status} | {t.title} | {t.priority} | {tags_str}")
    if truncated:
        lines.append(f"... {truncated} more items")
    return json.dumps(
        {"result": "\n".join(lines), "truncated": truncated, "count": len(ready)}
    )
```

`todo_ready` does not currently support `max_items`; this design does not add one. If `max_items` support is wanted later it's a separate enhancement — introducing it here would widen scope beyond the user's answered question.

### Skill parse rules

Grammar the skill must honor for `list` and `tree`:

```
list      [all|pending|ready|blocked] [--prio|--priorities] [--full]
tree      [--full]
```

Resolution:

- Tokenize the argument tail.
- Strip the subcommand word (`list` / `tree`).
- Collect flags: `--prio`/`--priorities` → `prio_mode=True`; `--full` → `full_mode=True`.
- Remaining positional token (if any) is the filter name for `list` (`all`, `pending`, `ready`, `blocked`).
- `prio_mode=True` → call the existing `--prio` branch with `compact=False` regardless of `full_mode`.
- `prio_mode=False` → call the relevant tool with `compact=(not full_mode)`.

### `list` subcommand behavior matrix

| Invocation | Tool | `compact` |
|---|---|---|
| `/proj:todo list` | `todo_tree(include_done=False)` | `True` |
| `/proj:todo list --full` | `todo_tree(include_done=False)` | `False` |
| `/proj:todo list all` | `todo_tree(include_done=True)` | `True` |
| `/proj:todo list all --full` | `todo_tree(include_done=True)` | `False` |
| `/proj:todo list ready` | `todo_ready()` | `True` |
| `/proj:todo list ready --full` | `todo_ready()` | `False` |
| `/proj:todo list blocked` | `todo_list(status="pending")` then filter `blocked_by` | `True` |
| `/proj:todo list blocked --full` | `todo_list(status="pending")` then filter `blocked_by` | `False` |
| `/proj:todo list --prio` | `todo_tree(include_done=False)`, flatten, tier | `False` (internal) |
| `/proj:todo list all --prio` | `todo_tree(include_done=True)`, flatten, tier | `False` (internal) |
| `/proj:todo list --prio --full` | same as `--prio` (no-op) | `False` (internal) |

### `tree` subcommand behavior matrix

| Invocation | Tool | `compact` |
|---|---|---|
| `/proj:todo tree` | `todo_tree()` | `True` |
| `/proj:todo tree --full` | `todo_tree()` | `False` |

### Rendering note for `list blocked`

`list blocked` calls `todo_list(status="pending", compact=True)` which returns pipe-delimited rows. The skill today filters to rows with non-empty `blocked_by`, but with `compact=True` it has only the flattened string — not structured objects. Resolution: the skill must pass `blocked=True` to `todo_list` (the tool already supports that filter) so the server does the filtering before compact rendering. Concretely:

- Today: `todo_list(status="pending")` → skill filters non-empty `blocked_by` in prose.
- New: `todo_list(status="pending", blocked=True, compact=compact)` → server filters, then compact-renders.

`blocked=True` already returns only todos with non-empty `blocked_by` (confirmed by reading `_filter_todos`). This is a small but real behavior change: the skill's old prose-filter step goes away, replaced by the tool's own filter. Output for the same input is equivalent.

### Error handling

- `todo_ready(compact=True)` with no ready todos: return the existing plain-string `"No todos ready to start."` before entering the compact branch. Matches `todo_list`/`todo_tree` pattern.
- `--full` passed to a subcommand that doesn't support it (`add`, `done`, etc.): skill silently ignores. Parse only recognizes `--full` on `list` and `tree`.
- `--full` passed alongside `--prio`: skill silently ignores `--full`. Documented in the subcommand matrix.
- Existing error paths (`require_project`, empty result, invalid status) unchanged.

### Tests

Add to `plugins/proj/server/tests/test_mcp_edge_cases.py` (alongside the existing `test_todo_list_compact_mode` / `test_todo_list_compact_max_items` tests). `test_mcp_tools.py` holds the non-compact `test_todo_ready*` cases — keep compact coverage in the edge-cases module to mirror how `todo_list` compact tests are organized today.

1. `test_todo_ready_compact_with_results` — seed 2 ready todos; call `todo_ready(compact=True)`; assert the response parses as JSON with `result` containing 2 pipe-delimited lines, `count == 2`, `truncated == 0`.
2. `test_todo_ready_compact_empty` — no ready todos; call `todo_ready(compact=True)`; assert the plain string `"No todos ready to start."` is returned (not the JSON wrapper).
3. `test_todo_ready_compact_parity` — seed N ready todos; call with `compact=False` and `compact=True`; parse both; assert the same set of todo IDs appears in both responses.

Skill prose itself has no unit test precedent in this codebase and will not get one — the `list blocked` behavior change is covered by a server-side test instead:

4. `test_todo_list_blocked_filter_with_compact` — seed two todos, one with `blocked_by=[other]`, one without; call `todo_list(status="pending", blocked=True, compact=True)`; assert only the blocked todo appears in `result`.

### Backward compatibility

- Direct MCP callers (other skills, hooks, pytest integration tests) are unaffected: tool defaults for `compact` stay `False` on `todo_list`, `todo_tree`, and the newly-parametrized `todo_ready`.
- The skill's user-facing contract changes: prior invocations like `/proj:todo list` that returned full JSON now return compact lines. Anyone who scripts against the skill output must switch to `--full`. This is acceptable — the skill is interactive-intended and users drive it, not scripts.

## Migration

One-shot. No data migration. No config migration. No deprecation window.

## Open Questions

None at design time. Remaining decisions (exact test filename, whether `max_items` is worth adding to `todo_ready`) are implementation-plan concerns, not design concerns.
