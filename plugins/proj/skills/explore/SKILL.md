---
name: explore
description: Walk through a codebase feature or code section in guided chapters, explaining structure and logic. Use when asked "explore src/auth/", "walk me through X", or "explain the hook system".
allowed-tools: Read, Glob, Grep, Bash, mcp__plugin_proj_proj__proj_session_context, mcp__plugin_proj_proj__content_get_requirements
argument-hint: "[<todo-id> | <path> | <description>] (any combination)"
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Walk through codebase feature/section in guided chapters. Explain structure/logic, answer questions inline.

Todos or in-depth review → `/proj:review`.


## Step 1 — Parse $ARGUMENTS

Extract from `$ARGUMENTS`:
- Todo IDs: tokens matching `^\d+(\.\d+)*$` (e.g. `42`, `3.1`, `397.2`)
- Paths: tokens starting w/ `/`, `./`, `~/`, or containing `/` + file extension
- Description: remaining tokens joined as free-form text

Empty `$ARGUMENTS` → ask "What to explore? Provide file path, dir, desc, or proj todo ID."


## Step 2 — Resolve scope

Build raw file list from all three input types:

### Todo IDs
Each todo ID:
1. `mcp__plugin_proj_proj__proj_session_context`
2. Proj active → `mcp__plugin_proj_proj__content_get_requirements` w/ todo ID. Extract file paths, dirs, module names from requirements text. Add to raw file list.
3. Proj inactive OR content empty → fall back to Grep + Glob via todo title keywords.
4. "not found" err → report "Todo ID `<id>` not found — skipping." Continue.

### Paths
Each path: `Glob` (as-is or w/ `/**/*` for dirs). Zero matches → report "Path `<path>` not found. Provide alternative." Wait for response.

### Description
Extract 2-4 keywords. Grep codebase for each. Glob for keyword-derived patterns (e.g. `**/*auth*.*`). Collect matches; deduplicate.


## Step 3 — Filter file list

**Source extension allowlist**:
`.py`, `.ts`, `.tsx`, `.js`, `.jsx`, `.go`, `.java`, `.rb`, `.rs`, `.c`, `.cpp`, `.h`, `.md`, `.yaml`, `.yml`, `.json`, `.toml`, `.sh`

**Exclude patterns** (drop if path contains):
`node_modules/`, `__pycache__/`, `.git/`, `dist/`, `build/`, `.venv/`, `*.lock`, `*.png`, `*.jpg`, `*.gif`, `*.svg`, `*.pyc`, `*.whl`, `*.min.js`, `*.map`

**Symlinks**: resolve via `Bash: readlink -f <path>`. Track visited real paths; skip duplicates (cycle detection).

**After filtering**:
- Zero files → warn "No source files after filtering. Broaden scope." Ask user.
- 50+ files → summarize count, ask "That's <N> files — narrow scope?"


## Step 4 — Announce scope, confirm

```
I'll walk you through **<N> files** covering: <scope description>

Files in scope:
- <file1>
- <file2>
- ...

Ready to start? (yes / change scope)
```

User says "change scope" → return step 1, re-parse new input.

Confirmed → step 5.


## Step 5 — Guided chapters

Present one chapter at time. Do NOT advance until user explicitly continues.

Todos or in-depth review → `/proj:review`.


### Chapter 1 — Overview

Read scoped files via `Read`. Produce high-level summary:
- What does feature do? What problem solved?
- How fits in broader system? What calls in, what it calls?
- File map: one line per file w/ role

After presenting:
```
Continue to Chapter 2 (Component Breakdown)? Or ask me anything about this chapter.
```

**User interaction rules (all chapters):**
- Question → answer inline via `Read`/`Grep`. Stay in chapter.
- Requests specific code → show via `Read`. Stay in chapter.
- "skip"/"next"/"continue" → advance.
- "go back" → prev chapter.


### Chapter 2 — Component Breakdown

Identify main components/modules/classes/subsystems. Each:
- Name + file location (`file:line`)
- Responsibility
- Key exports: public fns, types, interfaces
- Relationships: deps in/out

Present as structured list or table.

After presenting:
```
Continue to Chapter 3 (Data/Control Flow)? Or ask me anything about this chapter.
```


### Chapter 3 — Data/Control Flow

Trace data/control flow:
- Entry points: API call, event, CLI, import
- Processing: key transformations, decisions, side effects
- Output: what produced, where result goes
- Key fn call chains w/ `file:line` refs

Show relevant fn signatures/call sites via `Read`.

After presenting:
```
Continue to Chapter 4 (Key Code Sections)? Or ask me anything about this chapter.
```


### Chapter 4 — Key Code Sections

Show important code blocks w/ inline explanation. Focus on:
- Core logic (impl heart)
- Non-obvious algorithms/patterns
- Critical decision points (conditionals, err handling, branching)
- Surprising/counter-intuitive parts

Each block: show code via `Read`, explain what/why.

After presenting:
```
That completes the guided exploration.
```

→ step 6.


## Step 6 — Exploration summary

```
### Exploration Summary

**Scope**: <scope description>
**Files explored**: <N> files
**Chapters completed**: <list of chapters presented>
```

Session ends.


## Edge Cases

| Edge Case | Step | Behavior |
|-----------|------|----------|
| Empty $ARGUMENTS | 1 | Prompt for scope |
| Path not found | 2 | Report, ask alternative |
| Todo ID not found | 2 | Report, continue w/ remaining |
| Zero files after filter | 3 | Warn, ask broaden |
| 50+ files | 3 | Summarize count, ask narrow |
| Symlink cycle | 3 | Detect via visited set, skip dupes |
| Binary/non-text | 3 | Filtered by allowlist |
| Out-of-scope question | 5 | Note out of scope, offer expand |
| User skips chapter | 5 | "skip"/"next" → advance |
