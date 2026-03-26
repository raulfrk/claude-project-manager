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
    def test_adds_mcp_rules(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        settings_path = tmp_path / ".claude" / "settings.json"
        _write_settings(settings_path, allow=[])
        monkeypatch.setattr("server.lib.perms_helpers._USER_SETTINGS", settings_path)
        monkeypatch.setattr("server.tools.perms_grant._USER_SETTINGS", settings_path)
        monkeypatch.setattr("server.tools.perms_grant._USER_LOCAL_SETTINGS", tmp_path / "nonexistent.json")

        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg()
        counts = setup_permissions(
            meta, cfg,
            mcp_servers=["plugin_proj_proj", "plugin_perms_perms"],
        )

        allow = _read_allow(settings_path)
        assert "mcp__plugin_proj_proj__*" in allow
        assert "mcp__plugin_perms_perms__*" in allow
        assert counts["mcp_rules"] == 2

    def test_idempotent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        settings_path = tmp_path / ".claude" / "settings.json"
        _write_settings(settings_path, allow=[])
        monkeypatch.setattr("server.lib.perms_helpers._USER_SETTINGS", settings_path)
        monkeypatch.setattr("server.tools.perms_grant._USER_SETTINGS", settings_path)
        monkeypatch.setattr("server.tools.perms_grant._USER_LOCAL_SETTINGS", tmp_path / "nonexistent.json")

        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg()
        setup_permissions(meta, cfg, mcp_servers=["proj"])
        counts2 = setup_permissions(meta, cfg, mcp_servers=["proj"])

        assert sum(counts2.values()) == 0

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
        assert counts == {"sandbox_paths": 0, "mcp_rules": 0}

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
        assert "rule(s)" in result or "up to date" in result
        allow = _read_allow(settings_path)
        assert "mcp__plugin_proj_proj__*" in allow


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
    def test_adds_sandbox_write_paths(
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


        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg()
        cfg.tracking_dir = "/tmp/tracking"
        counts = setup_permissions(meta, cfg)

        aw = _read_sandbox_allow_write(local_path)
        assert "/home/user/proj" in aw
        assert counts["sandbox_paths"] > 0

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

    def test_mixed_repos_writable_and_reference(
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


        meta = _make_meta(repos=[
            RepoEntry(label="code", path="/home/user/proj"),
            RepoEntry(label="docs", path="/home/user/docs", reference=True),
        ])
        cfg = _make_cfg()
        cfg.tracking_dir = "/tmp/tracking"
        counts = setup_permissions(meta, cfg, mcp_servers=["plugin_proj_proj"])

        aw = _read_sandbox_allow_write(local_path)
        assert "/home/user/proj" in aw
        assert "/home/user/docs" not in aw
        assert counts["sandbox_paths"] >= 1  # proj + tracking

    def test_mcp_rules_and_sandbox_paths(
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


        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg()
        counts = setup_permissions(
            meta, cfg,
            mcp_servers=["plugin_proj_proj"],
        )

        allow = _read_local_allow(local_path)
        assert "mcp__plugin_proj_proj__*" in allow
        aw = _read_sandbox_allow_write(local_path)
        assert "/home/user/proj" in aw
        assert sum(counts.values()) > 0

    def test_idempotent_sandbox(
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


        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg()
        setup_permissions(meta, cfg, mcp_servers=["proj"])
        counts2 = setup_permissions(meta, cfg, mcp_servers=["proj"])

        assert sum(counts2.values()) == 0


# ── revoke_all_permissions ─────────────────────────────────────────────────────


class TestRevokeAllPermissions:
    def test_setup_then_revoke_removes_mcp_rules(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings_path = tmp_path / ".claude" / "settings.json"
        _write_settings(settings_path, allow=[])
        monkeypatch.setattr("server.lib.perms_helpers._USER_SETTINGS", settings_path)
        monkeypatch.setattr("server.tools.perms_grant._USER_SETTINGS", settings_path)

        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg()
        cfg.tracking_dir = "/tmp/tracking"

        # Setup permissions first
        setup_permissions(
            meta, cfg,
            mcp_servers=["plugin_proj_proj"],
        )
        allow_after_setup = _read_allow(settings_path)
        assert len(allow_after_setup) > 0

        # Revoke all (without mcp_servers -- MCP rules are shared across projects)
        counts = revoke_all_permissions(meta, cfg)
        # MCP rules are NOT removed by default (shared across projects)
        allow_after = _read_allow(settings_path)
        assert "mcp__plugin_proj_proj__*" in allow_after

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

    def test_revoke_no_permissions_returns_zero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings_path = tmp_path / ".claude" / "settings.json"
        _write_settings(settings_path, allow=[])
        monkeypatch.setattr("server.lib.perms_helpers._USER_SETTINGS", settings_path)
        monkeypatch.setattr("server.tools.perms_grant._USER_SETTINGS", settings_path)

        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg()

        counts = revoke_all_permissions(meta, cfg)
        assert sum(counts.values()) == 0
        assert _read_allow(settings_path) == []

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

    def test_revoke_idempotent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings_path = tmp_path / ".claude" / "settings.json"
        _write_settings(settings_path, allow=[])
        monkeypatch.setattr("server.lib.perms_helpers._USER_SETTINGS", settings_path)
        monkeypatch.setattr("server.tools.perms_grant._USER_SETTINGS", settings_path)

        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg()
        cfg.tracking_dir = "/tmp/tracking"

        setup_permissions(meta, cfg)
        revoke_all_permissions(meta, cfg)
        counts2 = revoke_all_permissions(meta, cfg)
        assert sum(counts2.values()) == 0

    def test_revoke_removes_sandbox_write_paths(
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

        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg()
        cfg.tracking_dir = "/tmp/tracking"

        # Setup permissions in sandbox mode
        setup_permissions(meta, cfg)
        aw_before = _read_sandbox_allow_write(local_path)
        assert "/home/user/proj" in aw_before

        # Revoke all
        counts = revoke_all_permissions(meta, cfg)
        assert counts["sandbox_paths"] > 0
        aw_after = _read_sandbox_allow_write(local_path)
        assert "/home/user/proj" not in aw_after
        allow = _read_local_allow(local_path)
        assert len(allow) == 0

    def test_revoke_mixed_repos(
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

        meta = _make_meta(repos=[
            RepoEntry(label="code", path="/home/user/proj"),
            RepoEntry(label="docs", path="/home/user/docs", reference=True),
        ])
        cfg = _make_cfg()
        cfg.tracking_dir = "/tmp/tracking"

        setup_permissions(meta, cfg, mcp_servers=["proj"])

        # Verify setup state
        aw = _read_sandbox_allow_write(local_path)
        assert "/home/user/proj" in aw
        assert "/home/user/docs" not in aw  # reference repo excluded from allowWrite

        counts = revoke_all_permissions(meta, cfg, mcp_servers=["proj"])
        assert counts["sandbox_paths"] > 0
        assert counts["mcp_rules"] == 1

        aw_after = _read_sandbox_allow_write(local_path)
        assert "/home/user/proj" not in aw_after

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
        assert counts == {"sandbox_paths": 0, "mcp_rules": 0}

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


        # Setup permissions
        await call_tool(
            mcp_app_with_grant,
            "proj_setup_permissions",
            mcp_servers=["plugin_proj_proj"],
        )
        allow_before = _read_allow(settings_path)
        assert len(allow_before) > 0

        # Archive the project
        result = await call_tool(mcp_app_with_grant, "proj_archive", name="myproject")
        assert "Archived" in result

        # MCP rules stay because they are shared across projects
        allow_after = _read_allow(settings_path)
        assert "mcp__plugin_proj_proj__*" in allow_after

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
