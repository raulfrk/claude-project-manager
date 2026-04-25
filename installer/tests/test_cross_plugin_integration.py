"""Cross-plugin integration test: every plugin loads its OWN server module.

Builds a real shared venv via `uv sync --extra plugins` against a synthetic
marketplace tree containing 8 plugin shells. Each shell's server/main.py is
unique (prints `<plugin>-loaded`). Runs all 8 plugin start.sh in parallel
and asserts each printed its own plugin name.

This catches namespace collision: if anyone re-introduces installing plugin
`server` packages into the shared venv, one plugin's main runs in another's
slot and the assertion fails.

Marked `slow` because the uv sync step is real (~2-3s on warm cache, longer
cold). Skip in fast CI; run via `pytest -m slow`.
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGINS = [
    "confluence",
    "jira",
    "proj",
    "router",
    "todoist",
    "trello",
    "wiki",
    "worktree",
]
MARKETPLACE_NAME = "claude-project-manager"
PLUGIN_VERSION = "0.0.0"


@pytest.mark.slow
def test_all_plugins_load_own_server_module(tmp_path: Path):
    home = tmp_path / "home"
    claude = home / ".claude"
    plugins_root = claude / "plugins"
    plugins_root.mkdir(parents=True)

    # 1. Synthetic marketplace tree at <tmp>/marketplace/, copying enough of
    #    the live repo for `uv sync --extra plugins` to succeed.
    marketplace = tmp_path / "marketplace"
    marketplace.mkdir()
    for fname in ("pyproject.toml", "uv.lock"):
        (marketplace / fname).write_bytes((REPO_ROOT / fname).read_bytes())
    # _shared is a path-dep; symlink the live source.
    (marketplace / "plugins").mkdir()
    os.symlink(REPO_ROOT / "plugins" / "_shared", marketplace / "plugins" / "_shared")
    # The marketplace's `installer` package is referenced by the wheel target;
    # symlink it so `uv sync` can resolve.
    os.symlink(REPO_ROOT / "installer", marketplace / "installer")
    os.symlink(REPO_ROOT / ".claude-plugin", marketplace / ".claude-plugin")

    # 2. Build the real shared venv. `--extra plugins` covers the library deps
    #    each plugin imports from at runtime.
    result = subprocess.run(
        ["uv", "sync", "--frozen", "--extra", "plugins"],
        cwd=marketplace,
        capture_output=True,
        text=True,
        timeout=300,
        stdin=subprocess.DEVNULL,
    )
    assert result.returncode == 0, (
        f"uv sync failed: stdout={result.stdout}\nstderr={result.stderr}"
    )
    shared_venv = marketplace / ".venv"
    assert (shared_venv / "bin" / "python").exists()

    # 3. Per plugin: build a cache shell with a stubbed server/main.py that
    #    prints `<plugin>-loaded` then exits cleanly.
    cache_marketplace = plugins_root / "cache" / MARKETPLACE_NAME
    cache_marketplace.mkdir(parents=True)
    plugin_dirs: dict[str, Path] = {}
    for plugin in PLUGINS:
        server_dir = cache_marketplace / plugin / PLUGIN_VERSION / "server"
        server_dir.mkdir(parents=True)
        (server_dir / "__init__.py").write_text("")
        # Make `server` a package and add a stub main module.
        server_pkg = server_dir / "server"
        server_pkg.mkdir()
        (server_pkg / "__init__.py").write_text("")
        (server_pkg / "main.py").write_text(
            f'def main():\n    print("{plugin}-loaded")\n\n'
            f'if __name__ == "__main__":\n    main()\n'
        )
        plugin_dirs[plugin] = server_dir

    # 4. known_marketplaces.json points at the synthetic marketplace.
    (plugins_root / "known_marketplaces.json").write_text(
        json.dumps(
            {
                MARKETPLACE_NAME: {
                    "source": {
                        "source": "directory",
                        "path": str(marketplace),
                    },
                    "installLocation": str(marketplace),
                }
            }
        )
    )

    # 5. Run all 8 plugin start.sh in parallel.
    def _run_one(plugin: str) -> tuple[str, subprocess.CompletedProcess[str]]:
        env = os.environ.copy()
        env["HOME"] = str(home)
        return plugin, subprocess.run(
            [
                "bash",
                str(REPO_ROOT / "plugins" / plugin / "start.sh"),
                str(plugin_dirs[plugin]),
                f"{plugin}-server",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = dict(pool.map(_run_one, PLUGINS))

    # 6. Each plugin must have printed ITS OWN identifier.
    failures: list[str] = []
    for plugin, result in results.items():
        if result.returncode != 0:
            failures.append(
                f"{plugin}: exit {result.returncode}\n  stdout={result.stdout!r}\n  stderr={result.stderr!r}"
            )
            continue
        expected = f"{plugin}-loaded"
        if expected not in result.stdout:
            failures.append(
                f"{plugin}: did not print {expected!r}\n  stdout={result.stdout!r}"
            )
    assert not failures, "Cross-plugin integration failures:\n" + "\n".join(failures)
