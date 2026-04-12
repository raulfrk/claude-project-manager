"""Tests for sandbox settings tools."""

from __future__ import annotations

import json
from pathlib import Path

from server.tools.settings import (
    sandbox_add_domain,
    sandbox_add_mcp_allow,
    sandbox_add_skill_allow,
    sandbox_add_write_path,
    sandbox_batch_revoke,
    sandbox_batch_setup,
    sandbox_check,
    sandbox_list,
    sandbox_reconcile,
    sandbox_remove_domain,
    sandbox_remove_mcp_allow,
    sandbox_remove_skill_allow,
    sandbox_remove_write_path,
    sandbox_set_deny,
)
from tests.conftest import read_settings, write_settings


class TestAddWritePath:
    def test_adds_path_and_edit_rule(self, tmp_path: Path) -> None:
        write_settings(
            tmp_path, {"sandbox": {"filesystem": {"allowWrite": []}}, "permissions": {"allow": []}}
        )
        result = json.loads(sandbox_add_write_path("/tmp/test"))
        assert result["added"] > 0
        data = read_settings(tmp_path)
        assert "/tmp/test" in data["sandbox"]["filesystem"]["allowWrite"]
        assert any("Edit(" in r for r in data["permissions"]["allow"])

    def test_idempotent(self, tmp_path: Path) -> None:
        write_settings(
            tmp_path,
            {
                "sandbox": {"filesystem": {"allowWrite": ["/tmp/test"]}},
                "permissions": {"allow": ["Edit(//tmp/test/**)"]},
            },
        )
        result = json.loads(sandbox_add_write_path("/tmp/test"))
        assert result["added"] == 0


class TestRemoveWritePath:
    def test_removes_path_and_edit_rule(self, tmp_path: Path) -> None:
        write_settings(
            tmp_path,
            {
                "sandbox": {"filesystem": {"allowWrite": ["/tmp/test"]}},
                "permissions": {"allow": ["Edit(//tmp/test/**)"]},
            },
        )
        result = json.loads(sandbox_remove_write_path("/tmp/test"))
        assert result["removed"] > 0
        data = read_settings(tmp_path)
        assert "/tmp/test" not in data.get("sandbox", {}).get("filesystem", {}).get(
            "allowWrite", []
        )

    def test_remove_missing_path(self, tmp_path: Path) -> None:
        write_settings(
            tmp_path,
            {"sandbox": {"filesystem": {"allowWrite": []}}, "permissions": {"allow": []}},
        )
        result = json.loads(sandbox_remove_write_path("/tmp/nonexistent"))
        assert result["removed"] == 0


class TestMcpAllow:
    def test_add_single(self, tmp_path: Path) -> None:
        write_settings(tmp_path, {"permissions": {"allow": []}})
        result = json.loads(sandbox_add_mcp_allow("plugin_proj_proj"))
        assert result["added"] == 1
        data = read_settings(tmp_path)
        assert "mcp__plugin_proj_proj__*" in data["permissions"]["allow"]

    def test_add_list(self, tmp_path: Path) -> None:
        write_settings(tmp_path, {"permissions": {"allow": []}})
        result = json.loads(sandbox_add_mcp_allow(["plugin_proj_proj", "plugin_sandbox_sandbox"]))
        assert result["added"] == 2

    def test_remove(self, tmp_path: Path) -> None:
        write_settings(tmp_path, {"permissions": {"allow": ["mcp__plugin_proj_proj__*"]}})
        result = json.loads(sandbox_remove_mcp_allow("plugin_proj_proj"))
        assert result["removed"] == 1


class TestSkillAllow:
    def test_add_single(self, tmp_path: Path) -> None:
        write_settings(tmp_path, {"permissions": {"allow": []}})
        result = json.loads(sandbox_add_skill_allow("proj"))
        assert result["added"] == 1
        data = read_settings(tmp_path)
        assert "Skill(proj:*)" in data["permissions"]["allow"]

    def test_add_list(self, tmp_path: Path) -> None:
        write_settings(tmp_path, {"permissions": {"allow": []}})
        result = json.loads(sandbox_add_skill_allow(["proj", "worktree"]))
        assert result["added"] == 2
        data = read_settings(tmp_path)
        assert "Skill(proj:*)" in data["permissions"]["allow"]
        assert "Skill(worktree:*)" in data["permissions"]["allow"]

    def test_idempotent(self, tmp_path: Path) -> None:
        write_settings(tmp_path, {"permissions": {"allow": ["Skill(proj:*)"]}})
        result = json.loads(sandbox_add_skill_allow("proj"))
        assert result["added"] == 0
        assert result["skipped"] == 1

    def test_remove_single(self, tmp_path: Path) -> None:
        write_settings(tmp_path, {"permissions": {"allow": ["Skill(proj:*)", "mcp__proj__*"]}})
        result = json.loads(sandbox_remove_skill_allow("proj"))
        assert result["removed"] == 1
        data = read_settings(tmp_path)
        assert "Skill(proj:*)" not in data["permissions"]["allow"]

    def test_remove_list(self, tmp_path: Path) -> None:
        write_settings(tmp_path, {"permissions": {"allow": ["Skill(proj:*)", "Skill(worktree:*)"]}})
        result = json.loads(sandbox_remove_skill_allow(["proj", "worktree"]))
        assert result["removed"] == 2

    def test_remove_missing(self, tmp_path: Path) -> None:
        write_settings(tmp_path, {"permissions": {"allow": []}})
        result = json.loads(sandbox_remove_skill_allow("proj"))
        assert result["removed"] == 0


class TestDomains:
    def test_add_domain(self, tmp_path: Path) -> None:
        write_settings(tmp_path, {"sandbox": {"network": {"allowedDomains": []}}})
        result = json.loads(sandbox_add_domain("github.com"))
        assert result["added"] is True
        data = read_settings(tmp_path)
        assert "github.com" in data["sandbox"]["network"]["allowedDomains"]

    def test_add_domain_idempotent(self, tmp_path: Path) -> None:
        write_settings(tmp_path, {"sandbox": {"network": {"allowedDomains": ["github.com"]}}})
        result = json.loads(sandbox_add_domain("github.com"))
        assert result["added"] is False

    def test_remove_domain(self, tmp_path: Path) -> None:
        write_settings(tmp_path, {"sandbox": {"network": {"allowedDomains": ["github.com"]}}})
        result = json.loads(sandbox_remove_domain("github.com"))
        assert result["removed"] is True

    def test_remove_domain_missing(self, tmp_path: Path) -> None:
        write_settings(tmp_path, {"sandbox": {"network": {"allowedDomains": []}}})
        result = json.loads(sandbox_remove_domain("github.com"))
        assert result["removed"] is False


class TestBatchOps:
    def test_batch_setup(self, tmp_path: Path) -> None:
        write_settings(
            tmp_path,
            {
                "permissions": {"allow": []},
                "sandbox": {"filesystem": {"allowWrite": []}, "network": {"allowedDomains": []}},
            },
        )
        result = json.loads(
            sandbox_batch_setup(
                paths=["/tmp/p1"],
                mcp_servers=["plugin_proj_proj"],
                domains=["github.com"],
            )
        )
        assert result["paths_added"] == 1
        assert result["mcp_added"] == 1
        assert result["domains_added"] == 1

    def test_batch_setup_with_skills(self, tmp_path: Path) -> None:
        write_settings(tmp_path, {"permissions": {"allow": []}})
        result = json.loads(sandbox_batch_setup(skill_prefixes=["proj", "worktree"]))
        assert result["skills_added"] == 2
        data = read_settings(tmp_path)
        assert "Skill(proj:*)" in data["permissions"]["allow"]
        assert "Skill(worktree:*)" in data["permissions"]["allow"]

    def test_batch_revoke(self, tmp_path: Path) -> None:
        write_settings(
            tmp_path,
            {
                "permissions": {"allow": ["mcp__plugin_proj_proj__*", "Edit(//tmp/p1/**)"]},
                "sandbox": {
                    "filesystem": {"allowWrite": ["/tmp/p1"]},
                    "network": {"allowedDomains": ["github.com"]},
                },
            },
        )
        result = json.loads(
            sandbox_batch_revoke(
                paths=["/tmp/p1"],
                mcp_servers=["plugin_proj_proj"],
                domains=["github.com"],
            )
        )
        assert result["paths_removed"] == 1
        assert result["mcp_removed"] == 1
        assert result["domains_removed"] == 1

    def test_batch_revoke_with_skills(self, tmp_path: Path) -> None:
        write_settings(
            tmp_path,
            {"permissions": {"allow": ["Skill(proj:*)", "Skill(worktree:*)"]}},
        )
        result = json.loads(sandbox_batch_revoke(skill_prefixes=["proj", "worktree"]))
        assert result["skills_removed"] == 2
        data = read_settings(tmp_path)
        assert "Skill(proj:*)" not in data.get("permissions", {}).get("allow", [])


class TestListAndCheck:
    def test_list_text(self, tmp_path: Path) -> None:
        write_settings(
            tmp_path,
            {
                "sandbox": {"enabled": True, "filesystem": {"allowWrite": ["/tmp/x"]}},
                "permissions": {"allow": ["mcp__proj__*"]},
            },
        )
        result = sandbox_list("text")
        assert "/tmp/x" in result
        assert "mcp__proj__*" in result

    def test_list_json(self, tmp_path: Path) -> None:
        write_settings(tmp_path, {"sandbox": {"enabled": True}, "permissions": {"allow": []}})
        data = json.loads(sandbox_list("json"))
        assert "write_paths" in data
        assert "sandbox_enabled" in data

    def test_list_json_includes_all_categories(self, tmp_path: Path) -> None:
        write_settings(
            tmp_path,
            {
                "sandbox": {"enabled": True},
                "permissions": {
                    "allow": ["mcp__proj__*", "Skill(proj:*)", "Edit(//tmp/**)"],
                    "deny": ["Bash(rm -rf *)"],
                },
            },
        )
        data = json.loads(sandbox_list("json"))
        assert data["mcp_allow"] == ["mcp__proj__*"]
        assert data["skill_allow"] == ["Skill(proj:*)"]
        assert data["edit_rules"] == ["Edit(//tmp/**)"]
        assert data["deny"] == ["Bash(rm -rf *)"]

    def test_check_present(self, tmp_path: Path) -> None:
        write_settings(
            tmp_path,
            {
                "sandbox": {"filesystem": {"allowWrite": ["/tmp/x"]}},
                "permissions": {"allow": ["mcp__proj__*"]},
            },
        )
        result = json.loads(sandbox_check(path="/tmp/x"))
        assert result["results"][0]["status"] == "present"

    def test_check_missing(self, tmp_path: Path) -> None:
        write_settings(
            tmp_path, {"sandbox": {"filesystem": {"allowWrite": []}}, "permissions": {"allow": []}}
        )
        result = json.loads(sandbox_check(path="/tmp/x"))
        assert result["results"][0]["status"] == "missing"

    def test_check_server(self, tmp_path: Path) -> None:
        write_settings(tmp_path, {"permissions": {"allow": ["mcp__proj__*"]}})
        result = json.loads(sandbox_check(server="proj"))
        assert result["results"][0]["type"] == "server"
        assert result["results"][0]["status"] == "present"

    def test_check_domain(self, tmp_path: Path) -> None:
        write_settings(tmp_path, {"sandbox": {"network": {"allowedDomains": ["gh.com"]}}})
        result = json.loads(sandbox_check(domain="gh.com"))
        assert result["results"][0]["type"] == "domain"
        assert result["results"][0]["status"] == "present"

    def test_check_skill(self, tmp_path: Path) -> None:
        write_settings(tmp_path, {"permissions": {"allow": ["Skill(proj:*)"]}})
        result = json.loads(sandbox_check(skill="proj"))
        assert result["results"][0]["type"] == "skill"
        assert result["results"][0]["status"] == "present"

    def test_check_no_args_returns_error(self, tmp_path: Path) -> None:
        write_settings(tmp_path, {})
        result = json.loads(sandbox_check())
        assert "error" in result

    def test_check_multiple_params(self, tmp_path: Path) -> None:
        write_settings(
            tmp_path,
            {
                "sandbox": {"filesystem": {"allowWrite": ["/tmp/x"]}},
                "permissions": {"allow": ["mcp__proj__*"]},
            },
        )
        result = json.loads(sandbox_check(path="/tmp/x", server="proj"))
        assert len(result["results"]) == 2


class TestReconcile:
    def test_adds_missing_removes_stale(self, tmp_path: Path) -> None:
        write_settings(tmp_path, {"permissions": {"allow": ["mcp__old_server__*"]}})
        result = json.loads(
            sandbox_reconcile(
                expected_servers=["new_server"],
                stale_servers=["old_server"],
            )
        )
        assert result["added"] >= 1
        assert result["removed"] >= 1
        data = read_settings(tmp_path)
        assert "mcp__new_server__*" in data["permissions"]["allow"]
        assert "mcp__old_server__*" not in data["permissions"]["allow"]

    def test_infers_stale_servers(self, tmp_path: Path) -> None:
        write_settings(
            tmp_path,
            {"permissions": {"allow": ["mcp__old_server__*", "mcp__keep_server__*"]}},
        )
        result = json.loads(sandbox_reconcile(expected_servers=["keep_server"]))
        assert result["removed"] >= 1
        data = read_settings(tmp_path)
        assert "mcp__keep_server__*" in data["permissions"]["allow"]
        assert "mcp__old_server__*" not in data["permissions"]["allow"]

    def test_reconcile_with_paths(self, tmp_path: Path) -> None:
        write_settings(
            tmp_path,
            {
                "permissions": {"allow": []},
                "sandbox": {"filesystem": {"allowWrite": []}},
            },
        )
        result = json.loads(sandbox_reconcile(expected_servers=[], expected_paths=["/tmp/proj"]))
        assert result["added"] >= 1
        data = read_settings(tmp_path)
        assert "/tmp/proj" in data["sandbox"]["filesystem"]["allowWrite"]

    def test_reconcile_path_adds_edit_permission(self, tmp_path: Path) -> None:
        write_settings(
            tmp_path,
            {
                "permissions": {"allow": []},
                "sandbox": {"filesystem": {"allowWrite": []}},
            },
        )
        sandbox_reconcile(expected_servers=[], expected_paths=["/tmp/proj"])
        data = read_settings(tmp_path)
        assert "Edit(//tmp/proj/**)" in data["permissions"]["allow"]

    def test_reconcile_path_added_count_includes_edit(self, tmp_path: Path) -> None:
        write_settings(
            tmp_path,
            {
                "permissions": {"allow": []},
                "sandbox": {"filesystem": {"allowWrite": []}},
            },
        )
        result = json.loads(sandbox_reconcile(expected_servers=[], expected_paths=["/tmp/proj"]))
        assert result["added"] == 2

    def test_reconcile_path_idempotent(self, tmp_path: Path) -> None:
        write_settings(
            tmp_path,
            {
                "permissions": {"allow": []},
                "sandbox": {"filesystem": {"allowWrite": []}},
            },
        )
        sandbox_reconcile(expected_servers=[], expected_paths=["/tmp/proj"])
        result = json.loads(sandbox_reconcile(expected_servers=[], expected_paths=["/tmp/proj"]))
        assert result["added"] == 0
        assert result["removed"] == 0

    def test_reconcile_multiple_paths_count(self, tmp_path: Path) -> None:
        write_settings(
            tmp_path,
            {
                "permissions": {"allow": []},
                "sandbox": {"filesystem": {"allowWrite": []}},
            },
        )
        result = json.loads(
            sandbox_reconcile(expected_servers=[], expected_paths=["/tmp/a", "/tmp/b"])
        )
        assert result["added"] == 4

    def test_reconcile_with_skill_prefixes(self, tmp_path: Path) -> None:
        write_settings(tmp_path, {"permissions": {"allow": []}})
        result = json.loads(
            sandbox_reconcile(
                expected_servers=[],
                expected_skill_prefixes=["proj", "worktree"],
            )
        )
        assert result["added"] >= 2
        data = read_settings(tmp_path)
        assert "Skill(proj:*)" in data["permissions"]["allow"]
        assert "Skill(worktree:*)" in data["permissions"]["allow"]


class TestSetDeny:
    def test_set_deny_rules(self, tmp_path: Path) -> None:
        write_settings(tmp_path, {"permissions": {}})
        result = json.loads(sandbox_set_deny(["Bash(git push *)", "Bash(rm -rf *)"]))
        assert result["count"] == 2
        data = read_settings(tmp_path)
        assert "Bash(git push *)" in data["permissions"]["deny"]


class TestValueErrorHandling:
    """Tests that invalid mcp_allow_entry / skill_allow_entry inputs return error JSON."""

    def test_sandbox_add_mcp_allow_invalid_entry(self, tmp_path: Path) -> None:
        write_settings(tmp_path, {"permissions": {"allow": []}})
        # server_name with '__' triggers ValueError in mcp_allow_entry
        result = json.loads(sandbox_add_mcp_allow("bad__name"))
        assert "error" in result
        # Settings must not have been modified
        data = read_settings(tmp_path)
        assert data["permissions"]["allow"] == []

    def test_sandbox_add_mcp_allow_empty_name(self, tmp_path: Path) -> None:
        write_settings(tmp_path, {"permissions": {"allow": []}})
        result = json.loads(sandbox_add_mcp_allow(""))
        assert "error" in result

    def test_sandbox_remove_mcp_allow_invalid_entry(self, tmp_path: Path) -> None:
        write_settings(tmp_path, {"permissions": {"allow": ["mcp__proj__*"]}})
        result = json.loads(sandbox_remove_mcp_allow("bad__name"))
        assert "error" in result
        # Settings must not have been modified
        data = read_settings(tmp_path)
        assert "mcp__proj__*" in data["permissions"]["allow"]

    def test_sandbox_check_invalid_entry(self, tmp_path: Path) -> None:
        write_settings(tmp_path, {"permissions": {"allow": []}})
        # server_name with '__' triggers ValueError (original line 422 bug)
        result = json.loads(sandbox_check(server="bad__name"))
        assert "error" in result

    def test_sandbox_check_invalid_skill(self, tmp_path: Path) -> None:
        write_settings(tmp_path, {"permissions": {"allow": []}})
        # skill prefix with '*' triggers ValueError in skill_allow_entry
        result = json.loads(sandbox_check(skill="bad*skill"))
        assert "error" in result

    def test_sandbox_batch_setup_invalid_mcp_server(self, tmp_path: Path) -> None:
        write_settings(
            tmp_path,
            {
                "permissions": {"allow": []},
                "sandbox": {"filesystem": {"allowWrite": []}, "network": {"allowedDomains": []}},
            },
        )
        result = json.loads(sandbox_batch_setup(mcp_servers=["bad__name"]))
        assert "error" in result
        # No partial write: settings unchanged
        data = read_settings(tmp_path)
        assert data["permissions"]["allow"] == []

    def test_sandbox_batch_setup_invalid_skill_prefix(self, tmp_path: Path) -> None:
        write_settings(tmp_path, {"permissions": {"allow": []}})
        result = json.loads(sandbox_batch_setup(skill_prefixes=["bad*prefix"]))
        assert "error" in result
        data = read_settings(tmp_path)
        assert data["permissions"]["allow"] == []

    def test_sandbox_batch_revoke_invalid_mcp_server(self, tmp_path: Path) -> None:
        write_settings(tmp_path, {"permissions": {"allow": ["mcp__good__*"]}})
        result = json.loads(sandbox_batch_revoke(mcp_servers=["bad__name"]))
        assert "error" in result
        # No partial write: settings unchanged
        data = read_settings(tmp_path)
        assert "mcp__good__*" in data["permissions"]["allow"]

    def test_sandbox_batch_revoke_invalid_skill_prefix(self, tmp_path: Path) -> None:
        write_settings(tmp_path, {"permissions": {"allow": ["Skill(proj:*)"]}})
        result = json.loads(sandbox_batch_revoke(skill_prefixes=["bad*prefix"]))
        assert "error" in result
        data = read_settings(tmp_path)
        assert "Skill(proj:*)" in data["permissions"]["allow"]

    def test_sandbox_reconcile_invalid_expected_server(self, tmp_path: Path) -> None:
        write_settings(tmp_path, {"permissions": {"allow": []}})
        result = json.loads(sandbox_reconcile(expected_servers=["bad__name"]))
        assert "error" in result
        data = read_settings(tmp_path)
        assert data["permissions"]["allow"] == []

    def test_sandbox_reconcile_invalid_skill_prefix(self, tmp_path: Path) -> None:
        write_settings(tmp_path, {"permissions": {"allow": []}})
        result = json.loads(
            sandbox_reconcile(
                expected_servers=[],
                expected_skill_prefixes=["bad*prefix"],
            )
        )
        assert "error" in result
        data = read_settings(tmp_path)
        assert data["permissions"]["allow"] == []
