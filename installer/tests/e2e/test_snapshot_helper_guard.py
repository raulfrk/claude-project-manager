"""AST-based regression guard for `_expand_collapsible` helper.

Ensures the helper in `test_snapshots_advanced.py` remains `async def` and
that every call site is wrapped in `await`. A line may opt out with a
trailing `# noqa: no-settle` token.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_TARGET = Path(__file__).parent / "test_snapshots_advanced.py"
_OPT_OUT_TOKEN = "# noqa: no-settle"


def _parse_target() -> tuple[ast.Module, list[str]]:
    source = _TARGET.read_text()
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        pytest.fail(f"Failed to parse {_TARGET}: {exc}")
    return tree, source.splitlines()


def test_expand_collapsible_helper_is_async() -> None:
    tree, _ = _parse_target()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.AsyncFunctionDef)
            and node.name == "_expand_collapsible"
        ):
            return
        if isinstance(node, ast.FunctionDef) and node.name == "_expand_collapsible":
            pytest.fail(
                "_expand_collapsible is defined as `def` but must be `async def` "
                "so _settle runs on every call site."
            )
    pytest.fail("_expand_collapsible is not defined in test_snapshots_advanced.py")


def test_no_unsettled_expand_collapsible() -> None:
    tree, lines = _parse_target()

    parent_map: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parent_map[child] = parent

    violations: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Name) and func.id == "_expand_collapsible"):
            continue
        parent = parent_map.get(node)
        if isinstance(parent, ast.Await):
            continue
        line_index = node.lineno - 1
        if 0 <= line_index < len(lines):
            line = lines[line_index].rstrip()
            if line.endswith(_OPT_OUT_TOKEN):
                continue
        violations.append(node.lineno)

    if violations:
        pytest.fail(
            "Unsettled `_expand_collapsible(...)` calls (not wrapped in `await`) "
            f"at lines: {violations}. Prefix with `await` or append "
            f"`{_OPT_OUT_TOKEN}` to opt out."
        )


# ---------------------------------------------------------------------------
# _normalize_svg helper guard
# ---------------------------------------------------------------------------


from installer.tests.e2e.test_snapshots import _normalize_svg  # noqa: E402


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
    svg = "<svg>.terminal-111-matrix { }.terminal-111-r1 { }.terminal-111-r2 { }</svg>"
    norm = _normalize_svg(svg)
    assert "terminal-111-" not in norm
    assert norm.count("terminal-XXX-") == 3
