# Tier-2 Lint: Section-Map Drift

Subagent-prompt template. Used by `/wiki:lint --tier=2`.

> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

> **SYNC CONTRACT**: This prose is the runtime impl. `plugins/wiki/server/server/tools/lint.py::check_section_map_drift` is a parallel reference impl pinned by tests. If you change the algorithm here (anchor markers, sentinel semantics, output kinds), update lint.py too — and vice versa. See todo 736 for plan to consolidate.

## Purpose

Detect drift between `wiki.yaml::session_ingest.section_map` keys and `## H2` headings in `/proj:save` SKILL.md's session-file template (step 7). Drift → ingest silently degrades to wholesale extraction.

## Path Discovery

Locate `/proj:save` SKILL.md. Check in order:

1. `~/.claude/plugins/marketplaces/<marketplace-id>/cpm/proj/skills/save/SKILL.md` — installed cpm cache. Use glob `~/.claude/plugins/marketplaces/*/cpm/proj/skills/save/SKILL.md` (first match).
2. Repo-local `plugins/proj/skills/save/SKILL.md` — present when running from cpm dev checkout. Detect via: `cwd` contains `claude-project-manager` OR `plugins/proj/` exists relative to cwd.

None resolve → emit single warning: `WARN: Could not locate /proj:save SKILL.md for drift check` + skip check entirely. Do NOT fail lint.

## Detection Algorithm

1. Load `wiki.yaml` via `Read` → parse `session_ingest.section_map` → extract keys list. Empty or missing → `section_map_keys = []`.
2. Read located SKILL.md via `Read`.
3. Extract H2 headings from session-file template block:
   - Find `<!-- session-template-start -->` HTML comment marker in save SKILL.
   - From that point forward, find opening triple-backtick ` ``` ` fence, then scan until closing ` ``` ` fence ends the template block.
   - Within that block, regex-extract all `^## (.+)$` lines → `template_h2s` list (whitespace-trimmed).
   - If marker not found OR fence not found → emit single `template_unparseable` warning + skip drift comparison entirely (do NOT emit per-key warnings).
4. Set diff:
   - `missing_from_template = section_map_keys - template_h2s` (key in config but no matching H2)
   - `missing_from_config = template_h2s - section_map_keys` (H2 in template but no config key)

## Output Format

One warning per finding:

```
WARN: section_map key 'X' has no matching H2 in /proj:save template
WARN: /proj:save H2 'X' has no section_map entry
```

No findings → emit nothing (silent pass).

## Template

```
You are a wiki lint agent checking for drift between wiki.yaml section_map and /proj:save SKILL.md.

WIKI_YAML: {wiki_yaml_path}
SAVE_SKILL_PATH: {save_skill_path}   ← resolved via path-discovery above; empty string if not found

MCP TOOLS AVAILABLE (READ-ONLY):
- Read

PROTOCOL:
1. Read {wiki_yaml_path} → parse session_ingest.section_map → collect keys as section_map_keys list.
   Empty / missing key → section_map_keys = [].
2. SAVE_SKILL_PATH empty → emit "WARN: Could not locate /proj:save SKILL.md for drift check"; return.
3. Read {save_skill_path}.
4. Find `<!-- session-template-start -->` marker → scan to opening ``` fence → scan to closing ``` fence.
   Within block: regex-extract ^## (.+)$ lines → template_h2s (stripped).
   Marker or fence not found → emit {"kind": "template_unparseable", ...}; return.
5. Compute:
   missing_from_template = [k for k in section_map_keys if k not in template_h2s]
   missing_from_config   = [h for h in template_h2s if h not in section_map_keys]
6. For each k in missing_from_template:
     emit "WARN: section_map key '{k}' has no matching H2 in /proj:save template"
   For each h in missing_from_config:
     emit "WARN: /proj:save H2 '{h}' has no section_map entry"
7. No findings → silent pass.

Return JSON: {
  warnings: [
    {"kind": "missing_from_template" | "missing_from_config", "value": "<key or H2>", "message": "<full WARN string>"},
    ...
  ]
}
```
