"""Giờ học quy định, chuẩn hoá payload lịch học và quyết định cảnh báo.

Module thuần không phụ thuộc camera, model, DB hay GPIO. Cung cấp cả bộ phân
tích cấu hình lịch học dùng chung cho ``config.yaml`` lẫn HTTP API
``GET/PUT /api/schedule`` để hai nơi không bao giờ lệch quy tắc kiểm tra.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Any, Mapping

DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_DAY_INDEX = {name: index for index, name in enumerate(DAY_NAMES)}

KIND_LEAVE_FRAME = "leave_frame"
KIND_PHONE = "phone"
KIND_STRANGER = "stranger"
ALERT_KINDS = (KIND_LEAVE_FRAME, KIND_PHONE, KIND_STRANGER)

KIND_LABELS = {
    KIND_LEAVE_FRAME: "Rời khung hình",
    KIND_PHONE: "Dùng điện thoại",
    KIND_STRANGER: "Có người lạ",
}

SCHEDULE_KEYS = ("enabled", "windows", "kinds")
_CLOCK_RE = re.compile(r"^(?P<hour>\d{1,2}):(?P<minute>\d{2})$")


class ScheduleError(ValueError):
    """Giờ học cấu hình sai (giờ, thứ, khung giờ hoặc thiết lập loại cảnh báo)."""


@dataclass(frozen=True)
class KindSettings:
    """Thiết lập cho một loại cảnh báo trong giờ học."""

    enabled: bool = True
    cooldown_s: float = 60.0
    hold_s: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ScheduleError(
                f"'enabled' của loại cảnh báo phải là true/false, nhận được "
                f"{self.enabled!r}."
            )
        if self.cooldown_s < 0:
            raise ScheduleError(
                f"'cooldown_s' không được âm, nhận được {self.cooldown_s!r}."
            )
        if self.hold_s < 0:
            raise ScheduleError(f"'hold_s' không được âm, nhận được {self.hold_s!r}.")


DEFAULT_PHONE_HOLD_S = 2.0
DEFAULT_REPEAT_S = 2.0

DEFAULT_KINDS: dict[str, KindSettings] = {
    KIND_LEAVE_FRAME: KindSettings(cooldown_s=DEFAULT_REPEAT_S, hold_s=5.0),
    KIND_PHONE: KindSettings(cooldown_s=DEFAULT_REPEAT_S, hold_s=DEFAULT_PHONE_HOLD_S),
    KIND_STRANGER: KindSettings(cooldown_s=DEFAULT_REPEAT_S, hold_s=5.0),
}


@dataclass(frozen=True)
class TimeWindow:
    """Một khung giờ học trong tuần (hỗ trợ cả khung vắt qua nửa đêm)."""

    days: tuple[str, ...]
    start: time
    end: time

    def __post_init__(self) -> None:
        if not self.days:
            raise ScheduleError("'days' phải có ít nhất một thứ.")
        for day in self.days:
            if day not in _DAY_INDEX:
                raise ScheduleError(
                    f"'{day}' không phải tên thứ hợp lệ; dùng một trong {DAY_NAMES}."
                )
        if self.start == self.end:
            raise ScheduleError(
                f"'start' và 'end' không được trùng nhau ({self.start})."
            )

    @property
    def overnight(self) -> bool:
        return _seconds_of_day(self.start) > _seconds_of_day(self.end)

    def covers(self, moment: datetime) -> bool:
        today = moment.weekday()
        seconds = _seconds_of_day(moment.time())
        start = _seconds_of_day(self.start)
        end = _seconds_of_day(self.end)
        indexes = {_DAY_INDEX[day] for day in self.days}

        if start < end:
            return today in indexes and start <= seconds < end
        if today in indexes and seconds >= start:
            return True
        previous = (today - 1) % 7
        return previous in indexes and seconds < end


@dataclass
class ScheduleConfig:
    """Mục ``schedule``: giờ học quy định và nhịp nhắc theo từng loại cảnh báo."""

    enabled: bool = False
    windows: tuple[TimeWindow, ...] = ()
    kinds: Mapping[str, KindSettings] = field(
        default_factory=lambda: dict(DEFAULT_KINDS)
    )


def _seconds_of_day(moment: time) -> int:
    return moment.hour * 3600 + moment.minute * 60 + moment.second


def _qualify(prefix: str, key: str) -> str:
    return f"{prefix}.{key}" if prefix else key


def parse_clock(value: Any, where: str) -> time:
    """Đọc một giờ dạng ``"HH:MM"``."""
    if isinstance(value, time):
        return value
    if isinstance(value, bool) or not isinstance(value, str):
        hint = ""
        if isinstance(value, int):
            hint = ' (YAML đọc giờ không có ngoặc kép thành số; hãy viết start: "19:00")'
        raise ScheduleError(
            f"'{where}' phải là chuỗi giờ dạng \"HH:MM\", nhận được {value!r}{hint}."
        )
    text = value.strip()
    match = _CLOCK_RE.match(text)
    if match is None:
        raise ScheduleError(
            f"'{where}' = {value!r} sai định dạng giờ; dùng dạng \"HH:MM\" "
            'ví dụ "19:00".'
        )
    hour = int(match.group("hour"))
    minute = int(match.group("minute"))
    if not (0 <= hour <= 23):
        raise ScheduleError(f"'{where}' = {value!r} có giờ ngoài khoảng 0..23.")
    if not (0 <= minute <= 59):
        raise ScheduleError(f"'{where}' = {value!r} có phút ngoài khoảng 0..59.")
    return time(hour, minute)


def parse_days(value: Any, where: str) -> tuple[str, ...]:
    """Đọc danh sách thứ ``[mon, tue, ...]``."""
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise ScheduleError(
            f"'{where}' phải là danh sách thứ, ví dụ [mon, tue, wed]; nhận "
            f"được {value!r}."
        )
    days: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ScheduleError(
                f"'{where}' chứa {item!r} không phải tên thứ dạng chuỗi."
            )
        day = item.strip().lower()
        if day not in _DAY_INDEX:
            raise ScheduleError(
                f"'{where}' có thứ {item!r} không hợp lệ; dùng một trong {DAY_NAMES}."
            )
        if day not in days:
            days.append(day)
    if not days:
        raise ScheduleError(f"'{where}' phải có ít nhất một thứ.")
    return tuple(days)


def parse_window(raw: Any, where: str) -> TimeWindow:
    """Đọc một khung giờ ``{days, start, end}``."""
    if not isinstance(raw, dict):
        raise ScheduleError(
            f"'{where}' phải là một ánh xạ gồm days/start/end, nhận được "
            f"{type(raw).__name__}."
        )
    for key in ("days", "start", "end"):
        if key not in raw or raw[key] is None:
            raise ScheduleError(f"'{where}' thiếu khóa '{key}'.")
    return TimeWindow(
        days=parse_days(raw["days"], f"{where}.days"),
        start=parse_clock(raw["start"], f"{where}.start"),
        end=parse_clock(raw["end"], f"{where}.end"),
    )


def parse_kind_settings(raw: Any, where: str) -> KindSettings:
    """Đọc thiết lập của một loại cảnh báo ``{enabled, cooldown_s, hold_s}``."""
    if raw is None:
        return KindSettings()
    if not isinstance(raw, dict):
        raise ScheduleError(
            f"'{where}' phải là một ánh xạ, nhận được {type(raw).__name__}."
        )
    enabled = raw.get("enabled")
    if enabled is None:
        enabled = KindSettings.enabled
    elif not isinstance(enabled, bool):
        raise ScheduleError(
            f"'{where}.enabled' phải là true/false, nhận được {enabled!r}."
        )
    cooldown = _read_number(raw, "cooldown_s", KindSettings.cooldown_s, where)
    hold = _read_number(raw, "hold_s", KindSettings.hold_s, where)
    return KindSettings(enabled=enabled, cooldown_s=cooldown, hold_s=hold)


def _read_number(
    data: Mapping[str, Any], key: str, default: float, where: str
) -> float:
    if key not in data or data[key] is None:
        return default
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ScheduleError(f"'{where}.{key}' phải là số, nhận được {value!r}.")
    if value < 0:
        raise ScheduleError(f"'{where}.{key}' không được âm, nhận được {value!r}.")
    return float(value)


def parse_schedule_mapping(
    raw: Mapping[str, Any],
    *,
    prefix: str = "schedule",
    reject_unknown_keys: bool = False,
) -> ScheduleConfig:
    """Phân tích ánh xạ lịch học dùng chung cho cả ``config.yaml`` và ``PUT /api/schedule``."""
    if reject_unknown_keys:
        unknown = sorted(set(raw) - set(SCHEDULE_KEYS))
        if unknown:
            raise ScheduleError(
                f"Khóa giờ học không hợp lệ: {', '.join(unknown)}; dùng một trong "
                f"{', '.join(SCHEDULE_KEYS)}."
            )

    raw_enabled = raw.get("enabled")
    if raw_enabled is None:
        enabled = ScheduleConfig.enabled
    elif not isinstance(raw_enabled, bool):
        label = _qualify(prefix, "enabled") if prefix else "'enabled' của giờ học"
        if prefix:
            raise ScheduleError(
                f"'{label}' phải là true/false, nhận được {type(raw_enabled).__name__}: {raw_enabled!r}."
            )
        raise ScheduleError(
            f"{label} phải là true/false, nhận được {raw_enabled!r}."
        )
    else:
        enabled = raw_enabled

    windows_label = _qualify(prefix, "windows")
    windows: list[TimeWindow] = []
    raw_windows = raw.get("windows")
    if raw_windows is not None:
        if not isinstance(raw_windows, (list, tuple)):
            raise ScheduleError(
                f"'{windows_label}' phải là danh sách khung giờ, nhận được "
                f"{type(raw_windows).__name__}."
            )
        for index, item in enumerate(raw_windows):
            windows.append(parse_window(item, f"{windows_label}[{index}]"))

    kinds_label = _qualify(prefix, "kinds")
    kinds: dict[str, KindSettings] = {}
    raw_kinds = raw.get("kinds")
    if raw_kinds is not None:
        if not isinstance(raw_kinds, Mapping):
            raise ScheduleError(
                f"'{kinds_label}' phải là ánh xạ theo tên loại cảnh báo "
                f"({', '.join(ALERT_KINDS)}), nhận được {type(raw_kinds).__name__}."
            )
        for name, item in raw_kinds.items():
            if name not in ALERT_KINDS:
                raise ScheduleError(
                    f"'{kinds_label}.{name}' không phải loại cảnh báo hợp lệ; "
                    f"dùng một trong {ALERT_KINDS}."
                )
            kinds[name] = parse_kind_settings(dict(item) if isinstance(item, Mapping) else item, f"{kinds_label}.{name}")

    if enabled and not windows:
        if prefix:
            raise ScheduleError(
                f"'{_qualify(prefix, 'enabled')}' là true nhưng '{windows_label}' đang trống. "
                "Thêm ít nhất một khung giờ học hoặc đặt enabled: false."
            )
        raise ScheduleError(
            "Bật giờ học nhưng 'windows' đang trống. Thêm ít nhất một "
            "khung giờ hoặc đặt enabled: false."
        )

    return ScheduleConfig(
        enabled=enabled,
        windows=tuple(windows),
        kinds={**DEFAULT_KINDS, **kinds},
    )


def schedule_to_dict(schedule: ScheduleConfig) -> dict[str, Any]:
    """Đổi :class:`ScheduleConfig` thành dict JSON-serializable cho API web."""
    return {
        "enabled": bool(schedule.enabled),
        "windows": [
            {
                "days": list(window.days),
                "start": window.start.strftime("%H:%M"),
                "end": window.end.strftime("%H:%M"),
            }
            for window in schedule.windows
        ],
        "kinds": {
            name: {
                "enabled": bool(settings.enabled),
                "cooldown_s": float(settings.cooldown_s),
                "hold_s": float(settings.hold_s),
            }
            for name, settings in schedule.kinds.items()
        },
    }


def is_active(schedule: ScheduleConfig, now: datetime) -> bool:
    """``now`` có nằm trong giờ học quy định không (nếu ``enabled=False`` luôn trả ``True``)."""
    if not schedule.enabled:
        return True
    return any(window.covers(now) for window in schedule.windows)


@dataclass(frozen=True)
class AlertDecision:
    """Kết quả quyết định phát cảnh báo: loại cảnh báo và lý do đọc được."""

    kind: str
    reason: str


def should_alert(
    schedule: ScheduleConfig,
    now: datetime,
    *,
    held: Mapping[str, float],
    last_alert_at: Mapping[str, datetime] | None = None,
    kinds: Mapping[str, KindSettings] | None = None,
) -> AlertDecision | None:
    """Trả :class:`AlertDecision` cho loại cảnh báo đầu tiên đủ điều kiện, hoặc ``None``."""
    if not is_active(schedule, now):
        return None

    settings = schedule.kinds if kinds is None else kinds
    last_alerts: Mapping[str, datetime] = last_alert_at or {}

    for kind in ALERT_KINDS:
        kind_settings = settings.get(kind) or DEFAULT_KINDS[kind]
        if not kind_settings.enabled:
            continue
        held_s = held.get(kind)
        if held_s is None or held_s < kind_settings.hold_s:
            continue
        last = last_alerts.get(kind)
        if last is not None:
            elapsed = _seconds_between(now, last)
            if elapsed < kind_settings.cooldown_s:
                continue
        label = KIND_LABELS[kind]
        if kind_settings.cooldown_s <= 0:
            reason = f"{label} liên tục {held_s:.0f} s trong giờ học."
        else:
            reason = (
                f"{label} liên tục {held_s:.0f} s trong giờ học "
                f"(nhắc lại mỗi {kind_settings.cooldown_s:.0f} s khi lỗi còn "
                "tiếp diễn)."
            )
        return AlertDecision(kind=kind, reason=reason)
    return None


def _seconds_between(later: datetime, earlier: datetime) -> float:
    if (later.tzinfo is None) != (earlier.tzinfo is None):
        raise ValueError(
            "'now' và 'last_alert_at' phải cùng dạng: cả hai đều có timezone "
            "hoặc cả hai đều naive; không trộn lẫn."
        )
    return (later - earlier).total_seconds()
