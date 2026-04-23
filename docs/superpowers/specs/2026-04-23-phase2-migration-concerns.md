# Phase 2 Full-Migration — Concerns and Questions

**Status**: For review before I proceed
**Date**: 2026-04-23
**Context**: You approved "full migration" over "cross-validation only". I started the work, hit friction I didn't anticipate at plan time, and want you to see it before I sink 3-5 hours of debug iterations into it.

---

## What's Already Done

- 3 vendored OpenAPI specs checked out under `plugins/<name>/server/tests/contracts/openapi/` (todoist 943 KB, trello 751 KB, confluence-cloud 404 KB)
- 2 hand-authored specs generated from existing `EndpointContract` literals (jira-dc-v2 28 KB / 28 paths, confluence-dc-v1 6 KB / 7 paths), marked `x-cpm-source: manual`
- `plugins/_shared/test_contracts/openapi.py` helper — `load()`, `endpoint_contract(spec, method, url_pattern, ...)`, ref resolution, operationId lookup
- Matching by `(method, url_pattern)` rather than `operationId` — uses fields the caller already has, zero new mapping dicts to maintain

None of that touches existing tests. It's pure addition.

---

## The Three Blockers I Hit

### Concern 1: Existing validator is schema-shape-incompatible with real OpenAPI

`plugins/_shared/test_contracts/validators.py:82` — `_validate_body_against_schema` — iterates **every** key in `schema["properties"]` and asserts it exists in the body. It doesn't respect `required: [...]`, doesn't do type checks, doesn't resolve `$ref`.

Our hand-authored schemas were minimal — 3-4 properties each — so this lightweight check worked. Real OpenAPI response schemas have 20-50 properties, most optional.

Concrete example — todoist `GET /api/v1/tasks` real response schema:

```json
{
  "type": "object",
  "required": ["results", "next_cursor"],
  "properties": {
    "results": {"type": "array", "items": {"$ref": "#/components/schemas/ItemSyncView"}},
    "next_cursor": {"anyOf": [{"type": "string"}, {"type": "null"}]}
  }
}
```

With the existing validator, if I swap this in, every test payload must include both `results` and `next_cursor`. With a proper JSON Schema validator (respecting `required`), payloads only need the fields listed in `required`. So to migrate, I have to replace the validator with a proper `jsonschema` lib call.

That's doable. `jsonschema` dep addition + rewrite `_validate_body_against_schema` to use `Draft202012Validator`. Maybe 30-60 min including registry setup for `$ref`.

**Question**: OK to rewrite the validator to use `jsonschema` lib in this same commit?

### Concern 2: Test payloads will break en masse

Even with a proper validator respecting `required`, test payloads need to include all fields the spec marks `required`. Many existing tests use minimal payloads:

```python
# plugins/confluence/server/tests/test_contracts_pages.py:21
payload = {
    "id": "42",
    "title": "T",
    "version": {"number": 1},
    "space": {"key": "DOCS"},
    "body": {"view": {"value": "<p>x</p>"}},
    "_links": {"webui": "/"},
}
```

The Confluence Cloud spec for `GET /wiki/rest/api/content/{id}` may mark additional fields as `required` (e.g. `type`, `status`, `history`, etc.). When I swap in the spec schema, this payload fails validation.

**Fix options**:

- **F1**: Add missing required fields to test payloads. Preserves drift-detection strictness. Tedious — 20-50 sites to edit.
- **F2**: Load spec schemas with `additionalProperties: true` + strip `required` at load time. Lenient — test payloads pass without modification, but the validator becomes weaker than spec intends.
- **F3**: Use a best-effort schema subset — only include properties our plugin reads from the response. Requires knowing which properties our plugin actually uses. More realistic but more work.

I don't know in advance how many tests will break — could be 5, could be 80. I only find out by running them and fixing one at a time.

**Question**: Which fix mode do you want? F1 is strictest (slowest). F2 is fastest (loosest). F3 is medium both.

### Concern 3: `$ref` chains explode when fully resolved

Todoist's `items: {"$ref": "#/components/schemas/ItemSyncView"}` references a schema that references others recursively. When I fully resolve refs to inline schemas, the resulting response_schema could be many KB per endpoint (circular cycles need detection).

`jsonschema` lib handles this natively via a `Registry` — I pass the whole spec, let it resolve at validation time. No pre-expansion needed.

This isn't really a "concern," just a note that the openapi.py helper keeps `$ref` intact and the validator needs registry support. Same 30-60 min as Concern 1.

---

## Broader Question — Single Commit vs Staged

Full migration in one commit means this commit touches:

- `plugins/_shared/test_contracts/validators.py` — rewrite to use jsonschema
- `plugins/_shared/test_contracts/openapi.py` — done
- `plugins/_shared/test_contracts/sync_openapi.py` — new
- `plugins/_shared/pyproject.toml` — add jsonschema dep + version bump
- `plugins/<name>/server/tests/contracts/*.py` — 14 files, 95 `EndpointContract` literals rewritten to `endpoint_contract()` calls
- `plugins/<name>/server/tests/test_contracts_*.py` — unknown N sites where payloads need adjustment
- 5 spec files in `plugins/<name>/server/tests/contracts/openapi/` — done
- `.github/workflows/openapi-refresh.yml` — new
- `uv.lock` across all plugins — regen

That's a single commit touching 30+ files across 4 plugins. Hard to revert if something goes sideways.

**Staged alternative** — two commits on this branch, both before rebase-merge to dev:

**Commit A (Phase 2a — infrastructure)**:
- Vendored + hand-authored specs
- `openapi.py` helper (done)
- `sync_openapi.py` CLI
- GH Actions cron
- `assert_validates_openapi_schema()` — new jsonschema validator, opt-in
- One cross-check test per plugin: for every `EndpointContract` constant in `contracts/`, assert its (method, url_pattern) exists in the vendored spec
- Zero touch on existing tests. Drift detection active via cross-check.

**Commit B (Phase 2b — migration)**:
- Rewrite 14 `contracts/*.py` files, 95 literals
- Fix test payloads as needed, file-by-file
- Each `contracts/<file>.py` could even be its own sub-commit (8 small commits total)

Both commits merge together via rebase, so user-facing history stays tidy. Debugging is local to the migration commit if payload fixes explode.

**Question**: Still single-commit "full migration", or split into 2a + 2b before the rebase?

---

## Concrete Recommendation (for the record)

If you must have full migration in one commit: go with **F2** (strip `required` at load time) to avoid the payload-fix rabbit hole. Trade off some strictness for predictability. Then tighten later in Phase 2b-ish work.

If staged is OK: do **Commit A** now with the cross-check, then **Commit B** later with proper F1 (strict) migration file-by-file. Merge to dev happens after both land.

The cross-check alone in Commit A delivers 80% of the drift-detection value (if Atlassian renames an endpoint, our hand-authored contract no longer matches the vendored spec → refresh cron picks up spec change → cross-check fails → we know). Full migration also adds "schema shape drift detection" (if Atlassian changes a field type), which is the remaining 20%.

---

## Things I Am NOT Worried About

- Vendored specs being stale: cron handles it. Done thinking about this.
- Hand-authored jira/confluence-dc specs being accurate: they were auto-generated from existing literals, so they're whatever those literals already claim.
- Pre-commit hooks: `_shared` version bump + uv.lock regen is routine now (Phase 1 did it).
- Worktree + branch: staying on feat/external-integration-testing-phase1, rebase-merge at end per your direction.
