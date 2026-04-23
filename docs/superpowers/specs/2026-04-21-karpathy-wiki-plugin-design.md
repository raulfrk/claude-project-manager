# Karpathy LLM Wiki Plugin — Design Spec

**Date**: 2026-04-21
**Status**: Design approved; awaiting implementation plan
**Todo**: [688](~/projects/tracking/claude-project-manager/todos.yaml) — "Investigate creating new plugin for cpm around Karpathy's LLM Wiki pattern"
**Source inspiration**: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
**Supersedes**: `~/.claude/projects/-home-raul-projects-claude-project-manager/memory/unified-recall-proposal.md` (2026-03-25, pending)

---

## 1. Overview + motivation

This spec defines a new `wiki` plugin for the cpm marketplace implementing Andrej Karpathy's "LLM Wiki" pattern: a persistent, LLM-maintained markdown knowledge base that compounds over time. Synthesis happens once at ingest time, not repeatedly at query time.

**Scope is deliberately generic.** The wiki is a domain-agnostic knowledge-base framework. Software engineering is one use case (this spec's running examples), but the same plugin must work identically for personal journals, research corpora, book notes, reading lists, meeting archives, incident post-mortems, medical research, legal case files — anything the user wants to accumulate + synthesize over time. Category profiles (§2.6 + §5.1) tailor the defaults per domain; every MCP tool + skill is domain-agnostic.

**Problem (cpm-specific)**: cpm has two parallel knowledge systems that don't interoperate — auto-memory (`~/.claude/projects/*/memory/`, sparse, global-only, 3 entries in claude-project-manager) and proj tracking (`~/projects/tracking/*/`, rich ~450 KB per active project, but only searchable via grep-style `proj_search_knowledge`). Architectural decisions, operational patterns, and cross-project lessons are buried. A prior proposal (`memory/unified-recall-proposal.md`) outlined enhancements to both but is 26 days old + not implemented. Solving this specific pain point is *one* motivation — but the wiki is built to be useful well beyond cpm.

**Opportunity**: Karpathy's wiki pattern unifies knowledge under a single entity-centric graph w/ well-defined ingest/query/lint semantics. Each concept gets a dedicated page w/ cross-refs; ingest distills sources into those pages; queries synthesize answers from pages via LLM reasoning. The synthesis boundary + scale pattern apply regardless of domain.

**This spec's scope**: the wiki plugin itself, its MCP surface, skills, optional proj integration touchpoints, migration from existing proj data (for the cpm adoption path), + testing approach. Implementation plan is deferred to the follow-on writing-plans phase.

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

**Our fidelity**: index.md categories match whatever category list the active profile declares in `config.yaml` (§5.1) — not hardcoded. Each entry is `[[page]] — one-line summary`. "Recent (by last_ingested)" sub-section added for temporal recall.

### 2.4 Parseable append-only log

> *"log.md is append-only… if each entry starts with a consistent prefix (e.g. `## [2026-04-02] ingest | Article Title`), the log becomes parseable with simple unix tools."*

**Our fidelity**: log entries use exact pattern `## [YYYY-MM-DD] <action> | <title>` grep-parseable via `grep "^## \["`.

### 2.5 Tooling as optional infrastructure

> *"At some point you may want to build small tools that help the LLM operate on the wiki more efficiently. A search engine over the wiki pages is the most obvious one."*

**Our fidelity**: MCP tools are small + focused persistence + pure-data helpers. Karpathy calls out "a search engine over the wiki pages" as the most obvious helper, so **BM25/qmd-style keyword search ships as a first-class tool in Phase 2** (`wiki_search_bm25`, §6). No embeddings / vector DB in v1 — a vector layer is deferred to a tracked todo for tens-of-thousands-scale corpora; see §2.7 + §16.

### 2.6 Where Karpathy is silent + our deliberate choices

| Karpathy | Our choice | Reason |
|---|---|---|
| Does not specify multi-wiki layering | Single wiki w/ `scope` frontmatter tags (not directory split) | Closest to Karpathy's one-wiki model; supports cross-project recall |
| Does not specify directory categories (explicitly "depends on your domain") | **Config-driven preset profiles**. Ship `software`, `personal`, `research`, `minimal` defaults; user-custom supported. `config.yaml` is source of truth. Wizard prompts on first install. Lint suggests additions (§11.2). | Matches Karpathy's anti-prescriptive stance + supports generic framework ask. Predictability preserved per-profile; no SWE bias baked in. |
| Does not specify page frontmatter | Minimal required: `title`, `tags`, `links_to`, `scope`, `sources`, `last_ingested` | Enough metadata for lint + graph walks; light author burden |
| Does not specify wikilink syntax | `[[page-slug]]` + `[[page-slug#section-heading]]` (Obsidian-style) | Easier to write; simpler lint for broken links; section-level linking for precise cross-refs |
| Does not specify query-time scope filtering | Default: read all scopes (Karpathy mode). `--scope project:<name>` + `--scope global` as escape hatches. | Trust LLM to handle relevance via synthesis |

### 2.7 Scale + search-layer strategy

Karpathy names a specific sweet spot + a known limit:

> *"This works surprisingly well at moderate scale (~100 sources, ~hundreds of pages) and avoids the need for embedding-based RAG infrastructure."*

Beyond that, he gestures at lightweight tooling (qmd-like BM25). Our strategy maps scale → retrieval method:

| Scale | Retrieval | Notes |
|---|---|---|
| <~100 sources / ~few hundred pages | LLM reads `index.md` → reads candidate pages directly | Karpathy's sweet spot. Works w/o any search infra. Default path. |
| ~100–thousands of sources / up to ~low-thousands pages | BM25/qmd-style keyword search (`wiki_search_bm25`) narrows candidates, LLM reads top hits | First-class tool in Phase 2. Index kept as sidecar (`.index/`, git-ignored). Obsidian vault unaffected. |
| Tens of thousands of sources | Embeddings-based vector retrieval as sidecar to BM25 (semantic similarity beyond keyword match) | **Deferred to v2** — tracked as todo. Adds embedding-model dep + vector store. Markdown stays canonical, vector DB stays sidecar — Obsidian unaffected. |

BM25 being first-class in v1 means LLM-reads never breaks as the wiki grows: the search tool returns ranked candidates, LLM reads them. No cliff.

---

## 3. Design principle: persistence / synthesis boundary

**This is the single most important design decision in this spec.**

**Domain-agnostic.** Everything below applies regardless of what the user puts in the wiki. Examples throughout this spec use software-engineering content because that is the current cpm context, but `wiki_page_write`, `wiki_page_get`, every skill, and every lint check work identically on a personal-journal wiki, a research-paper wiki, a book-reading wiki, or any other corpus.

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

**Design stance**: wiki is a **single-surface standalone plugin**. Users interact w/ the wiki exclusively through `/wiki:*` skills. Skills self-detect active project scope via `wiki_scope_detect` when proj is loaded, else fall back to `global`. Proj is never required; if it happens to be present + enabled, proj contributes exactly two lightweight integration touchpoints (a router hook + a `/proj:save` ingest step). No `/proj:wiki-*` wrapper skills.

### 4.1 Single-mode overview

```
┌──────────────────────────────────────────────────────┐
│ User: /wiki:query "hooks plugin rationale"           │
│       /wiki:ingest https://gist.github.com/karpathy  │
│       /wiki:lint                                     │
└──────────────┬───────────────────────────────────────┘
               │  (skills auto-detect scope via
               │   wiki_scope_detect; --scope overrides)
               ▼
┌─────────────────────────────┐
│ plugins/wiki/skills/         │
│  query/SKILL.md              │
│  ingest/SKILL.md             │      ┌─────────────────┐
│  lint/SKILL.md               │────▶ │ wiki MCP tools   │
│  init/SKILL.md               │      │ (persistence +   │
│  bootstrap/SKILL.md          │      │  pure-data incl. │
│  promote/SKILL.md            │      │  BM25 search)    │
└─────────────────────────────┘      └────────┬────────┘
                                                │
                                                ▼
                                     ┌──────────────────┐
                                     │ ~/.claude/wiki/   │
                                     │  index.md         │
                                     │  log.md           │
                                     │  pages/<cat>/*.md │
                                     │  config.yaml      │
                                     │  .index/  (BM25)  │
                                     │  .lock            │
                                     └──────────────────┘

Optional proj touchpoints (only when proj installed + sync.wiki.enabled):
  • Router hook:  notes_append → wiki_log_append  (pure data)
  • /proj:save adds a final step that spawns wiki ingest subagent
    if sync.wiki.auto_ingest_sessions is set (§8.2)
```

### 4.2 Plugin structure

- **`plugins/wiki/`** (new) — the plugin. FastMCP server w/ persistence + pure-data tools (incl. BM25 search). Own skills (`/wiki:*`) implementing all end-user operations. Own config (`~/.claude/wiki.yaml`). Fully self-contained. **Zero hard dependency on proj.**
- **`plugins/proj/`** (modified) — adds two touchpoints only:
  1. Router hook `notes_append` → `wiki_log_append` (registered by proj, guarded by `sync.wiki.enabled and sync.wiki.capture_notes_as_log`).
  2. Final step in `/proj:save` skill: if `sync.wiki.enabled and sync.wiki.auto_ingest_sessions`, spawn wiki ingest subagent on the freshly-written session file.
- No `/proj:wiki-*` wrapper skills. Users call `/wiki:*` directly; scope auto-detection does the work wrappers previously did.

### 4.3 Config split

**Wiki runtime config** (`~/.claude/wiki.yaml`) — standalone, owned by wiki plugin:
```yaml
wiki:
  enabled: false                        # master switch; default off
  wiki_dir: ~/.claude/wiki
  bootstrap_pending: false
  reingest_cooldown_hours: 24
  lint_on_ingest: false
  default_scope: global                 # standalone default; proj overrides when active
```

> **Bootstrap field:** the wiki plugin tracks bootstrap state via a single field, `bootstrap_pending: bool` in `~/.claude/wiki.yaml`. The installer sets this `true` when the user defers `/wiki:bootstrap` to a later session; the skill clears it on successful completion. Earlier drafts of this spec referenced `bootstrap_completed` and `proj.yaml::sync.wiki.bootstrap_completed` — neither exists in the current impl. See follow-up todo for broader §4.3 YAML block drift (`wiki:` nesting key, `lint_on_ingest`, `default_scope` are in this example block but not in `WikiConfig`).

**Wiki-local schema config** (`~/.claude/wiki/config.yaml`) — inside the wiki itself:
```yaml
schema_version: 1
required_frontmatter: [title, tags, links_to, scope, sources, last_ingested]
categories: [concepts, decisions, references, gotchas, entities]
lint:
  stale_after_days: 90
  orphan_min_page_count: 3
  contradiction_check: true
```

**Proj-side integration flags** (`~/.claude/proj.yaml`) — only consulted when proj is installed + active:
```yaml
sync:
  wiki:
    enabled: false                      # opt-in per project
    auto_ingest_sessions: false         # /proj:save spawns wiki ingest subagent
    capture_notes_as_log: false         # router hook: notes_append → wiki_log_append
    replace_notes_md: false             # future: redirect notes_append to wiki entirely
    bootstrap_docs: []                  # per-project design docs to bootstrap
```

These flags follow the existing cpm pattern (`sync.todoist.*`, `sync.trello.*`) + gate **behavior**, not skill surfaces. They control whether the two integration touchpoints fire; all wiki operations remain reachable via `/wiki:*` regardless.

### 4.4 Wizard integration

The cpm installer wizard acquires a "wiki" section when the wiki plugin is installed:

1. **Enable?** `[y/n]` — sets `wiki.enabled` in `~/.claude/wiki.yaml`.
2. **Category profile?** — multiple-choice: `software` / `personal` / `research` / `minimal` / `custom`. Writes `profile` + `categories` to `~/.claude/wiki/config.yaml` (wiki-local schema config). `custom` prompts for a free-form category list.
3. **Session-ingest section mapping?** (only if proj installed + `sync.wiki.auto_ingest_sessions` will be set) — maps session headings to wiki categories. Ships a per-profile default (e.g. software profile default: `Key Decisions → decisions`, `Insights Discovered → concepts|pitfalls`, `Related Todos → no-page:link-only`). User can edit. Stored as `session_ingest.section_map` in `wiki.yaml`.
4. **Proj sync flags?** (only if proj installed) — `enabled`, `auto_ingest_sessions`, `capture_notes_as_log`. Writes `sync.wiki.*` in proj.yaml.
5. **Queue bootstrap for next session?** `[y/n]` — the installer is a non-LLM Python process + cannot invoke `/wiki:bootstrap` (which spawns LLM subagents) directly. Instead, setting yes writes `wiki.bootstrap_pending: true` to `wiki.yaml`. A SessionStart hook (or the next `/wiki:*` invocation) detects the flag + prompts the user to run `/wiki:bootstrap` then. Setting no leaves the wiki empty until the user chooses to bootstrap manually.

The wizard is the UX surface for everything configurable in §9.4 (session section mapping) + §5.1 (category profiles). All flags are also editable directly in the YAML files after install. **Wizard never calls an LLM** — it only reads + writes YAML config. Operations needing synthesis (bootstrap, ingest) are deferred to skill invocations inside a Claude session.

---

## 5. Storage format + page schema

### 5.1 Directory layout (`~/.claude/wiki/`)

Category directories under `pages/` are **declared by `config.yaml` profile**, not hardcoded. Lint warns on dirs outside the configured list (`wiki_lint_category_violations`, §11.1). Suggested additions surface via Tier 2 lint (§11.2).

**Skeleton (category-agnostic)**:
```
~/.claude/wiki/
├── index.md                  # entry point: categorized page catalog + Recent
├── log.md                    # append-only chronological ledger
├── config.yaml               # wiki-local config (profile + categories + lint rules)
├── .lock                     # file lock (fcntl) — git-ignored
├── .index/                   # BM25 search index — git-ignored
├── pages/                    # category subdirs per active profile
└── attachments/              # optional: binary sources, screenshots
```

**Example profiles:**

```
# software profile (default for cpm users)
pages/
├── concepts/        # architecture concepts, patterns, domain ideas
├── decisions/       # decisions w/ rationale
├── references/      # external systems, URLs, docs
├── pitfalls/        # operational traps (was "gotchas")
└── entities/        # people, projects, tools

# personal profile
pages/
├── journal/         # dated entries
├── topics/          # recurring subjects
├── people/          # individuals
├── places/          # locations
└── lessons/         # things learned

# research profile
pages/
├── concepts/        # ideas + frameworks
├── sources/         # papers, articles, podcasts
├── findings/        # synthesized insights
└── questions/       # open lines of inquiry

# minimal profile
pages/                # flat; no category subdirs. Tags drive grouping in index.md.
```

Profiles live in the plugin; `config.yaml` references one by name + may override its `categories` list. `custom` = user-declared list only. Lint behavior: warn on unknown category dirs, error on frontmatter category values not in the configured list.

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

Two forms, both Obsidian-compatible:

- **Page-level**: `[[page-slug]]` — resolves to a page.
- **Section-level**: `[[page-slug#section-heading]]` — resolves to a specific `## section-heading` inside a page. Use for precise cross-refs when a whole page is broader than the target claim.

Resolver scans `pages/**/*.md` for matching frontmatter `title` slug or filename. Case-insensitive. Section matching walks markdown headings (`##`, `###`, …) inside the resolved page. Unresolved page refs → `wiki_lint_broken_links`; resolved page but missing section → `wiki_lint_broken_section_refs` (§11.1).

Aliases: frontmatter `aliases` field enables matching `[[hooks-architecture]]` to `hooks-plugin-architecture.md`.

### 5.4 index.md

Machine-maintained by wiki plugin (via `wiki_index_rebuild` tool). Sections = current profile's configured categories (software profile example shown):

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

## Pitfalls (1)
- [[podman-fqdn-required]] — Podman images need `docker.io/...` prefix.

## Entities (1)
- [[claude-project-manager]] — cpm project.

## Recent (by last_ingested, top 10)
- [[hooks-plugin-architecture]] (2026-04-21)
- [[router-hook-chain]] (2026-04-20)
```

A `personal`-profile index would instead show `## Journal`, `## Topics`, `## People`, etc. A `minimal`-profile index groups by tag cluster rather than directory.

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
| `wiki_page_delete` | Delete page + update backlinks | `page` (slug) | `{deleted, backlinks_updated: []}` |
| `wiki_index_read` | Read index.md | — | `{content, categories, recent}` |
| `wiki_index_rebuild` | Regenerate index.md from pages/ | — | `{entries_by_category, recent_count}` |
| `wiki_log_append` | Append entry to log.md | `action`, `title`, `body` (optional detail) | `{entry}` |
| `wiki_log_read` | Read log entries | `since` (date), `action_filter`, `limit` | `{entries: [{date, action, title, body}]}` |
| `wiki_scope_detect` | Resolve active project → scope tag + proj presence flag | — | `{scope: "project:<name>" \| "global", proj_present: bool}` |
| `wiki_link_resolve` | Resolve `[[page]]` or `[[page#section]]` → file path + section anchor | `link` (slug / alias, optional `#section`) | `{resolved: path \| null, section_found: bool \| null, candidates: []}` |
| `wiki_search_bm25` | BM25 keyword search over pages | `query`, optional `limit`, `category`, `tags`, `scope_filter` | `{hits: [{slug, score, snippet}]}` |
| `wiki_search_index_refresh` | Rebuild BM25 sidecar index from `pages/` | — | `{pages_indexed, elapsed_ms}` |
| `wiki_lint_orphans` | Pages w/ 0 inlinks + 0 outlinks | — | `{orphans: [page]}` |
| `wiki_lint_broken_links` | `[[link]]` refs w/ no matching page | — | `{broken: [{from, link}]}` |
| `wiki_lint_broken_section_refs` | `[[page#section]]` refs where page exists but section heading does not | — | `{broken: [{from, link, resolved_page}]}` |
| `wiki_lint_category_violations` | Pages whose directory or `category` frontmatter is not in configured profile categories | — | `{violations: [{page, found_category, configured: []}]}` |
| `wiki_lint_stale` | Pages older than N days | `days` | `{stale: [{slug, path, last_ingested, age_days}]}` |
| `wiki_lint_schema` | Pages violating required frontmatter | — | `{violations: [{page, path, missing_fields, invalid_fields}]}` |
| `wiki_lint_duplicates` | Pages w/ colliding slugs | — | `{duplicates: [[page_a, page_b]]}` |

**Concurrency**: all writes go through a shared file lock (`threading.Lock` + `fcntl.flock` on `~/.claude/wiki/.lock`). Matches `todo_batch_complete` pattern in proj.

**BM25 implementation note**: `wiki_search_bm25` wraps an in-process BM25 library (`rank-bm25` or similar) operating on a sidecar index in `~/.claude/wiki/.index/`. Index is plain-text JSON, git-ignored. Refresh runs automatically after `wiki_page_write` + `wiki_page_delete`; full rebuild available via `wiki_search_index_refresh`. No LLM, no embeddings.

**No tool does synthesis.** No `wiki_ingest`, no `wiki_query`, no `wiki_lint_contradictions` MCP tool. Those are skill-driven.

---

## 7. Skills

### 7.1 Wiki plugin skills (`plugins/wiki/skills/`) — the only surface

All end-user operations live under `/wiki:*`. Every skill works regardless of whether proj is installed. When proj is present + loaded, skills call `wiki_scope_detect` at start to auto-resolve active-project scope; otherwise scope defaults to `global`. User can override either way via `--scope` flag.

| Skill | Purpose | Scope default |
|---|---|---|
| `/wiki:init` | Create `~/.claude/wiki/` + `config.yaml` + empty `index.md` + `log.md`; set `wiki.enabled=true` in `wiki.yaml`. Wizard integration prompts for profile here (§4.4). | — |
| `/wiki:ingest <source>` | Ingest URL / file / `session:<path>` / `note:<text>` / `search:<query>` / `mcp:<server>:<tool>:<args>` into wiki | Auto-detected (active project → project scope, else global) |
| `/wiki:query <question>` | Query wiki + synthesize answer w/ citations. BM25 first-pass for large wikis, LLM-reads otherwise. | No scope filter — reads all |
| `/wiki:lint` | Full lint (Tier 1 data + Tier 2 semantic) + interactive fix prompts | — |
| `/wiki:bootstrap` | Bulk import. When proj loaded: auto-discovers proj sources (NOTES.md, sessions/, todos/). When standalone: prompts for directory or file list. | Auto-detected |
| `/wiki:promote <page>` | Add `global` to page's scope tags (or strip project-specific scopes) | — |

All skills are LLM-driven — their SKILL.md files contain step-by-step prose prompts describing the synthesis protocol. They call MCP tools for persistence only.

### 7.2 Scope auto-detection

Skills that touch scope (`/wiki:ingest`, `/wiki:query`, `/wiki:bootstrap`, `/wiki:promote`) call `wiki_scope_detect` at step 1. The tool:

1. Checks if proj plugin is installed + `~/.claude/proj.yaml` is readable.
2. If yes → reads active-project name → returns `scope: "project:<name>"` + `proj_present: true`.
3. If proj absent / no active project → returns `scope: "global"` + `proj_present: false`.

Skills default to the returned scope unless user passes `--scope <value>`. This replaces what `/proj:wiki-*` wrapper skills did in the previous design.

**Scope filter semantics in `/wiki:query`** (clarifying lines 365/407 feedback):
- No `--scope` flag → reads *all* pages regardless of scope tag (Karpathy default).
- `--scope project:<name>` → narrows to pages tagged with that project.
- `--scope global` → excludes project-scoped pages; reads only globals.
- Scope is a frontmatter *tag*, not a *filter default*. A page scoped to `project:cpm` is always queryable with `/wiki:query <q>` from any context.

---

## 8. Router hooks

Wiki integrates w/ proj via router hooks for **pure-data operations** (no synthesis). Operations that need LLM synthesis (ingest) are not hookable — they live inside user-invoked skills.

### 8.1 Hookable (pure-data) integrations

```yaml
hooks:
  - id: proj-wiki-log-on-notes-append
    trigger_tool: notes_append
    target_tool: wiki_log_append
    server: wiki
    condition: "sync.wiki.enabled and sync.wiki.capture_notes_as_log"
    param_mapping:
      action: "note"
      title: "${content_first_line}"
      body: "${content}"
    blocking: false
```

> **`notes_append` return-shape contract:** as of the wiki-plugin Phase 4a work (commit `d9faf8d`), `mcp__plugin_proj_proj__notes_append` returns JSON rather than plain string. Shape:
> ```json
> {
>   "status": "appended",
>   "project_name": "<name>",
>   "content": "<full text appended>",
>   "content_first_line": "<first line of content, trimmed>",
>   "message": "Note appended to <name>/NOTES.md."
> }
> ```
> The router hook above uses `${content_first_line}` for the log entry `title` and `${content}` for the body (router `${}` template substitution against the source result fields). Hooks that consume this tool must use these field names — not `source_result.first_line` / `source_result.body` (stale names from the original spec draft).

This is the only router hook in v1: `notes_append` → `wiki_log_append`. Both are MCP tools. Pure data forwarding. No synthesis. Registered by the **proj plugin** (not the wiki plugin) because proj owns `notes_append` + the hook only makes sense when proj is present.

### 8.2 Session auto-ingest (skill-level, not a router hook)

Session ingest requires LLM synthesis (read session file → extract concepts/decisions → write pages). Router hooks target MCP tools only; they cannot spawn subagents.

**v1 approach**: edit the existing `/proj:save` skill so its final step, guarded by `sync.wiki.enabled and sync.wiki.auto_ingest_sessions`, spawns a wiki ingest subagent on the freshly-written session file. The spawn happens inside the user's conversation, so the subagent has full LLM access + sees the ingest output inline with normal `/proj:save` output. No new skill; just a section appended to `/proj:save`.

**Rationale**: keeps hooks restricted to pure data forwarding. Keeps synthesis in the LLM layer. Preserves the persistence/synthesis boundary (§3).

**v2 (deferred, tracked as todo)**: a queue-based mechanism where `proj_session_digest` fires → MCP hook `wiki_queue_ingest(source)` writes to a pending-ingests file → startup skill picks up queued ingests on next session. Revisit if skill-integrated v1 causes friction.

---

## 9. Ingest protocol (model-centric)

### 9.1 `/wiki:ingest <source>` flow

**Source resolution is LLM-driven**: the subagent parses the user's `<source>` argument (free-form text or explicit prefix) + picks the right reader. Users never need to know prefix syntax — `/wiki:ingest the onboarding page from confluence about hiring` works as well as `/wiki:ingest mcp:confluence:page_get:space=HR,title=Onboarding`. Explicit prefixes still work for scripting + unambiguous dispatch.

**Resolution algorithm** (subagent step 0, before any fetch):

1. If source matches a known explicit prefix (`https://…`, `file:…`, `session:…`, `note:…`, `search:…`, `mcp:…`) → use the matching reader below directly.
2. Else: LLM reads the free-form text + resolves to a concrete source:
   - Mentions of "confluence"/"notion"/"jira"/"github"/"linear" + available MCP servers → pick the matching MCP server + infer the right tool from content (e.g. "page" → `page_get`, "issue/ticket" → `issue_get`).
   - Mentions of "search for X online" → `search:X`.
   - Mentions of "this file" / a concrete path → file read.
   - A URL anywhere in the text → `WebFetch` on that URL.
   - Ambiguous → subagent asks user via AskUserQuestion before fetching.
3. Returned resolution is logged in the ingest output so user sees what the LLM picked.

**Supported source forms**:

| Source form | Reader | Notes |
|---|---|---|
| `https://…` or `http://…` | `WebFetch` | Web article, gist, blog, HTML page |
| Absolute / relative file path | `Read` | Local markdown, text, transcripts, PDFs via Read's PDF support |
| `session:<path>` | `Read` | Proj session file (semantics identical to file path; flag enables section-aware extraction per wiki.yaml `session_ingest.section_map`) |
| `note:<text>` | inline | Free-form note; no external fetch |
| `search:<query>` | `WebSearch` | Runs web search; subagent picks top N results, ingests each |
| `mcp:<server>:<tool>:<args>` | dynamic MCP call | Explicit form: invokes the named MCP tool + treats return payload as source text. Preferred path when scripting; LLM resolves the same tool call from natural language otherwise. Works w/ any installed MCP server that returns document-like payloads (confluence, notion, jira, github, linear, …). |
| Free-form natural language | LLM-resolved → one of the above | E.g. "the RFC page from confluence about hooks" → `mcp:confluence:...`. "the jira ticket PROJ-42" → `mcp:jira:jira_get_issue:PROJ-42`. "this morning's session notes" → disambiguate via AskUserQuestion. |

1. Skill calls `wiki_scope_detect` → `scope = project:<active>` or `global`. User override via `--scope`.
2. Skill spawns subagent (general-purpose, forked context) w/ detailed ingest prompt.
3. Subagent workflow (prescribed in skill prompt):
   a. **Read source** via the matching reader above. For `search:` + `mcp:` forms that return multiple items, iterate.
   b. **Extract candidate entities** — slotted into the active profile's categories (`concepts`, `decisions`, `topics`, `journal`, etc. — whatever `config.yaml` declares). LLM reasoning. Each candidate has proposed title, category, summary, tags.
   c. **Dedup check**: for each candidate, call `wiki_page_list(tags=..., scope_filter=...)` + fuzzy title match via `wiki_link_resolve` + optional `wiki_search_bm25(query=<candidate-title>)`. Identify existing pages that may already cover the concept.
   d. **For new**: construct frontmatter + body → `wiki_page_write(mode="create", ...)`.
   e. **For existing**: `wiki_page_get(page)` → LLM merges new content into existing body (preserving prior claims, adding new, reconciling conflicts) → `wiki_page_write(mode="update", ...)`. Updates `sources[]` w/ new entry + `last_ingested`.
   f. **Cross-ref pass**: after all pages written, scan each new/updated page's body → identify mentioned concepts → add `[[wikilinks]]` (page-level or `[[page#section]]` for precise refs) → update `links_to` frontmatter via `wiki_page_write(mode="update")`.
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
- wiki_link_resolve, wiki_search_bm25
- (read-only: WebFetch, Read, Grep, WebSearch, dynamic MCP tool calls)

DO NOT write files directly. Always go through wiki_page_write.

SOURCE READERS:
- URL (http/https):        WebFetch
- Local path:              Read
- session:<path>:          Read (apply wiki.yaml session_ingest.section_map for extraction)
- note:<text>:             inline, no fetch
- search:<query>:          WebSearch (top 3-5 results), then iterate as URL sources
- mcp:<server>:<tool>:<a>: invoke the named MCP tool; treat return payload as source text

SOURCE RESOLUTION (infer before reading):
- If source starts with a known prefix above, use that reader directly.
- Else parse the free-form text:
    * Any http(s) URL present → WebFetch on it.
    * Mentions of "confluence" / "notion" / "jira" / "github" / "linear"
      + keywords like "page", "issue", "ticket", "repo" + available MCP
      servers → infer mcp:<server>:<tool>:<args>.
    * Mentions of "search for X online" or "look up X" → search:<query>.
    * Mentions of "this file <path>" or bare filesystem path → Read.
    * Ambiguous or missing required detail → AskUserQuestion to disambiguate.
- Log the resolved source form in the ingest JSON summary.

PROTOCOL:
1. Resolve source per SOURCE RESOLUTION above, then read using the matching reader.
2. Extract 3-15 candidate entities covering the active profile's categories (from config.yaml).
3. For each candidate: check for existing pages via wiki_page_list + wiki_link_resolve
   + wiki_search_bm25 if the wiki has grown past a few hundred pages.
4. For new: write via wiki_page_write(mode="create") w/ full frontmatter.
5. For existing: read via wiki_page_get; merge; write via wiki_page_write(mode="update").
   Preserve prior sources[] + append new entry.
6. Cross-ref pass: identify [[wikilinks]] + [[page#section]] refs in each written page;
   update links_to frontmatter.
7. Append log entry: wiki_log_append(action="ingest", title=<source>, body=<summary>).
8. Rebuild index: wiki_index_rebuild.
9. Return JSON summary.

FRONTMATTER REQUIRED: title, tags, links_to, scope, sources, last_ingested.

ERROR HANDLING:
- On wiki_page_write mode=create w/ existing page: switch to mode=update.
- On dedup ambiguity: prefer updating existing over creating new.
- On WebFetch/Read/WebSearch/MCP-fetch failure: abort, write no pages, return error JSON.
```

### 9.3 Idempotency

- Re-running `wiki_page_write(mode=upsert)` w/ identical body + frontmatter → no-op (content hash check).
- Re-running `/wiki:ingest <same-source>` within `reingest_cooldown_hours` (default 24) → returns existing pages w/o rewrite unless `--force`.
- Sources tracked by `sources[*].ref` URI; re-ingest updates `ingested_at` timestamp.

### 9.4 Session auto-ingest (skill-integrated, proj-only)

Sessions only exist when proj is installed + loaded. This subsection applies to that case.

Implemented as a final step appended to the existing `/proj:save` skill, not via router hook (see §8.2). Flow:

1. `/proj:save` does its normal work: write session file, update NOTES.md, bump meta.yaml timestamp.
2. If `sync.wiki.enabled and sync.wiki.auto_ingest_sessions`: skill reads the freshly-written session file.
3. Skill spawns ingest subagent w/ `source="session:<session-file>"` + `scope=project:<active>`.
4. Subagent runs the §9.1 protocol w/ section-aware extraction driven by `wiki.yaml:session_ingest.section_map`. **The mapping is user-configurable** via the wizard (§4.4) or by editing `wiki.yaml`. Default for the `software` profile:
   ```yaml
   session_ingest:
     section_map:
       "Key Decisions":      decisions   # new page per decision
       "Insights Discovered": auto       # LLM picks concepts | pitfalls
       "Related Todos":       links-only # no new pages; update existing links_to
       "Session Notes":       journal    # if journal category exists
   ```
   Other profiles ship their own defaults. `custom` profile = user-defined map only. `auto` lets the LLM classify per-item.
5. Subagent returns summary; skill renders it alongside normal `/proj:save` output.

If the ingest subagent fails, `/proj:save` still succeeds (session file + NOTES.md already written). User can manually retry via `/wiki:ingest session:<file>`.

---

## 10. Query protocol (model-centric)

### 10.1 `/wiki:query <question>` flow

1. Skill calls `wiki_scope_detect` → scope info (informational; default query reads all scopes).
2. Skill spawns subagent w/ query prompt + question + current wiki page count (from `wiki_page_list(limit=0)`).
3. Subagent workflow:
   a. `wiki_index_read` → catalog of all pages.
   b. **Retrieval strategy depends on scale** (§2.7):
      - Small wiki (<~few hundred pages): LLM reasons from the index alone → identifies 3-10 candidate pages by title/category/summary match.
      - Larger wiki: LLM first calls `wiki_search_bm25(query=<question-keywords>, limit=20)` → narrows to ranked candidates → then reasons over returned hits + index entries.
   c. For each candidate: `wiki_page_get(page)` → read full content.
   d. LLM synthesizes answer citing specific pages, quoting excerpts.
   e. If answer incomplete: LLM follows `[[wikilinks]]` or `[[page#section]]` refs to related pages/sections, reads them.
   f. (Optional, if `--file-back`) If question + answer seems durable + high-value: LLM proposes new `query-summary` page + calls `wiki_page_write` (after user approval).
4. Main skill renders:
   - Answer (markdown)
   - Citations table: `[page-slug] | category | excerpt | last_ingested`
   - Pages read (transparency count)
   - Search path (BM25 vs index-only) so user sees which retrieval mode fired

### 10.2 Subagent prompt shape (excerpt)

```
You are answering a user's question by reading the wiki at ~/.claude/wiki/.

QUESTION: {question}
SCOPE_FILTER: {scope_filter or "none — read all scopes"}

MCP TOOLS AVAILABLE (READ-ONLY):
- wiki_index_read, wiki_page_list, wiki_page_get, wiki_log_read, wiki_link_resolve
- wiki_search_bm25  (use when wiki has grown beyond ~few hundred pages
                     or when question is keyword-heavy)
- (external: WebSearch, fallback only)

DO NOT write pages unless explicitly told to file back.

PROTOCOL:
1. wiki_index_read to get catalog.
2. If page count is high OR question has distinctive keywords:
      wiki_search_bm25(query, limit=20) → seed candidate list from ranked hits.
   Else: reason from the index alone to pick 3-10 candidates.
3. wiki_page_get each candidate.
4. If candidate page references [[wikilinks]] or [[page#section]] that add info: wiki_page_get them too.
5. Synthesize a citation-backed answer.
6. Return JSON: {answer, citations, pages_read, retrieval_mode: "bm25"|"index-only", proposed_new_page: null | {...}}

CITATION RULE: every claim needs [[page-slug]] reference. Quote exactly where possible.

IF WIKI HAS NOTHING RELEVANT: say so + suggest ingestion via /wiki:ingest.
```

### 10.3 Query variations

- **Default** (no flags): reads all scopes, synthesizes across. A page scoped to `project:cpm` is reachable from any query context.
- **`--scope project:<name>`**: narrows to pages tagged with that project. Omitting `<name>` resolves via `wiki_scope_detect` (errors if no active project).
- **`--scope global`**: excludes project-scoped pages; reads only globals.
- **`--raw`**: returns candidate pages + excerpts w/o synthesis.
- **`--file-back`**: if answer is durable, propose new page for user approval.

Scope is a *tag*, not a default filter. Nothing is hidden from a no-flag query — scoping is for precision, not gating.

### 10.4 Relationship to `proj_search_knowledge`

Both coexist, different purposes:
- `proj_search_knowledge`: grep-based, literal string match, fast, no synthesis. Scoped to proj tracking dirs.
- `wiki_query`: LLM-driven, synthesis-based, slower, answers "what do we know about X". Scoped to the wiki.

Rule of thumb: need exact string in proj data → `proj_search_knowledge`. Need synthesis across concepts → `/wiki:query`.

---

## 11. Lint (on-demand, two-tier)

### 11.1 Tier 1: Pure-data checks (MCP tools, no LLM)

Called directly by `/wiki:lint` skill. Each tool returns structured findings.

| Check | MCP tool | Algorithm |
|---|---|---|
| Orphans | `wiki_lint_orphans` | Graph walk: pages w/ 0 inbound + 0 outbound `links_to`. Skip if total pages < `orphan_min_page_count`. |
| Broken links | `wiki_lint_broken_links` | For each page's `links_to` + inline `[[wikilinks]]`: resolve → collect misses. |
| Broken section refs | `wiki_lint_broken_section_refs` | For each `[[page#section]]` ref: page resolves but section heading absent. |
| Category violations | `wiki_lint_category_violations` | Pages whose directory or frontmatter `category` is not in the active profile's configured list. |
| Stale pages | `wiki_lint_stale(days)` | Filter pages where `last_ingested < now - N days`. |
| Schema violations | `wiki_lint_schema` | For each page: check `config.yaml:required_frontmatter` against actual. |
| Duplicate slugs | `wiki_lint_duplicates` | Group by slug → collisions. |

### 11.2 Tier 2: Semantic checks (LLM-driven, skill-prompted)

Driven by `/wiki:lint` skill after Tier 1. Each check spawns a subagent:

| Check | LLM prompt summary |
|---|---|
| Contradictions | "Read these N pages w/ tag overlap. Report factual contradictions. JSON: `{contradictions: [{pages, claim_a, claim_b, evidence}]}`" |
| Deprecation candidates | "Read pages not referenced in last 90 days. Which are obsolete? JSON: `{candidates: [{page, reason}]}`" |
| Missing cross-refs | "Read page X. Which other pages should it link to but doesn't? JSON: `{suggestions: [{from, to, reason}]}`" |
| **Category cluster suggestions** | "Here are all pages w/ frontmatter tags + one-line summaries. The active profile declares these categories: `<list>`. Identify topical clusters of 3+ pages that don't fit any current category. Suggest new category names w/ the pages that would move into them. JSON: `{suggestions: [{proposed_category, rationale, pages: []}]}`" |

Subagents run in parallel via TeamCreate. Category-cluster suggestions, once accepted by the user, trigger a config.yaml update + page-migration step (move files to new category dir + update `category` frontmatter).

### 11.3 Lint skill flow

Single `/wiki:lint` skill. The `file-todo` fix option is available only when proj is installed + active (detected via `wiki_scope_detect.proj_present`).

```
1. Skill calls all Tier 1 MCP tools (parallel).
2. Skill collects Tier 1 findings.
3. Skill spawns Tier 2 subagents (parallel team) incl. category-cluster suggester.
4. Skill aggregates + presents findings in report form.
5. For each finding: user prompted [fix / file-todo (if proj present) / skip]
   - "fix" → skill calls wiki_page_write, wiki_page_delete, or config.yaml update
     (for accepted category-cluster suggestions: also moves files + updates frontmatter)
   - "file-todo" → skill calls todo_add in proj to track fix (proj-integrated only)
   - "skip" → no action
6. wiki_log_append(action="lint", title="full").
```

### 11.4 Cadence

On-demand only. No automatic/scheduled lint in v1. Config flag `wiki.lint_on_ingest: false` default. Future: optional scheduled lint via cpm `/schedule`.

---

## 12. Migration path + bootstrap

### 12.1 What changes for existing users

Standalone installs have nothing to migrate — the wiki starts empty + the user populates it via `/wiki:ingest` or `/wiki:bootstrap` w/ their own source paths. The table below covers the proj-adoption path.

| File/feature | Current | After | Migration |
|---|---|---|---|
| `NOTES.md` | Chronological prose notes, appended via `notes_append` | Deprecated when `sync.wiki.replace_notes_md: true`; wiki's `log.md` + pages take over | `/wiki:bootstrap` reads existing NOTES.md → creates wiki pages + log entries |
| `sessions/*.md` | Per-session archive | Unchanged (stays as raw audit trail) | Auto-ingest on `/proj:save` going forward when `sync.wiki.auto_ingest_sessions: true` |
| `todos/{id}/requirements.md` + `research.md` | Per-todo content | Unchanged (stays per-todo) | Optionally bootstrapped into wiki as category pages w/ `sources: [todo:<id>]` |
| Design docs (e.g. `overhaul-requirements.md`) | Raw files | Unchanged (stays in tracking dir) | Bootstrapped into wiki pages per section |
| `proj_search_knowledge` | grep over notes/requirements/research/decisions | Unchanged (coexists w/ wiki_query) | No migration |
| `proj.yaml` | No wiki config | Adds `sync.wiki:` integration section | Default opt-out; wizard writes flags (§4.4) or user edits yaml directly |
| `~/.claude/wiki.yaml` | Does not exist | Created by `/wiki:init` | New file; wiki runtime config |
| `memory/unified-recall-proposal.md` | Pending 26-day-old memory | Superseded | Mark deprecated; move to `memory/archive/` w/ pointer to this spec |

### 12.2 Bootstrap flow (`/wiki:bootstrap`)

Single flow. Behavior adapts to whether proj is loaded:

```
1. User: /wiki:bootstrap

2. Skill calls wiki_scope_detect:
   - proj_present=true + active project → proj-aware source discovery (step 3a)
   - proj absent or no active project → prompt user for sources (step 3b)

3a. Proj-aware source enumeration:
    - ~/projects/tracking/<project>/NOTES.md (if exists)
    - ~/projects/tracking/<project>/sessions/*.md (all)
    - ~/projects/tracking/<project>/todos/*/requirements.md + research.md
    - Design docs specified in proj.yaml: sync.wiki.bootstrap_docs

3b. Standalone source enumeration:
    - Skill prompts: "Source dir, file list, or URL batch?"
    - User provides paths / URLs / `search:<query>` terms.

4. Skill spawns team of subagents (TeamCreate, one per source category).
   Each subagent writes directly to ~/.claude/wiki/ via wiki_page_write.

5. Main agent waits for team, runs wiki_index_rebuild + wiki_search_index_refresh,
   then cross-references pass (scan bodies → add [[wikilinks]] / [[page#section]] refs).

6. Summary:
   - N pages created (by category)
   - M cross-references added
   - Log entry: ## [YYYY-MM-DD] bootstrap | <scope>
   - If proj-aware + NOTES.md present: prompt "Preserve NOTES.md at <path>.bak? [y/n]"

7. Post-bootstrap: if proj present, skill prompts to flip:
   - sync.wiki.bootstrap_completed: true
   - sync.wiki.replace_notes_md: true
   - sync.wiki.auto_ingest_sessions: true
```

### 12.3 First-time enablement

Unified flow:

1. `/wiki:init` — creates `~/.claude/wiki/` + `~/.claude/wiki.yaml` w/ `enabled: true`. Wizard (§4.4) prompts for category profile + session-ingest mapping. If proj is installed, wizard also prompts for `sync.wiki.*` flags.
2. `/wiki:bootstrap` — populates the wiki (proj-aware or standalone per §12.2).
3. `/wiki:ingest <source>` — incremental additions going forward.

**Rollback**:
- Proj integration off: flip `sync.wiki.enabled: false`; `notes_append` re-enables NOTES.md write path + router hook goes dormant. Wiki + its content remain untouched.
- Wiki off entirely: flip `wiki.enabled: false` in wiki.yaml. `/wiki:*` skills exit w/ "wiki disabled". Wiki directory can be deleted; proj is unaffected.

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
| Subagent (query) | WebSearch / MCP source fetch fails | Synthesize from wiki only. No fallback required. |
| `/proj:save` wiki ingest step | Subagent fails | Step reports error inline. Session file + NOTES.md still saved. User retries via `/wiki:ingest session:<file>`. |
| `wiki_search_bm25` | Index missing or stale | Tool returns `{hits: [], stale: true}`. Caller falls back to index-only retrieval. Skill may call `wiki_search_index_refresh` + retry. |

### 13.3 Idempotency guarantees

- `wiki_page_write(mode=upsert)` w/ identical body + frontmatter → no-op (content hash check).
- `/wiki:ingest <same-source>` within `reingest_cooldown_hours` → returns existing pages w/o rewrite unless `--force`.
- `/wiki:bootstrap` re-run → dedups by source ref in `sources[*].ref`.

### 13.4 Degradation

Wiki plugin is optional. If wiki MCP server is down or `wiki.enabled=false`:
- Proj works normally.
- `/wiki:*` skills return "wiki disabled; enable via /wiki:init".
- Router hook `notes_append` → `wiki_log_append` goes dormant; `notes_append` falls back to its normal NOTES.md write path.
- `/proj:save` skips its wiki ingest step silently.

---

## 14. Testing strategy

### 14.1 Unit tests (MCP tools, pure Python)

Target: 85%+ coverage on `plugins/wiki/server/server/tools/`.

- `wiki_page_write`: create, update, upsert, frontmatter validation, mode=create-on-existing error, atomic lock held, category-violation on profile mismatch
- `wiki_page_get`: exists, not-found, malformed frontmatter
- `wiki_page_list`: all filter combos (scope, category, tags, linked_from/to)
- `wiki_page_delete`: exists, not-found, updates backlinks
- `wiki_index_rebuild`: from empty pages/, from N pages, handles missing frontmatter, adapts to active profile categories
- `wiki_log_append`: format matches Karpathy prefix, atomic
- `wiki_log_read`: since filter, action filter, limit
- `wiki_lint_orphans`: 0 orphans, all orphans, mixed, respects `orphan_min_page_count`
- `wiki_lint_broken_links`: resolved, unresolved, aliases
- `wiki_lint_broken_section_refs`: page-resolves-section-missing, both-present, page-missing (delegates to broken_links)
- `wiki_lint_category_violations`: config-ok, dir-not-in-profile, frontmatter-not-in-profile
- `wiki_lint_stale`: no stale, all stale, threshold boundary
- `wiki_lint_schema`: passing + failing frontmatter
- `wiki_lint_duplicates`: no dupes, dupes, case-insensitive
- `wiki_link_resolve`: by slug, by alias, `page#section` (heading present / absent), collision handling
- `wiki_scope_detect`: proj installed + active, proj installed + no active, proj absent
- `wiki_search_bm25`: empty index, top-N ranking, filter combos (category/tags/scope_filter), graceful stale-index response
- `wiki_search_index_refresh`: empty pages/, N pages, handles deletion, idempotent repeat
- Profile loader: `software`/`personal`/`research`/`minimal` defaults, custom override, malformed profile

### 14.2 Integration tests (multi-tool flows)

- Full ingest cycle: `wiki_page_write` x N → `wiki_index_rebuild` → `wiki_search_index_refresh` → `wiki_lint_broken_links` returns 0
- Bootstrap simulation: feed synthetic NOTES.md → verify N pages created + log entry
- Router hook: mock `notes_append` fire → verify `wiki_log_append` invoked w/ correct params
- Concurrency: 2 concurrent `wiki_page_write` calls → serialization via lock
- BM25 round-trip: write N pages, refresh index, search for seeded term, verify correct page ranks first

### 14.3 Skill tests (LLM-in-loop)

Use skill-eval harness. Non-deterministic; rubric + tolerance-based.

- `/wiki:ingest` on a fixture URL → verify pages created w/ expected frontmatter + body contains key claims
- `/wiki:ingest mcp:<fixture-server>:page_get:<args>` → verify MCP-sourced ingest works
- `/wiki:query` on known corpus (small) → verify answer cites correct pages (index-only retrieval path)
- `/wiki:query` on large corpus → verify BM25 retrieval path fires + answer cites correct pages
- `/wiki:lint` on corpus w/ seeded contradictions + off-profile pages → verify Tier 2 contradiction + category-cluster detection

Marked `@skip_in_ci` by default; run manually or in nightly workflow.

### 14.4 End-to-end smoke test

- `/wiki:init` (picks `software` profile) → `/wiki:bootstrap` on fixture project → `/wiki:query "what do we know about X"` → verify answer references bootstrapped pages. All in a temp wiki dir.
- Parallel run w/ `personal` profile + synthetic journal fixtures → verifies profile swap doesn't regress.

---

## 15. Phased implementation sketch

For handoff to `superpowers:writing-plans` — not a full plan, just a suggested phasing.

**Phase 1: Core MCP tools + storage + profile loader** (~350 LOC, ~1 week)
- `wiki_page_write`, `wiki_page_get`, `wiki_page_list`, `wiki_page_delete`
- `wiki_index_read`, `wiki_index_rebuild`
- `wiki_log_append`, `wiki_log_read`
- `wiki_link_resolve` (incl. `page#section`), `wiki_scope_detect`
- Frontmatter parser + validator
- Profile loader: ship `software`, `personal`, `research`, `minimal` + allow custom
- Atomic lock infrastructure
- Unit tests

**Phase 2: Lint + BM25 + standalone skills** (~400 LOC, ~1.5 weeks)
- `wiki_lint_orphans/broken_links/broken_section_refs/category_violations/stale/schema/duplicates`
- `wiki_search_bm25` + `wiki_search_index_refresh` (first-class, not deferred)
- `/wiki:init` skill (creates wiki dir + wiki.yaml; wizard-driven profile pick)
- `/wiki:query` skill (BM25 + LLM-reads hybrid)
- `/wiki:lint` skill (Tier 1 only)
- Standalone wiki is fully usable at end of Phase 2

**Phase 3: Ingest + bootstrap** (~400 LOC, ~2 weeks)
- `/wiki:ingest` skill accepting all six source forms (URL, file, `session:`, `note:`, `search:`, `mcp:`)
- `/wiki:bootstrap` skill (proj-aware when proj loaded; prompts standalone otherwise)
- `/wiki:promote` skill
- Subagent protocol + prompts

**Phase 4: Proj touchpoints + wizard + Tier 2 lint** (~350 LOC, ~2 weeks)
- cpm installer wizard "wiki" section (enable, profile, session_ingest map, sync.wiki.* flags, bootstrap-now)
- Router hook: `notes_append` → `wiki_log_append`
- `/proj:save` final step: spawn wiki ingest subagent when enabled
- Tier 2 lint subagents: contradictions, deprecation, missing cross-refs, **category cluster suggestions**
- Proj-aware bootstrap source discovery inside `/wiki:bootstrap`
- Migration tooling for existing NOTES.md + sessions
- Sunset unified-recall-proposal.md

**Phase 5: Polish + docs** (~100 LOC, ~1 week)
- README for wiki plugin
- CLAUDE.md updates documenting wiki config flags
- End-to-end smoke test in CI (incl. both profile variants)
- Update cpm marketplace docs

**Total estimate**: ~1600 LOC, 7-8 weeks. (+~300 LOC + ~1 week vs prior plan; absorbs BM25-first-class + wizard + generic-framework docs.)

---

## 16. Open questions / future work

- **Vector DB layer at scale** (tracked as todo): embeddings-based semantic retrieval as a sidecar to BM25 once a wiki grows past ~thousands of pages. Adds embedding-model dep + vector store; markdown stays canonical → Obsidian vault remains usable. Deferred to v2 pending evidence of BM25-insufficient queries in the wild.
- **Category profile marketplace** (tracked as todo): ship a mechanism to publish + consume community-contributed profiles (e.g. `book-reading`, `incident-management`, `medical-research`, `legal-case-files`). Lowers onboarding friction for new domains.
- **v2 queue-based auto-ingest** (tracked as todo): replace the skill-integrated `/proj:save` ingest step w/ a queue mechanism (MCP hook writes to pending-ingests file; startup skill drains it next session). Revisit if skill-integrated approach causes user-visible latency.
- **Page versioning**: no version history in v1. Git in the wiki dir covers this externally. If we need in-wiki diff/history, add later.
- **Binary attachments**: `attachments/` dir exists but no tools to manage it. Add if user demand arises.
- **Cross-wiki federation**: if multiple cpm users want to share wiki subsets, design a federation layer. Not in v1.
- **Auto-promotion heuristic**: currently `/wiki:promote` is manual. Could add heuristic ("page referenced by N+ projects → auto-promote") if manual becomes burdensome.
- **Wiki UI**: Obsidian compatibility is a first-class side effect (plain markdown + `[[wikilinks]]` + `[[page#section]]` + BM25 sidecar is index-only). No custom UI planned. `docs/superpowers/wiki-obsidian-setup.md` could ship w/ optional Obsidian vault config.

---

## 17. Superseded work

- `~/.claude/projects/-home-raul-projects-claude-project-manager/memory/unified-recall-proposal.md` (2026-03-25) — addressed enhanced frontmatter, SessionStart context injection, `proj_memory_link`/`proj_memory_migrate` tools. This spec replaces that proposal: the wiki pattern unifies the same knowledge surface under a single entity-centric model rather than enhancing two parallel systems. Moving proposal to `memory/archive/` post-approval.
- `~/.claude/projects/-home-raul-projects-claude-project-manager/memory/interaction-mapping.md` + `recall-gap-analysis.md` (2026-03-25) — retained as reference material (they document the problem space this spec solves).

---

## Appendix A: Directory at-a-glance

```
~/.claude/
├── wiki.yaml                    # wiki runtime config (standalone-owned)
├── proj.yaml                    # proj config; gains optional sync.wiki.* section
└── wiki/                        # the wiki itself
    ├── index.md                 # catalog; machine-maintained
    ├── log.md                   # ledger; append-only
    ├── config.yaml              # profile + categories + lint rules
    ├── .lock                    # fcntl lock file (git-ignored)
    ├── .index/                  # BM25 sidecar (git-ignored)
    ├── pages/                   # category subdirs per active profile
    │   └── <category>/*.md
    └── attachments/             # optional binaries

plugins/wiki/                     # standalone plugin
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
│           ├── lint.py          # orphans/stale/broken/section-refs/schema/dupes/category
│           ├── search.py        # wiki_search_bm25 + wiki_search_index_refresh
│           ├── scope.py         # detect (+ proj_present)
│           ├── links.py         # resolve (page + page#section)
│           └── profile.py       # profile loader + category validator
└── skills/                      # the only user surface (/wiki:*)
    ├── init/SKILL.md
    ├── ingest/SKILL.md
    ├── query/SKILL.md
    ├── lint/SKILL.md
    ├── bootstrap/SKILL.md
    └── promote/SKILL.md

plugins/proj/                    # existing plugin; adds exactly 2 wiki touchpoints
├── hooks/
│   └── hooks.json               # adds wiki-log-on-notes-append entry
└── skills/
    └── save/SKILL.md            # modified: adds final wiki-ingest step when
                                 # sync.wiki.enabled and sync.wiki.auto_ingest_sessions
# (no /proj:wiki-* wrapper skills — removed in revised design)
```

## Appendix B: Glossary

- **Wiki page**: a markdown file w/ required frontmatter, living under `pages/<category>/`.
- **Slug**: normalized page identifier (lowercase, dashes; derived from title or filename).
- **Scope**: metadata tag (`global` or `project:<name>`) on each page; used for attribution + lint + optional query narrowing, not default query filtering.
- **`[[wikilink]]`**: inline page reference by slug or alias.
- **Section-link**: `[[page-slug#section-heading]]` — inline reference to a specific heading within a page. Obsidian-compatible.
- **Category profile**: named preset (`software` / `personal` / `research` / `minimal` / `custom`) declaring the list of category directories + defaults. Source of truth: `~/.claude/wiki/config.yaml`. Wizard prompts on first install.
- **BM25**: classic information-retrieval ranking algorithm scoring documents by term frequency × inverse document frequency. No ML, no embeddings. First-class v1 search layer via `wiki_search_bm25`.
- **qmd**: Karpathy's "query my documents" CLI — wraps BM25 over a markdown directory. Conceptually equivalent to our `wiki_search_bm25`; we embed BM25 directly in the plugin rather than shelling out.
- **Vector DB**: embeddings-based retrieval (e.g. Chroma/LanceDB). **Rejected in v1** — deferred to a tracked todo for tens-of-thousands-scale corpora (§16).
- **Ingest**: synthesize a source (URL / file / `session:` / `note:` / `search:` / `mcp:`) into wiki pages via LLM subagent.
- **Query**: read index + relevant pages (optionally narrowed via BM25) + synthesize a cited answer via LLM subagent.
- **Tier 1 lint**: pure-data checks via MCP tools (orphans, broken links, broken section refs, category violations, stale, schema, duplicates).
- **Tier 2 lint**: LLM-driven checks via subagents (contradictions, deprecation candidates, missing cross-refs, category cluster suggestions).
- **Bootstrap**: one-shot bulk import from existing knowledge (proj data when loaded, user-specified sources otherwise).
- **Model-centric**: synthesis happens in the LLM, driven by skill prompts. MCP = pure persistence + pure-data.
