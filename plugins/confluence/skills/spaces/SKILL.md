---
name: spaces
description: List Confluence spaces.
allowed-tools: mcp__plugin_confluence_confluence__confluence_list_spaces
argument-hint: "[--type global|personal] [--status current|archived] [--limit N] [--start N]"
context: fork
agent: general-purpose
---

> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

List spaces. Config check: `~/.claude/confluence.yaml` must exist. Missing → err: "Run `cpm` installer to configure confluence."

## Args

- `--type global|personal` — filter
- `--status current|archived` — filter
- `--limit N` — page size
- `--start N` — pagination offset

## Execution

Call `confluence_list_spaces(type=..., status=..., limit=..., start=...)`.

## Output

Per space:
```
<key> | <name> | <type> | <url>
```

Footer:
- `<count> spaces`
- `next_start` present → `... more — use --start <N>`

## Errors

- 401/403 → "Auth failed. Re-run `cpm` wizard for confluence."
- 429 → "Rate limited. Retry-After: <seconds>"
- other → verbatim bubble-up
