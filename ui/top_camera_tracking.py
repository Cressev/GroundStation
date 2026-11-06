"""Display-only overhead camera tracking; no connection to fish controls."""

import math
import copy
import json
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import cv2
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QSettings, QStandardPaths
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel,
                             QLineEdit, QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget)

from vision.top_tracker import VelocityEstimator, candidates, follow_pair, nearest_marker, pose
from vision import planar_calibration as calibration
from stereo.recording import TimestampedH264Writer
from ui.save_paths import default_export_path, validate_label


class FrameReader:
    """Own capture on a daemon thread and retain only the newest frame."""

    def __init__(self, source):
        self.source = source
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.lock = threading.Lock()
        self.frame = None
        self.timestamp = None
        self.sequence = 0
        self.status = '正在打开视频源…'
        self.thread = threading.Thread(target=self.run, daemon=True)

    def start(self):
        self.thread.start()

    def run(self):
        cap = None
        try:
            if isinstance(self.source, int):
                cap = cv2.VideoCapture(self.source, cv2.CAP_DSHOW)
                if cap.isOpened():
                    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 2592)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1944)
                    cap.set(cv2.CAP_PROP_FPS, 30)
            else:
                cap = cv2.VideoCapture(self.source)
            if not cap.isOpened():
                self.status = '无法打开视频源，请检查设备编号、连接或占用情况'
                return
            fps = cap.get(cv2.CAP_PROP_FPS) or 30
            fps = fps if 1 <= fps <= 120 else 30
            self.status = '视频已打开，请依次选择中段靠鱼头的点和靠鱼尾的点'
            while not self.stop_event.is_set():
                if self.pause_event.is_set() and not isinstance(self.source, int):
                    self.stop_event.wait(.05)
                    continue
                start = time.monotonic()
                ok, frame = cap.read()
                if not ok:
                    self.status = '视频结束或读取失败'
                    break
                # Keep draining a live camera while the displayed image is frozen.
                if self.pause_event.is_set():
                    continue
                timestamp = (time.monotonic() if isinstance(self.source, int)
                             else cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0)
                with self.lock:
                    self.frame = frame
                    self.timestamp = timestamp
                    self.sequence += 1
                if not isinstance(self.source, int):
                    self.stop_event.wait(max(0, 1 / fps - (time.monotonic() - start)))
        except Exception as exc:
            self.status = f'视频错误：{exc}'
        finally:
            if cap is not None:
                cap.release()

    def latest(self):
        with self.lock:
            return self.sequence, self.frame, self.timestamp

    def stop(self):
        self.stop_event.set()


class ClickableImage(QLabel):
    clicked = pyqtSignal(float, float)

    def __init__(self):
        super().__init__('请打开顶部相机或视频文件')
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(320, 240)
        self._image = None

    def set_frame(self, frame):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        self._image = QImage(rgb.data, w, h, rgb.strides[0], QImage.Format_RGB888).copy()
        self._refresh()

    def _refresh(self):
        if self._image is not None:
            self.setPixmap(QPixmap.fromImage(self._image).scaled(
                self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh()

    def mousePressEvent(self, event):
        pixmap = self.pixmap()
        if pixmap is None or self._image is None:
            return
        left = (self.width() - pixmap.width()) / 2
        top = (self.height() - pixmap.height()) / 2
        x, y = event.pos().x() - left, event.pos().y() - top
        if 0 <= x < pixmap.width() and 0 <= y < pixmap.height():
            self.clicked.emit(x * self._image.width() / pixmap.width(),
                              y * self._image.height() / pixmap.height())


class TopCameraTrackingWidget(QWidget):
    calibration_finished = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.reader = None
        self.active = False
        self.sequence = -1
        self.frame = None
        self.raw_frame = None
        self.markers = []
        self.head = self.tail = None
        self.selecting = 'head'
        self.trail = deque(maxlen=5000)
        self.velocity = VelocityEstimator()
        self._gap = True
        self._last_frame_time = 0
        self.calibration = None
        self.calibration_path = None
        self.calibration_views = []
        self.view_size = None
        self.pending_plane = None
        self.measurement_points = []
        self.calibration_busy = False
        self._generation = 0
        self.record_worker = None
        self.record_path = None
        self.recording = False
        self._settings = QSettings('FishRobot', 'TopCameraTracking')
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel('USB 摄像头编号'))
        self.camera_index = QSpinBox()
        self.camera_index.setRange(0, 20)
        row.addWidget(self.camera_index)
        self.open_camera = QPushButton('打开摄像头')
        self.open_camera.clicked.connect(lambda: self.open_source(self.camera_index.value()))
        row.addWidget(self.open_camera)
        video = QPushButton('打开视频文件')
        video.clicked.connect(self.choose_video)
        row.addWidget(video)
        self.pause = QCheckBox('暂停画面')
        self.pause.toggled.connect(self._pause)
        row.addWidget(self.pause)
        stop = QPushButton('关闭视频')
        stop.clicked.connect(self.shutdown)
        row.addWidget(stop)
        layout.addLayout(row)
        recording_row = QHBoxLayout()
        self.record_btn = QPushButton('开始录制')
        self.record_btn.setEnabled(False)
        self.record_btn.clicked.connect(self._toggle_recording)
        recording_row.addWidget(self.record_btn)
        self.record_name_input = QLineEdit()
        self.record_name_input.setPlaceholderText('文件名（可选）')
        recording_row.addWidget(self.record_name_input, 1)
        self.record_label = QLabel('未录制')
        self.record_label.setWordWrap(True)
        recording_row.addWidget(self.record_label)
        layout.addLayout(recording_row)
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel('功能'))
        self.mode = QComboBox()
        self.mode.addItems(['实时跟踪', '棋盘标定'])
        self.mode.currentIndexChanged.connect(self._change_mode)
        mode_row.addWidget(self.mode)
        mode_row.addStretch()
        layout.addLayout(mode_row)
        self.calibration_group = QGroupBox('棋盘标定（默认 8×11 内角点，每格 10 mm）')
        cal_layout = QVBoxLayout(self.calibration_group)
        actions = QHBoxLayout()
        self.capture_view_btn = QPushButton('采集内参照片')
        self.capture_view_btn.clicked.connect(self.capture_intrinsic_view)
        actions.addWidget(self.capture_view_btn)
        self.fit_intrinsic_btn = QPushButton('计算内参')
        self.fit_intrinsic_btn.clicked.connect(self.compute_intrinsics)
        actions.addWidget(self.fit_intrinsic_btn)
        clear_views = QPushButton('清空内参采集')
        clear_views.clicked.connect(self.clear_calibration_views)
        actions.addWidget(clear_views)
        cal_layout.addLayout(actions)
        actions = QHBoxLayout()
        self.plane_btn = QPushButton('识别平面棋盘')
        self.plane_btn.clicked.connect(self.capture_plane)
        actions.addWidget(self.plane_btn)
        self.confirm_plane_btn = QPushButton('确认平面并保存')
        self.confirm_plane_btn.clicked.connect(self.confirm_plane)
        self.confirm_plane_btn.setEnabled(False)
        actions.addWidget(self.confirm_plane_btn)
        self.measure_check = QCheckBox('点击两点验证距离')
        self.measure_check.toggled.connect(lambda: self.measurement_points.clear())
        actions.addWidget(self.measure_check)
        cal_layout.addLayout(actions)
        self.calibration_help = QLabel('内参：多角度采集至少 12 张，再计算；平面：固定相机，将棋盘放在鱼标记的观测高度，识别后确认 O、X、Y。')
        self.calibration_help.setWordWrap(True)
        cal_layout.addWidget(self.calibration_help)
        layout.addWidget(self.calibration_group)
        self.calibration_group.setVisible(False)
        cal_row = QHBoxLayout()
        load = QPushButton('加载标定文件')
        load.clicked.connect(self.choose_calibration)
        cal_row.addWidget(load)
        cal_row.addStretch()
        layout.addLayout(cal_row)
        self.approve_calibration = QCheckBox('确认相机、分辨率和观测平面一致，启用米制坐标')
        self.approve_calibration.toggled.connect(self._calibration_approval_changed)
        layout.addWidget(self.approve_calibration)
        self.calibration_label = QLabel('未加载标定：显示图像像素坐标')
        self.calibration_label.setWordWrap(True)
        layout.addWidget(self.calibration_label)
        settings = QHBoxLayout()
        settings.addWidget(QLabel('黑点阈值'))
        self.threshold = QSpinBox()
        self.threshold.setRange(0, 255)
        self.threshold.setValue(75)
        settings.addWidget(self.threshold)
        settings.addWidget(QLabel('最小面积'))
        self.min_area = QSpinBox()
        self.min_area.setRange(5, 5000)
        self.min_area.setValue(20)
        settings.addWidget(self.min_area)
        reset = QPushButton('重新选择黑点')
        reset.clicked.connect(self.reset_selection)
        settings.addWidget(reset)
        clear = QPushButton('清除轨迹')
        clear.clicked.connect(self.clear_trail)
        settings.addWidget(clear)
        settings.addStretch()
        layout.addLayout(settings)
        self.hint = QLabel('选择电机中段的点3和点4：先点靠鱼头的点，再点靠鱼尾的点。位置取两点中点，箭头指向鱼头。')
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.image = ClickableImage()
        self.image.clicked.connect(self._image_clicked)
        layout.addWidget(self.image, 1)
        self.status = QLabel('未打开视频；仅显示，不发送控制指令')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(100)
        self.calibration_finished.connect(self._finish_calibration_job)
        saved = self._settings.value('calibration_path', '')
        if saved:
            try:
                self.load_calibration(saved, remember=False)
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                self.calibration_label.setText('上次标定文件不可用，请重新加载')

    def _change_mode(self):
        self._generation += 1
        self.pending_plane = None
        self.confirm_plane_btn.setEnabled(False)
        self.calibration_group.setVisible(self.mode.currentIndex() == 1)
        self.measurement_points.clear()
        self.reset_selection()

    def _calibration_approval_changed(self):
        self.clear_trail()
        self._gap = True

    def clear_calibration_views(self):
        self._generation += 1
        self.calibration_views.clear()
        self.view_size = None
        self.calibration_label.setText('已清空内参采集；已保存的标定文件不受影响')

    def _image_clicked(self, x, y):
        if self.mode.currentIndex() == 0:
            self.select_marker(x, y)
            return
        if not self.measure_check.isChecked() or not self.pause.isChecked():
            return
        if self.frame is None or self.raw_frame is None or not self.active:
            return
        try:
            height, width = self.raw_frame.shape[:2]
            self._check_calibration_source(width, height)
            self.measurement_points.append((x * width / self.frame.shape[1], y * height / self.frame.shape[0]))
            if len(self.measurement_points) == 1:
                self.calibration_label.setText('已选择第一点，请选择第二点。')
            else:
                world = calibration.map_points(self.measurement_points, self.calibration)
                distance = float(math.dist(world[0], world[1]))
                self.measurement_points.clear()
                self.calibration_label.setText(f'两点平面距离 {distance:.4f} m；请与同高度的独立实测长度比较。')
        except (ValueError, TypeError, KeyError, cv2.error) as exc:
            self.measurement_points.clear()
            self.calibration_label.setText(f'无法测距：{exc}')

    def choose_calibration(self):
        path, _ = QFileDialog.getOpenFileName(self, '加载相机平面标定', '', 'JSON 标定文件 (*.json)')
        if path:
            try:
                self.load_calibration(path)
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                self.calibration_label.setText(f'加载失败（保留原标定）：{exc}')

    def load_calibration(self, path, remember=True):
        with open(path, encoding='utf-8') as stream:
            data = json.load(stream)
        _, _, size, H = calibration.validate(data)
        self._generation += 1
        self.calibration, self.calibration_path = data, str(path)
        self.pending_plane = None
        self.confirm_plane_btn.setEnabled(False)
        self.approve_calibration.setChecked(False)
        self.clear_trail()
        self.calibration_label.setText(
            f'已加载：{Path(path).name}，{size[0]}×{size[1]}，'
            f'{"内参及平面" if H is not None else "仅内参，需标定平面"}；请确认相机及观测平面。')
        if remember:
            self._settings.setValue('calibration_path', str(path))

    def _persist_calibration(self, data):
        calibration.validate(data)
        folder = Path(QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation)) / 'FishRobot' / 'top_camera_calibration'
        filename = 'calibration_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.json'
        path = folder / filename
        calibration.save(path, data)
        self.load_calibration(path)
        return path

    def _start_calibration_job(self, kind, work):
        if self.calibration_busy:
            self.calibration_label.setText('正在处理上一项标定，请稍候')
            return
        self.calibration_busy = True
        token = self._generation
        self.calibration_label.setText('正在计算，请稍候…')
        def runner():
            try:
                result = (kind, token, work(), None)
            except Exception as exc:
                result = (kind, token, None, str(exc))
            try:
                self.calibration_finished.emit(result)
            except RuntimeError:
                pass  # The window may have been closed while OpenCV was working.
        threading.Thread(target=runner, daemon=True).start()

    def _snapshot(self):
        if self.mode.currentIndex() != 1 or not self.active or self.raw_frame is None:
            raise ValueError('请先打开视频源并切换到棋盘标定')
        if not self.pause.isChecked() and time.monotonic() - self._last_frame_time > 1:
            raise ValueError('画面不是最新帧')
        self.pause.setChecked(True)
        return self.raw_frame.copy()

    def capture_intrinsic_view(self):
        try:
            frame = self._snapshot()
            size = (frame.shape[1], frame.shape[0])
            if self.view_size is not None and size != self.view_size:
                raise ValueError('采集分辨率发生变化，请重新开始采集')
            self._start_calibration_job('view', lambda: (calibration.detect_board(frame), size, frame))
        except ValueError as exc:
            self.calibration_label.setText(str(exc))

    def compute_intrinsics(self):
        if self.mode.currentIndex() != 1 or not self.active:
            self.calibration_label.setText('请先打开视频源并切换到棋盘标定')
            return
        if len(self.calibration_views) < calibration.MIN_VIEWS:
            self.calibration_label.setText(f'当前 {len(self.calibration_views)} 张，至少需要 {calibration.MIN_VIEWS} 张有效照片')
            return
        views = [v.copy() for v in self.calibration_views]
        size = self.view_size
        camera_id = self.reader.source if isinstance(self.reader.source, int) else None
        self._start_calibration_job('intrinsics', lambda: calibration.new_calibration(
            calibration.fit_intrinsics(views, size), camera_id))

    def capture_plane(self):
        try:
            if self.calibration is None:
                raise ValueError('请先加载或计算相机内参')
            frame = self._snapshot()
            size = (frame.shape[1], frame.shape[0])
            K, dist, expected, _ = calibration.validate(self.calibration)
            if size != expected:
                raise ValueError(f'画面 {size} 与内参 {expected} 不一致')
            camera_id = self.calibration.get('camera_id')
            if isinstance(self.reader.source, int) and camera_id is not None and camera_id != self.reader.source:
                raise ValueError(f'当前相机编号与内参记录 {camera_id} 不一致')
            data = copy.deepcopy(self.calibration)
            def work():
                corners = calibration.detect_board(frame)
                data['extrinsics'] = calibration.fit_plane(corners, data, size)
                return data, corners, frame
            self._start_calibration_job('plane', work)
        except (ValueError, KeyError) as exc:
            self.calibration_label.setText(str(exc))

    def _show_board(self, frame, corners):
        display = frame.copy()
        cv2.drawChessboardCorners(display, calibration.PATTERN, corners, True)
        for name, index in [('O', 0), ('+X', calibration.PATTERN[0]-1),
                            ('+Y', (calibration.PATTERN[1]-1)*calibration.PATTERN[0])]:
            point = tuple(int(round(v)) for v in corners[index, 0])
            cv2.circle(display, point, 10, (0, 0, 255), -1)
            cv2.putText(display, name, (point[0]+12, point[1]-12),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 3)
        if display.shape[1] > 960:
            factor = 960 / display.shape[1]
            display = cv2.resize(display, (960, round(display.shape[0]*factor)))
        self.image.set_frame(display)

    def _finish_calibration_job(self, result):
        kind, token, value, error = result
        self.calibration_busy = False
        if token != self._generation:
            return
        if error:
            self.calibration_label.setText(f'标定失败：{error}')
            return
        try:
            if kind == 'view':
                corners, size, frame = value
                for previous in self.calibration_views:
                    if float(((corners - previous)**2).sum(axis=2).mean()**.5) < 2:
                        raise ValueError('棋盘与已有照片过于相似，请改变位置和倾角')
                self.view_size = size
                self.calibration_views.append(corners)
                self._show_board(frame, corners)
                self.calibration_label.setText(f'已采集 {len(self.calibration_views)} 张有效棋盘图。取消暂停、改变位置和倾角，再采集。')
            elif kind == 'intrinsics':
                path = self._persist_calibration(value)
                rms = value['intrinsics']['rms_px']
                warning = '误差偏高，请检查照片并重新采集。' if rms > 1.5 else ''
                self.calibration_label.setText(f'内参已保存：{path}；RMS {rms:.3f} 像素。{warning}接下来标定平面。')
            else:
                data, corners, frame = value
                self.pending_plane = data
                self.confirm_plane_btn.setEnabled(True)
                self._show_board(frame, corners)
                self.calibration_label.setText('已识别棋盘：检查画面 O、+X、+Y 的方向，再点“确认平面并保存”。')
        except (ValueError, OSError, KeyError) as exc:
            self.calibration_label.setText(f'标定保存失败：{exc}')

    def confirm_plane(self):
        if self.pending_plane is None:
            return
        try:
            path = self._persist_calibration(self.pending_plane)
            self.pending_plane = None
            self.confirm_plane_btn.setEnabled(False)
            self.calibration_label.setText(f'平面标定已保存：{path}。请用独立已知长度验证，再启用米制坐标。')
        except (ValueError, OSError, KeyError) as exc:
            self.calibration_label.setText(f'保存失败：{exc}')

    def choose_video(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择顶部摄像头录像', '',
                                              '视频文件 (*.mkv *.mp4 *.avi *.mov);;所有文件 (*)')
        if path:
            self.open_source(path)

    def open_source(self, source):
        if self.recording:
            self._stop_recording()
        self._generation += 1
        self.pending_plane = None
        self.confirm_plane_btn.setEnabled(False)
        self.approve_calibration.setChecked(False)
        self.calibration_views.clear()
        self.view_size = None
        if self.reader and self.reader.thread.is_alive():
            self.reader.stop()
            self.active = False
            self._gap = True
            self.status.setText('正在释放上一个视频源，请稍后再次打开')
            return
        self.clear_trail()
        self.reset_selection()
        self.frame = None
        self.raw_frame = None
        self.sequence = -1
        self._last_frame_time = 0
        self.pause.setChecked(False)
        self.reader = FrameReader(source)
        self.active = True
        self.reader.start()
        self.status.setText('正在打开视频源…')

    def _pause(self, paused):
        if self.reader:
            if paused:
                self.reader.pause_event.set()
                self.velocity.reset()
                self.status.setText('画面已暂停；速度和角速度等待恢复后的新数据')
            else:
                self.reader.pause_event.clear()
                self._gap = True
                self.velocity.reset()
                self.measurement_points.clear()
                if self.mode.currentIndex() == 1 and (self.pending_plane is not None or self.calibration_busy):
                    self._generation += 1
                    self.pending_plane = None
                    self.confirm_plane_btn.setEnabled(False)
                    self.calibration_label.setText('画面已恢复，未确认的标定结果已取消')

    def clear_trail(self):
        self.trail.clear()
        self.velocity.reset()
        self._gap = True

    def reset_selection(self):
        self.head = self.tail = None
        self.selecting = 'head'
        self._gap = True
        self.velocity.reset()
        self.status.setText('请先点击中段点3或点4中靠鱼头的点，再点击靠鱼尾的点')

    def select_marker(self, x, y):
        if self.mode.currentIndex() != 0 or not self.active or self.frame is None or self.selecting is None:
            return
        marker = nearest_marker(self.markers, (x, y), 30)
        if marker is None:
            self.status.setText('附近未找到唯一黑点，请调整阈值或点击黑点中心')
            return
        if self.selecting == 'head':
            self.head = marker
            self.selecting = 'tail'
            self.status.setText('已选中段前点，请点击中段靠鱼尾的点')
        else:
            if marker == self.head or math.dist(marker[:2], self.head[:2]) < 10:
                self.status.setText('请选择与前点分开的中段后点，两个点至少相距10个处理像素')
                return
            self.tail = marker
            self.selecting = None
            self._gap = True
            self.status.setText('已选择两点，开始跟踪')

    def refresh(self):
        self._poll_recording()
        if not self.reader or not self.active:
            return
        seq, raw, timestamp = self.reader.latest()
        if seq == self.sequence or raw is None:
            if not self.reader.thread.is_alive():
                if self.recording:
                    self._stop_recording()
                self.status.setText(self.reader.status)
                self._gap = True
                self.velocity.reset()
            elif not self.pause.isChecked() and self._last_frame_time and time.monotonic() - self._last_frame_time > 1:
                self.status.setText('画面已超过 1 秒未更新，跟踪中断')
                self.head = self.tail = None
                self.selecting = 'head'
                self._gap = True
                self.velocity.reset()
            return
        self.sequence = seq
        self._last_frame_time = time.monotonic()
        height, width = raw.shape[:2]
        self.raw_frame = raw
        self.record_btn.setEnabled(self.record_worker is None or self.recording)
        scale = min(1.0, 960.0 / width)
        self.frame = cv2.resize(raw, (round(width * scale), round(height * scale))) if scale < 1 else raw.copy()
        if self.mode.currentIndex() == 1:
            self.image.set_frame(self.frame)
            self._record_display_frame(self.frame)
            return
        self.markers = candidates(self.frame, self.threshold.value(), self.min_area.value())
        if self.selecting is None:
            found = follow_pair(self.markers, self.head, self.tail)
            if found is None:
                self.head = self.tail = None
                self.selecting = 'head'
                self._gap = True
                self.velocity.reset()
                self.status.setText('跟踪丢失：请重新选择中段靠鱼头和靠鱼尾的点')
            else:
                self.head, self.tail = found
                x, y, angle = pose(self.head, self.tail)
                self.trail.append((x, y, self._gap))
                self._gap = False
                angle_display = round(angle, 1) % 360
                pixel_text = f'中段中点 X={x * width / self.frame.shape[1]:.1f}, Y={y * height / self.frame.shape[0]:.1f} 像素｜图像航向 {angle_display:.1f}°'
                metric_text = self._world_pose(width, height, timestamp)
                self.status.setText(f'跟踪中｜{pixel_text}｜{metric_text}')
        display = self.frame.copy()
        previous = None
        for x, y, gap in self.trail:
            point = (round(x), round(y))
            if previous is not None and not gap:
                cv2.line(display, previous, point, (0, 200, 255), 2)
            previous = point
        if self.head is not None:
            cv2.circle(display, (round(self.head[0]), round(self.head[1])), 8, (0, 255, 0), 2)
        if self.head is not None and self.tail is not None:
            cv2.arrowedLine(display, tuple(round(v) for v in self.tail[:2]),
                            tuple(round(v) for v in self.head[:2]), (0, 255, 0), 2, tipLength=.25)
        self.image.set_frame(display)
        self._record_display_frame(display)

    def _toggle_recording(self):
        """Record the displayed tracking view without touching the fish control path."""
        if self.recording:
            self._stop_recording()
            return
        if not self.active or self.raw_frame is None or self.record_worker is not None:
            return
        try:
            label = validate_label(self.record_name_input.text())
            self.record_path = default_export_path('top_camera_videos', label, '.mp4')
            self.record_worker = TimestampedH264Writer(self.record_path)
        except (ValueError, OSError, ImportError) as exc:
            QMessageBox.warning(self, '录像不可用', str(exc))
            return
        self.recording = True
        self.record_btn.setText('停止录制')
        self.record_name_input.setEnabled(False)
        self.record_label.setText('录制中：0 帧')
        self.record_label.setToolTip('保存页面显示画面及跟踪标记，刷新频率最高约 10 次/秒。')

    def _record_display_frame(self, image):
        if self.recording and self.record_worker:
            if not self.record_worker.submit(image, time.monotonic()):
                self._stop_recording()
            else:
                count, _, _ = self.record_worker.snapshot()
                self.record_label.setText(f'录制中：{count} 帧')

    def _stop_recording(self):
        if not self.recording:
            return
        self.recording = False
        self.record_worker.stop()
        self.record_btn.setText('开始录制')
        self.record_btn.setEnabled(False)
        self.record_label.setText('正在保存…')

    def _poll_recording(self):
        worker = self.record_worker
        if not worker:
            return
        _, count, error = worker.snapshot()
        if self.recording and error:
            self._stop_recording()
        if not self.recording and worker.finished.is_set():
            self.record_worker = None
            self.record_name_input.setEnabled(True)
            self.record_btn.setEnabled(self.active and self.raw_frame is not None)
            self.record_label.setText('录像失败' if error else (f'已保存：{count} 帧' if count else '没有录制帧'))
            self.record_label.setToolTip(f'{self.record_path}\n{error or ""}')

    def _check_calibration_source(self, width, height):
        if not self.approve_calibration.isChecked():
            raise ValueError('请确认相机、分辨率及观测平面一致并启用米制坐标')
        if self.calibration is None:
            raise ValueError('未加载标定')
        _, _, expected, _ = calibration.validate(self.calibration, require_plane=True)
        if (width, height) != expected:
            raise ValueError(f'画面 {width}×{height} 与标定 {expected[0]}×{expected[1]} 不符')
        camera_id = self.calibration.get('camera_id')
        if isinstance(self.reader.source, int) and camera_id is not None and camera_id != self.reader.source:
            raise ValueError(f'相机编号与标定记录 {camera_id} 不一致')

    def _world_pose(self, width, height, timestamp=None):
        if not self.approve_calibration.isChecked():
            self.velocity.reset()
            return '米制坐标未启用'
        try:
            self._check_calibration_source(width, height)
            sx, sy = width / self.frame.shape[1], height / self.frame.shape[0]
            world = calibration.map_points([(self.head[0]*sx, self.head[1]*sy),
                                            (self.tail[0]*sx, self.tail[1]*sy)], self.calibration)
            center = (world[0] + world[1]) / 2
            delta = world[0] - world[1]
            if math.hypot(*delta) < 1e-9:
                raise ValueError('两点映射过近')
            direction = round(math.degrees(math.atan2(delta[1], delta[0])) % 360, 1) % 360
            heading = math.degrees(math.atan2(delta[1], delta[0])) % 360
            velocity = self.velocity.update(timestamp, float(center[0]), float(center[1]), heading)
            speeds = '速度和角速度等待连续数据' if velocity is None else (
                f'速度 {velocity[2]:.3f} m/s（Vx={velocity[0]:.3f}, Vy={velocity[1]:.3f} m/s）'
                f'｜角速度 {velocity[3]:+.1f} °/s')
            return f'平面 X={center[0]:.3f}, Y={center[1]:.3f} m｜中段航向 {direction:.1f}°｜{speeds}'
        except (ValueError, TypeError, KeyError, cv2.error) as exc:
            self.velocity.reset()
            return f'米制坐标不可用：{exc}'

    def shutdown(self):
        self._stop_recording()
        self.record_btn.setEnabled(False)
        self._generation += 1
        self.active = False
        if self.reader:
            self.reader.stop()
        self._gap = True
        self.velocity.reset()
        self.head = self.tail = None
        self.selecting = 'head'
        self.status.setText('视频已关闭；仅显示，不发送控制指令')
