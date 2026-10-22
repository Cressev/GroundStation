"""Offline real-window NPZ selection QA using archived stereo pairs; no hardware access."""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

GS = Path(__file__).resolve().parents[1]
ROOT = GS.parents[1]
sys.path.insert(0, str(GS))
import stereo_runtime
import cv2
import numpy as np
from PyQt5.QtCore import QPointF, Qt, QSettings
from PyQt5.QtGui import QMouseEvent
from PyQt5.QtWidgets import QApplication

from stereo.calculation import measure_depth
from ui.stereo_camera_widget import StereoFishCameraWidget


def sha256(path):
    """Fingerprint archived inputs before and after the read-only verification."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def wait_for_frame(app, widget, frame_id):
    """Pump the real Qt event loop while the production worker computes the JPEG."""
    deadline = time.monotonic()+10
    while time.monotonic() < deadline:
        app.processEvents()
        widget._poll_local_result()
        result = widget._local_result
        if result is not None and result['frame_id'] == frame_id:
            return result
        time.sleep(.005)
    raise RuntimeError('No current-model frame: '+widget.range_state_label.text())


def click_and_capture(app, widget, output, name):
    """Send a real mouse event, check its marker, and save only the displayed eye."""
    result = widget._local_result
    valid = np.isfinite(result['disparity']) & (result['disparity'] > 0)
    yy, xx = np.nonzero(valid)
    selected = None
    for index in range(len(xx)//2, len(xx), 41):
        u, v = int(xx[index]), int(yy[index])
        value = measure_depth(result['disparity'], result['points'], u, v,
                              result['scale'], result['offset'])
        if value:
            selected = (u, v)
            break
    # A correct UI also marks a point with invalid depth instead of retaining an old value.
    u, v = selected or (result['image'].shape[1]//2, result['image'].shape[0]//2)
    height, width = result['image'].shape[:2]
    left, top, shown_w, shown_h = widget.video_label.image_rectangle()
    position = QPointF(left+(height-1-v+.5)*shown_w/height, top+(u+.5)*shown_h/width)
    event = QMouseEvent(QMouseEvent.MouseButtonPress, position,
                        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(widget.video_label, event)
    app.processEvents()
    assert widget._selected_point is not None
    assert abs(widget._selected_point[0]-u) <= 2 and abs(widget._selected_point[1]-v) <= 2
    snapshot = output/(name+'_single.png')
    assert widget.save_snapshot(str(snapshot))
    image = cv2.imdecode(np.fromfile(snapshot, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image.shape == (width, height, 3)
    assert widget.grab().save(str(output/(name+'_window.png')))
    return dict(valid_depth=selected is not None, selected=widget._selected_point,
                distance=widget.distance_label.text(), snapshot_shape=list(image.shape))


def main():
    """Exercise three real environment files, default restore and worker identity offline."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    board = ROOT/'tmp/host_stereo_20261021_0102/backup/calibration.npz'
    inputs = ROOT/'tmp/stereo_15fps_20261019_1429/inputs.npz'
    directory = ROOT/'src/rect/inner-param/盒子'
    paths = [directory/name for name in ('stereo_params_updated.npz',
             'stereo_params_updated_with_glass.npz', 'stereo_params_updated_underwater.npz')]
    fingerprints = {str(path): sha256(path) for path in [board, inputs]+paths}
    with np.load(board, allow_pickle=False) as data:
        raw_swapped = bool(data['swap_capture_halves'].item()) if 'swap_capture_halves' in data else False
    with np.load(inputs, allow_pickle=False) as data:
        left, right = data['left'].copy(), data['right'].copy()
    # Reconstruct the original raw UVC order, independently of the selected environment file.
    pairs = [np.hstack((r, l) if raw_swapped else (l, r)) for l, r in zip(left, right)]
    app = QApplication([])
    widget = StereoFishCameraWidget(settings=QSettings(str(output/'settings.ini'), QSettings.IniFormat))
    widget.setWindowTitle('离线历史帧验证 · 不连接Pico · NPZ选择')
    widget.resize(1180, 1100)
    widget.show()
    app.processEvents()
    commands = []

    def capture_command(command):
        """Capture would-be protocol messages without opening any socket."""
        commands.append(command)
        return True

    widget.stream_client.send_command = capture_command
    widget._fish_connection_available = True
    widget._stream_state = 'connected'
    board_bytes = board.read_bytes()
    digest = fingerprints[str(board)]
    widget._on_message(json.dumps(dict(type='node_state', protocol='stereo-relay-v1',
        camera_on=True, source_width=1280, source_height=480, calibration_sha256=digest)))
    widget.status_label.setText('离线验证：历史双目帧，不连接Pico，不验证实际精度')
    widget._on_calibration(dict(connection_id=widget.stream_client.connection_id,
        sha256=digest, bytes=len(board_bytes)), board_bytes)
    cases = []
    try:
        for index, path in enumerate(paths):
            generation = widget.worker.generation
            with patch('ui.stereo_camera_widget.QFileDialog.getOpenFileName',
                       return_value=(str(path), '标定参数 (*.npz)')):
                widget.load_npz_btn.click()
            assert widget._local_model.sha256 == fingerprints[str(path)]
            assert widget._local_model.source_sha256 == digest
            assert widget.worker.generation > generation
            assert widget._selected_point is None and widget._local_result is None
            # A delayed board callback must not overwrite the chosen local environment.
            widget._on_calibration(dict(connection_id=widget.stream_client.connection_id,
                sha256=digest, bytes=len(board_bytes)), board_bytes)
            assert widget._local_model.sha256 == fingerprints[str(path)]
            rows = []
            best = None
            for pair_index, pair in enumerate(pairs):
                ok, jpeg = cv2.imencode('.jpg', pair, [cv2.IMWRITE_JPEG_QUALITY, 90])
                assert ok
                frame_id = index*100+pair_index
                widget._submit_stereo(dict(frame_id=frame_id, calibration_sha256=digest,
                    connection_id=widget.stream_client.connection_id), jpeg.tobytes())
                result = wait_for_frame(app, widget, frame_id)
                count = int(np.count_nonzero(np.isfinite(result['disparity']) & (result['disparity'] > 0)))
                rows.append(dict(frame_id=frame_id, positive_disparities=count,
                                 compute_ms=result['compute_ms']))
                if best is None or count > best[0]:
                    best = (count, jpeg.tobytes())
            frame_id = index*100+99
            widget._submit_stereo(dict(frame_id=frame_id, calibration_sha256=digest,
                connection_id=widget.stream_client.connection_id), best[1])
            wait_for_frame(app, widget, frame_id)
            app.processEvents()
            case = dict(path=str(path), sha256=widget._local_model.sha256,
                        source_sha256=widget._local_model.source_sha256, rows=rows,
                        status=widget.calibration_status_label.text())
            case.update(click_and_capture(app, widget, output, path.stem))
            cases.append(case)
        widget.close()
        widget = StereoFishCameraWidget(settings=QSettings(str(output/'settings.ini'), QSettings.IniFormat))
        assert widget._chosen_calibration['path'] == str(paths[-1].resolve())
        assert '校验通过' in widget.calibration_status_label.text()
        assert widget._local_model is None
        widget.resize(1180, 1100)
        widget.setWindowTitle('离线验证 · 重开自动恢复NPZ · 不连接Pico')
        widget.show()
        app.processEvents()
        assert widget.grab().save(str(output/'restored_startup.png'))
        widget.stream_client.send_command = capture_command
        widget._fish_connection_available = True
        widget._stream_state = 'connected'
        widget._on_message(json.dumps(dict(type='node_state', protocol='stereo-relay-v1',
            camera_on=True, source_width=1280, source_height=480, calibration_sha256=digest)))
        widget._on_calibration(dict(connection_id=widget.stream_client.connection_id,
            sha256=digest, bytes=len(board_bytes)), board_bytes)
        assert widget._local_model.sha256 == fingerprints[str(paths[-1])]
        widget.board_npz_btn.click()
        assert widget._chosen_calibration is None and widget._local_model.sha256 == digest
        assert widget._selected_point is None and widget._local_result is None
        assert all(not command.startswith(('RANGE_ON', 'SET_POINT')) for command in commands)
        assert fingerprints == {str(path): sha256(path) for path in [board, inputs]+paths}
        widget.close()
        failed_settings = QSettings(str(output/'missing-settings.ini'), QSettings.IniFormat)
        failed_settings.setValue('stereo/last_npz/dual', str(output/'missing.npz'))
        failed_settings.sync()
        widget = StereoFishCameraWidget(settings=failed_settings)
        assert widget._chosen_calibration is None and widget._calibration_path
        widget.stream_client.send_command = capture_command
        widget._fish_connection_available = True
        widget._stream_state = 'connected'
        widget._on_message(json.dumps(dict(type='node_state', protocol='stereo-relay-v1',
            camera_on=True, source_width=1280, source_height=480, calibration_sha256=digest)))
        widget._on_calibration(dict(connection_id=widget.stream_client.connection_id,
            sha256=digest, bytes=len(board_bytes)), board_bytes)
        assert widget._local_model is None
        assert '自动加载失败' in widget.calibration_status_label.text()
        widget.resize(1180, 1100)
        widget.setWindowTitle('离线验证 · 上次NPZ丢失 · 不静默切换参数')
        widget.show()
        app.processEvents()
        assert widget.grab().save(str(output/'restored_missing_file.png'))
        summary = dict(kind='offline_historical_frames_not_accuracy_validation',
            interpreter=sys.executable, opencv=cv2.__version__, qt_platform=app.platformName(),
            source_npz=str(board), inputs=str(inputs), raw_swapped=raw_swapped,
            cases=cases, startup_restore_passed=True, board_restore_passed=True, inputs_unchanged=True,
            startup_failure_blocked=True,
            commands=commands, sockets_opened=False, board_loads_started=0)
        (output/'summary.json').write_text(json.dumps(summary, ensure_ascii=True, indent=2), encoding='utf-8')
        print(json.dumps(summary, ensure_ascii=True))
    finally:
        widget.close()
        app.processEvents()


if __name__ == '__main__':
    main()
