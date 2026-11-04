"""Exercise timed experiments and command ownership without a robot."""
from copy import deepcopy
import math

import pytest
from PyQt5.QtWidgets import QApplication

from controllers.autonomous import AutonomousController
from test_ui_state_machine import make_connected_window

APP = None


def make_controller():
    global APP
    APP = QApplication.instance() or QApplication([])
    now = [100.0]
    controller = AutonomousController(time_source=lambda: now[0])
    widget = controller.get_control_widget()
    controller.activate()
    commands = []
    controller.control_command_generated.connect(lambda command: commands.append(deepcopy(command)))
    return controller, widget, now, commands


def set_values(controller, **values):
    for key, value in values.items():
        controller._inputs[key].setValue(value)


def test_zero_straight_starts_turn_immediately_and_stops_at_deadline():
    c, widget, now, commands = make_controller()
    set_values(c, straight=0, turn=20, frequency=1.2, amplitude=.2,
               base_bias=.05, turn_bias=-.25, kappa=.7)
    assert c.start_experiment()
    assert commands[-1].tail_frequency == pytest.approx(1.2)
    assert commands[-1].tail_offset == pytest.approx(-.2)
    assert commands[-1].tail_kappa == pytest.approx(.7)
    assert commands[-1].tail_phase_diff == pytest.approx(math.pi / 4)
    now[0] += 20
    c._update_control()
    assert commands[-1].tail_frequency == 0
    assert commands[-1].tail_amplitude == 0
    assert commands[-1].tail_offset == pytest.approx(.05)
    c.deactivate()
    widget.close()


def test_straight_then_turn_snapshots_parameters_and_manual_stop():
    c, widget, now, commands = make_controller()
    set_values(c, straight=1, turn=10, turn_bias=.25, kappa=.3)
    assert c.start_experiment()
    assert commands[-1].tail_offset == 0 and commands[-1].tail_kappa == .5
    set_values(c, turn_bias=-.5, kappa=.9)
    now[0] += 1
    c._update_control()
    assert commands[-1].tail_offset == pytest.approx(.25)
    assert commands[-1].tail_kappa == pytest.approx(.3)
    c.stop_motion()
    assert commands[-1].tail_frequency == 0 and c._run is None
    now[0] += 20
    c._update_control()
    assert commands[-1].tail_frequency == 0
    c.deactivate()
    widget.close()


def test_no_empty_run_or_unarmed_start():
    c, widget, _, commands = make_controller()
    set_values(c, straight=0, turn=0)
    assert not c.start_experiment() and not commands
    c.deactivate()
    set_values(c, straight=0, turn=1)
    assert not c.start_experiment() and not commands
    widget.close()


def test_autonomous_is_separate_heading_source_and_disconnect_disarms():
    window, communication = make_connected_window()
    assert window._request_controller('autonomous')
    assert window.controller_combo.currentData() == 'autonomous'
    assert window.controller_actions['autonomous'].isChecked()
    c = window.controllers['autonomous']
    window.enable_control_checkbox.setChecked(True)
    set_values(c, straight=0, turn=10, turn_bias=.25, kappa=.7)
    assert c.start_experiment()
    assert communication.commands[-1].tail_offset == pytest.approx(.25)
    assert communication.commands[-1].tail_kappa == pytest.approx(.7)
    window.axis_coordinator.set_connected(False)
    assert not c.active and c._run is None
    window._fish_connection_state = 'disconnected'
    window.communication = None
    window.close()
