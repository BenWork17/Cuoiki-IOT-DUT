"""Vẽ khung xương và keypoint lên khung hình (spec v2 §10, mốc M1).

Chỉ là lớp hiển thị: nhận :class:`~posture_monitor.pose.PoseResult` và một
khung BGR, trả khung đã vẽ. Không suy luận, không đọc cấu hình ngoài hai giá
trị được truyền vào.

Ngưỡng ``kp_conf_min`` (mặc định 0.5, lấy từ ``config.model.kp_conf_min``)
quyết định keypoint nào được vẽ: keypoint dưới ngưỡng **không** được vẽ, và
xương nào có đầu mút dưới ngưỡng cũng không được vẽ. Nhờ vậy overlay không
"đoán" vị trí khớp mà model không chắc (spec §5.3: thiếu thì bỏ, không đoán).

Thứ tự khớp và bộ xương theo chuẩn COCO-17 mà YOLO pose dùng.
"""

from __future__ import annotations

import cv2
import numpy as np

#: Tên 17 keypoint COCO, theo đúng thứ tự model trả về.
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

#: Các cặp keypoint nối thành xương, theo chỉ số COCO.
SKELETON_EDGES = (
    (0, 1),  # mũi - mắt trái
    (0, 2),  # mũi - mắt phải
    (1, 3),  # mắt trái - tai trái
    (2, 4),  # mắt phải - tai phải
    (5, 7),  # vai trái - khuỷu trái
    (7, 9),  # khuỷu trái - cổ tay trái
    (6, 8),  # vai phải - khuỷu phải
    (8, 10),  # khuỷu phải - cổ tay phải
    (5, 6),  # vai trái - vai phải
    (5, 11),  # vai trái - hông trái
    (6, 12),  # vai phải - hông phải
    (11, 12),  # hông trái - hông phải
    (11, 13),  # hông trái - gối trái
    (13, 15),  # gối trái - cổ chân trái
    (12, 14),  # hông phải - gối phải
    (14, 16),  # gối phải - cổ chân phải
)

#: Màu BGR của xương và keypoint.
EDGE_COLOR = (0, 255, 0)
POINT_COLOR = (0, 0, 255)

#: Độ dày nét vẽ, tính bằng pixel.
EDGE_THICKNESS = 2
POINT_RADIUS = 3


def draw_pose(
    frame: np.ndarray,
    xy: np.ndarray | None,
    conf: np.ndarray | None,
    kp_conf_min: float = 0.5,
    *,
    copy: bool = True,
) -> np.ndarray:
    """Vẽ xương và keypoint lên ``frame``.

    Args:
        frame: ảnh BGR ``uint8``.
        xy: toạ độ ``(17, 2)`` pixel, hoặc ``None`` nếu không có người.
        conf: độ tin cậy ``(17,)``, hoặc ``None``.
        kp_conf_min: keypoint có ``conf < kp_conf_min`` sẽ không được vẽ.
        copy: ``True`` thì vẽ lên bản sao, giữ nguyên ``frame`` gốc; ``False``
            thì vẽ trực tiếp lên ``frame`` (nhanh hơn cho vòng lặp webcam).

    Returns:
        Khung BGR đã vẽ. Không có người (``xy is None``) thì trả khung y nguyên
        (bản sao nếu ``copy=True``).
    """
    canvas = frame.copy() if copy else frame
    if xy is None:
        return canvas

    points = np.asarray(xy, dtype=np.float32).reshape(-1, 2)
    if conf is None:
        scores = np.ones(len(points), dtype=np.float32)
    else:
        scores = np.asarray(conf, dtype=np.float32).reshape(-1)
    if len(scores) != len(points):  # pragma: no cover - hợp đồng bị vi phạm
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
        cv2.circle(
            canvas, pixel, POINT_RADIUS, POINT_COLOR, -1, cv2.LINE_AA
        )

    return canvas


def _to_pixel(
    point: np.ndarray, width: int, height: int
) -> tuple[int, int] | None:
    """Chuyển toạ độ float sang pixel nguyên, bỏ điểm không hợp lệ.

    Điểm có toạ độ không hữu hạn (NaN/inf) — backend có thể trả khi không phát
    hiện khớp — bị loại thay vì vẽ bừa.
    """
    x, y = float(point[0]), float(point[1])
    if not (np.isfinite(x) and np.isfinite(y)):
        return None
    # Kẹp vào khung để OpenCV không cắt mất nét vẽ ở sát biên.
    x_int = int(round(min(max(x, 0.0), width - 1)))
    y_int = int(round(min(max(y, 0.0), height - 1)))
    return x_int, y_int
