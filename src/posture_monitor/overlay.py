"""Vẽ khung xương, keypoint và hộp phát hiện lên khung hình (spec v2 §10, M1).

Chỉ là lớp hiển thị: nhận :class:`~posture_monitor.pose.PoseResult` (hoặc hộp
phát hiện) và một khung BGR, trả khung đã vẽ. Không suy luận, không đọc cấu
hình ngoài các giá trị được truyền vào.

Hai hàm vẽ, tách riêng vì hai nguồn dữ liệu khác nhau:

- :func:`draw_pose` — khung xương + keypoint, có ngay trong khung đang xử lý.
- :func:`draw_detections` — hộp điện thoại (``PhoneSignal``) và hộp khuôn mặt
  (``PeopleService``). Hai nguồn này cập nhật **thưa hơn** nhịp khung (điện
  thoại mỗi ``detect_every_n_frames`` khung, khuôn mặt mỗi ``face.interval_s``
  giây trên luồng riêng), nên hộp là "kết quả gần nhất còn hạn", không phải
  kết quả của đúng khung này.

Ngưỡng ``kp_conf_min`` (mặc định 0.5, lấy từ ``config.model.kp_conf_min``)
quyết định keypoint nào được vẽ: keypoint dưới ngưỡng **không** được vẽ, và
xương nào có đầu mút dưới ngưỡng cũng không được vẽ. Nhờ vậy overlay không
"đoán" vị trí khớp mà model không chắc (spec §5.3: thiếu thì bỏ, không đoán).

Thứ tự khớp và bộ xương theo chuẩn COCO-17 mà YOLO pose dùng.
"""

from __future__ import annotations

from typing import Iterable, Sequence

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

#: Màu BGR của hộp phát hiện: điện thoại cam, khuôn mặt vàng.
#:
#: Cố ý **khác** :data:`POINT_COLOR` (đỏ): keypoint cũng là chấm đỏ, nên hộp
#: điện thoại màu đỏ sẽ chìm vào khung xương và không còn phân biệt được bằng
#: mắt — lẫn cả trong ảnh chụp màn hình gửi đi báo lỗi. Cam đủ tách khỏi xanh
#: lá (xương), đỏ (khớp) và vàng (mặt).
PHONE_BOX_COLOR = (0, 165, 255)
FACE_BOX_COLOR = (0, 255, 255)

#: Độ dày nét vẽ, tính bằng pixel.
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


def draw_detections(
    frame: np.ndarray,
    *,
    phone_boxes: Iterable[Sequence[float]] = (),
    face_box: tuple[float, float, float, float] | None = None,
    copy: bool = False,
) -> np.ndarray:
    """Vẽ hộp điện thoại và hộp khuôn mặt gần nhất lên ``frame``.

    Hai loại hộp đến từ hai nguồn **cập nhật thưa**, không phải từ khung này:

    - ``phone_boxes``: hộp ``(x1, y1, x2, y2)`` mà ``PhoneSignal`` vừa detect
      và còn trong hạn ``phone.box_ttl_s``. Điện thoại chỉ detect mỗi
      ``phone.detect_every_n_frames`` khung nên phần lớn khung dùng lại hộp cũ
      — đúng như lớp lọc thời gian phía dưới vẫn đang làm.
    - ``face_box``: hộp ``(x, y, w, h)`` của lần nhận diện khuôn mặt gần nhất
      **trong hệ pixel của khung gốc** (``PeopleService.latest_face_box``).
      Nhận diện chạy trên luồng riêng mỗi ``face.interval_s`` giây, nên hộp
      này có thể lệch vài phần trăm giây so với khung đang hiển thị. Nó **không
      phải** kết quả nhận diện tức thời — chỉ để người dùng thấy mô hình đang
      nhắm vào đâu.

    Hộp có toạ độ không hữu hạn hoặc rỗng sau khi kẹp bị bỏ qua, không vẽ bừa.

    Args:
        frame: ảnh BGR ``uint8``.
        phone_boxes: các hộp điện thoại, mỗi hộp ``(x1, y1, x2, y2)`` pixel.
        face_box: hộp khuôn mặt ``(x, y, w, h)`` pixel, hoặc ``None``.
        copy: ``True`` thì vẽ lên bản sao; ``False`` (mặc định) vẽ trực tiếp,
            vì hàm này luôn được gọi trên khung đã qua :func:`draw_pose`.

    Returns:
        Khung BGR đã vẽ (chính ``frame`` khi ``copy=False``).
    """
    canvas = frame.copy() if copy else frame
    height, width = canvas.shape[:2]

    for box in phone_boxes or ():
        rect = _box_to_rect(box, width, height)
        if rect is None:
            continue
        cv2.rectangle(
            canvas, rect[0], rect[1], PHONE_BOX_COLOR, BOX_THICKNESS,
            cv2.LINE_AA,
        )

    if face_box is not None:
        rect = _xywh_to_rect(face_box, width, height)
        if rect is not None:
            cv2.rectangle(
                canvas, rect[0], rect[1], FACE_BOX_COLOR, BOX_THICKNESS,
                cv2.LINE_AA,
            )

    return canvas


def _box_to_rect(
    box: Sequence[float], width: int, height: int
) -> tuple[tuple[int, int], tuple[int, int]] | None:
    """``(x1, y1, x2, y2)`` → hai góc pixel; ``None`` nếu hộp vô nghĩa."""
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
    """``(x, y, w, h)`` → hai góc pixel; ``None`` nếu hộp vô nghĩa."""
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
    """Kẹp hộp vào khung và loại hộp suy biến.

    Hộp có toạ độ không hữu hạn (NaN/inf) hoặc có cạnh dài dưới 1 px bị bỏ:
    ``cv2.rectangle`` với hai góc trùng nhau không vẽ gì, còn toạ độ NaN thì
    OpenCV có thể vẽ nét rác khắp khung.
    """
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
