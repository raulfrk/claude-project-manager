# Managed CLAUDE.md: Superpowers Preference + Post-wt_create Sync

**Todos:** 684, 685
**Target file:** `plugins/_shared/claudemd/managed_section.md`
**Test file:** `plugins/_shared/tests/test_claudemd_package.py`
**Date:** 2026-04-21

## Context

`managed_section.md` is injected into `~/.claude/CLAUDE.md` between `<!-- claude-project-manager:start -->` / `<!-- claude-project-manager:end -->` markers by `claudemd_refresh_managed`. It currently holds 11 rule bullets. Two new rules are needed:

- **684** — Prefer superpowers skills where appropriate, gated on the plugin being installed.
- **685** — After creating a worktree, sync it to the remote (fetch + reset --hard to `origin/<base>`).

## Design

### New bullet 1 — Prefer superpowers skills (684)

**Rule text (to append as a bullet):**

> - **Prefer superpowers skills when available** — If `enabledPlugins["superpowers@superpowers-marketplace"] == true` in `~/.claude/settings.json`, invoke applicable `superpowers:*` skills instead of ad-hoc workflows. Typical triggers: multi-step implementation → `superpowers:brainstorming` → `superpowers:writing-plans` → `superpowers:executing-plans`; bugs or unexpected behavior → `superpowers:systematic-debugging`; claiming work complete → `superpowers:verification-before-completion`; finishing a dev branch → `superpowers:finishing-a-development-branch`. If the plugin is not installed, fall back silently to built-in behavior. This rule does not override explicit user instructions.

**Why install-gated:** Superpowers is not a hard dependency of this marketplace. The rule must no-op cleanly on setups that don't have it. Precedent: the existing revdiff bullet (line 16) uses the same `enabledPlugins[...] == true` check.

**Why enumerate triggers:** The `superpowers:using-superpowers` skill itself enforces the "1% rule" at skill-invocation time, but the managed block is loaded *before* any skill runs. Naming the common triggers in the managed block nudges Claude toward calling `Skill` in the first place — which is what then loads `using-superpowers` and its stricter rules.

### New bullet 2 — Post-wt_create sync (685)

**Rule text (to append as a bullet):**

> - **Sync worktree to remote after `wt_create`** — After a successful `mcp__plugin_worktree_worktree__wt_create` call, run `git fetch origin` followed by `git reset --hard origin/<base-branch>` inside the returned `worktree_path` before any edits or agent dispatch. `wt_create` already resets to local HEAD + cleans untracked, but does not fetch — the local base branch may lag `origin/<base>`. This ensures agents start from the latest remote state. Skip only when the worktree was created explicitly from a non-remote branch (e.g. a local-only experimental branch).

**Why not modify `wt_create` directly:** User chose the managed-rule path (workflow-level, not code-level). Rationale: `wt_create` has callers beyond Claude (scripts, tests, other tools) that may not want a remote round-trip. Keeping the cleanup as a Claude-side discipline preserves `wt_create`'s current contract. A future code change could still be made if friction appears.

**Why `reset --hard origin/<base>`:** The worktree is created from a local ref. If `main` / `dev` hasn't been fetched recently, the worktree starts stale. Fetching + hard-resetting the worktree's HEAD to `origin/<base>` guarantees it matches what CI will see.

### Placement

Append both bullets to the end of the existing "Claude Project Manager Rules" list in `managed_section.md`, after the current bullet 16 (revdiff-routed review). Order: 684 first, 685 second. Rationale: no logical grouping forces a specific position; append-only preserves diff minimality and matches how the list has grown historically.

### Test additions

In `plugins/_shared/tests/test_claudemd_package.py`, add assertions in the style of the existing `test_managed_section_contains_required_rules` block:

```python
# 684 — superpowers preference
assert "Prefer superpowers skills" in MANAGED_SECTION
assert 'enabledPlugins["superpowers@superpowers-marketplace"]' in MANAGED_SECTION
assert "fall back silently" in MANAGED_SECTION
assert "superpowers:brainstorming" in MANAGED_SECTION
assert "superpowers:systematic-debugging" in MANAGED_SECTION

# 685 — post-wt_create sync
assert "Sync worktree to remote after" in MANAGED_SECTION
assert "git fetch origin" in MANAGED_SECTION
assert "git reset --hard origin/" in MANAGED_SECTION
```

Existing `test_managed_section_loaded_from_file` covers round-trip file ↔ constant equality and doesn't need changes.

## Non-goals

- No change to `wt_create` implementation.
- No new MCP tool, no new skill, no new config key.
- No change to `~/.claude/CLAUDE.md` refresh flow (existing `claudemd_refresh_managed` will pick up new content on next `/proj:claudemd-refresh`).
- No coverage of worktrees created outside `wt_create` (native `git worktree add`, external tools).

## Open questions

None. Install-check pattern already established by the revdiff bullet; placement is appendonly; test file already asserts per-rule substrings.

## Rollout

1. Edit `managed_section.md` → append two bullets.
2. Edit `test_claudemd_package.py` → add substring assertions.
3. Run `pytest plugins/_shared/tests/test_claudemd_package.py` → verify green.
4. User runs `/proj:claudemd-refresh` to pick up new bullets in their live `~/.claude/CLAUDE.md`.
