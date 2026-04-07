---
name: review
description: Walk through a codebase feature or code section in guided chapters, explain the logic, and create todos for improvements. Use when asked "review 1", "review src/auth/", "review the hook dispatch flow", or "walk me through X".
allowed-tools: Read, Glob, Grep, Bash, Task, mcp__plugin_proj_proj__proj_session_context, mcp__plugin_proj_proj__proj_load_session, mcp__plugin_proj_proj__ctx_session_start, mcp__plugin_proj_proj__content_get_requirements, mcp__plugin_proj_proj__todo_add, mcp__plugin_proj_proj__tracking_git_flush
argument-hint: "[<todo-id> | <path> | <description>] (any combination)"
---

Walk through a codebase feature or section with the user in guided chapters. Explain the logic, answer questions inline, create todos for improvements, and optionally run a 2-agent in-depth review.

> **Note**: Steps 1-5 below are the codebase exploration flow, identical to the standalone `/proj:explore` skill. Review adds todo creation (step 6) and in-depth review (steps 7-8) on top of the exploration.

---

## Step 1 — Parse $ARGUMENTS

Extract from `$ARGUMENTS`:
- **Todo IDs**: tokens matching `^\d+(\.\d+)*$` (e.g. `42`, `3.1`, `397.2`)
- **Paths**: tokens starting with `/`, `./`, `~/`, or containing a `/` followed by a file extension (e.g. `src/auth/`, `./plugins/hooks/`)
- **Description**: all remaining tokens joined as free-form text

If `$ARGUMENTS` is empty: ask the user "What would you like to review? You can provide a file path, directory, description, or a proj todo ID."

---

## Step 2 — Resolve scope

Build a raw file list from all three input types:

### Todo IDs
For each todo ID:
1. Call `mcp__plugin_proj_proj__proj_session_context`
2. If proj is active: call `mcp__plugin_proj_proj__content_get_requirements` with the todo ID. Extract any file paths, directories, or module names referenced in the requirements text (look for lines like "File:", paths with `/`, import references). Add those to the raw file list.
3. If proj is inactive OR content is empty: fall back to Grep + Glob using keywords from the todo ID itself (e.g. search for `grep -r "todo title keywords"` across the codebase).
4. If the MCP call returns a "not found" error: report "Todo ID `<id>` not found — skipping, continuing with remaining scope." Do not stop.

### Paths
For each path token:
- Run `Glob` with the path (as-is or with `/**/*` appended for directories).
- If zero matches: report "Path `<path>` not found. Please provide an alternative." and wait for the user's response before continuing.

### Description
For the free-form description:
- Extract 2–4 keywords. Run `Grep` across the codebase for each keyword.
- Run `Glob` for patterns derived from keywords (e.g. `**/*auth*.*`).
- Collect all matched files. Deduplicate.

---

## Step 3 — Filter file list

Apply to the raw file list:

**Source extension allowlist** (keep only):
`.py`, `.ts`, `.tsx`, `.js`, `.jsx`, `.go`, `.java`, `.rb`, `.rs`, `.c`, `.cpp`, `.h`, `.md`, `.yaml`, `.yml`, `.json`, `.toml`, `.sh`

**Exclude patterns** (remove any file whose path contains):
`node_modules/`, `__pycache__/`, `.git/`, `dist/`, `build/`, `.venv/`, `*.lock`, `*.png`, `*.jpg`, `*.gif`, `*.svg`, `*.pyc`, `*.whl`, `*.min.js`, `*.map`

**Symlink handling**:
- For each file, resolve the real path via `Bash: readlink -f <path>`
- Track visited real paths in a set. If a real path is already seen, skip (cycle detected).

**After filtering**:
- If zero files remain: warn "No source files found after filtering. Try broadening the scope." and ask the user to provide additional scope.
- If more than 50 files: summarize the count and ask "That's <N> files — would you like to narrow the scope?" before proceeding.

---

## Step 4 — Announce scope and confirm

Display:

```
I'll walk you through **<N> files** covering: <scope description>

Files in scope:
- <file1>
- <file2>
- ...

Ready to start? (yes / change scope)
```

If the user says "change scope": return to step 1 and re-parse with any new input they provide.

If the user confirms: proceed to step 5.

---

## Step 5 — Guided chapters

Present chapters one at a time. Do NOT advance to the next chapter until the user explicitly continues.

**At any point during a chapter**, if the user says "create a todo for X" or similar: pause the chapter, run step 6 (todo creation), then resume where you left off.

**At any point**, if the user says "in-depth review" or "skip to review": jump directly to step 7.

---

### Chapter 1 — Overview

Read the scoped files using `Read`. Produce a high-level summary:
- What does this feature/section do? What problem does it solve?
- How does it fit in the broader system? What calls into it, what does it call?
- Brief file map: one line per file explaining its role

After presenting:
```
Continue to Chapter 2 (Component Breakdown)? Or ask me anything about this chapter.
```

**User interaction rules for this and all chapters:**
- If user asks a question: answer inline using `Read`/`Grep`. Do NOT advance to the next chapter.
- If user requests specific code: show it with `Read`. Stay in current chapter.
- If user says "skip", "next", or "continue": advance to the next chapter.
- If user says "go back": return to the previous chapter.

---

### Chapter 2 — Component Breakdown

Identify the main components, modules, classes, or subsystems within the scope. For each:
- **Name** and file location (`file:line`)
- **Responsibility**: what it owns/manages
- **Key exports**: public functions, types, or interfaces
- **Relationships**: what it depends on and what depends on it

Present as a structured list or table.

After presenting:
```
Continue to Chapter 3 (Data/Control Flow)? Or ask me anything about this chapter.
```

---

### Chapter 3 — Data/Control Flow

Trace how data or control moves through the system:
- Entry points: where does the feature get triggered? (API call, event, CLI, import)
- Processing steps: key transformations, decisions, side effects
- Output: what does it produce? Where does the result go?
- Include key function call chains with `file:line` references

Use `Read` to show relevant function signatures and call sites.

After presenting:
```
Continue to Chapter 4 (Key Code Sections)? Or ask me anything about this chapter.
```

---

### Chapter 4 — Key Code Sections

Show the most important code blocks with inline explanation. Focus on:
- Core logic (the implementation heart of the feature)
- Non-obvious algorithms or patterns
- Critical decision points (conditionals, error handling, branching)
- Any surprising or counter-intuitive parts

For each block: show the actual code via `Read`, then explain what it does and why it matters.

After presenting:
```
That completes the guided walk-through.

Would you like an in-depth review? (yes/no)
```

If yes: proceed to step 7.
If no: proceed to step 9 (session summary).

---

## Step 6 — Todo creation (triggered at any point)

When the user says "create a todo for X", "add a todo", or similar during any chapter or between chapters:

**6a. Clarify description if needed**

If the user didn't specify what the todo is about: ask "What should the todo be about?"

**6b. Check proj session**

Call `mcp__plugin_proj_proj__proj_session_context`.
- If the call errors or returns no active project: proj is inactive → go to 6c.
- If proj is active: go to 6d.

**6c. Inactive proj — offer to load**

```
No active proj project. Load one? [Y/n]
```

If yes:
1. Ask "Project name?"
2. Call `mcp__plugin_proj_proj__proj_load_session` with the provided name.
3. On success: call `mcp__plugin_proj_proj__ctx_session_start`.
4. On failure (project not found): report the error and say "Skipping todo creation for this session." Return to the review.

If no: say "Skipping todo creation — no active project." Return to the review.

**6d. Project mismatch warning**

If the active project's root path does not match (or is not a parent of) the path currently being reviewed:
```
Active project is <project_name> but you are reviewing <reviewed_path>.
Todos will be created in <project_name>. Continue? [Y/n]
```
If no: skip todo creation and return to the review.

**6e. Create the todo**

Call `mcp__plugin_proj_proj__todo_add` with:
- `title`: the todo description
- `project_name`: the active project name
- NO `parent` field (always top-level)

Confirm: "Todo created: **<title>**"

Add the title to the session todo list (for step 9 summary).

Return to the chapter where the user was.

---

## Step 7 — In-depth review (triggered after chapter 4 or on user request)

If the user declined in-depth review: skip to step 9 (session summary).

If the user accepted: spawn 2 parallel Task agents. Each agent receives:
- The filtered scoped file list (from step 3)
- Instruction to analyze ONLY those files
- Tools: `Read, Glob, Grep, Bash`

**Agent A — Complexity & Bugs**

> You are a code reviewer. Analyze the provided files for two categories. For each category, report findings OR state "none found" explicitly — both are required outputs.
>
> **Category 1 — Complexity Hotspots**: functions with high cyclomatic complexity, deeply nested conditionals (3+ levels), functions over 50 lines, classes/modules with too many responsibilities, unclear naming that obscures intent.
>
> **Category 2 — Potential Bugs**: off-by-one errors, unchecked return values or errors, race conditions, resource leaks, incorrect error handling, type mismatches, logic errors, missing null/empty checks.
>
> Output format — one row per finding:
> `| <one-line summary> | complexity OR bug | high OR medium OR low | <file>:<line> | <explanation> |`
>
> If no findings in a category, output: `**Complexity Hotspots**: none found` or `**Potential Bugs**: none found`

**Agent B — Dead Code & Test Coverage**

> You are a code reviewer. Analyze the provided files for two categories. For each category, report findings OR state "none found" explicitly — both are required outputs.
>
> **Category 3 — Dead Code**: unused functions, unreachable branches, commented-out code blocks, unused imports, deprecated code with no callers, variables assigned but never read.
>
> **Category 4 — Missing Test Coverage**: public functions without tests, untested error paths, edge cases without test coverage, integration points without tests, untested conditional branches.
>
> Output format — one row per finding:
> `| <one-line summary> | dead-code OR test-coverage | high OR medium OR low | <file>:<line> | <explanation> |`
>
> If no findings in a category, output: `**Dead Code**: none found` or `**Missing Test Coverage**: none found`

---

## Step 8 — Synthesize in-depth report

Wait for both agents to complete.

**Failure handling**: If an agent fails or times out, mark its categories as incomplete:
- Agent A failure → complexity and bug categories: `[INCOMPLETE — manual review needed]`
- Agent B failure → dead-code and test-coverage categories: `[INCOMPLETE — manual review needed]`

Verify all 4 categories have a result (finding row or "none found"). If any category is missing from an agent's output (agent returned but omitted a category), treat it as incomplete.

Display:

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

**"all"**: create todos for every finding (run step 6e for each, reusing active proj session).

**"select"**: display numbered list:
```
1. <finding summary> [<severity>]
2. <finding summary> [<severity>]
...
Enter numbers to create todos (comma-separated, e.g. 1,3):
```
Parse the input and create todos for the selected findings only.

**"no"**: skip todo creation for findings, proceed to step 9.

**Partial write failure**: if a `todo_add` call fails mid-batch, report:
```
Created: <list of titles that succeeded>
Failed: <list of titles that failed> — <error>
```
Then proceed to step 9 regardless.

---

## Step 9 — Session summary

Display at the end of every session (whether or not in-depth review was run, whether or not the user created todos):

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

**If any todos were created AND proj is active**: call `mcp__plugin_proj_proj__tracking_git_flush` with `commit_message="Review: <scope-description>"`.

Session ends here.

---

## Edge Case Reference

These are handled inline at the steps noted — not a separate runtime section:

| Edge Case | Handled At | Behavior |
|-----------|-----------|---------|
| Empty $ARGUMENTS | Step 1 | Prompt user for scope |
| Path not found | Step 2 | Report, ask for alternative path |
| Todo ID not found in proj | Step 2 | Report "not found", continue with remaining scope |
| Zero files after filtering | Step 3 | Warn, ask to broaden scope |
| 50+ files in scope | Step 3 | Summarize count, ask to narrow |
| Symlink cycle | Step 3 | Detect via visited real-path set, skip duplicates |
| Binary/non-text file | Step 3 | Filtered by allowlist — never reaches agents |
| User asks about out-of-scope code | Step 5 | Note it's out of scope, offer to expand |
| User skips chapter | Step 5 | "skip"/"next" keyword → advance |
| Todo creation with no description | Step 6 | Ask "What should the todo be about?" |
| proj_load_session fails | Step 6 | Report error, skip todo creation |
| Proj session mismatches reviewed path | Step 6 | Warn user, ask to confirm before creating |
| In-depth agent fails/times out | Step 8 | Mark its 2 categories as INCOMPLETE |
| Partial bulk todo write failure | Step 8 | Report exactly which succeeded and which failed |
| No todos created, proj active | Step 9 | Skip tracking_git_flush (no-op) |
