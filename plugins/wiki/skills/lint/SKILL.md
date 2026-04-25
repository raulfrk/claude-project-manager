---
name: lint
description: Run Tier-1 + Tier-2 lint on wiki. Tier-1: orphans / broken links / section refs / category violations / stale / schema / duplicates. Tier-2: contradictions / deprecation / missing cross-refs / category clusters (LLM-driven). Interactive fix prompts per finding. Use `--tier=1|2|all`.
allowed-tools: mcp__plugin_wiki_wiki__wiki_lint_orphans, mcp__plugin_wiki_wiki__wiki_lint_broken_links, mcp__plugin_wiki_wiki__wiki_lint_broken_section_refs, mcp__plugin_wiki_wiki__wiki_lint_category_violations, mcp__plugin_wiki_wiki__wiki_lint_stale, mcp__plugin_wiki_wiki__wiki_lint_schema, mcp__plugin_wiki_wiki__wiki_lint_duplicates, mcp__plugin_wiki_wiki__wiki_page_write, mcp__plugin_wiki_wiki__wiki_page_delete, mcp__plugin_wiki_wiki__wiki_page_get, mcp__plugin_wiki_wiki__wiki_log_append, AskUserQuestion, Task, Agent, Read, Bash, Glob
argument-hint: "[--tier=1|2|all]"
---

> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Run Tier-1 lint + interactive fix flow.

## Architecture (tier-1 vs tier-2)

Tier-1 lint checks (orphans, broken-links, broken-section-refs, category-violations, stale, schema, duplicates) → Python-driven, registered as MCP tools (`wiki_lint_*`), tested. Tier-2 checks (contradictions, deprecation, missing-cross-refs, category-clusters, section-map-drift) → prose-only — each lives at `references/tier2-<check-name>.md` as an LLM subagent template. No Python helpers for tier-2; no dual-impl. See [[wiki-plugin]] for the architectural principle (decided 2026-04-25 per todo 737).

## Execution

**1.** Call all 7 Tier-1 lint tools in parallel:
- `wiki_lint_orphans`
- `wiki_lint_broken_links`
- `wiki_lint_broken_section_refs`
- `wiki_lint_category_violations`
- `wiki_lint_stale`
- `wiki_lint_schema`
- `wiki_lint_duplicates`

**2.** Aggregate findings. Count total per check. Render summary table:

| Check | Findings |
|-------|----------|
| Orphans | N |
| Broken links | N |
| Broken section refs | N |
| Category violations | N |
| Stale (>90d) | N |
| Schema violations | N |
| Duplicate slugs | N |

Zero findings → print "Wiki clean. No lint issues." + stop.

**3.** Parse `$ARGUMENTS` for `--tier` flag:
 - `--tier=1` (default) → skip to step 6 (present Tier-1 only).
 - `--tier=2` → skip Tier-1 summary; run only Tier-2 checks.
 - `--tier=all` → run both.

**4.** Tier-2 dispatch (`--tier=2` or `--tier=all`):
 - Read each `plugins/wiki/skills/lint/references/tier2-*.md` template via `Read`.
 - Substitute `{wiki_dir}` (read from `~/.claude/wiki.yaml::wiki_dir`) + `{current_categories}` (read from `~/.claude/wiki/config.yaml::categories`).
 - Resolve `/proj:save` SKILL.md path (for drift check):
    1. Glob `~/.claude/plugins/marketplaces/*/cpm/proj/skills/save/SKILL.md` → first match.
    2. Else `plugins/proj/skills/save/SKILL.md` (repo-local dev checkout).
    3. Else empty string (drift check will warn + skip).
 - Read `~/.claude/wiki.yaml` path (pass to drift agent as `{wiki_yaml_path}`).
 - Dispatch 5 parallel `Agent` calls in a single message, each `subagent_type: general-purpose` w/ `run_in_background: true`:
    - `contradictions`: prompt from `tier2-contradictions.md`
    - `deprecation`: prompt from `tier2-deprecation.md`
    - `cross-refs`: prompt from `tier2-missing-cross-refs.md`
    - `clusters`: prompt from `tier2-category-clusters.md`
    - `drift`: prompt from `tier2-section-map-drift.md` w/ `{wiki_yaml_path}` + `{save_skill_path}` substituted
 - Wait for all 5 background agents to complete (each notifies on finish). Collect JSON findings.

**5.** Aggregate Tier-1 + Tier-2 findings. Present combined summary:

| Tier | Check | Findings |
|------|-------|----------|
| 1 | Orphans | N |
| 1 | Broken links | N |
| 1 | Broken section refs | N |
| 1 | Category violations | N |
| 1 | Stale (>90d) | N |
| 1 | Schema violations | N |
| 1 | Duplicate slugs | N |
| 2 | Contradictions | N |
| 2 | Deprecation candidates | N |
| 2 | Missing cross-refs | N |
| 2 | Category clusters | N |
| 2 | Section-map drift | N |

**6.** Per finding (grouped by check type), present + prompt user via `AskUserQuestion`:
- Question: `[<check>] <page-slug>: <detail>. Fix?`
- Options: `fix` / `skip`
- (Note: `file-todo` disabled in Phase 2; only `fix` + `skip` offered.)

**7.** If user picks `fix`:

- **Orphan**: offer `delete page` (via `wiki_page_delete`) OR `leave` (mark intentional).
- **Broken link**: offer `remove ref from source links_to` (via `wiki_page_get` → edit frontmatter → `wiki_page_write`) OR `create target page stub` (via `wiki_page_write`, mode=create, empty body, minimal frontmatter).
- **Broken section ref**: offer `change ref to page-only` (drop `#section`) OR `add missing heading to target page`.
- **Category violation**: offer `move page to configured category` (delete + recreate in new dir OR prompt user for target) OR `add category to config.yaml`.
- **Stale**: offer `refresh page` (prompt for updated `last_ingested`) OR `archive`.
- **Schema violation**: offer `auto-fix missing fields w/ defaults` (e.g. `sources: []`, `tags: []`, `last_ingested: <now>`) OR `skip`.
- **Duplicate**: print paths + ask user to rename one manually. No auto-fix.
- **Contradiction**: offer `edit page A body` (via `wiki_page_get` + edit + `wiki_page_write(mode=update)`) OR `edit page B body` OR `add reconciliation note` (append to one page) OR `skip`.
- **Deprecation candidate**: apply `recommended_action` from agent JSON: `delete` (via `wiki_page_delete`) OR `mark_deprecated` (set frontmatter `deprecated: true` + optionally `deprecated_in_favor_of: <slug>`) OR `merge_into:<target>` (copy body + links to target via `wiki_page_get` + `wiki_page_write(mode=update)` on target, then delete).
- **Missing cross-ref**: insert `[[wikilink]]` into source page body via `wiki_page_get` + text edit + `wiki_page_write(mode=update)` + update frontmatter `links_to` list.
- **Category cluster**: confirm cluster name + target pages. Update `~/.claude/wiki/config.yaml::categories` to add new category. Move each page via `wiki_page_delete` + `wiki_page_write(mode=create)` in new dir. Confirm full migration before any moves fire.
- **Section-map drift**: inform user of specific missing keys/H2s. Offer "edit wiki.yaml" (open file for user to add missing section_map key) OR "skip". No auto-fix — user must decide category mapping for new/removed keys.

**8.** After all findings processed: `wiki_log_append` w/ `action=lint`, `title="full" | "tier-2"`, `body="<N> fixed, <M> skipped"`.

**9.** Print final summary:
```
Lint complete. <N> issues fixed, <M> skipped.
```

## Error Handling

- Wiki disabled / missing → print "Wiki not initialized. Run `/wiki:init` first." + stop.
- Any lint tool error → print err + continue w/ remaining checks.
- Fix tool call fails → print err, mark finding unresolved, continue.
