"""Installer TUI screens."""

from installer.screens.confirm import ConfirmOption, ConfirmResult, ConfirmScreen
from installer.screens.detection import DetectionScreen, PluginDetectionRow
from installer.screens.hooks_diff import HooksDiffScreen
from installer.screens.integration_config import (
    BaseIntegrationScreen,
    TodoistConfigScreen,
)
from installer.screens.plugin_select import PluginSelectScreen
from installer.screens.progress import ProgressScreen
from installer.screens.update import UpdateScreen

__all__ = [
    "BaseIntegrationScreen",
    "TodoistConfigScreen",
    "ConfirmOption",
    "ConfirmResult",
    "ConfirmScreen",
    "DetectionScreen",
    "HooksDiffScreen",
    "PluginDetectionRow",
    "PluginSelectScreen",
    "ProgressScreen",
    "UpdateScreen",
]
