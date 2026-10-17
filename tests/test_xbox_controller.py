"""Xbox 连续控制模型、紧急停止和 UI 参数的回归测试。"""

import ctypes
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PyQt5.QtCore import QEventLoop, QTimer
from PyQt5.QtWidgets import QApplication

from config import XBOX_CONTROL_DEFAULTS
from controllers.xbox import (
    ACTIVATION_VIBRATION_MS,
    EMERGENCY_VIBRATION_MS,
    XINPUT_GAMEPAD_A,
    XINPUT_GAMEPAD_B,
    XINPUT_GAMEPAD_X,
    XINPUT_GAMEPAD_Y,
    _XInputGamepad,
    XInputBackend,
    XboxController,
    XboxControlModel,
    XboxInputState,
)


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    ((0, 0.0), (127, 127.0 / 255.0), (128, 128.0 / 255.0), (255, 1.0)),
)
def test_xinput_triggers_use_unsigned_bytes_across_the_full_range(
        raw_value, expected):
    """LT/RT 原始值跨过 127 后仍须从 0 连续增加到 1，不能跳成负数。"""
    backend = XInputBackend.__new__(XInputBackend)
    backend.dll_name = "fake_xinput.dll"
    backend._set_state = None

    def get_state(index, state_pointer):
        """向 XInput 状态指针写入指定的无符号扳机测试值。"""
        if index != 0:
            return 1167
        state_pointer._obj.Gamepad.bLeftTrigger = raw_value
        state_pointer._obj.Gamepad.bRightTrigger = raw_value
        return 0

    backend._get_state = get_state
    state = backend.poll()

    assert state.left_trigger == pytest.approx(expected)
    assert state.right_trigger == pytest.approx(expected)
    assert ctypes.sizeof(_XInputGamepad) == 12


def make_parameters():
    """返回便于精确断言周期和平滑量的测试参数。"""
    parameters = dict(XBOX_CONTROL_DEFAULTS)
    parameters.update({
        "normal_frequency": 2.0,
        "normal_amplitude": 0.2,
        "boost_frequency": 4.0,
        "boost_amplitude": 0.4,
        "maximum_turn_bias": 0.4,
        "base_bias": 0.05,
        "pec_normal_rate": 100.0,
        "pec_fast_rate": 500.0,
    })
    return parameters


def advance(model, state, seconds, step=0.05):
    """按真实短控制周期累计推进模型，避免绕过单帧 dt 安全限幅。"""
    output = None
    remaining = float(seconds)
    while remaining > 1e-9:
        current_step = min(step, remaining)
        output = model.update(state, current_step)
        remaining -= current_step
    return output


def test_front_half_starts_and_release_stops_in_two_tail_periods():
    """2 Hz 时启动和停止都应在两个周期即 1 秒内完成。"""
    model = XboxControlModel(make_parameters())
    forward = XboxInputState(connected=True, left_y=1.0)

    halfway = advance(model, forward, 0.5)
    assert halfway.drive_envelope == pytest.approx(0.5)
    assert halfway.tail_frequency == pytest.approx(1.0)
    assert halfway.tail_amplitude == pytest.approx(0.1)

    running = advance(model, forward, 0.5)
    assert running.drive_envelope == pytest.approx(1.0)
    assert running.tail_frequency == pytest.approx(2.0)
    assert running.tail_amplitude == pytest.approx(0.2)

    released = XboxInputState(connected=True)
    stopping = advance(model, released, 0.5)
    assert stopping.motion_text == "平滑停止"
    assert stopping.tail_frequency == pytest.approx(1.0)

    stopped = advance(model, released, 0.5)
    assert stopped.tail_frequency == pytest.approx(0.0)
    assert stopped.tail_amplitude == pytest.approx(0.0)
    assert stopped.tail_offset == pytest.approx(0.05)


def test_rear_half_never_drives_and_front_angle_controls_direction_only():
    """从静止直接进入后半圆不启动，前半圆幅值不参与速度计算。"""
    model = XboxControlModel(make_parameters())
    rear = XboxInputState(connected=True, left_x=0.5, left_y=-0.5)
    assert advance(model, rear, 1.0).tail_amplitude == pytest.approx(0.0)

    left_front = XboxInputState(connected=True, left_x=-1.0, left_y=0.0)
    output = advance(model, left_front, 1.0)
    assert output.tail_frequency == pytest.approx(2.0)
    assert output.tail_offset == pytest.approx(-0.35)


def test_rear_half_holds_tail_and_crossing_to_opposite_side_blends_offset():
    """绕后半圆时冻结尾鳍，跨边界后的左右偏置用两个周期连续过渡。"""
    model = XboxControlModel(make_parameters())
    left_front = XboxInputState(connected=True, left_x=-1.0, left_y=0.0)
    left_running = advance(model, left_front, 1.0)
    assert left_running.tail_frequency == pytest.approx(2.0)
    assert left_running.tail_amplitude == pytest.approx(0.2)
    assert left_running.tail_offset == pytest.approx(-0.35)

    left_rear = XboxInputState(
        connected=True,
        left_x=-0.7,
        left_y=-0.7,
        left_trigger=1.0,
        buttons=XINPUT_GAMEPAD_Y,
    )
    held = advance(model, left_rear, 0.2)
    assert held.motion_text == "后半圆保持"
    assert held.tail_frequency == pytest.approx(2.0)
    assert held.tail_amplitude == pytest.approx(0.2)
    assert held.tail_offset == pytest.approx(-0.35)
    assert held.effective_lt == pytest.approx(0.0)
    assert held.pec_pwm == 1520

    right_rear = XboxInputState(connected=True, left_x=0.7, left_y=-0.7)
    held_on_other_side = advance(model, right_rear, 0.8)
    assert held_on_other_side.tail_frequency == pytest.approx(2.0)
    assert held_on_other_side.tail_amplitude == pytest.approx(0.2)
    assert held_on_other_side.tail_offset == pytest.approx(-0.35)

    right_front = XboxInputState(connected=True, left_x=1.0, left_y=0.0)
    halfway = advance(model, right_front, 0.5)
    assert halfway.tail_offset == pytest.approx(0.05)
    finished = advance(model, right_front, 0.5)
    assert finished.tail_offset == pytest.approx(0.45)


def test_lt_acceleration_is_continuous_and_takes_two_boost_periods():
    """LT 从 0 到 100% 应在 4 Hz 的两个周期即 0.5 秒内平滑完成。"""
    model = XboxControlModel(make_parameters())
    forward = XboxInputState(connected=True, left_y=1.0)
    advance(model, forward, 1.0)

    boost = XboxInputState(connected=True, left_y=1.0, left_trigger=1.0)
    halfway = advance(model, boost, 0.25)
    assert halfway.effective_lt == pytest.approx(0.5)
    assert halfway.tail_frequency == pytest.approx(3.0)
    assert halfway.tail_amplitude == pytest.approx(0.3)

    full = advance(model, boost, 0.25)
    assert full.effective_lt == pytest.approx(1.0)
    assert full.tail_frequency == pytest.approx(4.0)
    assert full.tail_amplitude == pytest.approx(0.4)


def test_y_a_and_rt_adjust_pectoral_pwm_at_configured_rates():
    """Y/A 方向相反，RT 连续提高胸鳍调节速度，同时按 Y/A 时抵消。"""
    model = XboxControlModel(make_parameters())
    y_pressed = XboxInputState(connected=True, buttons=XINPUT_GAMEPAD_Y)
    assert model.update(y_pressed, 0.2).pec_pwm == 1520

    a_fast = XboxInputState(
        connected=True,
        right_trigger=1.0,
        buttons=XINPUT_GAMEPAD_A,
    )
    assert model.update(a_fast, 0.2).pec_pwm == 1420

    both = XboxInputState(
        connected=True,
        right_trigger=1.0,
        buttons=XINPUT_GAMEPAD_Y | XINPUT_GAMEPAD_A,
    )
    assert model.update(both, 0.2).pec_pwm == 1420


class FakeBackend:
    """按顺序返回预设采样的无硬件测试后端。"""

    available = True

    def __init__(self, states):
        """保存采样序列，耗尽后持续返回最后一帧。"""
        self.states = list(states)
        self.last = self.states[-1]
        self.vibration_calls = []

    def poll(self):
        """弹出下一帧测试状态。"""
        if self.states:
            self.last = self.states.pop(0)
        return self.last

    def set_vibration(self, controller_index, left_motor, right_motor):
        """记录震动调用，模拟 XInputSetState 成功。"""
        self.vibration_calls.append(
            (controller_index, float(left_motor), float(right_motor))
        )
        return True


def ensure_app():
    """确保控制器 QTimer 有可用的 QApplication。"""
    return QApplication.instance() or QApplication([])


def test_successful_activation_uses_longer_confirmation_vibration():
    """控制成功启用后应长震 600 ms，且明显长于紧停短震。"""
    app = ensure_app()
    connected = XboxInputState(connected=True, controller_index=0)
    backend = FakeBackend([connected])
    times = iter((0.0, 0.0))
    controller = XboxController(backend=backend, time_source=lambda: next(times))
    controller._poll_timer.stop()
    messages = []
    controller.status_changed.connect(messages.append)

    assert controller.activate() is True
    assert backend.vibration_calls == [(0, 0.55, 0.75)]
    assert controller._vibration_timer.isActive()
    assert controller._vibration_timer.interval() == ACTIVATION_VIBRATION_MS
    assert ACTIVATION_VIBRATION_MS > EMERGENCY_VIBRATION_MS
    assert messages[-1] == "Xbox 控制已激活（手柄 1），长震确认"

    loop = QEventLoop()
    QTimer.singleShot(ACTIVATION_VIBRATION_MS + 100, loop.quit)
    loop.exec_()
    assert app is QApplication.instance()
    assert not controller._vibration_timer.isActive()
    assert backend.vibration_calls[-1] == (0, 0.0, 0.0)


@pytest.mark.parametrize(
    "button_mask",
    (XINPUT_GAMEPAD_X, XINPUT_GAMEPAD_B),
)
def test_x_or_b_emits_immediate_zero_tail_vibrates_then_requests_disarm(
        button_mask):
    """X/B 紧停须先发零摆幅、启动短震，再通知主界面撤销控制权。"""
    ensure_app()
    connected = XboxInputState(connected=True, controller_index=0, left_y=1.0)
    emergency = XboxInputState(
        connected=True,
        controller_index=0,
        left_y=1.0,
        buttons=button_mask,
    )
    backend = FakeBackend([connected, emergency, connected])
    times = iter((0.0, 0.0, 0.02, 0.04))
    controller = XboxController(backend=backend, time_source=lambda: next(times))
    controller._poll_timer.stop()
    commands = []
    events = []
    controller.control_command_generated.connect(commands.append)
    controller.emergency_stop_requested.connect(events.append)

    assert controller.activate() is True
    controller._stop_vibration()
    backend.vibration_calls.clear()
    controller._poll_controller()

    assert len(commands) == 1
    assert commands[0].tail_frequency == pytest.approx(0.0)
    assert commands[0].tail_amplitude == pytest.approx(0.0)
    assert commands[0].pec_angle == 1500
    assert backend.vibration_calls == [(0, 0.75, 1.0)]
    assert controller._vibration_timer.isActive()
    assert controller._vibration_timer.interval() == EMERGENCY_VIBRATION_MS
    assert events == ["X/B 紧急停止：尾鳍已立即停止，手柄短震提示"]

    controller._stop_vibration()
    assert backend.vibration_calls[-1] == (0, 0.0, 0.0)

    controller._poll_controller()
    assert len(commands) == 1
    assert controller._emergency_latched


def test_disconnect_emits_immediate_zero_tail_and_latches_stop():
    """已激活手柄断连时必须立即停尾并保持胸鳍指令。"""
    ensure_app()
    connected = XboxInputState(connected=True, controller_index=0, left_y=1.0)
    disconnected = XboxInputState()
    backend = FakeBackend([connected, disconnected])
    times = iter((0.0, 0.0, 0.02))
    controller = XboxController(backend=backend, time_source=lambda: next(times))
    controller._poll_timer.stop()
    commands = []
    events = []
    controller.control_command_generated.connect(commands.append)
    controller.emergency_stop_requested.connect(events.append)

    assert controller.activate() is True
    controller._poll_controller()

    assert len(commands) == 1
    assert commands[0].tail_frequency == pytest.approx(0.0)
    assert commands[0].tail_amplitude == pytest.approx(0.0)
    assert commands[0].pec_angle == 1500
    assert events == ["Xbox 手柄断开，尾鳍已立即停止"]
    assert controller._emergency_latched


def test_controller_refuses_activation_without_connected_gamepad():
    """未检测到手柄时控制器不得进入激活状态。"""
    ensure_app()
    backend = FakeBackend([XboxInputState()])
    times = iter((0.0, 0.0))
    controller = XboxController(backend=backend, time_source=lambda: next(times))
    controller._poll_timer.stop()

    assert controller.activate() is False
    assert controller.active is False
    assert backend.vibration_calls == []
