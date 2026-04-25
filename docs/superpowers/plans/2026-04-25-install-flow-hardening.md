# Install Flow Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix kill-stale ordering so old MCP processes are killed before shared-venv rebuild, and harden `ensure_local_clone` rmtree against silent / partial failures.

**Architecture:** Extract a `_kill_then_finalize(args, console)` helper in the TUI flow that calls `prompt_kill_stale_sessions` before `_finalize_shared_venv`. Wire into `_run_install`, `_run_reinstall`, `_run_update`. Add equivalent `prompt_kill_stale_sessions` calls in the `--no-tui` paths in `installer/main.py`. Wrap `shutil.rmtree(dest)` in `installer/local_marketplace.py` with try/except → `InstallerError` plus a post-check.

**Tech Stack:** Python (stdlib + pytest + unittest.mock), Rich console.

**Spec:** `docs/superpowers/specs/2026-04-25-install-flow-hardening-design.md`

---

## File Structure

| File | Responsibility | Action |
|------|----------------|--------|
| `installer/flow/installer_flow.py` | TUI install/reinstall/update flow + `_finalize_shared_venv` + new `_kill_then_finalize` helper | Modify |
| `installer/main.py` | `--no-tui` `_install` / `_reinstall` flows | Modify |
| `installer/local_marketplace.py` | `ensure_local_clone` git clone management | Modify (add try/except + post-check) |
| `installer/tests/flow/test_installer_flow.py` | TUI flow tests; existing `TestSharedVenvFinalize` extended w/ ordering | Modify |
| `installer/tests/test_main.py` | `--no-tui` `_install`/`_reinstall` tests; existing `TestInstall`/`TestReinstallSharedVenv` extended | Modify |
| `installer/tests/test_local_marketplace.py` | `ensure_local_clone` tests; new `TestRmtreeGuard` class | Modify |

---

## Task 1: Test ordering in TUI flow (red)

**Files:**
- Modify: `installer/tests/flow/test_installer_flow.py`

Three new tests in a new `TestKillStaleOrdering` class verify that
`prompt_kill_stale_sessions` is called BEFORE `_finalize_shared_venv` in
`_run_install`, `_run_reinstall`, and `_run_update`. Tests fail against
the current code because order is reversed in install/reinstall and
kill_stale is missing entirely from update.

- [ ] **Step 1: Add the test class at the bottom of the file (just before the line `# ── Uninstall ───────────────`)**

Insert this block immediately after the `TestSharedVenvFinalize` class
(end of class is around line 305 in current file). Place before the
`# ── Uninstall ──` separator comment:

```python
class TestKillStaleOrdering:
    """Stale Claude sessions must be killed BEFORE the shared venv rebuild.

    Old Claude Code processes still running with the previous plugin code
    hold open handles to the old shared venv. uv sync would replace files
    underneath them, leaving the old session in a half-stale state until
    restart. The kill must come first.
    """

    def _assert_kill_before_finalize(self, parent_mock):
        """Verify prompt_kill_stale_sessions was called before
        _finalize_shared_venv on the shared parent mock."""
        names = [c[0] for c in parent_mock.mock_calls]
        try:
            kill_idx = names.index("prompt_kill_stale_sessions")
            finalize_idx = names.index("_finalize_shared_venv")
        except ValueError as exc:
            raise AssertionError(
                f"Expected both calls; got names={names}"
            ) from exc
        assert kill_idx < finalize_idx, (
            f"prompt_kill_stale_sessions (call #{kill_idx}) must precede "
            f"_finalize_shared_venv (call #{finalize_idx}); calls={names}"
        )

    def test_run_install_kills_before_finalize(self) -> None:
        from unittest.mock import MagicMock as _MagicMock

        parent = _MagicMock()
        with (
            patch(
                "installer.flow.installer_flow.pre_install_phase",
                return_value=PreInstallResult(state=None, proceed=True),
            ),
            patch(
                "installer.flow.installer_flow.check_marketplace_registered",
                return_value=True,
            ),
            patch(
                "installer.flow.installer_flow.build_plugin_status_list",
                return_value=[],
            ),
            patch(
                "installer.flow.installer_flow.select_plugin_actions",
                return_value=[("proj", "install")],
            ),
            patch(
                "installer.flow.installer_flow._name_to_id_map",
                return_value={"proj": "proj@claude-project-manager"},
            ),
            patch(
                "installer.flow.installer_flow.compute_hooks_diff",
                return_value=[],
            ),
            patch(
                "installer.flow.installer_flow.review_hooks_diff",
                return_value={"apply": [], "remove": []},
            ),
            patch(
                "installer.flow.installer_flow.execute_install_plan",
                return_value=_ok(),
            ),
            patch("installer.flow.installer_flow.cleanup_orphaned_plugin_caches"),
            patch("installer.flow.installer_flow.ensure_managed_section"),
            patch(
                "installer.flow.installer_flow.prompt_kill_stale_sessions",
                parent.prompt_kill_stale_sessions,
            ),
            patch(
                "installer.flow.installer_flow._finalize_shared_venv",
                parent._finalize_shared_venv,
            ),
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            run_installer_flow("install", _Args(), console)
        self._assert_kill_before_finalize(parent)

    def test_run_reinstall_kills_before_finalize(self) -> None:
        from unittest.mock import MagicMock as _MagicMock

        parent = _MagicMock()
        with (
            patch(
                "installer.flow.installer_flow.pre_install_phase",
                return_value=PreInstallResult(
                    state=MagicMock(installed_plugins=["proj"]),
                    proceed=True,
                    mode_options={"reset_configs": False},
                ),
            ),
            patch(
                "installer.flow.installer_flow.get_installed_plugins",
                return_value=["proj@claude-project-manager"],
            ),
            patch(
                "installer.flow.installer_flow.get_available_plugins",
                return_value=["proj@claude-project-manager"],
            ),
            patch(
                "installer.flow.installer_flow.execute_install_plan",
                return_value=_ok(),
            ),
            patch("installer.flow.installer_flow.cleanup_orphaned_plugin_caches"),
            patch(
                "installer.flow.installer_flow.prompt_kill_stale_sessions",
                parent.prompt_kill_stale_sessions,
            ),
            patch(
                "installer.flow.installer_flow._finalize_shared_venv",
                parent._finalize_shared_venv,
            ),
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            run_installer_flow("reinstall", _Args(), console)
        self._assert_kill_before_finalize(parent)

    def test_run_update_kills_before_finalize(self) -> None:
        """_run_update was missing kill_stale entirely; this asserts it now
        fires AND fires before the venv build."""
        from unittest.mock import MagicMock as _MagicMock

        parent = _MagicMock()
        with (
            patch(
                "installer.flow.installer_flow.pre_install_phase",
                return_value=PreInstallResult(
                    state=MagicMock(installed_plugins=["proj"]),
                    proceed=True,
                ),
            ),
            patch(
                "installer.flow.installer_flow.compare_versions",
                return_value=[("proj", "1.0.0", "1.0.1")],
            ),
            patch(
                "installer.flow.installer_flow.select_updates",
                return_value=["proj"],
            ),
            patch(
                "installer.flow.installer_flow._name_to_id_map",
                return_value={"proj": "proj@claude-project-manager"},
            ),
            patch(
                "installer.flow.installer_flow.execute_install_plan",
                return_value=_ok(),
            ),
            patch("installer.flow.installer_flow.cleanup_orphaned_plugin_caches"),
            patch("installer.flow.installer_flow.ensure_managed_section"),
            patch(
                "installer.flow.installer_flow.prompt_kill_stale_sessions",
                parent.prompt_kill_stale_sessions,
            ),
            patch(
                "installer.flow.installer_flow._finalize_shared_venv",
                parent._finalize_shared_venv,
            ),
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            run_installer_flow("update", _Args(), console)
        self._assert_kill_before_finalize(parent)
```

- [ ] **Step 2: Run tests to verify they fail (red)**

Run: `uv run --no-sync pytest installer/tests/flow/test_installer_flow.py::TestKillStaleOrdering -v`

Expected:
- `test_run_install_kills_before_finalize` — FAILS (current order is finalize → kill)
- `test_run_reinstall_kills_before_finalize` — FAILS (same)
- `test_run_update_kills_before_finalize` — FAILS (kill never called in update)

- [ ] **Step 3: Commit (red)**

```bash
git add installer/tests/flow/test_installer_flow.py
git commit -m "test(flow): pin kill_stale before _finalize_shared_venv ordering (red)

3 ordering tests in TestKillStaleOrdering. Verifies kill-stale fires
before shared-venv rebuild in _run_install / _run_reinstall, and that
_run_update gets the kill_stale step it currently lacks. Tests fail
until the next task wires the new helper.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Wire `_kill_then_finalize` helper into TUI flow (green)

**Files:**
- Modify: `installer/flow/installer_flow.py`

- [ ] **Step 1: Add the helper just before the existing `_finalize_shared_venv` definition (around line 56)**

Insert this function above `_finalize_shared_venv`:

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

- [ ] **Step 2: Update `_run_install` (around line 494-496) — replace the two-call block**

Find:

```python
    if exit_code == 0:
        _finalize_shared_venv(args, console)
        prompt_kill_stale_sessions(console)
    return exit_code
```

Replace with:

```python
    if exit_code == 0:
        _kill_then_finalize(args, console)
    return exit_code
```

- [ ] **Step 3: Update `_run_reinstall` (around line 574-576) — same replacement**

Find:

```python
    if exit_code == 0:
        _finalize_shared_venv(args, console)
        prompt_kill_stale_sessions(console)
    if mode_options.get("reset_configs"):
        _reset_installer_configs(console)
    return exit_code
```

Replace with:

```python
    if exit_code == 0:
        _kill_then_finalize(args, console)
    if mode_options.get("reset_configs"):
        _reset_installer_configs(console)
    return exit_code
```

- [ ] **Step 4: Update `_run_update` (around line 524-525) — add kill where missing**

Find:

```python
    if exit_code == 0:
        _finalize_shared_venv(args, console)
    return exit_code
```

Replace with:

```python
    if exit_code == 0:
        _kill_then_finalize(args, console)
    return exit_code
```

- [ ] **Step 5: Run the ordering tests + the previously-passing TestSharedVenvFinalize tests**

Run: `uv run --no-sync pytest installer/tests/flow/test_installer_flow.py -v`

Expected: all green. The 3 new ordering tests pass, and existing
`TestSharedVenvFinalize` tests still pass (helper just renames the
sequence; semantics preserved).

- [ ] **Step 6: Commit (green)**

```bash
git add installer/flow/installer_flow.py
git commit -m "feat(flow): _kill_then_finalize helper — kill stale before venv

Extract _kill_then_finalize(args, console) that calls
prompt_kill_stale_sessions before _finalize_shared_venv. Wire into
_run_install, _run_reinstall, and _run_update (latter previously had
no kill_stale call at all).

Old Claude Code processes hold open file descriptors to the old shared
venv. Killing them first lets uv sync replace the venv cleanly.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Test kill-before-venv ordering in `--no-tui` paths (red)

**Files:**
- Modify: `installer/tests/test_main.py`

Three new ordering tests in `installer/main.py`'s `_install` and
`_reinstall` paths (both `--skip-wizard` and non-`--skip-wizard`).

- [ ] **Step 1: Add ordering tests inside the existing `TestInstall` class**

Locate `class TestInstall:` (around line 95). At the end of that class,
just before `class TestReinstall:` (around line 343), add:

```python
    @patch("installer.main.run_wizard")
    @patch("installer.main.install_plugin")
    @patch("installer.main.get_installed_plugins", return_value=[])
    @patch("installer.main.get_available_plugins", return_value=["proj@gh:x/y"])
    @patch("installer.main.check_marketplace_registered", return_value=True)
    def test_install_wizard_path_kills_before_run_wizard(
        self,
        _check_mp,
        _avail,
        _installed,
        _install_plugin,
        mock_wizard,
    ):
        """Non --skip-wizard install: prompt_kill_stale_sessions called
        before run_wizard (which itself triggers shared-venv build via
        _create_shared_venv_step)."""
        from unittest.mock import MagicMock as _MagicMock

        parent = _MagicMock()
        parent.run_wizard = mock_wizard
        with patch(
            "installer.flow.kill_stale.prompt_kill_stale_sessions",
            parent.prompt_kill_stale_sessions,
        ):
            args = _make_args(plugins=["proj"], skip_wizard=False)
            _install(args)
        names = [c[0] for c in parent.mock_calls]
        kill_idx = names.index("prompt_kill_stale_sessions")
        wizard_idx = names.index("run_wizard")
        assert kill_idx < wizard_idx, (
            f"prompt_kill_stale_sessions must precede run_wizard; got {names}"
        )

    @patch("installer.shared_venv.ensure_shared_venv")
    @patch("installer.main.install_plugin")
    @patch("installer.main.get_installed_plugins", return_value=[])
    @patch("installer.main.get_available_plugins", return_value=["proj@gh:x/y"])
    @patch("installer.main.check_marketplace_registered", return_value=True)
    @patch("installer.main.run_wizard")
    def test_install_skip_wizard_kills_before_ensure_shared_venv(
        self,
        _wizard,
        _check_mp,
        _avail,
        _installed,
        _install_plugin,
        mock_ensure,
        tmp_path,
        monkeypatch,
    ):
        """--skip-wizard install: prompt_kill_stale_sessions called before
        ensure_shared_venv in the belt-and-suspenders block."""
        from unittest.mock import MagicMock as _MagicMock

        target = tmp_path / "mp"
        target.mkdir()
        monkeypatch.setattr("installer.shared_venv.marketplaces_dir", lambda: target)

        parent = _MagicMock()
        parent.ensure_shared_venv = mock_ensure
        with patch(
            "installer.flow.kill_stale.prompt_kill_stale_sessions",
            parent.prompt_kill_stale_sessions,
        ):
            args = _make_args(plugins=["proj"], skip_wizard=True)
            _install(args)
        names = [c[0] for c in parent.mock_calls]
        kill_idx = names.index("prompt_kill_stale_sessions")
        ensure_idx = names.index("ensure_shared_venv")
        assert kill_idx < ensure_idx, (
            f"prompt_kill_stale_sessions must precede ensure_shared_venv; got {names}"
        )
```

- [ ] **Step 2: Add ordering test inside the existing `TestReinstallSharedVenv` class**

Locate `class TestReinstallSharedVenv:` (around line 624). Add this
method to that class (anywhere among its peers):

```python
    @patch("installer.shared_venv.ensure_shared_venv")
    @patch("installer.main.install_plugin")
    @patch("installer.main.add_marketplace")
    @patch("installer.main.remove_marketplace")
    @patch("installer.main.scan_stale_cache", side_effect=FileNotFoundError("skip"))
    @patch("installer.main.get_installed_plugins", return_value=["proj"])
    @patch("installer.main.display_detection")
    @patch("installer.main.detect_existing")
    @patch("installer.main.run_wizard")
    def test_reinstall_skip_wizard_kills_before_ensure_shared_venv(
        self,
        _wizard,
        mock_detect,
        _disp,
        _gip,
        _scan,
        _remove_mp,
        _add_mp,
        _install_plugin,
        mock_ensure,
        tmp_path,
        monkeypatch,
    ):
        """--skip-wizard reinstall: prompt_kill_stale_sessions called before
        ensure_shared_venv."""
        from unittest.mock import MagicMock as _MagicMock

        target = tmp_path / "mp"
        target.mkdir()
        monkeypatch.setattr("installer.shared_venv.marketplaces_dir", lambda: target)
        mock_detect.return_value = InstallState(installed_plugins=["proj"])

        parent = _MagicMock()
        parent.ensure_shared_venv = mock_ensure
        with patch(
            "installer.flow.kill_stale.prompt_kill_stale_sessions",
            parent.prompt_kill_stale_sessions,
        ):
            args = _make_args(reinstall=True, skip_wizard=True)
            _reinstall(args)
        names = [c[0] for c in parent.mock_calls]
        kill_idx = names.index("prompt_kill_stale_sessions")
        ensure_idx = names.index("ensure_shared_venv")
        assert kill_idx < ensure_idx, (
            f"prompt_kill_stale_sessions must precede ensure_shared_venv; got {names}"
        )
```

- [ ] **Step 3: Run tests to verify they fail (red)**

Run: `uv run --no-sync pytest installer/tests/test_main.py -v -k "kills_before"`

Expected: all 3 new tests FAIL — `installer/main.py` currently doesn't
call `prompt_kill_stale_sessions` anywhere.

- [ ] **Step 4: Commit (red)**

```bash
git add installer/tests/test_main.py
git commit -m "test(main): pin kill_stale before venv-build in --no-tui paths (red)

3 ordering tests asserting prompt_kill_stale_sessions is invoked before
shared-venv build (run_wizard or ensure_shared_venv) in
installer/main.py:_install and _reinstall, both --skip-wizard and
non-skip-wizard branches. Tests fail until kill calls are wired up.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Wire kill_stale into `installer/main.py` (green)

**Files:**
- Modify: `installer/main.py`

- [ ] **Step 1: Add `prompt_kill_stale_sessions` call before `run_wizard` in `_install`**

Locate `_install` (around line 161). The current block is:

```python
    # 5. Run setup wizard now that plugins are installed and marketplace
    # dir exists (so wizard can create the shared venv).
    run_wizard(selected, skip=args.skip_wizard, args=args)

    # Belt-and-suspenders: when --skip-wizard bypasses the wizard's
    # venv-creation step, fire ensure_shared_venv directly so the
    # shared environment still exists.
    if args.skip_wizard:
        from installer.shared_venv import ensure_shared_venv, marketplaces_dir
```

Replace with:

```python
    # 5. Kill stale Claude Code sessions BEFORE shared-venv rebuild so old
    # MCP processes release file descriptors to the old venv.
    from installer.flow.kill_stale import prompt_kill_stale_sessions

    prompt_kill_stale_sessions(console)

    # 6. Run setup wizard now that plugins are installed and marketplace
    # dir exists (so wizard can create the shared venv).
    run_wizard(selected, skip=args.skip_wizard, args=args)

    # Belt-and-suspenders: when --skip-wizard bypasses the wizard's
    # venv-creation step, fire ensure_shared_venv directly so the
    # shared environment still exists.
    if args.skip_wizard:
        from installer.shared_venv import ensure_shared_venv, marketplaces_dir
```

- [ ] **Step 2: Add same call in `_reinstall`**

Locate `_reinstall` (around line 299). The current block is:

```python
    # Run wizard after reinstall if configs were reset
    if not args.skip_wizard:
        run_wizard(plugins, skip=False, args=args)

    # Belt-and-suspenders: when --skip-wizard bypasses the wizard's
    # venv-creation step, fire ensure_shared_venv directly so the
    # shared environment still exists. Mirrors _install.
    if args.skip_wizard:
        from installer.shared_venv import ensure_shared_venv, marketplaces_dir
```

Replace with:

```python
    # Kill stale Claude Code sessions BEFORE shared-venv rebuild so old
    # MCP processes release file descriptors to the old venv.
    from installer.flow.kill_stale import prompt_kill_stale_sessions

    prompt_kill_stale_sessions(console)

    # Run wizard after reinstall if configs were reset
    if not args.skip_wizard:
        run_wizard(plugins, skip=False, args=args)

    # Belt-and-suspenders: when --skip-wizard bypasses the wizard's
    # venv-creation step, fire ensure_shared_venv directly so the
    # shared environment still exists. Mirrors _install.
    if args.skip_wizard:
        from installer.shared_venv import ensure_shared_venv, marketplaces_dir
```

- [ ] **Step 3: Run the new ordering tests + existing TestInstall / TestReinstall tests**

Run: `uv run --no-sync pytest installer/tests/test_main.py -v -k "Install or Reinstall"`

Expected: all green. The 3 new ordering tests pass; existing tests still
pass (they don't assert on order of any pre-wizard step).

- [ ] **Step 4: Commit (green)**

```bash
git add installer/main.py
git commit -m "feat(main): kill stale Claude sessions before --no-tui venv rebuild

installer/main.py:_install and _reinstall now call
prompt_kill_stale_sessions before the wizard / belt-and-suspenders
ensure_shared_venv block. Old MCP processes get killed before uv sync
replaces the shared venv, preventing half-stale state.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Test rmtree guard (red)

**Files:**
- Modify: `installer/tests/test_local_marketplace.py`

Two new tests verify `ensure_local_clone` raises `InstallerError` when
`shutil.rmtree` fails or silently leaves the dir behind.

- [ ] **Step 1: Locate the existing test file and add the new class**

Append to `installer/tests/test_local_marketplace.py`:

```python
class TestRmtreeGuard:
    """ensure_local_clone must surface rmtree failures clearly.

    Bare shutil.rmtree raises OSError on permission/busy/partial
    filesystem failures. The guard converts those into InstallerError
    with a path and recovery hint, so users see a clean message instead
    of a stack trace mid-install. A post-rmtree existence check catches
    the rare case where rmtree returns 0 but leaves a partial tree.
    """

    @patch("installer.local_marketplace._run_git")
    @patch("installer.local_marketplace.shutil.rmtree")
    def test_rmtree_oserror_raises_installer_error(
        self, mock_rmtree, _run_git, tmp_path, monkeypatch
    ):
        """rmtree raising OSError → InstallerError w/ path + recovery hint."""
        from installer.errors import InstallerError
        from installer.local_marketplace import ensure_local_clone

        dest = tmp_path / "local-marketplace"
        dest.mkdir()  # exists → triggers rmtree branch
        monkeypatch.setattr(
            "installer.local_marketplace.LOCAL_CLONE_DIR", dest
        )

        mock_rmtree.side_effect = OSError("Permission denied")

        with pytest.raises(InstallerError) as exc_info:
            ensure_local_clone()

        msg = str(exc_info.value)
        assert str(dest) in msg
        assert "Permission denied" in msg
        assert "rm -rf" in msg
        # _run_git must NOT have been called — we bailed before clone
        _run_git.assert_not_called()

    @patch("installer.local_marketplace._run_git")
    @patch("installer.local_marketplace.shutil.rmtree")
    def test_rmtree_silent_no_op_raises_installer_error(
        self, mock_rmtree, _run_git, tmp_path, monkeypatch
    ):
        """rmtree returns 0 but dest still exists → InstallerError."""
        from installer.errors import InstallerError
        from installer.local_marketplace import ensure_local_clone

        dest = tmp_path / "local-marketplace"
        dest.mkdir()
        monkeypatch.setattr(
            "installer.local_marketplace.LOCAL_CLONE_DIR", dest
        )

        # rmtree is a no-op (mock); dest stays put.
        mock_rmtree.return_value = None

        with pytest.raises(InstallerError) as exc_info:
            ensure_local_clone()

        msg = str(exc_info.value)
        assert str(dest) in msg
        assert "still exists" in msg or "partial" in msg
        _run_git.assert_not_called()
```

If `pytest` is not already imported at the top of `test_local_marketplace.py`, add `import pytest`. Verify by running step 2 — pytest will fail with ImportError if missing.

- [ ] **Step 2: Run tests to verify they fail (red)**

Run: `uv run --no-sync pytest installer/tests/test_local_marketplace.py::TestRmtreeGuard -v`

Expected: both tests FAIL — current `ensure_local_clone` calls
`shutil.rmtree` bare; first test propagates OSError (not InstallerError),
second test happily proceeds to call `_run_git("clone")`.

- [ ] **Step 3: Commit (red)**

```bash
git add installer/tests/test_local_marketplace.py
git commit -m "test(local_marketplace): pin rmtree failure handling (red)

Two tests asserting ensure_local_clone raises InstallerError with a
clear message when shutil.rmtree fails (OSError) or silently leaves
the destination behind. Tests fail until the rmtree guard lands.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Implement rmtree guard (green)

**Files:**
- Modify: `installer/local_marketplace.py`

- [ ] **Step 1: Replace the bare rmtree call**

Locate `ensure_local_clone` (around line 90). Find:

```python
    if dest.exists():
        _status(console, f"[yellow]Removing existing local clone at {dest}...[/yellow]")
        shutil.rmtree(dest)
```

Replace with:

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

- [ ] **Step 2: Run tests to verify green**

Run: `uv run --no-sync pytest installer/tests/test_local_marketplace.py -v`

Expected: all green (the 2 new tests + previously-passing tests).

- [ ] **Step 3: Commit (green)**

```bash
git add installer/local_marketplace.py
git commit -m "fix(local_marketplace): guard rmtree against silent + partial failures

Wrap shutil.rmtree(dest) in ensure_local_clone with try/except OSError
→ InstallerError(path + manual-recovery hint). Add post-rmtree
existence check to catch cases where rmtree returns 0 but leaves a
stale tree (busy mounts, root-owned files).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Run full installer suite + push

**Files:** none modified.

- [ ] **Step 1: Run fast suite**

Run: `uv run --no-sync pytest installer/tests --ignore=installer/tests/e2e -x`

Expected: all green (existing 736 + 8 new from Tasks 1, 3, 5).

- [ ] **Step 2: Run slow suite**

Run: `uv run --no-sync pytest installer/tests -m slow --ignore=installer/tests/e2e -x`

Expected: 9 slow tests still green (cross-plugin integration test from prior session unaffected).

- [ ] **Step 3: Push to dev**

```bash
git push origin dev
```

Expected: 6 new commits land on origin/dev. Watch CI:

```bash
gh run list --branch dev --limit 1
```

---

## Self-Review

**Spec coverage**

| Spec section | Task |
|---|---|
| Defect 1: kill before venv in TUI flow | Tasks 1, 2 |
| Defect 2: missing kill in `_run_update` | Task 1 (test) + Task 2 (impl via helper) |
| Defect 2: missing kill in `--no-tui` | Tasks 3, 4 |
| Defect 3: rmtree OSError guard | Tasks 5, 6 (case 1) |
| Defect 3: rmtree silent no-op post-check | Tasks 5, 6 (case 2) |
| Verification: pytest green | Task 7 |
| Verification: manual reinstall test | Out of scope per spec; user runs manually post-merge |

No gaps.

**Placeholder scan**

No "TBD" / "TODO" / "Add appropriate" / "Similar to Task N" / "..." patterns. Each step has exact code or exact command + expected output.

**Type/name consistency**

`_kill_then_finalize(args, console)` defined in Task 2 Step 1; referenced
identically in Tasks 2 Steps 2/3/4. `prompt_kill_stale_sessions(console)`
imported from `installer.flow.kill_stale` consistently across Tasks 4 and
test patches in Tasks 1 and 3. `InstallerError` imported via existing
import in `installer/local_marketplace.py` (already in file — verified
during spec phase).

`MagicMock` parent-call ordering pattern is identical across the three
ordering test variants in Task 1 and the two in Task 3, with the same
helper assertion (`_assert_kill_before_finalize`) reused inside `TestKillStaleOrdering`. The `--no-tui` tests inline the assertion (different mock parent shape — `run_wizard` vs `ensure_shared_venv` as the second call).

Plan is executable as-is.
