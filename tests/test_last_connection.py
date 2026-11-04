"""Offline persistence tests for the last successful endpoint, isolated from user data."""

from unittest.mock import Mock, patch
import json
import subprocess
import sys
from pathlib import Path

import pytest
import PyQt5
from PyQt5.QtCore import QSettings

from test_ui_state_machine import ensure_app
from ui.connection_store import ConnectionStore
from ui.main_window import MainWindow


@pytest.fixture
def windows(tmp_path):
    """Create windows using only temporary settings and connection archives."""
    ensure_app()
    settings_path = str(tmp_path/'settings.ini')
    settings = QSettings(settings_path, QSettings.IniFormat)
    profiles = ConnectionStore(tmp_path/'profiles.json')
    profiles.add('archive-first', '10.0.0.1', 9999)
    created = []

    def make(variant='dual'):
        """Construct a fresh window without accessing the real registry or profiles."""
        isolated = QSettings(settings_path, QSettings.IniFormat)
        with patch('ui.main_window.QSettings', return_value=isolated), \
                patch('ui.main_window.ConnectionStore', return_value=profiles), \
                patch('ui.video_display.VideoDisplayWidget._detect_cameras'):
            window = MainWindow(variant)
        if variant == 'dual':
            window.video_widget.connect_stream = Mock(return_value=False)
            window.depth_panel.set_parent_connection_available = Mock()
        created.append(window)
        return window

    yield make, settings, profiles
    for window in created:
        window._fish_connection_state = 'disconnected'
        window.communication = None
        window.data_timer.stop()
        window.connection_timer.stop()
        window.telemetry_timer.stop()
        window.close()


def test_last_success_overrides_first_profile_after_restart(windows, tmp_path):
    """A successful manual endpoint takes precedence over the first archived profile."""
    make, settings, profiles = windows
    first = make()
    first._finish_fish_connection('192.168.137.2', 10001)
    second = make()
    assert second.ip_input.text() == '192.168.137.2'
    assert second.port_input.text() == '10001'
    assert second.saved_combo.currentIndex() == 0
    assert profiles.entries[0]['ip'] == '10.0.0.1'
    assert second._fish_connection_state == 'disconnected'
    second.show()
    ensure_app().processEvents()
    assert second.ip_input.parentWidget().grab().save(str(tmp_path/'connection.png'))


def test_last_success_is_separate_for_fish_variants(windows):
    """Pico and OrangePi endpoints must not overwrite one another."""
    make, _, _ = windows
    make('dual')._finish_fish_connection('192.168.137.2', 9999)
    make('single')._finish_fish_connection('10.0.0.7', 8888)
    dual, single = make('dual'), make('single')
    assert (dual.ip_input.text(), dual.port_input.text()) == ('192.168.137.2', '9999')
    assert (single.ip_input.text(), single.port_input.text()) == ('10.0.0.7', '8888')


def test_failed_attempt_and_editing_do_not_overwrite_success(windows):
    """Only a real successful transition may persist a new endpoint."""
    make, _, _ = windows
    make()._finish_fish_connection('192.168.137.2', 9999)
    failed = make()
    failed.ip_input.setText('192.0.2.99')
    failed.port_input.setText('12345')
    communication = Mock()
    communication.connect.return_value = False
    with patch('ui.main_window.SocketCommunication', return_value=communication):
        failed._connect_to_fish()
    failed.close()
    restored = make()
    assert (restored.ip_input.text(), restored.port_input.text()) == ('192.168.137.2', '9999')


@pytest.mark.parametrize('value', [None, 'broken', {}, {'ip': '', 'port': 9999},
                                  {'ip': 'x', 'port': -1}, {'ip': 'x', 'port': 65536},
                                  {'ip': 'x', 'port': 'bad'}])
def test_invalid_history_falls_back_to_existing_profile(windows, value):
    """Corrupt history must not prevent launching the UI."""
    make, settings, _ = windows
    settings.setValue('connection/last_successful/dual', value)
    settings.sync()
    window = make()
    assert (window.ip_input.text(), window.port_input.text()) == ('10.0.0.1', '9999')


def test_matching_profile_selection_is_restored(windows):
    """The archive selection must agree with the endpoint shown after startup."""
    make, _, profiles = windows
    profiles.add('last', '192.168.137.2', 9999)
    profiles.add('newer-but-not-connected', '10.0.0.1', 9999)
    make()._finish_fish_connection('192.168.137.2', 9999)
    window = make()
    assert window.saved_combo.currentData()['ip'] == window.ip_input.text() == '192.168.137.2'


def test_success_is_synced_for_another_process(windows):
    """A separate Python process sees the saved endpoint immediately after connection."""
    make, settings, _ = windows
    make()._finish_fish_connection('192.168.137.2', 12345)
    code = ('import sys,json; sys.path.insert(0,sys.argv[2]); '
            'from PyQt5.QtCore import QSettings; '
            's=QSettings(sys.argv[1],QSettings.IniFormat); '
            'print(json.dumps(s.value("connection/last_successful/dual")))')
    output = subprocess.check_output([sys.executable, '-c', code, settings.fileName(),
                                      str(Path(PyQt5.__file__).parent.parent)], text=True)
    assert json.loads(output) == dict(ip='192.168.137.2', port=12345)
