# wiki

Karpathy-style LLM wiki plugin for cpm. Persistent, LLM-maintained markdown knowledge base.

See full design spec at `docs/superpowers/specs/2026-04-21-karpathy-wiki-plugin-design.md`.

## Quickstart

1. Install via cpm marketplace: `claude plugin install wiki@claude-project-manager`.
2. Run the installer wizard: `cpm-installer` → select wiki → pick a profile (software / personal / research / minimal / custom).
3. In a Claude session:
   - `/wiki:init` (if you skipped the wizard).
   - `/wiki:ingest <source>` — add content from URL, file, session file, free-form note, web search, or any installed MCP server (confluence, jira, github, etc.).
   - `/wiki:query <question>` — synthesize a cited answer from wiki pages.
   - `/wiki:lint` — find + fix integrity issues (add `--tier=2` for LLM-driven semantic checks).

## Skills

| Skill | Use |
|---|---|
| `/wiki:init` | Create wiki + pick category profile. |
| `/wiki:ingest <source>` | Add content. Source: URL, file, `session:<path>`, `note:<text>`, `search:<query>`, `mcp:<server>:<tool>:<args>`, or free-form natural language. |
| `/wiki:query <question>` | Citation-backed answer via index-reads or BM25 + LLM synthesis. |
| `/wiki:lint [--tier=1\|2\|all]` | Tier-1 = pure data checks; Tier-2 = LLM-driven semantic checks. |
| `/wiki:bootstrap [dir]` | Bulk import. Proj-aware when proj is loaded. |
| `/wiki:promote <slug>` | Change a page's scope (add-global / strip-project / replace). |

## Storage

- `~/.claude/wiki.yaml` — runtime config (enabled flag, session-ingest map, etc.)
- `~/.claude/wiki/` — wiki root
  - `config.yaml` — category profile + lint rules
  - `index.md` — page catalog
  - `log.md` — append-only ledger
  - `pages/<category>/*.md` — wiki pages
  - `.lock` — fcntl lock
  - `.index/` — BM25 sidecar (Phase 2)

### Proj integration config (when proj + wiki both installed)

- `~/.claude/proj.yaml::sync.wiki.*` — proj-owned flags gating integration behavior:
  - `enabled` — master switch for proj→wiki integration
  - `auto_sync` — inherits toggle used across sync.* dataclasses (currently informational)
  - `auto_ingest_sessions` — `/proj:save` spawns wiki ingest subagent on session file
  - `capture_notes_as_log` — router hook `notes_append` → `wiki_log_append` fires
  - `replace_notes_md` — (future) redirect `notes_append` to wiki entirely
  - `bootstrap_docs` — per-project doc paths to include in `/wiki:bootstrap`
- `~/.claude/proj-session.yaml` — proj-owned, session-scoped, file-backed active project marker. Wiki reads its own session's slot in `~/.claude/proj-session.yaml` (pid-keyed v2 schema) via the shared `session_key` helper to scope queries. See the "Wiki Plugin Config Flags" section of the top-level `CLAUDE.md` for schema details.

Note: `wiki.yaml::enabled` ("wiki plugin ready") and `proj.yaml::sync.wiki.enabled` ("proj should invoke wiki integrations") are distinct flags with different semantics. Both must be true for integration behaviors to fire.

## Phase status

- **Phase 1** — core persistence tools (page CRUD, index, log, links, scope). ✅
- **Phase 2** — BM25 search (`wiki_search_bm25`, `wiki_search_index_refresh`), 7 Tier-1 lint tools (`wiki_lint_*`), 3 standalone skills (`/wiki:init`, `/wiki:query`, `/wiki:lint`). ✅
- **Phase 3** — 3 more skills (`/wiki:ingest`, `/wiki:bootstrap`, `/wiki:promote`). Ingest accepts 6 source types (URL, file, `session:`, `note:`, `search:`, `mcp:`) + free-form natural language. Bootstrap is proj-aware. ✅
- **Phase 4a** — proj integration foundation: session-active file persistence (`~/.claude/proj-session.yaml`, fixes scope detection), `WikiSync` dataclass in proj.yaml, router hook `notes_append` → `wiki_log_append`, `/proj:save` final step spawns wiki ingest subagent when enabled. ✅
- **Phase 4b** — installer wizard gains wiki section: profile picker (software/personal/research/minimal/custom), bootstrap-queue flag, proj-integration toggles. Writes `wiki.yaml` + `wiki/config.yaml` + `proj.yaml::sync.wiki.*`. ✅
- **Phase 4c** — Tier-2 semantic lint: 4 LLM-driven checks dispatched in parallel via TeamCreate after Tier-1 (contradictions / deprecation / missing cross-refs / category clusters). Reference prompts at `plugins/wiki/skills/lint/references/tier2-*.md`. ✅
- **Phase 5** — polish + docs: CLAUDE.md wiki config-flag reference, e2e integration tests (pytest), README Quickstart, sunset of unified-recall-proposal.md. ✅

## Tier-2 lint references

`/wiki:lint --tier=2` (or `--tier=all`) dispatches 4 subagents in parallel, one per reference file at `plugins/wiki/skills/lint/references/`:

- `tier2-contradictions.md` — factual conflicts between tag-clustered pages.
- `tier2-deprecation.md` — obsolete pages (stale + no inbound links).
- `tier2-missing-cross-refs.md` — page titles appearing unwrapped in other page bodies.
- `tier2-category-clusters.md` — tag clusters that could justify a new category.

## Ingest protocol references

The `/wiki:ingest` + `/wiki:bootstrap` skills share a set of reference docs at `plugins/wiki/skills/ingest/references/`:

- `source-readers.md` — canonical mapping of source prefixes + free-form natural-language resolution to readers (URL / file / session / note / search / mcp).
- `dedup-protocol.md` — entity extraction, dedup decision matrix, merge semantics, cross-ref pass.
- `subagent-prompt.md` — the reusable forked-subagent prompt template.

These files are part of the plugin; future phases (`/proj:save` auto-ingest in Phase 4) will reuse them by reference rather than duplicating the prose.

### `references/` subfolder convention

Skills whose prose exceeds ~250 lines or whose prompt templates are reused across multiple skills should place supporting docs in a `references/` subfolder next to `SKILL.md`. Examples:

- `plugins/wiki/skills/ingest/references/` — source readers, dedup protocol, subagent prompt (shared with `/wiki:bootstrap` and `/proj:save` auto-ingest).
- `plugins/wiki/skills/lint/references/` — Tier-2 lint subagent prompts (one per concern).

This keeps `SKILL.md` under the 250-line soft cap while letting rich reference material stay version-controlled with the skill.
