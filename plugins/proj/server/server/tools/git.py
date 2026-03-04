"""MCP tools for git integration (optional — graceful degradation)."""

from __future__ import annotations

import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from typing import TYPE_CHECKING

from server.lib import state, storage
from server.tools.config import require_config

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def _run_git(args: list[str], cwd: str) -> list[str]:
    """Run a git command, return stdout lines. Returns [] on any error."""
    try:
        result = subprocess.run(["git", *args], capture_output=True, text=True, cwd=cwd)
        return result.stdout.splitlines() if result.returncode == 0 else []
    except (FileNotFoundError, subprocess.SubprocessError):
        return []


def _git_log(repo_path: str, since_days: int, repo_label: str = "") -> list[str]:
    """Return recent commits from a git repo as one-liner strings. Returns [] if not a git repo."""
    since = str(date.today() - timedelta(days=since_days))
    lines = _run_git(
        [
            "log",
            f"--since={since}",
            "--format=%H|%s|%an|%ad",
            "--date=short",
            "--no-walk=unsorted",
            "-n",
            "50",
        ],
        cwd=repo_path,
    )
    commits = []
    for line in lines:
        line = line.strip()
        if "|" in line:
            sha, subject, author, date_str = line.split("|", 3)
            suffix = f" ({repo_label})" if repo_label else ""
            commits.append(f"{date_str} {sha[:8]} {subject}{suffix}")
    return commits


def _active_branches(repo_path: str) -> list[str]:
    lines = _run_git(["branch", "--format=%(refname:short)"], cwd=repo_path)
    return [b.strip() for b in lines if b.strip()]


def register(app: FastMCP) -> None:
    """Register git_detect_work, git_link_todo, git_suggest_todos, and proj_git_reconcile_todos tools with the MCP app."""

    @app.tool(description="Detect recent git activity across all project repos.")
    def git_detect_work(project_name: str | None = None, since_days: int = 7) -> str:
        cfg = require_config()
        name = state.resolve_project(project_name)
        if not name:
            return "No active project."
        meta = storage.load_meta(cfg, name)
        if not meta.git_enabled:
            return json.dumps({"git_enabled": False, "commits": [], "branches": []})

        all_commits: list[str] = []
        all_branches: list[str] = []
        trackable_repos = [repo for repo in meta.repos if not repo.reference]
        with ThreadPoolExecutor() as executor:
            log_futures = {
                executor.submit(_git_log, repo.path, since_days, repo.label): repo
                for repo in trackable_repos
            }
            branch_futures = {
                executor.submit(_active_branches, repo.path): repo for repo in trackable_repos
            }
            for fut, repo in log_futures.items():
                all_commits.extend(fut.result())
            for fut, repo in branch_futures.items():
                all_branches.extend(f"{repo.label}:{b}" for b in fut.result())

        return json.dumps(
            {
                "git_enabled": True,
                "commits": all_commits,
                "branches": all_branches,
            },
            indent=2,
        )

    @app.tool(description="Link a git branch and/or commit SHA to a todo.")
    def git_link_todo(
        todo_id: str,
        branch: str | None = None,
        commit: str | None = None,
        project_name: str | None = None,
    ) -> str:
        cfg = require_config()
        name = state.resolve_project(project_name)
        if not name:
            return "No active project."
        todos = storage.load_todos(cfg, name)
        todo = next((t for t in todos if t.id == todo_id), None)
        if not todo:
            return f"Todo '{todo_id}' not found."
        if branch:
            todo.git.branch = branch
        if commit and commit not in todo.git.commits:
            todo.git.commits.append(commit[:8])
        from datetime import date as _date

        todo.updated = str(_date.today())
        storage.save_todos(cfg, name, todos)
        return f"Linked git info to {todo_id}: branch={todo.git.branch}, commits={todo.git.commits}"

    @app.tool(
        description=(
            "Run git reconciliation for a project in one call: detects recent commits, "
            "generates todo title suggestions, and returns structured data ready for the "
            "update skill to present to the user. Replaces calling git_detect_work + "
            "git_suggest_todos separately. Returns JSON with keys: "
            "git_enabled, commits, branches, suggestions (list of {repo, subject, sha, date})."
        )
    )
    def proj_git_reconcile_todos(project_name: str | None = None, since_days: int = 7) -> str:
        cfg = require_config()
        name = state.resolve_project(project_name)
        if not name:
            return "No active project."
        meta = storage.load_meta(cfg, name)
        if not meta.git_enabled:
            return json.dumps({"git_enabled": False, "commits": [], "branches": [], "suggestions": []})

        all_commits: list[str] = []
        all_branches: list[str] = []
        suggestions: list[dict[str, str]] = []

        trackable_repos = [repo for repo in meta.repos if not repo.reference]
        with ThreadPoolExecutor() as executor:
            log_futures = {
                executor.submit(_git_log, repo.path, since_days, repo.label): repo
                for repo in trackable_repos
            }
            branch_futures = {
                executor.submit(_active_branches, repo.path): repo for repo in trackable_repos
            }
            repo_commits: dict[str, list[str]] = {}
            for fut, repo in log_futures.items():
                commits = fut.result()
                all_commits.extend(commits)
                repo_commits[repo.label] = commits
            for fut, repo in branch_futures.items():
                all_branches.extend(f"{repo.label}:{b}" for b in fut.result())

        for repo in trackable_repos:
            for line in repo_commits.get(repo.label, []):
                # Format: "YYYY-MM-DD sha8 subject (repo_label)"
                parts = line.split(" ", 2)
                if len(parts) >= 3:
                    date_str, sha, subject_and_repo = parts
                    suffix = f" ({repo.label})"
                    subject = (
                        subject_and_repo[: -len(suffix)]
                        if subject_and_repo.endswith(suffix)
                        else subject_and_repo
                    )
                else:
                    date_str, sha, subject = "", "", line

                suggestions.append({
                    "repo": repo.label,
                    "subject": subject,
                    "sha": sha,
                    "date": date_str,
                })

        return json.dumps(
            {
                "git_enabled": True,
                "commits": all_commits,
                "branches": all_branches,
                "suggestions": suggestions[:20],
            },
            indent=2,
        )

    @app.tool(description="Suggest todo titles based on recent git commit messages.")
    def git_suggest_todos(project_name: str | None = None, since_days: int = 7) -> str:
        cfg = require_config()
        name = state.resolve_project(project_name)
        if not name:
            return "No active project."
        meta = storage.load_meta(cfg, name)
        if not meta.git_enabled:
            return "Git not enabled for this project."

        suggestions: list[str] = []
        for repo in [r for r in meta.repos if not r.reference]:
            commits = _git_log(repo.path, since_days, repo.label)
            for line in commits:
                # Format: "YYYY-MM-DD sha8 subject (repo)" — extract subject
                parts = line.split(" ", 2)
                if len(parts) >= 3:
                    subject_and_repo = parts[2]
                    # Strip trailing " (repo_label)" suffix
                    suffix = f" ({repo.label})"
                    if subject_and_repo.endswith(suffix):
                        subject = subject_and_repo[: -len(suffix)]
                    else:
                        subject = subject_and_repo
                else:
                    subject = line
                suggestions.append(f"[{repo.label}] {subject}")

        if not suggestions:
            return "No recent commits to suggest todos from."
        return "\n".join(suggestions[:20])
