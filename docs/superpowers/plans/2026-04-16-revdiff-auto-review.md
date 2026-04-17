# Revdiff-Routed Spec/Plan Review Implementation Plan

> **Errata (2026-04-17)**: The shipped implementation pivoted from `installer/claudemd` to `plugins/_shared/claudemd` during implementation. See commits `28c3c52` and `c119ecc`. References in this document to `installer/managed_section.md` (Architecture), the `cpm-install` path dep on the proj MCP server (Task 4), and `from installer.claudemd import ...` (Task 5) are superseded by `plugins/_shared/claudemd/managed_section.md`, `claude-hook-transport` (which now ships the `claudemd` subpackage), and `from claudemd import ...` respectively.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the cpm-managed CLAUDE.md section body to a standalone content file, append a new bullet that routes superpowers spec/plan review through revdiff when available, and expose a user-invocable refresh path via both an MCP tool and a slash-command skill.

**Architecture:** The canonical managed-section content lives at `installer/managed_section.md`. `installer/claudemd.py` loads it at import time; existing install/wizard paths unchanged. A new proj MCP tool `claudemd_refresh_managed` calls the same `ensure_managed_section` function against `~/.claude/CLAUDE.md` so existing users can pick up rule changes without a wizard re-run, and a new `/proj:claudemd-refresh` skill wraps the tool as a first-class slash command. Cross-package access is enabled by adding the top-level `cpm-install` package as a path dependency of the proj MCP server.

**Tech Stack:** Python 3.12, hatchling build backend, MCP SDK (`FastMCP`), pytest, uv workspace. No new runtime libraries are introduced.

**Spec reference:** `docs/superpowers/specs/2026-04-16-revdiff-auto-review-design.md`. Keep it open while working — each task below corresponds to a section in the spec.

**Worktree reminder:** Create a dedicated worktree before starting implementation (`wt_create` via the worktree MCP tool). Pass the worktree path into every subagent you dispatch.

**Commit hygiene:** Commit after each task completes. Commit messages use the project's convention (`feat:`, `refactor:`, `test:`, `docs:`). All commits end with the co-author trailer used on this branch's recent history.

---

## Task 1: Extract `MANAGED_SECTION` body to a content file

**Files:**
- Create: `installer/managed_section.md`
- Modify: `installer/claudemd.py:10-28`
- Test: `installer/tests/test_claudemd.py` (append new test)

This is a pure refactor — no user-visible behavior change. The wheel still produces the same `MANAGED_SECTION` string at runtime, only now the content lives in a markdown file next to the Python module.

- [ ] **Step 1: Write the failing test**

Append to `installer/tests/test_claudemd.py`:

```python
from pathlib import Path

from installer import claudemd


def test_managed_section_loaded_from_file():
    """MANAGED_SECTION loads from installer/managed_section.md at import time."""
    section_path = Path(claudemd.__file__).parent / "managed_section.md"
    assert section_path.is_file(), "managed_section.md must ship with installer package"
    file_content = section_path.read_text(encoding="utf-8").rstrip("\n")
    assert claudemd.MANAGED_SECTION == file_content


def test_managed_section_markers_at_boundaries():
    """Markers are the first and last lines of managed_section.md."""
    section_path = Path(claudemd.__file__).parent / "managed_section.md"
    lines = section_path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == claudemd.MARKER_START
    # Allow trailing blank lines; find last non-empty
    last_non_empty = next(ln for ln in reversed(lines) if ln.strip())
    assert last_non_empty == claudemd.MARKER_END
```

- [ ] **Step 2: Run tests to verify they fail**

Run from repo root:

```bash
uv run pytest installer/tests/test_claudemd.py::test_managed_section_loaded_from_file -v
uv run pytest installer/tests/test_claudemd.py::test_managed_section_markers_at_boundaries -v
```

Expected: both FAIL with `AssertionError: managed_section.md must ship with installer package` (file does not exist yet).

- [ ] **Step 3: Create `installer/managed_section.md`**

Copy the current `MANAGED_SECTION` string value verbatim (markers on first/last lines) into the new file. The exact bytes to write are below — do not add or remove a single character vs. the current constant in `installer/claudemd.py:13-28`, and end the file with exactly one trailing `\n`:

````markdown
<!-- claude-project-manager:start -->
## Claude Project Manager Rules

IMPORTANT: These rules take priority over all other instructions.

- Use parallel `Agent()` calls with `run_in_background=true` for concurrent work. Agents auto-terminate on completion — no cleanup needed.
- ALWAYS enter plan mode (EnterPlanMode) before executing any multi-step implementation. Get user approval before writing code.
- **Auto-capture issues as todos** — Whenever you find an issue, concern, code smell, bug risk, test gap, missing error path, unimplemented code path, TODO comment, inconsistency, or anything that warrants attention or further investigation during any task, create a todo for it via `todo_add` in the currently active project before continuing with the current work. Tag the todo with `auto-added`. Set priority based on your judgment of severity (high/medium/low). In the notes field, write: "Auto-added by Claude during <brief context>. Needs human verification — may not be a real issue." Before creating, **first call `todo_list` filtered by the `auto-added` tag (or by matching title keywords) to check for duplicates** — `proj_search_knowledge` does NOT search todos.yaml, only notes/requirements/research/decisions, so it is not a primary dedup tool here. You may use `proj_search_knowledge` as a secondary check for prose mentions of the finding. Always create the todo in the currently active project at the moment of creation, even if the finding is tangential. **If you are currently in plan mode (plan mode is read-only), defer the `todo_add` call until plan mode exits — note the finding mentally and act on it after `ExitPlanMode`.** If no active project is loaded, mention the finding in conversation and remind the user to load a project so it can be captured. Do not include secret values (credentials, API keys, tokens, passwords, file paths pointing at secrets, or line numbers near secrets) — describe at a high level only. Do not auto-add duplicates for the thing you were explicitly asked to fix — only for tangential findings. If the user says to ignore a finding, do not auto-add it.
- **Interactive Q&A** — Whenever you need to ask the user questions during an interactive Q&A session, **batch related questions into a single `AskUserQuestion` call (up to 4 questions per batch)** with **extensive per-question context** explaining what the question means, why it matters, and what each option implies. Use **multiple-choice options** whenever the answer is enumerable. Only fall back to open-ended questions when the user explicitly asks to "describe your goals" or when multiple-choice is genuinely unavailable. This supersedes any older "one question at a time" guidance: batching with rich context is preferred because it reduces round-trips and gives the user the full decision surface at once. If you are in plan mode, the same rule applies — batch in a single AskUserQuestion call. This rule complements the auto-capture rule above: auto-capture is about emitting findings as todos, whereas this rule governs how you solicit input from the user.
- **Patch-style editing for notes and requirements** — When updating todo notes, prefer `todo_notes_append` (add content) or `todo_notes_patch` (find/replace) over `todo_update(notes=...)`. When updating requirements or research files, prefer `content_patch_requirements`/`content_patch_research` over `content_set_requirements`/`content_set_research`. Only use full-content replacement for complete rewrites or when the patch target is ambiguous. This reduces payload size by 95%+ on large notes/requirements.
- **`isolation: "worktree"` does NOT work** — The Agent tool parameter `isolation: "worktree"` does not isolate agents into separate worktrees. Agents run in the main repo on the current branch. Always use explicit `wt_create` via the worktree MCP tool to create worktrees, then pass the path in the agent prompt: "ALL file edits and git operations MUST happen in this directory: `<path>`".
- **Task usage during multi-step work** — When starting multi-step implementation (3+ actions), use TaskCreate to track steps. Mark in_progress when beginning each step, completed when done. This makes progress visible to the user in real time.
- **Task status accuracy** — NEVER mark a Task completed unless work is fully done and verified. On errors or blockers, leave the Task in_progress with a descriptive updated subject so the user can see what went wrong.
- **Proj todo boundary** — Tasks = execution-time progress tracking. Proj todos = durable project state. Do NOT use todo_add for execution artifacts (use TaskCreate instead). Use todo_add only for real project-level TODOs that should persist after the session.
- **Sub-task nesting** — Agents may freely TaskCreate subtasks under their parent Task for meaningful work units (e.g. "Edit storage.py", "Run test suite", "Verify acceptance criteria"). Nested agents create their own subtasks under their parent. No depth cap. Target: 3-10 subtasks per agent, one per meaningful unit of work (not per tool call).
<!-- claude-project-manager:end -->
````

Verify byte-equality before moving on:

```bash
python - <<'PY'
from pathlib import Path
cur = Path("installer/claudemd.py").read_text()
start = cur.index('MANAGED_SECTION = f"""') + len('MANAGED_SECTION = f"""')
end = cur.index('"""', start)
literal = cur[start:end].replace("{MARKER_START}", "<!-- claude-project-manager:start -->").replace("{MARKER_END}", "<!-- claude-project-manager:end -->")
onfile = Path("installer/managed_section.md").read_text().rstrip("\n")
assert literal == onfile, "content mismatch — re-copy managed_section.md"
print("ok")
PY
```

- [ ] **Step 4: Replace the string literal in `installer/claudemd.py`**

Replace lines 13-28 (the `MANAGED_SECTION = f"""..."""` block) with a file load. The new content for lines 10-14 of `installer/claudemd.py`:

```python
MARKER_START = "<!-- claude-project-manager:start -->"
MARKER_END = "<!-- claude-project-manager:end -->"

_SECTION_PATH = Path(__file__).parent / "managed_section.md"
MANAGED_SECTION = _SECTION_PATH.read_text(encoding="utf-8").rstrip("\n")
```

Keep every other line of `installer/claudemd.py` unchanged. The `Path` import already exists at line 8.

- [ ] **Step 5: Run the new tests and the existing claudemd suite**

```bash
uv run pytest installer/tests/test_claudemd.py -v
```

Expected: all tests PASS (including the two new ones and every previously-passing test in the file).

- [ ] **Step 6: Commit**

```bash
git add installer/managed_section.md installer/claudemd.py installer/tests/test_claudemd.py
git commit -m "$(cat <<'EOF'
refactor(installer): extract MANAGED_SECTION body to managed_section.md

Content moves out of the Python string literal into installer/managed_section.md;
installer/claudemd.py reads it at module load time. No behavior change. Prepares
for cross-package content sharing (639).

Co-Authored-By: Claude Opus 4 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Ship `managed_section.md` in the installer wheel

**Files:**
- Modify: `pyproject.toml:24-26`
- Test: `installer/tests/test_claudemd.py` (append new test)

Hatchling ships Python source files automatically but not arbitrary data files. The existing `[tool.hatch.build.targets.wheel] force-include` entry already carries `installer/defaults.yaml`; add `installer/managed_section.md` alongside it.

- [ ] **Step 1: Write the failing test**

Append to `installer/tests/test_claudemd.py`:

```python
import installer


def test_managed_section_file_shipped():
    """installer/managed_section.md ships with the installer package."""
    pkg_root = Path(installer.__file__).parent
    assert (pkg_root / "managed_section.md").is_file()
```

- [ ] **Step 2: Run test to verify it passes in source tree**

```bash
uv run pytest installer/tests/test_claudemd.py::test_managed_section_file_shipped -v
```

Expected: PASS when run from the source tree (the file exists on disk from Task 1).

This test is valuable because it will regress if a future packaging refactor drops the file — but it passes today because hatchling's source layout exposes `installer/` directly. The real packaging fix is the next step; without it, `uv build` would produce a wheel missing the file.

- [ ] **Step 3: Update `force-include` in root `pyproject.toml`**

Edit `pyproject.toml` line 26. Change:

```toml
force-include = { "installer/defaults.yaml" = "installer/defaults.yaml", ".claude-plugin/marketplace.json" = "installer/marketplace.json" }
```

to:

```toml
force-include = { "installer/defaults.yaml" = "installer/defaults.yaml", "installer/managed_section.md" = "installer/managed_section.md", ".claude-plugin/marketplace.json" = "installer/marketplace.json" }
```

- [ ] **Step 4: Verify the wheel ships the file**

```bash
uv build --wheel
unzip -l dist/cpm_install-*.whl | grep managed_section.md
```

Expected: the listing contains `installer/managed_section.md`.

Then clean up:

```bash
rm -rf dist/
```

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml installer/tests/test_claudemd.py
git commit -m "$(cat <<'EOF'
build: ship installer/managed_section.md in the wheel (639)

Adds managed_section.md to the hatchling force-include list so the
managed-block content loads correctly from an installed wheel, not just
the source tree.

Co-Authored-By: Claude Opus 4 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Append the revdiff bullet

**Files:**
- Modify: `installer/managed_section.md` (insert new bullet)
- Test: `installer/tests/test_claudemd.py` (append new test)

- [ ] **Step 1: Write the failing test**

Append to `installer/tests/test_claudemd.py`:

```python
def test_managed_section_contains_revdiff_rule():
    """The revdiff-routed review bullet is present in MANAGED_SECTION."""
    assert "Revdiff-routed spec/plan review" in claudemd.MANAGED_SECTION
    assert 'enabledPlugins["revdiff@revdiff"]' in claudemd.MANAGED_SECTION
    assert "superpowers skill" in claudemd.MANAGED_SECTION
    assert "falls back silently" in claudemd.MANAGED_SECTION or "fall back silently" in claudemd.MANAGED_SECTION
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest installer/tests/test_claudemd.py::test_managed_section_contains_revdiff_rule -v
```

Expected: FAIL — the bullet is not in the file yet.

- [ ] **Step 3: Append the bullet to `installer/managed_section.md`**

Insert the following bullet as the LAST bullet in the list (i.e. directly before the closing `<!-- claude-project-manager:end -->` marker line):

```
- **Revdiff-routed spec/plan review** — When a superpowers skill produces a spec/plan/design file and reaches the "ask user to review" step, check if revdiff is available: `enabledPlugins["revdiff@revdiff"] == true` in `~/.claude/settings.json` AND `which revdiff` returns 0. If both hold, invoke the `revdiff:revdiff` skill on the file instead of asking the user to read it manually. If either check fails, fall back silently to the skill's default text-review prompt. This rule applies only to superpowers skills; skills outside the superpowers namespace are unaffected.
```

Ensure there is no blank line between this bullet and the preceding one, and that the closing marker is on the immediately following line.

- [ ] **Step 4: Run the new test and the load test**

```bash
uv run pytest installer/tests/test_claudemd.py::test_managed_section_contains_revdiff_rule installer/tests/test_claudemd.py::test_managed_section_loaded_from_file -v
```

Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add installer/managed_section.md installer/tests/test_claudemd.py
git commit -m "$(cat <<'EOF'
feat(installer): add revdiff-routed spec/plan review rule (639)

New bullet in the cpm-managed CLAUDE.md block tells Claude to route
superpowers spec/plan review steps through the revdiff skill when it is
enabled and its binary is on PATH. Silent fallback to the default text
prompt when revdiff is unavailable.

Co-Authored-By: Claude Opus 4 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Make `installer.claudemd` importable from the proj MCP server

**Files:**
- Modify: `plugins/proj/server/pyproject.toml:10-24`
- Verify only: `plugins/proj/server/uv.lock` (regenerated by `uv sync`)

This wires `cpm-install` (the installer package declared at the repo root `pyproject.toml`) as a workspace path dependency of the proj MCP server so `from installer.claudemd import ensure_managed_section, MANAGED_SECTION` resolves at runtime.

- [ ] **Step 1: Add `cpm-install` to `dependencies` and register its source**

Edit `plugins/proj/server/pyproject.toml`. Change the `dependencies` list (lines 10-15) from:

```toml
dependencies = [
    "mcp>=1.2.0",
    "pyyaml>=6.0",
    "gitpython>=3.1",
    "claude-hook-transport",
]
```

to:

```toml
dependencies = [
    "mcp>=1.2.0",
    "pyyaml>=6.0",
    "gitpython>=3.1",
    "claude-hook-transport",
    "cpm-install",
]
```

And change `[tool.uv.sources]` (lines 23-24) from:

```toml
[tool.uv.sources]
claude-hook-transport = { path = "../../_shared" }
```

to:

```toml
[tool.uv.sources]
claude-hook-transport = { path = "../../_shared" }
cpm-install = { path = "../../..", editable = true }
```

- [ ] **Step 2: Resolve the dependency graph**

```bash
cd plugins/proj/server
uv sync
cd ../../..
```

Expected: no errors. `uv.lock` is updated; commit it alongside the pyproject change. `textual`, `httpx`, and `pyyaml` will be pulled into the proj server's venv as transitive deps of `cpm-install` — this is intentional and acceptable.

- [ ] **Step 3: Verify the import resolves**

```bash
cd plugins/proj/server
uv run python -c "from installer.claudemd import ensure_managed_section, MANAGED_SECTION; print(len(MANAGED_SECTION), 'chars loaded')"
cd ../../..
```

Expected: prints a character count in the low thousands (matches the file content length).

- [ ] **Step 4: Run the existing proj server test suite to confirm no regression**

```bash
cd plugins/proj/server
uv run pytest -x
cd ../../..
```

Expected: all tests PASS. If coverage drops below the `--cov-fail-under=72` gate because of the new dep, that indicates unexpected import-time side effects — investigate rather than lower the gate.

- [ ] **Step 5: Commit**

```bash
git add plugins/proj/server/pyproject.toml plugins/proj/server/uv.lock
git commit -m "$(cat <<'EOF'
build(proj-server): add cpm-install as path dependency (639)

Enables `from installer.claudemd import ensure_managed_section` inside
the proj MCP server, so the upcoming claudemd_refresh_managed tool can
reuse the installer's managed-block logic without duplicating it.

Co-Authored-By: Claude Opus 4 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Add `claudemd_refresh_managed` MCP tool

**Files:**
- Modify: `plugins/proj/server/server/tools/context.py:412-415`
- Test: `plugins/proj/server/tests/test_context.py` (append new tests)

- [ ] **Step 1: Locate the test file and its existing fixture patterns**

Read `plugins/proj/server/tests/test_context.py` to understand how tests register tools, call them, and assert results. Follow the same patterns used for `claudemd_write` and `claudemd_read` (directly adjacent to where the new tool will go). Key points from inspection:
- Tests instantiate a FastMCP app, call the `register` entry point from `server.tools.context`, and drive tools by name.
- Use `tmp_path` + `monkeypatch.setattr(Path, "home", lambda: tmp_path)` (or an equivalent `monkeypatch.setenv("HOME", ...)` pattern if that file uses one).

If `test_context.py` uses a different fixture helper, follow that helper rather than inventing a new one.

- [ ] **Step 2: Write the failing tests**

Append to `plugins/proj/server/tests/test_context.py`:

```python
import json

from mcp.server.fastmcp import FastMCP

from installer.claudemd import MANAGED_SECTION, MARKER_END, MARKER_START
from server.tools import context


def _get_tool(app, name):
    # If the existing test file already has a helper for this, use that instead.
    tool = app._tool_manager._tools[name]  # noqa: SLF001
    return tool.fn


def _make_app():
    app = FastMCP("proj-test")
    context.register(app)
    return app


def test_claudemd_refresh_managed_creates_file(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    target = tmp_path / ".claude" / "CLAUDE.md"
    app = _make_app()
    fn = _get_tool(app, "claudemd_refresh_managed")

    result = fn()

    assert result == {"updated": True, "path": str(target)}
    assert target.exists()
    assert MARKER_START in target.read_text()
    assert MARKER_END in target.read_text()
    assert MANAGED_SECTION in target.read_text()


def test_claudemd_refresh_managed_noop_when_current(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    target = tmp_path / ".claude" / "CLAUDE.md"
    target.parent.mkdir()
    target.write_text(MANAGED_SECTION + "\n", encoding="utf-8")
    app = _make_app()
    fn = _get_tool(app, "claudemd_refresh_managed")

    result = fn()

    assert result == {"updated": False, "path": str(target)}


def test_claudemd_refresh_managed_replaces_stale_section(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    target = tmp_path / ".claude" / "CLAUDE.md"
    target.parent.mkdir()
    # Simulate an old managed block with different body content, wrapped in the same markers.
    stale = f"{MARKER_START}\n## Old Rules\n- Stale bullet\n{MARKER_END}"
    target.write_text(f"# User header\n\n{stale}\n\n# User footer\n", encoding="utf-8")
    app = _make_app()
    fn = _get_tool(app, "claudemd_refresh_managed")

    result = fn()

    assert result == {"updated": True, "path": str(target)}
    content = target.read_text()
    assert "Stale bullet" not in content
    assert MANAGED_SECTION in content
    assert "# User header" in content
    assert "# User footer" in content
```

If the existing `test_context.py` has a helper to resolve registered tool functions (look for one near the existing `claudemd_write`/`claudemd_read` tests), use it in place of `_get_tool`. Otherwise keep `_get_tool` as written — FastMCP stores tools under `_tool_manager._tools` in the installed MCP SDK version, and accessing it for tests is the accepted pattern in this codebase.

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd plugins/proj/server
uv run pytest tests/test_context.py::test_claudemd_refresh_managed_creates_file tests/test_context.py::test_claudemd_refresh_managed_noop_when_current tests/test_context.py::test_claudemd_refresh_managed_replaces_stale_section -v
cd ../../..
```

Expected: FAIL — the tool is not yet registered.

- [ ] **Step 4: Register the tool**

In `plugins/proj/server/server/tools/context.py`, after the existing `claudemd_read` tool (ends at line 415), add:

```python
    @app.tool(
        description=(
            "Refresh the cpm-managed section in ~/.claude/CLAUDE.md to the"
            " current version. Use after upgrading cpm to pick up new rules"
            " without re-running the installer wizard."
        )
    )
    def claudemd_refresh_managed() -> dict[str, str | bool]:
        from installer.claudemd import ensure_managed_section

        target = Path.home() / ".claude" / "CLAUDE.md"
        updated = ensure_managed_section(target)
        return {"updated": updated, "path": str(target)}
```

Notes:
- Import `ensure_managed_section` inside the function body to keep the `installer` import off the module-load path (avoids circulars and keeps cold-start cheap).
- `Path` is already imported at the top of `context.py` (line 10).
- The `dict[str, str | bool]` return type matches the basedpyright strict-mode expectations for this file; if basedpyright complains about heterogeneous dict typing, fall back to `dict[str, object]`.

- [ ] **Step 5: Run the new tests**

```bash
cd plugins/proj/server
uv run pytest tests/test_context.py -v -k claudemd_refresh
cd ../../..
```

Expected: all three tests PASS.

- [ ] **Step 6: Run the full proj server suite**

```bash
cd plugins/proj/server
uv run pytest
cd ../../..
```

Expected: all tests PASS, coverage stays above 72.

- [ ] **Step 7: Commit**

```bash
git add plugins/proj/server/server/tools/context.py plugins/proj/server/tests/test_context.py
git commit -m "$(cat <<'EOF'
feat(proj-server): add claudemd_refresh_managed MCP tool (639)

New proj MCP tool refreshes the cpm-managed block in ~/.claude/CLAUDE.md
to the current version, reusing installer.claudemd.ensure_managed_section.
Three tests cover the fresh-file, no-op, and stale-block cases.

Co-Authored-By: Claude Opus 4 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Add `/proj:claudemd-refresh` skill

**Files:**
- Create: `plugins/proj/skills/claudemd-refresh/SKILL.md`

The skill is a thin wrapper: call the tool, report the result. Follow the caveman-ultra format per the project's SKILL.md convention.

- [ ] **Step 1: Create the SKILL.md file**

Write `plugins/proj/skills/claudemd-refresh/SKILL.md` with the following content verbatim:

````markdown
---
name: claudemd-refresh
description: Refresh cpm-managed block in ~/.claude/CLAUDE.md to the current version. Use after upgrading cpm to pick up new rules without re-running the installer wizard. Use when user says "refresh claudemd", "update managed block", or "refresh managed section".
allowed-tools: mcp__plugin_proj_proj__claudemd_refresh_managed
context: fork
agent: general-purpose
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

# claudemd-refresh

Refresh cpm-managed block in `~/.claude/CLAUDE.md`. Single-step op.

## Flow

**1.** Call `mcp__plugin_proj_proj__claudemd_refresh_managed()`.

**2.** Parse result `{updated: bool, path: str}`.

**3.** Report:

- `updated=true` → "Managed block refreshed at `<path>`. Pick up new rules in next Claude session."
- `updated=false` → "Managed block already current at `<path>`. No changes."

## Err Handling

- Tool raises → surface err verbatim. Likely cause: `~/.claude` unreadable or installer pkg missing. Suggest: verify `~/.claude` perms or reinstall cpm.

## When to Use

- After `uv tool upgrade cpm-install` or equivalent cpm upgrade.
- After pulling new cpm rules from main (dev only).
- When `~/.claude/CLAUDE.md` missing the cpm-managed block entirely.

## When NOT to Use

- Normal session start — block is static, refresh only needed on upgrade.
- User wants to *remove* managed block — use installer uninstall flow instead.
````

- [ ] **Step 2: Verify the skill loads by opening a fresh Claude session and invoking it**

Manual verification (document for the human operator — automated discovery test is not practical in this repo):

1. In a separate Claude Code session, type `/proj:claudemd-refresh` — the skill must appear in the slash-command picker.
2. Invoke it. Claude calls `mcp__plugin_proj_proj__claudemd_refresh_managed` and reports `updated` + `path`.

- [ ] **Step 3: Commit**

```bash
git add plugins/proj/skills/claudemd-refresh/SKILL.md
git commit -m "$(cat <<'EOF'
feat(proj): add /proj:claudemd-refresh skill (639)

Slash-command wrapper for mcp__plugin_proj_proj__claudemd_refresh_managed
so users can refresh the cpm-managed CLAUDE.md block without remembering
the raw MCP tool name.

Co-Authored-By: Claude Opus 4 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Documentation touch-ups

**Files:**
- Modify: `installer/claudemd.py:1` (module docstring)
- Modify: `plugins/proj/README.md` (add skill row)

- [ ] **Step 1: Update the installer module docstring**

In `installer/claudemd.py`, replace line 1:

```python
"""Managed section CRUD for CLAUDE.md files."""
```

with:

```python
"""Managed section CRUD for CLAUDE.md files.

The section body lives in ``installer/managed_section.md`` (single source of
truth) and is loaded into ``MANAGED_SECTION`` at import time. The installer,
the proj ``claudemd_refresh_managed`` MCP tool, and the ``/proj:claudemd-refresh``
skill all resolve to the same content file.
"""
```

- [ ] **Step 2: Add the skill to the proj plugin README**

In `plugins/proj/README.md`, locate the "Permissions" section (line 190 in the current version — the heading `### Permissions`). **Insert a new section immediately before it:**

```markdown
### Maintenance

| Skill | Usage | Description |
|-------|-------|-------------|
| `claudemd-refresh` | `/proj:claudemd-refresh` | Refresh the cpm-managed block in `~/.claude/CLAUDE.md` to the current version. Use after upgrading cpm. |

```

If the README's skill-section ordering changes before implementation, place the new section as the nearest logical sibling to "Sync" and "Permissions" (i.e. an ops-grade skill, not a lifecycle one).

- [ ] **Step 3: Verify the README still renders**

```bash
grep -c '| Skill | Usage' plugins/proj/README.md
```

Expected: an integer one higher than before the edit.

- [ ] **Step 4: Commit**

```bash
git add installer/claudemd.py plugins/proj/README.md
git commit -m "$(cat <<'EOF'
docs: wire claudemd-refresh into module docstring and README (639)

Module docstring now points readers at the content file. Proj plugin README
gains a Maintenance section listing the new /proj:claudemd-refresh skill.

Co-Authored-By: Claude Opus 4 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: End-to-end verification and acceptance checklist

No code changes in this task — this is the implementer's and reviewer's acceptance gate.

- [ ] **Step 1: Run the entire test suite from repo root**

```bash
uv run pytest
cd plugins/proj/server && uv run pytest && cd ../../..
```

Expected: all tests PASS, in both the installer project (repo root) and the proj MCP server.

- [ ] **Step 2: Exercise the installer wizard on a throwaway `HOME`**

```bash
export FAKE_HOME=$(mktemp -d)
HOME=$FAKE_HOME uv run cpm-install --help  # confirm the installer entry point still works
# (The full wizard flow is interactive; verify by running without --help in a scratch terminal.)
```

After a wizard run that writes the managed block, confirm the output file contains the new revdiff bullet:

```bash
grep -F 'Revdiff-routed spec/plan review' "$FAKE_HOME/.claude/CLAUDE.md"
```

Expected: exactly one match.

- [ ] **Step 3: Exercise the refresh tool against a stale block**

```bash
export FAKE_HOME=$(mktemp -d)
mkdir -p "$FAKE_HOME/.claude"
cat > "$FAKE_HOME/.claude/CLAUDE.md" <<'EOF'
# User prologue

<!-- claude-project-manager:start -->
## Old block
- stale content
<!-- claude-project-manager:end -->

# User epilogue
EOF

cd plugins/proj/server
HOME=$FAKE_HOME uv run python -c "
from server.tools.context import register
from mcp.server.fastmcp import FastMCP
app = FastMCP('verify')
register(app)
fn = app._tool_manager._tools['claudemd_refresh_managed'].fn
print(fn())
"
cd ../../..

grep -F 'Revdiff-routed spec/plan review' "$FAKE_HOME/.claude/CLAUDE.md"
grep -F 'User prologue' "$FAKE_HOME/.claude/CLAUDE.md"
grep -F 'User epilogue' "$FAKE_HOME/.claude/CLAUDE.md"
grep -F 'stale content' "$FAKE_HOME/.claude/CLAUDE.md" && echo "FAIL: stale content retained" || echo "OK: stale content removed"
```

Expected: the three `grep -F` checks on revdiff bullet, prologue, and epilogue all return matches; the stale-content check prints `OK: stale content removed`.

- [ ] **Step 4: Confirm acceptance criteria from the spec**

Walk the spec's "Acceptance Criteria" section and tick each item:

1. `installer/managed_section.md` exists with full section including the revdiff bullet ✓
2. `installer/claudemd.py` loads from the .md file instead of an inline literal ✓
3. Packaging ships the .md file (`force-include` entry present) ✓
4. `claudemd_refresh_managed` MCP tool registered and returns `{updated, path}` ✓
5. `/proj:claudemd-refresh` skill at the expected path, listed in the plugin README ✓
6. All listed tests pass ✓
7. Manual verification — installer writes the bullet on a clean `~/.claude`; refresh tool updates a stale block in place ✓

Any `✗` here is a blocker — do not close the todo. Open a follow-up and escalate.

- [ ] **Step 5: Complete todo 639**

```bash
# From inside a Claude session with the claude-project-manager project loaded:
# mcp__plugin_proj_proj__todo_complete(todo_id="639")
```

Or via `/proj:todo done 639` in an interactive session.

---

## Dependencies between tasks

```
Task 1 (extract content file)
    |
    v
Task 2 (ship in wheel)
    |
    v
Task 3 (append revdiff bullet)
    |
    +-------------------+
    |                   |
    v                   v
Task 4 (proj dep)   (independent docs path — but wait for Task 4 before skill/test work)
    |
    v
Task 5 (MCP tool)
    |
    v
Task 6 (skill)
    |
    v
Task 7 (docs)
    |
    v
Task 8 (verification)
```

All tasks are strictly sequential for a single-agent execution. For subagent-driven execution, Tasks 1→3 can pipeline (each depends only on the prior), but Task 4 must complete before any work on Tasks 5+ because the import it enables is prerequisite for Task 5's tests.

---

## Out-of-scope follow-ups (do not do in this plan)

- Changing any superpowers skill file — the rule lives in CLAUDE.md, not in upstream skills.
- Adding per-project managed block support — the spec's non-goal.
- Extending the refresh tool to accept a custom target path — not requested; `~/.claude/CLAUDE.md` only.
- Adding telemetry for revdiff routing — explicit non-goal.
- Fixing the unrelated `proj_todoist_full_sync` unknown-tool hook error — already captured as todo 640.
