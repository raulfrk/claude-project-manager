# Jira Hooks — Raw-JSON → Structured `param_mapping` Refactor

**Todo**: 655
**Date**: 2026-04-17
**Status**: design

## Problem

Four `jira-*` hooks in `plugins/jira/.claude-plugin/default-hooks.yaml` use raw
JSON-string templates for `updates_json`:

- `jira-on-todo-update` (line 35)
- `jira-on-todo-complete` (line 26)
- `jira-on-todo-delete` (line 55)
- `jira-on-todo-batch-complete` (line 44, pass-through of prebuilt
  `${jira_updates_json}`)

The hook yaml embeds the full Jira wire-format JSON and interpolates `${...}`
placeholders directly into the string. This is fragile:

- **Template injection** — any source field containing JSON-breaking characters
  (`"`, `\`, newlines, `]`, `}`) corrupts the payload. `${synced_tags}` expands
  to a Python list literal inside a JSON array slot; any label containing
  special chars breaks parsing.
- **Inconsistent with `todoist-on-todo-update`** — the todoist equivalent uses
  a structured `param_mapping` (list of task dicts) because `todoist_update_tasks`
  accepts structured args. Jira hooks look different because
  `jira_update_issues(updates_json: str)` only accepts a pre-serialized JSON
  string.
- **No schema validation at hook-registration time** — a typo in the embedded
  JSON template fails silently at fire time, not at plugin load.
- **Harder to read and diff** — changes touch long string literals rather than
  structured yaml.

The 652 fix (switching `${tags}` → `${synced_tags}` in the `updates_json`
template) landed without addressing the underlying shape, because the scope
was surgical. 655 tracks the cleanup.

## Non-Goals

- **No change to auto-sync posture.** All four hooks keep their existing
  `condition:` gate (`sync.jira.enabled and sync.jira.auto_sync and ...`).
  Jira stays read-only by default; users who haven't set
  `sync.jira.auto_sync: true` in `~/.claude/proj.yaml` see no behavior change.
- **No breaking change to `jira_update_issues`.** The existing raw-JSON tool
  stays registered with unchanged signature for direct callers and existing
  tests.
- **No rework of the router template engine.** This spec adds tool-side
  wrappers, not router-side JSON assembly.

## Architecture

Two new structured wrapper tools on the jira server:

```python
def jira_update_issue_fields(
    key: str,
    summary: str | None = None,
    description: str | None = None,
    priority: str | None = None,
    labels: list[str] | None = None,
    resolution: str | None = None,
) -> str: ...

def jira_update_issues_bulk(
    updates: list[dict],  # [{"key": ..., "summary"?: ..., "resolution"?: ..., ...}, ...]
) -> str: ...
```

Both wrappers construct `updates_json` internally using a shared field→Jira-shape
mapping, then delegate to `_update_issues_core` — extracted from the current
`jira_update_issues` body so all three tools share one implementation.

### Field → Jira-shape mapping (shared)

```python
FIELD_MAP = {
    "summary":     lambda v: v,
    "description": lambda v: v,
    "priority":    lambda v: {"name": v},
    "labels":      lambda v: v,           # list[str] passes through
    "resolution":  lambda v: {"name": v},
}
```

Each wrapper call:

1. Drop any field whose value is `None`.
2. Apply the corresponding lambda to build the `fields` dict.
3. For single: wrap `{"key": key, "fields": fields}` in `{"updates": [...]}`.
   For bulk: map over `updates`, each item → `{"key": ..., "fields": {...}}`,
   wrap in `{"updates": [...]}`.
4. Call `_update_issues_core(updates_json=json.dumps(payload))`.

### Components

- `plugins/jira/server/server/tools/issues.py`
  - Extract the current `jira_update_issues` body into `_update_issues_core(updates_json: str) -> str`
  - `jira_update_issues` becomes a thin wrapper that calls `_update_issues_core`
  - Add `jira_update_issue_fields` (new tool)
  - Add `jira_update_issues_bulk` (new tool)
  - Add internal helper `_build_updates_json(items: list[dict]) -> str` used by both new wrappers

- `plugins/jira/.claude-plugin/default-hooks.yaml`
  - Rewrite 4 hooks to use structured `param_mapping` (shapes below)

- `plugins/proj/server/server/tools/todos.py` (wherever `jira_updates_json` is built
  for `todo_batch_complete`)
  - Add new output field `jira_batch_updates: list[dict]` (each item `{"key": ..., "resolution": "Done"}`)
  - Keep `jira_updates_json` unchanged for backwards-compat (direct callers / older hook cache)

## Hook yaml (after)

```yaml
- id: jira-on-todo-update
  trigger_tool: todo_update
  target_tool: jira_update_issue_fields
  server: jira
  param_mapping:
    key: "${jira_issue_key}"
    summary: "${title}"
    description: "${notes}"
    priority: "${priority}"
    labels: "${synced_tags}"
  blocking: true
  condition: "sync.jira.enabled and sync.jira.auto_sync and todo.jira_issue_key"

- id: jira-on-todo-complete
  trigger_tool: todo_complete
  target_tool: jira_update_issue_fields
  server: jira
  param_mapping:
    key: "${jira_issue_key}"
    resolution: "Done"
  blocking: true
  condition: "sync.jira.enabled and sync.jira.auto_sync and todo.jira_issue_key"

- id: jira-on-todo-delete
  trigger_tool: todo_delete
  target_tool: jira_update_issue_fields
  server: jira
  param_mapping:
    key: "${jira_issue_key}"
    resolution: "Won't Do"
  blocking: true
  condition: "sync.jira.enabled and sync.jira.auto_sync and todo.jira_issue_key"

- id: jira-on-todo-batch-complete
  trigger_tool: todo_complete
  target_tool: jira_update_issues_bulk
  server: jira
  param_mapping:
    updates: "${jira_batch_updates}"
  blocking: true
  condition: "sync.jira.enabled and sync.jira.auto_sync"
  result_condition:
    is_batch: true
```

Hooks that do NOT change: `jira-on-todo-add`, `jira-on-proj-init`,
`jira-on-proj-load`, `jira-full-sync-on-proj-load`. They already use
structured `param_mapping` or call non-update tools.

## Data flow

### Single-issue path

```
todo_update(id, title=..., notes=...)
  → hook router matches jira-on-todo-update
  → resolves template against source dict (synced_tags is list[str])
  → POST to jira server: jira_update_issue_fields(
        key="PROJ-123",
        summary="...", description="...", priority="Medium",
        labels=["bug", "frontend"])
  → wrapper builds payload:
        {"updates": [{"key": "PROJ-123", "fields": {
            "summary": "...",
            "description": "...",
            "priority": {"name": "Medium"},
            "labels": ["bug", "frontend"]}}]}
  → _update_issues_core(json.dumps(payload))
  → returns result
```

### Batch path

```
todo_complete([id1, id2])
  → storage emits jira_batch_updates=[
        {"key": "PROJ-1", "resolution": "Done"},
        {"key": "PROJ-2", "resolution": "Done"}]
  → hook jira-on-todo-batch-complete
  → jira_update_issues_bulk(updates=[...])
  → wrapper maps each item through FIELD_MAP, builds single updates_json
  → _update_issues_core(...)
```

Key benefit: `synced_tags` travels through the router as a typed `list[str]`.
The router's resolve_template handles list-valued template substitution
directly (same as todoist hooks). No JSON string escape issues.

## Error handling

- **Empty `key`** on single wrapper → return `{"error": "key required", "key": ""}`
  without calling `_update_issues_core`.
- **`updates` empty** on bulk wrapper → return
  `{"error": "updates list is empty"}`.
- **Any item missing `key`** on bulk wrapper → return
  `{"error": "each update requires a non-empty key"}`. (Hard error, not skip —
  caller shape is wrong.)
- **All fields `None`** on single wrapper → return
  `{"warning": "no fields to update", "key": "..."}`. Mirrors the existing
  null-safe hook tool pattern (e.g. `trello_add_checklist_item_hook`).
- **Bulk item with only `key` (no updatable fields)** → filter out that item
  before building payload. If all items filter out → return
  `{"warning": "no fields to update in any item", "count": N}` without calling
  `_update_issues_core`. Otherwise dispatch the surviving items and include
  a `skipped_keys: [...]` field in the result alongside the Jira response.
- **Invalid resolution name** → pass through to Jira, 400 propagates as
  existing error shape from `_update_issues_core`. No client-side allowlist —
  Jira is authoritative on valid resolution names per project.
- **Hook dispatch failure** — unchanged. Router logs `ConnectError` and
  continues without dispatch.
- **Bulk partial failure** — `_update_issues_core` already returns per-key
  results; bulk wrapper returns the same shape unchanged.

## Testing

### New files

- `plugins/jira/server/tests/test_update_issue_fields.py`
  - Each field builds correct `fields` dict (summary/description literal,
    priority→`{"name": v}`, labels→list, resolution→`{"name": v}`)
  - `None` fields omitted from serialized JSON
  - Empty `key` → `{"error": ...}`
  - All fields `None` (only `key` set) → `{"warning": ...}`
  - Parity: wrapper output ≡ raw-JSON output for the same inputs
    (regression guard that `_update_issues_core` refactor didn't change semantics)

- `plugins/jira/server/tests/test_update_issues_bulk.py`
  - Multi-item update → single `updates_json` w/ list of length N
  - Mixed field sets across items
  - Empty `updates` list → `{"error": ...}`
  - Item missing `key` → `{"error": ...}`
  - All items have only `key` (no updatable fields) → `{"warning": ..., "count": N}`
  - Mixed: some items have fields, some don't → payload built for the
    former, `skipped_keys` in result for the latter

### Existing files updated

- `plugins/proj/server/tests/test_default_hooks_refs.py`
  - Rewrite `test_jira_on_todo_update_labels_uses_synced_tags` — assert
    structured form (`param_mapping["labels"] == "${synced_tags}"`), drop
    raw-string substring assertions.
  - Add `test_jira_hooks_use_structured_param_mapping` — assert no
    jira hook has `updates_json` key anywhere in `param_mapping` (guards
    against regression to raw-JSON form).
  - Add `test_jira_on_todo_batch_complete_uses_structured_updates` — assert
    `target_tool == "jira_update_issues_bulk"` and
    `param_mapping["updates"] == "${jira_batch_updates}"`.

- `plugins/jira/server/tests/test_issues.py` + `test_contracts_issues.py` +
  `test_issues_null_fields.py`
  - Existing `jira_update_issues(updates_json=...)` tests stay green —
    signature unchanged.

- `plugins/proj/server/tests/` (wherever `todo_batch_complete` is tested)
  - Assert result dict contains both `jira_updates_json` (backwards-compat)
    and new `jira_batch_updates: list[dict]`.

### Coverage posture

- No snapshot tests expected to churn beyond the hook-refs test file.
- No CI config changes.

## Version bumps

- `plugins/jira/plugin.json` + `plugins/jira/.claude-plugin/marketplace.json`
  — minor bump (new tools). Current is post-5.0.0; bump to next minor.
- `plugins/proj/plugin.json` + `plugins/proj/.claude-plugin/marketplace.json`
  — minor bump (`todo_batch_complete` adds new output field).
- `plugins/router/` — no bump; no router changes.

## Rollout

Single PR. No phased migration needed:

1. Land `_update_issues_core` extraction + two new wrapper tools (no hook
   changes yet). All tests green — `jira_update_issues` behavior identical.
2. Land new `jira_batch_updates` field in `todo_batch_complete` output.
3. Land hook yaml rewrites + default-hooks-refs test updates + version bumps.

Steps 1-3 can ship in one commit or split — each is independently safe
because the old hook shape keeps working until yaml is rewritten (tool is
added first, hook is switched second).

No cache-invalidation concern for users on the router plugin — hook registry
auto-syncs from `default-hooks.yaml` at plugin load / `router_sync_tool`.
Older cached entries pointing at `jira_update_issues` with `updates_json`
template still evaluate (tool still registered); new version pushes new
shape.

## Out of scope / follow-ups

- **Deprecate `jira_update_issues`** — could be marked deprecated after all
  internal callers migrate. Not done here to keep PR scope tight; file a
  separate todo if desired.
- **Router-side JSON assembly primitive** — would eliminate the need for
  tool-side wrappers for future raw-JSON targets. Bigger router change,
  out of scope for 655.
- **Escape hardening in `resolve_template`** — defensive option rejected in
  favor of eliminating the raw-JSON string path entirely (this spec).
