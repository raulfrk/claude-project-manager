---
name: review-skill
description: Review a SKILL.md file using a 7-criterion parallel framework. Produces scored findings ranked by severity and confidence. Use when asked "review this skill", "check skill quality", or "audit SKILL.md".
disable-model-invocation: "true"
allowed-tools: Read, Task, Write
argument-hint: "<path-to-SKILL.md>"
---

Review the SKILL.md file at: $ARGUMENTS

## Step 1 — Read the file

Call `Read` with the path provided in `$ARGUMENTS`. If the file does not exist or cannot be read, stop and report: "Cannot read file at <path>: <error>. Provide the correct absolute path to a SKILL.md file."

Store the file content in memory for passing to subagents in Step 2. Do not call `Read` again after this step.

## Step 2 — Spawn 7 parallel criterion subagents

Spawn exactly 7 `Task` subagents simultaneously — one per criterion (C1 through C7). Launch all 7 in the same step before waiting for any results. Wait for all 7 to complete before proceeding to Step 3.

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
      "confidence": <integer 1–5>,
      "location": "<the specific section, step, or line where the issue occurs (e.g., 'Step 3', 'frontmatter line 2', 'line 42'). If the issue is not localized, use 'general'>"
    }
  ]
}

The "findings" array may be empty if no issues are found. The "score" field is always present. The "location" field is always present for each finding.

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

### C6 — Devil's Advocate

- `{criterion_id}`: `C6`
- `{criterion_name}`: `Devil's Advocate`
- `{criterion_definition}`: Actively attempt to find ways the skill/agent could fail, be misused, or produce incorrect results. Check four categories: (a) adversarial inputs — malformed, extremely large, empty, or boundary-case inputs that break assumptions (e.g., path traversal in a filename argument, unicode edge cases, input that matches a valid format but is semantically nonsensical); (b) environmental failures — what happens when permissions are denied, network is unavailable, disk is full, a tool times out, or a dependency is missing? (c) misuse potential — could a user misinterpret the instructions and invoke the skill in an unintended way with harmful consequences? Are guardrails and scope boundaries stated clearly enough to prevent misuse? (d) silent failures — can the skill produce plausible but wrong output without any error indication (e.g., a tool returns stale data, a grep matches the wrong line, a JSON field is missing but the skill proceeds with a default)? This criterion is NOT about general scope coverage or missing primary failure paths (that is C3) — it is about resilience to surprise, adversarial conditions, and degradation.
- `{rubric}`:
  - **5**: Skill explicitly anticipates adversarial inputs and environmental limits; gracefully degrades or clearly reports errors when conditions are abnormal; no plausible silent-failure vectors; instructions are unambiguous about guardrails, safety boundaries, and intended use; a malicious or confused user cannot easily cause harm by misusing the skill.
  - **4**: Good resilience overall; one edge case not explicitly handled (e.g., very large input, permission error on a secondary path, or a tool timeout) but unlikely to occur in normal use; at most one low-severity silent-failure vector exists and is acknowledged or mitigated by context.
  - **3**: One significant adversarial or environmental failure path is unaddressed (e.g., no timeout handling for a long-running tool, no validation of input size or format, no fallback when permissions are denied); OR one clear silent-failure vector exists (e.g., tool returns no error for malformed input and skill proceeds); OR instructions are ambiguous about intended use boundaries in a way that could lead to misuse.
  - **2**: Two or more adversarial or environmental failure paths are unaddressed; multiple silent-failure vectors are present; instructions are vague about guardrails and scope; skill could easily be misused with bad consequences in an untrusted environment.
  - **1**: Skill is brittle to any adversarial input or environmental variation; multiple unaddressed silent-failure vectors; no guardrails stated; skill is unsafe for untrusted or unconstrained environments; any unexpected condition causes undefined behaviour.

---

### C7 — End-to-End Flow Integrity

- `{criterion_id}`: `C7`
- `{criterion_name}`: `End-to-End Flow Integrity`
- `{criterion_definition}`: Does the skill's data flow form a coherent chain from input to output? Mentally simulate executing the skill from start to finish, tracing data through every step. Check: (a) data flow between steps — does each step consume exactly what the previous step produces? Are variable names consistent across steps? (b) output format consistency — if Step 2 stores data in a variable, does Step 3 reference the same variable? If Step 2 produces JSON, does Step 3 parse JSON? (c) state management — is any required state lost or implicitly assumed between steps? (d) ordering dependencies — could any steps be reordered without the skill noticing, indicating incomplete coupling? (e) final output — does the last step produce exactly what the description promises?
- `{rubric}`:
  - **5**: Complete data flow from input to output; every step consumes exactly what the previous step produces; variable names are consistent; data formats match across step boundaries; final output exactly matches description.
  - **4**: One minor data flow gap (e.g., a variable name inconsistency or assumed state that would not cause failure); final output matches description.
  - **3**: One step's output format doesn't exactly match the next step's expected input (e.g., Step 2 produces "results in memory" but Step 3 calls a tool expecting file output); or final output partially matches description; or one implicit state assumption between steps.
  - **2**: Two or more data flow breaks; or one break that would cause a runtime error; or final output significantly differs from what description promises; or critical missing state management.
  - **1**: Data flow is incoherent; steps do not logically connect; the skill cannot produce its stated output; variable chains are broken or circular.

---

Spawn all 7 subagents simultaneously. Do not await any individual result before launching the remaining subagents. Wait for all 7 to complete before proceeding to Step 3.

## Step 3 — Collect and merge findings

After all 7 subagents complete:

1. Parse each subagent's JSON output to extract `criterion`, `score`, and `findings` array.
2. Flatten all findings from all 7 subagents into a single list.

**Deduplication algorithm** (apply before ranking):

Two findings are duplicates if they describe the same underlying structural problem in the same location of the file, regardless of which criterion they come from.

- Compare `title` fields: if two titles describe the same issue (semantically equivalent, not necessarily lexically identical), they are candidates.
- Compare `detail` fields: if both `title` and `detail` point to the same location and the same root cause, they are duplicates.
- Keep the finding with the higher `severity × confidence` product. If tied, keep the finding from the lower-numbered criterion (C1 before C2, etc.).
- Discard the lower-priority duplicate.
- When in doubt whether two findings are duplicates, treat them as distinct. Deduplication is conservative — err on the side of inclusion.
- **C3/C6 overlap**: C3 covers primary failure paths (missing argument, tool error, empty results); C6 covers adversarial inputs, environmental failures, silent failures, and misuse. When a finding could belong to either: if it involves an input/environment that is "correct by the skill's stated rules but extreme or adversarial", assign to C6. If it is a "standard failure category the skill should handle as part of its normal scope", assign to C3. Tie-break to C3.
- **C4/C7 overlap**: C4 covers completeness of sections and description quality; C7 covers data flow coherence between steps. When a finding could belong to either: if it concerns whether a section is present or the description is accurate, assign to C4. If it concerns whether data flows correctly from one step to the next, assign to C7. Tie-break to C4.

## Step 4 — Rank findings and produce the report

**Ranking:** Sort the deduplicated findings list by `severity × confidence` descending. Highest product first. Tie-breaking: lower-numbered criterion first (C1 before C2, etc.); if still tied (same criterion), order is arbitrary.

**Overall score:** `round(mean(C1_score, C2_score, C3_score, C4_score, C5_score, C6_score, C7_score), 1)`

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
| C6 | Devil's Advocate | <score>/5 | <title of highest-priority finding for C6, or "—"> |
| C7 | End-to-End Flow Integrity | <score>/5 | <title of highest-priority finding for C7, or "—"> |

## Ranked Findings

<Omit this section entirely if the deduplicated findings list is empty.>

### F<N> — <finding title> (C<X>, severity <S>/5, confidence <K>/5, priority <S×K>)
**Location**: <location field verbatim>
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

Output the completed report in the conversation. Do not call any tools in this step. Proceed to Step 6 after presenting the report.

## Step 6 — Save the review report to file

After presenting the report, persist it to disk:

1. **Infer tracking directory:**
   - Read `CLAUDE.md` from the current git repository root (`git rev-parse --show-toplevel`). Look for a line matching `**Tracking**:` or `Tracking:` and extract the path.
   - If no CLAUDE.md or no Tracking field, fall back to `~/projects/tracking/` plus the repository directory name (e.g., `~/projects/tracking/claude-project-manager/`).
   - If not in a git repository, use `$HOME/.claude/reviews/` as the tracking directory and skip appending `reviews/` (it is the reviews directory).

2. **Slugify the reviewed filename:**
   - Take the basename of `$ARGUMENTS` without extension (e.g., `SKILL.md` becomes `SKILL`, `My Cool Agent.yaml` becomes `My Cool Agent`).
   - Convert to lowercase.
   - Replace every non-alphanumeric character with a hyphen (`-`).
   - Collapse consecutive hyphens into a single hyphen.
   - Strip leading and trailing hyphens.

3. **Construct file path:**
   - `<tracking_dir>/reviews/<slugified_name>-<YYYY-MM-DD>.md`
   - If the file already exists at that path, overwrite it (re-review replaces previous).
   - Create the `reviews/` directory if it does not exist by calling `Bash(mkdir -p <tracking_dir>/reviews)`.

4. **Build YAML frontmatter** with these fields in order:
   ```yaml
   ---
   type: skill
   reviewed_file: <absolute path from $ARGUMENTS>
   reviewed_name: <slugified name from step 2>
   date: <YYYY-MM-DD>
   overall_score: <float, 1 decimal>
   band: <band name>
   criterion_scores:
     C1: <score>
     C2: <score>
     C3: <score>
     C4: <score>
     C5: <score>
     C6: <score>
     C7: <score>
   findings:
     - id: F1
       criterion: <criterion_id>
       title: "<title>"
       detail: "<detail>"
       suggestion: "<suggestion>"   # omit key entirely if no suggestion
       severity: <int>
       confidence: <int>
       file: <absolute path of reviewed file>
       location: "<location>"
       status: pending
       todo_id: null
     - id: F2
       ...
   ---
   ```
   - For "No issues found" placeholder rows, include them in the findings array with `severity: null`, `confidence: null`, `status: pending`, `todo_id: null`, and omit `suggestion`, `detail`, `file`, `location`.
   - Quote any string values containing colons, quotes, or special YAML characters.

5. **Build markdown body:** Use the report from Step 5 verbatim (the full rendered report including the header, criterion scores table, ranked findings, and summary).

6. **Construct full file content:** Concatenate the YAML frontmatter (between `---` delimiters) followed by a blank line and the markdown body.

7. **Write the file:** Call `Write` with the constructed file path and the full file content.

8. **Display:** Output exactly: `Review saved to: <file path>`

9. Do not call any tools after `Write` completes.

Suggested next: (1) `/claude-helper:review-all <directory>` — batch-review all SKILL.md files in a directory and compare scores  (2) Edit the skill file to address the highest-impact findings, then re-run this review to verify improvement
