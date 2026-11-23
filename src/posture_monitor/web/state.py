"""Trạng thái chia sẻ an toàn đa luồng giữa vòng lặp giám sát và Flask (:class:`DashboardState`)."""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Mapping

from ..core.logging_setup import get_logger
from .constants import (
    LABEL_ORDER,
    LABEL_TEXT,
    STALE_AFTER_S,
    STATE_TEXT,
    STREAM_POLL_S,
    STREAM_WAIT_S,
)

_logger = get_logger("posture_monitor.web.state")


class DashboardState:
    """Cầu nối dữ liệu trong RAM giữa vòng lặp camera và các route HTTP."""

    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._status: dict[str, Any] = {
            "state": "ABSENT",
            "labels": [],
            "score": 0.0,
            "sitting_s": 0.0,
            "distance_cm": None,
            "alert": None,
            "message": "",
        }
        self._updated_at: float | None = None
        self._muted = False
        self._calibration_requested = False
        self._frame: bytes | None = None
        self._frame_seq = 0

    def update(self, status: Mapping[str, Any] | None = None, **fields: Any) -> None:
        merged: dict[str, Any] = {}
        if status:
            merged.update(dict(status))
        merged.update(fields)

        with self._lock:
            for key, value in merged.items():
                if key in self._status:
                    self._status[key] = value
                else:
                    _logger.debug("Bỏ qua trường trạng thái lạ: %s", key)
            self._status["labels"] = [
                str(label) for label in (self._status["labels"] or [])
            ]
            self._status["state"] = str(self._status["state"] or "ABSENT")
            self._updated_at = float(self._clock())

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            status = dict(self._status)
            status["labels"] = list(self._status["labels"])
            updated_at = self._updated_at
            muted = self._muted
            pending = self._calibration_requested

        labels = status["labels"]
        state = status["state"]
        age = None if updated_at is None else max(0.0, self._clock() - updated_at)

        status.update(
            {
                "state_text": STATE_TEXT.get(state, state),
                "label_texts": [
                    LABEL_TEXT.get(label, label)
                    for label in LABEL_ORDER
                    if label in labels
                ],
                "muted": muted,
                "calibration_pending": pending,
                "data_age_s": None if age is None else round(age, 1),
                "stale": age is None or age > STALE_AFTER_S,
            }
        )
        return status

    def set_frame(self, jpeg: bytes | None) -> None:
        with self._lock:
            self._frame = jpeg
            self._frame_seq += 1

    def latest_frame(self) -> tuple[int, bytes | None]:
        with self._lock:
            return self._frame_seq, self._frame

    @property
    def muted(self) -> bool:
        with self._lock:
            return self._muted

    def set_muted(self, muted: bool) -> bool:
        value = bool(muted)
        with self._lock:
            self._muted = value
        _logger.info("Tiếng cảnh báo: %s", "TẮT" if value else "BẬT")
        return value

    def toggle_mute(self) -> bool:
        with self._lock:
            self._muted = not self._muted
            value = self._muted
        _logger.info("Tiếng cảnh báo: %s", "TẮT" if value else "BẬT")
        return value

    def request_calibration(self) -> None:
        with self._lock:
            self._calibration_requested = True
        _logger.info("Đã nhận yêu cầu hiệu chỉnh lại từ dashboard.")

    def consume_calibration_request(self) -> bool:
        with self._lock:
            pending = self._calibration_requested
            self._calibration_requested = False
        return pending

    def wait_frame(
        self, last_seq: int, timeout: float = STREAM_WAIT_S
    ) -> tuple[int, bytes | None]:
        # Đọc động STREAM_POLL_S từ web.app để các bài kiểm thử monkeypatch vẫn có hiệu lực.
        from . import app as app_mod  # noqa: PLC0415

        poll_s = getattr(app_mod, "STREAM_POLL_S", STREAM_POLL_S)
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            seq, frame = self.latest_frame()
            if seq != last_seq and frame is not None:
                return seq, frame
            if time.monotonic() >= deadline:
                return seq, frame
            time.sleep(poll_s)
