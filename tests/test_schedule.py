"""Kiểm thử giờ học quy định và lớp quyết định cảnh báo (``schedule.py``).

Mọi thời điểm trong file này đều có ``tzinfo`` tường minh
(``timezone(timedelta(hours=7))``, giống máy Pi) hoặc cố ý naive ở đúng nơi
cần kiểm tra hành vi naive. Không dùng mốc thời gian "giờ địa phương của máy"
nào, nên kết quả giống nhau trên Windows (UTC+7) và trên Pi
(``Asia/Ho_Chi_Minh``).

Không dùng ``datetime.now()`` hay ``time.sleep``: ``now`` luôn được truyền
vào, cooldown đo bằng giá trị datetime.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from posture_monitor.schedule import (  # noqa: E402
    KIND_LEAVE_FRAME,
    KIND_PHONE,
    KIND_STRANGER,
    KindSettings,
    ScheduleConfig,
    ScheduleError,
    TimeWindow,
    is_active,
    parse_clock,
    parse_days,
    parse_window,
    should_alert,
)

#: Múi giờ của Pi (Asia/Ho_Chi_Minh, UTC+7). Dùng tường minh để test không
#: phụ thuộc cấu hình múi giờ của máy chạy.
TZ7 = timezone(timedelta(hours=7))

#: Thứ Hai 2026-10-05. Thứ Bảy 2026-10-10, Chủ nhật 2026-10-11.
MONDAY = (2026, 10, 5)
SATURDAY = (2026, 10, 10)
SUNDAY = (2026, 10, 11)


def at(
    day: tuple[int, int, int], hour: int, minute: int = 0, second: int = 0, tz=TZ7
) -> datetime:
    """Datetime có timezone tường minh (mặc định UTC+7)."""
    return datetime(*day, hour, minute, second, tzinfo=tz)


def weekday_schedule(*windows: TimeWindow, enabled: bool = True) -> ScheduleConfig:
    return ScheduleConfig(enabled=enabled, windows=windows)


def evening_window() -> TimeWindow:
    """19:00–21:30 các ngày trong tuần (thứ Hai tới thứ Sáu)."""
    return TimeWindow(
        days=("mon", "tue", "wed", "thu", "fri"),
        start=datetime(2000, 1, 1, 19, 0).time(),
        end=datetime(2000, 1, 1, 21, 30).time(),
    )


def overnight_window() -> TimeWindow:
    """22:00–01:00 bắt đầu thứ Sáu (qua đêm sang thứ Bảy)."""
    return TimeWindow(
        days=("fri",),
        start=datetime(2000, 1, 1, 22, 0).time(),
        end=datetime(2000, 1, 1, 1, 0).time(),
    )


# --------------------------------------------------------------------------
# Giờ trong / ngoài khung
# --------------------------------------------------------------------------


def test_inside_window_is_active() -> None:
    schedule = weekday_schedule(evening_window())
    assert is_active(schedule, at(MONDAY, 19, 0)) is True
    assert is_active(schedule, at(MONDAY, 20, 15)) is True
    # 21:30 là mốc kết thúc, tính là ngoài khung.
    assert is_active(schedule, at(MONDAY, 21, 29, 59)) is True


def test_outside_window_is_not_active() -> None:
    schedule = weekday_schedule(evening_window())
    assert is_active(schedule, at(MONDAY, 18, 59)) is False
    assert is_active(schedule, at(MONDAY, 12, 0)) is False
    assert is_active(schedule, at(MONDAY, 21, 30)) is False
    assert is_active(schedule, at(MONDAY, 23, 0)) is False


def test_window_end_is_exclusive() -> None:
    schedule = weekday_schedule(evening_window())
    assert is_active(schedule, at(MONDAY, 21, 30)) is False
    assert is_active(schedule, at(MONDAY, 21, 29, 59)) is True


def test_overnight_window_covers_both_sides_of_midnight() -> None:
    """22:00 thứ Sáu – 01:00 thứ Bảy: 23:30 và 00:30 đều đang học."""
    schedule = weekday_schedule(overnight_window())
    friday = (2026, 10, 9)
    saturday = SATURDAY
    assert is_active(schedule, at(friday, 23, 30)) is True
    assert is_active(schedule, at(saturday, 0, 30)) is True
    assert is_active(schedule, at(friday, 22, 0)) is True
    assert is_active(schedule, at(saturday, 0, 59)) is True
    # 01:00 thứ Bảy là hết giờ; 21:59 thứ Sáu là chưa tới giờ.
    assert is_active(schedule, at(saturday, 1, 0)) is False
    assert is_active(schedule, at(friday, 21, 59)) is False


def test_overnight_window_does_not_leak_to_start_day_evening() -> None:
    """Khung thứ Sáu 22:00–01:00 không làm thứ Bảy 23:30 thành giờ học."""
    schedule = weekday_schedule(overnight_window())
    assert is_active(schedule, at(SATURDAY, 23, 30)) is False
    assert is_active(schedule, at(SATURDAY, 0, 30)) is True


def test_wrong_weekday_is_not_active() -> None:
    """Chủ nhật không nằm trong [mon..fri] nên ngoài giờ."""
    schedule = weekday_schedule(evening_window())
    assert is_active(schedule, at(SATURDAY, 20, 0)) is False
    assert is_active(schedule, at(SUNDAY, 20, 0)) is False


def test_multiple_windows_are_unioned() -> None:
    weekend = TimeWindow(
        days=("sat", "sun"),
        start=datetime(2000, 1, 1, 8, 0).time(),
        end=datetime(2000, 1, 1, 11, 0).time(),
    )
    schedule = weekday_schedule(evening_window(), weekend)
    assert is_active(schedule, at(MONDAY, 20, 0)) is True
    assert is_active(schedule, at(SUNDAY, 9, 0)) is True
    assert is_active(schedule, at(SUNDAY, 20, 0)) is False


def test_disabled_schedule_never_restricts_time() -> None:
    """Tắt giờ học = cảnh báo mọi lúc, không phải tắt hết cảnh báo."""
    schedule = weekday_schedule(evening_window(), enabled=False)
    assert is_active(schedule, at(SUNDAY, 3, 0)) is True


def test_empty_enabled_schedule_and_no_windows() -> None:
    schedule = ScheduleConfig(enabled=False, windows=())
    assert is_active(schedule, at(SUNDAY, 3, 0)) is True


# --------------------------------------------------------------------------
# Naive datetime và tzinfo tường minh
# --------------------------------------------------------------------------


def test_naive_now_is_read_as_local_wall_clock() -> None:
    """``now`` naive đọc theo giờ trên mặt đồng hồ, không đổi múi giờ."""
    schedule = weekday_schedule(evening_window())
    naive = datetime(2026, 10, 5, 20, 0)  # thứ Hai, không tzinfo
    assert is_active(schedule, naive) is True
    assert is_active(schedule, datetime(2026, 10, 5, 22, 0)) is False


def test_explicit_tz_is_honoured_not_converted() -> None:
    """Cùng một giờ hiển thị nhưng tz khác nhau: kết quả như nhau.

    Hàm chỉ đọc giờ trên mặt đồng hồ của ``now``; nó không đổi sang múi giờ
    của máy, nên 20:00 UTC+7 và 20:00 UTC có cùng kết quả.
    """
    schedule = weekday_schedule(evening_window())
    assert is_active(schedule, at(MONDAY, 20, 0, tz=TZ7)) is True
    assert is_active(schedule, at(MONDAY, 20, 0, tz=timezone.utc)) is True
    assert is_active(schedule, at(MONDAY, 3, 0, tz=timezone.utc)) is False


# --------------------------------------------------------------------------
# Cooldown
# --------------------------------------------------------------------------


def test_should_alert_inside_window_returns_decision() -> None:
    schedule = weekday_schedule(evening_window())
    decision = should_alert(
        schedule,
        at(MONDAY, 20, 0),
        held={KIND_LEAVE_FRAME: 30.0},
        last_alert_at={},
    )
    assert decision is not None
    assert decision.kind == KIND_LEAVE_FRAME
    assert "Rời khung hình" in decision.reason


def test_should_alert_outside_window_returns_none() -> None:
    schedule = weekday_schedule(evening_window())
    assert (
        should_alert(
            schedule, at(SUNDAY, 20, 0), held={KIND_LEAVE_FRAME: 300.0}
        )
        is None
    )


def test_should_alert_requires_hold_time() -> None:
    schedule = weekday_schedule(evening_window())
    settings = {KIND_LEAVE_FRAME: KindSettings(hold_s=10.0, cooldown_s=0.0)}
    assert (
        should_alert(
            schedule,
            at(MONDAY, 20, 0),
            held={KIND_LEAVE_FRAME: 5.0},
            kinds=settings,
        )
        is None
    )
    assert (
        should_alert(
            schedule,
            at(MONDAY, 20, 0),
            held={KIND_LEAVE_FRAME: 10.0},
            kinds=settings,
        )
        is not None
    )


def test_cooldown_blocks_repeat_then_allows_after_expiry() -> None:
    schedule = weekday_schedule(evening_window())
    settings = {KIND_PHONE: KindSettings(cooldown_s=120.0, hold_s=0.0)}
    now = at(MONDAY, 20, 0)
    last = now

    # Ngay sau khi đã cảnh báo: còn trong cooldown.
    assert (
        should_alert(
            schedule,
            now + timedelta(seconds=60),
            held={KIND_PHONE: 30.0},
            last_alert_at={KIND_PHONE: last},
            kinds=settings,
        )
        is None
    )
    # Vừa hết cooldown: được cảnh báo lại.
    decision = should_alert(
        schedule,
        now + timedelta(seconds=120),
        held={KIND_PHONE: 30.0},
        last_alert_at={KIND_PHONE: last},
        kinds=settings,
    )
    assert decision is not None
    assert decision.kind == KIND_PHONE


def test_cooldown_is_per_kind() -> None:
    """Đang cooldown "dien thoai" không được chặn cảnh báo "roi khung"."""
    schedule = weekday_schedule(evening_window())
    settings = {
        KIND_LEAVE_FRAME: KindSettings(cooldown_s=600.0, hold_s=0.0),
        KIND_PHONE: KindSettings(cooldown_s=600.0, hold_s=0.0),
    }
    now = at(MONDAY, 20, 0)
    decision = should_alert(
        schedule,
        now + timedelta(seconds=10),
        held={KIND_PHONE: 20.0, KIND_LEAVE_FRAME: 20.0},
        last_alert_at={KIND_PHONE: now},  # chỉ điện thoại đang cooldown
        kinds=settings,
    )
    assert decision is not None
    assert decision.kind == KIND_LEAVE_FRAME


def test_disabling_one_kind_does_not_disable_others() -> None:
    schedule = weekday_schedule(evening_window())
    settings = {
        KIND_LEAVE_FRAME: KindSettings(enabled=False, hold_s=0.0),
        KIND_PHONE: KindSettings(enabled=True, cooldown_s=0.0, hold_s=0.0),
    }
    decision = should_alert(
        schedule,
        at(MONDAY, 20, 0),
        held={KIND_LEAVE_FRAME: 60.0, KIND_PHONE: 20.0},
        kinds=settings,
    )
    assert decision is not None
    assert decision.kind == KIND_PHONE


def test_all_kinds_disabled_returns_none() -> None:
    schedule = weekday_schedule(evening_window())
    settings = {kind: KindSettings(enabled=False) for kind in (
        KIND_LEAVE_FRAME,
        KIND_PHONE,
        KIND_STRANGER,
    )}
    assert (
        should_alert(
            schedule,
            at(MONDAY, 20, 0),
            held={KIND_LEAVE_FRAME: 60.0, KIND_PHONE: 60.0, KIND_STRANGER: 60.0},
            kinds=settings,
        )
        is None
    )


def test_kind_priority_order() -> None:
    """Nhiều loại cùng đủ điều kiện: trả loại đứng trước trong ALERT_KINDS."""
    schedule = weekday_schedule(evening_window())
    settings = {
        KIND_LEAVE_FRAME: KindSettings(cooldown_s=0.0, hold_s=0.0),
        KIND_PHONE: KindSettings(cooldown_s=0.0, hold_s=0.0),
    }
    decision = should_alert(
        schedule,
        at(MONDAY, 20, 0),
        held={KIND_PHONE: 20.0, KIND_LEAVE_FRAME: 20.0},
        kinds=settings,
    )
    assert decision is not None
    assert decision.kind == KIND_LEAVE_FRAME


def test_mixed_tzinfo_raises_value_error() -> None:
    """Trộn naive với có timezone: báo lỗi thay vì đoán múi giờ."""
    schedule = weekday_schedule(evening_window())
    with pytest.raises(ValueError):
        should_alert(
            schedule,
            at(MONDAY, 20, 0),  # có tzinfo
            held={KIND_PHONE: 20.0},
            last_alert_at={KIND_PHONE: datetime(2026, 10, 5, 19, 0)},  # naive
            kinds={KIND_PHONE: KindSettings(cooldown_s=600.0, hold_s=0.0)},
        )


# --------------------------------------------------------------------------
# Nạp cấu hình: báo lỗi lúc nạp, không phải lúc chạy
# --------------------------------------------------------------------------


def test_parse_clock_accepts_valid_time() -> None:
    assert parse_clock("19:00", "x").hour == 19
    assert parse_clock("7:05", "x").minute == 5
    assert parse_clock("23:59", "x").hour == 23


@pytest.mark.parametrize("bad", ["19", "19:0", "24:00", "19:60", "19h00", "", "  "])
def test_parse_clock_rejects_bad_format(bad: str) -> None:
    with pytest.raises(ScheduleError):
        parse_clock(bad, "schedule.windows[0].start")


def test_parse_clock_names_the_key_and_yaml_int_trap() -> None:
    with pytest.raises(ScheduleError) as excinfo:
        parse_clock(1140, "schedule.windows[0].start")
    message = str(excinfo.value)
    assert "schedule.windows[0].start" in message
    assert "19:00" in message  # gợi ý đặt trong ngoặc kép


def test_parse_days_accepts_case_and_rejects_unknown() -> None:
    assert parse_days(["Mon", "TUE", "mon"], "x") == ("mon", "tue")
    with pytest.raises(ScheduleError) as excinfo:
        parse_days(["monday"], "schedule.windows[0].days")
    assert "monday" in str(excinfo.value)
    with pytest.raises(ScheduleError):
        parse_days([], "x")


def test_parse_window_rejects_missing_key_and_equal_bounds() -> None:
    with pytest.raises(ScheduleError) as excinfo:
        parse_window({"days": ["mon"], "start": "19:00"}, "schedule.windows[0]")
    assert "end" in str(excinfo.value)

    with pytest.raises(ScheduleError):
        parse_window(
            {"days": ["mon"], "start": "19:00", "end": "19:00"},
            "schedule.windows[0]",
        )


def test_parse_window_builds_valid_window() -> None:
    window = parse_window(
        {"days": ["fri"], "start": "22:00", "end": "01:00"},
        "schedule.windows[0]",
    )
    assert window.days == ("fri",)
    assert window.overnight is True


def test_kind_settings_reject_negative_values() -> None:
    with pytest.raises(ScheduleError):
        KindSettings(cooldown_s=-1.0)
    with pytest.raises(ScheduleError):
        KindSettings(hold_s=-1.0)
