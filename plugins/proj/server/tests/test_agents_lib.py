"""Tests for server.lib.agents helper functions."""

from __future__ import annotations

from pathlib import Path

import pytest

from server.lib import storage
from server.lib.agents import STEP_DEFAULTS, resolve_agent_for_step
from server.lib.models import ProjConfig


@pytest.fixture()
def tmp_cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ProjConfig:
    config_path = tmp_path / "proj.yaml"
    monkeypatch.setattr(storage, "_DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.delenv("PROJ_CONFIG", raising=False)
    cfg = ProjConfig(tracking_dir=str(tmp_path / "tracking"))
    storage.save_config(cfg)
    return cfg


def _make_project_dir(cfg: ProjConfig, project_name: str) -> Path:
    proj_dir = Path(cfg.tracking_dir) / project_name
    proj_dir.mkdir(parents=True, exist_ok=True)
    return proj_dir


class TestStepDefaults:
    def test_define_default(self) -> None:
        assert STEP_DEFAULTS["define"] == "Plan"

    def test_research_default(self) -> None:
        assert STEP_DEFAULTS["research"] == "Explore"

    def test_decompose_default(self) -> None:
        assert STEP_DEFAULTS["decompose"] == "Plan"

    def test_execute_default(self) -> None:
        assert STEP_DEFAULTS["execute"] == "general-purpose"


class TestResolveAgentForStep:
    def test_resolve_no_override_returns_default(self, tmp_cfg: ProjConfig) -> None:
        """No agents.yaml override → returns (STEP_DEFAULTS[step], None)."""
        _make_project_dir(tmp_cfg, "myapp")
        agent, warning = resolve_agent_for_step(tmp_cfg, "myapp", "define")
        assert agent == STEP_DEFAULTS["define"]
        assert warning is None

    def test_resolve_override_file_exists_returns_agent(
        self, tmp_cfg: ProjConfig, tmp_path: Path
    ) -> None:
        """Override set + .claude/agents/<name>.md exists → returns (agent_name, None)."""
        proj_dir = _make_project_dir(tmp_cfg, "myapp")

        # Create a fake repo with .claude/agents/MyAgent.md
        repo_dir = tmp_path / "repo"
        agents_dir = repo_dir / ".claude" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "MyAgent.md").write_text("# MyAgent\n")

        # Set up meta with repo
        from datetime import date

        from server.lib.models import ProjectDates, ProjectMeta, RepoEntry

        meta = ProjectMeta(
            name="myapp",
            repos=[RepoEntry(label="code", path=str(repo_dir))],
            dates=ProjectDates(created=str(date.today()), last_updated=str(date.today())),
        )
        storage.save_meta(tmp_cfg, meta)

        storage.save_agents(
            tmp_cfg,
            "myapp",
            {"version": 1, "agents": {"define": "MyAgent"}},
        )

        agent, warning = resolve_agent_for_step(tmp_cfg, "myapp", "define")
        assert agent == "MyAgent"
        assert warning is None

    def test_resolve_override_file_missing_returns_default_and_warning(
        self, tmp_cfg: ProjConfig, tmp_path: Path
    ) -> None:
        """Override set + file doesn't exist in repo → returns (default, warning_string)."""
        _make_project_dir(tmp_cfg, "myapp")

        # Create repo dir but no agent file
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

        from datetime import date

        from server.lib.models import ProjectDates, ProjectMeta, RepoEntry

        meta = ProjectMeta(
            name="myapp",
            repos=[RepoEntry(label="code", path=str(repo_dir))],
            dates=ProjectDates(created=str(date.today()), last_updated=str(date.today())),
        )
        storage.save_meta(tmp_cfg, meta)

        storage.save_agents(
            tmp_cfg,
            "myapp",
            {"version": 1, "agents": {"research": "GhostAgent"}},
        )

        agent, warning = resolve_agent_for_step(tmp_cfg, "myapp", "research")
        assert agent == STEP_DEFAULTS["research"]
        assert warning is not None
        assert "GhostAgent" in warning

    def test_resolve_no_repos_returns_agent_no_warning(
        self, tmp_cfg: ProjConfig
    ) -> None:
        """Override set + no repos configured → returns (agent_name, None) without validation."""
        _make_project_dir(tmp_cfg, "myapp")

        from datetime import date

        from server.lib.models import ProjectDates, ProjectMeta

        meta = ProjectMeta(
            name="myapp",
            repos=[],
            dates=ProjectDates(created=str(date.today()), last_updated=str(date.today())),
        )
        storage.save_meta(tmp_cfg, meta)

        storage.save_agents(
            tmp_cfg,
            "myapp",
            {"version": 1, "agents": {"execute": "MyExecuteAgent"}},
        )

        agent, warning = resolve_agent_for_step(tmp_cfg, "myapp", "execute")
        assert agent == "MyExecuteAgent"
        assert warning is None

    def test_resolve_unknown_step_raises_value_error(self, tmp_cfg: ProjConfig) -> None:
        """Unknown step → raises ValueError."""
        _make_project_dir(tmp_cfg, "myapp")
        with pytest.raises(ValueError, match="Unknown step"):
            resolve_agent_for_step(tmp_cfg, "myapp", "nonexistent_step")
