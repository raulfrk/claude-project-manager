# Shared-venv lookup + creation fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the broken shared-venv path so plugins use one venv at the marketplace root instead of always falling back to per-plugin `uv sync` (which requires open PyPI access).

**Architecture:** Three coordinated changes — (1) `start.sh` does a 3-stage cascading lookup (walk-up → basename → per-plugin diagnostic), (2) installer creates the shared venv via a new `add_marketplace_with_shared_venv` wrapper around all 6 `add_marketplace` call sites, (3) `scripts/presync.sh` plugin list refreshed + shared-venv step appended.

**Tech Stack:** Bash (`start.sh`, `presync.sh`), Python 3.12+ + uv (installer), pytest (tests), subprocess (uv invocation).

**Spec:** `docs/superpowers/specs/2026-04-25-shared-venv-lookup-fix-design.md`

**Worktree:** `/home/raul/worktrees/claude-project-manager/feat-shared-venv-lookup-fix` (branch `feat/shared-venv-lookup-fix`). All file edits + git operations must happen in this directory.

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `plugins/proj/start.sh` | Modify lines 48-56 | New 3-stage cascading shared-venv lookup |
| `plugins/{worktree,trello,jira,router,todoist,confluence,wiki}/start.sh` | Replace (cp from proj) | Identical copies |
| `installer/shared_venv.py` | Create | `ensure_shared_venv()` + `add_marketplace_with_shared_venv()` |
| `installer/tests/test_shared_venv.py` | Create | Unit tests for both functions |
| `installer/main.py` | Modify imports + 3 call sites | Use wrapper instead of raw `add_marketplace` |
| `installer/flow/installer_flow.py` | Modify imports + 3 call sites | Use wrapper instead of raw `add_marketplace` |
| `installer/tests/test_main.py` | Modify | Update existing mocks to point at wrapper |
| `scripts/presync.sh` | Modify lines 19 + append | Refresh plugin list + add shared-venv step |
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

- [ ] **Step 2: Run existing tests against unmodified start.sh path**

Wait — `start.sh` has already been modified in Task 1. Run existing tests against the new file:

```bash
uv run --directory installer pytest /home/raul/worktrees/claude-project-manager/feat-shared-venv-lookup-fix/tests/test_install.py::TestStartShSharedVenv -v
```

Expected: `test_uses_shared_venv_when_present` passes (Stage 2 basename lookup still hits the same path). `test_falls_back_to_per_plugin_venv` may need updating — its assertion `"falling back" in r.stderr.lower()` should still match since new text is `"falling back to per-plugin venv:"`. Note the test does a `content.replace` on a line that no longer exists in current start.sh (`test -f "$DIR/.venv/bin/python" || uv sync ...`); that replace is a no-op. The test should still work because it just checks the chosen `UV_PROJECT_ENVIRONMENT` ends in `<server_dir>/.venv` and the fallback message appears.

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
uv run --directory installer pytest /home/raul/worktrees/claude-project-manager/feat-shared-venv-lookup-fix/tests/test_install.py::TestStartShSharedVenv::test_walk_up_finds_local_marketplace_venv -v
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
uv run --directory installer pytest /home/raul/worktrees/claude-project-manager/feat-shared-venv-lookup-fix/tests/test_install.py::TestStartShSharedVenv::test_diagnostic_emits_three_paths_on_total_miss -v
```

Expected: PASS.

- [ ] **Step 7: Run full `TestStartSh*` class set to confirm no regressions**

```bash
uv run --directory installer pytest /home/raul/worktrees/claude-project-manager/feat-shared-venv-lookup-fix/tests/test_install.py -k 'TestStartSh' -v
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
"""Shared marketplace venv creation + add_marketplace wrapper.

Creates a single .venv at the marketplace root so all plugins share one
Python environment. Replaces the per-plugin uv-sync fallback that fires
when no shared venv is found.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from installer.errors import InstallerError
from installer.local_marketplace import LOCAL_CLONE_DIR
from installer.plugin_cli import MARKETPLACE_NAME, add_marketplace

_UV_SYNC_TIMEOUT = 300  # seconds; uv sync can be slow on cold cache


def _marketplaces_dir() -> Path:
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


def add_marketplace_with_shared_venv(
    source: str, branch: str | None = None
) -> None:
    """Register the marketplace and create the shared venv.

    Calls add_marketplace(source, branch) first; if that fails, the error
    propagates. Then creates the shared venv at the standard marketplaces
    location (~/.claude/plugins/marketplaces/<name>/), and additionally at
    LOCAL_CLONE_DIR if source points there. Failures of ensure_shared_venv
    are caught and logged as warnings — install continues so that per-plugin
    fallback in start.sh can still work.
    """
    add_marketplace(source=source, branch=branch)

    venv_targets: list[Path] = [_marketplaces_dir()]
    try:
        source_path = Path(source)
        if source_path.exists() and source_path.resolve() == LOCAL_CLONE_DIR.resolve():
            venv_targets.append(LOCAL_CLONE_DIR)
    except (OSError, ValueError):
        pass  # source is a URL, not a path — ignore

    for target in venv_targets:
        try:
            ensure_shared_venv(target)
        except InstallerError as exc:
            print(
                f"[warn] failed to create shared venv at {target}: {exc}",
                file=sys.stderr,
            )
            print(
                "[warn] plugins will fall back to per-plugin uv sync at runtime",
                file=sys.stderr,
            )
```

- [ ] **Step 2: Run Task 4 test — verify it passes**

```bash
uv run --directory installer pytest installer/tests/test_shared_venv.py::TestEnsureSharedVenv::test_happy_path_invokes_uv_sync_in_marketplace_dir -v
```

Expected: PASS.

- [ ] **Step 3: Commit (intermediate — module + happy-path test)**

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

### Task 6: Add failure-path test for `ensure_shared_venv`

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

Expected: all 3 pass (the impl from Task 5 already handles both error paths).

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

### Task 7: Add tests for `add_marketplace_with_shared_venv` wrapper

**Files:**
- Modify: `installer/tests/test_shared_venv.py`

- [ ] **Step 1: Add wrapper test class to `installer/tests/test_shared_venv.py`**

Append to the file:

```python
class TestAddMarketplaceWithSharedVenv:
    @patch("installer.shared_venv.ensure_shared_venv")
    @patch("installer.shared_venv.add_marketplace")
    def test_calls_add_marketplace_then_ensure_at_marketplaces_dir(
        self, mock_add, mock_ensure
    ):
        from installer.shared_venv import (
            _marketplaces_dir,
            add_marketplace_with_shared_venv,
        )

        add_marketplace_with_shared_venv(source="raulfrk/cpm", branch="dev")

        mock_add.assert_called_once_with(source="raulfrk/cpm", branch="dev")
        mock_ensure.assert_called_once_with(_marketplaces_dir())

    @patch("installer.shared_venv.ensure_shared_venv")
    @patch("installer.shared_venv.add_marketplace")
    def test_local_clone_source_also_creates_venv_at_local_clone(
        self, mock_add, mock_ensure, tmp_path, monkeypatch
    ):
        from installer.shared_venv import (
            _marketplaces_dir,
            add_marketplace_with_shared_venv,
        )

        # Patch LOCAL_CLONE_DIR to a tmp path that exists
        local_clone = tmp_path / "local-marketplace"
        local_clone.mkdir()
        monkeypatch.setattr(
            "installer.shared_venv.LOCAL_CLONE_DIR", local_clone
        )

        add_marketplace_with_shared_venv(source=str(local_clone), branch=None)

        mock_add.assert_called_once_with(source=str(local_clone), branch=None)
        # Both targets should be ensured
        ensure_calls = {c.args[0] for c in mock_ensure.call_args_list}
        assert _marketplaces_dir() in ensure_calls
        assert local_clone in ensure_calls

    @patch("installer.shared_venv.ensure_shared_venv")
    @patch("installer.shared_venv.add_marketplace")
    def test_url_source_does_not_create_at_local_clone(self, mock_add, mock_ensure):
        from installer.shared_venv import (
            _marketplaces_dir,
            add_marketplace_with_shared_venv,
        )

        add_marketplace_with_shared_venv(source="raulfrk/cpm", branch=None)

        ensure_calls = [c.args[0] for c in mock_ensure.call_args_list]
        assert ensure_calls == [_marketplaces_dir()]

    @patch("installer.shared_venv.ensure_shared_venv")
    @patch("installer.shared_venv.add_marketplace")
    def test_ensure_failure_warns_but_does_not_raise(
        self, mock_add, mock_ensure, capsys
    ):
        from installer.shared_venv import add_marketplace_with_shared_venv

        mock_ensure.side_effect = InstallerError("boom")
        # Should not raise
        add_marketplace_with_shared_venv(source="raulfrk/cpm", branch=None)
        captured = capsys.readouterr()
        assert "[warn]" in captured.err
        assert "boom" in captured.err
        assert "fall back" in captured.err

    @patch("installer.shared_venv.ensure_shared_venv")
    @patch("installer.shared_venv.add_marketplace")
    def test_add_marketplace_failure_propagates(self, mock_add, mock_ensure):
        from installer.shared_venv import add_marketplace_with_shared_venv

        mock_add.side_effect = InstallerError("network down")
        with pytest.raises(InstallerError, match="network down"):
            add_marketplace_with_shared_venv(source="raulfrk/cpm", branch=None)
        # ensure_shared_venv should not have been called
        mock_ensure.assert_not_called()
```

- [ ] **Step 2: Run the wrapper test class**

```bash
uv run --directory installer pytest installer/tests/test_shared_venv.py::TestAddMarketplaceWithSharedVenv -v
```

Expected: all 5 pass (the impl from Task 5 already covers all behaviors).

- [ ] **Step 3: Commit**

```bash
git add installer/tests/test_shared_venv.py
git commit -m "$(cat <<'EOF'
test(shared_venv): cover add_marketplace_with_shared_venv wrapper

Five tests: marketplaces-dir target, additional local-clone target when
source is LOCAL_CLONE_DIR, URL source skips local-clone, ensure failure
warns + continues, add_marketplace failure propagates.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: Wire wrapper into `installer/main.py`

**Files:**
- Modify: `installer/main.py:32` (import) + lines 107, 118, 247 (call sites)
- Modify: `installer/tests/test_main.py` (existing mocks)

- [ ] **Step 1: Read current import block to find `add_marketplace`**

```bash
sed -n '25,45p' installer/main.py
```

Expected: see `from installer.plugin_cli import (add_marketplace, ...)`.

- [ ] **Step 2: Replace the `add_marketplace` import with the wrapper, aliased to keep call sites unchanged**

Edit `installer/main.py`. Find the line:

```python
    add_marketplace,
```

inside the `from installer.plugin_cli import (...)` block. Remove it from that block. Then add this new import directly below the `from installer.plugin_cli import (...)` block:

```python
from installer.shared_venv import add_marketplace_with_shared_venv as add_marketplace
```

(The alias keeps `_install` and `_reinstall` calling `add_marketplace(source=, branch=)` literally — no per-call-site edits needed.)

- [ ] **Step 3: Run existing test_main.py tests**

```bash
uv run --directory installer pytest installer/tests/test_main.py -v
```

Expected: tests that mock `installer.main.add_marketplace` should still pass — the mock now intercepts the wrapper instead of the underlying CLI call. Internal `ensure_shared_venv` is bypassed because the wrapper itself is mocked. If any test fails because it asserts internal behavior, update it to mock at the deeper level (`installer.shared_venv.add_marketplace` for the underlying CLI, or `installer.shared_venv.ensure_shared_venv` for the venv step).

- [ ] **Step 4: Commit**

```bash
git add installer/main.py
git commit -m "$(cat <<'EOF'
feat(installer/main): route add_marketplace through shared-venv wrapper

Aliasing keeps _install/_reinstall call sites unchanged while the wrapper
runs ensure_shared_venv post-registration. Mocks at installer.main.add_marketplace
continue to work — they now intercept the wrapper.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: Wire wrapper into `installer/flow/installer_flow.py`

**Files:**
- Modify: `installer/flow/installer_flow.py:46` (import) — call sites at lines 345, 355, 516 stay literal

- [ ] **Step 1: Read import block**

```bash
sed -n '40,55p' installer/flow/installer_flow.py
```

Expected: `from installer.plugin_cli import (..., add_marketplace, ...)`.

- [ ] **Step 2: Apply the same alias swap**

Edit `installer/flow/installer_flow.py`. Remove `add_marketplace` from the `from installer.plugin_cli import (...)` block. Add new import directly below it:

```python
from installer.shared_venv import add_marketplace_with_shared_venv as add_marketplace
```

- [ ] **Step 3: Run flow tests**

```bash
uv run --directory installer pytest installer/tests/flow/ -v
```

Expected: green. If anything fails on assertions about `add_marketplace`, same fix as Task 8 Step 3 — mocks may need to point at `installer.flow.installer_flow.add_marketplace` (which now refers to the wrapper).

- [ ] **Step 4: Run the full installer test suite**

```bash
uv run --directory installer pytest installer/tests/ -v
```

Expected: green.

- [ ] **Step 5: Commit**

```bash
git add installer/flow/installer_flow.py
git commit -m "$(cat <<'EOF'
feat(installer/flow): route add_marketplace through shared-venv wrapper

Same alias pattern as installer/main.py — three call sites at lines 345,
355, 516 stay literal; the import alias swaps the underlying impl.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 10: Refresh `scripts/presync.sh`

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

### Task 11: Final verification sweep

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

Expected: `git status -s` shows no modified files (clean tree). `git log` shows ~9 new commits on the branch (one per Task except Task 11).

- [ ] **Step 4: Hand off**

Implementation complete. Use `superpowers:finishing-a-development-branch` skill to decide merge strategy (FF-merge to dev per CLAUDE.md feedback memory).

---

## Out of Scope (tracked separately)

- **Empty stale dirs** `plugins/sandbox/` + `plugins/zoxide/` — todo 747 (auto-added during brainstorm).
- **Manual install verification** — see spec §Testing for the 4 manual checks. Run after merge as part of `cpm-install` smoke testing.
