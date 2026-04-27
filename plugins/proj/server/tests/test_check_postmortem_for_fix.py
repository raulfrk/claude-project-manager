"""Unit tests for scripts/check_postmortem_for_fix.py."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

# Test file lives at plugins/proj/server/tests/; scripts/ is at repo root.
# parents[0]=tests, [1]=server, [2]=proj, [3]=plugins, [4]=repo-root.
_REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import check_postmortem_for_fix as hook  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CPM_TRACKING_DIR", raising=False)


def test_missing_msg_file_exit_0(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    sys.argv = ["check_postmortem_for_fix.py", str(tmp_path / "no-such-file")]
    assert hook.main() == 0


def test_non_fix_commit_exit_0(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text("feat(scope): add a thing\n")
    sys.argv = ["check_postmortem_for_fix.py", str(msg)]
    assert hook.main() == 0


def test_fix_prefix_with_recent_postmortem_silent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    tracking = tmp_path / "tracking"
    proj = tracking / "proj1"
    proj.mkdir(parents=True)
    notes = proj / "NOTES.md"
    notes.write_text("## [2026-04-27 12:00] postmortem | 799\nclass: boundary-drift\n")
    monkeypatch.setenv("CPM_TRACKING_DIR", str(tracking))
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text("fix(scope/799): the bug\n")
    sys.argv = ["check_postmortem_for_fix.py", str(msg)]
    rc = hook.main()
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.err == ""


def test_fix_prefix_no_postmortem_warns_exit_0(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    tracking = tmp_path / "tracking"
    tracking.mkdir()
    monkeypatch.setenv("CPM_TRACKING_DIR", str(tracking))
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text("fix(scope/123): broke\n")
    sys.argv = ["check_postmortem_for_fix.py", str(msg)]
    rc = hook.main()
    captured = capsys.readouterr()
    assert rc == 0  # soft-warn
    assert "WARN" in captured.err
    assert "postmortem" in captured.err


def test_bug_prefix_treated_like_fix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    tracking = tmp_path / "tracking"
    tracking.mkdir()
    monkeypatch.setenv("CPM_TRACKING_DIR", str(tracking))
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text("bug(scope/123): broken\n")
    sys.argv = ["check_postmortem_for_fix.py", str(msg)]
    rc = hook.main()
    captured = capsys.readouterr()
    assert rc == 0
    assert "WARN" in captured.err


def test_old_postmortem_outside_window_warns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    tracking = tmp_path / "tracking"
    proj = tracking / "proj1"
    proj.mkdir(parents=True)
    notes = proj / "NOTES.md"
    notes.write_text("## [2025-01-01 00:00] postmortem | ancient\n")
    old = 1577836800.0  # backdate to 2020
    os.utime(notes, (old, old))
    monkeypatch.setenv("CPM_TRACKING_DIR", str(tracking))
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text("fix(scope/123): old\n")
    sys.argv = ["check_postmortem_for_fix.py", str(msg)]
    rc = hook.main()
    captured = capsys.readouterr()
    assert rc == 0
    assert "WARN" in captured.err


def test_env_override_respected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    custom = tmp_path / "elsewhere"
    proj = custom / "p"
    proj.mkdir(parents=True)
    (proj / "NOTES.md").write_text("## [2026-04-27 12:00] postmortem | x\n")
    monkeypatch.setenv("CPM_TRACKING_DIR", str(custom))
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text("fix(scope): a\n")
    sys.argv = ["check_postmortem_for_fix.py", str(msg)]
    rc = hook.main()
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.err == ""


def test_default_tracking_dir_used_when_no_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No env, no proj.yaml → falls back to ~/projects/tracking default."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.chdir(tmp_path)
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text("feat(scope): not a fix\n")  # not fix → exits 0 silent
    sys.argv = ["check_postmortem_for_fix.py", str(msg)]
    assert hook.main() == 0


def test_warning_message_mentions_heading_format(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    tracking = tmp_path / "tracking"
    tracking.mkdir()
    monkeypatch.setenv("CPM_TRACKING_DIR", str(tracking))
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text("fix(scope): broken\n")
    sys.argv = ["check_postmortem_for_fix.py", str(msg)]
    hook.main()
    captured = capsys.readouterr()
    assert "## [YYYY-MM-DD HH:MM] postmortem |" in captured.err


def test_fix_with_subscope_still_matches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    tracking = tmp_path / "tracking"
    tracking.mkdir()
    monkeypatch.setenv("CPM_TRACKING_DIR", str(tracking))
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text("fix(server/auth): bug\n")
    sys.argv = ["check_postmortem_for_fix.py", str(msg)]
    rc = hook.main()
    captured = capsys.readouterr()
    assert rc == 0
    assert "WARN" in captured.err


def test_revert_commit_exit_0_silent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`revert` is not a fix/bug prefix; should not trigger warning."""
    tracking = tmp_path / "tracking"
    tracking.mkdir()
    monkeypatch.setenv("CPM_TRACKING_DIR", str(tracking))
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text("revert(scope): undo\n")
    sys.argv = ["check_postmortem_for_fix.py", str(msg)]
    rc = hook.main()
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.err == ""


def test_cli_via_subprocess_returns_0(tmp_path: Path) -> None:
    """End-to-end subprocess invocation with fix prefix → exit 0 always."""
    tracking = tmp_path / "tracking"
    tracking.mkdir()
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text("fix(scope): broken\n")
    script = _REPO_ROOT / "scripts" / "check_postmortem_for_fix.py"
    env = {**os.environ, "CPM_TRACKING_DIR": str(tracking)}
    result = subprocess.run(
        [sys.executable, str(script), str(msg)],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 0
    assert "WARN" in result.stderr
