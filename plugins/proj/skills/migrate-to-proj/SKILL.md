---
name: migrate-to-proj
description: Migrate an existing project directory into proj tracking. Detects and imports tasks (TODOS.md, todo.yaml, legacy ~/.project-tracker/), notes (NOTES.md), and design/doc files (CLAUDE.md, architecture docs, diagrams). Use when the user says "migrate project", "import existing project", or "migrate-to-proj".
disable-model-invocation: "true"
allowed-tools: mcp__proj__config_load, mcp__proj__proj_get, mcp__proj__proj_init, mcp__proj__proj_set_active, mcp__proj__todo_add, mcp__proj__todo_complete, mcp__proj__notes_append, Bash, Read
argument-hint: "[path]"
---

Migrate an existing project directory into proj tracking: $ARGUMENTS

## 1. Load config and resolve primary path

Call `mcp__proj__config_load` to get `tracking_dir` and `projects_base_dir`.

If `$ARGUMENTS` is non-empty, use it as the primary path. Otherwise ask:
> "What is the path to the project directory to migrate?"

Expand `~` and resolve to an absolute path using Bash:
```bash
eval echo "<path>"
```

Check the path exists:
```bash
test -d "<resolved_path>" && echo "exists" || echo "missing"
```
If missing, stop with: `Directory <path> not found. Please check the path and try again.`

## 2. Ask for additional directories

Ask:
> "Are there any additional directories that also contain tracking information for this project? (comma-separated paths, or press Enter to skip)"

If the user provides paths, resolve and validate each one (skip any that don't exist with a warning). Collect all valid paths into `all_dirs = [primary_path, ...additional_paths]`.

## 3. Detect tracking files

For each directory in `all_dirs`, scan for supported files using Bash:

```bash
find "<dir>" -maxdepth 3 \( \
  -iname "TODOS.md" -o -iname "TODO.md" -o \
  -iname "NOTES.md" -o -iname "notes.md" -o \
  -name "todos.yaml" \
\) -not -path "*/.git/*" -not -path "*/.proj-migrate-backup*" 2>/dev/null
```

Also scan for design/doc files:
```bash
find "<dir>" -maxdepth 3 \( \
  -name "CLAUDE.md" -o -name "requirements.md" -o -name "research.md" -o \
  -iname "architecture.md" -o -iname "design.md" -o -iname "ARCHITECTURE.md" -o \
  -name "*.excalidraw" -o -name "*.mmd" -o -name "*.mermaid" \
\) -not -path "*/.git/*" -not -path "*/.proj-migrate-backup*" 2>/dev/null
```

Also check for legacy `~/.project-tracker/` YAML:
```bash
ls ~/.project-tracker/ 2>/dev/null | head -20
```

Collect:
- `task_files`: list of TODOS.md / TODO.md / todos.yaml paths found
- `notes_files`: list of NOTES.md / notes.md paths found
- `design_files`: list of design/doc/diagram files found
- `legacy_projects`: list of project names in `~/.project-tracker/` (if any)

## 4. Parse task files

For each file in `task_files`:

**Markdown checklist (TODOS.md / TODO.md):** Read the file and extract checklist items:
- `- [ ] Task title` → status: pending
- `- [x] Task title` or `- [X] Task title` → status: done
- Ignore indented items (flatten all to root level — sub-task hierarchy is out of scope in v1)
- Ignore non-checklist lines
- Ignore empty titles

**todos.yaml:** Read and parse the `todos:` list. Extract title and status for each entry.

**Legacy `~/.project-tracker/<name>/`:** Read YAML files; extract task titles and statuses.

Collect all parsed items into `detected_todos: list[{title, status, source_file}]`.

## 5. Display preview

Show a formatted preview of everything detected:

```
Detected in <primary_path> [+ N additional dirs]:

📋 Tasks (<N> total — X pending, Y done):
  ✅ Done task title  [from TODOS.md]
  🔲 Pending task title  [from TODOS.md]
  ... (show up to 10; summarise if more)

📝 Notes files: NOTES.md [from <path>]

📁 Design/doc files (<N>):
  - CLAUDE.md
  - architecture.md
  - diagram.excalidraw
  ...
```

If nothing was detected at all, show:
> "No tracking files found in the specified directories. Nothing to migrate."
> Stop.

## 6. Check if project already tracked

Infer a project name from the primary path's directory name (e.g. `/home/user/projects/my-app` → `my-app`).

Call `mcp__proj__proj_get` with the inferred name. Parse the result:

**If result contains "not found"** — project is not yet tracked:
- Ask: `Project name: [<inferred-name>]` (press Enter to accept default)
- Ask: `Description (optional):`
- Ask: `Tags (optional, comma-separated):`
- Set `init_needed = true`, `project_name = <confirmed name>`

**If result is JSON** — project already tracked:
- Show: `Project '<name>' is already tracked by proj.`
- Ask: `Merge imported data into existing project? [yes/no]`
  - If no: stop with `Migration aborted.`
  - If yes: set `init_needed = false`, `project_name = <existing name>`

## 7. Confirm before migrating

Show:
```
Ready to migrate into project '<name>':
  • Import <N> todos (<X> pending, <Y> done)
  • Append <N> notes files
  • Copy <N> design/doc files → <tracking_dir>/<name>/docs/
  • Move originals → <primary_path>/.proj-migrate-backup-<timestamp>/
  <• Initialize new proj project '<name>'> (if init_needed)

Proceed? [yes/no]
```

If no: stop with `Migration aborted.`

## 8. Execute migration

Generate timestamp: `date +%Y%m%d-%H%M%S`

**8a. Create backup:**
```bash
mkdir -p "<primary_path>/.proj-migrate-backup-<timestamp>"
```
For each file in `task_files + notes_files`, move it into the backup folder:
```bash
mv "<file>" "<primary_path>/.proj-migrate-backup-<timestamp>/"
```

**8b. Initialize project (if `init_needed`):**
Call `mcp__proj__proj_init` with `name`, `path=<primary_path>`, `description`, `tags` (as list).

**8c. Import todos:**
For each item in `detected_todos`:
- Skip if title is empty or whitespace
- Call `mcp__proj__todo_add` with `title`, `project_name=<project_name>`
  - Note the returned todo ID (parse from `"Added todo <id>: ..."`)
- If `status == "done"`: immediately call `mcp__proj__todo_complete` with the returned ID and `project_name`
- Show progress: `Importing todo <n>/<total>...`

**8d. Append notes:**
For each file in `notes_files`:
- Read the file content
- Call `mcp__proj__notes_append` with:
  ```
  ## <YYYY-MM-DD> — Migrated from <filename>

  <file content>
  ```
  and `project_name=<project_name>`

**8e. Copy design/doc files:**
Create the docs directory:
```bash
mkdir -p "<tracking_dir>/<project_name>/docs"
```
For each file in `design_files`:
```bash
cp "<file>" "<tracking_dir>/<project_name>/docs/"
```

## 9. Activate and summarise

Call `mcp__proj__proj_set_active` with `project_name` to set as active project.

Call `mcp__proj__notes_append` with a migration summary note:
```
## <YYYY-MM-DD> — migrate-to-proj

Migrated from: <primary_path>
Todos imported: <N> (<X> pending, <Y> done)
Notes appended: <N> files
Design docs copied: <N> files
Backup location: <primary_path>/.proj-migrate-backup-<timestamp>/
```

Show final summary:
```
✅ Migration complete — project '<name>' is now active.

  📋 Todos:   <N> imported (<X> pending, <Y> done)
  📝 Notes:   <N> files appended
  📁 Docs:    <N> files copied to <tracking_dir>/<name>/docs/
  💾 Backup:  <primary_path>/.proj-migrate-backup-<timestamp>/
```

💡 Suggested next: (1) /proj:status — see the migrated project overview  (2) /proj:sync — sync todos to Todoist
