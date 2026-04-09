"""Tests for proj_perms_sync MCP tool."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from server.lib import storage
from server.lib.models import (
    JiraSync,
    PermissionsConfig,
    ProjConfig,
    ProjectDates,
    ProjectMeta,
    RepoEntry,
    TodoistSync,
    TrelloSync,
)
from server.tools._perms_common import (
    derive_mcp_rules,
    derive_skill_prefixes,
    derive_write_paths,
)
from server.tools.perms_sync import (
    run_sync,
)

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_cfg(
    auto_allow_mcps: bool = True,
    todoist_enabled: bool = False,
    jira_enabled: bool = False,
    trello_enabled: bool = False,
    tracking_dir: str = "/tmp/tracking",
    sandbox_integration: bool = False,
    worktree_integration: bool = False,
    projects_root: str | None = None,
    tracking_root: str | None = None,
) -> ProjConfig:
    cfg = ProjConfig(
        tracking_dir=tracking_dir,
        sandbox_integration=sandbox_integration,
        worktree_integration=worktree_integration,
    )
    cfg.permissions = PermissionsConfig(
        auto_grant=True,
        auto_allow_mcps=auto_allow_mcps,
        projects_root=projects_root,
        tracking_root=tracking_root,
    )
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


# ── derive_mcp_rules ────────────────────────────────────────────────────


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

        rules = derive_mcp_rules(meta, cfg)

        # Only global Claude.ai MCP rules expected (no Read/Edit/Bash rules)
        expected = {
            "mcp__claude_ai_Excalidraw__*",
            "mcp__claude_ai_Mermaid_Chart__*",
        }
        assert rules == expected
        # No Read/Edit/Bash rules
        assert not any(
            r.startswith("Read(") or r.startswith("Edit(") or r.startswith("Bash(") for r in rules
        )

    def test_auto_allow_mcps_true_adds_mcp_rules(self) -> None:
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(
            auto_allow_mcps=True,
            todoist_enabled=False,
            sandbox_integration=True,
            worktree_integration=True,
        )

        rules = derive_mcp_rules(meta, cfg)

        assert "mcp__plugin_proj_proj__*" in rules
        assert "mcp__plugin_sandbox_sandbox__*" in rules
        assert "mcp__plugin_worktree_worktree__*" in rules
        assert "mcp__todoist__*" not in rules

    def test_integration_enabled_adds_mcp_rules(self) -> None:
        """Each integration flag adds its MCP rule when enabled."""
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(
            auto_allow_mcps=True,
            todoist_enabled=True,
            jira_enabled=True,
            trello_enabled=True,
        )

        rules = derive_mcp_rules(meta, cfg)

        assert "mcp__todoist__*" in rules
        assert "mcp__plugin_jira_jira__*" in rules
        assert "mcp__plugin_trello_trello__*" in rules

    def test_integration_disabled_excludes_mcp_rules(self) -> None:
        """Disabled integrations do not add MCP rules."""
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(
            auto_allow_mcps=True,
            todoist_enabled=False,
            jira_enabled=False,
            trello_enabled=False,
        )

        rules = derive_mcp_rules(meta, cfg)

        assert "mcp__todoist__*" not in rules
        assert "mcp__plugin_jira_jira__*" not in rules
        assert "mcp__plugin_trello_trello__*" not in rules

    def test_auto_allow_mcps_false_no_plugin_mcp_rules(self) -> None:
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(
            auto_allow_mcps=False,
            todoist_enabled=True,
            jira_enabled=True,
            trello_enabled=True,
            sandbox_integration=True,
            worktree_integration=True,
        )

        rules = derive_mcp_rules(meta, cfg)

        # All plugin MCP servers are excluded when auto_allow_mcps=False
        assert "mcp__plugin_proj_proj__*" not in rules
        assert "mcp__plugin_sandbox_sandbox__*" not in rules
        assert "mcp__plugin_worktree_worktree__*" not in rules
        assert "mcp__todoist__*" not in rules
        assert "mcp__plugin_jira_jira__*" not in rules
        assert "mcp__plugin_trello_trello__*" not in rules
        # Global Claude.ai servers are always present regardless
        assert "mcp__claude_ai_Excalidraw__*" in rules
        assert "mcp__claude_ai_Mermaid_Chart__*" in rules

    def test_no_repos_auto_allow_only_mcp_rules(self) -> None:
        meta = _make_meta(repos=[])
        cfg = _make_cfg(auto_allow_mcps=True, sandbox_integration=True, worktree_integration=True)

        rules = derive_mcp_rules(meta, cfg)

        assert "mcp__plugin_proj_proj__*" in rules
        assert "mcp__plugin_sandbox_sandbox__*" in rules
        assert "mcp__plugin_worktree_worktree__*" in rules
        assert "mcp__claude_ai_Excalidraw__*" in rules
        assert "mcp__claude_ai_Mermaid_Chart__*" in rules
        assert not any(r.startswith(("Read(", "Edit(", "Bash(")) for r in rules)

    def test_sandbox_integration_only_adds_perms_mcp_rule(self) -> None:
        meta = _make_meta(repos=[])
        cfg = _make_cfg(auto_allow_mcps=True, sandbox_integration=True, worktree_integration=False)

        rules = derive_mcp_rules(meta, cfg)

        assert "mcp__plugin_sandbox_sandbox__*" in rules
        assert "mcp__plugin_worktree_worktree__*" not in rules

    def test_worktree_integration_only_adds_worktree_mcp_rule(self) -> None:
        meta = _make_meta(repos=[])
        cfg = _make_cfg(auto_allow_mcps=True, sandbox_integration=False, worktree_integration=True)

        rules = derive_mcp_rules(meta, cfg)

        assert "mcp__plugin_worktree_worktree__*" in rules
        assert "mcp__plugin_sandbox_sandbox__*" not in rules


# ── derive_mcp_rules — custom mcp_server ────────────────────────────────


class TestDeriveExpectedRulesCustomServer:
    def test_todoist_enabled_always_emits_fixed_rule(self) -> None:
        """Todoist always uses fixed mcp__todoist__* rule regardless of config mcp_server."""
        cfg = _make_cfg(auto_allow_mcps=True, todoist_enabled=True)
        cfg.todoist.mcp_server = "sentry"  # config value ignored
        meta = _make_meta(repos=[])

        rules = derive_mcp_rules(meta, cfg)

        assert "mcp__todoist__*" in rules
        assert "mcp__sentry__*" not in rules


# ── run_sync ──────────────────────────────────────────────────────────────────


class TestRunSync:
    def test_all_rules_present_returns_in_sync(self) -> None:
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=True, todoist_enabled=False)
        expected = derive_mcp_rules(meta, cfg)

        result = run_sync(
            meta,
            cfg,
            actual_rules=expected,
            actual_sandbox_paths=set(),
            sandbox_mode=False,
        )

        assert "✅" in result
        assert "in sync" in result

    def test_missing_mcp_rules_reported(self) -> None:
        """Missing MCP rules are reported with category header; no Read/Edit rules."""
        meta = _make_meta(repos=[])
        cfg = _make_cfg(
            auto_allow_mcps=True,
            todoist_enabled=False,
            sandbox_integration=True,
            worktree_integration=True,
        )

        result = run_sync(
            meta,
            cfg,
            actual_rules=set(),
            actual_sandbox_paths=set(),
            sandbox_mode=False,
        )

        assert "❌" in result
        assert "mcp__plugin_proj_proj__*" in result
        assert "MCP rules" in result
        assert "Read(" not in result
        assert "Edit(" not in result

    def test_extras_in_actual_are_ignored(self) -> None:
        """Extra rules in settings.json beyond what's expected are fine."""
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=True, todoist_enabled=False)
        expected = derive_mcp_rules(meta, cfg)
        actual = expected | {"Read(//some/other/path/**)", "mcp__custom__*"}

        result = run_sync(
            meta,
            cfg,
            actual_rules=actual,
            actual_sandbox_paths=set(),
            sandbox_mode=False,
        )

        assert "✅" in result

    def test_missing_rules_suggest_perms_add(self) -> None:
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=False)

        result = run_sync(
            meta,
            cfg,
            actual_rules=set(),
            actual_sandbox_paths=set(),
            sandbox_mode=False,
        )

        assert "sandbox_add_mcp_allow" in result

    def test_partial_mcp_rules_present_reports_only_missing(self) -> None:
        """When some MCP rules are present but others missing, only missing ones are reported."""
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=False)

        result = run_sync(
            meta,
            cfg,
            actual_rules={"mcp__claude_ai_Excalidraw__*"},
            actual_sandbox_paths=set(),
            sandbox_mode=False,
        )

        assert "❌" in result
        assert "mcp__claude_ai_Mermaid_Chart__*" in result
        assert "mcp__claude_ai_Excalidraw__*" not in result

    def test_apply_true_writes_missing_mcp_rules(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """apply=True writes missing MCP rules and returns a success message."""
        repo_path = str(tmp_path / "myrepo")
        meta = _make_meta(repos=[RepoEntry(label="code", path=repo_path)])
        cfg = _make_cfg(auto_allow_mcps=False)
        settings_path = _write_settings(tmp_path, allow=[])
        monkeypatch.setattr("server.lib.sandbox_helpers._USER_SETTINGS", settings_path)

        result = run_sync(
            meta,
            cfg,
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

        def fake_batch_setup(
            paths: list[str],
            mcp_servers: list[str],
            additional_directories: list[str] | None = None,
        ) -> str:
            return "Sandbox paths added: 1. MCP rules added: 2. Additional directories added: 1."

        result = run_sync(
            meta,
            cfg,
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
        expected = derive_mcp_rules(meta, cfg)

        result = run_sync(
            meta,
            cfg,
            actual_rules=expected,
            actual_sandbox_paths=set(),
            sandbox_mode=False,
            apply=True,
        )

        assert "✅" in result
        assert "in sync" in result

    def test_sandbox_mode_false_ignores_sandbox_paths(self) -> None:
        """When sandbox_mode=False, actual_sandbox_paths are ignored."""
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=True, todoist_enabled=False)
        expected = derive_mcp_rules(meta, cfg)

        result = run_sync(
            meta,
            cfg,
            actual_rules=expected,
            actual_sandbox_paths=set(),
            sandbox_mode=False,
        )

        assert "✅" in result
        assert "Sandbox" not in result


# ── MCP tool integration ──────────────────────────────────────────────────────


class TestProjPermsSyncTool:
    @pytest.mark.anyio
    async def test_tool_missing_actual_rules_returns_error(
        self,
        cfg: ProjConfig,
        mcp_app: FastMCP,
    ) -> None:
        from tests.conftest import call_tool

        result = await call_tool(mcp_app, "proj_perms_sync")
        # Try parsing as JSON first, fall back to string check
        try:
            data = json.loads(result)
            assert "error" in data or "required" in data.get("result", "").lower()
        except json.JSONDecodeError:
            assert "actual_rules" in result.lower() or "required" in result.lower()

    @pytest.mark.anyio
    async def test_tool_no_active_project(self, cfg: ProjConfig, mcp_app: FastMCP) -> None:
        from tests.conftest import call_tool

        result = await call_tool(mcp_app, "proj_perms_sync", actual_rules=[])
        try:
            data = json.loads(result)
            assert "No active project" in data.get("error", data.get("result", ""))
        except json.JSONDecodeError:
            assert "No active project" in result

    @pytest.mark.anyio
    async def test_tool_with_project(
        self,
        cfg: ProjConfig,
        tmp_path: Path,
        mcp_app: FastMCP,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from server.lib import state
        from tests.conftest import call_tool, setup_project

        repo_path = str(tmp_path / "myrepo")
        setup_project(cfg, "myproject", repo_path)
        state.set_session_active("myproject")

        meta = storage.load_meta(cfg, "myproject")
        expected = derive_mcp_rules(meta, cfg)

        result = await call_tool(
            mcp_app,
            "proj_perms_sync",
            actual_rules=sorted(expected),
            actual_sandbox_paths=[],
            sandbox_mode=False,
        )
        # Result should have sync status info
        try:
            data = json.loads(result)
            assert "in_sync" in data or "sync_status" in data or "result" in data
        except json.JSONDecodeError:
            assert "✅" in result

    @pytest.mark.anyio
    async def test_tool_unknown_project_name(self, cfg: ProjConfig, mcp_app: FastMCP) -> None:
        from tests.conftest import call_tool

        result = await call_tool(
            mcp_app,
            "proj_perms_sync",
            project_name="ghost",
            actual_rules=[],
        )
        try:
            data = json.loads(result)
            assert "not found" in data.get("error", data.get("result", ""))
        except json.JSONDecodeError:
            assert "not found" in result

    @pytest.mark.anyio
    async def test_proj_perms_sync_apply_true_writes_rules(
        self,
        cfg: ProjConfig,
        tmp_path: Path,
        mcp_app: FastMCP,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """apply=True via the MCP tool writes missing rules."""
        from server.lib import state
        from tests.conftest import call_tool, setup_project

        repo_path = str(tmp_path / "myrepo")
        setup_project(cfg, "myproject", repo_path)
        state.set_session_active("myproject")

        settings_path = _write_settings(tmp_path, allow=[])
        monkeypatch.setattr("server.lib.sandbox_helpers._USER_SETTINGS", settings_path)

        result = await call_tool(
            mcp_app,
            "proj_perms_sync",
            apply=True,
            actual_rules=[],
            actual_sandbox_paths=[],
            sandbox_mode=False,
        )

        try:
            data = json.loads(result)
            # Should have sync status - check for success indicators
            assert (
                "applied" in data or "sync_status" in data or "in_sync" in data or "result" in data
            )
        except json.JSONDecodeError:
            assert "✅" in result
            assert "❌ Missing" not in result


# ── Sandbox mode tests ────────────────────────────────────────────────────────


class TestDeriveExpectedSandboxPaths:
    def test_writable_repo_paths_included(self) -> None:
        meta = _make_meta(
            repos=[
                RepoEntry(label="code", path="/home/user/proj"),
                RepoEntry(label="docs", path="/home/user/docs", reference=True),
            ]
        )
        cfg = _make_cfg(tracking_dir="/tmp/tracking")

        paths = derive_write_paths(meta, cfg)

        assert "/home/user/proj" in paths
        assert "/home/user/docs" not in paths  # reference repo excluded
        assert "/tmp/tracking" in paths

    def test_derive_sandbox_paths_uses_projects_root(self) -> None:
        """When projects_root is set, returns root instead of per-repo paths."""
        meta = _make_meta(
            repos=[
                RepoEntry(label="code", path="/home/user/projects/repo-a"),
                RepoEntry(label="docs", path="/home/user/projects/repo-b"),
            ]
        )
        cfg = _make_cfg(
            tracking_dir="/tmp/tracking",
            projects_root="/home/user/projects",
        )

        paths = derive_write_paths(meta, cfg)

        assert "/home/user/projects" in paths
        # Individual repo paths should NOT be present — root replaces them
        assert "/home/user/projects/repo-a" not in paths
        assert "/home/user/projects/repo-b" not in paths
        assert "/tmp/tracking" in paths

    def test_derive_sandbox_paths_tracking_root_containment(self) -> None:
        """tracking_root under projects_root is skipped (already covered)."""
        meta = _make_meta(
            repos=[
                RepoEntry(label="code", path="/home/user/projects/repo-a"),
            ]
        )
        cfg = _make_cfg(
            tracking_dir="/tmp/tracking",
            projects_root="/home/user/projects",
            tracking_root="/home/user/projects/tracking",
        )

        paths = derive_write_paths(meta, cfg)

        assert "/home/user/projects" in paths
        # tracking_root is under projects_root, so it should be skipped
        assert "/home/user/projects/tracking" not in paths

    def test_derive_sandbox_paths_resolves_tilde(self) -> None:
        """Paths with ~ are properly resolved."""
        meta = _make_meta(
            repos=[
                RepoEntry(label="code", path="~/myproject"),
            ]
        )
        cfg = _make_cfg(tracking_dir="/tmp/tracking")

        paths = derive_write_paths(meta, cfg)

        # No path should contain a tilde
        assert not any("~" in p for p in paths)
        # The expanded home path should be present
        expanded = str(Path("~/myproject").expanduser().resolve())
        assert expanded in paths

    def test_derive_sandbox_paths_resolves_relative(self) -> None:
        """Paths with .. are resolved to absolute form."""
        meta = _make_meta(
            repos=[
                RepoEntry(label="code", path="/home/user/projects/../projects/repo-a"),
            ]
        )
        cfg = _make_cfg(tracking_dir="/tmp/tracking")

        paths = derive_write_paths(meta, cfg)

        # The resolved path without ".." should be present
        assert "/home/user/projects/repo-a" in paths
        # No path should contain ".."
        assert not any(".." in p for p in paths)

    def test_derive_sandbox_paths_strips_trailing_slash(self) -> None:
        """Trailing slashes are stripped from all paths."""
        meta = _make_meta(
            repos=[
                RepoEntry(label="code", path="/home/user/proj/"),
            ]
        )
        cfg = _make_cfg(tracking_dir="/tmp/tracking/")

        paths = derive_write_paths(meta, cfg)

        assert not any(p.endswith("/") for p in paths)
        assert "/home/user/proj" in paths


# ── Skill allow rules ────────────────────────────────────────────────────────


class TestDeriveSkillPrefixes:
    def test_always_includes_proj_hooks_review(self) -> None:
        cfg = _make_cfg(worktree_integration=False)

        prefixes = derive_skill_prefixes(cfg)

        assert "Skill(proj:*)" in prefixes
        assert "Skill(hooks:*)" in prefixes
        assert "Skill(review:*)" in prefixes
        assert "Skill(worktree:*)" not in prefixes

    def test_worktree_integration_adds_worktree_skill(self) -> None:
        cfg = _make_cfg(worktree_integration=True)

        prefixes = derive_skill_prefixes(cfg)

        assert "Skill(worktree:*)" in prefixes


class TestRunSyncSkillAllow:
    def test_missing_skill_rules_reported(self) -> None:
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=True, todoist_enabled=False)
        expected_mcp = derive_mcp_rules(meta, cfg)

        result = run_sync(
            meta,
            cfg,
            actual_rules=expected_mcp,
            actual_sandbox_paths=set(),
            actual_skill_allow=set(),
            sandbox_mode=False,
        )

        assert "❌" in result
        assert "Skill rules" in result
        assert "Skill(proj:*)" in result

    def test_skill_rules_in_sync(self) -> None:
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=True, todoist_enabled=False)
        expected_mcp = derive_mcp_rules(meta, cfg)
        expected_skills = derive_skill_prefixes(cfg)

        result = run_sync(
            meta,
            cfg,
            actual_rules=expected_mcp,
            actual_sandbox_paths=set(),
            actual_skill_allow=expected_skills,
            sandbox_mode=False,
        )

        assert "✅" in result
        assert "in sync" in result

    def test_skill_allow_none_skips_check(self) -> None:
        """When actual_skill_allow is None (not provided), skill check is skipped."""
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=True, todoist_enabled=False)
        expected_mcp = derive_mcp_rules(meta, cfg)

        result = run_sync(
            meta,
            cfg,
            actual_rules=expected_mcp,
            actual_sandbox_paths=set(),
            actual_skill_allow=None,
            sandbox_mode=False,
        )

        assert "✅" in result


class TestRunSyncAdditionalDirs:
    def test_missing_additional_dirs_reported(self) -> None:
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=True, todoist_enabled=False, tracking_dir="/tmp/tracking")
        expected_mcp = derive_mcp_rules(meta, cfg)

        result = run_sync(
            meta,
            cfg,
            actual_rules=expected_mcp,
            actual_sandbox_paths=set(),
            actual_additional_dirs=set(),
            sandbox_mode=False,
        )

        assert "❌" in result
        assert "Additional directories" in result

    def test_additional_dirs_none_skips_check(self) -> None:
        """When actual_additional_dirs is None (not provided), check is skipped."""
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=True, todoist_enabled=False)
        expected_mcp = derive_mcp_rules(meta, cfg)

        result = run_sync(
            meta,
            cfg,
            actual_rules=expected_mcp,
            actual_sandbox_paths=set(),
            actual_additional_dirs=None,
            sandbox_mode=False,
        )

        assert "✅" in result


# ── Sandbox mode tests ────────────────────────────────────────────────────────


class TestRunSyncSandbox:
    def test_in_sync_sandbox_mode(self) -> None:
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=True, todoist_enabled=False, tracking_dir="/tmp/tracking")
        expected = derive_mcp_rules(meta, cfg)

        result = run_sync(
            meta,
            cfg,
            actual_rules=expected,
            actual_sandbox_paths={"/home/user/proj", "/tmp/tracking"},
            sandbox_mode=True,
        )

        assert "settings.json" in result
        assert "in sync" in result

    def test_missing_sandbox_paths_reported(self) -> None:
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=True, todoist_enabled=False)
        expected = derive_mcp_rules(meta, cfg)

        result = run_sync(
            meta,
            cfg,
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
            meta,
            cfg,
            actual_rules=set(),
            actual_sandbox_paths=set(),
            sandbox_mode=True,
        )

        assert "❌" in result
        assert "settings.json" in result
        assert "MCP rules" in result or "Sandbox allowWrite" in result
        assert "Read(" not in result


# ── Worktree root dir tests ──────────────────────────────────────────────────


class TestDeriveExpectedSandboxPathsWorktreeRoot:
    def test_includes_worktree_root_when_integration_on(self) -> None:
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(worktree_integration=True, tracking_dir="/tmp/tracking")

        paths = derive_write_paths(meta, cfg, worktree_root_dir="/home/user/worktrees")

        assert "/home/user/worktrees" in paths
        assert "/home/user/proj" in paths
        assert "/tmp/tracking" in paths

    def test_skips_worktree_root_when_integration_off(self) -> None:
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(worktree_integration=False, tracking_dir="/tmp/tracking")

        paths = derive_write_paths(meta, cfg, worktree_root_dir="/home/user/worktrees")

        assert "/home/user/worktrees" not in paths

    def test_skips_worktree_root_when_none(self) -> None:
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(worktree_integration=True, tracking_dir="/tmp/tracking")

        paths = derive_write_paths(meta, cfg, worktree_root_dir=None)

        assert len(paths) == 2  # repo + tracking only


class TestRunSyncWorktreeRoot:
    def test_missing_worktree_root_reported_as_missing_sandbox_path(self) -> None:
        """When worktree_root_dir is provided but not in
        actual_sandbox_paths, it is reported missing."""
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(
            auto_allow_mcps=True,
            todoist_enabled=False,
            worktree_integration=True,
            tracking_dir="/tmp/tracking",
        )
        expected_rules = derive_mcp_rules(meta, cfg)

        result = run_sync(
            meta,
            cfg,
            actual_rules=expected_rules,
            actual_sandbox_paths={"/home/user/proj", "/tmp/tracking"},
            sandbox_mode=True,
            worktree_root_dir="/home/user/worktrees",
        )

        assert "❌" in result
        assert "/home/user/worktrees" in result

    def test_apply_true_adds_worktree_path(self) -> None:
        """apply=True with missing worktree root forwards it to setup_permissions."""
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(
            auto_allow_mcps=False,
            worktree_integration=True,
            tracking_dir="/tmp/tracking",
        )

        def fake_batch_setup(
            paths: list[str],
            mcp_servers: list[str],
            additional_directories: list[str] | None = None,
        ) -> str:
            return (
                f"Sandbox paths added: {len(paths)}."
                f" MCP rules added: {len(mcp_servers)}."
                f" Additional directories added: {len(paths)}."
            )

        result = run_sync(
            meta,
            cfg,
            actual_rules=set(),
            actual_sandbox_paths=set(),
            sandbox_mode=True,
            apply=True,
            worktree_root_dir="/home/user/worktrees",
            batch_setup_fn=fake_batch_setup,
        )

        assert "✅" in result
        assert "Applied" in result


class TestRunSyncDenyWarning:
    def test_run_sync_deny_warning_when_roots_set(self) -> None:
        """When projects_root is set and no deny rules, a warning is generated."""
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(
            auto_allow_mcps=True,
            todoist_enabled=False,
            projects_root="/home/user/projects",
        )
        expected = derive_mcp_rules(meta, cfg)

        result = run_sync(
            meta,
            cfg,
            actual_rules=expected,
            actual_sandbox_paths={"/home/user/projects"},
            actual_deny_rules=None,
            sandbox_mode=True,
        )

        assert "⚠️" in result
        assert "deny" in result.lower()

    def test_run_sync_no_deny_warning_without_roots(self) -> None:
        """When projects_root is NOT set, no deny warning even without deny rules."""
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=True, todoist_enabled=False)
        expected = derive_mcp_rules(meta, cfg)

        result = run_sync(
            meta,
            cfg,
            actual_rules=expected,
            actual_sandbox_paths={"/home/user/proj"},
            actual_deny_rules=None,
            sandbox_mode=True,
        )

        assert "⚠️" not in result

    def test_run_sync_no_deny_warning_when_deny_rules_present(self) -> None:
        """When projects_root is set but deny rules exist, no warning."""
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(
            auto_allow_mcps=True,
            todoist_enabled=False,
            projects_root="/home/user/projects",
        )
        expected = derive_mcp_rules(meta, cfg)

        result = run_sync(
            meta,
            cfg,
            actual_rules=expected,
            actual_sandbox_paths={"/home/user/projects"},
            actual_deny_rules=["some_deny_rule"],
            sandbox_mode=True,
        )

        assert "⚠️" not in result
