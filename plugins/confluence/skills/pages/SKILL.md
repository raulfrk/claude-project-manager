---
name: pages
description: List pages in a Confluence space.
allowed-tools: mcp__plugin_confluence_confluence__confluence_list_pages
argument-hint: "<space_key> [--limit N] [--start N]"
context: fork
agent: general-purpose
---

> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

List pages in space. Config check: `~/.claude/confluence.yaml` must exist. Missing → err: "Run `cpm` installer to configure confluence."

## Args

- `<space_key>` (required) — space key
- `--limit N`, `--start N` — pagination

## Execution

Call `confluence_list_pages(space_key=<arg>, limit=..., start=...)`.

## Output

Per page:
```
<id> | <title> | <url>
```

Footer:
- `<count> pages`
- `next_start` present → `... more — use --start <N>`

## Errors

- 401/403 → "Auth failed. Re-run `cpm` wizard for confluence."
- 429 → "Rate limited. Retry-After: <seconds>"
- other → verbatim bubble-up
