"""Tests for server.cli — the hook CLI entry point.

Tests cover:
- cmd_session_start: active project context, missing config, missing project
- cmd_session_end: bumps last_updated, skips when date already current
- CLI argument parsing via subprocess (session-start, session-end, bad command)
"""

from __future__ import annotations

import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from server.lib import storage
from server.lib.models import (
    ProjConfig,
    ProjectDates,
    ProjectEntry,
    ProjectIndex,
    ProjectMeta,
    RepoEntry,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_project(cfg: ProjConfig, name: str, repo_path: str, *, active: bool = True) -> None:
    today = str(date.today())
    proj_dir = Path(cfg.tracking_dir) / name
    proj_dir.mkdir(parents=True)
    (proj_dir / "todos.yaml").write_text("todos: []\n")
    (proj_dir / "NOTES.md").write_text(f"# {name}\n")
    meta = ProjectMeta(
        name=name,
        repos=[RepoEntry(label="code", path=repo_path)],
        dates=ProjectDates(created=today, last_updated=today),
    )
    storage.save_meta(cfg, meta)
    index = storage.load_index(cfg)
    index.projects[name] = ProjectEntry(name=name, tracking_dir=str(proj_dir), created=today)
    storage.save_index(cfg, index)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ProjConfig:
    config_path = tmp_path / "proj.yaml"
    monkeypatch.setattr(storage, "_DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.delenv("PROJ_CONFIG", raising=False)
    c = ProjConfig(tracking_dir=str(tmp_path / "tracking"))
    storage.save_config(c)
    return c


# ---------------------------------------------------------------------------
# cmd_session_start — direct function tests
# ---------------------------------------------------------------------------


class TestCmdSessionStart:
    def test_no_config_prints_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """When proj.yaml does not exist, session-start emits nothing."""
        monkeypatch.setattr(storage, "_DEFAULT_CONFIG_PATH", tmp_path / "missing.yaml")
        monkeypatch.delenv("PROJ_CONFIG", raising=False)

        from server.cli import cmd_session_start

        cmd_session_start(cwd=None, compact=False)
        out, err = capsys.readouterr()
        assert out == ""
        assert err == ""

    def test_no_active_project_prints_nothing(
        self, cfg: ProjConfig, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """When config exists but no active project, session-start emits nothing."""
        # Index has no active project
        index = ProjectIndex()
        storage.save_index(cfg, index)

        from server.cli import cmd_session_start

        cmd_session_start(cwd=None, compact=False)
        out, err = capsys.readouterr()
        assert out == ""
        assert err == ""

    def test_cwd_detects_project_prints_context(
        self, cfg: ProjConfig, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """When cwd matches a project repo, session-start prints its context."""
        _make_project(cfg, "myapp", str(tmp_path), active=True)

        from server.cli import cmd_session_start

        cmd_session_start(cwd=str(tmp_path), compact=False)
        out, _ = capsys.readouterr()
        assert "myapp" in out

    def test_compact_flag_suppresses_notes(
        self, cfg: ProjConfig, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """compact=True skips Recent Notes section."""
        _make_project(cfg, "myapp", str(tmp_path), active=True)
        storage.append_note(cfg, "myapp", "A secret note")

        from server.cli import cmd_session_start

        cmd_session_start(cwd=str(tmp_path), compact=True)
        out, _ = capsys.readouterr()
        assert "myapp" in out
        assert "A secret note" not in out

    def test_cwd_auto_detects_project(
        self, cfg: ProjConfig, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """When cwd matches a repo, session-start auto-detects."""
        _make_project(cfg, "myapp", str(tmp_path), active=False)

        from server.cli import cmd_session_start

        cmd_session_start(cwd=str(tmp_path), compact=False)
        out, _ = capsys.readouterr()
        assert "myapp" in out

    def test_no_cwd_prints_nothing(
        self, cfg: ProjConfig, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Without cwd, session-start prints nothing (no persisted active)."""
        _make_project(cfg, "myapp", str(tmp_path), active=True)

        from server.cli import cmd_session_start

        cmd_session_start(cwd=None, compact=False)
        out, err = capsys.readouterr()
        assert out == ""

    def test_cwd_no_match_prints_nothing(
        self, cfg: ProjConfig, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """cwd that matches no project repo still prints nothing."""
        _make_project(cfg, "myapp", str(tmp_path), active=False)

        from server.cli import cmd_session_start

        cmd_session_start(cwd="/nonexistent/path/xyz", compact=False)
        out, err = capsys.readouterr()
        assert out == ""


# ---------------------------------------------------------------------------
# cmd_session_end — direct function tests
# ---------------------------------------------------------------------------


class TestCmdSessionEnd:
    def test_no_config_is_noop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """When proj.yaml does not exist, session-end does nothing."""
        monkeypatch.setattr(storage, "_DEFAULT_CONFIG_PATH", tmp_path / "missing.yaml")
        monkeypatch.delenv("PROJ_CONFIG", raising=False)

        from server.cli import cmd_session_end

        cmd_session_end(cwd=None)
        out, err = capsys.readouterr()
        assert out == ""
        assert err == ""

    def test_no_cwd_is_noop(
        self, cfg: ProjConfig, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """When no cwd is provided, session-end is silent (no project to detect)."""
        from server.cli import cmd_session_end

        cmd_session_end(cwd=None)
        out, err = capsys.readouterr()
        assert out == ""
        assert err == ""

    def test_bumps_last_updated_when_stale(
        self, cfg: ProjConfig, tmp_path: Path
    ) -> None:
        """When last_updated is in the past, session-end saves the meta (updating timestamp)."""
        _make_project(cfg, "myapp", str(tmp_path), active=True)

        # Set last_updated to yesterday
        meta = storage.load_meta(cfg, "myapp")
        meta.dates.last_updated = "2000-01-01"
        storage.save_meta(cfg, meta)

        from server.cli import cmd_session_end

        cmd_session_end(cwd=str(tmp_path))

        # After the call, meta should have been written (save_meta called)
        meta_after = storage.load_meta(cfg, "myapp")
        assert meta_after.name == "myapp"

    def test_skips_save_when_date_current(
        self, cfg: ProjConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When last_updated already equals today, session-end skips saving."""
        _make_project(cfg, "myapp", str(tmp_path), active=True)

        # last_updated is already today (set by _make_project)
        meta = storage.load_meta(cfg, "myapp")
        assert meta.dates.last_updated == str(date.today())

        # Spy on save_meta — it should NOT be called
        save_called: list[bool] = []
        original_save = storage.save_meta

        def spy_save(cfg_arg: ProjConfig, meta_arg: ProjectMeta) -> None:
            save_called.append(True)
            original_save(cfg_arg, meta_arg)

        monkeypatch.setattr(storage, "save_meta", spy_save)

        from server.cli import cmd_session_end

        cmd_session_end(cwd=str(tmp_path))
        assert save_called == [], "save_meta should not be called when date is already today"

    def test_cwd_no_match_is_noop(
        self, cfg: ProjConfig, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """When cwd doesn't match any project, session-end is silent."""
        _make_project(cfg, "myapp", str(tmp_path), active=True)

        from server.cli import cmd_session_end

        cmd_session_end(cwd="/nonexistent/path/xyz")
        out, err = capsys.readouterr()
        assert out == ""
        assert err == ""


# ---------------------------------------------------------------------------
# CLI argument parsing — subprocess integration tests
# ---------------------------------------------------------------------------


def _run_cli(*args: str, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Run `python -m server.cli <args>` as a subprocess."""
    import os

    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)

    server_dir = Path(__file__).parents[1]  # plugins/proj/server/
    return subprocess.run(
        [sys.executable, "-m", "server.cli", *args],
        capture_output=True,
        text=True,
        cwd=str(server_dir),
        env=env,
    )


class TestCliArgParsing:
    def test_no_subcommand_exits_nonzero(self, tmp_path: Path) -> None:
        """Calling the CLI with no subcommand prints help and exits 1."""
        result = _run_cli(env_extra={"PROJ_CONFIG": str(tmp_path / "missing.yaml")})
        assert result.returncode == 1

    def test_invalid_subcommand_exits_nonzero(self, tmp_path: Path) -> None:
        """An unrecognised subcommand exits non-zero."""
        result = _run_cli("bogus-command", env_extra={"PROJ_CONFIG": str(tmp_path / "missing.yaml")})
        # argparse prints error and exits 2 for unrecognised subcommands
        assert result.returncode != 0

    def test_session_start_no_config_exits_zero(self, tmp_path: Path) -> None:
        """session-start with no config exits 0 and emits no output."""
        result = _run_cli(
            "session-start",
            "--cwd", str(tmp_path),
            env_extra={"PROJ_CONFIG": str(tmp_path / "missing.yaml")},
        )
        assert result.returncode == 0
        assert result.stdout == ""

    def test_session_start_compact_flag_accepted(self, tmp_path: Path) -> None:
        """--compact flag is accepted without error."""
        result = _run_cli(
            "session-start",
            "--cwd", str(tmp_path),
            "--compact",
            env_extra={"PROJ_CONFIG": str(tmp_path / "missing.yaml")},
        )
        assert result.returncode == 0

    def test_session_end_no_config_exits_zero(self, tmp_path: Path) -> None:
        """session-end with no config exits 0 silently."""
        result = _run_cli(
            "session-end",
            "--cwd", str(tmp_path),
            env_extra={"PROJ_CONFIG": str(tmp_path / "missing.yaml")},
        )
        assert result.returncode == 0
        assert result.stdout == ""

    def test_session_start_cwd_optional(self, tmp_path: Path) -> None:
        """--cwd is optional for session-start."""
        result = _run_cli(
            "session-start",
            env_extra={"PROJ_CONFIG": str(tmp_path / "missing.yaml")},
        )
        assert result.returncode == 0

    def test_session_end_cwd_optional(self, tmp_path: Path) -> None:
        """--cwd is optional for session-end."""
        result = _run_cli(
            "session-end",
            env_extra={"PROJ_CONFIG": str(tmp_path / "missing.yaml")},
        )
        assert result.returncode == 0

    def test_session_start_with_active_project_outputs_context(self, tmp_path: Path) -> None:
        """End-to-end: session-start prints project context when project is active."""
        import os

        # Build a minimal config + project directory structure
        config_path = tmp_path / "proj.yaml"
        tracking_dir = tmp_path / "tracking"
        tracking_dir.mkdir()

        # Write config
        config_path.write_text(
            f"tracking_dir: {tracking_dir}\ngit_integration: false\n"
        )

        # Write index with project (no active field — session-only now)
        proj_dir = tracking_dir / "myapp"
        proj_dir.mkdir()
        today = str(date.today())
        (tracking_dir / "active-projects.yaml").write_text(
            f"projects:\n  myapp:\n    name: myapp\n"
            f"    tracking_dir: {proj_dir}\n    created: '{today}'\n"
        )

        # Write todos and notes
        (proj_dir / "todos.yaml").write_text("todos: []\n")
        (proj_dir / "NOTES.md").write_text("# myapp\n")

        # Write meta
        (proj_dir / "meta.yaml").write_text(
            f"name: myapp\nstatus: active\npriority: medium\n"
            f"repos:\n  - label: code\n    path: {tmp_path}\n"
            f"dates:\n  created: '{today}'\n  last_updated: '{today}'\n"
        )

        result = _run_cli(
            "session-start",
            "--cwd", str(tmp_path),
            env_extra={"PROJ_CONFIG": str(config_path)},
        )
        assert result.returncode == 0
        assert "myapp" in result.stdout
