"""Tests for server.tools.settings functions."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.lib import storage
from server.lib.storage import mcp_allow_entry
from server.tools.settings import add_allow, add_mcp_allow, batch_add_mcp_allow, check_allow, list_allow, remove_allow, remove_mcp_allow


def _write_settings(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def _read_allow(path: Path) -> list[str]:
    data: dict[str, object] = json.loads(path.read_text())
    perms = data.get("permissions", {})
    assert isinstance(perms, dict)
    allow = perms.get("allow", [])
    assert isinstance(allow, list)
    return allow  # type: ignore[return-value]


@pytest.fixture()
def user_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / ".claude" / "settings.json"
    monkeypatch.setattr(storage, "_USER_SETTINGS", path)
    return path


class TestAddAllow:
    def test_adds_rules_to_new_file(self, user_settings: Path) -> None:
        result = add_allow("/home/user/proj", scope="user")
        assert "Added 2" in result
        allow = _read_allow(user_settings)
        assert "Read(//home/user/proj/**)" in allow
        assert "Edit(//home/user/proj/**)" in allow

    def test_idempotent(self, user_settings: Path) -> None:
        add_allow("/home/user/proj", scope="user")
        result = add_allow("/home/user/proj", scope="user")
        assert "already present" in result
        # No duplicates
        assert _read_allow(user_settings).count("Read(//home/user/proj/**)") == 1

    def test_expands_tilde(self, user_settings: Path) -> None:
        result = add_allow("~/testdir", scope="user")
        assert "Added" in result
        allow = _read_allow(user_settings)
        # Should be expanded to absolute path
        assert any("testdir" in e for e in allow)

    def test_preserves_existing_rules(self, user_settings: Path) -> None:
        _write_settings(
            user_settings,
            {"model": "sonnet", "permissions": {"allow": ["Read(//other/**)"]}},
        )
        add_allow("/home/user/proj", scope="user")
        allow = _read_allow(user_settings)
        assert "Read(//other/**)" in allow
        assert "Read(//home/user/proj/**)" in allow

    def test_preserves_other_settings_keys(self, user_settings: Path, tmp_path: Path) -> None:
        _write_settings(user_settings, {"model": "sonnet"})
        add_allow(str(tmp_path / "proj"), scope="user")
        data: dict[str, object] = json.loads(user_settings.read_text())
        assert data["model"] == "sonnet"


class TestRemoveAllow:
    def test_removes_existing_rules(self, user_settings: Path) -> None:
        _write_settings(
            user_settings,
            {
                "permissions": {
                    "allow": ["Read(//home/user/proj/**)", "Edit(//home/user/proj/**)"]
                },
            },
        )
        result = remove_allow("/home/user/proj", scope="user")
        assert "Removed 2" in result
        assert _read_allow(user_settings) == []

    def test_no_match_is_idempotent(self, user_settings: Path) -> None:
        result = remove_allow("/nonexistent/path", scope="user")
        assert "No matching" in result

    def test_only_removes_matching(self, user_settings: Path) -> None:
        _write_settings(
            user_settings,
            {
                "permissions": {
                    "allow": [
                        "Read(//home/user/proj/**)",
                        "Edit(//home/user/proj/**)",
                        "Read(//other/**)",
                    ]
                },
            },
        )
        remove_allow("/home/user/proj", scope="user")
        allow = _read_allow(user_settings)
        assert "Read(//other/**)" in allow
        assert "Read(//home/user/proj/**)" not in allow


class TestListAllow:
    def test_shows_rules(self, user_settings: Path) -> None:
        _write_settings(user_settings, {"permissions": {"allow": ["Read(//foo/**)"]}})
        result = list_allow("user")
        assert "Read(//foo/**)" in result

    def test_empty(self, user_settings: Path) -> None:
        result = list_allow("user")
        assert "not found" in result or "no allow rules" in result


class TestCheckAllow:
    def test_missing(self, user_settings: Path) -> None:
        result = check_allow("/home/user/proj", scope="user")
        assert "MISSING" in result

    def test_present(self, user_settings: Path) -> None:
        _write_settings(
            user_settings,
            {
                "permissions": {
                    "allow": ["Read(//home/user/proj/**)", "Edit(//home/user/proj/**)"]
                },
            },
        )
        result = check_allow("/home/user/proj", scope="user")
        assert "OK" in result

    def test_partial(self, user_settings: Path) -> None:
        _write_settings(
            user_settings,
            {
                "permissions": {"allow": ["Read(//home/user/proj/**)"]},
            },
        )
        result = check_allow("/home/user/proj", scope="user")
        assert "PARTIAL" in result


class TestMcpAllow:
    def test_mcp_allow_entry_format(self) -> None:
        assert mcp_allow_entry("proj") == "mcp__proj__*"
        assert mcp_allow_entry("perms") == "mcp__perms__*"
        assert mcp_allow_entry("claude_ai_Todoist") == "mcp__claude_ai_Todoist__*"

    def test_mcp_allow_entry_rejects_empty(self) -> None:
        import pytest as _pytest
        with _pytest.raises(ValueError):
            mcp_allow_entry("")

    def test_add_mcp_allow_writes_rule(self, user_settings: Path) -> None:
        result = add_mcp_allow("proj", scope="user")
        assert "mcp__proj__*" in result
        allow = _read_allow(user_settings)
        assert "mcp__proj__*" in allow

    def test_add_mcp_allow_idempotent(self, user_settings: Path) -> None:
        add_mcp_allow("proj", scope="user")
        result = add_mcp_allow("proj", scope="user")
        assert "already present" in result
        assert _read_allow(user_settings).count("mcp__proj__*") == 1

    def test_add_mcp_allow_multiple_servers(self, user_settings: Path) -> None:
        for server in ("proj", "perms", "worktree"):
            add_mcp_allow(server, scope="user")
        allow = _read_allow(user_settings)
        assert "mcp__proj__*" in allow
        assert "mcp__perms__*" in allow
        assert "mcp__worktree__*" in allow

    def test_remove_mcp_allow(self, user_settings: Path) -> None:
        add_mcp_allow("proj", scope="user")
        result = remove_mcp_allow("proj", scope="user")
        assert "Removed" in result
        assert "mcp__proj__*" not in _read_allow(user_settings)

    def test_remove_mcp_allow_not_found(self, user_settings: Path) -> None:
        result = remove_mcp_allow("proj", scope="user")
        assert "not found" in result

    def test_mcp_allow_coexists_with_path_rules(self, user_settings: Path) -> None:
        add_allow("/home/user/proj", scope="user")
        add_mcp_allow("proj", scope="user")
        allow = _read_allow(user_settings)
        assert "Read(//home/user/proj/**)" in allow
        assert "mcp__proj__*" in allow

    def test_mcp_allow_entry_format_plugin_namespaced(self) -> None:
        # Claude Code namespaces plugin MCP servers as plugin_<plugin>_<server>.
        # init-plugin and init skills must pass these namespaced names.
        assert mcp_allow_entry("plugin_proj_proj") == "mcp__plugin_proj_proj__*"
        assert mcp_allow_entry("plugin_perms_perms") == "mcp__plugin_perms_perms__*"
        assert mcp_allow_entry("plugin_worktree_worktree") == "mcp__plugin_worktree_worktree__*"

    def test_add_mcp_allow_plugin_namespaced_servers(self, user_settings: Path) -> None:
        # Regression: settings.json must use namespaced names or Claude Code still prompts.
        for server in ("plugin_proj_proj", "plugin_perms_perms", "plugin_worktree_worktree"):
            add_mcp_allow(server, scope="user")
        allow = _read_allow(user_settings)
        assert "mcp__plugin_proj_proj__*" in allow
        assert "mcp__plugin_perms_perms__*" in allow
        assert "mcp__plugin_worktree_worktree__*" in allow
        # Short names must NOT be present — they would not match the actual tool names.
        assert "mcp__proj__*" not in allow
        assert "mcp__perms__*" not in allow
        assert "mcp__worktree__*" not in allow


class TestBatchAddMcpAllow:
    def test_adds_all_servers_in_one_write(self, user_settings: Path) -> None:
        result = batch_add_mcp_allow(["proj", "perms", "worktree"], scope="user")
        assert "Added 3" in result
        allow = _read_allow(user_settings)
        assert "mcp__proj__*" in allow
        assert "mcp__perms__*" in allow
        assert "mcp__worktree__*" in allow

    def test_idempotent_skips_existing(self, user_settings: Path) -> None:
        batch_add_mcp_allow(["proj", "perms"], scope="user")
        result = batch_add_mcp_allow(["proj", "perms"], scope="user")
        assert "already present" in result
        allow = _read_allow(user_settings)
        assert allow.count("mcp__proj__*") == 1
        assert allow.count("mcp__perms__*") == 1

    def test_partial_overlap_adds_only_new(self, user_settings: Path) -> None:
        batch_add_mcp_allow(["proj"], scope="user")
        result = batch_add_mcp_allow(["proj", "perms"], scope="user")
        assert "Added 1" in result
        assert "Skipped 1" in result
        allow = _read_allow(user_settings)
        assert allow.count("mcp__proj__*") == 1
        assert "mcp__perms__*" in allow

    def test_empty_list_returns_nothing_to_do(self, user_settings: Path) -> None:
        result = batch_add_mcp_allow([], scope="user")
        assert "nothing" in result.lower()
        # File should not be created
        assert not user_settings.exists()

    def test_preserves_existing_non_mcp_rules(self, user_settings: Path) -> None:
        _write_settings(user_settings, {"permissions": {"allow": ["Read(//home/user/proj/**)"]}})
        batch_add_mcp_allow(["proj"], scope="user")
        allow = _read_allow(user_settings)
        assert "Read(//home/user/proj/**)" in allow
        assert "mcp__proj__*" in allow

    def test_plugin_namespaced_servers(self, user_settings: Path) -> None:
        result = batch_add_mcp_allow(
            ["plugin_proj_proj", "plugin_perms_perms", "plugin_worktree_worktree"],
            scope="user",
        )
        assert "Added 3" in result
        allow = _read_allow(user_settings)
        assert "mcp__plugin_proj_proj__*" in allow
        assert "mcp__plugin_perms_perms__*" in allow
        assert "mcp__plugin_worktree_worktree__*" in allow


# ---------------------------------------------------------------------------
# scope="project" — writes to ./.claude/settings.json, not ~/.claude/settings.json
# ---------------------------------------------------------------------------


@pytest.fixture()
def project_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Return path to .claude/settings.json inside a tmp project dir (cwd set there)."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)
    return project_dir / ".claude" / "settings.json"


@pytest.fixture()
def project_and_user_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path]:
    """Return (project_settings_path, user_settings_path) with both isolated."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)

    user_path = tmp_path / "user" / ".claude" / "settings.json"
    monkeypatch.setattr(storage, "_USER_SETTINGS", user_path)

    return project_dir / ".claude" / "settings.json", user_path


class TestAddAllowProjectScope:
    def test_adds_rules_to_project_settings(self, project_settings: Path) -> None:
        result = add_allow("/home/user/proj", scope="project")
        assert "Added 2" in result
        allow = _read_allow(project_settings)
        assert "Read(//home/user/proj/**)" in allow
        assert "Edit(//home/user/proj/**)" in allow

    def test_does_not_touch_user_settings(
        self, project_and_user_settings: tuple[Path, Path]
    ) -> None:
        project_path, user_path = project_and_user_settings
        add_allow("/home/user/proj", scope="project")
        assert project_path.exists()
        assert not user_path.exists(), "user settings.json must NOT be created when scope='project'"

    def test_message_references_project_path(self, project_settings: Path) -> None:
        result = add_allow("/home/user/proj", scope="project")
        # Result message should mention the project-local path, not ~/.claude/settings.json
        assert ".claude/settings.json" in result
        home_settings = str(Path.home() / ".claude" / "settings.json")
        assert home_settings not in result

    def test_idempotent(self, project_settings: Path) -> None:
        add_allow("/home/user/proj", scope="project")
        result = add_allow("/home/user/proj", scope="project")
        assert "already present" in result
        assert _read_allow(project_settings).count("Read(//home/user/proj/**)") == 1

    def test_preserves_existing_rules(self, project_settings: Path) -> None:
        _write_settings(
            project_settings,
            {"permissions": {"allow": ["Read(//other/**)"]}},
        )
        add_allow("/home/user/proj", scope="project")
        allow = _read_allow(project_settings)
        assert "Read(//other/**)" in allow
        assert "Read(//home/user/proj/**)" in allow

    def test_preserves_other_settings_keys(self, project_settings: Path, tmp_path: Path) -> None:
        _write_settings(project_settings, {"model": "sonnet"})
        add_allow("/home/user/proj", scope="project")
        data: dict[str, object] = json.loads(project_settings.read_text())
        assert data["model"] == "sonnet"


class TestRemoveAllowProjectScope:
    def test_removes_rules_from_project_settings(self, project_settings: Path) -> None:
        _write_settings(
            project_settings,
            {
                "permissions": {
                    "allow": ["Read(//home/user/proj/**)", "Edit(//home/user/proj/**)"]
                }
            },
        )
        result = remove_allow("/home/user/proj", scope="project")
        assert "Removed 2" in result
        assert _read_allow(project_settings) == []

    def test_does_not_touch_user_settings(
        self, project_and_user_settings: tuple[Path, Path]
    ) -> None:
        project_path, user_path = project_and_user_settings
        _write_settings(
            project_path,
            {"permissions": {"allow": ["Read(//home/user/proj/**)", "Edit(//home/user/proj/**)"]}},
        )
        remove_allow("/home/user/proj", scope="project")
        assert not user_path.exists(), "user settings.json must NOT be created when scope='project'"

    def test_no_match_is_idempotent(self, project_settings: Path) -> None:
        result = remove_allow("/nonexistent/path", scope="project")
        assert "No matching" in result

    def test_only_removes_matching(self, project_settings: Path) -> None:
        _write_settings(
            project_settings,
            {
                "permissions": {
                    "allow": [
                        "Read(//home/user/proj/**)",
                        "Edit(//home/user/proj/**)",
                        "Read(//other/**)",
                    ]
                }
            },
        )
        remove_allow("/home/user/proj", scope="project")
        allow = _read_allow(project_settings)
        assert "Read(//other/**)" in allow
        assert "Read(//home/user/proj/**)" not in allow


class TestCheckAllowProjectScope:
    def test_missing(self, project_settings: Path) -> None:
        result = check_allow("/home/user/proj", scope="project")
        assert "MISSING" in result

    def test_present(self, project_settings: Path) -> None:
        _write_settings(
            project_settings,
            {
                "permissions": {
                    "allow": ["Read(//home/user/proj/**)", "Edit(//home/user/proj/**)"]
                }
            },
        )
        result = check_allow("/home/user/proj", scope="project")
        assert "OK" in result

    def test_partial(self, project_settings: Path) -> None:
        _write_settings(
            project_settings,
            {"permissions": {"allow": ["Read(//home/user/proj/**)"]}},
        )
        result = check_allow("/home/user/proj", scope="project")
        assert "PARTIAL" in result

    def test_does_not_check_user_settings(
        self, project_and_user_settings: tuple[Path, Path]
    ) -> None:
        project_path, user_path = project_and_user_settings
        # Put rule in user settings only — project check must still say MISSING
        _write_settings(
            user_path,
            {"permissions": {"allow": ["Read(//home/user/proj/**)", "Edit(//home/user/proj/**)"]}},
        )
        result = check_allow("/home/user/proj", scope="project")
        assert "MISSING" in result


class TestMcpAllowProjectScope:
    def test_add_mcp_allow_writes_to_project_settings(self, project_settings: Path) -> None:
        result = add_mcp_allow("proj", scope="project")
        assert "mcp__proj__*" in result
        allow = _read_allow(project_settings)
        assert "mcp__proj__*" in allow

    def test_add_mcp_allow_does_not_touch_user_settings(
        self, project_and_user_settings: tuple[Path, Path]
    ) -> None:
        project_path, user_path = project_and_user_settings
        add_mcp_allow("proj", scope="project")
        assert project_path.exists()
        assert not user_path.exists(), "user settings.json must NOT be created when scope='project'"

    def test_add_mcp_allow_idempotent(self, project_settings: Path) -> None:
        add_mcp_allow("proj", scope="project")
        result = add_mcp_allow("proj", scope="project")
        assert "already present" in result
        assert _read_allow(project_settings).count("mcp__proj__*") == 1

    def test_remove_mcp_allow_project_scope(self, project_settings: Path) -> None:
        add_mcp_allow("proj", scope="project")
        result = remove_mcp_allow("proj", scope="project")
        assert "Removed" in result
        assert "mcp__proj__*" not in _read_allow(project_settings)

    def test_remove_mcp_allow_not_found_project_scope(self, project_settings: Path) -> None:
        result = remove_mcp_allow("proj", scope="project")
        assert "not found" in result


class TestBatchAddMcpAllowProjectScope:
    def test_adds_servers_to_project_settings(self, project_settings: Path) -> None:
        result = batch_add_mcp_allow(["proj", "perms", "worktree"], scope="project")
        assert "Added 3" in result
        allow = _read_allow(project_settings)
        assert "mcp__proj__*" in allow
        assert "mcp__perms__*" in allow
        assert "mcp__worktree__*" in allow

    def test_does_not_touch_user_settings(
        self, project_and_user_settings: tuple[Path, Path]
    ) -> None:
        project_path, user_path = project_and_user_settings
        batch_add_mcp_allow(["proj", "perms"], scope="project")
        assert project_path.exists()
        assert not user_path.exists(), "user settings.json must NOT be created when scope='project'"

    def test_idempotent(self, project_settings: Path) -> None:
        batch_add_mcp_allow(["proj", "perms"], scope="project")
        result = batch_add_mcp_allow(["proj", "perms"], scope="project")
        assert "already present" in result
        allow = _read_allow(project_settings)
        assert allow.count("mcp__proj__*") == 1
        assert allow.count("mcp__perms__*") == 1

    def test_partial_overlap_adds_only_new(self, project_settings: Path) -> None:
        batch_add_mcp_allow(["proj"], scope="project")
        result = batch_add_mcp_allow(["proj", "perms"], scope="project")
        assert "Added 1" in result
        assert "Skipped 1" in result
        allow = _read_allow(project_settings)
        assert allow.count("mcp__proj__*") == 1
        assert "mcp__perms__*" in allow

    def test_preserves_existing_non_mcp_rules(self, project_settings: Path) -> None:
        _write_settings(project_settings, {"permissions": {"allow": ["Read(//home/user/proj/**)"]}})
        batch_add_mcp_allow(["proj"], scope="project")
        allow = _read_allow(project_settings)
        assert "Read(//home/user/proj/**)" in allow
        assert "mcp__proj__*" in allow


# ---------------------------------------------------------------------------
# target="sandbox" — writes to settings.local.json sandbox.filesystem.allowWrite
# ---------------------------------------------------------------------------


def _write_local_settings(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def _read_sandbox_allow_write(path: Path) -> list[str]:
    data: dict[str, object] = json.loads(path.read_text())
    sandbox = data.get("sandbox", {})
    assert isinstance(sandbox, dict)
    fs = sandbox.get("filesystem", {})
    assert isinstance(fs, dict)
    return fs.get("allowWrite", [])  # type: ignore[return-value]


def _read_local_allow(path: Path) -> list[str]:
    data: dict[str, object] = json.loads(path.read_text())
    perms = data.get("permissions", {})
    assert isinstance(perms, dict)
    return perms.get("allow", [])  # type: ignore[return-value]


@pytest.fixture()
def sandbox_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Return path to ~/.claude/settings.local.json with sandbox.enabled=true."""
    local_path = tmp_path / ".claude" / "settings.local.json"
    _write_local_settings(local_path, {"sandbox": {"enabled": True}})
    monkeypatch.setattr(storage, "_USER_LOCAL_SETTINGS", local_path)
    # Also set _USER_SETTINGS to a separate file so standard mode doesn't interfere
    monkeypatch.setattr(storage, "_USER_SETTINGS", tmp_path / ".claude" / "settings.json")
    return local_path


class TestAddAllowSandboxMode:
    def test_adds_path_to_sandbox_allow_write(self, sandbox_settings: Path) -> None:
        result = add_allow("/home/user/proj", scope="user", target="sandbox")
        assert "sandbox" in result.lower()
        aw = _read_sandbox_allow_write(sandbox_settings)
        assert "/home/user/proj" in aw

    def test_idempotent(self, sandbox_settings: Path) -> None:
        add_allow("/home/user/proj", scope="user", target="sandbox")
        result = add_allow("/home/user/proj", scope="user", target="sandbox")
        assert "already present" in result
        aw = _read_sandbox_allow_write(sandbox_settings)
        assert aw.count("/home/user/proj") == 1

    def test_auto_detects_sandbox(self, sandbox_settings: Path) -> None:
        result = add_allow("/home/user/proj", scope="user", target="auto")
        assert "sandbox" in result.lower()
        aw = _read_sandbox_allow_write(sandbox_settings)
        assert "/home/user/proj" in aw

    def test_preserves_existing_sandbox_config(self, sandbox_settings: Path) -> None:
        _write_local_settings(sandbox_settings, {
            "sandbox": {
                "enabled": True,
                "filesystem": {"allowWrite": ["/existing"]},
            },
        })
        add_allow("/home/user/proj", scope="user", target="sandbox")
        aw = _read_sandbox_allow_write(sandbox_settings)
        assert "/existing" in aw
        assert "/home/user/proj" in aw


class TestRemoveAllowSandboxMode:
    def test_removes_path_from_sandbox(self, sandbox_settings: Path) -> None:
        _write_local_settings(sandbox_settings, {
            "sandbox": {
                "enabled": True,
                "filesystem": {"allowWrite": ["/home/user/proj"]},
            },
        })
        result = remove_allow("/home/user/proj", scope="user", target="sandbox")
        assert "Removed" in result
        aw = _read_sandbox_allow_write(sandbox_settings)
        assert "/home/user/proj" not in aw

    def test_no_match_idempotent(self, sandbox_settings: Path) -> None:
        result = remove_allow("/nonexistent", scope="user", target="sandbox")
        assert "No matching" in result


class TestListAllowSandboxMode:
    def test_shows_sandbox_rules(self, sandbox_settings: Path) -> None:
        _write_local_settings(sandbox_settings, {
            "sandbox": {
                "enabled": True,
                "filesystem": {"allowWrite": ["/home/user/proj"]},
            },
            "permissions": {"allow": ["mcp__proj__*"]},
        })
        result = list_allow("user", target="sandbox")
        assert "/home/user/proj" in result
        assert "mcp__proj__*" in result

    def test_empty_sandbox(self, sandbox_settings: Path) -> None:
        result = list_allow("user", target="sandbox")
        assert "no sandbox rules" in result


class TestCheckAllowSandboxMode:
    def test_present(self, sandbox_settings: Path) -> None:
        _write_local_settings(sandbox_settings, {
            "sandbox": {
                "enabled": True,
                "filesystem": {"allowWrite": ["/home/user/proj"]},
            },
        })
        result = check_allow("/home/user/proj", scope="user", target="sandbox")
        assert "OK" in result

    def test_missing(self, sandbox_settings: Path) -> None:
        result = check_allow("/home/user/proj", scope="user", target="sandbox")
        assert "MISSING" in result


class TestMcpAllowSandboxMode:
    def test_mcp_rules_go_to_local_permissions_allow(self, sandbox_settings: Path) -> None:
        result = add_mcp_allow("proj", scope="user", target="sandbox")
        assert "mcp__proj__*" in result
        allow = _read_local_allow(sandbox_settings)
        assert "mcp__proj__*" in allow

    def test_idempotent(self, sandbox_settings: Path) -> None:
        add_mcp_allow("proj", scope="user", target="sandbox")
        result = add_mcp_allow("proj", scope="user", target="sandbox")
        assert "already present" in result

    def test_remove_mcp_sandbox(self, sandbox_settings: Path) -> None:
        add_mcp_allow("proj", scope="user", target="sandbox")
        result = remove_mcp_allow("proj", scope="user", target="sandbox")
        assert "Removed" in result
        allow = _read_local_allow(sandbox_settings)
        assert "mcp__proj__*" not in allow


class TestBatchAddMcpAllowSandboxMode:
    def test_adds_to_local_settings(self, sandbox_settings: Path) -> None:
        result = batch_add_mcp_allow(["proj", "perms"], scope="user", target="sandbox")
        assert "Added 2" in result
        allow = _read_local_allow(sandbox_settings)
        assert "mcp__proj__*" in allow
        assert "mcp__perms__*" in allow

    def test_auto_detects_sandbox(self, sandbox_settings: Path) -> None:
        result = batch_add_mcp_allow(["proj"], scope="user", target="auto")
        allow = _read_local_allow(sandbox_settings)
        assert "mcp__proj__*" in allow

    def test_does_not_write_to_settings_json(
        self, sandbox_settings: Path, tmp_path: Path
    ) -> None:
        """Sandbox mode must not create or modify settings.json."""
        user_settings = tmp_path / ".claude" / "settings.json"
        batch_add_mcp_allow(["proj"], scope="user", target="sandbox")
        assert not user_settings.exists()


class TestAutoTargetFallsBackToSettings:
    """When sandbox is not enabled, auto target falls back to settings.json."""

    def test_auto_uses_settings_when_no_sandbox(
        self, user_settings: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Ensure no settings.local.json exists
        monkeypatch.setattr(storage, "_USER_LOCAL_SETTINGS", tmp_path / "nonexistent.json")
        result = add_allow("/home/user/proj", scope="user", target="auto")
        assert "Added 2" in result
        allow = _read_allow(user_settings)
        assert "Read(//home/user/proj/**)" in allow
        assert "Edit(//home/user/proj/**)" in allow
