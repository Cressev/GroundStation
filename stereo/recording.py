"""Bounded, monotonic-clock resampling for constant-frame-rate video files."""

import math
from fractions import Fraction
import queue
import threading
import time


class TimestampedJpegWriter:
    """Save received JPEGs with source timestamps using a bounded background queue."""

    def __init__(self, path, queue_size=90, clock_ns=time.perf_counter_ns):
        """Start an isolated writer; fail immediately if the optional runtime is absent."""
        import av
        self.av = av
        self.path = path
        self.queue = queue.Queue(maxsize=queue_size)
        self.lock = threading.Lock()
        self.clock_ns = clock_ns
        self.stop_time_ns = None
        self.ending = False
        self.error = None
        self.input_count = 0
        self.output_count = 0
        self.finished = threading.Event()
        self.thread = threading.Thread(target=self._run_jpeg, daemon=True,
                                       name='stereo-jpeg-recorder')
        self.thread.start()

    def submit(self, metadata, jpeg):
        """Never block the network thread; stop explicitly if storage falls behind."""
        with self.lock:
            if self.ending or self.error:
                return False
            try:
                self.queue.put_nowait((dict(metadata), jpeg, self.clock_ns()))
            except queue.Full:
                self.error = '录像写入跟不上输入，已停止；不会静默丢帧'
                self.ending = True
                self.stop_time_ns = self.clock_ns()
                return False
            self.input_count += 1
            return True

    def snapshot(self):
        """Return input/output counts and any asynchronous failure."""
        with self.lock:
            return self.input_count, self.output_count, self.error

    def stop(self, timeout=10.0):
        """Drain pending packets and close the container without inventing frames."""
        with self.lock:
            if self.stop_time_ns is None:
                self.stop_time_ns = self.clock_ns()
            self.ending = True
        return self.finished.wait(timeout)

    def _run_jpeg(self):
        """Mux complete JPEGs into a variable-frame-rate MP4 using capture timestamps."""
        container = None
        previous_ns = None
        previous_pts = None
        first_ns = None
        source = None
        pending = None
        last_received_ns = None
        try:
            while True:
                try:
                    metadata, jpeg, received_ns = self.queue.get(timeout=.05)
                except queue.Empty:
                    with self.lock:
                        if self.ending:
                            break
                    continue
                stamp = metadata.get('capture_monotonic_ns')
                width, height = metadata.get('source_width'), metadata.get('source_height')
                epoch = metadata.get('camera_epoch')
                if (not isinstance(stamp, int) or stamp < 0 or
                        not isinstance(width, int) or not isinstance(height, int) or
                        not (0 < width <= 5120 and 0 < height <= 1440) or
                        not jpeg.startswith(b'\xff\xd8')):
                    raise ValueError('原始双目帧的时间戳、分辨率或 JPEG 格式无效')
                if previous_ns is not None and stamp <= previous_ns:
                    raise ValueError('相机时间戳未递增，已停止录像')
                if source is not None and source != (width, height, epoch):
                    raise ValueError('录像期间相机尺寸或连接发生变化')
                if container is None:
                    container = self.av.open(self.path, 'w', format='mp4')
                    stream = container.add_stream('mjpeg', rate=30)
                    stream.width, stream.height, stream.pix_fmt = width, height, 'yuvj422p'
                    stream.time_base = Fraction(1, 1_000_000)
                    source, first_ns = (width, height, epoch), stamp
                pts = (stamp - first_ns) // 1000
                if previous_pts is not None and pts <= previous_pts:
                    raise ValueError('相机时间戳间隔小于录像时间精度')
                if pending is not None:
                    pending.duration = max(1, pts - pending.pts)
                    container.mux(pending)
                    with self.lock:
                        self.output_count += 1
                packet = self.av.Packet(jpeg)
                packet.stream, packet.time_base = stream, Fraction(1, 1_000_000)
                packet.pts = packet.dts = pts
                pending = packet
                last_received_ns = received_ns
                previous_ns = stamp
                previous_pts = pts
            if pending is not None:
                with self.lock:
                    stop_time_ns = self.stop_time_ns or self.clock_ns()
                pending.duration = max(1, (stop_time_ns - last_received_ns) // 1000)
                container.mux(pending)
                with self.lock:
                    self.output_count += 1
        except Exception as exc:
            with self.lock:
                self.error = str(exc)
                self.ending = True
        finally:
            if container is not None:
                try:
                    container.close()
                except Exception as exc:
                    with self.lock:
                        self.error = self.error or str(exc)
            self.finished.set()


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
