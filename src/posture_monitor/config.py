"""Đọc và kiểm tra ``config.yaml``.

Mọi ngưỡng và đường dẫn của dự án nằm trong file cấu hình, không viết cứng
trong code (spec v2 §1). Module này chuyển YAML thành các dataclass lồng nhau
và kiểm tra kiểu ngay lúc nạp để lỗi cấu hình hiện ra sớm, kèm tên khóa cụ
thể.

Quy tắc:

- Khóa thiếu trong file thì lấy giá trị mặc định theo spec §6.
- Khóa có nhưng sai kiểu thì báo lỗi, không tự đoán.
- File cấu hình không tồn tại thì báo lỗi rõ ràng, không lặng lẽ dùng mặc định.
"""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

import yaml

from .faces import STORE_FILENAME as FACE_STORE_FILENAME
from .schedule import (
    ALERT_KINDS,
    DEFAULT_KINDS,
    ScheduleConfig,
    ScheduleError,
    parse_kind_settings,
    parse_window,
)

#: Biến môi trường ghi đè ``camera.source``; dùng để đặt URL camera IP kèm mật
#: khẩu mà không phải ghi mật khẩu vào file cấu hình nào (kể cả
#: ``config.local.yaml``). Có giá trị khác rỗng thì thắng cấu hình file.
CAMERA_SOURCE_ENV = "POSTURE_CAMERA_SOURCE"

#: Biến môi trường chứa mật khẩu ONVIF của camera IP. Mật khẩu **không** được
#: nằm trong ``config.yaml`` (file đó được commit); ``config.yaml`` chỉ có
#: ``camera.onvif.enabled/host/port/user``.
ONVIF_PASSWORD_ENV = "POSTURE_ONVIF_PASSWORD"

#: Giá trị hợp lệ cho các trường có danh sách đóng.
VIEWS = ("front", "side")
MODEL_FORMATS = ("ncnn", "onnx", "pt")
MOCK_MODES = ("auto", True, False)


class ConfigError(ValueError):
    """Cấu hình không hợp lệ (sai kiểu, sai giá trị, sai cấu trúc)."""


# --------------------------------------------------------------------------
# Dataclass cấu hình
# --------------------------------------------------------------------------


@dataclass
class OnvifConfig:
    """Điều khiển PTZ qua ONVIF (tuỳ chọn).

    ``enabled`` có **ba trạng thái**: ``True`` (bắt buộc bật, thiếu host/mật
    khẩu là lỗi cấu hình), ``False`` (bắt buộc tắt), và ``None`` (**tự động**,
    giá trị mặc định). Ở chế độ tự động, PTZ bật khi xác định được ``host`` —
    hoặc vì ``camera.onvif.host`` được điền, hoặc vì ``host`` suy ra từ
    ``camera.source`` khi đó là URL ``rtsp://``. Nhờ vậy một người dùng chỉ đặt
    ``POSTURE_CAMERA_SOURCE`` là camera IP không phải khai địa chỉ thêm lần nữa.

    Ngoại lệ duy nhất: ``camera.onvif.enabled: true`` ghi đè lên nguồn —
    xem :func:`_resolve_onvif`.

    **Không có trường mật khẩu.** Mật khẩu đọc từ biến môi trường
    :data:`ONVIF_PASSWORD_ENV` qua :func:`onvif_password`, nên ``repr`` của
    cấu hình, log và ``config.yaml`` (file được commit) không bao giờ chứa nó.
    """

    enabled: bool | None = None
    host: str = ""
    port: int = 80
    user: str = "admin"


@dataclass
class CameraSpeakerConfig:
    """Loa của camera IP, phát qua RTSP backchannel (tuỳ chọn, mặc định tắt).

    **Tách khỏi ``camera.onvif`` có chủ đích**: hai mục dùng hai cổng khác
    nhau cho hai tài nguyên khác nhau. ``camera.onvif.port`` là cổng **HTTP
    ONVIF** (mặc định 80) để điều khiển PTZ; ``camera.speaker.port`` là cổng
    **RTSP** (mặc định 554) để mở backchannel. Gộp chung một mục thì cấu hình
    một bên làm hỏng bên kia — đúng lỗi mà việc tách này sửa.

    **Không có trường mật khẩu** (giống :class:`OnvifConfig`): mật khẩu đọc từ
    biến môi trường :data:`ONVIF_PASSWORD_ENV` qua :func:`onvif_password`, nên
    ``repr`` của cấu hình, log và ``config.yaml`` (file được commit) không bao
    giờ chứa nó.
    """

    enabled: bool = False
    host: str = ""
    port: int = 554
    user: str = ""
    stream_path: str = "/1/2"


@dataclass
class CameraConfig:
    source: str = "usb:0"
    width: int = 640
    height: int = 480
    view: str = "front"
    onvif: OnvifConfig = field(default_factory=OnvifConfig)
    speaker: CameraSpeakerConfig = field(default_factory=CameraSpeakerConfig)

    def __repr__(self) -> str:
        # ``source`` có thể là URL RTSP kèm mật khẩu (đặt qua biến môi trường).
        # ``repr(config)`` hay lọt vào log và traceback, nên che ngay tại đây —
        # dataclass mặc định in nguyên giá trị.
        return (
            f"CameraConfig(source={redact_camera_source(self.source)!r}, "
            f"width={self.width}, height={self.height}, view={self.view!r}, "
            f"onvif={self.onvif!r}, speaker={self.speaker!r})"
        )


@dataclass
class FaceConfig:
    """Nhận diện khuôn mặt (YuNet + SFace), spec V3 §6.

    ``match_threshold`` là **ngưỡng cosine** và mặc định ``None`` = **chưa
    đo**. Spec §5.13 cấm chép ngưỡng từ tài liệu hay repo khác vào làm mặc
    định: chưa đo thì tính năng phải **không chạy**, chứ không được chạy với
    một con số bịa. Vì vậy ``enabled: true`` cùng ``match_threshold: null`` là
    tổ hợp **không hợp lệ về nghiệp vụ** và :func:`_parse_face` báo
    :class:`ConfigError` ngay lúc nạp — im lặng chạy tiếp sẽ khiến người vận
    hành tưởng nhận diện đã bật.

    ``enabled`` để trống/``null`` nghĩa là **tự động**: bật khi đã có ngưỡng,
    tắt khi chưa (cùng tinh thần ``camera.onvif.enabled``). Ghi rõ ``false``
    thì luôn tắt, kể cả khi đã có ngưỡng.

    Không có trường mật khẩu hay bí mật: đây là cấu hình thuần số/đường dẫn.
    """

    enabled: bool | None = None
    detector: str = "yunet.onnx"
    recognizer: str = "sface.onnx"
    interval_s: float = 2.0
    #: ``None`` = chưa đo ngưỡng → tính năng không chạy (spec §5.13, §6).
    match_threshold: float | None = None
    impostor_hold_s: float = 5.0
    enroll_step_s: float = 1.5
    enroll_min_samples: int = 3
    detect_width: int = 320
    clahe_enabled: bool = True
    store_path: str = f"data/{FACE_STORE_FILENAME}"


@dataclass
class ModelConfig:
    name: str = "yolo11n-pose"
    format: str = "ncnn"
    imgsz: int = 320
    target_fps: int = 5
    kp_conf_min: float = 0.5
    export_on_pc: bool = False


@dataclass
class TrackingConfig:
    enabled: bool = True
    tracker: str = "botsort.yaml"


@dataclass
class PhoneConfig:
    """Phát hiện "đang dùng điện thoại" bằng model detect COCO thứ hai (spec §5).

    Model pose ``yolo11n-pose`` chỉ có lớp ``person`` nên không bao giờ trả hộp
    ``cell phone``; muốn có hộp đó phải chạy thêm ``yolo11n`` (80 lớp COCO) và
    lấy lớp 67. Trên Pi 4 đo được 98,6 ms cho **một lần detect**, trên khung
    **tổng hợp** 640x480 — chỉ inference, không gồm capture và không phải
    khung camera thật.

    Con số đó **không** phải chi phí detect trong pipeline, nên không suy ra
    được FPS cho cấu hình có detect. Phép đo pipeline thật duy nhất của dự án
    là pose-only: 199,25 ms/khung → 5,02 FPS. Vì vậy
    ``detect_every_n_frames: 2`` **chưa được biện minh bằng phép đo FPS nào** —
    nó chỉ là lựa chọn tạm thời, phải đo lại trên Pi bằng
    ``benchmark --profile pose_phone`` (SPEC_V3 §4.3, §8.1).

    ``enabled: false`` tắt sạch sẽ: không nạp model, không gọi detect, không
    tạo cảnh báo điện thoại.
    """

    enabled: bool = True
    #: Tên model COCO 80 lớp (có lớp ``cell phone``), không phải model pose.
    detect_model: str = "yolo11n"
    #: Trọng số model detect; trống nghĩa là ``<detect_model>.pt``.
    detect_weights: str = ""
    #: Chạy detect mỗi N khung. Giá trị 1 = mọi khung (không đạt FPS trên Pi).
    detect_every_n_frames: int = 2
    imgsz: int = 320
    conf_threshold: float = 0.25
    #: Hộp detect còn dùng được bao lâu sau lần detect (giây).
    box_ttl_s: float = 0.5
    #: Phải chạm liên tục bao lâu mới thành "sự kiện" dùng điện thoại (giây).
    hold_s: float = 2.0
    #: Khoảng cách cho phép giữa cổ tay và mép hộp điện thoại (pixel). Mặc
    #: định 0 = chạm chính xác theo yêu cầu "khoảng cách = 0" của đề tài.
    touching_slack_px: float = 0.0


@dataclass
class ThresholdsConfig:
    head_down_ratio: float = 0.70
    too_close_ratio: float = 1.25
    shoulder_tilt_deg: float = 8.0
    head_tilt_deg: float = 12.0
    lean_x: float = 0.35
    look_away_yaw: float = 0.5
    neck_angle_drop_deg: float = 15.0


@dataclass
class TimingConfig:
    smooth_window_s: float = 1.0
    bad_hold_s: float = 5.0
    good_hold_s: float = 2.0
    alert_cooldown_s: float = 30.0
    escalate_after_s: float = 60.0
    break_after_min: float = 45.0
    absent_reset_s: float = 120.0
    drowsy_hold_s: float = 10.0


@dataclass
class AlertsConfig:
    buzzer_enabled: bool = True
    vibration_enabled: bool = True
    #: Cho phép cảnh báo bằng GPIO (kêu/rung). Mặc định TẮT vì chủ đề đã đổi
    #: sang theo dõi người học, không chấm điểm tư thế; bật lên chỉ khi thực sự
    #: muốn cảnh báo bằng phần cứng. LED vẫn cập nhật trạng thái khi tắt.
    gpio_alert_enabled: bool = False


@dataclass
class PinsConfig:
    led_green: int = 17
    led_yellow: int = 27
    led_red: int = 22
    buzzer: int = 18
    vibration: int = 23
    trig: int = 5
    echo: int = 6


@dataclass
class HardwareConfig:
    mock: str | bool = "auto"
    pins: PinsConfig = field(default_factory=PinsConfig)


@dataclass
class SensorsConfig:
    ultrasonic_enabled: bool = True
    min_distance_cm: float = 35.0


@dataclass
class PresenceConfig:
    """Mục ``presence``: ngưỡng cho bộ lọc trạng thái hiện diện.

    ``absent_grace_s`` khớp ``presence.DEFAULT_ABSENT_HOLD_S``: số giây vắng
    **liên tục** trước khi coi là đã rời khung. Giá trị này chỉ được
    ``__main__.py`` đọc rồi truyền vào ``PresenceTracker(absent_hold_s=...)``;
    ``presence.py`` không import module này (ngưỡng là tham số constructor).
    """

    absent_grace_s: float = 3.0


@dataclass
class StorageConfig:
    db_path: str = "data/posture.db"
    retention_days: int = 30


@dataclass
class WebConfig:
    host: str = "0.0.0.0"
    port: int = 8000
    stream_enabled: bool = False


@dataclass
class Config:
    """Toàn bộ cấu hình của ứng dụng."""

    camera: CameraConfig = field(default_factory=CameraConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    tracking: TrackingConfig = field(default_factory=TrackingConfig)
    #: Phát hiện dùng điện thoại (model detect COCO thứ hai).
    phone: PhoneConfig = field(default_factory=PhoneConfig)
    thresholds: ThresholdsConfig = field(default_factory=ThresholdsConfig)
    timing: TimingConfig = field(default_factory=TimingConfig)
    alerts: AlertsConfig = field(default_factory=AlertsConfig)
    hardware: HardwareConfig = field(default_factory=HardwareConfig)
    sensors: SensorsConfig = field(default_factory=SensorsConfig)
    #: Ngưỡng trạng thái hiện diện (``presence``); chỉ tác dụng khi
    #: ``schedule.enabled: true`` (xem ``config.yaml``).
    presence: PresenceConfig = field(default_factory=PresenceConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    web: WebConfig = field(default_factory=WebConfig)
    #: Nhận diện khuôn mặt (``face``); mặc định TẮT vì chưa đo ngưỡng.
    face: FaceConfig = field(default_factory=FaceConfig)
    #: Giờ học quy định (``schedule``); mặc định tắt.
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    #: Nhãn tư thế vẫn được tính (để hiển thị/debug) nhưng mặc định KHÔNG
    #: được đưa vào tập nhãn sinh cảnh báo. ``ABSENT`` không bị ảnh hưởng.
    posture_labels_enabled: bool = False

    #: Đường dẫn file cấu hình đã nạp (rỗng nếu tạo bằng tay).
    path: str = ""


# --------------------------------------------------------------------------
# Hàm kiểm tra kiểu
# --------------------------------------------------------------------------


def _where(section: str, key: str) -> str:
    return f"{section}.{key}" if section else key


def _as_dict(value: Any, section: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(
            f"Mục '{section}' phải là một ánh xạ (dict), nhận được "
            f"{type(value).__name__}."
        )
    return value


def _get_int(data: dict[str, Any], key: str, default: int, section: str) -> int:
    if key not in data or data[key] is None:
        return default
    value = data[key]
    # bool là lớp con của int trong Python, phải loại riêng.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(
            f"'{_where(section, key)}' phải là số nguyên, nhận được "
            f"{type(value).__name__}: {value!r}."
        )
    return value


def _get_float(
    data: dict[str, Any], key: str, default: float, section: str
) -> float:
    if key not in data or data[key] is None:
        return default
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(
            f"'{_where(section, key)}' phải là số, nhận được "
            f"{type(value).__name__}: {value!r}."
        )
    return float(value)


def _get_bool(
    data: dict[str, Any], key: str, default: bool, section: str
) -> bool:
    if key not in data or data[key] is None:
        return default
    value = data[key]
    if not isinstance(value, bool):
        raise ConfigError(
            f"'{_where(section, key)}' phải là true/false, nhận được "
            f"{type(value).__name__}: {value!r}."
        )
    return value


def _get_str(
    data: dict[str, Any], key: str, default: str, section: str
) -> str:
    if key not in data or data[key] is None:
        return default
    value = data[key]
    if not isinstance(value, str):
        raise ConfigError(
            f"'{_where(section, key)}' phải là chuỗi, nhận được "
            f"{type(value).__name__}: {value!r}."
        )
    return value


def _get_choice(
    data: dict[str, Any],
    key: str,
    default: str,
    allowed: tuple[str, ...],
    section: str,
) -> str:
    value = _get_str(data, key, default, section)
    if value not in allowed:
        raise ConfigError(
            f"'{_where(section, key)}' phải là một trong {allowed}, "
            f"nhận được {value!r}."
        )
    return value


# --------------------------------------------------------------------------
# Nạp từng mục
# --------------------------------------------------------------------------


def _normalize_env_source(override: str) -> str:
    """Chuẩn hoá giá trị biến môi trường thành cú pháp ``camera.source``.

    Người dùng tự nhiên dán thẳng URL RTSP vào ``POSTURE_CAMERA_SOURCE`` mà
    không kèm tiền tố loại nguồn, trong khi ``config.yaml`` bắt buộc tiền tố.
    Biến môi trường chấp nhận cả hai dạng: giá trị bắt đầu bằng ``rtsp://``
    hoặc ``rtsps://`` mà **không** có tiền tố ``usb|file|rtsp|rtsps|picamera``
    được hiểu ngầm là ``rtsp:``. Không nới lỏng ``parse_camera_source``: ở
    ``config.yaml`` tiền tố vẫn là bắt buộc.
    """
    text = override.strip()
    lowered = text.lower()
    if _SOURCE_PREFIX.match(lowered):
        return text
    if lowered.startswith(("rtsp://", "rtsps://")):
        return f"rtsp:{text}"
    return text


def _get_optional_bool(
    data: dict[str, Any], key: str, section: str
) -> bool | None:
    """Như :func:`_get_bool` nhưng thiếu khóa/``null`` trả ``None`` (tự động).

    ``None`` không phải giá trị sai kiểu — nó là trạng thái "người dùng không
    quyết định", để :func:`_resolve_onvif` tự suy ra. Chuỗi ``"auto"`` cũng
    được chấp nhận để YAML đọc dễ hơn ``null``.
    """
    if key not in data or data[key] is None:
        return None
    value = data[key]
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() == "auto":
        return None
    raise ConfigError(
        f"'{_where(section, key)}' phải là true, false hoặc auto/để trống, "
        f"nhận được {value!r}."
    )


def _parse_onvif(raw: Any) -> OnvifConfig:
    """Nạp mục ``camera.onvif`` (tuỳ chọn; thiếu mục = tự động).

    Chỉ đọc và kiểm tra kiểu. Việc suy ra ``host``/``enabled`` từ
    ``camera.source`` nằm ở :func:`_resolve_onvif`, vì nó cần nguồn ảnh đã
    được chuẩn hoá (kể cả phần ghi đè bằng biến môi trường).

    Mật khẩu **không** đọc từ YAML.
    """
    data = _as_dict(raw, "camera.onvif")
    cfg = OnvifConfig(
        enabled=_get_optional_bool(data, "enabled", "camera.onvif"),
        host=_get_str(data, "host", OnvifConfig.host, "camera.onvif"),
        port=_get_int(data, "port", OnvifConfig.port, "camera.onvif"),
        user=_get_str(data, "user", OnvifConfig.user, "camera.onvif"),
    )
    if not 0 < cfg.port < 65536:
        raise ConfigError("'camera.onvif.port' phải nằm trong khoảng 1..65535.")
    return cfg


def _source_host(source: str) -> str:
    """Host của camera suy ra từ ``camera.source``; ``""`` nếu không suy được.

    Chỉ URL ``rtsp://``/``rtsps://`` mới mang một địa chỉ máy. ``usb:``,
    ``file:`` và ``picamera`` không có host nên trả rỗng — khi đó PTZ phải
    được cấu hình tay ở ``camera.onvif.host``.
    """
    try:
        kind, value = parse_camera_source(source)
    except ConfigError:
        return ""
    if kind != "rtsp" or not isinstance(value, str):
        return ""
    try:
        host = urlsplit(value).hostname or ""
    except ValueError:
        return ""
    return host


def _source_credentials(source: str) -> tuple[str, str]:
    """``(user, password)`` nhúng trong URL ``camera.source``; rỗng nếu không có.

    Camera IP thường được đặt bằng ``POSTURE_CAMERA_SOURCE="rtsp://user:pass@host/..."``,
    nên URL đó đã mang sẵn tài khoản của chính camera. Dùng lại cho ONVIF tránh
    bắt người dùng nhập cùng một mật khẩu hai lần. Giá trị chỉ sống trong bộ
    nhớ của tiến trình, không ghi vào file cấu hình.
    """
    try:
        kind, value = parse_camera_source(source)
    except ConfigError:
        return "", ""
    if kind != "rtsp" or not isinstance(value, str):
        return "", ""
    try:
        parts = urlsplit(value)
    except ValueError:
        return "", ""
    return unquote(parts.username or ""), unquote(parts.password or "")


def _resolve_onvif(onvif: OnvifConfig, source: str, *, from_env: bool) -> OnvifConfig:
    """Chốt ``host`` và ``enabled`` của PTZ, kèm kiểm tra nhất quán.

    Quy ước (một địa chỉ camera, một nơi khai):

    1. ``camera.onvif.host`` điền tay thì dùng luôn — đây là đường ghi đè.
    2. Trống thì suy ra từ ``camera.source`` khi đó là URL ``rtsp://``. Nhờ
       vậy đặt ``POSTURE_CAMERA_SOURCE`` là đủ để cả xem ảnh lẫn điều khiển
       PTZ, không phải lặp lại IP ở ba nơi.
    3. ``enabled`` để trống/``auto`` → bật khi có ``host``. ``true`` vẫn bắt
       buộc bật (và thiếu thông tin thì báo lỗi ngay lúc nạp), ``false`` tắt
       hẳn — người dùng chủ động tắt thì tôn trọng, route sẽ báo rõ.

    Args:
        onvif: cấu hình đã nạp từ YAML.
        source: ``camera.source`` **sau** khi áp dụng biến môi trường.
        from_env: nguồn ảnh đến từ ``POSTURE_CAMERA_SOURCE`` hay không; chỉ để
            chọn câu hướng dẫn trong thông điệp lỗi.

    Raises:
        ConfigError: ``enabled: true`` mà không xác định được ``host`` hoặc
            không có mật khẩu khả dụng. Thông điệp không chứa mật khẩu.
    """
    if not onvif.host.strip():
        onvif.host = _source_host(source)

    explicit = onvif.enabled is not None
    if not explicit:
        onvif.enabled = bool(onvif.host.strip())

    if onvif.enabled and explicit:
        # Người dùng nói rõ ``enabled: true``: thiếu thông tin là lỗi cấu hình,
        # báo ngay lúc nạp (giữ nguyên hành vi cũ).
        _check_onvif_ready(onvif, source, from_env=from_env)
    elif onvif.enabled:
        # Chế độ tự động: không chặn chương trình chạy chỉ vì chưa có mật khẩu
        # — người dùng có thể chỉ muốn xem ảnh. Thiếu mật khẩu thì
        # ``POST /api/ptz`` báo lỗi tiếng Việt riêng, còn luồng camera chạy
        # bình thường.
        if not onvif_credentials(onvif, source)[1]:
            onvif.enabled = False
    return onvif


def _check_onvif_ready(
    onvif: OnvifConfig, source: str, *, from_env: bool
) -> None:
    """Kiểm tra ``enabled: true`` có đủ host và mật khẩu; ném ``ConfigError``.

    Thông điệp chỉ nêu **tên biến môi trường**, không bao giờ chứa giá trị mật
    khẩu, và mọi chỗ chèn ``host`` đều đi qua :func:`redact_camera_source`.
    """
    safe_host = redact_camera_source(onvif.host)
    if not onvif.host.strip():
        hint = (
            f"Đặt biến môi trường {CAMERA_SOURCE_ENV} thành URL RTSP của "
            "camera, hoặc điền 'camera.onvif.host'."
            if not from_env
            else "Điền 'camera.onvif.host' trong config.yaml."
        )
        raise ConfigError(
            "'camera.onvif.enabled' là true nhưng không xác định được "
            "'camera.onvif.host'. " + hint
        )
    if not onvif_credentials(onvif, source)[1]:
        raise ConfigError(
            "'camera.onvif.enabled' là true nhưng chưa có mật khẩu ONVIF "
            f"cho camera {safe_host!r}. Đặt biến môi trường "
            f"{ONVIF_PASSWORD_ENV}, hoặc đặt {CAMERA_SOURCE_ENV} thành URL "
            "RTSP có kèm tài khoản (mật khẩu không được ghi vào "
            "config.yaml)."
        )


def onvif_credentials(onvif: OnvifConfig, source: str) -> tuple[str, str]:
    """``(user, password)`` để mở phiên ONVIF, theo thứ tự ưu tiên.

    1. ``POSTURE_ONVIF_PASSWORD`` có giá trị → dùng ``camera.onvif.user`` (mặc
       định ``admin``) với mật khẩu đó. Biến môi trường luôn thắng.
    2. Không có thì lấy cặp tài khoản nhúng trong URL ``camera.source`` — cùng
       một camera nên cùng một tài khoản.
    3. Không có nguồn nào → ``""`` cho mật khẩu; nơi gọi tự báo lỗi.

    Không bao giờ trả mật khẩu đọc từ file cấu hình.
    """
    env_password = onvif_password()
    if env_password:
        return onvif.user, env_password
    user, password = _source_credentials(source)
    if password:
        return user, password
    return onvif.user, ""


def _parse_speaker(raw: Any) -> CameraSpeakerConfig:
    """Nạp mục ``camera.speaker`` (tuỳ chọn; thiếu mục = tắt).

    Mật khẩu **không** đọc từ YAML, giống ``camera.onvif``: chỉ biến môi
    trường :data:`ONVIF_PASSWORD_ENV`. Ở đây **không** đòi mật khẩu lúc nạp dù
    ``enabled: true`` — camera của dự án không bắt buộc đăng nhập cho
    backchannel, và ``speaker_config_from_config`` mới là nơi quyết định một
    lần phát có đủ điều kiện hay không. Đòi ở hai nơi sẽ khoá cứng cấu hình
    vào một giả định về camera.

    Mọi chỗ chèn ``host`` vào thông điệp lỗi đều đi qua
    :func:`redact_camera_source`, giống ``_parse_onvif`` — người dùng hay dán
    cả URL RTSP có mật khẩu vào ô ``host``.
    """
    data = _as_dict(raw, "camera.speaker")
    cfg = CameraSpeakerConfig(
        enabled=_get_bool(
            data, "enabled", CameraSpeakerConfig.enabled, "camera.speaker"
        ),
        host=_get_str(data, "host", CameraSpeakerConfig.host, "camera.speaker"),
        port=_get_int(data, "port", CameraSpeakerConfig.port, "camera.speaker"),
        user=_get_str(data, "user", CameraSpeakerConfig.user, "camera.speaker"),
        stream_path=_get_str(
            data,
            "stream_path",
            CameraSpeakerConfig.stream_path,
            "camera.speaker",
        ),
    )
    if not 0 < cfg.port < 65536:
        raise ConfigError(
            "'camera.speaker.port' phải nằm trong khoảng 1..65535."
        )
    if cfg.enabled and not cfg.host.strip():
        raise ConfigError(
            "'camera.speaker.enabled' là true nhưng 'camera.speaker.host' "
            "đang trống. Điền địa chỉ camera IP (ví dụ 192.168.1.50)."
        )
    if "://" in cfg.host:
        # Lỗi hay gặp: dán cả URL RTSP (có mật khẩu) vào ô host. Thông điệp
        # phải che userinfo — URL đó chứa mật khẩu thật.
        safe_host = redact_camera_source(cfg.host)
        raise ConfigError(
            f"'camera.speaker.host' = {safe_host!r} phải là tên máy hoặc IP, "
            "không kèm 'rtsp://' hay thông tin đăng nhập. Đặt phần đường dẫn "
            "vào 'camera.speaker.stream_path'."
        )
    return cfg


def _parse_camera(raw: Any) -> CameraConfig:
    data = _as_dict(raw, "camera")
    cfg = CameraConfig(
        source=_get_str(data, "source", CameraConfig.source, "camera"),
        width=_get_int(data, "width", CameraConfig.width, "camera"),
        height=_get_int(data, "height", CameraConfig.height, "camera"),
        view=_get_choice(data, "view", CameraConfig.view, VIEWS, "camera"),
        onvif=_parse_onvif(data.get("onvif")),
        speaker=_parse_speaker(data.get("speaker")),
    )
    # Nguồn ảnh có thể ghi đè bằng biến môi trường để đặt URL camera IP kèm
    # mật khẩu mà không phải ghi mật khẩu vào bất kỳ file cấu hình nào.
    override = os.environ.get(CAMERA_SOURCE_ENV, "").strip()
    if override:
        cfg.source = _normalize_env_source(override)

    # Kiểm tra cú pháp nguồn ngay lúc nạp, để lỗi hiện ra trước khi mở camera.
    parse_camera_source(cfg.source)

    # PTZ được chốt **sau** khi biết nguồn ảnh cuối cùng (kể cả phần ghi đè
    # bằng biến môi trường), nên host suy ra từ URL RTSP phản ánh đúng camera
    # đang dùng.
    cfg.onvif = _resolve_onvif(cfg.onvif, cfg.source, from_env=bool(override))
    if cfg.width <= 0 or cfg.height <= 0:
        raise ConfigError(
            f"'camera.width' và 'camera.height' phải là số dương, nhận được "
            f"{cfg.width}x{cfg.height}."
        )
    return cfg


def _parse_model(raw: Any) -> ModelConfig:
    data = _as_dict(raw, "model")
    cfg = ModelConfig(
        name=_get_str(data, "name", ModelConfig.name, "model"),
        format=_get_choice(
            data, "format", ModelConfig.format, MODEL_FORMATS, "model"
        ),
        imgsz=_get_int(data, "imgsz", ModelConfig.imgsz, "model"),
        target_fps=_get_int(
            data, "target_fps", ModelConfig.target_fps, "model"
        ),
        kp_conf_min=_get_float(
            data, "kp_conf_min", ModelConfig.kp_conf_min, "model"
        ),
        export_on_pc=_get_bool(
            data, "export_on_pc", ModelConfig.export_on_pc, "model"
        ),
    )
    if cfg.imgsz <= 0:
        raise ConfigError("'model.imgsz' phải là số dương.")
    if cfg.target_fps <= 0:
        raise ConfigError("'model.target_fps' phải là số dương.")
    if not 0.0 <= cfg.kp_conf_min <= 1.0:
        raise ConfigError("'model.kp_conf_min' phải nằm trong [0, 1].")
    return cfg


def _parse_tracking(raw: Any) -> TrackingConfig:
    data = _as_dict(raw, "tracking")
    return TrackingConfig(
        enabled=_get_bool(
            data, "enabled", TrackingConfig.enabled, "tracking"
        ),
        tracker=_get_str(data, "tracker", TrackingConfig.tracker, "tracking"),
    )


def _parse_phone(raw: Any) -> PhoneConfig:
    """Nạp mục ``phone`` (tuỳ chọn; thiếu mục = dùng mặc định ở trên).

    Lỗi kiểu/giá trị được báo ngay lúc nạp để ``enabled: true`` không bao giờ
    chạy với nhịp detect hay ngưỡng vô lý — sai ở đây làm hỏng cả vòng lặp.
    """
    data = _as_dict(raw, "phone")
    base = PhoneConfig()
    cfg = PhoneConfig(
        enabled=_get_bool(data, "enabled", base.enabled, "phone"),
        detect_model=_get_str(
            data, "detect_model", base.detect_model, "phone"
        ),
        detect_weights=_get_str(
            data, "detect_weights", base.detect_weights, "phone"
        ),
        detect_every_n_frames=_get_int(
            data,
            "detect_every_n_frames",
            base.detect_every_n_frames,
            "phone",
        ),
        imgsz=_get_int(data, "imgsz", base.imgsz, "phone"),
        conf_threshold=_get_float(
            data, "conf_threshold", base.conf_threshold, "phone"
        ),
        box_ttl_s=_get_float(data, "box_ttl_s", base.box_ttl_s, "phone"),
        hold_s=_get_float(data, "hold_s", base.hold_s, "phone"),
        touching_slack_px=_get_float(
            data, "touching_slack_px", base.touching_slack_px, "phone"
        ),
    )
    if not cfg.detect_model.strip():
        raise ConfigError("'phone.detect_model' phải là chuỗi không rỗng.")
    if cfg.detect_every_n_frames < 1:
        raise ConfigError("'phone.detect_every_n_frames' phải >= 1.")
    if cfg.imgsz <= 0:
        raise ConfigError("'phone.imgsz' phải là số dương.")
    if not 0.0 <= cfg.conf_threshold <= 1.0:
        raise ConfigError("'phone.conf_threshold' phải nằm trong [0, 1].")
    if cfg.box_ttl_s < 0:
        raise ConfigError("'phone.box_ttl_s' không được âm.")
    if cfg.hold_s < 0:
        raise ConfigError("'phone.hold_s' không được âm.")
    if cfg.touching_slack_px < 0:
        raise ConfigError("'phone.touching_slack_px' không được âm.")
    return cfg


def _parse_thresholds(raw: Any) -> ThresholdsConfig:
    data = _as_dict(raw, "thresholds")
    base = ThresholdsConfig()
    return ThresholdsConfig(
        head_down_ratio=_get_float(
            data, "head_down_ratio", base.head_down_ratio, "thresholds"
        ),
        too_close_ratio=_get_float(
            data, "too_close_ratio", base.too_close_ratio, "thresholds"
        ),
        shoulder_tilt_deg=_get_float(
            data, "shoulder_tilt_deg", base.shoulder_tilt_deg, "thresholds"
        ),
        head_tilt_deg=_get_float(
            data, "head_tilt_deg", base.head_tilt_deg, "thresholds"
        ),
        lean_x=_get_float(data, "lean_x", base.lean_x, "thresholds"),
        look_away_yaw=_get_float(
            data, "look_away_yaw", base.look_away_yaw, "thresholds"
        ),
        neck_angle_drop_deg=_get_float(
            data,
            "neck_angle_drop_deg",
            base.neck_angle_drop_deg,
            "thresholds",
        ),
    )


def _parse_timing(raw: Any) -> TimingConfig:
    data = _as_dict(raw, "timing")
    base = TimingConfig()
    return TimingConfig(
        smooth_window_s=_get_float(
            data, "smooth_window_s", base.smooth_window_s, "timing"
        ),
        bad_hold_s=_get_float(
            data, "bad_hold_s", base.bad_hold_s, "timing"
        ),
        good_hold_s=_get_float(
            data, "good_hold_s", base.good_hold_s, "timing"
        ),
        alert_cooldown_s=_get_float(
            data, "alert_cooldown_s", base.alert_cooldown_s, "timing"
        ),
        escalate_after_s=_get_float(
            data, "escalate_after_s", base.escalate_after_s, "timing"
        ),
        break_after_min=_get_float(
            data, "break_after_min", base.break_after_min, "timing"
        ),
        absent_reset_s=_get_float(
            data, "absent_reset_s", base.absent_reset_s, "timing"
        ),
        drowsy_hold_s=_get_float(
            data, "drowsy_hold_s", base.drowsy_hold_s, "timing"
        ),
    )


def _parse_alerts(raw: Any) -> AlertsConfig:
    data = _as_dict(raw, "alerts")
    return AlertsConfig(
        buzzer_enabled=_get_bool(
            data, "buzzer_enabled", AlertsConfig.buzzer_enabled, "alerts"
        ),
        vibration_enabled=_get_bool(
            data,
            "vibration_enabled",
            AlertsConfig.vibration_enabled,
            "alerts",
        ),
        gpio_alert_enabled=_get_bool(
            data,
            "gpio_alert_enabled",
            AlertsConfig.gpio_alert_enabled,
            "alerts",
        ),
    )


def _parse_schedule(raw: Any) -> ScheduleConfig:
    """Nạp mục ``schedule``: giờ học quy định (mặc định tắt).

    Lỗi giờ/thứ được báo **ngay lúc nạp** (spec v2 §1, §11.2) và đổi thành
    :class:`ConfigError` để API công khai của cấu hình chỉ có một kiểu lỗi.

    Mục ``kinds`` cho phép tắt riêng từng loại cảnh báo và đặt cooldown/thời
    gian giữ riêng cho từng loại. Khóa không có trong ``kinds`` lấy mặc định
    của module ``schedule``; khóa lạ bị báo lỗi để người dùng không tưởng
    nhầm là đã bật.
    """
    data = _as_dict(raw, "schedule")
    windows: list[Any] = []
    raw_windows = data.get("windows")
    if raw_windows is not None:
        if not isinstance(raw_windows, (list, tuple)):
            raise ConfigError(
                "'schedule.windows' phải là danh sách khung giờ, nhận được "
                f"{type(raw_windows).__name__}."
            )
        for index, item in enumerate(raw_windows):
            try:
                windows.append(parse_window(item, f"schedule.windows[{index}]"))
            except ScheduleError as exc:
                raise ConfigError(str(exc)) from exc

    kinds: dict[str, Any] = {}
    raw_kinds = data.get("kinds")
    if raw_kinds is not None:
        if not isinstance(raw_kinds, dict):
            raise ConfigError(
                "'schedule.kinds' phải là ánh xạ theo tên loại cảnh báo "
                f"({', '.join(ALERT_KINDS)}), nhận được "
                f"{type(raw_kinds).__name__}."
            )
        for name, item in raw_kinds.items():
            if name not in ALERT_KINDS:
                raise ConfigError(
                    f"'schedule.kinds.{name}' không phải loại cảnh báo hợp lệ; "
                    f"dùng một trong {ALERT_KINDS}."
                )
            try:
                kinds[name] = parse_kind_settings(
                    item, f"schedule.kinds.{name}"
                )
            except ScheduleError as exc:
                raise ConfigError(str(exc)) from exc

    enabled = _get_bool(
        data, "enabled", ScheduleConfig.enabled, "schedule"
    )
    if enabled and not windows:
        raise ConfigError(
            "'schedule.enabled' là true nhưng 'schedule.windows' đang trống. "
            "Thêm ít nhất một khung giờ học hoặc đặt enabled: false."
        )

    cfg = ScheduleConfig(
        enabled=enabled,
        windows=tuple(windows),
        kinds={**DEFAULT_KINDS, **kinds},
    )
    return cfg


def _parse_pins(raw: Any) -> PinsConfig:
    data = _as_dict(raw, "hardware.pins")
    base = PinsConfig()
    return PinsConfig(
        led_green=_get_int(data, "led_green", base.led_green, "hardware.pins"),
        led_yellow=_get_int(
            data, "led_yellow", base.led_yellow, "hardware.pins"
        ),
        led_red=_get_int(data, "led_red", base.led_red, "hardware.pins"),
        buzzer=_get_int(data, "buzzer", base.buzzer, "hardware.pins"),
        vibration=_get_int(
            data, "vibration", base.vibration, "hardware.pins"
        ),
        trig=_get_int(data, "trig", base.trig, "hardware.pins"),
        echo=_get_int(data, "echo", base.echo, "hardware.pins"),
    )


def _parse_hardware(raw: Any) -> HardwareConfig:
    data = _as_dict(raw, "hardware")
    mock: str | bool = "auto"
    if "mock" in data and data["mock"] is not None:
        value = data["mock"]
        if isinstance(value, bool):
            mock = value
        elif isinstance(value, str) and value in ("auto", "true", "false"):
            # Chấp nhận dạng chuỗi để người dùng YAML khỏi phải nhớ cú pháp.
            mock = True if value == "true" else False if value == "false" else "auto"
        else:
            raise ConfigError(
                "'hardware.mock' phải là auto, true hoặc false, nhận được "
                f"{value!r}."
            )
    return HardwareConfig(mock=mock, pins=_parse_pins(data.get("pins")))


def _parse_sensors(raw: Any) -> SensorsConfig:
    data = _as_dict(raw, "sensors")
    cfg = SensorsConfig(
        ultrasonic_enabled=_get_bool(
            data,
            "ultrasonic_enabled",
            SensorsConfig.ultrasonic_enabled,
            "sensors",
        ),
        min_distance_cm=_get_float(
            data,
            "min_distance_cm",
            SensorsConfig.min_distance_cm,
            "sensors",
        ),
    )
    if cfg.min_distance_cm <= 0:
        raise ConfigError("'sensors.min_distance_cm' phải là số dương.")
    return cfg


def _parse_presence(raw: Any) -> PresenceConfig:
    """Nạp mục ``presence`` (tuỳ chọn; thiếu mục = dùng mặc định).

    Giữ tinh thần của :func:`_parse_sensors`: giá trị vô lý bị từ chối ngay
    lúc nạp thay vì để ``PresenceTracker`` ném ``ValueError`` giữa vòng lặp
    camera.
    """
    data = _as_dict(raw, "presence")
    cfg = PresenceConfig(
        absent_grace_s=_get_float(
            data,
            "absent_grace_s",
            PresenceConfig.absent_grace_s,
            "presence",
        ),
    )
    if cfg.absent_grace_s < 0:
        raise ConfigError("'presence.absent_grace_s' không được âm.")
    return cfg


def _parse_storage(raw: Any) -> StorageConfig:
    data = _as_dict(raw, "storage")
    cfg = StorageConfig(
        db_path=_get_str(data, "db_path", StorageConfig.db_path, "storage"),
        retention_days=_get_int(
            data, "retention_days", StorageConfig.retention_days, "storage"
        ),
    )
    if cfg.retention_days < 0:
        raise ConfigError("'storage.retention_days' không được âm.")
    return cfg


def _get_optional_float(
    data: dict[str, Any], key: str, section: str
) -> float | None:
    """Như :func:`_get_float` nhưng thiếu khóa/``null`` trả ``None``.

    Dùng cho ``face.match_threshold``: ``None`` là trạng thái **hợp lệ và có
    nghĩa** — "chưa đo ngưỡng" — chứ không phải giá trị thiếu. Sai kiểu
    (chuỗi, bool) vẫn là lỗi cấu hình.
    """
    if key not in data or data[key] is None:
        return None
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(
            f"'{_where(section, key)}' phải là số hoặc null (chưa đo), nhận "
            f"được {type(value).__name__}: {value!r}."
        )
    return float(value)


def _parse_face(raw: Any) -> FaceConfig:
    """Nạp mục ``face`` (tuỳ chọn; thiếu mục = tắt).

    Quyết định ở mục 1 của nhiệm vụ: ``enabled: true`` cùng
    ``match_threshold: null`` **báo lỗi lúc nạp**, không lặng lẽ chạy với ngưỡng
    mặc định. Lý do: người dùng ghi ``enabled: true`` nghĩa là họ tin nhận
    diện đang bật; chạy với một con số bịa sẽ tạo ra nhãn MATCH/MISMATCH không
    có cơ sở đo, đúng điều spec §5.13 cấm ("không chép ngưỡng từ tài liệu hay
    repo khác"). Một lỗi cấu hình rõ ràng ở thời điểm nạp rẻ hơn nhiều so với
    một nhãn sai lúc chạy.

    ``enabled`` để trống/``null`` là tự động: bật khi có ngưỡng, tắt khi chưa.
    """
    data = _as_dict(raw, "face")
    cfg = FaceConfig(
        enabled=_get_optional_bool(data, "enabled", "face"),
        detector=_get_str(data, "detector", FaceConfig.detector, "face"),
        recognizer=_get_str(
            data, "recognizer", FaceConfig.recognizer, "face"
        ),
        interval_s=_get_float(
            data, "interval_s", FaceConfig.interval_s, "face"
        ),
        match_threshold=_get_optional_float(data, "match_threshold", "face"),
        impostor_hold_s=_get_float(
            data, "impostor_hold_s", FaceConfig.impostor_hold_s, "face"
        ),
        enroll_step_s=_get_float(
            data, "enroll_step_s", FaceConfig.enroll_step_s, "face"
        ),
        enroll_min_samples=_get_int(
            data, "enroll_min_samples", FaceConfig.enroll_min_samples, "face"
        ),
        detect_width=_get_int(
            data, "detect_width", FaceConfig.detect_width, "face"
        ),
        clahe_enabled=_get_bool(
            data, "clahe_enabled", FaceConfig.clahe_enabled, "face"
        ),
        store_path=_get_str(
            data, "store_path", FaceConfig.store_path, "face"
        ),
    )
    if not cfg.detector.strip():
        raise ConfigError("'face.detector' không được để trống.")
    if not cfg.recognizer.strip():
        raise ConfigError("'face.recognizer' không được để trống.")
    if not cfg.store_path.strip():
        raise ConfigError(
            "'face.store_path' không được để trống; kho khuôn mặt cần một "
            "đường dẫn tệp."
        )
    if cfg.interval_s <= 0:
        raise ConfigError(
            "'face.interval_s' phải là số dương (nhịp nhận diện, giây)."
        )
    if cfg.impostor_hold_s < 0:
        raise ConfigError("'face.impostor_hold_s' không được âm.")
    if cfg.enroll_step_s <= 0:
        raise ConfigError(
            "'face.enroll_step_s' phải là số dương (giây mỗi tư thế)."
        )
    if cfg.enroll_min_samples <= 0:
        raise ConfigError(
            "'face.enroll_min_samples' phải là số dương (số mẫu tối thiểu)."
        )
    if cfg.detect_width <= 0:
        raise ConfigError(
            "'face.detect_width' phải là số dương (chiều rộng thu nhỏ trước "
            "khi detect, spec §5.13)."
        )
    if cfg.match_threshold is not None:
        if not (-1.0 <= cfg.match_threshold <= 1.0):
            raise ConfigError(
                "'face.match_threshold' phải nằm trong [-1.0, 1.0] (miền giá "
                f"trị của cosine), nhận được {cfg.match_threshold!r}."
            )
        if not math.isfinite(cfg.match_threshold):
            raise ConfigError(
                "'face.match_threshold' phải hữu hạn, nhận được "
                f"{cfg.match_threshold!r}."
            )

    if cfg.enabled is None:
        # Tự động: chưa có ngưỡng thì tắt, có rồi thì bật.
        cfg.enabled = cfg.match_threshold is not None
    elif cfg.enabled and cfg.match_threshold is None:
        raise ConfigError(
            "'face.enabled' là true nhưng 'face.match_threshold' đang null. "
            "Ngưỡng nhận diện phải được ĐO trên dữ liệu thật của dự án rồi "
            "điền vào (spec V3 §5.13, §14 bước H) — không dùng ngưỡng mặc "
            "định. Hoặc điền 'face.match_threshold', hoặc đặt "
            "'face.enabled: false'."
        )
    return cfg


def _parse_web(raw: Any) -> WebConfig:
    data = _as_dict(raw, "web")
    cfg = WebConfig(
        host=_get_str(data, "host", WebConfig.host, "web"),
        port=_get_int(data, "port", WebConfig.port, "web"),
        stream_enabled=_get_bool(
            data, "stream_enabled", WebConfig.stream_enabled, "web"
        ),
    )
    if not 0 < cfg.port < 65536:
        raise ConfigError("'web.port' phải nằm trong khoảng 1..65535.")
    return cfg


# --------------------------------------------------------------------------
# Cú pháp nguồn camera
# --------------------------------------------------------------------------

#: Mẫu thông tin đăng nhập trong URL: ``scheme://user:pass@...``.
#: Cố ý khớp **mọi** scheme, không chỉ ``rtsp``: thông điệp lỗi cũng phải che
#: một URL sai scheme (``rtsp:http://user:pass@host``) hoặc URL lẫn trong nguồn
#: không nhận ra.
#:
#: ``userinfo`` dùng ``[^/]*`` **greedy** chứ không phải ``[^/@]*``: mật khẩu
#: hợp lệ có thể chứa ``@`` (``pa@ss``), và ``[^/@]*`` chỉ ăn tới ``@`` đầu
#: tiên nên phần đuôi mật khẩu lọt ra ngoài chuỗi đã che. Với ``[^/]*``,
#: greedy bắt tới ``@`` **cuối** trong authority — đúng ranh giới userinfo/địa
#: chỉ, vì ``@`` không được phép xuất hiện trong phần host của URL.
_URL_USERINFO = re.compile(
    r"(?P<scheme>[A-Za-z][A-Za-z0-9+.\-]*://)(?P<userinfo>[^/]*)@"
)

#: Chuỗi thay cho user/mật khẩu khi đưa nguồn ảnh vào log hoặc thông điệp lỗi.
REDACTED = "***"

#: Tiền tố loại nguồn hợp lệ đầu cú pháp ``camera.source``. Dùng để phân biệt
#: "người dùng đã ghi tiền tố" với "URL RTSP trần" ở biến môi trường.
#: Phải yêu cầu dấu ``:`` **và** loại trừ ``://`` — nếu chỉ dùng
#: ``^(?:usb|file|rtsp|rtsps|picamera)\b`` thì chính URL trần ``rtsp://...``
#: cũng khớp (biên từ nằm giữa ``p`` và ``:``) và sẽ không được thêm tiền tố.
_SOURCE_PREFIX = re.compile(r"^(?:usb|file|rtsp|rtsps):(?!//)")


def redact_camera_source(source: object) -> str:
    """Che user/mật khẩu trong URL RTSP trước khi đưa ra log hay thông điệp lỗi.

    URL camera IP chứa mật khẩu thật, nên đây là bản duy nhất được phép xuất
    hiện trong log, thông điệp lỗi và ``ConfigError``.

    >>> redact_camera_source("rtsp://admin:matkhau@192.168.1.50:554/1/2")
    'rtsp://***:***@192.168.1.50:554/1/2'
    >>> redact_camera_source("rtsp://192.168.1.50:554/1/2")
    'rtsp://192.168.1.50:554/1/2'
    """
    text = source if isinstance(source, str) else repr(source)

    def _hide(match: re.Match[str]) -> str:
        userinfo = match.group("userinfo")
        hidden = REDACTED if ":" not in userinfo else f"{REDACTED}:{REDACTED}"
        return f"{match.group('scheme')}{hidden}@"

    return _URL_USERINFO.sub(_hide, text)


def onvif_password() -> str:
    """Mật khẩu ONVIF, đọc từ biến môi trường :data:`ONVIF_PASSWORD_ENV`.

    Đọc tại thời điểm gọi (không cache vào dataclass) để mật khẩu không bao
    giờ nằm trong ``repr(config)``, log hay file cấu hình được commit. Trả
    chuỗi rỗng khi biến chưa được đặt.
    """
    return os.environ.get(ONVIF_PASSWORD_ENV, "").strip()


def parse_camera_source(source: str) -> tuple[str, int | str | None]:
    """Tách ``camera.source`` thành ``(loại, tham số)``.

    Cú pháp hợp lệ (spec v2 §5.1):

    - ``usb:0``        → ``("usb", 0)``
    - ``picamera``     → ``("picamera", None)``
    - ``file:a.mp4``   → ``("file", "a.mp4")``
    - ``rtsp:rtsp://user:matkhau@host:554/1/2``
                       → ``("rtsp", "rtsp://user:matkhau@host:554/1/2")``

    Đường dẫn file và URL RTSP được giữ nguyên phần sau dấu ``:`` đầu tiên,
    nên đường dẫn Windows (``file:C:\\video\\a.mp4``) và URL có ``:`` trong
    thông tin đăng nhập lẫn cổng (``rtsp://user:pass@host:554/...``) vẫn đọc
    đúng.

    Raises:
        ConfigError: cú pháp không hợp lệ. Thông điệp đã che thông tin đăng
            nhập của URL RTSP (xem :func:`redact_camera_source`).
    """
    safe = redact_camera_source(source)

    if not isinstance(source, str) or not source.strip():
        raise ConfigError("'camera.source' phải là chuỗi không rỗng.")

    text = source.strip()
    if text == "picamera":
        return "picamera", None

    if ":" not in text:
        raise ConfigError(
            f"'camera.source' = {safe!r} không hợp lệ. Dùng 'usb:N', "
            "'picamera', 'file:duong_dan.mp4' hoặc 'rtsp:rtsp://...'."
        )

    kind, _, value = text.partition(":")
    kind = kind.strip().lower()
    value = value.strip()

    if kind == "usb":
        try:
            index = int(value)
        except ValueError as exc:
            raise ConfigError(
                f"'camera.source' = {safe!r}: chỉ số USB phải là số nguyên."
            ) from exc
        if index < 0:
            raise ConfigError(
                f"'camera.source' = {safe!r}: chỉ số USB không được âm."
            )
        return "usb", index

    if kind == "file":
        if not value:
            raise ConfigError(
                f"'camera.source' = {safe!r}: thiếu đường dẫn file."
            )
        return "file", value

    if kind == "rtsp":
        if not value:
            raise ConfigError(
                f"'camera.source' = {safe!r}: thiếu URL RTSP sau 'rtsp:'."
            )
        if not value.lower().startswith(("rtsp://", "rtsps://")):
            raise ConfigError(
                f"'camera.source' = {safe!r}: URL RTSP phải bắt đầu bằng "
                "'rtsp://' hoặc 'rtsps://'."
            )
        return "rtsp", value

    raise ConfigError(
        f"'camera.source' = {safe!r}: loại {kind!r} không được hỗ trợ. "
        "Dùng 'usb:N', 'picamera', 'file:duong_dan.mp4' hoặc "
        "'rtsp:rtsp://...'."
    )


# --------------------------------------------------------------------------
# API công khai
# --------------------------------------------------------------------------


def load_config(path: str | Path = "config.yaml") -> Config:
    """Nạp và kiểm tra file cấu hình YAML.

    Raises:
        FileNotFoundError: khi file không tồn tại.
        ConfigError: khi YAML hỏng, gốc không phải ánh xạ, hoặc một khóa sai
            kiểu/sai giá trị.
    """
    config_path = Path(path)
    if not config_path.is_file():
        raise FileNotFoundError(
            f"Không tìm thấy file cấu hình: {config_path.resolve()}. "
            "Hãy tạo config.yaml (xem config.yaml mẫu trong repo) hoặc "
            "truyền --config đường_dẫn."
        )

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(
            f"File cấu hình '{config_path}' không phải YAML hợp lệ: {exc}"
        ) from exc
    except OSError as exc:
        raise ConfigError(
            f"Không đọc được file cấu hình '{config_path}': {exc}"
        ) from exc

    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConfigError(
            f"Gốc của '{config_path}' phải là ánh xạ (các mục camera, model, "
            f"...), nhận được {type(raw).__name__}."
        )

    return Config(
        camera=_parse_camera(raw.get("camera")),
        model=_parse_model(raw.get("model")),
        tracking=_parse_tracking(raw.get("tracking")),
        phone=_parse_phone(raw.get("phone")),
        thresholds=_parse_thresholds(raw.get("thresholds")),
        timing=_parse_timing(raw.get("timing")),
        alerts=_parse_alerts(raw.get("alerts")),
        hardware=_parse_hardware(raw.get("hardware")),
        sensors=_parse_sensors(raw.get("sensors")),
        presence=_parse_presence(raw.get("presence")),
        storage=_parse_storage(raw.get("storage")),
        web=_parse_web(raw.get("web")),
        face=_parse_face(raw.get("face")),
        schedule=_parse_schedule(raw.get("schedule")),
        posture_labels_enabled=_get_bool(
            raw, "posture_labels_enabled", Config.posture_labels_enabled, ""
        ),
        path=str(config_path),
    )
