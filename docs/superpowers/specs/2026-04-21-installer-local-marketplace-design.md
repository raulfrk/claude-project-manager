# Installer `--local-marketplace` flag — Design

**Todo**: 683
**Date**: 2026-04-21
**Status**: draft (brainstorming)

## Problem

The installer registers the marketplace from a hardcoded GitHub ref (`raulfrk/claude-project-manager`) via `claude plugin marketplace add`. For local development and iteration on marketplace/plugin code, there is no way to point the installer at a local working copy without manually editing `plugin_cli.py`.

## Solution

Add `--local-marketplace` flag to the installer CLI. When passed, the installer:

1. Clones (or updates) the marketplace repo into a fixed cache location.
2. Registers the marketplace using the local clone's absolute path as the source.
3. Installs plugins as usual.

If the marketplace is already registered (from any source — GitHub or prior local clone), the existing "remove + re-add" behavior applies.

## Architecture

### New module: `installer/local_marketplace.py`

Module constants:

```python
LOCAL_CLONE_DIR = Path.home() / ".cache" / "claude-project-manager" / "local-marketplace"
_HTTPS_SOURCE = "https://github.com/raulfrk/claude-project-manager.git"
_GIT_TIMEOUT = 120  # seconds
```

Public API:

```python
def ensure_local_clone(branch: str | None = None) -> Path:
    """Ensure LOCAL_CLONE_DIR is a clone of the marketplace at the given branch.

    - If dir missing: git clone _HTTPS_SOURCE LOCAL_CLONE_DIR
    - If dir exists: git fetch origin && git checkout <branch-or-default> && git reset --hard origin/<branch-or-default>
    - Returns absolute Path to the clone.
    - Raises InstallerError on any git failure.
    """
```

Internal helpers (private):

- `_run_git(args: list[str], cwd: Path | None) -> subprocess.CompletedProcess[str]` — thin wrapper around `subprocess.run` with timeout + `stdin=DEVNULL` (mirrors `plugin_cli._run`), raises `InstallerError` on non-zero exit.
- `_default_branch(repo_dir: Path) -> str` — resolves `origin/HEAD` symbolic-ref to get the repo's default branch when `branch` is not provided.
- `_is_valid_clone(path: Path) -> bool` — checks `path / ".git"` exists and `git -C <path> remote get-url origin` matches `_HTTPS_SOURCE` (defensive: handles a stale/wrong dir at the cache location).

### CLI wiring: `installer/cli.py`

Add one argument to the parser (not mutually exclusive with any existing mode):

```python
parser.add_argument(
    "--local-marketplace",
    action="store_true",
    help="Clone the marketplace repo locally and register it as the marketplace source.",
)
```

### Dispatch: `installer/main.py`

A small helper — `_resolve_marketplace_source(args) -> tuple[str, str | None]` — returns `(source, branch)` to pass into `add_marketplace`. This centralizes the decision so `_install()` and `_reinstall()` share one code path:

```python
def _resolve_marketplace_source(args) -> tuple[str, str | None]:
    if getattr(args, "local_marketplace", False):
        local_path = ensure_local_clone(branch=getattr(args, "branch", None))
        return (str(local_path), None)  # clone already on target branch
    return (MARKETPLACE_SOURCE, getattr(args, "branch", None))
```

Both `_install()` and `_reinstall()` call this helper instead of reading `args.branch` directly.

**Install flow change** (`_install`, step 3):

```python
source, branch = _resolve_marketplace_source(args)
if not check_marketplace_registered():
    add_marketplace(source=source, branch=branch)
elif args.local_marketplace or branch:
    # Re-register when --local-marketplace or --branch changes the source
    remove_marketplace()
    add_marketplace(source=source, branch=branch)
```

The existing condition was `elif branch:`. Extended to `elif args.local_marketplace or branch:` so the auto-remove-and-re-add behavior covers the local case.

**Reinstall flow change** (`_reinstall`): already always removes + re-adds the marketplace. Just swap in the resolved `(source, branch)`.

### `plugin_cli.add_marketplace` signature

Currently:

```python
def add_marketplace(source: str = MARKETPLACE_SOURCE, branch: str | None = None) -> None:
    ref = f"{source}#{branch}" if branch else source
    _run(["claude", "plugin", "marketplace", "add", ref])
```

**Unchanged.** Callers already pass `source` and `branch` explicitly in the reinstall path; new wiring in `_install()` will too. One caveat: `#branch` suffix is only meaningful for GitHub refs, not local paths. `_resolve_marketplace_source` returns `branch=None` for local paths, so this is safe — but a defensive assertion / early return in `add_marketplace` when `source` is an absolute path + `branch` is set would prevent silent misuse later. **Decision: skip the assertion** — callers enforce the invariant; an extra check here is YAGNI.

## Data flow

```
User: claude-pm-installer --local-marketplace [--branch dev] [--reinstall]
  │
  ├─► build_parser() parses --local-marketplace
  │
  ├─► _install() or _reinstall()
  │     │
  │     ├─► _resolve_marketplace_source(args)
  │     │     ├─► ensure_local_clone(branch="dev")
  │     │     │     ├─► if LOCAL_CLONE_DIR missing: git clone _HTTPS_SOURCE LOCAL_CLONE_DIR
  │     │     │     ├─► else: git fetch origin
  │     │     │     ├─► git checkout dev (or default branch)
  │     │     │     ├─► git reset --hard origin/dev
  │     │     │     └─► return Path("/home/<user>/.cache/claude-project-manager/local-marketplace")
  │     │     └─► return (str(local_path), None)
  │     │
  │     ├─► check_marketplace_registered()? yes → remove_marketplace()
  │     ├─► add_marketplace(source=local_path, branch=None)
  │     │     └─► subprocess: claude plugin marketplace add /home/<user>/.cache/claude-project-manager/local-marketplace
  │     │
  │     └─► install_plugin(...) for each selected plugin (unchanged)
```

## Error handling

- **Missing `git` binary** → `ensure_local_clone` raises `InstallerError("git not found on PATH")`. Detect via `shutil.which("git")` before the first git invocation.
- **Clone timeout** (network issue, GitHub down) → `_run_git` raises `InstallerError("git clone timed out after 120s")` (mirrors `plugin_cli._run` pattern).
- **Clone dir exists but is not a valid clone** (stray files, wrong remote) → `_is_valid_clone()` returns False → raise `InstallerError` with guidance: "Cache dir at <path> is not a valid clone of <url>. Delete it and retry."
  - **Rationale**: do not auto-nuke user data. The user answered "Fetch reset and pull" — not "rm -rf and re-clone".
- **Branch does not exist on remote** → `git checkout <branch>` fails → `InstallerError` with stderr passed through.
- **Filesystem errors** (permission denied creating cache dir) → `InstallerError` with path in message.

All errors propagate through the existing `InstallerError` → main.py → `EXIT_ERROR` (2) path. No new exit codes.

## CLI interactions

| Combination | Behavior |
|-------------|----------|
| `--local-marketplace` | Fresh install using local clone on repo's default branch. |
| `--local-marketplace --branch dev` | Clone / update, checkout `dev`, register from local path. |
| `--local-marketplace --reinstall` | Remove marketplace → update clone → re-register from local → reinstall plugins. |
| `--local-marketplace --skip-wizard` | Skip wizard; clone + register + install all plugins non-interactively. |
| `--local-marketplace --uninstall` | Remove marketplace + plugins. **Clone dir is NOT deleted** (persists at cache path). |
| `--local-marketplace --full-cleanup` | Same as `--uninstall`. Clone dir persists. A future todo could add cache-dir cleanup here. |
| `--local-marketplace --migrate` | Migrate path does not touch marketplace. Flag is ignored silently (migrate bypasses the install/reinstall paths entirely). |

## Testing

Unit tests in `installer/tests/test_local_marketplace.py`:

1. `ensure_local_clone` calls `git clone` when `LOCAL_CLONE_DIR` does not exist.
2. `ensure_local_clone` calls `git fetch` + `git checkout` + `git reset --hard` when clone exists.
3. `ensure_local_clone` checks out given branch.
4. `ensure_local_clone` falls back to default branch when `branch=None`.
5. `_is_valid_clone` returns False for arbitrary non-git dir.
6. `_is_valid_clone` returns False when origin URL does not match.
7. Raises `InstallerError` when `git` is missing on PATH.
8. Raises `InstallerError` when a git subprocess fails.
9. Raises `InstallerError` when a git subprocess times out.

Unit tests in `installer/tests/test_cli_local_marketplace.py`:

10. `build_parser().parse_args(["--local-marketplace"])` sets `args.local_marketplace=True`.
11. Default (no flag) leaves `args.local_marketplace=False`.

Integration tests in `installer/tests/test_main_local_marketplace.py`:

12. `_install(args)` with `--local-marketplace` calls `ensure_local_clone` once and `add_marketplace(source=<path>, branch=None)`.
13. `_install(args)` with `--local-marketplace --branch dev` passes `branch="dev"` to `ensure_local_clone` and `branch=None` to `add_marketplace`.
14. `_install(args)` with `--local-marketplace` and marketplace already registered: calls `remove_marketplace` then `add_marketplace` (not just `add_marketplace` alone).
15. `_reinstall(args)` with `--local-marketplace` uses local path as source in `add_marketplace`.
16. `_resolve_marketplace_source` without `--local-marketplace` returns `(MARKETPLACE_SOURCE, args.branch)` (backward compat).

All git calls are mocked via `subprocess.run` patching — no network, no real clone.

## Out of scope

- Cloning from a URL other than `raulfrk/claude-project-manager`. Hardcoded source is intentional per brainstorming.
- Cleaning up the clone dir on `--uninstall --full-cleanup`. Can be added later as a separate todo.
- Pointing at a directory that the user already has (no clone, just register). Separate feature.
- Changing `MARKETPLACE_SOURCE` to a URL form; it stays as the GitHub short ref for the default flow.
