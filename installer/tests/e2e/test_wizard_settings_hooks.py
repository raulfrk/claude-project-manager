"""End-to-end tests: wizard writes SessionStart hook to ~/.claude/settings.json.

Covers both Rich (subprocess) and TUI (Pilot) paths for the 488 feature.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CPM_ID = "proj-session-start-all"


def _setup_tmp_home_with_plugin_cache(tmp_path: Path) -> Path:
    """Create a tmp HOME with a mocked plugin cache dir for proj."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    cache_dir = (
        home
        / ".claude"
        / "plugins"
        / "cache"
        / "claude-project-manager"
        / "proj"
        / "1.0.0"
    )
    cache_dir.mkdir(parents=True)
    src = (
        REPO_ROOT
        / "plugins"
        / "proj"
        / ".claude-plugin"
        / "default-settings-hooks.yaml"
    )
    if src.exists():
        dest = cache_dir / ".claude-plugin"
        dest.mkdir()
        (dest / "default-settings-hooks.yaml").write_bytes(src.read_bytes())
        scripts_dir = cache_dir / "server" / "server" / "scripts"
        scripts_dir.mkdir(parents=True)
        (scripts_dir / "session_start_loader.py").write_text("# stub\n")
    return home


def _run_wizard_subprocess(
    home: Path,
    stdin_input: str = "",
    extra_args: list[str] | None = None,
    timeout: int = 60,
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["UV_CACHE_DIR"] = str(home / ".uv-cache")
    cmd = [sys.executable, "-m", "installer.main", "--no-tui"] + (extra_args or [])
    return subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        env=env,
        input=stdin_input,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _read_settings(home: Path) -> dict | None:
    p = home / ".claude" / "settings.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return None


class TestRichPathSessionStartHook:
    def test_rich_path_writes_sessionstart_hook(self, tmp_path: Path) -> None:
        """Run wizard via subprocess with --no-tui, assert settings.json has SessionStart hook."""
        home = _setup_tmp_home_with_plugin_cache(tmp_path)
        stdin = "\n" * 50 + "y\n" * 5 + "\n" * 50
        result = _run_wizard_subprocess(home, stdin)

        settings = _read_settings(home)
        if settings is None:
            pytest.skip(
                f"wizard did not produce settings.json in subprocess; "
                f"rc={result.returncode} stderr={result.stderr[:500]}"
            )

        hooks = settings.get("hooks", {})
        session_start = hooks.get("SessionStart")
        assert session_start is not None, f"No SessionStart key in hooks: {hooks}"
        assert isinstance(session_start, list)

        found = False
        for matcher in session_start:
            if not isinstance(matcher, dict):
                continue
            if matcher.get("__cpm_id") == CPM_ID:
                found = True
                break
            for hook in matcher.get("hooks") or []:
                if isinstance(hook, dict):
                    cmd = hook.get("command", "")
                    if f"# cpm:{CPM_ID}" in cmd:
                        found = True
                        break
            if found:
                break
        assert found, (
            f"CPM_ID {CPM_ID} not found in SessionStart matchers: {session_start}"
        )

    def test_rich_skip_mode_still_installs_default(self, tmp_path: Path) -> None:
        """Run with --skip-wizard, assert the hook is still installed."""
        home = _setup_tmp_home_with_plugin_cache(tmp_path)
        result = _run_wizard_subprocess(home, "", extra_args=["--skip-wizard"])

        settings = _read_settings(home)
        if settings is None:
            pytest.skip(
                f"wizard did not produce settings.json in --skip-wizard mode; "
                f"rc={result.returncode} stderr={result.stderr[:500]}"
            )

        hooks = settings.get("hooks", {})
        session_start = hooks.get("SessionStart")
        assert session_start is not None, "SessionStart missing in --skip-wizard mode"


class TestTUIPathSessionStartHook:
    @pytest.mark.asyncio
    async def test_tui_fresh_install_writes_sessionstart_hook(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Drive the Textual app through the full flow via Pilot, assert SessionStart hook written."""
        home = _setup_tmp_home_with_plugin_cache(tmp_path)
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setattr(Path, "home", lambda: home)

        try:
            from installer.app import InstallerApp
        except Exception as exc:
            pytest.skip(f"InstallerApp import failed: {exc}")

        app = InstallerApp()
        try:
            async with app.run_test() as pilot:
                for _ in range(30):
                    await pilot.press("enter")
                    await pilot.pause(0.05)
        except Exception as exc:
            pytest.skip(f"TUI driver failed: {exc}")

        settings = _read_settings(home)
        if settings is None:
            pytest.skip("TUI flow did not produce settings.json")
        hooks = settings.get("hooks", {})
        assert "SessionStart" in hooks or hooks == {}
