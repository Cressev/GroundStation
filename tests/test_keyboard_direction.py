"""Verify the dual-fish keyboard correction without any network or servo action."""

from copy import deepcopy
import json
import time
from unittest.mock import Mock

import pytest
from PyQt5.QtCore import QSettings
from controllers.base import KeyboardController
from communication.socket_client import SocketCommunication
from test_ui_state_machine import ensure_app, make_connected_window


@pytest.fixture(autouse=True)
def isolate_user_preferences(monkeypatch, tmp_path):
    """Keep new window checks and saved keyboard defaults away from user preferences."""
    settings_path = str(tmp_path / 'window.ini')
    monkeypatch.setattr('ui.main_window.QSettings',
                        lambda *args: QSettings(settings_path, QSettings.IniFormat))
    monkeypatch.setattr('controllers.base.PARAMS_FILE', str(tmp_path / 'keyboard.json'))


@pytest.mark.parametrize('mode', ['bias', 'kappa', 'combined'])
def test_reversed_keyboard_all_keys_modes_and_json(mode):
    """Reverse only turn deltas and kappa sides; keep speed, trim and chest PWM."""
    ensure_app()
    controller = KeyboardController(turn_direction=-1)
    controller.set_keyboard_parameters(.1, 1., .2, .25, 2., .3, .4,
                                       tail_kappa=.7, turn_mode=mode)
    controller.set_pec_pulse(1620)
    sent = []
    controller.control_command_generated.connect(lambda command: sent.append(deepcopy(command)))
    transport = SocketCommunication()
    transport._connected = True
    transport.socket = Mock()
    controller.activate()
    try:
        for key, left, fast in [('a', True, False), ('d', False, False),
                ('A', True, True), ('D', False, True),
                ('Shift+A', True, True), ('Shift+D', False, True)]:
            controller.handle_key_press(key)
            controller._update_control()
            command = sent[-1]
            delta = (.4 if fast else .25) * (1 if left else -1) if mode != 'kappa' else 0.
            expected_kappa = (.3 if left else .7) if mode != 'bias' else .5
            assert command.tail_offset == pytest.approx(.1 + delta)
            assert command.tail_kappa == pytest.approx(expected_kappa)
            assert command.tail_frequency == (2. if fast else 1.)
            assert command.tail_amplitude == (.3 if fast else .2)
            assert command.pec_angle == 1620
            assert command.tail_phase_diff == 1.57
            assert controller._motion_state.endswith('left' if left else 'right')
            assert transport.send_control_command(command)
            payload = json.loads(transport.socket.sendall.call_args.args[0])
            assert payload['tail_offset'] == pytest.approx(.1 + delta)
            assert payload['tail_kappa'] == pytest.approx(expected_kappa)
        for key in ('w', 'W', 'Shift+W', 's', 'Space'):
            controller.handle_key_press(key)
            controller._update_control()
            assert controller.get_current_command().tail_offset == .1
            assert controller.get_current_command().tail_kappa == .5
            assert controller.get_current_command().pec_angle == 1620
        assert controller.get_current_command().tail_amplitude == 0.
    finally:
        controller.deactivate()


@pytest.mark.parametrize('kind', ['bias', 'kappa'])
@pytest.mark.parametrize('sign', [-1, 1])
def test_explicit_experiment_keeps_signed_values(kind, sign):
    """Raw negative/positive bias experiments must not inherit keyboard orientation."""
    ensure_app()
    controller = KeyboardController(turn_direction=-1)
    controller.set_keyboard_parameters(.1, 1., .2, .25, 2., .3, .4, tail_kappa=.7)
    controller.activate()
    try:
        controller._experiment = dict(params=dict(controller._keyboard_params), speed='slow',
            kind=kind, direction=sign, straight=0., turn=60.,
            started=time.monotonic(), stage='straight')
        controller._update_control()
        command = controller.get_current_command()
        assert command.tail_offset == pytest.approx(.1 + sign * .25 if kind == 'bias' else .1)
        assert command.tail_kappa == (.5 if kind == 'bias' else .7)
    finally:
        controller.deactivate()


def test_actual_dual_main_window_uses_correction_and_preserves_labels():
    """The real window must opt in; a standalone old-platform controller stays unchanged."""
    window, communication = make_connected_window()
    try:
        keyboard = window.controllers['keyboard']
        keyboard.set_keyboard_parameters(.1, 1., .2, .25, 2., .3, .4, tail_kappa=.7)
        assert window._set_control_armed(True)
        for key, expected in [('a', .35), ('d', -.15)]:
            keyboard.handle_key_press(key)
            keyboard._update_control()
            assert communication.commands[-1].tail_offset == pytest.approx(expected)
            assert ('左转' if key == 'a' else '右转') in keyboard._motion_label.text()
        assert '左转使用 1−κ' in keyboard._turn_mode_input.toolTip()
    finally:
        window._stop_all_controls(send_stop=False)
        window.communication = None
        window._fish_connection_state = 'disconnected'
        window.close()


def test_single_window_keeps_original_polarity():
    """Only the dual-fish main window opts in; single-tail mapping remains negative left."""
    from ui.main_window import MainWindow
    ensure_app()
    window = MainWindow('single')
    keyboard = window.controllers['keyboard']
    try:
        keyboard.set_keyboard_parameters(.1, 1., .2, .25, 2., .3, .4)
        keyboard.activate()
        keyboard.handle_key_press('a')
        keyboard._update_control()
        assert keyboard.get_current_command().tail_offset == pytest.approx(-.15)
    finally:
        keyboard.deactivate()
        window.close()
