"""Tests for proj_perms_sync MCP tool."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
import yaml

from server.lib import storage
from server.lib.models import (
    PermissionsConfig,
    ProjConfig,
    ProjectDates,
    ProjectEntry,
    ProjectMeta,
    RepoEntry,
    TodoistSync,
)
from server.tools.perms_sync import _derive_expected_rules, _load_actual_rules, run_sync


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_cfg(
    auto_allow_mcps: bool = True,
    todoist_enabled: bool = False,
    tracking_dir: str = "/tmp/tracking",
    perms_integration: bool = False,
    worktree_integration: bool = False,
) -> ProjConfig:
    cfg = ProjConfig(
        tracking_dir=tracking_dir,
        perms_integration=perms_integration,
        worktree_integration=worktree_integration,
    )
    cfg.permissions = PermissionsConfig(auto_grant=True, auto_allow_mcps=auto_allow_mcps)
    cfg.todoist = TodoistSync(enabled=todoist_enabled)
    return cfg


def _make_meta(repos: list[RepoEntry]) -> ProjectMeta:
    today = str(date.today())
    return ProjectMeta(
        name="test-project",
        repos=repos,
        dates=ProjectDates(created=today, last_updated=today),
    )


def _write_settings(tmp_path: Path, allow: list[str]) -> Path:
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps({"permissions": {"allow": allow}}))
    return settings_path


# ── _derive_expected_rules ────────────────────────────────────────────────────


class TestDeriveExpectedRules:
    def test_two_repos_produce_read_and_edit_rules(self) -> None:
        from server.lib.models import DEFAULT_INVESTIGATION_TOOLS

        repos = [
            "/home/user/project-a",
            "/home/user/project-b",
        ]
        meta = _make_meta(
            repos=[
                RepoEntry(label="code", path=repos[0]),
                RepoEntry(label="docs", path=repos[1]),
            ]
        )
        cfg = _make_cfg(auto_allow_mcps=False)

        rules = _derive_expected_rules(meta, cfg)

        # collect_paths() includes repos + tracking_dir for Bash rules
        all_bash_paths = repos + ["/tmp/tracking"]
        expected: set[str] = set()
        for path in repos:
            prefix = f"/{path}"
            expected.add(f"Read({prefix}/**)")
            expected.add(f"Edit({prefix}/**)")
        for path in all_bash_paths:
            prefix = f"/{path}"
            for tool in DEFAULT_INVESTIGATION_TOOLS:
                expected.add(f"Bash({tool} {prefix}/**)")
        # Always-present global Claude.ai MCP rules (auto_allow_mcps=False only
        # suppresses plugin-specific MCP rules, not global ones)
        expected.add("mcp__claude_ai_Excalidraw__*")
        expected.add("mcp__claude_ai_Mermaid_Chart__*")

        assert rules == expected

    def test_auto_allow_mcps_true_adds_mcp_rules(self) -> None:
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(
            auto_allow_mcps=True,
            todoist_enabled=False,
            perms_integration=True,
            worktree_integration=True,
        )

        rules = _derive_expected_rules(meta, cfg)

        assert "mcp__proj__*" in rules
        assert "mcp__perms__*" in rules
        assert "mcp__worktree__*" in rules
        assert "mcp__claude_ai_Todoist__*" not in rules

    def test_todoist_enabled_adds_todoist_mcp_rule(self) -> None:
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=True, todoist_enabled=True)

        rules = _derive_expected_rules(meta, cfg)

        assert "mcp__claude_ai_Todoist__*" in rules

    def test_auto_allow_mcps_false_no_plugin_mcp_rules(self) -> None:
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(
            auto_allow_mcps=False,
            todoist_enabled=True,
            perms_integration=True,
            worktree_integration=True,
        )

        rules = _derive_expected_rules(meta, cfg)

        # All plugin MCP servers are excluded when auto_allow_mcps=False
        assert "mcp__proj__*" not in rules
        assert "mcp__perms__*" not in rules
        assert "mcp__worktree__*" not in rules
        assert "mcp__claude_ai_Todoist__*" not in rules
        # Global Claude.ai servers are always present regardless
        assert "mcp__claude_ai_Excalidraw__*" in rules
        assert "mcp__claude_ai_Mermaid_Chart__*" in rules

    def test_trailing_slash_in_path_is_stripped(self) -> None:
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj/")])
        cfg = _make_cfg(auto_allow_mcps=False)

        rules = _derive_expected_rules(meta, cfg)

        assert "Read(//home/user/proj/**)" in rules
        assert "Edit(//home/user/proj/**)" in rules
        # Double trailing slash variant must NOT appear
        assert "Read(//home/user/proj//**)" not in rules

    def test_no_repos_auto_allow_only_mcp_rules(self) -> None:
        meta = _make_meta(repos=[])
        cfg = _make_cfg(auto_allow_mcps=True)

        rules = _derive_expected_rules(meta, cfg)

        # MCP rules always present
        assert "mcp__proj__*" in rules
        assert "mcp__claude_ai_Excalidraw__*" in rules
        assert "mcp__claude_ai_Mermaid_Chart__*" in rules
        # Bash rules for tracking_dir also present (no repos, but tracking_dir is set)
        assert any("Bash(" in r and "/tmp/tracking" in r for r in rules)

    def test_no_repos_auto_allow_with_integrations(self) -> None:
        meta = _make_meta(repos=[])
        cfg = _make_cfg(
            auto_allow_mcps=True, perms_integration=True, worktree_integration=True
        )

        rules = _derive_expected_rules(meta, cfg)

        assert "mcp__proj__*" in rules
        assert "mcp__perms__*" in rules
        assert "mcp__worktree__*" in rules
        assert "mcp__claude_ai_Excalidraw__*" in rules
        assert "mcp__claude_ai_Mermaid_Chart__*" in rules

    def test_perms_integration_only_adds_perms_mcp_rule(self) -> None:
        meta = _make_meta(repos=[])
        cfg = _make_cfg(auto_allow_mcps=True, perms_integration=True, worktree_integration=False)

        rules = _derive_expected_rules(meta, cfg)

        assert "mcp__perms__*" in rules
        assert "mcp__worktree__*" not in rules

    def test_worktree_integration_only_adds_worktree_mcp_rule(self) -> None:
        meta = _make_meta(repos=[])
        cfg = _make_cfg(auto_allow_mcps=True, perms_integration=False, worktree_integration=True)

        rules = _derive_expected_rules(meta, cfg)

        assert "mcp__worktree__*" in rules
        assert "mcp__perms__*" not in rules

    def test_no_repos_no_mcps_empty_set(self) -> None:
        meta = _make_meta(repos=[])
        cfg = _make_cfg(auto_allow_mcps=False)

        rules = _derive_expected_rules(meta, cfg)

        # MCP rules + Bash rules for tracking_dir
        assert "mcp__claude_ai_Excalidraw__*" in rules
        assert "mcp__claude_ai_Mermaid_Chart__*" in rules
        # No Read/Edit rules since no repos
        assert not any(r.startswith("Read(") or r.startswith("Edit(") for r in rules)

    def test_worktree_integration_false_with_worktree_config_no_extra_bash_rules(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Extra paths in worktree.yaml are ignored when worktree_integration=False."""
        wt_config = tmp_path / "worktree.yaml"
        wt_config.write_text(
            yaml.dump({
                "base_repos": [
                    {"label": "wt", "path": "/extra/worktree/path", "default_branch": "main"},
                ],
            })
        )
        monkeypatch.setattr("server.tools.perms_grant._WORKTREE_CONFIG", wt_config)

        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=False, worktree_integration=False)

        rules = _derive_expected_rules(meta, cfg)

        # The extra worktree path must not appear in any expected rule
        assert not any("/extra/worktree/path" in r for r in rules)
        # The repo path is still present
        assert "Read(//home/user/proj/**)" in rules
        assert "Edit(//home/user/proj/**)" in rules

    def test_worktree_integration_true_with_worktree_config_adds_bash_rules(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Extra paths in worktree.yaml produce Bash rules when worktree_integration=True."""
        wt_config = tmp_path / "worktree.yaml"
        wt_config.write_text(
            yaml.dump({
                "base_repos": [
                    {"label": "wt", "path": "/extra/worktree/path", "default_branch": "main"},
                ],
            })
        )
        monkeypatch.setattr("server.tools.perms_grant._WORKTREE_CONFIG", wt_config)

        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=False, worktree_integration=True)

        rules = _derive_expected_rules(meta, cfg)

        # The extra worktree path appears in Bash rules (investigation tools are on by default)
        assert any("/extra/worktree/path" in r for r in rules)


# ── _derive_expected_rules — custom mcp_server ────────────────────────────────


class TestDeriveExpectedRulesCustomServer:
    def test_todoist_custom_mcp_server_emits_custom_rule(self) -> None:
        cfg = _make_cfg(auto_allow_mcps=True, todoist_enabled=True)
        cfg.todoist.mcp_server = "sentry"
        meta = _make_meta(repos=[])

        rules = _derive_expected_rules(meta, cfg)

        assert "mcp__sentry__*" in rules
        assert "mcp__claude_ai_Todoist__*" not in rules

    def test_todoist_default_mcp_server_still_emits_standard_rule(self) -> None:
        cfg = _make_cfg(auto_allow_mcps=True, todoist_enabled=True)
        meta = _make_meta(repos=[])

        rules = _derive_expected_rules(meta, cfg)

        assert "mcp__claude_ai_Todoist__*" in rules

    def test_todoist_disabled_custom_mcp_server_emits_no_rule(self) -> None:
        cfg = _make_cfg(auto_allow_mcps=True, todoist_enabled=False)
        cfg.todoist.mcp_server = "sentry"
        meta = _make_meta(repos=[])

        rules = _derive_expected_rules(meta, cfg)

        assert "mcp__sentry__*" not in rules
        assert "mcp__claude_ai_Todoist__*" not in rules


# ── _load_actual_rules ────────────────────────────────────────────────────────


class TestLoadActualRules:
    def test_missing_settings_returns_empty_set(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "server.tools.perms_sync._settings_path",
            lambda: tmp_path / ".claude" / "settings.json",
        )

        result = _load_actual_rules()

        assert result == set()

    def test_reads_allow_rules_from_settings(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings_path = _write_settings(
            tmp_path,
            allow=["Read(//home/user/proj/**)", "mcp__proj__*"],
        )
        monkeypatch.setattr(
            "server.tools.perms_sync._settings_path",
            lambda: settings_path,
        )

        result = _load_actual_rules()

        assert "Read(//home/user/proj/**)" in result
        assert "mcp__proj__*" in result
        assert len(result) == 2

    def test_empty_allow_list_returns_empty_set(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings_path = _write_settings(tmp_path, allow=[])
        monkeypatch.setattr(
            "server.tools.perms_sync._settings_path",
            lambda: settings_path,
        )

        result = _load_actual_rules()

        assert result == set()


# ── run_sync ──────────────────────────────────────────────────────────────────


class TestRunSync:
    def test_all_rules_present_returns_in_sync(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=True, todoist_enabled=False)
        expected = _derive_expected_rules(meta, cfg)
        settings_path = _write_settings(tmp_path, allow=sorted(expected))
        monkeypatch.setattr(
            "server.tools.perms_sync._settings_path",
            lambda: settings_path,
        )

        result = run_sync(meta, cfg)

        assert "✅" in result
        assert "in sync" in result

    def test_missing_path_rules_reported(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=False)
        # settings.json has no rules at all
        settings_path = _write_settings(tmp_path, allow=[])
        monkeypatch.setattr(
            "server.tools.perms_sync._settings_path",
            lambda: settings_path,
        )

        result = run_sync(meta, cfg)

        assert "❌" in result
        assert "Read(//home/user/proj/**)" in result
        assert "Edit(//home/user/proj/**)" in result
        assert "Directory rules" in result

    def test_missing_mcp_rules_reported(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        meta = _make_meta(repos=[])
        cfg = _make_cfg(
            auto_allow_mcps=True,
            todoist_enabled=False,
            perms_integration=True,
            worktree_integration=True,
        )
        settings_path = _write_settings(tmp_path, allow=[])
        monkeypatch.setattr(
            "server.tools.perms_sync._settings_path",
            lambda: settings_path,
        )

        result = run_sync(meta, cfg)

        assert "❌" in result
        assert "mcp__proj__*" in result
        assert "MCP rules" in result

    def test_extras_in_actual_are_ignored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Extra rules in settings.json beyond what's expected are fine."""
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=True, todoist_enabled=False)
        expected = _derive_expected_rules(meta, cfg)
        # Add extra rules in actual
        actual_rules = sorted(expected) + ["Read(//some/other/path/**)", "mcp__custom__*"]
        settings_path = _write_settings(tmp_path, allow=actual_rules)
        monkeypatch.setattr(
            "server.tools.perms_sync._settings_path",
            lambda: settings_path,
        )

        result = run_sync(meta, cfg)

        assert "✅" in result

    def test_missing_rules_suggest_perms_add(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=False)
        settings_path = _write_settings(tmp_path, allow=[])
        monkeypatch.setattr(
            "server.tools.perms_sync._settings_path",
            lambda: settings_path,
        )

        result = run_sync(meta, cfg)

        assert "perms_add_mcp_allow" in result

    def test_todoist_rule_appears_when_enabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        meta = _make_meta(repos=[])
        cfg = _make_cfg(auto_allow_mcps=True, todoist_enabled=True)
        settings_path = _write_settings(tmp_path, allow=[])
        monkeypatch.setattr(
            "server.tools.perms_sync._settings_path",
            lambda: settings_path,
        )

        result = run_sync(meta, cfg)

        assert "mcp__claude_ai_Todoist__*" in result

    def test_perms_integration_false_mcp_perms_not_reported_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When perms_integration=False, mcp__perms__* is not expected so it is not reported missing."""
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=True, perms_integration=False, worktree_integration=False)
        # Provide all expected rules but deliberately omit mcp__perms__*
        expected = _derive_expected_rules(meta, cfg)
        # Verify perms rule is not even expected
        assert "mcp__perms__*" not in expected
        settings_path = _write_settings(tmp_path, allow=sorted(expected))
        monkeypatch.setattr(
            "server.tools.perms_sync._settings_path",
            lambda: settings_path,
        )

        result = run_sync(meta, cfg)

        # In sync even though mcp__perms__* is absent from settings.json
        assert "✅" in result
        assert "in sync" in result

    def test_worktree_integration_false_in_sync_without_worktree_bash_rules(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When worktree_integration=False, Bash rules for worktree-only paths are not expected."""
        # Create a worktree.yaml with an extra path
        wt_config = tmp_path / "worktree.yaml"
        wt_config.write_text(
            yaml.dump({
                "base_repos": [
                    {"label": "wt", "path": "/extra/worktree/path", "default_branch": "main"},
                ],
            })
        )
        monkeypatch.setattr("server.tools.perms_grant._WORKTREE_CONFIG", wt_config)

        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=False, worktree_integration=False)
        # Only provide rules for the repo path — no rules for the extra worktree path
        expected = _derive_expected_rules(meta, cfg)
        assert not any("/extra/worktree/path" in r for r in expected)
        settings_path = _write_settings(tmp_path, allow=sorted(expected))
        monkeypatch.setattr(
            "server.tools.perms_sync._settings_path",
            lambda: settings_path,
        )

        result = run_sync(meta, cfg)

        # No missing rules even though worktree path has no Bash rules in settings.json
        assert "✅" in result
        assert "in sync" in result

    def test_partial_rule_match_read_present_edit_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When Read rule is present but Edit rule is missing, only Edit is reported as missing."""
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=False)
        # Build expected rules and derive all expected rules
        expected = _derive_expected_rules(meta, cfg)
        # Provide all expected rules except Edit for the repo path
        partial_rules = [r for r in sorted(expected) if r != "Edit(//home/user/proj/**)"]
        assert "Read(//home/user/proj/**)" in partial_rules  # Read IS present
        assert "Edit(//home/user/proj/**)" not in partial_rules  # Edit is NOT present
        settings_path = _write_settings(tmp_path, allow=partial_rules)
        monkeypatch.setattr(
            "server.tools.perms_sync._settings_path",
            lambda: settings_path,
        )

        result = run_sync(meta, cfg)

        # Edit rule must be reported as missing
        assert "❌" in result
        assert "Edit(//home/user/proj/**)" in result
        # Read rule must NOT be reported as missing (it's already present)
        # Check that Read does not appear in the missing section
        # The result lists missing rules; Read should not be among them
        lines = result.splitlines()
        missing_lines = [line for line in lines if "Read(" in line]
        # Any mention of Read in the output should not be in a "missing" context
        # Since only Edit is missing, Read should not appear in the missing list at all
        assert not any("Read(//home/user/proj/**)" in line for line in missing_lines)

    def test_worktree_integration_true_missing_worktree_bash_rules_reported(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When worktree_integration=True, Bash rules for worktree extra paths are expected and reported if missing."""
        wt_config = tmp_path / "worktree.yaml"
        wt_config.write_text(
            yaml.dump({
                "base_repos": [
                    {"label": "wt", "path": "/extra/worktree/path", "default_branch": "main"},
                ],
            })
        )
        monkeypatch.setattr("server.tools.perms_grant._WORKTREE_CONFIG", wt_config)

        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=False, worktree_integration=True)
        # settings.json has repo rules but not worktree path Bash rules
        repo_rules = [
            "Read(//home/user/proj/**)",
            "Edit(//home/user/proj/**)",
        ]
        settings_path = _write_settings(tmp_path, allow=repo_rules)
        monkeypatch.setattr(
            "server.tools.perms_sync._settings_path",
            lambda: settings_path,
        )

        result = run_sync(meta, cfg)

        # Missing Bash rules for the worktree path must be reported
        assert "❌" in result
        assert "/extra/worktree/path" in result

    def test_run_sync_reports_missing_custom_todoist_rule(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        meta = _make_meta(repos=[])
        cfg = _make_cfg(auto_allow_mcps=True, todoist_enabled=True)
        cfg.todoist.mcp_server = "sentry"
        settings_path = _write_settings(tmp_path, allow=[])
        monkeypatch.setattr(
            "server.tools.perms_sync._settings_path",
            lambda: settings_path,
        )

        result = run_sync(meta, cfg)

        assert "mcp__sentry__*" in result
        assert "mcp__claude_ai_Todoist__*" not in result

    def test_apply_true_writes_missing_rules(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """apply=True writes missing rules into settings.json and returns a success message."""
        repo_path = str(tmp_path / "myrepo")
        meta = _make_meta(repos=[RepoEntry(label="code", path=repo_path)])
        cfg = _make_cfg(auto_allow_mcps=False)
        # settings.json starts with no rules
        settings_path = _write_settings(tmp_path, allow=[])
        monkeypatch.setattr(
            "server.tools.perms_sync._settings_path",
            lambda: settings_path,
        )
        monkeypatch.setattr("server.tools.perms_grant._USER_SETTINGS", settings_path)

        result = run_sync(meta, cfg, apply=True)

        # Return value must be a success string, not a "❌ Missing" report
        assert "✅" in result
        assert "❌" not in result
        # settings.json must now contain the Read and Edit rules
        actual = json.loads(settings_path.read_text())
        allow = actual.get("permissions", {}).get("allow", [])
        allow_set = set(allow)
        prefix = f"//{repo_path.strip('/')}"
        assert f"Read({prefix}/**)" in allow_set
        assert f"Edit({prefix}/**)" in allow_set

    def test_apply_true_already_in_sync_is_noop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """apply=True with all rules already present returns in-sync message and leaves settings.json unchanged."""
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=True, todoist_enabled=False)
        expected = _derive_expected_rules(meta, cfg)
        settings_path = _write_settings(tmp_path, allow=sorted(expected))
        monkeypatch.setattr(
            "server.tools.perms_sync._settings_path",
            lambda: settings_path,
        )
        monkeypatch.setattr("server.tools.perms_grant._USER_SETTINGS", settings_path)

        original_mtime = settings_path.stat().st_mtime
        result = run_sync(meta, cfg, apply=True)

        # Must return in-sync message
        assert "✅" in result
        assert "in sync" in result
        # File must not have been rewritten (mtime unchanged)
        assert settings_path.stat().st_mtime == original_mtime

    def test_apply_false_does_not_write(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """apply=False (default) reports missing rules but does NOT modify settings.json."""
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=False)
        settings_path = _write_settings(tmp_path, allow=[])
        monkeypatch.setattr(
            "server.tools.perms_sync._settings_path",
            lambda: settings_path,
        )
        monkeypatch.setattr("server.tools.perms_grant._USER_SETTINGS", settings_path)

        original_content = settings_path.read_text()
        result = run_sync(meta, cfg, apply=False)

        # Must report missing rules
        assert "❌" in result
        # settings.json content must be unchanged
        assert settings_path.read_text() == original_content


# ── MCP tool integration ──────────────────────────────────────────────────────


class TestProjPermsSyncTool:
    @pytest.mark.anyio
    async def test_tool_registered(self, mcp_app) -> None:  # type: ignore[no-untyped-def]
        from tests.conftest import call_tool

        # With no active project the tool should return a helpful message
        result = await call_tool(mcp_app, "proj_perms_sync")
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.anyio
    async def test_tool_no_active_project(self, cfg: ProjConfig, mcp_app) -> None:  # type: ignore[no-untyped-def]
        from tests.conftest import call_tool

        result = await call_tool(mcp_app, "proj_perms_sync")
        assert "No active project" in result

    @pytest.mark.anyio
    async def test_tool_with_project(
        self,
        cfg: ProjConfig,
        tmp_path: Path,
        mcp_app,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:  # type: ignore[no-untyped-def]
        from server.lib import state
        from tests.conftest import call_tool, setup_project

        repo_path = str(tmp_path / "myrepo")
        setup_project(cfg, "myproject", repo_path)
        state.set_session_active("myproject")

        # Point settings to a file that has all expected rules
        meta = storage.load_meta(cfg, "myproject")
        expected = _derive_expected_rules(meta, cfg)
        settings_path = _write_settings(tmp_path, allow=sorted(expected))
        monkeypatch.setattr(
            "server.tools.perms_sync._settings_path",
            lambda: settings_path,
        )

        result = await call_tool(mcp_app, "proj_perms_sync")
        assert "✅" in result

    @pytest.mark.anyio
    async def test_tool_unknown_project_name(self, cfg: ProjConfig, mcp_app) -> None:  # type: ignore[no-untyped-def]
        from tests.conftest import call_tool

        result = await call_tool(mcp_app, "proj_perms_sync", project_name="ghost")
        assert "not found" in result

    @pytest.mark.anyio
    async def test_proj_perms_sync_apply_true_writes_rules(
        self,
        cfg: ProjConfig,
        tmp_path: Path,
        mcp_app,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:  # type: ignore[no-untyped-def]
        """apply=True via the MCP tool writes missing rules into settings.json."""
        from server.lib import state
        from tests.conftest import call_tool, setup_project

        repo_path = str(tmp_path / "myrepo")
        setup_project(cfg, "myproject", repo_path)
        state.set_session_active("myproject")

        # Start with an empty settings.json
        settings_path = _write_settings(tmp_path, allow=[])
        monkeypatch.setattr(
            "server.tools.perms_sync._settings_path",
            lambda: settings_path,
        )
        monkeypatch.setattr("server.tools.perms_grant._USER_SETTINGS", settings_path)

        result = await call_tool(mcp_app, "proj_perms_sync", apply=True)

        # Tool must report success, not a "❌ Missing" report
        assert "✅" in result
        assert "❌ Missing" not in result

        # settings.json must now contain the expected path rules
        actual = json.loads(settings_path.read_text())
        allow_set = set(actual.get("permissions", {}).get("allow", []))
        prefix = f"//{repo_path.strip('/')}"
        assert f"Read({prefix}/**)" in allow_set
        assert f"Edit({prefix}/**)" in allow_set


# ── Sandbox mode tests ────────────────────────────────────────────────────────


def _write_local_settings(path: Path, data: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return path


class TestSandboxDetection:
    def test_is_sandbox_enabled_true(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from server.tools.perms_sync import _is_sandbox_enabled

        local_path = tmp_path / ".claude" / "settings.local.json"
        _write_local_settings(local_path, {"sandbox": {"enabled": True}})
        monkeypatch.setattr(
            "server.tools.perms_sync._local_settings_path",
            lambda: local_path,
        )
        assert _is_sandbox_enabled() is True

    def test_is_sandbox_enabled_false(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from server.tools.perms_sync import _is_sandbox_enabled

        monkeypatch.setattr(
            "server.tools.perms_sync._local_settings_path",
            lambda: tmp_path / "nonexistent.json",
        )
        assert _is_sandbox_enabled() is False

    def test_is_sandbox_enabled_project_level_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sandbox enabled at project level but not user level is detected."""
        from server.tools.perms_sync import _is_sandbox_enabled

        # User-level settings.local.json does not exist
        monkeypatch.setattr(
            "server.tools.perms_sync._local_settings_path",
            lambda: tmp_path / "nonexistent.json",
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
        from server.tools.perms_sync import _is_sandbox_enabled

        user_local = tmp_path / "user" / ".claude" / "settings.local.json"
        _write_local_settings(user_local, {"sandbox": {"enabled": False}})
        monkeypatch.setattr(
            "server.tools.perms_sync._local_settings_path",
            lambda: user_local,
        )

        project_dir = tmp_path / "myproject"
        proj_local = project_dir / ".claude" / "settings.local.json"
        _write_local_settings(proj_local, {"sandbox": {"enabled": True}})

        assert _is_sandbox_enabled(project_dir) is True

    def test_is_sandbox_enabled_both_false(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When both user-level and project-level sandbox are disabled, returns False."""
        from server.tools.perms_sync import _is_sandbox_enabled

        user_local = tmp_path / "user" / ".claude" / "settings.local.json"
        _write_local_settings(user_local, {"sandbox": {"enabled": False}})
        monkeypatch.setattr(
            "server.tools.perms_sync._local_settings_path",
            lambda: user_local,
        )

        project_dir = tmp_path / "myproject"
        proj_local = project_dir / ".claude" / "settings.local.json"
        _write_local_settings(proj_local, {"sandbox": {"enabled": False}})

        assert _is_sandbox_enabled(project_dir) is False


class TestLoadActualRulesSandbox:
    def test_reads_from_local_when_sandbox_enabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        local_path = tmp_path / ".claude" / "settings.local.json"
        _write_local_settings(local_path, {
            "sandbox": {"enabled": True},
            "permissions": {"allow": ["mcp__proj__*"]},
        })
        monkeypatch.setattr(
            "server.tools.perms_sync._local_settings_path",
            lambda: local_path,
        )
        monkeypatch.setattr(
            "server.tools.perms_sync._settings_path",
            lambda: tmp_path / "settings.json",
        )

        result = _load_actual_rules()
        assert "mcp__proj__*" in result


class TestDeriveExpectedSandboxPaths:
    def test_writable_repo_paths_included(self) -> None:
        from server.tools.perms_sync import _derive_expected_sandbox_paths

        meta = _make_meta(repos=[
            RepoEntry(label="code", path="/home/user/proj"),
            RepoEntry(label="docs", path="/home/user/docs", reference=True),
        ])
        cfg = _make_cfg(tracking_dir="/tmp/tracking")

        paths = _derive_expected_sandbox_paths(meta, cfg)

        assert "/home/user/proj" in paths
        assert "/home/user/docs" not in paths  # reference repo excluded
        assert "/tmp/tracking" in paths


class TestRunSyncSandbox:
    def test_in_sync_sandbox_mode(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=True, todoist_enabled=False, tracking_dir="/tmp/tracking")
        expected = _derive_expected_rules(meta, cfg)

        local_path = tmp_path / ".claude" / "settings.local.json"
        _write_local_settings(local_path, {
            "sandbox": {
                "enabled": True,
                "filesystem": {"allowWrite": ["/home/user/proj", "/tmp/tracking"]},
            },
            "permissions": {"allow": sorted(expected)},
        })
        monkeypatch.setattr(
            "server.tools.perms_sync._local_settings_path",
            lambda: local_path,
        )
        monkeypatch.setattr(
            "server.tools.perms_sync._settings_path",
            lambda: tmp_path / "settings.json",
        )

        result = run_sync(meta, cfg)

        assert "settings.local.json" in result
        assert "in sync" in result

    def test_missing_sandbox_paths_reported(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=True, todoist_enabled=False)
        expected = _derive_expected_rules(meta, cfg)

        local_path = tmp_path / ".claude" / "settings.local.json"
        # All permission rules present but sandbox.filesystem.allowWrite is empty
        _write_local_settings(local_path, {
            "sandbox": {"enabled": True},
            "permissions": {"allow": sorted(expected)},
        })
        monkeypatch.setattr(
            "server.tools.perms_sync._local_settings_path",
            lambda: local_path,
        )
        monkeypatch.setattr(
            "server.tools.perms_sync._settings_path",
            lambda: tmp_path / "settings.json",
        )

        result = run_sync(meta, cfg)

        assert "❌" in result
        assert "sandbox allowWrite" in result.lower() or "Sandbox allowWrite" in result
        assert "/home/user/proj" in result

    def test_missing_rules_in_sandbox_mode_reported(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=False)

        local_path = tmp_path / ".claude" / "settings.local.json"
        _write_local_settings(local_path, {
            "sandbox": {"enabled": True},
            "permissions": {"allow": []},
        })
        monkeypatch.setattr(
            "server.tools.perms_sync._local_settings_path",
            lambda: local_path,
        )
        monkeypatch.setattr(
            "server.tools.perms_sync._settings_path",
            lambda: tmp_path / "settings.json",
        )

        result = run_sync(meta, cfg)

        assert "❌" in result
        assert "settings.local.json" in result
        assert "Read(//home/user/proj/**)" in result
