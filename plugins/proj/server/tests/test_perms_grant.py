"""Tests for proj_grant_tool_permissions / proj_revoke_tool_permissions."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
import yaml

from server.lib import state, storage
from server.lib.models import (
    DEFAULT_INVESTIGATION_TOOLS,
    PermissionsConfig,
    ProjConfig,
    ProjectDates,
    ProjectEntry,
    ProjectMeta,
    RepoEntry,
    TodoistSync,
)
from server.tools.perms_grant import (
    _bash_entry,
    collect_paths,
    grant_investigation_tools,
    revoke_investigation_tools,
    setup_permissions,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_cfg(
    tools: list[str] | None = None,
    worktree_integration: bool = False,
) -> ProjConfig:
    cfg = ProjConfig(tracking_dir="/tmp/tracking", worktree_integration=worktree_integration)
    cfg.permissions = PermissionsConfig(
        auto_grant=True,
        auto_allow_mcps=True,
        investigation_tools=tools if tools is not None else list(DEFAULT_INVESTIGATION_TOOLS),
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


# ── _bash_entry ───────────────────────────────────────────────────────────────


class TestBashEntry:
    def test_produces_double_slash_prefix(self) -> None:
        result = _bash_entry("grep", "/home/user/proj")
        assert result == "Bash(grep //home/user/proj/**)"

    def test_strips_trailing_slash(self) -> None:
        result = _bash_entry("find", "/home/user/proj/")
        assert result == "Bash(find //home/user/proj/**)"

    def test_various_tools(self) -> None:
        for tool in DEFAULT_INVESTIGATION_TOOLS:
            entry = _bash_entry(tool, "/some/path")
            assert entry.startswith(f"Bash({tool} //some/path/**)")


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


# ── grant_investigation_tools ─────────────────────────────────────────────────


class TestGrantInvestigationTools:
    def test_adds_bash_rules_for_all_tools(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings_path = tmp_path / ".claude" / "settings.json"
        _write_settings(settings_path, allow=[])
        monkeypatch.setattr("server.lib.perms_helpers._USER_SETTINGS", settings_path)

        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(tools=["grep", "find", "ls"])
        added = grant_investigation_tools(meta, cfg)

        assert added == 6  # 3 tools × 2 paths (repo + tracking_dir)
        allow = _read_allow(settings_path)
        assert "Bash(grep //home/user/proj/**)" in allow
        assert "Bash(find //home/user/proj/**)" in allow
        assert "Bash(ls //home/user/proj/**)" in allow

    def test_idempotent_no_duplicates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings_path = tmp_path / ".claude" / "settings.json"
        _write_settings(settings_path, allow=[
            "Bash(grep //home/user/proj/**)",
            "Bash(grep //tmp/tracking/**)",
        ])
        monkeypatch.setattr("server.lib.perms_helpers._USER_SETTINGS", settings_path)

        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(tools=["grep"])
        added = grant_investigation_tools(meta, cfg)

        assert added == 0
        allow = _read_allow(settings_path)
        assert allow.count("Bash(grep //home/user/proj/**)") == 1

    def test_multiple_repos_all_get_rules(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings_path = tmp_path / ".claude" / "settings.json"
        _write_settings(settings_path, allow=[])
        monkeypatch.setattr("server.lib.perms_helpers._USER_SETTINGS", settings_path)

        meta = _make_meta(
            repos=[
                RepoEntry(label="a", path="/home/user/proj-a"),
                RepoEntry(label="b", path="/home/user/proj-b"),
            ]
        )
        cfg = _make_cfg(tools=["grep"])
        added = grant_investigation_tools(meta, cfg)

        assert added == 3  # 1 tool × 3 paths (2 repos + tracking_dir)
        allow = _read_allow(settings_path)
        assert "Bash(grep //home/user/proj-a/**)" in allow
        assert "Bash(grep //home/user/proj-b/**)" in allow

    def test_empty_tool_list_adds_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings_path = tmp_path / ".claude" / "settings.json"
        _write_settings(settings_path, allow=[])
        monkeypatch.setattr("server.lib.perms_helpers._USER_SETTINGS", settings_path)

        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(tools=[])
        added = grant_investigation_tools(meta, cfg)

        assert added == 0
        assert _read_allow(settings_path) == []

    def test_creates_settings_file_if_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings_path = tmp_path / ".claude" / "settings.json"
        # Do not create the file
        monkeypatch.setattr("server.lib.perms_helpers._USER_SETTINGS", settings_path)

        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(tools=["grep"])
        added = grant_investigation_tools(meta, cfg)

        assert added == 2  # 1 tool × 2 paths (repo + tracking_dir)
        assert settings_path.exists()
        assert "Bash(grep //home/user/proj/**)" in _read_allow(settings_path)

    def test_existing_unrelated_rules_preserved(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings_path = tmp_path / ".claude" / "settings.json"
        _write_settings(
            settings_path,
            allow=["Read(//home/user/proj/**)", "mcp__proj__*"],
        )
        monkeypatch.setattr("server.lib.perms_helpers._USER_SETTINGS", settings_path)

        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(tools=["grep"])
        grant_investigation_tools(meta, cfg)

        allow = _read_allow(settings_path)
        assert "Read(//home/user/proj/**)" in allow
        assert "mcp__proj__*" in allow
        assert "Bash(grep //home/user/proj/**)" in allow


# ── revoke_investigation_tools ────────────────────────────────────────────────


class TestRevokeInvestigationTools:
    def test_removes_bash_rules(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings_path = tmp_path / ".claude" / "settings.json"
        _write_settings(
            settings_path,
            allow=["Bash(grep //home/user/proj/**)", "Bash(find //home/user/proj/**)"],
        )
        monkeypatch.setattr("server.lib.perms_helpers._USER_SETTINGS", settings_path)

        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(tools=["grep", "find"])
        removed = revoke_investigation_tools(meta, cfg)

        assert removed == 2
        assert _read_allow(settings_path) == []

    def test_does_not_remove_unrelated_rules(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings_path = tmp_path / ".claude" / "settings.json"
        _write_settings(
            settings_path,
            allow=[
                "Read(//home/user/proj/**)",
                "mcp__proj__*",
                "Bash(grep //home/user/proj/**)",
            ],
        )
        monkeypatch.setattr("server.lib.perms_helpers._USER_SETTINGS", settings_path)

        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(tools=["grep"])
        removed = revoke_investigation_tools(meta, cfg)

        assert removed == 1
        allow = _read_allow(settings_path)
        assert "Read(//home/user/proj/**)" in allow
        assert "mcp__proj__*" in allow
        assert "Bash(grep //home/user/proj/**)" not in allow

    def test_no_rules_to_remove_returns_zero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings_path = tmp_path / ".claude" / "settings.json"
        _write_settings(settings_path, allow=["Read(//home/user/proj/**)"])
        monkeypatch.setattr("server.lib.perms_helpers._USER_SETTINGS", settings_path)

        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(tools=["grep"])
        removed = revoke_investigation_tools(meta, cfg)

        assert removed == 0

    def test_grant_then_revoke_restores_original(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings_path = tmp_path / ".claude" / "settings.json"
        original = ["Read(//home/user/proj/**)", "mcp__proj__*"]
        _write_settings(settings_path, allow=original)
        monkeypatch.setattr("server.lib.perms_helpers._USER_SETTINGS", settings_path)

        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(tools=["grep", "ls"])

        grant_investigation_tools(meta, cfg)
        revoke_investigation_tools(meta, cfg)

        assert sorted(_read_allow(settings_path)) == sorted(original)


# ── setup_permissions ─────────────────────────────────────────────────────────


class TestSetupPermissions:
    def test_adds_path_rules(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        settings_path = tmp_path / ".claude" / "settings.json"
        _write_settings(settings_path, allow=[])
        monkeypatch.setattr("server.lib.perms_helpers._USER_SETTINGS", settings_path)

        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(tools=[])
        cfg.tracking_dir = "/tmp/tracking"
        counts = setup_permissions(meta, cfg, grant_path_access=True, grant_investigation_tools_flag=False)

        allow = _read_allow(settings_path)
        assert "Read(//home/user/proj/**)" in allow
        assert "Edit(//home/user/proj/**)" in allow
        assert counts["path_rules"] >= 2

    def test_adds_bash_rules(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        settings_path = tmp_path / ".claude" / "settings.json"
        _write_settings(settings_path, allow=[])
        monkeypatch.setattr("server.lib.perms_helpers._USER_SETTINGS", settings_path)

        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(tools=["grep", "find"])
        counts = setup_permissions(meta, cfg, grant_path_access=False, grant_investigation_tools_flag=True)

        allow = _read_allow(settings_path)
        assert "Bash(grep //home/user/proj/**)" in allow
        assert "Bash(find //home/user/proj/**)" in allow
        assert counts["bash_rules"] == 4  # 2 tools × 2 paths (repo + tracking_dir)

    def test_adds_mcp_rules(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        settings_path = tmp_path / ".claude" / "settings.json"
        _write_settings(settings_path, allow=[])
        monkeypatch.setattr("server.lib.perms_helpers._USER_SETTINGS", settings_path)

        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(tools=[])
        counts = setup_permissions(
            meta, cfg,
            grant_path_access=False,
            grant_investigation_tools_flag=False,
            mcp_servers=["plugin_proj_proj", "plugin_perms_perms"],
        )

        allow = _read_allow(settings_path)
        assert "mcp__plugin_proj_proj__*" in allow
        assert "mcp__plugin_perms_perms__*" in allow
        assert counts["mcp_rules"] == 2

    def test_all_rules_in_one_write(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        settings_path = tmp_path / ".claude" / "settings.json"
        _write_settings(settings_path, allow=[])
        monkeypatch.setattr("server.lib.perms_helpers._USER_SETTINGS", settings_path)

        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(tools=["grep"])
        counts = setup_permissions(
            meta, cfg,
            grant_path_access=True,
            grant_investigation_tools_flag=True,
            mcp_servers=["plugin_proj_proj"],
        )

        allow = _read_allow(settings_path)
        assert "Read(//home/user/proj/**)" in allow
        assert "Edit(//home/user/proj/**)" in allow
        assert "Bash(grep //home/user/proj/**)" in allow
        assert "mcp__plugin_proj_proj__*" in allow
        assert sum(counts.values()) > 0

    def test_idempotent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        settings_path = tmp_path / ".claude" / "settings.json"
        _write_settings(settings_path, allow=[])
        monkeypatch.setattr("server.lib.perms_helpers._USER_SETTINGS", settings_path)

        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(tools=["grep"])
        setup_permissions(meta, cfg, grant_path_access=True, grant_investigation_tools_flag=True, mcp_servers=["proj"])
        counts2 = setup_permissions(meta, cfg, grant_path_access=True, grant_investigation_tools_flag=True, mcp_servers=["proj"])

        assert sum(counts2.values()) == 0

    def test_archive_destination_adds_bash_rules(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        settings_path = tmp_path / ".claude" / "settings.json"
        _write_settings(settings_path, allow=[])
        monkeypatch.setattr("server.lib.perms_helpers._USER_SETTINGS", settings_path)

        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(tools=[])
        cfg.tracking_dir = "/tmp/tracking"
        counts = setup_permissions(
            meta, cfg,
            grant_path_access=False,
            grant_investigation_tools_flag=False,
            archive_destination="/tmp/arch",
        )

        allow = _read_allow(settings_path)
        # mv/rm/rm -rf/mkdir/mkdir -p rules for archive dest, repo path, and tracking dir
        assert any("Bash(mv " in e for e in allow)
        assert any("Bash(rm " in e for e in allow)
        assert any("Bash(mkdir " in e for e in allow)
        # Read+Edit for archive dest
        assert any("Read(" in e and "arch" in e for e in allow)
        assert any("Edit(" in e and "arch" in e for e in allow)
        assert counts["bash_rules"] > 0
        assert counts["path_rules"] > 0

    def test_no_flags_adds_nothing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        settings_path = tmp_path / ".claude" / "settings.json"
        _write_settings(settings_path, allow=[])
        monkeypatch.setattr("server.lib.perms_helpers._USER_SETTINGS", settings_path)

        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(tools=["grep"])
        counts = setup_permissions(meta, cfg, grant_path_access=False, grant_investigation_tools_flag=False, mcp_servers=[])

        assert sum(counts.values()) == 0
        assert _read_allow(settings_path) == []


# ── MCP tool integration ──────────────────────────────────────────────────────


class TestProjGrantToolPermissionsTool:
    @pytest.mark.anyio
    async def test_tool_registered(self, mcp_app_with_grant) -> None:  # type: ignore[no-untyped-def]
        from tests.conftest import call_tool

        result = await call_tool(mcp_app_with_grant, "proj_grant_tool_permissions")
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.anyio
    async def test_no_active_project(self, cfg: ProjConfig, mcp_app_with_grant) -> None:  # type: ignore[no-untyped-def]
        from tests.conftest import call_tool

        result = await call_tool(mcp_app_with_grant, "proj_grant_tool_permissions")
        assert "No active project" in result

    @pytest.mark.anyio
    async def test_grants_rules_for_active_project(
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

        result = await call_tool(mcp_app_with_grant, "proj_grant_tool_permissions")
        assert "✅" in result
        allow = _read_allow(settings_path)
        assert any(e.startswith("Bash(grep ") for e in allow)

    @pytest.mark.anyio
    async def test_revoke_tool_registered(self, mcp_app_with_grant) -> None:  # type: ignore[no-untyped-def]
        from tests.conftest import call_tool

        result = await call_tool(mcp_app_with_grant, "proj_revoke_tool_permissions")
        assert isinstance(result, str)

    @pytest.mark.anyio
    async def test_setup_permissions_tool_registered(self, mcp_app_with_grant) -> None:  # type: ignore[no-untyped-def]
        from tests.conftest import call_tool

        result = await call_tool(mcp_app_with_grant, "proj_setup_permissions")
        assert isinstance(result, str)

    @pytest.mark.anyio
    async def test_setup_permissions_adds_all_rules(
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
            grant_path_access=True,
            grant_investigation_tools=True,
            mcp_servers=["plugin_proj_proj"],
        )
        assert "✅" in result
        allow = _read_allow(settings_path)
        assert any("Read(" in e for e in allow)
        assert any("Bash(" in e for e in allow)
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


class TestGrantInvestigationToolsSandbox:
    def test_writes_to_local_settings_when_sandbox_enabled(
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
        cfg = _make_cfg(tools=["grep"])
        added = grant_investigation_tools(meta, cfg)

        assert added == 2  # 1 tool × 2 paths (repo + tracking_dir)
        allow = _read_local_allow(local_path)
        assert "Bash(grep //home/user/proj/**)" in allow
        # Standard settings.json must NOT be created
        assert not (tmp_path / "settings.json").exists()


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
        cfg = _make_cfg(tools=[])
        cfg.tracking_dir = "/tmp/tracking"
        counts = setup_permissions(
            meta, cfg,
            grant_path_access=True,
            grant_investigation_tools_flag=False,
        )

        # Path rules include Read+Edit in permissions.allow AND sandbox.filesystem.allowWrite
        allow = _read_local_allow(local_path)
        assert "Read(//home/user/proj/**)" in allow
        assert "Edit(//home/user/proj/**)" in allow
        aw = _read_sandbox_allow_write(local_path)
        assert "/home/user/proj" in aw
        assert counts["path_rules"] > 0

    def test_reference_repo_not_in_sandbox_allow_write(
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
        cfg = _make_cfg(tools=[])
        cfg.tracking_dir = ""
        setup_permissions(meta, cfg, grant_path_access=True, grant_investigation_tools_flag=False)

        aw = _read_sandbox_allow_write(local_path)
        assert "/home/user/docs" not in aw
        # Read rule should still be in permissions.allow
        allow = _read_local_allow(local_path)
        assert "Read(//home/user/docs/**)" in allow

    def test_all_rules_sandbox(
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
        cfg = _make_cfg(tools=["grep"])
        counts = setup_permissions(
            meta, cfg,
            grant_path_access=True,
            grant_investigation_tools_flag=True,
            mcp_servers=["plugin_proj_proj"],
        )

        allow = _read_local_allow(local_path)
        assert "Bash(grep //home/user/proj/**)" in allow
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
        cfg = _make_cfg(tools=["grep"])
        setup_permissions(meta, cfg, grant_path_access=True, grant_investigation_tools_flag=True, mcp_servers=["proj"])
        counts2 = setup_permissions(meta, cfg, grant_path_access=True, grant_investigation_tools_flag=True, mcp_servers=["proj"])

        assert sum(counts2.values()) == 0


class TestRevokeInvestigationToolsSandbox:
    def test_revokes_from_local_settings(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        local_path = tmp_path / ".claude" / "settings.local.json"
        _write_local_settings(local_path, {
            "sandbox": {"enabled": True},
            "permissions": {"allow": ["Bash(grep //home/user/proj/**)"]},
        })
        monkeypatch.setattr("server.lib.perms_helpers._USER_LOCAL_SETTINGS", local_path)
        monkeypatch.setattr("server.lib.perms_helpers._USER_SETTINGS", tmp_path / "settings.json")

        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(tools=["grep"])
        removed = revoke_investigation_tools(meta, cfg)

        assert removed == 1
        allow = _read_local_allow(local_path)
        assert "Bash(grep //home/user/proj/**)" not in allow


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
