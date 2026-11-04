"""Two manually selected dark markers, tracked in image coordinates."""

import math
from collections import deque

import cv2
import numpy as np


def candidates(frame, threshold=75, min_area=20, max_area=5000):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    mask = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY_INV)[1]
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    result = []
    for contour in contours:
        area = cv2.contourArea(contour)
        perimeter = cv2.arcLength(contour, True)
        if not min_area <= area <= max_area or perimeter <= 0:
            continue
        if 4 * math.pi * area / (perimeter * perimeter) < 0.55:
            continue
        moment = cv2.moments(contour)
        if moment['m00']:
            result.append((moment['m10'] / moment['m00'], moment['m01'] / moment['m00'], area))
    return result


def nearest_marker(markers, point, radius):
    choices = sorted((math.dist(m[:2], point), m) for m in markers
                     if math.dist(m[:2], point) <= radius)
    if not choices:
        return None
    # Nearby alternatives are ambiguous: ask for a new selection instead of guessing.
    if len(choices) > 1 and choices[1][0] - choices[0][0] < 5:
        return None
    return choices[0][1]


def follow_pair(markers, head, tail):
    separation = math.dist(head[:2], tail[:2])
    radius = max(12.0, min(60.0, separation * .45))
    new_head = nearest_marker(markers, head[:2], radius)
    new_tail = nearest_marker(markers, tail[:2], radius)
    if new_head is None or new_tail is None or new_head == new_tail:
        return None
    distance = math.dist(new_head[:2], new_tail[:2])
    if not .6 * separation <= distance <= 1.5 * separation:
        return None
    return new_head, new_tail


def pose(head, tail):
    """Midpoint and heading: image x right, y down, clockwise degrees."""
    return ((head[0] + tail[0]) / 2, (head[1] + tail[1]) / 2,
            math.degrees(math.atan2(head[1] - tail[1], head[0] - tail[0])) % 360)


class VelocityEstimator:
    """Average planar velocity over a short time window; unwrap successive headings."""

    def __init__(self, window_s=.5, min_span_s=.2, max_gap_s=1.0):
        self.window_s = window_s
        self.min_span_s = min_span_s
        self.max_gap_s = max_gap_s
        self.samples = deque()

    def reset(self):
        self.samples.clear()

    def update(self, timestamp, x, y, heading_deg):
        if timestamp is None or not all(math.isfinite(v) for v in (timestamp, x, y, heading_deg)):
            self.reset()
            return None
        if self.samples:
            last = self.samples[-1]
            dt = timestamp - last[0]
            if dt <= 0 or dt > self.max_gap_s:
                self.reset()
        if self.samples:
            last = self.samples[-1]
            difference = (heading_deg - last[3] + 180) % 360 - 180
            unwrapped = last[4] + difference
        else:
            unwrapped = heading_deg
        self.samples.append((timestamp, x, y, heading_deg, unwrapped))
        while len(self.samples) > 1 and timestamp - self.samples[0][0] > self.window_s:
            self.samples.popleft()
        first = self.samples[0]
        span = timestamp - first[0]
        if span + 1e-9 < self.min_span_s:
            return None
        vx, vy = (x-first[1])/span, (y-first[2])/span
        return vx, vy, math.hypot(vx, vy), (unwrapped-first[4])/span
