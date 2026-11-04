"""Chessboard calibration and image-to-plane mapping (metres)."""

from datetime import datetime
import json
import math
import os
from pathlib import Path

import cv2
import numpy as np


PATTERN = (8, 11)
SQUARE_M = .01
MIN_VIEWS = 12


def board_points(pattern=PATTERN, square_m=SQUARE_M):
    if min(pattern) < 3 or not math.isfinite(square_m) or square_m <= 0:
        raise ValueError('棋盘内角点数或方格尺寸无效')
    points = np.zeros((pattern[0] * pattern[1], 3), np.float32)
    points[:, :2] = np.mgrid[0:pattern[0], 0:pattern[1]].T.reshape(-1, 2) * square_m
    return points


def detect_board(frame, pattern=PATTERN):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    enhanced = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8)).apply(gray)
    ok, corners = cv2.findChessboardCornersSB(enhanced, pattern, cv2.CALIB_CB_ACCURACY)
    if not ok:
        ok, corners = cv2.findChessboardCorners(enhanced, pattern,
                            cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE)
        if ok:
            corners = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1),
                        (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_MAX_ITER, 50, 1e-4))
    if not ok:
        raise ValueError('未检测到完整棋盘，请检查棋盘尺寸、清晰度和反光')
    corners = corners.reshape(-1, 1, 2).astype(np.float32)
    if corners[0, 0, 1] > corners[-1, 0, 1]:
        corners = corners[::-1].copy()
    return corners


def fit_intrinsics(views, size, pattern=PATTERN, square_m=SQUARE_M):
    if len(views) < MIN_VIEWS:
        raise ValueError(f'至少需要 {MIN_VIEWS} 张有效棋盘图')
    obj = board_points(pattern, square_m)
    rms, K, dist, rvecs, tvecs = cv2.calibrateCamera(
        [obj.copy() for _ in views], views, tuple(size), None, None,
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_MAX_ITER, 100, 1e-9))
    if not math.isfinite(rms):
        raise ValueError('内参计算失败')
    errors = []
    for image, rv, tv in zip(views, rvecs, tvecs):
        projected = cv2.projectPoints(obj, rv, tv, K, dist)[0]
        errors.append(float(np.sqrt(np.mean(np.sum((projected - image) ** 2, axis=2)))))
    return {'source': 'OpenCV monocular chessboard calibration', 'K': K.tolist(),
            'dist': dist.reshape(-1).tolist(), 'image_size_wh': list(size),
            'pattern_size_inner_corners': list(pattern), 'square_size_m': square_m,
            'rms_px': float(rms), 'per_view_rmse_px': errors, 'view_count': len(views)}


def intrinsics(calibration):
    data = calibration['intrinsics']
    K = np.asarray(data['K'], np.float64)
    dist = np.asarray(data['dist'], np.float64).reshape(-1)
    size = np.asarray(data['image_size_wh'], np.float64).reshape(-1)
    if (K.shape != (3, 3) or not np.isfinite(K).all() or K[0, 0] <= 0 or K[1, 1] <= 0
            or not np.allclose(K[2], [0, 0, 1]) or abs(K[0, 1]) > 1e-8 or abs(K[1, 0]) > 1e-8
            or dist.size not in (4, 5, 8, 12, 14) or not np.isfinite(dist).all()
            or size.size != 2 or not np.isfinite(size).all() or np.any(size <= 0)
            or not np.allclose(size, np.round(size))):
        raise ValueError('无效的内参、畸变或图像尺寸')
    return K, dist, tuple(int(x) for x in size)


def validate(calibration, require_plane=False):
    K, dist, size = intrinsics(calibration)
    ext = calibration.get('extrinsics')
    if ext is None:
        if require_plane:
            raise ValueError('尚未完成平面标定')
        return K, dist, size, None
    H = np.asarray(ext['H_undistorted_pixel_to_world_xy'], np.float64)
    if H.shape != (3, 3) or not np.isfinite(H).all() or np.linalg.matrix_rank(H) < 3:
        raise ValueError('平面映射矩阵无效')
    if ext.get('world_unit') != 'm':
        raise ValueError('仅支持以米为单位的平面标定')
    return K, dist, size, H


def fit_plane(corners, calibration, size, pattern=PATTERN, square_m=SQUARE_M):
    K, dist, expected, _ = validate(calibration)
    if tuple(size) != expected:
        raise ValueError(f'画面尺寸 {size} 与内参尺寸 {expected} 不匹配')
    image = np.asarray(corners, np.float64).reshape(-1, 2)
    world = board_points(pattern, square_m).astype(np.float64)
    if len(image) != len(world) or not np.isfinite(image).all():
        raise ValueError('棋盘角点无效')
    if abs(cv2.contourArea(cv2.convexHull(image.astype(np.float32)))) < 100:
        raise ValueError('棋盘成像太小')
    undist = cv2.undistortPoints(image.reshape(-1, 1, 2), K, dist, P=K)
    H, _ = cv2.findHomography(undist, world[:, :2], 0)
    if H is None or not np.isfinite(H).all() or np.linalg.matrix_rank(H) < 3:
        raise ValueError('平面映射退化')
    solutions = []
    for method in (cv2.SOLVEPNP_IPPE, cv2.SOLVEPNP_ITERATIVE):
        try:
            answer = cv2.solvePnPGeneric(world, image, K, dist, flags=method)
            for rv, tv in zip(answer[1], answer[2]):
                rv, tv = cv2.solvePnPRefineLM(world, image, K, dist, rv.copy(), tv.copy())
                R = cv2.Rodrigues(rv)[0]
                if not np.isfinite(R).all() or not np.isfinite(tv).all() or np.any((R @ world.T + tv.reshape(3, 1))[2] <= 0):
                    continue
                projected = cv2.projectPoints(world, rv, tv, K, dist)[0].reshape(-1, 2)
                error = float(np.sqrt(np.mean(np.sum((projected-image)**2, axis=1))))
                if math.isfinite(error):
                    solutions.append((error, rv, tv, R))
        except cv2.error:
            continue
    if not solutions:
        raise ValueError('未求得有效棋盘位姿')
    error, rv, tv, R = min(solutions, key=lambda item: item[0])
    return {'world_unit': 'm', 'calibration_plane_z_m': 0.0,
            'axes': 'First detected corner O is origin; +X follows board columns; +Y follows board rows.',
            'H_undistorted_pixel_to_world_xy': H.tolist(), 'R_world_to_camera': R.tolist(),
            't_world_to_camera_m': tv.reshape(3).tolist(), 'rvec_world_to_camera_rad': rv.reshape(3).tolist(),
            'R_camera_to_world': R.T.tolist(), 'camera_center_world_m': (-R.T @ tv).reshape(3).tolist(),
            'image_points_raw_px': image.tolist(), 'world_points_m': world.tolist(),
            'pose_reprojection_rmse_px': error, 'pattern_size_inner_corners': list(pattern),
            'square_size_m': square_m, 'scope': 'Known-height plane only; apparent model through water.',
            'quality_note': 'Validate independently with measured lengths across the pool.'}


def map_points(points, calibration):
    K, dist, _, H = validate(calibration, require_plane=True)
    raw = np.asarray(points, np.float64).reshape(-1, 1, 2)
    if not np.isfinite(raw).all():
        raise ValueError('像素坐标无效')
    undist = cv2.undistortPoints(raw, K, dist, P=K)
    homogeneous = np.c_[undist.reshape(-1, 2), np.ones(len(raw))] @ H.T
    if not np.isfinite(homogeneous).all() or np.any(np.abs(homogeneous[:, 2]) < 1e-10):
        raise ValueError('坐标映射无效')
    return homogeneous[:, :2] / homogeneous[:, 2, None]


def save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    try:
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def new_calibration(intrinsic_data, camera_id):
    return {'created_at': datetime.now().astimezone().isoformat(), 'camera_id': camera_id,
            'pipeline_schema': 'fish_planar_calibration_v1', 'intrinsics': intrinsic_data, 'extrinsics': None}
