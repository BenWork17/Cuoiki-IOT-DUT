"""Hằng số miền, nhãn trạng thái, mã sự kiện và bảng dịch tiếng Việt dùng chung.

Module này nằm ở tầng đáy ``core/``, không phụ thuộc bất kỳ gói con nào khác,
giúp cả ``vision``, ``domain``, ``storage``, ``alerts``, ``web`` và ``cli``
dùng chung một nguồn sự thật duy nhất mà không tạo phụ thuộc vòng hay phụ thuộc
ngược lên tầng giao diện.
"""

from __future__ import annotations

import math
from typing import Any

# ---------------------------------------------------------------------------
# 1. Hằng số cấu hình nền & trạng thái máy trạng thái (spec v2 §5.6)
# ---------------------------------------------------------------------------
VIEWS = ("front", "side")
MODEL_FORMATS = ("ncnn", "onnx", "pt")
MOCK_MODES = ("auto", True, False)
DEFAULT_SESSION_MINUTES = 60

STATE_GOOD = "GOOD"
STATE_WARN = "WARN"
STATE_BAD = "BAD"
STATE_ABSENT = "ABSENT"
STATE_PAUSED = "PAUSED"
STATES = (STATE_GOOD, STATE_WARN, STATE_BAD, STATE_ABSENT)

PAUSED_MESSAGE = "Chưa bắt đầu phiên học nên chưa đo tư thế."

STATE_TEXT: dict[str, str] = {
    STATE_GOOD: "Tư thế tốt",
    STATE_WARN: "Cần chú ý",
    STATE_BAD: "Tư thế sai",
    STATE_ABSENT: "Không thấy người",
    STATE_PAUSED: "Chưa bắt đầu phiên học",
}

# ---------------------------------------------------------------------------
# 2. Nhãn phân loại tư thế & bảng chữ hiển thị (spec v2 §5.5)
# ---------------------------------------------------------------------------
HEAD_DOWN = "HEAD_DOWN"
TOO_CLOSE = "TOO_CLOSE"
SHOULDER_TILT = "SHOULDER_TILT"
HEAD_TILT = "HEAD_TILT"
LEAN = "LEAN"
LOOK_AWAY = "LOOK_AWAY"
ABSENT = "ABSENT"
GOOD = "GOOD"

BAD_LABELS = frozenset(
    {HEAD_DOWN, TOO_CLOSE, SHOULDER_TILT, HEAD_TILT, LEAN, LOOK_AWAY, ABSENT}
)

LABEL_ORDER = (
    HEAD_DOWN,
    TOO_CLOSE,
    SHOULDER_TILT,
    HEAD_TILT,
    LEAN,
    LOOK_AWAY,
    ABSENT,
    GOOD,
)

LABEL_TEXT: dict[str, str] = {
    HEAD_DOWN: "Cúi đầu",
    TOO_CLOSE: "Ngồi quá gần",
    SHOULDER_TILT: "Nghiêng vai",
    HEAD_TILT: "Nghiêng đầu",
    LEAN: "Ngả người",
    LOOK_AWAY: "Nhìn ra chỗ khác",
    ABSENT: "Vắng mặt",
    GOOD: "Đúng tư thế",
}

# ---------------------------------------------------------------------------
# 3. Sự kiện máy trạng thái & ba mã vi phạm trong giờ học (spec v3 §6)
# ---------------------------------------------------------------------------
EVENT_ALERT_START = "alert_start"
EVENT_ALERT_END = "alert_end"
EVENT_ESCALATE = "escalate"
EVENT_DROWSY = "DROWSY_SUSPECT"
EVENT_BREAK = "break_reminder"
EVENT_ABSENT_RESET = "absent_reset"
EVENT_SPEAK_OK = "SPEAK_OK"
EVENT_SPEAK_FAILED = "SPEAK_FAILED"

EVENT_ABSENT = "ABSENT"
EVENT_PHONE_USE = "PHONE_USE"
EVENT_IMPOSTOR = "IMPOSTOR"

VIOLATION_KINDS = (EVENT_ABSENT, EVENT_PHONE_USE, EVENT_IMPOSTOR)

ALERT_EVENT_TYPE: dict[str, str] = {
    "leave_frame": EVENT_ABSENT,
    "phone": EVENT_PHONE_USE,
    "stranger": EVENT_IMPOSTOR,
}

VIOLATION_KIND_TEXT: dict[str, str] = {
    EVENT_ABSENT: "Rời khỏi bàn học",
    EVENT_PHONE_USE: "Dùng điện thoại",
    EVENT_IMPOSTOR: "Không phải người đăng ký",
}

# ---------------------------------------------------------------------------
# 4. Hằng số tên tệp kho & chuẩn hoá giọng đọc cảnh báo
# ---------------------------------------------------------------------------
FACE_STORE_FILENAME = "faces.json"

VOICE_MALE = "nam"
VOICE_FEMALE = "nu"
VOICE_SYNTH = "espeak"
VOICES = (VOICE_MALE, VOICE_FEMALE, VOICE_SYNTH)

VOICE_LABELS: dict[str, str] = {
    VOICE_MALE: "Giọng nam",
    VOICE_FEMALE: "Giọng nữ",
    VOICE_SYNTH: "Giọng máy",
}

VOICE_DIRS: dict[str, str] = {
    VOICE_MALE: "giongnam",
    VOICE_FEMALE: "giongnu",
}

DEFAULT_VOICE = VOICE_MALE

DEFAULT_SPEECH_SPEED = 0.9
MIN_SPEECH_SPEED = 0.5
MAX_SPEECH_SPEED = 1.0

DEFAULT_VOLUME = 0.7
MIN_VOLUME = 0.05
MAX_VOLUME = 1.0


def normalise_voice(value: Any) -> str:
    """Đổi giá trị bất kỳ thành mã giọng hợp lệ; hỏng thì về mặc định."""
    if isinstance(value, str):
        candidate = value.strip().lower()
        if candidate in VOICES:
            return candidate
        for voice, directory in VOICE_DIRS.items():
            if candidate == directory:
                return voice
    return DEFAULT_VOICE


def normalise_volume(value: Any, default: float = DEFAULT_VOLUME) -> float:
    """Đổi ``value`` thành âm lượng hợp lệ; hỏng/ngoài khoảng thì ``default``."""
    try:
        level = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(level) or not MIN_VOLUME <= level <= MAX_VOLUME:
        return default
    return level


def normalise_speed(value: Any, default: float = DEFAULT_SPEECH_SPEED) -> float:
    """Đổi giá trị bất kỳ thành tốc độ đọc hợp lệ; hỏng thì về ``default``."""
    try:
        speed = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(speed) or not MIN_SPEECH_SPEED <= speed <= MAX_SPEECH_SPEED:
        return default
    return speed
