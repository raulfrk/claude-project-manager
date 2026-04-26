# Jira-Sync Standalone Bucketing — Design

**Date**: 2026-04-26
**Status**: approved (brainstorm); ready for implementation
**Component**: `plugins/proj/server/server/tools/jira_sync.py`

## Problem

`/jira-sync` (proj plugin v5.1.7) silently mis-buckets every standalone Jira issue as a todo under whichever project happens to be currently active, instead of creating a dedicated project per the documented Case C ("No epic or foreign/ghost epic → standalone project per issue").

### Root Cause

`_run_jira_full_sync` calls `require_project(project_name)` on line 1985, then unconditionally rebinds the local `project_name` to the resolved name on line 1991:

```python
cfg = require_project(project_name)
if isinstance(cfg, str):
    from server.tools.config import require_config
    cfg_obj = require_config()
else:
    cfg_obj, project_name = cfg          # ← BUG: rebinds project_name unconditionally
```

When the caller passes `project_name=None` (intent: "no override; standalone-per-issue"), `require_project(None)` falls back to the active project and returns `(cfg, active_name)`. The rebind clobbers the caller's None with `active_name`.

The non-None value flows into `_deterministic_map` on line 2119:

```python
apply_input, diagnostics = _deterministic_map(
    jira_issues_parsed,
    cfg_obj,
    project_name,        # ← was None at caller; now active_name
)
```

`_deterministic_map`'s standalone-handling on line 1724 treats truthy `name` as a caller-provided override:

```python
if name:
    # Caller provided a project override
    groups.append({
        "source": "standalone",
        "suggested_project": name,        # ← active project, not the issue's standalone name
        "create_project": False,           # ← per-issue creation BYPASSED
        ...
    })
else:
    # Check dedup: already linked via todo_key_index
    ...
```

The else branch (which contains both standalone-dedup logic AND per-issue project creation) is never reachable when an active project is loaded. The skill's documented "no `project_name` → standalone project per issue" contract cannot fire in that environment.

### Impact

1. **Project taxonomy corruption**: every standalone Jira issue becomes a todo under the active project. Unrelated tickets pile into one project's namespace.
2. **Dedup bypass**: re-runs of `/jira-sync` produce duplicate todos, because the dedup paths (`todo_key_index`, `meta_by_jira_key`) live in the else branch and never execute.
3. **Silent failure**: no error or warning is emitted; the user sees todos appear in the active project and may assume that's intended.

## Goal

When `_run_jira_full_sync` is invoked with `project_name=None`, preserve that None all the way through to `_deterministic_map` so that Case C (per-issue standalone projects + dedup) executes as documented. The caller's explicit `project_name="X"` override path is unchanged.

## Non-goals

1. **Auditing other call sites**: the bug is localized to `_run_jira_full_sync`. Other functions in `jira_sync.py` that call `require_project` are out of scope; no evidence they share the pattern.
2. **Retroactive cleanup of corrupted state**: users with already-mis-bucketed todos can manually delete + re-run `/jira-sync` after the fix lands. No automated migration.
3. **Refactoring `require_project` or its callers**: the helper itself is correct; the bug is in how `_run_jira_full_sync` consumes its return value.
4. **Behavior changes in the explicit-override path**: when caller passes `project_name="X"`, all standalone issues continue to route to project X. Only the implicit active-fallback path changes.

## Architecture

Single-file change, single-line semantic edit:

| File | Action | Responsibility |
|---|---|---|
| `plugins/proj/server/server/tools/jira_sync.py:1991` | Modify | Stop rebinding `project_name` to the active fallback; preserve caller's original value |
| `plugins/proj/server/tests/test_jira_sync.py` | Append | 3 regression tests that pin Case C behavior |

No other files. No installer changes, no plugin manifest changes, no CLI signature changes.

### Fix

Replace line 1991:

```python
# Before
cfg_obj, project_name = cfg

# After
cfg_obj, _ = cfg
# Preserve caller's project_name — do NOT use the active-project fallback.
# When caller passed None, _deterministic_map's standalone-per-issue path
# (Case C) MUST run. Rebinding here forced every standalone issue into the
# active project, bypassing both dedup logic and per-issue project creation.
```

The local `project_name` keeps the caller's original value (None when unset, or a string when caller explicitly overrode).

### End-to-end trace post-fix

- **Caller passes `project_name=None`, no active project loaded:**
  - `require_project(None)` returns `"No active project."` (string).
  - String branch fires: `cfg_obj = require_config()`, `project_name` untouched (still None).
  - `_deterministic_map(..., name=None)` → `if name:` is False → else branch runs → standalone-dedup + per-issue project creation. ✓ correct (already worked pre-fix).

- **Caller passes `project_name=None`, active project loaded** (this is the bug case):
  - `require_project(None)` returns `(cfg, active_name)` (tuple).
  - Tuple branch fires: post-fix, `cfg_obj, _ = cfg` — `project_name` stays None.
  - `_deterministic_map(..., name=None)` → else branch runs → standalone-dedup + per-issue project creation. ✓ correct after fix (was bug pre-fix).

- **Caller passes `project_name="X"`, regardless of active project state:**
  - `require_project("X")` returns `(cfg, "X")` if "X" exists, else error string.
  - Tuple branch: `cfg_obj, _ = cfg` — `project_name` stays `"X"`.
  - `_deterministic_map(..., name="X")` → `if name:` is True → override branch runs → all standalone issues route to X. ✓ unchanged behavior.

## Component: Tests

File: `plugins/proj/server/tests/test_jira_sync.py` (existing). Append 3 new tests targeting `_deterministic_map` directly (unit-level — isolates the bug surface).

### Test 1: `test_deterministic_map_standalone_creates_per_issue_projects_when_name_is_none`

- **Setup**: 1 jira issue with no my-epic. No existing standalone project for its key.
- **Call**: `_deterministic_map(issues, cfg, name=None)`.
- **Assert**: returned `apply_input.groups` contains 1 standalone group with `create_project=True` and `suggested_project` matching the issue-key-derived name. `labels` includes `"jira-standalone"`.

### Test 2: `test_deterministic_map_standalone_does_not_fall_back_to_active_project`

- **Setup**: same issue + an active project loaded (mocked via `cfg` having an active value or via `state.resolve_project`).
- **Call**: `_deterministic_map(issues, cfg, name=None)` — explicit None passed.
- **Assert**: standalone group's `suggested_project` is the issue-derived name, NOT the active project name. `create_project=True`. This pins the regression: previously `_run_jira_full_sync` rebound to active, now caller's None survives → `_deterministic_map` correctly enters Case C.

### Test 3: `test_deterministic_map_standalone_dedups_via_todo_key_index_when_name_is_none`

- **Setup**: 1 jira issue (key `"ABC-123"`). Existing project `"X"` already has a todo with `jira_issue_key="ABC-123"` (loaded into `todo_key_index`).
- **Call**: `_deterministic_map(issues, cfg, name=None)`.
- **Assert**: standalone group's `suggested_project="X"`, `create_project=False`, `project_exists=True`. No duplicate standalone project created.

### Test conventions

- Use existing fixtures from `test_jira_sync.py` (tmp_path-based cfg builders, etc.).
- Avoid mocking `_deterministic_map` itself (it's the unit under test).
- Mock the smallest scope: `state.resolve_project` for Test 2 only; pre-populated `todo_key_index` for Test 3.
- Run synchronously — no async-required call paths.

### Coverage

The 3 new tests target the `if name:` branch (line 1724) by exercising the else arm in three distinct scenarios. Existing tests in `test_jira_sync.py` cover the truthy `name="X"` arm. After this change, both branches have explicit regression coverage.

## Risks Accepted

- **Existing corrupted state**: users with mis-bucketed todos must manually clean up. Documented in the commit message; no automated migration. Future `/proj:jira-sync` runs after the fix will produce correct mappings.
- **Linter shadowing warning**: discarding the tuple element via `_` is the idiomatic Python convention; basedpyright should not flag it.

## Out-of-scope follow-ups

- Audit other `require_project` callers in `jira_sync.py` for similar rebind-shadowing patterns. Tracked separately if any are found.
- One-shot CLI to detect + relocate already-corrupted todos (could be valuable; not required for this fix).
