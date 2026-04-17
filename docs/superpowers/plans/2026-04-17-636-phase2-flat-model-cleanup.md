# 636 Phase 2 Flat-Model Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans.

**Goal:** Remove the dual-path (legacy nested + flat) server support from the proj plugin. Post-Phase-2, the codebase only understands the flat todo model; v1 projects raise `LegacyProjectError` pointing at the wizard.

**Architecture:** Five small ordered cleanups in one worktree, no dual-spawn parallelism (lesson from Phase 1). Each task has explicit file paths + commit message.

**Spec:** `docs/superpowers/specs/2026-04-17-636-phase2-flat-model-cleanup-design.md`

**Predicates:** 624 + 636 Phase 1 both landed on dev.

**Test execution:** `cd plugins/proj/server && uv run pytest -q --no-cov` + root `uv run pytest installer/tests/ -q --no-cov`.

---

## Task 1 — Runtime guard (`LegacyProjectError` + `require_flat` + storage entry-point calls)

**Files:**
- Modify: `plugins/proj/server/server/lib/schema_version.py` — add `LegacyProjectError` class + `require_flat` function
- Modify: `plugins/proj/server/server/lib/storage.py` — call `require_flat` at the start of `load_todos`, `save_todos`, `load_archive`, `save_archive` (check the actual function names in that file — some may be named differently)
- Create: `plugins/proj/server/tests/test_schema_version_require_flat.py` — 2 tests

**Tests:**

```python
from server.lib import schema_version
from server.lib.models import ProjConfig
from server.lib.schema_version import LegacyProjectError


def test_require_flat_raises_for_v1(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = ProjConfig(tracking_dir=str(tmp_path / "tracking"))
    proj_dir = tmp_path / "tracking" / "demo"
    proj_dir.mkdir(parents=True)
    (proj_dir / "proj.yaml").write_text("name: demo\n")  # no schema_version
    import pytest
    with pytest.raises(LegacyProjectError, match="cpm-install --migrate-flat"):
        schema_version.require_flat(cfg, "demo")


def test_require_flat_passes_for_v2(tmp_path):
    cfg = ProjConfig(tracking_dir=str(tmp_path / "tracking"))
    proj_dir = tmp_path / "tracking" / "demo"
    proj_dir.mkdir(parents=True)
    (proj_dir / "proj.yaml").write_text("name: demo\nschema_version: 2\n")
    schema_version.require_flat(cfg, "demo")  # no raise
```

**Implementation (append to `schema_version.py`):**

```python
class LegacyProjectError(RuntimeError):
    """Raised when a project is still on the nested (pre-flat-model) schema."""


def require_flat(cfg: ProjConfig, project_name: str) -> None:
    if not flat_only(cfg, project_name):
        raise LegacyProjectError(
            f"Project {project_name!r} is still on the nested todo schema "
            f"(schema_version < {TARGET}). Run `cpm-install --migrate-flat` "
            f"to upgrade this project before using todo tools.",
        )
```

**Storage wiring:** grep `storage.py` for `def load_todos`, `def save_todos`, `def load_archive`, `def save_archive` (or equivalent). In each, add as the first non-docstring line:

```python
from . import schema_version
schema_version.require_flat(cfg, project_name)
```

Adapt the import if `schema_version` is already imported at module top — then just call.

**Commit:** `feat(proj): LegacyProjectError + require_flat guard on storage entry points (636 Phase 2)`

---

## Task 2 — `Todo` dataclass field removal + SQL column cleanup

**Files:**
- Modify: `plugins/proj/server/server/lib/models.py` — drop `parent`, `children`, `next_child_id` from `Todo`
- Modify: `plugins/proj/server/server/lib/sql_todos.py` — remove those columns from INSERT / SELECT / column-list constants
- Modify: `plugins/proj/server/server/lib/sql_archive.py` — same
- Modify: any test fixture that constructs `Todo(parent=..., children=...)` — drop those kwargs
- Modify: any production code that reads `.parent` / `.children` / `.next_child_id` on a Todo — adapt

**Strategy:**

1. First, grep the codebase to map call sites:
   ```
   grep -rn "\.parent" plugins/proj/server --include="*.py" | grep -v "\.parent_" | grep -v "parent_id\|parent_todo\|parent_jira\|parent_todoist\|parent_trello"
   grep -rn "\.children" plugins/proj/server --include="*.py"
   grep -rn "next_child_id" plugins/proj/server --include="*.py"
   ```
2. For each site, decide: delete, replace with empty, or raise. Most should delete.
3. Expected hotspots:
   - `todos.py::todo_add` — already post-Phase-1 cleaned up (kwarg stays for batch); any direct `.parent` reads should be rare
   - `todos.py::_resolve_parent_for_hooks` — still reads `todo.parent` in fallback (removed by Task 3)
   - `todos.py::todo_complete` — may reference `.children` for family completion logic (THIS IS LOAD-BEARING — see §8 risk in spec)
   - `sql_todos.py` column lists
   - `full_sync` modules — todo 625's territory, but may need shim

**Tests to update first:**

```bash
grep -rln "Todo(.*parent=\|Todo(.*children=\|Todo(.*next_child_id=" plugins/proj/server/tests/
```

All matches: drop the kwargs.

**Commit:** `feat(proj): drop parent/children/next_child_id from Todo dataclass + SQL (636 Phase 2)`

**Expected test breakage:** anything touching `_complete_parent` / `_collect_family` — investigate + fix or delete obsolete logic. `todo_complete` in flat mode means "just complete this one todo" — no family traversal. The `_complete_parent` branch (which reads `.children`) becomes dead code for migrated projects; can be deleted or guarded.

---

## Task 3 — `_resolve_parent_for_hooks` + `_batch_add_children` + enforcement removal

**Files:**
- Modify: `plugins/proj/server/server/tools/todos.py`
- Modify: `plugins/proj/server/tests/test_todo_hook_fields_flat.py` — drop tests listed in §3.7 of spec
- Delete: `plugins/proj/server/tests/test_todo_add_schema_version_gate.py` (obsolete)

**`_resolve_parent_for_hooks` simplification:**

Replace:
```python
def _resolve_parent_for_hooks(todo: Todo, todos: list[Todo]) -> ParentLinks:
    parent_id = _parent_id_from_tag(todo.tags) or todo.parent
    # ...
```
With:
```python
def _resolve_parent_for_hooks(todo: Todo, todos: list[Todo]) -> ParentLinks:
    """Resolve parent integration IDs for hook dispatch via group:<id> tag."""
    parent_id = _parent_id_from_tag(todo.tags)
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

**Enforcement removal:**

Delete `_FLAT_MODE_ERROR` constant + `_enforce_flat_args` function.

In `todo_add`, delete the gate block:
```python
# DELETE:
_cfg = require_config()
from server.lib import state as _state
_project_name = _state.resolve_project(project_name)
if _project_name and schema_version.flat_only(_cfg, _project_name):
    try:
        _child_specs_for_gate = json.loads(children) if children and children.strip() else []
    except json.JSONDecodeError:
        _child_specs_for_gate = []
    try:
        _enforce_flat_args(title=title, parent=parent, children_list=_child_specs_for_gate)
    except ValueError as e:
        return json.dumps({"error": str(e)})
```

Storage-level guard (Task 1) handles the v1-project case now.

**`_batch_add_children` cleanup:**

- Drop `flat: bool = False` kwarg from signature
- Remove the `if flat / else` branch — keep only the flat path (auto-tag with `group:<parent.id>`)
- Remove the `parent.children.append(child.id)` block (was already skipped when `flat=True`)
- Call sites of `_batch_add_children(...)` — drop the `flat=schema_version.flat_only(cfg, name)` kwarg

**Test cleanup:**

In `test_todo_hook_fields_flat.py`, delete:
- `test_resolve_falls_back_to_parent_field`
- `test_resolve_uses_group_tag_over_parent_field` (keep but simplify — maybe rename to `test_resolve_returns_parent_from_group_tag`)
- `test_hook_fields_legacy_nested_child_still_works`

Delete the entire `test_todo_add_schema_version_gate.py` file (obsolete gate).

**Commit:** `refactor(proj): drop legacy parent-field resolution + enforcement gate (636 Phase 2)`

---

## Task 4 — Dead hook entries + `/proj:flatten-children` retirement

**Files:**
- Modify: `plugins/todoist/.claude-plugin/default-hooks.yaml` — delete `todoist-on-todo-add-child` entry
- Modify: `plugins/trello/.claude-plugin/default-hooks.yaml` — delete `trello-on-todo-add-child` + `trello-on-todo-batch-add-children` entries
- Delete: `plugins/proj/skills/flatten-children/` entire directory
- Modify: `README.md` if it references the skill
- Modify: `plugins/proj/server/tests/test_default_hooks_refs.py` if any tests assert on those hooks (drop)

**Commit:** `chore(plugins): delete dead todo_add_child hooks + retire flatten-children skill (636 Phase 2)`

---

## Task 5 — Final sweep + migration + merge

- [ ] Run full test sweep: `cd plugins/proj/server && uv run pytest -q --no-cov` — all pass
- [ ] Run `cd installer && uv run pytest -q --no-cov` — all pass (installer/migrations/ should be unaffected)
- [ ] Run `cd plugins/router/server && uv run pytest -q --no-cov` — unaffected
- [ ] Lint: `uv run ruff check + ruff format --check + basedpyright` on each changed plugin
- [ ] **Important pre-merge step:** run `cpm-install --migrate-flat` on your own dev tracking dir (if it's still v1) so the post-merge code doesn't error on your next tool use
- [ ] Rebase `feat/636-phase2-cleanup` onto current dev
- [ ] FF-merge to local dev
- [ ] Push dev + watch CI

---

## Implementer notes

- **Do NOT parallelize git-committing subagents.** Per feedback memory: shared worktree + git races cause bundling, empty commits, stash-restore losses. One agent at a time.
- **Tasks 1 + 2 are the riskiest** — they touch core storage + data model. Task 3 is smaller. Task 4 is trivial.
- **Grep before you edit** — the dataclass field removal will surface unexpected call sites. Don't assume; verify.
- **`todo_complete`'s `_complete_parent` logic reads `.children`** — either remove entirely (since flat model has no "family" concept) or check with the user. If in doubt, remove + add a follow-up todo to confirm no behavior regression.
