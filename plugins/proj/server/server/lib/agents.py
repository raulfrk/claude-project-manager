"""Agent resolution helpers for workflow steps."""

from __future__ import annotations

from pathlib import Path

from server.lib import storage
from server.lib.models import ProjConfig

# ── Constants ─────────────────────────────────────────────────────────────────

STEP_DEFAULTS: dict[str, str] = {
    "define": "Plan",
    "research": "Explore",
    "decompose": "Plan",
    "execute": "general-purpose",
}

VALID_STEPS: set[str] = set(STEP_DEFAULTS.keys())


# ── Resolver ──────────────────────────────────────────────────────────────────


def resolve_agent_for_step(
    cfg: ProjConfig,
    project_name: str,
    step: str,
) -> tuple[str, str | None]:
    """Resolve which agent to invoke for a given workflow step, with soft-fail validation.

    Args:
        cfg: The loaded ProjConfig (determines tracking_dir).
        project_name: Name of the project (matches ProjectMeta.name).
        step: Step name — must be one of VALID_STEPS.

    Returns:
        Tuple of (agent_name, warning):
        - agent_name (str): Name of the agent to invoke.
        - warning (str | None): Warning message if a fallback occurred, else None.

    Raises:
        ValueError: If step is not in VALID_STEPS.
    """
    if step not in VALID_STEPS:
        msg = f"Unknown step: '{step}'. Must be one of {sorted(VALID_STEPS)}"
        raise ValueError(msg)

    data = storage.load_agents(cfg, project_name)
    agents_section = data.get("agents", {})
    agent_override = agents_section.get(step) if isinstance(agents_section, dict) else None

    # No override → use default, no warning
    if not agent_override or not isinstance(agent_override, str):
        return (STEP_DEFAULTS[step], None)

    # Override present → try to validate file existence
    try:
        meta = storage.load_meta(cfg, project_name)
    except FileNotFoundError:
        # Can't load meta — cannot validate; trust the override
        return (agent_override, None)

    # No repos linked → cannot validate; trust the override
    if not meta.repos:
        return (agent_override, None)

    # Check whether the agent file exists in the first repo's .claude/agents/ dir
    repo_path = Path(meta.repos[0].path).expanduser().resolve()
    agent_file = repo_path / ".claude" / "agents" / f"{agent_override}.md"

    if agent_file.exists():
        return (agent_override, None)

    # File missing → soft-fail: return default + warning
    warning = f"Agent '{agent_override}.md' not found in .claude/agents/ \u2014 falling back to default"
    return (STEP_DEFAULTS[step], warning)
