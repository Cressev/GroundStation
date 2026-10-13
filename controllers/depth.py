#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""地面站深度 PID 控制器，保留键盘推进与转向控制。"""

import json
import math
import time
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox,
                             QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                             QPushButton, QSpinBox, QVBoxLayout)

from config import CONTROL_LIMITS, DEPTH_CONTROL_DEFAULTS
from controllers.base import KeyboardController


DEFAULT_PARAMS_PATH = Path(__file__).resolve().parent.parent / "depth_pid_params.json"


def clamp(value, minimum, maximum):
    """把数值限制到闭区间。"""
    return max(minimum, min(value, maximum))


class PID:
    """带积分限幅的离散 PID，并暴露每个分量供界面显示。"""

    def __init__(self, kp=0.0, ki=0.0, kd=0.0, integral_limit=1000.0):
        """初始化增益和积分限幅。"""
        self.configure(kp, ki, kd, integral_limit)
        self.reset()

    def configure(self, kp, ki, kd, integral_limit):
        """更新控制器参数，不隐式改变内部状态。"""
        self.kp = float(kp)
        self.ki = float(ki)
        self.kd = float(kd)
        self.integral_limit = max(0.0, float(integral_limit))

    def reset(self):
        """清空积分、历史误差和最近一次分量。"""
        self.integral = 0.0
        self.previous_error = None
        self.terms = (0.0, 0.0, 0.0)

    def update(self, error, dt):
        """根据误差和时间间隔计算 PID 输出及 P/I/D 三个分量。"""
        if dt <= 0.0:
            raise ValueError("dt must be positive")
        self.integral = clamp(
            self.integral + float(error) * dt,
            -self.integral_limit,
            self.integral_limit)
        derivative = 0.0
        if self.previous_error is not None:
            derivative = (float(error) - self.previous_error) / dt
        self.previous_error = float(error)
        self.terms = (
            self.kp * float(error),
            self.ki * self.integral,
            self.kd * derivative,
        )
        return sum(self.terms)


class DepthController(KeyboardController):
    """以标定后融合深度做 PID，同时沿用键盘尾鳍控制。"""

    def __init__(self, time_source=None, params_path=None):
        """初始化深度采样缓存、PID 状态和参数持久化路径。"""
        super().__init__()
        self._time_source = time_source or time.monotonic
        self._params_path = Path(params_path) if params_path else DEFAULT_PARAMS_PATH
        self._depth_params = self._load_depth_parameters()
        self._pid = PID(
            self._depth_params["kp"],
            self._depth_params["ki"],
            self._depth_params["kd"],
            self._depth_params["integral_limit"])
        self._pid_enabled = False
        self._latest_depth = None
        self._latest_depth_arrival = None
        self._latest_sample_id = None
        self._depth_sequence = 0
        self._processed_depth_sequence = -1
        self._last_pid_time = None
        self._pid_status = "PID 已关闭"
        self._pid_terms = (0.0, 0.0, 0.0)
        self._pid_correction = 0.0
        self._pec_angle = int(self._depth_params["neutral_pwm"])

    def _load_depth_parameters(self):
        """加载已保存参数；文件缺失或损坏时使用安全默认值。"""
        params = dict(DEPTH_CONTROL_DEFAULTS)
        try:
            saved = json.loads(self._params_path.read_text(encoding="utf-8"))
            for key in params:
                if key in saved:
                    params[key] = saved[key]
        except (OSError, ValueError, TypeError):
            pass
        numeric_ranges = {
            "target_depth": (-500.0, 500.0),
            "kp": (0.0, 1000.0),
            "ki": (0.0, 1000.0),
            "kd": (0.0, 1000.0),
            "integral_limit": (0.0, 10000.0),
            "neutral_pwm": (500.0, 2500.0),
            "minimum_pwm": (500.0, 2500.0),
            "maximum_pwm": (500.0, 2500.0),
            "sensor_timeout": (0.2, 5.0),
        }
        for key, (minimum, maximum) in numeric_ranges.items():
            try:
                params[key] = clamp(float(params[key]), minimum, maximum)
            except (TypeError, ValueError):
                params[key] = DEPTH_CONTROL_DEFAULTS[key]
        try:
            params["direction"] = -1 if float(params["direction"]) < 0 else 1
        except (TypeError, ValueError):
            params["direction"] = DEPTH_CONTROL_DEFAULTS["direction"]
        if not (params["minimum_pwm"] <= params["neutral_pwm"] <=
                params["maximum_pwm"]):
            for key in ("minimum_pwm", "neutral_pwm", "maximum_pwm"):
                params[key] = DEPTH_CONTROL_DEFAULTS[key]
        for key in ("neutral_pwm", "minimum_pwm", "maximum_pwm"):
            params[key] = int(round(params[key]))
        return params

    def _save_depth_parameters(self):
        """用 UTF-8 保存当前深度控制参数。"""
        try:
            self._params_path.write_text(
                json.dumps(self._depth_params, ensure_ascii=False, indent=2),
                encoding="utf-8")
        except OSError as exc:
            self.status_changed.emit(f"深度控制参数保存失败: {exc}")

    def _create_keyboard_widget(self):
        """在键盘控制界面顶部加入完整深度 PID 参数和状态区域。"""
        widget = super()._create_keyboard_widget()
        layout = widget.layout()
        title = layout.itemAt(0).widget()
        title.setText("深度闭环 + 键盘控制")

        pid_group = QGroupBox("深度 PID 控制")
        pid_layout = QVBoxLayout(pid_group)
        switch_layout = QHBoxLayout()
        self._pid_enable_checkbox = QCheckBox("启用深度 PID")
        self._parameter_unlock_checkbox = QCheckBox("解锁参数调节")
        self._pid_enable_checkbox.toggled.connect(self.set_pid_enabled)
        self._parameter_unlock_checkbox.toggled.connect(
            self._set_parameter_widgets_enabled)
        switch_layout.addWidget(self._pid_enable_checkbox)
        switch_layout.addWidget(self._parameter_unlock_checkbox)
        pid_layout.addLayout(switch_layout)

        form = QFormLayout()
        self._target_depth_input = self._double_spin(-500.0, 500.0, 0.5, 1, " cm")
        self._kp_input = self._double_spin(0.0, 1000.0, 1.0, 2, "")
        self._ki_input = self._double_spin(0.0, 1000.0, 0.1, 3, "")
        self._kd_input = self._double_spin(0.0, 1000.0, 0.1, 3, "")
        self._integral_limit_input = self._double_spin(
            0.0, 10000.0, 10.0, 1, " cm·s")
        self._neutral_pwm_input = self._integer_spin(500, 2500, 10, " μs")
        self._minimum_pwm_input = self._integer_spin(500, 2500, 10, " μs")
        self._maximum_pwm_input = self._integer_spin(500, 2500, 10, " μs")
        self._sensor_timeout_input = self._double_spin(0.2, 5.0, 0.1, 1, " s")
        self._direction_input = QComboBox()
        self._direction_input.addItem("下潜时减小脉宽", -1)
        self._direction_input.addItem("下潜时增大脉宽", 1)

        form.addRow("目标深度", self._target_depth_input)
        form.addRow("Kp", self._kp_input)
        form.addRow("Ki", self._ki_input)
        form.addRow("Kd", self._kd_input)
        form.addRow("积分限幅", self._integral_limit_input)
        form.addRow("中位脉宽", self._neutral_pwm_input)
        form.addRow("最小脉宽", self._minimum_pwm_input)
        form.addRow("最大脉宽", self._maximum_pwm_input)
        form.addRow("数据超时", self._sensor_timeout_input)
        form.addRow("输出方向", self._direction_input)
        pid_layout.addLayout(form)

        self._pid_parameter_widgets = [
            self._target_depth_input, self._kp_input, self._ki_input,
            self._kd_input, self._integral_limit_input,
            self._neutral_pwm_input, self._minimum_pwm_input,
            self._maximum_pwm_input, self._sensor_timeout_input,
            self._direction_input,
        ]
        self._load_parameters_into_widget()

        self._apply_pid_button = QPushButton("应用并保存参数")
        self._apply_pid_button.clicked.connect(self._apply_depth_parameters)
        pid_layout.addWidget(self._apply_pid_button)
        self._set_parameter_widgets_enabled(False)
        layout.insertWidget(2, pid_group)

        status_group = QGroupBox("深度控制器状态")
        status_layout = QVBoxLayout(status_group)
        self._depth_status_label = QLabel("当前深度: -- cm")
        self._error_status_label = QLabel("误差: -- cm")
        self._terms_status_label = QLabel("P: 0.0  I: 0.0  D: 0.0 μs")
        self._output_status_label = QLabel(
            f"修正: 0.0 μs  胸鳍: {self._pec_angle} μs")
        self._pid_status_label = QLabel(self._pid_status)
        self._pid_status_label.setFont(QFont("Arial", 10, QFont.Bold))
        for label in (self._pid_status_label, self._depth_status_label,
                      self._error_status_label, self._terms_status_label,
                      self._output_status_label):
            status_layout.addWidget(label)
        layout.insertWidget(3, status_group)
        return widget

    def _double_spin(self, minimum, maximum, step, decimals, suffix):
        """创建统一样式的浮点参数输入框。"""
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setSingleStep(step)
        spin.setDecimals(decimals)
        spin.setSuffix(suffix)
        return spin

    def _integer_spin(self, minimum, maximum, step, suffix):
        """创建统一样式的整数参数输入框。"""
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setSingleStep(step)
        spin.setSuffix(suffix)
        return spin

    def _load_parameters_into_widget(self):
        """把当前参数填入界面控件。"""
        p = self._depth_params
        self._target_depth_input.setValue(float(p["target_depth"]))
        self._kp_input.setValue(float(p["kp"]))
        self._ki_input.setValue(float(p["ki"]))
        self._kd_input.setValue(float(p["kd"]))
        self._integral_limit_input.setValue(float(p["integral_limit"]))
        self._neutral_pwm_input.setValue(int(p["neutral_pwm"]))
        self._minimum_pwm_input.setValue(int(p["minimum_pwm"]))
        self._maximum_pwm_input.setValue(int(p["maximum_pwm"]))
        self._sensor_timeout_input.setValue(float(p["sensor_timeout"]))
        index = self._direction_input.findData(int(p["direction"]))
        self._direction_input.setCurrentIndex(max(0, index))

    def _set_parameter_widgets_enabled(self, enabled):
        """按参数解锁开关统一启用或置灰全部可调项。"""
        for control in getattr(self, "_pid_parameter_widgets", []):
            control.setEnabled(bool(enabled))
        if hasattr(self, "_apply_pid_button"):
            self._apply_pid_button.setEnabled(bool(enabled))

    def _apply_depth_parameters(self):
        """校验、应用并持久化界面中的全部深度控制参数。"""
        minimum = self._minimum_pwm_input.value()
        neutral = self._neutral_pwm_input.value()
        maximum = self._maximum_pwm_input.value()
        if not minimum <= neutral <= maximum:
            self._set_pid_status("参数错误：需满足最小脉宽 ≤ 中位 ≤ 最大脉宽")
            return False
        self._depth_params = {
            "target_depth": self._target_depth_input.value(),
            "kp": self._kp_input.value(),
            "ki": self._ki_input.value(),
            "kd": self._kd_input.value(),
            "integral_limit": self._integral_limit_input.value(),
            "neutral_pwm": neutral,
            "minimum_pwm": minimum,
            "maximum_pwm": maximum,
            "sensor_timeout": self._sensor_timeout_input.value(),
            "direction": int(self._direction_input.currentData()),
        }
        self._pid.configure(
            self._depth_params["kp"], self._depth_params["ki"],
            self._depth_params["kd"], self._depth_params["integral_limit"])
        self._reset_pid_state()
        self._pec_angle = int(neutral)
        self._last_sent_command = None
        self._save_depth_parameters()
        self._set_pid_status("参数已应用并保存")
        if self._active:
            self._update_control()
        return True

    def set_pid_enabled(self, enabled):
        """启停深度闭环；关闭时回中并恢复 Q/E 手动胸鳍控制。"""
        self._pid_enabled = bool(enabled)
        self._reset_pid_state()
        self._pec_angle = int(self._depth_params["neutral_pwm"])
        self._last_sent_command = None
        self._set_pid_status("等待新深度数据" if enabled else "PID 已关闭")
        if hasattr(self, "_pid_enable_checkbox"):
            self._pid_enable_checkbox.blockSignals(True)
            self._pid_enable_checkbox.setChecked(bool(enabled))
            self._pid_enable_checkbox.blockSignals(False)
        if self._active:
            self._update_control()

    def update_depth(self, depth_cm, sample_id=None):
        """接收一帧标定后融合深度；重复 sample_id 不重复推进 PID。"""
        try:
            depth = float(depth_cm)
        except (TypeError, ValueError):
            return False
        if not math.isfinite(depth):
            return False
        if sample_id is not None and sample_id == self._latest_sample_id:
            return False
        self._latest_depth = depth
        self._latest_depth_arrival = self._time_source()
        self._latest_sample_id = sample_id
        self._depth_sequence += 1
        self._refresh_pid_labels()
        return True

    def _reset_pid_state(self):
        """清空 PID 历史和采样处理标记。"""
        self._pid.reset()
        self._pid_terms = (0.0, 0.0, 0.0)
        self._pid_correction = 0.0
        self._last_pid_time = None
        self._processed_depth_sequence = -1

    def _update_pectoral_control(self):
        """PID 开启时接管胸鳍；关闭时沿用基类 Q/E 手动控制。"""
        if not self._pid_enabled:
            return super()._update_pectoral_control()

        neutral = int(self._depth_params["neutral_pwm"])
        now = self._time_source()
        if (self._latest_depth_arrival is None or
                now - self._latest_depth_arrival > self._depth_params["sensor_timeout"]):
            changed = self._pec_angle != neutral
            self._pec_angle = neutral
            if self._pid_status != "深度数据超时，胸鳍已回中":
                self._reset_pid_state()
                self._set_pid_status("深度数据超时，胸鳍已回中")
            self._refresh_pid_labels()
            return changed

        if self._processed_depth_sequence == self._depth_sequence:
            return False

        dt = 0.1 if self._last_pid_time is None else now - self._last_pid_time
        dt = clamp(dt, 0.001, 1.0)
        self._last_pid_time = now
        error = self._depth_params["target_depth"] - self._latest_depth
        pid_output = self._pid.update(error, dt)
        self._pid_terms = self._pid.terms
        self._pid_correction = self._depth_params["direction"] * pid_output
        output = clamp(
            neutral + self._pid_correction,
            int(self._depth_params["minimum_pwm"]),
            int(self._depth_params["maximum_pwm"]))
        changed = self._pec_angle != int(round(output))
        self._pec_angle = int(round(output))
        self._processed_depth_sequence = self._depth_sequence
        self._set_pid_status("PID 运行中")
        self._refresh_pid_labels(error)
        return changed

    def _set_pid_status(self, text):
        """更新状态文字，并只在状态发生变化时写入系统日志。"""
        changed = text != self._pid_status
        self._pid_status = text
        if hasattr(self, "_pid_status_label"):
            self._pid_status_label.setText(text)
        if changed:
            self.status_changed.emit(text)

    def _refresh_pid_labels(self, error=None):
        """刷新深度、误差、PID 分量和最终脉宽显示。"""
        if not hasattr(self, "_depth_status_label"):
            return
        depth_text = "--" if self._latest_depth is None else f"{self._latest_depth:.2f}"
        if error is None and self._latest_depth is not None:
            error = self._depth_params["target_depth"] - self._latest_depth
        error_text = "--" if error is None else f"{error:.2f}"
        p_term, i_term, d_term = self._pid_terms
        self._depth_status_label.setText(f"当前深度: {depth_text} cm")
        self._error_status_label.setText(f"误差: {error_text} cm")
        self._terms_status_label.setText(
            f"P: {p_term:.1f}  I: {i_term:.1f}  D: {d_term:.1f} μs")
        self._output_status_label.setText(
            f"修正: {self._pid_correction:.1f} μs  胸鳍: {self._pec_angle} μs")

    def deactivate(self):
        """切走深度控制器时关闭 PID，并在停用前生成回中命令。"""
        if self._pid_enabled:
            self.set_pid_enabled(False)
        return super().deactivate()
