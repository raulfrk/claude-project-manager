# 605 Simplification — Design Spec
*2026-04-15*

## Status
Approved. Ready for implementation.

## Context
605.1–605.5 are complete (hook dedup, installer update removal, config surface reduction, speculative phase removal, SKILL.md trim). This spec covers the remaining 605.6–605.10.

## Approach
Single worktree branch `todo-605.6-10`. Linear execution: 605.6 → 605.7 → 605.8 → 605.9 → 605.10. Each merge group = one commit (server changes + SKILL.md updates + test updates bundled together). No intermediate inconsistent state.

**Consolidation depth:** Targeted merges only — merge redundant variants, keep semantically distinct tools separate (~76→~55 for proj). No action-discriminator god-tools.

---

## 605.6 — Proj Tool Merges

### Merge groups (in order)

| Old tools | New signature | Notes |
|---|---|---|
| `todo_add` + `todo_add_child` + `todo_batch_add_children` | `todo_add(parent=?, children=[...])` | Largest callsite impact |
| `todo_complete` + `todo_batch_complete` | `todo_complete(ids=[...])` | Hook trigger name changes |
| `todo_block` + `todo_unblock` | folded into `todo_update(blocked_by=[...])` | Few callsites |
| `proj_todoist_full_sync` + `proj_trello_full_sync` + `proj_jira_full_sync` | `proj_sync(integration=?)` | Hook trigger names change |

All other proj tools stay separate (semantically distinct).

### Pre-work
Clear stale `blocked_by 605.3` on 605.6 before starting (605.3 is done).

---

## 605.7 — Other Plugin Tool Merges

Targeted per plugin:
- **trello:** merge `batch_add_checklist_items`/`add_checklist_item`; merge `batch_update`/`update` variants
- **jira:** merge bulk + single variants for per-entity operations
- **todoist:** merge related task ops where safe
- **sandbox/worktree:** light merges only (already lean)

---

## 605.8 — Plugin Folding

Three folds, one commit each.

### analyse → proj
- Move `plugins/analyse/skills/review/` → `plugins/proj/skills/review/`
- Move `plugins/analyse/skills/explore/` → `plugins/proj/skills/explore/`
- analyse has no MCP server — no tool re-registration needed
- Remove `plugins/analyse/`, marketplace.json entry, installer reference
- Skill namespace: `analyse:review` → `proj:review`, `analyse:explore` → `proj:explore`
- Update CLAUDE.md skill reference table

### zoxide → worktree
- Move `zoxide_boost`, `zoxide_query`, `zoxide_remove` implementations into `plugins/worktree/server/server/`
- Register in worktree `main.py` via `enable_hook_dispatch`
- Remove `plugins/zoxide/`, marketplace.json entry, installer reference
- Keep MCP server name `zoxide` for hook dispatch compat (trigger_tool names unchanged)

### sandbox → proj
- Move all ~14 sandbox tool implementations into `plugins/proj/server/server/`
- Register in proj `main.py`
- Remove `plugins/sandbox/`, marketplace.json entry, installer reference
- MCP allow rule `mcp__plugin_sandbox_sandbox__*` → covered by existing `mcp__plugin_proj_proj__*` rule
- No hook condition updates needed (sandbox_integration removed in 605.3)

---

## 605.9 — File Format Legacy Removal

- Delete YAML load/fallback paths in `sql_todos.py` + `migration.py`
- `data.db` missing → hard fail (no fallback)
- Retain `archive.yaml.bak` fallback in `load_archived_todos` (explicit disaster recovery only)
- No user-facing behavior change for normal operation

---

## 605.10 — Version Bump + Changelog

- Gate: all plugin tests green on worktree branch before this commit
- Bump all remaining plugins to `5.0.0` in `plugin.json` + `marketplace.json`
- Write `CHANGELOG.md` listing all breaking changes:
  - Merged tool names + new signatures
  - Removed plugins (analyse, zoxide, sandbox as standalone)
  - New skill namespaces (proj:review, proj:explore)
  - Hook trigger_tool renames

---

## Error Handling + Edge Cases

**No backward compat.** Hard 5.0 cut. Old tool names removed. Skills calling old names fail loudly — caught by tests before merge.

**Hook trigger_tool migration:**
- `todo_batch_complete` → `todo_complete`
- `proj_todoist_full_sync` / `proj_trello_full_sync` / `proj_jira_full_sync` → `proj_sync`
- Migration script (from 605.1) extended to rename these trigger_tool values in `~/.claude/hooks.yaml`
- Dry-run mode: prints changes before writing

**Plugin folding — MCP server name changes:**
- zoxide + sandbox server entries in `~/.claude/settings.json` removed on reinstall
- Reinstall is the upgrade path — no runtime migration

**SKILL.md callsite check:**
After each merge, grep all SKILL.md + `.claude/` files for old tool name. Any miss = test failure. Grep check baked into PR verification.

---

## Commit Structure

Each commit must include:
1. Server changes (`plugins/<name>/server/server/`)
2. SKILL.md updates for calling skills
3. Test updates (existing tests to new signatures + new parametric tests)
4. Hook dispatch reference updates (`trigger_tool` field renames)

Rollback: each commit is atomic. `git revert <commit>` restores consistency.

---

## Expected Impact (605.6–605.10)

| Metric | Before | After |
|---|---|---|
| Plugins | 9 | 6 |
| Proj MCP tools | ~76 | ~55 |
| All MCP tools | ~210 | ~150 |
| Standalone plugins | analyse, zoxide, sandbox | folded |
| YAML fallback code | present | removed |
| Version | 4.x | 5.0.0 |
