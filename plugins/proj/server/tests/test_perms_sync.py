"""Tests for proj_perms_sync MCP tool."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from server.lib import storage
from server.lib.models import (
    JiraSync,
    PermissionsConfig,
    ProjConfig,
    ProjectDates,
    ProjectEntry,
    ProjectMeta,
    RepoEntry,
    TodoistSync,
    TrelloSync,
)
from server.tools.perms_sync import _derive_expected_rules, run_sync


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_cfg(
    auto_allow_mcps: bool = True,
    todoist_enabled: bool = False,
    jira_enabled: bool = False,
    trello_enabled: bool = False,
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
    cfg.jira = JiraSync(enabled=jira_enabled)
    cfg.trello = TrelloSync(enabled=trello_enabled)
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
    def test_two_repos_only_mcp_rules_returned(self) -> None:
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

        # Only global Claude.ai MCP rules expected (no Read/Edit/Bash rules)
        expected = {
            "mcp__claude_ai_Excalidraw__*",
            "mcp__claude_ai_Mermaid_Chart__*",
        }
        assert rules == expected
        # No Read/Edit/Bash rules
        assert not any(r.startswith("Read(") or r.startswith("Edit(") or r.startswith("Bash(") for r in rules)

    def test_auto_allow_mcps_true_adds_mcp_rules(self) -> None:
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(
            auto_allow_mcps=True,
            todoist_enabled=False,
            perms_integration=True,
            worktree_integration=True,
        )

        rules = _derive_expected_rules(meta, cfg)

        assert "mcp__plugin_proj_proj__*" in rules
        assert "mcp__plugin_perms_perms__*" in rules
        assert "mcp__plugin_worktree_worktree__*" in rules
        assert "mcp__todoist__*" not in rules

    def test_todoist_enabled_adds_todoist_mcp_rule(self) -> None:
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=True, todoist_enabled=True)

        rules = _derive_expected_rules(meta, cfg)

        assert "mcp__todoist__*" in rules

    def test_jira_enabled_adds_jira_mcp_rule(self) -> None:
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=True, jira_enabled=True)

        rules = _derive_expected_rules(meta, cfg)

        assert "mcp__plugin_jira_jira__*" in rules

    def test_jira_disabled_no_jira_mcp_rule(self) -> None:
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=True, jira_enabled=False)

        rules = _derive_expected_rules(meta, cfg)

        assert "mcp__plugin_jira_jira__*" not in rules

    def test_trello_enabled_adds_trello_mcp_rule(self) -> None:
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=True, trello_enabled=True)

        rules = _derive_expected_rules(meta, cfg)

        assert "mcp__plugin_trello_trello__*" in rules

    def test_trello_disabled_no_trello_mcp_rule(self) -> None:
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=True, trello_enabled=False)

        rules = _derive_expected_rules(meta, cfg)

        assert "mcp__plugin_trello_trello__*" not in rules

    def test_auto_allow_mcps_false_no_plugin_mcp_rules(self) -> None:
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(
            auto_allow_mcps=False,
            todoist_enabled=True,
            jira_enabled=True,
            trello_enabled=True,
            perms_integration=True,
            worktree_integration=True,
        )

        rules = _derive_expected_rules(meta, cfg)

        # All plugin MCP servers are excluded when auto_allow_mcps=False
        assert "mcp__plugin_proj_proj__*" not in rules
        assert "mcp__plugin_perms_perms__*" not in rules
        assert "mcp__plugin_worktree_worktree__*" not in rules
        assert "mcp__todoist__*" not in rules
        assert "mcp__plugin_jira_jira__*" not in rules
        assert "mcp__plugin_trello_trello__*" not in rules
        # Global Claude.ai servers are always present regardless
        assert "mcp__claude_ai_Excalidraw__*" in rules
        assert "mcp__claude_ai_Mermaid_Chart__*" in rules

    def test_no_path_rules_regardless_of_trailing_slash(self) -> None:
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj/")])
        cfg = _make_cfg(auto_allow_mcps=False)

        rules = _derive_expected_rules(meta, cfg)

        # No Read/Edit rules — only MCP rules
        assert not any(r.startswith("Read(") or r.startswith("Edit(") for r in rules)
        assert "mcp__claude_ai_Excalidraw__*" in rules
        assert "mcp__claude_ai_Mermaid_Chart__*" in rules

    def test_no_repos_auto_allow_only_mcp_rules(self) -> None:
        meta = _make_meta(repos=[])
        cfg = _make_cfg(auto_allow_mcps=True)

        rules = _derive_expected_rules(meta, cfg)

        # MCP rules always present
        assert "mcp__plugin_proj_proj__*" in rules
        assert "mcp__claude_ai_Excalidraw__*" in rules
        assert "mcp__claude_ai_Mermaid_Chart__*" in rules
        # No Bash rules — only MCP rules now
        assert not any(r.startswith("Bash(") for r in rules)

    def test_no_repos_auto_allow_with_integrations(self) -> None:
        meta = _make_meta(repos=[])
        cfg = _make_cfg(
            auto_allow_mcps=True, perms_integration=True, worktree_integration=True
        )

        rules = _derive_expected_rules(meta, cfg)

        assert "mcp__plugin_proj_proj__*" in rules
        assert "mcp__plugin_perms_perms__*" in rules
        assert "mcp__plugin_worktree_worktree__*" in rules
        assert "mcp__claude_ai_Excalidraw__*" in rules
        assert "mcp__claude_ai_Mermaid_Chart__*" in rules

    def test_perms_integration_only_adds_perms_mcp_rule(self) -> None:
        meta = _make_meta(repos=[])
        cfg = _make_cfg(auto_allow_mcps=True, perms_integration=True, worktree_integration=False)

        rules = _derive_expected_rules(meta, cfg)

        assert "mcp__plugin_perms_perms__*" in rules
        assert "mcp__plugin_worktree_worktree__*" not in rules

    def test_worktree_integration_only_adds_worktree_mcp_rule(self) -> None:
        meta = _make_meta(repos=[])
        cfg = _make_cfg(auto_allow_mcps=True, perms_integration=False, worktree_integration=True)

        rules = _derive_expected_rules(meta, cfg)

        assert "mcp__plugin_worktree_worktree__*" in rules
        assert "mcp__plugin_perms_perms__*" not in rules

    def test_no_repos_no_mcps_only_global_mcp_rules(self) -> None:
        meta = _make_meta(repos=[])
        cfg = _make_cfg(auto_allow_mcps=False)

        rules = _derive_expected_rules(meta, cfg)

        # Only global Claude.ai MCP rules
        assert rules == {"mcp__claude_ai_Excalidraw__*", "mcp__claude_ai_Mermaid_Chart__*"}
        # No Read/Edit/Bash rules
        assert not any(r.startswith(("Read(", "Edit(", "Bash(")) for r in rules)

    def test_worktree_integration_false_no_path_rules(self) -> None:
        """_derive_expected_rules returns only MCP rules, not path rules."""
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=False, worktree_integration=False)

        rules = _derive_expected_rules(meta, cfg)

        # Only global MCP rules — no path rules of any kind
        assert not any(r.startswith(("Read(", "Edit(", "Bash(")) for r in rules)
        assert "mcp__claude_ai_Excalidraw__*" in rules

    def test_worktree_integration_true_no_path_rules(self) -> None:
        """_derive_expected_rules returns only MCP rules, even with worktree_integration=True."""
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=False, worktree_integration=True)

        rules = _derive_expected_rules(meta, cfg)

        # Only MCP rules — no path or Bash rules
        assert not any(r.startswith(("Read(", "Edit(", "Bash(")) for r in rules)
        # worktree MCP rule present (auto_allow_mcps=False, so no plugin MCPs)
        assert "mcp__claude_ai_Excalidraw__*" in rules


# ── _derive_expected_rules — custom mcp_server ────────────────────────────────


class TestDeriveExpectedRulesCustomServer:
    def test_todoist_enabled_always_emits_fixed_rule(self) -> None:
        """Todoist always uses fixed mcp__todoist__* rule regardless of config mcp_server."""
        cfg = _make_cfg(auto_allow_mcps=True, todoist_enabled=True)
        cfg.todoist.mcp_server = "sentry"  # config value ignored
        meta = _make_meta(repos=[])

        rules = _derive_expected_rules(meta, cfg)

        assert "mcp__todoist__*" in rules
        assert "mcp__sentry__*" not in rules

    def test_todoist_default_mcp_server_emits_fixed_rule(self) -> None:
        cfg = _make_cfg(auto_allow_mcps=True, todoist_enabled=True)
        meta = _make_meta(repos=[])

        rules = _derive_expected_rules(meta, cfg)

        assert "mcp__todoist__*" in rules

    def test_todoist_disabled_emits_no_rule(self) -> None:
        cfg = _make_cfg(auto_allow_mcps=True, todoist_enabled=False)
        cfg.todoist.mcp_server = "sentry"
        meta = _make_meta(repos=[])

        rules = _derive_expected_rules(meta, cfg)

        assert "mcp__todoist__*" not in rules
        assert "mcp__sentry__*" not in rules


# ── run_sync ──────────────────────────────────────────────────────────────────


class TestRunSync:
    def test_all_rules_present_returns_in_sync(self) -> None:
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=True, todoist_enabled=False)
        expected = _derive_expected_rules(meta, cfg)

        result = run_sync(
            meta, cfg,
            actual_rules=expected,
            actual_sandbox_paths=set(),
            sandbox_mode=False,
        )

        assert "✅" in result
        assert "in sync" in result

    def test_missing_mcp_rules_only_reported(self) -> None:
        """With auto_allow_mcps=False, only global MCP rules are expected and reported missing."""
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=False)

        result = run_sync(
            meta, cfg,
            actual_rules=set(),
            actual_sandbox_paths=set(),
            sandbox_mode=False,
        )

        assert "❌" in result
        assert "MCP rules" in result
        assert "mcp__claude_ai_Excalidraw__*" in result
        assert "Read(" not in result
        assert "Edit(" not in result

    def test_missing_mcp_rules_reported(self) -> None:
        meta = _make_meta(repos=[])
        cfg = _make_cfg(
            auto_allow_mcps=True,
            todoist_enabled=False,
            perms_integration=True,
            worktree_integration=True,
        )

        result = run_sync(
            meta, cfg,
            actual_rules=set(),
            actual_sandbox_paths=set(),
            sandbox_mode=False,
        )

        assert "❌" in result
        assert "mcp__plugin_proj_proj__*" in result
        assert "MCP rules" in result

    def test_extras_in_actual_are_ignored(self) -> None:
        """Extra rules in settings.json beyond what's expected are fine."""
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=True, todoist_enabled=False)
        expected = _derive_expected_rules(meta, cfg)
        actual = expected | {"Read(//some/other/path/**)", "mcp__custom__*"}

        result = run_sync(
            meta, cfg,
            actual_rules=actual,
            actual_sandbox_paths=set(),
            sandbox_mode=False,
        )

        assert "✅" in result

    def test_missing_rules_suggest_perms_add(self) -> None:
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=False)

        result = run_sync(
            meta, cfg,
            actual_rules=set(),
            actual_sandbox_paths=set(),
            sandbox_mode=False,
        )

        assert "perms_add_mcp_allow" in result

    def test_todoist_rule_appears_when_enabled(self) -> None:
        meta = _make_meta(repos=[])
        cfg = _make_cfg(auto_allow_mcps=True, todoist_enabled=True)

        result = run_sync(
            meta, cfg,
            actual_rules=set(),
            actual_sandbox_paths=set(),
            sandbox_mode=False,
        )

        assert "mcp__todoist__*" in result

    def test_perms_integration_false_mcp_perms_not_reported_missing(self) -> None:
        """When perms_integration=False, mcp__perms__* is not expected so it is not reported missing."""
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=True, perms_integration=False, worktree_integration=False)
        expected = _derive_expected_rules(meta, cfg)
        assert "mcp__plugin_perms_perms__*" not in expected

        result = run_sync(
            meta, cfg,
            actual_rules=expected,
            actual_sandbox_paths=set(),
            sandbox_mode=False,
        )

        assert "✅" in result
        assert "in sync" in result

    def test_worktree_integration_false_in_sync_without_worktree_bash_rules(self) -> None:
        """When worktree_integration=False, Bash rules for worktree-only paths are not expected."""
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=False, worktree_integration=False)
        expected = _derive_expected_rules(meta, cfg)

        result = run_sync(
            meta, cfg,
            actual_rules=expected,
            actual_sandbox_paths=set(),
            sandbox_mode=False,
        )

        assert "✅" in result
        assert "in sync" in result

    def test_partial_mcp_rules_present_reports_only_missing(self) -> None:
        """When some MCP rules are present but others missing, only missing ones are reported."""
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=False)

        result = run_sync(
            meta, cfg,
            actual_rules={"mcp__claude_ai_Excalidraw__*"},
            actual_sandbox_paths=set(),
            sandbox_mode=False,
        )

        assert "❌" in result
        assert "mcp__claude_ai_Mermaid_Chart__*" in result
        assert "mcp__claude_ai_Excalidraw__*" not in result

    def test_worktree_integration_true_no_bash_rules_expected(self) -> None:
        """Bash rules are no longer expected in permissions.allow, even with worktree_integration=True."""
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=False, worktree_integration=True)
        expected = _derive_expected_rules(meta, cfg)

        result = run_sync(
            meta, cfg,
            actual_rules=expected,
            actual_sandbox_paths=set(),
            sandbox_mode=False,
        )

        assert "✅" in result
        assert "in sync" in result

    def test_run_sync_reports_fixed_todoist_rule_regardless_of_config(self) -> None:
        """Custom mcp_server config is ignored — always uses fixed mcp__todoist__* rule."""
        meta = _make_meta(repos=[])
        cfg = _make_cfg(auto_allow_mcps=True, todoist_enabled=True)
        cfg.todoist.mcp_server = "sentry"  # ignored

        result = run_sync(
            meta, cfg,
            actual_rules=set(),
            actual_sandbox_paths=set(),
            sandbox_mode=False,
        )

        assert "mcp__todoist__*" in result
        assert "mcp__sentry__*" not in result

    def test_apply_true_writes_missing_mcp_rules(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """apply=True writes missing MCP rules and returns a success message."""
        repo_path = str(tmp_path / "myrepo")
        meta = _make_meta(repos=[RepoEntry(label="code", path=repo_path)])
        cfg = _make_cfg(auto_allow_mcps=False)
        settings_path = _write_settings(tmp_path, allow=[])
        monkeypatch.setattr("server.lib.perms_helpers._USER_SETTINGS", settings_path)
        monkeypatch.setattr("server.tools.perms_grant._USER_SETTINGS", settings_path)
        monkeypatch.setattr("server.tools.perms_grant._USER_LOCAL_SETTINGS", tmp_path / "nonexistent.json")

        result = run_sync(
            meta, cfg,
            actual_rules=set(),
            actual_sandbox_paths=set(),
            sandbox_mode=False,
            apply=True,
        )

        assert "✅" in result
        assert "❌" not in result

    def test_apply_true_forwards_batch_setup_fn(self) -> None:
        """apply=True forwards batch_setup_fn to setup_permissions."""
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=False)

        def fake_batch_setup(paths: list[str], mcp_servers: list[str]) -> str:
            return "Sandbox paths added: 1. MCP rules added: 2."

        result = run_sync(
            meta, cfg,
            actual_rules=set(),
            actual_sandbox_paths=set(),
            sandbox_mode=False,
            apply=True,
            batch_setup_fn=fake_batch_setup,
        )

        assert "✅" in result
        assert "Applied" in result

    def test_apply_true_already_in_sync_is_noop(self) -> None:
        """apply=True with all rules already present returns in-sync message."""
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=True, todoist_enabled=False)
        expected = _derive_expected_rules(meta, cfg)

        result = run_sync(
            meta, cfg,
            actual_rules=expected,
            actual_sandbox_paths=set(),
            sandbox_mode=False,
            apply=True,
        )

        assert "✅" in result
        assert "in sync" in result

    def test_apply_false_does_not_write(self) -> None:
        """apply=False (default) reports missing rules but does NOT modify anything."""
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=False)

        result = run_sync(
            meta, cfg,
            actual_rules=set(),
            actual_sandbox_paths=set(),
            sandbox_mode=False,
            apply=False,
        )

        assert "❌" in result

    def test_empty_actual_rules_reports_all_missing(self) -> None:
        """Empty actual_rules means all expected rules are reported missing."""
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=True)

        result = run_sync(
            meta, cfg,
            actual_rules=set(),
            actual_sandbox_paths=set(),
            sandbox_mode=False,
        )

        assert "❌" in result
        assert "mcp__plugin_proj_proj__*" in result

    def test_sandbox_mode_false_ignores_sandbox_paths(self) -> None:
        """When sandbox_mode=False, actual_sandbox_paths are ignored."""
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=True, todoist_enabled=False)
        expected = _derive_expected_rules(meta, cfg)

        result = run_sync(
            meta, cfg,
            actual_rules=expected,
            actual_sandbox_paths=set(),
            sandbox_mode=False,
        )

        assert "✅" in result
        assert "Sandbox" not in result


# ── MCP tool integration ──────────────────────────────────────────────────────


class TestProjPermsSyncTool:
    @pytest.mark.anyio
    async def test_tool_registered(self, mcp_app) -> None:  # type: ignore[no-untyped-def]
        from tests.conftest import call_tool

        # Without actual_rules the tool should return an error
        result = await call_tool(mcp_app, "proj_perms_sync")
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.anyio
    async def test_tool_missing_actual_rules_returns_error(self, cfg: ProjConfig, mcp_app) -> None:  # type: ignore[no-untyped-def]
        from tests.conftest import call_tool

        result = await call_tool(mcp_app, "proj_perms_sync")
        assert "actual_rules" in result.lower() or "required" in result.lower()

    @pytest.mark.anyio
    async def test_tool_no_active_project(self, cfg: ProjConfig, mcp_app) -> None:  # type: ignore[no-untyped-def]
        from tests.conftest import call_tool

        result = await call_tool(mcp_app, "proj_perms_sync", actual_rules=[])
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

        meta = storage.load_meta(cfg, "myproject")
        expected = _derive_expected_rules(meta, cfg)

        result = await call_tool(
            mcp_app, "proj_perms_sync",
            actual_rules=sorted(expected),
            actual_sandbox_paths=[],
            sandbox_mode=False,
        )
        assert "✅" in result

    @pytest.mark.anyio
    async def test_tool_unknown_project_name(self, cfg: ProjConfig, mcp_app) -> None:  # type: ignore[no-untyped-def]
        from tests.conftest import call_tool

        result = await call_tool(
            mcp_app, "proj_perms_sync",
            project_name="ghost",
            actual_rules=[],
        )
        assert "not found" in result

    @pytest.mark.anyio
    async def test_proj_perms_sync_apply_true_writes_rules(
        self,
        cfg: ProjConfig,
        tmp_path: Path,
        mcp_app,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:  # type: ignore[no-untyped-def]
        """apply=True via the MCP tool writes missing rules."""
        from server.lib import state
        from tests.conftest import call_tool, setup_project

        repo_path = str(tmp_path / "myrepo")
        setup_project(cfg, "myproject", repo_path)
        state.set_session_active("myproject")

        settings_path = _write_settings(tmp_path, allow=[])
        monkeypatch.setattr("server.lib.perms_helpers._USER_SETTINGS", settings_path)
        monkeypatch.setattr("server.tools.perms_grant._USER_SETTINGS", settings_path)
        monkeypatch.setattr("server.tools.perms_grant._USER_LOCAL_SETTINGS", tmp_path / "nonexistent.json")

        result = await call_tool(
            mcp_app, "proj_perms_sync",
            apply=True,
            actual_rules=[],
            actual_sandbox_paths=[],
            sandbox_mode=False,
        )

        assert "✅" in result
        assert "❌ Missing" not in result


# ── Sandbox mode tests ────────────────────────────────────────────────────────


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
    def test_in_sync_sandbox_mode(self) -> None:
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=True, todoist_enabled=False, tracking_dir="/tmp/tracking")
        expected = _derive_expected_rules(meta, cfg)

        result = run_sync(
            meta, cfg,
            actual_rules=expected,
            actual_sandbox_paths={"/home/user/proj", "/tmp/tracking"},
            sandbox_mode=True,
        )

        assert "settings.local.json" in result
        assert "in sync" in result

    def test_missing_sandbox_paths_reported(self) -> None:
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=True, todoist_enabled=False)
        expected = _derive_expected_rules(meta, cfg)

        result = run_sync(
            meta, cfg,
            actual_rules=expected,
            actual_sandbox_paths=set(),
            sandbox_mode=True,
        )

        assert "❌" in result
        assert "sandbox allowWrite" in result.lower() or "Sandbox allowWrite" in result
        assert "/home/user/proj" in result

    def test_missing_rules_in_sandbox_mode_reported(self) -> None:
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=False)

        result = run_sync(
            meta, cfg,
            actual_rules=set(),
            actual_sandbox_paths=set(),
            sandbox_mode=True,
        )

        assert "❌" in result
        assert "settings.local.json" in result
        assert "MCP rules" in result or "Sandbox allowWrite" in result
        assert "Read(" not in result
