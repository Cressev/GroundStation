"""End-to-end timestamp and fault tests with synthetic frames, no hardware."""

import time

import cv2
import numpy as np
import pytest

from stereo.recording import RealtimeVideoWriter


@pytest.mark.parametrize('intervals', [
    [0.125] * 12,
    [0.04, 0.22, 0.08, 0.18, 0.05, 0.23, 0.12, 0.15, 0.18, 0.15, 0.1],
    [0.04] * 35,
])
def test_real_mp4_duration_tracks_wall_time_at_variable_input_rates(tmp_path, intervals):
    """8 FPS, jitter and fast input keep real duration with bounded time error."""
    path = str(tmp_path/'timeline.mp4')
    encoder = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*'mp4v'), 15, (64, 48))
    assert encoder.isOpened()
    frame = np.zeros((48, 64, 3), np.uint8)
    start = time.monotonic()
    recorder = RealtimeVideoWriter(encoder, 15, start, frame)
    try:
        for index, delay in enumerate(intervals):
            time.sleep(delay)
            recorder.submit(np.full_like(frame, (index * 17) % 255))
        end = time.monotonic()
    finally:
        assert recorder.stop(time.monotonic(), timeout=10)
    assert recorder.error is None
    capture = cv2.VideoCapture(path)
    assert capture.isOpened()
    try:
        fps = capture.get(cv2.CAP_PROP_FPS)
        count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        decoded = 0
        while capture.read()[0]:
            decoded += 1
    finally:
        capture.release()
    assert fps == pytest.approx(15)
    assert decoded == count == recorder.output_count
    assert abs(count/fps - (end-start)) <= 2/fps
    if intervals[0] == 0.125:
        assert count > len(intervals)


def test_encoder_failure_is_reported_and_released():
    """An encoder exception does not silently produce a successful status."""
    class BrokenWriter:
        def __init__(self):
            self.released = False

        def write(self, frame):
            raise RuntimeError('disk write failed')

        def release(self):
            self.released = True

    writer = BrokenWriter()
    recorder = RealtimeVideoWriter(writer, 15, time.monotonic(), np.zeros((2, 2, 3)))
    assert recorder.finished.wait(3)
    assert 'disk write failed' in recorder.error
    assert recorder.output_count == 0
    assert writer.released
    assert recorder.stop(time.monotonic())


def test_missing_input_holds_last_frame_and_preserves_duration(tmp_path):
    """During an input stall the most recent image persists on the time axis."""
    path = str(tmp_path/'stall.mp4')
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*'mp4v'), 15, (64, 48))
    assert writer.isOpened()
    start = time.monotonic()
    recorder = RealtimeVideoWriter(writer, 15, start, np.zeros((48, 64, 3), np.uint8))
    time.sleep(.25)
    recorder.submit(np.full((48, 64, 3), 200, np.uint8))
    time.sleep(.5)
    end = time.monotonic()
    assert recorder.stop(end, timeout=5)
    assert recorder.error is None
    video = cv2.VideoCapture(path)
    means = []
    while True:
        ok, frame = video.read()
        if not ok:
            break
        means.append(float(frame.mean()))
    video.release()
    assert len(means) == recorder.output_count
    assert means[0] < 10 and means[-1] > 180
    assert abs(len(means)/15 - (end-start)) <= 2/15


def test_encoder_lag_is_bounded_and_reported():
    """A slow encoder does not accumulate unlimited queued work."""
    import threading

    clock = [100.0]
    first = threading.Event()

    class Writer:
        def write(self, frame):
            first.set()

        def release(self):
            pass

    recorder = RealtimeVideoWriter(Writer(), 15, clock[0], np.zeros((2, 2, 3)),
                                   clock=lambda: clock[0])
    assert first.wait(2)
    clock[0] += 3.0
    recorder.submit(np.ones((2, 2, 3)))
    assert recorder.finished.wait(2)
    assert recorder.error is not None
    assert recorder.output_count < 45
