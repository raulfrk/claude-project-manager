"""Tests for trello_sync tools (proj_trello_diff and proj_trello_apply)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

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
    TrelloSyncState,
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

    now = datetime.now(tz=timezone.utc).replace(tzinfo=None).isoformat()
    proj_dir = Path(cfg.tracking_dir) / "myapp"
    proj_dir.mkdir(parents=True)
    (proj_dir / "todos.yaml").write_text("todos: []\n")
    (proj_dir / "archive.yaml").write_text("todos: []\n")
    meta = ProjectMeta(
        name="myapp",
        repos=[RepoEntry(label="code", path=str(tmp_path))],
        dates=ProjectDates(created=now, last_updated=now),
        trello_card_id="card_abc",
    )
    storage.save_meta(cfg, meta)
    index = ProjectIndex(
        projects={"myapp": ProjectEntry(name="myapp", tracking_dir=str(proj_dir), created=now)},
    )
    storage.save_index(cfg, index)
    return cfg, "myapp"


def _make_todo(cfg: ProjConfig, name: str, title: str, **kwargs: object) -> Todo:
    meta = storage.load_meta(cfg, name)
    now = datetime.now(tz=timezone.utc).replace(tzinfo=None).isoformat()
    parent_todo = None
    if "parent" in kwargs and kwargs["parent"]:
        todos = storage.load_todos(cfg, name)
        parent_todo = next((t for t in todos if t.id == kwargs["parent"]), None)
    todo = Todo(id=next_todo_id(meta, parent=parent_todo), title=title, created=now, updated=now)
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

    def test_strip_id_prefix_new_format_em_dash(self) -> None:
        """New nesting format: '2.3.1 \u2014 title'."""
        assert _strip_id_prefix("2.3.1 \u2014 Fix the bug") == "Fix the bug"

    def test_strip_id_prefix_new_format_simple(self) -> None:
        assert _strip_id_prefix("1.1 \u2014 Child task") == "Child task"


class TestFlattenDescendants:
    def test_single_child(self) -> None:
        parent = Todo(id="1", title="Parent", children=["1.1"])
        child = Todo(id="1.1", title="Child", parent="1")
        todo_map = {"1": parent, "1.1": child}
        result = _flatten_descendants(parent, todo_map)
        assert len(result) == 1
        assert result[0][0] == "1.1 \u2014 Child"
        assert result[0][1] is child

    def test_nested_children(self) -> None:
        parent = Todo(id="1", title="Parent", children=["1.1"])
        child = Todo(id="1.1", title="Child", parent="1", children=["1.1.1"])
        grandchild = Todo(id="1.1.1", title="Grandchild", parent="1.1")
        todo_map = {"1": parent, "1.1": child, "1.1.1": grandchild}
        result = _flatten_descendants(parent, todo_map)
        assert len(result) == 2
        assert result[0][0] == "1.1 \u2014 Child"
        assert result[1][0] == "1.1.1 \u2014 Grandchild"

    def test_multiple_children(self) -> None:
        parent = Todo(id="1", title="Parent", children=["1.1", "1.2"])
        child1 = Todo(id="1.1", title="First", parent="1")
        child2 = Todo(id="1.2", title="Second", parent="1")
        todo_map = {"1": parent, "1.1": child1, "1.2": child2}
        result = _flatten_descendants(parent, todo_map)
        assert len(result) == 2
        assert result[0][0] == "1.1 \u2014 First"
        assert result[1][0] == "1.2 \u2014 Second"

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
        assert items[0]["name"] == "1.1 \u2014 Child"

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
        """Deep hierarchy gets flattened with dotted ID path and em dash."""
        root = Todo(id="1", title="Root", children=["1.1"])
        child = Todo(id="1.1", title="Child", parent="1", children=["1.1.1"])
        grandchild = Todo(id="1.1.1", title="Grand", parent="1.1")
        checklists, _ = build_expected_state([root, child, grandchild])
        assert len(checklists) == 1
        items = checklists[0]["items"]
        assert isinstance(items, list)
        assert len(items) == 2
        assert items[0]["name"] == "1.1 \u2014 Child"
        assert items[1]["name"] == "1.1.1 \u2014 Grand"


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
                _make_check_item("item1", "1.1 \u2014 Child"),
            ]),
        ])
        plan = compute_diff(card_json, cfg, name)
        assert len(plan.push_rename_checklist) == 1
        assert plan.push_rename_checklist[0]["name"] == "New Name"

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


# ── Last-changed-wins diff tests ─────────────────────────────────────────────


class TestLastChangedWins:
    """Tests for the timestamp-based last-changed-wins sync logic."""

    def test_local_only_change_pushes(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """When only local has changed since last sync, push to Trello."""
        cfg, name = cfg_with_project
        # Create todo with sync state recorded at t0
        t0 = "2026-03-19T10:00:00"
        t1 = "2026-03-19T11:00:00"  # local updated after sync
        todo = _make_todo(
            cfg, name, "Updated locally",
            trello_checklist_item_id="item1",
            trello_sync_state=TrelloSyncState(
                last_sync=t0,
                synced_name="Original name",
                synced_state="incomplete",
            ),
        )
        todo.updated = t1  # local changed after sync
        storage.save_todos(cfg, name, [todo])

        # Trello still has the old name (matches snapshot)
        card_json = _make_trello_card_json([
            _make_checklist("cl1", TASKS_CHECKLIST_NAME, [
                _make_check_item("item1", "Original name", state="incomplete"),
            ]),
        ])
        plan = compute_diff(card_json, cfg, name)
        # Should push the local name
        assert len(plan.push_update_item) == 1
        assert plan.push_update_item[0]["name"] == "Updated locally"
        # No pulls
        assert len(plan.pull_update) == 0
        assert len(plan.pull_complete) == 0

    def test_trello_only_change_pulls(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """When only Trello has changed since last sync, pull from Trello."""
        cfg, name = cfg_with_project
        t0 = "2026-03-19T10:00:00"
        todo = _make_todo(
            cfg, name, "Old title",
            trello_checklist_item_id="item1",
            trello_sync_state=TrelloSyncState(
                last_sync=t0,
                synced_name="Old title",
                synced_state="incomplete",
            ),
        )
        todo.updated = "2026-03-19T09:00:00"  # not changed since sync
        storage.save_todos(cfg, name, [todo])

        # Trello has a new name (different from snapshot)
        card_json = _make_trello_card_json([
            _make_checklist("cl1", TASKS_CHECKLIST_NAME, [
                _make_check_item("item1", "Updated in Trello", state="incomplete"),
            ]),
        ])
        plan = compute_diff(card_json, cfg, name)
        # Should pull the Trello name
        assert len(plan.pull_update) == 1
        assert plan.pull_update[0]["title"] == "Updated in Trello"
        # No pushes for this item
        assert len(plan.push_update_item) == 0

    def test_trello_only_state_change_pulls_complete(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """When Trello checks an item and local hasn't changed, pull complete."""
        cfg, name = cfg_with_project
        t0 = "2026-03-19T10:00:00"
        todo = _make_todo(
            cfg, name, "Task",
            trello_checklist_item_id="item1",
            trello_sync_state=TrelloSyncState(
                last_sync=t0,
                synced_name="Task",
                synced_state="incomplete",
            ),
        )
        todo.updated = "2026-03-19T09:00:00"  # not changed since sync
        storage.save_todos(cfg, name, [todo])

        card_json = _make_trello_card_json([
            _make_checklist("cl1", TASKS_CHECKLIST_NAME, [
                _make_check_item("item1", "Task", state="complete"),
            ]),
        ])
        plan = compute_diff(card_json, cfg, name)
        assert len(plan.pull_complete) == 1
        assert plan.pull_complete[0] == todo.id

    def test_both_changed_shows_conflict(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """When both local and Trello changed, report conflict (prefer local)."""
        cfg, name = cfg_with_project
        t0 = "2026-03-19T10:00:00"
        t1 = "2026-03-19T11:00:00"
        todo = _make_todo(
            cfg, name, "Local version",
            trello_checklist_item_id="item1",
            trello_sync_state=TrelloSyncState(
                last_sync=t0,
                synced_name="Original",
                synced_state="incomplete",
            ),
        )
        todo.updated = t1  # local changed after sync
        storage.save_todos(cfg, name, [todo])

        # Trello also changed (name differs from snapshot)
        card_json = _make_trello_card_json([
            _make_checklist("cl1", TASKS_CHECKLIST_NAME, [
                _make_check_item("item1", "Trello version", state="incomplete"),
            ]),
        ])
        plan = compute_diff(card_json, cfg, name)
        # Should have a conflict
        assert len(plan.conflicts) == 1
        assert plan.conflicts[0]["todo_id"] == todo.id
        assert plan.conflicts[0]["resolution"] == "local"
        # Local wins -> push
        assert len(plan.push_update_item) == 1
        assert plan.push_update_item[0]["name"] == "Local version"
        # No pull
        assert len(plan.pull_update) == 0

    def test_neither_changed_skips(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """When neither local nor Trello changed since last sync, skip."""
        cfg, name = cfg_with_project
        t0 = "2026-03-19T10:00:00"
        todo = _make_todo(
            cfg, name, "Stable",
            trello_checklist_item_id="item1",
            trello_sync_state=TrelloSyncState(
                last_sync=t0,
                synced_name="Stable",
                synced_state="incomplete",
            ),
        )
        todo.updated = "2026-03-19T09:00:00"  # not changed since sync
        storage.save_todos(cfg, name, [todo])

        # Trello matches snapshot
        card_json = _make_trello_card_json([
            _make_checklist("cl1", TASKS_CHECKLIST_NAME, [
                _make_check_item("item1", "Stable", state="incomplete"),
            ]),
        ])
        plan = compute_diff(card_json, cfg, name)
        # Nothing should happen
        assert len(plan.pull_update) == 0
        assert len(plan.pull_complete) == 0
        assert len(plan.pull_reopen) == 0
        assert len(plan.push_update_item) == 0
        assert len(plan.push_complete_item) == 0
        assert len(plan.conflicts) == 0

    def test_first_sync_no_snapshot_uses_comparison(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """First sync (no trello_sync_state) falls back to direct comparison."""
        cfg, name = cfg_with_project
        # Todo without trello_sync_state
        todo = _make_todo(
            cfg, name, "Local title",
            trello_checklist_item_id="item1",
        )
        storage.save_todos(cfg, name, [todo])

        # Trello has a different name
        card_json = _make_trello_card_json([
            _make_checklist("cl1", TASKS_CHECKLIST_NAME, [
                _make_check_item("item1", "Different name", state="incomplete"),
            ]),
        ])
        plan = compute_diff(card_json, cfg, name)
        # First sync: local wins, so push local name
        assert len(plan.push_update_item) == 1
        assert plan.push_update_item[0]["name"] == "Local title"

    def test_first_sync_checked_in_trello_pulls(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """First sync: if Trello checked but local pending, pull complete."""
        cfg, name = cfg_with_project
        todo = _make_todo(
            cfg, name, "Task",
            trello_checklist_item_id="item1",
        )
        storage.save_todos(cfg, name, [todo])

        card_json = _make_trello_card_json([
            _make_checklist("cl1", TASKS_CHECKLIST_NAME, [
                _make_check_item("item1", "Task", state="complete"),
            ]),
        ])
        plan = compute_diff(card_json, cfg, name)
        assert len(plan.pull_complete) == 1


# ── Nesting format tests ─────────────────────────────────────────────────────


class TestNestingFormat:
    """Tests for the dotted ID path with em dash format."""

    def test_child_display_name(self) -> None:
        parent = Todo(id="2", title="Parent", children=["2.1"])
        child = Todo(id="2.1", title="Child task", parent="2")
        todo_map = {"2": parent, "2.1": child}
        result = _flatten_descendants(parent, todo_map)
        assert result[0][0] == "2.1 \u2014 Child task"

    def test_grandchild_display_name(self) -> None:
        root = Todo(id="2", title="Root", children=["2.3"])
        mid = Todo(id="2.3", title="Mid", parent="2", children=["2.3.1"])
        leaf = Todo(id="2.3.1", title="Leaf", parent="2.3")
        todo_map = {"2": root, "2.3": mid, "2.3.1": leaf}
        result = _flatten_descendants(root, todo_map)
        assert len(result) == 2
        assert result[0][0] == "2.3 \u2014 Mid"
        assert result[1][0] == "2.3.1 \u2014 Leaf"

    def test_strip_new_format(self) -> None:
        assert _strip_id_prefix("2.3.1 \u2014 My task") == "My task"

    def test_strip_old_format_still_works(self) -> None:
        assert _strip_id_prefix("1.1: Old style") == "Old style"


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

    def test_apply_records_sync_state(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """After apply, synced todos should have trello_sync_state set."""
        cfg, name = cfg_with_project
        todo = _make_todo(cfg, name, "Linked", trello_checklist_item_id="item1")
        storage.save_todos(cfg, name, [todo])

        data = TrelloApplyInput(
            link_trello_ids=[{
                "todo_id": todo.id,
                "trello_checklist_item_id": "item1",
            }],
        )
        apply_changes(data, cfg, name)
        todos = storage.load_todos(cfg, name)
        assert todos[0].trello_sync_state is not None
        assert todos[0].trello_sync_state.last_sync != ""
        assert todos[0].trello_sync_state.synced_name == "Linked"
        assert todos[0].trello_sync_state.synced_state == "incomplete"

    def test_apply_records_sync_state_for_done(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """After completing a child via apply, sync state should be 'complete'."""
        cfg, name = cfg_with_project
        parent = _make_todo(cfg, name, "Parent", trello_checklist_id="cl1")
        child = _make_todo(cfg, name, "Child", parent=parent.id, trello_checklist_item_id="item1")
        parent.children.append(child.id)
        storage.save_todos(cfg, name, [parent, child])

        data = TrelloApplyInput(completed_locally=[child.id])
        apply_changes(data, cfg, name)
        todos = storage.load_todos(cfg, name)
        child_reloaded = next(t for t in todos if t.id == child.id)
        assert child_reloaded.trello_sync_state is not None
        assert child_reloaded.trello_sync_state.synced_state == "complete"

    def test_updated_field_uses_datetime(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """After apply, updated field should be ISO datetime (contains 'T')."""
        cfg, name = cfg_with_project
        data = TrelloApplyInput(
            created_locally=[{
                "title": "New todo",
                "parent": None,
                "trello_checklist_item_id": "item1",
                "checked": False,
            }],
        )
        apply_changes(data, cfg, name)
        todos = storage.load_todos(cfg, name)
        assert "T" in todos[0].updated  # ISO datetime, not date-only
        assert "T" in todos[0].created


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

    def test_is_empty_false_conflicts(self) -> None:
        plan = TrelloSyncPlan(conflicts=[{"todo_id": "1"}])
        assert not plan.is_empty()

    def test_to_dict_has_summary(self) -> None:
        plan = TrelloSyncPlan(push_create_item=[{"name": "x"}])
        d = plan.to_dict()
        assert d["summary"]["push_create_item_count"] == 1  # type: ignore[index]
        assert d["summary"]["pull_create_count"] == 0  # type: ignore[index]

    def test_to_dict_has_conflict_count(self) -> None:
        plan = TrelloSyncPlan(conflicts=[{"todo_id": "1"}])
        d = plan.to_dict()
        assert d["summary"]["conflict_count"] == 1  # type: ignore[index]


# ── TrelloSyncState model tests ─────────────────────────────────────────────


class TestTrelloSyncState:
    def test_to_dict(self) -> None:
        ss = TrelloSyncState(
            last_sync="2026-03-19T14:30:00",
            synced_name="Task name",
            synced_state="incomplete",
        )
        d = ss.to_dict()
        assert d["last_sync"] == "2026-03-19T14:30:00"
        assert d["synced_name"] == "Task name"
        assert d["synced_state"] == "incomplete"

    def test_from_dict(self) -> None:
        d = {
            "last_sync": "2026-03-19T14:30:00",
            "synced_name": "Task name",
            "synced_state": "complete",
        }
        ss = TrelloSyncState.from_dict(d)
        assert ss.last_sync == "2026-03-19T14:30:00"
        assert ss.synced_name == "Task name"
        assert ss.synced_state == "complete"

    def test_todo_roundtrip_with_sync_state(self) -> None:
        todo = Todo(
            id="1",
            title="Test",
            trello_sync_state=TrelloSyncState(
                last_sync="2026-03-19T14:30:00",
                synced_name="Test",
                synced_state="incomplete",
            ),
        )
        d = todo.to_dict()
        restored = Todo.from_dict(d)
        assert restored.trello_sync_state is not None
        assert restored.trello_sync_state.last_sync == "2026-03-19T14:30:00"
        assert restored.trello_sync_state.synced_name == "Test"

    def test_todo_roundtrip_without_sync_state(self) -> None:
        todo = Todo(id="1", title="Test")
        d = todo.to_dict()
        restored = Todo.from_dict(d)
        assert restored.trello_sync_state is None

    def test_backward_compat_date_only_updated(self) -> None:
        """Todo.from_dict should accept both date-only and datetime updated strings."""
        d = {
            "id": "1",
            "title": "Test",
            "updated": "2026-03-19",  # date-only (legacy)
        }
        todo = Todo.from_dict(d)
        assert todo.updated == "2026-03-19"

    def test_backward_compat_datetime_updated(self) -> None:
        d = {
            "id": "1",
            "title": "Test",
            "updated": "2026-03-19T14:30:00",  # datetime (new)
        }
        todo = Todo.from_dict(d)
        assert todo.updated == "2026-03-19T14:30:00"


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


# ── Auto-linking verification tests (231) ───────────────────────────────────
#
# These tests verify that pull-sync from Trello (232.9) atomically stores
# trello IDs on newly created local todos and records trello_sync_state.


class TestAutoLinkingPullCreate:
    """Verify auto-linking: items created in Trello and pulled locally
    get their Trello IDs stored on the local todo atomically."""

    def test_pull_create_stores_trello_checklist_item_id(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """apply_changes sets trello_checklist_item_id on newly created child todos."""
        cfg, name = cfg_with_project
        parent = _make_todo(cfg, name, "Parent", trello_checklist_id="cl1")
        storage.save_todos(cfg, name, [parent])

        data = TrelloApplyInput(
            created_locally=[{
                "title": "New from Trello",
                "parent": parent.id,
                "trello_checklist_item_id": "trello_item_99",
                "checked": False,
            }],
        )
        counts = apply_changes(data, cfg, name)
        assert counts["created"] == 1

        todos = storage.load_todos(cfg, name)
        child = next(t for t in todos if t.title == "New from Trello")
        assert child.trello_checklist_item_id == "trello_item_99"

    def test_pull_create_root_stores_trello_checklist_id(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """apply_changes sets trello_checklist_id on newly created root todos."""
        cfg, name = cfg_with_project
        data = TrelloApplyInput(
            created_root_locally=[{
                "title": "Feature from Trello",
                "trello_checklist_id": "cl_trello_42",
            }],
        )
        counts = apply_changes(data, cfg, name)
        assert counts["created_root"] == 1

        todos = storage.load_todos(cfg, name)
        root = next(t for t in todos if t.title == "Feature from Trello")
        assert root.trello_checklist_id == "cl_trello_42"

    def test_pull_create_records_sync_state_atomically(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """After apply, newly pulled todos have trello_sync_state recorded."""
        cfg, name = cfg_with_project
        data = TrelloApplyInput(
            created_locally=[{
                "title": "Pulled item",
                "parent": None,
                "trello_checklist_item_id": "item_abc",
                "checked": False,
            }],
        )
        apply_changes(data, cfg, name)

        todos = storage.load_todos(cfg, name)
        todo = next(t for t in todos if t.title == "Pulled item")
        assert todo.trello_checklist_item_id == "item_abc"
        assert todo.trello_sync_state is not None
        assert todo.trello_sync_state.last_sync != ""
        assert todo.trello_sync_state.synced_name == "Pulled item"
        assert todo.trello_sync_state.synced_state == "incomplete"

    def test_pull_create_checked_records_complete_sync_state(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """Pulling a checked Trello item records synced_state='complete'."""
        cfg, name = cfg_with_project
        parent = _make_todo(cfg, name, "Parent", trello_checklist_id="cl1")
        storage.save_todos(cfg, name, [parent])

        data = TrelloApplyInput(
            created_locally=[{
                "title": "Already done in Trello",
                "parent": parent.id,
                "trello_checklist_item_id": "item_done",
                "checked": True,
            }],
        )
        apply_changes(data, cfg, name)

        todos = storage.load_todos(cfg, name)
        child = next(t for t in todos if t.title == "Already done in Trello")
        assert child.status == "done"
        assert child.trello_checklist_item_id == "item_done"
        assert child.trello_sync_state is not None
        assert child.trello_sync_state.synced_state == "complete"

    def test_pull_create_root_records_sync_state(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """After apply, newly pulled root todos have trello_sync_state recorded."""
        cfg, name = cfg_with_project
        data = TrelloApplyInput(
            created_root_locally=[{
                "title": "New Root Feature",
                "trello_checklist_id": "cl_new_root",
            }],
        )
        apply_changes(data, cfg, name)

        todos = storage.load_todos(cfg, name)
        root = next(t for t in todos if t.title == "New Root Feature")
        assert root.trello_checklist_id == "cl_new_root"
        assert root.trello_sync_state is not None
        assert root.trello_sync_state.last_sync != ""


class TestAutoLinkingAutoApply:
    """Verify auto_apply=True in proj_trello_diff stores Trello IDs and
    sync state on locally-created todos in one atomic operation."""

    def _get_diff_fn(self) -> object:
        from unittest.mock import MagicMock
        from server.tools.trello_sync import register
        app = MagicMock()
        tools: dict[str, object] = {}
        app.tool = lambda **kw: lambda fn: tools.update({fn.__name__: fn}) or fn
        register(app)
        return tools["proj_trello_diff"]

    def test_auto_apply_pull_create_stores_item_id(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """auto_apply=True: new Trello checklist items get trello_checklist_item_id stored."""
        cfg, name = cfg_with_project
        parent = _make_todo(cfg, name, "Parent", trello_checklist_id="cl1")
        storage.save_todos(cfg, name, [parent])

        diff_fn = self._get_diff_fn()
        card_json = _make_trello_card_json([
            _make_checklist("cl1", "Parent", [
                _make_check_item("item_from_trello", "New task from Trello"),
            ]),
        ])
        result = json.loads(diff_fn(  # type: ignore[operator]
            trello_card_json=card_json,
            auto_apply=True,
            project_name=name,
        ))
        assert result["auto_applied"]["created"] == 1

        todos = storage.load_todos(cfg, name)
        child = next(t for t in todos if t.title == "New task from Trello")
        assert child.trello_checklist_item_id == "item_from_trello"
        assert child.parent == parent.id

    def test_auto_apply_pull_create_root_stores_checklist_id(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """auto_apply=True: new Trello checklists get trello_checklist_id stored."""
        cfg, name = cfg_with_project
        diff_fn = self._get_diff_fn()
        card_json = _make_trello_card_json([
            _make_checklist("cl_brand_new", "Brand New Feature"),
        ])
        result = json.loads(diff_fn(  # type: ignore[operator]
            trello_card_json=card_json,
            auto_apply=True,
            project_name=name,
        ))
        assert result["auto_applied"]["created_root"] == 1

        todos = storage.load_todos(cfg, name)
        root = next(t for t in todos if t.title == "Brand New Feature")
        assert root.trello_checklist_id == "cl_brand_new"

    def test_auto_apply_pull_create_records_sync_state(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """auto_apply=True: pulled items get trello_sync_state recorded atomically."""
        cfg, name = cfg_with_project
        parent = _make_todo(cfg, name, "Parent", trello_checklist_id="cl1")
        storage.save_todos(cfg, name, [parent])

        diff_fn = self._get_diff_fn()
        card_json = _make_trello_card_json([
            _make_checklist("cl1", "Parent", [
                _make_check_item("item_x", "Pulled task"),
            ]),
        ])
        json.loads(diff_fn(  # type: ignore[operator]
            trello_card_json=card_json,
            auto_apply=True,
            project_name=name,
        ))

        todos = storage.load_todos(cfg, name)
        child = next(t for t in todos if t.title == "Pulled task")
        assert child.trello_checklist_item_id == "item_x"
        assert child.trello_sync_state is not None
        assert child.trello_sync_state.last_sync != ""
        assert child.trello_sync_state.synced_state == "incomplete"

    def test_auto_apply_pull_create_checked_records_complete(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """auto_apply=True: checked Trello item is created as done with complete sync state."""
        cfg, name = cfg_with_project
        parent = _make_todo(cfg, name, "Parent", trello_checklist_id="cl1")
        storage.save_todos(cfg, name, [parent])

        diff_fn = self._get_diff_fn()
        card_json = _make_trello_card_json([
            _make_checklist("cl1", "Parent", [
                _make_check_item("item_done", "Done in Trello", state="complete"),
            ]),
        ])
        json.loads(diff_fn(  # type: ignore[operator]
            trello_card_json=card_json,
            auto_apply=True,
            project_name=name,
        ))

        todos = storage.load_todos(cfg, name)
        child = next(t for t in todos if t.title == "Done in Trello")
        assert child.status == "done"
        assert child.trello_checklist_item_id == "item_done"
        assert child.trello_sync_state is not None
        assert child.trello_sync_state.synced_state == "complete"

    def test_auto_apply_pull_create_multiple_items_all_linked(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """auto_apply=True: multiple new Trello items all get unique IDs stored."""
        cfg, name = cfg_with_project
        parent = _make_todo(cfg, name, "Parent", trello_checklist_id="cl1")
        storage.save_todos(cfg, name, [parent])

        diff_fn = self._get_diff_fn()
        card_json = _make_trello_card_json([
            _make_checklist("cl1", "Parent", [
                _make_check_item("item_a", "Task A"),
                _make_check_item("item_b", "Task B"),
                _make_check_item("item_c", "Task C", state="complete"),
            ]),
        ])
        result = json.loads(diff_fn(  # type: ignore[operator]
            trello_card_json=card_json,
            auto_apply=True,
            project_name=name,
        ))
        assert result["auto_applied"]["created"] == 3

        todos = storage.load_todos(cfg, name)
        created_items = [t for t in todos if t.id != parent.id]
        assert len(created_items) == 3

        item_ids = {t.trello_checklist_item_id for t in created_items}
        assert item_ids == {"item_a", "item_b", "item_c"}

        # All should have sync state
        for t in created_items:
            assert t.trello_sync_state is not None
            assert t.trello_sync_state.last_sync != ""

    def test_diff_pull_create_includes_trello_item_id(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """compute_diff records trello_checklist_item_id in pull_create entries."""
        cfg, name = cfg_with_project
        parent = _make_todo(cfg, name, "Parent", trello_checklist_id="cl1")
        storage.save_todos(cfg, name, [parent])

        card_json = _make_trello_card_json([
            _make_checklist("cl1", "Parent", [
                _make_check_item("item_77", "From Trello board"),
            ]),
        ])
        plan = compute_diff(card_json, cfg, name)
        assert len(plan.pull_create) == 1
        assert plan.pull_create[0]["trello_checklist_item_id"] == "item_77"
        assert plan.pull_create[0]["parent"] == parent.id
        assert plan.pull_create[0]["title"] == "From Trello board"

    def test_diff_pull_create_root_includes_trello_checklist_id(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """compute_diff records trello_checklist_id in pull_create_root entries."""
        cfg, name = cfg_with_project
        card_json = _make_trello_card_json([
            _make_checklist("cl_new_55", "New Feature Root"),
        ])
        plan = compute_diff(card_json, cfg, name)
        assert len(plan.pull_create_root) == 1
        assert plan.pull_create_root[0]["trello_checklist_id"] == "cl_new_55"
        assert plan.pull_create_root[0]["title"] == "New Feature Root"


# ── push_complete_item verification tests (todo 230) ────────────────────────


class TestPushCompleteItem:
    """Verify that completing a local todo produces push_complete_item in the diff.

    This is the core scenario for todo 230: when a user marks a todo as done
    locally, the next Trello sync must push the completion to Trello.
    """

    def test_local_complete_with_sync_state_pushes_complete(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """Last-changed-wins: local completed after sync -> push_complete_item."""
        cfg, name = cfg_with_project
        t0 = "2026-03-19T10:00:00"
        t1 = "2026-03-19T11:00:00"
        todo = _make_todo(
            cfg, name, "Finished task",
            status="done",
            trello_checklist_item_id="item1",
            trello_sync_state=TrelloSyncState(
                last_sync=t0,
                synced_name="Finished task",
                synced_state="incomplete",
            ),
        )
        todo.updated = t1  # completed after last sync
        storage.save_todos(cfg, name, [todo])

        card_json = _make_trello_card_json([
            _make_checklist("cl1", TASKS_CHECKLIST_NAME, [
                _make_check_item("item1", "Finished task", state="incomplete"),
            ]),
        ])
        plan = compute_diff(card_json, cfg, name)
        assert len(plan.push_complete_item) == 1
        assert plan.push_complete_item[0]["item_id"] == "item1"
        assert plan.push_complete_item[0]["state"] == "complete"
        # No pull operations
        assert len(plan.pull_complete) == 0
        assert len(plan.pull_reopen) == 0

    def test_local_complete_child_with_sync_state_pushes_complete(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """Child todo completed locally -> push_complete_item in parent's checklist."""
        cfg, name = cfg_with_project
        t0 = "2026-03-19T10:00:00"
        t1 = "2026-03-19T11:00:00"
        parent = _make_todo(cfg, name, "Parent", trello_checklist_id="cl1")
        child = _make_todo(
            cfg, name, "Child",
            parent=parent.id,
            status="done",
            trello_checklist_item_id="item1",
            trello_sync_state=TrelloSyncState(
                last_sync=t0,
                synced_name="1.1 \u2014 Child",
                synced_state="incomplete",
            ),
        )
        child.updated = t1
        parent.children.append(child.id)
        storage.save_todos(cfg, name, [parent, child])

        card_json = _make_trello_card_json([
            _make_checklist("cl1", "Parent", [
                _make_check_item("item1", "1.1 \u2014 Child", state="incomplete"),
            ]),
        ])
        plan = compute_diff(card_json, cfg, name)
        assert len(plan.push_complete_item) == 1
        assert plan.push_complete_item[0]["item_id"] == "item1"
        assert plan.push_complete_item[0]["checklist_id"] == "cl1"

    def test_first_sync_local_done_pushes_complete(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """First sync migration: local done + Trello incomplete -> push_complete_item."""
        cfg, name = cfg_with_project
        todo = _make_todo(
            cfg, name, "Done locally",
            status="done",
            trello_checklist_item_id="item1",
            # No trello_sync_state — first sync
        )
        storage.save_todos(cfg, name, [todo])

        card_json = _make_trello_card_json([
            _make_checklist("cl1", TASKS_CHECKLIST_NAME, [
                _make_check_item("item1", "Done locally", state="incomplete"),
            ]),
        ])
        plan = compute_diff(card_json, cfg, name)
        assert len(plan.push_complete_item) == 1
        assert plan.push_complete_item[0]["item_id"] == "item1"
        assert plan.push_complete_item[0]["state"] == "complete"

    def test_local_complete_conflict_still_pushes(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """Both sides changed, local completed -> conflict with local-wins push_complete."""
        cfg, name = cfg_with_project
        t0 = "2026-03-19T10:00:00"
        t1 = "2026-03-19T11:00:00"
        todo = _make_todo(
            cfg, name, "Done",
            status="done",
            trello_checklist_item_id="item1",
            trello_sync_state=TrelloSyncState(
                last_sync=t0,
                synced_name="Original",
                synced_state="incomplete",
            ),
        )
        todo.updated = t1
        storage.save_todos(cfg, name, [todo])

        # Trello also changed (name differs from snapshot)
        card_json = _make_trello_card_json([
            _make_checklist("cl1", TASKS_CHECKLIST_NAME, [
                _make_check_item("item1", "Renamed in Trello", state="incomplete"),
            ]),
        ])
        plan = compute_diff(card_json, cfg, name)
        # Conflict detected
        assert len(plan.conflicts) == 1
        assert plan.conflicts[0]["resolution"] == "local"
        # Local wins: push complete
        assert len(plan.push_complete_item) == 1
        assert plan.push_complete_item[0]["state"] == "complete"

    def test_already_complete_both_sides_no_push(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """Both local and Trello are complete, synced state matches -> no push."""
        cfg, name = cfg_with_project
        t0 = "2026-03-19T10:00:00"
        todo = _make_todo(
            cfg, name, "Already done",
            status="done",
            trello_checklist_item_id="item1",
            trello_sync_state=TrelloSyncState(
                last_sync=t0,
                synced_name="Already done",
                synced_state="complete",
            ),
        )
        todo.updated = "2026-03-19T09:00:00"  # not changed since sync
        storage.save_todos(cfg, name, [todo])

        card_json = _make_trello_card_json([
            _make_checklist("cl1", TASKS_CHECKLIST_NAME, [
                _make_check_item("item1", "Already done", state="complete"),
            ]),
        ])
        plan = compute_diff(card_json, cfg, name)
        # Neither side changed -> no push, no pull
        assert len(plan.push_complete_item) == 0
        assert len(plan.pull_complete) == 0

    def test_auto_apply_includes_push_complete_in_plan(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """auto_apply mode: push_complete_item is in the returned plan for execution."""
        cfg, name = cfg_with_project
        t0 = "2026-03-19T10:00:00"
        t1 = "2026-03-19T11:00:00"
        todo = _make_todo(
            cfg, name, "Completed",
            status="done",
            trello_checklist_item_id="item1",
            trello_sync_state=TrelloSyncState(
                last_sync=t0,
                synced_name="Completed",
                synced_state="incomplete",
            ),
        )
        todo.updated = t1
        storage.save_todos(cfg, name, [todo])

        from unittest.mock import MagicMock
        from server.tools.trello_sync import register
        app = MagicMock()
        tools: dict[str, object] = {}
        app.tool = lambda **kw: lambda fn: tools.update({fn.__name__: fn}) or fn
        register(app)
        diff_fn = tools["proj_trello_diff"]

        card_json = _make_trello_card_json([
            _make_checklist("cl1", TASKS_CHECKLIST_NAME, [
                _make_check_item("item1", "Completed", state="incomplete"),
            ]),
        ])
        result = json.loads(diff_fn(  # type: ignore[operator]
            trello_card_json=card_json,
            auto_apply=True,
            project_name=name,
        ))
        assert result["plan"]["summary"]["push_complete_item_count"] == 1
        assert len(result["plan"]["push_complete_item"]) == 1
        assert result["plan"]["push_complete_item"][0]["item_id"] == "item1"


class TestTasksChecklistIdLookup:
    """Tests for ID-based Tasks checklist lookup (todo 243)."""

    def test_stored_id_used_when_valid(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """When meta has a stored Tasks checklist ID that exists in Trello, use it."""
        cfg, name = cfg_with_project

        # Store a Tasks checklist ID on meta
        meta = storage.load_meta(cfg, name)
        meta.trello.trello_tasks_checklist_id = "cl_tasks_stored"
        storage.save_meta(cfg, meta)

        # Create a leaf todo
        t1 = _make_todo(cfg, name, "Leaf task", trello_checklist_item_id="item1")
        storage.save_todos(cfg, name, [t1])

        # Trello has the Tasks checklist with the stored ID
        card_json = _make_trello_card_json([
            _make_checklist("cl_tasks_stored", TASKS_CHECKLIST_NAME, [
                _make_check_item("item1", "Leaf task"),
            ]),
        ])

        plan = compute_diff(card_json, cfg, name)

        # Verify stored ID was not cleared/changed
        meta_after = storage.load_meta(cfg, name)
        assert meta_after.trello.trello_tasks_checklist_id == "cl_tasks_stored"
        # The plan should be clean (no creates needed)
        assert not plan.push_create_checklist

    def test_name_fallback_when_no_stored_id(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """When no stored ID, fall back to name-based scan and store the found ID."""
        cfg, name = cfg_with_project

        # No stored ID
        meta = storage.load_meta(cfg, name)
        assert meta.trello.trello_tasks_checklist_id is None

        # Create a leaf todo
        t1 = _make_todo(cfg, name, "Leaf task", trello_checklist_item_id="item1")
        storage.save_todos(cfg, name, [t1])

        card_json = _make_trello_card_json([
            _make_checklist("cl_found_by_name", TASKS_CHECKLIST_NAME, [
                _make_check_item("item1", "Leaf task"),
            ]),
        ])

        plan = compute_diff(card_json, cfg, name)

        # Should have stored the ID found by name
        meta_after = storage.load_meta(cfg, name)
        assert meta_after.trello.trello_tasks_checklist_id == "cl_found_by_name"
        assert not plan.push_create_checklist

    def test_stale_id_recovery(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """When stored ID no longer exists in Trello, fall back to name scan."""
        cfg, name = cfg_with_project

        # Store a stale ID
        meta = storage.load_meta(cfg, name)
        meta.trello.trello_tasks_checklist_id = "cl_old_gone"
        storage.save_meta(cfg, meta)

        # Create a leaf todo
        t1 = _make_todo(cfg, name, "Leaf task", trello_checklist_item_id="item1")
        storage.save_todos(cfg, name, [t1])

        # Trello has the Tasks checklist with a DIFFERENT ID (old one is gone)
        card_json = _make_trello_card_json([
            _make_checklist("cl_new_id", TASKS_CHECKLIST_NAME, [
                _make_check_item("item1", "Leaf task"),
            ]),
        ])

        plan = compute_diff(card_json, cfg, name)

        # Should have recovered to the new ID
        meta_after = storage.load_meta(cfg, name)
        assert meta_after.trello.trello_tasks_checklist_id == "cl_new_id"
        assert not plan.push_create_checklist

    def test_apply_stores_tasks_checklist_id(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """When linking _tasks sentinel, apply_changes stores ID on meta."""
        cfg, name = cfg_with_project

        meta = storage.load_meta(cfg, name)
        assert meta.trello.trello_tasks_checklist_id is None

        data = TrelloApplyInput(
            link_trello_ids=[
                {"todo_id": "_tasks", "trello_checklist_id": "cl_tasks_new"},
            ],
        )
        counts = apply_changes(data, cfg, name)
        assert counts["linked"] == 1

        meta_after = storage.load_meta(cfg, name)
        assert meta_after.trello.trello_tasks_checklist_id == "cl_tasks_new"

    def test_backward_compat_no_stored_id_no_tasks_checklist(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """With no stored ID and no Tasks checklist in Trello, push_create_checklist is emitted."""
        cfg, name = cfg_with_project

        # No stored ID
        meta = storage.load_meta(cfg, name)
        assert meta.trello.trello_tasks_checklist_id is None

        # Create a leaf todo (not yet linked to Trello)
        t1 = _make_todo(cfg, name, "Leaf task")
        storage.save_todos(cfg, name, [t1])

        # Trello card has no checklists at all
        card_json = _make_trello_card_json([])

        plan = compute_diff(card_json, cfg, name)

        # Should request creating the Tasks checklist
        tasks_creates = [c for c in plan.push_create_checklist if c["name"] == TASKS_CHECKLIST_NAME]
        assert len(tasks_creates) == 1
        assert tasks_creates[0]["todo_id"] == "_tasks"
