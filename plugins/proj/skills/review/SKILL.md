---
name: review
description: Walk through a codebase feature or code section in guided chapters, explain the logic, and create todos for improvements. Use when asked "review 1", "review src/auth/", "review the hook dispatch flow", or "walk me through X".
allowed-tools: Read, Glob, Grep, Bash, Task, mcp__plugin_proj_proj__proj_session_context, mcp__plugin_proj_proj__proj_load_session, mcp__plugin_proj_proj__ctx_session_start, mcp__plugin_proj_proj__content_get_requirements, mcp__plugin_proj_proj__todo_add, mcp__plugin_proj_proj__tracking_git_flush
argument-hint: "[<todo-id> | <path> | <description>] (any combination)"
---

> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Walk through codebase feature/section in guided chapters. Explain logic, answer questions inline, create todos for improvements, optionally run 2-agent in-depth review.


## Steps 1-5 — Codebase Exploration

Follow `/proj:explore` workflow (Steps 1-5: parse → resolve → filter → announce → guided chapters) w/ additions:

- Step 1: `$ARGUMENTS` empty → ask "What would you like to review?"
- Step 5 inline triggers: user says "create todo for X" → pause, run Step 6, resume. User says "in-depth review"/"skip to review" → Step 7.
- Chapter 4 ending: ask "Would you like in-depth review? (yes/no)". Yes → Step 7. No → Step 9.


## Step 6 — Todo Creation (any point)

Triggered by "create todo for X", "add todo", etc. during any chapter.

**6a.** User didn't spec todo desc → ask "What should todo be about?"

**6b.** Call `mcp__plugin_proj_proj__proj_session_context`.
- Err/no active project → 6c
- Active → 6d

**6c. Inactive proj — offer to load**

```
No active proj project. Load one? [Y/n]
```

Yes:
1. Ask "Project name?"
2. `mcp__plugin_proj_proj__proj_load_session` w/ name
3. Success → `mcp__plugin_proj_proj__ctx_session_start`
4. Not found → report err, skip todo creation. Resume review.

No → skip todo creation. Resume review.

**6d. Project mismatch warning**

Active project root ≠ reviewed path parent:
```
Active project is <project_name> but you are reviewing <reviewed_path>.
Todos will be created in <project_name>. Continue? [Y/n]
```
No → skip todo, resume review.

**6e. Create todo**

`mcp__plugin_proj_proj__todo_add` w/:
- `title`: todo desc
- `project_name`: active project
- NO `parent` (always top-level)

Confirm: "Todo created: **<title>**"

Add title to session todo list (step 9 summary). Resume chapter.


## Step 7 — In-depth Review

Declined → skip to step 9.

Accepted → spawn 2 parallel Task agents. Each gets:
- Filtered scoped file list (step 3)
- Analyze ONLY those files
- Tools: `Read, Glob, Grep, Bash`

**Agent A — Complexity & Bugs**

> Code reviewer. Analyze files for 2 categories. Each: report findings OR "none found" — both required.
>
> **Category 1 — Complexity Hotspots**: high cyclomatic complexity, deep nesting (3+), fns >50 lines, too many responsibilities, unclear naming.
>
> **Category 2 — Potential Bugs**: off-by-one, unchecked returns/errs, race conditions, resource leaks, bad err handling, type mismatches, logic errs, missing null/empty checks.
>
> Output — one row per finding:
> `| <one-line summary> | complexity OR bug | high OR medium OR low | <file>:<line> | <explanation> |`
>
> No findings → `**Complexity Hotspots**: none found` / `**Potential Bugs**: none found`

**Agent B — Dead Code & Test Coverage**

> Code reviewer. Analyze files for 2 categories. Each: report findings OR "none found" — both required.
>
> **Category 3 — Dead Code**: unused fns, unreachable branches, commented-out code, unused imports, deprecated w/ no callers, assigned-never-read vars.
>
> **Category 4 — Missing Test Coverage**: public fns w/o tests, untested err paths, edge cases w/o coverage, integration points w/o tests, untested conditional branches.
>
> Output — one row per finding:
> `| <one-line summary> | dead-code OR test-coverage | high OR medium OR low | <file>:<line> | <explanation> |`
>
> No findings → `**Dead Code**: none found` / `**Missing Test Coverage**: none found`


## Step 8 — Synthesize Report

Wait for both agents.

**Failure**: agent fails/times out → mark its 2 categories `[INCOMPLETE — manual review needed]`.

Verify all 4 categories have result. Agent returned but omitted category → treat as incomplete.

```
### In-Depth Review Report

| # | Finding | Category | Severity | File | Detail |
|---|---------|----------|----------|------|--------|
| 1 | ...     | ...      | ...      | ...  | ...    |

⚠️ INCOMPLETE: <category> — manual review needed
(only shown if an agent failed)

---
Create todos for findings? (all / select / no)
```

**"all"**: create todos for every finding (run 6e each, reuse active proj session).

**"select"**: numbered list:
```
1. <finding summary> [<severity>]
2. <finding summary> [<severity>]
...
Enter numbers to create todos (comma-separated, e.g. 1,3):
```
Parse input, create todos for selected only.

**"no"**: skip todo creation → step 9.

**Partial write failure**: `todo_add` fails mid-batch →
```
Created: <list of titles that succeeded>
Failed: <list of titles that failed> — <error>
```
Proceed to step 9 regardless.


## Step 9 — Session Summary

Display at end of every session (despite review/todos):

```
### Review Session Summary

**Scope**: <scope description>
**Files reviewed**: <N> files
**Chapters completed**: <list of chapters presented>

**Todos created this session**: <N>
1. <title>
2. <title>
(or "No todos created this session" if none)
```

Todos created AND proj active → `mcp__plugin_proj_proj__tracking_git_flush` w/ `commit_message="Review: <scope-description>"`.

Session ends.


## Edge Cases

Handled inline at noted steps:

| Edge Case | Step | Behavior |
|-----------|------|----------|
| Empty `$ARGUMENTS` | 1 | Prompt for scope |
| Path not found | 2 | Report, ask alternative |
| Todo ID not found | 2 | Report "not found", continue |
| Zero files after filter | 3 | Warn, ask broaden scope |
| 50+ files | 3 | Summarize count, ask narrow |
| Symlink cycle | 3 | Detect via visited real-path set, skip dupes |
| Binary/non-text | 3 | Filtered by allowlist — never reaches agents |
| Out-of-scope question | 5 | Note out of scope, offer expand |
| User skips chapter | 5 | "skip"/"next" → advance |
| No todo desc | 6 | Ask "What should todo be about?" |
| `proj_load_session` fails | 6 | Report err, skip todo |
| Proj/path mismatch | 6 | Warn, ask confirm |
| Agent fails/times out | 8 | Mark 2 categories INCOMPLETE |
| Partial bulk todo fail | 8 | Report which succeeded/failed |
| No todos created, proj active | 9 | Skip `tracking_git_flush` |
