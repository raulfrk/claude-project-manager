# Development Guide

Guide for developing and contributing to claude-project-manager.

---

## Prerequisites

- **Python** >= 3.12
- **uv** -- Python package manager (replaces pip/poetry)
- **git** -- Version control
- **basedpyright** -- Strict type checker (installed as dev dependency)
- **ruff** -- Linter and formatter (installed as dev dependency)

Optional:
- **zoxide** -- Required if developing/testing the zoxide plugin
- Todoist API token -- Required for todoist plugin testing
- Trello API key/token -- Required for trello plugin testing
- Jira credentials -- Required for jira plugin testing

---

## Dev Setup

Each plugin with an MCP server has its own Python environment managed by uv.

```console
# Clone the repository
git clone https://github.com/raulfrk/claude-project-manager.git
cd claude-project-manager

# Install dependencies for each plugin
cd plugins/sandbox/server && uv sync && cd -
cd plugins/worktree/server && uv sync && cd -
cd plugins/proj/server && uv sync && cd -
cd plugins/router/server && uv sync && cd -
cd plugins/todoist/server && uv sync && cd -
cd plugins/trello/server && uv sync && cd -
cd plugins/jira/server && uv sync && cd -
cd plugins/zoxide/server && uv sync && cd -

# Install shared dependency dev deps
cd plugins/_shared && uv sync && cd -
```

Each `uv sync` creates a `.venv` in the plugin's `server/` directory and installs all dependencies including the shared `claude-hook-transport` package via path reference.

---

## Project Structure

```
claude-project-manager/
  .claude-plugin/
    marketplace.json            # Plugin registry (versions, descriptions)
  CLAUDE.md                     # Project conventions and architecture notes
  README.md                     # User-facing documentation
  CHANGELOG.md                  # Release history
  docs/                         # Detailed documentation
    architecture.md             # System architecture
    plugins.md                  # Plugin reference
    development.md              # This file
  plugins/
    _shared/                    # Shared library: claude-hook-transport
      hook_dispatch/            # Post-execution hook dispatch wrapper
        dispatch.py
      hook_transport/           # Dual-transport HTTP client
        dual_transport.py
        http_hook_handler.py
      pyproject.toml
      tests/
    sandbox/
      .claude-plugin/plugin.json
      .mcp.json
      server/
        pyproject.toml
        server/                 # Python package
          main.py               # FastMCP entry point
          lib/                  # Library code
          tools/                # MCP tool implementations
            settings.py
        tests/
    worktree/                   # Same structure as sandbox
    proj/                       # Same structure, plus:
      skills/                   # Skill definitions
        <skill-name>/SKILL.md
      hooks/                    # Hook definitions
        hooks.json
    hooks/                      # Same structure as sandbox
    todoist/                    # Same structure as sandbox
    trello/                     # Same structure as sandbox
    jira/                       # Same structure as sandbox
    zoxide/                     # Same structure as sandbox
    analyse/                    # Skills-only (no server/)
      skills/review/SKILL.md
```

### Key Directories

- `plugins/<name>/server/server/` -- The inner `server/` is the Python package (importable as `server.*`)
- `plugins/<name>/server/server/tools/` -- MCP tool implementations, one file per domain
- `plugins/<name>/server/server/lib/` -- Shared library code (models, storage, config)
- `plugins/<name>/server/tests/` -- pytest test files
- `plugins/<name>/skills/<skill>/SKILL.md` -- Skill instruction files with YAML frontmatter

---

## Running Tests

Each plugin has its own test suite. Tests run with pytest and pytest-xdist for parallelism.

```console
# Run a specific plugin's tests
cd plugins/proj/server && uv run pytest -q
cd plugins/worktree/server && uv run pytest -q
cd plugins/sandbox/server && uv run pytest -q
cd plugins/router/server && uv run pytest -q
cd plugins/todoist/server && uv run pytest -q
cd plugins/trello/server && uv run pytest -q
cd plugins/jira/server && uv run pytest -q
cd plugins/zoxide/server && uv run pytest -q

# Run shared library tests
cd plugins/_shared && uv run pytest -q

# Run with coverage report
cd plugins/proj/server && uv run pytest --cov=server --cov-report=html

# Run a specific test file
cd plugins/proj/server && uv run pytest tests/test_todos.py -q

# Run tests matching a pattern
cd plugins/proj/server && uv run pytest -k "test_todoist" -q
```

### Test Configuration

Each plugin's `pyproject.toml` configures pytest:
- `testpaths = ["tests"]`
- `-n auto` for parallel execution via pytest-xdist
- `--cov-fail-under` sets minimum coverage thresholds (typically 72-80%)
- `--tb=short` for concise tracebacks

### Test Dependencies

Common test dependencies across plugins:
- `pytest` >= 8.0
- `pytest-cov` >= 7.0
- `pytest-xdist` >= 3.5
- `pytest-asyncio` >= 0.23
- `pytest-mock` >= 3.14
- `hypothesis` >= 6.100 (property-based testing)
- `freezegun` >= 1.5 (time mocking)

---

## Code Style

### Type Checking: basedpyright

All plugins use basedpyright in strict mode:

```toml
[tool.basedpyright]
typeCheckingMode = "strict"
pythonVersion = "3.12"
```

Run type checking:

```console
cd plugins/proj/server && uv run basedpyright
```

Key rules:
- No `Any` or `object` types -- use concrete types everywhere
- All function parameters and return types must be annotated
- Strict generic type checking enabled

### Linting: ruff

All plugins use ruff with a consistent configuration:

```toml
[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["F", "E", "W", "I", "B", "C4", "UP", "SIM", "RUF", "TCH", "PTH", "S"]
ignore = ["S603", "S607"]
```

Run the linter:

```console
cd plugins/proj/server && uv run ruff check
cd plugins/proj/server && uv run ruff check --fix  # auto-fix
```

Enabled rule sets:
- **F** -- Pyflakes
- **E/W** -- pycodestyle errors and warnings
- **I** -- isort (import sorting)
- **B** -- flake8-bugbear
- **C4** -- flake8-comprehensions
- **UP** -- pyupgrade
- **SIM** -- flake8-simplify
- **RUF** -- Ruff-specific rules
- **TCH** -- flake8-type-checking
- **PTH** -- flake8-use-pathlib
- **S** -- bandit security checks (S603/S607 ignored for subprocess usage)

### Additional Lint Tools

- **bandit** >= 1.7 -- Security analysis (available in `lint` dependency group)
- **pip-audit** >= 2.8 -- Dependency vulnerability scanning

---

## Version Bumping

When releasing a new version, three files must be updated together:

1. **`plugins/<name>/.claude-plugin/plugin.json`** -- The `version` field
2. **`plugins/<name>/server/pyproject.toml`** -- The `version` field under `[project]`
3. **`.claude-plugin/marketplace.json`** -- The `version` field for the plugin entry

All three must match. Forgetting one will cause inconsistencies.

### Current Versions

| Plugin | Version |
|--------|---------|
| sandbox | 0.2.0 |
| worktree | 2.6.0 |
| proj | 3.0.1 |
| hooks | 1.10.1 |
| todoist | 1.4.5 |
| trello | 2.4.3 |
| jira | 2.1.4 |
| zoxide | 1.3.1 |
| analyse | 1.0.0 |
| _shared | 0.3.3 |

---

## Adding a New Plugin

1. Create the directory structure under `plugins/<name>/`
2. Add `.claude-plugin/plugin.json` with metadata
3. Add `.mcp.json` for MCP server configuration (if applicable)
4. Create `server/pyproject.toml` with dependencies and tool config
5. Implement the server in `server/server/main.py`
6. Add tool implementations in `server/server/tools/`
7. Add tests in `server/tests/`
8. Register in `.claude-plugin/marketplace.json`
9. Add skill files in `skills/<skill-name>/SKILL.md` (if applicable)
10. Call `enable_hook_dispatch(mcp)` in `main.py` for hook integration

---

## Adding a New Skill

1. Create `plugins/<name>/skills/<skill-name>/SKILL.md`
2. Add YAML frontmatter with `name`, `description`, and optionally `context: fork` and `agent: general-purpose`
3. Write skill instructions in Markdown
4. Update the README skill reference table
5. Update the "Skills by category" list in the README

### Frontmatter Criteria for context/agent

Add `context: fork` and `agent: general-purpose` to skills that:
- Perform self-contained operations (list, sync, status)
- Do NOT require interactive Q&A during execution
- Do NOT need plan mode approval mid-execution

Do NOT add to interactive skills (define, init, load), sub-skills, or skills needing plan approval (execute, run, quick).

---

## Hook Development

To add hooks to a plugin:

1. Call `enable_hook_dispatch(mcp, exclude={...})` in `main.py` before `register()` calls
2. Create `default-hooks.yaml` in the plugin directory to define default hooks
3. Use `router_register_tool` or `/router:add` to register hooks
4. Test with `/router:test <hook-id>`

The `exclude` parameter should list meta-tools that should not trigger hooks.
