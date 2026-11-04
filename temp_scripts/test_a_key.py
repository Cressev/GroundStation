#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""无界面测试: 验证大小写区分快慢 + 参数持久化"""
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtCore import QCoreApplication
from controllers.base import KeyboardController, PARAMS_FILE

app = QCoreApplication([])  # QTimer需要事件循环存在

sent = []
kc = KeyboardController()
kc.control_command_generated.connect(lambda cmd: sent.append(
    (round(cmd.tail_frequency, 2), round(cmd.tail_amplitude, 3), round(cmd.tail_offset, 3))))
kc.activate()


def press(key):
    sent.clear()
    kc.handle_key_press(key)
    kc._update_control()          # 模拟10Hz定时器触发一次
    state = {"w": "慢速前进", "W": "快速前进", "a": "慢速左转", "A": "快速左转",
             "d": "慢速右转", "D": "快速右转", "s": "停止"}.get(key, key)
    print(f"按下 {key:<8} -> {state:<6} 发送 (freq, amp, offset)={sent}")


print("=== 大小写区分快慢 ===")
press("w")
press("W")
press("a")
press("A")
press("d")
press("D")
press("s")
press("Shift+A")   # 兼容旧键名
kc.deactivate()

print("\n=== 基础偏置-0.5时的转向余量(复现用户场景) ===")
kc = KeyboardController()
kc.control_command_generated.connect(lambda cmd: sent.append(
    (round(cmd.tail_frequency, 2), round(cmd.tail_amplitude, 3), round(cmd.tail_offset, 3))))
kc.activate()
kc.set_keyboard_parameters(
    base_bias=-0.5, slow_frequency=1.5, slow_amplitude=0.2, slow_turn_bias=0.3,
    fast_frequency=4.0, fast_amplitude=0.5, fast_turn_bias=0.5)
kc._last_sent_command = None


def press2(key):
    sent.clear()
    kc.handle_key_press(key)
    kc._update_control()
    print(f"按下 {key:<4} -> 状态={kc._motion_state:<12} 发送 {sent}")


press2("w")   # 直行: -0.5
press2("a")   # 慢速左转: -0.8, 不再被截断成-0.5
press2("A")   # 快速左转: -1.0
press2("d")   # 慢速右转: -0.2
press2("D")   # 快速右转: 0.0
kc.deactivate()

print("\n=== 参数持久化 ===")
kc.activate()
kc.set_keyboard_parameters(
    base_bias=0.05, slow_frequency=1.8, slow_amplitude=0.25, slow_turn_bias=0.35,
    fast_frequency=3.6, fast_amplitude=0.45, fast_turn_bias=0.5)
kc._save_parameters()
print(f"已保存到 {PARAMS_FILE}")

kc2 = KeyboardController()   # 模拟下次启动
print(f"重新启动后加载: {kc2._keyboard_params}")
assert abs(kc2._keyboard_params["slow_frequency"] - 1.8) < 1e-6, "持久化加载失败"
assert abs(kc2._keyboard_params["fast_turn_bias"] - 0.5) < 1e-6, "持久化加载失败"
print("持久化验证通过 ✓")
