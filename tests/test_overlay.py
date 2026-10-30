"""Kiểm thử ``overlay.py`` (spec v2 §10, mốc M1).

Test chạy trên PC, không cần model hay camera: vẽ lên khung tổng hợp và kiểm
bằng đếm pixel đổi màu.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from posture_monitor.overlay import (  # noqa: E402
    EDGE_COLOR,
    FACE_BOX_COLOR,
    KEYPOINT_NAMES,
    PHONE_BOX_COLOR,
    POINT_COLOR,
    SKELETON_EDGES,
    draw_pose,
)

_NUM_KEYPOINTS = 17


def _blank(width: int = 320, height: int = 240) -> np.ndarray:
    """Khung đen ``uint8`` để dễ đếm pixel bị vẽ."""
    return np.zeros((height, width, 3), dtype=np.uint8)


def _grid_points(width: int = 320, height: int = 240) -> np.ndarray:
    """17 điểm nằm rải trong khung, chắc chắn nhìn thấy."""
    xs = np.linspace(width * 0.2, width * 0.8, _NUM_KEYPOINTS)
    ys = np.linspace(height * 0.2, height * 0.8, _NUM_KEYPOINTS)
    return np.stack([xs, ys], axis=1).astype(np.float32)


def _changed_pixels(before: np.ndarray, after: np.ndarray) -> int:
    """Số pixel (bất kỳ kênh nào) khác nhau giữa hai khung."""
    diff = np.any(before != after, axis=2)
    return int(diff.sum())


# --------------------------------------------------------------------------
# Dữ liệu chuẩn COCO
# --------------------------------------------------------------------------


def test_keypoint_count_is_coco():
    assert len(KEYPOINT_NAMES) == _NUM_KEYPOINTS


def test_skeleton_edges_are_valid_indices():
    for start, end in SKELETON_EDGES:
        assert 0 <= start < _NUM_KEYPOINTS
        assert 0 <= end < _NUM_KEYPOINTS
        assert start != end


def test_skeleton_covers_core_joints():
    """Các khớp chính của COCO phải có mặt trong bộ xương."""
    used = {index for edge in SKELETON_EDGES for index in edge}
    for index in (0, 5, 6, 11, 12):  # mũi, hai vai, hai hông
        assert index in used


# --------------------------------------------------------------------------
# Hành vi vẽ
# --------------------------------------------------------------------------


def test_draws_something_with_full_confidence():
    """Đủ tin cậy thì có pixel bị vẽ đè."""
    frame = _blank()
    conf = np.ones(_NUM_KEYPOINTS, dtype=np.float32)

    drawn = draw_pose(frame, _grid_points(), conf, kp_conf_min=0.5)

    assert _changed_pixels(frame, drawn) > 0


def test_original_frame_untouched_by_default():
    """``copy=True`` (mặc định) không sửa khung gốc."""
    frame = _blank()
    before = frame.copy()

    draw_pose(frame, _grid_points(), np.ones(_NUM_KEYPOINTS, np.float32))

    assert np.array_equal(frame, before)


def test_copy_false_draws_in_place():
    """``copy=False`` vẽ trực tiếp lên khung truyền vào."""
    frame = _blank()
    before = frame.copy()

    drawn = draw_pose(
        frame,
        _grid_points(),
        np.ones(_NUM_KEYPOINTS, np.float32),
        copy=False,
    )

    assert drawn is frame
    assert _changed_pixels(before, frame) > 0


def test_none_pose_returns_unchanged_frame():
    """Không có người thì khung không đổi."""
    frame = _blank()

    drawn = draw_pose(frame, None, None)

    assert _changed_pixels(frame, drawn) == 0


def test_low_confidence_points_are_not_drawn():
    """Tất cả keypoint dưới ngưỡng → không vẽ gì."""
    frame = _blank()
    conf = np.full(_NUM_KEYPOINTS, 0.1, dtype=np.float32)

    drawn = draw_pose(frame, _grid_points(), conf, kp_conf_min=0.5)

    assert _changed_pixels(frame, drawn) == 0


def test_confidence_threshold_is_respected_at_boundary():
    """``conf == kp_conf_min`` được vẽ (ngưỡng là ``>=``); thấp hơn thì không."""
    points = _grid_points()
    at_threshold = np.full(_NUM_KEYPOINTS, 0.5, dtype=np.float32)
    below = np.full(_NUM_KEYPOINTS, 0.49, dtype=np.float32)

    drawn_at = draw_pose(_blank(), points, at_threshold, kp_conf_min=0.5)
    drawn_below = draw_pose(_blank(), points, below, kp_conf_min=0.5)

    assert _changed_pixels(_blank(), drawn_at) > 0
    assert _changed_pixels(_blank(), drawn_below) == 0


def test_edge_hidden_when_one_endpoint_below_threshold():
    """Xương có một đầu mút dưới ngưỡng thì không vẽ (không đoán khớp)."""
    # Hai điểm (0, 1) nằm ngang trên cùng một hàng; điểm giữa xương là
    # (60, 20), cách mỗi đầu 40 px nên không nét tròn nào che tới được.
    points = np.full((_NUM_KEYPOINTS, 2), np.nan, dtype=np.float32)
    points[0] = (20.0, 20.0)
    points[1] = (100.0, 20.0)
    conf = np.zeros(_NUM_KEYPOINTS, dtype=np.float32)
    conf[0] = 0.9
    conf[1] = 0.9

    both_visible = draw_pose(_blank(), points, conf, kp_conf_min=0.5)
    assert tuple(both_visible[20, 60]) == EDGE_COLOR

    conf[1] = 0.1
    edge_hidden = draw_pose(_blank(), points, conf, kp_conf_min=0.5)
    # Điểm 0 vẫn được vẽ, nhưng không còn xương nối tới điểm 1.
    assert tuple(edge_hidden[20, 60]) == (0, 0, 0)
    assert _changed_pixels(_blank(), edge_hidden) > 0


def test_colors_used_are_distinct():
    """Màu xương và màu điểm khác nhau để nhìn rõ trên hình."""
    assert EDGE_COLOR != POINT_COLOR


def test_hop_detection_khong_trung_mau_keypoint():
    """Hộp điện thoại/mặt phải khác màu chấm keypoint.

    Đã từng trùng: ``PHONE_BOX_COLOR`` là ``(0, 0, 255)`` y như ``POINT_COLOR``.
    Hộp đỏ vẽ đè lên khung xương đỏ thì mắt không tách được, và ảnh chụp màn
    hình gửi đi báo lỗi không còn chứng minh được hộp đã hiện.
    """
    assert PHONE_BOX_COLOR != POINT_COLOR
    assert PHONE_BOX_COLOR != EDGE_COLOR
    assert FACE_BOX_COLOR not in (POINT_COLOR, EDGE_COLOR, PHONE_BOX_COLOR)


def test_nan_points_are_skipped():
    """Toạ độ NaN/không hữu hạn bị bỏ, không làm crash hay vẽ bừa."""
    points = _grid_points()
    points[3] = np.nan
    points[4] = np.inf

    drawn = draw_pose(
        _blank(), points, np.ones(_NUM_KEYPOINTS, np.float32)
    )

    # Vẫn vẽ được phần còn lại.
    assert _changed_pixels(_blank(), drawn) > 0


def test_out_of_frame_points_are_clamped():
    """Điểm ngoài khung được kẹp vào biên, không crash."""
    points = _grid_points()
    points[0] = (-5000.0, -5000.0)
    points[1] = (5000.0, 5000.0)

    drawn = draw_pose(
        _blank(), points, np.ones(_NUM_KEYPOINTS, np.float32)
    )

    assert drawn.shape == (240, 320, 3)


def test_mismatched_conf_length_raises():
    """Sai hợp đồng (số conf khác số điểm) phải báo lỗi rõ, không vẽ sai."""
    with pytest.raises(ValueError):
        draw_pose(
            _blank(), _grid_points(), np.ones(5, dtype=np.float32)
        )


def test_conf_none_draws_all_points():
    """Thiếu ``conf`` thì coi mọi điểm đều hiển thị."""
    frame = _blank()

    drawn = draw_pose(frame, _grid_points(), None)

    assert _changed_pixels(frame, drawn) > 0
