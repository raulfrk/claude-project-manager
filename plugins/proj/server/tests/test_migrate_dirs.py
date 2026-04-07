"""Tests for the multi-dir migration feature.

Covers:
- ProjectMeta.from_dict() backward-compat shim (legacy path -> repos)
- _build_context() legacy format warning
- proj_load_session() legacy format warning
- proj_migrate_dirs() MCP tool (dry run, live, idempotent, all-projects,
  backup, rollback, JSON structure, missing tracking dir)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from server.lib import state, storage
from server.lib.models import ProjConfig, ProjectEntry, ProjectMeta
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
        "version: 1\nagents:\n  define: null\n"
        "  research: null\n  decompose: null\n  execute: null\n"
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
    index.projects[name] = ProjectEntry(name=name, tracking_dir=str(tracking), created="2026-01-01")
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
        meta = ProjectMeta.from_dict(
            {
                "name": "x",
                "repos": [{"label": "app", "path": "/bar"}],
                "path": "/old",
            }
        )
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
        from server.tools.context import _build_context
        from tests.conftest import setup_project

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
        parsed = json.loads(result)
        assert parsed["dry_run"] is True
        assert len(parsed["skipped"]) == 1
        assert parsed["skipped"][0]["old_path"] == "/home/user/projects/legacy-proj"
        assert parsed["skipped"][0]["dry_run"] is True

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
        assert len(parsed["migrated"]) == 1
        assert parsed["migrated"][0]["migrated"] is True
        assert parsed["migrated"][0]["label"] == "main"
        assert parsed["migrated"][0]["old_path"] == "/home/user/projects/legacy-proj"

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
        result = await call_tool(mcp_app, "proj_migrate_dirs", project_name="new-proj")
        parsed = json.loads(result)
        assert len(parsed["migrated"]) == 0
        assert len(parsed["skipped"]) == 1
        assert parsed["skipped"][0]["reason"] == "already multi-dir"

    async def test_migrate_dirs_idempotent(
        self, mcp_app: Any, legacy_project: tuple[str, ProjConfig]
    ) -> None:
        """Migrating twice should succeed first time, then report already migrated."""
        _name, _cfg = legacy_project
        # First migration
        result1 = await call_tool(mcp_app, "proj_migrate_dirs", label="code")
        parsed1 = json.loads(result1)
        assert len(parsed1["migrated"]) == 1
        assert parsed1["migrated"][0]["migrated"] is True

        # Second call should say already migrated
        result2 = await call_tool(mcp_app, "proj_migrate_dirs", label="code")
        parsed2 = json.loads(result2)
        assert len(parsed2["migrated"]) == 0
        assert len(parsed2["skipped"]) == 1
        assert parsed2["skipped"][0]["reason"] == "already multi-dir"


# ===========================================================================
# New tests: all-projects mode, backup, rollback, JSON structure
# ===========================================================================


@pytest.mark.asyncio
class TestProjMigrateDirsExtended:
    async def test_migrate_dirs_all_projects(
        self, mcp_app: Any, cfg: ProjConfig, tmp_path: Path
    ) -> None:
        """all_projects=True should migrate legacy, skip modern, ignore archived."""
        from tests.conftest import setup_project

        # 1) Legacy project
        _write_legacy_meta(cfg, "proj-legacy", "/home/user/legacy")

        # 2) Modern project (uses repos format) — creates its own index entry
        setup_project(cfg, "proj-modern", str(tmp_path / "modern"))

        # 3) Archived legacy project
        _write_legacy_meta(cfg, "proj-archived", "/home/user/archived")

        # Load index AFTER setup_project so we don't overwrite its entry
        index = storage.load_index(cfg)
        tracking_legacy = Path(cfg.tracking_dir) / "proj-legacy"
        index.projects["proj-legacy"] = ProjectEntry(
            name="proj-legacy", tracking_dir=str(tracking_legacy), created="2026-01-01"
        )
        tracking_archived = Path(cfg.tracking_dir) / "proj-archived"
        index.projects["proj-archived"] = ProjectEntry(
            name="proj-archived",
            tracking_dir=str(tracking_archived),
            created="2026-01-01",
            archived=True,
        )
        storage.save_index(cfg, index)

        result = await call_tool(mcp_app, "proj_migrate_dirs", all_projects=True)
        parsed = json.loads(result)

        migrated_names = [r["project"] for r in parsed["migrated"]]
        skipped_names = [r["project"] for r in parsed["skipped"]]

        assert "proj-legacy" in migrated_names
        assert "proj-modern" in skipped_names
        # Archived project should not appear at all
        all_names = migrated_names + skipped_names + [r["project"] for r in parsed["errors"]]
        assert "proj-archived" not in all_names

    async def test_migrate_dirs_single_project_overrides_all(
        self,
        mcp_app: Any,
        cfg: ProjConfig,
    ) -> None:
        """Explicit project_name should migrate only that project."""
        # Create two legacy projects
        _write_legacy_meta(cfg, "proj-a", "/home/user/a")
        _write_legacy_meta(cfg, "proj-b", "/home/user/b")
        index = storage.load_index(cfg)
        for name in ("proj-a", "proj-b"):
            tracking = Path(cfg.tracking_dir) / name
            index.projects[name] = ProjectEntry(
                name=name, tracking_dir=str(tracking), created="2026-01-01"
            )
        storage.save_index(cfg, index)

        result = await call_tool(mcp_app, "proj_migrate_dirs", project_name="proj-a")
        parsed = json.loads(result)

        assert len(parsed["migrated"]) == 1
        assert parsed["migrated"][0]["project"] == "proj-a"
        # proj-b should not appear anywhere
        all_projects = [
            r["project"] for r in parsed["migrated"] + parsed["skipped"] + parsed["errors"]
        ]
        assert "proj-b" not in all_projects

    async def test_migrate_dirs_backup_created(
        self, mcp_app: Any, legacy_project: tuple[str, ProjConfig]
    ) -> None:
        """Live migration should create a .bak- backup of meta.yaml."""
        name, cfg = legacy_project
        await call_tool(mcp_app, "proj_migrate_dirs")

        meta_dir = storage.meta_path(cfg, name).parent
        bak_files = list(meta_dir.glob("meta.yaml.bak-*"))
        assert len(bak_files) == 1

        # Backup should contain the original legacy format
        bak_raw = yaml.safe_load(bak_files[0].read_text())
        assert "path" in bak_raw
        assert bak_raw["repos"] == []

    async def test_migrate_dirs_auto_rollback(
        self,
        mcp_app: Any,
        legacy_project: tuple[str, ProjConfig],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """If _write_yaml fails, meta.yaml should be restored from backup."""
        name, cfg = legacy_project

        # Save original content for comparison
        original_raw = storage._load_yaml(storage.meta_path(cfg, name))

        # Monkeypatch _write_yaml to raise after backup is created
        real_write = storage._write_yaml

        def exploding_write(path: Path, data: dict) -> None:
            raise RuntimeError("simulated write failure")

        monkeypatch.setattr(storage, "_write_yaml", exploding_write)

        result = await call_tool(mcp_app, "proj_migrate_dirs", project_name=name)
        parsed = json.loads(result)

        # Should appear in errors
        assert len(parsed["errors"]) == 1
        assert "simulated write failure" in parsed["errors"][0]["error"]

        # meta.yaml should be restored to original content
        monkeypatch.setattr(storage, "_write_yaml", real_write)
        restored_raw = storage._load_yaml(storage.meta_path(cfg, name))
        assert restored_raw["path"] == original_raw["path"]
        assert restored_raw["repos"] == original_raw["repos"]

    async def test_migrate_dirs_json_return_structure(
        self, mcp_app: Any, legacy_project: tuple[str, ProjConfig]
    ) -> None:
        """Return JSON must have migrated, skipped, errors, dry_run keys."""
        _name, _cfg = legacy_project
        result = await call_tool(mcp_app, "proj_migrate_dirs")
        parsed = json.loads(result)

        assert "migrated" in parsed
        assert "skipped" in parsed
        assert "errors" in parsed
        assert "dry_run" in parsed
        assert isinstance(parsed["migrated"], list)
        assert isinstance(parsed["skipped"], list)
        assert isinstance(parsed["errors"], list)
        assert isinstance(parsed["dry_run"], bool)

    async def test_migrate_dirs_missing_tracking_dir(
        self,
        mcp_app: Any,
        cfg: ProjConfig,
    ) -> None:
        """Index entry pointing to non-existent dir should not crash; appears in skipped."""
        index = storage.load_index(cfg)
        index.projects["ghost-proj"] = ProjectEntry(
            name="ghost-proj",
            tracking_dir=str(Path(cfg.tracking_dir) / "ghost-proj"),
            created="2026-01-01",
        )
        storage.save_index(cfg, index)

        result = await call_tool(mcp_app, "proj_migrate_dirs", project_name="ghost-proj")
        parsed = json.loads(result)

        # Should not crash; ghost project in skipped with reason
        assert len(parsed["errors"]) == 0
        assert len(parsed["skipped"]) == 1
        assert parsed["skipped"][0]["project"] == "ghost-proj"
        assert parsed["skipped"][0]["reason"] == "meta.yaml missing"
