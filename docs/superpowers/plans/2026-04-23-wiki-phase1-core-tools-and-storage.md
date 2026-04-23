# Wiki Plugin Phase 1: Core MCP Tools + Storage + Profile Loader — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the foundation of the `wiki` cpm plugin — core persistence + pure-data MCP tools (page CRUD, index, log, links, scope), profile loader, frontmatter parser, atomic lock infrastructure, + 85%+ unit-test coverage. At end of Phase 1, the wiki plugin's MCP server is installable and callable; no user-facing skills yet (those come in Phase 2).

**Architecture:** New `plugins/wiki/` plugin following existing cpm plugin conventions (FastMCP server, `server/server/` inner package, `~/.claude/wiki.yaml` + `~/.claude/wiki/config.yaml` config split, per-plugin `pyproject.toml` + `uv.lock`, path-dep on `plugins/_shared`, atomic `threading.Lock` + `fcntl.flock` pattern). All tools are pure-data — no LLM calls. Storage under `~/.claude/wiki/`: `pages/<category>/*.md`, `index.md`, `log.md`, `config.yaml`, `.lock`. BM25 sidecar `.index/` is **deferred to Phase 2**.

**Tech Stack:** Python 3.12, FastMCP (`mcp.server.fastmcp.FastMCP`), PyYAML, stdlib `dataclasses`, `fcntl` + `threading` for locks, pytest + pytest-asyncio + pytest-cov, ruff, basedpyright, uv, justfile.

**Spec reference:** `docs/superpowers/specs/2026-04-21-karpathy-wiki-plugin-design.md` (same worktree). Phase 1 = §15 "Phase 1: Core MCP tools + storage + profile loader".

---

## Scope (what's IN Phase 1, what's OUT)

**IN:**
- `plugins/wiki/` scaffolding: `.claude-plugin/`, `.mcp.json`, `README.md`, `server/` tree
- `server/server/lib/` — `config.py`, `profile.py`, `storage.py`, `frontmatter.py`, `models.py`
- `server/server/tools/` — `page.py`, `index.py`, `log.py`, `links.py`, `scope.py`
- MCP tools: `wiki_page_write`, `wiki_page_get`, `wiki_page_list`, `wiki_page_delete`, `wiki_index_read`, `wiki_index_rebuild`, `wiki_log_append`, `wiki_log_read`, `wiki_link_resolve`, `wiki_scope_detect`
- Four profile defaults (`software`, `personal`, `research`, `minimal`) + `custom` support
- Atomic lock (`threading.Lock` + `fcntl.flock` on `~/.claude/wiki/.lock`)
- Unit tests: target 85%+ coverage on `server/server/`
- Marketplace registration (`.claude-plugin/marketplace.json` root entry)

**OUT (later phases):**
- Lint tools (`wiki_lint_*`) — Phase 2
- BM25 search (`wiki_search_bm25`, `wiki_search_index_refresh`) — Phase 2
- Any `/wiki:*` skills — Phase 2+
- Ingest / query / bootstrap — Phase 3
- Router hook registration + `/proj:save` integration — Phase 4
- Wizard integration — Phase 4

---

## File Structure

All paths relative to repo root `/home/raul/projects/claude-project-manager/` (executed inside worktree `/home/raul/worktrees/cpm/feat-688-karpathy-wiki-plugin/`).

```
plugins/wiki/
├── .claude-plugin/
│   ├── default-hooks.yaml         # empty in P1 (no hooks yet)
│   └── plugin.json                # plugin metadata (name, version, etc.)
├── .mcp.json                      # MCP server registration
├── start.sh                       # launcher; copied from plugins/proj/start.sh
├── README.md                      # brief overview + pointer to spec
└── server/
    ├── pyproject.toml             # deps, ruff + basedpyright + pytest config
    ├── uv.lock                    # lockfile
    ├── justfile                   # check / test / security / ci
    ├── server/
    │   ├── __init__.py
    │   ├── main.py                # FastMCP entrypoint; register tool modules
    │   ├── lib/
    │   │   ├── __init__.py
    │   │   ├── config.py          # wiki.yaml runtime config loader
    │   │   ├── profile.py         # category profile loader (4 builtins + custom)
    │   │   ├── storage.py         # path resolution, atomic write, shared lock
    │   │   ├── frontmatter.py     # YAML-frontmatter / markdown-body parser
    │   │   └── models.py          # WikiConfig, Profile, Page dataclasses
    │   └── tools/
    │       ├── __init__.py
    │       ├── page.py            # wiki_page_write/get/list/delete
    │       ├── index.py           # wiki_index_read/rebuild
    │       ├── log.py             # wiki_log_append/read
    │       ├── links.py           # wiki_link_resolve (page + page#section)
    │       └── scope.py           # wiki_scope_detect
    └── tests/
        ├── conftest.py            # fixtures: tmp wiki dir, wiki_cfg, mcp_app
        ├── test_profile.py
        ├── test_frontmatter.py
        ├── test_storage.py
        ├── test_page.py
        ├── test_index.py
        ├── test_log.py
        ├── test_links.py
        └── test_scope.py

.claude-plugin/marketplace.json    # root marketplace — add wiki entry
```

**Responsibilities:**
- `lib/config.py` — load / save `~/.claude/wiki.yaml` (runtime flags: `enabled`, `wiki_dir`, `reingest_cooldown_hours`, `session_ingest.section_map`, `bootstrap_pending`).
- `lib/profile.py` — load / validate category profile from `~/.claude/wiki/config.yaml` (the wiki-local config); ship 4 builtin profile definitions.
- `lib/storage.py` — atomic file I/O, path resolution, shared `fcntl` lock; any tool that writes to `~/.claude/wiki/` uses this.
- `lib/frontmatter.py` — parse `---`-delimited YAML frontmatter + markdown body from a string or file; serialize back.
- `lib/models.py` — typed dataclasses: `WikiConfig`, `Profile`, `Page` (frontmatter + body + path).
- `tools/page.py` — page CRUD + list filters. Delegates file I/O to `storage.py`.
- `tools/index.py` — read index.md, rebuild index.md from `pages/**`.
- `tools/log.py` — append log entry in `## [YYYY-MM-DD] action | title` format; read back filtered entries.
- `tools/links.py` — resolve `[[page]]` + `[[page#section]]` to `{resolved, section_found, candidates}`.
- `tools/scope.py` — introspect proj.yaml presence + active project → return scope tag.

---

## TCP Port Reservation

Reserve port **19109** for wiki in the HOOK_TRANSPORT TCP fallback table. Ports already used per `CLAUDE.md`:
`router 19100, proj 19102, worktree 19103, trello 19104, jira 19105, todoist 19106, zoxide 19107, confluence 19108`. Wiki = next available = **19109**.

Update `CLAUDE.md` port table in a final doc-commit step (Task 19).

---

## Task Breakdown

19 tasks total. Each produces a self-contained, testable, committable unit.

---

### Task 1: Scaffold `plugins/wiki/` + MCP server boilerplate

**Goal:** Create the plugin directory tree + all non-code metadata files (plugin.json, .mcp.json, start.sh, README.md, pyproject.toml, justfile). Server is importable but has no tools yet.

**Files:**
- Create: `plugins/wiki/.claude-plugin/plugin.json`
- Create: `plugins/wiki/.claude-plugin/default-hooks.yaml`
- Create: `plugins/wiki/.mcp.json`
- Create: `plugins/wiki/start.sh` (copy from `plugins/proj/start.sh`, change plugin name)
- Create: `plugins/wiki/README.md`
- Create: `plugins/wiki/server/pyproject.toml`
- Create: `plugins/wiki/server/justfile`
- Create: `plugins/wiki/server/server/__init__.py` (empty)
- Create: `plugins/wiki/server/server/main.py` (stub)

- [ ] **Step 1.1: Copy start.sh from proj as template**

```bash
mkdir -p plugins/wiki/.claude-plugin plugins/wiki/server/server
cp plugins/proj/start.sh plugins/wiki/start.sh
chmod +x plugins/wiki/start.sh
```

Edit `plugins/wiki/start.sh` to replace any `proj` references with `wiki` (server name argument).

- [ ] **Step 1.2: Write plugin.json**

File: `plugins/wiki/.claude-plugin/plugin.json`
```json
{
  "name": "wiki",
  "version": "0.1.0",
  "description": "Karpathy-style LLM wiki: persistent, LLM-maintained markdown knowledge base with entity pages, cross-refs, + append-only log",
  "author": {"name": "raulfrk"},
  "license": "MIT",
  "keywords": ["wiki", "knowledge-base", "markdown", "karpathy"]
}
```

- [ ] **Step 1.3: Write empty default-hooks.yaml**

File: `plugins/wiki/.claude-plugin/default-hooks.yaml`
```yaml
# Wiki plugin hooks — populated in Phase 4 (proj integration).
hooks: []
servers: {}
settings:
  max_depth: 3
```

- [ ] **Step 1.4: Write .mcp.json**

File: `plugins/wiki/.mcp.json`
```json
{
  "mcpServers": {
    "wiki": {
      "command": "bash",
      "args": ["${CLAUDE_PLUGIN_ROOT}/start.sh", "${CLAUDE_PLUGIN_ROOT}/server", "wiki-server"],
      "env": {"WIKI_CONFIG": "~/.claude/wiki.yaml"},
      "timeout": 120
    }
  }
}
```

- [ ] **Step 1.5: Write README.md (brief)**

File: `plugins/wiki/README.md`
```markdown
# wiki

Karpathy-style LLM wiki plugin for cpm. Persistent, LLM-maintained markdown knowledge base.

See full design spec at `docs/superpowers/specs/2026-04-21-karpathy-wiki-plugin-design.md`.

## Storage

- `~/.claude/wiki.yaml` — runtime config (enabled flag, session-ingest map, etc.)
- `~/.claude/wiki/` — wiki root
  - `config.yaml` — category profile + lint rules
  - `index.md` — page catalog
  - `log.md` — append-only ledger
  - `pages/<category>/*.md` — wiki pages
  - `.lock` — fcntl lock
  - `.index/` — BM25 sidecar (Phase 2)

## Phase status

Phase 1 (this release): core MCP tools only (page CRUD, index, log, links, scope). No skills yet; no lint; no search.
```

- [ ] **Step 1.6: Write pyproject.toml**

File: `plugins/wiki/server/pyproject.toml`
```toml
[project]
name = "wiki-server"
version = "0.1.0"
description = "Wiki plugin MCP server"
requires-python = ">=3.12"
dependencies = [
    "mcp>=1.0.0",
    "pyyaml>=6.0",
    "claude-hook-transport",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-cov>=4.0",
    "pytest-xdist>=3.0",
    "ruff>=0.8",
    "basedpyright>=1.20",
    "bandit>=1.7",
    "pip-audit>=2.6",
]

[project.scripts]
wiki-server = "server.main:main"

[tool.uv.sources]
claude-hook-transport = { path = "../../_shared" }

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "UP", "B", "S", "A", "C4", "SIM"]
ignore = ["S101"]

[tool.basedpyright]
pythonVersion = "3.12"
typeCheckingMode = "strict"
reportMissingTypeStubs = false

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = ["-v", "--tb=short", "--cov=server", "--cov-fail-under=85", "-n", "auto"]
asyncio_mode = "auto"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["server"]
```

- [ ] **Step 1.7: Write justfile**

File: `plugins/wiki/server/justfile`
```make
default:
    @just --list

@check:
    uv run ruff check --fix .
    uv run ruff format .
    uv run basedpyright server/

@test:
    uv run pytest

@security:
    uv run bandit -r server
    uv run pip-audit --desc

@ci: check test security
```

- [ ] **Step 1.8: Write empty __init__.py + stub main.py**

File: `plugins/wiki/server/server/__init__.py` — empty file.

File: `plugins/wiki/server/server/main.py`
```python
"""Wiki plugin MCP server entrypoint."""
from hook_dispatch import enable_hook_dispatch
from hook_transport import run_dual
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("wiki")
enable_hook_dispatch(mcp)

# Tool modules registered in later tasks.


def main() -> None:
    run_dual(mcp, "wiki", default_port=19109)


if __name__ == "__main__":
    main()
```

- [ ] **Step 1.9: uv sync**

```bash
cd plugins/wiki/server && uv sync --all-groups
```
Expected: succeeds; `uv.lock` created.

- [ ] **Step 1.10: Verify basedpyright + ruff clean on empty server**

```bash
cd plugins/wiki/server && just check
```
Expected: 0 errors, 0 warnings.

- [ ] **Step 1.11: Commit**

```bash
git add plugins/wiki/
cd plugins/wiki/server && git add pyproject.toml uv.lock
git commit -m "feat(wiki/688): scaffold plugin skeleton (plugin.json, .mcp.json, pyproject, justfile)"
```

---

### Task 2: Add wiki entry to root marketplace.json

**Files:**
- Modify: `.claude-plugin/marketplace.json` — insert `plugins[]` entry for `wiki`

- [ ] **Step 2.1: Read current marketplace.json**

```bash
cat .claude-plugin/marketplace.json | head -50
```
Expected: see existing `plugins: [...]` array with proj, worktree, etc.

- [ ] **Step 2.2: Insert wiki entry alphabetically (after trello, before worktree)**

In `.claude-plugin/marketplace.json`, add this object inside `plugins[]`:
```json
{
  "name": "wiki",
  "source": "./plugins/wiki",
  "description": "Karpathy-style LLM wiki: persistent markdown knowledge base with entity pages, cross-refs, + append-only log",
  "version": "0.1.0",
  "author": {"name": "raulfrk"},
  "license": "MIT",
  "category": "productivity",
  "keywords": ["wiki", "knowledge-base", "markdown"]
}
```

- [ ] **Step 2.3: Validate JSON syntax**

```bash
python -m json.tool .claude-plugin/marketplace.json > /dev/null
```
Expected: no output, exit 0.

- [ ] **Step 2.4: Commit**

```bash
git add .claude-plugin/marketplace.json
git commit -m "feat(wiki/688): register plugin in root marketplace.json"
```

---

### Task 3: `lib/models.py` — typed dataclasses

**Goal:** Define `WikiConfig`, `Profile`, `Page` dataclasses. Each has `from_dict`/`to_dict` per existing cpm convention.

**Files:**
- Create: `plugins/wiki/server/server/lib/__init__.py` (empty)
- Create: `plugins/wiki/server/server/lib/models.py`
- Create: `plugins/wiki/server/tests/__init__.py` (empty)
- Create: `plugins/wiki/server/tests/test_models.py`

- [ ] **Step 3.1: Write failing tests**

File: `plugins/wiki/server/tests/test_models.py`
```python
"""Tests for lib/models.py."""
from datetime import datetime, timezone
from pathlib import Path

import pytest

from server.lib.models import Page, Profile, WikiConfig


class TestWikiConfig:
    def test_from_dict_defaults(self) -> None:
        cfg = WikiConfig.from_dict({})
        assert cfg.enabled is False
        assert cfg.wiki_dir == Path.home() / ".claude" / "wiki"
        assert cfg.reingest_cooldown_hours == 24
        assert cfg.bootstrap_pending is False
        assert cfg.session_ingest_section_map == {}

    def test_from_dict_overrides(self) -> None:
        cfg = WikiConfig.from_dict({
            "enabled": True,
            "wiki_dir": "/tmp/w",
            "reingest_cooldown_hours": 1,
            "bootstrap_pending": True,
            "session_ingest": {"section_map": {"Key Decisions": "decisions"}},
        })
        assert cfg.enabled is True
        assert cfg.wiki_dir == Path("/tmp/w")
        assert cfg.reingest_cooldown_hours == 1
        assert cfg.bootstrap_pending is True
        assert cfg.session_ingest_section_map == {"Key Decisions": "decisions"}

    def test_to_dict_roundtrip(self) -> None:
        cfg = WikiConfig(
            enabled=True,
            wiki_dir=Path("/tmp/w"),
            reingest_cooldown_hours=12,
            bootstrap_pending=False,
            session_ingest_section_map={"X": "y"},
        )
        restored = WikiConfig.from_dict(cfg.to_dict())
        assert restored == cfg


class TestProfile:
    def test_builtin_software_shape(self) -> None:
        # software profile must have exactly these 5 categories
        p = Profile(
            name="software",
            categories=["concepts", "decisions", "references", "pitfalls", "entities"],
            session_section_map_default={"Key Decisions": "decisions"},
        )
        assert "decisions" in p.categories
        assert p.name == "software"

    def test_categories_must_be_nonempty_unless_minimal(self) -> None:
        with pytest.raises(ValueError, match="categories cannot be empty"):
            Profile(name="custom", categories=[], session_section_map_default={})

    def test_minimal_profile_empty_categories_allowed(self) -> None:
        # minimal profile explicitly allows empty categories (flat pages/)
        p = Profile(name="minimal", categories=[], session_section_map_default={})
        assert p.categories == []


class TestPage:
    def test_from_frontmatter_body(self) -> None:
        fm = {
            "title": "Hooks architecture",
            "tags": ["hooks", "plugin"],
            "links_to": ["router"],
            "scope": ["project:cpm"],
            "sources": [{"type": "file", "ref": "/tmp/x.md", "ingested_at": "2026-04-23T10:00:00Z"}],
            "last_ingested": "2026-04-23T10:00:00Z",
        }
        body = "# Hooks\n\nContent."
        p = Page(path=Path("/tmp/hooks.md"), frontmatter=fm, body=body)
        assert p.title == "Hooks architecture"
        assert "hooks" in p.tags
        assert p.scope == ["project:cpm"]

    def test_slug_from_filename(self) -> None:
        p = Page(path=Path("/tmp/pages/concepts/hooks-architecture.md"), frontmatter={"title": "X"}, body="")
        assert p.slug == "hooks-architecture"

    def test_category_from_path(self) -> None:
        p = Page(path=Path("/tmp/pages/concepts/hooks-architecture.md"), frontmatter={"title": "X"}, body="")
        assert p.category == "concepts"

    def test_category_none_for_flat(self) -> None:
        p = Page(path=Path("/tmp/pages/hooks.md"), frontmatter={"title": "X"}, body="")
        assert p.category is None
```

- [ ] **Step 3.2: Run tests; verify all fail**

```bash
cd plugins/wiki/server && uv run pytest tests/test_models.py -v
```
Expected: ImportError / ModuleNotFoundError for `server.lib.models`.

- [ ] **Step 3.3: Write models.py**

File: `plugins/wiki/server/server/lib/__init__.py` — empty.

File: `plugins/wiki/server/server/lib/models.py`
```python
"""Typed dataclasses for wiki config, profiles, + pages."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class WikiConfig:
    """Runtime configuration from ~/.claude/wiki.yaml."""
    enabled: bool = False
    wiki_dir: Path = field(default_factory=lambda: Path.home() / ".claude" / "wiki")
    reingest_cooldown_hours: int = 24
    bootstrap_pending: bool = False
    session_ingest_section_map: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WikiConfig:
        wiki_dir_raw = data.get("wiki_dir")
        wiki_dir = (
            Path(str(wiki_dir_raw)).expanduser()
            if wiki_dir_raw
            else Path.home() / ".claude" / "wiki"
        )
        session_ingest = data.get("session_ingest", {}) or {}
        section_map = session_ingest.get("section_map", {}) if isinstance(session_ingest, dict) else {}
        return cls(
            enabled=bool(data.get("enabled", False)),
            wiki_dir=wiki_dir,
            reingest_cooldown_hours=int(data.get("reingest_cooldown_hours", 24)),
            bootstrap_pending=bool(data.get("bootstrap_pending", False)),
            session_ingest_section_map=dict(section_map) if isinstance(section_map, dict) else {},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "wiki_dir": str(self.wiki_dir),
            "reingest_cooldown_hours": self.reingest_cooldown_hours,
            "bootstrap_pending": self.bootstrap_pending,
            "session_ingest": {"section_map": dict(self.session_ingest_section_map)},
        }


@dataclass
class Profile:
    """Category profile loaded from ~/.claude/wiki/config.yaml."""
    name: str
    categories: list[str]
    session_section_map_default: dict[str, str]

    def __post_init__(self) -> None:
        if self.name != "minimal" and not self.categories:
            raise ValueError("Profile categories cannot be empty (except for 'minimal' profile)")


@dataclass
class Page:
    """A wiki page: filesystem path + parsed frontmatter + body text."""
    path: Path
    frontmatter: dict[str, Any]
    body: str

    @property
    def title(self) -> str:
        return str(self.frontmatter.get("title", ""))

    @property
    def slug(self) -> str:
        return self.path.stem

    @property
    def tags(self) -> list[str]:
        raw = self.frontmatter.get("tags", []) or []
        return [str(t) for t in raw] if isinstance(raw, list) else []

    @property
    def scope(self) -> list[str]:
        raw = self.frontmatter.get("scope", []) or []
        if isinstance(raw, str):
            return [raw]
        return [str(s) for s in raw] if isinstance(raw, list) else []

    @property
    def category(self) -> str | None:
        """Return the category directory name (e.g. 'concepts') or None for flat-layout pages."""
        parts = self.path.parts
        # Expected shape: .../pages/<category>/<slug>.md
        if "pages" in parts:
            idx = parts.index("pages")
            # If there's a dir between 'pages' and the file, that's the category.
            if idx + 2 < len(parts):
                return parts[idx + 1]
        return None
```

- [ ] **Step 3.4: Run tests; verify all pass**

```bash
cd plugins/wiki/server && uv run pytest tests/test_models.py -v
```
Expected: all 9 tests pass.

- [ ] **Step 3.5: basedpyright + ruff clean**

```bash
cd plugins/wiki/server && just check
```
Expected: 0 errors.

- [ ] **Step 3.6: Commit**

```bash
git add plugins/wiki/server/server/lib/ plugins/wiki/server/tests/
git commit -m "feat(wiki/688): add models.py with WikiConfig/Profile/Page dataclasses + tests"
```

---

### Task 4: `lib/frontmatter.py` — YAML-frontmatter parser

**Goal:** Parse markdown files with `---`-delimited YAML frontmatter. Used by every tool that reads pages.

**Files:**
- Create: `plugins/wiki/server/server/lib/frontmatter.py`
- Create: `plugins/wiki/server/tests/test_frontmatter.py`

- [ ] **Step 4.1: Write failing tests**

File: `plugins/wiki/server/tests/test_frontmatter.py`
```python
"""Tests for lib/frontmatter.py."""
import pytest

from server.lib.frontmatter import FrontmatterError, dump, parse


class TestParse:
    def test_parse_valid(self) -> None:
        raw = "---\ntitle: Hooks\ntags: [a, b]\n---\n# Body\n\nContent."
        fm, body = parse(raw)
        assert fm == {"title": "Hooks", "tags": ["a", "b"]}
        assert body == "# Body\n\nContent."

    def test_parse_no_frontmatter(self) -> None:
        raw = "# No frontmatter here\n\nJust body."
        fm, body = parse(raw)
        assert fm == {}
        assert body == raw

    def test_parse_empty_frontmatter(self) -> None:
        raw = "---\n---\n# Body"
        fm, body = parse(raw)
        assert fm == {}
        assert body == "# Body"

    def test_parse_missing_closing_delim(self) -> None:
        raw = "---\ntitle: Hooks\n# missing close\n"
        with pytest.raises(FrontmatterError, match="unterminated frontmatter"):
            parse(raw)

    def test_parse_invalid_yaml(self) -> None:
        raw = "---\ntitle: : :\n---\nbody"
        with pytest.raises(FrontmatterError, match="invalid YAML"):
            parse(raw)

    def test_parse_preserves_body_leading_whitespace(self) -> None:
        raw = "---\ntitle: X\n---\n\n\nBody with leading newlines"
        fm, body = parse(raw)
        assert fm == {"title": "X"}
        # Exactly 2 leading newlines preserved (the blank line after --- + one more)
        assert body == "\n\nBody with leading newlines"


class TestDump:
    def test_dump_roundtrip(self) -> None:
        raw = "---\ntitle: Hooks\ntags:\n- a\n- b\n---\nBody."
        fm, body = parse(raw)
        redumped = dump(fm, body)
        fm2, body2 = parse(redumped)
        assert fm == fm2
        assert body.strip() == body2.strip()

    def test_dump_empty_frontmatter(self) -> None:
        result = dump({}, "just body")
        # No frontmatter when empty → body only
        assert result == "just body"

    def test_dump_with_body(self) -> None:
        result = dump({"title": "X"}, "body text")
        fm, body = parse(result)
        assert fm == {"title": "X"}
        assert body == "body text"
```

- [ ] **Step 4.2: Run tests; verify all fail**

```bash
cd plugins/wiki/server && uv run pytest tests/test_frontmatter.py -v
```
Expected: ImportError.

- [ ] **Step 4.3: Write frontmatter.py**

File: `plugins/wiki/server/server/lib/frontmatter.py`
```python
"""YAML-frontmatter + markdown-body parser."""
from __future__ import annotations

from typing import Any

import yaml


class FrontmatterError(ValueError):
    """Raised when a markdown string has malformed frontmatter."""


_DELIM = "---"


def parse(raw: str) -> tuple[dict[str, Any], str]:
    """Parse a markdown string with optional YAML frontmatter.

    Returns (frontmatter_dict, body_str). Frontmatter is {} if absent.
    Raises FrontmatterError on malformed frontmatter.
    """
    if not raw.startswith(_DELIM + "\n") and raw != _DELIM:
        return {}, raw

    # Find closing delimiter on its own line.
    lines = raw.split("\n")
    closing_idx = -1
    for i in range(1, len(lines)):
        if lines[i] == _DELIM:
            closing_idx = i
            break
    if closing_idx == -1:
        raise FrontmatterError("unterminated frontmatter: missing closing '---'")

    fm_text = "\n".join(lines[1:closing_idx])
    try:
        fm = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError as e:
        raise FrontmatterError(f"invalid YAML in frontmatter: {e}") from e
    if not isinstance(fm, dict):
        raise FrontmatterError(f"frontmatter must be a YAML mapping, got {type(fm).__name__}")

    body = "\n".join(lines[closing_idx + 1 :])
    return fm, body


def dump(frontmatter: dict[str, Any], body: str) -> str:
    """Serialize frontmatter + body back into a markdown string.

    Empty frontmatter → body only (no delimiters).
    """
    if not frontmatter:
        return body
    fm_yaml = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).rstrip("\n")
    return f"{_DELIM}\n{fm_yaml}\n{_DELIM}\n{body}"
```

- [ ] **Step 4.4: Run tests; verify all pass**

```bash
cd plugins/wiki/server && uv run pytest tests/test_frontmatter.py -v
```
Expected: all 9 tests pass.

- [ ] **Step 4.5: Commit**

```bash
git add plugins/wiki/server/server/lib/frontmatter.py plugins/wiki/server/tests/test_frontmatter.py
git commit -m "feat(wiki/688): add frontmatter parser + tests"
```

---

### Task 5: `lib/config.py` — wiki.yaml loader

**Goal:** Load / save `~/.claude/wiki.yaml` via yaml.safe_load + dump, matching proj pattern.

**Files:**
- Create: `plugins/wiki/server/server/lib/config.py`
- Create: `plugins/wiki/server/tests/conftest.py` (shared fixtures — monkeypatch config path)
- Create: `plugins/wiki/server/tests/test_config.py`

- [ ] **Step 5.1: Write conftest.py w/ `wiki_cfg_path` fixture**

File: `plugins/wiki/server/tests/conftest.py`
```python
"""Shared pytest fixtures for wiki plugin."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def wiki_cfg_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Return a temp config path + redirect ~/.claude/wiki.yaml to it.

    Tests that load config will see the temp file instead of the user's real one.
    """
    cfg_path = tmp_path / "wiki.yaml"
    monkeypatch.setattr("server.lib.config._DEFAULT_CONFIG_PATH", cfg_path)
    return cfg_path


@pytest.fixture
def wiki_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Return a temp ~/.claude/wiki/ root + redirect config's wiki_dir there."""
    root = tmp_path / "wiki"
    root.mkdir()
    (root / "pages").mkdir()
    return root
```

- [ ] **Step 5.2: Write failing tests**

File: `plugins/wiki/server/tests/test_config.py`
```python
"""Tests for lib/config.py."""
from pathlib import Path

import pytest
import yaml

from server.lib.config import config_exists, config_path, load_config, save_config
from server.lib.models import WikiConfig


class TestLoadConfig:
    def test_load_default_when_missing(self, wiki_cfg_path: Path) -> None:
        cfg = load_config()
        assert cfg == WikiConfig()

    def test_load_existing(self, wiki_cfg_path: Path) -> None:
        wiki_cfg_path.write_text(yaml.safe_dump({
            "enabled": True,
            "wiki_dir": str(wiki_cfg_path.parent / "wiki"),
            "reingest_cooldown_hours": 48,
        }))
        cfg = load_config()
        assert cfg.enabled is True
        assert cfg.reingest_cooldown_hours == 48

    def test_load_malformed_yaml_returns_defaults(self, wiki_cfg_path: Path) -> None:
        wiki_cfg_path.write_text("enabled: : :")  # invalid YAML
        cfg = load_config()
        assert cfg == WikiConfig()

    def test_config_path_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Only when fixture isn't in play: config_path() → ~/.claude/wiki.yaml
        from server.lib import config as cfg_mod
        monkeypatch.setattr(cfg_mod, "_DEFAULT_CONFIG_PATH", Path.home() / ".claude" / "wiki.yaml")
        assert config_path() == Path.home() / ".claude" / "wiki.yaml"


class TestSaveConfig:
    def test_save_roundtrip(self, wiki_cfg_path: Path) -> None:
        cfg = WikiConfig(
            enabled=True,
            wiki_dir=wiki_cfg_path.parent / "w",
            reingest_cooldown_hours=6,
            bootstrap_pending=True,
            session_ingest_section_map={"K": "v"},
        )
        save_config(cfg)
        assert wiki_cfg_path.exists()
        reloaded = load_config()
        assert reloaded == cfg

    def test_save_creates_parent_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        deep = tmp_path / "a" / "b" / "wiki.yaml"
        monkeypatch.setattr("server.lib.config._DEFAULT_CONFIG_PATH", deep)
        save_config(WikiConfig(enabled=True))
        assert deep.exists()


class TestConfigExists:
    def test_false_when_missing(self, wiki_cfg_path: Path) -> None:
        assert config_exists() is False

    def test_true_when_present(self, wiki_cfg_path: Path) -> None:
        wiki_cfg_path.write_text("enabled: true\n")
        assert config_exists() is True
```

- [ ] **Step 5.3: Run tests; verify all fail**

```bash
cd plugins/wiki/server && uv run pytest tests/test_config.py -v
```
Expected: ImportError.

- [ ] **Step 5.4: Write config.py**

File: `plugins/wiki/server/server/lib/config.py`
```python
"""Wiki runtime config loader (~/.claude/wiki.yaml)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from server.lib.models import WikiConfig

_DEFAULT_CONFIG_PATH = Path.home() / ".claude" / "wiki.yaml"


def config_path() -> Path:
    return _DEFAULT_CONFIG_PATH


def config_exists() -> bool:
    return config_path().exists()


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        with path.open() as f:
            data = yaml.safe_load(f)
            return data if isinstance(data, dict) else {}
    except (FileNotFoundError, yaml.YAMLError):
        return {}


def load_config() -> WikiConfig:
    """Load wiki runtime config. Returns defaults if file missing or malformed."""
    data = _load_yaml(config_path())
    return WikiConfig.from_dict(data)


def save_config(cfg: WikiConfig) -> None:
    """Persist wiki runtime config. Creates parent dirs as needed."""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        yaml.safe_dump(cfg.to_dict(), f, sort_keys=False)
```

- [ ] **Step 5.5: Run tests; verify all pass**

```bash
cd plugins/wiki/server && uv run pytest tests/test_config.py -v
```
Expected: all 7 tests pass.

- [ ] **Step 5.6: Commit**

```bash
git add plugins/wiki/server/server/lib/config.py plugins/wiki/server/tests/conftest.py plugins/wiki/server/tests/test_config.py
git commit -m "feat(wiki/688): add wiki.yaml config loader + conftest fixtures"
```

---

### Task 6: `lib/profile.py` — category profile loader

**Goal:** Load category profile from `~/.claude/wiki/config.yaml`; ship 4 builtin profiles (`software`, `personal`, `research`, `minimal`); validate custom profiles.

**Files:**
- Create: `plugins/wiki/server/server/lib/profile.py`
- Create: `plugins/wiki/server/tests/test_profile.py`

- [ ] **Step 6.1: Write failing tests**

File: `plugins/wiki/server/tests/test_profile.py`
```python
"""Tests for lib/profile.py."""
from pathlib import Path

import pytest
import yaml

from server.lib.models import Profile
from server.lib.profile import (
    BUILTIN_PROFILES,
    ProfileError,
    get_builtin,
    load_profile,
    save_profile,
)


class TestBuiltinProfiles:
    def test_all_four_present(self) -> None:
        assert set(BUILTIN_PROFILES.keys()) == {"software", "personal", "research", "minimal"}

    def test_software_shape(self) -> None:
        p = get_builtin("software")
        assert p.name == "software"
        assert "decisions" in p.categories
        assert "concepts" in p.categories
        assert "references" in p.categories
        assert "pitfalls" in p.categories
        assert "entities" in p.categories
        assert len(p.categories) == 5

    def test_personal_shape(self) -> None:
        p = get_builtin("personal")
        assert "journal" in p.categories
        assert "topics" in p.categories
        assert "people" in p.categories
        assert "places" in p.categories
        assert "lessons" in p.categories

    def test_research_shape(self) -> None:
        p = get_builtin("research")
        assert set(p.categories) == {"concepts", "sources", "findings", "questions"}

    def test_minimal_is_empty(self) -> None:
        p = get_builtin("minimal")
        assert p.categories == []

    def test_unknown_raises(self) -> None:
        with pytest.raises(ProfileError, match="unknown builtin"):
            get_builtin("nonexistent")


class TestLoadProfile:
    def test_load_builtin_by_name(self, wiki_root: Path) -> None:
        (wiki_root / "config.yaml").write_text(yaml.safe_dump({
            "schema_version": 1,
            "profile": "software",
        }))
        p = load_profile(wiki_root)
        assert p.name == "software"
        assert "decisions" in p.categories

    def test_load_custom_categories_override(self, wiki_root: Path) -> None:
        (wiki_root / "config.yaml").write_text(yaml.safe_dump({
            "schema_version": 1,
            "profile": "custom",
            "categories": ["foo", "bar", "baz"],
        }))
        p = load_profile(wiki_root)
        assert p.name == "custom"
        assert p.categories == ["foo", "bar", "baz"]

    def test_load_builtin_with_category_override(self, wiki_root: Path) -> None:
        (wiki_root / "config.yaml").write_text(yaml.safe_dump({
            "schema_version": 1,
            "profile": "software",
            "categories": ["concepts", "decisions"],  # override
        }))
        p = load_profile(wiki_root)
        assert p.name == "software"
        assert p.categories == ["concepts", "decisions"]

    def test_missing_config_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ProfileError, match="config.yaml not found"):
            load_profile(tmp_path)

    def test_custom_without_categories_raises(self, wiki_root: Path) -> None:
        (wiki_root / "config.yaml").write_text(yaml.safe_dump({
            "schema_version": 1,
            "profile": "custom",
        }))
        with pytest.raises(ProfileError, match="custom profile requires categories"):
            load_profile(wiki_root)

    def test_unknown_builtin_raises(self, wiki_root: Path) -> None:
        (wiki_root / "config.yaml").write_text(yaml.safe_dump({
            "schema_version": 1,
            "profile": "not-a-real-profile",
        }))
        with pytest.raises(ProfileError, match="unknown"):
            load_profile(wiki_root)


class TestSaveProfile:
    def test_save_builtin(self, wiki_root: Path) -> None:
        p = get_builtin("software")
        save_profile(wiki_root, p)
        assert (wiki_root / "config.yaml").exists()
        data = yaml.safe_load((wiki_root / "config.yaml").read_text())
        assert data["profile"] == "software"

    def test_save_custom_writes_categories(self, wiki_root: Path) -> None:
        p = Profile(
            name="custom",
            categories=["a", "b"],
            session_section_map_default={},
        )
        save_profile(wiki_root, p)
        data = yaml.safe_load((wiki_root / "config.yaml").read_text())
        assert data["profile"] == "custom"
        assert data["categories"] == ["a", "b"]

    def test_save_roundtrip(self, wiki_root: Path) -> None:
        p = get_builtin("personal")
        save_profile(wiki_root, p)
        loaded = load_profile(wiki_root)
        assert loaded.name == p.name
        assert loaded.categories == p.categories
```

- [ ] **Step 6.2: Run tests; verify all fail**

```bash
cd plugins/wiki/server && uv run pytest tests/test_profile.py -v
```
Expected: ImportError.

- [ ] **Step 6.3: Write profile.py**

File: `plugins/wiki/server/server/lib/profile.py`
```python
"""Category profile loader. 4 builtin profiles + custom support."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from server.lib.models import Profile


class ProfileError(ValueError):
    """Raised for invalid or missing profile configuration."""


BUILTIN_PROFILES: dict[str, Profile] = {
    "software": Profile(
        name="software",
        categories=["concepts", "decisions", "references", "pitfalls", "entities"],
        session_section_map_default={
            "Key Decisions": "decisions",
            "Insights Discovered": "auto",
            "Related Todos": "links-only",
        },
    ),
    "personal": Profile(
        name="personal",
        categories=["journal", "topics", "people", "places", "lessons"],
        session_section_map_default={},
    ),
    "research": Profile(
        name="research",
        categories=["concepts", "sources", "findings", "questions"],
        session_section_map_default={},
    ),
    "minimal": Profile(
        name="minimal",
        categories=[],
        session_section_map_default={},
    ),
}


def get_builtin(name: str) -> Profile:
    if name not in BUILTIN_PROFILES:
        raise ProfileError(f"unknown builtin profile: {name!r}")
    return BUILTIN_PROFILES[name]


def load_profile(wiki_dir: Path) -> Profile:
    """Load active profile from wiki_dir/config.yaml.

    Supports builtin names (software/personal/research/minimal) + 'custom'.
    Builtin profiles may override `categories` via the config.
    """
    config_path = wiki_dir / "config.yaml"
    if not config_path.exists():
        raise ProfileError(f"config.yaml not found at {config_path}")

    try:
        with config_path.open() as f:
            data: dict[str, Any] = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise ProfileError(f"malformed config.yaml: {e}") from e

    profile_name = str(data.get("profile", "software"))
    categories_override = data.get("categories")

    if profile_name == "custom":
        if not categories_override:
            raise ProfileError("custom profile requires 'categories' list in config.yaml")
        return Profile(
            name="custom",
            categories=[str(c) for c in categories_override],
            session_section_map_default={},
        )

    if profile_name not in BUILTIN_PROFILES:
        raise ProfileError(f"unknown profile: {profile_name!r}")

    base = BUILTIN_PROFILES[profile_name]
    if categories_override is not None:
        return Profile(
            name=base.name,
            categories=[str(c) for c in categories_override],
            session_section_map_default=base.session_section_map_default,
        )
    return base


def save_profile(wiki_dir: Path, profile: Profile) -> None:
    """Persist the active profile choice to wiki_dir/config.yaml."""
    wiki_dir.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {
        "schema_version": 1,
        "profile": profile.name,
    }
    # For custom, always write categories. For builtins, write only if overridden.
    if profile.name == "custom":
        data["categories"] = list(profile.categories)
    else:
        base = BUILTIN_PROFILES[profile.name]
        if list(profile.categories) != list(base.categories):
            data["categories"] = list(profile.categories)

    with (wiki_dir / "config.yaml").open("w") as f:
        yaml.safe_dump(data, f, sort_keys=False)
```

- [ ] **Step 6.4: Run tests; verify all pass**

```bash
cd plugins/wiki/server && uv run pytest tests/test_profile.py -v
```
Expected: all 14 tests pass.

- [ ] **Step 6.5: Commit**

```bash
git add plugins/wiki/server/server/lib/profile.py plugins/wiki/server/tests/test_profile.py
git commit -m "feat(wiki/688): add profile loader with 4 builtins + custom support"
```

---

### Task 7: `lib/storage.py` — paths, atomic write, shared lock

**Goal:** Centralize filesystem operations. Atomic write via tmpfile+rename, shared lock via `threading.Lock` + `fcntl.flock` (matching proj's `todo_batch_complete` pattern).

**Files:**
- Create: `plugins/wiki/server/server/lib/storage.py`
- Create: `plugins/wiki/server/tests/test_storage.py`

- [ ] **Step 7.1: Write failing tests**

File: `plugins/wiki/server/tests/test_storage.py`
```python
"""Tests for lib/storage.py."""
import threading
from pathlib import Path

import pytest

from server.lib.storage import (
    atomic_write,
    page_path,
    pages_dir,
    wiki_lock,
    with_wiki_lock,
)


class TestPathHelpers:
    def test_pages_dir(self, wiki_root: Path) -> None:
        assert pages_dir(wiki_root) == wiki_root / "pages"

    def test_page_path_with_category(self, wiki_root: Path) -> None:
        assert page_path(wiki_root, "concepts", "hooks") == wiki_root / "pages" / "concepts" / "hooks.md"

    def test_page_path_without_category(self, wiki_root: Path) -> None:
        # minimal profile: pages/ is flat
        assert page_path(wiki_root, None, "hooks") == wiki_root / "pages" / "hooks.md"


class TestAtomicWrite:
    def test_creates_file(self, tmp_path: Path) -> None:
        target = tmp_path / "subdir" / "f.md"
        atomic_write(target, "content")
        assert target.read_text() == "content"

    def test_overwrites(self, tmp_path: Path) -> None:
        target = tmp_path / "f.md"
        target.write_text("old")
        atomic_write(target, "new")
        assert target.read_text() == "new"

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        target = tmp_path / "a" / "b" / "c.md"
        atomic_write(target, "x")
        assert target.exists()


class TestWikiLock:
    def test_lock_is_reentrant_within_thread(self, wiki_root: Path) -> None:
        # `with wiki_lock()` must allow recursive acquisition from the same thread
        with wiki_lock(wiki_root):
            with wiki_lock(wiki_root):  # should NOT deadlock
                (wiki_root / "x.md").write_text("ok")
        assert (wiki_root / "x.md").exists()

    def test_with_wiki_lock_decorator(self, wiki_root: Path) -> None:
        @with_wiki_lock
        def op(wiki_dir: Path, name: str) -> str:
            (wiki_dir / f"{name}.md").write_text(name)
            return name
        assert op(wiki_root, "foo") == "foo"
        assert (wiki_root / "foo.md").exists()

    def test_lock_blocks_other_thread(self, wiki_root: Path) -> None:
        import time
        order: list[str] = []

        def worker_a() -> None:
            with wiki_lock(wiki_root):
                order.append("A-enter")
                time.sleep(0.1)
                order.append("A-exit")

        def worker_b() -> None:
            time.sleep(0.02)  # start slightly after A
            with wiki_lock(wiki_root):
                order.append("B-enter")
                order.append("B-exit")

        t_a = threading.Thread(target=worker_a)
        t_b = threading.Thread(target=worker_b)
        t_a.start()
        t_b.start()
        t_a.join()
        t_b.join()
        assert order == ["A-enter", "A-exit", "B-enter", "B-exit"]
```

- [ ] **Step 7.2: Run tests; verify all fail**

```bash
cd plugins/wiki/server && uv run pytest tests/test_storage.py -v
```
Expected: ImportError.

- [ ] **Step 7.3: Write storage.py**

File: `plugins/wiki/server/server/lib/storage.py`
```python
"""Wiki filesystem helpers: path resolution, atomic writes, shared lock."""
from __future__ import annotations

import fcntl
import os
import tempfile
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import ParamSpec, TypeVar

_WIKI_LOCK = threading.RLock()  # re-entrant so same-thread nested wiki_lock() is fine
_LOCK_FILENAME = ".lock"


def pages_dir(wiki_dir: Path) -> Path:
    return wiki_dir / "pages"


def page_path(wiki_dir: Path, category: str | None, slug: str) -> Path:
    base = pages_dir(wiki_dir)
    if category:
        return base / category / f"{slug}.md"
    return base / f"{slug}.md"


def atomic_write(target: Path, content: str) -> None:
    """Write `content` to `target` atomically via tmpfile + os.replace.

    Creates parent dirs as needed.
    """
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


@contextmanager
def wiki_lock(wiki_dir: Path) -> Iterator[None]:
    """Acquire the shared wiki lock: thread-local RLock + fcntl.flock for cross-process.

    Yields once lock is held; releases on exit. Re-entrant within the same thread.
    """
    wiki_dir.mkdir(parents=True, exist_ok=True)
    lock_path = wiki_dir / _LOCK_FILENAME
    lock_path.touch(exist_ok=True)

    _WIKI_LOCK.acquire()
    fd = None
    try:
        fd = os.open(str(lock_path), os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        if fd is not None:
            os.close(fd)
        _WIKI_LOCK.release()


P = ParamSpec("P")
R = TypeVar("R")


def with_wiki_lock(fn: Callable[P, R]) -> Callable[P, R]:
    """Decorator: acquire wiki_lock before fn runs.

    Expects fn's first positional arg to be the wiki_dir Path.
    """
    @wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        wiki_dir = args[0] if args and isinstance(args[0], Path) else kwargs.get("wiki_dir")
        if not isinstance(wiki_dir, Path):
            raise TypeError("with_wiki_lock requires wiki_dir as first arg or kwarg")
        with wiki_lock(wiki_dir):
            return fn(*args, **kwargs)
    return wrapper
```

- [ ] **Step 7.4: Run tests; verify all pass**

```bash
cd plugins/wiki/server && uv run pytest tests/test_storage.py -v
```
Expected: all 8 tests pass.

- [ ] **Step 7.5: Commit**

```bash
git add plugins/wiki/server/server/lib/storage.py plugins/wiki/server/tests/test_storage.py
git commit -m "feat(wiki/688): add storage.py with atomic_write + wiki_lock"
```

---

### Task 8: `tools/page.py` — wiki_page_write

**Goal:** MCP tool to create / update / upsert a page with frontmatter validation.

**Files:**
- Create: `plugins/wiki/server/server/tools/__init__.py` (empty)
- Create: `plugins/wiki/server/server/tools/page.py`
- Create: `plugins/wiki/server/tests/test_page_write.py`

**Fixtures needed:** `mcp_app` fixture in conftest that wires a FastMCP server with `page.register(mcp)` called, using a temp wiki dir.

- [ ] **Step 8.1: Extend conftest.py with `mcp_app` + `wiki_cfg_setup` fixtures**

Edit `plugins/wiki/server/tests/conftest.py` — add at bottom:
```python
from typing import Any

from mcp.server.fastmcp import FastMCP

from server.lib import config as config_mod
from server.lib.models import WikiConfig
from server.lib.profile import get_builtin, save_profile


@pytest.fixture
def wiki_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Full wiki setup: config file + wiki dir + software profile."""
    cfg_path = tmp_path / "wiki.yaml"
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir()
    (wiki_dir / "pages").mkdir()

    monkeypatch.setattr(config_mod, "_DEFAULT_CONFIG_PATH", cfg_path)
    cfg = WikiConfig(enabled=True, wiki_dir=wiki_dir)
    config_mod.save_config(cfg)
    save_profile(wiki_dir, get_builtin("software"))
    return {"cfg_path": cfg_path, "wiki_dir": wiki_dir}


@pytest.fixture
def mcp_app(wiki_setup: dict[str, Path]) -> FastMCP:
    """FastMCP instance with all wiki tools registered."""
    from server.tools import page, index, log, links, scope  # noqa: F401  (imported for side effect in later tasks)

    mcp: FastMCP = FastMCP("wiki-test")
    page.register(mcp)
    # index/log/links/scope registered by their task
    return mcp


async def call_tool(app: FastMCP, tool_name: str, **kwargs: Any) -> str:
    """Invoke an MCP tool + return the text payload."""
    raw = await app.call_tool(tool_name, kwargs)
    items = raw[0] if isinstance(raw, tuple) else raw
    if items and hasattr(items[0], "text"):
        return items[0].text  # type: ignore[no-any-return]
    return ""
```

Note: `from server.tools import page, index, log, links, scope` in this fixture will fail until those modules exist. For Task 8 only `page` is needed — keep the imports minimal here and expand them as each tool module lands:

Edit the line to start w/ only `page`:
```python
from server.tools import page
```
Add `index`, `log`, `links`, `scope` in their respective tasks.

- [ ] **Step 8.2: Write failing tests for wiki_page_write**

File: `plugins/wiki/server/tests/test_page_write.py`
```python
"""Tests for wiki_page_write."""
import json
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from tests.conftest import call_tool


BASE_FRONTMATTER: dict = {
    "title": "Hooks architecture",
    "tags": ["hooks", "plugin"],
    "links_to": [],
    "scope": ["project:cpm"],
    "sources": [],
    "last_ingested": "2026-04-23T10:00:00Z",
}


@pytest.mark.asyncio
class TestWikiPageWrite:
    async def test_create_new_page(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        result = json.loads(await call_tool(
            mcp_app, "wiki_page_write",
            slug="hooks-architecture",
            category="concepts",
            frontmatter=BASE_FRONTMATTER,
            body="# Hooks\n\nContent.",
            mode="create",
        ))
        assert result["created"] is True
        assert result["updated"] is False
        path = wiki_setup["wiki_dir"] / "pages" / "concepts" / "hooks-architecture.md"
        assert path.exists()
        assert "title: Hooks architecture" in path.read_text()

    async def test_create_on_existing_returns_error(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        path = wiki_setup["wiki_dir"] / "pages" / "concepts" / "hooks.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("---\ntitle: X\n---\nold")

        result = json.loads(await call_tool(
            mcp_app, "wiki_page_write",
            slug="hooks", category="concepts",
            frontmatter=BASE_FRONTMATTER, body="new",
            mode="create",
        ))
        assert "error" in result
        assert "exists" in result["error"].lower()
        assert path.read_text().endswith("old")

    async def test_update_existing(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        path = wiki_setup["wiki_dir"] / "pages" / "concepts" / "hooks.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("---\ntitle: Old\n---\nold body")

        result = json.loads(await call_tool(
            mcp_app, "wiki_page_write",
            slug="hooks", category="concepts",
            frontmatter=BASE_FRONTMATTER, body="new body",
            mode="update",
        ))
        assert result["updated"] is True
        assert "new body" in path.read_text()

    async def test_update_missing_returns_error(self, mcp_app: FastMCP) -> None:
        result = json.loads(await call_tool(
            mcp_app, "wiki_page_write",
            slug="nope", category="concepts",
            frontmatter=BASE_FRONTMATTER, body="",
            mode="update",
        ))
        assert "error" in result
        assert "not_found" in result["error"] or "does not exist" in result["error"].lower()

    async def test_upsert_creates_then_updates(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        path = wiki_setup["wiki_dir"] / "pages" / "concepts" / "hooks.md"
        r1 = json.loads(await call_tool(
            mcp_app, "wiki_page_write",
            slug="hooks", category="concepts",
            frontmatter=BASE_FRONTMATTER, body="first",
            mode="upsert",
        ))
        assert r1["created"] is True

        r2 = json.loads(await call_tool(
            mcp_app, "wiki_page_write",
            slug="hooks", category="concepts",
            frontmatter={**BASE_FRONTMATTER, "title": "Updated"}, body="second",
            mode="upsert",
        ))
        assert r2["updated"] is True
        assert "second" in path.read_text()

    async def test_upsert_noop_on_identical_content(self, mcp_app: FastMCP) -> None:
        args = {
            "slug": "hooks", "category": "concepts",
            "frontmatter": BASE_FRONTMATTER, "body": "same",
            "mode": "upsert",
        }
        await call_tool(mcp_app, "wiki_page_write", **args)
        r2 = json.loads(await call_tool(mcp_app, "wiki_page_write", **args))
        # Identical payload → no-op
        assert r2.get("noop") is True

    async def test_missing_required_frontmatter_fails(self, mcp_app: FastMCP) -> None:
        incomplete: dict = {"title": "X"}  # missing tags, links_to, scope, sources, last_ingested
        result = json.loads(await call_tool(
            mcp_app, "wiki_page_write",
            slug="hooks", category="concepts",
            frontmatter=incomplete, body="",
            mode="create",
        ))
        assert "error" in result
        assert "missing" in result["error"].lower()

    async def test_category_not_in_profile_warns_but_writes(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        # software profile has 5 fixed categories; "random" is not one
        result = json.loads(await call_tool(
            mcp_app, "wiki_page_write",
            slug="odd", category="random",
            frontmatter=BASE_FRONTMATTER, body="x",
            mode="create",
        ))
        assert result["created"] is True
        assert result.get("warning")
        assert "category" in result["warning"].lower()
```

- [ ] **Step 8.3: Run tests; verify all fail**

```bash
cd plugins/wiki/server && uv run pytest tests/test_page_write.py -v
```
Expected: ImportError / tool-not-registered.

- [ ] **Step 8.4: Write tools/page.py (write only; get/list/delete later)**

File: `plugins/wiki/server/server/tools/__init__.py` — empty.

File: `plugins/wiki/server/server/tools/page.py`
```python
"""Wiki page CRUD tools."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from server.lib import config as config_mod
from server.lib import frontmatter as fm_mod
from server.lib import profile as profile_mod
from server.lib import storage

REQUIRED_FRONTMATTER_FIELDS = ("title", "tags", "links_to", "scope", "sources", "last_ingested")


def register(mcp: FastMCP) -> None:
    mcp.tool()(wiki_page_write)


def _validate_frontmatter(fm: dict[str, Any]) -> list[str]:
    return [field for field in REQUIRED_FRONTMATTER_FIELDS if field not in fm]


def _content_hash(frontmatter: dict[str, Any], body: str) -> str:
    h = hashlib.sha256()
    # Stable-sort keys for deterministic hash
    h.update(json.dumps(frontmatter, sort_keys=True).encode())
    h.update(body.encode())
    return h.hexdigest()


def wiki_page_write(
    slug: str,
    category: str | None,
    frontmatter: dict[str, Any],
    body: str,
    mode: str = "upsert",
) -> str:
    """Create, update, or upsert a wiki page.

    Args:
        slug: page slug (filename stem, lowercase-with-dashes).
        category: directory name under pages/. None = flat (minimal profile).
        frontmatter: dict with required keys: title, tags, links_to, scope, sources, last_ingested.
        body: markdown body text.
        mode: "create" | "update" | "upsert".

    Returns JSON string with {path, created, updated, noop, warning?} or {error}.
    """
    cfg = config_mod.load_config()
    if not cfg.enabled:
        return json.dumps({"error": "wiki disabled; run /wiki:init first"})

    wiki_dir: Path = cfg.wiki_dir
    missing = _validate_frontmatter(frontmatter)
    if missing:
        return json.dumps({"error": f"missing required frontmatter fields: {missing}"})

    warning: str | None = None
    try:
        profile = profile_mod.load_profile(wiki_dir)
    except profile_mod.ProfileError as e:
        return json.dumps({"error": f"profile load failed: {e}"})

    if profile.categories and category and category not in profile.categories:
        warning = f"category {category!r} not in active profile ({profile.name}): {profile.categories}"

    target = storage.page_path(wiki_dir, category, slug)
    exists = target.exists()

    if mode == "create" and exists:
        return json.dumps({"error": f"page exists at {target}"})
    if mode == "update" and not exists:
        return json.dumps({"error": f"not_found: {target} does not exist"})
    if mode not in {"create", "update", "upsert"}:
        return json.dumps({"error": f"invalid mode: {mode!r}"})

    new_content = fm_mod.dump(frontmatter, body)

    # Idempotency: on upsert with identical existing content → no-op.
    if mode == "upsert" and exists:
        existing_raw = target.read_text()
        existing_fm, existing_body = fm_mod.parse(existing_raw)
        if _content_hash(existing_fm, existing_body) == _content_hash(frontmatter, body):
            return json.dumps({
                "path": str(target),
                "created": False,
                "updated": False,
                "noop": True,
                "warning": warning,
            })

    with storage.wiki_lock(wiki_dir):
        storage.atomic_write(target, new_content)

    return json.dumps({
        "path": str(target),
        "created": not exists,
        "updated": exists,
        "noop": False,
        "warning": warning,
    })
```

- [ ] **Step 8.5: Run tests; verify all pass**

```bash
cd plugins/wiki/server && uv run pytest tests/test_page_write.py -v
```
Expected: all 8 tests pass.

- [ ] **Step 8.6: Commit**

```bash
git add plugins/wiki/server/server/tools/ plugins/wiki/server/tests/test_page_write.py plugins/wiki/server/tests/conftest.py
git commit -m "feat(wiki/688): add wiki_page_write MCP tool"
```

---

### Task 9: `tools/page.py` — wiki_page_get

**Files:**
- Modify: `plugins/wiki/server/server/tools/page.py` — add `wiki_page_get`
- Create: `plugins/wiki/server/tests/test_page_get.py`

- [ ] **Step 9.1: Write failing tests**

File: `plugins/wiki/server/tests/test_page_get.py`
```python
"""Tests for wiki_page_get."""
import json
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from tests.conftest import call_tool


@pytest.mark.asyncio
class TestWikiPageGet:
    async def test_get_existing(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        page = wiki_setup["wiki_dir"] / "pages" / "concepts" / "hooks.md"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(
            "---\ntitle: Hooks\ntags: [a]\nlinks_to: []\nscope: [global]\n"
            "sources: []\nlast_ingested: '2026-04-23'\n---\nBody text."
        )
        result = json.loads(await call_tool(
            mcp_app, "wiki_page_get", slug="hooks", category="concepts"
        ))
        assert result["frontmatter"]["title"] == "Hooks"
        assert result["body"] == "Body text."
        assert result["path"].endswith("hooks.md")

    async def test_get_missing_returns_error(self, mcp_app: FastMCP) -> None:
        result = json.loads(await call_tool(
            mcp_app, "wiki_page_get", slug="nope", category="concepts"
        ))
        assert result["error"] == "not_found"

    async def test_get_without_category_flat_layout(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        page = wiki_setup["wiki_dir"] / "pages" / "flat.md"
        page.write_text("---\ntitle: Flat\ntags: []\nlinks_to: []\nscope: []\nsources: []\nlast_ingested: '2026-04-23'\n---\nflat body")
        result = json.loads(await call_tool(
            mcp_app, "wiki_page_get", slug="flat", category=None
        ))
        assert result["frontmatter"]["title"] == "Flat"

    async def test_malformed_frontmatter_returns_error(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        page = wiki_setup["wiki_dir"] / "pages" / "concepts" / "broken.md"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text("---\ntitle: : :\n---\nbody")
        result = json.loads(await call_tool(
            mcp_app, "wiki_page_get", slug="broken", category="concepts"
        ))
        assert "error" in result
        assert "frontmatter" in result["error"].lower()
```

- [ ] **Step 9.2: Run tests; verify all fail**

```bash
cd plugins/wiki/server && uv run pytest tests/test_page_get.py -v
```
Expected: tool not registered.

- [ ] **Step 9.3: Add wiki_page_get to tools/page.py**

Add inside `plugins/wiki/server/server/tools/page.py` (after `wiki_page_write`):

```python
def wiki_page_get(slug: str, category: str | None) -> str:
    """Read a single wiki page.

    Returns JSON {frontmatter, body, path} or {error: "not_found" | ...}.
    """
    cfg = config_mod.load_config()
    target = storage.page_path(cfg.wiki_dir, category, slug)
    if not target.exists():
        return json.dumps({"error": "not_found", "path": str(target)})
    try:
        fm, body = fm_mod.parse(target.read_text())
    except fm_mod.FrontmatterError as e:
        return json.dumps({"error": f"malformed frontmatter: {e}", "path": str(target)})
    return json.dumps({"frontmatter": fm, "body": body, "path": str(target)})
```

Then modify `register()` to add the new tool:
```python
def register(mcp: FastMCP) -> None:
    mcp.tool()(wiki_page_write)
    mcp.tool()(wiki_page_get)
```

- [ ] **Step 9.4: Run tests; verify all pass**

```bash
cd plugins/wiki/server && uv run pytest tests/test_page_get.py -v
```
Expected: all 4 tests pass.

- [ ] **Step 9.5: Commit**

```bash
git add plugins/wiki/server/server/tools/page.py plugins/wiki/server/tests/test_page_get.py
git commit -m "feat(wiki/688): add wiki_page_get MCP tool"
```

---

### Task 10: `tools/page.py` — wiki_page_list

**Goal:** List pages with filters (scope, category, tags, linked_from, linked_to, limit).

**Files:**
- Modify: `plugins/wiki/server/server/tools/page.py` — add `wiki_page_list`
- Create: `plugins/wiki/server/tests/test_page_list.py`

- [ ] **Step 10.1: Write failing tests**

File: `plugins/wiki/server/tests/test_page_list.py`
```python
"""Tests for wiki_page_list."""
import json
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from tests.conftest import call_tool


def _write_page(wiki_dir: Path, category: str | None, slug: str, **fm_overrides) -> None:
    base = {
        "title": slug.replace("-", " ").title(),
        "tags": [],
        "links_to": [],
        "scope": ["global"],
        "sources": [],
        "last_ingested": "2026-04-23T10:00:00Z",
    }
    base.update(fm_overrides)
    fm_lines = "\n".join(f"{k}: {json.dumps(v)}" for k, v in base.items())
    path = wiki_dir / "pages"
    if category:
        path = path / category
    path.mkdir(parents=True, exist_ok=True)
    (path / f"{slug}.md").write_text(f"---\n{fm_lines}\n---\nbody")


@pytest.mark.asyncio
class TestWikiPageList:
    async def test_list_empty(self, mcp_app: FastMCP) -> None:
        result = json.loads(await call_tool(mcp_app, "wiki_page_list"))
        assert result["pages"] == []

    async def test_list_all(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "a", tags=["x"])
        _write_page(wiki_setup["wiki_dir"], "decisions", "b", tags=["y"])
        result = json.loads(await call_tool(mcp_app, "wiki_page_list"))
        slugs = sorted(p["slug"] for p in result["pages"])
        assert slugs == ["a", "b"]

    async def test_filter_by_category(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "a")
        _write_page(wiki_setup["wiki_dir"], "decisions", "b")
        result = json.loads(await call_tool(mcp_app, "wiki_page_list", category="concepts"))
        assert len(result["pages"]) == 1
        assert result["pages"][0]["slug"] == "a"

    async def test_filter_by_tags(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "a", tags=["hooks"])
        _write_page(wiki_setup["wiki_dir"], "concepts", "b", tags=["other"])
        result = json.loads(await call_tool(mcp_app, "wiki_page_list", tags=["hooks"]))
        assert [p["slug"] for p in result["pages"]] == ["a"]

    async def test_filter_by_scope(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "a", scope=["project:cpm"])
        _write_page(wiki_setup["wiki_dir"], "concepts", "b", scope=["global"])
        result = json.loads(await call_tool(mcp_app, "wiki_page_list", scope_filter="project:cpm"))
        assert [p["slug"] for p in result["pages"]] == ["a"]

    async def test_filter_by_linked_to(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "a", links_to=["router"])
        _write_page(wiki_setup["wiki_dir"], "concepts", "b", links_to=[])
        result = json.loads(await call_tool(mcp_app, "wiki_page_list", linked_to="router"))
        assert [p["slug"] for p in result["pages"]] == ["a"]

    async def test_filter_by_linked_from(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "a", links_to=["b"])
        _write_page(wiki_setup["wiki_dir"], "concepts", "b", links_to=[])
        # "linked_from=a" → pages that a points at → ["b"]
        result = json.loads(await call_tool(mcp_app, "wiki_page_list", linked_from="a"))
        assert [p["slug"] for p in result["pages"]] == ["b"]

    async def test_limit(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        for i in range(5):
            _write_page(wiki_setup["wiki_dir"], "concepts", f"p{i}")
        result = json.loads(await call_tool(mcp_app, "wiki_page_list", limit=2))
        assert len(result["pages"]) == 2
        assert result["truncated"] is True
```

- [ ] **Step 10.2: Run tests; verify fail**

```bash
cd plugins/wiki/server && uv run pytest tests/test_page_list.py -v
```
Expected: tool not registered.

- [ ] **Step 10.3: Add wiki_page_list to tools/page.py**

Add inside `plugins/wiki/server/server/tools/page.py`:

```python
def wiki_page_list(
    scope_filter: str | None = None,
    category: str | None = None,
    tags: list[str] | None = None,
    linked_from: str | None = None,
    linked_to: str | None = None,
    limit: int = 0,
) -> str:
    """List pages with optional filters.

    Filters:
        scope_filter: match pages whose scope[] contains this value.
        category: match pages under pages/<category>/.
        tags: match pages whose tags[] is a superset of this list.
        linked_from: match pages pointed at by this slug (i.e. slug's links_to).
        linked_to: match pages whose links_to contains this slug.
        limit: 0 = unlimited. Truncation flag in response.
    """
    cfg = config_mod.load_config()
    pages_root = storage.pages_dir(cfg.wiki_dir)
    if not pages_root.exists():
        return json.dumps({"pages": [], "truncated": False})

    tag_set = set(tags or [])

    # Build linked_from map: slug → links_to from that page (for linked_from filter)
    linked_from_targets: set[str] = set()
    if linked_from:
        source_path = None
        for md in pages_root.rglob("*.md"):
            if md.stem == linked_from:
                source_path = md
                break
        if source_path:
            fm, _ = fm_mod.parse(source_path.read_text())
            linked_from_targets = set(fm.get("links_to", []) or [])

    results: list[dict[str, Any]] = []
    for md in sorted(pages_root.rglob("*.md")):
        rel = md.relative_to(pages_root)
        cat = rel.parts[0] if len(rel.parts) > 1 else None
        if category and cat != category:
            continue
        try:
            fm, _ = fm_mod.parse(md.read_text())
        except fm_mod.FrontmatterError:
            continue  # skip malformed pages
        page_scope = fm.get("scope", []) or []
        if scope_filter and scope_filter not in page_scope:
            continue
        page_tags = set(fm.get("tags", []) or [])
        if tag_set and not tag_set.issubset(page_tags):
            continue
        if linked_to and linked_to not in (fm.get("links_to", []) or []):
            continue
        if linked_from and md.stem not in linked_from_targets:
            continue
        results.append({
            "title": fm.get("title", ""),
            "slug": md.stem,
            "category": cat,
            "scope": page_scope,
            "tags": list(page_tags),
            "last_ingested": fm.get("last_ingested", ""),
        })

    truncated = False
    if limit > 0 and len(results) > limit:
        results = results[:limit]
        truncated = True

    return json.dumps({"pages": results, "truncated": truncated})
```

Update `register()`:
```python
def register(mcp: FastMCP) -> None:
    mcp.tool()(wiki_page_write)
    mcp.tool()(wiki_page_get)
    mcp.tool()(wiki_page_list)
```

- [ ] **Step 10.4: Run tests; verify all pass**

```bash
cd plugins/wiki/server && uv run pytest tests/test_page_list.py -v
```
Expected: all 8 tests pass.

- [ ] **Step 10.5: Commit**

```bash
git add plugins/wiki/server/server/tools/page.py plugins/wiki/server/tests/test_page_list.py
git commit -m "feat(wiki/688): add wiki_page_list with scope/category/tags/linked filters"
```

---

### Task 11: `tools/page.py` — wiki_page_delete

**Goal:** Delete a page + update backlinks on other pages that reference it.

**Files:**
- Modify: `plugins/wiki/server/server/tools/page.py` — add `wiki_page_delete`
- Create: `plugins/wiki/server/tests/test_page_delete.py`

- [ ] **Step 11.1: Write failing tests**

File: `plugins/wiki/server/tests/test_page_delete.py`
```python
"""Tests for wiki_page_delete."""
import json
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from tests.conftest import call_tool
from tests.test_page_list import _write_page


@pytest.mark.asyncio
class TestWikiPageDelete:
    async def test_delete_existing(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "target")
        path = wiki_setup["wiki_dir"] / "pages" / "concepts" / "target.md"
        assert path.exists()

        result = json.loads(await call_tool(
            mcp_app, "wiki_page_delete", slug="target", category="concepts"
        ))
        assert result["deleted"] is True
        assert not path.exists()

    async def test_delete_missing_returns_error(self, mcp_app: FastMCP) -> None:
        result = json.loads(await call_tool(
            mcp_app, "wiki_page_delete", slug="nope", category="concepts"
        ))
        assert "error" in result
        assert "not_found" in result["error"]

    async def test_delete_updates_backlinks(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "target")
        _write_page(wiki_setup["wiki_dir"], "concepts", "referrer", links_to=["target"])

        result = json.loads(await call_tool(
            mcp_app, "wiki_page_delete", slug="target", category="concepts"
        ))
        assert result["deleted"] is True
        assert "referrer" in result["backlinks_updated"]

        referrer_path = wiki_setup["wiki_dir"] / "pages" / "concepts" / "referrer.md"
        import yaml
        raw = referrer_path.read_text()
        fm_text = raw.split("---")[1]
        fm = yaml.safe_load(fm_text)
        assert "target" not in fm.get("links_to", [])

    async def test_delete_no_backlinks_reports_empty(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "lonely")
        result = json.loads(await call_tool(
            mcp_app, "wiki_page_delete", slug="lonely", category="concepts"
        ))
        assert result["deleted"] is True
        assert result["backlinks_updated"] == []
```

- [ ] **Step 11.2: Run tests; verify fail**

```bash
cd plugins/wiki/server && uv run pytest tests/test_page_delete.py -v
```

- [ ] **Step 11.3: Add wiki_page_delete**

Add inside `plugins/wiki/server/server/tools/page.py`:

```python
def wiki_page_delete(slug: str, category: str | None) -> str:
    """Delete a page and prune references to it from other pages' links_to frontmatter.

    Returns JSON {deleted: bool, backlinks_updated: [slug, ...]} or {error}.
    """
    cfg = config_mod.load_config()
    wiki_dir = cfg.wiki_dir
    target = storage.page_path(wiki_dir, category, slug)
    if not target.exists():
        return json.dumps({"error": "not_found", "path": str(target)})

    updated_backlinks: list[str] = []
    with storage.wiki_lock(wiki_dir):
        # Find + update backlinks first, THEN delete the target
        pages_root = storage.pages_dir(wiki_dir)
        for md in pages_root.rglob("*.md"):
            if md == target:
                continue
            try:
                fm, body = fm_mod.parse(md.read_text())
            except fm_mod.FrontmatterError:
                continue
            links = fm.get("links_to", []) or []
            if slug in links:
                new_links = [l for l in links if l != slug]
                fm["links_to"] = new_links
                storage.atomic_write(md, fm_mod.dump(fm, body))
                updated_backlinks.append(md.stem)
        target.unlink()
    return json.dumps({
        "deleted": True,
        "backlinks_updated": updated_backlinks,
        "path": str(target),
    })
```

Update `register()`:
```python
def register(mcp: FastMCP) -> None:
    mcp.tool()(wiki_page_write)
    mcp.tool()(wiki_page_get)
    mcp.tool()(wiki_page_list)
    mcp.tool()(wiki_page_delete)
```

- [ ] **Step 11.4: Run tests; verify all pass**

```bash
cd plugins/wiki/server && uv run pytest tests/test_page_delete.py -v
```
Expected: all 4 tests pass.

- [ ] **Step 11.5: Commit**

```bash
git add plugins/wiki/server/server/tools/page.py plugins/wiki/server/tests/test_page_delete.py
git commit -m "feat(wiki/688): add wiki_page_delete with backlink pruning"
```

---

### Task 12: `tools/log.py` — wiki_log_append + wiki_log_read

**Goal:** Append-only log with Karpathy-format prefix `## [YYYY-MM-DD] action | title`. Grep-parseable.

**Files:**
- Create: `plugins/wiki/server/server/tools/log.py`
- Create: `plugins/wiki/server/tests/test_log.py`

- [ ] **Step 12.1: Add log to conftest mcp_app**

Edit `plugins/wiki/server/tests/conftest.py` — update the `from server.tools import` line:
```python
from server.tools import log, page
```

And update `mcp_app`:
```python
@pytest.fixture
def mcp_app(wiki_setup: dict[str, Path]) -> FastMCP:
    from server.tools import log, page
    mcp: FastMCP = FastMCP("wiki-test")
    page.register(mcp)
    log.register(mcp)
    return mcp
```

- [ ] **Step 12.2: Write failing tests**

File: `plugins/wiki/server/tests/test_log.py`
```python
"""Tests for wiki_log_append + wiki_log_read."""
import json
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from tests.conftest import call_tool


@pytest.mark.asyncio
class TestWikiLogAppend:
    async def test_append_creates_log_md(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        result = json.loads(await call_tool(
            mcp_app, "wiki_log_append",
            action="ingest", title="file:/tmp/x.md", body="2 pages updated"
        ))
        assert "entry" in result
        log_md = wiki_setup["wiki_dir"] / "log.md"
        assert log_md.exists()
        content = log_md.read_text()
        assert "## [" in content
        assert "ingest" in content
        assert "file:/tmp/x.md" in content
        assert "2 pages updated" in content

    async def test_entry_format_karpathy_prefix(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        await call_tool(
            mcp_app, "wiki_log_append", action="lint", title="full", body=""
        )
        content = (wiki_setup["wiki_dir"] / "log.md").read_text()
        # Must match: ## [YYYY-MM-DD] <action> | <title>
        import re
        assert re.search(r"^## \[\d{4}-\d{2}-\d{2}\] lint \| full$", content, re.MULTILINE)

    async def test_append_preserves_prior_entries(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        await call_tool(mcp_app, "wiki_log_append", action="ingest", title="first")
        await call_tool(mcp_app, "wiki_log_append", action="lint", title="second")
        content = (wiki_setup["wiki_dir"] / "log.md").read_text()
        assert content.index("first") < content.index("second")

    async def test_body_optional(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        result = json.loads(await call_tool(
            mcp_app, "wiki_log_append", action="note", title="observation"
        ))
        assert "error" not in result


@pytest.mark.asyncio
class TestWikiLogRead:
    async def test_read_empty(self, mcp_app: FastMCP) -> None:
        result = json.loads(await call_tool(mcp_app, "wiki_log_read"))
        assert result["entries"] == []

    async def test_read_returns_parsed_entries(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        await call_tool(mcp_app, "wiki_log_append", action="ingest", title="t1", body="b1")
        await call_tool(mcp_app, "wiki_log_append", action="lint", title="t2")
        result = json.loads(await call_tool(mcp_app, "wiki_log_read"))
        entries = result["entries"]
        assert len(entries) == 2
        assert entries[0]["action"] == "ingest"
        assert entries[0]["title"] == "t1"
        assert entries[0]["body"] == "b1"
        assert entries[1]["action"] == "lint"

    async def test_read_action_filter(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        await call_tool(mcp_app, "wiki_log_append", action="ingest", title="a")
        await call_tool(mcp_app, "wiki_log_append", action="lint", title="b")
        result = json.loads(await call_tool(mcp_app, "wiki_log_read", action_filter="ingest"))
        assert len(result["entries"]) == 1
        assert result["entries"][0]["action"] == "ingest"

    async def test_read_limit(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        for i in range(5):
            await call_tool(mcp_app, "wiki_log_append", action="note", title=f"n{i}")
        result = json.loads(await call_tool(mcp_app, "wiki_log_read", limit=2))
        # Limit returns most-recent N
        assert len(result["entries"]) == 2
        assert result["entries"][-1]["title"] == "n4"

    async def test_read_since_date(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        # Seed log with an older entry
        log_md = wiki_setup["wiki_dir"] / "log.md"
        log_md.write_text("## [2024-01-01] ingest | old\nold body\n\n")
        await call_tool(mcp_app, "wiki_log_append", action="ingest", title="new")
        result = json.loads(await call_tool(mcp_app, "wiki_log_read", since="2026-01-01"))
        titles = [e["title"] for e in result["entries"]]
        assert "new" in titles
        assert "old" not in titles
```

- [ ] **Step 12.3: Run tests; verify fail**

- [ ] **Step 12.4: Write log.py**

File: `plugins/wiki/server/server/tools/log.py`
```python
"""Wiki append-only log (log.md) tools."""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from mcp.server.fastmcp import FastMCP

from server.lib import config as config_mod
from server.lib import storage

LOG_FILENAME = "log.md"
_ENTRY_RE = re.compile(r"^## \[(\d{4}-\d{2}-\d{2})\] (\S+) \| (.+)$", re.MULTILINE)


def register(mcp: FastMCP) -> None:
    mcp.tool()(wiki_log_append)
    mcp.tool()(wiki_log_read)


def wiki_log_append(action: str, title: str, body: str = "") -> str:
    """Append an entry to log.md.

    Format: `## [YYYY-MM-DD] <action> | <title>` followed by optional body + blank line.
    """
    cfg = config_mod.load_config()
    wiki_dir = cfg.wiki_dir
    log_path = wiki_dir / LOG_FILENAME
    today = date.today().isoformat()
    header = f"## [{today}] {action} | {title}\n"
    entry = header + (body + "\n" if body else "") + "\n"

    with storage.wiki_lock(wiki_dir):
        wiki_dir.mkdir(parents=True, exist_ok=True)
        existing = log_path.read_text() if log_path.exists() else ""
        storage.atomic_write(log_path, existing + entry)

    return json.dumps({"entry": entry.strip(), "path": str(log_path)})


def wiki_log_read(
    since: str | None = None,
    action_filter: str | None = None,
    limit: int = 0,
) -> str:
    """Read log entries, optionally filtered.

    Args:
        since: ISO date string (YYYY-MM-DD); include entries with date >= since.
        action_filter: include only entries with matching action.
        limit: 0 = unlimited; otherwise return most-recent N matching.
    """
    cfg = config_mod.load_config()
    log_path = cfg.wiki_dir / LOG_FILENAME
    if not log_path.exists():
        return json.dumps({"entries": []})

    content = log_path.read_text()
    entries: list[dict[str, Any]] = []

    # Find each entry header; body is text between this header and next (or EOF).
    matches = list(_ENTRY_RE.finditer(content))
    for i, m in enumerate(matches):
        entry_date, action, title = m.group(1), m.group(2), m.group(3)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        body = content[start:end].strip()
        if since and entry_date < since:
            continue
        if action_filter and action != action_filter:
            continue
        entries.append({"date": entry_date, "action": action, "title": title, "body": body})

    if limit > 0 and len(entries) > limit:
        entries = entries[-limit:]

    return json.dumps({"entries": entries})
```

- [ ] **Step 12.5: Run tests; verify all pass**

```bash
cd plugins/wiki/server && uv run pytest tests/test_log.py -v
```
Expected: all 9 tests pass.

- [ ] **Step 12.6: Commit**

```bash
git add plugins/wiki/server/server/tools/log.py plugins/wiki/server/tests/test_log.py plugins/wiki/server/tests/conftest.py
git commit -m "feat(wiki/688): add wiki_log_append + wiki_log_read"
```

---

### Task 13: `tools/index.py` — wiki_index_read + wiki_index_rebuild

**Goal:** Read + regenerate `index.md` from `pages/**`. Groups by configured profile categories.

**Files:**
- Create: `plugins/wiki/server/server/tools/index.py`
- Create: `plugins/wiki/server/tests/test_index.py`

- [ ] **Step 13.1: Add index to conftest**

Edit `mcp_app` fixture:
```python
@pytest.fixture
def mcp_app(wiki_setup: dict[str, Path]) -> FastMCP:
    from server.tools import index, log, page
    mcp: FastMCP = FastMCP("wiki-test")
    page.register(mcp)
    log.register(mcp)
    index.register(mcp)
    return mcp
```

- [ ] **Step 13.2: Write failing tests**

File: `plugins/wiki/server/tests/test_index.py`
```python
"""Tests for wiki_index_read + wiki_index_rebuild."""
import json
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from tests.conftest import call_tool
from tests.test_page_list import _write_page


@pytest.mark.asyncio
class TestWikiIndexRebuild:
    async def test_rebuild_empty(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        result = json.loads(await call_tool(mcp_app, "wiki_index_rebuild"))
        assert result["entries_by_category"] == {}
        index_md = wiki_setup["wiki_dir"] / "index.md"
        assert index_md.exists()
        assert "# Wiki Index" in index_md.read_text()

    async def test_rebuild_groups_by_category(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "hooks", tags=["hooks"])
        _write_page(wiki_setup["wiki_dir"], "decisions", "fastmcp", tags=["mcp"])
        _write_page(wiki_setup["wiki_dir"], "references", "api")
        result = json.loads(await call_tool(mcp_app, "wiki_index_rebuild"))
        assert result["entries_by_category"]["concepts"] == 1
        assert result["entries_by_category"]["decisions"] == 1
        assert result["entries_by_category"]["references"] == 1
        content = (wiki_setup["wiki_dir"] / "index.md").read_text()
        assert "## Concepts" in content
        assert "[[hooks]]" in content

    async def test_rebuild_includes_recent(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "newest", last_ingested="2026-04-23T12:00:00Z")
        _write_page(wiki_setup["wiki_dir"], "concepts", "older", last_ingested="2024-01-01T00:00:00Z")
        await call_tool(mcp_app, "wiki_index_rebuild")
        content = (wiki_setup["wiki_dir"] / "index.md").read_text()
        assert "## Recent" in content
        # Newest first
        recent_section = content.split("## Recent")[1]
        assert recent_section.index("newest") < recent_section.index("older")

    async def test_rebuild_is_idempotent(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "hooks")
        await call_tool(mcp_app, "wiki_index_rebuild")
        first = (wiki_setup["wiki_dir"] / "index.md").read_text()
        await call_tool(mcp_app, "wiki_index_rebuild")
        second = (wiki_setup["wiki_dir"] / "index.md").read_text()
        assert first == second


@pytest.mark.asyncio
class TestWikiIndexRead:
    async def test_read_when_missing(self, mcp_app: FastMCP) -> None:
        result = json.loads(await call_tool(mcp_app, "wiki_index_read"))
        assert result["content"] == ""
        assert result["categories"] == {}
        assert result["recent"] == []

    async def test_read_after_rebuild(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "hooks")
        await call_tool(mcp_app, "wiki_index_rebuild")
        result = json.loads(await call_tool(mcp_app, "wiki_index_read"))
        assert "Wiki Index" in result["content"]
        assert result["categories"].get("concepts") == 1
```

- [ ] **Step 13.3: Run tests; verify fail**

- [ ] **Step 13.4: Write index.py**

File: `plugins/wiki/server/server/tools/index.py`
```python
"""Wiki index.md tools: read + rebuild."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from server.lib import config as config_mod
from server.lib import frontmatter as fm_mod
from server.lib import profile as profile_mod
from server.lib import storage

INDEX_FILENAME = "index.md"
RECENT_LIMIT = 10

_CATEGORY_HEADER_RE = re.compile(r"^## (\S.+?) \((\d+)\)$", re.MULTILINE)


def register(mcp: FastMCP) -> None:
    mcp.tool()(wiki_index_read)
    mcp.tool()(wiki_index_rebuild)


def _first_summary_line(body: str) -> str:
    """Extract a one-line summary from a page body (first non-empty line after any title)."""
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue  # skip heading lines
        # Truncate to a reasonable length
        return stripped[:200]
    return ""


def wiki_index_rebuild() -> str:
    """Regenerate index.md by scanning pages/**. Groups by active profile categories."""
    cfg = config_mod.load_config()
    wiki_dir = cfg.wiki_dir
    try:
        profile = profile_mod.load_profile(wiki_dir)
    except profile_mod.ProfileError:
        profile = None

    pages_root = storage.pages_dir(wiki_dir)
    if not pages_root.exists():
        pages_root.mkdir(parents=True, exist_ok=True)

    by_category: dict[str, list[dict[str, Any]]] = {}
    all_pages: list[dict[str, Any]] = []
    for md in sorted(pages_root.rglob("*.md")):
        rel = md.relative_to(pages_root)
        cat = rel.parts[0] if len(rel.parts) > 1 else "uncategorized"
        try:
            fm, body = fm_mod.parse(md.read_text())
        except fm_mod.FrontmatterError:
            continue
        entry = {
            "slug": md.stem,
            "title": fm.get("title", md.stem),
            "summary": _first_summary_line(body),
            "last_ingested": fm.get("last_ingested", ""),
        }
        by_category.setdefault(cat, []).append(entry)
        all_pages.append(entry)

    recent_sorted = sorted(
        all_pages, key=lambda e: str(e["last_ingested"]), reverse=True
    )[:RECENT_LIMIT]

    # Order categories by profile; unknown categories appended at end alphabetically
    category_order: list[str] = []
    if profile and profile.categories:
        category_order = [c for c in profile.categories if c in by_category]
        extras = sorted(set(by_category.keys()) - set(profile.categories))
        category_order.extend(extras)
    else:
        category_order = sorted(by_category.keys())

    lines: list[str] = ["# Wiki Index", ""]
    for cat in category_order:
        entries = by_category[cat]
        lines.append(f"## {cat.title()} ({len(entries)})")
        for e in sorted(entries, key=lambda x: str(x["title"])):
            summary = f" — {e['summary']}" if e["summary"] else ""
            lines.append(f"- [[{e['slug']}]]{summary}")
        lines.append("")

    if recent_sorted:
        lines.append(f"## Recent (by last_ingested, top {RECENT_LIMIT})")
        for e in recent_sorted:
            date_part = str(e["last_ingested"]).split("T")[0]
            lines.append(f"- [[{e['slug']}]] ({date_part})")
        lines.append("")

    with storage.wiki_lock(wiki_dir):
        storage.atomic_write(wiki_dir / INDEX_FILENAME, "\n".join(lines))

    return json.dumps({
        "entries_by_category": {c: len(v) for c, v in by_category.items()},
        "recent_count": len(recent_sorted),
    })


def wiki_index_read() -> str:
    """Read index.md + return content + parsed category counts + recent list."""
    cfg = config_mod.load_config()
    index_path: Path = cfg.wiki_dir / INDEX_FILENAME
    if not index_path.exists():
        return json.dumps({"content": "", "categories": {}, "recent": []})

    content = index_path.read_text()
    categories: dict[str, int] = {}
    for m in _CATEGORY_HEADER_RE.finditer(content):
        name = m.group(1).strip().lower()
        if name.startswith("recent"):
            continue
        categories[name] = int(m.group(2))

    # Parse "## Recent ..." section for slug list
    recent: list[str] = []
    if "## Recent" in content:
        section = content.split("## Recent", 1)[1]
        for line in section.splitlines():
            m = re.match(r"- \[\[(.+?)\]\]", line.strip())
            if m:
                recent.append(m.group(1))

    return json.dumps({"content": content, "categories": categories, "recent": recent})
```

- [ ] **Step 13.5: Run tests; verify all pass**

```bash
cd plugins/wiki/server && uv run pytest tests/test_index.py -v
```
Expected: all 6 tests pass.

- [ ] **Step 13.6: Commit**

```bash
git add plugins/wiki/server/server/tools/index.py plugins/wiki/server/tests/test_index.py plugins/wiki/server/tests/conftest.py
git commit -m "feat(wiki/688): add wiki_index_read + wiki_index_rebuild"
```

---

### Task 14: `tools/links.py` — wiki_link_resolve with section support

**Goal:** Resolve `[[page]]` and `[[page#section]]` to file path + section-found flag. Supports alias matching.

**Files:**
- Create: `plugins/wiki/server/server/tools/links.py`
- Create: `plugins/wiki/server/tests/test_links.py`

- [ ] **Step 14.1: Add links to conftest**

Edit mcp_app:
```python
@pytest.fixture
def mcp_app(wiki_setup: dict[str, Path]) -> FastMCP:
    from server.tools import index, links, log, page
    mcp: FastMCP = FastMCP("wiki-test")
    page.register(mcp)
    log.register(mcp)
    index.register(mcp)
    links.register(mcp)
    return mcp
```

- [ ] **Step 14.2: Write failing tests**

File: `plugins/wiki/server/tests/test_links.py`
```python
"""Tests for wiki_link_resolve."""
import json
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from tests.conftest import call_tool
from tests.test_page_list import _write_page


@pytest.mark.asyncio
class TestWikiLinkResolve:
    async def test_resolve_by_slug(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "hooks-architecture")
        result = json.loads(await call_tool(
            mcp_app, "wiki_link_resolve", link="hooks-architecture"
        ))
        assert result["resolved"].endswith("hooks-architecture.md")
        assert result["section_found"] is None
        assert result["candidates"] == []

    async def test_resolve_missing(self, mcp_app: FastMCP) -> None:
        result = json.loads(await call_tool(mcp_app, "wiki_link_resolve", link="nope"))
        assert result["resolved"] is None

    async def test_resolve_case_insensitive(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "hooks")
        result = json.loads(await call_tool(mcp_app, "wiki_link_resolve", link="HOOKS"))
        assert result["resolved"] is not None

    async def test_resolve_by_alias(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        _write_page(
            wiki_setup["wiki_dir"], "concepts", "hooks-plugin-architecture",
            aliases=["hooks-architecture"],
        )
        result = json.loads(await call_tool(
            mcp_app, "wiki_link_resolve", link="hooks-architecture"
        ))
        assert result["resolved"].endswith("hooks-plugin-architecture.md")

    async def test_resolve_section_present(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        page = wiki_setup["wiki_dir"] / "pages" / "concepts" / "hooks.md"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(
            "---\ntitle: Hooks\ntags: []\nlinks_to: []\nscope: []\n"
            "sources: []\nlast_ingested: '2026-04-23'\n---\n"
            "# Hooks\n\n## Overview\n\ndetails\n\n## Dispatch\n\nmore"
        )
        result = json.loads(await call_tool(
            mcp_app, "wiki_link_resolve", link="hooks#Dispatch"
        ))
        assert result["resolved"].endswith("hooks.md")
        assert result["section_found"] is True

    async def test_resolve_section_missing(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "hooks")
        result = json.loads(await call_tool(
            mcp_app, "wiki_link_resolve", link="hooks#Nonexistent"
        ))
        assert result["resolved"].endswith("hooks.md")
        assert result["section_found"] is False

    async def test_resolve_collisions(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "hooks")
        _write_page(wiki_setup["wiki_dir"], "decisions", "hooks")
        result = json.loads(await call_tool(mcp_app, "wiki_link_resolve", link="hooks"))
        # First match wins (sorted) + candidates list populated
        assert result["resolved"] is not None
        assert len(result["candidates"]) >= 1
```

- [ ] **Step 14.3: Run tests; verify fail**

- [ ] **Step 14.4: Write links.py**

File: `plugins/wiki/server/server/tools/links.py`
```python
"""Wiki link resolver: [[page]] and [[page#section]] → file path."""
from __future__ import annotations

import json
import re

from mcp.server.fastmcp import FastMCP

from server.lib import config as config_mod
from server.lib import frontmatter as fm_mod
from server.lib import storage

_HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)


def register(mcp: FastMCP) -> None:
    mcp.tool()(wiki_link_resolve)


def _parse_link(link: str) -> tuple[str, str | None]:
    """Split '[[page#section]]' notation into (slug, section) or (slug, None)."""
    # Accept raw slug or already-stripped-of-[[]]
    link = link.strip().strip("[]").strip()
    if "#" in link:
        slug, section = link.split("#", 1)
        return slug.strip(), section.strip()
    return link, None


def _find_page(pages_root, slug: str):
    """Find a page by slug (case-insensitive) or alias. Returns (path, all_candidates)."""
    slug_lower = slug.lower()
    candidates = []
    for md in sorted(pages_root.rglob("*.md")):
        if md.stem.lower() == slug_lower:
            candidates.append(md)
            continue
        # Alias lookup
        try:
            fm, _ = fm_mod.parse(md.read_text())
        except fm_mod.FrontmatterError:
            continue
        aliases = fm.get("aliases", []) or []
        if any(str(a).lower() == slug_lower for a in aliases):
            candidates.append(md)
    if not candidates:
        return None, []
    # First match wins; return others as collision candidates
    return candidates[0], [str(c) for c in candidates[1:]]


def _section_in_body(body: str, section: str) -> bool:
    section_lower = section.strip().lower()
    for m in _HEADING_RE.finditer(body):
        if m.group(1).strip().lower() == section_lower:
            return True
    return False


def wiki_link_resolve(link: str) -> str:
    """Resolve a [[page]] or [[page#section]] link to a file path + section flag."""
    cfg = config_mod.load_config()
    pages_root = storage.pages_dir(cfg.wiki_dir)
    slug, section = _parse_link(link)
    if not pages_root.exists():
        return json.dumps({"resolved": None, "section_found": None, "candidates": []})

    path, candidates = _find_page(pages_root, slug)
    if path is None:
        return json.dumps({"resolved": None, "section_found": None, "candidates": candidates})

    section_found: bool | None = None
    if section is not None:
        try:
            _, body = fm_mod.parse(path.read_text())
            section_found = _section_in_body(body, section)
        except fm_mod.FrontmatterError:
            section_found = False

    return json.dumps({
        "resolved": str(path),
        "section_found": section_found,
        "candidates": candidates,
    })
```

- [ ] **Step 14.5: Run tests; verify all pass**

```bash
cd plugins/wiki/server && uv run pytest tests/test_links.py -v
```
Expected: all 7 tests pass.

- [ ] **Step 14.6: Commit**

```bash
git add plugins/wiki/server/server/tools/links.py plugins/wiki/server/tests/test_links.py plugins/wiki/server/tests/conftest.py
git commit -m "feat(wiki/688): add wiki_link_resolve with section + alias support"
```

---

### Task 15: `tools/scope.py` — wiki_scope_detect

**Goal:** Detect proj presence + active-project name → return `{scope, proj_present}`.

**Field-name note:** the implementation uses `data.get("active_project")` against `~/.claude/proj.yaml`. Before writing, grep `plugins/proj/server/server/` for how active-project is persisted (runtime session state vs. explicit yaml key). If the key differs (e.g. `active`, `current_project`, etc.) or is not in proj.yaml at all (e.g. tracked in a separate file), adjust the implementation + tests. The spec requires pure-data file introspection; if proj stores active-project in a non-yaml location (e.g. a session-context file), read that instead — document the resolved location in a code comment.

**Files:**
- Create: `plugins/wiki/server/server/tools/scope.py`
- Create: `plugins/wiki/server/tests/test_scope.py`

- [ ] **Step 15.1: Add scope to conftest**

```python
@pytest.fixture
def mcp_app(wiki_setup: dict[str, Path]) -> FastMCP:
    from server.tools import index, links, log, page, scope
    mcp: FastMCP = FastMCP("wiki-test")
    page.register(mcp)
    log.register(mcp)
    index.register(mcp)
    links.register(mcp)
    scope.register(mcp)
    return mcp
```

Add `proj_yaml_path` fixture to conftest:
```python
@pytest.fixture
def proj_yaml_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect proj.yaml lookup in scope.py to a temp path."""
    p = tmp_path / "proj.yaml"
    monkeypatch.setattr("server.tools.scope._PROJ_YAML_PATH", p)
    return p
```

- [ ] **Step 15.2: Write failing tests**

File: `plugins/wiki/server/tests/test_scope.py`
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
    async def test_proj_absent(self, mcp_app: FastMCP, proj_yaml_path: Path) -> None:
        # proj.yaml doesn't exist
        result = json.loads(await call_tool(mcp_app, "wiki_scope_detect"))
        assert result["scope"] == "global"
        assert result["proj_present"] is False

    async def test_proj_present_with_active_project(self, mcp_app: FastMCP, proj_yaml_path: Path) -> None:
        proj_yaml_path.write_text(yaml.safe_dump({
            "active_project": "my-cool-project",
        }))
        result = json.loads(await call_tool(mcp_app, "wiki_scope_detect"))
        assert result["scope"] == "project:my-cool-project"
        assert result["proj_present"] is True

    async def test_proj_present_no_active(self, mcp_app: FastMCP, proj_yaml_path: Path) -> None:
        proj_yaml_path.write_text(yaml.safe_dump({}))
        result = json.loads(await call_tool(mcp_app, "wiki_scope_detect"))
        assert result["scope"] == "global"
        assert result["proj_present"] is True

    async def test_malformed_proj_yaml(self, mcp_app: FastMCP, proj_yaml_path: Path) -> None:
        proj_yaml_path.write_text("not: valid: yaml: :")
        result = json.loads(await call_tool(mcp_app, "wiki_scope_detect"))
        # Malformed → treat as missing
        assert result["scope"] == "global"
        assert result["proj_present"] is True  # file exists even if unreadable
```

- [ ] **Step 15.3: Run tests; verify fail**

- [ ] **Step 15.4: Write scope.py**

File: `plugins/wiki/server/server/tools/scope.py`
```python
"""wiki_scope_detect: resolve active-project scope via proj.yaml presence."""
from __future__ import annotations

import json
from pathlib import Path

import yaml
from mcp.server.fastmcp import FastMCP

_PROJ_YAML_PATH = Path.home() / ".claude" / "proj.yaml"


def register(mcp: FastMCP) -> None:
    mcp.tool()(wiki_scope_detect)


def wiki_scope_detect() -> str:
    """Detect active project scope via proj.yaml.

    Returns {scope, proj_present}:
        - scope: "project:<name>" if proj loaded + active_project set, else "global"
        - proj_present: whether proj.yaml exists on disk
    """
    proj_present = _PROJ_YAML_PATH.exists()
    if not proj_present:
        return json.dumps({"scope": "global", "proj_present": False})
    try:
        with _PROJ_YAML_PATH.open() as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError:
        return json.dumps({"scope": "global", "proj_present": True})
    active = data.get("active_project") if isinstance(data, dict) else None
    if active:
        return json.dumps({"scope": f"project:{active}", "proj_present": True})
    return json.dumps({"scope": "global", "proj_present": True})
```

- [ ] **Step 15.5: Run tests; verify all pass**

```bash
cd plugins/wiki/server && uv run pytest tests/test_scope.py -v
```
Expected: all 4 tests pass.

- [ ] **Step 15.6: Commit**

```bash
git add plugins/wiki/server/server/tools/scope.py plugins/wiki/server/tests/test_scope.py plugins/wiki/server/tests/conftest.py
git commit -m "feat(wiki/688): add wiki_scope_detect with proj.yaml introspection"
```

---

### Task 16: Wire main.py — register all tool modules

**Goal:** Update main.py to call every tool module's `register(mcp)`.

**Files:**
- Modify: `plugins/wiki/server/server/main.py`

- [ ] **Step 16.1: Update main.py**

File: `plugins/wiki/server/server/main.py`
```python
"""Wiki plugin MCP server entrypoint."""
from hook_dispatch import enable_hook_dispatch
from hook_transport import run_dual
from mcp.server.fastmcp import FastMCP

from server.tools import index, links, log, page, scope

mcp = FastMCP("wiki")
enable_hook_dispatch(mcp)

page.register(mcp)
index.register(mcp)
log.register(mcp)
links.register(mcp)
scope.register(mcp)


def main() -> None:
    run_dual(mcp, "wiki", default_port=19109)


if __name__ == "__main__":
    main()
```

- [ ] **Step 16.2: basedpyright + ruff clean**

```bash
cd plugins/wiki/server && just check
```
Expected: 0 errors.

- [ ] **Step 16.3: Smoke: server starts + responds to list_tools**

```bash
cd plugins/wiki/server && uv run python -c "
from server.main import mcp
import asyncio
async def list_tools():
    tools = await mcp.list_tools()
    print([t.name for t in tools])
asyncio.run(list_tools())
"
```
Expected output contains: `wiki_page_write`, `wiki_page_get`, `wiki_page_list`, `wiki_page_delete`, `wiki_log_append`, `wiki_log_read`, `wiki_index_read`, `wiki_index_rebuild`, `wiki_link_resolve`, `wiki_scope_detect`.

- [ ] **Step 16.4: Commit**

```bash
git add plugins/wiki/server/server/main.py
git commit -m "feat(wiki/688): wire main.py to register all Phase 1 tool modules"
```

---

### Task 17: Full test suite + coverage check

**Goal:** Ensure all tests pass + 85%+ coverage achieved.

- [ ] **Step 17.1: Run full suite**

```bash
cd plugins/wiki/server && uv run pytest --cov=server --cov-report=term-missing
```
Expected: all tests pass, coverage ≥ 85%. If coverage is below 85%, add tests for uncovered branches (typical: error paths in storage, edge cases in links).

- [ ] **Step 17.2: basedpyright + ruff clean on whole plugin**

```bash
cd plugins/wiki/server && just check
```
Expected: 0 errors, 0 warnings.

- [ ] **Step 17.3: If coverage gap: add tests**

If any module is below 85%, add targeted tests in the appropriate test file. Common gaps:
- `storage.atomic_write` error path on read-only dir
- `frontmatter.parse` body-only path (no opening `---`)
- `profile.load_profile` empty file / non-dict root
- `wiki_page_list` empty linked_from source missing

No commit required until tests exist; add them, rerun, commit as "test(wiki/688): cover <module> gap branches".

---

### Task 18: Update CLAUDE.md port table

**Goal:** Document wiki port 19109 in CLAUDE.md HOOK_TRANSPORT fallback table.

**Files:**
- Modify: `CLAUDE.md` — add `| wiki | 19109 |` row to port table

- [ ] **Step 18.1: Locate port table**

```bash
grep -n "todoist | 19106" CLAUDE.md
```
Expected: one line number; the port table lives there.

- [ ] **Step 18.2: Add wiki row**

Edit `CLAUDE.md`: after the `| confluence | 19108 |` row in the port table, add:
```markdown
| wiki | 19109 |
```

- [ ] **Step 18.3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(wiki/688): reserve port 19109 for wiki plugin in HOOK_TRANSPORT table"
```

---

### Task 19: Phase-close smoke + final commit

**Goal:** End-to-end sanity pass. Plugin is ready for Phase 2.

- [ ] **Step 19.1: Sync uv lockfiles from repo root**

```bash
cd /home/raul/worktrees/cpm/feat-688-karpathy-wiki-plugin && just sync
```
Expected: no errors; wiki lockfile tracked.

- [ ] **Step 19.2: Run repo-wide tests — ensure nothing else broke**

```bash
cd /home/raul/worktrees/cpm/feat-688-karpathy-wiki-plugin && just test
```
Expected: all plugins green including new wiki suite.

- [ ] **Step 19.3: Verify marketplace registration**

```bash
python -c "import json; data=json.load(open('.claude-plugin/marketplace.json')); print([p['name'] for p in data['plugins']])"
```
Expected: output contains `'wiki'`.

- [ ] **Step 19.4: Tag phase completion (no commit if nothing changed)**

If uv.lock changes or any adjustments were needed:
```bash
git add -A && git commit -m "chore(wiki/688): phase 1 complete — core tools + storage + profile loader ready"
```

---

## Verification

At phase-end, verify:

1. **Every Phase 1 tool present:** `wiki_page_write/get/list/delete`, `wiki_index_read/rebuild`, `wiki_log_append/read`, `wiki_link_resolve`, `wiki_scope_detect`. Verify via smoke test Step 16.3.
2. **Coverage ≥ 85%** on `server/`. Verify via Step 17.1.
3. **`just ci` green** (check + test + security). Run in `plugins/wiki/server/`.
4. **Repo-wide `just test` green** (no regressions in other plugins).
5. **Marketplace entry present** in `.claude-plugin/marketplace.json`.
6. **Port 19109 reserved** in `CLAUDE.md` port table.
7. **Plugin installable:** install into a test `~/.claude/plugins/` dir + run `wiki-server` — server binds, lists all 10 tools. (Manual smoke if time permits; not required to close Phase 1.)

## Handoff to Phase 2

After Phase 1 merges to dev, Phase 2 will build on this foundation:
- Lint tools (`wiki_lint_orphans`, `wiki_lint_broken_links`, `wiki_lint_broken_section_refs`, `wiki_lint_category_violations`, `wiki_lint_stale`, `wiki_lint_schema`, `wiki_lint_duplicates`).
- BM25 search (`wiki_search_bm25`, `wiki_search_index_refresh`) using `rank-bm25` (new dep).
- First user-facing skills (`/wiki:init`, `/wiki:query`, `/wiki:lint`).

Phase 2 plan to be written when Phase 1 is ready to merge.
