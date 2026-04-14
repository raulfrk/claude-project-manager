"""Plugin server import smoke tests — verify each plugin's server package can be imported.

Gap covered: bug 591 shipped with httpx missing from a plugin's runtime deps
because the local venv was stale and tests never verified real imports.

Motivation: the e2e test suite mocks plugin_cli.install_plugin, so it never
runs the actual plugin servers. These tests import each server package in an
isolated subprocess to catch missing dependencies early.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

# Root of the monorepo
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PLUGINS_DIR = _PROJECT_ROOT / "plugins"

# Each plugin that has a server/ directory with its own pyproject.toml
_PLUGIN_SERVERS = sorted(p.parent for p in _PLUGINS_DIR.glob("*/server/pyproject.toml"))


@pytest.mark.slow
class TestPluginServerImports:
    """Verify each plugin server can import its package without errors.

    Uses ``uv run`` with ``--directory`` for dep isolation — each plugin's
    pyproject.toml must resolve independently. This catches missing deps
    like httpx (bug 591).
    """

    @pytest.mark.parametrize(
        "server_dir",
        _PLUGIN_SERVERS,
        ids=[p.parent.name for p in _PLUGIN_SERVERS],
    )
    def test_server_import(self, server_dir: Path) -> None:
        """Import the server package in an isolated subprocess."""
        result = subprocess.run(
            [
                "uv",
                "run",
                "--directory",
                str(server_dir),
                "python",
                "-c",
                "import server",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, (
            f"Failed to import server package in {server_dir.relative_to(_PROJECT_ROOT)}:\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )
