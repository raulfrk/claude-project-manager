---
name: explore
description: Walk through a codebase feature or code section in guided chapters, explaining structure and logic. Use when asked "explore src/auth/", "walk me through X", or "explain the hook system".
allowed-tools: Read, Glob, Grep, Bash, mcp__plugin_proj_proj__proj_session_context, mcp__plugin_proj_proj__content_get_requirements
argument-hint: "[<todo-id> | <path> | <description>] (any combination)"
---

Walk through a codebase feature or section with the user in guided chapters. Explain the structure and logic, answer questions inline.

To create todos or run in-depth review, use `/analyse:review` instead.

---

## Step 1 — Parse $ARGUMENTS

Extract from `$ARGUMENTS`:
- **Todo IDs**: tokens matching `^\d+(\.\d+)*$` (e.g. `42`, `3.1`, `397.2`)
- **Paths**: tokens starting with `/`, `./`, `~/`, or containing a `/` followed by a file extension (e.g. `src/auth/`, `./plugins/hooks/`)
- **Description**: all remaining tokens joined as free-form text

If `$ARGUMENTS` is empty: ask the user "What would you like to explore? You can provide a file path, directory, description, or a proj todo ID."

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

To create todos or run in-depth review, use `/analyse:review` instead.

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
That completes the guided exploration.
```

Proceed to step 6 (exploration summary).

---

## Step 6 — Exploration summary

Display at the end of every session:

```
### Exploration Summary

**Scope**: <scope description>
**Files explored**: <N> files
**Chapters completed**: <list of chapters presented>
```

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
| Binary/non-text file | Step 3 | Filtered by allowlist — never reaches chapters |
| User asks about out-of-scope code | Step 5 | Note it's out of scope, offer to expand |
| User skips chapter | Step 5 | "skip"/"next" keyword — advance |
