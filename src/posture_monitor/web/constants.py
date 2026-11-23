"""Hằng số cấu hình, thông điệp tiếng Việt và giới hạn phân trang của tầng Web."""

from __future__ import annotations

from ..core import log_buffer as logs_module
from ..core.labels import (
    LABEL_ORDER,
    LABEL_TEXT,
    STATE_TEXT,
    VIOLATION_KIND_TEXT,
    VIOLATION_KINDS,
)

PTZ_DIRECTIONS = ("left", "right", "up", "down")
PTZ_DEFAULT_DURATION_S = 0.5
PTZ_DIRECTION_TEXT = {
    "left": "trái",
    "right": "phải",
    "up": "lên",
    "down": "xuống",
}

STALE_AFTER_S = 10.0
STREAM_WAIT_S = 2.0
STREAM_POLL_S = 0.05
STREAM_STALE_WARN_S = 5.0

STREAM_DISABLED_MESSAGE = (
    "Tính năng xem trực tiếp đang tắt. Bật 'web.stream_enabled: "
    "true' trong config.yaml nếu thật sự cần (tốn CPU và ảnh "
    "hưởng quyền riêng tư)."
)

FRAME_WAIT_S = 0.5
FRAME_MISSING_MESSAGE = (
    "Chưa có khung hình nào trong bộ nhớ. Vòng lặp camera chưa đặt khung đầu "
    "tiên — đợi vài giây rồi thử lại. Nếu vẫn không có, kiểm tra camera và "
    "xem log của 'posture_monitor run'."
)

PEOPLE_DISABLED_MESSAGE = "Tính năng người học chưa được bật trong phiên chạy này."

SPEAKER_DISABLED_MESSAGE = (
    "Loa cảnh báo chưa được bật trong phiên chạy này nên chưa đổi được giọng "
    "đọc. Kiểm tra mục 'speaker_alert' và 'camera.speaker' trong config.yaml."
)

PUBLIC_PERSON_FIELDS = ("id", "name", "created_ts")

LOGS_DEFAULT_LIMIT = 100
LOGS_MAX_LIMIT = logs_module.DEFAULT_MAXLEN

VIOLATIONS_DEFAULT_LIMIT = 100
VIOLATIONS_MAX_LIMIT = 500

__all__ = [
    "FRAME_MISSING_MESSAGE",
    "FRAME_WAIT_S",
    "LABEL_ORDER",
    "LABEL_TEXT",
    "LOGS_DEFAULT_LIMIT",
    "LOGS_MAX_LIMIT",
    "PEOPLE_DISABLED_MESSAGE",
    "PTZ_DEFAULT_DURATION_S",
    "PTZ_DIRECTIONS",
    "PTZ_DIRECTION_TEXT",
    "PUBLIC_PERSON_FIELDS",
    "SPEAKER_DISABLED_MESSAGE",
    "STALE_AFTER_S",
    "STATE_TEXT",
    "STREAM_DISABLED_MESSAGE",
    "STREAM_POLL_S",
    "STREAM_STALE_WARN_S",
    "STREAM_WAIT_S",
    "VIOLATIONS_DEFAULT_LIMIT",
    "VIOLATIONS_MAX_LIMIT",
    "VIOLATION_KINDS",
    "VIOLATION_KIND_TEXT",
]
