# installer/tests/flow/test_form.py
from unittest.mock import MagicMock

import pytest
from rich.console import Console

from installer.flow.form import FieldSpec, run_form


class TestFieldSpec:
    def test_dataclass_fields(self) -> None:
        spec = FieldSpec(key="x", label="X", kind="text", default="foo")
        assert spec.key == "x"
        assert spec.label == "X"
        assert spec.kind == "text"
        assert spec.default == "foo"
        assert spec.choices is None
        assert spec.validator is None
        assert spec.help_text is None
        assert spec.group is None


class TestRunForm:
    def test_submit_returns_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fields = [
            FieldSpec(key="name", label="Name", kind="text", default="alice"),
            FieldSpec(key="age", label="Age", kind="int", default=30),
            FieldSpec(key="sub", label="Subscribed", kind="bool", default=True),
        ]
        mock_app = MagicMock()
        mock_app.run.return_value = {"name": "alice", "age": 30, "sub": True}
        monkeypatch.setattr(
            "installer.flow.form._build_application", lambda *a, **k: mock_app
        )

        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = run_form(fields, console, title="Test")
        assert result == {"name": "alice", "age": 30, "sub": True}

    def test_cancel_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fields = [FieldSpec(key="name", label="Name", kind="text", default="alice")]
        mock_app = MagicMock()
        mock_app.run.return_value = None
        monkeypatch.setattr(
            "installer.flow.form._build_application", lambda *a, **k: mock_app
        )

        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = run_form(fields, console, title="Test")
        assert result is None

    def test_empty_fields_returns_empty_dict(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_app = MagicMock()
        mock_app.run.return_value = {}
        monkeypatch.setattr(
            "installer.flow.form._build_application", lambda *a, **k: mock_app
        )

        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = run_form([], console, title="Empty")
        assert result == {}

    def test_validator_blocks_invalid_submit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """FieldSpec.validator returning str should block submit + reshow form w/ error."""
        # First app.run returns {"_form_error": "required", "_values": {"x": ""}}
        # Second returns {"x": "ok"} (validator passes)
        mock_app = MagicMock()
        mock_app.run.side_effect = [
            {"_form_error": "required", "_values": {"x": ""}},
            {"x": "ok"},
        ]
        monkeypatch.setattr(
            "installer.flow.form._build_application", lambda *a, **k: mock_app
        )

        def validator(v: str) -> str | None:
            return "required" if not v else None

        fields = [
            FieldSpec(key="x", label="X", kind="text", default="", validator=validator)
        ]
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = run_form(fields, console, title="Test")
        assert result == {"x": "ok"}
        assert mock_app.run.call_count == 2

    def test_error_message_preserved_on_rerun(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Caller passes error_message='previous attempt failed' → passed to _build_application."""
        captured: dict[str, str | None] = {}

        def fake_build(fields, *, title=None, error_message=None):
            captured["err"] = error_message
            mock_app = MagicMock()
            mock_app.run.return_value = {"x": "ok"}
            return mock_app

        monkeypatch.setattr("installer.flow.form._build_application", fake_build)

        fields = [FieldSpec(key="x", label="X", kind="text", default="old")]
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        run_form(fields, console, title="Test", error_message="auth failed")
        assert captured["err"] == "auth failed"
