---
name: search
description: Search Confluence content via CQL or free text. Returns hits w/ page id, space, title, url, excerpt.
allowed-tools: mcp__plugin_confluence_confluence__confluence_search
argument-hint: "<query> [--cql] [--space KEY] [--type page|blogpost] [--limit N] [--start N] [--verbose]"
context: fork
agent: general-purpose
---

> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Search Confluence. Config check: `~/.claude/confluence.yaml` must exist w/ valid creds. Missing → err: "Run `cpm` installer to configure confluence."

## Args

- `<query>` — text (default) OR raw CQL (w/ `--cql`)
- `--cql` — treat query as CQL
- `--space KEY` — restrict to space (text mode only)
- `--type page|blogpost` — content-type filter
- `--limit N` — max hits (default: server default, cap 100)
- `--start N` — pagination offset
- `--verbose` — add excerpt line per hit

## Execution

Parse args; call `mcp__plugin_confluence_confluence__confluence_search`:
- `--cql` → pass `cql=<query>`
- else → pass `text=<query>`
- `--space` → `space_key=<KEY>`
- `--type` → `type=<page|blogpost>`
- `--limit`, `--start` → pass through

## Output

Per hit (one line):
```
<page_id> | <space_key> | <title> | <url> | <last_modified>
```

`--verbose` → second line per hit: `  ↳ <excerpt>`

Footer:
- `<count> results, total=<total>`
- `next_start` present → `... more — use --start <N>`

## Errors

- 401/403 → "Auth failed. Re-run `cpm` wizard for confluence."
- 429 → "Rate limited. Retry-After: <seconds>"
- 404 / other → verbatim bubble-up
