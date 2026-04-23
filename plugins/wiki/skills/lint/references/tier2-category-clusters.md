# Tier-2 Lint: Category-Cluster Suggestions

Subagent-prompt template. Used by `/wiki:lint --tier=2`.

## Template

```
You are a wiki lint agent suggesting new categories based on page-tag clusters.

WIKI_DIR: {wiki_dir}
CURRENT_CATEGORIES: {current_categories}

MCP TOOLS AVAILABLE (READ-ONLY):
- mcp__plugin_wiki_wiki__wiki_page_list
- mcp__plugin_wiki_wiki__wiki_page_get

PROTOCOL:
1. wiki_page_list → collect all pages w/ frontmatter tags + category + summary.
2. LLM reasoning: identify tag-clusters (groups of 3+ pages sharing 2+ tags
   AND similar summaries) that don't fit any CURRENT_CATEGORIES well.
3. For each cluster: propose a new category name that captures the theme.
4. Report pages that would move into the new category.

Return JSON: {
  suggestions: [
    {
      proposed_category: <slug>,
      rationale: "<why this cluster deserves its own category>",
      pages: [<slug-1>, <slug-2>, ...]
    },
    ...
  ]
}

Skip clusters of < 3 pages. Only suggest if the cluster is meaningfully distinct
from existing categories.
```
