#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
机载相机显示组件
Fish Onboard Camera Widget
"""

import cv2
import numpy as np
import datetime
import json
import os
import time
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QGroupBox, QMessageBox)
from PyQt5.QtCore import QThread, pyqtSignal, Qt, pyqtSlot
from PyQt5.QtGui import QImage, QPixmap, QFont
import socket
import struct

import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import FISH_IP

class CameraStreamClient(QThread):
    """机器鱼摄像头视频流接收线程"""
    frame_received = pyqtSignal(np.ndarray)
    connection_status = pyqtSignal(bool, str)  # (connected, message)
    message_received = pyqtSignal(str)         # 机上JSON消息(录制开始/保存完成通知)
    
    def __init__(self):
        super().__init__()
        self.running = False
        self.socket = None
        self.host = None
        self.port = 9998
        
    def set_connection(self, host: str, port: int = 9998):
        """设置连接参数"""
        self.host = host
        self.port = port
        
    def _recv_all(self, size):
        """接收指定大小的数据"""
        data = b''
        while len(data) < size:
            packet = self.socket.recv(size - len(data))
            if not packet:
                return None
            data += packet
        return data
    
    def send_command(self, cmd: str):
        """向机上发送命令(如REC_START/REC_STOP)
        TCP全双工, 与接收线程的recv并发安全
        """
        if self.socket:
            try:
                self.socket.sendall((cmd.strip() + "\n").encode('utf-8'))
            except Exception as e:
                print(f"发送命令失败: {e}")

    def run(self):
        """线程运行函数"""
        self.running = True

        try:
            # 创建Socket连接
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(5.0)
            self.socket.connect((self.host, self.port))
            self.connection_status.emit(True, f"已连接到 {self.host}:{self.port}")

            while self.running:
                try:
                    # 接收消息长度 (4字节，网络字节序)
                    size_data = self._recv_all(4)
                    if not size_data:
                        break

                    size = struct.unpack("!I", size_data)[0]

                    # 接收消息数据 (首字节为类型: 0xFF=JPEG帧, 0xFE=JSON消息)
                    payload = self._recv_all(size)
                    if not payload:
                        break

                    msg_type, body = payload[0], payload[1:]

                    if msg_type == 0xFF:
                        # 解码JPEG
                        frame = cv2.imdecode(
                            np.frombuffer(body, np.uint8),
                            cv2.IMREAD_COLOR
                        )

                        if frame is not None:
                            # 鱼眼相机在鱼体上为倒装安装，画面旋转180°矫正
                            frame = cv2.rotate(frame, cv2.ROTATE_180)
                            self.frame_received.emit(frame)
                    elif msg_type == 0xFE:
                        self.message_received.emit(body.decode('utf-8', 'ignore'))

                except socket.timeout:
                    continue
                except Exception as e:
                    print(f"接收错误: {e}")
                    break

        except Exception as e:
            self.connection_status.emit(False, f"连接失败: {str(e)}")
        finally:
            if self.socket:
                self.socket.close()
            self.connection_status.emit(False, "连接已断开")
            
    def stop(self):
        """停止线程"""
        self.running = False
        if self.socket:
            try:
                self.socket.shutdown(socket.SHUT_RDWR)
                self.socket.close()
            except:
                pass


class FishCameraWidget(QWidget):
    """机载相机显示组件"""
    
    def __init__(self):
        super().__init__()
        self.stream_client = CameraStreamClient()
        self.current_frame = None
        self.recording = False
        # 实际帧率统计(每秒刷新一次)
        self._fps_count = 0
        self._fps_t0 = time.time()
        self._init_ui()
        self._init_connections()
        
    def _init_ui(self):
        """初始化用户界面"""
        layout = QVBoxLayout(self)
        
        # 标题
        title = QLabel("机载相机")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(QFont("Arial", 14, QFont.Bold))
        layout.addWidget(title)
        
        # 控制组
        control_group = QGroupBox("连接控制")
        control_layout = QHBoxLayout(control_group)
        
        # 连接按钮
        self.connect_btn = QPushButton("连接")
        self.connect_btn.clicked.connect(self._toggle_connection)
        self.disconnect_btn = QPushButton("断开")
        self.disconnect_btn.clicked.connect(self._disconnect)
        self.disconnect_btn.setEnabled(False)
        
        control_layout.addWidget(self.connect_btn)
        control_layout.addWidget(self.disconnect_btn)
        
        # 录制按钮
        self.record_btn = QPushButton("开始录制")
        self.record_btn.clicked.connect(self._toggle_recording)
        self.record_btn.setEnabled(False)
        self.record_btn.setToolTip(
            "高清视频(1280x960@30)直接保存在机器鱼上, 不占用Wi-Fi带宽")
        control_layout.addWidget(self.record_btn)
        
        control_layout.addStretch()
        layout.addWidget(control_group)
        
        # 视频显示区域
        video_group = QGroupBox("视频画面")
        video_layout = QVBoxLayout(video_group)
        
        self.video_label = QLabel()
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setMinimumSize(320, 240)
        self.video_label.setStyleSheet("""
            QLabel {
                border: 2px solid #ccc;
                background-color: #f0f0f0;
                border-radius: 5px;
            }
        """)
        self.video_label.setText("未连接到机器鱼<br>点击'连接'按钮开始视频流")
        
        video_layout.addWidget(self.video_label)
        layout.addWidget(video_group)
        
        # 状态信息组
        status_group = QGroupBox("状态信息")
        status_layout = QVBoxLayout(status_group)
        
        self.status_label = QLabel("连接状态: 未连接")
        self.status_label.setFont(QFont("Arial", 10))
        
        self.resolution_label = QLabel("分辨率: --")
        self.resolution_label.setFont(QFont("Arial", 10))
        
        self.fps_label = QLabel("帧率: --")
        self.fps_label.setFont(QFont("Arial", 10))
        
        self.recording_label = QLabel("录制状态: 未录制")
        self.recording_label.setFont(QFont("Arial", 10))
        
        status_layout.addWidget(self.status_label)
        status_layout.addWidget(self.resolution_label)
        status_layout.addWidget(self.fps_label)
        status_layout.addWidget(self.recording_label)
        
        layout.addWidget(status_group)
        layout.addStretch()
        
    def _init_connections(self):
        """初始化信号连接"""
        # 使用QueuedConnection确保线程安全
        self.stream_client.frame_received.connect(self._update_frame, Qt.QueuedConnection)
        self.stream_client.connection_status.connect(self._on_connection_status, Qt.QueuedConnection)
        self.stream_client.message_received.connect(self._on_fish_message, Qt.QueuedConnection)
        
    def _toggle_connection(self):
        """连接"""
        if not self.stream_client.running:
            # 获取机器鱼IP
            fish_ip = self._get_fish_ip()
            if not fish_ip:
                QMessageBox.warning(self, "错误", "无法获取机器鱼IP地址\\n请先在主界面连接机器鱼")
                return
                
            self.stream_client.set_connection(fish_ip, 9998)
            self.stream_client.start()
            self.connect_btn.setEnabled(False)
            self.disconnect_btn.setEnabled(True)
            self.record_btn.setEnabled(False)  # 连接成功后才启用
            self.status_label.setText("连接状态: 连接中...")
            
    def _disconnect(self):
        """断开连接"""
        # 如果正在录制，先停止录制
        if self.recording:
            self._stop_recording()
            
        self.stream_client.stop()
        self.stream_client.wait()
        self.connect_btn.setEnabled(True)
        self.disconnect_btn.setEnabled(False)
        self.record_btn.setEnabled(False)
        
    def _toggle_recording(self):
        """切换录制状态 (高清录制在机器鱼上进行, 不经Wi-Fi)"""
        if self.recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self):
        """开始机上录制: 发送REC_START命令"""
        if not self.stream_client.running:
            QMessageBox.warning(self, "录制失败", "请先连接机器鱼")
            return
        self.stream_client.send_command("REC_START")
        self.recording = True
        self.record_btn.setText("停止录制")
        self.recording_label.setText("录制状态: 机上录制中 (1280x960@30, 存储在机器鱼上)")
        print("已发送机上录制开始命令")

    def _stop_recording(self):
        """停止机上录制: 发送REC_STOP命令, 保存完成后会收到机上回传通知"""
        if not self.recording:
            return
        self.recording = False
        self.stream_client.send_command("REC_STOP")
        self.record_btn.setText("开始录制")
        self.recording_label.setText("录制状态: 正在机器鱼上保存...")
        print("已发送机上录制停止命令")

    @pyqtSlot(str)
    def _on_fish_message(self, text: str):
        """处理机上回传的JSON消息(录制开始/保存完成通知)"""
        print(f"机上消息: {text}")
        try:
            info = json.loads(text)
        except (ValueError, TypeError):
            return
        event = info.get("event")
        if event == "rec_started":
            self.recording_label.setText("录制状态: 机上录制中...")
        elif event == "rec_saved":
            self.recording_label.setText("录制状态: 未录制")
            file_path = info.get('file', '')
            QMessageBox.information(
                self, "录制完成",
                f"高清视频已保存在机器鱼上:\n{file_path}\n\n"
                f"帧数: {info.get('frames', 0)}  时长: {info.get('duration', 0)}秒\n\n"
                "取回到电脑示例(任意终端执行):\n"
                f'scp orangepi:"{file_path}" %USERPROFILE%\\Desktop\\')
        
    def _get_fish_ip(self):
        """获取机器鱼IP地址"""
        try:
            main_window = self.window()
            if hasattr(main_window, 'ip_input'):
                return main_window.ip_input.text()
        except:
            pass
        return FISH_IP
        
    @pyqtSlot(np.ndarray)
    def _update_frame(self, frame):
        """更新视频帧"""
        try:
            self.current_frame = frame

            # 统计实际收到并显示的帧率, 每秒刷新一次
            self._fps_count += 1
            now = time.time()
            if now - self._fps_t0 >= 1.0:
                fps = self._fps_count / (now - self._fps_t0)
                self.fps_label.setText(f"帧率: {fps:.1f} FPS")
                self._fps_count = 0
                self._fps_t0 = now

            # 转换为Qt格式显示
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb_frame.shape
            bytes_per_line = ch * w
            qt_image = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format_RGB888)
            
            # 更新分辨率标签
            self.resolution_label.setText(f"分辨率: {w}x{h}")
            
            # 缩放显示
            label_size = self.video_label.size()
            scaled_image = qt_image.scaled(
                label_size.width() - 10,
                label_size.height() - 10,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            
            pixmap = QPixmap.fromImage(scaled_image)
            self.video_label.setPixmap(pixmap)
        except Exception as e:
            print(f"更新视频帧异常: {e}")
        
    @pyqtSlot(bool, str)
    def _on_connection_status(self, connected, message):
        """连接状态改变"""
        try:
            if connected:
                self.status_label.setText("连接状态: 已连接")
                self.record_btn.setEnabled(True)
                print(f"机载相机已连接: {message}")
            else:
                self.status_label.setText("连接状态: 未连接")
                self.record_btn.setEnabled(False)
                self.resolution_label.setText("分辨率: --")
                self.video_label.clear()
                self.video_label.setText(f"连接已断开<br>{message}")
                print(f"机载相机断开: {message}")
                if self.recording:
                    # 连接断开时机上会自动保存已录内容
                    self.recording = False
                    self.record_btn.setText("开始录制")
                    self.recording_label.setText("录制状态: 连接断开, 机上录制已自动保存")
        except Exception as e:
            print(f"连接状态更新异常: {e}")
            
    def closeEvent(self, event):
        """窗口关闭事件"""
        if self.recording:
            self._stop_recording()
        if self.stream_client.running:
            self.stream_client.stop()
            self.stream_client.wait()
        event.accept()
