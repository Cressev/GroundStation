"""Verify recording colors, timer and decodable MP4 using synthetic Windows Qt frames."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

os.environ['QT_QPA_PLATFORM'] = 'windows'
PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
import stereo_runtime
import cv2
import numpy as np
from PyQt5.QtCore import QSettings
from PyQt5.QtGui import QFont
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication
from ui.stereo_camera_widget import StereoFishCameraWidget


def settle(app):
    """Complete layout and timer events in the independent synthetic test window."""
    for _ in range(4):
        app.processEvents()


def button_color(button, path):
    """Inspect saved PNG bytes, avoiding temporary QImage pixel binding issues."""
    button.grab().save(str(path))
    image = cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_COLOR)
    colors, counts = np.unique(image.reshape(-1, 3), axis=0, return_counts=True)
    b, g, r = colors[counts.argmax()]
    return f'#{r:02x}{g:02x}{b:02x}'


def main():
    """Record 30 generated frames without sockets, then decode and compare the count."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    output = Path(parser.parse_args().output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    names = ['connections.json', 'depth_zero.json', 'keyboard_params.json', 'xbox_params.json']
    before = {name: hashlib.sha256((PROJECT/name).read_bytes()).hexdigest() for name in names}
    app = QApplication.instance() or QApplication([])
    app.setFont(QFont('Microsoft YaHei UI', 10))
    view = StereoFishCameraWidget(QSettings(str(output/'isolated.ini'), QSettings.IniFormat))
    view._result_timer.stop()
    commands = []
    view.stream_client.send_command = lambda command: commands.append(command) or False
    frame = np.zeros((320, 240, 3), np.uint8)
    frame[:, :, 1] = 70
    try:
        view._stream_state, view._camera_state = 'connected', 'on'
        view.current_frame = frame
        view._apply_ui_state()
        view.resize(1100, 850)
        view.show()
        settle(app)
        view.grab().save(str(output/'start-green.png'))
        start_color = button_color(view.record_btn, output/'start-button.png')
        assert start_color == '#15803d', start_color
        view.record_btn.click()
        for index in range(30):
            image = frame.copy()
            cv2.putText(image, f'frame {index+1}', (15, 70), cv2.FONT_HERSHEY_SIMPLEX, .6, (255, 255, 255), 1)
            view._update_frame(image)
            QTest.qWait(75)
        QTest.qWait(300)  # Allow the 250ms statistics timer to show the final writes.
        settle(app)
        assert view.recording and view._rec_count == 30, view.record_stats_label.text()
        live_status = view.record_stats_label.text()
        stop_color = button_color(view.record_btn, output/'stop-button.png')
        assert stop_color == '#b91c1c', stop_color
        view.grab().save(str(output/'recording-red.png'))
        view.action_bar.grab().save(str(output/'recording-toolbar.png'))
        with patch('ui.stereo_camera_widget.QFileDialog.getSaveFileName', return_value=(str(output/'single.mp4'), '')), \
             patch('ui.stereo_camera_widget.QMessageBox.information'):
            view.record_btn.click()
        frozen = view.record_stats_label.text()
        assert frozen.startswith('已停止 ') and frozen.endswith('30帧')
        QTest.qWait(1100)
        settle(app)
        assert frozen == view.record_stats_label.text()
        view.grab().save(str(output/'stopped-summary.png'))
        video = cv2.VideoCapture(str(output/'single.mp4'))
        count, sizes = 0, set()
        try:
            assert video.isOpened()
            while True:
                ok, image = video.read()
                if not ok:
                    break
                count += 1
                sizes.add(tuple(image.shape))
        finally:
            video.release()
        assert count == 30 and sizes == {(320, 240, 3)}, (count, sizes)
        assert (output/'single.mp4').stat().st_size > 0
        view.resize(480, 850)
        settle(app)
        assert view.page_scroll.horizontalScrollBar().maximum() == 0
        assert view.action_scroll.horizontalScrollBar().maximum() > 0
        view.action_scroll.ensureWidgetVisible(view.record_stats_label)
        settle(app)
        view.grab().save(str(output/'narrow-status.png'))
        assert not commands and not view.stream_client.isRunning()
        assert all(hashlib.sha256((PROJECT/name).read_bytes()).hexdigest() == digest for name, digest in before.items())
        result = dict(synthetic_only=True, hardware_touched=False, sockets_opened=False,
            qt_platform=app.platformName(), start_color=start_color, stop_color=stop_color,
            live_status=live_status, stopped_status=frozen, decoded_frames=count,
            decoded_shapes=sorted(sizes), mp4_bytes=(output/'single.mp4').stat().st_size,
            personal_files_unchanged=True)
        (output/'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=True))
    finally:
        view.close()


if __name__ == '__main__':
    main()
