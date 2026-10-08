#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""深度面板：实时显示 WF5803 深度传感器数据，支持 CSV 记录。

数据源：板上 gs_bridge（TCP 9999），10Hz 推送 JSON：
  {"type": "depth", "raw_1": .., "filtered_1": .., "fused": .., "timestamp": ..}

面板内容：
  - 大字号实时深度值（filtered_1/fused）
  - 原始值/融合值小字显示
  - 记录开始/停止按钮：停止后弹出对话框选择 CSV 保存位置
"""

import csv
import datetime
import json
import os
import socket
import threading
import time

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (QDialog, QFileDialog, QGridLayout, QGroupBox,
                             QHBoxLayout, QLabel, QMessageBox, QPushButton,
                             QVBoxLayout, QWidget)


class DepthTcpClient(QThread):
    """gs_bridge 深度/状态 JSON 接收线程。

    收到的每行 JSON 通过信号发出（depth/state 两类）。
    """

    line_received = pyqtSignal(dict)
    connection_status = pyqtSignal(bool, str)

    def __init__(self, host, port=9999):
        """初始化线程（不自动启动）。"""
        super().__init__()
        self.host = host
        self.port = port
        self.running = False
        self.socket = None

    def run(self):
        """接收主循环：按行切分 JSON 并发射信号。"""
        self.running = True
        try:
            self.socket = socket.create_connection((self.host, self.port), timeout=5)
            self.socket.settimeout(1.0)
            self.connection_status.emit(True, f"已连接 {self.host}:{self.port}")
            buf = b""
            while self.running:
                try:
                    data = self.socket.recv(65536)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not data:
                    break
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if line.startswith(b"{"):
                        try:
                            info = json.loads(line.decode("utf-8", "ignore"))
                            self.line_received.emit(info)
                        except ValueError:
                            pass
        except OSError as exc:
            self.connection_status.emit(False, f"连接失败: {exc}")
        finally:
            if self.socket:
                self.socket.close()
            self.connection_status.emit(False, "连接已断开")

    def stop(self):
        """停止接收线程。"""
        self.running = False
        if self.socket:
            try:
                self.socket.close()
            except OSError:
                pass


class DepthPanel(QWidget):
    """深度实时显示与记录面板。"""

    def __init__(self, host, parent=None):
        """初始化面板并连接数据源。"""
        super().__init__(parent)
        self.host = host
        self.client = DepthTcpClient(host)
        self.recording = False
        self.records = []
        self._init_ui()
        self._init_connections()

    def set_host(self, host):
        """切换数据源地址（断开当前连接，下次连接生效）。"""
        if self.client.running:
            self._disconnect()
        self.host = host
        self.client.host = host
        self.conn_status_label.setText(f"状态: 未连接（数据源 {host}:9999）")

    def _init_ui(self):
        """构建界面：连接控制 + 实时数值 + 记录控制。"""
        layout = QVBoxLayout(self)

        title = QLabel("深度（WF5803 深度传感器）")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(QFont("Arial", 14, QFont.Bold))
        layout.addWidget(title)

        conn_group = QGroupBox("连接")
        conn_layout = QHBoxLayout(conn_group)
        self.connect_btn = QPushButton("连接深度数据")
        self.connect_btn.clicked.connect(self._toggle_connection)
        self.disconnect_btn = QPushButton("断开")
        self.disconnect_btn.clicked.connect(self._disconnect)
        self.disconnect_btn.setEnabled(False)
        conn_layout.addWidget(self.connect_btn)
        conn_layout.addWidget(self.disconnect_btn)
        conn_layout.addStretch()
        self.conn_status_label = QLabel("状态: 未连接")
        conn_layout.addWidget(self.conn_status_label)
        layout.addWidget(conn_group)

        value_group = QGroupBox("实时深度")
        value_layout = QGridLayout(value_group)
        self.depth_big_label = QLabel("--.-- m")
        self.depth_big_label.setAlignment(Qt.AlignCenter)
        self.depth_big_label.setFont(QFont("Arial", 36, QFont.Bold))
        value_layout.addWidget(self.depth_big_label, 0, 0, 1, 2)
        self.raw_label = QLabel("原始: --")
        self.filtered_label = QLabel("滤波: --")
        self.fused_label = QLabel("融合: --")
        for col, label in enumerate([self.raw_label, self.filtered_label,
                                     self.fused_label]):
            label.setFont(QFont("Arial", 10))
            value_layout.addWidget(label, 1, col)
        layout.addWidget(value_group)

        record_group = QGroupBox("数据记录（CSV）")
        record_layout = QHBoxLayout(record_group)
        self.record_btn = QPushButton("开始记录")
        self.record_btn.setEnabled(False)
        self.record_btn.clicked.connect(self._toggle_recording)
        self.record_status_label = QLabel("记录状态: 未记录")
        record_layout.addWidget(self.record_btn)
        record_layout.addWidget(self.record_status_label)
        record_layout.addStretch()
        layout.addWidget(record_group)
        layout.addStretch()

    def _init_connections(self):
        """连接信号。"""
        self.client.line_received.connect(self._on_line, Qt.QueuedConnection)
        self.client.connection_status.connect(self._on_connection_status,
                                              Qt.QueuedConnection)

    def _toggle_connection(self):
        """连接/断开深度数据流。"""
        if self.client.running:
            self.client.stop()
            self.client.wait()
            self.connect_btn.setEnabled(True)
            self.disconnect_btn.setEnabled(False)
            self.record_btn.setEnabled(False)
        else:
            self.client.start()
            self.connect_btn.setEnabled(False)
            self.disconnect_btn.setEnabled(True)
            self.record_btn.setEnabled(True)

    def _disconnect(self):
        """断开深度数据流。"""
        self.client.stop()
        self.client.wait()
        self.connect_btn.setEnabled(True)
        self.disconnect_btn.setEnabled(False)
        self.record_btn.setEnabled(False)

    def _toggle_recording(self):
        """开始/停止 CSV 记录。停止后弹出保存对话框。"""
        if not self.client.running:
            return
        if not self.recording:
            self.records = []
            self.recording = True
            self.record_btn.setText("停止记录")
            self.record_status_label.setText("记录状态: 记录中…")
        else:
            self._stop_recording()

    def _stop_recording(self):
        """停止 CSV 记录并弹出保存对话框。"""
        self.recording = False
        self.record_btn.setText("开始记录")
        rows = getattr(self, "records", [])
        default_name = f"depth_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        path, _ = QFileDialog.getSaveFileName(
            self, "保存深度记录", default_name, "CSV 数据 (*.csv)")
        if not path:
            path = os.path.join("records", default_name)
        if not path.lower().endswith(".csv"):
            path += ".csv"
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["时间", "原始 raw_1", "滤波 filtered_1", "融合 fused"])
            writer.writerows(rows)
        self.record_status_label.setText(f"记录状态: 已保存 {os.path.basename(path)}")
        QMessageBox.information(self, "深度记录已保存",
                                f"共 {len(rows)} 条记录\n已保存到:\n{path}")

    def _on_line(self, info):
        """处理一行 JSON（深度/状态）。"""
        msg_type = info.get("type")
        if msg_type == "depth":
            fused = info.get("fused")
            if fused is None:
                self.depth_big_label.setText("--.-- m")
            else:
                self.depth_big_label.setText(f"{fused:.2f} m")
            self.raw_label.setText(f"原始: {info.get('raw_1', 0):.3f}")
            self.filtered_label.setText(f"滤波: {info.get('filtered_1', 0):.3f}")
            self.fused_label.setText(f"融合: {info.get('fused', 0):.3f}")
            if self.recording:
                now = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
                self.records.append([now, info.get("raw_1"),
                                     info.get("filtered_1"), info.get("fused")])
        elif msg_type == "state":
            pass

    def _on_connection_status(self, connected, message):
        """更新连接状态标签。"""
        self.conn_status_label.setText(
            f"状态: {'已连接' if connected else '未连接'} ({message})")

    def closeEvent(self, event):
        """组件销毁时停止数据接收线程。"""
        if self.client.running:
            self.client.stop()
            self.client.wait()
        event.accept()
