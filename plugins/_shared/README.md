# _shared

Shared libraries used by all claude-project-manager plugins:

- `hook_transport` — dual-transport (Unix socket + TCP) HTTP client/server for inter-plugin hook dispatch
- `hook_dispatch` — FastMCP monkey-patch that wraps registered tools with post-execution hook firing
- `scrubbing` — result scrubbing/truncation utilities
- `claudemd` — managed-section read/write for CLAUDE.md files
- `test_contracts` — shared test helpers and OpenAPI contract utilities
- `session_key` — proj-session.yaml v2 pid-keyed active-project resolver

## Running tests

Full suite (all modules, coverage gate enforced):

```bash
cd plugins/_shared
uv run pytest tests/
```

## Running targeted tests

`pyproject.toml` configures `--cov` for every module + `--cov-fail-under=80`.
pytest-cov aggregates coverage across **all** `--cov` targets, so running a
single test file fails the 80% gate even when the targeted module is
well-covered — the other modules contribute 0% to the aggregate.

Use `--no-cov` to skip the threshold check for targeted runs:

```bash
uv run pytest tests/test_session_key.py -v --no-cov
uv run pytest tests/test_hook_transport.py -v --no-cov
```

The full suite (`uv run pytest tests/`) always enforces the gate and is used
in CI.
