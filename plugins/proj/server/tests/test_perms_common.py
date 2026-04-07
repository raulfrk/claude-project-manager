"""Tests for _perms_common module — derive_write_paths, derive_mcp_rules, derive_skill_prefixes."""

from __future__ import annotations

from datetime import date

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


# ── derive_write_paths ───────────────────────────────────────────────────────


class TestDeriveWritePaths:
    def test_writable_repos_included(self) -> None:
        meta = _make_meta(
            repos=[
                RepoEntry(label="code", path="/home/user/proj"),
                RepoEntry(label="lib", path="/home/user/lib"),
            ]
        )
        cfg = _make_cfg(tracking_dir="")

        paths = derive_write_paths(meta, cfg)

        assert "/home/user/proj" in paths
        assert "/home/user/lib" in paths

    def test_reference_repos_excluded(self) -> None:
        meta = _make_meta(
            repos=[
                RepoEntry(label="code", path="/home/user/proj"),
                RepoEntry(label="docs", path="/home/user/docs", reference=True),
            ]
        )
        cfg = _make_cfg(tracking_dir="")

        paths = derive_write_paths(meta, cfg)

        assert "/home/user/proj" in paths
        assert "/home/user/docs" not in paths

    def test_tracking_dir_included(self) -> None:
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(tracking_dir="/tmp/tracking")

        paths = derive_write_paths(meta, cfg)

        assert "/tmp/tracking" in paths

    def test_no_tracking_dir_when_empty(self) -> None:
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(tracking_dir="")

        paths = derive_write_paths(meta, cfg)

        assert len(paths) == 1
        assert "/home/user/proj" in paths

    def test_projects_root_replaces_per_repo_paths(self) -> None:
        meta = _make_meta(
            repos=[
                RepoEntry(label="code", path="/home/user/projects/repo-a"),
                RepoEntry(label="lib", path="/home/user/projects/repo-b"),
            ]
        )
        cfg = _make_cfg(
            tracking_dir="/tmp/tracking",
            projects_root="/home/user/projects",
        )

        paths = derive_write_paths(meta, cfg)

        assert "/home/user/projects" in paths
        assert "/home/user/projects/repo-a" not in paths
        assert "/home/user/projects/repo-b" not in paths
        assert "/tmp/tracking" in paths

    def test_tracking_root_separate_from_projects_root(self) -> None:
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/projects/repo")])
        cfg = _make_cfg(
            projects_root="/home/user/projects",
            tracking_root="/home/user/tracking",
        )

        paths = derive_write_paths(meta, cfg)

        assert "/home/user/projects" in paths
        assert "/home/user/tracking" in paths

    def test_tracking_root_under_projects_root_skipped(self) -> None:
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/projects/repo")])
        cfg = _make_cfg(
            projects_root="/home/user/projects",
            tracking_root="/home/user/projects/tracking",
        )

        paths = derive_write_paths(meta, cfg)

        assert "/home/user/projects" in paths
        assert "/home/user/projects/tracking" not in paths

    def test_worktree_root_included_when_integration_on(self) -> None:
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(worktree_integration=True, tracking_dir="/tmp/tracking")

        paths = derive_write_paths(meta, cfg, worktree_root_dir="/home/user/worktrees")

        assert "/home/user/worktrees" in paths
        assert "/home/user/proj" in paths
        assert "/tmp/tracking" in paths

    def test_worktree_root_skipped_when_integration_off(self) -> None:
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(worktree_integration=False, tracking_dir="/tmp/tracking")

        paths = derive_write_paths(meta, cfg, worktree_root_dir="/home/user/worktrees")

        assert "/home/user/worktrees" not in paths

    def test_worktree_root_skipped_when_none(self) -> None:
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(worktree_integration=True, tracking_dir="/tmp/tracking")

        paths = derive_write_paths(meta, cfg, worktree_root_dir=None)

        assert len(paths) == 2  # repo + tracking

    def test_worktree_root_under_projects_root_skipped(self) -> None:
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/projects/repo")])
        cfg = _make_cfg(
            worktree_integration=True,
            projects_root="/home/user/projects",
            tracking_dir="",
        )

        paths = derive_write_paths(meta, cfg, worktree_root_dir="/home/user/projects/worktrees")

        assert "/home/user/projects" in paths
        assert "/home/user/projects/worktrees" not in paths

    def test_trailing_slashes_stripped(self) -> None:
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj/")])
        cfg = _make_cfg(tracking_dir="/tmp/tracking/")

        paths = derive_write_paths(meta, cfg)

        assert not any(p.endswith("/") for p in paths)

    def test_tilde_paths_expanded(self) -> None:
        meta = _make_meta(repos=[RepoEntry(label="code", path="~/myproject")])
        cfg = _make_cfg(tracking_dir="/tmp/tracking")

        paths = derive_write_paths(meta, cfg)

        assert not any("~" in p for p in paths)

    def test_relative_paths_resolved(self) -> None:
        meta = _make_meta(
            repos=[
                RepoEntry(label="code", path="/home/user/projects/../projects/repo"),
            ]
        )
        cfg = _make_cfg(tracking_dir="/tmp/tracking")

        paths = derive_write_paths(meta, cfg)

        assert not any(".." in p for p in paths)
        assert "/home/user/projects/repo" in paths

    def test_returns_set(self) -> None:
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg()

        result = derive_write_paths(meta, cfg)

        assert isinstance(result, set)

    def test_empty_repos_and_no_tracking(self) -> None:
        meta = _make_meta(repos=[])
        cfg = _make_cfg(tracking_dir="")

        paths = derive_write_paths(meta, cfg)

        assert len(paths) == 0


# ── derive_mcp_rules ─────────────────────────────────────────────────────────


class TestDeriveMcpRules:
    def test_auto_allow_mcps_true_includes_proj(self) -> None:
        meta = _make_meta(repos=[])
        cfg = _make_cfg(auto_allow_mcps=True)

        rules = derive_mcp_rules(meta, cfg)

        assert "mcp__plugin_proj_proj__*" in rules

    def test_auto_allow_mcps_false_excludes_plugins(self) -> None:
        meta = _make_meta(repos=[])
        cfg = _make_cfg(
            auto_allow_mcps=False,
            todoist_enabled=True,
            jira_enabled=True,
            trello_enabled=True,
            sandbox_integration=True,
            worktree_integration=True,
        )

        rules = derive_mcp_rules(meta, cfg)

        assert "mcp__plugin_proj_proj__*" not in rules
        assert "mcp__plugin_sandbox_sandbox__*" not in rules
        assert "mcp__plugin_worktree_worktree__*" not in rules
        assert "mcp__todoist__*" not in rules
        assert "mcp__plugin_jira_jira__*" not in rules
        assert "mcp__plugin_trello_trello__*" not in rules

    def test_global_claude_ai_always_present(self) -> None:
        meta = _make_meta(repos=[])
        cfg = _make_cfg(auto_allow_mcps=False)

        rules = derive_mcp_rules(meta, cfg)

        assert "mcp__claude_ai_Excalidraw__*" in rules
        assert "mcp__claude_ai_Mermaid_Chart__*" in rules

    def test_sandbox_integration_adds_sandbox_rule(self) -> None:
        meta = _make_meta(repos=[])
        cfg = _make_cfg(auto_allow_mcps=True, sandbox_integration=True)

        rules = derive_mcp_rules(meta, cfg)

        assert "mcp__plugin_sandbox_sandbox__*" in rules

    def test_sandbox_integration_false_excludes_sandbox_rule(self) -> None:
        meta = _make_meta(repos=[])
        cfg = _make_cfg(auto_allow_mcps=True, sandbox_integration=False)

        rules = derive_mcp_rules(meta, cfg)

        assert "mcp__plugin_sandbox_sandbox__*" not in rules

    def test_worktree_integration_adds_worktree_rule(self) -> None:
        meta = _make_meta(repos=[])
        cfg = _make_cfg(auto_allow_mcps=True, worktree_integration=True)

        rules = derive_mcp_rules(meta, cfg)

        assert "mcp__plugin_worktree_worktree__*" in rules

    def test_worktree_integration_false_excludes_worktree_rule(self) -> None:
        meta = _make_meta(repos=[])
        cfg = _make_cfg(auto_allow_mcps=True, worktree_integration=False)

        rules = derive_mcp_rules(meta, cfg)

        assert "mcp__plugin_worktree_worktree__*" not in rules

    def test_todoist_enabled_adds_todoist_rule(self) -> None:
        meta = _make_meta(repos=[])
        cfg = _make_cfg(auto_allow_mcps=True, todoist_enabled=True)

        rules = derive_mcp_rules(meta, cfg)

        assert "mcp__todoist__*" in rules

    def test_todoist_disabled_excludes_todoist_rule(self) -> None:
        meta = _make_meta(repos=[])
        cfg = _make_cfg(auto_allow_mcps=True, todoist_enabled=False)

        rules = derive_mcp_rules(meta, cfg)

        assert "mcp__todoist__*" not in rules

    def test_jira_enabled_adds_jira_rule(self) -> None:
        meta = _make_meta(repos=[])
        cfg = _make_cfg(auto_allow_mcps=True, jira_enabled=True)

        rules = derive_mcp_rules(meta, cfg)

        assert "mcp__plugin_jira_jira__*" in rules

    def test_jira_disabled_excludes_jira_rule(self) -> None:
        meta = _make_meta(repos=[])
        cfg = _make_cfg(auto_allow_mcps=True, jira_enabled=False)

        rules = derive_mcp_rules(meta, cfg)

        assert "mcp__plugin_jira_jira__*" not in rules

    def test_trello_enabled_adds_trello_rule(self) -> None:
        meta = _make_meta(repos=[])
        cfg = _make_cfg(auto_allow_mcps=True, trello_enabled=True)

        rules = derive_mcp_rules(meta, cfg)

        assert "mcp__plugin_trello_trello__*" in rules

    def test_trello_disabled_excludes_trello_rule(self) -> None:
        meta = _make_meta(repos=[])
        cfg = _make_cfg(auto_allow_mcps=True, trello_enabled=False)

        rules = derive_mcp_rules(meta, cfg)

        assert "mcp__plugin_trello_trello__*" not in rules

    def test_returns_set(self) -> None:
        meta = _make_meta(repos=[])
        cfg = _make_cfg()

        result = derive_mcp_rules(meta, cfg)

        assert isinstance(result, set)

    def test_all_integrations_enabled(self) -> None:
        meta = _make_meta(repos=[])
        cfg = _make_cfg(
            auto_allow_mcps=True,
            todoist_enabled=True,
            jira_enabled=True,
            trello_enabled=True,
            sandbox_integration=True,
            worktree_integration=True,
        )

        rules = derive_mcp_rules(meta, cfg)

        expected = {
            "mcp__plugin_proj_proj__*",
            "mcp__plugin_sandbox_sandbox__*",
            "mcp__plugin_worktree_worktree__*",
            "mcp__todoist__*",
            "mcp__plugin_jira_jira__*",
            "mcp__plugin_trello_trello__*",
            "mcp__claude_ai_Excalidraw__*",
            "mcp__claude_ai_Mermaid_Chart__*",
        }
        assert rules == expected

    def test_no_path_rules_in_output(self) -> None:
        """derive_mcp_rules never returns Read/Edit/Bash rules."""
        meta = _make_meta(repos=[RepoEntry(label="code", path="/home/user/proj")])
        cfg = _make_cfg(auto_allow_mcps=True)

        rules = derive_mcp_rules(meta, cfg)

        assert not any(r.startswith(("Read(", "Edit(", "Bash(")) for r in rules)


# ── derive_skill_prefixes ────────────────────────────────────────────────────


class TestDeriveSkillPrefixes:
    def test_always_includes_proj(self) -> None:
        cfg = _make_cfg()

        prefixes = derive_skill_prefixes(cfg)

        assert "Skill(proj:*)" in prefixes

    def test_always_includes_hooks(self) -> None:
        cfg = _make_cfg()

        prefixes = derive_skill_prefixes(cfg)

        assert "Skill(hooks:*)" in prefixes

    def test_always_includes_review(self) -> None:
        cfg = _make_cfg()

        prefixes = derive_skill_prefixes(cfg)

        assert "Skill(review:*)" in prefixes

    def test_worktree_integration_adds_worktree(self) -> None:
        cfg = _make_cfg(worktree_integration=True)

        prefixes = derive_skill_prefixes(cfg)

        assert "Skill(worktree:*)" in prefixes

    def test_worktree_integration_false_excludes_worktree(self) -> None:
        cfg = _make_cfg(worktree_integration=False)

        prefixes = derive_skill_prefixes(cfg)

        assert "Skill(worktree:*)" not in prefixes

    def test_returns_set(self) -> None:
        cfg = _make_cfg()

        result = derive_skill_prefixes(cfg)

        assert isinstance(result, set)

    def test_default_config_has_three_prefixes(self) -> None:
        """Default config (no worktree) has proj, hooks, review."""
        cfg = _make_cfg(worktree_integration=False)

        prefixes = derive_skill_prefixes(cfg)

        assert len(prefixes) == 3
        assert prefixes == {"Skill(proj:*)", "Skill(hooks:*)", "Skill(review:*)"}

    def test_with_worktree_has_four_prefixes(self) -> None:
        cfg = _make_cfg(worktree_integration=True)

        prefixes = derive_skill_prefixes(cfg)

        assert len(prefixes) == 4
        assert "Skill(worktree:*)" in prefixes

    def test_integration_flags_dont_affect_skill_prefixes(self) -> None:
        """sandbox/todoist/jira/trello integrations don't add skill prefixes."""
        cfg = _make_cfg(
            sandbox_integration=True,
            todoist_enabled=True,
            jira_enabled=True,
            trello_enabled=True,
            worktree_integration=False,
        )

        prefixes = derive_skill_prefixes(cfg)

        # Only proj, hooks, review -- no sandbox/todoist/jira/trello skills
        assert len(prefixes) == 3
