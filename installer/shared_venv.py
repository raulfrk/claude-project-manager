"""Shared marketplace venv creation.

Creates a single .venv at the marketplace root so all plugins share one
Python environment. Replaces the per-plugin uv-sync fallback that fires
when no shared venv is found.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from installer.errors import InstallerError
from installer.plugin_cli import MARKETPLACE_NAME

_UV_SYNC_TIMEOUT = 300  # seconds; uv sync can be slow on cold cache


def marketplaces_dir() -> Path:
    """Standard install location for the marketplace symlink/clone."""
    return Path.home() / ".claude" / "plugins" / "marketplaces" / MARKETPLACE_NAME


def ensure_shared_venv(marketplace_dir: Path) -> None:
    """Create or refresh the shared marketplace venv.

    Runs `uv sync --frozen --extra plugins` in marketplace_dir to create
    marketplace_dir/.venv/ with all plugin runtime deps installed.

    Idempotent: uv reuses cache on repeat calls.

    Raises:
        InstallerError: if uv sync fails (non-zero exit, timeout, or
            uv not found on PATH).
    """
    try:
        result = subprocess.run(
            ["uv", "sync", "--frozen", "--extra", "plugins"],
            cwd=marketplace_dir,
            capture_output=True,
            text=True,
            check=False,
            timeout=_UV_SYNC_TIMEOUT,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired as exc:
        raise InstallerError(
            f"uv sync timed out after {_UV_SYNC_TIMEOUT}s in {marketplace_dir}"
        ) from exc
    except FileNotFoundError as exc:
        raise InstallerError(
            "uv not found on PATH — install uv before running cpm-install"
        ) from exc
    if result.returncode != 0:
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        detail = stderr or stdout
        raise InstallerError(
            f"uv sync failed (exit {result.returncode}) in {marketplace_dir}\n{detail}"
        )
