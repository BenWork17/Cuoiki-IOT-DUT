"""Unit test cho ``state.py`` và ``calibration.py`` (spec v2 §5.4, §5.6, §9).

Toàn bộ mốc thời gian đi qua một đồng hồ giả (:class:`FakeClock`) rồi mới
truyền vào máy trạng thái; module không tự đọc ``time`` nên test tất định,
không phải ``sleep``. Quy ước: :func:`run_for` nhích đồng hồ theo bước ``dt``
rồi nạp một khung ở mỗi mốc, nên ``run_for(6)`` tạo khung ở các giây 1..6.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from posture_monitor.calibration import (  # noqa: E402
    MIN_VALID_FRAMES,
    CalibrationError,
    check_environment,
    compute_baseline,
    load,
    save,
)
from posture_monitor.classifier import (  # noqa: E402
    ABSENT,
    GOOD,
    HEAD_DOWN,
    TOO_CLOSE,
)
from posture_monitor.config import TimingConfig  # noqa: E402
from posture_monitor.features import Features  # noqa: E402
from posture_monitor.state import (  # noqa: E402
    EVENT_ABSENT_RESET,
    EVENT_ALERT_END,
    EVENT_ALERT_START,
    EVENT_BREAK,
    EVENT_DROWSY,
    EVENT_ESCALATE,
    STATE_ABSENT,
    STATE_BAD,
    STATE_GOOD,
    STATE_WARN,
    StateMachine,
    Smoother,
)

TIMING = TimingConfig()  # bad_hold 5, good_hold 2, cooldown 30, escalate 60, ...
BAD = frozenset({HEAD_DOWN})
GOOD_SET = frozenset({GOOD})
ABSENT_SET = frozenset({ABSENT})


class FakeClock:
    """Đồng hồ giả: chỉ nhích khi test gọi :meth:`advance`."""

    def __init__(self, start: float = 0.0):
        self.now = float(start)

    def advance(self, seconds: float) -> float:
        self.now += seconds
        return self.now


def make_machine(timing=None):
    return StateMachine(timing or TimingConfig()), FakeClock()


def run_collecting(machine, clock, labels, duration, dt=1.0, score=50.0):
    """Như :func:`run_for` nhưng trả ``(update cuối, mọi sự kiện đã sinh)``.

    Cần bản này cho các mốc chỉ vượt ngưỡng đúng một lần (leo thang,
    DROWSY): sự kiện rơi vào một khung giữa chuỗi, không phải khung cuối.
    """
    update = None
    collected = []
    remaining = float(duration)
    while remaining > 1e-9:
        update = machine.update(clock.now, labels, score)
        collected.extend(update.events)
        clock.advance(dt)
        remaining -= dt
    return update, collected


def run_for(machine, clock, labels, duration, dt=1.0, score=50.0):
    """Nạp khung ở thời điểm hiện tại rồi nhích ``dt``, lặp ``duration/dt`` lần.

    Nghĩa là ``run_for(..., 6)`` nạp khung ở các giây 0..5 và để đồng hồ ở
    giây 6. Nạp trước khi nhích giúp khung đầu tiên trùng mốc thời gian mà
    test đang đứng, không lệch một bước.
    """
    update, _ = run_collecting(
        machine, clock, labels, duration, dt=dt, score=score
    )
    return update


def events_of(update, event_type):
    return [event for event in update.events if event.type == event_type]


def raise_alert(machine, clock):
    """Chạy quá ``bad_hold_s`` với HEAD_DOWN để mở một đợt cảnh báo."""
    run_for(machine, clock, BAD, TIMING.bad_hold_s + 1)
    assert machine.active_labels == (HEAD_DOWN,)


# ---------------------------------------------------------------------------
# Hold: chỉ cảnh báo khi nhãn xấu duy trì đủ bad_hold_s
# ---------------------------------------------------------------------------

def test_bad_label_below_hold_stays_warn_without_alert():
    machine, clock = make_machine()
    update = run_for(machine, clock, BAD, 4)  # 4 khung → 3 s liên tục
    assert update.state == STATE_WARN
    assert events_of(update, EVENT_ALERT_START) == []
    assert machine.active_labels == ()


def test_bad_label_at_hold_raises_alert():
    machine, clock = make_machine()
    run_for(machine, clock, BAD, TIMING.bad_hold_s - 1)  # 4 s liên tục
    assert machine.active_labels == ()

    clock.advance(1.0)  # đúng bad_hold_s
    update = machine.update(clock.now, BAD, 40.0)

    starts = events_of(update, EVENT_ALERT_START)
    assert len(starts) == 1
    assert starts[0].label == HEAD_DOWN
    assert starts[0].alert is True
    assert update.state == STATE_BAD
    assert update.alerts == (starts[0],)


def test_hold_is_broken_by_a_good_frame():
    """Một khung tốt chen vào khi chưa đủ hold → hủy đợt, phải đếm lại."""
    machine, clock = make_machine()
    run_for(machine, clock, BAD, 4)
    run_for(machine, clock, GOOD_SET, 1)      # phá hold
    update = run_for(machine, clock, BAD, 4)  # đếm lại từ đầu: 3 s

    assert events_of(update, EVENT_ALERT_START) == []
    assert machine.active_labels == ()


def test_absent_frames_also_break_bad_hold():
    machine, clock = make_machine()
    run_for(machine, clock, BAD, 4)
    update = run_for(machine, clock, ABSENT_SET, 1)
    assert update.state == STATE_ABSENT

    update = run_for(machine, clock, BAD, 4)
    assert events_of(update, EVENT_ALERT_START) == []
    assert machine.active_labels == ()


# ---------------------------------------------------------------------------
# Hysteresis: kết thúc cần good_hold_s liên tục
# ---------------------------------------------------------------------------

def test_alert_does_not_end_before_good_hold():
    machine, clock = make_machine()
    raise_alert(machine, clock)

    update = run_for(machine, clock, GOOD_SET, 1)  # 1 s < 2 s
    assert events_of(update, EVENT_ALERT_END) == []
    assert update.state == STATE_BAD
    assert machine.active_labels == (HEAD_DOWN,)


def test_alert_ends_after_good_hold():
    machine, clock = make_machine()
    raise_alert(machine, clock)
    run_for(machine, clock, GOOD_SET, 1)
    clock.advance(1.0)  # đúng good_hold_s
    update = machine.update(clock.now, GOOD_SET, 95.0)

    ends = events_of(update, EVENT_ALERT_END)
    assert len(ends) == 1
    assert ends[0].label == HEAD_DOWN
    assert update.state == STATE_GOOD
    assert machine.active_labels == ()


def test_alert_survives_a_single_flapping_bad_frame():
    """Hysteresis: một khung xấu chen vào phải làm lại đồng hồ kết thúc."""
    machine, clock = make_machine()
    raise_alert(machine, clock)
    run_for(machine, clock, GOOD_SET, 1)
    clock.advance(1.0)
    machine.update(clock.now, BAD, 40.0)      # reset good_since

    update = run_for(machine, clock, GOOD_SET, 1)
    assert events_of(update, EVENT_ALERT_END) == []
    assert machine.active_labels == (HEAD_DOWN,)


# ---------------------------------------------------------------------------
# Cooldown
# ---------------------------------------------------------------------------

def test_same_label_not_realerted_within_cooldown():
    machine, clock = make_machine()
    raise_alert(machine, clock)               # cảnh báo ở giây 6
    run_for(machine, clock, GOOD_SET, 3)      # đóng sự kiện

    update = run_for(machine, clock, BAD, TIMING.bad_hold_s + 1)
    starts = events_of(update, EVENT_ALERT_START)
    assert len(starts) == 1
    assert starts[0].alert is False            # vẫn ghi nhận, không báo
    assert update.alerts == ()
    assert machine.active_labels == (HEAD_DOWN,)


def test_same_label_realerted_after_cooldown():
    machine, clock = make_machine()
    raise_alert(machine, clock)
    run_for(machine, clock, GOOD_SET, 3)
    clock.advance(TIMING.alert_cooldown_s)     # cooldown tính từ lúc cảnh báo

    update = run_for(machine, clock, BAD, TIMING.bad_hold_s + 1)
    starts = events_of(update, EVENT_ALERT_START)
    assert len(starts) == 1
    assert starts[0].alert is True
    assert len(update.alerts) == 1


def test_different_labels_do_not_share_cooldown():
    machine, clock = make_machine()
    raise_alert(machine, clock)                # cooldown cho HEAD_DOWN

    update = run_for(
        machine, clock, frozenset({TOO_CLOSE}), TIMING.bad_hold_s + 1
    )
    starts = events_of(update, EVENT_ALERT_START)
    assert len(starts) == 1
    assert starts[0].label == TOO_CLOSE
    assert starts[0].alert is True


# ---------------------------------------------------------------------------
# Leo thang
# ---------------------------------------------------------------------------

def test_escalates_once_after_escalate_after_s():
    machine, clock = make_machine()
    raise_alert(machine, clock)
    _, events = run_collecting(
        machine, clock, BAD, int(TIMING.escalate_after_s) + 1
    )

    escalations = [e for e in events if e.type == EVENT_ESCALATE]
    assert len(escalations) == 1
    assert escalations[0].label == HEAD_DOWN
    assert escalations[0].level == 2

    _, later = run_collecting(machine, clock, BAD, 5)
    assert [e for e in later if e.type == EVENT_ESCALATE] == []


def test_no_escalation_before_escalate_after_s():
    machine, clock = make_machine()
    raise_alert(machine, clock)
    _, events = run_collecting(machine, clock, BAD, 20)
    assert [e for e in events if e.type == EVENT_ESCALATE] == []


def test_escalation_blocked_by_cooldown_is_reported_but_not_alerted():
    machine, clock = make_machine(TimingConfig(alert_cooldown_s=600.0))
    raise_alert(machine, clock)
    update, events = run_collecting(
        machine, clock, BAD, int(TIMING.escalate_after_s) + 1
    )
    escalations = [e for e in events if e.type == EVENT_ESCALATE]
    assert len(escalations) == 1
    assert escalations[0].alert is False
    assert all(event.alert is False for event in events)
    assert update.alerts == ()


# ---------------------------------------------------------------------------
# DROWSY_SUSPECT và nhắc nghỉ
# ---------------------------------------------------------------------------

def test_drowsy_suspect_fires_once_after_drowsy_hold():
    machine, clock = make_machine()
    update = run_for(machine, clock, BAD, int(TIMING.drowsy_hold_s))
    assert events_of(update, EVENT_DROWSY) == []

    clock.advance(1.0)  # đúng drowsy_hold_s
    update = machine.update(clock.now, BAD, 30.0)
    assert len(events_of(update, EVENT_DROWSY)) == 1

    update = run_for(machine, clock, BAD, 3)
    assert events_of(update, EVENT_DROWSY) == []


def test_drowsy_flag_resets_when_head_comes_back_up():
    machine, clock = make_machine()
    run_for(machine, clock, BAD, int(TIMING.drowsy_hold_s) + 1)
    run_for(machine, clock, GOOD_SET, 1)
    _, events = run_collecting(
        machine, clock, BAD, int(TIMING.drowsy_hold_s) + 1
    )
    assert len([e for e in events if e.type == EVENT_DROWSY]) == 1


def test_break_reminder_after_sitting_long_enough():
    """break_after_min đổi sang giây; không chờ thật 45 phút."""
    machine, clock = make_machine(TimingConfig(break_after_min=0.1))  # 6 s
    update = run_for(machine, clock, GOOD_SET, 7)

    breaks = events_of(update, EVENT_BREAK)
    assert len(breaks) == 1
    assert update.sitting_s >= 6.0

    update = run_for(machine, clock, GOOD_SET, 2)
    assert events_of(update, EVENT_BREAK) == []


# ---------------------------------------------------------------------------
# Vắng mặt
# ---------------------------------------------------------------------------

def test_absent_state_and_reset_after_absent_reset_s():
    machine, clock = make_machine(TimingConfig(absent_reset_s=10.0))
    run_for(machine, clock, GOOD_SET, 20)
    sitting_before = machine.sitting_s
    assert sitting_before > 0

    update = run_for(machine, clock, ABSENT_SET, 1)
    assert update.state == STATE_ABSENT
    # Thời gian vắng không được cộng vào thời gian ngồi.
    assert machine.sitting_s == pytest.approx(sitting_before)

    update = run_for(machine, clock, ABSENT_SET, 10)
    resets = events_of(update, EVENT_ABSENT_RESET)
    assert len(resets) == 1
    assert machine.sitting_s == 0.0


def test_absence_just_under_reset_does_not_reset():
    machine, clock = make_machine(TimingConfig(absent_reset_s=10.0))
    run_for(machine, clock, GOOD_SET, 20)
    sitting_before = machine.sitting_s
    update = run_for(machine, clock, ABSENT_SET, 9)
    assert events_of(update, EVENT_ABSENT_RESET) == []
    assert machine.sitting_s == pytest.approx(sitting_before)


def test_absence_shorter_than_reset_keeps_sitting_counter():
    machine, clock = make_machine(TimingConfig(absent_reset_s=10.0))
    run_for(machine, clock, GOOD_SET, 20)
    sitting_before = machine.sitting_s

    run_for(machine, clock, ABSENT_SET, 5)
    run_for(machine, clock, GOOD_SET, 1)
    assert machine.sitting_s == pytest.approx(sitting_before + 1.0)


def test_absence_closes_open_alert_on_reset():
    machine, clock = make_machine(TimingConfig(absent_reset_s=10.0))
    raise_alert(machine, clock)
    run_for(machine, clock, ABSENT_SET, 1)
    update = run_for(machine, clock, ABSENT_SET, 10)

    ends = events_of(update, EVENT_ALERT_END)
    assert any(event.label == HEAD_DOWN for event in ends)
    assert machine.active_labels == ()


def test_absence_keeps_open_alert_when_it_ends_before_reset():
    """Sự kiện đang mở không bị đóng chỉ vì người dùng vắng mặt ngắn."""
    machine, clock = make_machine(TimingConfig(absent_reset_s=10.0))
    raise_alert(machine, clock)
    update = run_for(machine, clock, ABSENT_SET, 3)
    assert events_of(update, EVENT_ALERT_END) == []
    assert machine.active_labels == (HEAD_DOWN,)


# ---------------------------------------------------------------------------
# Hợp đồng đồng hồ
# ---------------------------------------------------------------------------

def test_clock_going_backwards_is_rejected():
    machine, clock = make_machine()
    clock.advance(10.0)
    machine.update(clock.now, GOOD_SET, 100.0)
    with pytest.raises(ValueError):
        machine.update(clock.now - 1.0, GOOD_SET, 100.0)


def test_negative_timing_is_rejected():
    with pytest.raises(ValueError):
        StateMachine(TimingConfig(bad_hold_s=-1.0))


def test_score_is_clamped():
    machine, clock = make_machine()
    clock.advance(1.0)
    assert machine.update(clock.now, GOOD_SET, 500.0).score == 100.0
    assert machine.update(clock.now, GOOD_SET, -20.0).score == 0.0


def test_reset_clears_all_counters():
    machine, clock = make_machine()
    raise_alert(machine, clock)
    machine.reset()
    assert machine.active_labels == ()
    assert machine.sitting_s == 0.0

    update = run_for(machine, clock, BAD, 1)
    assert update.state == STATE_WARN


# ---------------------------------------------------------------------------
# Smoother
# ---------------------------------------------------------------------------

def make_frame(**values) -> Features:
    merged = {name: None for name in ("shoulder_width", "head_height", "lean_x")}
    merged.update(values)
    return Features(view="front", person=True, values=merged)


def test_smoother_takes_median_within_window():
    smoother = Smoother(window_s=1.0)
    smoother.push(0.0, make_frame(head_height=0.1))
    smoother.push(0.5, make_frame(head_height=0.5))
    result = smoother.push(1.0, make_frame(head_height=0.9))
    assert result["head_height"] == pytest.approx(0.5)


def test_smoother_drops_samples_outside_window():
    smoother = Smoother(window_s=1.0)
    smoother.push(0.0, make_frame(head_height=0.1))
    result = smoother.push(5.0, make_frame(head_height=0.9))
    assert result["head_height"] == pytest.approx(0.9)


def test_smoother_ignores_none_samples():
    smoother = Smoother(window_s=1.0)
    smoother.push(0.0, make_frame(head_height=None))
    result = smoother.push(0.5, make_frame(head_height=0.4))
    assert result["head_height"] == pytest.approx(0.4)


def test_smoother_person_true_if_any_frame_sees_person():
    smoother = Smoother(window_s=1.0)
    smoother.push(0.0, Features(view="front", person=False, values={}))
    result = smoother.push(0.5, make_frame(head_height=0.4))
    assert result.person is True


def test_smoother_rejects_negative_window():
    with pytest.raises(ValueError):
        Smoother(window_s=-0.1)


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------

def calibration_frames(count=MIN_VALID_FRAMES, view="front", width=200.0):
    return [
        Features(
            view=view,
            person=True,
            values={
                "shoulder_width": width + offset,
                "shoulder_tilt_deg": 0.0,
                "head_height": 0.5,
                "closeness": 1.0,
                "lean_x": 0.0,
                "head_tilt_deg": None,
                "head_yaw": None,
                "neck_angle": None,
                "torso_angle": None,
                "shoulder_mid_x": 300.0,
            },
        )
        for offset in range(count)
    ]


def test_baseline_uses_median_not_mean():
    frames = calibration_frames(count=20)
    frames[0] = Features(
        view="front",
        person=True,
        values={**frames[0].values, "shoulder_width": 10_000.0},
    )
    baseline = compute_baseline(frames, view="front", width=640, height=480)
    # Trung vị của các giá trị còn lại (offset 1..19) là 210.5; trung bình sẽ
    # bị một khung ngoại lai kéo lên gần 700.
    assert baseline["shoulder_width"] == pytest.approx(210.5)


def test_baseline_requires_minimum_valid_frames():
    frames = calibration_frames(count=MIN_VALID_FRAMES - 1)
    with pytest.raises(CalibrationError, match="calibrate"):
        compute_baseline(frames, view="front", width=640, height=480)


def test_baseline_error_mentions_camera_guidance():
    with pytest.raises(CalibrationError, match="hai vai"):
        compute_baseline(
            calibration_frames(count=1), view="front", width=640, height=480
        )


def test_baseline_ignores_frames_without_person_or_shoulders():
    frames = calibration_frames(count=MIN_VALID_FRAMES) + [
        Features(view="front", person=False, values={}),
        make_frame(shoulder_width=None),
    ]
    baseline = compute_baseline(frames, view="front", width=640, height=480)
    assert baseline.frames == MIN_VALID_FRAMES


def test_baseline_ignores_frames_from_another_view():
    frames = calibration_frames(count=MIN_VALID_FRAMES)
    frames += calibration_frames(count=5, view="side")
    baseline = compute_baseline(frames, view="front", width=640, height=480)
    assert baseline.frames == MIN_VALID_FRAMES


def test_baseline_leaves_missing_feature_as_none():
    baseline = compute_baseline(
        calibration_frames(), view="front", width=640, height=480
    )
    assert baseline["head_tilt_deg"] is None


def test_baseline_rejects_bad_view():
    with pytest.raises(ValueError):
        compute_baseline(calibration_frames(), view="top", width=640, height=480)


def test_baseline_roundtrips_through_json(tmp_path):
    baseline = compute_baseline(
        calibration_frames(), view="front", width=640, height=480
    )
    path = save(baseline, tmp_path / "calibration.json")
    again = load(path)

    assert again.view == baseline.view
    assert (again.width, again.height) == (640, 480)
    assert again["shoulder_width"] == pytest.approx(baseline["shoulder_width"])
    assert again["head_tilt_deg"] is None
    assert again.created_at == baseline.created_at


def test_saved_json_contains_required_fields(tmp_path):
    baseline = compute_baseline(
        calibration_frames(), view="front", width=640, height=480
    )
    path = save(baseline, tmp_path / "calibration.json")
    raw = json.loads(path.read_text(encoding="utf-8"))

    assert set(raw) == {"version", "baseline", "camera", "created_at", "frames"}
    assert raw["camera"] == {"view": "front", "width": 640, "height": 480}
    assert raw["created_at"]


def test_save_creates_parent_directory(tmp_path):
    baseline = compute_baseline(
        calibration_frames(), view="front", width=640, height=480
    )
    path = save(baseline, tmp_path / "sau" / "calibration.json")
    assert path.is_file()


def test_load_missing_file_gives_actionable_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="calibrate"):
        load(tmp_path / "khong_co.json")


def test_load_rejects_wrong_version(tmp_path):
    path = tmp_path / "calibration.json"
    path.write_text(json.dumps({"version": 99}), encoding="utf-8")
    with pytest.raises(CalibrationError):
        load(path)


def test_load_rejects_corrupt_json(tmp_path):
    path = tmp_path / "calibration.json"
    path.write_text("{ khong phai json", encoding="utf-8")
    with pytest.raises(CalibrationError):
        load(path)


def test_check_environment_warns_on_resolution_change():
    baseline = compute_baseline(
        calibration_frames(), view="front", width=640, height=480
    )
    warnings = check_environment(baseline, view="front", width=1280, height=720)
    assert any("Độ phân giải" in warning for warning in warnings)


def test_check_environment_warns_on_view_change():
    baseline = compute_baseline(
        calibration_frames(), view="front", width=640, height=480
    )
    warnings = check_environment(baseline, view="side", width=640, height=480)
    assert any("Chế độ camera" in warning for warning in warnings)


def test_check_environment_is_silent_when_matching():
    baseline = compute_baseline(
        calibration_frames(), view="front", width=640, height=480
    )
    assert check_environment(baseline, view="front", width=640, height=480) == []
