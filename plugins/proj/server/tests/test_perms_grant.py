"""Tests for proj_setup_permissions / proj_revoke_all_permissions."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
import yaml

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
    _ALWAYS_ALLOWED_TOOLS,
    _SENSITIVE_DENY_RULES,
    _add_sandbox_deny_write_path,
    _add_sensitive_deny_rules,
    _remove_sandbox_deny_write_path,
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


def _read_deny(path: Path) -> list[str]:
    data = json.loads(path.read_text())
    return data.get("permissions", {}).get("deny", [])


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

    def test_worktree_paths_added_when_enabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wt_config = tmp_path / "worktree.yaml"
        wt_config.write_text(
            yaml.dump({
                "version": 1,
                "base_repos": [
                    {"label": "extra", "path": "/home/user/extra-repo", "default_branch": "main"},
                ],
            })
        )
        monkeypatch.setattr("server.tools.perms_grant._WORKTREE_CONFIG", wt_config)

        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(worktree_integration=True)
        paths = collect_paths(meta, cfg)
        assert "/home/user/proj" in paths
        assert "/home/user/extra-repo" in paths

    def test_no_duplicates_when_repo_in_worktree_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wt_config = tmp_path / "worktree.yaml"
        wt_config.write_text(
            yaml.dump({
                "base_repos": [
                    {"label": "same", "path": "/home/user/proj", "default_branch": "main"},
                ],
            })
        )
        monkeypatch.setattr("server.tools.perms_grant._WORKTREE_CONFIG", wt_config)

        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(worktree_integration=True)
        paths = collect_paths(meta, cfg)
        assert paths.count("/home/user/proj") == 1

    def test_missing_worktree_config_is_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "server.tools.perms_grant._WORKTREE_CONFIG",
            tmp_path / "nonexistent.yaml",
        )
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

        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg()
        setup_permissions(meta, cfg, mcp_servers=["proj"])
        counts2 = setup_permissions(meta, cfg, mcp_servers=["proj"])

        assert sum(counts2.values()) == 0

    def test_adds_builtin_tools(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        settings_path = tmp_path / ".claude" / "settings.json"
        _write_settings(settings_path, allow=[])
        monkeypatch.setattr("server.lib.perms_helpers._USER_SETTINGS", settings_path)

        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg()
        counts = setup_permissions(meta, cfg, mcp_servers=[])

        allow = _read_allow(settings_path)
        assert "Search" in allow
        assert counts["builtin_rules"] == 1

    def test_builtin_tools_idempotent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        settings_path = tmp_path / ".claude" / "settings.json"
        _write_settings(settings_path, allow=["Search"])
        monkeypatch.setattr("server.lib.perms_helpers._USER_SETTINGS", settings_path)

        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg()
        counts = setup_permissions(meta, cfg, mcp_servers=[])

        assert counts["builtin_rules"] == 0
        allow = _read_allow(settings_path)
        assert allow.count("Search") == 1

    def test_builtin_tools_constant(self) -> None:
        assert "Search" in _ALWAYS_ALLOWED_TOOLS

    def test_sensitive_deny_rules_always_added(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        settings_path = tmp_path / ".claude" / "settings.json"
        _write_settings(settings_path, allow=[])
        monkeypatch.setattr("server.lib.perms_helpers._USER_SETTINGS", settings_path)

        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg()
        counts = setup_permissions(meta, cfg, mcp_servers=[])

        # Sensitive deny rules are always added regardless of other flags
        assert counts["sensitive_deny_rules"] == 3
        assert counts["sandbox_paths"] == 0
        assert counts["mcp_rules"] == 0
        assert counts["builtin_rules"] == 1
        allow = _read_allow(settings_path)
        assert allow == ["Search"]
        data = json.loads(settings_path.read_text())
        deny = data.get("permissions", {}).get("deny", [])
        assert "Read(~/.ssh/**)" in deny
        assert "Read(~/.gnupg/**)" in deny
        assert "Read(~/.aws/**)" in deny


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


def _read_sandbox_deny_write(path: Path) -> list[str]:
    data = json.loads(path.read_text())
    return data.get("sandbox", {}).get("filesystem", {}).get("denyWrite", [])


# ── sandbox deny_write helpers ────────────────────────────────────────────────


class TestSandboxDenyWriteHelpers:
    def test_add_deny_write_path(self) -> None:
        data: dict[str, object] = {}
        assert _add_sandbox_deny_write_path(data, "/home/user/docs") is True
        dw = data["sandbox"]["filesystem"]["denyWrite"]  # type: ignore[index]
        assert "/home/user/docs" in dw

    def test_add_deny_write_path_idempotent(self) -> None:
        data: dict[str, object] = {}
        _add_sandbox_deny_write_path(data, "/home/user/docs")
        assert _add_sandbox_deny_write_path(data, "/home/user/docs") is False
        dw = data["sandbox"]["filesystem"]["denyWrite"]  # type: ignore[index]
        assert dw.count("/home/user/docs") == 1

    def test_remove_deny_write_path(self) -> None:
        data: dict[str, object] = {}
        _add_sandbox_deny_write_path(data, "/home/user/docs")
        assert _remove_sandbox_deny_write_path(data, "/home/user/docs") is True
        dw = data["sandbox"]["filesystem"]["denyWrite"]  # type: ignore[index]
        assert "/home/user/docs" not in dw

    def test_remove_deny_write_path_missing(self) -> None:
        data: dict[str, object] = {}
        assert _remove_sandbox_deny_write_path(data, "/home/user/docs") is False

    def test_strips_trailing_slash(self) -> None:
        data: dict[str, object] = {}
        _add_sandbox_deny_write_path(data, "/home/user/docs/")
        dw = data["sandbox"]["filesystem"]["denyWrite"]  # type: ignore[index]
        assert "/home/user/docs" in dw


# ── sensitive deny rules ──────────────────────────────────────────────────────


class TestSensitiveDenyRules:
    def test_adds_all_three_rules(self) -> None:
        data: dict[str, object] = {}
        count = _add_sensitive_deny_rules(data)
        assert count == 3
        deny = data["permissions"]["deny"]  # type: ignore[index]
        assert "Read(~/.ssh/**)" in deny
        assert "Read(~/.gnupg/**)" in deny
        assert "Read(~/.aws/**)" in deny

    def test_idempotent(self) -> None:
        data: dict[str, object] = {}
        _add_sensitive_deny_rules(data)
        count = _add_sensitive_deny_rules(data)
        assert count == 0
        deny = data["permissions"]["deny"]  # type: ignore[index]
        assert len(deny) == 3

    def test_preserves_existing_deny_rules(self) -> None:
        data: dict[str, object] = {"permissions": {"deny": ["Write(~/.bashrc)"]}}
        _add_sensitive_deny_rules(data)
        deny = data["permissions"]["deny"]  # type: ignore[index]
        assert "Write(~/.bashrc)" in deny
        assert "Read(~/.ssh/**)" in deny
        assert len(deny) == 4

    def test_constant_has_expected_rules(self) -> None:
        assert len(_SENSITIVE_DENY_RULES) == 3
        assert "Read(~/.ssh/**)" in _SENSITIVE_DENY_RULES
        assert "Read(~/.gnupg/**)" in _SENSITIVE_DENY_RULES
        assert "Read(~/.aws/**)" in _SENSITIVE_DENY_RULES


class TestSandboxModeDetection:
    def test_is_sandbox_enabled_true(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from server.lib.perms_helpers import is_sandbox_enabled as _is_sandbox_enabled

        local_path = tmp_path / ".claude" / "settings.local.json"
        _write_local_settings(local_path, {"sandbox": {"enabled": True}})
        monkeypatch.setattr("server.lib.perms_helpers._USER_LOCAL_SETTINGS", local_path)
        assert _is_sandbox_enabled() is True

    def test_is_sandbox_enabled_false_when_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from server.lib.perms_helpers import is_sandbox_enabled as _is_sandbox_enabled

        monkeypatch.setattr(
            "server.lib.perms_helpers._USER_LOCAL_SETTINGS",
            tmp_path / "nonexistent.json",
        )
        assert _is_sandbox_enabled() is False

    def test_is_sandbox_enabled_false_when_disabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from server.lib.perms_helpers import is_sandbox_enabled as _is_sandbox_enabled

        local_path = tmp_path / ".claude" / "settings.local.json"
        _write_local_settings(local_path, {"sandbox": {"enabled": False}})
        monkeypatch.setattr("server.lib.perms_helpers._USER_LOCAL_SETTINGS", local_path)
        assert _is_sandbox_enabled() is False

    def test_is_sandbox_enabled_project_level_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sandbox enabled at project level but not user level is detected."""
        from server.lib.perms_helpers import is_sandbox_enabled as _is_sandbox_enabled

        # User-level has no sandbox
        monkeypatch.setattr(
            "server.lib.perms_helpers._USER_LOCAL_SETTINGS",
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
        from server.lib.perms_helpers import is_sandbox_enabled as _is_sandbox_enabled

        user_local = tmp_path / "user" / ".claude" / "settings.local.json"
        _write_local_settings(user_local, {"sandbox": {"enabled": False}})
        monkeypatch.setattr("server.lib.perms_helpers._USER_LOCAL_SETTINGS", user_local)

        project_dir = tmp_path / "myproject"
        proj_local = project_dir / ".claude" / "settings.local.json"
        _write_local_settings(proj_local, {"sandbox": {"enabled": True}})

        assert _is_sandbox_enabled(project_dir) is True

    def test_is_sandbox_enabled_both_false(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When both user-level and project-level sandbox are disabled, returns False."""
        from server.lib.perms_helpers import is_sandbox_enabled as _is_sandbox_enabled

        user_local = tmp_path / "user" / ".claude" / "settings.local.json"
        _write_local_settings(user_local, {"sandbox": {"enabled": False}})
        monkeypatch.setattr("server.lib.perms_helpers._USER_LOCAL_SETTINGS", user_local)

        project_dir = tmp_path / "myproject"
        proj_local = project_dir / ".claude" / "settings.local.json"
        _write_local_settings(proj_local, {"sandbox": {"enabled": False}})

        assert _is_sandbox_enabled(project_dir) is False

    def test_is_sandbox_enabled_no_project_dir_only_checks_user(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When project_dir is None, only user-level is checked (backward compat)."""
        from server.lib.perms_helpers import is_sandbox_enabled as _is_sandbox_enabled

        monkeypatch.setattr(
            "server.lib.perms_helpers._USER_LOCAL_SETTINGS",
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
        monkeypatch.setattr("server.lib.perms_helpers._USER_SETTINGS", tmp_path / "settings.json")

        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg()
        cfg.tracking_dir = "/tmp/tracking"
        counts = setup_permissions(meta, cfg)

        aw = _read_sandbox_allow_write(local_path)
        assert "/home/user/proj" in aw
        assert counts["sandbox_paths"] > 0

    def test_reference_repo_in_deny_write_not_allow_write(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        local_path = tmp_path / ".claude" / "settings.local.json"
        _write_local_settings(local_path, {
            "sandbox": {"enabled": True},
            "permissions": {"allow": []},
        })
        monkeypatch.setattr("server.lib.perms_helpers._USER_LOCAL_SETTINGS", local_path)
        monkeypatch.setattr("server.lib.perms_helpers._USER_SETTINGS", tmp_path / "settings.json")

        meta = _make_meta(repos=[RepoEntry(label="docs", path="/home/user/docs", reference=True)])
        cfg = _make_cfg()
        cfg.tracking_dir = ""
        counts = setup_permissions(meta, cfg)

        aw = _read_sandbox_allow_write(local_path)
        assert "/home/user/docs" not in aw
        dw = _read_sandbox_deny_write(local_path)
        assert "/home/user/docs" in dw
        assert counts["deny_write_paths"] == 1
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
        monkeypatch.setattr("server.lib.perms_helpers._USER_SETTINGS", tmp_path / "settings.json")

        meta = _make_meta(repos=[
            RepoEntry(label="code", path="/home/user/proj"),
            RepoEntry(label="docs", path="/home/user/docs", reference=True),
        ])
        cfg = _make_cfg()
        cfg.tracking_dir = "/tmp/tracking"
        counts = setup_permissions(meta, cfg, mcp_servers=["plugin_proj_proj"])

        aw = _read_sandbox_allow_write(local_path)
        dw = _read_sandbox_deny_write(local_path)
        assert "/home/user/proj" in aw
        assert "/home/user/docs" not in aw
        assert "/home/user/docs" in dw
        assert "/home/user/proj" not in dw
        assert counts["sandbox_paths"] >= 1  # proj + tracking
        assert counts["deny_write_paths"] == 1  # docs

    def test_sensitive_deny_rules_in_sandbox_mode(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        local_path = tmp_path / ".claude" / "settings.local.json"
        _write_local_settings(local_path, {
            "sandbox": {"enabled": True},
            "permissions": {"allow": []},
        })
        monkeypatch.setattr("server.lib.perms_helpers._USER_LOCAL_SETTINGS", local_path)
        monkeypatch.setattr("server.lib.perms_helpers._USER_SETTINGS", tmp_path / "settings.json")

        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg()
        counts = setup_permissions(meta, cfg)

        assert counts["sensitive_deny_rules"] == 3
        data = json.loads(local_path.read_text())
        deny = data.get("permissions", {}).get("deny", [])
        assert "Read(~/.ssh/**)" in deny
        assert "Read(~/.gnupg/**)" in deny
        assert "Read(~/.aws/**)" in deny

    def test_mcp_rules_and_sandbox_paths(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        local_path = tmp_path / ".claude" / "settings.local.json"
        _write_local_settings(local_path, {
            "sandbox": {"enabled": True},
            "permissions": {"allow": []},
        })
        monkeypatch.setattr("server.lib.perms_helpers._USER_LOCAL_SETTINGS", local_path)
        monkeypatch.setattr("server.lib.perms_helpers._USER_SETTINGS", tmp_path / "settings.json")

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
        monkeypatch.setattr("server.lib.perms_helpers._USER_SETTINGS", tmp_path / "settings.json")

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
        allow = _read_allow(settings_path)
        assert "mcp__plugin_proj_proj__*" not in allow
        assert "Search" in allow  # Built-in tools are never revoked

    def test_revoke_no_permissions_returns_zero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings_path = tmp_path / ".claude" / "settings.json"
        _write_settings(settings_path, allow=[])
        monkeypatch.setattr("server.lib.perms_helpers._USER_SETTINGS", settings_path)

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
        monkeypatch.setattr("server.lib.perms_helpers._USER_SETTINGS", tmp_path / "settings.json")

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
        assert allow == ["Search"]  # Built-in tools are never revoked

    def test_revoke_removes_deny_write_paths_for_reference_repos(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        local_path = tmp_path / ".claude" / "settings.local.json"
        _write_local_settings(local_path, {
            "sandbox": {"enabled": True},
            "permissions": {"allow": []},
        })
        monkeypatch.setattr("server.lib.perms_helpers._USER_LOCAL_SETTINGS", local_path)
        monkeypatch.setattr("server.lib.perms_helpers._USER_SETTINGS", tmp_path / "settings.json")

        meta = _make_meta(repos=[
            RepoEntry(label="code", path="/home/user/proj"),
            RepoEntry(label="docs", path="/home/user/docs", reference=True),
        ])
        cfg = _make_cfg()
        cfg.tracking_dir = "/tmp/tracking"

        setup_permissions(meta, cfg)
        dw_before = _read_sandbox_deny_write(local_path)
        assert "/home/user/docs" in dw_before

        counts = revoke_all_permissions(meta, cfg)
        assert counts["deny_write_paths"] == 1
        dw_after = _read_sandbox_deny_write(local_path)
        assert "/home/user/docs" not in dw_after

    def test_revoke_preserves_sensitive_deny_rules(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sensitive path deny rules are global safety and NOT removed on revoke."""
        settings_path = tmp_path / ".claude" / "settings.json"
        _write_settings(settings_path, allow=[])
        monkeypatch.setattr("server.lib.perms_helpers._USER_SETTINGS", settings_path)

        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg()

        setup_permissions(meta, cfg, mcp_servers=["proj"])
        deny_before = _read_deny(settings_path)
        assert "Read(~/.ssh/**)" in deny_before

        revoke_all_permissions(meta, cfg, mcp_servers=["proj"])
        deny_after = _read_deny(settings_path)
        # Sensitive deny rules must survive revocation
        assert "Read(~/.ssh/**)" in deny_after
        assert "Read(~/.gnupg/**)" in deny_after
        assert "Read(~/.aws/**)" in deny_after

    def test_revoke_mixed_repos(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        local_path = tmp_path / ".claude" / "settings.local.json"
        _write_local_settings(local_path, {
            "sandbox": {"enabled": True},
            "permissions": {"allow": []},
        })
        monkeypatch.setattr("server.lib.perms_helpers._USER_LOCAL_SETTINGS", local_path)
        monkeypatch.setattr("server.lib.perms_helpers._USER_SETTINGS", tmp_path / "settings.json")

        meta = _make_meta(repos=[
            RepoEntry(label="code", path="/home/user/proj"),
            RepoEntry(label="docs", path="/home/user/docs", reference=True),
        ])
        cfg = _make_cfg()
        cfg.tracking_dir = "/tmp/tracking"

        setup_permissions(meta, cfg, mcp_servers=["proj"])

        # Verify setup state
        aw = _read_sandbox_allow_write(local_path)
        dw = _read_sandbox_deny_write(local_path)
        assert "/home/user/proj" in aw
        assert "/home/user/docs" in dw

        counts = revoke_all_permissions(meta, cfg, mcp_servers=["proj"])
        assert counts["sandbox_paths"] > 0
        assert counts["deny_write_paths"] == 1
        assert counts["mcp_rules"] == 1

        aw_after = _read_sandbox_allow_write(local_path)
        dw_after = _read_sandbox_deny_write(local_path)
        assert "/home/user/proj" not in aw_after
        assert "/home/user/docs" not in dw_after


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
