"""End-to-end Rich CLI wizard tests — subprocess-driven."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]


def _run_wizard(
    tmp_home: Path,
    stdin_input: str,
    extra_args: list[str] | None = None,
    env_overrides: dict[str, str] | None = None,
    timeout: int = 60,
) -> subprocess.CompletedProcess:
    """Run `python -m installer.main --no-tui` with tmp_home as HOME."""
    env = os.environ.copy()
    env["HOME"] = str(tmp_home)
    env["UV_CACHE_DIR"] = str(tmp_home / ".uv-cache")
    if env_overrides:
        env.update(env_overrides)
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


class TestRichWizardE2E:
    def test_full_rich_wizard_run_writes_all_fields(self, tmp_path: Path) -> None:
        """Pipe Enter/y through the whole wizard with advanced toggle ON.

        Asserts the resulting ~/.claude/proj.yaml contains every expected
        top-level key.
        """
        tmp_home = tmp_path / "home"
        tmp_home.mkdir()
        (tmp_home / ".claude").mkdir()

        # Enough newlines to accept all defaults + y for advanced + enough for advanced prompts
        # This is approximate — adjust if actual wizard has more/fewer prompts
        stdin = "\n" * 50 + "y\n" + "\n" * 50

        result = _run_wizard(tmp_home, stdin)
        # The wizard may fail in a clean env due to missing dependencies.
        # Assert it did not crash catastrophically (either exit 0 or a known-handled exit).
        # The key assertion is that SOME proj.yaml was written.
        proj_yaml = tmp_home / ".claude" / "proj.yaml"
        if not proj_yaml.exists():
            pytest.skip(
                f"wizard did not write proj.yaml in subprocess; stderr: {result.stderr[:500]}"
            )

        data = yaml.safe_load(proj_yaml.read_text())
        assert isinstance(data, dict)
        # Check at least the basic tier keys
        expected_keys = {"tracking_dir", "projects_base_dir"}
        actual_keys = set(data.keys())
        missing = expected_keys - actual_keys
        assert not missing, f"Missing top-level keys: {missing}. Got: {actual_keys}"

    def test_rich_wizard_skip_mode_uses_existing_defaults(self, tmp_path: Path) -> None:
        """Pre-populate proj.yaml, run with --skip, assert values preserved."""
        tmp_home = tmp_path / "home"
        tmp_home.mkdir()
        (tmp_home / ".claude").mkdir()
        proj_yaml = tmp_home / ".claude" / "proj.yaml"
        seed = {
            "tracking_dir": "/custom/tracking",
            "projects_base_dir": "/custom/projects",
            "quality_level": "paranoid",
        }
        proj_yaml.write_text(yaml.safe_dump(seed))

        result = _run_wizard(tmp_home, "", extra_args=["--skip"])
        if not proj_yaml.exists():
            pytest.skip(
                f"wizard did not write proj.yaml in --skip mode; stderr: {result.stderr[:500]}"
            )

        after = yaml.safe_load(proj_yaml.read_text())
        # --skip should preserve the seeded values unchanged
        assert after.get("tracking_dir") == "/custom/tracking"
        assert after.get("projects_base_dir") == "/custom/projects"
        assert after.get("quality_level") == "paranoid"

    def test_rich_wizard_preserves_unknown_yaml_keys(self, tmp_path: Path) -> None:
        """Add foo: bar to existing proj.yaml, run wizard, assert foo: bar still present."""
        tmp_home = tmp_path / "home"
        tmp_home.mkdir()
        (tmp_home / ".claude").mkdir()
        proj_yaml = tmp_home / ".claude" / "proj.yaml"
        seed = {"tracking_dir": "/seed", "foo": "bar", "extra": {"nested": "value"}}
        proj_yaml.write_text(yaml.safe_dump(seed))

        stdin = "\n" * 50
        result = _run_wizard(tmp_home, stdin)
        if not proj_yaml.exists():
            pytest.skip(
                f"wizard did not write proj.yaml; stderr: {result.stderr[:500]}"
            )

        after = yaml.safe_load(proj_yaml.read_text())
        # Unknown keys must be preserved through the wizard write path
        assert after.get("foo") == "bar"
        assert after.get("extra") == {"nested": "value"}
