# Todo 635: Local Test Env via Root `justfile` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a root `justfile` that installs every plugin + installer via `uv sync` and runs every plugin test suite, so a fresh clone can reach CI-equivalent state with `just sync && just test`.

**Architecture:** New root-level `/justfile` with three recipes (`sync`, `test`, `ci`) that iterate an explicit ordered list of plugin directories. `_shared` installs first because other plugins depend on it as a path dep. Per-plugin `justfile`s remain authoritative for single-plugin workflows; the root justfile orchestrates across all of them.

**Tech Stack:** just, uv, bash, pytest.

**Spec:** `docs/superpowers/specs/2026-04-16-tech-debt-635-648-651-design.md` §2.

**Prerequisite worktree:** `/home/raul/worktrees/cpm/feat-635-local-test-env` on branch `feat/635-local-test-env`. All file edits + git operations MUST happen inside this directory.

---

## File Structure

- **Create:** `/justfile` (repo root)
- **Modify:** `/README.md` (Local dev section)

No automated tests accompany this task (it is developer infrastructure). Success criteria are verified manually by executing `just sync` and `just test` and confirming no `respx` / `textual` / `hook_dispatch` import errors appear.

---

### Task 1: Create worktree

**Files:** none yet (worktree setup).

- [ ] **Step 1: Create worktree via `wt_create` MCP tool**

Call `mcp__plugin_worktree_worktree__wt_create` with:
```json
{
  "repo_label": "cpm",
  "branch": "feat/635-local-test-env",
  "base_branch": "dev"
}
```
Expected: worktree created at `/home/raul/worktrees/cpm/feat-635-local-test-env`.

- [ ] **Step 2: Confirm worktree path**

Run in the main repo:
```bash
cd /home/raul/worktrees/cpm/feat-635-local-test-env && git branch --show-current
```
Expected: `feat/635-local-test-env`.

---

### Task 2: Write the root `justfile`

**Files:**
- Create: `/home/raul/worktrees/cpm/feat-635-local-test-env/justfile`

- [ ] **Step 1: Create `/justfile` with the full recipe set**

Write this exact content to `/home/raul/worktrees/cpm/feat-635-local-test-env/justfile`:

```makefile
# Root-level justfile — orchestrates cross-plugin developer workflows.
#
# Per-plugin justfiles (plugins/<name>/server/justfile) remain the authoritative
# single-plugin interface. This file sets up ALL plugin dirs so a fresh clone
# can reach CI parity with `just sync && just test`.
#
# Ordering:
#   1. plugins/_shared first (other plugins + installer depend on it as a uv
#      path dep; its wheel must be available before dependents resolve).
#   2. installer at repo root second (cpm-install pyproject lives here).
#   3. Remaining plugin servers in declaration order.

_PLUGIN_DIRS := "plugins/router/server plugins/proj/server plugins/worktree/server plugins/todoist/server plugins/trello/server plugins/jira/server"

default: help

help:
    @just --list

# Install dev deps in every plugin + installer. Runs `uv sync --all-groups`
# in each directory. Does NOT fail-fast: aggregates failures and exits
# non-zero at the end if any dir failed.
sync:
    #!/usr/bin/env bash
    set -u
    failed=0
    echo "=== uv sync --all-groups (plugins/_shared) ==="
    (cd plugins/_shared && uv sync --all-groups) || { echo ">>> FAILED: plugins/_shared"; failed=$((failed+1)); }
    echo ""
    echo "=== uv sync --all-groups (installer @ repo root) ==="
    uv sync --all-groups || { echo ">>> FAILED: installer"; failed=$((failed+1)); }
    for d in {{_PLUGIN_DIRS}}; do
      echo ""
      echo "=== uv sync --all-groups ($d) ==="
      (cd "$d" && uv sync --all-groups) || { echo ">>> FAILED: $d"; failed=$((failed+1)); }
    done
    if [[ $failed -gt 0 ]]; then
      echo ""
      echo "SYNC FAILED in $failed dir(s)"
      exit 1
    fi

# Run pytest in every plugin + installer. Does NOT fail-fast.
test:
    #!/usr/bin/env bash
    set -u
    failed=0
    echo "=== pytest (installer @ repo root) ==="
    uv run pytest || { echo ">>> FAILED: installer"; failed=$((failed+1)); }
    echo ""
    echo "=== pytest (plugins/_shared) ==="
    (cd plugins/_shared && uv run pytest) || { echo ">>> FAILED: plugins/_shared"; failed=$((failed+1)); }
    for d in {{_PLUGIN_DIRS}}; do
      echo ""
      echo "=== pytest ($d) ==="
      (cd "$d" && uv run pytest) || { echo ">>> FAILED: $d"; failed=$((failed+1)); }
    done
    if [[ $failed -gt 0 ]]; then
      echo ""
      echo "TEST FAILED in $failed dir(s)"
      exit 1
    fi

# Full local CI mirror: sync then test.
ci: sync test
```

- [ ] **Step 2: Verify `just --list` discovers the recipes**

Run in the worktree:
```bash
cd /home/raul/worktrees/cpm/feat-635-local-test-env && just --list
```
Expected output includes:
```
Available recipes:
    ci
    default
    help
    sync
    test
```

- [ ] **Step 3: Commit the justfile**

Run in the worktree:
```bash
cd /home/raul/worktrees/cpm/feat-635-local-test-env
git add justfile
git commit -m "$(cat <<'EOF'
feat(635): add root justfile for cross-plugin dev setup

Orchestrates uv sync + pytest across installer + all plugin servers so a
fresh clone reaches CI parity via `just sync && just test`. _shared
installs first to satisfy path-dep ordering. Does not fail-fast; exits
non-zero only after iterating every dir.

Co-Authored-By: Claude Opus 4 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Verify `just sync` succeeds end-to-end

**Files:** none (verification only).

- [ ] **Step 1: Run `just sync` from the worktree**

```bash
cd /home/raul/worktrees/cpm/feat-635-local-test-env && just sync 2>&1 | tee /tmp/just-sync-635.log
```
Expected: exit code 0. Log contains `=== uv sync --all-groups (...)` banner for each of the 8 directories. No `SYNC FAILED` at the end.

- [ ] **Step 2: Inspect the log for per-directory success**

```bash
grep -c "^=== uv sync" /tmp/just-sync-635.log
```
Expected: `8` (one banner per directory).

```bash
grep ">>> FAILED" /tmp/just-sync-635.log
```
Expected: no output.

If any directory failed, diagnose the `uv sync` output for that dir and fix the underlying packaging issue before continuing. Do NOT alter the justfile to mask failures.

---

### Task 4: Verify `just test` no longer hits missing-dep errors

**Files:** none (verification only).

- [ ] **Step 1: Run `just test` from the worktree**

```bash
cd /home/raul/worktrees/cpm/feat-635-local-test-env && just test 2>&1 | tee /tmp/just-test-635.log
```
Expected: exit code may be 0 or non-zero (some unrelated tests may fail — not this change's problem). Banner for each directory appears.

- [ ] **Step 2: Assert no `respx`, `textual`, `hook_dispatch` missing-module errors**

```bash
grep -E "ModuleNotFoundError:.* (respx|textual|hook_dispatch)" /tmp/just-test-635.log
```
Expected: no output. If any of the three modules still shows as missing, the affected plugin's `pyproject.toml` dev deps need an entry; add it, re-run `just sync`, retry.

- [ ] **Step 3: Count banner lines to confirm all 8 dirs ran**

```bash
grep -c "^=== pytest" /tmp/just-test-635.log
```
Expected: `8`.

---

### Task 5: Update the README Local dev section

**Files:**
- Modify: `/home/raul/worktrees/cpm/feat-635-local-test-env/README.md`

- [ ] **Step 1: Read README to locate the existing dev section**

Read the current `README.md` and find the nearest section to "Local dev", "Development", or "Contributing". If none exists, a new `## Local development` section is added near the end, before any "License" or footer section.

- [ ] **Step 2: Patch the README**

Insert (or replace the existing equivalent block with) this content verbatim under a `## Local development` heading:

```markdown
## Local development

Install `just` (`brew install just` on macOS, `cargo install just` elsewhere)
and `uv` (https://docs.astral.sh/uv/). Then, from the repo root:

```bash
just sync   # uv sync --all-groups in installer + every plugin server
just test   # pytest in the same set; does not fail-fast
just ci     # sync + test
```

Per-plugin justfiles remain under `plugins/<name>/server/justfile` for
single-plugin workflows (`just check`, `just test-cov`, etc.).
```

- [ ] **Step 3: Verify the section renders**

```bash
grep -A 4 "## Local development" /home/raul/worktrees/cpm/feat-635-local-test-env/README.md
```
Expected: the inserted block appears.

- [ ] **Step 4: Commit the README patch**

```bash
cd /home/raul/worktrees/cpm/feat-635-local-test-env
git add README.md
git commit -m "$(cat <<'EOF'
docs(635): document just sync / just test in README

Co-Authored-By: Claude Opus 4 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Final acceptance check

**Files:** none (verification only).

- [ ] **Step 1: Fresh-clone simulation**

Run in the worktree:
```bash
cd /home/raul/worktrees/cpm/feat-635-local-test-env
# Remove every .venv (root + plugins) to simulate a fresh clone.
rm -rf .venv 2>/dev/null || true
find plugins -type d -name .venv -prune -exec rm -rf {} + 2>/dev/null || true
just sync && just test 2>&1 | tee /tmp/just-ci-635.log
```
Expected: `just sync` exits 0. `just test` produces 8 `=== pytest` banners (1 installer + 1 `_shared` + 6 plugin servers); no `respx` / `textual` / `hook_dispatch` missing-module errors.

- [ ] **Step 2: Confirm no uncommitted changes**

```bash
cd /home/raul/worktrees/cpm/feat-635-local-test-env && git status --short
```
Expected: empty output (two commits done, nothing untracked).

- [ ] **Step 3: Mark todo 635 complete via the MCP tool**

Call `mcp__plugin_proj_proj__todo_complete`:
```json
{"project": "claude-project-manager", "todo_id": "635"}
```

- [ ] **Step 4: Stop**

Hand off to the reviewer / merge flow. Do NOT merge to `dev` automatically; that is a user-gated step.

---

## Self-Review Notes

- Spec coverage: §2 "Design" — covered by Task 2. §2 "Success criteria" — Task 3 + Task 4 + Task 6. §2 "Files" — Task 2 (justfile) + Task 5 (README).
- No placeholders. Every code block is concrete.
- Type consistency: N/A (no typed APIs introduced).
- Worktree rule: every tasked command is prefixed with `cd /home/raul/worktrees/cpm/feat-635-local-test-env`.
