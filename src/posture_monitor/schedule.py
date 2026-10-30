"""Giờ học quy định và quyết định có nên phát cảnh báo hay không.

Đây là module **thuần**: không đọc file, không đọc đồng hồ hệ thống, không
phụ thuộc camera/model/GPIO. Mọi thời điểm đều nhận từ ngoài qua tham số
``now``, nên unit test điều khiển được thời gian và kết quả không phụ thuộc
múi giờ của máy chạy test.

Hai hàm công khai, cả hai đều không tác dụng phụ:

- :func:`is_active` — ``now`` có nằm trong khung giờ học không.
- :func:`should_alert` — có nên phát cảnh báo loại ``kind`` ngay bây giờ
  không, kèm lý do; trả ``None`` khi không nên.

Quy ước thời gian
-----------------

- Khung giờ nằm trong :class:`TimeWindow`. ``start`` tính là **trong**,
  ``end`` tính là **ngoài**: khung 19:00–21:30 thì 19:00 đang học còn 21:30
  đã hết giờ.
- Khung **qua đêm** (``start`` > ``end``) thuộc về ngày bắt đầu: khung
  ``days: [fri]``, 22:00–01:00 thì thứ Sáu 23:30 và thứ Bảy 00:30 đều đang
  học, còn thứ Bảy 23:30 thì không.
- ``now`` **naive** được hiểu là giờ địa phương của máy (hàm chỉ đọc
  ``weekday()`` và ``time()``). ``now`` có timezone thì dùng đúng giờ hiển
  thị trong chính timezone đó — hàm **không** tự đổi sang timezone của máy,
  để kết quả không phụ thuộc cấu hình hệ điều hành. Người gọi muốn "giờ địa
  phương" thì truyền ``datetime.now().astimezone()`` hoặc datetime naive.
- ``last_alert_at`` (mốc cảnh báo gần nhất của từng loại) phải **cùng dạng**
  với ``now``: cả hai đều có timezone hoặc cả hai đều naive. Trộn hai dạng
  thì báo lỗi rõ ràng thay vì đoán một múi giờ.

Không có cooldown hay thời gian giữ nào viết cứng ở đây: chúng đến từ
``schedule.kinds`` (đọc từ ``config.yaml``) hoặc từ tham số ``kinds`` truyền
vào :func:`should_alert`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Any, Mapping

#: Tên thứ theo thứ tự ``datetime.weekday()`` (0 = thứ Hai ... 6 = Chủ nhật).
DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_DAY_INDEX = {name: index for index, name in enumerate(DAY_NAMES)}

#: Ba loại cảnh báo của giờ học. Thứ tự này cũng là thứ tự ưu tiên khi nhiều
#: loại cùng đủ điều kiện trong một lần gọi :func:`should_alert`.
KIND_LEAVE_FRAME = "leave_frame"
KIND_PHONE = "phone"
KIND_STRANGER = "stranger"
ALERT_KINDS = (KIND_LEAVE_FRAME, KIND_PHONE, KIND_STRANGER)

#: Nhãn tiếng Việt dùng trong lý do cảnh báo.
KIND_LABELS = {
    KIND_LEAVE_FRAME: "Rời khung hình",
    KIND_PHONE: "Dùng điện thoại",
    KIND_STRANGER: "Có người lạ",
}

#: Mẫu giờ hợp lệ: ``HH:MM`` (1–2 chữ số giờ, đúng 2 chữ số phút).
_CLOCK_RE = re.compile(r"^(?P<hour>\d{1,2}):(?P<minute>\d{2})$")


class ScheduleError(ValueError):
    """Giờ học cấu hình sai (giờ, thứ, khung giờ hoặc thiết lập loại cảnh báo).

    ``config.py`` bắt lỗi này và đổi thành ``ConfigError`` để mọi lỗi cấu
    hình của dự án có cùng một kiểu ở API công khai.
    """


@dataclass(frozen=True)
class KindSettings:
    """Thiết lập cho một loại cảnh báo trong giờ học.

    Args:
        enabled: ``False`` thì loại này không bao giờ phát cảnh báo.
        cooldown_s: không lặp lại cảnh báo cùng loại trong khoảng này (giây).
        hold_s: điều kiện phải duy trì liên tục ít nhất chừng này giây.

    Raises:
        ScheduleError: khi ``cooldown_s`` hoặc ``hold_s`` âm.
    """

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


#: Số giây chạm điện thoại liên tục để thành sự kiện "đang dùng điện thoại".
#: **Một nguồn sự thật duy nhất** cho cả hai tầng: dashboard hiện trạng thái
#: theo ``phone.hold_s`` (``config.py``), loa quyết định theo
#: ``schedule.kinds.phone.hold_s`` (``DEFAULT_KINDS`` bên dưới). Hai giá trị
#: lệch nhau từng gây lỗi "web hiện đang dùng điện thoại mà loa không báo":
#: web đã báo ở giây thứ 2 trong khi loa chờ tới giây thứ 10.
DEFAULT_PHONE_HOLD_S = 2.0


DEFAULT_KINDS: dict[str, KindSettings] = {
    KIND_LEAVE_FRAME: KindSettings(cooldown_s=60.0, hold_s=5.0),
    #: ``hold_s`` lấy từ :data:`DEFAULT_PHONE_HOLD_S` — cùng nguồn với
    #: ``PhoneConfig.hold_s``, nên mặc định hai tầng không bao giờ lệch.
    #: ``_warn_phone_threshold_mismatch`` vẫn cảnh báo khi file cấu hình tự
    #: đặt hai giá trị khác nhau.
    KIND_PHONE: KindSettings(cooldown_s=120.0, hold_s=DEFAULT_PHONE_HOLD_S),
    KIND_STRANGER: KindSettings(cooldown_s=300.0, hold_s=5.0),
}


@dataclass(frozen=True)
class TimeWindow:
    """Một khung giờ học trong tuần.

    Args:
        days: các thứ khung này áp dụng, theo tên ``mon``...``sun``. Với khung
            qua đêm, đây là các ngày **bắt đầu**.
        start: giờ bắt đầu, tính là trong khung.
        end: giờ kết thúc, tính là ngoài khung.

    Raises:
        ScheduleError: khi danh sách thứ rỗng/có tên lạ, hoặc ``start`` bằng
            ``end`` (khung rỗng, không rõ nghĩa).
    """

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
        """``True`` khi khung vắt qua nửa đêm (ví dụ 22:00 → 01:00)."""
        return _seconds_of_day(self.start) > _seconds_of_day(self.end)

    def covers(self, moment: datetime) -> bool:
        """``moment`` có nằm trong khung này không.

        Phần sau nửa đêm của khung qua đêm được tính cho **ngày bắt đầu**:
        khung thứ Sáu 22:00–01:00 bao trùm thứ Bảy 00:30.
        """
        today = moment.weekday()
        seconds = _seconds_of_day(moment.time())
        start = _seconds_of_day(self.start)
        end = _seconds_of_day(self.end)
        indexes = {_DAY_INDEX[day] for day in self.days}

        if start < end:
            return today in indexes and start <= seconds < end
        # Qua đêm: [start, 24:00) của ngày bắt đầu, [00:00, end) của ngày kế.
        if today in indexes and seconds >= start:
            return True
        previous = (today - 1) % 7
        return previous in indexes and seconds < end


@dataclass
class ScheduleConfig:
    """Mục ``schedule`` trong ``config.yaml``: giờ học quy định.

    Sống ở ``config.py`` (nạp từ YAML) nhưng kiểu dữ liệu được định nghĩa ở
    đây để module này thuần và không phụ thuộc ``config.py``.
    """

    enabled: bool = False
    windows: tuple[TimeWindow, ...] = ()
    kinds: Mapping[str, KindSettings] = field(
        default_factory=lambda: dict(DEFAULT_KINDS)
    )


# --------------------------------------------------------------------------
# Đọc cấu hình
# --------------------------------------------------------------------------


def _seconds_of_day(moment: time) -> int:
    """Số giây kể từ 00:00 của một ``time`` (bỏ microsecond)."""
    return moment.hour * 3600 + moment.minute * 60 + moment.second


def parse_clock(value: Any, where: str) -> time:
    """Đọc một giờ dạng ``"HH:MM"``.

    ``where`` là đường dẫn khóa trong cấu hình (ví dụ
    ``schedule.windows[0].start``) để thông điệp lỗi chỉ đúng chỗ sửa.

    YAML không đặt trong ngoặc kép sẽ đọc ``19:00`` thành số 1140 (YAML hiểu
    dấu ``:`` là hệ 60). Đó là lỗi rất dễ gặp nên thông điệp nêu thẳng cách
    sửa.

    Raises:
        ScheduleError: khi sai định dạng hoặc giờ/phút ngoài phạm vi.
    """
    if isinstance(value, time):
        return value
    if isinstance(value, bool) or not isinstance(value, str):
        hint = ""
        if isinstance(value, int):
            hint = (
                ' (YAML đọc giờ không có ngoặc kép thành số; hãy viết start: "19:00")'
            )
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
    """Đọc danh sách thứ, ví dụ ``[mon, tue, wed]``.

    Tên thứ không phân biệt hoa thường; thứ trùng nhau được bỏ qua (giữ thứ
    tự xuất hiện).

    Raises:
        ScheduleError: khi không phải danh sách chuỗi hoặc có tên lạ.
    """
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
    """Đọc một khung giờ ``{days, start, end}``.

    Raises:
        ScheduleError: khi khung không phải ánh xạ, thiếu khóa, sai giờ hoặc
            ``start`` trùng ``end``.
    """
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
    """Đọc thiết lập của một loại cảnh báo: ``{enabled, cooldown_s, hold_s}``.

    Khóa thiếu thì dùng mặc định của :class:`KindSettings`; khóa có nhưng sai
    kiểu thì báo lỗi, không tự đoán.

    Raises:
        ScheduleError: khi không phải ánh xạ hoặc sai kiểu/giá trị âm.
    """
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


# --------------------------------------------------------------------------
# Quyết định
# --------------------------------------------------------------------------


def is_active(schedule: ScheduleConfig, now: datetime) -> bool:
    """``now`` có nằm trong giờ học quy định không.

    ``schedule.enabled`` là ``False`` thì trả ``True``: tắt giờ học nghĩa là
    không hạn chế thời gian cảnh báo, chứ không phải tắt hết cảnh báo. Muốn
    tắt cảnh báo thì tắt ở ``schedule.kinds``.

    ``now`` naive được hiểu là giờ địa phương của máy (chỉ đọc ``weekday()``
    và ``time()``).
    """
    if not schedule.enabled:
        return True
    return any(window.covers(now) for window in schedule.windows)


@dataclass(frozen=True)
class AlertDecision:
    """Kết quả "nên cảnh báo": loại cảnh báo và lý do đọc được."""

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
    """Có nên phát cảnh báo ngay bây giờ không, và vì sao.

    Args:
        schedule: giờ học (``ScheduleConfig``); quyết định cổng giờ học.
        now: thời điểm hiện tại, do bên gọi truyền vào.
        held: số giây mỗi điều kiện đã duy trì liên tục, theo loại cảnh báo
            (``leave_frame`` / ``phone`` / ``stranger``). Loại vắng mặt coi
            như chưa xảy ra.
        last_alert_at: thời điểm cảnh báo gần nhất **của từng loại**. Tính
            theo từng loại để một loại đang trong cooldown không chặn loại
            khác.
        kinds: thiết lập thay thế cho ``schedule.kinds`` (mỗi loại gồm
            ``enabled``, ``cooldown_s``, ``hold_s``); ``None`` = dùng cấu
            hình trong ``schedule``.

    Returns:
        :class:`AlertDecision` cho loại đầu tiên đủ điều kiện (theo thứ tự
        :data:`ALERT_KINDS`), hoặc ``None`` khi: ngoài giờ học, không có điều
        kiện nào duy trì đủ ``hold_s``, loại đó bị tắt, hoặc loại đó còn
        trong cooldown.

    Raises:
        ValueError: khi ``last_alert_at`` trộn datetime naive với datetime có
            timezone.
    """
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
        reason = (
            f"{label} liên tục {held_s:.0f} s trong giờ học "
            f"(đã hết cooldown {kind_settings.cooldown_s:.0f} s)."
        )
        return AlertDecision(kind=kind, reason=reason)
    return None


def _seconds_between(later: datetime, earlier: datetime) -> float:
    """Khoảng cách ``later - earlier`` tính bằng giây.

    Không dùng ``datetime.timestamp()``: trên Windows, ``timestamp()`` ném
    ``OSError`` với mốc gần epoch, và giá trị này không cần chuyển sang epoch.
    """
    if (later.tzinfo is None) != (earlier.tzinfo is None):
        raise ValueError(
            "'now' và 'last_alert_at' phải cùng dạng: cả hai đều có timezone "
            "hoặc cả hai đều naive; không trộn lẫn."
        )
    return (later - earlier).total_seconds()
