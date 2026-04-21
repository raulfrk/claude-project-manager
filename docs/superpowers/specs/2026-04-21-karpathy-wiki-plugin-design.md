# Karpathy LLM Wiki Plugin — Design Spec

**Date**: 2026-04-21
**Status**: Design approved; awaiting implementation plan
**Todo**: [688](~/projects/tracking/claude-project-manager/todos.yaml) — "Investigate creating new plugin for cpm around Karpathy's LLM Wiki pattern"
**Source inspiration**: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
**Supersedes**: `~/.claude/projects/-home-raul-projects-claude-project-manager/memory/unified-recall-proposal.md` (2026-03-25, pending)

---

## 1. Overview + motivation

This spec defines a new `wiki` plugin for the cpm marketplace implementing Andrej Karpathy's "LLM Wiki" pattern: a persistent, LLM-maintained markdown knowledge base that compounds over time. Synthesis happens once at ingest time, not repeatedly at query time.

**Problem**: cpm has two parallel knowledge systems that don't interoperate — auto-memory (`~/.claude/projects/*/memory/`, sparse, global-only, 3 entries in claude-project-manager) and proj tracking (`~/projects/tracking/*/`, rich ~450 KB per active project, but only searchable via grep-style `proj_search_knowledge`). Architectural decisions, operational patterns, and cross-project lessons are buried. A prior proposal (`memory/unified-recall-proposal.md`) outlined enhancements to both but is 26 days old + not implemented.

**Opportunity**: Karpathy's wiki pattern unifies this under a single entity-centric knowledge graph w/ well-defined ingest/query/lint semantics. Each concept gets a dedicated page w/ cross-refs; ingest distills sources into those pages; queries synthesize answers from pages via LLM reasoning.

**This spec's scope**: the wiki plugin itself, its MCP surface, skills, integration hooks w/ proj, migration from existing data, + testing approach. Implementation plan is deferred to the follow-on writing-plans phase.

---

## 2. Karpathy's philosophy (fidelity commitments)

The source gist is deliberately abstract. It specifies architectural principles + leaves implementation details to the user. Below: exact Karpathy quotes + how this spec stays faithful.

### 2.1 Three-layer architecture

> *"Raw sources (immutable documents), the wiki (LLM-generated markdown pages with summaries, entity pages, cross-references), and the schema (configuration document defining wiki structure and conventions)."*

**Our fidelity**: sources tracked via frontmatter `sources[*].ref` (raw layer); wiki pages at `~/.claude/wiki/pages/` (wiki layer); `~/.claude/wiki/config.yaml` + this spec (schema layer).

### 2.2 Model-centric synthesis

> *"You ask questions against the wiki. The LLM searches for relevant pages, reads them, and synthesizes an answer with citations."*

> *"When answering a query, the LLM reads the index first to find relevant pages, then drills into them. This works surprisingly well at moderate scale (~100 sources, ~hundreds of pages) and avoids the need for embedding-based RAG infrastructure."*

> *"Drop a source; the LLM reads it, extracts key information, updates 10-15 wiki pages, maintains cross-references, and logs the action."*

**Our fidelity**: all synthesis — ingest distillation, query answering, semantic lint — happens in the LLM, driven by skill prompts. MCP servers never call an LLM. See **§3 Design principle** below.

### 2.3 Content-oriented index

> *"index.md is content-oriented. It's a catalog of everything in the wiki — each page listed with a link, a one-line summary, and optionally metadata like date or source count. Organized by category."*

**Our fidelity**: index.md has categories matching our 5 directories; each entry is `[[page]] — one-line summary`; "Recent (by last_ingested)" sub-section added for temporal recall.

### 2.4 Parseable append-only log

> *"log.md is append-only… if each entry starts with a consistent prefix (e.g. `## [2026-04-02] ingest | Article Title`), the log becomes parseable with simple unix tools."*

**Our fidelity**: log entries use exact pattern `## [YYYY-MM-DD] <action> | <title>` grep-parseable via `grep "^## \["`.

### 2.5 Tooling as optional infrastructure

> *"At some point you may want to build small tools that help the LLM operate on the wiki more efficiently. A search engine over the wiki pages is the most obvious one."*

**Our fidelity**: MCP tools are small + focused persistence + pure-data helpers. No embeddings/vector DB. `qmd`-style BM25 search deferred until wiki grows beyond "moderate scale" (Karpathy's ~100 sources / hundreds of pages).

### 2.6 Where Karpathy is silent + our deliberate choices

| Karpathy | Our choice | Reason |
|---|---|---|
| Does not specify multi-wiki layering | Single wiki w/ `scope` frontmatter tags (not directory split) | Closest to Karpathy's one-wiki model; supports cross-project recall |
| Does not specify directory categories | 5 fixed: `concepts/`, `decisions/`, `references/`, `gotchas/`, `entities/` | Predictability for readers; lint warns-not-rejects |
| Does not specify page frontmatter | Minimal required: `title`, `tags`, `links_to`, `scope`, `sources`, `last_ingested` | Enough metadata for lint + graph walks; light author burden |
| Does not specify wikilink syntax | `[[page-slug]]` (Obsidian-style) | Easier to write; simpler lint for broken links |
| Does not specify query-time scope filtering | Default: read all scopes (Karpathy mode). `--scope project` as escape hatch. | Trust LLM to handle relevance via synthesis |

---

## 3. Design principle: persistence / synthesis boundary

**This is the single most important design decision in this spec.**

> **MCP tools are pure persistence + pure-data queries.** Atomic file I/O, frontmatter parsing, graph walks, date filters. They never call an LLM, never construct prompts, never make external API calls beyond file reads.
>
> **All synthesis happens in the LLM, driven by skill prompts.** Reading sources, extracting concepts, deduping, merging pages, answering questions, detecting contradictions — these are LLM operations. Skills orchestrate them via well-defined MCP primitives.

**Why**: matches Karpathy's philosophy (the LLM does the work; tooling is optional infrastructure). Matches cpm's existing pattern (todo tools are persistence; skills drive logic). Testable in two tiers (deterministic tool tests + LLM-in-loop skill evals). Debuggable — synthesis visible in transcripts, not opaque server code.

**Enforcement**:
- Wiki plugin Python code has zero LLM imports, zero Anthropic/OpenAI SDK calls, zero prompt construction.
- Skills describe operations step-by-step in natural language; call MCP tools for every persistence op.
- Any pull request that puts synthesis inside an MCP tool will be blocked in review.

---

## 4. Architecture

```
┌──────────────────────────────────────────────────────────────┐
│ User invokes skill: /proj:wiki-query "hooks plugin rationale" │
└──────────────┬───────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────┐     ┌──────────────────────────┐
│ plugins/proj/skills/         │     │ plugins/wiki/             │
│  wiki-query/SKILL.md         │     │  server/server/           │
│   1. detect active project   │───▶ │   tools/                  │
│   2. spawn subagent w/       │     │    page.py                │
│      query prompt            │     │    index.py               │
│   3. render answer+citations │     │    log.py                 │
└─────────────────────────────┘     │    lint.py                │
                                     │    scope.py               │
      Router hook fires:             │                           │
      notes_append →                  │  FastMCP server           │
      wiki_log_append                 │  run_dual()               │
                                     └────────┬──────────────────┘
                                              │
                                              ▼
                                     ┌──────────────────────────┐
                                     │ ~/.claude/wiki/           │
                                     │  index.md                 │
                                     │  log.md                   │
                                     │  pages/<category>/*.md    │
                                     │  config.yaml              │
                                     │  .lock                    │
                                     └──────────────────────────┘
```

**Plugins**:
- New `plugins/wiki/` — MCP server w/ persistence + pure-data tools.
- Proj plugin adds thin skills (`/proj:wiki-*`) orchestrating wiki via MCP calls.
- Router hook registered: `notes_append` → `wiki_log_append` (pure-data forwarding).
- Session auto-ingest is skill-integrated inside `/proj:save` (see §8.2 + §9.4); not a router hook.
- Standalone `/wiki:*` skills for non-project contexts (e.g. global-scope gist ingests).

**Wiki plugin does not depend on proj**. Wiki operates standalone for global content. Proj-side skills wrap wiki tools w/ active-project awareness.

**Config** (`~/.claude/proj.yaml` gains `wiki` section):
```yaml
wiki:
  enabled: false                        # default off; user opts in via /proj:wiki-init
  wiki_dir: ~/.claude/wiki
  bootstrap_completed: false
  replace_notes_md: false               # flip to true after bootstrap
  auto_ingest_sessions: false
  capture_notes_as_log: false
  default_scope: auto                   # auto-detects active project
  lint_on_ingest: false
  reingest_cooldown_hours: 24
  bootstrap_docs: []                    # per-project list of design docs to ingest
```

Wiki-local config (`~/.claude/wiki/config.yaml`):
```yaml
schema_version: 1
required_frontmatter: [title, tags, links_to, scope, sources, last_ingested]
categories: [concepts, decisions, references, gotchas, entities]
lint:
  stale_after_days: 90
  orphan_min_page_count: 3              # don't flag orphans in tiny wikis
  contradiction_check: true
```

---

## 5. Storage format + page schema

### 5.1 Directory layout (`~/.claude/wiki/`)

```
~/.claude/wiki/
├── index.md                  # entry point: categorized page catalog + Recent
├── log.md                    # append-only chronological ledger
├── config.yaml               # wiki-local config
├── .lock                     # file lock (fcntl) — ignored by git
├── pages/
│   ├── concepts/             # architecture concepts, patterns, domain ideas
│   ├── decisions/            # architecture decisions w/ rationale
│   ├── references/           # external systems, URLs, docs
│   ├── gotchas/              # operational traps
│   └── entities/             # people, projects, tools
└── attachments/              # optional: binary sources, screenshots
```

Categories are conventions. Lint warns (not rejects) on files outside known category dirs.

### 5.2 Page schema

YAML frontmatter + markdown body:

```markdown
---
title: Hooks plugin architecture
tags: [hooks, plugin, architecture, cpm]
links_to: [router-hook-chain, unix-socket-transport, 2026-03-04-fastmcp-over-pure-mcp]
scope: [project:claude-project-manager]
sources:
  - type: file
    ref: ~/projects/tracking/claude-project-manager/overhaul-requirements.md
    ingested_at: 2026-04-21T10:15:00Z
  - type: url
    ref: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
    ingested_at: 2026-04-21T10:15:00Z
last_ingested: 2026-04-21T10:15:00Z
aliases: [hooks-architecture, hooks-design]
deprecated: false
---

# Hooks plugin architecture

## Overview
...

## Related
- [[router-hook-chain]]
- [[unix-socket-transport]]
```

**Required fields**: `title`, `tags`, `links_to`, `scope`, `sources`, `last_ingested`.

**Optional**: `aliases`, `deprecated`, `deprecated_in_favor_of`, `verified_at`.

**scope values**: `[global]`, `[project:<name>]`, or array combining both.

### 5.3 Wikilinks

Use `[[page-slug]]` syntax. Resolver scans `pages/**/*.md` for matching frontmatter `title` slug or filename. Case-insensitive. Unresolved links surface as broken links in lint.

Aliases: frontmatter `aliases` field enables matching `[[hooks-architecture]]` to `hooks-plugin-architecture.md`.

### 5.4 index.md

Machine-maintained by wiki plugin (via `wiki_index_rebuild` tool). Shape:

```markdown
# Wiki Index

## Concepts (3)
- [[hooks-plugin-architecture]] — Centralized MCP-to-MCP registry w/ schema-based param mapping.
- [[router-hook-chain]] — How hooks fire + evaluate conditions.
- [[unix-socket-transport]] — IPC at `/tmp/claude-cpm-*.sock`.

## Decisions (1)
- [[2026-03-04-fastmcp-over-pure-mcp]] — Why FastMCP + CLI instead of pure MCP.

## References (1)
- [[todoist-api]] — Todoist REST API.

## Gotchas (1)
- [[podman-fqdn-required]] — Podman images need `docker.io/...` prefix.

## Entities (1)
- [[claude-project-manager]] — cpm project.

## Recent (by last_ingested, top 10)
- [[hooks-plugin-architecture]] (2026-04-21)
- [[router-hook-chain]] (2026-04-20)
```

### 5.5 log.md

Append-only. Entries use Karpathy prefix `## [YYYY-MM-DD] <action> | <title>` grep-parseable via `grep "^## \["`.

```markdown
## [2026-04-21] ingest | file:~/projects/tracking/cpm/overhaul-requirements.md
Pages updated: hooks-plugin-architecture, router-hook-chain, unix-socket-transport (3)
Pages created: unix-socket-transport (1)

## [2026-04-21] lint | full
Orphans: 0. Contradictions: 0. Stale (>90d): 2.

## [2026-04-21] note | Finished investigation of wiki plugin scope.
```

Actions: `ingest`, `lint`, `note`, `bootstrap`, `promote`, `delete`.

---

## 6. MCP tools

All tools live in `plugins/wiki/server/server/tools/`. Pure persistence + pure-data queries. No LLM calls.

| Tool | Purpose | Key params | Returns |
|---|---|---|---|
| `wiki_page_write` | Atomic page create/update w/ frontmatter validation | `page` (slug), `frontmatter` (dict), `body` (str), `mode` (create/update/upsert) | `{path, created, updated}` |
| `wiki_page_get` | Read single page | `page` (slug) | `{frontmatter, body}` or `{error: "not_found"}` |
| `wiki_page_list` | List pages w/ filters | `scope_filter`, `category`, `tags`, `linked_from`, `linked_to`, `limit` | `{pages: [{title, slug, category, scope, tags, last_ingested}]}` |
| `wiki_page_delete` | Delete page + update backlinks | `page` | `{deleted, backlinks_updated: []}` |
| `wiki_index_read` | Read index.md | — | `{content, categories, recent}` |
| `wiki_index_rebuild` | Regenerate index.md from pages/ | — | `{entries_by_category, recent_count}` |
| `wiki_log_append` | Append entry to log.md | `action`, `title`, `body` (optional detail) | `{entry}` |
| `wiki_log_read` | Read log entries | `since` (date), `action_filter`, `limit` | `{entries: [{date, action, title, body}]}` |
| `wiki_scope_detect` | Resolve active project → scope tag | — | `{scope: "project:<name>" \| "global"}` |
| `wiki_link_resolve` | Resolve `[[page]]` → file path | `link` (slug or alias) | `{resolved: path \| null, candidates: []}` |
| `wiki_lint_orphans` | Pages w/ 0 inlinks + 0 outlinks | — | `{orphans: [page]}` |
| `wiki_lint_broken_links` | `[[link]]` refs w/ no match | — | `{broken: [{from, link}]}` |
| `wiki_lint_stale` | Pages older than N days | `days` | `{stale: [page]}` |
| `wiki_lint_schema` | Pages violating required frontmatter | — | `{violations: [{page, missing_fields}]}` |
| `wiki_lint_duplicates` | Pages w/ colliding slugs | — | `{duplicates: [[page_a, page_b]]}` |

**Concurrency**: all writes go through a shared file lock (`threading.Lock` + `fcntl.flock` on `~/.claude/wiki/.lock`). Matches `todo_batch_complete` pattern in proj.

**No tool does synthesis.** No `wiki_ingest`, no `wiki_query`, no `wiki_lint_contradictions` MCP tool. Those are skill-driven.

---

## 7. Skills

### 7.1 Proj plugin skills (`plugins/proj/skills/`)

| Skill | Purpose | Notes |
|---|---|---|
| `/proj:wiki-init` | Create `~/.claude/wiki/` + config.yaml + empty index.md + log.md; set `wiki.enabled=true` in proj.yaml | One-time per installation |
| `/proj:wiki-ingest <source>` | Ingest URL / file / "session:<path>" / "note:<text>" into wiki | Auto-injects `scope=project:<active>` |
| `/proj:wiki-query <question>` | Query wiki + synthesize answer w/ citations | No scope filter default; `--scope project` narrows |
| `/proj:wiki-lint` | Run full lint (Tier 1 data + Tier 2 semantic) + interactive fix prompts | On-demand |
| `/proj:wiki-bootstrap` | One-shot bulk import from existing project knowledge (NOTES.md, sessions/, todo req+research, design docs) | Team-orchestrated subagents per source type |
| `/proj:wiki-promote <page>` | Add `global` to page's scope tags | Thin wrapper on `wiki_page_write` |

All skills are LLM-driven — their SKILL.md files contain step-by-step prose prompts describing the synthesis protocol. They call MCP tools for persistence only.

### 7.2 Wiki plugin skills (`plugins/wiki/skills/`)

For standalone use w/o a project context:

| Skill | Wrapper | Notes |
|---|---|---|
| `/wiki:ingest <source>` | → subagent + MCP | scope=global default |
| `/wiki:query <question>` | → subagent + MCP | No scope filter |
| `/wiki:lint` | → subagent + MCP | On-demand |

These skills invoke the same subagent protocols as the proj-side versions; the difference is scope defaulting.

---

## 8. Router hooks

Wiki integrates w/ proj via router hooks for **pure-data operations** (no synthesis). Operations that need LLM synthesis (ingest) are not hookable — they live inside user-invoked skills.

### 8.1 Hookable (pure-data) integrations

```yaml
hooks:
  - id: wiki-log-on-notes-append
    trigger_tool: notes_append
    target_tool: wiki_log_append
    server: wiki
    condition: "wiki.enabled and wiki.capture_notes_as_log"
    param_mapping:
      action: "note"
      title: "{source_result.first_line}"
      body: "{source_result.body}"
    blocking: false
```

This is the only router hook in v1: `notes_append` → `wiki_log_append`. Both are MCP tools. Pure data forwarding. No synthesis.

### 8.2 Non-hookable integrations (session auto-ingest)

Session ingest requires LLM synthesis (read session file → extract concepts/decisions → write pages). Router hooks target MCP tools only; they can't spawn subagents. Two alternatives:

**v1 choice**: `/proj:save` skill itself orchestrates wiki ingest as a final step in its flow. After writing the session file + NOTES.md update, the skill (still in the user's conversation, w/ full LLM access) spawns the ingest subagent. This is skill-level integration, not a router hook. User sees the ingest happening as part of their `/proj:save` output.

**Rationale**: keeps hooks restricted to pure data forwarding. Keeps synthesis in the LLM layer. Preserves the persistence/synthesis boundary (§3).

**v2 (deferred)**: a queue-based mechanism where `proj_session_digest` fires → MCP hook `wiki_queue_ingest(source)` writes to a pending-ingests file → next user session picks up queued ingests via a startup skill. Not in v1.

---

## 9. Ingest protocol (model-centric)

### 9.1 `/proj:wiki-ingest <source>` flow

1. Skill calls `wiki_scope_detect` → scope = `project:cpm` (or `global` if no active project).
2. Skill spawns subagent (general-purpose, forked context) w/ detailed ingest prompt.
3. Subagent workflow (prescribed in skill prompt):
   a. **Read source** via `WebFetch` (URL) or `Read` (file).
   b. **Extract candidate entities** — concepts/decisions/references/gotchas/entities. LLM reasoning. Each candidate has proposed title, category, summary, tags.
   c. **Dedup check**: for each candidate, call `wiki_page_list(tags=..., scope_filter=...)` + fuzzy title match via `wiki_link_resolve`. Identify existing pages that may already cover the concept.
   d. **For new**: construct frontmatter + body → `wiki_page_write(mode="create", ...)`.
   e. **For existing**: `wiki_page_get(page)` → LLM merges new content into existing body (preserving prior claims, adding new, reconciling conflicts) → `wiki_page_write(mode="update", ...)`. Updates `sources[]` w/ new entry + `last_ingested`.
   f. **Cross-ref pass**: after all pages written, scan each new/updated page's body → identify mentioned concepts → add `[[wikilinks]]` → update `links_to` frontmatter via `wiki_page_write(mode="update")`.
   g. `wiki_log_append(action="ingest", title=<source-ref>, body=summary)`.
   h. `wiki_index_rebuild`.
   i. Return JSON: `{pages_updated, pages_created, log_entry, sources}`.
4. Main skill renders the result table + any warnings.

### 9.2 Subagent prompt shape (excerpt)

```
You are an ingest agent for the Karpathy LLM Wiki at ~/.claude/wiki/.

SOURCE: {source}
SCOPE: {scope}
CONFIG: {wiki_config}

MCP TOOLS AVAILABLE:
- wiki_page_list, wiki_page_get, wiki_page_write, wiki_page_delete
- wiki_index_read, wiki_index_rebuild
- wiki_log_append, wiki_log_read
- wiki_link_resolve
- (read-only: WebFetch, Read, Grep)

DO NOT write files directly. Always go through wiki_page_write.

PROTOCOL:
1. Read source.
2. Extract 3-15 candidate entities covering: architecture concepts, decisions w/ rationale,
   references to external systems, operational gotchas, named entities.
3. For each candidate: check for existing pages via wiki_page_list + wiki_link_resolve.
4. For new: write via wiki_page_write(mode="create") w/ full frontmatter.
5. For existing: read via wiki_page_get; merge; write via wiki_page_write(mode="update").
   Preserve prior sources[] + append new entry.
6. Cross-ref pass: identify [[wikilinks]] in each written page; update links_to frontmatter.
7. Append log entry: wiki_log_append(action="ingest", title=<source>, body=<summary>).
8. Rebuild index: wiki_index_rebuild.
9. Return JSON summary.

FRONTMATTER REQUIRED: title, tags, links_to, scope, sources, last_ingested.

ERROR HANDLING:
- On wiki_page_write mode=create w/ existing page: switch to mode=update.
- On dedup ambiguity: prefer updating existing over creating new.
- On WebFetch/Read failure: abort, write no pages, return error JSON.
```

### 9.3 Idempotency

- Re-running `wiki_page_write(mode=upsert)` w/ identical body + frontmatter → no-op (content hash check).
- Re-running `/proj:wiki-ingest <same-source>` within `reingest_cooldown_hours` (default 24) → returns existing pages w/o rewrite unless `--force`.
- Sources tracked by `sources[*].ref` URI; re-ingest updates `ingested_at` timestamp.

### 9.4 Session auto-ingest (skill-integrated, v1)

Implemented inside `/proj:save` skill itself, not via router hook (see §8.2). Flow:

1. `/proj:save` does its normal work: write session file, update NOTES.md, bump meta.yaml timestamp.
2. If `wiki.enabled and wiki.auto_ingest_sessions`: skill reads the freshly-written session file.
3. Skill spawns ingest subagent w/ `source="session:<session-file>"` + `scope=project:<active>`.
4. Subagent runs the same protocol as §9.1 but w/ section-aware extraction since session files have known structure:
   - "Key Decisions" → `decisions/<date>-<slug>.md` pages
   - "Insights Discovered" → `concepts/` or `gotchas/` pages (LLM classifies)
   - "Related Todos" → no new pages; just `links_to` updates on existing concept pages
5. Subagent returns summary; skill renders it alongside normal `/proj:save` output.

If the ingest subagent fails, `/proj:save` still succeeds (session file + NOTES.md already written). User can manually retry via `/proj:wiki-ingest session:<file>`.

---

## 10. Query protocol (model-centric)

### 10.1 `/proj:wiki-query <question>` flow

1. Skill calls `wiki_scope_detect` → scope info (informational; default query reads all scopes).
2. Skill spawns subagent w/ query prompt + question.
3. Subagent workflow:
   a. `wiki_index_read` → catalog of all pages.
   b. LLM reasons: identify 3-10 candidate pages by title/category/summary match.
   c. For each candidate: `wiki_page_get(page)` → read full content.
   d. LLM synthesizes answer citing specific pages, quoting excerpts.
   e. If answer incomplete: LLM follows `[[wikilinks]]` to related pages, reads them.
   f. (Optional, if `--file-back`) If question + answer seems durable + high-value: LLM proposes new `query-summary` page + calls `wiki_page_write` (after user approval).
4. Main skill renders:
   - Answer (markdown)
   - Citations table: `[page-slug] | category | excerpt | last_ingested`
   - Pages read (transparency count)

### 10.2 Subagent prompt shape (excerpt)

```
You are answering a user's question by reading the wiki at ~/.claude/wiki/.

QUESTION: {question}
SCOPE_FILTER: {scope_filter or "none — read all scopes"}

MCP TOOLS AVAILABLE (READ-ONLY):
- wiki_index_read, wiki_page_list, wiki_page_get, wiki_log_read, wiki_link_resolve
- (external: WebSearch, fallback only)

DO NOT write pages unless explicitly told to file back.

PROTOCOL:
1. wiki_index_read to get catalog.
2. Identify 3-10 relevant pages by title/category/summary match.
3. wiki_page_get each candidate.
4. If candidate page references [[wikilinks]] that add information: wiki_page_get them too.
5. Synthesize a citation-backed answer.
6. Return JSON: {answer, citations, pages_read, proposed_new_page: null | {...}}

CITATION RULE: every claim needs [[page-slug]] reference. Quote exactly where possible.

IF WIKI HAS NOTHING RELEVANT: say so + suggest ingestion via /proj:wiki-ingest.
```

### 10.3 Query variations

- **Default** (no flags): reads all scopes, synthesizes across.
- **`--scope project`**: narrows to `scope:[project:<active>]` only.
- **`--raw`**: returns candidate pages + excerpts w/o synthesis.
- **`--file-back`**: if answer is durable, propose new page for user approval.

### 10.4 Relationship to `proj_search_knowledge`

Both coexist, different purposes:
- `proj_search_knowledge`: grep-based, literal string match, fast, no synthesis.
- `wiki_query`: LLM-driven, synthesis-based, slower, answers "what do we know about X".

Rule of thumb: need exact string → `proj_search_knowledge`. Need synthesis across concepts → `/proj:wiki-query`.

---

## 11. Lint (on-demand, two-tier)

### 11.1 Tier 1: Pure-data checks (MCP tools, no LLM)

Called directly by `/proj:wiki-lint` skill. Each tool returns structured findings.

| Check | MCP tool | Algorithm |
|---|---|---|
| Orphans | `wiki_lint_orphans` | Graph walk: pages w/ 0 inbound + 0 outbound `links_to`. Skip if total pages < `orphan_min_page_count`. |
| Broken links | `wiki_lint_broken_links` | For each page's `links_to` + inline `[[wikilinks]]`: resolve → collect misses. |
| Stale pages | `wiki_lint_stale(days)` | Filter pages where `last_ingested < now - N days`. |
| Schema violations | `wiki_lint_schema` | For each page: check `config.yaml:required_frontmatter` against actual. |
| Duplicate slugs | `wiki_lint_duplicates` | Group by slug → collisions. |

### 11.2 Tier 2: Semantic checks (LLM-driven, skill-prompted)

Driven by `/proj:wiki-lint` skill after Tier 1. Each check spawns a subagent:

| Check | LLM prompt summary |
|---|---|
| Contradictions | "Read these N pages w/ tag overlap. Report factual contradictions. JSON: `{contradictions: [{pages, claim_a, claim_b, evidence}]}`" |
| Deprecation candidates | "Read pages not referenced in last 90 days. Which are obsolete? JSON: `{candidates: [{page, reason}]}`" |
| Missing cross-refs | "Read page X. Which other pages should it link to but doesn't? JSON: `{suggestions: [{from, to, reason}]}`" |

Subagents run in parallel via TeamCreate.

### 11.3 `/proj:wiki-lint` skill flow

```
1. Skill calls all Tier 1 MCP tools (parallel).
2. Skill collects Tier 1 findings.
3. Skill spawns Tier 2 subagents (parallel team).
4. Skill aggregates + presents findings in report form.
5. For each finding: user prompted [fix / file-todo / skip]
   - "fix" → skill calls wiki_page_write or wiki_page_delete
   - "file-todo" → skill calls todo_add in proj to track fix
   - "skip" → no action
6. wiki_log_append(action="lint", title="full").
```

### 11.4 Cadence

On-demand only. No automatic/scheduled lint in v1. Config flag `wiki.lint_on_ingest: false` default. Future: optional scheduled lint via cpm `/schedule`.

---

## 12. Migration path + bootstrap

### 12.1 What changes for existing users

| File/feature | Current | After | Migration |
|---|---|---|---|
| `NOTES.md` | Chronological prose notes, appended via `notes_append` | Deprecated; wiki's `log.md` + pages take over | Bootstrap reads existing NOTES.md → creates wiki pages + log entries |
| `sessions/*.md` | Per-session archive | Unchanged (stays as raw audit trail) | Auto-ingest on `/proj:save` going forward |
| `todos/{id}/requirements.md` + `research.md` | Per-todo content | Unchanged (stays per-todo) | Optionally bootstrapped into wiki as `concepts/` pages w/ `sources: [todo:<id>]` |
| Design docs (e.g. `overhaul-requirements.md`) | Raw files | Unchanged (stays in tracking dir) | Bootstrapped into wiki pages per section |
| `proj_search_knowledge` | grep over notes/requirements/research/decisions | Unchanged (coexists w/ wiki_query) | No migration |
| `proj.yaml` | No wiki config | Adds `wiki:` section | Default opt-out; user runs `/proj:wiki-init` to enable |
| `memory/unified-recall-proposal.md` | Pending 26-day-old memory | Superseded | Mark deprecated; move to `memory/archive/` w/ pointer to this spec |

### 12.2 Bootstrap flow (`/proj:wiki-bootstrap`)

Run once per project (idempotent — can rerun, dedups by source ref).

```
1. User: /proj:wiki-bootstrap

2. Skill detects active project (or prompts for scope=global).

3. Skill enumerates sources:
   - ~/projects/tracking/<project>/NOTES.md (if exists)
   - ~/projects/tracking/<project>/sessions/*.md (all)
   - ~/projects/tracking/<project>/todos/*/requirements.md + research.md
   - Design docs specified in proj.yaml: wiki.bootstrap_docs

4. Skill spawns team of subagents (TeamCreate, one per source category):
   - agent A: NOTES.md → concepts/decisions pages
   - agent B: sessions → decisions/concepts/gotchas pages
   - agent C: todos/*/requirements+research → concepts pages per-domain
   - agent D: design docs → chunked section-by-section → concepts + references pages

5. Each subagent writes directly to ~/.claude/wiki/ via wiki_page_write.

6. Main agent waits for team completion, runs wiki_index_rebuild, then cross-references
   pass (second walk: scan page bodies for concept mentions → add [[wikilinks]]).

7. Summary:
   - N pages created (by category)
   - M cross-references added
   - Log entry: ## [2026-04-21] bootstrap | cpm
   - Flag to user: "NOTES.md preserved at <path>.bak. Delete after verifying wiki? [y/n]"

8. Post-bootstrap: proj.yaml flags flip:
   - wiki.bootstrap_completed: true
   - wiki.replace_notes_md: true
   - wiki.auto_ingest_sessions: true
```

### 12.3 Per-project enablement gate

Wiki is opt-in per project. First-time flow:

1. `/proj:wiki-init` — creates wiki directory + sets `wiki.enabled=true` in proj.yaml.
2. `/proj:wiki-bootstrap` — ingests existing knowledge, flips runtime flags.
3. From here, wiki operates normally.

Rollback: flip flags to `false`; `notes_append` re-enables NOTES.md write path. Wiki directory can be deleted; proj is unaffected.

### 12.4 Sunset the unified-recall-proposal

Mark `~/.claude/projects/-home-raul-projects-claude-project-manager/memory/unified-recall-proposal.md` as deprecated:

```yaml
---
deprecated: true
deprecated_in_favor_of: docs/superpowers/specs/2026-04-21-karpathy-wiki-plugin-design.md
deprecated_at: 2026-04-21
---
```

Move to `memory/archive/unified-recall-proposal.md`. Update `memory/MEMORY.md` index to remove the active link. Do NOT delete — keeps rationale discoverable.

---

## 13. Error handling

### 13.1 Atomic writes

All writes (`wiki_page_write`, `wiki_log_append`, `wiki_index_rebuild`, `wiki_page_delete`) use a shared file lock (`threading.Lock` + `fcntl.flock` on `~/.claude/wiki/.lock`). Matches `todo_batch_complete` pattern.

### 13.2 Failure modes per tool

| Tool | Failure | Handling |
|---|---|---|
| `wiki_page_write` | Frontmatter validation fails | Return error, no file written. Lock released. |
| `wiki_page_write` | Target exists + mode=create | Return error w/ existing page metadata. No overwrite. |
| `wiki_page_write` | Disk full / permission denied | Return error. Lock released. |
| `wiki_page_get` | Page not found | Return `{error: "not_found", page}`. Not an exception. |
| `wiki_index_rebuild` | pages/ unreadable | Return error. index.md untouched. |
| `wiki_log_append` | log.md unwritable | Return error. Caller decides fallback. |
| Subagent (ingest) | Crash mid-extraction | Last successful writes persisted. Next re-run checks slug-dedup + continues. |
| Subagent (query) | WebSearch fails | Synthesize from wiki only. No fallback required. |
| Router hook (session-save → ingest) | Subagent fails | Hook reports error in chain. Session file still saved. User can manually `/proj:wiki-ingest session:<file>`. |

### 13.3 Idempotency guarantees

- `wiki_page_write(mode=upsert)` w/ identical body + frontmatter → no-op (content hash check).
- `/proj:wiki-ingest <same-source>` within `reingest_cooldown_hours` → returns existing pages w/o rewrite unless `--force`.
- `/proj:wiki-bootstrap` re-run → dedups by source ref in `sources[*].ref`.

### 13.4 Degradation

Wiki plugin is optional. If wiki MCP server is down or `wiki.enabled=false`:
- Proj works normally.
- `/proj:wiki-*` skills return "wiki disabled; enable via /proj:wiki-init".
- `notes_append` falls back to NOTES.md write path.

---

## 14. Testing strategy

### 14.1 Unit tests (MCP tools, pure Python)

Target: 85%+ coverage on `plugins/wiki/server/server/tools/`.

- `wiki_page_write`: create, update, upsert, frontmatter validation, mode=create-on-existing error, atomic lock held
- `wiki_page_get`: exists, not-found, malformed frontmatter
- `wiki_page_list`: all filter combos (scope, category, tags, linked_from/to)
- `wiki_page_delete`: exists, not-found, updates backlinks
- `wiki_index_rebuild`: from empty pages/, from N pages, handles missing frontmatter
- `wiki_log_append`: format matches Karpathy prefix, atomic
- `wiki_log_read`: since filter, action filter, limit
- `wiki_lint_orphans`: 0 orphans, all orphans, mixed, respects `orphan_min_page_count`
- `wiki_lint_broken_links`: resolved, unresolved, aliases
- `wiki_lint_stale`: no stale, all stale, threshold boundary
- `wiki_lint_schema`: passing + failing frontmatter
- `wiki_lint_duplicates`: no dupes, dupes, case-insensitive
- `wiki_link_resolve`: by slug, by alias, collision handling
- `wiki_scope_detect`: active project, no active project

### 14.2 Integration tests (multi-tool flows)

- Full ingest cycle: `wiki_page_write` x N → `wiki_index_rebuild` → `wiki_lint_broken_links` returns 0
- Bootstrap simulation: feed synthetic NOTES.md → verify N pages created + log entry
- Router hook: mock `proj_session_digest` fire → verify `wiki_ingest_subagent_spawn` called w/ correct params
- Concurrency: 2 concurrent `wiki_page_write` calls → serialization via lock

### 14.3 Skill tests (LLM-in-loop)

Use skill-eval harness. Non-deterministic; rubric + tolerance-based.

- `/proj:wiki-ingest` on a fixture URL → verify pages created w/ expected frontmatter + body contains key claims
- `/proj:wiki-query` on known corpus → verify answer cites correct pages
- `/proj:wiki-lint` on corpus w/ seeded contradictions → verify Tier 2 detection

Marked `@skip_in_ci` by default; run manually or in nightly workflow.

### 14.4 End-to-end smoke test

- `/proj:wiki-init` → `/proj:wiki-bootstrap` on fixture project → `/proj:wiki-query "what do we know about X"` → verify answer references bootstrapped pages. All in a temp wiki dir.

---

## 15. Phased implementation sketch

For handoff to `superpowers:writing-plans` — not a full plan, just a suggested phasing.

**Phase 1: Core MCP tools + storage** (~300 LOC, ~1 week)
- `wiki_page_write`, `wiki_page_get`, `wiki_page_list`, `wiki_page_delete`
- `wiki_index_read`, `wiki_index_rebuild`
- `wiki_log_append`, `wiki_log_read`
- `wiki_link_resolve`, `wiki_scope_detect`
- Frontmatter parser + validator
- Atomic lock infrastructure
- Unit tests

**Phase 2: Lint tools + basic skills** (~200 LOC, ~1 week)
- `wiki_lint_orphans/broken_links/stale/schema/duplicates`
- `/proj:wiki-init` skill
- `/proj:wiki-lint` skill (Tier 1 only)
- `/wiki:query` + `/proj:wiki-query` skill (model-centric synthesis)

**Phase 3: Ingest + session integration** (~300 LOC, ~2 weeks)
- `/proj:wiki-ingest` + `/wiki:ingest` skill
- Subagent protocol + prompts
- Router hooks for session auto-ingest
- `notes_append` retargeting flag

**Phase 4: Bootstrap + Tier 2 lint** (~400 LOC, ~2 weeks)
- `/proj:wiki-bootstrap` skill w/ team-orchestrated subagents
- Tier 2 lint subagents (contradictions, deprecation, missing cross-refs)
- `/proj:wiki-promote`
- Migration tooling for existing NOTES.md + sessions
- Sunset unified-recall-proposal.md

**Phase 5: Polish + docs** (~100 LOC, ~1 week)
- README for wiki plugin
- CLAUDE.md updates documenting wiki config flags
- End-to-end smoke test in CI
- Update cpm marketplace docs

**Total estimate**: ~1300 LOC, 6-7 weeks.

---

## 16. Open questions / future work

- **`qmd` integration**: if wiki grows beyond moderate scale (~100 sources / hundreds of pages), evaluate adding `qmd` as an optional search layer. MCP tool `wiki_search_qmd(query)` would wrap the CLI. Not in v1.
- **Page versioning**: no version history in v1. Git in the wiki dir covers this externally. If we need in-wiki diff/history, add later.
- **Binary attachments**: `attachments/` dir exists but no tools to manage it. Add if user demand arises.
- **Cross-wiki federation**: if other cpm users want to share wiki subsets, design a federation layer. Not in v1.
- **Auto-promotion heuristic**: currently `/proj:wiki-promote` is manual. Could add heuristic ("page referenced by N+ projects → auto-promote") if manual becomes burdensome.
- **Wiki UI**: Obsidian compatibility is a side effect (plain markdown + `[[wikilinks]]`). No custom UI planned. `docs/superpowers/wiki-obsidian-setup.md` could ship w/ optional Obsidian vault config.

---

## 17. Superseded work

- `~/.claude/projects/-home-raul-projects-claude-project-manager/memory/unified-recall-proposal.md` (2026-03-25) — addressed enhanced frontmatter, SessionStart context injection, `proj_memory_link`/`proj_memory_migrate` tools. This spec replaces that proposal: the wiki pattern unifies the same knowledge surface under a single entity-centric model rather than enhancing two parallel systems. Moving proposal to `memory/archive/` post-approval.
- `~/.claude/projects/-home-raul-projects-claude-project-manager/memory/interaction-mapping.md` + `recall-gap-analysis.md` (2026-03-25) — retained as reference material (they document the problem space this spec solves).

---

## Appendix A: Directory at-a-glance

```
~/.claude/wiki/
├── index.md                     # catalog; machine-maintained
├── log.md                       # ledger; append-only
├── config.yaml                  # schema + lint rules
├── .lock                        # fcntl lock file
├── pages/
│   ├── concepts/*.md
│   ├── decisions/*.md
│   ├── references/*.md
│   ├── gotchas/*.md
│   └── entities/*.md
└── attachments/                 # optional binaries

plugins/wiki/
├── plugin.json
├── marketplace.json
├── server/
│   └── server/
│       ├── __init__.py
│       ├── main.py
│       └── tools/
│           ├── page.py          # write/get/list/delete
│           ├── index.py         # read/rebuild
│           ├── log.py           # append/read
│           ├── lint.py          # orphans/stale/broken/schema/dupes
│           ├── scope.py         # detect
│           └── links.py         # resolve
├── hooks/
│   └── hooks.json               # router registrations
└── skills/
    ├── ingest/SKILL.md          # /wiki:ingest
    ├── query/SKILL.md           # /wiki:query
    └── lint/SKILL.md            # /wiki:lint

plugins/proj/skills/             # new skills
├── wiki-init/SKILL.md
├── wiki-ingest/SKILL.md
├── wiki-query/SKILL.md
├── wiki-lint/SKILL.md
├── wiki-bootstrap/SKILL.md
└── wiki-promote/SKILL.md
```

## Appendix B: Glossary

- **Wiki page**: a markdown file w/ required frontmatter, living under `pages/<category>/`.
- **Slug**: normalized page identifier (lowercase, dashes; derived from title or filename).
- **Scope**: metadata tag (`global` or `project:<name>`) on each page; used for attribution + lint, not default query filtering.
- **`[[wikilink]]`**: inline reference to another page by slug or alias.
- **Ingest**: synthesize a source (URL/file/session) into wiki pages via LLM subagent.
- **Query**: read index + relevant pages + synthesize a cited answer via LLM subagent.
- **Tier 1 lint**: pure-data checks via MCP tools (orphans, broken links, stale, schema, duplicates).
- **Tier 2 lint**: LLM-driven checks via subagents (contradictions, deprecation candidates, missing cross-refs).
- **Bootstrap**: one-shot bulk import from existing project knowledge (NOTES.md, sessions, todo research, design docs).
- **Model-centric**: synthesis happens in the LLM, driven by skill prompts. MCP = pure persistence.
