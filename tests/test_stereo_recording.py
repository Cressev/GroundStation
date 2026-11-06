"""Offline recording controls and statistics, without fish/network access."""

from unittest.mock import Mock

import numpy as np
import pytest


@pytest.fixture
def recording_widget(tmp_path, monkeypatch):
    """Create a camera-ready widget with isolated settings and a fake encoder."""
    from test_ui_state_machine import ensure_app
    from PyQt5.QtCore import QSettings
    from ui import stereo_camera_widget as module
    from ui import save_paths
    ensure_app()
    monkeypatch.setattr(save_paths, 'ROOT', tmp_path/'saved_data')
    monkeypatch.setattr(module.tempfile, 'tempdir', str(tmp_path))
    widget = module.StereoFishCameraWidget(QSettings(str(tmp_path/'settings.ini'), QSettings.IniFormat))
    widget._stream_state, widget._camera_state = 'connected', 'on'
    widget.current_frame = np.zeros((80, 60, 3), np.uint8)
    widget._apply_ui_state()
    writer = Mock()
    writer.isOpened.return_value = True
    monkeypatch.setattr(module.cv2, 'VideoWriter', Mock(return_value=writer))
    class ImmediateRecorder:
        """Isolate widget lifecycle tests from the separately tested encoder thread."""
        def __init__(self, encoder, fps, start, initial_frame, clock):
            self.encoder, self.error, self.output_count = encoder, None, 0
            self.submit(initial_frame)

        def submit(self, frame):
            self.encoder.write(frame)
            self.output_count += 1
            return True

        def stop(self, end_time):
            self.encoder.release()
            return True
    monkeypatch.setattr(module, 'RealtimeVideoWriter', ImmediateRecorder)
    monkeypatch.setattr(module.QFileDialog, 'getSaveFileName', lambda *args: (str(tmp_path/'saved.mp4'), ''))
    monkeypatch.setattr(module.QMessageBox, 'information', lambda *args: None)
    clock = [100.]
    monkeypatch.setattr(module.time, 'monotonic', lambda: clock[0])
    yield widget, writer, clock
    if widget.recording:
        widget._stop_recording()
    widget.close()


def test_record_button_and_live_elapsed_frames(recording_widget):
    """Record real elapsed seconds, not frame/15, and count only encoder writes."""
    widget, writer, clock = recording_widget
    assert widget.record_btn.text() == '开始录制'
    assert widget.record_btn.property('recording') is False
    assert '#15803d' in widget.record_btn.styleSheet()
    assert 'QPushButton:disabled' in widget.record_btn.styleSheet()
    assert widget.record_stats_label.text() == '未录制 00:00:00 · 0帧'
    widget._toggle_recording()
    assert widget.record_btn.text() == '停止录制'
    assert widget.record_btn.property('recording') is True
    assert widget._record_stats_timer.isActive()
    widget._record_frame(widget.current_frame)
    widget._record_frame(widget.current_frame)
    clock[0] += 3661.2
    widget._update_recording_stats()
    assert widget.record_stats_label.text() == '录制中 01:01:01 · 2帧'
    assert writer.write.call_count == 2
    widget._stop_recording()
    assert widget.record_stats_label.text() == '已停止 01:01:01 · 2帧'
    assert not widget._record_stats_timer.isActive()
    clock[0] += 100
    widget._update_recording_stats()
    assert widget.record_stats_label.text() == '已停止 01:01:01 · 2帧'
    widget._stop_recording()
    assert writer.release.call_count == 1
    widget._toggle_recording()
    assert widget.record_stats_label.text() == '录制中 00:00:00 · 0帧'


@pytest.mark.parametrize('event', ['camera_off', 'disconnect'])
def test_recording_auto_stop_retains_stats(recording_widget, tmp_path, monkeypatch, event):
    """Camera closure and loss of connection freeze one recording identically."""
    widget, writer, clock = recording_widget
    monkeypatch.chdir(tmp_path)
    widget._toggle_recording()
    widget._record_frame(widget.current_frame)
    clock[0] += 3.7
    if event == 'camera_off':
        widget._camera_state = 'off'
        widget._clear_local_frames()
    else:
        widget._on_connection_status(False, '连接已断开')
    assert not widget.recording and not widget._record_stats_timer.isActive()
    assert widget.record_stats_label.text() == '已停止 00:00:03 · 1帧'
    assert widget.record_btn.text() == '开始录制'
    assert not widget.record_btn.isEnabled()
    assert writer.release.call_count == 1


def test_encoder_open_failure_stops_stats(recording_widget):
    """Do not show an increasing timer or frame count after encoder failure."""
    widget, writer, clock = recording_widget
    writer.isOpened.return_value = False
    widget._toggle_recording()
    clock[0] += 2
    widget._record_frame(widget.current_frame)
    assert not widget.recording and not widget._record_stats_timer.isActive()
    assert widget.record_stats_label.text() == '录制失败 00:00:02 · 0帧'
    assert widget.record_btn.text() == '开始录制'
    writer.write.assert_not_called()
    writer.release.assert_called_once()


def test_recording_status_stays_in_compact_action_row(recording_widget):
    """Two rows keep status and recording controls visible without horizontal scrolling."""
    from PyQt5.QtCore import QPoint
    from PyQt5.QtWidgets import QApplication
    widget, writer, clock = recording_widget
    widget.resize(1100, 800)
    widget.show()
    app = QApplication.instance()
    app.processEvents()
    app.processEvents()
    label = widget.record_stats_label
    assert label.mapTo(widget, QPoint()).y() < widget.record_btn.mapTo(widget, QPoint()).y()
    widget.resize(480, 800)
    app.processEvents()
    app.processEvents()
    assert widget.page_scroll.horizontalScrollBar().maximum() == 0
    assert not hasattr(widget, 'action_scroll')
    assert widget.snapshot_btn.mapTo(widget.action_bar, QPoint()).x() + widget.snapshot_btn.width() <= widget.action_bar.width()


def test_recording_write_failure_does_not_count_rejected_frame(recording_widget, tmp_path, monkeypatch):
    """A thrown write error preserves earlier statistics and stops the session."""
    widget, writer, clock = recording_widget
    monkeypatch.chdir(tmp_path)
    widget._toggle_recording()
    widget._record_frame(widget.current_frame)
    writer.write.side_effect = RuntimeError('write failed')
    clock[0] += 4
    widget._record_frame(widget.current_frame)
    assert not widget.recording and not widget._record_stats_timer.isActive()
    assert widget.record_stats_label.text() == '录制失败 00:00:04 · 1帧'
    assert 'write failed' in widget.record_stats_label.toolTip()
    assert len(list((tmp_path/'saved_data'/'stereo_videos').glob('*.mp4'))) == 1


def test_recording_without_new_frames_creates_no_empty_video(recording_widget, tmp_path):
    """Starting and stopping before a fresh frame must not export a zero-byte MP4."""
    from pathlib import Path
    widget, writer, clock = recording_widget
    widget._toggle_recording()
    temporary = Path(widget.recording_path)
    clock[0] += 2.5
    widget._stop_recording()
    assert widget.record_stats_label.text() == '已停止 00:00:02 · 0帧'
    assert not temporary.exists()
    assert not (tmp_path/'saved.mp4').exists()
    writer.write.assert_not_called()


def test_background_encoder_failure_without_new_frame_is_reported(recording_widget, monkeypatch):
    """A timer reports failure even if no later source frame arrives."""
    from pathlib import Path
    from ui import stereo_camera_widget as module
    widget, writer, clock = recording_widget

    class FailedRecorder:
        def __init__(self, encoder, fps, start, initial_frame, clock):
            self.encoder, self.error, self.output_count = encoder, 'disk failure', 0

        def stop(self, end_time):
            self.encoder.release()
            return True

    monkeypatch.setattr(module, 'RealtimeVideoWriter', FailedRecorder)
    widget._toggle_recording()
    temp = Path(widget.recording_path)
    widget._record_frame(widget.current_frame)
    widget._update_recording_stats()
    assert not widget.recording
    assert widget._rec_status == '录制失败'
    assert 'disk failure' in widget.record_stats_label.toolTip()
    assert str(temp) in widget.record_stats_label.toolTip()
    assert temp.exists()


def test_timed_out_encoder_preserves_file_in_place(recording_widget, monkeypatch):
    """A still-writing encoder's temporary file is not moved or deleted."""
    from pathlib import Path
    from ui import stereo_camera_widget as module
    widget, writer, clock = recording_widget

    class SlowRecorder:
        def __init__(self, encoder, fps, start, initial_frame, clock):
            self.error, self.output_count = None, 1

        def stop(self, end_time):
            return False

    monkeypatch.setattr(module, 'RealtimeVideoWriter', SlowRecorder)
    widget._toggle_recording()
    temp = Path(widget.recording_path)
    widget._record_frame(widget.current_frame)
    widget._stop_recording()
    assert not widget.recording
    assert widget._rec_status == '录制失败'
    assert temp.exists()
    assert str(temp) in widget.record_stats_label.toolTip()

def test_recording_stitches_right_eye_and_pads_black_when_missing(recording_widget):
    """Relay frames record left|right side by side; a missing right eye pads black."""
    from ui import stereo_camera_widget as module
    widget, writer, clock = recording_widget
    left = np.full((80, 60, 3), 40, np.uint8)
    right = np.full((80, 60, 3), 200, np.uint8)
    widget._toggle_recording()
    widget._record_frame(left, right)
    assert module.cv2.VideoWriter.call_args.args[3] == (120, 80)
    frames = [call.args[0] for call in writer.write.call_args_list]
    assert frames[0].shape == (80, 120, 3)
    assert int(frames[0][:, :60].mean()) == 40 and int(frames[0][:, 60:].mean()) == 200
    # 右目中途缺失：补黑保持编码器尺寸，布局不回落单目
    widget._record_frame(left, None)
    frames = [call.args[0] for call in writer.write.call_args_list]
    assert frames[1].shape == (80, 120, 3)
    assert int(frames[1][:, 60:].mean()) == 0
    widget._stop_recording()
    assert writer.write.call_count == 2


def test_recording_single_eye_layout_locks_when_right_missing_first(recording_widget):
    """First frame without a right eye locks the session to single-eye width."""
    widget, writer, clock = recording_widget
    left = np.full((80, 60, 3), 40, np.uint8)
    right = np.full((80, 60, 3), 200, np.uint8)
    widget._toggle_recording()
    widget._record_frame(left, None)
    widget._record_frame(left, right)
    frames = [call.args[0] for call in writer.write.call_args_list]
    assert [f.shape for f in frames] == [(80, 60, 3), (80, 60, 3)]
    widget._stop_recording()


def test_invalid_filename_never_starts_recording(recording_widget, monkeypatch):
    """A path-like label cannot create a recording or send any command."""
    from ui import stereo_camera_widget as module
    widget, writer, _ = recording_widget
    warnings = Mock()
    monkeypatch.setattr(module.QMessageBox, 'warning', warnings)
    widget.record_name_input.setText('../unsafe')
    widget._toggle_recording()
    assert not widget.recording and widget.recording_path is None
    assert warnings.called
    writer.write.assert_not_called()


def test_new_relay_defaults_to_raw_but_respects_user_mode(recording_widget):
    """A capable relay enables the requested default without overriding a user choice."""
    import json
    widget, _, _ = recording_widget
    widget._update_source_descriptor = Mock()
    widget._update_resolution_state = Mock()
    state = dict(type='node_state', protocol='stereo-relay-v1', camera_on=True,
                 fps_switch=True, stream_fps=15)
    widget._on_message(json.dumps(state))
    assert widget.record_mode.currentData() == 'raw'
    widget.record_mode.setCurrentIndex(widget.record_mode.findData('display'))
    widget.record_mode.activated.emit(widget.record_mode.currentIndex())
    widget.video_height_input.setValue(840)
    widget._on_message(json.dumps(dict(state, command='SET_STREAM_FPS', stream_fps=30)))
    assert widget.record_mode.currentData() == 'display'
    assert widget.video_height_input.value() == 840


def test_raw_recording_saves_timestamps_and_restores_rate(recording_widget, tmp_path, monkeypatch):
    """Raw mode saves exactly received packets without blocking the GUI on close."""
    import cv2
    av = pytest.importorskip('av')
    from PyQt5.QtTest import QTest
    widget, _, _ = recording_widget
    widget._relay_mode = widget._fps_control_supported = True
    widget._stream_fps = 15
    widget.record_mode.setCurrentIndex(widget.record_mode.findData('raw'))
    widget.record_name_input.setText('水下测试')
    widget.stream_client.send_command = Mock(return_value=True)
    widget.worker.submit = Mock()
    widget._toggle_recording()
    assert widget.recording
    for index, delta in enumerate((0, 33_000_000, 100_000_000)):
        ok, jpeg = cv2.imencode('.jpg', np.full((80, 120, 3), index*50, np.uint8))
        assert ok
        widget._submit_stereo(dict(connection_id=widget.stream_client.connection_id,
                                   camera_epoch=1, source_width=120, source_height=80,
                                   capture_monotonic_ns=1_000_000_000+delta), jpeg.tobytes())
    widget._stop_recording()
    for _ in range(200):
        if not widget._record_finalizing and widget.stream_client.send_command.call_count >= 2:
            break
        QTest.qWait(10)
    assert not widget._record_finalizing
    assert widget.stream_client.send_command.call_args_list[0].args[0] == 'SET_STREAM_FPS 30'
    assert widget.stream_client.send_command.call_args_list[-1].args[0] == 'SET_STREAM_FPS 15'
    with av.open(str(tmp_path/'saved.mp4')) as container:
        frames = list(container.decode(video=0))
    assert len(frames) == 3
    assert [float(frame.time) for frame in frames] == pytest.approx([0, .033, .1], abs=.002)


def test_raw_stop_does_not_block_gui_timer(recording_widget, monkeypatch):
    """An unfinished encoder must not block the event loop used by controls."""
    import threading
    import time
    from PyQt5.QtCore import QTimer
    from PyQt5.QtTest import QTest
    from ui import stereo_camera_widget as module
    widget, _, _ = recording_widget
    widget._relay_mode = widget._fps_control_supported = True
    widget.record_mode.setCurrentIndex(widget.record_mode.findData('raw'))
    widget.stream_client.send_command = Mock(return_value=True)

    class SlowRaw:
        """Keep finalization pending until the test explicitly releases it."""
        def __init__(self, _path):
            self.finished = threading.Event()
        def stop(self, timeout=10):
            return self.finished.wait(timeout)
        def snapshot(self):
            return 0, 0, None

    monkeypatch.setattr(module, 'TimestampedJpegWriter', SlowRaw)
    widget._toggle_recording()
    worker = widget._raw_record_worker
    ticks = []
    timer = QTimer()
    timer.setInterval(5)
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start()
    started = time.perf_counter()
    widget._stop_recording(prompt_for_path=False)
    assert time.perf_counter()-started < .2
    assert widget._record_finalizing and not widget.record_btn.isEnabled()
    QTest.qWait(40)
    assert ticks
    worker.finished.set()
    QTest.qWait(100)
    assert not widget._record_finalizing
    timer.stop()


def test_raw_cross_volume_save_does_not_block_gui(recording_widget, monkeypatch):
    """Even a slow final file move cannot stall the control event loop."""
    import threading
    from PyQt5.QtCore import QTimer
    from PyQt5.QtTest import QTest
    from ui import stereo_camera_widget as module
    widget, _, _ = recording_widget
    widget._relay_mode = widget._fps_control_supported = True
    widget.record_mode.setCurrentIndex(widget.record_mode.findData('raw'))
    widget.stream_client.send_command = Mock(return_value=True)

    class CompleteRaw:
        """Provide a finished recorder with one captured frame."""
        def __init__(self, _path):
            self.finished = threading.Event()
            self.finished.set()
        def stop(self, timeout=10):
            return True
        def snapshot(self):
            return 1, 1, None

    release = threading.Event()
    original_move = module.shutil.move
    def slow_move(source, destination):
        """Emulate slow cross-volume storage without blocking the test thread."""
        assert release.wait(3)
        return original_move(source, destination)
    monkeypatch.setattr(module, 'TimestampedJpegWriter', CompleteRaw)
    monkeypatch.setattr(module, 'convert_to_h264', lambda source, destination: None)
    monkeypatch.setattr(module.shutil, 'move', slow_move)
    widget._toggle_recording()
    ticks = []
    timer = QTimer()
    timer.setInterval(5)
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start()
    widget._stop_recording(prompt_for_path=False)
    assert widget._record_finalizing
    QTest.qWait(40)
    assert ticks and widget._record_finalizing
    release.set()
    for _ in range(100):
        if not widget._record_finalizing:
            break
        QTest.qWait(10)
    assert not widget._record_finalizing and widget._rec_status == '已停止'
    timer.stop()


def test_conversion_failure_keeps_original_video(recording_widget, tmp_path, monkeypatch):
    """A failed compatibility conversion never destroys the original recording."""
    from ui import stereo_camera_widget as module
    widget, _, _ = recording_widget
    original = tmp_path/'capture.tmp'
    original.write_bytes(b'original recording')
    target = tmp_path/'compatible.mp4'
    def fail_conversion(source, destination):
        raise RuntimeError('encode failed')
    monkeypatch.setattr(module, 'convert_to_h264', fail_conversion)
    widget._move_raw_file(str(original), str(target), None, False)
    from PyQt5.QtWidgets import QApplication
    QApplication.instance().processEvents()
    assert not target.exists()
    assert (tmp_path/'compatible_原始.mp4').read_bytes() == b'original recording'
    assert 'encode failed' in widget.record_stats_label.toolTip()


def test_slow_video_rate_command_does_not_block_controls(recording_widget, monkeypatch):
    """A congested video socket must not stall the GUI's control timers."""
    import threading
    import time
    from PyQt5.QtCore import QTimer
    from PyQt5.QtTest import QTest
    from ui import stereo_camera_widget as module
    widget, _, _ = recording_widget
    widget._relay_mode = widget._fps_control_supported = True
    widget.record_mode.setCurrentIndex(widget.record_mode.findData('raw'))
    release = threading.Event()
    started = threading.Event()
    def slow_send(_command, **_kwargs):
        """Emulate a blocked socket without affecting the main thread."""
        started.set()
        return release.wait(3)
    widget.stream_client.send_command = slow_send
    class EmptyRaw:
        """Return a completed empty recorder for this command-queue test."""
        def __init__(self, _path):
            self.finished = threading.Event()
            self.finished.set()
        def stop(self, timeout=10):
            return True
        def snapshot(self):
            return 0, 0, None
    monkeypatch.setattr(module, 'TimestampedJpegWriter', EmptyRaw)
    ticks = []
    timer = QTimer()
    timer.setInterval(5)
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start()
    before = time.perf_counter()
    widget._toggle_recording()
    assert time.perf_counter()-before < .2 and widget.recording
    assert started.wait(1)
    QTest.qWait(40)
    assert ticks
    release.set()
    widget._stop_recording(prompt_for_path=False)
    QTest.qWait(100)
    timer.stop()


def test_stale_rate_command_is_not_sent_to_new_video_connection():
    """An old queued command must not affect a newly reconnected video service."""
    from ui.stereo_camera_widget import StereoVideoClient
    client = StereoVideoClient()
    client.connected = True
    client.connection_id = 2
    client.socket = Mock()
    assert not client.send_command('SET_STREAM_FPS 30', expected_connection=1)
    client.socket.sendall.assert_not_called()
    assert client.send_command('SET_STREAM_FPS 15', expected_connection=2)
    client.socket.sendall.assert_called_once_with(b'SET_STREAM_FPS 15\n')
