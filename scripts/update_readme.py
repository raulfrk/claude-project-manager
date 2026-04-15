#!/usr/bin/env python3
"""Auto-update README.md sections from marketplace.json and test summary.

Replaces content between <!-- AUTO:X-start --> and <!-- AUTO:X-end --> markers.
Exit code 1 if README was modified (for pre-commit), 0 if unchanged.
"""

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
README_PATH = REPO_ROOT / "README.md"
MARKETPLACE_PATH = REPO_ROOT / ".claude-plugin" / "marketplace.json"
TEST_SUMMARY_PATH = REPO_ROOT / "scripts" / ".test-summary.json"


def load_marketplace() -> dict:
    """Load marketplace.json and return parsed data."""
    with MARKETPLACE_PATH.open() as f:
        return json.load(f)


def load_test_summary() -> dict | None:
    """Load test summary if it exists, else return None."""
    if not TEST_SUMMARY_PATH.exists():
        return None
    try:
        with TEST_SUMMARY_PATH.open() as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def escape_pipe(text: str) -> str:
    """Escape pipe characters for Markdown table cells."""
    return text.replace("|", "\\|")


def generate_plugins_table(plugins: list[dict]) -> str:
    """Generate a Markdown table of plugins from marketplace data."""
    if not plugins:
        return (
            "| Plugin | Version | Category | Description |\n"
            "|--------|---------|----------|-------------|\n"
            "| *No plugins found* | | | |"
        )

    lines = [
        "| Plugin | Version | Category | Description |",
        "|--------|---------|----------|-------------|",
    ]
    for p in plugins:
        name = escape_pipe(p.get("name", ""))
        version = escape_pipe(p.get("version", ""))
        category = escape_pipe(p.get("category", "uncategorized"))
        description = escape_pipe(p.get("description", ""))
        lines.append(
            f"| [{name}](plugins/{name}/) | {version} | {category} | {description} |"
        )
    return "\n".join(lines)


def generate_badges(version: str, test_count: int | None) -> str:
    """Generate shields.io badge markdown."""
    badges = []
    badges.append(
        f"[![version](https://img.shields.io/badge/version-{version}-blue?style=flat-square)](CHANGELOG.md)"
    )
    if test_count is not None:
        badges.append(
            f"[![tests](https://img.shields.io/badge/tests-{test_count}%20passing-brightgreen?style=flat-square)](#contributing)"
        )
    badges.append(
        "[![license](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE)"
    )
    return "\n".join(badges)


def compute_marketplace_version(plugins: list[dict]) -> str:
    """Derive an overall version from plugin versions (use the highest)."""
    versions = []
    for p in plugins:
        v = p.get("version", "0.0.0")
        try:
            parts = tuple(int(x) for x in v.split("."))
            versions.append((parts, v))
        except ValueError:
            continue
    if not versions:
        return "0.0.0"
    versions.sort(key=lambda x: x[0], reverse=True)
    return versions[0][1]


def replace_markers(content: str, sections: dict[str, str]) -> str:
    """Replace content between <!-- AUTO:X-start --> and <!-- AUTO:X-end --> markers.

    Args:
        content: Full README content.
        sections: Mapping of marker name to replacement content.

    Returns:
        Updated content with sections replaced.
    """
    for name, replacement in sections.items():
        start_tag = f"<!-- AUTO:{re.escape(name)}-start -->"
        end_tag = f"<!-- AUTO:{re.escape(name)}-end -->"
        pattern = re.compile(
            rf"({start_tag})\n.*?\n({end_tag})",
            re.DOTALL,
        )
        if not pattern.search(content):
            print(
                f"WARNING: marker AUTO:{name} not found in README.md, skipping",
                file=sys.stderr,
            )
            continue
        content = pattern.sub(
            rf"\1\n{replacement}\n\2",
            content,
        )
    return content


def main() -> int:
    """Main entry point. Returns 0 if unchanged, 1 if modified."""
    if not MARKETPLACE_PATH.exists():
        print(f"ERROR: {MARKETPLACE_PATH} not found", file=sys.stderr)
        return 1

    if not README_PATH.exists():
        print(f"ERROR: {README_PATH} not found", file=sys.stderr)
        return 1

    marketplace = load_marketplace()
    plugins = marketplace.get("plugins", [])
    test_summary = load_test_summary()

    # Build sections
    sections: dict[str, str] = {}

    # Plugins table
    sections["plugins-table"] = generate_plugins_table(plugins)

    # Badges
    version = compute_marketplace_version(plugins)
    test_count = test_summary.get("total_passing") if test_summary else None
    sections["badges"] = generate_badges(version, test_count)

    # Read current README
    original = README_PATH.read_text()

    # Replace markers
    updated = replace_markers(original, sections)

    if updated == original:
        print("README.md is up to date")
        return 0

    README_PATH.write_text(updated)
    print("README.md updated")
    return 1


if __name__ == "__main__":
    sys.exit(main())
