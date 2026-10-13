#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""地面站深度 PID 控制器的离线回归测试。"""

import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtWidgets import QApplication

from communication.base import FishState
from controllers.depth import DepthController, PID
from ui.main_window import MainWindow


_APP = None


class FakeClock:
    """可手动推进的单调时钟。"""

    def __init__(self):
        """从零秒开始计时。"""
        self.now = 0.0

    def __call__(self):
        """返回当前模拟时间。"""
        return self.now

    def advance(self, seconds):
        """推进指定秒数。"""
        self.now += seconds


def ensure_app():
    """创建并持有唯一 QApplication。"""
    global _APP
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    _APP = app
    return app


def make_controller(clock, directory):
    """创建使用临时参数文件的已激活控制器。"""
    controller = DepthController(
        time_source=clock,
        params_path=Path(directory) / "depth_pid_params.json")
    controller.get_control_widget()
    controller.activate()
    return controller


def unlock_and_set(controller, **values):
    """解锁参数区、设置指定输入并应用。"""
    controller._parameter_unlock_checkbox.setChecked(True)
    mapping = {
        "target_depth": controller._target_depth_input,
        "kp": controller._kp_input,
        "ki": controller._ki_input,
        "kd": controller._kd_input,
        "integral_limit": controller._integral_limit_input,
        "neutral_pwm": controller._neutral_pwm_input,
        "minimum_pwm": controller._minimum_pwm_input,
        "maximum_pwm": controller._maximum_pwm_input,
        "sensor_timeout": controller._sensor_timeout_input,
    }
    for key, value in values.items():
        if key == "direction":
            controller._direction_input.setCurrentIndex(
                controller._direction_input.findData(value))
        else:
            mapping[key].setValue(value)
    assert controller._apply_depth_parameters()


def test_pid_math_exposes_all_three_terms():
    """PID 应正确累计积分、计算微分并暴露三个分量。"""
    pid = PID(kp=2.0, ki=3.0, kd=4.0, integral_limit=10.0)
    assert pid.update(2.0, 0.5) == 7.0
    assert pid.terms == (4.0, 3.0, 0.0)
    assert pid.update(1.0, 0.5) == -1.5
    assert pid.terms == (2.0, 4.5, -8.0)


def test_parameter_lock_and_middle_position_controls():
    """参数锁关闭时全部置灰，解锁后负增益、中位和边界均可调。"""
    ensure_app()
    clock = FakeClock()
    with tempfile.TemporaryDirectory() as directory:
        controller = make_controller(clock, directory)
        assert all(not widget.isEnabled()
                   for widget in controller._pid_parameter_widgets)
        assert not controller._apply_pid_button.isEnabled()
        assert controller._target_depth_input.minimum() == 0.0
        assert controller._direction_input.currentData() == -1
        assert controller._direction_input.currentText() == "目标更深时减小脉宽"

        unlock_and_set(
            controller,
            kp=-2.5,
            ki=-0.125,
            kd=-0.75,
            neutral_pwm=1520,
            minimum_pwm=1320,
            maximum_pwm=1680,
            sensor_timeout=0.8)
        assert controller._depth_params["neutral_pwm"] == 1520
        assert controller._depth_params["kp"] == -2.5
        assert controller._depth_params["ki"] == -0.125
        assert controller._depth_params["kd"] == -0.75
        assert controller._kp_input.minimum() == -1000.0
        assert controller._depth_params["minimum_pwm"] == 1320
        assert controller._depth_params["maximum_pwm"] == 1680
        assert controller._depth_params["sensor_timeout"] == 0.8
        saved = json.loads(
            (Path(directory) / "depth_pid_params.json").read_text(
                encoding="utf-8"))
        assert saved["coordinate_convention"] == "positive_down_v2"
        assert saved["kp"] == -2.5
        controller.deactivate()


def test_legacy_negative_down_parameters_migrate_to_positive_down_defaults():
    """旧负向坐标参数必须重置目标和方向，其他整定值保留。"""
    ensure_app()
    clock = FakeClock()
    with tempfile.TemporaryDirectory() as directory:
        params_path = Path(directory) / "depth_pid_params.json"
        params_path.write_text(json.dumps({
            "coordinate_convention": "negative_down_v1",
            "target_depth": -15.0,
            "kp": 7.0,
            "direction": 1,
        }), encoding="utf-8")
        controller = make_controller(clock, directory)
        assert controller._depth_params["coordinate_convention"] == "positive_down_v2"
        assert controller._depth_params["target_depth"] == 15.0
        assert controller._depth_params["direction"] == -1
        assert controller._depth_params["kp"] == 7.0
        controller.deactivate()


def test_depth_pid_and_keyboard_motion_work_together():
    """深度 PID 接管胸鳍时，键盘 W 仍应控制尾鳍推进。"""
    ensure_app()
    clock = FakeClock()
    with tempfile.TemporaryDirectory() as directory:
        controller = make_controller(clock, directory)
        unlock_and_set(
            controller,
            target_depth=20.0,
            kp=20.0,
            ki=0.0,
            kd=0.0,
            neutral_pwm=1500,
            minimum_pwm=1300,
            maximum_pwm=1700,
            direction=-1)
        commands = []
        controller.control_command_generated.connect(commands.append)
        controller.set_pid_enabled(True)
        controller.update_depth(10.0, sample_id=1)
        controller.handle_key_press("w")
        controller._update_control()

        command = commands[-1]
        assert command.pec_angle == 1300
        assert command.tail_frequency == controller._keyboard_params["slow_frequency"]
        assert command.tail_amplitude == controller._keyboard_params["slow_amplitude"]
        assert controller._pid_terms == (200.0, 0.0, 0.0)
        controller.deactivate()


def test_pid_output_direction_can_be_reversed():
    """同一深度误差在反向设置下应产生相反胸鳍修正。"""
    ensure_app()
    clock = FakeClock()
    with tempfile.TemporaryDirectory() as directory:
        controller = make_controller(clock, directory)
        unlock_and_set(
            controller,
            target_depth=20.0,
            kp=10.0,
            neutral_pwm=1500,
            minimum_pwm=1200,
            maximum_pwm=1800,
            direction=1)
        controller.set_pid_enabled(True)
        controller.update_depth(10.0, sample_id=1)
        controller._update_control()
        assert controller._pec_angle == 1600
        controller.deactivate()


def test_sensor_timeout_returns_pectoral_to_middle():
    """深度数据超时必须回中并复位 PID。"""
    ensure_app()
    clock = FakeClock()
    with tempfile.TemporaryDirectory() as directory:
        controller = make_controller(clock, directory)
        unlock_and_set(
            controller,
            target_depth=20.0,
            kp=10.0,
            neutral_pwm=1500,
            minimum_pwm=1300,
            maximum_pwm=1700,
            sensor_timeout=0.5,
            direction=-1)
        controller.set_pid_enabled(True)
        controller.update_depth(10.0, sample_id=1)
        controller._update_control()
        assert controller._pec_angle == 1400

        clock.advance(0.6)
        controller._update_control()
        assert controller._pec_angle == 1500
        assert controller._pid.integral == 0.0
        assert controller._pid_status == "深度数据超时，胸鳍已回中"
        controller.deactivate()


def test_pid_off_restores_manual_qe_control():
    """PID 关闭后 Q/E 应恢复手动调节；开启时 Q/E 不得抢占胸鳍。"""
    ensure_app()
    clock = FakeClock()
    with tempfile.TemporaryDirectory() as directory:
        controller = make_controller(clock, directory)
        controller.handle_key_press("Q")
        controller._update_control()
        controller.handle_key_release("Q")
        assert controller._pec_angle == 1510

        controller.set_pid_enabled(True)
        controller.handle_key_press("Q")
        controller._update_control()
        controller.handle_key_release("Q")
        assert controller._pec_angle == 1500
        controller.deactivate()


def test_dual_main_window_exposes_depth_controller():
    """双尾鱼主窗口应注册控制器，并把标定后融合深度送入控制器。"""
    ensure_app()
    window = MainWindow("dual")
    assert window.controller_combo.findData("depth") >= 0
    assert isinstance(window.controllers["depth"], DepthController)
    widget = window.controllers["depth"].get_control_widget()
    assert widget is not None
    assert not window.controllers["depth"]._target_depth_input.isEnabled()

    state = FishState()
    state.depth = {"fused": 42.0}
    state.timestamp = 123.0
    communication = type(
        "FakeCommunication", (),
        {"connected": True, "get_fish_state": lambda self: state})()
    window.communication = communication
    window.depth_panel.zero_offset = 2.0
    window._update_data()
    assert window.controllers["depth"]._latest_depth == 40.0
    window.communication = None
    window.close()


if __name__ == "__main__":
    test_pid_math_exposes_all_three_terms()
    test_parameter_lock_and_middle_position_controls()
    test_depth_pid_and_keyboard_motion_work_together()
    test_pid_output_direction_can_be_reversed()
    test_sensor_timeout_returns_pectoral_to_middle()
    test_pid_off_restores_manual_qe_control()
    test_dual_main_window_exposes_depth_controller()
    print("depth controller tests passed")
