"""Camera-only stereo JPEG relay: no matcher, WLS or point-cloud computation."""

import hashlib
import json
from pathlib import Path
import re
import select
import socket
import subprocess
import threading
import time

import cv2
import numpy as np

from .stereo_lib import open_stereo_capture
from .native_mjpeg import NativeMjpegCapture
from .stereo_transport import encode_packet, encode_blob, STEREO_FRAME, CALIBRATION, MESSAGE


# UVC also advertises native-mono modes; even width alone does not imply SBS.
STEREO_SBS_MODES = ((640, 240), (1280, 480), (1600, 600), (2560, 720), (3200, 1200))


def discover_stereo_resolutions(camera_index):
    """Read MJPG capabilities without streaming, intersecting known SBS layouts."""
    try:
        result = subprocess.run(['v4l2-ctl', '-d', f'/dev/video{int(camera_index)}',
                                 '--list-formats-ext'], capture_output=True, text=True,
                                encoding='utf-8', errors='replace', timeout=3, check=False)
        if result.returncode:
            return []
        mjpg, sizes = False, set()
        for line in result.stdout.splitlines():
            if re.search(r"\[\d+\]:\s*'", line):
                mjpg = "'MJPG'" in line
            match = re.search(r'Size:\s*Discrete\s+(\d+)x(\d+)', line)
            if mjpg and match:
                sizes.add(tuple(map(int, match.groups())))
        return [size for size in STEREO_SBS_MODES if size in sizes]
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return []


def jpeg_dimensions(data):
    """Check native JPEG SOF dimensions without decompressing on the Pico."""
    if not data.startswith(b'\xff\xd8'):
        raise ValueError('Expected native JPEG')
    pos = 2
    while pos + 4 <= len(data):
        if data[pos] != 255:
            break
        while pos < len(data) and data[pos] == 255:
            pos += 1
        if pos >= len(data):
            break
        marker = data[pos]
        pos += 1
        if marker in (0xd8, 0xd9) or 0xd0 <= marker <= 0xd7:
            continue
        length = int.from_bytes(data[pos:pos+2], 'big')
        if length < 2 or pos+length > len(data):
            break
        if marker in (0xc0, 0xc1, 0xc2) and length >= 8:
            return int.from_bytes(data[pos+5:pos+7], 'big'), int.from_bytes(data[pos+3:pos+5], 'big')
        if marker == 0xda:
            break
        pos += length
    raise ValueError('JPEG has no supported SOF')


class StereoRelay:
    """One camera and one controlling video client, with bounded latest-frame storage."""

    def __init__(self, calibration, port=9998, camera_index=17, stream_fps=15.0,
                 capture_factory=None, logger=print, resolution_options=None):
        """Read calibration bytes only; never instantiate the depth algorithm."""
        self.calibration = Path(calibration).read_bytes()
        if len(self.calibration) > 8*1024*1024:
            raise ValueError('Calibration too large')
        self.sha256 = hashlib.sha256(self.calibration).hexdigest()
        with np.load(calibration, allow_pickle=False) as data:
            self.width, self.height = map(int, np.asarray(data['image_size']).reshape(-1))
        if not (192 < self.width <= 2560 and 0 < self.height <= 1440):
            raise ValueError('Unsupported calibration dimensions')
        self.port, self.camera_index = int(port), int(camera_index)
        self.resolution_options = (discover_stereo_resolutions(self.camera_index)
                                   if resolution_options is None else list(resolution_options))
        self.interval = 1.0/max(1.0, min(float(stream_fps), 60.0))
        self.default_interval = self.interval
        self.capture_factory = capture_factory or self._open_capture
        self.log = logger
        self.lock = threading.Lock()
        self.camera_io = threading.Lock()
        self.cap = None
        self.latest = None
        self.frame_id = 0
        self.error = ''
        self.encoding = 'not-open'
        self.camera_epoch = 0
        self.stopped = threading.Event()
        self.server = self.client = None
        self.capture_thread = self.server_thread = None

    def _open_capture(self):
        """Request calibrated SBS MJPG with the original auto-exposure/gain controls."""
        try:
            native = NativeMjpegCapture(self.camera_index, self.width*2, self.height)
            if jpeg_dimensions(native.first.tobytes()) != (self.width*2, self.height):
                native.release()
                raise ValueError('原生 MJPEG 实际分辨率不匹配')
            self.encoding = 'native-mjpg'
            self.log(json.dumps(dict(event='camera_open', requested=[self.width*2, self.height],
                                     encoding=self.encoding)))
            return native
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            self.log(json.dumps(dict(event='native_mjpg_fallback', error=str(exc))))
        cap = open_stereo_capture(self.camera_index, self.width*2, self.height,
                                  exposure=0, gain=0, auto_gain=120)
        cap.set(cv2.CAP_PROP_FPS, 60)
        actual = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        if actual != (self.width*2, self.height):
            cap.release()
            raise RuntimeError(f'Actual capture {actual} differs from requested {(self.width*2, self.height)}')
        raw_ok = cap.set(cv2.CAP_PROP_FORMAT, -1)
        self.encoding = 'native-mjpg' if raw_ok else 'bgr-jpeg-fallback'
        self.log(json.dumps(dict(event='camera_open', requested=[self.width*2, self.height],
                                 actual=[cap.get(3), cap.get(4)], fps=cap.get(5),
                                 raw_format=cap.get(cv2.CAP_PROP_FORMAT), encoding=self.encoding)))
        return cap

    def camera(self, enabled):
        """Open/close idempotently; serialize reads and releases on the same lock."""
        with self.camera_io, self.lock:
            if enabled and self.cap is None:
                self.cap = self.capture_factory()
                self.error = ''
                self.camera_epoch += 1
            elif not enabled and self.cap is not None:
                self.cap.release()
                self.cap = None
                self.camera_epoch += 1
            if not enabled:
                self.latest = None

    def state(self):
        """Expose actual camera state and explicitly advertise computer-side depth."""
        with self.lock:
            return dict(type='node_state', protocol='stereo-relay-v1', camera_on=self.cap is not None,
                        ranging_on=False, board_rec_on=False, layout='stereo_pair',
                        calibration_sha256=self.sha256, source_width=self.width*2,
                        source_height=self.height, stream_fps=1/self.interval,
                        resolution_options=[dict(width=w, height=h) for w, h in self.resolution_options],
                        resolution_switch=bool(self.resolution_options),
                        fps_switch=True,
                        encoding=self.encoding, error=self.error, camera_epoch=self.camera_epoch)

    def command(self, line):
        """Return bounded replies; refuse legacy commands that could compute on Pico."""
        if line.split(' ', 1)[0] == 'SET_STREAM_FPS':
            try:
                parts = line.split()
                fps = float(parts[1]) if len(parts) == 2 else 0.0
                if not 1.0 <= fps <= 60.0:
                    raise ValueError('帧率须在 1–60 FPS 范围内')
                with self.lock:
                    self.interval = 1.0 / fps
                result = self.state()
                result['command'] = 'SET_STREAM_FPS'
                return self._message(result)
            except (ValueError, OverflowError) as exc:
                return self._message(dict(type='error', command='SET_STREAM_FPS', message=str(exc)))
        if line.split(' ', 1)[0] == 'SET_RESOLUTION':
            return self._set_resolution(line)
        if line == 'CAM_ON':
            self.camera(True)
        elif line == 'CAM_OFF':
            self.camera(False)
        elif line == 'GET_CALIBRATION':
            return encode_packet(CALIBRATION, encode_blob(
                dict(sha256=self.sha256, bytes=len(self.calibration), format='npz'), self.calibration))
        elif line not in ('GET_STATE', 'PING', 'RANGE_OFF'):
            return self._message(dict(type='error', command=line[:64],
                                      message='Relay only; depth and recording run on the computer'))
        return self._message(self.state())

    def _set_resolution(self, line):
        """Configure the next capture only when off; acknowledge exact request identity."""
        parts = line.split()
        request_id = parts[3][:64] if len(parts) >= 4 else ''
        try:
            if len(parts) != 4 or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', request_id):
                raise ValueError('Expected SET_RESOLUTION width height request_id')
            size = (int(parts[1]), int(parts[2]))
            with self.camera_io, self.lock:
                if self.cap is not None:
                    raise ValueError('Close camera before changing resolution')
                if size not in self.resolution_options:
                    raise ValueError('Unsupported stereo MJPG resolution')
                if size != (self.width*2, self.height):
                    self.width, self.height = size[0]//2, size[1]
                    self.latest = None
                    self.camera_epoch += 1
                    self.error = ''
            result = self.state()
            result.update(command='SET_RESOLUTION', request_id=request_id)
            self.log(json.dumps(dict(event='resolution_selected', requested=list(size),
                                     camera_on=False, request_id=request_id)))
            return self._message(result)
        except (ValueError, TypeError) as exc:
            return self._message(dict(type='error', command='SET_RESOLUTION',
                                      request_id=request_id, message=str(exc)))

    @staticmethod
    def _message(value):
        """Encode a JSON status without exposing filesystem paths to clients."""
        return encode_packet(MESSAGE, json.dumps(value, allow_nan=False).encode('utf-8'))

    def start(self):
        """Bind before starting threads so port errors are reported synchronously."""
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(('0.0.0.0', self.port))
        self.port = self.server.getsockname()[1]
        self.server.listen(1)
        self.server.settimeout(.25)
        self.capture_thread = threading.Thread(target=self._capture, daemon=True, name='stereo-capture')
        self.server_thread = threading.Thread(target=self._serve, daemon=True, name='stereo-relay')
        self.capture_thread.start()
        self.server_thread.start()
        self.log(json.dumps(dict(event='relay_listen', port=self.port, calibration_sha256=self.sha256,
                                 depth_compute=False)))

    def _capture(self):
        """Drain capture continuously; hold only one atomic JPEG pair for transmission."""
        while not self.stopped.is_set():
            try:
                with self.camera_io:
                    with self.lock:
                        cap, epoch = self.cap, self.camera_epoch
                        width, height = self.width*2, self.height
                    if cap is None:
                        frame = None
                    else:
                        ok, frame = cap.read()
                        if not ok:
                            raise RuntimeError('Camera read failed')
                if frame is None:
                    self.stopped.wait(.02)
                    continue
                captured = time.monotonic_ns()
                if frame.ndim == 2 and frame.dtype == np.uint8 and frame.shape[0] == 1:
                    jpeg = frame.tobytes()
                    encoding = 'native-mjpg'
                    if jpeg_dimensions(jpeg) != (width, height):
                        raise ValueError('Native JPEG dimensions differ from selected stereo resolution')
                else:
                    if frame.shape != (height, width, 3):
                        raise ValueError('Camera delivered incorrect stereo dimensions')
                    ok, encoded = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
                    if not ok:
                        raise RuntimeError('JPEG encoding failed')
                    jpeg, encoding = encoded.tobytes(), 'bgr-jpeg-fallback'
                with self.lock:
                    if self.cap is not cap or self.camera_epoch != epoch:
                        continue
                    self.frame_id += 1
                    self.encoding = encoding
                    metadata = dict(frame_id=self.frame_id, capture_monotonic_ns=captured,
                                    source_width=width, source_height=height,
                                    calibration_sha256=self.sha256, camera_epoch=epoch, encoding=encoding)
                    self.latest = (self.frame_id, encode_packet(STEREO_FRAME, encode_blob(metadata, jpeg)))
            except Exception as exc:
                self.log(json.dumps(dict(event='capture_error', error=str(exc))))
                with self.camera_io, self.lock:
                    # An obsolete read must not close a newly opened camera generation.
                    if self.cap is cap and self.camera_epoch == epoch:
                        if self.cap is not None:
                            self.cap.release()
                            self.cap = None
                            self.camera_epoch += 1
                        self.latest = None
                        self.error = str(exc)

    def _serve(self):
        """Serve one UI connection; close the camera automatically after disconnect."""
        while not self.stopped.is_set():
            try:
                connection, address = self.server.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            self.client = connection
            connection.settimeout(3.0)
            self.log(json.dumps(dict(event='video_client', peer=address[0])))
            try:
                connection.sendall(self._message(self.state()))
                self._handle(connection)
            except (OSError, ValueError) as exc:
                self.log(json.dumps(dict(event='client_closed', error=str(exc))))
            finally:
                connection.close()
                self.client = None
                self.camera(False)
                with self.lock:
                    self.interval = self.default_interval

    def _handle(self, connection):
        """Interleave commands and fresh frames without queueing stale JPEG pairs."""
        pending, last_frame, next_send = b'', -1, 0.0
        last_state = None
        while not self.stopped.is_set():
            # Wait to the actual send deadline, not a fixed 10ms polling grid.
            # The old grid rounded 66.7ms up and reduced a requested 15FPS to ~14FPS.
            wait = min(.02, max(.001, next_send-time.monotonic()))
            readable, _, _ = select.select([connection], [], [], wait)
            if readable:
                part = connection.recv(1024)
                if not part:
                    return
                pending += part
                if len(pending) > 4096:
                    raise ValueError('Command buffer too large')
                while b'\n' in pending:
                    line, pending = pending.split(b'\n', 1)
                    if len(line) > 1024:
                        raise ValueError('Command too long')
                    try:
                        reply = self.command(line.decode('ascii').strip())
                    except Exception as exc:
                        reply = self._message(dict(type='error', message=str(exc)))
                    connection.sendall(reply)
            state = self.state()
            state_key = (state['camera_on'], state['camera_epoch'], state['error'])
            if state_key != last_state:
                connection.sendall(self._message(state))
                last_state = state_key
            now = time.monotonic()
            with self.lock:
                latest = self.latest
            if latest and latest[0] != last_frame and now >= next_send:
                connection.sendall(latest[1])
                last_frame, next_send = latest[0], now+self.interval

    def close(self):
        """Release sockets and capture; a process timeout remains the final read-hang bound."""
        self.stopped.set()
        for connection in (self.client, self.server):
            if connection:
                try:
                    connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                connection.close()
        self.camera(False)
        for thread in (self.capture_thread, self.server_thread):
            if thread:
                thread.join(2)
