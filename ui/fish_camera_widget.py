#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
机载相机显示组件
Fish Onboard Camera Widget
"""

import cv2
import numpy as np
import datetime
import os
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QGroupBox, QMessageBox, QFileDialog)
from PyQt5.QtCore import QThread, pyqtSignal, Qt, pyqtSlot
from PyQt5.QtGui import QImage, QPixmap, QFont
import socket
import struct

import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import VIDEO_CONFIG

class CameraStreamClient(QThread):
    """机器鱼摄像头视频流接收线程"""
    frame_received = pyqtSignal(np.ndarray)
    connection_status = pyqtSignal(bool, str)  # (connected, message)
    
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
                    # 接收帧大小 (4字节，网络字节序)
                    size_data = self._recv_all(4)
                    if not size_data:
                        break
                        
                    size = struct.unpack("!I", size_data)[0]
                    
                    # 接收帧数据
                    img_data = self._recv_all(size)
                    if not img_data:
                        break
                    
                    # 解码JPEG
                    frame = cv2.imdecode(
                        np.frombuffer(img_data, np.uint8), 
                        cv2.IMREAD_COLOR
                    )
                    
                    if frame is not None:
                        self.frame_received.emit(frame)
                        
                except socket.timeout:
                    continue
                except Exception as e:
                    print(f"接收帧错误: {e}")
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
        self.video_writer = None
        self.recording = False
        self.recording_start_time = None
        self.recording_frame_count = 0
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
        control_layout.addWidget(self.record_btn)
        
        control_layout.addStretch()
        layout.addWidget(control_group)
        
        # 视频显示区域
        video_group = QGroupBox("视频画面")
        video_layout = QVBoxLayout(video_group)
        
        self.video_label = QLabel()
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setMinimumSize(640, 480)
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
        
        self.fps_label = QLabel("帧率: ~17 FPS")
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
        """切换录制状态"""
        if self.recording:
            # 停止录制时选择保存目录
            save_dir = self._get_video_save_directory("选择视频保存目录")
            if save_dir:
                self._stop_recording(save_dir)
            else:
                print("用户取消选择保存目录，继续录制")
        else:
            # 开始录制
            self._start_recording()
            
    def _start_recording(self):
        """开始录制"""
        if self.current_frame is None:
            QMessageBox.warning(self, "录制失败", "没有可录制的视频帧")
            return
            
        try:
            # 创建临时目录
            temp_dir = "temp_records"
            if not os.path.exists(temp_dir):
                os.makedirs(temp_dir)
            
            # 生成文件名
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            self.temp_filename = f"fish_camera_{timestamp}.avi"
            temp_filepath = os.path.join(temp_dir, self.temp_filename)
            
            # 获取帧尺寸
            h, w = self.current_frame.shape[:2]
            
            # 创建VideoWriter
            fourcc = cv2.VideoWriter_fourcc(*VIDEO_CONFIG["record_codec"])
            self.video_writer = cv2.VideoWriter(
                temp_filepath,
                fourcc,
                VIDEO_CONFIG["record_fps"],
                (w, h)
            )
            
            if self.video_writer.isOpened():
                self.recording = True
                self.recording_start_time = datetime.datetime.now()
                self.recording_frame_count = 0
                self.record_btn.setText("停止录制")
                self.recording_label.setText("录制状态: 录制中...")
                self.connect_btn.setEnabled(False)
                self.disconnect_btn.setEnabled(False)
                print(f"开始录制: {temp_filepath}")
            else:
                QMessageBox.warning(self, "录制失败", "无法创建视频文件")
                
        except Exception as e:
            QMessageBox.warning(self, "录制失败", f"错误: {str(e)}")
            
    def _stop_recording(self, save_dir=None):
        """停止录制并保存"""
        if not self.recording:
            return
            
        self.recording = False
        
        if self.video_writer:
            try:
                self.video_writer.release()
            except Exception as e:
                print(f"释放VideoWriter异常: {e}")
            finally:
                self.video_writer = None
        
        # 移动文件到目标目录
        if save_dir:
            try:
                temp_filepath = os.path.join("temp_records", self.temp_filename)
                if os.path.exists(temp_filepath):
                    # 确保目标目录存在
                    os.makedirs(save_dir, exist_ok=True)
                    
                    target_path = os.path.join(save_dir, self.temp_filename)
                    
                    # 移动文件
                    import shutil
                    shutil.move(temp_filepath, target_path)
                    
                    if self.recording_start_time:
                        duration = datetime.datetime.now() - self.recording_start_time
                        print(f"录制完成: {target_path}")
                        print(f"时长: {duration.total_seconds():.1f}秒, 帧数: {self.recording_frame_count}")
                        QMessageBox.information(self, "录制完成", 
                            f"视频已保存到:\\n{target_path}\\n\\n时长: {duration.total_seconds():.1f}秒\\n帧数: {self.recording_frame_count}")
            except Exception as e:
                print(f"保存视频失败: {e}")
                QMessageBox.warning(self, "保存失败", f"无法保存视频: {str(e)}")
        
        self.record_btn.setText("开始录制")
        self.recording_label.setText("录制状态: 未录制")
        self.connect_btn.setEnabled(True)
        self.disconnect_btn.setEnabled(True)
        
    def _get_fish_ip(self):
        """获取机器鱼IP地址"""
        try:
            main_window = self.window()
            if hasattr(main_window, 'ip_input'):
                return main_window.ip_input.text()
        except:
            pass
        return "192.168.137.241"
        
    @pyqtSlot(np.ndarray)
    def _update_frame(self, frame):
        """更新视频帧"""
        try:
            self.current_frame = frame
            
            # 如果正在录制，保存帧
            if self.recording and self.video_writer:
                self.video_writer.write(frame)
                self.recording_frame_count += 1
            
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
        except Exception as e:
            print(f"连接状态更新异常: {e}")
            
    def _get_video_save_directory(self, title: str) -> str:
        """获取视频保存目录"""
        default_dir = f"records/{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        parent_dir = os.path.dirname(default_dir)
        if parent_dir and not os.path.exists(parent_dir):
            try:
                os.makedirs(parent_dir, exist_ok=True)
            except Exception as e:
                print(f"创建父目录失败: {e}")
                default_dir = "."
        
        selected_dir = QFileDialog.getExistingDirectory(
            self,
            title,
            default_dir,
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks
        )
        
        if selected_dir:
            try:
                os.makedirs(selected_dir, exist_ok=True)
                print(f"选择的视频保存目录: {selected_dir}")
                return selected_dir
            except Exception as e:
                print(f"创建选择的目录失败: {e}")
                return None
        return None
            
    def closeEvent(self, event):
        """窗口关闭事件"""
        if self.recording:
            self._stop_recording()
        if self.stream_client.running:
            self.stream_client.stop()
            self.stream_client.wait()
        event.accept()
