---
name: init
description: Initialize the Karpathy LLM wiki. Creates `~/.claude/wiki/` + `~/.claude/wiki.yaml`, prompts user to pick a category profile, writes empty index.md + log.md. Use when user says "init wiki", "create wiki", "set up wiki", "wiki init".
allowed-tools: mcp__plugin_wiki_wiki__wiki_log_append, mcp__plugin_wiki_wiki__wiki_index_rebuild, AskUserQuestion, Bash, Write
argument-hint: ""
---

> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Initialize wiki. Interactive; no args needed.

**1.** Check if wiki already initialized.
- `Bash`: `ls ~/.claude/wiki.yaml 2>/dev/null && echo EXISTS`
- `EXISTS` → print "Wiki already initialized at ~/.claude/wiki/. Re-init not supported. Edit `~/.claude/wiki.yaml` + `~/.claude/wiki/config.yaml` manually if needed." + stop.

**2.** Prompt user for category profile via `AskUserQuestion`:
- Question: "Which category profile fits your wiki's domain?"
- Header: "Profile"
- Options (single-select):
    - `software` — concepts / decisions / references / pitfalls / entities. Best for code projects, architecture notes, team docs.
    - `personal` — journal / topics / people / places / lessons. Best for life tracking, journal entries, relationship notes.
    - `research` — concepts / sources / findings / questions. Best for academic research, literature review, thesis writing.
    - `minimal` — flat `pages/`, no subdirs. Best if you want full freedom + tag-based grouping only.

**3.** If user picks "Other" (custom): prompt via `AskUserQuestion` free-text for comma-separated categories. Parse into list of strings, strip whitespace. Store profile name as `custom`.

**4.** Create wiki directory + lockfile via `Bash`:

```bash
set -e
mkdir -p ~/.claude/wiki/pages
touch ~/.claude/wiki/.lock
```

**5.** Write `~/.claude/wiki.yaml` via `Write` with:

```yaml
enabled: true
wiki_dir: ~/.claude/wiki
reingest_cooldown_hours: 24
bootstrap_pending: false
session_ingest:
  section_map: {}
```

**6.** Write `~/.claude/wiki/config.yaml` via `Write`. Per-profile content:

`software`:
```yaml
schema_version: 1
profile: software
required_frontmatter:
  - title
  - tags
  - links_to
  - scope
  - sources
  - last_ingested
lint:
  stale_after_days: 90
  orphan_min_page_count: 3
```

`personal` / `research` / `minimal` → same shape, different `profile:` name. Omit `categories:` key (builtin profiles derive categories from name).

`custom` → add `categories: [...]` list from user's comma-separated input.

**7.** Create category subdirs via `Bash`. Mapping:
- `software`: `mkdir -p ~/.claude/wiki/pages/{concepts,decisions,references,pitfalls,entities}`
- `personal`: `mkdir -p ~/.claude/wiki/pages/{journal,topics,people,places,lessons}`
- `research`: `mkdir -p ~/.claude/wiki/pages/{concepts,sources,findings,questions}`
- `minimal`: no subdirs.
- `custom`: loop user categories; `mkdir -p ~/.claude/wiki/pages/<cat>` each.

**8.** Seed wiki via MCP tools:
- `mcp__plugin_wiki_wiki__wiki_index_rebuild` → creates empty `index.md`.
- `mcp__plugin_wiki_wiki__wiki_log_append` w/ `action=init`, `title=<profile>`, `body=Wiki initialized w/ <profile> profile.`

**9.** Print confirmation:
- "Wiki initialized at `~/.claude/wiki/` w/ `<profile>` profile."
- List next steps: "To query: `/wiki:query <question>`. To lint: `/wiki:lint`. Ingest comes in Phase 3."

## Err handling

- Step 4 mkdir fails → err msg + stop. Don't write config files.
- Step 5 / 6 `Write` fails → err msg. Suggest user check `~/.claude/` perms.
- Step 8 `wiki_index_rebuild` fails → warn but don't stop; index can be rebuilt later.
