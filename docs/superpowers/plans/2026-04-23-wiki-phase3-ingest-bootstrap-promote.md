# Wiki Plugin Phase 3: Ingest + Bootstrap + Promote — Implementation Plan

> **Historical record (deprecated TeamCreate-based orchestration)** —
> superseded by bare parallel `Agent` calls. See current SKILL.md files
> for the live design.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the 3 remaining standalone skills — `/wiki:ingest` (accepts 6 source types: URL, file, `session:`, `note:`, `search:`, `mcp:`, + free-form natural language), `/wiki:bootstrap` (bulk import), `/wiki:promote` (scope editing). At end of Phase 3, a user can install the wiki plugin, init it, populate it from any source (web, local files, MCP servers like confluence/jira/github), bootstrap from a directory of markdown, query + lint. Still no proj integration — that's Phase 4.

**Architecture:** All three skills are LLM-driven. They spawn forked-context subagents that use the Phase 1/2 MCP tools for persistence (`wiki_page_write`, `wiki_page_list`, `wiki_page_get`, `wiki_log_append`, `wiki_index_rebuild`, `wiki_search_bm25`, `wiki_link_resolve`, `wiki_scope_detect`) + external readers (`WebFetch`, `Read`, `WebSearch`, any installed MCP server) for source ingestion. No new MCP tools; no new Python code under `plugins/wiki/server/`. All value is in the SKILL.md prose prompts — how the LLM orchestrates extraction, dedup, cross-ref, merge, + log.

**Tech Stack:** Markdown (SKILL.md w/ YAML frontmatter), MCP tools (existing), Claude Code built-in tools (`AskUserQuestion`, `WebFetch`, `Read`, `WebSearch`, `Task`-via-general-purpose subagent), caveman-ultra prose convention.

**Spec reference:** `docs/superpowers/specs/2026-04-21-karpathy-wiki-plugin-design.md` — Phase 3 = §15 "Phase 3: Ingest + bootstrap" + §§9, 12 for ingest / bootstrap protocol detail. Prior plans: Phase 1 (`2026-04-23-wiki-phase1-core-tools-and-storage.md`, HEAD `101e2e0`), Phase 2 (`2026-04-23-wiki-phase2-lint-bm25-and-skills.md`, HEAD `9c60af5`).

---

## Scope (what's IN Phase 3, what's OUT)

**IN:**
- `plugins/wiki/skills/promote/SKILL.md` — edit a page's `scope` frontmatter: add `global`, remove `project:<name>`, or set scopes directly
- `plugins/wiki/skills/ingest/SKILL.md` — ingest one source into wiki via forked subagent:
  - Source resolver: LLM-driven (parses natural-language or explicit prefix)
  - 6 source readers: URL (`WebFetch`), file (`Read`), `session:<path>` (`Read` w/ proj-section-aware extraction), `note:<text>` (inline), `search:<query>` (`WebSearch` → top N URL reads), `mcp:<server>:<tool>:<args>` (dynamic MCP tool call)
  - Extract candidates → dedup via `wiki_page_list` + `wiki_link_resolve` + optional `wiki_search_bm25` for larger wikis
  - Write via `wiki_page_write` (create/update/upsert)
  - Cross-ref pass → populate `links_to` + inline `[[wikilinks]]`
  - Log entry + index rebuild
- `plugins/wiki/skills/bootstrap/SKILL.md` — bulk import from directory or file list:
  - Standalone mode: user specifies directory via `argument-hint` or AskUserQuestion prompt
  - Proj-aware mode (auto-detected via `wiki_scope_detect`): enumerate proj sources (NOTES.md, sessions/*, todos/*/requirements.md + research.md, `sync.wiki.bootstrap_docs`)
  - Dispatch team of subagents via TeamCreate (one per source category), each running the ingest protocol from `/wiki:ingest`
  - Post-bootstrap cross-ref sweep + index rebuild + log entry
- `plugins/wiki/README.md` Phase 3 status update
- `plugins/wiki/skills/ingest/references/` — subfolder w/ prompt-engineering references (source-resolver decision table, dedup heuristics, cross-ref strategy) that SKILL.md references but doesn't inline (keeps SKILL.md scannable)

**OUT (later phases):**
- Router hook `notes_append` → `wiki_log_append` — Phase 4
- `/proj:save` auto-ingest of session files — Phase 4
- Tier-2 lint (contradictions, deprecation, missing cross-refs, category clusters) — Phase 4
- Wizard integration — Phase 4
- Queue-based v2 ingest — tracked as todo 702
- Code cleanup follow-ups from 706/707 — separate cleanup task

---

## File Structure

All paths relative to repo root. Work happens on worktree `/home/raul/worktrees/cpm/feat-688-karpathy-wiki-plugin`.

```
plugins/wiki/skills/
├── init/SKILL.md         # existing (Phase 2)
├── query/SKILL.md        # existing (Phase 2)
├── lint/SKILL.md         # existing (Phase 2)
├── promote/SKILL.md      # NEW — Task 1
├── ingest/
│   ├── SKILL.md          # NEW — Task 2 (main skill, forked subagent)
│   └── references/       # NEW — Task 2
│       ├── source-readers.md       # canonical source-resolver decision table
│       ├── dedup-protocol.md       # extraction + dedup heuristics
│       └── subagent-prompt.md      # reusable subagent-prompt template
└── bootstrap/
    └── SKILL.md          # NEW — Task 3 (team dispatch over many sources)

plugins/wiki/README.md    # Modify — Task 4
```

**Responsibilities:**
- `promote/SKILL.md` — minimal: read page frontmatter, edit scope list, rewrite via `wiki_page_write(mode=update)`. No subagent. Interactive prompt for scope changes.
- `ingest/SKILL.md` — entry point. Spawns ONE subagent with the full ingest protocol. Subagent handles everything (read, extract, dedup, write, cross-ref, log, index).
- `ingest/references/*.md` — long-form reference material the SKILL.md can point to without bloating itself. Keeps SKILL.md under 250 lines (readability + LLM context usage).
- `bootstrap/SKILL.md` — enumerates sources (proj-aware or user-specified), dispatches `TeamCreate` with one agent per source category, each invoking the ingest protocol with a scoped source list. Waits for team completion, then runs a final cross-ref sweep + index rebuild + log entry.

---

## Task Breakdown

6 tasks total.

---

### Task 1: `/wiki:promote` skill

**Goal:** Minimal scope-editing skill. Reads a page's frontmatter, offers the user a choice (add global scope / remove project scopes / replace scope list outright), writes the updated page.

**Files:**
- Create: `plugins/wiki/skills/promote/SKILL.md`

- [ ] **Step 1.1: Create skill directory**

```bash
cd /home/raul/worktrees/cpm/feat-688-karpathy-wiki-plugin
mkdir -p plugins/wiki/skills/promote
```

- [ ] **Step 1.2: Write SKILL.md**

File: `plugins/wiki/skills/promote/SKILL.md`
```markdown
---
name: promote
description: Edit a wiki page's scope frontmatter — add `global` to promote for cross-project visibility, strip `project:<name>` tags, or replace scope list directly. Use when user says "promote wiki page", "wiki:promote <slug>", "make this page global", "demote page to project scope".
allowed-tools: mcp__plugin_wiki_wiki__wiki_page_get, mcp__plugin_wiki_wiki__wiki_page_write, mcp__plugin_wiki_wiki__wiki_page_list, mcp__plugin_wiki_wiki__wiki_log_append, AskUserQuestion
argument-hint: "<slug> [--category <cat>]"
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Change a page's `scope` frontmatter list. `$ARGUMENTS` = `<slug> [--category <cat>]`.

**1.** Parse `$ARGUMENTS`:
- First token = slug.
- Optional `--category <cat>` flag. If absent, `category=None` (flat pages/ layout).
- Empty slug → stop: "Slug required. Usage: `/wiki:promote <slug> [--category <cat>]`."

**2.** `mcp__plugin_wiki_wiki__wiki_page_get(slug, category)` → get current page.
- `error: not_found` → stop: "Page `<slug>` not found (category=`<cat>`). Run `/wiki:query <slug>` to locate it, or check `/wiki:lint` for duplicates."

**3.** Print current scope list: "Current scope: `<scope list>` (<N> tags)."

**4.** Prompt user action via `AskUserQuestion`:
- Question: "What scope change do you want for `<slug>`?"
- Header: "Scope op"
- Options (single-select):
    - `add-global` — append `global` to scope list if not already present. Keeps existing project scopes.
    - `strip-project` — remove all `project:*` entries from scope list. Keeps `global` + any other tags.
    - `make-global-only` — replace scope list w/ exactly `["global"]`.
    - `replace-manual` — prompt user (via AskUserQuestion Other field) for comma-separated scope list; replace entirely.

**5.** Compute new scope list per picked action. Validate:
- Every entry must be `"global"` or start w/ `"project:"`. If user enters anything else via manual replace, confirm w/ them before proceeding (scope tags are unstructured — wiki doesn't reject them, but lint won't understand).

**6.** If new scope == current scope: skip write. Print "Scope unchanged (no-op)." + stop.

**7.** Otherwise, write via `mcp__plugin_wiki_wiki__wiki_page_write`:
- Build full frontmatter: copy existing `frontmatter` dict from step 2, set `scope = <new list>`, leave body unchanged.
- Call `wiki_page_write(slug, category, frontmatter=<merged>, body=<existing-body>, mode="update")`.
- Err from write → print err + stop.

**8.** Append log entry:
- `mcp__plugin_wiki_wiki__wiki_log_append` w/ `action=promote`, `title=<slug>`, `body="scope: <old list> → <new list>"`.

**9.** Print confirmation:
- "Promoted `<slug>`: scope now `<new list>`."

## Err handling

- Wiki disabled / missing → "Wiki not initialized. Run `/wiki:init` first." + stop.
- Page not found → step 2 err path.
- Write fails (lock contention, disk full, etc.) → print err + don't log.
- Log-append fails → warn but don't rollback — the write already succeeded.
```

- [ ] **Step 1.3: Verify frontmatter**

```bash
head -10 plugins/wiki/skills/promote/SKILL.md
```
Expected: YAML frontmatter visible w/ name, description, allowed-tools, argument-hint.

- [ ] **Step 1.4: Commit**

```bash
git add plugins/wiki/skills/promote/
git commit -m "feat(wiki/688): add /wiki:promote skill for scope editing"
```

---

### Task 2: `/wiki:ingest` skill + references

**Goal:** The heart of Phase 3. Interactive entry point that spawns ONE forked subagent with the full ingest protocol: source resolution (6 source types + natural language) → read → extract candidates → dedup → write pages → cross-ref → log + index. This is the largest single skill in the plugin.

**Strategy:** SKILL.md stays scannable (≤250 lines) by pointing at three reference files for long-form detail. The reference files are canonical — future phases (Phase 4 wizard, `/proj:save` auto-ingest) can reuse them by reference.

**Files:**
- Create: `plugins/wiki/skills/ingest/SKILL.md`
- Create: `plugins/wiki/skills/ingest/references/source-readers.md`
- Create: `plugins/wiki/skills/ingest/references/dedup-protocol.md`
- Create: `plugins/wiki/skills/ingest/references/subagent-prompt.md`

- [ ] **Step 2.1: Create skill directory tree**

```bash
cd /home/raul/worktrees/cpm/feat-688-karpathy-wiki-plugin
mkdir -p plugins/wiki/skills/ingest/references
```

- [ ] **Step 2.2: Write source-readers reference**

File: `plugins/wiki/skills/ingest/references/source-readers.md`
```markdown
# Source-Reader Reference

Canonical mapping from the user's `<source>` argument to the right reader. Used by `/wiki:ingest` + (Phase 4) `/proj:save` auto-ingest.

## Explicit prefix forms (highest priority)

| Prefix | Reader | Notes |
|---|---|---|
| `https://` / `http://` | `WebFetch` | Web article, gist, blog, HTML. |
| Absolute / relative file path | `Read` | Local md, text, transcripts. PDFs via Read's PDF support. |
| `session:<path>` | `Read` | Proj session file. Apply `wiki.yaml::session_ingest.section_map` for section-aware extraction. |
| `note:<text>` | inline | Free-form note. No external fetch. Use when user wants to capture a thought without a source doc. |
| `search:<query>` | `WebSearch` | Top 3-5 results; iterate each result URL as a URL source. |
| `mcp:<server>:<tool>:<args>` | dynamic MCP call | `args` is a comma-separated `key=value` list. E.g. `mcp:confluence:page_get:space=HR,title=Onboarding`. Subagent must ensure the named server + tool are both available; error cleanly if not. |

## Free-form resolution (LLM-driven)

If `<source>` does not match any explicit prefix, the subagent resolves via content analysis:

| Phrase pattern | Resolved form |
|---|---|
| Contains a bare URL | URL form (WebFetch) |
| `"the <something> page from confluence"` + confluence MCP installed | `mcp:confluence:page_get:...` w/ args inferred from context |
| `"issue/ticket <KEY>"` + jira MCP installed | `mcp:jira:jira_get_issue:<KEY>` |
| `"repo readme for <owner/repo>"` + github MCP installed | `mcp:github:repo_readme:<owner/repo>` (adapt to actual github MCP tool names) |
| `"search for X online"` / `"look up X"` | `search:<X>` |
| `"this file <path>"` or bare filesystem path | file Read |
| `"my note: <text>"` / `"remember: <text>"` | `note:<text>` |
| Ambiguous / missing detail | `AskUserQuestion` to disambiguate before fetching |

## Resolution algorithm

1. If source starts w/ `https://`, `http://`, `session:`, `note:`, `search:`, or `mcp:` → use the matching explicit reader.
2. Else if source is a valid filesystem path → file Read.
3. Else parse free-form text per the patterns above.
4. Log the resolved form in the ingest JSON summary so user sees what was chosen.
5. On ambiguity: AskUserQuestion w/ 2-4 options covering most likely interpretations.

## MCP-source-tool discovery

When resolving `mcp:*` or natural-language forms that map to MCP tools, check available tools via the subagent's tool registry (list_tools-equivalent). Match tool names by heuristic:

- confluence: `*page_get*`, `*page*search*`
- jira: `*issue_get*`, `*search*issue*`
- github: `*readme*`, `*file_get*`, `*issue_get*`, `*pr_get*`
- linear: `*issue_get*`, `*project_get*`

If none match, fall back to `AskUserQuestion`: "Which MCP tool should fetch this? Options: `<list of available tool names that look relevant>`."
```

- [ ] **Step 2.3: Write dedup-protocol reference**

File: `plugins/wiki/skills/ingest/references/dedup-protocol.md`
```markdown
# Dedup + Merge Protocol

Used by `/wiki:ingest`'s subagent during entity extraction.

## Extraction

After reading the source, the subagent extracts 3-15 candidate entities. Each candidate has:

- `title` — proposed page title (human-readable, title case).
- `slug` — derived from title (lowercase, hyphens, stripped of punctuation).
- `category` — one of the active profile's categories (from `wiki_page_list` or config.yaml).
- `tags` — 2-6 descriptive tags.
- `summary` — one-line description for index.md.
- `body_candidate` — full markdown body.
- `evidence` — which source lines / paragraphs support this entity.

## Dedup check per candidate

For each candidate:

1. `wiki_page_list(tags=<candidate.tags>, scope_filter=<scope>)` — find tag-overlapping pages.
2. `wiki_link_resolve(candidate.slug)` — exact / alias match.
3. If wiki has >~200 pages: `wiki_search_bm25(query=<candidate.title>, limit=5)` — keyword-ranked candidates.
4. Union the three result sets. For each existing page, compute overlap score:
   - Title similarity (word overlap / token match).
   - Tag overlap (Jaccard).
   - Summary-to-body cosine (LLM reads existing page's body + compares).

## Decision matrix

| Situation | Action |
|---|---|
| Exact slug match in candidate set | Treat as update (merge into existing page) |
| Alias match | Update the aliased page |
| 1 existing page w/ high-overlap (≥0.6 title similarity OR ≥3 shared tags) | Update — merge candidate body into existing. Preserve existing claims; add new; reconcile contradictions by noting both. |
| Multiple existing pages w/ high-overlap | Pause + AskUserQuestion: "This concept seems related to `[<list>]`. Merge into which, or create new?" |
| No high-overlap match | Create new page |

## Merge semantics (update case)

When updating an existing page:

1. `wiki_page_get(slug, category)` → get current frontmatter + body.
2. Merge frontmatter:
   - `tags`: union of existing + new (dedup).
   - `links_to`: union of existing + new (dedup). Cross-ref pass (below) adds more.
   - `sources`: append new `{type, ref, ingested_at}` entry. Keep all prior entries.
   - `last_ingested`: current UTC datetime.
   - Other fields: preserve existing; let LLM decide if new source contradicts (rare).
3. Merge body:
   - LLM reads existing body + new-content draft.
   - Preserves prior claims. Adds new sections for genuinely new info.
   - If a section exists on both: LLM picks the clearer version, or merges bullet-wise.
   - Explicit conflict (prior: "X is true"; new: "X is false") → write both as claims w/ source attribution: `Per [source-a]: X is true. Per [source-b]: X is false.` Flag for user review (print warning in final output).

## Cross-ref pass (after all candidates written)

1. Walk each new/updated page's body.
2. For each noun phrase that matches another page's title or alias (via `wiki_link_resolve`): insert `[[wikilink]]` replacement inline.
3. Update the page's `links_to` frontmatter (union of existing + newly inserted).
4. Write back via `wiki_page_write(mode="update")`.

## Idempotency safeguards

- Ingest same source twice within `reingest_cooldown_hours` (default 24) → subagent detects via `sources[*].ref` + returns existing pages. Only re-ingests w/ `--force` flag.
- Identical-content upsert → `wiki_page_write(mode="upsert")` returns `noop: true` (already handled by the tool).
```

- [ ] **Step 2.4: Write subagent-prompt reference**

File: `plugins/wiki/skills/ingest/references/subagent-prompt.md`
```markdown
# Ingest Subagent Prompt Template

Used by `/wiki:ingest` (Phase 3) + `/wiki:bootstrap` (Phase 3) + `/proj:save` (Phase 4). Reusable template — skills substitute `{source}`, `{scope}`, `{wiki_config}` + dispatch a general-purpose subagent with the resulting prompt.

## Template

```
You are the ingest agent for the Karpathy LLM wiki at ~/.claude/wiki/.

SOURCE: {source}
SCOPE: {scope}
CONFIG: {wiki_config}  (profile, categories, required_frontmatter, session_ingest.section_map)

MCP TOOLS AVAILABLE:
- mcp__plugin_wiki_wiki__wiki_page_list, wiki_page_get, wiki_page_write, wiki_page_delete
- mcp__plugin_wiki_wiki__wiki_index_read, wiki_index_rebuild
- mcp__plugin_wiki_wiki__wiki_log_append, wiki_log_read
- mcp__plugin_wiki_wiki__wiki_link_resolve
- mcp__plugin_wiki_wiki__wiki_search_bm25
- (read-only: WebFetch, Read, Grep, WebSearch, dynamic MCP tool calls)

DO NOT write files directly. Always go through wiki_page_write. Do NOT invoke
any wiki_* tool outside this list (no lint tools during ingest — lint is a
separate skill).

SOURCE RESOLUTION (step 0, before any fetch):
- If SOURCE starts with a known prefix (https://, http://, session:, note:,
  search:, mcp:, or a valid filesystem path), use the matching reader.
- Else parse free-form text per the `source-readers.md` reference.
- On ambiguity: use AskUserQuestion to disambiguate BEFORE fetching anything.
- Log the resolved form as part of your JSON return value.

PROTOCOL:
1. Resolve + read source using the matching reader.
2. Extract 3-15 candidate entities per the `dedup-protocol.md` extraction rules.
   Each candidate has: title, slug, category, tags, summary, body_candidate, evidence.
3. For each candidate, run dedup per `dedup-protocol.md` decision matrix:
   wiki_page_list → wiki_link_resolve → wiki_search_bm25 (if wiki ≥200 pages).
4. For candidates w/ no high-overlap match: construct full frontmatter + body →
   wiki_page_write(mode="create"). Required frontmatter: title, tags, links_to,
   scope (from SCOPE), sources (from this ingest), last_ingested (now UTC).
5. For candidates w/ high-overlap match: wiki_page_get existing → merge per
   `dedup-protocol.md` merge semantics → wiki_page_write(mode="update").
   Preserve prior sources[]; append new entry.
6. Cross-ref pass: for each written page, scan body for noun phrases that
   match other page titles/aliases via wiki_link_resolve → insert [[wikilinks]]
   inline → update links_to frontmatter → wiki_page_write(mode="update").
7. wiki_log_append(action="ingest", title=<short-source-ref>, body=<JSON summary
   of what was created/updated>).
8. wiki_index_rebuild.
9. Return JSON: {
     source_resolved: <form>,
     pages_created: [slug, ...],
     pages_updated: [slug, ...],
     cross_refs_added: N,
     contradictions_flagged: [<details if any>],
     warnings: [<if any>],
   }

FRONTMATTER REQUIRED: title, tags, links_to, scope, sources, last_ingested.
Minimal additional: aliases (optional list).

ERROR HANDLING:
- wiki_page_write(mode="create") on existing page → switch to mode="update".
- Dedup ambiguity (2+ high-overlap matches) → prefer updating the MOST RECENT
  (by last_ingested) over creating new. In ambiguous cases, ask user via
  AskUserQuestion before writing.
- Source fetch failure (WebFetch error, file not found, MCP tool missing) →
  abort. Write no pages. Return JSON error: {error: "...", source: "..."}.
- Cross-ref pass failure on a single page → warn but don't rollback. Other
  pages' writes persist.

IDEMPOTENCY:
- Before ingesting, check wiki_log_read(action_filter="ingest") for a recent
  entry w/ matching source ref within `reingest_cooldown_hours`. If found,
  return early w/ existing pages (skip re-ingest) unless user passed --force.
```

## Invocation

```python
# In the skill (conceptual — actual call is via Task tool with general-purpose agent type)
Task(
    subagent_type="general-purpose",
    description="Ingest <source> into wiki",
    prompt=template.format(
        source=<user-source>,
        scope=<scope-from-wiki_scope_detect>,
        wiki_config=<json dump of profile + categories + session_ingest.section_map>,
    ),
)
```

The subagent runs the protocol + returns the JSON summary. The skill renders the summary for the user.
```

- [ ] **Step 2.5: Write the main SKILL.md**

File: `plugins/wiki/skills/ingest/SKILL.md`
```markdown
---
name: ingest
description: Ingest a source (URL, file, session file, free-form note, web search, or any installed MCP server's content) into the wiki. Runs a forked subagent that extracts entities, dedups against existing pages, writes/updates pages, adds cross-references, + logs the action. Use when user says "ingest X into wiki", "wiki:ingest <source>", "add this to wiki", "pull this page into wiki".
allowed-tools: mcp__plugin_wiki_wiki__wiki_log_read, mcp__plugin_wiki_wiki__wiki_scope_detect, mcp__plugin_wiki_wiki__wiki_page_list, mcp__plugin_wiki_wiki__wiki_index_read, AskUserQuestion, Task, Read
argument-hint: "<source> [--scope <scope>] [--force]"
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Ingest one source into the wiki. Delegates to a forked subagent that runs the full ingest protocol.

**Reference docs** (read when needed during source-resolution ambiguity or dedup edge cases):
- `references/source-readers.md` — source prefix + free-form resolution table
- `references/dedup-protocol.md` — extraction, dedup decision matrix, merge semantics, cross-ref
- `references/subagent-prompt.md` — the subagent prompt template

**1.** Parse `$ARGUMENTS`:
- First token / URL / path = source spec. Everything before a `--` flag counts as the source.
- Flags: `--scope <val>`, `--force`.
- Empty source → stop: "Source required. Usage: `/wiki:ingest <source> [--scope <scope>] [--force]`. Supported: URL, file path, `session:<path>`, `note:<text>`, `search:<query>`, `mcp:<server>:<tool>:<args>`, or free-form natural language."

**2.** `mcp__plugin_wiki_wiki__wiki_scope_detect` → scope info.
- If `--scope` flag passed: use that value (validate `global` or `project:<name>`).
- Else if `proj_present and scope != "global"`: use returned scope.
- Else: `global`.

**3.** `mcp__plugin_wiki_wiki__wiki_index_read` → sanity check.
- `content == ""` → stop: "Wiki empty — but init is complete. Run `/wiki:ingest <source>` to populate. (Hint: you're trying to do that now; but run `/wiki:init` first if you haven't.)"
- Count total pages from category sums. Pass as `wiki_page_count` into subagent prompt for BM25 threshold decision.

**4.** Idempotency check (unless `--force`):
- `mcp__plugin_wiki_wiki__wiki_log_read(action_filter="ingest")` → list recent ingest entries.
- Read `wiki.yaml::reingest_cooldown_hours` (default 24).
- If any recent entry has `title` matching the current source (substring match or exact slug match) within cooldown → print "Source recently ingested (see log entry `<date>`). Skipping. Re-run w/ `--force` to re-ingest." + stop.

**5.** Read wiki config for the subagent prompt:
- `Read ~/.claude/wiki.yaml` → extract `session_ingest.section_map`.
- `Read ~/.claude/wiki/config.yaml` → extract `profile`, `categories`, `required_frontmatter`.
- Bundle into a single JSON string for the subagent (the "CONFIG" placeholder).

**6.** Construct subagent prompt:
- Read `references/subagent-prompt.md` → the template.
- Substitute `{source}` = user's source (trimmed), `{scope}` = chosen scope, `{wiki_config}` = JSON from step 5.
- Append: "After completing the protocol, return the JSON summary as your final output. Do not add conversational preamble."

**7.** Dispatch subagent via `Task`:
- `subagent_type="general-purpose"` (forked context).
- `description="Ingest <source-short> into wiki"` (truncate source to 60 chars).
- `prompt=<the substituted template>`.
- Wait for completion.

**8.** Parse subagent JSON return value. Handle:
- `error` present → print err + "Ingest failed. No pages written. Re-run w/ different source or check `/wiki:lint` for existing pages that might conflict."
- `pages_created + pages_updated == []` → print "No new pages derived from source. The source may have no extractable content, or all content was already in the wiki."
- Otherwise proceed to step 9.

**9.** Render summary to user:
```
## Ingest complete

**Source**: `<resolved-form>`
**Scope**: `<scope>`

**Pages created** (<N>):
- `<slug-1>` (<category>) — <summary line from subagent>
- ...

**Pages updated** (<N>):
- `<slug-1>` (<category>) — <what changed>
- ...

**Cross-refs added**: <N>

<if contradictions_flagged>
### ⚠️ Contradictions detected

- `<page-slug>`: prior claim `<claim-a>` vs new claim `<claim-b>`. Resolve via `/wiki:query <slug>` + manual edit.
</if>

<if warnings>
### Warnings

- <warning>
</if>

Log entry appended. Run `/wiki:lint` to check integrity.
```

## Err handling

- Wiki disabled / missing → "Wiki not initialized. Run `/wiki:init` first." + stop.
- Scope-detect fails → use `global` (log warning in final output).
- Subagent dispatch fails (`Task` returns error) → print err + suggest `--force` or re-run.
- Subagent returns malformed JSON → print raw output + "Ingest subagent returned unparseable output. This is a bug — please report."
```

- [ ] **Step 2.6: Verify skill structure**

```bash
ls plugins/wiki/skills/ingest/
ls plugins/wiki/skills/ingest/references/
wc -l plugins/wiki/skills/ingest/SKILL.md
```
Expected: SKILL.md under 250 lines; 3 reference files present.

- [ ] **Step 2.7: Commit**

```bash
git add plugins/wiki/skills/ingest/
git commit -m "feat(wiki/688): add /wiki:ingest skill w/ 6-source protocol + subagent prompt refs"
```

---

### Task 3: `/wiki:bootstrap` skill

**Goal:** Bulk import. Auto-detects proj (via `wiki_scope_detect`) for proj-aware source enumeration; otherwise prompts user for a directory or source list. Dispatches a team of subagents (one per source category), each running the ingest protocol.

**Files:**
- Create: `plugins/wiki/skills/bootstrap/SKILL.md`

- [ ] **Step 3.1: Create skill directory**

```bash
cd /home/raul/worktrees/cpm/feat-688-karpathy-wiki-plugin
mkdir -p plugins/wiki/skills/bootstrap
```

- [ ] **Step 3.2: Write SKILL.md**

File: `plugins/wiki/skills/bootstrap/SKILL.md`
```markdown
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
- Each agent gets a subset of sources from `references/subagent-prompt.md` template — with a modification: the prompt lists multiple sources + asks the agent to iterate, running the full ingest protocol per source.
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

<contradictions_flagged if any>

Log entry appended. Index + BM25 refreshed. Run `/wiki:lint` to check integrity.
```

## Err handling

- Wiki disabled / missing → "Wiki not initialized. Run `/wiki:init` first." + stop.
- Proj-aware mode but no active project → fall back to standalone mode w/ prompt.
- Any subagent in the team fails → other agents continue; report failure per-source in the summary. Partial success is OK.
- Cross-ref sweeper fails → warn but don't roll back — per-page `links_to` may be incomplete; user can re-run `/wiki:lint` to find broken links.
- Empty source list (standalone directory has no .md files) → stop: "No .md files found at `<path>`. Nothing to bootstrap."
```

- [ ] **Step 3.3: Verify skill structure**

```bash
ls plugins/wiki/skills/bootstrap/
head -15 plugins/wiki/skills/bootstrap/SKILL.md
```
Expected: directory + SKILL.md; frontmatter visible.

- [ ] **Step 3.4: Commit**

```bash
git add plugins/wiki/skills/bootstrap/
git commit -m "feat(wiki/688): add /wiki:bootstrap skill w/ team dispatch + cross-ref sweep"
```

---

### Task 4: Smoke-test `just check` + skill discovery

**Goal:** Verify nothing broke. Skills don't have Python code to lint, but the Phase 1/2 pytest suite should still pass + ruff/basedpyright on `server/` should remain clean.

**Files:** none modified; this is a verification task.

- [ ] **Step 4.1: Phase 1/2 test suite**

```bash
cd /home/raul/worktrees/cpm/feat-688-karpathy-wiki-plugin/plugins/wiki/server
uv run pytest --cov=server 2>&1 | tail -6
```
Expected: same 163 tests pass, ≥85% coverage (Phase 3 adds no tests, so counts unchanged).

- [ ] **Step 4.2: `just check` clean**

```bash
cd plugins/wiki/server && just check
```
Expected: 0 errors (Phase 3 touches no Python code).

- [ ] **Step 4.3: Skill directory listing**

```bash
ls plugins/wiki/skills/
```
Expected: `bootstrap  ingest  init  lint  promote  query` (6 skills, all from Phase 1 + 2 + 3).

- [ ] **Step 4.4: Skill frontmatter sanity — verify all parseable**

```bash
for s in plugins/wiki/skills/*/SKILL.md; do
  echo "--- $s ---"
  head -10 "$s"
done
```
Expected: each file opens w/ `---\nname: <name>\ndescription: ...` YAML frontmatter. No broken YAML.

- [ ] **Step 4.5: No commit unless coverage / lint regressed**

If step 4.1 or 4.2 surfaces regressions, investigate. Otherwise no commit needed for this task — Phase 3 is pure markdown + directory structure; infra commits happen in Tasks 1-3 + 5.

---

### Task 5: Update plugin README

**Files:**
- Modify: `plugins/wiki/README.md` — update Phase status

- [ ] **Step 5.1: Edit README**

In `plugins/wiki/README.md`, update the `## Phase status` section from:

```markdown
- **Phase 1** — core persistence tools (page CRUD, index, log, links, scope). ✅
- **Phase 2** — BM25 search (`wiki_search_bm25`, `wiki_search_index_refresh`), 7 Tier-1 lint tools (`wiki_lint_*`), 3 standalone skills (`/wiki:init`, `/wiki:query`, `/wiki:lint`). ✅
- **Phase 3** — ingest + bootstrap (URL, file, session, note, search, MCP sources). Pending.
- **Phase 4** — proj touchpoints (router hook, `/proj:save` integration, wizard), Tier-2 semantic lint. Pending.
- **Phase 5** — polish + docs. Pending.
```

to:

```markdown
- **Phase 1** — core persistence tools (page CRUD, index, log, links, scope). ✅
- **Phase 2** — BM25 search (`wiki_search_bm25`, `wiki_search_index_refresh`), 7 Tier-1 lint tools (`wiki_lint_*`), 3 standalone skills (`/wiki:init`, `/wiki:query`, `/wiki:lint`). ✅
- **Phase 3** — 3 more skills (`/wiki:ingest`, `/wiki:bootstrap`, `/wiki:promote`). Ingest accepts 6 source types (URL, file, `session:`, `note:`, `search:`, `mcp:`) + free-form natural language. Bootstrap is proj-aware. ✅
- **Phase 4** — proj touchpoints (router hook, `/proj:save` integration, wizard), Tier-2 semantic lint. Pending.
- **Phase 5** — polish + docs. Pending.
```

Also, below Phase status, append a section documenting the ingest-protocol reference files:

```markdown

## Ingest protocol references

The `/wiki:ingest` + `/wiki:bootstrap` skills share a set of reference docs
at `plugins/wiki/skills/ingest/references/`:

- `source-readers.md` — canonical mapping of source prefixes + free-form
  natural-language resolution to readers (URL / file / session / note /
  search / mcp).
- `dedup-protocol.md` — entity extraction, dedup decision matrix, merge
  semantics, cross-ref pass.
- `subagent-prompt.md` — the reusable forked-subagent prompt template.

These files are part of the plugin; future phases (`/proj:save` auto-ingest
in Phase 4) will reuse them by reference rather than duplicating the prose.
```

- [ ] **Step 5.2: Commit**

```bash
git add plugins/wiki/README.md
git commit -m "docs(wiki/688): update README w/ Phase 3 completion + ingest-protocol refs"
```

---

### Task 6: Phase-3 close — final code review

**Goal:** Dispatch a final reviewer subagent. Phase 3 has almost no Python code (it's all SKILL.md prose), so the review focuses on: (1) frontmatter correctness, (2) prose quality + actionability for the LLM that will invoke the skill, (3) reference-file coherence w/ SKILL.md flow, (4) no regressions in Phase 1/2 code.

- [ ] **Step 6.1: Get SHAs**

```bash
cd /home/raul/worktrees/cpm/feat-688-karpathy-wiki-plugin
git log --oneline 9c60af5..HEAD
```
Expected: 4-5 commits (promote, ingest, bootstrap, README; optionally a smoke-fix if Task 4 found anything).

- [ ] **Step 6.2: Dispatch reviewer**

Use the `superpowers:code-reviewer` subagent w/ these params:
- BASE_SHA: `9c60af5` (Phase 2 HEAD, post review fixes)
- HEAD_SHA: current HEAD
- DESCRIPTION: "Phase 3 final review — 3 new skills (ingest/bootstrap/promote) + ingest-protocol reference docs. No new Python code; all value in SKILL.md prose + reference files."

Focus areas for the reviewer:
1. **SKILL.md frontmatter** — `name`, `description`, `allowed-tools`, `argument-hint`, and (for ingest) `context: fork + agent: general-purpose` correct? Tool names fully qualified (`mcp__plugin_wiki_wiki__*`)?
2. **Prose actionability** — each step of each skill has concrete code/tool calls, not vague descriptions. The LLM reading this should be able to execute end-to-end w/o asking the user for clarification (except where the skill explicitly prompts).
3. **Reference file coherence** — SKILL.md points at reference files for long-form detail; the pointed-to content matches what the skill flow requires.
4. **Source-resolver completeness** — `source-readers.md` table covers every form the spec §9.1 mentions (URL / file / `session:` / `note:` / `search:` / `mcp:` + free-form).
5. **Dedup protocol** — merge semantics in `dedup-protocol.md` match spec §9's merge rules (preserve prior `sources[]`, append new; union `links_to`; union `tags`; update `last_ingested`).
6. **Subagent prompt reusability** — `subagent-prompt.md` works for both single-source ingest + bootstrap batch-ingest + (Phase 4) `/proj:save` session auto-ingest.
7. **Caveman-ultra style** — SKILL.md bodies match the cpm house style; frontmatter field values are normal English.
8. **Err handling parity** — each skill handles: wiki-disabled, subagent failure, partial success, no-content-extracted; consistent patterns.
9. **Spec coverage** — Phase 3 plan items from spec §15 all represented in the three skills.

Address any critical/important issues before closing. File minors as a Phase-3 followup todo.

- [ ] **Step 6.3: Address any issues or file followups**

If reviewer surfaces must-fix items: apply them, commit, re-verify. If they're minor: file a consolidated todo like todos 706/707.

- [ ] **Step 6.4: No blanket commit unless fixes landed**

If review is clean, Phase 3 is done. If fixes landed, the last commit's SHA is the new Phase-3 HEAD.

---

## Verification

At phase-end, verify:

1. **6 skills installed:** `ls plugins/wiki/skills/` → `bootstrap  ingest  init  lint  promote  query`.
2. **Each SKILL.md has valid YAML frontmatter** — verify Task 4.4.
3. **Ingest references present:** `ls plugins/wiki/skills/ingest/references/` → `dedup-protocol.md  source-readers.md  subagent-prompt.md`.
4. **Phase 1/2 test suite still green** — Task 4.1.
5. **`just check` clean in `plugins/wiki/server/`** — Task 4.2.
6. **README reflects Phase 3 completion** — Task 5.
7. **Manual end-to-end (optional but recommended):** in a scratch Claude session, install the worktree as a plugin, run `/wiki:init` → author a handful of pages via `/wiki:ingest note:<text>` → `/wiki:query` → `/wiki:lint` → `/wiki:promote`. Confirm each flow works. This surface test catches SKILL.md prose issues the reviewer may not have hit.

## Handoff to Phase 4

After Phase 3 lands, Phase 4 adds:

- **Router hook:** `notes_append` → `wiki_log_append` (when `sync.wiki.capture_notes_as_log: true`). Registered by proj plugin via `hooks.yaml`.
- **`/proj:save` integration:** final skill step that spawns the ingest subagent on the fresh session file (when `sync.wiki.auto_ingest_sessions: true`). Reuses `references/subagent-prompt.md`.
- **Wizard integration:** installer prompts for profile, session-ingest section map, `sync.wiki.*` flags, bootstrap-now (queued).
- **Tier-2 semantic lint:** contradictions, deprecation candidates, missing cross-refs, category-cluster suggestions. New LLM-driven lint subagents dispatched by the existing `/wiki:lint` skill.
- **Migration tooling:** `/proj:wiki-enable` convenience skill (writes `sync.wiki.*` flags). Sunset unified-recall-proposal memory file.

Phase 4 plan to be written after Phase 3 is ready to merge.

---

## Self-review notes (pre-handoff)

- **Spec §9.1 coverage:** all 6 source forms represented in `source-readers.md` + exercised by the subagent protocol in `subagent-prompt.md`. ✓
- **Spec §12.2 bootstrap:** `/wiki:bootstrap` covers proj-aware + standalone modes, subagent team dispatch, cross-ref sweep. ✓
- **Spec §7.1 scope auto-detection:** all 3 skills call `wiki_scope_detect` at start. ✓
- **Spec §13 err handling:** each skill's "Err handling" block covers wiki-disabled, write failure, subagent failure. ✓
- **No new Python code:** Phase 3 ships no production Python or tests. The whole Phase is prose. Aligns with the plan estimate of "~400 LOC, 2 weeks" — LOC includes the reference docs + all three SKILL.md bodies (~400 lines combined).
