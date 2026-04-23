# wiki

Karpathy-style LLM wiki plugin for cpm. Persistent, LLM-maintained markdown knowledge base.

See full design spec at `docs/superpowers/specs/2026-04-21-karpathy-wiki-plugin-design.md`.

## Storage

- `~/.claude/wiki.yaml` — runtime config (enabled flag, session-ingest map, etc.)
- `~/.claude/wiki/` — wiki root
  - `config.yaml` — category profile + lint rules
  - `index.md` — page catalog
  - `log.md` — append-only ledger
  - `pages/<category>/*.md` — wiki pages
  - `.lock` — fcntl lock
  - `.index/` — BM25 sidecar (Phase 2)

## Phase status

- **Phase 1** — core persistence tools (page CRUD, index, log, links, scope). ✅
- **Phase 2** — BM25 search (`wiki_search_bm25`, `wiki_search_index_refresh`), 7 Tier-1 lint tools (`wiki_lint_*`), 3 standalone skills (`/wiki:init`, `/wiki:query`, `/wiki:lint`). ✅
- **Phase 3** — 3 more skills (`/wiki:ingest`, `/wiki:bootstrap`, `/wiki:promote`). Ingest accepts 6 source types (URL, file, `session:`, `note:`, `search:`, `mcp:`) + free-form natural language. Bootstrap is proj-aware. ✅
- **Phase 4** — proj touchpoints (router hook, `/proj:save` integration, wizard), Tier-2 semantic lint. Pending.
- **Phase 5** — polish + docs. Pending.

## Ingest protocol references

The `/wiki:ingest` + `/wiki:bootstrap` skills share a set of reference docs at `plugins/wiki/skills/ingest/references/`:

- `source-readers.md` — canonical mapping of source prefixes + free-form natural-language resolution to readers (URL / file / session / note / search / mcp).
- `dedup-protocol.md` — entity extraction, dedup decision matrix, merge semantics, cross-ref pass.
- `subagent-prompt.md` — the reusable forked-subagent prompt template.

These files are part of the plugin; future phases (`/proj:save` auto-ingest in Phase 4) will reuse them by reference rather than duplicating the prose.
