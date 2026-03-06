"""Tests for the multi-dir migration feature.

Covers:
- ProjectMeta.from_dict() backward-compat shim (legacy path -> repos)
- _build_context() legacy format warning
- proj_load_session() legacy format warning
- proj_migrate_dirs() MCP tool (dry run, live, idempotent)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from server.lib import state, storage
from server.lib.models import ProjConfig, ProjectEntry, ProjectMeta, RepoEntry
from tests.conftest import call_tool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_legacy_meta(cfg: ProjConfig, name: str, path: str) -> None:
    """Write a meta.yaml in legacy single-path format (path key, empty repos)."""
    tracking = Path(cfg.tracking_dir) / name
    tracking.mkdir(parents=True, exist_ok=True)
    meta_data = {
        "version": 1,
        "name": name,
        "description": "A legacy project",
        "status": "active",
        "priority": "medium",
        "path": path,
        "repos": [],
        "tags": [],
        "links": [],
        "next_todo_id": 1,
        "git_enabled": True,
        "dates": {"created": "2026-01-01", "last_updated": "2026-01-01"},
        "permissions": {"auto_grant": True},
        "todoist": {},
        "trello": {},
    }
    meta_path = tracking / "meta.yaml"
    with meta_path.open("w") as f:
        yaml.dump(meta_data, f)
    (tracking / "todos.yaml").write_text("todos: []\n")
    (tracking / "NOTES.md").write_text(f"# {name}\n")
    (tracking / "agents.yaml").write_text(
        "version: 1\nagents:\n  define: null\n  research: null\n  decompose: null\n  execute: null\n"
    )


@pytest.fixture()
def legacy_project(cfg: ProjConfig, tmp_path: Path) -> tuple[str, ProjConfig]:
    """Create a project with legacy single-path format."""
    name = "legacy-proj"
    legacy_path = "/home/user/projects/legacy-proj"
    _write_legacy_meta(cfg, name, legacy_path)

    # Register in index
    tracking = Path(cfg.tracking_dir) / name
    index = storage.load_index(cfg)
    index.projects[name] = ProjectEntry(
        name=name, tracking_dir=str(tracking), created="2026-01-01"
    )
    index.active = name
    storage.save_index(cfg, index)
    state.set_session_active(name)

    return name, cfg


# ===========================================================================
# Unit tests: ProjectMeta.from_dict() backward-compat shim
# ===========================================================================


class TestFromDictLegacyPath:
    def test_from_dict_legacy_path_creates_repos(self) -> None:
        """Legacy `path` + empty `repos` should auto-populate repos."""
        meta = ProjectMeta.from_dict({"name": "x", "path": "/foo", "repos": []})
        assert len(meta.repos) == 1
        assert meta.repos[0].label == "code"
        assert meta.repos[0].path == "/foo"

    def test_from_dict_new_format_ignores_path(self) -> None:
        """When repos is non-empty, the legacy `path` key should be ignored."""
        meta = ProjectMeta.from_dict({
            "name": "x",
            "repos": [{"label": "app", "path": "/bar"}],
            "path": "/old",
        })
        assert len(meta.repos) == 1
        assert meta.repos[0].label == "app"
        assert meta.repos[0].path == "/bar"

    def test_from_dict_no_path_no_repos(self) -> None:
        """No path and no repos should give empty repos list."""
        meta = ProjectMeta.from_dict({"name": "x"})
        assert meta.repos == []


# ===========================================================================
# Integration tests: _build_context and MCP tools
# ===========================================================================


@pytest.mark.asyncio
class TestBuildContextWarning:
    async def test_build_context_warns_legacy_format(
        self, legacy_project: tuple[str, ProjConfig]
    ) -> None:
        """_build_context should include a migration warning for legacy projects."""
        from server.tools.context import _build_context

        name, cfg = legacy_project
        result = _build_context(cfg, name)
        assert "legacy single-path format" in result
        assert "/proj:migrate-dirs" in result

    async def test_build_context_no_warning_new_format(
        self, cfg: ProjConfig, tmp_path: Path
    ) -> None:
        """_build_context should NOT warn for projects using the new repos format."""
        from tests.conftest import setup_project
        from server.tools.context import _build_context

        setup_project(cfg, "new-proj", str(tmp_path))
        result = _build_context(cfg, "new-proj")
        assert "legacy single-path format" not in result


@pytest.mark.asyncio
class TestProjLoadSessionWarning:
    async def test_proj_load_session_warns_legacy_format(
        self, mcp_app: Any, legacy_project: tuple[str, ProjConfig]
    ) -> None:
        """proj_load_session should include migration warning for legacy projects."""
        name, _cfg = legacy_project
        state.clear_session_active()
        result = await call_tool(mcp_app, "proj_load_session", name=name)
        assert "legacy single-path format" in result
        assert "/proj:migrate-dirs" in result


@pytest.mark.asyncio
class TestProjMigrateDirs:
    async def test_migrate_dirs_dry_run(
        self, mcp_app: Any, legacy_project: tuple[str, ProjConfig]
    ) -> None:
        """Dry run should show preview but NOT modify meta.yaml on disk."""
        name, cfg = legacy_project
        result = await call_tool(mcp_app, "proj_migrate_dirs", dry_run=True)
        assert "Dry run" in result
        assert "/home/user/projects/legacy-proj" in result

        # Verify meta.yaml still has old format
        raw = storage._load_yaml(storage.meta_path(cfg, name))
        assert "path" in raw
        assert raw["repos"] == []

    async def test_migrate_dirs_live(
        self, mcp_app: Any, legacy_project: tuple[str, ProjConfig]
    ) -> None:
        """Live migration should update meta.yaml: repos populated, path removed."""
        name, cfg = legacy_project
        result = await call_tool(mcp_app, "proj_migrate_dirs", label="main")
        parsed = json.loads(result)
        assert parsed["migrated"] is True
        assert parsed["label"] == "main"
        assert parsed["path"] == "/home/user/projects/legacy-proj"

        # Verify on-disk meta.yaml
        raw = storage._load_yaml(storage.meta_path(cfg, name))
        assert "path" not in raw
        assert len(raw["repos"]) == 1
        assert raw["repos"][0]["label"] == "main"
        assert raw["repos"][0]["path"] == "/home/user/projects/legacy-proj"

    async def test_migrate_dirs_already_migrated(
        self, mcp_app: Any, cfg: ProjConfig, tmp_path: Path
    ) -> None:
        """Projects already using repos format should get 'already migrated' message."""
        from tests.conftest import setup_project

        setup_project(cfg, "new-proj", str(tmp_path))
        state.set_session_active("new-proj")
        result = await call_tool(mcp_app, "proj_migrate_dirs")
        assert "already uses multi-dir format" in result

    async def test_migrate_dirs_idempotent(
        self, mcp_app: Any, legacy_project: tuple[str, ProjConfig]
    ) -> None:
        """Migrating twice should succeed first time, then report already migrated."""
        name, cfg = legacy_project
        # First migration
        result1 = await call_tool(mcp_app, "proj_migrate_dirs", label="code")
        parsed = json.loads(result1)
        assert parsed["migrated"] is True

        # Second call should say already migrated
        result2 = await call_tool(mcp_app, "proj_migrate_dirs", label="code")
        assert "already uses multi-dir format" in result2
