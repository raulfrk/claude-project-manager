---
name: save
description: Save session notes, reconcile git activity with todos, and update project context. Use when asked "save session", "proj:save", or at the end of a work session.
allowed-tools: mcp__proj__proj_session_context, mcp__proj__notes_append, mcp__proj__proj_git_reconcile_todos, mcp__proj__todo_complete, mcp__proj__claudemd_write, mcp__proj__tracking_git_flush, mcp__proj__proj_decision_log, mcp__proj__config_load, mcp__plugin_wiki_wiki__wiki_scope_detect, Task, Read, Bash, Write
argument-hint: "[free-form session note]"
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Save session ctx; reconcile git activity for active project.

**1.** `mcp__proj__proj_session_context` → extract `project.name`, `config.tracking_dir`.

**2.** Git reconciliation (if git_enabled):
 - `mcp__proj__proj_git_reconcile_todos(since_days=1)` to detect recent commits.
 - Suggestions returned → display. Each todo looking completed per commit msgs, ask user to confirm. `mcp__proj__todo_complete` for confirmed.
 - No suggestions → skip silently.

**3.** Note from `$ARGUMENTS`:
 - `$ARGUMENTS` empty → no user note; skip to step 4.
 - `$ARGUMENTS` non-empty → use the full string verbatim as the user note; include under "## User Note" in step 7's template.

**4.** Synthesise session content from conversation. Extract:
 - Key Decisions: choices made this session
 - Todos Worked On: todo IDs touched + outcomes
 - Insights Discovered: technical findings, patterns, gotchas
 - Open Questions: unresolved items for next session

 User provided note in step 3 → include under "## User Note".

**5.** Determine session filename:
 - `date +%Y-%m-%d` → today's date
 - `ls <tracking_dir>/<name>/sessions/session-<date>*.md 2>/dev/null | wc -l` → count
 - Count 0 → `session-<date>.md`; count ≥1 → `session-<date>-<count+1>.md`

**6.** `mkdir -p <tracking_dir>/<name>/sessions`

**7.** Write session file via Write tool to `<tracking_dir>/<name>/sessions/<filename>`:

   ```
   # Session: <date>

   ## User Note
   <only if user provided something>

   ## Key Decisions
   - <bullet>

   ## Todos Worked On
   - <bullet with todo ID and outcome>

   ## Insights Discovered
   - <bullet>

   ## Open Questions
   - <bullet>
   ```

**8.** Knowledge bridge — extract Key Decisions from step 7:
 - No decisions → skip silently.
 - Each decision: `mcp__proj__proj_decision_log(action="add", decision=<text>, context="Extracted from session <filename>", tags="session-extracted")`.
 - Append to `<tracking_dir>/<name>/knowledge.md` via Write (create/append):
     ```
     ## <YYYY-MM-DD>
     - decision 1
     - decision 2
     ```
 File exists → read first, append new section at end.

**9.** Update CLAUDE.md (if project has repos w/ claudemd=true):
 - `mcp__proj__claudemd_write` to update active todos section.

**10.** `mcp__proj__notes_append` w/ one-line summary.

**11.** Wiki auto-ingest (if enabled):
 - `mcp__proj__config_load` → check `sync.wiki.enabled` + `sync.wiki.auto_ingest_sessions`.
 - Both false → skip silently.
 - Both true → spawn forked subagent via `Task`:
     - `subagent_type="general-purpose"`
     - `description="Wiki ingest session file"`
     - `prompt` = contents of `plugins/wiki/skills/ingest/references/subagent-prompt.md` (read via `Read`) w/ `{source}` = `session:<tracking_dir>/<name>/sessions/<filename>`, `{scope}` = `project:<name>` (from step 1), `{wiki_config}` = JSON of `~/.claude/wiki.yaml` + `~/.claude/wiki/config.yaml` (read via `Read`).
 - Subagent success → "Wiki ingest: N pages created, M updated."
 - Subagent failure → warn: "Wiki ingest failed: <err>. Session file saved. Retry manually via `/wiki:ingest session:<path>`." + continue.

**12.** "Session saved to sessions/<filename>"

**13.** Git tracking flush: `mcp__proj__tracking_git_flush(commit_message="Save: session")`.

## Prerequisites

Active project must be loaded.

## Err Handling

- No active project → display err from `proj_session_context`, stop.
- Git reconciliation err → skip silently, continue.
- Session file write err → display err, stop.
- CLAUDE.md write err → log warning, continue.

## Output

`Session saved to sessions/<filename>`. Git reconciliation suggestions (if any). Session file w/ key decisions, todos, insights, open questions.

## Usage

- `/proj:save` → save w/o user note. No prompt.
- `/proj:save <free-form note>` → save w/ user note = the full argument string.
