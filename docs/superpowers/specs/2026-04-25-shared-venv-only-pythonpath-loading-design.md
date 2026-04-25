# Shared-Venv-Only Plugin Loading via PYTHONPATH

**Date**: 2026-04-25
**Status**: design
**Owner**: claude-project-manager

## Problem

Each of 8 plugins (`proj`, `router`, `jira`, `confluence`, `todoist`, `trello`, `wiki`, `worktree`) ships
`plugins/<name>/server/server/main.py` with `packages = ["server"]` in its pyproject. Multiple plugins
installed into one venv collide on the top-level `server/` namespace — last writer wins. All `*-server`
script entry points then resolve `from server.main import main` against the wrong plugin's main module,
so only one plugin's MCP tools register at runtime.

A prior attempt (commit `351b967`) added all 8 servers as path-deps to root `pyproject.toml`'s `plugins`
extra, which exposed exactly this collision: `proj-server`, `router-server`, etc. all ended up running
worktree's main module. Reverted in `bf1afd2`.

Without those path-deps, `*-server` scripts are absent from the shared venv. `start.sh`'s
`uv run --frozen --no-sync $SERVER` then falls back to PATH, hits stale `~/.pyenv/.../bin/proj-server`
(global pip leftovers), and crashes with `ModuleNotFoundError: hook_dispatch`.

Two failure modes, one root cause: plugin server packages can't share a venv as long as they all
declare `packages = ["server"]`.

## Approach: PYTHONPATH-based loading

Don't install plugin server packages into any venv. The plugin's source already lives at
`~/.claude/plugins/cache/<mp>/<plugin>/<ver>/server/`. Set that on `PYTHONPATH` and import directly.
PYTHONPATH dirs precede site-packages in `sys.path`, so each plugin's `$DIR/server/` resolves to its
own module regardless of what's installed in the shared venv.

The shared marketplace venv keeps its existing role: hosting library deps (`mcp`, `httpx`, `pyyaml`,
`gitpython`, `claude-hook-transport`, `markdownify`, `beautifulsoup4`, `rank-bm25`, `packaging`).
No `*-server` scripts needed.

`start.sh` execs the shared venv's Python directly — no `uv run` wrapping at runtime.

```bash
exec env PYTHONPATH="$DIR" "$SHARED_VENV/bin/python" -m server.main
```

Each plugin's `$DIR` is unique, so `server.main` resolves to its own code. No collision possible.

### Why not source rename

Renaming each `server/` to `<plugin>_server/` and rewriting hundreds of `from server.X` imports across
8 plugins + tests would also fix the collision and keep the script-entry-point install model. Rejected
for blast radius vs. payoff: PYTHONPATH gets the same correctness with ~60 lines deleted from each
`start.sh` and zero source-code changes.

### Why drop the per-plugin venv fallback

The fallback path (`uv sync --frozen --no-dev` in the per-plugin cache dir) was a safety net for hosts
where the shared venv was absent. It's also a network-dependent path that fails on restricted hosts
(2026-04-25 incident). Removing it forces shared-venv to be the only supported runtime path. Failure
mode becomes a clean `cpm-install --reinstall` instruction instead of a long, possibly-failing uv sync
on every plugin start.

### Why drop the runtime `_shared` copy block

`start.sh` currently copies `plugins/_shared/` from the marketplace source into each plugin's cache
dir at runtime, so `uv sync --frozen` can resolve the `claude-hook-transport = { path = "../../_shared" }`
path-dep declared in each plugin pyproject. Without `uv sync` at runtime (the per-plugin fallback is
gone), no path-dep resolution happens. `claude-hook-transport` lives in the shared venv via the
marketplace root pyproject's `plugins` extra. Cache-side `_shared` copies become dead weight.

## start.sh new shape

```bash
#!/bin/bash
set -euo pipefail
DIR="$(cd "$1" && pwd)"
# Arg 2 ($SERVER) is preserved for back-compat with plugin .mcp.json files but
# unused at exec — entry is always `python -m server.main`.

MARKETPLACE_CACHE="$(cd "$DIR/../../.." && pwd)"
MARKETPLACE_NAME="$(basename "$MARKETPLACE_CACHE")"

# Resolve marketplace install location via known_marketplaces.json (a835cc0).
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

# 3-stage shared-venv probe.
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

Goes from 110 lines to ~50.

## Files to modify

All 8 `plugins/<name>/start.sh` (byte-identical, md5-locked). Same patch applied uniformly.

```
plugins/confluence/start.sh
plugins/jira/start.sh
plugins/proj/start.sh
plugins/router/start.sh
plugins/todoist/start.sh
plugins/trello/start.sh
plugins/wiki/start.sh
plugins/worktree/start.sh
```

## Tests

### Update: `installer/tests/test_start_sh_shared_lookup.py`

Existing 7 tests assume the old exec form (`uv run --frozen --no-sync server.main:main`) plus
`_shared/` copy assertions. Rewrite for new shape:

| Case | New assertion |
|------|---------------|
| `directory-source happy path` | exit 0; venv python invoked with `PYTHONPATH=$DIR` and `-m server.main` |
| `github-source happy path` | same as above against marketplaces dir layout |
| `known_marketplaces.json missing` | falls back to basename-derived venv; exit 0 |
| `known_marketplaces.json malformed` | falls back to basename-derived venv; exit 0 |
| `no shared venv anywhere` | exit 1; stderr contains `Run: cpm-install --reinstall` |

`test_no_shared_anywhere_errors` keeps its name; assertion changes from "_shared not found" to
"shared marketplace venv not found / Run: cpm-install --reinstall".

Drop test entirely:
- `test_per_plugin_venv_fallback_passes_no_dev` — fallback path removed; nothing to assert.

Drop assertions about `_shared` copy in cache (the copy block is gone).

Stub `python` in fake venv so exec succeeds without crashing on missing module — fake `bin/python`
records argv to a log file then exits 0.

Drop the `_all_start_sh_byte_identical` test? No — keep it. Still want md5 lock across all 8 files
to enforce manual-sync convention.

### New: `installer/tests/test_cross_plugin_integration.py`

Verifies all 8 plugins boot independently from a single shared venv and load each plugin's *own*
`server/main` module. Runs slow path — marked `@pytest.mark.slow`.

Sketch:

1. `tmp_path` fixture builds a synthetic marketplace tree:
   - Copies the live `pyproject.toml` + `uv.lock` to `<tmp>/marketplace/`
   - Symlinks `<tmp>/marketplace/plugins/_shared` → real `plugins/_shared/`
   - For each of 8 plugins, creates `<tmp>/cache/cpm/<plugin>/0.0.0/server/server/main.py`
     containing only `def main(): print(f"{plugin_name}-loaded")` (no MCP runtime)
   - Creates `<tmp>/known_marketplaces.json` pointing `installLocation` at `<tmp>/marketplace/`
2. Runs `uv sync --frozen --extra plugins` in `<tmp>/marketplace/` to build a real shared venv.
3. For each plugin, invokes `bash <repo>/plugins/<plugin>/start.sh <cache>/server <plugin>-server`
   with `HOME=<tmp>`. Captures stdout.
4. Asserts each plugin's stdout contains `{plugin_name}-loaded` (its own module ran, not another's).
5. Runs all 8 in parallel (`concurrent.futures`) to catch race conditions in venv access.

This test catches namespace-collision regressions: if anyone re-introduces installing plugin servers
into the shared venv, one plugin's main runs in another's slot and the assertion fails.

Test marked `slow` because the `uv sync` step is real (~2-3s on warm cache, longer cold). Run via
`pytest -m slow` in CI.

### Existing tests untouched

- `test_shared_venv.py` — covers `ensure_shared_venv` subprocess; unaffected.
- `test_shared_venv_deps.py` — drift detection; unaffected.
- `test_main.py::TestReinstallSharedVenv` — covers reinstall venv finalize; unaffected.
- `test_installer_flow.py::TestSharedVenvFinalize` — covers default TUI flow venv finalize; unaffected.

## Verification

1. `uv run --no-sync pytest installer/tests --ignore=installer/tests/e2e -x` — all green (existing
   735 + updates).
2. `uv run --no-sync pytest installer/tests -m slow` — the new cross-plugin integration test passes.
3. Manual: `cpm-install --reinstall` on this host, restart Claude Code, verify all 8 MCP plugins
   register their full toolset (proj exposes `todo_add` etc., router exposes `router_*`, wiki exposes
   `wiki_*`, etc. — not just `wt_*`/`zoxide_*`).
4. Manual on the network-restricted host: `cpm-install --reinstall --local-marketplace --branch dev`,
   restart Claude Code, verify offline plugin boot works (no per-plugin uv sync attempts).

## Out of scope

- Renaming plugin source packages to `<plugin>_server` (separate todo if ever desired; PYTHONPATH
  approach makes it unnecessary).
- Changing the per-plugin script entry points in plugin pyprojects (kept per design decision —
  harmless and lets standalone uv-installs of a single plugin still work).
- Cleaning up the stale `~/.pyenv/.../bin/*-server` global installs (user-side cleanup; documented).
- Bumping plugin versions (no semantic change to plugin behavior; users still see same MCP tool surface
  area, only the loader changed).

## Risks

- **Stale shared venv after pull**: existing users who pull dev get start.sh expecting shared venv to
  contain library deps. If their old shared venv was built with the path-dep version (commit 351b967,
  later reverted) it still has `*-server` scripts that won't be invoked anymore — harmless, just
  unused. Re-running `cpm-install --reinstall` is recommended but not required.
- **Plugin pyprojects keep `claude-hook-transport = { path = "../../_shared" }`**: harmless at runtime
  (PYTHONPATH-based exec doesn't trigger uv's dep resolution). Only relevant if someone manually
  `uv sync`s a plugin's own pyproject — that path-dep still works since `_shared/` is in the cache
  layout, but only after `cpm-install` has populated it. Documented in the per-plugin pyproject as a
  comment if the cleanup feels worthwhile.
- **PYTHONPATH leakage**: `env PYTHONPATH="$DIR"` only affects the exec'd process. No side effects.
- **uv version drift**: removing `uv run` from runtime path also removes uv as a runtime dependency.
  Users only need `uv` for install, not boot. Slight reduction in coupling.
