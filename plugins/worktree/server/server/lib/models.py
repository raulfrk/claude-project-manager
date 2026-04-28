"""Data models for worktree configuration."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BaseRepo:
    label: str
    path: str  # absolute path as string
    default_branch: str = "main"

    def to_dict(self) -> dict[str, str]:
        return {
            "label": self.label,
            "path": self.path,
            "default_branch": self.default_branch,
        }

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> BaseRepo:
        return cls(
            label=data["label"],
            path=data["path"],
            default_branch=data.get("default_branch", "main"),
        )


@dataclass
class WorktreeEntry:
    """Represents a single git worktree."""

    path: str
    branch: str
    head: str
    bare: bool = False
    detached: bool = False
    locked: bool = False
    prunable: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "branch": self.branch,
            "head": self.head,
            "bare": self.bare,
            "detached": self.detached,
            "locked": self.locked,
            "prunable": self.prunable,
        }


@dataclass
class WorktreeConfig:
    default_worktree_dir: str = "~/worktrees"
    base_repos: list[BaseRepo] = field(default_factory=list)
    zoxide_integration: bool = False
    # When True, ``create_worktree`` runs ``uv sync --frozen --all-groups``
    # in each ``plugins/<x>/server`` and ``plugins/_shared`` dir of the
    # newly created worktree (when those dirs exist + contain a
    # ``pyproject.toml``). Ensures dev/test deps (pytest, basedpyright,
    # pre-commit) are present so quality gates run cleanly out of the box.
    # Default ``True`` because the cpm dogfooding workflow assumes those
    # deps are present; set to ``False`` for non-uv repos. (Todo 822.)
    sync_venvs_on_create: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "version": 1,
            "default_worktree_dir": self.default_worktree_dir,
            "base_repos": [r.to_dict() for r in self.base_repos],
            "zoxide_integration": self.zoxide_integration,
            "sync_venvs_on_create": self.sync_venvs_on_create,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> WorktreeConfig:
        repos_raw = data.get("base_repos", [])
        if not isinstance(repos_raw, list):
            repos_raw = []
        return cls(
            default_worktree_dir=str(data.get("default_worktree_dir", "~/worktrees")),
            base_repos=[BaseRepo.from_dict(r) for r in repos_raw if isinstance(r, dict)],
            zoxide_integration=bool(data.get("zoxide_integration", False)),
            sync_venvs_on_create=bool(data.get("sync_venvs_on_create", True)),
        )
