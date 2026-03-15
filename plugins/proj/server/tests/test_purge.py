"""Tests for the archive purge feature — model round-trips, config, and tool behavior."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from server.lib import state, storage
from server.lib.models import ArchiveConfig, ProjConfig, ProjectEntry
from tests.conftest import call_tool, setup_project


# ── Model tests ──────────────────────────────────────────────────────────────


class TestArchiveConfigPurge:
    def test_archive_config_purge_after_days_roundtrip(self) -> None:
        ac = ArchiveConfig(purge_after_days=30)
        result = ArchiveConfig.from_dict(ac.to_dict())
        assert result.purge_after_days == 30

    def test_archive_config_purge_after_days_default(self) -> None:
        ac = ArchiveConfig.from_dict({})
        assert ac.purge_after_days is None


class TestProjectEntryPurgeFields:
    def test_project_entry_archive_date_purgeable_roundtrip(self) -> None:
        entry = ProjectEntry(
            name="test",
            tracking_dir="/tmp/tracking/test",
            created="2026-01-01",
            archived=True,
            archive_date="2026-03-01",
            purgeable=False,
        )
        result = ProjectEntry.from_dict(entry.to_dict())
        assert result.archive_date == "2026-03-01"
        assert result.purgeable is False

    def test_project_entry_backward_compat(self) -> None:
        """Old data without archive_date/purgeable gives correct defaults."""
        old_data: dict[str, object] = {
            "name": "legacy",
            "tracking_dir": "/tmp/tracking/legacy",
            "created": "2025-01-01",
            "archived": True,
        }
        entry = ProjectEntry.from_dict(old_data)
        assert entry.archive_date is None
        assert entry.purgeable is True


# ── Tool tests ───────────────────────────────────────────────────────────────


@pytest.fixture()
def project(cfg: ProjConfig, tmp_path: Path) -> tuple[ProjConfig, str]:
    setup_project(cfg, "myapp", str(tmp_path))
    state.set_session_active("myapp")
    return cfg, "myapp"


@pytest.mark.anyio
class TestProjArchiveSetsFields:
    async def test_proj_archive_sets_archive_date(
        self,
        mcp_app: Any,
        project: tuple[ProjConfig, str],
    ) -> None:
        cfg, name = project
        await call_tool(mcp_app, "proj_archive", name=name)

        index = storage.load_index(cfg)
        entry = index.projects[name]
        assert entry.archived is True
        assert entry.archive_date == date.today().isoformat()

    async def test_proj_archive_sets_purgeable(
        self,
        mcp_app: Any,
        project: tuple[ProjConfig, str],
    ) -> None:
        cfg, name = project
        await call_tool(mcp_app, "proj_archive", name=name, purgeable=False)

        index = storage.load_index(cfg)
        entry = index.projects[name]
        assert entry.purgeable is False


@pytest.mark.anyio
class TestProjPurgeArchive:
    def _setup_archived_project(
        self,
        cfg: ProjConfig,
        name: str,
        tmp_path: Path,
        archive_date: str | None,
        purgeable: bool = True,
    ) -> None:
        """Create an archived project in the index with given archive_date/purgeable."""
        setup_project(cfg, name, str(tmp_path / name))
        index = storage.load_index(cfg)
        entry = index.projects[name]
        entry.archived = True
        entry.archive_date = archive_date
        entry.purgeable = purgeable
        storage.save_index(cfg, index)

    async def test_purge_not_configured(
        self,
        mcp_app: Any,
        cfg: ProjConfig,
    ) -> None:
        """When purge_after_days is None, tool returns 'not configured'."""
        result = await call_tool(mcp_app, "proj_purge_archive")
        assert "not configured" in result.lower()

    async def test_filters_correctly(
        self,
        mcp_app: Any,
        cfg: ProjConfig,
        tmp_path: Path,
    ) -> None:
        """Only archived+purgeable+expired projects are returned as candidates."""
        # Set purge_after_days = 30
        await call_tool(mcp_app, "config_update", archive_purge_after_days=30)

        old_date = (date.today() - timedelta(days=60)).isoformat()
        recent_date = (date.today() - timedelta(days=10)).isoformat()

        # Eligible: archived, purgeable, old date
        self._setup_archived_project(cfg, "old-proj", tmp_path, archive_date=old_date)
        # Not eligible: archived but too recent
        self._setup_archived_project(cfg, "recent-proj", tmp_path, archive_date=recent_date)
        # Not eligible: archived but not purgeable
        self._setup_archived_project(cfg, "protected-proj", tmp_path, archive_date=old_date, purgeable=False)
        # Not eligible: not archived (active project)
        setup_project(cfg, "active-proj", str(tmp_path / "active-proj"))

        result = await call_tool(mcp_app, "proj_purge_archive")
        data = json.loads(result)
        names = [c["name"] for c in data["candidates"]]
        assert "old-proj" in names
        assert "recent-proj" not in names
        assert "protected-proj" not in names
        assert "active-proj" not in names
        assert data["count"] == 1

    async def test_skips_no_archive_date(
        self,
        mcp_app: Any,
        cfg: ProjConfig,
        tmp_path: Path,
    ) -> None:
        """Archived project without archive_date is skipped."""
        await call_tool(mcp_app, "config_update", archive_purge_after_days=1)
        self._setup_archived_project(cfg, "no-date-proj", tmp_path, archive_date=None)

        result = await call_tool(mcp_app, "proj_purge_archive")
        assert "no projects eligible" in result.lower()

    async def test_confirm_deletes(
        self,
        mcp_app: Any,
        cfg: ProjConfig,
        tmp_path: Path,
    ) -> None:
        """confirm=True removes tracking dir and index entry."""
        await call_tool(mcp_app, "config_update", archive_purge_after_days=30)

        old_date = (date.today() - timedelta(days=60)).isoformat()
        self._setup_archived_project(cfg, "doomed-proj", tmp_path, archive_date=old_date)

        tracking_dir = Path(cfg.tracking_dir) / "doomed-proj"
        assert tracking_dir.exists()

        result = await call_tool(mcp_app, "proj_purge_archive", confirm=True)
        assert "purged" in result.lower()
        assert "doomed-proj" in result

        # Tracking dir removed
        assert not tracking_dir.exists()
        # Index entry removed
        index = storage.load_index(cfg)
        assert "doomed-proj" not in index.projects


@pytest.mark.anyio
class TestConfigPurgeAfterDays:
    async def test_config_init_purge_after_days(
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
            archive_purge_after_days=90,
        )

        assert "saved" in result.lower()
        loaded = storage.load_config()
        assert loaded.archive.purge_after_days == 90

    async def test_config_update_purge_after_days(
        self,
        mcp_app: Any,
        cfg: ProjConfig,
    ) -> None:
        result = await call_tool(mcp_app, "config_update", archive_purge_after_days=60)

        assert "updated" in result.lower()
        loaded = storage.load_config()
        assert loaded.archive.purge_after_days == 60

    async def test_config_update_purge_after_days_rejects_zero(
        self,
        mcp_app: Any,
        cfg: ProjConfig,
    ) -> None:
        result = await call_tool(mcp_app, "config_update", archive_purge_after_days=0)
        assert "invalid" in result.lower()

    async def test_config_update_purge_after_days_rejects_negative(
        self,
        mcp_app: Any,
        cfg: ProjConfig,
    ) -> None:
        result = await call_tool(mcp_app, "config_update", archive_purge_after_days=-5)
        assert "invalid" in result.lower()

    async def test_config_load_shows_purge_after_days(
        self,
        mcp_app: Any,
        cfg: ProjConfig,
    ) -> None:
        result = await call_tool(mcp_app, "config_load")
        assert "archive.purge_after_days" in result
