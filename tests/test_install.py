"""Tests for install.sh and start.sh behavior.

These tests exercise the shell scripts via subprocess. Most are integration
tests that require ``uv`` to be available on the system.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALL_SH = REPO_ROOT / "install.sh"
START_SH = REPO_ROOT / "plugins" / "proj" / "start.sh"


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    """Run a command with common defaults."""
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=120,
        **kwargs,
    )


# ── install.sh unit tests (synthetic, no real deps) ────────────────


class TestInstallHelp:
    """Test --help and unknown option handling.

    install.sh checks for uv.lock before the case statement, so we need
    a minimal working directory with pyproject.toml and uv.lock present.
    """

    @pytest.fixture()
    def install_dir(self, tmp_path: Path) -> Path:
        """Create a minimal dir with install.sh, pyproject.toml, and uv.lock."""
        d = tmp_path / "repo"
        d.mkdir()
        shutil.copy2(INSTALL_SH, d / "install.sh")
        (d / "install.sh").chmod(0o755)
        (d / "pyproject.toml").write_text("[project]\nname='t'\nversion='0.1.0'\n")
        (d / "uv.lock").write_text("version = 1\n")
        return d

    def test_help_flag(self, install_dir: Path) -> None:
        r = _run(["bash", str(install_dir / "install.sh"), "--help"])
        assert r.returncode == 0
        assert "Usage:" in r.stdout

    def test_h_flag(self, install_dir: Path) -> None:
        r = _run(["bash", str(install_dir / "install.sh"), "-h"])
        assert r.returncode == 0
        assert "Usage:" in r.stdout

    def test_unknown_option(self, install_dir: Path) -> None:
        r = _run(["bash", str(install_dir / "install.sh"), "--bogus"])
        assert r.returncode != 0
        assert "Unknown option" in r.stderr


class TestInstallStaleLock:
    """Test that install.sh detects stale uv.lock (pyproject.toml newer)."""

    def test_stale_lock_error(self, tmp_path: Path) -> None:
        """When pyproject.toml is newer than uv.lock, should error."""
        # Create minimal files
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            textwrap.dedent("""\
            [project]
            name = "test"
            version = "0.1.0"
            requires-python = ">=3.12"
            dependencies = []
            """)
        )
        lock = tmp_path / "uv.lock"
        lock.write_text("version = 1\n")

        # Copy install.sh to tmp so DIR resolves to tmp_path
        install_copy = tmp_path / "install.sh"
        install_copy.write_text(INSTALL_SH.read_text())
        install_copy.chmod(0o755)

        # Make pyproject.toml strictly newer than uv.lock
        import time

        os.utime(lock, (time.time() - 10, time.time() - 10))
        os.utime(pyproject, (time.time(), time.time()))

        r = _run(["bash", str(install_copy)])
        assert r.returncode != 0
        assert "stale" in r.stderr.lower() or "uv.lock" in r.stderr

    def test_missing_lock_error(self, tmp_path: Path) -> None:
        """When uv.lock is missing, should error."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("[project]\nname = 'test'\nversion = '0.1.0'\n")

        install_copy = tmp_path / "install.sh"
        install_copy.write_text(INSTALL_SH.read_text())
        install_copy.chmod(0o755)

        r = _run(["bash", str(install_copy)])
        assert r.returncode != 0
        assert "uv.lock not found" in r.stderr


# ── install.sh integration tests ────────────────────────────────────


@pytest.mark.integration
class TestInstallIntegration:
    """Integration tests that run install.sh against the real repo.

    These require uv and network access (for initial dependency resolution).
    """

    @pytest.fixture(autouse=True)
    def _check_uv(self) -> None:
        if not shutil.which("uv"):
            pytest.skip("uv not available")

    @pytest.fixture(autouse=True)
    def _check_lock(self) -> None:
        if not (REPO_ROOT / "uv.lock").exists():
            pytest.skip("uv.lock not present (run 'uv lock' first)")

    def test_install_creates_venv(self, tmp_path: Path) -> None:
        """install.sh (no args) creates .venv with a working python."""
        # Work in a copy to avoid polluting the repo
        work = tmp_path / "repo"
        # Only copy the minimal files needed
        work.mkdir()
        shutil.copy2(REPO_ROOT / "pyproject.toml", work / "pyproject.toml")
        shutil.copy2(REPO_ROOT / "uv.lock", work / "uv.lock")
        shutil.copy2(INSTALL_SH, work / "install.sh")
        (work / "install.sh").chmod(0o755)

        # Copy plugins/_shared since it's referenced in uv sources
        shared_src = REPO_ROOT / "plugins" / "_shared"
        if shared_src.exists():
            shared_dst = work / "plugins" / "_shared"
            shutil.copytree(shared_src, shared_dst)

        r = _run(["bash", str(work / "install.sh")])
        assert r.returncode == 0, f"install.sh failed: {r.stderr}"

        venv_python = work / ".venv" / "bin" / "python"
        assert venv_python.exists(), ".venv/bin/python not created"

        dep_hash = work / ".venv" / ".dep-hash"
        assert dep_hash.exists(), ".dep-hash not written"

    def test_idempotent_rerun(self, tmp_path: Path) -> None:
        """Running install.sh twice succeeds and keeps the same venv."""
        work = tmp_path / "repo"
        work.mkdir()
        shutil.copy2(REPO_ROOT / "pyproject.toml", work / "pyproject.toml")
        shutil.copy2(REPO_ROOT / "uv.lock", work / "uv.lock")
        shutil.copy2(INSTALL_SH, work / "install.sh")
        (work / "install.sh").chmod(0o755)

        shared_src = REPO_ROOT / "plugins" / "_shared"
        if shared_src.exists():
            shared_dst = work / "plugins" / "_shared"
            shutil.copytree(shared_src, shared_dst)

        r1 = _run(["bash", str(work / "install.sh")])
        assert r1.returncode == 0, f"First run failed: {r1.stderr}"

        # Record the dep-hash
        hash1 = (work / ".venv" / ".dep-hash").read_text().strip()

        r2 = _run(["bash", str(work / "install.sh")])
        assert r2.returncode == 0, f"Second run failed: {r2.stderr}"

        hash2 = (work / ".venv" / ".dep-hash").read_text().strip()
        assert hash1 == hash2, "dep-hash changed on idempotent rerun"

    def test_update_picks_up_changes(self, tmp_path: Path) -> None:
        """--update re-syncs and updates the dep-hash."""
        work = tmp_path / "repo"
        work.mkdir()
        shutil.copy2(REPO_ROOT / "pyproject.toml", work / "pyproject.toml")
        shutil.copy2(REPO_ROOT / "uv.lock", work / "uv.lock")
        shutil.copy2(INSTALL_SH, work / "install.sh")
        (work / "install.sh").chmod(0o755)

        shared_src = REPO_ROOT / "plugins" / "_shared"
        if shared_src.exists():
            shared_dst = work / "plugins" / "_shared"
            shutil.copytree(shared_src, shared_dst)

        # Initial install
        r1 = _run(["bash", str(work / "install.sh")])
        assert r1.returncode == 0, f"Install failed: {r1.stderr}"

        hash_before = (work / ".venv" / ".dep-hash").read_text().strip()

        # Tamper with the dep-hash to simulate a change
        (work / ".venv" / ".dep-hash").write_text("stale-hash\n")

        r2 = _run(["bash", str(work / "install.sh"), "--update"])
        assert r2.returncode == 0, f"--update failed: {r2.stderr}"
        assert "updated" in r2.stdout.lower() or "Shared venv" in r2.stdout

        hash_after = (work / ".venv" / ".dep-hash").read_text().strip()
        # Should have been recomputed to the real hash
        assert hash_after == hash_before
        assert hash_after != "stale-hash"


# ── start.sh tests ──────────────────────────────────────────────────


class TestStartShSharedVenv:
    """Test start.sh shared-venv vs fallback logic.

    These tests create minimal directory structures to exercise the
    branching in start.sh without actually running MCP servers.
    """

    def _make_start_sh(self, tmp_path: Path) -> Path:
        """Create a modified start.sh that exits before exec uv run.

        Replace the final `exec uv ...` line with `echo VENV=$UV_PROJECT_ENVIRONMENT`
        so we can observe which venv was chosen without starting a server.
        """
        content = START_SH.read_text()
        # Replace the exec line to just print the chosen venv
        content = content.replace(
            'exec uv --directory "$DIR" run --frozen --no-sync "$SERVER"',
            'echo "CHOSEN_VENV=$UV_PROJECT_ENVIRONMENT"',
        )
        script = tmp_path / "start.sh"
        script.write_text(content)
        script.chmod(0o755)
        return script

    def _setup_plugin_cache_layout(
        self, tmp_path: Path, marketplace_name: str = "claude-project-manager"
    ) -> tuple[Path, Path]:
        """Create the expected plugin cache directory layout.

        Returns (server_dir, _marketplace_cache_dir).
        Layout: <marketplace>/<plugin>/<version>/server/
        """
        marketplace_cache = tmp_path / "cache" / marketplace_name
        marketplace_cache.mkdir(parents=True)

        plugin_dir = marketplace_cache / "proj" / "1.0.0"
        server_dir = plugin_dir / "server"
        server_dir.mkdir(parents=True)

        # Create a minimal pyproject.toml so uv sync won't fail at parse time
        (server_dir / "pyproject.toml").write_text(
            textwrap.dedent("""\
            [project]
            name = "test-plugin"
            version = "0.1.0"
            requires-python = ">=3.12"
            dependencies = []
            """)
        )

        # _shared needs to exist at ../../_shared relative to server_dir
        shared_dir = plugin_dir / "_shared"
        shared_dir.mkdir(parents=True)
        (shared_dir / "pyproject.toml").write_text(
            textwrap.dedent("""\
            [project]
            name = "claude-hook-transport"
            version = "0.3.3"
            """)
        )

        return server_dir, marketplace_cache

    def test_uses_shared_venv_when_present(self, tmp_path: Path) -> None:
        """When shared marketplace .venv exists, start.sh should use it."""
        server_dir, _marketplace_cache = self._setup_plugin_cache_layout(tmp_path)
        script = self._make_start_sh(tmp_path)

        # Copy the modified script into server_dir so DIR resolves correctly
        target_script = server_dir / "start.sh"
        target_script.write_text(script.read_text())
        target_script.chmod(0o755)

        # Create the shared venv at the marketplace cache level
        shared_venv = (
            tmp_path
            / ".claude"
            / "plugins"
            / "marketplaces"
            / "claude-project-manager"
            / ".venv"
        )
        shared_venv.mkdir(parents=True)
        (shared_venv / "bin").mkdir()
        (shared_venv / "bin" / "python").write_text("#!/bin/sh\n")
        (shared_venv / "bin" / "python").chmod(0o755)

        # Set HOME so the script finds the shared venv
        env = os.environ.copy()
        env["HOME"] = str(tmp_path)

        # Create the marketplaces source dir
        mp_src = (
            tmp_path / ".claude" / "plugins" / "marketplaces" / "claude-project-manager"
        )
        mp_src.mkdir(parents=True, exist_ok=True)
        # Copy _shared to the marketplace source
        plugins_shared = mp_src / "plugins" / "_shared"
        plugins_shared.mkdir(parents=True, exist_ok=True)
        (plugins_shared / "pyproject.toml").write_text(
            textwrap.dedent("""\
            [project]
            name = "claude-hook-transport"
            version = "0.3.3"
            """)
        )

        r = _run(
            ["bash", str(target_script), str(server_dir), "dummy_server"],
            env=env,
        )
        assert r.returncode == 0, f"start.sh failed: {r.stderr}"
        assert "CHOSEN_VENV=" in r.stdout
        # Should use the shared venv path
        assert str(shared_venv) in r.stdout

    def test_falls_back_to_per_plugin_venv(self, tmp_path: Path) -> None:
        """When shared venv is missing, start.sh falls back to per-plugin venv."""
        server_dir, _marketplace_cache = self._setup_plugin_cache_layout(tmp_path)
        script = self._make_start_sh(tmp_path)

        target_script = server_dir / "start.sh"
        target_script.write_text(script.read_text())
        target_script.chmod(0o755)

        # Do NOT create the shared venv -- this tests the fallback path
        env = os.environ.copy()
        env["HOME"] = str(tmp_path)

        # Create the marketplaces source dir with _shared
        mp_src = (
            tmp_path / ".claude" / "plugins" / "marketplaces" / "claude-project-manager"
        )
        mp_src.mkdir(parents=True)
        plugins_shared = mp_src / "plugins" / "_shared"
        plugins_shared.mkdir(parents=True)
        (plugins_shared / "pyproject.toml").write_text(
            textwrap.dedent("""\
            [project]
            name = "claude-hook-transport"
            version = "0.3.3"
            """)
        )

        # Also patch out uv sync so it doesn't actually run
        content = target_script.read_text()
        content = content.replace(
            'test -f "$DIR/.venv/bin/python" || uv sync --frozen --directory "$DIR"',
            'test -f "$DIR/.venv/bin/python" || echo "WOULD_SYNC=1"',
        )
        target_script.write_text(content)

        r = _run(
            ["bash", str(target_script), str(server_dir), "dummy_server"],
            env=env,
        )
        assert r.returncode == 0, f"start.sh failed: {r.stderr}"
        assert "CHOSEN_VENV=" in r.stdout
        # Should use the per-plugin venv
        assert str(server_dir / ".venv") in r.stdout
        # Should print the fallback message
        assert "falling back" in r.stderr.lower()


class TestStartShSharedSync:
    """Test that start.sh syncs _shared correctly."""

    def test_shared_version_mismatch_triggers_refresh(self, tmp_path: Path) -> None:
        """When cached _shared version differs from source, it should be refreshed."""
        # Build the layout
        marketplace_name = "claude-project-manager"
        marketplace_cache = tmp_path / "cache" / marketplace_name
        plugin_dir = marketplace_cache / "proj" / "1.0.0"
        server_dir = plugin_dir / "server"
        server_dir.mkdir(parents=True)

        (server_dir / "pyproject.toml").write_text(
            textwrap.dedent("""\
            [project]
            name = "test"
            version = "0.1.0"
            requires-python = ">=3.12"
            dependencies = []
            """)
        )

        # Cached _shared sits at ../../_shared relative to server/ dir,
        # which resolves to <marketplace>/<plugin>/_shared (NOT under version dir)
        # because SHARED_TARGET = $(cd "$DIR/../.." && pwd)/_shared
        # where DIR = .../proj/1.0.0/server, so ../../ = .../proj/
        proj_dir = marketplace_cache / "proj"
        shared_target = proj_dir / "_shared"
        shared_target.mkdir(parents=True)
        (shared_target / "pyproject.toml").write_text(
            textwrap.dedent("""\
            [project]
            name = "claude-hook-transport"
            version = "0.3.2"
            """)
        )

        # Source _shared at version 0.3.3 (newer)
        mp_src = tmp_path / ".claude" / "plugins" / "marketplaces" / marketplace_name
        mp_src.mkdir(parents=True)
        plugins_shared = mp_src / "plugins" / "_shared"
        plugins_shared.mkdir(parents=True)
        (plugins_shared / "pyproject.toml").write_text(
            textwrap.dedent("""\
            [project]
            name = "claude-hook-transport"
            version = "0.3.3"
            """)
        )
        # Add a marker file to verify the copy
        (plugins_shared / "marker.txt").write_text("refreshed")

        # Create the shared venv so the script doesn't fall back to uv sync
        shared_venv = mp_src / ".venv"
        shared_venv.mkdir(parents=True)
        (shared_venv / "bin").mkdir()
        (shared_venv / "bin" / "python").write_text("#!/bin/sh\n")
        (shared_venv / "bin" / "python").chmod(0o755)

        # Modify start.sh to skip exec
        content = (REPO_ROOT / "plugins" / "proj" / "start.sh").read_text()
        content = content.replace(
            'exec uv --directory "$DIR" run --frozen --no-sync "$SERVER"',
            'echo "DONE"',
        )
        target_script = server_dir / "start.sh"
        target_script.write_text(content)
        target_script.chmod(0o755)

        env = os.environ.copy()
        env["HOME"] = str(tmp_path)

        r = _run(
            ["bash", str(target_script), str(server_dir), "dummy_server"],
            env=env,
        )
        assert r.returncode == 0, f"start.sh failed: {r.stderr}"

        # Verify _shared was refreshed: marker.txt should now exist in cached _shared
        assert (shared_target / "marker.txt").exists(), "_shared was not refreshed"
        # Version should be updated
        new_version = (shared_target / "pyproject.toml").read_text()
        assert "0.3.3" in new_version


class TestStartShMissingShared:
    """Test start.sh behavior when _shared is not available anywhere."""

    def test_errors_when_shared_not_found(self, tmp_path: Path) -> None:
        """When _shared can't be found anywhere and isn't cached, should error."""
        marketplace_name = "claude-project-manager"
        marketplace_cache = tmp_path / "cache" / marketplace_name
        plugin_dir = marketplace_cache / "proj" / "1.0.0"
        server_dir = plugin_dir / "server"
        server_dir.mkdir(parents=True)

        (server_dir / "pyproject.toml").write_text(
            textwrap.dedent("""\
            [project]
            name = "test"
            version = "0.1.0"
            requires-python = ">=3.12"
            dependencies = []
            """)
        )

        # Do NOT create _shared at the target location or marketplace source
        # Create empty marketplace dir so the path doesn't match
        mp_src = tmp_path / ".claude" / "plugins" / "marketplaces" / marketplace_name
        mp_src.mkdir(parents=True)
        # No plugins/_shared here

        content = (REPO_ROOT / "plugins" / "proj" / "start.sh").read_text()
        content = content.replace(
            'exec uv --directory "$DIR" run --frozen --no-sync "$SERVER"',
            'echo "DONE"',
        )
        target_script = server_dir / "start.sh"
        target_script.write_text(content)
        target_script.chmod(0o755)

        env = os.environ.copy()
        env["HOME"] = str(tmp_path)

        r = _run(
            ["bash", str(target_script), str(server_dir), "dummy_server"],
            env=env,
        )
        assert r.returncode != 0
        assert "_shared" in r.stderr or "not found" in r.stderr


# ── dep-hash staleness detection ────────────────────────────────────


class TestDepHash:
    """Test the dep-hash mechanism in install.sh."""

    def test_compute_dep_hash_deterministic(self, tmp_path: Path) -> None:
        """compute_dep_hash should produce the same hash for same inputs."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("[project]\nname='test'\nversion='0.1.0'\n")
        lock = tmp_path / "uv.lock"
        lock.write_text("version = 1\nrequires-python = '>=3.12'\n")

        # Create a mini script that sources the hash function
        script = tmp_path / "hash_test.sh"
        script.write_text(
            textwrap.dedent(f"""\
            #!/bin/bash
            DIR="{tmp_path}"
            compute_dep_hash() {{
                cat "$DIR/pyproject.toml" "$DIR/uv.lock" \
                    | sha256sum | awk '{{print $1}}'
            }}
            H1=$(compute_dep_hash)
            H2=$(compute_dep_hash)
            echo "$H1"
            echo "$H2"
            """)
        )
        script.chmod(0o755)

        r = _run(["bash", str(script)])
        assert r.returncode == 0
        lines = r.stdout.strip().split("\n")
        assert len(lines) == 2
        assert lines[0] == lines[1], "Hash should be deterministic"
        assert len(lines[0]) == 64, "Should be a SHA-256 hex digest"

    def test_dep_hash_changes_with_content(self, tmp_path: Path) -> None:
        """Changing pyproject.toml content should change the dep-hash."""
        tmp_path / "pyproject.toml"
        lock = tmp_path / "uv.lock"
        lock.write_text("version = 1\n")

        script = tmp_path / "hash_test.sh"
        script.write_text(
            textwrap.dedent(f"""\
            #!/bin/bash
            DIR="{tmp_path}"
            compute_dep_hash() {{
                cat "$DIR/pyproject.toml" "$DIR/uv.lock" \
                    | sha256sum | awk '{{print $1}}'
            }}
            echo -n "[project]\\nname='v1'" > "$DIR/pyproject.toml"
            H1=$(compute_dep_hash)
            echo -n "[project]\\nname='v2'" > "$DIR/pyproject.toml"
            H2=$(compute_dep_hash)
            echo "$H1"
            echo "$H2"
            """)
        )
        script.chmod(0o755)

        r = _run(["bash", str(script)])
        assert r.returncode == 0
        lines = r.stdout.strip().split("\n")
        assert len(lines) == 2
        assert lines[0] != lines[1], "Hash should change when content changes"
