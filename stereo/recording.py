"""Bounded, monotonic-clock resampling for constant-frame-rate video files."""

import math
import threading
import time


class RealtimeVideoWriter:
    """Encode the latest input on a fixed time grid in one background thread.

    The queue contains at most one pending frame. Missing input is represented
    by holding the last image; excessive encoder lag fails explicitly instead
    of allowing unbounded latency or silently shortening the video.
    """

    def __init__(self, writer, fps, start_time, initial_frame, clock=time.monotonic,
                 max_lag_seconds=2.0):
        """Take ownership of an already-open writer and start encoding."""
        self.writer = writer
        self.fps = float(fps)
        self.start_time = start_time
        self.clock = clock
        self.max_lag_frames = max(1, int(self.fps * max_lag_seconds))
        self.condition = threading.Condition()
        self.latest = initial_frame
        self.output_count = 0
        self.error = None
        self.end_time = None
        self.finished = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True,
                                       name='stereo-video-encoder')
        self.thread.start()

    def submit(self, frame):
        """Replace the pending image without accumulating an unbounded queue."""
        with self.condition:
            if self.end_time is not None or self.error is not None:
                return False
            self.latest = frame
            self.condition.notify()
            return True

    def snapshot(self):
        """Return encoder progress and any asynchronous error."""
        with self.condition:
            return self.output_count, self.error

    def stop(self, end_time, timeout=5.0):
        """Finish through the stop timestamp, waiting at most timeout seconds."""
        with self.condition:
            if self.end_time is None:
                self.end_time = max(self.start_time, end_time)
            self.condition.notify_all()
        if not self.finished.wait(timeout):
            return False
        return True

    def _run(self):
        """Sample the latest frame at 1/fps until the requested stop time."""
        try:
            while True:
                with self.condition:
                    now = self.clock()
                    elapsed = max(0.0, (self.end_time if self.end_time is not None
                                        else now) - self.start_time)
                    target = max(1, math.ceil(elapsed * self.fps))
                    if self.end_time is None:
                        target = max(1, math.floor(elapsed * self.fps) + 1)
                    if self.output_count >= target:
                        if self.end_time is not None:
                            break
                        next_time = self.start_time + self.output_count / self.fps
                        self.condition.wait(timeout=max(0.001, next_time - now))
                        continue
                    if target - self.output_count > self.max_lag_frames:
                        raise RuntimeError('视频编码跟不上实时速度，已停止以避免录像时间失真')
                    frame = self.latest
                self.writer.write(frame)
                with self.condition:
                    self.output_count += 1
        except Exception as exc:
            with self.condition:
                self.error = str(exc)
        finally:
            try:
                self.writer.release()
            except Exception as exc:
                with self.condition:
                    if self.error is None:
                        self.error = '视频文件收尾失败: '+str(exc)
            finally:
                self.finished.set()
