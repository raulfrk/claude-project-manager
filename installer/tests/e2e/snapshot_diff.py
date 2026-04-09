"""Generate an HTML visual diff report for snapshot mismatches.

Usage (called by CI on snapshot failure):
    python snapshot_diff.py <snapshots_dir> <output.html>

Compares each ``*_actual.svg`` against the corresponding golden ``*.svg``
and produces a single HTML report with:
- Side-by-side view (golden vs actual)
- Ghost overlay (golden at 50% opacity over actual)
- Text diff of extracted visible content
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


def _extract_text(svg: str) -> list[str]:
    """Pull visible text from SVG ``<text>`` elements."""
    raw = re.findall(r"<text[^>]*>(.*?)</text>", svg, re.DOTALL)
    return [
        f.replace("&#160;", " ").strip()
        for f in raw
        if f.replace("&#160;", " ").strip()
    ]


def _build_diff_section(name: str, golden_svg: str, actual_svg: str) -> str:
    golden_text = _extract_text(golden_svg)
    actual_text = _extract_text(actual_svg)

    # Find text differences
    text_diff_rows = ""
    max_len = max(len(golden_text), len(actual_text))
    has_diff = False
    for i in range(max_len):
        g = golden_text[i] if i < len(golden_text) else "(missing)"
        a = actual_text[i] if i < len(actual_text) else "(missing)"
        if g != a:
            has_diff = True
            text_diff_rows += (
                f'<tr class="diff"><td>{i}</td><td>{g}</td><td>{a}</td></tr>\n'
            )

    text_section = ""
    if has_diff:
        text_section = f"""
        <h3>Text Differences</h3>
        <table class="text-diff">
            <tr><th>#</th><th>Golden</th><th>Actual</th></tr>
            {text_diff_rows}
        </table>
        """
    else:
        text_section = "<p>Text content is identical — differences are in layout/coordinates only.</p>"

    return f"""
    <div class="snapshot-diff">
        <h2>{name}</h2>

        <h3>Side by Side</h3>
        <div class="side-by-side">
            <div class="panel">
                <h4>Golden (committed)</h4>
                <div class="svg-container">{golden_svg}</div>
            </div>
            <div class="panel">
                <h4>Actual (this run)</h4>
                <div class="svg-container">{actual_svg}</div>
            </div>
        </div>

        <h3>Ghost Overlay (golden at 50% over actual)</h3>
        <div class="overlay-container">
            <div class="overlay-actual">{actual_svg}</div>
            <div class="overlay-golden">{golden_svg}</div>
        </div>

        {text_section}
    </div>
    """


HTML_TEMPLATE = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Snapshot Diff Report</title>
<style>
    body {{ font-family: system-ui, sans-serif; margin: 2rem; background: #1a1a2e; color: #e0e0e0; }}
    h1 {{ color: #ff6b6b; }}
    h2 {{ color: #4ecdc4; border-bottom: 1px solid #333; padding-bottom: 0.5rem; }}
    h3 {{ color: #ffe66d; }}
    h4 {{ text-align: center; color: #a0a0a0; }}
    .snapshot-diff {{ margin-bottom: 3rem; }}
    .side-by-side {{ display: flex; gap: 1rem; }}
    .panel {{ flex: 1; overflow: auto; border: 1px solid #333; border-radius: 8px; padding: 0.5rem; background: #16213e; }}
    .svg-container svg {{ width: 100%; height: auto; }}
    .overlay-container {{ position: relative; border: 1px solid #333; border-radius: 8px; padding: 0.5rem; background: #16213e; }}
    .overlay-actual svg {{ width: 100%; height: auto; }}
    .overlay-golden {{ position: absolute; top: 0.5rem; left: 0.5rem; right: 0.5rem; opacity: 0.5; }}
    .overlay-golden svg {{ width: 100%; height: auto; filter: hue-rotate(180deg) brightness(1.5); }}
    .text-diff {{ border-collapse: collapse; width: 100%; }}
    .text-diff th, .text-diff td {{ border: 1px solid #333; padding: 0.3rem 0.5rem; text-align: left; }}
    .text-diff th {{ background: #16213e; }}
    .text-diff .diff td {{ background: #3d1f1f; }}
    .no-diffs {{ color: #4ecdc4; font-size: 1.2rem; text-align: center; padding: 2rem; }}
</style>
</head>
<body>
<h1>Snapshot Diff Report</h1>
{sections}
</body>
</html>
"""


def main() -> None:
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <snapshots_dir> <output.html>")
        sys.exit(1)

    snap_dir = Path(sys.argv[1])
    output = Path(sys.argv[2])

    sections = []
    for actual_file in sorted(snap_dir.glob("*_actual.svg")):
        name = actual_file.stem.removesuffix("_actual")
        golden_file = snap_dir / f"{name}.svg"
        if not golden_file.exists():
            continue
        golden_svg = golden_file.read_text(encoding="utf-8")
        actual_svg = actual_file.read_text(encoding="utf-8")
        if golden_svg != actual_svg:
            sections.append(_build_diff_section(name, golden_svg, actual_svg))

    if not sections:
        html = HTML_TEMPLATE.format(
            sections='<p class="no-diffs">No snapshot differences found.</p>'
        )
    else:
        html = HTML_TEMPLATE.format(sections="\n".join(sections))

    output.write_text(html, encoding="utf-8")
    print(f"Diff report written to {output} ({len(sections)} diff(s))")


if __name__ == "__main__":
    main()
