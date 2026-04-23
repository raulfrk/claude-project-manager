# Task Tracking Emphasis (704) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tighten managed-block rules 7 (Task usage) + 10 (Proj todo boundary) in `plugins/_shared/claudemd/managed_section.md` so Claude defaults to native task tracking on any 2+ action work and clearly distinguishes ephemeral native Tasks from durable cpm proj todos.

**Architecture:** Single-file markdown edit. 2 `Edit` operations on `managed_section.md`. Verify by running `ensure_managed_section()` against an isolated tempdir. No code changes, no tests added. Single PR, FF-merge to dev.

**Tech Stack:** Markdown, `claudemd.py` Python helper for verification.

**Spec:** `docs/superpowers/specs/2026-04-23-704-task-tracking-emphasis-design.md`

**Todo:** 704

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `plugins/_shared/claudemd/managed_section.md` | modify | rewrite rules 7 + 10 |

No other files touched (no README change, no code, no tests).

---

### Task 1: Set up worktree

**Files:**
- Create worktree at: `~/worktrees/cpm/feat-704-task-tracking-emphasis`

- [ ] **Step 1: Create worktree**

```python
mcp__plugin_worktree_worktree__wt_create(
    repo_label="cpm",
    branch="feat/704-task-tracking-emphasis",
    base="dev",
    path="~/worktrees/cpm/feat-704-task-tracking-emphasis",
)
```

Note: `wt_create` does not accept a `base` kwarg (verified in `plugins/worktree/server/server/tools/worktrees.py:479`). If the call errors with that arg, drop `base="dev"` from the call. The MCP tool may accept extra args silently, in which case the call succeeds but the new branch is cut from whatever `dev` happens to be at the moment of the call. Either way, sync to remote in Step 2.

- [ ] **Step 2: Sync to remote per managed-block rule 13**

```bash
cd ~/worktrees/cpm/feat-704-task-tracking-emphasis
git fetch origin
git rev-list origin/dev..dev
# If empty (local not ahead): git reset --hard origin/dev
# If non-empty (local ahead): git reset --hard dev
```

- [ ] **Step 3: Verify clean tree**

```bash
git status --short
```

Expected: empty output, on branch `feat/704-task-tracking-emphasis`.

### Task 2: Verify current rule 7 + rule 10 wording

**Files:**
- Read: `plugins/_shared/claudemd/managed_section.md`

- [ ] **Step 1: Confirm current state**

```bash
grep -n "Task usage during multi-step work\|Proj todo boundary" plugins/_shared/claudemd/managed_section.md
```

Expected output (line numbers may vary by ±1 if other dev work has landed):
```
12:- **Task usage during multi-step work** — When starting multi-step implementation (3+ actions), use TaskCreate to track steps. Mark in_progress when beginning each step, completed when done. This makes progress visible to the user in real time.
14:- **Proj todo boundary** — Tasks = execution-time progress tracking. Proj todos = durable project state. Do NOT use todo_add for execution artifacts (use TaskCreate instead). Use todo_add only for real project-level TODOs that should persist after the session.
```

If either rule's wording differs from the above (someone else may have updated them between spec and plan execution), **STOP** and re-evaluate. The Edit ops in Tasks 3-4 require exact-match `old_string`.

### Task 3: Rewrite rule 7 (Task usage during multi-step work)

**Files:**
- Modify: `plugins/_shared/claudemd/managed_section.md` (line 12 area)

- [ ] **Step 1: Apply edit**

```python
Edit(
    file_path="/home/raul/projects/claude-project-manager/plugins/_shared/claudemd/managed_section.md",
    old_string="- **Task usage during multi-step work** — When starting multi-step implementation (3+ actions), use TaskCreate to track steps. Mark in_progress when beginning each step, completed when done. This makes progress visible to the user in real time.",
    new_string="- **Task usage during multi-step work** — Any work involving 2+ distinct actions → use `TaskCreate` (or `TodoWrite` on older harness) to track steps. Mark in_progress when beginning each step, completed when done. Default ON: when in doubt, create the task. Makes progress visible to the user in real time.",
)
```

- [ ] **Step 2: Verify edit landed**

```bash
grep "2+ distinct actions" plugins/_shared/claudemd/managed_section.md
grep "Default ON: when in doubt, create the task" plugins/_shared/claudemd/managed_section.md
```

Expected: 1 match each.

### Task 4: Rewrite rule 10 (Proj todo boundary)

**Files:**
- Modify: `plugins/_shared/claudemd/managed_section.md` (line 14 area)

- [ ] **Step 1: Apply edit**

```python
Edit(
    file_path="/home/raul/projects/claude-project-manager/plugins/_shared/claudemd/managed_section.md",
    old_string="- **Proj todo boundary** — Tasks = execution-time progress tracking. Proj todos = durable project state. Do NOT use todo_add for execution artifacts (use TaskCreate instead). Use todo_add only for real project-level TODOs that should persist after the session.",
    new_string="- **Proj todo boundary** — Native Tasks (`TaskCreate` / `TaskUpdate` / `TodoWrite`) = execution-time progress tracking, ephemeral, in-session only. Proj todos (`mcp__plugin_proj_proj__todo_add`) = durable project state, persist cross-session. Do NOT use `todo_add` for execution artifacts (use `TaskCreate` / `TodoWrite` instead). Use `todo_add` only for real project-level TODOs that should persist after the session.",
)
```

- [ ] **Step 2: Verify edit landed**

```bash
grep "ephemeral, in-session only" plugins/_shared/claudemd/managed_section.md
grep "persist cross-session" plugins/_shared/claudemd/managed_section.md
grep "mcp__plugin_proj_proj__todo_add" plugins/_shared/claudemd/managed_section.md
```

Expected: 1 match each.

### Task 5: Verify managed-block via `ensure_managed_section()` against tempdir

**Files:**
- No file change. Run a Python smoke test.

- [ ] **Step 1: Run the verification**

```bash
TEMP_HOME=$(mktemp -d)
mkdir -p "$TEMP_HOME/.claude"
echo "# Test CLAUDE.md" > "$TEMP_HOME/.claude/CLAUDE.md"
cd plugins/_shared/claudemd
HOME="$TEMP_HOME" uv run python3 -c "
from claudemd import ensure_managed_section
from pathlib import Path
result = ensure_managed_section(Path('$TEMP_HOME/.claude/CLAUDE.md'))
print(f'modified: {result}')
content = Path('$TEMP_HOME/.claude/CLAUDE.md').read_text()
import re
bullet_count = len(re.findall(r'^- \*\*', content, re.MULTILINE))
print(f'bold-rule count: {bullet_count}')
assert '2+ distinct actions' in content, 'rule 7 new wording missing'
assert 'Default ON: when in doubt, create the task' in content, 'rule 7 default-ON framing missing'
assert 'TodoWrite' in content, 'TodoWrite mention missing'
assert 'ephemeral, in-session only' in content, 'rule 10 ephemeral framing missing'
assert 'persist cross-session' in content, 'rule 10 cross-session framing missing'
assert 'mcp__plugin_proj_proj__todo_add' in content, 'rule 10 qualified todo_add reference missing'
assert bullet_count == 22, f'bold-rule count changed: expected 22, got {bullet_count}'
print('all assertions passed')
"
rm -rf "$TEMP_HOME"
```

If the import path differs from `from claudemd import ensure_managed_section`, find the correct one with:
```bash
grep -rn "def ensure_managed_section" plugins/_shared/claudemd/ | head -3
```

Then adapt the import line.

Expected output: `modified: True` + `bold-rule count: 22` + `all assertions passed`.

### Task 6: Run claudemd + shared tests

**Files:**
- No file change.

- [ ] **Step 1: Run shared tests**

```bash
cd /home/raul/projects/claude-project-manager
just test-shared 2>&1 | tail -30
# or, if no recipe exists:
cd plugins/_shared && uv run pytest 2>&1 | tail -30
```

Expected: all tests pass. Markdown content shape unchanged (still flat block w/ start/end markers, still 22 bolded rules); existing tests should continue to pass.

### Task 7: Commit + push + FF-merge to dev + watch CI

**Files:**
- Single commit including the modified managed_section.md.

- [ ] **Step 1: Commit**

```bash
cd ~/worktrees/cpm/feat-704-task-tracking-emphasis
git add plugins/_shared/claudemd/managed_section.md
git status
git commit -m "$(cat <<'EOF'
feat(claudemd/704): tighten task-tracking emphasis (rules 7 + 10)

Rule 7 (Task usage during multi-step work): drop threshold from
3+ to 2+ distinct actions; mention TodoWrite as the older-harness
variant alongside TaskCreate; add explicit "Default ON: when in
doubt, create the task" framing.

Rule 10 (Proj todo boundary): name both surfaces explicitly
(TaskCreate / TaskUpdate / TodoWrite vs mcp__plugin_proj_proj__todo_add);
add "ephemeral, in-session only" vs "persist cross-session"
to sharpen the boundary.

Spec: docs/superpowers/specs/2026-04-23-704-task-tracking-emphasis-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 2: Push + FF-merge to dev**

```bash
git push -u origin feat/704-task-tracking-emphasis
git checkout dev
git pull origin dev
git merge --ff-only feat/704-task-tracking-emphasis
git push origin dev
```

If FF-merge fails (dev has advanced): rebase the feature branch onto current dev, then retry FF-merge.

- [ ] **Step 3: Watch CI**

```bash
gh run watch
```

Expected: green CI on dev. Markdown-only change; only existing claudemd tests should be affected.

---

## Self-Review

After executing, verify:

1. **Spec coverage**: every spec section maps to a task.
   - Rule 7 rewording ↔ Task 3 ✓
   - Rule 10 rewording ↔ Task 4 ✓
   - Testing strategy (ensure_managed_section + claudemd tests) ↔ Tasks 5 + 6 ✓
   - No README change (per spec non-goal) ↔ no task ✓
   - No code change (per spec non-goal) ↔ no task ✓
2. **No placeholders**: searched plan; no TBD/TODO/fill-in.
3. **Type consistency**: `TaskCreate`/`TaskUpdate`/`TodoWrite`/`mcp__plugin_proj_proj__todo_add` are referenced consistently across rule 7, rule 10, and verification asserts.
4. **Worktree discipline**: Task 1 sets up worktree per managed-block rule pattern.

---

## Notes

- **No worktree for the plan itself** — plan lives on `dev`. Implementation happens in `~/worktrees/cpm/feat-704-task-tracking-emphasis`.
- **`base` kwarg caveat in Task 1 Step 1**: `wt_create` may not accept `base`; the Phase 3 fix of todo 699 documented this. The call may either error or succeed depending on argument-passing strictness. Either path produces the right outcome (branch cut from whatever `dev` is at the time, then synced in Step 2).
- **No revdiff for review** per user instruction (2026-04-23). Manual review on the spec already approved.
- **Caveman-ultra phrasing** in the rewrites preserves the existing block style.
