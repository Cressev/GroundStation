#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
状态栏心跳呼吸灯组件

脉冲只由真实心跳发送事件驱动：通信层每成功发出一拍心跳（ping）经 Qt 信号点亮一次，
两拍之间亮度自然衰减，停止发送即沉暗，不做装饰性空闪；鼠标悬停显示累计拍数与
最后心跳时刻；连接断开时整灯转灰。
"""

import time

from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt5.QtGui import QColor, QPainter
from PyQt5.QtWidgets import QWidget


class HeartbeatSignalBridge(QObject):
    """把通信层后台线程的回调转成 Qt 信号。

    SocketCommunication 的心跳回调在后台线程触发，直接操作 QWidget 不安全；
    通过本桥发出信号并以 QueuedConnection 连接，槽在主线程执行。
    """

    #: 每成功发出一拍心跳发射一次
    beat = pyqtSignal()


class HeartbeatLight(QWidget):
    """状态栏心跳呼吸灯。

    亮度由 beat() 驱动：每一拍瞬间点亮，随后按固定比例衰减，未连接时恒为灰色。
    不做任何装饰性自动闪烁——灯不动就说明链路上没有真实心跳。
    """

    #: 衰减定时器周期（秒）
    _TICK_INTERVAL_S = 0.08
    #: 每个周期亮度保留比例（约 0.5s 一拍时衰减到 ~20% 再被下一拍点亮）
    _DECAY_PER_TICK = 0.78
    #: 未连接时的灰色
    _COLOR_GRAY = QColor("#8a8a8a")
    #: 已连接且无脉冲时的暗绿（底色）
    _COLOR_DIM = QColor("#1e5e3a")
    #: 满脉冲时的亮绿
    _COLOR_BRIGHT = QColor("#2ecc71")

    def __init__(self, parent=None):
        """构造呼吸灯：固定 16x16 逻辑像素，启动亮度衰减定时器。"""
        super().__init__(parent)
        self.setFixedSize(16, 16)
        self._level = 0.0            # 当前脉冲亮度 0..1
        self._connected = False
        self._beat_count = 0
        self._last_beat_ts = None
        self._decay_timer = QTimer(self)
        self._decay_timer.timeout.connect(self._decay_tick)
        self._decay_timer.start(int(self._TICK_INTERVAL_S * 1000))
        self._update_tooltip()

    def beat(self):
        """点亮一拍：由通信层的真实心跳事件（经 Qt 信号）调用。"""
        self._level = 1.0
        self._beat_count += 1
        self._last_beat_ts = time.time()
        self._update_tooltip()
        self.update()

    def set_connected(self, connected):
        """设置链路连接状态；断开时灯转灰并清零脉冲。"""
        self._connected = bool(connected)
        if not self._connected:
            self._level = 0.0
        self._update_tooltip()
        self.update()

    def _decay_tick(self):
        """定时衰减脉冲亮度；已沉暗时不重绘，避免无谓刷新。"""
        if self._level > 0.01:
            self._level *= self._DECAY_PER_TICK
            if self._level <= 0.01:
                self._level = 0.0
            self.update()

    def paintEvent(self, event):
        """绘制圆形指示灯：未连接灰色，已连接按脉冲亮度在暗绿-亮绿间插值。"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        if self._connected:
            t = max(0.0, min(1.0, self._level))
            color = QColor(
                round(self._COLOR_DIM.red() + (self._COLOR_BRIGHT.red() - self._COLOR_DIM.red()) * t),
                round(self._COLOR_DIM.green() + (self._COLOR_BRIGHT.green() - self._COLOR_DIM.green()) * t),
                round(self._COLOR_DIM.blue() + (self._COLOR_BRIGHT.blue() - self._COLOR_DIM.blue()) * t),
            )
        else:
            color = self._COLOR_GRAY
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(2, 2, self.width() - 5, self.height() - 5)

    def _update_tooltip(self):
        """刷新悬停提示：链路状态 + 累计拍数 + 最近一拍时刻。"""
        if self._connected:
            last_txt = ("最近一拍 " + time.strftime(
                "%H:%M:%S", time.localtime(self._last_beat_ts))
                if self._last_beat_ts else "尚无心跳")
            self.setToolTip(f"控制链路心跳: 已连接\n累计 {self._beat_count} 拍\n{last_txt}")
        else:
            self.setToolTip("控制链路心跳: 未连接")
