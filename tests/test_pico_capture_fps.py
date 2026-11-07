"""Video-only rate command validation, without opening a camera or sockets."""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]/'pico_stereo'))
pytest.importorskip('pico_stereo.stereo_stream', reason='Pico source tree is not present')
from pico_stereo.stereo_stream import StereoRelay, discover_stereo_modes


def decode_reply(data):
    """Decode the relay's framed JSON reply."""
    return json.loads(data[5:].decode('utf-8'))


def test_rate_can_switch_and_restore_without_enabling_camera(tmp_path):
    """Commands change only send timing, preserve camera state and accept old 60 FPS."""
    file = tmp_path/'calibration.npz'
    np.savez(file, image_size=np.array([640, 480]))
    relay = StereoRelay(file, stream_fps=15, resolution_options=[])
    assert relay.state()['fps_switch'] is True
    assert decode_reply(relay.command('SET_STREAM_FPS 30'))['stream_fps'] == 30
    assert relay.cap is None
    assert decode_reply(relay.command('SET_STREAM_FPS 60'))['stream_fps'] == 60
    assert decode_reply(relay.command('SET_STREAM_FPS 15'))['stream_fps'] == 15
    assert decode_reply(relay.command('SET_STREAM_FPS 120'))['stream_fps'] == 120
    assert decode_reply(relay.command('SET_STREAM_FPS 15'))['stream_fps'] == 15
    for bad in ('NaN', '0', '121', 'oops', '-1'):
        assert decode_reply(relay.command('SET_STREAM_FPS '+bad))['type'] == 'error'
        assert relay.state()['stream_fps'] == 15


def test_discovery_parses_only_reported_mjpg_rates(monkeypatch):
    """Do not invent rate modes or mix single-camera and YUYV formats."""
    from types import SimpleNamespace
    data = """[0]: 'MJPG'
 Size: Discrete 1280x480
 Interval: Discrete 0.033s (30.000 fps)
 Interval: Discrete 0.008s (120.000 fps)
 Size: Discrete 3200x1200
 Interval: Discrete 0.017s (60.000 fps)
 Size: Discrete 640x480
 Interval: Discrete 0.008s (120.000 fps)
 [1]: 'YUYV'
 Size: Discrete 3200x1200
 Interval: Discrete 0.008s (120.000 fps)
"""
    monkeypatch.setattr('pico_stereo.stereo_stream.subprocess.run',
                        lambda *a, **k: SimpleNamespace(returncode=0, stdout=data))
    assert discover_stereo_modes(17) == {(1280, 480): [30, 120], (3200, 1200): [60]}


def test_atomic_capture_mode_checks_capability_and_camera_state(tmp_path):
    """Invalid or busy requests never change any part of the selected mode."""
    file = tmp_path/'calibration.npz'
    np.savez(file, image_size=np.array([640, 480]))
    modes = {(1280, 480): [15, 30, 60, 120], (3200, 1200): [15, 30, 60]}
    relay = StereoRelay(file, resolution_options=list(modes), fps_options=modes)
    assert decode_reply(relay.command('SET_CAPTURE_MODE 3200 1200 120 bad'))['type'] == 'error'
    state = decode_reply(relay.command('SET_CAPTURE_MODE 1280 480 120 a'))
    assert (state['capture_fps'], state['stream_fps'], state['request_id']) == (120, 120, 'a')
    epoch = state['camera_epoch']
    assert decode_reply(relay.command('SET_CAPTURE_MODE 1280 480 120 b'))['camera_epoch'] == epoch
    relay.cap = object()
    assert decode_reply(relay.command('SET_CAPTURE_MODE 3200 1200 60 c'))['type'] == 'error'
    assert (relay.width, relay.height, relay.capture_fps) == (640, 480, 120)


def test_camera_open_failure_reports_state_without_losing_connection(tmp_path):
    """A rejected driver FPS should return the camera-off state and the failure."""
    file = tmp_path/'calibration.npz'
    np.savez(file, image_size=np.array([640, 480]))
    def fail():
        raise ValueError('FPS readback failed')
    relay = StereoRelay(file, resolution_options=[], capture_factory=fail)
    response = decode_reply(relay.command('CAM_ON'))
    assert not response['camera_on'] and 'FPS readback failed' in response['error']


def test_native_capture_rejects_unconfirmed_driver_rate(monkeypatch):
    """A successful ioctl is not enough when the driver readback differs."""
    from types import SimpleNamespace
    from unittest.mock import Mock
    from pico_stereo.native_mjpeg import NativeMjpegCapture
    run = Mock(side_effect=[SimpleNamespace(), SimpleNamespace(),
                            SimpleNamespace(stdout='Frames per second: 30.000 (30/1)')])
    start = Mock()
    monkeypatch.setattr('pico_stereo.native_mjpeg.subprocess.run', run)
    monkeypatch.setattr('pico_stereo.native_mjpeg.subprocess.Popen', start)
    with pytest.raises(ValueError, match='采集帧率'):
        NativeMjpegCapture(17, 1280, 480, fps=120)
    start.assert_not_called()
