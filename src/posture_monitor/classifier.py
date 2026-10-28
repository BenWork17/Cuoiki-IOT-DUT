"""Phân loại tư thế theo luật hình học (spec v2 §5.5).

Mỗi khung sinh ra một tập nhãn (có thể nhiều nhãn cùng lúc) và một điểm tư
thế 0–100. Toàn bộ **ngưỡng quyết định** đọc từ ``config.thresholds``; module
này không tự đặt ngưỡng nào (spec §1, §11.2). Các hằng số còn lại chỉ là
trọng số của công thức tính điểm, ghi rõ ngay dưới đây.

Điểm tư thế — công thức::

    score = clamp(100 - sum(penalty_i), 0, 100)

    penalty_i = min(PENALTY_MAX, PENALTY_BASE + PENALTY_WEIGHT * excess_i)

``excess_i`` là mức vượt ngưỡng đã chuẩn hóa: bằng 0 đúng tại ngưỡng, bằng 1
khi vượt một khoảng đúng bằng ngưỡng (ví dụ nghiêng vai 16° với ngưỡng 8°),
và lớn hơn khi vượt xa hơn. Nhờ vậy mọi nhãn dùng chung một thang đo dù đơn
vị khác nhau (độ, tỉ lệ, pixel).

Không thấy người, hoặc thiếu hai vai, thì nhãn là ``ABSENT``. Khi đó
``score`` trả 0 vì không có gì để chấm, **không** phải "tư thế tệ nhất":
tầng thống kê phải loại khung ABSENT khỏi ``avg_score`` (spec §5.9 đã có
cột ``absent_s`` riêng), nếu không điểm trung bình sẽ bị kéo xuống một cách
vô nghĩa mỗi lần người dùng đứng dậy.

Đặc trưng thiếu → nhãn tương ứng **không được đánh giá** (không có mặt trong
tập nhãn xấu), tuyệt đối không đoán (spec §5.3, §11.4). Điều này quan trọng
với ``HEAD_TILT``/``LOOK_AWAY`` vì chúng phụ thuộc keypoint tai có độ tin cậy
thấp; chúng là nhãn phụ, không phải nguồn cảnh báo chính (spec §5.3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping

from .features import Features

#: Tám nhãn của spec v2 §5.5.
HEAD_DOWN = "HEAD_DOWN"
TOO_CLOSE = "TOO_CLOSE"
SHOULDER_TILT = "SHOULDER_TILT"
HEAD_TILT = "HEAD_TILT"
LEAN = "LEAN"
LOOK_AWAY = "LOOK_AWAY"
ABSENT = "ABSENT"
GOOD = "GOOD"

#: Nhãn "xấu" — những nhãn khiến trạng thái rời khỏi GOOD.
BAD_LABELS = frozenset(
    {HEAD_DOWN, TOO_CLOSE, SHOULDER_TILT, HEAD_TILT, LEAN, LOOK_AWAY, ABSENT}
)

#: Thứ tự cố định để log/test/API ổn định.
LABEL_ORDER = (
    HEAD_DOWN,
    TOO_CLOSE,
    SHOULDER_TILT,
    HEAD_TILT,
    LEAN,
    LOOK_AWAY,
    ABSENT,
    GOOD,
)

#: Trọng số công thức điểm (không phải ngưỡng nghiệp vụ).
PENALTY_BASE = 10.0
PENALTY_WEIGHT = 20.0
PENALTY_MAX = 40.0
SCORE_MAX = 100.0
SCORE_MIN = 0.0


@dataclass(frozen=True)
class Classification:
    """Kết quả phân loại một khung."""

    labels: frozenset[str]
    score: float
    #: Mức vượt ngưỡng đã chuẩn hóa của từng nhãn (chỉ nhãn đang bật).
    excess: Mapping[str, float] = field(default_factory=dict)

    @property
    def is_good(self) -> bool:
        return GOOD in self.labels

    @property
    def sorted_labels(self) -> tuple[str, ...]:
        """Nhãn theo thứ tự cố định :data:`LABEL_ORDER`."""
        return tuple(label for label in LABEL_ORDER if label in self.labels)

    def penalty(self, label: str) -> float:
        """Điểm bị trừ bởi một nhãn; 0 nếu nhãn không bật."""
        return _penalty(self.excess.get(label, 0.0)) if label in self.labels else 0.0


def _penalty(excess: float) -> float:
    raw = PENALTY_BASE + PENALTY_WEIGHT * max(0.0, excess)
    return min(PENALTY_MAX, raw)


def _ratio_excess(value: float, limit: float) -> float:
    """Mức vượt ngưỡng tương đối khi ``value > limit`` (ngưỡng dương)."""
    if limit == 0:
        return 0.0
    return (value - limit) / abs(limit)


def _abs_excess(deviation: float, limit: float) -> float:
    """Mức vượt ngưỡng tương đối khi ``abs(deviation) > limit``."""
    if limit == 0:
        return 0.0
    return (deviation - limit) / abs(limit)


def _deviation(value: float | None, base: float | None) -> float | None:
    if value is None or base is None:
        return None
    return float(value) - float(base)


def _abs_deviation(value: float | None, base: float | None) -> float | None:
    deviation = _deviation(value, base)
    return None if deviation is None else abs(deviation)


def classify(
    features: Features,
    baseline,
    thresholds,
) -> Classification:
    """Áp luật §5.5 lên đặc trưng của một khung.

    Args:
        features: kết quả :func:`posture_monitor.features.extract`.
        baseline: :class:`posture_monitor.calibration.Baseline`. Đặc trưng
            baseline là ``None`` thì nhãn phụ thuộc nó không được đánh giá.
        thresholds: ``config.thresholds`` (``ThresholdsConfig``).

    Returns:
        :class:`Classification`. ``labels`` luôn chứa ``ABSENT`` hoặc
        ``GOOD`` hoặc ít nhất một nhãn xấu.
    """
    if not features.person or not features.has_shoulders:
        return Classification(
            labels=frozenset({ABSENT}),
            score=SCORE_MIN,
            excess={ABSENT: 1.0},
        )

    excess: dict[str, float] = {}

    def add(label: str, value: float) -> None:
        if value > 0.0:
            # Lấy mức vượt lớn nhất, không để luật sau ghi đè mức nặng hơn
            # của luật trước. Hiện tại mỗi nhãn chỉ có đúng một nguồn ghi
            # (HEAD_DOWN tách hẳn theo view, xem bên dưới), nên đây là phòng
            # thủ: không có đường nào qua API công khai chạm tới nhánh
            # ``max`` khi hai nguồn cùng bắn, vì vậy chưa có test cho nó.
            excess[label] = max(excess.get(label, 0.0), value)

    # ---- HEAD_DOWN (front): đầu thấp hơn baseline quá tỉ lệ cho phép ------
    # Chỉ áp ở front: ``head_height`` chuẩn hóa theo ``shoulder_width``, mà ở
    # góc nghiêng hai vai chồng nhau nên mẫu số co lại và phép chuẩn hóa suy
    # biến — đầu không đổi vẫn tụt "độ cao" khi người xoay/vai rộng ra. Spec
    # §5.5 ghi rõ cột điều kiện là "(front)"; side dùng ``neck_angle`` (§5.3).
    if features.view == "front":
        base_head_height = baseline.get("head_height")
        head_height = features.get("head_height")
        if base_head_height is not None and head_height is not None:
            limit = float(base_head_height) * float(thresholds.head_down_ratio)
            if limit > 0 and head_height < limit:
                add(HEAD_DOWN, (limit - head_height) / limit)

    # ---- TOO_CLOSE: vai rộng hơn baseline quá tỉ lệ -----------------------
    closeness = features.get("closeness")
    if closeness is not None:
        limit = float(thresholds.too_close_ratio)
        if closeness > limit:
            add(TOO_CLOSE, _ratio_excess(closeness, limit))

    # ---- SHOULDER_TILT ----------------------------------------------------
    deviation = _abs_deviation(
        features.get("shoulder_tilt_deg"), baseline.get("shoulder_tilt_deg")
    )
    if deviation is not None:
        add(
            SHOULDER_TILT,
            _abs_excess(deviation, float(thresholds.shoulder_tilt_deg)),
        )

    # ---- HEAD_TILT (nhãn phụ, phụ thuộc tai) ------------------------------
    deviation = _abs_deviation(
        features.get("head_tilt_deg"), baseline.get("head_tilt_deg")
    )
    if deviation is not None:
        add(HEAD_TILT, _abs_excess(deviation, float(thresholds.head_tilt_deg)))

    # ---- LEAN: ``lean_x`` đã là độ lệch so với baseline.x (features.py) ----
    lean_x = features.get("lean_x")
    if lean_x is not None:
        add(LEAN, _abs_excess(abs(float(lean_x)), float(thresholds.lean_x)))

    # ---- LOOK_AWAY (nhãn phụ, phụ thuộc tai) ------------------------------
    deviation = _abs_deviation(
        features.get("head_yaw"), baseline.get("head_yaw")
    )
    if deviation is not None:
        add(LOOK_AWAY, _abs_excess(deviation, float(thresholds.look_away_yaw)))

    # ---- Chế độ side: cổ gập quá ngưỡng coi là HEAD_DOWN ------------------
    # Spec §5.3 chỉ định nghĩa ngưỡng cho neck_angle ở chế độ side; dùng
    # HEAD_DOWN làm nhãn gần nhất thay vì thêm nhãn ngoài danh sách §5.5.
    # Ở side đây là **nguồn duy nhất** của HEAD_DOWN: luật head_height phía
    # trên bị chặn theo view, nên mỗi nhãn chỉ có một nguồn ghi.
    if features.view == "side":
        base_neck = baseline.get("neck_angle")
        neck_angle = features.get("neck_angle")
        if base_neck is not None and neck_angle is not None:
            drop = float(base_neck) - float(neck_angle)
            limit = float(thresholds.neck_angle_drop_deg)
            if drop > limit:
                add(HEAD_DOWN, (drop - limit) / abs(limit) if limit else 0.0)

    if not excess:
        return Classification(
            labels=frozenset({GOOD}), score=SCORE_MAX, excess={}
        )

    total = sum(_penalty(value) for value in excess.values())
    score = max(SCORE_MIN, min(SCORE_MAX, SCORE_MAX - total))
    return Classification(
        labels=frozenset(excess.keys()), score=score, excess=excess
    )


def merge_labels(items: Iterable[Classification]) -> frozenset[str]:
    """Hợp nhãn của nhiều kết quả (tiện cho test và cho bước làm mượt)."""
    merged: set[str] = set()
    for item in items:
        merged.update(item.labels)
    return frozenset(merged)
