---
name: metadata
description: Fetch a Confluence page's attachments and/or comments.
allowed-tools: mcp__plugin_confluence_confluence__confluence_list_attachments, mcp__plugin_confluence_confluence__confluence_list_comments
argument-hint: "<page_id> [comments|attachments|both] [--location footer|inline|resolved|all] [--limit N]"
context: fork
agent: general-purpose
---

> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Fetch attachments + comments for page. Config check: `~/.claude/confluence.yaml` must exist. Missing → err: "Run `cpm` installer to configure confluence."

## Args

- `<page_id>` (required)
- `comments|attachments|both` — section filter (default: both)
- `--location footer|inline|resolved|all` — comments location filter (comments only)
- `--limit N` — limit per section

## Execution

Per selected section:
- `attachments` → call `confluence_list_attachments(page_id=..., limit=...)`
- `comments` → call `confluence_list_comments(page_id=..., location=..., limit=...)`

## Output

Two sections (only selected ones shown):

```
### Attachments (<count>)
- <filename> | <media_type> | <size_bytes> | <download_url>
...

### Comments (<count>)
- [<location>] <author> @ <created>: <body_md first 80 chars>
...
```

`next_start` per section → `... more — use --limit/--start` footer.

## Errors

- 401/403 → "Auth failed. Re-run `cpm` wizard for confluence."
- 429 → "Rate limited. Retry-After: <seconds>"
- other → verbatim bubble-up
