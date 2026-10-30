#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
控制器基类和键盘控制器实现
Controller Base Class and Keyboard Controller Implementation
"""

from abc import ABC, abstractmethod
from PyQt5.QtCore import QObject, pyqtSignal, QTimer
from PyQt5.QtWidgets import QWidget
from typing import Dict, Any
import json
import math
import time

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from communication.base import ControlCommand
from config import KEYBOARD_MAPPING, CONTROL_LIMITS, KEYBOARD_CONTROL_DEFAULTS

# 控制参数持久化文件(项目根目录), 下次启动自动加载
PARAMS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "keyboard_params.json")

class ControllerBase(QObject):
    """控制器基类"""
    
    # 信号定义
    control_command_generated = pyqtSignal(ControlCommand)
    status_changed = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self._active = False
        self._current_command = ControlCommand()
        
    @property
    def active(self) -> bool:
        return self._active
        
    @abstractmethod
    def activate(self) -> bool:
        """激活控制器"""
        pass
        
    @abstractmethod
    def deactivate(self) -> bool:
        """停用控制器"""
        pass
        
    @abstractmethod
    def get_control_widget(self) -> QWidget:
        """获取控制界面组件"""
        pass
        
    def get_current_command(self) -> ControlCommand:
        """获取当前控制命令"""
        return self._current_command

class KeyboardController(ControllerBase):
    """键盘控制器"""
    
    def __init__(self, enable_kappa=True):
        super().__init__()
        self._enable_kappa = bool(enable_kappa)
        self._key_states = {}
        self._control_widget = None
        self._update_timer = QTimer()
        self._update_timer.timeout.connect(self._update_control)
        self._update_timer.setInterval(100)  # 10Hz

        self._keyboard_params = {}
        self.set_keyboard_parameters(**self._load_saved_parameters())

        # 运动状态（保持状态而非瞬时按键）
        self._motion_state = "stop"  # stop, slow_forward, slow_left, slow_right, fast_forward, fast_left, fast_right
        
        # 胸鳍脉宽控制 (500-2500 μs)
        self._pec_angle = CONTROL_LIMITS["pec_angle"]["default"]
        self._pec_angle_step = 10  # 每次增减10μs
        self._pectoral_override = None
        
        # 上次发送的命令，用于检测变化
        self._last_sent_command = None
        
    def activate(self) -> bool:
        """激活键盘控制"""
        try:
            self._active = True
            self._update_timer.start()
            self.status_changed.emit("键盘控制已激活")
            return True
        except Exception as e:
            self.status_changed.emit(f"键盘控制激活失败: {e}")
            return False
            
    def deactivate(self) -> bool:
        """停用键盘控制"""
        try:
            self._active = False
            self._update_timer.stop()
            self._key_states.clear()
            self._motion_state = "stop"
            self.status_changed.emit("键盘控制已停用")
            return True
        except Exception as e:
            self.status_changed.emit(f"键盘控制停用失败: {e}")
            return False
    
    def get_control_widget(self) -> QWidget:
        """获取键盘控制界面"""
        if self._control_widget is None:
            self._control_widget = self._create_keyboard_widget()
        return self._control_widget
    
    def _create_keyboard_widget(self) -> QWidget:
        """创建键盘控制界面"""
        from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, 
                                     QLabel, QGroupBox, QGridLayout,
                                     QPushButton,
                                     QSizePolicy)
        from ui.numeric_inputs import NoWheelDoubleSpinBox, NoWheelSpinBox
        from PyQt5.QtCore import Qt
        from PyQt5.QtGui import QFont
        
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)
        
        # 标题
        title = QLabel("键盘控制")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(QFont("Arial", 16, QFont.Bold))
        layout.addWidget(title)
        
        # 控制说明
        control_group = QGroupBox("控制按键说明")
        control_layout = QGridLayout(control_group)
        control_layout.setHorizontalSpacing(8)
        control_layout.setVerticalSpacing(4)
        
        mappings = [
            ("慢速前进", "w"),
            ("慢速左转", "a"),
            ("慢速右转", "d"),
            ("快速前进", "W (=Shift+w)"),
            ("快速左转", "A (=Shift+a)"),
            ("快速右转", "D (=Shift+d)"),
            ("停止/归中", "s / Space"),
            ("胸鳍+", "Q"),
            ("胸鳍-", "E"),
            ("切换绘图", "P"),
            ("清空数据", "C")
        ]
        
        for i, (action, key) in enumerate(mappings):
            row, col = i // 2, (i % 2) * 2
            control_layout.addWidget(QLabel(f"{action}:"), row, col)
            control_layout.addWidget(QLabel(f"[{key}]"), row, col + 1)
        
        layout.addWidget(control_group)

        # 参数输入
        input_group = QGroupBox("开环控制参数")
        input_layout = QGridLayout(input_group)
        input_layout.setHorizontalSpacing(8)
        input_layout.setVerticalSpacing(6)
        input_layout.setColumnStretch(0, 0)
        input_layout.setColumnStretch(1, 1)
        self._param_inputs = {}

        def add_spin(row, key, label, minimum, maximum, step, suffix):
            label_widget = QLabel(label)
            label_widget.setMinimumWidth(58)
            input_layout.addWidget(label_widget, row, 0)
            spin = NoWheelDoubleSpinBox()
            spin.setRange(minimum, maximum)
            spin.setSingleStep(step)
            spin.setDecimals(3)
            spin.setValue(self._keyboard_params[key])
            spin.setSuffix(suffix)
            spin.setMinimumWidth(112)
            spin.setMaximumWidth(140)
            spin.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            self._param_inputs[key] = spin
            input_layout.addWidget(spin, row, 1)

        add_spin(0, "base_bias", "基础偏置", CONTROL_LIMITS["tail_offset"]["min"],
                 CONTROL_LIMITS["tail_offset"]["max"], 0.01, " rad")
        add_spin(1, "slow_frequency", "慢频", CONTROL_LIMITS["tail_frequency"]["min"],
                 CONTROL_LIMITS["tail_frequency"]["max"], 0.1, " Hz")
        add_spin(2, "slow_amplitude", "慢幅", CONTROL_LIMITS["tail_amplitude"]["min"],
                 CONTROL_LIMITS["tail_amplitude"]["max"], 0.01, " rad")
        add_spin(3, "slow_turn_bias", "慢转", 0.0,
                 CONTROL_LIMITS["tail_offset"]["max"],
                 0.01, " rad")
        add_spin(4, "fast_frequency", "快频", CONTROL_LIMITS["tail_frequency"]["min"],
                 CONTROL_LIMITS["tail_frequency"]["max"], 0.1, " Hz")
        add_spin(5, "fast_amplitude", "快幅", CONTROL_LIMITS["tail_amplitude"]["min"],
                 CONTROL_LIMITS["tail_amplitude"]["max"], 0.01, " rad")
        add_spin(6, "fast_turn_bias", "快转", 0.0,
                 CONTROL_LIMITS["tail_offset"]["max"],
                 0.01, " rad")
        add_spin(7, "tail_phase_diff", "相位差", -6.282, 6.282,
                 0.1, " rad")
        if self._enable_kappa:
            add_spin(8, "tail_kappa", "去程占比 κ", 0.1, 0.9, 0.01, "")
            self._param_inputs["tail_kappa"].setToolTip(
                "最小角度到最大角度占完整周期的比例；0.5对称，低于0.5去程快、回程慢。")

        # 胸鳍脉宽直接设定：与 Q/E 增量调节共用同一个状态。
        input_layout.addWidget(QLabel("胸鳍脉宽"), 9, 0)
        pec_layout = QHBoxLayout()
        self._pec_pulse_input = NoWheelSpinBox()
        self._pec_pulse_input.setRange(
            int(CONTROL_LIMITS["pec_angle"]["min"]),
            int(CONTROL_LIMITS["pec_angle"]["max"]))
        self._pec_pulse_input.setSingleStep(10)
        self._pec_pulse_input.setValue(int(self._pec_angle))
        self._pec_pulse_input.setSuffix(" μs")
        self._pec_pulse_input.setMinimumWidth(112)
        self._pec_pulse_input.setMaximumWidth(140)
        set_pec_button = QPushButton("设定")
        self._set_pec_button = set_pec_button
        set_pec_button.clicked.connect(self._set_pec_from_widget)
        pec_layout.addWidget(self._pec_pulse_input)
        pec_layout.addWidget(set_pec_button)
        input_layout.addLayout(pec_layout, 9, 1)

        button_layout = QHBoxLayout()
        apply_button = QPushButton("应用参数")
        apply_button.clicked.connect(self._apply_parameters_from_widget)
        stop_button = QPushButton("停止/归中")
        stop_button.clicked.connect(self.stop_motion)
        button_layout.addWidget(apply_button)
        button_layout.addWidget(stop_button)
        input_layout.addLayout(button_layout, 10, 0, 1, 2)

        layout.addWidget(input_group)
        
        # 当前参数显示
        params_group = QGroupBox("当前控制参数")
        params_layout = QVBoxLayout(params_group)
        
        self._motion_label = QLabel(f"运动状态: 停止")
        self._freq_label = QLabel(f"摆尾频率: {self._current_command.tail_frequency:.2f} Hz")
        self._amp_label = QLabel(f"摆尾幅度: {self._current_command.tail_amplitude:.2f} rad")
        self._offset_label = QLabel(f"偏移角度: {self._current_command.tail_offset:.2f} rad")
        self._pec_label = QLabel(f"胸鳍脉宽: {self._pec_angle} μs")
        self._kappa_label = QLabel("去程占比 κ: 0.500（停止）")
        self._param_label = QLabel(self._format_parameter_summary())
        self._param_label.setWordWrap(True)
        
        params_layout.addWidget(self._motion_label)
        params_layout.addWidget(self._freq_label)
        params_layout.addWidget(self._amp_label)
        params_layout.addWidget(self._offset_label)
        params_layout.addWidget(self._pec_label)
        if self._enable_kappa:
            params_layout.addWidget(self._kappa_label)
        params_layout.addWidget(self._param_label)
        
        layout.addWidget(params_group)
        
        layout.addStretch()
        
        return widget

    def _clamp(self, value, minimum, maximum):
        return max(minimum, min(float(value), maximum))

    def _clamp_frequency(self, value):
        return self._clamp(
            value,
            CONTROL_LIMITS["tail_frequency"]["min"],
            CONTROL_LIMITS["tail_frequency"]["max"]
        )

    def _clamp_amplitude(self, value):
        return self._clamp(
            value,
            CONTROL_LIMITS["tail_amplitude"]["min"],
            CONTROL_LIMITS["tail_amplitude"]["max"]
        )

    def _clamp_offset(self, value):
        return self._clamp(
            value,
            CONTROL_LIMITS["tail_offset"]["min"],
            CONTROL_LIMITS["tail_offset"]["max"]
        )

    def set_keyboard_parameters(self, base_bias, slow_frequency, slow_amplitude,
                                slow_turn_bias, fast_frequency, fast_amplitude,
                                fast_turn_bias, tail_phase_diff=1.57, tail_kappa=0.5):
        """应用键盘开环控制参数，所有输入在控制器层再次限幅。"""
        # 转向量以基础偏置为中心, 单侧范围受tail_offset.max限制
        turn_max = CONTROL_LIMITS["tail_offset"]["max"]
        tail_kappa = float(tail_kappa)
        tail_kappa = self._clamp(tail_kappa, 0.1, 0.9) if math.isfinite(tail_kappa) else 0.5
        self._keyboard_params = {
            "base_bias": self._clamp_offset(base_bias),
            "slow_frequency": self._clamp_frequency(slow_frequency),
            "slow_amplitude": self._clamp_amplitude(slow_amplitude),
            "slow_turn_bias": self._clamp(slow_turn_bias, 0.0, turn_max),
            "fast_frequency": self._clamp_frequency(fast_frequency),
            "fast_amplitude": self._clamp_amplitude(fast_amplitude),
            "fast_turn_bias": self._clamp(fast_turn_bias, 0.0, turn_max),
            "tail_phase_diff": self._clamp(tail_phase_diff, -6.282, 6.282),
            "tail_kappa": tail_kappa,
        }
        if hasattr(self, "_param_label"):
            self._param_label.setText(self._format_parameter_summary())

    def _apply_parameters_from_widget(self):
        """从界面读取参数，点击应用后才生效。"""
        if not hasattr(self, "_param_inputs"):
            return
        self.set_keyboard_parameters(
            base_bias=self._param_inputs["base_bias"].value(),
            slow_frequency=self._param_inputs["slow_frequency"].value(),
            slow_amplitude=self._param_inputs["slow_amplitude"].value(),
            slow_turn_bias=self._param_inputs["slow_turn_bias"].value(),
            fast_frequency=self._param_inputs["fast_frequency"].value(),
            fast_amplitude=self._param_inputs["fast_amplitude"].value(),
            fast_turn_bias=self._param_inputs["fast_turn_bias"].value(),
            tail_phase_diff=self._param_inputs["tail_phase_diff"].value(),
            tail_kappa=(self._param_inputs["tail_kappa"].value() if self._enable_kappa
                        else self._keyboard_params["tail_kappa"]),
        )
        self._save_parameters()
        self._last_sent_command = None
        self._update_control()
        self.status_changed.emit("键盘控制参数已应用并保存")

    def set_pec_pulse(self, pulse_width):
        """设定胸鳍 PWM 脉宽并立即生成一条包含该值的控制命令。"""
        if self._pectoral_override is not None:
            self.status_changed.emit('胸鳍由深度控制占用，请先停止深度控制')
            return False
        minimum = int(CONTROL_LIMITS["pec_angle"]["min"])
        maximum = int(CONTROL_LIMITS["pec_angle"]["max"])
        self._pec_angle = max(minimum, min(int(pulse_width), maximum))
        if hasattr(self, "_pec_pulse_input"):
            self._pec_pulse_input.setValue(self._pec_angle)
        if hasattr(self, "_pec_label"):
            self._pec_label.setText(f"胸鳍脉宽: {self._pec_angle} μs")
        self._last_sent_command = None
        self._update_control()
        self.status_changed.emit(f"胸鳍脉宽已设定为 {self._pec_angle} μs")

    def set_pectoral_override(self, pulse_width):
        """Transfer pectoral ownership without emitting a complete stale tail command."""
        self._pectoral_override = pulse_width
        if pulse_width is not None:
            self._pec_angle = max(500, min(2500, int(pulse_width)))
            if hasattr(self, '_pec_pulse_input'):
                self._pec_pulse_input.setValue(self._pec_angle)
        for name in ('_pec_pulse_input', '_set_pec_button'):
            if hasattr(self, name):
                getattr(self, name).setEnabled(pulse_width is None)
        if hasattr(self, '_pec_label'):
            owner = '（深度控制）' if pulse_width is not None else ''
            self._pec_label.setText(f'胸鳍脉宽: {self._pec_angle} μs{owner}')

    def _set_pec_from_widget(self):
        """读取胸鳍脉宽输入框，并通过控制器现有信号链发送。"""
        self.set_pec_pulse(self._pec_pulse_input.value())

    def _format_parameter_summary(self):
        p = self._keyboard_params
        return (
            "参数: "
            f"base={p['base_bias']:.3f}, "
            f"慢速 f={p['slow_frequency']:.2f} A={p['slow_amplitude']:.3f} turn={p['slow_turn_bias']:.3f}, "
            f"快速 f={p['fast_frequency']:.2f} A={p['fast_amplitude']:.3f} turn={p['fast_turn_bias']:.3f}"
            + (f", κ={p['tail_kappa']:.3f}" if self._enable_kappa else "")
        )

    def get_base_bias(self):
        return self._keyboard_params["base_bias"]

    def _load_saved_parameters(self):
        """从keyboard_params.json加载上次保存的控制参数, 首次启动用默认值"""
        params = dict(KEYBOARD_CONTROL_DEFAULTS)
        try:
            with open(PARAMS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            for k in params:
                if k in saved:
                    params[k] = float(saved[k])
        except (FileNotFoundError, json.JSONDecodeError, ValueError):
            pass  # 文件不存在或损坏时使用默认参数
        return params

    def _save_parameters(self):
        """当前控制参数保存到keyboard_params.json, 下次启动自动加载"""
        try:
            with open(PARAMS_FILE, "w", encoding="utf-8") as f:
                json.dump(self._keyboard_params, f, ensure_ascii=False, indent=2)
        except OSError as e:
            self.status_changed.emit(f"控制参数保存失败: {e}")

    def stop_motion(self):
        self._motion_state = "stop"
        self._last_sent_command = None
        self._update_control()
    
    def handle_key_press(self, key: str):
        """处理按键按下 - 切换运动状态
        方向键用大小写区分快慢: 小写w/a/d=慢速, 大写W/A/D(Shift或大写锁产生)=快速
        """
        self._key_states[key] = True

        # 方向控制 - 按一次切换状态并保持
        if key == "w":
            self._motion_state = "slow_forward"
        elif key == "a":
            self._motion_state = "slow_left"
        elif key == "d":
            self._motion_state = "slow_right"
        elif key in ("W", "Shift+W"):
            self._motion_state = "fast_forward"
        elif key in ("A", "Shift+A"):
            self._motion_state = "fast_left"
        elif key in ("D", "Shift+D"):
            self._motion_state = "fast_right"
        elif key in (KEYBOARD_MAPPING["backward"], "s", "S", "Space"):
            self._motion_state = "stop"
        
    def handle_key_release(self, key: str):
        """处理按键释放"""
        self._key_states[key] = False

    def _update_pectoral_control(self) -> bool:
        """按 Q/E 更新胸鳍脉宽，返回本周期是否需要同步输入框。"""
        if self._pectoral_override is not None:
            self._pec_angle = int(self._pectoral_override)
            return False
        if self._key_states.get(KEYBOARD_MAPPING["increase_pec"], False):  # Q键
            self._pec_angle = min(
                self._pec_angle + self._pec_angle_step,
                CONTROL_LIMITS["pec_angle"]["max"]
            )
            return True
        if self._key_states.get(KEYBOARD_MAPPING["decrease_pec"], False):  # E键
            self._pec_angle = max(
                self._pec_angle - self._pec_angle_step,
                CONTROL_LIMITS["pec_angle"]["min"]
            )
            return True
        return False

    def _update_control(self):
        """更新控制命令"""
        if not self._active:
            return

        # Q/E 控制胸鳍脉宽（增量式，长按生效）。仅按键调节时才回写输入框，
        # 避免 100 ms 控制定时器覆盖用户尚未提交的手动输入。
        pec_adjusted_by_key = self._update_pectoral_control()
        
        # 基于运动状态设置参数
        p = self._keyboard_params
        motion_label_text = "停止"
        self._current_command.tail_phase_diff = p.get("tail_phase_diff", 1.57)
        self._current_command.tail_kappa = p.get("tail_kappa", 0.5) if self._enable_kappa else 0.5
        
        if self._motion_state == "stop":
            self._current_command.tail_frequency = 0.0
            self._current_command.tail_amplitude = 0.0
            self._current_command.tail_offset = p["base_bias"]
            motion_label_text = "停止"
        elif self._motion_state == "slow_forward":
            self._current_command.tail_frequency = p["slow_frequency"]
            self._current_command.tail_amplitude = p["slow_amplitude"]
            self._current_command.tail_offset = p["base_bias"]
            motion_label_text = "慢速前进"
        elif self._motion_state == "slow_left":
            self._current_command.tail_frequency = p["slow_frequency"]
            self._current_command.tail_amplitude = p["slow_amplitude"]
            self._current_command.tail_offset = p["base_bias"] - p["slow_turn_bias"]
            motion_label_text = "慢速左转"
        elif self._motion_state == "slow_right":
            self._current_command.tail_frequency = p["slow_frequency"]
            self._current_command.tail_amplitude = p["slow_amplitude"]
            self._current_command.tail_offset = p["base_bias"] + p["slow_turn_bias"]
            motion_label_text = "慢速右转"
        elif self._motion_state == "fast_forward":
            self._current_command.tail_frequency = p["fast_frequency"]
            self._current_command.tail_amplitude = p["fast_amplitude"]
            self._current_command.tail_offset = p["base_bias"]
            motion_label_text = "快速前进"
        elif self._motion_state == "fast_left":
            self._current_command.tail_frequency = p["fast_frequency"]
            self._current_command.tail_amplitude = p["fast_amplitude"]
            self._current_command.tail_offset = p["base_bias"] - p["fast_turn_bias"]
            motion_label_text = "快速左转"
        elif self._motion_state == "fast_right":
            self._current_command.tail_frequency = p["fast_frequency"]
            self._current_command.tail_amplitude = p["fast_amplitude"]
            self._current_command.tail_offset = p["base_bias"] + p["fast_turn_bias"]
            motion_label_text = "快速右转"
        
        # 偏置限幅: ±0.5的转向范围以基础偏置为中位, 而不是绝对零位
        # (舵机摆幅围绕偏置中心, 因此合成偏置允许越过绝对±0.5, 最大到±1.0)
        turn_range = CONTROL_LIMITS["tail_offset"]["max"]
        self._current_command.tail_offset = max(
            p["base_bias"] - turn_range,
            min(self._current_command.tail_offset, p["base_bias"] + turn_range)
        )
        self._current_command.timestamp = time.time()
        self._current_command.pec_angle = self._pec_angle
        
        # 更新界面显示
        if hasattr(self, '_motion_label'):
            self._motion_label.setText(f"运动状态: {motion_label_text}")
        if hasattr(self, '_freq_label'):
            self._freq_label.setText(f"摆尾频率: {self._current_command.tail_frequency:.2f} Hz")
            self._amp_label.setText(f"摆尾幅度: {self._current_command.tail_amplitude:.2f} rad")
            self._offset_label.setText(f"偏移角度: {self._current_command.tail_offset:.2f} rad")
            self._pec_label.setText(f"胸鳍脉宽: {self._pec_angle} μs")
            freq = self._current_command.tail_frequency
            kappa = self._current_command.tail_kappa
            timing = (f"去程 {kappa/freq:.3f} s / 回程 {(1-kappa)/freq:.3f} s"
                      if freq > 0 else "停止")
            self._kappa_label.setText(f"去程占比 κ: {kappa:.3f}（{timing}）")
        if (pec_adjusted_by_key and hasattr(self, '_pec_pulse_input') and
                self._pec_pulse_input.value() != self._pec_angle):
            self._pec_pulse_input.setValue(self._pec_angle)
        
        # 只在命令变化时发送（避免静止时持续发送）
        current_cmd_tuple = (
            round(self._current_command.tail_frequency, 2),
            round(self._current_command.tail_amplitude, 2), 
            round(self._current_command.tail_offset, 2),
            round(self._current_command.tail_phase_diff, 3),
            round(self._current_command.tail_kappa, 3),
            self._pec_angle
        )
        
        if self._last_sent_command != current_cmd_tuple:
            self._last_sent_command = current_cmd_tuple
            self.control_command_generated.emit(self._current_command)
