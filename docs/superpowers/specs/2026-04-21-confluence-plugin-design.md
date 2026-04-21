# Confluence Plugin — Design Spec

**Todo**: 686
**Date**: 2026-04-21
**Branch**: `feat/686-confluence-plugin`
**Status**: approved (design phase); pending implementation plan

## Goal

Add a read-only Confluence integration to the `claude-project-manager` marketplace: an MCP server that queries + pulls Confluence documents, plus a skill layer that routes common operations. Must be YAML-configurable with a token, and support both Atlassian Cloud and Confluence Server / Data Center (DC).

## Non-goals

- No write operations (no page create/update, no comment posts, no label mutations).
- No coupling to the `proj` plugin. Confluence stays independent: pages are not linked to todos; no new `proj.yaml` schema beyond the `sync.confluence.enabled` flag written by the wizard.
- No local caching of responses (stale-data risk avoided).
- No Confluence Cloud REST API v2 targeting. See "API target decision" below.

## Scope summary

- 1 new plugin directory: `plugins/confluence/`
- 1 MCP server: `confluence` on port 19108 (Unix socket + TCP fallback)
- 8 MCP tools (1 init + 7 read tools)
- 6 skills: `/confluence:search`, `/confluence:page`, `/confluence:spaces`, `/confluence:pages`, `/confluence:tree`, `/confluence:metadata`
- Installer + wizard integration (8 registration touchpoints)
- 3 test tiers: unit, contract/e2e-mock (respx), e2e live (gated by env)

## API target decision

**The plugin uses Confluence REST API v1 endpoints on BOTH Cloud and Server/DC.**

### Why not Cloud v2

Cloud v2 has gaps that would force per-deployment branching in every tool:
- No CQL search endpoint under `/wiki/api/v2/*`. Atlassian directs callers to v1's `/wiki/rest/api/search` even from v2 clients.
- Spaces take numeric space IDs (`/spaces/{id}/pages`), not space keys. Requires a second lookup (`/spaces?keys=KEY`) for every key-based call.
- Footer and inline comments are two separate endpoints (v1 has one `/content/{id}/child/comment` with a `location` filter).
- No `/descendants` endpoint; tree walks must recurse `/children` manually.
- Response shapes differ from v1, forcing parallel parsing paths.

### v1 on both deployments

Cloud v1 (`/wiki/rest/api/*`) and Server/DC (`/rest/api/*`) share:
- Identical endpoint path suffixes (everything after the base prefix matches).
- Same query parameters (`expand`, `start`, `limit`, `cql`, `spaceKey`, `type`, `location`, etc.).
- Compatible response shapes (`results`, `start`, `limit`, `size`, `totalSize`, `_links.next`).
- A single `/descendant/page` endpoint for full subtree walks.

Differences — only 2:
1. **Base path prefix**: Cloud = `/wiki/rest/api/`; Server = `/rest/api/`.
2. **Auth header**: Cloud = `Authorization: Basic base64(email:api_token)`; Server = `Authorization: Bearer <pat>`.

Both are resolved once at client construction — tool code sees one uniform interface.

## Architecture

### Plugin layout

```
plugins/confluence/
  .claude-plugin/
    plugin.json                       # name=confluence, version=1.0.0, mcp ref
    default-hooks.yaml                # hooks: []  (read-only)
  .mcp.json                           # CONFLUENCE_CONFIG=~/.claude/confluence.yaml
  start.sh                            # uv venv + uv run confluence-server
  README.md
  server/
    pyproject.toml                    # deps: httpx, pyyaml, mcp, markdownify, beautifulsoup4, claude-hook-transport
    server/
      __init__.py
      main.py                         # FastMCP + enable_hook_dispatch + run_dual(port=19108)
      lib/
        __init__.py
        config.py                     # ConfluenceConfig dataclass + load_config()
        client.py                     # ConfluenceClient + get_client() singleton + deployment detection
        markdown.py                   # html_to_markdown() helper (markdownify wrapper)
        ratelimit.py                  # token bucket + 429 retry
        errors.py                     # typed exception hierarchy
      tools/
        __init__.py
        init.py                       # confluence_init
        search.py                     # confluence_search
        pages.py                      # confluence_get_page + confluence_list_pages + confluence_get_page_tree
        spaces.py                     # confluence_list_spaces
        attachments.py                # confluence_list_attachments
        comments.py                   # confluence_list_comments
    tests/
      ... (see "Testing")
  skills/
    search/SKILL.md
    page/SKILL.md
    spaces/SKILL.md
    pages/SKILL.md
    tree/SKILL.md
    metadata/SKILL.md
```

### Config schema (`~/.claude/confluence.yaml`)

```yaml
deployment: auto                        # auto | cloud | server
base_url: https://your.atlassian.net    # Cloud; or https://confluence.company.com
# Cloud auth (Basic): email + api_token
email: user@example.com
api_token: <secret>
# Server/DC auth (Bearer): PAT
personal_access_token: <secret>
# Optional
rate_limit_per_10s: 10
allowed_spaces: []                      # [] = all; else list of space keys
default_max_results: 25
max_results_cap: 100
timeout_seconds: 30
```

Env var override: `CONFLUENCE_CONFIG=~/.claude/confluence.yaml` in `.mcp.json`, matching the jira pattern. Direct env-var fallbacks (`CONFLUENCE_BASE_URL`, `CONFLUENCE_API_TOKEN`, `CONFLUENCE_PAT`, `CONFLUENCE_EMAIL`) also supported.

### Deployment detection

`ConfluenceClient.__init__`:
1. If `deployment` is `cloud` or `server`, use it.
2. If `deployment` is `auto`: if `base_url` host ends in `.atlassian.net` → `cloud`; else `server`.
3. Validate required creds for the chosen deployment:
   - `cloud` → `email` + `api_token` both required; else raise `ConfigError`.
   - `server` → `personal_access_token` required; else raise `ConfigError`.
4. Assemble auth header + API base path:
   - `cloud` → `Authorization: Basic base64(email:api_token)`, base path `<base_url>/wiki/rest/api`.
   - `server` → `Authorization: Bearer <pat>`, base path `<base_url>/rest/api`.

### Port assignment

**Port 19108** (next sequential after zoxide=19107). Update the port table in `/home/raul/projects/claude-project-manager/CLAUDE.md`.

## MCP tool surface

All tools live in `server/tools/*.py` and are registered in `main.py` via `enable_hook_dispatch(mcp, exclude={"confluence_init"})` + each module's `register(mcp)` call.

| Tool | Endpoint suffix | Params | Returns |
|------|-----------------|--------|---------|
| `confluence_init` | — (writes yaml only) | `deployment`, `base_url`, `email?`, `api_token?`, `personal_access_token?`, `allowed_spaces?` | `{status, config_path}` |
| `confluence_search` | `GET /search?cql=...` | `cql` (raw) OR `text` (wrapped: `text ~ "..."`); `space_key?`, `type?`; `limit=25`, `start=0`; `expand?` | `{results: [{page_id, type, title, space_key, url, excerpt, last_modified}], count, total, next_start}` |
| `confluence_get_page` | `GET /content/{id}?expand=body.view,version,ancestors,space,metadata.labels` | `page_id` OR (`title` + `space_key`) — latter calls `GET /content?type=page&spaceKey=KEY&title=T&expand=...`; `format="md"` (md\|html\|both); `include_labels?`, `include_ancestors?` | `{page_id, title, space_key, url, version, body_md, body_html?, labels?, ancestors?}` |
| `confluence_list_spaces` | `GET /space?type=...&start=0&limit=25` | `type?` (global\|personal), `status?`, `limit=25`, `start=0` | `{results: [{key, name, type, url}], count, next_start}` |
| `confluence_list_pages` | `GET /content?type=page&spaceKey=KEY&start=0&limit=25` | `space_key`, `limit=25`, `start=0` | `{results: [{page_id, title, url}], count, next_start}` |
| `confluence_get_page_tree` | `GET /content/{id}/descendant/page?depth=all&limit=200` | `root_page_id`, `depth="all"` or int, `max_nodes=200` | `{root_page_id, tree: nested}` — flat `descendant` results grouped client-side into a tree via `ancestors` parent chain |
| `confluence_list_attachments` | `GET /content/{id}/child/attachment?limit=25&start=0` | `page_id`, `limit=25`, `start=0`, `media_type?`, `filename?` | `{results: [{id, title, media_type, file_size, download_url}], count, next_start}` |
| `confluence_list_comments` | `GET /content/{id}/child/comment?location=footer\|inline\|resolved&expand=body.view&start=0&limit=25` | `page_id`, `location?` (footer\|inline\|resolved\|all), `limit=25`, `start=0` | `{results: [{id, author, created, body_md, location}], count, next_start}` |

### Cross-cutting tool behaviors

- **`allowed_spaces` enforcement**: Before any call taking `space_key`, client raises `SpaceNotAllowedError` if the key is not in `allowed_spaces` (when non-empty). For search with a CQL `space=X` filter, X must be allowed. For search with no space filter + non-empty `allowed_spaces`, client injects `AND (space=A OR space=B OR ...)` into the CQL. For `get_page` by id (no `space_key` arg), the check runs after response parse; violation raises + body is not returned.
- **Pagination**: Response envelope always includes `next_start` = `start + limit` when the upstream response has `_links.next`, else `null`. Callers loop as needed.
- **Body rendering**: `expand=body.view` returns server-rendered HTML; client runs `html_to_markdown(html)` → `body_md`. With `format=html`, returns `body_html` only. With `format=both`, returns both fields.
- **Rate limiter**: global token bucket (capacity = `rate_limit_per_10s`, default 10; refill rate = capacity / 10s). `acquire()` blocks when empty. On 429, read `Retry-After` header (seconds); sleep; exponential backoff on retry (3 tries total: 1s, 2s, 4s — `Retry-After` takes precedence).
- **Preemptive slowdown**: On Cloud, if `X-RateLimit-Remaining` header indicates < 2 tokens left, sleep 1s before next call.

## Skill layer

All skills: caveman ultra, YAML frontmatter with `allowed-tools`, `context: fork`, `agent: general-purpose`.

| Skill | Args | MCP tools | Output |
|-------|------|-----------|--------|
| `/confluence:search` | `<query> [--cql] [--space KEY] [--type page\|blogpost] [--limit N] [--start N] [--verbose]` | `confluence_search` | Per hit: `id \| space \| title \| url \| last_modified`; `--verbose` adds excerpt line |
| `/confluence:page` | `<page_id>` OR `<space_key>/<title>` `[--format md\|html\|both] [--labels] [--ancestors]` | `confluence_get_page` | Header (title, space, id, version, url) + markdown body; `--labels` appends labels; `--ancestors` appends breadcrumb; `--format both` adds `## HTML Source` fenced block |
| `/confluence:spaces` | `[--type global\|personal] [--status current\|archived] [--limit N] [--start N]` | `confluence_list_spaces` | `key \| name \| type \| url` per row + pagination footer |
| `/confluence:pages` | `<space_key> [--limit N] [--start N]` | `confluence_list_pages` | `id \| title \| url` per row + pagination footer |
| `/confluence:tree` | `<root_page_id> [--depth all\|N] [--max N]` | `confluence_get_page_tree` | Indented tree `- <title> (<id>)`; `... truncated at <N>` when cap hit |
| `/confluence:metadata` | `<page_id> [comments\|attachments\|both] [--location footer\|inline\|resolved\|all] [--limit N]` | `confluence_list_attachments`, `confluence_list_comments` | `### Attachments` + `### Comments` sections; one-liner per entry |

### Skill common patterns

- **Prerequisite check**: skill body opens with: "Config check: `~/.claude/confluence.yaml` must exist with valid creds. Missing → err: `Run cpm installer to configure confluence.`"
- **No auto-pagination**: print `... more results — use --start <N>` footer when `next_start` non-null. User opts in.
- **Error formatting** (consistent across skills):
  - 401/403 → "Auth failed. Re-run `cpm` wizard for confluence."
  - 404 → "<entity> not found: <id>"
  - 429 → "Rate limited. Retry-After: <seconds>"
  - other → verbatim bubble-up

### No hooks

`plugins/confluence/.claude-plugin/default-hooks.yaml` → `hooks: []`. Read-only plugin has no auto-sync targets.

## Markdown conversion

`server/lib/markdown.py` single helper:

```python
from markdownify import markdownify as _md

def html_to_markdown(html: str) -> str:
    return _md(
        html,
        heading_style="ATX",
        bullets="-",
        strip=["script", "style"],
        code_language="",
    ).strip()
```

Deps to add to `plugins/confluence/server/pyproject.toml`: `markdownify>=0.11`, `beautifulsoup4>=4.12`.

### Macro coverage

Confluence server-rendered `body.view` HTML passes macros through as rendered HTML, so `markdownify` handles the common cases out of the box: headings, paragraphs, code blocks (fenced), tables, bulleted/numbered lists, panels (→ blockquotes), expandable sections (unfolded in view format), images, links.

**Not handled** (documented limitations):
- Live-updating macros (recently-updated widget, search results) render as empty divs in view format — nothing to convert.
- Rich embeds (draw.io, Gliffy) render as static images with links; markdown shows the image + link.

## Error handling

`server/lib/errors.py`:

```python
class ConfluenceError(Exception): ...
class ConfigError(ConfluenceError): ...
class AuthError(ConfluenceError): ...             # 401/403
class NotFoundError(ConfluenceError): ...         # 404
class RateLimitError(ConfluenceError): ...        # 429 after retries
class ServerError(ConfluenceError): ...           # 5xx
class SpaceNotAllowedError(ConfluenceError): ...  # allowed_spaces violation
```

Tool implementations catch + re-raise as FastMCP errors with user-actionable messages (listed under "Cross-cutting tool behaviors" above).

## Installer + wizard integration

### Files to modify

| File | Change |
|------|--------|
| `.claude-plugin/marketplace.json` | Add `confluence` plugin entry: name, source `./plugins/confluence`, description, version `1.0.0`, author, license MIT, category `integrations`, keywords `["confluence", "atlassian", "docs", "wiki"]` |
| `installer/flow/installer_flow.py:50` | Add `"confluence"` to `_WIZARD_PLUGINS` |
| `installer/flow/installer_flow.py:78-99` | Add entries to `_INTEGRATION_CRED_FIELDS` (confluence: `["base_url", "email", "api_token", "personal_access_token"]`), `_INTEGRATION_SYNC_PREFIX` (`"sync.confluence"`), `_INTEGRATION_SYNC_FIELDS` (`["enabled"]` — no `auto_sync`, read-only) |
| `installer/flow/installer_flow.py:335-338` | Add `("confluence", configure_confluence)` to integration loop |
| `installer/flow/integration_config.py` | New function `configure_confluence(console)` — see "Wizard UX" |
| `installer/flow/wizard.py:23` | Add `"confluence"` to `_PROJ_PLUGINS` |
| `installer/wizard_specs.py:21` | Add `"confluence"` to `YamlFile` `Literal` |
| `installer/wizard.py:606` | Add `"confluence"` to `proj_plugins` set (legacy rich-wizard parity) |
| `installer/defaults.yaml:55-70` | Add `sync.confluence: {enabled: false}` (no `auto_sync`) |
| `/home/raul/projects/claude-project-manager/CLAUDE.md` | Add confluence bullet to plugin list; add port 19108 row to port table |
| Root `README.md` | Add 6 new skill rows (confluence category) + Skills-by-category entries |

### Wizard UX flow (`configure_confluence`)

1. Prompt: "Confluence deployment?" → `cloud | server | auto` (default: `auto`).
2. Prompt: "Base URL?" → e.g. `https://example.atlassian.net` or `https://confluence.example.com`.
3. Compute effective deployment (user choice or auto-detect from base_url host).
4. Conditional creds:
   - Cloud → prompt `email` + `api_token`.
   - Server → prompt `personal_access_token`.
5. Optional prompt: "Restrict to specific space keys? (comma-separated, empty = all)".
6. Validate: attempt `GET <base>/<api_base>/space?limit=1` with assembled auth header. 200 → pass. 401 → re-prompt creds. Other (network, DNS) → warn + allow save anyway.
7. Write `~/.claude/confluence.yaml`.
8. Update `~/.claude/proj.yaml` → `sync.confluence.enabled: true`.
9. Update `~/.claude/settings.json` → add `mcp__confluence__*` allow rule via `sandbox_batch_setup(mcp_servers=["confluence"])`.

### Upgrade path for existing users

Existing installs: on next `cpm` run, wizard detects missing `sync.confluence` in `~/.claude/proj.yaml` and prompts. Alternative: `claude plugin install confluence@claude-project-manager` + re-run `cpm` to configure. Read-only means no sync-state migration.

### Uninstall

`installer/uninstall.py` matches the existing jira/trello/todoist pattern — it does not remove per-integration yaml files. Document in plugin README that `~/.claude/confluence.yaml` is manual cleanup.

## Testing

Three tiers: unit, contract/e2e-mock (respx), e2e live (env-gated).

### Directory layout

```
plugins/confluence/server/tests/
  conftest.py                    # fixtures: mock_confluence_client, cloud_config, server_config, sample_html, sample_md
  __init__.py
  contracts/
    __init__.py
    search.py                    # SEARCH_CLOUD, SEARCH_SERVER EndpointContract defs
    pages.py                     # GET_PAGE, GET_PAGE_BY_TITLE, TREE, LIST_PAGES
    spaces.py                    # LIST_SPACES
    metadata.py                  # LIST_ATTACHMENTS, LIST_COMMENTS
    errors.py                    # ErrorContract: 401, 403, 404, 429, 500
  fixtures/
    sample_view_01.html ... _10.html
    expected_md_01.md   ... _10.md
  test_config.py                 # yaml load/merge/env precedence; deployment detection
  test_init.py                   # confluence_init tool tests
  test_client.py                 # auth header assembly (Basic vs Bearer), base path resolution
  test_markdown.py               # html_to_markdown() paired fixtures
  test_ratelimit.py              # token bucket, refill, 429 retry, Retry-After honoring
  test_search.py                 # unit: tool parsing (mocked client)
  test_pages.py                  # unit
  test_spaces.py                 # unit
  test_tree.py                   # tree-flatten + nesting logic (mocked client)
  test_attachments.py            # unit
  test_comments.py               # unit
  test_contracts_search.py       # respx: real ConfluenceClient + EndpointContract validation (Cloud + Server)
  test_contracts_pages.py        # respx: real client, contracts (Cloud + Server)
  test_contracts_spaces.py       # respx: real client, contracts
  test_contracts_tree.py         # respx: real client, contracts
  test_contracts_metadata.py     # respx: real client, attachments + comments contracts
  test_contracts_errors.py       # 401/403/404/429/500 → correct typed exception raised; 429 retry + Retry-After honored
  e2e/
    __init__.py
    README.md                    # how to set env + required scopes
    test_e2e_cloud.py            # gated: CONFLUENCE_E2E_CLOUD=1
    test_e2e_server.py           # gated: CONFLUENCE_E2E_SERVER=1
```

### Tier 1: Unit tests

Mock `get_client()` globally via `conftest.py`'s `mock_confluence_client` fixture (mirrors `mock_jira_client` at `plugins/jira/server/tests/conftest.py:32-44`). Test tool-level input parsing, response shaping, and error re-raising. Fast; no network.

### Tier 2: Contract / e2e-mock tests

Mirror `plugins/jira/server/tests/test_contracts_issues.py` pattern:
- Real `ConfluenceClient` instance (via `cloud_config` + `server_config` fixtures — two variants).
- `respx.mock` intercepts httpx traffic at the HTTP layer.
- Mock responses built via shared `build_success_response` / `build_error_response` helpers from `plugins/_shared/test_contracts/builders.py`.
- Validate request method/URL/headers via `assert_request_matches_contract` (shared in `plugins/_shared/test_contracts/validators.py`).
- Validate parsed response shape via `assert_response_parses`.

`tests/contracts/*.py` defines `EndpointContract` instances:

```python
# tests/contracts/search.py
from test_contracts.base import EndpointContract

_CLOUD_BASIC_HEADERS = {"Authorization": "Basic {b64_email_token}"}
_SERVER_BEARER_HEADERS = {"Authorization": "Bearer {token}"}

SEARCH_CLOUD = EndpointContract(
    method="GET",
    url_pattern="/wiki/rest/api/search",
    required_headers=_CLOUD_BASIC_HEADERS,
    auth_style="basic",
    request_schema=None,
    response_schema={
        "properties": {
            "results": {"type": "array"},
            "size": {"type": "integer"},
            "totalSize": {"type": "integer"},
        }
    },
    response_status=200,
)

SEARCH_SERVER = EndpointContract(
    method="GET",
    url_pattern="/rest/api/search",
    required_headers=_SERVER_BEARER_HEADERS,
    auth_style="bearer",
    request_schema=None,
    response_schema={...same as cloud...},
    response_status=200,
)
```

Each tool gets Cloud + Server contract variants; tests are parametrized over both.

Pre-work: `plugins/_shared/test_contracts/base.py` currently declares `auth_style` as `"bearer" | "query_params"`. Extend to also accept `"basic"`. Update `builders.py` + `validators.py` to handle Basic auth header assembly + validation.

### Tier 3: E2E live tests

Opt-in via env vars:
- `CONFLUENCE_E2E_CLOUD=1` + `CONFLUENCE_E2E_CLOUD_BASE_URL` + `CONFLUENCE_E2E_CLOUD_EMAIL` + `CONFLUENCE_E2E_CLOUD_API_TOKEN` + `CONFLUENCE_E2E_CLOUD_TEST_SPACE_KEY`
- `CONFLUENCE_E2E_SERVER=1` + `CONFLUENCE_E2E_SERVER_BASE_URL` + `CONFLUENCE_E2E_SERVER_PAT` + `CONFLUENCE_E2E_SERVER_TEST_SPACE_KEY`

Skipped by default (pytest skipif). Each live suite exercises a dedicated read-only test space: search, get_page, list_spaces, list_pages, tree, attachments, comments. Assertions are shape-checks (not content-specific) so the test space content can change over time without breaking CI.

Run locally: `pytest tests/e2e/ -m "e2e_cloud or e2e_server"` with env loaded. CI: dedicated optional job, not in the default gate.

### Coverage target

80%+ (matches jira plugin). `pytest --cov=server --cov-fail-under=80 -n auto` wired via `pyproject.toml`.

## Hooks + dispatch

`main.py`:

```python
from hook_dispatch import enable_hook_dispatch
from hook_transport import run_dual
from mcp.server.fastmcp import FastMCP
from server.tools import init, search, pages, spaces, attachments, comments

mcp = FastMCP("confluence")
enable_hook_dispatch(mcp, exclude={"confluence_init"})
init.register(mcp)
search.register(mcp)
pages.register(mcp)
spaces.register(mcp)
attachments.register(mcp)
comments.register(mcp)

def main() -> None:
    run_dual(mcp, "confluence", default_port=19108)

if __name__ == "__main__":
    main()
```

`default-hooks.yaml` is empty (`hooks: []`), so dispatch events find no matching hooks and return quickly (~1ms overhead per call). `confluence_init` is excluded from dispatch entirely.

## Documentation + housekeeping

- `plugins/confluence/README.md` — install, config, skill reference, troubleshooting (401, 403, 429), macro limitations.
- Root `README.md` — 6 new skill rows + Skills-by-category entries.
- `/home/raul/projects/claude-project-manager/CLAUDE.md` — plugin overview bullet, port 19108 row.
- Plugin version 1.0.0. Bump both `plugins/confluence/.claude-plugin/plugin.json` and root `.claude-plugin/marketplace.json` together per project convention.

## Acceptance criteria

1. `cpm` installer lists confluence in plugin selection; selecting it runs `configure_confluence` flow.
2. Wizard writes valid `~/.claude/confluence.yaml` for both Cloud and Server deployments.
3. MCP server starts on port 19108 (Unix socket + TCP fallback).
4. All 8 MCP tools work end-to-end against both Cloud and Server (via e2e live tests when env configured).
5. All 6 skills callable with documented args, produce documented output format.
6. Contract tests pass for both Cloud-Basic and Server-Bearer variants.
7. Unit + contract test coverage ≥ 80%.
8. Rate limiter honors 429 `Retry-After` header; preemptive slow on Cloud when `X-RateLimit-Remaining < 2`.
9. `allowed_spaces` filter blocks space access in every tool that takes `space_key` (search, list_pages, get_page by title).
10. README + CLAUDE.md + port table updates land in the same PR.

## Open questions

None blocking. Resolved in brainstorm Q&A:
- Deployment: both (auto-detect from base_url).
- Operations scope: search, get_page, list_spaces, list_pages, page_tree, attachments, comments — all included.
- Skill layout: 6 focused skills.
- Content format: markdown conversion via server-rendered view HTML + markdownify; no proj coupling.
- Pagination: explicit `start`/`limit`, no auto-pagination.
- Rate limit: client-side token bucket + 429 retry; no local caching.
- API target: v1 on both deployments (Cloud v2 rejected due to CQL + pagination + comment-split gaps).
- Testing: unit + contract (respx) + e2e live (env-gated) — three tiers; contracts like jira.
- Installer: full wizard integration + marketplace registration.

## Implementation plan

To be written next via the `superpowers:writing-plans` skill. Expected output: `docs/superpowers/plans/2026-04-21-confluence-plugin.md` with phased, reviewable steps.
