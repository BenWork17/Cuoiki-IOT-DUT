"""Phân loại tư thế theo luật hình học & lọc nhãn cảnh báo (spec v2 §5.5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from ..core.labels import (
    ABSENT,
    BAD_LABELS,
    GOOD,
    HEAD_DOWN,
    HEAD_TILT,
    LABEL_ORDER,
    LEAN,
    LOOK_AWAY,
    SHOULDER_TILT,
    TOO_CLOSE,
)
from .features import Features

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
    excess: Mapping[str, float] = field(default_factory=dict)

    @property
    def is_good(self) -> bool:
        return GOOD in self.labels

    @property
    def sorted_labels(self) -> tuple[str, ...]:
        return tuple(label for label in LABEL_ORDER if label in self.labels)

    def penalty(self, label: str) -> float:
        return _penalty(self.excess.get(label, 0.0)) if label in self.labels else 0.0


def _penalty(excess: float) -> float:
    raw = PENALTY_BASE + PENALTY_WEIGHT * max(0.0, excess)
    return min(PENALTY_MAX, raw)


def _ratio_excess(value: float, limit: float) -> float:
    if limit == 0:
        return 0.0
    return (value - limit) / abs(limit)


def _abs_excess(deviation: float, limit: float) -> float:
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
    baseline: Any,
    thresholds: Any,
) -> Classification:
    """Áp luật phân loại tư thế §5.5 lên đặc trưng của một khung."""
    if not features.person or not features.has_shoulders:
        return Classification(
            labels=frozenset({ABSENT}),
            score=SCORE_MIN,
            excess={ABSENT: 1.0},
        )

    excess: dict[str, float] = {}

    def add(label: str, value: float) -> None:
        if value > 0.0:
            excess[label] = max(excess.get(label, 0.0), value)

    if features.view == "front":
        base_head_height = baseline.get("head_height")
        head_height = features.get("head_height")
        if base_head_height is not None and head_height is not None:
            limit = float(base_head_height) * float(thresholds.head_down_ratio)
            if limit > 0 and head_height < limit:
                add(HEAD_DOWN, (limit - head_height) / limit)

    closeness = features.get("closeness")
    if closeness is not None:
        limit = float(thresholds.too_close_ratio)
        if closeness > limit:
            add(TOO_CLOSE, _ratio_excess(closeness, limit))

    deviation = _abs_deviation(
        features.get("shoulder_tilt_deg"), baseline.get("shoulder_tilt_deg")
    )
    if deviation is not None:
        add(SHOULDER_TILT, _abs_excess(deviation, float(thresholds.shoulder_tilt_deg)))

    deviation = _abs_deviation(
        features.get("head_tilt_deg"), baseline.get("head_tilt_deg")
    )
    if deviation is not None:
        add(HEAD_TILT, _abs_excess(deviation, float(thresholds.head_tilt_deg)))

    lean_x = features.get("lean_x")
    if lean_x is not None:
        add(LEAN, _abs_excess(abs(float(lean_x)), float(thresholds.lean_x)))

    deviation = _abs_deviation(features.get("head_yaw"), baseline.get("head_yaw"))
    if deviation is not None:
        add(LOOK_AWAY, _abs_excess(deviation, float(thresholds.look_away_yaw)))

    if features.view == "side":
        base_neck = baseline.get("neck_angle")
        neck_angle = features.get("neck_angle")
        if base_neck is not None and neck_angle is not None:
            drop = float(base_neck) - float(neck_angle)
            limit = float(thresholds.neck_angle_drop_deg)
            if drop > limit:
                add(HEAD_DOWN, (drop - limit) / abs(limit) if limit else 0.0)

    if not excess:
        return Classification(labels=frozenset({GOOD}), score=SCORE_MAX, excess={})

    total = sum(_penalty(value) for value in excess.values())
    score = max(SCORE_MIN, min(SCORE_MAX, SCORE_MAX - total))
    return Classification(
        labels=frozenset(excess.keys()), score=score, excess=excess
    )


def merge_labels(items: Iterable[Classification]) -> frozenset[str]:
    """Hợp nhãn của nhiều kết quả."""
    merged: set[str] = set()
    for item in items:
        merged.update(item.labels)
    return frozenset(merged)


def filter_posture_labels(labels: Iterable[str], enabled: bool) -> frozenset[str]:
    """Lọc nhãn tư thế khỏi tập nhãn sinh cảnh báo khi ``posture_labels_enabled=False``.

    ``ABSENT`` luôn được giữ lại vì cảnh báo rời khung hình phụ thuộc vào nó.
    """
    if enabled:
        return frozenset(labels)
    return frozenset(label for label in labels if label == ABSENT)


__all__ = [
    "ABSENT",
    "BAD_LABELS",
    "Classification",
    "GOOD",
    "HEAD_DOWN",
    "HEAD_TILT",
    "LABEL_ORDER",
    "LEAN",
    "LOOK_AWAY",
    "PENALTY_BASE",
    "PENALTY_MAX",
    "PENALTY_WEIGHT",
    "SCORE_MAX",
    "SCORE_MIN",
    "SHOULDER_TILT",
    "TOO_CLOSE",
    "classify",
    "filter_posture_labels",
    "merge_labels",
]
