# installer/migrations/report.py
from __future__ import annotations

from pathlib import Path

from installer.migrations.types import MigrationPlan


def write_dry_run_report(
    plans: list[MigrationPlan],
    output_path: Path,
    *,
    run_ts: str,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = [
        "# Flat-Todo Migration — Dry Run",
        "",
        f"Run timestamp: `{run_ts}`",
        "",
    ]
    if not plans:
        lines.append("No projects require migration.")
        output_path.write_text("\n".join(lines) + "\n")
        return output_path

    for plan in plans:
        lines.extend(_render_project(plan))

    output_path.write_text("\n".join(lines) + "\n")
    return output_path


def _render_project(plan: MigrationPlan) -> list[str]:
    out = [
        f"## {plan.project.name}",
        "",
        f"- Path: `{plan.project.path}`",
        f"- Schema version: {plan.project.current_version} → 2",
        f"- Recovery path: `{plan.recovery_path.value}`",
        f"- Parents: {len(plan.parents)}",
        f"- Children: {len(plan.children)}",
        "",
        "### Remote actions",
        "",
    ]
    for integ, actions in plan.integration_actions.items():
        out.append(f"**{integ}** — {len(actions)} actions")
        for a in actions:
            out.append(f"- `{a.kind}` target=`{a.target_id}`")
        out.append("")
    return out
