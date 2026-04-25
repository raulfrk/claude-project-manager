"""End-to-end tests for plugins/*/start.sh `_shared` and shared-venv lookups.

Drives the real start.sh script under a synthetic $HOME with a stubbed `uv`
on PATH. Covers the directory-source bug fix (lookup via
known_marketplaces.json::installLocation) plus the --no-dev requirement on
the per-plugin venv fallback.
"""

from __future__ import annotations

import json
import os
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
START_SH = REPO_ROOT / "plugins" / "jira" / "start.sh"
MARKETPLACE_NAME = "claude-project-manager"
PLUGIN = "jira"
VERSION = "1.0.0"
SHARED_VERSION = "0.0.1"
SERVER_TARGET = "server.main:main"


def _write_pyproject(path: Path, name: str, version: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        textwrap.dedent(
            f"""\
            [project]
            name = "{name}"
            version = "{version}"
            """
        )
    )


def _make_venv(venv_dir: Path) -> None:
    """Create the minimum file start.sh probes for: <venv>/bin/python."""
    bin_dir = venv_dir / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    (bin_dir / "python").write_text("#!/bin/sh\nexit 0\n")
    (bin_dir / "python").chmod(0o755)


def _make_uv_stub(stub_dir: Path, log_file: Path) -> None:
    """Drop a `uv` shim that records its argv to log_file then exits 0."""
    stub_dir.mkdir(parents=True, exist_ok=True)
    stub = stub_dir / "uv"
    stub.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            printf '%s\\n' "$*" >> {log_file}
            exit 0
            """
        )
    )
    stub.chmod(0o755)


@pytest.fixture()
def synthetic(tmp_path: Path):
    """Build a synthetic $HOME + plugin cache layout.

    Returns a namespace dict so tests can layer in installLocation,
    marketplaces dir, etc. as needed.
    """
    home = tmp_path / "home"
    claude = home / ".claude"
    plugins_dir = claude / "plugins"
    cache_plugin_dir = plugins_dir / "cache" / MARKETPLACE_NAME / PLUGIN / VERSION
    server_dir = cache_plugin_dir / "server"
    server_dir.mkdir(parents=True)
    (server_dir / "main.py").write_text("def main(): pass\n")

    stub_dir = tmp_path / "uv-stub"
    uv_log = tmp_path / "uv.log"
    _make_uv_stub(stub_dir, uv_log)

    return {
        "home": home,
        "plugins_dir": plugins_dir,
        "known_marketplaces": plugins_dir / "known_marketplaces.json",
        "cache_marketplace": plugins_dir / "cache" / MARKETPLACE_NAME,
        "cache_plugin": cache_plugin_dir,
        "server_dir": server_dir,
        "stub_dir": stub_dir,
        "uv_log": uv_log,
        "tmp": tmp_path,
    }


def _run_start_sh(synthetic) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(synthetic["home"])
    env["PATH"] = f"{synthetic['stub_dir']}:{env.get('PATH', '')}"
    return subprocess.run(
        [
            "bash",
            str(START_SH),
            str(synthetic["server_dir"]),
            SERVER_TARGET,
        ],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )


def _write_known_marketplaces(synthetic, install_location: str | Path) -> None:
    synthetic["plugins_dir"].mkdir(parents=True, exist_ok=True)
    synthetic["known_marketplaces"].write_text(
        json.dumps(
            {
                MARKETPLACE_NAME: {
                    "source": {"source": "directory", "path": str(install_location)},
                    "installLocation": str(install_location),
                }
            }
        )
    )


def _populate_install_loc(install_loc: Path, *, with_venv: bool) -> None:
    _write_pyproject(
        install_loc / "plugins" / "_shared" / "pyproject.toml",
        name="claude-hook-transport",
        version=SHARED_VERSION,
    )
    if with_venv:
        _make_venv(install_loc / ".venv")


def _shared_target(synthetic) -> Path:
    """Path start.sh writes the copied _shared into."""
    return synthetic["cache_marketplace"] / PLUGIN / "_shared"


def test_directory_source_happy_path(synthetic):
    """installLocation outside ~/.claude/plugins/marketplaces/ resolves _shared + venv."""
    install_loc = synthetic["tmp"] / "directory-source-marketplace"
    _populate_install_loc(install_loc, with_venv=True)
    _write_known_marketplaces(synthetic, install_loc)

    result = _run_start_sh(synthetic)

    assert result.returncode == 0, f"stderr={result.stderr}\nstdout={result.stdout}"
    assert (_shared_target(synthetic) / "pyproject.toml").exists()
    # exec stage hits the uv stub: should record `--directory <dir> run --frozen --no-sync server.main:main`
    log = synthetic["uv_log"].read_text() if synthetic["uv_log"].exists() else ""
    assert "run --frozen --no-sync server.main:main" in log
    # No `uv sync` line means shared venv was found (not the per-plugin fallback path).
    assert "sync --frozen" not in log


def test_github_source_happy_path(synthetic):
    """installLocation under ~/.claude/plugins/marketplaces/ — both Stage 2a and 2b match."""
    install_loc = synthetic["plugins_dir"] / "marketplaces" / MARKETPLACE_NAME
    _populate_install_loc(install_loc, with_venv=True)
    _write_known_marketplaces(synthetic, install_loc)

    result = _run_start_sh(synthetic)

    assert result.returncode == 0, f"stderr={result.stderr}\nstdout={result.stdout}"
    assert (_shared_target(synthetic) / "pyproject.toml").exists()


def test_known_marketplaces_missing_falls_back(synthetic):
    """No JSON file → MARKETPLACE_SRC fallback still works."""
    # Don't create known_marketplaces.json; populate marketplaces dir directly.
    install_loc = synthetic["plugins_dir"] / "marketplaces" / MARKETPLACE_NAME
    _populate_install_loc(install_loc, with_venv=True)

    result = _run_start_sh(synthetic)

    assert result.returncode == 0, f"stderr={result.stderr}\nstdout={result.stdout}"
    assert (_shared_target(synthetic) / "pyproject.toml").exists()


def test_known_marketplaces_malformed_falls_back(synthetic):
    """Truncated JSON → silently fall through to MARKETPLACE_SRC."""
    synthetic["plugins_dir"].mkdir(parents=True, exist_ok=True)
    synthetic["known_marketplaces"].write_text("{not valid json")
    install_loc = synthetic["plugins_dir"] / "marketplaces" / MARKETPLACE_NAME
    _populate_install_loc(install_loc, with_venv=True)

    result = _run_start_sh(synthetic)

    assert result.returncode == 0, f"stderr={result.stderr}\nstdout={result.stdout}"
    assert (_shared_target(synthetic) / "pyproject.toml").exists()


def test_no_shared_anywhere_errors(synthetic):
    """No installLocation, no MARKETPLACE_SRC, no sibling cache → preserve original error."""
    # known_marketplaces.json points at a path that doesn't contain _shared.
    bogus_loc = synthetic["tmp"] / "empty-dir"
    bogus_loc.mkdir()
    _write_known_marketplaces(synthetic, bogus_loc)

    result = _run_start_sh(synthetic)

    assert result.returncode == 1, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "_shared (claude-hook-transport) not found" in result.stderr


def test_per_plugin_venv_fallback_passes_no_dev(synthetic):
    """Shared-venv miss → uv sync invocation must include --no-dev (production runtime)."""
    install_loc = synthetic["tmp"] / "directory-source-marketplace"
    # _shared present, but NO .venv anywhere → triggers per-plugin venv fallback.
    _populate_install_loc(install_loc, with_venv=False)
    _write_known_marketplaces(synthetic, install_loc)

    result = _run_start_sh(synthetic)

    assert result.returncode == 0, f"stderr={result.stderr}\nstdout={result.stdout}"
    log = synthetic["uv_log"].read_text()
    # Verify the per-plugin fallback fired with --no-dev.
    sync_lines = [ln for ln in log.splitlines() if ln.startswith("sync ")]
    assert sync_lines, f"expected a `uv sync` invocation, got log:\n{log}"
    assert any("--no-dev" in ln for ln in sync_lines), (
        f"`uv sync` ran without --no-dev:\n{log}"
    )
    assert any("--frozen" in ln for ln in sync_lines)


def test_all_start_sh_byte_identical():
    """All 8 plugin start.sh files must remain byte-identical (manual sync convention)."""
    plugins_dir = REPO_ROOT / "plugins"
    candidates = sorted(plugins_dir.glob("*/start.sh"))
    assert len(candidates) == 8, f"expected 8 start.sh files, found {len(candidates)}"
    contents = {p: p.read_bytes() for p in candidates}
    canonical = contents[START_SH]
    drifted = [str(p) for p, c in contents.items() if c != canonical]
    assert not drifted, "start.sh drift detected vs jira/start.sh:\n  " + "\n  ".join(
        drifted
    )
