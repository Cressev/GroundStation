"""Keep stereo NPZ preferences isolated from the user's real registry in every test."""

import pytest
from PyQt5.QtCore import QSettings


@pytest.fixture(autouse=True)
def isolated_stereo_settings(monkeypatch, tmp_path):
    """Use one temporary INI per test, shared only by that test's widget instances."""
    path = str(tmp_path/'stereo-settings.ini')

    class IsolatedSettings(QSettings):
        """Retain Qt enum values while redirecting only the settings constructor."""

        def __init__(self, *args):
            """Always read/write this test's disposable INI instead of the registry."""
            super().__init__(path, QSettings.IniFormat)

    monkeypatch.setattr('ui.stereo_camera_widget.QSettings', IsolatedSettings)
    return path
