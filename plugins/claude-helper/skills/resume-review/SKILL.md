---
name: resume-review
description: Load a saved review file and continue the interactive finding-by-finding loop from the first pending finding. Use when asked "resume review", "continue review", or "resume-review <file>".
disable-model-invocation: "true"
allowed-tools: Read, Write, mcp__proj__todo_add
argument-hint: "<path-to-review-file>"
---

Resume an interactive review from the saved review file at: $ARGUMENTS

## Step 1 — Load and parse the review file

Call `Read` with the path from `$ARGUMENTS`.

If the file does not exist or cannot be read, stop and report: "Cannot read review file at <path>: <error>. Provide the correct absolute path to a review file."

Parse the file content:

1. The file has YAML frontmatter between `---` delimiters at the top, followed by a markdown body.
2. Split the content on the `---` markers. The frontmatter is the YAML block between the first `---` and the second `---`. Everything after the second `---` is the markdown body.
3. Parse the YAML frontmatter. Extract these fields:
   - `type` (string: "skill" or "agent")
   - `reviewed_file` (string: absolute path)
   - `reviewed_name` (string: slug)
   - `date` (string: YYYY-MM-DD)
   - `overall_score` (float)
   - `band` (string)
   - `criterion_scores` (dict)
   - `findings` (list of finding objects)

If parsing fails (malformed YAML, missing `---` delimiters, or missing `findings` array), stop and report: "Cannot parse review file <path>: YAML frontmatter is malformed or missing required fields. Provide a valid review file."

Store the parsed frontmatter, the findings array, and the markdown body separately in memory. You will need all three to reconstruct the file after updates.

## Step 2 — Filter pending findings and initialize counters

From the `findings` array, collect all findings where `status` equals `"pending"`. Preserve their original order (ranked by severity x confidence descending, as produced by the review skill).

Also count findings with other statuses:
- `already_added`: count of findings where `status` equals `"added"`
- `already_skipped`: count of findings where `status` equals `"skipped"`

Set these counters:
- `added_this_session = 0`
- `skipped_this_session = 0`
- `total_findings = length of findings array`
- `pending_findings = list of findings with status "pending"`
- `pending_count = length of pending_findings`

If `pending_count` is 0, display the following and stop (do not proceed to Step 3):

```
All findings processed.

Summary: <total_findings> total findings — <already_added> added as todos, <already_skipped> skipped, 0 pending.
```

## Step 3 — Interactive finding loop

For each finding in `pending_findings` (in order), perform the following sub-steps. Track the loop index starting at 1.

### Step 3a — Display the finding

Display the finding with full context using this exact format:

```
---
Finding <loop_index>/<pending_count> — <finding.id>: <finding.title>
Criterion: <finding.criterion> | Severity: <finding.severity>/5 | Confidence: <finding.confidence>/5
File: <finding.file>
Location: <finding.location>

Detail: <finding.detail>

Suggestion: <finding.suggestion>
---
```

If the finding has no `suggestion` field (key is absent, not just null), omit the `Suggestion:` line entirely.

After the finding display, show the progress line:

```
Progress: <pending_count - loop_index + 1> pending, <already_added + added_this_session> added, <already_skipped + skipped_this_session> skipped
```

Then present the options:

```
Options:
  1. Create todo
  2. Skip
  3. Edit title, then create todo
  4. Stop reviewing
```

Wait for the user to respond with their choice (1, 2, 3, or 4).

### Step 3b — Handle user choice

**If user chooses 1 (Create todo):**

1. Call `mcp__proj__todo_add` with:
   - `title`: the finding's `title` field verbatim
   - `notes`: formatted as:
     ```
     [<finding.criterion> | Severity <finding.severity>/5 | Confidence <finding.confidence>/5]

     <finding.detail>

     File: <finding.file>
     Location: <finding.location>

     Suggestion: <finding.suggestion>
     ```
     Omit the `Suggestion:` line if the finding has no `suggestion` field.
2. Extract the created todo's ID from the response.
3. Update the finding in the in-memory findings array: set `status` to `"added"` and `todo_id` to the created ID.
4. Increment `added_this_session` by 1.
5. Proceed to Step 3c.

**If user chooses 2 (Skip):**

1. Update the finding in the in-memory findings array: set `status` to `"skipped"`. Leave `todo_id` as `null`.
2. Increment `skipped_this_session` by 1.
3. Proceed to Step 3c.

**If user chooses 3 (Edit title, then create todo):**

1. Display: "Enter revised title (press Enter to keep original):"
2. Wait for user input.
3. If user provides a non-empty string, use it as the title. Otherwise use the finding's original `title`.
4. Call `mcp__proj__todo_add` with:
   - `title`: the revised or original title
   - `notes`: same format as option 1
5. Extract the created todo's ID from the response.
6. Update the finding in the in-memory findings array: set `status` to `"added"` and `todo_id` to the created ID.
7. Increment `added_this_session` by 1.
8. Proceed to Step 3c.

**If user chooses 4 (Stop reviewing):**

1. Proceed to Step 3c (the file write), then skip to Step 4 (do not process remaining findings).

### Step 3c — Write updated file back to disk

After every user decision (including Stop), reconstruct and write the file:

1. Rebuild the YAML frontmatter from the in-memory data. The frontmatter must contain all original top-level fields (`type`, `reviewed_file`, `reviewed_name`, `date`, `overall_score`, `band`, `criterion_scores`, `findings`) with the `findings` array reflecting all status/todo_id updates made so far.
2. Reconstruct the full file content: `---\n` + YAML frontmatter + `---\n` + markdown body (preserved exactly as read in Step 1).
3. Call `Write` with the original file path from `$ARGUMENTS` and the reconstructed content.

After writing, if the user chose Stop (option 4), skip to Step 4. Otherwise, advance to the next pending finding and return to Step 3a.

## Step 4 — Final summary

After all pending findings are processed or the user chose Stop, display:

```
Review session complete.

This session: <added_this_session> todos created, <skipped_this_session> skipped.
Overall: <total_findings> total findings — <already_added + added_this_session> added, <already_skipped + skipped_this_session> skipped, <remaining_pending> still pending.
Review file updated: <file path>
```

Where `remaining_pending` is `pending_count - added_this_session - skipped_this_session`.

Do not call any tools after displaying the summary.

Suggested next: (1) Run `/claude-helper:resume-review <same-file>` again to process remaining pending findings  (2) Check created todos with `mcp__proj__todo_list`
