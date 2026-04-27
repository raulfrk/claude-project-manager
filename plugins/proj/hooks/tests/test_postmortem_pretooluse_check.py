"""Subprocess-driven tests for plugins/proj/hooks/postmortem_pretooluse_check.sh.

The trampoline is a thin filter: only forwards to run-cli.sh when the
PreToolUse payload is for Bash AND the command contains
`git commit ... fix(` or `bug(`. Other invocations exit 0 silent.

Tests stub `run-cli.sh` with a wrapper that echoes "FORWARDED" so we can
observe whether the trampoline forwarded or short-circuited.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

TRAMPOLINE = Path(__file__).resolve().parents[1] / "postmortem_pretooluse_check.sh"


@pytest.fixture()
def fake_plugin_root(tmp_path: Path) -> Path:
    """Build a fake CLAUDE_PLUGIN_ROOT w/ a stub run-cli.sh that echoes FORWARDED."""
    plugin_root = tmp_path / "plugin"
    hooks_dir = plugin_root / "hooks"
    hooks_dir.mkdir(parents=True)
    # Copy real trampoline so it sees CLAUDE_PLUGIN_ROOT properly
    shutil.copy(TRAMPOLINE, hooks_dir / "postmortem_pretooluse_check.sh")
    (hooks_dir / "postmortem_pretooluse_check.sh").chmod(0o755)
    # Stub run-cli.sh: drains stdin and echoes "FORWARDED <stdin>"
    stub = hooks_dir / "run-cli.sh"
    stub.write_text(
        '#!/usr/bin/env bash\nstdin=$(cat)\necho "FORWARDED $1 stdin=$stdin"\n'
    )
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return plugin_root


def _run(plugin_root: Path, payload: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(plugin_root)}
    return subprocess.run(
        ["bash", str(plugin_root / "hooks" / "postmortem_pretooluse_check.sh")],
        input=payload,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def test_non_bash_tool_exits_silent(fake_plugin_root: Path) -> None:
    payload = json.dumps({"tool_name": "Read", "tool_input": {"file_path": "/x"}})
    res = _run(fake_plugin_root, payload)
    assert res.returncode == 0
    assert res.stdout == ""


def test_bash_non_git_command_exits_silent(fake_plugin_root: Path) -> None:
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls -la"}})
    res = _run(fake_plugin_root, payload)
    assert res.returncode == 0
    assert "FORWARDED" not in res.stdout


def test_bash_git_status_exits_silent(fake_plugin_root: Path) -> None:
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "git status"}})
    res = _run(fake_plugin_root, payload)
    assert res.returncode == 0
    assert "FORWARDED" not in res.stdout


def test_bash_git_commit_no_fix_prefix_exits_silent(fake_plugin_root: Path) -> None:
    payload = json.dumps(
        {
            "tool_name": "Bash",
            "tool_input": {"command": 'git commit -m "feat(scope): add"'},
        }
    )
    res = _run(fake_plugin_root, payload)
    assert res.returncode == 0
    assert "FORWARDED" not in res.stdout


def test_bash_git_commit_fix_prefix_forwards(fake_plugin_root: Path) -> None:
    payload = json.dumps(
        {
            "tool_name": "Bash",
            "tool_input": {"command": 'git commit -m "fix(scope): bug"'},
        }
    )
    res = _run(fake_plugin_root, payload)
    assert res.returncode == 0
    assert "FORWARDED postmortem-pretooluse-git-commit" in res.stdout


def test_bash_git_commit_bug_prefix_forwards(fake_plugin_root: Path) -> None:
    payload = json.dumps(
        {
            "tool_name": "Bash",
            "tool_input": {"command": 'git commit -m "bug(scope): broke"'},
        }
    )
    res = _run(fake_plugin_root, payload)
    assert res.returncode == 0
    assert "FORWARDED postmortem-pretooluse-git-commit" in res.stdout


def test_bash_heredoc_git_commit_fix_forwards(fake_plugin_root: Path) -> None:
    """HEREDOC-style commit msg embedded inside git commit cmd still matches."""
    cmd = "git commit -m \"$(cat <<'EOF'\nfix(server/auth/799): broken thing\nEOF\n)\""
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}})
    res = _run(fake_plugin_root, payload)
    assert res.returncode == 0
    assert "FORWARDED" in res.stdout


def test_invalid_payload_does_not_crash(fake_plugin_root: Path) -> None:
    """Non-JSON payload: greps run normally; no fix( present → silent exit."""
    res = _run(fake_plugin_root, "this is not json at all")
    assert res.returncode == 0
    assert "FORWARDED" not in res.stdout
