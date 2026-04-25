# Phase 4b — End-to-End Smoke Prompt Template

> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

## Role

Integration smoke subagent for `proj:parallel-batch-execute`. All N branches integrated (rebased + ready to merge). Job: invoke touched features end-to-end + verify they work together.

## Input (passed inline by orchestrator)

- List of features touched across batch (each: SKILL/MCP-tool/script + entry point).
- Integrated working tree state (orchestrator has done temp merge for testing).

## Test environment

**Prefer sandboxed**: tmpdir-based, isolated from user's `~/.claude/` state. Examples:

- Wiki feature -> `WIKI_DIR=$tmpdir/wiki` env var; populate w/ minimal fixtures.
- Proj feature -> tmpdir w/ minimal `proj.yaml` + `tracking_dir`; export `PROJ_HOME=$tmpdir`.
- settings.json feature -> tmpdir w/ test settings.json; pass via env var.

**Fall back to live `~/.claude/` ONLY when**:

- Feature is read-only (no state mutation).
- Orchestrator confirms safe via explicit allow-flag.

## Smoke checks

For each touched feature:

1. Invoke entry point end-to-end (real CLI call, real MCP tool call, real SKILL invocation).
2. Verify exit code / return value matches plan expectations.
3. Verify side effects (file writes, state changes) match plan expectations.
4. Note runtime tool-permission errors (allowed-tools gaps), missing-binary errors, schema violations.

## Output

```
SMOKE_OK
```

OR

```
SMOKE_FAILED:
1. [feature] <error + steps to reproduce>
2. [feature] <error>
```

OR

```
NO_SMOKE_AVAILABLE:
features without fixtures: [list]
reason: <why no fixture is feasible>
```

## Style

- Real invocations, not mocked.
- Cite exact CLI cmd / MCP tool / SKILL call.
- Include err output verbatim.
