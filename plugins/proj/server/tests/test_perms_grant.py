"""Tests for proj_setup_permissions / proj_revoke_all_permissions."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import Mock

import pytest

from server.lib import state, storage
from server.lib.models import (
    PermissionsConfig,
    ProjConfig,
    ProjectDates,
    ProjectEntry,
    ProjectMeta,
    RepoEntry,
    TodoistSync,
)
from server.tools.perms_grant import (
    _collect_sandbox_write_paths,
    _compute_setup_paths,
    collect_paths,
    revoke_all_permissions,
    setup_permissions,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_cfg(
    worktree_integration: bool = False,
) -> ProjConfig:
    cfg = ProjConfig(tracking_dir="/tmp/tracking", worktree_integration=worktree_integration)
    cfg.permissions = PermissionsConfig(
        auto_grant=True,
        auto_allow_mcps=True,
    )
    cfg.todoist = TodoistSync(enabled=False)
    return cfg


def _make_meta(repos: list[RepoEntry]) -> ProjectMeta:
    today = str(date.today())
    return ProjectMeta(
        name="test-project",
        repos=repos,
        dates=ProjectDates(created=today, last_updated=today),
    )


def _write_settings(path: Path, allow: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"permissions": {"allow": allow}}))


def _read_allow(path: Path) -> list[str]:
    data = json.loads(path.read_text())
    return data.get("permissions", {}).get("allow", [])


# ── collect_paths ─────────────────────────────────────────────────────────────


class TestCollectPaths:
    def test_returns_repo_paths(self) -> None:
        meta = _make_meta(
            repos=[
                RepoEntry(label="code", path="/home/user/proj"),
                RepoEntry(label="docs", path="/home/user/docs"),
            ]
        )
        cfg = _make_cfg()
        paths = collect_paths(meta, cfg)
        assert "/home/user/proj" in paths
        assert "/home/user/docs" in paths

    def test_no_worktree_paths_when_disabled(self, tmp_path: Path) -> None:
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(worktree_integration=False)
        paths = collect_paths(meta, cfg)
        assert len(paths) == 2  # repo + tracking_dir

    def test_worktree_paths_added_when_enabled(self) -> None:
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(worktree_integration=True)
        paths = collect_paths(meta, cfg, worktree_base_paths=["/home/user/extra-repo"])
        assert "/home/user/proj" in paths
        assert "/home/user/extra-repo" in paths

    def test_no_duplicates_when_repo_in_worktree_paths(self) -> None:
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(worktree_integration=True)
        paths = collect_paths(meta, cfg, worktree_base_paths=["/home/user/proj"])
        assert paths.count("/home/user/proj") == 1

    def test_no_worktree_paths_when_none_provided(self) -> None:
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(worktree_integration=True)
        paths = collect_paths(meta, cfg)
        assert "/home/user/proj" in paths
        assert len(paths) == 2  # repo + tracking_dir


# ── setup_permissions ─────────────────────────────────────────────────────────


class TestSetupPermissions:
    def test_returns_computed_counts_without_batch_fn(self) -> None:
        """Without batch_setup_fn, returns computed counts (hooks handle dispatch)."""
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg()
        counts = setup_permissions(
            meta, cfg,
            mcp_servers=["plugin_proj_proj", "plugin_perms_perms"],
        )

        # writable repo + tracking_dir = 2 paths, 2 MCP servers
        assert counts["sandbox_paths"] == 2
        assert counts["mcp_rules"] == 2

    def test_returns_zero_when_nothing_to_do(self) -> None:
        """No paths and no servers returns zero counts."""
        meta = _make_meta(repos=[])
        cfg = ProjConfig(tracking_dir=None, worktree_integration=False)
        counts = setup_permissions(meta, cfg, mcp_servers=[])

        assert sum(counts.values()) == 0

    # ── batch_setup_fn delegation tests ──

    def test_batch_setup_fn_called_with_correct_paths_and_servers(self) -> None:
        mock_fn = Mock(return_value="Sandbox paths added: 2, MCP rules added: 1")
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg()
        cfg.tracking_dir = "/tmp/tracking"

        counts = setup_permissions(
            meta, cfg,
            mcp_servers=["plugin_proj_proj"],
            batch_setup_fn=mock_fn,
        )

        mock_fn.assert_called_once()
        call_kwargs = mock_fn.call_args.kwargs
        assert "/home/user/proj" in call_kwargs["paths"]
        assert "/tmp/tracking" in call_kwargs["paths"]
        assert call_kwargs["mcp_servers"] == ["plugin_proj_proj"]
        assert counts["sandbox_paths"] == 2
        assert counts["mcp_rules"] == 1

    def test_batch_setup_fn_excludes_reference_repos(self) -> None:
        mock_fn = Mock(return_value="Sandbox paths added: 1, MCP rules added: 0")
        meta = _make_meta(repos=[
            RepoEntry(label="code", path="/home/user/proj"),
            RepoEntry(label="docs", path="/home/user/docs", reference=True),
        ])
        cfg = _make_cfg()
        cfg.tracking_dir = "/tmp/tracking"

        setup_permissions(meta, cfg, batch_setup_fn=mock_fn)

        call_kwargs = mock_fn.call_args.kwargs
        paths = call_kwargs["paths"]
        assert "/home/user/proj" in paths
        assert "/home/user/docs" not in paths

    def test_batch_setup_fn_includes_archive_destination(self) -> None:
        mock_fn = Mock(return_value="Sandbox paths added: 3, MCP rules added: 0")
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg()
        cfg.tracking_dir = "/tmp/tracking"

        setup_permissions(
            meta, cfg,
            archive_destination="/home/user/archived",
            batch_setup_fn=mock_fn,
        )

        call_kwargs = mock_fn.call_args.kwargs
        paths = call_kwargs["paths"]
        assert "/home/user/archived" in paths

    def test_batch_setup_fn_not_called_when_nothing_to_do(self) -> None:
        mock_fn = Mock()
        meta = _make_meta(repos=[])
        cfg = _make_cfg()
        cfg.tracking_dir = ""

        counts = setup_permissions(meta, cfg, batch_setup_fn=mock_fn)

        mock_fn.assert_not_called()
        assert counts == {"sandbox_paths": 0, "mcp_rules": 0, "additional_directories": 0}

    def test_batch_setup_fn_parses_counts_from_result(self) -> None:
        mock_fn = Mock(return_value="Sandbox paths added: 5, MCP rules added: 3")
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg()

        counts = setup_permissions(
            meta, cfg,
            mcp_servers=["a", "b", "c"],
            batch_setup_fn=mock_fn,
        )

        assert counts["sandbox_paths"] == 5
        assert counts["mcp_rules"] == 3


# ── MCP tool integration ──────────────────────────────────────────────────────


class TestProjSetupPermissionsTool:
    @pytest.mark.anyio
    async def test_setup_permissions_tool_registered(self, mcp_app_with_grant) -> None:  # type: ignore[no-untyped-def]
        from tests.conftest import call_tool

        result = await call_tool(mcp_app_with_grant, "proj_setup_permissions")
        assert isinstance(result, str)

    @pytest.mark.anyio
    async def test_setup_permissions_adds_mcp_rules(
        self,
        cfg: ProjConfig,
        tmp_path: Path,
        mcp_app_with_grant,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:  # type: ignore[no-untyped-def]
        from tests.conftest import call_tool, setup_project

        repo_path = str(tmp_path / "myrepo")
        setup_project(cfg, "myproject", repo_path)
        state.set_session_active("myproject")

        settings_path = tmp_path / ".claude" / "settings.json"
        _write_settings(settings_path, allow=[])
        monkeypatch.setattr("server.lib.perms_helpers._USER_SETTINGS", settings_path)
        monkeypatch.setattr("server.tools.perms_grant._USER_SETTINGS", settings_path)


        result = await call_tool(
            mcp_app_with_grant,
            "proj_setup_permissions",
            mcp_servers=["plugin_proj_proj"],
        )
        # Without batch_fn, returns computed counts (hooks handle dispatch)
        assert "rule(s)" in result or "up to date" in result


# ── Sandbox mode tests ─────────────────────────────────────────────────────────


def _write_local_settings(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def _read_local_allow(path: Path) -> list[str]:
    data = json.loads(path.read_text())
    return data.get("permissions", {}).get("allow", [])


def _read_sandbox_allow_write(path: Path) -> list[str]:
    data = json.loads(path.read_text())
    return data.get("sandbox", {}).get("filesystem", {}).get("allowWrite", [])


class TestSandboxModeDetection:
    def test_is_sandbox_enabled_true(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from server.tools.perms_grant import _is_sandbox_enabled

        local_path = tmp_path / ".claude" / "settings.local.json"
        _write_local_settings(local_path, {"sandbox": {"enabled": True}})
        monkeypatch.setattr("server.tools.perms_grant._USER_LOCAL_SETTINGS", local_path)
        assert _is_sandbox_enabled() is True

    def test_is_sandbox_enabled_false_when_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from server.tools.perms_grant import _is_sandbox_enabled

        monkeypatch.setattr(
            "server.tools.perms_grant._USER_LOCAL_SETTINGS",
            tmp_path / "nonexistent.json",
        )
        assert _is_sandbox_enabled() is False

    def test_is_sandbox_enabled_false_when_disabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from server.tools.perms_grant import _is_sandbox_enabled

        local_path = tmp_path / ".claude" / "settings.local.json"
        _write_local_settings(local_path, {"sandbox": {"enabled": False}})
        monkeypatch.setattr("server.tools.perms_grant._USER_LOCAL_SETTINGS", local_path)
        assert _is_sandbox_enabled() is False

    def test_is_sandbox_enabled_project_level_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sandbox enabled at project level but not user level is detected."""
        from server.tools.perms_grant import _is_sandbox_enabled

        # User-level has no sandbox
        monkeypatch.setattr(
            "server.tools.perms_grant._USER_LOCAL_SETTINGS",
            tmp_path / "nonexistent.json",
        )
        # Project-level has sandbox enabled
        project_dir = tmp_path / "myproject"
        proj_local = project_dir / ".claude" / "settings.local.json"
        _write_local_settings(proj_local, {"sandbox": {"enabled": True}})

        assert _is_sandbox_enabled(project_dir) is True

    def test_is_sandbox_enabled_user_false_project_true(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When user-level sandbox is disabled but project-level is enabled, returns True."""
        from server.tools.perms_grant import _is_sandbox_enabled

        user_local = tmp_path / "user" / ".claude" / "settings.local.json"
        _write_local_settings(user_local, {"sandbox": {"enabled": False}})
        monkeypatch.setattr("server.tools.perms_grant._USER_LOCAL_SETTINGS", user_local)

        project_dir = tmp_path / "myproject"
        proj_local = project_dir / ".claude" / "settings.local.json"
        _write_local_settings(proj_local, {"sandbox": {"enabled": True}})

        assert _is_sandbox_enabled(project_dir) is True

    def test_is_sandbox_enabled_both_false(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When both user-level and project-level sandbox are disabled, returns False."""
        from server.tools.perms_grant import _is_sandbox_enabled

        user_local = tmp_path / "user" / ".claude" / "settings.local.json"
        _write_local_settings(user_local, {"sandbox": {"enabled": False}})
        monkeypatch.setattr("server.tools.perms_grant._USER_LOCAL_SETTINGS", user_local)

        project_dir = tmp_path / "myproject"
        proj_local = project_dir / ".claude" / "settings.local.json"
        _write_local_settings(proj_local, {"sandbox": {"enabled": False}})

        assert _is_sandbox_enabled(project_dir) is False

    def test_is_sandbox_enabled_no_project_dir_only_checks_user(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When project_dir is None, only user-level is checked (backward compat)."""
        from server.tools.perms_grant import _is_sandbox_enabled

        monkeypatch.setattr(
            "server.tools.perms_grant._USER_LOCAL_SETTINGS",
            tmp_path / "nonexistent.json",
        )
        assert _is_sandbox_enabled(None) is False


class TestSetupPermissionsSandbox:
    def test_adds_sandbox_write_paths(self) -> None:
        """Without batch_setup_fn, returns computed counts for sandbox paths."""
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg()
        cfg.tracking_dir = "/tmp/tracking"
        counts = setup_permissions(meta, cfg)

        # writable repo + tracking_dir = 2 paths
        assert counts["sandbox_paths"] == 2
        assert counts["mcp_rules"] == 0

    def test_reference_repo_not_in_allow_write(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        local_path = tmp_path / ".claude" / "settings.local.json"
        _write_local_settings(local_path, {
            "sandbox": {"enabled": True},
            "permissions": {"allow": []},
        })
        monkeypatch.setattr("server.lib.perms_helpers._USER_LOCAL_SETTINGS", local_path)
        monkeypatch.setattr("server.tools.perms_grant._USER_LOCAL_SETTINGS", local_path)

        monkeypatch.setattr("server.lib.perms_helpers._USER_SETTINGS", tmp_path / "settings.json")
        monkeypatch.setattr("server.tools.perms_grant._USER_SETTINGS", tmp_path / "settings.json")


        meta = _make_meta(repos=[RepoEntry(label="docs", path="/home/user/docs", reference=True)])
        cfg = _make_cfg()
        cfg.tracking_dir = ""
        counts = setup_permissions(meta, cfg)

        aw = _read_sandbox_allow_write(local_path)
        assert "/home/user/docs" not in aw
        assert counts["sandbox_paths"] == 0

    def test_mixed_repos_writable_and_reference(self) -> None:
        """Without batch_setup_fn, reference repos are excluded from computed path count."""
        meta = _make_meta(repos=[
            RepoEntry(label="code", path="/home/user/proj"),
            RepoEntry(label="docs", path="/home/user/docs", reference=True),
        ])
        cfg = _make_cfg()
        cfg.tracking_dir = "/tmp/tracking"
        counts = setup_permissions(meta, cfg, mcp_servers=["plugin_proj_proj"])

        # Only writable repo + tracking_dir = 2 paths (reference repo excluded)
        assert counts["sandbox_paths"] == 2
        assert counts["mcp_rules"] == 1

    def test_mcp_rules_and_sandbox_paths(self) -> None:
        """Without batch_setup_fn, returns computed counts for both paths and MCP servers."""
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg()
        counts = setup_permissions(
            meta, cfg,
            mcp_servers=["plugin_proj_proj"],
        )

        # repo + tracking_dir = 2 paths, 1 MCP server, 2 additional_directories
        assert counts["sandbox_paths"] == 2
        assert counts["mcp_rules"] == 1
        assert counts["additional_directories"] == 2

    def test_idempotent_sandbox(self) -> None:
        """Without batch_setup_fn, repeated calls return the same computed counts.

        Idempotency is guaranteed by the batch_setup_fn (perms plugin) deduplicating;
        without it, computed counts are always the same since no local state changes.
        """
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg()
        counts1 = setup_permissions(meta, cfg, mcp_servers=["proj"])
        counts2 = setup_permissions(meta, cfg, mcp_servers=["proj"])

        assert counts1 == counts2


# ── revoke_all_permissions ─────────────────────────────────────────────────────


class TestRevokeAllPermissions:
    def test_setup_then_revoke_removes_mcp_rules(self) -> None:
        """Without batch fns, setup returns computed counts; revoke without mcp_servers
        returns sandbox_paths count but mcp_rules=0 (MCP rules shared across projects)."""
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg()
        cfg.tracking_dir = "/tmp/tracking"

        # Setup returns computed counts (no local writes)
        setup_counts = setup_permissions(
            meta, cfg,
            mcp_servers=["plugin_proj_proj"],
        )
        assert setup_counts["sandbox_paths"] == 2
        assert setup_counts["mcp_rules"] == 1

        # Revoke without mcp_servers -- MCP rules are shared across projects
        revoke_counts = revoke_all_permissions(meta, cfg)
        assert revoke_counts["sandbox_paths"] == 2  # repo + tracking
        assert revoke_counts["mcp_rules"] == 0  # not explicitly provided

    def test_revoke_with_mcp_servers_removes_mcp_rules(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings_path = tmp_path / ".claude" / "settings.json"
        _write_settings(settings_path, allow=[])
        monkeypatch.setattr("server.lib.perms_helpers._USER_SETTINGS", settings_path)
        monkeypatch.setattr("server.tools.perms_grant._USER_SETTINGS", settings_path)

        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg()
        cfg.tracking_dir = "/tmp/tracking"

        setup_permissions(
            meta, cfg,
            mcp_servers=["plugin_proj_proj"],
        )

        # Revoke with explicit mcp_servers -- MCP rules should also be removed
        counts = revoke_all_permissions(meta, cfg, mcp_servers=["plugin_proj_proj"])
        assert counts["mcp_rules"] == 1
        assert _read_allow(settings_path) == []

    def test_revoke_no_permissions_returns_zero(self) -> None:
        """Without batch_revoke_fn and no paths/servers, returns zero counts."""
        meta = _make_meta(repos=[])
        cfg = _make_cfg()
        cfg.tracking_dir = ""

        counts = revoke_all_permissions(meta, cfg)
        assert sum(counts.values()) == 0

    def test_revoke_preserves_unrelated_rules(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings_path = tmp_path / ".claude" / "settings.json"
        unrelated = ["Read(//some/other/path/**)", "mcp__unrelated_server__*"]
        _write_settings(settings_path, allow=unrelated)
        monkeypatch.setattr("server.lib.perms_helpers._USER_SETTINGS", settings_path)
        monkeypatch.setattr("server.tools.perms_grant._USER_SETTINGS", settings_path)

        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg()
        cfg.tracking_dir = ""

        counts = revoke_all_permissions(meta, cfg)
        allow = _read_allow(settings_path)
        # Unrelated rules should remain
        for rule in unrelated:
            assert rule in allow

    def test_revoke_idempotent(self) -> None:
        """Without batch_revoke_fn, repeated calls return the same computed counts.

        Idempotency is guaranteed by the batch_revoke_fn (perms plugin) deduplicating;
        without it, computed counts are always the same since no local state changes.
        """
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg()
        cfg.tracking_dir = "/tmp/tracking"

        counts1 = revoke_all_permissions(meta, cfg)
        counts2 = revoke_all_permissions(meta, cfg)
        assert counts1 == counts2

    def test_revoke_removes_sandbox_write_paths(self) -> None:
        """Without batch_revoke_fn, returns computed counts for sandbox paths to remove."""
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg()
        cfg.tracking_dir = "/tmp/tracking"

        counts = revoke_all_permissions(meta, cfg)
        # writable repo + tracking_dir = 2 paths
        assert counts["sandbox_paths"] == 2
        assert counts["mcp_rules"] == 0

    def test_revoke_mixed_repos(self) -> None:
        """Without batch_revoke_fn, reference repos are excluded from computed path count."""
        meta = _make_meta(repos=[
            RepoEntry(label="code", path="/home/user/proj"),
            RepoEntry(label="docs", path="/home/user/docs", reference=True),
        ])
        cfg = _make_cfg()
        cfg.tracking_dir = "/tmp/tracking"

        counts = revoke_all_permissions(meta, cfg, mcp_servers=["proj"])
        # Only writable repo + tracking_dir = 2 paths (reference repo excluded)
        assert counts["sandbox_paths"] == 2
        assert counts["mcp_rules"] == 1

    # ── batch_revoke_fn delegation tests ──

    def test_batch_revoke_fn_called_with_correct_paths_and_servers(self) -> None:
        mock_fn = Mock(return_value="sandbox paths removed: 2, MCP rules removed: 1")
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg()
        cfg.tracking_dir = "/tmp/tracking"

        counts = revoke_all_permissions(
            meta, cfg,
            mcp_servers=["plugin_proj_proj"],
            batch_revoke_fn=mock_fn,
        )

        mock_fn.assert_called_once()
        call_kwargs = mock_fn.call_args.kwargs
        assert "/home/user/proj" in call_kwargs["paths"]
        assert "/tmp/tracking" in call_kwargs["paths"]
        assert call_kwargs["mcp_servers"] == ["plugin_proj_proj"]
        assert counts["sandbox_paths"] == 2
        assert counts["mcp_rules"] == 1

    def test_batch_revoke_fn_excludes_reference_repos(self) -> None:
        mock_fn = Mock(return_value="sandbox paths removed: 1, MCP rules removed: 0")
        meta = _make_meta(repos=[
            RepoEntry(label="code", path="/home/user/proj"),
            RepoEntry(label="docs", path="/home/user/docs", reference=True),
        ])
        cfg = _make_cfg()
        cfg.tracking_dir = "/tmp/tracking"

        revoke_all_permissions(meta, cfg, batch_revoke_fn=mock_fn)

        call_kwargs = mock_fn.call_args.kwargs
        paths = call_kwargs["paths"]
        assert "/home/user/proj" in paths
        assert "/home/user/docs" not in paths

    def test_batch_revoke_fn_without_mcp_servers(self) -> None:
        mock_fn = Mock(return_value="sandbox paths removed: 2, MCP rules removed: 0")
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg()
        cfg.tracking_dir = "/tmp/tracking"

        counts = revoke_all_permissions(meta, cfg, batch_revoke_fn=mock_fn)

        call_kwargs = mock_fn.call_args.kwargs
        assert call_kwargs["mcp_servers"] == []
        assert counts["mcp_rules"] == 0

    def test_batch_revoke_fn_not_called_when_nothing_to_do(self) -> None:
        mock_fn = Mock()
        meta = _make_meta(repos=[])
        cfg = _make_cfg()
        cfg.tracking_dir = ""

        counts = revoke_all_permissions(meta, cfg, batch_revoke_fn=mock_fn)

        mock_fn.assert_not_called()
        assert counts == {"sandbox_paths": 0, "mcp_rules": 0, "additional_directories": 0}

    def test_batch_revoke_fn_parses_counts_from_result(self) -> None:
        mock_fn = Mock(return_value="sandbox paths removed: 4, MCP rules removed: 2")
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg()

        counts = revoke_all_permissions(
            meta, cfg,
            mcp_servers=["a", "b"],
            batch_revoke_fn=mock_fn,
        )

        assert counts["sandbox_paths"] == 4
        assert counts["mcp_rules"] == 2


# ── proj_archive revokes permissions ──────────────────────────────────────────


class TestArchiveRevokesPermissions:
    @pytest.mark.anyio
    async def test_archive_revokes_permissions(
        self,
        cfg: ProjConfig,
        tmp_path: Path,
        mcp_app_with_grant,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from tests.conftest import call_tool, setup_project

        repo_path = str(tmp_path / "myrepo")
        Path(repo_path).mkdir(parents=True, exist_ok=True)
        setup_project(cfg, "myproject", repo_path)
        state.set_session_active("myproject")

        settings_path = tmp_path / ".claude" / "settings.json"
        _write_settings(settings_path, allow=[])
        monkeypatch.setattr("server.lib.perms_helpers._USER_SETTINGS", settings_path)
        monkeypatch.setattr("server.tools.perms_grant._USER_SETTINGS", settings_path)


        # Setup permissions (returns computed counts, hooks handle dispatch)
        setup_result = await call_tool(
            mcp_app_with_grant,
            "proj_setup_permissions",
            mcp_servers=["plugin_proj_proj"],
        )
        assert "rule(s)" in setup_result

        # Archive the project
        result = await call_tool(mcp_app_with_grant, "proj_archive", name="myproject")
        assert "Archived" in result

    @pytest.mark.anyio
    async def test_archive_succeeds_without_permissions(
        self,
        cfg: ProjConfig,
        tmp_path: Path,
        mcp_app_with_grant,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from tests.conftest import call_tool, setup_project

        repo_path = str(tmp_path / "myrepo")
        Path(repo_path).mkdir(parents=True, exist_ok=True)
        setup_project(cfg, "myproject", repo_path)
        state.set_session_active("myproject")

        settings_path = tmp_path / ".claude" / "settings.json"
        _write_settings(settings_path, allow=[])
        monkeypatch.setattr("server.lib.perms_helpers._USER_SETTINGS", settings_path)
        monkeypatch.setattr("server.tools.perms_grant._USER_SETTINGS", settings_path)


        # Archive without setting up permissions first
        result = await call_tool(mcp_app_with_grant, "proj_archive", name="myproject")
        assert "Archived" in result
        # No "Revoked" since there were no permissions to revoke
        assert _read_allow(settings_path) == []


# ── T19: Root-aware _compute_setup_paths ─────────────────────────────────────


class TestComputeSetupPathsRootAware:
    def test_compute_setup_paths_uses_projects_root(self) -> None:
        """When projects_root is set, returns root instead of per-repo paths."""
        meta = _make_meta(repos=[
            RepoEntry(label="code", path="/home/user/projects/repo-a"),
            RepoEntry(label="lib", path="/home/user/projects/repo-b"),
        ])
        cfg = _make_cfg()
        cfg.permissions.projects_root = "/home/user/projects"
        cfg.tracking_dir = ""

        paths = _compute_setup_paths(meta, cfg)

        assert "/home/user/projects" in paths
        # Per-repo paths should NOT appear when root is set
        assert "/home/user/projects/repo-a" not in paths
        assert "/home/user/projects/repo-b" not in paths

    def test_compute_setup_paths_tracking_root_containment(self) -> None:
        """tracking_root under projects_root is skipped (containment check)."""
        meta = _make_meta(repos=[
            RepoEntry(label="code", path="/home/user/projects/repo-a"),
        ])
        cfg = _make_cfg()
        cfg.permissions.projects_root = "/home/user/projects"
        cfg.permissions.tracking_root = "/home/user/projects/tracking"

        paths = _compute_setup_paths(meta, cfg)

        assert "/home/user/projects" in paths
        # tracking_root is under projects_root, should be skipped
        assert "/home/user/projects/tracking" not in paths

    def test_compute_setup_paths_archive_containment(self) -> None:
        """archive_dest under projects_root is skipped (containment check)."""
        meta = _make_meta(repos=[
            RepoEntry(label="code", path="/home/user/projects/repo-a"),
        ])
        cfg = _make_cfg()
        cfg.permissions.projects_root = "/home/user/projects"
        cfg.tracking_dir = ""

        paths = _compute_setup_paths(
            meta, cfg, archive_destination="/home/user/projects/archived",
        )

        assert "/home/user/projects" in paths
        # archive_dest is under projects_root, should be skipped
        assert "/home/user/projects/archived" not in paths

    def test_compute_setup_paths_tracking_root_separate(self) -> None:
        """tracking_root outside projects_root is included."""
        meta = _make_meta(repos=[
            RepoEntry(label="code", path="/home/user/projects/repo-a"),
        ])
        cfg = _make_cfg()
        cfg.permissions.projects_root = "/home/user/projects"
        cfg.permissions.tracking_root = "/home/user/tracking"

        paths = _compute_setup_paths(meta, cfg)

        assert "/home/user/projects" in paths
        assert "/home/user/tracking" in paths


# ── T20: Backward compatibility (no roots fallback) ─────────────────────────


class TestComputeSetupPathsBackwardCompat:
    def test_compute_setup_paths_no_roots_fallback(self) -> None:
        """When projects_root=None, uses per-repo paths (legacy behavior)."""
        meta = _make_meta(repos=[
            RepoEntry(label="code", path="/home/user/proj"),
            RepoEntry(label="docs", path="/home/user/docs", reference=True),
        ])
        cfg = _make_cfg()
        cfg.permissions.projects_root = None
        cfg.permissions.tracking_root = None
        cfg.tracking_dir = "/tmp/tracking"

        paths = _compute_setup_paths(meta, cfg)

        # Writable repo included, reference repo excluded
        assert "/home/user/proj" in paths
        assert "/home/user/docs" not in paths
        # tracking_dir used as fallback
        assert "/tmp/tracking" in paths

    def test_collect_sandbox_write_paths_no_roots_fallback(self) -> None:
        """When projects_root=None, _collect_sandbox_write_paths uses per-repo paths (legacy)."""
        meta = _make_meta(repos=[
            RepoEntry(label="code", path="/home/user/proj"),
            RepoEntry(label="docs", path="/home/user/docs", reference=True),
        ])
        cfg = _make_cfg()
        cfg.permissions.projects_root = None
        cfg.permissions.tracking_root = None
        cfg.tracking_dir = "/tmp/tracking"

        paths = _collect_sandbox_write_paths(meta, cfg)

        # Writable repo included, reference repo excluded
        assert "/home/user/proj" in paths
        assert "/home/user/docs" not in paths
        # tracking_dir used as fallback
        assert "/tmp/tracking" in paths


# ── T22: User custom sandbox paths (root mode exclusion) ────────────────────


class TestComputeSetupPathsUserPaths:
    def test_compute_setup_paths_does_not_include_user_paths(self) -> None:
        """Root-mode only returns roots, not per-repo paths -- user custom paths are separate."""
        meta = _make_meta(repos=[
            RepoEntry(label="code", path="/home/user/projects/repo-a"),
            RepoEntry(label="lib", path="/home/user/projects/repo-b"),
            RepoEntry(label="extra", path="/home/user/other/repo-c"),
        ])
        cfg = _make_cfg()
        cfg.permissions.projects_root = "/home/user/projects"
        cfg.permissions.tracking_root = None
        cfg.tracking_dir = ""

        paths = _compute_setup_paths(meta, cfg)

        # Only root is included, not individual repo paths
        assert paths == ["/home/user/projects"]
        # Per-repo paths are NOT present
        assert "/home/user/projects/repo-a" not in paths
        assert "/home/user/projects/repo-b" not in paths
        # Repos outside projects_root are also NOT present (root mode replaces per-repo)
        assert "/home/user/other/repo-c" not in paths


# ── Fixture ───────────────────────────────────────────────────────────────────


@pytest.fixture()
def mcp_app_with_grant(cfg: ProjConfig):  # type: ignore[no-untyped-def]
    """FastMCP app with perms_grant registered in addition to standard tools."""
    from mcp.server.fastmcp import FastMCP

    from server.tools import (
        config,
        content,
        context,
        git,
        migrate,
        perms_grant,
        perms_sync,
        projects,
        todos,
    )

    app = FastMCP("test-proj-grant")
    config.register(app)
    projects.register(app)
    todos.register(app)
    content.register(app)
    git.register(app)
    context.register(app)
    migrate.register(app)
    perms_sync.register(app)
    perms_grant.register(app)
    return app
