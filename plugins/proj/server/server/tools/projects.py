"""MCP tools for project lifecycle management."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from server.lib import state, storage
from server.lib.models import (
    ProjectEntry,
    ProjectMeta,
    ProjectPermissions,
    RepoEntry,
    validate_project_name,
)
from server.lib.zoxide import resolve_enabled as _zoxide_enabled, zoxide_boost, zoxide_remove
from server.tools.config import require_config, require_project

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def _init_tracking_dir(tracking_dir: Path, project_name: str) -> None:
    """Create the tracking directory structure for a new project."""
    proj_dir = tracking_dir / project_name
    proj_dir.mkdir(parents=True, exist_ok=True)
    notes = proj_dir / "NOTES.md"
    if not notes.exists():
        notes.write_text(f"# {project_name}\n")
    todos_yaml = proj_dir / "todos.yaml"
    if not todos_yaml.exists():
        todos_yaml.write_text("todos: []\n")
    agents_yaml = proj_dir / "agents.yaml"
    if not agents_yaml.exists():
        agents_yaml.write_text("version: 1\nagents:\n  define: null\n  research: null\n  decompose: null\n  execute: null\n")


def register(app: FastMCP) -> None:
    """Register proj_init, proj_list, proj_get, proj_get_active, proj_set_active, proj_update_meta, proj_archive, proj_add_repo, proj_remove_repo, proj_set_permissions, and proj_load_session tools with the MCP app."""

    @app.tool(description="Initialize tracking for a new project. Accepts multiple directories via the dirs parameter (list of {path, label} dicts). The legacy path parameter is kept for backward compatibility and creates a single directory with label 'code'.")
    def proj_init(
        name: str,
        path: str | None = None,
        dirs: list[dict[str, str]] | None = None,
        description: str = "",
        tags: list[str] | None = None,
        git_enabled: bool = True,
    ) -> str:
        err = validate_project_name(name)
        if err:
            return err

        cfg = require_config()
        index = storage.load_index(cfg)

        if name in index.projects:
            return f"Project '{name}' already exists."

        # Build list of RepoEntry from dirs or legacy path parameter
        repo_entries: list[RepoEntry] = []
        if dirs:
            if path:
                return "Provide either 'dirs' or 'path', not both."
            labels_seen: set[str] = set()
            for d in dirs:
                d_path = d.get("path", "")
                d_label = d.get("label", "")
                if not d_path:
                    return "Each directory entry must have a 'path'."
                if not d_label:
                    return "Each directory entry must have a 'label'."
                if d_label in labels_seen:
                    return f"Duplicate label '{d_label}'. Each directory must have a unique label."
                labels_seen.add(d_label)
                resolved = str(Path(d_path).expanduser().resolve())
                repo_entries.append(RepoEntry(label=d_label, path=resolved))
        else:
            # Legacy single-path mode
            if path:
                resolved_path = str(Path(path).expanduser().resolve())
            elif cfg.projects_base_dir:
                resolved_path = str((Path(cfg.projects_base_dir).expanduser() / name).resolve())
            else:
                return (
                    f"No path provided for project '{name}' and no projects_base_dir configured. "
                    "Provide an explicit path or set projects_base_dir via /proj:init-plugin."
                )
            repo_entries.append(RepoEntry(label="code", path=resolved_path))

        if not repo_entries:
            return "At least one directory is required."

        today = str(date.today())
        tracking = Path(cfg.tracking_dir).expanduser() / name
        _init_tracking_dir(Path(cfg.tracking_dir).expanduser(), name)

        meta = ProjectMeta(
            name=name,
            description=description,
            tags=tags or [],
            git_enabled=git_enabled,
        )
        for repo_entry in repo_entries:
            meta.repos.append(repo_entry)
        meta.dates.created = today
        meta.dates.last_updated = today
        storage.save_meta(cfg, meta)

        # Boost paths in zoxide frecency database if enabled
        if _zoxide_enabled(cfg, meta):
            for repo_entry in repo_entries:
                zoxide_boost(repo_entry.path)

        entry = ProjectEntry(
            name=name,
            tracking_dir=str(tracking),
            created=today,
            tags=tags or [],
        )
        index.projects[name] = entry
        if index.active is None:
            index.active = name
        storage.save_index(cfg, index)

        return f"Initialized project '{name}' at {tracking}."

    @app.tool(description="List all projects.")
    def proj_list(include_archived: bool = False) -> str:
        cfg = require_config()
        index = storage.load_index(cfg)
        projects = [p for p in index.projects.values() if include_archived or not p.archived]
        if not projects:
            return "No projects found."
        active = state.get_session_active()
        lines = [f"Projects (active: {active or 'none'}):"]
        for p in sorted(projects, key=lambda x: x.name):
            marker = " *" if p.name == active else ""
            try:
                meta = storage.load_meta(cfg, p.name)
                status = meta.status
                desc = f" — {meta.description}" if meta.description else ""
            except FileNotFoundError:
                status = "unknown"
                desc = ""
            lines.append(f"  {p.name}{marker} [{status}]{desc} — created {p.created}")
        return "\n".join(lines)

    @app.tool(description="Get full details of a project (defaults to active project).")
    def proj_get(name: str | None = None) -> str:
        cfg = require_config()
        index = storage.load_index(cfg)
        project_name = state.resolve_project(name)
        if not project_name:
            return "No active project."
        if project_name not in index.projects:
            return f"Project '{project_name}' not found."
        meta = storage.load_meta(cfg, project_name)
        return json.dumps(meta.to_dict(), indent=2)

    @app.tool(description="Get the currently active project.")
    def proj_get_active() -> str:
        cfg = require_config()
        name = state.get_session_active()
        if not name:
            return "No active project."
        index = storage.load_index(cfg)
        if name not in index.projects:
            return "No active project."
        meta = storage.load_meta(cfg, name)
        return json.dumps(meta.to_dict(), indent=2)

    @app.tool(description="Set the active project by name.")
    def proj_set_active(name: str) -> str:
        import difflib

        cfg = require_config()
        index = storage.load_index(cfg)
        if name not in index.projects:
            candidates = [k for k, v in index.projects.items() if not v.archived]
            matches = difflib.get_close_matches(name, candidates, n=3, cutoff=0.4)
            if not matches:
                all_names = ", ".join(sorted(candidates)) if candidates else "(none)"
                return f"Project '{name}' not found. Available: {all_names}"
            if len(matches) == 1:
                name = matches[0]
            else:
                return f"Ambiguous match. Did you mean one of: {', '.join(matches)}?"
        index.active = name
        storage.save_index(cfg, index)
        return f"Active project set to '{name}'."

    @app.tool(description="Update project metadata fields.")
    def proj_update_meta(
        name: str | None = None,
        description: str | None = None,
        status: str | None = None,
        priority: str | None = None,
        tags: list[str] | None = None,
        target_date: str | None = None,
        git_enabled: bool | None = None,
        claudemd_management: bool | None = None,
        zoxide_integration: bool | None = None,
    ) -> str:
        result = require_project(name)
        if isinstance(result, str):
            return result
        cfg, project_name = result
        meta = storage.load_meta(cfg, project_name)
        if description is not None:
            meta.description = description
        if status is not None:
            meta.status = status
        if priority is not None:
            meta.priority = priority
        if tags is not None:
            meta.tags = tags
        if target_date is not None:
            meta.dates.target = target_date
        if git_enabled is not None:
            meta.git_enabled = git_enabled
        if claudemd_management is not None:
            meta.claudemd_management = claudemd_management
        if zoxide_integration is not None:
            meta.zoxide_integration = zoxide_integration
        storage.save_meta(cfg, meta)
        return f"Updated project '{project_name}'."

    @app.tool(description="Archive a project (marks as archived, unsets active if needed).")
    def proj_archive(name: str | None = None) -> str:
        result = require_project(name)
        if isinstance(result, str):
            return result
        cfg, project_name = result
        index = storage.load_index(cfg)
        if project_name not in index.projects:
            return f"Project '{project_name}' not found."

        # Remove repo paths from zoxide before archiving
        try:
            meta = storage.load_meta(cfg, project_name)
            if _zoxide_enabled(cfg, meta):
                # Collect worktree base repo paths to skip
                skip_paths: set[str] = set()
                if cfg.worktree_integration:
                    from server.tools.perms_grant import _WORKTREE_CONFIG
                    import yaml
                    if _WORKTREE_CONFIG.exists():
                        try:
                            wt_data = yaml.safe_load(_WORKTREE_CONFIG.read_text()) or {}
                            base_repos_raw = wt_data.get("base_repos", [])
                            if isinstance(base_repos_raw, list):
                                for repo in base_repos_raw:
                                    if isinstance(repo, dict):
                                        p = repo.get("path", "")
                                        if isinstance(p, str) and p:
                                            skip_paths.add(p)
                        except Exception:  # noqa: BLE001
                            pass
                for repo in meta.repos:
                    if repo.path not in skip_paths:
                        zoxide_remove(repo.path)
        except FileNotFoundError:
            pass  # No meta file — skip zoxide removal

        index.projects[project_name].archived = True
        if index.active == project_name:
            index.active = None
        storage.save_index(cfg, index)
        return f"Archived project '{project_name}'."

    @app.tool(description="Add a repository path to a project.")
    def proj_add_repo(
        repo_path: str,
        label: str = "code",
        claudemd: bool = False,
        reference: bool = False,
        project_name: str | None = None,
    ) -> str:
        result = require_project(project_name)
        if isinstance(result, str):
            return result
        cfg, name = result
        meta = storage.load_meta(cfg, name)
        abs_path = str(Path(repo_path).expanduser().resolve())
        if any(r.path == abs_path for r in meta.repos):
            return f"Repo at '{abs_path}' already registered."
        if any(r.label == label for r in meta.repos):
            return f"Label '{label}' already in use. Choose a different label."
        meta.repos.append(RepoEntry(label=label, path=abs_path, claudemd=claudemd, reference=reference))
        storage.save_meta(cfg, meta)

        # Boost path in zoxide frecency database if enabled
        if _zoxide_enabled(cfg, meta):
            zoxide_boost(abs_path)

        if reference:
            return f"Added reference repo '{label}' at {abs_path} to project '{name}' (read-only)."
        return f"Added repo '{label}' at {abs_path} to project '{name}'."

    @app.tool(description="Remove a repository from a project by label (cannot remove the last repo).")
    def proj_remove_repo(
        label: str,
        project_name: str | None = None,
    ) -> str:
        result = require_project(project_name)
        if isinstance(result, str):
            return result
        cfg, name = result
        meta = storage.load_meta(cfg, name)
        if len(meta.repos) <= 1:
            return "Cannot remove the last repo from a project. Use /proj:archive to remove the entire project instead."
        found = next((r for r in meta.repos if r.label == label), None)
        if found is None:
            return f"No repo with label '{label}' found in project '{name}'."
        meta.repos.remove(found)
        storage.save_meta(cfg, meta)
        ref_note = " (reference, read-only)" if found.reference else ""
        return f"Removed repo '{label}' at {found.path}{ref_note} from project '{name}'."

    @app.tool(description="Set per-project permissions override (null = use global config).")
    def proj_set_permissions(auto_grant: bool | None, project_name: str | None = None) -> str:
        result = require_project(project_name)
        if isinstance(result, str):
            return result
        cfg, name = result
        meta = storage.load_meta(cfg, name)
        meta.permissions = ProjectPermissions(auto_grant=auto_grant)
        storage.save_meta(cfg, meta)
        auto_grant_state = str(auto_grant) if auto_grant is not None else "use global default"
        return f"Set permissions.auto_grant={auto_grant_state} for project '{name}'."

    @app.tool(
        description="Set the active project for this session only (not persisted globally)."
    )
    def proj_load_session(name: str) -> str:
        """Load a project into session context without changing the persisted active project."""
        import difflib

        cfg = require_config()
        index = storage.load_index(cfg)
        if name not in index.projects:
            candidates = [k for k, v in index.projects.items() if not v.archived]
            matches = difflib.get_close_matches(name, candidates, n=3, cutoff=0.4)
            if not matches:
                all_names = ", ".join(sorted(candidates)) if candidates else "(none)"
                return f"Project '{name}' not found. Available: {all_names}"
            if len(matches) == 1:
                name = matches[0]
            else:
                return f"Ambiguous match. Did you mean one of: {', '.join(matches)}?"
        state.set_session_active(name)
        return f"Loaded project '{name}' for this session."
