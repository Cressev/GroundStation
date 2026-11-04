"""Behavior tests for display-only overhead tracking."""

import os
import json
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import cv2
import numpy as np
from PyQt5.QtWidgets import QApplication

from vision.top_tracker import VelocityEstimator, candidates, follow_pair, nearest_marker, pose
from vision import planar_calibration as cal
from ui.top_camera_tracking import TopCameraTrackingWidget


def scene(head=(100, 100), tail=(60, 100), missing=False):
    image = np.full((240, 320, 3), 230, np.uint8)
    cv2.circle(image, head, 12, (0, 0, 0), -1)
    if not missing:
        cv2.circle(image, tail, 7, (0, 0, 0), -1)
    return image


class FakeThread:
    def is_alive(self):
        return True


class FakeReader:
    def __init__(self, frame):
        self.frame = frame
        self.sequence = 1
        self.thread = FakeThread()
        self.source = 0
        self.pause_event = threading.Event()

    def latest(self):
        return self.sequence, self.frame, self.sequence / 10

    def stop(self):
        pass


class TrackingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_heading_and_marker_loss(self):
        spots = candidates(scene())
        head = nearest_marker(spots, (100, 100), 10)
        tail = nearest_marker(spots, (60, 100), 10)
        self.assertEqual(pose(head, tail), (80, 100, 0))
        self.assertIsNotNone(follow_pair(candidates(scene((105, 103), (65, 103))), head, tail))
        self.assertIsNone(follow_pair(candidates(scene(missing=True)), head, tail))
        self.assertAlmostEqual(pose((100, 120, 1), (100, 100, 1))[2], 90)

    def test_equal_size_middle_markers_and_heading(self):
        image = np.full((240, 320, 3), 230, np.uint8)
        cv2.circle(image, (100, 100), 10, (0, 0, 0), -1)
        cv2.circle(image, (60, 100), 10, (0, 0, 0), -1)
        widget = TopCameraTrackingWidget()
        widget.reader, widget.active = FakeReader(image), True
        widget.refresh()
        widget.select_marker(100, 100)  # The middle marker closer to the head.
        widget.select_marker(60, 100)
        self.assertIsNone(widget.selecting)
        widget.reader.sequence += 1
        widget.refresh()
        self.assertIn('中段中点 X=80.0, Y=100.0', widget.status.text())
        self.assertIn('图像航向 0.0°', widget.status.text())
        self.assertEqual(len(widget.trail), 1)
        widget.shutdown()
        widget.timer.stop()

    def test_velocity_wrap_and_timestamp_discontinuity(self):
        estimator = VelocityEstimator()
        self.assertIsNone(estimator.update(1.0, 0, 0, 359))
        self.assertIsNone(estimator.update(1.1, .1, 0, 0))
        vx, vy, speed, omega = estimator.update(1.2, .2, 0, 1)
        self.assertAlmostEqual(vx, 1)
        self.assertAlmostEqual(vy, 0)
        self.assertAlmostEqual(speed, 1)
        self.assertAlmostEqual(omega, 10)
        self.assertIsNone(estimator.update(3.0, 8, 0, 90))
        self.assertIsNone(estimator.update(2.0, 9, 0, 100))
        estimator.reset()
        self.assertIsNone(estimator.update(4.0, 0, 0, 1))

    def test_widget_does_not_join_trajectory_across_loss(self):
        widget = TopCameraTrackingWidget()
        reader = FakeReader(scene())
        widget.reader, widget.active = reader, True
        widget.refresh()
        widget.select_marker(100, 100)
        widget.select_marker(60, 100)
        reader.sequence += 1
        widget.refresh()
        self.assertEqual(len(widget.trail), 1)
        reader.frame = scene(missing=True)
        reader.sequence += 1
        widget.refresh()
        self.assertEqual(widget.selecting, 'head')
        self.assertIn('丢失', widget.status.text())
        reader.frame = scene((160, 100), (120, 100))
        reader.sequence += 1
        widget.refresh()
        widget.select_marker(160, 100)
        widget.select_marker(120, 100)
        reader.sequence += 1
        widget.refresh()
        self.assertEqual(len(widget.trail), 2)
        self.assertTrue(widget.trail[-1][2])
        widget.shutdown()
        widget.timer.stop()

    def test_calibrated_coordinates_and_source_mismatch(self):
        intrinsic = {'K': [[200, 0, 160], [0, 200, 120], [0, 0, 1]],
                     'dist': [0, 0, 0, 0, 0], 'image_size_wh': [320, 240]}
        data = {'intrinsics': intrinsic, 'camera_id': 0,
                'extrinsics': {'world_unit': 'm',
                    'H_undistorted_pixel_to_world_xy': [[.01, 0, 0], [0, .01, 0], [0, 0, 1]]}}
        widget = TopCameraTrackingWidget()
        widget.reader, widget.active = FakeReader(scene()), True
        widget.calibration = data
        widget.refresh()
        widget.select_marker(100, 100)
        widget.select_marker(60, 100)
        self.assertEqual(widget._world_pose(320, 240), '米制坐标未启用')
        widget.approve_calibration.setChecked(True)
        self.assertIn('X=0.800, Y=1.000 m', widget._world_pose(320, 240))
        widget.reader.sequence = 2
        widget.refresh()
        widget.reader.sequence = 3
        widget.reader.frame = scene((103, 100), (63, 100))
        widget.refresh()
        widget.reader.sequence = 4
        widget.reader.frame = scene((105, 100), (65, 100))
        widget.refresh()
        self.assertIn('速度 0.250 m/s', widget.status.text())
        self.assertIn('角速度 +0.0 °/s', widget.status.text())
        self.assertIn('不符', widget._world_pose(640, 480))
        widget.reader.source = 1
        self.assertIn('相机编号', widget._world_pose(320, 240))
        widget.shutdown()
        widget.timer.stop()

    def test_plane_calibration_maps_distorted_points(self):
        K = np.array([[900., 0, 1280], [0, 910, 970], [0, 0, 1]])
        dist = np.array([.03, -.02, .001, -.002, .004])
        board = cal.board_points()
        pixels, _ = cv2.projectPoints(board, np.array([.1, -.2, .1]),
                                      np.array([-.05, -.04, 1.5]), K, dist)
        data = {'intrinsics': {'K': K.tolist(), 'dist': dist.tolist(),
                                'image_size_wh': [2592, 1944]}, 'extrinsics': None}
        data['extrinsics'] = cal.fit_plane(pixels, data, (2592, 1944))
        actual = cal.map_points(pixels, data)
        np.testing.assert_allclose(actual, board[:, :2], atol=1e-5)
        with self.assertRaises(ValueError):
            cal.fit_plane(pixels, data, (640, 480))
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'calibration.json')
            cal.save(path, data)
            with open(path, encoding='utf8') as stream:
                loaded = json.load(stream)
            np.testing.assert_allclose(cal.map_points(pixels, loaded), actual)

    def test_calibration_page_freezes_and_saves_confirmed_board(self):
        image = np.full((680, 550, 3), 255, np.uint8)
        for row in range(12):
            for col in range(9):
                if (row + col) % 2 == 0:
                    cv2.rectangle(image, (50+col*50, 40+row*50),
                                  (49+(col+1)*50, 39+(row+1)*50), (0, 0, 0), -1)
        data = {'camera_id': 0, 'intrinsics': {
            'K': [[800, 0, 275], [0, 800, 340], [0, 0, 1]],
            'dist': [0, 0, 0, 0, 0], 'image_size_wh': [550, 680]}, 'extrinsics': None}
        widget = TopCameraTrackingWidget()
        widget.reader, widget.active = FakeReader(image), True
        widget.calibration = data
        widget.mode.setCurrentIndex(1)
        widget.refresh()
        widget.capture_plane()
        deadline = time.monotonic() + 20
        while widget.calibration_busy and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.assertFalse(widget.calibration_busy)
        self.assertTrue(widget.pause.isChecked())
        self.assertIsNotNone(widget.pending_plane, widget.calibration_label.text())
        with tempfile.TemporaryDirectory() as folder:
            saved = os.path.join(folder, 'plane.json')
            def persist(value):
                cal.save(saved, value)
                return saved
            with patch.object(widget, '_persist_calibration', side_effect=persist):
                widget.confirm_plane()
            self.assertTrue(os.path.exists(saved))
            with open(saved, encoding='utf8') as stream:
                cal.validate(json.load(stream), require_plane=True)
        widget.shutdown()
        widget.timer.stop()


if __name__ == '__main__':
    unittest.main()
