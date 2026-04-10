# Installer E2E Tests

End-to-end tests for the `cpm-install` TUI installer. Runs inside a Docker
container so host state (Python venv, Node.js, uv, Claude CLI) does not
influence results, and so CI and local runs stay in lockstep.

## Overview

This suite exercises the installer end-to-end:

- **TUI screens** — drives the Textual installer, asserts screen transitions,
  field validation, and focus management (`test_install_flow.py`,
  `test_edge_cases.py`, `test_uninstall_wizard.py`, `test_update_flows.py`).
- **Snapshot goldens** — captures each TUI screen as a frozen `.svg` golden
  and diffs against it on future runs (`test_snapshots.py`, `snapshots/`).
- **Integration flow** — boots the installer against a fresh `$HOME` and
  asserts the resulting `~/.claude/` layout, plugin marketplace state, and
  sandbox `settings.json` output (`test_integration_flow.py`).

The Docker image provides Python 3.12, Node.js LTS, git, the Claude CLI
(`@anthropic-ai/claude-code`), and a uv-managed venv preinstalled at
`/opt/venv`. Source code is **not** baked into the image — it is
bind-mounted at runtime.

## Running locally

Use the runner script from any location in the repo:

```bash
./installer/tests/e2e/run.sh                                 # run everything
./installer/tests/e2e/run.sh installer/tests/e2e/test_snapshots.py
./installer/tests/e2e/run.sh -k test_install_flow -x         # pytest args forwarded
```

The script:

1. `cd`s to the repo root via `git rev-parse --show-toplevel`.
2. Builds (or cache-hits) `cpm-e2e:latest` from
   `installer/tests/e2e/Dockerfile`.
3. `docker run`s the image with narrow bind-mounts matching CI and
   `--user $(id -u):$(id -g)` so writes on the host stay owned by you.

All trailing arguments are forwarded to `pytest` inside the container.

### Environment variables

| Var | Effect |
|-----|--------|
| `SNAPSHOT_CREATE_MISSING=1` | Create goldens for any snapshot that doesn't have one yet. Existing goldens are left alone. |
| `SNAPSHOT_UPDATE=1` | Regenerate **all** snapshot goldens. Review the diff before committing. |

## Regenerating goldens

### Locally

```bash
# Seed only the missing ones (safe):
SNAPSHOT_CREATE_MISSING=1 ./installer/tests/e2e/run.sh

# Regenerate everything (review the diff!):
SNAPSHOT_UPDATE=1 ./installer/tests/e2e/run.sh
```

The runner bind-mounts `installer/tests/e2e/snapshots/` read-write, so new
goldens land on the host tree directly and can be `git add`ed.

### In CI

The `test-installer-e2e` job in `.github/workflows/ci.yml` supports manual
regeneration via `workflow_dispatch`:

1. Open the Actions tab, select the CI workflow, click **Run workflow**.
2. Set the `regenerate_snapshots` input to `true`.
3. The job runs with `SNAPSHOT_UPDATE=1`, commits the new goldens as the
   `github-actions[bot]` user, and pushes back to the branch with
   `[skip ci]`.

On normal pushes the job runs with `SNAPSHOT_CREATE_MISSING=1`, which only
fills in goldens for brand-new snapshots and never overwrites existing ones.

## Cache strategy

The Dockerfile and ci.yml deliberately avoid the naive `COPY . .` pattern.
Here's why.

### Why no `COPY . .`

Previously the image copied the entire repo in. Every source change
invalidated the image layer, so CI (and local `docker build`) had to
reinstall all Python and apt dependencies on every run. With a bind-mount,
the image only contains the toolchain and the pre-installed venv; source
comes in fresh at `docker run` time. Rebuilds are now triggered only by
changes to `Dockerfile`, `pyproject.toml`, or `uv.lock`.

### Why `/opt/venv`

The runtime bind-mount lands at `/app`. If the venv lived at `/app/.venv`
(the uv default), the bind-mount would **shadow it** — the container would
see the host's (possibly missing or wrong-arch) `.venv`, not the one
installed at build time. Pinning the venv to `/opt/venv` via
`UV_PROJECT_ENVIRONMENT=/opt/venv` and then setting `VIRTUAL_ENV` +
`PATH=/opt/venv/bin:$PATH` keeps it safely outside the bind-mount.

### Why narrow bind-mounts in ci.yml

The CI job mounts each source path explicitly:

```yaml
-v ${{ github.workspace }}/installer:/app/installer
-v ${{ github.workspace }}/plugins:/app/plugins
-v ${{ github.workspace }}/pyproject.toml:/app/pyproject.toml:ro
-v ${{ github.workspace }}/uv.lock:/app/uv.lock:ro
-v ${{ github.workspace }}/installer/tests/e2e/snapshots:/app/installer/tests/e2e/snapshots
```

rather than `-v ${{ github.workspace }}:/app`. Narrow mounts:

- Prevent `.git/`, `node_modules/`, `.venv/`, editor files, and other
  workspace junk from leaking into the container.
- Make the container's view of the source deterministic: it only sees what
  the tests actually need.
- Keep `pyproject.toml`/`uv.lock` read-only so a runaway `uv sync` inside
  the container cannot corrupt the host lockfile.

`run.sh` mirrors this exact mount set so local runs match CI byte-for-byte.

### Why `--user $(id -u):$(id -g)`

Without it, containerized pytest writes snapshot files as root on the
bind-mounted host tree. On the CI runner this breaks the subsequent
`git add installer/tests/e2e/snapshots/` step (can't index root-owned
files). Locally it leaves files you need `sudo` to delete. Running as the
host UID/GID sidesteps the issue entirely.

### Why `.dockerignore` still matters

Even with the bind-mount strategy, `docker build` still sends a build
context to the daemon. The root-level `.dockerignore` keeps that context
small (no `.git/`, no `node_modules/`, no caches). It does **not** affect
the runtime bind-mounts — narrow mounts in ci.yml/`run.sh` are what
enforce runtime isolation. See the header comment in `.dockerignore` for
details.

## Troubleshooting

### Stale buildx cache

If CI picks up a cache from an older Dockerfile and the dep-install layer
looks wrong, the cache key in ci.yml is
`buildx-e2e-${{ hashFiles('installer/tests/e2e/Dockerfile', 'pyproject.toml', 'uv.lock') }}`.
Any change to those three files produces a fresh key. Locally, force a
clean build with:

```bash
docker build --no-cache -f installer/tests/e2e/Dockerfile -t cpm-e2e:latest .
```

### Host venv pollution

If you see errors like `ModuleNotFoundError` for packages you know are
installed, check that no `plugins/*/server/.venv/` directories exist on
your host — the plugins bind-mount drags them into the container and they
can shadow `/opt/venv`. CI cleans these up explicitly:

```bash
find plugins -type d -name .venv -prune -exec rm -rf {} +
```

Run the same command locally before `./run.sh` if needed.

### UID/GID permission issues on bind-mount writes

If tests fail writing to `snapshots/`, `actuals/`, or `diff_report/`:

- Make sure you're using `run.sh` (it sets `--user`) rather than a raw
  `docker run`.
- On Linux, confirm your UID is the owner of those directories:
  `ls -ld installer/tests/e2e/snapshots`.
- If you previously ran tests as root, clean up:
  `sudo chown -R $(id -u):$(id -g) installer/tests/e2e/{snapshots,actuals,diff_report}`.

### Podman

Podman is out of scope for this suite. `run.sh` hard-codes `docker` and
the CI job uses `docker/build-push-action`. Podman's rootless UID mapping
also interacts differently with `--user` and bind-mounts, so the
permission guarantees above do not automatically carry over. If you need
Podman support, raise a new todo.
