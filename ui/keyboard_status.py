#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
按键状态显示组件
Keyboard Status Display Component
"""

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, 
                             QLabel, QGridLayout, QPushButton, QFrame)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont, QPalette

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import KEYBOARD_MAPPING

class KeyboardStatusWidget(QWidget):
    """按键状态显示组件"""
    
    # 信号定义
    plot_toggled = pyqtSignal(bool)  # 绘图开关信号
    plot_cleared = pyqtSignal()      # 清空绘图信号
    
    def __init__(self):
        super().__init__()
        self.key_states = {}  # 存储按键状态
        self.key_labels = {}  # 存储按键标签组件
        self.plot_enabled = True  # 绘图状态
        
        self._init_ui()
        
        # 按键状态更新定时器
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self._update_key_display)
        self.update_timer.start(50)  # 20Hz更新频率
        
    def _init_ui(self):
        """初始化用户界面"""
        layout = QVBoxLayout(self)
        
        # 标题
        title = QLabel("按键状态监控")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(QFont("Arial", 14, QFont.Bold))
        layout.addWidget(title)
        
        # 按键状态显示区域
        keys_group = QGroupBox("当前按键状态")
        keys_layout = QGridLayout(keys_group)
        
        # 创建按键显示标签
        key_buttons = [
            # 运动控制
            ("前进", KEYBOARD_MAPPING["forward"], 0, 0),
            ("停止", KEYBOARD_MAPPING["backward"], 0, 1),
            ("左转", KEYBOARD_MAPPING["left"], 1, 0),
            ("右转", KEYBOARD_MAPPING["right"], 1, 1),
            
            # 参数调节
            ("胸鳍+", KEYBOARD_MAPPING["increase_pec"], 2, 0),
            ("胸鳍-", KEYBOARD_MAPPING["decrease_pec"], 2, 1),
            ("频率+", KEYBOARD_MAPPING["increase_freq"], 3, 0),
            ("频率-", KEYBOARD_MAPPING["decrease_freq"], 3, 1),
            ("幅度+", KEYBOARD_MAPPING["increase_amp"], 4, 0),
            ("幅度-", KEYBOARD_MAPPING["decrease_amp"], 4, 1),
            
            # UI控制
            ("切换绘图", KEYBOARD_MAPPING["toggle_plot"], 5, 0),
            ("清空数据", KEYBOARD_MAPPING["clear_plot"], 5, 1),
        ]
        
        for description, key, row, col in key_buttons:
            # 创建按键显示框
            key_frame = QFrame()
            key_frame.setFrameStyle(QFrame.Box | QFrame.Raised)
            key_frame.setLineWidth(2)
            key_frame.setFixedSize(100, 50)
            
            frame_layout = QVBoxLayout(key_frame)
            frame_layout.setContentsMargins(5, 5, 5, 5)
            
            # 按键标签
            key_label = QLabel(f"[{key}]")
            key_label.setAlignment(Qt.AlignCenter)
            key_label.setFont(QFont("Arial", 10, QFont.Bold))
            
            # 功能描述标签
            desc_label = QLabel(description)
            desc_label.setAlignment(Qt.AlignCenter)
            desc_label.setFont(QFont("Arial", 8))
            
            frame_layout.addWidget(key_label)
            frame_layout.addWidget(desc_label)
            
            keys_layout.addWidget(key_frame, row, col)
            
            # 保存引用以便后续更新
            self.key_labels[key] = (key_frame, key_label, desc_label)
            self.key_states[key] = False
        
        layout.addWidget(keys_group)
        
        # 绘图控制区域
        plot_group = QGroupBox("绘图控制")
        plot_layout = QVBoxLayout(plot_group)
        
        # 绘图状态显示
        self.plot_status_label = QLabel("绘图状态: 开启")
        self.plot_status_label.setAlignment(Qt.AlignCenter)
        self.plot_status_label.setFont(QFont("Arial", 12, QFont.Bold))
        self.plot_status_label.setStyleSheet("color: green;")
        plot_layout.addWidget(self.plot_status_label)
        
        # 控制按钮
        button_layout = QHBoxLayout()
        
        self.toggle_plot_btn = QPushButton("暂停绘图 [P]")
        self.toggle_plot_btn.clicked.connect(self._toggle_plot)
        self.toggle_plot_btn.setFont(QFont("Arial", 10))
        
        self.clear_plot_btn = QPushButton("清空数据 [C]")
        self.clear_plot_btn.clicked.connect(self._clear_plot)
        self.clear_plot_btn.setFont(QFont("Arial", 10))
        
        button_layout.addWidget(self.toggle_plot_btn)
        button_layout.addWidget(self.clear_plot_btn)
        
        plot_layout.addLayout(button_layout)
        
        # 快捷键说明
        shortcut_label = QLabel("快捷键: [P] 切换绘图, [C] 清空数据")
        shortcut_label.setAlignment(Qt.AlignCenter)
        shortcut_label.setFont(QFont("Arial", 9))
        shortcut_label.setStyleSheet("color: gray;")
        plot_layout.addWidget(shortcut_label)
        
        layout.addWidget(plot_group)
        
        # 按键记录区域
        record_group = QGroupBox("按键记录")
        record_layout = QVBoxLayout(record_group)
        
        self.key_history_label = QLabel("等待按键输入...")
        self.key_history_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.key_history_label.setFont(QFont("Consolas", 9))
        self.key_history_label.setWordWrap(True)
        self.key_history_label.setFixedHeight(120)  # 增加高度到120
        self.key_history_label.setStyleSheet("background-color: #f0f0f0; padding: 5px; border: 1px solid #ccc;")
        
        record_layout.addWidget(self.key_history_label)
        layout.addWidget(record_group)
        
        layout.addStretch()
        
        # 初始化按键历史记录
        self.key_history = []
        self.max_history = 10
        
    def update_key_state(self, key: str, pressed: bool):
        """更新按键状态"""
        if key in self.key_states:
            self.key_states[key] = pressed
            
            # 更新按键历史记录
            if pressed:
                import datetime
                timestamp = datetime.datetime.now().strftime("%H:%M:%S")
                action = self._get_key_action(key)
                self.key_history.append(f"[{timestamp}] {action} ({key})")
                
                # 限制历史记录长度
                if len(self.key_history) > self.max_history:
                    self.key_history.pop(0)
                
                self._update_history_display()
    
    def handle_special_keys(self, key: str, pressed: bool):
        """处理特殊功能键"""
        if not pressed:  # 只响应按键按下事件
            return
            
        if key == KEYBOARD_MAPPING["toggle_plot"]:
            self._toggle_plot()
        elif key == KEYBOARD_MAPPING["clear_plot"]:
            self._clear_plot()
    
    def _get_key_action(self, key: str) -> str:
        """获取按键对应的动作描述"""
        action_map = {
            KEYBOARD_MAPPING["forward"]: "前进",
            KEYBOARD_MAPPING["backward"]: "停止",
            KEYBOARD_MAPPING["left"]: "左转", 
            KEYBOARD_MAPPING["right"]: "右转",
            KEYBOARD_MAPPING["increase_pec"]: "胸鳍+",
            KEYBOARD_MAPPING["decrease_pec"]: "胸鳍-",
            KEYBOARD_MAPPING["increase_freq"]: "频率+",
            KEYBOARD_MAPPING["decrease_freq"]: "频率-",
            KEYBOARD_MAPPING["increase_amp"]: "幅度+",
            KEYBOARD_MAPPING["decrease_amp"]: "幅度-"
        }
        return action_map.get(key, "未知动作")
    
    def _update_key_display(self):
        """更新按键显示状态"""
        for key, (frame, key_label, desc_label) in self.key_labels.items():
            is_pressed = self.key_states.get(key, False)
            
            if is_pressed:
                # 按键按下状态 - 高亮显示
                frame.setStyleSheet("""
                    QFrame {
                        background-color: #4CAF50;
                        border: 2px solid #45a049;
                        border-radius: 5px;
                    }
                """)
                key_label.setStyleSheet("color: white; font-weight: bold;")
                desc_label.setStyleSheet("color: white;")
            else:
                # 按键释放状态 - 正常显示
                frame.setStyleSheet("""
                    QFrame {
                        background-color: #f9f9f9;
                        border: 1px solid #ddd;
                        border-radius: 5px;
                    }
                """)
                key_label.setStyleSheet("color: black;")
                desc_label.setStyleSheet("color: #666;")
    
    def _update_history_display(self):
        """更新按键历史显示"""
        history_text = "\n".join(self.key_history[-5:])  # 只显示最近5条
        if not history_text:
            history_text = "等待按键输入..."
        self.key_history_label.setText(history_text)
    
    def _toggle_plot(self):
        """切换绘图状态"""
        self.plot_enabled = not self.plot_enabled
        
        if self.plot_enabled:
            self.plot_status_label.setText("绘图状态: 开启")
            self.plot_status_label.setStyleSheet("color: green;")
            self.toggle_plot_btn.setText("暂停绘图 [P]")
        else:
            self.plot_status_label.setText("绘图状态: 暂停")
            self.plot_status_label.setStyleSheet("color: red;")
            self.toggle_plot_btn.setText("开启绘图 [P]")
        
        # 发射信号
        self.plot_toggled.emit(self.plot_enabled)
        
        # 记录到历史
        import datetime
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        action = "开启绘图" if self.plot_enabled else "暂停绘图"
        self.key_history.append(f"[{timestamp}] {action}")
        if len(self.key_history) > self.max_history:
            self.key_history.pop(0)
        self._update_history_display()
    
    def _clear_plot(self):
        """清空绘图数据"""
        # 发射信号
        self.plot_cleared.emit()
        
        # 记录到历史
        import datetime
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.key_history.append(f"[{timestamp}] 清空绘图数据")
        if len(self.key_history) > self.max_history:
            self.key_history.pop(0)
        self._update_history_display()
    
    def get_plot_enabled(self) -> bool:
        """获取绘图开启状态"""
        return self.plot_enabled
