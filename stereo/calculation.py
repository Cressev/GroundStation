"""Original SGBM192/WLS/Q calculation, now executed on the computer only."""

import hashlib
import io
import time
import zipfile

import stereo_runtime
import cv2
import numpy as np

MAX_CALIBRATION_BYTES = 32*1024*1024


def measure_depth(disparity, points, x, y, scale=1.0, offset=0.0, win=4):
    """Use the original 9x9 valid-pixel medians and underwater correction (cm)."""
    height, width = disparity.shape
    if not (0 <= x < width and 0 <= y < height):
        return None
    region = disparity[max(0, y-win):min(height, y+win+1),
                       max(0, x-win):min(width, x+win+1)].reshape(-1)
    xyz = points[max(0, y-win):min(height, y+win+1),
                 max(0, x-win):min(width, x+win+1)].reshape(-1, 3)
    valid = np.isfinite(region) & (region > 0) & np.isfinite(xyz).all(axis=1)
    if not valid.any():
        return None
    raw = np.median(xyz[valid], axis=0)
    X, Y = scale*float(raw[0]), scale*float(raw[1])
    Z = abs(scale*(abs(float(raw[2]))-offset))
    if not 0 < Z <= 1000:
        return None
    return dict(disp=float(np.median(region[valid])), X=X, Y=Y, Z=Z,
                Z_raw=float(raw[2]), D=float(np.sqrt(X*X+Y*Y+Z*Z)),
                valid_count=int(valid.sum()))


def display_to_rectified(x, y, rectangle, width, height):
    """Map the actual pixmap rectangle through inverse clockwise rotation."""
    left, top, shown_width, shown_height = rectangle
    if not (shown_width > 0 and shown_height > 0 and
            left <= x < left+shown_width and top <= y < top+shown_height):
        return None
    dx = min(height-1, int((x-left)*height/shown_width))
    dy = min(width-1, int((y-top)*width/shown_height))
    return dy, height-1-dx


class StereoCalculator:
    """Validate a connection's calibration and preserve the board's algorithm."""

    def __init__(self, calibration_bytes, expected_sha256, source_sha256=None):
        """Load bounded non-pickle NPZ and construct mandatory SGBM/WLS matchers."""
        self.sha256 = hashlib.sha256(calibration_bytes).hexdigest()
        if self.sha256 != expected_sha256:
            raise ValueError('Calibration SHA256 mismatch')
        self.source_sha256 = source_sha256 if source_sha256 is not None else self.sha256
        if (not isinstance(self.source_sha256, str) or len(self.source_sha256) != 64 or
                any(value not in '0123456789abcdef' for value in self.source_sha256)):
            raise ValueError('Invalid capture source SHA256')
        if len(calibration_bytes) > MAX_CALIBRATION_BYTES:
            raise ValueError('Calibration too large')
        with zipfile.ZipFile(io.BytesIO(calibration_bytes)) as archive:
            if len(archive.infolist()) > 64 or sum(v.file_size for v in archive.infolist()) > 32*1024*1024:
                raise ValueError('Expanded calibration too large')
        with np.load(io.BytesIO(calibration_bytes), allow_pickle=False) as data:
            missing = {'image_size', 'map1x', 'map1y', 'map2x', 'map2y', 'Q'}-set(data.files)
            if missing:
                raise ValueError('NPZ缺少必需字段: '+', '.join(sorted(missing)))
            size = np.asarray(data['image_size']).reshape(-1)
            if len(size) != 2 or not np.isfinite(size).all() or not np.equal(size, size.astype(int)).all():
                raise ValueError('Invalid image_size')
            self.width, self.height = map(int, size)
            if not (192 < self.width <= 2560 and 0 < self.height <= 1440):
                raise ValueError('Unsupported calibration dimensions')
            self.maps = [np.array(data[key], copy=True) for key in ('map1x', 'map1y', 'map2x', 'map2y')]
            for mapping in self.maps:
                if mapping.shape != (self.height, self.width) or mapping.dtype != np.float32 or not np.isfinite(mapping).all():
                    raise ValueError('Invalid rectification maps')
            if data['Q'].dtype.kind not in 'fiub':
                raise ValueError('Invalid Q matrix numeric type')
            self.Q = np.asarray(data['Q'], dtype=np.float64)
            if self.Q.shape != (4, 4) or not np.isfinite(self.Q).all():
                raise ValueError('Invalid Q matrix')
            swap = data['swap_capture_halves'] if 'swap_capture_halves' in data else np.array(False)
            if swap.size != 1 or swap.dtype.kind not in 'biuf' or not np.isin(swap, [0, 1]).all():
                raise ValueError('Invalid swap_capture_halves: expected boolean or 0/1')
            self.swap = bool(swap.item())
            for key in ('depth_scale', 'depth_offset_cm'):
                if key in data and (data[key].size != 1 or data[key].dtype.kind not in 'fiub'):
                    raise ValueError('Invalid numeric scalar: '+key)
            self.scale = float(data['depth_scale'].item()) if 'depth_scale' in data else 1.0
            self.offset = float(data['depth_offset_cm'].item()) if 'depth_offset_cm' in data else 0.0
            if not np.isfinite([self.scale, self.offset]).all() or self.scale <= 0:
                raise ValueError('Invalid underwater correction')
        if not hasattr(cv2, 'ximgproc') or not hasattr(cv2.ximgproc, 'createDisparityWLSFilter'):
            raise RuntimeError('缺少OpenCV-contrib WLS；请运行ref/install_local_stereo_runtime.py并重启地面站')
        self.left = cv2.StereoSGBM_create(
            minDisparity=0, numDisparities=192, blockSize=5, P1=600, P2=2400,
            disp12MaxDiff=1, uniquenessRatio=10, speckleWindowSize=100,
            speckleRange=32, preFilterCap=63, mode=cv2.STEREO_SGBM_MODE_SGBM_3WAY)
        # Factory order matters: WLS changes the left matcher's internal parameters.
        self.right = cv2.ximgproc.createRightMatcher(self.left)
        self.wls = cv2.ximgproc.createDisparityWLSFilter(self.left)
        self.wls.setLambda(80000)
        self.wls.setSigmaColor(1.3)

    def process(self, pair, metadata, enabled=True):
        """Return one rectified left image and its exact-frame depth snapshot."""
        if metadata.get('calibration_sha256') != self.source_sha256:
            raise ValueError('Frame/capture source mismatch')
        if pair.shape != (self.height, self.width*2, 3):
            raise ValueError('Stereo frame dimensions do not match calibration')
        start = time.perf_counter()
        first, second = pair[:, :self.width], pair[:, self.width:]
        left, right = (second, first) if self.swap else (first, second)
        rect_left = cv2.remap(left, *self.maps[:2], cv2.INTER_LINEAR)
        disparity, points = None, None
        if enabled:
            rect_right = cv2.remap(right, *self.maps[2:], cv2.INTER_LINEAR)
            gray_left = cv2.cvtColor(rect_left, cv2.COLOR_BGR2GRAY)
            gray_right = cv2.cvtColor(rect_right, cv2.COLOR_BGR2GRAY)
            dl = self.left.compute(gray_left, gray_right)
            dr = self.right.compute(gray_right, gray_left)
            disparity = self.wls.filter(dl, gray_left, None, dr).astype(np.float32)/16.0
            points = cv2.reprojectImageTo3D(disparity, self.Q)
        return dict(frame_id=metadata.get('frame_id'), image=rect_left, disparity=disparity,
                    points=points, scale=self.scale, offset=self.offset,
                    calibration_sha256=self.sha256, source_sha256=self.source_sha256,
                    compute_ms=(time.perf_counter()-start)*1000, metadata=metadata)

    def process_jpeg(self, data, metadata, enabled=True):
        """Decode the atomic side-by-side JPEG before calibrated processing."""
        # Bound dimensions before imdecode can allocate a decompressed image.
        width, height = jpeg_size(data)
        if (width, height) != (self.width*2, self.height):
            raise ValueError('JPEG dimensions do not match calibration')
        pair = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if pair is None:
            raise ValueError('Invalid JPEG frame')
        return self.process(pair, metadata, enabled)


class StereoPreview:
    """Display only the raw first eye when no matching calibration is available."""

    def __init__(self, source):
        """Bind preview geometry and source identity without constructing a matcher."""
        self.width, self.height = source['width']//2, source['height']
        self.source_sha256 = source['sha256']

    def process_jpeg(self, data, metadata, enabled=True):
        """Validate before decoding, never resize maps/Q or return a distance."""
        if metadata.get('calibration_sha256') != self.source_sha256:
            raise ValueError('Frame/capture source mismatch')
        if jpeg_size(data) != (self.width*2, self.height):
            raise ValueError('JPEG dimensions do not match selected capture')
        pair = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if pair is None:
            raise ValueError('Invalid JPEG frame')
        return dict(frame_id=metadata.get('frame_id'), image=pair[:, :self.width].copy(),
                    disparity=None, points=None, scale=1.0, offset=0.0, compute_ms=0.0,
                    metadata=metadata, uncalibrated=True)


def jpeg_size(data):
    """Read JPEG SOF dimensions without decoding untrusted image allocations."""
    if not data.startswith(b'\xff\xd8'):
        raise ValueError('Expected JPEG')
    pos = 2
    while pos + 4 <= len(data):
        if data[pos] != 0xff:
            raise ValueError('Invalid JPEG marker')
        while pos < len(data) and data[pos] == 0xff:
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
        if marker in (0xc0, 0xc1, 0xc2):
            if length < 8:
                break
            return int.from_bytes(data[pos+5:pos+7], 'big'), int.from_bytes(data[pos+3:pos+5], 'big')
        if marker == 0xda:
            break
        pos += length
    raise ValueError('JPEG has no supported SOF')
