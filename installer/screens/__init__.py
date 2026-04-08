"""Installer TUI screens."""

from installer.screens.confirm import ConfirmOption, ConfirmResult, ConfirmScreen
from installer.screens.detection import DetectionScreen, PluginDetectionRow
from installer.screens.plugin_select import PluginSelectScreen
from installer.screens.progress import ProgressScreen
from installer.screens.update import UpdateScreen

__all__ = [
    "ConfirmOption",
    "ConfirmResult",
    "ConfirmScreen",
    "DetectionScreen",
    "PluginDetectionRow",
    "PluginSelectScreen",
    "ProgressScreen",
    "UpdateScreen",
]
