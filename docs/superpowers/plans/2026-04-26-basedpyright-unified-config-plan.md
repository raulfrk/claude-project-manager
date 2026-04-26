# basedpyright Unified Config Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the per-plugin `basedpyright` loop in `.pre-commit-config.yaml` with a single invocation backed by a top-level `pyrightconfig.json` containing per-plugin `executionEnvironments`. Delete `[tool.basedpyright]` sections from all plugin `pyproject.toml` files so the top-level config is the single source of truth.

**Architecture:** basedpyright searches parent directories for a config file; deeper configs win. By creating `/pyrightconfig.json` AND deleting the deeper `[tool.basedpyright]` sections, every basedpyright invocation (pre-commit batch OR local-dev `cd plugins/<x>/server && uv run basedpyright`) reads the SAME top-level config. 8 of 9 plugins share a "proj-style" set of overrides — make those top-level defaults; wiki has a stricter variant — give wiki an executionEnvironment that re-enables those rules.

**Tech Stack:** basedpyright (v1.20+), pre-commit, uv, Python 3.12.

**Spec:** `docs/superpowers/specs/2026-04-26-basedpyright-unified-config-design.md`.

---

## Files Touched

**Create**:
- `/pyrightconfig.json` — top-level config, single source of truth.

**Modify**:
- `.pre-commit-config.yaml` — replace basedpyright hook entry.
- `plugins/_shared/pyproject.toml` — delete `[tool.basedpyright]` section.
- `plugins/proj/server/pyproject.toml` — delete `[tool.basedpyright]` section.
- `plugins/router/server/pyproject.toml` — delete `[tool.basedpyright]` section.
- `plugins/wiki/server/pyproject.toml` — delete `[tool.basedpyright]` section.
- `plugins/todoist/server/pyproject.toml` — delete `[tool.basedpyright]` section.
- `plugins/trello/server/pyproject.toml` — delete `[tool.basedpyright]` section.
- `plugins/jira/server/pyproject.toml` — delete `[tool.basedpyright]` section.
- `plugins/worktree/server/pyproject.toml` — delete `[tool.basedpyright]` section.
- `plugins/confluence/server/pyproject.toml` — delete `[tool.basedpyright]` section.

**Verified inventory** (`grep -rln '\[tool.basedpyright\]' plugins/`): 9 files. zoxide has no server pyproject. 8 use the proj-style overrides; wiki uses a minimal/stricter variant.

---

## Task 1: Capture baseline error counts

**Files:** none modified. Records pre-migration state for Task 6 verification.

- [ ] **Step 1: Run baseline capture script**

```bash
cd /home/raul/projects/claude-project-manager
mkdir -p /tmp/basedpyright-baseline
for d in plugins/*/server plugins/_shared; do
  if [ -f "$d/pyproject.toml" ] && grep -q '\[tool.basedpyright\]' "$d/pyproject.toml"; then
    name=$(echo "$d" | sed 's|plugins/||;s|/server||;s|/||')
    echo "==> $d"
    if [ "$d" = "plugins/_shared" ]; then
      (cd "$d" && uv run python -m basedpyright hook_transport hook_dispatch sandbox session_key claudemd 2>&1) > "/tmp/basedpyright-baseline/$name.txt" 2>&1
    else
      (cd "$d" && uv run python -m basedpyright server 2>&1) > "/tmp/basedpyright-baseline/$name.txt" 2>&1
    fi
    err_count=$(grep -c 'error' "/tmp/basedpyright-baseline/$name.txt" || true)
    echo "$name: $err_count errors"
  fi
done | tee /tmp/basedpyright-baseline/summary.txt
```

Expected: each plugin reports a number of errors (often 0; some may have informational diagnostics). The exact numbers become the baseline for Task 6.

- [ ] **Step 2: Stash the baseline files**

```bash
ls -la /tmp/basedpyright-baseline/
cat /tmp/basedpyright-baseline/summary.txt
```

Don't commit these — they're in `/tmp/`. Reference them in Task 6.

---

## Task 2: Create top-level `pyrightconfig.json`

**Files:**
- Create: `/pyrightconfig.json`

- [ ] **Step 1: Write `pyrightconfig.json`**

Create `/home/raul/projects/claude-project-manager/pyrightconfig.json`:

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
    "plugins/_shared/hook_dispatch",
    "plugins/_shared/hook_transport",
    "plugins/_shared/sandbox",
    "plugins/_shared/session_key",
    "plugins/_shared/claudemd"
  ],
  "reportUnusedFunction": false,
  "reportUnknownMemberType": false,
  "reportUnknownVariableType": false,
  "reportUnknownArgumentType": false,
  "reportUnknownParameterType": false,
  "reportPrivateUsage": false,
  "reportMissingTypeStubs": false,
  "reportUnnecessaryIsInstance": false,
  "executionEnvironments": [
    {
      "root": "plugins/wiki/server/server",
      "reportUnknownMemberType": true,
      "reportUnknownVariableType": true,
      "reportUnknownArgumentType": true,
      "reportUnknownParameterType": true,
      "reportUnnecessaryIsInstance": true
    }
  ]
}
```

Top-level applies the proj-style overrides used by 8/9 plugins. Wiki environment re-enables the 5 rules that wiki keeps strict (per its current `[tool.basedpyright]` which only disables `reportUnusedFunction`, `reportMissingTypeStubs`, `reportPrivateUsage`).

- [ ] **Step 2: Verify config parses**

```bash
cd /home/raul/projects/claude-project-manager
uv run --directory plugins/_shared python -c 'import json; json.load(open("pyrightconfig.json")); print("OK")'
```

Expected: `OK`.

- [ ] **Step 3: Test single-invocation analysis**

```bash
cd /home/raul/projects/claude-project-manager
uv run --directory plugins/_shared python -m basedpyright 2>&1 | tail -5
```

Expected: basedpyright runs to completion (may report errors — those are the analyzed diagnostics, not config errors). If basedpyright complains about config syntax, fix the JSON.

- [ ] **Step 4: Commit**

```bash
git add pyrightconfig.json
git commit -m "feat(basedpyright): top-level pyrightconfig.json w/ executionEnvironments"
```

---

## Task 3: Verify executionEnvironment override semantics work

**Critical sanity check before deleting per-plugin configs.** Verifies that an executionEnvironment can override a rule from `false` (top-level) back to `true` (wiki's stricter setting).

- [ ] **Step 1: Write a test file w/ a triggering issue**

Create a temporary file `plugins/wiki/server/server/__test_unknown_member.py`:

```python
"""Temp file to verify wiki's reportUnknownMemberType override re-enables strictness."""

from __future__ import annotations


def consume_unknown(x):  # type: ignore[no-untyped-def]
    return x.unknown_attr  # should fire reportUnknownMemberType in wiki env
```

- [ ] **Step 2: Run basedpyright on the file from repo root**

```bash
cd /home/raul/projects/claude-project-manager
uv run --directory plugins/_shared python -m basedpyright plugins/wiki/server/server/__test_unknown_member.py 2>&1
```

Expected output: includes a `reportUnknownMemberType` error (because wiki env re-enables it) OR `reportMissingParameterType` etc. — at minimum, the wiki-env strict rules surface.

If the wiki env override does NOT re-enable strictness (basedpyright limitation), STOP HERE — fall back to a different config strategy:

**Fallback strategy**: top-level config has the WIKI-style minimal overrides (few rules disabled); each non-wiki plugin gets its own executionEnvironment block disabling the additional rules. More verbose config but guaranteed to work. Replace `pyrightconfig.json` content with the verbose version and continue.

- [ ] **Step 3: Run from wiki dir to confirm parent-dir search**

```bash
cd /home/raul/projects/claude-project-manager/plugins/wiki/server
uv run python -m basedpyright server/__test_unknown_member.py 2>&1
```

Expected: SAME error reported. Confirms basedpyright walks up from `plugins/wiki/server/server/` to find `/pyrightconfig.json`.

- [ ] **Step 4: Clean up test file**

```bash
rm /home/raul/projects/claude-project-manager/plugins/wiki/server/server/__test_unknown_member.py
```

No commit (file deleted before any commit).

---

## Task 4: Delete `[tool.basedpyright]` from all plugin pyproject.toml files

**Files:** all 9 listed at top of plan.

- [ ] **Step 1: Delete from `plugins/_shared/pyproject.toml`**

Read `plugins/_shared/pyproject.toml`. Find the `[tool.basedpyright]` block (currently lines have `typeCheckingMode = "strict"`, etc., until the next `[tool.X]` or end-of-file boundary).

Use `Edit` tool to replace the entire block + immediate trailing blank line with a one-line comment:

```toml
# basedpyright config: see /pyrightconfig.json (top-level, single source of truth)
```

- [ ] **Step 2: Repeat for each of the other 8 plugin pyproject.toml files**

Same operation for each:
- `plugins/proj/server/pyproject.toml`
- `plugins/router/server/pyproject.toml`
- `plugins/wiki/server/pyproject.toml`
- `plugins/todoist/server/pyproject.toml`
- `plugins/trello/server/pyproject.toml`
- `plugins/jira/server/pyproject.toml`
- `plugins/worktree/server/pyproject.toml`
- `plugins/confluence/server/pyproject.toml`

For each: `Read` to find exact block + `Edit` to replace.

- [ ] **Step 3: Verify zero remaining `[tool.basedpyright]` sections**

```bash
cd /home/raul/projects/claude-project-manager
grep -rn '\[tool.basedpyright\]' plugins/
```

Expected: ZERO matches.

- [ ] **Step 4: Commit**

```bash
git add plugins/*/server/pyproject.toml plugins/_shared/pyproject.toml
git commit -m "refactor(basedpyright): delete per-plugin [tool.basedpyright] (top-level config is SoT)"
```

---

## Task 5: Update pre-commit hook

**Files:**
- Modify: `.pre-commit-config.yaml`

- [ ] **Step 1: Read current `.pre-commit-config.yaml`**

```bash
cat /home/raul/projects/claude-project-manager/.pre-commit-config.yaml
```

Identify the `basedpyright` hook block (currently has `entry: bash -c '...for dir in plugins/*/server...'`).

- [ ] **Step 2: Replace the basedpyright hook**

Use `Edit` to replace the existing block:

```yaml
      - id: basedpyright
        name: basedpyright
        entry: bash -c 'export UV_CACHE_DIR="${UV_CACHE_DIR:-.uv-cache}"; exit_code=0; for dir in plugins/*/server; do echo "==> basedpyright $dir"; uv run --directory "$dir" python -m basedpyright server || exit_code=1; done; echo "==> basedpyright plugins/_shared"; uv run --directory plugins/_shared python -m basedpyright hook_transport hook_dispatch || exit_code=1; exit $exit_code'
        language: system
        pass_filenames: false
        types: [python]
```

With:

```yaml
      - id: basedpyright
        name: basedpyright
        entry: uv run --directory plugins/_shared python -m basedpyright
        language: system
        pass_filenames: false
        types: [python]
```

- [ ] **Step 3: Run the new hook directly to verify it works**

```bash
cd /home/raul/projects/claude-project-manager
uv run --directory plugins/_shared python -m basedpyright 2>&1 | tail -10
```

Expected: basedpyright analyzes all `include` paths from `pyrightconfig.json`. Reports diagnostics (errors + warnings if any). Exit code 0 if no errors, non-zero if there are errors. The migration MUST not introduce new errors — Task 6 verifies parity.

- [ ] **Step 4: Commit**

```bash
git add .pre-commit-config.yaml
git commit -m "feat(pre-commit): single basedpyright invocation via top-level pyrightconfig.json"
```

---

## Task 6: Per-plugin error parity verification

**Critical**: confirms the migration didn't change any plugin's error set.

- [ ] **Step 1: Capture post-migration error counts using the SAME methodology as Task 1**

```bash
cd /home/raul/projects/claude-project-manager
mkdir -p /tmp/basedpyright-postmigration
for d in plugins/*/server plugins/_shared; do
  if [ -f "$d/pyproject.toml" ]; then
    name=$(echo "$d" | sed 's|plugins/||;s|/server||;s|/||')
    if [ "$d" = "plugins/_shared" ]; then
      (cd "$d" && uv run python -m basedpyright hook_transport hook_dispatch sandbox session_key claudemd 2>&1) > "/tmp/basedpyright-postmigration/$name.txt" 2>&1
    else
      (cd "$d" && uv run python -m basedpyright server 2>&1) > "/tmp/basedpyright-postmigration/$name.txt" 2>&1
    fi
    err_count=$(grep -c 'error' "/tmp/basedpyright-postmigration/$name.txt" || true)
    echo "$name: $err_count errors"
  fi
done | tee /tmp/basedpyright-postmigration/summary.txt
```

- [ ] **Step 2: Diff baseline vs post-migration**

```bash
diff /tmp/basedpyright-baseline/summary.txt /tmp/basedpyright-postmigration/summary.txt
```

Expected: NO differences. If any plugin's error count changed, the executionEnvironment is missing/wrong for that plugin. Fix `pyrightconfig.json` and re-run.

- [ ] **Step 3: Confirm local-dev parity**

```bash
cd /home/raul/projects/claude-project-manager/plugins/wiki/server
LOCAL_OUT=$(uv run python -m basedpyright server 2>&1 | grep -c 'error' || true)
echo "wiki local: $LOCAL_OUT"

cd /home/raul/projects/claude-project-manager
ROOT_OUT=$(uv run --directory plugins/_shared python -m basedpyright plugins/wiki/server/server 2>&1 | grep -c 'error' || true)
echo "wiki from root: $ROOT_OUT"

[ "$LOCAL_OUT" = "$ROOT_OUT" ] && echo "PARITY OK" || echo "PARITY FAIL"
```

Expected: `PARITY OK`. Confirms basedpyright's parent-dir search finds top-level `pyrightconfig.json` from a plugin subdirectory.

- [ ] **Step 4: Repeat parity check for one proj-style plugin (e.g. proj)**

```bash
cd /home/raul/projects/claude-project-manager/plugins/proj/server
LOCAL_OUT=$(uv run python -m basedpyright server 2>&1 | grep -c 'error' || true)
cd /home/raul/projects/claude-project-manager
ROOT_OUT=$(uv run --directory plugins/_shared python -m basedpyright plugins/proj/server/server 2>&1 | grep -c 'error' || true)
[ "$LOCAL_OUT" = "$ROOT_OUT" ] && echo "PROJ PARITY OK" || echo "PROJ PARITY FAIL"
```

Expected: `PROJ PARITY OK`.

If either parity check fails: investigate the executionEnvironment for that plugin in `pyrightconfig.json`. Likely cause: a missing override or wrong root path.

- [ ] **Step 5: Time savings measurement (informational)**

```bash
cd /home/raul/projects/claude-project-manager
time bash -c 'exit_code=0; for dir in plugins/*/server; do uv run --directory "$dir" python -m basedpyright server > /dev/null 2>&1 || exit_code=1; done; uv run --directory plugins/_shared python -m basedpyright hook_transport hook_dispatch > /dev/null 2>&1 || exit_code=1; exit $exit_code'
```

Note the time. Then:

```bash
time uv run --directory plugins/_shared python -m basedpyright > /dev/null 2>&1
```

Note the time. Document the percentage reduction in the PR / commit message (informational; not a hard pass/fail gate).

---

## Task 7: End-to-end pre-commit hook test

**Files:** no permanent changes.

- [ ] **Step 1: Trigger pre-commit via a touch + commit attempt**

```bash
cd /home/raul/projects/claude-project-manager
# Create a dummy whitespace change in a Python file
touch plugins/proj/server/server/main.py
git add plugins/proj/server/server/main.py
SKIP=ruff,ruff-format,update-readme,check-shared-version pre-commit run basedpyright --files plugins/proj/server/server/main.py
```

Expected: basedpyright hook runs the new single-invocation entry, completes successfully (or reports the same diagnostics as Task 6).

- [ ] **Step 2: Reset the staged change**

```bash
git reset HEAD plugins/proj/server/server/main.py
```

(Don't commit the touch.)

---

## Task 8: Final cleanup + commit

- [ ] **Step 1: Verify no leftover stale files**

```bash
cd /home/raul/projects/claude-project-manager
git status
```

Expected: clean working tree (after Task 7's reset). All committed changes are: `pyrightconfig.json` (Task 2), 9 pyproject.toml deletions (Task 4), `.pre-commit-config.yaml` (Task 5).

- [ ] **Step 2: Run lint on the modified files**

```bash
uv run --directory plugins/_shared ruff check . 2>&1 | tail -5
uv run --directory plugins/_shared ruff format --check . 2>&1 | tail -5
```

Expected: clean.

- [ ] **Step 3: Run a representative plugin's test suite (sanity check)**

```bash
cd plugins/proj/server && uv run pytest 2>&1 | tail -5
```

Expected: ALL pass. Coverage threshold met.

- [ ] **Step 4: Commit any formatting fixes (if any)**

```bash
git add -u
git diff --cached
# If diff is non-empty:
git commit -m "style: ruff fixes for basedpyright unified config migration"
```

If diff is empty, skip.

---

## Acceptance criteria recap

1. `/pyrightconfig.json` exists with executionEnvironments preserving every override from the deleted per-plugin sections. **Task 2.**
2. `.pre-commit-config.yaml` `basedpyright` hook is a single `uv run` invocation (no bash loop). **Task 5.**
3. Per-plugin error parity: 0 difference vs baseline. **Task 6 step 2.**
4. Local-dev parity: same error count whether basedpyright is invoked from plugin dir or repo root. **Task 6 steps 3-4.**
5. No `[tool.basedpyright]` sections remain in any plugin `pyproject.toml`. **Task 4 step 3.**
6. Pre-commit hook runs end-to-end successfully. **Task 7.**
7. (Informational) Time saving documented. **Task 6 step 5.**
