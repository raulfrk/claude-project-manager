# installer/tests/flow/test_install_plan.py
from rich.console import Console

from installer.flow.install_plan import InstallAction, InstallPlan, execute_install_plan


def test_execute_calls_hooks_in_order(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake_install(pid: str) -> None:
        calls.append(("install", pid))

    def fake_uninstall(pid: str) -> None:
        calls.append(("uninstall", pid))

    monkeypatch.setattr("installer.flow.install_plan.install_plugin", fake_install)
    monkeypatch.setattr("installer.flow.install_plan.uninstall_plugin", fake_uninstall)

    plan = InstallPlan(
        description="Test plan",
        actions=[
            InstallAction(plugin_id="a@m", action="install"),
            InstallAction(plugin_id="b@m", action="uninstall"),
        ],
    )
    console = Console(record=True, width=80, force_terminal=False, no_color=True)
    result = execute_install_plan(plan, console)

    assert calls == [("install", "a@m"), ("uninstall", "b@m")]
    assert result.success_count == 2
    assert result.failure_count == 0


def test_execute_reports_failure(monkeypatch) -> None:
    from installer.errors import InstallerError

    def fake_install(pid: str) -> None:
        raise InstallerError(f"boom {pid}")

    monkeypatch.setattr("installer.flow.install_plan.install_plugin", fake_install)

    plan = InstallPlan(
        description="Test plan",
        actions=[InstallAction(plugin_id="a@m", action="install")],
    )
    console = Console(record=True, width=80, force_terminal=False, no_color=True)
    result = execute_install_plan(plan, console)

    assert result.success_count == 0
    assert result.failure_count == 1
    assert result.failures[0].plugin_id == "a@m"
    assert "boom" in result.failures[0].error


def test_execute_reinstall_runs_uninstall_then_install(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake_install(pid: str) -> None:
        calls.append(("install", pid))

    def fake_uninstall(pid: str) -> None:
        calls.append(("uninstall", pid))

    monkeypatch.setattr("installer.flow.install_plan.install_plugin", fake_install)
    monkeypatch.setattr("installer.flow.install_plan.uninstall_plugin", fake_uninstall)

    plan = InstallPlan(
        description="Test plan",
        actions=[InstallAction(plugin_id="a@m", action="reinstall")],
    )
    console = Console(record=True, width=80, force_terminal=False, no_color=True)
    result = execute_install_plan(plan, console)

    assert calls == [("uninstall", "a@m"), ("install", "a@m")]
    assert result.success_count == 1
    assert result.failure_count == 0


def test_execute_continues_after_failure(monkeypatch) -> None:
    from installer.errors import InstallerError

    calls: list[str] = []

    def fake_install(pid: str) -> None:
        calls.append(pid)
        if pid == "b@m":
            raise InstallerError(f"boom {pid}")

    monkeypatch.setattr("installer.flow.install_plan.install_plugin", fake_install)

    plan = InstallPlan(
        description="Test plan",
        actions=[
            InstallAction(plugin_id="a@m", action="install"),
            InstallAction(plugin_id="b@m", action="install"),
            InstallAction(plugin_id="c@m", action="install"),
        ],
    )
    console = Console(record=True, width=80, force_terminal=False, no_color=True)
    result = execute_install_plan(plan, console)

    assert calls == ["a@m", "b@m", "c@m"]
    assert result.success_count == 2
    assert result.failure_count == 1
    assert result.failures[0].plugin_id == "b@m"


def test_execute_empty_plan(monkeypatch) -> None:
    # No-op — empty plan should not raise.
    plan = InstallPlan(description="Empty", actions=[])
    console = Console(record=True, width=80, force_terminal=False, no_color=True)
    result = execute_install_plan(plan, console)

    assert result.success_count == 0
    assert result.failure_count == 0
    assert result.failures == []
