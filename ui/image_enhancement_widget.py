#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""原始视频与图像增强结果的左右同步对比组件。

组件既可接收现有 ``StereoVideoClient.frame_received`` 的 Pico 实时帧，也可循环播放
本地视频做 UI/算法演示。增强在线程中执行，队列只保留最新帧，避免处理速度低于采集
速度时累积不可控延迟。
"""

import json
import os
import threading
import time
from collections import deque
from pathlib import Path

import cv2
import numpy as np
from PyQt5.QtCore import QRect, QSize, QThread, QTimer, Qt, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from enhancers import MODEL_METHODS, create_enhancer


class MockVideoThread(QThread):
    """按源视频帧率循环读取本地视频。"""

    frame_ready = pyqtSignal(np.ndarray)
    status_changed = pyqtSignal(bool, str)
    source_info = pyqtSignal(float, int, int)

    def __init__(self, path, parent=None):
        """保存视频路径并初始化线程状态。"""
        super().__init__(parent)
        self.path = str(path)
        self.running = False
        self.paused = False

    def run(self):
        """打开视频并按照原始时间轴循环发送帧。"""
        capture = cv2.VideoCapture(self.path)
        if not capture.isOpened():
            self.status_changed.emit(False, f"无法打开 Mock 视频: {self.path}")
            return

        fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        period = 1.0 / max(float(fps), 1.0)
        self.running = True
        self.source_info.emit(float(fps), width, height)
        self.status_changed.emit(True, f"Mock: {Path(self.path).name}")
        next_frame_time = time.perf_counter()

        try:
            while self.running:
                if self.paused:
                    self.msleep(40)
                    next_frame_time = time.perf_counter()
                    continue

                ok, frame = capture.read()
                if not ok:
                    capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    next_frame_time = time.perf_counter()
                    continue

                self.frame_ready.emit(frame)
                next_frame_time += period
                delay = next_frame_time - time.perf_counter()
                if delay > 0:
                    self.msleep(max(1, int(delay * 1000)))
                elif delay < -period * 3:
                    next_frame_time = time.perf_counter()
        finally:
            capture.release()
            self.status_changed.emit(False, "Mock 视频已停止")

    def set_paused(self, paused):
        """设置播放暂停状态。"""
        self.paused = bool(paused)

    def stop(self):
        """请求线程停止。"""
        self.running = False


class EnhancementWorker(QThread):
    """在后台处理最新视频帧的低延迟增强线程。"""

    enhanced_ready = pyqtSignal(np.ndarray, np.ndarray, float, int)
    model_status_changed = pyqtSignal(str, str, str)

    def __init__(self, parent=None):
        """创建条件变量与单帧缓冲区。"""
        super().__init__(parent)
        self._condition = threading.Condition()
        self._pending = None
        self._running = True
        self._dropped = 0
        self._model_adapter = None
        self._active_model_id = None
        self._failed_model_id = None

    def submit(self, frame, parameters):
        """提交一帧；已有待处理帧时用新帧替换并计为丢帧。"""
        with self._condition:
            if self._pending is not None:
                self._dropped += 1
            self._pending = (frame.copy(), dict(parameters))
            self._condition.notify()

    def run(self):
        """等待新帧、执行增强并返回处理耗时。"""
        try:
            while True:
                with self._condition:
                    while self._pending is None and self._running:
                        self._condition.wait(timeout=0.5)
                    if not self._running:
                        return
                    frame, parameters = self._pending
                    self._pending = None
                    dropped = self._dropped

                started = time.perf_counter()
                enhanced = self._process_frame(frame, parameters)
                latency_ms = (time.perf_counter() - started) * 1000.0
                # 原帧随结果一起返回，确保上下两个窗口显示的是严格同一帧。
                self.enhanced_ready.emit(frame, enhanced, latency_ms, dropped)
        finally:
            self._release_model()

    def stop(self):
        """停止线程并唤醒等待状态。"""
        with self._condition:
            self._running = False
            self._pending = None
            self._condition.notify_all()

    def _release_model(self):
        """释放当前神经网络适配器及其显存。"""
        adapter = self._model_adapter
        self._model_adapter = None
        self._active_model_id = None
        if adapter is not None:
            adapter.close()

    def _ensure_model(self, model_id):
        """在工作线程中按需切换和加载指定模型。"""
        if self._active_model_id == model_id and self._model_adapter is not None:
            return True
        if self._failed_model_id == model_id:
            return False

        self._release_model()
        self._failed_model_id = None
        self.model_status_changed.emit(
            model_id, "loading", f"正在加载 {model_id} 模型与权重…")
        try:
            adapter = create_enhancer(model_id)
            adapter.load()
        except Exception as exc:
            self._failed_model_id = model_id
            self.model_status_changed.emit(model_id, "error", str(exc))
            return False
        self._model_adapter = adapter
        self._active_model_id = model_id
        self.model_status_changed.emit(model_id, "ready", adapter.status_text())
        return True

    @staticmethod
    def _region_height(frame, parameters):
        """根据处理区域和视频源类型计算需要增强的画面高度。"""
        region_mode = parameters.get("region", "auto")
        if region_mode == "stereo_top":
            return frame.shape[0] // 2
        if region_mode == "auto":
            source_mode = parameters.get("source_mode", "none")
            known_canvas = frame.shape[:2] == (960, 1280)
            if source_mode == "live" or known_canvas:
                return frame.shape[0] // 2
        return frame.shape[0]

    def _process_frame(self, frame, parameters):
        """调用传统算法或当前神经网络并统一执行强度混合。"""
        method = parameters.get("method", "traditional")
        if method not in MODEL_METHODS:
            if self._model_adapter is not None:
                self._release_model()
            if self._failed_model_id is not None:
                self._failed_model_id = None
            return self.apply_enhancement(frame, parameters)

        output = frame.copy()
        region_height = self._region_height(frame, parameters)
        source_region = frame[:region_height, :]
        if not self._ensure_model(method):
            return output
        stereo_pair = region_height < frame.shape[0]
        try:
            processed = self._model_adapter.process(
                source_region, stereo_pair=stereo_pair)
        except Exception as exc:
            self._release_model()
            self._failed_model_id = method
            self.model_status_changed.emit(
                method, "error", f"模型推理失败: {exc}")
            return output
        if processed.shape != source_region.shape:
            raise ValueError(
                f"模型输出尺寸 {processed.shape} 与输入 {source_region.shape} 不一致")
        strength = np.clip(
            float(parameters.get("strength", 100)) / 100.0, 0.0, 1.0)
        output[:region_height, :] = cv2.addWeighted(
            source_region, 1.0 - strength, processed, strength, 0)
        return output

    @staticmethod
    def _gray_world(image):
        """使用灰度世界假设校正 BGR 三通道平均值。"""
        work = image.astype(np.float32)
        means = work.reshape(-1, 3).mean(axis=0)
        target = float(means.mean())
        scales = target / np.maximum(means, 1.0)
        return np.clip(work * scales, 0, 255).astype(np.uint8)

    @staticmethod
    def _apply_clahe(image, clip_limit):
        """仅增强 LAB 明度通道，避免直接拉伸色彩通道。"""
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        lightness, channel_a, channel_b = cv2.split(lab)
        clahe = cv2.createCLAHE(
            clipLimit=max(float(clip_limit), 0.1), tileGridSize=(8, 8))
        lightness = clahe.apply(lightness)
        return cv2.cvtColor(
            cv2.merge((lightness, channel_a, channel_b)), cv2.COLOR_LAB2BGR)

    @staticmethod
    def _apply_gamma(image, gamma):
        """用查找表执行 Gamma 校正；大于 1 时提亮暗部。"""
        gamma = max(float(gamma), 0.1)
        table = np.array([
            ((index / 255.0) ** (1.0 / gamma)) * 255
            for index in range(256)
        ], dtype=np.uint8)
        return cv2.LUT(image, table)

    @staticmethod
    def _adjust_saturation(image, saturation):
        """在 HSV 空间调整饱和度。"""
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[:, :, 1] = np.clip(hsv[:, :, 1] * float(saturation), 0, 255)
        return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

    @classmethod
    def _process_region(cls, image, parameters):
        """根据所选算法处理一个 BGR 图像区域。"""
        algorithm = parameters.get("algorithm", "underwater")
        gamma = parameters.get("gamma", 1.15)
        contrast = parameters.get("contrast", 1.10)
        saturation = parameters.get("saturation", 1.12)
        clip_limit = parameters.get("clip_limit", 2.0)

        if algorithm == "none":
            processed = image.copy()
        elif algorithm == "white_balance":
            processed = cls._gray_world(image)
        elif algorithm == "gamma":
            processed = cls._apply_gamma(image, gamma)
        elif algorithm == "clahe":
            processed = cls._apply_clahe(image, clip_limit)
        else:
            processed = cls._gray_world(image)
            processed = cls._apply_clahe(processed, clip_limit)
            processed = cls._apply_gamma(processed, gamma)
            processed = cls._adjust_saturation(processed, saturation)
            processed = cv2.convertScaleAbs(processed, alpha=contrast, beta=0)
        return processed

    @classmethod
    def apply_enhancement(cls, frame, parameters):
        """增强整帧或双目画布上半部，并按强度与原图混合。"""
        output = frame.copy()
        region_height = cls._region_height(frame, parameters)
        source_region = frame[:region_height, :]
        processed = cls._process_region(source_region, parameters)
        strength = np.clip(float(parameters.get("strength", 70)) / 100.0, 0.0, 1.0)
        output[:region_height, :] = cv2.addWeighted(
            source_region, 1.0 - strength, processed, strength, 0)
        return output


class ComparisonVideoRecorder(QThread):
    """在独立线程中编码原图在左、增强图在右的 MP4 对比视频。"""

    recording_finished = pyqtSignal(str, int, float, int)
    recording_failed = pyqtSignal(str)

    def __init__(self, output_path, fps, parent=None):
        """保存输出参数并创建有界录像队列。"""
        super().__init__(parent)
        self.output_path = str(output_path)
        self.fps = max(float(fps), 1.0)
        self._condition = threading.Condition()
        self._queue = deque()
        self._accepting = True
        self._max_queue = 90
        self._dropped = 0

    def submit(self, original, enhanced):
        """提交严格同帧的一对图像；队列满时丢弃最旧录像帧。"""
        with self._condition:
            if not self._accepting:
                return
            if len(self._queue) >= self._max_queue:
                self._queue.popleft()
                self._dropped += 1
            self._queue.append((original.copy(), enhanced.copy()))
            self._condition.notify()

    def stop_recording(self):
        """停止接收新帧，并在写完队列后安全关闭编码器。"""
        with self._condition:
            self._accepting = False
            self._condition.notify_all()

    @staticmethod
    def compose_pair(original, enhanced):
        """生成带英文标签的左右对比帧，并保证编码尺寸为偶数。"""
        left = original.copy()
        right = enhanced.copy()
        if right.shape[:2] != left.shape[:2]:
            right = cv2.resize(right, (left.shape[1], left.shape[0]))

        for image, text in ((left, "ORIGINAL"), (right, "ENHANCED")):
            cv2.putText(image, text, (18, 38), cv2.FONT_HERSHEY_SIMPLEX,
                        0.95, (0, 0, 0), 4, cv2.LINE_AA)
            cv2.putText(image, text, (18, 38), cv2.FONT_HERSHEY_SIMPLEX,
                        0.95, (255, 255, 255), 2, cv2.LINE_AA)

        comparison = np.hstack((left, right))
        height, width = comparison.shape[:2]
        return comparison[:height - height % 2, :width - width % 2]

    def run(self):
        """持续取出帧对并写入 mp4v 编码的 MP4 文件。"""
        writer = None
        frame_count = 0
        failure = None
        try:
            while True:
                with self._condition:
                    while not self._queue and self._accepting:
                        self._condition.wait(timeout=0.5)
                    if not self._queue and not self._accepting:
                        break
                    original, enhanced = self._queue.popleft()

                comparison = self.compose_pair(original, enhanced)
                if writer is None:
                    height, width = comparison.shape[:2]
                    Path(self.output_path).parent.mkdir(parents=True, exist_ok=True)
                    writer = cv2.VideoWriter(
                        self.output_path,
                        cv2.VideoWriter_fourcc(*"mp4v"),
                        self.fps,
                        (width, height),
                    )
                    if not writer.isOpened():
                        failure = "当前 OpenCV 环境无法创建 MP4 编码器"
                        break
                writer.write(comparison)
                frame_count += 1
        except Exception as exc:
            failure = str(exc)
        finally:
            if writer is not None:
                writer.release()

        if failure:
            self.recording_failed.emit(failure)
            return
        if frame_count == 0:
            self.recording_failed.emit("没有收到可写入的同步视频帧")
            return

        duration = frame_count / self.fps
        try:
            file_size = os.path.getsize(self.output_path)
        except OSError:
            file_size = 0
        if file_size <= 0:
            self.recording_failed.emit("编码器未生成有效视频文件")
            return
        self.recording_finished.emit(
            self.output_path, frame_count, duration, self._dropped)


class VideoCanvas(QWidget):
    """只在既定控件范围内绘图、不让视频尺寸参与布局计算的画布。"""

    def __init__(self, parent=None):
        """创建具有固定最小高度和独立图像缓存的视频画布。"""
        super().__init__(parent)
        self._image = QImage()
        self._message = "等待视频源"
        self.setMinimumSize(0, 180)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def sizeHint(self):
        """返回与视频原始分辨率无关的紧凑建议尺寸。"""
        return QSize(1, 180)

    def minimumSizeHint(self):
        """允许画布横向压缩，同时保留基本可视高度。"""
        return QSize(0, 180)

    def set_frame(self, frame):
        """复制一帧 BGR 图像到画布缓存并请求重绘。"""
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        height, width, channels = rgb.shape
        self._image = QImage(
            rgb.data, width, height, channels * width,
            QImage.Format_RGB888).copy()
        self._message = ""
        self.update()

    def clear(self, message="等待视频源"):
        """清空当前图像并显示状态提示。"""
        self._image = QImage()
        self._message = str(message)
        self.update()

    def paintEvent(self, event):
        """在当前矩形内保持比例绘制图像，绝不修改自身几何尺寸。"""
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.fillRect(self.rect(), QColor("#17191c"))

        content = self.rect().adjusted(4, 4, -4, -4)
        if not self._image.isNull() and not content.isEmpty():
            scaled = self._image.size()
            scaled.scale(content.size(), Qt.KeepAspectRatio)
            target = QRect(0, 0, scaled.width(), scaled.height())
            target.moveCenter(content.center())
            painter.drawImage(target, self._image)
        elif self._message:
            painter.setPen(QColor("#aaaaaa"))
            painter.drawText(content, Qt.AlignCenter, self._message)

        painter.setPen(QPen(QColor("#555555"), 1))
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 4, 4)


class VideoPane(QWidget):
    """带标题、性能信息和快捷操作的视频显示面板。"""

    expand_requested = pyqtSignal(str)
    snapshot_requested = pyqtSignal(str)

    def __init__(self, pane_id, title, parent=None):
        """创建标题栏和保持比例的视频标签。"""
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.pane_id = pane_id
        self._frame = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        header = QHBoxLayout()
        self.title_label = QLabel(title)
        self.title_label.setFont(QFont("Arial", 11, QFont.Bold))
        self.meta_label = QLabel("等待视频帧")
        self.meta_label.setMinimumWidth(0)
        self.meta_label.setSizePolicy(
            QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.meta_label.setStyleSheet("color: #666;")
        expand_button = QPushButton("放大")
        expand_button.setMaximumWidth(58)
        expand_button.clicked.connect(
            lambda: self.expand_requested.emit(self.pane_id))
        snapshot_button = QPushButton("截图")
        snapshot_button.setMaximumWidth(58)
        snapshot_button.clicked.connect(
            lambda: self.snapshot_requested.emit(self.pane_id))
        header.addWidget(self.title_label)
        header.addWidget(self.meta_label, 1)
        header.addWidget(expand_button)
        header.addWidget(snapshot_button)
        layout.addLayout(header)

        self.image_label = VideoCanvas()
        layout.addWidget(self.image_label, 1)

    def set_frame(self, frame, fps=0.0, detail=""):
        """保存并显示一帧，同时更新元数据。"""
        self._frame = frame.copy()
        height, width = frame.shape[:2]
        fps_text = f"{fps:.1f} FPS" if fps > 0 else "-- FPS"
        suffix = f" | {detail}" if detail else ""
        meta_text = f"{width}×{height} | {fps_text}{suffix}"
        self.meta_label.setText(meta_text)
        self.meta_label.setToolTip(meta_text)
        self.image_label.set_frame(self._frame)

    def frame(self):
        """返回当前帧副本。"""
        return None if self._frame is None else self._frame.copy()

    def clear(self, message="等待视频源"):
        """清空当前帧并显示提示文字。"""
        self._frame = None
        self.image_label.clear(message)
        self.meta_label.setText("等待视频帧")
        self.meta_label.setToolTip("")


class FramePreviewDialog(QDialog):
    """持续显示指定帧提供器内容的最大化预览窗口。"""

    def __init__(self, title, frame_provider, parent=None):
        """创建预览标签并启动刷新定时器。"""
        super().__init__(parent)
        self.setWindowTitle(title)
        self._frame_provider = frame_provider
        self.label = QLabel("等待视频帧")
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setStyleSheet("background: #101214; color: #aaa;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.label)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._refresh)
        self.timer.start(33)
        self.showMaximized()

    def _refresh(self):
        """读取最新帧并按窗口尺寸显示。"""
        frame = self._frame_provider()
        if frame is None:
            return
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        height, width, channels = rgb.shape
        image = QImage(
            rgb.data, width, height, channels * width, QImage.Format_RGB888)
        self.label.setPixmap(QPixmap.fromImage(image).scaled(
            self.label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def keyPressEvent(self, event):
        """按 Esc 关闭预览。"""
        if event.key() == Qt.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)


class ImageEnhancementWidget(QWidget):
    """图像增强对比页：原图在左、增强图在右。"""

    def __init__(self, mock_video_path=None, parent=None):
        """构建界面、启动增强线程并可选自动播放 Mock 视频。"""
        super().__init__(parent)
        self._mock_thread = None
        self._mock_paused = False
        self._live_connected = False
        self._source_mode = "none"
        self._source_description = "未连接"
        self._source_nominal_fps = 0.0
        self._latest_source_frame = None
        self._original_frame = None
        self._enhanced_frame = None
        self._input_count = 0
        self._output_count = 0
        self._input_fps = 0.0
        self._output_fps = 0.0
        self._last_rate_time = time.perf_counter()
        self._latency_ms = 0.0
        self._dropped = 0
        self._preview_dialogs = []
        self._recorder = None
        self._closing = False

        self._worker = EnhancementWorker(self)
        self._worker.enhanced_ready.connect(
            self._on_enhanced_ready, Qt.QueuedConnection)
        self._worker.model_status_changed.connect(
            self._on_model_status_changed, Qt.QueuedConnection)
        self._worker.start()

        self._init_ui()
        self._stats_timer = QTimer(self)
        self._stats_timer.timeout.connect(self._refresh_statistics)
        self._stats_timer.start(500)

        if mock_video_path and os.path.isfile(mock_video_path):
            QTimer.singleShot(0, lambda: self.start_mock_video(mock_video_path))

    def _init_ui(self):
        """创建紧凑控制区、上下视频窗和底部状态区。"""
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        control_group = QGroupBox("图像增强控制")
        control_grid = QGridLayout(control_group)
        control_grid.setHorizontalSpacing(8)
        control_grid.setVerticalSpacing(5)

        self.source_status = QLabel("● 视频源未连接")
        self.source_status.setMinimumWidth(0)
        self.source_status.setSizePolicy(
            QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.source_status.setToolTip("视频源未连接")
        self.source_status.setStyleSheet("color: #888; font-weight: bold;")
        self.load_mock_button = QPushButton("加载 Mock 视频")
        self.load_mock_button.clicked.connect(self._select_mock_video)
        self.pause_mock_button = QPushButton("暂停 Mock")
        self.pause_mock_button.setEnabled(False)
        self.pause_mock_button.clicked.connect(self._toggle_mock_pause)
        self.stop_mock_button = QPushButton("停止 Mock")
        self.stop_mock_button.setEnabled(False)
        self.stop_mock_button.clicked.connect(self.stop_mock_video)
        control_grid.addWidget(self.source_status, 0, 0, 1, 2)
        control_grid.addWidget(self.load_mock_button, 0, 2)
        control_grid.addWidget(self.pause_mock_button, 0, 3)
        control_grid.addWidget(self.stop_mock_button, 0, 4)

        self.enable_checkbox = QCheckBox("启用增强")
        self.enable_checkbox.setChecked(True)
        self.enable_checkbox.toggled.connect(self._settings_changed)

        self.method_combo = QComboBox()
        self.method_combo.addItem("传统图像增强", "traditional")
        model_options = (
            ("UIEC²-Net", "uiec2", True,
             "CUDA实时模式，内部按 320×240/目推理"),
            ("U-shape Transformer", "ushape", True,
             "CUDA实时模式，固定 256×256/目；已知可能出现网格伪影"),
            ("Ucolor", "ucolor", True,
             "ONNX Runtime CUDA 模式，固定 256×256/目；双目逐目推理"),
            ("LightUcolorRetinex（待接入）", "light_ucolor_retinex", False,
             "等待算法和最终权重确定"),
        )
        for display_name, model_id, enabled, tooltip in model_options:
            self.method_combo.addItem(display_name, model_id)
            item = self.method_combo.model().item(self.method_combo.count() - 1)
            item.setEnabled(enabled)
            item.setToolTip(tooltip)
        self.method_combo.addItem("不处理", "none")
        self.method_combo.currentIndexChanged.connect(self._method_changed)
        self._last_method = "traditional"

        self.traditional_mode_label = QLabel("传统模式:")
        self.traditional_mode_combo = QComboBox()
        self.traditional_mode_combo.addItem("水下综合增强", "underwater")
        self.traditional_mode_combo.addItem("CLAHE 局部对比度", "clahe")
        self.traditional_mode_combo.addItem("Gamma 明暗校正", "gamma")
        self.traditional_mode_combo.addItem("灰度世界白平衡", "white_balance")
        self.traditional_mode_combo.currentIndexChanged.connect(
            self._traditional_mode_changed)

        self.preset_label = QLabel("示例预设:")
        self.preset_combo = QComboBox()
        self.preset_combo.addItems([
            "浑浊水体（示例）", "清水（示例）", "偏蓝绿色（示例）",
            "低照度（示例）", "自定义",
        ])
        self.preset_combo.currentTextChanged.connect(self._apply_preset)
        control_grid.addWidget(self.enable_checkbox, 1, 0)
        control_grid.addWidget(QLabel("增强方法:"), 1, 1)
        control_grid.addWidget(self.method_combo, 1, 2, 1, 3)
        control_grid.addWidget(self.traditional_mode_label, 2, 0)
        control_grid.addWidget(self.traditional_mode_combo, 2, 1, 1, 2)
        control_grid.addWidget(self.preset_label, 2, 3)
        control_grid.addWidget(self.preset_combo, 2, 4)

        self.strength_slider = QSlider(Qt.Horizontal)
        self.strength_slider.setRange(0, 100)
        self.strength_slider.setValue(70)
        self.strength_slider.valueChanged.connect(self._on_strength_changed)
        self.strength_label = QLabel("70%")
        self.advanced_button = QPushButton("高级参数")
        self.advanced_button.setCheckable(True)
        self.advanced_button.toggled.connect(self._toggle_advanced)
        self.reset_button = QPushButton("恢复默认")
        self.reset_button.clicked.connect(self._reset_defaults)
        self.strength_title_label = QLabel("增强强度:")
        control_grid.addWidget(self.strength_title_label, 3, 0)
        control_grid.addWidget(self.strength_slider, 3, 1, 1, 3)
        control_grid.addWidget(self.strength_label, 3, 4)
        control_grid.addWidget(self.advanced_button, 0, 5)
        control_grid.addWidget(self.reset_button, 1, 5, 3, 1)
        control_grid.setColumnStretch(1, 1)
        control_grid.setColumnStretch(2, 1)
        root.addWidget(control_group)

        self.advanced_group = QGroupBox("传统方法高级参数")
        advanced = QGridLayout(self.advanced_group)
        self.gamma_spin = self._make_spin(0.10, 3.00, 1.15, 0.05)
        self.contrast_spin = self._make_spin(0.50, 2.00, 1.10, 0.05)
        self.saturation_spin = self._make_spin(0.00, 2.50, 1.12, 0.05)
        self.clip_spin = self._make_spin(0.10, 8.00, 2.00, 0.10)
        self.region_combo = QComboBox()
        self.region_combo.addItem("自动（实时双目仅上半部）", "auto")
        self.region_combo.addItem("整张画面", "full")
        self.region_combo.addItem("仅双目图区域（上半部）", "stereo_top")
        for spin in (self.gamma_spin, self.contrast_spin,
                     self.saturation_spin, self.clip_spin):
            spin.valueChanged.connect(self._mark_custom_and_refresh)
        self.region_combo.currentIndexChanged.connect(self._settings_changed)
        self.gamma_label = QLabel("Gamma:")
        self.contrast_label = QLabel("对比度:")
        self.saturation_label = QLabel("饱和度:")
        self.clip_label = QLabel("CLAHE:")
        advanced.addWidget(self.gamma_label, 0, 0)
        advanced.addWidget(self.gamma_spin, 0, 1)
        advanced.addWidget(self.contrast_label, 0, 2)
        advanced.addWidget(self.contrast_spin, 0, 3)
        advanced.addWidget(self.saturation_label, 0, 4)
        advanced.addWidget(self.saturation_spin, 0, 5)
        advanced.addWidget(self.clip_label, 0, 6)
        advanced.addWidget(self.clip_spin, 0, 7)
        advanced.addWidget(QLabel("处理区域:"), 0, 8)
        advanced.addWidget(self.region_combo, 0, 9)
        self.advanced_group.setVisible(False)
        root.addWidget(self.advanced_group)

        self.model_status_label = QLabel("算法状态: 传统方法就绪")
        self.model_status_label.setStyleSheet("color: #555;")
        control_grid.addWidget(self.model_status_label, 4, 0, 1, 6)
        self._update_algorithm_controls()

        self.video_layout = QHBoxLayout()
        self.video_layout.setContentsMargins(0, 0, 0, 0)
        self.video_layout.setSpacing(6)
        self.original_pane = VideoPane("original", "原始画面")
        self.enhanced_pane = VideoPane("enhanced", "增强画面")
        self.original_pane.expand_requested.connect(self._open_preview)
        self.enhanced_pane.expand_requested.connect(self._open_preview)
        self.original_pane.snapshot_requested.connect(self._save_single_snapshot)
        self.enhanced_pane.snapshot_requested.connect(self._save_single_snapshot)
        self.video_layout.addWidget(self.original_pane, 1)
        self.video_layout.addWidget(self.enhanced_pane, 1)
        root.addLayout(self.video_layout, 1)

        action_row = QHBoxLayout()
        self.save_compare_button = QPushButton("保存对比截图")
        self.save_compare_button.clicked.connect(self._save_comparison_snapshot)
        self.record_compare_button = QPushButton("开始保存对比视频")
        self.record_compare_button.clicked.connect(
            self._toggle_comparison_recording)
        self.export_params_button = QPushButton("导出增强参数")
        self.export_params_button.clicked.connect(self._export_parameters)
        self.record_status_label = QLabel("录像: 未开始")
        self.record_status_label.setStyleSheet("color: #666;")
        self.low_latency_label = QLabel("模式: 实时优先（只处理最新帧）")
        self.low_latency_label.setStyleSheet("color: #555;")
        action_row.addWidget(self.save_compare_button)
        action_row.addWidget(self.record_compare_button)
        action_row.addWidget(self.export_params_button)
        action_row.addWidget(self.record_status_label)
        action_row.addStretch()
        action_row.addWidget(self.low_latency_label)
        root.addLayout(action_row)

        status_group = QGroupBox("实时性能")
        status_layout = QHBoxLayout(status_group)
        self.input_fps_label = QLabel("输入: -- FPS")
        self.output_fps_label = QLabel("增强: -- FPS")
        self.latency_label = QLabel("处理耗时: -- ms")
        self.drop_label = QLabel("丢弃旧帧: 0")
        self.frame_status_label = QLabel("帧同步: 等待")
        for label in (self.input_fps_label, self.output_fps_label,
                      self.latency_label, self.drop_label,
                      self.frame_status_label):
            status_layout.addWidget(label)
        status_layout.addStretch()
        root.addWidget(status_group)

    @staticmethod
    def _make_spin(minimum, maximum, value, step):
        """创建统一样式的小数参数输入框。"""
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        spin.setSingleStep(step)
        spin.setDecimals(2)
        return spin

    def _toggle_advanced(self, visible):
        """展开或收起高级参数区域。"""
        self.advanced_group.setVisible(bool(visible))
        self.advanced_button.setText("收起参数" if visible else "高级参数")

    def _method_changed(self):
        """切换一级增强方法并更新其可用的二级控制。"""
        method = self.method_combo.currentData()
        previous = self._last_method
        self._last_method = method
        if method in ("uiec2", "ushape", "ucolor") and previous != method:
            self.strength_slider.setValue(100)
            self.model_status_label.setText("算法状态: 等待视频帧后加载模型")
            self.model_status_label.setStyleSheet("color: #b36b00;")
        elif method == "traditional" and previous != "traditional":
            self.strength_slider.setValue(70)
            self.model_status_label.setText("算法状态: 传统方法就绪")
            self.model_status_label.setStyleSheet("color: #555;")
        elif method == "none":
            self.model_status_label.setText("算法状态: 不处理，直接显示原图")
            self.model_status_label.setStyleSheet("color: #555;")
        self._update_algorithm_controls()
        self._settings_changed()

    @pyqtSlot(str, str, str)
    def _on_model_status_changed(self, model_id, state, message):
        """显示后台模型加载、就绪或失败状态。"""
        if self.method_combo.currentData() != model_id:
            return
        colors = {
            "loading": "#b36b00",
            "ready": "#159447",
            "error": "#c0392b",
        }
        self.model_status_label.setText(f"算法状态: {message}")
        self.model_status_label.setStyleSheet(
            f"color: {colors.get(state, '#555')}; font-weight: bold;")

    def _traditional_mode_changed(self):
        """切换传统算法模式并联动预设和高级参数。"""
        self._update_algorithm_controls()
        self._settings_changed()

    def _update_algorithm_controls(self):
        """只显示当前方法真正会使用的控件并禁用无效参数。"""
        method = self.method_combo.currentData()
        traditional = method == "traditional"
        mode = self.traditional_mode_combo.currentData()
        comprehensive = traditional and mode == "underwater"

        self.traditional_mode_label.setVisible(traditional)
        self.traditional_mode_combo.setVisible(traditional)
        self.preset_label.setVisible(comprehensive)
        self.preset_combo.setVisible(comprehensive)
        self.advanced_button.setVisible(traditional)
        self.strength_title_label.setEnabled(method != "none")
        self.strength_slider.setEnabled(method != "none")
        self.strength_label.setEnabled(method != "none")

        if not traditional:
            self.advanced_button.setChecked(False)

        enabled_fields = {
            "gamma": comprehensive or mode == "gamma",
            "contrast": comprehensive,
            "saturation": comprehensive,
            "clahe": comprehensive or mode == "clahe",
        }
        for key, label, spin in (
                ("gamma", self.gamma_label, self.gamma_spin),
                ("contrast", self.contrast_label, self.contrast_spin),
                ("saturation", self.saturation_label, self.saturation_spin),
                ("clahe", self.clip_label, self.clip_spin)):
            enabled = traditional and enabled_fields[key]
            label.setEnabled(enabled)
            spin.setEnabled(enabled)

    def _on_strength_changed(self, value):
        """同步强度数值文本并刷新增强。"""
        self.strength_label.setText(f"{value}%")
        self._settings_changed()

    def _mark_custom_and_refresh(self):
        """手动参数变化时切到自定义预设并刷新。"""
        if (self.method_combo.currentData() == "traditional"
                and self.traditional_mode_combo.currentData() == "underwater"):
            self.preset_combo.blockSignals(True)
            self.preset_combo.setCurrentText("自定义")
            self.preset_combo.blockSignals(False)
        self._settings_changed()

    def _apply_preset(self, name):
        """把场景预设映射为一组可继续微调的参数。"""
        if (self.method_combo.currentData() != "traditional"
                or self.traditional_mode_combo.currentData() != "underwater"):
            return
        presets = {
            "浑浊水体（示例）": (70, 1.15, 1.10, 1.12, 2.00),
            "清水（示例）": (45, 1.05, 1.04, 1.05, 1.40),
            "偏蓝绿色（示例）": (75, 1.12, 1.12, 1.18, 2.20),
            "低照度（示例）": (72, 1.35, 1.08, 1.08, 2.40),
        }
        if name not in presets:
            return
        values = presets[name]
        widgets = (self.strength_slider, self.gamma_spin, self.contrast_spin,
                   self.saturation_spin, self.clip_spin)
        for widget in widgets:
            widget.blockSignals(True)
        self.strength_slider.setValue(values[0])
        self.gamma_spin.setValue(values[1])
        self.contrast_spin.setValue(values[2])
        self.saturation_spin.setValue(values[3])
        self.clip_spin.setValue(values[4])
        for widget in widgets:
            widget.blockSignals(False)
        self.strength_label.setText(f"{values[0]}%")
        self._settings_changed()

    def _reset_defaults(self):
        """恢复默认综合增强参数。"""
        self.method_combo.setCurrentIndex(0)
        self.traditional_mode_combo.setCurrentIndex(0)
        self.preset_combo.setCurrentText("浑浊水体（示例）")
        self.enable_checkbox.setChecked(True)
        self._update_algorithm_controls()

    def _parameters(self):
        """收集当前增强参数。"""
        method = self.method_combo.currentData()
        traditional_mode = self.traditional_mode_combo.currentData()
        algorithm = traditional_mode if method == "traditional" else "none"
        algorithm_name = (self.traditional_mode_combo.currentText()
                          if method == "traditional"
                          else self.method_combo.currentText())
        return {
            "enabled": self.enable_checkbox.isChecked(),
            "method": method,
            "method_name": self.method_combo.currentText(),
            "algorithm": algorithm,
            "algorithm_name": algorithm_name,
            "preset": self.preset_combo.currentText(),
            "strength": self.strength_slider.value(),
            "gamma": self.gamma_spin.value(),
            "contrast": self.contrast_spin.value(),
            "saturation": self.saturation_spin.value(),
            "clip_limit": self.clip_spin.value(),
            "region": self.region_combo.currentData(),
            "region_name": self.region_combo.currentText(),
            "source_mode": self._source_mode,
        }

    def _settings_changed(self):
        """参数变化时立即用当前原图刷新增强结果。"""
        source = self._latest_source_frame
        if source is None:
            source = self._original_frame
        if source is None:
            return
        if self.enable_checkbox.isChecked():
            self._worker.submit(source, self._parameters())
        else:
            self._original_frame = source.copy()
            self._enhanced_frame = source.copy()
            self.original_pane.set_frame(
                self._original_frame, self._input_fps, self._source_description)
            self.enhanced_pane.set_frame(
                self._enhanced_frame, self._input_fps, "增强关闭")
            self._submit_recording_pair(
                self._original_frame, self._enhanced_frame)

    def _select_mock_video(self):
        """选择并播放本地 Mock 视频。"""
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 Mock 视频", "", "视频文件 (*.mp4 *.avi *.mov *.mkv)")
        if path:
            self.start_mock_video(path)

    def start_mock_video(self, path):
        """停止旧 Mock 后循环播放给定视频。"""
        if not os.path.isfile(path):
            QMessageBox.warning(self, "Mock 视频", f"文件不存在:\n{path}")
            return
        self.stop_mock_video()
        self._source_mode = "mock"
        self._mock_paused = False
        self._mock_thread = MockVideoThread(path, self)
        self._mock_thread.frame_ready.connect(
            self._on_source_frame, Qt.QueuedConnection)
        self._mock_thread.status_changed.connect(
            self._on_mock_status, Qt.QueuedConnection)
        self._mock_thread.source_info.connect(
            self._on_source_info, Qt.QueuedConnection)
        self._mock_thread.start()
        self.pause_mock_button.setEnabled(True)
        self.stop_mock_button.setEnabled(True)
        self.pause_mock_button.setText("暂停 Mock")

    def stop_mock_video(self):
        """停止本地 Mock，之后恢复接收 Pico 实时帧。"""
        thread = self._mock_thread
        self._mock_thread = None
        if thread is not None:
            thread.stop()
            thread.wait(2000)
            thread.deleteLater()
        self._mock_paused = False
        self.pause_mock_button.setEnabled(False)
        self.stop_mock_button.setEnabled(False)
        self.pause_mock_button.setText("暂停 Mock")
        if self._live_connected:
            self._source_mode = "live"
            self._set_source_status(True, "Pico 实时视频流")
        else:
            self._source_mode = "none"
            self._set_source_status(False, "未连接")

    def _toggle_mock_pause(self):
        """暂停或继续 Mock 视频。"""
        if self._mock_thread is None:
            return
        self._mock_paused = not self._mock_paused
        self._mock_thread.set_paused(self._mock_paused)
        self.pause_mock_button.setText("继续 Mock" if self._mock_paused else "暂停 Mock")

    @pyqtSlot(bool, str)
    def _on_mock_status(self, connected, message):
        """显示 Mock 视频打开或停止状态。"""
        if self._source_mode == "mock" or connected:
            self._set_source_status(connected, message)

    @pyqtSlot(float, int, int)
    def _on_source_info(self, fps, width, height):
        """保存 Mock 视频标称参数。"""
        self._source_nominal_fps = fps
        self.frame_status_label.setText(
            f"源: {width}×{height} @ {fps:.1f} FPS")

    def _set_source_status(self, connected, description):
        """统一更新视频源状态标签。"""
        self._source_description = description
        color = "#159447" if connected else "#888"
        prefix = "●" if connected else "○"
        self.source_status.setText(f"{prefix} {description}")
        self.source_status.setToolTip(description)
        self.source_status.setStyleSheet(
            f"color: {color}; font-weight: bold;")

    @pyqtSlot(bool, str)
    def set_live_connection_status(self, connected, message):
        """接收现有 Pico 视频客户端的连接状态。"""
        self._live_connected = bool(connected)
        if self._source_mode != "mock":
            self._source_mode = "live" if connected else "none"
            self._set_source_status(
                connected, "Pico 实时视频流" if connected else message)

    @pyqtSlot(np.ndarray)
    def push_live_frame(self, frame):
        """接收现有 9998 视频流；Mock 播放时暂不覆盖 Mock。"""
        if self._source_mode == "mock":
            return
        self._source_mode = "live"
        self._set_source_status(True, "Pico 实时视频流")
        self._on_source_frame(frame)

    @pyqtSlot(np.ndarray)
    def _on_source_frame(self, frame):
        """显示原图并向增强线程提交最新帧。"""
        self._latest_source_frame = frame.copy()
        self._input_count += 1
        if self.enable_checkbox.isChecked():
            self._worker.submit(frame, self._parameters())
        else:
            self._original_frame = frame.copy()
            self._enhanced_frame = frame.copy()
            self._output_count += 1
            self.original_pane.set_frame(
                self._original_frame, self._input_fps, self._source_description)
            self.enhanced_pane.set_frame(
                self._enhanced_frame, self._input_fps, "增强关闭")

    @pyqtSlot(np.ndarray, np.ndarray, float, int)
    def _on_enhanced_ready(self, original, enhanced, latency_ms, dropped):
        """同步显示同一原帧及其增强结果，并更新性能统计。"""
        self._original_frame = original.copy()
        self._enhanced_frame = enhanced.copy()
        self._latency_ms = latency_ms
        self._dropped = dropped
        self._output_count += 1
        self.original_pane.set_frame(
            self._original_frame, self._input_fps, self._source_description)
        self.enhanced_pane.set_frame(
            self._enhanced_frame, self._output_fps,
            f"{self._parameters()['algorithm_name']} | {latency_ms:.1f} ms")
        self._submit_recording_pair(
            self._original_frame, self._enhanced_frame)

    def _refresh_statistics(self):
        """按固定时间窗计算输入和增强输出帧率。"""
        now = time.perf_counter()
        elapsed = now - self._last_rate_time
        if elapsed < 0.9:
            return
        self._input_fps = self._input_count / elapsed
        self._output_fps = self._output_count / elapsed
        self._input_count = 0
        self._output_count = 0
        self._last_rate_time = now
        self.input_fps_label.setText(f"输入: {self._input_fps:.1f} FPS")
        self.output_fps_label.setText(f"增强: {self._output_fps:.1f} FPS")
        self.latency_label.setText(f"处理耗时: {self._latency_ms:.1f} ms")
        self.drop_label.setText(f"丢弃旧帧: {self._dropped}")
        if self._original_frame is not None and self._enhanced_frame is not None:
            self.frame_status_label.setText("帧同步: 严格同帧")

    def _frame_for(self, pane_id):
        """按面板标识返回对应帧。"""
        frame = self._original_frame if pane_id == "original" else self._enhanced_frame
        return None if frame is None else frame.copy()

    @pyqtSlot(str)
    def _open_preview(self, pane_id):
        """打开持续刷新的最大化单画面窗口。"""
        title = "原始画面（Esc退出）" if pane_id == "original" else "增强画面（Esc退出）"
        dialog = FramePreviewDialog(
            title, lambda: self._frame_for(pane_id), self)
        dialog.finished.connect(
            lambda _result, item=dialog: self._discard_preview(item))
        self._preview_dialogs.append(dialog)
        dialog.show()

    def _discard_preview(self, dialog):
        """从预览窗口引用列表移除已关闭窗口。"""
        if dialog in self._preview_dialogs:
            self._preview_dialogs.remove(dialog)

    @pyqtSlot(str)
    def _save_single_snapshot(self, pane_id):
        """保存原始或增强画面截图。"""
        frame = self._frame_for(pane_id)
        if frame is None:
            QMessageBox.warning(self, "保存截图", "当前没有可保存的视频帧")
            return
        default_name = time.strftime(
            "%Y%m%d_%H%M%S_") + ("original.jpg" if pane_id == "original" else "enhanced.jpg")
        path, _ = QFileDialog.getSaveFileName(
            self, "保存截图", default_name, "JPEG 图像 (*.jpg);;PNG 图像 (*.png)")
        if path and self._write_image(path, frame):
            QMessageBox.information(self, "保存完成", f"截图已保存到:\n{path}")

    def _save_comparison_snapshot(self):
        """把原图和增强图左右拼接后保存。"""
        if self._original_frame is None or self._enhanced_frame is None:
            QMessageBox.warning(self, "保存对比图", "原始画面或增强画面尚未就绪")
            return
        comparison = ComparisonVideoRecorder.compose_pair(
            self._original_frame, self._enhanced_frame)
        default_name = time.strftime("%Y%m%d_%H%M%S_compare.jpg")
        path, _ = QFileDialog.getSaveFileName(
            self, "保存左右对比图", default_name,
            "JPEG 图像 (*.jpg);;PNG 图像 (*.png)")
        if path and self._write_image(path, comparison):
            QMessageBox.information(self, "保存完成", f"对比图已保存到:\n{path}")

    def _toggle_comparison_recording(self):
        """开始录像，或停止当前录像并等待编码线程收尾。"""
        if self._recorder is not None:
            self._stop_comparison_recording()
        else:
            self._start_comparison_recording()

    def _start_comparison_recording(self):
        """选择 MP4 路径并启动左右对比视频编码线程。"""
        if self._original_frame is None or self._enhanced_frame is None:
            QMessageBox.warning(self, "保存对比视频", "请先等待原始和增强画面显示")
            return

        default_name = time.strftime("%Y%m%d_%H%M%S_compare.mp4")
        path, _ = QFileDialog.getSaveFileName(
            self, "保存左右对比视频", default_name, "MP4 视频 (*.mp4)")
        if not path:
            return
        if not path.lower().endswith(".mp4"):
            path += ".mp4"

        measured_fps = self._output_fps if self._output_fps >= 1.0 else 0.0
        if measured_fps <= 0.0:
            measured_fps = self._source_nominal_fps or 25.0
        # 综合增强约 25~30FPS；录像声明帧率不高于25可避免回放速度偏快。
        recording_fps = max(1.0, min(float(measured_fps), 25.0))
        self._recorder = ComparisonVideoRecorder(path, recording_fps, self)
        self._recorder.recording_finished.connect(
            self._on_recording_finished, Qt.QueuedConnection)
        self._recorder.recording_failed.connect(
            self._on_recording_failed, Qt.QueuedConnection)
        self._recorder.start()
        self.record_compare_button.setText("停止并保存视频")
        self.record_compare_button.setStyleSheet(
            "QPushButton {background-color: #d9534f; color: white; font-weight: bold;}")
        self.record_status_label.setText(f"录像: 进行中 ({recording_fps:.1f} FPS)")
        self.record_status_label.setStyleSheet("color: #c0392b; font-weight: bold;")

    def _submit_recording_pair(self, original, enhanced):
        """把严格同帧的原图/增强图交给录像线程。"""
        if self._recorder is not None:
            self._recorder.submit(original, enhanced)

    def _stop_comparison_recording(self):
        """停止接收录像帧并异步完成剩余编码。"""
        if self._recorder is None:
            return
        self._recorder.stop_recording()
        self.record_compare_button.setEnabled(False)
        self.record_status_label.setText("录像: 正在完成编码…")

    @pyqtSlot(str, int, float, int)
    def _on_recording_finished(self, path, frame_count, duration, dropped):
        """录像成功后恢复按钮并报告保存结果。"""
        recorder = self._recorder
        self._recorder = None
        if recorder is not None:
            recorder.deleteLater()
        self.record_compare_button.setEnabled(True)
        self.record_compare_button.setText("开始保存对比视频")
        self.record_compare_button.setStyleSheet("")
        self.record_status_label.setText(
            f"录像: 已保存 {frame_count} 帧 / {duration:.1f}s")
        self.record_status_label.setStyleSheet("color: #159447; font-weight: bold;")
        if not self._closing:
            QMessageBox.information(
                self, "对比视频保存完成",
                f"视频已保存到:\n{path}\n\n"
                f"帧数: {frame_count}\n时长: {duration:.2f} 秒\n"
                f"录像队列丢帧: {dropped}")

    @pyqtSlot(str)
    def _on_recording_failed(self, message):
        """录像失败后恢复按钮并显示错误。"""
        recorder = self._recorder
        self._recorder = None
        if recorder is not None:
            recorder.deleteLater()
        self.record_compare_button.setEnabled(True)
        self.record_compare_button.setText("开始保存对比视频")
        self.record_compare_button.setStyleSheet("")
        self.record_status_label.setText("录像: 保存失败")
        self.record_status_label.setStyleSheet("color: #c0392b; font-weight: bold;")
        if not self._closing:
            QMessageBox.critical(self, "保存对比视频失败", message)

    @staticmethod
    def _write_image(path, frame):
        """用 imencode 支持包含中文字符的 Windows 路径。"""
        extension = Path(path).suffix.lower() or ".jpg"
        if extension not in (".jpg", ".jpeg", ".png"):
            extension = ".jpg"
            path += extension
        ok, encoded = cv2.imencode(extension, frame)
        if not ok:
            return False
        encoded.tofile(path)
        return True

    def _export_parameters(self):
        """把当前增强设置和性能数据导出为 JSON。"""
        default_name = time.strftime("%Y%m%d_%H%M%S_enhancement.json")
        path, _ = QFileDialog.getSaveFileName(
            self, "导出增强参数", default_name, "JSON 文件 (*.json)")
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"
        payload = self._parameters()
        payload.update({
            "source": self._source_description,
            "input_fps": round(self._input_fps, 3),
            "enhanced_fps": round(self._output_fps, 3),
            "latency_ms": round(self._latency_ms, 3),
            "dropped_frames": self._dropped,
            "exported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        })
        Path(path).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        QMessageBox.information(self, "导出完成", f"参数已保存到:\n{path}")

    def shutdown(self):
        """停止 Mock、增强线程及预览窗口。"""
        self._closing = True
        self._stats_timer.stop()
        self.stop_mock_video()
        if self._recorder is not None:
            recorder = self._recorder
            recorder.stop_recording()
            recorder.wait(5000)
            self._recorder = None
        for dialog in list(self._preview_dialogs):
            dialog.close()
        self._worker.stop()
        self._worker.wait(3000)

    def closeEvent(self, event):
        """组件关闭时释放后台线程。"""
        self.shutdown()
        event.accept()
