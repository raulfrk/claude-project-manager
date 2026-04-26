# basedpyright unified config (todo 760)

**Date**: 2026-04-26
**Source todo**: 760 — `Pre-commit: batch basedpyright across all plugins instead of looping per-plugin`
**Status**: design pre-approved, ready for plan
**Origin**: VM-freeze investigation 2026-04-26 (originally framed as memory amplifier; rescoped to dev-loop perf improvement after freeze cause was refuted as primary OOM hypothesis).

## Problem

`.pre-commit-config.yaml` runs basedpyright in a sequential bash loop:

```bash
for dir in plugins/*/server; do
  uv run --directory "$dir" python -m basedpyright server || exit_code=1
done
uv run --directory plugins/_shared python -m basedpyright hook_transport hook_dispatch
```

Each iteration spawns: `uv` resolution + Python interpreter + basedpyright module init + cold-start type analysis. ~8 plugins × 2-3s each = ~16-24s total per commit. Memory peaks per invocation but they run sequentially (so peak is single-process, not amplified).

Originally framed (todo 760 notes) as "memory amplifier when 2 sessions commit concurrently → +1.4GB spike." After the VM-freeze re-investigation refuted the cross-process flock deadlock hypothesis (see memory `project_vm_freeze_root_cause.md`), the freeze cause is now unverified. **760 is repurposed as a dev-loop perf improvement** — concurrent commits are rare; the real win is faster pre-commit on every commit.

## Solution overview

Single basedpyright invocation analyzing all plugin source paths. Per-plugin overrides preserved via `executionEnvironments` in a top-level `pyrightconfig.json`. Per-plugin `[tool.basedpyright]` sections in plugin `pyproject.toml` files are **deleted** to make the top-level config the single source of truth (basedpyright config search walks up parent dirs; deeper config wins, so removing the deeper config makes the top-level config authoritative).

Result:
- Pre-commit `basedpyright` runs once instead of 8 times. Estimated 60-80% time reduction.
- Local-dev `cd plugins/<name>/server && uv run basedpyright server` walks up to find top-level `pyrightconfig.json`, applies the matching executionEnvironment. Same behavior as pre-commit invocation.
- Drift between pre-commit + local-dev configs is structurally impossible (single source of truth).

## Layer 1: top-level `/pyrightconfig.json`

```json
{
  "typeCheckingMode": "strict",
  "pythonVersion": "3.12",
  "include": [
    "plugins/proj/server/server",
    "plugins/router/server/server",
    "plugins/wiki/server/server",
    "plugins/worktree/server/server",
    "plugins/todoist/server/server",
    "plugins/trello/server/server",
    "plugins/jira/server/server",
    "plugins/confluence/server/server",
    "plugins/zoxide/server/server",
    "plugins/_shared/hook_dispatch",
    "plugins/_shared/hook_transport",
    "plugins/_shared/sandbox",
    "plugins/_shared/session_key",
    "plugins/_shared/claudemd"
  ],
  "executionEnvironments": [
    {
      "root": "plugins/wiki/server/server",
      "reportUnusedFunction": false,
      "reportMissingTypeStubs": false,
      "reportPrivateUsage": false
    },
    {
      "root": "plugins/proj/server/server",
      "reportUnusedFunction": false,
      "reportUnknownMemberType": false,
      "reportUnknownVariableType": false,
      "reportUnknownArgumentType": false,
      "reportUnknownParameterType": false,
      "reportPrivateUsage": false,
      "reportMissingTypeStubs": false,
      "reportUnnecessaryIsInstance": false
    },
    {
      "root": "plugins/router/server/server",
      "reportUnusedFunction": false,
      "reportUnknownMemberType": false,
      "reportUnknownVariableType": false,
      "reportUnknownArgumentType": false,
      "reportUnknownParameterType": false,
      "reportPrivateUsage": false,
      "reportMissingTypeStubs": false,
      "reportUnnecessaryIsInstance": false
    },
    {
      "root": "plugins/_shared",
      "reportUnusedFunction": false,
      "reportUnknownMemberType": false,
      "reportUnknownVariableType": false,
      "reportUnknownArgumentType": false,
      "reportUnknownParameterType": false,
      "reportPrivateUsage": false,
      "reportMissingTypeStubs": false,
      "reportUnnecessaryIsInstance": false
    }
  ]
}
```

**Per-plugin overrides preserved** — implementer audits every `plugins/*/server/pyproject.toml` + `plugins/_shared/pyproject.toml` for existing `[tool.basedpyright]` sections. Each set of overrides is mirrored as a corresponding executionEnvironment block. Plugins with no overrides (e.g. todoist, trello, jira, worktree, confluence, zoxide) inherit top-level defaults (strict + python 3.12) and DON'T need an executionEnvironment block.

**Path conventions verified** — confirmed via `grep -rn '\[tool.basedpyright\]' plugins/` during the brainstorm: proj, router, wiki, _shared have explicit overrides; others use defaults.

## Layer 2: pre-commit hook

`.pre-commit-config.yaml` — replace the bash loop:

```yaml
- id: basedpyright
  name: basedpyright
  entry: uv run --directory plugins/_shared python -m basedpyright
  language: system
  pass_filenames: false
  types: [python]
```

`uv run --directory plugins/_shared` chosen because `_shared` has basedpyright in dev deps (verify during plan). The working directory for the analysis is the repo root (pre-commit invokes hooks from repo root by default), so basedpyright reads `/pyrightconfig.json` and analyzes all paths in `include`.

## Layer 3: delete per-plugin `[tool.basedpyright]` sections

In each affected plugin's `pyproject.toml`:
- Delete the entire `[tool.basedpyright]` block.
- Add a comment in its place: `# basedpyright config: see /pyrightconfig.json (top-level, single source of truth)`.

Other sections (`[tool.pytest.ini_options]`, `[tool.coverage.run]`, `[project]`, etc.) stay unchanged.

Affected files:
- `plugins/proj/server/pyproject.toml`
- `plugins/router/server/pyproject.toml`
- `plugins/wiki/server/pyproject.toml`
- `plugins/_shared/pyproject.toml`
- Any other plugin pyproject.toml files that have `[tool.basedpyright]` sections (implementer greps to find).

## Verification gates

1. **Per-plugin error parity** — capture baseline before migration:
   ```bash
   for d in plugins/*/server; do
     echo "$d: $(cd $d && uv run basedpyright server 2>&1 | grep -c 'error')"
   done > /tmp/baseline-errors.txt
   ```
   Repeat after migration. Counts must match exactly (tolerance: 0). Any difference indicates a missing executionEnvironment override.

2. **Local-dev parity** — `cd plugins/wiki/server && uv run basedpyright server` must produce SAME error count as `cd / && uv run --directory plugins/_shared python -m basedpyright plugins/wiki/server/server`. Verifies basedpyright correctly walks up to find `/pyrightconfig.json`.

3. **Time savings measured** — implementer runs `time` on both old + new invocations; expects 60-80% reduction.

4. **Pre-commit end-to-end** — `touch plugins/proj/server/server/main.py && git add -A && git commit -m 'test'` runs the new hook, succeeds with same diagnostics as before. (Touch + revert; don't actually commit.)

5. **No remaining per-plugin sections** — `grep -rn '\[tool.basedpyright\]' plugins/` returns ZERO matches.

## Acceptance criteria

1. `/pyrightconfig.json` exists with executionEnvironments preserving every override from the deleted per-plugin sections.
2. `.pre-commit-config.yaml` `basedpyright` hook is a single `uv run` invocation (no bash loop).
3. Per-plugin error parity: 0 difference vs baseline.
4. Local-dev parity: same error count whether basedpyright is invoked from plugin dir or repo root.
5. No `[tool.basedpyright]` sections remain in any plugin `pyproject.toml`.
6. Time saving measured (informational acceptance — not a hard pass/fail; documented in PR description).

## Files affected

**Create**:
- `/pyrightconfig.json`

**Modify**:
- `.pre-commit-config.yaml`
- `plugins/proj/server/pyproject.toml`
- `plugins/router/server/pyproject.toml`
- `plugins/wiki/server/pyproject.toml`
- `plugins/_shared/pyproject.toml`
- Any other plugin pyproject.toml with `[tool.basedpyright]` (audit during implementation).

**NOT affected**:
- Plugin source code — no changes.
- Plugin tests — no changes (basedpyright analyzes test code via the same `include` paths if `tests/` is included; current behavior excludes them).

## Out of scope

- Drift-check script — single source of truth makes drift structurally impossible; no script needed.
- Caching beyond what executionEnvironments enables.
- Other lint tools (ruff already runs once per pre-commit batch via the standard mechanism).
- Test coverage — verification is empirical (error count parity).

## Cross-references

- Memory: `project_vm_freeze_root_cause.md` — why this todo's premise was reframed.
- Wiki: `[[python-quality-stack]]` (basedpyright is type checker of choice), `[[plan-verbatim-bugs-caught-by-tdd]]` (basedpyright catches `dict` vs `dict[str, object]`).
- Sibling: 764 (wiki async W1) — also in this batch, completely independent file scope.
- basedpyright docs: [executionEnvironments](https://docs.basedpyright.com/v1.20.0/configuration/config-files/).
