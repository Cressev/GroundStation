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
    ensure_app()
    widget = module.StereoFishCameraWidget(QSettings(str(tmp_path/'settings.ini'), QSettings.IniFormat))
    widget._stream_state, widget._camera_state = 'connected', 'on'
    widget.current_frame = np.zeros((80, 60, 3), np.uint8)
    widget._apply_ui_state()
    writer = Mock()
    writer.isOpened.return_value = True
    monkeypatch.setattr(module.cv2, 'VideoWriter', Mock(return_value=writer))
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
    """Status follows the snapshot button, with no page horizontal overflow."""
    from PyQt5.QtCore import QPoint
    from PyQt5.QtWidgets import QApplication
    widget, writer, clock = recording_widget
    widget.resize(1100, 800)
    widget.show()
    app = QApplication.instance()
    app.processEvents()
    app.processEvents()
    label = widget.record_stats_label
    assert label.mapTo(widget.action_bar, QPoint()).x() >= widget.snapshot_btn.geometry().right()
    assert abs(label.geometry().center().y()-widget.record_btn.geometry().center().y()) <= 1
    widget.resize(480, 800)
    app.processEvents()
    app.processEvents()
    assert widget.page_scroll.horizontalScrollBar().maximum() == 0
    assert widget.action_scroll.horizontalScrollBar().maximum() > 0


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
    assert len(list((tmp_path/'records').glob('*.mp4'))) == 1


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
