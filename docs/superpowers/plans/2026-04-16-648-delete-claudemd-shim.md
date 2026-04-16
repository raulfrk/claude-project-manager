# Todo 648: Delete `installer.claudemd` Shim — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retire the `installer/claudemd.py` re-export shim. Rewrite the four internal importers (`installer/wizard.py`, `installer/app.py`, two installer test files) to import from `claudemd` directly, delete the shim, delete installer tests whose only purpose was exercising the shim path, and migrate any unique assertions into `plugins/_shared/tests/test_claudemd_package.py` so coverage does not regress.

**Architecture:** No behavior change. Pure import-site refactor + test-file migration. The canonical home of the managed-section logic already lives at `plugins/_shared/claudemd/` (shipped inside the `claude-hook-transport` distribution). Removing the shim tightens the import graph and eliminates a forwarding layer that 639 left in place for safety.

**Tech Stack:** Python 3.12+, pytest, uv, grep.

**Spec:** `docs/superpowers/specs/2026-04-16-tech-debt-635-648-651-design.md` §4.

**Prerequisite worktree:** `/home/raul/worktrees/cpm/feat-648-delete-claudemd-shim` on branch `feat/648-delete-claudemd-shim`. All file edits + git operations MUST happen inside this directory.

---

## File Structure

- **Modify:** `installer/wizard.py` — rewrite `installer.claudemd` import.
- **Modify:** `installer/app.py` — rewrite `installer.claudemd` import.
- **Modify:** `installer/tests/test_integration_screens.py` — rewrite `installer.claudemd` import.
- **Delete:** `installer/claudemd.py` — the shim itself.
- **Delete:** `installer/tests/test_claudemd.py` — shim-specific path-resolution tests and any behavioral tests that already duplicate `_shared` coverage.
- **Modify:** `plugins/_shared/tests/test_claudemd_package.py` — extend with any unique assertions carried over from the deleted installer test file.

Audit ordering: extend `_shared` tests FIRST, then delete the installer test file. This preserves coverage at every intermediate commit.

---

### Task 1: Create the worktree + install deps

**Files:** none yet.

- [ ] **Step 1: Create worktree via `wt_create` MCP tool**

Call `mcp__plugin_worktree_worktree__wt_create` with:
```json
{
  "repo_label": "cpm",
  "branch": "feat/648-delete-claudemd-shim",
  "base_branch": "dev"
}
```
Expected: worktree created at `/home/raul/worktrees/cpm/feat-648-delete-claudemd-shim`.

- [ ] **Step 2: Install `_shared` + installer deps once**

The `installer` package (`cpm-install`) is declared at the repo-root `pyproject.toml`, not inside `installer/`. `_shared` must install first because installer declares it as a `uv.sources` path dep.

```bash
cd /home/raul/worktrees/cpm/feat-648-delete-claudemd-shim
(cd plugins/_shared && uv sync --all-groups)
uv sync --all-groups
```
Expected: both commands exit 0.

---

### Task 2: Audit the two test files for coverage parity

**Files:** none modified (read-only audit).

- [ ] **Step 1: Read `installer/tests/test_claudemd.py`**

```bash
cd /home/raul/worktrees/cpm/feat-648-delete-claudemd-shim
cat installer/tests/test_claudemd.py
```
Record every test class / function name and the behavior it asserts. Specifically note:
- `ensure_managed_section` cases (create-when-missing, append-to-empty, append-after-user-content, idempotency on re-call, marker-block integrity after edits).
- `remove_managed_section` cases.
- `has_managed_section` cases.
- Any path-resolution tests that reach into `installer.claudemd`'s `__file__` — these are shim-specific and will be deleted.

- [ ] **Step 2: Read `plugins/_shared/tests/test_claudemd_package.py`**

```bash
cat plugins/_shared/tests/test_claudemd_package.py
```
Record every test class / function. Compare against the installer-file list from Step 1.

- [ ] **Step 3: Draft the migration list**

Produce a scratch note listing:
- Tests in `installer/tests/test_claudemd.py` with NO equivalent in `plugins/_shared/tests/test_claudemd_package.py` → MIGRATE.
- Tests in `installer/tests/test_claudemd.py` that duplicate `_shared` coverage → DELETE WITHOUT PORTING.
- Tests in `installer/tests/test_claudemd.py` that rely on the shim's `__file__` / import path → DELETE (meaningless after shim removal).

Keep this note in the commit message for Task 3 so the deletion in Task 7 is justifiable.

No commit in this task.

---

### Task 3: Extend `plugins/_shared/tests/test_claudemd_package.py`

**Files:**
- Modify: `plugins/_shared/tests/test_claudemd_package.py`

- [ ] **Step 1: Add each unique installer test from the Task 2 migration list**

For every test in the MIGRATE list: copy the test body into `plugins/_shared/tests/test_claudemd_package.py`, rewriting its imports so they reference `claudemd` directly (the `installer.claudemd` shim will not exist by the end of this branch).

Rewrite rules:
- `from installer.claudemd import ensure_managed_section, MARKER_START, ...` → `from claudemd import ensure_managed_section, MARKER_START, ...`
- `import installer.claudemd as claudemd` → `import claudemd`
- Fixture / helper names stay the same.

Preserve each test's docstring verbatim so the history in blame remains readable.

- [ ] **Step 2: Run the `_shared` test suite**

```bash
cd /home/raul/worktrees/cpm/feat-648-delete-claudemd-shim/plugins/_shared
uv run pytest tests/test_claudemd_package.py -v
```
Expected: all tests PASS — the migrated ones and the pre-existing ones. If any migrated test fails, the test body carried over a dependency on the shim that needs rewriting; diagnose and fix before committing.

- [ ] **Step 3: Commit the migrated tests**

```bash
cd /home/raul/worktrees/cpm/feat-648-delete-claudemd-shim
git add plugins/_shared/tests/test_claudemd_package.py
git commit -m "$(cat <<'EOF'
test(_shared): carry over claudemd cases from installer shim tests (648)

Migrate unique assertions (create-when-missing, append-after-user-content,
idempotency on re-call, marker-block integrity — AUDIT_RESULT) from
installer/tests/test_claudemd.py into the _shared test suite so coverage
of plugins/_shared/claudemd/claudemd.py does not regress when the shim +
its installer-side tests are removed.

Co-Authored-By: Claude Opus 4 (1M context) <noreply@anthropic.com>
EOF
)"
```
Before committing, replace the `AUDIT_RESULT` token above with the concrete list of migrated cases from Task 2 Step 3.

---

### Task 4: Migrate `installer/wizard.py`

**Files:**
- Modify: `installer/wizard.py`

- [ ] **Step 1: Locate the existing import**

```bash
cd /home/raul/worktrees/cpm/feat-648-delete-claudemd-shim
grep -n 'installer\.claudemd\|installer claudemd' installer/wizard.py
```
Expected output: one or more lines in the form `from installer.claudemd import ...` or `import installer.claudemd as ...`.

- [ ] **Step 2: Rewrite the import**

For each matching line, change the import as follows:
- `from installer.claudemd import X, Y, Z` → `from claudemd import X, Y, Z`
- `import installer.claudemd as claudemd` → `import claudemd`
- `import installer.claudemd` → `import claudemd`

Preserve the relative position of the import (keep it grouped with other package-relative imports or with third-party imports — match the file's existing grouping style).

- [ ] **Step 3: Run the installer tests that exercise wizard.py**

```bash
cd /home/raul/worktrees/cpm/feat-648-delete-claudemd-shim
uv run pytest installer/tests/ -v -k wizard
```
Expected: every collected test passes. If a test fails with `ImportError: cannot import name ... from claudemd`, confirm the symbol actually exists in `plugins/_shared/claudemd/claudemd.py` — if not, the migration rewrite in Step 2 introduced a bad import; revert to the previous version and retry.

- [ ] **Step 4: Commit**

```bash
cd /home/raul/worktrees/cpm/feat-648-delete-claudemd-shim
git add installer/wizard.py
git commit -m "$(cat <<'EOF'
refactor(installer): import claudemd directly in wizard (648)

Drop the installer.claudemd shim indirection; import from the canonical
claudemd package shipped via claude-hook-transport.

Co-Authored-By: Claude Opus 4 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Migrate `installer/app.py`

**Files:**
- Modify: `installer/app.py`

- [ ] **Step 1: Locate the existing import**

```bash
cd /home/raul/worktrees/cpm/feat-648-delete-claudemd-shim
grep -n 'installer\.claudemd' installer/app.py
```

- [ ] **Step 2: Rewrite the import** using the same rules as Task 4 Step 2.

- [ ] **Step 3: Run the installer tests that exercise app.py**

```bash
cd /home/raul/worktrees/cpm/feat-648-delete-claudemd-shim
uv run pytest installer/tests/ -v -k app
```
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
cd /home/raul/worktrees/cpm/feat-648-delete-claudemd-shim
git add installer/app.py
git commit -m "$(cat <<'EOF'
refactor(installer): import claudemd directly in app (648)

Co-Authored-By: Claude Opus 4 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Migrate `installer/tests/test_integration_screens.py`

**Files:**
- Modify: `installer/tests/test_integration_screens.py`

- [ ] **Step 1: Locate the existing import**

```bash
cd /home/raul/worktrees/cpm/feat-648-delete-claudemd-shim
grep -n 'installer\.claudemd' installer/tests/test_integration_screens.py
```

- [ ] **Step 2: Rewrite the import** using the same rules as Task 4 Step 2.

- [ ] **Step 3: Run the affected test file**

```bash
cd /home/raul/worktrees/cpm/feat-648-delete-claudemd-shim
uv run pytest installer/tests/test_integration_screens.py -v
```
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
cd /home/raul/worktrees/cpm/feat-648-delete-claudemd-shim
git add installer/tests/test_integration_screens.py
git commit -m "$(cat <<'EOF'
refactor(installer/tests): import claudemd directly in integration screens (648)

Co-Authored-By: Claude Opus 4 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Delete the shim + its installer tests

**Files:**
- Delete: `installer/claudemd.py`
- Delete: `installer/tests/test_claudemd.py`

- [ ] **Step 1: Confirm no production importer still references the shim**

```bash
cd /home/raul/worktrees/cpm/feat-648-delete-claudemd-shim
grep -rn 'installer\.claudemd\|from installer import claudemd' --include='*.py' .
```
Expected: only matches inside `installer/tests/test_claudemd.py` (the file about to be deleted) and possibly docs/spec files. If any other `.py` file matches, fix the remaining importer before deleting the shim. Do NOT proceed until production code matches are zero.

- [ ] **Step 2: Delete the shim + its installer test file**

```bash
cd /home/raul/worktrees/cpm/feat-648-delete-claudemd-shim
rm installer/claudemd.py
rm installer/tests/test_claudemd.py
```

- [ ] **Step 3: Verify the grep acceptance condition**

```bash
cd /home/raul/worktrees/cpm/feat-648-delete-claudemd-shim
grep -rn 'installer\.claudemd\|from installer import claudemd' --include='*.py' .
```
Expected: no matches (exit code 1 from grep). If anything matches, stop and restore files until the matches are down to zero.

- [ ] **Step 4: Run the full installer test suite**

```bash
cd /home/raul/worktrees/cpm/feat-648-delete-claudemd-shim
uv run pytest installer/
```
Expected: PASS. Test count is lower than before (the deleted test file contributed some cases) but no failures.

- [ ] **Step 5: Run the `_shared` test suite**

```bash
cd /home/raul/worktrees/cpm/feat-648-delete-claudemd-shim/plugins/_shared
uv run pytest
```
Expected: PASS — including the migrated cases from Task 3.

- [ ] **Step 6: Commit the deletion**

```bash
cd /home/raul/worktrees/cpm/feat-648-delete-claudemd-shim
git add -A installer/claudemd.py installer/tests/test_claudemd.py
git commit -m "$(cat <<'EOF'
refactor(installer): delete claudemd shim + shim-specific tests (648)

All internal importers (wizard.py, app.py, test_integration_screens.py)
now import claudemd directly. Shim-specific path-resolution tests are
dropped; behavioral assertions have moved to
plugins/_shared/tests/test_claudemd_package.py.

Closes todo 648.

Co-Authored-By: Claude Opus 4 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: Final verification + close out

**Files:** none (verification only).

- [ ] **Step 1: Run lint/type on the installer package**

```bash
cd /home/raul/worktrees/cpm/feat-648-delete-claudemd-shim
uv run ruff check --fix installer/
uv run ruff format installer/
uv run basedpyright installer/
```
Expected: all three exit 0. Commit any ruff format diffs as a separate chore commit if present.

- [ ] **Step 2: Run `_shared` lint/type**

```bash
cd /home/raul/worktrees/cpm/feat-648-delete-claudemd-shim/plugins/_shared
uv run ruff check --fix .
uv run ruff format .
```
(basedpyright isn't typically configured for `_shared`; skip if the per-plugin justfile doesn't run it.)

- [ ] **Step 3: Final acceptance grep**

```bash
cd /home/raul/worktrees/cpm/feat-648-delete-claudemd-shim
grep -rn 'installer\.claudemd\|from installer import claudemd' --include='*.py' .
```
Expected: no matches.

- [ ] **Step 4: Confirm no uncommitted changes**

```bash
cd /home/raul/worktrees/cpm/feat-648-delete-claudemd-shim
git status --short
```
Expected: empty output.

- [ ] **Step 5: Stop and hand off**

Do NOT call `todo_complete` and do NOT merge to `dev`. Both are controller-owned steps that happen AFTER spec review + code review have passed. Report back with the final commit SHAs and let the controller (or user) handle archive + merge.

---

## Self-Review Notes

- Spec coverage: §4 step 1 — Tasks 4, 5, 6. §4 step 2 — Task 7. §4 step 3 — Task 7 (delete) + Task 2 (audit rationale). §4 step 4 — Tasks 2 + 3. §4 step 5 — Tasks 4–7 verification steps.
- No placeholders. `AUDIT_RESULT` in Task 3 Step 3 is an explicit instruction to substitute the concrete audit findings before committing — not a leftover TODO.
- Type consistency: no new typed APIs introduced. Import rewrites are mechanical.
- Worktree rule: every command is prefixed with the worktree path.
- Ordering rationale: audit → extend `_shared` tests (Task 3) → migrate importers (Tasks 4–6) → delete shim + installer test (Task 7). Coverage never drops at an intermediate commit.
