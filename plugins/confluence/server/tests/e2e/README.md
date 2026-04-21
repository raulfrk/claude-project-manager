# Confluence E2E Live Tests

Opt-in live tests against real Confluence instances. Gated by env vars — skipped by default.

## Cloud

```bash
export CONFLUENCE_E2E_CLOUD=1
export CONFLUENCE_E2E_CLOUD_BASE_URL=https://acme.atlassian.net
export CONFLUENCE_E2E_CLOUD_EMAIL=you@example.com
export CONFLUENCE_E2E_CLOUD_API_TOKEN=<token>
export CONFLUENCE_E2E_CLOUD_TEST_SPACE_KEY=TESTDOCS
export CONFLUENCE_E2E_CLOUD_TEST_PAGE_ID=<numeric-id>
uv run pytest tests/e2e/test_e2e_cloud.py -m e2e_cloud -v
```

## Server / Data Center

```bash
export CONFLUENCE_E2E_SERVER=1
export CONFLUENCE_E2E_SERVER_BASE_URL=https://confluence.company.com
export CONFLUENCE_E2E_SERVER_PAT=<pat>
export CONFLUENCE_E2E_SERVER_TEST_SPACE_KEY=TESTDOCS
export CONFLUENCE_E2E_SERVER_TEST_PAGE_ID=<numeric-id>
uv run pytest tests/e2e/test_e2e_server.py -m e2e_server -v
```

## Requirements

- Dedicated read-only test space (assertions are shape-only; content may change).
- Test space must contain at least 1 page (use the page id in `TEST_PAGE_ID`).
- Test PAT/token needs: read spaces, read content, read attachments, read comments.
