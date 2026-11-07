"""Bounded native V4L2 MJPEG capture with no OpenCV decode/re-encode."""
import os
import re
import select
import subprocess
import time

import numpy as np


def jpeg_end(data):
    """Find an actual JPEG EOI while skipping marker payloads and stuffed bytes."""
    if len(data) < 2 or data[:2] != b'\xff\xd8':
        raise ValueError('JPEG SOI missing')
    pos = 2
    scan = False
    while pos < len(data):
        if scan:
            marker = data.find(b'\xff', pos)
            if marker < 0 or marker + 1 >= len(data):
                return None
            pos = marker
        if data[pos] != 0xff:
            raise ValueError('Invalid JPEG marker')
        while pos < len(data) and data[pos] == 0xff:
            pos += 1
        if pos >= len(data):
            return None
        kind = data[pos]
        pos += 1
        if scan and (kind == 0 or 0xd0 <= kind <= 0xd7):
            continue
        scan = False
        if kind == 0xd9:
            return pos
        if kind == 0xd8 or 0xd0 <= kind <= 0xd7 or kind == 1:
            continue
        if pos + 2 > len(data):
            return None
        length = int.from_bytes(data[pos:pos+2], 'big')
        if length < 2:
            raise ValueError('Invalid JPEG segment length')
        if pos + length > len(data):
            return None
        pos += length
        if kind == 0xda:
            scan = True
    return None


class NativeMjpegCapture:
    """Capture atomic native JPEG buffers via a single managed V4L2 process."""

    def __init__(self, camera_index, width, height, fps=60):
        """Set the existing auto-exposure policy and start an owned capture process."""
        device = '/dev/video{}'.format(int(camera_index))
        subprocess.run(['v4l2-ctl', '-d', device, '-c', 'exposure_auto=3',
                        '-c', 'gain=120', '-c', 'white_balance_temperature_auto=1'],
                       capture_output=True, timeout=3, check=False)
        subprocess.run(['v4l2-ctl', '-d', device,
                        '--set-fmt-video=width={},height={},pixelformat=MJPG'.format(width, height),
                        '--set-parm={}'.format(int(fps))],
                       capture_output=True, timeout=3, check=True)
        readback = subprocess.run(['v4l2-ctl', '-d', device, '--get-parm'],
                                  capture_output=True, text=True, timeout=3, check=True)
        match = re.search(r'Frames per second:\s*([0-9.]+)', readback.stdout)
        if not match or abs(float(match.group(1)) - fps) > 0.5:
            raise ValueError('相机未确认所选采集帧率: ' + readback.stdout.strip())
        self.actual_fps = float(match.group(1))
        self.process = subprocess.Popen(['v4l2-ctl', '-d', device,
                                         '--stream-mmap=4', '--stream-to=-'],
                                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                        bufsize=0)
        self.buffer = bytearray()
        self.first = None
        try:
            ok, self.first = self._read_frame(timeout=3.0)
            if not ok:
                raise RuntimeError('原生 MJPEG 首帧超时')
        except Exception:
            self.release()
            raise

    def _read_frame(self, timeout=1.0):
        """Read a complete JPEG before timeout without unbounded accumulation."""
        deadline = time.monotonic() + timeout
        while True:
            start = self.buffer.find(b'\xff\xd8')
            if start >= 0:
                if start:
                    del self.buffer[:start]
                end = jpeg_end(self.buffer)
                if end is not None:
                    data = bytes(self.buffer[:end])
                    del self.buffer[:end]
                    return True, np.frombuffer(data, dtype=np.uint8).reshape(1, -1)
            elif len(self.buffer) > 1:
                del self.buffer[:-1]
            if len(self.buffer) > 12_000_000:
                raise ValueError('原生 JPEG 超过安全大小')
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False, None
            ready, _, _ = select.select([self.process.stdout], [], [], remaining)
            if not ready:
                return False, None
            chunk = os.read(self.process.stdout.fileno(), 65536)
            if not chunk:
                return False, None
            self.buffer.extend(chunk)

    def read(self):
        """Return the retained first frame or read the next bounded frame."""
        if self.first is not None:
            frame, self.first = self.first, None
            return True, frame
        return self._read_frame()

    def release(self):
        """Terminate only this capture subprocess, then release its pipe."""
        process = getattr(self, 'process', None)
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        if process.stdout:
            process.stdout.close()
        self.process = None
