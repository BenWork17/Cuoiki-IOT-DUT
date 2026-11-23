"""Phiên học đếm ngược bật/tắt bằng tay, an toàn đa luồng (:class:`StudySession`)."""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from typing import Any

STATE_IDLE = "idle"
STATE_RUNNING = "running"
STATE_FINISHED = "finished"

MIN_MINUTES = 1
MAX_MINUTES = 720
DEFAULT_MINUTES = 60

FINISHED_MESSAGE = "Đã hết giờ học. Nghỉ ngơi nhé."


class StudySessionError(ValueError):
    """Thời lượng phiên không hợp lệ."""


def normalise_minutes(value: Any) -> int:
    """Kiểm tra thời lượng phiên, trả số phút nguyên trong ``[MIN_MINUTES, MAX_MINUTES]``."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StudySessionError(
            "Thời lượng phiên học phải là số phút, nhận được "
            f"{type(value).__name__}: {value!r}."
        )
    number = float(value)
    if not math.isfinite(number):
        raise StudySessionError(
            f"Thời lượng phiên học phải là số hữu hạn, nhận được {value!r}."
        )
    rounded = int(round(number))
    if abs(number - rounded) > 1e-9:
        raise StudySessionError(
            f"Thời lượng phiên học phải là số phút nguyên, nhận được {value!r}."
        )
    if not MIN_MINUTES <= rounded <= MAX_MINUTES:
        raise StudySessionError(
            f"Thời lượng phiên học phải trong khoảng {MIN_MINUTES}–"
            f"{MAX_MINUTES} phút, nhận được {rounded} phút."
        )
    return rounded


@dataclass(frozen=True)
class SessionSnapshot:
    """Ảnh chụp trạng thái phiên tại một thời điểm."""

    state: str
    minutes: int
    remaining_s: float
    elapsed_s: float
    ends_in_text: str | None
    finished_message: str | None


IDLE_SNAPSHOT = SessionSnapshot(
    state=STATE_IDLE,
    minutes=0,
    remaining_s=0.0,
    elapsed_s=0.0,
    ends_in_text=None,
    finished_message=None,
)


def _format_countdown(seconds: float) -> str:
    total = max(0, int(math.ceil(seconds - 1e-9)))
    return f"{total // 60:02d}:{total % 60:02d}"


class StudySession:
    """Bộ đếm một phiên học, an toàn đa luồng."""

    def __init__(
        self,
        default_minutes: int = DEFAULT_MINUTES,
        *,
        clock: Any = None,
    ) -> None:
        self._default_minutes = normalise_minutes(default_minutes)
        self._clock = time.monotonic if clock is None else clock
        self._lock = threading.Lock()

        self._state = STATE_IDLE
        self._minutes = 0
        self._started_at: float | None = None
        self._ends_at: float | None = None
        self._finish_announced = False

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._state == STATE_RUNNING

    @property
    def default_minutes(self) -> int:
        return self._default_minutes

    def snapshot(self) -> SessionSnapshot:
        with self._lock:
            now = float(self._clock())
            self._expire_locked(now)
            return self._snapshot_locked(now, finished_message=None)

    def start(self, minutes: Any = None) -> SessionSnapshot:
        wanted = (
            self._default_minutes if minutes is None else normalise_minutes(minutes)
        )
        with self._lock:
            now = float(self._clock())
            self._state = STATE_RUNNING
            self._minutes = wanted
            self._started_at = now
            self._ends_at = now + wanted * 60.0
            self._finish_announced = False
            return self._snapshot_locked(now, finished_message=None)

    def stop(self) -> SessionSnapshot:
        with self._lock:
            self._state = STATE_IDLE
            self._minutes = 0
            self._started_at = None
            self._ends_at = None
            self._finish_announced = False
            return self._snapshot_locked(float(self._clock()), finished_message=None)

    def tick(self) -> SessionSnapshot:
        with self._lock:
            now = float(self._clock())
            self._expire_locked(now)
            if not self._finish_announced and self._state == STATE_FINISHED:
                self._finish_announced = True
                return self._snapshot_locked(now, finished_message=FINISHED_MESSAGE)
            return self._snapshot_locked(now, finished_message=None)

    def _expire_locked(self, now: float) -> bool:
        if self._state != STATE_RUNNING:
            return False
        if self._ends_at is None or now < self._ends_at:
            return False
        self._state = STATE_FINISHED
        return True

    def _snapshot_locked(
        self, now: float, *, finished_message: str | None
    ) -> SessionSnapshot:
        if self._state == STATE_RUNNING and self._ends_at is not None:
            remaining = max(0.0, self._ends_at - now)
            started = self._started_at if self._started_at is not None else now
            elapsed = max(0.0, now - started)
            return SessionSnapshot(
                state=STATE_RUNNING,
                minutes=self._minutes,
                remaining_s=remaining,
                elapsed_s=elapsed,
                ends_in_text=_format_countdown(remaining),
                finished_message=finished_message,
            )
        if self._state == STATE_FINISHED:
            total = float(self._minutes) * 60.0
            return SessionSnapshot(
                state=STATE_FINISHED,
                minutes=self._minutes,
                remaining_s=0.0,
                elapsed_s=total,
                ends_in_text=None,
                finished_message=finished_message,
            )
        return SessionSnapshot(
            state=STATE_IDLE,
            minutes=0,
            remaining_s=0.0,
            elapsed_s=0.0,
            ends_in_text=None,
            finished_message=finished_message,
        )


def payload(snapshot: SessionSnapshot) -> dict[str, Any]:
    """Đổi ảnh chụp phiên thành dict JSON cho dashboard."""
    return {
        "state": snapshot.state,
        "minutes": snapshot.minutes,
        "remaining_s": round(snapshot.remaining_s, 1),
        "elapsed_s": round(snapshot.elapsed_s, 1),
        "ends_in_text": snapshot.ends_in_text,
        "finished_message": snapshot.finished_message,
        "finish_text": FINISHED_MESSAGE if snapshot.state == STATE_FINISHED else None,
    }
