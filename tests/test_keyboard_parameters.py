# -*- coding: utf-8 -*-
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtWidgets import QApplication

from controllers.base import KeyboardController

_APP = None


def ensure_app():
    """创建并持有唯一 QApplication，避免局部引用释放导致 QWidget 测试退出。"""
    global _APP
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    _APP = app
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

    assert_command(last_command_after_key(controller, "w"), 1.1, 0.16, 0.04)
    assert_command(last_command_after_key(controller, "a"), 1.1, 0.16, -0.02)
    assert_command(last_command_after_key(controller, "d"), 1.1, 0.16, 0.10)
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

    assert_command(last_command_after_key(controller, "d"), 4.0, 0.5, 0.38)
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


def test_pec_pulse_can_be_set_directly_across_full_safe_range():
    """胸鳍直接设定应立即发命令，并把越界值限制到 500–2500 μs。"""
    ensure_app()
    controller = KeyboardController()
    controller.activate()
    controller.get_control_widget()
    assert controller._pec_pulse_input.minimum() == 500
    assert controller._pec_pulse_input.maximum() == 2500
    commands = []
    controller.control_command_generated.connect(commands.append)

    controller.set_pec_pulse(500)
    assert commands[-1].pec_angle == 500
    controller.set_pec_pulse(2500)
    assert commands[-1].pec_angle == 2500
    controller.set_pec_pulse(3000)
    assert commands[-1].pec_angle == 2500
    controller._pec_pulse_input.setValue(1750)
    controller._set_pec_from_widget()
    assert commands[-1].pec_angle == 1750

    controller.deactivate()


def test_pec_pulse_manual_input_is_not_overwritten_by_control_timer():
    """控制定时器运行时应保留输入框中尚未点击设定的新数字。"""
    ensure_app()
    controller = KeyboardController()
    controller.activate()
    controller.get_control_widget()

    controller._pec_pulse_input.lineEdit().setText("1820")
    controller._update_control()

    assert controller._pec_pulse_input.value() == 1820
    assert controller._pec_angle == 1500
    controller._set_pec_from_widget()
    assert controller._pec_angle == 1820

    controller.deactivate()


if __name__ == "__main__":
    test_slow_keyboard_mapping_uses_base_bias_and_turn_bias()
    test_fast_keyboard_mapping_uses_fast_frequency_amplitude_and_turn_bias()
    test_keyboard_parameters_are_clamped_before_commands_are_sent()
    test_keyboard_controller_exposes_base_bias_for_safe_disconnect_stop()
    test_pec_pulse_can_be_set_directly_across_full_safe_range()
    test_pec_pulse_manual_input_is_not_overwritten_by_control_timer()
    print("keyboard parameter tests passed")
