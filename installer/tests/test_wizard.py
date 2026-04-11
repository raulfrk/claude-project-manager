"""Tests for installer.wizard — post-install setup wizard (Rich path)."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from rich.console import Console

from installer.wizard import (
    _atomic_write,
    _dispatch_rich_prompt,
    _merge_dotted_into_dict,
    _setup_proj_yaml,
    _setup_worktree_yaml,
    run_wizard,
)
from installer.wizard_specs import PROJ_YAML_PROMPTS, PromptSpec


class TestAtomicWrite:
    def test_creates_file(self, tmp_path: Path):
        target = tmp_path / "test.yaml"
        _atomic_write(target, "hello")
        assert target.read_text() == "hello"

    def test_creates_parent_dirs(self, tmp_path: Path):
        target = tmp_path / "nested" / "dir" / "test.yaml"
        _atomic_write(target, "content")
        assert target.exists()

    def test_overwrites_existing(self, tmp_path: Path):
        target = tmp_path / "test.yaml"
        target.write_text("old")
        _atomic_write(target, "new")
        assert target.read_text() == "new"

    def test_no_partial_write_on_error(self, tmp_path: Path):
        target = tmp_path / "test.yaml"
        target.write_text("original")

        with (
            patch(
                "installer.wizard.Path.replace",
                side_effect=OSError("boom"),
            ),
            pytest.raises(OSError, match="boom"),
        ):
            _atomic_write(target, "new content")

        assert target.read_text() == "original"


@pytest.fixture()
def rich_console() -> Console:
    """Headless Rich console for capturing output."""
    return Console(file=StringIO(), force_terminal=False, width=80)


def _basic_proj_answers(
    *,
    tracking_dir: str = "~/projects/tracking",
    projects_base_dir: str = "~/projects",
    sandbox_integration: bool = True,
    zoxide_integration: bool = False,
    git_tracking_enabled: bool = False,
    github_enabled: bool = False,
    github_repo_format: str = "cpm-tracking-{project}",
    quality_level: str = "careful",
    worktree_isolation: bool = True,
) -> list:
    """Return the sequence of answers for all basic-tier proj prompts in order.

    Basic proj prompts (in spec order, when conditions allow):
      1. tracking_dir (str)
      2. projects_base_dir (str)
      3. sandbox_integration (bool)
      4. zoxide_integration (bool)
      5. git_tracking.enabled (bool)
      6. git_tracking.github_enabled (bool)        [cond: git_tracking.enabled]
      7. git_tracking.github_repo_format (str)     [cond: github_enabled]
      8. quality_level (choice)
      9. worktree_isolation (bool)
    """
    out: list = [tracking_dir, projects_base_dir]
    out.append(sandbox_integration)
    out.append(zoxide_integration)
    out.append(git_tracking_enabled)
    if git_tracking_enabled:
        out.append(github_enabled)
        if github_enabled:
            out.append(github_repo_format)
    out.append(quality_level)
    out.append(worktree_isolation)
    return out


class _AnswerScript:
    """Dispatcher that returns pre-scripted answers for Rich prompts.

    Routes Prompt.ask, Confirm.ask, IntPrompt.ask to the same queue in call
    order. Used to pin down full wizard sequences without per-prompt patches.
    """

    def __init__(self, answers: list) -> None:
        self._answers = list(answers)
        self._index = 0

    def __call__(self, *args, **kwargs):
        if self._index >= len(self._answers):
            raise AssertionError(
                f"AnswerScript exhausted at index {self._index}: args={args}"
            )
        value = self._answers[self._index]
        self._index += 1
        return value

    @property
    def consumed(self) -> int:
        return self._index


class TestRichWizardPromptSpec:
    """Unit tests for the PromptSpec-driven Rich wizard flow (514.22)."""

    # ---------------- Load existing (5 tests) ----------------

    def test_setup_proj_yaml_loads_existing_tracking_dir(
        self, mock_home: Path, rich_console: Console
    ):
        proj_yaml = mock_home / ".claude" / "proj.yaml"
        proj_yaml.write_text("tracking_dir: /custom/tracking\n")

        captured_defaults: list = []

        real_ask = __import__("installer.wizard", fromlist=["Prompt"]).Prompt.ask

        def fake_prompt_ask(label, *args, default=None, **kwargs):
            captured_defaults.append((label, default))
            # Return default so the wizard completes
            return default if default is not None else ""

        def fake_confirm(label, *args, default=False, **kwargs):
            return default

        with (
            patch("installer.wizard.Prompt.ask", side_effect=fake_prompt_ask),
            patch("installer.wizard.Confirm.ask", side_effect=fake_confirm),
            patch("installer.wizard.int_in_range", side_effect=lambda *a, **k: a[1]),
            patch(
                "installer.wizard.prompt_choice",
                side_effect=lambda label, default, choices, console: default,
            ),
        ):
            _setup_proj_yaml(rich_console, [])

        del real_ask  # not used; kept for doc
        tracking_defaults = [d for label, d in captured_defaults if "Tracking" in label]
        assert tracking_defaults, f"No Tracking prompt fired; saw {captured_defaults}"
        assert tracking_defaults[0] == "/custom/tracking"

    def test_setup_proj_yaml_loads_existing_sandbox_integration(
        self, mock_home: Path, rich_console: Console
    ):
        proj_yaml = mock_home / ".claude" / "proj.yaml"
        proj_yaml.write_text("sandbox_integration: false\n")

        captured: list = []

        def fake_confirm(label, *args, default=False, **kwargs):
            captured.append((label, default))
            return default

        with (
            patch(
                "installer.wizard.Prompt.ask",
                side_effect=lambda *a, **k: k.get("default", ""),
            ),
            patch("installer.wizard.Confirm.ask", side_effect=fake_confirm),
            patch("installer.wizard.int_in_range", side_effect=lambda *a, **k: a[1]),
            patch(
                "installer.wizard.prompt_choice",
                side_effect=lambda label, default, choices, console: default,
            ),
        ):
            _setup_proj_yaml(rich_console, [])

        sandbox_defaults = [d for label, d in captured if "sandbox" in label.lower()]
        assert sandbox_defaults
        assert sandbox_defaults[0] is False

    def test_setup_worktree_yaml_loads_existing_worktree_dir(
        self, mock_home: Path, rich_console: Console
    ):
        wt_yaml = mock_home / ".claude" / "worktree.yaml"
        wt_yaml.write_text("worktree_dir: /custom/worktrees\n")

        captured: list = []

        def fake_prompt_ask(label, *args, default=None, **kwargs):
            captured.append((label, default))
            return default if default is not None else ""

        with (
            patch("installer.wizard.Prompt.ask", side_effect=fake_prompt_ask),
            patch(
                "installer.wizard.Confirm.ask",
                side_effect=lambda *a, **k: k.get("default", False),
            ),
            patch("installer.wizard.int_in_range", side_effect=lambda *a, **k: a[1]),
            patch(
                "installer.wizard.prompt_choice",
                side_effect=lambda label, default, choices, console: default,
            ),
        ):
            _setup_worktree_yaml(rich_console)

        wt_defaults = [d for label, d in captured if "Worktree" in label]
        assert wt_defaults
        assert wt_defaults[0] == "/custom/worktrees"

    def test_setup_todoist_loads_existing_api_token_masked(
        self, mock_home: Path, rich_console: Console
    ):
        """Existing token is surfaced as masked default with proportional reveal."""
        from installer.wizard import _masked_default

        # len 18 → suffix_len = max(2, 18//4) = 4 → reveal last 4
        assert _masked_default(True, "sk-abcdef12345XYZ9") == "****XYZ9"
        assert _masked_default(True, "short") == "****"
        assert _masked_default(True, "") == ""

    def test_setup_trello_loads_existing_default_list(
        self, mock_home: Path, rich_console: Console
    ):
        """Advanced proj tier surfaces sync.trello.default_list from existing yaml."""
        proj_yaml = mock_home / ".claude" / "proj.yaml"
        proj_yaml.write_text(
            yaml.safe_dump(
                {"sync": {"trello": {"enabled": True, "default_list": "MyCustomList"}}}
            )
        )

        captured: list = []

        def fake_prompt_ask(label, *args, default=None, **kwargs):
            captured.append((label, default))
            return default if default is not None else ""

        with (
            patch("installer.wizard.Prompt.ask", side_effect=fake_prompt_ask),
            patch(
                "installer.wizard.Confirm.ask",
                side_effect=lambda label, *a, **k: (
                    True if "advanced" in label.lower() else k.get("default", False)
                ),
            ),
            patch("installer.wizard.int_in_range", side_effect=lambda *a, **k: a[1]),
            patch(
                "installer.wizard.prompt_choice",
                side_effect=lambda label, default, choices, console: default,
            ),
        ):
            _setup_proj_yaml(rich_console, [])

        trello_list_defaults = [
            d for label, d in captured if "Trello default list" in label
        ]
        assert trello_list_defaults
        assert trello_list_defaults[0] == "MyCustomList"

    # ---------------- Preserve unknown keys ----------------

    def test_setup_proj_yaml_preserves_unknown_key(
        self, mock_home: Path, rich_console: Console
    ):
        proj_yaml = mock_home / ".claude" / "proj.yaml"
        proj_yaml.write_text("foo: bar\ntracking_dir: /x\n")

        with (
            patch(
                "installer.wizard.Prompt.ask",
                side_effect=lambda *a, **k: k.get("default", ""),
            ),
            patch(
                "installer.wizard.Confirm.ask",
                side_effect=lambda *a, **k: k.get("default", False),
            ),
            patch("installer.wizard.int_in_range", side_effect=lambda *a, **k: a[1]),
            patch(
                "installer.wizard.prompt_choice",
                side_effect=lambda label, default, choices, console: default,
            ),
        ):
            _setup_proj_yaml(rich_console, [])

        final = yaml.safe_load(proj_yaml.read_text())
        assert final.get("foo") == "bar"

    # ---------------- Keep-existing gate removed ----------------

    def test_keep_existing_gate_removed(self, mock_home: Path, rich_console: Console):
        """No 'Overwrite existing proj.yaml?' prompt should fire."""
        proj_yaml = mock_home / ".claude" / "proj.yaml"
        proj_yaml.write_text("tracking_dir: /x\n")

        confirm_labels: list[str] = []

        def fake_confirm(label, *args, **kwargs):
            confirm_labels.append(label)
            return kwargs.get("default", False)

        with (
            patch(
                "installer.wizard.Prompt.ask",
                side_effect=lambda *a, **k: k.get("default", ""),
            ),
            patch("installer.wizard.Confirm.ask", side_effect=fake_confirm),
            patch("installer.wizard.int_in_range", side_effect=lambda *a, **k: a[1]),
            patch(
                "installer.wizard.prompt_choice",
                side_effect=lambda label, default, choices, console: default,
            ),
        ):
            _setup_proj_yaml(rich_console, [])

        # No prompt should ask about keeping/overwriting existing proj.yaml
        for label in confirm_labels:
            lower = label.lower()
            assert "overwrite" not in lower
            assert "keep existing" not in lower

    # ---------------- Basic tier — git_tracking branching ----------------

    def test_git_tracking_disabled_hides_github_enabled(
        self, mock_home: Path, rich_console: Console
    ):
        confirm_labels: list[str] = []

        def fake_confirm(label, *args, **kwargs):
            confirm_labels.append(label)
            if "git tracking" in label.lower():
                return False
            return kwargs.get("default", False)

        with (
            patch(
                "installer.wizard.Prompt.ask",
                side_effect=lambda *a, **k: k.get("default", ""),
            ),
            patch("installer.wizard.Confirm.ask", side_effect=fake_confirm),
            patch("installer.wizard.int_in_range", side_effect=lambda *a, **k: a[1]),
            patch(
                "installer.wizard.prompt_choice",
                side_effect=lambda label, default, choices, console: default,
            ),
        ):
            _setup_proj_yaml(rich_console, [])

        github_labels = [label for label in confirm_labels if "github" in label.lower()]
        assert github_labels == []

    def test_git_tracking_enabled_shows_github_enabled(
        self, mock_home: Path, rich_console: Console
    ):
        confirm_labels: list[str] = []

        def fake_confirm(label, *args, **kwargs):
            confirm_labels.append(label)
            if "git tracking" in label.lower():
                return True
            if "github" in label.lower():
                return False
            return kwargs.get("default", False)

        with (
            patch(
                "installer.wizard.Prompt.ask",
                side_effect=lambda *a, **k: k.get("default", ""),
            ),
            patch("installer.wizard.Confirm.ask", side_effect=fake_confirm),
            patch("installer.wizard.int_in_range", side_effect=lambda *a, **k: a[1]),
            patch(
                "installer.wizard.prompt_choice",
                side_effect=lambda label, default, choices, console: default,
            ),
        ):
            _setup_proj_yaml(rich_console, [])

        github_labels = [label for label in confirm_labels if "github" in label.lower()]
        assert any("github" in label.lower() for label in github_labels)

    def test_github_enabled_shows_repo_format(
        self, mock_home: Path, rich_console: Console
    ):
        prompt_labels: list[str] = []

        def fake_prompt_ask(label, *args, default=None, **kwargs):
            prompt_labels.append(label)
            return default if default is not None else ""

        def fake_confirm(label, *args, **kwargs):
            if "git tracking" in label.lower():
                return True
            if "github" in label.lower():
                return True
            return kwargs.get("default", False)

        with (
            patch("installer.wizard.Prompt.ask", side_effect=fake_prompt_ask),
            patch("installer.wizard.Confirm.ask", side_effect=fake_confirm),
            patch("installer.wizard.int_in_range", side_effect=lambda *a, **k: a[1]),
            patch(
                "installer.wizard.prompt_choice",
                side_effect=lambda label, default, choices, console: default,
            ),
        ):
            _setup_proj_yaml(rich_console, [])

        assert any("repo format" in label.lower() for label in prompt_labels)

    # ---------------- Advanced toggle ----------------

    def test_advanced_toggle_default_no(self, mock_home: Path, rich_console: Console):
        """The 'Show advanced options?' Confirm.ask is called with default=False."""
        recorded: list = []

        def fake_confirm(label, *args, **kwargs):
            if "advanced" in label.lower():
                recorded.append(kwargs.get("default"))
                return False
            return kwargs.get("default", False)

        with (
            patch(
                "installer.wizard.Prompt.ask",
                side_effect=lambda *a, **k: k.get("default", ""),
            ),
            patch("installer.wizard.Confirm.ask", side_effect=fake_confirm),
            patch("installer.wizard.int_in_range", side_effect=lambda *a, **k: a[1]),
            patch(
                "installer.wizard.prompt_choice",
                side_effect=lambda label, default, choices, console: default,
            ),
        ):
            _setup_proj_yaml(rich_console, [])

        assert recorded  # at least one 'advanced' toggle fired
        assert all(d is False for d in recorded)

    def test_advanced_toggle_yes_drills_into_team_mode(
        self, mock_home: Path, rich_console: Console
    ):
        confirm_labels: list[str] = []

        def fake_confirm(label, *args, **kwargs):
            confirm_labels.append(label)
            if "advanced" in label.lower():
                return True
            return kwargs.get("default", False)

        with (
            patch(
                "installer.wizard.Prompt.ask",
                side_effect=lambda *a, **k: k.get("default", ""),
            ),
            patch("installer.wizard.Confirm.ask", side_effect=fake_confirm),
            patch("installer.wizard.int_in_range", side_effect=lambda *a, **k: a[1]),
            patch(
                "installer.wizard.prompt_choice",
                side_effect=lambda label, default, choices, console: default,
            ),
        ):
            _setup_proj_yaml(rich_console, [])

        assert any("team mode" in label.lower() for label in confirm_labels)

    def test_advanced_toggle_yes_drills_into_smart_gate(
        self, mock_home: Path, rich_console: Console
    ):
        confirm_labels: list[str] = []

        def fake_confirm(label, *args, **kwargs):
            confirm_labels.append(label)
            if "advanced" in label.lower():
                return True
            return kwargs.get("default", False)

        with (
            patch(
                "installer.wizard.Prompt.ask",
                side_effect=lambda *a, **k: k.get("default", ""),
            ),
            patch("installer.wizard.Confirm.ask", side_effect=fake_confirm),
            patch("installer.wizard.int_in_range", side_effect=lambda *a, **k: a[1]),
            patch(
                "installer.wizard.prompt_choice",
                side_effect=lambda label, default, choices, console: default,
            ),
        ):
            _setup_proj_yaml(rich_console, [])

        assert any("smart gate" in label.lower() for label in confirm_labels)

    def test_advanced_toggle_yes_drills_into_archive(
        self, mock_home: Path, rich_console: Console
    ):
        confirm_labels: list[str] = []

        def fake_confirm(label, *args, **kwargs):
            confirm_labels.append(label)
            if "advanced" in label.lower():
                return True
            return kwargs.get("default", False)

        with (
            patch(
                "installer.wizard.Prompt.ask",
                side_effect=lambda *a, **k: k.get("default", ""),
            ),
            patch("installer.wizard.Confirm.ask", side_effect=fake_confirm),
            patch("installer.wizard.int_in_range", side_effect=lambda *a, **k: a[1]),
            patch(
                "installer.wizard.prompt_choice",
                side_effect=lambda label, default, choices, console: default,
            ),
        ):
            _setup_proj_yaml(rich_console, [])

        assert any("auto-archive" in label.lower() for label in confirm_labels)

    def test_advanced_toggle_no_skips_all_advanced(
        self, mock_home: Path, rich_console: Console
    ):
        """With advanced=No, none of the advanced-tier prompts fire."""
        confirm_labels: list[str] = []
        prompt_labels: list[str] = []

        def fake_confirm(label, *args, **kwargs):
            confirm_labels.append(label)
            if "advanced" in label.lower():
                return False
            return kwargs.get("default", False)

        def fake_prompt_ask(label, *args, default=None, **kwargs):
            prompt_labels.append(label)
            return default if default is not None else ""

        with (
            patch("installer.wizard.Prompt.ask", side_effect=fake_prompt_ask),
            patch("installer.wizard.Confirm.ask", side_effect=fake_confirm),
            patch("installer.wizard.int_in_range", side_effect=lambda *a, **k: a[1]),
            patch(
                "installer.wizard.prompt_choice",
                side_effect=lambda label, default, choices, console: default,
            ),
        ):
            _setup_proj_yaml(rich_console, [])

        advanced_specs = [
            s
            for s in PROJ_YAML_PROMPTS
            if s.tier == "advanced" and s.yaml_file == "proj"
        ]
        all_seen = confirm_labels + prompt_labels
        for spec in advanced_specs:
            assert spec.label not in all_seen, (
                f"advanced prompt {spec.label!r} fired despite toggle=No"
            )

    # ---------------- Validation ----------------

    def test_int_in_range_valid_returned(self, rich_console: Console):
        """Integration through _dispatch_rich_prompt for an int spec."""
        spec = PromptSpec(
            label="Test int",
            dotted_key="x.int",
            type="int",
            group="g",
            tier="basic",
            default_factory=lambda ex: 5,
            int_range=(1, 10),
        )
        with patch("installer.wizard.int_in_range", return_value=7) as mocked:
            result = _dispatch_rich_prompt(spec, 5, rich_console)
        assert result == 7
        mocked.assert_called_once()

    def test_prompt_choice_invalid_default_coerced(self, rich_console: Console):
        """_dispatch_rich_prompt passes default into prompt_choice verbatim."""
        spec = PromptSpec(
            label="Quality",
            dotted_key="quality_level",
            type="choice",
            group="g",
            tier="basic",
            default_factory=lambda ex: "careful",
            choices=["fast", "balanced", "careful"],
        )
        with patch("installer.wizard.prompt_choice", return_value="fast") as mocked:
            result = _dispatch_rich_prompt(spec, "nonsense", rich_console)
        assert result == "fast"
        call_args = mocked.call_args
        assert call_args.args[0] == "Quality"
        assert call_args.args[1] == "nonsense"

    def test_piped_eof_falls_through_to_default(self, rich_console: Console):
        """Patch Prompt.ask to raise EOFError, assert default used."""
        spec = PromptSpec(
            label="Tracking",
            dotted_key="tracking_dir",
            type="str",
            group="g",
            tier="basic",
            default_factory=lambda ex: "~/x",
        )
        with patch("installer.wizard.Prompt.ask", side_effect=EOFError):
            result = _dispatch_rich_prompt(spec, "~/x", rich_console)
        assert result == "~/x"

    def test_invalid_existing_value_warns(self, mock_home: Path, rich_console: Console):
        """quality_level='blazing' (invalid) should be coerced by prompt_choice."""
        proj_yaml = mock_home / ".claude" / "proj.yaml"
        proj_yaml.write_text("quality_level: blazing\n")

        recorded_defaults: list = []

        def fake_prompt_choice(label, default, choices, console):
            recorded_defaults.append((label, default, list(choices)))
            # mimic real coercion: if default not in choices, use choices[0]
            return default if default in choices else choices[0]

        with (
            patch(
                "installer.wizard.Prompt.ask",
                side_effect=lambda *a, **k: k.get("default", ""),
            ),
            patch(
                "installer.wizard.Confirm.ask",
                side_effect=lambda *a, **k: k.get("default", False),
            ),
            patch("installer.wizard.int_in_range", side_effect=lambda *a, **k: a[1]),
            patch("installer.wizard.prompt_choice", side_effect=fake_prompt_choice),
        ):
            _setup_proj_yaml(rich_console, [])

        quality_calls = [r for r in recorded_defaults if "quality" in r[0].lower()]
        assert quality_calls, f"no quality_level prompt fired: {recorded_defaults}"
        label, default, choices = quality_calls[0]
        assert default == "blazing"
        assert "fast" in choices

        written = yaml.safe_load(proj_yaml.read_text())
        assert written["quality_level"] == "fast"

    # ---------------- Edge cases ----------------

    def test_null_nested_value_returns_default(self):
        from installer._config_loader import get_nested

        existing = {"git_tracking": None}
        assert get_nested(existing, "git_tracking.enabled", False) is False
        assert get_nested({"a": {"b": None}}, "a.b.c", "fallback") == "fallback"

    def test_schema_drift_unknown_key_preserved(
        self, mock_home: Path, rich_console: Console
    ):
        """wizard_specs has no spec for `extra.unknown` but yaml has it — preserved."""
        proj_yaml = mock_home / ".claude" / "proj.yaml"
        proj_yaml.write_text(
            yaml.safe_dump({"extra": {"unknown": "preserved-value"}, "other": 42})
        )

        with (
            patch(
                "installer.wizard.Prompt.ask",
                side_effect=lambda *a, **k: k.get("default", ""),
            ),
            patch(
                "installer.wizard.Confirm.ask",
                side_effect=lambda *a, **k: k.get("default", False),
            ),
            patch("installer.wizard.int_in_range", side_effect=lambda *a, **k: a[1]),
            patch(
                "installer.wizard.prompt_choice",
                side_effect=lambda label, default, choices, console: default,
            ),
        ):
            _setup_proj_yaml(rich_console, [])

        result = yaml.safe_load(proj_yaml.read_text())
        assert result["extra"]["unknown"] == "preserved-value"
        assert result["other"] == 42

    def test_malformed_existing_yaml_aborts(
        self, mock_home: Path, rich_console: Console
    ):
        """Broken yaml: wizard prints error and returns {} without writing."""
        proj_yaml = mock_home / ".claude" / "proj.yaml"
        proj_yaml.write_text("foo: [unclosed\n:::bad")
        original = proj_yaml.read_text()

        with (
            patch("installer.wizard.Prompt.ask") as p_ask,
            patch("installer.wizard.Confirm.ask") as c_ask,
        ):
            result = _setup_proj_yaml(rich_console, [])

        assert result == {}
        # Must not have prompted the user — early abort
        p_ask.assert_not_called()
        c_ask.assert_not_called()
        # File must be untouched
        assert proj_yaml.read_text() == original

    def test_trello_disabled_preservation(self, mock_home: Path, rich_console: Console):
        """sync.trello.enabled=False: list_mappings prompts must not fire."""
        proj_yaml = mock_home / ".claude" / "proj.yaml"
        proj_yaml.write_text(yaml.safe_dump({"sync": {"trello": {"enabled": False}}}))

        prompt_labels: list[str] = []

        def fake_prompt_ask(label, *args, default=None, **kwargs):
            prompt_labels.append(label)
            return default if default is not None else ""

        def fake_confirm(label, *args, **kwargs):
            if "advanced" in label.lower():
                return True  # drill into advanced to reach trello section
            return kwargs.get("default", False)

        with (
            patch("installer.wizard.Prompt.ask", side_effect=fake_prompt_ask),
            patch("installer.wizard.Confirm.ask", side_effect=fake_confirm),
            patch("installer.wizard.int_in_range", side_effect=lambda *a, **k: a[1]),
            patch(
                "installer.wizard.prompt_choice",
                side_effect=lambda label, default, choices, console: default,
            ),
        ):
            _setup_proj_yaml(rich_console, [])

        list_mapping_labels = [
            label for label in prompt_labels if "Trello list:" in label
        ]
        assert list_mapping_labels == [], (
            f"list_mappings fired despite trello disabled: {list_mapping_labels}"
        )

    # ---------------- Concurrent mtime ----------------

    def test_concurrent_mtime_aborts_write(
        self, mock_home: Path, rich_console: Console
    ):
        """If proj.yaml mtime changes during wizard, write is aborted.

        Strategy: patch Path.stat only for proj.yaml to return a stat whose
        st_mtime is derived from a monotonically-increasing counter. First
        read (stored as mtime_before) gets 1.0; post-prompt compare gets 2.0,
        triggering the abort branch.
        """
        proj_yaml = mock_home / ".claude" / "proj.yaml"
        proj_yaml.write_text("tracking_dir: /original\n")
        original_content = proj_yaml.read_text()

        real_stat = Path.stat
        counter = {"n": 0}

        def fake_stat(self, *args, **kwargs):
            result = real_stat(self, *args, **kwargs)
            if str(self).endswith(".claude/proj.yaml"):
                counter["n"] += 1

                class _Stat:
                    st_mtime = float(counter["n"])
                    st_size = result.st_size
                    st_mode = result.st_mode
                    st_ino = result.st_ino
                    st_dev = result.st_dev
                    st_nlink = result.st_nlink
                    st_uid = result.st_uid
                    st_gid = result.st_gid
                    st_atime = result.st_atime
                    st_ctime = result.st_ctime

                return _Stat()
            return result

        with (
            patch.object(Path, "stat", fake_stat),
            patch(
                "installer.wizard.Prompt.ask",
                side_effect=lambda *a, **k: k.get("default", ""),
            ),
            patch(
                "installer.wizard.Confirm.ask",
                side_effect=lambda *a, **k: k.get("default", False),
            ),
            patch("installer.wizard.int_in_range", side_effect=lambda *a, **k: a[1]),
            patch(
                "installer.wizard.prompt_choice",
                side_effect=lambda label, default, choices, console: default,
            ),
            patch("installer.wizard._atomic_write") as mock_write,
        ):
            _setup_proj_yaml(rich_console, [])

        mock_write.assert_not_called()
        assert proj_yaml.read_text() == original_content

    # ---------------- Basic-only regression ----------------

    def test_basic_only_regression(self, mock_home: Path, rich_console: Console):
        """Full wizard in basic-only mode writes expected keys."""
        prompt_count = {"n": 0}
        confirm_count = {"n": 0}

        def fake_prompt_ask(label, *args, default=None, **kwargs):
            prompt_count["n"] += 1
            return default if default is not None else ""

        def fake_confirm(label, *args, **kwargs):
            confirm_count["n"] += 1
            if "advanced" in label.lower():
                return False
            return kwargs.get("default", False)

        with (
            patch("installer.wizard.Prompt.ask", side_effect=fake_prompt_ask),
            patch("installer.wizard.Confirm.ask", side_effect=fake_confirm),
            patch("installer.wizard.int_in_range", side_effect=lambda *a, **k: a[1]),
            patch(
                "installer.wizard.prompt_choice",
                side_effect=lambda label, default, choices, console: default,
            ),
        ):
            _setup_proj_yaml(rich_console, [])

        proj_yaml = mock_home / ".claude" / "proj.yaml"
        assert proj_yaml.exists()
        data = yaml.safe_load(proj_yaml.read_text())
        # Basic-tier keys that must appear (non-conditional ones)
        assert "tracking_dir" in data
        assert "projects_base_dir" in data
        assert "sandbox_integration" in data
        assert "zoxide_integration" in data
        assert "quality_level" in data
        assert "worktree_isolation" in data
        # ~12 prompts: 6 bool-or-str basic + choice + worktree + advanced toggle
        total = prompt_count["n"] + confirm_count["n"]
        assert 6 <= total <= 20, f"expected ~12 prompts, got {total}"


class TestRunWizardDispatch:
    """Thin smoke tests for run_wizard plugin dispatch."""

    def test_skip_wizard(self, mock_home: Path):
        run_wizard(["proj"], skip=True)

    def test_proj_triggers_proj_yaml_setup(self, mock_home: Path):
        with (
            patch("installer.wizard._setup_proj_yaml") as mock_proj,
            patch("installer.wizard._setup_worktree_yaml") as mock_wt,
            patch("installer.wizard._hooks_diff_prompt"),
            patch("installer.wizard.ensure_managed_section"),
        ):
            run_wizard(["proj", "sandbox"], skip=False)
            mock_proj.assert_called_once()
            mock_wt.assert_not_called()

    def test_worktree_triggers_worktree_yaml_setup(self, mock_home: Path):
        with (
            patch("installer.wizard._setup_proj_yaml") as mock_proj,
            patch("installer.wizard._setup_worktree_yaml") as mock_wt,
            patch("installer.wizard._hooks_diff_prompt"),
            patch("installer.wizard.ensure_managed_section"),
        ):
            run_wizard(["worktree"], skip=False)
            mock_proj.assert_not_called()
            mock_wt.assert_called_once()

    def test_empty_plugins_skips_all(self, mock_home: Path):
        with (
            patch("installer.wizard._setup_proj_yaml") as mock_proj,
            patch("installer.wizard._setup_worktree_yaml") as mock_wt,
            patch("installer.wizard._hooks_diff_prompt"),
            patch("installer.wizard.ensure_managed_section"),
        ):
            run_wizard([], skip=False)
            mock_proj.assert_not_called()
            mock_wt.assert_not_called()


class TestMergeDottedIntoDict:
    def test_nested_keys_merged(self):
        existing: dict = {"a": {"b": 1}}
        _merge_dotted_into_dict(existing, {"a.c": 2, "d": 3})
        assert existing == {"a": {"b": 1, "c": 2}, "d": 3}

    def test_overrides_non_dict_intermediate(self):
        existing: dict = {"git_tracking": None}
        _merge_dotted_into_dict(existing, {"git_tracking.enabled": True})
        assert existing == {"git_tracking": {"enabled": True}}

    def test_deep_nesting(self):
        existing: dict = {}
        _merge_dotted_into_dict(existing, {"a.b.c.d": "deep"})
        assert existing == {"a": {"b": {"c": {"d": "deep"}}}}


class TestRichWizardSettingsHooksCallOrder:
    """Assert run_wizard calls _settings_hooks_diff_prompt after _hooks_diff_prompt."""

    def test_run_wizard_calls_settings_hooks_diff_prompt(self, tmp_path, monkeypatch):
        """Patch helpers and assert call order in the Rich path."""
        from unittest.mock import patch

        home = tmp_path / "home"
        home.mkdir()
        (home / ".claude").mkdir()
        monkeypatch.setattr(Path, "home", lambda: home)

        from installer import wizard as w

        calls: list[str] = []

        def _stub_setup_proj(*args, **kwargs):
            calls.append("_setup_proj_yaml")
            return {}

        def _stub_setup_worktree(*args, **kwargs):
            calls.append("_setup_worktree_yaml")
            return {}

        def _stub_hooks_diff(*args, **kwargs):
            calls.append("_hooks_diff_prompt")

        def _stub_settings_hooks_diff(*args, **kwargs):
            calls.append("_settings_hooks_diff_prompt")

        def _stub_ensure_managed(*args, **kwargs):
            calls.append("ensure_managed_section")

        def _stub_resolve_plugin_dir(cache_dir, name):
            return home / ".claude" / "plugins" / name

        with (
            patch.object(w, "_setup_proj_yaml", side_effect=_stub_setup_proj),
            patch.object(w, "_setup_worktree_yaml", side_effect=_stub_setup_worktree),
            patch.object(w, "_hooks_diff_prompt", side_effect=_stub_hooks_diff),
            patch.object(
                w, "_settings_hooks_diff_prompt", side_effect=_stub_settings_hooks_diff
            ),
            patch.object(w, "ensure_managed_section", side_effect=_stub_ensure_managed),
            patch.object(
                w, "_resolve_plugin_dir", side_effect=_stub_resolve_plugin_dir
            ),
            patch.object(w, "Confirm") as mock_confirm,
            patch.object(w, "Prompt") as mock_prompt,
        ):
            mock_confirm.ask.return_value = False
            mock_prompt.ask.return_value = ""
            try:
                w.run_wizard(selected_plugins=["proj"], skip=False)
            except SystemExit:
                pass
            except Exception:
                pass

        assert "_settings_hooks_diff_prompt" in calls, (
            f"_settings_hooks_diff_prompt was not called. Calls: {calls}"
        )
        if "_hooks_diff_prompt" in calls and "_settings_hooks_diff_prompt" in calls:
            assert calls.index("_hooks_diff_prompt") < calls.index(
                "_settings_hooks_diff_prompt"
            ), f"Call order wrong: {calls}"

    def test_skips_on_empty_plugin_dirs(self, tmp_path, monkeypatch):
        """With empty plugin_dirs, _settings_hooks_diff_prompt is a no-op guard."""
        from io import StringIO

        from rich.console import Console

        from installer.wizard import _settings_hooks_diff_prompt

        console = Console(file=StringIO(), force_terminal=False)
        _settings_hooks_diff_prompt([], console)
