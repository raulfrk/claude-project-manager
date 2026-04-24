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

Scope: **same-category only**. For a page in category X, this pass considers
links to other pages within category X. Cross-category links are not added
here; `/wiki:lint` tier-2 sweep fills them in separately. Rationale: most
ingest-time noun-phrase matches across categories are noise; restricting to
same-category cuts wiki_link_resolve calls roughly proportional to the
category-to-wiki size ratio.

1. For each new/updated page in category X, call `wiki_page_list(category=X)`
   once to obtain the candidate target set (pages within category X only).
   Reuse this list across all candidates written into the same category in
   this ingest pass — no need to re-call per page.
2. Walk the page's body. For each noun phrase that matches the title or alias
   of ANOTHER page in the candidate target set, insert `[[wikilink]]`
   replacement inline. Use `wiki_link_resolve(link)` for alias confirmation
   on candidates from the set; do NOT pass any category/scope arg to
   `wiki_link_resolve` itself.
3. Update the page's `links_to` frontmatter (union of existing + newly inserted).
4. Write back via `wiki_page_write(mode="update")`.

Cross-category links: not handled here. The `/wiki:lint` tier-2 sweep
identifies missing-cross-ref candidates across categories and either inserts
them or surfaces them for user review. This split keeps ingest fast and lint
authoritative for cross-category coherence.

## Idempotency safeguards

Defense-in-depth — three independent checks, each intentional:

1. **Skill-level** (ingest step 4): the skill calls `wiki_log_read(action_filter="ingest")` and short-circuits if a log entry within `reingest_cooldown_hours` matches the source ref. First line of defense; cheapest.
2. **Subagent-level** (`subagent-prompt.md` IDEMPOTENCY block): subagent re-runs the same `wiki_log_read(action_filter="ingest")` check after dispatch. Defensive re-check (e.g. covers log-write races between skill and subagent). The dedup decision matrix above (overlap/title/slug-based, not source-ref-based) is a separate guard against duplicate page *creation* when the same content is ingested under a different source ref.
3. **Tool-level**: `wiki_page_write(mode="upsert")` returns `noop: true` when content hash matches existing. Handles pathological retries or external file writes.

Re-ingest same source within `reingest_cooldown_hours` (default 24) → check (1) short-circuits. Only re-ingests w/ `--force` flag (bypasses checks 1 + 2; check 3 still applies). Note: there is no `sources[*].ref` index — guards 1 and 2 share the log-read mechanism, not the page frontmatter.
