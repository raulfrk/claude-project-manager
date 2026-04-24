# Managed-block Hygiene Bundle (722) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve 3 hygiene items in `plugins/_shared/claudemd/managed_section.md`: (1) insert HTML rule-number comments to prevent recurring off-by-one in specs/commits, (2) backtick-normalize 4 bare tool names, (3) reword rule 24 to drop "don't count tasks" framing.

**Architecture:** Single-file markdown edit. awk-driven insertion of HTML comments, then 5 Edit ops for backticks + rule 24 rewrite. No code, no tests. Single PR, FF-merge to dev.

**Tech Stack:** Markdown, awk, `claudemd.py` Python helper for verification.

**Spec:** `docs/superpowers/specs/2026-04-23-722-managed-block-hygiene-design.md`

**Todo:** 722

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `plugins/_shared/claudemd/managed_section.md` | modify | insert 24 HTML comments + 4 backtick Edits + 1 rule 24 rewrite |

No other files touched.

---

### Task 1: Set up worktree

**Files:**
- Create worktree at: `~/worktrees/cpm/feat-722-managed-block-hygiene`

- [ ] **Step 1: Create worktree**

```python
mcp__plugin_worktree_worktree__wt_create(
    repo_label="cpm",
    branch="feat/722-managed-block-hygiene",
    base="dev",
    path="~/worktrees/cpm/feat-722-managed-block-hygiene",
)
```

Drop `base="dev"` if the call errors (per Phase 3 fix of 699).

- [ ] **Step 2: Sync to remote per rule 13**

```bash
cd ~/worktrees/cpm/feat-722-managed-block-hygiene
git fetch origin
git rev-list origin/dev..dev
# If empty: git reset --hard origin/dev
# If non-empty: git reset --hard dev
git status --short  # expect empty
```

### Task 2: Confirm baseline state of `managed_section.md`

**Files:**
- Read: `plugins/_shared/claudemd/managed_section.md`

- [ ] **Step 1: Verify bullet count + key targets**

```bash
grep -c "^- " plugins/_shared/claudemd/managed_section.md
```
Expected: `24`

```bash
grep -n "(EnterPlanMode)\|after ExitPlanMode\|a single AskUserQuestion call\|Agents may freely TaskCreate\|Don't require Claude to count tasks" plugins/_shared/claudemd/managed_section.md
```
Expected: 5 matches (one per target).

If `grep -c "^- "` ≠ 24, or any target string is missing, **STOP** and report BLOCKED — the implementation relies on this exact state.

### Task 3: Insert 24 HTML rule-number comments

**Files:**
- Modify: `plugins/_shared/claudemd/managed_section.md`

- [ ] **Step 1: Apply awk transform**

```bash
cd ~/worktrees/cpm/feat-722-managed-block-hygiene
awk '
  /^- / { count++; print "<!-- rule: " count " -->"; print; next }
  { print }
' plugins/_shared/claudemd/managed_section.md > /tmp/managed_section_with_comments.md

# Verify output looks right
head -15 /tmp/managed_section_with_comments.md

# Replace the file atomically
mv /tmp/managed_section_with_comments.md plugins/_shared/claudemd/managed_section.md
```

- [ ] **Step 2: Verify the 24 comments landed**

```bash
grep -c "^<!-- rule: [0-9]\+ -->" plugins/_shared/claudemd/managed_section.md
# Expect: 24

grep -c "^- " plugins/_shared/claudemd/managed_section.md
# Expect: 24 (bullet count unchanged)

# Spot-check a few bullets have their number directly above them
grep -B 1 "^- \*\*Auto-capture issues" plugins/_shared/claudemd/managed_section.md
# Expect: "<!-- rule: 3 -->" line above the Auto-capture bullet
```

- [ ] **Step 3: Verify rule numbers on known anchors**

```bash
# rule 7 = Task usage during multi-step work
grep -B 1 "^- \*\*Task usage during multi-step work" plugins/_shared/claudemd/managed_section.md
# Expect: "<!-- rule: 7 -->"

# rule 9 = Proj todo boundary (NOT rule 10 — this is the bug the comments prevent)
grep -B 1 "^- \*\*Proj todo boundary" plugins/_shared/claudemd/managed_section.md
# Expect: "<!-- rule: 9 -->"

# rule 20 = Append-only log convention
grep -B 1 "^- \*\*Append-only log convention" plugins/_shared/claudemd/managed_section.md
# Expect: "<!-- rule: 20 -->"

# rule 24 = Mid-execution checkpoint rhythm
grep -B 1 "^- \*\*Mid-execution checkpoint rhythm" plugins/_shared/claudemd/managed_section.md
# Expect: "<!-- rule: 24 -->"
```

All 4 checks must match. If any don't, the awk ordering is off — **STOP** and report.

### Task 4: Backtick-normalize 4 bare tool names

**Files:**
- Modify: `plugins/_shared/claudemd/managed_section.md`

All 4 Edits below use precise `old_string` anchors w/ surrounding context for uniqueness.

- [ ] **Step 1: Rule 2 — backtick `EnterPlanMode`**

```
Edit:
  file_path: "<worktree>/plugins/_shared/claudemd/managed_section.md"
  old_string: "- ALWAYS enter plan mode (EnterPlanMode) before executing any multi-step implementation."
  new_string: "- ALWAYS enter plan mode (`EnterPlanMode`) before executing any multi-step implementation."
```

- [ ] **Step 2: Rule 3 — backtick `ExitPlanMode`**

```
Edit:
  file_path: "<worktree>/plugins/_shared/claudemd/managed_section.md"
  old_string: "note the finding mentally and act on it after `ExitPlanMode`.**"
  new_string: "note the finding mentally and act on it after `ExitPlanMode`.**"
```

**Note**: `ExitPlanMode` is ALREADY backticked in rule 3 (verified via Read of the file in Task 2). **Skip this Step if the grep from Task 2 Step 1 didn't find `after ExitPlanMode` as a bare mention.** Re-verify before applying:

```bash
grep -c "after ExitPlanMode\b" plugins/_shared/claudemd/managed_section.md
# If 0: ExitPlanMode already backticked, skip this step
# If 1: bare mention exists, apply Edit below
```

If Edit is needed:
```
Edit:
  file_path: "<worktree>/plugins/_shared/claudemd/managed_section.md"
  old_string: "act on it after ExitPlanMode"
  new_string: "act on it after `ExitPlanMode`"
```

- [ ] **Step 3: Rule 4 — backtick `AskUserQuestion` (2nd mention)**

Rule 4's 1st mention of `AskUserQuestion` is already backticked. The 2nd mention is bare: "batch in a single AskUserQuestion call".

```
Edit:
  file_path: "<worktree>/plugins/_shared/claudemd/managed_section.md"
  old_string: "If you are in plan mode, the same rule applies — batch in a single AskUserQuestion call."
  new_string: "If you are in plan mode, the same rule applies — batch in a single `AskUserQuestion` call."
```

- [ ] **Step 4: Rule 10 — backtick `TaskCreate` in Sub-task nesting**

```
Edit:
  file_path: "<worktree>/plugins/_shared/claudemd/managed_section.md"
  old_string: "- **Sub-task nesting** — Agents may freely TaskCreate subtasks under their parent Task for meaningful work units"
  new_string: "- **Sub-task nesting** — Agents may freely `TaskCreate` subtasks under their parent Task for meaningful work units"
```

- [ ] **Step 5: Verify all 4 backtick fixes landed**

```bash
grep "(\`EnterPlanMode\`)" plugins/_shared/claudemd/managed_section.md
# Expect: 1 match

# ExitPlanMode: either it was already backticked (no change needed) or now is
grep -c "after ExitPlanMode\b" plugins/_shared/claudemd/managed_section.md
# Expect: 0

grep "batch in a single \`AskUserQuestion\` call" plugins/_shared/claudemd/managed_section.md
# Expect: 1 match

grep "Agents may freely \`TaskCreate\` subtasks" plugins/_shared/claudemd/managed_section.md
# Expect: 1 match
```

### Task 5: Rewrite rule 24 (Mid-execution checkpoint rhythm)

**Files:**
- Modify: `plugins/_shared/claudemd/managed_section.md`

- [ ] **Step 1: Apply edit**

```
Edit:
  file_path: "<worktree>/plugins/_shared/claudemd/managed_section.md"
  old_string: "- **Mid-execution checkpoint rhythm** — During multi-step impl, suggest `/proj:checkpoint` when TaskCreate-tracked phase completes OR user pauses to evaluate. Asks: continue / reset+restart w/ tightened scope / tighten scope only. Don't require Claude to count tasks — anchor on phase-boundary signals or explicit user pause. *(Source: derived from Howells reset-over-recover + Karpathy autonomy-slider per task.)*"
  new_string: "- **Mid-execution checkpoint rhythm** — During multi-step impl, suggest `/proj:checkpoint` when a `TaskCreate`-tracked phase completes OR user pauses to evaluate. Asks: continue / reset+restart w/ tightened scope / tighten scope only. Anchor checkpoint suggestions on phase-boundary signals or explicit user pause (not on completed-task counts). *(Source: derived from Howells reset-over-recover + Karpathy autonomy-slider per task.)*"
```

- [ ] **Step 2: Verify edit landed**

```bash
grep "when a \`TaskCreate\`-tracked phase completes" plugins/_shared/claudemd/managed_section.md
# Expect: 1 match

grep "(not on completed-task counts)" plugins/_shared/claudemd/managed_section.md
# Expect: 1 match

grep -c "Don't require Claude to count tasks" plugins/_shared/claudemd/managed_section.md
# Expect: 0 (old framing gone)
```

### Task 6: Verify managed-block via `ensure_managed_section()` against tempdir

**Files:**
- No file change. Run Python smoke test.

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
comment_count = len(re.findall(r'^<!-- rule: \d+ -->$', content, re.MULTILINE))
print(f'rule-comment count: {comment_count}')
assert bullet_count == 22, f'bold-rule count changed: {bullet_count}'
assert comment_count == 24, f'rule-comment count wrong: {comment_count}'
assert '\`EnterPlanMode\`' in content, 'rule 2 backtick missing'
assert 'batch in a single \`AskUserQuestion\` call' in content, 'rule 4 backtick missing'
assert 'Agents may freely \`TaskCreate\` subtasks' in content, 'rule 10 backtick missing'
assert 'when a \`TaskCreate\`-tracked phase completes' in content, 'rule 24 TaskCreate backtick missing'
assert '(not on completed-task counts)' in content, 'rule 24 new wording missing'
assert \"Don't require Claude to count tasks\" not in content, 'rule 24 old wording still present'
print('all assertions passed')
"
rm -rf "$TEMP_HOME"
```

If the import path errors, find via `grep -rn "def ensure_managed_section" plugins/_shared/claudemd/` and adapt.

Expected: `modified: True`, `bold-rule count: 22`, `rule-comment count: 24`, `all assertions passed`.

If `rule-comment count` is NOT 24 after `ensure_managed_section()` runs, the claudemd parser is stripping HTML comments — STOP and report BLOCKED (item 1 is not viable; a different approach is needed).

### Task 7: Run shared tests

**Files:**
- No file change.

- [ ] **Step 1: Run shared tests**

```bash
cd /home/raul/worktrees/cpm/feat-722-managed-block-hygiene
just test-shared 2>&1 | tail -30
# or:
cd plugins/_shared && uv run pytest 2>&1 | tail -30
```

Expected: all tests pass. Markdown shape unchanged (same 22 bolded rules, same markers, + 24 HTML comments which parser should treat as invisible).

If any test fails: investigate root cause.

### Task 8: Commit + push + FF-merge to dev + watch CI

- [ ] **Step 1: Commit**

```bash
cd ~/worktrees/cpm/feat-722-managed-block-hygiene
git add plugins/_shared/claudemd/managed_section.md
git status
git commit -m "$(cat <<'EOF'
feat(claudemd/722): managed-block hygiene bundle

3 hygiene items in a single PR:

- Item 1: inline <!-- rule: N --> HTML comments before each of
  the 24 bullets in managed_section.md. Canonical rule numbers
  visible to spec/commit authors; prevents recurring off-by-one
  errors (Phase 1 had it, 720 had it again). HTML comments are
  invisible to markdown renderers but present in the raw file.
- Item 2: backtick-normalize 4 bare tool names: EnterPlanMode
  (rule 2), AskUserQuestion 2nd mention (rule 4), TaskCreate in
  Sub-task nesting (rule 10), TaskCreate in Mid-execution
  checkpoint rhythm (rule 24, absorbed by item 3).
- Item 3: rewrite rule 24 to drop "Don't require Claude to count
  tasks" negation. New form: "Anchor checkpoint suggestions on
  phase-boundary signals or explicit user pause (not on
  completed-task counts)." Removes surface tension with rule 7's
  "2+ distinct actions" framing.

Spec: docs/superpowers/specs/2026-04-23-722-managed-block-hygiene-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 2: Push + FF-merge to dev**

```bash
git push -u origin feat/722-managed-block-hygiene
git checkout dev
git pull origin dev
git merge --ff-only feat/722-managed-block-hygiene
git push origin dev
```

If FF-merge fails: rebase onto current dev + retry.

- [ ] **Step 3: Watch CI**

```bash
gh run watch
```

Expected: green CI on dev.

---

## Self-Review

After executing, verify:

1. **Spec coverage**:
   - Item 1 (HTML rule-number comments) ↔ Task 3 ✓
   - Item 2 (backtick normalization, 4 names) ↔ Task 4 (steps 1, 3, 4) + Task 5 step 1 absorbs rule 24's TaskCreate ✓
   - Item 3 (rule 24 rewrite) ↔ Task 5 ✓
   - No managed-block size change in rule count ↔ Task 6 asserts 22 bolded ✓
2. **No placeholders**: scanned plan; no TBD/TODO. Task 4 Step 2 has conditional skip logic based on Task 2 grep result — not a placeholder, it's a branch decision.
3. **Type consistency**: backticked tool names consistent (`EnterPlanMode`, `AskUserQuestion`, `TaskCreate`).
4. **Worktree discipline**: Task 1 sets up per managed-block rule 13.

---

## Notes

- **No revdiff for review** per user instruction (2026-04-23). Manual spec review already approved.
- **awk insertion (Task 3) is deterministic + idempotent-ish**: running awk twice would double-insert comments. Task 2 baseline check prevents double-insertion; Task 6 tempdir verification catches count mismatches.
- **Task 4 Step 2 (ExitPlanMode) may no-op** depending on current state; the conditional skip avoids breaking the implementer if the file already has `` `ExitPlanMode` ``.
- **Caveman-ultra** preserved in all rewrites (rule 24 stays fragmented + direct).
- **Token cost on users**: +24 lines × ~15 chars = ~360 chars added to `~/.claude/CLAUDE.md`. Negligible vs total size.
- **Rollback**: if HTML comments break anything unexpectedly, revert by running awk again inverse: `awk '/^<!-- rule: / {next} {print}' managed_section.md > out && mv out managed_section.md`.
