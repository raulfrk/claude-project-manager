---
name: promote
description: Edit wiki page scope frontmatter — add `global` to promote cross-project visibility, strip `project:<name>` tags, or replace scope list directly. Use when user says "promote wiki page", "wiki:promote <slug>", "make this page global", "demote page to project scope".
allowed-tools: mcp__plugin_wiki_wiki__wiki_page_get, mcp__plugin_wiki_wiki__wiki_page_write, mcp__plugin_wiki_wiki__wiki_page_list, mcp__plugin_wiki_wiki__wiki_log_append, AskUserQuestion
argument-hint: "<slug> [--category <cat>]"
---

> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Change page `scope` frontmatter list. `$ARGUMENTS` = `<slug> [--category <cat>]`.

**1. Parse args:**
- First token → slug.
- Optional `--category <cat>` flag; if absent, `category=None` (flat pages/ layout).
- No slug → stop: "Slug required. Usage: `/wiki:promote <slug> [--category <cat>]`."

**2. Fetch page:**
- `mcp__plugin_wiki_wiki__wiki_page_get(slug, category)`.
- `error: not_found` → stop: "Page `<slug>` not found (category=`<cat>`). Run `/wiki:query <slug>` to locate, or check `/wiki:lint` for duplicates."

**3. Show current scope:**
- Print: "Current scope: `<scope list>` (<N> tags)."

**4. Prompt via AskUserQuestion:**
- Header: "Scope op".
- Q: "What scope change for `<slug>`?"
- Single-select options:
    - `add-global` — append `global` to scope if absent. Keep existing project scopes.
    - `strip-project` — remove all `project:*` from scope. Keep `global` + other tags.
    - `make-global-only` — replace scope w/ exactly `["global"]`.
    - `replace-manual` — prompt user (AskUserQuestion Other field) for comma-separated scope; replace entirely.

**5. Compute new scope:**
- Per picked action, build new list.
- Validate: each entry must be `"global"` or start w/ `"project:"`. If user enters other via manual replace, confirm before proceeding (scope unstructured — wiki accepts, lint won't understand).

**6. No-op check:**
- If new scope == current scope: print "Scope unchanged (no-op)." + stop.

**7. Write page:**
- Copy existing `frontmatter` dict from step 2; set `scope = <new list>`; keep body unchanged.
- `mcp__plugin_wiki_wiki__wiki_page_write(slug, category, frontmatter=<merged>, body=<body>, mode="update")`.
- Err → print + stop.

**8. Log entry:**
- `mcp__plugin_wiki_wiki__wiki_log_append(action="promote", title=<slug>, body="scope: <old> → <new>")`.

**9. Confirm:**
- Print: "Promoted `<slug>`: scope now `<new list>`."

## Err handling

- Wiki disabled/missing → "Wiki not initialized. Run `/wiki:init` first." + stop.
- Page not found → step 2 err path.
- Write fails (lock, disk, etc.) → print err + don't log.
- Log-append fails → warn; don't rollback (write already succeeded).
