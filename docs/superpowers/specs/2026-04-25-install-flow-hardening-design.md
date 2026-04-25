# Install Flow Hardening: kill-stale Ordering + rmtree Guard

**Date**: 2026-04-25
**Status**: design
**Owner**: claude-project-manager

## Problem

Two install-flow defects surfaced after the shared-venv refactor (commit `fae8623`).

### Defect 1: `prompt_kill_stale_sessions` runs after `_finalize_shared_venv`

`installer/flow/installer_flow.py` calls `_finalize_shared_venv` *before*
`prompt_kill_stale_sessions` in `_run_install` (lines 494-496) and
`_run_reinstall` (lines 574-576). Old Claude Code sessions still hold open
file descriptors to old MCP server processes that mmap the old `.venv`.
Rebuilding the venv while those processes run yields half-stale state — uv
rewrites site-packages while old python instances cache old modules. By the
time the kill prompt fires, the venv is already replaced.

### Defect 2: missing kill_stale in adjacent paths

- `_run_update` calls `_finalize_shared_venv` (line 525) but **never**
  prompts to kill stale sessions. Same risk on update.
- `installer/main.py` (the `--no-tui` path) has no `prompt_kill_stale_sessions`
  reference at all in either `_install` or `_reinstall`.

### Defect 3: bare `shutil.rmtree` in `ensure_local_clone`

`installer/local_marketplace.py:118` does `shutil.rmtree(dest)` without
guarding. On failure (permission denied, busy file, partial mount, etc.) the
stdlib OSError propagates with a generic message. The user gets a confusing
trace mid-install. Worse, `rmtree` can partially succeed and leave a stale
tree behind; the subsequent `git clone` then fails with an unclear "directory
exists" error far from root cause.

## Approach

### Fix 1: extract `_kill_then_finalize` helper, wire into 5 sites

Add to `installer/flow/installer_flow.py`:

```python
def _kill_then_finalize(args: Any, console: Console) -> None:
    """Kill stale Claude sessions BEFORE rebuilding the shared venv.

    Old Claude Code processes still running with the previous plugin code
    hold open handles to the old shared venv. uv sync would replace files
    underneath them, leaving the old session in a half-stale state until
    restart. Kill them first so the new venv lands cleanly.
    """
    prompt_kill_stale_sessions(console)
    _finalize_shared_venv(args, console)
```

Replace existing pairs in `_run_install` + `_run_reinstall` with one
`_kill_then_finalize(args, console)` call. Add the same call to:
- `_run_update` (currently has venv only)
- `installer/main.py:_install` (currently has neither)
- `installer/main.py:_reinstall` (currently has neither)

For the `--no-tui` paths, `prompt_kill_stale_sessions` is interactive but
relies on `ask_yn(default=False)`. In non-TTY automation, `ask_yn` returns
the default; current behavior is preserved (skip kill). Users who want
auto-kill in automation can `pkill claude` separately — out of scope here.

The `installer/main.py` paths have a slightly different call form because
they import `ensure_shared_venv` directly inside conditional `--skip-wizard`
blocks (commits `56f04e1` and `de4b28f`). Replicate the helper logic inline
there:

```python
# In installer/main.py:_install (and similarly _reinstall):
if args.skip_wizard:
    from installer.flow.kill_stale import prompt_kill_stale_sessions
    from installer.shared_venv import ensure_shared_venv, marketplaces_dir

    prompt_kill_stale_sessions(console)         # <-- new

    target = marketplaces_dir()
    if target.is_dir():
        try:
            ensure_shared_venv(target)
        except InstallerError as exc:
            console.print(f"[yellow]Failed to create shared venv at {target}: {exc}[/yellow]")
    if getattr(args, "local_marketplace", False):
        from installer.local_marketplace import LOCAL_CLONE_DIR
        if LOCAL_CLONE_DIR.is_dir():
            try:
                ensure_shared_venv(LOCAL_CLONE_DIR)
            except InstallerError as exc:
                console.print(f"[yellow]Failed to create shared venv at {LOCAL_CLONE_DIR}: {exc}[/yellow]")
```

The `--skip-wizard` path is the only one that currently has explicit
`ensure_shared_venv` calls in `installer/main.py`. The non-`--skip-wizard`
path delegates to `run_wizard(args=args)` which calls
`installer.wizard._create_shared_venv_step` internally. That function does
not currently have a kill-stale prompt either; rather than adding the prompt
inside the wizard (which has its own flow control), we add it OUTSIDE the
wizard call in `installer/main.py:_install`/`_reinstall`. So both paths get:

```python
if not args.skip_wizard:
    prompt_kill_stale_sessions(console)
    run_wizard(selected, skip=False, args=args)
elif args.skip_wizard:
    prompt_kill_stale_sessions(console)
    # ensure_shared_venv block (existing)
```

### Fix 2: guard `ensure_local_clone` rmtree

Replace bare `shutil.rmtree(dest)` with try/except + post-check:

```python
if dest.exists():
    _status(console, f"[yellow]Removing existing local clone at {dest}...[/yellow]")
    try:
        shutil.rmtree(dest)
    except OSError as exc:
        raise InstallerError(
            f"Failed to remove existing local clone at {dest}: {exc}. "
            f"Check permissions or remove manually with `rm -rf {dest}`."
        ) from exc
    if dest.exists():
        raise InstallerError(
            f"rmtree completed but {dest} still exists — partial filesystem state. "
            f"Remove manually with `rm -rf {dest}` and retry."
        )
```

The post-check covers cases where `rmtree` returns 0 but leaves a stale
directory behind (busy mount points, root-owned files, race with another
process).

## Files to modify

| File | Changes |
|------|---------|
| `installer/flow/installer_flow.py` | Add `_kill_then_finalize` helper; replace 2 call pairs; add 1 call to `_run_update` |
| `installer/main.py` | Add `prompt_kill_stale_sessions` call before wizard / venv-build in `_install` and `_reinstall` (both `--skip-wizard` and non-`--skip-wizard` paths) |
| `installer/local_marketplace.py` | Wrap `shutil.rmtree(dest)` with try/except + post-check |
| `installer/tests/test_main.py` | Add ordering tests for `_install`, `_reinstall` |
| `installer/tests/flow/test_installer_flow.py` | Add ordering tests for `_run_install`, `_run_reinstall`, `_run_update` |
| `installer/tests/test_local_marketplace.py` | Add 2 tests for rmtree failure + post-check |

## Tests

### `installer/tests/flow/test_installer_flow.py` — new TestKillStaleOrdering class

```python
class TestKillStaleOrdering:
    """Stale Claude sessions must be killed BEFORE the shared venv rebuild,
    so old MCP processes release file descriptors before uv sync replaces
    site-packages."""

    def test_run_install_kills_before_venv(self):
        """_run_install: kill_stale called before _finalize_shared_venv."""
        # Mock both; assert mock_calls order in a single MagicMock parent.
        ...

    def test_run_reinstall_kills_before_venv(self):
        """Same for _run_reinstall."""
        ...

    def test_run_update_kills_before_venv(self):
        """_run_update was missing kill_stale entirely. Now must call it
        before _finalize_shared_venv."""
        ...
```

Each test patches `prompt_kill_stale_sessions` and `_finalize_shared_venv`
on the module; uses a parent `MagicMock` to record call order; asserts
`parent.mock_calls.index('prompt_kill_stale_sessions') < parent.mock_calls.index('_finalize_shared_venv')`.

### `installer/tests/test_main.py` — extend TestInstallSharedVenv / TestReinstallSharedVenv

```python
def test_install_skip_wizard_kills_before_venv(self):
    """--no-tui --skip-wizard install: prompt_kill_stale_sessions called
    before ensure_shared_venv."""
    ...

def test_reinstall_skip_wizard_kills_before_venv(self):
    """Same for reinstall."""
    ...

def test_install_wizard_path_kills_before_run_wizard(self):
    """--no-tui without --skip-wizard: prompt_kill_stale_sessions called
    before run_wizard (which itself triggers _create_shared_venv_step)."""
    ...
```

### `installer/tests/test_local_marketplace.py` — new TestRmtreeGuard class

```python
class TestRmtreeGuard:
    @patch("installer.local_marketplace.shutil.rmtree", side_effect=OSError("Permission denied"))
    def test_rmtree_failure_raises_installer_error(self, mock_rmtree, tmp_path):
        """rmtree OSError → InstallerError with path + manual-recovery hint."""
        ...

    @patch("installer.local_marketplace.shutil.rmtree", return_value=None)
    def test_rmtree_silent_no_op_raises_installer_error(self, mock_rmtree, tmp_path):
        """rmtree returns 0 but dest still exists → InstallerError flagging
        partial filesystem state."""
        ...
```

## Verification

1. `uv run --no-sync pytest installer/tests --ignore=installer/tests/e2e -x` — all green.
2. Manual: re-run `cpm-install --reinstall` on this host while another
   Claude Code session is active. Confirm:
   - kill prompt appears BEFORE the "Creating shared environment..." status.
   - Wizard's venv build completes cleanly (no half-stale state).
3. Manual: `chmod -w ~/.cache/claude-project-manager/local-marketplace/.git`
   to make rmtree fail, then run `cpm-install --reinstall --local-marketplace`.
   Confirm: clean InstallerError with path + recovery instructions, no
   stack trace.

## Out of scope

- Auto-kill in `--skip-wizard` mode (preserves current default-False behavior;
  separate decision if automation needs it).
- Adding kill_stale to `installer/wizard.py:run_wizard`'s
  `_create_shared_venv_step`. The kill is wired one level up in
  `installer/main.py` so wizard internals stay focused on config flow.
- Refactoring `ensure_local_clone` beyond the rmtree guard. The git-clone
  path already raises clean InstallerError via `_run_git`.

## Risks

- **Stale `--no-tui --skip-wizard` automations**: users who pipe `yes`
  through automation today get default-False from `ask_yn` (no kill). New
  call-site adds same prompt → same default → behavior unchanged. Verified
  by `test_install_skip_wizard_kills_before_venv` mocking `ask_yn` to return
  False and confirming no kill happens.
- **Helper test coupling**: extracting `_kill_then_finalize` means flow
  tests must patch it as a unit OR patch its internals. Tests patch
  internals (`prompt_kill_stale_sessions`, `_finalize_shared_venv`) on the
  module, so they verify ordering through the helper rather than mocking
  the helper itself. Keeps tests truthful to the call contract.
