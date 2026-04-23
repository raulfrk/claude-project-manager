# Source-Reader Reference

Canonical mapping from the user's `<source>` argument to the right reader. Used by `/wiki:ingest` + (Phase 4) `/proj:save` auto-ingest.

## Explicit prefix forms (highest priority)

| Prefix | Reader | Notes |
|---|---|---|
| `https://` / `http://` | `WebFetch` | Web article, gist, blog, HTML. |
| Absolute / relative file path | `Read` | Local md, text, transcripts. PDFs via Read's PDF support. |
| `session:<path>` | `Read` | Proj session file. Apply `wiki.yaml::session_ingest.section_map` for section-aware extraction. |
| `note:<text>` | inline | Free-form note. No external fetch. Use when user wants to capture a thought without a source doc. |
| `search:<query>` | `WebSearch` | Top 3-5 results; iterate each result URL as a URL source. |
| `mcp:<server>:<tool>:<args>` | dynamic MCP call | `args` is a comma-separated `key=value` list. E.g. `mcp:confluence:page_get:space=HR,title=Onboarding`. Subagent must ensure the named server + tool are both available; error cleanly if not. |

## Free-form resolution (LLM-driven)

If `<source>` does not match any explicit prefix, the subagent resolves via content analysis:

| Phrase pattern | Resolved form |
|---|---|
| Contains a bare URL | URL form (WebFetch) |
| `"the <something> page from confluence"` + confluence MCP installed | `mcp:confluence:page_get:...` w/ args inferred from context |
| `"issue/ticket <KEY>"` + jira MCP installed | `mcp:jira:jira_get_issue:<KEY>` |
| `"repo readme for <owner/repo>"` + github MCP installed | `mcp:github:repo_readme:<owner/repo>` (adapt to actual github MCP tool names) |
| `"search for X online"` / `"look up X"` | `search:<X>` |
| `"this file <path>"` or bare filesystem path | file Read |
| `"my note: <text>"` / `"remember: <text>"` | `note:<text>` |
| Ambiguous / missing detail | `AskUserQuestion` to disambiguate before fetching |

## Resolution algorithm

1. If source starts w/ `https://`, `http://`, `session:`, `note:`, `search:`, or `mcp:` → use the matching explicit reader.
2. Else if source is a valid filesystem path → file Read.
3. Else parse free-form text per the patterns above.
4. Log the resolved form in the ingest JSON summary so user sees what was chosen.
5. On ambiguity: AskUserQuestion w/ 2-4 options covering most likely interpretations.

## MCP-source-tool discovery

When resolving `mcp:*` or natural-language forms that map to MCP tools, check available tools via the subagent's tool registry (list_tools-equivalent). Match tool names by heuristic:

- confluence: `*page_get*`, `*page*search*`
- jira: `*issue_get*`, `*search*issue*`
- github: `*readme*`, `*file_get*`, `*issue_get*`, `*pr_get*`
- linear: `*issue_get*`, `*project_get*`

If none match, fall back to `AskUserQuestion`: "Which MCP tool should fetch this? Options: `<list of available tool names that look relevant>`."
