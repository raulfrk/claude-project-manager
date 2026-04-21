---
name: page
description: Fetch a Confluence page by id or (space_key/title). Returns header + markdown body.
allowed-tools: mcp__plugin_confluence_confluence__confluence_get_page
argument-hint: "<page_id> | <space_key>/<title> [--format md|html|both] [--labels] [--ancestors]"
context: fork
agent: general-purpose
---

> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Fetch Confluence page. Config check: `~/.claude/confluence.yaml` must exist w/ valid creds. Missing → err: "Run `cpm` installer to configure confluence."

## Args

- `<page_id>` — numeric id, OR
- `<space_key>/<title>` — slash-separated space key + exact page title
- `--format md|html|both` — body rendering (default: md)
- `--labels` — include labels
- `--ancestors` — include ancestor breadcrumb

## Execution

Parse arg:
- Contains `/` → split on first `/` → `space_key=<left>`, `title=<right>`; call `confluence_get_page(title=..., space_key=...)`
- else → `confluence_get_page(page_id=<arg>)`

Pass through `format`, `include_labels`, `include_ancestors` per flags.

## Output

Header block:
```
# <title>
**Space**: <space_key> | **Page ID**: <id> | **Version**: <n> | **URL**: <url>
```

`--labels` → append: `**Labels**: a, b, c`
`--ancestors` → append: `**Path**: <anc_1> → <anc_2> → ...`

Body:
- `format=md` (default) → `<body_md>`
- `format=html` → fenced `<body_html>`
- `format=both` → `<body_md>` then `## HTML Source` heading + fenced `<body_html>`

## Errors

- 401/403 → "Auth failed. Re-run `cpm` wizard for confluence."
- 404 → "Page not found: <arg>"
- 429 → "Rate limited. Retry-After: <seconds>"
