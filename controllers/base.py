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
import time

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from communication.base import ControlCommand
from config import KEYBOARD_MAPPING, CONTROL_LIMITS

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
    
    def __init__(self):
        super().__init__()
        self._key_states = {}
        self._control_widget = None
        self._update_timer = QTimer()
        self._update_timer.timeout.connect(self._update_control)
        self._update_timer.setInterval(100)  # 10Hz
        
        # 初始化控制参数
        self._freq_step = 0.1
        self._amp_step = 0.05
        
        # 运动状态（保持状态而非瞬时按键）
        self._motion_state = "stop"  # stop, forward, left, right, up, down
        
        # 胸鳍角度控制 (1300-2000μs)
        self._pec_angle = CONTROL_LIMITS["pec_angle"]["default"]
        self._pec_angle_step = 10  # 每次增减10μs
        
        # 保存的参数（停止时不清零这些）
        self._saved_frequency = 0.5  # 默认0.5Hz
        self._saved_amplitude = 0.2  # 默认0.2rad
        
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
                                     QLabel, QGroupBox, QGridLayout)
        from PyQt5.QtCore import Qt
        from PyQt5.QtGui import QFont
        
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # 标题
        title = QLabel("键盘控制")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(QFont("Arial", 16, QFont.Bold))
        layout.addWidget(title)
        
        # 控制说明
        control_group = QGroupBox("控制按键说明")
        control_layout = QGridLayout(control_group)
        
        mappings = [
            ("前进", "W"),
            ("停止", "S"),
            ("左转", "A"),
            ("右转", "D"),
            ("胸鳍+", "Q"),
            ("胸鳍-", "E"),
            ("频率+", "Up"),
            ("频率-", "Down"),
            ("幅度+", "R"),
            ("幅度-", "F"),
            ("切换绘图", "P"),
            ("清空数据", "C")
        ]
        
        for i, (action, key) in enumerate(mappings):
            row, col = i // 2, (i % 2) * 2
            control_layout.addWidget(QLabel(f"{action}:"), row, col)
            control_layout.addWidget(QLabel(f"[{key}]"), row, col + 1)
        
        layout.addWidget(control_group)
        
        # 当前参数显示
        params_group = QGroupBox("当前控制参数")
        params_layout = QVBoxLayout(params_group)
        
        self._motion_label = QLabel(f"运动状态: 停止")
        self._freq_label = QLabel(f"摆尾频率: {self._current_command.tail_frequency:.2f} Hz")
        self._amp_label = QLabel(f"摆尾幅度: {self._current_command.tail_amplitude:.2f} rad")
        self._offset_label = QLabel(f"偏移角度: {self._current_command.tail_offset:.2f} rad")
        self._pec_label = QLabel(f"胸鳍角度: {self._pec_angle} μs")
        
        params_layout.addWidget(self._motion_label)
        params_layout.addWidget(self._freq_label)
        params_layout.addWidget(self._amp_label)
        params_layout.addWidget(self._offset_label)
        params_layout.addWidget(self._pec_label)
        
        layout.addWidget(params_group)
        
        layout.addStretch()
        
        return widget
    
    def handle_key_press(self, key: str):
        """处理按键按下 - 切换运动状态"""
        self._key_states[key] = True
        
        # 方向控制 - 按一次切换状态并保持
        if key == KEYBOARD_MAPPING["forward"]:
            self._motion_state = "forward"
            # 恢复保存的参数
            if self._current_command.tail_frequency == 0:
                self._current_command.tail_frequency = self._saved_frequency
                self._current_command.tail_amplitude = self._saved_amplitude
        elif key == KEYBOARD_MAPPING["backward"]:  # S键 = 停止
            self._motion_state = "stop"
            # 保存当前非零参数
            if self._current_command.tail_frequency > 0:
                self._saved_frequency = self._current_command.tail_frequency
                self._saved_amplitude = self._current_command.tail_amplitude
        elif key == KEYBOARD_MAPPING["left"]:
            self._motion_state = "left"
            # A键只改偏置，保持freq/amp不变
            if self._current_command.tail_frequency == 0:
                self._current_command.tail_frequency = self._saved_frequency
                self._current_command.tail_amplitude = self._saved_amplitude
        elif key == KEYBOARD_MAPPING["right"]:
            self._motion_state = "right"
            # D键只改偏置，保持freq/amp不变
            if self._current_command.tail_frequency == 0:
                self._current_command.tail_frequency = self._saved_frequency
                self._current_command.tail_amplitude = self._saved_amplitude
        # 注意：上下箭头不在这里处理，在_update_control中作为持续按键处理
        
    def handle_key_release(self, key: str):
        """处理按键释放"""
        self._key_states[key] = False
    
    def _update_control(self):
        """更新控制命令"""
        if not self._active:
            return
        
        # Q/E控制胸鳍角度（增量式，长按生效）
        if self._key_states.get(KEYBOARD_MAPPING["increase_pec"], False):  # Q键
            self._pec_angle = min(
                self._pec_angle + self._pec_angle_step,
                CONTROL_LIMITS["pec_angle"]["max"]
            )
        elif self._key_states.get(KEYBOARD_MAPPING["decrease_pec"], False):  # E键
            self._pec_angle = max(
                self._pec_angle - self._pec_angle_step,
                CONTROL_LIMITS["pec_angle"]["min"]
            )
        
        # 上下箭头控制频率（按住生效）
        if self._key_states.get(KEYBOARD_MAPPING["increase_freq"], False):  # Up键
            new_freq = min(
                self._current_command.tail_frequency + self._freq_step,
                CONTROL_LIMITS["tail_frequency"]["max"]
            )
            self._current_command.tail_frequency = new_freq
            self._saved_frequency = new_freq
        elif self._key_states.get(KEYBOARD_MAPPING["decrease_freq"], False):  # Down键
            new_freq = max(
                self._current_command.tail_frequency - self._freq_step,
                CONTROL_LIMITS["tail_frequency"]["min"]
            )
            self._current_command.tail_frequency = new_freq
            self._saved_frequency = new_freq
        
        # R/F调节幅度（按住生效）
        if self._key_states.get(KEYBOARD_MAPPING["increase_amp"], False):  # R键
            new_amp = min(
                self._current_command.tail_amplitude + self._amp_step,
                CONTROL_LIMITS["tail_amplitude"]["max"]
            )
            self._current_command.tail_amplitude = new_amp
            self._saved_amplitude = new_amp
        elif self._key_states.get(KEYBOARD_MAPPING["decrease_amp"], False):  # F键
            new_amp = max(
                self._current_command.tail_amplitude - self._amp_step,
                CONTROL_LIMITS["tail_amplitude"]["min"]
            )
            self._current_command.tail_amplitude = new_amp
            self._saved_amplitude = new_amp
        
        # 基于运动状态设置参数
        motion_label_text = "停止"
        
        if self._motion_state == "stop":
            # 停止状态：发送0但不清除保存的参数
            self._current_command.tail_frequency = 0.0
            self._current_command.tail_amplitude = 0.0
            self._current_command.tail_offset = 0.0
            motion_label_text = "停止"
        elif self._motion_state == "forward":
            # 前进：偏移0
            self._current_command.tail_offset = 0.0
            motion_label_text = "前进"
        elif self._motion_state == "left":
            # 左转：负偏移，频率幅度由上次设定决定
            self._current_command.tail_offset = -0.15
            motion_label_text = "左转"
        elif self._motion_state == "right":
            # 右转：正偏移，频率幅度由上次设定决定
            self._current_command.tail_offset = 0.15
            motion_label_text = "右转"
        elif self._motion_state == "up":
            motion_label_text = "上浮"
        elif self._motion_state == "down":
            motion_label_text = "下潜"
        
        # 确保偏移在安全范围内
        self._current_command.tail_offset = max(
            CONTROL_LIMITS["tail_offset"]["min"],
            min(self._current_command.tail_offset, CONTROL_LIMITS["tail_offset"]["max"])
        )
        self._current_command.timestamp = time.time()
        
        # 更新界面显示
        if hasattr(self, '_motion_label'):
            self._motion_label.setText(f"运动状态: {motion_label_text}")
        if hasattr(self, '_freq_label'):
            self._freq_label.setText(f"摆尾频率: {self._current_command.tail_frequency:.2f} Hz")
            self._amp_label.setText(f"摆尾幅度: {self._current_command.tail_amplitude:.2f} rad")
            self._offset_label.setText(f"偏移角度: {self._current_command.tail_offset:.2f} rad")
            self._pec_label.setText(f"胸鳍角度: {self._pec_angle} μs")
        
        # 只在命令变化时发送（避免静止时持续发送）
        current_cmd_tuple = (
            round(self._current_command.tail_frequency, 2),
            round(self._current_command.tail_amplitude, 2), 
            round(self._current_command.tail_offset, 2),
            self._pec_angle
        )
        
        if self._last_sent_command != current_cmd_tuple:
            self._last_sent_command = current_cmd_tuple
            self.control_command_generated.emit(self._current_command)
