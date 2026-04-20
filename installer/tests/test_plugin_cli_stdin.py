"""Regression test: plugin_cli._run must pass stdin=DEVNULL to subprocess.

Prevents child `claude plugin …` process from reading/mangling the
parent's TTY (e.g. Ink setting raw mode and not restoring it).
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

from installer import plugin_cli


def test_run_passes_stdin_devnull() -> None:
    captured: dict[str, object] = {}

    def fake_run(cmd, **kwargs):  # noqa: ANN001, ANN003
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        res = MagicMock()
        res.returncode = 0
        res.stdout = ""
        res.stderr = ""
        return res

    with patch("installer.plugin_cli.subprocess.run", side_effect=fake_run):
        plugin_cli._run(["claude", "plugin", "list", "--json"])

    assert captured["kwargs"].get("stdin") is subprocess.DEVNULL
    assert captured["kwargs"].get("capture_output") is True
