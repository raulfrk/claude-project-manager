"""MCP tools for project lifecycle management."""

from __future__ import annotations

import json
import logging
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from server.lib import state, storage
from server.lib.models import (
    JsonValue,
    ProjConfig,
    ProjectEntry,
    ProjectMeta,
    ProjectPermissions,
    RepoEntry,
    TrelloListMappings,
    validate_project_name,
)
from server.tools.config import require_config, require_project

logger = logging.getLogger(__name__)


def _resolve_list_mappings(cfg: ProjConfig, meta: ProjectMeta) -> TrelloListMappings:
    """Resolve effective Trello list mappings: per-project override falls back to global."""

    if not isinstance(cfg, ProjConfig):
        raise TypeError(f"Expected ProjConfig, got {type(cfg).__name__}")
    if meta.trello.list_mappings is not None:
        return meta.trello.list_mappings
    return cfg.trello.list_mappings


if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def _resolve_router_socket_path() -> str | None:
    """Read the router server socket path from the registry file."""

    registry_file = Path.home() / ".claude" / "sockets" / "router"
    if not registry_file.exists():
        return _fallback_router_socket()
    try:
        path = registry_file.read_text().strip()
        if path and Path(path).exists():
            return path
    except (FileNotFoundError, OSError):
        pass
    return _fallback_router_socket()


def _fallback_router_socket() -> str | None:
    import tempfile

    _tmp = tempfile.gettempdir()
    candidates = sorted(
        Path(_tmp).glob("claude-cpm-router-*.sock"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if candidates:
        return str(candidates[0])
    fallback = Path(_tmp) / "claude-cpm-router.sock"
    if fallback.exists():
        return str(fallback)
    return None


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


def _enrich_trello_sync(cfg: ProjConfig) -> dict[str, JsonValue]:
    """Return Trello sync config dict with list_mappings resolved to IDs."""
    from server.tools.todos import _enrich_trello_dict, _resolve_trello_list_ids

    trello_dict = cfg.trello.to_dict()
    trello_list_ids = _resolve_trello_list_ids(cfg)
    return _enrich_trello_dict(trello_dict, trello_list_ids)


def register(app: FastMCP) -> None:
    """Register project management tools with the MCP app.

    Registers proj_init, proj_list, proj_list_full, proj_get,
    proj_get_active, proj_update_meta, proj_archive_preflight,
    proj_archive, proj_add_repo, proj_remove_repo,
    proj_set_permissions, proj_load_session, and proj_migrate_dirs.
    """

    @app.tool(
        description=(
            "Initialize tracking for a new project. Accepts multiple"
            " directories via the dirs parameter (list of"
            " {path, label} dicts). The legacy path parameter is"
            " kept for backward compatibility and creates a single"
            " directory with label 'code'."
        )
    )
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
            return json.dumps({"error": err})

        cfg = require_config()
        index = storage.load_index(cfg)

        if name in index.projects:
            return json.dumps({"error": f"Project '{name}' already exists."})

        # Build list of RepoEntry from dirs or legacy path parameter
        repo_entries: list[RepoEntry] = []
        if dirs:
            if path:
                return json.dumps({"error": "Provide either 'dirs' or 'path', not both."})
            labels_seen: set[str] = set()
            for d in dirs:
                d_path = d.get("path", "")
                d_label = d.get("label", "")
                if not d_path:
                    return json.dumps({"error": "Each directory entry must have a 'path'."})
                if not d_label:
                    return json.dumps({"error": "Each directory entry must have a 'label'."})
                if d_label in labels_seen:
                    return json.dumps(
                        {
                            "error": (
                                f"Duplicate label '{d_label}'."
                                " Each directory must have a"
                                " unique label."
                            )
                        }
                    )
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
                return json.dumps(
                    {
                        "error": (
                            f"No path provided for project"
                            f" '{name}' and no"
                            " projects_base_dir configured. "
                            "Provide an explicit path or set"
                            " projects_base_dir via"
                            " /proj:init-plugin."
                        )
                    }
                )
            repo_entries.append(RepoEntry(label="code", path=resolved_path))

        if not repo_entries:
            return json.dumps({"error": "At least one directory is required."})

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

        # Best-effort hook auto-discovery
        try:
            import httpx

            sock_path = _resolve_router_socket_path()
            if not sock_path:
                raise FileNotFoundError("No router socket found")
            transport = httpx.HTTPTransport(uds=sock_path)
            with httpx.Client(transport=transport, timeout=5.0) as client:
                client.post(
                    "http://localhost/hook",
                    json={"tool": "router_sync_tool", "params": {}},
                )
        except Exception:
            logger.debug("Router server sync failed", exc_info=True)

        first_repo = str(repo_entries[0].path) if repo_entries else ""
        return json.dumps(
            {
                "result": f"Initialized project '{name}' at {tracking}",
                "project_name": name,
                "repo_path": first_repo,
                "paths": [r.path for r in repo_entries],
                "mcp_servers": [],
                "todoist_project_id": meta.todoist_project_id,
                "trello_card_id": meta.trello_card_id,
                "sync": {
                    "trello": _enrich_trello_sync(cfg),
                },
            }
        )

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
            return json.dumps(
                {
                    "error": f"Unknown integration '{integration_filter}'. "
                    f"Valid values: {', '.join(sorted(valid_integrations))}",
                }
            )

        entries = [p for p in index.projects.values() if include_archived or not p.archived]

        projects: list[dict[str, JsonValue]] = []
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
                if (
                    (integration_filter == "todoist" and meta.todoist_project_id)
                    or (integration_filter == "trello" and meta.trello_card_id)
                    or (integration_filter == "jira" and meta.jira_issue_key)
                ):
                    has_integration = True
                if not has_integration:
                    continue

            # Build integration summary
            integrations: dict[str, str | None] = {
                "todoist": meta.todoist_project_id,
                "trello": meta.trello_card_id,
                "jira": meta.jira_issue_key,
            }

            projects.append(
                {
                    "name": meta.name,
                    "description": meta.description,
                    "status": meta.status,
                    "priority": meta.priority,
                    "tags": meta.tags,
                    "repos": [r.to_dict() for r in meta.repos],
                    "dates": meta.dates.to_dict(),
                    "archived": entry.archived,
                    "integrations": {k: v for k, v in integrations.items() if v},
                }
            )

        return json.dumps(
            {"projects": projects, "count": len(projects), "warnings": warnings}, indent=2
        )

    @app.tool(description="Get full details of a project (defaults to active project).")
    def proj_get(name: str | None = None) -> str:
        cfg = require_config()
        index = storage.load_index(cfg)
        project_name = state.resolve_project(name)
        if not project_name:
            return json.dumps({"error": "No active project."})
        if project_name not in index.projects:
            return json.dumps({"error": f"Project '{project_name}' not found."})
        meta = storage.load_meta(cfg, project_name)
        return json.dumps(meta.to_dict(), indent=2)

    @app.tool(description="Get the currently active project.")
    def proj_get_active() -> str:
        cfg = require_config()
        name = state.get_session_active()
        if not name:
            return json.dumps({"error": "No active project."})
        index = storage.load_index(cfg)
        if name not in index.projects:
            return json.dumps({"error": "No active project."})
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
        todoist_project_id: str | None = None,
        trello_card_id: str | None = None,
    ) -> str:
        result = require_project(name)
        if isinstance(result, str):
            return json.dumps({"status": "not_found", "project_name": name, "error": result})
        cfg, project_name = result
        try:
            meta = storage.load_meta(cfg, project_name)
        except FileNotFoundError:
            return json.dumps({"status": "not_found", "project_name": project_name})
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
        if todoist_project_id is not None:
            meta.todoist_project_id = todoist_project_id
        if trello_card_id is not None:
            meta.trello_card_id = trello_card_id
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
                        f'\ntrello_move: {{"card_id": "{meta.trello_card_id}", '
                        f'"target_list": "{target_list}"}}'
                    )
            except Exception:
                logger.debug("Trello move hint generation failed", exc_info=True)

        result_dict: dict[str, JsonValue] = {
            "result": f"Updated project '{project_name}'.",
            "project_name": project_name,
        }
        if trello_move_hint:
            # Parse the trello_move hint to extract card_id and target_list
            import re

            match = re.search(
                r'trello_move: \{"card_id": "([^"]+)", "target_list": "([^"]+)"\}', trello_move_hint
            )
            if match:
                result_dict["trello_move"] = {
                    "card_id": match.group(1),
                    "target_list": match.group(2),
                }
        return json.dumps(result_dict)

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
            return json.dumps({"error": f"Project '{project_name}' not found."})

        entry = index.projects[project_name]
        if entry.archived:
            return json.dumps({"error": f"Project '{project_name}' is already archived."})

        try:
            meta = storage.load_meta(cfg, project_name)
        except FileNotFoundError:
            return json.dumps({"error": f"meta.yaml missing for project '{project_name}'."})

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
            return json.dumps({"error": result})
        cfg, project_name = result
        index = storage.load_index(cfg)
        if project_name not in index.projects:
            return json.dumps({"error": f"Project '{project_name}' not found."})

        index.projects[project_name].archived = True
        index.projects[project_name].archive_date = date.today().isoformat()
        index.projects[project_name].purgeable = purgeable
        storage.save_index(cfg, index)
        # Clear session active if archiving the current session project
        if state.get_session_active() == project_name:
            state.clear_session_active()

        # Revoke all permissions granted by setup_permissions
        revoke_summary = ""
        meta = storage.load_meta(cfg, project_name)
        try:
            from server.tools.perms_grant import revoke_all_permissions

            counts = revoke_all_permissions(meta, cfg)
            total = sum(counts.values())
            if total > 0:
                parts = []
                if counts["sandbox_paths"]:
                    parts.append(f"{counts['sandbox_paths']} sandbox path(s)")
                if counts["mcp_rules"]:
                    parts.append(f"{counts['mcp_rules']} MCP")
                revoke_summary = f" Revoked {total} permission rule(s) ({', '.join(parts)})."
        except Exception:
            logger.debug("Permission revocation failed during archive", exc_info=True)

        # Build trello_move hint if project has a Trello card and archived list mapping
        trello_move_hint = ""
        try:
            if not meta:
                meta = storage.load_meta(cfg, project_name)
            if meta.trello_card_id:
                mappings = _resolve_list_mappings(cfg, meta)
                if mappings.archived:
                    trello_move_hint = (
                        f'\ntrello_move: {{"card_id": "{meta.trello_card_id}", '
                        f'"target_list": "{mappings.archived}"}}'
                    )
        except Exception:
            logger.debug("Trello move hint generation failed during archive", exc_info=True)

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
        except Exception:
            logger.debug("Trash info hint generation failed during archive", exc_info=True)

        # Build result dict with repo paths
        result_dict = {
            "result": (
                f"Archived project '{project_name}'.{revoke_summary}{trash_hint}{trello_move_hint}"
            ),
            "project_name": project_name,
            "repo_path": meta.repos[0].path if meta.repos else "",
            "paths": [r.path for r in meta.repos],
            "mcp_servers": [],
            "todoist_project_id": meta.todoist_project_id,
            "trello_card_id": meta.trello_card_id,
            "sync": {
                "trello": _enrich_trello_sync(cfg),
            },
        }
        return json.dumps(result_dict)

    @app.tool(description="List or execute purge of archived projects older than purge_after_days.")
    def proj_purge_archive(confirm: bool = False) -> str:
        import shutil

        cfg = require_config()
        if cfg.archive.purge_after_days is None:
            return json.dumps(
                {
                    "error": (
                        "Purge not configured. Set"
                        " archive.purge_after_days via"
                        " config_update or /proj:init-plugin."
                    )
                }
            )

        index = storage.load_index(cfg)
        today = date.today()
        candidates: list[dict[str, JsonValue]] = []
        for name, entry in list(index.projects.items()):
            if not entry.archived or not entry.purgeable or not entry.archive_date:
                continue
            archive_dt = date.fromisoformat(entry.archive_date)
            days_since = (today - archive_dt).days
            if days_since >= cfg.archive.purge_after_days:
                candidates.append(
                    {"name": name, "archive_date": entry.archive_date, "days_since": days_since}
                )

        if not candidates:
            return json.dumps(
                {"result": "No projects eligible for purge.", "candidates": [], "purged": []}
            )

        if not confirm:
            return json.dumps(
                {
                    "result": "Purge candidates listed.",
                    "candidates": candidates,
                    "count": len(candidates),
                    "dry_run": True,
                }
            )

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
            name = str(c["name"])
            tracking_path = Path(cfg.tracking_dir).expanduser() / name
            if tracking_path.exists():
                # Create a tarball backup before purging
                backup_path = (
                    backup_dir / f"{name}-{datetime.now().strftime('%Y%m%dT%H%M%S')}.tar.gz"
                )
                try:
                    with tarfile.open(backup_path, "w:gz") as tar:
                        tar.add(str(tracking_path), arcname=name)
                    backup_paths.append(str(backup_path))
                except Exception:
                    # Backup failed — skip purge for this project to avoid data loss
                    logger.debug("Backup failed for project %s", name, exc_info=True)
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
                except Exception:
                    logger.debug("Failed to clean expired backup %s", bf, exc_info=True)
                    continue

        # Sweep .trash/ for entries older than trash_grace_days
        swept = 0
        if trash_dir.exists():
            grace = cfg.archive.trash_grace_days
            now = datetime.now()
            for trash_entry in trash_dir.iterdir():
                if not trash_entry.is_dir():
                    continue
                # Parse timestamp from directory name: <name>-<YYYYMMDDTHHmmss>
                parts = trash_entry.name.rsplit("-", 1)
                if len(parts) != 2:
                    continue
                try:
                    entry_time = datetime.strptime(parts[1], "%Y%m%dT%H%M%S")
                except ValueError:
                    continue
                if (now - entry_time).days >= grace:
                    shutil.rmtree(trash_entry, ignore_errors=True)
                    swept += 1

        sweep_note = f" Swept {swept} expired trash entries." if swept else ""
        backup_note = f" Backups: {', '.join(backup_paths)}." if backup_paths else ""
        expired_note = f" Removed {expired_backups} expired backup(s)." if expired_backups else ""
        result_msg = (
            f"Purged {len(purged)} projects:"
            f" {', '.join(purged)}"
            f"{backup_note}{expired_note}{sweep_note}"
        )
        return json.dumps(
            {
                "result": result_msg,
                "purged": purged,
                "count": len(purged),
                "backups": backup_paths,
                "expired_backups_removed": expired_backups,
                "trash_swept": swept,
            }
        )

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
            return json.dumps({"error": result})
        cfg, name = result
        meta = storage.load_meta(cfg, name)
        abs_path = str(Path(repo_path).expanduser().resolve())
        if any(r.path == abs_path for r in meta.repos):
            return json.dumps({"error": f"Repo at '{abs_path}' already registered."})
        if any(r.label == label for r in meta.repos):
            return json.dumps(
                {"error": f"Label '{label}' already in use. Choose a different label."}
            )
        if not Path(abs_path).is_dir():
            return json.dumps({"error": f"Path '{abs_path}' does not exist or is not a directory."})
        meta.repos.append(
            RepoEntry(label=label, path=abs_path, claudemd=claudemd, reference=reference)
        )
        storage.save_meta(cfg, meta)

        # Build paths list for hooks (writable repos only, not references)
        paths = [r.path for r in meta.repos if not r.reference]
        if reference:
            result_msg = (
                f"Added reference repo '{label}' at {abs_path} to project '{name}' (read-only)."
            )
        else:
            result_msg = f"Added repo '{label}' at {abs_path} to project '{name}'."
        return json.dumps(
            {
                "result": result_msg,
                "paths": paths,
                "path": abs_path,
                "project_name": name,
                "mcp_servers": [],
                "todoist_project_id": meta.todoist_project_id,
                "trello_card_id": meta.trello_card_id,
            }
        )

    @app.tool(
        description="Remove a repository from a project by label (cannot remove the last repo)."
    )
    def proj_remove_repo(
        label: str,
        project_name: str | None = None,
    ) -> str:
        result = require_project(project_name)
        if isinstance(result, str):
            return json.dumps({"error": result})
        cfg, name = result
        meta = storage.load_meta(cfg, name)
        found = next((r for r in meta.repos if r.label == label), None)
        if found is None:
            return json.dumps({"error": f"No repo with label '{label}' found in project '{name}'."})
        if len(meta.repos) <= 1:
            return json.dumps(
                {
                    "error": (
                        "Cannot remove the last repo from a project."
                        " Use /proj:archive to remove the entire"
                        " project instead."
                    )
                }
            )
        meta.repos.remove(found)
        storage.save_meta(cfg, meta)
        # Build paths list for hooks (writable repos only, not references)
        paths = [r.path for r in meta.repos if not r.reference]
        ref_note = " (reference, read-only)" if found.reference else ""
        result_msg = f"Removed repo '{label}' at {found.path}{ref_note} from project '{name}'."
        return json.dumps(
            {
                "result": result_msg,
                "paths": paths,
                "project_name": name,
                "mcp_servers": [],
                "todoist_project_id": meta.todoist_project_id,
                "trello_card_id": meta.trello_card_id,
            }
        )

    @app.tool(description="Set per-project permissions override (null = use global config).")
    def proj_set_permissions(auto_grant: bool | None, project_name: str | None = None) -> str:
        result = require_project(project_name)
        if isinstance(result, str):
            return json.dumps({"error": result})
        cfg, name = result
        meta = storage.load_meta(cfg, name)
        meta.permissions = ProjectPermissions(auto_grant=auto_grant)
        storage.save_meta(cfg, meta)
        auto_grant_state = str(auto_grant) if auto_grant is not None else "use global default"
        return json.dumps(
            {
                "result": f"Set permissions.auto_grant={auto_grant_state} for project '{name}'.",
                "project_name": name,
                "auto_grant": auto_grant,
            }
        )

    @app.tool(description="Set the active project for this session only (not persisted globally).")
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
                return json.dumps({"error": f"Project '{name}' not found. Available: {all_names}"})
            if len(matches) == 1:
                name = matches[0]
            else:
                return json.dumps(
                    {"error": f"Ambiguous match. Did you mean one of: {', '.join(matches)}?"}
                )
        state.set_session_active(name)
        meta = storage.load_meta(cfg, name)
        msg = f"Loaded project '{name}' for this session."
        # Detect old single-path format
        raw = storage._load_yaml(storage.meta_path(cfg, name))
        if raw.get("path") and (not raw.get("repos") or raw.get("repos") == []):
            msg += (
                "\n\n⚠️ Project uses legacy single-path format."
                " Run `/proj:migrate-dirs` to upgrade"
                " to multi-dir format."
            )
        # Include paths/mcp_servers for hooks (auto-repair on load)
        paths = [r.path for r in meta.repos if not r.reference]
        if cfg.tracking_dir:
            paths.append(str(Path(cfg.tracking_dir).expanduser().resolve()))
        return json.dumps(
            {
                "message": msg,
                "project_name": name,
                "paths": paths,
                "mcp_servers": [],
                "todoist_project_id": meta.todoist_project_id or "",
                "trello_card_id": meta.trello_card_id or "",
            }
        )

    def _migrate_single_dir(
        cfg: ProjConfig, project_name: str, label: str, dry_run: bool, timestamp: str
    ) -> dict[str, JsonValue]:
        """Migrate one project from single-path to multi-repo format. Returns result dict."""
        meta_p = storage.meta_path(cfg, project_name)
        if not meta_p.exists():
            return {"project": project_name, "migrated": False, "reason": "meta.yaml missing"}

        raw = storage._load_yaml(meta_p)
        path_val = raw.get("path")
        repos_val = raw.get("repos", [])

        if (
            not isinstance(path_val, str)
            or not path_val
            or (isinstance(repos_val, list) and repos_val)
        ):
            return {"project": project_name, "migrated": False, "reason": "already multi-dir"}

        if dry_run:
            return {
                "project": project_name,
                "migrated": False,
                "dry_run": True,
                "old_path": path_val,
                "new_label": label,
            }

        # Backup
        backup_path = meta_p.with_name(f"meta.yaml.bak-{timestamp}")
        shutil.copy2(meta_p, backup_path)

        try:
            new_repo: dict[str, JsonValue] = {
                "label": label,
                "path": path_val,
                "claudemd": False,
                "reference": False,
            }
            raw["repos"] = [new_repo]
            del raw["path"]
            storage._write_yaml(meta_p, raw)
        except Exception:
            # Rollback
            shutil.copy2(backup_path, meta_p)
            raise

        return {"project": project_name, "migrated": True, "label": label, "old_path": path_val}

    @app.tool(
        description=(
            "Migrate projects from legacy single-path format to"
            " multi-dir repos format. Defaults to all"
            " non-archived projects."
        )
    )
    def proj_migrate_dirs(
        label: str = "code",
        project_name: str | None = None,
        all_projects: bool = True,
        dry_run: bool = False,
    ) -> str:
        cfg = require_config()
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

        if project_name:
            # Single project mode
            names = [project_name]
        elif all_projects:
            # All non-archived projects
            index = storage.load_index(cfg)
            names = [name for name, entry in index.projects.items() if not entry.archived]
        else:
            # Resolve active project
            resolved = state.resolve_project(None)
            if not resolved:
                return json.dumps({"error": "No active project."})
            names = [resolved]

        results = []
        for name in names:
            try:
                result = _migrate_single_dir(cfg, name, label, dry_run, timestamp)
                results.append(result)
            except Exception as e:
                results.append({"project": name, "migrated": False, "error": str(e)})

        migrated = [r for r in results if r.get("migrated")]
        skipped = [r for r in results if not r.get("migrated") and not r.get("error")]
        errors = [r for r in results if r.get("error")]

        return json.dumps(
            {"migrated": migrated, "skipped": skipped, "errors": errors, "dry_run": dry_run}
        )
