# Todo 651: Router Sync-Layer Dedup-by-`hook_id` Guard — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `HookRegistry.deduplicate_by_hook_id()` method that collapses entries sharing the same `hook.id` with a canonical-server keep-rule, and wire it into `storage.save()` so `~/.claude/hooks.yaml` never re-accumulates duplicate named hook ids.

**Architecture:** New method on the existing `HookRegistry` dataclass (alongside `deduplicate_numeric_hooks()`). The sole write path `storage.save()` calls the new method before serializing and emits a `WARNING` log listing removed ids when dedup fires. Because `save()` is the only write entry point, this guard catches every sync / recovery path without further wiring.

**Tech Stack:** Python 3.12+, pytest, standard `logging` module, `dataclasses`, PyYAML.

**Spec:** `docs/superpowers/specs/2026-04-16-tech-debt-635-648-651-design.md` §3.

**Prerequisite worktree:** `/home/raul/worktrees/cpm/feat-651-router-dedup-guard` on branch `feat/651-router-dedup-guard`. All file edits + git operations MUST happen inside this directory.

---

## File Structure

- **Modify:** `plugins/router/server/server/lib/models.py` — add `deduplicate_by_hook_id` method on `HookRegistry`.
- **Modify:** `plugins/router/server/server/lib/storage.py` — call dedup in `save()`; emit warning on removal.
- **Create:** `plugins/router/server/tests/test_models_dedup_by_id.py` — unit tests for the new method.
- **Modify:** `plugins/router/server/tests/test_storage.py` — integration test asserting `save()` dedups + logs.

Keep the new method adjacent to `deduplicate_numeric_hooks` (line ~216 in models.py) so both dedup utilities live together.

---

### Task 1: Create the worktree

**Files:** none yet.

- [ ] **Step 1: Create worktree via `wt_create` MCP tool**

Call `mcp__plugin_worktree_worktree__wt_create` with:
```json
{
  "repo_label": "cpm",
  "branch": "feat/651-router-dedup-guard",
  "base_branch": "dev"
}
```
Expected: worktree created at `/home/raul/worktrees/cpm/feat-651-router-dedup-guard`.

- [ ] **Step 2: Install deps once in the router plugin**

```bash
cd /home/raul/worktrees/cpm/feat-651-router-dedup-guard/plugins/router/server
uv sync --all-groups
```
Expected: deps installed without errors.

---

### Task 2: Write the failing unit test for `deduplicate_by_hook_id`

**Files:**
- Create: `plugins/router/server/tests/test_models_dedup_by_id.py`

- [ ] **Step 1: Write the first failing test**

Create `plugins/router/server/tests/test_models_dedup_by_id.py` with this content:

```python
"""Tests for HookRegistry.deduplicate_by_hook_id() — collapse same-id duplicates."""

from __future__ import annotations

from server.lib.models import Hook, HookRegistry


class TestDeduplicateByHookId:
    """Test HookRegistry.deduplicate_by_hook_id()."""

    def test_same_id_collapses_to_one(self):
        """Two entries sharing a hook.id collapse to a single hook."""
        registry = HookRegistry(
            hooks=[
                Hook(
                    id="proj-tracking-flush-on-todo-update",
                    trigger_tool="todo_update",
                    target_tool="tracking_git_flush",
                    server="proj",
                ),
                Hook(
                    id="proj-tracking-flush-on-todo-update",
                    trigger_tool="todo_update",
                    target_tool="tracking_git_flush",
                    server="proj",
                ),
            ]
        )
        removed = registry.deduplicate_by_hook_id()
        assert removed == ["proj-tracking-flush-on-todo-update"]
        assert len(registry.hooks) == 1
```

- [ ] **Step 2: Run the test and verify it fails**

```bash
cd /home/raul/worktrees/cpm/feat-651-router-dedup-guard/plugins/router/server
uv run pytest tests/test_models_dedup_by_id.py::TestDeduplicateByHookId::test_same_id_collapses_to_one -v
```
Expected: FAIL with `AttributeError: 'HookRegistry' object has no attribute 'deduplicate_by_hook_id'`.

---

### Task 3: Implement `deduplicate_by_hook_id` (minimal)

**Files:**
- Modify: `plugins/router/server/server/lib/models.py`

- [ ] **Step 1: Add the method on `HookRegistry`**

Open `plugins/router/server/server/lib/models.py`. Insert the following method on the `HookRegistry` class, directly below `deduplicate_numeric_hooks` (near line 216). Import `DEFAULT_SERVER_PORTS` at the top of the file if not already imported.

Add import near the top (if not present):
```python
from server.lib.constants import DEFAULT_SERVER_PORTS
```

Add method body inside `HookRegistry` (after `deduplicate_numeric_hooks`):

```python
    def deduplicate_by_hook_id(self) -> list[str]:
        """Collapse multiple hooks sharing the same ``hook.id`` to a single entry.

        Keep-rule (in order):
          1. Prefer an entry whose ``server`` appears in ``DEFAULT_SERVER_PORTS``
             (the canonical plugin-owned entry).
          2. On tie, keep the *last* occurrence in list order (freshest
             re-registration wins).

        Returns the list of removed hook ids (one entry per removed hook; the
        same id may appear multiple times if it had three or more duplicates).
        """
        from collections import defaultdict

        groups: defaultdict[str, list[tuple[int, Hook]]] = defaultdict(list)
        for idx, hook in enumerate(self.hooks):
            groups[hook.id].append((idx, hook))

        keep_indices: set[int] = set()
        removed_ids: list[str] = []
        for hook_id, entries in groups.items():
            if len(entries) == 1:
                keep_indices.add(entries[0][0])
                continue
            # Multiple entries share this id — apply the keep-rule.
            canonical = [(i, h) for i, h in entries if h.server in DEFAULT_SERVER_PORTS]
            pool = canonical if canonical else entries
            # Tiebreak: last in list order wins.
            kept_idx = max(i for i, _h in pool)
            keep_indices.add(kept_idx)
            for i, h in entries:
                if i != kept_idx:
                    removed_ids.append(h.id)

        if removed_ids:
            self.hooks = [h for i, h in enumerate(self.hooks) if i in keep_indices]
        return removed_ids
```

- [ ] **Step 2: Run the test and verify it passes**

```bash
cd /home/raul/worktrees/cpm/feat-651-router-dedup-guard/plugins/router/server
uv run pytest tests/test_models_dedup_by_id.py::TestDeduplicateByHookId::test_same_id_collapses_to_one -v
```
Expected: PASS.

- [ ] **Step 3: Commit the minimal implementation**

```bash
cd /home/raul/worktrees/cpm/feat-651-router-dedup-guard
git add plugins/router/server/server/lib/models.py plugins/router/server/tests/test_models_dedup_by_id.py
git commit -m "$(cat <<'EOF'
fix(router): add HookRegistry.deduplicate_by_hook_id (651)

New method collapses duplicate hook.id entries that the existing
deduplicate_numeric_hooks does not catch. Keep-rule: prefer canonical
plugin-owned server (entry in DEFAULT_SERVER_PORTS); tiebreak by last
occurrence in list order (freshest re-registration wins).

Co-Authored-By: Claude Opus 4 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Cover the keep-rule + edge cases

**Files:**
- Modify: `plugins/router/server/tests/test_models_dedup_by_id.py`

- [ ] **Step 1: Add the canonical-server preference test**

Append to `TestDeduplicateByHookId`:

```python
    def test_canonical_server_wins_over_blank(self):
        """When one dup has a canonical server and the other has an off-registry
        server, the canonical entry is kept regardless of list order."""
        registry = HookRegistry(
            hooks=[
                Hook(
                    id="x-hook",
                    trigger_tool="t",
                    target_tool="u",
                    server="proj",  # canonical (in DEFAULT_SERVER_PORTS)
                ),
                Hook(
                    id="x-hook",
                    trigger_tool="t",
                    target_tool="u",
                    server="wrong-server",  # not in DEFAULT_SERVER_PORTS
                ),
            ]
        )
        removed = registry.deduplicate_by_hook_id()
        assert removed == ["x-hook"]
        assert len(registry.hooks) == 1
        assert registry.hooks[0].server == "proj"

    def test_list_position_tiebreak_when_all_canonical(self):
        """Two canonical entries: last in list wins (freshest wins)."""
        registry = HookRegistry(
            hooks=[
                Hook(id="y-hook", trigger_tool="t", target_tool="u", server="proj"),
                Hook(id="y-hook", trigger_tool="t", target_tool="u", server="todoist"),
            ]
        )
        removed = registry.deduplicate_by_hook_id()
        assert removed == ["y-hook"]
        assert registry.hooks[0].server == "todoist"

    def test_three_way_duplicate_returns_two_removed(self):
        """Three entries → one survivor, two removed ids (id appears twice)."""
        registry = HookRegistry(
            hooks=[
                Hook(id="z-hook", trigger_tool="t", target_tool="u", server="proj"),
                Hook(id="z-hook", trigger_tool="t", target_tool="u", server="proj"),
                Hook(id="z-hook", trigger_tool="t", target_tool="u", server="proj"),
            ]
        )
        removed = registry.deduplicate_by_hook_id()
        assert removed == ["z-hook", "z-hook"]
        assert len(registry.hooks) == 1

    def test_no_duplicates_is_noop(self):
        """Registry with unique hook ids is unchanged; returns empty list."""
        registry = HookRegistry(
            hooks=[
                Hook(id="a-hook", trigger_tool="t", target_tool="u", server="proj"),
                Hook(id="b-hook", trigger_tool="t", target_tool="v", server="proj"),
            ]
        )
        before = list(registry.hooks)
        removed = registry.deduplicate_by_hook_id()
        assert removed == []
        assert registry.hooks == before

    def test_composes_with_numeric_dedup(self):
        """deduplicate_numeric_hooks then deduplicate_by_hook_id leave a clean registry."""
        registry = HookRegistry(
            hooks=[
                Hook(
                    id="hook-009",
                    trigger_tool="todo_update",
                    target_tool="tracking_git_flush",
                    server="proj",
                    source="auto",
                ),
                Hook(
                    id="proj-tracking-flush-on-todo-update",
                    trigger_tool="todo_update",
                    target_tool="tracking_git_flush",
                    server="proj",
                ),
                Hook(
                    id="proj-tracking-flush-on-todo-update",
                    trigger_tool="todo_update",
                    target_tool="tracking_git_flush",
                    server="proj",
                ),
            ]
        )
        numeric_removed = registry.deduplicate_numeric_hooks()
        id_removed = registry.deduplicate_by_hook_id()
        assert numeric_removed == ["hook-009"]
        assert id_removed == ["proj-tracking-flush-on-todo-update"]
        assert len(registry.hooks) == 1
        assert registry.hooks[0].id == "proj-tracking-flush-on-todo-update"
```

- [ ] **Step 2: Run the full test file and verify all tests pass**

```bash
cd /home/raul/worktrees/cpm/feat-651-router-dedup-guard/plugins/router/server
uv run pytest tests/test_models_dedup_by_id.py -v
```
Expected: 5 tests pass (`test_same_id_collapses_to_one` + the 4 new ones).

- [ ] **Step 3: Commit the expanded test coverage**

```bash
cd /home/raul/worktrees/cpm/feat-651-router-dedup-guard
git add plugins/router/server/tests/test_models_dedup_by_id.py
git commit -m "$(cat <<'EOF'
test(router): cover deduplicate_by_hook_id keep-rule + compose (651)

Adds canonical-server preference, list-position tiebreak, three-way
duplicate, no-op, and numeric/by-id compose cases.

Co-Authored-By: Claude Opus 4 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Wire the dedup into `storage.save()`

**Files:**
- Modify: `plugins/router/server/server/lib/storage.py`
- Modify: `plugins/router/server/tests/test_storage.py`

- [ ] **Step 1: Write the failing integration test**

Open `plugins/router/server/tests/test_storage.py` and add this test class at the bottom of the file:

```python
class TestSaveDeduplicatesByHookId:
    """Integration: storage.save() invokes deduplicate_by_hook_id before writing."""

    def test_save_collapses_same_id_dupes_and_logs(
        self, hooks_yaml: Path, caplog
    ):
        from server.lib.models import Hook, HookRegistry
        from server.lib.storage import load, save

        registry = HookRegistry(
            hooks=[
                Hook(
                    id="proj-tracking-flush-on-todo-update",
                    trigger_tool="todo_update",
                    target_tool="tracking_git_flush",
                    server="proj",
                ),
                Hook(
                    id="proj-tracking-flush-on-todo-update",
                    trigger_tool="todo_update",
                    target_tool="tracking_git_flush",
                    server="proj",
                ),
            ]
        )
        with caplog.at_level("WARNING"):
            save(registry, hooks_yaml)

        # File on disk contains only one entry.
        reloaded = load(hooks_yaml)
        assert len(reloaded.hooks) == 1
        assert reloaded.hooks[0].id == "proj-tracking-flush-on-todo-update"

        # A dedup warning was emitted naming the id.
        dedup_msgs = [
            r.message
            for r in caplog.records
            if "hooks.yaml dedup-by-id" in r.message
        ]
        assert len(dedup_msgs) == 1
        assert "proj-tracking-flush-on-todo-update" in dedup_msgs[0]

    def test_save_noop_when_no_duplicates(self, hooks_yaml: Path, caplog):
        from server.lib.models import Hook, HookRegistry
        from server.lib.storage import save

        registry = HookRegistry(
            hooks=[
                Hook(id="a-hook", trigger_tool="t", target_tool="u", server="proj"),
                Hook(id="b-hook", trigger_tool="t", target_tool="v", server="proj"),
            ]
        )
        with caplog.at_level("WARNING"):
            save(registry, hooks_yaml)
        assert not any(
            "hooks.yaml dedup-by-id" in r.message for r in caplog.records
        )
```

- [ ] **Step 2: Run the new test class and verify both fail**

```bash
cd /home/raul/worktrees/cpm/feat-651-router-dedup-guard/plugins/router/server
uv run pytest tests/test_storage.py::TestSaveDeduplicatesByHookId -v
```
Expected: `test_save_collapses_same_id_dupes_and_logs` FAILS (2 hooks written; no warning). `test_save_noop_when_no_duplicates` passes (no dedup → no warning, which matches assertion).

- [ ] **Step 3: Modify `storage.save()` to call the dedup + warn**

Open `plugins/router/server/server/lib/storage.py`. Replace the body of `save()` (around line 139–148) with:

```python
def save(registry: HookRegistry, path: Path | None = None) -> Path:
    """Atomically write the hook registry to YAML. Creates file and parent dirs if needed.

    Before writing, collapses entries sharing the same ``hook.id`` via
    ``HookRegistry.deduplicate_by_hook_id``. If any ids were removed, emits
    a WARNING log naming them so re-accumulation sources are diagnosable.

    Returns the path written to.
    """
    target = path or _HOOKS_FILE
    removed = registry.deduplicate_by_hook_id()
    if removed:
        logger.warning(
            "hooks.yaml dedup-by-id: collapsed duplicate hook_ids: %s",
            ", ".join(sorted(set(removed))),
        )
    data = registry.to_dict()
    content = yaml.dump(data, default_flow_style=False, sort_keys=False)
    _atomic_write(target, content)
    return target
```

- [ ] **Step 4: Run the integration test and verify it passes**

```bash
cd /home/raul/worktrees/cpm/feat-651-router-dedup-guard/plugins/router/server
uv run pytest tests/test_storage.py::TestSaveDeduplicatesByHookId -v
```
Expected: both tests PASS.

- [ ] **Step 5: Commit the save() wiring**

```bash
cd /home/raul/worktrees/cpm/feat-651-router-dedup-guard
git add plugins/router/server/server/lib/storage.py plugins/router/server/tests/test_storage.py
git commit -m "$(cat <<'EOF'
fix(router): dedup-by-hook_id in storage.save (651)

save() now calls deduplicate_by_hook_id before serializing and emits a
WARNING listing collapsed ids. Because save() is the sole write path,
this guard catches every sync/recovery flow without further wiring.

Co-Authored-By: Claude Opus 4 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Full router test + lint sweep

**Files:** none (verification + fixup only).

- [ ] **Step 1: Run the router plugin's full test suite**

```bash
cd /home/raul/worktrees/cpm/feat-651-router-dedup-guard/plugins/router/server
uv run pytest
```
Expected: all tests pass. No pre-existing test should regress because the dedup is a no-op on unique-id registries, and the existing `test_save_round_trip` / `test_save_overwrites_existing` tests use registries with distinct hook ids.

If a pre-existing test fails, inspect whether it was deliberately constructing a duplicate-id registry (it should not be). Do not suppress the dedup to make the test pass — instead fix the test to use distinct ids.

- [ ] **Step 2: Run ruff + basedpyright**

```bash
cd /home/raul/worktrees/cpm/feat-651-router-dedup-guard/plugins/router/server
uv run ruff check --fix .
uv run ruff format .
uv run basedpyright server/
```
Expected: all three commands exit 0. Any trivial formatting diffs are acceptable; any typing diagnostic must be fixed in the changed files.

- [ ] **Step 3: If any lint/type fixups were needed, commit them**

```bash
cd /home/raul/worktrees/cpm/feat-651-router-dedup-guard
git status --short
# If there are staged changes from ruff --fix or type adjustments:
git add plugins/router/server/
git commit -m "$(cat <<'EOF'
chore(router): ruff/basedpyright fixups for 651 dedup guard

Co-Authored-By: Claude Opus 4 (1M context) <noreply@anthropic.com>
EOF
)"
```
If `git status --short` is empty, skip the commit.

- [ ] **Step 4: Mark todo 651 complete via the MCP tool**

Call `mcp__plugin_proj_proj__todo_complete`:
```json
{"project": "claude-project-manager", "todo_id": "651"}
```

- [ ] **Step 5: Stop**

Hand off to the reviewer / merge flow. Do NOT merge to `dev` automatically.

---

## Self-Review Notes

- Spec coverage: §3 "Design" — Tasks 3 + 5. §3 "Test plan" — Tasks 2, 4, 5. §3 "Files" — all four files touched in matching tasks.
- No placeholders. Every code block is concrete and immediately executable.
- Type consistency: method signature `deduplicate_by_hook_id() -> list[str]` matches spec and is referenced consistently across Task 3 (impl), Task 4 (tests), Task 5 (integration).
- `DEFAULT_SERVER_PORTS` import is added explicitly in Task 3 Step 1.
- Worktree rule: every command is prefixed with the worktree path.
