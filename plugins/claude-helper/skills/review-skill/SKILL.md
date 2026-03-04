---
name: review-skill
description: Review a SKILL.md file using a 5-criterion parallel framework. Produces scored findings ranked by severity and confidence. Use when asked "review this skill", "check skill quality", or "audit SKILL.md".
disable-model-invocation: "true"
allowed-tools: Read, Task
argument-hint: "<path-to-SKILL.md>"
---

Review the SKILL.md file at: $ARGUMENTS

## Step 1 — Read the file

Call `Read` with the path provided in `$ARGUMENTS`. If the file does not exist or cannot be read, stop and report: "Cannot read file at <path>: <error>. Provide the correct absolute path to a SKILL.md file."

Store the file content in memory for passing to subagents in Step 2. Do not call `Read` again after this step.

## Step 2 — Spawn 5 parallel criterion subagents

Spawn exactly 5 `Task` subagents simultaneously — one per criterion (C1 through C5). Launch all 5 in the same step before waiting for any results. Wait for all 5 to complete before proceeding to Step 3.

Each subagent receives a prompt built from the template below. Pass the file content read in Step 1 inline in each prompt. Subagents must not call `Read`.

**Subagent prompt template** (substitute placeholders for each criterion):

```
You are evaluating a SKILL.md file for criterion {criterion_id} — {criterion_name}.

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
- 5: Causes a runtime error or makes the file non-functional (e.g., tool called but not in allowed-tools, frontmatter absent).
- 4: Causes likely divergence across Claude instances or material misuse (e.g., vague decision point in a critical path).
- 3: Reduces quality in a non-critical path (e.g., missing example for a complex argument).
- 2: Minor quality concern, no runtime impact (e.g., unused tool listed, weak trigger phrase).
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

**Per-criterion substitutions:**

---

### C1 — Instruction clarity

- `{criterion_id}`: `C1`
- `{criterion_name}`: `Instruction clarity`
- `{criterion_definition}`: Are the steps unambiguous and deterministic? Two different Claude instances running the same file would take identical actions. Vague verbs ("handle", "process", "deal with", "manage", "address", "check", "look at") used without defining the exact action lower the score. Decision points where multiple interpretations are valid lower the score.
- `{rubric}`:
  - **5**: Every step is deterministic; no vague verbs; all conditional branches define what to do in each case; a second Claude instance would make the same decisions.
  - **4**: One or two minor ambiguities (e.g., a single "handle" without context) that would not materially change outcomes; fewer than two vague verbs or interpretation gaps.
  - **3**: Three to four ambiguities or vague decision points; a second instance might make different choices in some steps.
  - **2**: Five or more vague steps, or the overall flow is unclear; different instances would likely diverge significantly.
  - **1**: Impossible to follow consistently; most steps are undefined or rely on vague verbs with no defined behaviour; the skill cannot be reliably executed.

---

### C2 — Factual accuracy

- `{criterion_id}`: `C2`
- `{criterion_name}`: `Factual accuracy`
- `{criterion_definition}`: Does the described behaviour match verifiable ground truth? Check: (a) tools listed in `allowed-tools` match tools actually called in the body; (b) frontmatter fields are present, correctly typed, and correctly valued; (c) factual claims about tool behaviour, API conventions, or file formats are accurate. Decide autonomously which sources to cross-reference based on what is most relevant to this specific file — do not rely only on what is explicitly stated in the file.
- `{rubric}`:
  - **5**: All tools listed match tools called; frontmatter is complete and correctly typed; all factual claims are accurate.
  - **4**: One minor error (e.g., one unused tool listed, or description could be marginally more precise) with no runtime impact.
  - **3**: One required frontmatter field is missing or incorrectly typed, or one tool is called but missing from `allowed-tools` (would cause a runtime error on that path).
  - **2**: Two or more required frontmatter fields are missing or incorrect, or two or more tools are missing from `allowed-tools`.
  - **1**: Frontmatter is absent or unparseable; `allowed-tools` is empty while the body calls tools; or the tool list is entirely wrong.

---

### C3 — Overfitting vs generalisation

- `{criterion_id}`: `C3`
- `{criterion_name}`: `Overfitting vs generalisation`
- `{criterion_definition}`: Is the skill correctly scoped? Too narrow (handles only one specific case when it should generalise) and too broad (tries to be universal when it should be specific) both lower the score. Also covers: missing example invocations where they would reduce ambiguity, unhandled failure paths (missing argument, tool call failure, empty results), and absence of "Suggested next" guidance.
- `{rubric}`:
  - **5**: Skill generalises well across its intended scope; all primary failure paths are explicitly handled with defined fallback behaviour; "Suggested next" block is present and relevant.
  - **4**: Good generalisation; one uncommon failure path unaddressed or one non-critical example missing; "Suggested next" block present.
  - **3**: Most cases handled; one primary failure path missing (e.g., missing argument or empty result unaddressed) or "Suggested next" block absent; examples absent in one or two places where they would genuinely help.
  - **2**: Limited generalisation; two or more primary failure paths unaddressed; examples absent in most non-trivial steps; no follow-up guidance.
  - **1**: Highly specific or brittle; no error handling; no examples; no "Suggested next" block; any failure would leave Claude without guidance.

---

### C4 — Completeness

- `{criterion_id}`: `C4`
- `{criterion_name}`: `Completeness`
- `{criterion_definition}`: Does the skill fully achieve its stated goal? Are there gaps between what the description promises and what the body delivers? Also covers: presence and quality of all expected sections, logical ordering of steps, and description quality (accuracy and trigger-phrase richness for auto-invocation).
- `{rubric}`:
  - **5**: All expected sections are present and well-documented; steps follow logical order (setup → main action → output); description is accurate and contains two or more trigger phrases enabling reliable auto-invocation.
  - **4**: All key sections present; one section could be improved; description has one trigger phrase or could use one more.
  - **3**: Structure is readable but one expected section is missing or weak; description lacks trigger phrases making auto-invocation unreliable; or one gap exists between description and body.
  - **2**: Two or more expected sections are missing; steps feel out of order; description is vague or terse; material gaps between description and body.
  - **1**: Unstructured; description absent, empty, or unrelated to function; major sections missing; body does not deliver on what description promises.

---

### C5 — Structure (SKILL.md variant)

- `{criterion_id}`: `C5`
- `{criterion_name}`: `Structure`
- `{criterion_definition}`: Does the file follow Claude Code SKILL.md conventions? Check: (1) frontmatter fields — `name` (required, lowercase-hyphen), `description` (required), `disable-model-invocation` (required, string `"true"` not boolean), `allowed-tools` (required, comma-separated), `argument-hint` (required when skill accepts arguments), `context` (optional, only valid value `"fork"`), `agent` (optional, requires `context: fork`). No agent-file-specific fields (`tools` as standalone field). (2) Tool list accuracy — exact match between `allowed-tools` and tools called in the body; missing tools (called but not listed) are more severe than unused tools (listed but not called). (3) Body ordering — numbered steps or clear section headers, logical sequence (setup → main action → output), "Suggested next" block at the end. (4) Formatting conventions — consistent header levels, code blocks for code and tool outputs, bullet lists for options.
- `{rubric}`:
  - **5**: All required frontmatter fields present and correctly typed; exact match between `allowed-tools` and tools called; body follows numbered steps with logical sequence and "Suggested next" at the end; formatting is consistent throughout.
  - **4**: One minor issue — either one unused tool listed, or one formatting inconsistency, or `argument-hint` phrasing slightly off; no missing required fields and no missing tools.
  - **3**: One required frontmatter field is missing or incorrectly typed (e.g., `disable-model-invocation` is boolean), OR one tool called in the body is missing from `allowed-tools`, OR body ordering is informal but readable.
  - **2**: Two or more required frontmatter fields are missing or incorrect, OR two or more tools are missing from `allowed-tools`, OR presence of agent-file-specific fields (`tools` as standalone instead of `allowed-tools`).
  - **1**: Frontmatter is absent or unparseable; `allowed-tools` is empty while body calls tools; or multiple SKILL.md-specific conventions violated simultaneously making the file unloadable.

---

Spawn all 5 subagents simultaneously. Do not await any individual result before launching the remaining subagents. Wait for all 5 to complete before proceeding to Step 3.

## Step 3 — Collect and merge findings

After all 5 subagents complete:

1. Parse each subagent's JSON output to extract `criterion`, `score`, and `findings` array.
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

**Assign F-numbers** (F1, F2, ...) to the sorted findings after ranking. F1 is the highest-priority finding. "No findings" rows (for criteria with zero findings) appear after all real findings with `N/A` for severity, confidence, and priority.

**Report format** — produce exactly this structure:

```
# Skill Review: <value of `name` frontmatter field, or filename if name is missing>
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
```

**"Top Finding" cell rules:**
- The value is the `title` string of the finding for that criterion with the highest `severity × confidence` product after deduplication.
- If the criterion has no findings, the cell contains `—`.

**"No findings" display:** If a criterion subagent returns zero findings, its criterion still appears in the Criterion Scores table with its score and `—` in the Top Finding column. Additionally, the criterion appears in the Ranked Findings section as a row with the label `No issues found` and `N/A` for severity, confidence, and priority:

```
### F<N> — No issues found (C<X>, severity N/A, confidence N/A, priority N/A)
```

This row has no **Detail** or **Suggestion** lines. "No findings" rows appear after all real findings (since N/A priority sorts last).

**Summary section:** After the Ranked Findings section, produce:

```
## Summary
<2–4 sentence narrative. Main strengths first. Name the top 2–3 findings by criterion ID (e.g., "C1", "C3"). End with a directional recommendation — e.g., "Addressing C1 and C3 would move this skill from 'Needs work' to 'Good'.">
```

## Step 5 — Present the report

Output the completed report in the conversation. Do not write any files. Do not modify any files. Do not call any tools after Step 1.

Suggested next: (1) `/claude-helper:review-all <directory>` — batch-review all SKILL.md files in a directory and compare scores  (2) Edit the skill file to address the highest-impact findings, then re-run this review to verify improvement
