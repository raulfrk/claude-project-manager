"""Tests for server.tools.settings functions."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.lib import storage
from server.lib.storage import mcp_allow_entry
from server.tools.settings import (
    add_allow,
    add_domain,
    add_mcp_allow,
    batch_add_mcp_allow,
    check_allow,
    is_sandbox_enabled_tool,
    list_allow,
    reconcile_mcp,
    remove_allow,
    remove_domain,
    remove_mcp_allow,
    sandbox_init,
    set_deny,
    set_sandbox_paths,
)


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


# ---------------------------------------------------------------------------
# list_allow format="json"
# ---------------------------------------------------------------------------


class TestListAllowJsonFormat:
    """Tests for list_allow(format='json') structured output."""

    def test_returns_valid_json(self, user_settings: Path) -> None:
        _write_settings(user_settings, {"permissions": {"allow": ["mcp__proj__*"]}})
        result = list_allow("user", format="json")
        data = json.loads(result)
        assert "scopes" in data

    def test_json_contains_permissions_allow(self, user_settings: Path) -> None:
        _write_settings(user_settings, {"permissions": {"allow": ["mcp__proj__*", "mcp__perms__*"]}})
        result = list_allow("user", format="json")
        data = json.loads(result)
        scope_entry = data["scopes"][0]
        assert scope_entry["scope"] == "user"
        assert scope_entry["permissions_allow"] == ["mcp__proj__*", "mcp__perms__*"]

    def test_json_contains_sandbox_allow_write(self, sandbox_settings: Path) -> None:
        _write_local_settings(sandbox_settings, {
            "sandbox": {
                "enabled": True,
                "filesystem": {"allowWrite": ["/home/user/proj", "/home/user/other"]},
            },
            "permissions": {"allow": ["mcp__proj__*"]},
        })
        result = list_allow("user", target="sandbox", format="json")
        data = json.loads(result)
        scope_entry = data["scopes"][0]
        assert scope_entry["target"] == "sandbox"
        assert scope_entry["sandbox_allow_write"] == ["/home/user/proj", "/home/user/other"]
        assert scope_entry["permissions_allow"] == ["mcp__proj__*"]

    def test_json_empty_file_returns_empty_lists(self, user_settings: Path) -> None:
        # File does not exist — should still return valid JSON with empty lists
        result = list_allow("user", format="json")
        data = json.loads(result)
        scope_entry = data["scopes"][0]
        assert scope_entry["permissions_allow"] == []
        assert scope_entry["sandbox_allow_write"] == []
        assert scope_entry["path"] == str(user_settings)

    def test_json_scope_all_returns_both(
        self, project_and_user_settings: tuple[Path, Path]
    ) -> None:
        project_path, user_path = project_and_user_settings
        _write_settings(user_path, {"permissions": {"allow": ["mcp__proj__*"]}})
        _write_settings(project_path, {"permissions": {"allow": ["mcp__perms__*"]}})
        result = list_allow("all", format="json")
        data = json.loads(result)
        assert len(data["scopes"]) == 2
        scopes_by_name = {s["scope"]: s for s in data["scopes"]}
        assert scopes_by_name["user"]["permissions_allow"] == ["mcp__proj__*"]
        assert scopes_by_name["project"]["permissions_allow"] == ["mcp__perms__*"]

    def test_json_includes_path_field(self, user_settings: Path) -> None:
        _write_settings(user_settings, {"permissions": {"allow": []}})
        result = list_allow("user", format="json")
        data = json.loads(result)
        assert data["scopes"][0]["path"] == str(user_settings)

    def test_json_includes_target_field_settings(self, user_settings: Path) -> None:
        result = list_allow("user", target="settings", format="json")
        data = json.loads(result)
        assert data["scopes"][0]["target"] == "settings"

    def test_json_includes_target_field_sandbox(self, sandbox_settings: Path) -> None:
        result = list_allow("user", target="sandbox", format="json")
        data = json.loads(result)
        assert data["scopes"][0]["target"] == "sandbox"

    def test_text_format_unchanged(self, user_settings: Path) -> None:
        """format='text' returns the same output as the original (no JSON)."""
        _write_settings(user_settings, {"permissions": {"allow": ["Read(//foo/**)"]}})
        result_text = list_allow("user", format="text")
        assert "Read(//foo/**)" in result_text
        # Must not be JSON
        with pytest.raises(json.JSONDecodeError):
            json.loads(result_text)

    def test_default_format_is_text(self, user_settings: Path) -> None:
        """Omitting format returns text (backward compatible)."""
        _write_settings(user_settings, {"permissions": {"allow": ["Read(//foo/**)"]}})
        result = list_allow("user")
        assert "Read(//foo/**)" in result
        with pytest.raises(json.JSONDecodeError):
            json.loads(result)


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


# ---------------------------------------------------------------------------
# sandbox_init
# ---------------------------------------------------------------------------


def _read_sandbox(path: Path) -> dict[str, object]:
    data: dict[str, object] = json.loads(path.read_text())
    sandbox = data.get("sandbox", {})
    assert isinstance(sandbox, dict)
    return sandbox


class TestSandboxInit:
    def test_init_clean_file(self, user_settings: Path) -> None:
        result = sandbox_init()
        assert "initialized" in result.lower() or "enabled" in result.lower()
        sandbox = _read_sandbox(user_settings)
        assert sandbox.get("enabled") is True
        assert sandbox.get("autoAllowBashIfSandboxed") is True

    def test_init_with_path(self, user_settings: Path) -> None:
        result = sandbox_init(path="/home/user/proj")
        assert "/home/user/proj" in result
        sandbox = _read_sandbox(user_settings)
        fs = sandbox.get("filesystem", {})
        assert isinstance(fs, dict)
        assert "/home/user/proj" in fs.get("allowWrite", [])

    def test_auto_migrate_read_edit_rules(self, user_settings: Path) -> None:
        _write_settings(user_settings, {
            "permissions": {
                "allow": [
                    "Read(//home/user/proj/**)",
                    "Edit(//home/user/proj/**)",
                    "Read(//home/user/other/**)",
                    "mcp__proj__*",
                ]
            },
        })
        result = sandbox_init()
        assert "Migrated 2" in result
        sandbox = _read_sandbox(user_settings)
        fs = sandbox.get("filesystem", {})
        assert isinstance(fs, dict)
        aw = fs.get("allowWrite", [])
        assert "/home/user/proj" in aw
        assert "/home/user/other" in aw

    def test_idempotent(self, user_settings: Path) -> None:
        sandbox_init()
        result = sandbox_init()
        assert "already initialized" in result.lower()

    def test_migrate_plus_path(self, user_settings: Path) -> None:
        _write_settings(user_settings, {
            "permissions": {"allow": ["Read(//home/user/proj/**)", "Edit(//home/user/proj/**)"]}
        })
        result = sandbox_init(path="/extra/path")
        sandbox = _read_sandbox(user_settings)
        fs = sandbox.get("filesystem", {})
        assert isinstance(fs, dict)
        aw = fs.get("allowWrite", [])
        assert "/home/user/proj" in aw
        assert "/extra/path" in aw


# ---------------------------------------------------------------------------
# Domain tools
# ---------------------------------------------------------------------------


def _read_sandbox_domains(path: Path) -> list[str]:
    sandbox = _read_sandbox(path)
    net = sandbox.get("network", {})
    assert isinstance(net, dict)
    return net.get("allowedDomains", [])  # type: ignore[return-value]


class TestAddDomain:
    def test_adds_domain(self, user_settings: Path) -> None:
        result = add_domain("github.com")
        assert "github.com" in result
        assert "github.com" in _read_sandbox_domains(user_settings)

    def test_idempotent(self, user_settings: Path) -> None:
        add_domain("github.com")
        result = add_domain("github.com")
        assert "already present" in result
        assert _read_sandbox_domains(user_settings).count("github.com") == 1


class TestRemoveDomain:
    def test_removes_domain(self, user_settings: Path) -> None:
        add_domain("github.com")
        result = remove_domain("github.com")
        assert "Removed" in result
        assert "github.com" not in _read_sandbox_domains(user_settings)

    def test_not_found(self, user_settings: Path) -> None:
        result = remove_domain("nonexistent.com")
        assert "not found" in result


# ---------------------------------------------------------------------------
# is_sandbox_enabled tool
# ---------------------------------------------------------------------------


class TestIsSandboxEnabled:
    def test_returns_true_when_sandbox_enabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        local_path = tmp_path / ".claude" / "settings.local.json"
        _write_local_settings(local_path, {"sandbox": {"enabled": True}})
        monkeypatch.setattr(storage, "_USER_LOCAL_SETTINGS", local_path)
        result = is_sandbox_enabled_tool(scope="user")
        assert result == "sandbox_enabled: true"

    def test_returns_false_when_sandbox_disabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        local_path = tmp_path / ".claude" / "settings.local.json"
        _write_local_settings(local_path, {"sandbox": {"enabled": False}})
        monkeypatch.setattr(storage, "_USER_LOCAL_SETTINGS", local_path)
        result = is_sandbox_enabled_tool(scope="user")
        assert result == "sandbox_enabled: false"

    def test_returns_false_when_file_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(storage, "_USER_LOCAL_SETTINGS", tmp_path / "nonexistent.json")
        result = is_sandbox_enabled_tool(scope="user")
        assert result == "sandbox_enabled: false"

    def test_returns_false_when_no_sandbox_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        local_path = tmp_path / ".claude" / "settings.local.json"
        _write_local_settings(local_path, {"permissions": {"allow": []}})
        monkeypatch.setattr(storage, "_USER_LOCAL_SETTINGS", local_path)
        result = is_sandbox_enabled_tool(scope="user")
        assert result == "sandbox_enabled: false"

    def test_project_scope(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)
        local_path = project_dir / ".claude" / "settings.local.json"
        _write_local_settings(local_path, {"sandbox": {"enabled": True}})
        result = is_sandbox_enabled_tool(scope="project")
        assert result == "sandbox_enabled: true"


# ---------------------------------------------------------------------------
# T16 — set_sandbox_paths
# ---------------------------------------------------------------------------


class TestSetSandboxPaths:
    def test_set_sandbox_paths_replace(self, sandbox_settings: Path) -> None:
        _write_local_settings(sandbox_settings, {
            "sandbox": {
                "enabled": True,
                "filesystem": {"allowWrite": ["/old/path1", "/old/path2"]},
            },
        })
        result = set_sandbox_paths(["/new/a", "/new/b"])
        assert "2 root(s)" in result
        aw = _read_sandbox_allow_write(sandbox_settings)
        assert "/new/a" in aw
        assert "/new/b" in aw
        # Old paths not under new roots are preserved by default
        assert "/old/path1" in aw
        assert "/old/path2" in aw

    def test_set_sandbox_paths_preserve_extra(self, sandbox_settings: Path) -> None:
        """User-added paths not under given roots are preserved."""
        _write_local_settings(sandbox_settings, {
            "sandbox": {
                "enabled": True,
                "filesystem": {"allowWrite": ["/user/custom", "/home/user/proj/sub"]},
            },
        })
        result = set_sandbox_paths(["/home/user/proj"])
        aw = _read_sandbox_allow_write(sandbox_settings)
        # /user/custom is not under /home/user/proj so it is preserved
        assert "/user/custom" in aw
        assert "/home/user/proj" in aw
        assert "1 preserved" in result

    def test_set_sandbox_paths_containment(self, sandbox_settings: Path) -> None:
        """Paths under roots are NOT preserved (deduplication)."""
        _write_local_settings(sandbox_settings, {
            "sandbox": {
                "enabled": True,
                "filesystem": {"allowWrite": ["/home/user/proj/subdir", "/home/user/proj"]},
            },
        })
        result = set_sandbox_paths(["/home/user/proj"])
        aw = _read_sandbox_allow_write(sandbox_settings)
        assert "/home/user/proj" in aw
        # /home/user/proj/subdir starts with /home/user/proj/ so it's dropped
        assert "/home/user/proj/subdir" not in aw
        assert "0 preserved" in result


# ---------------------------------------------------------------------------
# T17 — set_deny
# ---------------------------------------------------------------------------


class TestSetDeny:
    def test_set_deny_replaces_rules(self, sandbox_settings: Path) -> None:
        rules = ["Bash(git push *)", "Bash(rm -rf *)"]
        result = set_deny(rules)
        assert "2 rules" in result
        data: dict[str, object] = json.loads(sandbox_settings.read_text())
        perms = data.get("permissions", {})
        assert isinstance(perms, dict)
        assert perms.get("deny") == rules

    def test_set_deny_clear_settings_json(self, sandbox_settings: Path) -> None:
        """When clear_settings_json_deny is True, deny is cleared from settings.json."""
        main_path = sandbox_settings.parent / "settings.json"
        _write_settings(main_path, {"permissions": {"deny": ["Bash(sudo *)"]}})
        set_deny(["Bash(git push *)"], clear_settings_json_deny=True)
        main_data: dict[str, object] = json.loads(main_path.read_text())
        main_perms = main_data.get("permissions", {})
        assert isinstance(main_perms, dict)
        # deny should be cleared from settings.json
        assert main_perms.get("deny", []) == []


# ---------------------------------------------------------------------------
# T18 — reconcile_mcp
# ---------------------------------------------------------------------------


class TestReconcileMcp:
    def test_reconcile_mcp_removes_stale_from_both(self, sandbox_settings: Path) -> None:
        main_path = sandbox_settings.parent / "settings.json"
        _write_settings(main_path, {
            "permissions": {"allow": ["mcp__stale_srv__*", "mcp__keep__*"]},
        })
        _write_local_settings(sandbox_settings, {
            "sandbox": {"enabled": True},
            "permissions": {"allow": ["mcp__stale_srv__*", "mcp__local_keep__*"]},
        })
        result = reconcile_mcp(
            expected_servers=["keep", "local_keep"],
            stale_servers=["stale_srv"],
        )
        assert "stale removed" in result
        main_allow = _read_allow(main_path)
        assert "mcp__stale_srv__*" not in main_allow
        assert "mcp__keep__*" in main_allow
        local_allow = _read_local_allow(sandbox_settings)
        assert "mcp__stale_srv__*" not in local_allow
        assert "mcp__local_keep__*" in local_allow

    def test_reconcile_mcp_adds_missing_to_local_only(self, sandbox_settings: Path) -> None:
        main_path = sandbox_settings.parent / "settings.json"
        _write_settings(main_path, {"permissions": {"allow": []}})
        _write_local_settings(sandbox_settings, {
            "sandbox": {"enabled": True},
            "permissions": {"allow": []},
        })
        result = reconcile_mcp(expected_servers=["proj", "perms"])
        assert "2 missing added" in result
        local_allow = _read_local_allow(sandbox_settings)
        assert "mcp__proj__*" in local_allow
        assert "mcp__perms__*" in local_allow
        # Must NOT be added to main settings.json
        main_allow = _read_allow(main_path)
        assert "mcp__proj__*" not in main_allow
        assert "mcp__perms__*" not in main_allow

    def test_reconcile_mcp_preserves_user_rules(self, sandbox_settings: Path) -> None:
        main_path = sandbox_settings.parent / "settings.json"
        _write_settings(main_path, {
            "permissions": {"allow": ["mcp__user_custom__*"]},
        })
        _write_local_settings(sandbox_settings, {
            "sandbox": {"enabled": True},
            "permissions": {"allow": ["mcp__another_custom__*"]},
        })
        reconcile_mcp(
            expected_servers=["proj"],
            stale_servers=["old_srv"],
        )
        main_allow = _read_allow(main_path)
        assert "mcp__user_custom__*" in main_allow
        local_allow = _read_local_allow(sandbox_settings)
        assert "mcp__another_custom__*" in local_allow


# ---------------------------------------------------------------------------
# T23 — set_deny cross-file (no clear by default)
# ---------------------------------------------------------------------------


class TestSetDenyCrossFile:
    def test_set_deny_no_clear_by_default(self, sandbox_settings: Path) -> None:
        """settings.json deny is untouched when clear_settings_json_deny is False."""
        main_path = sandbox_settings.parent / "settings.json"
        _write_settings(main_path, {"permissions": {"deny": ["Bash(sudo *)"]}})
        set_deny(["Bash(git push *)"], clear_settings_json_deny=False)
        main_data: dict[str, object] = json.loads(main_path.read_text())
        main_perms = main_data.get("permissions", {})
        assert isinstance(main_perms, dict)
        assert main_perms.get("deny") == ["Bash(sudo *)"]


# ---------------------------------------------------------------------------
# T25 — fresh state (no existing files)
# ---------------------------------------------------------------------------


class TestFreshState:
    def test_set_sandbox_paths_fresh_state(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        local_path = tmp_path / ".claude" / "settings.local.json"
        monkeypatch.setattr(storage, "_USER_LOCAL_SETTINGS", local_path)
        # No file exists yet
        assert not local_path.exists()
        result = set_sandbox_paths(["/home/user/proj"])
        assert "1 root(s)" in result
        assert local_path.exists()
        aw = _read_sandbox_allow_write(local_path)
        assert "/home/user/proj" in aw

    def test_set_deny_fresh_state(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        local_path = tmp_path / ".claude" / "settings.local.json"
        monkeypatch.setattr(storage, "_USER_LOCAL_SETTINGS", local_path)
        assert not local_path.exists()
        result = set_deny(["Bash(git push *)"])
        assert "1 rules" in result
        assert local_path.exists()
        data: dict[str, object] = json.loads(local_path.read_text())
        perms = data.get("permissions", {})
        assert isinstance(perms, dict)
        assert perms.get("deny") == ["Bash(git push *)"]


