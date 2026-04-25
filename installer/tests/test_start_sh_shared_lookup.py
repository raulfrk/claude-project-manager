"""End-to-end tests for plugins/*/start.sh shared-venv probe + PYTHONPATH exec.

Drives the real start.sh script under a synthetic $HOME with a stub `python`
that records its argv to a log file. Asserts that start.sh:

1. Resolves the shared venv via the 3-stage probe (walk-up,
   known_marketplaces.json::installLocation, basename).
2. Execs the shared venv's python with `PYTHONPATH=$DIR` and `-m server.main`.
3. Errors loudly when no shared venv is found, with a `cpm-install --reinstall`
   recovery hint.

The `_shared/` copy block and per-plugin uv-sync fallback are gone — those
assertions are removed.
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


def _make_stub_python(venv_dir: Path, log_file: Path) -> None:
    """Create <venv>/bin/python that records argv + env to log_file then exits 0."""
    bin_dir = venv_dir / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / "python"
    stub.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            {{
              echo "ARGV: $*"
              echo "PYTHONPATH: ${{PYTHONPATH:-<unset>}}"
            }} >> {log_file}
            exit 0
            """
        )
    )
    stub.chmod(0o755)


@pytest.fixture()
def synthetic(tmp_path: Path):
    home = tmp_path / "home"
    claude = home / ".claude"
    plugins_dir = claude / "plugins"
    cache_plugin_dir = plugins_dir / "cache" / MARKETPLACE_NAME / PLUGIN / VERSION
    server_dir = cache_plugin_dir / "server"
    server_dir.mkdir(parents=True)
    (server_dir / "main.py").write_text("def main(): pass\n")

    python_log = tmp_path / "python.log"

    return {
        "home": home,
        "plugins_dir": plugins_dir,
        "known_marketplaces": plugins_dir / "known_marketplaces.json",
        "cache_marketplace": plugins_dir / "cache" / MARKETPLACE_NAME,
        "cache_plugin": cache_plugin_dir,
        "server_dir": server_dir,
        "python_log": python_log,
        "tmp": tmp_path,
    }


def _run_start_sh(synthetic) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(synthetic["home"])
    return subprocess.run(
        [
            "bash",
            str(START_SH),
            str(synthetic["server_dir"]),
            "jira-server",  # arg 2 is preserved for back-compat but unused at exec
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


def _populate_install_loc_with_venv(install_loc: Path, python_log: Path) -> None:
    install_loc.mkdir(parents=True, exist_ok=True)
    _make_stub_python(install_loc / ".venv", python_log)


def test_directory_source_happy_path(synthetic):
    """installLocation outside ~/.claude/plugins/marketplaces/ resolves shared venv."""
    install_loc = synthetic["tmp"] / "directory-source-marketplace"
    _populate_install_loc_with_venv(install_loc, synthetic["python_log"])
    _write_known_marketplaces(synthetic, install_loc)

    result = _run_start_sh(synthetic)

    assert result.returncode == 0, f"stderr={result.stderr}\nstdout={result.stdout}"
    log = synthetic["python_log"].read_text()
    assert "ARGV: -m server.main" in log
    assert f"PYTHONPATH: {synthetic['server_dir']}" in log


def test_github_source_happy_path(synthetic):
    """installLocation under ~/.claude/plugins/marketplaces/ resolves via Stage 2a/2b."""
    install_loc = synthetic["plugins_dir"] / "marketplaces" / MARKETPLACE_NAME
    _populate_install_loc_with_venv(install_loc, synthetic["python_log"])
    _write_known_marketplaces(synthetic, install_loc)

    result = _run_start_sh(synthetic)

    assert result.returncode == 0, f"stderr={result.stderr}\nstdout={result.stdout}"
    log = synthetic["python_log"].read_text()
    assert "ARGV: -m server.main" in log


def test_known_marketplaces_missing_falls_back(synthetic):
    """No JSON file → basename fallback still finds shared venv."""
    install_loc = synthetic["plugins_dir"] / "marketplaces" / MARKETPLACE_NAME
    _populate_install_loc_with_venv(install_loc, synthetic["python_log"])
    # Don't write known_marketplaces.json — basename lookup is the fallback.

    result = _run_start_sh(synthetic)

    assert result.returncode == 0, f"stderr={result.stderr}\nstdout={result.stdout}"
    assert "ARGV: -m server.main" in synthetic["python_log"].read_text()


def test_known_marketplaces_malformed_falls_back(synthetic):
    """Truncated JSON → silently fall through to basename lookup."""
    synthetic["plugins_dir"].mkdir(parents=True, exist_ok=True)
    synthetic["known_marketplaces"].write_text("{not valid json")
    install_loc = synthetic["plugins_dir"] / "marketplaces" / MARKETPLACE_NAME
    _populate_install_loc_with_venv(install_loc, synthetic["python_log"])

    result = _run_start_sh(synthetic)

    assert result.returncode == 0, f"stderr={result.stderr}\nstdout={result.stdout}"
    assert "ARGV: -m server.main" in synthetic["python_log"].read_text()


def test_no_shared_anywhere_errors(synthetic):
    """No installLocation .venv, no marketplaces dir .venv → exit 1 with reinstall hint."""
    bogus_loc = synthetic["tmp"] / "empty-dir"
    bogus_loc.mkdir()
    _write_known_marketplaces(synthetic, bogus_loc)
    # No .venv anywhere.

    result = _run_start_sh(synthetic)

    assert result.returncode == 1, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "shared marketplace venv not found" in result.stderr
    assert "cpm-install --reinstall" in result.stderr


def test_pythonpath_exec_does_not_invoke_uv(synthetic):
    """Runtime exec should not call `uv` — verifies uv-runtime decoupling."""
    install_loc = synthetic["tmp"] / "directory-source-marketplace"
    _populate_install_loc_with_venv(install_loc, synthetic["python_log"])
    _write_known_marketplaces(synthetic, install_loc)

    # Stub `uv` on PATH that fails loudly if invoked.
    uv_stub_dir = synthetic["tmp"] / "uv-tripwire"
    uv_stub_dir.mkdir()
    uv_stub = uv_stub_dir / "uv"
    uv_stub.write_text("#!/usr/bin/env bash\necho 'UV INVOKED' >&2\nexit 99\n")
    uv_stub.chmod(0o755)

    env = os.environ.copy()
    env["HOME"] = str(synthetic["home"])
    env["PATH"] = f"{uv_stub_dir}:{env.get('PATH', '')}"
    result = subprocess.run(
        ["bash", str(START_SH), str(synthetic["server_dir"]), "jira-server"],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )

    assert result.returncode == 0, f"uv was invoked? stderr={result.stderr}"
    assert "UV INVOKED" not in result.stderr
    # python3 is still allowed (used for known_marketplaces.json parsing).


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
