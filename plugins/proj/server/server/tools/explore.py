"""MCP tool for structured codebase exploration (no Bash required)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

_IGNORE_DIRS = {".git", "node_modules", "__pycache__", ".venv", ".tox", "dist", "build", ".mypy_cache", ".ruff_cache"}

_TECH_MARKERS: list[tuple[str, str]] = [
    ("pyproject.toml", "Python"),
    ("setup.py", "Python"),
    ("requirements.txt", "Python"),
    ("package.json", "Node/JavaScript"),
    ("tsconfig.json", "TypeScript"),
    ("Cargo.toml", "Rust"),
    ("go.mod", "Go"),
    ("pom.xml", "Java"),
    ("build.gradle", "Java/Kotlin"),
    ("justfile", "just (build)"),
    ("Makefile", "make (build)"),
    ("Dockerfile", "Docker"),
    ("docker-compose.yml", "Docker Compose"),
]

_ENTRY_POINT_NAMES = {
    "main.py", "app.py", "server.py", "cli.py",
    "main.ts", "index.ts", "app.ts",
    "main.go",
    "main.rs", "lib.rs",
    "index.js", "app.js",
}

_CONFIG_FILES = {
    "pyproject.toml", "setup.py", "setup.cfg",
    "package.json", "tsconfig.json",
    "Cargo.toml", "go.mod",
    "justfile", "Makefile",
    ".github",
}


def explore_codebase(path: str, max_files: int = 80) -> dict[str, object]:
    """Walk a directory and return structured exploration data.

    Returns::

        {
            "tech_stack": list[str],
            "entry_points": list[str],   # relative paths
            "key_dirs": list[str],        # top-level subdirectories
            "config_files": list[str],    # detected config file paths
            "file_types": dict[str, int], # extension → count
            "file_tree": list[str],       # up to max_files relative paths
            "arch_note": str,
        }
    """
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        return {"error": f"Path does not exist or is not a directory: {path}"}

    file_tree: list[str] = []
    file_types: dict[str, int] = {}
    tech_stack: list[str] = []
    entry_points: list[str] = []
    config_files: list[str] = []
    key_dirs: list[str] = []

    # Top-level directories (excluding ignored)
    for item in sorted(root.iterdir()):
        if item.is_dir() and item.name not in _IGNORE_DIRS:
            key_dirs.append(item.name)

    # Tech stack detection from root-level markers
    seen_stacks: set[str] = set()
    for marker, label in _TECH_MARKERS:
        candidate = root / marker
        if candidate.exists() and label not in seen_stacks:
            tech_stack.append(label)
            seen_stacks.add(label)
            config_files.append(marker)

    # Walk up to depth 4
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune ignored directories in-place
        dirnames[:] = [d for d in dirnames if d not in _IGNORE_DIRS]

        rel_dir = Path(dirpath).relative_to(root)
        depth = len(rel_dir.parts)
        if depth > 4:
            dirnames.clear()
            continue

        for filename in sorted(filenames):
            rel_file = rel_dir / filename if str(rel_dir) != "." else Path(filename)
            rel_str = str(rel_file)

            # File tree (capped)
            if len(file_tree) < max_files:
                file_tree.append(rel_str)

            # File type counts
            ext = Path(filename).suffix.lstrip(".").lower() or "no-ext"
            file_types[ext] = file_types.get(ext, 0) + 1

            # Entry points
            if filename in _ENTRY_POINT_NAMES:
                entry_points.append(rel_str)

    # Arch note synthesis
    arch_note = _synthesize_arch_note(root, tech_stack, key_dirs, entry_points)

    return {
        "tech_stack": tech_stack,
        "entry_points": entry_points,
        "key_dirs": key_dirs,
        "config_files": config_files,
        "file_types": dict(sorted(file_types.items(), key=lambda x: -x[1])[:20]),
        "file_tree": file_tree,
        "arch_note": arch_note,
    }


def _synthesize_arch_note(
    root: Path,
    tech_stack: list[str],
    key_dirs: list[str],
    entry_points: list[str],
) -> str:
    parts: list[str] = []
    if tech_stack:
        parts.append(f"Tech stack: {', '.join(tech_stack)}.")
    if key_dirs:
        shown = key_dirs[:6]
        parts.append(f"Key dirs: {', '.join(shown)}{'...' if len(key_dirs) > 6 else ''}.")
    if entry_points:
        shown = entry_points[:4]
        parts.append(f"Entry points: {', '.join(shown)}.")
    # Check for README
    for readme in ("README.md", "README.rst", "README.txt"):
        if (root / readme).exists():
            parts.append(f"Has {readme}.")
            break
    return " ".join(parts) if parts else "No notable structure detected."


def register(app: FastMCP) -> None:
    """Register the proj_explore_codebase tool with the MCP app."""

    @app.tool(
        description=(
            "Explore a codebase directory and return structured findings: tech stack, "
            "entry points, key directories, file type breakdown, and a directory tree. "
            "Uses Python stdlib only — no Bash required. Replaces 6+ Bash commands in the "
            "explore skill. Returns JSON with keys: tech_stack, entry_points, key_dirs, "
            "config_files, file_types, file_tree, arch_note."
        )
    )
    def proj_explore_codebase(path: str, max_files: int = 80) -> str:
        result = explore_codebase(path, max_files=max_files)
        return json.dumps(result, indent=2)
