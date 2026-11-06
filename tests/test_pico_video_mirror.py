"""Check the Git-tracked Pico video source mirror and native JPEG framing."""
import importlib.util
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
MIRROR = ROOT/'board_support/pico_video'
spec = importlib.util.spec_from_file_location('mirrored_native_mjpeg', MIRROR/'native_mjpeg.py')
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)


def test_embedded_jpeg_end_marker_is_not_a_frame_boundary():
    """JPEG APP payloads may contain marker-like bytes without ending a frame."""
    ok, encoded = cv2.imencode('.jpg', np.zeros((24, 32, 3), dtype=np.uint8))
    assert ok
    jpeg = encoded.tobytes()
    jpeg = jpeg[:2]+b'\xff\xe1\x00\x06\xff\xd9xy'+jpeg[2:]
    assert native.jpeg_end(jpeg) == len(jpeg)
    assert native.jpeg_end(jpeg[:-1]) is None


def test_mirror_matches_project_source_when_present():
    """Do not silently diverge when the full multi-repository workspace exists."""
    source = ROOT.parents[1]/'pico_stereo'/'pico_stereo'
    if source.is_dir():
        for name in ('native_mjpeg.py', 'stereo_stream.py'):
            assert (MIRROR/name).read_bytes() == (source/name).read_bytes()
