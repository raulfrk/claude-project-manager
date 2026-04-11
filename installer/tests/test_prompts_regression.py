"""AST-based regression guard for Console.print(file=...) misuse.

Rich's `Console.print()` does not accept a `file=` kwarg — passing it raises
`TypeError` at runtime (see todo 516 for the original bug). Plain regex cannot
distinguish forbidden `Console.print(..., file=...)` from legitimate builtin
`print(..., file=sys.stderr)`, so this guard walks the AST of every installer
source file and flags only the former.

The walker also leaves `Console(file=...)` constructor calls alone — those are
a supported Rich API for redirecting a Console's output sink (used e.g. in
test fixtures with `Console(file=StringIO(...))`).
"""

from __future__ import annotations

import ast
from pathlib import Path


def _collect_console_names(tree: ast.Module) -> set[str]:
    """Return names bound at module level to `Console(...)` instances."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        value = node.value
        if not (isinstance(value, ast.Call) and isinstance(value.func, ast.Name)):
            continue
        if value.func.id != "Console":
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                names.add(target.id)
    return names


def test_no_console_print_file_kwarg_in_installer() -> None:
    installer_root = Path(__file__).parent.parent
    offenders: list[tuple[str, int]] = []
    for path in installer_root.rglob("*.py"):
        parts = path.parts
        if "__pycache__" in parts or "tests" in parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        console_names = _collect_console_names(tree)
        # Common receiver names used for stderr/stdout Consoles; the walker
        # checks attribute-call receivers against this set plus any name
        # bound to a module-level `Console(...)` assignment.
        receivers = console_names | {"console", "_err", "_out", "err_console"}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr == "print"):
                continue
            receiver = func.value
            if not isinstance(receiver, ast.Name):
                continue
            if receiver.id not in receivers:
                continue
            if any(kw.arg == "file" for kw in node.keywords):
                offenders.append((str(path.relative_to(installer_root)), node.lineno))
    assert not offenders, (
        "Console.print(file=...) is forbidden — Rich Console.print does not "
        f"accept file=. Offenders: {offenders}"
    )
