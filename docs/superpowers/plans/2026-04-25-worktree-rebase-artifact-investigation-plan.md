# Worktree Rebase Artifact Investigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Note**: this is an INVESTIGATION plan with conditional phases (later phases depend on earlier phase outcomes). Each phase's task is concrete; the branching at Phase 4/5 is documented inline because the fix shape depends on what Phase 4 finds.

**Goal:** Reliably reproduce the worktree-rebase-artifact bug, identify its root cause via bisect-style investigation, ship a targeted fix with regression test. In parallel: standardize the existing `git restore .` workaround in the recipe + skill.

**Architecture:** 5-phase bisect (bare git → +pre-commit → +tests → instrument → fix) using deterministic repro scripts in `scripts/repro/`. Each phase is a separate Bash script; later phases extend the earlier fixture. Phase 4 + Phase 5 are conditional on Phase 2/3 outcomes. Workaround codification (Task 8) ships independently.

**Tech Stack:** Bash repro scripts (POSIX-compatible), git worktree CLI, pytest (Phase 3+), pre-commit, optionally `strace` (Phase 4).

**Spec:** `docs/superpowers/specs/2026-04-25-worktree-rebase-artifact-investigation-design.md`

---

## File Structure

| File | Responsibility | Created/modified by task |
|---|---|---|
| `scripts/repro/735-bare-git-repro.sh` | Phase 0+1: deterministic 3-worktree repro w/o pre-commit/tests | Task 1 |
| `scripts/repro/735-precommit-bisect.sh` | Phase 2: per-hook bisection on cpm clone | Task 3 |
| `scripts/repro/735-tests-bisect.sh` | Phase 3: + pytest invocations | Task 5 |
| `tmp/735-investigation/` | Trace logs, run output (gitignored, NOT committed) | Tasks 4-7 (working state) |
| `.gitignore` | Add `tmp/735-investigation/` if not already covered | Task 1 |
| TBD by Phase 4 outcome | Fix target (e.g. `scripts/update_readme.py`, snapshot tests, or other) | Task 7 |
| `~/.claude/wiki/pages/concepts/parallel-impl-orchestration.md` | "Known speed bumps" section update | Task 8 |
| `~/.claude/wiki/pages/pitfalls/worktree-rebase-artifact.md` | Status section update post-fix | Task 7 (post-fix) |
| `plugins/proj/skills/parallel-batch-execute/SKILL.md` | Phase 5 step 1 prose: add `git status --porcelain` check | Task 8 |

The Phase 4/5 fix-target line is intentionally TBD — what file gets patched depends on which layer Phase 2 or Phase 3 fingers as the culprit. Three candidate fix paths are documented in spec Phase 5.

---

## Pre-Task Setup

Before starting any task, create an isolated worktree per project rules.

- [ ] **Step 1: Create worktree from dev**

```
mcp__plugin_worktree_worktree__wt_create(
  repo_label="cpm",
  branch="feat/735-worktree-rebase-investigation",
  new_branch=true
)
```

Expected: returns `worktree_path` like `/home/raul/worktrees/cpm/feat-735-worktree-rebase-investigation`.

- [ ] **Step 2: Sync worktree to remote per managed rule 13**

```bash
cd <worktree_path>
git fetch origin
local_ahead=$(git rev-list origin/dev..dev)
if [ -z "$local_ahead" ]; then
  git reset --hard origin/dev
else
  git reset --hard dev
fi
git status
```

Expected: clean working tree.

- [ ] **Step 3: Sync uv groups for proj server (per cpm convention — fresh worktrees lack dev deps)**

```bash
cd <worktree_path>/plugins/proj/server
uv sync --all-groups
```

---

## Task 1: Build Phase 0+1 repro script + execute Phase 1 (bare git)

**Files:**
- Create: `scripts/repro/735-bare-git-repro.sh`
- Modify: `.gitignore` (add `tmp/735-investigation/`)

- [ ] **Step 1: Add `tmp/735-investigation/` to `.gitignore`**

```bash
cd <worktree_path>
echo "tmp/735-investigation/" >> .gitignore
```

Verify: `grep '735-investigation' .gitignore` → 1 match.

- [ ] **Step 2: Create the repro script**

Write to `scripts/repro/735-bare-git-repro.sh` and make it executable:

```bash
#!/usr/bin/env bash
# 735-bare-git-repro.sh — deterministic 3-worktree repro for sibling-file leak.
# Phase 0+1 of todo 735 investigation. No pre-commit, no tests.
# Idempotent: nukes its tmpdir each run.
#
# Usage: scripts/repro/735-bare-git-repro.sh
# Exit: 0 = no artifact detected (Phase 1 PASS); 1 = artifact reproduced.

set -euo pipefail

TMPDIR_BASE="${TMPDIR:-/tmp}"
WORK="$TMPDIR_BASE/735-bare-git-repro-$$"
SCRATCH="$WORK/scratch"
WORKTREES_DIR="$WORK/wt"

cleanup() { rm -rf "$WORK" 2>/dev/null || true; }
trap cleanup EXIT

mkdir -p "$SCRATCH" "$WORKTREES_DIR"
cd "$SCRATCH"

# Init scratch repo on `dev` branch
git -c init.defaultBranch=dev init -q
git config user.email "test@example.com"
git config user.name "735 repro"

for f in a b c; do
    echo "$f base content" > "$f.txt"
done
git add a.txt b.txt c.txt
git commit -m "init" -q

# Create 3 worktrees off dev
for branch in feat-A feat-B feat-C; do
    git worktree add -b "$branch" "$WORKTREES_DIR/$branch" dev -q
done

# Each worktree appends to its OWN file (disjoint changes)
declare -A BRANCH_FILE=( [feat-A]=a [feat-B]=b [feat-C]=c )
for branch in feat-A feat-B feat-C; do
    f="${BRANCH_FILE[$branch]}"
    cd "$WORKTREES_DIR/$branch"
    echo "modified by $branch" >> "$f.txt"
    git commit -am "$branch: modify $f" -q --no-verify
done

# Sequential rebase + FF-merge; check for sibling-file artifact between rebases
fail=0
for branch in feat-A feat-B feat-C; do
    cd "$WORKTREES_DIR/$branch"

    # Files this branch is supposed to own (vs current dev tip)
    own_files=$(git diff --name-only "dev..$branch" | sort -u)
    # Files showing as unstaged in working tree
    unstaged=$(git diff --name-only | sort -u)

    echo "=== Pre-rebase: $branch ==="
    echo "own_files: $own_files"
    echo "unstaged:  $unstaged"

    # Sibling-leak detection: any unstaged file NOT in own_files
    for u in $unstaged; do
        if ! echo "$own_files" | grep -qx "$u"; then
            echo "ARTIFACT: $branch has unstaged sibling file: $u"
            fail=1
        fi
    done

    git rebase dev -q || { echo "REBASE FAILED for $branch"; fail=1; break; }
    cd "$SCRATCH"
    git merge --ff-only "$branch" -q
done

cd "$SCRATCH"
echo "=== Final dev log ==="
git log --oneline | head -5

if [ "$fail" -eq 0 ]; then
    echo "PASS: no sibling-file artifact in Phase 1 (bare git)"
    exit 0
else
    echo "FAIL: sibling-file artifact detected in Phase 1"
    exit 1
fi
```

- [ ] **Step 3: Make executable + run dry-run**

```bash
chmod +x scripts/repro/735-bare-git-repro.sh
scripts/repro/735-bare-git-repro.sh 2>&1 | tail -20
echo "Exit: $?"
```

Expected: script runs end-to-end without errors; outputs `PASS` and exit 0 (most likely; bare git alone shouldn't reproduce the artifact). If it prints `FAIL` and exits 1 → **escalate to user immediately**: the bug reproduces with bare git alone, which means git internals are responsible. Pause investigation; user decides whether to file upstream git bug or continue.

- [ ] **Step 4: Capture run output to NOTES.md**

```
mcp__plugin_proj_proj__notes_append(
  op="experiment",
  heading="735 Phase 1 (bare git) result",
  text="<paste the PASS/FAIL line + the per-branch own_files/unstaged debug lines>"
)
```

- [ ] **Step 5: Commit script + .gitignore**

```bash
git add scripts/repro/735-bare-git-repro.sh .gitignore
git commit -m "feat(scripts/735): bare-git repro + Phase 1 result"
```

- [ ] **Step 6: Decision gate**

If Phase 1 PASS → continue to Task 2.
If Phase 1 FAIL → **stop, escalate via AskUserQuestion**, do NOT proceed to Phases 2-3.

---

## Task 2: Phase 2 audit — read `scripts/update_readme.py` for path-resolution bugs

**Files**: read-only (no commit).

- [ ] **Step 1: Read `scripts/update_readme.py` head and identify path-resolution lines**

```bash
head -30 scripts/update_readme.py
```

Look for:
- `Path(__file__).resolve().parent.parent` walks (line ~12) — RESOLVES the script's own filesystem location. In a worktree, this gives the worktree's root; SHOULD be safe.
- `os.environ["HOME"]`-derived paths
- `git rev-parse` invocations (good pattern — uses cwd)
- Hardcoded paths

- [ ] **Step 2: Audit any subprocess invocations**

```bash
grep -nE 'subprocess|os\.system|os\.environ|HOME|cwd' scripts/update_readme.py
```

Note any path-resolution that could resolve to wrong worktree.

- [ ] **Step 3: Read other pre-commit hook scripts for similar patterns**

```bash
grep -nE 'Path\(__file__\)|REPO_ROOT|os\.environ\["HOME"\]' scripts/*.py
```

- [ ] **Step 4: Note findings**

Record findings in NOTES.md:

```
mcp__plugin_proj_proj__notes_append(
  op="note",
  heading="735 Phase 2 audit — pre-commit script path resolution",
  text="update_readme.py: REPO_ROOT = Path(__file__).resolve().parent.parent at line ~12. <Add observations about whether this is safe or suspicious. Note: in a worktree, __file__ resolves to the worktree's copy of the file → REPO_ROOT correctly = worktree root. Should be safe.>"
)
```

If the audit finds a clear bug pattern → flag it for Task 7 (Phase 5 fix). Continue to Task 3 regardless.

---

## Task 3: Phase 2 — Pre-commit bisection

**Files:**
- Create: `scripts/repro/735-precommit-bisect.sh`

This script extends the bare-git repro by using a fresh cpm clone in tmpdir + enabling pre-commit hooks one at a time.

- [ ] **Step 1: Create the bisection script**

Write `scripts/repro/735-precommit-bisect.sh`:

```bash
#!/usr/bin/env bash
# 735-precommit-bisect.sh — Phase 2: per-hook bisection.
# Clones cpm to tmpdir, creates 3 worktrees with disjoint Python edits,
# runs pre-commit with each hook enabled in turn. Detects sibling-file artifact.
#
# Usage: scripts/repro/735-precommit-bisect.sh
# Pre-req: cpm repo has CWD = repo root when invoked.
#
# Exit: 0 = no artifact in any hook config; 1 = artifact reproduced; prints which hook.

set -euo pipefail

CPM_SOURCE="$(git rev-parse --show-toplevel)"
TMPDIR_BASE="${TMPDIR:-/tmp}"
WORK="$TMPDIR_BASE/735-precommit-bisect-$$"
CLONE="$WORK/cpm"
WORKTREES_DIR="$WORK/wt"

cleanup() { rm -rf "$WORK" 2>/dev/null || true; }
trap cleanup EXIT

mkdir -p "$WORK"
git clone --no-hardlinks --shared "$CPM_SOURCE" "$CLONE" -q
cd "$CLONE"
git checkout dev -q 2>/dev/null || git checkout -b dev origin/dev -q
git config user.email "test@example.com"
git config user.name "735 repro"

# Disjoint files for 3 worktrees (each touches a different plugin)
declare -A BRANCH_FILE=(
  [feat-A]="plugins/proj/server/server/cli.py"
  [feat-B]="plugins/wiki/server/server/main.py"
  [feat-C]="plugins/router/server/server/main.py"
)

mkdir -p "$WORKTREES_DIR"
for branch in feat-A feat-B feat-C; do
    git worktree add -b "$branch" "$WORKTREES_DIR/$branch" dev -q
done

# Hook bisection: each iteration enables ONE hook (skip-others via SKIP env).
HOOKS=("ruff" "ruff-format" "basedpyright" "update-readme" "check-shared-version")
ALL_HOOKS=$(IFS=,; echo "${HOOKS[*]}")

fail_hook=""
for hook in "${HOOKS[@]}"; do
    # Reset: nuke + recreate the worktrees for clean state per hook
    for branch in feat-A feat-B feat-C; do
        git worktree remove -f "$WORKTREES_DIR/$branch" 2>/dev/null || true
        git branch -D "$branch" 2>/dev/null || true
        git worktree add -b "$branch" "$WORKTREES_DIR/$branch" dev -q
    done

    # SKIP all hooks except the one being tested
    SKIP_LIST=$(echo "$ALL_HOOKS" | sed "s/$hook,//;s/,$hook//")

    echo "=== Testing hook: $hook (SKIP=$SKIP_LIST) ==="

    # Each worktree appends to its file + commits with this hook active
    for branch in feat-A feat-B feat-C; do
        f="${BRANCH_FILE[$branch]}"
        cd "$WORKTREES_DIR/$branch"
        # Trivial syntactic-no-op append (a comment)
        echo "# 735-repro-$branch" >> "$f"
        # Force update-readme to trigger by also touching marketplace.json once on feat-A
        if [ "$branch" = "feat-A" ] && [ "$hook" = "update-readme" ]; then
            touch ".claude-plugin/marketplace.json"
        fi
        SKIP="$SKIP_LIST" git commit -am "$branch: $hook test" -q || {
            # If pre-commit fails, that's not the artifact bug. Try again w/ --no-verify.
            git commit -am "$branch: $hook test (skip-on-fail)" -q --no-verify
        }
    done

    # Sequential rebase + FF-merge; detect artifact
    cd "$CLONE"
    artifact_found=0
    for branch in feat-A feat-B feat-C; do
        cd "$WORKTREES_DIR/$branch"
        own_files=$(git diff --name-only "dev..$branch" | sort -u)
        unstaged=$(git diff --name-only | sort -u)
        for u in $unstaged; do
            if ! echo "$own_files" | grep -qx "$u"; then
                echo "ARTIFACT (hook=$hook, worktree=$branch): unstaged sibling file $u"
                artifact_found=1
            fi
        done
        git rebase dev -q || { echo "REBASE FAILED for $branch (hook=$hook)"; }
        cd "$CLONE"
        git merge --ff-only "$branch" -q || true
    done

    if [ "$artifact_found" -eq 1 ]; then
        fail_hook="$hook"
        break
    fi

    # Reset CLONE's dev to start point for next hook test
    git reset --hard origin/dev -q 2>/dev/null || true
done

if [ -n "$fail_hook" ]; then
    echo "FAIL: hook '$fail_hook' produces sibling-file artifact"
    exit 1
else
    echo "PASS: no hook produces artifact (Phase 2 ruled out)"
    exit 0
fi
```

- [ ] **Step 2: Make executable + run**

```bash
cd <worktree_path>
chmod +x scripts/repro/735-precommit-bisect.sh
scripts/repro/735-precommit-bisect.sh 2>&1 | tee tmp/735-investigation/phase2.log | tail -30
```

(Create `tmp/735-investigation/` first if needed: `mkdir -p tmp/735-investigation`. Path is gitignored.)

- [ ] **Step 3: Capture result**

If a hook is identified → record it. If not → record PASS.

```
mcp__plugin_proj_proj__notes_append(
  op="experiment",
  heading="735 Phase 2 (pre-commit bisection) result",
  text="<paste FAIL hook=X line OR PASS line, plus any artifact details from the log>"
)
```

- [ ] **Step 4: Commit script regardless of outcome**

```bash
git add scripts/repro/735-precommit-bisect.sh
git commit -m "feat(scripts/735): pre-commit bisection script + Phase 2 result"
```

- [ ] **Step 5: Decision gate**

If FAIL hook=X → skip Tasks 4-5, go to Task 6 (instrument hook X).
If PASS → continue to Task 4.

---

## Task 4: Phase 3 audit — read snapshot test fixtures

**Files**: read-only.

- [ ] **Step 1: Find snapshot test files**

```bash
cd <worktree_path>
find installer/tests/e2e -name 'test_snapshot*.py' -o -name 'conftest.py' 2>/dev/null
```

- [ ] **Step 2: Audit each for absolute paths**

For each found file:

```bash
grep -nE 'Path\("/|os\.environ\["HOME"\]|/home/|/tmp/[^"]' <file>
```

Look for paths that could write outside the worktree. Note: `tmp_path` (pytest fixture) IS safe; paths like `/home/raul/...` or hardcoded absolute paths are NOT.

- [ ] **Step 3: Note findings**

```
mcp__plugin_proj_proj__notes_append(
  op="note",
  heading="735 Phase 3 audit — snapshot test path resolution",
  text="<list audited files + any suspicious absolute-path patterns found>"
)
```

If audit finds a clear absolute-path write → flag it for Task 7 (Phase 5 fix). Continue to Task 5 regardless.

---

## Task 5: Phase 3 — Tests bisection

**Files:**
- Create: `scripts/repro/735-tests-bisect.sh`

- [ ] **Step 1: Create the bisection script**

Write `scripts/repro/735-tests-bisect.sh`. This extends the precommit-bisect script by also running pytest in each worktree between commit + rebase.

```bash
#!/usr/bin/env bash
# 735-tests-bisect.sh — Phase 3: tests bisection on top of full pre-commit.
# Same fixture as precommit-bisect; adds pytest run per worktree.
# Bisects test directory by running with progressively wider --collect-only patterns.

set -euo pipefail

CPM_SOURCE="$(git rev-parse --show-toplevel)"
TMPDIR_BASE="${TMPDIR:-/tmp}"
WORK="$TMPDIR_BASE/735-tests-bisect-$$"
CLONE="$WORK/cpm"
WORKTREES_DIR="$WORK/wt"

cleanup() { rm -rf "$WORK" 2>/dev/null || true; }
trap cleanup EXIT

mkdir -p "$WORK"
git clone --no-hardlinks --shared "$CPM_SOURCE" "$CLONE" -q
cd "$CLONE"
git checkout dev -q 2>/dev/null || git checkout -b dev origin/dev -q
git config user.email "test@example.com"
git config user.name "735 repro"

declare -A BRANCH_FILE=(
  [feat-A]="plugins/proj/server/server/cli.py"
  [feat-B]="plugins/wiki/server/server/main.py"
  [feat-C]="plugins/router/server/server/main.py"
)
declare -A BRANCH_TESTDIR=(
  [feat-A]="plugins/proj/server"
  [feat-B]="plugins/wiki/server"
  [feat-C]="plugins/router/server"
)

mkdir -p "$WORKTREES_DIR"
for branch in feat-A feat-B feat-C; do
    git worktree add -b "$branch" "$WORKTREES_DIR/$branch" dev -q
done

# Each worktree: edit + commit + run pytest + rebase + FF-merge; check artifact
fail=0
for branch in feat-A feat-B feat-C; do
    f="${BRANCH_FILE[$branch]}"
    testdir="${BRANCH_TESTDIR[$branch]}"

    cd "$WORKTREES_DIR/$branch"
    echo "# 735-test-$branch" >> "$f"
    git commit -am "$branch: test bisect" -q

    # Run pytest in this worktree's plugin
    cd "$WORKTREES_DIR/$branch/$testdir"
    uv sync --all-groups -q 2>&1 | tail -2 || true
    uv run pytest --no-cov -x 2>&1 | tail -5 || true

    # Check for cross-worktree leakage NOW (before rebase, after pytest)
    cd "$WORKTREES_DIR/$branch"
    own_files=$(git diff --name-only "dev..$branch" | sort -u)
    unstaged=$(git diff --name-only | sort -u)
    for u in $unstaged; do
        if ! echo "$own_files" | grep -qx "$u"; then
            echo "ARTIFACT (post-pytest, worktree=$branch): unstaged sibling file $u"
            fail=1
        fi
    done

    git rebase dev -q || { echo "REBASE FAILED for $branch"; fail=1; }
    cd "$CLONE"
    git merge --ff-only "$branch" -q || true
done

if [ "$fail" -eq 1 ]; then
    echo "FAIL: pytest run produced sibling-file artifact"
    exit 1
else
    echo "PASS: pytest run did not produce artifact (Phase 3 ruled out)"
    exit 0
fi
```

- [ ] **Step 2: Run + capture**

```bash
cd <worktree_path>
chmod +x scripts/repro/735-tests-bisect.sh
mkdir -p tmp/735-investigation
scripts/repro/735-tests-bisect.sh 2>&1 | tee tmp/735-investigation/phase3.log | tail -30
```

- [ ] **Step 3: Capture result**

```
mcp__plugin_proj_proj__notes_append(
  op="experiment",
  heading="735 Phase 3 (tests bisection) result",
  text="<paste FAIL/PASS line + worktree info from log>"
)
```

- [ ] **Step 4: Commit script**

```bash
git add scripts/repro/735-tests-bisect.sh
git commit -m "feat(scripts/735): tests bisection script + Phase 3 result"
```

- [ ] **Step 5: Decision gate**

If FAIL → narrow to which test file by adding `-k` filters (out of scope for v1; document the broad fail).
If PASS → time-box hit; jump to Task 8 (workaround codification only) + write a "Could not reproduce" decision-log entry.

---

## Task 6: Phase 4 — Instrument the culprit

**Conditional**: only run if Task 3 OR Task 5 reproduced.

The instrumentation approach branches by which layer reproduced.

- [ ] **Branch A (Task 3 reproduced — pre-commit hook)**: 

Wrap the offending hook's entry with strace OR a Python wrapper.

For `update-readme` (the most likely candidate per the spec):

```bash
# strace approach (Linux)
cd <worktree_path>
mkdir -p tmp/735-investigation
# Modify .pre-commit-config.yaml temporarily to wrap the entry:
# entry: bash -c 'strace -f -e trace=openat -o /tmp/735-trace-$$ python scripts/update_readme.py'
# Run the precommit-bisect script with this modified config.
# Inspect /tmp/735-trace-* for openat() calls writing outside the worktree.
```

OR (simpler, no strace):

```python
# Wrap the hook script with a Python tracer:
# Replace `entry: python scripts/update_readme.py` with
# `entry: python scripts/735_trace_wrapper.py update_readme`
# 735_trace_wrapper.py monkey-patches builtin open() to log all 'w'-mode opens.
```

The wrapper script content:

```python
# scripts/735_trace_wrapper.py — temporary instrumentation for 735 investigation
import builtins
import os
import sys

LOG = open(os.path.expanduser(f"~/735-trace-{os.getpid()}.log"), "w")
original_open = builtins.open

def traced_open(*args, **kwargs):
    mode = kwargs.get("mode") or (args[1] if len(args) > 1 else "r")
    if "w" in str(mode) or "a" in str(mode):
        LOG.write(f"{os.getcwd()} :: {args[0]} :: mode={mode}\n")
        LOG.flush()
    return original_open(*args, **kwargs)

builtins.open = traced_open

# Then exec the real script
target = sys.argv[1]
script_path = f"scripts/{target}.py"
with original_open(script_path) as f:
    exec(f.read(), {"__name__": "__main__", "__file__": script_path})
```

Run the precommit-bisect with the wrapped hook + grep `~/735-trace-*.log` for paths outside the worktree.

- [ ] **Branch B (Task 5 reproduced — test artifact)**:

Add a pytest `conftest.py`-level autouse fixture in the worktree's test dir:

```python
# Conftest snippet (add to plugins/<plugin>/server/tests/conftest.py temporarily)
import builtins
import os
import pytest
from pathlib import Path

@pytest.fixture(autouse=True)
def trace_writes(request):
    """735 instrumentation: log all writes outside the worktree."""
    worktree_root = Path(__file__).resolve().parent.parent.parent.parent.parent
    log = open(f"/tmp/735-pytest-trace-{os.getpid()}.log", "a")
    original_write_text = Path.write_text
    original_write_bytes = Path.write_bytes
    original_open = builtins.open

    def traced_write_text(self, *args, **kwargs):
        if not str(self.resolve()).startswith(str(worktree_root)):
            log.write(f"{request.node.nodeid} :: {self} :: write_text\n")
            log.flush()
        return original_write_text(self, *args, **kwargs)

    Path.write_text = traced_write_text
    yield
    Path.write_text = original_write_text
    log.close()
```

Run pytest in each worktree; inspect `/tmp/735-pytest-trace-*.log` for cross-worktree paths.

- [ ] **Step (both branches): Identify the culprit code path**

The trace log contains specific `<file>:<line>` references for cross-worktree writes. Document the exact file + line for Task 7.

```
mcp__plugin_proj_proj__notes_append(
  op="experiment",
  heading="735 Phase 4 (instrumentation) — root cause identified",
  text="Cross-worktree write at <file:line>. Trace excerpt: <relevant lines from log>. Cause: <one-sentence diagnosis>."
)
```

- [ ] **Step (both branches): Revert instrumentation**

DO NOT commit the temporary wrapper / fixture. Use `git restore` or remove the inline edits before proceeding to Task 7. The repro scripts (Tasks 1, 3, 5) ARE the durable artifacts; the trace wrappers are throwaway.

---

## Task 7: Phase 5 — Targeted fix + regression

**Conditional**: only run if Task 6 identified a specific code path.

The fix has 3 candidate shapes per the spec:

- [ ] **Branch A: pre-commit script writes outside worktree**

Patch the offending script (e.g. `scripts/update_readme.py`):

```python
# Replace:
REPO_ROOT = Path(__file__).resolve().parent.parent
# With:
import subprocess
REPO_ROOT = Path(subprocess.check_output(
    ["git", "rev-parse", "--show-toplevel"], cwd=Path.cwd()
).decode().strip())
```

(Or whatever shape makes sense for the actual bug — this is the canonical fix pattern.)

Add a regression test: invoke the script from a worktree with cwd set; assert no opens outside the worktree.

- [ ] **Branch B: snapshot test writes absolute path**

Patch the test file. Replace absolute paths with `tmp_path` fixture or `Path(__file__).parent`-relative paths:

```python
# Replace:
SNAPSHOT_DIR = Path("/home/raul/...")
# With:
SNAPSHOT_DIR = Path(__file__).parent / "snapshots"
# OR:
def test_with_tmp(tmp_path):
    snapshot = tmp_path / "snapshot.txt"
    ...
```

Add regression test: pytest fixture wrapping `Path.write_text` asserts paths are inside the test's expected dir.

- [ ] **Branch C: uv cache leak**

Set `UV_CACHE_DIR` per-worktree in `.pre-commit-config.yaml` or wherever `uv` is invoked. Audit Existing config — pre-commit's basedpyright entry already does this:

```yaml
entry: bash -c 'export UV_CACHE_DIR="${UV_CACHE_DIR:-.uv-cache}"; ...'
```

If other invocations lack this, add it.

Regression: smoke test that `uv run` in worktree A doesn't write to worktree B's `.uv-cache/`.

- [ ] **Step (any branch): Add regression test**

The Phase 0 repro script (`scripts/repro/735-bare-git-repro.sh`) becomes the canonical regression. Extend it to cover the specific fixed scenario; ensure it passes after the fix.

- [ ] **Step (any branch): Update wiki page**

Edit `~/.claude/wiki/pages/pitfalls/worktree-rebase-artifact.md` "Status" section. Replace:

```
## Status

Cause not root-caused. Workaround reliable.
```

With:

```
## Status

**Root cause**: <brief description>. Fixed in commit <SHA>. Regression test: `scripts/repro/735-bare-git-repro.sh`.
```

Use `mcp__plugin_wiki_wiki__wiki_page_write` (preserve frontmatter, replace body).

- [ ] **Step: Decision-log entry per managed rule 20**

```
mcp__plugin_proj_proj__notes_append(
  op="decision",
  heading="735 root cause + fix",
  text="Root cause: <description>. Fix: <description>. Regression: scripts/repro/735-bare-git-repro.sh. Wiki updated."
)
```

- [ ] **Step: Run the original repro script + full proj suite to verify**

```bash
cd <worktree_path>
scripts/repro/735-bare-git-repro.sh  # PASS expected
cd plugins/proj/server && uv run pytest --no-cov  # all green
```

- [ ] **Step: Commit fix**

```bash
git add <patched files> scripts/repro/735-bare-git-repro.sh
git commit -m "fix(<area>/735): <root-cause description>"
```

---

## Task 8: Workaround codification (parallel track — independent of Tasks 1-7)

**Files:**
- Modify: `~/.claude/wiki/pages/concepts/parallel-impl-orchestration.md` (via wiki MCP)
- Modify: `plugins/proj/skills/parallel-batch-execute/SKILL.md`

This task ships REGARDLESS of investigation outcome.

- [ ] **Step 1: Read current wiki page**

```
mcp__plugin_wiki_wiki__wiki_page_get(slug="parallel-impl-orchestration", category="concepts")
```

Locate the "Known speed bumps" section's `worktree-rebase-artifact` entry.

- [ ] **Step 2: Update wiki page with safer workaround procedure**

Replace the existing `[[worktree-rebase-artifact]]` line with:

```markdown
- [[worktree-rebase-artifact]] — unstaged copies of sibling-worktree files mid-merge. Workaround procedure (per managed rule 8):
  1. Before each sequential rebase: `git status --porcelain` in the worktree.
  2. If non-empty: log warning + show diff to user via `AskUserQuestion`: [Discard | Investigate | Abort].
  3. User picks "Discard" → `git restore .` → retry rebase.
  4. User picks "Investigate" → halt; user resolves manually.
  5. User picks "Abort" → halt batch.

  Never auto-restore preemptively (managed rule 8 — destructive ops need consent). Standardized 2026-04-25 per todo 735.
```

Use `mcp__plugin_wiki_wiki__wiki_page_write`.

- [ ] **Step 3: Update `proj:parallel-batch-execute` SKILL Phase 5 step 1**

Edit `plugins/proj/skills/parallel-batch-execute/SKILL.md`. Locate Phase 5 step 1:

```
1. Sequential rebase + FF-merge (per [[worktree-merge-uses-rebase]])
   - First branch: FF-merge to dev directly
   - Each subsequent: rebase onto current dev -> FF-merge
   - Disjoint files -> conflict-free in practice
   - On rebase artifact (per [[worktree-rebase-artifact]]): git restore . -> retry rebase
```

Replace the `On rebase artifact` line with:

```
   - Pre-rebase artifact check (per [[worktree-rebase-artifact]] standardized procedure):
     a. `git status --porcelain` in worktree before rebase.
     b. Non-empty -> AskUserQuestion: [Discard | Investigate | Abort]. Never auto-restore (managed rule 8).
     c. User picks Discard -> `git restore .` -> retry rebase.
```

- [ ] **Step 4: Verify wiki + SKILL updated correctly**

```
mcp__plugin_wiki_wiki__wiki_lint_schema(category="concepts")
mcp__plugin_wiki_wiki__wiki_lint_broken_links(category="concepts")
```

```bash
grep -n 'Pre-rebase artifact check' plugins/proj/skills/parallel-batch-execute/SKILL.md
```

Expected: lint clean; SKILL has the new wording.

- [ ] **Step 5: Commit**

```bash
git add plugins/proj/skills/parallel-batch-execute/SKILL.md
git commit -m "feat(proj/735): codify worktree-rebase-artifact workaround in skill + wiki"
```

(Wiki page changes are out-of-repo; no git commit for the wiki edit. Note via `notes_append` for traceability.)

```
mcp__plugin_proj_proj__notes_append(
  op="note",
  heading="735 workaround codified in wiki + skill",
  text="parallel-impl-orchestration wiki page updated. proj:parallel-batch-execute SKILL Phase 5 step 1 updated to require AskUserQuestion gate before any git restore. Standardized procedure documented."
)
```

---

## Task 9: Pre-commit + final verification

- [ ] **Step 1: Run pre-commit on the changeset**

```bash
cd <worktree_path>
pre-commit run --all-files 2>&1 | tail -10
```

Expected: all hooks pass.

- [ ] **Step 2: Verify all repro scripts run**

```bash
scripts/repro/735-bare-git-repro.sh  # PASS expected (especially after fix)
```

(Phase 2 + 3 scripts are slower; run if time permits but not strictly required for verification.)

- [ ] **Step 3: Verify SKILL parses + cross-refs intact**

```bash
python3 -c "
import yaml
with open('plugins/proj/skills/parallel-batch-execute/SKILL.md') as f:
    fm = yaml.safe_load(f.read().split('---', 2)[1])
print('skill name:', fm['name'])
"
grep -c 'Pre-rebase artifact check' plugins/proj/skills/parallel-batch-execute/SKILL.md
```

Expected: skill name parses; new wording present.

---

## Task 10: Branch finishing (FF-merge to dev)

- [ ] **Step 1: Invoke `superpowers:finishing-a-development-branch`**

Per managed rule 11.

- [ ] **Step 2: Per project memory, FF-merge to dev (no PR)**

```bash
cd <worktree_path>
git fetch origin
git rebase origin/dev
cd /home/raul/projects/claude-project-manager
git checkout dev
git merge --ff-only feat/735-worktree-rebase-investigation
git push origin dev
```

- [ ] **Step 3: Watch CI**

```bash
gh run list --branch dev --limit 1
gh run watch <run-id> --exit-status
```

- [ ] **Step 4: Cleanup**

```
mcp__plugin_worktree_worktree__wt_remove(path="<worktree_path>")
```

```bash
git branch -d feat/735-worktree-rebase-investigation
```

- [ ] **Step 5: Mark todo 735 done**

```
mcp__plugin_proj_proj__todo_complete(todo_id="735")
```

- [ ] **Step 6: Append-only log entry**

```
mcp__plugin_proj_proj__notes_append(
  op="checkpoint",
  heading="735 worktree-rebase-artifact investigation shipped",
  text="<one-sentence summary: root cause found / not found / workaround codified>"
)
```

---

## Self-Review

**Spec coverage check** — every spec section maps to a task:

| Spec section | Task |
|---|---|
| Phase 0 (repro fixture) | Task 1 |
| Phase 1 (bare git) | Task 1 (executes Phase 1 with the script) |
| Phase 2 (pre-commit bisection) | Tasks 2 (audit) + 3 (bisection) |
| Phase 3 (tests bisection) | Tasks 4 (audit) + 5 (bisection) |
| Phase 4 (instrument) | Task 6 (conditional) |
| Phase 5 (targeted fix) | Task 7 (conditional) |
| Parallel track (workaround codify) | Task 8 (independent) |
| Risks (Phase 1 reproduces, time-box hit, etc.) | Decision gates at Tasks 1, 3, 5 |
| Validation per phase | Embedded in each task's verify steps |
| Wiki + SKILL updates | Task 7 (status section after fix) + Task 8 (workaround codification) |

Every spec phase + the parallel track is mapped to a concrete task. Decision gates handle the conditional branches.

**Placeholder scan** — search for: `TBD`, `Add appropriate`, `Similar to Task`, `Write tests for the above`. Found ONE intentional `TBD` in the File Structure table for Task 7's fix target — this is intentionally TBD because the fix target depends on Phase 4's finding. Documented as "TBD by Phase 4 outcome" + 3 candidate fix paths in Task 7. Not a placeholder failure.

**Type/name consistency** — script paths consistent: `scripts/repro/735-bare-git-repro.sh`, `735-precommit-bisect.sh`, `735-tests-bisect.sh`. Branch name consistent: `feat/735-worktree-rebase-investigation`. Worktree path consistent.

---

## Notes for the implementer

- **Investigation, not feature build**: this plan has CONDITIONAL phases. Decision gates at Tasks 1, 3, 5 determine whether to continue or escalate. Don't blindly run all tasks — respect the gates.
- **Time-box**: spec says ≤ 2 hours total for Phases 1-3. If you're past that without reproduction, jump to Task 8 (workaround codification) + document evidence.
- **Trace logs are throwaway**: `tmp/735-investigation/`, `~/735-trace-*.log`, `/tmp/735-pytest-trace-*.log` are NOT committed. The repro scripts ARE committed.
- **Phase 4 instrumentation is destructive to source**: temporarily editing `.pre-commit-config.yaml` or `conftest.py`. Always `git restore` after — never commit the wrapper.
- **No revdiff for this session**: per session-scoped user preference; user reads files directly for spec/plan review.
- **Parallel track (Task 8) is independent**: can be done first if you want quick discoverable wins. The investigation outcome doesn't change Task 8's content.
- **Per managed rule 17 (reproduce before fix)**: Phase 0 repro script IS the failing test. Once fix lands in Task 7, the same script becomes the regression test (it should now PASS).
