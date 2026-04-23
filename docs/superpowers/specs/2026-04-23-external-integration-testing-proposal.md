# External Integration Testing — Credential-Free Design

**Status**: Approved (plan at `~/.claude/plans/valiant-herding-wind.md`)
**Date**: 2026-04-23
**Scope**: Testing strategy for todoist, jira, confluence, trello plugins

---

## Current State

Audit of `plugins/{todoist,jira,confluence,trello}/server/tests/`:

- **Unit tests**: `MagicMock(spec=Client)` patched at a hand-maintained `_GET_CLIENT_LOCATIONS` list in each plugin's `conftest.py`. Lists have 14 / 14 / 9 entries for todoist / jira / trello. Confluence diverges — uses real client instances, not mocks.
- **Contract tests**: `respx` + shared `EndpointContract` framework at `plugins/_shared/test_contracts/`. Response payloads are hardcoded per test. The `EndpointContract.response_schema` slot already exists but schemas are hand-authored.
- **E2E tests**: only confluence has live-API tests (`test_e2e_cloud.py`, `test_e2e_server.py`, env-gated via `CONFLUENCE_E2E_CLOUD=1` + creds). Todoist / jira / trello have none.
- **Counts**: 16 / 43 / 9 / 48 contract tests for todoist / jira / confluence / trello.

## Pain Points

1. **API schema drift undetected** — responses are mock-synthesized. When Atlassian / Trello / Todoist change response shape, tests still pass.
2. **Brittle mock-patching** — `_GET_CLIENT_LOCATIONS` breaks when new tool modules are added.
3. **Confluence divergence** — different pattern than the other three.
4. **No e2e for 3 of 4 plugins** — no real-API coverage for auth, retries, pagination, rate limits on todoist / jira / trello.
5. **No MCP tool-schema contract verification** — contract tests validate HTTP shape but not that MCP tool input/output schemas match tool definitions.

## Success Criteria

- **Catch real-API regressions** — tests fail when external API response shape changes.
- **Reduce test maintenance** — less boilerplate per new tool; no hand-maintained mock-location lists; no duplicate response construction.
- **Confidence in integration logic** — coverage of auth, retries, pagination, rate limits end-to-end.

## Hard Constraint — No Real Credentials

User will not provision test accounts for any of the four services. Rules out:

- Recorded cassettes (VCR / pytest-recording) — need real creds to record the first pass.
- Nightly sandbox e2e — needs creds + stable test accounts per service.
- Anything requiring a live connection to the real API.

All solutions must work from **public, credential-free** sources.

---

## Approach — Vendored OpenAPI + Phased Rollout

Key insight from audit: `plugins/_shared/test_contracts/base.py:EndpointContract.response_schema` already reserves a slot for JSON Schema validation. Schemas are just hand-authored today. The improvement path is to replace hand-authored schemas with references into vendored OpenAPI snapshots.

- **Jira / Confluence / Todoist**: download official OpenAPI specs (public, no creds). Vendor as snapshots.
- **Trello** (no official spec): seed from APIs.guru community spec; hand-trim to endpoints we actually call.
- Monthly GitHub Actions cron pulls upstream specs, diffs against snapshots, opens a PR when drift detected. Humans review.
- Existing contract-test framework extended to pull `response_schema` by reference (`openapi["paths"][...]["responses"]["200"]`) instead of hand-authored blobs.
- Optional Phase 4 adds `prism mock` — an OpenAPI-driven local HTTP server — for integration-logic coverage without creds.

### Phase 1 — Consolidate + auto-discover (foundation)

**Goal**: kill brittleness so later phases land cleanly.

- Replace `_GET_CLIENT_LOCATIONS` with a module-autodiscovery helper in `plugins/_shared/test_contracts/fixtures.py`. Walks the plugin's `server/tools/` package and patches `get_client` on every module found.
- Migrate confluence's conftest to the same pattern; make respx-level mocking the default, keep real-client mode as opt-in for tests that need it.
- Deduplicate `build_success_response` callsites via a `response_for(operation_id)` helper in `builders.py`.

**Critical files**:
- `plugins/_shared/test_contracts/fixtures.py` *(new)*
- `plugins/{todoist,jira,trello,confluence}/server/tests/conftest.py` *(modify)*
- `plugins/_shared/test_contracts/builders.py` *(extend)*

### Phase 2 — Vendor OpenAPI specs + schema-by-reference

**Goal**: make drift detection mechanical.

- Vendor specs at `plugins/<name>/server/tests/contracts/openapi/<name>-<ver>.json`. Sources:
  - Jira Cloud: `https://developer.atlassian.com/cloud/jira/platform/swagger-v3.v3.json`
  - Confluence Cloud: `https://developer.atlassian.com/cloud/confluence/swagger.v3.json`
  - Confluence Server/DC: scraped from Atlassian marketplace (no Cloud spec covers DC)
  - Todoist REST v2: `https://developer.todoist.com/rest/v2/openapi.json`
  - Trello: seeded from `https://api.apis.guru/v2/specs/trello.com/1.0/openapi.json`, hand-trimmed
- Add `plugins/_shared/test_contracts/openapi.py` with `load()`, `schema_for(plugin, operation_id)`, `endpoint_contract(plugin, operation_id)`.
- Migrate per-endpoint `EndpointContract` literals to `endpoint_contract(...)` calls. Hand-authored schemas vanish.
- Add `jsonschema`-based validator in `validators.py` asserting responses validate against spec.
- Add `sync_openapi.py` CLI — pulls upstream, writes snapshot, reports diff.
- Wire `.github/workflows/openapi-refresh.yml` as a monthly cron that opens a PR (no push to main).

**Critical files**:
- `plugins/<name>/server/tests/contracts/openapi/<name>-<ver>.json` *(new, vendored)*
- `plugins/_shared/test_contracts/openapi.py` *(new)*
- `plugins/_shared/test_contracts/validators.py` *(extend)*
- `plugins/_shared/test_contracts/sync_openapi.py` *(new)*
- `.github/workflows/openapi-refresh.yml` *(new)*
- `plugins/<name>/server/tests/contracts/*.py` *(migrate)*

**Reuse**: `plugins/_shared/test_contracts/base.py:EndpointContract.response_schema` — existing slot, no new dataclass. `jsonschema` already transitively available; add explicit dep to `plugins/_shared/pyproject.toml` `[dependency-groups] test`.

### Phase 3 — MCP tool-schema contract check

**Goal**: catch the second drift axis — MCP tool param/return shapes vs. tool implementation.

- Generic test per plugin that introspects every `@mcp.tool` function, compares its signature and return type to the MCP server's registered schema, fails on mismatch. Shared helper in `plugins/_shared/test_contracts/test_mcp_schemas.py` invoked by each plugin's test suite.

**Critical files**:
- `plugins/_shared/test_contracts/test_mcp_schemas.py` *(new)*
- `plugins/{todoist,jira,trello,confluence}/server/tests/test_mcp_contract.py` *(new)*

### Phase 4 *(optional)* — Prism mock server

**Goal**: real HTTP flow coverage (auth, pagination, rate-limits, error codes) without creds.

- Add `prism-cli` as dev dep. Spin up as pytest fixture pointing at vendored OpenAPI spec.
- Per-plugin `tests/integration/` — override plugin client base URL to Prism port. Prism synthesizes realistic responses and validates requests against spec.
- Gate behind `RUN_PRISM_TESTS=1` to keep default suite fast.

**Judgement**: Phases 1–3 deliver success criteria 1 and 2 cleanly. Phase 4 is the credential-free substitute for real-API e2e — valuable but overhead. Defer until Phases 1–3 settle and pain emerges.

## Trello Caveat

No official OpenAPI. Phase 2's vendored spec is the weakest link:

- Start from APIs.guru community spec.
- Trim to endpoints actually called by `plugins/trello/server/server/tools/`.
- Trello spec drifts silently — cron can't refresh automatically. Mitigation: Trello-specific check that diffs the trimmed spec against APIs.guru on the same cron, flags upstream-changed endpoints.

## Dependencies and Ordering

```
Phase 1 (consolidate) ──> Phase 2 (OpenAPI + schema-by-ref) ──> Phase 3 (MCP contract) ──> Phase 4 (Prism, optional)
```

Phase 1 first — Phase 2's migration touches every conftest.py the autodiscovery replaces. Phases 3 and 4 independent after Phase 2.

## Verification

**Phase 1**:
- `cd plugins/<name>/server && uv run pytest tests/` — full suite green for all four.
- `grep -r _GET_CLIENT_LOCATIONS plugins/` returns zero matches.
- Add a dummy tool module; autodiscovery picks it up without conftest edits.

**Phase 2**:
- `uv run python -m test_contracts.sync_openapi --plugin jira --dry-run` — prints URL, downloads, reports diff vs. vendored snapshot.
- All contract tests green using `endpoint_contract(...)`.
- Mutate a vendored spec fragment; corresponding test fails with clear schema-mismatch error.
- Manual workflow dispatch of `openapi-refresh.yml` on a throwaway branch.

**Phase 3**:
- Introduce mismatch between `@mcp.tool` signature and registered schema; `test_mcp_contract.py` flags it.

**Phase 4**:
- `RUN_PRISM_TESTS=1 uv run pytest tests/integration/` passes.
- Deliberately broken request (e.g. missing auth header) → test fails.

## What This Plan Does Not Do

- Does **not** provision real sandbox accounts or require any credentials.
- Does **not** check cassettes into git.
- Does **not** add network access to PR-gate CI (Phase 4's Prism is local).
- Does **not** touch existing `sync.*` integration code — testing-layer only.
