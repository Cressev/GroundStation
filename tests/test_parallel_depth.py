"""Parallel PID, identified telemetry, safe source switching and side-by-side UI regression."""

import ast
from copy import deepcopy
import json
import math
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, Mock
import threading
import time
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3]/'gs_bridge'))
from gs_bridge.depth_control import BoardDepthControl

import pytest
from PyQt5.QtCore import QSettings

from controllers.parallel_depth import ParallelDepthController
from communication.socket_client import SocketCommunication
from test_control_axes import Clock, window
from test_ui_state_machine import ensure_app


@pytest.fixture
def parallel(tmp_path):
    """Create a real controller with deterministic time and a disposable parameter file."""
    ensure_app()
    clock = Clock()
    controller = ParallelDepthController(time_source=clock, params_path=tmp_path/'parallel.json')
    controller._parallel_params['depth'].update(target=20., kp=10., direction=-1)
    controller._parallel_params['pitch'].update(target=0., kp=2., direction=-1)
    controller._configure_loops()
    controller.get_control_widget()
    frames = []
    controller.control_command_generated.connect(frames.append)
    yield controller, clock, frames
    controller.deactivate()
    controller.get_control_widget().close()


def feed(controller, depth=10., pitch=5., identity=1):
    """Deliver independently identified depth in cm and IMU pitch in radians."""
    controller.update_depth(depth, 'd'+str(identity))
    controller.update_pitch(math.radians(pitch), 'p'+str(identity))
    controller._update_control()


def test_parallel_sum_is_not_a_cascade(parallel):
    """Depth contributes -100us and fixed-zero-target pitch contributes +10us."""
    controller, clock, frames = parallel
    controller.activate()
    feed(controller)
    assert controller._outputs == dict(depth=-100., pitch=10.)
    assert frames[-1].pec_angle == 1410
    assert controller._parallel_params['pitch']['target'] == 0.
    assert frames[-1].tail_amplitude == 0.


def test_independent_unique_samples_do_not_reintegrate_cached_feedback(parallel):
    """A new pitch sample must not rerun/integrate the held depth sample."""
    controller, clock, frames = parallel
    controller._parallel_params['depth'].update(ki=1.)
    controller._configure_loops()
    controller.activate()
    feed(controller)
    integral = controller._loops['depth'].integral
    clock.now += .1
    assert not controller.update_depth(10., 'd1')
    controller.update_pitch(math.radians(6), 'p2')
    controller._update_control()
    assert controller._loops['depth'].integral == integral
    assert frames[-1].pec_angle == 1411


@pytest.mark.parametrize('missing', ['depth', 'pitch'])
def test_start_requires_both_post_start_samples(parallel, missing):
    """Pre-start cached values do not satisfy either new-data startup gate."""
    controller, clock, frames = parallel
    feed(controller)
    controller.activate()
    if missing == 'pitch':
        controller.update_depth(10., 'd2')
    else:
        controller.update_pitch(0., 'p2')
    controller._update_control()
    assert frames[-1].pec_angle == 1500


@pytest.mark.parametrize('stale', ['depth', 'pitch'])
def test_any_stale_loop_centers_and_requires_two_new_samples(parallel, stale):
    """One failed feedback never silently degrades into the other single-loop controller."""
    controller, clock, frames = parallel
    controller.activate()
    feed(controller)
    clock.now += .6
    if stale == 'pitch':
        controller.update_depth(10., 'd2')
    else:
        controller.update_pitch(0., 'p2')
    controller._update_control()
    assert frames[-1].pec_angle == 1500
    assert all(loop.integral == 0 for loop in controller._loops.values())
    controller.update_pitch(0., 'p3')
    controller._update_control()
    assert frames[-1].pec_angle == 1500
    feed(controller, identity=4)
    assert frames[-1].pec_angle == 1410


def test_final_limits_apply_after_both_contributions(parallel):
    """Opposing loop outputs cancel before clipping; saturation respects configured bounds."""
    controller, clock, frames = parallel
    controller._parallel_params['pitch']['kp'] = 20.
    controller._configure_loops()
    controller.activate()
    feed(controller)
    assert frames[-1].pec_angle == 1500
    feed(controller, depth=100., pitch=0., identity=2)
    assert frames[-1].pec_angle == 1700


@pytest.mark.parametrize('value', [None, float('nan'), float('inf'), 'bad'])
def test_bad_feedback_is_not_accepted(parallel, value):
    """Malformed values cannot reach PID arithmetic or a transmitted actuator frame."""
    controller, clock, frames = parallel
    assert not controller.update_depth(value, 1)
    assert not controller.update_pitch(value, 1)


def test_age_identity_and_dt_use_real_sample_arrivals(parallel):
    """Packet arrival age is retained and a duplicate never renews sensor freshness."""
    controller, clock, frames = parallel
    assert controller.update_depth(10., 1, received_at=clock.now, age_s=.4)
    arrival = controller._samples['depth']['arrival']
    clock.now += .2
    assert not controller.update_depth(10., 1)
    assert controller._samples['depth']['arrival'] == arrival
    assert controller.update_depth(10., 2)
    assert controller._samples['depth']['arrival'] == clock.now


def test_parallel_parameters_are_independent_persisted_and_validated(parallel):
    """All settings save to a separate file, while invalid actuator limits do not apply."""
    controller, clock, frames = parallel
    controller._loop_inputs['depth']['kp'].setValue(-3.)
    controller._loop_inputs['pitch']['target'].setValue(7.)
    controller._loop_inputs['pitch']['kd'].setValue(.25)
    assert controller._apply_depth_parameters()
    saved = json.loads(controller._params_path.read_text())
    assert saved['pitch']['target'] == 7.
    assert saved['depth']['kp'] == -3.
    assert saved['pitch']['kd'] == .25
    original = deepcopy(controller._parallel_params)
    controller._common_inputs['minimum_pwm'].setValue(2000)
    assert not controller._apply_depth_parameters()
    assert controller._parallel_params == original


def test_stop_and_restart_do_not_emit_cleanup_or_resume_old_pid(parallel):
    """Stopping is silent and repeat activation does not clear a running integrator."""
    controller, clock, frames = parallel
    controller.activate()
    feed(controller)
    count = len(frames)
    controller.activate()
    assert len(frames) == count
    controller.deactivate()
    controller._update_control()
    assert len(frames) == count
    controller.activate()
    assert frames[-1].pec_angle == 1500


def test_socket_keeps_independent_identities_and_does_not_refresh_cached_imu():
    """20Hz IMU and 10Hz depth snapshots cannot overwrite each other's freshness metadata."""
    client = SocketCommunication()
    imu = dict(type='imu', roll=0., pitch=.1, yaw=0., sample_id='imu1', age_s=.2)
    with patch('communication.socket_client.time.monotonic', return_value=10.):
        client._parse_sensor_data(json.dumps(imu))
    with patch('communication.socket_client.time.monotonic', return_value=11.):
        client._parse_sensor_data(json.dumps(imu))
        client._parse_sensor_data(json.dumps(dict(type='depth', fused=12., timestamp=200,
                                                  sample_id='depth1', age_s=.1)))
    state = client.get_fish_state()
    assert state.imu_sample['received_at'] == 10.
    assert state.depth_sample['received_at'] == 11.
    assert state.orientation['pitch'] == .1
    state.orientation['pitch'] = 999
    assert client.get_fish_state().orientation['pitch'] == .1


def test_legacy_imu_is_display_only_and_missing_pitch_is_not_zero():
    """A legacy or incomplete packet must never fabricate valid parallel feedback."""
    client = SocketCommunication()
    client._parse_sensor_data(json.dumps(dict(type='state', imu=dict(roll=0, pitch=.2, yaw=0))))
    assert client.get_fish_state().imu_sample is None
    client._parse_sensor_data(json.dumps(dict(type='imu', roll=0, yaw=0, sample_id='bad', age_s=0)))
    assert client.get_fish_state().orientation['pitch'] == .2


def test_main_window_parallel_selection_layout_lock_and_stale_source(window):
    """The parallel page has adjacent groups; switching is locked and old sources are rejected."""
    index = window.depth_controller_combo.findData('parallel_pid')
    assert index >= 0
    window.depth_controller_combo.setCurrentIndex(index)
    controller = window.controllers['parallel_depth']
    widget = controller.get_control_widget()
    window.show()
    ensure_app().processEvents()
    left, right = controller._loop_groups['depth'], controller._loop_groups['pitch']
    assert left.y() == right.y() and left.x() < right.x()
    assert not controller._loop_inputs['depth']['kp'].isEnabled()
    window.heading_enable_checkbox.setChecked(True)
    window.depth_enable_checkbox.setChecked(True)
    assert controller._loop_inputs['pitch']['kp'].isEnabled()
    assert window.axis_coordinator.depth is controller
    window.depth_controller_combo.setCurrentIndex(0)
    assert window.depth_controller_combo.currentData() == 'parallel_pid'
    assert window.axis_coordinator.depth is controller
    count = len(window.communication.commands)
    from communication.base import ControlCommand
    late = ControlCommand()
    late.pec_angle = 600
    window.controllers['depth'].control_command_generated.emit(late)
    assert len(window.communication.commands) == count
    window.depth_enable_checkbox.setChecked(False)
    window.depth_controller_combo.setCurrentIndex(0)
    assert window.axis_coordinator.heading_enabled
    assert window.axis_coordinator.depth is window.controllers['depth']


def test_parallel_view_compact_width_and_nonwrapping_labels(window):
    """Shrink the legacy wide sidebar while keeping both PID columns and complete editors."""
    from PyQt5.QtWidgets import QFormLayout
    from PyQt5.QtGui import QFont
    window.setFont(QFont('Microsoft YaHei', 18))
    window.show()
    window.main_splitter.setSizes([1000, 500, 240])
    window.depth_controller_combo.setCurrentIndex(window.depth_controller_combo.findData('parallel_pid'))
    ensure_app().processEvents()
    ensure_app().processEvents()  # Let font propagation and the queued splitter fit both settle.
    controller = window.controllers['parallel_depth']
    widget = controller.get_control_widget()
    assert widget.font().pointSizeF() == 9.
    assert widget.minimumSizeHint().width() <= 580  # Native Qt styles have different arrow padding.
    assert window.main_splitter.sizes()[0] <= 640
    groups = list(controller._loop_groups.values())
    assert groups[0].y() == groups[1].y()
    for form in widget.findChildren(QFormLayout):
        for row in range(form.rowCount()):
            label = form.itemAt(row, QFormLayout.LabelRole).widget()
            field = form.itemAt(row, QFormLayout.FieldRole).widget()
            assert not label.wordWrap()
            assert label.width() >= label.fontMetrics().horizontalAdvance(label.text())
            assert field.width() >= field.minimumSizeHint().width()
    assert all(not field.isEnabled() for field in controller._pid_parameter_widgets)


@pytest.fixture
def bridge():
    """Execute actual bridge methods without needing a Windows ROS2 installation."""
    source = Path(__file__).resolve().parents[3] / 'gs_bridge/gs_bridge/gs_bridge_node.py'
    tree = ast.parse(source.read_text(encoding='utf-8-sig'))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'GroundStationBridgeNode')
    methods = [node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name in
               ('_on_imu', '_on_depth', '_sample_stamp', '_feedback_payload', '_send_feedback', '_push_imu', '_push_depth',
                '_publish_control', '_publish_control_locked', '_handle_depth_control')]
    selected = ast.Module(body=[ast.ClassDef(name='Bridge', bases=[], keywords=[], body=methods, decorator_list=[])], type_ignores=[])
    namespace = dict(math=math, time=time, json=json,
                     clamp=lambda value, bounds: max(bounds[0], min(bounds[1], float(value))),
                     CONTROL_LIMITS=dict(tail_frequency=(0, 4), tail_amplitude=(0, .6), tail_offset=(-1, 1),
                                         tail_phase_diff=(-6.282, 6.282), pec_angle=(500, 2500)),
                     ActuatorCommand=lambda: SimpleNamespace(header=SimpleNamespace(stamp=None)))
    exec(compile(ast.fix_missing_locations(selected), str(source), 'exec'), namespace)
    obj = namespace['Bridge']()
    obj._sensor_epoch = 'test-boot'
    obj._sensor_sequences = dict(imu=0, depth=0)
    obj._imu_cache = obj._depth_cache = None
    obj._tcp_clients_lock = threading.Lock()
    obj._tcp_send_lock = threading.Lock()
    obj._depth_lock = threading.RLock()
    obj._depth_control = BoardDepthControl()
    obj._depth_timer = Mock()
    obj.command_pub = Mock()
    obj.get_clock = Mock()
    obj._ack_counter = 0
    obj._tcp_clients = []
    return obj


def imu_message(angle=10., stamp=1, scale=1.):
    """Build a sensor_msgs-compatible pitch quaternion with a controllable source stamp."""
    return SimpleNamespace(header=SimpleNamespace(stamp=SimpleNamespace(sec=stamp, nanosec=0)),
                           orientation=SimpleNamespace(x=0., y=scale*math.sin(math.radians(angle)/2),
                                                       z=0., w=scale*math.cos(math.radians(angle)/2)),
                           orientation_covariance=[0.]*9)


def test_bridge_normalizes_quaternions_and_keeps_repeated_source_stamp_stale(bridge):
    """Repeated callback stamps and repeated sends must not renew the original sample age."""
    with patch('time.monotonic', return_value=10.):
        bridge._on_imu(imu_message(scale=2.))
    with patch('time.monotonic', return_value=11.):
        bridge._on_imu(imu_message(scale=2.))
        payload = bridge._feedback_payload(bridge._imu_cache)
    assert payload['age_s'] == 1.
    assert bridge._sensor_sequences['imu'] == 1
    assert payload['pitch'] == pytest.approx(math.radians(10), abs=1e-4)
    assert '_received_at' not in payload


@pytest.mark.parametrize('invalid', ['zero', 'nan', 'missing-orientation'])
def test_bridge_invalid_quaternion_is_not_valid_control_feedback(bridge, invalid):
    """Uninitialized/non-finite/declared-missing orientation cannot become pitch=0."""
    message = imu_message()
    if invalid == 'zero':
        message.orientation = SimpleNamespace(x=0., y=0., z=0., w=0.)
    elif invalid == 'nan':
        message.orientation.w = float('nan')
    else:
        message.orientation_covariance[0] = -1.
    bridge._on_imu(message)
    assert bridge._imu_cache is None


def test_bridge_depth_invalid_fields_are_json_null_and_sample_stamps_do_not_refresh(bridge):
    """Sensor NaN/Inf never break the feedback timer's strict JSON serialization."""
    message = SimpleNamespace(header=imu_message().header, raw_1=float('inf'), filtered_1=float('nan'),
                              raw_2=1., filtered_2=2., fused=3.)
    bridge._on_depth(message)
    identity = bridge._depth_cache['sample_id']
    bridge._on_depth(message)
    assert bridge._depth_cache['sample_id'] == identity
    assert bridge._sensor_sequences['depth'] == 1
    payload = bridge._feedback_payload(bridge._depth_cache)
    assert payload['raw_1'] is None and payload['filtered_1'] is None
    json.dumps(payload, allow_nan=False)


def test_bridge_whole_lines_are_serialized_across_writers(bridge):
    """Independent IMU/depth/telemetry writers use one lock per complete JSON frame."""
    frames = []

    class Client:
        """Record complete messages without a network or ROS executor."""

        def sendall(self, data):
            """Assert the common send lock is held before recording a complete line."""
            assert bridge._tcp_send_lock.locked()
            frames.append(json.loads(data))

    bridge._tcp_clients = [(Client(), None)]
    bridge._on_imu(imu_message())
    bridge._push_imu()
    assert frames[-1]['type'] == 'imu'
    assert frames[-1]['sample_id'] == 'test-boot:imu:1'


def test_pico_blocks_heading_pectoral_values_while_depth_is_enabled(bridge):
    """Board arbitration rejects even a stale/old desktop manual PWM of 500us."""
    from controllers.parallel_depth import DEFAULTS
    bridge._depth_control.configure('parallel', DEFAULTS)
    bridge._depth_control.start()
    bridge._depth_control.output = 1420
    bridge._publish_control(dict(tail_frequency=2., tail_amplitude=.3, tail_offset=.1, pec_angle=500.))
    command = bridge.command_pub.publish.call_args.args[0]
    assert command.pectoral_pwm == 1420
    assert command.tail_frequency == 2. and command.tail_amplitude == .3
    bridge._depth_control.stop()
    bridge._publish_control(dict(tail_frequency=2., pec_angle=1600.))
    assert bridge.command_pub.publish.call_args.args[0].pectoral_pwm == 1600
