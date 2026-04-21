# Managed CLAUDE.md: Superpowers Preference + Post-wt_create Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Append two new rule bullets to `managed_section.md` (superpowers-preference + post-wt_create sync), with matching test assertions, so `~/.claude/CLAUDE.md` picks them up on next `claudemd_refresh_managed`.

**Architecture:** `managed_section.md` is a plain-markdown file inside the `_shared/claudemd` Python package, loaded into the `MANAGED_SECTION` module constant at import time. Rules are append-only bullets in a single `<!-- claude-project-manager:start --> ... <!-- claude-project-manager:end -->` fenced block. Tests in `plugins/_shared/tests/test_claudemd_package.py` assert substring presence — new rules need matching substring assertions in the same style.

**Tech Stack:** Python 3.13 (`_shared` package), pytest, uv-managed deps, pre-commit hooks (ruff + basedpyright). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-04-21-managed-claudemd-superpowers-wt-cleanup-design.md`

**Todos:** 684, 685

---

## File Structure

**Modify:**
- `plugins/_shared/claudemd/managed_section.md` — append 2 bullets before the end marker.
- `plugins/_shared/tests/test_claudemd_package.py` — add 2 test functions in `TestManagedSectionContent`.

**No new files.** No `wt_create` code change. No new MCP tools or skills.

---

## Task 1: Test for the superpowers-preference bullet (684)

**Files:**
- Modify: `plugins/_shared/tests/test_claudemd_package.py` (append inside `class TestManagedSectionContent`)

- [ ] **Step 1: Write the failing test**

Append inside the `TestManagedSectionContent` class (after `test_sub_task_nesting`, before `test_managed_section_still_has_preexisting_rules`):

```python
    def test_prefer_superpowers_rule(self):
        assert "Prefer superpowers skills" in MANAGED_SECTION
        assert 'enabledPlugins["superpowers@superpowers-marketplace"]' in MANAGED_SECTION
        assert "superpowers:brainstorming" in MANAGED_SECTION
        assert "superpowers:systematic-debugging" in MANAGED_SECTION
        assert "superpowers:verification-before-completion" in MANAGED_SECTION
        assert (
            "fall back silently" in MANAGED_SECTION
            or "falls back silently" in MANAGED_SECTION
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run from the worktree root:

```bash
uv run --project plugins/_shared pytest plugins/_shared/tests/test_claudemd_package.py::TestManagedSectionContent::test_prefer_superpowers_rule -v
```

Expected: FAIL with assertion error on `"Prefer superpowers skills" in MANAGED_SECTION` (substring not yet in the managed block).

- [ ] **Step 3: Add the rule bullet to `managed_section.md`**

Edit `plugins/_shared/claudemd/managed_section.md`. Insert this bullet *before* the closing `<!-- claude-project-manager:end -->` marker (after the current revdiff bullet):

```markdown
- **Prefer superpowers skills when available** — If `enabledPlugins["superpowers@superpowers-marketplace"] == true` in `~/.claude/settings.json`, invoke applicable `superpowers:*` skills instead of ad-hoc workflows. Typical triggers: multi-step implementation → `superpowers:brainstorming` → `superpowers:writing-plans` → `superpowers:executing-plans`; bugs or unexpected behavior → `superpowers:systematic-debugging`; claiming work complete → `superpowers:verification-before-completion`; finishing a dev branch → `superpowers:finishing-a-development-branch`. If the plugin is not installed, fall back silently to built-in behavior. Does not override explicit user instructions.
```

Exact insertion point: between the current line 16 (`- **Revdiff-routed spec/plan review** — ...`) and the closing marker on line 17 (`<!-- claude-project-manager:end -->`). The bullet goes on its own line; the file must still end with a single newline after the closing marker.

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run --project plugins/_shared pytest plugins/_shared/tests/test_claudemd_package.py::TestManagedSectionContent::test_prefer_superpowers_rule -v
```

Expected: PASS.

- [ ] **Step 5: Run the file-load round-trip test to confirm no marker corruption**

```bash
uv run --project plugins/_shared pytest plugins/_shared/tests/test_claudemd_package.py::test_managed_section_loaded_from_file plugins/_shared/tests/test_claudemd_package.py::test_managed_section_markers_at_boundaries -v
```

Expected: PASS (both). This catches stray whitespace or missing newline after the closing marker.

- [ ] **Step 6: Commit**

```bash
git add plugins/_shared/claudemd/managed_section.md plugins/_shared/tests/test_claudemd_package.py
git commit -m "feat(684): managed CLAUDE.md rule for preferring superpowers skills

Installs when superpowers plugin is enabled in settings.json. Enumerates
common triggers (brainstorming, writing-plans, systematic-debugging,
verification-before-completion). Falls back silently when not installed.

Test assertions added in TestManagedSectionContent."
```

---

## Task 2: Test for the post-wt_create-sync bullet (685)

**Files:**
- Modify: `plugins/_shared/tests/test_claudemd_package.py` (append inside `class TestManagedSectionContent`)

- [ ] **Step 1: Write the failing test**

Append inside `TestManagedSectionContent`, immediately after `test_prefer_superpowers_rule` from Task 1:

```python
    def test_post_wt_create_sync_rule(self):
        assert "Sync worktree to remote after" in MANAGED_SECTION
        assert "wt_create" in MANAGED_SECTION
        assert "git fetch origin" in MANAGED_SECTION
        assert "git reset --hard origin/" in MANAGED_SECTION
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run --project plugins/_shared pytest plugins/_shared/tests/test_claudemd_package.py::TestManagedSectionContent::test_post_wt_create_sync_rule -v
```

Expected: FAIL on `"Sync worktree to remote after" in MANAGED_SECTION`.

- [ ] **Step 3: Add the rule bullet to `managed_section.md`**

Edit `plugins/_shared/claudemd/managed_section.md`. Insert this bullet immediately after the superpowers-preference bullet added in Task 1, still before the closing `<!-- claude-project-manager:end -->` marker:

```markdown
- **Sync worktree to remote after `wt_create`** — After a successful `mcp__plugin_worktree_worktree__wt_create` call, run `git fetch origin` and then `git reset --hard origin/<base-branch>` inside the returned `worktree_path` before any edits or agent dispatch. `wt_create` already resets to local HEAD and cleans untracked files, but does not fetch — the local base branch may lag `origin/<base>`. This ensures agents start from the latest remote state. Skip only when the worktree was created explicitly from a non-remote branch (e.g. a local-only experimental branch).
```

Final file tail after both edits should look like:

```markdown
- **Revdiff-routed spec/plan review** — ...
- **Prefer superpowers skills when available** — ...
- **Sync worktree to remote after `wt_create`** — ...
<!-- claude-project-manager:end -->
```

(One trailing newline after the closing marker.)

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run --project plugins/_shared pytest plugins/_shared/tests/test_claudemd_package.py::TestManagedSectionContent::test_post_wt_create_sync_rule -v
```

Expected: PASS.

- [ ] **Step 5: Run the full test file to confirm no regressions**

```bash
uv run --project plugins/_shared pytest plugins/_shared/tests/test_claudemd_package.py -v
```

Expected: all tests PASS, including the pre-existing rule assertions and the revdiff bullet test.

- [ ] **Step 6: Commit**

```bash
git add plugins/_shared/claudemd/managed_section.md plugins/_shared/tests/test_claudemd_package.py
git commit -m "feat(685): managed CLAUDE.md rule for post-wt_create remote sync

After wt_create, run 'git fetch origin' + 'git reset --hard origin/<base>'
inside the worktree. wt_create already resets to local HEAD but does not
fetch, so worktrees can start stale. Managed-rule approach per spec
(no wt_create code change)."
```

---

## Task 3: Refresh the live `~/.claude/CLAUDE.md` and verify end-to-end

**Files:** none edited. Runs the existing refresh flow against the user's actual `~/.claude/CLAUDE.md`.

- [ ] **Step 1: Refresh the managed block**

From the worktree root:

```bash
uv run --project plugins/proj python -c "from server.tools.context import claudemd_refresh_managed; print(claudemd_refresh_managed())"
```

Expected: output confirms the managed block was updated (refresh may return "unchanged" if the user already ran it via `/proj:claudemd-refresh` — either is fine as long as no exception).

- [ ] **Step 2: Verify the new bullets are present in `~/.claude/CLAUDE.md`**

```bash
grep -c "Prefer superpowers skills when available" ~/.claude/CLAUDE.md
grep -c "Sync worktree to remote after" ~/.claude/CLAUDE.md
```

Expected: each command prints `1`.

- [ ] **Step 3: Verify markers are intact and exactly once each**

```bash
grep -c '<!-- claude-project-manager:start -->' ~/.claude/CLAUDE.md
grep -c '<!-- claude-project-manager:end -->' ~/.claude/CLAUDE.md
```

Expected: each prints `1`. More than one of either means marker corruption — stop and investigate.

- [ ] **Step 4: Run the full `_shared` test suite as a final gate**

```bash
uv run --project plugins/_shared pytest plugins/_shared/tests/ -v
```

Expected: all tests PASS. No commit needed in this task (verification only).

---

## Self-Review (done)

- **Spec coverage:** Spec §"New bullet 1" → Task 1. Spec §"New bullet 2" → Task 2. Spec §"Test additions" → Steps 1 in Tasks 1 + 2. Spec §"Placement" → Step 3 in each task explicitly documents the insertion point + final file tail. Spec §"Rollout" step 4 (`/proj:claudemd-refresh`) → Task 3.
- **Placeholder scan:** no TBDs, no "add validation", all code blocks concrete, all commands runnable with expected output.
- **Type consistency:** `MANAGED_SECTION` (module constant), `TestManagedSectionContent` (class name), method names match the file's style. `enabledPlugins["superpowers@superpowers-marketplace"]` spelling verified against `~/.claude/settings.json`.
- **Scope check:** single spec, two append-only edits plus a verification task. Well within one plan.
