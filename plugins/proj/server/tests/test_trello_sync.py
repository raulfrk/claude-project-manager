"""Tests for trello_sync tools (proj_trello_diff and proj_trello_apply)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from server.lib import storage
from server.lib.ids import next_todo_id
from server.lib.models import (
    ProjConfig,
    ProjectDates,
    ProjectEntry,
    ProjectIndex,
    ProjectMeta,
    ProjectTrelloConfig,
    RepoEntry,
    Todo,
    TrelloSync,
)
from server.tools.trello_sync import (
    TASKS_CHECKLIST_NAME,
    TrelloApplyInput,
    TrelloSyncPlan,
    _flatten_descendants,
    _strip_id_prefix,
    apply_changes,
    build_expected_state,
    compute_diff,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def cfg_with_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[ProjConfig, str]:
    config_path = tmp_path / "proj.yaml"
    monkeypatch.setattr(storage, "_DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.delenv("PROJ_CONFIG", raising=False)

    cfg = ProjConfig(
        tracking_dir=str(tmp_path / "tracking"),
        trello=TrelloSync(enabled=True, default_board_id="board123"),
    )
    storage.save_config(cfg)

    today = str(date.today())
    proj_dir = Path(cfg.tracking_dir) / "myapp"
    proj_dir.mkdir(parents=True)
    (proj_dir / "todos.yaml").write_text("todos: []\n")
    (proj_dir / "archive.yaml").write_text("todos: []\n")
    meta = ProjectMeta(
        name="myapp",
        repos=[RepoEntry(label="code", path=str(tmp_path))],
        dates=ProjectDates(created=today, last_updated=today),
        trello_card_id="card_abc",
    )
    storage.save_meta(cfg, meta)
    index = ProjectIndex(
        projects={"myapp": ProjectEntry(name="myapp", tracking_dir=str(proj_dir), created=today)},
    )
    storage.save_index(cfg, index)
    return cfg, "myapp"


def _make_todo(cfg: ProjConfig, name: str, title: str, **kwargs: object) -> Todo:
    meta = storage.load_meta(cfg, name)
    today = str(date.today())
    parent_todo = None
    if "parent" in kwargs and kwargs["parent"]:
        todos = storage.load_todos(cfg, name)
        parent_todo = next((t for t in todos if t.id == kwargs["parent"]), None)
    todo = Todo(id=next_todo_id(meta, parent=parent_todo), title=title, created=today, updated=today)
    for k, v in kwargs.items():
        setattr(todo, k, v)
    storage.save_meta(cfg, meta)
    return todo


def _make_trello_card_json(checklists: list[dict] | None = None) -> str:
    """Build a Trello card JSON string."""
    return json.dumps({"checklists": checklists or []})


def _make_checklist(
    cl_id: str,
    name: str,
    items: list[dict] | None = None,
) -> dict:
    return {
        "id": cl_id,
        "name": name,
        "checkItems": items or [],
    }


def _make_check_item(
    item_id: str,
    name: str,
    state: str = "incomplete",
) -> dict:
    return {
        "id": item_id,
        "name": name,
        "state": state,
    }


# ── Helper tests ─────────────────────────────────────────────────────────────


class TestHelpers:
    def test_strip_id_prefix_simple(self) -> None:
        assert _strip_id_prefix("1.1: Fix the bug") == "Fix the bug"

    def test_strip_id_prefix_nested(self) -> None:
        assert _strip_id_prefix("1.1: 1.1.1: Deep task") == "Deep task"

    def test_strip_id_prefix_no_prefix(self) -> None:
        assert _strip_id_prefix("Just a title") == "Just a title"

    def test_strip_id_prefix_complex(self) -> None:
        assert _strip_id_prefix("42: Hello") == "Hello"

    def test_strip_id_prefix_multiple_digits(self) -> None:
        assert _strip_id_prefix("123.456: Title") == "Title"


class TestFlattenDescendants:
    def test_single_child(self) -> None:
        parent = Todo(id="1", title="Parent", children=["1.1"])
        child = Todo(id="1.1", title="Child", parent="1")
        todo_map = {"1": parent, "1.1": child}
        result = _flatten_descendants(parent, todo_map)
        assert len(result) == 1
        assert result[0][0] == "1.1: Child"
        assert result[0][1] is child

    def test_nested_children(self) -> None:
        parent = Todo(id="1", title="Parent", children=["1.1"])
        child = Todo(id="1.1", title="Child", parent="1", children=["1.1.1"])
        grandchild = Todo(id="1.1.1", title="Grandchild", parent="1.1")
        todo_map = {"1": parent, "1.1": child, "1.1.1": grandchild}
        result = _flatten_descendants(parent, todo_map)
        assert len(result) == 2
        assert result[0][0] == "1.1: Child"
        assert result[1][0] == "1.1: 1.1.1: Grandchild"

    def test_multiple_children(self) -> None:
        parent = Todo(id="1", title="Parent", children=["1.1", "1.2"])
        child1 = Todo(id="1.1", title="First", parent="1")
        child2 = Todo(id="1.2", title="Second", parent="1")
        todo_map = {"1": parent, "1.1": child1, "1.2": child2}
        result = _flatten_descendants(parent, todo_map)
        assert len(result) == 2
        assert result[0][0] == "1.1: First"
        assert result[1][0] == "1.2: Second"

    def test_missing_child(self) -> None:
        parent = Todo(id="1", title="Parent", children=["1.1", "1.2"])
        child1 = Todo(id="1.1", title="First", parent="1")
        todo_map = {"1": parent, "1.1": child1}
        result = _flatten_descendants(parent, todo_map)
        assert len(result) == 1


class TestBuildExpectedState:
    def test_root_leaf_goes_to_tasks(self) -> None:
        todos = [Todo(id="1", title="A leaf task")]
        checklists, tasks_items = build_expected_state(todos)
        assert len(checklists) == 0
        assert len(tasks_items) == 1
        assert tasks_items[0]["name"] == "A leaf task"
        assert tasks_items[0]["todo_id"] == "1"

    def test_root_with_children_becomes_checklist(self) -> None:
        parent = Todo(id="1", title="Parent", children=["1.1"])
        child = Todo(id="1.1", title="Child", parent="1")
        checklists, tasks_items = build_expected_state([parent, child])
        assert len(checklists) == 1
        assert checklists[0]["name"] == "Parent"
        assert checklists[0]["todo_id"] == "1"
        items = checklists[0]["items"]
        assert isinstance(items, list)
        assert len(items) == 1
        assert items[0]["name"] == "1.1: Child"

    def test_done_child_is_checked(self) -> None:
        parent = Todo(id="1", title="Parent", children=["1.1"])
        child = Todo(id="1.1", title="Child", parent="1", status="done")
        checklists, _ = build_expected_state([parent, child])
        items = checklists[0]["items"]
        assert isinstance(items, list)
        assert items[0]["checked"] is True

    def test_done_root_leaf_is_checked(self) -> None:
        todos = [Todo(id="1", title="Done task", status="done")]
        _, tasks_items = build_expected_state(todos)
        assert tasks_items[0]["checked"] is True

    def test_mixed_roots(self) -> None:
        parent = Todo(id="1", title="Parent", children=["1.1"])
        child = Todo(id="1.1", title="Child", parent="1")
        leaf = Todo(id="2", title="Standalone")
        checklists, tasks_items = build_expected_state([parent, child, leaf])
        assert len(checklists) == 1
        assert len(tasks_items) == 1

    def test_multi_level_flatten(self) -> None:
        """Deep hierarchy gets flattened to 2-level with ID prefixes."""
        root = Todo(id="1", title="Root", children=["1.1"])
        child = Todo(id="1.1", title="Child", parent="1", children=["1.1.1"])
        grandchild = Todo(id="1.1.1", title="Grand", parent="1.1")
        checklists, _ = build_expected_state([root, child, grandchild])
        assert len(checklists) == 1
        items = checklists[0]["items"]
        assert isinstance(items, list)
        assert len(items) == 2
        assert items[0]["name"] == "1.1: Child"
        assert items[1]["name"] == "1.1: 1.1.1: Grand"


# ── Diff tests ───────────────────────────────────────────────────────────────


class TestTrelloDiff:
    def test_empty_both_sides(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        plan = compute_diff(_make_trello_card_json(), cfg, name)
        assert plan.is_empty()

    def test_card_create_when_no_card_id(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        meta = storage.load_meta(cfg, name)
        meta.trello_card_id = None
        storage.save_meta(cfg, meta)
        plan = compute_diff(_make_trello_card_json(), cfg, name)
        assert plan.card_create is True

    def test_no_card_create_when_card_id_set(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        plan = compute_diff(_make_trello_card_json(), cfg, name)
        assert plan.card_create is False

    def test_push_create_checklist_for_root_with_children(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        cfg, name = cfg_with_project
        parent = _make_todo(cfg, name, "Parent")
        child = _make_todo(cfg, name, "Child", parent=parent.id)
        parent.children.append(child.id)
        storage.save_todos(cfg, name, [parent, child])

        plan = compute_diff(_make_trello_card_json(), cfg, name)
        assert len(plan.push_create_checklist) == 1
        assert plan.push_create_checklist[0]["name"] == "Parent"

    def test_push_create_item_for_root_leaf(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        cfg, name = cfg_with_project
        todo = _make_todo(cfg, name, "Leaf task")
        storage.save_todos(cfg, name, [todo])

        plan = compute_diff(_make_trello_card_json(), cfg, name)
        # Should create "Tasks" checklist + one item
        tasks_checklists = [c for c in plan.push_create_checklist if c["name"] == TASKS_CHECKLIST_NAME]
        assert len(tasks_checklists) == 1
        assert len(plan.push_create_item) == 1
        assert plan.push_create_item[0]["name"] == "Leaf task"

    def test_push_create_item_for_children(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        cfg, name = cfg_with_project
        parent = _make_todo(cfg, name, "Parent")
        child = _make_todo(cfg, name, "Child", parent=parent.id)
        parent.children.append(child.id)
        storage.save_todos(cfg, name, [parent, child])

        plan = compute_diff(_make_trello_card_json(), cfg, name)
        assert len(plan.push_create_item) == 1
        assert "Child" in plan.push_create_item[0]["name"]

    def test_pull_create_from_new_trello_item(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        cfg, name = cfg_with_project
        # Root todo linked to a checklist
        parent = _make_todo(cfg, name, "Parent", trello_checklist_id="cl1")
        storage.save_todos(cfg, name, [parent])

        card_json = _make_trello_card_json([
            _make_checklist("cl1", "Parent", [
                _make_check_item("item1", "New from Trello"),
            ]),
        ])
        plan = compute_diff(card_json, cfg, name)
        assert len(plan.pull_create) == 1
        assert plan.pull_create[0]["title"] == "New from Trello"
        assert plan.pull_create[0]["parent"] == parent.id

    def test_pull_create_root_from_new_checklist(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        cfg, name = cfg_with_project
        card_json = _make_trello_card_json([
            _make_checklist("cl_new", "New Feature"),
        ])
        plan = compute_diff(card_json, cfg, name)
        assert len(plan.pull_create_root) == 1
        assert plan.pull_create_root[0]["title"] == "New Feature"
        assert plan.pull_create_root[0]["trello_checklist_id"] == "cl_new"

    def test_pull_create_root_skips_tasks_checklist(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        cfg, name = cfg_with_project
        card_json = _make_trello_card_json([
            _make_checklist("cl_tasks", TASKS_CHECKLIST_NAME),
        ])
        plan = compute_diff(card_json, cfg, name)
        assert len(plan.pull_create_root) == 0

    def test_pull_update_on_name_change(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        cfg, name = cfg_with_project
        todo = _make_todo(cfg, name, "Old title", trello_checklist_item_id="item1")
        storage.save_todos(cfg, name, [todo])

        card_json = _make_trello_card_json([
            _make_checklist("cl1", TASKS_CHECKLIST_NAME, [
                _make_check_item("item1", "New title"),
            ]),
        ])
        plan = compute_diff(card_json, cfg, name)
        assert len(plan.pull_update) == 1
        assert plan.pull_update[0]["title"] == "New title"

    def test_pull_complete_checked_item(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        cfg, name = cfg_with_project
        todo = _make_todo(cfg, name, "Task", trello_checklist_item_id="item1")
        storage.save_todos(cfg, name, [todo])

        card_json = _make_trello_card_json([
            _make_checklist("cl1", TASKS_CHECKLIST_NAME, [
                _make_check_item("item1", "Task", state="complete"),
            ]),
        ])
        plan = compute_diff(card_json, cfg, name)
        assert len(plan.pull_complete) == 1
        assert plan.pull_complete[0] == todo.id

    def test_pull_reopen_unchecked_item(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        cfg, name = cfg_with_project
        todo = _make_todo(cfg, name, "Done task", trello_checklist_item_id="item1", status="done")
        storage.save_todos(cfg, name, [todo])

        card_json = _make_trello_card_json([
            _make_checklist("cl1", TASKS_CHECKLIST_NAME, [
                _make_check_item("item1", "Done task", state="incomplete"),
            ]),
        ])
        plan = compute_diff(card_json, cfg, name)
        assert len(plan.pull_reopen) == 1
        assert plan.pull_reopen[0] == todo.id

    def test_push_rename_checklist(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        cfg, name = cfg_with_project
        parent = _make_todo(cfg, name, "New Name", trello_checklist_id="cl1")
        child = _make_todo(cfg, name, "Child", parent=parent.id, trello_checklist_item_id="item1")
        parent.children.append(child.id)
        storage.save_todos(cfg, name, [parent, child])

        card_json = _make_trello_card_json([
            _make_checklist("cl1", "Old Name", [
                _make_check_item("item1", "1.1: Child"),
            ]),
        ])
        plan = compute_diff(card_json, cfg, name)
        assert len(plan.push_rename_checklist) == 1
        assert plan.push_rename_checklist[0]["name"] == "New Name"

    def test_push_update_item_name(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        cfg, name = cfg_with_project
        todo = _make_todo(cfg, name, "Updated locally", trello_checklist_item_id="item1")
        storage.save_todos(cfg, name, [todo])

        card_json = _make_trello_card_json([
            _make_checklist("cl1", TASKS_CHECKLIST_NAME, [
                _make_check_item("item1", "Old name"),
            ]),
        ])
        plan = compute_diff(card_json, cfg, name)
        assert len(plan.push_update_item) == 1
        assert plan.push_update_item[0]["name"] == "Updated locally"

    def test_push_complete_item(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        cfg, name = cfg_with_project
        todo = _make_todo(cfg, name, "Done", trello_checklist_item_id="item1", status="done")
        storage.save_todos(cfg, name, [todo])

        card_json = _make_trello_card_json([
            _make_checklist("cl1", TASKS_CHECKLIST_NAME, [
                _make_check_item("item1", "Done", state="incomplete"),
            ]),
        ])
        plan = compute_diff(card_json, cfg, name)
        assert len(plan.push_complete_item) == 1

    def test_push_delete_item(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """Item linked to a local todo that no longer exists -> push delete."""
        cfg, name = cfg_with_project
        # Create a todo linked to a Trello item, then remove it locally
        # but keep another todo so the project has state
        other = _make_todo(cfg, name, "Keeper", trello_checklist_item_id="item_keep")
        storage.save_todos(cfg, name, [other])
        # Trello still has both the keeper item and the orphaned one
        card_json = _make_trello_card_json([
            _make_checklist("cl1", TASKS_CHECKLIST_NAME, [
                _make_check_item("item_keep", "Keeper"),
                _make_check_item("item_orphan", "Deleted locally"),
            ]),
        ])
        plan = compute_diff(card_json, cfg, name)
        # item_orphan is not linked to any local todo, and is not being pull_create'd
        # because ... it actually IS being pull_create'd (Trello item not linked locally).
        # Unlinked items in Trello are always pull_create'd, never push_delete'd.
        # push_delete only fires if the item was in pull_create exclusion (which it is).
        # So actually: unlinked Trello items -> pull_create, not push_delete.
        assert len(plan.pull_create) == 1
        assert plan.pull_create[0]["trello_checklist_item_id"] == "item_orphan"
        assert len(plan.push_delete_item) == 0

    def test_unlinked_trello_item_is_pulled(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """An item in Trello with no local counterpart is pulled as a new todo."""
        cfg, name = cfg_with_project
        card_json = _make_trello_card_json([
            _make_checklist("cl1", TASKS_CHECKLIST_NAME, [
                _make_check_item("item_new", "Brand new from Trello"),
            ]),
        ])
        plan = compute_diff(card_json, cfg, name)
        assert len(plan.pull_create) == 1
        assert plan.pull_create[0]["title"] == "Brand new from Trello"

    def test_leaf_gains_children_restructure(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """A root leaf todo gains children -> should push a new checklist."""
        cfg, name = cfg_with_project
        parent = _make_todo(cfg, name, "Was a leaf", trello_checklist_item_id="item1")
        child = _make_todo(cfg, name, "New child", parent=parent.id)
        parent.children.append(child.id)
        storage.save_todos(cfg, name, [parent, child])

        # Trello still has the old item in Tasks
        card_json = _make_trello_card_json([
            _make_checklist("cl_tasks", TASKS_CHECKLIST_NAME, [
                _make_check_item("item1", "Was a leaf"),
            ]),
        ])
        plan = compute_diff(card_json, cfg, name)
        # Should create a new checklist for the parent
        assert len(plan.push_create_checklist) == 1
        assert plan.push_create_checklist[0]["name"] == "Was a leaf"

    def test_invalid_json_handled(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        cfg, name = cfg_with_project
        plan = compute_diff("not valid json", cfg, name)
        assert plan.is_empty()

    def test_empty_string_handled(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        cfg, name = cfg_with_project
        plan = compute_diff("", cfg, name)
        assert plan.is_empty()


# ── Apply tests ──────────────────────────────────────────────────────────────


class TestTrelloApply:
    def test_create_locally(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        data = TrelloApplyInput(
            created_locally=[{
                "title": "From Trello",
                "parent": None,
                "trello_checklist_item_id": "item1",
                "checked": False,
            }],
        )
        counts = apply_changes(data, cfg, name)
        assert counts["created"] == 1
        todos = storage.load_todos(cfg, name)
        assert len(todos) == 1
        assert todos[0].title == "From Trello"
        assert todos[0].trello_checklist_item_id == "item1"

    def test_create_root_locally(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        data = TrelloApplyInput(
            created_root_locally=[{
                "title": "New Feature",
                "trello_checklist_id": "cl_new",
            }],
        )
        counts = apply_changes(data, cfg, name)
        assert counts["created_root"] == 1
        todos = storage.load_todos(cfg, name)
        assert len(todos) == 1
        assert todos[0].title == "New Feature"
        assert todos[0].trello_checklist_id == "cl_new"

    def test_create_with_parent(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        parent = _make_todo(cfg, name, "Parent")
        storage.save_todos(cfg, name, [parent])

        data = TrelloApplyInput(
            created_locally=[{
                "title": "Child from Trello",
                "parent": parent.id,
                "trello_checklist_item_id": "item2",
                "checked": False,
            }],
        )
        counts = apply_changes(data, cfg, name)
        assert counts["created"] == 1
        todos = storage.load_todos(cfg, name)
        parent_reloaded = next(t for t in todos if t.id == parent.id)
        assert len(parent_reloaded.children) == 1

    def test_create_checked_item(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        data = TrelloApplyInput(
            created_locally=[{
                "title": "Already done",
                "parent": None,
                "trello_checklist_item_id": "item3",
                "checked": True,
            }],
        )
        counts = apply_changes(data, cfg, name)
        assert counts["created"] == 1
        todos = storage.load_todos(cfg, name)
        assert todos[0].status == "done"

    def test_update_locally(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        todo = _make_todo(cfg, name, "Old title", trello_checklist_item_id="item1")
        storage.save_todos(cfg, name, [todo])

        data = TrelloApplyInput(
            updated_locally=[{
                "todo_id": todo.id,
                "title": "New title",
            }],
        )
        counts = apply_changes(data, cfg, name)
        assert counts["updated"] == 1
        todos = storage.load_todos(cfg, name)
        assert todos[0].title == "New title"

    def test_complete_locally(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        todo = _make_todo(cfg, name, "To complete")
        storage.save_todos(cfg, name, [todo])

        data = TrelloApplyInput(completed_locally=[todo.id])
        counts = apply_changes(data, cfg, name)
        assert counts["completed"] == 1
        # Root leaf is archived
        todos = storage.load_todos(cfg, name)
        assert len(todos) == 0
        archived = storage.load_archived_todos(cfg, name)
        assert len(archived) == 1

    def test_complete_child_not_archived(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        parent = _make_todo(cfg, name, "Parent")
        child = _make_todo(cfg, name, "Child", parent=parent.id)
        parent.children.append(child.id)
        storage.save_todos(cfg, name, [parent, child])

        data = TrelloApplyInput(completed_locally=[child.id])
        counts = apply_changes(data, cfg, name)
        assert counts["completed"] == 1
        todos = storage.load_todos(cfg, name)
        assert len(todos) == 2
        child_reloaded = next(t for t in todos if t.id == child.id)
        assert child_reloaded.status == "done"

    def test_reopen_locally(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        todo = _make_todo(cfg, name, "Was done", status="done")
        storage.save_todos(cfg, name, [todo])

        data = TrelloApplyInput(reopened_locally=[todo.id])
        counts = apply_changes(data, cfg, name)
        assert counts["reopened"] == 1
        todos = storage.load_todos(cfg, name)
        assert todos[0].status == "pending"

    def test_link_trello_ids(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        todo = _make_todo(cfg, name, "To link")
        storage.save_todos(cfg, name, [todo])

        data = TrelloApplyInput(
            link_trello_ids=[{
                "todo_id": todo.id,
                "trello_checklist_id": "cl1",
                "trello_checklist_item_id": "item1",
            }],
        )
        counts = apply_changes(data, cfg, name)
        assert counts["linked"] == 1
        todos = storage.load_todos(cfg, name)
        assert todos[0].trello_checklist_id == "cl1"
        assert todos[0].trello_checklist_item_id == "item1"

    def test_link_trello_card_id(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        data = TrelloApplyInput(link_trello_card_id="card_new_123")
        apply_changes(data, cfg, name)
        meta = storage.load_meta(cfg, name)
        assert meta.trello_card_id == "card_new_123"

    def test_combined_operations(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        existing = _make_todo(cfg, name, "Existing", trello_checklist_item_id="item_ex")
        to_complete = _make_todo(cfg, name, "To complete")
        done_todo = _make_todo(cfg, name, "Was done", status="done")
        storage.save_todos(cfg, name, [existing, to_complete, done_todo])

        data = TrelloApplyInput(
            created_locally=[{"title": "New", "trello_checklist_item_id": "item_new"}],
            updated_locally=[{"todo_id": existing.id, "title": "Updated"}],
            completed_locally=[to_complete.id],
            reopened_locally=[done_todo.id],
        )
        counts = apply_changes(data, cfg, name)
        assert counts["created"] == 1
        assert counts["updated"] == 1
        assert counts["completed"] == 1
        assert counts["reopened"] == 1

    def test_invalid_json_returns_error(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        from unittest.mock import MagicMock
        from server.tools.trello_sync import register
        app = MagicMock()
        tools: dict[str, object] = {}
        app.tool = lambda **kw: lambda fn: tools.update({fn.__name__: fn}) or fn
        register(app)
        result = tools["proj_trello_apply"]
        out = result(apply_json="not json", project_name=name)  # type: ignore[operator]
        assert "Invalid JSON" in out


# ── TrelloSyncPlan tests ────────────────────────────────────────────────────


class TestTrelloSyncPlan:
    def test_is_empty_true(self) -> None:
        plan = TrelloSyncPlan()
        assert plan.is_empty()

    def test_is_empty_false_pull(self) -> None:
        plan = TrelloSyncPlan(pull_create=[{"title": "x"}])
        assert not plan.is_empty()

    def test_is_empty_false_card_create(self) -> None:
        plan = TrelloSyncPlan(card_create=True)
        assert not plan.is_empty()

    def test_to_dict_has_summary(self) -> None:
        plan = TrelloSyncPlan(push_create_item=[{"name": "x"}])
        d = plan.to_dict()
        assert d["summary"]["push_create_item_count"] == 1  # type: ignore[index]
        assert d["summary"]["pull_create_count"] == 0  # type: ignore[index]


# ── MCP tool registration tests ─────────────────────────────────────────────


class TestMCPToolDiff:
    def _get_tools(self) -> dict[str, object]:
        from unittest.mock import MagicMock
        from server.tools.trello_sync import register
        app = MagicMock()
        tools: dict[str, object] = {}
        app.tool = lambda **kw: lambda fn: tools.update({fn.__name__: fn}) or fn
        register(app)
        return tools

    def test_diff_empty_both_sides(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        tools = self._get_tools()
        diff = tools["proj_trello_diff"]
        result = json.loads(diff(trello_card_json=_make_trello_card_json(), project_name=name))  # type: ignore[operator]
        assert result["summary"]["pull_create_count"] == 0
        assert result["summary"]["push_create_checklist_count"] == 0

    def test_diff_invalid_json(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        tools = self._get_tools()
        diff = tools["proj_trello_diff"]
        # Invalid JSON for card state should not crash
        result = json.loads(diff(trello_card_json="not json", project_name=name))  # type: ignore[operator]
        assert "summary" in result

    def test_auto_apply_false_returns_plan(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        tools = self._get_tools()
        diff = tools["proj_trello_diff"]
        result = json.loads(diff(  # type: ignore[operator]
            trello_card_json=_make_trello_card_json(),
            auto_apply=False,
            project_name=name,
        ))
        assert "summary" in result
        assert "auto_applied" not in result

    def test_auto_apply_true_returns_project_info(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        cfg, name = cfg_with_project
        tools = self._get_tools()
        diff = tools["proj_trello_diff"]
        result = json.loads(diff(  # type: ignore[operator]
            trello_card_json=_make_trello_card_json(),
            auto_apply=True,
            project_name=name,
        ))
        assert "project_info" in result
        assert result["project_info"]["trello_card_id"] == "card_abc"
        assert "auto_applied" in result

    def test_auto_apply_creates_pulled_todos(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        cfg, name = cfg_with_project
        tools = self._get_tools()
        diff = tools["proj_trello_diff"]
        card_json = _make_trello_card_json([
            _make_checklist("cl_new", "Feature X"),
        ])
        result = json.loads(diff(  # type: ignore[operator]
            trello_card_json=card_json,
            auto_apply=True,
            project_name=name,
        ))
        assert result["auto_applied"]["created_root"] == 1
        todos = storage.load_todos(cfg, name)
        assert len(todos) == 1
        assert todos[0].title == "Feature X"

    def test_auto_apply_completes_pulled_todos(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        cfg, name = cfg_with_project
        todo = _make_todo(cfg, name, "Task", trello_checklist_item_id="item1")
        storage.save_todos(cfg, name, [todo])

        tools = self._get_tools()
        diff = tools["proj_trello_diff"]
        card_json = _make_trello_card_json([
            _make_checklist("cl1", TASKS_CHECKLIST_NAME, [
                _make_check_item("item1", "Task", state="complete"),
            ]),
        ])
        result = json.loads(diff(  # type: ignore[operator]
            trello_card_json=card_json,
            auto_apply=True,
            project_name=name,
        ))
        assert result["auto_applied"]["completed"] == 1

    def test_auto_apply_preserves_push_operations(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        cfg, name = cfg_with_project
        todo = _make_todo(cfg, name, "Local only")
        storage.save_todos(cfg, name, [todo])

        tools = self._get_tools()
        diff = tools["proj_trello_diff"]
        result = json.loads(diff(  # type: ignore[operator]
            trello_card_json=_make_trello_card_json(),
            auto_apply=True,
            project_name=name,
        ))
        # Push create should still be in the plan
        assert result["plan"]["summary"]["push_create_item_count"] == 1
        assert result["plan"]["summary"]["push_create_checklist_count"] == 1


# ── Apply MCP tool tests ────────────────────────────────────────────────────


class TestMCPToolApply:
    def _get_apply_fn(self) -> object:
        from unittest.mock import MagicMock
        from server.tools.trello_sync import register
        app = MagicMock()
        tools: dict[str, object] = {}
        app.tool = lambda **kw: lambda fn: tools.update({fn.__name__: fn}) or fn
        register(app)
        return tools["proj_trello_apply"]

    def test_apply_creates_and_links(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        apply_fn = self._get_apply_fn()
        data = {
            "created_locally": [{
                "title": "From Trello",
                "parent": None,
                "trello_checklist_item_id": "item1",
            }],
            "link_trello_card_id": "card_xyz",
        }
        result = json.loads(apply_fn(apply_json=json.dumps(data), project_name=name))  # type: ignore[operator]
        assert result["status"] == "ok"
        assert result["counts"]["created"] == 1
        meta = storage.load_meta(cfg, name)
        assert meta.trello_card_id == "card_xyz"
