"""Board-local computation and remote-only ground-station ownership tests."""

from copy import deepcopy
import json
import math
from pathlib import Path
import sys
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]/'gs_bridge'))
from gs_bridge.depth_control import BoardDepthControl
from controllers.parallel_depth import DEFAULTS
from controllers.remote_depth import RemoteDepthController, RemoteParallelDepthController
from communication.base import ControlCommand, FishState
from communication.socket_client import SocketCommunication
from test_control_axes import Clock, window
from test_ui_state_machine import ensure_app


@pytest.fixture
def engine():
    """Use the production pure-Python Pico engine with a deterministic local sensor clock."""
    clock = Clock()
    controller = BoardDepthControl(clock)
    params = deepcopy(DEFAULTS)
    params['depth'].update(target=20, kp=10)
    params['pitch'].update(kp=2)
    params['zero_offset'] = 2
    controller.configure('parallel', params)
    return controller, clock


def feed(controller, sample=1):
    """Supply Pico-local sensor callbacks: raw depth 12cm minus zero 2cm, pitch 5 degrees."""
    controller.update('depth', 12., 'd'+str(sample))
    controller.update('pitch', 5., 'p'+str(sample))
    return controller.tick()


def test_pico_parallel_math_and_calibration_are_local(engine):
    """Both independent outputs and zero calibration combine only on the Pico engine."""
    controller, clock = engine
    controller.start()
    assert feed(controller) == 1410
    report = controller.snapshot()
    assert report['execution'] == 'pico'
    assert report['loops']['depth']['value'] == 10
    assert report['loops']['depth']['output'] == -100
    assert report['loops']['pitch']['output'] == 10


def test_pico_single_does_not_need_an_imu(engine):
    """The retained single-loop mode runs with depth alone, not a fabricated zero pitch."""
    controller, clock = engine
    controller.configure('single', controller.params)
    controller.start()
    controller.update('depth', 12, 'd1')
    assert controller.tick() == 1400


@pytest.mark.parametrize('period', [50, 100, 250, 1000])
def test_period_is_validated_configurable_and_used_in_first_integral_dt(engine, period):
    """The UI-configured period sets the board schedule and first-sample integration dt."""
    controller, clock = engine
    params = deepcopy(controller.params)
    params['period_ms'] = period
    params['depth'].update(kp=0, ki=1)
    params['pitch']['kp'] = 0
    controller.configure('parallel', params)
    controller.start()
    feed(controller)
    assert controller.history['depth']['integral'] == pytest.approx(10*period/1000)


@pytest.mark.parametrize('value', [0, 49, 1001, float('nan'), float('inf')])
def test_invalid_period_rejected_without_replacing_running_configuration(engine, value):
    """Bad parameter packets cannot disable limits or partially replace the active controller."""
    controller, clock = engine
    before = deepcopy(controller.params)
    changed = deepcopy(before)
    changed['period_ms'] = value
    with pytest.raises(ValueError):
        controller.configure('parallel', changed)
    assert controller.params == before


def test_sensor_stale_centers_clears_and_requires_both_new_samples(engine):
    """Local monotonic sensor timeout is independent of any network/display update rate."""
    controller, clock = engine
    controller.start()
    feed(controller)
    clock.now += .6
    controller.update('depth', 12, 'd2')
    assert controller.tick() == 1500
    controller.update('pitch', 5, 'p2')
    assert controller.tick() == 1500
    assert feed(controller, 3) == 1410


def test_repeated_samples_do_not_integrate_and_saturation_is_after_sum(engine):
    """The board holds each contribution until its own new sample, and clips the final sum."""
    controller, clock = engine
    controller.params['depth']['ki'] = 1.
    controller.start()
    feed(controller)
    integral = controller.history['depth']['integral']
    clock.now += .1
    assert not controller.update('depth', 12, 'd1')
    controller.update('pitch', 6., 'p2')
    controller.tick()
    assert controller.history['depth']['integral'] == integral
    controller.update('depth', 200., 'd3')
    assert controller.tick() == 1700


@pytest.mark.parametrize('kind', ['single', 'parallel'])
def test_desktop_proxy_never_runs_pid_or_emits_local_actuator_frames(tmp_path, kind):
    """Desktop timers only watch acknowledgements; all PID.update calls are forbidden."""
    ensure_app()
    cls = RemoteDepthController if kind == 'single' else RemoteParallelDepthController
    controller = cls(params_path=tmp_path/'params.json')
    controller.get_control_widget()
    requests, frames = [], []
    controller.remote_sender = lambda data: requests.append(data) or True
    controller.control_command_generated.connect(frames.append)
    with patch('controllers.depth.PID.update', side_effect=AssertionError('desktop PID ran')):
        assert controller.activate()
        controller._update_control()
        state = dict(execution='pico', enabled=True, session_id=controller.remote_session,
                     pwm=1420, status='running', loops={}, period_ms=100)
        controller.receive_remote_state(state)
        assert controller._pec_angle == 1420
        controller.deactivate()
    assert [r['action'] for r in requests] == ['start', 'stop']
    assert not frames


def test_remote_sessions_reject_late_board_status_and_fault_when_board_stops(tmp_path):
    """A late old session cannot arm or override the new UI or manual handover state."""
    ensure_app()
    controller = RemoteParallelDepthController(params_path=tmp_path/'parallel.json')
    controller.remote_sender = lambda data: True
    faults = []
    controller.remote_fault.connect(faults.append)
    controller.activate()
    controller.receive_remote_state(dict(execution='pico', enabled=False, session_id='old'))
    assert not faults
    controller.receive_remote_state(dict(execution='pico', enabled=False, session_id=controller.remote_session))
    assert faults
    controller.deactivate()


def test_desktop_heading_frame_omits_pectoral_when_board_depth_owns_it():
    """A heading packet sends tail fields only while Pico controls pectoral PWM."""
    client = SocketCommunication()
    client._connected = True
    client.socket = Mock()
    command = ControlCommand()
    command.pec_angle = 600
    command.pectoral_owner = 'pico_depth'
    assert client.send_control_command(command)
    message = json.loads(client.socket.sendall.call_args.args[0])
    assert 'pec_angle' not in message
    assert message['pectoral_owner'] == 'pico_depth'


def test_running_board_depth_greys_and_blocks_manual_pectoral_controls(window):
    """UI ownership and final-frame routing are unchanged by moving the math to Pico."""
    window.depth_enable_checkbox.setChecked(True)
    window.heading_enable_checkbox.setChecked(True)
    keyboard = window.controllers['keyboard']
    assert not keyboard._pec_pulse_input.isEnabled()
    assert not keyboard._set_pec_button.isEnabled()
    assert not keyboard.set_pec_pulse(500)
    keyboard.handle_key_press('Q')
    keyboard._update_control()
    assert window.communication.commands[-1].pectoral_owner == 'pico_depth'
    request = window.communication.depth_requests[0]
    assert request['params']['zero_offset'] == window.depth_panel.zero_offset
    assert request['mode'] == 'single'


def test_stop_holds_actual_board_pwm_until_ack_and_full_stop_can_force_neutral(window):
    """Delayed desktop PWM feedback cannot undo a board-side stop/manual handover."""
    window.depth_enable_checkbox.setChecked(True)
    controller = window.axis_coordinator.depth
    session = controller.remote_session
    window.depth_enable_checkbox.setChecked(False)
    assert window._depth_handover_session == session
    assert window.communication.commands[-1].pectoral_owner == 'pico_hold'
    state = FishState()
    state.depth_control = dict(execution='pico', mode='single', session_id=session, enabled=False, pwm=1437)
    window.communication.get_fish_state = lambda: state
    window._update_data()
    assert window.axis_coordinator.last_pwm == 1437
    assert window.controllers['keyboard']._pec_angle == 1437
    assert window._depth_handover_session is None
    window.depth_enable_checkbox.setChecked(True)
    window.all_stop_button.click()
    assert window.communication.commands[-1].pec_angle == 1500
    assert not hasattr(window.communication.commands[-1], 'pectoral_owner')
