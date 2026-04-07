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

    def test_remove_domain(self, tmp_path: Path) -> None:
        write_settings(tmp_path, {"sandbox": {"network": {"allowedDomains": ["github.com"]}}})
        result = json.loads(sandbox_remove_domain("github.com"))
        assert result["removed"] is True


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


class TestSetDeny:
    def test_set_deny_rules(self, tmp_path: Path) -> None:
        write_settings(tmp_path, {"permissions": {}})
        result = json.loads(sandbox_set_deny(["Bash(git push *)", "Bash(rm -rf *)"]))
        assert result["count"] == 2
        data = read_settings(tmp_path)
        assert "Bash(git push *)" in data["permissions"]["deny"]
