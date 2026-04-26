# Plugin Cache Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate cascading hook-registration failures by pruning stale plugin caches in the installer and teaching the router to pick only the highest-versioned plugin per name + remove orphaned hooks on sync.

**Architecture:** Three layers changing in parallel.
1. Installer: extend `installer/cleanup.py` with stale-version + orphan detection; wire into both CLI (`main.py`) and TUI (`app.py`) reinstall flows.
2. Router discovery: fix `_plugin_name_from_path` (cache layout name bug), add highest-semver version selection + optional `active_plugins` filter to `find_default_hooks_files`.
3. Router sync: remove orphaned `source: auto` hooks in `discover_and_register` when their `(trigger, target, server)` key disappears from discovery.

**Tech Stack:** Python 3.12+, pytest, `packaging.version.Version`, `pathlib`, `shutil` for directory removal.

**Spec:** `docs/superpowers/specs/2026-04-16-plugin-cache-management-design.md`

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `installer/cleanup.py` | Extend | Add `scan_stale_cache`, `prune_stale_versions`, `prune_orphaned_plugins` |
| `installer/main.py` | Modify | Call pruning from `_reinstall` CLI flow with Rich prompt |
| `installer/app.py` | Modify | Call pruning from `_prepare_and_reinstall` TUI flow with ConfirmScreen |
| `installer/tests/test_cleanup.py` | Extend | Tests for new scan/prune functions |
| `installer/tests/test_main.py` | Extend | `_reinstall` integrates cleanup |
| `installer/tests/test_app.py` | Extend | `_prepare_and_reinstall` integrates cleanup |
| `plugins/router/server/server/lib/discovery.py` | Modify | Fix path parser + version selection + orphan-auto-hook removal |
| `plugins/router/server/server/tools/sync.py` | Modify | Accept + forward `active_plugins` if user provides it |
| `plugins/router/server/server/main.py` | Modify | Resolve `active_plugins` from marketplace.json on startup |
| `plugins/router/server/tests/test_discovery.py` | Extend | Tests for new behavior |
| `plugins/router/server/tests/test_orphan_cleanup.py` | Create | New test file for orphan-auto-hook removal |

---

## Task 1: Semver helper and path parser fix (router)

Fix the `_plugin_name_from_path` bug that returns the version string as the plugin name in cache layout, and add a helper for parsing the version segment.

**Files:**
- Modify: `plugins/router/server/server/lib/discovery.py:147-153`
- Modify: `plugins/router/server/pyproject.toml` (add `packaging` dep if missing)
- Test: `plugins/router/server/tests/test_discovery.py`

- [ ] **Step 1: Check if packaging is already a dep**

```bash
grep -E "packaging" /home/raul/projects/claude-project-manager/plugins/router/server/pyproject.toml
```
Expected: shows `packaging` in dependencies. If not, add `"packaging>=24.0"` to `dependencies` array in pyproject.toml. (It's stdlib-adjacent and usually bundled with setuptools.)

- [ ] **Step 2: Write failing tests for path parsing**

Add to `plugins/router/server/tests/test_discovery.py`:

```python
from pathlib import Path

from server.lib.discovery import _is_version_string, _path_version, _plugin_name_from_path


class TestIsVersionString:
    def test_semver(self):
        assert _is_version_string("5.0.0")
        assert _is_version_string("3.0.1")

    def test_pre_release(self):
        assert _is_version_string("1.0.0rc1")

    def test_not_version(self):
        assert not _is_version_string("proj")
        assert not _is_version_string("92f892f2b997")


class TestPluginNameFromPath:
    def test_dev_layout(self):
        path = Path("/repo/plugins/proj/.claude-plugin/default-hooks.yaml")
        assert _plugin_name_from_path(path) == "proj"

    def test_cache_layout_semver(self):
        path = Path("/home/u/.claude/plugins/cache/cpm/proj/5.0.0/.claude-plugin/default-hooks.yaml")
        assert _plugin_name_from_path(path) == "proj"

    def test_cache_layout_version_with_pre_release(self):
        path = Path("/cache/worktree/2.6.0rc1/.claude-plugin/default-hooks.yaml")
        assert _plugin_name_from_path(path) == "worktree"


class TestPathVersion:
    def test_cache_layout_returns_version(self):
        from packaging.version import Version

        path = Path("/cache/proj/5.0.0/.claude-plugin/default-hooks.yaml")
        assert _path_version(path) == Version("5.0.0")

    def test_dev_layout_returns_none(self):
        path = Path("/repo/plugins/proj/.claude-plugin/default-hooks.yaml")
        assert _path_version(path) is None

    def test_unparseable_returns_none(self):
        path = Path("/cache/something/not-a-version/.claude-plugin/default-hooks.yaml")
        assert _path_version(path) is None
```

- [ ] **Step 3: Run tests to verify failure**

```bash
cd /home/raul/projects/claude-project-manager/plugins/router/server
python -m pytest tests/test_discovery.py::TestIsVersionString tests/test_discovery.py::TestPluginNameFromPath tests/test_discovery.py::TestPathVersion -v
```

Expected: all tests FAIL with `ImportError: cannot import name '_is_version_string'` or `AssertionError` for cache_layout_semver returning "5.0.0" instead of "proj".

- [ ] **Step 4: Implement the fixes**

In `plugins/router/server/server/lib/discovery.py`, add imports:

```python
from packaging.version import InvalidVersion, Version
```

Replace `_plugin_name_from_path` (around line 147-153) with:

```python
def _is_version_string(s: str) -> bool:
    """Heuristic: looks like a semver or version-ish token."""
    try:
        Version(s)
        return True
    except InvalidVersion:
        return False


def _path_version(path: Path) -> Version | None:
    """Extract version from path if cache layout, else None (dev layout)."""
    candidate = path.parent.parent.name
    try:
        return Version(candidate)
    except InvalidVersion:
        return None


def _plugin_name_from_path(path: Path) -> str:
    """Extract plugin name from a default-hooks.yaml path.

    Dev layout:   .../plugins/<name>/.claude-plugin/default-hooks.yaml
    Cache layout: .../cache/.../<name>/<version>/.claude-plugin/default-hooks.yaml
    """
    grandparent = path.parent.parent
    if _is_version_string(grandparent.name):
        return grandparent.parent.name
    return grandparent.name
```

- [ ] **Step 5: Run tests to verify pass**

```bash
cd /home/raul/projects/claude-project-manager/plugins/router/server
python -m pytest tests/test_discovery.py -v 2>&1 | tail -30
```

Expected: new tests PASS. Existing discovery tests also PASS (no regression).

- [ ] **Step 6: Commit**

```bash
cd /home/raul/projects/claude-project-manager
git add plugins/router/server/server/lib/discovery.py plugins/router/server/tests/test_discovery.py plugins/router/server/pyproject.toml
git commit -m "fix(router): correct _plugin_name_from_path for cache layout + add version helpers

Cache layout (<name>/<version>/.claude-plugin/...) was treating the version
string as the plugin name. Also add _is_version_string and _path_version
helpers for version-based filtering in find_default_hooks_files.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Version selection in find_default_hooks_files (router)

Make `find_default_hooks_files` return one path per plugin, preferring the highest semver, with an optional `active_plugins` filter.

**Files:**
- Modify: `plugins/router/server/server/lib/discovery.py:81-105` (find_default_hooks_files)
- Test: `plugins/router/server/tests/test_discovery.py`

- [ ] **Step 1: Write failing tests**

Add to `plugins/router/server/tests/test_discovery.py`:

```python
class TestVersionSelection:
    def test_picks_highest_semver_per_plugin(self, tmp_path):
        from server.lib.discovery import find_default_hooks_files

        # Cache layout: <name>/<version>/.claude-plugin/default-hooks.yaml
        for name, version in [("proj", "3.0.1"), ("proj", "5.0.0"), ("worktree", "2.6.0")]:
            d = tmp_path / name / version / ".claude-plugin"
            d.mkdir(parents=True)
            (d / "default-hooks.yaml").write_text("hooks: []\n")

        files = find_default_hooks_files(root=tmp_path, glob_pattern="*/*/.claude-plugin")
        # Should return 2 files: proj/5.0.0 and worktree/2.6.0
        assert len(files) == 2
        paths_str = [str(p) for p in files]
        assert any("proj/5.0.0" in p for p in paths_str)
        assert not any("proj/3.0.1" in p for p in paths_str)

    def test_active_plugins_filters_orphans(self, tmp_path):
        from server.lib.discovery import find_default_hooks_files

        for name in ("proj", "sandbox"):
            d = tmp_path / name / "1.0.0" / ".claude-plugin"
            d.mkdir(parents=True)
            (d / "default-hooks.yaml").write_text("hooks: []\n")

        files = find_default_hooks_files(
            root=tmp_path,
            glob_pattern="*/*/.claude-plugin",
            active_plugins={"proj"},  # sandbox is orphan
        )
        assert len(files) == 1
        assert "proj" in str(files[0])
        assert "sandbox" not in str(files[0])

    def test_none_active_plugins_means_no_filter(self, tmp_path):
        from server.lib.discovery import find_default_hooks_files

        for name in ("proj", "sandbox"):
            d = tmp_path / name / "1.0.0" / ".claude-plugin"
            d.mkdir(parents=True)
            (d / "default-hooks.yaml").write_text("hooks: []\n")

        files = find_default_hooks_files(
            root=tmp_path,
            glob_pattern="*/*/.claude-plugin",
            active_plugins=None,  # no filter
        )
        assert len(files) == 2

    def test_dev_layout_single_file_preserved(self, tmp_path):
        from server.lib.discovery import find_default_hooks_files

        # Dev layout: plugins/<name>/.claude-plugin/default-hooks.yaml
        d = tmp_path / "plugins" / "proj" / ".claude-plugin"
        d.mkdir(parents=True)
        (d / "default-hooks.yaml").write_text("hooks: []\n")

        files = find_default_hooks_files(root=tmp_path)
        assert len(files) == 1
```

- [ ] **Step 2: Run tests to verify failure**

```bash
cd /home/raul/projects/claude-project-manager/plugins/router/server
python -m pytest tests/test_discovery.py::TestVersionSelection -v
```

Expected: `test_picks_highest_semver_per_plugin` FAILS with 3 files returned instead of 2. `test_active_plugins_filters_orphans` FAILS with `TypeError: unexpected keyword argument 'active_plugins'`.

- [ ] **Step 3: Implement the fix**

In `plugins/router/server/server/lib/discovery.py`, replace `find_default_hooks_files` (lines 81-105) with:

```python
def find_default_hooks_files(
    root: Path | None = None,
    glob_pattern: str = _DEFAULT_PLUGIN_GLOB,
    active_plugins: set[str] | None = None,
) -> list[Path]:
    """Find default-hooks.yaml files, one per plugin, preferring highest version.

    Supports two directory layouts:
    - Dev layout:   <project>/plugins/<name>/.claude-plugin/default-hooks.yaml
    - Cache layout: <cache>/<name>/<version>/.claude-plugin/default-hooks.yaml

    When multiple versions of the same plugin exist (cache layout), returns
    only the path with the highest semver version.

    When active_plugins is provided, plugins not in that set are filtered
    out (used to exclude orphaned plugin dirs after a plugin is removed
    from the marketplace).

    Returns a list of Paths, one per plugin.
    """
    discovery_root = root or _default_discovery_root()
    pattern = f"{glob_pattern}/{_DEFAULT_HOOKS_FILENAME}"
    found = sorted(discovery_root.glob(pattern))
    if not found:
        cache_pattern = f"*/*/.claude-plugin/{_DEFAULT_HOOKS_FILENAME}"
        found = sorted(discovery_root.glob(cache_pattern))

    by_plugin: dict[str, list[tuple[Version, Path]]] = {}
    for path in found:
        name = _plugin_name_from_path(path)
        if not name:
            continue
        if active_plugins is not None and name not in active_plugins:
            continue
        version = _path_version(path) or Version("0.0.0")
        by_plugin.setdefault(name, []).append((version, path))

    return [
        max(candidates, key=lambda vp: vp[0])[1]
        for candidates in by_plugin.values()
    ]
```

- [ ] **Step 4: Run tests to verify pass**

```bash
cd /home/raul/projects/claude-project-manager/plugins/router/server
python -m pytest tests/test_discovery.py -v 2>&1 | tail -30
```

Expected: all TestVersionSelection tests PASS. Pre-existing discovery tests also pass (no regression).

- [ ] **Step 5: Commit**

```bash
cd /home/raul/projects/claude-project-manager
git add plugins/router/server/server/lib/discovery.py plugins/router/server/tests/test_discovery.py
git commit -m "feat(router): version selection + active_plugins filter in discovery

find_default_hooks_files now returns one path per plugin (highest semver
when cache holds multiple versions) and supports an optional active_plugins
filter to exclude orphaned plugin dirs.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Plumb active_plugins through run_discovery + callers (router)

Make `run_discovery` and `discover_and_register` accept `active_plugins` and thread it through; resolve it from `marketplace.json` at server startup.

**Files:**
- Modify: `plugins/router/server/server/lib/discovery.py:159-253` (discover_and_register), `:276-340` (run_discovery)
- Modify: `plugins/router/server/server/main.py` (resolve active_plugins)

- [ ] **Step 1: Write failing test for run_discovery signature**

Add to `plugins/router/server/tests/test_discovery.py`:

```python
class TestRunDiscoveryActivePlugins:
    def test_accepts_active_plugins_arg(self, tmp_path, monkeypatch):
        """run_discovery accepts active_plugins kwarg and passes to discover_and_register."""
        from server.lib import storage
        from server.lib.discovery import run_discovery
        from server.lib.models import HookRegistry

        # Arrange: empty registry + in-memory storage
        monkeypatch.setattr(storage, "load", lambda: HookRegistry())
        saved = []
        monkeypatch.setattr(storage, "save", lambda r: saved.append(r))

        # Create cache with one active + one orphan plugin
        for name in ("proj", "sandbox"):
            d = tmp_path / name / "5.0.0" / ".claude-plugin"
            d.mkdir(parents=True)
            (d / "default-hooks.yaml").write_text(
                f"hooks:\n  - trigger_tool: t\n    target_tool: u\n    server: {name}\n"
            )

        summary = run_discovery(
            root=tmp_path,
            glob_pattern="*/*/.claude-plugin",
            active_plugins={"proj"},
        )
        # Only proj should register
        registry = saved[-1] if saved else HookRegistry()
        names = {h.server for h in registry.hooks}
        assert "proj" in names
        assert "sandbox" not in names
```

- [ ] **Step 2: Run test to verify failure**

```bash
cd /home/raul/projects/claude-project-manager/plugins/router/server
python -m pytest tests/test_discovery.py::TestRunDiscoveryActivePlugins -v
```

Expected: FAIL with `TypeError: run_discovery() got an unexpected keyword argument 'active_plugins'`.

- [ ] **Step 3: Update signatures**

In `plugins/router/server/server/lib/discovery.py`, change `discover_and_register` signature (line 159-163) from:
```python
def discover_and_register(
    registry: HookRegistry,
    root: Path | None = None,
    glob_pattern: str = _DEFAULT_PLUGIN_GLOB,
) -> dict[str, dict[str, int]]:
```
to:
```python
def discover_and_register(
    registry: HookRegistry,
    root: Path | None = None,
    glob_pattern: str = _DEFAULT_PLUGIN_GLOB,
    active_plugins: set[str] | None = None,
) -> dict[str, dict[str, int]]:
```

Change the `find_default_hooks_files` call inside (around line 181) from:
```python
files = find_default_hooks_files(root=root, glob_pattern=glob_pattern)
```
to:
```python
files = find_default_hooks_files(
    root=root, glob_pattern=glob_pattern, active_plugins=active_plugins
)
```

Change `run_discovery` signature (line 276-279) from:
```python
def run_discovery(
    root: Path | None = None,
    glob_pattern: str = _DEFAULT_PLUGIN_GLOB,
) -> str:
```
to:
```python
def run_discovery(
    root: Path | None = None,
    glob_pattern: str = _DEFAULT_PLUGIN_GLOB,
    active_plugins: set[str] | None = None,
) -> str:
```

Change the `discover_and_register` call inside (line 297) from:
```python
stats = discover_and_register(registry, root=root, glob_pattern=glob_pattern)
```
to:
```python
stats = discover_and_register(
    registry, root=root, glob_pattern=glob_pattern, active_plugins=active_plugins
)
```

- [ ] **Step 4: Run tests to verify pass**

```bash
cd /home/raul/projects/claude-project-manager/plugins/router/server
python -m pytest tests/test_discovery.py -v 2>&1 | tail -20
```

Expected: TestRunDiscoveryActivePlugins PASS, all existing tests still pass.

- [ ] **Step 5: Resolve active_plugins from marketplace.json in main.py**

Read the current startup code first:
```bash
cat /home/raul/projects/claude-project-manager/plugins/router/server/server/main.py
```

Add a helper function above `main()`:

```python
import json
from pathlib import Path


def _resolve_active_plugins() -> set[str] | None:
    """Load active plugin names from the nearest marketplace.json.

    Returns None if the file cannot be found/parsed (disables orphan filter).
    """
    # Walk up looking for .claude-plugin/marketplace.json
    current = Path(__file__).resolve()
    for _ in range(8):
        current = current.parent
        candidate = current / ".claude-plugin" / "marketplace.json"
        if candidate.is_file():
            try:
                data = json.loads(candidate.read_text())
                plugins = data.get("plugins", [])
                return {p["name"] for p in plugins if isinstance(p, dict) and "name" in p}
            except (json.JSONDecodeError, OSError, KeyError):
                return None
    return None
```

In the `main()` function, change the `run_discovery(...)` calls to pass `active_plugins=_resolve_active_plugins()`. For example if current is:

```python
summary = run_discovery(root=root, glob_pattern=glob_env)
```

change to:

```python
summary = run_discovery(
    root=root, glob_pattern=glob_env, active_plugins=_resolve_active_plugins()
)
```

Apply the same change to every `run_discovery()` call site in `main.py`.

- [ ] **Step 6: Update sync tool forwarding**

Read `plugins/router/server/server/tools/sync.py`. The `hooks_sync` function calls `run_discovery()` with no args. Leave it as-is — sync tool does not need active_plugins because startup already resolved it via main.py.

Verify by re-reading:
```bash
grep -n "run_discovery" /home/raul/projects/claude-project-manager/plugins/router/server/server/tools/sync.py
```

- [ ] **Step 7: Run all router tests**

```bash
cd /home/raul/projects/claude-project-manager/plugins/router/server
python -m pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: all pass, no regressions.

- [ ] **Step 8: Commit**

```bash
cd /home/raul/projects/claude-project-manager
git add plugins/router/server/server/lib/discovery.py plugins/router/server/server/main.py plugins/router/server/tests/test_discovery.py
git commit -m "feat(router): plumb active_plugins from marketplace.json into discovery

run_discovery and discover_and_register now accept active_plugins.
main.py resolves it from the nearest marketplace.json at startup. Orphaned
plugin cache dirs no longer register hooks when marketplace.json is found.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Remove orphaned auto hooks on sync (router)

After `discover_and_register` processes all discovered hooks, any existing `source: auto` hook whose `(trigger, target, server)` triple is not in the discovered set gets removed. Manual hooks are preserved.

**Files:**
- Modify: `plugins/router/server/server/lib/discovery.py::discover_and_register` (around lines 159-253)
- Test: `plugins/router/server/tests/test_orphan_cleanup.py` (new)

- [ ] **Step 1: Write failing tests**

Create `plugins/router/server/tests/test_orphan_cleanup.py`:

```python
"""Tests for orphan auto-hook removal in discover_and_register."""

from __future__ import annotations

from pathlib import Path

import pytest

from server.lib.discovery import discover_and_register
from server.lib.models import Hook, HookRegistry


def _make_default_hooks_file(tmp_path: Path, plugin: str, hooks: list[dict]) -> None:
    """Write a default-hooks.yaml at cache layout for `plugin`."""
    d = tmp_path / plugin / "1.0.0" / ".claude-plugin"
    d.mkdir(parents=True)
    import yaml

    d.joinpath("default-hooks.yaml").write_text(yaml.dump({"hooks": hooks}))


class TestOrphanAutoHookRemoval:
    def test_removes_auto_hook_when_source_file_vanishes(self, tmp_path):
        registry = HookRegistry()
        # Pre-register an auto hook for plugin "sandbox" (which will not appear in discovery)
        registry.hooks.append(
            Hook(
                id="sandbox-on-setup",
                trigger_tool="proj_init",
                target_tool="sandbox_batch_setup",
                server="sandbox",
                param_mapping={},
                blocking=True,
                source="auto",
            )
        )
        # Only proj appears in discovery
        _make_default_hooks_file(
            tmp_path,
            "proj",
            [{"trigger_tool": "todo_add", "target_tool": "tracking_flush", "server": "proj"}],
        )

        discover_and_register(registry, root=tmp_path, glob_pattern="*/*/.claude-plugin")

        # Orphan removed
        ids = [h.id for h in registry.hooks]
        assert "sandbox-on-setup" not in ids
        # New proj hook registered
        assert any(h.server == "proj" for h in registry.hooks)

    def test_preserves_manual_hooks(self, tmp_path):
        registry = HookRegistry()
        # Manual (source != auto) hook — must survive
        registry.hooks.append(
            Hook(
                id="user-custom-hook",
                trigger_tool="todo_complete",
                target_tool="custom_webhook",
                server="external",
                param_mapping={},
                blocking=False,
                source="manual",
            )
        )
        _make_default_hooks_file(
            tmp_path,
            "proj",
            [{"trigger_tool": "todo_add", "target_tool": "tracking_flush", "server": "proj"}],
        )

        discover_and_register(registry, root=tmp_path, glob_pattern="*/*/.claude-plugin")

        ids = [h.id for h in registry.hooks]
        assert "user-custom-hook" in ids

    def test_idempotent_twice(self, tmp_path):
        registry = HookRegistry()
        _make_default_hooks_file(
            tmp_path,
            "proj",
            [{"trigger_tool": "todo_add", "target_tool": "tracking_flush", "server": "proj"}],
        )

        discover_and_register(registry, root=tmp_path, glob_pattern="*/*/.claude-plugin")
        first_state = [(h.id, h.trigger_tool, h.target_tool, h.server) for h in registry.hooks]

        discover_and_register(registry, root=tmp_path, glob_pattern="*/*/.claude-plugin")
        second_state = [(h.id, h.trigger_tool, h.target_tool, h.server) for h in registry.hooks]

        assert first_state == second_state
```

- [ ] **Step 2: Run tests to verify failure**

```bash
cd /home/raul/projects/claude-project-manager/plugins/router/server
python -m pytest tests/test_orphan_cleanup.py -v
```

Expected: `test_removes_auto_hook_when_source_file_vanishes` FAILS — the sandbox-on-setup hook still exists in registry after discover_and_register runs.

- [ ] **Step 3: Implement orphan removal**

In `plugins/router/server/server/lib/discovery.py`, modify `discover_and_register`. Just before the `return stats` line at the end of the function (around line 253), collect discovered keys during the loop and remove orphaned auto hooks.

Add at the start of `discover_and_register` after `stats: dict[...] = {}`:
```python
    discovered_keys: set[tuple[str, str, str]] = set()
```

Inside the inner loop (right after `if not trigger or not target or not server:` check passes), add:
```python
            discovered_keys.add((trigger, target, server))
```

After the outer `for path in files:` loop completes and before `return stats`, add:
```python
    # Remove orphaned source:auto hooks whose source file no longer exists
    orphans_removed = 0
    for hook in list(registry.hooks):
        if hook.source != _AUTO_SOURCE:
            continue
        key = (hook.trigger_tool, hook.target_tool, hook.server)
        if key not in discovered_keys:
            registry.hooks.remove(hook)
            orphans_removed += 1
            logger.info("Removed orphaned auto hook: %s", hook.id)

    if orphans_removed:
        stats["_orphans_removed"] = {"registered": 0, "updated": 0, "orphans_removed": orphans_removed}
```

- [ ] **Step 4: Run tests to verify pass**

```bash
cd /home/raul/projects/claude-project-manager/plugins/router/server
python -m pytest tests/test_orphan_cleanup.py -v
python -m pytest tests/test_discovery.py -v 2>&1 | tail -15
```

Expected: orphan cleanup tests PASS. Existing discovery tests still PASS.

- [ ] **Step 5: Update run_discovery summary to report orphans**

In `plugins/router/server/server/lib/discovery.py::run_discovery`, after computing `total_registered` and `total_updated`, add:
```python
    orphans_removed = stats.get("_orphans_removed", {}).get("orphans_removed", 0)
```

In the summary `lines` assembly (where stats are printed), add a line:
```python
    if orphans_removed:
        lines.append(f"Orphaned auto hooks removed: {orphans_removed}")
```

(Locate the exact insertion point by reading the current summary assembly; place after the per-plugin stat lines and before the trailing totals.)

- [ ] **Step 6: Run all router tests**

```bash
cd /home/raul/projects/claude-project-manager/plugins/router/server
python -m pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
cd /home/raul/projects/claude-project-manager
git add plugins/router/server/server/lib/discovery.py plugins/router/server/tests/test_orphan_cleanup.py
git commit -m "feat(router): remove orphaned source:auto hooks on sync

discover_and_register now tracks discovered (trigger,target,server) keys
and removes any source:auto hook in the registry whose key is no longer
in the discovered set. Manual hooks (source != auto) are preserved.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Installer — scan_stale_cache + prune_stale_versions

Extend `installer/cleanup.py` with functions to classify cache dirs as active/stale-version/orphan and to remove stale version subdirs.

**Files:**
- Modify: `installer/cleanup.py`
- Test: `installer/tests/test_cleanup.py`

- [ ] **Step 1: Write failing tests**

Add to `installer/tests/test_cleanup.py`:

```python
import json
from pathlib import Path

import pytest

from installer.cleanup import (
    PruneReport,
    prune_stale_versions,
    scan_stale_cache,
)


def _write_marketplace(tmp_path: Path, plugin_names: list[str]) -> Path:
    mp = tmp_path / "marketplace.json"
    mp.write_text(
        json.dumps({"plugins": [{"name": n, "version": "5.0.0"} for n in plugin_names]})
    )
    return mp


def _make_cache_dir(tmp_path: Path, plugin: str, version: str) -> Path:
    d = tmp_path / plugin / version
    d.mkdir(parents=True)
    return d


class TestScanStaleCache:
    def test_detects_orphan(self, tmp_path):
        cache = tmp_path / "cache"
        cache.mkdir()
        _make_cache_dir(cache, "sandbox", "1.0.0")  # orphan
        _make_cache_dir(cache, "proj", "5.0.0")
        mp = _write_marketplace(tmp_path, ["proj"])

        report = scan_stale_cache(cache, mp)

        assert report.orphans == ["sandbox"]
        assert report.stale_versions == {}

    def test_detects_stale_versions(self, tmp_path):
        cache = tmp_path / "cache"
        cache.mkdir()
        for v in ("3.0.0", "4.0.0", "5.0.0"):
            _make_cache_dir(cache, "proj", v)
        mp = _write_marketplace(tmp_path, ["proj"])

        report = scan_stale_cache(cache, mp)

        assert report.orphans == []
        assert set(report.stale_versions["proj"]) == {"3.0.0", "4.0.0"}

    def test_ignores_current_version(self, tmp_path):
        cache = tmp_path / "cache"
        cache.mkdir()
        _make_cache_dir(cache, "proj", "5.0.0")  # only the current
        mp = _write_marketplace(tmp_path, ["proj"])

        report = scan_stale_cache(cache, mp)

        assert report.orphans == []
        assert report.stale_versions == {}

    def test_unparseable_version_skipped(self, tmp_path):
        cache = tmp_path / "cache"
        cache.mkdir()
        _make_cache_dir(cache, "proj", "92f892f2b997")  # hash, not semver
        _make_cache_dir(cache, "proj", "5.0.0")
        mp = _write_marketplace(tmp_path, ["proj"])

        report = scan_stale_cache(cache, mp)

        # Unparseable version is not treated as stale; not in stale_versions
        assert "proj" not in report.stale_versions or "92f892f2b997" not in report.stale_versions.get("proj", [])

    def test_missing_marketplace_json(self, tmp_path):
        cache = tmp_path / "cache"
        cache.mkdir()
        _make_cache_dir(cache, "proj", "5.0.0")

        with pytest.raises(FileNotFoundError):
            scan_stale_cache(cache, tmp_path / "nonexistent.json")


class TestPruneStaleVersions:
    def test_removes_old_versions_keeps_newest(self, tmp_path):
        cache = tmp_path / "cache"
        cache.mkdir()
        for v in ("3.0.0", "4.0.0", "5.0.0"):
            _make_cache_dir(cache, "proj", v)

        report = PruneReport(orphans=[], stale_versions={"proj": ["3.0.0", "4.0.0"]})
        deleted = prune_stale_versions(cache, report)

        assert (cache / "proj" / "5.0.0").is_dir()
        assert not (cache / "proj" / "3.0.0").exists()
        assert not (cache / "proj" / "4.0.0").exists()
        assert len(deleted) == 2

    def test_empty_report_noop(self, tmp_path):
        cache = tmp_path / "cache"
        cache.mkdir()
        _make_cache_dir(cache, "proj", "5.0.0")

        report = PruneReport(orphans=[], stale_versions={})
        deleted = prune_stale_versions(cache, report)

        assert deleted == []
        assert (cache / "proj" / "5.0.0").is_dir()
```

- [ ] **Step 2: Run tests to verify failure**

```bash
cd /home/raul/projects/claude-project-manager/installer
python -m pytest tests/test_cleanup.py::TestScanStaleCache tests/test_cleanup.py::TestPruneStaleVersions -v
```

Expected: all FAIL with `ImportError: cannot import name 'PruneReport'` / `'scan_stale_cache'` / `'prune_stale_versions'`.

- [ ] **Step 3: Implement**

In `installer/cleanup.py`, add at the top of the file after existing imports:

```python
from dataclasses import dataclass, field

from packaging.version import InvalidVersion, Version
```

Add below the existing `_parse_live_plugins` function (but above `cleanup_orphaned_plugin_caches`):

```python
@dataclass
class PruneReport:
    """Classification of cache dirs."""

    orphans: list[str] = field(default_factory=list)
    stale_versions: dict[str, list[str]] = field(default_factory=dict)


def _load_marketplace_plugins(marketplace_path: Path) -> set[str]:
    """Load plugin names from marketplace.json.

    Raises FileNotFoundError if the file doesn't exist.
    """
    if not marketplace_path.is_file():
        raise FileNotFoundError(f"marketplace.json not found: {marketplace_path}")
    data = json.loads(marketplace_path.read_text())
    plugins = data.get("plugins", [])
    return {p["name"] for p in plugins if isinstance(p, dict) and "name" in p}


def scan_stale_cache(cache_dir: Path, marketplace_path: Path) -> PruneReport:
    """Classify every dir in cache_dir as active, stale-version, or orphan.

    - Orphans: plugin dirs whose name is not in marketplace.json.
    - Stale versions: non-highest semver subdirs for active plugins.
    - The highest-semver dir for each active plugin is kept out of the report.

    Raises FileNotFoundError if marketplace.json is missing.
    """
    active = _load_marketplace_plugins(marketplace_path)
    report = PruneReport()

    if not cache_dir.is_dir():
        return report

    for plugin_dir in sorted(cache_dir.iterdir()):
        if not plugin_dir.is_dir():
            continue
        if plugin_dir.name.startswith("."):
            continue
        if plugin_dir.name == "_shared":
            continue  # shared library dir, not a plugin
        if plugin_dir.name not in active:
            report.orphans.append(plugin_dir.name)
            continue
        # Active plugin — enumerate version subdirs
        version_dirs: list[tuple[Version, str]] = []
        unparseable: list[str] = []
        for v_dir in plugin_dir.iterdir():
            if not v_dir.is_dir():
                continue
            try:
                version_dirs.append((Version(v_dir.name), v_dir.name))
            except InvalidVersion:
                unparseable.append(v_dir.name)
        if len(version_dirs) <= 1:
            continue
        # Keep highest semver; mark the rest stale
        version_dirs.sort(key=lambda t: t[0], reverse=True)
        stale = [name for _, name in version_dirs[1:]]
        if stale:
            report.stale_versions[plugin_dir.name] = stale

    return report


def prune_stale_versions(cache_dir: Path, report: PruneReport) -> list[str]:
    """Delete the stale version dirs listed in the report.

    Returns list of deleted paths (as strings) for logging.
    """
    deleted: list[str] = []
    for plugin, versions in report.stale_versions.items():
        plugin_dir = cache_dir / plugin
        if not plugin_dir.is_dir():
            continue
        for version in versions:
            v_dir = plugin_dir / version
            if not v_dir.is_dir():
                continue
            try:
                shutil.rmtree(v_dir)
                deleted.append(str(v_dir))
                logger.info("Pruned stale version dir: %s", v_dir)
            except OSError as exc:
                logger.warning("Failed to remove %s: %s", v_dir, exc)
    return deleted
```

- [ ] **Step 4: Run tests to verify pass**

```bash
cd /home/raul/projects/claude-project-manager/installer
python -m pytest tests/test_cleanup.py -v 2>&1 | tail -15
```

Expected: all new tests PASS. Existing `cleanup_orphaned_plugin_caches` tests still pass.

- [ ] **Step 5: Commit**

```bash
cd /home/raul/projects/claude-project-manager
git add installer/cleanup.py installer/tests/test_cleanup.py
git commit -m "feat(installer): add scan_stale_cache + prune_stale_versions

Classify plugin cache dirs as active / stale-version / orphan via
marketplace.json. prune_stale_versions removes old-version subdirs while
keeping the highest semver per plugin.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Installer — prune_orphaned_plugins helper

Add the explicit orphan-removal function (separate from `cleanup_orphaned_plugin_caches` which uses `installed_plugins.json`, not `marketplace.json`).

**Files:**
- Modify: `installer/cleanup.py`
- Test: `installer/tests/test_cleanup.py`

- [ ] **Step 1: Write failing tests**

Add to `installer/tests/test_cleanup.py`:

```python
from installer.cleanup import prune_orphaned_plugins


class TestPruneOrphanedPlugins:
    def test_removes_listed_orphans(self, tmp_path):
        cache = tmp_path / "cache"
        cache.mkdir()
        (cache / "sandbox" / "1.0.0").mkdir(parents=True)
        (cache / "zoxide" / "1.0.0").mkdir(parents=True)
        (cache / "proj" / "5.0.0").mkdir(parents=True)

        deleted = prune_orphaned_plugins(cache, ["sandbox", "zoxide"])

        assert set(deleted) == {str(cache / "sandbox"), str(cache / "zoxide")}
        assert not (cache / "sandbox").exists()
        assert not (cache / "zoxide").exists()
        assert (cache / "proj").is_dir()

    def test_handles_missing_dir(self, tmp_path):
        cache = tmp_path / "cache"
        cache.mkdir()
        # Orphan named but dir does not exist
        deleted = prune_orphaned_plugins(cache, ["nonexistent"])
        assert deleted == []

    def test_empty_list_noop(self, tmp_path):
        cache = tmp_path / "cache"
        cache.mkdir()
        (cache / "proj" / "5.0.0").mkdir(parents=True)
        deleted = prune_orphaned_plugins(cache, [])
        assert deleted == []
        assert (cache / "proj").is_dir()
```

- [ ] **Step 2: Run test to verify failure**

```bash
cd /home/raul/projects/claude-project-manager/installer
python -m pytest tests/test_cleanup.py::TestPruneOrphanedPlugins -v
```

Expected: FAIL with `ImportError: cannot import name 'prune_orphaned_plugins'`.

- [ ] **Step 3: Implement**

Append to `installer/cleanup.py`:

```python
def prune_orphaned_plugins(cache_dir: Path, orphans: list[str]) -> list[str]:
    """Delete the listed orphan plugin dirs.

    Caller is responsible for user confirmation before calling. Returns list
    of deleted paths (as strings).
    """
    deleted: list[str] = []
    for name in orphans:
        target = cache_dir / name
        if not target.is_dir():
            continue
        try:
            shutil.rmtree(target)
            deleted.append(str(target))
            logger.info("Pruned orphaned plugin: %s", target)
        except OSError as exc:
            logger.warning("Failed to remove %s: %s", target, exc)
    return deleted
```

- [ ] **Step 4: Run tests to verify pass**

```bash
cd /home/raul/projects/claude-project-manager/installer
python -m pytest tests/test_cleanup.py -v 2>&1 | tail -15
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
cd /home/raul/projects/claude-project-manager
git add installer/cleanup.py installer/tests/test_cleanup.py
git commit -m "feat(installer): add prune_orphaned_plugins helper

Caller-controlled orphan removal — takes an explicit list, never infers.
Paired with scan_stale_cache to produce the list.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Installer CLI — wire pruning into _reinstall

Call `scan_stale_cache` + auto `prune_stale_versions` + Rich-prompt `prune_orphaned_plugins` at the start of `_reinstall`.

**Files:**
- Modify: `installer/main.py` (find `_reinstall` function, ~line 130)
- Test: `installer/tests/test_main.py`

- [ ] **Step 1: Read current _reinstall code**

```bash
sed -n '125,195p' /home/raul/projects/claude-project-manager/installer/main.py
```

Note the resolution of `cache_dir` / `marketplace_path`. If they aren't already resolved in `_reinstall`, prepare to reuse whatever helper `installer.detect` provides (e.g. `detect_existing().cache_dir`).

- [ ] **Step 2: Write failing test**

Add to `installer/tests/test_main.py`:

```python
def test_reinstall_prunes_stale_cache_before_install(monkeypatch, tmp_path, capsys):
    """_reinstall runs scan_stale_cache + prune_stale_versions before install loop."""
    import installer.main as main_mod

    # Set up cache with stale versions
    cache = tmp_path / "cache"
    cache.mkdir()
    for v in ("3.0.0", "4.0.0", "5.0.0"):
        (cache / "proj" / v).mkdir(parents=True)
    (cache / "sandbox" / "1.0.0").mkdir(parents=True)  # orphan

    # Set up marketplace
    mp = tmp_path / "marketplace.json"
    mp.write_text('{"plugins": [{"name": "proj"}]}')

    # Monkeypatch installers _reinstall to use our paths
    monkeypatch.setattr(main_mod, "_cache_dir_for_reinstall", lambda: cache, raising=False)
    monkeypatch.setattr(main_mod, "_marketplace_path_for_reinstall", lambda: mp, raising=False)

    # Auto-confirm orphan removal
    monkeypatch.setattr("rich.prompt.Confirm.ask", lambda *a, **kw: True)

    # Stub claude plugin install subprocess calls to no-op
    monkeypatch.setattr(main_mod, "install_plugin", lambda *a, **kw: None, raising=False)
    monkeypatch.setattr(main_mod, "remove_marketplace", lambda *a, **kw: None, raising=False)
    monkeypatch.setattr(main_mod, "add_marketplace", lambda *a, **kw: None, raising=False)
    monkeypatch.setattr(main_mod, "get_installed_plugins", lambda: ["proj@cpm"], raising=False)

    # Invoke
    import argparse
    args = argparse.Namespace(reinstall=True, plugins=None, skip_wizard=True)
    main_mod._reinstall(args)

    # Assertions: stale versions removed, orphan removed
    assert (cache / "proj" / "5.0.0").is_dir()
    assert not (cache / "proj" / "3.0.0").exists()
    assert not (cache / "proj" / "4.0.0").exists()
    assert not (cache / "sandbox").exists()
```

(If `_cache_dir_for_reinstall` / `_marketplace_path_for_reinstall` helpers don't exist yet, the test defines them via monkeypatch and expects `_reinstall` to fall back to them — adjust in Step 3.)

- [ ] **Step 3: Run test to verify failure**

```bash
cd /home/raul/projects/claude-project-manager/installer
python -m pytest tests/test_main.py::test_reinstall_prunes_stale_cache_before_install -v
```

Expected: FAIL — either cache isn't pruned (test assertions fail) or the test setup itself fails to patch the right names.

- [ ] **Step 4: Implement cleanup call in _reinstall**

In `installer/main.py`, near the top of `_reinstall` (after the initial console setup but before the install-loop logic), add:

```python
from pathlib import Path

from installer.cleanup import (
    prune_orphaned_plugins,
    prune_stale_versions,
    scan_stale_cache,
)
from rich.prompt import Confirm


def _cache_dir_for_reinstall() -> Path:
    """Resolve cache dir for reinstall — overridable in tests."""
    return Path.home() / ".claude" / "plugins" / "cache" / "claude-project-manager"


def _marketplace_path_for_reinstall() -> Path:
    """Resolve marketplace.json path — overridable in tests."""
    # Installer-bundled marketplace.json travels next to the installer
    here = Path(__file__).resolve().parent
    bundled = here / "marketplace.json"
    if bundled.is_file():
        return bundled
    # Fallback: repo-relative path
    return here.parent / ".claude-plugin" / "marketplace.json"
```

In `_reinstall` body, before the existing install loop, insert:

```python
    cache_dir = _cache_dir_for_reinstall()
    marketplace_path = _marketplace_path_for_reinstall()

    if cache_dir.is_dir() and marketplace_path.is_file():
        try:
            report = scan_stale_cache(cache_dir, marketplace_path)
        except (FileNotFoundError, OSError) as exc:
            console.print(f"[yellow]Skipping cache cleanup: {exc}[/yellow]")
        else:
            deleted_stale = prune_stale_versions(cache_dir, report)
            if deleted_stale:
                console.print(
                    f"[dim]Pruned {len(deleted_stale)} stale version dir(s)[/dim]"
                )
            if report.orphans:
                console.print(
                    f"[yellow]Found {len(report.orphans)} orphaned plugin(s): "
                    f"{', '.join(report.orphans)}[/yellow]"
                )
                if Confirm.ask(
                    "Remove orphaned plugin cache dirs?", default=True
                ):
                    deleted_orph = prune_orphaned_plugins(cache_dir, report.orphans)
                    console.print(
                        f"[dim]Removed {len(deleted_orph)} orphan plugin(s)[/dim]"
                    )
                else:
                    console.print(
                        "[dim]Leaving orphans in place; rerun --reinstall anytime.[/dim]"
                    )
```

- [ ] **Step 5: Run test to verify pass**

```bash
cd /home/raul/projects/claude-project-manager/installer
python -m pytest tests/test_main.py::test_reinstall_prunes_stale_cache_before_install -v
```

Expected: PASS.

- [ ] **Step 6: Run full installer test suite**

```bash
cd /home/raul/projects/claude-project-manager/installer
python -m pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: all pass, no regressions.

- [ ] **Step 7: Commit**

```bash
cd /home/raul/projects/claude-project-manager
git add installer/main.py installer/tests/test_main.py
git commit -m "feat(installer): prune stale cache in CLI --reinstall flow

_reinstall now scans for stale plugin versions and orphaned plugin dirs
before the install loop. Stale versions auto-pruned; orphans prompted
via Rich.Confirm.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Installer TUI — wire pruning into _prepare_and_reinstall

Same logic as Task 7 but for the TUI flow, using ConfirmScreen for orphan confirmation.

**Files:**
- Modify: `installer/app.py::_prepare_and_reinstall` (~line 640-720)
- Test: `installer/tests/test_app.py`

- [ ] **Step 1: Read current _prepare_and_reinstall**

```bash
sed -n '640,720p' /home/raul/projects/claude-project-manager/installer/app.py
```

Note the existing flow, the ConfirmScreen class used, and the `progress.write_log(...)` pattern.

- [ ] **Step 2: Write failing test**

Add to `installer/tests/test_app.py`:

```python
async def test_prepare_and_reinstall_prunes_stale_cache(monkeypatch, tmp_path):
    """_prepare_and_reinstall runs scan+prune before calling install worker."""
    from installer.app import InstallerApp

    cache = tmp_path / "cache"
    cache.mkdir()
    for v in ("3.0.0", "5.0.0"):
        (cache / "proj" / v).mkdir(parents=True)
    (cache / "sandbox" / "1.0.0").mkdir(parents=True)
    mp = tmp_path / "marketplace.json"
    mp.write_text('{"plugins": [{"name": "proj"}]}')

    # Monkeypatch resolution helpers
    monkeypatch.setattr(
        "installer.app._cache_dir_for_reinstall", lambda: cache, raising=False
    )
    monkeypatch.setattr(
        "installer.app._marketplace_path_for_reinstall", lambda: mp, raising=False
    )

    # Stub the install worker
    async def _stub_worker(self, plugins, progress, reset_configs):
        return None

    monkeypatch.setattr(InstallerApp, "_run_reinstall_worker", _stub_worker, raising=True)
    monkeypatch.setattr(
        "installer.app.get_installed_plugins", lambda: ["proj@cpm"], raising=False
    )

    # Set up app + stub _state + stub push_screen + auto-confirm
    app = InstallerApp(mode="reinstall")
    app._state = type("S", (), {})()  # placeholder (not used by cleanup path)
    app.push_screen = lambda *a, **kw: None
    monkeypatch.setattr(
        "installer.app.InstallerApp._confirm_orphans", lambda self, names: True, raising=False
    )

    await app._prepare_and_reinstall(reset_configs=False)

    # Stale version removed, orphan removed
    assert not (cache / "proj" / "3.0.0").exists()
    assert (cache / "proj" / "5.0.0").is_dir()
    assert not (cache / "sandbox").exists()
```

- [ ] **Step 3: Run test to verify failure**

```bash
cd /home/raul/projects/claude-project-manager/installer
python -m pytest tests/test_app.py::test_prepare_and_reinstall_prunes_stale_cache -v
```

Expected: FAIL (either attribute missing or cache not pruned).

- [ ] **Step 4: Implement cleanup in _prepare_and_reinstall**

Add to `installer/app.py` top-level (after existing imports):

```python
from installer.cleanup import (
    prune_orphaned_plugins,
    prune_stale_versions,
    scan_stale_cache,
)
from installer.main import (
    _cache_dir_for_reinstall,
    _marketplace_path_for_reinstall,
)
```

Add a helper method to `InstallerApp`:

```python
    async def _confirm_orphans(self, orphan_names: list[str]) -> bool:
        """Show ConfirmScreen for orphan removal; returns True if user confirmed."""
        from installer.screens.confirm import ConfirmResult, ConfirmScreen

        confirmed: list[bool] = []

        def _cb(result: ConfirmResult) -> None:
            confirmed.append(bool(result.confirmed))

        await self.push_screen_wait(
            ConfirmScreen(
                title="Remove Orphaned Plugins",
                message=(
                    f"Found {len(orphan_names)} orphaned plugin dir(s) in cache:\n"
                    f"  {', '.join(orphan_names)}\n\n"
                    "These plugins are no longer in the marketplace. Remove them?"
                ),
                options=[],
                confirm_label="Remove",
                confirm_variant="warning",
            ),
            callback=_cb,
        )
        return bool(confirmed and confirmed[0])
```

(If `push_screen_wait` doesn't exist in Textual's async API here, use the existing `push_screen(..., callback=...)` pattern from the same file and await via an `asyncio.Event`. Check the existing `_on_reinstall_confirmed` callback pattern in `_prepare_and_reinstall` — mirror that.)

Near the top of `_prepare_and_reinstall`, before the `get_installed_plugins` call, add:

```python
        cache_dir = _cache_dir_for_reinstall()
        marketplace_path = _marketplace_path_for_reinstall()

        if cache_dir.is_dir() and marketplace_path.is_file():
            try:
                report = await asyncio.to_thread(
                    scan_stale_cache, cache_dir, marketplace_path
                )
            except (FileNotFoundError, OSError):
                report = None

            if report is not None:
                deleted_stale = await asyncio.to_thread(
                    prune_stale_versions, cache_dir, report
                )
                if report.orphans:
                    if await self._confirm_orphans(report.orphans):
                        await asyncio.to_thread(
                            prune_orphaned_plugins, cache_dir, report.orphans
                        )
```

- [ ] **Step 5: Run tests to verify pass**

```bash
cd /home/raul/projects/claude-project-manager/installer
python -m pytest tests/test_app.py -v --tb=short 2>&1 | tail -15
```

Expected: all pass.

- [ ] **Step 6: Run full installer test suite**

```bash
cd /home/raul/projects/claude-project-manager/installer
python -m pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
cd /home/raul/projects/claude-project-manager
git add installer/app.py installer/tests/test_app.py
git commit -m "feat(installer): prune stale cache in TUI reinstall flow

_prepare_and_reinstall now runs scan_stale_cache + prune_stale_versions
(auto) + prune_orphaned_plugins (via ConfirmScreen) before calling the
install worker. Mirrors CLI --reinstall flow from task 7.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: End-to-end verification

**Files:** none modified; just running the whole flow.

- [ ] **Step 1: Run full test suite for both affected plugins**

```bash
cd /home/raul/projects/claude-project-manager/plugins/router/server
python -m pytest tests/ -v --tb=short 2>&1 | tail -20

cd /home/raul/projects/claude-project-manager/installer
python -m pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: all pass.

- [ ] **Step 2: Manual reproduction test**

Set up dirty state and verify end-to-end:

```bash
# Reset state — introduce synthetic orphans and stale versions
mkdir -p ~/.claude/plugins/cache/claude-project-manager/proj/3.0.0
mkdir -p ~/.claude/plugins/cache/claude-project-manager/sandbox/1.0.0

# Regenerate hooks.yaml
cp ~/.claude/hooks.yaml ~/.claude/hooks.yaml.bak-task9 2>/dev/null || true
echo 'hooks: []' > ~/.claude/hooks.yaml
echo 'servers: {}' >> ~/.claude/hooks.yaml

# Run reinstall (use --skip-wizard for clean test)
# (Actual invocation depends on CLI binary — adjust as needed)
# The reinstall flow should:
#  - Print "Pruned N stale version dir(s)"
#  - Show orphan prompt: "Found 1 orphaned plugin(s): sandbox"
#  - On Yes: print "Removed 1 orphan plugin(s)"
```

Verify:
```bash
ls ~/.claude/plugins/cache/claude-project-manager/
# Expected: only proj, worktree, router, trello, jira, todoist (+ _shared)
# NOT: sandbox, analyse, zoxide

# After router restart / next router_sync_tool call:
grep -c "server: sandbox" ~/.claude/hooks.yaml  # Expected: 0
grep -c "server: zoxide" ~/.claude/hooks.yaml   # Expected: 0
awk '/^- id:/ {print $3}' ~/.claude/hooks.yaml | sort | uniq -d  # Expected: empty
```

- [ ] **Step 3: Push to dev and verify CI**

```bash
git push origin dev
gh run watch $(gh run list --branch dev --limit 1 --json databaseId -q '.[0].databaseId') --exit-status
```

Expected: CI green.

- [ ] **Step 4: Mark todo 638 complete**

Via MCP:
```
mcp__plugin_proj_proj__todo_complete(todo_id="638", note="Implemented per spec 2026-04-16-plugin-cache-management-design.md. Installer cleanup + router discovery + orphan hook removal all landed. See commits from tasks 1-8.")
```

---

## Verification checklist (post-merge)

- [ ] `plugins/router/server/tests/test_discovery.py` all tests pass including `TestVersionSelection`, `TestPluginNameFromPath`, `TestRunDiscoveryActivePlugins`
- [ ] `plugins/router/server/tests/test_orphan_cleanup.py` all tests pass
- [ ] `installer/tests/test_cleanup.py` all tests pass including `TestScanStaleCache`, `TestPruneStaleVersions`, `TestPruneOrphanedPlugins`
- [ ] `installer/tests/test_main.py::test_reinstall_prunes_stale_cache_before_install` passes
- [ ] `installer/tests/test_app.py::test_prepare_and_reinstall_prunes_stale_cache` passes
- [ ] Manual reproduction produces a clean cache + hooks.yaml
- [ ] CI green on dev
- [ ] Todo 638 marked complete
