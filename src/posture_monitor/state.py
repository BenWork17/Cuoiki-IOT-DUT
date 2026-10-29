"""Làm mượt, hold, hysteresis, cooldown và leo thang (spec v2 §5.6).

Hai lớp, cả hai đều **nhận đồng hồ từ ngoài** (tham số ``now``, đơn vị giây,
không đọc ``time`` bên trong) để unit test điều khiển được thời gian:

- :class:`Smoother` — lấy trung vị từng đặc trưng trong cửa sổ
  ``smooth_window_s`` trước khi áp luật.
- :class:`StateMachine` — biến chuỗi nhãn theo thời gian thành trạng thái
  ``GOOD | WARN | BAD | ABSENT`` và danh sách sự kiện.

Quy tắc theo spec §5.6:

- Nhãn xấu thành sự kiện cảnh báo khi duy trì **liên tục** ``bad_hold_s``.
- Sự kiện kết thúc khi nhãn vắng mặt liên tục ``good_hold_s`` (hysteresis).
- Không lặp cảnh báo cùng nhãn trong ``alert_cooldown_s``.
- Vẫn sai sau ``escalate_after_s`` tính từ lúc sự kiện bắt đầu → leo thang
  một lần cho mỗi đợt.
- ``HEAD_DOWN`` liên tục ``drowsy_hold_s`` → ``DROWSY_SUSPECT`` (xấp xỉ; hệ
  thống **không** phát hiện nhắm mắt — README phải ghi rõ).
- Ngồi liên tục ``break_after_min`` phút → ``BREAK_REMINDER``.
- Vắng mặt liên tục ``absent_reset_s`` → đặt lại bộ đếm.
- Vắng mặt ngắn hơn ``absent_reset_s`` không xóa đợt đang mở, nhưng mọi mốc
  thời gian đang mở được dời qua đúng khoảng vắng khi người quay lại: các
  ngưỡng ``bad_hold_s`` / ``escalate_after_s`` / ``drowsy_hold_s`` chỉ đo
  thời gian sai **có quan sát**, không đo thời gian người dùng đi vắng.

Module không phụ thuộc camera, model hay GPIO.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Iterable

from .classifier import ABSENT, BAD_LABELS, HEAD_DOWN
from .features import ALL_NAMES, Features

#: Trạng thái đầu ra (spec v2 §5.6).
STATE_GOOD = "GOOD"
STATE_WARN = "WARN"
STATE_BAD = "BAD"
STATE_ABSENT = "ABSENT"
STATES = (STATE_GOOD, STATE_WARN, STATE_BAD, STATE_ABSENT)

# Kiểu sự kiện.
EVENT_ALERT_START = "alert_start"
EVENT_ALERT_END = "alert_end"
EVENT_ESCALATE = "escalate"
EVENT_DROWSY = "DROWSY_SUSPECT"
EVENT_BREAK = "break_reminder"
EVENT_ABSENT_RESET = "absent_reset"
#: Loa đã thật sự phát cảnh báo (spec v3 §8.2 tiêu chí 2).
EVENT_SPEAK_OK = "SPEAK_OK"
#: Loa không phát được (spec v3 §5.15, §6). **Không** dùng cho ca tắt tiếng.
EVENT_SPEAK_FAILED = "SPEAK_FAILED"


@dataclass(frozen=True)
class Event:
    """Một sự kiện do máy trạng thái sinh ra.

    ``ts`` là mốc thời gian (giây) của lần cập nhật đã sinh ra sự kiện.
    ``alert=True`` nghĩa là sự kiện này nên kích hoạt phần cứng ngay; sự kiện
    bị chặn bởi cooldown vẫn được ghi nhận với ``alert=False``.
    """

    ts: float
    type: str
    label: str | None
    duration_s: float = 0.0
    level: int = 1
    alert: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "ts": self.ts,
            "type": self.type,
            "label": self.label,
            "duration_s": self.duration_s,
            "level": self.level,
            "alert": self.alert,
        }


@dataclass(frozen=True)
class StateUpdate:
    """Kết quả một lần cập nhật máy trạng thái."""

    now: float
    state: str
    labels: frozenset[str]
    score: float
    sitting_s: float
    events: tuple[Event, ...] = ()
    #: Sự kiện cần báo ngay (đã qua cooldown), tách sẵn cho tầng alerts.
    alerts: tuple[Event, ...] = ()


class Smoother:
    """Trung vị trượt theo thời gian cho :class:`Features` (spec v2 §5.6).

    Mỗi đặc trưng lấy trung vị của các giá trị khác ``None`` trong cửa sổ
    ``window_s`` giây gần nhất, kể cả khung hiện tại. Đặc trưng không có mẫu
    nào trong cửa sổ là ``None``. ``person`` là ``True`` nếu cửa sổ có ít
    nhất một khung thấy người, giúp một khung lỗi không làm nhảy sang ABSENT.
    """

    def __init__(self, window_s: float) -> None:
        if not math.isfinite(window_s) or window_s < 0:
            raise ValueError(
                f"window_s phải là số hữu hạn không âm, nhận được {window_s!r}."
            )
        self.window_s = float(window_s)
        self._frames: list[tuple[float, Features]] = []

    def reset(self) -> None:
        self._frames.clear()

    def push(self, now: float, features: Features) -> Features:
        """Thêm khung mới và trả về đặc trưng đã làm mượt."""
        self._frames.append((float(now), features))
        cutoff = float(now) - self.window_s
        self._frames = [
            (ts, frame) for ts, frame in self._frames if ts >= cutoff
        ]

        person = any(frame.person for _, frame in self._frames)
        values: dict[str, float | None] = {}
        for name in ALL_NAMES:
            samples = [
                float(value)
                for _, frame in self._frames
                if (value := frame.get(name)) is not None
                and math.isfinite(float(value))
            ]
            values[name] = statistics.median(samples) if samples else None

        last_view = self._frames[-1][1].view
        return Features(view=last_view, person=person, values=values)


@dataclass
class _Episode:
    """Một đợt nhãn xấu đã đủ hold và đang ở trạng thái cảnh báo."""

    start: float
    escalated: bool = False


class StateMachine:
    """Máy trạng thái tư thế; mọi mốc thời gian do bên ngoài bơm vào."""

    def __init__(self, timing) -> None:
        """Khởi tạo từ ``config.timing`` (``TimingConfig``).

        Raises:
            ValueError: khi các mốc thời gian âm hoặc không hữu hạn.
        """
        self.timing = timing
        for name in (
            "smooth_window_s",
            "bad_hold_s",
            "good_hold_s",
            "alert_cooldown_s",
            "escalate_after_s",
            "break_after_min",
            "absent_reset_s",
            "drowsy_hold_s",
        ):
            value = float(getattr(timing, name))
            if not math.isfinite(value) or value < 0:
                raise ValueError(
                    f"timing.{name} phải là số hữu hạn không âm, nhận được "
                    f"{value!r}."
                )

        self.reset()

    # ------------------------------------------------------------------
    # Trạng thái nội bộ
    # ------------------------------------------------------------------
    def reset(self) -> None:
        """Xóa toàn bộ bộ đếm, như lúc mới khởi tạo."""
        self._last_now: float | None = None
        self._bad_since: dict[str, float] = {}
        self._good_since: dict[str, float] = {}
        self._active: dict[str, _Episode] = {}
        self._last_alert: dict[str, float] = {}
        self._drowsy_sent = False
        self._break_sent = False
        self._sitting_s = 0.0
        self._absent_since: float | None = None
        self._absent_reset_done = False

    # ------------------------------------------------------------------
    # Truy vấn
    # ------------------------------------------------------------------
    @property
    def sitting_s(self) -> float:
        """Số giây đã ngồi liên tục (không tính lúc vắng mặt)."""
        return self._sitting_s

    @property
    def active_labels(self) -> tuple[str, ...]:
        """Các nhãn đang ở trạng thái cảnh báo (đã đủ ``bad_hold_s``)."""
        return tuple(sorted(self._active))

    # ------------------------------------------------------------------
    # Cập nhật
    # ------------------------------------------------------------------
    def update(
        self, now: float, labels: Iterable[str], score: float
    ) -> StateUpdate:
        """Nạp kết quả một khung và trả về trạng thái mới.

        Args:
            now: mốc thời gian (giây), phải không giảm so với lần trước.
            labels: tập nhãn của khung đã làm mượt (kể cả ``GOOD``/``ABSENT``).
            score: điểm tư thế 0–100 của khung.

        Raises:
            ValueError: khi ``now`` nhỏ hơn lần cập nhật trước.
        """
        now = float(now)
        if not math.isfinite(now):
            raise ValueError(f"now phải là số hữu hạn, nhận được {now!r}.")
        if self._last_now is not None and now < self._last_now:
            raise ValueError(
                f"now={now!r} nhỏ hơn lần cập nhật trước {self._last_now!r}; "
                "đồng hồ phải không giảm."
            )
        delta = 0.0 if self._last_now is None else now - self._last_now
        self._last_now = now

        current = frozenset(labels)
        events: list[Event] = []

        absent = ABSENT in current

        if absent:
            self._good_since.clear()
            # Khung vắng mặt không chứng minh nhãn xấu "liên tục": hủy các đợt
            # chưa đủ hold. Sự kiện đã mở thì giữ nguyên, đồng hồ hysteresis
            # dừng lại (xóa good_since) cho tới khi thấy người trở lại.
            for label in list(self._bad_since):
                if label not in self._active:
                    del self._bad_since[label]
            if self._absent_since is None:
                self._absent_since = now
                self._absent_reset_done = False
            if (
                not self._absent_reset_done
                and now - self._absent_since >= float(
                    self.timing.absent_reset_s
                )
            ):
                events.extend(self._reset_after_absence(now))
            return self._build(now, STATE_ABSENT, current, score, events)

        # Có người trở lại: kết thúc đợt vắng, bộ đếm ngồi chạy tiếp.
        # Đồng hồ của mọi đợt/đếm đang mở phải nhảy qua khoảng vắng: nhãn chỉ
        # được coi là duy trì "liên tục" khi thực sự có khung quan sát, nên
        # ``now - start`` phải đo thời gian sai đã quan sát, không đo thời
        # gian người dùng đi vắng (spec §5.6). Cảnh báo đang mở vẫn giữ
        # nguyên (không phát ``alert_end`` chỉ vì vắng chốc lát).
        if self._absent_since is not None:
            self._shift_open_clocks(now - self._absent_since)
        self._absent_since = None
        self._absent_reset_done = False
        self._sitting_s += max(0.0, delta)

        bad_now = current & BAD_LABELS
        events.extend(self._update_episodes(now, bad_now))
        events.extend(self._check_drowsy(now, current))
        events.extend(self._check_break(now))

        if self._active:
            state = STATE_BAD
        elif bad_now:
            state = STATE_WARN
        else:
            state = STATE_GOOD

        return self._build(now, state, current, score, events)

    # ------------------------------------------------------------------
    # Nội bộ
    # ------------------------------------------------------------------
    def _update_episodes(
        self, now: float, bad_now: frozenset[str]
    ) -> list[Event]:
        events: list[Event] = []

        # Nhãn xấu xuất hiện: bắt đầu/tiếp tục đếm hold.
        for label in bad_now:
            self._good_since.pop(label, None)
            self._bad_since.setdefault(label, now)

        # Nhãn xấu vắng: đếm thời gian tốt để kết thúc (hysteresis).
        for label in list(self._bad_since):
            if label in bad_now:
                continue
            if label not in self._active:
                # Chưa đủ hold mà đã hết: hủy đợt, không có cảnh báo.
                del self._bad_since[label]
                continue
            good_since = self._good_since.setdefault(label, now)
            if now - good_since >= float(self.timing.good_hold_s):
                episode = self._active.pop(label)
                del self._bad_since[label]
                self._good_since.pop(label, None)
                events.append(
                    Event(
                        ts=now,
                        type=EVENT_ALERT_END,
                        label=label,
                        duration_s=now - episode.start,
                        level=2 if episode.escalated else 1,
                    )
                )

        # Nhãn xấu đã đủ hold: mở đợt cảnh báo.
        for label, since in list(self._bad_since.items()):
            if label in self._active:
                continue
            if now - since < float(self.timing.bad_hold_s):
                continue
            episode = _Episode(start=since)
            self._active[label] = episode
            allowed = self._cooldown_allows(label, now)
            if allowed:
                # Cooldown tính từ lúc cảnh báo thực sự phát, không từ lúc
                # nhãn bắt đầu: người dùng vừa được nhắc thì phải được yên.
                self._last_alert[label] = now
            events.append(
                Event(
                    ts=now,
                    type=EVENT_ALERT_START,
                    label=label,
                    duration_s=now - since,
                    level=1,
                    alert=allowed,
                )
            )

        # Leo thang khi vẫn sai quá escalate_after_s tính từ lúc bắt đầu đợt.
        for label, episode in list(self._active.items()):
            if episode.escalated or label not in bad_now:
                continue
            if now - episode.start >= float(self.timing.escalate_after_s):
                episode.escalated = True
                allowed = self._cooldown_allows(label, now)
                if allowed:
                    self._last_alert[label] = now
                events.append(
                    Event(
                        ts=now,
                        type=EVENT_ESCALATE,
                        label=label,
                        duration_s=now - episode.start,
                        level=2,
                        alert=allowed,
                    )
                )

        return events

    def _shift_open_clocks(self, gap: float) -> None:
        """Dời mọi mốc thời gian đang mở tiến thêm ``gap`` giây.

        Dùng khi người dùng quay lại sau một khoảng vắng: ``now - start`` sau
        đó chỉ còn đo phần thời gian sai **có quan sát**, nhờ vậy một người đi
        vắng 90 giây rồi quay lại với tư thế sai không bị báo leo thang hay
        buồn ngủ ngay lập tức.
        """
        if gap <= 0.0:
            return
        for episode in self._active.values():
            episode.start += gap
        for label in list(self._bad_since):
            self._bad_since[label] += gap
        # ``_good_since`` và ``_last_alert`` không cần dời: khung vắng mặt đã
        # xóa ``_good_since``, còn cooldown cố ý để trôi theo thời gian thật
        # để buổi học mới sau khi quay lại vẫn được nhắc.

    def _cooldown_allows(self, label: str, at: float) -> bool:
        last = self._last_alert.get(label)
        if last is None:
            return True
        return at - last >= float(self.timing.alert_cooldown_s)

    def _check_drowsy(
        self, now: float, current: frozenset[str]
    ) -> list[Event]:
        if HEAD_DOWN not in current:
            self._drowsy_sent = False
            return []
        if self._drowsy_sent:
            return []
        since = self._bad_since.get(HEAD_DOWN)
        if since is None:
            return []
        if now - since < float(self.timing.drowsy_hold_s):
            return []
        self._drowsy_sent = True
        return [
            Event(
                ts=now,
                type=EVENT_DROWSY,
                label=HEAD_DOWN,
                duration_s=now - since,
                level=2,
                alert=self._cooldown_allows(HEAD_DOWN, now),
            )
        ]

    def _check_break(self, now: float) -> list[Event]:
        if self._break_sent:
            return []
        limit = float(self.timing.break_after_min) * 60.0
        if self._sitting_s < limit:
            return []
        self._break_sent = True
        return [
            Event(
                ts=now,
                type=EVENT_BREAK,
                label=None,
                duration_s=self._sitting_s,
                level=1,
                alert=True,
            )
        ]

    def _reset_after_absence(self, now: float) -> list[Event]:
        """Vắng đủ ``absent_reset_s``: đóng sự kiện và đặt lại bộ đếm."""
        events: list[Event] = []
        for label, episode in sorted(self._active.items()):
            events.append(
                Event(
                    ts=now,
                    type=EVENT_ALERT_END,
                    label=label,
                    duration_s=now - episode.start,
                    level=2 if episode.escalated else 1,
                )
            )
        self._active.clear()
        self._bad_since.clear()
        self._good_since.clear()
        self._drowsy_sent = False
        self._break_sent = False
        self._sitting_s = 0.0
        self._absent_reset_done = True
        events.append(
            Event(
                ts=now,
                type=EVENT_ABSENT_RESET,
                label=None,
                duration_s=now - float(self._absent_since or now),
                level=0,
            )
        )
        return events

    def _build(
        self,
        now: float,
        state: str,
        labels: frozenset[str],
        score: float,
        events: list[Event],
    ) -> StateUpdate:
        score = float(score)
        if not math.isfinite(score):
            score = 0.0
        score = max(0.0, min(100.0, score))
        return StateUpdate(
            now=now,
            state=state,
            labels=labels,
            score=score,
            sitting_s=self._sitting_s,
            events=tuple(events),
            alerts=tuple(event for event in events if event.alert),
        )
