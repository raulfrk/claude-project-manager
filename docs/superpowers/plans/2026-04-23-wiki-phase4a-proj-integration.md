# Wiki Plugin Phase 4a: Proj Integration Foundation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make proj and wiki talk to each other end-to-end. Fix todo 705 (`wiki_scope_detect` currently always returns `"global"`) by persisting proj's session-active project to a file that wiki reads. Add the two touchpoints the spec calls out: router hook `notes_append` → `wiki_log_append` and a new final step in `/proj:save` that spawns the wiki ingest subagent on the freshly-written session file. At end of P4a, the sequence `/proj:load my-project → /wiki:query "something"` returns scope-aware results, + `/proj:save` auto-ingests sessions into wiki.

**Architecture:** Proj's `state.set_session_active(name)` gains file-backed persistence at `~/.claude/proj-session.yaml` (new file; ephemeral; auto-purged on `proj_archive` / explicit clear). `wiki_scope_detect` reads that file via pure-data file I/O (no cross-MCP calls, respects spec §3 persistence/synthesis boundary). Proj gains a `WikiSync` dataclass mirroring `TodoistSync`/`TrelloSync`/`JiraSync` patterns. A new hook entry in `plugins/proj/.claude-plugin/default-hooks.yaml` wires `notes_append` → `wiki_log_append` via the existing router. `/proj:save` SKILL.md gets a new step 11a that spawns a forked ingest subagent reusing `plugins/wiki/skills/ingest/references/subagent-prompt.md` when `sync.wiki.auto_ingest_sessions` is true.

**Tech Stack:** Python 3.12, existing proj dataclass patterns, router hook YAML DSL, SKILL.md prose edits. No new Python deps. No new MCP tools (wiki_scope_detect gets refactored; no signature change).

**Spec reference:** `docs/superpowers/specs/2026-04-21-karpathy-wiki-plugin-design.md` §§4.2, 4.3, 7.2, 8.1, 8.2, 9.4. Prior plans: Phase 1/2/3 all complete at `docs/superpowers/plans/2026-04-23-wiki-phase{1,2,3}-*.md`.

---

## Scope (what's IN P4a, what's OUT)

**IN:**
- **Proj change**: `state.set_session_active` also persists to `~/.claude/proj-session.yaml`; `state.get_session_active` reads from file if in-memory is unset (recovers on MCP server restart); `state.clear_session_active` removes both in-memory + file.
- **Proj change**: new `WikiSync` dataclass in `models.py`; added to `ProjConfig.sync.wiki`; from_dict / to_dict full support.
- **Wiki change**: `wiki_scope_detect` reads `~/.claude/proj-session.yaml` for active-project (with legacy fallback to `proj.yaml::active_project` for forward compatibility).
- **Proj change**: new router hook entry `notes_append` → `wiki_log_append` in `default-hooks.yaml`, condition `"sync.wiki.enabled and sync.wiki.capture_notes_as_log"`.
- **Proj change**: `/proj:save` SKILL.md adds final step that spawns wiki ingest subagent on the freshly-written session file when `sync.wiki.enabled and sync.wiki.auto_ingest_sessions`.
- Unit tests for proj state persistence + scope_detect + WikiSync + hook registration.
- End-to-end smoke: `/proj:load` → `wiki_scope_detect` returns `project:<name>` → `/wiki:query` scoped correctly.

**OUT (later phases):**
- Wizard integration for wiki section — P4b (next).
- Tier-2 semantic lint (contradictions / deprecation / missing cross-refs / category-cluster suggestions) — P4c.
- Migration tooling for existing NOTES.md → wiki — later.
- Unified-recall-proposal.md sunset — later.
- Any cleanup from todos 706/707/708 — separate cleanup sprint.

---

## File Structure

All paths relative to repo root. Work in worktree `/home/raul/worktrees/cpm/feat-688-karpathy-wiki-plugin`.

```
plugins/proj/
├── server/server/lib/
│   ├── state.py                   # Modify — persist session-active
│   └── models.py                  # Modify — add WikiSync dataclass + ProjConfig.wiki
├── server/tests/
│   ├── test_state.py              # Modify / Create — cover persistence round-trip
│   └── test_wiki_sync_config.py   # Create — WikiSync from_dict/to_dict roundtrip
├── .claude-plugin/
│   └── default-hooks.yaml         # Modify — add notes_append → wiki_log_append entry
└── skills/
    └── save/SKILL.md              # Modify — add final wiki ingest step

plugins/wiki/
├── server/server/tools/
│   └── scope.py                   # Modify — read proj-session.yaml
├── server/tests/
│   └── test_scope.py              # Modify — update expectations
└── README.md                      # Modify — Phase 4a status
```

**Responsibilities:**
- `proj/server/server/lib/state.py` — session-active mgmt. Adds `_SESSION_FILE` constant + read/write helpers. Writes atomic (tmpfile + rename per proj/cpm convention).
- `proj/server/server/lib/models.py` — adds `WikiSync` dataclass w/ fields `enabled`, `auto_sync`, `auto_ingest_sessions`, `capture_notes_as_log`, `replace_notes_md`, `bootstrap_docs`. `ProjConfig.wiki` field populated from `sync.wiki.*` in yaml.
- `wiki/server/server/tools/scope.py` — reads `~/.claude/proj-session.yaml` first; falls back to `proj.yaml::active_project` (for legacy / future-proofing). Returns `{scope, proj_present}`.
- `proj/.claude-plugin/default-hooks.yaml` — one new hook entry.
- `proj/skills/save/SKILL.md` — new numbered step between existing steps 10 (notes_append) and 12 (tracking_git_flush) that dispatches wiki ingest via Task.

---

## Task Breakdown

10 tasks.

---

### Task 1: Proj — persist session-active to file

**Goal:** `state.set_session_active(name)` writes `~/.claude/proj-session.yaml`; `state.get_session_active()` reads file if in-memory is None; `state.clear_session_active()` deletes both. Preserves existing API signatures so callers don't change.

**Files:**
- Modify: `plugins/proj/server/server/lib/state.py`
- Modify: `plugins/proj/server/tests/test_state.py` (create if it doesn't exist — check first)

### Step 1.1: Confirm + locate test file

```bash
cd /home/raul/worktrees/cpm/feat-688-karpathy-wiki-plugin
ls plugins/proj/server/tests/ | grep -i state
```

If `test_state.py` exists, modify it. If not, create it. Either way:

### Step 1.2: Write failing tests

File: `plugins/proj/server/tests/test_state.py` (add these test classes, or create file with these + existing content if file is new):

```python
"""Tests for lib/state.py session-active persistence."""
from __future__ import annotations

from pathlib import Path

import pytest

from server.lib import state


@pytest.fixture
def session_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect _SESSION_FILE to a temp path + clear in-memory state."""
    p = tmp_path / "proj-session.yaml"
    monkeypatch.setattr(state, "_SESSION_FILE", p)
    monkeypatch.setattr(state, "_session_active_project", None)
    return p


class TestSessionActivePersistence:
    def test_set_writes_file(self, session_file: Path) -> None:
        state.set_session_active("my-proj")
        assert session_file.exists()
        content = session_file.read_text()
        assert "my-proj" in content

    def test_get_returns_in_memory_first(self, session_file: Path) -> None:
        # in-memory set; file may or may not exist
        state.set_session_active("in-mem")
        # Overwrite file to different value — in-memory should still win
        session_file.write_text("active: file-value\n")
        assert state.get_session_active() == "in-mem"

    def test_get_falls_back_to_file_when_memory_none(
        self, session_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session_file.write_text("active: from-file\n")
        monkeypatch.setattr(state, "_session_active_project", None)
        assert state.get_session_active() == "from-file"

    def test_get_returns_none_when_both_empty(self, session_file: Path) -> None:
        # No in-memory value; no file
        assert state.get_session_active() is None

    def test_clear_removes_both(self, session_file: Path) -> None:
        state.set_session_active("x")
        assert session_file.exists()
        state.clear_session_active()
        assert not session_file.exists()
        assert state.get_session_active() is None

    def test_clear_when_nothing_set_is_idempotent(self, session_file: Path) -> None:
        # Should not raise
        state.clear_session_active()
        assert state.get_session_active() is None

    def test_file_malformed_falls_back_to_none(
        self, session_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session_file.write_text("not: : : valid yaml")
        monkeypatch.setattr(state, "_session_active_project", None)
        assert state.get_session_active() is None

    def test_round_trip_across_module_reimport(
        self, session_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Simulates MCP server restart: set, clear in-memory, get reads file."""
        state.set_session_active("survived")
        monkeypatch.setattr(state, "_session_active_project", None)  # Simulates restart
        assert state.get_session_active() == "survived"
```

### Step 1.3: Run tests; verify fail

```bash
cd plugins/proj/server && uv run pytest tests/test_state.py -v
```
Expected: AttributeError on `state._SESSION_FILE` or `state.clear_session_active` (undefined) + assertion failures.

### Step 1.4: Implement persistence in state.py

Read current state.py first to preserve existing API:

```bash
cat plugins/proj/server/server/lib/state.py
```

Then update the file to this shape (preserving any existing session mgmt + tooling):

File: `plugins/proj/server/server/lib/state.py`
```python
"""Session-scoped state for proj MCP server.

Active project is session-scoped but now file-backed for cross-process visibility
(wiki plugin reads proj-session.yaml via wiki_scope_detect). In-memory state
takes priority; file provides fallback/persistence across MCP server restarts.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Final

import yaml

_SESSION_FILE: Final[Path] = Path.home() / ".claude" / "proj-session.yaml"

_session_active_project: str | None = None


def _atomic_write(target: Path, content: str) -> None:
    """Atomically write content to target via tmpfile + rename."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        os.replace(tmp, target)
    except Exception:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def _read_session_file() -> str | None:
    """Read active-project name from session file. Returns None if missing/malformed."""
    if not _SESSION_FILE.exists():
        return None
    try:
        with _SESSION_FILE.open() as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    value = data.get("active")
    return str(value) if value else None


def get_session_active() -> str | None:
    """Return the session-scoped active project.

    In-memory state wins; falls back to on-disk session file (useful after MCP
    server restarts).
    """
    if _session_active_project is not None:
        return _session_active_project
    return _read_session_file()


def set_session_active(name: str) -> None:
    """Set the session-scoped active project. Writes to both in-memory + disk."""
    global _session_active_project
    _session_active_project = name
    _atomic_write(_SESSION_FILE, yaml.safe_dump({"active": name}, sort_keys=False))


def clear_session_active() -> None:
    """Clear session-scoped active project from both in-memory + disk. Idempotent."""
    global _session_active_project
    _session_active_project = None
    if _SESSION_FILE.exists():
        _SESSION_FILE.unlink()
```

### Step 1.5: Run tests; verify pass

```bash
cd plugins/proj/server && uv run pytest tests/test_state.py -v
```
Expected: 8 tests pass.

### Step 1.6: `just check` clean on proj

```bash
cd plugins/proj/server && just check
```
Expected: 0 errors.

### Step 1.7: Commit

```bash
git add plugins/proj/server/server/lib/state.py plugins/proj/server/tests/test_state.py
git commit -m "feat(proj): persist session-active project to ~/.claude/proj-session.yaml"
```

---

### Task 2: Proj — update callers if needed

**Goal:** Find all places that call `set_session_active` or `get_session_active`. Verify existing tests still pass. The API didn't change, but we want to confirm no caller relied on the file-not-existing as a signal.

**Files:** (verification-only; no guaranteed modifications)

- [ ] **Step 2.1: Grep callers**

```bash
cd /home/raul/worktrees/cpm/feat-688-karpathy-wiki-plugin
grep -rn "set_session_active\|get_session_active\|clear_session_active" plugins/proj/server/server/
```

Review each call site. If any test or helper assumes the file doesn't exist, flag it.

- [ ] **Step 2.2: Run full proj test suite**

```bash
cd plugins/proj/server && uv run pytest
```
Expected: all pass (no test touched _SESSION_FILE, but new fixture `session_file` isolates the new tests).

- [ ] **Step 2.3: If any existing test fails (because it monkey-patched old behavior)**: update it to use the new `_SESSION_FILE` monkeypatch pattern from Task 1's conftest-equivalent. If no test fails, skip.

- [ ] **Step 2.4: No commit unless fixes were needed**

If Task 2 required a test fix, commit as:
```bash
git add plugins/proj/server/tests/
git commit -m "test(proj): update existing tests for file-backed session-active"
```

---

### Task 3: Wiki — update `wiki_scope_detect` to read `proj-session.yaml`

**Goal:** `wiki_scope_detect` reads the new file to resolve active-project. Returns `scope: "project:<name>"` when available. Falls back to `"global"` when proj not present, file missing, or file malformed.

**Files:**
- Modify: `plugins/wiki/server/server/tools/scope.py`
- Modify: `plugins/wiki/server/tests/test_scope.py`
- Modify: `plugins/wiki/server/tests/conftest.py` — rename/extend `proj_yaml_path` fixture to cover both proj.yaml AND proj-session.yaml

- [ ] **Step 3.1: Update conftest fixture**

In `plugins/wiki/server/tests/conftest.py`, replace the existing `proj_yaml_path` fixture with one that handles both files:

```python
@pytest.fixture
def proj_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Redirect both proj.yaml + proj-session.yaml lookups in scope.py."""
    proj_yaml = tmp_path / "proj.yaml"
    session_yaml = tmp_path / "proj-session.yaml"
    monkeypatch.setattr("server.tools.scope._PROJ_YAML_PATH", proj_yaml)
    monkeypatch.setattr("server.tools.scope._SESSION_YAML_PATH", session_yaml)
    return {"proj_yaml": proj_yaml, "session_yaml": session_yaml}
```

Leave the old `proj_yaml_path` fixture in place as an alias if any other test still uses it:

```python
@pytest.fixture
def proj_yaml_path(proj_paths: dict[str, Path]) -> Path:
    """Legacy alias for proj_paths['proj_yaml']."""
    return proj_paths["proj_yaml"]
```

- [ ] **Step 3.2: Update failing tests + add new ones**

Replace existing `test_scope.py` TestWikiScopeDetect class with:

```python
"""Tests for wiki_scope_detect."""

import json
from pathlib import Path

import pytest
import yaml
from mcp.server.fastmcp import FastMCP

from tests.conftest import call_tool


@pytest.mark.asyncio
class TestWikiScopeDetect:
    async def test_proj_absent(self, mcp_app: FastMCP, proj_paths: dict[str, Path]) -> None:
        """proj.yaml doesn't exist → global, proj_present=False."""
        result = json.loads(await call_tool(mcp_app, "wiki_scope_detect"))
        assert result["scope"] == "global"
        assert result["proj_present"] is False

    async def test_proj_present_no_session(
        self, mcp_app: FastMCP, proj_paths: dict[str, Path]
    ) -> None:
        """proj.yaml exists, no session file → global, proj_present=True."""
        proj_paths["proj_yaml"].write_text(yaml.safe_dump({}))
        result = json.loads(await call_tool(mcp_app, "wiki_scope_detect"))
        assert result["scope"] == "global"
        assert result["proj_present"] is True

    async def test_session_file_resolves_project_scope(
        self, mcp_app: FastMCP, proj_paths: dict[str, Path]
    ) -> None:
        """Session file has `active: my-proj` → scope=project:my-proj."""
        proj_paths["proj_yaml"].write_text(yaml.safe_dump({}))
        proj_paths["session_yaml"].write_text(yaml.safe_dump({"active": "my-proj"}))
        result = json.loads(await call_tool(mcp_app, "wiki_scope_detect"))
        assert result["scope"] == "project:my-proj"
        assert result["proj_present"] is True

    async def test_session_file_without_proj_yaml_still_works(
        self, mcp_app: FastMCP, proj_paths: dict[str, Path]
    ) -> None:
        """If session file exists but proj.yaml doesn't, still detect scope."""
        # proj_present is based on proj.yaml existence; session file alone doesn't flip it
        proj_paths["session_yaml"].write_text(yaml.safe_dump({"active": "lonely-proj"}))
        result = json.loads(await call_tool(mcp_app, "wiki_scope_detect"))
        assert result["scope"] == "project:lonely-proj"
        assert result["proj_present"] is False  # proj.yaml didn't exist

    async def test_malformed_proj_yaml(
        self, mcp_app: FastMCP, proj_paths: dict[str, Path]
    ) -> None:
        """Malformed proj.yaml: treat as global but proj_present=True."""
        proj_paths["proj_yaml"].write_text("not: valid: yaml: :")
        result = json.loads(await call_tool(mcp_app, "wiki_scope_detect"))
        assert result["scope"] == "global"
        assert result["proj_present"] is True

    async def test_malformed_session_file_falls_back_to_global(
        self, mcp_app: FastMCP, proj_paths: dict[str, Path]
    ) -> None:
        proj_paths["proj_yaml"].write_text(yaml.safe_dump({}))
        proj_paths["session_yaml"].write_text("not: : : valid")
        result = json.loads(await call_tool(mcp_app, "wiki_scope_detect"))
        assert result["scope"] == "global"
        assert result["proj_present"] is True

    async def test_session_file_empty_active_field(
        self, mcp_app: FastMCP, proj_paths: dict[str, Path]
    ) -> None:
        """active: null or active: '' → treat as no active project."""
        proj_paths["proj_yaml"].write_text(yaml.safe_dump({}))
        proj_paths["session_yaml"].write_text(yaml.safe_dump({"active": None}))
        result = json.loads(await call_tool(mcp_app, "wiki_scope_detect"))
        assert result["scope"] == "global"
```

- [ ] **Step 3.3: Run tests; verify fail**

```bash
cd plugins/wiki/server && uv run pytest tests/test_scope.py -v
```
Expected: AttributeError on `_SESSION_YAML_PATH` + assertion failures for the new tests.

- [ ] **Step 3.4: Update scope.py**

File: `plugins/wiki/server/server/tools/scope.py`
```python
"""wiki_scope_detect: resolve active-project scope via proj plugin state.

Reads two files, both owned by proj plugin:
  - ~/.claude/proj.yaml          (existence signal → proj_present)
  - ~/.claude/proj-session.yaml  (active project name → scope)

No cross-MCP calls; pure file I/O per spec §3 persistence/synthesis boundary.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

_PROJ_YAML_PATH = Path.home() / ".claude" / "proj.yaml"
_SESSION_YAML_PATH = Path.home() / ".claude" / "proj-session.yaml"


def register(mcp: FastMCP) -> None:
    mcp.tool()(wiki_scope_detect)


def _read_active_from_session() -> str | None:
    """Read proj-session.yaml's `active` field. Returns None if missing/malformed/empty."""
    if not _SESSION_YAML_PATH.exists():
        return None
    try:
        with _SESSION_YAML_PATH.open() as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    value = data.get("active")
    if not value:
        return None
    return str(value)


def _proj_yaml_present() -> bool:
    """True if ~/.claude/proj.yaml exists (regardless of contents)."""
    return _PROJ_YAML_PATH.exists()


def _proj_yaml_readable() -> bool:
    """True if proj.yaml exists + is parseable. Used to distinguish 'malformed' from 'missing'."""
    if not _proj_yaml_present():
        return False
    try:
        with _PROJ_YAML_PATH.open() as f:
            yaml.safe_load(f)
    except yaml.YAMLError:
        return True  # exists but malformed — proj_present is still True
    return True


def wiki_scope_detect() -> str:
    """Detect active project scope via proj plugin's session file.

    Returns JSON {scope, proj_present}:
        - scope: "project:<name>" if proj_session_yaml has active project, else "global"
        - proj_present: whether ~/.claude/proj.yaml exists on disk
    """
    proj_present = _proj_yaml_present()
    active = _read_active_from_session()
    scope = f"project:{active}" if active else "global"
    return json.dumps({"scope": scope, "proj_present": proj_present})
```

- [ ] **Step 3.5: Run tests; verify pass**

```bash
cd plugins/wiki/server && uv run pytest tests/test_scope.py -v
```
Expected: 7 tests pass.

- [ ] **Step 3.6: Run full wiki suite to confirm no regression**

```bash
cd plugins/wiki/server && uv run pytest --cov=server
```
Expected: 163 (or 164 w/ the new test) pass; coverage still ≥85%.

- [ ] **Step 3.7: Commit**

```bash
git add plugins/wiki/server/server/tools/scope.py plugins/wiki/server/tests/test_scope.py plugins/wiki/server/tests/conftest.py
git commit -m "feat(wiki/688): scope_detect reads proj-session.yaml (addresses todo 705)"
```

---

### Task 4: Proj — add `WikiSync` dataclass to `models.py`

**Goal:** New `WikiSync` dataclass mirroring `TodoistSync`/`TrelloSync`/`JiraSync`. Integrates into `ProjConfig.sync.wiki` + from_dict/to_dict.

**Files:**
- Modify: `plugins/proj/server/server/lib/models.py`
- Create: `plugins/proj/server/tests/test_wiki_sync_config.py`

- [ ] **Step 4.1: Write failing tests**

File: `plugins/proj/server/tests/test_wiki_sync_config.py`
```python
"""Tests for WikiSync dataclass + ProjConfig.wiki integration."""
from __future__ import annotations

import pytest

from server.lib.models import ProjConfig, WikiSync


class TestWikiSync:
    def test_from_dict_defaults(self) -> None:
        w = WikiSync.from_dict({})
        assert w.enabled is False
        assert w.auto_sync is True
        assert w.auto_ingest_sessions is False
        assert w.capture_notes_as_log is False
        assert w.replace_notes_md is False
        assert w.bootstrap_docs == []

    def test_from_dict_overrides(self) -> None:
        w = WikiSync.from_dict({
            "enabled": True,
            "auto_sync": False,
            "auto_ingest_sessions": True,
            "capture_notes_as_log": True,
            "replace_notes_md": True,
            "bootstrap_docs": ["docs/arch.md", "overhaul.md"],
        })
        assert w.enabled is True
        assert w.auto_sync is False
        assert w.auto_ingest_sessions is True
        assert w.capture_notes_as_log is True
        assert w.replace_notes_md is True
        assert w.bootstrap_docs == ["docs/arch.md", "overhaul.md"]

    def test_to_dict_roundtrip(self) -> None:
        w = WikiSync(
            enabled=True,
            auto_sync=True,
            auto_ingest_sessions=True,
            capture_notes_as_log=False,
            replace_notes_md=False,
            bootstrap_docs=["a.md"],
        )
        restored = WikiSync.from_dict(w.to_dict())
        assert restored == w

    def test_bootstrap_docs_non_list_coerces_to_empty(self) -> None:
        w = WikiSync.from_dict({"bootstrap_docs": "not-a-list"})
        assert w.bootstrap_docs == []


class TestProjConfigWithWiki:
    def test_config_has_wiki_field_with_defaults(self) -> None:
        cfg = ProjConfig.from_dict({})
        assert hasattr(cfg, "wiki")
        assert cfg.wiki == WikiSync()

    def test_config_loads_wiki_sync(self) -> None:
        cfg = ProjConfig.from_dict({
            "sync": {
                "wiki": {
                    "enabled": True,
                    "auto_ingest_sessions": True,
                }
            }
        })
        assert cfg.wiki.enabled is True
        assert cfg.wiki.auto_ingest_sessions is True

    def test_config_roundtrip_preserves_wiki(self) -> None:
        cfg = ProjConfig.from_dict({
            "sync": {
                "wiki": {
                    "enabled": True,
                    "auto_ingest_sessions": True,
                    "capture_notes_as_log": True,
                }
            }
        })
        restored = ProjConfig.from_dict(cfg.to_dict())
        assert restored.wiki == cfg.wiki
```

- [ ] **Step 4.2: Run tests; verify fail**

```bash
cd plugins/proj/server && uv run pytest tests/test_wiki_sync_config.py -v
```
Expected: ImportError on `WikiSync` + AttributeError on `cfg.wiki`.

- [ ] **Step 4.3: Read models.py; locate the sync dataclasses + ProjConfig**

```bash
grep -n "class TodoistSync\|class TrelloSync\|class JiraSync\|class ProjConfig" plugins/proj/server/server/lib/models.py
```

- [ ] **Step 4.4: Add WikiSync dataclass**

Add to `plugins/proj/server/server/lib/models.py` after the JiraSync class:

```python
@dataclass
class WikiSync:
    """Wiki plugin integration settings under proj.yaml sync.wiki.*."""

    enabled: bool = False
    auto_sync: bool = True
    auto_ingest_sessions: bool = False
    capture_notes_as_log: bool = False
    replace_notes_md: bool = False
    bootstrap_docs: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: JsonDict) -> WikiSync:
        raw_docs = data.get("bootstrap_docs", []) or []
        docs = [str(d) for d in raw_docs] if isinstance(raw_docs, list) else []
        return cls(
            enabled=bool(data.get("enabled", False)),
            auto_sync=bool(data.get("auto_sync", True)),
            auto_ingest_sessions=bool(data.get("auto_ingest_sessions", False)),
            capture_notes_as_log=bool(data.get("capture_notes_as_log", False)),
            replace_notes_md=bool(data.get("replace_notes_md", False)),
            bootstrap_docs=docs,
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "enabled": self.enabled,
            "auto_sync": self.auto_sync,
            "auto_ingest_sessions": self.auto_ingest_sessions,
            "capture_notes_as_log": self.capture_notes_as_log,
            "replace_notes_md": self.replace_notes_md,
            "bootstrap_docs": list(self.bootstrap_docs),
        }
```

Add `wiki: WikiSync = field(default_factory=WikiSync)` as a new field in `ProjConfig`:

```python
@dataclass
class ProjConfig:
    # ... existing fields ...
    todoist: TodoistSync = field(default_factory=TodoistSync)
    trello: TrelloSync = field(default_factory=TrelloSync)
    jira: JiraSync = field(default_factory=JiraSync)
    wiki: WikiSync = field(default_factory=WikiSync)   # NEW
    # ... rest of existing fields ...
```

Update `ProjConfig.from_dict` to load wiki:

```python
# In from_dict method, after jira loading:
sync = data.get("sync", {}) or {}
wiki_data = sync.get("wiki", {}) or {}
# ... existing code that sets self.todoist etc ...
wiki=WikiSync.from_dict(wiki_data),
```

Update `ProjConfig.to_dict` to include wiki under `sync`:

```python
# In to_dict method, in the "sync" sub-dict:
"sync": {
    "todoist": self.todoist.to_dict(),
    "trello": self.trello.to_dict(),
    "jira": self.jira.to_dict(),
    "wiki": self.wiki.to_dict(),   # NEW
},
```

**Note:** These are sketch-level edits — the agent should read the actual models.py + apply surgically. The dataclass + field additions must preserve every other field in ProjConfig untouched.

- [ ] **Step 4.5: Run tests; verify pass**

```bash
cd plugins/proj/server && uv run pytest tests/test_wiki_sync_config.py -v
```
Expected: 6 tests pass.

- [ ] **Step 4.6: Run full proj suite — no regression**

```bash
cd plugins/proj/server && uv run pytest
```
Expected: all pass including new tests.

- [ ] **Step 4.7: `just check` clean**

```bash
cd plugins/proj/server && just check
```

- [ ] **Step 4.8: Commit**

```bash
git add plugins/proj/server/server/lib/models.py plugins/proj/server/tests/test_wiki_sync_config.py
git commit -m "feat(proj): add WikiSync dataclass + ProjConfig.wiki for sync.wiki.* yaml keys"
```

---

### Task 5: Proj — register router hook `notes_append` → `wiki_log_append`

**Goal:** Append one hook entry to `plugins/proj/.claude-plugin/default-hooks.yaml` matching spec §8.1. Condition `sync.wiki.enabled and sync.wiki.capture_notes_as_log`. Non-blocking (wiki logging shouldn't gate proj's `notes_append`).

**Files:**
- Modify: `plugins/proj/.claude-plugin/default-hooks.yaml`

- [ ] **Step 5.1: Read current file**

```bash
cat plugins/proj/.claude-plugin/default-hooks.yaml
```

- [ ] **Step 5.2: Append wiki hook entry**

Add to the end of `plugins/proj/.claude-plugin/default-hooks.yaml`:

```yaml

  - id: proj-wiki-log-on-notes-append
    trigger_tool: notes_append
    target_tool: wiki_log_append
    server: wiki
    param_mapping:
      action: "note"
      title: "${content_first_line}"
      body: "${content}"
    blocking: false
    condition: "sync.wiki.enabled and sync.wiki.capture_notes_as_log"
```

**Note:** `${content_first_line}` + `${content}` are template fields resolved from the source_result of `notes_append`. If the router's param-mapping DSL doesn't support deriving `content_first_line` inline, use just `${content}` for both title + body (the wiki log will store the full note).

- [ ] **Step 5.3: Validate YAML parseability**

```bash
python -c "import yaml; yaml.safe_load(open('plugins/proj/.claude-plugin/default-hooks.yaml'))"
```
Expected: no output, exit 0.

- [ ] **Step 5.4: If there are existing router-hook schema tests, run them**

```bash
grep -l "default-hooks" plugins/proj/server/tests/*.py
```

If a schema test exists (e.g. `test_default_hooks_refs.py`), run it:

```bash
cd plugins/proj/server && uv run pytest tests/test_default_hooks_refs.py -v
```
Expected: all tests pass (new entry matches existing structural expectations).

- [ ] **Step 5.5: Commit**

```bash
git add plugins/proj/.claude-plugin/default-hooks.yaml
git commit -m "feat(proj): register router hook notes_append → wiki_log_append"
```

---

### Task 6: Check wiki.yaml default config is consistent w/ WikiSync

**Goal:** Sanity check — Phase 2's `/wiki:init` skill writes `~/.claude/wiki.yaml` with a set of defaults. Proj's new `WikiSync` dataclass lives in `~/.claude/proj.yaml::sync.wiki`. These are **different files with complementary concerns**:
- `wiki.yaml` is wiki-plugin-owned (enabled, wiki_dir, bootstrap_pending, session_ingest.section_map).
- `proj.yaml::sync.wiki` is proj-plugin-owned (gates for the proj↔wiki integration).

Verify no field name collisions. This is a 5-minute verification, not a code change.

- [ ] **Step 6.1: List wiki.yaml fields**

From `plugins/wiki/server/server/lib/models.py::WikiConfig`:
- `enabled`, `wiki_dir`, `reingest_cooldown_hours`, `bootstrap_pending`, `session_ingest_section_map`

- [ ] **Step 6.2: List sync.wiki fields (P4a new)**

From `WikiSync` (Task 4):
- `enabled`, `auto_sync`, `auto_ingest_sessions`, `capture_notes_as_log`, `replace_notes_md`, `bootstrap_docs`

- [ ] **Step 6.3: Overlap analysis**

Both have an `enabled` field. This is OK because they're in different config files + have different semantics:
- `wiki.yaml::enabled` = "wiki plugin ready to serve requests"
- `proj.yaml::sync.wiki.enabled` = "proj should invoke wiki integrations"

Document this in a one-liner comment in wiki/README.md:

- [ ] **Step 6.4: Update wiki README**

Add to `plugins/wiki/README.md` under the Storage section, after the existing bullets:

```markdown

**Proj integration config** (when proj + wiki both installed):
- `~/.claude/proj.yaml::sync.wiki.*` — proj-owned flags gating integration behavior:
  - `enabled` — master switch for proj→wiki integration
  - `auto_ingest_sessions` — `/proj:save` spawns wiki ingest subagent on session file
  - `capture_notes_as_log` — router hook `notes_append` → `wiki_log_append` fires
  - `replace_notes_md` — (future) redirect `notes_append` to wiki entirely
  - `bootstrap_docs` — per-project doc paths to include in `/wiki:bootstrap`
- `~/.claude/proj-session.yaml` — proj-owned, session-scoped, file-backed active project marker. Wiki reads the `active` field to scope queries.
```

- [ ] **Step 6.5: Commit**

```bash
git add plugins/wiki/README.md
git commit -m "docs(wiki/688): document proj integration config surface"
```

---

### Task 7: Edit `/proj:save` skill — add final wiki ingest step

**Goal:** Between existing step 10 (`notes_append`) and step 12 (`tracking_git_flush`), add a new numbered step (11a or renumber) that spawns the wiki ingest subagent on the freshly-written session file when `sync.wiki.enabled and sync.wiki.auto_ingest_sessions`.

**Files:**
- Modify: `plugins/proj/skills/save/SKILL.md`

- [ ] **Step 7.1: Read current skill**

```bash
cat plugins/proj/skills/save/SKILL.md
```

Identify the numbering. Likely step 11 is `notes_append` / summary + step 12 is `tracking_git_flush` (per Explore report).

- [ ] **Step 7.2: Update allowed-tools**

Add to the `allowed-tools` frontmatter line:
- `mcp__plugin_wiki_wiki__wiki_log_append`
- `mcp__plugin_wiki_wiki__wiki_scope_detect`
- `Task`

(Keep existing entries.)

- [ ] **Step 7.3: Insert new step + update numbering if needed**

After the `notes_append` step (let's call it step N), before `tracking_git_flush` (step N+2), add a new step N+1:

```markdown
**N+1.** Wiki ingest (if `sync.wiki.enabled and sync.wiki.auto_ingest_sessions`):
- `mcp__proj__config_load` (if not already loaded) → read `sync.wiki.enabled` + `sync.wiki.auto_ingest_sessions`.
- Both flags true → spawn a forked subagent via `Task`:
    - `subagent_type="general-purpose"`
    - `description="Wiki ingest session file"`
    - `prompt` = `Read plugins/wiki/skills/ingest/references/subagent-prompt.md` + substitute `{source}` = `session:<full-session-file-path>`, `{scope}` = `project:<active-name>` (from step 1 session context), `{wiki_config}` = JSON of `wiki.yaml` + `wiki/config.yaml` contents.
- Wait for subagent JSON return. On success, render a one-line summary: "Wiki ingest complete: N pages created, M updated."
- On failure, print warning ("Wiki ingest failed: <err>. Session file saved successfully. Retry manually via `/wiki:ingest session:<path>`.") + continue.
- Either flag false → silently skip this step.
```

Renumber subsequent steps if needed (step 12 becomes step N+2, etc.).

- [ ] **Step 7.4: Verify edit**

```bash
head -30 plugins/proj/skills/save/SKILL.md  # confirm frontmatter updated
grep -A 10 "Wiki ingest" plugins/proj/skills/save/SKILL.md  # confirm step inserted
```

- [ ] **Step 7.5: Commit**

```bash
git add plugins/proj/skills/save/SKILL.md
git commit -m "feat(proj): /proj:save spawns wiki ingest subagent on session file (when enabled)"
```

---

### Task 8: End-to-end smoke (manual + automated)

**Goal:** Verify the loop works. Python tests + one manual scripted check.

**Files:** (verification-only)

- [ ] **Step 8.1: Full proj test suite**

```bash
cd plugins/proj/server && uv run pytest --cov=server 2>&1 | tail -10
```
Expected: all pass, coverage within existing threshold.

- [ ] **Step 8.2: Full wiki test suite**

```bash
cd plugins/wiki/server && uv run pytest --cov=server 2>&1 | tail -10
```
Expected: all pass (164+), ≥85% coverage.

- [ ] **Step 8.3: `just ci` on both plugins**

```bash
cd plugins/proj/server && just ci
cd ../../wiki/server && just ci
```
Expected: both green.

- [ ] **Step 8.4: Scripted cross-plugin smoke**

This verifies the round-trip that matters most: proj sets session-active → wiki reads + returns project scope.

```bash
cd /home/raul/worktrees/cpm/feat-688-karpathy-wiki-plugin
uv run python <<'EOF'
import os
import tempfile
import asyncio
from pathlib import Path

# Isolate — redirect HOME to a scratch dir so this smoke doesn't touch real state
scratch = Path(tempfile.mkdtemp())
os.environ["HOME"] = str(scratch)
(scratch / ".claude").mkdir()

# Write a minimal proj.yaml to signal proj_present
(scratch / ".claude" / "proj.yaml").write_text("version: 1\n")

# Import proj's state + set an active project (this writes proj-session.yaml)
import sys
sys.path.insert(0, str(Path("plugins/proj/server").resolve()))
from server.lib import state as proj_state

# Force _SESSION_FILE to re-evaluate now that HOME is scratch
import importlib
importlib.reload(proj_state)
proj_state.set_session_active("smoke-project")

# Verify the file was written
session_file = scratch / ".claude" / "proj-session.yaml"
assert session_file.exists(), f"Expected {session_file} to exist"
print(f"✓ proj-session.yaml written: {session_file.read_text().strip()}")

# Now call wiki_scope_detect (the MCP tool's Python entrypoint)
sys.path.insert(0, str(Path("plugins/wiki/server").resolve()))
from server.tools import scope as wiki_scope

importlib.reload(wiki_scope)
result = wiki_scope.wiki_scope_detect()
import json
parsed = json.loads(result)
print(f"✓ wiki_scope_detect returned: {parsed}")

assert parsed["scope"] == "project:smoke-project", f"Expected scope=project:smoke-project, got {parsed}"
assert parsed["proj_present"] is True
print("✓ SMOKE PASSED: proj-session.yaml round-trips through wiki_scope_detect")

# Cleanup
proj_state.clear_session_active()
assert not session_file.exists()
print("✓ clear_session_active removes the file")
EOF
```
Expected output: all three ✓ lines + "SMOKE PASSED".

- [ ] **Step 8.5: If smoke fails, investigate + fix**

Common failure modes:
- `_SESSION_FILE` using cached Path.home() — fix by using `Path.home()` at call time (not module-import time).
- Import cycles — fix by deferring imports.

- [ ] **Step 8.6: No commit unless fix lands**

If smoke passes: no new commit. If smoke uncovered a bug: fix + commit:

```bash
git add <fixed-file>
git commit -m "fix(688): <describe the smoke fix>"
```

---

### Task 9: Update plugin README + spec phase status

**Files:**
- Modify: `plugins/wiki/README.md`

- [ ] **Step 9.1: Update Phase status section**

Replace:
```markdown
- **Phase 4** — proj touchpoints (router hook, `/proj:save` integration, wizard), Tier-2 semantic lint. Pending.
```

With:
```markdown
- **Phase 4a** — proj integration foundation: session-active file persistence (fixes scope-detection), router hook `notes_append` → `wiki_log_append`, `/proj:save` final step spawns wiki ingest subagent. ✅
- **Phase 4b** — wizard integration (installer prompts for wiki section). Pending.
- **Phase 4c** — Tier-2 semantic lint (contradictions, deprecation, missing cross-refs, category cluster suggestions). Pending.
```

- [ ] **Step 9.2: Commit**

```bash
git add plugins/wiki/README.md
git commit -m "docs(wiki/688): update README w/ Phase 4a completion status"
```

---

### Task 10: Final code review

**Goal:** Dispatch `superpowers:code-reviewer` subagent. Focus on: cross-plugin state-file contract, schema migration safety, router hook correctness, /proj:save regression risk.

- [ ] **Step 10.1: Get SHAs**

```bash
cd /home/raul/worktrees/cpm/feat-688-karpathy-wiki-plugin
git log --oneline 5ae9f20..HEAD
```

Expected: ~8-10 commits across proj + wiki.

- [ ] **Step 10.2: Dispatch reviewer**

Focus areas:
1. **Cross-plugin file contract** — `proj-session.yaml` is owned by proj but read by wiki. Does the schema + read/write coupling look reasonable? Any race conditions (proj writing while wiki reading)?
2. **Atomic write safety** — `state._atomic_write` creates tmpfile + rename. Matches proj's existing atomic-write patterns elsewhere?
3. **WikiSync schema additions** — any field overlap / shadowing with other Sync dataclasses or ProjConfig top-level fields? Migration-safe for users w/ existing proj.yaml (no sync.wiki section yet)?
4. **Router hook condition DSL** — `"sync.wiki.enabled and sync.wiki.capture_notes_as_log"` evaluates correctly against ProjConfig dot-path resolution?
5. **Skill change in `/proj:save`** — new step doesn't break existing users (both flags default-false); allowed-tools list covers all calls in the new step?
6. **Testing surface** — each of the 3 new cross-cutting concerns (state file, WikiSync, scope_detect) has adequate coverage? Smoke test covers the integration round-trip?
7. **Follow-ups from todos 706/707/708** — any accidentally resolved or newly blocked by P4a?

- [ ] **Step 10.3: Address any critical/important issues**

Apply fixes as a single commit + re-run smoke + suite.

- [ ] **Step 10.4: File consolidated follow-up todo** (if minor items surface)

---

## Verification

At phase-end:

1. `wiki_scope_detect` returns `project:<name>` after `/proj:load <name>` — confirmed via smoke Task 8.
2. Proj test suite passes (existing + 8 new state tests + 6 new WikiSync tests).
3. Wiki test suite passes (existing 163 + updated scope tests).
4. `just ci` green on both plugins.
5. Router hook entry structurally valid (`test_default_hooks_refs.py` passes).
6. `/proj:save` skill updated — manual smoke recommended after phase: init a scratch project, load it, author a note, save session, check wiki log has new entry.

## Handoff to Phase 4b (wizard)

After P4a lands, P4b adds:
- Installer wizard "wiki" section: enable, profile picker, session-ingest section map, sync.wiki.* flags, bootstrap-queue marker (writes `wiki.yaml::bootstrap_pending: true` for next-session pickup).
- Plan to be written when P4a is ready to merge.

## Handoff to Phase 4c (Tier-2 lint)

- Extend `/wiki:lint` skill with Tier-2 subagent dispatch.
- Add 4 LLM-driven semantic checks: contradictions, deprecation candidates, missing cross-refs, category cluster suggestions.
- Plan to be written after P4b.

---

## Self-review notes (pre-handoff)

- **Spec §7.2 scope auto-detection:** fixed via file-backed session-active ✓
- **Spec §8.1 router hook:** added `notes_append` → `wiki_log_append` w/ condition ✓
- **Spec §8.2 session ingest:** `/proj:save` gains the final step ✓
- **Spec §4.3 sync.wiki schema:** `WikiSync` dataclass matches spec fields ✓
- **Spec §3 persistence/synthesis boundary:** `wiki_scope_detect` remains pure-data (file reads only, no MCP call, no LLM) ✓
- **No new MCP tools:** correct — P4a refactors existing tools only ✓
- **No breaking change:** all new flags default-false; existing users see no behavior change until they opt in ✓
