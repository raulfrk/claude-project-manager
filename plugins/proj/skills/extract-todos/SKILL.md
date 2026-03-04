---
name: extract-todos
description: Scan source files in all registered repo paths for TODO and FIXME comments and import them as project todos. Supports optional metadata in parentheses (owner, priority, due). Performs fuzzy duplicate detection to update existing todos rather than creating duplicates. Use when the user says "extract todos from code", "import TODOs", or "scan for fixmes".
disable-model-invocation: "true"
allowed-tools: mcp__proj__proj_get_active, mcp__proj__todo_list, mcp__proj__todo_add, mcp__proj__todo_update, mcp__proj__config_load, mcp__claude_ai_Todoist__add-tasks, mcp__claude_ai_Todoist__update-tasks, Bash
argument-hint: "[--dry-run]"
---

Scan registered repo paths for TODO and FIXME comments and create/update project todos.

## Argument Parsing

Parse $ARGUMENTS:
- If `--dry-run` is present: set `dry_run = true`. Print a preview table; make no MCP write calls.
- Otherwise: `dry_run = false`.

## Step 1 — Load Active Project

Call `mcp__proj__proj_get_active`.

- If the call fails or returns no project: exit with "No active project. Run /proj:init or /proj:switch first."
- Extract `repos` from the project metadata (`meta.repos` or the `repos` field on the returned object). This is a list of objects with at least a `path` field.
- If `repos` is empty or null: exit with "No repos registered for this project. Use /proj:save to add a repo path first."
- Store the project name as `project_name` and `todoist_project_id` for optional sync later.

## Step 2 — Load Config

Call `mcp__proj__config_load`.

- Read `todoist.enabled` and `todoist.auto_sync` (both default `false`).
- Read `todoist.mcp_server` (default `"claude_ai_Todoist"`). All Todoist tool calls use `mcp__<todoist_mcp_server>__<tool>` — substitute the actual server name.

## Step 3 — Enumerate and Scan Files

For each repo in `repos`:
- Let `repo_path` = the repo's `path` field (absolute path string).

### File enumeration

Run via Bash:

```bash
cd "<repo_path>" && git ls-files 2>/dev/null
```

- If the command succeeds and outputs lines: use those as the file list (relative to `repo_path`).
- If `git ls-files` fails (exit code non-zero, e.g. not a git repo): fall back to:
  ```bash
  find "<repo_path>" -type f -not -path '*/.git/*' -not -path '*/node_modules/*' -not -path '*/__pycache__/*' -not -path '*/.venv/*'
  ```
  In the fallback case, strip the `repo_path` prefix to get relative paths.

Track total files scanned: `scanned_count`.

### Comment scanning

For each file (up to a reasonable limit — skip binary files, files > 1 MB):

Run via Bash (Python one-liner to scan and emit structured output):

```bash
python3 - <<'PYEOF'
import re, sys, os, json

repo_path = "<repo_path>"
file_rel = "<relative_file_path>"
file_abs = os.path.join(repo_path, file_rel)

pattern = re.compile(
    r'(?i)\b(TODO|FIXME)\s*(?:\(([^)]*)\))?\s*:\s*(.*)'
)

try:
    with open(file_abs, 'r', encoding='utf-8', errors='replace') as f:
        for lineno, line in enumerate(f, 1):
            m = pattern.search(line)
            if m:
                prefix = m.group(1).upper()
                raw_meta = m.group(2) or ''
                title = m.group(3).strip()
                if not title:
                    continue
                print(json.dumps({
                    "file": file_rel,
                    "line": lineno,
                    "prefix": prefix,
                    "raw_meta": raw_meta,
                    "title": title
                }))
except (OSError, UnicodeDecodeError):
    pass
PYEOF
```

In practice, batch the scanning — scan all files in the repo in a single Bash call to avoid N shell invocations. Use a Python script that reads a list of files and emits one JSON line per match:

```bash
python3 - <<'PYEOF'
import re, sys, os, json, subprocess

repo_path = "<repo_path>"
pattern = re.compile(r'(?i)\b(TODO|FIXME)\s*(?:\(([^)]*)\))?\s*:\s*(.*)')

# Get file list
result = subprocess.run(['git', 'ls-files'], capture_output=True, text=True, cwd=repo_path)
if result.returncode == 0:
    files = [f for f in result.stdout.splitlines() if f]
else:
    files = []
    for root, dirs, filenames in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in {'.git', 'node_modules', '__pycache__', '.venv'}]
        for fn in filenames:
            abs_path = os.path.join(root, fn)
            files.append(os.path.relpath(abs_path, repo_path))

results = {"scanned": 0, "matches": []}

for file_rel in files:
    file_abs = os.path.join(repo_path, file_rel)
    if not os.path.isfile(file_abs):
        continue
    try:
        size = os.path.getsize(file_abs)
        if size > 1_000_000:
            continue
        with open(file_abs, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        if '\x00' in content[:512]:
            continue  # binary file
        results["scanned"] += 1
        for lineno, line in enumerate(content.splitlines(), 1):
            m = pattern.search(line)
            if m:
                title = m.group(3).strip()
                if not title:
                    continue
                results["matches"].append({
                    "file": file_rel,
                    "line": lineno,
                    "prefix": m.group(1).upper(),
                    "raw_meta": m.group(2) or '',
                    "title": title
                })
    except (OSError, UnicodeDecodeError):
        pass

print(json.dumps(results))
PYEOF
```

Collect all matches across all repos. Accumulate `scanned_count` and `found_count`.

## Step 4 — Parse Metadata

For each match, parse `raw_meta` into structured fields:

```python
# Parse: "owner: Alice, priority: high, due: 2026-06-01"
meta = {}
for part in raw_meta.split(','):
    part = part.strip()
    if ':' in part:
        k, v = part.split(':', 1)
        meta[k.strip().lower()] = v.strip()
```

Map fields:
- `meta.get('priority')` → todo `priority`. Valid values: `high`, `medium`, `low`. Anything else (or absent) → `medium`.
- `meta.get('owner')` → tag string `owner:<value>`. Add to `tags` list.
- `meta.get('due')` → `due_date` (ISO date string, e.g. `"2026-06-01"`). Pass as-is; the MCP server validates format.
- `file:line` → `notes` = `"Source: <file_rel>:<lineno>"`

Build a structured record per match:
```
{
  title: <str>,
  priority: <"high"|"medium"|"low">,
  tags: <list[str]>,       # e.g. ["owner:Alice"]
  due_date: <str|null>,
  notes: "Source: <file>:<line>"
}
```

## Step 5 — Load Existing Todos for Deduplication

Call `mcp__proj__todo_list` with no filters (returns pending + in_progress todos).

Build a list of `{id, title}` pairs from the result for duplicate detection.

## Step 6 — Duplicate Detection and Create/Update

For each extracted todo record:

**Exact match** (case-insensitive): check if any existing todo title equals the extracted `title` (case-insensitive string comparison). If found → this is an update candidate.

**Fuzzy match** (if no exact match): for each existing todo, compute `difflib.SequenceMatcher(None, extracted_title.lower(), existing_title.lower()).ratio()`. If the maximum ratio >= 0.85, that existing todo is a fuzzy match.

Run this via Bash:

```bash
python3 - <<'PYEOF'
import difflib, json, sys

extracted_title = "<title>"
existing_todos = <json_list_of_{id,title}_pairs>

best_id = None
best_ratio = 0.0

for t in existing_todos:
    ratio = difflib.SequenceMatcher(None, extracted_title.lower(), t['title'].lower()).ratio()
    if ratio >= 0.85 and ratio > best_ratio:
        best_ratio = ratio
        best_id = t['id']

print(json.dumps({"match_id": best_id, "ratio": best_ratio}))
PYEOF
```

In practice, batch all duplicate detection in a single Python call across all matches to avoid repeated shell invocations.

**Decision**:
- **Match found** (exact or fuzzy): call `mcp__proj__todo_update` with the matched todo ID, updated `notes`, and any metadata fields that differ (priority, tags, due_date). Track as `updated_count += 1`.
- **No match**: call `mcp__proj__todo_add` with `title`, `priority`, `tags`, `due_date`, `notes`. Track as `created_count += 1`.

**In dry-run mode**: skip all `todo_add` and `todo_update` calls. Instead, collect preview rows:

```
| Action | Title | Priority | Tags | Due | Source |
|--------|-------|----------|------|-----|--------|
| CREATE | Fix null pointer | medium | | | src/main.py:42 |
| UPDATE (2.3) | Refactor auth | high | owner:Raul | 2026-06-01 | auth.go:99 |
```

Print the table at the end and skip steps 7 and 8.

## Step 7 — Todoist Sync (if enabled)

If `todoist.enabled AND todoist.auto_sync AND NOT dry_run`:

For each **newly created** todo (from step 6 `todo_add` results):
- If the `todo_add` response includes a `todoist_task_id` already set: skip.
- Otherwise: call `mcp__<todoist_mcp_server>__add-tasks` with:
  - `content`: todo title
  - `priority`: mapped (high→p2, medium→p3, low→p4)
  - `labels`: tags list
  - `projectId`: `todoist_project_id`
  - `dueString`: `due_date` if set (omit the field entirely if `due_date` is null)
- Call `mcp__proj__todo_update` with the new local todo ID and `todoist_task_id` = returned Todoist task ID.

For each **updated** todo (from step 6 `todo_update` calls) where the todo has an existing `todoist_task_id`:
- Call `mcp__<todoist_mcp_server>__update-tasks` with:
  - `id`: existing `todoist_task_id`
  - `content`: title (if changed)
  - `priority`: mapped priority (if changed)
  - `labels`: full replacement tags list (if changed)
  - `dueString`: `due_date` if set; omit entirely if `due_date` is null (do NOT send an empty string)

## Step 8 — Summary

After scanning (or preview in dry-run mode), print:

```
Scanned <scanned_count> files. Found <found_count> TODO/FIXME comments. Created <created_count>, updated <updated_count>.
```

In dry-run mode: prepend `[dry-run] ` to the summary line and omit created/updated counts (replace with the count of what would be created/updated from the preview table).

Example:
```
Scanned 142 files. Found 7 TODO/FIXME comments. Created 5, updated 2.
```

Dry-run example:
```
[dry-run] Scanned 142 files. Found 7 TODO/FIXME comments. Would create 5, update 2.
```

---

## Notes and Edge Cases

- **No title after prefix**: skip the match entirely (title is empty after stripping).
- **Unrecognized metadata keys**: silently ignore them (only `owner`, `priority`, `due` are recognized).
- **Invalid priority value**: treat as `medium` with no warning.
- **Invalid `due` date format**: pass through to `todo_add`/`todo_update` as-is; the MCP server returns an error if the format is malformed. Report the error and continue to the next match.
- **Binary files**: skip files where the first 512 bytes contain a null byte.
- **Large files**: skip files > 1 MB.
- **Fuzzy match conflict** (multiple existing todos near 0.85 threshold): pick the one with the highest ratio. If tied, pick the first (lowest ID).
- **Multiple matches in same file**: each is treated independently.
- **Same title in multiple files**: each match is checked for duplicates against existing todos independently. If the first one creates a new todo, subsequent matches from other files may fuzzy-match that newly created todo — but since `todo_list` is fetched once before the loop, subsequent matches will not see the just-created todo. This means the same logical TODO in two files creates two separate todos. This is acceptable behaviour.

💡 Suggested next: /proj:todo list — review extracted todos  |  /proj:status — see full project overview
