"""Real mux/decode checks for source-timed JPEG recordings, with no hardware."""
import time

import cv2
import numpy as np
import pytest

av = pytest.importorskip('av')
from stereo.recording import TimestampedJpegWriter


def test_variable_frame_timing_survives_mp4_roundtrip(tmp_path):
    """Four inputs remain four frames with original irregular intervals."""
    out = tmp_path/'timed.mp4'
    writer = TimestampedJpegWriter(str(out))
    offsets = [0, 33_000_000, 105_000_000, 200_000_000]
    for index, offset in enumerate(offsets):
        image = np.full((240, 320, 3), index*40, dtype=np.uint8)
        ok, encoded = cv2.imencode('.jpg', image)
        assert ok
        assert writer.submit(dict(capture_monotonic_ns=1_000_000_000+offset,
                                  source_width=320, source_height=240, camera_epoch=1),
                             encoded.tobytes())
    assert writer.stop()
    assert writer.snapshot() == (4, 4, None)
    with av.open(str(out)) as container:
        frames = list(container.decode(video=0))
    assert len(frames) == 4
    assert [float(frame.time) for frame in frames] == pytest.approx([0, .033, .105, .2], abs=.002)


def test_invalid_timestamp_stops_without_silent_retiming(tmp_path):
    """Duplicate source timestamps are an explicit error, never a fabricated FPS."""
    writer = TimestampedJpegWriter(str(tmp_path/'bad.mp4'))
    ok, jpeg = cv2.imencode('.jpg', np.zeros((32, 64, 3), dtype=np.uint8))
    assert ok
    meta = dict(capture_monotonic_ns=1000, source_width=64, source_height=32, camera_epoch=1)
    assert writer.submit(meta, jpeg.tobytes())
    assert writer.submit(meta, jpeg.tobytes())
    assert writer.stop()
    assert writer.snapshot()[2]


def test_last_frame_holds_to_stop_without_adding_frames(tmp_path):
    """A pause before stop must not silently shorten elapsed recording time."""
    now = [1_000_000_000]
    out = tmp_path/'hold.mp4'
    writer = TimestampedJpegWriter(str(out), clock_ns=lambda: now[0])
    ok, jpeg = cv2.imencode('.jpg', np.zeros((32, 64, 3), dtype=np.uint8))
    assert ok
    base = dict(source_width=64, source_height=32, camera_epoch=1)
    assert writer.submit(dict(base, capture_monotonic_ns=3_000_000_000), jpeg.tobytes())
    now[0] += 100_000_000
    assert writer.submit(dict(base, capture_monotonic_ns=3_100_000_000), jpeg.tobytes())
    now[0] += 500_000_000
    assert writer.stop()
    assert writer.snapshot() == (2, 2, None)
    with av.open(str(out)) as container:
        assert len(list(container.decode(video=0))) == 2
        assert container.duration/1_000_000 == pytest.approx(.6, abs=.01)
