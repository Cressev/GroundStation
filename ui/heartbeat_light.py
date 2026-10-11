#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""heartbeat_light.py — 心跳呼吸灯（真实发送驱动，不做装饰性空闪）。

设计原则（用户 2026-10-11 要求）：脉冲只由"真实发出心跳"事件触发——
通信层心跳线程每次 sendall 成功后调用 trigger_pulse()，亮度抬升后在
两次心跳间隔内自然衰减（0.5s 心跳周期 → 约 2Hz 的视觉呼吸节奏）；
心跳停止（线程死亡/连接断开/发送失败）则灯沉回暗态，绝不独立闪烁。

状态：
  未连接          灰点（set_connected(False)）
  已连接待活      暗绿点（set_connected(True)，等待第一拍心跳）
  心跳正常        每拍亮起-衰减的呼吸绿；悬停可见累计拍数
"""
import time

from PyQt5.QtCore import QTimer, pyqtSignal
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QWidget


class HeartbeatLight(QWidget):
    """心跳呼吸灯组件（主窗口状态栏左下角用）。

    心跳线程跨线程调用 trigger_pulse()（内部经 Qt 信号排队回 UI 线程）；
    连接状态用 set_connected() 切换。
    """

    pulse_received = pyqtSignal(int)

    DIM = "#3a5a3a"    # 已连接暗态（暗绿，表示"在等下一拍"）
    OFF = "#666666"    # 未连接灰
    LIVE = "#2ecc71"   # 脉冲亮绿

    def __init__(self, parent=None):
        """构造呼吸灯：圆点+文字标签、33ms 衰减定时器与跨线程脉冲信号。"""
        super().__init__(parent)
        self._level = 0.0          # 0..1 脉冲亮度
        self._connected = False
        self._count = 0
        self._last_time = "--:--:--"

        self.pulse_received.connect(self._on_pulse_received)

        # 衰减定时器：约 30fps，每 33ms 亮度×0.8（0.5s 后≈0.03，贴近暗态）
        self._decay = QTimer(self)
        self._decay.timeout.connect(self._tick)
        self._decay.start(33)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 0, 6, 0)
        self._dot = QLabel("●")
        self._dot.setFixedWidth(16)
        self._text = QLabel("心跳")
        self._text.setStyleSheet("color: #888888;")
        layout.addWidget(self._dot)
        layout.addWidget(self._text)
        layout.addStretch(1)
        self._paint()

    def trigger_pulse(self, counter: int = 0):
        """心跳线程调用：真实发出一拍心跳（跨线程安全，经信号排队）。"""
        self.pulse_received.emit(counter)

    def set_connected(self, connected: bool):
        """连接状态切换：断开转灰熄灭；连接后先暗绿，等第一拍心跳点亮。"""
        self._connected = bool(connected)
        if not self._connected:
            self._level = 0.0
        self._paint()

    def _on_pulse_received(self, counter: int):
        """UI 线程槽：抬升亮度并记录拍号/时刻。"""
        self._count = counter
        self._last_time = time.strftime("%H:%M:%S")
        self._level = 1.0
        self._paint()

    def _tick(self):
        """衰减定时器槽：亮度按周期衰减，沉到阈值以下即熄灭并停止重绘。"""
        if self._level > 0.0:
            self._level *= 0.80
            if self._level <= 0.02:
                self._level = 0.0
            self._paint()

    def _paint(self):
        """按当前亮度在暗态与亮绿之间插值刷新圆点与提示。"""
        if not self._connected:
            color = self.OFF
        else:
            level = max(0.0, min(1.0, self._level))
            r = int(int(self.DIM[1:3], 16) + (int(self.LIVE[1:3], 16) - int(self.DIM[1:3], 16)) * level)
            g = int(int(self.DIM[3:5], 16) + (int(self.LIVE[3:5], 16) - int(self.DIM[3:5], 16)) * level)
            b = int(int(self.DIM[5:7], 16) + (int(self.LIVE[5:7], 16) - int(self.DIM[5:7], 16)) * level)
            color = f"#{r:02x}{g:02x}{b:02x}"
        self._dot.setStyleSheet(f"color: {color}; font-size: 14px;")
        if self._connected:
            tip = (f"心跳: 已发 {self._count} 拍，最后 {self._last_time}\n"
                   f"停发约 2s 后板端自动兜底停机")
        else:
            tip = "心跳: 未连接"
        self._dot.setToolTip(tip)
