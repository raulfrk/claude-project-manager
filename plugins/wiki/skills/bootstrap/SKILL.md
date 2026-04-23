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

**1.** `mcp__plugin_wiki_wiki__wiki_scope_detect` → `scope` + `proj_present`.
- `proj_present == true` AND `$ARGUMENTS` is empty → **proj-aware mode** (step 2).
- Else → **standalone mode** (step 3).

**2.** (proj-aware) Enumerate proj sources:
- Determine tracking dir: read `~/.claude/proj.yaml::tracking_dir` via `Read` (default `~/projects/tracking`).
- Determine active project name via `wiki_scope_detect` (`scope` = `project:<name>`, extract `<name>`).
- If no active project → fall back to standalone mode w/ AskUserQuestion prompt.
- Scan `<tracking_dir>/<project>/`:
    - `NOTES.md` (if exists)
    - `sessions/*.md` (glob via Bash `ls`)
    - `todos/*/requirements.md` + `todos/*/research.md`
    - `docs/*.md`, `overhaul-requirements.md`, etc. (pattern-match any top-level `.md`)
- Read `proj.yaml::sync.wiki.bootstrap_docs` (if present) → append user-declared doc paths.
- Group sources by category:
    - `NOTES.md` + top-level docs → "narrative-sources"
    - `sessions/*.md` → "session-sources"
    - `todos/*/*.md` → "todo-sources"
- Skip to step 4.

**3.** (standalone) Prompt for sources:
- If `$ARGUMENTS` is a directory path → scan for `*.md` files (via `Bash ls <dir>/**/*.md`).
- Else prompt via `AskUserQuestion`:
    - Question: "What sources to bootstrap?"
    - Options:
        - `directory` — scan a directory for *.md. Prompt for path (Other field).
        - `file-list` — paste a newline-separated list of source specs.
        - `cancel` — exit.
- Group all files as a single "mixed-sources" bucket (no per-category split in standalone mode).

**4.** Dispatch subagent team via `TeamCreate` + per-agent `Task`:
- One agent per source bucket from step 2/3.
- Each agent gets a subset of sources from `../ingest/references/subagent-prompt.md` template — with a modification: the prompt lists multiple sources + asks the agent to iterate, running the full ingest protocol per source.
- Per-agent prompt mod:

```
You are ingesting MULTIPLE sources for a bootstrap batch. For each SOURCE below,
run the full single-source ingest protocol sequentially (NOT in parallel — the
same subagent handles the batch to avoid duplicate-write races on shared pages).

SOURCES (one per line):
<list-of-sources-for-this-bucket>

SCOPE: <from step 1>
CONFIG: <same JSON as single-source ingest>

After all sources processed, return JSON: {
  per_source: [{source, status, pages_created, pages_updated, contradictions}],
  totals: {created: N, updated: N, cross_refs: N, contradictions: N},
}
```

- `TeamCreate` size = number of source buckets (usually 2-4 agents for proj-aware, 1 for standalone).

**5.** Wait for team completion. Aggregate per-agent summaries.

**6.** Final cross-ref sweep (post-team):
- Parallel agents may have written pages with stale `links_to` (agent A didn't know agent B created `[[concept-X]]`).
- Dispatch ONE cleanup subagent via `Task` w/ prompt:

```
You are the post-bootstrap cross-ref sweeper. Walk every page under
~/.claude/wiki/pages/. For each page:
1. Use wiki_page_get to read frontmatter + body.
2. Scan body for noun phrases matching other page titles/aliases via
   wiki_link_resolve.
3. Insert [[wikilinks]] inline for any new matches.
4. Update links_to frontmatter via wiki_page_write(mode="update").
Return JSON: {pages_touched: N, cross_refs_added: N}.
```

**7.** `wiki_search_index_refresh` → rebuild BM25 sidecar to include new pages (so first `/wiki:query` after bootstrap doesn't waste time on a full rebuild).

**8.** `wiki_index_rebuild` → refresh index.md w/ new pages + Recent section.

**9.** `wiki_log_append` w/ `action=bootstrap`, `title=<scope>`, `body=<summary>`.

**10.** Render summary:

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
