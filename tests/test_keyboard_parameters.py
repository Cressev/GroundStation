# -*- coding: utf-8 -*-
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtWidgets import QApplication

from controllers.base import KeyboardController


def ensure_app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def last_command_after_key(controller, key):
    commands = []
    controller.control_command_generated.connect(commands.append)
    controller.handle_key_press(key)
    controller._update_control()
    assert commands, f"no command emitted for {key}"
    return commands[-1]


def assert_command(command, freq, amp, offset):
    assert round(command.tail_frequency, 6) == round(freq, 6)
    assert round(command.tail_amplitude, 6) == round(amp, 6)
    assert round(command.tail_offset, 6) == round(offset, 6)


def test_slow_keyboard_mapping_uses_base_bias_and_turn_bias():
    ensure_app()
    controller = KeyboardController()
    controller.activate()
    controller.set_keyboard_parameters(
        base_bias=0.04,
        slow_frequency=1.1,
        slow_amplitude=0.16,
        slow_turn_bias=0.06,
        fast_frequency=1.8,
        fast_amplitude=0.3,
        fast_turn_bias=0.11,
    )

    assert_command(last_command_after_key(controller, "W"), 1.1, 0.16, 0.04)
    assert_command(last_command_after_key(controller, "A"), 1.1, 0.16, -0.02)
    assert_command(last_command_after_key(controller, "D"), 1.1, 0.16, 0.10)
    assert_command(last_command_after_key(controller, "S"), 0.0, 0.0, 0.04)

    controller.deactivate()


def test_fast_keyboard_mapping_uses_fast_frequency_amplitude_and_turn_bias():
    ensure_app()
    controller = KeyboardController()
    controller.activate()
    controller.set_keyboard_parameters(
        base_bias=-0.03,
        slow_frequency=1.0,
        slow_amplitude=0.12,
        slow_turn_bias=0.04,
        fast_frequency=1.9,
        fast_amplitude=0.35,
        fast_turn_bias=0.10,
    )

    assert_command(last_command_after_key(controller, "Shift+W"), 1.9, 0.35, -0.03)
    assert_command(last_command_after_key(controller, "Shift+A"), 1.9, 0.35, -0.13)
    assert_command(last_command_after_key(controller, "Shift+D"), 1.9, 0.35, 0.07)

    controller.deactivate()


def test_keyboard_parameters_are_clamped_before_commands_are_sent():
    ensure_app()
    controller = KeyboardController()
    controller.activate()
    controller.set_keyboard_parameters(
        base_bias=0.18,
        slow_frequency=5.0,
        slow_amplitude=5.0,
        slow_turn_bias=0.20,
        fast_frequency=9.0,
        fast_amplitude=9.0,
        fast_turn_bias=0.40,
    )

    assert_command(last_command_after_key(controller, "D"), 4.0, 0.5, 0.38)
    assert_command(last_command_after_key(controller, "Shift+A"), 4.0, 0.5, -0.22)

    controller.deactivate()


def test_keyboard_controller_exposes_base_bias_for_safe_disconnect_stop():
    ensure_app()
    controller = KeyboardController()
    controller.set_keyboard_parameters(
        base_bias=0.07,
        slow_frequency=1.0,
        slow_amplitude=0.1,
        slow_turn_bias=0.1,
        fast_frequency=1.5,
        fast_amplitude=0.2,
        fast_turn_bias=0.2,
    )

    assert round(controller.get_base_bias(), 6) == 0.07


if __name__ == "__main__":
    test_slow_keyboard_mapping_uses_base_bias_and_turn_bias()
    test_fast_keyboard_mapping_uses_fast_frequency_amplitude_and_turn_bias()
    test_keyboard_parameters_are_clamped_before_commands_are_sent()
    test_keyboard_controller_exposes_base_bias_for_safe_disconnect_stop()
    print("keyboard parameter tests passed")
