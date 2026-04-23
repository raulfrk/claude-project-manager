# Managed CLAUDE.md — Wiki + proj_search Knowledge-Source Rule — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new bullet to the cpm managed CLAUDE.md block directing Claude to consult `/wiki:query` (wiki-gated) and `proj_search_knowledge` (always-on) before making domain claims, with `Explore` / `general-purpose` subagents as code-level fallback.

**Architecture:** Content-only change in `plugins/_shared/claudemd/managed_section.md` + one new test method in `plugins/_shared/tests/test_claudemd_package.py` + `_shared` version bump + `uv.lock` regeneration across all plugins + proj plugin version bump. Rule is read-time guidance in the managed block — no runtime enforcement, no new tool, no new skill.

**Tech Stack:** Python 3.13, pytest, uv (lockfile management), pre-commit hooks, FastMCP (proj plugin consumes `MANAGED_SECTION` via `claudemd_refresh_managed`).

**Worktree:** `/home/raul/worktrees/cpm/feat-710-managed-claudemd-wiki-query-rules`
**Branch:** `feat/710-managed-claudemd-wiki-query-rules`
**Base:** `origin/dev` (at `852162d` as of worktree creation)
**Spec:** `docs/superpowers/specs/2026-04-23-managed-claudemd-wiki-query-rules-design.md`

---

## Context for the engineer

- `plugins/_shared/claudemd/managed_section.md` is the single source of truth for the cpm managed block in `~/.claude/CLAUDE.md`. Its content is loaded at Python import time into the `MANAGED_SECTION` constant (see `plugins/_shared/claudemd/claudemd.py:24`).
- `plugins/_shared/tests/test_claudemd_package.py` has a `TestManagedSectionContent` class (starts at line 143) with one test method per bullet in the managed block. Each method pins discriminating substrings from its bullet. The class also ends with a regression test `test_managed_section_still_has_preexisting_rules` (line 197) that asserts old rules still exist.
- The `scripts/check_shared_version.py` script runs as a pre-commit hook. It triggers when any `plugins/_shared/**.py` file is staged and fails the commit unless `plugins/_shared/pyproject.toml`'s `version` field differs between staged and HEAD. Since this plan stages a test file (`.py`) under `plugins/_shared/tests/`, the `_shared` version MUST be bumped.
- Bumping `_shared` version requires regenerating every `uv.lock` file that pins `claude-hook-transport` to the old version. Eight lockfiles exist: root `./uv.lock` + each plugin's `plugins/<name>/server/uv.lock` + `plugins/_shared/uv.lock`.
- The proj plugin version bump is required by project convention (CLAUDE.md "Key Conventions") because proj's `claudemd_refresh_managed` tool ships the new managed-block content to user environments; the version signal lets users track which proj release shipped this rule.
- A parallel branch `feat/687-691-692-700-bundled-cleanups` also bumps `_shared` (to 0.4.12) and adds a new bullet. Do NOT rebase onto or merge from that branch during this plan. Spec flags merge-order reconciliation as a separate concern handled at merge time.

---

### Task 1: Write failing test for the new bullet

**Files:**
- Modify: `plugins/_shared/tests/test_claudemd_package.py` (insert new test method inside `TestManagedSectionContent` class, before the closing of the class at or near line 195)

- [ ] **Step 1: Open the test file and locate insertion point**

Read `plugins/_shared/tests/test_claudemd_package.py`. Find the `TestManagedSectionContent` class. Find the last method inside that class — it should be `test_post_wt_create_sync_rule` (currently ends around line 195). Insert the new test method immediately after that method, still inside the `TestManagedSectionContent` class (before `test_managed_section_still_has_preexisting_rules` which is OUTSIDE the class at line 197).

- [ ] **Step 2: Add the new test method**

Insert this method verbatim:

```python
    def test_wiki_proj_search_knowledge_rule(self):
        assert "Wiki + proj_search are primary knowledge sources" in MANAGED_SECTION
        assert "/wiki:query" in MANAGED_SECTION
        assert "mcp__plugin_proj_proj__proj_search_knowledge" in MANAGED_SECTION
        assert "Explore" in MANAGED_SECTION
        assert "general-purpose" in MANAGED_SECTION
        assert "skip if wiki plugin disabled" in MANAGED_SECTION
```

Six assertions: (1) discriminating lead phrase; (2) wiki query skill reference; (3) full MCP tool name for proj_search_knowledge; (4) Explore agent name; (5) general-purpose agent name; (6) install-gating phrase.

- [ ] **Step 3: Run the new test to verify it fails**

From the worktree root:

```bash
cd /home/raul/worktrees/cpm/feat-710-managed-claudemd-wiki-query-rules
uv run --directory plugins/_shared pytest tests/test_claudemd_package.py::TestManagedSectionContent::test_wiki_proj_search_knowledge_rule -v
```

Expected: `FAILED` with `AssertionError: assert 'Wiki + proj_search are primary knowledge sources' in MANAGED_SECTION` (or whichever of the six assertions fails first — all six should fail because the bullet has not been added yet).

- [ ] **Step 4: Do NOT commit yet**

The test will be committed together with the bullet in Task 2 to keep the branch in a buildable state at every commit boundary. Continue to Task 2.

---

### Task 2: Add the bullet to managed_section.md

**Files:**
- Modify: `plugins/_shared/claudemd/managed_section.md` (insert new last bullet before the `<!-- claude-project-manager:end -->` marker on the last line)

- [ ] **Step 1: Read the current file**

```bash
cat /home/raul/worktrees/cpm/feat-710-managed-claudemd-wiki-query-rules/plugins/_shared/claudemd/managed_section.md
```

Confirm the last bullet is `**Sync worktree to remote after \`wt_create\`**` on line 18 and the file ends with `<!-- claude-project-manager:end -->` on line 19.

- [ ] **Step 2: Insert the new bullet**

Use the Edit tool. Replace the exact two-line string:

```
- **Sync worktree to remote after `wt_create`** — After a successful `mcp__plugin_worktree_worktree__wt_create` call, run `git fetch origin` and then `git reset --hard origin/<base-branch>` inside the returned `worktree_path` before any edits or agent dispatch. `wt_create` already resets to local HEAD and cleans untracked files, but does not fetch — the local base branch may lag `origin/<base>`. This ensures agents start from the latest remote state. Skip only when the worktree was created explicitly from a non-remote branch (e.g. a local-only experimental branch).
<!-- claude-project-manager:end -->
```

with:

```
- **Sync worktree to remote after `wt_create`** — After a successful `mcp__plugin_worktree_worktree__wt_create` call, run `git fetch origin` and then `git reset --hard origin/<base-branch>` inside the returned `worktree_path` before any edits or agent dispatch. `wt_create` already resets to local HEAD and cleans untracked files, but does not fetch — the local base branch may lag `origin/<base>`. This ensures agents start from the latest remote state. Skip only when the worktree was created explicitly from a non-remote branch (e.g. a local-only experimental branch).
- **Wiki + proj_search are primary knowledge sources** — When you need project or domain info, first query `/wiki:query` (skip if wiki plugin disabled), then `mcp__plugin_proj_proj__proj_search_knowledge`, then fall back to `Explore` / `general-purpose` subagents for code-level search. These stores are authoritative; training priors and guesswork are not. Use before making claims, design decisions, or asking the user for information that might already be captured.
<!-- claude-project-manager:end -->
```

Verify: file is now 20 lines, the new bullet is line 19, the end marker is line 20.

- [ ] **Step 3: Run the new test to verify it passes**

```bash
cd /home/raul/worktrees/cpm/feat-710-managed-claudemd-wiki-query-rules
uv run --directory plugins/_shared pytest tests/test_claudemd_package.py::TestManagedSectionContent::test_wiki_proj_search_knowledge_rule -v
```

Expected: `PASSED`.

- [ ] **Step 4: Run all claudemd tests to catch regressions**

```bash
uv run --directory plugins/_shared pytest tests/test_claudemd_package.py -v
```

Expected: all tests pass (including the pre-existing per-bullet tests and the ensure/remove/has tests).

- [ ] **Step 5: Do NOT commit yet**

The `_shared/*.py` staging will trigger the `check_shared_version.py` pre-commit hook. Bump the version in Task 3 before attempting a commit. Keep the changes in the working tree.

---

### Task 3: Bump `plugins/_shared` version

**Files:**
- Modify: `plugins/_shared/pyproject.toml` (change the `version` field from `0.4.10` to `0.4.11`)

- [ ] **Step 1: Confirm current version**

```bash
grep '^version' /home/raul/worktrees/cpm/feat-710-managed-claudemd-wiki-query-rules/plugins/_shared/pyproject.toml
```

Expected output: `version = "0.4.10"`.

If you see `0.4.12` (or anything other than `0.4.10`), STOP. This means either the parallel branch has been merged or someone else bumped _shared between the creation of this worktree and now. Abort the task, investigate which branches have merged, and update the target version accordingly.

- [ ] **Step 2: Apply the version bump**

Use the Edit tool. Replace:

```
version = "0.4.10"
```

with:

```
version = "0.4.11"
```

- [ ] **Step 3: Verify**

```bash
grep '^version' /home/raul/worktrees/cpm/feat-710-managed-claudemd-wiki-query-rules/plugins/_shared/pyproject.toml
```

Expected output: `version = "0.4.11"`.

- [ ] **Step 4: Do NOT commit yet**

uv.lock files still reference the old version. Regenerating them in Task 4 before the commit keeps the branch buildable at every commit boundary.

---

### Task 4: Regenerate all uv.lock files

**Files:**
- Modify: `uv.lock` (repo root)
- Modify: `plugins/_shared/uv.lock`
- Modify: `plugins/proj/server/uv.lock`
- Modify: `plugins/worktree/server/uv.lock`
- Modify: `plugins/trello/server/uv.lock`
- Modify: `plugins/jira/server/uv.lock`
- Modify: `plugins/router/server/uv.lock`
- Modify: `plugins/todoist/server/uv.lock`
- Modify: `plugins/confluence/server/uv.lock`

- [ ] **Step 1: Regenerate each lockfile in place**

Run each of the following commands in sequence from the worktree root. Each `uv lock` call regenerates the lockfile in its respective directory, picking up the new `claude-hook-transport` version `0.4.11` from `plugins/_shared/pyproject.toml`.

```bash
cd /home/raul/worktrees/cpm/feat-710-managed-claudemd-wiki-query-rules
uv lock --directory plugins/_shared
uv lock --directory plugins/proj/server
uv lock --directory plugins/worktree/server
uv lock --directory plugins/trello/server
uv lock --directory plugins/jira/server
uv lock --directory plugins/router/server
uv lock --directory plugins/todoist/server
uv lock --directory plugins/confluence/server
uv lock
```

The final `uv lock` (no `--directory` flag) regenerates the root `./uv.lock`.

- [ ] **Step 2: Verify lockfiles were updated**

```bash
cd /home/raul/worktrees/cpm/feat-710-managed-claudemd-wiki-query-rules
for f in uv.lock plugins/_shared/uv.lock plugins/proj/server/uv.lock plugins/worktree/server/uv.lock plugins/trello/server/uv.lock plugins/jira/server/uv.lock plugins/router/server/uv.lock plugins/todoist/server/uv.lock plugins/confluence/server/uv.lock; do
  echo "=== $f ==="
  grep -A 1 'name = "claude-hook-transport"' "$f" | head -2
done
```

Expected output: every lockfile shows `version = "0.4.11"` on the line immediately after `name = "claude-hook-transport"`. If any lockfile still shows `"0.4.10"`, rerun the `uv lock` command for that specific directory.

- [ ] **Step 3: Run the check_shared_version validator manually to confirm readiness**

Stage all the changes so far and dry-run the check:

```bash
cd /home/raul/worktrees/cpm/feat-710-managed-claudemd-wiki-query-rules
git add plugins/_shared/claudemd/managed_section.md \
        plugins/_shared/tests/test_claudemd_package.py \
        plugins/_shared/pyproject.toml \
        plugins/_shared/uv.lock \
        plugins/proj/server/uv.lock \
        plugins/worktree/server/uv.lock \
        plugins/trello/server/uv.lock \
        plugins/jira/server/uv.lock \
        plugins/router/server/uv.lock \
        plugins/todoist/server/uv.lock \
        plugins/confluence/server/uv.lock \
        uv.lock
python3 scripts/check_shared_version.py
echo "exit=$?"
```

Expected: `exit=0` (no output on success).

- [ ] **Step 4: Do NOT commit yet**

Proj version bump comes next (Task 5) and will be folded into the same commit.

---

### Task 5: Bump proj plugin version

**Files:**
- Modify: `plugins/proj/plugin.json`
- Modify: `.claude-plugin/marketplace.json`

- [ ] **Step 1: Confirm current proj version**

```bash
cd /home/raul/worktrees/cpm/feat-710-managed-claudemd-wiki-query-rules
grep '"version"' plugins/proj/plugin.json
python3 -c "import json; d=json.load(open('.claude-plugin/marketplace.json')); print([p['version'] for p in d['plugins'] if p['name']=='proj'][0])"
```

Expected: both print `5.1.1`. If different, STOP and investigate (another branch may have bumped).

- [ ] **Step 2: Bump `plugins/proj/plugin.json`**

Use the Edit tool. Replace `"version": "5.1.1"` with `"version": "5.1.2"` in `plugins/proj/plugin.json`. (If the exact quoted string appears more than once, scope the Edit by including surrounding context — usually the key appears once per file.)

- [ ] **Step 3: Bump `.claude-plugin/marketplace.json`**

Use the Edit tool. Find the proj plugin entry in `.claude-plugin/marketplace.json` (search for `"name": "proj"`) and change its `"version"` field from `"5.1.1"` to `"5.1.2"`. Leave all other plugins' versions unchanged.

- [ ] **Step 4: Verify both bumps**

```bash
cd /home/raul/worktrees/cpm/feat-710-managed-claudemd-wiki-query-rules
grep '"version"' plugins/proj/plugin.json
python3 -c "import json; d=json.load(open('.claude-plugin/marketplace.json')); print([p['version'] for p in d['plugins'] if p['name']=='proj'][0])"
```

Expected: both print `5.1.2`.

- [ ] **Step 5: Stage and commit everything together**

```bash
cd /home/raul/worktrees/cpm/feat-710-managed-claudemd-wiki-query-rules
git add plugins/_shared/claudemd/managed_section.md \
        plugins/_shared/tests/test_claudemd_package.py \
        plugins/_shared/pyproject.toml \
        plugins/_shared/uv.lock \
        plugins/proj/server/uv.lock \
        plugins/worktree/server/uv.lock \
        plugins/trello/server/uv.lock \
        plugins/jira/server/uv.lock \
        plugins/router/server/uv.lock \
        plugins/todoist/server/uv.lock \
        plugins/confluence/server/uv.lock \
        uv.lock \
        plugins/proj/plugin.json \
        .claude-plugin/marketplace.json

git commit -m "$(cat <<'EOF'
feat(710): managed CLAUDE.md rule — wiki + proj_search as primary knowledge sources

Adds a new bullet at the end of the cpm managed block directing Claude
to consult /wiki:query (wiki-gated) and proj_search_knowledge
(always-on) before making domain claims, design decisions, or asking
the user for info that might already be captured. Code-level search
fallback via Explore / general-purpose subagents.

Bumps plugins/_shared 0.4.10 → 0.4.11 and regenerates all 9 uv.lock
files to keep scripts/check_shared_version.py validator green. Bumps
proj plugin 5.1.1 → 5.1.2 (the MCP plugin that exposes
claudemd_refresh_managed — users pick up this rule via refresh or
fresh install).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: pre-commit hooks run, `check_shared_version.py` returns 0, commit succeeds. If the commit fails because of a hook, read the hook output carefully, fix the root cause, re-stage any files the fix touched, and create a NEW commit (do NOT use `--amend` on a commit that failed to land — the commit did not happen if the hook blocked it).

---

### Task 6: Run the full `_shared` test suite

**Files:**
- (no changes)

- [ ] **Step 1: Run the full `_shared` pytest suite**

```bash
cd /home/raul/worktrees/cpm/feat-710-managed-claudemd-wiki-query-rules
uv run --directory plugins/_shared pytest tests/ -v
```

Expected: every test passes. Pay special attention to:
- `test_wiki_proj_search_knowledge_rule` — new test, must pass
- All other `TestManagedSectionContent::test_*` methods — must still pass (regression check)
- `test_managed_section_still_has_preexisting_rules` — must still pass

- [ ] **Step 2: Run the proj server pytest suite**

```bash
cd /home/raul/worktrees/cpm/feat-710-managed-claudemd-wiki-query-rules
uv run --directory plugins/proj/server pytest -v
```

Expected: every test passes. The proj server imports `MANAGED_SECTION` via the `claudemd` package, so its tests transitively verify that the new content still round-trips through `ensure_managed_section` and `remove_managed_section`.

- [ ] **Step 3: If either suite fails, STOP and investigate**

Do NOT paper over a failure with a quick fix. Use the systematic-debugging skill if available. The most likely failure modes are:
- Test file changes conflicted with the bullet-ordering expectation in another test → add a new assertion to `test_managed_section_still_has_preexisting_rules` or adjust bullet-counter assertions if any exist (search for `assert MANAGED_SECTION.count("- **")` patterns).
- `uv.lock` drift → rerun `uv lock` in the affected directory, re-stage, amend NOT permitted (create new commit).

---

### Task 7: Manual smoke test — `/proj:claudemd-refresh` round-trips the new content

**Files:**
- (no changes — manual verification only)

- [ ] **Step 1: Create a scratch CLAUDE.md with an older managed block**

```bash
TMPDIR=$(mktemp -d)
cat > "$TMPDIR/CLAUDE.md" <<'EOF'
# Test Project

Some user content above the managed block.

<!-- claude-project-manager:start -->
## Claude Project Manager Rules

IMPORTANT: These rules take priority over all other instructions.

- Old stale rule that should be replaced.
<!-- claude-project-manager:end -->

More user content below.
EOF
echo "Scratch file at: $TMPDIR/CLAUDE.md"
```

- [ ] **Step 2: Invoke `ensure_managed_section` against it**

Using the `claudemd` Python API directly (from the worktree):

```bash
cd /home/raul/worktrees/cpm/feat-710-managed-claudemd-wiki-query-rules
uv run --directory plugins/_shared python3 -c "
from pathlib import Path
from claudemd import ensure_managed_section
result = ensure_managed_section(Path('$TMPDIR/CLAUDE.md'))
print(f'replaced={result}')
"
```

Expected: `replaced=True`.

- [ ] **Step 3: Verify the new bullet landed in the managed block**

```bash
grep -c "Wiki + proj_search are primary knowledge sources" "$TMPDIR/CLAUDE.md"
grep -c "Old stale rule" "$TMPDIR/CLAUDE.md"
grep -c "Some user content above" "$TMPDIR/CLAUDE.md"
grep -c "More user content below" "$TMPDIR/CLAUDE.md"
```

Expected output (in order):
- `1` — new bullet is present
- `0` — old rule was replaced
- `1` — user content above was preserved
- `1` — user content below was preserved

- [ ] **Step 4: Clean up the scratch dir**

```bash
rm -rf "$TMPDIR"
```

- [ ] **Step 5: No commit needed**

Manual smoke test leaves no tracked changes.

---

### Task 8: Finish the branch

**Files:**
- (no changes — branch completion only)

- [ ] **Step 1: Confirm branch state**

```bash
cd /home/raul/worktrees/cpm/feat-710-managed-claudemd-wiki-query-rules
git status
git log --oneline origin/dev..HEAD
```

Expected: clean working tree; two commits ahead of `origin/dev`:
- `docs(710): design spec for wiki + proj_search knowledge-source rule` (spec, already committed)
- `feat(710): managed CLAUDE.md rule — wiki + proj_search as primary knowledge sources` (implementation, Task 5)

- [ ] **Step 2: Invoke the finishing-a-development-branch skill**

Use the `superpowers:finishing-a-development-branch` skill to pick the integration path (FF-merge to dev + push + watch CI per the saved convention for this repo, or PR flow if that skill directs otherwise).

Do NOT `git push` or `git merge` directly from this plan — let the finishing skill drive the decision.

- [ ] **Step 3: After merge completes, mark todo 710 done**

From any context with the proj MCP tools loaded:

```
mcp__plugin_proj_proj__todo_complete(todo_id="710", project_name="claude-project-manager")
```

The completion fires the Todoist hook automatically. The finishing skill handles worktree cleanup separately.

---

## Rollback

If any task fails in a way that cannot be cleanly fixed:

```bash
cd /home/raul/worktrees/cpm/feat-710-managed-claudemd-wiki-query-rules
git reset --hard origin/dev  # discards all local commits on this branch
```

The worktree branch is cheap — the only committed work before the implementation commit is the design spec, which can be re-written from the spec file (`docs/superpowers/specs/2026-04-23-managed-claudemd-wiki-query-rules-design.md`) on a fresh attempt.

---

## Self-review

Spec coverage:
- Bullet placement + text → Task 2 ✓
- Test pin on discriminating substring + tool names → Task 1 ✓
- `_shared` version bump 0.4.10 → 0.4.11 → Task 3 ✓
- `uv.lock` regen across all 9 lockfiles → Task 4 ✓
- proj version bump 5.1.1 → 5.1.2 (plugin.json + marketplace.json) → Task 5 ✓
- `scripts/check_shared_version.py` passes → Task 4 step 3 + Task 5 step 5 (commit hook) ✓
- `_shared` test suite passes → Task 6 step 1 ✓
- `/proj:claudemd-refresh` smoke test → Task 7 ✓

Placeholder scan: no "TBD", no "TODO", no "handle edge cases" hand-waving, no "similar to Task N" shorthand.

Type consistency: the only type-like identifier used is the `MANAGED_SECTION` import in the test file — spelled identically in Task 1 and the existing codebase; no cross-task name drift.
