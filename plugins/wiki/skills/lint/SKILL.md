---
name: lint
description: Run Tier-1 lint on wiki — orphans / broken links / section refs / category violations / stale pages / schema / duplicates. Interactive fix prompts per finding. Use when user says "lint wiki", "wiki:lint", "check wiki health".
allowed-tools: mcp__plugin_wiki_wiki__wiki_lint_orphans, mcp__plugin_wiki_wiki__wiki_lint_broken_links, mcp__plugin_wiki_wiki__wiki_lint_broken_section_refs, mcp__plugin_wiki_wiki__wiki_lint_category_violations, mcp__plugin_wiki_wiki__wiki_lint_stale, mcp__plugin_wiki_wiki__wiki_lint_schema, mcp__plugin_wiki_wiki__wiki_lint_duplicates, mcp__plugin_wiki_wiki__wiki_page_write, mcp__plugin_wiki_wiki__wiki_page_delete, mcp__plugin_wiki_wiki__wiki_page_get, mcp__plugin_wiki_wiki__wiki_log_append, AskUserQuestion
argument-hint: ""
---

> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Run Tier-1 lint + interactive fix flow.

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

**3.** Per finding (grouped by check type), present + prompt user via `AskUserQuestion`:
- Question: `[<check>] <page-slug>: <detail>. Fix?`
- Options: `fix` / `skip`
- (Note: `file-todo` disabled in Phase 2; only `fix` + `skip` offered.)

**4.** If user picks `fix`:

- **Orphan**: offer `delete page` (via `wiki_page_delete`) OR `leave` (mark intentional).
- **Broken link**: offer `remove ref from source links_to` (via `wiki_page_get` → edit frontmatter → `wiki_page_write`) OR `create target page stub` (via `wiki_page_write`, mode=create, empty body, minimal frontmatter).
- **Broken section ref**: offer `change ref to page-only` (drop `#section`) OR `add missing heading to target page`.
- **Category violation**: offer `move page to configured category` (delete + recreate in new dir OR prompt user for target) OR `add category to config.yaml`.
- **Stale**: offer `refresh page` (prompt for updated `last_ingested`) OR `archive`.
- **Schema violation**: offer `auto-fix missing fields w/ defaults` (e.g. `sources: []`, `tags: []`, `last_ingested: <now>`) OR `skip`.
- **Duplicate**: print paths + ask user to rename one manually. No auto-fix.

**5.** After all findings processed: `wiki_log_append` w/ `action=lint`, `title=full`, `body="<N> fixed, <M> skipped"`.

**6.** Print final summary:
```
Lint complete. <N> issues fixed, <M> skipped.
```

## Error Handling

- Wiki disabled / missing → print "Wiki not initialized. Run `/wiki:init` first." + stop.
- Any lint tool error → print err + continue w/ remaining checks.
- Fix tool call fails → print err, mark finding unresolved, continue.
