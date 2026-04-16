# Flat-Todo Model Server + Hook Changes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Teach the proj MCP server + integration hooks to treat `group:<parent-id>` tags as first-class parent pointers, fix the Jira `parent_key` bug, filter `group:*` from remote labels, and gate flat-only enforcement on `schema_version >= 2` in each project's proj.yaml.

**Architecture:** All behavior changes land inside a single file (`plugins/proj/server/server/tools/todos.py`) plus a new tiny module (`lib/schema_version.py`), plus YAML edits to two integration hook configs (`jira`, `todoist`), plus a one-function extension to the router template DSL (`omit_if_empty` support). No MCP tool additions; `todo_add`'s existing children-only mode is formalized as the canonical flat batch API. Unit tests cover every branch; respx-mocked e2e tests exercise the hook dispatch chain end to end.

**Tech Stack:** Python 3.11+, pytest + pytest-mock + respx, PyYAML, `uv` for dependency/test execution. All tests live under `plugins/<plugin>/server/tests/` and run via `cd plugins/<plugin>/server && uv run pytest -q`.

**Spec:** `docs/superpowers/specs/2026-04-16-flat-todo-model-server-design.md`

**Unblocks:** Todo 636 Phase 1 (installer wizard migration). Must merge to `dev` before 636 Phase 1 work begins.

---

## File Structure

**New files:**

```
plugins/proj/server/server/lib/schema_version.py          # TARGET constant, current(), flat_only()
plugins/proj/server/tests/test_todo_hook_fields_flat.py   # parent resolution + new fields
plugins/proj/server/tests/test_todo_hook_fields_synced_tags.py
plugins/proj/server/tests/test_schema_version.py          # lib unit tests
plugins/proj/server/tests/test_todo_add_schema_version_gate.py
plugins/proj/server/tests/test_default_hooks_refs.py      # YAML smoke tests
plugins/proj/server/tests/test_todo_add_e2e_hooks.py      # respx e2e
plugins/router/server/tests/test_template_omit_if_empty.py
```

**Modified files:**

```
plugins/proj/server/server/tools/todos.py                  # helper extract, synced_tags, parent_jira_issue_key, enforcement
plugins/jira/.claude-plugin/default-hooks.yaml             # labels → synced_tags; parent_key → parent_jira_issue_key w/ omit_if_empty
plugins/todoist/.claude-plugin/default-hooks.yaml          # labels → synced_tags
plugins/router/server/server/lib/template.py               # omit_if_empty support
```

**Not touched** (verified during pre-plan survey):

- `plugins/trello/.claude-plugin/default-hooks.yaml` — no hook currently reads `${tags}` for labels (proj-task label intentionally omitted; next `/proj:trello-sync` adds it). No flip needed.
- `plugins/proj/server/server/lib/storage.py` — `schema_version` read via a new direct-YAML reader inside `schema_version.py`, not layered into `load_meta` (keeps the SQL-backed meta loader untouched).
- `plugins/proj/server/server/tools/` — no new MCP tools; no `todo_add_child` tool exists today, so no gate needed there (the hook file referencing `todo_add_child` trigger is effectively dead and is cleaned up in 636 Phase 2).

---

## Task 1: `_parent_id_from_tag` + `ParentLinks` types

**Files:**
- Modify: `plugins/proj/server/server/tools/todos.py` (add at top, near imports)
- Create: `plugins/proj/server/tests/test_todo_hook_fields_flat.py`

- [ ] **Step 1: Write failing tests**

```python
# plugins/proj/server/tests/test_todo_hook_fields_flat.py
from __future__ import annotations

import logging

import pytest

from server.tools.todos import (
    ParentLinks,
    _parent_id_from_tag,
)


def test_parent_id_from_tag_finds_group():
    assert _parent_id_from_tag(["x", "group:42", "y"]) == "42"


def test_parent_id_from_tag_returns_none_when_absent():
    assert _parent_id_from_tag(["x", "y"]) is None


def test_parent_id_from_tag_returns_none_when_tags_empty():
    assert _parent_id_from_tag([]) is None


def test_parent_id_from_tag_accepts_dotted_ids():
    assert _parent_id_from_tag(["group:475.17"]) == "475.17"


def test_parent_id_from_tag_rejects_empty_id():
    # `group:` with no id is treated as a normal tag, not a parent pointer
    assert _parent_id_from_tag(["group:"]) is None


def test_parent_id_from_tag_uses_first_when_multiple(caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.DEBUG, logger="server.tools.todos")
    assert _parent_id_from_tag(["group:1", "group:2"]) == "1"
    assert any("multiple group" in r.message.lower() for r in caplog.records)


def test_parent_links_default_is_all_none():
    pl = ParentLinks()
    assert pl.todoist_task_id is None
    assert pl.trello_card_id is None
    assert pl.trello_checklist_id is None
    assert pl.jira_issue_key is None


def test_parent_links_is_frozen():
    import dataclasses
    pl = ParentLinks()
    with pytest.raises(dataclasses.FrozenInstanceError):
        pl.todoist_task_id = "x"  # type: ignore[misc]
```

- [ ] **Step 2: Run tests to verify failure**

Run: `cd plugins/proj/server && uv run pytest tests/test_todo_hook_fields_flat.py -v`
Expected: ImportError on `ParentLinks` + `_parent_id_from_tag`.

- [ ] **Step 3: Add types + parser to `todos.py`**

Add near the top of `plugins/proj/server/server/tools/todos.py` (after existing imports, before the first function):

```python
import logging
import re
from dataclasses import dataclass

log = logging.getLogger(__name__)

_GROUP_TAG_RE = re.compile(r"^group:(?P<id>.+)$")


@dataclass(frozen=True)
class ParentLinks:
    todoist_task_id: str | None = None
    trello_card_id: str | None = None
    trello_checklist_id: str | None = None
    jira_issue_key: str | None = None


def _parent_id_from_tag(tags: list[str]) -> str | None:
    """Return the parent id from the first `group:<id>` tag, or None.

    A `group:` tag with no id is ignored (treated as a normal tag).
    Multiple `group:*` tags → first wins + DEBUG log for diagnosability.
    """
    matches = [m for m in (_GROUP_TAG_RE.match(t) for t in tags) if m]
    if not matches:
        return None
    if len(matches) > 1:
        log.debug(
            "todo has multiple group:* tags: %s — using first",
            [m.group(0) for m in matches],
        )
    return matches[0].group("id")
```

Note: the existing `todos.py` may already import `logging` — check before adding a duplicate import. If `logging` is absent, the import block above is correct.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd plugins/proj/server && uv run pytest tests/test_todo_hook_fields_flat.py -v`
Expected: 8 tests pass.

- [ ] **Step 5: Commit**

```bash
git add plugins/proj/server/server/tools/todos.py plugins/proj/server/tests/test_todo_hook_fields_flat.py
git commit -m "feat(proj): ParentLinks + _parent_id_from_tag for group:* resolution (624)"
```

---

## Task 2: `_resolve_parent_for_hooks` helper

**Files:**
- Modify: `plugins/proj/server/server/tools/todos.py`
- Modify: `plugins/proj/server/tests/test_todo_hook_fields_flat.py` (append)

- [ ] **Step 1: Extend tests**

Append to `plugins/proj/server/tests/test_todo_hook_fields_flat.py`:

```python
from server.lib.models import Todo  # existing path — confirm during implementation
from server.tools.todos import _resolve_parent_for_hooks


def _todo(id_: str, **kwargs) -> Todo:
    """Helper: build a minimal Todo with sensible defaults; overridable per test."""
    defaults = {
        "id": id_,
        "title": f"todo {id_}",
        "tags": [],
        "parent": None,
        "children": [],
        "status": "pending",
        "priority": "medium",
        "todoist_task_id": None,
        "trello_card_id": None,
        "trello_checklist_id": None,
        "trello_checklist_item_id": None,
        "jira_issue_key": None,
    }
    defaults.update(kwargs)
    return Todo(**defaults)


def test_resolve_returns_empty_when_no_parent_marker():
    child = _todo("2", tags=[])
    parents = [_todo("1", todoist_task_id="tid")]
    result = _resolve_parent_for_hooks(child, parents + [child])
    assert result == ParentLinks()


def test_resolve_uses_group_tag_over_parent_field():
    # Both set — tag wins
    parent_via_tag = _todo("1", todoist_task_id="FROM-TAG")
    parent_via_field = _todo("9", todoist_task_id="FROM-FIELD")
    child = _todo("2", tags=["group:1"], parent="9")
    result = _resolve_parent_for_hooks(
        child, [parent_via_tag, parent_via_field, child],
    )
    assert result.todoist_task_id == "FROM-TAG"


def test_resolve_falls_back_to_parent_field():
    parent = _todo("9", todoist_task_id="FROM-FIELD")
    child = _todo("2", parent="9")  # no group tag
    result = _resolve_parent_for_hooks(child, [parent, child])
    assert result.todoist_task_id == "FROM-FIELD"


def test_resolve_returns_empty_when_parent_id_unknown():
    child = _todo("2", tags=["group:404"])
    result = _resolve_parent_for_hooks(child, [child])  # no parent in list
    assert result == ParentLinks()


def test_resolve_injects_all_integration_ids():
    parent = _todo(
        "1",
        todoist_task_id="T",
        trello_card_id="R",
        trello_checklist_id="CL",
        jira_issue_key="CPM-1",
    )
    child = _todo("2", tags=["group:1"])
    result = _resolve_parent_for_hooks(child, [parent, child])
    assert result == ParentLinks(
        todoist_task_id="T",
        trello_card_id="R",
        trello_checklist_id="CL",
        jira_issue_key="CPM-1",
    )


def test_resolve_handles_parent_with_no_integrations():
    parent = _todo("1")  # no integration ids
    child = _todo("2", tags=["group:1"])
    result = _resolve_parent_for_hooks(child, [parent, child])
    assert result == ParentLinks()
```

- [ ] **Step 2: Run tests — expect failure**

Run: `cd plugins/proj/server && uv run pytest tests/test_todo_hook_fields_flat.py::test_resolve_uses_group_tag_over_parent_field -v`
Expected: ImportError on `_resolve_parent_for_hooks`.

- [ ] **Step 3: Implement the helper**

Add to `plugins/proj/server/server/tools/todos.py` (immediately after `_parent_id_from_tag`):

```python
def _resolve_parent_for_hooks(todo: Todo, todos: list[Todo]) -> ParentLinks:
    """Resolve parent integration IDs for hook dispatch.

    Resolution order: `group:<id>` tag wins over `todo.parent` when both set.
    Returns empty ParentLinks if no parent marker, or parent not found, or
    parent has no integration IDs.
    """
    parent_id = _parent_id_from_tag(todo.tags) or todo.parent
    if not parent_id:
        return ParentLinks()
    parent = next((t for t in todos if t.id == parent_id), None)
    if parent is None:
        return ParentLinks()
    return ParentLinks(
        todoist_task_id=parent.todoist_task_id,
        trello_card_id=parent.trello_card_id,
        trello_checklist_id=parent.trello_checklist_id,
        jira_issue_key=parent.jira_issue_key,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd plugins/proj/server && uv run pytest tests/test_todo_hook_fields_flat.py -v`
Expected: 14 tests pass (8 from Task 1 + 6 new).

- [ ] **Step 5: Commit**

```bash
git add plugins/proj/server/server/tools/todos.py plugins/proj/server/tests/test_todo_hook_fields_flat.py
git commit -m "feat(proj): _resolve_parent_for_hooks unifies tag + parent-field resolution (624)"
```

---

## Task 3: Wire helper into `_todo_hook_fields` + emit `parent_jira_issue_key`

**Files:**
- Modify: `plugins/proj/server/server/tools/todos.py` (replace lines 172–180)
- Modify: `plugins/proj/server/tests/test_todo_hook_fields_flat.py` (append)

- [ ] **Step 1: Extend tests for injected fields**

Append to `plugins/proj/server/tests/test_todo_hook_fields_flat.py`:

```python
from server.tools.todos import _todo_hook_fields
from server.lib.models import ProjectMeta  # adjust path if different


def _meta() -> ProjectMeta:
    """Minimal ProjectMeta for hook-field tests — adjust constructor args
    to the real ProjectMeta signature during implementation."""
    return ProjectMeta(
        trello_card_id=None,
        todoist_project_id=None,
        jira_issue_key=None,
    )


def test_hook_fields_flat_child_injects_todoist_id():
    parent = _todo("1", todoist_task_id="PAR-T")
    child = _todo("2", tags=["group:1"])
    fields = _todo_hook_fields(
        child, _meta(), name="demo", todos=[parent, child],
    )
    assert fields["parent_todoist_task_id"] == "PAR-T"


def test_hook_fields_flat_child_injects_jira_key():
    parent = _todo("1", jira_issue_key="CPM-100")
    child = _todo("2", tags=["group:1"])
    fields = _todo_hook_fields(
        child, _meta(), name="demo", todos=[parent, child],
    )
    assert fields["parent_jira_issue_key"] == "CPM-100"


def test_hook_fields_flat_child_injects_trello_card_id():
    parent = _todo("1", trello_card_id="CARD-1")
    child = _todo("2", tags=["group:1"])
    fields = _todo_hook_fields(
        child, _meta(), name="demo", todos=[parent, child],
    )
    assert fields["parent_trello_card_id"] == "CARD-1"


def test_hook_fields_top_level_has_no_parent_fields():
    todo = _todo("1")
    fields = _todo_hook_fields(todo, _meta(), name="demo", todos=[todo])
    assert "parent_todoist_task_id" not in fields
    assert "parent_jira_issue_key" not in fields
    assert "parent_trello_card_id" not in fields
    assert "parent_trello_checklist_id" not in fields


def test_hook_fields_legacy_nested_child_still_works():
    parent = _todo("9", todoist_task_id="T", jira_issue_key="CPM-9")
    child = _todo("9.1", parent="9")  # legacy — no group tag
    fields = _todo_hook_fields(
        child, _meta(), name="demo", todos=[parent, child],
    )
    assert fields["parent_todoist_task_id"] == "T"
    assert fields["parent_jira_issue_key"] == "CPM-9"
```

- [ ] **Step 2: Run — expect failure**

Run: `cd plugins/proj/server && uv run pytest tests/test_todo_hook_fields_flat.py -v`
Expected: last 5 tests fail (`parent_jira_issue_key` not emitted; group-tag resolution not wired yet).

- [ ] **Step 3: Replace the parent-resolution block in `_todo_hook_fields`**

In `plugins/proj/server/server/tools/todos.py`, find the existing block at lines 172–180:

```python
    # Resolve parent's Todoist task ID for child todos so hooks can set parentId.
    if todo.parent and todos:
        parent_todo = next((t for t in todos if t.id == todo.parent), None)
        if parent_todo and parent_todo.todoist_task_id:
            fields["parent_todoist_task_id"] = parent_todo.todoist_task_id
        if parent_todo and parent_todo.trello_card_id:
            fields["parent_trello_card_id"] = parent_todo.trello_card_id
        if parent_todo and parent_todo.trello_checklist_id:
            fields["parent_trello_checklist_id"] = parent_todo.trello_checklist_id
```

Replace it with:

```python
    # Resolve parent integration IDs for hook dispatch.
    # Supports both legacy nested model (todo.parent) and flat model (group:<id> tag).
    if todos:
        parent_links = _resolve_parent_for_hooks(todo, todos)
        if parent_links.todoist_task_id:
            fields["parent_todoist_task_id"] = parent_links.todoist_task_id
        if parent_links.trello_card_id:
            fields["parent_trello_card_id"] = parent_links.trello_card_id
        if parent_links.trello_checklist_id:
            fields["parent_trello_checklist_id"] = parent_links.trello_checklist_id
        if parent_links.jira_issue_key:
            fields["parent_jira_issue_key"] = parent_links.jira_issue_key
```

- [ ] **Step 4: Run tests**

Run: `cd plugins/proj/server && uv run pytest tests/test_todo_hook_fields_flat.py -v`
Expected: all 19 tests pass.

Run the existing proj test suite to catch regressions:

Run: `cd plugins/proj/server && uv run pytest -q`
Expected: all pass. If any pre-existing test asserted the absence of `parent_jira_issue_key`, update it — the field is newly available.

- [ ] **Step 5: Commit**

```bash
git add plugins/proj/server/server/tools/todos.py plugins/proj/server/tests/test_todo_hook_fields_flat.py
git commit -m "feat(proj): _todo_hook_fields emits parent_jira_issue_key + group-tag resolution (624)"
```

---

## Task 4: `synced_tags` field

**Files:**
- Modify: `plugins/proj/server/server/tools/todos.py` (one line in `_todo_hook_fields`)
- Create: `plugins/proj/server/tests/test_todo_hook_fields_synced_tags.py`

- [ ] **Step 1: Write failing tests**

```python
# plugins/proj/server/tests/test_todo_hook_fields_synced_tags.py
from __future__ import annotations

from server.lib.models import ProjectMeta, Todo
from server.tools.todos import _todo_hook_fields


def _todo(**kwargs) -> Todo:
    defaults = {
        "id": "1",
        "title": "x",
        "tags": [],
        "parent": None,
        "children": [],
        "status": "pending",
        "priority": "medium",
        "todoist_task_id": None,
        "trello_card_id": None,
        "trello_checklist_id": None,
        "trello_checklist_item_id": None,
        "jira_issue_key": None,
    }
    defaults.update(kwargs)
    return Todo(**defaults)


def _meta() -> ProjectMeta:
    return ProjectMeta(trello_card_id=None, todoist_project_id=None, jira_issue_key=None)


def test_synced_tags_strips_group_prefix():
    todo = _todo(tags=["manual", "group:5", "auto-added"])
    fields = _todo_hook_fields(todo, _meta(), name="demo", todos=[todo])
    assert fields["synced_tags"] == ["manual", "auto-added"]


def test_synced_tags_preserves_order():
    todo = _todo(tags=["z", "group:5", "a", "m"])
    fields = _todo_hook_fields(todo, _meta(), name="demo", todos=[todo])
    assert fields["synced_tags"] == ["z", "a", "m"]


def test_synced_tags_empty_when_only_group_tags():
    todo = _todo(tags=["group:5"])
    fields = _todo_hook_fields(todo, _meta(), name="demo", todos=[todo])
    assert fields["synced_tags"] == []


def test_synced_tags_unchanged_when_no_group_prefix():
    todo = _todo(tags=["a", "b"])
    fields = _todo_hook_fields(todo, _meta(), name="demo", todos=[todo])
    assert fields["synced_tags"] == ["a", "b"]


def test_raw_tags_field_still_includes_group_tag():
    todo = _todo(tags=["manual", "group:5"])
    fields = _todo_hook_fields(todo, _meta(), name="demo", todos=[todo])
    assert fields["tags"] == ["manual", "group:5"]  # raw list preserved


def test_synced_tags_empty_list_for_todo_with_no_tags():
    todo = _todo(tags=[])
    fields = _todo_hook_fields(todo, _meta(), name="demo", todos=[todo])
    assert fields["synced_tags"] == []
```

- [ ] **Step 2: Run — expect failure**

Run: `cd plugins/proj/server && uv run pytest tests/test_todo_hook_fields_synced_tags.py -v`
Expected: all fail with `KeyError: 'synced_tags'`.

- [ ] **Step 3: Add `synced_tags` to `_todo_hook_fields`**

In `plugins/proj/server/server/tools/todos.py`, inside `_todo_hook_fields`, inside the `fields` dict literal (before the `return fields` line), add:

```python
    fields["synced_tags"] = [t for t in todo.tags if not t.startswith("group:")]
```

Place this line after the parent-links block (so raw `tags` stays initialized first, and the derived field computes after).

- [ ] **Step 4: Run tests**

Run: `cd plugins/proj/server && uv run pytest tests/test_todo_hook_fields_synced_tags.py -v`
Expected: 6 tests pass.

Run: `cd plugins/proj/server && uv run pytest -q`
Expected: no regressions.

- [ ] **Step 5: Commit**

```bash
git add plugins/proj/server/server/tools/todos.py plugins/proj/server/tests/test_todo_hook_fields_synced_tags.py
git commit -m "feat(proj): emit synced_tags (tags minus group:* prefix) for remote labels (624)"
```

---

## Task 5: Router template DSL — `omit_if_empty` support

**Files:**
- Modify: `plugins/router/server/server/lib/template.py`
- Create: `plugins/router/server/tests/test_template_omit_if_empty.py`

- [ ] **Step 1: Write failing tests**

```python
# plugins/router/server/tests/test_template_omit_if_empty.py
from __future__ import annotations

from server.lib.template import resolve_mapping


def test_plain_template_still_resolves():
    mapping = {"name": "${title}", "priority": "${priority}"}
    source = {"title": "hi", "priority": "high"}
    assert resolve_mapping(mapping, source) == {"name": "hi", "priority": "high"}


def test_omit_if_empty_removes_key_when_value_empty():
    mapping = {
        "name": "${title}",
        "parent_key": {"value": "${parent}", "omit_if_empty": True},
    }
    source = {"title": "hi", "parent": ""}
    result = resolve_mapping(mapping, source)
    assert "parent_key" not in result
    assert result["name"] == "hi"


def test_omit_if_empty_removes_key_when_value_missing():
    mapping = {
        "parent_key": {"value": "${parent}", "omit_if_empty": True},
    }
    source = {}  # parent absent entirely
    assert resolve_mapping(mapping, source) == {}


def test_omit_if_empty_removes_key_when_value_none():
    mapping = {
        "parent_key": {"value": "${parent}", "omit_if_empty": True},
    }
    source = {"parent": None}
    assert resolve_mapping(mapping, source) == {}


def test_omit_if_empty_keeps_key_when_value_present():
    mapping = {
        "parent_key": {"value": "${parent}", "omit_if_empty": True},
    }
    source = {"parent": "CPM-100"}
    assert resolve_mapping(mapping, source) == {"parent_key": "CPM-100"}


def test_omit_if_empty_false_keeps_empty_value():
    mapping = {
        "parent_key": {"value": "${parent}", "omit_if_empty": False},
    }
    source = {"parent": ""}
    assert resolve_mapping(mapping, source) == {"parent_key": ""}


def test_dict_without_omit_if_empty_treated_as_plain_dict():
    # Backward compat: nested dicts without the omit_if_empty key still work
    mapping = {"outer": {"inner": "${x}"}}
    source = {"x": "y"}
    assert resolve_mapping(mapping, source) == {"outer": {"inner": "y"}}
```

- [ ] **Step 2: Run — expect failure**

Run: `cd plugins/router/server && uv run pytest tests/test_template_omit_if_empty.py -v`
Expected: tests that exercise `omit_if_empty` fail (feature not wired).

- [ ] **Step 3: Extend `resolve_mapping` + add helper**

In `plugins/router/server/server/lib/template.py`, locate `resolve_mapping` (approximately lines 79–87). Replace with:

```python
def resolve_mapping(
    param_mapping: dict[str, JsonValue],
    source: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    """Resolve every value in *param_mapping* against *source*.

    Dict values of the shape ``{"value": ..., "omit_if_empty": True}`` are
    resolved specially: when the resolved value is falsy (None, "", 0, [], {}),
    the key is omitted from the output dict. All other values resolve normally.
    """
    out: dict[str, JsonValue] = {}
    for key, value in param_mapping.items():
        if _is_omit_if_empty_directive(value):
            resolved = resolve_value(value["value"], source)
            if _is_empty(resolved):
                continue
            out[key] = resolved
        else:
            out[key] = resolve_value(value, source)
    return out


def _is_omit_if_empty_directive(value: JsonValue) -> bool:
    return (
        isinstance(value, dict)
        and "value" in value
        and value.get("omit_if_empty") is True
    )


def _is_empty(value: JsonValue) -> bool:
    if value is None:
        return True
    if isinstance(value, (str, list, dict)):
        return len(value) == 0
    if isinstance(value, (int, float)):
        return value == 0
    return False
```

- [ ] **Step 4: Run tests**

Run: `cd plugins/router/server && uv run pytest tests/test_template_omit_if_empty.py -v`
Expected: 7 tests pass.

Run the full router test suite to catch regressions:

Run: `cd plugins/router/server && uv run pytest -q`
Expected: no regressions. Any pre-existing test that relied on dicts being resolved naively without the directive check continues to pass because `_is_omit_if_empty_directive` gates on both `value` key presence AND `omit_if_empty: True`.

- [ ] **Step 5: Commit**

```bash
git add plugins/router/server/server/lib/template.py plugins/router/server/tests/test_template_omit_if_empty.py
git commit -m "feat(router/template): add omit_if_empty directive for conditional param resolution (624)"
```

---

## Task 6: Jira hook fix — `parent_key` + `labels`

**Files:**
- Modify: `plugins/jira/.claude-plugin/default-hooks.yaml`
- Create: `plugins/proj/server/tests/test_default_hooks_refs.py`

- [ ] **Step 1: Write failing hook-config smoke test**

```python
# plugins/proj/server/tests/test_default_hooks_refs.py
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).parents[4]  # adjust if test layout differs

JIRA_HOOKS = REPO_ROOT / "plugins" / "jira" / ".claude-plugin" / "default-hooks.yaml"
TODOIST_HOOKS = REPO_ROOT / "plugins" / "todoist" / ".claude-plugin" / "default-hooks.yaml"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def _hook(hooks_doc: dict, hook_id: str) -> dict:
    for h in hooks_doc.get("hooks", []):
        if h.get("id") == hook_id:
            return h
    pytest.fail(f"hook {hook_id} not found in {hooks_doc.get('hooks', [])}")


def test_jira_on_todo_add_labels_uses_synced_tags():
    hook = _hook(_load(JIRA_HOOKS), "jira-on-todo-add")
    assert hook["param_mapping"]["labels"] == "${synced_tags}"


def test_jira_on_todo_add_parent_key_references_parent_jira_issue_key():
    hook = _hook(_load(JIRA_HOOKS), "jira-on-todo-add")
    pk = hook["param_mapping"]["parent_key"]
    assert isinstance(pk, dict)
    assert pk["value"] == "${parent_jira_issue_key}"
    assert pk["omit_if_empty"] is True


def test_jira_on_todo_add_condition_unchanged():
    hook = _hook(_load(JIRA_HOOKS), "jira-on-todo-add")
    assert "sync.jira.enabled" in hook["condition"]
    assert "sync.jira.auto_sync" in hook["condition"]
    assert "project.jira_issue_key" in hook["condition"]
```

- [ ] **Step 2: Run — expect failure**

Run: `cd plugins/proj/server && uv run pytest tests/test_default_hooks_refs.py -v`
Expected: tests fail — `labels` still `${tags}`, `parent_key` still `${jira_issue_key}` (string not dict).

- [ ] **Step 3: Edit Jira hook config**

In `plugins/jira/.claude-plugin/default-hooks.yaml`, find the `jira-on-todo-add` hook entry. Update the `param_mapping`:

```yaml
- id: jira-on-todo-add
  trigger_tool: todo_add
  target_server: jira
  target_tool: jira_create_issue
  condition: "sync.jira.enabled and sync.jira.auto_sync and project.jira_issue_key"
  param_mapping:
    project_key: "${jira_project_key}"
    summary: "${title}"
    description: "${notes}"
    priority: "${priority}"
    labels: "${synced_tags}"
    parent_key:
      value: "${parent_jira_issue_key}"
      omit_if_empty: true
```

Key changes:
- `labels: "${tags}"` → `labels: "${synced_tags}"`
- `parent_key: "${jira_issue_key}"` → dict form with `parent_jira_issue_key` and `omit_if_empty: true`

- [ ] **Step 4: Run tests**

Run: `cd plugins/proj/server && uv run pytest tests/test_default_hooks_refs.py -v`
Expected: 3 tests pass.

Full plugin test sweep:

Run: `cd plugins/jira/server && uv run pytest -q`
Expected: no regressions. If there's a Jira hook-fire test that asserts old behavior (`parent_key == ""` on top-level), update it — new behavior is `parent_key` absent on top-level.

- [ ] **Step 5: Commit**

```bash
git add plugins/jira/.claude-plugin/default-hooks.yaml plugins/proj/server/tests/test_default_hooks_refs.py
git commit -m "fix(jira): parent_key uses parent_jira_issue_key + omit_if_empty; labels use synced_tags (624)"
```

---

## Task 7: Todoist hook fix — `labels`

**Files:**
- Modify: `plugins/todoist/.claude-plugin/default-hooks.yaml`
- Modify: `plugins/proj/server/tests/test_default_hooks_refs.py` (append)

- [ ] **Step 1: Append smoke test**

Append to `plugins/proj/server/tests/test_default_hooks_refs.py`:

```python
def test_todoist_on_todo_add_labels_uses_synced_tags():
    hook = _hook(_load(TODOIST_HOOKS), "todoist-on-todo-add")
    # The Todoist hook maps over a list of tasks; labels is inside each task entry.
    tasks = hook["param_mapping"]["tasks"]
    assert isinstance(tasks, list)
    assert tasks[0]["labels"] == "${synced_tags}"
```

- [ ] **Step 2: Run — expect failure**

Run: `cd plugins/proj/server && uv run pytest tests/test_default_hooks_refs.py::test_todoist_on_todo_add_labels_uses_synced_tags -v`
Expected: fails — labels still `${tags}`.

- [ ] **Step 3: Edit Todoist hook**

In `plugins/todoist/.claude-plugin/default-hooks.yaml`, find the `todoist-on-todo-add` hook. Update the `labels` field inside `tasks[0]`:

```yaml
- id: todoist-on-todo-add
  trigger_tool: todo_add
  target_server: todoist
  target_tool: todoist_add_tasks
  condition: "sync.todoist.enabled and sync.todoist.auto_sync and project.todoist_project_id"
  param_mapping:
    tasks:
      - content: "${title}"
        projectId: "${todoist_project_id}"
        parentId: "${parent_todoist_task_id}"
        priority: "${priority}"
        labels: "${synced_tags}"
```

Change: `labels: "${tags}"` → `labels: "${synced_tags}"`.

- [ ] **Step 4: Run tests**

Run: `cd plugins/proj/server && uv run pytest tests/test_default_hooks_refs.py -v`
Expected: 4 tests pass.

Run: `cd plugins/todoist/server && uv run pytest -q`
Expected: no regressions.

- [ ] **Step 5: Commit**

```bash
git add plugins/todoist/.claude-plugin/default-hooks.yaml plugins/proj/server/tests/test_default_hooks_refs.py
git commit -m "feat(todoist): labels use synced_tags (drop group:* noise in Todoist) (624)"
```

---

## Task 8: `schema_version` library module

**Files:**
- Create: `plugins/proj/server/server/lib/schema_version.py`
- Create: `plugins/proj/server/tests/test_schema_version.py`

- [ ] **Step 1: Write failing tests**

```python
# plugins/proj/server/tests/test_schema_version.py
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from server.lib import schema_version


@pytest.fixture
def fake_cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Minimal ProjConfig shim with a tracking_dir pointing at tmp_path."""
    from server.lib.models import ProjConfig

    # NOTE: adjust ProjConfig args to the real constructor signature.
    cfg = ProjConfig(tracking_dir=str(tmp_path))
    return cfg


def _write_proj_yaml(tracking_dir: Path, project: str, data: dict) -> None:
    proj_dir = tracking_dir / project
    proj_dir.mkdir(parents=True, exist_ok=True)
    (proj_dir / "proj.yaml").write_text(yaml.safe_dump(data))


def test_target_constant_is_2():
    assert schema_version.TARGET == 2


def test_current_returns_1_when_field_absent(fake_cfg, tmp_path):
    _write_proj_yaml(tmp_path, "demo", {"name": "demo"})
    assert schema_version.current(fake_cfg, "demo") == 1


def test_current_returns_int_value(fake_cfg, tmp_path):
    _write_proj_yaml(tmp_path, "demo", {"name": "demo", "schema_version": 2})
    assert schema_version.current(fake_cfg, "demo") == 2


def test_current_returns_1_when_proj_yaml_missing(fake_cfg):
    assert schema_version.current(fake_cfg, "nope") == 1


def test_current_returns_1_when_field_malformed(fake_cfg, tmp_path):
    _write_proj_yaml(tmp_path, "demo", {"schema_version": "not-a-number"})
    assert schema_version.current(fake_cfg, "demo") == 1


def test_current_returns_1_when_yaml_corrupted(fake_cfg, tmp_path):
    proj_dir = tmp_path / "demo"
    proj_dir.mkdir()
    (proj_dir / "proj.yaml").write_text("not: [valid")
    assert schema_version.current(fake_cfg, "demo") == 1


def test_flat_only_false_when_below_target(fake_cfg, tmp_path):
    _write_proj_yaml(tmp_path, "demo", {"schema_version": 1})
    assert schema_version.flat_only(fake_cfg, "demo") is False


def test_flat_only_true_when_at_target(fake_cfg, tmp_path):
    _write_proj_yaml(tmp_path, "demo", {"schema_version": 2})
    assert schema_version.flat_only(fake_cfg, "demo") is True


def test_flat_only_true_when_above_target(fake_cfg, tmp_path):
    _write_proj_yaml(tmp_path, "demo", {"schema_version": 99})
    assert schema_version.flat_only(fake_cfg, "demo") is True


def test_no_caching_between_calls(fake_cfg, tmp_path):
    _write_proj_yaml(tmp_path, "demo", {"schema_version": 1})
    assert schema_version.flat_only(fake_cfg, "demo") is False
    _write_proj_yaml(tmp_path, "demo", {"schema_version": 2})
    # Second call must pick up the new value — no cache.
    assert schema_version.flat_only(fake_cfg, "demo") is True
```

- [ ] **Step 2: Run — expect failure**

Run: `cd plugins/proj/server && uv run pytest tests/test_schema_version.py -v`
Expected: ImportError on `schema_version`.

- [ ] **Step 3: Implement the module**

```python
# plugins/proj/server/server/lib/schema_version.py
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from .models import ProjConfig

log = logging.getLogger(__name__)

TARGET = 2


def current(cfg: ProjConfig, project_name: str) -> int:
    """Return the per-project schema_version. Missing / unreadable → 1.

    Reads `proj.yaml` directly rather than going through the SQL-backed
    meta loader because `schema_version` is the migration gate that the
    installer wizard writes before any other storage operations succeed
    for migrated projects. Keeping it out of SQL also avoids needing a
    SQL schema migration for this one field.
    """
    path = Path(cfg.tracking_dir) / project_name / "proj.yaml"
    try:
        raw = path.read_text()
    except FileNotFoundError:
        return 1
    try:
        data = yaml.safe_load(raw) or {}
    except yaml.YAMLError:
        log.warning("proj.yaml for %s is corrupted; treating as schema_version=1", project_name)
        return 1
    if not isinstance(data, dict):
        return 1
    v = data.get("schema_version")
    if v is None:
        return 1
    try:
        return int(v)
    except (TypeError, ValueError):
        return 1


def flat_only(cfg: ProjConfig, project_name: str) -> bool:
    return current(cfg, project_name) >= TARGET
```

- [ ] **Step 4: Run tests**

Run: `cd plugins/proj/server && uv run pytest tests/test_schema_version.py -v`
Expected: 10 tests pass.

- [ ] **Step 5: Commit**

```bash
git add plugins/proj/server/server/lib/schema_version.py plugins/proj/server/tests/test_schema_version.py
git commit -m "feat(proj/lib): schema_version module reads per-project proj.yaml (624)"
```

---

## Task 9: Enforcement gate in `todo_add` (truth-table rejection)

**Files:**
- Modify: `plugins/proj/server/server/tools/todos.py`
- Create: `plugins/proj/server/tests/test_todo_add_schema_version_gate.py`

- [ ] **Step 1: Write failing truth-table tests**

```python
# plugins/proj/server/tests/test_todo_add_schema_version_gate.py
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from server.tools.todos import todo_add


# ---- Fixtures ----


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Set up a project at tmp_path and make todo_add target it.

    Adjust monkeypatches to match the actual project-loading entry point
    (e.g. require_project / ProjConfig resolution) used in existing tests.
    """
    tracking = tmp_path / "tracking"
    project_dir = tracking / "demo"
    project_dir.mkdir(parents=True)
    (project_dir / "proj.yaml").write_text(yaml.safe_dump({"name": "demo"}))
    # Empty todos + data.db will be created by project init — or mock.
    # This fixture pattern MUST match whatever existing test_todos.py does.
    monkeypatch.setenv("HOME", str(tmp_path))
    return project_dir


def _set_schema_version(project_dir: Path, v: int) -> None:
    path = project_dir / "proj.yaml"
    data = yaml.safe_load(path.read_text()) or {}
    data["schema_version"] = v
    path.write_text(yaml.safe_dump(data))


# ---- Legacy mode (schema_version=1): everything allowed ----


def test_legacy_mode_allows_single_child_with_parent(project):
    _set_schema_version(project, 1)
    # First create a parent
    todo_add(title="parent", project_name="demo")
    # Then create child with parent= — must succeed in legacy mode
    result = json.loads(todo_add(title="child", parent="1", project_name="demo"))
    assert result.get("error") is None
    assert result.get("id") == "1.1"


def test_legacy_mode_allows_batch_children(project):
    _set_schema_version(project, 1)
    todo_add(title="parent", project_name="demo")
    result = json.loads(
        todo_add(
            title="",
            parent="1",
            children=json.dumps([{"title": "a"}, {"title": "b"}]),
            project_name="demo",
        ),
    )
    assert result.get("error") is None
    assert len(result.get("children", [])) == 2


# ---- Flat mode (schema_version=2): nested args rejected ----


def test_flat_mode_rejects_single_child_with_parent(project):
    _set_schema_version(project, 2)
    todo_add(title="parent", project_name="demo")
    result = json.loads(todo_add(title="child", parent="1", project_name="demo"))
    assert "error" in result
    assert "nested mode disabled" in result["error"]
    assert "schema_version" in result["error"]
    assert "group:" in result["error"]  # actionable hint


def test_flat_mode_allows_single_flat_child_via_tag(project):
    _set_schema_version(project, 2)
    todo_add(title="parent", project_name="demo")
    result = json.loads(
        todo_add(title="child", tags=["group:1"], project_name="demo"),
    )
    assert result.get("error") is None
    assert "group:1" in result.get("tags", [])
    assert result.get("parent") is None


def test_flat_mode_allows_batch_via_children_only_mode(project):
    _set_schema_version(project, 2)
    todo_add(title="parent", project_name="demo")
    result = json.loads(
        todo_add(
            title="",
            parent="1",
            children=json.dumps([{"title": "a"}, {"title": "b"}]),
            project_name="demo",
        ),
    )
    assert result.get("error") is None
    # See Task 10 for the tag auto-application behavior.


def test_flat_mode_rejects_title_plus_parent_plus_children(project):
    """Ambiguous: title non-empty means 'create root too', but parent means
    'nest it' — in flat mode this shape is not allowed."""
    _set_schema_version(project, 2)
    todo_add(title="parent", project_name="demo")
    result = json.loads(
        todo_add(
            title="root_too",
            parent="1",
            children=json.dumps([{"title": "a"}]),
            project_name="demo",
        ),
    )
    assert "error" in result
    assert "nested mode disabled" in result["error"]


def test_flat_mode_allows_top_level_with_no_parent(project):
    _set_schema_version(project, 2)
    result = json.loads(todo_add(title="lone", project_name="demo"))
    assert result.get("error") is None
    assert result.get("parent") is None


def test_gate_reads_schema_version_fresh_each_call(project):
    _set_schema_version(project, 1)
    r1 = json.loads(todo_add(title="a", parent="1", project_name="demo"))
    # Allowed under v1 (if parent exists — depends on ordering; adjust fixture
    # to create parent="1" first in a shared setup). Focus here is on ensuring
    # a version bump is observed in the next call.
    _set_schema_version(project, 2)
    r2 = json.loads(todo_add(title="b", parent="1", project_name="demo"))
    assert "error" in r2
```

- [ ] **Step 2: Run — expect failure**

Run: `cd plugins/proj/server && uv run pytest tests/test_todo_add_schema_version_gate.py -v`
Expected: flat-mode tests fail (no gate yet).

- [ ] **Step 3: Add enforcement helper + call site**

In `plugins/proj/server/server/tools/todos.py`, add the helper near the other private helpers:

```python
from server.lib import schema_version

_FLAT_MODE_ERROR = (
    "todo_add: nested mode disabled (project schema_version >= 2).\n"
    '  * single child:  todo_add(title="...", tags=["group:<parent-id>"])\n'
    '  * batch:         todo_add(title="", parent="<parent-id>", children=[...])'
)


def _enforce_flat_args(
    *,
    title: str,
    parent: str | None,
    children_list: list,
) -> None:
    """Raise ValueError when arg shape is disallowed under schema_version >= 2.

    Allowed post-enforcement:
      * title non-empty, parent None, children empty     → flat top-level
      * title empty,     parent set,  children non-empty → canonical batch path
    Rejected:
      * title non-empty, parent set                      → use tags=["group:<id>"]
      * title non-empty, parent set, children non-empty  → ambiguous
    """
    if parent and title and title.strip():
        raise ValueError(_FLAT_MODE_ERROR)
```

In `todo_add`, at the top of the function body (before the existing `_child_specs_raw` line), add:

```python
    # Schema-version-gated flat-only enforcement (todo 624).
    cfg = require_config()
    _project_name = _resolve_project_name(cfg, project_name)
    _child_specs_for_gate = json.loads(children) if children and children.strip() else []
    if schema_version.flat_only(cfg, _project_name):
        try:
            _enforce_flat_args(
                title=title,
                parent=parent,
                children_list=_child_specs_for_gate,
            )
        except ValueError as e:
            return json.dumps({"error": str(e)})
```

**Notes for implementer:**
- `require_config()` is already used elsewhere in `todos.py`; reuse.
- `_resolve_project_name` may not exist under that exact name; use whatever the file already uses to normalize `project_name` against `cfg`. Look for a call like `resolve_project_name`, `require_project`, or inline `project_name or cfg.default_project`. If the resolution normally returns a string-or-result union, adapt the assignment.
- The `_child_specs_for_gate` pre-parse is a throwaway — `todo_add` parses `children` again below. Fine to duplicate because `children` is small JSON and this avoids refactoring the main flow.
- Return `json.dumps({"error": ...})` matches the existing error-return convention in `todo_add` (search for other `return json.dumps({"error"` in the function).

- [ ] **Step 4: Run tests**

Run: `cd plugins/proj/server && uv run pytest tests/test_todo_add_schema_version_gate.py -v`
Expected: all tests pass.

Run: `cd plugins/proj/server && uv run pytest -q`
Expected: no regressions.

- [ ] **Step 5: Commit**

```bash
git add plugins/proj/server/server/tools/todos.py plugins/proj/server/tests/test_todo_add_schema_version_gate.py
git commit -m "feat(proj): schema_version-gated flat-only enforcement in todo_add (624)"
```

---

## Task 10: Batch-path auto-tagging post-enforcement

**Files:**
- Modify: `plugins/proj/server/server/tools/todos.py` (`_batch_add_children`)
- Modify: `plugins/proj/server/tests/test_todo_add_schema_version_gate.py` (append)

When `schema_version >= 2`, the batch path (`todo_add(title="", parent=X, children=[...])`) should set `group:X` on each child's tags instead of setting the `parent` field.

- [ ] **Step 1: Append failing tests**

Append to `plugins/proj/server/tests/test_todo_add_schema_version_gate.py`:

```python
def test_flat_mode_batch_path_auto_tags_children(project):
    _set_schema_version(project, 2)
    todo_add(title="parent", project_name="demo")
    result = json.loads(
        todo_add(
            title="",
            parent="1",
            children=json.dumps([{"title": "child_a"}, {"title": "child_b"}]),
            project_name="demo",
        ),
    )
    assert result.get("error") is None
    created = result.get("children", [])
    assert len(created) == 2
    for child in created:
        assert "group:1" in child.get("tags", [])
        assert child.get("parent") is None


def test_flat_mode_batch_path_dedups_existing_group_tag(project):
    _set_schema_version(project, 2)
    todo_add(title="parent", project_name="demo")
    result = json.loads(
        todo_add(
            title="",
            parent="1",
            children=json.dumps([
                {"title": "c", "tags": ["group:1", "keep"]},
            ]),
            project_name="demo",
        ),
    )
    created = result["children"]
    tags = created[0]["tags"]
    assert tags.count("group:1") == 1
    assert "keep" in tags


def test_legacy_mode_batch_path_sets_parent_field(project):
    _set_schema_version(project, 1)
    todo_add(title="parent", project_name="demo")
    result = json.loads(
        todo_add(
            title="",
            parent="1",
            children=json.dumps([{"title": "c"}]),
            project_name="demo",
        ),
    )
    created = result["children"]
    assert created[0]["parent"] == "1"
    # No auto-tag in legacy mode
    assert "group:1" not in created[0].get("tags", [])
```

- [ ] **Step 2: Run — expect failure**

Run: `cd plugins/proj/server && uv run pytest tests/test_todo_add_schema_version_gate.py::test_flat_mode_batch_path_auto_tags_children -v`
Expected: fail — children created with `parent` field, not `group:` tag.

- [ ] **Step 3: Modify `_batch_add_children` to auto-tag in flat mode**

In `plugins/proj/server/server/tools/todos.py`, find `_batch_add_children` (starting line 359). Add a `flat` keyword argument and use it to decide between `parent` field and `group:` tag.

Change the signature:

```python
def _batch_add_children(
    cfg: ProjConfig,
    name: str,
    parent_todo: Todo,
    child_specs: list[dict[str, JsonValue]],
    blocking_pairs: list[list[int]],
    today: str,
    todos: list[Todo],
    meta: ProjectMeta,
    *,
    flat: bool = False,
) -> str:
```

Inside the function, find the spot where each child is constructed (look for `Todo(` or `parent=parent_todo.id` — grep within the function body). Replace the parent-field assignment with a conditional:

```python
    # (inside the per-spec loop)
    child_tags = list(spec.get("tags", []) or [])
    if flat:
        group_tag = f"group:{parent_todo.id}"
        if group_tag not in child_tags:
            child_tags.append(group_tag)
        child_parent = None
    else:
        child_parent = parent_todo.id

    new_todo = Todo(
        # ... other fields ...
        parent=child_parent,
        tags=child_tags,
        # ... rest ...
    )
```

The exact surrounding code depends on current `_batch_add_children` internals; preserve every other field (blocked_by, priority, etc.) exactly.

In `todo_add`, at the call site for `_batch_add_children`, pass the `flat` flag based on the same gate:

```python
    flat = schema_version.flat_only(cfg, name)
    result_json = _batch_add_children(
        cfg, name, parent_todo, child_specs, bp_list, today, todos, meta,
        flat=flat,
    )
```

Adapt to the real call site signature; the point is threading `flat` through.

- [ ] **Step 4: Run tests**

Run: `cd plugins/proj/server && uv run pytest tests/test_todo_add_schema_version_gate.py -v`
Expected: all pass.

Run: `cd plugins/proj/server && uv run pytest -q`
Expected: no regressions in pre-existing nested-mode tests (because `flat=False` is the default and pre-enforcement gate never flips it).

- [ ] **Step 5: Commit**

```bash
git add plugins/proj/server/server/tools/todos.py plugins/proj/server/tests/test_todo_add_schema_version_gate.py
git commit -m "feat(proj): batch path auto-tags children with group:<parent> post-enforcement (624)"
```

---

## Task 11: E2E hook-dispatch integration tests

**Files:**
- Create: `plugins/proj/server/tests/test_todo_add_e2e_hooks.py`

Exercise the full `todo_add` → hook dispatch → mocked SaaS endpoint chain to verify Tasks 3–7 compose correctly.

- [ ] **Step 1: Write failing tests**

```python
# plugins/proj/server/tests/test_todo_add_e2e_hooks.py
from __future__ import annotations

import json
from pathlib import Path

import pytest
import respx
import yaml
from httpx import Response

from server.tools.todos import todo_add


@pytest.fixture
def project_with_integrations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Project with Todoist + Jira enabled, a synced parent, and schema_version=2."""
    tracking = tmp_path / "tracking"
    demo = tracking / "demo"
    demo.mkdir(parents=True)
    (demo / "proj.yaml").write_text(
        yaml.safe_dump({
            "name": "demo",
            "schema_version": 2,
            "sync": {
                "todoist": {"enabled": True, "auto_sync": True, "api_token": "tok"},
                "jira": {
                    "enabled": True,
                    "auto_sync": True,
                    "base_url": "https://ex.atlassian.net",
                    "email": "e@x.com",
                    "api_token": "tok",
                    "epic_link_field": "customfield_10014",
                },
            },
        }),
    )
    monkeypatch.setenv("HOME", str(tmp_path))
    # Pre-create a parent todo in the project (with integration IDs already recorded
    # as if previously synced). Fixture details adapt to the real project-seeding
    # utilities used in test_todos.py.
    todo_add(title="parent epic", project_name="demo")
    # Stamp integration IDs onto the parent — adapt to real `todo_update` API
    # or direct storage mutation if needed.
    return demo


@respx.mock
def test_e2e_flat_child_fires_todoist_hook_with_parent_id(
    project_with_integrations: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Capture the Todoist request payload
    captured = {}

    def capture_request(request):
        captured["body"] = json.loads(request.content)
        return Response(200, json={"sync_status": {}})

    respx.post("https://api.todoist.com/api/v1/sync").mock(side_effect=capture_request)

    # Create a flat child via group tag
    result = json.loads(
        todo_add(title="child", tags=["group:1"], project_name="demo"),
    )
    assert result.get("error") is None

    body = captured.get("body", {})
    commands = body.get("commands", [])
    # Expect item_add (or the tool's command for creation) with parentId=parent's todoist id
    assert commands, "no Todoist commands captured"
    cmd_args = commands[0]["args"]
    assert cmd_args.get("parent_id") == "<parent-todoist-id>"  # replace with real fixture value
    assert "group:1" not in cmd_args.get("labels", [])  # synced_tags strips group:*


@respx.mock
def test_e2e_flat_child_fires_jira_hook_with_epic_parent_key(
    project_with_integrations: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = {}

    def capture(request):
        captured["body"] = json.loads(request.content)
        return Response(201, json={"key": "CPM-101"})

    respx.post(url__regex=r"https://ex\.atlassian\.net/rest/api/.*/issue").mock(side_effect=capture)

    result = json.loads(
        todo_add(title="child", tags=["group:1"], project_name="demo"),
    )
    assert result.get("error") is None

    body = captured.get("body", {})
    fields = body.get("fields", {})
    assert fields.get("parent", {}).get("key") == "<parent-epic-key>"  # from fixture
    assert "group:1" not in fields.get("labels", [])


@respx.mock
def test_e2e_top_level_flat_todo_fires_jira_hook_without_parent_key(
    project_with_integrations: Path,
) -> None:
    captured = {}

    def capture(request):
        captured["body"] = json.loads(request.content)
        return Response(201, json={"key": "CPM-200"})

    respx.post(url__regex=r"https://ex\.atlassian\.net/rest/api/.*/issue").mock(side_effect=capture)

    result = json.loads(todo_add(title="lone", project_name="demo"))
    assert result.get("error") is None

    body = captured.get("body", {})
    fields = body.get("fields", {})
    # `parent_key` must be OMITTED, not sent as empty string
    assert "parent" not in fields
```

**Implementer note:** The exact fixture shape (how parent's `todoist_task_id` / `jira_issue_key` get recorded after `todo_add` fires the create hooks) depends on existing test patterns in `test_batch_complete_hooks.py` and `test_hooks_schema.py`. Read those for the conventional way to seed synced state; adapt. The placeholder values like `"<parent-todoist-id>"` above need to be replaced with the real ids returned from the Todoist mock's first (parent-creation) response — either by capturing multiple requests in sequence or by stubbing the parent's integration IDs into storage directly before the child is created.

- [ ] **Step 2: Run — expect failure**

Run: `cd plugins/proj/server && uv run pytest tests/test_todo_add_e2e_hooks.py -v`
Expected: fails — either fixture setup missing or asserts don't line up yet.

- [ ] **Step 3: Adapt fixtures + make tests pass**

Iterate: read existing e2e test patterns, align the parent-setup pattern, make the captured-request assertions concrete. No new production code should be needed — this task is purely integration validation.

- [ ] **Step 4: Run tests**

Run: `cd plugins/proj/server && uv run pytest tests/test_todo_add_e2e_hooks.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add plugins/proj/server/tests/test_todo_add_e2e_hooks.py
git commit -m "test(proj): e2e hook-dispatch assertions for flat-todo resolution (624)"
```

---

## Final steps

- [ ] **Step A: Full plugin test sweep**

Run each plugin's suite:

```
cd plugins/proj/server && uv run pytest -q
cd plugins/jira/server && uv run pytest -q
cd plugins/todoist/server && uv run pytest -q
cd plugins/router/server && uv run pytest -q
```

Expected: all pass.

- [ ] **Step B: Lint**

Run: `cd plugins/proj/server && uv run ruff check server/ tests/`
Run: `cd plugins/proj/server && uv run ruff format --check server/ tests/`
Run: `cd plugins/router/server && uv run ruff check server/ tests/`
Run: `cd plugins/router/server && uv run ruff format --check server/ tests/`
Expected: clean.

- [ ] **Step C: Type check (if configured)**

Run: `cd plugins/proj/server && uv run basedpyright server/` (skip if not configured)
Expected: no new errors.

- [ ] **Step D: Verify no regression in full pre-existing hook tests**

Run: `cd plugins/proj/server && uv run pytest tests/test_batch_complete_hooks.py tests/test_hooks_schema.py tests/test_session_hook_edge_cases.py -v`
Expected: all pass. Any that fail due to `parent_jira_issue_key` now being present where it wasn't before → update assertion (the new field is additive; no hook should be broken by it).

- [ ] **Step E: Smoke test — manual verification against a real project (optional)**

If a personal sandbox project with `schema_version: 2` exists locally:

```bash
cd plugins/proj/server && uv run python -c "
from server.tools.todos import todo_add
print(todo_add(title='smoke', parent='1', project_name='<your-project>'))
"
```

Expected: JSON with `error` field containing the `nested mode disabled` message.

Then:

```bash
cd plugins/proj/server && uv run python -c "
from server.tools.todos import todo_add
print(todo_add(title='smoke', tags=['group:1'], project_name='<your-project>'))
"
```

Expected: JSON with no error, child created with `group:1` tag.

- [ ] **Step F: Open PR from `feat/624-flat-todo-model-server`**

PR body should summarize the 4 concerns (parent resolution, synced_tags, Jira fix, enforcement) and link the spec.

After merge, 636 Phase 1 is unblocked.

---

## Implementer notes

**Respx / pytest-textual-snapshot availability:** todo 635 ("Fix local test env: install respx/textual/hook_dispatch for all plugins") should be resolved before running the integration tests. If not, `uv sync --group test` from each plugin dir should install respx locally.

**`Todo` / `ProjectMeta` constructor args:** the test helpers in Tasks 1/2/3/4 use placeholder fixture constructors. Read `plugins/proj/server/server/lib/models.py` at the start of Task 1 and align the `_todo()` / `_meta()` fixtures to the real dataclass signatures before writing test bodies.

**`ProjConfig` constructor args in Task 8:** same story — check `server.lib.models.ProjConfig` for the actual constructor; the `tracking_dir=` arg is correct per the existing storage.py code but other required fields may need defaults.

**`require_config` + `_resolve_project_name` in Task 9:** these function names are the expected API of the surrounding module; the actual names in `todos.py` may differ slightly. Grep `require_config` and find the project-name resolution pattern used by other tools (`todo_list`, `todo_get`) and mirror it.

**Hook-file structure (YAML):** the exact key path (`hooks[*].param_mapping.parent_key` vs `hooks[*].param_mapping.parent`) is as shown in the survey report — double-check by reading the YAML before editing.

**Order of Tasks 3 and 5:** Task 5 (`omit_if_empty` in router template) must land before Task 6 (Jira hook uses `omit_if_empty: true`). The plan's task numbering reflects this. If the router DSL already supports `omit_if_empty` (check during Task 5 Step 1), skip the implementation steps and only run the tests to verify. If tests reveal existing support, commit `docs(router): confirm omit_if_empty DSL already supported (624)` with just the new tests.

**`parent_jira_issue_key` backward compat:** any pre-existing test that calls `_todo_hook_fields` and asserts on the exact keyset (`assert set(fields.keys()) == {...}`) will break because the new field is additive. Update the assertion to include `parent_jira_issue_key` in the expected set (or loosen to `assert "parent_jira_issue_key" in fields`).
