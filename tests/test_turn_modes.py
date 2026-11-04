"""Keyboard turn modes isolate commanded offset and waveform asymmetry."""
import json
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt5.QtWidgets import QApplication
from controllers.base import KeyboardController

APP = None

@pytest.mark.parametrize("mode,left,right", [
    ("bias", (-.15, .5), (.35, .5)),
    ("kappa", (.1, .7), (.1, .3)),
    ("combined", (-.15, .7), (.35, .3)),
])
def test_modes_apply_to_both_speeds_and_return_to_symmetric_forward(mode, left, right):
    global APP
    APP = QApplication.instance() or QApplication([])
    c = KeyboardController()
    c.set_keyboard_parameters(.1, 1, .2, .25, 2, .3, .25, tail_kappa=.7, turn_mode=mode)
    c.activate()
    for key, expected in (("a", left), ("d", right), ("A", left), ("D", right),
                          ("w", (.1, .5)), ("W", (.1, .5)), ("s", (.1, .5))):
        c.handle_key_press(key)
        c._update_control()
        cmd = c.get_current_command()
        assert cmd.tail_offset == pytest.approx(expected[0])
        assert cmd.tail_kappa == pytest.approx(expected[1])
    c.deactivate()


def test_mode_selection_is_applied_and_persisted(monkeypatch, tmp_path):
    global APP
    APP = QApplication.instance() or QApplication([])
    path = tmp_path / "keyboard.json"
    monkeypatch.setattr("controllers.base.PARAMS_FILE", str(path))
    c = KeyboardController()
    widget = c.get_control_widget()
    c._turn_mode_input.setCurrentIndex(c._turn_mode_input.findData("kappa"))
    c._apply_parameters_from_widget()
    assert json.loads(path.read_text(encoding="utf-8"))["turn_mode"] == "kappa"
    assert KeyboardController()._keyboard_params["turn_mode"] == "kappa"
    widget.close()


def test_single_tail_keeps_bias_control():
    global APP
    APP = QApplication.instance() or QApplication([])
    c = KeyboardController(enable_kappa=False)
    c.set_keyboard_parameters(0, 1, .2, .25, 2, .3, .4, tail_kappa=.7, turn_mode="kappa")
    c.activate()
    c.handle_key_press("a")
    c._update_control()
    assert c.get_current_command().tail_offset == pytest.approx(-.25)
    assert c.get_current_command().tail_kappa == .5
    c.deactivate()


@pytest.mark.parametrize("value", [.3, .7, .9])
def test_kappa_reverses_immediately_when_direction_key_changes(value):
    global APP
    APP = QApplication.instance() or QApplication([])
    c = KeyboardController()
    c.set_keyboard_parameters(0, 1, .2, .25, 2, .3, .25, tail_kappa=value, turn_mode="kappa")
    c.activate()
    for key, expected in (("a", value), ("d", 1-value), ("a", value)):
        c.handle_key_press(key)
        c._update_control()
        assert c.get_current_command().tail_kappa == pytest.approx(expected)
    c.deactivate()
