# Shared-venv lookup + creation fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the broken shared-venv path so plugins use one venv at the marketplace root instead of always falling back to per-plugin `uv sync` (which requires open PyPI access).

**Architecture:** Three coordinated changes — (1) `start.sh` does a 3-stage cascading lookup (walk-up → basename → per-plugin diagnostic), (2) installer creates the shared venv at end-of-install via a wizard finalize step (visible UX) plus a `--skip-wizard` fallback in `main.py`, (3) `scripts/presync.sh` plugin list refreshed + shared-venv step appended.

**Tech Stack:** Bash (`start.sh`, `presync.sh`), Python 3.12+ + uv (installer), pytest (tests), subprocess (uv invocation).

**Spec:** `docs/superpowers/specs/2026-04-25-shared-venv-lookup-fix-design.md`

**Worktree:** `/home/raul/worktrees/claude-project-manager/feat-shared-venv-lookup-fix` (branch `feat/shared-venv-lookup-fix`). All file edits + git operations must happen in this directory.

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `plugins/proj/start.sh` | Modify lines 48-56 | New 3-stage cascading shared-venv lookup |
| `plugins/{worktree,trello,jira,router,todoist,confluence,wiki}/start.sh` | Replace (cp from proj) | Identical copies |
| `installer/shared_venv.py` | Create | `ensure_shared_venv(marketplace_dir)` |
| `installer/tests/test_shared_venv.py` | Create | Unit tests for ensure_shared_venv |
| `installer/main.py` | Reorder + add finalize call | wizard runs after plugin install; `--skip-wizard` triggers explicit `ensure_shared_venv` |
| `installer/wizard.py` | Add final wizard step | "Creating shared environment..." step calling `ensure_shared_venv` |
| `installer/flow/wizard.py` | Add final wizard step | Same step in the alternative wizard impl |
| `installer/tests/test_main.py` | Update | Reflect new wizard ordering in `_install` tests |
| `installer/tests/test_wizard.py` (or nearest) | Add | Wizard's venv-step happy path + skip-when-marketplace-missing |
| `scripts/presync.sh` | Modify line 19 + append | Refresh plugin list + add shared-venv step |
| `tests/test_install.py` | Modify + extend | Update existing fallback test, add walk-up + diagnostic tests |

---

### Task 1: Update `plugins/proj/start.sh` shared-venv lookup

**Files:**
- Modify: `plugins/proj/start.sh:48-56`

- [ ] **Step 1: Read current file to confirm starting state**

```bash
sed -n '48,58p' plugins/proj/start.sh
```

Expected: lines 48-58 show the existing `SHARED_VENV` lookup (basename-derived).

- [ ] **Step 2: Replace lines 48-56 with new 3-stage cascade**

Use the Edit tool. Find:

```bash
# Use shared marketplace venv if available, otherwise fall back to per-plugin venv
SHARED_VENV="$HOME/.claude/plugins/marketplaces/$MARKETPLACE_NAME/.venv"
if [ -f "$SHARED_VENV/bin/python" ]; then
  export UV_PROJECT_ENVIRONMENT="$SHARED_VENV"
else
  echo "Shared venv not found, falling back to per-plugin venv" >&2
  export UV_PROJECT_ENVIRONMENT="$DIR/.venv"
  uv sync --frozen --directory "$DIR"
fi
```

Replace with:

```bash
# Locate shared venv via two-stage lookup
SHARED_VENV=""
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
fi

# Stage 2: basename-derived lookup (covers standard cache install)
if [ -z "$SHARED_VENV" ]; then
  BASENAME_CANDIDATE="$HOME/.claude/plugins/marketplaces/$MARKETPLACE_NAME/.venv"
  if [ -f "$BASENAME_CANDIDATE/bin/python" ]; then
    SHARED_VENV="$BASENAME_CANDIDATE"
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

- [ ] **Step 3: Smoke test — bash syntax check**

```bash
bash -n plugins/proj/start.sh
```

Expected: exits 0 with no output.

- [ ] **Step 4: Commit**

```bash
git add plugins/proj/start.sh
git commit -m "$(cat <<'EOF'
fix(start.sh): 3-stage cascading shared-venv lookup

Stage 1: walk up from $DIR for .claude-plugin/marketplace.json.
Stage 2: basename-derived $HOME/.claude/plugins/marketplaces/<name>/.venv.
Stage 3: per-plugin venv with diagnostic listing all paths tried.

Fixes silent miss when --local-marketplace install diverges cache
basename from marketplace symlink name.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Update + extend `tests/test_install.py` start.sh tests

**Files:**
- Modify: `tests/test_install.py:226-388`

- [ ] **Step 1: Read existing test classes to confirm structure**

```bash
sed -n '226,400p' tests/test_install.py
```

Expected: see `TestStartShSharedVenv` with `_make_start_sh`, `_setup_plugin_cache_layout`, `test_uses_shared_venv_when_present`, `test_falls_back_to_per_plugin_venv`.

- [ ] **Step 2: Run existing tests against the modified start.sh**

```bash
uv run pytest tests/test_install.py::TestStartShSharedVenv -v
```

Expected: `test_uses_shared_venv_when_present` passes (Stage 2 basename lookup still hits the same path). `test_falls_back_to_per_plugin_venv` should still pass — its assertion `"falling back" in r.stderr.lower()` matches the new text `"falling back to per-plugin venv:"`. The test's `content.replace` on `'test -f "$DIR/.venv/bin/python" || uv sync...'` is a no-op (line doesn't exist in current source); not a problem.

- [ ] **Step 3: Add `test_walk_up_finds_local_marketplace_venv` to `TestStartShSharedVenv`**

Edit `tests/test_install.py`. Add this test method **inside class `TestStartShSharedVenv`** (after `test_falls_back_to_per_plugin_venv`):

```python
    def test_walk_up_finds_local_marketplace_venv(self, tmp_path: Path) -> None:
        """When $DIR is inside a local-marketplace clone (has .claude-plugin/
        marketplace.json), walk-up should locate the venv at the clone root."""
        # Layout: tmp_path/clone/plugins/proj/server/  (mirrors --local-marketplace)
        clone_root = tmp_path / "clone"
        server_dir = clone_root / "plugins" / "proj" / "server"
        server_dir.mkdir(parents=True)

        # Marketplace metadata at clone root
        (clone_root / ".claude-plugin").mkdir()
        (clone_root / ".claude-plugin" / "marketplace.json").write_text(
            '{"name": "claude-project-manager"}'
        )

        # Plugin pyproject.toml at server dir
        (server_dir / "pyproject.toml").write_text(
            textwrap.dedent("""\
            [project]
            name = "test-plugin"
            version = "0.1.0"
            requires-python = ">=3.12"
            dependencies = []
            """)
        )

        # _shared at expected location relative to server_dir (../../_shared)
        plugin_dir = server_dir.parent
        shared_dir = plugin_dir / "_shared"
        shared_dir.mkdir(parents=True)
        (shared_dir / "pyproject.toml").write_text(
            textwrap.dedent("""\
            [project]
            name = "claude-hook-transport"
            version = "0.3.3"
            """)
        )

        # Create the shared venv at clone root
        shared_venv = clone_root / ".venv"
        shared_venv.mkdir(parents=True)
        (shared_venv / "bin").mkdir()
        (shared_venv / "bin" / "python").write_text("#!/bin/sh\n")
        (shared_venv / "bin" / "python").chmod(0o755)

        script = self._make_start_sh(tmp_path)
        target_script = server_dir / "start.sh"
        target_script.write_text(script.read_text())
        target_script.chmod(0o755)

        env = os.environ.copy()
        env["HOME"] = str(tmp_path / "home_unused")  # ensure basename lookup misses

        r = _run(
            ["bash", str(target_script), str(server_dir), "dummy_server"],
            env=env,
        )
        assert r.returncode == 0, f"start.sh failed: {r.stderr}"
        assert f"CHOSEN_VENV={shared_venv}" in r.stdout, r.stdout
```

- [ ] **Step 4: Run new test**

```bash
uv run pytest tests/test_install.py::TestStartShSharedVenv::test_walk_up_finds_local_marketplace_venv -v
```

Expected: PASS.

- [ ] **Step 5: Add `test_diagnostic_emits_three_paths_on_total_miss` to `TestStartShSharedVenv`**

Add this test method right after the previous one:

```python
    def test_diagnostic_emits_three_paths_on_total_miss(self, tmp_path: Path) -> None:
        """When both walk-up and basename lookup miss, fallback diagnostic
        must emit all three searched paths (walk-up status, basename path,
        per-plugin path) for diagnosability."""
        server_dir, _marketplace_cache = self._setup_plugin_cache_layout(tmp_path)

        env = os.environ.copy()
        env["HOME"] = str(tmp_path)

        # Marketplaces source dir w/ _shared (so the _shared sync step succeeds),
        # but NO .venv anywhere
        mp_src = (
            tmp_path / ".claude" / "plugins" / "marketplaces" / "claude-project-manager"
        )
        mp_src.mkdir(parents=True)
        plugins_shared = mp_src / "plugins" / "_shared"
        plugins_shared.mkdir(parents=True)
        (plugins_shared / "pyproject.toml").write_text(
            textwrap.dedent("""\
            [project]
            name = "claude-hook-transport"
            version = "0.3.3"
            """)
        )

        # Patch out the actual `uv sync` so we don't need network
        script = self._make_start_sh(tmp_path)
        content = script.read_text()
        content = content.replace(
            'uv sync --frozen --directory "$DIR"',
            'echo "WOULD_SYNC=1"',
        )
        target_script = server_dir / "start.sh"
        target_script.write_text(content)
        target_script.chmod(0o755)

        r = _run(
            ["bash", str(target_script), str(server_dir), "dummy_server"],
            env=env,
        )
        assert r.returncode == 0, f"start.sh failed: {r.stderr}"
        # Diagnostic must mention all three searched locations
        assert "walk-up from" in r.stderr, r.stderr
        assert "basename lookup tried:" in r.stderr, r.stderr
        assert "per-plugin venv:" in r.stderr, r.stderr
        assert "<not found>" in r.stderr, r.stderr  # walk-up should report not-found
```

- [ ] **Step 6: Run new test**

```bash
uv run pytest tests/test_install.py::TestStartShSharedVenv::test_diagnostic_emits_three_paths_on_total_miss -v
```

Expected: PASS.

- [ ] **Step 7: Run full `TestStartSh*` class set to confirm no regressions**

```bash
uv run pytest tests/test_install.py -k 'TestStartSh' -v
```

Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add tests/test_install.py
git commit -m "$(cat <<'EOF'
test(start.sh): cover walk-up lookup + 3-path diagnostic

Two new tests in TestStartShSharedVenv:
- walk-up locates venv at clone root (--local-marketplace layout)
- diagnostic emits all three paths when both lookup stages miss

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Propagate `start.sh` change to all 7 other plugins

**Files:**
- Replace: `plugins/{worktree,trello,jira,router,todoist,confluence,wiki}/start.sh`

- [ ] **Step 1: Copy proj/start.sh to every other plugin**

```bash
for p in worktree trello jira router todoist confluence wiki; do
  cp plugins/proj/start.sh "plugins/$p/start.sh"
done
```

- [ ] **Step 2: Verify all 8 byte-identical**

```bash
for p in proj worktree trello jira router todoist confluence wiki; do
  md5sum "plugins/$p/start.sh"
done
```

Expected: all 8 lines show the same MD5 hash.

- [ ] **Step 3: Bash syntax check on all 8**

```bash
for p in proj worktree trello jira router todoist confluence wiki; do
  bash -n "plugins/$p/start.sh" || echo "FAIL: $p"
done
```

Expected: no `FAIL:` lines.

- [ ] **Step 4: Commit**

```bash
git add plugins/*/start.sh
git commit -m "$(cat <<'EOF'
fix(start.sh): propagate shared-venv lookup fix to all plugins

8 plugin start.sh files kept byte-identical per existing convention.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Write failing test for `ensure_shared_venv` happy path

**Files:**
- Create: `installer/tests/test_shared_venv.py`

- [ ] **Step 1: Create test file with failing happy-path test**

```python
"""Tests for installer.shared_venv — shared marketplace venv creation."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from installer.errors import InstallerError


class TestEnsureSharedVenv:
    @patch("installer.shared_venv.subprocess.run")
    def test_happy_path_invokes_uv_sync_in_marketplace_dir(self, mock_run, tmp_path):
        """ensure_shared_venv runs `uv sync --frozen --extra plugins` in marketplace_dir."""
        from installer.shared_venv import ensure_shared_venv

        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        ensure_shared_venv(tmp_path)

        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        cmd = args[0]
        assert cmd[0] == "uv"
        assert "sync" in cmd
        assert "--frozen" in cmd
        assert "--extra" in cmd
        assert "plugins" in cmd
        # Must run in the marketplace dir (either via cwd= or --directory=)
        used_cwd = kwargs.get("cwd") == tmp_path
        used_directory_flag = (
            "--directory" in cmd and cmd[cmd.index("--directory") + 1] == str(tmp_path)
        )
        assert used_cwd or used_directory_flag, (
            f"Expected cwd={tmp_path} or --directory={tmp_path}; got cmd={cmd}, kwargs={kwargs}"
        )
        # stdin=DEVNULL mirrors plugin_cli._run for TTY safety
        assert kwargs.get("stdin") == subprocess.DEVNULL
```

- [ ] **Step 2: Run test — verify it fails**

```bash
uv run --directory installer pytest installer/tests/test_shared_venv.py::TestEnsureSharedVenv::test_happy_path_invokes_uv_sync_in_marketplace_dir -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'installer.shared_venv'`.

---

### Task 5: Implement `ensure_shared_venv` to make Task 4 test pass

**Files:**
- Create: `installer/shared_venv.py`

- [ ] **Step 1: Create `installer/shared_venv.py`**

```python
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
        InstallerError: if uv sync fails (non-zero exit, timeout).
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
    if result.returncode != 0:
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        detail = stderr or stdout
        raise InstallerError(
            f"uv sync failed (exit {result.returncode}) in {marketplace_dir}\n{detail}"
        )
```

- [ ] **Step 2: Run Task 4 test — verify it passes**

```bash
uv run --directory installer pytest installer/tests/test_shared_venv.py::TestEnsureSharedVenv::test_happy_path_invokes_uv_sync_in_marketplace_dir -v
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add installer/shared_venv.py installer/tests/test_shared_venv.py
git commit -m "$(cat <<'EOF'
feat(installer): add shared_venv.ensure_shared_venv

Runs `uv sync --frozen --extra plugins` in the marketplace dir to create
the single shared venv used by all plugins at runtime via start.sh.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Add failure-path tests for `ensure_shared_venv`

**Files:**
- Modify: `installer/tests/test_shared_venv.py`

- [ ] **Step 1: Add failure-path tests inside `TestEnsureSharedVenv`**

Append to the class:

```python
    @patch("installer.shared_venv.subprocess.run")
    def test_nonzero_exit_raises_installer_error(self, mock_run, tmp_path):
        from installer.shared_venv import ensure_shared_venv

        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="error: lock mismatch"
        )
        with pytest.raises(InstallerError, match="uv sync failed"):
            ensure_shared_venv(tmp_path)

    @patch("installer.shared_venv.subprocess.run")
    def test_timeout_raises_installer_error(self, mock_run, tmp_path):
        from installer.shared_venv import ensure_shared_venv

        mock_run.side_effect = subprocess.TimeoutExpired(cmd="uv", timeout=300)
        with pytest.raises(InstallerError, match="timed out"):
            ensure_shared_venv(tmp_path)
```

- [ ] **Step 2: Run the new tests**

```bash
uv run --directory installer pytest installer/tests/test_shared_venv.py::TestEnsureSharedVenv -v
```

Expected: all 3 pass (impl from Task 5 already handles both error paths).

- [ ] **Step 3: Commit**

```bash
git add installer/tests/test_shared_venv.py
git commit -m "$(cat <<'EOF'
test(shared_venv): cover non-zero exit + timeout error paths

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Reorder `installer/main.py::_install` — wizard runs after plugin install

The current `_install` calls `run_wizard` at line 87, BEFORE `add_marketplace` (line 107/118) and BEFORE the install loop (line 132+). The wizard cannot create the shared venv at that point because the marketplace dir doesn't exist yet. Reorder so wizard runs at the end of install (matching `_reinstall` and `installer_flow._run_install`).

**Files:**
- Modify: `installer/main.py:87` (remove early call) + `installer/main.py:160` (add late call)

- [ ] **Step 1: Read current `_install` to locate both insertion points**

```bash
sed -n '70,170p' installer/main.py
```

Expected: see `run_wizard(selected, skip=args.skip_wizard)` near line 87 and the plugin install loop ending around line 159.

- [ ] **Step 2: Remove the early `run_wizard` call**

Edit `installer/main.py`. Find:

```python
    # 2. Run the setup wizard
    run_wizard(selected, skip=args.skip_wizard)

    # 3. Ensure marketplace is registered (optionally from a local clone)
```

Replace with:

```python
    # 2. Ensure marketplace is registered (optionally from a local clone)
```

(The numbering will shift; we'll patch other comments below.)

- [ ] **Step 3: Renumber the comments in the rest of `_install`**

Find each numbered step comment (e.g. `# 3. Ensure marketplace is registered`, `# 4. Check already-installed plugins`, `# 5. Install each plugin`, `# 6. Summary`) and decrement each number by 1 since the wizard step was removed from this position.

- [ ] **Step 4: Add the late `run_wizard` call after the plugin install loop**

Find the end of the plugin install loop (the line right before `# 6. Summary` — which after Step 3 should read `# 5. Summary`). Add immediately before it:

```python
    # Run the setup wizard now that plugins are installed and the
    # marketplace dir exists (so the wizard can create the shared venv).
    run_wizard(selected, skip=args.skip_wizard, args=args)
```

Note the new `args=args` kwarg — Task 8 adds this parameter to `run_wizard`.

- [ ] **Step 5: Run install-flow tests**

```bash
uv run --directory installer pytest installer/tests/test_main.py -k '_install' -v
```

Expected: existing tests may need updating to reflect the new order. Where a test asserts `run_wizard` was called BEFORE `add_marketplace`, swap the assertion to AFTER `install_plugin`. Where a test asserts `run_wizard(selected, skip=...)`, update to `run_wizard(selected, skip=..., args=ANY)` (use `unittest.mock.ANY` if exact args don't matter for that test).

- [ ] **Step 6: Commit**

```bash
git add installer/main.py installer/tests/test_main.py
git commit -m "$(cat <<'EOF'
refactor(installer/main): run wizard after plugin install in _install

Matches order already used by _reinstall and installer_flow._run_install.
Required for wizard to create the shared venv (marketplace dir must exist
before uv sync can read its pyproject.toml). Pass args= so the wizard can
detect --local-marketplace.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: Add shared-venv finalize step to `installer/wizard.py::run_wizard`

**Files:**
- Modify: `installer/wizard.py:590-631`
- Create or extend: `installer/tests/test_wizard.py` (only if no existing test file covers `run_wizard`)

- [ ] **Step 1: Check for existing wizard test file**

```bash
ls installer/tests/test_wizard*.py 2>/dev/null
```

Use existing file if found; otherwise create `installer/tests/test_wizard.py`.

- [ ] **Step 2: Update `run_wizard` signature to accept optional `args`**

Edit `installer/wizard.py`. Find:

```python
def run_wizard(selected_plugins: list[str], skip: bool = False) -> None:
    """Run the post-install setup wizard.

    Args:
        selected_plugins: List of plugin names that were installed.
        skip: If True, skip all prompts and use defaults / keep existing.
    """
```

Replace with:

```python
def run_wizard(
    selected_plugins: list[str],
    skip: bool = False,
    args: Any | None = None,
) -> None:
    """Run the post-install setup wizard.

    Args:
        selected_plugins: List of plugin names that were installed.
        skip: If True, skip all prompts and use defaults / keep existing.
        args: Parsed CLI args (for --local-marketplace detection during
              the shared-venv creation step). May be None if invoked
              outside the standard install flow.
    """
```

- [ ] **Step 3: Add the shared-venv step at the end of `run_wizard` body**

Find the line near the end:

```python
    ensure_managed_section(Path.home() / ".claude" / "CLAUDE.md")

    console.print("\n[green]Setup wizard complete.[/green]")
```

Replace with:

```python
    ensure_managed_section(Path.home() / ".claude" / "CLAUDE.md")

    _create_shared_venv_step(args, console)

    console.print("\n[green]Setup wizard complete.[/green]")
```

- [ ] **Step 4: Add the `_create_shared_venv_step` helper above `run_wizard`**

Insert this function right above `run_wizard` (after `_setup_jira_config`):

```python
def _create_shared_venv_step(args: Any | None, console: Console) -> None:
    """Create the shared marketplace venv as the final wizard step.

    Failures are logged as warnings but do not abort install — plugins
    fall back to per-plugin uv sync at runtime via start.sh.
    """
    from installer.errors import InstallerError
    from installer.shared_venv import ensure_shared_venv, marketplaces_dir

    targets: list[Path] = [marketplaces_dir()]

    # Also create at LOCAL_CLONE_DIR if --local-marketplace was used.
    if args is not None and getattr(args, "local_marketplace", False):
        from installer.local_marketplace import LOCAL_CLONE_DIR
        targets.append(LOCAL_CLONE_DIR)

    for target in targets:
        if not target.is_dir():
            console.print(
                f"[yellow]Skipping shared venv at {target} (dir does not exist).[/yellow]"
            )
            continue
        with console.status(
            f"[bold]Creating shared environment at {target}...[/bold]"
        ):
            try:
                ensure_shared_venv(target)
            except InstallerError as exc:
                console.print(
                    f"[yellow]Failed to create shared venv at {target}: {exc}[/yellow]"
                )
                console.print(
                    "[yellow]Plugins will fall back to per-plugin uv sync at runtime.[/yellow]"
                )
                continue
        console.print(f"  [green]✓[/green] Shared venv ready at {target}")
```

- [ ] **Step 5: Add tests for the new wizard step**

In `installer/tests/test_wizard.py` (create if missing), add:

```python
"""Tests for installer.wizard.run_wizard's shared-venv step."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from installer.errors import InstallerError


class TestSharedVenvWizardStep:
    @patch("installer.wizard.ensure_managed_section")
    @patch("installer.shared_venv.ensure_shared_venv")
    @patch("installer.wizard._hooks_diff_prompt")
    def test_creates_venv_at_marketplaces_dir(
        self, _hd, mock_ensure, _mgr, tmp_path, monkeypatch
    ):
        from installer.shared_venv import marketplaces_dir
        from installer.wizard import run_wizard

        # Make marketplaces_dir() return a real existing path
        target = tmp_path / "mp"
        target.mkdir()
        monkeypatch.setattr(
            "installer.shared_venv.marketplaces_dir", lambda: target
        )

        run_wizard(selected_plugins=[], skip=True)

        # skip=True returns early — no venv step. This documents that
        # behavior; remove this assertion if you want venv to fire even on skip.
        mock_ensure.assert_not_called()

    @patch("installer.wizard.ensure_managed_section")
    @patch("installer.shared_venv.ensure_shared_venv")
    @patch("installer.wizard._hooks_diff_prompt")
    @patch("installer.wizard._setup_proj_yaml", return_value={})
    def test_runs_full_flow_creates_venv(
        self, _proj, _hd, mock_ensure, _mgr, tmp_path, monkeypatch
    ):
        from installer.wizard import run_wizard

        target = tmp_path / "mp"
        target.mkdir()
        monkeypatch.setattr(
            "installer.shared_venv.marketplaces_dir", lambda: target
        )

        # Run the wizard non-skip; the proj setup is mocked out so
        # interactive prompts don't fire.
        run_wizard(selected_plugins=["proj"], skip=False, args=None)

        mock_ensure.assert_called_once_with(target)

    @patch("installer.wizard.ensure_managed_section")
    @patch("installer.shared_venv.ensure_shared_venv")
    @patch("installer.wizard._hooks_diff_prompt")
    @patch("installer.wizard._setup_proj_yaml", return_value={})
    def test_local_marketplace_also_creates_at_local_clone(
        self, _proj, _hd, mock_ensure, _mgr, tmp_path, monkeypatch
    ):
        from installer.wizard import run_wizard

        target = tmp_path / "mp"
        target.mkdir()
        local_clone = tmp_path / "local-marketplace"
        local_clone.mkdir()

        monkeypatch.setattr(
            "installer.shared_venv.marketplaces_dir", lambda: target
        )
        monkeypatch.setattr(
            "installer.local_marketplace.LOCAL_CLONE_DIR", local_clone
        )

        args = SimpleNamespace(local_marketplace=True)
        run_wizard(selected_plugins=["proj"], skip=False, args=args)

        called_with = {c.args[0] for c in mock_ensure.call_args_list}
        assert target in called_with
        assert local_clone in called_with

    @patch("installer.wizard.ensure_managed_section")
    @patch("installer.shared_venv.ensure_shared_venv")
    @patch("installer.wizard._hooks_diff_prompt")
    @patch("installer.wizard._setup_proj_yaml", return_value={})
    def test_failure_is_warning_not_raise(
        self, _proj, _hd, mock_ensure, _mgr, tmp_path, monkeypatch, capsys
    ):
        from installer.wizard import run_wizard

        target = tmp_path / "mp"
        target.mkdir()
        monkeypatch.setattr(
            "installer.shared_venv.marketplaces_dir", lambda: target
        )
        mock_ensure.side_effect = InstallerError("uv sync exploded")

        # Should NOT raise
        run_wizard(selected_plugins=["proj"], skip=False, args=None)
```

- [ ] **Step 6: Run the new tests**

```bash
uv run --directory installer pytest installer/tests/test_wizard.py::TestSharedVenvWizardStep -v
```

Expected: all 4 pass.

- [ ] **Step 7: Run full installer test suite**

```bash
uv run --directory installer pytest installer/tests/ -v
```

Expected: green. If any pre-existing test fails because it now sees the shared-venv step run, mock `installer.shared_venv.ensure_shared_venv` in that test or rely on the marketplaces_dir not existing in the test's tmp environment.

- [ ] **Step 8: Commit**

```bash
git add installer/wizard.py installer/tests/test_wizard.py
git commit -m "$(cat <<'EOF'
feat(installer/wizard): add shared-venv finalize step

Wizard's last step now creates the shared marketplace venv via
ensure_shared_venv. Visible Rich progress message ("Creating shared
environment..."). Also handles --local-marketplace by creating an
additional venv at LOCAL_CLONE_DIR.

Failures are warnings only — plugins fall back to per-plugin uv sync
at runtime via start.sh.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: Add the same shared-venv step to `installer/flow/wizard.py::run_wizard`

**Files:**
- Modify: `installer/flow/wizard.py:44+`

- [ ] **Step 1: Read the file**

```bash
cat installer/flow/wizard.py
```

Expected: `run_wizard(state, args, console)` is the public entry. Find its body and the natural insertion point at the end.

- [ ] **Step 2: Add the shared-venv step at the end of the function body**

Reuse the `_create_shared_venv_step` helper from `installer/wizard.py`. Edit `installer/flow/wizard.py`. At the top of the file, add:

```python
from installer.wizard import _create_shared_venv_step
```

At the end of `run_wizard` (just before its return statement), add:

```python
    _create_shared_venv_step(args, console)
```

- [ ] **Step 3: Run the flow wizard tests (if any)**

```bash
uv run --directory installer pytest installer/tests/flow/ -v
```

Expected: green. If a flow-wizard test asserts internals that now include the venv step, mock `installer.shared_venv.ensure_shared_venv` in that test.

- [ ] **Step 4: Commit**

```bash
git add installer/flow/wizard.py
git commit -m "$(cat <<'EOF'
feat(installer/flow/wizard): reuse shared-venv finalize step

Imports _create_shared_venv_step from installer.wizard so both wizard
implementations behave identically at the venv-creation step.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 10: Add `--skip-wizard` finalize call in `installer/main.py::_install`

When `--skip-wizard` is passed, `run_wizard` returns early and the venv step never fires. Add an explicit `ensure_shared_venv` call in this branch.

**Files:**
- Modify: `installer/main.py` (after `run_wizard` call added in Task 7)

- [ ] **Step 1: Update the late `run_wizard` call site to also handle skip case**

Edit `installer/main.py`. Find the block added in Task 7:

```python
    # Run the setup wizard now that plugins are installed and the
    # marketplace dir exists (so the wizard can create the shared venv).
    run_wizard(selected, skip=args.skip_wizard, args=args)
```

Replace with:

```python
    # Run the setup wizard now that plugins are installed and the
    # marketplace dir exists (so the wizard can create the shared venv).
    run_wizard(selected, skip=args.skip_wizard, args=args)

    # Belt-and-suspenders: when --skip-wizard bypasses the wizard's
    # venv-creation step, fire ensure_shared_venv directly so the
    # shared environment still exists.
    if args.skip_wizard:
        from installer.errors import InstallerError
        from installer.shared_venv import ensure_shared_venv, marketplaces_dir

        target = marketplaces_dir()
        if target.is_dir():
            try:
                ensure_shared_venv(target)
            except InstallerError as exc:
                console.print(
                    f"[yellow]Failed to create shared venv at {target}: {exc}[/yellow]"
                )
        if getattr(args, "local_marketplace", False):
            from installer.local_marketplace import LOCAL_CLONE_DIR

            if LOCAL_CLONE_DIR.is_dir():
                try:
                    ensure_shared_venv(LOCAL_CLONE_DIR)
                except InstallerError as exc:
                    console.print(
                        f"[yellow]Failed to create shared venv at {LOCAL_CLONE_DIR}: {exc}[/yellow]"
                    )
```

- [ ] **Step 2: Add a test for the skip-wizard path**

In `installer/tests/test_main.py`, add a test inside the existing `_install` test class:

```python
    @patch("installer.shared_venv.ensure_shared_venv")
    @patch("installer.main.add_marketplace")
    @patch("installer.main.install_plugin")
    @patch("installer.main.get_installed_plugins", return_value=[])
    @patch("installer.main.get_available_plugins", return_value=["proj@gh:x/y"])
    @patch("installer.main.check_marketplace_registered", return_value=True)
    @patch("installer.main.run_wizard")
    def test_install_skip_wizard_still_creates_shared_venv(
        self,
        _wizard,
        _check_mp,
        _avail,
        _installed,
        _install_plugin,
        _add_mp,
        mock_ensure,
        tmp_path,
        monkeypatch,
    ):
        """--skip-wizard bypasses the wizard step; main.py must still
        call ensure_shared_venv as a finalize step."""
        from installer.shared_venv import marketplaces_dir

        target = tmp_path / "mp"
        target.mkdir()
        monkeypatch.setattr(
            "installer.shared_venv.marketplaces_dir", lambda: target
        )

        args = _make_args(plugins=["proj"], skip_wizard=True)
        result = _install(args)
        assert result == EXIT_SUCCESS
        mock_ensure.assert_called_with(target)
```

(Adjust `_make_args` if the helper does not yet support `skip_wizard=True`; pass through the parameter as needed.)

- [ ] **Step 3: Run the new test**

```bash
uv run --directory installer pytest installer/tests/test_main.py::test_install_skip_wizard_still_creates_shared_venv -v
```

Expected: PASS. If the test class needs the new test inside it, locate the right `class TestXxx:` for `_install` and add it there.

- [ ] **Step 4: Run full test_main.py to confirm no regressions**

```bash
uv run --directory installer pytest installer/tests/test_main.py -v
```

Expected: green.

- [ ] **Step 5: Commit**

```bash
git add installer/main.py installer/tests/test_main.py
git commit -m "$(cat <<'EOF'
feat(installer/main): finalize shared venv when --skip-wizard

Wizard's venv-creation step is bypassed by --skip-wizard. Fire
ensure_shared_venv directly in main.py for that case so the shared
environment still exists after non-interactive installs.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 11: Refresh `scripts/presync.sh`

**Files:**
- Modify: `scripts/presync.sh:19` + append after the per-plugin loop

- [ ] **Step 1: Read current script**

```bash
sed -n '17,30p' scripts/presync.sh
```

Expected: `plugins=(proj sandbox worktree trello jira hooks todoist zoxide)` and the for-loop below.

- [ ] **Step 2: Replace the plugins array**

Find:
```bash
plugins=(proj sandbox worktree trello jira hooks todoist zoxide)
```

Replace with:
```bash
plugins=(proj worktree trello jira router todoist confluence wiki)
```

- [ ] **Step 3: Append shared-venv step after the for-loop**

Find:
```bash
echo "done"
```
(at the end of the file)

Replace with:
```bash
echo "syncing shared marketplace venv ..."
uv sync --extra plugins --directory "$REPO_ROOT"

echo "done"
```

- [ ] **Step 4: Bash syntax check**

```bash
bash -n scripts/presync.sh
```

Expected: exits 0.

- [ ] **Step 5: Run presync.sh end-to-end**

```bash
bash scripts/presync.sh
```

Expected: 8 `syncing <plugin> ...` lines (no `skip <plugin>` for any tracked plugin), then `syncing shared marketplace venv ...`, then `done`. The script may take 30-90s on a cold uv cache.

- [ ] **Step 6: Verify shared venv was created**

```bash
test -x .venv/bin/python && echo "shared venv exists"
```

Expected: `shared venv exists`.

- [ ] **Step 7: Commit**

```bash
git add scripts/presync.sh
git commit -m "$(cat <<'EOF'
fix(presync.sh): refresh plugin list + add shared-venv step

Drops sandbox (folded into proj), hooks (renamed router), zoxide (folded
into worktree). Adds confluence, router, wiki. Appends `uv sync --extra
plugins` at REPO_ROOT so dev contributors get the shared venv that
production installs now create via the installer.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 12: Final verification sweep

**Files:** none (verification only)

- [ ] **Step 1: Run full installer test suite**

```bash
uv run --directory installer pytest installer/tests/ -v
```

Expected: all green.

- [ ] **Step 2: Run repo-root test suite**

```bash
uv run pytest tests/ -v
```

Expected: all green. Pay attention to `tests/test_install.py::TestStartShSharedVenv::*` — these exercise the actual modified `start.sh`.

- [ ] **Step 3: Verify branch state — clean working tree, all commits made**

```bash
git status -s
git log --oneline feat/shared-venv-lookup-fix ^dev
```

Expected: `git status -s` shows no modified files (clean tree). `git log` shows ~10 new commits on the branch (one per Task 1-11).

- [ ] **Step 4: Hand off**

Implementation complete. Use `superpowers:finishing-a-development-branch` skill to decide merge strategy (FF-merge to dev per CLAUDE.md feedback memory).

---

## Out of Scope (tracked separately)

- **Empty stale dirs** `plugins/sandbox/` + `plugins/zoxide/` — todo 747 (auto-added during brainstorm).
- **Manual install verification** — see spec §Testing for the 4 manual checks. Run after merge as part of `cpm-install` smoke testing.
