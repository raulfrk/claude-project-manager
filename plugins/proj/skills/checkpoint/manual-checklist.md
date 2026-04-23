# /proj:checkpoint — Manual E2E Verification Checklist

This checklist verifies `/proj:checkpoint` works end-to-end. User-interactive prompts cannot be automated, so run through this manually before merge.

## Prerequisites

- Test project initialized via `/proj:init` in a scratch directory
- One worktree created via `mcp__plugin_worktree_worktree__wt_create`
- `revdiff` plugin enabled (per `~/.claude/settings.json::enabledPlugins["revdiff@revdiff"]`) AND `which revdiff` returns 0 — for the revdiff path
- Run separately with revdiff disabled to verify the inline-fallback path

## Scenarios

### Scenario A: Continue path (revdiff enabled)

1. [ ] Make 2-3 small commits on the worktree branch.
2. [ ] Invoke `/proj:checkpoint` (no args).
3. [ ] Verify diff is surfaced via revdiff TUI overlay (terminal popup).
4. [ ] Quit revdiff with no annotations.
5. [ ] Verify `AskUserQuestion` prompt appears with 3 options.
6. [ ] Select "Continue".
7. [ ] Verify `tracking_dir/<project>/notes.md` has a new entry with heading `## [YYYY-MM-DD HH:MM] checkpoint | continue` (audit-trail entry; no git state change).

### Scenario B: Reset path (default `-v2` suffix)

1. [ ] On a fresh worktree branch with 1 commit, invoke `/proj:checkpoint`.
2. [ ] Select "Reset + restart with tightened scope".
3. [ ] Provide a tightened-scope statement when prompted.
4. [ ] Verify the original worktree is removed (`wt_list` no longer shows it).
5. [ ] Verify a new worktree exists with branch suffix `-v2` (e.g. `feat/foo` → `feat/foo-v2`).
6. [ ] Verify the base repo's `dev` was reset to `origin/dev` (`git -C <repo_root> log dev --oneline -1` matches `origin/dev`) before `wt_create`, and the new worktree branches from that HEAD (per rule 13).
7. [ ] Verify `notes.md` has a new entry with heading `## [YYYY-MM-DD HH:MM] checkpoint | reset to v2: <scope>`.

### Scenario C: Reset path with custom suffix via $ARGUMENTS

1. [ ] On a fresh worktree branch, invoke `/proj:checkpoint focus-impl-only`.
2. [ ] Select "Reset + restart".
3. [ ] Verify new branch is `<original>-focus-impl-only` (not `-v2`).
4. [ ] Verify notes.md heading reflects the user-supplied scope.

### Scenario D: Tighten path

1. [ ] On a worktree with diverging commits, invoke `/proj:checkpoint`.
2. [ ] Select "Tighten scope only".
3. [ ] Provide a new constraint when prompted.
4. [ ] Verify worktree + branch are unchanged (still on the same branch + path).
5. [ ] Verify `notes.md` has a new entry with heading `## [YYYY-MM-DD HH:MM] checkpoint | tightened: <constraint>`.

### Scenario E: revdiff fallback (revdiff disabled)

1. [ ] Disable revdiff in `~/.claude/settings.json::enabledPlugins`.
2. [ ] Invoke `/proj:checkpoint`.
3. [ ] Verify diff is rendered inline (text), not via revdiff TUI.
4. [ ] Verify the rest of the flow (state context, AskUserQuestion, action) works the same.
5. [ ] Re-enable revdiff after testing.

### Scenario F: No worktrees error

1. [ ] In a project with no registered worktrees, invoke `/proj:checkpoint`.
2. [ ] Verify the skill exits cleanly with the error message: "No worktrees found. Create via wt_create first."
3. [ ] Verify no notes.md entry is added.

## Pass criteria

All 6 scenarios complete without errors. Diff surface (revdiff/inline) renders correctly. Each path produces the expected log entry in notes.md with the convention heading format.
