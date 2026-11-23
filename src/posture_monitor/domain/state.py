"""Làm mượt đặc trưng (:class:`Smoother`) và máy trạng thái tư thế (:class:`StateMachine`)."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Any, Iterable

from ..core.labels import (
    ABSENT,
    ALERT_EVENT_TYPE,
    BAD_LABELS,
    EVENT_ABSENT,
    EVENT_ABSENT_RESET,
    EVENT_ALERT_END,
    EVENT_ALERT_START,
    EVENT_BREAK,
    EVENT_DROWSY,
    EVENT_ESCALATE,
    EVENT_IMPOSTOR,
    EVENT_PHONE_USE,
    EVENT_SPEAK_FAILED,
    EVENT_SPEAK_OK,
    HEAD_DOWN,
    PAUSED_MESSAGE,
    STATE_ABSENT,
    STATE_BAD,
    STATE_GOOD,
    STATE_PAUSED,
    STATE_WARN,
    STATES,
)
from ..vision.features import ALL_NAMES, Features


@dataclass(frozen=True)
class Event:
    """Một sự kiện do máy trạng thái sinh ra."""

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
    alerts: tuple[Event, ...] = ()


class Smoother:
    """Trung vị trượt theo thời gian cho :class:`Features` (spec v2 §5.6)."""

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
        self._frames.append((float(now), features))
        cutoff = float(now) - self.window_s
        self._frames = [(ts, frame) for ts, frame in self._frames if ts >= cutoff]

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
    start: float
    escalated: bool = False


class StateMachine:
    """Máy trạng thái tư thế; mọi mốc thời gian do bên ngoài bơm vào."""

    def __init__(self, timing: Any) -> None:
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
                    f"timing.{name} phải là số hữu hạn không âm, nhận được {value!r}."
                )
        self.reset()

    def reset(self) -> None:
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

    @property
    def sitting_s(self) -> float:
        return self._sitting_s

    @property
    def active_labels(self) -> tuple[str, ...]:
        return tuple(sorted(self._active))

    def update(self, now: float, labels: Iterable[str], score: float) -> StateUpdate:
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

        if ABSENT in current:
            self._good_since.clear()
            for label in list(self._bad_since):
                if label not in self._active:
                    del self._bad_since[label]
            if self._absent_since is None:
                self._absent_since = now
                self._absent_reset_done = False
            if not self._absent_reset_done and now - self._absent_since >= float(
                self.timing.absent_reset_s
            ):
                events.extend(self._reset_after_absence(now))
            return self._build(now, STATE_ABSENT, current, score, events)

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

    def _update_episodes(self, now: float, bad_now: frozenset[str]) -> list[Event]:
        events: list[Event] = []

        for label in bad_now:
            self._good_since.pop(label, None)
            self._bad_since.setdefault(label, now)

        for label in list(self._bad_since):
            if label in bad_now:
                continue
            if label not in self._active:
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

        for label, since in list(self._bad_since.items()):
            if label in self._active:
                continue
            if now - since < float(self.timing.bad_hold_s):
                continue
            episode = _Episode(start=since)
            self._active[label] = episode
            allowed = self._cooldown_allows(label, now)
            if allowed:
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
        if gap <= 0.0:
            return
        for episode in self._active.values():
            episode.start += gap
        for label in list(self._bad_since):
            self._bad_since[label] += gap

    def _cooldown_allows(self, label: str, at: float) -> bool:
        last = self._last_alert.get(label)
        if last is None:
            return True
        return at - last >= float(self.timing.alert_cooldown_s)

    def _check_drowsy(self, now: float, current: frozenset[str]) -> list[Event]:
        if HEAD_DOWN not in current:
            self._drowsy_sent = False
            return []
        if self._drowsy_sent:
            return []
        since = self._bad_since.get(HEAD_DOWN)
        if since is None or now - since < float(self.timing.drowsy_hold_s):
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


__all__ = [
    "ALERT_EVENT_TYPE",
    "EVENT_ABSENT",
    "EVENT_ABSENT_RESET",
    "EVENT_ALERT_END",
    "EVENT_ALERT_START",
    "EVENT_BREAK",
    "EVENT_DROWSY",
    "EVENT_ESCALATE",
    "EVENT_IMPOSTOR",
    "EVENT_PHONE_USE",
    "EVENT_SPEAK_FAILED",
    "EVENT_SPEAK_OK",
    "Event",
    "PAUSED_MESSAGE",
    "STATE_ABSENT",
    "STATE_BAD",
    "STATE_GOOD",
    "STATE_PAUSED",
    "STATE_WARN",
    "STATES",
    "Smoother",
    "StateMachine",
    "StateUpdate",
]
