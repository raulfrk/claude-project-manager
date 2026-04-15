# Superpowers + CPM Integration Design

**Date:** 2026-04-15
**Todo:** 626

---

## Goal

Integrate Superpowers (obra/superpowers-marketplace) with CPM so that Superpowers owns the development workflow (brainstorming → planning → execution) while CPM owns todo tracking. All Superpowers-generated documents (specs, plans) are stored in the CPM tracking directory, never in the project repo.

## Architecture

Two changes, no new code:

1. **`installer/claudemd.py`** — new `SUPERPOWERS_SECTION` constant + helper functions to add/remove/detect it independently from the existing CPM managed block.
2. **`installer/app.py`** — wire up superpowers detection at the existing `ensure_managed_section` call site.

The injected CLAUDE.md rules use Superpowers' own "user instructions always take precedence" contract to redirect all doc-writes to the CPM tracking dir without forking any skill files. Superpowers skills remain unchanged and upgrade-safe.

## Components

### 1. `installer/claudemd.py`

**New markers** (independent from CPM block):
```
<!-- cpm-superpowers:start -->
<!-- cpm-superpowers:end -->
```

**New functions:**
- `ensure_superpowers_section(path: Path) -> bool` — add or update the block; returns True if file modified
- `remove_superpowers_section(path: Path) -> bool` — remove block; returns True if file modified
- `_is_superpowers_installed() -> bool` — reads `~/.claude/plugins/installed_plugins.json`; returns True if any key matches `*@superpowers-marketplace`; returns False on missing file or malformed JSON (logged as warning)

**`SUPERPOWERS_SECTION` content:**

```markdown
## Superpowers + CPM Integration

**Project repo is read-only for all Superpowers skills EXCEPT `superpowers:executing-plans` and `superpowers:subagent-driven-development`.** Writing docs, specs, plans, notes, scripts, or any artifact to the project repo from `superpowers:brainstorming`, `superpowers:writing-plans`, `superpowers:finishing-a-development-branch`, or any other Superpowers skill is FORBIDDEN. Only `executing-plans` and `subagent-driven-development` may write to the project repo (code changes only).

When using `superpowers:brainstorming` or `superpowers:writing-plans`:

**Step 0 — Resolve paths**: call `mcp__plugin_proj_proj__proj_session_context` → get `config.tracking_dir` + `project.name`. If no project loaded, prompt user to `/proj:load` first. If declined, use standalone mode.

**Step 1 — Ask for todo linkage**: "Is this brainstorm/plan tied to a CPM todo? If yes, which ID?" before starting.

**Todo-linked mode** (todo ID provided + project loaded):
- Spec (brainstorming output): call `mcp__plugin_proj_proj__content_set_requirements(todo_id=<id>, requirements=<spec>)`
- Plan (writing-plans output): write to `<tracking_dir>/<project>/todos/<id>/plan.md`
- Git flush: `mcp__plugin_proj_proj__tracking_git_flush(commit_message="Define: <id>")`

**Standalone mode** (no todo linked):
- Spec: write to `<tracking_dir>/<project>/docs/specs/YYYY-MM-DD-<topic>-design.md`
- Plan: write to `<tracking_dir>/<project>/docs/plans/YYYY-MM-DD-<feature>.md`
- Git flush: `mcp__plugin_proj_proj__tracking_git_flush(commit_message="Spec: <topic>")`

**CPM owns todo tracking** — do not create Superpowers task lists, todo files, or checklists. Use CPM todos instead.
```

### 2. `installer/app.py`

At the existing `ensure_managed_section` call site (~line 605), add:

```python
ensure_managed_section(Path.home() / ".claude" / "CLAUDE.md")
if _is_superpowers_installed():
    ensure_superpowers_section(Path.home() / ".claude" / "CLAUDE.md")
else:
    remove_superpowers_section(Path.home() / ".claude" / "CLAUDE.md")
```

In the uninstall path (~line 775), add alongside `remove_managed_section`:

```python
remove_superpowers_section(claude_md)
```

Import: add `ensure_superpowers_section`, `remove_superpowers_section`, `_is_superpowers_installed` to the existing `from installer.claudemd import ...` line.

## Data Flow

```
CPM install/reinstall
  → ensure_managed_section()       # CPM rules block
  → _is_superpowers_installed()?
      yes → ensure_superpowers_section()   # integration rules block
      no  → remove_superpowers_section()   # clean up if previously present

Session start
  → CLAUDE.md loaded (both blocks visible to model)
  → User: /superpowers:brainstorming
      → model reads integration rules
      → proj_session_context() → resolve tracking_dir + project.name
      → ask: todo-linked or standalone?
      → run brainstorming skill normally
      → spec-write step: content_set_requirements (linked) OR tracking/docs/specs/ (standalone)
      → tracking_git_flush

CPM uninstall
  → remove_managed_section()
  → remove_superpowers_section()
```

## Error Handling

### Wizard (Python)

| Scenario | Handling |
|---|---|
| `installed_plugins.json` missing | `_is_superpowers_installed()` → `False`, silent |
| `installed_plugins.json` malformed JSON | `json.JSONDecodeError` caught → `False`, log warning |
| CLAUDE.md write fails (permissions) | `OSError` propagates — existing `_atomic_write` behaviour; wizard surfaces error |
| Superpowers removed after CPM install | Next CPM reinstall detects absence → `remove_superpowers_section` cleans up |

### Runtime (CLAUDE.md rule enforcement)

| Scenario | Handling |
|---|---|
| No active CPM project at brainstorm start | Prompt `/proj:load`; if declined → standalone mode |
| `proj_session_context` fails | Fall back to standalone mode, warn user, ask for tracking dir path |
| Todo ID not found | Warn + offer: retry with correct ID or proceed standalone |
| Tracking dir doesn't exist | Surface error, do NOT fall back to writing project repo |

## Testing

### Unit tests — `installer/tests/test_claudemd.py`

- `test_ensure_superpowers_section_creates` — empty CLAUDE.md → section injected
- `test_ensure_superpowers_section_updates` — stale section → replaced with current content
- `test_ensure_superpowers_section_idempotent` — already current → returns False, no write
- `test_remove_superpowers_section` — section present → removed cleanly
- `test_remove_superpowers_section_missing` — no section → returns False, no error
- `test_is_superpowers_installed_true` — mocked `installed_plugins.json` with `superpowers@superpowers-marketplace` key → True
- `test_is_superpowers_installed_false` — json present, no superpowers key → False
- `test_is_superpowers_installed_missing_file` — file absent → False
- `test_is_superpowers_installed_malformed_json` — bad JSON → False, no exception raised

### Integration tests — `installer/tests/test_integration_screens.py`

- Install worker: assert `ensure_superpowers_section` called when superpowers detected in `installed_plugins.json`
- Uninstall worker: assert `remove_superpowers_section` called

### Manual verification

1. Install CPM with Superpowers present → confirm `SUPERPOWERS_SECTION` appears in `~/.claude/CLAUDE.md`
2. Start session → invoke `/superpowers:brainstorming` on a todo → confirm spec written to tracking dir, not project repo
3. Invoke standalone brainstorm → confirm spec in `tracking/<proj>/docs/specs/`
4. Uninstall CPM → confirm both blocks removed from CLAUDE.md

## Out of Scope

- Forking or modifying any Superpowers skill files
- Syncing Superpowers plan steps to CPM child todos (future work)
- Detecting Superpowers installation changes mid-session (requires restart)
- Supporting multiple Superpowers marketplaces simultaneously

## Q&A Transcript

**Q:** Will brainstorming always be tied to a CPM todo or sometimes standalone?
**A:** Both — option B. Tied to todo when in context of a specific todo; standalone otherwise.

**Q:** Should the Superpowers spec replace or coexist with CPM's requirements.md/research.md?
**A:** Replace (option A) — spec becomes the single source of truth via `content_set_requirements`. `/proj:define` is retired.

**Q:** How to implement path redirection — CLAUDE.md override, skill fork, or wrapper skill?
**A:** CLAUDE.md override + single integration block (option 4). No skill forking, upgrade-safe.

**Q:** Should Superpowers be prohibited from dirtying the project repo entirely?
**A:** Yes — all files prohibited except code writes inside `executing-plans` / `subagent-driven-development`.

**Q:** How to express the write-prohibition exception?
**A:** Skill-scoped (option C) — only `executing-plans` and `subagent-driven-development` may write to project repo.
