---
name: review-agent
description: Review a Claude subagent definition file using a 5-criterion parallel framework. Produces scored findings ranked by severity and confidence. Use when asked "review this agent", "check agent quality", or "audit agent file".
disable-model-invocation: "true"
allowed-tools: Read, Task, mcp__proj__todo_add
argument-hint: "<path-to-agent-file>"
---

Review the subagent definition file at: $ARGUMENTS

## Step 1 — Read the file

Call `Read` with the path provided in `$ARGUMENTS`. If the file does not exist or cannot be read, stop and report: "Cannot read file at <path>: <error>. Provide the correct absolute path to a subagent definition file."

Store the file content in memory for passing to subagents in Step 2. Do not call `Read` again after this step.

**SKILL.md detection gate:** After reading the file, determine the file type:
- Set `file_type = "skill"` if `$ARGUMENTS` ends with `SKILL.md` OR the frontmatter contains any of the fields `disable-model-invocation`, `argument-hint`, `context`, or `agent`.
- Otherwise set `file_type = "agent"`.

Use `file_type` in Step 2 to select the appropriate C5 rubric variant: if `file_type = "skill"`, pass the **C5 SKILL.md variant** rubric to the C5 subagent; if `file_type = "agent"`, pass the **C5 agent file variant** rubric.

## Step 2 — Spawn 5 parallel criterion subagents

Spawn exactly 5 `Task` subagents simultaneously — one per criterion (C1 through C5). All 5 must be launched in the same step before waiting for any results. Wait for all 5 to complete before proceeding to Step 3.

Each subagent receives a prompt built from the template below. The file content read in Step 1 is passed inline in the prompt — the subagent does not call `Read`.

**Subagent prompt template** (one instance per criterion; substitute the placeholders):

```
You are evaluating a Claude subagent definition file for criterion {criterion_id} — {criterion_name}.

Assess ONLY this criterion. Do not comment on other criteria.

## Criterion Definition

{criterion_definition}

## Rubric

{rubric}

## Output Format

Return your assessment as a JSON object with exactly this structure:

{
  "criterion": "{criterion_id}",
  "score": <integer 1–5>,
  "findings": [
    {
      "criterion": "{criterion_id}",
      "title": "<one-sentence summary, 10 words or fewer>",
      "detail": "<2–4 sentences describing the specific issue, including where in the file it occurs>",
      "suggestion": "<concrete actionable fix — omit this field entirely when no issue is found>",
      "severity": <integer 1–5>,
      "confidence": <integer 1–5>
    }
  ]
}

The "findings" array may be empty if no issues are found. The "score" field is always present.

## Severity scale
- 5: Causes a runtime error or makes the file non-functional (e.g., tool called but not in `tools`, frontmatter absent).
- 4: Causes likely divergence across Claude instances or material misuse (e.g., vague decision point in a critical path).
- 3: Reduces quality in a non-critical path (e.g., missing example for a complex step).
- 2: Minor quality concern, no runtime impact (e.g., unused tool listed, weak description).
- 1: Cosmetic or stylistic, negligible impact (e.g., inconsistent bullet style).

## Confidence scale
- 5: Definitively present — verifiable against a formal spec or exact convention.
- 4: Very likely present — strong contextual evidence.
- 3: Probable but requires interpretation.
- 2: Possible but requires domain knowledge to confirm.
- 1: Speculative — flagging a potential concern with low certainty.

## Criterion score vs findings
- Score 5: No issues, or only cosmetic issues (severity 1).
- Score 4: One finding with severity 2 or lower.
- Score 3: One finding with severity 3, or two findings with severity 2.
- Score 2: One finding with severity 4, or two or more findings with severity 3.
- Score 1: One or more findings with severity 5, or criterion so severely violated the file cannot be reliably used.

## File Content

{file_content}
```

**Per-criterion values to substitute:**

**C1 — Instruction Clarity**
- `{criterion_id}`: `C1`
- `{criterion_name}`: `Instruction clarity`
- `{criterion_definition}`: Are the steps unambiguous and deterministic? Two different Claude instances running the same file would take identical actions. Vague verbs ("handle", "process", "deal with", "manage", "address", "check", "look at") used without defining the exact action lower the score. Decision points where multiple interpretations are valid lower the score.
- `{rubric}`:
  - **5**: Every step is deterministic; no vague verbs; all conditional branches define what to do in each case; a second Claude instance would make the same decisions.
  - **4**: One or two minor ambiguities (e.g., a single "handle" without context) that would not materially change outcomes; fewer than two vague verbs or interpretation gaps.
  - **3**: Three to four ambiguities or vague decision points; a second instance might make different choices in some steps.
  - **2**: Five or more vague steps, or the overall flow is unclear; different instances would likely diverge significantly.
  - **1**: Impossible to follow consistently; most steps are undefined or rely on vague verbs with no defined behaviour; the agent cannot be reliably executed.

**C2 — Factual Accuracy**
- `{criterion_id}`: `C2`
- `{criterion_name}`: `Factual accuracy`
- `{criterion_definition}`: Does the described behaviour match verifiable ground truth? Check: (a) tools listed in `tools` match tools actually called in the body; (b) frontmatter fields are present, correctly typed, and correctly valued; (c) factual claims about tool behaviour, API conventions, or file formats are accurate. Decide autonomously which sources to cross-reference based on what is most relevant to this specific file — do not rely only on what is explicitly stated in the file.
- `{rubric}`:
  - **5**: All tools listed match tools called; frontmatter is complete and correctly typed; all factual claims are accurate.
  - **4**: One minor error (e.g., one unused tool listed, or description could be marginally more precise) with no runtime impact.
  - **3**: One required frontmatter field is missing or incorrectly typed, or one tool is called but missing from `tools` (would cause a runtime error on that path).
  - **2**: Two or more required frontmatter fields are missing or incorrect, or two or more tools are missing from `tools`.
  - **1**: Frontmatter is absent or unparseable; `tools` is empty while the body calls tools; or the tool list is entirely wrong.

**C3 — Overfitting vs Generalisation**
- `{criterion_id}`: `C3`
- `{criterion_name}`: `Overfitting vs generalisation`
- `{criterion_definition}`: Is the agent correctly scoped? Too narrow (handles only one specific case when it should generalise) and too broad (tries to be universal when it should be specific) both lower the score. Also covers: missing example invocations where they would reduce ambiguity, unhandled failure paths (tool call failure, empty results, permission errors), and absence of "Suggested next" guidance when the agent is designed for direct user interaction.
- `{rubric}`:
  - **5**: Agent generalises well across its intended scope; all primary failure paths are explicitly handled with defined fallback behaviour; follow-up guidance is present when appropriate for the agent's interaction mode.
  - **4**: Good generalisation; one uncommon failure path unaddressed or one non-critical example missing; follow-up guidance present if applicable.
  - **3**: Most cases handled; one primary failure path missing (e.g., tool error or empty result unaddressed) or follow-up guidance absent in an interactive agent; examples absent in one or two places where they would genuinely help.
  - **2**: Limited generalisation; two or more primary failure paths unaddressed; examples absent in most non-trivial steps; no follow-up guidance even for an interactive agent.
  - **1**: Highly specific or brittle; no error handling; no examples; any failure would leave the agent without guidance.

**C4 — Completeness**
- `{criterion_id}`: `C4`
- `{criterion_name}`: `Completeness`
- `{criterion_definition}`: Does the agent fully achieve its stated goal? Are there gaps between what the description promises and what the body delivers? Also covers: presence and quality of all expected sections, logical ordering of steps, and description quality — specifically, accuracy and specificity sufficient for a caller to determine whether to invoke this agent. Unlike SKILL.md descriptions, trigger-phrase richness is less critical than caller-selectability.
- `{rubric}`:
  - **5**: All expected sections are present and well-documented; steps follow logical order (role definition → main action → output); description is accurate and specific enough for a caller to reliably select this agent over alternatives.
  - **4**: All key sections present; one section could be improved; description is good but could be more specific about domain or deliverables.
  - **3**: Structure is readable but one expected section is missing or weak; description is so generic a caller would struggle to distinguish this agent from a general-purpose one; or one material gap exists between description and body.
  - **2**: Two or more expected sections are missing; steps feel out of order; description is vague or inaccurate; material gaps between description and body.
  - **1**: Unstructured; description absent, empty, or unrelated to function; major sections missing; body does not deliver on what description promises.

**C5 — Structure (agent file variant)** _(use when `file_type = "agent"`)_
- `{criterion_id}`: `C5`
- `{criterion_name}`: `Structure`
- `{criterion_definition}`: Does the file follow Claude Code agent file conventions? Check: (1) Frontmatter fields — `name` (required, lowercase-hyphen), `description` (required), `tools` (required; note: field name is `tools` not `allowed-tools`), `model` (optional, must be a valid Claude model ID if present). Presence of SKILL.md-specific fields (`disable-model-invocation`, `argument-hint`, `context`, `agent`) is a convention violation — flag each one found. (2) Tool list accuracy — exact match between `tools` and tools actually called in the body; missing tools (called but not listed) are more severe than unused tools (listed but not called). (3) Body ordering — role definition or context-setting opening, logical sequence of steps, output specification. (4) Formatting conventions — consistent header levels, code blocks for code and tool outputs, bullet lists for options.
- `{rubric}`:
  - **5**: All required frontmatter fields present and correctly typed; `tools` field (not `allowed-tools`) used; exact match between `tools` and tools called; no SKILL.md-specific fields present; body follows logical sequence with role definition and output specification; formatting is consistent throughout.
  - **4**: One minor issue — either one unused tool listed, or one formatting inconsistency, or `model` value slightly off; no missing required fields and no missing tools; no SKILL.md-specific fields.
  - **3**: One required frontmatter field is missing or incorrectly typed (e.g., `allowed-tools` used instead of `tools`), OR one tool called in the body is missing from `tools`, OR body ordering is informal but readable.
  - **2**: Two or more required frontmatter fields are missing or incorrect, OR two or more tools are missing from `tools`, OR one or more SKILL.md-specific fields (`disable-model-invocation`, `argument-hint`, `context`, `agent`) are present alongside the required agent fields.
  - **1**: Frontmatter is absent or unparseable; `tools` is empty while body calls tools; or multiple SKILL.md-specific fields are present making the file structurally ambiguous between a SKILL.md and an agent file.

**C5 — Structure (SKILL.md variant)** _(use when `file_type = "skill"`)_
- `{criterion_id}`: `C5`
- `{criterion_name}`: `Structure`
- `{criterion_definition}`: Does the file follow Claude Code SKILL.md conventions? Check: (1) Frontmatter fields — `name` (required, lowercase-hyphen), `description` (required), `allowed-tools` (required; note: SKILL.md uses `allowed-tools`, not `tools`), optional fields: `disable-model-invocation`, `argument-hint`, `context`, `agent`. These optional SKILL.md-specific fields are correct conventions — do NOT flag them as violations. (2) Tool list accuracy — exact match between `allowed-tools` and tools actually called in the body; missing tools (called but not listed) are more severe than unused tools (listed but not called). (3) Body ordering — opening directive or context-setting, logical sequence of steps, output specification. (4) Formatting conventions — consistent header levels, code blocks for code and tool outputs, bullet lists for options.
- `{rubric}`:
  - **5**: All required frontmatter fields present and correctly typed; `allowed-tools` field used; exact match between `allowed-tools` and tools called; optional SKILL.md fields used correctly; body follows logical sequence with output specification; formatting is consistent throughout.
  - **4**: One minor issue — either one unused tool listed, or one formatting inconsistency; no missing required fields and no missing tools.
  - **3**: One required frontmatter field is missing or incorrectly typed (e.g., `tools` used instead of `allowed-tools`), OR one tool called in the body is missing from `allowed-tools`, OR body ordering is informal but readable.
  - **2**: Two or more required frontmatter fields are missing or incorrect, OR two or more tools are missing from `allowed-tools`.
  - **1**: Frontmatter is absent or unparseable; `allowed-tools` is empty while body calls tools; or the file is structurally malformed.

## Step 3 — Collect and merge findings

After all 5 subagents complete:

1. Parse each subagent's JSON output to extract `criterion`, `score`, and `findings` array. If a subagent's output cannot be parsed as valid JSON, display the raw output inline (prefixed with the criterion ID, e.g., "C3 raw output: ..."), assign that criterion a score of 0 with an empty findings array, and continue processing the remaining subagents.
2. Flatten all findings from all 5 subagents into a single list.

**Deduplication algorithm** (apply before ranking):

Two findings are duplicates if they describe the same underlying structural problem in the same location of the file, regardless of which criterion they come from.

- Compare `title` fields: if two titles describe the same issue (semantically equivalent, not necessarily lexically identical), they are candidates.
- Compare `detail` fields: if both `title` and `detail` point to the same location and the same root cause, they are duplicates.
- Keep the finding with the higher `severity × confidence` product. If tied, keep the finding from the lower-numbered criterion (C1 before C2, etc.).
- Discard the lower-priority duplicate.
- When in doubt whether two findings are duplicates, treat them as distinct. Deduplication is conservative — err on the side of inclusion.

## Step 4 — Rank findings and produce the report

**Ranking:** Sort the deduplicated findings list by `severity × confidence` descending. Highest product first. Tie-breaking: lower-numbered criterion first (C1 before C2, etc.); if still tied (same criterion), order is arbitrary.

**Overall score:** `round(mean(C1_score, C2_score, C3_score, C4_score, C5_score), 1)`

**Score bands:**
- 4.5–5.0: Excellent
- 3.5–4.4: Good
- 2.5–3.4: Needs work
- 1.0–2.4: Critical issues

**Report format** — produce exactly this structure:

```
# Agent Review: <value of `name` frontmatter field, or filename if name is missing>
**File**: <absolute path>
**Date**: <today's date as YYYY-MM-DD>
**Overall**: <overall>/5.0 — <Band>

## Criterion Scores

| # | Criterion | Score | Top Finding |
|---|-----------|-------|-------------|
| C1 | Instruction clarity | <score>/5 | <title of highest-priority finding for C1, or "—" if no findings> |
| C2 | Factual accuracy | <score>/5 | <title of highest-priority finding for C2, or "—"> |
| C3 | Overfitting vs generalisation | <score>/5 | <title of highest-priority finding for C3, or "—"> |
| C4 | Completeness | <score>/5 | <title of highest-priority finding for C4, or "—"> |
| C5 | Structure | <score>/5 | <title of highest-priority finding for C5, or "—"> |

## Ranked Findings

<Omit this section entirely if the deduplicated findings list is empty.>

### F<N> — <finding title> (C<X>, severity <S>/5, confidence <K>/5, priority <S×K>)
**Detail**: <detail field verbatim>
**Suggestion**: <suggestion field verbatim>

<Omit the **Suggestion** line entirely if the finding has no suggestion field.>

## Summary
<2–4 sentence narrative. Main strengths first. Name the top 2–3 findings by criterion ID (e.g., "C1", "C3"). End with a directional recommendation — e.g., "Addressing C1 and C3 would move this agent from 'Needs work' to 'Good'.">
```

**"Top Finding" cell rules:**
- The value is the `title` string of the finding for that criterion with the highest `severity × confidence` product after deduplication.
- If the criterion has no findings, the cell contains `—`.

**Ranked Findings numbering:** F1, F2, F3, ... in descending priority order. F1 is the highest-priority finding.

**"No findings" display:** If a criterion subagent returns zero findings, its criterion still appears in the Criterion Scores table with its score and `—` in the Top Finding column. Additionally, the criterion still appears in the Ranked Findings section as a row with the label `No issues found` and `N/A` for both severity and confidence:

```
### F<N> — No issues found (C<X>, severity N/A, confidence N/A, priority N/A)
```

This row has no **Detail** or **Suggestion** lines. "No findings" rows appear after all real findings (since N/A priority sorts last).

## Step 5 — Present the report

Output the completed report in the conversation. Do not write any files. Do not modify any files. Do not call any tools in Steps 3–5.

Retain the ranked findings list in memory (in ranked order, F1 first) for use in Step 6. Proceed to Step 6 after presenting the report.

## Step 6 — Interactive review phase

**Save issue context:** Before iterating through findings, ensure each finding in the ranked list has the following fields retained in memory for display during the review loop:
- `file`: the absolute path of the reviewed file (value of `$ARGUMENTS`)
- `location`: where in the file the issue occurs (extracted from the `detail` field — e.g., the step name or line reference mentioned)
- `description`: the `detail` field verbatim
- `severity`: the numeric severity value
- `criterion`: the criterion ID (e.g., C2)
- `suggestion`: the `suggestion` field verbatim (absent if the finding has no suggestion)
- `title`: the `title` field

After the report is presented, iterate through each finding in the ranked findings list (F1 first, in descending priority order). Skip any "No issues found" placeholder rows — only process findings with real detail.

For each finding, display:

```
Issue <N>/<total>: <finding title>
Criterion: <criterion_id> | Severity: <severity>/5 | Confidence: <confidence>/5
Detail: <detail text>
Suggestion: <suggestion text>

Options:
  1. Create todo
  2. Skip
  3. Edit description, then create todo
  4. Stop reviewing
```

Where `<total>` is the count of real findings (excluding "No issues found" rows) and `<N>` increments from 1.

Omit the `Suggestion:` line if the finding has no `suggestion` field.

**Handling the user's choice:**

- **1 — Create todo**: Call `mcp__proj__todo_add` with `title` set to the finding's `title` and `notes` set to `"[<criterion_id> | Severity <severity>/5 | Confidence <confidence>/5]\n\n<detail>\n\nSuggestion: <suggestion>"` (omit the Suggestion line in notes if no suggestion). Increment the todos-created counter. Advance to the next finding.

- **2 — Skip**: Increment the skipped counter. Advance to the next finding without calling any tools.

- **3 — Edit then create todo**: Ask the user: "Enter the revised description for this todo (or press Enter to keep the original):" Wait for the user's input. Use the user's input as the `title` if provided, otherwise keep the original finding `title`. Then call `mcp__proj__todo_add` with the (possibly revised) title and the same `notes` format as option 1. Increment the todos-created counter. Advance to the next finding.

- **4 — Stop**: Exit the review loop immediately. Do not process remaining findings.

**After the loop ends** (all findings reviewed, or option 4 chosen), display:

```
Review complete: <N_reviewed> issues reviewed, <M_created> todos created, <K_skipped> skipped.
```

Where `N_reviewed` is the number of findings shown to the user (not counting any that were not yet reached when Stop was chosen), `M_created` is the number of todos created, and `K_skipped` is the number of findings skipped.

Suggested next: (1) `/claude-helper:review-all <directory> --include-agents` — batch-review all SKILL.md and agent files in a directory and compare scores  (2) Edit the agent file to address the highest-impact findings, then re-run this review to verify improvement
