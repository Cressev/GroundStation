"""Xbox output throttling tests with a fake controller and no socket or device."""

from dataclasses import replace
import os
import json
import threading
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PyQt5.QtWidgets import QApplication

from config import XBOX_CONTROL_DEFAULTS
from controllers.xbox import XboxController, XboxInputState
from communication.socket_client import SocketCommunication
from ui.main_window import MainWindow


class FakeBackend:
    """Provide a stationary connected input without loading Windows XInput."""

    available = True

    def poll(self):
        """Return a connected synthetic gamepad."""
        return XboxInputState(connected=True, controller_index=0)

    def set_vibration(self, index, left, right):
        """Do not access any device, including the physical vibration motors."""
        return True


@pytest.fixture
def controller(monkeypatch):
    """Construct only the fake backend and prevent reading user parameter files."""
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(XboxController, '_load_saved_parameters', lambda self: dict(XBOX_CONTROL_DEFAULTS))
    ctrl = XboxController(backend=FakeBackend(), time_source=lambda: 0.0)
    ctrl._poll_timer.stop()
    ctrl._app_for_test = app
    yield ctrl
    ctrl._poll_timer.stop()
    ctrl._vibration_timer.stop()


def test_latest_changes_are_sent_no_faster_than_ten_hertz(controller):
    """Repeated updates send at most 10 Hz and deliver the latest value, not old values."""
    sent = []
    controller.control_command_generated.connect(lambda command: sent.append((controller._last_poll_time, command)))
    base = controller._model._last_output
    for step in range(51):
        controller._last_poll_time = step * .02
        controller._emit_output(replace(base, tail_amplitude=step / 1000))
    assert len(sent) == 11
    assert all(b[0] - a[0] >= .1 - 1e-9 for a, b in zip(sent, sent[1:]))
    assert sent[-1][1].tail_amplitude == pytest.approx(.05)


def test_last_unsent_change_is_delivered_even_if_input_stabilizes(controller):
    """Repeated steady polls deliver the final change after the interval elapses."""
    sent = []
    controller.control_command_generated.connect(sent.append)
    base = controller._model._last_output
    controller._last_poll_time = 0.0
    controller._emit_output(base)
    controller._last_poll_time = .02
    final = replace(base, tail_amplitude=.2)
    controller._emit_output(final)
    assert len(sent) == 1
    controller._last_poll_time = .12
    controller._emit_output(final)
    assert len(sent) == 2
    assert sent[-1].tail_amplitude == pytest.approx(.2)


def test_forced_stop_bypasses_ordinary_rate_limit(controller):
    """A forced emergency zero is emitted immediately inside the normal interval."""
    sent = []
    controller.control_command_generated.connect(sent.append)
    base = controller._model._last_output
    controller._last_poll_time = 0.0
    controller._emit_output(replace(base, tail_amplitude=.2))
    controller._last_poll_time = .02
    controller._emit_output(base, force=True)
    assert len(sent) == 2
    assert sent[-1].tail_amplitude == 0


def test_socket_lifecycle_events_use_same_serialized_stream():
    """Both lifecycle markers are complete JSON lines without a real TCP connection."""
    writes = []
    client = SocketCommunication.__new__(SocketCommunication)
    client._connected = True
    client._send_lock = threading.Lock()
    client.socket = SimpleNamespace(sendall=writes.append)
    assert client.send_emergency_stop()
    assert client.send_control_arm()
    assert [json.loads(line) for line in writes] == [
        {'type': 'emergency_stop'}, {'type': 'control_arm'}]
    assert all(line.endswith(b'\n') for line in writes)


def test_ui_sends_emergency_before_revoking_the_axes():
    """The explicit priority marker precedes ordinary coordinator cleanup."""
    order = []
    coord = SimpleNamespace(heading_enabled=True, depth_enabled=False,
                            emergency_stop=lambda: order.append('coordinator'))
    transport = SimpleNamespace(send_emergency_stop=lambda: order.append('network') or True)
    window = SimpleNamespace(_current_controller_name='xbox', axis_coordinator=coord,
                             communication=transport, _log_message=lambda message: None,
                             status_bar=SimpleNamespace(showMessage=lambda message: None))
    MainWindow._on_xbox_emergency_stop(window, 'test')
    assert order == ['network', 'coordinator']


def test_ui_heading_rearm_precedes_latest_snapshot_replay():
    """After explicit heading activation the arm marker precedes the replay."""
    order = []
    coord = SimpleNamespace(heading_enabled=False)
    coord.set_connected = lambda connected: order.append('connected')
    coord.set_heading_enabled = lambda armed, send=True: order.append('activate') or True
    coord._publish = lambda force=False: order.append('replay')
    transport = SimpleNamespace(connected=True, send_control_arm=lambda: order.append('arm') or True)
    window = SimpleNamespace(axis_coordinator=coord, _fish_connection_state='connected',
                             communication=transport, _apply_main_ui_state=lambda: None,
                             _log_message=lambda message: None)
    assert MainWindow._set_control_armed(window, True)
    assert order == ['connected', 'activate', 'arm', 'replay']
