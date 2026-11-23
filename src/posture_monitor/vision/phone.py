"""Phép đo hình học thuần giữa cổ tay và hộp điện thoại (lớp COCO 67)."""

from __future__ import annotations

import math
from typing import NamedTuple, Sequence

import numpy as np

PHONE_CLASS_ID = 67
WRIST_KEYPOINTS: tuple[int, ...] = (9, 10)
SHOULDER_KEYPOINTS: tuple[int, int] = (5, 6)
NOSE_KEYPOINT = 0


class HandPhoneResult(NamedTuple):
    """Kết quả một lần xét bàn tay ↔ điện thoại, kèm chi tiết debug."""

    co_cham: bool
    khoang_cach_nho_nhat: float | None
    khoang_cach_theo_tay: tuple[tuple[int, float], ...] = ()
    hop_gan_nhat: int | None = None
    hop_le: bool = True
    ly_do: str | None = None


def _khong_cham(ly_do: str | None = None) -> HandPhoneResult:
    return HandPhoneResult(
        co_cham=False,
        khoang_cach_nho_nhat=None,
        ly_do=ly_do,
        hop_le=ly_do is None,
    )


def _doc_keypoints(keypoints: object) -> np.ndarray | None:
    """Ép ``keypoints`` về mảng ``float`` shape ``(N, >=3)``; ``None`` nếu sai dạng."""
    try:
        arr = np.asarray(keypoints, dtype=float)
    except (TypeError, ValueError):
        return None
    if arr.ndim != 2 or arr.shape[1] < 3:
        return None
    if arr.shape[0] <= max(WRIST_KEYPOINTS):
        return None
    return arr


def usable_wrist_keypoints(keypoints: object, min_kp_conf: float) -> np.ndarray | None:
    """Trả mảng keypoint nếu đúng hình dạng và có ít nhất một cổ tay đạt ``min_kp_conf``."""
    arr = _doc_keypoints(keypoints)
    if arr is None:
        return None
    for index in WRIST_KEYPOINTS:
        confidence = float(arr[index, 2])
        if math.isfinite(confidence) and confidence >= min_kp_conf:
            return arr
    return None


def _doc_hop(hop: Sequence[float]) -> tuple[float, float, float, float] | None:
    try:
        x1, y1, x2, y2 = (float(v) for v in hop)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(v) for v in (x1, y1, x2, y2)):
        return None
    if x1 > x2:
        x1, x2 = x2, x1
    if y1 > y2:
        y1, y2 = y2, y1
    return x1, y1, x2, y2


def khoang_cach_diem_hop(
    px: float, py: float, hop: tuple[float, float, float, float]
) -> float:
    """Khoảng cách Euclid từ điểm ``(px, py)`` đến hình chữ nhật; nằm trong hộp → ``0.0``."""
    x1, y1, x2, y2 = hop
    dx = max(x1 - px, 0.0, px - x2)
    dy = max(y1 - py, 0.0, py - y2)
    return math.hypot(dx, dy)


def hand_phone_contact(
    keypoints: object,
    phone_boxes: object,
    *,
    proximity_px: float,
    min_kp_conf: float,
) -> HandPhoneResult:
    """Xét cổ tay có chạm hoặc nằm trong ngưỡng ``proximity_px`` quanh hộp điện thoại không."""
    if not math.isfinite(proximity_px) or proximity_px < 0:
        raise ValueError("proximity_px phải là số hữu hạn không âm")
    if not math.isfinite(min_kp_conf) or not 0.0 <= min_kp_conf <= 1.0:
        raise ValueError("min_kp_conf phải nằm trong [0, 1]")

    arr = _doc_keypoints(keypoints)
    if arr is None:
        return _khong_cham("keypoints sai hình dạng")

    if phone_boxes is None:
        return _khong_cham("không có hộp điện thoại")
    try:
        danh_sach_hop = list(phone_boxes)
    except TypeError:
        return _khong_cham("phone_boxes không phải dãy")

    hop_hop_le: list[tuple[int, tuple[float, float, float, float]]] = []
    for i, hop in enumerate(danh_sach_hop):
        da_chuan = _doc_hop(hop)
        if da_chuan is not None:
            hop_hop_le.append((i, da_chuan))
    if not hop_hop_le:
        return _khong_cham("không có hộp điện thoại hợp lệ")

    khoang_cach_theo_tay: list[tuple[int, float]] = []
    gan_nhat: float | None = None
    hop_gan_nhat: int | None = None
    for idx in WRIST_KEYPOINTS:
        x, y, conf = (float(v) for v in arr[idx, :3])
        if not math.isfinite(conf) or conf < min_kp_conf:
            continue
        if not (math.isfinite(x) and math.isfinite(y)):
            continue
        gan_nhat_cua_tay = math.inf
        for vi_tri_goc, hop in hop_hop_le:
            d = khoang_cach_diem_hop(x, y, hop)
            if d < gan_nhat_cua_tay:
                gan_nhat_cua_tay = d
            if gan_nhat is None or d < gan_nhat:
                gan_nhat = d
                hop_gan_nhat = vi_tri_goc
        khoang_cach_theo_tay.append((idx, gan_nhat_cua_tay))

    if gan_nhat is None:
        return HandPhoneResult(
            co_cham=False,
            khoang_cach_nho_nhat=None,
            ly_do="không có cổ tay đủ tin cậy",
        )

    return HandPhoneResult(
        co_cham=gan_nhat <= proximity_px,
        khoang_cach_nho_nhat=gan_nhat,
        khoang_cach_theo_tay=tuple(khoang_cach_theo_tay),
        hop_gan_nhat=hop_gan_nhat,
    )


def shoulder_width_px(keypoints: object, *, min_kp_conf: float) -> float | None:
    """Bề rộng vai (pixel) làm thước tỉ lệ cho ngưỡng chạm; ``None`` nếu thiếu vai."""
    if not math.isfinite(min_kp_conf) or not 0.0 <= min_kp_conf <= 1.0:
        raise ValueError("min_kp_conf phải nằm trong [0, 1]")

    arr = _doc_keypoints(keypoints)
    if arr is None:
        return None

    points: list[tuple[float, float]] = []
    for index in SHOULDER_KEYPOINTS:
        x, y, conf = (float(v) for v in arr[index, :3])
        if not math.isfinite(conf) or conf < min_kp_conf:
            return None
        if not (math.isfinite(x) and math.isfinite(y)):
            return None
        points.append((x, y))

    (x1, y1), (x2, y2) = points
    width = math.hypot(x2 - x1, y2 - y1)
    if not math.isfinite(width) or width <= 0.0:
        return None
    return width


def is_head_like_box(
    box: tuple[float, float, float, float],
    keypoints: object,
    *,
    min_kp_conf: float,
    span_ratio: float = 1.0,
    oversize_ratio: float = 2.25,
) -> bool:
    """Kiểm tra hộp lớp 67 có phải hộp giả phủ vùng đầu (gọng kính) không."""
    if not math.isfinite(min_kp_conf) or not 0.0 <= min_kp_conf <= 1.0:
        raise ValueError("min_kp_conf phải nằm trong [0, 1]")
    if not math.isfinite(span_ratio) or span_ratio < 0.0:
        raise ValueError("span_ratio phải là số hữu hạn không âm")
    if not math.isfinite(oversize_ratio) or oversize_ratio < 0.0:
        raise ValueError("oversize_ratio phải là số hữu hạn không âm")

    hop = _doc_hop(box)
    if hop is None:
        return False
    arr = _doc_keypoints(keypoints)
    if arr is None:
        return False

    x1, y1, x2, y2 = hop
    nose = arr[NOSE_KEYPOINT, :3]
    if not all(math.isfinite(float(v)) for v in nose) or float(nose[2]) < min_kp_conf:
        return False
    nose_x, nose_y = float(nose[0]), float(nose[1])

    shoulder_ys: list[float] = []
    for index in SHOULDER_KEYPOINTS:
        x, y, conf = (float(v) for v in arr[index, :3])
        if not math.isfinite(conf) or conf < min_kp_conf:
            return False
        if not (math.isfinite(x) and math.isfinite(y)):
            return False
        shoulder_ys.append(y)
    shoulder_y = sum(shoulder_ys) / len(shoulder_ys)

    span = shoulder_y - nose_y
    if not math.isfinite(span) or span <= 0.0:
        return False
    box_h = y2 - y1
    covers_nose = y1 <= nose_y <= y2 and x1 <= nose_x <= x2
    if not (covers_nose and box_h >= span_ratio * span):
        return False
    if oversize_ratio > 0.0:
        width = shoulder_width_px(arr, min_kp_conf=min_kp_conf)
        if width is not None and max(x2 - x1, box_h) > oversize_ratio * width:
            return False
    return True


def is_plausible_phone_box(
    box: tuple[float, float, float, float],
    keypoints: object,
    *,
    min_kp_conf: float,
    min_size_ratio: float = 0.45,
    max_above_shoulder_px: float = 10.0,
    oversize_ratio: float = 2.25,
) -> bool:
    """Kiểm tra hộp lớp 67 có nằm ở vị trí/tỉ lệ hợp lý của điện thoại đang cầm không."""
    if not math.isfinite(min_kp_conf) or not 0.0 <= min_kp_conf <= 1.0:
        raise ValueError("min_kp_conf phải nằm trong [0, 1]")
    if not math.isfinite(min_size_ratio) or min_size_ratio < 0.0:
        raise ValueError("min_size_ratio phải là số hữu hạn không âm")
    if not math.isfinite(max_above_shoulder_px) or max_above_shoulder_px < 0.0:
        raise ValueError("max_above_shoulder_px phải là số hữu hạn không âm")
    if not math.isfinite(oversize_ratio) or oversize_ratio < 0.0:
        raise ValueError("oversize_ratio phải là số hữu hạn không âm")

    hop = _doc_hop(box)
    if hop is None:
        return True
    arr = _doc_keypoints(keypoints)
    if arr is None:
        return True

    width = shoulder_width_px(arr, min_kp_conf=min_kp_conf)
    if width is None:
        return True

    shoulder_y = sum(float(arr[index, 1]) for index in SHOULDER_KEYPOINTS) / len(
        SHOULDER_KEYPOINTS
    )
    x1, y1, x2, y2 = hop
    longest_side = max(x2 - x1, y2 - y1)
    if oversize_ratio > 0.0 and longest_side > oversize_ratio * width:
        return True
    center_y = (y1 + y2) / 2.0
    if center_y < shoulder_y - max_above_shoulder_px:
        return False
    return longest_side >= min_size_ratio * width
