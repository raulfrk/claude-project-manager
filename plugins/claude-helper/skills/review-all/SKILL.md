---
name: review-all
description: Batch-review all SKILL.md files in a directory. Spawns parallel review agents and produces a combined summary sorted by overall score. Use when asked "review all skills", "audit skills in X", or "batch skill review".
disable-model-invocation: "true"
allowed-tools: Glob, Task, Write, Bash
argument-hint: "<directory> [--include-agents]"
---

Batch-review all skill (and optionally agent) files found under: $ARGUMENTS

## Step 1 — Parse arguments

Extract the following from `$ARGUMENTS`:

- **directory**: the first positional argument — the absolute path to the directory to scan. If the path is relative, resolve it against the current working directory.
- **--include-agents flag**: present if `$ARGUMENTS` contains the string `--include-agents`.

If no directory is provided (i.e. `$ARGUMENTS` is empty or contains only the flag), stop and report: "No directory provided. Usage: `/claude-helper:review-all <directory> [--include-agents]`"

If the directory argument is provided but does not look like a valid path (e.g. it is a flag or a typo), stop and report: "Invalid directory path: <value>. Provide an absolute path to a directory to scan."

## Step 2 — Glob for SKILL.md files

Call `Glob` with pattern `**/SKILL.md` under the directory extracted in Step 1.

Collect all matching paths into a list called **skill_files**.

## Step 3 — Glob for agent files (conditional)

If `--include-agents` was present in `$ARGUMENTS`:

Call `Glob` with pattern `**/*.md` under `~/.claude/agents/` to find agent files in the user's global agents directory. Add any matches to a separate list called **agent_files**.

Also call `Glob` with pattern `**/*.md` under `<directory>/.claude/agents/` (the `.claude/agents/` subdirectory within the scanned directory, if it exists). Add any matches to **agent_files** as well.

If `--include-agents` was not present, set **agent_files** to an empty list.

## Step 4 — Check for empty results

If both **skill_files** and **agent_files** are empty, stop and report:

```
No skill or agent files found in <directory>.

- SKILL.md files: 0 found
- Agent files: 0 found (--include-agents was <present/not present>)

Verify the directory path is correct and contains SKILL.md files.
```

If only **skill_files** is empty but **agent_files** has entries (or vice versa), continue — there is at least one file to review.

## Step 5 — Spawn parallel review Task agents

For each file in **skill_files**, spawn one Task agent using the following template:

```
Run the full `/claude-helper:review-skill` skill instructions on the file at: <absolute-path>

Return a JSON object with exactly these keys:
{
  "path": "<absolute path to the file>",
  "type": "skill",
  "overall_score": <number, e.g. 3.7>,
  "band": "<Excellent | Good | Needs work | Critical issues>",
  "top_finding": "<one sentence — the single highest-impact finding from the report, prefixed with its criterion ID, e.g. 'C6: no error handling for missing argument'>",
  "full_report": "<the complete markdown report text produced by review-skill>",
  "criterion_scores": {
    "C1": <integer 1-5>,
    "C2": <integer 1-5>,
    "C3": <integer 1-5>,
    "C4": <integer 1-5>,
    "C5": <integer 1-5>,
    "C6": <integer 1-5>,
    "C7": <integer 1-5>
  },
  "findings": [
    {
      "id": "F1",
      "criterion": "<C1-C7>",
      "title": "<one-sentence summary, ~10 words max>",
      "detail": "<2-4 sentences describing the issue>",
      "suggestion": "<concrete actionable fix, or omit key if none>",
      "severity": <integer 1-5>,
      "confidence": <integer 1-5>,
      "location": "<where in the file, e.g. Step 4, line 23>"
    }
  ]
}

The findings array must match the ranked findings from the review, ordered by severity x confidence descending. If no findings exist, use an empty array.

Do not present the report in the conversation. Return only the JSON object described above.
```

For each file in **agent_files**, spawn one Task agent using the following template:

```
Run the full `/claude-helper:review-agent` skill instructions on the file at: <absolute-path>

Return a JSON object with exactly these keys:
{
  "path": "<absolute path to the file>",
  "type": "agent",
  "overall_score": <number, e.g. 3.7>,
  "band": "<Excellent | Good | Needs work | Critical issues>",
  "top_finding": "<one sentence — the single highest-impact finding from the report, prefixed with its criterion ID, e.g. 'C6: no error handling for missing argument'>",
  "full_report": "<the complete markdown report text produced by review-agent>",
  "criterion_scores": {
    "C1": <integer 1-5>,
    "C2": <integer 1-5>,
    "C3": <integer 1-5>,
    "C4": <integer 1-5>,
    "C5": <integer 1-5>,
    "C6": <integer 1-5>,
    "C7": <integer 1-5>
  },
  "findings": [
    {
      "id": "F1",
      "criterion": "<C1-C7>",
      "title": "<one-sentence summary, ~10 words max>",
      "detail": "<2-4 sentences describing the issue>",
      "suggestion": "<concrete actionable fix, or omit key if none>",
      "severity": <integer 1-5>,
      "confidence": <integer 1-5>,
      "location": "<where in the file, e.g. Step 4, line 23>"
    }
  ]
}

The findings array must match the ranked findings from the review, ordered by severity x confidence descending. If no findings exist, use an empty array.

Do not present the report in the conversation. Return only the JSON object described above.
```

All Task agents run in parallel. Wait for all agents to complete before proceeding to Step 6.

**Parallelism note**: Each Task agent is independent — it reads its assigned file, runs the full 7-criterion review (C1–C7), and returns its JSON result. There is no shared state between agents. The number of parallel agents equals the total number of files (skill_files + agent_files). On large directories this approach is significantly faster than sequential review.

**Agent failure handling**: If a Task agent fails to return a valid JSON result (e.g. the file could not be read, or the agent returned an error string instead of JSON), record a placeholder result for that file:

```json
{
  "path": "<absolute path>",
  "overall_score": null,
  "band": "Error",
  "top_finding": "Review failed: <error message or 'agent returned no result'>",
  "full_report": "Review could not be completed for this file."
}
```

## Step 6 — Collect and sort results

Collect all JSON results from Step 5 into a single list.

Sort the list by `overall_score` ascending (lowest score first — these are the files most in need of improvement). Place any error results (where `overall_score` is null) at the end of the list.

Compute:
- **total_files**: total number of files reviewed (skill_files + agent_files)
- **error_count**: number of files where review failed
- **reviewed_count**: total_files − error_count

## Step 7 — Resolve tracking directory

Determine the project's tracking directory. Use the `mcp__plugin_proj_proj__proj_get_active` tool if available to get the active project's tracking path. If that fails, fall back to `~/projects/tracking/<project-name>` where `<project-name>` is inferred from the scanned directory's name.

Store the result as **tracking_dir**.

Ensure the `<tracking_dir>/reviews/` directory exists by running:

```
Bash: mkdir -p <tracking_dir>/reviews
```

## Step 8 — Save per-file review files

For each result in the sorted list from Step 6 where `overall_score` is not null (skip error results):

1. **Slugify** the reviewed file's basename (without extension):
   - Convert to lowercase
   - Replace every non-alphanumeric character with a hyphen (`-`)
   - Collapse consecutive hyphens into a single hyphen
   - Strip leading and trailing hyphens

2. **Construct the file path**: `<tracking_dir>/reviews/<slug>-<YYYY-MM-DD>.md`
   - If the file already exists (collision from a previous review of the same file on the same day), append a numeric suffix: `-2`, `-3`, etc.

3. **Build YAML frontmatter** from the result's structured data:

   ```yaml
   ---
   type: <result.type>
   reviewed_file: <result.path>
   reviewed_name: <slug>
   date: <YYYY-MM-DD>
   overall_score: <result.overall_score>
   band: <result.band>
   criterion_scores:
     C1: <result.criterion_scores.C1>
     C2: <result.criterion_scores.C2>
     C3: <result.criterion_scores.C3>
     C4: <result.criterion_scores.C4>
     C5: <result.criterion_scores.C5>
     C6: <result.criterion_scores.C6>
     C7: <result.criterion_scores.C7>
   findings:
     - id: <finding.id>
       criterion: <finding.criterion>
       title: "<finding.title>"
       detail: "<finding.detail>"
       suggestion: "<finding.suggestion>"   # omit key entirely if no suggestion
       severity: <finding.severity>
       confidence: <finding.confidence>
       file: <result.path>
       location: "<finding.location>"
       status: pending
       todo_id: null
   ---
   ```

4. **Append the markdown body**: use `result.full_report` verbatim after the closing `---`.

5. **Write** the complete file (frontmatter + body) using the `Write` tool.

6. Store the written file path alongside the result for use in Steps 9 and 10.

## Step 9 — Create summary index file

After all per-file review files are saved, create the summary index.

**Compute aggregate statistics**:
- **total_files**: total number of files reviewed (skill_files + agent_files)
- **reviewed_count**: total_files minus error_count
- **error_count**: number of files where review failed
- **mean_score**: arithmetic mean of all successful `overall_score` values, rounded to 1 decimal
- **total_findings**: sum of findings count across all successful reviews
- **band_distribution**: count of each band (Excellent, Good, Needs work, Critical issues) across successful reviews

**Write** the index file to `<tracking_dir>/reviews/index-<YYYY-MM-DD>.md` with this format:

```markdown
# Review Summary Index

**Date**: <YYYY-MM-DD>
**Directory**: <directory from Step 1>
**Total files**: <total_files>
**Reviewed successfully**: <reviewed_count>
**Errors**: <error_count>

## Aggregate Statistics

- **Mean score**: <mean_score>/5.0
- **Total findings**: <total_findings>
- **Band distribution**: Excellent (<count>), Good (<count>), Needs work (<count>), Critical issues (<count>)

## Per-File Reviews

| File | Type | Score | Band | Findings | Review File |
|------|------|-------|------|----------|-------------|
| <relative path> | <type> | <overall_score> | <band> | <findings count> | <relative path to review file from tracking_dir> |
| ... | ... | ... | ... | ... | ... |

## Score Distribution

| Range | Band | Count |
|-------|------|-------|
| 4.5-5.0 | Excellent | <count> |
| 3.5-4.4 | Good | <count> |
| 2.5-3.4 | Needs work | <count> |
| 1.0-2.4 | Critical issues | <count> |
```

Store the index file path as **index_path**.

## Step 10 — Produce and present the batch summary report

Produce the following report and present it in the conversation.

```markdown
# Skill Review Summary
**Directory**: <directory from Step 1>
**Date**: <today's date as YYYY-MM-DD>
**Files reviewed**: <reviewed_count> (<skill_files count> skills, <agent_files count> agents)
<If error_count > 0: "**Errors**: <error_count> file(s) could not be reviewed — see end of Results table.">

## Results (sorted by overall score, ascending)

| File | Overall | Band | Findings | Top Issue | Review File |
|------|---------|------|----------|-----------|-------------|
| <relative path from directory> | <score> | <band> | <findings count> | <top_finding> | <review file path> |
| ... | ... | ... | ... | ... | ... |
<For error rows: score = "—", band = "Error", findings = "—", top_finding = the error message, review file = "—">

## Detailed Reports

<For each file in the sorted order, output its full_report. Separate reports with a horizontal rule (---).>
```

After the report, display:

```
Review files saved to: <tracking_dir>/reviews/
Review index saved to: <index_path>
```

**Relative path display**: In the Results table, show file paths relative to the scanned directory (omit the directory prefix) for readability. In the Detailed Reports section, use the full absolute path as included in each `full_report`.

**Top issue cell**: If `top_finding` is "—" (meaning the file scored Excellent with no significant issues), display "—" in the Top Issue column.

Suggested next: (1) `/claude-helper:review-skill <path>` — re-review a specific file after making improvements  (2) Edit the lowest-scoring files to address their highest-impact findings, then re-run `review-all` to verify improvement  (3) `/claude-helper:resume-review` — resume reviewing findings from the saved review files  (4) `/claude-helper:review-to-todo` — convert review findings into actionable todos
