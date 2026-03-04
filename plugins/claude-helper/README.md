# claude-helper

Review and quality tooling for Claude Code. Analyse SKILL.md files and Claude subagent definition files, producing scored, prioritised reports on quality, completeness, and clarity. Reports are presented in the conversation — no files are modified.

---

## Table of Contents

- [What it does](#what-it-does)
- [Requirements](#requirements)
- [Installation](#installation)
- [Skills](#skills)
- [Scoring dimensions](#scoring-dimensions)
- [Report format](#report-format)
- [Usage notes](#usage-notes)

---

## What it does

The `claude-helper` plugin provides review skills that score Claude skill and agent definition files across five criteria:

- **Skill review** — read a single SKILL.md file, score each dimension, and produce an annotated report with findings and concrete improvement suggestions.
- **Agent review** — same workflow applied to Claude subagent definition files, with criteria adapted to agent frontmatter conventions.
- **Batch review** — scan a directory recursively, spawn parallel review agents, and produce a combined summary table sorted by overall score (lowest quality first).

The plugin has no MCP server — all review logic is pure Claude reasoning over file content.

---

## Requirements

- Claude Code with skill support

No Python, no MCP server, no external services required.

---

## Installation

Install from the Claude Code plugin marketplace:

```
/plugins install claude-helper
```

No additional setup is required after installation.

---

## Skills

Skills are invoked as `/claude-helper:<name>`.

| Skill | Usage | Description | Argument hint |
|-------|-------|-------------|---------------|
| `review-skill` | `/claude-helper:review-skill <path>` | Review a single SKILL.md file. Reads the file, scores all 5 criteria, and presents a detailed report in the conversation. Does not modify any files. | `<path-to-SKILL.md>` |
| `review-agent` | `/claude-helper:review-agent <path>` | Review a Claude subagent definition file. Identical workflow to `review-skill` with criteria adapted for agent frontmatter conventions. Does not modify any files. | `<path-to-agent-file>` |
| `review-all` | `/claude-helper:review-all <dir> [--include-agents]` | Batch-review all SKILL.md files under a directory. Spawns parallel review agents for performance, aggregates individual reports into a summary table sorted by overall score ascending. Pass `--include-agents` to also review agent definition files. | `<directory> [--include-agents]` |

---

## Scoring dimensions

The scoring framework uses five criteria evaluated in parallel. Each criterion produces a score (1–5), a one-sentence finding, and — when the score is below 5 — a concrete suggestion.

| ID | Criterion | What it checks |
|----|-----------|----------------|
| C1 | Instruction clarity | Are the steps unambiguous and deterministic? Two different Claude instances running the same file would take identical actions. Vague verbs without defined behaviour lower the score. |
| C2 | Factual accuracy | Does the described behaviour match verifiable ground truth? The subagent cross-references whatever sources are most relevant to the specific skill/agent being reviewed. |
| C3 | Overfitting vs generalisation | Is the skill/agent correctly scoped? Too narrow (handles only one case when it should generalise) or too broad (tries to be universal when it should be specific) both lower the score. |
| C4 | Completeness | Does the skill/agent fully achieve its stated goal? Are there gaps between what the description promises and what the body delivers? |
| C5 | Structure | Does the file follow Claude Code conventions? For SKILL.md files: correct frontmatter fields, tool list accuracy, body ordering. For agent files: correct agent frontmatter fields, no SKILL.md-specific fields. |

### Overall score

`overall = round(mean(C1..C5), 1)` — reported alongside individual criterion scores.

### Score bands

| Overall | Band |
|---------|------|
| 4.5 – 5.0 | Excellent |
| 3.5 – 4.4 | Good |
| 2.5 – 3.4 | Needs work |
| 1.0 – 2.4 | Critical issues |

---

## Report format

### Single-file report (`review-skill`, `review-agent`)

```markdown
# Skill Review: <skill-name>
**File**: <path>
**Date**: <date>
**Overall**: <score>/5.0 — <Band>

## Criterion Scores

| # | Criterion | Score | Top Finding |
|---|-----------|-------|-------------|
| C1 | Instruction clarity | 4/5 | Vague verb "handle" in step 3 |
| C2 | Factual accuracy | 5/5 | — |
| C3 | Overfitting vs generalisation | 3/5 | Missing error handling for empty result |
| C4 | Completeness | 4/5 | — |
| C5 | Structure | 5/5 | — |

## Ranked Findings

### F1 — Missing error handling for empty result (C3, severity 3/5, confidence 4/5, priority 12)
**Detail**: Step 4 does not specify what to do when the glob returns no files. A Claude instance would have to guess whether to stop silently, report an error, or continue with an empty list.
**Suggestion**: Add: "If the glob returns no files, stop and report: 'No files found matching the pattern. Verify the path and pattern are correct.'"

### F2 — Vague verb "handle" in step 3 (C1, severity 2/5, confidence 5/5, priority 10)
**Detail**: Step 3 says "handle errors from the API call" without specifying what handling means — retry, log, or stop.
**Suggestion**: Replace with "If the API call fails, display the error message and stop."

### F3 — No issues found (C2, severity N/A, confidence N/A, priority N/A)
### F4 — No issues found (C4, severity N/A, confidence N/A, priority N/A)
### F5 — No issues found (C5, severity N/A, confidence N/A, priority N/A)

## Summary
The skill is well-structured and factually accurate (C2, C5). The most impactful issues are a missing empty-result handler in C3 and one vague verb in C1. Addressing C3 and C1 would move this skill from 'Good' to 'Excellent'.
```

Omit the `## Ranked Findings` section entirely if no findings are present.

### Batch summary report (`review-all`)

```markdown
# Skill Review Summary
**Directory**: <path>
**Date**: <date>
**Files reviewed**: <N>

## Results (sorted by overall score, ascending)

| File | Overall | Band | Top Issue |
|------|---------|------|-----------|
| skills/todo/SKILL.md | 2.1 | Critical issues | D2: ambiguous branch logic |
| skills/define/SKILL.md | 3.4 | Needs work | D3: no examples |
| skills/explore/SKILL.md | 4.6 | Excellent | — |

## Detailed Reports

<individual report per file, separated by --->
```

---

## Usage notes

- Reports are presented in the conversation only. No files are written or modified.
- `review-all` spawns parallel Task agents — one per file — for performance on large directories.
- `review-all --include-agents` also reviews agent definition files alongside SKILL.md files.
- Review scope is generic: any skill or agent file anywhere on the filesystem, not scoped to a specific project.
- For subagent files, D4 and D5 criteria are adapted to agent frontmatter conventions (e.g. `model`, `tools` keys) rather than SKILL.md conventions.

---

## Version

Current version: **0.2.0**

See the marketplace manifest at `.claude-plugin/plugin.json` for details.
