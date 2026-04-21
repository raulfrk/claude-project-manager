# Installer `--local-marketplace` Flag Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `--local-marketplace` flag to the installer that clones `raulfrk/claude-project-manager` into a fixed cache dir, registers the local clone as the Claude Code marketplace source, and reuses the existing remove-and-re-add flow when the marketplace is already registered.

**Architecture:** A new `installer/local_marketplace.py` module owns git clone/update, branch checkout, and clone validity checks. `installer/cli.py` grows one bool flag. `installer/main.py` gains a thin `_resolve_marketplace_source(args)` helper that both `_install()` and `_reinstall()` use to pick between the GitHub short ref (default) and the local clone path (flag set). `plugin_cli.add_marketplace` is unchanged — it already accepts `source` + `branch`.

**Tech Stack:** Python 3.12, `subprocess` for git, `argparse` for CLI, `pytest` + `unittest.mock` for tests. All git commands are mocked in tests — no real clone, no network.

**Spec:** `docs/superpowers/specs/2026-04-21-installer-local-marketplace-design.md`

**Todo:** 683

**Worktree:** `/home/raul/worktrees/cpm/feat-installer-local-marketplace` (branch `feat/installer-local-marketplace`)

---

## File Structure

| Path | Responsibility | Op |
|------|---------------|-----|
| `installer/local_marketplace.py` | Module constants; `_run_git` subprocess wrapper; `_is_valid_clone`, `_default_branch` helpers; `ensure_local_clone()` public entry point. | Create |
| `installer/cli.py` | Add `--local-marketplace` arg (bool, `action="store_true"`). | Modify |
| `installer/main.py` | Import `ensure_local_clone`; add `_resolve_marketplace_source(args) -> tuple[str, str \| None]`; wire it into `_install()` (marketplace registration block, lines ~70-83) and `_reinstall()` (lines ~189-196). | Modify |
| `installer/tests/test_local_marketplace.py` | Unit tests for `_run_git`, `_is_valid_clone`, `_default_branch`, `ensure_local_clone`. | Create |
| `installer/tests/test_cli.py` | Append `test_local_marketplace_flag` + default assertion for the new flag. | Modify |
| `installer/tests/test_main.py` | Add `local_marketplace` default to `_make_args`; integration tests for `_resolve_marketplace_source` + `_install` + `_reinstall` wiring. | Modify |

---

## Task 1: Scaffold `installer/local_marketplace.py` with constants and a trivial test

**Files:**
- Create: `installer/local_marketplace.py`
- Create: `installer/tests/test_local_marketplace.py`

- [ ] **Step 1: Write the failing test for module constants**

Create `installer/tests/test_local_marketplace.py`:

```python
"""Tests for installer.local_marketplace — local clone management."""

from __future__ import annotations

from pathlib import Path


class TestConstants:
    def test_local_clone_dir_is_user_cache(self):
        from installer.local_marketplace import LOCAL_CLONE_DIR
        assert LOCAL_CLONE_DIR == Path.home() / ".cache" / "claude-project-manager" / "local-marketplace"

    def test_https_source_is_github_https_url(self):
        from installer.local_marketplace import _HTTPS_SOURCE
        assert _HTTPS_SOURCE == "https://github.com/raulfrk/claude-project-manager.git"

    def test_git_timeout_is_positive(self):
        from installer.local_marketplace import _GIT_TIMEOUT
        assert _GIT_TIMEOUT > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest installer/tests/test_local_marketplace.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'installer.local_marketplace'`.

- [ ] **Step 3: Create the module with constants**

Create `installer/local_marketplace.py`:

```python
"""Local marketplace clone management for the installer.

Clones the claude-project-manager marketplace repo into a fixed cache
directory so the installer can register a local path as the Claude Code
marketplace source (used by --local-marketplace).
"""

from __future__ import annotations

from pathlib import Path

LOCAL_CLONE_DIR = Path.home() / ".cache" / "claude-project-manager" / "local-marketplace"
_HTTPS_SOURCE = "https://github.com/raulfrk/claude-project-manager.git"
_GIT_TIMEOUT = 120  # seconds
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest installer/tests/test_local_marketplace.py -v`
Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add installer/local_marketplace.py installer/tests/test_local_marketplace.py
git commit -m "feat(installer/683): scaffold local_marketplace module"
```

---

## Task 2: `_run_git` subprocess wrapper

**Files:**
- Modify: `installer/local_marketplace.py`
- Modify: `installer/tests/test_local_marketplace.py`

- [ ] **Step 1: Write failing tests for `_run_git`**

Append to `installer/tests/test_local_marketplace.py`:

```python
import subprocess
from unittest.mock import MagicMock, patch

from installer.errors import InstallerError


class TestRunGit:
    @patch("installer.local_marketplace.subprocess.run")
    def test_success_returns_completed_process(self, mock_run):
        from installer.local_marketplace import _run_git
        mock_run.return_value = MagicMock(returncode=0, stdout="ok\n", stderr="")
        result = _run_git(["status"], cwd=None)
        assert result.returncode == 0
        # stdin=DEVNULL mirrors plugin_cli._run to avoid TTY leakage
        assert mock_run.call_args.kwargs["stdin"] == subprocess.DEVNULL

    @patch("installer.local_marketplace.subprocess.run")
    def test_nonzero_exit_raises_installer_error(self, mock_run):
        from installer.local_marketplace import _run_git
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="fatal: bad ref\n")
        with pytest.raises(InstallerError) as exc_info:
            _run_git(["checkout", "nope"], cwd=None)
        assert "fatal: bad ref" in str(exc_info.value)

    @patch("installer.local_marketplace.subprocess.run")
    def test_timeout_raises_installer_error(self, mock_run):
        from installer.local_marketplace import _run_git
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="git", timeout=120)
        with pytest.raises(InstallerError) as exc_info:
            _run_git(["clone", "foo"], cwd=None)
        assert "timed out" in str(exc_info.value).lower()

    @patch("installer.local_marketplace.subprocess.run")
    def test_cwd_is_passed_through(self, mock_run):
        from installer.local_marketplace import _run_git
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        _run_git(["status"], cwd=Path("/tmp/x"))
        assert mock_run.call_args.kwargs["cwd"] == Path("/tmp/x")
```

Add the `pytest` import at the top of the file if not present:

```python
import pytest
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest installer/tests/test_local_marketplace.py::TestRunGit -v`
Expected: FAIL with `ImportError: cannot import name '_run_git'`.

- [ ] **Step 3: Implement `_run_git`**

Append to `installer/local_marketplace.py`:

```python
import subprocess

from installer.errors import InstallerError


def _run_git(
    args: list[str], *, cwd: Path | None
) -> subprocess.CompletedProcess[str]:
    """Run ``git <args>`` and return the result.

    Mirrors ``installer.plugin_cli._run``:
    - ``stdin=DEVNULL`` prevents the child from grabbing the controlling TTY.
    - Timeout fires ``InstallerError``.
    - Non-zero exit fires ``InstallerError`` with combined stderr/stdout.
    """
    cmd = ["git", *args]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_TIMEOUT,
            stdin=subprocess.DEVNULL,
            cwd=cwd,
        )
    except subprocess.TimeoutExpired as exc:
        raise InstallerError(
            f"git command timed out after {_GIT_TIMEOUT}s: {' '.join(cmd)}"
        ) from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise InstallerError(
            f"git failed (exit {result.returncode}): {' '.join(cmd)}\n{detail}"
        )
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest installer/tests/test_local_marketplace.py -v`
Expected: all `TestConstants` and `TestRunGit` tests PASS (7 total).

- [ ] **Step 5: Commit**

```bash
git add installer/local_marketplace.py installer/tests/test_local_marketplace.py
git commit -m "feat(installer/683): add _run_git subprocess wrapper"
```

---

## Task 3: `_is_valid_clone` helper

**Files:**
- Modify: `installer/local_marketplace.py`
- Modify: `installer/tests/test_local_marketplace.py`

- [ ] **Step 1: Write failing tests for `_is_valid_clone`**

Append to `installer/tests/test_local_marketplace.py`:

```python
class TestIsValidClone:
    def test_false_when_dir_missing(self, tmp_path):
        from installer.local_marketplace import _is_valid_clone
        assert _is_valid_clone(tmp_path / "missing") is False

    def test_false_when_not_a_git_repo(self, tmp_path):
        from installer.local_marketplace import _is_valid_clone
        # A dir with contents but no .git
        (tmp_path / "file.txt").write_text("hi")
        assert _is_valid_clone(tmp_path) is False

    @patch("installer.local_marketplace._run_git")
    def test_false_when_origin_url_mismatches(self, mock_run_git, tmp_path):
        from installer.local_marketplace import _is_valid_clone
        (tmp_path / ".git").mkdir()
        mock_run_git.return_value = MagicMock(stdout="git@github.com:other/repo.git\n")
        assert _is_valid_clone(tmp_path) is False

    @patch("installer.local_marketplace._run_git")
    def test_true_when_origin_url_matches(self, mock_run_git, tmp_path):
        from installer.local_marketplace import _HTTPS_SOURCE, _is_valid_clone
        (tmp_path / ".git").mkdir()
        mock_run_git.return_value = MagicMock(stdout=f"{_HTTPS_SOURCE}\n")
        assert _is_valid_clone(tmp_path) is True

    @patch("installer.local_marketplace._run_git")
    def test_false_when_git_command_fails(self, mock_run_git, tmp_path):
        from installer.local_marketplace import _is_valid_clone
        (tmp_path / ".git").mkdir()
        mock_run_git.side_effect = InstallerError("no origin")
        assert _is_valid_clone(tmp_path) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest installer/tests/test_local_marketplace.py::TestIsValidClone -v`
Expected: FAIL with `ImportError: cannot import name '_is_valid_clone'`.

- [ ] **Step 3: Implement `_is_valid_clone`**

Append to `installer/local_marketplace.py`:

```python
def _is_valid_clone(path: Path) -> bool:
    """Return True if *path* is an existing clone of ``_HTTPS_SOURCE``.

    Checks:
    - ``path`` exists and contains a ``.git`` entry
    - ``git -C <path> remote get-url origin`` returns ``_HTTPS_SOURCE``
    """
    if not (path / ".git").exists():
        return False
    try:
        result = _run_git(["remote", "get-url", "origin"], cwd=path)
    except InstallerError:
        return False
    return result.stdout.strip() == _HTTPS_SOURCE
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest installer/tests/test_local_marketplace.py -v`
Expected: all tests PASS (12 total).

- [ ] **Step 5: Commit**

```bash
git add installer/local_marketplace.py installer/tests/test_local_marketplace.py
git commit -m "feat(installer/683): add _is_valid_clone helper"
```

---

## Task 4: `_default_branch` helper

**Files:**
- Modify: `installer/local_marketplace.py`
- Modify: `installer/tests/test_local_marketplace.py`

- [ ] **Step 1: Write failing tests for `_default_branch`**

Append to `installer/tests/test_local_marketplace.py`:

```python
class TestDefaultBranch:
    @patch("installer.local_marketplace._run_git")
    def test_returns_branch_name_from_symref(self, mock_run_git, tmp_path):
        from installer.local_marketplace import _default_branch
        mock_run_git.return_value = MagicMock(stdout="refs/remotes/origin/dev\n")
        assert _default_branch(tmp_path) == "dev"

    @patch("installer.local_marketplace._run_git")
    def test_strips_refs_remotes_origin_prefix(self, mock_run_git, tmp_path):
        from installer.local_marketplace import _default_branch
        mock_run_git.return_value = MagicMock(stdout="refs/remotes/origin/main\n")
        assert _default_branch(tmp_path) == "main"

    @patch("installer.local_marketplace._run_git")
    def test_falls_back_to_main_when_symref_not_set(self, mock_run_git, tmp_path):
        from installer.local_marketplace import _default_branch
        # origin/HEAD is not always set in a fresh clone without --origin-head
        mock_run_git.side_effect = InstallerError("ref refs/remotes/origin/HEAD is not a symbolic ref")
        assert _default_branch(tmp_path) == "main"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest installer/tests/test_local_marketplace.py::TestDefaultBranch -v`
Expected: FAIL with `ImportError: cannot import name '_default_branch'`.

- [ ] **Step 3: Implement `_default_branch`**

Append to `installer/local_marketplace.py`:

```python
_DEFAULT_BRANCH_FALLBACK = "main"


def _default_branch(repo_dir: Path) -> str:
    """Return the repo's default branch by resolving ``origin/HEAD``.

    Falls back to ``main`` if ``origin/HEAD`` is not set (some clones skip
    ``--origin-head`` resolution).
    """
    try:
        result = _run_git(
            ["symbolic-ref", "refs/remotes/origin/HEAD"],
            cwd=repo_dir,
        )
    except InstallerError:
        return _DEFAULT_BRANCH_FALLBACK
    # Output: "refs/remotes/origin/<branch>"
    return result.stdout.strip().rsplit("/", 1)[-1]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest installer/tests/test_local_marketplace.py -v`
Expected: all tests PASS (15 total).

- [ ] **Step 5: Commit**

```bash
git add installer/local_marketplace.py installer/tests/test_local_marketplace.py
git commit -m "feat(installer/683): add _default_branch helper"
```

---

## Task 5: `ensure_local_clone` public entry point

**Files:**
- Modify: `installer/local_marketplace.py`
- Modify: `installer/tests/test_local_marketplace.py`

- [ ] **Step 1: Write failing tests for `ensure_local_clone`**

Append to `installer/tests/test_local_marketplace.py`:

```python
class TestEnsureLocalClone:
    @patch("installer.local_marketplace.shutil.which", return_value="/usr/bin/git")
    @patch("installer.local_marketplace._is_valid_clone", return_value=False)
    @patch("installer.local_marketplace._run_git")
    def test_clones_when_dir_missing(self, mock_run_git, _is_valid, _which, tmp_path, monkeypatch):
        from installer.local_marketplace import _HTTPS_SOURCE, ensure_local_clone
        clone_dir = tmp_path / "mk"
        monkeypatch.setattr("installer.local_marketplace.LOCAL_CLONE_DIR", clone_dir)
        mock_run_git.return_value = MagicMock(stdout="", stderr="")
        returned = ensure_local_clone(branch="dev")
        # First call must be the clone
        first_call_args = mock_run_git.call_args_list[0].args[0]
        assert first_call_args[0] == "clone"
        assert _HTTPS_SOURCE in first_call_args
        assert str(clone_dir) in first_call_args
        assert returned == clone_dir

    @patch("installer.local_marketplace.shutil.which", return_value="/usr/bin/git")
    @patch("installer.local_marketplace._is_valid_clone", return_value=True)
    @patch("installer.local_marketplace._run_git")
    def test_fetches_and_resets_when_clone_exists(
        self, mock_run_git, _is_valid, _which, tmp_path, monkeypatch
    ):
        from installer.local_marketplace import ensure_local_clone
        clone_dir = tmp_path / "mk"
        clone_dir.mkdir()
        (clone_dir / ".git").mkdir()
        monkeypatch.setattr("installer.local_marketplace.LOCAL_CLONE_DIR", clone_dir)
        mock_run_git.return_value = MagicMock(stdout="", stderr="")
        ensure_local_clone(branch="dev")
        # Verify fetch, checkout, reset were called in order
        calls = [c.args[0] for c in mock_run_git.call_args_list]
        assert ["fetch", "origin"] in calls
        assert ["checkout", "dev"] in calls
        assert ["reset", "--hard", "origin/dev"] in calls

    @patch("installer.local_marketplace.shutil.which", return_value="/usr/bin/git")
    @patch("installer.local_marketplace._is_valid_clone", return_value=True)
    @patch("installer.local_marketplace._default_branch", return_value="main")
    @patch("installer.local_marketplace._run_git")
    def test_uses_default_branch_when_branch_none(
        self, mock_run_git, _default, _is_valid, _which, tmp_path, monkeypatch
    ):
        from installer.local_marketplace import ensure_local_clone
        clone_dir = tmp_path / "mk"
        clone_dir.mkdir()
        (clone_dir / ".git").mkdir()
        monkeypatch.setattr("installer.local_marketplace.LOCAL_CLONE_DIR", clone_dir)
        mock_run_git.return_value = MagicMock(stdout="", stderr="")
        ensure_local_clone(branch=None)
        calls = [c.args[0] for c in mock_run_git.call_args_list]
        assert ["checkout", "main"] in calls
        assert ["reset", "--hard", "origin/main"] in calls

    @patch("installer.local_marketplace.shutil.which", return_value=None)
    def test_raises_when_git_not_on_path(self, _which, monkeypatch, tmp_path):
        from installer.local_marketplace import ensure_local_clone
        monkeypatch.setattr("installer.local_marketplace.LOCAL_CLONE_DIR", tmp_path / "mk")
        with pytest.raises(InstallerError) as exc_info:
            ensure_local_clone(branch=None)
        assert "git" in str(exc_info.value).lower()

    @patch("installer.local_marketplace.shutil.which", return_value="/usr/bin/git")
    def test_raises_when_existing_dir_is_not_valid_clone(self, _which, tmp_path, monkeypatch):
        from installer.local_marketplace import ensure_local_clone
        clone_dir = tmp_path / "mk"
        clone_dir.mkdir()
        (clone_dir / "stray-file.txt").write_text("not a clone")
        monkeypatch.setattr("installer.local_marketplace.LOCAL_CLONE_DIR", clone_dir)
        with pytest.raises(InstallerError) as exc_info:
            ensure_local_clone(branch=None)
        assert "not a valid clone" in str(exc_info.value).lower()

    @patch("installer.local_marketplace.shutil.which", return_value="/usr/bin/git")
    @patch("installer.local_marketplace._run_git")
    def test_creates_parent_dir_before_clone(self, mock_run_git, _which, tmp_path, monkeypatch):
        from installer.local_marketplace import ensure_local_clone
        clone_dir = tmp_path / "deeply" / "nested" / "mk"
        monkeypatch.setattr("installer.local_marketplace.LOCAL_CLONE_DIR", clone_dir)
        mock_run_git.return_value = MagicMock(stdout="", stderr="")
        ensure_local_clone(branch=None)
        assert clone_dir.parent.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest installer/tests/test_local_marketplace.py::TestEnsureLocalClone -v`
Expected: FAIL with `ImportError: cannot import name 'ensure_local_clone'`.

- [ ] **Step 3: Implement `ensure_local_clone`**

Append to `installer/local_marketplace.py`:

```python
import shutil


def ensure_local_clone(branch: str | None = None) -> Path:
    """Ensure a valid clone at ``LOCAL_CLONE_DIR`` on the given branch.

    Behavior:
    - ``git`` missing on PATH → ``InstallerError``.
    - Dir missing: parent created, then ``git clone _HTTPS_SOURCE LOCAL_CLONE_DIR``,
      followed by ``git checkout <branch>`` and ``git reset --hard origin/<branch>``
      when ``branch`` differs from the clone's initial HEAD.
    - Dir exists and is a valid clone: ``git fetch origin``, ``git checkout <branch>``,
      ``git reset --hard origin/<branch>``.
    - Dir exists but is not a valid clone (stray files or wrong remote):
      ``InstallerError`` with guidance to delete the path.

    When ``branch`` is ``None``, resolves the remote's default branch via
    ``_default_branch`` and uses that.

    Returns the absolute path to the clone.
    """
    if shutil.which("git") is None:
        raise InstallerError("git not found on PATH")

    dest = LOCAL_CLONE_DIR

    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        _run_git(["clone", _HTTPS_SOURCE, str(dest)], cwd=None)
        target = branch or _default_branch(dest)
        _run_git(["fetch", "origin"], cwd=dest)
        _run_git(["checkout", target], cwd=dest)
        _run_git(["reset", "--hard", f"origin/{target}"], cwd=dest)
        return dest

    if not _is_valid_clone(dest):
        raise InstallerError(
            f"Cache dir at {dest} is not a valid clone of {_HTTPS_SOURCE}. "
            f"Delete it and retry."
        )

    target = branch or _default_branch(dest)
    _run_git(["fetch", "origin"], cwd=dest)
    _run_git(["checkout", target], cwd=dest)
    _run_git(["reset", "--hard", f"origin/{target}"], cwd=dest)
    return dest
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest installer/tests/test_local_marketplace.py -v`
Expected: all tests PASS (21 total).

- [ ] **Step 5: Commit**

```bash
git add installer/local_marketplace.py installer/tests/test_local_marketplace.py
git commit -m "feat(installer/683): implement ensure_local_clone entry point"
```

---

## Task 6: Add `--local-marketplace` CLI flag

**Files:**
- Modify: `installer/cli.py`
- Modify: `installer/tests/test_cli.py`

- [ ] **Step 1: Write failing tests**

Append to `installer/tests/test_cli.py` inside the `TestBuildParser` class:

```python
    def test_local_marketplace_default_false(self):
        parser = build_parser()
        args = parser.parse_args([])
        assert args.local_marketplace is False

    def test_local_marketplace_flag(self):
        parser = build_parser()
        args = parser.parse_args(["--local-marketplace"])
        assert args.local_marketplace is True

    def test_local_marketplace_with_branch(self):
        parser = build_parser()
        args = parser.parse_args(["--local-marketplace", "--branch", "dev"])
        assert args.local_marketplace is True
        assert args.branch == "dev"

    def test_local_marketplace_with_reinstall(self):
        parser = build_parser()
        args = parser.parse_args(["--reinstall", "--local-marketplace"])
        assert args.local_marketplace is True
        assert args.reinstall is True
```

Also update `test_default_flags` to include the new default:

Find in `installer/tests/test_cli.py`:

```python
    def test_default_flags(self):
        """No flags produces default namespace."""
        parser = build_parser()
        args = parser.parse_args([])
        assert args.reinstall is False
        assert args.uninstall is False
        assert args.full_cleanup is False
        assert args.plugins is None
        assert args.skip_wizard is False
        assert args.verbose is False
```

Replace with:

```python
    def test_default_flags(self):
        """No flags produces default namespace."""
        parser = build_parser()
        args = parser.parse_args([])
        assert args.reinstall is False
        assert args.uninstall is False
        assert args.full_cleanup is False
        assert args.plugins is None
        assert args.skip_wizard is False
        assert args.verbose is False
        assert args.local_marketplace is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest installer/tests/test_cli.py -v`
Expected: FAIL — `AttributeError: 'Namespace' object has no attribute 'local_marketplace'`.

- [ ] **Step 3: Add the flag to the parser**

Open `installer/cli.py`. After the existing `--branch` argument block (around line 72) and before the `--migrate` block, insert:

```python
    parser.add_argument(
        "--local-marketplace",
        action="store_true",
        help=(
            "Clone the marketplace repo into a local cache and register it as "
            "the marketplace source instead of pulling from GitHub directly."
        ),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest installer/tests/test_cli.py -v`
Expected: all tests PASS, including the 4 new ones.

- [ ] **Step 5: Commit**

```bash
git add installer/cli.py installer/tests/test_cli.py
git commit -m "feat(installer/683): add --local-marketplace CLI flag"
```

---

## Task 7: `_resolve_marketplace_source` helper in `installer/main.py`

**Files:**
- Modify: `installer/main.py`
- Modify: `installer/tests/test_main.py`

- [ ] **Step 1: Write failing tests**

Append to `installer/tests/test_main.py` (above the existing `TestInstall` class, after the `_make_args` helper):

```python
from installer.main import _resolve_marketplace_source
from installer.plugin_cli import _MARKETPLACE_SOURCE


class TestResolveMarketplaceSource:
    def test_default_uses_github_short_ref(self):
        args = _make_args()
        source, branch = _resolve_marketplace_source(args)
        assert source == _MARKETPLACE_SOURCE
        assert branch is None

    def test_branch_without_local_passes_through(self):
        args = _make_args(branch="dev")
        source, branch = _resolve_marketplace_source(args)
        assert source == _MARKETPLACE_SOURCE
        assert branch == "dev"

    @patch("installer.main.ensure_local_clone")
    def test_local_marketplace_returns_local_path_and_no_branch(self, mock_ensure):
        from pathlib import Path
        mock_ensure.return_value = Path("/home/x/.cache/cpm/local-marketplace")
        args = _make_args(local_marketplace=True)
        source, branch = _resolve_marketplace_source(args)
        mock_ensure.assert_called_once_with(branch=None)
        assert source == "/home/x/.cache/cpm/local-marketplace"
        assert branch is None

    @patch("installer.main.ensure_local_clone")
    def test_local_marketplace_passes_branch_to_ensure_clone(self, mock_ensure):
        from pathlib import Path
        mock_ensure.return_value = Path("/home/x/.cache/cpm/local-marketplace")
        args = _make_args(local_marketplace=True, branch="dev")
        source, branch = _resolve_marketplace_source(args)
        mock_ensure.assert_called_once_with(branch="dev")
        assert source == "/home/x/.cache/cpm/local-marketplace"
        # Branch returned as None because clone is already on that branch
        assert branch is None
```

Also update `_make_args` to include the new field:

Find in `installer/tests/test_main.py`:

```python
def _make_args(**overrides) -> argparse.Namespace:
    """Build a minimal args namespace with sensible defaults."""
    defaults = {
        "reinstall": False,
        "uninstall": False,
        "full_cleanup": False,
        "plugins": None,
        "skip_wizard": True,
        "verbose": False,
        "no_tui": True,
        "branch": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)
```

Replace with:

```python
def _make_args(**overrides) -> argparse.Namespace:
    """Build a minimal args namespace with sensible defaults."""
    defaults = {
        "reinstall": False,
        "uninstall": False,
        "full_cleanup": False,
        "plugins": None,
        "skip_wizard": True,
        "verbose": False,
        "no_tui": True,
        "branch": None,
        "local_marketplace": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest installer/tests/test_main.py::TestResolveMarketplaceSource -v`
Expected: FAIL with `ImportError: cannot import name '_resolve_marketplace_source'`.

- [ ] **Step 3: Add the helper to main.py**

Open `installer/main.py`. After the existing imports (around line 43, after `from installer.wizard import run_wizard`), add:

```python
from installer.local_marketplace import ensure_local_clone
from installer.plugin_cli import _MARKETPLACE_SOURCE
```

Then, after the `EXIT_ERROR = 2` line (around line 48) and before `def _install(args)`, add:

```python
def _resolve_marketplace_source(args) -> tuple[str, str | None]:
    """Return (source, branch) to pass to ``add_marketplace``.

    With ``--local-marketplace`` set, clones (or updates) the repo locally
    and returns the absolute path as the marketplace source. The branch is
    returned as ``None`` because ``ensure_local_clone`` already checks out
    the target branch inside the clone.

    Without ``--local-marketplace``, returns the hardcoded GitHub short ref
    and passes the raw ``--branch`` flag through.
    """
    if getattr(args, "local_marketplace", False):
        branch = getattr(args, "branch", None)
        local_path = ensure_local_clone(branch=branch)
        return (str(local_path), None)
    return (_MARKETPLACE_SOURCE, getattr(args, "branch", None))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest installer/tests/test_main.py::TestResolveMarketplaceSource -v`
Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add installer/main.py installer/tests/test_main.py
git commit -m "feat(installer/683): add _resolve_marketplace_source helper"
```

---

## Task 8: Wire `_install()` to use `_resolve_marketplace_source`

**Files:**
- Modify: `installer/main.py`
- Modify: `installer/tests/test_main.py`

- [ ] **Step 1: Write failing tests**

Append to `installer/tests/test_main.py` inside the `TestInstall` class:

```python
    @patch("installer.main.install_plugin")
    @patch("installer.main.get_installed_plugins", return_value=[])
    @patch("installer.main.get_available_plugins", return_value=["proj@claude-project-manager"])
    @patch("installer.main.add_marketplace")
    @patch("installer.main.remove_marketplace")
    @patch("installer.main.check_marketplace_registered", return_value=False)
    @patch("installer.main.run_wizard")
    @patch("installer.main.ensure_local_clone")
    def test_install_with_local_marketplace_adds_local_path(
        self, mock_ensure, _wizard, _check_mp, mock_remove, mock_add,
        _avail, _installed, _install_plugin,
    ):
        from pathlib import Path
        mock_ensure.return_value = Path("/home/x/.cache/cpm/mk")
        args = _make_args(plugins=["proj"], local_marketplace=True)
        result = _install(args)
        assert result == EXIT_SUCCESS
        mock_ensure.assert_called_once_with(branch=None)
        mock_add.assert_called_once_with(source="/home/x/.cache/cpm/mk", branch=None)
        mock_remove.assert_not_called()

    @patch("installer.main.install_plugin")
    @patch("installer.main.get_installed_plugins", return_value=[])
    @patch("installer.main.get_available_plugins", return_value=["proj@claude-project-manager"])
    @patch("installer.main.add_marketplace")
    @patch("installer.main.remove_marketplace")
    @patch("installer.main.check_marketplace_registered", return_value=True)
    @patch("installer.main.run_wizard")
    @patch("installer.main.ensure_local_clone")
    def test_install_local_marketplace_when_already_registered_removes_and_readds(
        self, mock_ensure, _wizard, _check_mp, mock_remove, mock_add,
        _avail, _installed, _install_plugin,
    ):
        from pathlib import Path
        mock_ensure.return_value = Path("/home/x/.cache/cpm/mk")
        args = _make_args(plugins=["proj"], local_marketplace=True)
        _install(args)
        mock_remove.assert_called_once()
        mock_add.assert_called_once_with(source="/home/x/.cache/cpm/mk", branch=None)

    @patch("installer.main.install_plugin")
    @patch("installer.main.get_installed_plugins", return_value=[])
    @patch("installer.main.get_available_plugins", return_value=["proj@claude-project-manager"])
    @patch("installer.main.add_marketplace")
    @patch("installer.main.check_marketplace_registered", return_value=False)
    @patch("installer.main.run_wizard")
    @patch("installer.main.ensure_local_clone")
    def test_install_local_marketplace_with_branch_passes_branch_to_ensure(
        self, mock_ensure, _wizard, _check_mp, mock_add, _avail, _installed, _install_plugin,
    ):
        from pathlib import Path
        mock_ensure.return_value = Path("/home/x/.cache/cpm/mk")
        args = _make_args(plugins=["proj"], local_marketplace=True, branch="dev")
        _install(args)
        mock_ensure.assert_called_once_with(branch="dev")
        mock_add.assert_called_once_with(source="/home/x/.cache/cpm/mk", branch=None)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest installer/tests/test_main.py::TestInstall -v`
Expected: 3 new tests FAIL — `_install` still calls `add_marketplace()` with no args (which defaults to the GitHub ref), not the local path.

- [ ] **Step 3: Replace the marketplace registration block in `_install`**

Open `installer/main.py`. Find the existing block inside `_install()` (around lines 69-83):

```python
    # 3. Ensure marketplace is registered (with optional branch)
    branch = getattr(args, "branch", None)
    with console.status("[bold]Checking marketplace registration..."):
        if not check_marketplace_registered():
            branch_msg = f" (branch: {branch})" if branch else ""
            console.print(f"Marketplace not registered. Adding...{branch_msg}")
            add_marketplace(branch=branch)
            console.print("[green]Marketplace registered.[/green]")
        elif branch:
            console.print(f"Re-adding marketplace for branch: {branch}")
            remove_marketplace()
            add_marketplace(branch=branch)
            console.print(f"[green]Marketplace updated to branch {branch}.[/green]")
        else:
            console.print("[dim]Marketplace already registered.[/dim]")
```

Replace with:

```python
    # 3. Ensure marketplace is registered (optionally from a local clone)
    source, branch = _resolve_marketplace_source(args)
    source_is_local = getattr(args, "local_marketplace", False)
    with console.status("[bold]Checking marketplace registration..."):
        if not check_marketplace_registered():
            branch_msg = f" (branch: {branch})" if branch else ""
            source_msg = " from local clone" if source_is_local else ""
            console.print(f"Marketplace not registered. Adding{source_msg}...{branch_msg}")
            add_marketplace(source=source, branch=branch)
            console.print("[green]Marketplace registered.[/green]")
        elif source_is_local or branch:
            label = "local clone" if source_is_local else f"branch {branch}"
            console.print(f"Re-adding marketplace from {label}")
            remove_marketplace()
            add_marketplace(source=source, branch=branch)
            console.print(f"[green]Marketplace updated from {label}.[/green]")
        else:
            console.print("[dim]Marketplace already registered.[/dim]")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest installer/tests/test_main.py::TestInstall -v`
Expected: all `TestInstall` tests PASS (existing + 3 new).

- [ ] **Step 5: Commit**

```bash
git add installer/main.py installer/tests/test_main.py
git commit -m "feat(installer/683): wire _install() to use local marketplace path"
```

---

## Task 9: Wire `_reinstall()` to use `_resolve_marketplace_source`

**Files:**
- Modify: `installer/main.py`
- Modify: `installer/tests/test_main.py`

- [ ] **Step 1: Write failing tests**

Append to `installer/tests/test_main.py` inside the `TestReinstall` class (or create it if missing). Here's the complete class addition — if `TestReinstall` already exists, add only the new methods:

```python
class TestReinstall:
    """Tests for _reinstall()."""

    @patch("installer.main.install_plugin")
    @patch("installer.main.add_marketplace")
    @patch("installer.main.remove_marketplace")
    @patch("installer.main.scan_stale_cache", side_effect=FileNotFoundError("skip"))
    @patch("installer.main.display_detection")
    @patch("installer.main.detect_existing", return_value=InstallState())
    @patch("installer.main.get_installed_plugins", return_value=["proj@claude-project-manager"])
    @patch("installer.main.run_wizard")
    @patch("installer.main.ensure_local_clone")
    def test_reinstall_with_local_marketplace_adds_local_path(
        self, mock_ensure, _wizard, _installed, _detect, _display, _scan,
        mock_remove, mock_add, _install_plugin,
    ):
        from pathlib import Path
        mock_ensure.return_value = Path("/home/x/.cache/cpm/mk")
        args = _make_args(reinstall=True, local_marketplace=True)
        result = _reinstall(args)
        mock_remove.assert_called_once()
        mock_add.assert_called_once_with(source="/home/x/.cache/cpm/mk", branch=None)
        assert result == EXIT_SUCCESS

    @patch("installer.main.install_plugin")
    @patch("installer.main.add_marketplace")
    @patch("installer.main.remove_marketplace")
    @patch("installer.main.scan_stale_cache", side_effect=FileNotFoundError("skip"))
    @patch("installer.main.display_detection")
    @patch("installer.main.detect_existing", return_value=InstallState())
    @patch("installer.main.get_installed_plugins", return_value=["proj@claude-project-manager"])
    @patch("installer.main.run_wizard")
    @patch("installer.main.ensure_local_clone")
    def test_reinstall_local_marketplace_with_branch(
        self, mock_ensure, _wizard, _installed, _detect, _display, _scan,
        mock_remove, mock_add, _install_plugin,
    ):
        from pathlib import Path
        mock_ensure.return_value = Path("/home/x/.cache/cpm/mk")
        args = _make_args(reinstall=True, local_marketplace=True, branch="dev")
        _reinstall(args)
        mock_ensure.assert_called_once_with(branch="dev")
        mock_add.assert_called_once_with(source="/home/x/.cache/cpm/mk", branch=None)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest installer/tests/test_main.py::TestReinstall -v`
Expected: FAIL — `_reinstall` currently ignores `local_marketplace` and passes the default source to `add_marketplace`.

- [ ] **Step 3: Patch the reinstall block**

Open `installer/main.py`. Find the existing block inside `_reinstall()` (around lines 153-196):

```python
    plugins = list(installed)
    branch = getattr(args, "branch", None)

    console.print(f"\n[bold]Reinstalling:[/bold] {', '.join(plugins)}")

    # Prune stale cache versions and orphaned plugins before reinstall
    cache_dir = _cache_dir_for_reinstall()
    marketplace_path = _marketplace_path_for_reinstall()
    ...
    # Remove marketplace (uninstalls all plugins) then re-add
    with console.status("[bold]Removing marketplace...[/bold]"):
        remove_marketplace()
    console.print("  [green]✓[/green] Marketplace removed")

    branch_msg = f" (branch: {branch})" if branch else ""
    with console.status(f"[bold]Re-adding marketplace{branch_msg}...[/bold]"):
        add_marketplace(branch=branch)
    console.print(f"  [green]✓[/green] Marketplace re-added{branch_msg}")
```

Replace the `branch = getattr(args, "branch", None)` line and the re-add block (keeping the cache-pruning in the middle unchanged):

Find:
```python
    plugins = list(installed)
    branch = getattr(args, "branch", None)
```

Replace with:
```python
    plugins = list(installed)
    source, branch = _resolve_marketplace_source(args)
    source_is_local = getattr(args, "local_marketplace", False)
```

Find:
```python
    branch_msg = f" (branch: {branch})" if branch else ""
    with console.status(f"[bold]Re-adding marketplace{branch_msg}...[/bold]"):
        add_marketplace(branch=branch)
    console.print(f"  [green]✓[/green] Marketplace re-added{branch_msg}")
```

Replace with:
```python
    if source_is_local:
        label = "from local clone"
    elif branch:
        label = f"(branch: {branch})"
    else:
        label = ""
    with console.status(f"[bold]Re-adding marketplace {label}...[/bold]"):
        add_marketplace(source=source, branch=branch)
    console.print(f"  [green]✓[/green] Marketplace re-added {label}".rstrip())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest installer/tests/test_main.py::TestReinstall -v`
Expected: new tests PASS. Existing `TestReinstall` tests (if any) still PASS.

- [ ] **Step 5: Commit**

```bash
git add installer/main.py installer/tests/test_main.py
git commit -m "feat(installer/683): wire _reinstall() to use local marketplace path"
```

---

## Task 10: Full-suite green + static checks

**Files:**
- No new code. Verification only.

- [ ] **Step 1: Run the full installer test suite**

Run: `uv run pytest installer/tests -v`
Expected: all tests PASS. No regressions in pre-existing tests.

- [ ] **Step 2: Run ruff format + lint**

Run: `uv run ruff format installer/local_marketplace.py installer/cli.py installer/main.py installer/tests/test_local_marketplace.py installer/tests/test_cli.py installer/tests/test_main.py`
Then: `uv run ruff check installer/local_marketplace.py installer/cli.py installer/main.py`
Expected: no issues reported.

- [ ] **Step 3: Run basedpyright type check**

Run: `uv run basedpyright installer/local_marketplace.py installer/main.py`
Expected: no errors. (Warnings from pre-existing code are acceptable; new errors from the new module are not.)

- [ ] **Step 4: Smoke-test the CLI parser**

Run: `uv run python -c "from installer.cli import build_parser; p = build_parser(); args = p.parse_args(['--local-marketplace', '--branch', 'dev']); print(args.local_marketplace, args.branch)"`
Expected output: `True dev`

- [ ] **Step 5: Commit any formatter diffs if ruff format modified files**

```bash
git add -u
git diff --cached --quiet || git commit -m "chore(installer/683): ruff format"
```

(If there is no diff, this is a no-op.)

---

## Out of scope (follow-ups)

- Cleaning the local clone dir on `--uninstall --full-cleanup`. File as a separate todo if desired.
- Accepting a user-supplied path instead of always cloning from GitHub.
- An alternate source URL (SSH, other forks).
- TUI-flow integration (`installer/flow/installer_flow.py`) — current flow already routes through `_install()` / `_reinstall()` when `--no-tui` is set. If the TUI path needs parallel wiring, confirm with user and file a follow-up.
