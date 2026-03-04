---
name: review-all
description: Batch-review all SKILL.md files in a directory. Spawns parallel review agents and produces a combined summary sorted by overall score. Use when asked "review all skills", "audit skills in X", or "batch skill review".
disable-model-invocation: "true"
allowed-tools: Glob, Task
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
  "overall_score": <number, e.g. 3.7>,
  "band": "<Excellent | Good | Needs work | Critical issues>",
  "top_finding": "<one sentence — the single highest-impact finding from the report, prefixed with its dimension ID, e.g. 'D6: no error handling for missing argument'>",
  "full_report": "<the complete markdown report text produced by review-skill>"
}

Do not present the report in the conversation. Return only the JSON object described above.
```

For each file in **agent_files**, spawn one Task agent using the following template:

```
Run the full `/claude-helper:review-agent` skill instructions on the file at: <absolute-path>

Return a JSON object with exactly these keys:
{
  "path": "<absolute path to the file>",
  "overall_score": <number, e.g. 3.7>,
  "band": "<Excellent | Good | Needs work | Critical issues>",
  "top_finding": "<one sentence — the single highest-impact finding from the report, prefixed with its dimension ID, e.g. 'D6: no error handling for missing argument'>",
  "full_report": "<the complete markdown report text produced by review-agent>"
}

Do not present the report in the conversation. Return only the JSON object described above.
```

All Task agents run in parallel. Wait for all agents to complete before proceeding to Step 6.

**Parallelism note**: Each Task agent is independent — it reads its assigned file, runs the full 10-dimension review, and returns its JSON result. There is no shared state between agents. The number of parallel agents equals the total number of files (skill_files + agent_files). On large directories this approach is significantly faster than sequential review.

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

## Step 7 — Produce and present the batch summary report

Produce the following report and present it in the conversation. Do not write any files. Do not modify any files.

```markdown
# Skill Review Summary
**Directory**: <directory from Step 1>
**Date**: <today's date as YYYY-MM-DD>
**Files reviewed**: <reviewed_count> (<skill_files count> skills, <agent_files count> agents)
<If error_count > 0: "**Errors**: <error_count> file(s) could not be reviewed — see end of Results table.">

## Results (sorted by overall score, ascending)

| File | Overall | Band | Top Issue |
|------|---------|------|-----------|
| <relative path from directory> | <score> | <band> | <top_finding> |
| ... | ... | ... | ... |
<For error rows: score = "—", band = "Error", top_finding = the error message>

## Detailed Reports

<For each file in the sorted order, output its full_report. Separate reports with a horizontal rule (---).>
```

**Relative path display**: In the Results table, show file paths relative to the scanned directory (omit the directory prefix) for readability. In the Detailed Reports section, use the full absolute path as included in each `full_report`.

**Top issue cell**: If `top_finding` is "—" (meaning the file scored Excellent with no significant issues), display "—" in the Top Issue column.

Suggested next: (1) `/claude-helper:review-skill <path>` — re-review a specific file after making improvements  (2) Edit the lowest-scoring files to address their highest-impact findings, then re-run `review-all` to verify improvement
