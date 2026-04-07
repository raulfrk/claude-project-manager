"""Tests for Trello list mappings for project statuses (todo 228)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from server.lib import state, storage
from server.lib.models import (
    ProjConfig,
    ProjectDates,
    ProjectEntry,
    ProjectMeta,
    ProjectTrelloConfig,
    RepoEntry,
    TrelloListMappings,
    TrelloSync,
)
from server.tools.trello_sync import TrelloSyncPlan
from tests.conftest import call_tool

# ── Model tests ──────────────────────────────────────────────────────────────


class TestTrelloListMappingsModel:
    def test_defaults(self) -> None:
        lm = TrelloListMappings()
        assert lm.created == "Backlog"
        assert lm.done == "Done"
        assert lm.active == ""
        assert lm.pending == ""
        assert lm.archived == ""

    def test_to_dict_includes_status_fields(self) -> None:
        lm = TrelloListMappings(active="Active", pending="On Hold", archived="Archived")
        d = lm.to_dict()
        assert d["active"] == "Active"
        assert d["pending"] == "On Hold"
        assert d["archived"] == "Archived"
        assert d["done"] == "Done"
        assert d["tasks"] == "proj-tasks"
        assert d["projects"] == "Projects"

    def test_from_dict_with_status_fields(self) -> None:
        data = {
            "created": "Todo",
            "done": "Complete",
            "active": "In Progress",
            "pending": "Waiting",
            "archived": "Done",
        }
        lm = TrelloListMappings.from_dict(data)
        assert lm.created == "Todo"
        assert lm.done == "Complete"
        assert lm.active == "In Progress"
        assert lm.pending == "Waiting"
        assert lm.archived == "Done"

    def test_from_dict_without_status_fields_defaults_empty(self) -> None:
        data: dict[str, object] = {"created": "Backlog", "done": "Done"}
        lm = TrelloListMappings.from_dict(data)
        assert lm.active == ""
        assert lm.pending == ""
        assert lm.archived == ""

    def test_roundtrip(self) -> None:
        original = TrelloListMappings(
            done="Complete",
            active="Active",
            pending="Paused",
            archived="Archive",
        )
        restored = TrelloListMappings.from_dict(original.to_dict())
        assert restored.done == original.done
        assert restored.active == original.active
        assert restored.pending == original.pending
        assert restored.archived == original.archived

    def test_empty_dict_produces_defaults(self) -> None:
        lm = TrelloListMappings.from_dict({})
        assert lm.created == "Backlog"
        assert lm.done == "Done"
        assert lm.active == ""
        assert lm.pending == ""
        assert lm.archived == ""


class TestTrelloSyncModelWithListMappings:
    def test_trello_sync_to_dict_includes_list_mappings(self) -> None:
        ts = TrelloSync(
            enabled=True,
            default_board_id="board1",
            list_mappings=TrelloListMappings(active="Active", archived="Archive"),
        )
        d = ts.to_dict()
        assert d["list_mappings"]["active"] == "Active"
        assert d["list_mappings"]["archived"] == "Archive"

    def test_trello_sync_from_dict_preserves_list_mappings(self) -> None:
        data = {
            "enabled": True,
            "default_board_id": "board1",
            "list_mappings": {
                "created": "Backlog",
                "done": "Done",
                "active": "Active",
                "pending": "Waiting",
                "archived": "Archive",
            },
        }
        ts = TrelloSync.from_dict(data)
        assert ts.list_mappings.active == "Active"
        assert ts.list_mappings.pending == "Waiting"
        assert ts.list_mappings.archived == "Archive"

    def test_trello_sync_roundtrip(self) -> None:
        original = TrelloSync(
            enabled=True,
            default_board_id="b1",
            list_mappings=TrelloListMappings(
                active="In Progress", pending="Blocked", archived="Done"
            ),
        )
        restored = TrelloSync.from_dict(original.to_dict())
        assert restored.list_mappings.active == "In Progress"
        assert restored.list_mappings.pending == "Blocked"
        assert restored.list_mappings.archived == "Done"


class TestProjectTrelloConfigListMappings:
    def test_per_project_override_roundtrip(self) -> None:
        ptc = ProjectTrelloConfig(
            list_mappings=TrelloListMappings(
                active="Active", pending="Paused", archived="Archived"
            ),
        )
        d = ptc.to_dict()
        restored = ProjectTrelloConfig.from_dict(d)
        assert restored.list_mappings is not None
        assert restored.list_mappings.active == "Active"
        assert restored.list_mappings.pending == "Paused"
        assert restored.list_mappings.archived == "Archived"

    def test_per_project_none_list_mappings(self) -> None:
        ptc = ProjectTrelloConfig()
        d = ptc.to_dict()
        restored = ProjectTrelloConfig.from_dict(d)
        assert restored.list_mappings is None


class TestProjConfigListMappings:
    def test_proj_config_to_dict_includes_list_mappings(self) -> None:
        cfg = ProjConfig(
            trello=TrelloSync(
                list_mappings=TrelloListMappings(active="Active", archived="Archive"),
            ),
        )
        d = cfg.to_dict()
        sync = d["sync"]
        assert isinstance(sync, dict)
        trello = sync["trello"]
        assert isinstance(trello, dict)
        lm = trello["list_mappings"]
        assert isinstance(lm, dict)
        assert lm["active"] == "Active"
        assert lm["archived"] == "Archive"

    def test_proj_config_from_dict_preserves_list_mappings(self) -> None:
        data: dict[str, object] = {
            "sync": {
                "trello": {
                    "enabled": True,
                    "list_mappings": {"active": "WIP", "pending": "Hold", "archived": "Done"},
                },
            },
        }
        cfg = ProjConfig.from_dict(data)
        assert cfg.trello.list_mappings.active == "WIP"
        assert cfg.trello.list_mappings.pending == "Hold"
        assert cfg.trello.list_mappings.archived == "Done"

    def test_backward_compat_no_list_mapping_status_fields(self) -> None:
        """Old config without active/pending/archived fields still deserializes."""
        data: dict[str, object] = {
            "sync": {
                "trello": {
                    "enabled": True,
                    "list_mappings": {"created": "Backlog", "done": "Done"},
                },
            },
        }
        cfg = ProjConfig.from_dict(data)
        assert cfg.trello.list_mappings.active == ""
        assert cfg.trello.list_mappings.pending == ""
        assert cfg.trello.list_mappings.archived == ""


# ── Config tool tests ────────────────────────────────────────────────────────


@pytest.mark.anyio
class TestConfigListMappings:
    async def test_config_init_trello_list_mappings(
        self,
        mcp_app: Any,
        cfg: ProjConfig,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        new_cfg_path = tmp_path / "proj.yaml"
        monkeypatch.setattr(storage, "_DEFAULT_CONFIG_PATH", new_cfg_path)

        result = await call_tool(
            mcp_app,
            "config_init",
            tracking_dir=str(tmp_path / "tracking"),
            trello_list_active="Active",
            trello_list_pending="On Hold",
            trello_list_archived="Archive",
        )

        assert "saved" in result.lower()
        loaded = storage.load_config()
        assert loaded.trello.list_mappings.active == "Active"
        assert loaded.trello.list_mappings.pending == "On Hold"
        assert loaded.trello.list_mappings.archived == "Archive"

    async def test_config_update_trello_list_mappings(
        self,
        mcp_app: Any,
        cfg: ProjConfig,
    ) -> None:
        result = await call_tool(
            mcp_app,
            "config_update",
            trello_list_active="In Progress",
            trello_list_archived="Done",
        )

        assert "updated" in result.lower()
        loaded = storage.load_config()
        assert loaded.trello.list_mappings.active == "In Progress"
        assert loaded.trello.list_mappings.archived == "Done"
        # pending was not updated, should remain default
        assert loaded.trello.list_mappings.pending == ""

    async def test_config_update_list_mappings_partial_leaves_others(
        self,
        mcp_app: Any,
        cfg: ProjConfig,
    ) -> None:
        # First set all three
        await call_tool(
            mcp_app,
            "config_update",
            trello_list_active="Active",
            trello_list_pending="Hold",
            trello_list_archived="Archive",
        )
        # Now update only one
        await call_tool(mcp_app, "config_update", trello_list_active="WIP")

        loaded = storage.load_config()
        assert loaded.trello.list_mappings.active == "WIP"
        assert loaded.trello.list_mappings.pending == "Hold"
        assert loaded.trello.list_mappings.archived == "Archive"

    async def test_config_load_shows_list_mappings(
        self,
        mcp_app: Any,
        cfg: ProjConfig,
    ) -> None:
        await call_tool(
            mcp_app,
            "config_update",
            trello_list_active="Active",
            trello_list_archived="Archive",
        )

        result = await call_tool(mcp_app, "config_load")

        assert "trello.list_mappings.active: Active" in result
        assert "trello.list_mappings.archived: Archive" in result

    async def test_config_load_shows_not_set_when_empty(
        self,
        mcp_app: Any,
        cfg: ProjConfig,
    ) -> None:
        result = await call_tool(mcp_app, "config_load")

        assert "trello.list_mappings.active: (not set)" in result
        assert "trello.list_mappings.pending: (not set)" in result
        assert "trello.list_mappings.archived: (not set)" in result


# ── proj_archive trello_move hint tests ──────────────────────────────────────


def _setup_project_with_trello(
    cfg: ProjConfig,
    tmp_path: Path,
    name: str = "myapp",
    trello_card_id: str | None = "card_abc",
    project_trello: ProjectTrelloConfig | None = None,
) -> ProjectMeta:
    """Helper to set up a project with Trello config for archive/update tests."""
    today = str(date.today())
    proj_dir = Path(cfg.tracking_dir) / name
    proj_dir.mkdir(parents=True, exist_ok=True)
    (proj_dir / "todos.yaml").write_text("todos: []\n")
    (proj_dir / "NOTES.md").write_text(f"# {name}\n")
    repo_path = str(tmp_path / "repo")
    Path(repo_path).mkdir(exist_ok=True)
    meta = ProjectMeta(
        name=name,
        repos=[RepoEntry(label="code", path=repo_path)],
        dates=ProjectDates(created=today, last_updated=today),
        trello_card_id=trello_card_id,
    )
    if project_trello is not None:
        meta.trello = project_trello
    storage.save_meta(cfg, meta)
    index = storage.load_index(cfg)
    index.projects[name] = ProjectEntry(name=name, tracking_dir=str(proj_dir), created=today)
    storage.save_index(cfg, index)
    state.set_session_active(name)
    return meta


@pytest.mark.anyio
class TestArchiveTrelloMoveHint:
    async def test_archive_includes_trello_move_hint(
        self,
        mcp_app: Any,
        cfg: ProjConfig,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Set global archived list mapping
        cfg.trello.list_mappings.archived = "Archive"
        storage.save_config(cfg)

        _setup_project_with_trello(cfg, tmp_path, trello_card_id="card_123")

        result = await call_tool(mcp_app, "proj_archive", name="myapp")

        assert "Archived project 'myapp'" in result
        assert "trello_move" in result
        assert "card_123" in result
        assert "Archive" in result

    async def test_archive_no_hint_when_no_list_mapping(
        self,
        mcp_app: Any,
        cfg: ProjConfig,
        tmp_path: Path,
    ) -> None:
        # No archived list mapping configured (default empty)
        _setup_project_with_trello(cfg, tmp_path, trello_card_id="card_123")

        result = await call_tool(mcp_app, "proj_archive", name="myapp")

        assert "Archived project 'myapp'" in result
        assert "trello_move" not in result

    async def test_archive_no_hint_when_no_trello_card(
        self,
        mcp_app: Any,
        cfg: ProjConfig,
        tmp_path: Path,
    ) -> None:
        cfg.trello.list_mappings.archived = "Archive"
        storage.save_config(cfg)

        _setup_project_with_trello(cfg, tmp_path, trello_card_id=None)

        result = await call_tool(mcp_app, "proj_archive", name="myapp")

        assert "Archived project 'myapp'" in result
        assert "trello_move" not in result

    async def test_archive_uses_per_project_override(
        self,
        mcp_app: Any,
        cfg: ProjConfig,
        tmp_path: Path,
    ) -> None:
        # Global mapping says "GlobalArchive"
        cfg.trello.list_mappings.archived = "GlobalArchive"
        storage.save_config(cfg)

        # Per-project override says "ProjectArchive"
        project_trello = ProjectTrelloConfig(
            list_mappings=TrelloListMappings(archived="ProjectArchive"),
        )
        _setup_project_with_trello(
            cfg, tmp_path, trello_card_id="card_99", project_trello=project_trello
        )

        result = await call_tool(mcp_app, "proj_archive", name="myapp")

        assert "trello_move" in result
        assert "ProjectArchive" in result
        assert "GlobalArchive" not in result


# ── proj_update_meta trello_move hint tests ──────────────────────────────────


@pytest.mark.anyio
class TestUpdateMetaTrelloMoveHint:
    async def test_status_change_to_active_includes_hint(
        self,
        mcp_app: Any,
        cfg: ProjConfig,
        tmp_path: Path,
    ) -> None:
        cfg.trello.list_mappings.active = "Active"
        storage.save_config(cfg)

        meta = _setup_project_with_trello(cfg, tmp_path, trello_card_id="card_1")
        meta.status = "paused"
        storage.save_meta(cfg, meta)

        result = await call_tool(mcp_app, "proj_update_meta", name="myapp", status="active")

        assert "Updated project 'myapp'" in result
        assert "trello_move" in result
        assert "card_1" in result
        assert "Active" in result

    async def test_status_change_to_paused_uses_pending(
        self,
        mcp_app: Any,
        cfg: ProjConfig,
        tmp_path: Path,
    ) -> None:
        cfg.trello.list_mappings.pending = "On Hold"
        storage.save_config(cfg)

        _setup_project_with_trello(cfg, tmp_path, trello_card_id="card_2")

        result = await call_tool(mcp_app, "proj_update_meta", name="myapp", status="paused")

        assert "trello_move" in result
        assert "On Hold" in result

    async def test_status_change_to_blocked_uses_pending(
        self,
        mcp_app: Any,
        cfg: ProjConfig,
        tmp_path: Path,
    ) -> None:
        cfg.trello.list_mappings.pending = "Waiting"
        storage.save_config(cfg)

        _setup_project_with_trello(cfg, tmp_path, trello_card_id="card_3")

        result = await call_tool(mcp_app, "proj_update_meta", name="myapp", status="blocked")

        assert "trello_move" in result
        assert "Waiting" in result

    async def test_no_hint_when_status_unchanged(
        self,
        mcp_app: Any,
        cfg: ProjConfig,
        tmp_path: Path,
    ) -> None:
        cfg.trello.list_mappings.active = "Active"
        storage.save_config(cfg)

        _setup_project_with_trello(cfg, tmp_path, trello_card_id="card_4")

        # Status is already "active" (default)
        result = await call_tool(mcp_app, "proj_update_meta", name="myapp", status="active")

        assert "trello_move" not in result

    async def test_no_hint_when_no_mapping(
        self,
        mcp_app: Any,
        cfg: ProjConfig,
        tmp_path: Path,
    ) -> None:
        # No list mappings configured (empty defaults)
        _setup_project_with_trello(cfg, tmp_path, trello_card_id="card_5")

        result = await call_tool(mcp_app, "proj_update_meta", name="myapp", status="paused")

        assert "trello_move" not in result

    async def test_no_hint_when_no_trello_card(
        self,
        mcp_app: Any,
        cfg: ProjConfig,
        tmp_path: Path,
    ) -> None:
        cfg.trello.list_mappings.active = "Active"
        storage.save_config(cfg)

        _setup_project_with_trello(cfg, tmp_path, trello_card_id=None)

        result = await call_tool(mcp_app, "proj_update_meta", name="myapp", status="paused")

        assert "trello_move" not in result

    async def test_no_hint_when_only_description_changes(
        self,
        mcp_app: Any,
        cfg: ProjConfig,
        tmp_path: Path,
    ) -> None:
        cfg.trello.list_mappings.active = "Active"
        storage.save_config(cfg)

        _setup_project_with_trello(cfg, tmp_path, trello_card_id="card_6")

        result = await call_tool(mcp_app, "proj_update_meta", name="myapp", description="new desc")

        assert "trello_move" not in result

    async def test_per_project_override_in_update_meta(
        self,
        mcp_app: Any,
        cfg: ProjConfig,
        tmp_path: Path,
    ) -> None:
        cfg.trello.list_mappings.active = "GlobalActive"
        storage.save_config(cfg)

        project_trello = ProjectTrelloConfig(
            list_mappings=TrelloListMappings(active="ProjectActive"),
        )
        meta = _setup_project_with_trello(
            cfg, tmp_path, trello_card_id="card_7", project_trello=project_trello
        )
        meta.status = "paused"
        storage.save_meta(cfg, meta)

        result = await call_tool(mcp_app, "proj_update_meta", name="myapp", status="active")

        assert "trello_move" in result
        assert "ProjectActive" in result
        assert "GlobalActive" not in result


# ── TrelloSyncPlan basic tests ─────────────────────────────────────────────


class TestTrelloSyncPlanBasic:
    def test_empty_plan(self) -> None:
        plan = TrelloSyncPlan()
        assert plan.is_empty()

    def test_not_empty_with_push_create(self) -> None:
        plan = TrelloSyncPlan(push_create_card=[{"todo_id": "1"}])
        assert not plan.is_empty()
