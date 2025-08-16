#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
视频显示组件
Video Display Component
"""

import cv2
import numpy as np
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, 
                             QLabel, QPushButton, QComboBox, QFrame, QMessageBox)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QThread, pyqtSlot
from PyQt5.QtGui import QImage, QPixmap, QFont

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import VIDEO_CONFIG

class CameraThread(QThread):
    """摄像头线程类"""
    
    frame_ready = pyqtSignal(np.ndarray)
    error_occurred = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self.camera = None
        self.camera_index = -1
        self.running = False
        self.frame_width = VIDEO_CONFIG["default_resolution"][0]
        self.frame_height = VIDEO_CONFIG["default_resolution"][1]
        
    def set_camera_index(self, index: int):
        """设置摄像头索引"""
        self.camera_index = index
        
    def start_capture(self):
        """开始捕获"""
        if self.camera_index >= 0:
            self.running = True
            self.start()
        
    def stop_capture(self):
        """停止捕获"""
        self.running = False
        if self.camera and self.camera.isOpened():
            self.camera.release()
        self.wait()
        
    def run(self):
        """线程运行函数"""
        try:
            # 初始化摄像头
            self.camera = cv2.VideoCapture(self.camera_index)
            if not self.camera.isOpened():
                self.error_occurred.emit(f"无法打开摄像头 {self.camera_index}")
                return
            
            # 设置摄像头参数
            self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, self.frame_width)
            self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, self.frame_height)
            self.camera.set(cv2.CAP_PROP_FPS, VIDEO_CONFIG["video_update_rate"])
            
            while self.running:
                ret, frame = self.camera.read()
                if ret:
                    # 发射帧信号
                    self.frame_ready.emit(frame)
                else:
                    self.error_occurred.emit("读取摄像头帧失败")
                    break
                    
                self.msleep(33)  # 约30FPS
                
        except Exception as e:
            self.error_occurred.emit(f"摄像头线程异常: {str(e)}")
        finally:
            if self.camera and self.camera.isOpened():
                self.camera.release()

class VideoDisplayWidget(QWidget):
    """视频显示组件"""
    
    def __init__(self):
        super().__init__()
        self.camera_thread = CameraThread()
        self.available_cameras = []
        self.current_frame = None
        
        self._init_ui()
        self._detect_cameras()
        self._init_connections()
        
    def _init_ui(self):
        """初始化用户界面"""
        layout = QVBoxLayout(self)
        
        # 标题
        title = QLabel("视频监控")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(QFont("Arial", 14, QFont.Bold))
        layout.addWidget(title)
        
        # 摄像头控制组
        control_group = QGroupBox("摄像头控制")
        control_layout = QHBoxLayout(control_group)
        
        # 摄像头选择
        control_layout.addWidget(QLabel("选择摄像头:"))
        self.camera_combo = QComboBox()
        self.camera_combo.currentIndexChanged.connect(self._on_camera_changed)
        control_layout.addWidget(self.camera_combo)
        
        # 控制按钮
        self.start_btn = QPushButton("开启")
        self.start_btn.clicked.connect(self._start_camera)
        self.stop_btn = QPushButton("停止")
        self.stop_btn.clicked.connect(self._stop_camera)
        self.stop_btn.setEnabled(False)
        
        control_layout.addWidget(self.start_btn)
        control_layout.addWidget(self.stop_btn)
        
        # 刷新按钮
        refresh_btn = QPushButton("刷新设备")
        refresh_btn.clicked.connect(self._detect_cameras)
        control_layout.addWidget(refresh_btn)
        
        control_layout.addStretch()
        layout.addWidget(control_group)
        
        # 视频显示区域
        video_group = QGroupBox("视频画面")
        video_layout = QVBoxLayout(video_group)
        
        # 视频标签
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
        self.video_label.setText("摄像头未启动\n点击'开启'按钮开始视频")
        
        video_layout.addWidget(self.video_label)
        layout.addWidget(video_group)
        
        # 状态信息组
        status_group = QGroupBox("状态信息")
        status_layout = QVBoxLayout(status_group)
        
        self.status_label = QLabel("摄像头状态: 未连接")
        self.status_label.setFont(QFont("Arial", 10))
        
        self.resolution_label = QLabel("分辨率: --")
        self.resolution_label.setFont(QFont("Arial", 10))
        
        self.fps_label = QLabel("帧率: --")
        self.fps_label.setFont(QFont("Arial", 10))
        
        status_layout.addWidget(self.status_label)
        status_layout.addWidget(self.resolution_label)
        status_layout.addWidget(self.fps_label)
        
        layout.addWidget(status_group)
        
        layout.addStretch()
        
    def _init_connections(self):
        """初始化信号连接"""
        self.camera_thread.frame_ready.connect(self._update_frame)
        self.camera_thread.error_occurred.connect(self._handle_error)
        
    def _detect_cameras(self):
        """检测可用摄像头"""
        self.available_cameras.clear()
        self.camera_combo.clear()
        
        # 检测摄像头设备
        for i in range(VIDEO_CONFIG["max_cameras"]):
            try:
                cap = cv2.VideoCapture(i)
                if cap.isOpened():
                    # 尝试读取一帧来确认摄像头工作
                    ret, _ = cap.read()
                    if ret:
                        # 获取摄像头信息
                        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                        fps = int(cap.get(cv2.CAP_PROP_FPS))
                        
                        camera_info = {
                            'index': i,
                            'name': f"摄像头 {i}",
                            'resolution': f"{width}x{height}",
                            'fps': fps
                        }
                        
                        self.available_cameras.append(camera_info)
                        display_text = f"{camera_info['name']} ({camera_info['resolution']})"
                        self.camera_combo.addItem(display_text, i)
                        
                cap.release()
            except Exception as e:
                continue
        
        if not self.available_cameras:
            self.camera_combo.addItem("未检测到摄像头", -1)
            self.start_btn.setEnabled(False)
            self.status_label.setText("摄像头状态: 未检测到设备")
        else:
            self.start_btn.setEnabled(True)
            self.status_label.setText(f"摄像头状态: 检测到 {len(self.available_cameras)} 个设备")
            
        self._log_camera_info()
        
    def _log_camera_info(self):
        """记录摄像头信息"""
        if self.available_cameras:
            print("检测到的摄像头设备:")
            for camera in self.available_cameras:
                print(f"  - {camera['name']}: {camera['resolution']}, {camera['fps']} FPS")
        else:
            print("未检测到可用的摄像头设备")
    
    def _on_camera_changed(self, index):
        """摄像头选择改变"""
        if 0 <= index < len(self.available_cameras):
            camera_info = self.available_cameras[index]
            self.resolution_label.setText(f"分辨率: {camera_info['resolution']}")
            self.fps_label.setText(f"帧率: {camera_info['fps']} FPS")
    
    def _start_camera(self):
        """启动摄像头"""
        current_index = self.camera_combo.currentIndex()
        if current_index >= 0 and current_index < len(self.available_cameras):
            camera_index = self.available_cameras[current_index]['index']
            
            # 设置摄像头索引并启动
            self.camera_thread.set_camera_index(camera_index)
            self.camera_thread.start_capture()
            
            # 更新UI状态
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.camera_combo.setEnabled(False)
            self.status_label.setText("摄像头状态: 运行中")
            
            print(f"启动摄像头 {camera_index}")
        else:
            QMessageBox.warning(self, "警告", "请选择有效的摄像头设备")
    
    def _stop_camera(self):
        """停止摄像头"""
        self.camera_thread.stop_capture()
        
        # 更新UI状态
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.camera_combo.setEnabled(True)
        self.status_label.setText("摄像头状态: 已停止")
        
        # 清空视频显示
        self.video_label.clear()
        self.video_label.setText("摄像头已停止\n点击'开启'按钮重新开始")
        
        print("摄像头已停止")
    
    @pyqtSlot(np.ndarray)
    def _update_frame(self, frame):
        """更新视频帧"""
        try:
            # 转换颜色格式 (BGR -> RGB)
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            # 获取帧尺寸
            h, w, ch = rgb_frame.shape
            bytes_per_line = ch * w
            
            # 创建QImage
            qt_image = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format_RGB888)
            
            # 缩放图像以适应标签大小
            label_size = self.video_label.size()
            scaled_image = qt_image.scaled(
                label_size.width() - 10, 
                label_size.height() - 10, 
                Qt.KeepAspectRatio, 
                Qt.SmoothTransformation
            )
            
            # 转换为QPixmap并显示
            pixmap = QPixmap.fromImage(scaled_image)
            self.video_label.setPixmap(pixmap)
            
            # 保存当前帧
            self.current_frame = frame
            
        except Exception as e:
            self._handle_error(f"更新视频帧失败: {str(e)}")
    
    @pyqtSlot(str)
    def _handle_error(self, error_message):
        """处理错误"""
        print(f"摄像头错误: {error_message}")
        self.status_label.setText(f"摄像头状态: 错误 - {error_message}")
        
        # 如果是严重错误，停止摄像头
        if "无法打开" in error_message or "读取" in error_message:
            self._stop_camera()
    
    def get_current_frame(self):
        """获取当前帧"""
        return self.current_frame
    
    def save_snapshot(self, filename=None):
        """保存快照"""
        if self.current_frame is not None:
            if filename is None:
                import datetime
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"snapshot_{timestamp}.jpg"
            
            cv2.imwrite(filename, self.current_frame)
            return filename
        return None
    
    def closeEvent(self, event):
        """窗口关闭事件"""
        self._stop_camera()
        event.accept()
