"""Tests for trello_sync tools — card-per-todo model (v2).

Covers: format_card_title, parse_card_title, build_card_description,
compute_desc_hash, compute_diff (card-based), TrelloSyncPlan,
_topo_sort_todos, apply_changes.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
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
    RepoEntry,
    Todo,
    TrelloListMappings,
    TrelloSync,
    TrelloSyncState,
)
from server.tools.trello_sync import (
    TrelloApplyInput,
    TrelloSyncPlan,
    _topo_sort_todos,
    apply_changes,
    build_card_description,
    compute_desc_hash,
    compute_diff,
    format_card_title,
    parse_card_title,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def cfg_with_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[ProjConfig, str]:
    config_path = tmp_path / "proj.yaml"
    monkeypatch.setattr(storage, "_DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.delenv("PROJ_CONFIG", raising=False)

    cfg = ProjConfig(
        tracking_dir=str(tmp_path / "tracking"),
        trello=TrelloSync(
            enabled=True,
            default_board_id="board123",
            list_mappings=TrelloListMappings(
                tasks="proj-tasks",
                done="Done",
                projects="Projects",
            ),
        ),
    )
    storage.save_config(cfg)

    now = datetime.now(tz=UTC).replace(tzinfo=None).isoformat()
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
    now = datetime.now(tz=UTC).replace(tzinfo=None).isoformat()
    parent_todo = None
    if kwargs.get("parent"):
        todos = storage.load_todos(cfg, name)
        parent_todo = next((t for t in todos if t.id == kwargs["parent"]), None)
    todo = Todo(id=next_todo_id(meta, parent=parent_todo), title=title, created=now, updated=now)
    for k, v in kwargs.items():
        setattr(todo, k, v)
    storage.save_meta(cfg, meta)
    return todo


def _make_trello_data(
    cards: list[dict] | None = None,
    lists: list[dict] | None = None,
    project_card: dict | None = None,
) -> str:
    """Build a JSON string in the format expected by compute_diff."""
    data: dict = {}
    if cards is not None:
        data["cards"] = cards
    if lists is not None:
        data["lists"] = lists
    if project_card is not None:
        data["project_card"] = project_card
    return json.dumps(data)


# ── TestCardTitleFormat ────────────────────────────────────────────────────────


class TestCardTitleFormat:
    def test_format_basic(self) -> None:
        result = format_card_title("myapp", "1", "Fix the bug")
        assert result == "[myapp] [1] Fix the bug"

    def test_format_nested_id(self) -> None:
        result = format_card_title("proj", "1.2.3", "Deep task")
        assert result == "[proj] [1.2.3] Deep task"

    def test_parse_basic(self) -> None:
        parsed = parse_card_title("[myapp] [1] Fix the bug")
        assert parsed is not None
        assert parsed == ("myapp", "1", "Fix the bug")

    def test_parse_nested_id(self) -> None:
        parsed = parse_card_title("[proj] [1.2.3] Deep task")
        assert parsed is not None
        assert parsed == ("proj", "1.2.3", "Deep task")

    def test_parse_roundtrip(self) -> None:
        title = format_card_title("my-project", "42.1", "Implement feature X")
        parsed = parse_card_title(title)
        assert parsed == ("my-project", "42.1", "Implement feature X")

    def test_parse_invalid_no_brackets(self) -> None:
        assert parse_card_title("Just a plain title") is None

    def test_parse_invalid_single_bracket(self) -> None:
        assert parse_card_title("[proj] Missing second bracket") is None

    def test_parse_empty_fields(self) -> None:
        parsed = parse_card_title("[] [] Title")
        assert parsed is not None
        assert parsed == ("", "", "Title")

    def test_format_special_chars(self) -> None:
        result = format_card_title("my app", "1", "Fix: the [bug]")
        assert result == "[my app] [1] Fix: the [bug]"


# ── TestCardDescription ────────────────────────────────────────────────────────


class TestCardDescription:
    def test_basic_fields(self) -> None:
        todo = Todo(id="1", title="Test", status="pending", priority="high")
        desc = build_card_description(todo, "myapp")
        assert "**Status**: pending" in desc
        assert "**Priority**: high" in desc
        assert "**Project**: myapp" in desc

    def test_due_date(self) -> None:
        todo = Todo(id="1", title="Test", due_date="2026-12-31")
        desc = build_card_description(todo)
        assert "**Due**: 2026-12-31" in desc

    def test_tags_sorted(self) -> None:
        todo = Todo(id="1", title="Test", tags=["zebra", "alpha", "mid"])
        desc = build_card_description(todo)
        assert "**Tags**: alpha, mid, zebra" in desc

    def test_blocked_by_sorted(self) -> None:
        todo = Todo(id="1", title="Test", blocked_by=["3", "1", "2"])
        desc = build_card_description(todo)
        assert "**Blocked by**: 1, 2, 3" in desc

    def test_children_listed(self) -> None:
        todo = Todo(id="1", title="Parent", children=["1.1", "1.2"])
        desc = build_card_description(todo)
        assert "**Children**: 1.1, 1.2" in desc

    def test_notes_included(self) -> None:
        todo = Todo(id="1", title="Test", notes="Some notes here")
        desc = build_card_description(todo)
        assert "---" in desc
        assert "Some notes here" in desc

    def test_no_project_name(self) -> None:
        todo = Todo(id="1", title="Test")
        desc = build_card_description(todo)
        assert "**Project**" not in desc

    def test_truncation_at_max_length(self) -> None:
        todo = Todo(id="1", title="Test", notes="x" * 20000)
        desc = build_card_description(todo)
        assert len(desc) <= 16384
        assert desc.endswith("...")

    def test_empty_optional_fields_omitted(self) -> None:
        todo = Todo(id="1", title="Test")
        desc = build_card_description(todo)
        assert "**Due**" not in desc
        assert "**Tags**" not in desc
        assert "**Blocked by**" not in desc
        assert "**Children**" not in desc
        assert "---" not in desc


# ── TestDescHash ───────────────────────────────────────────────────────────────


class TestDescHash:
    def test_deterministic(self) -> None:
        desc = "**Status**: pending\n**Priority**: medium"
        h1 = compute_desc_hash(desc)
        h2 = compute_desc_hash(desc)
        assert h1 == h2

    def test_changes_on_content_change(self) -> None:
        h1 = compute_desc_hash("**Status**: pending")
        h2 = compute_desc_hash("**Status**: done")
        assert h1 != h2

    def test_empty_string(self) -> None:
        h = compute_desc_hash("")
        assert isinstance(h, str)
        assert len(h) == 32  # md5 hex digest

    def test_consistent_for_same_todo(self) -> None:
        todo = Todo(id="1", title="Test", status="pending", priority="high")
        d1 = build_card_description(todo, "proj")
        d2 = build_card_description(todo, "proj")
        assert compute_desc_hash(d1) == compute_desc_hash(d2)


# ── TestTopoSort ──────────────────────────────────────────────────────────────


class TestTopoSort:
    def test_parents_before_children(self) -> None:
        parent = Todo(id="1", title="Parent", children=["1.1"])
        child = Todo(id="1.1", title="Child", parent="1")
        # Feed in child-first order
        result = _topo_sort_todos([child, parent])
        ids = [t.id for t in result]
        assert ids.index("1") < ids.index("1.1")

    def test_independent_todos_preserved(self) -> None:
        a = Todo(id="1", title="A")
        b = Todo(id="2", title="B")
        result = _topo_sort_todos([a, b])
        assert len(result) == 2

    def test_deep_hierarchy(self) -> None:
        root = Todo(id="1", title="Root", children=["1.1"])
        mid = Todo(id="1.1", title="Mid", parent="1", children=["1.1.1"])
        leaf = Todo(id="1.1.1", title="Leaf", parent="1.1")
        result = _topo_sort_todos([leaf, mid, root])
        ids = [t.id for t in result]
        assert ids.index("1") < ids.index("1.1") < ids.index("1.1.1")

    def test_circular_refs_handled(self) -> None:
        """Circular references should not cause infinite loop."""
        a = Todo(id="1", title="A", parent="2")
        b = Todo(id="2", title="B", parent="1")
        # Should not hang
        result = _topo_sort_todos([a, b])
        assert len(result) == 2

    def test_empty_list(self) -> None:
        assert _topo_sort_todos([]) == []

    def test_single_todo(self) -> None:
        t = Todo(id="1", title="Only")
        result = _topo_sort_todos([t])
        assert len(result) == 1
        assert result[0].id == "1"


# ── TestComputeDiff ───────────────────────────────────────────────────────────


class TestComputeDiff:
    def test_empty_both_sides(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        lists = [
            {"id": "l1", "name": "proj-tasks"},
            {"id": "l2", "name": "Done"},
            {"id": "l3", "name": "Projects"},
        ]
        plan = compute_diff(_make_trello_data(cards=[], lists=lists), cfg, name)
        # No todos, no card changes -> only possible non-empty is project_card_update
        assert len(plan.push_create_card) == 0
        assert len(plan.push_update_card) == 0
        assert len(plan.pull_update) == 0
        assert len(plan.pull_complete) == 0

    def test_unlinked_todo_creates_card(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        todo = _make_todo(cfg, name, "New task")
        storage.save_todos(cfg, name, [todo])

        plan = compute_diff(_make_trello_data(cards=[], lists=[]), cfg, name)
        assert len(plan.push_create_card) == 1
        assert plan.push_create_card[0]["todo_id"] == todo.id
        assert "[myapp]" in str(plan.push_create_card[0]["title"])

    def test_linked_todo_no_change(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """Linked todo with matching card title, desc, and list -> no operations."""
        cfg, name = cfg_with_project
        todo = _make_todo(cfg, name, "Task", trello_card_id="card_1")
        expected_title = format_card_title(name, todo.id, todo.title)
        expected_desc = build_card_description(todo, name)
        desc_hash = compute_desc_hash(expected_desc)
        todo.trello_sync_state = TrelloSyncState(
            last_sync="2026-01-01T00:00:00",
            synced_name=expected_title,
            card_id="card_1",
            list_id="list_tasks",
            desc_hash=desc_hash,
        )
        storage.save_todos(cfg, name, [todo])

        cards = [
            {"id": "card_1", "name": expected_title, "desc": expected_desc, "idList": "list_tasks"}
        ]
        lists = [{"id": "list_tasks", "name": "proj-tasks"}, {"id": "list_done", "name": "Done"}]
        plan = compute_diff(_make_trello_data(cards=cards, lists=lists), cfg, name)

        assert len(plan.push_update_card) == 0
        assert len(plan.push_move_card) == 0
        assert len(plan.pull_update) == 0

    def test_linked_todo_local_title_change_pushes(
        self,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """Local title change should push update to Trello."""
        cfg, name = cfg_with_project
        old_title = format_card_title(name, "1", "Old Title")
        old_desc = "**Status**: pending\n**Priority**: medium"
        todo = _make_todo(cfg, name, "New Title", trello_card_id="card_1")
        todo.trello_sync_state = TrelloSyncState(
            last_sync="2026-01-01T00:00:00",
            synced_name=old_title,
            card_id="card_1",
            list_id="list_tasks",
            desc_hash=compute_desc_hash(old_desc),
        )
        storage.save_todos(cfg, name, [todo])

        cards = [{"id": "card_1", "name": old_title, "desc": old_desc, "idList": "list_tasks"}]
        lists = [{"id": "list_tasks", "name": "proj-tasks"}]
        plan = compute_diff(_make_trello_data(cards=cards, lists=lists), cfg, name)

        assert len(plan.push_update_card) == 1
        assert "New Title" in str(plan.push_update_card[0]["title"])

    def test_trello_title_change_pulls(
        self,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """Trello title change (local unchanged) should pull update."""
        cfg, name = cfg_with_project
        synced_title = format_card_title(name, "1", "Original")
        todo = _make_todo(cfg, name, "Original", trello_card_id="card_1")
        expected_desc = build_card_description(todo, name)
        todo.trello_sync_state = TrelloSyncState(
            last_sync="2026-01-01T00:00:00",
            synced_name=synced_title,
            card_id="card_1",
            list_id="list_tasks",
            desc_hash=compute_desc_hash(expected_desc),
        )
        storage.save_todos(cfg, name, [todo])

        trello_title = format_card_title(name, "1", "Renamed in Trello")
        cards = [
            {"id": "card_1", "name": trello_title, "desc": expected_desc, "idList": "list_tasks"}
        ]
        lists = [{"id": "list_tasks", "name": "proj-tasks"}]
        plan = compute_diff(_make_trello_data(cards=cards, lists=lists), cfg, name)

        assert len(plan.pull_update) == 1
        assert plan.pull_update[0]["title"] == "Renamed in Trello"

    def test_card_moved_to_done_pulls_complete(
        self,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """Card moved to Done list in Trello should pull complete."""
        cfg, name = cfg_with_project
        synced_title = format_card_title(name, "1", "Task")
        todo = _make_todo(cfg, name, "Task", trello_card_id="card_1")
        expected_desc = build_card_description(todo, name)
        todo.trello_sync_state = TrelloSyncState(
            last_sync="2026-01-01T00:00:00",
            synced_name=synced_title,
            card_id="card_1",
            list_id="list_tasks",
            desc_hash=compute_desc_hash(expected_desc),
        )
        storage.save_todos(cfg, name, [todo])

        cards = [
            {"id": "card_1", "name": synced_title, "desc": expected_desc, "idList": "list_done"}
        ]
        lists = [
            {"id": "list_tasks", "name": "proj-tasks"},
            {"id": "list_done", "name": "Done"},
        ]
        plan = compute_diff(_make_trello_data(cards=cards, lists=lists), cfg, name)

        assert todo.id in plan.pull_complete

    def test_done_todo_in_active_list_pulls_reopen(
        self,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """Done todo whose card is in active list should pull reopen."""
        cfg, name = cfg_with_project
        synced_title = format_card_title(name, "1", "Task")
        todo = _make_todo(cfg, name, "Task", trello_card_id="card_1", status="done")
        expected_desc = build_card_description(todo, name)
        todo.trello_sync_state = TrelloSyncState(
            last_sync="2026-01-01T00:00:00",
            synced_name=synced_title,
            card_id="card_1",
            list_id="list_done",
            desc_hash=compute_desc_hash(expected_desc),
        )
        storage.save_todos(cfg, name, [todo])

        cards = [
            {"id": "card_1", "name": synced_title, "desc": expected_desc, "idList": "list_tasks"}
        ]
        lists = [
            {"id": "list_tasks", "name": "proj-tasks"},
            {"id": "list_done", "name": "Done"},
        ]
        plan = compute_diff(_make_trello_data(cards=cards, lists=lists), cfg, name)

        assert todo.id in plan.pull_reopen

    def test_deleted_card_re_creates(
        self,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """Card deleted in Trello should produce a warning and re-create."""
        cfg, name = cfg_with_project
        todo = _make_todo(cfg, name, "Lost card", trello_card_id="card_gone")
        storage.save_todos(cfg, name, [todo])

        plan = compute_diff(_make_trello_data(cards=[], lists=[]), cfg, name)
        assert len(plan.push_create_card) == 1
        assert any("not found" in w for w in plan.warnings)

    def test_conflict_both_changed(
        self,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """Both local and Trello changed since last sync -> conflict."""
        cfg, name = cfg_with_project
        old_title = format_card_title(name, "1", "Original")
        old_desc = "**Status**: pending\n**Priority**: medium"
        todo = _make_todo(cfg, name, "Local Version", trello_card_id="card_1")
        todo.updated = "2026-03-19T11:00:00"
        todo.trello_sync_state = TrelloSyncState(
            last_sync="2026-03-19T10:00:00",
            synced_name=old_title,
            card_id="card_1",
            list_id="list_tasks",
            desc_hash=compute_desc_hash(old_desc),
            trello_updated="2026-03-19T10:30:00",
        )
        storage.save_todos(cfg, name, [todo])

        trello_title = format_card_title(name, todo.id, "Trello Version")
        cards = [{"id": "card_1", "name": trello_title, "desc": old_desc, "idList": "list_tasks"}]
        lists = [{"id": "list_tasks", "name": "proj-tasks"}]
        plan = compute_diff(_make_trello_data(cards=cards, lists=lists), cfg, name)

        assert len(plan.conflicts) == 1
        assert plan.conflicts[0]["todo_id"] == todo.id

    def test_conflict_resolution_local_wins(
        self,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """When local updated is newer than trello_updated, local wins."""
        cfg, name = cfg_with_project
        old_title = format_card_title(name, "1", "Original")
        old_desc = "**Status**: pending\n**Priority**: medium"
        todo = _make_todo(cfg, name, "Local Version", trello_card_id="card_1")
        todo.updated = "2026-03-19T12:00:00"
        todo.trello_sync_state = TrelloSyncState(
            last_sync="2026-03-19T10:00:00",
            synced_name=old_title,
            card_id="card_1",
            list_id="list_tasks",
            desc_hash=compute_desc_hash(old_desc),
            trello_updated="2026-03-19T11:00:00",
        )
        storage.save_todos(cfg, name, [todo])

        trello_title = format_card_title(name, todo.id, "Trello Version")
        cards = [{"id": "card_1", "name": trello_title, "desc": old_desc, "idList": "list_tasks"}]
        lists = [{"id": "list_tasks", "name": "proj-tasks"}]
        plan = compute_diff(_make_trello_data(cards=cards, lists=lists), cfg, name)

        assert plan.conflicts[0]["resolution"] == "local"
        assert len(plan.push_update_card) == 1

    def test_conflict_resolution_trello_wins(
        self,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """When trello_updated is newer than local updated, Trello wins."""
        cfg, name = cfg_with_project
        old_title = format_card_title(name, "1", "Original")
        old_desc = "**Status**: pending\n**Priority**: medium"
        todo = _make_todo(cfg, name, "Local Version", trello_card_id="card_1")
        todo.updated = "2026-03-19T10:30:00"
        todo.trello_sync_state = TrelloSyncState(
            last_sync="2026-03-19T10:00:00",
            synced_name=old_title,
            card_id="card_1",
            list_id="list_tasks",
            desc_hash=compute_desc_hash(old_desc),
            trello_updated="2026-03-19T11:00:00",
        )
        storage.save_todos(cfg, name, [todo])

        trello_title = format_card_title(name, todo.id, "Trello Version")
        cards = [{"id": "card_1", "name": trello_title, "desc": old_desc, "idList": "list_tasks"}]
        lists = [{"id": "list_tasks", "name": "proj-tasks"}]
        plan = compute_diff(_make_trello_data(cards=cards, lists=lists), cfg, name)

        assert plan.conflicts[0]["resolution"] == "trello"
        assert len(plan.pull_update) == 1

    def test_invalid_json_handled(
        self,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        cfg, name = cfg_with_project
        plan = compute_diff("not valid json", cfg, name)
        # Should not crash; plan may still have project card create
        assert isinstance(plan, TrelloSyncPlan)

    def test_empty_string_handled(
        self,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        cfg, name = cfg_with_project
        plan = compute_diff("", cfg, name)
        assert isinstance(plan, TrelloSyncPlan)

    def test_project_card_create_when_no_card_id(
        self,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        cfg, name = cfg_with_project
        meta = storage.load_meta(cfg, name)
        meta.trello_card_id = None
        storage.save_meta(cfg, meta)

        plan = compute_diff(_make_trello_data(cards=[], lists=[]), cfg, name)
        assert plan.project_card_create is True

    def test_project_card_update_when_desc_changed(
        self,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        cfg, name = cfg_with_project
        plan = compute_diff(
            _make_trello_data(
                cards=[],
                lists=[],
                project_card={"desc": "outdated description"},
            ),
            cfg,
            name,
        )
        assert plan.project_card_update is True

    def test_lists_to_create(
        self,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """Missing required lists should be in lists_to_create."""
        cfg, name = cfg_with_project
        plan = compute_diff(_make_trello_data(cards=[], lists=[]), cfg, name)
        # With no lists provided, proj-tasks, Done, Projects should all be needed
        assert "proj-tasks" in plan.lists_to_create
        assert "Done" in plan.lists_to_create
        assert "Projects" in plan.lists_to_create

    def test_existing_lists_not_re_created(
        self,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        cfg, name = cfg_with_project
        lists = [
            {"id": "l1", "name": "proj-tasks"},
            {"id": "l2", "name": "Done"},
            {"id": "l3", "name": "Projects"},
        ]
        plan = compute_diff(_make_trello_data(cards=[], lists=lists), cfg, name)
        assert len(plan.lists_to_create) == 0

    def test_push_create_sorted_topologically(
        self,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """Parent cards should be created before child cards."""
        cfg, name = cfg_with_project
        parent = _make_todo(cfg, name, "Parent")
        child = _make_todo(cfg, name, "Child", parent=parent.id)
        parent.children.append(child.id)
        storage.save_todos(cfg, name, [parent, child])

        plan = compute_diff(_make_trello_data(cards=[], lists=[]), cfg, name)
        ids = [str(op["todo_id"]) for op in plan.push_create_card]
        assert ids.index(parent.id) < ids.index(child.id)

    def test_push_attach_link_for_parent_child(
        self,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """When parent has a card and child is being created, attach link is emitted."""
        cfg, name = cfg_with_project
        parent = _make_todo(cfg, name, "Parent", trello_card_id="parent_card")
        child = _make_todo(cfg, name, "Child", parent=parent.id)
        parent.children.append(child.id)
        expected_title = format_card_title(name, parent.id, "Parent")
        expected_desc = build_card_description(parent, name)
        parent.trello_sync_state = TrelloSyncState(
            last_sync="2026-01-01T00:00:00",
            synced_name=expected_title,
            card_id="parent_card",
            list_id="l1",
            desc_hash=compute_desc_hash(expected_desc),
        )
        storage.save_todos(cfg, name, [parent, child])

        # Parent card exists in Trello so it won't be re-created
        cards = [
            {"id": "parent_card", "name": expected_title, "desc": expected_desc, "idList": "l1"}
        ]
        lists = [{"id": "l1", "name": "proj-tasks"}, {"id": "l2", "name": "Done"}]
        plan = compute_diff(_make_trello_data(cards=cards, lists=lists), cfg, name)
        assert len(plan.push_attach_link) == 1
        assert plan.push_attach_link[0]["parent_card_id"] == "parent_card"

    def test_archived_todo_card_archived(
        self,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """Cards belonging to archived todos should be archived in Trello."""
        cfg, name = cfg_with_project
        # Create and archive a todo
        todo = Todo(
            id="99",
            title="Archived todo",
            status="done",
            trello_card_id="card_archived",
        )
        archived = storage.load_archived_todos(cfg, name)
        archived.append(todo)
        storage.save_archived_todos(cfg, name, archived)

        cards = [
            {
                "id": "card_archived",
                "name": "[myapp] [99] Archived todo",
                "desc": "",
                "idList": "l1",
            }
        ]
        lists = [{"id": "l1", "name": "proj-tasks"}]
        plan = compute_diff(_make_trello_data(cards=cards, lists=lists), cfg, name)
        assert len(plan.push_archive_card) == 1
        assert plan.push_archive_card[0]["card_id"] == "card_archived"

    def test_first_sync_no_snapshot_pushes_local(
        self,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """First sync (no trello_sync_state) pushes local state."""
        cfg, name = cfg_with_project
        todo = _make_todo(cfg, name, "Local task", trello_card_id="card_1")
        # No trello_sync_state set
        storage.save_todos(cfg, name, [todo])

        format_card_title(name, todo.id, "Local task")
        cards = [{"id": "card_1", "name": "different title", "desc": "old", "idList": "list_tasks"}]
        lists = [{"id": "list_tasks", "name": "proj-tasks"}]
        plan = compute_diff(_make_trello_data(cards=cards, lists=lists), cfg, name)

        assert len(plan.push_update_card) == 1


# ── TestApplyChanges ──────────────────────────────────────────────────────────


class TestApplyChanges:
    def test_update_locally(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        todo = _make_todo(cfg, name, "Old title", trello_card_id="card_1")
        storage.save_todos(cfg, name, [todo])

        data = TrelloApplyInput(
            updated_locally=[{"todo_id": todo.id, "title": "New title"}],
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

    def test_reopen_locally(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        todo = _make_todo(cfg, name, "Was done", status="done")
        storage.save_todos(cfg, name, [todo])

        data = TrelloApplyInput(reopened_locally=[todo.id])
        counts = apply_changes(data, cfg, name)
        assert counts["reopened"] == 1
        todos = storage.load_todos(cfg, name)
        assert todos[0].status == "pending"

    def test_link_card_ids(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        todo = _make_todo(cfg, name, "To link")
        storage.save_todos(cfg, name, [todo])

        data = TrelloApplyInput(
            link_card_ids=[{"todo_id": todo.id, "card_id": "card_new_123"}],
        )
        counts = apply_changes(data, cfg, name)
        assert counts["linked"] == 1
        todos = storage.load_todos(cfg, name)
        assert todos[0].trello_card_id == "card_new_123"

    def test_link_project_card_id(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        data = TrelloApplyInput(link_project_card_id="proj_card_xyz")
        apply_changes(data, cfg, name)
        meta = storage.load_meta(cfg, name)
        assert meta.trello_card_id == "proj_card_xyz"

    def test_push_confirmed_records_sync_state(
        self,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        cfg, name = cfg_with_project
        todo = _make_todo(cfg, name, "Synced", trello_card_id="card_1")
        storage.save_todos(cfg, name, [todo])

        data = TrelloApplyInput()
        apply_changes(data, cfg, name, push_confirmed=True)
        todos = storage.load_todos(cfg, name)
        assert todos[0].trello_sync_state is not None
        assert todos[0].trello_sync_state.last_sync != ""
        assert "Synced" in todos[0].trello_sync_state.synced_name
        assert todos[0].trello_sync_state.card_id == "card_1"

    def test_without_push_confirmed_no_sync_state(
        self,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        cfg, name = cfg_with_project
        todo = _make_todo(cfg, name, "No sync", trello_card_id="card_1")
        storage.save_todos(cfg, name, [todo])

        data = TrelloApplyInput()
        apply_changes(data, cfg, name)
        todos = storage.load_todos(cfg, name)
        assert todos[0].trello_sync_state is None

    def test_combined_operations(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        existing = _make_todo(cfg, name, "Existing", trello_card_id="card_ex")
        to_complete = _make_todo(cfg, name, "To complete")
        done_todo = _make_todo(cfg, name, "Was done", status="done")
        storage.save_todos(cfg, name, [existing, to_complete, done_todo])

        data = TrelloApplyInput(
            updated_locally=[{"todo_id": existing.id, "title": "Updated"}],
            completed_locally=[to_complete.id],
            reopened_locally=[done_todo.id],
        )
        counts = apply_changes(data, cfg, name)
        assert counts["updated"] == 1
        assert counts["completed"] == 1
        assert counts["reopened"] == 1

    def test_updated_field_uses_datetime(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        todo = _make_todo(cfg, name, "Test")
        storage.save_todos(cfg, name, [todo])

        data = TrelloApplyInput(
            updated_locally=[{"todo_id": todo.id, "title": "Changed"}],
        )
        apply_changes(data, cfg, name)
        todos = storage.load_todos(cfg, name)
        assert "T" in todos[0].updated  # ISO datetime, not date-only


# ── TrelloSyncPlan tests ──────────────────────────────────────────────────────


class TestTrelloSyncPlan:
    def test_is_empty_true(self) -> None:
        plan = TrelloSyncPlan()
        assert plan.is_empty()

    def test_is_empty_false_push_create(self) -> None:
        plan = TrelloSyncPlan(push_create_card=[{"todo_id": "1"}])
        assert not plan.is_empty()

    def test_is_empty_false_pull_complete(self) -> None:
        plan = TrelloSyncPlan(pull_complete=["1"])
        assert not plan.is_empty()

    def test_is_empty_false_conflicts(self) -> None:
        plan = TrelloSyncPlan(conflicts=[{"todo_id": "1"}])
        assert not plan.is_empty()

    def test_is_empty_false_project_card_create(self) -> None:
        plan = TrelloSyncPlan(project_card_create=True)
        assert not plan.is_empty()

    def test_is_empty_false_lists_to_create(self) -> None:
        plan = TrelloSyncPlan(lists_to_create=["Tasks"])
        assert not plan.is_empty()

    def test_to_dict_has_summary(self) -> None:
        plan = TrelloSyncPlan(push_create_card=[{"todo_id": "1"}])
        d = plan.to_dict()
        assert d["summary"]["push_create_card_count"] == 1  # type: ignore[index]
        assert d["summary"]["pull_update_count"] == 0  # type: ignore[index]

    def test_to_dict_has_conflict_count(self) -> None:
        plan = TrelloSyncPlan(conflicts=[{"todo_id": "1"}])
        d = plan.to_dict()
        assert d["summary"]["conflict_count"] == 1  # type: ignore[index]

    def test_to_dict_has_all_fields(self) -> None:
        plan = TrelloSyncPlan()
        d = plan.to_dict()
        expected_keys = {
            "push_create_card",
            "push_update_card",
            "push_move_card",
            "push_archive_card",
            "push_attach_link",
            "pull_update",
            "pull_move",
            "pull_complete",
            "pull_reopen",
            "conflicts",
            "warnings",
            "project_card_create",
            "project_card_update",
            "lists_to_create",
            "summary",
        }
        assert expected_keys.issubset(set(d.keys()))


# ── TrelloSyncState model tests ───────────────────────────────────────────────


class TestTrelloSyncState:
    def test_to_dict(self) -> None:
        ss = TrelloSyncState(
            last_sync="2026-03-19T14:30:00",
            synced_name="Task name",
            card_id="card_1",
            list_id="list_1",
            desc_hash="abc123",
        )
        d = ss.to_dict()
        assert d["last_sync"] == "2026-03-19T14:30:00"
        assert d["synced_name"] == "Task name"
        assert d["card_id"] == "card_1"
        assert d["list_id"] == "list_1"
        assert d["desc_hash"] == "abc123"

    def test_from_dict(self) -> None:
        d = {
            "last_sync": "2026-03-19T14:30:00",
            "synced_name": "Task name",
            "card_id": "card_1",
            "list_id": "list_1",
            "desc_hash": "abc123",
        }
        ss = TrelloSyncState.from_dict(d)
        assert ss.last_sync == "2026-03-19T14:30:00"
        assert ss.synced_name == "Task name"
        assert ss.card_id == "card_1"

    def test_todo_roundtrip_with_sync_state(self) -> None:
        todo = Todo(
            id="1",
            title="Test",
            trello_sync_state=TrelloSyncState(
                last_sync="2026-03-19T14:30:00",
                synced_name="[proj] [1] Test",
                card_id="card_1",
                list_id="list_1",
                desc_hash="abc",
            ),
        )
        d = todo.to_dict()
        restored = Todo.from_dict(d)
        assert restored.trello_sync_state is not None
        assert restored.trello_sync_state.last_sync == "2026-03-19T14:30:00"
        assert restored.trello_sync_state.card_id == "card_1"

    def test_todo_roundtrip_without_sync_state(self) -> None:
        todo = Todo(id="1", title="Test")
        d = todo.to_dict()
        restored = Todo.from_dict(d)
        assert restored.trello_sync_state is None


# ── MCP tool registration tests ───────────────────────────────────────────────


class TestMCPToolDiff:
    def _get_tools(self) -> dict[str, object]:
        from unittest.mock import MagicMock

        from server.tools.trello_sync import register

        app = MagicMock()
        tools: dict[str, object] = {}
        app.tool = lambda **kw: lambda fn: tools.update({fn.__name__: fn}) or fn
        register(app)
        return tools

    def test_diff_empty_returns_summary(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        _cfg, name = cfg_with_project
        tools = self._get_tools()
        diff = tools["proj_trello_diff"]
        result = json.loads(
            diff(trello_cards_json=_make_trello_data(cards=[], lists=[]), project_name=name)
        )  # type: ignore[operator]
        assert "summary" in result

    def test_diff_invalid_json(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        _cfg, name = cfg_with_project
        tools = self._get_tools()
        diff = tools["proj_trello_diff"]
        result = json.loads(diff(trello_cards_json="not json", project_name=name))  # type: ignore[operator]
        assert "summary" in result

    def test_auto_apply_returns_project_info(
        self,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        _cfg, name = cfg_with_project
        tools = self._get_tools()
        diff = tools["proj_trello_diff"]
        result = json.loads(
            diff(  # type: ignore[operator]
                trello_cards_json=_make_trello_data(cards=[], lists=[]),
                auto_apply=True,
                project_name=name,
            )
        )
        assert "project_info" in result
        assert result["project_info"]["trello_card_id"] == "card_abc"
        assert "auto_applied" in result


class TestMCPToolApply:
    def _get_apply_fn(self) -> object:
        from unittest.mock import MagicMock

        from server.tools.trello_sync import register

        app = MagicMock()
        tools: dict[str, object] = {}
        app.tool = lambda **kw: lambda fn: tools.update({fn.__name__: fn}) or fn
        register(app)
        return tools["proj_trello_apply"]

    def test_apply_links_card(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        todo = _make_todo(cfg, name, "To link")
        storage.save_todos(cfg, name, [todo])

        apply_fn = self._get_apply_fn()
        data = {
            "link_card_ids": [{"todo_id": todo.id, "card_id": "card_xyz"}],
            "link_project_card_id": "proj_card_xyz",
        }
        result = json.loads(apply_fn(apply_json=json.dumps(data), project_name=name))  # type: ignore[operator]
        assert result["status"] == "ok"
        assert result["counts"]["linked"] == 1
        meta = storage.load_meta(cfg, name)
        assert meta.trello_card_id == "proj_card_xyz"

    def test_apply_invalid_json_returns_error(
        self, cfg_with_project: tuple[ProjConfig, str]
    ) -> None:
        _cfg, name = cfg_with_project
        apply_fn = self._get_apply_fn()
        result = apply_fn(apply_json="not json", project_name=name)  # type: ignore[operator]
        assert "Invalid JSON" in result
