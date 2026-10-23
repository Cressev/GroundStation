"""Independent actuator ownership, PID composition and production-window safety tests."""

from dataclasses import replace
from unittest.mock import Mock, patch

import pytest
from PyQt5.QtCore import QSettings
from PyQt5.QtWidgets import QAbstractSpinBox

from communication.base import ControlCommand
from controllers.base import KeyboardController
from controllers.coordinator import ControlCoordinator
from controllers.depth_axis import DepthAxisController
from controllers.xbox import XboxController, XboxInputState, XINPUT_GAMEPAD_Y, XINPUT_GAMEPAD_X
from test_ui_state_machine import FakeCommunication, ensure_app
from ui.main_window import MainWindow
from ui.numeric_inputs import NoWheelDoubleSpinBox, NoWheelSpinBox


class Clock:
    """Keep sampling and timeout transitions deterministic without wall-clock waits."""

    def __init__(self):
        """Begin at a nonzero monotonic time."""
        self.now = 100.0

    def __call__(self):
        """Return the explicitly advanced time."""
        return self.now


@pytest.fixture
def axes(tmp_path):
    """Create real algorithms with a fake Xbox backend and no network/parameter writes."""
    ensure_app()
    clock = Clock()
    keyboard = KeyboardController()
    keyboard.set_keyboard_parameters(.03, 1., .2, .1, 2., .3, .2)
    backend = Mock(available=True)
    backend.poll.return_value = XboxInputState(connected=True, controller_index=0)
    backend.set_vibration.return_value = True
    xbox = XboxController(backend=backend, time_source=clock)
    xbox._poll_timer.stop()
    depth = DepthAxisController(time_source=clock, params_path=tmp_path/'depth.json')
    depth._depth_params.update(target_depth=20., kp=10., ki=0., kd=0., neutral_pwm=1500,
        minimum_pwm=500, maximum_pwm=2500, direction=-1, sensor_timeout=.5)
    depth._pid.configure(10, 0, 0, 1000)
    for controller in (keyboard, xbox, depth):
        controller.get_control_widget()
    coordinator = ControlCoordinator({'keyboard': keyboard, 'xbox': xbox}, depth)
    outputs = []
    coordinator.command_generated.connect(outputs.append)
    xbox.emergency_stop_requested.connect(lambda message: coordinator.emergency_stop())
    yield coordinator, keyboard, xbox, depth, clock, backend, outputs
    coordinator.set_connected(False)
    for controller in (keyboard, xbox, depth):
        controller.get_control_widget().close()
    xbox._vibration_timer.stop()


def step_depth(depth, value=10., sample=1):
    """Process one new depth sample through the unmodified single-loop PID math."""
    depth.update_depth(value, sample)
    depth._update_control()


def test_disconnected_channels_cannot_start(axes):
    """Neither channel can run before the transport has a confirmed connection."""
    hub, keyboard, xbox, depth, clock, backend, outputs = axes
    assert not hub.set_heading_enabled(True)
    assert not hub.set_depth_enabled(True)
    assert not keyboard.active and not depth.active and not outputs


def test_explicit_manual_pwm_prepared_while_stopped_is_not_lost_on_start(axes):
    """Editing a manual setpoint before enabling heading remains an intentional input."""
    hub, keyboard, xbox, depth, clock, backend, outputs = axes
    hub.set_connected(True)
    keyboard.set_pec_pulse(1820)
    assert not outputs
    hub.set_heading_enabled(True)
    assert outputs[-1].pec_angle == 1820


def test_inactive_xbox_preview_follows_depth_pwm_outside_manual_limits(axes):
    """Background Xbox refresh must not display or restore its obsolete manual limits."""
    hub, keyboard, xbox, depth, clock, backend, outputs = axes
    hub.set_connected(True)
    hub.set_depth_enabled(True)
    frame = ControlCommand()
    frame.pec_angle = 2400
    hub.receive_depth(frame)
    xbox._poll_controller()
    assert xbox._model._last_output.pec_pwm == 2400
    assert '2400' in xbox._pec_label.text()
    hub.set_depth_enabled(False)
    hub.select_heading('xbox')
    hub.set_heading_enabled(True)
    assert outputs[-1].pec_angle == 2400


@pytest.mark.parametrize('heading', ['keyboard', 'xbox'])
def test_each_heading_combines_with_pid_without_overwriting_tail(axes, heading):
    """Both heading algorithms keep every tail field while depth updates only pectoral PWM."""
    hub, keyboard, xbox, depth, clock, backend, outputs = axes
    hub.set_connected(True)
    assert hub.select_heading(heading)
    assert hub.set_heading_enabled(True)
    assert hub.set_depth_enabled(True)
    command = ControlCommand(freq=1.7, amp=.27, offset=.13)
    command.tail_phase_diff, command.pec_angle = -.7, 2300
    hub.receive_heading(heading, command)
    step_depth(depth)
    actual = outputs[-1]
    assert (actual.tail_frequency, actual.tail_amplitude, actual.tail_offset,
            actual.tail_phase_diff, actual.pec_angle) == (1.7, .27, .13, -.7, 1400)
    command.tail_amplitude = .49
    depth._update_control()
    assert outputs[-1].tail_amplitude == .27  # copied, not a mutable controller reference


def test_depth_alone_does_not_start_heading(axes):
    """Only depth active means zero tail movement without requiring a keyboard/gamepad."""
    hub, keyboard, xbox, depth, clock, backend, outputs = axes
    hub.set_connected(True)
    hub.set_depth_enabled(True)
    step_depth(depth)
    assert not keyboard.active and not xbox.active and not hub.heading_enabled
    assert outputs[-1].tail_frequency == outputs[-1].tail_amplitude == 0
    assert outputs[-1].pec_angle == 1400


def test_stopping_heading_preserves_running_depth(axes):
    """Stopping tail motion must not reset integrator/sample state or pectoral ownership."""
    hub, keyboard, xbox, depth, clock, backend, outputs = axes
    hub.set_connected(True)
    hub.set_heading_enabled(True)
    keyboard.handle_key_press('w')
    keyboard._update_control()
    hub.set_depth_enabled(True)
    step_depth(depth)
    hub.set_heading_enabled(False)
    assert hub.depth_enabled and depth.active and depth._pid_enabled
    assert outputs[-1].tail_amplitude == 0 and outputs[-1].pec_angle == 1400
    clock.now += .1
    step_depth(depth, 15, 2)
    assert outputs[-1].tail_amplitude == 0 and outputs[-1].pec_angle == 1450


@pytest.mark.parametrize('heading', ['keyboard', 'xbox'])
def test_stopping_depth_hands_back_actual_pwm_without_jump(axes, heading):
    """Manual controls resume from the last transmitted PWM, not a hidden pre-PID value."""
    hub, keyboard, xbox, depth, clock, backend, outputs = axes
    hub.set_connected(True)
    hub.select_heading(heading)
    hub.set_heading_enabled(True)
    hub.set_depth_enabled(True)
    step_depth(depth)
    hub.set_depth_enabled(False)
    assert hub.heading_enabled and hub.heading.active
    assert outputs[-1].pec_angle == 1400
    assert hub.heading._pec_angle == 1400
    assert hub.heading._pectoral_override is None
    if heading == 'keyboard':
        keyboard.handle_key_press('w')
        keyboard._update_control()
    else:
        clock.now += .1
        xbox._poll_controller()
    assert outputs[-1].pec_angle == 1400


def test_manual_pectoral_inputs_are_blocked_not_accumulated_during_pid(axes):
    """QE/direct PWM and Xbox Y/A/RT/center cannot fight depth or leave a hidden offset."""
    hub, keyboard, xbox, depth, clock, backend, outputs = axes
    hub.set_connected(True)
    hub.set_heading_enabled(True)
    hub.set_depth_enabled(True)
    step_depth(depth)
    keyboard.handle_key_press('Q')
    keyboard._update_control()
    assert not keyboard.set_pec_pulse(2100)
    assert keyboard._pec_angle == outputs[-1].pec_angle == 1400
    assert not keyboard._pec_pulse_input.isEnabled()
    hub.set_heading_enabled(False)
    hub.select_heading('xbox')
    hub.set_heading_enabled(True)
    backend.poll.return_value = XboxInputState(connected=True, controller_index=0,
        left_y=1., buttons=XINPUT_GAMEPAD_Y, right_trigger=1.)
    clock.now += .1
    xbox._poll_controller()
    xbox._center_pectoral()
    assert xbox._model._pec_pwm == 1400
    assert outputs[-1].pec_angle == 1400
    assert not xbox._center_button.isEnabled()


def test_stale_sources_and_inactive_depth_cannot_publish(axes):
    """Source identity and enabled flags must reject every late/old-controller signal."""
    hub, keyboard, xbox, depth, clock, backend, outputs = axes
    hub.set_connected(True)
    hub.set_heading_enabled(True)
    count = len(outputs)
    command = ControlCommand()
    command.pec_angle = 2000
    hub.receive_heading('xbox', command)
    hub.receive_depth(command)
    assert len(outputs) == count
    hub.stop_all()
    count = len(outputs)
    hub.receive_heading('keyboard', command)
    hub.receive_depth(command)
    assert len(outputs) == count


def test_running_heading_cannot_switch_and_repeated_operations_are_idempotent(axes):
    """Only the running axis is locked and same-state requests do not reinitialize PID."""
    hub, keyboard, xbox, depth, clock, backend, outputs = axes
    hub.set_connected(True)
    hub.set_heading_enabled(True)
    count = len(outputs)
    assert not hub.select_heading('xbox')
    assert hub.set_heading_enabled(True) and len(outputs) == count
    hub.set_depth_enabled(True)
    step_depth(depth)
    sample = depth._processed_depth_sequence
    count = len(outputs)
    hub.set_depth_enabled(True)
    assert depth._processed_depth_sequence == sample and len(outputs) == count
    hub.set_heading_enabled(False)
    assert hub.select_heading('xbox')
    assert hub.depth_enabled and depth._processed_depth_sequence == sample


def test_start_requires_new_sample_and_timeout_keeps_tail_but_centers_pectoral(axes):
    """Cached pre-start/duplicate depth cannot integrate; timeout uses the original fail-safe."""
    hub, keyboard, xbox, depth, clock, backend, outputs = axes
    hub.set_connected(True)
    depth.update_depth(10., 1)
    hub.set_heading_enabled(True)
    keyboard.handle_key_press('w')
    keyboard._update_control()
    hub.set_depth_enabled(True)
    depth._update_control()
    assert outputs[-1].pec_angle == 1500
    assert not depth.update_depth(10., 1)
    step_depth(depth, 10, 2)
    assert outputs[-1].pec_angle == 1400
    clock.now += 1.
    depth._update_control()
    assert outputs[-1].pec_angle == 1500 and outputs[-1].tail_amplitude == .2
    assert '超时' in depth._pid_status


@pytest.mark.parametrize('event', ['emergency', 'disconnect'])
def test_emergency_and_disconnect_revoke_both_axes_without_automatic_resume(axes, event):
    """X/B holds actual pectoral PWM; both cases reject late frames and never rearm."""
    hub, keyboard, xbox, depth, clock, backend, outputs = axes
    hub.set_connected(True)
    hub.set_heading_enabled(True)
    hub.set_depth_enabled(True)
    step_depth(depth)
    if event == 'emergency':
        hub.emergency_stop()
        assert outputs[-1].tail_amplitude == 0 and outputs[-1].pec_angle == 1400
    else:
        hub.set_connected(False)
    assert not hub.heading_enabled and not hub.depth_enabled
    assert not depth._pid_enabled and not keyboard.active
    count = len(outputs)
    depth._update_control()
    keyboard._update_control()
    hub.set_connected(True)
    assert not hub.heading_enabled and not hub.depth_enabled and len(outputs) == count


def test_no_gamepad_does_not_stop_an_independent_running_pid(axes):
    """Failed Xbox activation leaves the depth channel running and heading disabled."""
    hub, keyboard, xbox, depth, clock, backend, outputs = axes
    hub.set_connected(True)
    hub.set_depth_enabled(True)
    hub.select_heading('xbox')
    backend.poll.return_value = XboxInputState()
    assert not hub.set_heading_enabled(True)
    assert hub.depth_enabled and not hub.heading_enabled
    step_depth(depth)
    assert outputs[-1].tail_amplitude == 0 and outputs[-1].pec_angle == 1400


@pytest.fixture
def window(tmp_path):
    """Use the production main window with isolated settings and a non-network transport."""
    ensure_app()
    settings = QSettings(str(tmp_path/'window.ini'), QSettings.IniFormat)
    with patch('ui.main_window.QSettings', return_value=settings):
        view = MainWindow('dual')
    view.controllers['xbox']._poll_timer.stop()
    view.communication = FakeCommunication()
    view._fish_connection_state = 'connected'
    view._apply_main_ui_state()
    yield view
    view._stop_all_controls(send_stop=False)
    view._fish_connection_state = 'disconnected'
    view.communication = None
    view.close()


def test_production_layout_independent_checkboxes_types_and_right_bottom_log(window):
    """One scroll area contains ordered axis sections, while logs live in the right panel."""
    assert window.heading_group.title() == '航向控制'
    assert window.depth_group.title() == '深度控制'
    assert window.axis_control_scroll.widget().isAncestorOf(window.heading_group)
    assert window.axis_control_scroll.widget().isAncestorOf(window.depth_group)
    assert window.right_panel.isAncestorOf(window.info_text)
    assert not window.left_panel.isAncestorOf(window.info_text)
    assert window.controller_combo.findData('depth') == -1
    assert window.depth_controller_combo.currentData() == 'pid'
    assert len(window.controllers['depth'].get_control_widget().findChildren(QAbstractSpinBox)) == 10
    window.depth_enable_checkbox.setChecked(True)
    assert window.axis_coordinator.depth_enabled and not window._control_armed
    assert window.controller_combo.isEnabled() and not window.depth_controller_combo.isEnabled()
    window.heading_enable_checkbox.setChecked(True)
    assert window.axis_coordinator.heading_enabled and window.axis_coordinator.depth_enabled
    assert not window.controller_combo.isEnabled()
    window.heading_enable_checkbox.setChecked(False)
    assert window.axis_coordinator.depth_enabled
    assert '深度控制仍运行' in window.status_bar.currentMessage()
    window.all_stop_button.click()
    assert not window.axis_coordinator.depth_enabled


@pytest.mark.parametrize('event', ['x-button', 'gamepad-disconnected'])
def test_window_xbox_x_stops_both_axes_and_holds_actual_depth_pwm(window, event):
    """Production signal wiring must treat Xbox emergency as a whole-system stop."""
    xbox = window.controllers['xbox']
    backend = Mock(available=True)
    backend.poll.return_value = XboxInputState(connected=True, controller_index=0)
    xbox._backend = backend
    window._request_controller('xbox')
    window.heading_enable_checkbox.setChecked(True)
    window.depth_enable_checkbox.setChecked(True)
    depth_frame = ControlCommand(freq=4, amp=.5, offset=.4)
    depth_frame.pec_angle = 1370
    window.axis_coordinator.receive_depth(depth_frame)
    backend.poll.return_value = (replace(backend.poll.return_value, buttons=XINPUT_GAMEPAD_X)
                                if event == 'x-button' else XboxInputState())
    xbox._poll_controller()
    assert not window.heading_enable_checkbox.isChecked()
    assert not window.depth_enable_checkbox.isChecked()
    assert not window.axis_coordinator.depth_enabled
    actual = window.communication.commands[-1]
    assert actual.tail_amplitude == 0 and actual.pec_angle == 1370


def test_control_axes_keep_all_numeric_fields_wheel_safe(window):
    """Both new axis sections must retain the previous no-wheel editing policy."""
    for name in ('keyboard', 'xbox'):
        window._request_controller(name)
        for spin in window.axis_control_scroll.findChildren(QAbstractSpinBox):
            assert isinstance(spin, (NoWheelSpinBox, NoWheelDoubleSpinBox))


@pytest.mark.parametrize('heading', ['keyboard', 'xbox'])
def test_parameter_editability_follows_each_axis_start_without_extra_unlock(window, heading):
    """Stopped axes are grey; each successful start directly enables only its own parameters."""
    xbox = window.controllers['xbox']
    xbox._backend = Mock(available=True)
    xbox._backend.poll.return_value = XboxInputState(connected=True, controller_index=0)
    window._request_controller(heading)
    heading_widget = window.current_controller.get_control_widget()
    depth = window.controllers['depth']
    heading_fields = heading_widget.findChildren(QAbstractSpinBox)
    assert heading_fields and all(not field.isEnabled() for field in heading_fields)
    assert all(not field.isEnabled() for field in depth._pid_parameter_widgets)
    assert not depth._apply_pid_button.isEnabled()
    assert depth._parameter_unlock_checkbox.isHidden()
    assert window.controller_combo.isEnabled() and window.depth_controller_combo.isEnabled()
    window.depth_enable_checkbox.setChecked(True)
    assert all(field.isEnabled() for field in depth._pid_parameter_widgets)
    assert depth._apply_pid_button.isEnabled()
    assert all(not field.isEnabled() for field in heading_fields)
    window.heading_enable_checkbox.setChecked(True)
    assert window.controller_widget_container.isEnabled()
    assert all(field.isEnabled() for field in heading_fields
               if field is not getattr(window.current_controller, '_pec_pulse_input', None))
    assert not window.controller_combo.isEnabled()
    depth._kp_input.setValue(12.34)
    window.heading_enable_checkbox.setChecked(False)
    assert all(not field.isEnabled() for field in heading_fields)
    assert depth._kp_input.isEnabled() and depth._kp_input.value() == 12.34
    window.depth_enable_checkbox.setChecked(False)
    assert all(not field.isEnabled() for field in depth._pid_parameter_widgets)
    assert not depth._apply_pid_button.isEnabled()
    window.depth_enable_checkbox.setChecked(True)
    assert depth._kp_input.isEnabled() and depth._kp_input.value() == 12.34


@pytest.mark.parametrize('event', ['stop', 'emergency', 'disconnect'])
def test_safety_events_grey_both_parameter_panels_without_rearming(window, event):
    """Whole-system stops and link loss restore the same locked state as initial startup."""
    window.heading_enable_checkbox.setChecked(True)
    window.depth_enable_checkbox.setChecked(True)
    if event == 'stop':
        window.all_stop_button.click()
    elif event == 'emergency':
        window.axis_coordinator.emergency_stop()
    else:
        window._handle_connection_changed(window.communication, False)
    assert not window.controller_widget_container.isEnabled()
    assert not window.depth_widget_container.isEnabled()
    assert not window.controllers['depth']._apply_pid_button.isEnabled()
    window._apply_main_ui_state()
    assert not window.controller_widget_container.isEnabled()
    assert not window.depth_widget_container.isEnabled()


def test_failed_xbox_start_keeps_heading_parameters_grey(window):
    """A checked request is not an active controller when no gamepad can be opened."""
    xbox = window.controllers['xbox']
    xbox._backend = Mock(available=True)
    xbox._backend.poll.return_value = XboxInputState()
    window._request_controller('xbox')
    window.heading_enable_checkbox.setChecked(True)
    assert not window.heading_enable_checkbox.isChecked()
    assert not window.controller_widget_container.isEnabled()


@pytest.mark.parametrize('invalid', [None, 'not-a-number', float('nan')])
def test_non_numeric_axis_frames_are_rejected_without_publishing(axes, invalid):
    """Bad axis output must not raise inside a Qt slot or reach JSON/actuator frames."""
    hub, keyboard, xbox, depth, clock, backend, outputs = axes
    hub.set_connected(True)
    hub.set_heading_enabled(True)
    hub.set_depth_enabled(True)
    count = len(outputs)
    command = ControlCommand()
    command.tail_amplitude = command.pec_angle = invalid
    hub.receive_heading('keyboard', command)
    hub.receive_depth(command)
    assert len(outputs) == count


def test_type_selector_cannot_change_from_page_wheel_and_cached_widgets_survive(window):
    """Scrolling type selectors is a no-op and repeated switches preserve unapplied input."""
    from test_control_no_wheel import wheel
    selected = window.controller_combo.currentData()
    wheel(window.controller_combo, -120)
    assert window.controller_combo.currentData() == selected
    keyboard = window.controllers['keyboard']
    keyboard._param_inputs['slow_frequency'].setValue(1.23)
    depth_widget = window.controllers['depth'].get_control_widget()
    for _ in range(4):
        assert window._request_controller('xbox')
        assert window._request_controller('keyboard')
    assert keyboard._param_inputs['slow_frequency'].value() == 1.23
    assert window.controllers['depth'].get_control_widget() is depth_widget


def test_remote_connection_loss_revokes_depth_only_and_late_pid_cannot_send(window):
    """A main-link failure must stop depth even when heading was never enabled."""
    transport = window.communication
    window.depth_enable_checkbox.setChecked(True)
    count = len(transport.commands)
    window._handle_connection_changed(transport, False)
    assert window._fish_connection_state == 'disconnected'
    assert not window.axis_coordinator.depth_enabled
    assert not window.depth_enable_checkbox.isChecked()
    window.controllers['depth']._update_control()
    assert len(transport.commands) == count


def test_compact_depth_form_keeps_parameter_names_visible(window):
    """Wrapping long sidebar explanations must not collapse QFormLayout label columns."""
    from PyQt5.QtWidgets import QLabel
    window.show()
    ensure_app().processEvents()
    labels = window.controllers['depth'].get_control_widget().findChildren(QLabel)
    names = [label for label in labels if label.text() in ('目标深度', 'Kp', '中位脉宽', '输出方向')]
    assert len(names) == 4
    assert all(label.width() > 0 and not label.isHidden() for label in names)


@pytest.mark.parametrize('heading', ['keyboard', 'xbox', 'depth'])
@pytest.mark.parametrize('font_size', [12, 18])
@pytest.mark.parametrize('width', [420, 580])
def test_parameter_labels_do_not_wrap_and_fields_use_available_width(window, heading, font_size, width):
    """Parameter names retain a full line under wide sidebars and large Windows fonts."""
    from PyQt5.QtGui import QFont
    from PyQt5.QtWidgets import QLabel, QGridLayout, QFormLayout, QWidget
    controller = window.controllers[heading]
    if heading != 'depth':
        window._request_controller(heading)
    widget = controller.get_control_widget()
    original_parent = widget.parentWidget()
    container = QWidget()
    from PyQt5.QtWidgets import QVBoxLayout
    layout = QVBoxLayout(container)
    widget.setParent(container)
    layout.addWidget(widget)
    container.setFont(QFont('Microsoft YaHei', font_size))
    container.resize(width, 1800)
    container.show()
    ensure_app().processEvents()
    try:
        labels = []
        for grid in widget.findChildren(QGridLayout):
            for row in range(grid.rowCount()):
                item = grid.itemAtPosition(row, 0)
                field = grid.itemAtPosition(row, 1)
                label = item.widget() if item is not None else None
                if (isinstance(label, QLabel) and field is not None and
                        (isinstance(field.widget(), QAbstractSpinBox) or field.layout() is not None)):
                    labels.append(label)
        for form in widget.findChildren(QFormLayout):
            for row in range(form.rowCount()):
                labels.append(form.itemAt(row, QFormLayout.LabelRole).widget())
        assert labels
        for label in labels:
            assert not label.wordWrap(), label.text()
            assert label.width() >= label.sizeHint().width(), (label.text(), label.width(), label.sizeHint().width())
        for spin in widget.findChildren(QAbstractSpinBox):
            assert spin.lineEdit().width() >= spin.fontMetrics().horizontalAdvance(spin.text()), (heading, spin.text(), spin.lineEdit().width())
            if heading != 'keyboard' or spin is not controller._pec_pulse_input:
                assert spin.width() > 140, (heading, spin.width())
        if heading == 'keyboard':
            grid = controller._param_inputs['base_bias'].parentWidget().layout()
            spin = controller._param_inputs['base_bias']
            assert spin.geometry().right() >= grid.contentsRect().right() - 2
    finally:
        widget.setParent(original_parent)
        container.close()


@pytest.mark.parametrize('event', ['x-button', 'gamepad-disconnected'])
def test_selected_xbox_emergency_stops_depth_when_heading_is_not_running(window, event):
    """A selected gamepad retains emergency authority during a depth-only experiment."""
    xbox = window.controllers['xbox']
    backend = Mock(available=True)
    backend.poll.return_value = XboxInputState(connected=True, controller_index=0)
    xbox._backend = backend
    window._request_controller('xbox')
    window.depth_enable_checkbox.setChecked(True)
    xbox._poll_controller()
    assert not window._control_armed and window.axis_coordinator.depth_enabled
    frame = ControlCommand()
    frame.pec_angle = 1410
    window.axis_coordinator.receive_depth(frame)
    backend.poll.return_value = (replace(backend.poll.return_value, buttons=XINPUT_GAMEPAD_X)
                                if event == 'x-button' else XboxInputState())
    xbox._poll_controller()
    assert not window.axis_coordinator.depth_enabled and not window._control_armed
    assert window.communication.commands[-1].tail_amplitude == 0
    assert window.communication.commands[-1].pec_angle == 1410
