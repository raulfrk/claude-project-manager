---
name: review-to-todo
description: Convert review findings into todos. Iterates pending findings with full context and asks the user to create a todo, skip, edit-then-create, or stop. Use when asked "turn findings into todos", "create todos from review", or "process review findings".
disable-model-invocation: "true"
allowed-tools: Read, Edit, mcp__proj__todo_add
argument-hint: "<path-to-review-file>"
---

Convert pending review findings into todos from: $ARGUMENTS

## Step 1 — Load and validate the review file

1. If `$ARGUMENTS` is empty, stop and report: "No review file path provided. Usage: `/claude-helper:review-to-todo <path-to-review-file>`"
2. Call `Read` with the path from `$ARGUMENTS`.
3. If the file cannot be read, stop and report: "Cannot read review file at <path>: <error>. Provide the correct absolute path to a review file."
4. Parse the YAML frontmatter (the content between the opening `---` and closing `---` delimiters). Extract the `findings` array and all top-level fields (`type`, `reviewed_file`, `reviewed_name`, `date`, `overall_score`, `band`, `criterion_scores`).
5. If the YAML frontmatter cannot be parsed, stop and report: "Review file is malformed or missing YAML frontmatter. Verify the file was created by the review-skill or review-agent."
6. If the `findings` array is missing or not a list, stop and report: "Review file has no findings array. Nothing to process."
7. Store the full file content and parsed frontmatter in memory. Do not call `Read` again until Step 3c requires a re-read.

## Step 2 — Filter pending findings

1. Iterate through the `findings` array from the frontmatter.
2. Collect only findings where `status` equals `pending`. Skip findings where `status` is `added`, `skipped`, or any other value.
3. Also skip any "no issues found" placeholder findings (those with `severity: null` or missing `title`).
4. Count the total number of pending findings. Store this as `total`.
5. If `total` is zero, report: "All findings have been processed. Review complete." and stop. This is not an error.

## Step 3 — Iterate findings and prompt the user

Initialize counters: `added = 0`, `skipped = 0`, `processed = 0`.

For each pending finding in order:

### Step 3a — Display full finding context

Display exactly this format:

```
---
Finding <N>/<total>: <title>
File: <file>
Location: <location>
Criterion: <criterion> | Severity: <severity>/5 | Confidence: <confidence>/5

Detail:
<detail>

Suggestion:
<suggestion>

Progress: <processed> processed, <added> added, <skipped> skipped, <remaining> remaining

Options:
  1. Create todo
  2. Skip
  3. Edit todo title, then create
  4. Stop reviewing
---
```

Where:
- `<N>` is the 1-based index of this finding among pending findings
- `<total>` is the total count of pending findings
- `<file>` is the `file` field from the finding (absolute path)
- `<location>` is the `location` field (e.g., "Step 4" or "line 23")
- `<criterion>` is the `criterion` field (e.g., "C1")
- `<severity>` and `<confidence>` are integer values from the finding
- `<detail>` is the full `detail` text
- `<suggestion>` is the `suggestion` text. If the finding has no `suggestion` field, omit the "Suggestion:" line and its content entirely.
- `<remaining>` is `total - processed`

Wait for the user to choose an option before proceeding.

### Step 3b — Execute the user's choice

**Option 1 — Create todo:**
1. Call `mcp__proj__todo_add` with:
   - `title`: the finding's `title` field verbatim
   - `notes`: formatted as:
     ```
     [<criterion> | Severity <severity>/5 | Confidence <confidence>/5]

     <detail>

     Suggestion: <suggestion>
     ```
     Omit the "Suggestion: ..." line if the finding has no `suggestion` field.
2. Parse the returned todo ID from the response (the response contains text like "Created todo X. ID: X").
3. Set `decision_status = "added"` and `decision_todo_id = <returned todo ID>`.
4. Increment `added` by 1.

**Option 2 — Skip:**
1. Set `decision_status = "skipped"` and `decision_todo_id = null`.
2. Increment `skipped` by 1.

**Option 3 — Edit todo title, then create:**
1. Ask the user: "Enter revised todo title (or press Enter to keep the original):"
2. Wait for the user's response.
3. If the user provides a non-empty response, use it as the todo title. Otherwise, use the finding's `title` field.
4. Call `mcp__proj__todo_add` with the chosen title and the same `notes` format as Option 1.
5. Parse the returned todo ID.
6. Set `decision_status = "added"` and `decision_todo_id = <returned todo ID>`.
7. Increment `added` by 1.

**Option 4 — Stop:**
1. Skip all remaining findings. Do not process them.
2. Proceed directly to Step 4 (final summary).

If `mcp__proj__todo_add` fails, report: "Warning: Could not create todo: <error>. Continuing to next finding." Set `decision_status = "added"` and `decision_todo_id = "error"`. Do not halt the loop.

### Step 3c — Update the review file

After each decision (options 1, 2, or 3):

1. Call `Read` to re-read the review file from disk (to avoid conflicts if edited externally).
2. Parse the YAML frontmatter again.
3. Locate the finding in the `findings` array by matching the `id` field (e.g., "F1", "F2").
4. Update the finding's fields:
   - Set `status` to `decision_status` (either `"added"` or `"skipped"`)
   - Set `todo_id` to `decision_todo_id` (either the todo ID string or `null`)
5. Rebuild the YAML frontmatter with the updated finding. Preserve all other fields and the markdown body unchanged.
6. Call `Edit` to write the updated frontmatter back to the file.
7. Increment `processed` by 1.
8. Display: "Processed <processed>/<total>: <added> added, <skipped> skipped"

If the file update fails, report: "Warning: Could not persist this decision to the review file. Continuing." Increment `processed` by 1 and continue to the next finding. Do not halt the loop.

Then return to Step 3a for the next pending finding.

## Step 4 — Final summary

After all pending findings are processed (or the user chose Stop):

```
Review-to-todo complete:
  - Processed: <processed> findings
  - Todos created: <added>
  - Skipped: <skipped>
  - Remaining: <total - processed> (unprocessed)
  - Created todo IDs: <comma-separated list of all todo IDs created, or "none">
```

Do not call any tools after displaying this summary.

Suggested next: (1) `/claude-helper:resume-review <path>` — revisit and discuss remaining findings interactively  (2) `/proj:todo list` — view the newly created todos
