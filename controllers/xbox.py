#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Windows Xbox 手柄输入、连续控制模型和地面站控制面板。"""

from dataclasses import dataclass
import ctypes
import json
import math
import os
import sys
import time
from ctypes import wintypes

from PyQt5.QtCore import QTimer, pyqtSignal, Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from communication.base import ControlCommand
from config import CONTROL_LIMITS, XBOX_CONTROL_DEFAULTS
from controllers.base import ControllerBase


PARAMS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "xbox_params.json",
)

XINPUT_GAMEPAD_A = 0x1000
XINPUT_GAMEPAD_B = 0x2000
XINPUT_GAMEPAD_X = 0x4000
XINPUT_GAMEPAD_Y = 0x8000


class _XInputGamepad(ctypes.Structure):
    """与 Windows XINPUT_GAMEPAD 二进制布局一致的结构体。"""

    _fields_ = [
        ("wButtons", wintypes.WORD),
        # ctypes.wintypes.BYTE 在当前 Python 环境中是有符号 c_byte，
        # 128～255 会被读成 -128～-1。XInput 规范中的扳机是无符号 BYTE。
        ("bLeftTrigger", ctypes.c_ubyte),
        ("bRightTrigger", ctypes.c_ubyte),
        ("sThumbLX", ctypes.c_short),
        ("sThumbLY", ctypes.c_short),
        ("sThumbRX", ctypes.c_short),
        ("sThumbRY", ctypes.c_short),
    ]


class _XInputState(ctypes.Structure):
    """与 Windows XINPUT_STATE 二进制布局一致的结构体。"""

    _fields_ = [
        ("dwPacketNumber", wintypes.DWORD),
        ("Gamepad", _XInputGamepad),
    ]


class _XInputVibration(ctypes.Structure):
    """与 Windows XINPUT_VIBRATION 二进制布局一致的结构体。"""

    _fields_ = [
        ("wLeftMotorSpeed", wintypes.WORD),
        ("wRightMotorSpeed", wintypes.WORD),
    ]


@dataclass(frozen=True)
class XboxInputState:
    """一次标准化后的 Xbox 手柄采样。"""

    connected: bool = False
    controller_index: int = -1
    left_x: float = 0.0
    left_y: float = 0.0
    left_trigger: float = 0.0
    right_trigger: float = 0.0
    buttons: int = 0

    def button_pressed(self, mask):
        """判断给定 XInput 按键掩码当前是否按下。"""
        return bool(self.buttons & mask)


@dataclass(frozen=True)
class XboxControlOutput:
    """连续控制模型输出，数值单位与 ControlCommand 一致。"""

    tail_frequency: float
    tail_amplitude: float
    tail_offset: float
    tail_phase_diff: float
    pec_pwm: int
    steering: float
    effective_lt: float
    drive_envelope: float
    motion_text: str


class XInputBackend:
    """使用 Windows 原生 XInput DLL 读取最多四只 Xbox 手柄。"""

    def __init__(self):
        """按系统推荐顺序加载可用的 XInput DLL。"""
        self._get_state = None
        self._set_state = None
        self.dll_name = ""
        if sys.platform != "win32" or not hasattr(ctypes, "WinDLL"):
            return
        for dll_name in ("xinput1_4.dll", "xinput1_3.dll", "xinput9_1_0.dll"):
            try:
                library = ctypes.WinDLL(dll_name)
                get_state = library.XInputGetState
                get_state.argtypes = [wintypes.DWORD, ctypes.POINTER(_XInputState)]
                get_state.restype = wintypes.DWORD
                self._get_state = get_state
                try:
                    set_state = library.XInputSetState
                    set_state.argtypes = [
                        wintypes.DWORD,
                        ctypes.POINTER(_XInputVibration),
                    ]
                    set_state.restype = wintypes.DWORD
                    self._set_state = set_state
                except AttributeError:
                    self._set_state = None
                self.dll_name = dll_name
                break
            except (OSError, AttributeError):
                continue

    @property
    def available(self):
        """返回当前平台是否成功加载 XInput。"""
        return self._get_state is not None

    @staticmethod
    def _normalize_thumb(value):
        """把有符号 16 位摇杆值无偏地归一化到 -1～1。"""
        denominator = 32767.0 if value >= 0 else 32768.0
        return max(-1.0, min(float(value) / denominator, 1.0))

    def poll(self):
        """返回编号最小的已连接手柄状态，没有设备时返回断开状态。"""
        if self._get_state is None:
            return XboxInputState()
        for index in range(4):
            raw = _XInputState()
            if self._get_state(index, ctypes.byref(raw)) == 0:
                gamepad = raw.Gamepad
                return XboxInputState(
                    connected=True,
                    controller_index=index,
                    left_x=self._normalize_thumb(gamepad.sThumbLX),
                    left_y=self._normalize_thumb(gamepad.sThumbLY),
                    left_trigger=float(gamepad.bLeftTrigger) / 255.0,
                    right_trigger=float(gamepad.bRightTrigger) / 255.0,
                    buttons=int(gamepad.wButtons),
                )
        return XboxInputState()

    def set_vibration(self, controller_index, left_motor, right_motor):
        """设置两只震动电机的 0～1 强度，调用失败时安全返回 False。"""
        if self._set_state is None or controller_index < 0:
            return False
        left_motor = max(0.0, min(float(left_motor), 1.0))
        right_motor = max(0.0, min(float(right_motor), 1.0))
        vibration = _XInputVibration(
            int(round(left_motor * 65535.0)),
            int(round(right_motor * 65535.0)),
        )
        return self._set_state(
            controller_index, ctypes.byref(vibration)
        ) == 0


class XboxControlModel:
    """将手柄状态转换为安全、连续的尾鳍和胸鳍控制量。"""

    def __init__(self, parameters=None):
        """创建模型并从安全静止状态开始。"""
        self.parameters = dict(XBOX_CONTROL_DEFAULTS)
        if parameters:
            self.parameters.update(parameters)
        self._drive_envelope = 0.0
        self._drive_target = 0.0
        self._drive_rate = 0.0
        self._effective_lt = 0.0
        self._tail_offset = float(self.parameters["base_bias"])
        self._pec_pwm = float(self.parameters["pec_neutral_pwm"])
        self._last_output = self._stopped_output()

    @staticmethod
    def _clamp(value, minimum, maximum):
        """把浮点值限制在闭区间。"""
        return max(float(minimum), min(float(value), float(maximum)))

    @staticmethod
    def _move_toward(current, target, maximum_delta):
        """以有限变化率让 current 靠近 target。"""
        if current < target:
            return min(target, current + maximum_delta)
        return max(target, current - maximum_delta)

    @staticmethod
    def _smoothstep(value):
        """使用首尾斜率为零的三次曲线柔化启停包络。"""
        value = max(0.0, min(float(value), 1.0))
        return value * value * (3.0 - 2.0 * value)

    def configure(self, parameters):
        """替换已校验参数，并保持当前胸鳍值在新范围内。"""
        self.parameters = dict(parameters)
        self._pec_pwm = self._clamp(
            self._pec_pwm,
            self.parameters["pec_minimum_pwm"],
            self.parameters["pec_maximum_pwm"],
        )
        self.reset_tail()

    def set_pectoral_pwm(self, pulse_width):
        """设置胸鳍指令并按当前配置限幅。"""
        self._pec_pwm = self._clamp(
            pulse_width,
            self.parameters["pec_minimum_pwm"],
            self.parameters["pec_maximum_pwm"],
        )

    def reset_tail(self):
        """立即把内部尾鳍状态复位为静止，不改变胸鳍位置。"""
        self._drive_envelope = 0.0
        self._drive_target = 0.0
        self._drive_rate = 0.0
        self._effective_lt = 0.0
        self._tail_offset = float(self.parameters["base_bias"])
        self._last_output = self._stopped_output()

    def _stopped_output(self):
        """生成保持胸鳍位置和基础偏置的静止输出。"""
        return XboxControlOutput(
            tail_frequency=0.0,
            tail_amplitude=0.0,
            tail_offset=float(self.parameters["base_bias"]),
            tail_phase_diff=float(self.parameters["tail_phase_diff"]),
            pec_pwm=int(round(self._pec_pwm)),
            steering=0.0,
            effective_lt=0.0,
            drive_envelope=0.0,
            motion_text="停止",
        )

    def immediate_stop(self):
        """不经过平滑过程立即停止尾鳍，并保持胸鳍当前位置。"""
        self.reset_tail()
        return self._last_output

    def _stick_zone(self, state):
        """把左摇杆明确划分为中心、前半圆和后半圆三种状态。"""
        radius = math.hypot(state.left_x, state.left_y)
        deadzone = float(self.parameters["stick_deadzone"])
        if radius <= deadzone:
            return "center", 0.0
        if state.left_y < 0.0:
            return "rear", 0.0
        angle = math.atan2(state.left_x, max(0.0, state.left_y))
        steering = self._clamp(angle / (math.pi / 2.0), -1.0, 1.0)
        return "front", steering

    def _trigger_value(self, raw_value, deadzone):
        """移除扳机静止噪声后重新映射到 0～1。"""
        raw_value = self._clamp(raw_value, 0.0, 1.0)
        deadzone = self._clamp(deadzone, 0.0, 0.95)
        if raw_value <= deadzone:
            return 0.0
        return (raw_value - deadzone) / (1.0 - deadzone)

    def _start_drive_transition(self, target, reference_frequency):
        """按给定频率换算两个摆动周期对应的包络变化率。"""
        self._drive_target = float(target)
        cycles = max(0.1, float(self.parameters["ramp_cycles"]))
        reference_frequency = max(0.1, float(reference_frequency))
        self._drive_rate = reference_frequency / cycles

    def _update_pectoral(self, state, dt, trigger_deadzone):
        """独立推进胸鳍，确保左摇杆后半圆保持不影响 Y/A/RT。"""
        y_pressed = state.button_pressed(XINPUT_GAMEPAD_Y)
        a_pressed = state.button_pressed(XINPUT_GAMEPAD_A)
        if y_pressed == a_pressed:
            return
        rt = self._trigger_value(state.right_trigger, trigger_deadzone)
        rate = (
            float(self.parameters["pec_normal_rate"])
            + rt
            * (float(self.parameters["pec_fast_rate"])
               - float(self.parameters["pec_normal_rate"]))
        )
        direction = 1.0 if y_pressed else -1.0
        self._pec_pwm = self._clamp(
            self._pec_pwm + direction * rate * dt,
            self.parameters["pec_minimum_pwm"],
            self.parameters["pec_maximum_pwm"],
        )

    def _update_tail_offset(self, target_offset, reference_frequency, dt):
        """限制偏置变化率，使最大左到最大右恰好用两个尾摆周期。"""
        turn_range = float(self.parameters["maximum_turn_bias"])
        base_bias = float(self.parameters["base_bias"])
        if turn_range <= 0.0:
            self._tail_offset = base_bias
            return self._tail_offset
        cycles = max(0.1, float(self.parameters["ramp_cycles"]))
        reference_frequency = max(0.1, float(reference_frequency))
        full_span = 2.0 * turn_range
        maximum_delta = full_span * reference_frequency / cycles * dt
        minimum = base_bias - turn_range
        maximum = base_bias + turn_range
        target_offset = self._clamp(target_offset, minimum, maximum)
        self._tail_offset = self._move_toward(
            self._tail_offset, target_offset, maximum_delta
        )
        return self._tail_offset

    def update(self, state, dt):
        """推进一个控制周期并返回新的连续控制输出。"""
        dt = self._clamp(dt, 0.0, 0.2)
        stick_zone, steering = self._stick_zone(state)
        trigger_deadzone = float(self.parameters["trigger_deadzone"])
        requested_lt = self._trigger_value(state.left_trigger, trigger_deadzone)
        self._update_pectoral(state, dt, trigger_deadzone)

        # 后半圆是保持区而不是停止区。只更新独立的胸鳍指令，尾鳍的
        # 频率、摆幅、偏置、LT 包络和正在进行的启停进度全部冻结。
        if stick_zone == "rear":
            self._last_output = XboxControlOutput(
                tail_frequency=self._last_output.tail_frequency,
                tail_amplitude=self._last_output.tail_amplitude,
                tail_offset=self._last_output.tail_offset,
                tail_phase_diff=self._last_output.tail_phase_diff,
                pec_pwm=int(round(self._pec_pwm)),
                steering=self._last_output.steering,
                effective_lt=self._last_output.effective_lt,
                drive_envelope=self._last_output.drive_envelope,
                motion_text="后半圆保持",
            )
            return self._last_output

        requested_frequency = (
            float(self.parameters["normal_frequency"])
            + requested_lt
            * (float(self.parameters["boost_frequency"])
               - float(self.parameters["normal_frequency"]))
        )
        if stick_zone == "front" and self._drive_target == 0.0:
            self._start_drive_transition(1.0, requested_frequency)
        elif stick_zone == "center" and self._drive_target == 1.0:
            reference = max(
                self._last_output.tail_frequency,
                float(self.parameters["normal_frequency"]),
            )
            self._start_drive_transition(0.0, reference)

        self._drive_envelope = self._move_toward(
            self._drive_envelope,
            self._drive_target,
            self._drive_rate * dt,
        )

        lt_reference_frequency = max(
            requested_frequency,
            self._last_output.tail_frequency,
            0.1,
        )
        lt_rate = lt_reference_frequency / max(
            0.1, float(self.parameters["ramp_cycles"])
        )
        lt_target = requested_lt if stick_zone == "front" else 0.0
        self._effective_lt = self._move_toward(
            self._effective_lt, lt_target, lt_rate * dt
        )

        drive = self._smoothstep(self._drive_envelope)
        profile_frequency = (
            float(self.parameters["normal_frequency"])
            + self._effective_lt
            * (float(self.parameters["boost_frequency"])
               - float(self.parameters["normal_frequency"]))
        )
        profile_amplitude = (
            float(self.parameters["normal_amplitude"])
            + self._effective_lt
            * (float(self.parameters["boost_amplitude"])
               - float(self.parameters["normal_amplitude"]))
        )

        active_steering = steering if stick_zone == "front" else 0.0
        base_bias = float(self.parameters["base_bias"])
        target_offset = (
            base_bias
            + drive * active_steering * float(self.parameters["maximum_turn_bias"])
        )
        offset_reference_frequency = max(
            drive * profile_frequency,
            self._last_output.tail_frequency,
            float(self.parameters["normal_frequency"]),
        )
        tail_offset = self._update_tail_offset(
            target_offset, offset_reference_frequency, dt
        )

        if drive <= 0.0:
            motion_text = "停止"
            active_steering = 0.0
        elif self._drive_target == 0.0:
            motion_text = "平滑停止"
        elif self._drive_envelope < 1.0:
            motion_text = "平滑启动"
        elif self._effective_lt > 0.01:
            motion_text = "LT 加速游动"
        else:
            motion_text = "普通游动"

        self._last_output = XboxControlOutput(
            tail_frequency=drive * profile_frequency,
            tail_amplitude=drive * profile_amplitude,
            tail_offset=tail_offset,
            tail_phase_diff=float(self.parameters["tail_phase_diff"]),
            pec_pwm=int(round(self._pec_pwm)),
            steering=active_steering,
            effective_lt=self._effective_lt,
            drive_envelope=self._drive_envelope,
            motion_text=motion_text,
        )
        return self._last_output


class XboxController(ControllerBase):
    """轮询 Xbox 手柄、维护连续控制模型并提供专用 Qt 参数面板。"""

    emergency_stop_requested = pyqtSignal(str)

    def __init__(self, backend=None, time_source=None):
        """创建控制器；backend 可在测试中注入。"""
        super().__init__()
        self._backend = backend or XInputBackend()
        self._time_source = time_source or time.monotonic
        self._parameters = self._load_saved_parameters()
        self._model = XboxControlModel(self._parameters)
        self._pec_angle = int(self._parameters["pec_neutral_pwm"])
        self._control_widget = None
        self._last_poll_time = self._time_source()
        self._last_input = XboxInputState()
        self._last_connected = False
        self._previous_buttons = 0
        self._emergency_latched = False
        self._last_sent_command = None
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(20)
        self._poll_timer.timeout.connect(self._poll_controller)
        self._poll_timer.start()
        self._vibration_controller_index = -1
        self._vibration_timer = QTimer(self)
        self._vibration_timer.setSingleShot(True)
        self._vibration_timer.setInterval(250)
        self._vibration_timer.timeout.connect(self._stop_vibration)

    def activate(self):
        """仅在检测到 Xbox 手柄时激活控制器。"""
        state = self._backend.poll()
        self._last_input = state
        self._update_connection_state(state)
        if not state.connected:
            self.status_changed.emit("未检测到 Xbox 手柄，控制未启用")
            return False
        self._model.reset_tail()
        self._active = True
        self._emergency_latched = False
        self._previous_buttons = 0
        self._last_sent_command = None
        self._last_poll_time = self._time_source()
        self.status_changed.emit(
            f"Xbox 控制已激活（手柄 {state.controller_index + 1}）"
        )
        return True

    def deactivate(self):
        """停用控制器并复位内部尾鳍状态，胸鳍保持最后指令。"""
        self._active = False
        self._model.reset_tail()
        self._previous_buttons = 0
        self._last_sent_command = None
        self._refresh_status_labels(self._last_input, self._model.immediate_stop())
        self.status_changed.emit("Xbox 控制已停用")
        return True

    def get_control_widget(self):
        """按需创建并返回 Xbox 控制面板。"""
        if self._control_widget is None:
            self._control_widget = self._create_control_widget()
        return self._control_widget

    def get_base_bias(self):
        """返回停止命令应保持的尾鳍基础偏置。"""
        return float(self._parameters["base_bias"])

    def get_pectoral_pwm(self):
        """返回当前胸鳍指令脉宽。"""
        return int(self._pec_angle)

    def _load_saved_parameters(self):
        """读取持久化参数，缺失或损坏时使用安全默认值。"""
        parameters = dict(XBOX_CONTROL_DEFAULTS)
        try:
            with open(PARAMS_FILE, "r", encoding="utf-8") as file:
                saved = json.load(file)
            for key in parameters:
                if key in saved:
                    parameters[key] = float(saved[key])
        except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
            pass
        return self._sanitize_parameters(parameters)

    def _save_parameters(self):
        """以 UTF-8 保存当前 Xbox 参数。"""
        try:
            with open(PARAMS_FILE, "w", encoding="utf-8") as file:
                json.dump(self._parameters, file, ensure_ascii=False, indent=2)
        except OSError as error:
            self.status_changed.emit(f"Xbox 参数保存失败: {error}")

    @staticmethod
    def _sanitize_parameters(parameters):
        """在控制器层对所有外部参数做最终限幅。"""
        result = dict(parameters)
        result["stick_deadzone"] = max(
            0.0, min(float(result["stick_deadzone"]), 0.5)
        )
        result["trigger_deadzone"] = max(
            0.0, min(float(result["trigger_deadzone"]), 0.5)
        )
        for key in ("normal_frequency", "boost_frequency"):
            result[key] = max(
                CONTROL_LIMITS["tail_frequency"]["min"],
                min(float(result[key]), CONTROL_LIMITS["tail_frequency"]["max"]),
            )
        for key in ("normal_amplitude", "boost_amplitude"):
            result[key] = max(
                CONTROL_LIMITS["tail_amplitude"]["min"],
                min(float(result[key]), CONTROL_LIMITS["tail_amplitude"]["max"]),
            )
        result["maximum_turn_bias"] = max(
            0.0,
            min(
                float(result["maximum_turn_bias"]),
                CONTROL_LIMITS["tail_offset"]["max"],
            ),
        )
        result["base_bias"] = max(
            CONTROL_LIMITS["tail_offset"]["min"],
            min(float(result["base_bias"]), CONTROL_LIMITS["tail_offset"]["max"]),
        )
        result["tail_phase_diff"] = max(
            -6.282, min(float(result["tail_phase_diff"]), 6.282)
        )
        result["ramp_cycles"] = 2.0
        for key in ("pec_minimum_pwm", "pec_neutral_pwm", "pec_maximum_pwm"):
            result[key] = int(
                max(
                    CONTROL_LIMITS["pec_angle"]["min"],
                    min(float(result[key]), CONTROL_LIMITS["pec_angle"]["max"]),
                )
            )
        result["pec_normal_rate"] = max(
            1.0, min(float(result["pec_normal_rate"]), 2000.0)
        )
        result["pec_fast_rate"] = max(
            1.0, min(float(result["pec_fast_rate"]), 4000.0)
        )
        return result

    def _create_control_widget(self):
        """创建按键说明、可调参数和实时状态三个区域。"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)

        title = QLabel("Xbox 控制")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(QFont("Arial", 16, QFont.Bold))
        layout.addWidget(title)

        mapping_group = QGroupBox("控制映射")
        mapping_layout = QGridLayout(mapping_group)
        mappings = [
            ("左摇杆前半圆", "游动/连续转向"),
            ("左摇杆后半圆", "保持进入前的尾鳍状态"),
            ("LT", "连续加速"),
            ("Y / A", "胸鳍上升 / 下降"),
            ("Y/A + RT", "胸鳍快速调节"),
            ("X / B", "尾鳍立即停止 + 手柄短震"),
        ]
        for row, (button, action) in enumerate(mappings):
            mapping_layout.addWidget(QLabel(button), row, 0)
            mapping_layout.addWidget(QLabel(action), row, 1)
        layout.addWidget(mapping_group)

        parameter_group = QGroupBox("Xbox 控制参数")
        parameter_layout = QGridLayout(parameter_group)
        parameter_layout.setHorizontalSpacing(8)
        parameter_layout.setVerticalSpacing(6)
        self._parameter_inputs = {}

        def add_double(row, key, label, minimum, maximum, step, suffix, decimals=3):
            """向参数网格添加一个浮点输入框。"""
            parameter_layout.addWidget(QLabel(label), row, 0)
            spin = QDoubleSpinBox()
            spin.setRange(minimum, maximum)
            spin.setSingleStep(step)
            spin.setDecimals(decimals)
            spin.setValue(float(self._parameters[key]))
            spin.setSuffix(suffix)
            spin.setMinimumWidth(122)
            spin.setMaximumWidth(155)
            spin.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            self._parameter_inputs[key] = spin
            parameter_layout.addWidget(spin, row, 1)

        def add_integer(row, key, label, minimum, maximum, step, suffix):
            """向参数网格添加一个整数输入框。"""
            parameter_layout.addWidget(QLabel(label), row, 0)
            spin = QSpinBox()
            spin.setRange(minimum, maximum)
            spin.setSingleStep(step)
            spin.setValue(int(self._parameters[key]))
            spin.setSuffix(suffix)
            spin.setMinimumWidth(122)
            spin.setMaximumWidth(155)
            spin.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            self._parameter_inputs[key] = spin
            parameter_layout.addWidget(spin, row, 1)

        add_double(0, "normal_frequency", "LT 松开频率", 0.1, 4.0, 0.1, " Hz", 2)
        add_double(1, "normal_amplitude", "LT 松开摆幅", 0.0, 0.5, 0.01, " rad")
        add_double(2, "boost_frequency", "LT 全按频率", 0.1, 4.0, 0.1, " Hz", 2)
        add_double(3, "boost_amplitude", "LT 全按摆幅", 0.0, 0.5, 0.01, " rad")
        add_double(4, "maximum_turn_bias", "最大转向量", 0.0, 0.5, 0.01, " rad")
        add_double(5, "base_bias", "基础偏置", -0.5, 0.5, 0.01, " rad")
        add_double(6, "tail_phase_diff", "相位差", -6.282, 6.282, 0.1, " rad")
        add_double(7, "stick_deadzone", "摇杆死区", 0.0, 0.5, 0.01, "", 2)
        add_integer(8, "pec_minimum_pwm", "胸鳍最小值", 500, 2500, 10, " μs")
        add_integer(9, "pec_neutral_pwm", "胸鳍中位", 500, 2500, 10, " μs")
        add_integer(10, "pec_maximum_pwm", "胸鳍最大值", 500, 2500, 10, " μs")
        add_double(11, "pec_normal_rate", "胸鳍普通速度", 1.0, 2000.0, 10.0, " μs/s", 1)
        add_double(12, "pec_fast_rate", "胸鳍 RT 速度", 1.0, 4000.0, 10.0, " μs/s", 1)

        button_row = QHBoxLayout()
        apply_button = QPushButton("应用并保存")
        apply_button.clicked.connect(self._apply_parameters_from_widget)
        center_button = QPushButton("胸鳍回中")
        center_button.clicked.connect(self._center_pectoral)
        button_row.addWidget(apply_button)
        button_row.addWidget(center_button)
        parameter_layout.addLayout(button_row, 13, 0, 1, 2)
        layout.addWidget(parameter_group)

        status_group = QGroupBox("实时状态")
        status_layout = QVBoxLayout(status_group)
        self._connection_label = QLabel("手柄: 正在检测…")
        self._input_label = QLabel("方向: --  LT: 0%  RT: 0%")
        self._motion_label = QLabel("运动状态: 停止")
        self._tail_label = QLabel("尾鳍: 0.00 Hz / 0.000 rad / 0.000 rad")
        self._pec_label = QLabel("")
        for label in (
            self._connection_label,
            self._input_label,
            self._motion_label,
            self._tail_label,
            self._pec_label,
        ):
            status_layout.addWidget(label)
        layout.addWidget(status_group)
        layout.addStretch()
        self._refresh_status_labels(self._last_input, self._model._last_output)
        return widget

    def _apply_parameters_from_widget(self):
        """校验并应用界面参数；无效组合不会覆盖当前配置。"""
        values = dict(self._parameters)
        for key, control in self._parameter_inputs.items():
            values[key] = control.value()
        values = self._sanitize_parameters(values)
        if values["normal_frequency"] > values["boost_frequency"]:
            self.status_changed.emit("Xbox 参数错误：LT 全按频率不能低于松开频率")
            return False
        if values["normal_amplitude"] > values["boost_amplitude"]:
            self.status_changed.emit("Xbox 参数错误：LT 全按摆幅不能低于松开摆幅")
            return False
        if not (
            values["pec_minimum_pwm"]
            <= values["pec_neutral_pwm"]
            <= values["pec_maximum_pwm"]
        ):
            self.status_changed.emit("Xbox 参数错误：胸鳍需满足最小值 ≤ 中位 ≤ 最大值")
            return False
        if values["pec_normal_rate"] > values["pec_fast_rate"]:
            self.status_changed.emit("Xbox 参数错误：RT 速度不能低于普通速度")
            return False
        self._parameters = values
        self._model.configure(values)
        self._pec_angle = self._model._last_output.pec_pwm
        self._last_sent_command = None
        self._save_parameters()
        self.status_changed.emit("Xbox 控制参数已应用并保存")
        return True

    def _center_pectoral(self):
        """把胸鳍指令设为当前配置的中位值。"""
        self._model.set_pectoral_pwm(self._parameters["pec_neutral_pwm"])
        self._pec_angle = int(self._parameters["pec_neutral_pwm"])
        self._last_sent_command = None
        if self._active:
            output = self._model.update(self._last_input, 0.0)
            self._emit_output(output, force=True)
        self._refresh_status_labels(self._last_input, self._model._last_output)
        self.status_changed.emit(f"胸鳍已回中：{self._pec_angle} μs")

    def _update_connection_state(self, state):
        """仅在连接状态变化时报告，避免轮询日志刷屏。"""
        if state.connected != self._last_connected:
            self._last_connected = state.connected
            if state.connected:
                self.status_changed.emit(
                    f"检测到 Xbox 手柄 {state.controller_index + 1}"
                )
            else:
                self.status_changed.emit("Xbox 手柄已断开")

    def _pulse_emergency_vibration(self, controller_index):
        """让触发紧停的手柄双电机短震 250 ms，不阻塞控制循环。"""
        set_vibration = getattr(self._backend, "set_vibration", None)
        if not callable(set_vibration):
            return False
        if not set_vibration(controller_index, 0.75, 1.0):
            return False
        self._vibration_controller_index = controller_index
        self._vibration_timer.start()
        return True

    def _stop_vibration(self):
        """停止最近一次紧停提示震动。"""
        controller_index = self._vibration_controller_index
        self._vibration_controller_index = -1
        set_vibration = getattr(self._backend, "set_vibration", None)
        if controller_index >= 0 and callable(set_vibration):
            set_vibration(controller_index, 0.0, 0.0)

    def _poll_controller(self):
        """以 50 Hz 轮询手柄并在激活时推进控制模型。"""
        now = self._time_source()
        dt = max(0.0, min(now - self._last_poll_time, 0.2))
        self._last_poll_time = now
        state = self._backend.poll()
        was_connected = self._last_input.connected
        self._last_input = state
        self._update_connection_state(state)

        if self._active and was_connected and not state.connected:
            self._emergency_latched = True
            output = self._model.immediate_stop()
            self._emit_output(output, force=True)
            self.emergency_stop_requested.emit("Xbox 手柄断开，尾鳍已立即停止")
            self._refresh_status_labels(state, output)
            return

        if not self._active or not state.connected:
            self._previous_buttons = state.buttons
            self._refresh_status_labels(state, self._model._last_output)
            return

        if self._emergency_latched:
            self._refresh_status_labels(state, self._model._last_output)
            return

        newly_pressed = state.buttons & ~self._previous_buttons
        self._previous_buttons = state.buttons
        if newly_pressed & (XINPUT_GAMEPAD_X | XINPUT_GAMEPAD_B):
            self._emergency_latched = True
            output = self._model.immediate_stop()
            self._emit_output(output, force=True)
            self._pulse_emergency_vibration(state.controller_index)
            self.emergency_stop_requested.emit(
                "X/B 紧急停止：尾鳍已立即停止，手柄短震提示"
            )
            self._refresh_status_labels(state, output)
            return

        output = self._model.update(state, dt)
        self._emit_output(output)
        self._refresh_status_labels(state, output)

    def _emit_output(self, output, force=False):
        """将模型输出转换为 ControlCommand，并按变化去重后发出。"""
        self._pec_angle = int(output.pec_pwm)
        command_key = (
            round(output.tail_frequency, 3),
            round(output.tail_amplitude, 4),
            round(output.tail_offset, 4),
            round(output.tail_phase_diff, 4),
            int(output.pec_pwm),
        )
        if not force and command_key == self._last_sent_command:
            return
        self._last_sent_command = command_key
        command = ControlCommand(
            freq=output.tail_frequency,
            amp=output.tail_amplitude,
            offset=output.tail_offset,
        )
        command.tail_phase_diff = output.tail_phase_diff
        command.pec_angle = output.pec_pwm
        command.timestamp = time.time()
        self._current_command = command
        self.control_command_generated.emit(command)

    @staticmethod
    def _estimated_pectoral_angle(pulse_width):
        """按硬件完整 500～2500 μs 行程估算 0～180° 指令角。"""
        minimum = float(CONTROL_LIMITS["pec_angle"]["min"])
        maximum = float(CONTROL_LIMITS["pec_angle"]["max"])
        pulse_width = max(minimum, min(float(pulse_width), maximum))
        return 180.0 * (pulse_width - minimum) / (maximum - minimum)

    def _refresh_status_labels(self, state, output):
        """刷新连接、输入、尾鳍和胸鳍指令状态。"""
        if not hasattr(self, "_connection_label"):
            return
        if state.connected:
            self._connection_label.setText(
                f"手柄: 已连接（编号 {state.controller_index + 1}）"
            )
        elif getattr(self._backend, "available", True):
            self._connection_label.setText("手柄: 未连接")
        else:
            self._connection_label.setText("手柄: 当前系统无可用 XInput")

        stick_zone, steering = self._model._stick_zone(state)
        if stick_zone == "front":
            direction_text = f"{steering * 100:+.0f}%"
        elif stick_zone == "rear":
            direction_text = "后半圆保持"
        else:
            direction_text = "中心/停止"
        self._input_label.setText(
            f"方向: {direction_text}  LT: {state.left_trigger * 100:.0f}%  "
            f"RT: {state.right_trigger * 100:.0f}%"
        )
        self._motion_label.setText(f"运动状态: {output.motion_text}")
        self._tail_label.setText(
            f"尾鳍: {output.tail_frequency:.2f} Hz / "
            f"{output.tail_amplitude:.3f} rad / {output.tail_offset:.3f} rad"
        )
        angle = self._estimated_pectoral_angle(output.pec_pwm)
        self._pec_label.setText(
            f"胸鳍指令: {output.pec_pwm} μs / {angle:.1f}°（估算）"
        )
