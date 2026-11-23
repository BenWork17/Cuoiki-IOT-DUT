"""Bộ đệm log vòng trong RAM để Web và Mobile đọc qua ``GET /api/logs``.

Giữ mọi mức log lúc ghi và chỉ lọc theo ngưỡng lúc đọc (:meth:`LogBuffer.snapshot`);
mọi thông điệp đều đi qua :func:`redact_camera_source` để không bao giờ lộ mật
khẩu RTSP lên HTTP.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from typing import Any

from .credentials import redact_camera_source

LEVEL_ORDER = {
    "DEBUG": 10,
    "INFO": 20,
    "WARNING": 30,
    "ERROR": 40,
    "CRITICAL": 50,
}

DEFAULT_MAXLEN = 500
DEFAULT_MIN_LEVEL = "WARNING"

_ROOT_LOGGER_NAME = "posture_monitor"
_LOGGER_PREFIX = _ROOT_LOGGER_NAME + "."


def normalize_level(value: Any, default: str = DEFAULT_MIN_LEVEL) -> str | None:
    """Đổi giá trị mức log thành tên chuẩn trong :data:`LEVEL_ORDER`, hoặc ``None`` nếu sai."""
    if value is None:
        return default
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        for name, number in LEVEL_ORDER.items():
            if number == value:
                return name
        return None
    text = str(value).strip().upper()
    if not text:
        return default
    return text if text in LEVEL_ORDER else None


def meets_level(level: str, min_level: str) -> bool:
    """``level`` có đạt ngưỡng ``min_level`` không (bằng hoặc cao hơn)."""
    return LEVEL_ORDER.get(level, 0) >= LEVEL_ORDER.get(min_level, 0)


def short_logger_name(name: str) -> str:
    """Bỏ tiền tố ``posture_monitor.`` để tên logger ngắn gọn trên giao diện."""
    if name == _ROOT_LOGGER_NAME:
        return name
    if name.startswith(_LOGGER_PREFIX):
        return name[len(_LOGGER_PREFIX) :]
    return name


class LogBuffer(logging.Handler):
    """Giữ ``maxlen`` bản ghi log gần nhất trong RAM, an toàn đa luồng."""

    def __init__(
        self, maxlen: int = DEFAULT_MAXLEN, level: int = logging.NOTSET
    ) -> None:
        super().__init__(level=level)
        capacity = int(maxlen)
        if capacity <= 0:
            raise ValueError(f"maxlen phải là số dương, nhận được {maxlen!r}.")
        self.maxlen = capacity
        self._records: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - handler không được ném
            message = "<không format được bản ghi>"
        message = redact_camera_source(message)
        entry = {
            "ts": float(record.created),
            "level": record.levelname,
            "logger": short_logger_name(record.name),
            "message": message,
        }
        with self._lock:
            self._records.append(entry)

    def snapshot(
        self,
        limit: int | None = None,
        min_level: str | None = DEFAULT_MIN_LEVEL,
    ) -> list[dict[str, Any]]:
        """Trả bản sao sâu một tầng các bản ghi mới nhất trước, đã lọc theo ``min_level``."""
        threshold = normalize_level(min_level) if min_level is not None else None
        with self._lock:
            items = [dict(entry) for entry in self._records]
        if threshold is not None:
            items = [item for item in items if meets_level(item["level"], threshold)]
        items.reverse()
        if limit is not None and int(limit) > 0:
            items = items[: int(limit)]
        return items

    def clear(self) -> None:
        """Xoá toàn bộ bản ghi đang giữ."""
        with self._lock:
            self._records.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._records)
