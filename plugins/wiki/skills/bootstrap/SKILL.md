---
name: bootstrap
description: Bulk-import many sources into the wiki. Proj-aware — auto-enumerates proj sources (NOTES.md, sessions/*, todos/*) when proj is loaded; otherwise prompts for a directory or file list. Dispatches a team of ingest subagents in parallel, runs final cross-ref sweep. Use when user says "bootstrap wiki", "wiki:bootstrap", "import project docs into wiki".
allowed-tools: mcp__plugin_wiki_wiki__wiki_scope_detect, mcp__plugin_wiki_wiki__wiki_index_read, mcp__plugin_wiki_wiki__wiki_index_rebuild, mcp__plugin_wiki_wiki__wiki_log_append, mcp__plugin_wiki_wiki__wiki_search_index_refresh, AskUserQuestion, Task, TeamCreate, Bash, Read
argument-hint: "[<directory-or-file-list>]"
---

> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Bulk import. `$ARGUMENTS` = optional directory path or file-list file.

**Reference docs** (used via the ingest protocol):
- `../ingest/references/source-readers.md`
- `../ingest/references/dedup-protocol.md`
- `../ingest/references/subagent-prompt.md`

**1.** Sanity check — confirm wiki is initialized:
- `mcp__plugin_wiki_wiki__wiki_index_read` → read catalog.
- `content == ""` → stop: "Wiki not initialized or empty. Run `/wiki:init` first, then retry."

**2.** `mcp__plugin_wiki_wiki__wiki_scope_detect` → `scope` + `proj_present`.
- `proj_present == true` AND `$ARGUMENTS` is empty → **proj-aware mode** (step 3).
- Else → **standalone mode** (step 4).

**3.** (proj-aware) Enumerate proj sources:
- Determine tracking dir: read `~/.claude/proj.yaml::tracking_dir` via `Read` (default `~/projects/tracking`).
- Determine active project name via `wiki_scope_detect` (`scope` = `project:<name>`, extract `<name>`).
- If no active project → fall back to standalone mode (jump to step 4 w/ `AskUserQuestion` prompt).

> **Note:** proj-aware enumeration depends on the active-project being persisted in `~/.claude/proj-session.yaml` (file-backed per todo 705). Session-only setups (proj loaded via `/proj:load` but `proj-session.yaml` not written) will fall back to standalone mode here. If you expected proj-aware mode + got standalone, run `/proj:load <name>` again to re-persist, then retry `/wiki:bootstrap`.
- Scan `<tracking_dir>/<project>/`:
    - `NOTES.md` (if exists)
    - `sessions/*.md` (use `Bash find <tracking_dir>/<project>/sessions -name "*.md" -type f`)
    - `todos/*/requirements.md` + `todos/*/research.md` (use `Bash find <tracking_dir>/<project>/todos \( -name "requirements.md" -o -name "research.md" \) -type f`)
    - `docs/*.md`, `overhaul-requirements.md`, etc. (use `Bash find <tracking_dir>/<project> -maxdepth 2 -name "*.md" -type f`)
- Read `proj.yaml::sync.wiki.bootstrap_docs` (if present) → append user-declared doc paths.
- Group sources by category:
    - `NOTES.md` + top-level docs → "narrative-sources"
    - `sessions/*.md` → "session-sources"
    - `todos/*/*.md` → "todo-sources"
- Skip to step 5.

**4.** (standalone) Prompt for sources:
- If `$ARGUMENTS` is a directory path → scan for `*.md` files: `Bash find <dir> -name "*.md" -type f`.
- Else prompt via `AskUserQuestion`:
    - Question: "What sources to bootstrap?"
    - Options:
        - `directory` — scan a directory for *.md. Prompt for path (Other field).
        - `file-list` — paste a newline-separated list of source specs.
        - `cancel` — exit.
- Group all files as a single "mixed-sources" bucket (no per-category split in standalone mode).

**5.** Read wiki config for subagent prompts (same shape as `/wiki:ingest` step 5):
- `Read ~/.claude/wiki.yaml` → extract `session_ingest.section_map`.
- `Read ~/.claude/wiki/config.yaml` → extract `profile`, `categories`, `required_frontmatter`.
- Bundle into a single JSON string (the "CONFIG" placeholder used in agent prompts below).

**6.** `Read ../ingest/references/subagent-prompt.md` → the template.

**7.** Dispatch subagent team via `TeamCreate` + per-agent `Task`:
- One agent per source bucket from step 3/4.
- For each bucket, construct a per-agent prompt by taking the template from step 6 + substituting `{source}` → a BATCH-SOURCES list (one path per line), `{scope}` → scope from step 2, `{wiki_config}` → JSON from step 5. Prepend the batch-iteration prologue:

```
You are ingesting MULTIPLE sources for a bootstrap batch. For each source in the
BATCH-SOURCES list below, run the full single-source ingest protocol sequentially
(NOT in parallel — the same subagent handles the batch to avoid duplicate-write
races on shared pages).

BATCH-SOURCES (one per line):
<list-of-sources-for-this-bucket>

After all sources processed, return JSON: {
  per_source: [{source, status, pages_created, pages_updated, contradictions}],
  totals: {created: N, updated: N, cross_refs: N, contradictions: N},
}
```

- `TeamCreate` size = number of source buckets (usually 2-4 agents for proj-aware, 1 for standalone).

**8.** Wait for team completion. Aggregate per-agent summaries.

**9.** Final cross-ref sweep (post-team):
- Parallel agents may have written pages with stale `links_to` (agent A didn't know agent B created `[[concept-X]]`).
- Dispatch ONE cleanup subagent via `Task` w/ prompt:

```
You are the post-bootstrap cross-ref sweeper. Walk every page under
~/.claude/wiki/pages/. For each page:
1. mcp__plugin_wiki_wiki__wiki_page_get to read frontmatter + body.
2. Scan body for noun phrases matching other page titles/aliases via
   mcp__plugin_wiki_wiki__wiki_link_resolve.
3. Insert [[wikilinks]] inline for any new matches.
4. Update links_to frontmatter via mcp__plugin_wiki_wiki__wiki_page_write(mode="update").
Return JSON: {pages_touched: N, cross_refs_added: N}.
```

**10.** `mcp__plugin_wiki_wiki__wiki_search_index_refresh` → rebuild BM25 sidecar to include new pages (so first `/wiki:query` after bootstrap doesn't waste time on a full rebuild).

**11.** `mcp__plugin_wiki_wiki__wiki_index_rebuild` → refresh index.md w/ new pages + Recent section.

**12.** `mcp__plugin_wiki_wiki__wiki_log_append` w/ `action=bootstrap`, `title=<scope>`, `body=<summary>`.

**13.** Render summary:

```
## Bootstrap complete

**Scope**: `<scope>` (proj-aware | standalone)
**Sources processed**: <N>

**Pages created** (<N>):
<group by category, summary>

**Pages updated** (<N>):
<group by category>

**Cross-refs added** (initial pass + sweep): <N>
```

If `contradictions_flagged` non-empty: list + suggest `/wiki:query <slug>` to resolve.

Close with: "Log entry appended. Index + BM25 refreshed. Run `/wiki:lint` to check integrity."

## Err handling

- Wiki disabled / missing → "Wiki not initialized. Run `/wiki:init` first." + stop.
- Proj-aware mode but no active project → fall back to standalone mode w/ prompt.
- Any subagent in the team fails → other agents continue; report failure per-source in the summary. Partial success is OK.
- Cross-ref sweeper fails → warn but don't roll back — per-page `links_to` may be incomplete; user can re-run `/wiki:lint` to find broken links.
- Empty source list (standalone directory has no .md files) → stop: "No .md files found at `<path>`. Nothing to bootstrap."
