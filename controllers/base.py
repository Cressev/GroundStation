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
        self._update_timer.setInterval(50)  # 20Hz
        
        # 初始化控制参数
        self._freq_step = 0.1
        self._amp_step = 0.05
        self._offset_step = 0.05
        
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
            ("前进", KEYBOARD_MAPPING["forward"]),
            ("后退", KEYBOARD_MAPPING["backward"]),
            ("左转", KEYBOARD_MAPPING["left"]),
            ("右转", KEYBOARD_MAPPING["right"]),
            ("上浮", KEYBOARD_MAPPING["up"]),
            ("下潜", KEYBOARD_MAPPING["down"]),
            ("停止", KEYBOARD_MAPPING["stop"]),
            ("增加频率", KEYBOARD_MAPPING["increase_freq"]),
            ("减少频率", KEYBOARD_MAPPING["decrease_freq"]),
            ("增加幅度", KEYBOARD_MAPPING["increase_amp"]),
            ("减少幅度", KEYBOARD_MAPPING["decrease_amp"]),
            ("切换绘图", KEYBOARD_MAPPING["toggle_plot"]),
            ("清空数据", KEYBOARD_MAPPING["clear_plot"])
        ]
        
        for i, (action, key) in enumerate(mappings):
            row, col = i // 2, (i % 2) * 2
            control_layout.addWidget(QLabel(f"{action}:"), row, col)
            control_layout.addWidget(QLabel(f"[{key}]"), row, col + 1)
        
        layout.addWidget(control_group)
        
        # 当前参数显示
        params_group = QGroupBox("当前控制参数")
        params_layout = QVBoxLayout(params_group)
        
        self._freq_label = QLabel(f"摆尾频率: {self._current_command.tail_frequency:.2f} Hz")
        self._amp_label = QLabel(f"摆尾幅度: {self._current_command.tail_amplitude:.2f} rad")
        self._offset_label = QLabel(f"偏移角度: {self._current_command.tail_offset:.2f} rad")
        
        params_layout.addWidget(self._freq_label)
        params_layout.addWidget(self._amp_label)
        params_layout.addWidget(self._offset_label)
        
        layout.addWidget(params_group)
        
        layout.addStretch()
        
        return widget
    
    def handle_key_press(self, key: str):
        """处理按键按下"""
        self._key_states[key] = True
        
    def handle_key_release(self, key: str):
        """处理按键释放"""
        self._key_states[key] = False
    
    def _update_control(self):
        """更新控制命令"""
        if not self._active:
            return
            
        # 处理频率控制
        if self._key_states.get(KEYBOARD_MAPPING["increase_freq"], False):
            self._current_command.tail_frequency = min(
                self._current_command.tail_frequency + self._freq_step,
                CONTROL_LIMITS["tail_frequency"]["max"]
            )
        elif self._key_states.get(KEYBOARD_MAPPING["decrease_freq"], False):
            self._current_command.tail_frequency = max(
                self._current_command.tail_frequency - self._freq_step,
                CONTROL_LIMITS["tail_frequency"]["min"]
            )
        
        # 处理幅度控制
        if self._key_states.get(KEYBOARD_MAPPING["increase_amp"], False):
            self._current_command.tail_amplitude = min(
                self._current_command.tail_amplitude + self._amp_step,
                CONTROL_LIMITS["tail_amplitude"]["max"]
            )
        elif self._key_states.get(KEYBOARD_MAPPING["decrease_amp"], False):
            self._current_command.tail_amplitude = max(
                self._current_command.tail_amplitude - self._amp_step,
                CONTROL_LIMITS["tail_amplitude"]["min"]
            )
        
        # 处理方向控制（通过偏移角度）
        base_offset = 0.0
        if self._key_states.get(KEYBOARD_MAPPING["forward"], False):
            base_offset = 0.0
        elif self._key_states.get(KEYBOARD_MAPPING["backward"], False):
            base_offset = 3.14159  # 180度
        elif self._key_states.get(KEYBOARD_MAPPING["left"], False):
            base_offset = -1.5708  # -90度
        elif self._key_states.get(KEYBOARD_MAPPING["right"], False):
            base_offset = 1.5708   # 90度
        elif self._key_states.get(KEYBOARD_MAPPING["up"], False):
            # 上浮：减小频率，增大幅度
            self._current_command.tail_frequency *= 0.8
            self._current_command.tail_amplitude = min(
                self._current_command.tail_amplitude * 1.1,
                CONTROL_LIMITS["tail_amplitude"]["max"]
            )
        elif self._key_states.get(KEYBOARD_MAPPING["down"], False):
            # 下潜：增大频率，减小幅度  
            self._current_command.tail_frequency = min(
                self._current_command.tail_frequency * 1.2,
                CONTROL_LIMITS["tail_frequency"]["max"]
            )
            self._current_command.tail_amplitude *= 0.9
        elif self._key_states.get(KEYBOARD_MAPPING["stop"], False):
            # 停止：频率和幅度都设为0
            self._current_command.tail_frequency = 0.0
            self._current_command.tail_amplitude = 0.0
            base_offset = 0.0
        
        self._current_command.tail_offset = base_offset
        self._current_command.timestamp = time.time()
        
        # 更新界面显示
        if hasattr(self, '_freq_label'):
            self._freq_label.setText(f"摆尾频率: {self._current_command.tail_frequency:.2f} Hz")
            self._amp_label.setText(f"摆尾幅度: {self._current_command.tail_amplitude:.2f} rad")
            self._offset_label.setText(f"偏移角度: {self._current_command.tail_offset:.2f} rad")
        
        # 发送控制命令
        self.control_command_generated.emit(self._current_command)
