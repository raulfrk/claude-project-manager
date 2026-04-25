# Shared-venv lookup + creation fix — Design

**Date**: 2026-04-25
**Branch**: `feat/shared-venv-lookup-fix`
**Status**: draft (spec)

## Problem

Two coupled bugs in the plugin shared-venv path:

### Bug 1 — `start.sh` lookup misses on `--local-marketplace` installs

Every plugin's `plugins/<plugin>/start.sh` (8 byte-identical files) derives the marketplace name like this:

```bash
MARKETPLACE_CACHE="$(cd "$DIR/../../.." && pwd)"        # line 12
MARKETPLACE_NAME="$(basename "$MARKETPLACE_CACHE")"     # line 13
SHARED_VENV="$HOME/.claude/plugins/marketplaces/$MARKETPLACE_NAME/.venv"  # line 49
```

When the marketplace is registered via `cpm-install --local-marketplace`, Claude Code's plugin cache lays out at `~/.claude/plugins/cache/local-marketplace/<plugin>/<version>/server/` (cache dir basename comes from the local-clone dir name, not the marketplace metadata `name`). The marketplace symlink still lives at `~/.claude/plugins/marketplaces/claude-project-manager/` (named after `marketplace.json::name`). The basename-derived lookup at line 49 misses, every plugin silently falls back to per-plugin `uv sync` (line 53), and that fallback requires unrestricted PyPI access.

The fallback log line — `"Shared venv not found, falling back to per-plugin venv"` — hides the actual mismatch. No way to diagnose which path was tried.

### Bug 2 — Installer never creates the shared venv

Verified across `installer/`: there is **no code path** that creates `~/.claude/plugins/marketplaces/<name>/.venv`. The shared-venv branch in `start.sh` (lines 49-51) is dead code on the standard install path because the venv it expects never materializes. Only `scripts/presync.sh` creates anything close, and it builds **per-plugin** venvs, not a shared one. Consequence: every plugin always falls through to per-plugin `uv sync` on every install. The shared-venv optimization referenced in commit `23eecbe` ("Shared venv: single .venv for all plugins, 8 start.sh updated") landed only on the read side.

### Bug 3 — `scripts/presync.sh` plugin list stale

`plugins=(proj sandbox worktree trello jira hooks todoist zoxide)` references `sandbox` (folded into `proj` in `0608506`), `hooks` (renamed to `router` in `5b93248`), and `zoxide` (folded into `worktree` in `ae2b79c`). Missing: `confluence`, `router`, `wiki`. Dev contributors running `presync.sh` get errors on stale plugins and silently skip the new ones.

## Solution

Three coordinated changes. Each works independently; together they make shared-venv the default actually-functional behavior.

## Architecture

### Component 1 — `start.sh` shared-venv lookup

Replace lines 48-56 in all 8 `plugins/*/start.sh` files. Files are byte-identical (verified via `diff` across all 8). New lookup is a three-stage cascade:

```bash
# Locate shared venv via two-stage lookup
SHARED_VENV=""
SHARED_VENV_SOURCE=""
WALK_UP_FOUND=""

# Stage 1: walk up from $DIR looking for marketplace metadata
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
  SHARED_VENV_SOURCE="walk-up at $WALK_UP_FOUND"
fi

# Stage 2: basename-derived lookup (covers standard cache install)
if [ -z "$SHARED_VENV" ]; then
  BASENAME_CANDIDATE="$HOME/.claude/plugins/marketplaces/$MARKETPLACE_NAME/.venv"
  if [ -f "$BASENAME_CANDIDATE/bin/python" ]; then
    SHARED_VENV="$BASENAME_CANDIDATE"
    SHARED_VENV_SOURCE="basename '$MARKETPLACE_NAME'"
  fi
fi

if [ -n "$SHARED_VENV" ]; then
  export UV_PROJECT_ENVIRONMENT="$SHARED_VENV"
else
  echo "[start.sh] shared venv not found, falling back to per-plugin venv:" >&2
  echo "  walk-up from $DIR for .claude-plugin/marketplace.json: ${WALK_UP_FOUND:-<not found>}" >&2
  echo "  basename lookup tried: $HOME/.claude/plugins/marketplaces/$MARKETPLACE_NAME/.venv" >&2
  echo "  per-plugin venv: $DIR/.venv (will run 'uv sync --frozen')" >&2
  export UV_PROJECT_ENVIRONMENT="$DIR/.venv"
  uv sync --frozen --directory "$DIR"
fi
```

**Stage rationale:**
- Stage 1 (walk-up): handles `--local-marketplace` install. `$DIR` is `<local-clone>/plugins/<plugin>/server`; walk-up finds `<local-clone>/.claude-plugin/marketplace.json` → uses `<local-clone>/.venv`. Marker `.claude-plugin/marketplace.json` is unambiguous (only marketplace roots have it).
- Stage 2 (basename): handles standard cache install. `$DIR` is `<cache>/<name>/<plugin>/<version>/server`; cache dir has no `marketplace.json` so walk-up finds nothing, basename derives `<name>` correctly, falls through to existing logic at the marketplaces-symlink path.
- Stage 3 (per-plugin + diagnostic): both missed. Three log lines name every path tried so the user can diagnose without reading source.

**Walk-up depth:** unbounded (stops at `/`). Bash filesystem traversal is fast; no realistic depth where this would matter.

**`MARKETPLACE_NAME` retained** because Stage 2 still needs it. Lines 11-14 unchanged.

### Component 2 — Installer-side shared-venv creation

New module `installer/shared_venv.py` with one public function:

```python
def ensure_shared_venv(marketplace_dir: Path) -> None:
    """Create or refresh the shared marketplace venv.

    Runs `uv sync --frozen --extra plugins` in marketplace_dir, which has the
    marketplace-root pyproject.toml (project name "cpm-install", optional
    extra `plugins` listing all runtime deps). Creates marketplace_dir/.venv/.

    Idempotent: uv reuses cache on repeat calls.

    Raises:
        InstallerError: if uv sync fails (network, lockfile mismatch, etc.).
    """
```

Implementation: thin `subprocess.run` wrapper mirroring `installer/plugin_cli._run`; timeout 300s; `stdin=DEVNULL`; raises `InstallerError` with stderr captured on non-zero exit.

**Wrapper-based wiring** (avoids missed call sites): add `installer/shared_venv.py::add_marketplace_with_shared_venv(source, branch)` that calls `add_marketplace(source, branch)` then `ensure_shared_venv(<dir>)`. Replace all 6 existing `add_marketplace` call sites with the wrapper:

| File | Line(s) | Notes |
|------|---------|-------|
| `installer/main.py::_install` | 107, 118 | Standard + branch-update paths |
| `installer/main.py::_reinstall` | 247 | Reinstall path |
| `installer/flow/installer_flow.py` | 345, 355, 516 | Alternative flow entry points |

**Marketplace dir resolution** (inside the wrapper):
- Always: `~/.claude/plugins/marketplaces/<name>/` — `<name>` comes from `installer.plugin_cli.MARKETPLACE_NAME` (existing module-level constant, hardcoded to `claude-project-manager`). Avoids the wheel-bundled-vs-source-tree split that would force reading `installer/marketplace.json` w/ a fallback to `.claude-plugin/marketplace.json`.
- If `source` is a filesystem path (`Path(source).exists()`) AND resolves to `LOCAL_CLONE_DIR`: also call `ensure_shared_venv(LOCAL_CLONE_DIR)` so walk-up from `start.sh` resolves at the local clone. Both calls are needed because Claude Code may reference either location depending on cache state; both are idempotent.

`installer/update.py` is version-comparison utilities only — no `add_marketplace` calls. No changes needed there.

**Failure handling:** `ensure_shared_venv` raises on failure; call sites catch and log a yellow warning, then continue. Plugins fall back to per-plugin venv at runtime, exactly preserving today's behavior. Do **not** abort install on shared-venv failure — that would regress users in restricted-network environments who can still use per-plugin sync if their PyPI mirror works.

**Marketplace name resolution:** import `MARKETPLACE_NAME` from `installer.plugin_cli` (already used elsewhere as the source-of-truth constant). No extra plumbing, no file IO at install time.

### Component 3 — `scripts/presync.sh` sweep

Two changes:

1. Replace `plugins=(...)` array on line 19 with current tracked plugins:
   ```bash
   plugins=(proj worktree trello jira router todoist confluence wiki)
   ```
   Drops `sandbox`, `hooks`, `zoxide` (folded/renamed). Adds `confluence`, `router`, `wiki`.

2. Append a shared-venv creation step after the per-plugin loop:
   ```bash
   echo "syncing shared marketplace venv ..."
   uv sync --extra plugins --directory "$REPO_ROOT"
   ```
   So dev contributors running `presync.sh` from a fresh clone get the same shared-venv setup as installed users.

## Testing

### Manual verification (must pass before merge)

1. **Standard install** — wipe `~/.claude/plugins/marketplaces/claude-project-manager/`, run `cpm-install`. Expect: `~/.claude/plugins/marketplaces/claude-project-manager/.venv/bin/python` exists. Start any plugin's MCP server (e.g., via Claude Code restart). Expect: no `[start.sh]` fallback log lines in stderr.
2. **Local-marketplace install** — `cpm-install --local-marketplace`. Expect: `<LOCAL_CLONE_DIR>/.venv/bin/python` exists. Start a plugin. Expect: walk-up resolves to local clone; no fallback log.
3. **Fallback diagnostic** — manually `rm -rf <marketplace>/.venv`; restart Claude Code. Expect stderr contains all three log lines from Stage 3 with concrete paths.
4. **Presync** — fresh repo clone, `bash scripts/presync.sh`. Expect: 8 plugins sync (no "skip <plugin>" lines for tracked plugins), shared venv created at repo root.

### Automated tests

| Layer | Test | Coverage |
|-------|------|----------|
| Unit | `installer/tests/test_shared_venv.py` (new) | `ensure_shared_venv` happy path, subprocess args, error propagation. Mock `subprocess.run`. |
| Unit | Extend `installer/tests/test_main.py` | `_install` + `_reinstall` call `ensure_shared_venv` post-`add_marketplace`; handle `InstallerError` w/ warning + continue. |
| E2E | Extend `installer/tests/e2e/test_install.py` (or nearest equivalent) | Full installer run in container; assert `~/.claude/plugins/marketplaces/<name>/.venv` exists post-install. |
| Manual only | `start.sh` lookup logic | No bash test infrastructure; rely on manual verification + E2E install catching gross failures. |

## Out of scope (track separately)

Auto-add as todos after `ExitPlanMode`:

1. **Empty stale dirs** — `plugins/sandbox/` and `plugins/zoxide/` (visible in `git status` as untracked) should be removed from working tree. Not a code bug; cleanup hygiene.

## Risks

- **`uv sync --extra plugins` at marketplace dir** installs both installer (`cpm-install`) deps AND plugin runtime deps into one venv. The mixed venv has no harm at runtime — `start.sh` only uses it for plugin Python — but is mildly surprising. Alternative (`--all-extras` or splitting deps into a separate `[project.optional-dependencies] runtime`) adds complexity for no functional gain. Keep as-is.
- **Walk-up matching the wrong marketplace** if a user has nested marketplace clones. Stops at first match (deepest). Acceptable; user can configure explicitly via env var if this collides in practice.
- **Failure to create shared venv** in restricted-PyPI environments. Mitigated by warn-and-continue: per-plugin venv path still works exactly as today.
