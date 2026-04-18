"""Tests for trello_migration — checklist-to-card auto-migration."""

from __future__ import annotations

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
    TrelloSync,
)
from server.tools.trello_migration import (
    _needs_migration,
    migrate_checklist_to_card,
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

    now = datetime.now(tz=UTC).replace(tzinfo=None).isoformat()
    proj_dir = Path(cfg.tracking_dir) / "myapp"
    proj_dir.mkdir(parents=True)
    (proj_dir / "todos.yaml").write_text("todos: []\n")
    (proj_dir / "archive.yaml").write_text("todos: []\n")
    meta = ProjectMeta(
        name="myapp",
        repos=[RepoEntry(label="code", path=str(tmp_path))],
        dates=ProjectDates(created=now, last_updated=now),
        trello_card_id="project_card_abc",
    )
    storage.save_meta(cfg, meta)
    index = ProjectIndex(
        projects={"myapp": ProjectEntry(name="myapp", tracking_dir=str(proj_dir), created=now)},
    )
    storage.save_index(cfg, index)
    return cfg, "myapp"


def _make_todo(
    cfg: ProjConfig,
    name: str,
    title: str,
    **kwargs: object,
) -> Todo:
    meta = storage.load_meta(cfg, name)
    now = datetime.now(tz=UTC).replace(tzinfo=None).isoformat()
    parent_todo = None
    if kwargs.get("parent"):
        todos = storage.load_todos(cfg, name)
        parent_todo = next((t for t in todos if t.id == kwargs["parent"]), None)
    todo = Todo(
        id=next_todo_id(meta, parent=parent_todo),
        title=title,
        created=now,
        updated=now,
    )
    for k, v in kwargs.items():
        setattr(todo, k, v)
    storage.save_meta(cfg, meta)
    return todo


def _save_todos(cfg: ProjConfig, name: str, todos: list[Todo]) -> None:
    storage.save_todos(cfg, name, todos)


def _fake_trello_tool(results: dict[str, list]) -> object:
    """Create a fake call_trello that returns canned responses.

    results maps tool_name -> list of responses (consumed in order).
    """
    counters: dict[str, int] = {}

    def _call(tool_name: str, params: dict) -> object:
        if tool_name not in results:
            raise RuntimeError(f"Unexpected tool call: {tool_name}")
        idx = counters.get(tool_name, 0)
        counters[tool_name] = idx + 1
        resp_list = results[tool_name]
        if idx >= len(resp_list):
            raise RuntimeError(f"Too many calls to {tool_name} (call #{idx + 1})")
        resp = resp_list[idx]
        if isinstance(resp, Exception):
            raise resp
        return resp

    return _call


# ── Detection tests ───────────────────────────────────────────────────────────


class TestNeedsMigration:
    def test_no_legacy_fields(self):
        todos = [
            Todo(id="1", title="t1"),
            Todo(id="2", title="t2", trello_card_id="card1"),
        ]
        assert _needs_migration(todos) is False

    def test_has_checklist_id(self):
        todos = [
            Todo(id="1", title="t1", trello_checklist_id="cl1"),
        ]
        assert _needs_migration(todos) is True

    def test_has_checklist_item_id(self):
        todos = [
            Todo(id="1", title="t1", trello_checklist_item_id="item1"),
        ]
        assert _needs_migration(todos) is True

    def test_both_old_and_new(self):
        """Todo with both card_id and checklist fields still triggers migration."""
        todos = [
            Todo(id="1", title="t1", trello_card_id="card1", trello_checklist_id="cl1"),
        ]
        assert _needs_migration(todos) is True

    def test_empty_list(self):
        assert _needs_migration([]) is False


# ── Migration tests ───────────────────────────────────────────────────────────


class TestMigrateChecklistToCard:
    def test_no_todos_to_migrate(self, cfg_with_project):
        cfg, name = cfg_with_project
        meta = storage.load_meta(cfg, name)
        todos = [Todo(id="1", title="t1", trello_card_id="existing_card")]
        _save_todos(cfg, name, todos)

        result = migrate_checklist_to_card(
            cfg,
            name,
            meta,
            todos,
            call_trello=_fake_trello_tool({}),
        )
        assert result["already_migrated"] is True
        assert result["migrated"] == 0

    def test_basic_migration(self, cfg_with_project):
        cfg, name = cfg_with_project
        meta = storage.load_meta(cfg, name)

        t1 = _make_todo(cfg, name, "Root todo", trello_checklist_id="cl1")
        t2 = _make_todo(cfg, name, "Leaf todo", trello_checklist_item_id="item1")
        todos = [t1, t2]
        _save_todos(cfg, name, todos)

        call_trello = _fake_trello_tool(
            {
                "get_lists": [[{"id": "list1", "name": "proj-tasks"}]],
                "add_card_to_list": [
                    {"id": "new_card_1"},
                    {"id": "new_card_2"},
                ],
            }
        )

        result = migrate_checklist_to_card(
            cfg,
            name,
            meta,
            todos,
            call_trello=call_trello,
        )

        assert result["migrated"] == 2
        assert result["errors"] == []
        assert result["already_migrated"] is False
        assert result["backup_path"]  # backup was created

        # Verify todos were updated in place
        assert todos[0].trello_card_id == "new_card_1"
        assert todos[0].trello_checklist_id is None
        assert todos[1].trello_card_id == "new_card_2"
        assert todos[1].trello_checklist_item_id is None

        # Verify backup file exists
        backup_path = Path(result["backup_path"])
        assert backup_path.exists()

    def test_skips_todos_with_card_id(self, cfg_with_project):
        cfg, name = cfg_with_project
        meta = storage.load_meta(cfg, name)

        t1 = _make_todo(
            cfg,
            name,
            "Already migrated",
            trello_card_id="existing_card",
            trello_checklist_id="cl1",  # stale legacy field
        )
        t2 = _make_todo(cfg, name, "Needs migration", trello_checklist_item_id="item1")
        todos = [t1, t2]
        _save_todos(cfg, name, todos)

        call_trello = _fake_trello_tool(
            {
                "get_lists": [[{"id": "list1", "name": "proj-tasks"}]],
                "add_card_to_list": [{"id": "new_card_2"}],
            }
        )

        result = migrate_checklist_to_card(
            cfg,
            name,
            meta,
            todos,
            call_trello=call_trello,
        )

        assert result["migrated"] == 1
        assert result["skipped"] == 0  # t1 wasn't in to_migrate (has card_id)
        # But t1's stale checklist fields should be cleared
        assert t1.trello_checklist_id is None
        assert t1.trello_card_id == "existing_card"  # preserved

    def test_parent_child_attachment(self, cfg_with_project):
        cfg, name = cfg_with_project
        meta = storage.load_meta(cfg, name)

        parent = _make_todo(cfg, name, "Parent", trello_checklist_id="cl1")
        # Flat model: child membership encoded via group:<parent_id> tag
        child = _make_todo(
            cfg,
            name,
            "Child",
            trello_checklist_item_id="item1",
            tags=[f"group:{parent.id}"],
        )
        todos = [parent, child]
        _save_todos(cfg, name, todos)

        call_trello = _fake_trello_tool(
            {
                "get_lists": [[{"id": "list1", "name": "proj-tasks"}]],
                "add_card_to_list": [
                    {"id": "parent_card"},
                    {"id": "child_card"},
                ],
                "add_attachment": [{"id": "attach1"}],
            }
        )

        result = migrate_checklist_to_card(
            cfg,
            name,
            meta,
            todos,
            call_trello=call_trello,
        )

        assert result["migrated"] == 2
        assert result["attachments_created"] == 1

    def test_card_creation_error_partial(self, cfg_with_project):
        """When one card creation fails, others still proceed."""
        cfg, name = cfg_with_project
        meta = storage.load_meta(cfg, name)

        t1 = _make_todo(cfg, name, "Todo 1", trello_checklist_item_id="item1")
        t2 = _make_todo(cfg, name, "Todo 2", trello_checklist_item_id="item2")
        todos = [t1, t2]
        _save_todos(cfg, name, todos)

        call_trello = _fake_trello_tool(
            {
                "get_lists": [[{"id": "list1", "name": "proj-tasks"}]],
                "add_card_to_list": [
                    RuntimeError("API timeout"),
                    {"id": "card_for_t2"},
                ],
            }
        )

        result = migrate_checklist_to_card(
            cfg,
            name,
            meta,
            todos,
            call_trello=call_trello,
        )

        assert result["migrated"] == 1
        assert len(result["errors"]) == 1
        assert "API timeout" in result["errors"][0]

    def test_no_board_id(self, cfg_with_project):
        cfg, name = cfg_with_project
        # Override config to remove board_id
        cfg.trello.default_board_id = ""
        storage.save_config(cfg)
        meta = storage.load_meta(cfg, name)
        meta.trello.board_id = ""
        storage.save_meta(cfg, meta)

        t1 = _make_todo(cfg, name, "Todo", trello_checklist_item_id="item1")
        todos = [t1]
        _save_todos(cfg, name, todos)

        result = migrate_checklist_to_card(
            cfg,
            name,
            meta,
            todos,
            call_trello=_fake_trello_tool({}),
        )

        assert result["migrated"] == 0
        assert "No Trello board_id" in result["errors"][0]

    def test_creates_tasks_list_if_missing(self, cfg_with_project):
        cfg, name = cfg_with_project
        meta = storage.load_meta(cfg, name)

        t1 = _make_todo(cfg, name, "Todo", trello_checklist_item_id="item1")
        todos = [t1]
        _save_todos(cfg, name, todos)

        call_trello = _fake_trello_tool(
            {
                "get_lists": [[{"id": "list1", "name": "Other List"}]],  # no proj-tasks
                "create_list": [{"id": "new_list_id"}],
                "add_card_to_list": [{"id": "new_card"}],
            }
        )

        result = migrate_checklist_to_card(
            cfg,
            name,
            meta,
            todos,
            call_trello=call_trello,
        )

        assert result["migrated"] == 1
        assert result["errors"] == []

    def test_saves_to_disk(self, cfg_with_project):
        """Verify that migrated todos are persisted to todos.yaml."""
        cfg, name = cfg_with_project
        meta = storage.load_meta(cfg, name)

        t1 = _make_todo(cfg, name, "Todo", trello_checklist_item_id="item1")
        todos = [t1]
        _save_todos(cfg, name, todos)

        call_trello = _fake_trello_tool(
            {
                "get_lists": [[{"id": "list1", "name": "proj-tasks"}]],
                "add_card_to_list": [{"id": "saved_card"}],
            }
        )

        migrate_checklist_to_card(
            cfg,
            name,
            meta,
            todos,
            call_trello=call_trello,
        )

        # Reload from disk
        reloaded = storage.load_todos(cfg, name)
        assert reloaded[0].trello_card_id == "saved_card"
        assert reloaded[0].trello_checklist_item_id is None

    def test_attachment_error_non_fatal(self, cfg_with_project):
        """Attachment failure should not prevent migration from succeeding."""
        cfg, name = cfg_with_project
        meta = storage.load_meta(cfg, name)

        parent = _make_todo(cfg, name, "Parent", trello_checklist_id="cl1")
        # Flat model: child membership encoded via group:<parent_id> tag
        child = _make_todo(
            cfg,
            name,
            "Child",
            trello_checklist_item_id="item1",
            tags=[f"group:{parent.id}"],
        )
        todos = [parent, child]
        _save_todos(cfg, name, todos)

        call_trello = _fake_trello_tool(
            {
                "get_lists": [[{"id": "list1", "name": "proj-tasks"}]],
                "add_card_to_list": [
                    {"id": "parent_card"},
                    {"id": "child_card"},
                ],
                "add_attachment": [RuntimeError("attachment failed")],
            }
        )

        result = migrate_checklist_to_card(
            cfg,
            name,
            meta,
            todos,
            call_trello=call_trello,
        )

        assert result["migrated"] == 2
        assert result["attachments_created"] == 0
        assert len(result["errors"]) == 1
        assert "attachment failed" in result["errors"][0]

    def test_get_lists_api_error(self, cfg_with_project):
        """When fetching board lists fails, migration returns early with error."""
        cfg, name = cfg_with_project
        meta = storage.load_meta(cfg, name)

        t1 = _make_todo(cfg, name, "Todo", trello_checklist_item_id="item1")
        todos = [t1]
        _save_todos(cfg, name, todos)

        call_trello = _fake_trello_tool({"get_lists": [RuntimeError("board not accessible")]})

        result = migrate_checklist_to_card(
            cfg,
            name,
            meta,
            todos,
            call_trello=call_trello,
        )

        assert result["migrated"] == 0
        assert "board not accessible" in result["errors"][0]
        assert result["backup_path"]  # backup was still created before the error
