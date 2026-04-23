# Wiki Plugin Phase 4b: Wizard Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** cpm installer wizard gains a "wiki" section. User picks profile, integration flags, optional bootstrap-queuing. Wizard writes 3 config files: `~/.claude/wiki.yaml`, `~/.claude/wiki/config.yaml`, + `~/.claude/proj.yaml::sync.wiki.*`. No LLM calls (spec §4.4).

**Architecture:** New `configure_wiki()` function in `installer/flow/integration_config.py` mirroring `configure_trello`/`configure_jira` patterns. Add `"wiki"` to `_WIZARD_PLUGINS`. Add `configure_wiki` to the integration-config handler tuple. Custom write path for `wiki/config.yaml` (nested) since bucket-partition logic assumes single-level yaml_file. User's profile choice drives which category dirs get created via `mkdir -p` in the install-plan execution phase.

**Tech Stack:** Existing installer stack (prompt_toolkit, yaml, pytest).

**Spec reference:** §4.4. Prior: P4a shipped at `d9faf8d`.

---

## Scope

**IN:**
- `configure_wiki()` in `integration_config.py` — prompts: enable (bool), profile (select: software/personal/research/minimal/custom), custom categories (text, only when profile=custom), auto_ingest_sessions (bool, only if proj selected), capture_notes_as_log (bool, only if proj selected), queue-bootstrap (bool).
- Write logic: wiki.yaml + wiki/config.yaml + proj.yaml::sync.wiki.* updates.
- Add `"wiki"` to `_WIZARD_PLUGINS` + the `_run_install` integration tuple.
- Tests: mock prompts + assert files written with expected content.

**OUT:** session-ingest section-map editor (ship default per profile; user edits YAML by hand if needed). Credential validation (no wiki auth exists).

---

## Tasks

### Task 1: Add `configure_wiki()` scaffold + field specs

**Files:**
- Modify: `installer/flow/integration_config.py`

- [ ] **Step 1.1:** Read the existing `configure_trello` implementation for patterns.
- [ ] **Step 1.2:** Add `configure_wiki(console: Console, proj_selected: bool) -> dict[str, Any] | None` after `configure_jira`. Fields:

```python
def configure_wiki(console: Console, proj_selected: bool = False) -> dict[str, Any] | None:
    """Wiki integration config form. Returns dict or None on cancel."""
    claude_home = Path.home() / ".claude"
    wiki_yaml = _load_yaml(claude_home / "wiki.yaml")
    wiki_config_yaml = _load_yaml(claude_home / "wiki" / "config.yaml")
    proj_yaml = _load_yaml(claude_home / "proj.yaml")
    proj_sync_wiki = (proj_yaml.get("sync", {}) or {}).get("wiki", {}) or {}

    fields = [
        FieldSpec(
            key="enabled",
            label="Enable wiki plugin",
            kind="bool",
            default=bool(wiki_yaml.get("enabled", False)),
            help_text="Master switch. Wiki MCP server serves requests when enabled.",
        ),
        FieldSpec(
            key="profile",
            label="Category profile",
            kind="select",
            choices=["software", "personal", "research", "minimal", "custom"],
            default=str(wiki_config_yaml.get("profile", "software")),
            help_text=(
                "software: concepts/decisions/references/pitfalls/entities. "
                "personal: journal/topics/people/places/lessons. "
                "research: concepts/sources/findings/questions. "
                "minimal: flat pages/, no subdirs. "
                "custom: you define categories."
            ),
        ),
        FieldSpec(
            key="custom_categories",
            label="Custom categories (comma-separated, only used if profile=custom)",
            kind="text",
            default=",".join(wiki_config_yaml.get("categories", []) or []),
            help_text="Leave blank unless you picked 'custom' profile.",
        ),
        FieldSpec(
            key="bootstrap_pending",
            label="Queue /wiki:bootstrap for next session?",
            kind="bool",
            default=bool(wiki_yaml.get("bootstrap_pending", False)),
            help_text=(
                "If yes, /wiki:init-check will prompt on next Claude session to run "
                "/wiki:bootstrap. The wizard itself cannot invoke LLM-driven skills."
            ),
        ),
    ]
    if proj_selected:
        fields.extend([
            FieldSpec(
                key="proj_auto_ingest_sessions",
                label="[proj integration] Auto-ingest /proj:save sessions into wiki",
                kind="bool",
                default=bool(proj_sync_wiki.get("auto_ingest_sessions", False)),
                help_text="Final step of /proj:save spawns wiki ingest subagent on session file.",
            ),
            FieldSpec(
                key="proj_capture_notes_as_log",
                label="[proj integration] Capture notes_append as wiki log entries",
                kind="bool",
                default=bool(proj_sync_wiki.get("capture_notes_as_log", False)),
                help_text="Router hook: every notes_append call also appends a wiki log entry.",
            ),
        ])

    return _run_integration_form("Wiki", fields, None, console)  # No validator; no credentials
```

- [ ] **Step 1.3:** Commit.

```bash
git add installer/flow/integration_config.py
git commit -m "feat(installer): add configure_wiki() form w/ profile + proj-integration flags"
```

---

### Task 2: Wire `configure_wiki` into `_run_install`

**Files:**
- Modify: `installer/flow/installer_flow.py`

- [ ] **Step 2.1:** Add `"wiki"` to `_WIZARD_PLUGINS` (so `run_wizard` runs if user picks wiki).
- [ ] **Step 2.2:** Extend the integration-config loop in `_run_install`. The existing loop:

```python
for service, configure_fn in (
    ("todoist", configure_todoist),
    ("trello", configure_trello),
    ("jira", configure_jira),
):
    if service not in selected_names:
        continue
    result = configure_fn(console)
```

Replace with a variant that passes `proj_selected` to configure_wiki:

```python
for service, configure_fn in (
    ("todoist", configure_todoist),
    ("trello", configure_trello),
    ("jira", configure_jira),
):
    if service not in selected_names:
        continue
    result = configure_fn(console)
    # ... existing handling

# Wiki is special — passes proj_selected flag
if "wiki" in selected_names:
    proj_selected = "proj" in selected_names
    result = configure_wiki(console, proj_selected=proj_selected)
    if result is None:
        continue  # or whatever the existing cancel-handling does
    _write_wiki_integration_result(result, proj_selected)
```

- [ ] **Step 2.3:** Import `configure_wiki` at top.
- [ ] **Step 2.4:** Commit.

```bash
git add installer/flow/installer_flow.py
git commit -m "feat(installer): wire configure_wiki into install flow; gate proj fields by selection"
```

---

### Task 3: Custom write path `_write_wiki_integration_result`

**Files:**
- Modify: `installer/flow/integration_config.py` (or new helper module — follow existing patterns)

**Goal:** Write the form result across 3 files atomically:
- `~/.claude/wiki.yaml` — `enabled`, `bootstrap_pending`
- `~/.claude/wiki/config.yaml` — `schema_version: 1`, `profile`, `categories` (when profile=custom), `required_frontmatter` defaults, `lint` defaults
- `~/.claude/proj.yaml` — `sync.wiki.enabled`, `sync.wiki.auto_ingest_sessions`, `sync.wiki.capture_notes_as_log` (when proj_selected)

- [ ] **Step 3.1:** Define `_write_wiki_integration_result(result: dict[str, Any], proj_selected: bool) -> None`:

```python
def _write_wiki_integration_result(result: dict[str, Any], proj_selected: bool) -> None:
    """Write wiki config to 3 files. Creates ~/.claude/wiki/ + /pages/<cat>/ subdirs."""
    claude_home = Path.home() / ".claude"
    wiki_home = claude_home / "wiki"
    wiki_home.mkdir(parents=True, exist_ok=True)
    (wiki_home / "pages").mkdir(exist_ok=True)

    # 1. ~/.claude/wiki.yaml
    wiki_yaml_path = claude_home / "wiki.yaml"
    existing_wiki = _load_yaml(wiki_yaml_path)
    existing_wiki.update({
        "enabled": bool(result["enabled"]),
        "wiki_dir": str(wiki_home),
        "reingest_cooldown_hours": int(existing_wiki.get("reingest_cooldown_hours", 24)),
        "bootstrap_pending": bool(result.get("bootstrap_pending", False)),
        "session_ingest": existing_wiki.get("session_ingest") or {"section_map": {}},
    })
    _atomic_write_yaml(wiki_yaml_path, existing_wiki)

    # 2. ~/.claude/wiki/config.yaml
    profile = str(result.get("profile", "software"))
    config_yaml_path = wiki_home / "config.yaml"
    config_data: dict[str, Any] = {
        "schema_version": 1,
        "profile": profile,
        "required_frontmatter": [
            "title", "tags", "links_to", "scope", "sources", "last_ingested",
        ],
        "lint": {
            "stale_after_days": 90,
            "orphan_min_page_count": 3,
        },
    }
    if profile == "custom":
        raw = str(result.get("custom_categories", "") or "")
        cats = [c.strip() for c in raw.split(",") if c.strip()]
        if not cats:
            cats = ["notes"]  # minimal fallback
        config_data["categories"] = cats
    _atomic_write_yaml(config_yaml_path, config_data)

    # 3. Create category subdirs per profile
    cat_map = {
        "software": ["concepts", "decisions", "references", "pitfalls", "entities"],
        "personal": ["journal", "topics", "people", "places", "lessons"],
        "research": ["concepts", "sources", "findings", "questions"],
        "minimal": [],
        "custom": config_data.get("categories", []),
    }
    for cat in cat_map.get(profile, []):
        (wiki_home / "pages" / cat).mkdir(exist_ok=True)

    # 4. proj.yaml sync.wiki.* (only if proj is being installed too)
    if proj_selected:
        proj_yaml_path = claude_home / "proj.yaml"
        existing_proj = _load_yaml(proj_yaml_path)
        sync = existing_proj.setdefault("sync", {})
        sync["wiki"] = {
            "enabled": bool(result["enabled"]),
            "auto_sync": True,
            "auto_ingest_sessions": bool(result.get("proj_auto_ingest_sessions", False)),
            "capture_notes_as_log": bool(result.get("proj_capture_notes_as_log", False)),
            "replace_notes_md": False,
            "bootstrap_docs": sync.get("wiki", {}).get("bootstrap_docs", []),
        }
        _atomic_write_yaml(proj_yaml_path, existing_proj)
```

- [ ] **Step 3.2:** Add `_atomic_write_yaml(path, data)` helper (or use existing one from `_config_writer.py` — check first).
- [ ] **Step 3.3:** Commit.

---

### Task 4: Tests for `configure_wiki` + write path

**Files:**
- Create: `installer/tests/flow/test_configure_wiki.py`

- [ ] **Step 4.1:** Cover:
  - `configure_wiki` without proj → 4 fields
  - `configure_wiki` with proj → 6 fields
  - `_write_wiki_integration_result` writes all 3 files correctly
  - Custom profile writes categories list
  - Missing optional proj fields handled gracefully
  - Atomic write preserves existing keys (e.g. reingest_cooldown_hours untouched)

- [ ] **Step 4.2:** Follow existing `test_integration_config.py` mock patterns (mock `_load_yaml`, `_run_integration_form`, `Path.home`).

- [ ] **Step 4.3:** Commit.

---

### Task 5: Update plugin README + final smoke

**Files:**
- Modify: `plugins/wiki/README.md` — update Phase status to P4b ✅

- [ ] **Step 5.1:** Update README Phase status.
- [ ] **Step 5.2:** Run installer tests (`cd installer && uv run pytest flow/test_configure_wiki.py`).
- [ ] **Step 5.3:** Commit + dispatch final reviewer (same pattern as P4a).

---

## Verification

1. `configure_wiki` test passes end-to-end in isolation.
2. Run full installer test suite — no regressions.
3. Manual smoke: run `claude-project-manager-installer` in a scratch HOME, select wiki, pick software profile, confirm all 3 files created.
