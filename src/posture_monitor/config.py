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

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

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
    """Điều khiển PTZ qua ONVIF (tuỳ chọn, mặc định tắt).

    **Không có trường mật khẩu.** Mật khẩu đọc từ biến môi trường
    :data:`ONVIF_PASSWORD_ENV` qua :func:`onvif_password`, nên ``repr`` của
    cấu hình, log và ``config.yaml`` (file được commit) không bao giờ chứa nó.
    """

    enabled: bool = False
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
    thresholds: ThresholdsConfig = field(default_factory=ThresholdsConfig)
    timing: TimingConfig = field(default_factory=TimingConfig)
    alerts: AlertsConfig = field(default_factory=AlertsConfig)
    hardware: HardwareConfig = field(default_factory=HardwareConfig)
    sensors: SensorsConfig = field(default_factory=SensorsConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    web: WebConfig = field(default_factory=WebConfig)

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


def _parse_onvif(raw: Any) -> OnvifConfig:
    """Nạp mục ``camera.onvif`` (tuỳ chọn; thiếu mục = tắt).

    Mật khẩu **không** đọc từ YAML. Khi ``enabled: true`` mà biến môi trường
    :data:`ONVIF_PASSWORD_ENV` chưa được đặt, báo lỗi ngay lúc nạp cấu hình
    thay vì để route ``/api/ptz`` hỏng lần đầu có người bấm nút. Thông điệp
    chỉ nêu **tên biến môi trường**, không bao giờ chứa giá trị mật khẩu, và
    mọi chỗ chèn ``host`` đều đi qua :func:`redact_camera_source`.
    """
    data = _as_dict(raw, "camera.onvif")
    cfg = OnvifConfig(
        enabled=_get_bool(data, "enabled", OnvifConfig.enabled, "camera.onvif"),
        host=_get_str(data, "host", OnvifConfig.host, "camera.onvif"),
        port=_get_int(data, "port", OnvifConfig.port, "camera.onvif"),
        user=_get_str(data, "user", OnvifConfig.user, "camera.onvif"),
    )
    if not 0 < cfg.port < 65536:
        raise ConfigError("'camera.onvif.port' phải nằm trong khoảng 1..65535.")
    if cfg.enabled:
        safe_host = redact_camera_source(cfg.host)
        if not cfg.host.strip():
            raise ConfigError(
                "'camera.onvif.enabled' là true nhưng 'camera.onvif.host' "
                "đang trống. Điền địa chỉ camera IP (ví dụ 192.168.1.50)."
            )
        if not onvif_password():
            raise ConfigError(
                "'camera.onvif.enabled' là true nhưng chưa có mật khẩu ONVIF "
                f"cho camera {safe_host!r}. Đặt biến môi trường "
                f"{ONVIF_PASSWORD_ENV} (mật khẩu không được ghi vào "
                "config.yaml)."
            )
    return cfg


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
    )


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
        thresholds=_parse_thresholds(raw.get("thresholds")),
        timing=_parse_timing(raw.get("timing")),
        alerts=_parse_alerts(raw.get("alerts")),
        hardware=_parse_hardware(raw.get("hardware")),
        sensors=_parse_sensors(raw.get("sensors")),
        storage=_parse_storage(raw.get("storage")),
        web=_parse_web(raw.get("web")),
        path=str(config_path),
    )
