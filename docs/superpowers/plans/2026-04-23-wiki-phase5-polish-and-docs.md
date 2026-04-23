# Wiki Plugin Phase 5: Polish + Docs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** Final phase. CLAUDE.md config-flag docs, end-to-end smoke as pytest, cpm marketplace README entry, sunset the unified-recall-proposal memory file (per spec §12.4).

**Architecture:** Cross-cutting docs + light test. No new surface. No new plugin code.

**Spec reference:** §15 Phase 5, §12.4, §17. Prior: P4c shipped at `898357d`.

---

## Scope

**IN:**
- Add wiki config-flag reference section to the root `CLAUDE.md` (worktree copy) + repo `plugins/wiki/README.md` — single source of truth for all wiki.yaml + wiki/config.yaml + proj.yaml::sync.wiki.* keys.
- Add E2E smoke test at `plugins/wiki/server/tests/test_e2e_integration.py` — automated cross-plugin test (proj sets session-active → wiki_scope_detect returns project:<name>).
- Add cpm root README entry for wiki plugin (if missing).
- Sunset `~/.claude/projects/-home-raul-projects-claude-project-manager/memory/unified-recall-proposal.md` — mark deprecated + move to archive + update MEMORY.md.
- Final plugin README Phase status → P5 ✅, plugin bumps to `0.1.0` (or 1.0.0 if that's cpm convention).

**OUT:** Any substantive code changes. Cleanup of todos 706/707/708/709 (defer to separate cleanup sprint).

---

## Tasks

### Task 1: E2E smoke test (pytest)

**Files:**
- Create: `plugins/wiki/server/tests/test_e2e_integration.py`

- [ ] **Step 1.1:** Pytest test that replicates the manual smoke: set up tmp ~/.claude/, write proj-session.yaml + proj.yaml, call `wiki_scope_detect`, assert scope=`project:<name>`.

```python
"""End-to-end integration tests for wiki ↔ proj coupling."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from server.lib import config as config_mod
from server.tools import scope as wiki_scope


@pytest.fixture
def integrated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a scratch ~/.claude/ layout w/ proj.yaml + proj-session.yaml + wiki.yaml."""
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "proj.yaml").write_text(yaml.safe_dump({"version": 1}))
    monkeypatch.setattr(wiki_scope, "_PROJ_YAML_PATH", claude / "proj.yaml")
    monkeypatch.setattr(wiki_scope, "_SESSION_YAML_PATH", claude / "proj-session.yaml")
    return claude


class TestWikiProjIntegration:
    def test_scope_detect_no_session(self, integrated_home: Path) -> None:
        """proj.yaml exists but no session file → global."""
        result = json.loads(wiki_scope.wiki_scope_detect())
        assert result == {"scope": "global", "proj_present": True}

    def test_scope_detect_with_active_project(self, integrated_home: Path) -> None:
        """Writing active project to session file surfaces via wiki_scope_detect."""
        (integrated_home / "proj-session.yaml").write_text(
            yaml.safe_dump({"active": "e2e-test-project"})
        )
        result = json.loads(wiki_scope.wiki_scope_detect())
        assert result["scope"] == "project:e2e-test-project"
        assert result["proj_present"] is True

    def test_scope_detect_session_without_proj(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Session file exists but proj.yaml doesn't → still detects scope but proj_present=False."""
        claude = tmp_path / ".claude"
        claude.mkdir()
        (claude / "proj-session.yaml").write_text(yaml.safe_dump({"active": "orphan"}))
        monkeypatch.setattr(wiki_scope, "_PROJ_YAML_PATH", claude / "proj.yaml")  # doesn't exist
        monkeypatch.setattr(wiki_scope, "_SESSION_YAML_PATH", claude / "proj-session.yaml")

        result = json.loads(wiki_scope.wiki_scope_detect())
        assert result["scope"] == "project:orphan"
        assert result["proj_present"] is False

    def test_wiki_config_surfaces_defaults_when_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """wiki.yaml missing → config loads defaults."""
        monkeypatch.setattr(config_mod, "_DEFAULT_CONFIG_PATH", tmp_path / "wiki.yaml")
        cfg = config_mod.load_config()
        assert cfg.enabled is False
        assert cfg.reingest_cooldown_hours == 24
```

- [ ] **Step 1.2:** Run test. Commit.

---

### Task 2: CLAUDE.md config-flag reference

**Files:**
- Modify: `CLAUDE.md` (worktree root)

- [ ] **Step 2.1:** Append a "Wiki plugin config flags" section documenting:
  - `~/.claude/wiki.yaml`: enabled, wiki_dir, reingest_cooldown_hours, bootstrap_pending, session_ingest.section_map
  - `~/.claude/wiki/config.yaml`: schema_version, profile, categories (custom only), required_frontmatter, lint.{stale_after_days, orphan_min_page_count}
  - `~/.claude/proj.yaml::sync.wiki.*`: enabled, auto_sync, auto_ingest_sessions, capture_notes_as_log, replace_notes_md, bootstrap_docs
  - `~/.claude/proj-session.yaml`: `active: <name>` (owned by proj, read by wiki scope_detect)

- [ ] **Step 2.2:** Commit.

---

### Task 3: Sunset unified-recall-proposal.md

**Files:**
- (operation on `~/.claude/projects/-home-raul-projects-claude-project-manager/memory/unified-recall-proposal.md`)

- [ ] **Step 3.1:** If the file exists, prepend a deprecation header:

```markdown
---
deprecated: true
deprecated_in_favor_of: docs/superpowers/specs/2026-04-21-karpathy-wiki-plugin-design.md
deprecated_at: 2026-04-23
---

# Unified Recall Proposal (DEPRECATED)

> This proposal was superseded by the Karpathy LLM Wiki plugin design.
> See `docs/superpowers/specs/2026-04-21-karpathy-wiki-plugin-design.md` for the
> current approach. This file is preserved for historical context.

---

(original content below)
```

- [ ] **Step 3.2:** Move to `~/.claude/projects/-home-raul-projects-claude-project-manager/memory/archive/unified-recall-proposal.md`.

- [ ] **Step 3.3:** Update `~/.claude/projects/-home-raul-projects-claude-project-manager/memory/MEMORY.md` — remove the active link, add an archived-link line.

- [ ] **Step 3.4:** No commit needed (memory is outside repo).

---

### Task 4: Plugin README final polish

**Files:**
- Modify: `plugins/wiki/README.md`

- [ ] **Step 4.1:** Phase 5 → ✅. Add a "Quickstart" section near the top:

```markdown
## Quickstart

1. Install via cpm marketplace: `claude plugin install wiki@claude-project-manager`
2. Run the installer wizard: `cpm-installer` → pick wiki + profile.
3. In a Claude session: `/wiki:init` (if not wizard-initialized) → `/wiki:ingest <source>` → `/wiki:query <question>`.

## User-facing skills

- `/wiki:init` — create wiki + pick profile
- `/wiki:ingest <source>` — add content (URL, file, session, note, search, MCP server)
- `/wiki:query <question>` — synthesize a cited answer
- `/wiki:lint [--tier=1|2|all]` — find + fix integrity issues
- `/wiki:bootstrap [directory]` — bulk import
- `/wiki:promote <slug>` — change page scope
```

- [ ] **Step 4.2:** Commit.

---

### Task 5: Phase-close final review (optional if time permits)

- [ ] **Step 5.1:** Dispatch final reviewer on the entire P5 diff. Address must-fixes.
- [ ] **Step 5.2:** File consolidated todo 710 if minor items surface.

---

## Verification

1. `plugins/wiki/server/tests/test_e2e_integration.py` passes.
2. `CLAUDE.md` has wiki config-flag reference.
3. Plugin README has Quickstart + shows all 6 skills.
4. Full wiki test suite green.

## Handoff

Per `superpowers:finishing-a-development-branch`: the branch is ready for merge. User decides (FF-merge to dev / PR / discard).
