---
name: create-skill
description: Generate compressed SKILL.md or .claude/agents/ definitions via skill-creator + caveman compress
allowed-tools: [Bash, Read, Write, Glob, Grep, Skill]
argument-hint: "[--type skill|agent] [--name <name>] <description>"
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Generate new SKILL.md or agent definition file w/ caveman ultra compression.

## Arg Parsing

Parse `$ARGUMENTS`:
- `--type` → `skill` (default) or `agent`
- `--name` → kebab-case name (required)
- Remaining text → description (required)

Validation:
- `--name` must be kebab-case (`^[a-z][a-z0-9]*(-[a-z0-9]+)*$`) → err + stop if not
- Description non-empty → err + stop if missing
- `--type` not `skill`/`agent` → err + stop

## Pass 1 — Generation

Call `Skill(skill="example-skills:skill-creator")` w/ enriched prompt containing:

**Context to include:**
- Target type: skill or agent
- Name + description from args
- Caveman ultra rules:
  - Drop: articles (a/an/the), filler, hedging, conjunctions when clear
  - Abbreviate: fn/impl/config/req/res/DB/auth/msg/param/arg/deps/env/dir/repo/cmd/exec/init/sync/info/orig/desc/prev/cur/num/val/err/ctx/ref/opt/spec/max/min/avg/diff/fmt/gen/ver
  - Syntax: fragments > sentences, arrows for causality, semicolons merge short items
  - Preserve: code blocks, inline code, URLs, file paths, MCP tool names, tables
- Output directive template: `> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.`
- CPM conventions:
  - Skills invoked as `/proj:<name>`, `/worktree:<name>`
  - MCP tool format: `mcp__plugin_<plugin>_<plugin>__<tool_name>`
  - Agent delegation: ASK_USER + PLAN_ESCALATION protocols (ref run/SKILL.md appendix)
  - `context: fork` + `agent: general-purpose` frontmatter for autonomous skills (no interactive Q&A, no plan mode mid-exec)
- For `--type agent`: include `tools` list, `model` field, tool restriction notes in frontmatter

**Fallback**: skill-creator unavailable → generate directly using above conventions + 2-3 existing SKILL.md files as reference templates (read from `plugins/proj/skills/status/SKILL.md`, `plugins/proj/skills/todo/SKILL.md`).

## Pass 2 — Compress

Run deterministic compression:

```
python3 ~/projects/tracking/claude-project-manager/caveman-compress/scripts/compress.py <output-file>
```

**Fallback**: compress.py missing/fails → warn "Compression script unavailable, using model-only compression." Skip pass 2; pass 1 output used as-is.

## Validation

Check output for:
1. Valid YAML frontmatter (name, description, allowed-tools present)
2. Output directive line present after frontmatter
3. No articles (a/an/the) outside code blocks, inline code, URLs
4. Abbreviations used consistently (fn not function, impl not implementation, config not configuration, etc.)

Failures → show list, offer retry (re-run pass 1 + 2 w/ failure feedback).

## File Placement

- `--type skill` → `plugins/proj/skills/<name>/SKILL.md`
  - Create dir if needed: `mkdir -p plugins/proj/skills/<name>/`
- `--type agent` → `.claude/agents/<name>.md`
  - Create dir if needed: `mkdir -p .claude/agents/`

## Prerequisites

None. Works in any project dir.

## Err Handling

- Missing `--name` → "Name required. Usage: `/proj:create-skill --name <name> <description>`"
- Invalid name format → "Name must be kebab-case (e.g. `my-skill`)"
- Empty description → "Description required"
- skill-creator unavailable → fall back to direct generation
- compress.py missing → fall back to model-only compression, warn
- Validation fails → show failures, offer retry

## Output

Confirm file created w/ path. Show validation results (pass/fail per check).

Suggested next: `1. /proj:todo add "Test <name> skill"` -- track testing | `2. Read <output-path>` -- review generated file
