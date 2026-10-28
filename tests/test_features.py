"""Unit test cho ``features.py`` (spec v2 §5.3, §9).

Keypoint đều là **tổng hợp** với kết quả đã biết trước, nên test chạy trên PC
mà không cần model, camera hay ``pose.py``.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from posture_monitor.features import (  # noqa: E402
    LEFT_EAR,
    LEFT_HIP,
    LEFT_KNEE,
    LEFT_SHOULDER,
    NOSE,
    RIGHT_EAR,
    RIGHT_HIP,
    RIGHT_KNEE,
    RIGHT_SHOULDER,
    Features,
    angle_at,
    extract,
    normalize_angle,
)

ALL_VISIBLE = 0.99


def make_keypoints(
    *,
    left_shoulder=(200.0, 300.0),
    right_shoulder=(400.0, 300.0),
    nose=(300.0, 200.0),
    left_ear=(260.0, 180.0),
    right_ear=(340.0, 180.0),
    left_hip=(220.0, 450.0),
    right_hip=(380.0, 450.0),
    left_knee=(220.0, 600.0),
    right_knee=(380.0, 600.0),
    conf=ALL_VISIBLE,
):
    """Dựng cặp ``(xy, conf)`` 17 keypoint; mọi keypoint khác đặt giữa ảnh."""
    xy = np.full((17, 2), 0.0)
    xy[:, 0] = 320.0
    xy[:, 1] = 240.0
    xy[NOSE] = nose
    xy[LEFT_EAR] = left_ear
    xy[RIGHT_EAR] = right_ear
    xy[LEFT_SHOULDER] = left_shoulder
    xy[RIGHT_SHOULDER] = right_shoulder
    xy[LEFT_HIP] = left_hip
    xy[RIGHT_HIP] = right_hip
    xy[LEFT_KNEE] = left_knee
    xy[RIGHT_KNEE] = right_knee
    confidence = np.full((17,), conf)
    return xy, confidence


class FakeBaseline:
    """Baseline tối thiểu cho ``closeness``/``lean_x``."""

    def __init__(self, shoulder_width: float, shoulder_mid_x: float):
        self.shoulder_width = shoulder_width
        self.shoulder_mid_x = shoulder_mid_x


# ---------------------------------------------------------------------------
# normalize_angle — quy tắc bắt buộc của §5.3
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (0.0, 0.0),
        (45.0, 45.0),
        (90.0, 90.0),
        (-90.0, 90.0),      # -90 và +90 cùng một đường thẳng đứng
        (91.0, -89.0),
        (179.69, pytest.approx(-0.31, abs=1e-9)),
        (-179.69, pytest.approx(0.31, abs=1e-9)),
        (-120.0, 60.0),
        (270.0, 90.0),      # đầu vào lệch vòng vẫn nhất quán
    ],
)
def test_normalize_angle_matches_spec_rule(raw, expected):
    assert normalize_angle(raw) == expected


@pytest.mark.parametrize("raw", [-179.69, -179.0, 179.0, 179.69, -900.0, 900.0])
def test_normalize_angle_always_within_half_open_range(raw):
    result = normalize_angle(raw)
    assert -90.0 < result <= 90.0


def test_normalize_angle_rejects_nan():
    with pytest.raises(ValueError):
        normalize_angle(float("nan"))


# ---------------------------------------------------------------------------
# Đặc trưng front với hình học đã biết
# ---------------------------------------------------------------------------

def test_shoulder_width_and_tilt_for_horizontal_shoulders():
    xy, conf = make_keypoints(
        left_shoulder=(200.0, 300.0), right_shoulder=(400.0, 300.0)
    )
    result = extract(xy, conf, view="front")

    assert result.person is True
    assert result["shoulder_width"] == pytest.approx(200.0)
    assert result["shoulder_tilt_deg"] == pytest.approx(0.0, abs=1e-9)


def test_shoulder_tilt_known_angle():
    """Vai phải thấp hơn 100 px trên 100 px ngang → đúng 45°."""
    xy, conf = make_keypoints(
        left_shoulder=(200.0, 200.0), right_shoulder=(300.0, 300.0)
    )
    result = extract(xy, conf, view="front")
    assert result["shoulder_tilt_deg"] == pytest.approx(45.0)


def test_head_height_is_ratio_not_pixels():
    """head_height = (y giữa vai − y mũi) / shoulder_width."""
    xy, conf = make_keypoints(
        left_shoulder=(200.0, 300.0),
        right_shoulder=(400.0, 300.0),
        nose=(300.0, 200.0),
    )
    result = extract(xy, conf, view="front")
    assert result["head_height"] == pytest.approx((300.0 - 200.0) / 200.0)


def test_head_yaw_uses_ear_distance():
    xy, conf = make_keypoints(
        left_ear=(260.0, 180.0),
        right_ear=(340.0, 180.0),
        nose=(325.0, 200.0),
    )
    result = extract(xy, conf, view="front")
    # (325 − 300) / 80
    assert result["head_yaw"] == pytest.approx(25.0 / 80.0)


def test_head_tilt_known_angle():
    xy, conf = make_keypoints(
        left_ear=(260.0, 180.0), right_ear=(300.0, 220.0)
    )
    result = extract(xy, conf, view="front")
    assert result["head_tilt_deg"] == pytest.approx(45.0)


def test_closeness_and_lean_need_baseline():
    xy, conf = make_keypoints(
        left_shoulder=(200.0, 300.0), right_shoulder=(400.0, 300.0)
    )
    baseline = FakeBaseline(shoulder_width=100.0, shoulder_mid_x=330.0)

    without = extract(xy, conf, view="front")
    assert without["closeness"] is None
    assert without["lean_x"] is None

    with_baseline = extract(xy, conf, view="front", baseline=baseline)
    assert with_baseline["closeness"] == pytest.approx(2.0)
    # x giữa vai hiện tại 300, baseline 330, chia cho shoulder_width 200
    assert with_baseline["lean_x"] == pytest.approx((300.0 - 330.0) / 200.0)


# ---------------------------------------------------------------------------
# Chuẩn hóa góc trên dữ liệu thật của bẫy §5.3
# ---------------------------------------------------------------------------

def test_swapped_shoulders_are_normalized_not_near_180():
    """Vai bị đảo trái/phải: góc thô ≈ 180°, chuẩn hóa phải về gần 0."""
    xy, conf = make_keypoints(
        left_shoulder=(400.0, 300.0), right_shoulder=(200.0, 300.0)
    )
    raw_angle = math.degrees(
        math.atan2(300.0 - 300.0, 200.0 - 400.0)
    )
    assert abs(raw_angle) == pytest.approx(180.0)

    result = extract(xy, conf, view="front")
    assert result["shoulder_tilt_deg"] is not None
    assert abs(result["shoulder_tilt_deg"]) < 1.0
    assert -90.0 < result["shoulder_tilt_deg"] <= 90.0


def test_swapped_ears_are_normalized_not_near_180():
    """Cùng bẫy với tai: đảo trái/phải cho thô ≈ 180° nhưng chuẩn hóa gần 0."""
    xy, conf = make_keypoints(
        left_ear=(340.0, 180.0), right_ear=(260.0, 180.0)
    )
    result = extract(xy, conf, view="front")
    assert abs(result["head_tilt_deg"]) < 1.0
    assert -90.0 < result["head_tilt_deg"] <= 90.0


def test_normalization_keeps_steep_real_tilt():
    """Nghiêng thật 80° vẫn giữ 80°, không bị quy về 0."""
    # dx=10, dy=57 → atan2 ≈ 80.0°
    dy = 10.0 * math.tan(math.radians(80.0))
    xy, conf = make_keypoints(
        left_shoulder=(200.0, 300.0), right_shoulder=(210.0, 300.0 + dy)
    )
    result = extract(xy, conf, view="front")
    assert result["shoulder_tilt_deg"] == pytest.approx(80.0, abs=1e-6)


# ---------------------------------------------------------------------------
# Keypoint thiếu → None, tuyệt đối không đoán
# ---------------------------------------------------------------------------

def test_none_xy_means_no_person():
    result = extract(None, None, view="front")
    assert result.person is False
    assert result.has_shoulders is False
    assert all(result[name] is None for name in result.values)


def test_low_confidence_shoulder_yields_none_features():
    xy, conf = make_keypoints()
    conf[LEFT_SHOULDER] = 0.49
    result = extract(xy, conf, view="front", kp_conf_min=0.5)

    assert result.person is True
    assert result.has_shoulders is False
    assert result["shoulder_width"] is None
    assert result["shoulder_tilt_deg"] is None
    assert result["head_height"] is None


def test_confidence_exactly_at_threshold_is_used():
    """Spec: ``conf >= kp_conf_min``, nên đúng bằng ngưỡng vẫn dùng."""
    xy, conf = make_keypoints()
    conf[LEFT_SHOULDER] = 0.5
    conf[RIGHT_SHOULDER] = 0.5
    result = extract(xy, conf, view="front", kp_conf_min=0.5)
    assert result["shoulder_width"] == pytest.approx(200.0)


def test_missing_ears_only_disable_ear_features():
    """Tai thiếu không được kéo theo đặc trưng vai (spec §5.3)."""
    xy, conf = make_keypoints()
    conf[LEFT_EAR] = 0.1
    result = extract(xy, conf, view="front")

    assert result["head_tilt_deg"] is None
    assert result["head_yaw"] is None
    assert result["shoulder_width"] == pytest.approx(200.0)
    assert result["head_height"] is not None


def test_missing_nose_keeps_shoulder_features_but_drops_head_height():
    xy, conf = make_keypoints()
    conf[NOSE] = 0.0
    result = extract(xy, conf, view="front")
    assert result["shoulder_width"] is not None
    assert result["head_height"] is None


def test_non_finite_keypoint_is_treated_as_missing():
    xy, conf = make_keypoints()
    xy[LEFT_SHOULDER] = (float("nan"), 300.0)
    result = extract(xy, conf, view="front")
    assert result["shoulder_width"] is None


# ---------------------------------------------------------------------------
# Chế độ side
# ---------------------------------------------------------------------------

def test_side_neck_angle_for_known_geometry():
    """Tai thẳng trên vai, hông thẳng dưới vai → góc cổ = 180°."""
    xy, conf = make_keypoints(
        left_shoulder=(300.0, 300.0),
        right_shoulder=(320.0, 300.0),
        left_ear=(300.0, 200.0),
        right_ear=(320.0, 200.0),
        left_hip=(300.0, 450.0),
        right_hip=(320.0, 450.0),
    )
    result = extract(xy, conf, view="side")
    assert result["neck_angle"] == pytest.approx(180.0)


def test_side_neck_angle_drops_when_head_leans_forward():
    """Đầu chúi về trước 45° so với trục thân."""
    xy, conf = make_keypoints(
        left_shoulder=(300.0, 300.0),
        right_shoulder=(320.0, 300.0),
        left_ear=(400.0, 200.0),   # lệch phải 100, cao 100 → 45°
        right_ear=(420.0, 200.0),
        left_hip=(300.0, 450.0),
        right_hip=(320.0, 450.0),
    )
    result = extract(xy, conf, view="side")
    assert result["neck_angle"] == pytest.approx(135.0)


def test_side_picks_the_side_with_higher_confidence():
    """Bên phải thấy rõ hơn phải được chọn, không phải bên trái mặc định."""
    xy, conf = make_keypoints(
        left_shoulder=(200.0, 300.0),
        right_shoulder=(300.0, 300.0),
        left_ear=(200.0, 200.0),    # cấu hình góc 180°
        right_ear=(400.0, 200.0),   # cấu hình góc 90°
        left_hip=(200.0, 450.0),
        right_hip=(300.0, 450.0),
    )
    conf[LEFT_SHOULDER] = conf[LEFT_EAR] = conf[LEFT_HIP] = 0.55
    conf[RIGHT_SHOULDER] = conf[RIGHT_EAR] = conf[RIGHT_HIP] = 0.95

    result = extract(xy, conf, view="side")
    assert result["neck_angle"] == pytest.approx(135.0)


def test_side_reports_torso_angle_when_knees_visible():
    xy, conf = make_keypoints(
        left_shoulder=(300.0, 300.0),
        right_shoulder=(320.0, 300.0),
        left_ear=(300.0, 200.0),
        right_ear=(320.0, 200.0),
        left_hip=(300.0, 450.0),
        right_hip=(320.0, 450.0),
        left_knee=(400.0, 550.0),
        right_knee=(420.0, 550.0),
    )
    result = extract(xy, conf, view="side")
    assert result["torso_angle"] == pytest.approx(135.0)


def test_front_mode_does_not_report_side_features():
    xy, conf = make_keypoints()
    result = extract(xy, conf, view="front")
    assert result["neck_angle"] is None
    assert result["torso_angle"] is None


# ---------------------------------------------------------------------------
# Kiểm tra đầu vào / tiện ích
# ---------------------------------------------------------------------------

def test_invalid_view_is_rejected():
    xy, conf = make_keypoints()
    with pytest.raises(ValueError):
        extract(xy, conf, view="top")


def test_wrong_xy_shape_is_rejected():
    with pytest.raises(ValueError):
        extract(np.zeros((10, 2)), np.zeros(10), view="front")


def test_wrong_conf_shape_is_rejected():
    xy, _ = make_keypoints()
    with pytest.raises(ValueError):
        extract(xy, np.zeros(5), view="front")


def test_conf_none_with_xy_is_rejected():
    xy, _ = make_keypoints()
    with pytest.raises(ValueError):
        extract(xy, None, view="front")


def test_angle_at_returns_none_for_degenerate_vectors():
    assert angle_at((0.0, 0.0), (0.0, 0.0), (1.0, 1.0)) is None


def test_features_get_returns_none_for_unknown_name():
    features = Features(view="front", person=False, values={})
    assert features.get("khong_ton_tai") is None


def test_zero_width_shoulders_do_not_divide_by_zero():
    xy, conf = make_keypoints(
        left_shoulder=(300.0, 300.0), right_shoulder=(300.0, 300.0)
    )
    result = extract(xy, conf, view="front")
    assert result["shoulder_width"] is None
    assert result["shoulder_tilt_deg"] is None
    assert result["head_height"] is None
