"""Vẽ khung xương, keypoint và hộp phát hiện (điện thoại / khuôn mặt) lên khung hình."""

from __future__ import annotations

from typing import Iterable, Sequence

import cv2
import numpy as np

KEYPOINT_NAMES = (
    "nose",
    "left_eye",
    "right_eye",
    "left_ear",
    "right_ear",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
)

SKELETON_EDGES = (
    (0, 1),
    (0, 2),
    (1, 3),
    (2, 4),
    (5, 7),
    (7, 9),
    (6, 8),
    (8, 10),
    (5, 6),
    (5, 11),
    (6, 12),
    (11, 12),
    (11, 13),
    (13, 15),
    (12, 14),
    (14, 16),
)

EDGE_COLOR = (0, 255, 0)
POINT_COLOR = (0, 0, 255)
PHONE_BOX_COLOR = (0, 165, 255)
FACE_BOX_COLOR = (0, 255, 255)

EDGE_THICKNESS = 2
POINT_RADIUS = 3
BOX_THICKNESS = 2


def draw_pose(
    frame: np.ndarray,
    xy: np.ndarray | None,
    conf: np.ndarray | None,
    kp_conf_min: float = 0.5,
    *,
    copy: bool = True,
) -> np.ndarray:
    """Vẽ xương và keypoint lên ``frame``."""
    canvas = frame.copy() if copy else frame
    if xy is None:
        return canvas

    points = np.asarray(xy, dtype=np.float32).reshape(-1, 2)
    scores = (
        np.ones(len(points), dtype=np.float32)
        if conf is None
        else np.asarray(conf, dtype=np.float32).reshape(-1)
    )
    if len(scores) != len(points):  # pragma: no cover
        raise ValueError(
            f"xy có {len(points)} điểm nhưng conf có {len(scores)} giá trị."
        )

    visible = scores >= float(kp_conf_min)
    height, width = canvas.shape[:2]

    for start, end in SKELETON_EDGES:
        if start >= len(points) or end >= len(points):  # pragma: no cover
            continue
        if not (visible[start] and visible[end]):
            continue
        p1 = _to_pixel(points[start], width, height)
        p2 = _to_pixel(points[end], width, height)
        if p1 is None or p2 is None:
            continue
        cv2.line(canvas, p1, p2, EDGE_COLOR, EDGE_THICKNESS, cv2.LINE_AA)

    for index, point in enumerate(points):
        if not visible[index]:
            continue
        pixel = _to_pixel(point, width, height)
        if pixel is None:
            continue
        cv2.circle(canvas, pixel, POINT_RADIUS, POINT_COLOR, -1, cv2.LINE_AA)

    return canvas


def draw_detections(
    frame: np.ndarray,
    *,
    phone_boxes: Iterable[Sequence[float]] = (),
    face_box: tuple[float, float, float, float] | None = None,
    copy: bool = False,
) -> np.ndarray:
    """Vẽ hộp điện thoại và hộp khuôn mặt gần nhất lên ``frame``."""
    canvas = frame.copy() if copy else frame
    height, width = canvas.shape[:2]

    for box in phone_boxes or ():
        rect = _box_to_rect(box, width, height)
        if rect is not None:
            cv2.rectangle(
                canvas, rect[0], rect[1], PHONE_BOX_COLOR, BOX_THICKNESS, cv2.LINE_AA
            )

    if face_box is not None:
        rect = _xywh_to_rect(face_box, width, height)
        if rect is not None:
            cv2.rectangle(
                canvas, rect[0], rect[1], FACE_BOX_COLOR, BOX_THICKNESS, cv2.LINE_AA
            )

    return canvas


def _box_to_rect(
    box: Sequence[float], width: int, height: int
) -> tuple[tuple[int, int], tuple[int, int]] | None:
    if box is None or len(box) != 4:
        return None
    try:
        x1, y1, x2, y2 = (float(value) for value in box)
    except (TypeError, ValueError):
        return None
    return _clamped_rect(x1, y1, x2, y2, width, height)


def _xywh_to_rect(
    box: Sequence[float], width: int, height: int
) -> tuple[tuple[int, int], tuple[int, int]] | None:
    if box is None or len(box) != 4:
        return None
    try:
        x, y, w, h = (float(value) for value in box)
    except (TypeError, ValueError):
        return None
    return _clamped_rect(x, y, x + w, y + h, width, height)


def _clamped_rect(
    x1: float, y1: float, x2: float, y2: float, width: int, height: int
) -> tuple[tuple[int, int], tuple[int, int]] | None:
    values = (x1, y1, x2, y2)
    if not all(np.isfinite(value) for value in values):
        return None
    x1, x2 = sorted((x1, x2))
    y1, y2 = sorted((y1, y2))
    left = int(round(min(max(x1, 0.0), width - 1)))
    top = int(round(min(max(y1, 0.0), height - 1)))
    right = int(round(min(max(x2, 0.0), width - 1)))
    bottom = int(round(min(max(y2, 0.0), height - 1)))
    if right <= left or bottom <= top:
        return None
    return (left, top), (right, bottom)


def _to_pixel(
    point: np.ndarray, width: int, height: int
) -> tuple[int, int] | None:
    x, y = float(point[0]), float(point[1])
    if not (np.isfinite(x) and np.isfinite(y)):
        return None
    x_int = int(round(min(max(x, 0.0), width - 1)))
    y_int = int(round(min(max(y, 0.0), height - 1)))
    return x_int, y_int
