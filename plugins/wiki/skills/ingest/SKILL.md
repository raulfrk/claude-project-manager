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
```

If `contradictions_flagged` non-empty:
```
### ⚠️ Contradictions detected

- `<page-slug>`: prior claim `<claim-a>` vs new claim `<claim-b>`. Resolve via `/wiki:query <slug>` + manual edit.
```

If `warnings` non-empty:
```
### Warnings

- <warning>
```

Close with: "Log entry appended. Run `/wiki:lint` to check integrity."

## Err handling

- Wiki disabled / missing → "Wiki not initialized. Run `/wiki:init` first." + stop.
- Scope-detect fails → use `global` (log warning in final output).
- Subagent dispatch fails (`Task` returns error) → print err + suggest `--force` or re-run.
- Subagent returns malformed JSON → print raw output + "Ingest subagent returned unparseable output. This is a bug — please report."
