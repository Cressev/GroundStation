#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
机器鱼版本选择对话框
Fish Variant Selection Dialog

启动时让用户选择要控制的机器鱼版本：
  - 双尾双目鱼（pico RK3588S，ROS2，双目测距）
  - 单尾单目鱼（orangepi，ROS1，鱼眼相机）
不同版本决定主窗口的视频页面、通信对象与控制面板。
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
                             QLabel, QFrame, QGroupBox)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

from config import FISH_VARIANTS


class FishVariantDialog(QDialog):
    """机器鱼版本选择对话框。

    exec_() 返回所选变体键名（FISH_VARIANTS 的 key）；
    用户关闭对话框（Esc/右上角）时返回空字符串，主程序直接退出。
    """

    def __init__(self, parent=None):
        """构建变体按钮并绑定选择事件。"""
        super().__init__(parent)
        self.selected_variant = ""
        self.setWindowTitle("选择机器鱼版本 Select Fish Variant")
        self.setMinimumSize(520, 320)

        layout = QVBoxLayout(self)

        title = QLabel("请选择要控制的机器鱼版本")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(QFont("Arial", 15, QFont.Bold))
        layout.addWidget(title)

        hint = QLabel("不同版本的鱼体结构、机载计算机与视频系统不同，"
                      "地面站将加载对应的控制与显示页面")
        hint.setAlignment(Qt.AlignCenter)
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # 双尾双目鱼卡片
        dual_group = QGroupBox("双尾双目鱼（当前主攻）")
        dual_layout = QVBoxLayout(dual_group)
        dual_desc = QLabel(FISH_VARIANTS["dual"]["description"] +
                           "\n机载: pico RK3588S + ROS2 Humble"
                           "\n视频: 双目校正画布 + 点击测距"
                           "\n控制: TCP 控制桥 -> 串口桥 -> STM32")
        dual_desc.setWordWrap(True)
        dual_layout.addWidget(dual_desc)
        self.dual_button = QPushButton(FISH_VARIANTS["dual"]["name"])
        self.dual_button.setMinimumHeight(44)
        self.dual_button.setStyleSheet(
            "QPushButton {background-color: #2d8cf0; color: white; "
            "font-weight: bold; font-size: 14px; border-radius: 6px;}"
            "QPushButton:hover {background-color: #5cadff;}")
        self.dual_button.clicked.connect(lambda: self._select("dual"))
        dual_layout.addWidget(self.dual_button)
        layout.addWidget(dual_group)

        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)

        # 单尾单目鱼卡片
        single_group = QGroupBox("单尾单目鱼（旧平台）")
        single_layout = QVBoxLayout(single_group)
        single_desc = QLabel(FISH_VARIANTS["single"]["description"] +
                             "\n机载: orangepi + ROS1"
                             "\n视频: 鱼眼相机 TCP 流"
                             "\n控制: socket_server -> /servo_info_*")
        single_desc.setWordWrap(True)
        single_layout.addWidget(single_desc)
        self.single_button = QPushButton(FISH_VARIANTS["single"]["name"])
        self.single_button.setMinimumHeight(40)
        self.single_button.clicked.connect(lambda: self._select("single"))
        single_layout.addWidget(self.single_button)
        layout.addWidget(single_group)

    def _select(self, variant):
        """记录所选变体并关闭对话框。"""
        self.selected_variant = variant
        self.accept()
