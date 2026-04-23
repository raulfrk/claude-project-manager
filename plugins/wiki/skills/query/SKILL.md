---
name: query
description: Query the Karpathy LLM wiki. Reads index + runs BM25 on large wikis, drills into candidate pages, synthesizes a cited answer. Use when user says "wiki query", "search wiki", "what do we know about X", "wiki:query <question>".
allowed-tools: mcp__plugin_wiki_wiki__wiki_index_read, mcp__plugin_wiki_wiki__wiki_page_list, mcp__plugin_wiki_wiki__wiki_page_get, mcp__plugin_wiki_wiki__wiki_search_bm25, mcp__plugin_wiki_wiki__wiki_link_resolve, mcp__plugin_wiki_wiki__wiki_scope_detect
argument-hint: "<question> [--scope <scope>] [--raw] [--file-back]"
context: fork
agent: general-purpose
---

> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Answer user's question from wiki. `$ARGUMENTS` = full query string; may contain flags.

**1.** Parse `$ARGUMENTS`:
- Extract `--scope <val>`, `--raw`, `--file-back` flags.
- Remaining text = question.
- Empty question → stop: "Question required. Usage: `/wiki:query <your question>`."

**2.** `mcp__plugin_wiki_wiki__wiki_scope_detect` → get scope info (informational; default query reads all scopes).

**3.** `mcp__plugin_wiki_wiki__wiki_index_read` → get catalog (content + categories + recent).
- Empty wiki → stop: "Wiki empty. Add content via `/wiki:ingest <source>` first (Phase 3)."

**4.** Pick retrieval path:
- Total pages (sum of category counts) <~100 → **index-only path**: reason over index entries to pick 3–10 candidate slugs by title/category/summary match.
- Total pages ≥100 → **BM25 path**: `mcp__plugin_wiki_wiki__wiki_search_bm25` w/ `query=<extracted-keywords>`, `limit=20`. Use returned hits as candidates.
- If `--scope` flag passed: apply to BM25 call OR filter index-only candidates post-hoc.

**5.** Read each candidate via `mcp__plugin_wiki_wiki__wiki_page_get(slug, category)`:
- If candidate references `[[wikilink]]` or `[[page#section]]` that adds info → resolve via `wiki_link_resolve` + `wiki_page_get` + read too.

**6.** Synthesize answer (markdown):
- Every claim → cite specific `[[page-slug]]` refs. Quote exact text where possible.
- If wiki has nothing relevant → say so + suggest `/wiki:ingest <source>`.

**7.** Flag handling:
- `--raw` → print candidate pages + excerpts, skip synthesis step.
- `--file-back` → after synthesis, if answer is durable + high-value, propose new `query-summary` page via `wiki_page_write` (confirm w/ user first).

**8.** Render output:

```
## Answer

<synthesized markdown>

## Citations

| Slug | Category | Excerpt | Last ingested |
|------|----------|---------|---------------|
| [[hooks-architecture]] | concepts | "Centralized MCP-to-MCP registry..." | 2026-04-23 |
| ...

## Pages read

N pages (via BM25 | index-only)
```

## Err handling

- Wiki disabled / missing → "Wiki not initialized. Run `/wiki:init` first." + stop.
- `wiki_index_read` returns empty → as step 3.
- `wiki_search_bm25` returns empty hits → fall back to index-only path.
- No relevant content found → "No pages relevant to the query. Ingest source via `/wiki:ingest`."
