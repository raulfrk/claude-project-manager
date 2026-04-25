# Shared-Venv-Only PYTHONPATH Loading Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace per-plugin uv-driven exec with a PYTHONPATH-based load against the shared marketplace venv, so 8 plugins can coexist in one venv without `server` package collision.

**Architecture:** `start.sh` resolves the shared venv (3-stage probe), then `exec env PYTHONPATH="$DIR" "$SHARED_VENV/bin/python" -m server.main`. PYTHONPATH dirs precede site-packages, so each plugin's own `$DIR/server/` wins regardless of what's installed in the venv. No plugin server packages are installed into the shared venv. No per-plugin venv fallback.

**Tech Stack:** bash, Python (subprocess), pytest, uv (install-time only).

**Spec:** `docs/superpowers/specs/2026-04-25-shared-venv-only-pythonpath-loading-design.md`

---

## File Structure

| File | Responsibility | Action |
|------|----------------|--------|
| `plugins/jira/start.sh` | Canonical plugin entrypoint — shared-venv probe + PYTHONPATH exec | Modify (rewrite) |
| `plugins/{confluence,proj,router,todoist,trello,wiki,worktree}/start.sh` | Byte-identical mirrors of canonical | Modify (cp from canonical) |
| `installer/tests/test_start_sh_shared_lookup.py` | Synthetic-tree tests for new exec form + new error path | Modify (rewrite assertions) |
| `installer/tests/test_cross_plugin_integration.py` | Live-shared-venv parallel boot test for all 8 plugins | Create |

---

## Task 1: Update test_start_sh_shared_lookup.py for new exec form (TDD red)

**Files:**
- Modify: `installer/tests/test_start_sh_shared_lookup.py`

The existing tests assert the old exec form (`uv run --frozen --no-sync server.main:main`). Update them to assert the new form (`PYTHONPATH=$DIR <venv>/bin/python -m server.main`) BEFORE touching `start.sh`. Tests should fail against the unmodified `start.sh`. After Task 2 patches `start.sh`, the same tests pass.

- [ ] **Step 1: Replace the test file content**

Full rewrite (current file does the old assertions; this writes the new ones):

```python
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
```

- [ ] **Step 2: Run tests to verify they fail against the unmodified start.sh**

Run: `uv run --no-sync pytest installer/tests/test_start_sh_shared_lookup.py -v`

Expected: most tests fail. The old `start.sh` execs `uv run` and writes `_shared/`, neither of which the new assertions look for. `test_all_start_sh_byte_identical` may still pass since the 8 files haven't been touched yet.

- [ ] **Step 3: Commit (red)**

```bash
git add installer/tests/test_start_sh_shared_lookup.py
git commit -m "test(start.sh): pin new PYTHONPATH exec form (red)

Tests now assert exec replaces \`uv run --frozen --no-sync \$SERVER\`
with \`<venv>/bin/python -m server.main\` under PYTHONPATH=\$DIR.
Drops _shared/ copy + per-plugin venv fallback assertions.
Tests fail until start.sh is rewritten in the next task."
```

---

## Task 2: Rewrite plugins/jira/start.sh (canonical)

**Files:**
- Modify: `plugins/jira/start.sh`

- [ ] **Step 1: Replace start.sh content with the new shape**

Full rewrite:

```bash
#!/bin/bash
set -euo pipefail
DIR="$(cd "$1" && pwd)"
# Arg 2 is preserved for back-compat with plugin .mcp.json files but unused.
# Runtime entry is always `python -m server.main`; PYTHONPATH=$DIR ensures
# each plugin's own server/ wins in import resolution.

MARKETPLACE_CACHE="$(cd "$DIR/../../.." && pwd)"
MARKETPLACE_NAME="$(basename "$MARKETPLACE_CACHE")"

# Resolve marketplace install location via known_marketplaces.json — the
# authoritative source-of-truth Claude Code maintains for github + directory
# source installs. Used as the primary venv probe (Stage 2a below).
KNOWN_MARKETPLACES="$HOME/.claude/plugins/known_marketplaces.json"
INSTALL_LOC=""
if [ -f "$KNOWN_MARKETPLACES" ] && command -v python3 >/dev/null 2>&1; then
  INSTALL_LOC=$(MARKETPLACE_NAME="$MARKETPLACE_NAME" KM_FILE="$KNOWN_MARKETPLACES" python3 -c '
import json, os
try:
    with open(os.environ["KM_FILE"]) as f:
        data = json.load(f)
    print(data.get(os.environ["MARKETPLACE_NAME"], {}).get("installLocation", ""))
except Exception:
    pass
' 2>/dev/null)
fi

# Locate shared venv via 3-stage probe.
SHARED_VENV=""
WALK_UP_FOUND=""

# Stage 1: walk up from $DIR for marketplace metadata.
walk_dir="$DIR"
while [ "$walk_dir" != "/" ] && [ -n "$walk_dir" ]; do
  if [ -f "$walk_dir/.claude-plugin/marketplace.json" ]; then
    WALK_UP_FOUND="$walk_dir"
    break
  fi
  walk_dir="$(dirname "$walk_dir")"
done
if [ -n "$WALK_UP_FOUND" ] && [ -f "$WALK_UP_FOUND/.venv/bin/python" ]; then
  SHARED_VENV="$WALK_UP_FOUND/.venv"
fi

# Stage 2a: installLocation-derived (directory-source installs).
if [ -z "$SHARED_VENV" ] && [ -n "$INSTALL_LOC" ] && [ -f "$INSTALL_LOC/.venv/bin/python" ]; then
  SHARED_VENV="$INSTALL_LOC/.venv"
fi

# Stage 2b: basename-derived (standard cache install).
if [ -z "$SHARED_VENV" ]; then
  BASENAME_CANDIDATE="$HOME/.claude/plugins/marketplaces/$MARKETPLACE_NAME/.venv"
  if [ -f "$BASENAME_CANDIDATE/bin/python" ]; then
    SHARED_VENV="$BASENAME_CANDIDATE"
  fi
fi

if [ -z "$SHARED_VENV" ]; then
  echo "ERROR: shared marketplace venv not found." >&2
  echo "Probed:" >&2
  echo "  walk-up from $DIR for .claude-plugin/marketplace.json: ${WALK_UP_FOUND:-<not found>}" >&2
  echo "  installLocation lookup: ${INSTALL_LOC:-<not resolved>}/.venv" >&2
  echo "  basename lookup: $HOME/.claude/plugins/marketplaces/$MARKETPLACE_NAME/.venv" >&2
  echo "Fix: cpm-install --reinstall" >&2
  exit 1
fi

exec env PYTHONPATH="$DIR" "$SHARED_VENV/bin/python" -m server.main
```

- [ ] **Step 2: Run tests to verify all pass except the byte-identical guard**

Run: `uv run --no-sync pytest installer/tests/test_start_sh_shared_lookup.py -v`

Expected: 6 of 7 tests pass. `test_all_start_sh_byte_identical` FAILS because only `plugins/jira/start.sh` has the new content; the other 7 still have old.

- [ ] **Step 3: Commit (canonical patched, sync pending)**

```bash
git add plugins/jira/start.sh
git commit -m "feat(start.sh): rewrite jira canonical for shared-venv-only PYTHONPATH exec

start.sh from ~110 lines to ~50. Drops _shared/ copy block + per-plugin
venv fallback. New exec: \`env PYTHONPATH=\$DIR \$SHARED_VENV/bin/python -m server.main\`.
Other 7 plugin start.sh files synced in next task."
```

---

## Task 3: Sync new start.sh to other 7 plugins

**Files:**
- Modify: `plugins/{confluence,proj,router,todoist,trello,wiki,worktree}/start.sh`

- [ ] **Step 1: Copy canonical to all 7 mirrors**

Run:

```bash
for p in confluence proj router todoist trello wiki worktree; do
  cp plugins/jira/start.sh "plugins/$p/start.sh"
done
md5sum plugins/*/start.sh
```

Expected: all 8 md5 hashes identical.

- [ ] **Step 2: Run tests to confirm green**

Run: `uv run --no-sync pytest installer/tests/test_start_sh_shared_lookup.py -v`

Expected: all 7 tests pass.

- [ ] **Step 3: Commit (green)**

```bash
git add plugins/{confluence,proj,router,todoist,trello,wiki,worktree}/start.sh
git commit -m "chore(start.sh): sync 7 mirrors to new canonical

All 8 plugin start.sh files now byte-identical (md5-locked).
test_all_start_sh_byte_identical guards against future drift."
```

---

## Task 4: Add cross-plugin integration test

**Files:**
- Create: `installer/tests/test_cross_plugin_integration.py`

This test catches namespace-collision regressions. Builds a real shared venv via `uv sync --extra plugins` against a synthetic marketplace tree containing 8 plugin shells with stubbed `server/main.py` files. Runs all 8 start.sh in parallel, asserts each loads its own stub.

- [ ] **Step 1: Write the test**

```python
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
```

- [ ] **Step 2: Run the test**

Run: `uv run --no-sync pytest installer/tests/test_cross_plugin_integration.py -m slow -v`

Expected: PASS. Each plugin's start.sh execs the shared venv's python with `PYTHONPATH=<plugin's cache server dir>`, so `python -m server.main` resolves the stub from THAT plugin's tree, not from any installed package.

If FAIL with all 8 plugins printing the same name: namespace collision regressed (someone is installing plugin server packages into the shared venv).

- [ ] **Step 3: Commit**

```bash
git add installer/tests/test_cross_plugin_integration.py
git commit -m "test(cross-plugin): assert all 8 plugins load own server module

Live shared-venv test: builds a real venv via \`uv sync --extra plugins\`
against the marketplace pyproject, then runs all 8 plugin start.sh in
parallel. Each plugin must print its own \`<name>-loaded\` from a stubbed
main module. Catches namespace-collision regressions.

Marked @pytest.mark.slow — skip in fast CI."
```

---

## Task 5: Run full installer suite

**Files:** none modified.

- [ ] **Step 1: Run fast suite**

Run: `uv run --no-sync pytest installer/tests --ignore=installer/tests/e2e -x`

Expected: all green (existing 735 + this plan's updates).

- [ ] **Step 2: Run slow suite (one-shot)**

Run: `uv run --no-sync pytest installer/tests -m slow -x`

Expected: cross-plugin test passes.

- [ ] **Step 3: Commit if any test files needed touch-ups**

If both suites green without touch-ups, skip this commit.

---

## Task 6: Manual verification

**Files:** none modified.

- [ ] **Step 1: Rebuild shared venv on this host**

Run:

```bash
rm -rf ~/.claude/plugins/marketplaces/claude-project-manager/.venv
cpm-install --reinstall --skip-wizard
```

Expected: cpm-install rebuilds the shared venv at `~/.claude/plugins/marketplaces/claude-project-manager/.venv/`. No `*-server` scripts in `<venv>/bin/` (they're not installed anymore — by design).

- [ ] **Step 2: Restart Claude Code**

The `/mcp` command should show all proj/router/wiki/etc. plugins reconnected. Specifically:

- proj exposes its full toolset (`todo_add`, `todo_list`, `proj_session_context`, `notes_append`, etc.) — not just `wt_*`/`zoxide_*`.
- router exposes `router_list_tool`, `router_fire_tool`, etc.
- wiki exposes `wiki_page_get`, `wiki_search_bm25`, etc.

If only `wt_*`/`zoxide_*` show, the namespace collision is back.

- [ ] **Step 3: Verify on the network-restricted host**

Pull dev, then:

```bash
cpm-install --reinstall --local-marketplace --branch dev
```

Restart Claude Code. Proj/router/wiki MCP should reconnect cleanly without any per-plugin `uv sync` attempts (those code paths are gone). Offline boot works because the shared venv has all libs and PYTHONPATH provides the plugin source.

---

## Self-Review

Spec coverage check:

| Spec section | Covered by |
|--------------|-----------|
| start.sh new shape | Task 2 |
| 8-file sync (md5-locked) | Task 3 + Task 1's `test_all_start_sh_byte_identical` |
| `_shared/` copy removed | Task 2 (copy block absent from rewrite) + Task 1 (no assertion left) |
| per-plugin venv fallback removed | Task 2 (block absent) + Task 1 (`test_per_plugin_venv_fallback_passes_no_dev` deleted) |
| INSTALL_LOC + 3-stage probe kept | Task 2 (preserved verbatim from a835cc0) |
| `*-server` script entries kept in pyprojects | Out of scope (Task 0 — no plugin pyproject changes; verified by absence in plan) |
| Test rewrite | Task 1 |
| New cross-plugin integration test | Task 4 |
| Verification | Tasks 5, 6 |
| `cpm-install --reinstall` recovery hint in error | Task 2's start.sh stderr block + Task 1's `test_no_shared_anywhere_errors` |
| uv-runtime decoupling | Task 1's `test_pythonpath_exec_does_not_invoke_uv` |

No placeholders. All file paths absolute. All code blocks complete.

Type/name consistency: `SHARED_VENV`, `INSTALL_LOC`, `MARKETPLACE_NAME`, `WALK_UP_FOUND` used consistently across Tasks 1-3. Stub log file is `python.log` everywhere it appears.

Plan is executable as-is.
