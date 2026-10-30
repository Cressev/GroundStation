"""Verify duration fraction persistence and transmission without real hardware."""
import json
from pathlib import Path
import sys
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from PyQt5.QtWidgets import QApplication

from communication.base import ControlCommand, FishState
from communication.socket_client import SocketCommunication
from controllers.base import KeyboardController
from controllers.xbox import XboxController
from data.recorder import RecordEntry
from test_control_axes import axes

APP = None


def app():
    """Keep a QApplication alive for controller labels and signals."""
    global APP
    APP = QApplication.instance() or QApplication([])
    return APP


def test_missing_saved_kappa_defaults_to_symmetric_without_changing_other_values(monkeypatch, tmp_path):
    """Old saved parameters retain their original values and gain a 0.5 fraction."""
    app()
    path = tmp_path / 'keyboard.json'
    path.write_text(json.dumps({'slow_frequency': 1.23, 'tail_phase_diff': 0.785}), encoding='utf-8')
    monkeypatch.setattr('controllers.base.PARAMS_FILE', str(path))
    controller = KeyboardController()
    assert controller._keyboard_params['tail_kappa'] == 0.5
    assert controller._keyboard_params['slow_frequency'] == 1.23
    assert controller._keyboard_params['tail_phase_diff'] == 0.785


def test_kappa_only_change_is_saved_emitted_and_visible(monkeypatch, tmp_path):
    """Changing only kappa survives deduplication, persistence and the timing display."""
    app()
    path = tmp_path / 'keyboard.json'
    monkeypatch.setattr('controllers.base.PARAMS_FILE', str(path))
    controller = KeyboardController()
    widget = controller.get_control_widget()
    controller.activate()
    controller.set_keyboard_parameters(0, 1, .17, .1, 2, .3, .2, .785, .5)
    controller.handle_key_press('w')
    controller._update_control()
    sent = []
    controller.control_command_generated.connect(sent.append)
    controller.set_keyboard_parameters(0, 1, .17, .1, 2, .3, .2, .785, .3)
    controller._update_control()
    assert sent[-1].tail_kappa == .3
    assert '0.300 s' in controller._kappa_label.text()
    assert '0.700 s' in controller._kappa_label.text()
    controller._save_parameters()
    assert json.loads(path.read_text(encoding='utf-8'))['tail_kappa'] == .3
    controller.deactivate()
    widget.close()


@pytest.mark.parametrize('value, expected', [(0, .1), (1, .9), (float('nan'), .5), (float('inf'), .5)])
def test_keyboard_rejects_nonfinite_and_limits_fraction(value, expected):
    """Unsafe saved fractions cannot enter a generated command."""
    app()
    controller = KeyboardController()
    controller.set_keyboard_parameters(0, 1, .1, .1, 2, .2, .2, tail_kappa=value)
    assert controller._keyboard_params['tail_kappa'] == expected


def test_json_and_recording_preserve_fraction():
    """The TCP payload and exported record carry the experiment's selected fraction."""
    app()
    transport = SocketCommunication()
    transport._connected = True
    transport.socket = Mock()
    command = ControlCommand(freq=1, amp=.17)
    command.tail_kappa = .3
    assert transport.send_control_command(command)
    payload = json.loads(transport.socket.sendall.call_args.args[0])
    assert payload['tail_kappa'] == .3
    assert RecordEntry.from_fish_state_and_command(FishState(), command).to_dict()['control_kappa'] == .3


def test_xbox_sends_fraction_and_deduplicates_it(monkeypatch, tmp_path):
    """Both heading sources carry the same parameter even without a connected gamepad."""
    app()
    monkeypatch.setattr('controllers.xbox.PARAMS_FILE', str(tmp_path / 'xbox.json'))
    controller = XboxController(backend=Mock(available=True))
    controller._poll_timer.stop()
    sent = []
    controller.control_command_generated.connect(sent.append)
    output = controller._model._last_output
    controller._emit_output(output)
    controller._parameters['tail_kappa'] = .7
    controller._emit_output(output)
    assert len(sent) == 2 and sent[-1].tail_kappa == .7
    controller._vibration_timer.stop()


def test_depth_publication_cannot_replace_heading_kappa(axes):
    """Independent pectoral PID updates and heading stops retain the selected tail fraction."""
    hub, keyboard, _, depth, _, _, outputs = axes
    hub.set_connected(True)
    hub.set_heading_enabled(True)
    keyboard.set_keyboard_parameters(0, 1, .17, .1, 2, .3, .2, tail_kappa=.3)
    keyboard.handle_key_press('w')
    keyboard._update_control()
    assert outputs[-1].tail_kappa == .3
    hub.set_depth_enabled(True)
    depth.update_depth(10., 1)
    depth._update_control()
    assert outputs[-1].tail_kappa == .3
    hub.set_heading_enabled(False)
    assert outputs[-1].tail_kappa == .3 and outputs[-1].tail_amplitude == 0


def test_single_tail_panel_does_not_offer_unsupported_fraction():
    """The existing single-tail platform keeps its original control surface."""
    app()
    controller = KeyboardController(enable_kappa=False)
    widget = controller.get_control_widget()
    assert 'tail_kappa' not in controller._param_inputs
    assert 'κ' not in controller._format_parameter_summary()
    widget.close()
