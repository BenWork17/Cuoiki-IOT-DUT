"""Gói con ``storage``: lưu trữ phiên học, sự kiện và thống kê phút trên SQLite."""

from .sqlite_store import (
    CLOCK_OUT_OF_RANGE_MESSAGE,
    DAY_S,
    FLUSH_INTERVAL_S,
    HISTORY_7D_DAYS,
    MAX_FRAME_GAP_S,
    MAX_PENDING_ROWS,
    MINUTE_S,
    Storage,
    VIOLATION_KIND_CODES,
    _format_local,
    _local_day_key,
    _local_midnight,
    _pack_stat_series,
)

__all__ = [
    "CLOCK_OUT_OF_RANGE_MESSAGE",
    "DAY_S",
    "FLUSH_INTERVAL_S",
    "HISTORY_7D_DAYS",
    "MAX_FRAME_GAP_S",
    "MAX_PENDING_ROWS",
    "MINUTE_S",
    "Storage",
    "VIOLATION_KIND_CODES",
    "_format_local",
    "_local_day_key",
    "_local_midnight",
    "_pack_stat_series",
]
