---
name: explore
description: Explore and map a project's codebase — scans directory structure, tech stack, entry points, README, and config files. Writes a summary to CLAUDE.md and key findings to NOTES.md. Use when the user says "explore this repo", "map the codebase", "scan this project", or "update CLAUDE.md from code".
disable-model-invocation: "true"
allowed-tools: mcp__proj__config_load, mcp__proj__proj_get_active, mcp__proj__proj_explore_codebase, mcp__proj__claudemd_read, mcp__proj__claudemd_write, mcp__proj__notes_append
argument-hint: "[path]"
---

Explore and map the codebase at the given path. $ARGUMENTS may contain a directory path (optional).

1. Load config via `mcp__proj__config_load`. Get active project via `mcp__proj__proj_get_active`.

2. Determine target path:
   - If $ARGUMENTS is non-empty, use that as the path
   - Otherwise, use the active project's content path (from proj_get_active → `repos[0].path` or `path` field)
   - Confirm: "Exploring `<path>` …"

3. Run exploration:
   - Call `mcp__proj__proj_explore_codebase` with `path=<target_path>`.
   - This returns JSON with: `tech_stack`, `entry_points`, `key_dirs`, `config_files`, `file_types`, `file_tree`, `arch_note`.

4. Synthesize findings from the returned data:
   - Primary language(s) and framework(s) — from `tech_stack`
   - Key directories and their purpose — from `key_dirs`
   - Entry points and main modules — from `entry_points`
   - Notable config / tooling — from `config_files`
   - Architecture summary (1–3 sentences) — use `arch_note` as a starting point

5. **Write CLAUDE.md**:
   - Call `mcp__proj__claudemd_read` with the target path to check for an existing CLAUDE.md.
   - If it **exists**: merge — preserve ALL existing sections verbatim, then add or update an
     `## Architecture` section and a `## Key Files` section with the new exploration findings.
     Do not duplicate content that is already present.
   - If it **does not exist**: create from scratch:
     ```markdown
     # <project-name>

     **Status**: active
     **Tracking**: ~/projects/tracking/<name>

     ## Overview
     <1–2 sentence description synthesised from README or inferred from code>

     ## Architecture
     <tech stack, key dirs, entry points — 3–8 bullet points>

     ## Key Files
     <notable files with brief descriptions — 3–8 bullet points>
     ```
   - Call `mcp__proj__claudemd_write` with the final content.

6. **Append to NOTES.md** — call `mcp__proj__notes_append` with:
   ```
   ## Repo Exploration — <date>

   **Tech stack**: <languages, frameworks>
   **Entry points**: <list>
   **Key dirs**: <list>
   **Config**: <notable config files>
   **Architecture note**: <1–2 sentences>
   ```

7. Confirm: "Exploration complete. CLAUDE.md updated and findings appended to NOTES.md."

💡 Suggested next: (1) /proj:status — see full project status  (2) /proj:todo add — add todos based on findings
