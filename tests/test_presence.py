"""Kiểm thử ``presence.py`` — người ngồi trong khung và trạng thái vắng mặt.

Test chạy trên PC, không cần model hay camera: ``PoseResult`` được dựng bằng
numpy và đồng hồ được tiêm bằng một bộ đếm giả, nên không có ``sleep`` thật và
kết quả tất định.
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

from posture_monitor.pose import NUM_KEYPOINTS, PoseResult  # noqa: E402
from posture_monitor.presence import (  # noqa: E402
    STATE_ABSENT,
    STATE_PRESENT,
    PresenceTracker,
    count_upper_keypoints,
)

#: Chỉ số COCO của vùng thân trên dùng trong test.
UPPER = (0, 1, 2, 3, 4, 5, 6)


class _FakeClock:
    """Đồng hồ tiêm được: thời gian chỉ chạy khi test tự đẩy."""

    def __init__(self, start: float = 100.0) -> None:
        self.now = float(start)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += float(seconds)


def _pose(conf_upper: float, *, conf_lower: float = 0.0) -> PoseResult:
    """PoseResult tổng hợp: 7 điểm thân trên và 10 điểm dưới cùng độ tin cậy."""
    conf = np.zeros(NUM_KEYPOINTS, dtype=np.float32)
    conf[list(UPPER)] = conf_upper
    conf[7:] = conf_lower
    xy = np.zeros((NUM_KEYPOINTS, 2), dtype=np.float32)
    return PoseResult(xy=xy, conf=conf, bbox=np.array([0, 0, 10, 10], np.float32))


# --------------------------------------------------------------------------
# count_upper_keypoints — hàm thuần
# --------------------------------------------------------------------------


def test_confidence_equal_to_threshold_counts():
    """Keypoint có conf đúng bằng ngưỡng vẫn phải được đếm."""
    assert count_upper_keypoints(_pose(0.5), 0.5) == len(UPPER)


def test_confidence_below_threshold_ignored():
    assert count_upper_keypoints(_pose(0.49), 0.5) == 0


def test_count_ignores_lower_body_keypoints():
    """Hông/gối/ cổ chân tin cậy cao cũng không chứng minh được thân trên."""
    assert count_upper_keypoints(_pose(0.0, conf_lower=0.99), 0.5) == 0


@pytest.mark.parametrize(
    "broken",
    [
        None,
        object(),
        PoseResult(xy=np.zeros((0, 2)), conf=np.zeros(0), bbox=np.zeros(4)),
        PoseResult(xy=np.zeros((17, 2)), conf=np.zeros((3, 3)), bbox=np.zeros(4)),
        PoseResult(
            xy=np.zeros((17, 2)),
            conf=np.full(17, np.nan, dtype=np.float32),
            bbox=np.zeros(4),
        ),
    ],
)
def test_malformed_input_does_not_crash(broken):
    """Dữ liệu hỏng trả 0, không ném lỗi."""
    assert count_upper_keypoints(broken, 0.5) == 0


def test_all_zero_confidence_is_not_present():
    assert count_upper_keypoints(_pose(0.0), 0.5) == 0


# --------------------------------------------------------------------------
# PresenceTracker — bộ lọc thời gian
# --------------------------------------------------------------------------


def test_person_visible_is_present():
    clock = _FakeClock()
    tracker = PresenceTracker(absent_hold_s=3.0, clock=clock)

    result = tracker.update(_pose(0.9))

    assert result.present is True
    assert result.state == STATE_PRESENT
    assert result.visible is True
    assert result.absent_for_s == 0.0


def test_none_holds_present_until_hold_elapses():
    """Không thấy người: vẫn 'có mặt' cho tới khi qua ``absent_hold_s``."""
    clock = _FakeClock()
    tracker = PresenceTracker(absent_hold_s=3.0, clock=clock)
    tracker.update(_pose(0.9))

    clock.advance(1.0)
    early = tracker.update(None)
    assert early.present is True
    assert early.visible is False
    assert early.state == STATE_PRESENT

    clock.advance(1.9)  # vắng 1.9 giây liên tục
    still = tracker.update(None)
    assert still.present is True

    clock.advance(1.2)  # vắng 3.1 giây liên tục
    late = tracker.update(None)
    assert late.present is False
    assert late.state == STATE_ABSENT
    assert late.absent_for_s >= 3.0


def test_absent_hold_zero_reports_immediately():
    clock = _FakeClock()
    tracker = PresenceTracker(absent_hold_s=0.0, clock=clock)

    result = tracker.update(None)

    assert result.present is False


def test_absent_accumulator_resets_when_person_returns():
    """Một khung thấy người giữa chuỗi vắng phải xoá bộ đếm vắng."""
    clock = _FakeClock()
    tracker = PresenceTracker(absent_hold_s=3.0, clock=clock)

    tracker.update(None)
    clock.advance(2.5)
    tracker.update(None)
    tracker.update(_pose(0.9))  # thấy lại

    clock.advance(2.5)
    result = tracker.update(None)  # mới vắng 2.5 giây liên tục
    assert result.present is True


def test_heads_down_but_shoulders_visible_is_not_absent():
    """Ca biên quan trọng nhất: cúi xuống bàn, đầu khuất nhưng vai còn.

    Pose vẫn trả về 17 keypoint với đầu conf thấp; bbox vẫn tồn tại. Chỉ hai
    vai đủ tin cậy — người vẫn phải được coi là ngồi trong khung, kể cả khi
    đã vắng mặt > ``absent_hold_s`` nếu tính nhầm.
    """
    conf = np.zeros(NUM_KEYPOINTS, dtype=np.float32)
    conf[5] = 0.95  # vai trái
    conf[6] = 0.92  # vai phải
    bent = PoseResult(
        xy=np.zeros((NUM_KEYPOINTS, 2), np.float32),
        conf=conf,
        bbox=np.array([0, 0, 100, 100], np.float32),
    )
    clock = _FakeClock()
    tracker = PresenceTracker(absent_hold_s=1.0, clock=clock)

    for _ in range(5):
        result = tracker.update(bent)
        clock.advance(1.0)

    assert result.present is True
    assert result.upper_keypoints == 2


def test_only_one_upper_keypoint_is_not_enough():
    """Một keypoint lẻ (có thể là nhiễu) không đủ kết luận còn người."""
    conf = np.zeros(NUM_KEYPOINTS, dtype=np.float32)
    conf[0] = 0.99  # chỉ có mũi
    noisy = PoseResult(
        xy=np.zeros((NUM_KEYPOINTS, 2), np.float32),
        conf=conf,
        bbox=np.zeros(4, np.float32),
    )
    clock = _FakeClock()
    tracker = PresenceTracker(absent_hold_s=0.0, clock=clock)

    assert tracker.update(noisy).present is False


def test_broken_input_stream_does_not_crash():
    """Chuỗi dữ liệu hỏng xen kẽ không được làm sập tracker."""
    clock = _FakeClock()
    tracker = PresenceTracker(absent_hold_s=2.0, clock=clock)

    for item in (
        _pose(0.9),
        None,
        object(),
        PoseResult(xy=np.zeros((0, 2)), conf=np.zeros(0), bbox=np.zeros(4)),
        PoseResult(xy=np.zeros((17, 2)), conf=np.full(17, np.nan), bbox=np.zeros(4)),
        _pose(0.0),
    ):
        result = tracker.update(item)
        clock.advance(0.5)

    assert result.present in (True, False)  # chỉ cần không ném lỗi


@pytest.mark.parametrize(
    "kwargs",
    [
        {"absent_hold_s": -1.0},
        {"absent_hold_s": float("nan")},
        {"absent_hold_s": float("inf")},
        {"kp_conf_min": -0.1},
        {"min_upper_keypoints": -1},
        {"min_upper_keypoints": 8},
    ],
)
def test_invalid_parameters_rejected(kwargs):
    with pytest.raises(ValueError):
        PresenceTracker(clock=_FakeClock(), **kwargs)
