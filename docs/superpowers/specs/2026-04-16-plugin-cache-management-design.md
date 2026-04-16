# Permanent Fix for Plugin Cache Management

## Context

The 605.8 plugin folding (sandbox → proj, zoxide → worktree, analyse → proj/skills) revealed four interacting bugs that together produce cascading hook-registration failures after upgrades:

1. **Installer does not prune old version dirs** — after upgrading from 4.0.0 → 5.0.0, cache holds both `proj/4.0.0/` and `proj/5.0.0/` (and often older versions too)
2. **Installer does not remove orphaned plugin dirs** — `analyse/`, `sandbox/`, `zoxide/` cache dirs remain after those plugins are deleted from marketplace
3. **Router discovery scans all version subdirs** — `find_default_hooks_files()` in `plugins/router/server/server/lib/discovery.py` returns every `default-hooks.yaml` under every version of every plugin
4. **`router_sync_tool` does not remove orphaned hooks** — when a source `default-hooks.yaml` vanishes, its auto-registered hooks linger in `~/.claude/hooks.yaml` forever

Also found: `_plugin_name_from_path()` returns the version string as the plugin name for the cache layout — sync summary output already shows this bug (`5.0.0: 5 new`, `3.0.1: 7 new`).

### Symptoms observed

- Reinstall with `--reinstall` flag fails trying to reinstall deleted plugins (`analyse`, `sandbox`, `zoxide`)
- `~/.claude/hooks.yaml` accumulates 50+ hooks with duplicated IDs registering the same trigger against different (old vs new) target tools — e.g. `jira-on-todo-complete` appears twice, once with `jira_bulk_update_issues` (3.0.0), once with `jira_update_issues` (5.0.0)
- Hooks fire against non-existent servers (`server: sandbox`, `server: zoxide`) producing `Unknown tool: X` errors during normal MCP operations

### Intended outcome

After upgrade + reinstall:
- Cache contains only active plugins at current marketplace versions
- `router_sync_tool` produces a clean `hooks.yaml` with one entry per logical hook
- No dangling references to deleted plugins/servers
- Defense in depth: router tolerates messy cache (e.g., user sideloads plugins) without registering duplicates

## Approach

Fix at both layers: installer cleans the cache, router defends against any remaining mess. Four components:

```
Installer reinstall flow
  └─ NEW: prune_stale_cache()
      - auto-delete old version dirs (semver comparison)
      - detect orphans → confirm → delete

Router discovery
  ├─ FIX: find_default_hooks_files()
  │   - per-plugin: pick highest semver only
  │   - skip orphans (not in marketplace.json)
  └─ FIX: _plugin_name_from_path()
      - cache layout: skip version segment

Router sync
  └─ FIX: discover_and_register()
      - remove source:auto hooks no longer in discovered set
```

## Component 1: Installer cache pruning

**New file:** `installer/cleanup.py` (or extend existing `installer/cleanup.py` if present)

**Public API:**
```python
@dataclass
class PruneReport:
    orphans: list[str]                   # plugin names not in marketplace.json
    stale_versions: dict[str, list[str]]  # {plugin_name: [old_version, ...]}

def scan_stale_cache(
    cache_dir: Path,
    marketplace_path: Path,
) -> PruneReport:
    """Enumerate cache; classify dirs as active/orphan/stale."""

def prune_stale_versions(cache_dir: Path, report: PruneReport) -> list[str]:
    """Delete old-version dirs (safe auto-operation). Returns deleted paths."""

def prune_orphaned_plugins(cache_dir: Path, orphans: list[str]) -> list[str]:
    """Delete orphaned plugin dirs (caller must confirm). Returns deleted paths."""
```

**Integration points:**
- CLI: call in `installer/main.py::_reinstall()` before the install loop
  - `scan_stale_cache()` → auto-run `prune_stale_versions()` → prompt via Rich for orphans → `prune_orphaned_plugins()`
- TUI: call in `installer/app.py::_prepare_and_reinstall()` before `_run_reinstall_worker()`
  - Same flow but use `ConfirmScreen` for orphan confirmation

**Semver comparison:** use `packaging.version.Version`. Unparseable versions (e.g. hash-based "92f892f2b997") → skip pruning for that plugin, log warning.

**Safety:** `prune_stale_versions` only touches version subdirs under a plugin dir that IS in marketplace.json. Never deletes the currently-highest version. `prune_orphaned_plugins` only deletes dirs explicitly listed in the report's `orphans` field.

## Component 2: Router discovery — version selection

**File:** `plugins/router/server/server/lib/discovery.py`

**Fix `_plugin_name_from_path()`** (lines 147-153):
```python
def _plugin_name_from_path(path: Path) -> str:
    """Extract plugin name from a default-hooks.yaml path.

    Dev layout:   .../plugins/<name>/.claude-plugin/default-hooks.yaml
    Cache layout: .../cache/.../<name>/<version>/.claude-plugin/default-hooks.yaml
    """
    # path.parent = .claude-plugin
    # Dev: path.parent.parent = <name>
    # Cache: path.parent.parent = <version>, .parent.parent.parent = <name>
    grandparent = path.parent.parent
    if _is_version_string(grandparent.name):
        return grandparent.parent.name
    return grandparent.name


def _is_version_string(s: str) -> bool:
    """Heuristic: looks like a semver or version-ish token."""
    try:
        Version(s)
        return True
    except InvalidVersion:
        return False
```

**Fix `find_default_hooks_files()`** (lines 81-105):
```python
def find_default_hooks_files(
    root: Path | None = None,
    glob_pattern: str = _DEFAULT_PLUGIN_GLOB,
    active_plugins: set[str] | None = None,
) -> list[Path]:
    """Find default-hooks.yaml files, one per plugin, preferring highest version.

    active_plugins: if provided, filter out plugins not in this set.
    """
    discovery_root = root or _default_discovery_root()
    pattern = f"{glob_pattern}/{_DEFAULT_HOOKS_FILENAME}"
    found = sorted(discovery_root.glob(pattern))
    if not found:
        cache_pattern = f"*/*/.claude-plugin/{_DEFAULT_HOOKS_FILENAME}"
        found = sorted(discovery_root.glob(cache_pattern))

    # Group by plugin name, pick highest semver per plugin
    by_plugin: dict[str, list[tuple[Version, Path]]] = {}
    for path in found:
        name = _plugin_name_from_path(path)
        if active_plugins is not None and name not in active_plugins:
            continue  # skip orphan
        version = _path_version(path) or Version("0.0.0")  # dev layout
        by_plugin.setdefault(name, []).append((version, path))

    return [max(candidates, key=lambda vp: vp[0])[1] for candidates in by_plugin.values()]


def _path_version(path: Path) -> Version | None:
    """Extract version from path if cache layout, else None (dev layout)."""
    # path.parent.parent is version in cache layout
    candidate = path.parent.parent.name
    try:
        return Version(candidate)
    except InvalidVersion:
        return None
```

**Active plugins source:** passed through from `run_discovery()`. Default: read from `marketplace.json` — caller responsibility (router can't assume location). If `marketplace.json` not found, pass `None` to disable orphan filtering (scan all).

## Component 3: Router sync — remove orphaned hooks

**File:** `plugins/router/server/server/lib/discovery.py::discover_and_register()`

Current behavior: for each hook in discovered `default-hooks.yaml`, register or update if drifted. Never removes anything.

**New behavior:** after processing all discovered hooks, enumerate existing `source: auto` hooks in registry. If the hook's `(trigger, target, server)` triple is NOT in the set of currently-discovered keys → remove it. Manual hooks (`source != auto`) untouched.

```python
def discover_and_register(registry, root=None, glob_pattern=...) -> dict:
    files = find_default_hooks_files(root, glob_pattern)
    discovered_keys: set[tuple[str, str, str]] = set()
    stats = {}

    for path in files:
        # ... existing registration logic ...
        for hook_def in hook_defs:
            key = (trigger, target, server)
            discovered_keys.add(key)
            # ... existing register/update ...

    # NEW: remove orphaned auto hooks
    removed = []
    for hook in list(registry.hooks):
        if hook.source != "auto":
            continue
        if (hook.trigger_tool, hook.target_tool, hook.server) not in discovered_keys:
            registry.hooks.remove(hook)
            removed.append(hook.id)

    stats["orphans_removed"] = len(removed)
    return stats
```

## Component 4: Tests

### Installer

**`installer/tests/test_cleanup.py`** (new or extended):

```python
class TestScanStaleCache:
    def test_detects_orphans(self, tmp_path): ...
    def test_detects_stale_versions(self, tmp_path): ...
    def test_ignores_current_version(self, tmp_path): ...
    def test_handles_unparseable_version(self, tmp_path): ...

class TestPruneStaleVersions:
    def test_removes_old_versions_keeps_newest(self, tmp_path): ...
    def test_safe_on_single_version(self, tmp_path): ...

class TestPruneOrphanedPlugins:
    def test_removes_listed_orphans(self, tmp_path): ...
    def test_handles_rm_failure(self, tmp_path): ...
```

### Router

**`plugins/router/server/tests/test_discovery.py`** (extend):

```python
class TestVersionSelection:
    def test_picks_highest_semver_per_plugin(self, tmp_path): ...
    def test_dev_layout_only(self, tmp_path): ...
    def test_cache_layout_only(self, tmp_path): ...
    def test_mixed_layouts_cache_wins(self, tmp_path): ...
    def test_orphan_filter_via_active_plugins(self, tmp_path): ...
    def test_unparseable_version_logs_and_continues(self, tmp_path): ...

class TestPluginNameFromPath:
    def test_dev_layout(self): ...
    def test_cache_layout_strips_version(self): ...
```

**`plugins/router/server/tests/test_sync.py`** (extend or new):

```python
class TestOrphanRemoval:
    def test_removes_auto_hook_when_source_file_vanishes(self): ...
    def test_preserves_manual_hooks(self): ...
    def test_idempotent_twice(self): ...
```

## Error handling

| Situation | Behavior |
|---|---|
| Installer: `rm -rf` permission denied | Log warning, continue with other dirs |
| Installer: `marketplace.json` missing | Abort cleanup, proceed with standard install |
| Installer: user declines orphan removal | Log orphans, continue (idempotent on next run) |
| Router: unparseable version string | Fall back to `Version("0.0.0")`, log warning |
| Router: tied highest versions (same-version in multiple paths) | Lexicographic tiebreak on path (stable) |
| Router: `marketplace.json` not found | Skip orphan filtering (`active_plugins=None`), scan all |
| Router sync: orphan removal log level | INFO (visible in summary, not warn-spam) |

## Verification

End-to-end manual:
1. Reset to dirty state: `cp ~/.claude/hooks.yaml.bak-2026-04-16 ~/.claude/hooks.yaml` (from prior session backup)
2. Verify cache has stale dirs: `ls ~/.claude/plugins/cache/claude-project-manager/`
3. Run `cpm --reinstall`
4. Expected: TUI/CLI shows "Removing 6 stale version dirs" auto, then "3 orphaned plugins (analyse, sandbox, zoxide). Remove? [Y/n]"
5. After install + next `router_sync_tool` call:
   - `~/.claude/plugins/cache/claude-project-manager/` contains only 6 active plugins at 5.0.0
   - `grep -c "^- id:" ~/.claude/hooks.yaml` returns ~45 (not 50+ with dupes)
   - `grep -c "server: sandbox" ~/.claude/hooks.yaml` returns 0
   - `grep -c "server: zoxide" ~/.claude/hooks.yaml` returns 0
   - No duplicate hook IDs: `awk '/^- id:/ {print $3}' ~/.claude/hooks.yaml | sort | uniq -d` returns empty

Automated: pytest suites pass for both installer and router plugins.

## Related todos

- **638** (high) — Installer reinstall errors for deleted plugins. This spec supersedes: Option A + C from 638 notes are implemented in Component 1.
- **617, 618** (done) — Worktree default-hooks.yaml fixes. Root cause addressed at source (the folding hook migration). This spec adds defense in depth so future foldings don't cause the same cascade.

## Out of scope

- Backfilling old users' `hooks.yaml` — handled manually via `rm hooks.yaml && router_sync_tool` or via Component 3's orphan removal on next sync
- Plugin version bump automation (marketplace.json vs plugin.json sync) — separate concern, tracked elsewhere
- User-added manual hooks surviving cleanup — by design, `source != auto` hooks never removed
