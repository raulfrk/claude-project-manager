---
name: checkpoint
description: Mid-execution checkpoint — review in-flight work, decide continue/reset/tighten. Use when a TaskCreate-tracked phase completes during multi-step impl, when user pauses to evaluate, or when the user says "checkpoint", "/proj:checkpoint", "review where we are", or "should we keep going".
allowed-tools: mcp__proj__proj_get_active, mcp__proj__notes_append, mcp__plugin_worktree_worktree__wt_list, mcp__plugin_worktree_worktree__wt_remove, mcp__plugin_worktree_worktree__wt_create, mcp__proj__todo_list, AskUserQuestion, Bash, Skill
argument-hint: "[optional: scope hint or branch suffix]"
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Mid-exec checkpoint. Read in-flight diff; surface state; prompt continue/reset/tighten.

**1.** Active project: `mcp__proj__proj_get_active` → extract `name`, `repos[].path`.

**2.** Worktrees: `mcp__plugin_worktree_worktree__wt_list(repo_label=<from project meta>)`. Multiple worktrees → prompt user via `AskUserQuestion` to pick one. Single → use it.

**3.** Compute diff-since-last-checkpoint:
 - Last checkpoint marker = git note tag `checkpoint:<timestamp>` on branch HEAD.
 - `cd <wt_path> && git notes list 2>/dev/null | tail -1` → last marker SHA, if any.
 - No marker → use base branch divergence: `git merge-base origin/<base>..HEAD` (base = `git config --get branch.<branch>.remote-base` or default `dev`).
 - Diff cmd: `git diff <base-sha>..HEAD --stat` + `git diff <base-sha>..HEAD --name-only`.

**4.** Surface diff:
 - revdiff available (rule 11 check: `enabledPlugins["revdiff@revdiff"]` in `~/.claude/settings.json` AND `which revdiff` returns 0):
     - Invoke `revdiff:revdiff` skill w/ ref args `<base-sha> HEAD`.
 - Else: render inline — `git diff --stat` output + bullet summary per file (line counts, brief purpose).

**5.** State context:
 - Recent commits: `git log <base-sha>..HEAD --oneline | head -10`.
 - Open todos: `mcp__proj__todo_list(status="open", compact=True)` → first 5.
 - Recent notes: `tail -20 <tracking_dir>/<name>/notes.md` (last few entries).

**6.** Prompt user via `AskUserQuestion`:
 - Q: "Checkpoint review — what next?"
 - Options:
     - **Continue** — Work continues. Next checkpoint marker advances to current HEAD.
     - **Reset + restart w/ tightened scope** — `wt_remove` current; `wt_create` new w/ branch suffix `-v2` (or `$ARGUMENTS` if provided). Prompt for tightened-scope statement. Log via `notes_append(op="checkpoint", heading="reset to v2: <scope>")`.
     - **Tighten scope only** — Keep branch + worktree. Prompt for new constraint. Log via `notes_append(op="checkpoint", heading="tightened: <constraint>")`.

**7.** Apply chosen action:
 - Continue → `cd <wt_path> && git notes add -m "checkpoint" HEAD`. `notes_append(op="checkpoint", heading="continue", text="<diff summary + decision rationale>")`.
 - Reset → `mcp__plugin_worktree_worktree__wt_remove(path=<old>)`; `mcp__plugin_worktree_worktree__wt_create(repo_label=<x>, branch=<old-branch>-v2, base="dev", path=<old>-v2)`. Sync per rule 13 (fetch + reset). `notes_append(op="checkpoint", heading="reset to v2: <user-supplied scope>", text="<reason>")`. Inform user new wt path.
 - Tighten → `notes_append(op="checkpoint", heading="tightened: <constraint>", text="<full text>")`. Continue on same branch.

**8.** "Checkpoint complete. Next action: <continue|reset|tighten>."

## Prerequisites

- Active project loaded (`mcp__proj__proj_get_active` returns project meta).
- Project has at least one repo registered.
- Repo has at least one worktree (created via `wt_create` per managed-block rule 6).

## Err Handling

- No active project → display err, stop.
- No worktrees → display err: "No worktrees found. Create via wt_create first.", stop.
- `git notes` not supported (some configs disable) → fall back to base-branch divergence (step 3 fallback path) silently.
- revdiff missing or fails to launch → fall back to inline diff render silently (per rule 11).
- User cancels AskUserQuestion → no action; state preserved.
- wt_create fails on reset path → display err, original worktree NOT removed (safety).

## Output

Selected action + applied change + log entry confirmation. Diff display happens via revdiff or inline.

## Usage

- `/proj:checkpoint` → review w/o scope hint; reset path uses `-v2` default suffix.
- `/proj:checkpoint <scope-hint>` → `$ARGUMENTS` becomes the branch suffix on reset (replaces `-v2` default) and is included in the tightened-scope prompt.
