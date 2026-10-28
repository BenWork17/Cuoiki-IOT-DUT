"""Unit test cho ``classifier.py`` (spec v2 §5.5, §9).

Mỗi luật được kiểm tra **quanh ngưỡng**: ngay dưới (không bật), đúng bằng
(không bật, vì luật là "vượt ngưỡng"), ngay trên (bật). Toàn bộ ngưỡng lấy
từ :class:`ThresholdsConfig` của ``config.py``, không viết cứng trong test.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from posture_monitor.classifier import (  # noqa: E402
    ABSENT,
    GOOD,
    HEAD_DOWN,
    HEAD_TILT,
    LEAN,
    LOOK_AWAY,
    SHOULDER_TILT,
    TOO_CLOSE,
    classify,
    merge_labels,
)
from posture_monitor.config import ThresholdsConfig  # noqa: E402
from posture_monitor.features import Features  # noqa: E402

THRESHOLDS = ThresholdsConfig()
BASELINE_VALUES = {
    "shoulder_width": 200.0,
    "shoulder_tilt_deg": 0.0,
    "head_tilt_deg": 0.0,
    "head_height": 0.5,
    "closeness": 1.0,
    "lean_x": 0.0,
    "head_yaw": 0.0,
    "neck_angle": 170.0,
    "torso_angle": 170.0,
    "shoulder_mid_x": 300.0,
}


class FakeBaseline:
    """Baseline đọc được bằng ``get`` cho mọi đặc trưng."""

    def __init__(self, **overrides):
        self.values = dict(BASELINE_VALUES)
        self.values.update(overrides)

    def get(self, name):
        return self.values.get(name)


def make_features(**overrides) -> Features:
    """Features với mọi đặc trưng ở giá trị "tốt", rồi ghi đè từng cái."""
    view = overrides.pop("view", "front")
    values = dict(BASELINE_VALUES)
    values["closeness"] = 1.0
    values["lean_x"] = 0.0
    values["head_yaw"] = 0.0
    values.update(overrides)
    return Features(view=view, person=True, values=values)


def labels_of(features, baseline=None, thresholds=THRESHOLDS):
    return classify(features, baseline or FakeBaseline(), thresholds).labels


# ---------------------------------------------------------------------------
# ABSENT / GOOD
# ---------------------------------------------------------------------------

def test_no_person_is_absent_with_zero_score():
    features = Features(view="front", person=False, values={})
    result = classify(features, FakeBaseline(), THRESHOLDS)
    assert result.labels == frozenset({ABSENT})
    assert result.score == 0.0


def test_missing_shoulders_is_absent_even_if_person_seen():
    """Spec §5.5: ABSENT khi không thấy người hoặc thiếu hai vai."""
    features = make_features(shoulder_width=None)
    assert labels_of(features) == frozenset({ABSENT})


def test_all_features_in_range_is_good_with_full_score():
    result = classify(make_features(), FakeBaseline(), THRESHOLDS)
    assert result.labels == frozenset({GOOD})
    assert result.score == 100.0


# ---------------------------------------------------------------------------
# HEAD_DOWN — head_height < baseline.head_height * head_down_ratio
# ---------------------------------------------------------------------------

def test_head_down_just_above_threshold_is_good():
    ratio = THRESHOLDS.head_down_ratio
    limit = BASELINE_VALUES["head_height"] * ratio
    features = make_features(head_height=limit + 0.001)
    assert GOOD in labels_of(features)


def test_head_down_exactly_at_threshold_is_good():
    ratio = THRESHOLDS.head_down_ratio
    limit = BASELINE_VALUES["head_height"] * ratio
    features = make_features(head_height=limit)
    assert GOOD in labels_of(features)


def test_head_down_just_below_threshold_is_flagged():
    ratio = THRESHOLDS.head_down_ratio
    limit = BASELINE_VALUES["head_height"] * ratio
    features = make_features(head_height=limit - 0.001)
    assert HEAD_DOWN in labels_of(features)


def test_head_down_is_skipped_when_baseline_missing():
    baseline = FakeBaseline(head_height=None)
    features = make_features(head_height=0.1)
    assert labels_of(features, baseline) == frozenset({GOOD})


def test_head_down_is_skipped_when_feature_missing():
    """head_height=None (thiếu mũi hoặc vai) → không đánh giá, không đoán."""
    features = make_features(head_height=None)
    assert labels_of(features) == frozenset({GOOD})


# ---------------------------------------------------------------------------
# TOO_CLOSE — closeness > too_close_ratio
# ---------------------------------------------------------------------------

def test_too_close_below_threshold_is_good():
    features = make_features(closeness=THRESHOLDS.too_close_ratio - 0.01)
    assert GOOD in labels_of(features)


def test_too_close_exactly_at_threshold_is_good():
    features = make_features(closeness=THRESHOLDS.too_close_ratio)
    assert GOOD in labels_of(features)


def test_too_close_above_threshold_is_flagged():
    features = make_features(closeness=THRESHOLDS.too_close_ratio + 0.01)
    assert TOO_CLOSE in labels_of(features)


# ---------------------------------------------------------------------------
# SHOULDER_TILT — abs(shoulder_tilt − baseline) > ngưỡng
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("offset", "expected"),
    [
        (-0.01, False),
        (0.0, False),
        (0.01, True),
        (-0.01, False),
    ],
)
def test_shoulder_tilt_around_threshold(offset, expected):
    limit = THRESHOLDS.shoulder_tilt_deg
    features = make_features(shoulder_tilt_deg=limit + offset)
    assert (SHOULDER_TILT in labels_of(features)) is expected


def test_shoulder_tilt_in_negative_direction_is_flagged():
    """Nghiêng sang trái cũng phải bắt: dùng trị tuyệt đối độ lệch."""
    limit = THRESHOLDS.shoulder_tilt_deg
    features = make_features(shoulder_tilt_deg=-limit - 0.01)
    assert SHOULDER_TILT in labels_of(features)


def test_shoulder_tilt_exactly_at_threshold_is_good():
    limit = THRESHOLDS.shoulder_tilt_deg
    features = make_features(shoulder_tilt_deg=-limit)
    assert GOOD in labels_of(features)


# ---------------------------------------------------------------------------
# HEAD_TILT — nhãn phụ, cần baseline tai
# ---------------------------------------------------------------------------

def test_head_tilt_around_threshold():
    limit = THRESHOLDS.head_tilt_deg
    assert HEAD_TILT not in labels_of(make_features(head_tilt_deg=limit))
    assert HEAD_TILT in labels_of(make_features(head_tilt_deg=limit + 0.01))
    assert HEAD_TILT not in labels_of(make_features(head_tilt_deg=limit - 0.01))


def test_head_tilt_skipped_when_ears_missing():
    """Tai có conf thấp → head_tilt=None → không đánh giá (spec §5.3)."""
    assert labels_of(make_features(head_tilt_deg=None)) == frozenset({GOOD})


# ---------------------------------------------------------------------------
# LEAN — abs(lean_x) > ngưỡng
# ---------------------------------------------------------------------------

def test_lean_around_threshold():
    limit = THRESHOLDS.lean_x
    assert LEAN not in labels_of(make_features(lean_x=limit))
    assert LEAN in labels_of(make_features(lean_x=limit + 0.01))
    assert LEAN in labels_of(make_features(lean_x=-limit - 0.01))
    assert LEAN not in labels_of(make_features(lean_x=limit - 0.01))


# ---------------------------------------------------------------------------
# LOOK_AWAY — abs(head_yaw − baseline) > ngưỡng
# ---------------------------------------------------------------------------

def test_look_away_around_threshold():
    limit = THRESHOLDS.look_away_yaw
    assert LOOK_AWAY not in labels_of(make_features(head_yaw=limit))
    assert LOOK_AWAY in labels_of(make_features(head_yaw=limit + 0.01))
    assert LOOK_AWAY not in labels_of(make_features(head_yaw=limit - 0.01))


def test_look_away_uses_baseline_not_absolute_zero():
    """Baseline lệch 0.2 thì ngưỡng tính từ baseline, không từ 0 (spec §5.5)."""
    baseline = FakeBaseline(head_yaw=0.2)
    limit = THRESHOLDS.look_away_yaw
    features = make_features(head_yaw=0.2 + limit)
    assert LOOK_AWAY not in labels_of(features, baseline)
    features = make_features(head_yaw=0.2 + limit + 0.01)
    assert LOOK_AWAY in labels_of(features, baseline)


# ---------------------------------------------------------------------------
# Chế độ side
# ---------------------------------------------------------------------------

def test_side_neck_drop_around_threshold():
    limit = THRESHOLDS.neck_angle_drop_deg
    base = BASELINE_VALUES["neck_angle"]
    features = make_features(view="side", neck_angle=base - limit)
    assert HEAD_DOWN not in labels_of(features)

    features = make_features(view="side", neck_angle=base - limit - 0.01)
    assert HEAD_DOWN in labels_of(features)


def test_front_ignores_neck_angle():
    limit = THRESHOLDS.neck_angle_drop_deg
    features = make_features(view="front", neck_angle=170.0 - limit - 10.0)
    assert GOOD in labels_of(features)


def test_side_ignores_head_height_rule():
    """Ở góc nghiêng hai vai chồng nhau nên ``head_height`` suy biến.

    Spec §5.5 ghi cột điều kiện là "(front)"; side chỉ dùng ``neck_angle``
    (§5.3). Đầu không đổi mà vai rộng ra không được sinh HEAD_DOWN giả.
    """
    ratio = THRESHOLDS.head_down_ratio
    limit = BASELINE_VALUES["head_height"] * ratio
    very_low = limit / 4.0  # thấp hơn hẳn ngưỡng, như bảng tái hiện của Lead

    side = make_features(view="side", head_height=very_low, neck_angle=170.0)
    assert HEAD_DOWN not in labels_of(side)
    assert labels_of(side) == frozenset({GOOD})

    front = make_features(view="front", head_height=very_low)
    assert HEAD_DOWN in labels_of(front)


def test_side_head_down_still_comes_from_neck_angle():
    """Chặn luật head_height không được làm mất nguồn HEAD_DOWN của side."""
    limit = THRESHOLDS.neck_angle_drop_deg
    base = BASELINE_VALUES["neck_angle"]
    features = make_features(
        view="side", head_height=0.0, neck_angle=base - limit - 1.0
    )
    result = classify(features, FakeBaseline(), THRESHOLDS)
    assert HEAD_DOWN in result.labels


# ---------------------------------------------------------------------------
# Nhiều nhãn, điểm số
# ---------------------------------------------------------------------------

def test_multiple_labels_can_fire_at_once():
    features = make_features(
        closeness=THRESHOLDS.too_close_ratio + 0.1,
        shoulder_tilt_deg=THRESHOLDS.shoulder_tilt_deg + 5.0,
    )
    labels = labels_of(features)
    assert TOO_CLOSE in labels
    assert SHOULDER_TILT in labels
    assert GOOD not in labels
    assert ABSENT not in labels


def test_score_never_below_zero_even_with_every_label():
    features = make_features(
        head_height=0.0,
        closeness=5.0,
        shoulder_tilt_deg=90.0,
        head_tilt_deg=90.0,
        lean_x=5.0,
        head_yaw=5.0,
    )
    result = classify(features, FakeBaseline(), THRESHOLDS)
    assert result.score == 0.0
    assert result.score >= 0.0


def test_score_is_between_zero_and_hundred_and_drops_with_excess():
    mild = classify(
        make_features(closeness=THRESHOLDS.too_close_ratio + 0.01),
        FakeBaseline(),
        THRESHOLDS,
    )
    severe = classify(
        make_features(closeness=THRESHOLDS.too_close_ratio * 3),
        FakeBaseline(),
        THRESHOLDS,
    )
    assert 0.0 <= severe.score < mild.score < 100.0


def test_thresholds_come_from_config_not_constants():
    """Đổi ngưỡng trong config phải đổi kết quả (spec §1, §11.2)."""
    features = make_features(shoulder_tilt_deg=20.0)
    loose = ThresholdsConfig(shoulder_tilt_deg=25.0)
    strict = ThresholdsConfig(shoulder_tilt_deg=5.0)

    assert SHOULDER_TILT not in labels_of(features, thresholds=loose)
    assert SHOULDER_TILT in labels_of(features, thresholds=strict)


def test_sorted_labels_is_stable_order():
    features = make_features(
        shoulder_tilt_deg=THRESHOLDS.shoulder_tilt_deg + 5.0,
        closeness=THRESHOLDS.too_close_ratio + 0.1,
    )
    result = classify(features, FakeBaseline(), THRESHOLDS)
    assert result.sorted_labels == (TOO_CLOSE, SHOULDER_TILT)


def test_penalty_is_zero_for_inactive_label():
    result = classify(make_features(), FakeBaseline(), THRESHOLDS)
    assert result.penalty(HEAD_DOWN) == 0.0


def test_merge_labels_unions_results():
    a = classify(
        make_features(closeness=THRESHOLDS.too_close_ratio + 0.1),
        FakeBaseline(),
        THRESHOLDS,
    )
    b = classify(make_features(), FakeBaseline(), THRESHOLDS)
    assert merge_labels([a, b]) == frozenset({TOO_CLOSE, GOOD})
