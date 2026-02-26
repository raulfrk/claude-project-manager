# claude-project-manager — Project Conventions

## Key Decisions

- **Version bumping**: version must be bumped in both `plugins/<name>/.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` together
- **Hooks**: require an explicit `"hooks"` key in `plugin.json` to be recognized
- **Skills location**: `plugins/<name>/skills/<skill-name>/SKILL.md`
- **Storage**: project tracking data lives in `~/projects/tracking/` (per global `~/CLAUDE.md`)

## Structure

```
.claude-plugin/marketplace.json     # Marketplace catalog (top-level)
plugins/<name>/
  .claude-plugin/plugin.json        # Plugin manifest
  skills/<skill-name>/SKILL.md      # Skill definitions
```
