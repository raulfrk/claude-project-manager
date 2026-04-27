"""Tests for postmortem-related Claude Code hook subcommands in server.cli.

Covers:
- cmd_postmortem_session_reminder: prints 4-line reminder to stderr
- cmd_postmortem_pretooluse_git_commit: PreToolUse JSON in/out flow
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from server.lib import storage
from server.lib.models import ProjConfig


@pytest.fixture()
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ProjConfig:
    config_path = tmp_path / "proj.yaml"
    monkeypatch.setattr(storage, "_DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.delenv("PROJ_CONFIG", raising=False)
    c = ProjConfig(tracking_dir=str(tmp_path / "tracking"))
    Path(c.tracking_dir).mkdir(parents=True)
    storage.save_config(c)
    return c


# ---------------------------------------------------------------------------
# cmd_postmortem_session_reminder
# ---------------------------------------------------------------------------


class TestPostmortemSessionReminder:
    def test_prints_reminder_to_stderr(
        self,
        cfg: ProjConfig,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from server.cli import cmd_postmortem_session_reminder

        cmd_postmortem_session_reminder()
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "postmortem" in captured.err.lower()

    def test_reminder_mentions_heading_format(
        self,
        cfg: ProjConfig,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from server.cli import cmd_postmortem_session_reminder

        cmd_postmortem_session_reminder()
        captured = capsys.readouterr()
        assert "## [" in captured.err
        assert "postmortem |" in captured.err

    def test_silent_when_recent_postmortem_exists(
        self,
        cfg: ProjConfig,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """If a recent postmortem exists in tracking_dir, suppress reminder."""
        proj_dir = Path(cfg.tracking_dir) / "p1"
        proj_dir.mkdir(parents=True)
        notes = proj_dir / "NOTES.md"
        notes.write_text("## [2026-04-27 12:00] postmortem | 799\nclass: boundary-drift\n")
        from server.cli import cmd_postmortem_session_reminder

        cmd_postmortem_session_reminder()
        captured = capsys.readouterr()
        # When recent postmortem exists, reminder is suppressed
        assert captured.err == ""


# ---------------------------------------------------------------------------
# cmd_postmortem_pretooluse_git_commit
# ---------------------------------------------------------------------------


class TestPostmortemPreToolUse:
    def test_no_recent_postmortem_emits_allow_with_reason(
        self,
        cfg: ProjConfig,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """No postmortem in tracking dir → emit modern hookSpecificOutput w/
        permissionDecision="allow" + reason. Reason shown to user (not
        Claude) per Claude Code hook docs."""
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": 'git commit -m "fix(scope/123): bug"'},
        }
        monkeypatch.setattr("sys.stdin", _stdin_with(json.dumps(payload)))
        from server.cli import cmd_postmortem_pretooluse_git_commit

        cmd_postmortem_pretooluse_git_commit()
        captured = capsys.readouterr()
        body = json.loads(captured.out)
        # Modern hookSpecificOutput schema
        hso = body["hookSpecificOutput"]
        assert hso["hookEventName"] == "PreToolUse"
        assert hso["permissionDecision"] == "allow"
        assert "postmortem" in hso["permissionDecisionReason"].lower()
        # Legacy top-level fields must not be set (deprecated for PreToolUse)
        assert "decision" not in body
        assert "reason" not in body

    def test_recent_postmortem_emits_silent_approve(
        self,
        cfg: ProjConfig,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        proj_dir = Path(cfg.tracking_dir) / "p1"
        proj_dir.mkdir(parents=True)
        (proj_dir / "NOTES.md").write_text(
            "## [2026-04-27 12:00] postmortem | 799\nclass: boundary-drift\n"
        )
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": 'git commit -m "fix(scope): bug"'},
        }
        monkeypatch.setattr("sys.stdin", _stdin_with(json.dumps(payload)))
        from server.cli import cmd_postmortem_pretooluse_git_commit

        cmd_postmortem_pretooluse_git_commit()
        captured = capsys.readouterr()
        # Silent approve = empty stdout (Claude Code interprets no output as OK)
        assert captured.out == ""

    def test_invalid_json_silent_exit(
        self,
        cfg: ProjConfig,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("sys.stdin", _stdin_with("not json at all"))
        from server.cli import cmd_postmortem_pretooluse_git_commit

        cmd_postmortem_pretooluse_git_commit()
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_empty_stdin_silent_exit(
        self,
        cfg: ProjConfig,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("sys.stdin", _stdin_with(""))
        from server.cli import cmd_postmortem_pretooluse_git_commit

        cmd_postmortem_pretooluse_git_commit()
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_missing_config_silent_exit(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """No proj.yaml → silent exit, never crashes."""
        monkeypatch.setattr(storage, "_DEFAULT_CONFIG_PATH", tmp_path / "missing.yaml")
        monkeypatch.delenv("PROJ_CONFIG", raising=False)
        payload = {"tool_name": "Bash", "tool_input": {"command": "git commit -m fix(s)"}}
        monkeypatch.setattr("sys.stdin", _stdin_with(json.dumps(payload)))
        from server.cli import cmd_postmortem_pretooluse_git_commit

        cmd_postmortem_pretooluse_git_commit()
        captured = capsys.readouterr()
        # No crash, default behavior: allow w/ reason (no recent postmortem)
        if captured.out:
            body = json.loads(captured.out)
            assert body["hookSpecificOutput"]["permissionDecision"] == "allow"


# ---------------------------------------------------------------------------
# CLI argparse integration via subprocess
# ---------------------------------------------------------------------------


class TestCliArgparseIntegration:
    def test_session_reminder_argparse_dispatches(
        self, cfg: ProjConfig, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """argparse routes `postmortem-session-reminder` to the right cmd."""
        from server import cli as cli_mod

        sys.argv = ["server.cli", "postmortem-session-reminder"]
        cli_mod.main()
        captured = capsys.readouterr()
        # Reminder went to stderr (no recent postmortem in fresh cfg)
        assert "postmortem" in captured.err.lower()

    def test_pretooluse_argparse_dispatches(
        self, cfg: ProjConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """argparse routes `postmortem-pretooluse-git-commit` to the right cmd."""
        from server import cli as cli_mod

        sys.argv = ["server.cli", "postmortem-pretooluse-git-commit"]
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}})
        monkeypatch.setattr("sys.stdin", _stdin_with(payload))
        cli_mod.main()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


class _StdinShim:
    def __init__(self, content: str) -> None:
        self._content = content

    def read(self) -> str:
        return self._content


def _stdin_with(content: str) -> _StdinShim:
    return _StdinShim(content)
