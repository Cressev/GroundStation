"""Local NPZ selection, source binding and UI state tests without board access."""

import hashlib
import io
import json
from unittest.mock import patch

import cv2
import numpy as np
import pytest

from test_ui_state_machine import ensure_app
from stereo.calculation import StereoCalculator
from ui.stereo_camera_widget import StereoFishCameraWidget


def npz_bytes(width=256, height=48, scale=1.0):
    """Create a complete valid file with distinguishable environment correction."""
    y, x = np.mgrid[:height, :width].astype(np.float32)
    stream = io.BytesIO()
    np.savez(stream, map1x=x, map1y=y, map2x=x, map2y=y,
             Q=np.eye(4), image_size=[width, height], depth_scale=scale)
    return stream.getvalue()


@pytest.fixture
def widget():
    """Keep worker/network resources isolated and close them after every test."""
    ensure_app()
    view = StereoFishCameraWidget()
    view.commands = []
    view.stream_client.send_command = lambda command: view.commands.append(command) or True
    yield view
    view.close()


def announce(view, board_bytes):
    """Provide the real relay descriptor and exact current connection ID."""
    view._fish_connection_available = True
    view._stream_state = 'connected'
    digest = hashlib.sha256(board_bytes).hexdigest()
    view._on_message(json.dumps(dict(type='node_state', protocol='stereo-relay-v1',
        camera_on=True, source_width=512, source_height=48, calibration_sha256=digest)))
    return dict(connection_id=view.stream_client.connection_id, sha256=digest, bytes=len(board_bytes))


def test_model_binds_capture_hash_separately_from_selected_npz():
    """Different environment files must work without accepting a different video source."""
    board, local = npz_bytes(), npz_bytes(scale=1.3)
    source = hashlib.sha256(board).hexdigest()
    model = StereoCalculator(local, hashlib.sha256(local).hexdigest(), source_sha256=source)
    frame = np.zeros((48, 512, 3), np.uint8)
    result = model.process(frame, dict(frame_id=1, calibration_sha256=source), enabled=False)
    assert result['calibration_sha256'] == hashlib.sha256(local).hexdigest()
    assert result['source_sha256'] == source
    with pytest.raises(ValueError):
        model.process(frame, {'calibration_sha256': '0'*64}, enabled=False)


def test_local_npz_before_connect_and_reconnect_is_not_overwritten(widget, tmp_path):
    """A selected environment survives server callbacks and reconnect without overrides."""
    local, board = npz_bytes(scale=1.3), npz_bytes()
    path = tmp_path/'stereo_params_updated_with_glass.npz'
    path.write_bytes(local)
    assert widget.load_calibration_file(str(path))
    assert widget._local_model is None
    metadata = announce(widget, board)
    assert widget._local_model.sha256 == hashlib.sha256(local).hexdigest()
    assert widget._local_model.source_sha256 == metadata['sha256']
    widget._on_calibration(metadata, board)
    assert widget._local_model.sha256 == hashlib.sha256(local).hexdigest()
    widget._reset_remote_state()
    widget.stream_client.connection_id += 1
    metadata = announce(widget, board)
    widget._on_calibration(metadata, board)
    assert widget._local_model.sha256 == hashlib.sha256(local).hexdigest()
    assert not any(command.startswith(('RANGE_ON', 'SET_POINT')) for command in widget.commands)


def test_switch_back_to_board_clears_old_result_and_point(widget, tmp_path):
    """Model changes cancel queued/in-flight output and clear old visible distance."""
    board, local = npz_bytes(), npz_bytes(scale=1.3)
    metadata = announce(widget, board)
    widget._on_calibration(metadata, board)
    path = tmp_path/'local.npz'
    path.write_bytes(local)
    assert widget.load_calibration_file(str(path))
    widget._local_result = {'old': True}
    widget._selected_point = (230, 24)
    widget.distance_label.setText('old distance')
    previous_generation = widget.worker.generation
    widget._use_board_calibration()
    assert widget._local_model.sha256 == metadata['sha256']
    assert widget._chosen_calibration is None
    assert widget._local_result is None and widget._selected_point is None
    assert widget.distance_label.text().endswith('--')
    assert widget.worker.generation > previous_generation


@pytest.mark.parametrize('content', [b'not npz', npz_bytes(width=320)], ids=['invalid-bytes', 'wrong-size'])
def test_rejected_file_keeps_previous_model_and_reports_error(widget, tmp_path, content):
    """A corrupt or mismatched file must not silently become active."""
    board = npz_bytes()
    widget._on_calibration(announce(widget, board), board)
    previous = widget._local_model
    path = tmp_path/'bad.npz'
    path.write_bytes(content)
    assert not widget.load_calibration_file(str(path))
    assert widget._local_model is previous
    assert widget._chosen_calibration is None
    assert '失败' in widget.calibration_status_label.text()


def test_loading_file_dialog_cancel_changes_nothing(widget):
    """Cancel is a no-op; no network command or calibration selection changes."""
    with patch('ui.stereo_camera_widget.QFileDialog.getOpenFileName', return_value=('', '')):
        widget._choose_calibration_file()
    assert widget._chosen_calibration is None and widget.commands == []


def test_selected_size_mismatch_on_later_connection_blocks_measurement(widget, tmp_path):
    """A file validated offline is not used for a later differently-sized capture."""
    path = tmp_path/'other.npz'
    path.write_bytes(npz_bytes(width=320))
    assert widget.load_calibration_file(str(path))
    board = npz_bytes()
    widget._on_calibration(announce(widget, board), board)
    assert widget._chosen_calibration is not None
    assert widget._local_model is None
    assert not widget.range_btn.isEnabled()
    assert '不匹配' in widget.calibration_status_label.text()


def test_only_one_local_file_is_needed_without_board_npz(widget, tmp_path):
    """Relay descriptor plus raw pair plus local final NPZ is sufficient."""
    board = npz_bytes()
    announce(widget, board)
    path = tmp_path/'stereo_params_updated.npz'
    path.write_bytes(npz_bytes(scale=1.1))
    assert widget.load_calibration_file(str(path))
    assert widget._local_model is not None
    assert widget._board_calibration is None
    assert '水下标定' not in widget.mode_label.text()


def test_missing_fields_and_oversized_files_are_rejected(widget, tmp_path):
    """Corner archives and oversized blobs are not usable final calibration files."""
    buffer = io.BytesIO()
    np.savez(buffer, corners=np.zeros((2, 2)))
    path = tmp_path/'corners.npz'
    path.write_bytes(buffer.getvalue())
    assert not widget.load_calibration_file(str(path))
    assert '缺少必需字段' in widget.calibration_status_label.text()
    path.write_bytes(b'x'*(8*1024*1024+1))
    assert not widget.load_calibration_file(str(path))
    assert widget._chosen_calibration is None


def test_recording_must_stop_before_user_changes_model(widget, tmp_path):
    """Disable file switches while saving so a recording never mixes calibrations."""
    widget.recording = True
    widget._apply_ui_state()
    assert not widget.load_npz_btn.isEnabled() and not widget.board_npz_btn.isEnabled()
    assert not widget.load_calibration_file(str(tmp_path/'unused.npz'))
    assert '录像' in widget.calibration_status_label.text()


def test_stale_calibration_callback_cannot_replace_local_model(widget, tmp_path):
    """Old connection metadata never changes the chosen active matcher."""
    board = npz_bytes()
    metadata = announce(widget, board)
    path = tmp_path/'local.npz'
    path.write_bytes(npz_bytes(scale=1.3))
    assert widget.load_calibration_file(str(path))
    previous = widget._local_model
    metadata['connection_id'] -= 1
    widget._on_calibration(metadata, board)
    assert widget._local_model is previous


def test_first_frame_marks_active_without_hiding_file_error(widget):
    """New output ends the waiting hint, but never hides a rejected selection warning."""
    board = npz_bytes()
    metadata = announce(widget, board)
    widget._on_calibration(metadata, board)
    result = widget._local_model.process(np.zeros((48, 512, 3), np.uint8),
        dict(frame_id=1, calibration_sha256=metadata['sha256']), enabled=False)
    with patch.object(widget.worker, 'take_latest', return_value=result):
        widget._poll_local_result()
    assert '已生效' in widget.calibration_status_label.text()
    widget._local_result = None
    widget._refresh_calibration_label('加载失败，仍保留当前参数', error=True)
    with patch.object(widget.worker, 'take_latest', return_value=result):
        widget._poll_local_result()
    assert '加载失败' in widget.calibration_status_label.text()


def test_valid_file_is_restored_after_widget_restart(widget, tmp_path):
    """Only a validated choice is persisted and automatically revalidated after restart."""
    path = tmp_path/'中文 标定.npz'
    path.write_bytes(npz_bytes())
    assert widget.load_calibration_file(str(path))
    widget.close()
    restored = StereoFishCameraWidget()
    try:
        assert restored._chosen_calibration['path'] == str(path.resolve())
        assert '中文 标定.npz' in restored.calibration_file_label.text()
        assert str(path.resolve()) == restored.calibration_source_input.text()
        assert '校验通过' in restored.calibration_status_label.text()
        assert restored._local_model is None  # Wait for the real source geometry.
    finally:
        restored.close()


@pytest.mark.parametrize('replacement', [None, b'broken'], ids=['missing', 'corrupt'])
def test_restored_bad_file_blocks_board_fallback(widget, tmp_path, replacement):
    """A deleted or corrupted saved file must never silently activate the board model."""
    path = tmp_path/'remember.npz'
    path.write_bytes(npz_bytes())
    assert widget.load_calibration_file(str(path))
    widget.close()
    if replacement is None:
        path.unlink()
    else:
        path.write_bytes(replacement)
    restored = StereoFishCameraWidget()
    try:
        restored.commands = []
        restored.stream_client.send_command = lambda command: restored.commands.append(command) or True
        board = npz_bytes()
        restored._on_calibration(announce(restored, board), board)
        assert restored._local_model is None and restored._chosen_calibration is None
        assert '自动加载失败' in restored.calibration_status_label.text()
        assert str(path.resolve()) == restored.calibration_source_input.text()
        assert restored.board_npz_btn.isEnabled()
        assert 'GET_CALIBRATION' not in restored.commands
        restored._use_board_calibration()
        assert restored._local_model is not None
    finally:
        restored.close()


def test_bad_selection_does_not_replace_saved_path(widget, tmp_path):
    """Failed manual choices cannot become next startup's default file."""
    good, bad = tmp_path/'good.npz', tmp_path/'bad.npz'
    good.write_bytes(npz_bytes())
    bad.write_bytes(b'bad')
    assert widget.load_calibration_file(str(good))
    assert not widget.load_calibration_file(str(bad))
    restored = StereoFishCameraWidget()
    try:
        assert restored._chosen_calibration['path'] == str(good.resolve())
    finally:
        restored.close()


def test_board_mode_is_remembered_after_restart(widget, tmp_path):
    """Explicit board restore clears local preference immediately, not just on close."""
    path = tmp_path/'remember.npz'
    path.write_bytes(npz_bytes())
    assert widget.load_calibration_file(str(path))
    widget._use_board_calibration()
    restored = StereoFishCameraWidget()
    try:
        assert restored._chosen_calibration is None and not restored._calibration_path
    finally:
        restored.close()


@pytest.mark.parametrize('field,value', [
    ('Q', np.full((4, 4), np.nan)),
    ('map1x', np.zeros((48, 256), np.float64)),
    ('swap_capture_halves', 'False'),
    ('depth_scale', -1),
], ids=['Q-nan', 'map-dtype', 'swap-string', 'negative-scale'])
def test_invalid_npz_content_rejected_before_remembering(widget, tmp_path, field, value):
    """The .npz suffix alone is insufficient; validate all consumed model fields."""
    with np.load(io.BytesIO(npz_bytes()), allow_pickle=False) as archive:
        values = {key: archive[key] for key in archive.files}
    values[field] = value
    buffer = io.BytesIO()
    np.savez(buffer, **values)
    path = tmp_path/'invalid.npz'
    path.write_bytes(buffer.getvalue())
    assert not widget.load_calibration_file(str(path))
    assert widget._chosen_calibration is None and not widget._calibration_path


def test_path_is_restored_in_a_new_process(widget, tmp_path, isolated_stereo_settings):
    """A fresh Python/Qt process reads a flushed path and revalidates its actual bytes."""
    import subprocess
    import sys
    from pathlib import Path

    path = tmp_path/'跨进程标定.npz'
    path.write_bytes(npz_bytes())
    assert widget.load_calibration_file(str(path))
    code = '''
import json, sys
sys.path.insert(0, sys.argv[3])
import stereo_runtime
from PyQt5.QtCore import QSettings
from PyQt5.QtWidgets import QApplication
from ui.stereo_camera_widget import StereoFishCameraWidget
app = QApplication([])
view = StereoFishCameraWidget(settings=QSettings(sys.argv[1], QSettings.IniFormat))
assert view._chosen_calibration['path'] == sys.argv[2]
assert view._local_model is None
print(json.dumps(dict(path=view.calibration_source_input.text(), status=view.calibration_status_label.text()), ensure_ascii=True))
view.close()
'''
    result = subprocess.run([sys.executable, '-X', 'utf8', '-c', code,
        isolated_stereo_settings, str(path.resolve()), str(Path(__file__).resolve().parents[1])],
        capture_output=True, text=True, encoding='utf-8', timeout=20)
    assert result.returncode == 0, result.stderr
    message = json.loads(result.stdout.strip().splitlines()[-1])
    assert message['path'] == str(path.resolve()) and '校验通过' in message['status']
