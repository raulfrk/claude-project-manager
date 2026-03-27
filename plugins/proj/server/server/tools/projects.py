"""MCP tools for project lifecycle management."""

from __future__ import annotations

import json
from datetime import date, timedelta
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
from server.lib.models import TrelloListMappings
from server.tools.config import require_config, require_project


def _resolve_list_mappings(cfg: object, meta: ProjectMeta) -> TrelloListMappings:
    """Resolve effective Trello list mappings: per-project override falls back to global."""
    from server.lib.models import ProjConfig  # local import to avoid circularity at module level

    assert isinstance(cfg, ProjConfig)
    if meta.trello.list_mappings is not None:
        return meta.trello.list_mappings
    return cfg.trello.list_mappings

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


def register(app: FastMCP) -> None:
    """Register proj_init, proj_list, proj_list_full, proj_get, proj_get_active, proj_update_meta, proj_archive_preflight, proj_archive, proj_add_repo, proj_remove_repo, proj_set_permissions, proj_load_session, and proj_migrate_dirs tools with the MCP app."""

    @app.tool(description="Initialize tracking for a new project. Accepts multiple directories via the dirs parameter (list of {path, label} dicts). The legacy path parameter is kept for backward compatibility and creates a single directory with label 'code'.")
    def proj_init(
        name: str,
        path: str | None = None,
        dirs: list[dict[str, str]] | None = None,
        description: str = "",
        tags: list[str] | None = None,
        git_enabled: bool = True,
        zoxide_integration: bool | None = None,
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
        if zoxide_integration is not None:
            meta.zoxide_integration = zoxide_integration
        storage.save_meta(cfg, meta)

        entry = ProjectEntry(
            name=name,
            tracking_dir=str(tracking),
            created=today,
            tags=tags or [],
        )
        index.projects[name] = entry
        storage.save_index(cfg, index)

        # Initialize git tracking for tracking directory if enabled
        if cfg.git_tracking.enabled:
            from server.lib.tracking_git import ensure_git_repo, tracking_commit
            root_tracking = Path(cfg.tracking_dir).expanduser()
            if ensure_git_repo(root_tracking):
                tracking_commit(root_tracking, f"[{name}] Initial commit: project '{name}'")

        # Auto-set as session active so the newly created project is immediately usable
        state.set_session_active(name)

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

    @app.tool(
        description="List all projects with full metadata (status, tags, repos, integrations). "
        "Optionally filter by integration (todoist, trello, jira)."
    )
    def proj_list_full(
        include_archived: bool = False,
        integration_filter: str | None = None,
    ) -> str:
        cfg = require_config()
        index = storage.load_index(cfg)

        valid_integrations = {"todoist", "trello", "jira"}
        if integration_filter and integration_filter not in valid_integrations:
            return json.dumps({
                "error": f"Unknown integration '{integration_filter}'. "
                f"Valid values: {', '.join(sorted(valid_integrations))}",
            })

        entries = [
            p for p in index.projects.values()
            if include_archived or not p.archived
        ]

        projects: list[dict[str, object]] = []
        warnings: list[str] = []
        for entry in sorted(entries, key=lambda x: x.name):
            try:
                meta = storage.load_meta(cfg, entry.name)
            except FileNotFoundError:
                warnings.append(f"meta.yaml missing for project '{entry.name}'")
                continue

            # Apply integration filter
            if integration_filter:
                has_integration = False
                if integration_filter == "todoist" and meta.todoist_project_id:
                    has_integration = True
                elif integration_filter == "trello" and meta.trello_card_id:
                    has_integration = True
                elif integration_filter == "jira" and meta.jira_issue_key:
                    has_integration = True
                if not has_integration:
                    continue

            # Build integration summary
            integrations: dict[str, str | None] = {
                "todoist": meta.todoist_project_id,
                "trello": meta.trello_card_id,
                "jira": meta.jira_issue_key,
            }

            projects.append({
                "name": meta.name,
                "description": meta.description,
                "status": meta.status,
                "priority": meta.priority,
                "tags": meta.tags,
                "repos": [r.to_dict() for r in meta.repos],
                "dates": meta.dates.to_dict(),
                "archived": entry.archived,
                "integrations": {k: v for k, v in integrations.items() if v},
            })

        return json.dumps({"projects": projects, "count": len(projects), "warnings": warnings}, indent=2)

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
        git_tracking_enabled: bool | None = None,
        git_tracking_github_enabled: bool | None = None,
        git_tracking_github_repo_format: str | None = None,
    ) -> str:
        result = require_project(name)
        if isinstance(result, str):
            return result
        cfg, project_name = result
        meta = storage.load_meta(cfg, project_name)
        if description is not None:
            meta.description = description
        old_status = meta.status
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
        if git_tracking_enabled is not None:
            meta.git_tracking.enabled = git_tracking_enabled
        if git_tracking_github_enabled is not None:
            meta.git_tracking.github_enabled = git_tracking_github_enabled
        if git_tracking_github_repo_format is not None:
            meta.git_tracking.github_repo_format = git_tracking_github_repo_format
        storage.save_meta(cfg, meta)

        # Build trello_move hint if status changed and project has Trello card
        trello_move_hint = ""
        if status is not None and status != old_status and meta.trello_card_id:
            try:
                mappings = _resolve_list_mappings(cfg, meta)
                # Map status to target list
                status_list_map = {
                    "active": mappings.active,
                    "paused": mappings.pending,
                    "blocked": mappings.pending,
                }
                target_list = status_list_map.get(status, "")
                if target_list:
                    trello_move_hint = (
                        f"\ntrello_move: {{\"card_id\": \"{meta.trello_card_id}\", "
                        f"\"target_list\": \"{target_list}\"}}"
                    )
            except Exception:  # noqa: BLE001
                pass  # Update succeeds even if hint generation fails

        return f"Updated project '{project_name}'.{trello_move_hint}"

    @app.tool(
        description="Pre-flight check for archiving a project. Returns config, project metadata, "
        "open todos, and detected worktrees in a single call so the skill can present a "
        "consolidated prompt without sequential guard calls."
    )
    def proj_archive_preflight(project_name: str) -> str:
        from server.lib.enums import TERMINAL_STATUSES

        cfg = require_config()
        index = storage.load_index(cfg)

        if project_name not in index.projects:
            return f"Project '{project_name}' not found."

        entry = index.projects[project_name]
        if entry.archived:
            return f"Project '{project_name}' is already archived."

        try:
            meta = storage.load_meta(cfg, project_name)
        except FileNotFoundError:
            return f"meta.yaml missing for project '{project_name}'."

        try:
            todos = storage.load_todos(cfg, project_name)
        except FileNotFoundError:
            todos = []

        open_todos = [t for t in todos if t.status not in TERMINAL_STATUSES]

        # Detect worktrees: a .git *file* (not directory) indicates a worktree checkout
        worktrees: list[dict[str, str]] = []
        for repo in meta.repos:
            git_path = Path(repo.path) / ".git"
            if git_path.is_file():
                worktrees.append({"path": repo.path, "label": repo.label})

        result = {
            "config": {
                "archive_destination": cfg.archive.destination,
                "trash_grace_days": cfg.archive.trash_grace_days,
            },
            "project": {
                "name": meta.name,
                "status": meta.status,
                "repos": [r.to_dict() for r in meta.repos],
                "trello_card_id": meta.trello_card_id,
                "todoist_project_id": meta.todoist_project_id,
            },
            "open_todos": {
                "count": len(open_todos),
                "items": [{"id": t.id, "title": t.title} for t in open_todos],
            },
            "worktrees": worktrees,
        }
        return json.dumps(result, indent=2)

    @app.tool(description="Archive a project (marks as archived, unsets active if needed).")
    def proj_archive(
        name: str | None = None,
        purgeable: bool = True,
    ) -> str:
        result = require_project(name)
        if isinstance(result, str):
            return result
        cfg, project_name = result
        index = storage.load_index(cfg)
        if project_name not in index.projects:
            return f"Project '{project_name}' not found."

        index.projects[project_name].archived = True
        index.projects[project_name].archive_date = date.today().isoformat()
        index.projects[project_name].purgeable = purgeable
        storage.save_index(cfg, index)
        # Clear session active if archiving the current session project
        if state.get_session_active() == project_name:
            state.clear_session_active()

        # Revoke all permissions granted by setup_permissions
        revoke_summary = ""
        try:
            from server.tools.perms_grant import revoke_all_permissions
            meta = storage.load_meta(cfg, project_name)
            counts = revoke_all_permissions(meta, cfg)
            total = sum(counts.values())
            if total > 0:
                parts = []
                if counts["sandbox_paths"]:
                    parts.append(f"{counts['sandbox_paths']} sandbox path(s)")
                if counts["mcp_rules"]:
                    parts.append(f"{counts['mcp_rules']} MCP")
                revoke_summary = f" Revoked {total} permission rule(s) ({', '.join(parts)})."
        except Exception:  # noqa: BLE001
            pass  # Archive succeeds even if revocation fails

        # Build trello_move hint if project has a Trello card and archived list mapping
        trello_move_hint = ""
        try:
            if not meta:
                meta = storage.load_meta(cfg, project_name)
            if meta.trello_card_id:
                mappings = _resolve_list_mappings(cfg, meta)
                if mappings.archived:
                    trello_move_hint = (
                        f"\ntrello_move: {{\"card_id\": \"{meta.trello_card_id}\", "
                        f"\"target_list\": \"{mappings.archived}\"}}"
                    )
        except Exception:  # noqa: BLE001
            pass  # Archive succeeds even if hint generation fails

        # Build trash info hint
        trash_hint = ""
        try:
            archive_dest = Path(cfg.archive.destination).expanduser()
            trash_loc = archive_dest / ".trash"
            grace = cfg.archive.trash_grace_days
            expiry = (date.today() + timedelta(days=grace)).isoformat()
            trash_hint = (
                f"\nTracking data moved to {trash_loc}/ "
                f"(permanent deletion after {expiry}, {grace}-day grace period)."
            )
        except Exception:  # noqa: BLE001
            pass  # Archive succeeds even if hint generation fails

        return f"Archived project '{project_name}'.{revoke_summary}{trash_hint}{trello_move_hint}"

    @app.tool(description="List or execute purge of archived projects older than purge_after_days.")
    def proj_purge_archive(confirm: bool = False) -> str:
        import shutil

        cfg = require_config()
        if cfg.archive.purge_after_days is None:
            return "Purge not configured. Set archive.purge_after_days via config_update or /proj:init-plugin."

        index = storage.load_index(cfg)
        today = date.today()
        candidates = []
        for name, entry in list(index.projects.items()):
            if not entry.archived or not entry.purgeable or not entry.archive_date:
                continue
            archive_dt = date.fromisoformat(entry.archive_date)
            days_since = (today - archive_dt).days
            if days_since >= cfg.archive.purge_after_days:
                candidates.append({"name": name, "archive_date": entry.archive_date, "days_since": days_since})

        if not candidates:
            return "No projects eligible for purge."

        if not confirm:
            return json.dumps({"candidates": candidates, "count": len(candidates)})

        # Actually purge — move to .trash/ instead of immediate deletion
        import tarfile
        from datetime import datetime, timedelta

        archive_dest = Path(cfg.archive.destination).expanduser()
        trash_dir = archive_dest / ".trash"
        trash_dir.mkdir(parents=True, exist_ok=True)

        # Prepare backup directory for pre-purge tarball snapshots
        backup_dir = Path(cfg.tracking_dir).expanduser() / ".archive-backups"
        backup_dir.mkdir(parents=True, exist_ok=True)

        purged = []
        backup_paths: list[str] = []
        for c in candidates:
            name = c["name"]
            tracking_path = Path(cfg.tracking_dir).expanduser() / name
            if tracking_path.exists():
                # Create a tarball backup before purging
                backup_path = backup_dir / f"{name}-{datetime.now().strftime('%Y%m%dT%H%M%S')}.tar.gz"
                try:
                    with tarfile.open(backup_path, "w:gz") as tar:
                        tar.add(str(tracking_path), arcname=name)
                    backup_paths.append(str(backup_path))
                except Exception:  # noqa: BLE001
                    # Backup failed — skip purge for this project to avoid data loss
                    continue

                timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
                trash_dest = trash_dir / f"{name}-{timestamp}"
                try:
                    shutil.move(str(tracking_path), str(trash_dest))
                except (OSError, shutil.Error):
                    # Move to trash failed — skip purge for this project
                    continue
            del index.projects[name]
            purged.append(name)
        storage.save_index(cfg, index)

        # Clean up backups older than backup_retention_days
        expired_backups = 0
        if backup_dir.exists():
            cutoff = datetime.now() - timedelta(days=cfg.archive.backup_retention_days)
            for bf in backup_dir.iterdir():
                if not bf.is_file() or not bf.name.endswith(".tar.gz"):
                    continue
                try:
                    mtime = datetime.fromtimestamp(bf.stat().st_mtime)
                    if mtime < cutoff:
                        bf.unlink()
                        expired_backups += 1
                except Exception:  # noqa: BLE001
                    continue

        # Sweep .trash/ for entries older than trash_grace_days
        swept = 0
        if trash_dir.exists():
            grace = cfg.archive.trash_grace_days
            now = datetime.now()
            for entry in trash_dir.iterdir():
                if not entry.is_dir():
                    continue
                # Parse timestamp from directory name: <name>-<YYYYMMDDTHHmmss>
                parts = entry.name.rsplit("-", 1)
                if len(parts) != 2:
                    continue
                try:
                    entry_time = datetime.strptime(parts[1], "%Y%m%dT%H%M%S")
                except ValueError:
                    continue
                if (now - entry_time).days >= grace:
                    shutil.rmtree(entry, ignore_errors=True)
                    swept += 1

        sweep_note = f" Swept {swept} expired trash entries." if swept else ""
        backup_note = f" Backups: {', '.join(backup_paths)}." if backup_paths else ""
        expired_note = f" Removed {expired_backups} expired backup(s)." if expired_backups else ""
        return f"Purged {len(purged)} projects: {', '.join(purged)}{backup_note}{expired_note}{sweep_note}"

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
        if not Path(abs_path).is_dir():
            return f"Path '{abs_path}' does not exist or is not a directory."
        meta.repos.append(RepoEntry(label=label, path=abs_path, claudemd=claudemd, reference=reference))
        storage.save_meta(cfg, meta)

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
        found = next((r for r in meta.repos if r.label == label), None)
        if found is None:
            return f"No repo with label '{label}' found in project '{name}'."
        if len(meta.repos) <= 1:
            return "Cannot remove the last repo from a project. Use /proj:archive to remove the entire project instead."
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
        meta = storage.load_meta(cfg, name)
        msg = f"Loaded project '{name}' for this session."
        # Detect old single-path format
        raw = storage._load_yaml(storage.meta_path(cfg, name))
        if raw.get("path") and (not raw.get("repos") or raw.get("repos") == []):
            msg += "\n\n⚠️ Project uses legacy single-path format. Run `/proj:migrate-dirs` to upgrade to multi-dir format."
        # Include paths/mcp_servers for hooks (auto-repair on load)
        paths = [r.path for r in meta.repos if not r.reference]
        if cfg.tracking_dir:
            paths.append(str(Path(cfg.tracking_dir).expanduser().resolve()))
        return json.dumps({
            "message": msg,
            "project_name": name,
            "paths": paths,
            "mcp_servers": [],
        })

    @app.tool(description="Migrate a project from legacy single-path format to multi-dir repos format.")
    def proj_migrate_dirs(
        label: str = "code",
        project_name: str | None = None,
        dry_run: bool = False,
    ) -> str:
        cfg = require_config()
        project_name = state.resolve_project(project_name)
        if not project_name:
            return "No active project."
        raw = storage._load_yaml(storage.meta_path(cfg, project_name))
        path_val = raw.get("path")
        repos_val = raw.get("repos", [])
        if not isinstance(path_val, str) or not path_val or (isinstance(repos_val, list) and repos_val):
            return f"Project '{project_name}' already uses multi-dir format. No migration needed."
        if dry_run:
            return (
                f"Dry run — migration preview for '{project_name}':\n"
                f"  Old format: path: {path_val}\n"
                f"  New format: repos:\n"
                f"    - label: {label}\n"
                f"      path: {path_val}\n"
                f"      claudemd: false\n"
                f"      reference: false"
            )
        new_repo = {"label": label, "path": path_val, "claudemd": False, "reference": False}
        raw["repos"] = [new_repo]
        del raw["path"]
        storage._write_yaml(storage.meta_path(cfg, project_name), raw)
        return json.dumps({"migrated": True, "project": project_name, "label": label, "path": path_val})
