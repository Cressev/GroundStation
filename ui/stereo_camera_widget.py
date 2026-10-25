#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
双尾双目鱼机载双目视频组件
Stereo Fish Onboard Camera Widget

接收同帧双目JPEG与绑定标定，电脑后台执行SGBM/WLS，只显示左校正图。
点击只读取当前显示帧的点云，不发送板端测距命令；截图/视频只保存单目。
旧单目流仍可预览，但没有双目和标定时禁止测距。
"""

import stereo_runtime
import cv2
import numpy as np
import json
import os
import sys
import time
import socket
import struct
import datetime
import shutil
import tempfile
import threading
import hashlib

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QGroupBox, QMessageBox, QGridLayout,
                             QFileDialog, QSizePolicy, QScrollArea, QFrame, QLineEdit, QComboBox)
from PyQt5.QtCore import QThread, QTimer, pyqtSignal, Qt, pyqtSlot, QSettings
from PyQt5.QtGui import QImage, QPixmap, QFont

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (DUAL_FISH_CONFIG, STEREO_PREVIEW_LAYOUT,
                    STEREO_RANGING_UI_ENABLED)
from stereo.transport import (MAX_PACKET, STEREO_FRAME, CALIBRATION,
                              decode_blob, receive_exact)
from stereo.calculation import (StereoCalculator, StereoPreview, display_to_rectified,
                                measure_depth, MAX_CALIBRATION_BYTES)
from stereo.worker import StereoWorker
from ui.numeric_inputs import NoWheelSpinBox

# 画布布局常量（与 pico_stereo.stereo_lib 保持一致）
CANVAS_W, CANVAS_H = 1280, 960
LEFT_RECT_W, LEFT_RECT_H = 640, 480
FAST_PREVIEW_GAMMA = 2.0
DEFAULT_VIDEO_CANVAS_HEIGHT = 720
FAST_PREVIEW_LUT = np.array([
    ((value / 255.0) ** (1.0 / FAST_PREVIEW_GAMMA)) * 255.0
    for value in range(256)
], dtype=np.uint8)


def prepare_stereo_display_frame(frame, layout=STEREO_PREVIEW_LAYOUT):
    """把板端原始单目帧转正提亮；旧双目横拼流只取第一目。"""
    height, width = frame.shape[:2]
    if layout == "processed":
        return frame
    if layout == "raw_sbs" or (
            layout not in ("raw_single", "processed") and
            width >= height * 2 and width % 2 == 0):
        frame = frame[:, :width // 2]
    single = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
    return cv2.LUT(single, FAST_PREVIEW_LUT)


class SingleViewLabel(QLabel):
    """Keep the displayed pixmap and click rectangle identical through resizes."""

    def __init__(self):
        """Retain a detached image rather than a NumPy-backed temporary buffer."""
        super().__init__()
        self._image = None
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)

    def set_frame(self, frame):
        """Copy one BGR view into Qt-owned storage."""
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        height, width = rgb.shape[:2]
        self._image = QImage(rgb.data, width, height, rgb.strides[0], QImage.Format_RGB888).copy()
        self._rescale()

    def _rescale(self):
        """Fit inside contentsRect, retaining black margins outside the pixmap."""
        if self._image is not None:
            area = self.contentsRect()
            scaled = self._image.scaled(max(1, area.width()-12), max(1, area.height()-12),
                                        Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.setPixmap(QPixmap.fromImage(scaled))

    def image_rectangle(self):
        """Return exactly where the centered pixmap is painted in label coordinates."""
        pixmap, area = self.pixmap(), self.contentsRect()
        if pixmap is None or pixmap.isNull():
            return 0, 0, 0, 0
        width = pixmap.width()/pixmap.devicePixelRatio()
        height = pixmap.height()/pixmap.devicePixelRatio()
        return area.x()+(area.width()-width)//2, area.y()+(area.height()-height)//2, width, height

    def setText(self, text):
        """Do not resurrect an old pixmap when a camera-off label is resized."""
        self._image = None
        super().setText(text)

    def resizeEvent(self, event):
        """Recompute the actual display rectangle without changing frame identity."""
        super().resizeEvent(event)
        self._rescale()


class StereoVideoClient(QThread):
    """双目视频流接收线程（协议兼容老版 CameraStreamClient）。

    信号:
      frame_received(np.ndarray)  解码后的 BGR 画布
      connection_status(bool,str) 连接状态
      message_received(str)       机上 JSON 消息原文（测量/确认）
    """

    frame_received = pyqtSignal(np.ndarray)
    connection_status = pyqtSignal(bool, str)
    message_received = pyqtSignal(str)
    calibration_received = pyqtSignal(object, bytes)

    def __init__(self):
        """初始化线程状态。"""
        super().__init__()
        self.running = False
        self.connected = False
        self.socket = None
        self.host = None
        self.port = DUAL_FISH_CONFIG["video_port"]
        self.preview_layout = STEREO_PREVIEW_LAYOUT
        self._stop_requested = False
        self.stereo_sink = None
        self._send_lock = threading.Lock()
        self.connection_id = 0

    def set_connection(self, host, port):
        """设置服务器地址与端口。"""
        self.host = host
        self.port = port
        self.preview_layout = STEREO_PREVIEW_LAYOUT
        self._stop_requested = False
        self.connection_id += 1

    def _recv_all(self, size):
        """阻塞收满 size 字节，连接断开返回 None。"""
        return receive_exact(self.socket, size, lambda: self._stop_requested)

    def send_command(self, cmd):
        """向板上发送一行文本命令（如 SET_POINT u v）。"""
        if self.connected and self.socket:
            try:
                with self._send_lock:
                    self.socket.sendall((cmd.strip() + "\n").encode('utf-8'))
                return True
            except Exception as exc:
                print(f"发送命令失败: {exc}")
        return False

    def run(self):
        """接收主循环：解析 [长度][类型][数据] 消息并分发信号。"""
        if self._stop_requested:
            self.connection_status.emit(False, "连接已取消")
            return
        self.running = True
        disconnect_message = "连接已断开"
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(5.0)
            self.socket.connect((self.host, self.port))
            if self._stop_requested:
                disconnect_message = "连接已取消"
                return
            self.connected = True
            self.connection_status.emit(True, f"已连接到 {self.host}:{self.port}")

            while self.running and not self._stop_requested:
                try:
                    size_data = self._recv_all(4)
                    if not size_data:
                        break
                    size = struct.unpack("!I", size_data)[0]
                    if not 1 <= size <= MAX_PACKET:
                        raise ValueError('Invalid video packet length')
                    payload = self._recv_all(size)
                    if not payload:
                        break
                    msg_type, body = payload[0], payload[1:]
                    if msg_type in (STEREO_FRAME, CALIBRATION):
                        metadata, blob = decode_blob(body)
                        metadata['connection_id'] = self.connection_id
                        if msg_type == CALIBRATION:
                            self.calibration_received.emit(metadata, blob)
                        elif self.stereo_sink:
                            self.stereo_sink(metadata, blob)
                    elif msg_type == 0xFF:
                        frame = cv2.imdecode(
                            np.frombuffer(body, np.uint8), cv2.IMREAD_COLOR)
                        if frame is not None:
                            self.frame_received.emit(
                                prepare_stereo_display_frame(
                                    frame, self.preview_layout))
                    elif msg_type == 0xFE:
                        text = body.decode('utf-8', 'ignore')
                        try:
                            info = json.loads(text)
                            layout = info.get("layout") or info.get(
                                "preview_layout")
                            if layout in ("raw_single", "raw_sbs", "processed"):
                                self.preview_layout = layout
                        except (TypeError, ValueError):
                            pass
                        self.message_received.emit(text)
                except socket.timeout:
                    continue
                except Exception as exc:
                    if not self._stop_requested:
                        print(f"接收错误: {exc}")
                    break
        except Exception as exc:
            disconnect_message = f"连接失败: {str(exc)}"
        finally:
            if self.socket:
                try:
                    self.socket.close()
                except OSError:
                    pass
            self.socket = None
            self.connected = False
            self.running = False
            self.connection_status.emit(False, disconnect_message)

    def stop(self):
        """停止线程并断开连接。"""
        self._stop_requested = True
        self.running = False
        if self.socket:
            try:
                self.socket.shutdown(socket.SHUT_RDWR)
                self.socket.close()
            except Exception:
                pass


class StereoFishCameraWidget(QWidget):
    """双尾双目鱼视频/测距组件。

    电脑测距、单目显示、同帧点击标点，保留主连接与相机状态门闩。
    """

    state_changed = pyqtSignal()
    single_frame_ready = pyqtSignal(np.ndarray)

    def __init__(self, settings=None):
        """初始化界面、连接与统计。"""
        super().__init__()
        self._calibration_settings = settings if settings is not None else QSettings('FishRobot', 'GroundStation')
        self._calibration_path = ''
        self._calibration_restore_error = ''
        self.stream_client = StereoVideoClient()
        self.worker = StereoWorker()
        self.stream_client.stereo_sink = self._submit_stereo
        self._local_model = None
        self._local_result = None
        self._chosen_calibration = None
        self._board_calibration = None
        self._source_descriptor = None
        self._source_epoch = None
        self._resolution_options = []
        self._resolution_supported = False
        self._resolution_pending = None
        self._calibration_notice_error = False
        self._selected_point = None
        self._relay_mode = False
        self._allow_board_recording = False
        self._local_enabled = True
        self._fish_connection_available = False
        self._stream_state = "locked"
        self._camera_state = "unavailable"
        self._camera_request_id = 0
        self.camera_on = False
        self.ranging_on = False
        self.board_rec_on = False
        self.current_frame = None
        self.recording = False
        self.writer = None
        self.recording_path = None
        self._rec_count = 0
        self._fps_count = 0
        self._fps_t0 = time.time()
        self._init_ui()
        self._init_connections()
        self._result_timer = QTimer(self)
        self._result_timer.timeout.connect(self._poll_local_result)
        self._result_timer.start(20)
        self._apply_ui_state()
        self._restore_calibration_selection()

    def _init_ui(self):
        """构建界面：连接控制、视频画布、测量数据面板（整页可滚动）。"""
        content = QWidget()
        layout = QVBoxLayout(content)

        title = QLabel("双目传输 · 电脑测距 · 单目显示（点击画面测距）")
        title.setAlignment(Qt.AlignCenter)
        title.setWordWrap(True)
        title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        title.setFont(QFont("Arial", 14, QFont.Bold))
        layout.addWidget(title)

        control_group = QGroupBox("连接控制")
        control_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        control_layout = QVBoxLayout(control_group)
        control_layout.setSpacing(6)
        self.connect_btn = QPushButton("连接视频")
        self.connect_btn.clicked.connect(self._toggle_connection)
        self.disconnect_btn = QPushButton("断开")
        self.disconnect_btn.clicked.connect(self._disconnect)
        self.disconnect_btn.setEnabled(False)
        self.record_btn = QPushButton("保存视频")
        self.record_btn.setEnabled(False)
        self.record_btn.setToolTip(
            "录制当前单目画面；停止后弹出对话框选择 mp4 保存位置")
        self.record_btn.clicked.connect(self._toggle_recording)
        self.snapshot_btn = QPushButton("保存图像")
        self.snapshot_btn.clicked.connect(self._choose_snapshot)
        self.cam_btn = QPushButton("开启摄像头")
        self.cam_btn.setEnabled(False)
        self.cam_btn.setToolTip(
            "板上相机默认不随启动脚本开启；点击发 CAM_ON 打开，再点发 CAM_OFF 关闭")
        self.cam_btn.clicked.connect(self._toggle_camera)
        self.board_rec_btn = QPushButton("板上高清录制", control_group)
        self.board_rec_btn.setEnabled(False)
        self.board_rec_btn.setToolTip(
            "命令板子以 2560x720 录制 MJPG 并保存在板子本地（录制期间预览暂停）")
        self.board_rec_btn.clicked.connect(self._toggle_board_recording)
        self.board_rec_btn.hide()

        self.action_bar = QWidget()
        action_layout = QHBoxLayout(self.action_bar)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(6)
        for button in (self.connect_btn, self.disconnect_btn, self.cam_btn,
                       self.record_btn, self.snapshot_btn):
            button.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
            action_layout.addWidget(button)
        action_layout.addStretch(1)
        self.action_scroll = QScrollArea()
        self.action_scroll.setWidget(self.action_bar)
        self.action_scroll.setWidgetResizable(True)
        self.action_scroll.setFrameShape(QFrame.NoFrame)
        self.action_scroll.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.action_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.action_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.action_scroll.horizontalScrollBar().rangeChanged.connect(self._update_action_bar_height)
        self._update_action_bar_height(0, 0)
        control_layout.addWidget(self.action_scroll)

        self.mode_label = QLabel("模式: 电脑测距 · 显示左校正图")
        self.mode_label.setWordWrap(True)
        self.mode_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        control_layout.addWidget(self.mode_label)
        resolution_row = QHBoxLayout()
        resolution_row.addWidget(QLabel('采集分辨率'))
        self.resolution_combo = QComboBox()
        self.resolution_combo.setAccessibleName('双目采集分辨率')
        self.resolution_combo.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.resolution_combo.setMinimumWidth(100)
        self.resolution_combo.setToolTip('每目是单个相机的尺寸；双目是实际传输的横拼尺寸。关闭摄像头后应用。')
        self.resolution_combo.currentIndexChanged.connect(self._resolution_selection_changed)
        resolution_row.addWidget(self.resolution_combo, 1)
        self.resolution_apply_btn = QPushButton('应用分辨率')
        self.resolution_apply_btn.clicked.connect(self._apply_resolution)
        resolution_row.addWidget(self.resolution_apply_btn)
        control_layout.addLayout(resolution_row)
        self.resolution_hint = QLabel('连接视频后读取相机可用档位；关闭摄像头后可切换。')
        self.resolution_hint.setWordWrap(True)
        self.resolution_hint.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        control_layout.addWidget(self.resolution_hint)
        layout.addWidget(control_group)

        # 测距与标定只在电脑切换；绝不向板端启动测距。
        range_group = QGroupBox("测距")
        range_layout = QVBoxLayout(range_group)
        range_controls = QHBoxLayout()
        self.range_btn = QPushButton("暂停本地测距")
        self.range_btn.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.range_btn.setEnabled(False)
        self.range_btn.setToolTip(
            "只切换电脑端SGBM/WLS；不会启动Pico测距")
        self.range_btn.clicked.connect(self._toggle_ranging)
        self.range_state_label = QLabel("测距状态: 关")
        self.range_state_label.setWordWrap(True)
        self.range_state_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        range_controls.addWidget(self.range_btn)
        range_controls.addWidget(self.range_state_label, 1)
        range_layout.addLayout(range_controls)
        calibration_row = QHBoxLayout()
        self.load_npz_btn = QPushButton("加载本地NPZ")
        self.load_npz_btn.setToolTip("选择当前空气、玻璃或水下环境对应的最终NPZ；不重新标定。录制期间先停止保存。")
        self.load_npz_btn.clicked.connect(self._choose_calibration_file)
        self.board_npz_btn = QPushButton("使用板端NPZ")
        self.board_npz_btn.setToolTip("切回当前视频服务提供的默认标定，不修改板端文件")
        self.board_npz_btn.clicked.connect(self._use_board_calibration)
        self.calibration_source_input = QLineEdit("板端自动NPZ（等待连接）")
        self.calibration_source_input.setReadOnly(True)
        self.calibration_source_input.setAccessibleName("当前测距NPZ文件")
        self.calibration_source_input.setMinimumWidth(100)
        calibration_row.addWidget(self.load_npz_btn)
        calibration_row.addWidget(self.board_npz_btn)
        calibration_row.addWidget(self.calibration_source_input, 1)
        range_layout.addLayout(calibration_row)
        self.calibration_file_label = QLabel('当前参数：板端自动NPZ')
        self.calibration_file_label.setTextFormat(Qt.PlainText)
        self.calibration_file_label.setWordWrap(True)
        self.calibration_file_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        range_layout.addWidget(self.calibration_file_label)
        self.calibration_status_label = QLabel("当前使用板端自动参数；也可选择本地最终NPZ。请选择匹配环境、相机和分辨率的文件。")
        self.calibration_status_label.setTextFormat(Qt.PlainText)
        self.calibration_status_label.setWordWrap(True)
        self.calibration_status_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        range_layout.addWidget(self.calibration_status_label)
        layout.addWidget(range_group)

        video_group = QGroupBox("单目实时画面")
        video_layout = QVBoxLayout(video_group)
        canvas_controls = QHBoxLayout()
        canvas_controls.addWidget(QLabel('画布高度'))
        self.video_height_input = NoWheelSpinBox()
        self.video_height_input.setRange(320, 2400)
        self.video_height_input.setSingleStep(80)
        self.video_height_input.setValue(DEFAULT_VIDEO_CANVAS_HEIGHT)
        self.video_height_input.setSuffix(' px')
        self.video_height_input.setAccessibleName('单目显示画布高度')
        self.video_height_input.setToolTip('界面逻辑像素；只调整显示大小，不改变相机分辨率、测距或保存尺寸。可输入、用方向键或按钮调整，滚轮只滚动页面。')
        canvas_controls.addWidget(self.video_height_input)
        self.video_height_reset_btn = QPushButton('恢复默认大小')
        self.video_height_reset_btn.clicked.connect(
            lambda: self.video_height_input.setValue(DEFAULT_VIDEO_CANVAS_HEIGHT))
        canvas_controls.addWidget(self.video_height_reset_btn)
        canvas_controls.addStretch()
        video_layout.addLayout(canvas_controls)
        self.video_label = SingleViewLabel()
        self.video_label.setAlignment(Qt.AlignCenter)
        # 竖向图按高度缩放，增大画布而不拉伸或裁剪；整页可滚动。
        self.video_label.setMinimumWidth(160)
        self.video_label.setFixedHeight(DEFAULT_VIDEO_CANVAS_HEIGHT)
        self.video_height_input.valueChanged.connect(self._set_video_canvas_height)
        self.video_label.setCursor(Qt.CrossCursor)
        self.video_label.setStyleSheet("""
            QLabel {
                border: 2px solid #ccc;
                background-color: #202020;
                color: #eeeeee;
                border-radius: 5px;
            }
        """)
        self.video_label.setText("未连接到机器鱼相机\n点击'连接视频'开始单目实时画面")
        self.video_label.mousePressEvent = self._on_video_click
        video_layout.addWidget(self.video_label)
        layout.addWidget(video_group)

        measure_group = QGroupBox("测距结果")
        measure_layout = QGridLayout(measure_group)
        self.distance_label = QLabel("距离 D: --")
        self.z_label = QLabel("深度 Z: --")
        self.x_label = QLabel("X: --")
        self.y_label = QLabel("Y: --")
        self.disp_label = QLabel("视差: --")
        self.measure_point_label = QLabel("测点: --")
        for col, label in enumerate([self.distance_label, self.z_label,
                                     self.disp_label, self.x_label,
                                     self.y_label, self.measure_point_label]):
            label.setFont(QFont("Arial", 11, QFont.Bold))
            measure_layout.addWidget(label, col//3, col % 3)
        layout.addWidget(measure_group)

        status_group = QGroupBox("状态信息")
        status_layout = QVBoxLayout(status_group)
        self.status_label = QLabel("连接状态: 未连接")
        self.camera_state_label = QLabel("摄像头: 未连接")
        self.camera_state_label.setFont(QFont("Arial", 11, QFont.Bold))
        self.fps_label = QLabel("帧率: --")
        self.resolution_label = QLabel("分辨率: --")
        for label in (self.status_label, self.camera_state_label, self.fps_label, self.resolution_label):
            label.setWordWrap(True)
            label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        status_layout.addWidget(self.status_label)
        status_layout.addWidget(self.camera_state_label)
        status_layout.addWidget(self.fps_label)
        status_layout.addWidget(self.resolution_label)
        layout.addWidget(status_group)
        layout.addStretch()

        # 整页滚动：窗口矮时"双目测距"选项卡整体上下滚动
        # （按钮/画布/测距结果/状态相对页面静止一起滚），窗口高时完整平铺
        page_scroll = QScrollArea()
        self.page_scroll = page_scroll
        page_scroll.setWidget(content)
        page_scroll.setWidgetResizable(True)
        page_scroll.setFrameShape(QFrame.NoFrame)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(page_scroll)

    def _init_connections(self):
        """连接视频线程信号（QueuedConnection 保证线程安全）。"""
        self.stream_client.frame_received.connect(self._on_legacy_frame, Qt.QueuedConnection)
        self.stream_client.calibration_received.connect(self._on_calibration, Qt.QueuedConnection)
        self.stream_client.connection_status.connect(self._on_connection_status, Qt.QueuedConnection)
        self.stream_client.message_received.connect(self._on_message, Qt.QueuedConnection)

    def _set_video_canvas_height(self, height):
        """Resize only the display canvas, preserving image identity and click mapping."""
        self.video_label.setFixedHeight(height)

    def _update_action_bar_height(self, minimum, maximum):
        """Keep one compact action row, adding scrollbar height only on narrow pages."""
        scrollbar = self.action_scroll.horizontalScrollBar()
        self.action_scroll.setFixedHeight(self.action_bar.sizeHint().height()+
                                         (scrollbar.sizeHint().height() if maximum > minimum else 0))

    def set_fish_connection_available(self, available):
        """设置主控连接门闩；断开主连接时同步收拢视频连接。"""
        available = bool(available)
        if available == self._fish_connection_available:
            self._apply_ui_state()
            return
        self._fish_connection_available = available
        if not available:
            self._disconnect(prompt_for_recording=False)
            self._stream_state = "locked"
            self._camera_state = "unavailable"
        elif self._stream_state == "locked":
            self._stream_state = "disconnected"
            self._camera_state = "unavailable"
        self._apply_ui_state()

    def connect_stream(self):
        """在主控连接已就绪时启动视频服务连接，重复调用无副作用。"""
        if (not self._fish_connection_available or
                self._stream_state not in ("disconnected", "error")):
            return False
        if self.stream_client.isRunning():
            self._stream_state = "disconnecting"
            self._apply_ui_state()
            return False
        fish_ip = self._get_fish_ip()
        if not fish_ip:
            QMessageBox.warning(self, "错误", "无法获取机器鱼IP地址")
            return False
        self.stream_client.set_connection(
            fish_ip, DUAL_FISH_CONFIG["video_port"])
        self._stream_state = "connecting"
        self.status_label.setText("连接状态: 连接中...")
        self._apply_ui_state()
        self.stream_client.start()
        return True

    def _toggle_connection(self):
        """连接 pico 双目视频服务。"""
        if self._stream_state in ("connected", "connecting"):
            self._disconnect()
        else:
            self.connect_stream()

    def _disconnect(self, prompt_for_recording=True):
        """断开视频流。"""
        if self.recording:
            self._stop_recording(prompt_for_path=prompt_for_recording)
        if self._stream_state in ("locked", "disconnected"):
            self._reset_remote_state()
            self._apply_ui_state()
            return False
        self._stream_state = "disconnecting"
        self._apply_ui_state()
        self.stream_client.stop()
        if self.stream_client.isRunning():
            self.stream_client.wait(2000)
        if self.stream_client.isRunning():
            self._stream_state = "disconnecting"
        else:
            self._stream_state = (
                "disconnected" if self._fish_connection_available else "locked")
        self._reset_remote_state()
        self._apply_ui_state()
        return True

    def _reset_remote_state(self):
        """清除上一次连接的板端状态，避免重连期间误用旧值。"""
        self._camera_request_id += 1
        self.camera_on = False
        self.ranging_on = False
        self.board_rec_on = False
        self._camera_state = "unavailable"
        self._stream_seen = False
        self.current_frame = None
        self.worker.set_model(None)
        self._local_model = self._local_result = self._selected_point = None
        self._relay_mode = False
        self._board_calibration = self._source_descriptor = None
        self._source_epoch = None
        self._resolution_pending = None
        self._resolution_options = []
        self._resolution_supported = False
        self.resolution_combo.clear()
        self.resolution_hint.setText('连接视频后读取相机可用档位；关闭摄像头后可切换。')
        self._local_enabled = True
        self._clear_measurement()
        self._refresh_calibration_label(self._calibration_restore_error or
            ('等待连接同步双目' if self._calibration_path else '等待板端参数'),
            error=bool(self._calibration_restore_error))

    def _apply_ui_state(self):
        """根据主连接、视频服务和相机状态唯一地刷新控件。"""
        can_connect = (
            self._fish_connection_available and
            self._stream_state in ("disconnected", "error"))
        can_disconnect = self._stream_state in ("connecting", "connected")
        stream_connected = self._stream_state == "connected"
        camera_ready = self._camera_state in ("off", "on")
        camera_on = self._camera_state == "on"

        self.connect_btn.setEnabled(can_connect)
        self.disconnect_btn.setEnabled(can_disconnect)
        self.cam_btn.setEnabled(stream_connected and camera_ready and self._resolution_pending is None)
        resolution_ready = (stream_connected and self._camera_state == 'off' and
                            not self.recording and self._resolution_supported and
                            self._resolution_pending is None)
        self.resolution_combo.setEnabled(resolution_ready)
        actual = ((self._source_descriptor['width'], self._source_descriptor['height'])
                  if self._source_descriptor else None)
        self.resolution_apply_btn.setEnabled(resolution_ready and
            self.resolution_combo.currentData() in self._resolution_options and
            self.resolution_combo.currentData() != actual)
        self.record_btn.setEnabled(
            stream_connected and camera_on and self.current_frame is not None and
            not self.board_rec_on)
        self.board_rec_btn.setEnabled(False)
        self.snapshot_btn.setEnabled(stream_connected and camera_on and self.current_frame is not None)
        self.range_btn.setEnabled(
            stream_connected and camera_on and self._local_model is not None)
        self.range_btn.setText("暂停本地测距" if self._local_enabled else "恢复本地测距")
        self.load_npz_btn.setEnabled(not self.recording and self._resolution_pending is None)
        self.board_npz_btn.setEnabled(not self.recording and self._resolution_pending is None and bool(self._calibration_path))

        camera_text = {
            "unavailable": "开启摄像头",
            "querying": "查询摄像头…",
            "off": "开启摄像头",
            "turning_on": "开启中…",
            "on": "关闭摄像头",
            "turning_off": "关闭中…",
        }
        self.cam_btn.setText(camera_text.get(
            self._camera_state, "开启摄像头"))
        self.record_btn.setText("停止录制" if self.recording else "保存视频")
        self.board_rec_btn.setText(
            "停止板上录制" if self.board_rec_on else "板上高清录制")
        self.state_changed.emit()

    def _resolution_selection_changed(self, index):
        """Update the apply gate without issuing a network write on combo selection."""
        if hasattr(self, 'resolution_apply_btn'):
            self._apply_ui_state()

    def _update_resolution_state(self, info):
        """Accept server capabilities and exact acknowledgements, not guessed UI state."""
        options = info.get('resolution_options', [])
        valid = []
        if isinstance(options, list) and len(options) <= 32:
            for option in options:
                if not isinstance(option, dict):
                    continue
                width, height = option.get('width'), option.get('height')
                if (type(width) is int and type(height) is int and
                        384 < width <= 5120 and width % 2 == 0 and 0 < height <= 1440 and
                        (width, height) not in valid):
                    valid.append((width, height))
        self._resolution_supported = (self._relay_mode and self._source_descriptor is not None and
                                      info.get('resolution_switch') is True and bool(valid))
        actual = (info.get('source_width'), info.get('source_height'))
        pending = self._resolution_pending
        acknowledged = bool(pending and info.get('command') == 'SET_RESOLUTION' and
                            info.get('request_id') == pending['id'])
        resolved = acknowledged or bool(pending and pending['querying'])
        if resolved:
            self._resolution_pending = None
        selected = self.resolution_combo.currentData()
        if valid != self._resolution_options:
            self.resolution_combo.blockSignals(True)
            self.resolution_combo.clear()
            for width, height in valid:
                self.resolution_combo.addItem(f'每目 {width//2}×{height} · 双目 {width}×{height}', (width, height))
            self._resolution_options = valid
            self.resolution_combo.blockSignals(False)
            selected = None
        if resolved or selected is None:
            self.resolution_combo.blockSignals(True)
            self.resolution_combo.setCurrentIndex(valid.index(actual) if actual in valid else -1)
            self.resolution_combo.blockSignals(False)
        if self._resolution_pending:
            self.resolution_hint.setText('分辨率设置中，等待板端确认…')
        elif not self._resolution_supported:
            self.resolution_hint.setText('视频服务未提供可切换档位；请升级板端双目传输服务并检查相机枚举。')
        else:
            prefix = '已确认' if self._camera_state == 'on' else '下次采集'
            self.resolution_hint.setText(f'{prefix}：每目 {actual[0]//2}×{actual[1]} · 双目 {actual[0]}×{actual[1]}。关闭摄像头后应用；测距须匹配NPZ。')
            if resolved and actual != pending['size']:
                self.resolution_hint.setText('设置未生效，已恢复板端实际档位。'+self.resolution_hint.text())

    def _apply_resolution(self):
        """Request one camera-off configuration transaction; never reopen automatically."""
        self._apply_ui_state()
        if not self.resolution_apply_btn.isEnabled():
            return
        width, height = self.resolution_combo.currentData()
        request_id = f'{self.stream_client.connection_id}_{time.monotonic_ns()}'
        self._resolution_pending = dict(id=request_id, size=(width, height), querying=False)
        self._clear_local_frames()
        self._selected_point = None
        self.resolution_hint.setText('分辨率设置中，等待板端确认…')
        self._apply_ui_state()
        if not self.stream_client.send_command(f'SET_RESOLUTION {width} {height} {request_id}'):
            self._resolution_timeout(request_id)
        else:
            QTimer.singleShot(3000, lambda: self._resolution_timeout(request_id))

    def _resolution_timeout(self, request_id):
        """Reconcile uncertain writes with GET_STATE, never repeat a camera operation."""
        if self._resolution_pending and self._resolution_pending['id'] == request_id:
            self._resolution_pending['querying'] = True
            self.resolution_hint.setText('设置确认超时，正在查询实际档位；若无响应请断开视频后重连。')
            self.stream_client.send_command('GET_STATE')
            self._apply_ui_state()

    def get_action_states(self):
        """返回供主菜单同步的双目视频操作状态。"""
        stream_connected = self._stream_state == "connected"
        return {
            "connect": self.connect_btn.isEnabled(),
            "disconnect": self.disconnect_btn.isEnabled(),
            "camera_toggle": self.cam_btn.isEnabled(),
            "camera_text": self.cam_btn.text(),
            "record_start": self.record_btn.isEnabled() and not self.recording,
            "record_stop": self.recording,
            "snapshot": stream_connected and self._camera_state == 'on' and self.current_frame is not None,
        }

    def _toggle_recording(self):
        """开始/停止录制。停止后弹出对话框选择 mp4 保存位置与文件名。"""
        if self._stream_state != "connected" or self._camera_state != "on":
            QMessageBox.warning(self, "录制失败", "请先连接视频服务并开启摄像头")
            return
        if self.current_frame is None:
            QMessageBox.warning(self, "录制失败", "尚未收到视频画面")
            return
        if not self.recording:
            fd, self.recording_path = tempfile.mkstemp(suffix=".mp4")
            os.close(fd)
            self.writer = None  # 首帧到达时按实际尺寸创建
            self.recording = True
            self._rec_count = 0
            self.range_state_label.setText("录制状态: 录制中…")
            self._apply_ui_state()
        else:
            self._stop_recording()

    def _stop_recording(self, prompt_for_path=True):
        """停止录制并弹出保存对话框（仅 mp4）；取消则存到默认位置。"""
        if self.writer is not None:
            self.writer.release()
            self.writer = None
        self.recording = False
        self._apply_ui_state()
        temp_path = self.recording_path
        self.recording_path = None
        if not temp_path:
            return
        default_name = f"stereo_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
        path = ""
        if prompt_for_path:
            path, _ = QFileDialog.getSaveFileName(
                self, "保存录制视频", default_name, "MP4 视频 (*.mp4)")
        if not path:
            path = os.path.join("records", default_name)
        if not path.lower().endswith(".mp4"):
            path += ".mp4"
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        shutil.move(temp_path, path)
        self.range_state_label.setText(f"录制状态: 已保存 {os.path.basename(path)}")
        if prompt_for_path:
            QMessageBox.information(self, "录制完成", f"视频已保存到:\n{path}")

    def _record_frame(self, frame):
        """录制中则写入一帧（writer 在首帧按实际尺寸懒创建）。"""
        if not self.recording:
            return
        if self.writer is None:
            h, w = frame.shape[:2]
            self.writer = cv2.VideoWriter(
                self.recording_path, cv2.VideoWriter_fourcc(*"mp4v"),
                15.0, (w, h))
            if not self.writer.isOpened():
                self.writer = None
                self.recording = False
                self.range_state_label.setText("录制状态: 编码器不可用")
                self._apply_ui_state()
                return
        self.writer.write(frame)
        self._rec_count += 1

    def _toggle_ranging(self):
        """仅切换本地算法；不发送RANGE_ON或任何板端测距命令。"""
        if self._stream_state != "connected" or self._camera_state != "on" or self._local_model is None:
            return
        self._local_enabled = not self._local_enabled
        self.ranging_on = self._local_enabled
        self.worker.invalidate(enabled=self._local_enabled)
        self._local_result = None
        self._clear_measurement()
        self.range_state_label.setText('本地测距: 等待新帧' if self._local_enabled else '本地测距: 已暂停')
        self._apply_ui_state()

    def _toggle_camera(self):
        """开关板上相机：发送 CAM_ON / CAM_OFF（启动脚本默认不开相机）。

        命令在板端是幂等的：重复 CAM_ON/CAM_OFF 无副作用。
        """
        if self._resolution_pending is not None:
            return
        if self._stream_state != "connected":
            QMessageBox.warning(self, "切换失败", "请先连接视频服务")
            return
        if self._camera_state == "off":
            desired_on = True
        elif self._camera_state == "on":
            desired_on = False
        else:
            return
        self._camera_state = "turning_on" if desired_on else "turning_off"
        if not desired_on:
            self._clear_local_frames()
        self.camera_state_label.setText(
            f"摄像头: {'开启中…' if desired_on else '关闭中…'}")
        self._camera_request_id += 1
        request_id = self._camera_request_id
        if not self.stream_client.send_command("CAM_ON" if desired_on else "CAM_OFF"):
            self._camera_state = "querying"
            self.camera_state_label.setText("摄像头: 命令发送失败，重新查询中…")
        self._apply_ui_state()
        QTimer.singleShot(
            3000, lambda: self._camera_request_timeout(request_id))

    def _camera_request_timeout(self, request_id):
        """相机开关确认超时后重新查询板端真实状态。"""
        if request_id != self._camera_request_id:
            return
        if self._camera_state not in ("turning_on", "turning_off"):
            return
        self._camera_state = "querying"
        self.camera_state_label.setText("摄像头: 确认超时，重新查询中…")
        self.stream_client.send_command("GET_STATE")
        self._apply_ui_state()

    def _toggle_board_recording(self):
        """板上高清录制开关：REC_START / REC_STOP（2560x720 存板子本地）。

        录制期间相机被 v4l2-ctl 独占，预览暂停；停止后预览自动恢复。
        """
        if not self._allow_board_recording:
            return
        if self._stream_state != "connected" or self._camera_state != "on":
            QMessageBox.warning(self, "切换失败", "请先连接视频服务")
            return
        self.board_rec_on = not getattr(self, "board_rec_on", False)
        self.stream_client.send_command(
            "REC_START" if self.board_rec_on else "REC_STOP")
        self.board_rec_btn.setText(
            "停止板上录制" if self.board_rec_on else "板上高清录制")
        self.status_label.setText(
            f"板上录制: {'已发起' if self.board_rec_on else '已停止'}")
        self._apply_ui_state()

    def _get_fish_ip(self):
        """从主窗口读取 IP 输入框（未连接控制时用 DUAL_FISH_CONFIG 默认值）。"""
        try:
            main_window = self.window()
            if hasattr(main_window, 'ip_input'):
                return main_window.ip_input.text().strip() or DUAL_FISH_CONFIG["fish_ip"]
        except Exception:
            pass
        return DUAL_FISH_CONFIG["fish_ip"]

    def _on_video_click(self, event):
        """反算真实单目显示矩形，用当前帧点云读数并立即显示测点。"""
        if event.button() != Qt.LeftButton or self._local_result is None:
            return
        if not self._local_enabled or self._local_result.get('disparity') is None:
            self.status_label.setText('提示: 请开启本地测距并等待新帧')
            return
        height, width = self._local_result['image'].shape[:2]
        point = display_to_rectified(event.pos().x(), event.pos().y(),
                                     self.video_label.image_rectangle(), width, height)
        if point is not None:
            self._selected_point = point
            self._render_local_result(record=False)

    @pyqtSlot(str)
    def _on_message(self, text):
        """处理机上 JSON 消息：测量结果 / 测点确认 / 错误。"""
        try:
            info = json.loads(text)
        except (ValueError, TypeError):
            return
        msg_type = info.get("type")
        if self._stream_state != 'connected':
            return
        if msg_type == 'error':
            self.status_label.setText('视频服务: '+str(info.get('message', '未知错误')))
            pending = self._resolution_pending
            if (pending and info.get('command') == 'SET_RESOLUTION' and
                    info.get('request_id') == pending['id']):
                self._resolution_pending = None
                actual = (self._source_descriptor['width'], self._source_descriptor['height'])
                self.resolution_combo.setCurrentIndex(self._resolution_options.index(actual)
                    if actual in self._resolution_options else -1)
                self.resolution_hint.setText('分辨率设置失败，保留原档位：'+str(info.get('message', '未知错误')))
                self._apply_ui_state()
        elif msg_type == "ranging":
            return  # 板端开关不能改变电脑端算法的状态。
        elif msg_type == "camera":
            # 板端两种形态：命令回执 {"enabled": bool}、1Hz 推送 {"state": "on"/"off"}。
            # 幂等处理：1Hz 重复推送同状态时不重设控件（避免无谓刷新）
            enabled = bool(info.get("enabled", info.get("state") == "on"))
            self._camera_request_id += 1
            self.camera_on = enabled
            self._camera_state = "on" if enabled else "off"
            self.camera_state_label.setText(
                f"摄像头: {'已开启' if enabled else '已关闭'}")
            if not enabled:
                self._clear_local_frames()
                self._stream_seen = False
                self.current_frame = None
                self.video_label.setText("摄像头已关闭\n点击'开启摄像头'恢复画面")
            self._apply_ui_state()
        elif msg_type == "point_set":
            self.measure_point_label.setText(f"测点: ({info.get('u')},{info.get('v')})")
        elif msg_type == "recording":
            # 板上录制状态回报（REC_STOP 后带文件名）
            info_file = info.get("file", "")
            self.board_rec_on = info.get("state") not in ("stopped", "off") \
                and not bool(info_file)
            if info.get("state") == "stopped" or info_file:
                self.status_label.setText(
                    f"板上录制文件: {info_file}" if info_file else "板上录制已停止")
            self._apply_ui_state()
        elif msg_type == "node_state":
            # 板上真实状态（GET_STATE 应答）：UI 按实际情况显示而非固定假设
            layout = info.get("preview_layout")
            if layout in ("raw_single", "raw_sbs", "processed"):
                self.stream_client.preview_layout = layout
            self._relay_mode = info.get('protocol') == 'stereo-relay-v1'
            if self._relay_mode:
                self._update_source_descriptor(info)
            enabled = bool(info.get("camera_on", info.get("camera_enabled", False)))
            self._camera_request_id += 1
            self.camera_on = enabled
            self._camera_state = "on" if enabled else "off"
            self._source_epoch = info.get('camera_epoch')
            self._update_resolution_state(info)
            self.camera_state_label.setText(
                f"摄像头: {'已开启' if enabled else '关闭——点击开启摄像头出画面'}")
            if enabled and self.current_frame is None:
                self.video_label.setText("摄像头已开启——等待画面…")
            elif not enabled:
                self._clear_local_frames()
                self.video_label.setText(
                    "摄像头处于关闭状态\n点击'开启摄像头'按钮开始回传")
            self.mode_label.setText(('模式: Pico只传双目 · 电脑SGBM/WLS · 显示左校正图'
                if self._local_model else '模式: 仅预览原始第一目 · 未启用测距')
                if self._relay_mode else '旧视频服务: 仅预览，不启动板端测距')
            if not self._relay_mode:
                self.range_state_label.setText('本地测距: 旧服务未提供同步双目和标定')
            self._apply_ui_state()
        elif msg_type == "measurement":
            return  # 不能将旧板端读数叠加在电脑端另一帧上。

    def _update_measurement(self, info):
        """刷新测距结果标签。"""
        if info.get("layout") in ("raw_single", "raw_sbs"):
            source_w = info.get("source_width", "--")
            source_h = info.get("source_height", "--")
            source_name = (
                "原生单目" if info.get("layout") == "raw_single"
                else "兼容双目流取第一目")
            self.mode_label.setText(
                f"模式: 纯显示快通路（{source_name} {source_w}x{source_h}，电脑端提亮）")
            return
        if info.get("D") is not None:
            self.distance_label.setText(f"距离 D: {info['D']:.2f} cm")
            self.z_label.setText(f"深度 Z: {info['Z']:.2f} cm")
            self.x_label.setText(f"X: {info['X']:.2f} cm")
            self.y_label.setText(f"Y: {info['Y']:.2f} cm")
            self.disp_label.setText(f"视差: {info['disp']:.2f} px")
        else:
            self.distance_label.setText("距离 D: 无效")
            self.z_label.setText("深度 Z: --")
            self.x_label.setText("X: --")
            self.y_label.setText("Y: --")
            self.disp_label.setText("视差: --")
        source = '本地NPZ' if self._chosen_calibration else '板端NPZ'
        self.mode_label.setText(f"电脑测距 · {source} · 有效点: {info.get('valid_count', info.get('valid', 0))}")

    @pyqtSlot(np.ndarray)
    def _update_frame(self, frame):
        """刷新视频帧并统计帧率。"""
        try:
            if self._stream_state != 'connected' or self._camera_state in ('turning_off', 'off', 'unavailable'):
                return
            self.current_frame = frame
            first_frame = not getattr(self, "_stream_seen", False)
            if first_frame:
                # 首帧到达 = 相机确实在出图（覆盖按钮请求后的"开启中…"状态）
                self._stream_seen = True
                self._camera_request_id += 1
                self.camera_on = True
                self._camera_state = "on"
                self.camera_state_label.setText("摄像头: 已开启（画面回传中）")
            self._fps_count += 1
            now = time.time()
            if now - self._fps_t0 >= 1.0:
                fps = self._fps_count / (now - self._fps_t0)
                self.fps_label.setText(f"帧率: {fps:.1f} FPS")
                self._fps_count = 0
                self._fps_t0 = now

            h, w = frame.shape[:2]
            source = self._source_descriptor
            self.resolution_label.setText(
                f"采集双目: {source['width']}×{source['height']} · 显示单目: {w}×{h}"
                if source else f"分辨率: {w}×{h}")
            self.video_label.set_frame(frame)
            self.single_frame_ready.emit(frame)
            self._record_frame(frame)
            if first_frame:
                self._apply_ui_state()
        except Exception as exc:
            print(f"更新视频帧异常: {exc}")

    @pyqtSlot(bool, str)
    def _on_connection_status(self, connected, message):
        """更新连接状态标签。"""
        if connected:
            if not self._fish_connection_available:
                self.stream_client.stop()
                return
            self._stream_state = "connected"
            self._camera_state = "querying"
            self.status_label.setText("连接状态: 已连接")
            self._stream_seen = False
            # 不猜测板上状态：向节点查询真实相机/测距状态（GET_STATE 应答）
            self.camera_state_label.setText("摄像头: 查询中…")
            self.video_label.setText("已连接到视频服务\n正在查询摄像头状态…")
            self.stream_client.send_command("GET_STATE")
            if not self._calibration_path:
                self.stream_client.send_command("GET_CALIBRATION")
            self._apply_ui_state()
        else:
            if self.recording:
                self._stop_recording(prompt_for_path=False)
            failed = message.startswith("连接失败")
            self._stream_state = (
                "locked" if not self._fish_connection_available
                else "error" if failed else "disconnected")
            self._reset_remote_state()
            self.range_state_label.setText("测距状态: 关")
            self.status_label.setText(
                f"连接状态: {'连接失败' if failed else '未连接'}")
            self.camera_state_label.setText("摄像头: 未连接")
            self.resolution_label.setText("分辨率: --")
            self.video_label.clear()
            self.video_label.setText(f"连接已断开\n{message}")
            self._apply_ui_state()

    def save_snapshot(self, filename=None):
        """保存当前单目画面；无画面时返回 None。"""
        if self.current_frame is None:
            return None
        if filename is None:
            os.makedirs("records", exist_ok=True)
            filename = os.path.join(
                "records", datetime.datetime.now().strftime(
                    "stereo_snapshot_%Y%m%d_%H%M%S.png"))
        extension = os.path.splitext(filename)[1] or '.png'
        ok, data = cv2.imencode(extension, self.current_frame)
        if ok:
            data.tofile(filename)
            return filename
        return None

    def closeEvent(self, event):
        """组件销毁时停止视频线程。"""
        self.set_fish_connection_available(False)
        self.shutdown()
        event.accept()

    def shutdown(self):
        """Stop this widget's network/worker resources without starting any control."""
        self._result_timer.stop()
        self._disconnect(prompt_for_recording=False)
        self.worker.close()

    def _choose_snapshot(self):
        """Choose a PNG path and save only the displayed single-camera frame."""
        if self.current_frame is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, '保存当前单目图像', 'fish.png', 'PNG图像 (*.png)')
        if path:
            self.save_snapshot(path if path.lower().endswith('.png') else path+'.png')

    def _clear_measurement(self):
        """Clear every coordinate so invalid depth cannot retain an old X or Y."""
        for label, title in ((self.distance_label, '距离 D'), (self.z_label, '深度 Z'),
                             (self.x_label, 'X'), (self.y_label, 'Y'), (self.disp_label, '视差'),
                             (self.measure_point_label, '测点')):
            label.setText(title+': --')

    def _clear_local_frames(self):
        """Invalidate camera-off results, including a calculation already in flight."""
        self.worker.invalidate()
        self._local_result = None
        self.ranging_on = False
        self._stream_seen = False
        self.current_frame = None
        self._clear_measurement()
        self.range_state_label.setText('本地测距: 摄像头已关闭' if self._camera_state == 'off'
                                       else '本地测距: 等待有效新帧')
        if self._relay_mode:
            self.mode_label.setText('模式: Pico只传双目 · 电脑SGBM/WLS · 显示左校正图'
                if self._local_model else '模式: 仅预览原始第一目 · 未启用测距')
        if self.recording:
            self._stop_recording(prompt_for_path=False)

    @pyqtSlot(object, bytes)
    def _on_calibration(self, metadata, data):
        """Cache validated board bytes without overriding an explicit local selection."""
        if self._stream_state != 'connected' or metadata.get('connection_id') != self.stream_client.connection_id:
            return
        try:
            if metadata.get('bytes') != len(data) or len(data) > 8*1024*1024:
                raise ValueError('板端NPZ长度不正确')
            digest = hashlib.sha256(data).hexdigest()
            if digest != metadata.get('sha256'):
                raise ValueError('板端NPZ SHA256不匹配')
            if self._source_descriptor and digest != self._source_descriptor['sha256']:
                raise ValueError('板端NPZ不属于当前视频源')
            self._board_calibration = dict(data=data, sha256=digest)
            if not self._calibration_path:
                self._activate_calibration()
        except Exception as exc:
            if not self._calibration_path:
                self._install_calibration_model(None)
                self._refresh_calibration_label('板端参数不可用: '+str(exc), error=True)
        self._apply_ui_state()

    def _update_source_descriptor(self, info):
        """Bind selected calibration to the current raw capture, not the board's model content."""
        digest = info.get('calibration_sha256')
        width, height = info.get('source_width'), info.get('source_height')
        if (not isinstance(digest, str) or len(digest) != 64 or
                any(value not in '0123456789abcdef' for value in digest) or
                type(width) is not int or type(height) is not int or
                not (384 < width <= 5120 and width % 2 == 0 and 0 < height <= 1440)):
            self._source_descriptor = None
            self._install_calibration_model(None)
            self._refresh_calibration_label('视频来源信息不完整，不能测距', error=True)
            return
        descriptor = dict(sha256=digest, width=width, height=height)
        if descriptor == self._source_descriptor:
            return
        previous = self._source_descriptor
        self._source_descriptor = descriptor
        if self._board_calibration and self._board_calibration['sha256'] != digest:
            self._board_calibration = None
        self._activate_calibration()
        if previous is not None and not self._calibration_path and self._board_calibration is None:
            self.stream_client.send_command('GET_CALIBRATION')

    def _install_calibration_model(self, model):
        """Discard every previous-frame result before committing a different model."""
        self._clear_local_frames()
        self._selected_point = None
        self.ranging_on = False
        self._local_model = model
        preview = StereoPreview(self._source_descriptor) if model is None and self._source_descriptor else None
        self.worker.set_model(model if model is not None else preview)
        self.worker.invalidate(enabled=self._local_enabled)
        self.video_label.setText('标定已切换，等待当前参数的新帧…' if model else '无匹配标定：仅预览原始第一目，不能测距')
        if model is None:
            self.range_state_label.setText('本地测距: 未启用，请加载匹配分辨率的NPZ')
        self._apply_ui_state()

    def _activate_calibration(self):
        """Create just the active matcher, checking raw geometry and independent source SHA."""
        if self._calibration_path and self._chosen_calibration is None:
            self._install_calibration_model(None)
            self._refresh_calibration_label(self._calibration_restore_error, error=True)
            return
        chosen = self._chosen_calibration if self._calibration_path else self._board_calibration
        if self._source_descriptor is None or chosen is None:
            self._install_calibration_model(None)
            self._refresh_calibration_label('已校验本地文件，等待同步双目' if self._chosen_calibration else '等待板端参数')
            return
        try:
            model = StereoCalculator(chosen['data'], chosen['sha256'],
                                     source_sha256=self._source_descriptor['sha256'])
            self._check_calibration_size(model)
            self._install_calibration_model(model)
            self._refresh_calibration_label('就绪，开启相机并点击画面测距')
            self.range_state_label.setText('本地测距: 参数已加载，等待新帧')
        except Exception as exc:
            self._install_calibration_model(None)
            self._refresh_calibration_label('参数不可用: '+str(exc), error=True)

    def _check_calibration_size(self, model):
        """Reject incompatible capture dimensions without resizing or altering the camera."""
        if self._source_descriptor is not None:
            expected = (self._source_descriptor['width'], self._source_descriptor['height'])
            if (model.width*2, model.height) != expected:
                raise ValueError(f'尺寸不匹配：NPZ每目{model.width}×{model.height}，视频双目{expected[0]}×{expected[1]}')

    def _refresh_calibration_label(self, status, error=False):
        """Show exact chosen path and validation state; do not infer environment from pixels."""
        self._calibration_notice_error = error
        chosen = self._chosen_calibration
        label = self._calibration_path or '板端自动NPZ'
        self.calibration_source_input.setText(label)
        self.calibration_source_input.setCursorPosition(0)
        name = os.path.basename(self._calibration_path) if self._calibration_path else '板端自动NPZ'
        state = '已生效' if self._local_model else '未生效' if error else '已校验，待连接/新帧' if chosen else '未加载'
        self.calibration_file_label.setText(f'当前参数：{name}（{state}）')
        self.calibration_file_label.setToolTip(label)
        active = self._local_model
        details = f' · 每目{active.width}×{active.height} · SHA256 {active.sha256[:12]}' if active else (
            f" · 每目{chosen['width']}×{chosen['height']} · SHA256 {chosen['sha256'][:12]}" if chosen else '')
        self.calibration_source_input.setToolTip(label + (f'\nSHA256: {active.sha256}' if active else ''))
        self.calibration_status_label.setText(status+details)
        self.calibration_status_label.setStyleSheet('color: #b00020;' if error else '')

    def _restore_calibration_selection(self):
        """Re-read and validate the saved path on startup; never silently use board fallback."""
        path = self._calibration_settings.value('stereo/last_npz/dual', '')
        if not isinstance(path, str):
            self._refresh_calibration_label('上次NPZ路径记录格式错误，请重新选择；当前为板端模式', error=True)
            return
        if not path:
            return
        self._calibration_path = path
        if self.load_calibration_file(path, persist=False):
            self._refresh_calibration_label('已恢复上次NPZ，校验通过，等待连接同步双目')
        else:
            self._calibration_restore_error = '自动加载失败，未启用测距；请重新选择NPZ或使用板端NPZ。'+self.calibration_status_label.text()
            self._refresh_calibration_label(self._calibration_restore_error, error=True)
            self._apply_ui_state()

    def _remember_calibration_selection(self):
        """Persist only committed selections, or the explicit return to board mode."""
        key = 'stereo/last_npz/dual'
        if self._calibration_path:
            self._calibration_settings.setValue(key, self._calibration_path)
        else:
            self._calibration_settings.remove(key)
        self._calibration_settings.sync()
        if self._calibration_settings.status() != QSettings.NoError:
            self._refresh_calibration_label('当前选择已加载，但路径记忆保存失败，下次启动可能无法恢复', error=True)

    def load_calibration_file(self, path, persist=True):
        """Validate a local final NPZ transactionally; never upload it or start calibration."""
        if self._resolution_pending is not None:
            self._refresh_calibration_label('请等待分辨率设置确认后再切换NPZ', error=True)
            return False
        if self.recording:
            self._refresh_calibration_label('请先停止并保存录像，再切换NPZ', error=True)
            return False
        try:
            if os.path.splitext(path)[1].lower() != '.npz':
                raise ValueError('请选择NPZ格式的最终标定文件')
            with open(path, 'rb') as stream:
                data = stream.read(MAX_CALIBRATION_BYTES+1)
            digest = hashlib.sha256(data).hexdigest()
            source = self._source_descriptor['sha256'] if self._source_descriptor else None
            model = StereoCalculator(data, digest, source_sha256=source)
            self._check_calibration_size(model)
        except Exception as exc:
            self._clear_local_frames()
            previous = '仍保留当前参数' if self._local_model or self._chosen_calibration else '未加载本地参数'
            self._refresh_calibration_label('加载失败，'+previous+': '+str(exc), error=True)
            self._apply_ui_state()
            return False
        self._calibration_path = os.path.abspath(path)
        self._calibration_restore_error = ''
        self._chosen_calibration = dict(path=self._calibration_path, data=data, sha256=digest,
                                        width=model.width, height=model.height)
        self._install_calibration_model(model if self._source_descriptor else None)
        self._refresh_calibration_label('校验通过，本地NPZ已加载，等待新帧' if self._source_descriptor else '校验通过，本地NPZ已校验，等待连接同步双目')
        if persist:
            self._remember_calibration_selection()
        return True

    def _choose_calibration_file(self):
        """Choose one environment-specific NPZ using the native file picker."""
        current = self._calibration_path
        path, _ = QFileDialog.getOpenFileName(self, '选择当前环境对应的最终标定NPZ', current, '标定参数 (*.npz)')
        if path and not self.load_calibration_file(path):
            QMessageBox.warning(self, 'NPZ加载失败', self.calibration_status_label.text())

    def _use_board_calibration(self):
        """Explicitly return to automatic server parameters, requesting them only if needed."""
        if self.recording or self._resolution_pending is not None:
            return
        self._calibration_path = self._calibration_restore_error = ''
        self._chosen_calibration = None
        self._activate_calibration()
        self._remember_calibration_selection()
        if self._stream_state == 'connected' and self._board_calibration is None:
            self.stream_client.send_command('GET_CALIBRATION')

    def _submit_stereo(self, metadata, jpeg):
        """Network-thread callback: submit bytes only, never touch Qt or run SGBM."""
        if (self._stream_state == 'connected' and self._camera_state == 'on' and
                self._resolution_pending is None and
                metadata.get('connection_id') == self.stream_client.connection_id and
                (self._source_epoch is None or metadata.get('camera_epoch') == self._source_epoch)):
            self.worker.submit(metadata, jpeg)

    def _poll_local_result(self):
        """Pull a latest-only result without queued per-frame Qt signals."""
        result = self.worker.take_latest()
        if result is None or self._stream_state != 'connected' or self._camera_state != 'on':
            return
        if 'error' in result:
            self._clear_local_frames()
            self.video_label.setText('本地处理错误，等待有效新帧\n'+result['error'])
            self.range_state_label.setText('本地测距错误: '+result['error'])
            return
        if self._local_result is None and not self._calibration_notice_error and not result.get('uncalibrated'):
            self._refresh_calibration_label('本地NPZ已生效' if self._chosen_calibration else '板端NPZ已生效')
        self._local_result = result
        self.ranging_on = result['disparity'] is not None
        self.range_state_label.setText('仅预览原始第一目：NPZ与当前采集不匹配或尚未加载，不能测距'
            if result.get('uncalibrated') else
            f"本地测距: {'开' if self.ranging_on else '暂停'} · 帧{result['frame_id']} · 计算{result['compute_ms']:.1f}ms")
        self._render_local_result(record=True)

    def _render_local_result(self, record=False):
        """Render one rectified view with a visible valid/invalid fixed-coordinate marker."""
        result = self._local_result
        if result is None:
            return
        image = cv2.LUT(cv2.rotate(result['image'], cv2.ROTATE_90_CLOCKWISE), FAST_PREVIEW_LUT)
        if self._selected_point is not None:
            x, y = self._selected_point
            value = None
            if result['disparity'] is not None:
                value = measure_depth(result['disparity'], result['points'], x, y,
                                      result['scale'], result['offset'])
            self._update_measurement(value or {})
            self.measure_point_label.setText(f"测点: ({x},{y}) · 帧{result['frame_id']}")
            position = (result['image'].shape[0]-1-y, x)
            color = (0, 255, 0) if value else (0, 0, 255)
            cv2.drawMarker(image, position, color, cv2.MARKER_CROSS, 19, 2)
            cv2.circle(image, position, 8, color, 2)
            text = f"D={value['D']:.2f}cm" if value else 'invalid depth'
            cv2.putText(image, text, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, .6, color, 2)
        if record:
            self._update_frame(image)
        else:
            self.current_frame = image
            self.video_label.set_frame(image)

    @pyqtSlot(np.ndarray)
    def _on_legacy_frame(self, frame):
        """Keep old services preview-only and prevent a legacy depth canvas being saved."""
        if self._relay_mode:
            return
        self._local_result = None
        self._clear_measurement()
        if self.stream_client.preview_layout == 'processed':
            frame = prepare_stereo_display_frame(frame[:LEFT_RECT_H, :LEFT_RECT_W], 'raw_single')
        self._update_frame(frame)
