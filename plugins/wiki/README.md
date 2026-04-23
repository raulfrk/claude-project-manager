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

Phase 1 (this release): core MCP tools only (page CRUD, index, log, links, scope). No skills yet; no lint; no search.
