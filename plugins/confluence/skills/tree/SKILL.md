---
name: tree
description: Fetch descendant-page tree rooted at a Confluence page.
allowed-tools: mcp__plugin_confluence_confluence__confluence_get_page_tree
argument-hint: "<root_page_id> [--depth all|N] [--max N]"
context: fork
agent: general-purpose
---

> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Fetch page tree. Config check: `~/.claude/confluence.yaml` must exist. Missing → err: "Run `cpm` installer to configure confluence."

## Args

- `<root_page_id>` (required) — numeric id
- `--depth all|N` — tree depth (default: all)
- `--max N` — max nodes (default: 200)

## Execution

Call `confluence_get_page_tree(root_page_id=<arg>, depth=..., max_nodes=...)`.

## Output

Indented tree (2-space indent per level):
```
- <root_title> (<id>)
  - <child_title> (<id>)
    - <grandchild_title> (<id>)
```

If `truncated=true` in response → append footer: `... truncated at <max> nodes`.

## Errors

- 401/403 → "Auth failed. Re-run `cpm` wizard for confluence."
- 429 → "Rate limited. Retry-After: <seconds>"
- other → verbatim bubble-up
