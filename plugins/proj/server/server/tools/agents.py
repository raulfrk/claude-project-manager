"""MCP tools for per-project agent overrides."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from server.lib import storage
from server.lib.agents import STEP_DEFAULTS, VALID_STEPS, resolve_agent_for_step
from server.tools.config import require_project

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

_VALID_STEPS_DISPLAY = ", ".join(sorted(VALID_STEPS))

_DEFAULT_AGENTS_YAML: dict[str, object] = {
    "version": 1,
    "agents": {
        "define": None,
        "research": None,
        "decompose": None,
        "execute": None,
    },
}


def register(app: FastMCP) -> None:
    """Register proj_set_agent, proj_get_agents, proj_remove_agent, and proj_resolve_agent tools with the MCP app."""

    @app.tool(description="Set agent override for a step.")
    def proj_set_agent(
        step: str,
        agent_name: str,
        project_name: str | None = None,
    ) -> str:
        # Validate step
        if step not in VALID_STEPS:
            return (
                f"Invalid step '{step}'. Must be one of: {_VALID_STEPS_DISPLAY}."
            )

        # Validate agent_name (no path separators or .md extension)
        if "/" in agent_name or "\\" in agent_name or agent_name.endswith(".md"):
            return (
                f"Invalid agent_name '{agent_name}'. "
                "Provide the agent name without path separators or the .md extension."
            )

        result = require_project(project_name)
        if isinstance(result, str):
            return result
        cfg, name = result

        # Validate .claude/agents/<agent_name>.md exists in the project repo
        try:
            meta = storage.load_meta(cfg, name)
        except FileNotFoundError:
            return f"Project '{name}' metadata not found."

        if not meta.repos:
            return "Project has no repositories configured."

        writable_repos = [r for r in meta.repos if not r.reference]
        if not writable_repos:
            return "Project has no writable repositories configured."
        # Search all writable repos for the agent file
        agent_found = False
        searched_paths: list[str] = []
        for repo in writable_repos:
            agents_dir = Path(repo.path).expanduser().resolve() / ".claude" / "agents"
            agent_path = agents_dir / f"{agent_name}.md"
            searched_paths.append(str(agent_path))
            if agent_path.exists():
                agent_found = True
                break
        if not agent_found:
            return (
                f"Agent '{agent_name}' not found in any writable repo's .claude/agents/ directory. "
                f"Searched: {', '.join(searched_paths)}. "
                "Create the agent file before assigning it."
            )

        # Load existing data or create skeleton if missing
        path = storage.agents_path(cfg, name)
        if not path.exists():
            import copy
            data: dict[str, object] = copy.deepcopy(_DEFAULT_AGENTS_YAML)
        else:
            data = storage.load_agents(cfg, name)
            if not isinstance(data.get("agents"), dict):
                data["agents"] = {
                    "define": None,
                    "research": None,
                    "decompose": None,
                    "execute": None,
                }

        agents_section = data["agents"]
        assert isinstance(agents_section, dict)
        agents_section[step] = agent_name
        storage.save_agents(cfg, name, data)
        return f"Set agent for step '{step}' to '{agent_name}' in project '{name}'."

    @app.tool(description="List agents for all steps.")
    def proj_get_agents(project_name: str | None = None) -> str:
        result = require_project(project_name)
        if isinstance(result, str):
            return result
        cfg, name = result

        data = storage.load_agents(cfg, name)
        agents_section = data.get("agents", {})
        if not isinstance(agents_section, dict):
            agents_section = {}

        lines = [f"Agents for project '{name}':"]
        for step in sorted(VALID_STEPS):
            override = agents_section.get(step)
            if override and isinstance(override, str):
                lines.append(f"  {step}: {override}")
            else:
                default = STEP_DEFAULTS[step]
                lines.append(f"  {step}: (default: {default})")
        return "\n".join(lines)

    @app.tool(description="Remove agent override for a step.")
    def proj_remove_agent(
        step: str,
        project_name: str | None = None,
    ) -> str:
        if step not in VALID_STEPS:
            return (
                f"Invalid step '{step}'. Must be one of: {_VALID_STEPS_DISPLAY}."
            )

        result = require_project(project_name)
        if isinstance(result, str):
            return result
        cfg, name = result

        path = storage.agents_path(cfg, name)
        if not path.exists():
            # Nothing to remove — succeed silently
            return (
                f"No agents.yaml found for project '{name}'; "
                f"step '{step}' already uses the default ({STEP_DEFAULTS[step]})."
            )

        data = storage.load_agents(cfg, name)
        agents_section = data.get("agents", {})
        if not isinstance(agents_section, dict):
            agents_section = {}

        agents_section[step] = None
        data["agents"] = agents_section
        storage.save_agents(cfg, name, data)
        return (
            f"Removed agent override for step '{step}' in project '{name}' "
            f"(reverted to default: {STEP_DEFAULTS[step]})."
        )

    @app.tool(description="Resolve agent for a step.")
    def proj_resolve_agent(
        step: str,
        project_name: str | None = None,
    ) -> str:
        if step not in VALID_STEPS:
            return (
                f"Invalid step '{step}'. Must be one of: {_VALID_STEPS_DISPLAY}."
            )

        result = require_project(project_name)
        if isinstance(result, str):
            return result
        cfg, name = result

        agent, warning = resolve_agent_for_step(cfg, name, step)
        return json.dumps({"agent": agent, "warning": warning})
