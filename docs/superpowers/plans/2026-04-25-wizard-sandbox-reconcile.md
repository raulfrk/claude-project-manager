# Wizard Sandbox Reconcile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auto-reconcile `~/.claude/settings.json` MCP allow rules during install, by factoring sandbox lib to `_shared` and wiring a `_finalize_sandbox` step into both TUI and `--no-tui` install flows.

**Architecture:** Move pure-Python sandbox library out of `plugins/proj/.../lib/sandbox/` into `plugins/_shared/sandbox/`. Add `reconcile_settings(...)` factored from the existing `sandbox_reconcile` MCP tool. Installer + plugin both consume the shared lib. New install-flow step fires after `prompt_kill_stale_sessions` and before `_finalize_shared_venv` in `_run_install`/`_run_reinstall`/`_run_update` (TUI) and `_install`/`_reinstall` (`--no-tui`).

**Tech Stack:** Python (dataclasses, json, pathlib, tempfile), pytest with monkeypatch + tmp_path.

**Spec:** `docs/superpowers/specs/2026-04-25-wizard-sandbox-reconcile-design.md`

---

## File Structure

| File | Responsibility | Action |
|------|----------------|--------|
| `plugins/_shared/sandbox/__init__.py` | Public API: `reconcile_settings`, `ReconcileResult`, `PLUGIN_TO_MCP_SERVER`, re-exports of storage primitives | NEW |
| `plugins/_shared/sandbox/models.py` | `Permissions`, `SandboxFilesystem`, `SettingsFile` dataclasses | MOVED from `plugins/proj/server/server/lib/sandbox/models.py` |
| `plugins/_shared/sandbox/storage.py` | atomic load/save, `mcp_allow_entry`, `allow_entries_for_path`, `skill_allow_entry` | MOVED from `plugins/proj/server/server/lib/sandbox/storage.py` |
| `plugins/_shared/sandbox/reconcile.py` | Pure `reconcile_settings(...) -> ReconcileResult` | NEW |
| `plugins/_shared/pyproject.toml` | Add `sandbox` to wheel packages, bump version to 0.4.30 | MODIFY |
| `plugins/proj/server/server/lib/sandbox/__init__.py` | Back-compat shim re-exporting from `_shared` | REPLACE |
| `plugins/proj/server/server/lib/sandbox/storage.py` | (removed) | DELETE |
| `plugins/proj/server/server/lib/sandbox/models.py` | (removed) | DELETE |
| `plugins/proj/server/server/tools/sandbox.py` | Update imports to use `from sandbox import ...`; thin-wrap `sandbox_reconcile` MCP tool | MODIFY |
| `installer/flow/installer_flow.py` | New `_finalize_sandbox` helper + 3 call-site updates | MODIFY |
| `installer/main.py` | New call sites in `_install` + `_reinstall` | MODIFY |
| `plugins/_shared/tests/test_sandbox_reconcile.py` | 5 unit tests on pure `reconcile_settings` | NEW |
| `installer/tests/test_finalize_sandbox.py` | 4 tests on `_finalize_sandbox` step | NEW |
| `installer/tests/flow/test_installer_flow.py::TestKillStaleOrdering` | Extend ordering helper for kill < sandbox < venv | MODIFY |
| `installer/tests/test_main.py` | Add 3 ordering tests for --no-tui paths | MODIFY |
| `plugins/proj/skills/sandbox/SKILL.md` | sed (16 hits) | MODIFY |
| `plugins/proj/skills/init-plugin/SKILL.md` | sed (7 hits) | MODIFY |
| `plugins/proj/evals/init-plugin.md` | sed (4 hits) | MODIFY |
| `plugins/worktree/skills/create/SKILL.md` | sed (2 hits) | MODIFY |

---

## Task 1: Move sandbox lib to `_shared` (storage + models)

**Files:**
- Create: `plugins/_shared/sandbox/__init__.py`
- Create: `plugins/_shared/sandbox/models.py`
- Create: `plugins/_shared/sandbox/storage.py`
- Modify: `plugins/_shared/pyproject.toml`
- Replace: `plugins/proj/server/server/lib/sandbox/__init__.py`
- Delete: `plugins/proj/server/server/lib/sandbox/storage.py`
- Delete: `plugins/proj/server/server/lib/sandbox/models.py`
- Modify: `plugins/proj/server/server/tools/sandbox.py` (import updates only — function bodies stay; reconcile factoring is Task 3)

This task is the lift-and-shift. After it, `_shared/sandbox` exists, proj's lib/sandbox is a back-compat shim, and tools/sandbox.py imports from `_shared`. Pre-commit hook enforces `_shared` version bump on changes — bump in same commit.

- [ ] **Step 1: Create `plugins/_shared/sandbox/models.py`**

Copy the entire current contents of `plugins/proj/server/server/lib/sandbox/models.py` to `plugins/_shared/sandbox/models.py` verbatim. The file is pure-Python dataclasses with no imports from `server.*` — straight copy.

- [ ] **Step 2: Create `plugins/_shared/sandbox/storage.py`**

Copy `plugins/proj/server/server/lib/sandbox/storage.py` to `plugins/_shared/sandbox/storage.py`. Change one import line:

```python
from server.lib.sandbox.models import SettingsFile
```

to:

```python
from sandbox.models import SettingsFile
```

The rest (atomic write, `mcp_allow_entry`, `allow_entries_for_path`, `skill_allow_entry`, `SETTINGS_PATH` constant) stays identical.

- [ ] **Step 3: Create `plugins/_shared/sandbox/__init__.py`**

```python
"""Sandbox library shared between installer and proj plugin.

Pure-Python lib for reading/writing ~/.claude/settings.json. Owns the
allow-rule semantics for MCP servers, sandbox paths, and skill prefixes.
The proj plugin's tools/sandbox.py wraps these primitives in MCP tools;
the installer calls reconcile_settings directly during install finalize.
"""

from __future__ import annotations

from sandbox import storage
from sandbox.models import (
    Permissions,
    SandboxFilesystem,
    SettingsFile,
)
from sandbox.storage import (
    SETTINGS_PATH,
    allow_entries_for_path,
    mcp_allow_entry,
    skill_allow_entry,
)

__all__ = [
    "Permissions",
    "SETTINGS_PATH",
    "SandboxFilesystem",
    "SettingsFile",
    "allow_entries_for_path",
    "mcp_allow_entry",
    "skill_allow_entry",
    "storage",
]
```

(Note: `reconcile_settings`, `ReconcileResult`, `PLUGIN_TO_MCP_SERVER` get added in Task 3. This task lands the lib move only.)

- [ ] **Step 4: Update `plugins/_shared/pyproject.toml`**

Find the `[tool.hatch.build.targets.wheel]` section. Current:

```toml
[tool.hatch.build.targets.wheel]
packages = ["hook_transport", "hook_dispatch", "scrubbing", "test_contracts", "claudemd", "session_key"]
```

Add `sandbox` to the list:

```toml
[tool.hatch.build.targets.wheel]
packages = ["hook_transport", "hook_dispatch", "scrubbing", "test_contracts", "claudemd", "session_key", "sandbox"]
```

Bump version. Find:

```toml
version = "0.4.29"
```

Change to:

```toml
version = "0.4.30"
```

- [ ] **Step 5: Replace `plugins/proj/server/server/lib/sandbox/__init__.py` with a back-compat shim**

Replace the file content with:

```python
"""Back-compat shim — sandbox lib lives in plugins/_shared/sandbox/.

Exists so existing in-tree imports like `from server.lib.sandbox.storage
import mcp_allow_entry` keep working without churn during the migration.
New code should import directly from `sandbox`.
"""

from __future__ import annotations

from sandbox import storage  # noqa: F401  re-export
from sandbox.models import (  # noqa: F401
    Permissions,
    SandboxFilesystem,
    SettingsFile,
)
from sandbox.storage import (  # noqa: F401
    SETTINGS_PATH,
    allow_entries_for_path,
    mcp_allow_entry,
    skill_allow_entry,
)
```

Then delete the old `storage.py` and `models.py` from `plugins/proj/server/server/lib/sandbox/`:

```bash
rm plugins/proj/server/server/lib/sandbox/storage.py
rm plugins/proj/server/server/lib/sandbox/models.py
```

- [ ] **Step 6: Update `plugins/proj/server/server/tools/sandbox.py` imports**

Find at the top of the file (around line 10-11):

```python
from server.lib.sandbox import storage
from server.lib.sandbox.storage import allow_entries_for_path, mcp_allow_entry, skill_allow_entry
```

Replace with:

```python
from sandbox import storage
from sandbox.storage import allow_entries_for_path, mcp_allow_entry, skill_allow_entry
```

If there are other `from server.lib.sandbox` imports in the file, update them similarly. Do not change function bodies — Task 3 will refactor `sandbox_reconcile` to delegate to the new `reconcile_settings` from `_shared`.

- [ ] **Step 7: Verify imports work end-to-end**

Run:

```bash
uv sync --frozen --extra plugins --group test
```

Expected: succeeds with the bumped `_shared` version. The dev `.venv` rebuilds the path-dep packages.

Then:

```bash
PYTHONPATH=plugins/_shared uv run --no-sync python -c "from sandbox import storage, mcp_allow_entry, SETTINGS_PATH; print('ok:', storage.__file__)"
```

Expected: prints `ok: <path-to-_shared/sandbox/storage.py>`. Verifies the package installs correctly + `__init__.py` exposes the names.

- [ ] **Step 8: Run existing tests to verify back-compat shim works**

Run: `uv run --no-sync pytest plugins/_shared/tests -x`

Expected: green (existing 24 tests still pass — the move doesn't change semantics).

Run: `uv run --no-sync pytest installer/tests --ignore=installer/tests/e2e -x`

Expected: green (no regression in installer suite).

If proj has its own pytest invocation (check `plugins/proj/server/justfile` or root `pyproject.toml` `[tool.pytest.ini_options].testpaths`), run it too. If not, the integration is covered by the in-tree imports being green during install.

- [ ] **Step 9: Commit**

```bash
git add plugins/_shared/sandbox/ plugins/_shared/pyproject.toml \
        plugins/proj/server/server/lib/sandbox/__init__.py \
        plugins/proj/server/server/tools/sandbox.py \
        plugins/_shared/uv.lock plugins/proj/server/uv.lock uv.lock
# Note: deletion of storage.py/models.py is implicit via `git add` of the changed
# directory? Use `git add -A plugins/proj/server/server/lib/sandbox` to capture
# deletions explicitly:
git add -A plugins/proj/server/server/lib/sandbox/
git commit -m "refactor(sandbox): move pure lib from proj plugin to _shared

Pure-Python sandbox library (storage.py, models.py) factored out of
plugins/proj/server/server/lib/sandbox/ into plugins/_shared/sandbox/
so the installer can import it directly without crossing process
boundaries. Proj plugin's lib/sandbox/__init__.py becomes a back-compat
re-export shim — existing in-tree callers untouched.

_shared version bumped to 0.4.30 to trigger per-plugin path-dep cache
invalidation.

Tracking: todo 752, step 1 of 4 (lift-and-shift). Reconcile factoring
is the next task.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

Pre-commit hook may auto-fix formatting; on failure re-stage + commit (don't amend, no `--no-verify`). The `Check _shared version bump` hook should pass because pyproject.toml version field changed.

---

## Task 2: Reconcile-settings unit tests (red)

**Files:**
- Create: `plugins/_shared/tests/test_sandbox_reconcile.py`

Write 5 tests for the `reconcile_settings` function that doesn't exist yet. Tests must FAIL on import (`from sandbox.reconcile import reconcile_settings, ReconcileResult` raises `ModuleNotFoundError`).

- [ ] **Step 1: Create the test file**

```python
"""Unit tests for sandbox.reconcile.reconcile_settings.

The reconciler syncs ~/.claude/settings.json MCP allow rules with an
expected list of MCP server names. Removes stale entries (mcp__*__* rules
not in expected) and adds missing ones. Atomic write — partial state
should never reach disk.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


def _settings_path(tmp_path: Path) -> Path:
    return tmp_path / "settings.json"


def _write_settings(path: Path, allow: list[str]) -> None:
    path.write_text(json.dumps({"permissions": {"allow": allow}}, indent=2))


def _read_allow(path: Path) -> list[str]:
    return list(json.loads(path.read_text())["permissions"]["allow"])


@pytest.fixture()
def isolated_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect SETTINGS_PATH into tmp_path."""
    from sandbox import storage

    target = _settings_path(tmp_path)
    monkeypatch.setattr(storage, "SETTINGS_PATH", target)
    return target


class TestReconcileSettings:
    def test_empty_settings_adds_all_expected(
        self, isolated_settings: Path
    ) -> None:
        from sandbox.reconcile import reconcile_settings

        result = reconcile_settings(
            expected_servers=["plugin_proj_proj", "plugin_wiki_wiki"],
        )

        assert result.added == 2
        assert result.removed == 0
        on_disk = _read_allow(isolated_settings)
        assert "mcp__plugin_proj_proj__*" in on_disk
        assert "mcp__plugin_wiki_wiki__*" in on_disk

    def test_existing_stale_removed(self, isolated_settings: Path) -> None:
        from sandbox.reconcile import reconcile_settings

        _write_settings(
            isolated_settings,
            allow=[
                "mcp__plugin_old__*",
                "mcp__plugin_sandbox_sandbox__*",
                "mcp__plugin_proj_proj__*",
            ],
        )

        result = reconcile_settings(expected_servers=["plugin_proj_proj"])

        assert result.removed == 2
        assert sorted(result.stale_removed) == sorted(
            ["plugin_old", "plugin_sandbox_sandbox"]
        )
        on_disk = _read_allow(isolated_settings)
        assert "mcp__plugin_old__*" not in on_disk
        assert "mcp__plugin_sandbox_sandbox__*" not in on_disk
        assert "mcp__plugin_proj_proj__*" in on_disk

    def test_existing_correct_is_noop(self, isolated_settings: Path) -> None:
        from sandbox.reconcile import reconcile_settings

        _write_settings(
            isolated_settings,
            allow=["mcp__plugin_proj_proj__*", "mcp__plugin_wiki_wiki__*"],
        )

        result = reconcile_settings(
            expected_servers=["plugin_proj_proj", "plugin_wiki_wiki"],
        )

        assert result.added == 0
        assert result.removed == 0
        on_disk = sorted(_read_allow(isolated_settings))
        assert on_disk == sorted(
            ["mcp__plugin_proj_proj__*", "mcp__plugin_wiki_wiki__*"]
        )

    def test_idempotent(self, isolated_settings: Path) -> None:
        from sandbox.reconcile import reconcile_settings

        first = reconcile_settings(expected_servers=["plugin_proj_proj"])
        second = reconcile_settings(expected_servers=["plugin_proj_proj"])

        assert first.added == 1 and first.removed == 0
        assert second.added == 0 and second.removed == 0

    def test_atomic_write_failure_leaves_settings_unchanged(
        self, isolated_settings: Path
    ) -> None:
        """If save() fails mid-write, original settings.json must be intact."""
        from sandbox import storage
        from sandbox.reconcile import reconcile_settings

        _write_settings(
            isolated_settings, allow=["mcp__plugin_proj_proj__*"]
        )
        original = isolated_settings.read_text()

        with patch.object(storage, "save", side_effect=OSError("disk full")):
            with pytest.raises(OSError, match="disk full"):
                reconcile_settings(expected_servers=["plugin_wiki_wiki"])

        assert isolated_settings.read_text() == original
```

- [ ] **Step 2: Run tests to verify they fail (red)**

Run: `uv run --no-sync pytest plugins/_shared/tests/test_sandbox_reconcile.py -v`

Expected: 5 tests FAIL with `ModuleNotFoundError: No module named 'sandbox.reconcile'`. Task 3 lands the module.

- [ ] **Step 3: Commit (red)**

```bash
git add plugins/_shared/tests/test_sandbox_reconcile.py
git commit -m "test(sandbox): pin reconcile_settings behavior (red)

5 tests on the pure reconcile_settings function that doesn't exist
yet: empty→added, stale→removed, no-op idempotent, atomic write
failure preserves original. Tests fail until Task 3 lands the
module.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Implement `reconcile_settings` (green)

**Files:**
- Create: `plugins/_shared/sandbox/reconcile.py`
- Modify: `plugins/_shared/sandbox/__init__.py`
- Modify: `plugins/proj/server/server/tools/sandbox.py` (thin-wrap `sandbox_reconcile`)

- [ ] **Step 1: Create `plugins/_shared/sandbox/reconcile.py`**

```python
"""Pure reconciler for ~/.claude/settings.json MCP allow rules.

Factored out of plugins/proj/server/server/tools/sandbox.py:sandbox_reconcile
so the installer can call it directly without crossing process boundaries.
The MCP tool in proj-server now wraps this function and serializes the
result to JSON for skill consumers.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sandbox import storage
from sandbox.storage import allow_entries_for_path, mcp_allow_entry, skill_allow_entry


PLUGIN_TO_MCP_SERVER: dict[str, str] = {
    "proj": "plugin_proj_proj",
    "router": "plugin_router_router",
    "todoist": "plugin_todoist_todoist",
    "trello": "plugin_trello_trello",
    "jira": "plugin_jira_jira",
    "confluence": "plugin_confluence_confluence",
    "wiki": "plugin_wiki_wiki",
    "worktree": "plugin_worktree_worktree",
}


@dataclass
class ReconcileResult:
    """Outcome of a reconcile_settings call.

    `added` and `removed` are counts. `stale_removed` lists server names
    that were inferred-stale and removed. `paths_added` lists filesystem
    paths added to sandbox.filesystem.allow_write (when expected_paths
    was provided).
    """

    added: int = 0
    removed: int = 0
    stale_removed: list[str] = field(default_factory=list)
    paths_added: list[str] = field(default_factory=list)


def reconcile_settings(
    expected_servers: list[str],
    expected_paths: list[str] | None = None,
    expected_skill_prefixes: list[str] | None = None,
) -> ReconcileResult:
    """Sync expected vs actual MCP servers, paths, and skill prefixes.

    Args:
        expected_servers: list of MCP server names (e.g. `plugin_proj_proj`).
        expected_paths: optional sandbox.filesystem.allow_write paths.
        expected_skill_prefixes: optional skill-allow prefix strings.

    Returns:
        ReconcileResult with counts and diagnostic lists.

    Raises:
        ValueError: malformed server name (rejected by mcp_allow_entry).
        OSError: filesystem failure during save.
    """
    expected_entries = [mcp_allow_entry(name) for name in expected_servers]
    skill_entries = [skill_allow_entry(prefix) for prefix in expected_skill_prefixes or []]

    settings = storage.load()
    result = ReconcileResult()

    # Infer stale: present mcp__*__* rules not in expected_servers.
    current_servers = [
        r.removeprefix("mcp__").removesuffix("__*")
        for r in settings.permissions.allow
        if r.startswith("mcp__") and r.endswith("__*")
    ]
    stale = [s for s in current_servers if s not in expected_servers]

    for name in stale:
        try:
            stale_entry = mcp_allow_entry(name)
        except ValueError:
            continue
        if stale_entry in settings.permissions.allow:
            settings.permissions.allow.remove(stale_entry)
            result.removed += 1
            result.stale_removed.append(name)

    # Add missing servers.
    for entry in expected_entries:
        if entry not in settings.permissions.allow:
            settings.permissions.allow.append(entry)
            result.added += 1

    # Reconcile paths if provided.
    if expected_paths is not None:
        for p in expected_paths:
            abs_path = p  # caller is expected to pass absolute paths
            if abs_path not in settings.sandbox.filesystem.allow_write:
                settings.sandbox.filesystem.allow_write.append(abs_path)
                result.added += 1
                result.paths_added.append(abs_path)
            for entry in allow_entries_for_path(abs_path):
                if entry not in settings.permissions.allow:
                    settings.permissions.allow.append(entry)
                    result.added += 1

    # Reconcile skill prefixes if provided.
    if expected_skill_prefixes is not None:
        for entry in skill_entries:
            if entry not in settings.permissions.allow:
                settings.permissions.allow.append(entry)
                result.added += 1

    storage.save(settings)
    return result
```

- [ ] **Step 2: Update `plugins/_shared/sandbox/__init__.py`**

Add `reconcile_settings`, `ReconcileResult`, `PLUGIN_TO_MCP_SERVER` to the imports + `__all__`:

```python
"""Sandbox library shared between installer and proj plugin.

Pure-Python lib for reading/writing ~/.claude/settings.json. Owns the
allow-rule semantics for MCP servers, sandbox paths, and skill prefixes.
The proj plugin's tools/sandbox.py wraps these primitives in MCP tools;
the installer calls reconcile_settings directly during install finalize.
"""

from __future__ import annotations

from sandbox import storage
from sandbox.models import (
    Permissions,
    SandboxFilesystem,
    SettingsFile,
)
from sandbox.reconcile import (
    PLUGIN_TO_MCP_SERVER,
    ReconcileResult,
    reconcile_settings,
)
from sandbox.storage import (
    SETTINGS_PATH,
    allow_entries_for_path,
    mcp_allow_entry,
    skill_allow_entry,
)

__all__ = [
    "PLUGIN_TO_MCP_SERVER",
    "Permissions",
    "ReconcileResult",
    "SETTINGS_PATH",
    "SandboxFilesystem",
    "SettingsFile",
    "allow_entries_for_path",
    "mcp_allow_entry",
    "reconcile_settings",
    "skill_allow_entry",
    "storage",
]
```

- [ ] **Step 3: Update `plugins/proj/server/server/tools/sandbox.py:sandbox_reconcile` to wrap the new function**

Find the existing `sandbox_reconcile` function (around line 321). Replace its body with a thin wrapper that delegates to `reconcile_settings` and serializes the result to the existing JSON envelope.

The current function body (the validate-load-mutate-save logic) is now inside `_shared`. Replace it with:

```python
def sandbox_reconcile(
    expected_servers: list[str],
    expected_paths: list[str] | None = None,
    stale_servers: list[str] | None = None,
    expected_skill_prefixes: list[str] | None = None,
) -> str:
    """Sync expected vs actual MCP servers, paths, and skill prefixes.

    MCP tool wrapping `sandbox.reconcile_settings`. Skill consumers
    receive the JSON envelope; programmatic in-tree callers should
    import `reconcile_settings` directly from `sandbox`.

    Note: the legacy `stale_servers` arg is accepted for back-compat but
    ignored — the new reconciler always infers stale from current state.
    """
    from sandbox.reconcile import reconcile_settings

    try:
        result = reconcile_settings(
            expected_servers=expected_servers,
            expected_paths=expected_paths,
            expected_skill_prefixes=expected_skill_prefixes,
        )
    except ValueError as exc:
        return _json_result(error=str(exc))

    return _json_result(
        added=result.added,
        removed=result.removed,
        stale_removed=result.stale_removed,
    )
```

If `_json_result` already accepts those keyword args, no change. Otherwise check its signature and adapt this wrapper to match what it accepts (likely `**kwargs` or the explicit fields it uses today).

- [ ] **Step 4: Run reconcile tests**

Run: `uv run --no-sync pytest plugins/_shared/tests/test_sandbox_reconcile.py -v`

Expected: 5 tests pass.

Run: `uv run --no-sync pytest plugins/_shared/tests -v`

Expected: 29 green (24 existing + 5 new).

- [ ] **Step 5: Run proj sandbox tool tests if present**

Search for tests on `tools/sandbox.py`:

```bash
find /home/raul/projects/claude-project-manager -path '*/proj*' -name 'test*sandbox*.py' 2>/dev/null
```

If any test files exist, run them: `uv run --no-sync pytest <file> -v` for each. Expected: green (the wrapper preserves the JSON envelope shape).

If a test breaks because it expected a specific JSON envelope key that we didn't preserve, edit the wrapper's `_json_result(...)` call to include that key. Document any test edits in this step's commit.

- [ ] **Step 6: Commit (green)**

```bash
git add plugins/_shared/sandbox/reconcile.py \
        plugins/_shared/sandbox/__init__.py \
        plugins/proj/server/server/tools/sandbox.py
# If proj test files were edited:
# git add plugins/proj/...test_files...
git commit -m "feat(sandbox): factor reconcile_settings into _shared

Pure reconcile_settings(expected_servers, …) returning ReconcileResult
dataclass. Lives in plugins/_shared/sandbox/reconcile.py alongside
the moved storage + models. PLUGIN_TO_MCP_SERVER static map exposed
for installer consumers.

Proj's MCP tool sandbox_reconcile becomes a thin wrapper that
delegates to the shared function and serializes ReconcileResult to
the existing JSON envelope for skill consumers.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: `_finalize_sandbox` step tests (red)

**Files:**
- Create: `installer/tests/test_finalize_sandbox.py`

Tests for the new install-flow step that doesn't exist yet. Must fail on import.

- [ ] **Step 1: Create the test file**

```python
"""Unit tests for installer.flow.installer_flow._finalize_sandbox.

The step reconciles ~/.claude/settings.json MCP allow rules with the
union of (selected_plugins from this run, get_installed_plugins() from
the cache). Failures are warnings only — install must NOT abort.
"""

from __future__ import annotations

import argparse
from unittest.mock import MagicMock, patch

from rich.console import Console


def _args() -> argparse.Namespace:
    return argparse.Namespace(
        reinstall=False,
        uninstall=False,
        plugins=None,
        skip_wizard=True,
        verbose=False,
        no_tui=True,
        branch=None,
        local_marketplace=False,
    )


class TestFinalizeSandbox:
    def test_calls_reconcile_with_union_of_selected_and_installed(self):
        """selected = ['proj']; installed = ['worktree'] → expected_servers
        contains both plugin_proj_proj AND plugin_worktree_worktree."""
        from installer.flow.installer_flow import _finalize_sandbox

        with (
            patch(
                "installer.flow.installer_flow._name_to_id_map",
                return_value={"worktree": "worktree@cpm"},
            ),
            patch("sandbox.reconcile_settings") as mock_reconcile,
        ):
            mock_reconcile.return_value = MagicMock(
                added=2, removed=0, stale_removed=[]
            )
            console = Console(width=80, force_terminal=False, no_color=True)
            _finalize_sandbox(_args(), ["proj"], console)

        mock_reconcile.assert_called_once()
        call_args = mock_reconcile.call_args
        expected_servers = call_args.kwargs.get(
            "expected_servers"
        ) or call_args.args[0]
        assert "plugin_proj_proj" in expected_servers
        assert "plugin_worktree_worktree" in expected_servers

    def test_unmapped_plugin_warning(self):
        """A plugin name not in PLUGIN_TO_MCP_SERVER → warning printed,
        plugin skipped from expected_servers, install continues."""
        from io import StringIO

        from installer.flow.installer_flow import _finalize_sandbox

        buf = StringIO()
        console = Console(file=buf, width=80, force_terminal=False, no_color=True)

        with (
            patch(
                "installer.flow.installer_flow._name_to_id_map",
                return_value={},
            ),
            patch("sandbox.reconcile_settings") as mock_reconcile,
        ):
            mock_reconcile.return_value = MagicMock(
                added=0, removed=0, stale_removed=[]
            )
            _finalize_sandbox(_args(), ["unknown-plugin"], console)

        assert "unknown-plugin" in buf.getvalue()
        assert "Skipped" in buf.getvalue() or "unmapped" in buf.getvalue()

    def test_oserror_is_yellow_warning_not_abort(self):
        """reconcile_settings raising OSError → yellow warning, no exception."""
        from io import StringIO

        from installer.flow.installer_flow import _finalize_sandbox

        buf = StringIO()
        console = Console(file=buf, width=80, force_terminal=False, no_color=True)

        with (
            patch(
                "installer.flow.installer_flow._name_to_id_map",
                return_value={},
            ),
            patch(
                "sandbox.reconcile_settings",
                side_effect=OSError("disk full"),
            ),
        ):
            # Must not raise — failures are warnings only.
            _finalize_sandbox(_args(), ["proj"], console)

        assert "Failed to reconcile" in buf.getvalue() or "disk full" in buf.getvalue()

    def test_counter_message_shows_added_and_removed(self):
        """Non-zero added/removed counts → green ✓ message with counts."""
        from io import StringIO

        from installer.flow.installer_flow import _finalize_sandbox

        buf = StringIO()
        console = Console(file=buf, width=80, force_terminal=False, no_color=True)

        with (
            patch(
                "installer.flow.installer_flow._name_to_id_map",
                return_value={},
            ),
            patch("sandbox.reconcile_settings") as mock_reconcile,
        ):
            mock_reconcile.return_value = MagicMock(
                added=3,
                removed=1,
                stale_removed=["plugin_old_old"],
            )
            _finalize_sandbox(_args(), ["proj"], console)

        out = buf.getvalue()
        assert "added 3" in out
        assert "removed 1" in out
        assert "plugin_old_old" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --no-sync pytest installer/tests/test_finalize_sandbox.py -v`

Expected: 4 tests FAIL with `ImportError: cannot import name '_finalize_sandbox' from 'installer.flow.installer_flow'`. Task 5 lands the helper.

- [ ] **Step 3: Commit (red)**

```bash
git add installer/tests/test_finalize_sandbox.py
git commit -m "test(installer/flow): pin _finalize_sandbox behavior (red)

4 tests on the install-flow sandbox step that doesn't exist yet:
union of selected+installed plugin names → expected_servers,
unmapped plugin warning, OSError as yellow warning (no abort),
counter message format.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Implement `_finalize_sandbox` + wire into TUI flow (green)

**Files:**
- Modify: `installer/flow/installer_flow.py`

- [ ] **Step 1: Add `_finalize_sandbox` helper near the top of `installer/flow/installer_flow.py`**

Insert immediately after the existing `_kill_then_finalize` helper (around line 56-66). The full helper:

```python
def _finalize_sandbox(
    args: Any, selected_plugins: list[str], console: Console
) -> None:
    """Reconcile ~/.claude/settings.json MCP allow rules.

    Runs AFTER plugin install + kill_stale, BEFORE shared venv build.
    Failures are warnings only — start.sh + plugin runtime degrade
    gracefully without sandbox rules (Claude prompts per-tool
    permissions instead of auto-allow).

    The expected-set is the union of:
    - selected_plugins from this install's wizard selection.
    - get_installed_plugins() parsed names (covers plugins from prior
      installs the user didn't touch this run).

    Stale inference still removes entries for plugins NOT installed
    at all.
    """
    from sandbox import PLUGIN_TO_MCP_SERVER, reconcile_settings

    name_to_id = _name_to_id_map()
    union = set(selected_plugins) | set(name_to_id.keys())

    expected_servers: list[str] = []
    skipped: list[str] = []
    for plugin_name in sorted(union):
        server = PLUGIN_TO_MCP_SERVER.get(plugin_name)
        if server is None:
            skipped.append(plugin_name)
            continue
        expected_servers.append(server)

    if skipped:
        console.print(
            f"[dim]Skipped sandbox reconcile for unmapped plugins: "
            f"{', '.join(skipped)}[/dim]"
        )

    try:
        result = reconcile_settings(expected_servers=expected_servers)
    except (OSError, ValueError) as exc:
        console.print(
            f"[yellow]Failed to reconcile settings.json sandbox rules: "
            f"{exc}[/yellow]"
        )
        return

    if result.added or result.removed:
        msg_parts: list[str] = []
        if result.added:
            msg_parts.append(f"added {result.added}")
        if result.removed:
            stale = ", ".join(result.stale_removed)
            msg_parts.append(f"removed {result.removed} stale ({stale})")
        console.print(
            f"  [green]✓[/green] Sandbox rules reconciled: "
            f"{', '.join(msg_parts)}"
        )
    else:
        console.print("  [dim]✓ Sandbox rules already in sync[/dim]")
```

- [ ] **Step 2: Wire into `_run_install`**

Find `_run_install` (around line 484-498). Locate the call to `_kill_then_finalize`:

```python
    if exit_code == 0:
        _kill_then_finalize(args, console)
    return exit_code
```

Replace with:

```python
    if exit_code == 0:
        prompt_kill_stale_sessions(console)
        _finalize_sandbox(args, selected_names, console)
        _finalize_shared_venv(args, console)
    return exit_code
```

Where `selected_names` is already in scope (from `_select_plugin_actions(...)` earlier in the function — verify by reading lines 360-410). If `selected_names` is computed differently, adapt to use the appropriate local variable holding the list of plugin names being installed.

This expands the `_kill_then_finalize` helper inline so we can insert `_finalize_sandbox` between kill and finalize. Alternative: rename `_kill_then_finalize` to `_kill_then_sandbox_then_finalize` and have it accept `selected_plugins` — but inlining is clearer here because sandbox needs the plugin list and venv finalize doesn't.

- [ ] **Step 3: Wire into `_run_reinstall`**

Find `_run_reinstall` (around line 568-584). Locate the same `_kill_then_finalize(args, console)` call:

```python
    if exit_code == 0:
        _kill_then_finalize(args, console)
```

Replace with:

```python
    if exit_code == 0:
        prompt_kill_stale_sessions(console)
        _finalize_sandbox(args, installed_names, console)
        _finalize_shared_venv(args, console)
```

Where `installed_names` is already in scope (from `pre_state.installed_plugins` earlier in the function — verify lines 536-540).

- [ ] **Step 4: Wire into `_run_update`**

Find `_run_update` (around line 524-526). Same replacement:

```python
    if exit_code == 0:
        _kill_then_finalize(args, console)
```

Replace with:

```python
    if exit_code == 0:
        prompt_kill_stale_sessions(console)
        _finalize_sandbox(args, selected, console)
        _finalize_shared_venv(args, console)
```

Where `selected` is already in scope (from `select_updates(diffs, console)` at line 506).

- [ ] **Step 5: Run tests**

Run: `uv run --no-sync pytest installer/tests/test_finalize_sandbox.py -v`

Expected: 4 tests pass.

Run: `uv run --no-sync pytest installer/tests/flow/test_installer_flow.py -v`

Expected: existing tests still green. The `TestKillStaleOrdering` tests may fail because the order changed from `_kill_then_finalize` (single call) to three separate calls. The ordering helper checks `prompt_kill_stale_sessions < _finalize_shared_venv` — that still holds. If `_kill_then_finalize` was patched in the test, the test now sees the inline calls instead. Task 7 extends the ordering tests to assert `kill < sandbox < finalize`; if `TestKillStaleOrdering` fails NOW because of patching mismatch, document it and fix in Task 7.

Run: `uv run --no-sync pytest installer/tests --ignore=installer/tests/e2e -x`

Expected: green except possibly the kill-stale ordering tests in flow/test_installer_flow.py (which Task 7 fixes). If anything else fails, address before commit.

- [ ] **Step 6: Commit (green)**

```bash
git add installer/flow/installer_flow.py
git commit -m "feat(installer/flow): _finalize_sandbox step wires reconcile

New _finalize_sandbox helper in installer/flow/installer_flow.py
calls sandbox.reconcile_settings with the union of selected_plugins
(this run) and get_installed_plugins() (prior installs). Wired into
_run_install, _run_reinstall, _run_update between kill_stale and
venv finalize.

Failures are yellow warnings — install does not abort. Plugins not
in PLUGIN_TO_MCP_SERVER are logged + skipped, not failed.

Tracking: todo 752, step 3 of 4 (TUI wiring). --no-tui paths land
in the next task.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Wire `_finalize_sandbox` into `--no-tui` paths

**Files:**
- Modify: `installer/main.py`

- [ ] **Step 1: Wire into `_install`**

Find `_install` in `installer/main.py` (around line 74). Look for the existing `prompt_kill_stale_sessions(console)` call (around line 165 after P2's e4fee71 / 7aabf43 commits). Insert `_finalize_sandbox` between kill and the wizard call:

Current:

```python
    # 5. Kill stale Claude Code sessions BEFORE shared-venv rebuild so old
    # MCP processes release file descriptors to the old venv.
    from installer.flow.kill_stale import prompt_kill_stale_sessions

    prompt_kill_stale_sessions(console)

    # 6. Run setup wizard now that plugins are installed and marketplace
    # dir exists (so wizard can create the shared venv).
    run_wizard(selected, skip=args.skip_wizard, args=args)
```

Replace with:

```python
    # 5. Kill stale Claude Code sessions BEFORE shared-venv rebuild so old
    # MCP processes release file descriptors to the old venv.
    from installer.flow.kill_stale import prompt_kill_stale_sessions

    prompt_kill_stale_sessions(console)

    # 6. Reconcile ~/.claude/settings.json MCP allow rules with selected
    # plugins. Runs before the wizard (which builds the shared venv).
    from installer.flow.installer_flow import _finalize_sandbox

    _finalize_sandbox(args, selected, console)

    # 7. Run setup wizard now that plugins are installed and marketplace
    # dir exists (so wizard can create the shared venv).
    run_wizard(selected, skip=args.skip_wizard, args=args)
```

The variable `selected` is already in scope (built at the top of `_install` from `args.plugins` or `select_plugins(...)`).

Note: the existing comment block was renumbered to 6 in P2's earlier commit (43a14a4). The new comment block becomes 6, the wizard becomes 7, and any later `# 7. Summary` comment must move to `# 8. Summary`. Find the existing `# 7. Summary` (or whatever number it now has) and bump it to `# 8.`.

- [ ] **Step 2: Wire into `_reinstall`**

Find `_reinstall` (around line 207). Look for the existing `prompt_kill_stale_sessions(console)` call:

```python
    # Kill stale Claude Code sessions BEFORE shared-venv rebuild so old
    # MCP processes release file descriptors to the old venv.
    from installer.flow.kill_stale import prompt_kill_stale_sessions

    prompt_kill_stale_sessions(console)

    # Run wizard after reinstall if configs were reset
    if not args.skip_wizard:
        run_wizard(plugins, skip=False, args=args)
```

Replace with:

```python
    # Kill stale Claude Code sessions BEFORE shared-venv rebuild so old
    # MCP processes release file descriptors to the old venv.
    from installer.flow.kill_stale import prompt_kill_stale_sessions

    prompt_kill_stale_sessions(console)

    # Reconcile ~/.claude/settings.json MCP allow rules with selected
    # plugins.
    from installer.flow.installer_flow import _finalize_sandbox

    _finalize_sandbox(args, plugins, console)

    # Run wizard after reinstall if configs were reset
    if not args.skip_wizard:
        run_wizard(plugins, skip=False, args=args)
```

The variable `plugins` is already in scope (from `plugins = list(installed)` in `_reinstall`).

- [ ] **Step 3: Run tests**

Run: `uv run --no-sync pytest installer/tests/test_main.py -v`

Expected: existing tests pass; the 3 ordering tests added in P2 (`test_install_skip_wizard_kills_before_ensure_shared_venv`, `test_reinstall_skip_wizard_kills_before_ensure_shared_venv`, `test_install_wizard_path_kills_before_run_wizard`) still pass — they assert kill < {wizard, ensure_shared_venv}, which is still true. The new sandbox call is between kill and venv but doesn't break those assertions.

Run: `uv run --no-sync pytest installer/tests --ignore=installer/tests/e2e -x`

Expected: green.

- [ ] **Step 4: Commit**

```bash
git add installer/main.py
git commit -m "feat(installer/main): wire _finalize_sandbox into --no-tui paths

installer/main.py:_install and _reinstall now call _finalize_sandbox
between prompt_kill_stale_sessions and the wizard / belt-and-
suspenders ensure_shared_venv block. Settings.json gets reconciled
before the heavy venv rebuild so even if venv build fails the user
already has correct sandbox rules.

Tracking: todo 752, step 4 of 4 (--no-tui wiring). The TUI flow
landed in the previous commit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Extend ordering tests for kill < sandbox < venv

**Files:**
- Modify: `installer/tests/flow/test_installer_flow.py::TestKillStaleOrdering`
- Modify: `installer/tests/test_main.py` (add 3 ordering tests)

The existing P2 ordering tests assert `prompt_kill_stale < _finalize_shared_venv`. With Task 5/6, the new helper `_finalize_sandbox` runs between them. The existing tests should still pass (the kill < finalize relationship still holds), but we add new assertions: `kill < sandbox` AND `sandbox < finalize`.

- [ ] **Step 1: Update `_assert_kill_before_finalize` helper in `TestKillStaleOrdering` to also assert sandbox ordering**

Open `installer/tests/flow/test_installer_flow.py`. Find `_assert_kill_before_finalize` inside the `TestKillStaleOrdering` class (around line 307). Replace with:

```python
    def _assert_ordering(self, parent_mock):
        """Verify prompt_kill_stale_sessions < _finalize_sandbox <
        _finalize_shared_venv on the shared parent mock."""
        names = [c[0] for c in parent_mock.mock_calls]
        try:
            kill_idx = names.index("prompt_kill_stale_sessions")
            sandbox_idx = names.index("_finalize_sandbox")
            finalize_idx = names.index("_finalize_shared_venv")
        except ValueError as exc:
            raise AssertionError(
                f"Expected all three calls; got names={names}"
            ) from exc
        assert kill_idx < sandbox_idx < finalize_idx, (
            f"Expected kill (#{kill_idx}) < sandbox (#{sandbox_idx}) < "
            f"finalize (#{finalize_idx}); calls={names}"
        )

    def _assert_kill_before_finalize(self, parent_mock):
        """Back-compat alias — call _assert_ordering."""
        self._assert_ordering(parent_mock)
```

(The alias keeps existing test methods using the old name working.)

- [ ] **Step 2: Update each of the 3 ordering tests in `TestKillStaleOrdering` to patch `_finalize_sandbox` too**

For `test_run_install_kills_before_finalize`, `test_run_reinstall_kills_before_finalize`, `test_run_update_kills_before_finalize`: each currently patches `prompt_kill_stale_sessions` and `_finalize_shared_venv` onto the parent. Add a third patch for `_finalize_sandbox`:

In each test's `with` block, add:

```python
            patch(
                "installer.flow.installer_flow._finalize_sandbox",
                parent._finalize_sandbox,
            ),
```

After the `_finalize_shared_venv` patch line. The helper `_assert_ordering` then verifies the three-way order.

- [ ] **Step 3: Run TUI ordering tests**

Run: `uv run --no-sync pytest installer/tests/flow/test_installer_flow.py::TestKillStaleOrdering -v`

Expected: 3 tests pass.

- [ ] **Step 4: Add 3 ordering tests to `installer/tests/test_main.py`**

Inside `class TestInstall:` (around line 95), add at the end:

```python
    @patch("installer.main.run_wizard")
    @patch("installer.main.install_plugin")
    @patch("installer.main.get_installed_plugins", return_value=[])
    @patch("installer.main.get_available_plugins", return_value=["proj@gh:x/y"])
    @patch("installer.main.check_marketplace_registered", return_value=True)
    def test_install_wizard_path_sandbox_between_kill_and_wizard(
        self,
        _check_mp,
        _avail,
        _installed,
        _install_plugin,
        _wizard,
    ):
        """--no-tui non-skip-wizard install: kill < sandbox < run_wizard."""
        from unittest.mock import MagicMock as _MagicMock

        parent = _MagicMock()
        parent.run_wizard = _wizard
        with (
            patch(
                "installer.flow.kill_stale.prompt_kill_stale_sessions",
                parent.prompt_kill_stale_sessions,
            ),
            patch(
                "installer.flow.installer_flow._finalize_sandbox",
                parent._finalize_sandbox,
            ),
        ):
            args = _make_args(plugins=["proj"], skip_wizard=False)
            _install(args)
        names = [c[0] for c in parent.mock_calls]
        kill_idx = names.index("prompt_kill_stale_sessions")
        sandbox_idx = names.index("_finalize_sandbox")
        wizard_idx = names.index("run_wizard")
        assert kill_idx < sandbox_idx < wizard_idx, (
            f"Expected kill < sandbox < run_wizard; got {names}"
        )

    @patch("installer.shared_venv.ensure_shared_venv")
    @patch("installer.main.install_plugin")
    @patch("installer.main.get_installed_plugins", return_value=[])
    @patch("installer.main.get_available_plugins", return_value=["proj@gh:x/y"])
    @patch("installer.main.check_marketplace_registered", return_value=True)
    @patch("installer.main.run_wizard")
    def test_install_skip_wizard_sandbox_between_kill_and_ensure(
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
        """--no-tui --skip-wizard install: kill < sandbox < ensure_shared_venv."""
        from unittest.mock import MagicMock as _MagicMock

        target = tmp_path / "mp"
        target.mkdir()
        monkeypatch.setattr("installer.shared_venv.marketplaces_dir", lambda: target)

        parent = _MagicMock()
        parent.ensure_shared_venv = mock_ensure
        with (
            patch(
                "installer.flow.kill_stale.prompt_kill_stale_sessions",
                parent.prompt_kill_stale_sessions,
            ),
            patch(
                "installer.flow.installer_flow._finalize_sandbox",
                parent._finalize_sandbox,
            ),
        ):
            args = _make_args(plugins=["proj"], skip_wizard=True)
            _install(args)
        names = [c[0] for c in parent.mock_calls]
        kill_idx = names.index("prompt_kill_stale_sessions")
        sandbox_idx = names.index("_finalize_sandbox")
        ensure_idx = names.index("ensure_shared_venv")
        assert kill_idx < sandbox_idx < ensure_idx, (
            f"Expected kill < sandbox < ensure; got {names}"
        )
```

Inside `class TestReinstallSharedVenv:` (around line 624), add:

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
    def test_reinstall_skip_wizard_sandbox_between_kill_and_ensure(
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
        """--no-tui --skip-wizard reinstall: kill < sandbox < ensure."""
        from unittest.mock import MagicMock as _MagicMock

        target = tmp_path / "mp"
        target.mkdir()
        monkeypatch.setattr("installer.shared_venv.marketplaces_dir", lambda: target)
        mock_detect.return_value = InstallState(installed_plugins=["proj"])

        parent = _MagicMock()
        parent.ensure_shared_venv = mock_ensure
        with (
            patch(
                "installer.flow.kill_stale.prompt_kill_stale_sessions",
                parent.prompt_kill_stale_sessions,
            ),
            patch(
                "installer.flow.installer_flow._finalize_sandbox",
                parent._finalize_sandbox,
            ),
        ):
            args = _make_args(reinstall=True, skip_wizard=True)
            _reinstall(args)
        names = [c[0] for c in parent.mock_calls]
        kill_idx = names.index("prompt_kill_stale_sessions")
        sandbox_idx = names.index("_finalize_sandbox")
        ensure_idx = names.index("ensure_shared_venv")
        assert kill_idx < sandbox_idx < ensure_idx, (
            f"Expected kill < sandbox < ensure; got {names}"
        )
```

- [ ] **Step 5: Run --no-tui ordering tests**

Run: `uv run --no-sync pytest installer/tests/test_main.py -v -k "sandbox_between"`

Expected: 3 tests pass.

- [ ] **Step 6: Commit**

```bash
git add installer/tests/flow/test_installer_flow.py installer/tests/test_main.py
git commit -m "test(install-flow): assert kill < sandbox < venv ordering

Extend TestKillStaleOrdering helper to verify the three-way
ordering: prompt_kill_stale_sessions < _finalize_sandbox <
_finalize_shared_venv. Add 3 --no-tui ordering tests in
test_main.py for the same property in installer/main.py
:_install (wizard + skip-wizard paths) and :_reinstall
(skip-wizard path).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: SKILL.md cleanup (sed)

**Files:**
- Modify: `plugins/proj/skills/sandbox/SKILL.md` (16 hits)
- Modify: `plugins/proj/skills/init-plugin/SKILL.md` (7 hits)
- Modify: `plugins/proj/evals/init-plugin.md` (4 hits)
- Modify: `plugins/worktree/skills/create/SKILL.md` (2 hits)

Replace stale tool references `mcp__plugin_sandbox_sandbox__*` with `mcp__plugin_proj_proj__sandbox_*`.

- [ ] **Step 1: Verify the sed pattern matches all 29 hits cleanly**

Run:

```bash
grep -nE 'mcp__plugin_sandbox_sandbox__|mcp__sandbox_sandbox__' \
  plugins/proj/skills/sandbox/SKILL.md \
  plugins/proj/skills/init-plugin/SKILL.md \
  plugins/proj/evals/init-plugin.md \
  plugins/worktree/skills/create/SKILL.md
```

Expected: ~29 lines printed. Capture the patterns: most should be `mcp__plugin_sandbox_sandbox__` (the namespaced form). If any are `mcp__sandbox_sandbox__` (unnamespaced), they need a different replacement.

- [ ] **Step 2: Apply replacements**

Two patterns to replace:

```bash
sed -i 's/mcp__plugin_sandbox_sandbox__/mcp__plugin_proj_proj__sandbox_/g' \
  plugins/proj/skills/sandbox/SKILL.md \
  plugins/proj/skills/init-plugin/SKILL.md \
  plugins/proj/evals/init-plugin.md \
  plugins/worktree/skills/create/SKILL.md

sed -i 's/mcp__sandbox_sandbox__/mcp__plugin_proj_proj__sandbox_/g' \
  plugins/proj/skills/sandbox/SKILL.md \
  plugins/proj/skills/init-plugin/SKILL.md \
  plugins/proj/evals/init-plugin.md \
  plugins/worktree/skills/create/SKILL.md
```

- [ ] **Step 3: Verify zero remaining stale references**

Run:

```bash
grep -nE 'mcp__plugin_sandbox_sandbox__|mcp__sandbox_sandbox__' \
  plugins/proj/skills/sandbox/SKILL.md \
  plugins/proj/skills/init-plugin/SKILL.md \
  plugins/proj/evals/init-plugin.md \
  plugins/worktree/skills/create/SKILL.md
```

Expected: zero output (no remaining matches).

- [ ] **Step 4: Spot-check the changes**

Run: `git diff plugins/proj/skills/sandbox/SKILL.md | head -60`

Verify each change replaces a stale tool reference with the proj-namespaced form. No surrounding context should be changed.

- [ ] **Step 5: Commit**

```bash
git add plugins/proj/skills/sandbox/SKILL.md \
        plugins/proj/skills/init-plugin/SKILL.md \
        plugins/proj/evals/init-plugin.md \
        plugins/worktree/skills/create/SKILL.md
git commit -m "docs(skills): rename stale mcp__plugin_sandbox_sandbox__* refs

29 sed-replacements across 4 files: mcp__plugin_sandbox_sandbox__* →
mcp__plugin_proj_proj__sandbox_*. The sandbox plugin folded into proj
in commit 0608506; SKILL.md / evals references didn't get updated.

Files: plugins/proj/skills/{sandbox,init-plugin}/SKILL.md (16+7),
plugins/proj/evals/init-plugin.md (4),
plugins/worktree/skills/create/SKILL.md (2).

Tracking: todo 752, step 4 of 4.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Full suite + push

**Files:** none modified.

- [ ] **Step 1: Run fast suite**

Run: `uv run --no-sync pytest installer/tests --ignore=installer/tests/e2e -x`

Expected: all green (existing 744 + 4 new finalize_sandbox + 3 new --no-tui ordering = 751).

- [ ] **Step 2: Run _shared tests**

Run: `uv run --no-sync pytest plugins/_shared/tests -x`

Expected: 29 green (existing 24 + 5 new reconcile).

- [ ] **Step 3: Run slow suite**

Run: `uv run --no-sync pytest installer/tests -m slow --ignore=installer/tests/e2e -x`

Expected: 9 green (cross-plugin integration test still works).

- [ ] **Step 4: Push**

```bash
git push origin dev
```

Expected: 8 new commits (1 spec + 1 plan + 6 impl). Watch CI:

```bash
gh run list --branch dev --limit 1
```

---

## Self-Review

**Spec coverage**

| Spec section | Task |
|---|---|
| Factor sandbox lib to `_shared` (storage, models) | Task 1 |
| `reconcile_settings` pure function w/ `ReconcileResult` | Tasks 2, 3 |
| `PLUGIN_TO_MCP_SERVER` static map | Task 3 |
| Back-compat shim in `proj/lib/sandbox/__init__.py` | Task 1 Step 5 |
| Proj's `tools/sandbox.py:sandbox_reconcile` thin wrapper | Task 3 Step 3 |
| `_finalize_sandbox` step in TUI flow | Tasks 4, 5 |
| `_finalize_sandbox` in `--no-tui` paths | Task 6 |
| Ordering: kill < sandbox < venv | Task 7 |
| SKILL.md sed cleanup | Task 8 |
| `_shared` version bump 0.4.29 → 0.4.30 | Task 1 Step 4 |
| Verification (full suite + manual) | Task 9 + spec's manual section |

No gaps.

**Placeholder scan**

No "TBD" / "TODO" / "Add appropriate" / "Similar to Task N" / "..." patterns. Every step has exact code or exact command + expected output. Task 5 references "verify by reading lines 360-410" / "verify lines 536-540" — those are specific line ranges to inspect, not placeholders.

**Type/name consistency**

- `reconcile_settings(expected_servers, expected_paths=None, expected_skill_prefixes=None) -> ReconcileResult` — same signature in Tasks 2 (test), 3 (impl), and 5 (called from `_finalize_sandbox`).
- `ReconcileResult.added`, `.removed`, `.stale_removed`, `.paths_added` — same field names across all tests and impl.
- `PLUGIN_TO_MCP_SERVER` keys: 8 lowercase plugin names; values: `plugin_<name>_<name>` form. Used identically in spec, Task 3 impl, Task 4 tests, Task 5 helper.
- `_finalize_sandbox(args, selected_plugins, console)` — same signature in Tasks 4 (test), 5 (impl + 3 call sites in TUI flow), 6 (2 call sites in `--no-tui` flow), 7 (3 ordering tests patch this name).

Plan is executable as-is.
