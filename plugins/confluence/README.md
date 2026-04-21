# Confluence Plugin

Read-only Confluence integration for `claude-project-manager`. MCP server + 6 skills.

## Features

- Search (CQL or free text)
- Get page by id or (space_key + title)
- List spaces + pages in space
- Descendant page tree
- Attachments + comments (footer + inline)
- Markdown conversion from Confluence `view` HTML

## Supported Deployments

- **Confluence Cloud** — Basic auth (email + API token)
- **Confluence Server / Data Center** — Bearer auth (Personal Access Token)

## Install + Configure

1. Run the `cpm` installer and select `confluence` in the plugin list.
2. Wizard prompts for:
   - Deployment (`cloud | server | auto`)
   - Base URL
   - Creds (email + API token for Cloud; PAT for Server)
   - Optional: allowed space keys (comma-separated; empty = all)
3. Wizard validates with a `GET /space?limit=1` call and writes `~/.claude/confluence.yaml`.

Upgrade path for existing installs: re-run `cpm` — it detects confluence missing and prompts.

## Skills

| Skill | Purpose |
|-------|---------|
| `/confluence:search` | Search content (CQL or text) |
| `/confluence:page` | Fetch a page as markdown |
| `/confluence:spaces` | List spaces |
| `/confluence:pages` | List pages in a space |
| `/confluence:tree` | Descendant-page tree |
| `/confluence:metadata` | Attachments + comments for a page |

## Config (`~/.claude/confluence.yaml`)

```yaml
deployment: auto                         # auto | cloud | server
base_url: https://example.atlassian.net
# Cloud
email: you@example.com
api_token: <secret>
# Server
personal_access_token: <secret>
# Optional
allowed_spaces: []                       # empty = all
rate_limit_per_10s: 10
default_max_results: 25
max_results_cap: 100
timeout_seconds: 30
```

Env-var overrides (highest precedence): `CONFLUENCE_CONFIG`, `CONFLUENCE_BASE_URL`, `CONFLUENCE_EMAIL`, `CONFLUENCE_API_TOKEN`, `CONFLUENCE_PAT`.

## Limitations

- API v1 only on both deployments (Cloud v2 not supported due to CQL + comment + space-id gaps).
- Live-updating macros (recently-updated, inline search) render as empty divs — no markdown.
- No local caching — every call hits the API.

## Troubleshooting

| Error | Fix |
|-------|-----|
| 401/403 | Re-run `cpm` wizard; verify token scopes |
| 429 | Lower `rate_limit_per_10s` in yaml; wait for `Retry-After` |
| Space not allowed | Add the key to `allowed_spaces` in yaml, or clear `allowed_spaces` |

## Uninstall

`claude plugin uninstall confluence@claude-project-manager` removes the plugin cache. Delete `~/.claude/confluence.yaml` manually for a clean slate.
