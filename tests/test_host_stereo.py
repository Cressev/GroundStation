"""Bounded stereo transport and calibrated single-view regression tests."""

import hashlib
import io
import socket
import struct
import time

import cv2
import numpy as np
import pytest

from stereo.transport import encode_packet, decode_blob, encode_blob, receive_exact
from stereo.calculation import StereoCalculator, display_to_rectified, measure_depth


def calibration():
    """Build a small valid calibration without depending on the fish hardware."""
    y, x = np.mgrid[:48, :256].astype(np.float32)
    stream = io.BytesIO()
    np.savez(stream, map1x=x, map1y=y, map2x=x, map2y=y,
             image_size=np.array([256, 48]), Q=np.eye(4))
    return stream.getvalue()


def test_packet_limits_and_blob():
    """Reject malformed payloads before allocating unbounded memory."""
    payload = encode_blob({'frame_id': 3}, b'jpeg')
    assert decode_blob(payload) == ({'frame_id': 3}, b'jpeg')
    assert struct.unpack('!I', encode_packet(0xFD, payload)[:4])[0] == len(payload) + 1
    with pytest.raises(ValueError):
        decode_blob(b'\xff\xffshort')
    with pytest.raises(ValueError):
        encode_packet(0xFD, b'x' * (16 * 1024 * 1024))


def test_partial_timeout_keeps_bytes():
    """A timeout in the middle of a header must not reset its framing."""
    class Source:
        """Return fragments with a timeout between them."""
        def __init__(self):
            """Prepare a deterministic fake socket."""
            self.parts = iter([b'ab', socket.timeout(), b'cd'])

        def recv(self, size):
            """Return or raise the next fragment."""
            value = next(self.parts)
            if isinstance(value, Exception):
                raise value
            return value
    assert receive_exact(Source(), 4, lambda: False) == b'abcd'


def test_calibration_hash_and_size():
    """Never compute using a different calibration or a native mono frame."""
    data = calibration()
    digest = hashlib.sha256(data).hexdigest()
    with pytest.raises(ValueError):
        StereoCalculator(data, '0' * 64)
    model = StereoCalculator(data, digest)
    with pytest.raises(ValueError):
        model.process(np.zeros((48, 256, 3), np.uint8), {'calibration_sha256': digest})


def test_rotated_click_and_invalid_measurement():
    """Invert clockwise rotation and ignore label letterboxing."""
    assert display_to_rectified(10, 20, (10, 20, 480, 640), 640, 480) == (0, 479)
    assert display_to_rectified(489, 659, (10, 20, 480, 640), 640, 480) == (639, 0)
    assert display_to_rectified(9, 20, (10, 20, 480, 640), 640, 480) is None
    disp = np.zeros((4, 5), np.float32)
    points = np.ones((4, 5, 3), np.float32)
    assert measure_depth(disp, points, 2, 2) is None
    disp[:] = 10
    value = measure_depth(disp, points, 2, 2)
    assert value['D'] == pytest.approx(3 ** .5)


def test_latest_worker_discards_inflight_generation():
    """Camera closure invalidates even a computation already in progress."""
    import threading
    from stereo.worker import StereoWorker
    entered, release = threading.Event(), threading.Event()

    class Model:
        """Hold one computation until the camera has been reset."""
        def process_jpeg(self, data, metadata, enabled):
            """Return an obsolete result after the test releases it."""
            entered.set()
            release.wait(2)
            return {'frame_id': metadata['frame_id']}
    worker = StereoWorker()
    worker.set_model(Model())
    worker.submit({'frame_id': 1}, b'x')
    assert entered.wait(2)
    worker.invalidate()
    release.set()
    time.sleep(.05)
    assert worker.take_latest() is None
    worker.close()


def test_widget_single_view_marker_save_and_no_board_depth(tmp_path):
    """Clicks use the shown snapshot, invalidate all coordinates, and save one eye."""
    from test_ui_state_machine import ensure_app
    from ui.stereo_camera_widget import StereoFishCameraWidget
    from PyQt5.QtCore import Qt, QPointF
    from PyQt5.QtGui import QMouseEvent
    app = ensure_app()
    widget = StereoFishCameraWidget()
    commands = []
    widget.stream_client.send_command = lambda command: commands.append(command) or True
    widget.set_fish_connection_available(True)
    widget._stream_state, widget._camera_state = 'connected', 'on'
    widget._local_model = object()
    result = dict(frame_id=7, image=np.full((480, 640, 3), 60, np.uint8),
                  disparity=np.full((480, 640), 10, np.float32),
                  points=np.ones((480, 640, 3), np.float32), scale=1.0, offset=0.0,
                  compute_ms=10, metadata={})
    widget._local_result = result
    widget.show()
    app.processEvents()
    widget._render_local_result(record=True)
    left, top, width, height = widget.video_label.image_rectangle()
    point = QPointF(left+width*.5, top+height*.5)
    event = QMouseEvent(QMouseEvent.MouseButtonPress, point, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    app.sendEvent(widget.video_label, event)
    assert widget._selected_point is not None
    assert '1.73' in widget.distance_label.text()
    path = tmp_path/'single.png'
    assert widget.save_snapshot(str(path)) == str(path)
    image = cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_COLOR)
    assert image.shape == (640, 480, 3)
    assert np.any(image[:, :, 1] != image[:, :, 0]), 'Visible green marker missing'
    result['disparity'][:] = 0
    widget._render_local_result(record=False)
    assert widget.x_label.text() == 'X: --'
    assert widget.y_label.text() == 'Y: --'
    widget._toggle_ranging()
    assert not any(command.startswith(('RANGE_ON', 'SET_POINT')) for command in commands)
    widget._camera_state = 'turning_off'
    widget._clear_local_frames()
    widget._update_frame(image)
    assert widget.current_frame is None, 'Late frame resurrected a closing camera'
    widget.shutdown()
    widget.close()


@pytest.mark.parametrize('width', [480, 720, 1100])
def test_single_view_image_center_tracks_viewport_without_horizontal_overflow(width):
    """A portrait image centers in the visible page, not in a wider hidden content widget."""
    from test_ui_state_machine import ensure_app
    from ui.stereo_camera_widget import StereoFishCameraWidget
    from PyQt5.QtCore import QPoint
    app = ensure_app()
    widget = StereoFishCameraWidget()
    try:
        widget.resize(width, 760)
        widget.show()
        widget.video_label.set_frame(np.full((640, 480, 3), 120, np.uint8))
        app.processEvents()
        app.processEvents()
        viewport = widget.page_scroll.viewport()
        assert widget.page_scroll.horizontalScrollBar().maximum() == 0
        x, y, w, h = widget.video_label.image_rectangle()
        origin = widget.video_label.mapTo(viewport, QPoint(0, 0))
        assert abs(origin.x()+x+w/2.-viewport.width()/2.) <= 2.
        assert abs(y+h/2.-widget.video_label.contentsRect().center().y()) <= 1.
    finally:
        widget.shutdown()
        widget.close()
