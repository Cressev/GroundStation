"""Real Windows Qt/TCP verification using a synthetic relay, never the actual fish."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

os.environ['QT_QPA_PLATFORM'] = 'windows'
PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT.parents[1]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(ROOT/'pico_stereo'))
import stereo_runtime
import cv2
import numpy as np
from PyQt5.QtCore import QSettings, Qt, QPointF
from PyQt5.QtGui import QMouseEvent
from PyQt5.QtWidgets import QApplication
from pico_stereo.stereo_stream import StereoRelay, STEREO_SBS_MODES
from ui.stereo_camera_widget import StereoFishCameraWidget


def write_calibration(path, width, height):
    """Write generated uncompressed identity maps, including the >8MiB case."""
    y, x = np.mgrid[:height, :width].astype(np.float32)
    q = np.array([[1, 0, 0, -width/2], [0, 1, 0, -height/2],
                  [0, 0, 0, 400], [0, 0, .5, 0]], dtype=np.float64)
    np.savez(path, image_size=[width, height], map1x=x, map1y=y, map2x=x,
             map2y=y, Q=q)


def wait_for(app, predicate, timeout=12):
    """Process real Qt events until the bounded asynchronous condition is met."""
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError('Timed out waiting for asynchronous UI/relay state')


def click_image(app, view):
    """Send a real mouse event into the middle of the displayed single eye."""
    left, top, width, height = view.video_label.image_rectangle()
    point = QPointF(left+width*.5, top+height*.5)
    event = QMouseEvent(QMouseEvent.MouseButtonPress, point, Qt.LeftButton,
                        Qt.LeftButton, Qt.NoModifier)
    app.sendEvent(view.video_label, event)


def main():
    """Exercise high-resolution selection, mismatch preview, NPZ loading and clicks."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    output = Path(parser.parse_args().output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    default, high = output/'synthetic-default.npz', output/'synthetic-high.npz'
    write_calibration(default, 640, 480)
    write_calibration(high, 1280, 720)
    original = {name: hashlib.sha256((PROJECT/name).read_bytes()).hexdigest()
                for name in ('connections.json', 'depth_zero.json', 'keyboard_params.json', 'xbox_params.json')}
    app = QApplication.instance() or QApplication([])
    events, opened = [], []
    relay = StereoRelay(default, port=0, resolution_options=STEREO_SBS_MODES, logger=events.append)

    class Capture:
        """Generate one physically plausible displaced stereo pair at requested size."""

        def __init__(self):
            """Snapshot capture geometry only when explicitly opened by the UI."""
            width, height = relay.width, relay.height
            left = np.random.default_rng(42).integers(20, 200, (height, width, 3), dtype=np.uint8)
            right = np.roll(left, -10, axis=1)
            self.pair = np.concatenate([left, right], axis=1)
            opened.append([width*2, height])

        def read(self):
            """Pace the synthetic source; never touch a video device."""
            time.sleep(.04)
            return True, self.pair

        def release(self):
            """Synthetic capture has no external resources."""

    relay.capture_factory = Capture
    relay.start()
    view = StereoFishCameraWidget(settings=QSettings(str(output/'settings.ini'), QSettings.IniFormat))
    commands = []
    send = view.stream_client.send_command

    def logged_send(command):
        """Keep exact emitted command evidence, including forbidden-command checks."""
        commands.append(command)
        return send(command)

    view.stream_client.send_command = logged_send
    try:
        view.resize(1100, 1000)
        view.show()
        view._fish_connection_available = True
        view._stream_state = 'connecting'
        view.stream_client.set_connection('127.0.0.1', relay.port)
        view.stream_client.start()
        wait_for(app, lambda: view.resolution_combo.count() == 5 and view._local_model is not None)
        view.resolution_combo.setCurrentIndex(view._resolution_options.index((2560, 720)))
        view._apply_resolution()
        wait_for(app, lambda: view._resolution_pending is None and relay.width == 1280)
        assert not opened and not view.range_btn.isEnabled()
        view.grab().save(str(output/'resolution-selected.png'))
        view._toggle_camera()
        wait_for(app, lambda: view.current_frame is not None)
        assert view.current_frame.shape == (1280, 720, 3)
        assert view._local_model is None and view._local_result['uncalibrated']
        click_image(app, view)
        assert view._selected_point is None and view.distance_label.text().endswith('--')
        view.save_snapshot(str(output/'single-uncalibrated.png'))
        view.grab().save(str(output/'preview-mismatch.png'))
        assert high.stat().st_size > 8*1024*1024
        assert view.load_calibration_file(str(high))
        wait_for(app, lambda: view._local_result is not None and view._local_result['disparity'] is not None)
        click_image(app, view)
        assert view._selected_point is not None and not view.distance_label.text().endswith('--')
        view.save_snapshot(str(output/'single-measurement.png'))
        view.grab().save(str(output/'calibrated-measurement.png'))
        measurement = view.distance_label.text()
        assert not view.resolution_combo.isEnabled()
        view._toggle_camera()
        wait_for(app, lambda: view._camera_state == 'off')
        view.resize(640, 900)
        app.processEvents()
        app.processEvents()
        assert view.page_scroll.horizontalScrollBar().maximum() == 0
        view.grab().save(str(output/'narrow-640.png'))
        assert not any(command.startswith(('RANGE_ON', 'SET_POINT', 'REC_START')) for command in commands)
        summary = dict(synthetic=True, real_fish_touched=False, commands=commands,
                       options=view._resolution_options, opened=opened,
                       high_npz_bytes=high.stat().st_size, measurement=measurement,
                       saved_shape=list(cv2.imdecode(np.fromfile(output/'single-measurement.png', np.uint8), 1).shape),
                       horizontal_scroll=view.page_scroll.horizontalScrollBar().maximum(),
                       personal_settings_unchanged=all(hashlib.sha256((PROJECT/name).read_bytes()).hexdigest() == digest
                           for name, digest in original.items()), events=events)
        assert summary['personal_settings_unchanged']
        (output/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(summary, ensure_ascii=True))
    finally:
        view.shutdown()
        view.stream_client.wait(3000)
        view.close()
        relay.close()


if __name__ == '__main__':
    main()
