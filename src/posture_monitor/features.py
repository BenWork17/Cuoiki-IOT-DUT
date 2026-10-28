"""Tính đặc trưng hình học từ 17 keypoint COCO (spec v2 §5.3).

Đầu vào là mảng numpy thô, **không** phụ thuộc ``pose.py``: nhờ vậy module
này (và unit test của nó) chạy được trên PC mà không cần model hay camera.

Quy tắc bất biến:

- Chỉ dùng keypoint có ``conf >= kp_conf_min``. Keypoint thiếu (conf thấp,
  tọa độ không hữu hạn, hoặc ``xy is None``) thì đặc trưng liên quan là
  ``None`` — **không nội suy, không đoán** (spec v2 §5.3, §11.4).
- ``shoulder_tilt_deg`` và ``head_tilt_deg`` được chuẩn hóa về ``(-90, 90]``
  trước khi trả ra (spec v2 §5.3). Công thức thô ``atan2(dy, dx)`` cho gần
  ±180° khi hai keypoint trái/phải đảo chỗ trong ảnh do góc nhìn camera;
  giữ nguyên số thô sẽ khiến luật cảnh báo bắn liên tục.
- Không có đặc trưng nào được suy ra từ baseline ở đây ngoài ``closeness`` và
  ``lean_x``; hai đặc trưng đó là ``None`` khi chưa có baseline.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Protocol

import numpy as np

#: Số keypoint của định dạng COCO.
NUM_KEYPOINTS = 17

# Chỉ số keypoint COCO (spec v2 §5.3).
NOSE = 0
LEFT_EYE = 1
RIGHT_EYE = 2
LEFT_EAR = 3
RIGHT_EAR = 4
LEFT_SHOULDER = 5
RIGHT_SHOULDER = 6
LEFT_HIP = 11
RIGHT_HIP = 12
LEFT_KNEE = 13
RIGHT_KNEE = 14

#: Góc camera được hỗ trợ (spec v2 §2, §6).
VIEWS = ("front", "side")

DEFAULT_KP_CONF_MIN = 0.5

#: Miền giá trị hợp lệ của góc nghiêng sau chuẩn hóa: ``(-90, 90]``.
ANGLE_MIN_EXCLUSIVE = -90.0
ANGLE_MAX_INCLUSIVE = 90.0

#: Tên đặc trưng theo bảng §5.3.
FEATURE_NAMES = (
    "shoulder_width",
    "shoulder_tilt_deg",
    "head_tilt_deg",
    "head_height",
    "closeness",
    "lean_x",
    "head_yaw",
    "neck_angle",
    "torso_angle",
)

#: Đại lượng hình học phụ, không phải đặc trưng nghiệp vụ, nhưng baseline cần
#: lưu để ``lean_x`` tính được ở các khung sau (spec §5.3 dùng ``baseline.x``).
AUXILIARY_NAMES = ("shoulder_mid_x",)

ALL_NAMES = FEATURE_NAMES + AUXILIARY_NAMES

_EPS = 1e-9


class BaselineLike(Protocol):
    """Phần baseline mà bộ trích đặc trưng cần đọc.

    Định nghĩa dạng Protocol để :mod:`posture_monitor.features` không phải
    import :mod:`posture_monitor.calibration` (tránh vòng import).
    """

    #: Trung vị chiều rộng vai lúc hiệu chỉnh (pixel).
    shoulder_width: float
    #: Trung vị x trung điểm vai lúc hiệu chỉnh (pixel).
    shoulder_mid_x: float


@dataclass(frozen=True)
class Features:
    """Tập đặc trưng của một khung hình.

    ``person=False`` nghĩa là không thấy người (hoặc ``xy is None``). Mọi
    đặc trưng không tính được đều là ``None``.
    """

    view: str
    person: bool
    values: Mapping[str, float | None]

    def get(self, name: str) -> float | None:
        """Trả giá trị đặc trưng, ``None`` nếu thiếu."""
        return self.values.get(name)

    def __getitem__(self, name: str) -> float | None:
        return self.values[name]

    @property
    def has_shoulders(self) -> bool:
        """Có đủ hai vai để đánh giá tư thế hay không (spec §5.5, ABSENT)."""
        return self.get("shoulder_width") is not None


def normalize_angle(angle_deg: float) -> float:
    """Chuẩn hóa góc nghiêng về ``(-90, 90]`` (spec v2 §5.3).

    Quy tắc spec: góc > 90 thì trừ 180, góc < -90 thì cộng 180. Ở đây dùng
    ``<= -90`` cho trường hợp biên -90 để miền kết quả đúng là nửa khoảng
    ``(-90, 90]``; -90 và +90 mô tả cùng một đường thẳng đứng nên không mất
    thông tin.

    Ví dụ đã đo trong spec: ``-179.69`` → ``0.31``; ``179.69`` → ``-0.31``.
    """
    angle = float(angle_deg)
    if not math.isfinite(angle):
        raise ValueError(f"Góc phải là số hữu hạn, nhận được {angle_deg!r}.")

    # Đưa về [-180, 180) trước để đầu vào lệch vòng (vd 540°) vẫn nhất quán.
    angle = (angle + 180.0) % 360.0 - 180.0
    if angle <= -90.0:
        angle += 180.0
    elif angle > 90.0:
        angle -= 180.0
    return angle


def angle_at(
    a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]
) -> float | None:
    """Góc tại ``b`` của tam giác ``a-b-c``, đơn vị độ, trong ``[0, 180]``.

    Trả ``None`` khi hai vector suy biến (độ dài ~0) vì góc không xác định.
    """
    ux, uy = a[0] - b[0], a[1] - b[1]
    vx, vy = c[0] - b[0], c[1] - b[1]
    nu = math.hypot(ux, uy)
    nv = math.hypot(vx, vy)
    if nu <= _EPS or nv <= _EPS:
        return None
    cos_value = (ux * vx + uy * vy) / (nu * nv)
    cos_value = max(-1.0, min(1.0, cos_value))
    return math.degrees(math.acos(cos_value))


def _angle_deg(dx: float, dy: float) -> float:
    return math.degrees(math.atan2(dy, dx))


def extract(
    xy: np.ndarray | None,
    conf: np.ndarray | None,
    *,
    view: str = "front",
    kp_conf_min: float = DEFAULT_KP_CONF_MIN,
    baseline: BaselineLike | None = None,
) -> Features:
    """Trích đặc trưng từ output của ``pose.detect`` (spec v2 §5.2, §5.3).

    Args:
        xy: mảng ``(17, 2)`` tọa độ pixel, hoặc ``None`` nếu không thấy người.
        conf: mảng ``(17,)`` độ tin cậy keypoint (đi kèm ``xy``).
        view: ``"front"`` hoặc ``"side"``.
        kp_conf_min: ngưỡng tin cậy tối thiểu; keypoint có ``conf`` đúng bằng
            ngưỡng vẫn được dùng (spec: ``conf >= kp_conf_min``).
        baseline: baseline hiệu chỉnh, chỉ cần cho ``closeness`` và ``lean_x``.

    Returns:
        :class:`Features` với mọi tên trong :data:`ALL_NAMES`; đặc trưng
        không tính được là ``None``.

    Raises:
        ValueError: khi ``view`` không hợp lệ hoặc mảng sai shape.
    """
    if view not in VIEWS:
        raise ValueError(
            f"view phải là một trong {VIEWS}, nhận được {view!r}."
        )

    values: dict[str, float | None] = {name: None for name in ALL_NAMES}

    if xy is None:
        return Features(view=view, person=False, values=values)

    xy_array = np.asarray(xy, dtype=float)
    if xy_array.shape != (NUM_KEYPOINTS, 2):
        raise ValueError(
            f"xy phải có shape ({NUM_KEYPOINTS}, 2), nhận được "
            f"{xy_array.shape}."
        )

    if conf is None:
        raise ValueError("conf là bắt buộc khi xy khác None (spec §5.2).")
    conf_array = np.asarray(conf, dtype=float)
    if conf_array.shape != (NUM_KEYPOINTS,):
        raise ValueError(
            f"conf phải có shape ({NUM_KEYPOINTS},), nhận được "
            f"{conf_array.shape}."
        )

    finite = np.isfinite(xy_array).all(axis=1) & np.isfinite(conf_array)
    usable = finite & (conf_array >= kp_conf_min)

    def point(index: int) -> tuple[float, float] | None:
        if not usable[index]:
            return None
        return float(xy_array[index, 0]), float(xy_array[index, 1])

    nose = point(NOSE)

    # ---- Vai: thước chuẩn hóa, nghiêng vai, chiều cao đầu, vị trí ngang ----
    left_shoulder = point(LEFT_SHOULDER)
    right_shoulder = point(RIGHT_SHOULDER)
    if left_shoulder is not None and right_shoulder is not None:
        mid_x = (left_shoulder[0] + right_shoulder[0]) / 2.0
        mid_y = (left_shoulder[1] + right_shoulder[1]) / 2.0
        values["shoulder_mid_x"] = mid_x

        dx = right_shoulder[0] - left_shoulder[0]
        dy = right_shoulder[1] - left_shoulder[1]
        width = math.hypot(dx, dy)

        if width > _EPS:
            values["shoulder_width"] = width
            values["shoulder_tilt_deg"] = normalize_angle(_angle_deg(dx, dy))

            if nose is not None:
                values["head_height"] = (mid_y - nose[1]) / width

            if baseline is not None:
                base_width = float(baseline.shoulder_width)
                if base_width > _EPS:
                    values["closeness"] = width / base_width
                    values["lean_x"] = (
                        mid_x - float(baseline.shoulder_mid_x)
                    ) / width

    # ---- Tai: nghiêng đầu, quay đầu ---------------------------------------
    left_ear = point(LEFT_EAR)
    right_ear = point(RIGHT_EAR)
    if left_ear is not None and right_ear is not None:
        ear_dx = right_ear[0] - left_ear[0]
        ear_dy = right_ear[1] - left_ear[1]
        ear_distance = math.hypot(ear_dx, ear_dy)
        if ear_distance > _EPS:
            values["head_tilt_deg"] = normalize_angle(
                _angle_deg(ear_dx, ear_dy)
            )
            if nose is not None:
                ear_mid_x = (left_ear[0] + right_ear[0]) / 2.0
                values["head_yaw"] = (nose[0] - ear_mid_x) / ear_distance

    # ---- Chế độ side: góc cổ và góc thân, chọn bên thấy rõ hơn -------------
    if view == "side":
        best: tuple[float, float, float | None] | None = None
        for side in ((LEFT_EAR, LEFT_SHOULDER, LEFT_HIP, LEFT_KNEE),
                     (RIGHT_EAR, RIGHT_SHOULDER, RIGHT_HIP, RIGHT_KNEE)):
            ear_index, shoulder_index, hip_index, knee_index = side
            ear = point(ear_index)
            shoulder = point(shoulder_index)
            hip = point(hip_index)
            if ear is None or shoulder is None or hip is None:
                continue
            neck_angle = angle_at(ear, shoulder, hip)
            if neck_angle is None:
                continue
            confidence_sum = float(
                conf_array[ear_index]
                + conf_array[shoulder_index]
                + conf_array[hip_index]
            )
            knee = point(knee_index)
            torso_angle = (
                angle_at(shoulder, hip, knee) if knee is not None else None
            )
            if best is None or confidence_sum > best[0]:
                best = (confidence_sum, neck_angle, torso_angle)
        if best is not None:
            values["neck_angle"] = best[1]
            values["torso_angle"] = best[2]

    return Features(view=view, person=True, values=values)
