#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
双尾双目鱼机载双目视频组件
Stereo Fish Onboard Camera Widget

连接 pico 的 pico_stereo depth_node TCP 服务（默认 9998 端口），
帧协议与老版 camera_stream_server 兼容：
  服务端 -> 地面站: [4字节大端长度][1字节类型][数据]  0xFF=JPEG帧 0xFE=JSON消息
  地面站 -> 服务端: 文本行命令  SET_POINT u v（在左校正图上点击测距）

纯显示快通路接收相机原始左右拼接帧，旋转、上下拼接和 Gamma 提亮在电脑端完成，
避免 pico 用旧 640x480 标定映射处理高清帧。开启测距后仍使用原画布布局：
  上行: 左校正图(0,0,640,480) | 右校正图(640,0,640,480)
  下行: 视差伪彩(0,480,1280,480)
鼠标点击落在左校正图区域时换算为校正图坐标发送 SET_POINT，
服务端把测点十字与 D 读数画在画布上，并通过 0xFE JSON 推送测量值。
"""

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

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QGroupBox, QMessageBox, QGridLayout,
                             QFileDialog, QSizePolicy, QScrollArea, QFrame)
from PyQt5.QtCore import QThread, QTimer, pyqtSignal, Qt, pyqtSlot
from PyQt5.QtGui import QImage, QPixmap, QFont

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DUAL_FISH_CONFIG, STEREO_RANGING_UI_ENABLED

# 画布布局常量（与 pico_stereo.stereo_lib 保持一致）
CANVAS_W, CANVAS_H = 1280, 960
LEFT_RECT_W, LEFT_RECT_H = 640, 480
FAST_PREVIEW_GAMMA = 2.0
FAST_PREVIEW_LUT = np.array([
    ((value / 255.0) ** (1.0 / FAST_PREVIEW_GAMMA)) * 255.0
    for value in range(256)
], dtype=np.uint8)


def prepare_stereo_display_frame(frame):
    """把板端原始左右拼接帧转正、上下排布并提亮；处理后画布原样返回。"""
    height, width = frame.shape[:2]
    if width < height * 2 or width % 2:
        return frame
    middle = width // 2
    left = cv2.rotate(frame[:, :middle], cv2.ROTATE_90_CLOCKWISE)
    right = cv2.rotate(frame[:, middle:], cv2.ROTATE_90_CLOCKWISE)
    canvas = cv2.vconcat([left, right])
    return cv2.LUT(canvas, FAST_PREVIEW_LUT)


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

    def __init__(self):
        """初始化线程状态。"""
        super().__init__()
        self.running = False
        self.connected = False
        self.socket = None
        self.host = None
        self.port = DUAL_FISH_CONFIG["video_port"]
        self._stop_requested = False

    def set_connection(self, host, port):
        """设置服务器地址与端口。"""
        self.host = host
        self.port = port
        self._stop_requested = False

    def _recv_all(self, size):
        """阻塞收满 size 字节，连接断开返回 None。"""
        data = b''
        while len(data) < size:
            packet = self.socket.recv(size - len(data))
            if not packet:
                return None
            data += packet
        return data

    def send_command(self, cmd):
        """向板上发送一行文本命令（如 SET_POINT u v）。"""
        if self.connected and self.socket:
            try:
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
                    payload = self._recv_all(size)
                    if not payload:
                        break
                    msg_type, body = payload[0], payload[1:]
                    if msg_type == 0xFF:
                        frame = cv2.imdecode(
                            np.frombuffer(body, np.uint8), cv2.IMREAD_COLOR)
                        if frame is not None:
                            self.frame_received.emit(
                                prepare_stereo_display_frame(frame))
                    elif msg_type == 0xFE:
                        self.message_received.emit(body.decode('utf-8', 'ignore'))
                except socket.timeout:
                    continue
                except Exception as exc:
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

    显示 pico 双目画布（校正对 + 视差），点击左校正图区域发送 SET_POINT
    测距命令，并实时显示测量结果（D/Z/X/Y/视差）与节点状态。
    """

    state_changed = pyqtSignal()

    def __init__(self):
        """初始化界面、连接与统计。"""
        super().__init__()
        self.stream_client = StereoVideoClient()
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
        self._apply_ui_state()

    def _init_ui(self):
        """构建界面：连接控制、视频画布、测量数据面板（整页可滚动）。"""
        content = QWidget()
        layout = QVBoxLayout(content)

        title = QLabel("双目视频（纯显示高清快通路；开启测距后可点击左校正图）")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(QFont("Arial", 14, QFont.Bold))
        layout.addWidget(title)

        control_group = QGroupBox("连接控制")
        control_layout = QHBoxLayout(control_group)
        self.connect_btn = QPushButton("连接视频")
        self.connect_btn.clicked.connect(self._toggle_connection)
        self.disconnect_btn = QPushButton("断开")
        self.disconnect_btn.clicked.connect(self._disconnect)
        self.disconnect_btn.setEnabled(False)
        control_layout.addWidget(self.connect_btn)
        control_layout.addWidget(self.disconnect_btn)
        self.record_btn = QPushButton("保存视频")
        self.record_btn.setEnabled(False)
        self.record_btn.setToolTip(
            "录制当前双目画面(两路上下排布)；停止后弹出对话框选择 mp4 保存位置")
        self.record_btn.clicked.connect(self._toggle_recording)
        control_layout.addWidget(self.record_btn)
        self.cam_btn = QPushButton("开启摄像头")
        self.cam_btn.setEnabled(False)
        self.cam_btn.setToolTip(
            "板上相机默认不随启动脚本开启；点击发 CAM_ON 打开，再点发 CAM_OFF 关闭")
        self.cam_btn.clicked.connect(self._toggle_camera)
        control_layout.addWidget(self.cam_btn)
        self.board_rec_btn = QPushButton("板上高清录制")
        self.board_rec_btn.setEnabled(False)
        self.board_rec_btn.setToolTip(
            "命令板子以 2560x720 录制 MJPG 并保存在板子本地（录制期间预览暂停）")
        self.board_rec_btn.clicked.connect(self._toggle_board_recording)
        control_layout.addWidget(self.board_rec_btn)
        control_layout.addStretch()

        self.mode_label = QLabel("介质: 水下模型")
        control_layout.addWidget(self.mode_label)
        layout.addWidget(control_group)

        # 测距开关：板上默认纯视频模式；点击后启动/停止测距程序（SGBM+测量）
        range_group = QGroupBox("测距")
        range_layout = QHBoxLayout(range_group)
        self.range_btn = QPushButton("启动测距")
        self.range_btn.setEnabled(False)
        self.range_btn.setToolTip(
            "当前保持纯显示模式，测距功能待后续单独恢复")
        self.range_btn.clicked.connect(self._toggle_ranging)
        self.range_state_label = QLabel("测距状态: 关")
        range_layout.addWidget(self.range_btn)
        range_layout.addWidget(self.range_state_label)
        range_layout.addStretch()
        layout.addWidget(range_group)

        video_group = QGroupBox("双目画面（左上:左校正 | 右上:右校正 | 下:视差伪彩）")
        video_layout = QVBoxLayout(video_group)
        self.video_label = QLabel()
        self.video_label.setAlignment(Qt.AlignCenter)
        # 竖版画布（两路 640x480 上下拼接 = 640x960, 2:3）：
        # 画布静态排在页面里随整页滚动，按页面宽度缩放、保持比例
        self.video_label.setMinimumSize(380, 570)
        self.video_label.setCursor(Qt.CrossCursor)
        self.video_label.setStyleSheet("""
            QLabel {
                border: 2px solid #ccc;
                background-color: #202020;
                border-radius: 5px;
            }
        """)
        self.video_label.setText("未连接到双目鱼\n点击'连接视频'开始实时画面")
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
            measure_layout.addWidget(label, 0, col)
        layout.addWidget(measure_group)

        status_group = QGroupBox("状态信息")
        status_layout = QVBoxLayout(status_group)
        self.status_label = QLabel("连接状态: 未连接")
        self.camera_state_label = QLabel("摄像头: 未连接")
        self.camera_state_label.setFont(QFont("Arial", 11, QFont.Bold))
        self.fps_label = QLabel("帧率: --")
        self.resolution_label = QLabel("分辨率: --")
        status_layout.addWidget(self.status_label)
        status_layout.addWidget(self.camera_state_label)
        status_layout.addWidget(self.fps_label)
        status_layout.addWidget(self.resolution_label)
        layout.addWidget(status_group)
        layout.addStretch()

        # 整页滚动：窗口矮时"双目测距"选项卡整体上下滚动
        # （按钮/画布/测距结果/状态相对页面静止一起滚），窗口高时完整平铺
        page_scroll = QScrollArea()
        page_scroll.setWidget(content)
        page_scroll.setWidgetResizable(True)
        page_scroll.setFrameShape(QFrame.NoFrame)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(page_scroll)

    def _init_connections(self):
        """连接视频线程信号（QueuedConnection 保证线程安全）。"""
        self.stream_client.frame_received.connect(self._update_frame, Qt.QueuedConnection)
        self.stream_client.connection_status.connect(self._on_connection_status, Qt.QueuedConnection)
        self.stream_client.message_received.connect(self._on_message, Qt.QueuedConnection)

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
        self.cam_btn.setEnabled(stream_connected and camera_ready)
        self.record_btn.setEnabled(
            stream_connected and camera_on and self.current_frame is not None and
            not self.board_rec_on)
        self.board_rec_btn.setEnabled(
            stream_connected and camera_on and not self.recording)
        self.range_btn.setEnabled(
            STEREO_RANGING_UI_ENABLED and stream_connected and camera_on)

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
            "snapshot": stream_connected and self.current_frame is not None,
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
        """切换板上测距程序：发送 RANGE_ON / RANGE_OFF 命令。"""
        if not STEREO_RANGING_UI_ENABLED:
            QMessageBox.information(self, "纯显示模式", "当前版本不启动双目测距")
            return
        if self._stream_state != "connected" or self._camera_state != "on":
            QMessageBox.warning(self, "切换失败", "请先连接视频流")
            return
        self.ranging_on = not getattr(self, "ranging_on", False)
        self.stream_client.send_command("RANGE_ON" if self.ranging_on else "RANGE_OFF")
        self.range_btn.setText("停止测距" if self.ranging_on else "启动测距")
        self.range_state_label.setText(
            f"测距状态: {'开' if self.ranging_on else '关'}")

    def _toggle_camera(self):
        """开关板上相机：发送 CAM_ON / CAM_OFF（启动脚本默认不开相机）。

        命令在板端是幂等的：重复 CAM_ON/CAM_OFF 无副作用。
        """
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
        """鼠标点击画布：换算左校正图坐标并下发 SET_POINT。"""
        if self._stream_state != "connected" or self.current_frame is None:
            return
        if not getattr(self, "ranging_on", False):
            self.status_label.setText("提示: 纯显示模式不做标定映射，请先启动测距")
            return
        # 点击位置 -> 显示像素 -> 画布像素
        label_w = max(self.video_label.width(), 1)
        label_h = max(self.video_label.height(), 1)
        # 实际显示区域按 KeepAspectRatio 缩放
        frame_h, frame_w = self.current_frame.shape[:2]
        scale = min(label_w / frame_w, label_h / frame_h)
        shown_w, shown_h = int(frame_w * scale), int(frame_h * scale)
        offset_x = (label_w - shown_w) // 2
        offset_y = (label_h - shown_h) // 2
        px = event.pos().x() - offset_x
        py = event.pos().y() - offset_y
        if not (0 <= px < shown_w and 0 <= py < shown_h):
            return
        canvas_x = int(px / scale)
        canvas_y = int(py / scale)
        # 仅接受左校正图区域内的点击
        if not (0 <= canvas_x < LEFT_RECT_W and 0 <= canvas_y < LEFT_RECT_H):
            self.status_label.setText("提示: 请点击左上角(左校正图)区域测距")
            return
        self.stream_client.send_command(f"SET_POINT {canvas_x} {canvas_y}")
        self.measure_point_label.setText(f"测点: ({canvas_x},{canvas_y}) 请求中...")

    @pyqtSlot(str)
    def _on_message(self, text):
        """处理机上 JSON 消息：测量结果 / 测点确认 / 错误。"""
        try:
            info = json.loads(text)
        except (ValueError, TypeError):
            return
        msg_type = info.get("type")
        if msg_type == "ranging":
            self.ranging_on = info.get("enabled", False)
            self.range_btn.setText("停止测距" if self.ranging_on else "启动测距")
            self.range_state_label.setText(
                f"测距状态: {'开' if self.ranging_on else '关'}")
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
            enabled = bool(info.get("camera_enabled", False))
            self._camera_request_id += 1
            self.camera_on = enabled
            self._camera_state = "on" if enabled else "off"
            self.camera_state_label.setText(
                f"摄像头: {'已开启' if enabled else '关闭——点击开启摄像头出画面'}")
            if enabled:
                self.video_label.setText("摄像头已开启——等待画面…")
            else:
                self.video_label.setText(
                    "摄像头处于关闭状态\n点击'开启摄像头'按钮开始回传")
            self.ranging_on = bool(info.get("ranging", False))
            self.range_btn.setText("停止测距" if self.ranging_on else "启动测距")
            self.range_state_label.setText(
                f"测距状态: {'开' if self.ranging_on else '关'}")
            self.mode_label.setText(
                f"介质: {'水下模型' if info.get('mode') == 'underwater' else '空气模型'}")
            self._apply_ui_state()
        elif msg_type == "measurement":
            self._update_measurement(info)

    def _update_measurement(self, info):
        """刷新测距结果标签。"""
        if info.get("layout") == "raw_sbs":
            source_w = info.get("source_width", "--")
            source_h = info.get("source_height", "--")
            self.mode_label.setText(
                f"模式: 纯显示快通路（原始双目 {source_w}x{source_h}，电脑端提亮）")
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
            self.disp_label.setText("视差: --")
        self.mode_label.setText(f"介质: {info.get('medium', '水下模型')}  "
                                f"有效点: {info.get('valid', 0)}")

    @pyqtSlot(np.ndarray)
    def _update_frame(self, frame):
        """刷新视频帧并统计帧率。"""
        try:
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

            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb_frame.shape
            qt_image = QImage(rgb_frame.data, w, h, ch * w, QImage.Format_RGB888)
            self.resolution_label.setText(f"分辨率: {w}x{h}")
            label_size = self.video_label.size()
            scaled_image = qt_image.scaled(
                label_size.width() - 12, label_size.height() - 12,
                Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.video_label.setPixmap(QPixmap.fromImage(scaled_image))
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
        """保存当前双目画面；无画面时返回 None。"""
        if self.current_frame is None:
            return None
        if filename is None:
            os.makedirs("records", exist_ok=True)
            filename = os.path.join(
                "records", datetime.datetime.now().strftime(
                    "stereo_snapshot_%Y%m%d_%H%M%S.jpg"))
        if cv2.imwrite(filename, self.current_frame):
            return filename
        return None

    def closeEvent(self, event):
        """组件销毁时停止视频线程。"""
        self.set_fish_connection_available(False)
        event.accept()
