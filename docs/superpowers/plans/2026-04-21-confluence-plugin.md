# Confluence Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a read-only Confluence integration plugin (`plugins/confluence/`) for the `claude-project-manager` marketplace — MCP server on port 19108, 8 MCP tools, 6 skills, full installer wizard integration, 3-tier test coverage (unit + contract/respx + e2e live).

**Architecture:** Target Confluence REST API v1 on both Cloud (Basic auth, `/wiki/rest/api/*`) and Server/DC (Bearer PAT, `/rest/api/*`). Single client code path; deployment detection + auth assembly happen at client construction. Body rendering via `body.view` expansion → `markdownify` → markdown string. Cursor-less pagination using `start`+`limit` on both deployments. No hooks (read-only means no auto-sync targets).

**Tech Stack:** Python 3.12+, FastMCP, httpx, pyyaml, markdownify, beautifulsoup4, pytest, respx, claude-hook-transport (shared).

**Spec:** `docs/superpowers/specs/2026-04-21-confluence-plugin-design.md`

**Branch:** `feat/686-confluence-plugin` (worktree at `/home/raul/worktrees/cpm/feat-686-confluence-plugin/`)

---

## File Structure

### New files

```
plugins/confluence/
  .claude-plugin/
    plugin.json                                        # new
    default-hooks.yaml                                 # new — hooks: []
  .mcp.json                                            # new
  start.sh                                             # new
  README.md                                            # new
  server/
    pyproject.toml                                     # new
    server/
      __init__.py                                      # new
      main.py                                          # new — FastMCP + run_dual(port=19108)
      lib/
        __init__.py                                    # new
        config.py                                      # new — ConfluenceConfig + load_config
        client.py                                      # new — ConfluenceClient + get_client singleton
        markdown.py                                    # new — html_to_markdown
        ratelimit.py                                   # new — TokenBucket + retry helpers
        errors.py                                      # new — exception hierarchy
      tools/
        __init__.py                                    # new
        init.py                                        # new — confluence_init
        search.py                                      # new — confluence_search
        pages.py                                       # new — get_page + list_pages + get_page_tree
        spaces.py                                      # new — confluence_list_spaces
        attachments.py                                 # new — confluence_list_attachments
        comments.py                                    # new — confluence_list_comments
    tests/
      __init__.py                                      # new
      conftest.py                                      # new — fixtures (mock_client, cloud_config, server_config)
      contracts/
        __init__.py                                    # new
        search.py                                      # new — SEARCH_CLOUD, SEARCH_SERVER contracts
        pages.py                                       # new — GET_PAGE, GET_PAGE_BY_TITLE, TREE, LIST_PAGES
        spaces.py                                      # new — LIST_SPACES
        metadata.py                                    # new — LIST_ATTACHMENTS, LIST_COMMENTS
        errors.py                                      # new — 401/403/404/429/500 ErrorContract
      fixtures/
        sample_view_01.html ... sample_view_10.html    # new
        expected_md_01.md ... expected_md_10.md        # new
      test_config.py                                   # new
      test_init.py                                     # new
      test_client.py                                   # new
      test_markdown.py                                 # new
      test_ratelimit.py                                # new
      test_search.py                                   # new
      test_pages.py                                    # new
      test_spaces.py                                   # new
      test_tree.py                                     # new
      test_attachments.py                              # new
      test_comments.py                                 # new
      test_contracts_search.py                         # new
      test_contracts_pages.py                          # new
      test_contracts_spaces.py                         # new
      test_contracts_tree.py                           # new
      test_contracts_metadata.py                       # new
      test_contracts_errors.py                         # new
      e2e/
        __init__.py                                    # new
        README.md                                      # new — live-run instructions
        test_e2e_cloud.py                              # new — env-gated
        test_e2e_server.py                             # new — env-gated
  skills/
    search/SKILL.md                                    # new
    page/SKILL.md                                      # new
    spaces/SKILL.md                                    # new
    pages/SKILL.md                                     # new
    tree/SKILL.md                                      # new
    metadata/SKILL.md                                  # new
```

### Modified files

```
.claude-plugin/marketplace.json                        # add confluence entry
installer/flow/installer_flow.py                       # register confluence in wizard dispatch
installer/flow/integration_config.py                   # add configure_confluence
installer/flow/wizard.py                               # add to _PROJ_PLUGINS
installer/wizard.py                                    # add to proj_plugins (legacy)
installer/wizard_specs.py                              # extend YamlFile Literal
installer/defaults.yaml                                # add sync.confluence
plugins/_shared/test_contracts/base.py                 # allow auth_style="basic"
plugins/_shared/test_contracts/builders.py             # support Basic auth header
plugins/_shared/test_contracts/validators.py           # validate Basic auth header
CLAUDE.md                                              # add confluence plugin + port 19108
README.md                                              # add 6 skill rows
```

---

## Task Map

| Phase | Tasks | Summary |
|-------|-------|---------|
| 1. Scaffold | T1–T3 | Plugin directory, manifest files, pyproject |
| 2. Core libs | T4–T7 | Errors, config, rate limiter, markdown helper |
| 3. Client | T8 | ConfluenceClient w/ deployment detection + retry |
| 4. Contract infra | T9 | Extend _shared test_contracts for Basic auth |
| 5. MCP tools | T10–T17 | init, search, get_page, list_spaces, list_pages, tree, attachments, comments |
| 6. Server wiring | T18 | main.py + run_dual + dispatch |
| 7. E2E live | T19 | Env-gated live test scaffolding |
| 8. Skills | T20–T25 | 6 SKILL.md files |
| 9. Installer | T26–T29 | marketplace.json, wizard specs, integration_config, defaults |
| 10. Docs | T30–T31 | README files, CLAUDE.md, port table |
| 11. Integration check | T32 | Full wizard + MCP server boot smoke test |

---

## Pre-flight

Work happens in worktree `/home/raul/worktrees/cpm/feat-686-confluence-plugin/` on branch `feat/686-confluence-plugin`. All commands assume `cd /home/raul/worktrees/cpm/feat-686-confluence-plugin/` unless stated otherwise.

---

### Task 1: Plugin directory scaffold

**Files:**
- Create: `plugins/confluence/` + nested dirs
- Create: `plugins/confluence/.claude-plugin/plugin.json`
- Create: `plugins/confluence/.claude-plugin/default-hooks.yaml`
- Create: `plugins/confluence/.mcp.json`
- Create: `plugins/confluence/start.sh`
- Create: `plugins/confluence/server/server/__init__.py` + sub-package `__init__.py` files

- [ ] **Step 1: Create directory structure**

Run:
```bash
mkdir -p plugins/confluence/.claude-plugin
mkdir -p plugins/confluence/server/server/lib
mkdir -p plugins/confluence/server/server/tools
mkdir -p plugins/confluence/server/tests/contracts
mkdir -p plugins/confluence/server/tests/fixtures
mkdir -p plugins/confluence/server/tests/e2e
mkdir -p plugins/confluence/skills/search
mkdir -p plugins/confluence/skills/page
mkdir -p plugins/confluence/skills/spaces
mkdir -p plugins/confluence/skills/pages
mkdir -p plugins/confluence/skills/tree
mkdir -p plugins/confluence/skills/metadata
touch plugins/confluence/server/server/__init__.py
touch plugins/confluence/server/server/lib/__init__.py
touch plugins/confluence/server/server/tools/__init__.py
touch plugins/confluence/server/tests/__init__.py
touch plugins/confluence/server/tests/contracts/__init__.py
touch plugins/confluence/server/tests/e2e/__init__.py
```

- [ ] **Step 2: Write `plugin.json`** — delegates to `.mcp.json` per jira/trello pattern

Create `plugins/confluence/.claude-plugin/plugin.json`:
```json
{
  "name": "confluence",
  "description": "Read-only Confluence Cloud + Server/Data Center access via REST API.",
  "version": "1.0.0",
  "author": {
    "name": "raulfrk"
  },
  "mcpServers": "./.mcp.json"
}
```

- [ ] **Step 3: Write `.mcp.json`** — passes 2 positional args that `start.sh` requires (`server_dir`, `entrypoint_name`)

Create `plugins/confluence/.mcp.json`:
```json
{
  "mcpServers": {
    "confluence": {
      "command": "bash",
      "args": [
        "${CLAUDE_PLUGIN_ROOT}/start.sh",
        "${CLAUDE_PLUGIN_ROOT}/server",
        "confluence-server"
      ],
      "env": {
        "CONFLUENCE_CONFIG": "~/.claude/confluence.yaml"
      },
      "timeout": 120
    }
  }
}
```

- [ ] **Step 4: Write `default-hooks.yaml`**

Create `plugins/confluence/.claude-plugin/default-hooks.yaml`:
```yaml
# Confluence is a read-only integration — no auto-sync hooks.
hooks: []
```

- [ ] **Step 5: Write `start.sh`** — copy `plugins/jira/start.sh` byte-for-byte (complex _shared resolution + shared-venv fallback logic). Do NOT hand-write a simplified version.

Run:
```bash
cp plugins/jira/start.sh plugins/confluence/start.sh
```

Run:
```bash
chmod +x plugins/confluence/start.sh
```

- [ ] **Step 6: Verify structure**

Run:
```bash
find plugins/confluence -type f -not -path '*/__pycache__/*' | sort
```

Expected output includes `plugin.json`, `default-hooks.yaml`, `.mcp.json`, `start.sh`, and init files for Python packages.

- [ ] **Step 7: Commit**

```bash
git add plugins/confluence/
git commit -m "feat(confluence): scaffold plugin directory + manifests"
```

---

### Task 2: Python package config

**Files:**
- Create: `plugins/confluence/server/pyproject.toml`

- [ ] **Step 1: Write `pyproject.toml`**

Pattern copied from `plugins/jira/server/pyproject.toml`. Create `plugins/confluence/server/pyproject.toml`:
```toml
[project]
name = "confluence-server"
version = "1.0.0"
description = "Confluence read-only MCP server"
requires-python = ">=3.12"
dependencies = [
    "mcp>=1.2.0",
    "httpx>=0.28",
    "pyyaml>=6.0",
    "markdownify>=0.11",
    "beautifulsoup4>=4.12",
    "claude-hook-transport",
]

[project.scripts]
confluence-server = "server.main:main"

[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-cov>=5.0",
    "pytest-mock>=3.14",
    "pytest-xdist>=3.6",
    "respx>=0.21",
    "basedpyright>=1.15",
    "ruff>=0.6",
]

[tool.uv.sources]
claude-hook-transport = { path = "../../_shared" }

[tool.hatch.build.targets.wheel]
packages = ["server"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = ["-v", "--tb=short", "--cov=server", "--cov-fail-under=80", "-n", "auto"]
pythonpath = ["."]
markers = [
    "e2e_cloud: live Cloud tests (requires CONFLUENCE_E2E_CLOUD=1 + creds)",
    "e2e_server: live Server tests (requires CONFLUENCE_E2E_SERVER=1 + creds)",
]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "UP", "B", "SIM"]

[tool.basedpyright]
typeCheckingMode = "strict"
include = ["server", "tests"]
```

- [ ] **Step 2: Initial dependency sync**

Run:
```bash
cd plugins/confluence/server && uv sync
```

Expected: downloads deps, creates `.venv/`, generates `uv.lock`.

- [ ] **Step 3: Commit**

```bash
git add plugins/confluence/server/pyproject.toml plugins/confluence/server/uv.lock
git commit -m "feat(confluence): pyproject + uv lock"
```

---

### Task 3: Empty server boot (smoke)

**Files:**
- Modify: `plugins/confluence/server/server/main.py` (minimal)

- [ ] **Step 1: Write minimal `main.py`**

Create `plugins/confluence/server/server/main.py`:
```python
"""Confluence read-only MCP server entrypoint."""

from hook_dispatch import enable_hook_dispatch
from hook_transport import run_dual
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("confluence")
enable_hook_dispatch(mcp, exclude={"confluence_init"})


def main() -> None:
    run_dual(mcp, "confluence", default_port=19108)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Boot server manually**

Run (from `plugins/confluence/server/`):
```bash
timeout 3 uv run confluence-server || echo "server exit OK"
```

Expected: server starts + listens briefly + exits via timeout. No exceptions.

- [ ] **Step 3: Commit**

```bash
git add plugins/confluence/server/server/main.py plugins/confluence/server/server/__init__.py plugins/confluence/server/server/lib/__init__.py plugins/confluence/server/server/tools/__init__.py
git commit -m "feat(confluence): boot empty MCP server on port 19108"
```

---

### Task 4: Errors module

**Files:**
- Create: `plugins/confluence/server/server/lib/errors.py`
- Create: `plugins/confluence/server/tests/test_errors.py`

- [ ] **Step 1: Write failing test**

Create `plugins/confluence/server/tests/test_errors.py`:
```python
"""Tests for confluence error hierarchy."""

from __future__ import annotations

import pytest

from server.lib.errors import (
    AuthError,
    ConfigError,
    ConfluenceError,
    NotFoundError,
    RateLimitError,
    ServerError,
    SpaceNotAllowedError,
)


def test_all_errors_inherit_from_confluence_error() -> None:
    for err_cls in (
        ConfigError,
        AuthError,
        NotFoundError,
        RateLimitError,
        ServerError,
        SpaceNotAllowedError,
    ):
        assert issubclass(err_cls, ConfluenceError)


def test_rate_limit_error_carries_retry_after() -> None:
    err = RateLimitError("rate limited", retry_after=42)
    assert err.retry_after == 42


def test_space_not_allowed_error_carries_space_key() -> None:
    err = SpaceNotAllowedError("DOCS")
    assert err.space_key == "DOCS"
    assert "DOCS" in str(err)


def test_raising_and_catching() -> None:
    with pytest.raises(AuthError):
        raise AuthError("bad creds")
    with pytest.raises(ConfluenceError):
        raise NotFoundError("page 42 missing")
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd plugins/confluence/server && uv run pytest tests/test_errors.py -v
```

Expected: FAIL with `ImportError: cannot import name` (module doesn't exist yet).

- [ ] **Step 3: Write `errors.py`**

Create `plugins/confluence/server/server/lib/errors.py`:
```python
"""Confluence plugin exception hierarchy."""

from __future__ import annotations


class ConfluenceError(Exception):
    """Base error for the Confluence plugin."""


class ConfigError(ConfluenceError):
    """Invalid or missing configuration."""


class AuthError(ConfluenceError):
    """401/403 from Confluence."""


class NotFoundError(ConfluenceError):
    """404 from Confluence."""


class RateLimitError(ConfluenceError):
    """429 from Confluence after retries exhausted."""

    def __init__(self, message: str, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class ServerError(ConfluenceError):
    """5xx from Confluence."""


class SpaceNotAllowedError(ConfluenceError):
    """Caller referenced a space key not in allowed_spaces."""

    def __init__(self, space_key: str) -> None:
        super().__init__(f"Space not allowed: {space_key}")
        self.space_key = space_key
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
cd plugins/confluence/server && uv run pytest tests/test_errors.py -v
```

Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add plugins/confluence/server/server/lib/errors.py plugins/confluence/server/tests/test_errors.py
git commit -m "feat(confluence): typed exception hierarchy"
```

---

### Task 5: Config module

**Files:**
- Create: `plugins/confluence/server/server/lib/config.py`
- Create: `plugins/confluence/server/tests/test_config.py`

- [ ] **Step 1: Write failing test**

Create `plugins/confluence/server/tests/test_config.py`:
```python
"""Tests for confluence config loading."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from server.lib.config import ConfluenceConfig, load_config
from server.lib.errors import ConfigError


def _write_yaml(path: Path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data))


def test_load_cloud_config(tmp_path: Path) -> None:
    cfg_path = tmp_path / "confluence.yaml"
    _write_yaml(cfg_path, {
        "deployment": "cloud",
        "base_url": "https://acme.atlassian.net",
        "email": "u@example.com",
        "api_token": "tok123",
        "allowed_spaces": ["DOCS"],
    })

    cfg = load_config(str(cfg_path))

    assert cfg.deployment == "cloud"
    assert cfg.base_url == "https://acme.atlassian.net"
    assert cfg.email == "u@example.com"
    assert cfg.api_token == "tok123"
    assert cfg.personal_access_token is None
    assert cfg.allowed_spaces == ["DOCS"]
    assert cfg.rate_limit_per_10s == 10
    assert cfg.default_max_results == 25
    assert cfg.max_results_cap == 100
    assert cfg.timeout_seconds == 30


def test_load_server_config(tmp_path: Path) -> None:
    cfg_path = tmp_path / "confluence.yaml"
    _write_yaml(cfg_path, {
        "deployment": "server",
        "base_url": "https://confluence.example.com",
        "personal_access_token": "pat-456",
    })

    cfg = load_config(str(cfg_path))

    assert cfg.deployment == "server"
    assert cfg.personal_access_token == "pat-456"
    assert cfg.email is None
    assert cfg.api_token is None
    assert cfg.allowed_spaces == []


def test_base_url_trailing_slash_stripped(tmp_path: Path) -> None:
    cfg_path = tmp_path / "confluence.yaml"
    _write_yaml(cfg_path, {
        "deployment": "server",
        "base_url": "https://confluence.example.com/",
        "personal_access_token": "pat",
    })

    cfg = load_config(str(cfg_path))

    assert cfg.base_url == "https://confluence.example.com"


def test_missing_config_file_raises(tmp_path: Path) -> None:
    missing = tmp_path / "nope.yaml"
    with pytest.raises(ConfigError, match="not found"):
        load_config(str(missing))


def test_env_var_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg_path = tmp_path / "confluence.yaml"
    _write_yaml(cfg_path, {
        "deployment": "server",
        "base_url": "https://yaml.example.com",
        "personal_access_token": "yaml-pat",
    })
    monkeypatch.setenv("CONFLUENCE_BASE_URL", "https://env.example.com")
    monkeypatch.setenv("CONFLUENCE_PAT", "env-pat")

    cfg = load_config(str(cfg_path))

    assert cfg.base_url == "https://env.example.com"
    assert cfg.personal_access_token == "env-pat"


def test_config_default_path_used(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg_path = tmp_path / "confluence.yaml"
    _write_yaml(cfg_path, {
        "deployment": "server",
        "base_url": "https://x.example.com",
        "personal_access_token": "pat",
    })
    monkeypatch.setenv("CONFLUENCE_CONFIG", str(cfg_path))

    cfg = load_config()

    assert cfg.base_url == "https://x.example.com"


def test_empty_allowed_spaces_defaults_to_list(tmp_path: Path) -> None:
    cfg_path = tmp_path / "confluence.yaml"
    _write_yaml(cfg_path, {
        "deployment": "server",
        "base_url": "https://x.example.com",
        "personal_access_token": "pat",
    })

    cfg = load_config(str(cfg_path))

    assert cfg.allowed_spaces == []
    assert isinstance(cfg.allowed_spaces, list)
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd plugins/confluence/server && uv run pytest tests/test_config.py -v
```

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Write `config.py`**

Create `plugins/confluence/server/server/lib/config.py`:
```python
"""Confluence plugin config loading."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from server.lib.errors import ConfigError

DEFAULT_CONFIG_PATH = "~/.claude/confluence.yaml"


@dataclass(frozen=True)
class ConfluenceConfig:
    deployment: str  # "auto" | "cloud" | "server"
    base_url: str
    email: str | None = None
    api_token: str | None = None
    personal_access_token: str | None = None
    allowed_spaces: list[str] = field(default_factory=list)
    rate_limit_per_10s: int = 10
    default_max_results: int = 25
    max_results_cap: int = 100
    timeout_seconds: int = 30


def load_config(path: str | None = None) -> ConfluenceConfig:
    """Load config from YAML, applying env var overrides."""
    effective_path = path or os.environ.get("CONFLUENCE_CONFIG", DEFAULT_CONFIG_PATH)
    expanded = Path(effective_path).expanduser()
    if not expanded.exists():
        raise ConfigError(f"Confluence config not found: {expanded}")

    with expanded.open() as f:
        raw = yaml.safe_load(f) or {}

    base_url = (
        os.environ.get("CONFLUENCE_BASE_URL")
        or raw.get("base_url", "")
    ).rstrip("/")

    return ConfluenceConfig(
        deployment=raw.get("deployment", "auto"),
        base_url=base_url,
        email=os.environ.get("CONFLUENCE_EMAIL") or raw.get("email"),
        api_token=os.environ.get("CONFLUENCE_API_TOKEN") or raw.get("api_token"),
        personal_access_token=(
            os.environ.get("CONFLUENCE_PAT") or raw.get("personal_access_token")
        ),
        allowed_spaces=list(raw.get("allowed_spaces") or []),
        rate_limit_per_10s=int(raw.get("rate_limit_per_10s", 10)),
        default_max_results=int(raw.get("default_max_results", 25)),
        max_results_cap=int(raw.get("max_results_cap", 100)),
        timeout_seconds=int(raw.get("timeout_seconds", 30)),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
cd plugins/confluence/server && uv run pytest tests/test_config.py -v
```

Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add plugins/confluence/server/server/lib/config.py plugins/confluence/server/tests/test_config.py
git commit -m "feat(confluence): YAML config + env var overrides"
```

---

### Task 6: Rate limiter

**Files:**
- Create: `plugins/confluence/server/server/lib/ratelimit.py`
- Create: `plugins/confluence/server/tests/test_ratelimit.py`

- [ ] **Step 1: Write failing test**

Create `plugins/confluence/server/tests/test_ratelimit.py`:
```python
"""Tests for token bucket rate limiter."""

from __future__ import annotations

import time

from server.lib.ratelimit import TokenBucket


def test_initial_bucket_is_full() -> None:
    bucket = TokenBucket(capacity=5, refill_seconds=10.0)
    for _ in range(5):
        assert bucket.try_acquire() is True


def test_acquire_blocks_until_refill() -> None:
    bucket = TokenBucket(capacity=2, refill_seconds=1.0)
    assert bucket.try_acquire() is True
    assert bucket.try_acquire() is True
    assert bucket.try_acquire() is False

    time.sleep(0.6)
    assert bucket.try_acquire() is True


def test_acquire_blocking_call() -> None:
    bucket = TokenBucket(capacity=1, refill_seconds=0.5)
    assert bucket.try_acquire() is True

    t0 = time.monotonic()
    bucket.acquire()  # should block ~0.5s
    elapsed = time.monotonic() - t0

    assert 0.3 < elapsed < 0.9


def test_capacity_and_refill_rate_exposed() -> None:
    bucket = TokenBucket(capacity=10, refill_seconds=10.0)
    assert bucket.capacity == 10
    assert bucket.refill_seconds == 10.0
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd plugins/confluence/server && uv run pytest tests/test_ratelimit.py -v
```

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Write `ratelimit.py`**

Create `plugins/confluence/server/server/lib/ratelimit.py`:
```python
"""Token bucket rate limiter for Confluence API calls."""

from __future__ import annotations

import threading
import time


class TokenBucket:
    """Simple token bucket. Capacity tokens refilled over refill_seconds."""

    def __init__(self, capacity: int, refill_seconds: float) -> None:
        self.capacity = capacity
        self.refill_seconds = refill_seconds
        self._tokens = float(capacity)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        added = elapsed * (self.capacity / self.refill_seconds)
        self._tokens = min(float(self.capacity), self._tokens + added)
        self._last_refill = now

    def try_acquire(self) -> bool:
        with self._lock:
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False

    def acquire(self) -> None:
        """Block until a token is available."""
        while not self.try_acquire():
            wait = max(0.05, self.refill_seconds / self.capacity)
            time.sleep(wait)
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
cd plugins/confluence/server && uv run pytest tests/test_ratelimit.py -v
```

Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add plugins/confluence/server/server/lib/ratelimit.py plugins/confluence/server/tests/test_ratelimit.py
git commit -m "feat(confluence): token bucket rate limiter"
```

---

### Task 7: Markdown conversion

**Files:**
- Create: `plugins/confluence/server/server/lib/markdown.py`
- Create: `plugins/confluence/server/tests/test_markdown.py`
- Create: 4 paired HTML + MD fixtures in `plugins/confluence/server/tests/fixtures/`

- [ ] **Step 1: Create fixture files**

Create 4 paired fixtures. The `expected_md_*.md` files below are the expected output of `markdownify` on the HTML — regenerate if `markdownify` behavior changes.

Create `plugins/confluence/server/tests/fixtures/sample_view_01.html`:
```html
<h1>Heading</h1><p>A paragraph with <strong>bold</strong> and <em>italic</em>.</p>
```

Create `plugins/confluence/server/tests/fixtures/expected_md_01.md`:
```
# Heading

A paragraph with **bold** and *italic*.
```

Create `plugins/confluence/server/tests/fixtures/sample_view_02.html`:
```html
<p>Code sample:</p>
<pre><code class="language-python">def foo():
    return 42
</code></pre>
```

Create `plugins/confluence/server/tests/fixtures/expected_md_02.md`:
```
Code sample:

```
def foo():
    return 42
```
```

Create `plugins/confluence/server/tests/fixtures/sample_view_03.html`:
```html
<ul><li>one</li><li>two</li><li>three</li></ul>
```

Create `plugins/confluence/server/tests/fixtures/expected_md_03.md`:
```
- one
- two
- three
```

Create `plugins/confluence/server/tests/fixtures/sample_view_04.html`:
```html
<blockquote><p>Panel: Note</p><p>Be careful.</p></blockquote>
```

Create `plugins/confluence/server/tests/fixtures/expected_md_04.md`:
```
> Panel: Note
> 
> Be careful.
```

- [ ] **Step 2: Write failing test**

Create `plugins/confluence/server/tests/test_markdown.py`:
```python
"""Tests for HTML-to-Markdown conversion."""

from __future__ import annotations

from pathlib import Path

import pytest

from server.lib.markdown import html_to_markdown

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("index", ["01", "02", "03", "04"])
def test_markdown_conversion(index: str) -> None:
    html = (FIXTURES_DIR / f"sample_view_{index}.html").read_text()
    expected = (FIXTURES_DIR / f"expected_md_{index}.md").read_text().strip()

    result = html_to_markdown(html).strip()

    # Collapse excess whitespace differences for robustness
    norm = lambda s: "\n".join(line.rstrip() for line in s.splitlines() if line.strip() or not s.endswith(line))
    assert norm(result) == norm(expected), f"fixture {index}:\nExpected:\n{expected}\nGot:\n{result}"


def test_script_tags_stripped() -> None:
    html = "<p>hello</p><script>alert(1)</script>"
    result = html_to_markdown(html)
    assert "alert" not in result
    assert "hello" in result


def test_style_tags_stripped() -> None:
    html = "<style>body{color:red}</style><p>hi</p>"
    result = html_to_markdown(html)
    assert "color:red" not in result
    assert "hi" in result


def test_empty_input_returns_empty() -> None:
    assert html_to_markdown("") == ""
```

- [ ] **Step 3: Run test to verify it fails**

Run:
```bash
cd plugins/confluence/server && uv run pytest tests/test_markdown.py -v
```

Expected: FAIL with `ImportError`.

- [ ] **Step 4: Write `markdown.py`**

Create `plugins/confluence/server/server/lib/markdown.py`:
```python
"""HTML-to-Markdown conversion for Confluence view format."""

from __future__ import annotations

from markdownify import markdownify as _md


def html_to_markdown(html: str) -> str:
    """Convert Confluence view-format HTML to Markdown."""
    if not html:
        return ""
    return _md(
        html,
        heading_style="ATX",
        bullets="-",
        strip=["script", "style"],
        code_language="",
    ).strip()
```

- [ ] **Step 5: Run test to verify it passes**

Run:
```bash
cd plugins/confluence/server && uv run pytest tests/test_markdown.py -v
```

Expected: PASS (7 tests). If any fixture comparison fails due to `markdownify` output formatting quirks, update the `expected_md_*.md` file to match actual output (comparison is normalized for trailing whitespace).

- [ ] **Step 6: Commit**

```bash
git add plugins/confluence/server/server/lib/markdown.py plugins/confluence/server/tests/test_markdown.py plugins/confluence/server/tests/fixtures/
git commit -m "feat(confluence): HTML→Markdown helper w/ fixtures"
```

---

### Task 8: ConfluenceClient — deployment detection + HTTP

**Files:**
- Create: `plugins/confluence/server/server/lib/client.py`
- Create: `plugins/confluence/server/tests/test_client.py`

- [ ] **Step 1: Write failing test**

Create `plugins/confluence/server/tests/test_client.py`:
```python
"""Tests for ConfluenceClient construction + HTTP behavior."""

from __future__ import annotations

import base64

import httpx
import pytest
import respx

from server.lib.client import ConfluenceClient, get_client
from server.lib.config import ConfluenceConfig
from server.lib.errors import (
    AuthError,
    ConfigError,
    NotFoundError,
    RateLimitError,
    ServerError,
)


def _cloud_cfg(**overrides) -> ConfluenceConfig:
    return ConfluenceConfig(
        deployment="auto",
        base_url="https://acme.atlassian.net",
        email="u@example.com",
        api_token="tok",
        **overrides,
    )


def _server_cfg(**overrides) -> ConfluenceConfig:
    return ConfluenceConfig(
        deployment="auto",
        base_url="https://conf.example.com",
        personal_access_token="pat",
        **overrides,
    )


def test_auto_detects_cloud() -> None:
    client = ConfluenceClient(_cloud_cfg())
    assert client.effective_deployment == "cloud"
    assert client.api_base == "https://acme.atlassian.net/wiki/rest/api"


def test_auto_detects_server() -> None:
    client = ConfluenceClient(_server_cfg())
    assert client.effective_deployment == "server"
    assert client.api_base == "https://conf.example.com/rest/api"


def test_explicit_deployment_overrides_detection() -> None:
    cfg = ConfluenceConfig(
        deployment="server",
        base_url="https://acme.atlassian.net",  # normally cloud
        personal_access_token="pat",
    )
    client = ConfluenceClient(cfg)
    assert client.effective_deployment == "server"


def test_cloud_missing_creds_raises() -> None:
    cfg = ConfluenceConfig(
        deployment="cloud",
        base_url="https://acme.atlassian.net",
    )
    with pytest.raises(ConfigError, match="email.*api_token"):
        ConfluenceClient(cfg)


def test_server_missing_pat_raises() -> None:
    cfg = ConfluenceConfig(
        deployment="server",
        base_url="https://conf.example.com",
    )
    with pytest.raises(ConfigError, match="personal_access_token"):
        ConfluenceClient(cfg)


def test_cloud_auth_header_is_basic() -> None:
    client = ConfluenceClient(_cloud_cfg())
    expected = base64.b64encode(b"u@example.com:tok").decode()
    assert client.auth_header == f"Basic {expected}"


def test_server_auth_header_is_bearer() -> None:
    client = ConfluenceClient(_server_cfg())
    assert client.auth_header == "Bearer pat"


@respx.mock
def test_get_success() -> None:
    client = ConfluenceClient(_server_cfg())
    respx.get("https://conf.example.com/rest/api/space").mock(
        return_value=httpx.Response(200, json={"results": []})
    )

    data = client.get("/space", params={})

    assert data == {"results": []}


@respx.mock
def test_get_404_raises_not_found() -> None:
    client = ConfluenceClient(_server_cfg())
    respx.get("https://conf.example.com/rest/api/content/nope").mock(
        return_value=httpx.Response(404, json={"message": "not found"})
    )

    with pytest.raises(NotFoundError):
        client.get("/content/nope", params={})


@respx.mock
def test_get_401_raises_auth_error() -> None:
    client = ConfluenceClient(_server_cfg())
    respx.get("https://conf.example.com/rest/api/space").mock(
        return_value=httpx.Response(401, json={"message": "bad auth"})
    )

    with pytest.raises(AuthError):
        client.get("/space", params={})


@respx.mock
def test_get_500_raises_server_error() -> None:
    client = ConfluenceClient(_server_cfg())
    respx.get("https://conf.example.com/rest/api/space").mock(
        return_value=httpx.Response(500, text="internal")
    )

    with pytest.raises(ServerError):
        client.get("/space", params={})


@respx.mock
def test_get_429_retries_honoring_retry_after() -> None:
    client = ConfluenceClient(_server_cfg())
    route = respx.get("https://conf.example.com/rest/api/space")
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "1"}),
        httpx.Response(200, json={"results": []}),
    ]

    data = client.get("/space", params={})

    assert data == {"results": []}
    assert route.call_count == 2


@respx.mock
def test_get_429_after_3_retries_raises_rate_limit() -> None:
    client = ConfluenceClient(_server_cfg())
    respx.get("https://conf.example.com/rest/api/space").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "1"})
    )

    with pytest.raises(RateLimitError):
        client.get("/space", params={})


def test_get_client_is_cached(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    cfg_path = tmp_path / "confluence.yaml"
    cfg_path.write_text(
        "deployment: server\n"
        "base_url: https://x.example.com\n"
        "personal_access_token: pat\n"
    )
    monkeypatch.setenv("CONFLUENCE_CONFIG", str(cfg_path))

    import server.lib.client as mod
    mod._cached_client = None  # reset

    a = get_client()
    b = get_client()
    assert a is b
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd plugins/confluence/server && uv run pytest tests/test_client.py -v
```

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Write `client.py`**

Create `plugins/confluence/server/server/lib/client.py`:
```python
"""Confluence HTTP client — deployment detection, auth, retry, rate limit."""

from __future__ import annotations

import base64
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from server.lib.config import ConfluenceConfig, load_config
from server.lib.errors import (
    AuthError,
    ConfigError,
    NotFoundError,
    RateLimitError,
    ServerError,
)
from server.lib.ratelimit import TokenBucket

_CLOUD_HOST_SUFFIX = ".atlassian.net"
_MAX_RETRIES = 3


class ConfluenceClient:
    def __init__(self, config: ConfluenceConfig) -> None:
        self._config = config
        self.effective_deployment = self._detect_deployment(config)
        self._validate_creds()
        self.auth_header = self._assemble_auth_header()
        self.api_base = self._resolve_api_base()
        self._http = httpx.Client(
            base_url=self.api_base,
            headers={
                "Authorization": self.auth_header,
                "Accept": "application/json",
            },
            timeout=config.timeout_seconds,
        )
        self._bucket = TokenBucket(
            capacity=config.rate_limit_per_10s,
            refill_seconds=10.0,
        )

    @staticmethod
    def _detect_deployment(cfg: ConfluenceConfig) -> str:
        if cfg.deployment in ("cloud", "server"):
            return cfg.deployment
        host = urlparse(cfg.base_url).hostname or ""
        if host.endswith(_CLOUD_HOST_SUFFIX):
            return "cloud"
        return "server"

    def _validate_creds(self) -> None:
        cfg = self._config
        if self.effective_deployment == "cloud":
            if not cfg.email or not cfg.api_token:
                raise ConfigError(
                    "Cloud deployment requires email + api_token"
                )
        elif self.effective_deployment == "server":
            if not cfg.personal_access_token:
                raise ConfigError(
                    "Server deployment requires personal_access_token"
                )

    def _assemble_auth_header(self) -> str:
        cfg = self._config
        if self.effective_deployment == "cloud":
            raw = f"{cfg.email}:{cfg.api_token}".encode()
            return f"Basic {base64.b64encode(raw).decode()}"
        return f"Bearer {cfg.personal_access_token}"

    def _resolve_api_base(self) -> str:
        if self.effective_deployment == "cloud":
            return f"{self._config.base_url}/wiki/rest/api"
        return f"{self._config.base_url}/rest/api"

    def get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        """GET with rate limit, retry, and typed error translation."""
        for attempt in range(_MAX_RETRIES):
            self._bucket.acquire()
            resp = self._http.get(path, params=params)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", "1"))
                if attempt == _MAX_RETRIES - 1:
                    raise RateLimitError(
                        f"Rate limited after {_MAX_RETRIES} retries",
                        retry_after=retry_after,
                    )
                time.sleep(retry_after)
                continue
            if resp.status_code in (401, 403):
                raise AuthError(f"Auth failed: {resp.status_code} {resp.text}")
            if resp.status_code == 404:
                raise NotFoundError(f"Not found: {resp.status_code} {resp.text}")
            if resp.status_code >= 500:
                raise ServerError(f"Server error: {resp.status_code} {resp.text}")
            raise ServerError(
                f"Unexpected response: {resp.status_code} {resp.text}"
            )
        # Unreachable
        raise RateLimitError("Exhausted retries")

    def check_space_allowed(self, space_key: str) -> None:
        """Raise SpaceNotAllowedError if allowed_spaces non-empty and key not in it."""
        from server.lib.errors import SpaceNotAllowedError

        if self._config.allowed_spaces and space_key not in self._config.allowed_spaces:
            raise SpaceNotAllowedError(space_key)

    @property
    def config(self) -> ConfluenceConfig:
        return self._config


_cached_client: ConfluenceClient | None = None


def get_client() -> ConfluenceClient:
    global _cached_client
    if _cached_client is None:
        _cached_client = ConfluenceClient(load_config())
    return _cached_client
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
cd plugins/confluence/server && uv run pytest tests/test_client.py -v
```

Expected: PASS (13 tests).

- [ ] **Step 5: Commit**

```bash
git add plugins/confluence/server/server/lib/client.py plugins/confluence/server/tests/test_client.py
git commit -m "feat(confluence): HTTP client w/ deployment detection + retry"
```

---

### Task 9: Extend _shared/test_contracts for Basic auth

**Files:**
- Modify: `plugins/_shared/test_contracts/base.py`
- Modify: `plugins/_shared/test_contracts/builders.py`
- Modify: `plugins/_shared/test_contracts/validators.py`
- Create: `plugins/_shared/test_contracts/tests/test_basic_auth.py` (if tests dir exists; else inline in existing)

- [ ] **Step 1: Inspect existing builders + validators**

Run:
```bash
cat plugins/_shared/test_contracts/builders.py | head -60
cat plugins/_shared/test_contracts/validators.py | head -60
```

Expected: `build_success_response(contract, data)` returns an `httpx.Response`; `assert_request_matches_contract(req, contract)` validates method/url/headers. Both check `contract.auth_style` — currently only `"bearer"` and `"query_params"`.

- [ ] **Step 2: Write failing test**

Create `plugins/_shared/test_contracts/tests/test_basic_auth.py` (create the tests dir if needed):
```python
"""Tests for Basic auth style support in contract validators."""

from __future__ import annotations

import base64

import httpx
import pytest

from test_contracts.base import EndpointContract
from test_contracts.validators import assert_request_matches_contract


def test_basic_auth_style_accepted() -> None:
    contract = EndpointContract(
        method="GET",
        url_pattern="/rest/api/space",
        required_headers={"Authorization": "Basic {b64_email_token}"},
        auth_style="basic",
        request_schema=None,
        response_schema={"properties": {"results": {"type": "array"}}},
        response_status=200,
    )

    raw = base64.b64encode(b"u@example.com:tok").decode()
    req = httpx.Request(
        "GET",
        "https://x.example.com/rest/api/space",
        headers={"Authorization": f"Basic {raw}"},
    )

    assert_request_matches_contract(req, contract)  # no raise


def test_basic_auth_rejects_bearer() -> None:
    contract = EndpointContract(
        method="GET",
        url_pattern="/rest/api/space",
        required_headers={"Authorization": "Basic {b64_email_token}"},
        auth_style="basic",
        request_schema=None,
        response_schema={"properties": {}},
        response_status=200,
    )

    req = httpx.Request(
        "GET",
        "https://x.example.com/rest/api/space",
        headers={"Authorization": "Bearer token"},
    )

    with pytest.raises(AssertionError, match="Basic"):
        assert_request_matches_contract(req, contract)
```

- [ ] **Step 3: Run test to verify it fails**

Run:
```bash
cd plugins/_shared && uv run pytest test_contracts/tests/test_basic_auth.py -v
```

Expected: FAIL (validator doesn't recognize `"basic"`).

- [ ] **Step 4: Update `base.py` docstring**

In `plugins/_shared/test_contracts/base.py`, update the `auth_style` field comment:
```python
    auth_style: str
    """Authentication style: "bearer", "basic", or "query_params"."""
```

- [ ] **Step 5: Update `validators.py` to accept `"basic"`**

In `plugins/_shared/test_contracts/validators.py`, locate the auth-validation branch and extend:
```python
def assert_request_matches_contract(req: httpx.Request, contract: EndpointContract) -> None:
    # ... existing method/URL checks ...
    auth = req.headers.get("authorization", "")
    if contract.auth_style == "bearer":
        assert auth.startswith("Bearer "), f"expected Bearer auth, got: {auth}"
    elif contract.auth_style == "basic":
        assert auth.startswith("Basic "), f"expected Basic auth, got: {auth}"
    elif contract.auth_style == "query_params":
        # ... existing check ...
        pass
    else:
        raise AssertionError(f"unknown auth_style: {contract.auth_style}")
```

(Preserve existing logic — this snippet shows only the `basic` branch addition.)

- [ ] **Step 6: Update `builders.py` to support `"basic"`**

In `plugins/_shared/test_contracts/builders.py`, locate `build_success_response` and `build_error_response`. Both functions assemble the sample response; neither needs to change for Basic auth since the contract's `required_headers` already encodes the pattern. No code change needed — verify with:
```bash
grep -n auth_style plugins/_shared/test_contracts/builders.py
```

Expected: if no `auth_style` reference in builders, skip this step.

- [ ] **Step 7: Run test to verify it passes**

Run:
```bash
cd plugins/_shared && uv run pytest test_contracts/tests/test_basic_auth.py -v
```

Expected: PASS (2 tests).

- [ ] **Step 8: Run full _shared test suite to catch regressions**

Run:
```bash
cd plugins/_shared && uv run pytest
```

Expected: all existing tests pass.

- [ ] **Step 9: Commit**

```bash
git add plugins/_shared/test_contracts/base.py plugins/_shared/test_contracts/validators.py plugins/_shared/test_contracts/tests/
git commit -m "feat(_shared): add Basic auth style to test_contracts validators"
```

---

### Task 10: MCP tool — `confluence_init`

**Files:**
- Create: `plugins/confluence/server/server/tools/init.py`
- Create: `plugins/confluence/server/tests/test_init.py`
- Modify: `plugins/confluence/server/server/main.py` — register `init`

- [ ] **Step 1: Write failing test**

Create `plugins/confluence/server/tests/test_init.py`:
```python
"""Tests for confluence_init tool."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from mcp.server.fastmcp import FastMCP

from server.tools import init as init_mod


@pytest.fixture()
def init_tool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> callable:
    cfg_path = tmp_path / "confluence.yaml"
    monkeypatch.setenv("CONFLUENCE_CONFIG", str(cfg_path))

    mcp = FastMCP("test")
    init_mod.register(mcp)
    return mcp._tool_manager._tools["confluence_init"].fn, cfg_path


def test_init_writes_cloud_yaml(init_tool) -> None:
    tool, cfg_path = init_tool
    result = tool(
        deployment="cloud",
        base_url="https://acme.atlassian.net",
        email="u@example.com",
        api_token="tok",
        allowed_spaces=["DOCS", "ENG"],
    )

    assert cfg_path.exists()
    data = yaml.safe_load(cfg_path.read_text())
    assert data["deployment"] == "cloud"
    assert data["base_url"] == "https://acme.atlassian.net"
    assert data["email"] == "u@example.com"
    assert data["api_token"] == "tok"
    assert data["allowed_spaces"] == ["DOCS", "ENG"]
    assert "status" in result
    assert result["config_path"] == str(cfg_path)


def test_init_writes_server_yaml(init_tool) -> None:
    tool, cfg_path = init_tool
    tool(
        deployment="server",
        base_url="https://conf.example.com",
        personal_access_token="pat",
    )

    data = yaml.safe_load(cfg_path.read_text())
    assert data["deployment"] == "server"
    assert data["personal_access_token"] == "pat"
    assert data.get("email") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd plugins/confluence/server && uv run pytest tests/test_init.py -v
```

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Write `init.py`**

Create `plugins/confluence/server/server/tools/init.py`:
```python
"""confluence_init tool — write ~/.claude/confluence.yaml."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from mcp.server.fastmcp import FastMCP

from server.lib.config import DEFAULT_CONFIG_PATH


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def confluence_init(
        deployment: str,
        base_url: str,
        email: str | None = None,
        api_token: str | None = None,
        personal_access_token: str | None = None,
        allowed_spaces: list[str] | None = None,
    ) -> dict[str, Any]:
        """Initialize or overwrite ~/.claude/confluence.yaml."""
        cfg_path = Path(
            os.environ.get("CONFLUENCE_CONFIG", DEFAULT_CONFIG_PATH)
        ).expanduser()
        cfg_path.parent.mkdir(parents=True, exist_ok=True)

        data: dict[str, Any] = {
            "deployment": deployment,
            "base_url": base_url.rstrip("/"),
            "allowed_spaces": allowed_spaces or [],
        }
        if email:
            data["email"] = email
        if api_token:
            data["api_token"] = api_token
        if personal_access_token:
            data["personal_access_token"] = personal_access_token

        cfg_path.write_text(yaml.safe_dump(data, sort_keys=True))

        return {"status": "ok", "config_path": str(cfg_path)}
```

- [ ] **Step 4: Register in `main.py`**

Modify `plugins/confluence/server/server/main.py` — add `init` import + register:
```python
"""Confluence read-only MCP server entrypoint."""

from hook_dispatch import enable_hook_dispatch
from hook_transport import run_dual
from mcp.server.fastmcp import FastMCP

from server.tools import init

mcp = FastMCP("confluence")
enable_hook_dispatch(mcp, exclude={"confluence_init"})

init.register(mcp)


def main() -> None:
    run_dual(mcp, "confluence", default_port=19108)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run test to verify it passes**

Run:
```bash
cd plugins/confluence/server && uv run pytest tests/test_init.py -v
```

Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add plugins/confluence/server/server/tools/init.py plugins/confluence/server/tests/test_init.py plugins/confluence/server/server/main.py
git commit -m "feat(confluence): confluence_init tool"
```

---

### Task 11: MCP tool + contract — `confluence_search`

**Files:**
- Create: `plugins/confluence/server/server/tools/search.py`
- Create: `plugins/confluence/server/tests/test_search.py`
- Create: `plugins/confluence/server/tests/conftest.py`
- Create: `plugins/confluence/server/tests/contracts/search.py`
- Create: `plugins/confluence/server/tests/test_contracts_search.py`
- Modify: `plugins/confluence/server/server/main.py` — register `search`

- [ ] **Step 1: Write `conftest.py` (shared fixtures)**

Create `plugins/confluence/server/tests/conftest.py`:
```python
"""Shared test fixtures."""

from __future__ import annotations

import pytest

from server.lib.client import ConfluenceClient
from server.lib.config import ConfluenceConfig


@pytest.fixture()
def cloud_config() -> ConfluenceConfig:
    return ConfluenceConfig(
        deployment="cloud",
        base_url="https://acme.atlassian.net",
        email="u@example.com",
        api_token="tok",
    )


@pytest.fixture()
def server_config() -> ConfluenceConfig:
    return ConfluenceConfig(
        deployment="server",
        base_url="https://conf.example.com",
        personal_access_token="pat",
    )


@pytest.fixture()
def cloud_client(cloud_config, monkeypatch: pytest.MonkeyPatch) -> ConfluenceClient:
    for var in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(var, raising=False)
    return ConfluenceClient(cloud_config)


@pytest.fixture()
def server_client(server_config, monkeypatch: pytest.MonkeyPatch) -> ConfluenceClient:
    for var in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(var, raising=False)
    return ConfluenceClient(server_config)
```

- [ ] **Step 2: Write failing unit test**

Create `plugins/confluence/server/tests/test_search.py`:
```python
"""Unit tests for confluence_search tool."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from mcp.server.fastmcp import FastMCP

from server.tools import search as search_mod


@pytest.fixture()
def search_tool() -> callable:
    mcp = FastMCP("test")
    search_mod.register(mcp)
    return mcp._tool_manager._tools["confluence_search"].fn


def test_search_wraps_text_in_cql(search_tool) -> None:
    client = MagicMock()
    client.get.return_value = {
        "results": [],
        "size": 0,
        "totalSize": 0,
        "_links": {},
    }
    client.config = MagicMock(allowed_spaces=[], default_max_results=25)

    with patch("server.tools.search.get_client", return_value=client):
        search_tool(text="incident report")

    call_params = client.get.call_args.kwargs["params"]
    assert 'text ~ "incident report"' in call_params["cql"]


def test_search_with_raw_cql_passes_through(search_tool) -> None:
    client = MagicMock()
    client.get.return_value = {"results": [], "size": 0, "totalSize": 0, "_links": {}}
    client.config = MagicMock(allowed_spaces=[], default_max_results=25)

    with patch("server.tools.search.get_client", return_value=client):
        search_tool(cql="space = DOCS AND type = page")

    assert client.get.call_args.kwargs["params"]["cql"] == "space = DOCS AND type = page"


def test_search_injects_space_filter_when_space_key_given(search_tool) -> None:
    client = MagicMock()
    client.get.return_value = {"results": [], "size": 0, "totalSize": 0, "_links": {}}
    client.config = MagicMock(allowed_spaces=[], default_max_results=25)

    with patch("server.tools.search.get_client", return_value=client):
        search_tool(text="foo", space_key="DOCS")

    cql = client.get.call_args.kwargs["params"]["cql"]
    assert "space = DOCS" in cql


def test_search_envelope_shape(search_tool) -> None:
    client = MagicMock()
    client.get.return_value = {
        "results": [
            {
                "content": {
                    "id": "42",
                    "type": "page",
                    "title": "Incident",
                    "space": {"key": "DOCS"},
                },
                "excerpt": "snippet",
                "url": "/display/DOCS/Incident",
                "lastModified": "2026-04-20T10:00:00Z",
            }
        ],
        "size": 1,
        "totalSize": 10,
        "_links": {"next": "/search?..."},
    }
    client.config = MagicMock(allowed_spaces=[], default_max_results=25)

    with patch("server.tools.search.get_client", return_value=client):
        result = search_tool(text="foo", limit=1, start=0)

    assert result["count"] == 1
    assert result["total"] == 10
    assert result["next_start"] == 1
    assert result["results"][0]["page_id"] == "42"
    assert result["results"][0]["space_key"] == "DOCS"


def test_search_enforces_allowed_spaces(search_tool) -> None:
    from server.lib.errors import SpaceNotAllowedError

    client = MagicMock()
    client.check_space_allowed.side_effect = SpaceNotAllowedError("ENG")
    client.config = MagicMock(allowed_spaces=["DOCS"], default_max_results=25)

    with patch("server.tools.search.get_client", return_value=client):
        with pytest.raises(SpaceNotAllowedError):
            search_tool(text="foo", space_key="ENG")
```

- [ ] **Step 3: Run test to verify it fails**

Run:
```bash
cd plugins/confluence/server && uv run pytest tests/test_search.py -v
```

Expected: FAIL with `ImportError`.

- [ ] **Step 4: Write `search.py` tool**

Create `plugins/confluence/server/server/tools/search.py`:
```python
"""confluence_search tool."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from server.lib.client import get_client


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def confluence_search(
        cql: str | None = None,
        text: str | None = None,
        space_key: str | None = None,
        type: str | None = None,
        limit: int | None = None,
        start: int = 0,
        expand: str | None = None,
    ) -> dict[str, Any]:
        """Search Confluence content via CQL or free text.

        Either `cql` (raw CQL) OR `text` (wrapped as text search) must be given.
        """
        if not cql and not text:
            raise ValueError("Either cql or text must be provided")

        client = get_client()
        if space_key:
            client.check_space_allowed(space_key)

        effective_cql = cql or f'text ~ "{text}"'
        clauses: list[str] = []
        if not cql:  # only inject when building from text
            if space_key:
                clauses.append(f"space = {space_key}")
            if type:
                clauses.append(f"type = {type}")
        if clauses:
            effective_cql = effective_cql + " AND " + " AND ".join(clauses)

        # Inject allowed_spaces filter when non-empty and caller didn't already filter
        if client.config.allowed_spaces and "space" not in effective_cql.lower():
            space_clause = " OR ".join(
                f"space = {k}" for k in client.config.allowed_spaces
            )
            effective_cql = f"({effective_cql}) AND ({space_clause})"

        effective_limit = limit or client.config.default_max_results
        params: dict[str, Any] = {
            "cql": effective_cql,
            "limit": effective_limit,
            "start": start,
        }
        if expand:
            params["expand"] = expand

        raw = client.get("/search", params=params)

        results = []
        for entry in raw.get("results", []):
            content = entry.get("content", {})
            results.append({
                "page_id": content.get("id"),
                "type": content.get("type"),
                "title": content.get("title"),
                "space_key": content.get("space", {}).get("key"),
                "url": entry.get("url") or entry.get("_links", {}).get("webui"),
                "excerpt": entry.get("excerpt"),
                "last_modified": entry.get("lastModified"),
            })

        has_next = bool(raw.get("_links", {}).get("next"))
        next_start = (start + effective_limit) if has_next else None

        return {
            "results": results,
            "count": len(results),
            "total": raw.get("totalSize"),
            "next_start": next_start,
        }
```

- [ ] **Step 5: Register in `main.py`**

In `plugins/confluence/server/server/main.py`, add `search` to imports + register:
```python
from server.tools import init, search

# ...
init.register(mcp)
search.register(mcp)
```

- [ ] **Step 6: Run unit test to verify it passes**

Run:
```bash
cd plugins/confluence/server && uv run pytest tests/test_search.py -v
```

Expected: PASS (5 tests).

- [ ] **Step 7: Write contract definitions**

Create `plugins/confluence/server/tests/contracts/search.py`:
```python
"""Confluence search endpoint contracts."""

from __future__ import annotations

from test_contracts.base import EndpointContract

_CLOUD_HEADERS = {"Authorization": "Basic {b64_email_token}"}
_SERVER_HEADERS = {"Authorization": "Bearer {token}"}

_SEARCH_RESPONSE_SCHEMA = {
    "properties": {
        "results": {"type": "array"},
        "size": {"type": "integer"},
        "totalSize": {"type": "integer"},
    }
}

SEARCH_CLOUD = EndpointContract(
    method="GET",
    url_pattern="/wiki/rest/api/search",
    required_headers=_CLOUD_HEADERS,
    auth_style="basic",
    request_schema=None,
    response_schema=_SEARCH_RESPONSE_SCHEMA,
    response_status=200,
)

SEARCH_SERVER = EndpointContract(
    method="GET",
    url_pattern="/rest/api/search",
    required_headers=_SERVER_HEADERS,
    auth_style="bearer",
    request_schema=None,
    response_schema=_SEARCH_RESPONSE_SCHEMA,
    response_status=200,
)
```

- [ ] **Step 8: Write contract test**

Create `plugins/confluence/server/tests/test_contracts_search.py`:
```python
"""Contract tests for confluence_search — Cloud + Server."""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from test_contracts.builders import build_success_response
from test_contracts.validators import assert_request_matches_contract, assert_response_parses

from tests.contracts import search as c


@pytest.fixture()
def search_tool(cloud_client, monkeypatch):
    from mcp.server.fastmcp import FastMCP

    from server.tools.search import register

    app = FastMCP("test")
    register(app)
    monkeypatch.setattr("server.tools.search.get_client", lambda: cloud_client)
    return app._tool_manager._tools["confluence_search"].fn


class TestSearchContractCloud:
    @respx.mock
    def test_request_shape(self, search_tool, cloud_client):
        payload = {"results": [], "size": 0, "totalSize": 0, "_links": {}}
        route = respx.get(f"{cloud_client.api_base}/search").mock(
            return_value=build_success_response(c.SEARCH_CLOUD, payload)
        )

        search_tool(text="foo", limit=10)

        req = route.calls[0].request
        assert_request_matches_contract(req, c.SEARCH_CLOUD)
        assert req.headers["authorization"].startswith("Basic ")

    @respx.mock
    def test_response_parses(self, search_tool, cloud_client):
        payload = {
            "results": [
                {
                    "content": {"id": "1", "type": "page", "title": "T",
                                "space": {"key": "DOCS"}},
                    "excerpt": "x",
                    "url": "/x",
                    "lastModified": "2026-04-20",
                }
            ],
            "size": 1,
            "totalSize": 1,
            "_links": {},
        }
        respx.get(f"{cloud_client.api_base}/search").mock(
            return_value=build_success_response(c.SEARCH_CLOUD, payload)
        )

        result = search_tool(text="foo")
        assert result["count"] == 1
        assert result["results"][0]["page_id"] == "1"


class TestSearchContractServer:
    @pytest.fixture()
    def search_tool_server(self, server_client, monkeypatch):
        from mcp.server.fastmcp import FastMCP

        from server.tools.search import register

        app = FastMCP("test")
        register(app)
        monkeypatch.setattr("server.tools.search.get_client", lambda: server_client)
        return app._tool_manager._tools["confluence_search"].fn

    @respx.mock
    def test_server_request_shape(self, search_tool_server, server_client):
        payload = {"results": [], "size": 0, "totalSize": 0, "_links": {}}
        route = respx.get(f"{server_client.api_base}/search").mock(
            return_value=build_success_response(c.SEARCH_SERVER, payload)
        )

        search_tool_server(text="foo")

        req = route.calls[0].request
        assert_request_matches_contract(req, c.SEARCH_SERVER)
        assert req.headers["authorization"].startswith("Bearer ")
```

- [ ] **Step 9: Run contract test**

Run:
```bash
cd plugins/confluence/server && uv run pytest tests/test_contracts_search.py -v
```

Expected: PASS (3 tests).

- [ ] **Step 10: Commit**

```bash
git add plugins/confluence/server/server/tools/search.py plugins/confluence/server/tests/test_search.py plugins/confluence/server/tests/conftest.py plugins/confluence/server/tests/contracts/search.py plugins/confluence/server/tests/test_contracts_search.py plugins/confluence/server/server/main.py
git commit -m "feat(confluence): confluence_search tool + contracts"
```

---

### Task 12: MCP tool + contract — `confluence_get_page`

**Files:**
- Create: `plugins/confluence/server/server/tools/pages.py`
- Create: `plugins/confluence/server/tests/test_pages.py`
- Create: `plugins/confluence/server/tests/contracts/pages.py`
- Create: `plugins/confluence/server/tests/test_contracts_pages.py`
- Modify: `plugins/confluence/server/server/main.py` — register `pages`

Note: `pages.py` will accrete 3 tools across tasks 12, 14, 15: `confluence_get_page`, `confluence_list_pages`, `confluence_get_page_tree`.

- [ ] **Step 1: Write failing unit test for get_page**

Create `plugins/confluence/server/tests/test_pages.py`:
```python
"""Unit tests for pages tools."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from mcp.server.fastmcp import FastMCP

from server.tools import pages as pages_mod


@pytest.fixture()
def get_page_tool() -> callable:
    mcp = FastMCP("test")
    pages_mod.register(mcp)
    return mcp._tool_manager._tools["confluence_get_page"].fn


def test_get_page_by_id_returns_markdown(get_page_tool) -> None:
    client = MagicMock()
    client.get.return_value = {
        "id": "42",
        "title": "My Page",
        "version": {"number": 3},
        "space": {"key": "DOCS"},
        "body": {"view": {"value": "<h1>Hello</h1>"}},
        "_links": {"webui": "/display/DOCS/My+Page"},
    }
    client.config = MagicMock(allowed_spaces=[])
    client.check_space_allowed = MagicMock()

    with patch("server.tools.pages.get_client", return_value=client):
        result = get_page_tool(page_id="42")

    client.get.assert_called_once()
    path_called = client.get.call_args.args[0]
    assert path_called == "/content/42"
    assert result["page_id"] == "42"
    assert result["title"] == "My Page"
    assert result["space_key"] == "DOCS"
    assert result["version"] == 3
    assert "# Hello" in result["body_md"]


def test_get_page_by_title_and_space(get_page_tool) -> None:
    client = MagicMock()
    client.get.return_value = {
        "results": [
            {
                "id": "99",
                "title": "Target",
                "version": {"number": 1},
                "space": {"key": "DOCS"},
                "body": {"view": {"value": "<p>x</p>"}},
                "_links": {"webui": "/"},
            }
        ]
    }
    client.config = MagicMock(allowed_spaces=[])
    client.check_space_allowed = MagicMock()

    with patch("server.tools.pages.get_client", return_value=client):
        result = get_page_tool(title="Target", space_key="DOCS")

    path_called = client.get.call_args.args[0]
    assert path_called == "/content"
    params = client.get.call_args.kwargs["params"]
    assert params["spaceKey"] == "DOCS"
    assert params["title"] == "Target"
    assert result["page_id"] == "99"


def test_get_page_format_html_returns_html_only(get_page_tool) -> None:
    client = MagicMock()
    client.get.return_value = {
        "id": "1",
        "title": "T",
        "version": {"number": 1},
        "space": {"key": "D"},
        "body": {"view": {"value": "<p>x</p>"}},
        "_links": {"webui": "/"},
    }
    client.config = MagicMock(allowed_spaces=[])
    client.check_space_allowed = MagicMock()

    with patch("server.tools.pages.get_client", return_value=client):
        result = get_page_tool(page_id="1", format="html")

    assert "body_html" in result
    assert "body_md" not in result


def test_get_page_format_both_returns_both(get_page_tool) -> None:
    client = MagicMock()
    client.get.return_value = {
        "id": "1",
        "title": "T",
        "version": {"number": 1},
        "space": {"key": "D"},
        "body": {"view": {"value": "<p>x</p>"}},
        "_links": {"webui": "/"},
    }
    client.config = MagicMock(allowed_spaces=[])
    client.check_space_allowed = MagicMock()

    with patch("server.tools.pages.get_client", return_value=client):
        result = get_page_tool(page_id="1", format="both")

    assert "body_md" in result
    assert "body_html" in result


def test_get_page_requires_id_or_title(get_page_tool) -> None:
    with patch("server.tools.pages.get_client", return_value=MagicMock()):
        with pytest.raises(ValueError):
            get_page_tool()


def test_get_page_title_requires_space(get_page_tool) -> None:
    with patch("server.tools.pages.get_client", return_value=MagicMock()):
        with pytest.raises(ValueError):
            get_page_tool(title="Target")


def test_get_page_enforces_allowed_spaces_by_title(get_page_tool) -> None:
    from server.lib.errors import SpaceNotAllowedError

    client = MagicMock()
    client.check_space_allowed.side_effect = SpaceNotAllowedError("ENG")
    client.config = MagicMock(allowed_spaces=["DOCS"])

    with patch("server.tools.pages.get_client", return_value=client):
        with pytest.raises(SpaceNotAllowedError):
            get_page_tool(title="x", space_key="ENG")


def test_get_page_enforces_allowed_spaces_after_fetch(get_page_tool) -> None:
    from server.lib.errors import SpaceNotAllowedError

    client = MagicMock()
    client.get.return_value = {
        "id": "42",
        "title": "T",
        "version": {"number": 1},
        "space": {"key": "ENG"},
        "body": {"view": {"value": "<p>x</p>"}},
        "_links": {"webui": "/"},
    }

    def _check(key):
        if key == "ENG":
            raise SpaceNotAllowedError("ENG")
    client.check_space_allowed.side_effect = _check
    client.config = MagicMock(allowed_spaces=["DOCS"])

    with patch("server.tools.pages.get_client", return_value=client):
        with pytest.raises(SpaceNotAllowedError):
            get_page_tool(page_id="42")
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd plugins/confluence/server && uv run pytest tests/test_pages.py -v
```

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Write `pages.py` with `confluence_get_page`**

Create `plugins/confluence/server/server/tools/pages.py`:
```python
"""Pages tools: get_page, list_pages, get_page_tree."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from server.lib.client import get_client
from server.lib.markdown import html_to_markdown


def register(mcp: FastMCP) -> None:
    _register_get_page(mcp)
    # list_pages + get_page_tree registered in subsequent tasks


def _register_get_page(mcp: FastMCP) -> None:
    @mcp.tool()
    def confluence_get_page(
        page_id: str | None = None,
        title: str | None = None,
        space_key: str | None = None,
        format: str = "md",
        include_labels: bool = False,
        include_ancestors: bool = False,
    ) -> dict[str, Any]:
        """Fetch a Confluence page by id OR (title + space_key). Returns markdown body."""
        if not page_id and not title:
            raise ValueError("Either page_id or title must be provided")
        if title and not space_key:
            raise ValueError("title requires space_key")
        if format not in ("md", "html", "both"):
            raise ValueError("format must be md|html|both")

        client = get_client()
        if space_key:
            client.check_space_allowed(space_key)

        expand_parts = ["body.view", "version", "space"]
        if include_ancestors:
            expand_parts.append("ancestors")
        if include_labels:
            expand_parts.append("metadata.labels")
        expand = ",".join(expand_parts)

        if page_id:
            raw = client.get(f"/content/{page_id}", params={"expand": expand})
        else:
            listing = client.get(
                "/content",
                params={
                    "type": "page",
                    "spaceKey": space_key,
                    "title": title,
                    "expand": expand,
                    "limit": 1,
                },
            )
            results = listing.get("results", [])
            if not results:
                from server.lib.errors import NotFoundError
                raise NotFoundError(
                    f"Page not found: {space_key}/{title}"
                )
            raw = results[0]

        resolved_space_key = raw.get("space", {}).get("key")
        if resolved_space_key:
            client.check_space_allowed(resolved_space_key)

        body_html = raw.get("body", {}).get("view", {}).get("value", "")
        out: dict[str, Any] = {
            "page_id": raw.get("id"),
            "title": raw.get("title"),
            "space_key": resolved_space_key,
            "url": raw.get("_links", {}).get("webui"),
            "version": raw.get("version", {}).get("number"),
        }
        if format in ("md", "both"):
            out["body_md"] = html_to_markdown(body_html)
        if format in ("html", "both"):
            out["body_html"] = body_html
        if include_labels:
            labels_block = raw.get("metadata", {}).get("labels", {})
            out["labels"] = [lb.get("name") for lb in labels_block.get("results", [])]
        if include_ancestors:
            out["ancestors"] = [
                {"id": a.get("id"), "title": a.get("title")}
                for a in raw.get("ancestors", [])
            ]
        return out
```

- [ ] **Step 4: Register in `main.py`**

In `main.py`, add `pages` import + register:
```python
from server.tools import init, pages, search
# ...
pages.register(mcp)
```

- [ ] **Step 5: Run unit test to verify it passes**

Run:
```bash
cd plugins/confluence/server && uv run pytest tests/test_pages.py -v
```

Expected: PASS (8 tests).

- [ ] **Step 6: Write contract definitions**

Create `plugins/confluence/server/tests/contracts/pages.py`:
```python
"""Confluence page endpoint contracts."""

from __future__ import annotations

from test_contracts.base import EndpointContract

_CLOUD_HEADERS = {"Authorization": "Basic {b64_email_token}"}
_SERVER_HEADERS = {"Authorization": "Bearer {token}"}

_PAGE_RESPONSE_SCHEMA = {
    "properties": {
        "id": {"type": "string"},
        "title": {"type": "string"},
        "version": {"type": "object"},
        "body": {"type": "object"},
    }
}

GET_PAGE_CLOUD = EndpointContract(
    method="GET",
    url_pattern="/wiki/rest/api/content/{id}",
    required_headers=_CLOUD_HEADERS,
    auth_style="basic",
    request_schema=None,
    response_schema=_PAGE_RESPONSE_SCHEMA,
    response_status=200,
)

GET_PAGE_SERVER = EndpointContract(
    method="GET",
    url_pattern="/rest/api/content/{id}",
    required_headers=_SERVER_HEADERS,
    auth_style="bearer",
    request_schema=None,
    response_schema=_PAGE_RESPONSE_SCHEMA,
    response_status=200,
)

_CONTENT_LIST_SCHEMA = {
    "properties": {
        "results": {"type": "array"},
        "size": {"type": "integer"},
    }
}

GET_PAGE_BY_TITLE_CLOUD = EndpointContract(
    method="GET",
    url_pattern="/wiki/rest/api/content",
    required_headers=_CLOUD_HEADERS,
    auth_style="basic",
    request_schema=None,
    response_schema=_CONTENT_LIST_SCHEMA,
    response_status=200,
)

GET_PAGE_BY_TITLE_SERVER = EndpointContract(
    method="GET",
    url_pattern="/rest/api/content",
    required_headers=_SERVER_HEADERS,
    auth_style="bearer",
    request_schema=None,
    response_schema=_CONTENT_LIST_SCHEMA,
    response_status=200,
)

# Aliases for list_pages + get_page_tree (added in Tasks 14, 15)
LIST_PAGES_CLOUD = GET_PAGE_BY_TITLE_CLOUD
LIST_PAGES_SERVER = GET_PAGE_BY_TITLE_SERVER

TREE_CLOUD = EndpointContract(
    method="GET",
    url_pattern="/wiki/rest/api/content/{id}/descendant/page",
    required_headers=_CLOUD_HEADERS,
    auth_style="basic",
    request_schema=None,
    response_schema=_CONTENT_LIST_SCHEMA,
    response_status=200,
)

TREE_SERVER = EndpointContract(
    method="GET",
    url_pattern="/rest/api/content/{id}/descendant/page",
    required_headers=_SERVER_HEADERS,
    auth_style="bearer",
    request_schema=None,
    response_schema=_CONTENT_LIST_SCHEMA,
    response_status=200,
)
```

- [ ] **Step 7: Write contract test for get_page**

Create `plugins/confluence/server/tests/test_contracts_pages.py`:
```python
"""Contract tests for confluence_get_page + confluence_list_pages + confluence_get_page_tree."""

from __future__ import annotations

import httpx
import pytest
import respx
from test_contracts.builders import build_success_response
from test_contracts.validators import assert_request_matches_contract

from tests.contracts import pages as c


def _get_page_tool(client, monkeypatch):
    from mcp.server.fastmcp import FastMCP

    from server.tools.pages import register

    app = FastMCP("test")
    register(app)
    monkeypatch.setattr("server.tools.pages.get_client", lambda: client)
    return app._tool_manager._tools["confluence_get_page"].fn


class TestGetPageContract:
    @respx.mock
    def test_cloud_by_id(self, cloud_client, monkeypatch):
        payload = {
            "id": "42", "title": "T", "version": {"number": 1},
            "space": {"key": "DOCS"}, "body": {"view": {"value": "<p>x</p>"}},
            "_links": {"webui": "/"},
        }
        route = respx.get(f"{cloud_client.api_base}/content/42").mock(
            return_value=build_success_response(c.GET_PAGE_CLOUD, payload)
        )

        tool = _get_page_tool(cloud_client, monkeypatch)
        tool(page_id="42")

        req = route.calls[0].request
        assert_request_matches_contract(req, c.GET_PAGE_CLOUD)

    @respx.mock
    def test_server_by_id(self, server_client, monkeypatch):
        payload = {
            "id": "42", "title": "T", "version": {"number": 1},
            "space": {"key": "DOCS"}, "body": {"view": {"value": "<p>x</p>"}},
            "_links": {"webui": "/"},
        }
        route = respx.get(f"{server_client.api_base}/content/42").mock(
            return_value=build_success_response(c.GET_PAGE_SERVER, payload)
        )

        tool = _get_page_tool(server_client, monkeypatch)
        tool(page_id="42")

        req = route.calls[0].request
        assert_request_matches_contract(req, c.GET_PAGE_SERVER)

    @respx.mock
    def test_cloud_by_title(self, cloud_client, monkeypatch):
        payload = {
            "results": [{
                "id": "42", "title": "T", "version": {"number": 1},
                "space": {"key": "DOCS"}, "body": {"view": {"value": "<p>x</p>"}},
                "_links": {"webui": "/"},
            }],
            "size": 1,
        }
        route = respx.get(f"{cloud_client.api_base}/content").mock(
            return_value=build_success_response(c.GET_PAGE_BY_TITLE_CLOUD, payload)
        )

        tool = _get_page_tool(cloud_client, monkeypatch)
        tool(title="T", space_key="DOCS")

        req = route.calls[0].request
        assert_request_matches_contract(req, c.GET_PAGE_BY_TITLE_CLOUD)
        assert "spaceKey=DOCS" in str(req.url)
        assert "title=T" in str(req.url)
```

- [ ] **Step 8: Run contract test**

Run:
```bash
cd plugins/confluence/server && uv run pytest tests/test_contracts_pages.py -v
```

Expected: PASS (3 tests — we'll add more as list_pages + tree land).

- [ ] **Step 9: Commit**

```bash
git add plugins/confluence/server/server/tools/pages.py plugins/confluence/server/tests/test_pages.py plugins/confluence/server/tests/contracts/pages.py plugins/confluence/server/tests/test_contracts_pages.py plugins/confluence/server/server/main.py
git commit -m "feat(confluence): confluence_get_page tool + contracts"
```

---

### Task 13: MCP tool + contract — `confluence_list_spaces`

**Files:**
- Create: `plugins/confluence/server/server/tools/spaces.py`
- Create: `plugins/confluence/server/tests/test_spaces.py`
- Create: `plugins/confluence/server/tests/contracts/spaces.py`
- Create: `plugins/confluence/server/tests/test_contracts_spaces.py`
- Modify: `plugins/confluence/server/server/main.py` — register `spaces`

- [ ] **Step 1: Write failing unit test**

Create `plugins/confluence/server/tests/test_spaces.py`:
```python
"""Unit tests for confluence_list_spaces."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from mcp.server.fastmcp import FastMCP

from server.tools import spaces as spaces_mod


@pytest.fixture()
def list_spaces_tool() -> callable:
    mcp = FastMCP("test")
    spaces_mod.register(mcp)
    return mcp._tool_manager._tools["confluence_list_spaces"].fn


def test_list_spaces_envelope_shape(list_spaces_tool) -> None:
    client = MagicMock()
    client.get.return_value = {
        "results": [
            {
                "key": "DOCS",
                "name": "Docs",
                "type": "global",
                "_links": {"webui": "/display/DOCS"},
            }
        ],
        "size": 1,
        "_links": {"next": "/space?..."},
    }
    client.config = MagicMock(default_max_results=25)

    with patch("server.tools.spaces.get_client", return_value=client):
        result = list_spaces_tool()

    assert result["count"] == 1
    assert result["results"][0]["key"] == "DOCS"
    assert result["next_start"] == 25


def test_list_spaces_passes_type_filter(list_spaces_tool) -> None:
    client = MagicMock()
    client.get.return_value = {"results": [], "size": 0, "_links": {}}
    client.config = MagicMock(default_max_results=25)

    with patch("server.tools.spaces.get_client", return_value=client):
        list_spaces_tool(type="personal")

    params = client.get.call_args.kwargs["params"]
    assert params["type"] == "personal"


def test_list_spaces_no_next_link_returns_null_cursor(list_spaces_tool) -> None:
    client = MagicMock()
    client.get.return_value = {"results": [], "size": 0, "_links": {}}
    client.config = MagicMock(default_max_results=25)

    with patch("server.tools.spaces.get_client", return_value=client):
        result = list_spaces_tool()

    assert result["next_start"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd plugins/confluence/server && uv run pytest tests/test_spaces.py -v
```

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Write `spaces.py`**

Create `plugins/confluence/server/server/tools/spaces.py`:
```python
"""confluence_list_spaces tool."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from server.lib.client import get_client


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def confluence_list_spaces(
        type: str | None = None,
        status: str | None = None,
        limit: int | None = None,
        start: int = 0,
    ) -> dict[str, Any]:
        """List Confluence spaces."""
        client = get_client()
        effective_limit = limit or client.config.default_max_results

        params: dict[str, Any] = {"limit": effective_limit, "start": start}
        if type:
            params["type"] = type
        if status:
            params["status"] = status

        raw = client.get("/space", params=params)

        results = []
        for s in raw.get("results", []):
            results.append({
                "key": s.get("key"),
                "name": s.get("name"),
                "type": s.get("type"),
                "url": s.get("_links", {}).get("webui"),
            })

        has_next = bool(raw.get("_links", {}).get("next"))
        next_start = (start + effective_limit) if has_next else None

        return {
            "results": results,
            "count": len(results),
            "next_start": next_start,
        }
```

- [ ] **Step 4: Register in `main.py`**

```python
from server.tools import init, pages, search, spaces
# ...
spaces.register(mcp)
```

- [ ] **Step 5: Run unit test to verify it passes**

Run:
```bash
cd plugins/confluence/server && uv run pytest tests/test_spaces.py -v
```

Expected: PASS (3 tests).

- [ ] **Step 6: Write contract definitions**

Create `plugins/confluence/server/tests/contracts/spaces.py`:
```python
"""Confluence space endpoint contracts."""

from __future__ import annotations

from test_contracts.base import EndpointContract

_CLOUD_HEADERS = {"Authorization": "Basic {b64_email_token}"}
_SERVER_HEADERS = {"Authorization": "Bearer {token}"}

_LIST_SCHEMA = {
    "properties": {
        "results": {"type": "array"},
        "size": {"type": "integer"},
    }
}

LIST_SPACES_CLOUD = EndpointContract(
    method="GET",
    url_pattern="/wiki/rest/api/space",
    required_headers=_CLOUD_HEADERS,
    auth_style="basic",
    request_schema=None,
    response_schema=_LIST_SCHEMA,
    response_status=200,
)

LIST_SPACES_SERVER = EndpointContract(
    method="GET",
    url_pattern="/rest/api/space",
    required_headers=_SERVER_HEADERS,
    auth_style="bearer",
    request_schema=None,
    response_schema=_LIST_SCHEMA,
    response_status=200,
)
```

- [ ] **Step 7: Write contract test**

Create `plugins/confluence/server/tests/test_contracts_spaces.py`:
```python
"""Contract tests for confluence_list_spaces."""

from __future__ import annotations

import respx
from test_contracts.builders import build_success_response
from test_contracts.validators import assert_request_matches_contract

from tests.contracts import spaces as c


def _tool(client, monkeypatch):
    from mcp.server.fastmcp import FastMCP

    from server.tools.spaces import register

    app = FastMCP("test")
    register(app)
    monkeypatch.setattr("server.tools.spaces.get_client", lambda: client)
    return app._tool_manager._tools["confluence_list_spaces"].fn


class TestListSpacesContract:
    @respx.mock
    def test_cloud(self, cloud_client, monkeypatch):
        payload = {"results": [], "size": 0, "_links": {}}
        route = respx.get(f"{cloud_client.api_base}/space").mock(
            return_value=build_success_response(c.LIST_SPACES_CLOUD, payload)
        )

        tool = _tool(cloud_client, monkeypatch)
        tool()

        req = route.calls[0].request
        assert_request_matches_contract(req, c.LIST_SPACES_CLOUD)

    @respx.mock
    def test_server(self, server_client, monkeypatch):
        payload = {"results": [], "size": 0, "_links": {}}
        route = respx.get(f"{server_client.api_base}/space").mock(
            return_value=build_success_response(c.LIST_SPACES_SERVER, payload)
        )

        tool = _tool(server_client, monkeypatch)
        tool()

        req = route.calls[0].request
        assert_request_matches_contract(req, c.LIST_SPACES_SERVER)
```

- [ ] **Step 8: Run contract test**

Run:
```bash
cd plugins/confluence/server && uv run pytest tests/test_contracts_spaces.py -v
```

Expected: PASS (2 tests).

- [ ] **Step 9: Commit**

```bash
git add plugins/confluence/server/server/tools/spaces.py plugins/confluence/server/tests/test_spaces.py plugins/confluence/server/tests/contracts/spaces.py plugins/confluence/server/tests/test_contracts_spaces.py plugins/confluence/server/server/main.py
git commit -m "feat(confluence): confluence_list_spaces tool + contracts"
```

---

### Task 14: MCP tool + contract — `confluence_list_pages`

**Files:**
- Modify: `plugins/confluence/server/server/tools/pages.py` — add `confluence_list_pages`
- Modify: `plugins/confluence/server/tests/test_pages.py` — add tests
- Modify: `plugins/confluence/server/tests/test_contracts_pages.py` — add contract tests

- [ ] **Step 1: Write failing unit tests**

Append to `plugins/confluence/server/tests/test_pages.py`:
```python
@pytest.fixture()
def list_pages_tool() -> callable:
    mcp = FastMCP("test")
    pages_mod.register(mcp)
    return mcp._tool_manager._tools["confluence_list_pages"].fn


def test_list_pages_envelope(list_pages_tool) -> None:
    client = MagicMock()
    client.get.return_value = {
        "results": [
            {"id": "1", "title": "p1", "_links": {"webui": "/p1"}},
            {"id": "2", "title": "p2", "_links": {"webui": "/p2"}},
        ],
        "size": 2,
        "_links": {"next": "/content?..."},
    }
    client.config = MagicMock(default_max_results=25)
    client.check_space_allowed = MagicMock()

    with patch("server.tools.pages.get_client", return_value=client):
        result = list_pages_tool(space_key="DOCS")

    params = client.get.call_args.kwargs["params"]
    assert params["spaceKey"] == "DOCS"
    assert params["type"] == "page"
    assert result["count"] == 2
    assert result["next_start"] == 25
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd plugins/confluence/server && uv run pytest tests/test_pages.py::test_list_pages_envelope -v
```

Expected: FAIL with `KeyError: 'confluence_list_pages'`.

- [ ] **Step 3: Add `confluence_list_pages` to `pages.py`**

In `pages.py`, extend `register()`:
```python
def register(mcp: FastMCP) -> None:
    _register_get_page(mcp)
    _register_list_pages(mcp)


def _register_list_pages(mcp: FastMCP) -> None:
    @mcp.tool()
    def confluence_list_pages(
        space_key: str,
        limit: int | None = None,
        start: int = 0,
    ) -> dict[str, Any]:
        """List pages in a space."""
        client = get_client()
        client.check_space_allowed(space_key)

        effective_limit = limit or client.config.default_max_results
        params = {
            "type": "page",
            "spaceKey": space_key,
            "limit": effective_limit,
            "start": start,
        }
        raw = client.get("/content", params=params)

        results = [
            {
                "page_id": p.get("id"),
                "title": p.get("title"),
                "url": p.get("_links", {}).get("webui"),
            }
            for p in raw.get("results", [])
        ]
        has_next = bool(raw.get("_links", {}).get("next"))
        next_start = (start + effective_limit) if has_next else None

        return {
            "results": results,
            "count": len(results),
            "next_start": next_start,
        }
```

- [ ] **Step 4: Run unit test to verify it passes**

Run:
```bash
cd plugins/confluence/server && uv run pytest tests/test_pages.py -v
```

Expected: PASS (9 tests).

- [ ] **Step 5: Add contract test**

Append to `plugins/confluence/server/tests/test_contracts_pages.py`:
```python
def _list_pages_tool(client, monkeypatch):
    from mcp.server.fastmcp import FastMCP

    from server.tools.pages import register

    app = FastMCP("test")
    register(app)
    monkeypatch.setattr("server.tools.pages.get_client", lambda: client)
    return app._tool_manager._tools["confluence_list_pages"].fn


class TestListPagesContract:
    @respx.mock
    def test_cloud(self, cloud_client, monkeypatch):
        payload = {"results": [], "size": 0, "_links": {}}
        route = respx.get(f"{cloud_client.api_base}/content").mock(
            return_value=build_success_response(c.LIST_PAGES_CLOUD, payload)
        )

        tool = _list_pages_tool(cloud_client, monkeypatch)
        tool(space_key="DOCS")

        req = route.calls[0].request
        assert_request_matches_contract(req, c.LIST_PAGES_CLOUD)
        assert "type=page" in str(req.url)
        assert "spaceKey=DOCS" in str(req.url)

    @respx.mock
    def test_server(self, server_client, monkeypatch):
        payload = {"results": [], "size": 0, "_links": {}}
        route = respx.get(f"{server_client.api_base}/content").mock(
            return_value=build_success_response(c.LIST_PAGES_SERVER, payload)
        )

        tool = _list_pages_tool(server_client, monkeypatch)
        tool(space_key="DOCS")

        req = route.calls[0].request
        assert_request_matches_contract(req, c.LIST_PAGES_SERVER)
```

- [ ] **Step 6: Run contract test**

Run:
```bash
cd plugins/confluence/server && uv run pytest tests/test_contracts_pages.py -v
```

Expected: PASS (5 tests).

- [ ] **Step 7: Commit**

```bash
git add plugins/confluence/server/server/tools/pages.py plugins/confluence/server/tests/test_pages.py plugins/confluence/server/tests/test_contracts_pages.py
git commit -m "feat(confluence): confluence_list_pages tool + contracts"
```

---

### Task 15: MCP tool + contract — `confluence_get_page_tree`

**Files:**
- Modify: `plugins/confluence/server/server/tools/pages.py` — add `confluence_get_page_tree`
- Create: `plugins/confluence/server/tests/test_tree.py`
- Modify: `plugins/confluence/server/tests/test_contracts_pages.py` — add tree contract tests

- [ ] **Step 1: Write failing unit test**

Create `plugins/confluence/server/tests/test_tree.py`:
```python
"""Unit tests for confluence_get_page_tree."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from mcp.server.fastmcp import FastMCP

from server.tools import pages as pages_mod


@pytest.fixture()
def tree_tool() -> callable:
    mcp = FastMCP("test")
    pages_mod.register(mcp)
    return mcp._tool_manager._tools["confluence_get_page_tree"].fn


def test_tree_nests_by_ancestors(tree_tool) -> None:
    client = MagicMock()
    # Flat descendant list with ancestor chains
    client.get.return_value = {
        "results": [
            {"id": "10", "title": "root", "ancestors": []},
            {"id": "11", "title": "c1", "ancestors": [{"id": "10"}]},
            {"id": "12", "title": "c2", "ancestors": [{"id": "10"}]},
            {"id": "13", "title": "gc", "ancestors": [{"id": "10"}, {"id": "11"}]},
        ],
        "size": 4,
        "_links": {},
    }
    client.config = MagicMock(default_max_results=25)

    with patch("server.tools.pages.get_client", return_value=client):
        result = tree_tool(root_page_id="10")

    tree = result["tree"]
    assert tree["page_id"] == "10"
    ids_at_level_1 = sorted(c["page_id"] for c in tree["children"])
    assert ids_at_level_1 == ["11", "12"]
    c1 = next(c for c in tree["children"] if c["page_id"] == "11")
    assert c1["children"][0]["page_id"] == "13"


def test_tree_max_nodes_cap(tree_tool) -> None:
    client = MagicMock()
    client.get.return_value = {
        "results": [{"id": str(i), "title": f"n{i}", "ancestors": [{"id": "1"}]}
                    for i in range(500)],
        "size": 500,
        "_links": {},
    }
    client.config = MagicMock(default_max_results=25)

    with patch("server.tools.pages.get_client", return_value=client):
        result = tree_tool(root_page_id="1", max_nodes=10)

    def count(n):
        return 1 + sum(count(c) for c in n.get("children", []))

    assert count(result["tree"]) <= 11  # root + at most 10
    assert result.get("truncated") is True
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd plugins/confluence/server && uv run pytest tests/test_tree.py -v
```

Expected: FAIL with `KeyError: 'confluence_get_page_tree'`.

- [ ] **Step 3: Add `confluence_get_page_tree` to `pages.py`**

In `pages.py`, extend `register()` + add implementation:
```python
def register(mcp: FastMCP) -> None:
    _register_get_page(mcp)
    _register_list_pages(mcp)
    _register_get_page_tree(mcp)


def _register_get_page_tree(mcp: FastMCP) -> None:
    @mcp.tool()
    def confluence_get_page_tree(
        root_page_id: str,
        depth: str | int = "all",
        max_nodes: int = 200,
    ) -> dict[str, Any]:
        """Fetch descendant-page tree rooted at root_page_id. Builds nested structure from flat descendant list."""
        client = get_client()
        params: dict[str, Any] = {
            "depth": str(depth),
            "expand": "ancestors",
            "limit": min(max_nodes + 1, 200),
        }
        raw = client.get(f"/content/{root_page_id}/descendant/page", params=params)

        # Build index: id → node_dict; each node has children list.
        nodes: dict[str, dict[str, Any]] = {
            root_page_id: {
                "page_id": root_page_id,
                "title": None,
                "children": [],
            }
        }
        truncated = False
        for p in raw.get("results", [])[:max_nodes]:
            pid = p.get("id")
            nodes[pid] = {"page_id": pid, "title": p.get("title"), "children": []}
        if len(raw.get("results", [])) > max_nodes:
            truncated = True

        # Wire children using last ancestor's id as the parent.
        for p in raw.get("results", [])[:max_nodes]:
            pid = p.get("id")
            ancestors = p.get("ancestors", [])
            parent_id = ancestors[-1].get("id") if ancestors else root_page_id
            if parent_id in nodes and pid in nodes:
                nodes[parent_id]["children"].append(nodes[pid])

        out: dict[str, Any] = {
            "root_page_id": root_page_id,
            "tree": nodes[root_page_id],
        }
        if truncated:
            out["truncated"] = True
        return out
```

- [ ] **Step 4: Run unit test to verify it passes**

Run:
```bash
cd plugins/confluence/server && uv run pytest tests/test_tree.py -v
```

Expected: PASS (2 tests).

- [ ] **Step 5: Add contract test**

Append to `test_contracts_pages.py`:
```python
def _tree_tool(client, monkeypatch):
    from mcp.server.fastmcp import FastMCP

    from server.tools.pages import register

    app = FastMCP("test")
    register(app)
    monkeypatch.setattr("server.tools.pages.get_client", lambda: client)
    return app._tool_manager._tools["confluence_get_page_tree"].fn


class TestTreeContract:
    @respx.mock
    def test_cloud(self, cloud_client, monkeypatch):
        payload = {"results": [], "size": 0, "_links": {}}
        route = respx.get(
            f"{cloud_client.api_base}/content/10/descendant/page"
        ).mock(return_value=build_success_response(c.TREE_CLOUD, payload))

        tool = _tree_tool(cloud_client, monkeypatch)
        tool(root_page_id="10")

        req = route.calls[0].request
        assert_request_matches_contract(req, c.TREE_CLOUD)

    @respx.mock
    def test_server(self, server_client, monkeypatch):
        payload = {"results": [], "size": 0, "_links": {}}
        route = respx.get(
            f"{server_client.api_base}/content/10/descendant/page"
        ).mock(return_value=build_success_response(c.TREE_SERVER, payload))

        tool = _tree_tool(server_client, monkeypatch)
        tool(root_page_id="10")

        req = route.calls[0].request
        assert_request_matches_contract(req, c.TREE_SERVER)
```

- [ ] **Step 6: Run full contract suite**

Run:
```bash
cd plugins/confluence/server && uv run pytest tests/test_contracts_pages.py -v
```

Expected: PASS (7 tests).

- [ ] **Step 7: Commit**

```bash
git add plugins/confluence/server/server/tools/pages.py plugins/confluence/server/tests/test_tree.py plugins/confluence/server/tests/test_contracts_pages.py
git commit -m "feat(confluence): confluence_get_page_tree tool + contracts"
```

---

### Task 16: MCP tool + contract — `confluence_list_attachments`

**Files:**
- Create: `plugins/confluence/server/server/tools/attachments.py`
- Create: `plugins/confluence/server/tests/test_attachments.py`
- Create: `plugins/confluence/server/tests/contracts/metadata.py`
- Create: `plugins/confluence/server/tests/test_contracts_metadata.py`
- Modify: `plugins/confluence/server/server/main.py` — register `attachments`

- [ ] **Step 1: Write failing unit test**

Create `plugins/confluence/server/tests/test_attachments.py`:
```python
"""Unit tests for confluence_list_attachments."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from mcp.server.fastmcp import FastMCP

from server.tools import attachments as att_mod


@pytest.fixture()
def tool() -> callable:
    mcp = FastMCP("test")
    att_mod.register(mcp)
    return mcp._tool_manager._tools["confluence_list_attachments"].fn


def test_attachments_envelope_shape(tool) -> None:
    client = MagicMock()
    client.get.return_value = {
        "results": [
            {
                "id": "a1",
                "title": "diagram.png",
                "extensions": {"mediaType": "image/png", "fileSize": 12345},
                "_links": {"download": "/download/a1"},
            }
        ],
        "size": 1,
        "_links": {},
    }
    client.config = MagicMock(default_max_results=25)

    with patch("server.tools.attachments.get_client", return_value=client):
        result = tool(page_id="42")

    assert result["count"] == 1
    assert result["results"][0]["id"] == "a1"
    assert result["results"][0]["media_type"] == "image/png"
    assert result["results"][0]["file_size"] == 12345
    assert result["results"][0]["download_url"] == "/download/a1"


def test_attachments_media_type_filter(tool) -> None:
    client = MagicMock()
    client.get.return_value = {"results": [], "size": 0, "_links": {}}
    client.config = MagicMock(default_max_results=25)

    with patch("server.tools.attachments.get_client", return_value=client):
        tool(page_id="42", media_type="image/png")

    params = client.get.call_args.kwargs["params"]
    assert params["mediaType"] == "image/png"
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd plugins/confluence/server && uv run pytest tests/test_attachments.py -v
```

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Write `attachments.py`**

Create `plugins/confluence/server/server/tools/attachments.py`:
```python
"""confluence_list_attachments tool."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from server.lib.client import get_client


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def confluence_list_attachments(
        page_id: str,
        limit: int | None = None,
        start: int = 0,
        media_type: str | None = None,
        filename: str | None = None,
    ) -> dict[str, Any]:
        """List attachments on a Confluence page."""
        client = get_client()
        effective_limit = limit or client.config.default_max_results

        params: dict[str, Any] = {"limit": effective_limit, "start": start}
        if media_type:
            params["mediaType"] = media_type
        if filename:
            params["filename"] = filename

        raw = client.get(f"/content/{page_id}/child/attachment", params=params)

        results = []
        for a in raw.get("results", []):
            ext = a.get("extensions", {})
            results.append({
                "id": a.get("id"),
                "title": a.get("title"),
                "media_type": ext.get("mediaType"),
                "file_size": ext.get("fileSize"),
                "download_url": a.get("_links", {}).get("download"),
            })

        has_next = bool(raw.get("_links", {}).get("next"))
        next_start = (start + effective_limit) if has_next else None

        return {
            "results": results,
            "count": len(results),
            "next_start": next_start,
        }
```

- [ ] **Step 4: Register in `main.py`**

```python
from server.tools import attachments, init, pages, search, spaces
# ...
attachments.register(mcp)
```

- [ ] **Step 5: Run unit test to verify it passes**

Run:
```bash
cd plugins/confluence/server && uv run pytest tests/test_attachments.py -v
```

Expected: PASS (2 tests).

- [ ] **Step 6: Write contract definitions**

Create `plugins/confluence/server/tests/contracts/metadata.py`:
```python
"""Contracts for attachments + comments endpoints."""

from __future__ import annotations

from test_contracts.base import EndpointContract

_CLOUD_HEADERS = {"Authorization": "Basic {b64_email_token}"}
_SERVER_HEADERS = {"Authorization": "Bearer {token}"}

_LIST_SCHEMA = {
    "properties": {
        "results": {"type": "array"},
        "size": {"type": "integer"},
    }
}

LIST_ATTACHMENTS_CLOUD = EndpointContract(
    method="GET",
    url_pattern="/wiki/rest/api/content/{id}/child/attachment",
    required_headers=_CLOUD_HEADERS,
    auth_style="basic",
    request_schema=None,
    response_schema=_LIST_SCHEMA,
    response_status=200,
)

LIST_ATTACHMENTS_SERVER = EndpointContract(
    method="GET",
    url_pattern="/rest/api/content/{id}/child/attachment",
    required_headers=_SERVER_HEADERS,
    auth_style="bearer",
    request_schema=None,
    response_schema=_LIST_SCHEMA,
    response_status=200,
)

LIST_COMMENTS_CLOUD = EndpointContract(
    method="GET",
    url_pattern="/wiki/rest/api/content/{id}/child/comment",
    required_headers=_CLOUD_HEADERS,
    auth_style="basic",
    request_schema=None,
    response_schema=_LIST_SCHEMA,
    response_status=200,
)

LIST_COMMENTS_SERVER = EndpointContract(
    method="GET",
    url_pattern="/rest/api/content/{id}/child/comment",
    required_headers=_SERVER_HEADERS,
    auth_style="bearer",
    request_schema=None,
    response_schema=_LIST_SCHEMA,
    response_status=200,
)
```

- [ ] **Step 7: Write contract test**

Create `plugins/confluence/server/tests/test_contracts_metadata.py`:
```python
"""Contract tests for confluence_list_attachments + confluence_list_comments."""

from __future__ import annotations

import respx
from test_contracts.builders import build_success_response
from test_contracts.validators import assert_request_matches_contract

from tests.contracts import metadata as c


def _att_tool(client, monkeypatch):
    from mcp.server.fastmcp import FastMCP

    from server.tools.attachments import register

    app = FastMCP("test")
    register(app)
    monkeypatch.setattr("server.tools.attachments.get_client", lambda: client)
    return app._tool_manager._tools["confluence_list_attachments"].fn


class TestAttachmentsContract:
    @respx.mock
    def test_cloud(self, cloud_client, monkeypatch):
        payload = {"results": [], "size": 0, "_links": {}}
        route = respx.get(
            f"{cloud_client.api_base}/content/42/child/attachment"
        ).mock(return_value=build_success_response(c.LIST_ATTACHMENTS_CLOUD, payload))

        tool = _att_tool(cloud_client, monkeypatch)
        tool(page_id="42")

        req = route.calls[0].request
        assert_request_matches_contract(req, c.LIST_ATTACHMENTS_CLOUD)

    @respx.mock
    def test_server(self, server_client, monkeypatch):
        payload = {"results": [], "size": 0, "_links": {}}
        route = respx.get(
            f"{server_client.api_base}/content/42/child/attachment"
        ).mock(return_value=build_success_response(c.LIST_ATTACHMENTS_SERVER, payload))

        tool = _att_tool(server_client, monkeypatch)
        tool(page_id="42")

        req = route.calls[0].request
        assert_request_matches_contract(req, c.LIST_ATTACHMENTS_SERVER)
```

- [ ] **Step 8: Run contract test**

Run:
```bash
cd plugins/confluence/server && uv run pytest tests/test_contracts_metadata.py -v
```

Expected: PASS (2 tests).

- [ ] **Step 9: Commit**

```bash
git add plugins/confluence/server/server/tools/attachments.py plugins/confluence/server/tests/test_attachments.py plugins/confluence/server/tests/contracts/metadata.py plugins/confluence/server/tests/test_contracts_metadata.py plugins/confluence/server/server/main.py
git commit -m "feat(confluence): confluence_list_attachments tool + contracts"
```

---

### Task 17: MCP tool + contract — `confluence_list_comments`

**Files:**
- Create: `plugins/confluence/server/server/tools/comments.py`
- Create: `plugins/confluence/server/tests/test_comments.py`
- Modify: `plugins/confluence/server/tests/test_contracts_metadata.py` — add comments contract tests
- Modify: `plugins/confluence/server/server/main.py` — register `comments`

- [ ] **Step 1: Write failing unit test**

Create `plugins/confluence/server/tests/test_comments.py`:
```python
"""Unit tests for confluence_list_comments."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from mcp.server.fastmcp import FastMCP

from server.tools import comments as cm_mod


@pytest.fixture()
def tool() -> callable:
    mcp = FastMCP("test")
    cm_mod.register(mcp)
    return mcp._tool_manager._tools["confluence_list_comments"].fn


def test_comments_envelope_shape(tool) -> None:
    client = MagicMock()
    client.get.return_value = {
        "results": [
            {
                "id": "c1",
                "version": {"when": "2026-04-20T10:00:00Z", "by": {"displayName": "Alice"}},
                "body": {"view": {"value": "<p>nice</p>"}},
                "extensions": {"location": "footer"},
            }
        ],
        "size": 1,
        "_links": {},
    }
    client.config = MagicMock(default_max_results=25)

    with patch("server.tools.comments.get_client", return_value=client):
        result = tool(page_id="42")

    assert result["count"] == 1
    assert result["results"][0]["id"] == "c1"
    assert result["results"][0]["author"] == "Alice"
    assert "nice" in result["results"][0]["body_md"]
    assert result["results"][0]["location"] == "footer"


def test_comments_location_filter(tool) -> None:
    client = MagicMock()
    client.get.return_value = {"results": [], "size": 0, "_links": {}}
    client.config = MagicMock(default_max_results=25)

    with patch("server.tools.comments.get_client", return_value=client):
        tool(page_id="42", location="inline")

    params = client.get.call_args.kwargs["params"]
    assert params["location"] == "inline"
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd plugins/confluence/server && uv run pytest tests/test_comments.py -v
```

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Write `comments.py`**

Create `plugins/confluence/server/server/tools/comments.py`:
```python
"""confluence_list_comments tool."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from server.lib.client import get_client
from server.lib.markdown import html_to_markdown


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def confluence_list_comments(
        page_id: str,
        location: str | None = None,
        limit: int | None = None,
        start: int = 0,
    ) -> dict[str, Any]:
        """List comments on a Confluence page."""
        client = get_client()
        effective_limit = limit or client.config.default_max_results

        params: dict[str, Any] = {
            "limit": effective_limit,
            "start": start,
            "expand": "body.view,version",
        }
        if location and location != "all":
            params["location"] = location

        raw = client.get(f"/content/{page_id}/child/comment", params=params)

        results = []
        for c in raw.get("results", []):
            version = c.get("version", {})
            author = version.get("by", {}).get("displayName") if version else None
            body_html = c.get("body", {}).get("view", {}).get("value", "")
            results.append({
                "id": c.get("id"),
                "author": author,
                "created": version.get("when"),
                "body_md": html_to_markdown(body_html),
                "location": c.get("extensions", {}).get("location"),
            })

        has_next = bool(raw.get("_links", {}).get("next"))
        next_start = (start + effective_limit) if has_next else None

        return {
            "results": results,
            "count": len(results),
            "next_start": next_start,
        }
```

- [ ] **Step 4: Register in `main.py`**

```python
from server.tools import attachments, comments, init, pages, search, spaces
# ...
comments.register(mcp)
```

- [ ] **Step 5: Run unit test to verify it passes**

Run:
```bash
cd plugins/confluence/server && uv run pytest tests/test_comments.py -v
```

Expected: PASS (2 tests).

- [ ] **Step 6: Add contract test**

Append to `plugins/confluence/server/tests/test_contracts_metadata.py`:
```python
def _cm_tool(client, monkeypatch):
    from mcp.server.fastmcp import FastMCP

    from server.tools.comments import register

    app = FastMCP("test")
    register(app)
    monkeypatch.setattr("server.tools.comments.get_client", lambda: client)
    return app._tool_manager._tools["confluence_list_comments"].fn


class TestCommentsContract:
    @respx.mock
    def test_cloud(self, cloud_client, monkeypatch):
        payload = {"results": [], "size": 0, "_links": {}}
        route = respx.get(
            f"{cloud_client.api_base}/content/42/child/comment"
        ).mock(return_value=build_success_response(c.LIST_COMMENTS_CLOUD, payload))

        tool = _cm_tool(cloud_client, monkeypatch)
        tool(page_id="42")

        req = route.calls[0].request
        assert_request_matches_contract(req, c.LIST_COMMENTS_CLOUD)

    @respx.mock
    def test_server(self, server_client, monkeypatch):
        payload = {"results": [], "size": 0, "_links": {}}
        route = respx.get(
            f"{server_client.api_base}/content/42/child/comment"
        ).mock(return_value=build_success_response(c.LIST_COMMENTS_SERVER, payload))

        tool = _cm_tool(server_client, monkeypatch)
        tool(page_id="42")

        req = route.calls[0].request
        assert_request_matches_contract(req, c.LIST_COMMENTS_SERVER)
```

- [ ] **Step 7: Run contract test**

Run:
```bash
cd plugins/confluence/server && uv run pytest tests/test_contracts_metadata.py -v
```

Expected: PASS (4 tests).

- [ ] **Step 8: Commit**

```bash
git add plugins/confluence/server/server/tools/comments.py plugins/confluence/server/tests/test_comments.py plugins/confluence/server/tests/test_contracts_metadata.py plugins/confluence/server/server/main.py
git commit -m "feat(confluence): confluence_list_comments tool + contracts"
```

---

### Task 18: Error contract tests

**Files:**
- Create: `plugins/confluence/server/tests/contracts/errors.py`
- Create: `plugins/confluence/server/tests/test_contracts_errors.py`

- [ ] **Step 1: Write error contracts**

Create `plugins/confluence/server/tests/contracts/errors.py`:
```python
"""Error response contracts for Confluence API."""

from __future__ import annotations

from test_contracts.base import ErrorContract

UNAUTHORIZED = ErrorContract(
    status_code=401,
    response_body={"message": "Unauthorized"},
    extra_headers={},
    expected_exception="AuthError",
)

FORBIDDEN = ErrorContract(
    status_code=403,
    response_body={"message": "Forbidden"},
    extra_headers={},
    expected_exception="AuthError",
)

NOT_FOUND = ErrorContract(
    status_code=404,
    response_body={"message": "Not found"},
    extra_headers={},
    expected_exception="NotFoundError",
)

RATE_LIMITED = ErrorContract(
    status_code=429,
    response_body={"message": "Rate limited"},
    extra_headers={"Retry-After": "1"},
    expected_exception="RateLimitError",
)

SERVER_ERROR = ErrorContract(
    status_code=500,
    response_body={"message": "Internal error"},
    extra_headers={},
    expected_exception="ServerError",
)
```

- [ ] **Step 2: Write contract tests**

Create `plugins/confluence/server/tests/test_contracts_errors.py`:
```python
"""Error behavior contract tests."""

from __future__ import annotations

import httpx
import pytest
import respx

from server.lib.errors import (
    AuthError,
    NotFoundError,
    RateLimitError,
    ServerError,
)
from tests.contracts import errors as err


class TestErrorContracts:
    @respx.mock
    def test_401_raises_auth_error(self, server_client):
        respx.get(f"{server_client.api_base}/space").mock(
            return_value=httpx.Response(
                err.UNAUTHORIZED.status_code,
                json=err.UNAUTHORIZED.response_body,
            )
        )
        with pytest.raises(AuthError):
            server_client.get("/space", params={})

    @respx.mock
    def test_403_raises_auth_error(self, server_client):
        respx.get(f"{server_client.api_base}/space").mock(
            return_value=httpx.Response(
                err.FORBIDDEN.status_code,
                json=err.FORBIDDEN.response_body,
            )
        )
        with pytest.raises(AuthError):
            server_client.get("/space", params={})

    @respx.mock
    def test_404_raises_not_found(self, server_client):
        respx.get(f"{server_client.api_base}/content/42").mock(
            return_value=httpx.Response(
                err.NOT_FOUND.status_code,
                json=err.NOT_FOUND.response_body,
            )
        )
        with pytest.raises(NotFoundError):
            server_client.get("/content/42", params={})

    @respx.mock
    def test_429_retries_and_raises(self, server_client):
        respx.get(f"{server_client.api_base}/space").mock(
            return_value=httpx.Response(
                err.RATE_LIMITED.status_code,
                json=err.RATE_LIMITED.response_body,
                headers=err.RATE_LIMITED.extra_headers,
            )
        )
        with pytest.raises(RateLimitError) as exc_info:
            server_client.get("/space", params={})
        assert exc_info.value.retry_after == 1

    @respx.mock
    def test_500_raises_server_error(self, server_client):
        respx.get(f"{server_client.api_base}/space").mock(
            return_value=httpx.Response(
                err.SERVER_ERROR.status_code,
                json=err.SERVER_ERROR.response_body,
            )
        )
        with pytest.raises(ServerError):
            server_client.get("/space", params={})
```

- [ ] **Step 3: Run tests**

Run:
```bash
cd plugins/confluence/server && uv run pytest tests/test_contracts_errors.py -v
```

Expected: PASS (5 tests).

- [ ] **Step 4: Commit**

```bash
git add plugins/confluence/server/tests/contracts/errors.py plugins/confluence/server/tests/test_contracts_errors.py
git commit -m "test(confluence): error behavior contract tests"
```

---

### Task 19: E2E live test scaffolding

**Files:**
- Create: `plugins/confluence/server/tests/e2e/README.md`
- Create: `plugins/confluence/server/tests/e2e/test_e2e_cloud.py`
- Create: `plugins/confluence/server/tests/e2e/test_e2e_server.py`

- [ ] **Step 1: Write `e2e/README.md`**

Create `plugins/confluence/server/tests/e2e/README.md`:
```markdown
# Confluence E2E Live Tests

Opt-in live tests against real Confluence instances. Gated by env vars — skipped by default.

## Cloud

```bash
export CONFLUENCE_E2E_CLOUD=1
export CONFLUENCE_E2E_CLOUD_BASE_URL=https://acme.atlassian.net
export CONFLUENCE_E2E_CLOUD_EMAIL=you@example.com
export CONFLUENCE_E2E_CLOUD_API_TOKEN=<token>
export CONFLUENCE_E2E_CLOUD_TEST_SPACE_KEY=TESTDOCS
export CONFLUENCE_E2E_CLOUD_TEST_PAGE_ID=<numeric-id>
uv run pytest tests/e2e/test_e2e_cloud.py -m e2e_cloud -v
```

## Server / Data Center

```bash
export CONFLUENCE_E2E_SERVER=1
export CONFLUENCE_E2E_SERVER_BASE_URL=https://confluence.company.com
export CONFLUENCE_E2E_SERVER_PAT=<pat>
export CONFLUENCE_E2E_SERVER_TEST_SPACE_KEY=TESTDOCS
export CONFLUENCE_E2E_SERVER_TEST_PAGE_ID=<numeric-id>
uv run pytest tests/e2e/test_e2e_server.py -m e2e_server -v
```

## Requirements

- Dedicated read-only test space (assertions are shape-only; content may change).
- Test space must contain at least 1 page (use the page id in `TEST_PAGE_ID`).
- Test PAT/token needs: read spaces, read content, read attachments, read comments.
```

- [ ] **Step 2: Write `test_e2e_cloud.py`**

Create `plugins/confluence/server/tests/e2e/test_e2e_cloud.py`:
```python
"""Live Cloud E2E tests. Gated by CONFLUENCE_E2E_CLOUD=1 + creds."""

from __future__ import annotations

import os

import pytest

from server.lib.client import ConfluenceClient
from server.lib.config import ConfluenceConfig

pytestmark = [
    pytest.mark.e2e_cloud,
    pytest.mark.skipif(
        os.environ.get("CONFLUENCE_E2E_CLOUD") != "1",
        reason="set CONFLUENCE_E2E_CLOUD=1 to run",
    ),
]


@pytest.fixture(scope="module")
def cloud_client() -> ConfluenceClient:
    cfg = ConfluenceConfig(
        deployment="cloud",
        base_url=os.environ["CONFLUENCE_E2E_CLOUD_BASE_URL"],
        email=os.environ["CONFLUENCE_E2E_CLOUD_EMAIL"],
        api_token=os.environ["CONFLUENCE_E2E_CLOUD_API_TOKEN"],
    )
    return ConfluenceClient(cfg)


@pytest.fixture(scope="module")
def test_space_key() -> str:
    return os.environ["CONFLUENCE_E2E_CLOUD_TEST_SPACE_KEY"]


@pytest.fixture(scope="module")
def test_page_id() -> str:
    return os.environ["CONFLUENCE_E2E_CLOUD_TEST_PAGE_ID"]


def test_list_spaces(cloud_client, test_space_key):
    data = cloud_client.get("/space", params={"limit": 50})
    assert "results" in data
    keys = [s.get("key") for s in data["results"]]
    assert test_space_key in keys


def test_search(cloud_client, test_space_key):
    data = cloud_client.get(
        "/search",
        params={"cql": f"space = {test_space_key} AND type = page", "limit": 1},
    )
    assert "results" in data


def test_get_page(cloud_client, test_page_id):
    data = cloud_client.get(
        f"/content/{test_page_id}",
        params={"expand": "body.view,version,space"},
    )
    assert data.get("id") == test_page_id
    assert "body" in data


def test_list_pages_in_space(cloud_client, test_space_key):
    data = cloud_client.get(
        "/content",
        params={"type": "page", "spaceKey": test_space_key, "limit": 1},
    )
    assert "results" in data


def test_list_attachments(cloud_client, test_page_id):
    data = cloud_client.get(
        f"/content/{test_page_id}/child/attachment",
        params={"limit": 5},
    )
    assert "results" in data


def test_list_comments(cloud_client, test_page_id):
    data = cloud_client.get(
        f"/content/{test_page_id}/child/comment",
        params={"limit": 5, "expand": "body.view,version"},
    )
    assert "results" in data
```

- [ ] **Step 3: Write `test_e2e_server.py`**

Create `plugins/confluence/server/tests/e2e/test_e2e_server.py`:
```python
"""Live Server E2E tests. Gated by CONFLUENCE_E2E_SERVER=1 + creds."""

from __future__ import annotations

import os

import pytest

from server.lib.client import ConfluenceClient
from server.lib.config import ConfluenceConfig

pytestmark = [
    pytest.mark.e2e_server,
    pytest.mark.skipif(
        os.environ.get("CONFLUENCE_E2E_SERVER") != "1",
        reason="set CONFLUENCE_E2E_SERVER=1 to run",
    ),
]


@pytest.fixture(scope="module")
def server_client() -> ConfluenceClient:
    cfg = ConfluenceConfig(
        deployment="server",
        base_url=os.environ["CONFLUENCE_E2E_SERVER_BASE_URL"],
        personal_access_token=os.environ["CONFLUENCE_E2E_SERVER_PAT"],
    )
    return ConfluenceClient(cfg)


@pytest.fixture(scope="module")
def test_space_key() -> str:
    return os.environ["CONFLUENCE_E2E_SERVER_TEST_SPACE_KEY"]


@pytest.fixture(scope="module")
def test_page_id() -> str:
    return os.environ["CONFLUENCE_E2E_SERVER_TEST_PAGE_ID"]


def test_list_spaces(server_client, test_space_key):
    data = server_client.get("/space", params={"limit": 50})
    assert "results" in data
    keys = [s.get("key") for s in data["results"]]
    assert test_space_key in keys


def test_search(server_client, test_space_key):
    data = server_client.get(
        "/search",
        params={"cql": f"space = {test_space_key} AND type = page", "limit": 1},
    )
    assert "results" in data


def test_get_page(server_client, test_page_id):
    data = server_client.get(
        f"/content/{test_page_id}",
        params={"expand": "body.view,version,space"},
    )
    assert data.get("id") == test_page_id


def test_list_pages_in_space(server_client, test_space_key):
    data = server_client.get(
        "/content",
        params={"type": "page", "spaceKey": test_space_key, "limit": 1},
    )
    assert "results" in data


def test_list_attachments(server_client, test_page_id):
    data = server_client.get(
        f"/content/{test_page_id}/child/attachment",
        params={"limit": 5},
    )
    assert "results" in data


def test_list_comments(server_client, test_page_id):
    data = server_client.get(
        f"/content/{test_page_id}/child/comment",
        params={"limit": 5, "expand": "body.view,version"},
    )
    assert "results" in data
```

- [ ] **Step 4: Verify e2e tests skip without env**

Run:
```bash
cd plugins/confluence/server && uv run pytest tests/e2e -v
```

Expected: all tests SKIPPED (CONFLUENCE_E2E_* env vars not set).

- [ ] **Step 5: Commit**

```bash
git add plugins/confluence/server/tests/e2e/
git commit -m "test(confluence): env-gated live e2e tests (Cloud + Server)"
```

---

### Task 20: Skill — `/confluence:search`

**Files:**
- Create: `plugins/confluence/skills/search/SKILL.md`

- [ ] **Step 1: Write SKILL.md**

Create `plugins/confluence/skills/search/SKILL.md`:
```markdown
---
name: search
description: Search Confluence content via CQL or free text. Returns hits w/ page id, space, title, url, excerpt.
allowed-tools: mcp__plugin_confluence_confluence__confluence_search
argument-hint: "<query> [--cql] [--space KEY] [--type page|blogpost] [--limit N] [--start N] [--verbose]"
context: fork
agent: general-purpose
---

> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Search Confluence. Config check: `~/.claude/confluence.yaml` must exist w/ valid creds. Missing → err: "Run `cpm` installer to configure confluence."

## Args

- `<query>` — text (default) OR raw CQL (w/ `--cql`)
- `--cql` — treat query as CQL
- `--space KEY` — restrict to space (text mode only)
- `--type page|blogpost` — content-type filter
- `--limit N` — max hits (default: server default, cap 100)
- `--start N` — pagination offset
- `--verbose` — add excerpt line per hit

## Execution

Parse args; call `mcp__plugin_confluence_confluence__confluence_search`:
- `--cql` → pass `cql=<query>`
- else → pass `text=<query>`
- `--space` → `space_key=<KEY>`
- `--type` → `type=<page|blogpost>`
- `--limit`, `--start` → pass through

## Output

Per hit (one line):
```
<page_id> | <space_key> | <title> | <url> | <last_modified>
```

`--verbose` → second line per hit: `  ↳ <excerpt>`

Footer:
- `<count> results, total=<total>`
- `next_start` present → `... more — use --start <N>`

## Errors

- 401/403 → "Auth failed. Re-run `cpm` wizard for confluence."
- 429 → "Rate limited. Retry-After: <seconds>"
- 404 / other → verbatim bubble-up
```

- [ ] **Step 2: Verify skill syntax (basic sanity)**

Run:
```bash
grep -c "^---" plugins/confluence/skills/search/SKILL.md
```

Expected: `2` (frontmatter open + close).

- [ ] **Step 3: Commit**

```bash
git add plugins/confluence/skills/search/SKILL.md
git commit -m "feat(confluence): /confluence:search skill"
```

---

### Task 21: Skill — `/confluence:page`

**Files:**
- Create: `plugins/confluence/skills/page/SKILL.md`

- [ ] **Step 1: Write SKILL.md**

Create `plugins/confluence/skills/page/SKILL.md`:
```markdown
---
name: page
description: Fetch a Confluence page by id or (space_key/title). Returns header + markdown body.
allowed-tools: mcp__plugin_confluence_confluence__confluence_get_page
argument-hint: "<page_id> | <space_key>/<title> [--format md|html|both] [--labels] [--ancestors]"
context: fork
agent: general-purpose
---

> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Fetch Confluence page. Config check: `~/.claude/confluence.yaml` must exist w/ valid creds. Missing → err: "Run `cpm` installer to configure confluence."

## Args

- `<page_id>` — numeric id, OR
- `<space_key>/<title>` — slash-separated space key + exact page title
- `--format md|html|both` — body rendering (default: md)
- `--labels` — include labels
- `--ancestors` — include ancestor breadcrumb

## Execution

Parse arg:
- Contains `/` → split on first `/` → `space_key=<left>`, `title=<right>`; call `confluence_get_page(title=..., space_key=...)`
- else → `confluence_get_page(page_id=<arg>)`

Pass through `format`, `include_labels`, `include_ancestors` per flags.

## Output

Header block:
```
# <title>
**Space**: <space_key> | **Page ID**: <id> | **Version**: <n> | **URL**: <url>
```

`--labels` → append: `**Labels**: a, b, c`
`--ancestors` → append: `**Path**: <anc_1> → <anc_2> → ...`

Body:
- `format=md` (default) → `<body_md>`
- `format=html` → fenced `<body_html>`
- `format=both` → `<body_md>` then `## HTML Source` heading + fenced `<body_html>`

## Errors

- 401/403 → "Auth failed. Re-run `cpm` wizard for confluence."
- 404 → "Page not found: <arg>"
- 429 → "Rate limited. Retry-After: <seconds>"
```

- [ ] **Step 2: Commit**

```bash
git add plugins/confluence/skills/page/SKILL.md
git commit -m "feat(confluence): /confluence:page skill"
```

---

### Task 22: Skill — `/confluence:spaces`

- [ ] **Step 1: Write SKILL.md**

Create `plugins/confluence/skills/spaces/SKILL.md`:
```markdown
---
name: spaces
description: List Confluence spaces.
allowed-tools: mcp__plugin_confluence_confluence__confluence_list_spaces
argument-hint: "[--type global|personal] [--status current|archived] [--limit N] [--start N]"
context: fork
agent: general-purpose
---

> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

List spaces. Config check: `~/.claude/confluence.yaml` must exist. Missing → err: "Run `cpm` installer to configure confluence."

## Args

- `--type global|personal` — filter
- `--status current|archived` — filter
- `--limit N` — page size
- `--start N` — pagination offset

## Execution

Call `confluence_list_spaces(type=..., status=..., limit=..., start=...)`.

## Output

Per space:
```
<key> | <name> | <type> | <url>
```

Footer:
- `<count> spaces`
- `next_start` present → `... more — use --start <N>`

## Errors

Common error formatting (see `/confluence:search`).
```

- [ ] **Step 2: Commit**

```bash
git add plugins/confluence/skills/spaces/SKILL.md
git commit -m "feat(confluence): /confluence:spaces skill"
```

---

### Task 23: Skill — `/confluence:pages`

- [ ] **Step 1: Write SKILL.md**

Create `plugins/confluence/skills/pages/SKILL.md`:
```markdown
---
name: pages
description: List pages in a Confluence space.
allowed-tools: mcp__plugin_confluence_confluence__confluence_list_pages
argument-hint: "<space_key> [--limit N] [--start N]"
context: fork
agent: general-purpose
---

> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

List pages in space. Config check: `~/.claude/confluence.yaml` must exist. Missing → err: "Run `cpm` installer to configure confluence."

## Args

- `<space_key>` (required) — space key
- `--limit N`, `--start N` — pagination

## Execution

Call `confluence_list_pages(space_key=<arg>, limit=..., start=...)`.

## Output

Per page:
```
<id> | <title> | <url>
```

Footer:
- `<count> pages`
- `next_start` present → `... more — use --start <N>`

## Errors

Common error formatting (see `/confluence:search`).
```

- [ ] **Step 2: Commit**

```bash
git add plugins/confluence/skills/pages/SKILL.md
git commit -m "feat(confluence): /confluence:pages skill"
```

---

### Task 24: Skill — `/confluence:tree`

- [ ] **Step 1: Write SKILL.md**

Create `plugins/confluence/skills/tree/SKILL.md`:
```markdown
---
name: tree
description: Fetch descendant-page tree rooted at a Confluence page.
allowed-tools: mcp__plugin_confluence_confluence__confluence_get_page_tree
argument-hint: "<root_page_id> [--depth all|N] [--max N]"
context: fork
agent: general-purpose
---

> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Fetch page tree. Config check: `~/.claude/confluence.yaml` must exist. Missing → err: "Run `cpm` installer to configure confluence."

## Args

- `<root_page_id>` (required) — numeric id
- `--depth all|N` — tree depth (default: all)
- `--max N` — max nodes (default: 200)

## Execution

Call `confluence_get_page_tree(root_page_id=<arg>, depth=..., max_nodes=...)`.

## Output

Indented tree (2-space indent per level):
```
- <root_title> (<id>)
  - <child_title> (<id>)
    - <grandchild_title> (<id>)
```

If `truncated=true` in response → append footer: `... truncated at <max> nodes`.

## Errors

Common error formatting (see `/confluence:search`).
```

- [ ] **Step 2: Commit**

```bash
git add plugins/confluence/skills/tree/SKILL.md
git commit -m "feat(confluence): /confluence:tree skill"
```

---

### Task 25: Skill — `/confluence:metadata`

- [ ] **Step 1: Write SKILL.md**

Create `plugins/confluence/skills/metadata/SKILL.md`:
```markdown
---
name: metadata
description: Fetch a Confluence page's attachments and/or comments.
allowed-tools: mcp__plugin_confluence_confluence__confluence_list_attachments, mcp__plugin_confluence_confluence__confluence_list_comments
argument-hint: "<page_id> [comments|attachments|both] [--location footer|inline|resolved|all] [--limit N]"
context: fork
agent: general-purpose
---

> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Fetch attachments + comments for page. Config check: `~/.claude/confluence.yaml` must exist. Missing → err: "Run `cpm` installer to configure confluence."

## Args

- `<page_id>` (required)
- `comments|attachments|both` — section filter (default: both)
- `--location footer|inline|resolved|all` — comments location filter (comments only)
- `--limit N` — limit per section

## Execution

Per selected section:
- `attachments` → call `confluence_list_attachments(page_id=..., limit=...)`
- `comments` → call `confluence_list_comments(page_id=..., location=..., limit=...)`

## Output

Two sections (only selected ones shown):

```
### Attachments (<count>)
- <filename> | <media_type> | <size_bytes> | <download_url>
...

### Comments (<count>)
- [<location>] <author> @ <created>: <body_md first 80 chars>
...
```

`next_start` per section → `... more — use --limit/--start` footer.

## Errors

Common error formatting (see `/confluence:search`).
```

- [ ] **Step 2: Commit**

```bash
git add plugins/confluence/skills/metadata/SKILL.md
git commit -m "feat(confluence): /confluence:metadata skill"
```

---

### Task 26: Marketplace + wizard_specs registration

**Files:**
- Modify: `.claude-plugin/marketplace.json`
- Modify: `installer/wizard_specs.py`

- [ ] **Step 1: Add confluence to marketplace.json**

In `.claude-plugin/marketplace.json`, add this entry to the `plugins` array (alongside jira/trello/todoist):
```json
{
  "name": "confluence",
  "source": "./plugins/confluence",
  "description": "Read-only Confluence Cloud + Server/Data Center access via REST API.",
  "version": "1.0.0",
  "author": {"name": "raulfrk"},
  "license": "MIT",
  "category": "integrations",
  "keywords": ["confluence", "atlassian", "docs", "wiki"]
}
```

Placement: keep alphabetical inside the integrations group (between any existing `c*` plugins).

- [ ] **Step 2: Extend `YamlFile` literal**

In `installer/wizard_specs.py` find the `YamlFile` definition (around line 21) and add `"confluence"`:
```python
YamlFile = Literal["proj", "worktree", "todoist", "trello", "jira", "confluence"]
```

- [ ] **Step 3: Smoke-test the installer loads the plugin**

Run:
```bash
python3 -c "
import json
m = json.load(open('.claude-plugin/marketplace.json'))
names = [p['name'] for p in m['plugins']]
print('confluence' in names)
"
```

Expected: `True`.

- [ ] **Step 4: Commit**

```bash
git add .claude-plugin/marketplace.json installer/wizard_specs.py
git commit -m "feat(installer): register confluence in marketplace + wizard_specs"
```

---

### Task 27: `configure_confluence` integration flow

**Files:**
- Modify: `installer/flow/integration_config.py`
- Modify: `installer/flow/installer_flow.py`

- [ ] **Step 1: Read existing `configure_jira` for pattern**

Run:
```bash
grep -n "^def configure_" installer/flow/integration_config.py
```

Expected: lists `configure_jira`, `configure_todoist`, `configure_trello`.

- [ ] **Step 2: Add `configure_confluence` in `installer/flow/integration_config.py`**

Append to end of `installer/flow/integration_config.py`:
```python
def configure_confluence(console: Console) -> dict[str, Any] | None:
    """Prompt user for Confluence config, validate, write ~/.claude/confluence.yaml."""
    from urllib.parse import urlparse

    import httpx

    console.print("[bold]Confluence integration setup[/bold]")
    deployment = Prompt.ask(
        "Deployment",
        choices=["cloud", "server", "auto"],
        default="auto",
    )
    base_url = Prompt.ask(
        "Base URL (e.g. https://example.atlassian.net or https://confluence.company.com)"
    ).rstrip("/")

    # Resolve effective deployment for conditional prompts
    effective = deployment
    if effective == "auto":
        host = urlparse(base_url).hostname or ""
        effective = "cloud" if host.endswith(".atlassian.net") else "server"

    values: dict[str, Any] = {
        "deployment": deployment,
        "base_url": base_url,
        "allowed_spaces": [],
    }
    if effective == "cloud":
        values["email"] = Prompt.ask("Email (Atlassian account)")
        values["api_token"] = Prompt.ask("API token", password=True)
    else:
        values["personal_access_token"] = Prompt.ask(
            "Personal Access Token", password=True
        )

    spaces_raw = Prompt.ask(
        "Restrict to specific space keys (comma-separated; empty = all)",
        default="",
    )
    values["allowed_spaces"] = [
        s.strip() for s in spaces_raw.split(",") if s.strip()
    ] if spaces_raw else []

    # Validate via one GET call
    api_base = (
        f"{base_url}/wiki/rest/api"
        if effective == "cloud"
        else f"{base_url}/rest/api"
    )
    if effective == "cloud":
        auth = (values["email"], values["api_token"])
        headers = {}
    else:
        auth = None
        headers = {"Authorization": f"Bearer {values['personal_access_token']}"}

    try:
        with httpx.Client(timeout=10) as http:
            resp = http.get(
                f"{api_base}/space",
                params={"limit": 1},
                auth=auth,
                headers=headers,
            )
        if resp.status_code == 200:
            console.print("[green]✓ Validated Confluence credentials[/green]")
        elif resp.status_code in (401, 403):
            console.print(
                f"[red]✗ Auth failed ({resp.status_code}). Check creds.[/red]"
            )
            if not Confirm.ask("Save config anyway?", default=False):
                return None
        else:
            console.print(
                f"[yellow]Validation warning: HTTP {resp.status_code}[/yellow]"
            )
    except httpx.HTTPError as e:
        console.print(f"[yellow]Could not validate ({e}). Saving anyway.[/yellow]")

    cfg_path = Path("~/.claude/confluence.yaml").expanduser()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(yaml.safe_dump(values, sort_keys=True))
    console.print(f"[green]Wrote {cfg_path}[/green]")

    return values
```

Ensure imports at top of file include (add missing ones only):
```python
from pathlib import Path
from typing import Any

import yaml
from rich.console import Console
from rich.prompt import Confirm, Prompt
```

- [ ] **Step 3: Register confluence in `installer_flow.py`**

Open `installer/flow/installer_flow.py`. Make four edits:

(a) Around line 50 — extend `_WIZARD_PLUGINS`:
```python
_WIZARD_PLUGINS = {"proj", "router", "todoist", "trello", "jira", "worktree", "confluence"}
```

(b) Around lines 78-99 — extend the integration dicts:
```python
_INTEGRATION_CRED_FIELDS = {
    # ... existing ...
    "confluence": ["base_url", "email", "api_token", "personal_access_token"],
}
_INTEGRATION_SYNC_PREFIX = {
    # ... existing ...
    "confluence": "sync.confluence",
}
_INTEGRATION_SYNC_FIELDS = {
    # ... existing ...
    "confluence": ["enabled"],   # read-only — no auto_sync
}
```

(c) Near the integration dispatch loop (around lines 335-338), add:
```python
from installer.flow.integration_config import configure_confluence

_INTEGRATION_CONFIGURERS = [
    # ... existing entries ...
    ("confluence", configure_confluence),
]
```

(Exact surrounding code varies — follow the existing shape. Goal: confluence dispatches to `configure_confluence` when selected.)

(d) If there's a `_PROJ_PLUGINS` set in `installer/flow/wizard.py` (around line 23), add `"confluence"`:
```python
_PROJ_PLUGINS = {"proj", "router", "todoist", "trello", "jira", "confluence"}
```

- [ ] **Step 4: Wizard smoke test**

Run (don't actually enter data — just check it starts cleanly):
```bash
cd /home/raul/worktrees/cpm/feat-686-confluence-plugin && python3 -c "
from installer.flow.installer_flow import _WIZARD_PLUGINS
assert 'confluence' in _WIZARD_PLUGINS
print('confluence registered:', 'confluence' in _WIZARD_PLUGINS)
"
```

Expected: `confluence registered: True`.

- [ ] **Step 5: Commit**

```bash
git add installer/flow/integration_config.py installer/flow/installer_flow.py installer/flow/wizard.py
git commit -m "feat(installer): configure_confluence wizard flow + dispatch"
```

---

### Task 28: Defaults + legacy wizard parity

**Files:**
- Modify: `installer/defaults.yaml`
- Modify: `installer/wizard.py` (legacy rich-wizard)

- [ ] **Step 1: Update `installer/defaults.yaml`**

In `installer/defaults.yaml`, find the `sync:` block (around lines 55-70) and add:
```yaml
sync:
  # ... existing todoist/trello/jira ...
  confluence:
    enabled: false
```

Note: NO `auto_sync` key — confluence is read-only, no hooks to gate.

- [ ] **Step 2: Update legacy `installer/wizard.py`**

In `installer/wizard.py` around line 606, locate `proj_plugins` set and add `"confluence"`:
```python
proj_plugins = {"proj", "router", "todoist", "trello", "jira", "confluence"}
```

- [ ] **Step 3: Verify defaults load cleanly**

Run:
```bash
python3 -c "
import yaml
d = yaml.safe_load(open('installer/defaults.yaml'))
assert 'confluence' in d['sync']
assert d['sync']['confluence']['enabled'] is False
print('ok')
"
```

Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
git add installer/defaults.yaml installer/wizard.py
git commit -m "feat(installer): confluence defaults + legacy wizard parity"
```

---

### Task 29: Plugin README

**Files:**
- Create: `plugins/confluence/README.md`

- [ ] **Step 1: Write README**

Create `plugins/confluence/README.md`:
```markdown
# Confluence Plugin

Read-only Confluence integration for `claude-project-manager`. MCP server + 6 skills.

## Features

- Search (CQL or free text)
- Get page by id or (space_key + title)
- List spaces + pages in space
- Descendant page tree
- Attachments + comments (footer + inline)
- Markdown conversion from Confluence `view` HTML

## Supported Deployments

- **Confluence Cloud** — Basic auth (email + API token)
- **Confluence Server / Data Center** — Bearer auth (Personal Access Token)

## Install + Configure

1. Run the `cpm` installer and select `confluence` in the plugin list.
2. Wizard prompts for:
   - Deployment (`cloud | server | auto`)
   - Base URL
   - Creds (email + API token for Cloud; PAT for Server)
   - Optional: allowed space keys (comma-separated; empty = all)
3. Wizard validates with a `GET /space?limit=1` call and writes `~/.claude/confluence.yaml`.

Upgrade path for existing installs: re-run `cpm` — it detects confluence missing and prompts.

## Skills

| Skill | Purpose |
|-------|---------|
| `/confluence:search` | Search content (CQL or text) |
| `/confluence:page` | Fetch a page as markdown |
| `/confluence:spaces` | List spaces |
| `/confluence:pages` | List pages in a space |
| `/confluence:tree` | Descendant-page tree |
| `/confluence:metadata` | Attachments + comments for a page |

## Config (`~/.claude/confluence.yaml`)

```yaml
deployment: auto                         # auto | cloud | server
base_url: https://example.atlassian.net
# Cloud
email: you@example.com
api_token: <secret>
# Server
personal_access_token: <secret>
# Optional
allowed_spaces: []                       # empty = all
rate_limit_per_10s: 10
default_max_results: 25
max_results_cap: 100
timeout_seconds: 30
```

Env-var overrides (highest precedence): `CONFLUENCE_CONFIG`, `CONFLUENCE_BASE_URL`, `CONFLUENCE_EMAIL`, `CONFLUENCE_API_TOKEN`, `CONFLUENCE_PAT`.

## Limitations

- API v1 only on both deployments (Cloud v2 not supported due to CQL + comment + space-id gaps).
- Live-updating macros (recently-updated, inline search) render as empty divs — no markdown.
- No local caching — every call hits the API.

## Troubleshooting

| Error | Fix |
|-------|-----|
| 401/403 | Re-run `cpm` wizard; verify token scopes |
| 429 | Lower `rate_limit_per_10s` in yaml; wait for `Retry-After` |
| Space not allowed | Add the key to `allowed_spaces` in yaml, or clear `allowed_spaces` |

## Uninstall

`claude plugin uninstall confluence@claude-project-manager` removes the plugin cache. Delete `~/.claude/confluence.yaml` manually for a clean slate.
```

- [ ] **Step 2: Commit**

```bash
git add plugins/confluence/README.md
git commit -m "docs(confluence): plugin README"
```

---

### Task 30: Root README + CLAUDE.md updates

**Files:**
- Modify: root `README.md`
- Modify: root `CLAUDE.md`

- [ ] **Step 1: Add confluence rows to README skill table**

In root `README.md`, find the skills reference table and add (preserve alphabetical ordering within "Integrations" category):
```markdown
| `/confluence:search` | Search Confluence content via CQL or text |
| `/confluence:page` | Fetch Confluence page as markdown |
| `/confluence:spaces` | List Confluence spaces |
| `/confluence:pages` | List pages in a Confluence space |
| `/confluence:tree` | Fetch descendant page tree |
| `/confluence:metadata` | Attachments + comments for a page |
```

Also add confluence to the "Skills by category" list under "Integrations".

- [ ] **Step 2: Add confluence to CLAUDE.md plugin list**

In root `CLAUDE.md`, find the "Overview" section's plugin list and add:
```markdown
- `confluence` — read-only Confluence (Cloud + Server/DC) search + page fetch via REST API
```

- [ ] **Step 3: Add port 19108 row to CLAUDE.md port table**

In root `CLAUDE.md`, find the "Port assignments" table and add a row:
```markdown
| confluence | 19108 |
```

Insert under zoxide=19107 to preserve ordering.

- [ ] **Step 4: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "docs: add confluence to root README + CLAUDE.md port table"
```

---

### Task 31: Full suite run + coverage check

**Files:** (no new files)

- [ ] **Step 1: Run full confluence test suite**

Run:
```bash
cd plugins/confluence/server && uv run pytest
```

Expected: ALL PASS. Coverage ≥ 80%. Failures → fix in place before proceeding.

- [ ] **Step 2: Run _shared test suite (regression check)**

Run:
```bash
cd plugins/_shared && uv run pytest
```

Expected: ALL PASS.

- [ ] **Step 3: Run installer test suite**

Run:
```bash
cd /home/raul/worktrees/cpm/feat-686-confluence-plugin && uv run pytest installer/tests
```

Expected: ALL PASS.

- [ ] **Step 4: Boot the confluence server manually**

Run:
```bash
cd plugins/confluence/server && timeout 3 uv run confluence-server || echo "exit OK"
```

Expected: starts cleanly, listens on socket + 19108, exits on timeout.

- [ ] **Step 5: Lint + type check**

Run:
```bash
cd plugins/confluence/server && uv run ruff check . && uv run basedpyright
```

Expected: no errors.

- [ ] **Step 6: If all green, mark integration complete**

No commit — this is a verification step. If any step fails, fix + re-run the suite.

---

### Task 32: Self-review against spec

- [ ] **Step 1: Spec coverage check**

Re-read `docs/superpowers/specs/2026-04-21-confluence-plugin-design.md` section by section. For each item, confirm there's a task covering it:

| Spec section | Task(s) |
|--------------|---------|
| Plugin layout + directory | T1 |
| Config schema | T5 |
| Deployment detection | T8 |
| Port 19108 | T3, T30 |
| MCP tool surface (8 tools) | T10–T17 |
| Cross-cutting behaviors (allowed_spaces, pagination, rate limit) | T6, T8, T11, T12 |
| Skill layer (6 skills) | T20–T25 |
| Installer + wizard | T26, T27, T28 |
| Markdown conversion | T7 |
| Error hierarchy | T4 |
| Testing (unit + contract + e2e) | T10–T19 |
| Docs | T29, T30 |
| Acceptance criteria | T31 |

If any spec item lacks a task, add a task inline and re-run this checklist.

- [ ] **Step 2: Placeholder scan**

Search this plan file for red flags:
```bash
grep -n "TBD\|TODO\|implement later\|fill in\|similar to Task\|add appropriate" docs/superpowers/plans/2026-04-21-confluence-plugin.md
```

Expected: no hits (or only within planned test strings that legitimately use "TODO" as part of tested content).

- [ ] **Step 3: Type consistency**

Scan method + field names across tasks:
- `ConfluenceClient.get()` — signature consistent across Tasks 8, 11, 12, 13, 14, 15, 16, 17 ✓
- `check_space_allowed(space_key)` — used in Tasks 8, 11, 12, 14 ✓
- `html_to_markdown(html)` — used in Tasks 7, 12, 17 ✓
- Envelope fields `results`, `count`, `next_start` — consistent in all list tools ✓
- `ConfluenceConfig` fields — consistent between Tasks 5, 8 ✓

If a mismatch surfaces, fix inline.

- [ ] **Step 4: (No commit — review step only)**

---

## Execution notes

- Every task runs from the worktree root: `/home/raul/worktrees/cpm/feat-686-confluence-plugin/`.
- Python commands run in `plugins/confluence/server/` use `uv run` (venv-aware).
- Each task ends with a single commit. Rebase or squash at merge time if preferred.
- Tests MUST run green before moving on — no leaving red tests.
- The final merge to `dev` should be preceded by a full test + lint run (Task 31).

---

## Post-plan handoff

After execution completes, follow up with:
1. `superpowers:finishing-a-development-branch` — decide merge vs PR (convention: FF-merge to `dev`, push, watch CI).
2. Mark todo 686 as complete via `mcp__plugin_proj_proj__todo_complete`.
