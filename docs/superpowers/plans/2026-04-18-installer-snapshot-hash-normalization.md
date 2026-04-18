# Installer Snapshot Hash Normalization Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the flaky snapshot tests in `installer/tests/e2e/test_snapshots_main.py` by normalizing the non-deterministic `terminal-<hash>-` CSS class prefix that Rich/Textual injects into every SVG.

**Architecture:** Single-task plan. Add a `_normalize_svg(svg)` helper in `installer/tests/e2e/test_snapshots.py` that runs `re.sub(r'terminal-\d+-', 'terminal-XXX-', svg)` before writing/comparing goldens. Regenerate all goldens with `SNAPSHOT_UPDATE=1`. Add 1 invariant test that proves normalization is stable across runs.

**Tech Stack:** Python 3.13, pytest, Rich/Textual SVG rendering, `re.sub`.

**Predicates:**
- Worktree: `/home/raul/worktrees/cpm/fix-installer-snapshot-hash-flake`, branch `fix/installer-snapshot-hash-flake`.
- Baseline: `cd installer && uv run pytest tests/e2e/test_snapshots_main.py -q --no-cov` currently reports 7–14 failures depending on run (non-deterministic).

**Test-sweep commands:**
```bash
cd installer && uv run pytest -q --no-cov          # full installer suite
cd installer && uv run ruff check . && uv run ruff format --check .
cd installer && uv run basedpyright installer/ tests/
```

---

## Task 1: Normalize terminal-<hash>- prefix in snapshot compare

**Files:**
- Modify: `installer/tests/e2e/test_snapshots.py` (add helper + use in `_assert_snapshot`)
- Regenerate: every `*.svg` under `installer/tests/e2e/snapshots/` (via `SNAPSHOT_UPDATE=1`)
- Delete: every `*_actual.svg` under `installer/tests/e2e/snapshots/` (diagnostic leftovers from failed runs)
- Test: add `test_snapshot_hash_normalization` in `installer/tests/e2e/test_snapshot_helper_guard.py` (or a new file if that one is out of scope)

**Why regenerate all goldens:** after normalization, the golden-on-disk must match the normalized form (`terminal-XXX-`). Existing goldens have the random hash baked in, so they'd never match.

- [ ] **Step 1: Write a failing invariant test**

Add to `installer/tests/e2e/test_snapshot_helper_guard.py` (append; do not rewrite):

```python
from installer.tests.e2e.test_snapshots import _normalize_svg


def test_normalize_svg_collapses_terminal_hash_prefix() -> None:
    """Two renders of the same screen differ only in the random terminal-<hash>- prefix.

    After normalization they must be byte-equal, so snapshot compares are stable.
    """
    svg_a = '<svg class="rich-terminal">.terminal-12345-r1 { fill: #abc }</svg>'
    svg_b = '<svg class="rich-terminal">.terminal-67890-r1 { fill: #abc }</svg>'
    assert _normalize_svg(svg_a) == _normalize_svg(svg_b)


def test_normalize_svg_preserves_all_other_content() -> None:
    """Normalization only touches the terminal-<digits>- prefix, nothing else."""
    svg = '<svg><text x="10" y="20">hello</text></svg>'
    assert _normalize_svg(svg) == svg


def test_normalize_svg_replaces_every_occurrence() -> None:
    """Every .terminal-<hash>- occurrence in the SVG must be replaced, not just the first."""
    svg = (
        '<svg>'
        '.terminal-111-matrix { }'
        '.terminal-111-r1 { }'
        '.terminal-111-r2 { }'
        '</svg>'
    )
    norm = _normalize_svg(svg)
    assert "terminal-111-" not in norm
    assert norm.count("terminal-XXX-") == 3
```

- [ ] **Step 2: Run — expect FAIL (module `_normalize_svg` missing)**

Run: `cd installer && uv run pytest tests/e2e/test_snapshot_helper_guard.py::test_normalize_svg_collapses_terminal_hash_prefix tests/e2e/test_snapshot_helper_guard.py::test_normalize_svg_preserves_all_other_content tests/e2e/test_snapshot_helper_guard.py::test_normalize_svg_replaces_every_occurrence -v --no-cov`

Expected: `ImportError: cannot import name '_normalize_svg' from 'installer.tests.e2e.test_snapshots'`.

- [ ] **Step 3: Add `_normalize_svg` helper + wire it into `_assert_snapshot`**

Edit `installer/tests/e2e/test_snapshots.py`:

At module level (near `_FORCE_UPDATE` / `_CREATE_MISSING` constants, around line 135), add:

```python
import re

_TERMINAL_HASH_RE = re.compile(r"terminal-\d+-")


def _normalize_svg(svg: str) -> str:
    """Replace the non-deterministic `terminal-<hash>-` prefix that Rich/Textual
    generates per-render with a stable placeholder, so snapshot compares are
    byte-exact across runs.

    Only the hash-prefixed CSS class names are touched; all other SVG content
    passes through unchanged.
    """
    return _TERMINAL_HASH_RE.sub("terminal-XXX-", svg)
```

Then update `_assert_snapshot` (around line 156) to apply the normalization before all write and read paths:

```python
def _assert_snapshot(svg: str, name: str) -> None:
    """Compare *svg* against the golden file ``<name>.svg``.

    Modes:
    - ``SNAPSHOT_UPDATE=1``: overwrite all goldens (regenerate baseline).
    - ``SNAPSHOT_CREATE_MISSING=1``: create only missing goldens, compare existing.
    - Default: hard-fail on missing, exact-match on existing.

    The SVG is normalized before compare/write via `_normalize_svg` so that
    Rich's non-deterministic ``terminal-<digits>-`` CSS class prefix doesn't
    cause spurious mismatches between runs.
    """
    normalized = _normalize_svg(svg)
    golden = _SNAPSHOT_DIR / f"{name}.svg"
    if _FORCE_UPDATE:
        golden.write_text(normalized, encoding="utf-8")
        return
    if not golden.exists():
        if _CREATE_MISSING:
            golden.write_text(normalized, encoding="utf-8")
            return
        pytest.fail(
            f"Golden file missing for {name!r}: {golden}. "
            f"Run with SNAPSHOT_UPDATE=1 to generate."
        )
    expected = golden.read_text(encoding="utf-8")
    if normalized != expected:
        actual_path = _SNAPSHOT_DIR / f"{name}_actual.svg"
        actual_path.write_text(normalized, encoding="utf-8")
        pytest.fail(
            f"Snapshot mismatch for {name!r}. "
            f"Actual saved to {actual_path}. "
            f"Run with SNAPSHOT_UPDATE=1 to accept changes."
        )
```

- [ ] **Step 4: Run the 3 helper tests — expect PASS**

Run: `cd installer && uv run pytest tests/e2e/test_snapshot_helper_guard.py -v --no-cov`

Expected: all 3 new tests pass (plus any other existing tests in that file — do not regress).

- [ ] **Step 5: Regenerate all snapshot goldens**

```bash
cd /home/raul/worktrees/cpm/fix-installer-snapshot-hash-flake/installer
rm -f tests/e2e/snapshots/*_actual.svg          # drop diagnostic leftovers first
SNAPSHOT_UPDATE=1 uv run pytest tests/e2e/ --no-cov -q 2>&1 | tail -10
```

Expected: every snapshot test "passes" (since `_FORCE_UPDATE=1` writes goldens unconditionally). Check `git status --short tests/e2e/snapshots/` — you should see many modified `.svg` files (every golden now has `terminal-XXX-` instead of a random hash).

- [ ] **Step 6: Run the full snapshot suite twice to prove stability**

```bash
cd /home/raul/worktrees/cpm/fix-installer-snapshot-hash-flake/installer
uv run pytest tests/e2e/test_snapshots_main.py -q --no-cov 2>&1 | tail -5
uv run pytest tests/e2e/test_snapshots_main.py -q --no-cov 2>&1 | tail -5
```

Expected: both runs report the same pass count (no flakes). If run 2 shows any failure that run 1 didn't, the normalization has gaps — investigate.

- [ ] **Step 7: Run the full installer suite**

```bash
cd /home/raul/worktrees/cpm/fix-installer-snapshot-hash-flake/installer && uv run pytest -q --no-cov 2>&1 | tail -5
```

Expected: all pass (no regressions). If any test outside `tests/e2e/` fails, it's unrelated to this plan — flag as a concern, do not fix here.

- [ ] **Step 8: Lint + typecheck**

```bash
cd /home/raul/worktrees/cpm/fix-installer-snapshot-hash-flake/installer
uv run ruff check .
uv run ruff format --check .
uv run basedpyright installer/ tests/
```

Expected: all green.

- [ ] **Step 9: Commit**

```bash
cd /home/raul/worktrees/cpm/fix-installer-snapshot-hash-flake
# Stage only the specific files you changed + the regenerated goldens under snapshots/
git add installer/tests/e2e/test_snapshots.py \
        installer/tests/e2e/test_snapshot_helper_guard.py \
        installer/tests/e2e/snapshots/
# Verify no stray files (e.g. _actual.svg diagnostic leftovers) are staged:
git status --short | grep actual.svg && echo "WARN: _actual.svg still staged — unstage + rm first" || echo "clean"
git commit -m "fix(installer/snapshots): normalize rich terminal-<hash>- prefix to stop snapshot flake

The snapshot helper did byte-exact compares against SVG output, but Rich/Textual
inject a random integer hash into every terminal's CSS class prefix
(e.g. '.terminal-3325053476-r1'). The hash changes every render, so two runs of
the same test produce different SVGs even though the rendered pixels are identical.

Fix: strip the '.terminal-<digits>-' prefix to 'terminal-XXX-' before write +
compare. All 20+ goldens regenerated under the new normalized form.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 10: Verify the commit is clean**

`git show HEAD --stat | head -10` — confirm only the expected files are touched. Then `git show HEAD --name-only | grep -v "installer/tests/e2e/"` — should return empty (every file should be under `installer/tests/e2e/`).

## Implementer notes

- **Regenerate goldens ONCE.** Do not run `SNAPSHOT_UPDATE=1` in a loop or repeatedly — each run writes the goldens atomically, and repeated writes shouldn't change content after normalization is wired in, but keep it to one authoritative regeneration for a clean diff.
- **Do NOT delete existing `.svg` goldens** before `SNAPSHOT_UPDATE=1`. The pytest command overwrites them in place — manual rm beforehand can leave orphans if a test no longer runs (unlikely here but keep the idiom safe).
- **The `_actual.svg` files are diagnostic leftovers** written only when a test fails mid-comparison. Remove them before committing so they don't clutter the tree.
- **If a test that was passing now fails after normalization** (shouldn't happen, since normalization is idempotent on already-stable content), the golden content itself has semantic drift — investigate the specific test. Do not blindly re-run `SNAPSHOT_UPDATE=1` to paper over it.
