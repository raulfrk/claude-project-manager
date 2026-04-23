# Managed CLAUDE.md — Wiki + proj_search Knowledge-Source Rule

**Todo**: 710 — Update managed CLAUDE.md to always use new wiki approach + other superpowers methodologies to query for important info for any project or query

**Branch**: `feat/710-managed-claudemd-wiki-query-rules`

**Worktree**: `/home/raul/worktrees/cpm/feat-710-managed-claudemd-wiki-query-rules`

## Goal

Add a managed-block rule that directs Claude to consult durable knowledge stores (`/wiki:query` + `proj_search_knowledge`) before making domain claims, design decisions, or asking the user for information that might already be captured. Escalate to code-search subagents (`Explore`, `general-purpose`) when durable stores come up empty.

Rule fires across all sessions that pick up the updated managed block (via fresh install or `/proj:claudemd-refresh`).

## Motivation

Claude currently defaults to training priors or asking the user when it needs project or domain knowledge. Two durable stores are available:

- **Wiki** (plugin `wiki@claude-project-manager`, branch `feat/688-karpathy-wiki-plugin`) — cross-project curated knowledge; BM25 search over ingested pages; authoritative citations. Tools: `/wiki:query` skill, `wiki_search_bm25`, `wiki_page_get`, `wiki_index_read`, `wiki_scope_detect`, `wiki_link_resolve`.
- **proj_search_knowledge** (proj plugin, always installed when managed block is present) — active-project notes, decisions, research, requirements.

Without an explicit rule, Claude does not invoke either consistently. A managed-block bullet makes the behavior default.

## Design

### Rule placement

Insert the new bullet as the last rule in the managed block, after the **Sync worktree to remote after `wt_create`** bullet and before the closing `<!-- claude-project-manager:end -->` marker.

Placement rationale:
- Topical proximity: retrieval discipline sits next to verification discipline (the parallel `feat/687-691-692-700-bundled-cleanups` branch adds a **Verify before asserting** bullet in the same position). If that branch merges first, the two rules end up adjacent, which is the natural reading order (retrieve → verify).
- Append-only matches precedent: every recent managed-block addition (commits `5d00298`, `6aa2e1b`, `a24936c`) added its new bullet at the end rather than inserting mid-block.

### Exact bullet text

```markdown
- **Wiki + proj_search are primary knowledge sources** — When you need project or domain info, first query `/wiki:query` (skip if wiki plugin disabled), then `mcp__plugin_proj_proj__proj_search_knowledge`, then fall back to `Explore` / `general-purpose` subagents for code-level search. These stores are authoritative; training priors and guesswork are not. Use before making claims, design decisions, or asking the user for information that might already be captured.
```

Substring chosen for the test-pin (next section): `"Wiki + proj_search are primary knowledge sources"` — unique to this bullet, discriminating against all existing neighbors.

### Install gating

- **Wiki part**: gated softly by the rule text itself (`"skip if wiki plugin disabled"`). Claude reads the rule each session; if the `/wiki:query` skill is unavailable (not installed or disabled), the skill invocation will fail cleanly and Claude falls through to `proj_search_knowledge`. The rule does not reference `enabledPlugins["wiki@..."]` explicitly — keeping the bullet short; the "skip if disabled" phrasing is sufficient for Claude to reason about it.
- **proj_search_knowledge part**: not gated. Proj is installed by definition whenever the managed block is present, so `proj_search_knowledge` is always available.
- **Explore / general-purpose**: not gated. These are Claude Code built-ins.

### Testing

Extend `plugins/_shared/tests/test_claudemd_package.py` with a new test method in the existing `TestManagedSectionContent` class:

```python
def test_wiki_proj_search_knowledge_rule(self):
    assert "Wiki + proj_search are primary knowledge sources" in MANAGED_SECTION
    assert "/wiki:query" in MANAGED_SECTION
    assert "mcp__plugin_proj_proj__proj_search_knowledge" in MANAGED_SECTION
    assert "Explore" in MANAGED_SECTION
    assert "general-purpose" in MANAGED_SECTION
```

Also update `test_managed_section_still_has_preexisting_rules` to reference the new rule content for regression coverage — add one assertion line pinning the new bullet's lead phrase.

Test rationale: pins the **discriminating substring** (the lead phrase) + the specific tool names. This mirrors the pattern from the `test_post_wt_create_sync_rule` test which pins `mcp__plugin_worktree_worktree__wt_create` (full MCP tool name) rather than a short substring that might match a neighbor.

### Version bumps

Two version bumps are required because the managed-section content change ships through `plugins/_shared`:

1. **`plugins/_shared/pyproject.toml`**: bump `version` (current `0.4.10` on dev; the parallel `feat/687-691-692-700-bundled-cleanups` branch bumps to `0.4.12`). If the parallel branch merges first, this branch bumps `0.4.12` → `0.4.13`. If this branch merges first, `0.4.10` → `0.4.11`. Decide at merge time.
2. **`plugins/proj/plugin.json` + `.claude-plugin/marketplace.json`**: bump proj `5.1.1` → `5.1.2` (proj is the MCP plugin that exposes `claudemd_refresh_managed` — users pick up the new managed block via refresh or fresh install).

After the `_shared` version bump, regenerate `uv.lock` files across the repo so the `scripts/check_shared_version.py` validator (added in commit `5074a4d` on the parallel branch) passes. The generator pattern is to run `uv lock` from each plugin's `server/` directory and from the repo root. The parallel branch's commit message calls out this regeneration explicitly — if the parallel branch has already merged by the time this branch lands, the validator will already exist on dev and catch any lockfile drift.

### Rollout

1. **Fresh installs**: installer writes the current `MANAGED_SECTION` to `~/.claude/CLAUDE.md` during the managed-block step of the wizard. No installer code change needed; the content file change is picked up automatically.
2. **Existing installs**: users run `/proj:claudemd-refresh` (wraps `mcp__plugin_proj_proj__claudemd_refresh_managed`). The existing `ensure_managed_section` function (in `plugins/_shared/claudemd/claudemd.py`) already does atomic replace — no code change needed.

## Out of scope

- No new MCP tool, no new skill, no new config flag.
- No changes to `/wiki:query`, `proj_search_knowledge`, or the Explore / general-purpose agents.
- No auto-firing hook — rule is read-time guidance, not runtime enforcement.
- No change to installer flow. No change to `proj:claudemd-refresh` skill.

## Risks

- **Soft-fail when wiki plugin is absent**: the rule says `"skip if wiki plugin disabled"` rather than embedding an `enabledPlugins` check. Claude may still attempt `/wiki:query` when the plugin is missing; the failure is a single unrecoverable tool-call error, not data loss, and Claude will fall through to the next step in the priority order. Acceptable trade-off for keeping the bullet compact.
- **Merge conflict with parallel `feat/687-691-692-700-bundled-cleanups`**: both branches add a new bullet at the end of `managed_section.md` and both bump `plugins/_shared` version. Resolution at merge time: (a) keep both new bullets; (b) pick the later `_shared` version and regenerate uv.locks; (c) ensure neither test-pin assertion overlaps. Topical ordering at merge: "Verify before asserting" (687/700) and "Wiki + proj_search" (this branch) sit adjacent at the end in either order — final ordering is a merge-time cosmetic decision.
- **Bullet count growth**: the managed block has 14 bullets on dev today. This change takes it to 15 (or 16 if the parallel branch merges first). Each bullet shipped loads into every project's CLAUDE.md context. The new bullet is ~70 words — within the per-bullet budget observed in neighbors. No mitigation needed at this size.

## Acceptance criteria

- [ ] `plugins/_shared/claudemd/managed_section.md` contains the new bullet at the end, before the `<!-- claude-project-manager:end -->` marker.
- [ ] `plugins/_shared/tests/test_claudemd_package.py` has `test_wiki_proj_search_knowledge_rule` that pins the discriminating substring + all four named tools/skills (`/wiki:query`, `mcp__plugin_proj_proj__proj_search_knowledge`, `Explore`, `general-purpose`).
- [ ] `plugins/_shared/pyproject.toml` version bumped (target depends on merge order with `feat/687-691-692-700-bundled-cleanups`).
- [ ] `plugins/proj/plugin.json` + `.claude-plugin/marketplace.json` proj version bumped `5.1.1` → `5.1.2`.
- [ ] All `uv.lock` files regenerated to pin the new `_shared` version; `scripts/check_shared_version.py` passes (when the parallel branch has merged).
- [ ] Full `_shared` test suite passes: `uv run pytest plugins/_shared/tests/test_claudemd_package.py`.
- [ ] `/proj:claudemd-refresh` applied against a test `CLAUDE.md` atomically replaces the managed block with the new content (manual smoke test on the worktree).

## Open questions

_None._ Design is closed per Q&A answers:
- Trigger scope: broad / "consider as important info source".
- Install gating: wiki-gated (via soft rule text), proj always-on.
- Priority order: wiki → proj_search → Explore.
- Bullet structure: single new bullet.
- Wording: Variant B (short + principle-first).
